# -*- coding: utf-8 -*-
"""
blender_efx/sim_preview.py  —  粒子模拟播放器（modal 时钟 + gpu 绘制，零场景对象）

定位
----
`efx_format/sim`（零 bpy）负责算，本模块只负责三件事：

  1. **喂数据**：从**正在编辑的属性树**拼 `[(type_hash, fields_dict)]`——不是从
     上次保存的文件读，否则预览看到的不是你刚改的值。
  2. **时钟**：modal + `wm.event_timer_add`，自带播放/循环/倍速，**不碰
     `scene.frame_current`**，与时间轴完全解耦。
  3. **绘制**：`SpaceView3D.draw_handler_add(POST_VIEW)` 直接画，**不建任何场景对象**
     ——没有标记、没有孤儿、不污染 undo 栈（session_core 那一整套在这里用不上）。

为什么不走 mesh + 几何节点
--------------------------
用户明确「不要求在 3D View、不要求拖时间轴」之后，场景对象那条路的代价（生命周期
管理 + GN 建图 + frame_change 耦合 + EEVEE 没有加法混合）就全都没必要付了。直接
gpu 绘制还顺带把加法混合白拿了：`gpu.state.blend_set('ADDITIVE')` 一行，比 EEVEE
（4.2+ 只剩 Dithered/Blended 两种 Render Method）能做到的更准。

骨架照搬 `uvs_io.py`（`wm.window_new` + `draw_handler_add` + modal 管生命周期），
那套在本仓库已经跑通过。

⚠ 本文件尚未在 Blender 里跑过
-----------------------------
写它的环境没有 Blender。逻辑层（efx_format/sim）有 74 条单测护着，但下面这些
bpy 侧的东西必须实机验一遍：

  - `gpu.shader.from_builtin` 的名字：4.0+ 是 'FLAT_COLOR'，3.x 是 '3D_FLAT_COLOR'。
    `_builtin()` 两个都试。（顺带一提 uvs_io.py:766 直接写死了 4.0+ 的名字，
    如果那边 3.6 确实报错，把 `_builtin` 提出去共用即可。）
  - `gpu.state.blend_set('ADDITIVE')` 是否如预期。
  - **不要**用 `gpu.types.GPUShader(vert_src, frag_src)` 字符串构造器：3.4 起废弃、
    5.0 移除，且 Vulkan 后端（5.x 默认）下不工作。本模块只用 builtin shader，
    真要自定义 shader 走 `gpu.shader.create_from_info`。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层，不改 efx_format/。
"""

import base64
import math
import time

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       IntVectorProperty)
from bpy.types import Operator, Panel

from .i18n import T
from . import root_collection as _rc

_DRAW_TAG = "~EFX_SIM_PREVIEW"      # draw handler 识别用（跨热重载按名移除）


# ─────────────────────────────────────────────────────────────────────────────
# 播放器状态
#
# 这里用模块级 dict 是**合理的**（对比 session_core 的教条）：本模块不产生任何
# 场景数据，没有「场景里的残留物要清理」的问题。真相源就是 draw handler 在不在、
# modal 在不在——两者都由本 dict 持有并由算子成对管理。
# ─────────────────────────────────────────────────────────────────────────────

_P = {
    # 每个被选中的 entry 一条 track（**多选同时模拟**）：
    #   {"sim", "entry_name", "ref_rows", "items", "image", "uvs"}
    # 一条 track 自带参考矩阵和渲染产物——多个 entry 各自摆在自己的位置上，
    # 共享的只有时钟（同一个累加器 → 天然同步，不会各跑各的帧）。
    "tracks": [],
    "playing": False,
    "acc": 0.0,           # 帧累加器（浮点，只走整数帧）
    "last_t": 0.0,        # 上次 tick 的墙钟
    "duration": 0,        # 本次「播放一次」的长度（帧）= 各 track 里最长的那个
    "handler": None,
    "timer": None,
    "dirty": False,       # 属性被编辑过 → 下个 tick 重建
    "error": "",
    "mesh_cache": {},     # 绑定网格 → 游戏坐标系下的三角顶点（按网格名，全局共享）
    "cam_fwd": None,      # 上一帧的视线方向（Blender 世界系），由 _draw 缓存
}


def tracks():
    return _P["tracks"]


def primary_track():
    """第一条 track。面板显示帧号/取单条信息时用它代表整体（时钟是共享的）。"""
    return _P["tracks"][0] if _P["tracks"] else None



def is_active():
    return _P["handler"] is not None


def is_playing():
    return _P["playing"] and is_active()


