"""预览 UVCONTROL 对绑定网格材质 UV 的滚动和缩放。

维护约束：UVCONTROL 与 MESH 从同一 Entry 的属性配对；预览只临时驱动 Mapping
节点和材质状态，退出时必须恢复快照。一个根集合只运行一个共享时间轴会话；本模块
不解析或修改 EFX 字节数据。
"""

from math import radians

import bpy
from mathutils import Matrix, Euler, Vector
from bpy.props import PointerProperty, BoolProperty
from bpy.types import Operator, Panel
from bpy.app.handlers import persistent

from .i18n import T
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
    """从属性 field_items 读取 UVCONTROL 字段，找不到时返回 ``None``。"""
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


# ─────────────────────────────────────────────────────────────────────────────
# 运动学：UVCONTROL 参数 → 时刻 t 的 UV 偏移 / 缩放
# ─────────────────────────────────────────────────────────────────────────────

#: 游戏的逐帧速率。UVCONTROL 的 Coef 按游戏帧作用，与场景帧率无关。
_GAME_FPS = 60.0


def _compute_uv(params, t):
    """叠加启用通道在第 ``t`` 秒的偏移和缩放，公式见 ``sim.behaviors.uvcontrol``。"""
    from ..efx_format.sim.behaviors.uvcontrol import uv_xform
    su, sv, ou, ov = uv_xform(params["channels"], t * _GAME_FPS, _GAME_FPS)
    return (ou, ov), (su, sv)


def _channel_enabled(uvc_obj, prefix) -> bool:
    """判断 uv1/uv2 通道是否启用；两者使用不同字段名。"""
    field = prefix + ("_unknFlag" if prefix == "uv1" else "_enable")
    v = _read_field(uvc_obj, field)
    return int(v) == 1 if v is not None else False


def _extract_params(uvc_obj):
    """返回启用通道和所用 UV 层；仅 uv2 启用时使用第二层 UV。"""
    uv1_on = _channel_enabled(uvc_obj, "uv1")
    uv2_on = _channel_enabled(uvc_obj, "uv2")

    from ..efx_format.sim.behaviors.uvcontrol import channel_names, roll_channels
    # 网格预览没有逐粒子随机，只取 static 分量
    channels = roll_channels(lambda name: _read_field(uvc_obj, name),
                             channel_names(uv1_on, uv2_on))

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
    """临时切换材质到稳定的 Blended 透明模式，返回可还原的属性记录。"""
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
    """准备可驱动 Mapping 节点及完整还原记录。

    复用节点时仅恢复数值；创建节点时退出删除节点。纹理回绕和渲染方式均需还原。
    """
    tree = mat.node_tree
    render_method = _force_blended(mat)

    # UV 滚动要求图像纹理回绕；退出时恢复每个纹理的原设置。
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
        _abort_restore()
        return None, None

    # UV Map 显式选择 UV 层，支持 uv2 使用第二套 UV。
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

# ROTATEANIM 自转速度按游戏 tick 换算。
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
    """收集有绑定网格及变换来源的 Entry，并快照其世界矩阵。"""
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
                continue

            # 骨骼只提供世界位置；朝向统一由游戏到 Blender 轴变换处理。
            bone_base = _tsync.bone_base_matrix(armature, _tsync._entry_joint_no(body))
            bone_pos = bone_base.to_translation() if bone_base is not None else None

            ent = {"mesh": mesh, "bone_pos": bone_pos}
            if t3d is not None:
                ent["base_translate"] = _read_triple(t3d, "translate")
                ent["base_rotate"] = _read_triple(t3d, "rotate")
                ent["base_scale"] = _read_triple(t3d, "resize", (1.0, 1.0, 1.0))
                # bit 0 决定是否应用速度，基础变换始终保留。
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

    # 朝向统一通过游戏到 Blender 的轴变换计算。
    loc = Vector(_tsync.game_loc_to_blender(*tr))
    rot_m = Euler(_tsync.game_rot_to_blender(*ro), "XYZ").to_matrix().to_4x4()
    spin_m = Euler(_tsync.game_rot_to_blender(*spin), "XYZ").to_matrix().to_4x4()
    sx, sy, sz = _tsync.game_scale_to_blender(*sc)

    scl_m = Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))
    local = Matrix.Translation(loc) @ rot_m @ spin_m @ scl_m
    # 绑定骨骼时仅叠加其世界位置。
    if ent["bone_pos"] is not None:
        return Matrix.Translation(ent["bone_pos"]) @ local
    return local


