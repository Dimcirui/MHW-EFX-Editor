"""EXTERNREFERENCE 的 Extern 指针化。

维护约束：
- referenceIndex 位于 data_bytes 偏移 4，使用有符号 int32；-1 表示无目标。
- 有效本地索引和 -1 才可指针化；越界值保持 pointerized=False，并保留原始字节。
- 导出时无法解析的指针必须写为 -1，不能保留可能因段重排而失效的旧索引。
- 指针选择限制在同一 EFX 根，多个引用可指向同一 Extern。
"""

import struct
import bpy
from bpy.props import (
    BoolProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup, Operator

from .i18n import T
from . import root_collection as _rc


_REFERENCE_INDEX_OFFSET = 4
_SENTINEL_VALUE = -1


def _extern_object_poll(self, obj):
    """仅允许选择活动对象所属 EFX 根内的 Extern。"""
    if obj.get("~TYPE") != "EFX_EXTERN":
        return False
    editing = getattr(bpy.context, "active_object", None)
    if editing is not None and not _rc.same_root(editing, obj):
        return False
    return True


class EFXExternRefProps(PropertyGroup):
    """挂在 EXTERNREFERENCE 属性对象上的指针状态。"""

    extern_ref_ptr: PointerProperty(
        name="Extern Reference",
        description="The EFX_EXTERN object this ExternReference attribute points to (the extern corresponding to referenceIndex)",
        type=bpy.types.Object,
        poll=_extern_object_poll,
    )

    extern_ref_none: BoolProperty(
        name="No Target (-1)",
        description="True = referenceIndex == -1 (sentinel, no extern target)",
        default=False,
    )

    extern_ref_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = referenceIndex has been pointerized (valid range / -1 sentinel); "
            "False = dead attribute / out of range, preserve original bytes (byte-perfect fallback)"
        ),
        default=False,
    )


def init_extern_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    extern_objs_by_index: dict,
    count_extern: int,
) -> None:
    """从原始索引初始化指针状态；越界值保持为未指针化。"""
    props = blk_obj.efx_extern_ref

    if len(data_bytes) < 8:
        props.extern_ref_pointerized = False
        return

    v = struct.unpack_from('<i', data_bytes, _REFERENCE_INDEX_OFFSET)[0]

    if v == _SENTINEL_VALUE:
        props.extern_ref_none = True
        props.extern_ref_pointerized = True
        return

    if count_extern > 0 and 0 <= v < count_extern:
        target_obj = extern_objs_by_index.get(v)
        if target_obj is not None:
            props.extern_ref_ptr = target_obj
            props.extern_ref_pointerized = True
        else:
            props.extern_ref_pointerized = False
        return

    props.extern_ref_pointerized = False