# ─────────────────────────────────────────────────────────────────────────────
# 属性树 → 模拟器输入
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_entry(obj):
    """从当前活动对象往上找 EFX_ENTRY。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ENTRY":
            return cur
        cur = cur.parent
    return None


def _entry_attributes(entry_obj):
    """entry 下的 EFX_ATTRIBUTE 子对象，按 efx_index 排序（= 文件里的顺序）。"""
    out = [o for o in bpy.data.objects
           if o.parent is entry_obj and o.get("~TYPE") == "EFX_ATTRIBUTE"]
    out.sort(key=lambda o: int(o.get("efx_index", 0)))
    return out


def _block_fields(blk_obj):
    """一个属性块 → (type_hash, fields_dict)，**反映未保存的编辑**。

    走导出同一条路：`fields.get_attribute_data_bytes` 按当前属性树重建字节，
    再用 `AttrBlock.decode()` 解成 dict。复用已经被往返测试盖住的路径，比另写
    一套「property → dict」的读法可靠得多（后者要重复处理十几种值槽）。
    opaque 块或重建异常 → 回退到自定义属性里的原始字节。
    """
    from ..efx_format.efxfile import AttrBlock

    try:
        type_hash = int(blk_obj.efx_block.type_hash_str)
    except Exception:
        return None

    data = None
    try:
        from . import fields as _fields
        data = _fields.get_attribute_data_bytes(blk_obj)
    except Exception:
        data = None
    if data is None:
        try:
            data = base64.b64decode(str(blk_obj["data_bytes"]))
        except Exception:
            return None

    try:
        decoded = AttrBlock(type_hash, data).decode()
    except Exception:
        decoded = None
    return (type_hash, decoded if decoded is not None else {})


#: entry 名 → UVSEQUENCE 属性对象名。找宿主要扫一遍 bpy.data.objects，而面板每次
#: 重绘都要报「帧表从哪来」——不缓存就是每帧一次全场景扫描（见记忆
#: onchange-full-scene-scan-perf-bug）。缓存只存名字，取用时再查一次对象是否还在。
_UVS_HOST_CACHE = {}


def _uvs_host(entry_obj, use_cache=False):
    """entry 下的 UVSEQUENCE 属性对象；没有则 None。

    全语料 10084 个官方文件里一个 entry 最多一个 UVSEQUENCE（84106 个有的 entry
    全是 1 个），所以「取第一个」不是将就，就是全部。
    """
    from ..efx_format.hashes import UVSEQUENCE

    if use_cache and entry_obj.name in _UVS_HOST_CACHE:
        name = _UVS_HOST_CACHE[entry_obj.name]
        obj = bpy.data.objects.get(name) if name else None
        if name == "" or (obj is not None and obj.parent is entry_obj):
            return obj

    found = None
    for blk in _entry_attributes(entry_obj):
        try:
            if int(blk.efx_block.type_hash_str) == UVSEQUENCE:
                found = blk
                break
        except Exception:
            continue
    _UVS_HOST_CACHE[entry_obj.name] = found.name if found is not None else ""
    return found


def _uvs_info(host):
    """UVSEQUENCE 宿主 → 面板展示信息（只读属性，便宜，可每次重绘调）。"""
    if host is None:
        return None
    info = {"host": host.name, "file": "", "groups": 0, "loaded": False}
    props = getattr(host, "efx_uvs", None)
    if props is not None and getattr(props, "is_loaded", False):
        info["file"] = bpy.path.basename(props.filepath) or "(uvs)"
        info["groups"] = len(props.groups)
        info["loaded"] = bool(props.raw_b64)
    return info


def _uvs_state(entry_obj):
    """(SimResources, 展示信息 dict)。

    序列帧的真实矩形在 `.uvs` 里，属性里只有游戏相对路径——所以这里读的是**用户
    在该属性上手动载入的那份**（uvs_io.py 的导入按钮，存在 `obj.efx_uvs.raw_b64`）。
    没载入就交空资源，核心会退到网格兜底并 note 一条（预览不静默撒谎）。
    """
    from ..efx_format.sim import SimResources

    host = _uvs_host(entry_obj)
    info = _uvs_info(host)
    if info is None or not info["loaded"]:
        return SimResources(), info
    try:
        data = base64.b64decode(host.efx_uvs.raw_b64)
    except Exception:
        data = b""
        info["loaded"] = False
    return SimResources(data), info


def _entry_timl_bytes(entry_obj):
    try:
        return base64.b64decode(str(entry_obj.get("timl_bytes", "")))
    except Exception:
        return b""


def _config_from_scene(scene):
    """场景属性 → SimConfig。待标定项全在这儿落地成开关。"""
    from ..efx_format.sim import SimConfig

    return SimConfig(
        seed=int(getattr(scene, "efx_sim_seed", 0)),
        jitter_mode=getattr(scene, "efx_sim_jitter_mode", "onesided"),
        a0_sample=getattr(scene, "efx_sim_a0_sample", "spawn"),
        timl_mode=getattr(scene, "efx_sim_timl_mode", "replace"),
        timl_interp=getattr(scene, "efx_sim_timl_interp", "native"),
        life_model=getattr(scene, "efx_sim_life_model", "sum"),
        age_during_delay=bool(getattr(scene, "efx_sim_age_during_delay", False)),
        es3d_range_mode=getattr(scene, "efx_sim_es3d_range", "shell"),
        rot_order_applied=getattr(scene, "efx_sim_rot_order", "forward"),
        ribbon_length_mode=getattr(scene, "efx_sim_ribbon_length", "per_segment"),
        parent_release_clock=getattr(scene, "efx_sim_parent_clock", "particle_age"),
        color_range_mode=getattr(scene, "efx_sim_color_range", "channel"),
        t3d_velocity_unit=getattr(scene, "efx_sim_t3d_vel_unit", "per_second"),
        spawn_interval_jitter=getattr(scene, "efx_sim_spawn_jitter", "per_burst"),
        t3d_rotation_sign=getattr(scene, "efx_sim_t3d_rot_sign", "flip"),
        rgb_tint_mode=getattr(scene, "efx_sim_rgb_tint", "weighted"),
        uvs_speed_unit=getattr(scene, "efx_sim_uvs_speed_unit", "per_frame"),
        uvs_once_span=getattr(scene, "efx_sim_uvs_once_span", "to_end"),
        uvs_start_wrap=getattr(scene, "efx_sim_uvs_start_wrap", "wrap"),
        uvs_grid_h=int(getattr(scene, "efx_sim_uvs_grid", (8, 8))[0]),
        uvs_grid_v=int(getattr(scene, "efx_sim_uvs_grid", (8, 8))[1]),
    )


def build_simulator(entry_obj, scene, out=None):
    """按当前属性树建一个新的 Simulator。失败返回 None 并把原因写进 _P['error']。

    `out` 给了就往里写 `{"uvs": 帧表来源信息}`——面板要显示「帧表从哪来」，而那个
    信息是建资源时顺带算出来的，不想为它再扫一遍属性树。
    """
    from ..efx_format.sim import Simulator

    blocks = []
    for blk in _entry_attributes(entry_obj):
        pair = _block_fields(blk)
        if pair is not None:
            blocks.append(pair)
    if not blocks:
        _P["error"] = T("sim.err_no_attributes")
        return None

    resources, uvs_info = _uvs_state(entry_obj)
    if out is not None:
        out["uvs"] = uvs_info
    try:
        sim = Simulator(blocks, _entry_timl_bytes(entry_obj),
                        _config_from_scene(scene), resources)
    except Exception as exc:
        _P["error"] = str(exc)
        return None
    _P["error"] = ""
    return sim


def _uvs_image_name(entry_obj):
    """这个 entry 的序列帧大图（UVSEQUENCE 属性上绑的参考图名）；没有则 ""。

    一个 entry 最多一个 UVSEQUENCE（全语料 84106/84106），所以「一 entry 一张图」
    成立，绘制时按图分桶即可。图是 uvs_link 的链式载入或用户手选填进去的。
    """
    host = _uvs_host(entry_obj, use_cache=True)
    if host is None:
        return ""
    try:
        name = host.efx_uvs.ref_image_name or ""
    except Exception:
        return ""
    return name if name in bpy.data.images else ""


def _attributes_by_entry():
    """一次遍历建 {entry 对象 → [属性对象(按 efx_index)]}。

    **不要**按 entry 逐个调 `_entry_attributes`：那是 O(entry 数 × 场景对象数)，
    多文件场景下就是记忆里那个导入退化到分钟级的坑（onchange-full-scene-scan-perf-bug）。
    """
    out = {}
    for o in bpy.data.objects:
        if o.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        parent = o.parent
        if parent is None:
            continue
        out.setdefault(parent, []).append(o)
    for lst in out.values():
        lst.sort(key=lambda o: int(o.get("efx_index", 0)))
    return out


def _action_table(root_col):
    """{action 段下标 → [ActionTarget]}。

    下标就是 EFX_ACTION 在段里的局部顺序（`collect_top_level` 已按 efx_index 排序），
    与 PTLIFE.relationIndex 同一套编号。目标 entry 走已有的对象指针
    （`action_emitter.py` 的 targets[].body_ptr），Size/Position 取那两个实机确认的字段。
    """
    from ..efx_format.sim import ActionTarget
    from ..efx_format.sim.state import Vec3

    table = {}
    playefx = False
    for ai, act in enumerate(_rc.collect_top_level(root_col, "EFX_ACTION")):
        targets = []
        props = getattr(act, "efx_play", None)
        for entry in (getattr(props, "entries", None) or ()):
            if not getattr(entry, "is_emitter", False):
                playefx = True
                continue
            size = Vec3(*tuple(entry.xyz)) if len(entry.xyz) >= 3 else None
            pos = (Vec3(*tuple(entry.em_position))
                   if len(entry.em_position) >= 3 else None)
            for t in (getattr(entry, "targets", None) or ()):
                tgt = getattr(t, "body_ptr", None)
                if tgt is None:
                    continue
                targets.append(ActionTarget(tgt.name,
                                            size.copy() if size else None,
                                            pos.copy() if pos else None))
        table[ai] = targets
    return table, playefx


def _reachable_entries(root_entry, action_table, attrs_by_entry, max_depth):
    """根 entry + 它经 PTLIFE/ACTION 能到的那些 entry（别给整份文件都建模板）。"""
    from ..efx_format.hashes import PTLIFE

    def _relation_indices(entry_obj):
        out = []
        for blk in attrs_by_entry.get(entry_obj, ()):
            try:
                if int(blk.efx_block.type_hash_str) != PTLIFE:
                    continue
            except Exception:
                continue
            pair = _block_fields(blk)
            if pair:
                # ⚠ 别写成 `... or -1`：**relationIndex 0 是合法值而且是最常见的那个**
                # （全语料 8904 块里 4192 个是 0），0 被 `or` 判成假就整条链断掉。
                raw = (pair[1] or {}).get("relationIndex", -1)
                ri = -1 if raw is None else int(raw)
                if ri >= 0:
                    out.append(ri)
        return out

    seen = {root_entry.name: root_entry}
    frontier = [(root_entry, 0)]
    while frontier:
        obj, depth = frontier.pop()
        if depth >= max_depth:
            continue
        for ri in _relation_indices(obj):
            for target in action_table.get(ri, ()):
                nxt = bpy.data.objects.get(target.entry_key)
                if nxt is None or nxt.name in seen:
                    continue
                seen[nxt.name] = nxt
                frontier.append((nxt, depth + 1))
    return seen


def build_track(entry_obj, scene):
    """建一条 track。

    track 里的 `sim` 是一个 **SimScene**（实例树）：根是选中的 entry，PTLIFE 触发的
    ACTION 会在树上长出子实例。SimScene 与 Simulator 鸭子兼容（frame/particles/
    step/build_render/unsupported/notes/config/em/suggested_duration），所以时钟、
    绘制、面板那几段都不用分情况。失败返回 None。
    """
    from ..efx_format.sim import EntryTemplate, SimScene

    root_col = _rc.find_root_collection(entry_obj)
    attrs_by_entry = _attributes_by_entry()
    action_table, has_playefx = ({}, False)
    if root_col is not None:
        action_table, has_playefx = _action_table(root_col)

    cfg = _config_from_scene(scene)
    entries = _reachable_entries(entry_obj, action_table, attrs_by_entry,
                                 max(1, int(cfg.max_spawn_depth)))

    templates = {}
    resources = {}
    images = {}
    root_uvs_info = None
    for name, obj in entries.items():
        blocks = []
        for blk in attrs_by_entry.get(obj, ()):
            pair = _block_fields(blk)
            if pair is not None:
                blocks.append(pair)
        if not blocks:
            continue
        templates[name] = EntryTemplate(name, blocks, _entry_timl_bytes(obj))
        res, info = _uvs_state(obj)
        resources[name] = res
        images[name] = _uvs_image_name(obj)
        if obj is entry_obj:
            root_uvs_info = info

    if entry_obj.name not in templates:
        _P["error"] = T("sim.err_no_attributes")
        return None

    try:
        sim = SimScene(templates, action_table, root_key=entry_obj.name, config=cfg,
                       resources_for=resources.get)
    except Exception as exc:
        _P["error"] = str(exc)
        return None
    _P["error"] = ""
    if has_playefx:
        sim.note("Action 里有 PLAYEFX（调用外部 .efx）未模拟")

    return {
        "sim": sim,
        "entry_name": entry_obj.name,
        # 用**播放起点**的矩阵并固定下来：发射器之后的移动经 host_origin 进模拟，
        # 绘制再用当前矩阵就会把同一段位移算两遍。
        "ref_rows": _entry_matrix_rows(entry_obj),
        "items": [],
        "image": images.get(entry_obj.name, ""),
        #: entry 名 → 序列帧大图名。一棵树里每个 entry 各有各的图，绘制时按
        #: item.extra['entry_key'] 查（见 _collect_track）。
        "images": images,
        "uvs": root_uvs_info,          # 帧表来源（真 .uvs / 网格兜底），面板显示用
    }


def rebuild_track(tr, scene, keep_frame=True):
    """就地重建一条 track（改了字段/标定开关之后）。成功返回 True。"""
    entry = bpy.data.objects.get(tr["entry_name"])
    if entry is None:
        return False
    frame = tr["sim"].frame if (keep_frame and tr["sim"] is not None) else -1
    new = build_track(entry, scene)
    if new is None:
        return False
    if 0 <= frame <= _REBUILD_CATCHUP_MAX:
        try:
            new["sim"].run_to(frame)
        except Exception as exc:
            _P["error"] = str(exc)
    tr.update(new)
    return True


def collect_entries(context):
    """要模拟哪些 entry：**所有选中对象**各自往上找 entry，去重；空则退回活动对象。

    多选同时模拟就落在这里——用户选几个 entry（或它们下面的任意属性）就播几个。
    """
    out = []
    seen = set()
    for obj in list(getattr(context, "selected_objects", None) or ()):
        e = _resolve_entry(obj)
        if e is not None and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    if not out:
        e = _resolve_entry(context.active_object)
        if e is not None:
            out.append(e)
    return out



def invalidate_if_active(obj=None):
    """字段被编辑 → 下个 tick 重建模拟器。fields.py 的编辑回调调用本函数。

    刻意只置一个标志：编辑回调是**每改一个字段就触发一次**的热路径，在里面重建
    整个模拟器会卡。真正的重建推迟到定时器 tick（见 `_tick`）。
    """
    if is_active():
        _P["dirty"] = True


# ─────────────────────────────────────────────────────────────────────────────
# 坐标换算（游戏 → Blender）
#
# 与 transform_sync.game_loc_to_blender 同一套：/100 + (X,Y,Z)→(X,-Z,Y)。
# 核心层全程用游戏坐标，换算只在这里发生一次。
# ─────────────────────────────────────────────────────────────────────────────

_UNIT = 1.0 / 100.0


def _display_color(c, mode):
    """HDR 的渲染项颜色 → 能画进 LDR 帧缓冲的颜色。

    `BILLBOARD3D.brightness` 是个 HDR 强度，不是 0~1 的倍率：全语料中位 1.5、90% 到
    49.25、最大 255，**39% 的块 >1.5**。

    用户在 test.efx 上做的受控扫描（alpha=1、纯红、暗背景、逐个改 brightness，
    读出的屏幕色解到线性）把机制定死了：

        Alpha 混合   红恒为 0.1046，**与 brightness 完全无关**
        Add 混合     亮度 1 → 0.1046   10 → 0.982   100 → 0.982
                     即 emitted = 0.1046 × 亮度，然后**硬夹取**（不是软过渡：
                     Reinhard 在亮度 10 处只给 0.51、1-exp 给 0.65，都对不上 0.982）

    那个 0.1046 是贴图在取样点上的值。⚠ **别据此以为「有贴图就可以照实夹取」**：
    贴图是 shader 在这一步**之后**才乘的（`clip(tex × col)`，不是 `tex × clip(col)`），
    所以 'raw' 下 col 早就被夹成白的了，贴图再乘也救不回来。游戏那边不全白靠的是
    tone map + 自动曝光，我们没有这两样——所以预览必须自己把色相保下来。

      'preserve_hue'（默认）除以最大分量保住色相，超出的倍数折进不透明度。有贴图时
                     shader 再乘上去，得到 tex × 作者调的那个颜色，亮度正常。
      'tonemap'      Reinhard c/(1+c)。⚠ 与实测不符（受控扫描证明是硬夹取），留作对照
      'raw'          直接夹取：与「单个像素」的实机行为一致，但少了 tone map/自动曝光，
                     brightness 一大就整片白
    """
    r, g, b, a = c[0], c[1], c[2], c[3]
    if mode == "raw":
        return (r, g, b, a)
    if mode == "tonemap":
        return (r / (1.0 + r), g / (1.0 + g), b / (1.0 + b), a)
    m = max(r, g, b)
    if m <= 1.0:
        return (r, g, b, a)
    return (r / m, g / m, b / m, min(1.0, a * m))


def _to_blender(v):
    return (v.x * _UNIT, -v.z * _UNIT, v.y * _UNIT)


def _axis_swap(v):
    """**方向**的坐标系换算：只换轴，不乘 `_UNIT`。

    ⚠ 位置要 ÷100（游戏单位→米），方向不能——`_to_blender` 拿来转单位向量会把它
    缩成 0.01 长，乘上半宽之后面片就小了 100 倍。PLANE 的 axis_u/axis_v 就是这么
    被缩没的（长宽 76.8 游戏单位的片画出来只有 1.2 厘米，屏幕上等于不可见）。
    """
    return (v.x, -v.z, v.y)


def _to_game(bx, by, bz):
    """_to_blender 的逆。宿主报告发射器位移时用。"""
    return (bx / _UNIT, bz / _UNIT, -by / _UNIT)


def _ref_local(rows, world_pos):
    """世界坐标点 → 参考系下的局部偏移。

    把参考系当刚体处理（`Rᵀ(p − t)`）：entry empty 上如果有非 1 的缩放，这里会
    有偏差——语料里 TRANSFORM3D.resize 恒为 1.0，先不为它引入 mathutils 依赖。
    """
    dx = world_pos[0] - rows[0][3]
    dy = world_pos[1] - rows[1][3]
    dz = world_pos[2] - rows[2][3]
    return (rows[0][0] * dx + rows[1][0] * dy + rows[2][0] * dz,
            rows[0][1] * dx + rows[1][1] * dy + rows[2][1] * dz,
            rows[0][2] * dx + rows[1][2] * dy + rows[2][2] * dz)


def _sync_track_origin(tr):
    """把 entry empty 相对**播放起点**的位移报给该 track 的模拟器。

    为什么需要：条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE 刀光）画的是发射器
    划过的轨迹。blade_trail 这类原型根本没有 VELOCITY3D——粒子自己不动，整个效果
    靠 PARENTOPTIONS 把发射器绑在挥动的武器骨骼上。宿主不把这个位移报进去，
    模拟层就永远看不到运动，刀光永远是空的。

    参考系取**播放开始那一刻**的世界矩阵并固定下来（`tr["ref_rows"]`），绘制也
    用它——这样发射器移动时，已经发出去的粒子会如实留在原地，而不是跟着整体平移。
    """
    sim = tr.get("sim")
    entry = bpy.data.objects.get(tr["entry_name"])
    rows = tr.get("ref_rows")
    if sim is None or entry is None or rows is None:
        return
    try:
        world = entry.matrix_world.translation
    except Exception:
        return
    bx, by, bz = _ref_local(rows, (world[0], world[1], world[2]))
    gx, gy, gz = _to_game(bx, by, bz)
    ho = sim.em.host_origin
    ho.x, ho.y, ho.z = gx, gy, gz


def _sync_host_origin(scene=None):
    for tr in _P["tracks"]:
        _sync_track_origin(tr)



def _entry_matrix_rows(entry_obj):
    """entry empty 的世界矩阵，拆成三行纯 float 元组。

    用**完整矩阵**而不只是位置：TRANSFORM3D 的 rotate/resize 以及 PARENTOPTIONS 的
    骨骼绑定都已经由 transform_sync.py 烘进了这个矩阵，乘上去就自动全部继承——
    模拟层因此完全不必知道骨骼、锚定这些事（见 behaviors/transform3d.py 的分工说明）。

    ⚠ 只有**位置**过这个矩阵，粒子自身的尺寸不跟着 entry 的 scale 缩放。语料里
    TRANSFORM3D.resize 恒为 1.0，区分不出来；真遇到非 1 的再定。
    """
    try:
        m = entry_obj.matrix_world
        return ((m[0][0], m[0][1], m[0][2], m[0][3]),
                (m[1][0], m[1][1], m[1][2], m[1][3]),
                (m[2][0], m[2][1], m[2][2], m[2][3]))
    except Exception:
        return ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


def _spin(right, up, deg):
    """把相机平面内的右/上向量绕视线转 `deg` 度 —— billboard 的自转。"""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return ((right[0] * c + up[0] * s, right[1] * c + up[1] * s, right[2] * c + up[2] * s),
            (-right[0] * s + up[0] * c, -right[1] * s + up[1] * c, -right[2] * s + up[2] * c))


# ─────────────────────────────────────────────────────────────────────────────
# GPU 绘制
# ─────────────────────────────────────────────────────────────────────────────

def _builtin(name):
    """builtin shader 取名的跨版本包装。

    4.0 起 2D/3D 统一成 'FLAT_COLOR' 这样的短名，3.x 是 '3D_FLAT_COLOR'。
    先试新名、失败再试旧名，这样 3.6→5.x 同一份代码都能跑。
    """
    import gpu
    try:
        return gpu.shader.from_builtin(name)
    except Exception:
        return gpu.shader.from_builtin("3D_" + name)


def _quad_verts(center, right, up, hw, hh):
    """两个三角形拼一个面朝相机的方片。"""
    rx, ry, rz = right[0] * hw, right[1] * hw, right[2] * hw
    ux, uy, uz = up[0] * hh, up[1] * hh, up[2] * hh
    cx, cy, cz = center
    a = (cx - rx - ux, cy - ry - uy, cz - rz - uz)
    b = (cx + rx - ux, cy + ry - uy, cz + rz - uz)
    c = (cx + rx + ux, cy + ry + uy, cz + rz + uz)
    d = (cx - rx + ux, cy - ry + uy, cz - rz + uz)
    return (a, b, c, a, c, d)


def _camera_axes(rv3d):
    """视图矩阵前两行 = 世界空间下的相机右/上向量（面向相机用）。"""
    vm = rv3d.view_matrix
    right = (vm[0][0], vm[0][1], vm[0][2])
    up = (vm[1][0], vm[1][1], vm[1][2])
    return right, up


def _view_direction(rv3d):
    """视图矩阵第三行 = 相机朝向（世界空间）。条带要绕它把宽度撑开。"""
    vm = rv3d.view_matrix
    return (vm[2][0], vm[2][1], vm[2][2])


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-9:
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _uv_corners(item, flip_v, tex):
    """一个 RenderItem 的四角 UV（BL, BR, TR, TL），已处理 v 轴朝向；无贴图返回 None。

    UVSEQUENCE 写的 `uv_corners` 用的是 **.uvs 里的 v 向下**约定，而
    `gpu.texture.from_image` 取到的图第 0 行在**下**——所以默认翻一次 v。
    翻错了会整幅上下颠倒，一眼能看出来，故留一个开关（`efx_sim_uv_flip_v`）
    而不是把方向当成已知（同 uvs_io 里那处订正的教训）。
    """
    if not tex:
        return None
    c = item.uv_corners
    if not c:
        # 有贴图但这一项没有序列帧信息（比如渲染体没挂 UVSEQUENCE）→ 整张图铺满
        c = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    if flip_v:
        return tuple((u, 1.0 - v) for u, v in c)
    return tuple((float(u), float(v)) for u, v in c)


#: `_quad_verts` 的六个顶点对应的四角下标（a=BL b=BR c=TR d=TL）
_QUAD_UV_ORDER = (0, 1, 2, 0, 2, 3)


def _quad_uvs(corners):
    return tuple(corners[i] for i in _QUAD_UV_ORDER)


def _lerp2(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _emit_ribbon(verts, colors, uvs, item, col, size_mul, world_fn, view_dir,
                 corners=None, col2s=None, core=None):
    """条带 → 三角形（`uvs` 非 None 时同时产出逐顶点 UV）。

    每一段的「横向」取 `段方向 × 视线` 并归一化——这样条带永远把宽面朝向相机，
    是 Trail Renderer 的标准做法。段方向与视线平行时（正对着看）叉乘退化，
    这一段就跳过，不画烂三角。

    UV：横向铺满这一格（s: 左 0 → 右 1），纵向沿条带铺满（t: 尾 0 → 头 1），
    四角之间双线性插值——这样序列帧的翻转/90° 旋转对条带同样生效。
    """
    pts = item.points
    if not pts or len(pts) < 2:
        return
    world = [world_fn(q) for q, _hw, _a in pts]
    sides = []
    n = len(world)
    for i in range(n):
        a = world[max(0, i - 1)]
        b = world[min(n - 1, i + 1)]
        seg = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        s = _norm(_cross(seg, view_dir))
        sides.append(s)

    half = [max(1e-5, size_mul * abs(hw) * _UNIT) for _q, hw, _a in pts]
    alphas = [a for _q, _hw, a in pts]

    if uvs is not None and corners:
        bl, br, tr, tl = corners
        span = max(1, n - 1)

        def _uv(i, right_side):
            t = i / float(span)
            lo = _lerp2(bl, br, 1.0 if right_side else 0.0)
            hi = _lerp2(tl, tr, 1.0 if right_side else 0.0)
            return _lerp2(lo, hi, t)
    else:
        _uv = None

    for i in range(n - 1):
        s0, s1 = sides[i], sides[i + 1]
        if s0 is None or s1 is None:
            continue
        p0, p1 = world[i], world[i + 1]
        h0, h1 = half[i], half[i + 1]
        a0 = (col[0], col[1], col[2], col[3] * alphas[i])
        a1 = (col[0], col[1], col[2], col[3] * alphas[i + 1])

        l0 = (p0[0] - s0[0] * h0, p0[1] - s0[1] * h0, p0[2] - s0[2] * h0)
        r_0 = (p0[0] + s0[0] * h0, p0[1] + s0[1] * h0, p0[2] + s0[2] * h0)
        l1 = (p1[0] - s1[0] * h1, p1[1] - s1[1] * h1, p1[2] - s1[2] * h1)
        r_1 = (p1[0] + s1[0] * h1, p1[1] + s1[1] * h1, p1[2] + s1[2] * h1)

        verts.extend((l0, r_0, r_1, l0, r_1, l1))
        colors.extend((a0, a0, a1, a0, a1, a1))
        if col2s is not None:
            c = core if core is not None else col
            b0 = (c[0], c[1], c[2], a0[3])
            b1 = (c[0], c[1], c[2], a1[3])
            col2s.extend((b0, b0, b1, b0, b1, b1))
        if _uv is not None:
            u_l0, u_r0 = _uv(i, False), _uv(i, True)
            u_l1, u_r1 = _uv(i + 1, False), _uv(i + 1, True)
            uvs.extend((u_l0, u_r0, u_r1, u_l0, u_r1, u_l1))



#: MESH 没绑定网格时画的占位：单位立方体的 12 个三角（游戏坐标系，半边长 1）
_PLACEHOLDER_TRIS = None


def _placeholder_cube():
    global _PLACEHOLDER_TRIS
    if _PLACEHOLDER_TRIS is not None:
        return _PLACEHOLDER_TRIS
    c = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
             (0, 4, 5), (0, 5, 1), (2, 6, 7), (2, 7, 3),
             (1, 5, 6), (1, 6, 2), (0, 3, 7), (0, 7, 4)]
    _PLACEHOLDER_TRIS = [c[i] for f in faces for i in f]
    return _PLACEHOLDER_TRIS


def _mesh_tris_game(mesh_obj):
    """绑定网格的三角顶点，换算到**游戏坐标系**并缓存。

    返回 `(平坦列表, numpy 数组或 None, 逐顶点 UV 或 None)`。换算一次、缓存下来，
    之后每个粒子只要过一次仿射矩阵。numpy 那份是快路径用的（见 `_emit_mesh`），
    Blender 自带 numpy，拿不到就退回纯 Python。

    UV 来自网格自己的第一层 UVMap（mod3 导进来就带着），有它才能把材质贴图画上去——
    否则网格只能平涂一个颜色，作者调的「在贴图上染色」就完全看不出来。
    """
    uvs = None
    if mesh_obj is None:
        key, tris = "~placeholder", _placeholder_cube()
    else:
        key = mesh_obj.name
        cached = _P["mesh_cache"].get(key)
        if cached is not None:
            return cached
        try:
            me = mesh_obj.data
            me.calc_loop_triangles()
            verts = me.vertices
            uvl = me.uv_layers.active or (me.uv_layers[0] if me.uv_layers else None)
            uvdata = uvl.data if uvl is not None else None
            tris = []
            uvs = [] if uvdata is not None else None
            for tri in me.loop_triangles:
                for k, vi in enumerate(tri.vertices):
                    co = verts[vi].co
                    tris.append(_to_game(co[0], co[1], co[2]))
                    if uvs is not None:
                        u = uvdata[tri.loops[k]].uv
                        uvs.append((u[0], u[1]))
        except Exception:
            tris, uvs = _placeholder_cube(), None
    cached = _P["mesh_cache"].get(key)
    if cached is not None:
        return cached
    arr = None
    try:
        import numpy
        arr = numpy.array(tris, dtype="f4")
    except Exception:
        arr = None
    out = (tris, arr, uvs)
    _P["mesh_cache"][key] = out
    return out


def _mesh_image_name(mesh_obj):
    """绑定网格用哪张贴图。

    reference mesh 是 Model Editor 那条链导进来的，材质和贴图已经建好了——我们只要
    找出「基础色」那张图，不自己解析 mrl3。优先顺着 Principled BSDF 的 Base Color
    连线找；找不到就退回第一张**不是法线贴图**的图（法线图命名以 `_NM` 结尾）。
    多材质槽的网格只取第一张：我们一个网格只画一个桶。
    """
    if mesh_obj is None:
        return ""
    for slot in getattr(mesh_obj, "material_slots", ()):
        mat = slot.material
        if mat is None or not getattr(mat, "use_nodes", False):
            continue
        nodes = mat.node_tree.nodes
        for nd in nodes:
            if nd.type != "BSDF_PRINCIPLED":
                continue
            inp = nd.inputs.get("Base Color")
            for link in (inp.links if inp is not None else ()):
                src = link.from_node
                if src.type == "TEX_IMAGE" and src.image is not None:
                    return src.image.name
        for nd in nodes:
            if nd.type == "TEX_IMAGE" and nd.image is not None                     and not nd.image.name.upper().endswith(("_NM.DDS", "_NM.TEX")):
                return nd.image.name
    return ""


def _mat3_mul(a, b):
    """3×3 × 3×3。就三行，不值得为它引依赖。"""
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
             for j in range(3)] for i in range(3)]


def _mesh_affine(item, size_mul, rows):
    """把「逐轴缩放 → 欧拉旋转 → 平移 → 游戏坐标转 Blender → 参考矩阵」压成一个 3×4。

    这是网格能画得动的关键：原来每个顶点都要调一次 `rotate_euler`（每次重算三角
    函数）再过一次矩阵，1 万面的网格配 1 个粒子就要 58 ms。现在每个**粒子**算一次
    矩阵，每个顶点只剩 9 乘 9 加。

    返回 `(L, T)`：world = L·v + T，L 是 3×3、T 是 3 元组。
    """
    from ..efx_format.sim.vecmath import rotate_euler
    from ..efx_format.sim.state import Vec3

    r0, r1, r2 = rows
    rot = item.extra.get("rot")
    order = item.extra.get("rot_order", "XYZ")
    sx = size_mul * item.size.x
    sy = size_mul * item.size.y
    sz = size_mul * item.size.z

    def rot3():
        """欧拉角 → 3×3。把三个基向量各转一次得到，走 `rotate_euler` 而不是另写一份
        公式，保证与别处（V3D/ES3D）用的是同一套顺序与手性。"""
        e = [rotate_euler(Vec3(*b), rot.x, rot.y, rot.z, order=order)
             for b in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
        return [[e[0].x, e[1].x, e[2].x],
                [e[0].y, e[1].y, e[2].y],
                [e[0].z, e[1].z, e[2].z]]

    scl = [[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, sz]]
    turning = rot is not None and (rot.x or rot.y or rot.z)
    # 游戏 → Blender：(x, -z, y) × _UNIT（与 _to_blender 同一式子）
    au = [[_UNIT, 0.0, 0.0], [0.0, 0.0, -_UNIT], [0.0, _UNIT, 0.0]]
    m3 = [[r0[0], r0[1], r0[2]], [r1[0], r1[1], r1[2]], [r2[0], r2[1], r2[2]]]

    space = _P.get("mesh_rot_space") or "local"
    if turning and space == "game":
        # 在游戏坐标系里转，再换轴（= M·R·M⁻¹，M=Rx(90°)）
        lin = _mat3_mul(m3, _mat3_mul(au, _mat3_mul(rot3(), scl)))
    elif turning:
        # 'local'：换完轴再在**网格自己的 Blender 局部系**里转。
        # 判据是实机形态：arrow_base 的 rotation Z=-90 在游戏里是把箭在地面上转个向，
        # 不是把它立起来。箭身沿游戏 -X，绕游戏 Z（水平轴）转 90° 必然竖起来，
        # 只有绕竖直轴转才躺得平。
        lin = _mat3_mul(m3, _mat3_mul(rot3(), _mat3_mul(au, scl)))
    else:
        lin = _mat3_mul(m3, _mat3_mul(au, scl))

    px, py, pz = item.pos.x, item.pos.y, item.pos.z
    bx, by, bz = px * _UNIT, -pz * _UNIT, py * _UNIT
    t = (m3[0][0] * bx + m3[0][1] * by + m3[0][2] * bz + r0[3],
         m3[1][0] * bx + m3[1][1] * by + m3[1][2] * bz + r1[3],
         m3[2][0] * bx + m3[2][1] * by + m3[2][2] * bz + r2[3])
    return lin, t


def _bound_mesh_for(entry_obj):
    """entry 下 MESH 属性绑定的网格对象（mod3_link 填的 efx_mesh_target）。"""
    for blk in _entry_attributes(entry_obj):
        try:
            tgt = getattr(blk, "efx_mesh_target", None)
        except Exception:
            tgt = None
        if tgt is not None and getattr(tgt, "type", None) == "MESH":
            return tgt
    return None


def _join_chunks(verts, colors, uvs, col2s, chunks):
    """把网格的 numpy 分块和普通三角（片/条带）拼成一对可直接喂 batch 的数组。"""
    try:
        import numpy
        vs = [c[0] for c in chunks]
        cs = [c[1] for c in chunks]
        us = [c[2][0] for c in chunks if c[2] is not None]
        c2 = [c[2][1] for c in chunks if c[2] is not None]
        if verts:
            vs.insert(0, numpy.array(verts, dtype="f4"))
            cs.insert(0, numpy.array(colors, dtype="f4"))
            if us:
                us.insert(0, numpy.array(uvs, dtype="f4"))
                c2.insert(0, numpy.array(col2s, dtype="f4"))
        cat = lambda a: (numpy.concatenate(a) if len(a) > 1 else a[0])
        return cat(vs), cat(cs), (cat(us) if us else None), (cat(c2) if c2 else None)
    except Exception:
        out_v, out_c = list(verts), list(colors)
        out_u = list(uvs) if uvs else []
        out_2 = list(col2s) if col2s else []
        for a, c, ex in chunks:
            out_v.extend(a.tolist())
            out_c.extend(c.tolist())
            if ex is not None:
                out_u.extend(ex[0].tolist())
                out_2.extend(ex[1].tolist())
        return out_v, out_c, (out_u or None), (out_2 or None)


def _emit_mesh(verts, colors, chunks, item, col, size_mul, rows, geom,
               uvs=None, col2s=None, core=None):
    """网格 → 三角形。

    几何来自宿主（mod3_link 已经把 mod3 导进来并绑在 MESH 属性上），模拟层只给
    位置/旋转/缩放/颜色。没绑定就画一个占位立方体——比什么都不画诚实。

    整条变换压成一个 3×4（见 `_mesh_affine`），有 numpy 就整批算完，没有就逐顶点走
    同一个矩阵。两条路结果一致，只差速度。
    """
    tris, arr, muv = geom
    if not tris:
        return
    lin, t = _mesh_affine(item, size_mul, rows)

    if arr is not None and chunks is not None:
        try:
            import numpy
            out = arr.dot(numpy.array(lin, dtype="f4").T)
            out += numpy.array(t, dtype="f4")
            cc = numpy.empty((len(tris), 4), dtype="f4")
            cc[:] = col
            extra = None
            if uvs is not None and muv is not None:
                c2 = numpy.empty((len(tris), 4), dtype="f4")
                c2[:] = (core if core is not None else col)
                c2[:, 3] = col[3]
                uvarr = numpy.array(muv, dtype="f4")
                xf = item.extra.get("uv_xform")
                if xf:      # UVCONTROL：uv' = uv × 缩放 + 偏移
                    uvarr = uvarr * numpy.array((xf[0], xf[1]), dtype="f4")
                    uvarr += numpy.array((xf[2], xf[3]), dtype="f4")
                extra = (uvarr, c2)
            chunks.append((out, cc, extra))
            return
        except Exception:
            pass

    a0, a1, a2 = lin[0], lin[1], lin[2]
    t0, t1, t2 = t
    for (vx, vy, vz) in tris:
        verts.append((a0[0] * vx + a0[1] * vy + a0[2] * vz + t0,
                      a1[0] * vx + a1[1] * vy + a1[2] * vz + t1,
                      a2[0] * vx + a2[1] * vy + a2[2] * vz + t2))
    colors.extend([col] * len(tris))
    if uvs is not None and muv is not None:
        xf = item.extra.get("uv_xform")
        if xf:
            uvs.extend([(u * xf[0] + xf[2], v * xf[1] + xf[3]) for (u, v) in muv])
        else:
            uvs.extend(muv)
        c = core if core is not None else col
        col2s.extend([(c[0], c[1], c[2], col[3])] * len(tris))


#: 自定义 shader（pos + uv + color + sampler2D）。None = 还没建，False = 建不出来
#: （那就退回 FLAT_COLOR 的白方块，功能降级但不报错）。
_TEX_SHADER = None
#: shader 的 CreateInfo / 接口对象：有版本在 shader 存活期间要求它们别被回收，
#: 一并挂在模块上（同 enum-callback-gc-trap 那类坑的防法）。
_TEX_SHADER_KEEP = []
#: 图像名 → GPUTexture。逐帧重建太贵；换图/重启时清掉（见 _clear_tex_cache）。
_GPU_TEX = {}

_VERT_SRC = """
void main()
{
  v_uv = uv;
  v_col = color;
  v_col2 = col2;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

#: `alphaFix` = (lowPass, contrast_gamma)，中性值 (0, 1)。ALPHACORRECTION 是**逐纹素**
#: 改贴图 alpha 的形状（硬阈值裁切 + 伽马），只有在这里做才是对的。
#: 两层染色（RGBFIRE/RGBWATER）按**贴图亮度**在外缘色与核心色之间插值：笔画核心亮
#: → 取核心色，边缘暗 → 取外缘色。没有第二层时 col2 == color，mix 自动退化成恒等。
_FRAG_SRC = """
void main()
{
  vec4 t = texture(image, v_uv);
  float lum = max(t.r, max(t.g, t.b));
  vec3 rgb = mix(v_col.rgb, v_col2.rgb, lum);
  float a = t.a;
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  fragColor = vec4(t.rgb * rgb, a * v_col.a);
}
"""


def _tex_shader():
    """带贴图的 shader；建不出来返回 None（调用方退回纯色）。

    **不要**用 `gpu.types.GPUShader(vert, frag)` 字符串构造器：3.4 起废弃、5.0 移除、
    Vulkan 后端下不工作。`create_from_info` 是 3.2+ 一直支持、5.x 仍推荐的那条路。
    """
    global _TEX_SHADER
    if _TEX_SHADER is not None:
        return _TEX_SHADER or None
    try:
        import gpu
        iface = gpu.types.GPUStageInterfaceInfo("efx_sim_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC4", "v_col")
        iface.smooth("VEC4", "v_col2")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC2", "alphaFix")
        info.sampler(0, "FLOAT_2D", "image")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_in(3, "VEC4", "col2")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(_VERT_SRC)
        info.fragment_source(_FRAG_SRC)
        _TEX_SHADER = gpu.shader.create_from_info(info)
        _TEX_SHADER_KEEP[:] = [iface, info]
    except Exception:
        _TEX_SHADER = False
    return _TEX_SHADER or None


def _gpu_texture(name):
    """图像名 → GPUTexture（缓存）。图不在/传不上去返回 None。"""
    if not name:
        return None
    tex = _GPU_TEX.get(name)
    if tex is not None:
        return tex
    img = bpy.data.images.get(name)
    if img is None:
        return None
    try:
        import gpu
        tex = gpu.texture.from_image(img)
    except Exception:
        return None
    _GPU_TEX[name] = tex
    return tex


def _clear_tex_cache():
    _GPU_TEX.clear()


def _collect_track(tr, scene, rv3d, buckets, points, point_colors, lines,
                   line_colors):
    """一条 track 的 RenderItem → 顶点桶。

    桶的 key 是 `(混合模式, 贴图名)`：多选同时模拟时各 entry 用各自的序列帧大图，
    按图分桶就能一次 batch 画完同一张图的所有片，不必逐粒子换绑定。
    """
    items = tr.get("items") or ()
    if not items:
        return
    rows = tr.get("ref_rows")
    entry = bpy.data.objects.get(tr["entry_name"])
    if rows is None or entry is None:
        return
    r0, r1, r2 = rows

    size_mul = float(getattr(scene, "efx_sim_particle_size", 1.0))
    draw_mode = getattr(scene, "efx_sim_draw_mode", "QUADS")
    blend = getattr(scene, "efx_sim_blend", "AUTO")
    hdr_mode = getattr(scene, "efx_sim_hdr_mode", "preserve_hue")
    # 逐帧读一次存进 _P：`_mesh_affine` 是逐粒子调的，在那里读 Scene 属性等于
    # 每个粒子过一次 RNA
    _P["mesh_rot_space"] = getattr(scene, "efx_sim_mesh_rot", "local")
    show_vel = bool(getattr(scene, "efx_sim_show_velocity", False))
    flip_v = bool(getattr(scene, "efx_sim_uv_flip_v", True))
    use_tex = bool(getattr(scene, "efx_sim_textured", True))

    images = tr.get("images") or {}
    root_tex = tr.get("image") or ""

    def _tex_of(it):
        """这一项用哪张序列帧大图：按它所属的 entry 查（子实例是别的 entry）。"""
        if not use_tex:
            return ""
        name = images.get(it.extra.get("entry_key"), root_tex)
        return name if (name and _gpu_texture(name) is not None) else ""

    right, up = _camera_axes(rv3d)
    view_dir = _view_direction(rv3d)

    def _bucket_for(it, tex):
        """桶 key = (混合模式, 贴图, alpha 修正)。

        alpha 修正（ALPHACORRECTION）是 shader 的 push constant，逐 draw 生效，所以
        必须进 key。它是**逐 entry**的，一个场景里不同取值就那么几种，分桶开销可忽略。
        """
        mode = it.blend if blend == "AUTO" else blend
        if mode not in ("ALPHA", "ADDITIVE"):
            mode = "ALPHA"
        fix = it.extra.get("alpha_fix") or (0.0, 1.0)
        key = (mode, tex, fix)
        b = buckets.get(key)
        if b is None:
            # 第 4 条是双层染色的核心色；和 uv 一样只有走贴图 shader 的桶才需要。
            # 第 5 条是网格的 numpy 分块 [(顶点, 颜色), …]：静态网格整块过同一个矩阵，
            # 留在 numpy 里到画之前才拼，省掉 tolist（51200 面时那一步占六成时间）。
            b = [[], [], ([] if tex else None), ([] if tex else None), []]
            buckets[key] = b
        return b

    #: 这一趟里「entry → 网格三角」的记忆。`_bound_mesh_for` 要遍历 entry 的属性列表、
    #: 前面还要 `bpy.data.objects.get`——逐粒子做就是每个粒子一次小扫描，粒子一多就是
    #: 网格路径的主要固定开销（实测占每粒子 120 µs 里的大半）。一个 entry 只查一次。
    mesh_memo = {}

    def _geom_of(it):
        """(几何, 贴图名)。贴图来自绑定网格自己的材质——reference mesh 那条链已经把
        材质和贴图建好了，我们只取用不解析。`use_tex` 关掉时退回纯色桶。"""
        key = it.extra.get("entry_key") or ""
        got = mesh_memo.get(key)
        if got is None:
            owner = bpy.data.objects.get(key) or entry
            m = _bound_mesh_for(owner)
            if m is None:
                # 没绑 mod3 → 画的是占位方块，面板上要说清楚（方块是对称的，
                # 看不出旋转对不对，容易被误判成「旋转没实现」）
                miss = tr.setdefault("mesh_missing", [])
                nm = getattr(owner, "name", "") or "?"
                if nm not in miss:
                    miss.append(nm)
            name = _mesh_image_name(m) if use_tex else ""
            if name and _gpu_texture(name) is None:
                name = ""
            got = (_mesh_tris_game(m), name)
            mesh_memo[key] = got
        return got

    def _corners_of(it, tex_name):
        """这一项的四角 UV，含 UVCONTROL 的滚动/缩放。"""
        c = _uv_corners(it, flip_v, tex_name)
        xf = it.extra.get("uv_xform")
        if not xf or not c:
            return c
        su, sv, ou, ov = xf
        return tuple((u * su + ou, v * sv + ov) for (u, v) in c)

    def _layers_of(it, col):
        """(外缘色, 核心色)：没挂双层染色就两边都用 col，shader 里 mix 退化成恒等。"""
        lay = it.extra.get("layers")
        if not lay:
            return col, col
        a = _display_color((lay[0][0], lay[0][1], lay[0][2], col[3]), hdr_mode)
        b = _display_color((lay[1][0], lay[1][1], lay[1][2], col[3]), hdr_mode)
        return a, b

    def _world(v):
        """游戏坐标 → 世界坐标（过该 track 的参考矩阵）。"""
        bx, by, bz = _to_blender(v)
        return (r0[0] * bx + r0[1] * by + r0[2] * bz + r0[3],
                r1[0] * bx + r1[1] * by + r1[2] * bz + r1[3],
                r2[0] * bx + r2[1] * by + r2[2] * bz + r2[3])

    def _world_dir(v):
        """游戏坐标系的**方向**（不含平移、不含单位缩放）→ 世界方向（单位长）。

        归一化是为了让面片尺寸只由 hw/hh 决定：参考矩阵里如果带了缩放，
        方向向量会被拉长，面片就会连带变形。
        """
        bx, by, bz = _axis_swap(v)
        d = (r0[0] * bx + r0[1] * by + r0[2] * bz,
             r1[0] * bx + r1[1] * by + r1[2] * bz,
             r2[0] * bx + r2[1] * by + r2[2] * bz)
        return _norm(d) or d

    for it in items:
        center = _world(it.pos)
        tex_name = _tex_of(it)
        col = _display_color(it.color, hdr_mode)
        kind = it.kind

        if kind == "RIBBON" and it.points:
            bv, bc, bu, b2, _np = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col)
            _emit_ribbon(bv, bc, bu, it, edge, size_mul, _world, view_dir,
                         _corners_of(it, tex_name), col2s=b2, core=core)
        elif kind == "MESH":
            # 网格用自己的 UV（来自 mod3），我们没收集 → 始终走纯色桶。
            # ⚠ 绑定网格要按**这一项所属的 entry**查：子实例是别的 entry，
            # 拿根 entry 的绑定会让所有子特效都画成根的那个网格。
            geom, tex_name = _geom_of(it)
            bv, bc, bu, b2, bnp = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col)
            _emit_mesh(bv, bc, bnp, it, edge, size_mul, rows, geom,
                       uvs=bu, col2s=b2, core=core)
        elif draw_mode in ("QUADS", "BOTH"):
            # it.size 是**游戏单位**（BILLBOARD3D 的 width×scale 一类），和位置同一
            # 套换算：÷100。size_mul 只是个人工放大镜，默认 1.0 = 照文件里的尺寸画。
            hw = max(1e-5, size_mul * abs(it.size.x) * _UNIT * 0.5)
            hh = max(1e-5, size_mul * abs(it.size.y) * _UNIT * 0.5)
            if it.axis_u is not None and it.axis_v is not None:
                # PLANE：固定朝向，用属性给的横/纵轴，不朝相机
                qr, qu = _world_dir(it.axis_u), _world_dir(it.axis_v)
            else:
                qr, qu = (_spin(right, up, it.rot) if it.rot else (right, up))
            bv, bc, bu, b2, _np = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col)
            bv.extend(_quad_verts(center, qr, qu, hw, hh))
            bc.extend([edge] * 6)
            if b2 is not None:
                b2.extend([(core[0], core[1], core[2], edge[3])] * 6)
            if bu is not None:
                bu.extend(_quad_uvs(_corners_of(it, tex_name)))

        if draw_mode in ("POINTS", "BOTH") and kind not in ("RIBBON", "MESH"):
            points.append(center)
            point_colors.append(col)
        vel = it.extra.get("vel")
        if show_vel and vel is not None:
            # 速度是「每帧位移」，直接画一帧的长度太短，乘一个可读的倍数
            vx, vy, vz = _to_blender(vel)
            k = 8.0
            lines.append(center)
            lines.append((center[0] + vx * k, center[1] + vy * k, center[2] + vz * k))
            line_colors.extend([col, (col[0], col[1], col[2], 0.0)])


