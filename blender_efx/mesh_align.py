"""按 TRANSFORM3D 与 MESH 字段对齐绑定网格的临时实例。

维护约束：
- 会话创建共享网格数据、独立变换的实例并隐藏源对象；退出必须删除实例、恢复源对象。
- 会话状态由场景标记派生，不能依赖 Python 缓存。
- 字段编辑期间按当前 Entry 与 MESH 属性重对齐实例；本模块只读取 EFX 字段。
"""

import bpy
from mathutils import Matrix, Vector
from bpy.types import Operator, Panel

from .i18n import T
from . import transform_sync as _ts
from . import session_core as _sc
from . import root_collection as _rc


_TEMP_COLLECTION = "EFX Mesh Align (preview)"

_INSTANCE_MARKER = "~EFX_ALIGN_INSTANCE"
_BODY_KEY = "~EFX_ALIGN_BODY"
_ATTR_KEY = "~EFX_ALIGN_ATTR"
_HID_FLAG = "~EFX_ALIGN_HID_ORIG"


def _is_active() -> bool:
    """会话是否活跃：场景里有无对齐实例（标记扫描派生，非 Python 状态）。"""
    return bool(_sc.iter_marked(_INSTANCE_MARKER))


def _attribute_type_hash(obj):
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return None
    try:
        return int(obj.efx_block.type_hash_str)
    except Exception:
        return None


def _is_mesh_attribute(obj):
    from ..efx_format.hashes import MESH
    return _attribute_type_hash(obj) == MESH


def _read_field6_fixed(block, name):
    """读 FLOAT6 字段的基础三元组（idx 0/2/4）；无则 None。"""
    try:
        for it in block.efx_block.field_items:
            if it.ori_name == name and it.data_type == "FLOAT6":
                v = it.float6_value
                return (v[0], v[2], v[4])
    except Exception:
        pass
    return None


def _read_float(block, name, default):
    try:
        for it in block.efx_block.field_items:
            if it.ori_name == name:
                return float(it.float_value)
    except Exception:
        pass
    return default


def _mesh_local_matrix(mesh_attribute):
    """MESH 属性的本地变换矩阵：rotation(共轭) · Diag(scale·global_scale)。"""
    rot_g = _read_field6_fixed(mesh_attribute, "rotation")
    scl_g = _read_field6_fixed(mesh_attribute, "scale")
    gscale = _read_float(mesh_attribute, "global_scale", 1.0)
    if gscale == 0.0:
        gscale = 1.0

    rot = _ts.game_rot_matrix_blender(*rot_g) if rot_g else Matrix.Identity(4)
    if scl_g:
        sx, sy, sz = _ts.game_scale_to_blender(*scl_g)
    else:
        sx = sy = sz = 1.0
    scl = Matrix.Diagonal(Vector((sx * gscale, sy * gscale, sz * gscale, 1.0)))
    return rot @ scl


def apply_mesh_rotscale_to_object(mesh_attribute):
    """将 MESH 旋转和缩放作用到全部绑定对象，保留其位置。"""
    if not _is_mesh_attribute(mesh_attribute):
        return
    targets = []
    primary = getattr(mesh_attribute, "efx_mesh_target", None)
    if primary is not None:
        targets.append(primary)
    for item in getattr(mesh_attribute, "efx_mesh_targets", ()):
        obj = item.obj
        if obj is not None and obj not in targets:
            targets.append(obj)
    if not targets:
        return
    mat_local = _mesh_local_matrix(mesh_attribute)
    for obj in targets:
        try:
            loc = obj.matrix_basis.to_translation()
            obj.matrix_basis = Matrix.Translation(loc) @ mat_local
        except Exception:
            pass


def _entry_mesh_bindings(entry_obj):
    """返回 entry 下 (mesh_attribute, source_obj) 列表：MESH 属性且 efx_mesh_target 非空。"""
    out = []
    for blk in entry_obj.children:
        if not _is_mesh_attribute(blk):
            continue
        src = getattr(blk, "efx_mesh_target", None)
        if src is not None:
            out.append((blk, src))
    return out


