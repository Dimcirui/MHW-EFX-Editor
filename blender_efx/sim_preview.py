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
import os
import time

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       IntVectorProperty)
from bpy.types import Operator, Panel

from .i18n import T
from . import root_collection as _rc
from . import entry_action_ref as _entry_ref

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
    "gen": 0,             # 渲染项的版本号：每次重建 items +1，绘制缓存据此失效
    "needs_items": False, # 下个 tick 无论走没走帧都要重建一次 items
    "draw_cache": {},     # id(region_data) → (签名, 绘制负载)，见 _draw
    "gc_was_on": None,    # 播放期间关掉的 GC 原状态（见 _gc_hold）
    "skipped": 0,         # 距上次重建画面攒了几帧（efx_sim_render_every）
}


def _gc_hold(on):
    """播放期间关掉分代 GC，停止时恢复并补一次回收。

    模拟每帧要造几万个 Vec3/元组，而场景里长期活着的对象有二十多万个（光是
    `tr["items"]` 里上千条条带的顶点就占了一大半）。分代 GC 一到 gen2 就要把这
    二十多万个全遍历一遍——实测 `build_render` 因此在 105 ms 和 265 ms 之间反复
    跳，那一下就是肉眼可见的卡顿。

    关掉是安全的：这里造的垃圾（Vec3、元组、RenderItem）都不成环，引用计数当场
    就回收了，GC 只负责环。停止/暂停时恢复并 `collect()` 一次收尾。
    """
    import gc
    if on:
        if _P["gc_was_on"] is None:
            _P["gc_was_on"] = gc.isenabled()
            gc.disable()
    else:
        was = _P["gc_was_on"]
        _P["gc_was_on"] = None
        if was:
            gc.enable()
        if was is not None:
            gc.collect()


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
    """entry 下 UVSEQUENCE 属性实际存 `efx_uvs` 数据的对象；没有则 None。

    全语料 10084 个官方文件里一个 entry 最多一个 UVSEQUENCE（84106 个有的 entry
    全是 1 个），所以「取第一个」不是将就，就是全部。

    ⚠ uvs_link.py 把数据搬到了属性对象外挂的 `efx_uvs_target`（见
    `ensure_host_for_attribute`）——属性对象自己的 `efx_uvs` 现在恒空。有外挂宿主
    就必须跟过去，否则读到的永远是空数据（序列帧贴图静默消失）。老数据/尚未跑过
    uvs_link 的属性没有 `efx_uvs_target`，退回属性对象自己（兼容旧场景）。
    """
    from ..efx_format.hashes import UVSEQUENCE

    if use_cache and entry_obj.name in _UVS_HOST_CACHE:
        name = _UVS_HOST_CACHE[entry_obj.name]
        obj = bpy.data.objects.get(name) if name else None
        if name == "" or obj is not None:
            return obj

    found = None
    for blk in _entry_attributes(entry_obj):
        try:
            if int(blk.efx_block.type_hash_str) == UVSEQUENCE:
                found = getattr(blk, "efx_uvs_target", None) or blk
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
        flowmap_speed_unit=getattr(scene, "efx_sim_flowmap_speed_unit", "per_second"),
        flowmap_phase=getattr(scene, "efx_sim_flowmap_phase", "cycle"),
        ribbon_subdiv_max=int(getattr(scene, "efx_sim_ribbon_subdiv_max", 0)),
        ribbon_rigid_dir=getattr(scene, "efx_sim_ribbon_rigid_dir", "static"),
        homing_compose=getattr(scene, "efx_sim_homing_compose", "pursuit"),
        homing_orbit_axial_falloff=float(
            getattr(scene, "efx_sim_homing_axial_falloff", 0.0)),
        homing_orbit_retarget=getattr(scene, "efx_sim_homing_retarget",
                                      "once"),
        homing_orbit_lateral_tilt=float(
            getattr(scene, "efx_sim_homing_lateral_tilt", 0.0)),
        homing_orbit_axis_update=getattr(scene, "efx_sim_homing_axis_update",
                                         "frozen"),
        homing_ff_scale_mode=getattr(scene, "efx_sim_homing_ff_scale",
                                     "balanced"),
        homing_ff_recover_frames=float(
            getattr(scene, "efx_sim_homing_ff_recover", 48.0)),
        homing_speed_converge=getattr(scene, "efx_sim_homing_converge", "linear"),
        homing_speed_ramp_turns=float(
            getattr(scene, "efx_sim_homing_ramp_turns", 4.0)),
        **_budget_kw(scene))


def _budget_kw(scene):
    """粒子预算：0 = 用 SimConfig 自己的默认上限，不覆盖。"""
    n = int(getattr(scene, "efx_sim_particle_budget", 0))
    return {"max_particles_total": n} if n > 0 else {}


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


#: MATERIAL 的贴图槽 → 已载入的图名。键是 (槽位游戏路径)，跨 entry/文件共享——
#: 同一张 null_white 被几十个 entry 引用是常态，转一次就够。
_MAT_TEX_CACHE = {}


#: 图名 → 这张图的 alpha 通道有没有实际内容。判一次要把整张图读进来，缓存住。
_TEX_ALPHA_USABLE = {}


def _texture_alpha_is_usable(name):
    """这张贴图的 alpha 通道能不能当遮罩用。

    两类贴图混在一起，**不能按渲染体一刀切**（按 MESH 切会让 aura32a 那种从对的变成错的）：

      - 流动贴图（`_BM` / flow 系）：alpha 恒 1。实测 `zrx_008` 0.9961~1、
        `zr024` 0.9843~1、`flow_331` 0.9647~1——那点变化是 DDS 压缩噪声，不是内容。
        照实取 alpha 会把黑底一起画成实心方片，得改用 RGB 的明暗当 alpha。
      - 真带 alpha 的：`hx_10` alpha 0~1、平均 0.0446（RGB 几乎全白，形状全在 alpha 里），
        `md_wp11_000_BM` 0~1 平均 0.469。这些必须用自己的 alpha。

    判据取「alpha < 0.5 的像素占比」，两类之间空得很开（0.96 以上 vs 0），
    用占比而不是最小值是为了不被几个杂散纹素带偏。
    """
    if not name:
        return True
    got = _TEX_ALPHA_USABLE.get(name)
    if got is not None:
        return got
    img = bpy.data.images.get(name)
    if img is None:
        return True
    usable = True
    try:
        import numpy
        w, h = img.size
        n = w * h * 4
        if n > 0 and int(getattr(img, "depth", 32)) >= 32:
            buf = numpy.empty(n, dtype="f4")
            img.pixels.foreach_get(buf)
            a = buf[3::4]
            usable = float((a < 0.5).mean()) > 0.001
        else:
            usable = False      # 没有 alpha 通道
    except Exception:
        usable = int(getattr(img, "depth", 32)) >= 32
    _TEX_ALPHA_USABLE[name] = usable
    return usable


def _clear_flow_cache():
    _FLOW_TEX_CACHE.clear()


def _clear_material_cache():
    _MAT_TEX_CACHE.clear()


def _material_tex_paths(attr_objs):
    """entry 的 MATERIAL 属性 → {贴图槽名: 游戏相对路径}。没有 MATERIAL 则 {}。

    MATERIAL 是 mrl3 同源的内联材质覆盖，`sets` 里 `type == 128` 的才是贴图槽，
    槽位由 `t` 哈希反查（meta.texture_slot_name）。其余 type 是非贴图参数，跳过。
    一个块里 58 个 set 是常态，但贴图槽只有十来个。

    ⚠ `null_white` / `null_NM` 这类**照常读取**，不特判——它们是游戏里真实存在的
    占位贴图，作者拿 null_white 当纯白底正是为了让 MESH 的染色不被贴图串色。
    """
    from ..efx_format.material.meta import texture_slot_name
    from ..efx_format.hashes import MATERIAL

    out = {}
    for blk in attr_objs:
        pair = _block_fields(blk)
        if pair is None or pair[0] != MATERIAL:
            continue
        for block in (pair[1].get("blocks") or ()):
            for st in (block.get("sets") or ()):
                try:
                    if int(st.get("type", 0)) != 128:
                        continue
                    slot = texture_slot_name(int(st.get("t", 0)) & 0xFFFFFFFF)
                except Exception:
                    continue
                if not slot:
                    continue
                path = st.get("path") or b""
                if isinstance(path, bytes):
                    path = path.decode("ascii", "replace")
                path = path.rstrip(chr(0)).strip()
                if path and slot not in out:
                    out[slot] = path
    return out


def _material_image_name(entry_obj, attr_objs, slot, chunk_root):
    """MATERIAL 指定的那张贴图 → 已载入的图名；取不到返回 ""。

    走的是 uvs_link 那条现成的链（游戏路径解析 → tex→dds → bpy.data.images），
    与序列帧大图同一套，不另起炉灶。**在 build_track 里调一次**——这是磁盘 I/O，
    逐帧做会卡死。
    """
    paths = _material_tex_paths(attr_objs)
    rel = paths.get(slot) or ""
    if not rel:
        return ""
    cached = _MAT_TEX_CACHE.get(rel)
    if cached is not None:
        return cached if cached in bpy.data.images else ""
    try:
        from . import uvs_link as _ul
    except Exception:
        return ""
    try:
        efx_dir = _ul.efx_dir_of(entry_obj)
    except Exception:
        efx_dir = None
    name = ""
    try:
        abspath = _ul.resolve_game_path(rel, ".tex", chunk_root, efx_dir)
        if abspath:
            img = _ul.load_tex_image(abspath, rel)
            if img is not None:
                name = img.name
    except Exception:
        name = ""
    _MAT_TEX_CACHE[rel] = name      # 失败也缓存：别每次重建 track 都去磁盘扑空
    return name


#: 游戏路径 → 已载入的 flowmap 图名（""=找不到）。11 张共享图，全局缓存一次够用。
_FLOW_TEX_CACHE = {}


def _flowmap_path(attr_objs):
    """entry 的渲染体属性里那条 flowmap 贴图路径；没启用/没配就 ""。

    八件套挂在 BILLBOARD3D / PLANE / BILLBOARD2D 自己身上（不是独立属性类型），
    路径也存在同一个块里。`applicationRule` 的 bit 0x04 才是「启用」——语料里有
    9663 个块备了路径但没开位，那些不该画。
    """
    from ..efx_format.hashes import BILLBOARD3D, BILLBOARD2D, PLANE
    from ..efx_format.sim.behaviors._flowmap import BIT_ENABLE

    for blk in attr_objs:
        pair = _block_fields(blk)
        if pair is None or pair[0] not in (BILLBOARD3D, BILLBOARD2D, PLANE):
            continue
        d = pair[1]
        if not (int(d.get("applicationRule", 0) or 0) & BIT_ENABLE):
            continue
        raw = d.get("path") or b""
        if isinstance(raw, bytes):
            raw = raw.split(b"\x00")[0].decode("ascii", "replace")
        raw = str(raw).rstrip(chr(0)).strip()
        if raw:
            return raw
    return ""