def _draw():
    """POST_VIEW draw handler。**不改任何状态**，只画各 track 的 items。"""
    if not is_active():
        return
    trs = [t for t in _P["tracks"] if t.get("items")]
    if not trs:
        return

    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return

    context = bpy.context
    rv3d = getattr(context, "region_data", None)
    if rv3d is not None:
        _P["cam_fwd"] = _view_direction(rv3d)
    if rv3d is None:
        return
    scene = context.scene

    buckets = {}          # (混合模式, 贴图名) -> [verts, colors, uvs|None]
    points, point_colors, lines, line_colors = [], [], [], []
    for tr in trs:
        _collect_track(tr, scene, rv3d, buckets, points, point_colors,
                       lines, line_colors)

    try:
        flat = _builtin("FLAT_COLOR")
    except Exception:
        return
    tex_shader = _tex_shader()
    blend = getattr(scene, "efx_sim_blend", "AUTO")

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)      # 粒子之间不互相遮挡，但仍被场景几何遮挡
    try:
        # 先 Alpha 再 Add：加法混合的东西通常是最亮的高光，压在最后一层
        for mode in ("ALPHA", "ADDITIVE"):
            for (bmode, tex_name, fix), (bv, bc, bu, b2, bnp) in buckets.items():
                if bmode != mode or not (bv or bnp):
                    continue
                if bnp:
                    bv, bc, bu, b2 = _join_chunks(bv, bc, bu, b2, bnp)
                gpu.state.blend_set(mode)
                tex = _gpu_texture(tex_name) if (bu is not None) else None
                if tex is not None and tex_shader is not None:
                    tex_shader.bind()
                    tex_shader.uniform_sampler("image", tex)
                    # ALPHACORRECTION：(lowPass, contrast_gamma)，中性值 (0, 1)
                    tex_shader.uniform_float("alphaFix", fix)
                    batch_for_shader(tex_shader, "TRIS",
                                     {"pos": bv, "uv": bu, "color": bc,
                                      "col2": b2}).draw(tex_shader)
                else:
                    batch_for_shader(flat, "TRIS",
                                     {"pos": bv, "color": bc}).draw(flat)

        overlay = "ADDITIVE" if blend == "ADDITIVE" else "ALPHA"
        if points:
            gpu.state.blend_set(overlay)
            gpu.state.point_size_set(max(1.0, float(
                getattr(scene, "efx_sim_point_px", 4))))
            batch_for_shader(flat, "POINTS",
                             {"pos": points, "color": point_colors}).draw(flat)
        if lines:
            gpu.state.blend_set("ALPHA")     # 速度线是调试叠加层，别被加法混合冲白
            batch_for_shader(flat, "LINES",
                             {"pos": lines, "color": line_colors}).draw(flat)
    except Exception:
        pass
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")