def _iter_scope_bodies(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ENTRY")


def _resolve_root(obj):
    return _rc.find_root_collection(obj)


def _all_efx_roots():
    return _rc.all_root_collections()


def _make_instance(src, col, label, body, mesh_attribute):
    """建链接复制体（共享网格数据）并打标记，返回新对象。"""
    dup = src.copy()
    dup.name = "EFX_align::" + label
    dup[_INSTANCE_MARKER] = 1
    dup[_BODY_KEY] = body.name
    dup[_ATTR_KEY] = mesh_attribute.name
    # 源对象可能已隐藏，实例必须强制可见。
    try:
        dup.hide_viewport = False
        dup.hide_render = False
    except Exception:
        pass
    try:
        col.objects.link(dup)
    except Exception:
        pass
    try:
        dup.hide_set(False)
    except Exception:
        pass
    return dup


def _align_instance(dup, body, mesh_attribute):
    try:
        dup.matrix_world = body.matrix_world @ _mesh_local_matrix(mesh_attribute)
    except Exception:
        pass


def realign_entry_if_active(body):
    """会话中按场景标记重对齐指定 Entry 的全部实例。"""
    if body is None or not _is_active():
        return
    for dup in _sc.iter_marked(_INSTANCE_MARKER):
        if dup.get(_BODY_KEY) != body.name:
            continue
        blk = bpy.data.objects.get(dup.get(_ATTR_KEY, "") or "")
        if blk is not None:
            _align_instance(dup, body, blk)


def _reconcile():
    """按标记清理实例、恢复源对象并删除临时集合；可重复调用。"""
    _sc.purge_marked(_INSTANCE_MARKER)
    _sc.restore_hidden(_HID_FLAG)
    _sc.remove_collection_named(_TEMP_COLLECTION)


def _start(roots, armature, use_anchor):
    """清场后创建并对齐实例，返回实例数量。"""
    _reconcile()
    col = _sc.get_or_create_collection(_TEMP_COLLECTION)
    n = 0
    for root in roots:
        if root is None:
            continue
        try:
            _ts.sync_all_transform3d(root, armature, use_anchor=use_anchor)
        except Exception:
            pass
        for body in _iter_scope_bodies(root):
            bindings = _entry_mesh_bindings(body)
            if not bindings:
                continue
            for mattribute, src in bindings:
                label = str(body.get("efx_raw_label", "") or body.name)
                dup = _make_instance(src, col, label, body, mattribute)
                _align_instance(dup, body, mattribute)
                _sc.flag_hidden(src, _HID_FLAG)
                n += 1
    return n


def _stop():
    """退出对齐会话并恢复场景。"""
    _reconcile()


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scope_roots(context):
    if getattr(context.scene, "efx_align_all_efx", False):
        roots = _all_efx_roots()
        return roots or None
    root = _resolve_root(context.active_object)
    return [root] if root is not None else None


class EFX_OT_mesh_align_enter(Operator):
    """进入网格对齐预览（按 TRANSFORM3D + MESH 旋转/缩放摆放绑定网格的实例，会话内可实时编辑）"""

    bl_idname = "efx.mesh_align_enter"
    bl_label = "Enter Mesh Align"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if _is_active():
            return False
        if getattr(context.scene, "efx_align_all_efx", False):
            return True
        return _resolve_root(context.active_object) is not None

    def execute(self, context):
        roots = _resolve_scope_roots(context)
        if not roots:
            self.report({"ERROR"}, T("align.no_root"))
            return {"CANCELLED"}
        armature = getattr(context.scene, "efx_armature", None)
        use_anchor = getattr(context.scene, "efx_anchor_placement", True)
        try:
            n = _start(roots, armature, use_anchor)
        except Exception as exc:
            _stop()
            self.report({"ERROR"}, T("align.failed").format(exc))
            return {"CANCELLED"}
        if n == 0:
            _stop()
            self.report({"WARNING"}, T("align.no_content"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("align.entered").format(n))
        return {"FINISHED"}


class EFX_OT_mesh_align_exit(Operator):
    """退出网格对齐预览（删实例、恢复源网格）"""

    bl_idname = "efx.mesh_align_exit"
    bl_label = "Exit Mesh Align"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _is_active()

    def execute(self, context):
        _stop()
        self.report({"INFO"}, T("align.exited"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_mesh_align_enter,
    EFX_OT_mesh_align_exit,
    # 本模块不出面板：静态摆放这一项已并进「Mesh Drive」面板（mesh_drive.py），
    # 这里只留算子供它编排调用。
]


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_align_all_efx = bpy.props.BoolProperty(
        name="所有 EFX 一起对齐",
        description="进入对齐时处理场景内所有 EFX 的绑定网格（不勾则仅当前 EFX）",
        default=False,
    )
    # 无 Python 状态需要 load 复位（真相全在场景标记）；孤儿清理靠 enter 先清场。


def unregister():
    _stop()
    if hasattr(bpy.types.Scene, "efx_align_all_efx"):
        del bpy.types.Scene.efx_align_all_efx
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