def _flowmap_image_name(entry_obj, attr_objs, chunk_root):
    """flowmap 贴图 → 已载入的图名；取不到返回 ""。链路同 `_material_image_name`。"""
    rel = _flowmap_path(attr_objs)
    if not rel:
        return ""
    cached = _FLOW_TEX_CACHE.get(rel)
    if cached is not None:
        return cached if cached in bpy.data.images else ""
    try:
        from . import uvs_link as _ul
    except Exception:
        return ""
    try:
        efx_dir = _ul.efx_dir_of(entry_obj)
    except Exception:
        efx_dir = None
    name = ""
    try:
        abspath = _ul.resolve_game_path(rel, ".tex", chunk_root, efx_dir)
        if abspath:
            img = _ul.load_tex_image(abspath, rel)
            if img is not None:
                name = img.name
    except Exception:
        name = ""
    _FLOW_TEX_CACHE[rel] = name
    return name


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
    mesh_images = {}
    flow_images = {}
    mat_slot = getattr(scene, "efx_sim_material_slot", "tAlbedoMap")
    chunk_root = getattr(scene, "efx_chunk_root", "") or ""
    root_uvs_info = None
    for name, obj in entries.items():
        attrs = attrs_by_entry.get(obj, ())
        blocks = []
        for blk in attrs:
            pair = _block_fields(blk)
            if pair is not None:
                blocks.append(pair)
        if not blocks:
            continue
        templates[name] = EntryTemplate(name, blocks, _entry_timl_bytes(obj))
        res, info = _uvs_state(obj)
        resources[name] = res
        images[name] = _uvs_image_name(obj)
        # MATERIAL 是 MESH 的伴生属性（全语料 5873 个带 MATERIAL 的 entry 全都带
        # MESH），它指定的贴图应当盖过 mod3 自带材质里那张。解析是磁盘 I/O，
        # 只在这里做一次。
        if mat_slot != "none":
            got = _material_image_name(obj, attrs, mat_slot, chunk_root)
            if got:
                mesh_images[name] = got
        got = _flowmap_image_name(obj, attrs, chunk_root)
        if got:
            flow_images[name] = got
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
        "order": entry_order(entry_obj),
        # 用**播放起点**的矩阵并固定下来：发射器之后的移动经 host_origin 进模拟，
        # 绘制再用当前矩阵就会把同一段位移算两遍。
        "ref_rows": _entry_matrix_rows(entry_obj),
        "items": [],
        "image": images.get(entry_obj.name, ""),
        #: entry 名 → 序列帧大图名。一棵树里每个 entry 各有各的图，绘制时按
        #: item.extra['entry_key'] 查（见 _collect_track）。
        "images": images,
        "mesh_images": mesh_images,
        #: entry 名 → flowmap 贴图名（启用了才有）。见 `_flowmap_image_name`。
        "flow_images": flow_images,
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


def _active_root_collection(context):
    """大纲里当前点中的集合所属的 EFX 文件根集合；不在任何 EFX 文件里则 None。

    根集合本身、以及它下面的 Entry / Direct Trigger 这些子集合都算——点进去的任何
    一层都只可能属于**一个**文件，没有歧义。真正要播单个 entry 的人是去选 entry
    **对象**的，那条路在 `collect_entries` 里优先级更高。
    """
    try:
        lc = context.view_layer.active_layer_collection
    except Exception:
        return None
    col = getattr(lc, "collection", None)
    if col is None:
        return None
    if _rc.is_root_collection(col):
        return col

    def contains(parent, target, depth=0):
        if depth > 8:
            return False
        for child in parent.children:
            if child == target or contains(child, target, depth + 1):
                return True
        return False

    for root in bpy.data.collections:
        if _rc.is_root_collection(root) and contains(root, col):
            return root
    return None


#: "点中根集合" 播放范围下拉的标识前缀：具体 Subselect 用 "SS:" + 对象名，
#: 区别于固定项 "ALL"（Direct Trigger 那批，原行为）。
_SIM_SCOPE_SS_PREFIX = "SS:"

#: 全局缓存：防止 Blender EnumProperty 动态回调因 GC 丢引用导致下拉乱码
#: （见 memory/enum-callback-gc-trap：必须是模块级变量，回调里 global 重新赋值，
#: 返回这个全局对象本身，不能返回局部 list）。
_sim_scope_items_cache = [("ALL", "All", "")]


def _sim_scope_items(self, context):
    """播放范围下拉的候选项：固定 "All"（Direct Trigger）+ 当前根集合下的每个
    Subselect（选中即只播那个 Subselect.members 指向的 entry 集合）。"""
    global _sim_scope_items_cache
    items = [("ALL", T("sim.scope_all"), T("sim.scope_all_tip"))]
    root = _active_root_collection(context) if context is not None else None
    if root is not None:
        for ss in _rc.collect_top_level(root, "EFX_SUBSELECT"):
            items.append((_SIM_SCOPE_SS_PREFIX + ss.name, ss.name, T("sim.scope_subselect_tip")))
    _sim_scope_items_cache = items
    return _sim_scope_items_cache


def _subselect_scope_entries(root, ss_name):
    """指定 Subselect 的成员 entry 列表：按 members 原序，去重，跳过悬空指针。
    ss_name 对不上当前 root 下的任何 Subselect（改名/切到别的文件）时返回空列表
    ——不悄悄退回全播，播放范围选错了就该看见"没东西可播"而不是播了别的一批。"""
    ss_obj = bpy.data.objects.get(ss_name)
    if ss_obj is None or _rc.find_root_collection(ss_obj) is not root:
        return []
    try:
        members = ss_obj.efx_subselect.members
    except AttributeError:
        return []
    out = []
    seen = set()
    for m in members:
        e = m.body_ptr
        if e is not None and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    return out


def _selected_entries(context):
    """当前**选中对象**（不是 `active_object`）各自往上找到的 entry，去重、按选中顺序。

    刻意不用 `context.active_object`：在大纲里点一个集合行只会改
    `view_layer.active_layer_collection`，不会清掉之前选中物体时留下的
    `active_object`——用 `active_object` 判断"是不是选中了具体 entry"会在
    「先选了个 entry，再点集合切到播放范围下拉」这个顺序下误判成"还选着 entry"，
    导致下拉怎么点都不出现（面板判据必须跟 `collect_entries` 真正的优先级一致）。
    """
    out = []
    seen = set()
    for obj in list(getattr(context, "selected_objects", None) or ()):
        e = _resolve_entry(obj)
        if e is not None and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    return out


def collect_entries(context):
    """要模拟哪些 entry。

    两条路：

      - 大纲里点中**一个 EFX 根集合** → 按播放范围下拉（`Scene.efx_sim_scope`）：
        "All" 播整个文件的 **Direct Trigger** 那批 entry（原行为，Not Direct Trigger
        的不起 track——它们是靠 PtLife → Action 召唤出来的，模拟里已经会作为子实例
        生出来，见 sim/scene.py；再起一条就会被画两遍）；选了具体 Subselect 则只播
        它 members 指向的那些 entry（"这套子选择实际会用到的特效"）。
      - 否则按**选中对象**各自往上找 entry，去重；空则退回活动对象（多选=同时播）。
    """
    out = _selected_entries(context)
    if out:
        return out              # 选了具体的 entry（或它下面的属性）→ 就播这些

    root = _active_root_collection(context)
    if root is not None:
        scope = getattr(context.scene, "efx_sim_scope", "ALL")
        if scope.startswith(_SIM_SCOPE_SS_PREFIX):
            return _subselect_scope_entries(root, scope[len(_SIM_SCOPE_SS_PREFIX):])
        ents = _rc.collect_top_level(root, "EFX_ENTRY")
        direct = [e for e in ents if _entry_ref.is_entry_in_eof(e)]
        if direct:
            return direct
        return ents        # 没有 eof 分流信息（opaque 模型）→ 只能全播

    e = _resolve_entry(context.active_object)
    return [e] if e is not None else []


def entry_order(entry_obj):
    """绘制次序的排序键 `(文件, 文件内次序)`。

    **文件内**有权威答案：entry 在 main 段里的次序（`efx_index`）。完全重合的面片
    谁盖谁就按这个来——我们的粒子不写深度（`depth_mask_set(False)`），所以先后
    全由绘制顺序决定，这正是实机那套「按 entry 排布定覆盖优先权」的机制。

    **跨文件没有权威答案**：不同 .efx 是各自独立的特效实例，相对先后由引擎在触发时
    决定，文件里没有这个信息。这里取根集合名——就是大纲里看到的顺序，要调整改个名即可。
    """
    if entry_obj is None:
        return ("", 0)
    root = _rc.find_root_collection(entry_obj)
    try:
        idx = int(entry_obj.get("efx_index", 0) or 0)
    except Exception:
        idx = 0
    return (root.name if root is not None else "", idx)



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

      'preserve_hue'（默认）除以最大分量保住色相，**alpha 原样不动**。
                     ⚠ 曾经这里把超出的倍数折进不透明度（`a * m` 再夹 1），理由是
                     「加法混合下更亮 = 加得更多」——那会**把淡入淡出整条压平**：
                     `star` 的 brightness=50，alpha 只要 >0.02 就一律顶成 1，LIFE
                     算得好好的 1.0→0.6 的淡出在屏幕上完全看不出来。宁可整体偏暗
                     也不能丢掉淡入淡出，那是作者调出来的东西。
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
    return (r / m, g / m, b / m, a)


def _multiply_tint(c, gain=1.0):
    """折射（乘法通道）的源色：按覆盖度在「无操作(1,1,1)」和「颜色×brightness」之间插值。

    定点管线的 MULTIPLY 是 `dst × src`，`src.a` 根本不参与 RGB 的结果——所以粒子的
    alpha（LIFE 的淡入淡出、颜色自带的 a）必须在这里折进 RGB，否则折射层会在出生
    和死亡的瞬间硬闪。折到 1 而不是 0：乘 1 等于不改变背景，这才是「淡出」。

    贴图那一档还会再按纹素 alpha 混一次，两次朝同一个端点插值可以复合
    （`mix(1, mix(1,C,α), t) == mix(1, C, α·t)`），所以两边都对。
    """
    a = c[3] * gain
    if a == 1.0:
        return (c[0], c[1], c[2], 1.0)
    if a <= 0.0:
        return (1.0, 1.0, 1.0, 1.0)
    return (1.0 + (c[0] - 1.0) * a,
            1.0 + (c[1] - 1.0) * a,
            1.0 + (c[2] - 1.0) * a,
            1.0)


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
        _apply_swing_preview(tr, scene)
        _sync_track_origin(tr)


# ─────────────────────────────────────────────────────────────────────────────
# "模拟挥砍"预览开关
#
# RIBBON/RIBBONBLADE 这类条带渲染体画的是**宿主**（entry empty）划过的轨迹，
# 不认粒子自身速度——ribbonblade.py 已实测确认它没有 VELOCITY3D，纯靠 PARENTOPTIONS
# 把发射器绑在挥动的武器骨骼上。没有骨骼动画可播时，宿主永远静止，轨迹永远是空的。
# 这里给预览加一个内置的往复摆动量，纯粹为了让轨迹逻辑有东西可画——编出来的摆动
# 不追求还原游戏内挥砍手感，只用来验证渲染逻辑本身。
# ─────────────────────────────────────────────────────────────────────────────

def _mute_bone_follow(entry):
    """挥砍预览和骨骼跟随约束二选一：两边都在改 entry 位置会叠出双份位移，
    这里临时静音 transform_sync 挂的 Copy Location 约束（若有）。"""
    from . import transform_sync as _tsync
    con = entry.constraints.get(_tsync._BONE_FOLLOW_CONSTRAINT_NAME)
    if con is not None:
        con.mute = True


def _restore_bone_follow(entry_name):
    entry = bpy.data.objects.get(entry_name)
    if entry is None:
        return
    from . import transform_sync as _tsync
    con = entry.constraints.get(_tsync._BONE_FOLLOW_CONSTRAINT_NAME)
    if con is not None:
        con.mute = False


def _restore_all_bone_follow():
    """停止播放 / 插件卸载时兜底：别把静音状态留在场景里。"""
    for tr in _P["tracks"]:
        _restore_bone_follow(tr["entry_name"])