#: 本模块注册过的 draw handler。模块级列表即可——不像 uvc_preview 那样需要「跨热
#: 重载按名清理」，因为本模块不往场景里放任何东西，重载后最坏只是叠加层不再刷新，
#: unregister() 会把它们摘干净。
_HANDLERS = []


def _remove_handlers():
    removed = 0
    while _HANDLERS:
        h = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
            removed += 1
        except Exception:
            pass
    _P["handler"] = None
    return removed


def _add_handler():
    _remove_handlers()
    h = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _HANDLERS.append(h)
    _P["handler"] = h
    return h


def _redraw_viewports():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ─────────────────────────────────────────────────────────────────────────────
# 时钟
# ─────────────────────────────────────────────────────────────────────────────

#: 重建后最多快进多少帧。超过就从头播——纯粹是防手滑设了个巨大的 duration
#: 之后每改一个字段都卡一下；正常值（百来帧）远在这个上限之下。
_REBUILD_CATCHUP_MAX = 600


def _rebuild_if_dirty(scene):
    """属性被编辑过 → 用新参数重建全部 track，并**快进回原来那一帧**。

    不快进的话，拖一下滑块画面就跳回第 0 帧，调参时根本没法比较前后差异。
    快进是划算的：整个模拟就是个 for 循环，几百帧 × 几百粒子是毫秒级
    （实测 600 粒子 2.1 ms/帧），而且确定性重放保证快进结果与连续播放一致。
    """
    if not _P["dirty"]:
        return
    _P["dirty"] = False
    _clear_tex_cache()          # 参考图可能被换了
    alive = []
    for tr in _P["tracks"]:
        if rebuild_track(tr, scene, keep_frame=True):
            alive.append(tr)
    _P["tracks"] = alive
    _P["duration"] = _resolve_duration(scene)
    _P["acc"] = 0.0


