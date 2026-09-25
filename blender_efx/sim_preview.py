# -*- coding: utf-8 -*-
"""以独立 modal 时钟和 GPU 绘制预览 EFX 粒子模拟。

维护约束：模拟计算归 ``efx_format.sim``；输入必须来自当前编辑树而非磁盘快照。
预览不得改 ``scene.frame_current`` 或创建场景对象。builtin shader 名称跨 Blender
版本需要回退；不得使用已废弃的字符串 GPUShader 构造器。
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
# 本模块不产生场景数据，播放器生命周期由 draw handler 与 modal 状态共同持有。

_P = {
    "tracks": [],
    "playing": False,
    "acc": 0.0,
    "last_t": 0.0,
    "duration": 0,
    "handler": None,
    "timer": None,
    "dirty": False,       # 属性被编辑过 → 下个 tick 重建
    "error": "",
    "mesh_cache": {},     # 绑定网格 → 游戏坐标系下的三角顶点（按网格名，全局共享）
    "cam_fwd": None,      # 上一帧的视线方向（Blender 世界系），由 _draw 缓存
    "cam_pos": None,      # 上一帧的相机位置（Blender 世界系），由 _draw 缓存
    "gen": 0,             # 渲染项的版本号：每次重建 items +1，绘制缓存据此失效
    "needs_items": False, # 下个 tick 无论走没走帧都要重建一次 items
    "draw_cache": {},     # id(region_data) → (签名, 绘制负载)，见 _draw
    "gc_was_on": None,    # 播放期间关掉的 GC 原状态（见 _gc_hold）
    "skipped": 0,         # 距上次重建画面攒了几帧（efx_sim_render_every）
}


def _gc_hold(on):
    """播放时暂存并关闭 GC 状态，停止时恢复并执行一次回收。"""
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
    """将当前属性块解析为模拟输入；重建失败时回退原始字节。"""
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


#: Entry 名到 UVSEQUENCE 宿主对象名的缓存；缓存名称后仍需查验对象存在。
_UVS_HOST_CACHE = {}


def _uvs_host(entry_obj, use_cache=False):
    """返回实际存放 ``efx_uvs`` 的 UVSEQUENCE 宿主；兼容未迁移场景。"""
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
    """返回已载入 UVS 的模拟资源及展示信息；缺失时返回空资源。"""
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
    """将场景属性映射为 SimConfig。"""
    from ..efx_format.sim import SimConfig

    return SimConfig(
        seed=int(getattr(scene, "efx_sim_seed", 0)),
        a0_sample=getattr(scene, "efx_sim_a0_sample", "spawn"),
        timl_interp=getattr(scene, "efx_sim_timl_interp", "native"),
        age_during_delay=bool(getattr(scene, "efx_sim_age_during_delay", False)),
        rot_order_applied=getattr(scene, "efx_sim_rot_order", "forward"),
        parent_release_clock=getattr(scene, "efx_sim_parent_clock", "particle_age"),
        spawn_interval_jitter=getattr(scene, "efx_sim_spawn_jitter", "per_burst"),
        uvs_speed_unit=getattr(scene, "efx_sim_uvs_speed_unit", "per_frame"),
        uvs_once_span=getattr(scene, "efx_sim_uvs_once_span", "to_end"),
        uvs_start_wrap=getattr(scene, "efx_sim_uvs_start_wrap", "wrap"),
        uvs_grid_h=int(getattr(scene, "efx_sim_uvs_grid", (8, 8))[0]),
        uvs_grid_v=int(getattr(scene, "efx_sim_uvs_grid", (8, 8))[1]),
        blink_phase=getattr(scene, "efx_sim_blink_phase", "zero"),
        fade_depth_metric=getattr(scene, "efx_sim_fade_depth_metric", "view_depth"),
        fade_cone_mode=getattr(scene, "efx_sim_fade_cone_mode", "outer"),
        ribbon_subdiv_max=int(getattr(scene, "efx_sim_ribbon_subdiv_max", 0)),
        ribbon_gravity_scale=float(getattr(scene, "efx_sim_ribbon_gravity_scale", 1.0)),
        ribbon_trail_time_frames=float(
            getattr(scene, "efx_sim_ribbon_trail_time_frames", 0.42)),
        homing_orbit_lateral_tilt=float(
            getattr(scene, "efx_sim_homing_lateral_tilt", 0.0)),
        homing_ff_recover_frames=float(
            getattr(scene, "efx_sim_homing_ff_recover", 48.0)),
        **_budget_kw(scene))


def _budget_kw(scene):
    """粒子预算：0 = 用 SimConfig 自己的默认上限，不覆盖。"""
    n = int(getattr(scene, "efx_sim_particle_budget", 0))
    return {"max_particles_total": n} if n > 0 else {}


def build_simulator(entry_obj, scene, out=None):
    """按当前属性树构造 Simulator；失败原因写入共享播放器状态。"""
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
    """返回 Entry UVSEQUENCE 绑定的已载入参考图名。"""
    host = _uvs_host(entry_obj, use_cache=True)
    if host is None:
        return ""
    try:
        name = host.efx_uvs.ref_image_name or ""
    except Exception:
        return ""
    return name if name in bpy.data.images else ""


#: MATERIAL 游戏路径到已载入图像名的缓存。
_MAT_TEX_CACHE = {}


def _clear_flow_cache():
    _FLOW_TEX_CACHE.clear()


def _clear_material_cache():
    _MAT_TEX_CACHE.clear()
    _DECAL_UVS_CACHE.clear()


def _material_tex_paths(attr_objs):
    """从 MATERIAL 属性提取贴图槽名到游戏相对路径的映射。"""
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


def _material_params(attr_objs):
    """MATERIAL 覆盖的着色器参数：参数名 → 值，按所属 shader 的参数表解码；同名取首个。"""
    from ..efx_format.hashes import MATERIAL
    from ..efx_format.material.params import param_name_type
    from ..efx_format.material.edit import get_param_value

    out = {}
    for blk in attr_objs:
        pair = _block_fields(blk)
        if pair is None or pair[0] != MATERIAL:
            continue
        for block in (pair[1].get("blocks") or ()):
            shader = int(block.get("mat_shader", 0) or 0)
            for st in (block.get("sets") or ()):
                try:
                    if int(st.get("type", 0)) == 128:
                        continue
                    nt = param_name_type(shader, int(st.get("t", 0)))
                    if not nt or nt[0] in out:
                        continue
                    value = get_param_value(st, nt[1])
                except Exception:
                    continue
                if value is not None:
                    out[nt[0]] = value
    return out


#: MATERIAL 参数中会覆盖网格绘制的几项
_MESH_PARAM_KEYS = ("fVertexAlpha", "fDotOpacity", "fDotOpacityFactor", "bDotInverse",
                    "bUseUVPrimaryAM", "fFlowStrength", "fSecondaryFlowStrength",
                    "fFlowSpeed", "fFlowSpeedSecondary")


def _material_image_name(entry_obj, attr_objs, slot, chunk_root):
    """解析并载入 MATERIAL 槽贴图；调用方应仅在构建 track 时调用。"""
    paths = _material_tex_paths(attr_objs)
    return _game_tex_image(entry_obj, paths.get(slot) or "", chunk_root, _MAT_TEX_CACHE)


def _game_tex_image(entry_obj, rel, chunk_root, cache):
    """游戏相对路径的 .tex → 已载入的图名；取不到返回 ""。

    只缓存成功的结果：贴图可能在导入后才补进目录，图像也可能被删除（如重新导入）。
    """
    if not rel:
        return ""
    cached = cache.get(rel)
    if cached and cached in bpy.data.images:
        return cached
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
    if name:
        cache[rel] = name
    return name


#: flowmap 游戏路径到已载入图像名的缓存。
_FLOW_TEX_CACHE = {}


def _flowmap_path(attr_objs):
    """返回启用的渲染体 flowmap 路径；未设置启用位时忽略路径。"""
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


def _uvc_flowmap_on(attr_objs):
    """UVCONTROL 是否启用了 flowmap 组。"""
    from ..efx_format.hashes import UVCONTROL

    for blk in attr_objs:
        pair = _block_fields(blk)
        if pair is not None and pair[0] == UVCONTROL and pair[1].get("enableFlowmap"):
            return True
    return False


def _flowmap_image_name(entry_obj, attr_objs, chunk_root):
    """flowmap 贴图 → 已载入的图名；取不到返回 ""。

    渲染体没有启用的路径时，UVCONTROL 的 flowmap 取 MATERIAL 的 tFlowMap 槽。
    """
    rel = _flowmap_path(attr_objs)
    if not rel and _uvc_flowmap_on(attr_objs):
        rel = _material_tex_paths(attr_objs).get("tFlowMap") or ""
    return _game_tex_image(entry_obj, rel, chunk_root, _FLOW_TEX_CACHE)


#: 贴花 .uvs 游戏路径到文件字节的缓存；只缓存读到的结果。
_DECAL_UVS_CACHE = {}


def _decal_uvs_bytes(entry_obj, rel, chunk_root):
    """读取贴花引用的 .uvs；取不到返回 b""。"""
    if not rel:
        return b""
    got = _DECAL_UVS_CACHE.get(rel)
    if got:
        return got
    data = b""
    try:
        from . import uvs_link as _ul
        abspath = _ul.resolve_game_path(rel, ".uvs", chunk_root, _ul.efx_dir_of(entry_obj))
        if abspath:
            with open(abspath, "rb") as f:
                data = f.read()
    except Exception:
        data = b""
    if data:
        _DECAL_UVS_CACHE[rel] = data
    return data


def _decal_assets(entry_obj, blocks, chunk_root, use_tex=True):
    """返回 Entry 中贴花 PTBEHAVIOR 用到的外部资源；没有贴花返回 None。

    结果含 ``resources``（序列帧模式的 .uvs）、``image``（序列帧贴图或 BaseMap）、
    ``emissive`` 与 ``flow`` 图名。
    """
    from ..efx_format.hashes import PTBEHAVIOR
    from ..efx_format.sim import SimResources
    from ..efx_format.sim.behaviors import decal as _decal
    from ..efx_format.sim.uvs_table import from_uvs_bytes

    d = None
    for h, fields in blocks:
        if int(h) == PTBEHAVIOR:
            flat = _decal.flatten(fields)
            if flat.get("b_type") == _decal.DECAL_CLASS:
                d = flat
                break
    if d is None:
        return None

    out = {"resources": None, "image": "", "emissive": "", "flow": ""}
    if int(d.get("mMappingMode", _decal.MAP_TEXTURES)) == _decal.MAP_UVSEQUENCE:
        data = _decal_uvs_bytes(entry_obj, d.get("mpUVSequence", ""), chunk_root)
        if data:
            out["resources"] = SimResources(data)
            table = from_uvs_bytes(data, int(d.get("mSequenceNo", 0)))
            paths = table.tex_paths if table is not None else ()
            if paths and use_tex:
                out["image"] = _game_tex_image(entry_obj, paths[0], chunk_root,
                                               _MAT_TEX_CACHE)
    elif use_tex:
        out["image"] = _game_tex_image(entry_obj, d.get("mpAlbedoMap", ""), chunk_root,
                                       _MAT_TEX_CACHE)
        out["emissive"] = _game_tex_image(entry_obj, d.get("mpEmissiveMap", ""),
                                          chunk_root, _MAT_TEX_CACHE)
    if use_tex and int(d.get("mFlowEnable", 0)):
        out["flow"] = _game_tex_image(entry_obj, d.get("mpFlowMap", ""), chunk_root,
                                      _FLOW_TEX_CACHE)
    return out


def _attributes_by_entry():
    """一次遍历按 Entry 建属性映射，供整棵模拟树复用。"""
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
    """构建 Action 段局部索引到模拟目标的表，供 PTLIFE relationIndex 使用。"""
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
    """收集根 Entry 经 PTLIFE/Action 可达的 Entry，受深度限制。"""
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
                # relationIndex 的 0 是合法 Action 段局部索引。
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
    """构造一条含根 Entry 及可达 PTLIFE Action 实例的模拟 track。"""
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
    #: Entry 名到 MATERIAL 覆盖的 Alpha 遮罩图名
    mesh_masks = {}
    #: Entry 名到 MATERIAL 覆盖的网格绘制参数
    mesh_params = {}
    #: Entry 名到 MATERIAL 覆盖的材质流动贴图图名
    mesh_flows = {}
    flow_images = {}
    emissive_images = {}
    mat_slot = getattr(scene, "efx_sim_material_slot", "tAlbedoMap")
    chunk_root = getattr(scene, "efx_chunk_root", "") or ""
    root_uvs_info = None
    mrl3_map = None
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
        decal = _decal_assets(obj, blocks, chunk_root)
        if decal is not None:
            # 贴花是该 Entry 的渲染主体，贴图与序列帧均取自贴花自身的参数。
            if decal["resources"] is not None:
                resources[name] = decal["resources"]
            images[name] = decal["image"] or images[name]
            if decal["emissive"]:
                emissive_images[name] = decal["emissive"]
            if decal["flow"]:
                flow_images[name] = decal["flow"]
        # MATERIAL 槽贴图优先于网格自带材质，且仅在构建时解析。
        if mat_slot != "none":
            got = _material_image_name(obj, attrs, mat_slot, chunk_root)
            if got:
                mesh_images[name] = got
            got = _material_image_name(obj, attrs, "tAlphaMap", chunk_root)
            if got:
                mesh_masks[name] = got
            got = _material_image_name(obj, attrs, "tFlowMap", chunk_root)
            if got:
                mesh_flows[name] = got
        got = {k: v for k, v in _material_params(attrs).items() if k in _MESH_PARAM_KEYS}
        if got:
            mesh_params[name] = got
        got = _flowmap_image_name(obj, attrs, chunk_root)
        if got and name not in flow_images:
            flow_images[name] = got
        if _bound_meshes_for(obj, None):
            if mrl3_map is None:
                mrl3_map = _mrl3_by_material()
            _prepare_mesh_materials(obj, chunk_root, mrl3_map)
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
        #: Entry 名到序列帧图像名的映射，子实例按自己的 Entry 查找。
        "images": images,
        "mesh_images": mesh_images,
        "mesh_masks": mesh_masks,
        "mesh_params": mesh_params,
        "mesh_flows": mesh_flows,
        #: Entry 名到已启用 flowmap 图像名的映射。
        "flow_images": flow_images,
        #: Entry 名到贴花自发光贴图名的映射。
        "emissive_images": emissive_images,
        "uvs": root_uvs_info,
    }


def rebuild_track(tr, scene, keep_frame=True):
    """就地重建 track，并在允许时恢复原帧；成功返回 ``True``。"""
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
    """返回活动大纲集合所属的 EFX 根集合；找不到时返回 ``None``。"""
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


# Subselect 播放范围的 Enum identifier 前缀。
_SIM_SCOPE_SS_PREFIX = "SS:"

# EnumProperty 动态回调必须返回持久模块级列表，避免 GC 后的失效引用。
_sim_scope_items_cache = [("ALL", "All", "")]


def _sim_scope_items(self, context):
    """返回 All 与当前根集合内各 Subselect 的播放范围选项。"""
    global _sim_scope_items_cache
    items = [("ALL", T("sim.scope_all"), T("sim.scope_all_tip"))]
    root = _active_root_collection(context) if context is not None else None
    if root is not None:
        for ss in _rc.collect_top_level(root, "EFX_SUBSELECT"):
            items.append((_SIM_SCOPE_SS_PREFIX + ss.name, ss.name, T("sim.scope_subselect_tip")))
    _sim_scope_items_cache = items
    return _sim_scope_items_cache


def _subselect_scope_entries(root, ss_name):
    """返回 Subselect 成员 Entry，保序去重并跳过悬空指针。

    名称不属于当前根集合时返回空列表，不能退回全量播放。
    """
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
    """从选中对象解析 Entry，去重并保留选择顺序。"""
    out = []
    seen = set()
    for obj in list(getattr(context, "selected_objects", None) or ()):
        e = _resolve_entry(obj)
        if e is not None and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    return out


def collect_entries(context):
    """按选中 Entry 或活动根集合范围收集模拟入口。

    根集合全播时只启动 Direct Trigger Entry；Not Direct Trigger 会在 PTLIFE Action
    实例树中出现，不能再作为独立 track 重复播放。
    """
    out = _selected_entries(context)
    if out:
        return out

    root = _active_root_collection(context)
    if root is not None:
        scope = getattr(context.scene, "efx_sim_scope", "ALL")
        if scope.startswith(_SIM_SCOPE_SS_PREFIX):
            return _subselect_scope_entries(root, scope[len(_SIM_SCOPE_SS_PREFIX):])
        ents = _rc.collect_top_level(root, "EFX_ENTRY")
        direct = [e for e in ents if _entry_ref.is_entry_in_eof(e)]
        if direct:
            return direct
        return ents        # 缺少 EOF 信息时无法可靠筛选 Direct Trigger。

    e = _resolve_entry(context.active_object)
    return [e] if e is not None else []


def entry_order(entry_obj):
    """返回 ``(根集合名, efx_index)`` 绘制排序键。

    同文件 Entry 必须按段内 ``efx_index`` 排序；粒子绘制不写深度。
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
    """标记活跃预览需要重建；实际重建延后到 timer tick。"""
    if is_active():
        _P["dirty"] = True