def _apply_swing_preview(tr, scene):
    """挥砍开关开着时，把 entry 摆到「参考位置」为圆心的一段往复圆弧上；
    关着（默认）什么都不做，只确保约束状态复原。

    往复一次 = 去程 + 回程，各占 `efx_sim_swing_duration` 秒，smoothstep 缓入缓出。
    方向反转的瞬间速度过零——正好把 RIBBONBLADE「停下才回缩」的那一段也一并练到。
    时间轴用 `tr["sim"].frame`（模拟自己的帧计数），暂停/调速/重播都天然跟着走，
    不用另起一个时钟。
    """
    entry_name = tr["entry_name"]
    if scene is None or not getattr(scene, "efx_sim_swing_enable", False):
        _restore_bone_follow(entry_name)
        return

    entry = bpy.data.objects.get(entry_name)
    if entry is None:
        return
    _mute_bone_follow(entry)

    fps = float(getattr(tr["sim"].config, "fps", 60)) or 60.0
    t = tr["sim"].frame / fps

    duration = max(0.05, float(getattr(scene, "efx_sim_swing_duration", 0.35)))
    half_angle = math.radians(float(getattr(scene, "efx_sim_swing_angle", 180.0))) * 0.5
    axis = getattr(scene, "efx_sim_swing_axis", "Z")
    radius = max(0.0, float(getattr(scene, "efx_sim_swing_radius", 1.0)))

    cycle = 2.0 * duration
    phase = (t % cycle) / duration              # 0..2：去程/回程各占一段
    u = phase if phase <= 1.0 else 2.0 - phase
    u = u * u * (3.0 - 2.0 * u)                  # smoothstep
    theta = half_angle * (2.0 * u - 1.0)         # -half..+half

    rows = tr["ref_rows"]
    rx, ry, rz = rows[0][3], rows[1][3], rows[2][3]
    s, c = math.sin(theta), math.cos(theta)

    # 圆弧半径 radius，theta=0 时正好落回参考位置（c-1=0, s=0）。
    if axis == "X":
        pos = (rx, ry + radius * (c - 1.0), rz + radius * s)
    elif axis == "Y":
        pos = (rx + radius * s, ry, rz + radius * (c - 1.0))
    else:  # "Z"（默认）：弧线在水平面内
        pos = (rx + radius * (c - 1.0), ry + radius * s, rz)

    # 只改位置，entry 自身的朝向/缩放（TRANSFORM3D 本地旋转/缩放）原样保留。
    # ⚠ 不能拿一份手搭的嵌套 tuple 直接赋给 matrix_world/matrix_basis——那样赋值
    # 不会报错，但会被静默当成单位矩阵（实机验证过），朝向/缩放全部丢失。必须
    # 改在一个真正的 Matrix 实例上（这里就是读出来的 cur 本身）再整个赋回去。
    cur = entry.matrix_world
    cur.translation = pos
    entry.matrix_world = cur



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


#: 面片的**局部** UV（0..1 铺满这一格），顶点序同 `_quad_verts`。flowmap 要按它
#: 采流动贴图——流动图是整张独立的图，不该跟着序列帧的子格走。
_QUAD_LUV = tuple(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[i]
                  for i in _QUAD_UV_ORDER)


def _ribbon_affine(rows):
    """把「游戏坐标 → Blender 世界」压成一个 3×3 + 平移。

    `_world` 是 `rows · _to_blender(v)` 两步，逐顶点调等于每个顶点两次函数调用；
    条带一帧有几十万个顶点，合并成一个矩阵之后 numpy 一次点乘就完事。

    `_to_blender` 是 (x, y, z) → (x, -z, y) × _UNIT，代进去并按 (x, y, z) 重新
    收系数即可（同 `_mesh_affine` 里那处合并）。
    """
    u = _UNIT
    lin = []
    t = []
    for r in rows:
        lin.append((u * r[0], u * r[2], -u * r[1]))
        t.append(r[3])
    return lin, t


def _ribbon_np_ctx(rows, view_dir):
    """条带 numpy 快路径的逐 track 常量：(numpy, 3×3, 平移, 视线)。拿不到 numpy 返回 None。"""
    try:
        import numpy
    except Exception:
        return None
    lin, t = _ribbon_affine(rows)
    return (numpy,
            numpy.array(lin, dtype="f4"),
            numpy.array(t, dtype="f4"),
            numpy.array(view_dir, dtype="f4"))


#: 条带展开成三角的下标表：n → (顶点下标, alpha 下标, 纵向参数列)。
#: 只跟顶点数有关，一个文件里就那么一两种，算一次全场复用。
_RIBBON_IDX = {}


def _ribbon_idx(numpy, n):
    got = _RIBBON_IDX.get(n)
    if got is not None:
        return got
    m = n - 1
    i = numpy.arange(m)
    # 每段六个顶点 = (l0, r0, r1, l0, r1, l1)；左右两侧拼成一个 (2n, …) 再按下标取，
    # 六次分量赋值就压成一次高级索引
    vidx = numpy.empty((m, 6), dtype=numpy.intp)
    vidx[:, 0] = i
    vidx[:, 1] = n + i
    vidx[:, 2] = n + i + 1
    vidx[:, 3] = i
    vidx[:, 4] = n + i + 1
    vidx[:, 5] = i + 1
    aidx = numpy.empty((m, 6), dtype=numpy.intp)
    aidx[:, 0] = i
    aidx[:, 1] = i
    aidx[:, 2] = i + 1
    aidx[:, 3] = i
    aidx[:, 4] = i + 1
    aidx[:, 5] = i + 1
    ucol = numpy.linspace(0.0, 1.0, n, dtype="f4").reshape(n, 1)
    got = (vidx.reshape(-1), aidx.reshape(-1), ucol)
    _RIBBON_IDX[n] = got
    return got


def _emit_ribbons_np(chunks, group, size_mul, ctx):
    """**一批**条带 → numpy 分块。按顶点数分组，同组的一次算完。

    为什么要成批：单条带走 numpy 也要二十来次 numpy 调用，每次约 2 µs 的调度开销
    ——上千条带就是 60 ms，而且这笔开销**不随细分数下降**（降细分只让数组变短，
    调用次数一个不少）。整组拉成 `(K, n, …)` 之后，同样二十来次调用把一万条带
    全算完，降细分才真的降得动。

    中途出错不会留下半截数据：分块先攒在本地，整组算完才并进桶里，调用方可以
    整组退回纯 Python。
    """
    numpy, lin, tr, vdir = ctx
    # 分组键带上「是不是数组形态」：核心层大多数条带已经是 RibbonStrip
    # （见 efx_format/sim/state.py），这种整组 stack 就完了；老的元组列表
    # （柔体链/刚性矩形/没有 numpy 时的兜底）还得逐顶点拉平。
    by_n = {}
    for rec in group:
        pts = rec[0].points
        n = len(pts)
        if n < 2:
            continue
        key = (n, getattr(pts, "pos", None) is not None)
        g = by_n.get(key)
        if g is None:
            g = by_n[key] = []
        g.append(rec)

    out = []
    for (n, is_strip), recs in by_n.items():
        vidx, aidx, ucol = _ribbon_idx(numpy, n)
        k = len(recs)
        m = n - 1
        six = m * 6

        if is_strip:
            # 数组形态：三次 stack 就位，Python 侧一个顶点都不用碰
            pos = numpy.stack([r[0].points.pos for r in recs]).astype("f4")
            half = numpy.stack([r[0].points.half for r in recs]).astype("f4")
            alpha = numpy.stack([r[0].points.alpha for r in recs]).astype("f4")
        else:
            # (K, n, 5) = [x, y, z, 半宽, alpha]，逐顶点拉平
            flat = []
            ex = flat.extend
            for it, _col, _core, _cn in recs:
                for q, h, a in it.points:
                    ex((q.x, q.y, q.z, h, a))
            raw = numpy.array(flat, dtype="f4").reshape(k, n, 5)
            pos = numpy.ascontiguousarray(raw[:, :, :3])
            half = raw[:, :, 3]
            alpha = raw[:, :, 4]

        W = pos.dot(lin.T)
        W += tr

        # 每个顶点的「前后方向」：首尾各用自己那一段
        seg = numpy.empty_like(W)
        seg[:, 1:-1] = W[:, 2:]
        seg[:, 1:-1] -= W[:, :-2]
        seg[:, 0] = W[:, 1] - W[:, 0]
        seg[:, -1] = W[:, -1] - W[:, -2]

        # 横向 = 段方向 × 视线。`numpy.cross` 的 Python 外壳（moveaxis 一类）比
        # 算式本身还贵，直接按分量写。
        sx = seg[:, :, 0]
        sy = seg[:, :, 1]
        sz = seg[:, :, 2]
        vx = float(vdir[0])
        vy = float(vdir[1])
        vz = float(vdir[2])
        side = numpy.empty_like(W)
        side[:, :, 0] = sy * vz - sz * vy
        side[:, :, 1] = sz * vx - sx * vz
        side[:, :, 2] = sx * vy - sy * vx

        nrm = numpy.sqrt((side * side).sum(axis=2))          # (K, n)
        good = nrm > 1e-9
        hw = numpy.abs(half) * (size_mul * _UNIT)
        numpy.maximum(hw, 1e-5, out=hw)
        numpy.divide(hw, nrm, out=hw, where=good)            # 归一化与半宽合成一步
        side *= hw[:, :, None]

        lr = numpy.empty((k, n * 2, 3), dtype="f4")
        numpy.subtract(W, side, out=lr[:, :n])
        numpy.add(W, side, out=lr[:, n:])
        V = lr[:, vidx]                                      # (K, 6m, 3)

        cols = numpy.array([r[1] for r in recs], dtype="f4")  # (K, 4)
        av = alpha * cols[:, 3:4]
        C = numpy.empty((k, six, 4), dtype="f4")
        C[:] = cols[:, None, :]
        C[:, :, 3] = av[:, aidx]

        cn0 = recs[0][3]
        if cn0:
            cn = numpy.array([r[3] for r in recs], dtype="f4")   # (K, 4, 2)
            uvlr = numpy.empty((k, n * 2, 2), dtype="f4")
            bl = cn[:, 0:1, :]
            br = cn[:, 1:2, :]
            uvlr[:, :n] = bl + (cn[:, 3:4, :] - bl) * ucol       # 左：BL → TL
            uvlr[:, n:] = br + (cn[:, 2:3, :] - br) * ucol       # 右：BR → TR
            U = uvlr[:, vidx]
            cores = numpy.array([(r[2] if r[2] is not None else r[1])
                                 for r in recs], dtype="f4")
            C2 = numpy.empty((k, six, 4), dtype="f4")
            C2[:] = cores[:, None, :]
            C2[:, :, 3] = C[:, :, 3]
        else:
            U = C2 = None

        V = V.reshape(-1, 3)
        C = C.reshape(-1, 4)
        if U is not None:
            U = U.reshape(-1, 2)
            C2 = C2.reshape(-1, 4)

        # 段方向与视线平行时叉乘退化，那一段不画（两端有一端退化就整段丢）
        if not good.all():
            keep = numpy.repeat(good[:, :-1] & good[:, 1:], 6, axis=1).reshape(-1)
            V = V[keep]
            C = C[keep]
            if U is not None:
                U = U[keep]
                C2 = C2[keep]
        if not len(V):
            continue
        out.append((V, C, None if U is None else (U, C2)))

    chunks.extend(out)


