"""
blender_efx/uvc_preview.py  —  UVCONTROL 视口 UV 滚动动画预览

设计（与用户确认的边界）
------------------------
- **绑定责任全交用户**：用户自行导入网格、上好材质（材质里需含一个 Mapping 节点），
  然后在 MESH 属性上手选目标网格对象（`Object.efx_mesh_target`）。本模块不生成几何、
  不创建/修改材质节点结构，只在预览期间写 Mapping 节点的 Location/Scale。
- **UVCONTROL → MESH 关联**：UVCONTROL 与 MESH 是同一 entry（EFX_ENTRY）下的兄弟 EFX_ATTRIBUTE。
  预览时对每个 UVCONTROL 属性，在同 entry 找 MESH 兄弟属性，读其绑定网格。
- **根级单会话，全播**：进入预览=收集本 EFX_ROOT 下所有 (UVCONTROL↔已绑定网格) 配对，
  全部一起驱动；共享时间轴 → 天然同步。一个场景同时只有一个会话。
- **进入/退出状态**（类似 UVS 编辑器）：进入时快照各 Mapping 节点原值并注册
  frame_change_post handler；退出时注销 handler 并还原所有原值。非侵入。

约束（CLAUDE.md）
-----------------
- 纯胶水层，绝不 import efx_format 解析以外的东西；不碰 byte-perfect 底线。
- Python 3.10 兼容；bpy 只用长期稳定子集（app.handlers.frame_change_post 自 2.8 稳定）。
"""

import math
from math import radians

import bpy
from mathutils import Matrix, Euler, Vector
from bpy.props import PointerProperty, BoolProperty
from bpy.types import Operator, Panel
from bpy.app.handlers import persistent

from .i18n import T  # 运行时双语查表（draw / report 文案）
from . import transform_sync as _tsync
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 属性类型判定
# ─────────────────────────────────────────────────────────────────────────────