def _resolve_duration(scene, sim=None):
    """「播放一次」多长。0 = 自动（SPAWN 三态里没有停止条件，见 sim/behaviors/spawn.py）。

    多 track 时取**最长**的那个：短的那些循环几轮等长的跑完，比谁先结束谁就
    整体重置更符合「同时看几个效果」的意图。
    """
    d = int(getattr(scene, "efx_sim_duration", 0))
    if d > 0:
        return d
    sims = [sim] if sim is not None else [t["sim"] for t in _P["tracks"]]
    best = 0
    for s in sims:
        if s is None:
            continue
        try:
            best = max(best, int(s.suggested_duration()))
        except Exception:
            pass
    return best or 180


def _reset_all():
    for tr in _P["tracks"]:
        try:
            tr["sim"].reset()
        except Exception:
            pass


def _view_context():
    """给核心用的相机信息。BILLBOARD3D 要靠它决定自旋的哪一轴变成屏幕自转。

    `_draw` 每帧把视线方向缓存进 `_P["cam_fwd"]`（那里才拿得到 region_data；
    构建渲染项是在定时器里做的，上下文里没有视图）。还没画过第一帧时退回 game +Z。
    """
    from ..efx_format.sim.state import ViewContext, Vec3

    fwd = _P.get("cam_fwd")
    if not fwd:
        return ViewContext()
    # Blender 世界方向 → 游戏方向（`_axis_swap` 的逆，方向不换单位）
    return ViewContext(cam_forward=Vec3(fwd[0], fwd[2], -fwd[1]))