def overlay_extern_ref_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    extern_index_map: dict,
) -> bytes:
    """按当前指针覆写索引；未指针化或悬空时保留原始字节。"""
    try:
        props = blk_obj.efx_extern_ref
    except AttributeError:
        return data_bytes

    if not props.extern_ref_pointerized:
        return data_bytes

    if props.extern_ref_none:
        new_index = _SENTINEL_VALUE
    else:
        extern_obj = props.extern_ref_ptr
        if extern_obj is None:
            return data_bytes
        new_index = extern_index_map.get(extern_obj)
        if new_index is None:
            # 段内索引改变后，旧索引可能错误指向另一项。
            new_index = _SENTINEL_VALUE

    if len(data_bytes) < 8:
        return data_bytes

    buf = bytearray(data_bytes)
    struct.pack_into('<i', buf, _REFERENCE_INDEX_OFFSET, new_index)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# §6  算子：强制解锁死块（pointerized=False → pointerized=True + ptr=None）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_force_pointerize_extern_ref(Operator):
    """把死块/越界的 ExternReference 强制升级为悬空指针，以便手动重连 Extern 目标"""

    bl_idname  = "efx.force_pointerize_extern_ref"
    bl_label   = "Force Unlock (dangling)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            from ..efx_format.hashes import EXTERNREFERENCE
            if int(str(obj.get("type_hash", ""))) != EXTERNREFERENCE:
                return False
            return not obj.efx_extern_ref.extern_ref_pointerized
        except (AttributeError, ValueError, ImportError):
            return False

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_extern_ref
        props.extern_ref_pointerized = True
        props.extern_ref_none        = False
        props.extern_ref_ptr         = None
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §7  面板：ExternReference 块的 referenceIndex 指针编辑器
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_extern_ref(bpy.types.Panel):
    """
    ExternReference 块的 Extern 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_ATTRIBUTE（EXTERNREFERENCE 类型）时显示：
      - pointerized=False：显示"死块/越界"警告（原始字节保留）
      - pointerized=True + none=False：EFX_EXTERN 对象选择器
      - pointerized=True + none=True：显示"无目标（-1 哨兵）"勾选
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Extern Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        # 仅当 type_hash == EXTERNREFERENCE 时显示
        try:
            from ..efx_format.hashes import EXTERNREFERENCE
            bp = obj.efx_block
            return int(bp.type_hash_str) == EXTERNREFERENCE
        except (AttributeError, ValueError, ImportError):
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_extern_ref
        except AttributeError:
            layout.label(text=T("extern.no_data"), icon="ERROR")
            return

        if not props.extern_ref_pointerized:
            # 死块/越界：原始字节保留，只读提示 + 强制解锁按钮
            box = layout.box()
            box.label(text=T("extern.dead_title"), icon="ERROR")
            box.label(text=T("extern.dead_line1"))
            box.label(text=T("extern.dead_line2"))
            box.operator("efx.force_pointerize_extern_ref",
                         text=T("extern.force_unlock"), icon="UNLOCKED")
            return

        # 已指针化
        box = layout.box()
        box.label(text="Reference Index", icon="LINKED")

        # 无目标（-1 哨兵）勾选
        row = box.row(align=True)
        row.prop(props, "extern_ref_none", text=T("extern.no_target_sentinel"))

        if props.extern_ref_none:
            # none=True：没有 extern 目标，禁用指针选择器
            row2 = box.row(align=True)
            row2.enabled = False
            row2.prop(props, "extern_ref_ptr", text=T("extern.extern_object"))
        else:
            # 正常指针：显示 EFX_EXTERN 对象选择器
            row2 = box.row(align=True)
            row2.prop(props, "extern_ref_ptr", text=T("extern.extern_object"))

            # 悬空警告
            if props.extern_ref_ptr is None:
                warn = box.row()
                warn.alert = True
                warn.label(
                    text=T("extern.dangling"),
                    icon="ERROR",
                )
            else:
                # 显示 extern 的 efx_index（参考信息）
                ext_obj = props.extern_ref_ptr
                ext_idx = ext_obj.get("efx_index", "?")
                info = box.row()
                info.label(text=T("extern.local_index") + f" {ext_idx}", icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 注册顺序：PropertyGroup 先；Panel 依赖 EFX_PT_entry（bl_parent_id），
# 由 panels.register() 在 EFX_PT_entry 之后注册。
_CLASSES_CORE = (
    EFXExternRefProps,
    EFX_OT_force_pointerize_extern_ref,
)

# EFX_PT_extern_ref 导出给 panels.py，由 panels.register() 在 EFX_PT_entry 之后注册。


def register():
    """
    注册 ExternRef 核心类（PropertyGroup）并把 EFXExternRefProps 挂到 Object 上。
    注意：EFX_PT_extern_ref 面板由 panels.py 在 EFX_PT_entry 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_extern_ref = PointerProperty(
        name="EFX Extern Reference Properties",
        description="Extern pointer data for EFX_ATTRIBUTE (EXTERNREFERENCE type)",
        type=EFXExternRefProps,
    )


def unregister():
    """
    注销 ExternRef 核心类并清理 PointerProperty。
    EFX_PT_extern_ref 由 panels.py 先注销。
    """
    try:
        del bpy.types.Object.efx_extern_ref
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