# ─────────────────────────────────────────────────────────────────────────────
# 坐标换算（游戏 → Blender）。模拟核心保持游戏坐标，边界统一换算。
# ─────────────────────────────────────────────────────────────────────────────

_UNIT = 1.0 / 100.0


def _display_color(c, mode):
    """将 HDR 渲染色转换为预览帧缓冲可用颜色。

    ``preserve_hue`` 不得改变 alpha，否则会破坏粒子淡入淡出。
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


def _multiply_tint(c, gain=1.0, add=False):
    """为乘法通道将覆盖度折入 RGB；透明端必须回到乘法恒等色 ``(1,1,1)``。

    ``add`` 为折射的加法档：乘数为 ``1 + 颜色 × 覆盖度``。
    """
    a = c[3] * gain
    if add:
        a = max(0.0, a)
        return (1.0 + c[0] * a, 1.0 + c[1] * a, 1.0 + c[2] * a, 1.0)
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
    """转换方向坐标轴，不应用位置单位缩放。"""
    return (v.x, -v.z, v.y)


def _to_game(bx, by, bz):
    """_to_blender 的逆。宿主报告发射器位移时用。"""
    return (bx / _UNIT, bz / _UNIT, -by / _UNIT)


def _ref_local(rows, world_pos):
    """将世界坐标点转换为参考系局部偏移，按刚体矩阵处理。"""
    dx = world_pos[0] - rows[0][3]
    dy = world_pos[1] - rows[1][3]
    dz = world_pos[2] - rows[2][3]
    return (rows[0][0] * dx + rows[1][0] * dy + rows[2][0] * dz,
            rows[0][1] * dx + rows[1][1] * dy + rows[2][1] * dz,
            rows[0][2] * dx + rows[1][2] * dy + rows[2][2] * dz)


def _sync_track_origin(tr):
    """将 Entry 相对播放起点的位移同步到模拟器。

    参考矩阵在播放开始时固定，使已经发射的粒子不随宿主整体平移。
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
# 挥砍预览为宿主轨迹提供独立的往复运动。

def _mute_bone_follow(entry):
    """挥砍预览启用时静音骨骼跟随，避免叠加两份宿主位移。"""
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
    """停止或卸载时恢复所有被静音的骨骼跟随约束。"""
    for tr in _P["tracks"]:
        _restore_bone_follow(tr["entry_name"])


def _apply_swing_preview(tr, scene):
    """按模拟帧在参考位置周围应用往复圆弧，并与骨骼跟随互斥。"""
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
    phase = (t % cycle) / duration
    u = phase if phase <= 1.0 else 2.0 - phase
    u = u * u * (3.0 - 2.0 * u)
    theta = half_angle * (2.0 * u - 1.0)

    rows = tr["ref_rows"]
    rx, ry, rz = rows[0][3], rows[1][3], rows[2][3]
    s, c = math.sin(theta), math.cos(theta)

    if axis == "X":
        pos = (rx, ry + radius * (c - 1.0), rz + radius * s)
    elif axis == "Y":
        pos = (rx + radius * s, ry, rz + radius * (c - 1.0))
    else:
        pos = (rx + radius * (c - 1.0), ry + radius * s, rz)

    # 保留现有 Matrix 的旋转和缩放，仅替换平移。
    cur = entry.matrix_world
    cur.translation = pos
    entry.matrix_world = cur



def _entry_matrix_rows(entry_obj):
    """将 Entry 世界矩阵保存为三行纯浮点参考系。"""
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
    """取得 builtin shader，回退到旧版 3D 名称。"""
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


def _camera_position(rv3d):
    """视图矩阵之逆的平移 = 相机位置（世界空间）。"""
    t = rv3d.view_matrix.inverted().translation
    return (t[0], t[1], t[2])


#: 渲染结果依赖相机位置的属性；暂停时转视角须重建渲染项
_VIEW_DEPENDENT = None


def _view_dependent(tr):
    """该 track 的模板里是否有依赖相机位置的属性。"""
    global _VIEW_DEPENDENT
    if _VIEW_DEPENDENT is None:
        from ..efx_format.hashes import FADEBYANGLE, FADEBYDEPTH
        _VIEW_DEPENDENT = frozenset((int(FADEBYDEPTH), int(FADEBYANGLE)))
    sim = tr.get("sim")
    got = tr.get("view_dep")
    if got is None or got[0] is not sim:
        templates = getattr(sim, "templates", None) or {}
        got = (sim, any(int(h) in _VIEW_DEPENDENT
                        for t in templates.values() for h, _f in (t.blocks or ())))
        tr["view_dep"] = got
    return got[1]


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


def _mesh_uv_xform(item, channel=None):
    """UVCONTROL 变换换到网格 UV 空间；导入网格的 UV 已做 V 翻转。

    `channel` 为 None 时取 uv1 与 uv2 合成的变换；0 / 1 取单独一套（uv1 → 第一套 UV，
    uv2 → 第二套 UV），该通道未启用时返回 None。
    """
    if channel is None:
        xf = item.extra.get("uv_xform")
    else:
        ch = item.extra.get("uv_xform_ch") or ()
        xf = ch[channel] if channel < len(ch) else None
        if xf == (1.0, 1.0, 0.0, 0.0):
            xf = None
    if not xf:
        return None
    from ..efx_format.sim.behaviors.uvcontrol import flip_v_xform
    return flip_v_xform(xf)


def _uv_corners(item, flip_v, tex):
    """返回贴图四角 UV；v 方向由可配置的 ``flip_v`` 统一处理。"""
    if not tex:
        return None
    c = item.uv_corners
    if not c:
        # 无序列帧数据时使用整张贴图。
        c = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    if flip_v:
        return tuple((u, 1.0 - v) for u, v in c)
    return tuple((float(u), float(v)) for u, v in c)


#: ``_quad_verts`` 的六个顶点对应的四角下标。
_QUAD_UV_ORDER = (0, 1, 2, 0, 2, 3)


def _quad_uvs(corners):
    return tuple(corners[i] for i in _QUAD_UV_ORDER)


#: flowmap 使用整图局部 UV，不随序列帧子格变化。
_QUAD_LUV = tuple(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[i]
                  for i in _QUAD_UV_ORDER)


def _ribbon_affine(rows):
    """合并游戏到 Blender 的轴变换和参考矩阵，供条带批量变换。"""
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


#: 条带三角展开索引按点数缓存，可跨渲染项复用。
_RIBBON_IDX = {}


def _ribbon_idx(numpy, n):
    got = _RIBBON_IDX.get(n)
    if got is not None:
        return got
    m = n - 1
    i = numpy.arange(m)
    # 每段由左右两侧的相邻点组成两个三角形。
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
    """按点数分组批量生成条带；结果完整后才追加到 ``chunks``。"""
    numpy, lin, tr, vdir = ctx
    # 数组形态可直接堆叠；旧式点元组需先拉平。
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
            # 数组形态可直接批量堆叠。
            pos = numpy.stack([r[0].points.pos for r in recs]).astype("f4")
            half = numpy.stack([r[0].points.half for r in recs]).astype("f4")
            alpha = numpy.stack([r[0].points.alpha for r in recs]).astype("f4")
        else:
            # (K, n, 5) = [x, y, z, 半宽, alpha]。
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

        # 首尾使用唯一相邻段估计方向。
        seg = numpy.empty_like(W)
        seg[:, 1:-1] = W[:, 2:]
        seg[:, 1:-1] -= W[:, :-2]
        seg[:, 0] = W[:, 1] - W[:, 0]
        seg[:, -1] = W[:, -1] - W[:, -2]

        # 横向由段方向与视线叉乘；按分量计算以保持批量路径。
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
        numpy.divide(hw, nrm, out=hw, where=good)
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

        # 与视线平行的段没有可用宽度方向，跳过它。
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
    """以 Python 兜底路径展开条带三角形；numpy 可用时使用批量路径。"""
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

    # 先按顶点行计算共享数据，再展开相邻行的三角形。
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


def _emit_ribbon_uv(verts, colors, uvs, item, col, size_mul, world_fn, view_dir,
                    corners, uv_scale, col2s=None, core=None):
    """带贴图缩放的条带：按重复边界与宽度钳制边界切片后逐片展开，只走 Python 路径。"""
    from ..efx_format.sim import ribbon_uv as _ruv
    pts = list(item.points)
    n = len(pts)
    if n < 2:
        return
    repeat, width_scale = uv_scale
    world = [world_fn(q) for q, _hw, _a in pts]
    k = size_mul * _UNIT
    lo = []
    hi = []
    for i in range(n):
        a = world[i - 1] if i else world[0]
        b = world[i + 1] if i < n - 1 else world[n - 1]
        s_ = _norm(_cross((b[0] - a[0], b[1] - a[1], b[2] - a[2]), view_dir))
        if s_ is None:
            lo.append(None)
            hi.append(None)
            continue
        w = world[i]
        h = max(1e-5, abs(pts[i][1]) * k)
        lo.append((w[0] - s_[0] * h, w[1] - s_[1] * h, w[2] - s_[2] * h))
        hi.append((w[0] + s_[0] * h, w[1] + s_[1] * h, w[2] + s_[2] * h))

    ca, cb, cc, cd = col[0], col[1], col[2], col[3]
    core_rgb = core if core is not None else col
    cols = _ruv.width_columns(width_scale)

    def lerp3(p0, p1, t):
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t,
                p0[2] + (p1[2] - p0[2]) * t)

    for i, fa, fb, va, vb in _ruv.length_pieces(n, repeat):
        if lo[i] is None or lo[i + 1] is None:
            continue
        l0 = lerp3(lo[i], lo[i + 1], fa)
        l1 = lerp3(lo[i], lo[i + 1], fb)
        r0 = lerp3(hi[i], hi[i + 1], fa)
        r1 = lerp3(hi[i], hi[i + 1], fb)
        a_i = pts[i][2]
        a_j = pts[i + 1][2]
        a0 = (ca, cb, cc, cd * (a_i + (a_j - a_i) * fa))
        a1 = (ca, cb, cc, cd * (a_i + (a_j - a_i) * fb))
        for s0, s1, u0, u1 in cols:
            p00 = lerp3(l0, r0, s0)
            p10 = lerp3(l0, r0, s1)
            p01 = lerp3(l1, r1, s0)
            p11 = lerp3(l1, r1, s1)
            verts.extend((p00, p10, p11, p00, p11, p01))
            colors.extend((a0, a0, a1, a0, a1, a1))
            if col2s is not None:
                b0 = (core_rgb[0], core_rgb[1], core_rgb[2], a0[3])
                b1 = (core_rgb[0], core_rgb[1], core_rgb[2], a1[3])
                col2s.extend((b0, b0, b1, b0, b1, b1))
            if uvs is not None:
                q00 = _ruv.corner_uv(corners, u0, va)
                q10 = _ruv.corner_uv(corners, u1, va)
                q01 = _ruv.corner_uv(corners, u0, vb)
                q11 = _ruv.corner_uv(corners, u1, vb)
                uvs.extend((q00, q10, q11, q00, q11, q01))