def _emit_ribbon(verts, colors, uvs, item, col, size_mul, world_fn, view_dir,
                 corners=None, col2s=None, core=None):
    """条带 → 三角形（`uvs` 非 None 时同时产出逐顶点 UV）。

    每一段的「横向」取 `段方向 × 视线` 并归一化——这样条带永远把宽面朝向相机，
    是 Trail Renderer 的标准做法。段方向与视线平行时（正对着看）叉乘退化，
    这一段就跳过，不画烂三角。

    UV：横向铺满这一格（s: 左 0 → 右 1），纵向沿条带铺满（t: 尾 0 → 头 1），
    四角之间双线性插值——这样序列帧的翻转/90° 旋转对条带同样生效。

    这是 numpy 缺席时的兜底路（有 numpy 走成批的 `_emit_ribbons_np`）。逐行的
    UV/颜色都**先按顶点行算好再展开成三角**，别在每段里重算一遍——相邻两段共用
    同一行，照四角逐段插值等于把每行算两遍。
    """
    pts = item.points
    if not pts or len(pts) < 2:
        return
    n = len(pts)

    world = [world_fn(q) for q, _hw, _a in pts]
    sides = []
    for i in range(n):
        a = world[i - 1] if i else world[0]
        b = world[i + 1] if i < n - 1 else world[n - 1]
        s = _norm(_cross((b[0] - a[0], b[1] - a[1], b[2] - a[2]), view_dir))
        sides.append(s)

    k = size_mul * _UNIT
    ca, cb, cc, cd = col[0], col[1], col[2], col[3]
    core_rgb = core if core is not None else col

    # 逐**顶点行**先算好：左右两侧的世界坐标、颜色、UV。三角只是这些行的排列组合。
    lo = []
    hi = []
    rowc = []
    for i in range(n):
        s = sides[i]
        _q, hw, am = pts[i]
        if s is None:
            lo.append(None)
            hi.append(None)
        else:
            w = world[i]
            h = max(1e-5, abs(hw) * k)
            lo.append((w[0] - s[0] * h, w[1] - s[1] * h, w[2] - s[2] * h))
            hi.append((w[0] + s[0] * h, w[1] + s[1] * h, w[2] + s[2] * h))
        rowc.append((ca, cb, cc, cd * am))

    if uvs is not None and corners:
        bl, br, tr_, tl = corners
        span = float(n - 1)
        uvl = []
        uvr = []
        for i in range(n):
            t = i / span
            uvl.append((bl[0] + (tl[0] - bl[0]) * t, bl[1] + (tl[1] - bl[1]) * t))
            uvr.append((br[0] + (tr_[0] - br[0]) * t, br[1] + (tr_[1] - br[1]) * t))
    else:
        uvl = uvr = None

    for i in range(n - 1):
        l0 = lo[i]
        l1 = lo[i + 1]
        if l0 is None or l1 is None:
            continue
        r0 = hi[i]
        r1 = hi[i + 1]
        a0 = rowc[i]
        a1 = rowc[i + 1]
        verts.extend((l0, r0, r1, l0, r1, l1))
        colors.extend((a0, a0, a1, a0, a1, a1))
        if col2s is not None:
            b0 = (core_rgb[0], core_rgb[1], core_rgb[2], a0[3])
            b1 = (core_rgb[0], core_rgb[1], core_rgb[2], a1[3])
            col2s.extend((b0, b0, b1, b0, b1, b1))
        if uvl is not None:
            u_l0 = uvl[i]
            u_r0 = uvr[i]
            u_l1 = uvl[i + 1]
            u_r1 = uvr[i + 1]
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


def _mesh_tris_game_multi(mesh_objs):
    """同一 viscon 组常常由好几个 Sub 网格拼成——把它们的三角顶点（各自走
    `_mesh_tris_game` 换算+缓存）拼成一份，缓存 key 用全部对象名排序后的 tuple。

    UV 要求全体都有才拼（否则贴图坐标对不上、干脆整体退回纯色桶，同单网格没有
    UV 时的既有降级路径一致）。
    """
    objs = [m for m in mesh_objs if m is not None]
    if not objs:
        return _mesh_tris_game(None)
    if len(objs) == 1:
        return _mesh_tris_game(objs[0])

    key = tuple(sorted(o.name for o in objs))
    cached = _P["mesh_cache"].get(key)
    if cached is not None:
        return cached

    parts = [_mesh_tris_game(o) for o in objs]
    tris = []
    for t, _a, _u in parts:
        tris.extend(t)
    uvs = None
    if all(u is not None for _t, _a, u in parts):
        uvs = []
        for _t, _a, u in parts:
            uvs.extend(u)
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

    space = _P.get("mesh_rot_space") or "game"
    if turning and space == "game":
        # 在游戏坐标系里转，再换轴（= M·R·M⁻¹，M=Rx(90°)）。
        #
        # 两条互相独立的实测都指向这一支：
        #   MOD_aura2 的 ROTATEANIM spin_velocity.z=1 —— 转轴要平行于 Blender Y
        #     （'game' 给 Y、'local' 给 Z）
        #   MOD_aura2 的 MESH.rotation 是 game Y=4 —— transform_sync 把它摆成
        #     Blender Z=4°（'game' 给 Z、'local' 给 Y）
        # 后一条尤其硬：那是另一条独立写成的代码路径算出来的同一个结论。
        lin = _mat3_mul(m3, _mat3_mul(au, _mat3_mul(rot3(), scl)))
    elif turning:
        # 'local'：换完轴再在网格自己的 Blender 局部系里转。留作对照。
        lin = _mat3_mul(m3, _mat3_mul(rot3(), _mat3_mul(au, scl)))
    else:
        lin = _mat3_mul(m3, _mat3_mul(au, scl))

    px, py, pz = item.pos.x, item.pos.y, item.pos.z
    bx, by, bz = px * _UNIT, -pz * _UNIT, py * _UNIT
    t = (m3[0][0] * bx + m3[0][1] * by + m3[0][2] * bz + r0[3],
         m3[1][0] * bx + m3[1][1] * by + m3[1][2] * bz + r1[3],
         m3[2][0] * bx + m3[2][1] * by + m3[2][2] * bz + r2[3])
    return lin, t


def _bound_meshes_for(entry_obj, viscon=None):
    """entry 下 MESH 属性绑定的网格对象列表，按 viscon（Visible Condition）过滤。

    优先用 `efx_mesh_targets`（mod3_link 按 visconIndex/visconIndexJitter 范围绑的
    多网格，同一组常有好几个 Sub 网格）；没有精确命中该 viscon 时（超出范围/老
    数据没有分组信息）退回单体 `efx_mesh_target`，保证预览不会因为一次没打中
    随机范围就整个不画。
    """
    for blk in _entry_attributes(entry_obj):
        try:
            targets = blk.efx_mesh_targets
        except Exception:
            targets = None
        if targets:
            matches = [it.obj for it in targets
                       if it.obj is not None and getattr(it.obj, "type", None) == "MESH"
                       and (viscon is None or it.viscon == viscon)]
            if matches:
                return matches
        try:
            tgt = getattr(blk, "efx_mesh_target", None)
        except Exception:
            tgt = None
        if tgt is not None and getattr(tgt, "type", None) == "MESH":
            return [tgt]
    return []


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

#: `alphaFix` = (lowPass, contrast_gamma, lumaAsAlpha)，中性值 (0, 1, 0)。
#: 第三位把**贴图 RGB 的明暗当成 alpha**：`_BM`/flow 这类贴图是 RGB-only 的，
#: alpha 通道恒 1，照实取 alpha 画出来会连黑底一起变成不透明的一整片。
#: ALPHACORRECTION 是**逐纹素**
#: 改贴图 alpha 的形状（硬阈值裁切 + 伽马），只有在这里做才是对的。
#: 两层染色（RGBFIRE/RGBWATER）按**贴图亮度**在外缘色与核心色之间插值：笔画核心亮
#: → 取核心色，边缘暗 → 取外缘色。没有第二层时 col2 == color，mix 自动退化成恒等。
#:
#: ⚠ 最终色只乘贴图**亮度**（`lum`），不乘贴图的 RGB 本身——用户实机对拍确认：
#: RIBBON 设纯饱和蓝，贴图（cm_elec_902_BM，实测不透明区平均 R0.34/G0.62/B0.19，
#: 明显偏绿）绑着的情况下，游戏里显示的仍是纯蓝，贴图自己的色相完全不参与，只提供
#: 形状/亮度。之前这里写的是 `t.rgb * rgb`——贴图当"有色贴图"参与调色，蓝乘绿贴图
#: 蓝通道被摁低、算出来反而绿占主导，这是把 tint 蓝显示成绿的根因。
_FRAG_SRC = """
void main()
{
  vec4 t = texture(image, v_uv);
  float lum = max(t.r, max(t.g, t.b));
  vec3 rgb = mix(v_col.rgb, v_col2.rgb, lum);
  float a = mix(t.a, lum, alphaFix.z);
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  fragColor = vec4(lum * rgb, a * v_col.a);
}
"""


#: 折射的贴图 shader（pos + uv + color + sampler2D）。语义同 `_REFR_FRAG_SRC`。
_REFR_SHADER = None
_REFR_SHADER_KEEP = []