def _attribute_type_hash(obj):
    """返回 EFX_ATTRIBUTE 对象的 type_hash（int）；非属性或异常返回 None。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return None
    try:
        return int(obj.efx_block.type_hash_str)
    except Exception:
        return None


def _is_uvcontrol_attribute(obj) -> bool:
    from ..efx_format.hashes import UVCONTROL
    return _attribute_type_hash(obj) == UVCONTROL


def _is_mesh_attribute(obj) -> bool:
    from ..efx_format.hashes import MESH
    return _attribute_type_hash(obj) == MESH


# ─────────────────────────────────────────────────────────────────────────────
# 字段值读取（按 data_type 取对应值槽）
# ─────────────────────────────────────────────────────────────────────────────

def _read_field(obj, name):
    """从 EFX_ATTRIBUTE 的 field_items 读取指定字段，返回 python 值（标量或 tuple）。

    覆盖 UVCONTROL 用到的类型：FLOAT / INT / FLOAT2/3/4，以及 *_STR 字符串数组兜底。
    找不到字段返回 None。
    """
    bp = getattr(obj, "efx_block", None)
    if bp is None:
        return None
    for it in bp.field_items:
        if it.ori_name != name:
            continue
        dt = it.data_type
        if dt == "FLOAT":
            return float(it.float_value)
        if dt in ("INT", "UINT", "BYTE1", "SHORT1"):
            return int(it.int_value)
        if dt == "FLOAT2":
            return tuple(it.float2_value)
        if dt == "FLOAT3":
            return tuple(it.float3_value)
        if dt == "FLOAT4":
            return tuple(it.float4_value)
        if dt == "FLOAT6":
            return tuple(it.float6_value)
        if dt.endswith("_STR") or dt == "ARRAY_STR":
            try:
                return tuple(float(x) for x in it.string_value.split(","))
            except Exception:
                return None
        return None
    return None


def _comp(val, idx, default=0.0):
    """从 tuple/标量里取第 idx 个分量；越界或 None 返回 default。"""
    if val is None:
        return default
    if isinstance(val, (tuple, list)):
        return float(val[idx]) if idx < len(val) else default
    return float(val) if idx == 0 else default


# ─────────────────────────────────────────────────────────────────────────────
# 运动学：UVCONTROL 参数 → 时刻 t 的 UV 偏移 / 缩放
# ─────────────────────────────────────────────────────────────────────────────

def _advance(init, speed, accel, t):
    """位置随时间演化。

    annotations 确认 acceleration = "每秒对速度做乘法"（速度按 accel 的指数增长）。
    - accel≈1（无加速）：pos = init + speed·t（线性滚动，最常见）。
    - accel>0 且 ≠1：speed(τ)=speed·accel^τ，位移 = ∫₀ᵗ = speed·(accel^t−1)/ln(accel)。
    - accel≤0（异常/无意义）：退回线性。
    """
    if accel is None or accel <= 0.0 or abs(accel - 1.0) < 1e-6:
        return init + speed * t
    try:
        return init + speed * (accel ** t - 1.0) / math.log(accel)
    except (OverflowError, ValueError):
        return init + speed * t


def _compute_channel(ch, t):
    """单通道 → ((loc_u, loc_v), (scale_u, scale_v))。

    ⚠ UVCONTROL 的 ('f',4) 字段布局是 [U值, ?, V值, ?]——U 在 index 0、V 在 **index 2**
    （index 1/3 实测恒为 0，疑似 jitter/保留）。实证：uv1_scale=(4,0,4,0)=U/V 各 4 倍，
    uv1_initialPosition=(0,0,0.6,0)=V 偏移 0.6。早期误读 index 1 致 V 方向塌缩成条纹。
    """
    init = ch["init"]
    speed = ch["speed"]
    accel = ch["accel"]
    scale = ch["scale"]
    scale_speed = ch["scale_speed"]

    loc_u = _advance(_comp(init, 0), _comp(speed, 0), _comp(accel, 0, 1.0), t)
    loc_v = _advance(_comp(init, 2), _comp(speed, 2), _comp(accel, 2, 1.0), t)
    s_u = _comp(scale, 0, 1.0) + _comp(scale_speed, 0) * t
    s_v = _comp(scale, 2, 1.0) + _comp(scale_speed, 2) * t
    return (loc_u, loc_v), (s_u, s_v)


def _compute_uv(params, t):
    """多通道叠加 → ((loc_u, loc_v), (scale_u, scale_v))。

    两套 UV 共用同一套贴图（布局一致），同时启用时效果叠加：偏移相加、缩放相乘
    （滚动以偏移为主，scale≈1 时偏移叠加即精确）。
    """
    loc_u = loc_v = 0.0
    s_u = s_v = 1.0
    for ch in params["channels"]:
        (lu, lv), (su, sv) = _compute_channel(ch, t)
        loc_u += lu
        loc_v += lv
        s_u *= su
        s_v *= sv
    return (loc_u, loc_v), (s_u, s_v)


def _channel_enabled(uvc_obj, prefix) -> bool:
    """该通道(uv1/uv2)是否启用：unkn0==1（实测的逐通道启用开关）。"""
    v = _read_field(uvc_obj, prefix + "_unkn0")
    return int(v) == 1 if v is not None else False


def _read_channel(uvc_obj, prefix):
    """读取单通道运动学参数 dict。"""
    return {
        "init":        _read_field(uvc_obj, prefix + "_initialPosition"),
        "speed":       _read_field(uvc_obj, prefix + "_speed"),
        "accel":       _read_field(uvc_obj, prefix + "_acceleration"),
        "scale":       _read_field(uvc_obj, prefix + "_scale"),
        "scale_speed": _read_field(uvc_obj, prefix + "_scaleSpeed"),
    }


def _extract_params(uvc_obj):
    """抽取启用的通道并叠加；决定 Mapping 的 UV 源。

    逐通道启用开关 = <prefix>_unkn0==1。两套 UV 共用同一批贴图、布局一致：
      - uv1、uv2 都启用 → 两者叠加（同用第一套 UV 即可，布局一致）。
      - 仅 uv2 启用 → 用 uv2 + 第二套 UV。
      - 仅 uv1 / 都不启用 → 用 uv1 + 第一套 UV（都不启用时为静态 base）。
    """
    uv1_on = _channel_enabled(uvc_obj, "uv1")
    uv2_on = _channel_enabled(uvc_obj, "uv2")

    channels = []
    if uv1_on:
        channels.append(_read_channel(uvc_obj, "uv1"))
    if uv2_on:
        channels.append(_read_channel(uvc_obj, "uv2"))
    if not channels:
        channels.append(_read_channel(uvc_obj, "uv1"))  # 都不启用 → uv1 静态

    # UV 源：仅 uv2 启用时取第二套 UV；否则（含两者叠加）取第一套
    use_second = uv2_on and not uv1_on
    return {"channels": channels, "use_second_uv": use_second}


# ─────────────────────────────────────────────────────────────────────────────
# 材质 Mapping 节点：定位已有 / 自动插入（B 方案）
# ─────────────────────────────────────────────────────────────────────────────

def _active_node_tree(mesh_obj):
    """返回网格活动材质的节点树（需启用节点）；否则 None。"""
    if mesh_obj is None:
        return None
    mat = mesh_obj.active_material
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    return mat.node_tree


def _find_existing_mapping(tree):
    """节点树里找第一个 Mapping 节点；找不到返回 None。"""
    if tree is None:
        return None
    for node in tree.nodes:
        if node.type == "MAPPING":
            return node
    return None


def _image_texture_targets(tree):
    """返回 Vector 输入口未连线的图像纹理节点列表（这些用默认 UV，可被驱动）。"""
    targets = []
    for node in tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        vec_in = node.inputs.get("Vector")
        if vec_in is not None and not vec_in.is_linked:
            targets.append(node)
    return targets


def _material_previewable(mesh_obj):
    """判断绑定网格能否预览，返回 (ok: bool, reason: str)。"""
    tree = _active_node_tree(mesh_obj)
    if tree is None:
        return False, "uvc.reason_no_node_mat"
    if _find_existing_mapping(tree) is not None:
        return True, "uvc.reason_has_mapping"
    if _image_texture_targets(tree):
        return True, "uvc.reason_auto_mapping"
    return False, "uvc.reason_no_texture"


def _force_blended(mat):
    """把材质渲染方式临时切到 Blended（真 alpha 混合），返回 (attr, orig) 供还原。

    Dithered/Hashed 透明靠 TAA 累积，时间轴一动采样重置成 1 → 半透明区变稀疏噪点近乎不可见。
    Blended 不依赖采样累积，运动时稳定。版本守卫：
      - 4.2+ EEVEE Next：material.surface_render_method ∈ {'DITHERED','BLENDED'}
      - <4.2 旧 EEVEE：material.blend_method ∈ {'OPAQUE','CLIP','HASHED','BLEND'}
    返回 None 表示无可切属性（不报错）。
    """
    if mat is None:
        return None
    if hasattr(mat, "surface_render_method"):
        orig = mat.surface_render_method
        if orig != "BLENDED":
            try:
                mat.surface_render_method = "BLENDED"
                return ("surface_render_method", orig)
            except Exception:
                return None
        return None
    if hasattr(mat, "blend_method"):
        orig = mat.blend_method
        if orig != "BLEND":
            try:
                mat.blend_method = "BLEND"
                return ("blend_method", orig)
            except Exception:
                return None
        return None
    return None


def _uv_layer_name(mesh_obj, use_second):
    """返回网格第一/第二套 UV 层名；不足时回退到现有的；无 UV 返回 ""。"""
    try:
        layers = mesh_obj.data.uv_layers
    except Exception:
        return ""
    if not layers:
        return ""
    idx = 1 if use_second else 0
    if idx < len(layers):
        return layers[idx].name
    return layers[0].name  # 没有第二套时回退第一套


def _prepare_material(mat, mesh_obj, use_second_uv):
    """为材质准备可驱动的 Mapping 节点 + 临时切 Blended 渲染方式。

    - 已有 Mapping → 复用（mode='existing'，退出时只还原其 Location/Scale 数值）。
    - 无 Mapping → 新建 UV Map(指定 UV 层) + Mapping，接到所有 Vector 口空着的图像纹理
      （mode='created'，退出时删除新建节点、连接随节点移除自动断开还原）。
      use_second_uv=True 时 UV Map 指向网格第二套 UV，实现 uv2 通道预览。

    返回 (mapping_node, restore_record) 或 (None, None)（无可驱动目标）。
    """
    tree = mat.node_tree
    # 渲染方式临时切 Blended（快照原值供还原）。
    render_method = _force_blended(mat)

    # UV 滚动前提是贴图回绕：对材质里**所有**图像纹理强制 Extension=REPEAT（快照原值，
    # 退出还原）。非 Repeat（Clip/Extend）会让偏移超出 [0,1] 后采样到透明/边缘 →
    # 网格随时间淡出消失。无论复用已有 Mapping 还是新建，都要覆盖（含已连线的纹理）。
    tex_ext = []
    for node in tree.nodes:
        if node.type == "TEX_IMAGE":
            try:
                tex_ext.append((node, node.extension))
                node.extension = "REPEAT"
            except Exception:
                pass

    def _abort_restore():
        for tex, orig in tex_ext:
            try:
                tex.extension = orig
            except Exception:
                pass
        if render_method is not None:
            try:
                setattr(mat, render_method[0], render_method[1])
            except Exception:
                pass

    existing = _find_existing_mapping(tree)
    if existing is not None:
        rec = {
            "mode": "existing",
            "mat": mat,
            "render_method": render_method,
            "node": existing,
            "loc": tuple(existing.inputs["Location"].default_value),
            "scale": tuple(existing.inputs["Scale"].default_value),
            "tex_ext": tex_ext,
        }
        return existing, rec

    targets = _image_texture_targets(tree)
    if not targets:
        # 没有可接的图像纹理 → 还原刚才改的 extension/渲染方式，放弃
        _abort_restore()
        return None, None

    # UV 源：用 UV Map 节点显式指定 UV 层（uv1=第一套 / uv2=第二套），
    # 而非 TexCoord（只能取活动套），这样 uv2 能正确驱动第二套 UV。
    uvmap = tree.nodes.new("ShaderNodeUVMap")
    uvmap.uv_map = _uv_layer_name(mesh_obj, use_second_uv)
    mapping = tree.nodes.new("ShaderNodeMapping")
    base = targets[0].location
    mapping.location = (base[0] - 350, base[1])
    uvmap.location = (base[0] - 650, base[1])

    tree.links.new(uvmap.outputs["UV"], mapping.inputs["Vector"])
    for tex in targets:
        tree.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

    rec = {
        "mode": "created",
        "mat": mat,
        "render_method": render_method,
        "tree": tree,
        "nodes": [mapping, uvmap],
        "tex_ext": tex_ext,
    }
    return mapping, rec


def _find_sibling_mesh_target(uvc_obj):
    """在 UVCONTROL 同 entry 的兄弟属性里找 MESH 属性，返回其绑定网格对象（或 None）。"""
    body = uvc_obj.parent
    if body is None:
        return None
    for sib in body.children:
        if _is_mesh_attribute(sib):
            tgt = getattr(sib, "efx_mesh_target", None)
            if tgt is not None:
                return tgt
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 网格变换动画：TRANSFORM3D（base + 速度/加速度）+ ROTATEANIM（自转）→ mesh matrix_world
# ─────────────────────────────────────────────────────────────────────────────

# ROTATEANIM spin_velocity 量纲不是度/秒（实测偏慢）；疑为度/帧（×游戏 tick 60fps=度/秒）→ 试 60×。
_ROTATEANIM_SPIN_SCALE = 60.0


def _entry_attribute(entry_obj, type_hash):
    """entry 下第一个指定 type_hash 的 EFX_ATTRIBUTE；无则 None。"""
    for blk in entry_obj.children:
        if blk.get("~TYPE") == "EFX_ATTRIBUTE" and _attribute_type_hash(blk) == type_hash:
            return blk
    return None


def _entry_mesh_target(entry_obj):
    """entry 下 MESH 属性绑定的网格对象（或 None）。"""
    for blk in entry_obj.children:
        if _is_mesh_attribute(blk):
            tgt = getattr(blk, "efx_mesh_target", None)
            if tgt is not None:
                return tgt
    return None


def _read_triple(block, name, default=(0.0, 0.0, 0.0)):
    """读 XYZ type 0（FLOAT6）字段的基础三元组（idx 0/2/4）；缺失返回 default。"""
    v = _read_field(block, name)
    if isinstance(v, (tuple, list)):
        if len(v) >= 6:
            return (float(v[0]), float(v[2]), float(v[4]))
        if len(v) >= 3:
            return (float(v[0]), float(v[1]), float(v[2]))
    return default


def _collect_transform_entries(roots, armature):
    """收集需要做变换动画的 entry：每个有绑定网格、且含 TRANSFORM3D 或 ROTATEANIM 的 entry。

    返回 (entries, snaps)：
      entries = [dict(mesh, bone_base, base_*, *_vel, spin_*)]
      snaps   = [(mesh, 原 matrix_world)]   —— 退出还原
    无 TRANSFORM3D 也无 ROTATEANIM → 跳过（mesh 不动，等价"原点局部系、不重建"）。
    同一网格只收一次（去重）。
    """
    from ..efx_format.hashes import TRANSFORM3D, ROTATEANIM
    entries = []
    snaps = []
    seen = set()
    for root in roots:
        if root is None:
            continue
        for body in _rc.collect_top_level(root, "EFX_ENTRY"):
            mesh = _entry_mesh_target(body)
            if mesh is None or mesh.name in seen:
                continue
            t3d = _entry_attribute(body, TRANSFORM3D)
            rot = _entry_attribute(body, ROTATEANIM)
            if t3d is None and rot is None:
                continue  # 无可定位/动画来源 → fallback 原点，不动网格

            # 只取骨骼世界位置（head），不继承骨骼 rest 朝向：
            # Blender 骨骼默认沿 +Y，指向 +Z 的 MhBone 其 matrix_local 内嵌 +90°X 伪旋转，
            # 整体继承会把网格莫名转 +90°X。朝向统一交给 M_G2B 轴交换。
            bone_base = _tsync.bone_base_matrix(armature, _tsync._entry_bone_lim(body))
            bone_pos = bone_base.to_translation() if bone_base is not None else None

            ent = {"mesh": mesh, "bone_pos": bone_pos}
            if t3d is not None:
                ent["base_translate"] = _read_triple(t3d, "translate")
                ent["base_rotate"] = _read_triple(t3d, "rotate")
                ent["base_scale"] = _read_triple(t3d, "resize", (1.0, 1.0, 1.0))
                # 速度总开关：enableVelocityBitflag bit0(&1) 置位才启用速度（base 定位不受影响）。
                # 参考 EFX_*.bt：Pos0=Enable Velocity, Pos1=Enable Acceleration。
                flag = _read_field(t3d, "enableVelocityBitflag")
                vel_on = bool(int(flag) & 1) if flag is not None else False
                if vel_on:
                    ent["trans_vel"] = _read_triple(t3d, "translation_velocity")
                    ent["rot_vel"] = _read_triple(t3d, "rotation_velocity")
                    ent["scale_vel"] = _read_triple(t3d, "scale_velocity")
                else:
                    ent["trans_vel"] = (0.0, 0.0, 0.0)
                    ent["rot_vel"] = (0.0, 0.0, 0.0)
                    ent["scale_vel"] = (0.0, 0.0, 0.0)
            else:
                ent["base_translate"] = (0.0, 0.0, 0.0)
                ent["base_rotate"] = (0.0, 0.0, 0.0)
                ent["base_scale"] = (1.0, 1.0, 1.0)
                ent["trans_vel"] = (0.0, 0.0, 0.0)
                ent["rot_vel"] = (0.0, 0.0, 0.0)
                ent["scale_vel"] = (0.0, 0.0, 0.0)
            if rot is not None:
                ent["spin_vel"] = _read_triple(rot, "spin_velocity")
            else:
                ent["spin_vel"] = (0.0, 0.0, 0.0)

            entries.append(ent)
            snaps.append((mesh, mesh.matrix_world.copy()))
            seen.add(mesh.name)
    return entries, snaps


def _transform_matrix(ent, t):
    """按时刻 t 计算网格的 matrix_world。

    base 三元组随时间线性演化：value(t) = base + velocity·t。
    ROTATEANIM spin 作为附加自转叠在 TRANSFORM3D 旋转之后（mesh 局部空间）。
    坐标约定与 transform_sync 一致：有骨骼基准用游戏坐标原样，无骨骼用 M_G2B 轴交换。
    """
    bt, tv = ent["base_translate"], ent["trans_vel"]
    br, rv = ent["base_rotate"], ent["rot_vel"]
    bs, sv = ent["base_scale"], ent["scale_vel"]
    sp = ent["spin_vel"]

    tr = tuple(bt[i] + tv[i] * t for i in range(3))
    ro = tuple(br[i] + rv[i] * t for i in range(3))
    sc = tuple(bs[i] + sv[i] * t for i in range(3))
    spin = tuple(sp[i] * _ROTATEANIM_SPIN_SCALE * t for i in range(3))

    # 朝向统一用 M_G2B 轴交换（不依赖骨骼 rest 朝向，避免 +Z 骨骼的 +90°X 伪旋转）。
    loc = Vector(_tsync.game_loc_to_blender(*tr))
    rot_m = Euler(_tsync.game_rot_to_blender(*ro), "XYZ").to_matrix().to_4x4()
    spin_m = Euler(_tsync.game_rot_to_blender(*spin), "XYZ").to_matrix().to_4x4()
    sx, sy, sz = _tsync.game_scale_to_blender(*sc)

    scl_m = Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))
    local = Matrix.Translation(loc) @ rot_m @ spin_m @ scl_m
    # 绑骨骼时只把骨骼世界位置作为平移基准叠加（不继承骨骼朝向）
    if ent["bone_pos"] is not None:
        return Matrix.Translation(ent["bone_pos"]) @ local
    return local


# ─────────────────────────────────────────────────────────────────────────────
# 预览会话状态（模块级，生命周期与 handler 绑定）
# ─────────────────────────────────────────────────────────────────────────────

# ⚠ uvc 是 handler+还原数据模型（持活节点引用），非实例对象——session_core 的对象标记模型不适用。
# 但同样怕状态脱节：热重载/undo 后 _state 是新模块的空 dict，却有**旧模块的 _on_frame** 还挂在
# frame_change_post 上驱动真实节点（"越用越黏"）。故 handler 一律**按函数名+模块识别**移除（不靠
# 缓存引用），"是否活跃"也由 handler 是否在册派生——跨热重载都能认出并清掉旧 handler。
_state = {
    "handler": None,       # frame_change_post handler 引用（仅本模块内用；清理不靠它）
    "pairs": [],           # [(params_dict, mapping_node)]  —— UV 驱动
    "restore": [],         # [restore_record]（见 _prepare_material）
    "xform": [],           # [entry]  —— 网格变换动画（见 _collect_transform_entries）
    "xform_snaps": [],     # [(mesh, 原 matrix_world)]
    "start_frame": 0,
}


def _our_frame_handlers():
    """frame_change_post 里所有属于本模块的 _on_frame（按名+模块识别，跨热重载有效）。"""
    out = []
    for h in list(bpy.app.handlers.frame_change_post):
        if (getattr(h, "__name__", None) == "_on_frame"
                and getattr(h, "__module__", "").endswith("uvc_preview")):
            out.append(h)
    return out


def _remove_our_frame_handlers():
    """移除所有本模块 handler（含热重载残留的旧模块 handler）。返回移除数。"""
    removed = 0
    for h in _our_frame_handlers():
        try:
            bpy.app.handlers.frame_change_post.remove(h); removed += 1
        except Exception:
            pass
    return removed


def _is_active() -> bool:
    """预览是否活跃：本模块 handler 是否在册（场景事实派生，非 _state 布尔）。"""
    return bool(_our_frame_handlers())


def _scene_fps(scene):
    fps = scene.render.fps
    base = getattr(scene.render, "fps_base", 1.0) or 1.0
    return float(fps) / float(base)


def _apply_frame(scene):
    """按当前帧把所有配对的 UV 写进各自 Mapping 节点。"""
    fps = _scene_fps(scene)
    t = (scene.frame_current - _state["start_frame"]) / fps if fps > 0 else 0.0
    if t < 0:
        t = 0.0
    touched = set()
    for params, node in _state["pairs"]:
        try:
            (lu, lv), (su, sv) = _compute_uv(params, t)
            loc = node.inputs["Location"]
            scl = node.inputs["Scale"]
            loc.default_value[0] = lu
            loc.default_value[1] = lv
            scl.default_value[0] = su
            scl.default_value[1] = sv
            touched.add(node.id_data)  # 节点所属的 NodeTree（材质）
        except Exception:
            # 单个节点出错不影响其余配对的预览
            continue

    # 网格变换动画：TRANSFORM3D（base+速度）+ ROTATEANIM（自转）→ mesh.matrix_world
    for ent in _state["xform"]:
        try:
            ent["mesh"].matrix_world = _transform_matrix(ent, t)
        except Exception:
            continue

    # ⚠ 从 handler 改 default_value，EEVEE 视口不会自动重绘 → 看似淡出/消失，
    # 拖边框（强制重绘）才正常。手动给材质打更新标记 + 标记所有 3D 视口重绘。
    for nt in touched:
        try:
            nt.update_tag()
        except Exception:
            pass
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


@persistent
def _on_frame(scene, depsgraph=None):
    # handler 在册即活跃；有 pairs/xform 才有活可干（热重载残留的旧 handler 其 _state 为空 → 空转无害）
    if _state["pairs"] or _state["xform"]:
        _apply_frame(scene)


def _collect_pairs(roots):
    """收集多个 EFX_ROOT 下所有 (UVCONTROL params, Mapping 节点) 配对，按需自动插入节点。

    roots：EFX_ROOT 对象列表（单 EFX 传 [root]，多 EFX 传全部）。
    返回 (pairs, restore, missing)：
      pairs   = [(params, mapping_node)]
      restore = [restore_record]   —— 退出时据此删节点/还原数值
      missing = [(网格名, 原因)]   —— 已绑定但材质无法预览
    同一材质只准备一次（按 material dedupe，跨 root 也共享，避免重复插 Mapping）。
    """
    pairs = []
    restore = []
    missing = []
    prepared = {}  # material → mapping_node（去重，跨 root 共享）
    for root_obj in roots:
        if root_obj is None:
            continue
        for body in _rc.collect_top_level(root_obj, "EFX_ENTRY"):
            for blk in body.children:
                if not _is_uvcontrol_attribute(blk):
                    continue
                mesh_obj = _find_sibling_mesh_target(blk)
                if mesh_obj is None:
                    continue  # 同 entry 没有绑定网格的 MESH 属性 → 跳过
                tree = _active_node_tree(mesh_obj)
                if tree is None:
                    missing.append((mesh_obj.name, "uvc.reason_no_node_mat"))
                    continue
                params = _extract_params(blk)
                mat = mesh_obj.active_material
                if mat in prepared:
                    mapping = prepared[mat]
                else:
                    mapping, rec = _prepare_material(
                        mat, mesh_obj, params["use_second_uv"]
                    )
                    if mapping is None:
                        missing.append((mesh_obj.name, "uvc.reason_no_texture"))
                        continue
                    prepared[mat] = mapping
                    restore.append(rec)
                pairs.append((params, mapping))
    return pairs, restore, missing


def _all_efx_roots():
    """返回场景里所有 EFX_ROOT 顶层文件集合。"""
    return _rc.all_root_collections()


def _restore():
    """据 restore 记录还原：删除新建节点 / 还原已有节点数值。"""
    for rec in _state["restore"]:
        try:
            # 还原图像纹理 Extension（两种模式通用；created 模式须在删节点前）
            for tex, orig_ext in rec.get("tex_ext", []):
                try:
                    tex.extension = orig_ext
                except Exception:
                    pass
            # 还原渲染方式
            rm = rec.get("render_method")
            if rm is not None:
                try:
                    setattr(rec["mat"], rm[0], rm[1])
                except Exception:
                    pass

            if rec["mode"] == "created":
                tree = rec["tree"]
                for node in rec["nodes"]:
                    try:
                        tree.nodes.remove(node)
                    except Exception:
                        pass
            elif rec["mode"] == "existing":
                node = rec["node"]
                node.inputs["Location"].default_value = rec["loc"]
                node.inputs["Scale"].default_value = rec["scale"]
        except Exception:
            continue

    # 还原网格变换（matrix_world）
    for mesh, mw in _state["xform_snaps"]:
        try:
            mesh.matrix_world = mw
        except Exception:
            continue


def _stop_preview():
    """退出预览：注销 handler（含热重载残留）、还原节点、清空状态。可重复安全调用。"""
    _remove_our_frame_handlers()
    _restore()
    _state["handler"] = None
    _state["pairs"] = []
    _state["restore"] = []
    _state["xform"] = []
    _state["xform_snaps"] = []
    _state["start_frame"] = 0


def _resolve_root(obj):
    """从任意 EFX 对象（属性/entry/…）找所属 EFX_ROOT 顶层文件集合；找不到返回 None。"""
    return _rc.find_root_collection(obj)


def _is_efx_object(obj) -> bool:
    """该对象是否属于某个 EFX 树（属性/entry/root 任意一层）。"""
    return _resolve_root(obj) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Operator：进入 / 退出预览
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvc_preview_enter(Operator):
    """进入 UV 预览（驱动本 EFX 下所有已绑定网格的 UVCONTROL）"""

    bl_idname = "efx.uvc_preview_enter"
    bl_label = "Enter UV Preview (all bound)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if _is_active():
            return False
        if getattr(context.scene, "efx_uvc_preview_all", False):
            return True
        return _is_efx_object(context.active_object)

    def execute(self, context):
        if getattr(context.scene, "efx_uvc_preview_all", False):
            roots = _all_efx_roots()
            if not roots:
                self.report({"ERROR"}, T("uvc.no_efx_scene"))
                return {"CANCELLED"}
        else:
            root = _resolve_root(context.active_object)
            if root is None:
                self.report({"ERROR"}, T("uvc.no_root"))
                return {"CANCELLED"}
            roots = [root]

        pairs, restore, missing = _collect_pairs(roots)

        if missing:
            # 已为部分材质插了节点 → 回滚，避免半残留
            _state["restore"] = restore
            _restore()
            _state["restore"] = []
            detail = "；".join(f"{n}（{T(r)}）" for n, r in missing[:6])
            self.report({"ERROR"}, T("uvc.missing_header").format(detail))
            return {"CANCELLED"}

        # 网格变换动画（TRANSFORM3D + ROTATEANIM），可与 UV 独立存在
        armature = getattr(context.scene, "efx_armature", None)
        xform, xform_snaps = _collect_transform_entries(roots, armature)

        if not pairs and not xform:
            _state["restore"] = restore
            _restore()
            _state["restore"] = []
            self.report({"WARNING"}, T("uvc.no_content"))
            return {"CANCELLED"}

        _state["pairs"] = pairs
        _state["restore"] = restore
        _state["xform"] = xform
        _state["xform_snaps"] = xform_snaps
        _state["start_frame"] = context.scene.frame_current
        _state["handler"] = _on_frame
        _remove_our_frame_handlers()   # 先清任何残留（含热重载旧模块 handler），杜绝重复/黏连
        bpy.app.handlers.frame_change_post.append(_on_frame)

        # 立即按当前帧应用一次（不必等用户拖动时间轴）
        _apply_frame(context.scene)
        self.report({"INFO"}, T("uvc.entered").format(len(pairs), len(xform)))
        return {"FINISHED"}


class EFX_OT_uvc_preview_exit(Operator):
    """退出 UV 预览并还原所有材质 Mapping 节点原值"""

    bl_idname = "efx.uvc_preview_exit"
    bl_label = "Exit UV Preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _is_active()

    def execute(self, context):
        _stop_preview()
        self.report({"INFO"}, T("uvc.exited"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# load_post：换文件/重载时强制清理残留会话（防 handler 悬挂）
# ─────────────────────────────────────────────────────────────────────────────

@persistent
def _on_load(*_args):
    # 新文件里旧的 node 引用全失效，直接清状态（不调用 _restore，节点已不存在）。
    # handler 按名+模块移除（含热重载残留），不靠缓存引用。
    _remove_our_frame_handlers()
    _state["handler"] = None
    _state["pairs"] = []
    _state["restore"] = []
    _state["xform"] = []
    _state["xform_snaps"] = []
    _state["start_frame"] = 0


# ─────────────────────────────────────────────────────────────────────────────
# Panel：MESH 属性 → 网格绑定（顶层 N 面板，仅选中 MESH 属性时显示）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_mesh_binding(Panel):
    """MESH 属性的预览网格绑定（仅选中 MESH 属性时显示）"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Mesh Binding (Preview)"
    bl_order = 0  # 压在 Attribute Properties（默认顺序）之上
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not _is_mesh_attribute(obj):
            return False
        from . import root_collection as _rc
        return not _rc.is_color_editor_mode(obj)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        layout.label(text=T("uvc.bind_target_hint"), icon="MESH_DATA")
        layout.prop(obj, "efx_mesh_target", text="")
        tgt = getattr(obj, "efx_mesh_target", None)
        if tgt is not None:
            ok, reason = _material_previewable(tgt)
            if ok:
                layout.label(text=T("uvc.previewable").format(T(reason)), icon="CHECKMARK")
            else:
                box = layout.box()
                box.label(text=T("uvc.not_previewable").format(T(reason)), icon="ERROR")
                box.label(text=T("uvc.need_texture"))