#: MESH 未绑定网格时使用的占位几何。
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
    """读取并缓存游戏坐标三角形、可选 numpy 数组、逐顶点 UV、顶点色 alpha、逐角法线与第二套 UV。"""
    uvs = None
    uvs2 = None
    valpha = None
    normals = None
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
            uvl2 = next((l for l in me.uv_layers if uvl is not None and l.name != uvl.name), None)
            uvdata2 = uvl2.data if uvl2 is not None else None
            cattr = getattr(me, "color_attributes", None)
            cattr = (cattr.active_color or (cattr[0] if len(cattr) else None)) if cattr else None
            cdata = cattr.data if cattr is not None else None
            per_loop = getattr(cattr, "domain", "") == "CORNER"
            cnorm = getattr(me, "corner_normals", None)     # Blender 4.1+
            if cnorm is None:
                try:
                    me.calc_normals_split()
                except Exception:
                    pass
            tris = []
            uvs = [] if uvdata is not None else None
            valpha = [] if cdata is not None else None
            normals = []
            uvs2 = [] if uvdata2 is not None else None
            for tri in me.loop_triangles:
                for k, vi in enumerate(tri.vertices):
                    co = verts[vi].co
                    tris.append(_to_game(co[0], co[1], co[2]))
                    if uvs is not None:
                        u = uvdata[tri.loops[k]].uv
                        uvs.append((u[0], u[1]))
                    if uvs2 is not None:
                        u = uvdata2[tri.loops[k]].uv
                        uvs2.append((u[0], u[1]))
                    if valpha is not None:
                        valpha.append(cdata[tri.loops[k] if per_loop else vi].color[3])
                    li = tri.loops[k]
                    n = cnorm[li].vector if cnorm is not None else me.loops[li].normal
                    normals.append((n[0], n[2], -n[1]))       # 与 _to_game 同一换轴
        except Exception:
            tris, uvs, valpha, normals, uvs2 = _placeholder_cube(), None, None, None, None
    cached = _P["mesh_cache"].get(key)
    if cached is not None:
        return cached
    arr = narr = None
    try:
        import numpy
        arr = numpy.array(tris, dtype="f4")
        if normals and len(normals) == len(tris):
            narr = numpy.array(normals, dtype="f4")
    except Exception:
        arr = narr = None
    out = (tris, arr, uvs, valpha, narr, uvs2)
    _P["mesh_cache"][key] = out
    return out


def _mesh_tris_game_multi(mesh_objs):
    """合并 viscon 网格；仅全部具有 UV 时才保留合并后的 UV。"""
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
    for part in parts:
        tris.extend(part[0])
    uvs = None
    if all(part[2] is not None for part in parts):
        uvs = []
        for part in parts:
            uvs.extend(part[2])
    valpha = None
    if all(part[3] is not None for part in parts):
        valpha = []
        for part in parts:
            valpha.extend(part[3])
    uvs2 = None
    if all(part[5] is not None for part in parts):
        uvs2 = []
        for part in parts:
            uvs2.extend(part[5])
    arr = narr = None
    try:
        import numpy
        arr = numpy.array(tris, dtype="f4")
        if all(part[4] is not None for part in parts):
            narr = numpy.concatenate([part[4] for part in parts])
    except Exception:
        arr = narr = None
    out = (tris, arr, uvs, valpha, narr, uvs2)
    _P["mesh_cache"][key] = out
    return out


def _mesh_image_name(mesh_obj):
    """从绑定网格材质取得基础色图，回退到首张非 normal 图。"""
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


_NO_FACTOR = (1.0, 1.0, 1.0, 1.0)

#: 网格对象名 → mrl3 派生的绘制信息，由 build_track 在播放前填好，绘制期只读。
_MESH_MAT_INFO = {}


def _node_image(mat, node_name):
    """材质里指定名字的贴图节点的图名；没有返回 ""。"""
    tree = getattr(mat, "node_tree", None) if mat is not None else None
    nd = tree.nodes.get(node_name) if tree is not None else None
    img = getattr(nd, "image", None) if nd is not None else None
    return img.name if img is not None else ""


def _node_factor(mat, node_name):
    """材质里 BaseMapFactor 一类颜色组节点的 RGBA；取不到返回 None。"""
    tree = getattr(mat, "node_tree", None) if mat is not None else None
    nd = tree.nodes.get(node_name) if tree is not None else None
    if nd is None:
        return None
    try:
        c = nd.inputs["Color"].default_value
        a = nd.inputs["Alpha"].default_value if "Alpha" in nd.inputs else c[3]
        return (float(c[0]), float(c[1]), float(c[2]), float(a))
    except Exception:
        return None


def _mrl3_by_material():
    """Blender 材质名 → mrl3 材质属性组（Model Editor 导入的 Mrl3 Material 对象）。"""
    out = {}
    for obj in bpy.data.objects:
        pg = getattr(obj, "mhw_mrl3_material", None)
        mat = getattr(pg, "linkedMaterial", None) if pg is not None else None
        if mat is not None:
            out.setdefault(mat.name, pg)
    return out


def _mrl3_prop(pg, prop_name):
    for blk in getattr(pg, "propertyBlock_items", ()):
        for p in blk.propertyList_items:
            if p.prop_name == prop_name:
                return p
    return None


def _mrl3_factor(pg, prop_name):
    p = _mrl3_prop(pg, prop_name)
    try:
        return tuple(float(x) for x in p.color_value) if p is not None else None
    except Exception:
        return None


def _mrl3_map_path(pg, map_name):
    """mrl3 贴图槽的游戏相对路径；未设置或是 null_ 占位图时返回 ""。"""
    for it in getattr(pg, "mapList_items", ()):
        if it.name == map_name:
            rel = str(it.value or "").strip()
            base = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
            return "" if (not rel or base.startswith("null_")) else rel
    return ""


def _prepare_mesh_materials(entry_obj, chunk_root, mrl3_map):
    """播放前为 Entry 绑定的网格解析 mrl3：底色 / 自发光 / 遮罩贴图、颜色系数与几个开关。

    需要载入贴图，只能在构建 track 时调用，绘制期不能改 bpy.data。
    """
    for mesh in _bound_meshes_for(entry_obj, None):
        if mesh.name in _MESH_MAT_INFO:
            continue
        mat = next((s.material for s in mesh.material_slots if s.material is not None), None)
        pg = mrl3_map.get(mat.name) if mat is not None else None
        base = _mrl3_factor(pg, "BaseMapFactor") if pg is not None else None
        emis = _mrl3_factor(pg, "EmissiveMapFactor") if pg is not None else None
        albedo = _mesh_image_name(mesh)
        emissive = _node_image(mat, "EmissiveMap")
        rel = _mrl3_map_path(pg, "AlphaMap") if pg is not None else ""
        mask = _game_tex_image(entry_obj, rel, chunk_root, _MAT_TEX_CACHE) if rel else ""
        rel = _mrl3_map_path(pg, "FlowMap") if pg is not None else ""
        flow = _game_tex_image(entry_obj, rel, chunk_root, _MAT_TEX_CACHE) if rel else ""
        _MESH_MAT_INFO[mesh.name] = {
            "base": base or _node_factor(mat, "BaseMapFactor") or _NO_FACTOR,
            "emissive": emis or _node_factor(mat, "EmissiveMapFactor") or _NO_FACTOR,
            "albedo": albedo,
            "emissive_img": emissive,
            # AlphaMap 在 shader 里单独采样；UseUVPrimaryAM 关闭时用第二套 UV
            "mask": mask,
            "mask_uv2": not (bool(getattr(_mrl3_prop(pg, "UseUVPrimaryAM"), "bool_value", True))
                             if pg is not None else True),
            # mrl3 绘制优先级：alphaCoef[1] 每差 16 为一级，越大越后画
            "priority": int(pg.alphaCoef[1]) if pg is not None else 0,
            # mrl3 flowmap：主贴图 / 遮罩的扭曲强度与每秒推进轮数
            "flow": flow,
            "flow_speed": ((float(getattr(_mrl3_prop(pg, "FlowSpeed"), "float_value", 0.0)),
                            float(getattr(_mrl3_prop(pg, "FlowSpeedSecondary"), "float_value", 0.0)))
                           if pg is not None else (0.0, 0.0)),
            "flow_k": ((float(getattr(_mrl3_prop(pg, "FlowStrength"), "float_value", 0.0)),
                        float(getattr(_mrl3_prop(pg, "SecondaryFlowStrength"), "float_value", 0.0)))
                       if pg is not None else (0.0, 0.0)),
            "vertex_alpha": (bool(getattr(_mrl3_prop(pg, "VertexAlpha"), "bool_value", False))
                             if pg is not None else False),
            "dot_opacity": (float(getattr(_mrl3_prop(pg, "DotOpacity"), "float_value", 0.0))
                            if pg is not None else 0.0),
            "dot_factor": (float(getattr(_mrl3_prop(pg, "DotOpacityFactor"), "float_value", 1.0))
                           if pg is not None else 1.0),
            "dot_inverse": (bool(getattr(_mrl3_prop(pg, "DotInverse"), "bool_value", False))
                            if pg is not None else False),
        }


def _mesh_mat_info(mesh_obj):
    """build_track 预先解析的 mrl3 信息；没有时只取材质节点上的底色贴图。"""
    info = _MESH_MAT_INFO.get(getattr(mesh_obj, "name", ""))
    if info is not None:
        return info
    return {"base": _NO_FACTOR, "emissive": _NO_FACTOR,
            "albedo": _mesh_image_name(mesh_obj), "emissive_img": "", "mask": "",
            "mask_uv2": False, "flow": "", "flow_k": (0.0, 0.0), "flow_speed": (0.0, 0.0), "priority": 0, "vertex_alpha": False, "dot_opacity": 0.0, "dot_factor": 1.0, "dot_inverse": False}


def _mat3_mul(a, b):
    """相乘两个 3×3 矩阵。"""
    return [[a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
             for j in range(3)] for i in range(3)]