_REFR_VERT_SRC = """
void main()
{
  v_uv = uv;
  v_col = color;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

#: 乘法通道 + 贴图：源色 = 贴图 RGB × 渲染体颜色 × brightness，按覆盖度混向
#: 「无操作(1,1,1)」——贴图之外和淡出的时候都不改变背景。
#:
#: 覆盖度沿用整条管线那一套（`alphaFix`，见 `_FRAG_SRC`）：`_BM`/flow 这类
#: RGB-only 贴图用亮度当 alpha，ALPHACORRECTION 的阈值/伽马也照样生效。
#:
#: ⚠ 贴图 RGB 当颜色乘是**推断**：实测的那个样本没有 UVSEQUENCE，所以只坐实了
#: 「颜色 × brightness」那一半。而带折射的官方 entry 100% 挂 UVSEQUENCE，其中
#: `cm_smoke_905_BM` 在不透明区的通道形态（B 恒高 0.63~0.94、G 跨 0.5 两侧）
#: 更像切线空间法线图而不是颜色——真是法线的话这里就该拿去算位移而不是相乘。
#: 等 pixelNormalOffset 那一档实测了再回来改。
#: `refrParam` = (贴图 RGB 的参与度, 预览放大倍数)，见 `efx_sim_refraction_tex`
#: 与 `efx_sim_refraction_gain`。参与度 0 = 贴图只当遮罩、RGB 不进源色。
_REFR_FRAG_SRC = """
void main()
{
  vec4 t = texture(image, v_uv);
  float lum = max(t.r, max(t.g, t.b));
  float a = mix(t.a, lum, alphaFix.z);
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  a *= clamp(v_col.a, 0.0, 1.0) * refrParam.y;
  vec3 src = mix(vec3(1.0), t.rgb, refrParam.x) * v_col.rgb;
  fragColor = vec4(mix(vec3(1.0), src, a), 1.0);
}
"""


def _refraction_shader():
    """折射的贴图 shader；建不出来返回 None（调用方退回纯色乘法）。"""
    global _REFR_SHADER
    if _REFR_SHADER is not None:
        return _REFR_SHADER or None
    try:
        import gpu
        iface = gpu.types.GPUStageInterfaceInfo("efx_refr_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC4", "v_col")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC3", "alphaFix")
        info.push_constant("VEC2", "refrParam")
        info.sampler(0, "FLOAT_2D", "image")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(_REFR_VERT_SRC)
        info.fragment_source(_REFR_FRAG_SRC)
        _REFR_SHADER = gpu.shader.create_from_info(info)
        _REFR_SHADER_KEEP[:] = [iface, info]
    except Exception:
        _REFR_SHADER = False
    return _REFR_SHADER or None


#: flowmap shader：在 `_tex_shader` 基础上，先按流动贴图把 UV 推一下再采样。
_FLOW_SHADER = None
_FLOW_SHADER_KEEP = []

_FLOW_VERT_SRC = """
void main()
{
  v_uv = uv;
  v_col = color;
  v_col2 = col2;
  v_luv = luv;
  v_flowoff = flowoff;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

#: 流动贴图是切线空间法线图（语料里那 11 张全叫 `_NM`，实测 R 居中 0.5、B 恒高
#: 0.82~1.0），`rg × 2 − 1` 就是二维流动方向。按**局部** UV 采它——它是整张独立
#: 的图，不跟着序列帧的子格走；推出来的位移量已经在 CPU 侧乘过格子尺寸。
#: 其余（双层染色、alpha 修正）与 `_FRAG_SRC` 完全一致，只是采样点变了。
_FLOW_FRAG_SRC = """
void main()
{
  vec2 f = texture(flowTex, v_luv).rg * 2.0 - 1.0;
  vec4 t = texture(image, v_uv + f * v_flowoff);
  float lum = max(t.r, max(t.g, t.b));
  vec3 rgb = mix(v_col.rgb, v_col2.rgb, lum);
  float a = mix(t.a, lum, alphaFix.z);
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  fragColor = vec4(lum * rgb, a * v_col.a);
}
"""


def _flow_shader():
    """带流动贴图的 shader；建不出来返回 None（调用方退回普通贴图 shader）。"""
    global _FLOW_SHADER
    if _FLOW_SHADER is not None:
        return _FLOW_SHADER or None
    try:
        import gpu
        iface = gpu.types.GPUStageInterfaceInfo("efx_flow_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC4", "v_col")
        iface.smooth("VEC4", "v_col2")
        iface.smooth("VEC2", "v_luv")
        iface.smooth("VEC2", "v_flowoff")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC3", "alphaFix")
        info.sampler(0, "FLOAT_2D", "image")
        info.sampler(1, "FLOAT_2D", "flowTex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_in(3, "VEC4", "col2")
        info.vertex_in(4, "VEC2", "luv")
        info.vertex_in(5, "VEC2", "flowoff")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(_FLOW_VERT_SRC)
        info.fragment_source(_FLOW_FRAG_SRC)
        _FLOW_SHADER = gpu.shader.create_from_info(info)
        _FLOW_SHADER_KEEP[:] = [iface, info]
    except Exception:
        _FLOW_SHADER = False
    return _FLOW_SHADER or None


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
        info.push_constant("VEC3", "alphaFix")
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


def _clear_refraction_shader():
    global _REFR_SHADER, _FLOW_SHADER
    _REFR_SHADER = None
    _REFR_SHADER_KEEP[:] = []
    _FLOW_SHADER = None
    _FLOW_SHADER_KEEP[:] = []


def _clear_tex_cache():
    _GPU_TEX.clear()
    _TEX_ALPHA_USABLE.clear()


def _collect_track(tr, scene, rv3d, buckets, points, point_colors, lines,
                   line_colors):
    """一条 track 的 RenderItem → 顶点桶。

    桶的 key 是 `(混合模式, 贴图名)`：多选同时模拟时各 entry 用各自的序列帧大图，
    按图分桶就能一次 batch 画完同一张图的所有片，不必逐粒子换绑定。
    """
    items = tr.get("items") or ()
    rows = tr.get("ref_rows")
    entry = bpy.data.objects.get(tr["entry_name"])
    if rows is None or entry is None:
        return
    r0, r1, r2 = rows
    show_shape = bool(getattr(scene, "efx_sim_show_shape", False))
    if not items and not show_shape:
        return          # 没粒子也没要画形状 → 后面那一堆准备工作全省了

    size_mul = float(getattr(scene, "efx_sim_particle_size", 1.0))
    draw_mode = getattr(scene, "efx_sim_draw_mode", "QUADS")
    blend = getattr(scene, "efx_sim_blend", "AUTO")
    hdr_mode = getattr(scene, "efx_sim_hdr_mode", "preserve_hue")
    # 逐帧读一次存进 _P：`_mesh_affine` 是逐粒子调的，在那里读 Scene 属性等于
    # 每个粒子过一次 RNA
    _P["mesh_rot_space"] = getattr(scene, "efx_sim_mesh_rot_space", "game")
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
    #: 条带的 numpy 快路径常量（仿射矩阵 + 视线）。拿不到 numpy 就是 None，
    #: `_emit_ribbon` 自动退回纯 Python。
    np_ctx = _ribbon_np_ctx(rows, view_dir)

    def _order_of(it):
        """这一项属于哪个 entry → 绘制次序键。子实例（PtLife → Action）属于别的
        entry，按**它自己**那个 entry 的次序排。

        ⚠ 游戏里子实例究竟按子 entry 的次序排、还是按父粒子的生成时机排，没有实测
        依据；这里取前者（与文件内的静态次序一致，至少是可预期的）。
        """
        key = it.extra.get("entry_key")
        if not key:
            return track_order
        got = order_memo.get(key)
        if got is None:
            got = entry_order(bpy.data.objects.get(key)) if key else track_order
            order_memo[key] = got
        return got

    def _flow_of(it, tex):
        """这一项的 (flowmap 贴图名, 位移量)；不该走 flowmap 就 ("", 0.0)。

        没有序列帧贴图就没有可推的 UV，直接不走——`use_tex` 关掉时同理。
        """
        if not tex or not flow_images:
            return "", 0.0
        amt = it.extra.get("flowmap")
        if not amt:
            return "", 0.0
        name = flow_images.get(it.extra.get("entry_key"), root_flow)
        if not name or _gpu_texture(name) is None:
            return "", 0.0
        return name, float(amt) * flow_gain

    def _bucket_for(it, tex, flow_tex=""):
        """返回 `(桶 key, 桶)`。key = (绘制次序, 混合模式, 贴图, alpha 修正, 流动贴图)。

        次序键放最前面：完全重合的面片谁盖谁由绘制顺序决定（粒子不写深度），而实机
        是按 entry 在文件里的排布定的，所以桶必须能按它排序，见 `entry_order`。

        alpha 修正（ALPHACORRECTION）是 shader 的 push constant，逐 draw 生效，所以
        也必须进 key。两者都是**逐 entry**的，一个场景里就那么几种取值，分桶开销可忽略。
        """
        mode = it.blend
        if mode == "MULTIPLY":
            # 折射是整条通道的性质（REFRACTION 覆盖渲染体自己的 blendMode，实机
            # 确认），不该被「强制混合模式」那个调试开关顶掉
            pass
        elif blend != "AUTO":
            mode = blend
        if mode not in ("ALPHA", "ADDITIVE", "MULTIPLY"):
            mode = "ALPHA"
        low, gamma = it.extra.get("alpha_fix") or (0.0, 1.0)
        if luma_mode == "auto":
            luma = 0.0 if _texture_alpha_is_usable(tex) else 1.0
        else:
            luma = 1.0 if luma_mode == "on" else 0.0
        key = (_order_of(it), mode, tex, (low, gamma, luma), flow_tex)
        b = buckets.get(key)
        if b is None:
            # 第 4 条是双层染色的核心色；和 uv 一样只有走贴图 shader 的桶才需要。
            # 第 5 条是网格的 numpy 分块 [(顶点, 颜色), …]：静态网格整块过同一个矩阵，
            # 留在 numpy 里到画之前才拼，省掉 tolist（51200 面时那一步占六成时间）。
            # 第 6/7 条是 flowmap 的局部 UV 与逐粒子位移量，只有流动桶才有。
            b = [[], [], ([] if tex else None), ([] if tex else None), [],
                 ([] if flow_tex else None), ([] if flow_tex else None)]
            buckets[key] = b
        return key, b

    #: 这一趟里「(entry, viscon) → 网格三角」的记忆。`_bound_meshes_for` 要遍历
    #: entry 的属性列表、前面还要 `bpy.data.objects.get`——逐粒子做就是每个粒子一次
    #: 小扫描，粒子一多就是网格路径的主要固定开销（实测占每粒子 120 µs 里的大半）。
    #: 同一 entry + 同一 viscon 只查一次。
    mesh_memo = {}
    #: entry 名 → 绘制次序键。子实例每帧都要查，缓存一下别逐粒子反查集合
    order_memo = {}
    track_order = tr.get("order") or ("", 0)
    mat_images = tr.get("mesh_images") or {}
    flow_images = (tr.get("flow_images") or {}) if use_tex else {}
    root_flow = flow_images.get(tr["entry_name"], "")
    flow_gain = float(getattr(scene, "efx_sim_flowmap_gain", 1.0))
    luma_mode = getattr(scene, "efx_sim_alpha_source", "auto")
    #: 折射的预览放大倍数（见 `efx_sim_refraction_gain`）。没贴图那条路在 CPU 侧
    #: 折进源色，有贴图那条交给 shader，两边都是「乘在混合系数上」。
    refr_gain = float(getattr(scene, "efx_sim_refraction_gain", 1.0))

    def _geom_of(it):
        """(几何, 贴图名)。贴图来自绑定网格自己的材质——reference mesh 那条链已经把
        材质和贴图建好了，我们只取用不解析。`use_tex` 关掉时退回纯色桶。

        ⚠ 缓存 key 要带上 viscon：同一 entry 下不同粒子可能因 visconIndexJitter
        各自摇到不同的组（`me_viscon`，见 behaviors/mesh.py），只按 entry 缓存会
        让后到的粒子沿用第一个粒子摇到的那组网格，"随机换网格"的效果就没了。
        """
        key = it.extra.get("entry_key") or ""
        viscon = it.extra.get("viscon")
        memo_key = (key, viscon)
        got = mesh_memo.get(memo_key)
        if got is None:
            owner = bpy.data.objects.get(key) or entry
            meshes = _bound_meshes_for(owner, viscon)
            if not meshes:
                # 没绑 mod3 → 画的是占位方块，面板上要说清楚（方块是对称的，
                # 看不出旋转对不对，容易被误判成「旋转没实现」）
                miss = tr.setdefault("mesh_missing", [])
                nm = getattr(owner, "name", "") or "?"
                if nm not in miss:
                    miss.append(nm)
            m0 = meshes[0] if meshes else None
            # MATERIAL 指定的贴图优先；没有（或没载上）才退回 mod3 自带材质那张
            name = (mat_images.get(key) or _mesh_image_name(m0)) if use_tex else ""
            if name and _gpu_texture(name) is None:
                name = ""
            got = (_mesh_tris_game_multi(meshes), name)
            mesh_memo[memo_key] = got
        return got

    def _corners_of(it, tex_name):
        """这一项的四角 UV，含 UVCONTROL 的滚动/缩放。"""
        c = _uv_corners(it, flip_v, tex_name)
        xf = it.extra.get("uv_xform")
        if not xf or not c:
            return c
        su, sv, ou, ov = xf
        return tuple((u * su + ou, v * sv + ov) for (u, v) in c)

    def _layers_of(it, col, tex=""):
        """(外缘色, 核心色)：没挂双层染色就两边都用 col，shader 里 mix 退化成恒等。

        折射（乘法）不走双层染色那套——它是给加法/Alpha 的显示变换，套进来会把
        brightness 归一化掉。折射的源色按有没有贴图分两条：

        * **有贴图** → 原样传，逐纹素的遮罩和淡出都交给 `_refraction_shader`
          （`mix(1, 贴图×颜色, 覆盖度×alpha)`）。
        * **没贴图** → 走 FLAT_COLOR，shader 里没法混，只能在这里把 alpha 折进
          RGB，见 `_multiply_tint`。
        """
        if it.blend == "MULTIPLY":
            c = col if tex else _multiply_tint(col, refr_gain)
            return c, c
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

    #: 桶 key → (桶, [(渲染项, 外缘色, 核心色, UV 四角), …])。条带不当场展开，
    #: 攒到这一趟走完再整批过 numpy，见 `_emit_ribbons_np`。
    ribbon_pend = {}

    if show_shape:
        # 生成区域的线框。用的是**模拟器自己**那份读法（见
        # behaviors/emittershape3d.py::outline），所以框和粒子真正的落点必然一致
        # ——两边各算一遍迟早会走样。并进速度线那条现成的 LINES 叠加层。
        try:
            pts = tr["sim"].emitter_outline()
        except Exception:
            pts = ()
        col_shape = (0.35, 0.75, 1.0, 0.55)
        for i in range(0, len(pts) - 1, 2):
            lines.append(_world(pts[i]))
            lines.append(_world(pts[i + 1]))
            line_colors.append(col_shape)
            line_colors.append(col_shape)

    for it in items:
        center = _world(it.pos)
        tex_name = _tex_of(it)
        if it.blend == "MULTIPLY":
            # 折射走乘法：输出 = 背后画面 × (贴图 × 颜色 × brightness)。
            # ⚠ 这里**不能**过 `_display_color` —— 那是给加法/Alpha 用的 HDR 压缩，
            #   会把 brightness 归一化掉，而乘法通道正要靠它（实机：白色
            #   brightness=10 明显提亮背景、改成 1 则面片完全消失）。
            col = tuple(it.color)
        else:
            col = _display_color(it.color, hdr_mode)
        kind = it.kind

        if kind == "RIBBON" and it.points:
            key, b = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col, tex_name)
            corners = _corners_of(it, tex_name)
            if np_ctx is not None:
                # 攒着，等这一趟走完再按桶成批算（见 `_emit_ribbons_np`）
                pend = ribbon_pend.get(key)
                if pend is None:
                    pend = ribbon_pend[key] = (b, [])
                pend[1].append((it, edge, core, corners))
            else:
                _emit_ribbon(b[0], b[1], b[2], it, edge, size_mul, _world,
                             view_dir, corners, col2s=b[3], core=core)
        elif kind == "MESH":
            # 网格用自己的 UV（来自 mod3），我们没收集 → 始终走纯色桶。
            # ⚠ 绑定网格要按**这一项所属的 entry**查：子实例是别的 entry，
            # 拿根 entry 的绑定会让所有子特效都画成根的那个网格。
            geom, tex_name = _geom_of(it)
            _key, (bv, bc, bu, b2, bnp, _lu, _fo) = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col, tex_name)
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
            flow_tex, flow_amt = _flow_of(it, tex_name)
            _key, (bv, bc, bu, b2, _np, blu, bfo) = _bucket_for(it, tex_name, flow_tex)
            edge, core = _layers_of(it, col, tex_name)
            bv.extend(_quad_verts(center, qr, qu, hw, hh))
            bc.extend([edge] * 6)
            if b2 is not None:
                b2.extend([(core[0], core[1], core[2], edge[3])] * 6)
            corners = _corners_of(it, tex_name) if bu is not None else None
            if bu is not None:
                bu.extend(_quad_uvs(corners))
            if blu is not None:
                # 位移量是**相对这一格**的：strength 0.2 若按整张大图算，一步就跨过
                # 一格半；按格子算才是「在自己这一帧里推一点点」
                us = [c[0] for c in corners]
                vs = [c[1] for c in corners]
                off = (flow_amt * (max(us) - min(us)),
                       flow_amt * (max(vs) - min(vs)))
                blu.extend(_QUAD_LUV)
                bfo.extend([off] * 6)

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

    for b, group in ribbon_pend.values():
        try:
            _emit_ribbons_np(b[4], group, size_mul, np_ctx)
        except Exception:
            # numpy 那条整组失败就整组退回纯 Python（`_emit_ribbons_np` 保证
            # 失败时一个分块都没并进桶，不会画出半截）
            for it, edge, core, corners in group:
                _emit_ribbon(b[0], b[1], b[2], it, edge, size_mul, _world,
                             view_dir, corners, col2s=b[3], core=core)