def _build_items(tr):
    try:
        tr["items"] = tr["sim"].build_render(_view_context())
    except Exception as exc:
        _P["error"] = str(exc)
        tr["items"] = []


def _tick(scene):
    """一次定时器滴答：按墙钟推进整数帧（所有 track 共用这一个时钟 → 天然同步）。

    倍速不靠改定时器间隔（那会丢整数帧语义），靠浮点累加器：
    0.25 倍速 = 每 4 个 tick 走一帧，2 倍速 = 每 tick 走两帧，
    逐帧乘法递推在任何倍速下都精确。
    """
    _rebuild_if_dirty(scene)
    if not _P["tracks"]:
        return
    _sync_host_origin(scene)

    now = time.perf_counter()
    dt = now - _P["last_t"]
    _P["last_t"] = now
    if dt <= 0.0 or dt > 0.5:
        dt = min(max(dt, 0.0), 1.0 / 30.0)   # 卡顿/切后台后不要一次补几百帧

    cfg = _P["tracks"][0]["sim"].config
    fps = float(getattr(cfg, "fps", 60))
    speed = float(getattr(scene, "efx_sim_speed", 1.0))
    _P["acc"] += dt * fps * speed

    steps = 0
    while _P["acc"] >= 1.0 and steps < 240:   # 单 tick 步数上限，防卡死
        for tr in _P["tracks"]:
            tr["sim"].step()
        _P["acc"] -= 1.0
        steps += 1

        frame = _P["tracks"][0]["sim"].frame
        if _P["duration"] > 0 and frame >= _P["duration"]:
            if getattr(scene, "efx_sim_mode", "LOOP") == "LOOP":
                _reset_all()
                _P["acc"] = 0.0
                break
            _P["playing"] = False
            break

    for tr in _P["tracks"]:
        _build_items(tr)



# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_sim_play(Operator):
    """开始播放选中 Entry 的粒子模拟（多选 = 同时播；自带时钟，不动时间轴）"""

    bl_idname = "efx.sim_play"
    bl_label = "Play EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _resolve_entry(context.active_object) is not None and not is_active()

    def invoke(self, context, event):
        entries = collect_entries(context)
        if not entries:
            self.report({"WARNING"}, T("sim.err_no_entry"))
            return {"CANCELLED"}

        _clear_tex_cache()
        _P["mesh_cache"] = {}
        trs = []
        for entry in entries:
            tr = build_track(entry, context.scene)
            if tr is not None:
                trs.append(tr)
        if not trs:
            self.report({"ERROR"}, _P["error"] or T("sim.err_build"))
            return {"CANCELLED"}

        _P["tracks"] = trs
        _P["duration"] = _resolve_duration(context.scene)
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["dirty"] = False
        _P["playing"] = True

        _add_handler()
        wm = context.window_manager
        # 固定高频 tick；倍速由累加器处理，不改这个间隔
        _P["timer"] = wm.event_timer_add(1.0 / 120.0, window=context.window)
        wm.modal_handler_add(self)

        if len(trs) > 1:
            self.report({"INFO"}, T("sim.playing_n").format(len(trs)))
        n_unsup = sum(len(tr["sim"].unsupported) for tr in trs)
        if n_unsup:
            self.report({"INFO"}, T("sim.unsupported_n").format(n_unsup))
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not is_active():
            return self._finish(context)
        if event.type == "TIMER":
            if _P["playing"]:
                _tick(context.scene)
                _redraw_viewports()
        return {"PASS_THROUGH"}       # 不吞事件：播放时照样能转视角、改参数

    def _finish(self, context):
        wm = context.window_manager
        if _P["timer"] is not None:
            try:
                wm.event_timer_remove(_P["timer"])
            except Exception:
                pass
            _P["timer"] = None
        _remove_handlers()
        _P["playing"] = False
        _P["tracks"] = []
        _P["mesh_cache"] = {}
        _clear_tex_cache()
        _redraw_viewports()
        return {"FINISHED"}

    def cancel(self, context):
        self._finish(context)


class EFX_OT_sim_stop(Operator):
    """停止播放并清除叠加层"""

    bl_idname = "efx.sim_stop"
    bl_label = "Stop EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        # 只摘 handler：modal 下一个 tick 看到 is_active()==False 就自己收尾
        _remove_handlers()
        _P["playing"] = False
        _P["tracks"] = []
        _P["mesh_cache"] = {}
        _clear_tex_cache()
        _redraw_viewports()
        return {"FINISHED"}


class EFX_OT_sim_pause(Operator):
    """暂停 / 继续（暂停时仍可转视角——渲染 pass 与模拟解耦）"""

    bl_idname = "efx.sim_pause"
    bl_label = "Pause EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        _P["playing"] = not _P["playing"]
        _P["last_t"] = time.perf_counter()
        return {"FINISHED"}