def _mesh_affine(item, size_mul, rows):
    """合并粒子的缩放、旋转、平移及坐标变换，返回 ``world = L·v + T``。"""
    from ..efx_format.sim.vecmath import rotate_euler
    from ..efx_format.sim.state import Vec3

    r0, r1, r2 = rows
    rot = item.extra.get("rot")
    order = item.extra.get("rot_order", "XYZ")
    sx = size_mul * item.size.x
    sy = size_mul * item.size.y
    sz = size_mul * item.size.z

    def rot3():
        """以共享的 ``rotate_euler`` 构造旋转矩阵，保持旋转约定一致。"""
        e = [rotate_euler(Vec3(*b), rot.x, rot.y, rot.z, order=order)
             for b in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
        return [[e[0].x, e[1].x, e[2].x],
                [e[0].y, e[1].y, e[2].y],
                [e[0].z, e[1].z, e[2].z]]

    scl = [[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, sz]]
    turning = rot is not None and (rot.x or rot.y or rot.z)
    # 游戏到 Blender 的线性轴变换。
    au = [[_UNIT, 0.0, 0.0], [0.0, 0.0, -_UNIT], [0.0, _UNIT, 0.0]]
    m3 = [[r0[0], r0[1], r0[2]], [r1[0], r1[1], r1[2]], [r2[0], r2[1], r2[2]]]

    space = _P.get("mesh_rot_space") or "game"
    if turning and space == "game":
        # 默认旋转在游戏坐标系完成后再换轴。
        lin = _mat3_mul(m3, _mat3_mul(au, _mat3_mul(rot3(), scl)))
    elif turning:
        # ``local`` 在换轴后旋转，用于兼容性切换。
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
    """按 viscon 查找绑定网格，缺少精确组时回退单个目标。"""
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


def _join_chunks(verts, colors, uvs, col2s, chunks, luvs=None, flowoffs=None):
    """把网格的 numpy 分块和普通三角（片/条带）拼成可直接喂 batch 的数组。

    flowmap 桶（``luvs`` 不为 None）同时拼接流动贴图 UV 与位移参数，返回值依次为
    ``(pos, color, uv, col2, luv, flowoff, muv)``，luv / flowoff 在非 flowmap 桶为 None；
    muv 是网格分块带的遮罩 UV，没有时为 None（遮罩桶只收网格的 numpy 分块）。
    """
    flow = luvs is not None
    try:
        import numpy
        vs = [c[0] for c in chunks]
        cs = [c[1] for c in chunks]
        us = [c[2][0] for c in chunks if c[2] is not None]
        c2 = [c[2][1] for c in chunks if c[2] is not None]
        lu = [c[2][2] for c in chunks if flow and c[2] is not None and len(c[2]) > 2]
        fo = [c[2][3] for c in chunks if flow and c[2] is not None and len(c[2]) > 2]
        mu = [c[2][4] for c in chunks if c[2] is not None and len(c[2]) > 4]
        if verts:
            vs.insert(0, numpy.array(verts, dtype="f4"))
            cs.insert(0, numpy.array(colors, dtype="f4"))
            if us:
                us.insert(0, numpy.array(uvs, dtype="f4"))
                c2.insert(0, numpy.array(col2s, dtype="f4"))
            if lu and luvs:
                lu.insert(0, numpy.array(luvs, dtype="f4"))
                fo.insert(0, numpy.array(flowoffs, dtype="f4"))
        cat = lambda a: (numpy.concatenate(a) if len(a) > 1 else a[0])
        return (cat(vs), cat(cs), (cat(us) if us else None), (cat(c2) if c2 else None),
                (cat(lu) if lu else luvs), (cat(fo) if fo else flowoffs),
                (cat(mu) if (mu and len(mu) == len(vs)) else None))
    except Exception:
        out_v, out_c = list(verts), list(colors)
        out_u = list(uvs) if uvs else []
        out_2 = list(col2s) if col2s else []
        out_l = list(luvs) if luvs else []
        out_f = list(flowoffs) if flowoffs else []
        for a, c, ex in chunks:
            out_v.extend(a.tolist())
            out_c.extend(c.tolist())
            if ex is not None:
                out_u.extend(ex[0].tolist())
                out_2.extend(ex[1].tolist())
                if flow and len(ex) > 2:
                    out_l.extend(ex[2].tolist())
                    out_f.extend(ex[3].tolist())
        return (out_v, out_c, (out_u or None), (out_2 or None),
                (out_l if flow else None), (out_f if flow else None), None)


def _emit_mesh(verts, colors, chunks, item, col, size_mul, rows, geom,
               uvs=None, col2s=None, core=None, luvs=None, flowoffs=None, flow_amt=None,
               vertex_alpha=False, dot_opacity=None, mask_uv=None):
    """将网格按粒子变换输出三角形；numpy 不可用时回退逐顶点路径。

    ``luvs`` 不为 None 时另输出 flowmap 数据：流动贴图按网格自身 UV 采样，位移量为整张
    贴图的比例。``flow_amt`` 为 `_flow_of` 返回的 (强度, 相位, 循环标记)。
    ``dot_opacity`` = (相机世界坐标, 是否反向, 视图方向, DotOpacity, DotOpacityFactor)：
    不透明度乘以 mix(1, d^DotOpacity, DotOpacityFactor)，d = |法线·视线|，反向时 d 取 1 − |法线·视线|。
    (1, 1) 即斜看变透明的线性形式；其余取值的曲线为推测。相机坐标为 None（正交视图）时视线取
    视图方向。只在 numpy 路径生效。
    ``mask_uv``（遮罩是否用第二套 UV）给出时走分通道路径：底色只用 uv1 的变换，另输出遮罩 UV
    （所选那套 UV 经对应通道变换），只在 numpy 路径生效。
    """
    tris, arr, muv = geom[:3]
    if not tris:
        return
    lin, t = _mesh_affine(item, size_mul, rows)
    # mrl3 开启 VertexAlpha 时顶点色 alpha 乘进不透明度（网格边缘多靠它羽化）
    va = geom[3] if (vertex_alpha and len(geom) > 3) else None

    if arr is not None and chunks is not None:
        try:
            import numpy
            out = arr.dot(numpy.array(lin, dtype="f4").T)
            out += numpy.array(t, dtype="f4")
            cc = numpy.empty((len(tris), 4), dtype="f4")
            cc[:] = col
            if va is not None:
                cc[:, 3] *= numpy.asarray(va, dtype="f4")
            narr = geom[4] if len(geom) > 4 else None
            if dot_opacity is not None and narr is not None:
                cam, inverse, vdir, expo, fac = dot_opacity
                try:
                    # 法线按线性部分的逆转置变换；行向量写法即 n · L⁻¹
                    nw = narr.dot(numpy.linalg.inv(numpy.array(lin, dtype="f4")))
                    nw /= numpy.maximum(numpy.linalg.norm(nw, axis=1), 1e-9)[:, None]
                    if cam is None:
                        vw = numpy.array(vdir, dtype="f4")[None, :]
                    else:
                        vw = numpy.array(cam, dtype="f4") - out
                        vw /= numpy.maximum(numpy.linalg.norm(vw, axis=1), 1e-9)[:, None]
                    d = numpy.abs((nw * vw).sum(axis=1))
                    d = (1.0 - d) if inverse else d
                    cc[:, 3] *= 1.0 + (numpy.power(d, max(expo, 1e-6)) - 1.0) * fac
                except Exception:
                    pass
            extra = None
            if uvs is not None and muv is not None:
                c2 = numpy.empty((len(tris), 4), dtype="f4")
                c2[:] = (core if core is not None else col)
                c2[:, 3] = cc[:, 3]
                base = uvarr = numpy.array(muv, dtype="f4")
                # 带遮罩时 uv1 / uv2 分管两套 UV，否则两者合成作用在同一套上
                xf = _mesh_uv_xform(item, 0 if mask_uv is not None else None)
                if xf:      # UVCONTROL：uv' = uv × 缩放 + 偏移
                    uvarr = uvarr * numpy.array((xf[0], xf[1]), dtype="f4")
                    uvarr += numpy.array((xf[2], xf[3]), dtype="f4")
                if mask_uv is not None:
                    second = mask_uv and len(geom) > 5 and geom[5] is not None
                    marr = numpy.array(geom[5] if second else muv, dtype="f4")
                    mxf = _mesh_uv_xform(item, 1 if second else 0)
                    if mxf:
                        marr = marr * numpy.array((mxf[0], mxf[1]), dtype="f4")
                        marr += numpy.array((mxf[2], mxf[3]), dtype="f4")
                    extra = (uvarr, c2, None, None, marr)
                elif luvs is not None:
                    amt, ph, lap = flow_amt
                    fo = numpy.empty((len(tris), 4), dtype="f4")
                    fo[:] = (amt, amt, ph, lap)
                    extra = (uvarr, c2, base, fo)
                else:
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
    if va is not None:
        colors.extend([(col[0], col[1], col[2], col[3] * a) for a in va])
    else:
        colors.extend([col] * len(tris))
    if uvs is not None and muv is not None:
        xf = _mesh_uv_xform(item)
        if xf:
            uvs.extend([(u * xf[0] + xf[2], v * xf[1] + xf[3]) for (u, v) in muv])
        else:
            uvs.extend(muv)
        c = core if core is not None else col
        if va is not None:
            col2s.extend([(c[0], c[1], c[2], col[3] * a) for a in va])
        else:
            col2s.extend([(c[0], c[1], c[2], col[3])] * len(tris))
        if luvs is not None:
            luvs.extend(muv)
            amt, ph, lap = flow_amt
            flowoffs.extend([(amt, amt, ph, lap)] * len(tris))


#: 渲染项可用的混合方式；其余值按 'ALPHA' 画。
_BLEND_MODES = ("ALPHA", "ADDITIVE", "MULTIPLY", "OPAQUE", "INV_MULTIPLY",
                "REFRACT", "REFRACT_ADD")
#: 折射通道（REFRACTION）：源色为背后画面，贴图 RGB 不参与
_REFRACT_MODES = ("REFRACT", "REFRACT_ADD")
#: 以乘法混合实现、颜色不经过 HDR 映射的模式
_MULTIPLY_MODES = ("MULTIPLY", "INV_MULTIPLY") + _REFRACT_MODES
#: 渲染项混合方式 → ``gpu.state.blend_set`` 预设
_GPU_BLEND = {"OPAQUE": "NONE", "INV_MULTIPLY": "MULTIPLY",
              "REFRACT": "MULTIPLY", "REFRACT_ADD": "MULTIPLY"}
#: 贴图 shader 的 ``blendOut`` 取值
_BLEND_OUT = {"INV_MULTIPLY": 1.0, "MULTIPLY": 2.0}


def _flat_blend_colors(colors, mode):
    """纯色路径的乘法乘数，与贴图 shader 的 ``blendOut`` 分支一致。"""
    out = []
    for c in colors:
        r, g, b = float(c[0]), float(c[1]), float(c[2])
        a = max(0.0, min(1.0, float(c[3])))
        if mode == "MULTIPLY":
            out.append((1.0 + (r - 1.0) * a, 1.0 + (g - 1.0) * a,
                        1.0 + (b - 1.0) * a, 1.0))
        else:
            out.append((max(0.0, 1.0 - r * a), max(0.0, 1.0 - g * a),
                        max(0.0, 1.0 - b * a), 1.0))
    return out


#: 贴图 shader；``False`` 表示创建失败并回退纯色绘制。
_TEX_SHADER = None
#: 部分 Blender 版本要求 CreateInfo 与接口对象随 shader 存活。
_TEX_SHADER_KEEP = []
#: 图像名到 GPUTexture 的缓存。
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

#: ``alphaFix`` 逐纹素修正不透明度（低阈值、对比度伽马）；不透明度取贴图 alpha。
#: ``blendOut`` 为 1 / 2 时输出乘法混合的乘数：反相乘法 ``1 − 颜色×alpha``、
#: 乘法 ``lerp(1, 颜色, alpha)``。
#: RGBFIRE 与 RGBWATER 使用互斥的双层通道遮罩；其他项逐通道染色。
_FRAG_SRC = """
// 整张贴图按重复平铺（UVCONTROL 滚动），越界夹边只留给 flowmap 位移；梯度取回绕前的 UV，
// 回绕处 mip 层级不跳变
vec4 sample_wrap(vec2 uv)
{
  return textureGrad(image, uv - floor(uv), dFdx(uv), dFdy(uv));
}

void main()
{
  vec4 t = sample_wrap(v_uv);
  vec3 rgb;
  float a = t.a;
  if (fireLerp >= 0.0) {
    float fireMask = t.g;
    float smokeMask = t.r * mix(t.a, t.b, fireLerp);
    rgb = v_col.rgb * fireMask + v_col2.rgb * smokeMask;
  } else if (waterLerp >= 0.0) {
    // 两层遮罩都已含 alpha，不透明度取两者较大者
    float sheetMask = t.a * mix(t.g, t.b, waterLerp);
    float specMask = t.r * t.a;
    a = max(sheetMask, specMask);
    rgb = v_col.rgb * sheetMask + v_col2.rgb * specMask;
  } else {
    rgb = t.rgb * v_col.rgb;
  }
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  a *= v_col.a;
  if (blendOut > 1.5) {
    fragColor = vec4(mix(vec3(1.0), rgb, clamp(a, 0.0, 1.0)), 1.0);
  } else if (blendOut > 0.5) {
    fragColor = vec4(max(vec3(0.0), 1.0 - rgb * a), 1.0);
  } else {
    fragColor = vec4(rgb, a);
  }
}
"""


#: 折射贴图 shader 状态。
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

#: 折射输出对背景的乘数；贴图只取 alpha 作覆盖度，RGB 不参与。
#: ``refrParam`` = (加法档标记, 预览增益)：Alpha 档 ``lerp(1, 颜色, a)``，加法档 ``1 + 颜色 × a``。
_REFR_FRAG_SRC = """
// 整张贴图按重复平铺（UVCONTROL 滚动），越界夹边只留给 flowmap 位移；梯度取回绕前的 UV，
// 回绕处 mip 层级不跳变
vec4 sample_wrap(vec2 uv)
{
  return textureGrad(image, uv - floor(uv), dFdx(uv), dFdy(uv));
}

void main()
{
  vec4 t = sample_wrap(v_uv);
  float a = t.a;
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  a *= clamp(v_col.a, 0.0, 1.0) * refrParam.y;
  vec3 m = (refrParam.x > 0.5) ? vec3(1.0) + v_col.rgb * a
                               : mix(vec3(1.0), v_col.rgb, a);
  fragColor = vec4(m, 1.0);
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


#: 带流动贴图的折射 shader：从读回的背后画面按流向偏移采样。
_DIST_SHADER = None
_DIST_SHADER_KEEP = []

#: distortionType → 位移倍率，单位为视口高度 / (强度 × p × |f|)。
#: 0 档按实机网格截图估算，1 档约为 0 档的 6 倍；2 档（方向模糊）的采样跨度沿用 1 档。
_DISTORT_SCALE = {0: 0.075, 1: 0.45, 2: 0.45}
#: 方向模糊沿流向的采样数
_DISTORT_BLUR_TAPS = 7

_DIST_VERT_SRC = """
void main()
{
  v_uv = uv;
  v_col = color;
  v_luv = luv;
  v_flowoff = flowoff;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

#: 流向按局部 UV 采样后换算到屏幕方向，长度只取决于 |f|，与渲染体在屏幕上多大无关。
#: 位移 = 倍率 × 强度 × p × |f|（视口高度为单位），p 与两层交叠同 flowmap shader。
#: ``distParam`` = (distortionType, alphaBlend, 倍率, 未使用)；
#: ``screenRect`` = 视口 (x, y, 宽, 高)。输出 = 背后画面采样 × 颜色，覆盖度取贴图 alpha，
#: 由 ALPHA / ADDITIVE 混合完成两种档位。alphaBlend 按线性把未畸变的背景混回，1 时各半。
_DIST_FRAG_SRC = """
vec4 sample_wrap(vec2 uv)
{
  return textureGrad(image, uv - floor(uv), dFdx(uv), dFdy(uv));
}

// 视口帧缓冲为 sRGB 格式：读回的是编码值，写入时会再编码一次，须先解码为线性
vec3 scene_at(vec2 suv)
{
  vec3 c = clamp(texture(sceneTex, clamp(suv, vec2(0.0), vec2(1.0))).rgb, 0.0, 1.0);
  return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c));
}

vec3 displaced(vec2 suv, vec2 d)
{
  if (distParam.x > 1.5) {
    vec3 acc = vec3(0.0);
    for (int i = 0; i < BLUR_TAPS; i++) {
      acc += scene_at(suv - d * (float(i) / float(BLUR_TAPS - 1) - 0.5));
    }
    return acc / float(BLUR_TAPS);
  }
  return scene_at(suv - d);
}

void main()
{
  vec4 t = sample_wrap(v_uv);
  float a = t.a;
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  a *= clamp(v_col.a, 0.0, 1.0) * refrParam.y;

  vec2 f = texture(flowTex, v_luv).rg * 2.0 - 1.0;
  f.y = -f.y;
  // 局部 UV 方向 → 屏幕像素方向：对 d(luv)/d(像素) 求逆
  vec2 jx = dFdx(v_luv);
  vec2 jy = dFdy(v_luv);
  float det = jx.x * jy.y - jy.x * jx.y;
  vec2 dir = vec2(0.0);
  if (abs(det) > 1e-12) {
    vec2 px = vec2(jy.y * f.x - jy.x * f.y, -jx.y * f.x + jx.x * f.y) / det;
    float l = length(px);
    if (l > 0.0) {
      dir = px / l * length(f);
    }
  }
  // 以视口高度为单位 → 屏幕 UV
  vec2 unit = dir * distParam.z * v_flowoff.x * vec2(screenRect.w / screenRect.z, 1.0);
  vec2 suv = (gl_FragCoord.xy - screenRect.xy) / screenRect.zw;

  vec3 bg;
  if (v_flowoff.w > 0.5) {
    float p0 = fract(v_flowoff.z);
    float p1 = fract(v_flowoff.z + 0.5);
    bg = mix(displaced(suv, unit * p1), displaced(suv, unit * p0), 1.0 - abs(p0 * 2.0 - 1.0));
  } else {
    bg = displaced(suv, unit * v_flowoff.z);
  }
  bg = mix(bg, scene_at(suv), 0.5 * clamp(distParam.y, 0.0, 1.0));
  fragColor = vec4(bg * v_col.rgb, a);
}
"""


def _distortion_shader():
    """带流动贴图的折射 shader；建不出来返回 None（调用方退回不位移的乘法）。"""
    global _DIST_SHADER
    if _DIST_SHADER is not None:
        return _DIST_SHADER or None
    try:
        import gpu
        iface = gpu.types.GPUStageInterfaceInfo("efx_dist_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC4", "v_col")
        iface.smooth("VEC2", "v_luv")
        iface.smooth("VEC4", "v_flowoff")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC3", "alphaFix")
        info.push_constant("VEC2", "refrParam")
        info.push_constant("VEC4", "distParam")
        info.push_constant("VEC4", "screenRect")
        info.sampler(0, "FLOAT_2D", "image")
        info.sampler(1, "FLOAT_2D", "flowTex")
        info.sampler(2, "FLOAT_2D", "sceneTex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_in(3, "VEC2", "luv")
        info.vertex_in(4, "VEC4", "flowoff")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(_DIST_VERT_SRC)
        info.fragment_source(_DIST_FRAG_SRC.replace("BLUR_TAPS", str(_DISTORT_BLUR_TAPS)))
        _DIST_SHADER = gpu.shader.create_from_info(info)
        _DIST_SHADER_KEEP[:] = [iface, info]
    except Exception:
        _DIST_SHADER = False
    return _DIST_SHADER or None


#: 读回背后画面用的缓冲，按视口尺寸复用
_SCENE_BUF = {}


def _grab_scene():
    """读回当前帧缓冲作为背后画面，返回 (GPUTexture, 视口矩形)；失败返回 None。"""
    try:
        import gpu
        fb = gpu.state.active_framebuffer_get()
        x, y, w, h = gpu.state.viewport_get()
        if w <= 0 or h <= 0:
            return None
        buf = _SCENE_BUF.get((w, h))
        if buf is None:
            _SCENE_BUF.clear()
            buf = gpu.types.Buffer("FLOAT", w * h * 4)
            _SCENE_BUF[(w, h)] = buf
        fb.read_color(x, y, w, h, 4, 0, "FLOAT", data=buf)
        tex = gpu.types.GPUTexture((w, h), format="RGBA16F", data=buf)
    except Exception:
        return None
    return tex, (float(x), float(y), float(w), float(h))


#: flowmap shader 在采样前偏移主贴图 UV。
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

#: flowmap 按局部 UV 采样；其偏移量已在 CPU 侧换算到当前贴图格。流动矢量的 G 以贴图像素
#: 向下为正，而 v 向上为正，y 分量须取反。
#: ``v_flowoff`` = (x 量, y 量, 相位, 循环标记)。循环时两层相位错开半轮各采样一次，按三角波
#: 权重混合：一层回绕时权重为 0，另一层权重为 1，因此没有跳变。
_FLOW_FRAG_SRC = """
void main()
{
  vec2 f = texture(flowTex, v_luv).rg * 2.0 - 1.0;
  f.y = -f.y;
  // 整张贴图按重复平铺（UVCONTROL 滚动），flowmap 位移越界才夹边
  vec2 uv = v_uv - floor(v_uv);
  vec2 gx = dFdx(v_uv);
  vec2 gy = dFdy(v_uv);
  vec4 t;
  if (v_flowoff.w > 0.5) {
    float p0 = fract(v_flowoff.z);
    float p1 = fract(v_flowoff.z + 0.5);
    vec4 t0 = textureGrad(image, uv - f * v_flowoff.xy * p0, gx, gy);
    vec4 t1 = textureGrad(image, uv - f * v_flowoff.xy * p1, gx, gy);
    t = mix(t1, t0, 1.0 - abs(p0 * 2.0 - 1.0));
  } else {
    t = textureGrad(image, uv - f * v_flowoff.xy * v_flowoff.z, gx, gy);
  }
  vec3 rgb;
  float a = t.a;
  if (fireLerp >= 0.0) {
    float fireMask = t.g;
    float smokeMask = t.r * mix(t.a, t.b, fireLerp);
    rgb = v_col.rgb * fireMask + v_col2.rgb * smokeMask;
  } else if (waterLerp >= 0.0) {
    // 两层遮罩都已含 alpha，不透明度取两者较大者
    float sheetMask = t.a * mix(t.g, t.b, waterLerp);
    float specMask = t.r * t.a;
    a = max(sheetMask, specMask);
    rgb = v_col.rgb * sheetMask + v_col2.rgb * specMask;
  } else {
    rgb = t.rgb * v_col.rgb;
  }
  a = (a < alphaFix.x) ? 0.0 : pow(a, alphaFix.y);
  a *= v_col.a;
  if (blendOut > 1.5) {
    fragColor = vec4(mix(vec3(1.0), rgb, clamp(a, 0.0, 1.0)), 1.0);
  } else if (blendOut > 0.5) {
    fragColor = vec4(max(vec3(0.0), 1.0 - rgb * a), 1.0);
  } else {
    fragColor = vec4(rgb, a);
  }
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
        iface.smooth("VEC4", "v_flowoff")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC3", "alphaFix")
        info.push_constant("FLOAT", "fireLerp")
        info.push_constant("FLOAT", "waterLerp")
        info.push_constant("FLOAT", "blendOut")
        info.sampler(0, "FLOAT_2D", "image")
        info.sampler(1, "FLOAT_2D", "flowTex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_in(3, "VEC4", "col2")
        info.vertex_in(4, "VEC2", "luv")
        info.vertex_in(5, "VEC4", "flowoff")
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
    """构建贴图 shader；不可用时返回 ``None`` 以回退纯色绘制。

    使用 ``GPUShaderCreateInfo``，避免已废弃的字符串构造器。
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
        info.push_constant("FLOAT", "fireLerp")
        info.push_constant("FLOAT", "waterLerp")
        info.push_constant("FLOAT", "blendOut")
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


#: 带 AlphaMap 遮罩的网格 shader 状态。
_MASK_SHADER = None
_MASK_SHADER_KEEP = []

_MASK_VERT_SRC = """
void main()
{
  v_uv = uv;
  v_muv = muv;
  v_col = color;
  v_col2 = col2;
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""


def _mask_frag_src():
    """在贴图 shader 的基础上加材质流动贴图与遮罩。

    流动贴图分别按主贴图 UV、遮罩 UV 采样，沿用渲染体 flowmap 的模型（材质这组的单位为推测）：
    一层采样 = UV − 强度 × p × f，f = RG × 2 − 1、y 取反；两层相位错开半轮、按三角波权重交叠，
    p 每秒推进 speed 轮，速度为 0 时只剩 p = 0.5 那层。遮罩 R 通道乘进不透明度。
    ``meshFlow`` = (主贴图扭曲强度, 遮罩扭曲强度)，``meshPhase`` = (主贴图相位, 遮罩相位)；
    没有遮罩或流动贴图时绑定白图、强度为 0。
    """
    helper = """
vec4 mask_wrap(vec2 uv)
{
  return textureGrad(maskTex, uv - floor(uv), dFdx(uv), dFdy(uv));
}

vec4 flow_wrap(vec2 uv)
{
  return textureGrad(flowTex, uv - floor(uv), dFdx(uv), dFdy(uv));
}

vec2 flow_dir(vec2 uv)
{
  vec2 f = flow_wrap(uv).rg * 2.0 - 1.0;
  f.y = -f.y;
  return f;
}

vec4 flow_main(vec2 uv)
{
  if (meshFlow.x == 0.0) {
    return sample_wrap(uv);
  }
  vec2 f = flow_dir(uv) * meshFlow.x;
  float p0 = fract(meshPhase.x);
  float p1 = fract(meshPhase.x + 0.5);
  return mix(sample_wrap(uv - f * p1), sample_wrap(uv - f * p0), 1.0 - abs(p0 * 2.0 - 1.0));
}

vec4 flow_mask(vec2 uv)
{
  if (meshFlow.y == 0.0) {
    return mask_wrap(uv);
  }
  vec2 f = flow_dir(uv) * meshFlow.y;
  float p0 = fract(meshPhase.y);
  float p1 = fract(meshPhase.y + 0.5);
  return mix(mask_wrap(uv - f * p1), mask_wrap(uv - f * p0), 1.0 - abs(p0 * 2.0 - 1.0));
}
"""
    src = _FRAG_SRC.replace("void main()", helper + "\nvoid main()", 1)
    src = src.replace("  vec4 t = sample_wrap(v_uv);",
                      "  vec4 t = flow_main(v_uv);", 1)
    return src.replace(
        "  a = (a < alphaFix.x)",
        "  a *= flow_mask(v_muv).r;\n"
        "  a = (a < alphaFix.x)", 1)


def _mask_shader():
    """网格底色与遮罩分用两套 UV、带 mrl3 flowmap 的贴图 shader；建不出来返回 None。"""
    global _MASK_SHADER
    if _MASK_SHADER is not None:
        return _MASK_SHADER or None
    try:
        import gpu
        iface = gpu.types.GPUStageInterfaceInfo("efx_sim_mask_iface")
        iface.smooth("VEC2", "v_uv")
        iface.smooth("VEC2", "v_muv")
        iface.smooth("VEC4", "v_col")
        iface.smooth("VEC4", "v_col2")
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant("MAT4", "ModelViewProjectionMatrix")
        info.push_constant("VEC3", "alphaFix")
        info.push_constant("FLOAT", "fireLerp")
        info.push_constant("FLOAT", "waterLerp")
        info.push_constant("FLOAT", "blendOut")
        info.push_constant("VEC2", "meshFlow")
        info.push_constant("VEC2", "meshPhase")
        info.sampler(0, "FLOAT_2D", "image")
        info.sampler(1, "FLOAT_2D", "maskTex")
        info.sampler(2, "FLOAT_2D", "flowTex")
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC2", "uv")
        info.vertex_in(2, "VEC4", "color")
        info.vertex_in(3, "VEC4", "col2")
        info.vertex_in(4, "VEC2", "muv")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.vertex_source(_MASK_VERT_SRC)
        info.fragment_source(_mask_frag_src())
        _MASK_SHADER = gpu.shader.create_from_info(info)
        _MASK_SHADER_KEEP[:] = [iface, info]
    except Exception:
        _MASK_SHADER = False
    return _MASK_SHADER or None


#: 分通道 shader 缺遮罩 / flowmap 时绑定的 1×1 白图
_WHITE_TEX = []


def _white_texture():
    if not _WHITE_TEX:
        try:
            import gpu
            buf = gpu.types.Buffer("FLOAT", 4, [1.0, 1.0, 1.0, 1.0])
            _WHITE_TEX.append(gpu.types.GPUTexture((1, 1), format="RGBA16F", data=buf))
        except Exception:
            return None
    return _WHITE_TEX[0]


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
    _tex_sampling(tex)
    _GPU_TEX[name] = tex
    return tex


def _tex_sampling(tex):
    """预览贴图统一的采样设置。"""
    if hasattr(tex, "mipmap_mode"):
        # 缩小采样时取 mip 层级，变模糊而非出锯齿
        try:
            tex.mipmap_mode(use_mipmap=True, use_filter=True)
        except Exception:
            pass
    if hasattr(tex, "extend_mode"):
        # 越界取边缘像素，与游戏中 flowmap 位移一致；UV 的整张平铺由 shader 自行回绕
        try:
            tex.extend_mode("EXTEND")
        except Exception:
            pass


def _clear_refraction_shader():
    global _REFR_SHADER, _FLOW_SHADER, _MASK_SHADER, _DIST_SHADER
    _DIST_SHADER = None
    _DIST_SHADER_KEEP[:] = []
    _SCENE_BUF.clear()
    _MASK_SHADER = None
    _MASK_SHADER_KEEP[:] = []
    _REFR_SHADER = None
    _REFR_SHADER_KEEP[:] = []
    _FLOW_SHADER = None
    _FLOW_SHADER_KEEP[:] = []


def _clear_tex_cache():
    _GPU_TEX.clear()
    _MESH_MAT_INFO.clear()


def _collect_track(tr, scene, rv3d, buckets, points, point_colors, lines,
                   line_colors):
    """将一个 track 的渲染项装配到按绘制状态分组的顶点桶。"""
    from ..efx_format.sim.state import RenderItem as _RenderItem
    import copy as _copy

    items = tr.get("items") or ()
    rows = tr.get("ref_rows")
    entry = bpy.data.objects.get(tr["entry_name"])
    if rows is None or entry is None:
        return
    r0, r1, r2 = rows
    show_shape = bool(getattr(scene, "efx_sim_show_shape", True))
    if not items and not show_shape:
        return          # 没粒子也没要画形状 → 后面那一堆准备工作全省了

    size_mul = float(getattr(scene, "efx_sim_particle_size", 1.0))
    draw_mode = getattr(scene, "efx_sim_draw_mode", "QUADS")
    blend = getattr(scene, "efx_sim_blend", "AUTO")
    hdr_mode = getattr(scene, "efx_sim_hdr_mode", "preserve_hue")
    # 逐帧读取，避免逐粒子访问 Scene RNA。
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
    cam_pos = _camera_position(rv3d)
    #: 正交视图没有真正的相机点，视线取固定的视图方向
    persp = bool(getattr(rv3d, "is_perspective", True))
    #: 条带批量路径常量；无 numpy 时使用 Python 兜底。
    np_ctx = _ribbon_np_ctx(rows, view_dir)

    def _order_of(it):
        """返回渲染项所属 Entry 的绘制次序键。"""
        key = it.extra.get("entry_key")
        if not key:
            return track_order
        got = order_memo.get(key)
        if got is None:
            got = entry_order(bpy.data.objects.get(key)) if key else track_order
            order_memo[key] = got
        return got

    def _flow_of(it, tex):
        """这一项的 (flowmap 贴图名, (强度, 相位, 循环标记))；不该走 flowmap 就 ("", None)。

        没有序列帧贴图就没有可推的 UV，直接不走——`use_tex` 关掉时同理。
        """
        if not tex or not flow_images:
            return "", None
        amt = it.extra.get("flowmap")
        if not amt:
            return "", None
        name = flow_images.get(it.extra.get("entry_key"), root_flow)
        if not name or _gpu_texture(name) is None:
            return "", None
        return name, (float(amt) * flow_gain,
                      float(it.extra.get("flowmap_phase", 0.0)),
                      1.0 if it.extra.get("flowmap_loop") else 0.0)

    def _bucket_for(it, tex, flow_tex="", after=False, dist=None, mask="", prio=0):
        """返回 `(桶 key, 桶)`。key = (绘制次序, 混合模式, 贴图, alpha 修正, 流动贴图,
        RGBFIRE/RGBWATER 通道混合系数, 网格分通道参数)。
        网格分通道参数为 (遮罩, mrl3 flowmap, (主贴图扭曲强度, 遮罩扭曲强度))，其余为 ""。`after` 让这一项排在同一 Entry 的其余桶之后。

        绘制次序：粒子为 (根集合名, efx_index, 0, 0, 0, efx_index, after)；网格传入 `dist`（实例
        沿视线的深度）与 `prio`（mrl3 优先级），为 (根集合名, efx_index, 1, 优先级, −深度,
        efx_index, after)。装配时同一文件的网格整组先按优先级、再按深度由远到近排，见
        `_draw_order_key`。

        次序键放最前面：完全重合的面片谁盖谁由绘制顺序决定（粒子不写深度），而实机
        是按 entry 在文件里的排布定的，所以桶必须能按它排序，见 `entry_order`。

        alpha 修正（ALPHACORRECTION）、RGBFIRE 的 `fireLerp`、RGBWATER 的
        `waterLerp`（折射项为 distortionType 与 alphaBlend）都是 shader 的 push constant，逐 draw 生效，所以都必须进 key，
        否则同一个 shader 程序画完其中一种的桶又画别的桶时会沿用上一次的取值。
        都是**逐 entry**的，一个场景里就那么几种取值，分桶开销可忽略。
        """
        mode = it.blend
        if mode in _REFRACT_MODES:
            # 折射是整条通道的性质，不该被「强制混合模式」那个调试开关顶掉
            pass
        elif blend != "AUTO":
            mode = blend
        if mode not in _BLEND_MODES:
            mode = "ALPHA"
        low, gamma = it.extra.get("alpha_fix") or (0.0, 1.0)
        # 两种双层通道模式互斥，关闭时使用通用贴图路径。
        fire_lerp = it.extra.get("rgbfire_lerp")
        fire_lerp = -1.0 if fire_lerp is None else fire_lerp
        water_lerp = it.extra.get("rgbwater_lerp")
        water_lerp = -1.0 if water_lerp is None else water_lerp
        lerp = (fire_lerp, water_lerp)
        if mode in _REFRACT_MODES:
            # 折射不走双层通道，这一格改放 (distortionType, alphaBlend)
            lerp = tuple(it.extra.get("refraction") or (0, 0.0))
        root, idx = _order_of(it)
        if dist is None:
            order = (root, idx, 0, 0, 0.0, idx, int(after))
        else:
            order = (root, idx, 1, int(prio), -round(dist, 4), idx, int(after))
        key = (order, mode, tex, (low, gamma, 0.0), flow_tex, lerp, mask)
        b = buckets.get(key)
        if b is None:
            # 贴图桶额外保存核心色、UV、numpy 网格分块及可选 flowmap 数据。
            b = [[], [], ([] if tex else None), ([] if tex else None), [],
                 ([] if flow_tex else None), ([] if flow_tex else None)]
            buckets[key] = b
        return key, b

    #: 同一 Entry/viscon 的网格几何在本次装配中只解析一次。
    mesh_memo = {}
    #: Entry 名到绘制次序键的本次装配缓存。
    order_memo = {}
    track_order = tr.get("order") or ("", 0)
    mat_images = tr.get("mesh_images") or {}
    mat_masks = tr.get("mesh_masks") or {}
    mat_params = tr.get("mesh_params") or {}
    mat_flows = tr.get("mesh_flows") or {}
    #: 材质流动的时间轴取本 track 的模拟时间（秒）
    sim_seconds = max(0, tr["sim"].frame) / (float(getattr(tr["sim"].config, "fps", 60)) or 60.0)
    flow_images = (tr.get("flow_images") or {}) if use_tex else {}
    emissive_images = (tr.get("emissive_images") or {}) if use_tex else {}

    def _emissive_of(it):
        """贴花自发光贴图名；未载入返回 ""。"""
        name = emissive_images.get(it.extra.get("entry_key") or tr["entry_name"], "")
        return name if (name and _gpu_texture(name) is not None) else ""
    root_flow = flow_images.get(tr["entry_name"], "")
    flow_gain = float(getattr(scene, "efx_sim_flowmap_gain", 1.0))
    #: 折射预览增益；无贴图和贴图路径都应用它。
    refr_gain = float(getattr(scene, "efx_sim_refraction_gain", 1.0))

    def _geom_of(it):
        """返回网格几何和贴图；缓存键必须包含 viscon 以保持随机分组。"""
        key = it.extra.get("entry_key") or ""
        viscon = it.extra.get("viscon")
        memo_key = (key, viscon)
        got = mesh_memo.get(memo_key)
        if got is None:
            owner = bpy.data.objects.get(key) or entry
            meshes = _bound_meshes_for(owner, viscon)
            if not meshes:
                # 无绑定网格时改用占位几何，并记录诊断信息。
                miss = tr.setdefault("mesh_missing", [])
                nm = getattr(owner, "name", "") or "?"
                if nm not in miss:
                    miss.append(nm)
            m0 = meshes[0] if meshes else None
            # MATERIAL 指定贴图优先于绑定网格材质；此时 mrl3 的系数与自发光层不适用。
            override = mat_images.get(key)
            info = _mesh_mat_info(m0)
            name = (override or info["albedo"]) if use_tex else ""
            if name and _gpu_texture(name) is None:
                name = ""
            ename = "" if (override or not use_tex) else info["emissive_img"]
            if ename and _gpu_texture(ename) is None:
                ename = ""
            factor = _NO_FACTOR if override else info["base"]
            # MATERIAL 覆盖的参数优先于 mrl3
            mp = mat_params.get(key) or {}
            dop = float(mp.get("fDotOpacity", info["dot_opacity"]))
            dot = (bool(dop), bool(mp.get("bDotInverse", info["dot_inverse"])), dop,
                   float(mp.get("fDotOpacityFactor", info.get("dot_factor", 1.0))))
            vtx_alpha = bool(mp.get("fVertexAlpha", info["vertex_alpha"]))
            mask_uv2 = (not mp["bUseUVPrimaryAM"]) if "bUseUVPrimaryAM" in mp else info["mask_uv2"]
            geom = _mesh_tris_game_multi(meshes)
            # MATERIAL 覆盖的 Alpha 遮罩优先；只覆盖底色时 mrl3 的遮罩不再适用
            mask = mat_masks.get(key) or ("" if override else info["mask"])
            if mask and (not use_tex or _gpu_texture(mask) is None):
                mask = ""
            # MATERIAL 覆盖的流动贴图优先；只覆盖底色时 mrl3 的流动贴图不再适用
            flow = mat_flows.get(key) or ("" if override else info["flow"])
            if flow and (not use_tex or _gpu_texture(flow) is None):
                flow = ""
            flow_k = (float(mp.get("fFlowStrength", info["flow_k"][0])),
                      float(mp.get("fSecondaryFlowStrength", info["flow_k"][1])))
            speed = info.get("flow_speed") or (0.0, 0.0)
            speed = (float(mp.get("fFlowSpeed", speed[0])),
                     float(mp.get("fFlowSpeedSecondary", speed[1])))
            # 分通道路径（mesh shader）：有遮罩或材质流动贴图，或网格带第二套 UV 时 uv1 / uv2 各管一套
            dual = (bool(name) and geom[2] is not None
                    and (bool(mask) or bool(flow) or geom[5] is not None))
            mkey = ((mask, flow, flow_k if flow else (0.0, 0.0),
                     (round(sim_seconds * speed[0], 4), round(sim_seconds * speed[1], 4)))
                    if dual else None)
            got = (geom, name, factor, ename, info["emissive"],
                   vtx_alpha, dot, mkey, mask_uv2, info["priority"])
            mesh_memo[memo_key] = got
        return got

    def _corners_of(it, tex_name):
        """这一项的四角 UV，含 UVCONTROL 的滚动/缩放。"""
        c = _uv_corners(it, flip_v, tex_name)
        xf = it.extra.get("uv_xform")
        if not xf or not c:
            return c
        if flip_v:
            from ..efx_format.sim.behaviors.uvcontrol import flip_v_xform
            xf = flip_v_xform(xf)
        su, sv, ou, ov = xf
        return tuple((u * su + ou, v * sv + ov) for (u, v) in c)

    def _layers_of(it, col, tex=""):
        """返回外缘和核心色；折射不使用双层染色，保留其亮度语义。"""
        if it.blend in _REFRACT_MODES:
            c = col if tex else _multiply_tint(col, refr_gain,
                                              add=it.blend == "REFRACT_ADD")
            return c, c
        lay = it.extra.get("layers")
        if not lay:
            return col, col
        bt = it.extra.get("base_tint") or (1.0, 1.0, 1.0)
        a = _display_color((lay[0][0] * bt[0], lay[0][1] * bt[1], lay[0][2] * bt[2],
                            col[3]), hdr_mode)
        b = _display_color((lay[1][0] * bt[0], lay[1][1] * bt[1], lay[1][2] * bt[2],
                            col[3]), hdr_mode)
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

    #: 条带延后按桶批量展开，避免逐条调用 numpy。
    ribbon_pend = {}

    if show_shape:
        # 直接使用模拟器的轮廓计算，避免预览和发射逻辑分叉。
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
        if it.extra.get("decal_ground"):
            # 向下投射的贴花贴在地面（世界 Z=0）上，不跟随发射器高度。
            center = (center[0], center[1], 0.0)
        tex_name = _tex_of(it)
        if it.blend in _MULTIPLY_MODES:
            # 乘法路径不能经过 HDR 映射，否则会丢失 brightness 语义。
            col = tuple(it.color)
        else:
            col = _display_color(it.color, hdr_mode)
        kind = it.kind

        if kind == "RIBBON" and it.points:
            key, b = _bucket_for(it, tex_name)
            edge, core = _layers_of(it, col, tex_name)
            corners = _corners_of(it, tex_name)
            uv_scale = it.extra.get("uv_scale")
            if uv_scale is not None and corners and b[2] is not None:
                # 贴图缩放需要按重复边界切片，不进批量路径
                _emit_ribbon_uv(b[0], b[1], b[2], it, edge, size_mul, _world,
                                view_dir, corners, uv_scale, col2s=b[3], core=core)
            elif np_ctx is not None:
                # 延后到本轮末尾按桶批量展开。
                pend = ribbon_pend.get(key)
                if pend is None:
                    pend = ribbon_pend[key] = (b, [])
                pend[1].append((it, edge, core, corners))
            else:
                _emit_ribbon(b[0], b[1], b[2], it, edge, size_mul, _world,
                             view_dir, corners, col2s=b[3], core=core)
        elif kind == "MESH":
            # 子实例按其所属 Entry 查询绑定网格。
            (geom, tex_name, factor, etex, efactor, vtx_a, dot, mkey, mask_uv2,
             prio) = _geom_of(it)
            mask_uv = mask_uv2 if mkey is not None else None
            # 网格之间先按 mrl3 优先级，同级再按实例轴心（发射位置）沿视线的深度排序，与网格
            # 几何本身在哪无关；不做深度遮挡。都相同时游戏里先后不稳定，预览退回 Entry 顺序
            dist = sum((cam_pos[i] - center[i]) * view_dir[i] for i in range(3))
            dot_op = ((cam_pos if persp else None), dot[1], view_dir, dot[2], dot[3]) if dot[0] else None
            if factor != _NO_FACTOR:
                # mrl3 的 BaseMapFactor 与底色贴图相乘，第 4 位是不透明度系数
                c = it.color
                c = (c[0] * factor[0], c[1] * factor[1], c[2] * factor[2],
                     c[3] * factor[3])
                col = c if it.blend in _MULTIPLY_MODES else _display_color(c, hdr_mode)
            # 网格没有 UV 时无从采样流动贴图
            flow_tex, flow_amt = (_flow_of(it, tex_name) if (geom[2] is not None and mkey is None)
                                  else ("", None))
            uvc_amt = it.extra.get("flowmap")
            if mkey is not None and mkey[1] and uvc_amt:
                # 分通道路径：UVCONTROL 的 flowmap 组驱动材质流动贴图，同时扭曲底色与遮罩，
                # 取代材质自身的强度与速度（作用层为推测）
                amt = float(uvc_amt) * flow_gain
                ph = round(float(it.extra.get("flowmap_phase", 0.0)), 4)
                mkey = (mkey[0], mkey[1], (amt, amt), (ph, ph))
            _key, (bv, bc, bu, b2, bnp, blu, bfo) = _bucket_for(it, tex_name, flow_tex,
                                                                dist=dist, mask=mkey or "",
                                                                prio=prio)
            edge, core = _layers_of(it, col, tex_name)
            _emit_mesh(bv, bc, bnp, it, edge, size_mul, rows, geom,
                       uvs=bu, col2s=b2, core=core, luvs=blu, flowoffs=bfo,
                       flow_amt=flow_amt, vertex_alpha=vtx_a, dot_opacity=dot_op,
                       mask_uv=mask_uv)
            em = it.extra.get("emissive")
            if etex and em and geom[2] is not None and max(em[0], em[1], em[2]) > 0.0:
                # 自发光层：EmissiveMap × EmissiveMapFactor × 自发光色，叠加在底色层之上；
                # 不透明度沿用底色层（含生命期渐隐与遮罩）
                ec = (em[0] * efactor[0], em[1] * efactor[1], em[2] * efactor[2],
                      it.color[3] * factor[3] * efactor[3] * em[3])
                ec = _display_color(ec, hdr_mode)
                eit = _copy.copy(it)
                eit.blend = "ADDITIVE"
                _key, (bv, bc, bu, b2, bnp, _l, _f) = _bucket_for(eit, etex, after=True,
                                                                  dist=dist, mask=mkey or "",
                                                                  prio=prio)
                _emit_mesh(bv, bc, bnp, eit, ec, size_mul, rows, geom,
                           uvs=bu, col2s=b2, core=ec, vertex_alpha=vtx_a, dot_opacity=dot_op,
                           mask_uv=mask_uv)
        elif draw_mode in ("QUADS", "BOTH"):
            # 片尺寸与位置同为游戏单位，统一应用坐标换算。
            hw = max(1e-5, size_mul * abs(it.size.x) * _UNIT * 0.5)
            hh = max(1e-5, size_mul * abs(it.size.y) * _UNIT * 0.5)
            if it.axis_u is not None and it.axis_v is not None:
                # PLANE 使用属性轴而非面朝相机。
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
                # flowmap 位移按当前序列格尺寸缩放。
                us = [c[0] for c in corners]
                vs = [c[1] for c in corners]
                amt, ph, lap = flow_amt
                if it.blend in _REFRACT_MODES:
                    # 折射位移按屏幕计，不随序列格缩放
                    off = (amt, amt, ph, lap)
                else:
                    off = (amt * (max(us) - min(us)), amt * (max(vs) - min(vs)), ph, lap)
                blu.extend(_QUAD_LUV)
                bfo.extend([off] * 6)
            emis = it.extra.get("decal_emissive")
            etex = _emissive_of(it) if emis is not None else ""
            if etex:
                # 贴花自发光：用 EmissiveMap 以加法混合再画一层同形面片。
                e_it = _RenderItem(kind="PLANE")
                e_it.blend = "ADDITIVE"
                e_it.extra["entry_key"] = it.extra.get("entry_key")
                _key, (ev, ec, eu, e2, _np, _lu, _fo) = _bucket_for(e_it, etex)
                ecol = _display_color(emis, hdr_mode)
                ev.extend(_quad_verts(center, qr, qu, hw, hh))
                ec.extend([ecol] * 6)
                e2.extend([ecol] * 6)
                eu.extend(_quad_uvs(_corners_of(it, etex)))

        if draw_mode in ("POINTS", "BOTH") and kind not in ("RIBBON", "MESH"):
            points.append(center)
            point_colors.append(col)
        vel = it.extra.get("vel")
        if show_vel and vel is not None:
            # 速度按可读比例绘制。
            vx, vy, vz = _to_blender(vel)
            k = 8.0
            lines.append(center)
            lines.append((center[0] + vx * k, center[1] + vy * k, center[2] + vz * k))
            line_colors.extend([col, (col[0], col[1], col[2], 0.0)])

    for b, group in ribbon_pend.values():
        try:
            _emit_ribbons_np(b[4], group, size_mul, np_ctx)
        except Exception:
            # 批量路径失败时整组回退，避免混入不完整分块。
            for it, edge, core, corners in group:
                _emit_ribbon(b[0], b[1], b[2], it, edge, size_mul, _world,
                             view_dir, corners, col2s=b[3], core=core)


#: 参与绘制缓存签名的 Scene 旋钮：任一变了就得重新装配顶点。
_DRAW_KNOBS = ("efx_sim_particle_size", "efx_sim_draw_mode", "efx_sim_blend",
               "efx_sim_hdr_mode", "efx_sim_mesh_rot_space",
               "efx_sim_show_velocity", "efx_sim_uv_flip_v", "efx_sim_textured",
               "efx_sim_draw_order", "efx_sim_point_px",
               "efx_sim_ribbon_subdiv_max",
               "efx_sim_refraction_gain",
               "efx_sim_flowmap_gain", "efx_sim_show_shape")


def _draw_signature(scene, rv3d, trs):
    """返回绘制负载缓存签名；任一输入变化均需重新装配顶点。"""
    vm = rv3d.view_matrix
    return (_P["gen"],
            tuple(vm[i][j] for i in range(4) for j in range(4)),
            tuple(getattr(scene, k, None) for k in _DRAW_KNOBS),
            tuple(t.get("ref_rows") for t in trs))


def _draw_order_key(buckets):
    """桶的排序键：粒子按 Entry 顺序；同一文件的网格整组排在其中最靠前的 MESH Entry 处，
    组内先按 mrl3 优先级从小到大，同级按离相机距离由远到近，再相同按 Entry 顺序。"""
    anchor = {}
    for k in buckets:
        o = k[0]
        if o[2]:
            anchor[o[0]] = min(anchor.get(o[0], o[1]), o[1])

    def key(k):
        o = k[0]
        if o[2]:
            o = (o[0], anchor[o[0]]) + o[2:]
        return (o,) + k[1:]
    return key


def _build_payload(scene, rv3d, trs):
    """装配顶点并创建可复用的 ``GPUBatch`` 绘制负载。"""
    from gpu_extras.batch import batch_for_shader

    buckets = {}          # 按绘制状态分组的顶点数据。
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
    mask_shader = _mask_shader()

    # Alpha 与 Add 不可交换；默认保留 Entry 排序以决定重叠覆盖关系。
    if getattr(scene, "efx_sim_draw_order", "entry") == "entry":
        order = sorted(buckets.keys(), key=_draw_order_key(buckets))
    else:
        order = sorted(buckets.keys(), key=lambda k: (k[1] == "ADDITIVE",))

    refr_shader = _refraction_shader()
    dist_shader = _distortion_shader()
    refr_gain = float(getattr(scene, "efx_sim_refraction_gain", 1.0))
    tris = []
    for key in order:
        bv, bc, bu, b2, bnp, blu, bfo = buckets[key]
        if not (bv or bnp):
            continue
        _bo, mode, tex_name, fix, flow_name, lerp, mkey = key
        bmu = None
        if bnp:
            bv, bc, bu, b2, blu, bfo, bmu = _join_chunks(bv, bc, bu, b2, bnp, blu, bfo)
        tex = _gpu_texture(tex_name) if (bu is not None) else None
        white = _white_texture() if mkey else None
        if (mkey and bmu is not None and tex is not None and white is not None
                and mask_shader is not None):
            mask_name, mflow, fk, fphase = mkey
            mtex = _gpu_texture(mask_name) or white
            ftex = _gpu_texture(mflow) or white
            tris.append((mode, mask_shader, (tex, mtex, ftex, fk, fphase), fix, lerp,
                         batch_for_shader(mask_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "col2": b2, "muv": bmu})))
            continue
        ftex = (_gpu_texture(flow_name)
                if (flow_name and blu is not None) else None)
        if (mode in _REFRACT_MODES and ftex is not None and tex is not None
                and dist_shader is not None):
            # 折射 + 流动贴图：背后画面按流向位移，流动贴图不再偏移主贴图 UV
            dtype = int(lerp[0])
            dist_param = (float(dtype), float(lerp[1]),
                          _DISTORT_SCALE.get(dtype, _DISTORT_SCALE[0]), 0.0)
            refr_param = (1.0 if mode == "REFRACT_ADD" else 0.0, refr_gain)
            tris.append((mode, dist_shader, (tex, ftex), (fix, refr_param, dist_param), None,
                         batch_for_shader(dist_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "luv": blu, "flowoff": bfo})))
            continue
        if mode in _REFRACT_MODES:
            ftex = None
        if ftex is not None and tex is not None and flow_shader is not None:
            tris.append((mode, flow_shader, (tex, ftex), fix, lerp,
                         batch_for_shader(flow_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "col2": b2, "luv": blu,
                                           "flowoff": bfo})))
            continue
        if mode in _REFRACT_MODES:
            # 折射不使用双层通道混合；贴图 shader 不可用时回退整片乘法。
            if tex is not None and refr_shader is not None:
                refr_param = (1.0 if mode == "REFRACT_ADD" else 0.0, refr_gain)
                tris.append((mode, refr_shader, tex, (fix, refr_param), None,
                             batch_for_shader(refr_shader, "TRIS",
                                              {"pos": bv, "uv": bu, "color": bc})))
            else:
                tris.append((mode, flat, None, None, None,
                             batch_for_shader(flat, "TRIS",
                                              {"pos": bv, "color": bc})))
        elif tex is not None and tex_shader is not None:
            tris.append((mode, tex_shader, tex, fix, lerp,
                         batch_for_shader(tex_shader, "TRIS",
                                          {"pos": bv, "uv": bu, "color": bc,
                                           "col2": b2})))
        else:
            if mode in _BLEND_OUT:
                bc = _flat_blend_colors(bc, mode)
            tris.append((mode, flat, None, None, None,
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
    """POST_VIEW draw handler；仅绘制现有渲染项。"""
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
        cam = _camera_position(rv3d)
        if cam != _P["cam_pos"]:
            _P["cam_pos"] = cam
            # 暂停时视角变化只重建依赖相机的渲染项，不推进模拟
            if not _P["playing"] and any(_view_dependent(t) for t in trs):
                _P["needs_items"] = True
    if rv3d is None:
        return
    scene = context.scene

    # 分屏视图独立缓存；优先稳定的底层指针而非临时 Python 包装对象。
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
            _P["draw_cache"].clear()    # 释放已失效区域缓存。
        _P["draw_cache"][ck] = (sig, payload)
    else:
        payload = got[1]

    tris, flat, pt, ln = payload
    blend = getattr(scene, "efx_sim_blend", "AUTO")

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)      # 粒子间不写深度，仍受场景深度测试约束。
    dist_shader = _DIST_SHADER or None
    #: 背后画面在第一个位移折射桶之前读回一次，之后的桶共用
    grabbed = None
    try:
        for mode, shader, tex, fix, lerp, batch in tris:
            if dist_shader is not None and shader is dist_shader:
                if grabbed is None:
                    grabbed = _grab_scene() or False
                if not grabbed:
                    continue
                # 源色已是背后画面 × 颜色，按 Alpha / 加法正常混合
                gpu.state.blend_set("ADDITIVE" if mode == "REFRACT_ADD" else "ALPHA")
                shader.bind()
                shader.uniform_sampler("image", tex[0])
                shader.uniform_sampler("flowTex", tex[1])
                shader.uniform_sampler("sceneTex", grabbed[0])
                shader.uniform_float("alphaFix", fix[0])
                shader.uniform_float("refrParam", fix[1])
                shader.uniform_float("distParam", fix[2])
                shader.uniform_float("screenRect", grabbed[1])
                batch.draw(shader)
                continue
            gpu.state.blend_set(_GPU_BLEND.get(mode, mode))
            if tex is not None:
                shader.bind()
                if isinstance(tex, tuple) and len(tex) == 5:
                    # 网格分通道：(主图, 遮罩, 材质流动贴图, 两个扭曲强度, 两个相位)
                    shader.uniform_sampler("image", tex[0])
                    shader.uniform_sampler("maskTex", tex[1])
                    shader.uniform_sampler("flowTex", tex[2])
                    shader.uniform_float("meshFlow", tex[3])
                    shader.uniform_float("meshPhase", tex[4])
                elif isinstance(tex, tuple):
                    # flowmap 使用主图与流动图两个采样器。
                    shader.uniform_sampler("image", tex[0])
                    shader.uniform_sampler("flowTex", tex[1])
                else:
                    shader.uniform_sampler("image", tex)
                if isinstance(fix, tuple) and len(fix) == 2:
                    # 折射参数：(alphaFix, refrParam)。
                    shader.uniform_float("alphaFix", fix[0])
                    shader.uniform_float("refrParam", fix[1])
                elif fix is not None:
                    # (lowPass, contrast_gamma, 未使用)。
                    shader.uniform_float("alphaFix", fix)
                    if lerp is not None:
                        # 每次绑定均设置两个值，避免前一桶的 shader 状态泄漏。
                        shader.uniform_float("fireLerp", lerp[0])
                        shader.uniform_float("waterLerp", lerp[1])
                    shader.uniform_float("blendOut", _BLEND_OUT.get(mode, 0.0))
            batch.draw(shader)

        overlay = "ADDITIVE" if blend == "ADDITIVE" else "ALPHA"
        if pt is not None:
            gpu.state.blend_set(overlay)
            gpu.state.point_size_set(max(1.0, float(
                getattr(scene, "efx_sim_point_px", 4))))
            pt.draw(flat)
        if ln is not None:
            gpu.state.blend_set("ALPHA")     # 速度线保持可读的调试叠加层。
            ln.draw(flat)
    except Exception:
        pass
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")



#: 当前模块注册的 draw handler。
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

#: 重建时允许恢复的最大帧数，避免编辑触发无界快进。
_REBUILD_CATCHUP_MAX = 600


def _rebuild_if_dirty(scene):
    """以新参数重建脏 track，并在可控范围内恢复原播放帧。"""
    if not _P["dirty"]:
        return
    _P["dirty"] = False
    _P["needs_items"] = True
    _clear_tex_cache()
    _clear_material_cache()
    _clear_flow_cache()
    alive = []
    for tr in _P["tracks"]:
        if rebuild_track(tr, scene, keep_frame=True):
            alive.append(tr)
    _P["tracks"] = alive
    _P["duration"] = _resolve_duration(scene)
    _P["acc"] = 0.0


def _resolve_duration(scene, sim=None):
    """解析单次播放时长；自动模式下多 track 取最长建议值。"""
    d = int(getattr(scene, "efx_sim_duration", 240))
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


def _inverse_rows(rows):
    """参考矩阵（三行 3×4）的逆，按一般仿射矩阵求，允许带缩放。"""
    (a, b, c, tx), (d, e, f, ty), (g, h, i, tz) = rows
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        return None
    inv = ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
           (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det)
    return inv, (tx, ty, tz)


def _view_context(tr=None):
    """将 draw handler 缓存的相机换算为该 track 局部游戏坐标下的 ViewContext。"""
    from ..efx_format.sim.state import ViewContext, Vec3

    fwd = _P.get("cam_fwd")
    if not fwd:
        return ViewContext()
    cam = _P.get("cam_pos")
    got = _inverse_rows(tr["ref_rows"]) if tr and tr.get("ref_rows") else None
    if got is None:
        # 没有参考矩阵：世界方向直接转为游戏方向，不应用单位缩放
        return ViewContext(cam_forward=Vec3(fwd[0], fwd[2], -fwd[1]))
    m, t = got

    def _local(v, point):
        if point:
            v = (v[0] - t[0], v[1] - t[1], v[2] - t[2])
        return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
                m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
                m[6] * v[0] + m[7] * v[1] + m[8] * v[2])

    lf = _local(fwd, False)
    view = ViewContext(cam_forward=Vec3(lf[0], lf[2], -lf[1]))
    if cam:
        view.cam_pos = Vec3(*_to_game(*_local(cam, True)))
    return view


def _build_items(tr):
    try:
        tr["items"] = tr["sim"].build_render(_view_context(tr))
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
    """以共享的墙钟累加器推进整数模拟帧。"""
    _rebuild_if_dirty(scene)
    if not _P["tracks"]:
        return
    _sync_host_origin(scene)

    now = time.perf_counter()
    dt = now - _P["last_t"]
    _P["last_t"] = now
    if dt <= 0.0 or dt > 0.5:
        dt = min(max(dt, 0.0), 1.0 / 30.0)   # 避免恢复后单次补帧过多。

    cfg = _P["tracks"][0]["sim"].config
    fps = float(getattr(cfg, "fps", 60))
    speed = float(getattr(scene, "efx_sim_speed", 1.0))
    _P["acc"] += dt * fps * speed

    steps = 0
    while _P["acc"] >= 1.0 and steps < 240:   # 单 tick 步数上限。
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

    # 仅在模拟或参数状态变化后重建渲染项。
    if steps or _P["needs_items"]:
        # 抽帧只降低显示更新频率，不改变模拟步进；参数变化和暂停时立即更新。
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
        # 选中根集合时无需活动 Entry。
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
        # tick 间隔固定，倍速由累加器处理。
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
                # 暂停时仅重建显示，不能通过 tick 推进模拟。
                _rebuild_if_dirty(context.scene)
                _rebuild_items()
                _redraw_viewports()
                _P["last_t"] = time.perf_counter()
            elif _P["needs_items"]:
                # 暂停时视角变化：只重建渲染项
                _rebuild_items()
                _redraw_viewports()
        return {"PASS_THROUGH"}       # 保留视图和编辑交互。

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
        # modal 会在下一个 tick 完成剩余清理。
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
        # 暂停时恢复 GC，继续播放时再暂存其状态。
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
        # 重放从第 0 帧重建，不恢复原播放位置。
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
    """为面板读取 UVSEQUENCE 信息，不构建模拟资源。"""
    if entry_obj is None:
        return None
    try:
        return _uvs_info(_uvs_host(entry_obj, use_cache=True))
    except Exception:
        return None


def _uvs_cell_readout():
    """返回首个序列帧渲染项的当前格读数，供面板显示。"""
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
    # 根实例不计入子实例数。
    children = sum(max(0, getattr(tr["sim"], "instance_count", 1) - 1) for tr in trs)
    return (frame, alive, spawned, len(trs), children)

class EFX_PT_sim(Panel):
    """粒子模拟播放器面板。"""

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

        # 仅根集合播放时显示范围选择器。
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
                # 多 track 时显示当前播放对象。
                col.label(text=T("sim.playing_n").format(n_tracks), icon="SEQUENCE")
                sub = col.column(align=True)
                sub.scale_y = 0.7
                for tr in trs[:4]:
                    sub.label(text="· " + tr["entry_name"])
                if len(trs) > 4:
                    sub.label(text=T("sim.and_more").format(len(trs) - 4))
            if _P["error"]:
                col.label(text=_P["error"], icon="ERROR")

        # ── 未绑定网格诊断 ───────────────────────────────────────────────────
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

        # ── 未支持属性诊断 ───────────────────────────────────────────────────
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
    """模拟播放器的可折叠子面板基类。"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_parent_id = "EFX_PT_sim"

    @classmethod
    def poll(cls, context):
        # 与父面板的可见条件保持一致。
        return (is_active() or _resolve_entry(context.active_object) is not None
                or _active_root_collection(context) is not None)


class EFX_PT_sim_playback(_SimSubPanel):
    """播放和挥砍预览设置。"""

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

        # 挥砍预览为条带提供宿主轨迹。
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
    """显示、性能和序列帧读数设置。"""

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
        # 独立叠加层可在不播放时显示选中项。
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

        # ── 序列帧读数 ──────────────────────────────────────────────────────
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
            # 已载入 UVS 但没有绑定贴图时显示诊断。
            col.label(text=T("sim.uvs_noimage"), icon="INFO")
        if not uvs["loaded"]:
            box.prop(scene, "efx_sim_uvs_grid")


class EFX_PT_sim_unknowns(Panel):
    """模拟器行为的校准开关。"""

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
        # 已有稳定默认值的开关不在校准面板重复显示。
        col.prop(scene, "efx_sim_spawn_jitter")
        col.prop(scene, "efx_sim_material_slot")
        col.prop(scene, "efx_sim_refraction_gain")
        col.prop(scene, "efx_sim_flowmap_gain")
        col.prop(scene, "efx_sim_blink_phase")
        col.prop(scene, "efx_sim_fade_depth_metric")
        col.prop(scene, "efx_sim_fade_cone_mode")
        col.prop(scene, "efx_sim_draw_order")
        col.prop(scene, "efx_sim_mesh_rot_space")
        col.prop(scene, "efx_sim_hdr_mode")
        col.prop(scene, "efx_sim_a0_sample")
        col.prop(scene, "efx_sim_timl_interp")
        col.prop(scene, "efx_sim_rot_order")
        col.prop(scene, "efx_sim_age_during_delay")
        # 仅保留仍需校准的 HOMING 选项。
        col.prop(scene, "efx_sim_homing_lateral_tilt")
        col.prop(scene, "efx_sim_parent_clock")
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
    """标记播放状态为脏，以便下一个 tick 重建。"""
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
        name="Duration", default=240, min=0, soft_max=600,
        description="Frames per cycle; 0 = auto (start delay + one burst cycle + one particle life). "
                    "EFX emitters have no documented stop condition, so this is the player's call")
    S.efx_sim_seed = IntProperty(
        name="Seed", default=0, update=_on_knob_changed,
        description="Base random seed; same seed replays identically")

    # ── 挥砍预览 ────────────────────────────────────────────────────────────
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
        items=[("AUTO", "From file", "Use each entry's own blend mode "
                                     "(Shader Settings)"),
               ("ADDITIVE", "Force additive", "Override everything to additive"),
               ("ALPHA", "Force alpha", "Override everything to plain alpha")],
        default="AUTO")
    S.efx_sim_particle_size = FloatProperty(
        name="Size x", default=1.0, min=0.01, max=20.0, soft_min=0.25, soft_max=4.0,
        description="Magnifier on top of the size read from the file "
                    "(BILLBOARD3D width/height x scale, in game units). 1.0 = as authored")
    S.efx_sim_point_px = IntProperty(name="Point px", default=4, min=1, max=32)

    # ── 预览性能 ────────────────────────────────────────────────────────────
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
        name="Emitter shape", default=True,
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

    # ── 校准 ────────────────────────────────────────────────────────────────
    # 新属性名避免旧场景保存的废弃值覆盖当前默认行为。
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
    S.efx_sim_blink_phase = EnumProperty(
        name="Blink start", update=_on_knob_changed,
        items=[("zero", "From birth",
                "Every particle starts its blink cycle when it is born"),
               ("random", "Random",
                "Every particle starts at a random point in its blink cycle")],
        default="zero")
    S.efx_sim_fade_depth_metric = EnumProperty(
        name="Depth fade distance", update=_on_knob_changed,
        items=[("view_depth", "Along view",
                "Measure how far a particle is along the viewing direction"),
               ("distance", "Straight line",
                "Measure the straight-line distance from the camera to a particle")],
        default="view_depth")
    S.efx_sim_fade_cone_mode = EnumProperty(
        name="Angle fade cone", update=_on_knob_changed,
        items=[("outer", "Outer angle",
                "Fade Cone Angle is the angle where the fade ends"),
               ("width", "Fade width",
                "Fade Cone Angle is how wide the fade is, counted from Cutoff Cone Angle")],
        default="outer")
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
    S.efx_sim_homing_ff_recover = FloatProperty(
        name="Homing field recovery", default=48.0, min=4.0, max=600.0,
        description="How many frames it takes a homing particle to pull its speed "
                    "back up to its full speed after a force field has slowed it. "
                    "Only used by the damped force field. Preview only")
    S.efx_sim_homing_lateral_tilt = FloatProperty(
        name="Homing lateral tilt", default=0.0, min=0.0, max=2.0,
        description="How far the sideways force that bends a homing particle into "
                    "its orbit tilts out of horizontal as the particle comes in "
                    "closer to straight up or down. 0 = always horizontal, which "
                    "squashes the swarm into a flat disc at full spread; higher "
                    "values keep more height. The swarm stays centred on its "
                    "target at any setting. Preview only")
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
    S.efx_sim_spawn_jitter = EnumProperty(
        name="Burst interval jitter", update=_on_knob_changed,
        items=[("per_burst", "Per burst",
                "Re-roll SPAWN's burst interval for every burst, so the spacing "
                "between particles varies"),
               ("per_cycle", "Per cycle",
                "Roll it once per cycle, so a whole cycle is evenly spaced")],
        default="per_burst")
    S.efx_sim_a0_sample = EnumProperty(
        name="TIML A0", update=_on_knob_changed,
        items=[("spawn", "Frozen at spawn", "Particle-level fields read A0 at their birth frame"),
               ("current", "Follows emitter time", "Particle-level fields re-read A0 every frame")],
        default="spawn")
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
        description="Whether particleDelayFrame still advances the particle's age")
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
        "efx_sim_mesh_rot",   # 清理旧场景遗留属性。
        "efx_sim_draw_order", "efx_sim_material_slot",
        "efx_sim_alpha_source",
        "efx_sim_luma_alpha",   # 清理旧场景遗留属性。
        "efx_sim_hdr_mode",
        "efx_sim_hdr",   # 清理旧场景遗留属性。
        "efx_sim_ribbon_subdiv_max", "efx_sim_render_every",
        "efx_sim_particle_budget",
        "efx_sim_refraction_tex", "efx_sim_refraction_gain",
        "efx_sim_flowmap_gain", "efx_sim_flowmap_speed_unit", "efx_sim_flowmap_phase",
        "efx_sim_oscillator_freq_unit", "efx_sim_blink_phase",
        "efx_sim_fade_depth_metric", "efx_sim_fade_cone_mode",
        "efx_sim_homing_compose",
        "efx_sim_homing_axial_falloff", "efx_sim_homing_retarget",
        "efx_sim_homing_lateral_tilt", "efx_sim_homing_axis_update",
        "efx_sim_homing_ff_scale",
        "efx_sim_homing_ff_recover", "efx_sim_homing_converge",
        "efx_sim_homing_ramp_turns",
        "efx_sim_fps",   # 清理旧场景遗留属性。
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