#: 参与绘制缓存签名的 Scene 旋钮：任一变了就得重新装配顶点。
_DRAW_KNOBS = ("efx_sim_particle_size", "efx_sim_draw_mode", "efx_sim_blend",
               "efx_sim_hdr_mode", "efx_sim_mesh_rot_space",
               "efx_sim_show_velocity", "efx_sim_uv_flip_v", "efx_sim_textured",
               "efx_sim_alpha_source", "efx_sim_draw_order", "efx_sim_point_px",
               "efx_sim_ribbon_subdiv_max",
               "efx_sim_refraction_tex", "efx_sim_refraction_gain",
               "efx_sim_flowmap_gain", "efx_sim_show_shape")


def _draw_signature(scene, rv3d, trs):
    """「这一次画的东西和上次一模一样吗」的判据。

    顶点装配只依赖这四样：渲染项的版本号、视角（面片朝相机）、这些旋钮、
    各 track 的参考矩阵。全都没变就直接重画上次烘好的 batch。
    """
    vm = rv3d.view_matrix
    return (_P["gen"],
            tuple(vm[i][j] for i in range(4) for j in range(4)),
            tuple(getattr(scene, k, None) for k in _DRAW_KNOBS),
            tuple(t.get("ref_rows") for t in trs))


def _build_payload(scene, rv3d, trs):
    """收集顶点并**当场烘成 GPUBatch**，返回可反复画的负载。

    烘成 batch 而不是留着顶点列表：`batch_for_shader` 本身在几十万顶点时也要十几
    毫秒，而视口一帧里可能被重绘好几次（鼠标划过、叠加层刷新），没理由每次都重传。
    """
    from gpu_extras.batch import batch_for_shader

    buckets = {}          # (次序, 混合模式, 贴图名, alpha 修正) -> [顶点, 颜色, UV|None, 核心色|None, numpy 分块]
    points, point_colors, lines, line_colors = [], [], [], []
    for tr in trs:
        _collect_track(tr, scene, rv3d, buckets, points, point_colors,
                       lines, line_colors)
    try:
        flat = _builtin("FLAT_COLOR")
    except Exception:
        return None
    tex_shader = _tex_shader()
    flow_shader = _flow_shader()

    # 先 Alpha 再 Add：加法混合的东西通常是最亮的高光，压在最后一层
    # 绘制顺序 = 桶 key 的次序（entry 在文件里的排布），见 `entry_order`。
    # 'alpha_first' 退回改动前的「先所有 Alpha 再所有 Add」。
    # ⚠ 两者不等价：加法之间可交换，但**加法与 Alpha 之间不可交换**——一个 Alpha
    # 面片画在加法之后会把已经加上去的光按 (1-a) 衰减掉。要照实机的覆盖关系来，
    # 就得让这个启发式让位。
    if getattr(scene, "efx_sim_draw_order", "entry") == "entry":
        order = sorted(buckets.keys())
    else:
        order = sorted(buckets.keys(), key=lambda k: (k[1] == "ADDITIVE",))

    refr_shader = _refraction_shader()
    refr_param = (0.0 if getattr(scene, "efx_sim_refraction_tex", "color") == "mask"
                  else 1.0,
                  float(getattr(scene, "efx_sim_refraction_gain", 1.0)))
    tris = []
    for key in order:
        bv, bc, bu, b2, bnp, blu, bfo = buckets[key]
        if not (bv or bnp):
            continue
        _bo, mode, tex_name, fix, flow_name = key
        if bnp:
            bv, bc, bu, b2 = _join_chunks(bv, bc, bu, b2, bnp)
        tex = _gpu_texture(tex_name) if (bu is not None) else None
        # ⚠ 折射排在 flowmap 前面：折射换掉的是整条输出通道，flowmap 只推 UV，
        # 两者撞车时丢掉后者损失小。语料里同时有这两样的 entry 只占 3.4%，
        # 核心层会在那些 entry 上如实记一条 note。
        ftex = (_gpu_texture(flow_name)
                if (flow_name and blu is not None and mode != "MULTIPLY") else None)
        if ftex is not None and tex is not None and flow_shader is not None:
            tris.append((mode, flow_shader, (tex, ftex), fix,
                         batch_for_shader(flow_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "col2": b2, "luv": blu,
                                           "flowoff": bfo})))
            continue
        if mode == "MULTIPLY":
            # 折射：源色已经在 `_multiply_tint` 里折好了，shader 只负责遮罩。
            # 没贴图（或 shader 建不出来）就整片乘——实测样本正是这一档。
            if tex is not None and refr_shader is not None:
                tris.append((mode, refr_shader, tex, (fix, refr_param),
                             batch_for_shader(refr_shader, "TRIS",
                                              {"pos": bv, "uv": bu, "color": bc})))
            else:
                tris.append((mode, flat, None, None,
                             batch_for_shader(flat, "TRIS",
                                              {"pos": bv, "color": bc})))
        elif tex is not None and tex_shader is not None:
            tris.append((mode, tex_shader, tex, fix,
                         batch_for_shader(tex_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "col2": b2})))
        else:
            tris.append((mode, flat, None, None,
                         batch_for_shader(flat, "TRIS",
                                          {"pos": bv, "color": bc})))

    pt = (batch_for_shader(flat, "POINTS",
                           {"pos": points, "color": point_colors})
          if points else None)
    ln = (batch_for_shader(flat, "LINES",
                           {"pos": lines, "color": line_colors})
          if lines else None)
    return (tris, flat, pt, ln)


def _draw():
    """POST_VIEW draw handler。**不改任何状态**，只画各 track 的 items。"""
    if not is_active():
        return
    trs = [t for t in _P["tracks"] if t.get("items")]
    if not trs:
        return

    try:
        import gpu
    except ImportError:
        return

    context = bpy.context
    rv3d = getattr(context, "region_data", None)
    if rv3d is not None:
        _P["cam_fwd"] = _view_direction(rv3d)
    if rv3d is None:
        return
    scene = context.scene

    # 逐 region 缓存：分屏时两个视口视角不同，各存各的。
    # ⚠ 键要用 `as_pointer()`（底层 C 地址）——`id()` 拿到的是这一次访问临时生成的
    # Python 包装对象，每次都不一样，缓存永远命中不了。
    try:
        ck = rv3d.as_pointer()
    except Exception:
        ck = id(rv3d)
    sig = _draw_signature(scene, rv3d, trs)
    got = _P["draw_cache"].get(ck)
    if got is None or got[0] != sig:
        payload = _build_payload(scene, rv3d, trs)
        if payload is None:
            return
        if len(_P["draw_cache"]) > 4:
            _P["draw_cache"].clear()    # 换布局会留下死 region，别无限长
        _P["draw_cache"][ck] = (sig, payload)
    else:
        payload = got[1]

    tris, flat, pt, ln = payload
    blend = getattr(scene, "efx_sim_blend", "AUTO")

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)      # 粒子之间不互相遮挡，但仍被场景几何遮挡
    try:
        for mode, shader, tex, fix, batch in tris:
            gpu.state.blend_set(mode)
            if tex is not None:
                shader.bind()
                if isinstance(tex, tuple):
                    # flowmap：主图 + 流动图两个采样器
                    shader.uniform_sampler("image", tex[0])
                    shader.uniform_sampler("flowTex", tex[1])
                else:
                    shader.uniform_sampler("image", tex)
                if isinstance(fix, tuple) and len(fix) == 2:
                    # 折射：(alphaFix, refrParam)
                    shader.uniform_float("alphaFix", fix[0])
                    shader.uniform_float("refrParam", fix[1])
                elif fix is not None:
                    # (lowPass, contrast_gamma, lumaAsAlpha)，中性值 (0, 1, 0)
                    shader.uniform_float("alphaFix", fix)
            batch.draw(shader)

        overlay = "ADDITIVE" if blend == "ADDITIVE" else "ALPHA"
        if pt is not None:
            gpu.state.blend_set(overlay)
            gpu.state.point_size_set(max(1.0, float(
                getattr(scene, "efx_sim_point_px", 4))))
            pt.draw(flat)
        if ln is not None:
            gpu.state.blend_set("ALPHA")     # 速度线是调试叠加层，别被加法混合冲白
            ln.draw(flat)
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
    _P["draw_cache"] = {}
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
    _P["needs_items"] = True    # 参数变了，即使这一 tick 不走帧也得重画
    _clear_tex_cache()          # 参考图可能被换了
    _clear_material_cache()     # MATERIAL 的贴图路径也可能被改过
    _clear_flow_cache()         # flowmap 的路径同理
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


