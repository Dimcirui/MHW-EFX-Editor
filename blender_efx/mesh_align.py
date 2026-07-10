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
from bpy.app.handlers import persistent

from .i18n import T
from . import transform_sync as _ts


_TEMP_COLLECTION = "EFX Mesh Align (preview)"


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
    for b in root_obj.children:
        if b.get("~TYPE") == "EFX_ENTRY":
            yield b


def _resolve_root(obj):
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _all_efx_roots():
    return [o for o in bpy.data.objects if o.get("~TYPE") == "EFX_ROOT"]


# ─────────────────────────────────────────────────────────────────────────────
# 会话状态
# ─────────────────────────────────────────────────────────────────────────────

_state = {
    "active": False,
    "by_entry": {},          # body.name -> [(dup_obj, mesh_attribute)]
    "instances": [],        # 所有 dup 对象
    "hidden": [],           # [(source_obj, orig_hide_viewport)]
    "collection": None,
}


def _get_temp_collection():
    col = bpy.data.collections.get(_TEMP_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(_TEMP_COLLECTION)
        try:
            bpy.context.scene.collection.children.link(col)
        except Exception:
            pass
    return col


def _make_instance(src, col, label):
    """建链接复制体（共享网格数据），返回新对象。"""
    dup = src.copy()          # 默认共享 .data（链接复制）
    dup.name = "EFX_align::" + label
    dup["~EFX_ALIGN_INSTANCE"] = 1
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

    ⚠ 按**对象名**重新解析（不用缓存的对象引用）：Blender 撤销(undo)会让 Python 持有的
    bpy 对象引用失效，缓存引用会变悬空 → 实例无法继续跟随。按名每次重取即可幸免。
    """
    if not _state["active"] or body is None:
        return
    entries = _state["by_entry"].get(body.name)
    if not entries:
        return
    for dup_name, blk_name in entries:
        dup = bpy.data.objects.get(dup_name)
        blk = bpy.data.objects.get(blk_name)
        if dup is not None and blk is not None:
            _align_instance(dup, body, blk)


# ─────────────────────────────────────────────────────────────────────────────
# 进入 / 退出
# ─────────────────────────────────────────────────────────────────────────────

def _start(roots, armature, use_anchor):
    """建实例并对齐。返回实例数。"""
    col = _get_temp_collection()
    hidden_seen = set()
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
            entries = []
            for mattribute, src in bindings:
                label = str(body.get("efx_raw_label", "") or body.name)
                dup = _make_instance(src, col, label)
                _align_instance(dup, body, mattribute)
                # ⚠ 存对象名（非引用）：撤销后引用失效，名仍可重取（见 realign_entry_if_active）
                entries.append((dup.name, mattribute.name))
                _state["instances"].append(dup.name)
                # 隐藏源网格（每个源只隐一次，快照原状态）
                if src.name not in hidden_seen:
                    hidden_seen.add(src.name)
                    _state["hidden"].append((src.name, src.hide_viewport))
                    try:
                        src.hide_viewport = True
                    except Exception:
                        pass
                n += 1
            if entries:
                _state["by_entry"][body.name] = entries
    _state["collection"] = col.name
    _state["active"] = True
    return n


def _stop():
    """删实例、恢复源网格可见、删临时集合、清状态。可重复安全调用。

    全部按**名**重新解析（撤销后引用失效；名仍有效）。
    """
    for dup_name in _state["instances"]:
        dup = bpy.data.objects.get(dup_name)
        if dup is not None:
            try:
                bpy.data.objects.remove(dup, do_unlink=True)
            except Exception:
                pass
    for src_name, orig in _state["hidden"]:
        src = bpy.data.objects.get(src_name)
        if src is not None:
            try:
                src.hide_viewport = orig
            except Exception:
                pass
    col = bpy.data.collections.get(_state["collection"]) if _state["collection"] else None
    if col is not None:
        try:
            bpy.data.collections.remove(col)
        except Exception:
            pass
    _state["active"] = False
    _state["by_entry"] = {}
    _state["instances"] = []
    _state["hidden"] = []
    _state["collection"] = None


@persistent
def _on_load(*_args):
    # 换文件：旧引用失效，直接清状态（不碰已不存在的对象）
    _state["active"] = False
    _state["by_entry"] = {}
    _state["instances"] = []
    _state["hidden"] = []
    _state["collection"] = None


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
        if _state["active"]:
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
        return _state["active"]

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
        return obj is not None and obj.get("~TYPE") == "EFX_ENTRY"

    def draw(self, context):
        layout = self.layout
        layout.label(text=T("align.hint"), icon="SNAP_ON")
        if _state["active"]:
            box = layout.box()
            box.label(text=T("align.previewing").format(len(_state["instances"])), icon="PLAY")
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
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    _stop()
    if _on_load in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "efx_align_all_efx"):
        del bpy.types.Scene.efx_align_all_efx
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