# ─────────────────────────────────────────────────────────────────────────────
# Panel：UVCONTROL 属性 → 预览控制（顶层 N 面板，仅选中 UVCONTROL 属性时显示）
# ─────────────────────────────────────────────────────────────────────────────

def _draw_preview_controls(layout, context):
    """预览进入/退出控件（UVCONTROL 属性面板与 entry 面板共用）。"""
    layout.label(text=T("uvc.timeline_hint"), icon="TIME")

    if _is_active():
        box = layout.box()
        box.label(text=T("uvc.previewing").format(len(_state["pairs"])), icon="PLAY")
        row = box.row()
        row.scale_y = 1.3
        row.operator("efx.uvc_preview_exit", text=T("uvc.exit"), icon="X")
    else:
        layout.prop(context.scene, "efx_uvc_preview_all", text=T("uvc.all_efx"))
        row = layout.row()
        row.scale_y = 1.3
        row.operator("efx.uvc_preview_enter", text=T("uvc.enter"), icon="PLAY")
        if getattr(context.scene, "efx_uvc_preview_all", False):
            layout.label(text=T("uvc.scope_all"), icon="WORLD")
        else:
            layout.label(text=T("uvc.scope_one"))


class EFX_PT_uvc_preview(Panel):
    """UV Control 预览控制（仅选中 UVCONTROL 属性时显示）"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "UV Control Preview"
    bl_order = 0  # 压在 Attribute Properties 之上
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _is_uvcontrol_attribute(context.active_object)

    def draw(self, context):
        _draw_preview_controls(self.layout, context)


class EFX_PT_uvc_preview_entry(Panel):
    """全局预览（选中 EFX_ENTRY 时显示）—— entry 级入口，默认驱动本 EFX 全部已绑定网格。"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Effect Preview"
    bl_order = 0  # 压在 Entry Properties 之上
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            return False
        from . import root_collection as _rc
        return not _rc.is_color_editor_mode(obj)

    def draw(self, context):
        _draw_preview_controls(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_uvc_preview_enter,
    EFX_OT_uvc_preview_exit,
    EFX_PT_mesh_binding,
    # EFX_PT_uvc_preview / EFX_PT_uvc_preview_entry 已整合进统一「EFX Preview」面板
    # （efx_preview.py），不再单独注册；算子保留供 EFX Preview 编排调用。
]


def _on_mesh_target_update(self, context):
    """绑定网格变更时：把该 MESH 属性的旋转/缩放立即反映到新绑定的对象上。
    self = 挂该属性的对象（应为 MESH 属性）。"""
    try:
        from . import mesh_align
        mesh_align.apply_mesh_rotscale_to_object(self)
    except Exception:
        pass


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # MESH 属性绑定目标：仅网格对象可选；绑定后立即把 MESH 属性旋转/缩放反映到该对象。
    bpy.types.Object.efx_mesh_target = PointerProperty(
        name="Preview Mesh",
        description="UV 预览的目标网格对象（用户自备、需接好基础贴图的材质）",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == "MESH",
        update=_on_mesh_target_update,
    )
    bpy.types.Scene.efx_uvc_preview_all = BoolProperty(
        name="同时播放所有 EFX",
        description="进入预览时驱动场景内所有 EFX 的已绑定网格（不勾选则只驱动当前 EFX）",
        default=False,
    )
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    _stop_preview()
    if _on_load in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "efx_uvc_preview_all"):
        del bpy.types.Scene.efx_uvc_preview_all
    if hasattr(bpy.types.Object, "efx_mesh_target"):
        del bpy.types.Object.efx_mesh_target
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