def _rebuild_items():
    """重建全部 track 的渲染项，并让绘制缓存失效。"""
    for tr in _P["tracks"]:
        _build_items(tr)
    _P["needs_items"] = False
    _P["gen"] += 1


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
            _gc_hold(False)
            break

    # ⚠ 只有真走了帧（或参数被改过）才重建渲染项并请求重绘。定时器是固定
    # 1/120 s 的高频 tick，倍速低的时候大多数 tick 根本没推进——照旧无脑重建
    # 等于把最贵的两段（build_render + 顶点装配）白跑四五遍，而画面一模一样。
    # 这也正是「把倍速调到 0.5 却一点不见变快」的原因。
    if steps or _P["needs_items"]:
        # 抽帧显示（efx_sim_render_every）：模拟照样逐帧走，只是攒够 N 帧才重建
        # 一次画面。重文件里把它开到 2~3，时序仍然精确，肉眼只觉得帧率低一点。
        # 参数改过 / 暂停中要立刻看到结果，这两种情况不抽。
        every = max(1, int(getattr(scene, "efx_sim_render_every", 1)))
        _P["skipped"] = 0 if _P["needs_items"] else _P["skipped"] + steps
        if _P["needs_items"] or not _P["playing"] or _P["skipped"] >= every:
            _P["skipped"] = 0
            _rebuild_items()
            _redraw_viewports()



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
        # 点中根集合时活动对象未必是 entry（甚至可能没有），那条路照样能播整个文件
        if is_active():
            return False
        return (_resolve_entry(context.active_object) is not None
                or _active_root_collection(context) is not None)

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
        _P["needs_items"] = True
        _P["playing"] = True
        _gc_hold(True)

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
            elif _P["dirty"]:
                # 暂停中改字段同样要立刻看到结果。不能直接调 `_tick`——它会按墙钟
                # 往累加器里加时间，暂停的语义就没了。这里只重建、不走帧。
                _rebuild_if_dirty(context.scene)
                _rebuild_items()
                _redraw_viewports()
                _P["last_t"] = time.perf_counter()
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
        _restore_all_bone_follow()
        _P["tracks"] = []
        _P["mesh_cache"] = {}
        _clear_tex_cache()
        _gc_hold(False)
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
        _restore_all_bone_follow()
        _P["tracks"] = []
        _P["mesh_cache"] = {}
        _clear_tex_cache()
        _gc_hold(False)
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
        # 暂停是回收垃圾的好时机：这一下的开销用户感觉不到，继续播时再关掉
        _gc_hold(_P["playing"])
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
        _P["needs_items"] = True
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["playing"] = True
        _gc_hold(True)
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
        _rebuild_items()
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
    """粒子模拟播放器。独立于 EFX_PT_mesh_drive 那一族——那边是「给绑定网格挂驱动」
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

        entry = bool(_selected_entries(context))
        root = _active_root_collection(context)
        if not entry and root is None and not active:
            layout.label(text=T("sim.pick_entry"), icon="INFO")
            return

        # ── 播放范围：点中根集合时才有意义（选了具体 entry 就是播那些，没有"范围"
        # 一说）。"All" = 原行为（Direct Trigger 那批）；否则播指定 Subselect 的
        # members，即"这个装备状态/这套子选择实际会用到的那些特效"。
        if root is not None and not entry:
            row = layout.row()
            row.enabled = not active
            row.prop(scene, "efx_sim_scope", text=T("sim.scope"))

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


class _SimSubPanel(Panel):
    """播放器的可收起分组。父面板 `EFX_PT_sim` 里只留走带 + 读数 + 诊断，
    参数按「多久碰一次」分组塞进子面板——Blender 的子面板自带折叠状态记忆，
    跟 Calibration 用的是同一套（`bl_parent_id` + `bl_options`）。"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_parent_id = "EFX_PT_sim"

    @classmethod
    def poll(cls, context):
        # 父面板在「没选中 entry、没点中根集合、也没在播」时只画一句提示就 return，
        # 子面板要跟着一起消失，否则会剩下几个空壳标题。
        return (is_active() or _resolve_entry(context.active_object) is not None
                or _active_root_collection(context) is not None)


class EFX_PT_sim_playback(_SimSubPanel):
    """调得最勤的一组：循环方式/倍速/时长/种子 + 挥砍预览。默认展开。"""

    bl_idname = "EFX_PT_sim_playback"
    bl_label = "Playback"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.prop(scene, "efx_sim_mode", text="")
        col.prop(scene, "efx_sim_speed")
        col.prop(scene, "efx_sim_duration")
        col.prop(scene, "efx_sim_seed")

        # 挥砍预览：没有骨骼动画时，给 RIBBON/RIBBONBLADE 一点轨迹可画
        box = layout.box()
        box.label(text=T("sim.swing"), icon="CON_ROTLIKE")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_swing_enable")
        if getattr(scene, "efx_sim_swing_enable", False):
            col.prop(scene, "efx_sim_swing_axis", text="Axis")
            col.prop(scene, "efx_sim_swing_angle")
            col.prop(scene, "efx_sim_swing_radius")
            col.prop(scene, "efx_sim_swing_duration")