# ─────────────────────────────────────────────────────────────────────────────
# 预览会话状态（模块级，生命周期与 handler 绑定）
# ─────────────────────────────────────────────────────────────────────────────

# 会话持有节点引用，不能使用对象标记模型。handler 必须按名称和模块识别并移除，
# 以清理热重载或 undo 后残留的旧函数。
_state = {
    "handler": None,
    "pairs": [],
    "restore": [],
    "xform": [],
    "xform_snaps": [],
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
            touched.add(node.id_data)
        except Exception:
            continue

    for ent in _state["xform"]:
        try:
            ent["mesh"].matrix_world = _transform_matrix(ent, t)
        except Exception:
            continue

    # handler 改节点值后显式更新材质和 3D 视口。
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
    # 残留 handler 的空状态无需处理。
    if _state["pairs"] or _state["xform"]:
        _apply_frame(scene)


def _collect_pairs(roots):
    """收集根集合内的 UVCONTROL/Mapping 配对及其还原记录。

    同一材质仅准备一次；无法预览的已绑定网格加入 ``missing``。
    """
    pairs = []
    restore = []
    missing = []
    prepared = {}
    for root_obj in roots:
        if root_obj is None:
            continue
        for body in _rc.collect_top_level(root_obj, "EFX_ENTRY"):
            for blk in body.children:
                if not _is_uvcontrol_attribute(blk):
                    continue
                mesh_obj = _find_sibling_mesh_target(blk)
                if mesh_obj is None:
                    continue
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
    """根据快照还原材质节点、材质状态及网格矩阵。"""
    for rec in _state["restore"]:
        try:
            for tex, orig_ext in rec.get("tex_ext", []):
                try:
                    tex.extension = orig_ext
                except Exception:
                    pass
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

    for mesh, mw in _state["xform_snaps"]:
        try:
            mesh.matrix_world = mw
        except Exception:
            continue


def _stop_preview():
    """停止预览、移除残留 handler、还原状态并清空会话。"""
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
            # 任何材质不可预览时回滚已准备的临时状态。
            _state["restore"] = restore
            _restore()
            _state["restore"] = []
            detail = "；".join(f"{n}（{T(r)}）" for n, r in missing[:6])
            self.report({"ERROR"}, T("uvc.missing_header").format(detail))
            return {"CANCELLED"}

        # 网格变换动画可独立于 UV 配对存在。
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
        _remove_our_frame_handlers()
        bpy.app.handlers.frame_change_post.append(_on_frame)

        # 立即应用当前帧状态。
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
# load_post：清理残留会话。
# ─────────────────────────────────────────────────────────────────────────────

@persistent
def _on_load(*_args):
    # 新文件中的旧节点引用无效，不尝试还原，直接清理 handler 和会话状态。
    _remove_our_frame_handlers()
    _state["handler"] = None
    _state["pairs"] = []
    _state["restore"] = []
    _state["xform"] = []
    _state["xform_snaps"] = []
    _state["start_frame"] = 0


# ─────────────────────────────────────────────────────────────────────────────
# MESH 属性的网格绑定面板。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_mesh_binding(Panel):
    """MESH 属性的预览网格绑定（仅选中 MESH 属性时显示）"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Mesh Binding"
    bl_parent_id = "EFX_PT_mesh_drive"
    bl_order = 0
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

        # 可展示由 mod3_link 自动绑定的 viscon 网格组。
        targets = getattr(obj, "efx_mesh_targets", None)
        if targets:
            box = layout.box()
            groups = sorted({it.viscon for it in targets})
            box.label(text=T("uvc.viscon_bound").format(len(targets), len(groups)),
                      icon="MOD_PARTICLE_INSTANCE")
            col = box.column(align=True)
            col.scale_y = 0.8
            for it in targets:
                nm = it.obj.name if it.obj is not None else "?"
                col.label(text="  viscon %d: %s" % (it.viscon, nm))


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_uvc_preview_enter,
    EFX_OT_uvc_preview_exit,
    EFX_PT_mesh_binding,
    # 预览控制由 mesh_drive.py 的父面板提供。
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
