"""
blender_efx/mesh_align.py  —  绑定网格随 TRANSFORM3D + MESH 旋转/缩放实时对齐（预览式 + 可编辑 + 实例化）

设计（与用户确认）
------------------
- **预览式会话**（进入/退出，类 uvc/timl），但**会话内支持编辑实时重对齐**。
- **实例化**：一个网格对象不能同时出现在多处，故为每个「MESH 属性绑定」建一个**链接复制体**
  （共享网格数据、各自独立 transform），解决「多个 entry 复用同一网格也都显示」。
  进入时建实例 + 隐藏源网格；退出时删实例 + 恢复源网格可见，场景零残留。
- **对齐公式**：`instance.matrix_world = body.matrix_world · mesh_local`
    body.matrix_world = EFX_ENTRY empty 的世界矩阵（transform_sync 已据 TRANSFORM3D+骨骼+锚定摆好）
    mesh_local       = game_rot_matrix_blender(MESH.rotation) · Diag(game_scale_to_blender(MESH.scale)·global_scale)
  旋转/缩放复用 transform_sync 的正确转换器（基变换共轭，非朴素交换）。
- **实时编辑**：会话期间，fields.py 的字段编辑回调会调用本模块 realign_entry_if_active()——
    编辑 TRANSFORM3D(translate/rotate/resize) → 先重摆 entry empty，再重对齐其实例；
    编辑 MESH(rotation/scale/global_scale) → 重对齐其实例。

约束（CLAUDE.md）
-----------------
- 纯胶水层、只读 EFX 字段，不碰 byte-perfect。Python 3.10、bpy 稳定子集。
"""

import bpy
from mathutils import Matrix, Vector
from bpy.types import Operator, Panel

from .i18n import T
from . import transform_sync as _ts
from . import session_core as _sc
from . import root_collection as _rc


_TEMP_COLLECTION = "EFX Mesh Align (preview)"

# 标记：会话产物一律打自定义属性，"是否活跃/有哪些实例"由标记扫描派生，不用 Python _state
# （见 session_core 设计原则：状态=场景事实的派生量，undo/reload/热重载不残留孤儿）。
_INSTANCE_MARKER = "~EFX_ALIGN_INSTANCE"   # 实例对象标记
_BODY_KEY = "~EFX_ALIGN_BODY"              # 实例记源 entry 名（重对齐时反查）
_ATTR_KEY = "~EFX_ALIGN_ATTR"             # 实例记源 MESH 属性名（重对齐时反查）
_HID_FLAG = "~EFX_ALIGN_HID_ORIG"         # 被隐藏源网格记原 hide_viewport 值（还原用）


def _is_active() -> bool:
    """会话是否活跃：场景里有无对齐实例（标记扫描派生，非 Python 状态）。"""
    return bool(_sc.iter_marked(_INSTANCE_MARKER))


# ─────────────────────────────────────────────────────────────────────────────
# 属性/字段读取
# ─────────────────────────────────────────────────────────────────────────────

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
        gscale = 1.0  # 0 视为未设，避免实例塌成不可见

    rot = _ts.game_rot_matrix_blender(*rot_g) if rot_g else Matrix.Identity(4)
    if scl_g:
        sx, sy, sz = _ts.game_scale_to_blender(*scl_g)
    else:
        sx = sy = sz = 1.0
    scl = Matrix.Diagonal(Vector((sx * gscale, sy * gscale, sz * gscale, 1.0)))
    return rot @ scl


def apply_mesh_rotscale_to_object(mesh_attribute):
    """把 MESH 属性的 rotation/scale/global_scale 直接作用到其绑定对象（efx_mesh_target）。

    持久、实时：保留对象当前位置，只覆盖其本地旋转与缩放（= mesh_local）。
    仅对真正的 MESH 属性生效；非 MESH 属性或未绑定则忽略。
    """
    if not _is_mesh_attribute(mesh_attribute):
        return
    obj = getattr(mesh_attribute, "efx_mesh_target", None)
    if obj is None:
        return
    try:
        loc = obj.matrix_basis.to_translation()   # 保留原位置
        obj.matrix_basis = Matrix.Translation(loc) @ _mesh_local_matrix(mesh_attribute)
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


# ─────────────────────────────────────────────────────────────────────────────
# 会话（无 Python 状态：真相全在场景标记，见文件头设计原则）
# ─────────────────────────────────────────────────────────────────────────────