class EFX_PT_sim_display(_SimSubPanel):
    """设一次就不大动的一组：显示 / 性能 / 序列帧读数。默认收起。"""

    bl_idname = "EFX_PT_sim_display"
    bl_label = "Display & Performance"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active = is_active()
        trs = _P["tracks"]
        entry = _resolve_entry(context.active_object)

        # ── 显示 ─────────────────────────────────────────────────────────────
        col = layout.column(align=True)
        col.prop(scene, "efx_sim_draw_mode", text="")
        col.prop(scene, "efx_sim_blend", text="")
        col.prop(scene, "efx_sim_particle_size")
        if getattr(scene, "efx_sim_draw_mode", "QUADS") in ("POINTS", "BOTH"):
            col.prop(scene, "efx_sim_point_px")
        # 独立叠加层：不用播放、只画选中的那几个（见 es3d_overlay.py）
        from . import es3d_overlay as _es3do
        _es3do.draw_button(layout, context)
        col = layout.column(align=True)
        col.prop(scene, "efx_sim_show_shape")
        col.prop(scene, "efx_sim_show_velocity")
        col.prop(scene, "efx_sim_textured")
        if getattr(scene, "efx_sim_textured", True):
            col.prop(scene, "efx_sim_uv_flip_v")

        # ── 性能 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("sim.perf"), icon="SORTTIME")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_ribbon_subdiv_max")
        col.prop(scene, "efx_sim_particle_budget")
        col.prop(scene, "efx_sim_render_every")

        # ── 序列帧：帧表来源 + 现在放到第几格 ────────────────────────────────
        uvs = (trs[0].get("uvs") if trs else None) if active             else _uvs_state_info(entry)
        if uvs is None:
            return
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
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text=T("sim.calib_hint"), icon="INFO")
        col = layout.column(align=True)
        col.prop(scene, "efx_sim_jitter_mode")
        # efx_sim_es3d_range / efx_sim_t3d_vel_unit：不再列在这里——两条各自的
        # UNKNOWNS 描述都直接写了「另一个选项与实机对不上」（es3d_range_mode 的
        # minmax、t3d_velocity_unit 的 per_frame，见 config.py），不是「两个都说得
        # 通，等实测」那类真正待标定项。开关本身还留着（默认值已经是 shell /
        # per_second），只是没必要再占 Calibration 面板的位置。
        col.prop(scene, "efx_sim_spawn_jitter")
        col.prop(scene, "efx_sim_t3d_rot_sign")
        col.prop(scene, "efx_sim_material_slot")
        col.prop(scene, "efx_sim_alpha_source")
        col.prop(scene, "efx_sim_refraction_tex")
        col.prop(scene, "efx_sim_refraction_gain")
        col.prop(scene, "efx_sim_flowmap_speed_unit")
        col.prop(scene, "efx_sim_flowmap_phase")
        col.prop(scene, "efx_sim_flowmap_gain")
        col.prop(scene, "efx_sim_draw_order")
        col.prop(scene, "efx_sim_mesh_rot_space")
        col.prop(scene, "efx_sim_rgb_tint")
        col.prop(scene, "efx_sim_hdr_mode")
        col.prop(scene, "efx_sim_life_model")
        col.prop(scene, "efx_sim_a0_sample")
        col.prop(scene, "efx_sim_timl_mode")
        col.prop(scene, "efx_sim_timl_interp")
        col.prop(scene, "efx_sim_rot_order")
        col.prop(scene, "efx_sim_age_during_delay")
        col.prop(scene, "efx_sim_ribbon_length")
        col.prop(scene, "efx_sim_ribbon_rigid_dir")
        # HOMING 的其余开关（转弯重定轴 / 速度爬升曲线与圈数 / 力场倍率读法与
        # 恢复帧数 / 竖直压扁 axial_falloff）2026-09-12 已逐项拿游戏实拍标定完，
        # 不再占 Calibration 的位置——Scene 属性与 SimConfig 开关都还在，要对照
        # 旧行为直接在代码里改默认值即可。axis_update / retarget / axial_falloff
        # 在纯追踪默认下已经**没有意义**（每帧按当前几何重算转向，那几个结构性
        # 缺口本来就不存在），一并撤出面板。这里只留两项：HOMING 的驱动方式
        # （compose，默认纯追踪，留 add/override 对照被排除的两种读法），以及
        # lateral_tilt —— 它现在只管「穿过目标那一瞬间往哪边拐」这个退化点。
        col.prop(scene, "efx_sim_homing_compose")
        col.prop(scene, "efx_sim_homing_lateral_tilt")
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
    EFX_PT_sim_playback,
    EFX_PT_sim_display,
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
    S.efx_sim_scope = EnumProperty(
        name="Scope",
        description="Which entries to simulate when a root EFX collection (not a specific "
                    "entry) is selected",
        items=_sim_scope_items)
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

    # ── 挥砍预览：RIBBON/RIBBONBLADE 靠宿主位移画轨迹，没有骨骼动画时用这个代打 ──
    S.efx_sim_swing_enable = BoolProperty(
        name="Simulate Swing", default=False,
        description="Sweep the entry back and forth on a synthetic arc while playing "
                    "(this does not read any real bone animation). RIBBON/RIBBONBLADE "
                    "trails are drawn from how far the host itself moved, not from "
                    "particle velocity, so a still host never shows a trail - this is "
                    "a stand-in for that motion when there is no rig to play. Preview "
                    "only; mutes the entry's bone-follow constraint (if any) while active")
    S.efx_sim_swing_axis = EnumProperty(
        name="Swing axis",
        items=[("X", "X", "Arc lies in the Y/Z plane"),
               ("Y", "Y", "Arc lies in the Z/X plane"),
               ("Z", "Z", "Arc lies in the X/Y plane")],
        default="Z")
    S.efx_sim_swing_angle = FloatProperty(
        name="Swing angle", default=180.0, min=1.0, max=360.0, soft_max=270.0,
        description="Total angle swept between the two extremes of the arc, in degrees")
    S.efx_sim_swing_radius = FloatProperty(
        name="Swing radius", default=1.0, min=0.0, soft_max=5.0,
        description="Distance from the entry's rest position to the pivot it swings "
                    "around, in meters")
    S.efx_sim_swing_duration = FloatProperty(
        name="Swing duration", default=0.35, min=0.05, soft_max=2.0,
        description="Seconds for one sweep from one extreme to the other; the entry "
                    "keeps swinging back and forth at this pace while enabled")

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

    # ── 性能（预览降载；只影响画面精细度与刷新率，不碰文件）──────────────────
    S.efx_sim_ribbon_subdiv_max = IntProperty(
        name="Ribbon detail cap", default=0, min=0, soft_max=64,
        update=_on_knob_changed,
        description="Upper limit on how many points a ribbon is resampled to. "
                    "0 = use the subdivisionCount stored in the file. A 50-point "
                    "ribbon costs ~300 vertices per frame, and a PtLife tree can "
                    "hold thousands of them at once; capping it around 12 keeps "
                    "the shape and cuts most of the cost. Preview only")
    S.efx_sim_particle_budget = IntProperty(
        name="Particle budget", default=0, min=0, soft_max=5000,
        update=_on_knob_changed,
        description="Cap on how many particles the whole instance tree may hold at "
                    "once. 0 = the built-in ceiling (20000). Lowering it keeps a "
                    "dense PtLife tree from swamping the preview; the panel says so "
                    "when the cap is reached. Preview only")
    S.efx_sim_render_every = IntProperty(
        name="Draw every N frames", default=1, min=1, max=8,
        description="Rebuild the on-screen geometry only every N simulated frames. "
                    "The simulation still advances every frame, so timing stays "
                    "exact; only the picture updates less often")
    S.efx_sim_show_shape = BoolProperty(
        name="Emitter shape", default=False,
        description="Outline the region new particles are placed in "
                    "(EMITTERSHAPE3D). Drawn from the same reading the simulation "
                    "samples, so the outline and where particles actually appear "
                    "always agree. The root emitter only")
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
                "and the fade in and out both survive - the sprite reads dimmer "
                "than it does in game"),
               ("tonemap", "Tone map",
                "Roll bright colours off towards white, the way bloom does in game"),
               ("raw", "Clip",
                "Let the framebuffer clip them - matches what a single pixel does "
                "in game, but without its tone mapping a high brightness turns "
                "the whole sprite white")],
        default="preserve_hue")
    S.efx_sim_alpha_source = EnumProperty(
        name="Opacity from",
        items=[("auto", "Auto",
                "Per texture: use its alpha channel where that channel carries "
                "something, and how bright the texture is where it does not - "
                "flow and _BM textures have a flat alpha channel"),
               ("on", "Brightness", "Always use how bright the texture is"),
               ("off", "Alpha channel", "Always use the texture's alpha channel")],
        default="auto")
    S.efx_sim_flowmap_speed_unit = EnumProperty(
        name="Flowmap speed", update=_on_knob_changed,
        items=[("per_second", "Per second",
                "The stored speed is how many flow cycles pass in a second"),
               ("per_frame", "Per frame",
                "The stored speed is how many flow cycles pass in a single frame")],
        default="per_second")
    S.efx_sim_flowmap_phase = EnumProperty(
        name="Flowmap travel", update=_on_knob_changed,
        items=[("cycle", "Cycles",
                "Sweep back and forth over one flow cycle, so the distortion stays "
                "bounded however long a particle lives"),
               ("linear", "Keeps going",
                "Let the distortion build up with age, so a pixel keeps drifting "
                "the way the flowmap points")],
        default="cycle")
    S.efx_sim_refraction_tex = EnumProperty(
        name="Refraction sprite",
        items=[("color", "Tints the background",
                "Multiply the background by the sprite's own colour, so the sprite "
                "both shapes and tints the layer"),
               ("mask", "Shapes it only",
                "Use the sprite only to decide where the layer covers; its colour "
                "stays out, so a white renderer colour leaves the background alone")],
        default="mask")
    S.efx_sim_refraction_gain = FloatProperty(
        name="Refraction strength x", default=1.0, min=0.0, max=8.0,
        soft_min=0.0, soft_max=4.0,
        description="Magnifier on how far the refraction layer pushes the "
                    "background away from leaving it untouched. 1.0 = as authored; "
                    "0 = invisible; above 1 exaggerates it so a faint layer is easy "
                    "to place. Preview only")
    S.efx_sim_flowmap_gain = FloatProperty(
        name="Flowmap strength x", default=1.0, min=0.0, max=8.0,
        soft_min=0.0, soft_max=4.0,
        description="Magnifier on how far the flowmap pushes the sprite's pixels "
                    "around. 1.0 = the strength stored in the file; 0 = off, the "
                    "sprite stays still. Preview only")
    S.efx_sim_homing_converge = EnumProperty(
        name="Homing spiral",
        items=[("linear", "Even spacing",
                "Speed climbs by a fixed step, so the orbit widens by the same "
                "amount every lap and starts off very tight"),
               ("per_revolution", "Tightening",
                "Speed closes a fixed fraction of what is left each lap, so the "
                "spiral starts wide and the gaps shrink"),
               ("instant", "No spiral",
                "Jump straight to the target speed, so the orbit is its final "
                "size from the first frame")],
        default="linear")
    S.efx_sim_homing_ramp_turns = FloatProperty(
        name="Homing spiral laps", default=4.0, min=0.5, max=16.0,
        description="How many laps the orbit takes to grow from the starting "
                    "speed to the target speed. Only used by the even-spacing "
                    "spiral. Preview only")
    S.efx_sim_homing_ff_scale = EnumProperty(
        name="Homing force field",
        items=[("balanced", "Damped",
                "The field slows the particle down every frame while a steady pull "
                "brings its speed back up, so the orbit settles at a size that "
                "climbs steeply as the scale approaches 1"),
               ("per_frame", "Compounding",
                "The force field's speed scale is applied again every frame, so "
                "the particle keeps slowing down and its orbit tightens"),
               ("output", "Flat",
                "The speed scale is a constant slow-motion factor; the particle "
                "keeps a steady speed while it is in the field")],
        default="balanced")
    S.efx_sim_homing_ff_recover = FloatProperty(
        name="Homing field recovery", default=48.0, min=4.0, max=600.0,
        description="How many frames it takes a homing particle to pull its speed "
                    "back up to the target speed after a force field has slowed it. "
                    "Only used by the damped force field. Preview only")
    S.efx_sim_homing_compose = EnumProperty(
        name="Homing steering",
        items=[("pursuit", "Steers the velocity",
                "Homing turns whichever way the particle is already moving towards "
                "its target, at the turn rate, and sets the speed. A Velocity 3D "
                "starting speed throws the particles outwards first and homing "
                "swings them back around"),
               ("add", "Adds its own speed",
                "Homing pulls straight at the target and that pull is added on top "
                "of whatever else is driving the particle"),
               ("override", "Replaces other speed",
                "Homing alone decides the velocity every frame, so a Velocity 3D "
                "starting speed has no visible effect")],
        default="pursuit")
    S.efx_sim_homing_axis_update = EnumProperty(
        name="Homing orbit axis",
        items=[("frozen", "Locked at arrival",
                "The orbit keeps the plane it picked when the particle reached its "
                "target, so every lap retraces the same circle"),
               ("live", "Follows velocity",
                "The sideways force is re-aimed from the current velocity every "
                "frame, so an orbit that is not level slowly tips over the first "
                "lap and then holds. Level orbits are identical either way")],
        default="frozen")
    S.efx_sim_homing_lateral_tilt = FloatProperty(
        name="Homing lateral tilt", default=0.0, min=0.0, max=2.0,
        description="How far the sideways force that bends a homing particle into "
                    "its orbit tilts out of horizontal as the particle comes in "
                    "closer to straight up or down. 0 = always horizontal, which "
                    "squashes the swarm into a flat disc at full spread; higher "
                    "values keep more height. The swarm stays centred on its "
                    "target at any setting. Preview only")
    S.efx_sim_homing_retarget = EnumProperty(
        name="Homing orbit re-aim",
        items=[("once_more", "Re-aim once",
                "Turn again after the first full lap, then keep that orbit "
                "forever. Matches footage: the particle swaps to a second orbit "
                "of the same size and stays there"),
               ("once", "Lock at arrival",
                "Pick the orbit when the particle first reaches its target and "
                "never change it"),
               ("every_pass", "Re-aim every lap",
                "Turn again after every lap. Ends up alternating between two "
                "orbits forever")],
        default="once")
    S.efx_sim_homing_axial_falloff = FloatProperty(
        name="Homing vertical squash", default=0.0, min=0.0, max=1.0,
        description="How much of the speed along the vertical axis is dropped when "
                    "a homing particle turns at its target. 0 = off, every particle "
                    "orbits at the same radius and the swarm stays a sphere the "
                    "whole cycle; above 0 shrinks the orbit of particles arriving "
                    "along the vertical axis, flattening the swarm as it expands. "
                    "Leave at 0 unless comparing: particles arriving straight down "
                    "the vertical axis do keep circling in game, and this knob "
                    "stops them dead at 1. Preview only")
    S.efx_sim_material_slot = EnumProperty(
        name="Mesh texture from",
        items=[("tAlbedoMap", "Material albedo",
                "Take the mesh texture from the MATERIAL attribute's albedo slot"),
               ("tEmissiveMap", "Material emissive",
                "Take it from the emissive slot instead"),
               ("none", "Mesh material",
                "Ignore the MATERIAL attribute and use whatever the imported "
                "mod3's own material points at")],
        default="tAlbedoMap")
    S.efx_sim_draw_order = EnumProperty(
        name="Draw order",
        items=[("entry", "Entry order",
                "Draw in the order the entries sit in the file, so fully "
                "overlapping faces cover each other the way they do in game"),
               ("alpha_first", "Alpha then additive",
                "Draw every alpha-blended body first and the additive ones on top")],
        default="entry")
    S.efx_sim_mesh_rot_space = EnumProperty(
        name="Mesh rotation space", update=_on_knob_changed,
        items=[("game", "Game axes",
                "Turn the mesh in game space, then swap to Blender axes"),
               ("local", "Mesh local",
                "Swap axes first, then turn it about its own Blender axes")],
        default="game")
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
        description="Whether spawnWaitFrame still advances the particle's age")
    S.efx_sim_ribbon_length = EnumProperty(
        name="Ribbon length", update=_on_knob_changed,
        items=[("per_segment", "length x (subdiv-1)",
                "Trail-follow ribbons get one 'length' per subdivision, so the strip "
                "gets longer as you raise the subdivision count"),
               ("total", "length is the whole strip",
                "Trail-follow ribbons are 'length' long no matter the subdivision count")],
        default="per_segment")
    S.efx_sim_ribbon_rigid_dir = EnumProperty(
        name="Ribbon Length direction", update=_on_knob_changed,
        items=[("static", "baseAxis + rotation",
                "Fixed direction set once at spawn from baseAxis/rotationX-Y-Z; "
                "never changes for the rest of the particle's life"),
               ("velocity", "Current movement",
                "Tracks current velocity every frame - the particle's own first, "
                "falling back to the emitter's movement if the particle itself "
                "isn't moving, holding the last valid direction if both are still "
                "(the way Unity's Stretched Billboard works)")],
        default="static")
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
    _restore_all_bone_follow()
    _P["tracks"] = []
    _P["mesh_cache"] = {}
    _clear_tex_cache()
    _gc_hold(False)
    _UVS_HOST_CACHE.clear()

    for attr in (
        "efx_sim_scope",
        "efx_sim_mode", "efx_sim_speed", "efx_sim_duration", "efx_sim_seed",
        "efx_sim_swing_enable", "efx_sim_swing_axis", "efx_sim_swing_angle",
        "efx_sim_swing_radius", "efx_sim_swing_duration",
        "efx_sim_draw_mode", "efx_sim_blend", "efx_sim_particle_size",
        "efx_sim_point_px", "efx_sim_show_velocity", "efx_sim_show_shape",
        "efx_sim_jitter_mode", "efx_sim_es3d_range", "efx_sim_es3d_range_mode",
        "efx_sim_life_model",
        "efx_sim_a0_sample", "efx_sim_timl_mode", "efx_sim_timl_interp",
        "efx_sim_rot_order", "efx_sim_age_during_delay",
        "efx_sim_uvs_speed_unit", "efx_sim_uvs_once_span",
        "efx_sim_uvs_start_wrap", "efx_sim_uvs_grid",
        "efx_sim_textured", "efx_sim_uv_flip_v", "efx_sim_ribbon_length",
        "efx_sim_ribbon_rigid_dir",
        "efx_sim_parent_clock", "efx_sim_color_range", "efx_sim_t3d_vel_unit",
        "efx_sim_spawn_jitter", "efx_sim_t3d_rot_sign", "efx_sim_rgb_tint", "efx_sim_mesh_rot_space",
        "efx_sim_mesh_rot",   # 撤掉的旧名（存过 local），留着清场
        "efx_sim_draw_order", "efx_sim_material_slot",
        "efx_sim_alpha_source",
        "efx_sim_luma_alpha",   # 撤掉的旧名（存过 mesh/all），留着清场
        "efx_sim_hdr_mode",
        "efx_sim_hdr",   # 撤掉的旧名（存过已删除的 auto），留着清场
        "efx_sim_ribbon_subdiv_max", "efx_sim_render_every",
        "efx_sim_particle_budget",
        "efx_sim_refraction_tex", "efx_sim_refraction_gain",
        "efx_sim_flowmap_gain", "efx_sim_flowmap_speed_unit", "efx_sim_flowmap_phase",
        "efx_sim_homing_compose",
        "efx_sim_homing_axial_falloff", "efx_sim_homing_retarget",
        "efx_sim_homing_lateral_tilt", "efx_sim_homing_axis_update",
        "efx_sim_homing_ff_scale",
        "efx_sim_homing_ff_recover", "efx_sim_homing_converge",
        "efx_sim_homing_ramp_turns",
        "efx_sim_fps",   # 已撤掉的开关，留在这里是为了从老场景里清掉
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