class EFX_OT_sim_restart(Operator):
    """从第 0 帧重放全部（同一种子 → 逐帧完全复现）"""

    bl_idname = "efx.sim_restart"
    bl_label = "Restart EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        # 直接重建，不走 _rebuild_if_dirty 的「快进回原帧」——重放的语义就是回到开头
        _clear_tex_cache()
        _P["mesh_cache"] = {}
        alive = []
        for tr in _P["tracks"]:
            if rebuild_track(tr, context.scene, keep_frame=False):
                tr["items"] = []
                alive.append(tr)
        if not alive:
            self.report({"ERROR"}, _P["error"] or T("sim.err_build"))
            return {"CANCELLED"}
        _P["tracks"] = alive
        _P["duration"] = _resolve_duration(context.scene)
        _P["dirty"] = False
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["playing"] = True
        _redraw_viewports()
        return {"FINISHED"}


class EFX_OT_sim_step(Operator):
    """单步：暂停状态下推进一帧，用来逐帧对拍"""

    bl_idname = "efx.sim_step"
    bl_label = "Step One Frame"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active() and not _P["playing"]

    def execute(self, context):
        if not _P["tracks"]:
            return {"CANCELLED"}
        _rebuild_if_dirty(context.scene)
        _sync_host_origin(context.scene)
        for tr in _P["tracks"]:
            tr["sim"].step()
            _build_items(tr)
        _redraw_viewports()
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板
# ─────────────────────────────────────────────────────────────────────────────


def _uvs_state_info(entry_obj):
    """没在播放时，面板也要能说清帧表会从哪来（不建资源，只看属性）。

    走带缓存的宿主查找：面板 draw 是高频路径，不能每次重绘扫一遍全场景对象。
    """
    if entry_obj is None:
        return None
    try:
        return _uvs_info(_uvs_host(entry_obj, use_cache=True))
    except Exception:
        return None


def _uvs_cell_readout():
    """(帧号, 总帧数, sequenceNo)——各 track 最近一次 build_render 里第一个带序列帧的项。

    贴图已经画出来了，但这个读数仍然有用：格号是唯一能**数**着验证帧推进对不对的
    东西（贴图看着对不对是主观的，格号能跟游戏逐帧对拍）。
    """
    for tr in _P["tracks"]:
        for it in tr.get("items") or ():
            n = it.extra.get("uvs_n")
            if n:
                return (int(it.extra.get("uvs_frame", 0)), int(n),
                        int(it.extra.get("uvs_group", 0)))
    return None


def _agg_status():
    """面板顶部的聚合读数：(帧, 存活总数, 累计生成总数, track 数, 子实例数)。"""
    trs = _P["tracks"]
    if not trs:
        return None
    frame = trs[0]["sim"].frame
    alive = sum(len(tr["sim"].particles) for tr in trs)
    spawned = sum(tr["sim"].em.spawned_total for tr in trs)
    # SimScene 才有 instance_count；根实例自己不算「子特效」
    children = sum(max(0, getattr(tr["sim"], "instance_count", 1) - 1) for tr in trs)
    return (frame, alive, spawned, len(trs), children)

class EFX_PT_sim(Panel):
    """粒子模拟播放器。独立于 EFX_PT_efx_preview 那一族——那边是「进入/退出会话」
    模型，这边是「播放器」模型，混在一起只会互相干扰。"""

    bl_idname = "EFX_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Particle Simulation"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active = is_active()
        trs = _P["tracks"]
        sim = trs[0]["sim"] if trs else None

        entry = _resolve_entry(context.active_object)
        if entry is None and not active:
            layout.label(text=T("sim.pick_entry"), icon="INFO")
            return

        # ── 走带 ─────────────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.4
        if not active:
            row.operator("efx.sim_play", text=T("sim.play"), icon="PLAY")
        else:
            row.operator("efx.sim_pause",
                         text=T("sim.pause") if _P["playing"] else T("sim.resume"),
                         icon="PAUSE" if _P["playing"] else "PLAY")
            row.operator("efx.sim_restart", text="", icon="LOOP_BACK")
            sub = row.row(align=True)
            sub.enabled = not _P["playing"]
            sub.operator("efx.sim_step", text="", icon="FRAME_NEXT")
            row.operator("efx.sim_stop", text="", icon="X")

        st = _agg_status() if active else None
        if st is not None:
            frame, alive, spawned, n_tracks, children = st
            box = layout.box()
            col = box.column(align=True)
            col.label(text=T("sim.frame").format(frame, _P["duration"]), icon="TIME")
            col.label(text=T("sim.alive").format(alive, spawned), icon="PARTICLES")
            if children:
                col.label(text=T("sim.children").format(children), icon="OUTLINER_OB_GROUP_INSTANCE")
            if n_tracks > 1:
                # 多选同时模拟：列出在播的是哪几个，别让人猜
                col.label(text=T("sim.playing_n").format(n_tracks), icon="SEQUENCE")
                sub = col.column(align=True)
                sub.scale_y = 0.7
                for tr in trs[:4]:
                    sub.label(text="· " + tr["entry_name"])
                if len(trs) > 4:
                    sub.label(text=T("sim.and_more").format(len(trs) - 4))
            if _P["error"]:
                col.label(text=_P["error"], icon="ERROR")

        # ── 播放设置 ─────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("sim.playback"), icon="PLAY")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_mode", text="")
        col.prop(scene, "efx_sim_speed")
        col.prop(scene, "efx_sim_duration")
        col.prop(scene, "efx_sim_seed")

        # ── 显示 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("sim.display"), icon="SHADING_RENDERED")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_draw_mode", text="")
        col.prop(scene, "efx_sim_blend", text="")
        col.prop(scene, "efx_sim_particle_size")
        if getattr(scene, "efx_sim_draw_mode", "QUADS") in ("POINTS", "BOTH"):
            col.prop(scene, "efx_sim_point_px")
        col.prop(scene, "efx_sim_show_velocity")
        col.prop(scene, "efx_sim_textured")
        if getattr(scene, "efx_sim_textured", True):
            col.prop(scene, "efx_sim_uv_flip_v")

        # ── 序列帧：帧表来源 + 现在放到第几格 ────────────────────────────────
        uvs = (trs[0].get("uvs") if trs else None) if active \
            else _uvs_state_info(entry)
        if uvs is not None:
            box = layout.box()
            box.label(text=T("sim.uvs"), icon="IMAGE_DATA")
            col = box.column(align=True)
            col.scale_y = 0.8
            if uvs["loaded"]:
                col.label(text=T("sim.uvs_file").format(uvs["file"], uvs["groups"]))
            else:
                g = getattr(scene, "efx_sim_uvs_grid", (8, 8))
                col.label(text=T("sim.uvs_grid").format(int(g[0]), int(g[1])),
                          icon="ERROR")
                col.label(text=T("sim.uvs_hint"))
            cell = _uvs_cell_readout()
            if cell is not None:
                col.label(text=T("sim.uvs_cell").format(cell[0] + 1, cell[1], cell[2]))
            img = trs[0].get("image") if trs else None
            if active and not img:
                # 载了 .uvs 但没绑图 → 画出来仍然是纯色片，说清楚为什么
                col.label(text=T("sim.uvs_noimage"), icon="INFO")
            if not uvs["loaded"]:
                box.prop(scene, "efx_sim_uvs_grid")

        # ── MESH 没绑 mod3：画的是占位方块，说清楚 ───────────────────────────
        missing = []
        for tr in trs:
            for nm in (tr.get("mesh_missing") or ()):
                if nm not in missing:
                    missing.append(nm)
        if missing:
            box = layout.box()
            box.label(text=T("sim.mesh_unbound"), icon="INFO")
            col = box.column(align=True)
            col.scale_y = 0.7
            for nm in missing[:6]:
                col.label(text="· " + nm)

        # ── 未模拟的属性：如实列出，预览不静默撒谎 ───────────────────────────
        unsup = []
        for tr in trs:
            for _h, name in tr["sim"].unsupported:
                if name not in unsup:
                    unsup.append(name or "?")
        if unsup:
            box = layout.box()
            box.label(text=T("sim.unsupported"), icon="ERROR")
            col = box.column(align=True)
            col.scale_y = 0.7
            for name in unsup[:8]:
                col.label(text="· " + name)
            if len(unsup) > 8:
                col.label(text=T("sim.and_more").format(len(unsup) - 8))


class EFX_PT_sim_unknowns(Panel):
    """待标定开关。

    这些不是「偏好设置」，是**还没实测确定的语义**。每一项都对应
    efx_format/sim/config.py::UNKNOWNS 里的一条。标定方式就是切开关对拍，
    定下来之后把 sim/config.py 的默认值改掉。
    """

    bl_idname = "EFX_PT_sim_unknowns"
    bl_parent_id = "EFX_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Calibration"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text=T("sim.calib_hint"), icon="INFO")
        col = layout.column(align=True)
        col.prop(scene, "efx_sim_jitter_mode")
        col.prop(scene, "efx_sim_es3d_range")
        col.prop(scene, "efx_sim_t3d_vel_unit")
        col.prop(scene, "efx_sim_spawn_jitter")
        col.prop(scene, "efx_sim_t3d_rot_sign")
        col.prop(scene, "efx_sim_mesh_rot")
        col.prop(scene, "efx_sim_rgb_tint")
        col.prop(scene, "efx_sim_hdr_mode")
        col.prop(scene, "efx_sim_life_model")
        col.prop(scene, "efx_sim_a0_sample")
        col.prop(scene, "efx_sim_timl_mode")
        col.prop(scene, "efx_sim_timl_interp")
        col.prop(scene, "efx_sim_rot_order")
        col.prop(scene, "efx_sim_age_during_delay")
        col.prop(scene, "efx_sim_ribbon_length")
        col.prop(scene, "efx_sim_parent_clock")
        col.prop(scene, "efx_sim_color_range")
        col.prop(scene, "efx_sim_uvs_speed_unit")
        col.prop(scene, "efx_sim_uvs_once_span")
        col.prop(scene, "efx_sim_uvs_start_wrap")
        layout.operator("efx.sim_restart", text=T("sim.reapply"), icon="FILE_REFRESH")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_sim_play,
    EFX_OT_sim_stop,
    EFX_OT_sim_pause,
    EFX_OT_sim_restart,
    EFX_OT_sim_step,
    EFX_PT_sim,
    EFX_PT_sim_unknowns,
)