def _make_instance(src, col, label, body, mesh_attribute):
    """建链接复制体（共享网格数据）并打标记，返回新对象。"""
    dup = src.copy()          # 默认共享 .data（链接复制）
    dup.name = "EFX_align::" + label
    dup[_INSTANCE_MARKER] = 1
    dup[_BODY_KEY] = body.name          # 反查用：重对齐按 body 名筛实例
    dup[_ATTR_KEY] = mesh_attribute.name
    # ⚠ src.copy() 会继承源的隐藏状态：若源已被前一次循环隐藏，复制体会跟着隐藏
    # （多 entry 复用同源时只显示第一个的根因）→ 强制实例可见。
    try:
        dup.hide_viewport = False
        dup.hide_render = False
    except Exception:
        pass
    # 仅链进临时集合（src.copy 不自动入集合）
    try:
        col.objects.link(dup)
    except Exception:
        pass
    try:
        dup.hide_set(False)   # 取消按视图层的隐藏（眼睛图标）
    except Exception:
        pass
    return dup


def _align_instance(dup, body, mesh_attribute):
    try:
        dup.matrix_world = body.matrix_world @ _mesh_local_matrix(mesh_attribute)
    except Exception:
        pass


def realign_entry_if_active(body):
    """会话进行中，重对齐属于该 entry 的全部实例（供 fields.py 编辑回调调用）。

    ⚠ 完全按**场景标记**重新解析（零 Python 缓存）：扫所有对齐实例，取 _BODY_KEY==body.name 的，
    按 _ATTR_KEY 反查 MESH 属性对象再对齐。undo/reload 让引用失效也无所谓——每次按名重取。
    """
    if body is None or not _is_active():
        return
    for dup in _sc.iter_marked(_INSTANCE_MARKER):
        if dup.get(_BODY_KEY) != body.name:
            continue
        blk = bpy.data.objects.get(dup.get(_ATTR_KEY, "") or "")
        if blk is not None:
            _align_instance(dup, body, blk)


# ─────────────────────────────────────────────────────────────────────────────
# 进入 / 退出
# ─────────────────────────────────────────────────────────────────────────────

def _reconcile():
    """清场：删掉全部对齐实例、还原全部被隐藏源、删临时集合。按标记，非缓存引用。
    幂等、可重复安全调用；进入前先跑一次即根治历史遗留孤儿（"越进越乱"）。"""
    _sc.purge_marked(_INSTANCE_MARKER)
    _sc.restore_hidden(_HID_FLAG)
    _sc.remove_collection_named(_TEMP_COLLECTION)


def _start(roots, armature, use_anchor):
    """建实例并对齐。返回实例数。进入前先清场（marker 扫描），杜绝孤儿累积。"""
    _reconcile()
    col = _sc.get_or_create_collection(_TEMP_COLLECTION)
    n = 0
    for root in roots:
        if root is None:
            continue
        # 先确保 entry empty 已据 TRANSFORM3D+骨骼+锚定摆好（entry_world 来源）
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
                # 隐藏源网格：原 hide 值存源对象自定义属性（flag_hidden 幂等，多源复用只记一次）
                _sc.flag_hidden(src, _HID_FLAG)
                n += 1
    return n


def _stop():
    """退出：清场（删实例/还原源/删集合）。按标记，撤销/热重载脱节也不残留。"""
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
# Panel（选中 EFX_ENTRY 时显示）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_mesh_align(Panel):
    """绑定网格实时对齐预览"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Mesh Align (Preview)"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            return False
        from . import root_collection as _rc
        return not _rc.is_color_editor_mode(obj)

    def draw(self, context):
        layout = self.layout
        layout.label(text=T("align.hint"), icon="SNAP_ON")
        if _is_active():
            box = layout.box()
            box.label(text=T("align.previewing").format(len(_sc.iter_marked(_INSTANCE_MARKER))), icon="PLAY")
            row = box.row()
            row.scale_y = 1.3
            row.operator("efx.mesh_align_exit", text=T("align.exit"), icon="X")
        else:
            layout.prop(context.scene, "efx_align_all_efx", text=T("align.all_efx"))
            row = layout.row()
            row.scale_y = 1.3
            row.operator("efx.mesh_align_enter", text=T("align.enter"), icon="PLAY")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_mesh_align_enter,
    EFX_OT_mesh_align_exit,
    # EFX_PT_mesh_align 已整合进统一「EFX Preview」面板（efx_preview.py），
    # 不再单独注册；算子保留供 EFX Preview 编排调用。
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