def _on_knob_changed(self, context):
    """标定开关变了 → 标脏，下个 tick 用新配置重建。"""
    _P["dirty"] = True


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene

    # ── 播放 ─────────────────────────────────────────────────────────────────
    S.efx_sim_mode = EnumProperty(
        name="Mode",
        items=[("ONCE", "Play Once", "Stop at the end of one cycle"),
               ("LOOP", "Loop", "Restart from frame 0 at the end of each cycle")],
        default="LOOP")
    S.efx_sim_speed = FloatProperty(
        name="Speed", default=1.0, min=0.05, max=4.0, soft_min=0.1, soft_max=2.0,
        description="Playback speed multiplier (whole EFX frames are preserved at any speed)")
    S.efx_sim_duration = IntProperty(
        name="Duration", default=0, min=0, soft_max=600,
        description="Frames per cycle; 0 = auto (start delay + one burst cycle + one particle life). "
                    "EFX emitters have no documented stop condition, so this is the player's call")
    S.efx_sim_seed = IntProperty(
        name="Seed", default=0, update=_on_knob_changed,
        description="Base random seed; same seed replays identically")

    # ── 显示 ─────────────────────────────────────────────────────────────────
    S.efx_sim_draw_mode = EnumProperty(
        name="Draw",
        items=[("QUADS", "Billboards", "Camera-facing quads sized by particle scale"),
               ("POINTS", "Points", "One pixel-sized dot per particle (fastest)"),
               ("BOTH", "Both", "Quads plus centre dots")],
        default="QUADS")
    S.efx_sim_blend = EnumProperty(
        name="Blend",
        items=[("AUTO", "From file", "Use each renderer's own blendMode "
                                     "(BILLBOARD3D: 0=Alpha, 1=Additive)"),
               ("ADDITIVE", "Force additive", "Override everything to additive"),
               ("ALPHA", "Force alpha", "Override everything to plain alpha")],
        default="AUTO")
    S.efx_sim_particle_size = FloatProperty(
        name="Size x", default=1.0, min=0.01, max=20.0, soft_min=0.25, soft_max=4.0,
        description="Magnifier on top of the size read from the file "
                    "(BILLBOARD3D width/height x scale, in game units). 1.0 = as authored")
    S.efx_sim_point_px = IntProperty(name="Point px", default=4, min=1, max=32)
    S.efx_sim_show_velocity = BoolProperty(
        name="Velocity lines", default=False,
        description="Draw each particle's per-frame velocity as a fading line")
    S.efx_sim_textured = BoolProperty(
        name="Sprite sheet", default=True,
        description="Sample the sprite sheet bound to the entry's UVSEQUENCE attribute "
                    "(load it with Quick Load on that attribute). Off = flat colour")
    S.efx_sim_uv_flip_v = BoolProperty(
        name="Flip V", default=True,
        description="Flip the sprite sheet vertically. On by default: .uvs stores v "
                    "downwards while the GPU samples row 0 at the bottom. Turn it off "
                    "if the artwork shows up upside down")

    # ── 待标定（见 efx_format/sim/config.py::UNKNOWNS）───────────────────────
    S.efx_sim_jitter_mode = EnumProperty(
        name="Jitter", update=_on_knob_changed,
        items=[("onesided", "base + U[0, a]", "Confirmed: jitter is added on top of the static value"),
               ("symmetric", "base + U[-a, a]", "Symmetric around the static value"),
               ("gaussian", "base + N(0, a/2)", "Gaussian instead of uniform")],
        default="onesided")
    # ⚠ 刻意换了属性名（原 efx_sim_es3d_range_mode）：老名字在会话/.blend 里存着
    #   "minmax" 这个**仍然合法**的旧值，不换名就会把用户静默钉在被推翻的读法上。
    S.efx_sim_hdr_mode = EnumProperty(
        name="Over-bright colours",
        items=[("preserve_hue", "Keep hue",
                "Scale colours brighter than white back down so the authored hue "
                "survives, and fold the extra brightness into opacity"),
               ("tonemap", "Tone map",
                "Roll bright colours off towards white, the way bloom does in game"),
               ("raw", "Clip",
                "Let the framebuffer clip them - matches what a single pixel does "
                "in game, but without its tone mapping a high brightness turns "
                "the whole sprite white")],
        default="preserve_hue")
    S.efx_sim_mesh_rot = EnumProperty(
        name="Mesh rotation space", update=_on_knob_changed,
        items=[("local", "Mesh local",
                "Turn the mesh about its own axes after the game-to-Blender swap"),
               ("game", "Game axes",
                "Turn it in game space before the swap")],
        default="local")
    S.efx_sim_rgb_tint = EnumProperty(
        name="RGB tint", update=_on_knob_changed,
        items=[("weighted", "Weighted",
                "Blend the two layers by their own intensity and life weight"),
               ("mix", "Even mix", "Blend the two layers equally"),
               ("first", "Fire / Specular", "Use only the first layer's colour"),
               ("second", "Smoke / Sheet", "Use only the second layer's colour")],
        default="weighted")
    S.efx_sim_t3d_rot_sign = EnumProperty(
        name="Emitter spin direction", update=_on_knob_changed,
        items=[("flip", "Flip",
                "TRANSFORM3D's rotation velocity turns the emitter the opposite way "
                "from the raw sign"),
               ("raw", "Raw", "Take the authored sign as-is")],
        default="flip")
    S.efx_sim_spawn_jitter = EnumProperty(
        name="Burst interval jitter", update=_on_knob_changed,
        items=[("per_burst", "Per burst",
                "Re-roll SPAWN's burst interval for every burst, so the spacing "
                "between particles varies"),
               ("per_cycle", "Per cycle",
                "Roll it once per cycle, so a whole cycle is evenly spaced")],
        default="per_burst")
    S.efx_sim_t3d_vel_unit = EnumProperty(
        name="Emitter velocity", update=_on_knob_changed,
        items=[("per_second", "Per second",
                "TRANSFORM3D's translation / rotation / scale velocities are amounts "
                "per second; each frame advances by value / fps"),
               ("per_frame", "Per frame",
                "Amounts per frame (the behaviour before this was calibrated) - makes "
                "the authored values come out about 60x too fast")],
        default="per_second")
    S.efx_sim_es3d_range = EnumProperty(
        name="Spawn range", update=_on_knob_changed,
        items=[("shell", "Offset / Size",
                "Offset is the inner boundary, size is the thickness extending outwards, "
                "so the outer boundary is offset + size. Same for every shape"),
               ("minmax", "Min / Max",
                "The reading the RE DTI names (RangeMinX/RangeMaxX) suggest. Kept for "
                "comparison - it does not match how the game behaves")],
        default="shell")
    S.efx_sim_life_model = EnumProperty(
        name="Lifetime", update=_on_knob_changed,
        items=[("sum", "fadeIn + duration + fadeOut", "Total life is the sum of all three"),
               ("duration", "duration is the total", "Fades are carved out of duration")],
        default="sum")
    S.efx_sim_a0_sample = EnumProperty(
        name="TIML A0", update=_on_knob_changed,
        items=[("spawn", "Frozen at spawn", "Particle-level fields read A0 at their birth frame"),
               ("current", "Follows emitter time", "Particle-level fields re-read A0 every frame")],
        default="spawn")
    S.efx_sim_timl_mode = EnumProperty(
        name="TIML value", update=_on_knob_changed,
        items=[("replace", "Replaces static", "Keyframe value replaces the static field"),
               ("multiply", "Multiplies static", "Keyframe value scales the static field")],
        default="replace")
    S.efx_sim_timl_interp = EnumProperty(
        name="Interpolation", update=_on_knob_changed,
        items=[("native", "Per keyframe", "Use each keyframe's transition (QUAD/CUBIC fall back to linear)"),
               ("linear", "Force linear", ""),
               ("constant", "Force hold", "")],
        default="native")
    S.efx_sim_rot_order = EnumProperty(
        name="Rotation order", update=_on_knob_changed,
        items=[("forward", "First listed applies first", ""),
               ("reverse", "Last listed applies first", "")],
        default="forward")
    S.efx_sim_age_during_delay = BoolProperty(
        name="Age during spawn delay", default=False, update=_on_knob_changed,
        description="Whether particleSpawnDelay still advances the particle's age")
    S.efx_sim_ribbon_length = EnumProperty(
        name="Ribbon length", update=_on_knob_changed,
        items=[("per_segment", "length x (subdiv-1)",
                "Trail-follow ribbons get one 'length' per subdivision, so the strip "
                "gets longer as you raise the subdivision count"),
               ("total", "length is the whole strip",
                "Trail-follow ribbons are 'length' long no matter the subdivision count")],
        default="per_segment")
    S.efx_sim_color_range = EnumProperty(
        name="Colour range", update=_on_knob_changed,
        items=[("channel", "Per channel", "Every channel (alpha included) draws its own "
                                          "value between Colour and Colour Range"),
               ("shared", "Locked channels", "One random factor shared by all channels, "
                                             "so the hue stays on the line between the two"),
               ("add", "Colour + random", "Colour Range read as an additive amount: "
                                          "Colour + random[0, Range]")],
        default="channel")
    S.efx_sim_parent_clock = EnumProperty(
        name="Stop tracking after", update=_on_knob_changed,
        items=[("particle_age", "Each particle's own age",
                "PARENTOPTIONS' stop-tracking frame count is measured from each "
                "particle's birth (the field has its own Jitter, which only means "
                "something per particle)"),
               ("emitter_frame", "Emitter timeline",
                "Counted on the emitter timeline: every particle locks at the same moment")],
        default="particle_age")
    S.efx_sim_uvs_speed_unit = EnumProperty(
        name="UVS speed", update=_on_knob_changed,
        items=[("per_frame", "Cells per frame", "playSpeed = sprite cells advanced each frame"),
               ("per_second", "Cells per second", "playSpeed = sprite cells advanced each second")],
        default="per_frame")
    S.efx_sim_uvs_once_span = EnumProperty(
        name="UVS one play", update=_on_knob_changed,
        items=[("to_end", "Start frame to last", "One play runs from the start frame to the end of the sequence"),
               ("full_cycle", "Whole sequence", "One play always runs the full cell count")],
        default="to_end")
    S.efx_sim_uvs_start_wrap = EnumProperty(
        name="UVS start frame", update=_on_knob_changed,
        items=[("wrap", "Wrap around", "A start frame past the last cell wraps to the front"),
               ("clamp", "Clamp", "A start frame past the last cell sticks to the last cell")],
        default="wrap")
    S.efx_sim_uvs_grid = IntVectorProperty(
        name="Assumed grid", size=2, default=(8, 8), min=1, soft_max=16,
        update=_on_knob_changed,
        description="Sprite sheet cell count assumed when no .uvs is loaded "
                    "(H x V). 8x8 = 64 cells matches how most files author their "
                    "start-frame jitter")


def unregister():
    _remove_handlers()
    _P["playing"] = False
    _P["tracks"] = []
    _P["mesh_cache"] = {}
    _clear_tex_cache()
    _UVS_HOST_CACHE.clear()

    for attr in (
        "efx_sim_mode", "efx_sim_speed", "efx_sim_duration", "efx_sim_seed",
        "efx_sim_draw_mode", "efx_sim_blend", "efx_sim_particle_size",
        "efx_sim_point_px", "efx_sim_show_velocity",
        "efx_sim_jitter_mode", "efx_sim_es3d_range", "efx_sim_es3d_range_mode",
        "efx_sim_life_model",
        "efx_sim_a0_sample", "efx_sim_timl_mode", "efx_sim_timl_interp",
        "efx_sim_rot_order", "efx_sim_age_during_delay",
        "efx_sim_uvs_speed_unit", "efx_sim_uvs_once_span",
        "efx_sim_uvs_start_wrap", "efx_sim_uvs_grid",
        "efx_sim_textured", "efx_sim_uv_flip_v", "efx_sim_ribbon_length",
        "efx_sim_parent_clock", "efx_sim_color_range", "efx_sim_t3d_vel_unit",
        "efx_sim_spawn_jitter", "efx_sim_t3d_rot_sign", "efx_sim_rgb_tint", "efx_sim_mesh_rot",
        "efx_sim_hdr_mode",
        "efx_sim_hdr",   # 撤掉的旧名（存过已删除的 auto），留着清场
        "efx_sim_fps",   # 已撤掉的开关，留在这里是为了从老场景里清掉
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
