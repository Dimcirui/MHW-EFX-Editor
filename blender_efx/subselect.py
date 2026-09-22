"""在 Blender 属性与 ``SubselectTable`` 之间转换 Subselect 成员关系。

维护约束：``entries`` 是 Main 段的零基局部 Entry 索引，导入/导出均通过
``efx_index`` 映射；成员顺序即导出顺序。缺失结构化属性时从 ``raw_b64`` 回退，
悬空或不属于当前 Main 段的成员在导出时跳过，由校验模块报告。
"""

import bpy
from bpy.props import (
    StringProperty,
    CollectionProperty,
    PointerProperty,
    IntProperty,
)
from bpy.types import PropertyGroup, Operator

from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# §1  段局部索引映射地基（通用 helper，导出路径共用）
# ─────────────────────────────────────────────────────────────────────────────

def build_local_index_map(segment_collection, type_tag: str) -> dict:
    """构建对象到段内零基索引的映射，排序必须与 Main 段导出保持一致。"""
    raw_objs = []
    _collect_typed_objects(segment_collection, type_tag, raw_objs)

    # 仅可确定导出次序的对象能参与映射。
    valid = [o for o in raw_objs if o.get("efx_index") is not None]

    # ``efx_index`` 是导出段内次序。
    valid.sort(key=lambda o: int(o["efx_index"]))

    return {obj: idx for idx, obj in enumerate(valid)}


def _collect_typed_objects(col, type_tag: str, out: list) -> None:
    """递归收集集合及其子集合里 ~TYPE == type_tag 的对象（就地追加到 out）。"""
    for obj in col.objects:
        if obj.get("~TYPE") == type_tag:
            out.append(obj)
    for child_col in col.children:
        _collect_typed_objects(child_col, type_tag, out)


# ─────────────────────────────────────────────────────────────────────────────
# §2  PropertyGroup：Subselect 结构化存储
# ─────────────────────────────────────────────────────────────────────────────

def _table_type_hint(table_type_str: str) -> str:
    """返回 table_type 十进制字符串的只读十六进制与置位提示。"""
    try:
        v = int(str(table_type_str)) & 0xFFFFFFFF
    except (ValueError, TypeError):
        return "—"
    hexs = f"0x{v:08X}"
    if v == 0:
        return f"{hexs}  (no bits)"
    if v == 0xFFFFFFFF:
        return f"{hexs}  all bits (全选)"
    bits = [str(i) for i in range(32) if v & (1 << i)]
    if len(bits) == 1:
        return f"{hexs}  bit {bits[0]}"
    return f"{hexs}  bits {','.join(bits)}"


def _entry_object_poll(self, obj):
    """仅接受当前 EFX 根集合内、仍被集合引用的 EFX_ENTRY 对象。"""
    if obj.get("~TYPE") != "EFX_ENTRY":
        return False
    if not obj.users_collection:
        return False
    editing = getattr(bpy.context, "active_object", None)
    if editing is not None and not _rc.same_root(editing, obj):
        return False
    return True


class EFXSubselectMember(PropertyGroup):
    """Subselect 的单个 Entry 指针成员。"""
    body_ptr: PointerProperty(
        name="Entry Object",
        description="EFX_ENTRY object referenced by this Subselect table",
        type=bpy.types.Object,
        poll=_entry_object_poll,
    )


class EFXSubselectProps(PropertyGroup):
    """挂在 EFX_SUBSELECT 对象上的结构化表数据。

    uint32 字段以十进制字符串保存，避免 Blender 有符号整数范围限制。
    """
    table_type_str: StringProperty(
        name="Table Type",
        description="SubselectTable.table_type (uint32 bitmask, decimal string)",
        default="0",
    )

    unkn0_0_str: StringProperty(
        name="unkn0[0]",
        description="SubselectTable.unkn0[0] (uint32, decimal string)",
        default="4294967295",
    )

    unkn0_1_str: StringProperty(
        name="unkn0[1]",
        description="SubselectTable.unkn0[1] (uint32) — usually 0",
        default="0",
    )

    unkn0_2_str: StringProperty(
        name="unkn0[2]",
        description="SubselectTable.unkn0[2] (uint32) — usually 0",
        default="0",
    )

    members: CollectionProperty(
        name="Members",
        description="List of EFX_ENTRY referenced by this Subselect table (corresponds to entries[])",
        type=EFXSubselectMember,
    )

    active_member_index: IntProperty(
        name="Active Member Index",
        description="Currently active member (used by the list UI)",
        default=0,
        min=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# §2a  导入：SubselectTable → EFXSubselectProps
# ─────────────────────────────────────────────────────────────────────────────

def init_subselect_props(ss_obj: bpy.types.Object,
                         tbl,
                         main_bodies_by_index: dict) -> None:
    """将 SubselectTable 写入对象属性，并按 ``entries`` 原序解析成员指针。"""
    props = ss_obj.efx_subselect

    props.table_type_str = str(tbl.table_type)

    props.unkn0_0_str = str(tbl.unkn0[0])
    props.unkn0_1_str = str(tbl.unkn0[1])
    props.unkn0_2_str = str(tbl.unkn0[2])

    props.members.clear()
    for entry_idx in tbl.entries:
        item = props.members.add()
        entry_obj = main_bodies_by_index.get(entry_idx)
        if entry_obj is not None:
            item.body_ptr = entry_obj
        # 未解析的索引保留为空成员，供校验模块报告。


# ─────────────────────────────────────────────────────────────────────────────
# §2b  导出：EFXSubselectProps → SubselectTable
# ─────────────────────────────────────────────────────────────────────────────

def export_subselect_table(ss_obj: bpy.types.Object,
                           entry_index_map: dict):
    """从对象属性重建 SubselectTable。

    旧场景缺少结构化属性或 uint32 解析失败时，从 ``raw_b64`` 回退；悬空成员及
    不在当前 Main 段映射内的成员不写入 ``entries``。
    """
    from ..efx_format.efxfile import SubselectTable

    try:
        props = ss_obj.efx_subselect
    except AttributeError:
        # 兼容没有结构化属性的旧场景。
        return _fallback_raw_subselect(ss_obj)

    try:
        table_type = int(str(props.table_type_str))
    except (ValueError, TypeError):
        return _fallback_raw_subselect(ss_obj)

    try:
        unkn0 = (
            int(str(props.unkn0_0_str)),
            int(str(props.unkn0_1_str)),
            int(str(props.unkn0_2_str)),
        )
    except (ValueError, TypeError):
        return _fallback_raw_subselect(ss_obj)

    entries = []
    for item in props.members:
        entry_obj = item.body_ptr
        if entry_obj is None:
            # 悬空成员不导出。
            continue
        local_idx = entry_index_map.get(entry_obj)
        if local_idx is None:
            # 其他文件的 Entry 没有当前 Main 段索引，不能导出。
            continue
        entries.append(local_idx)

    return SubselectTable(
        table_type=table_type,
        unkn0=unkn0,
        entries=entries,
    )


def _fallback_raw_subselect(ss_obj: bpy.types.Object):
    """从 ``raw_b64`` 还原 SubselectTable，供旧场景兼容回退。"""
    import base64
    from ..efx_format.efxfile import SubselectTable
    import struct

    raw = base64.b64decode(str(ss_obj["raw_b64"]))
    table_type = struct.unpack_from('<I', raw, 0)[0]
    unkn0 = struct.unpack_from('<3I', raw, 4)
    entry_count = struct.unpack_from('<i', raw, 16)[0]
    entries = list(struct.unpack_from(f'<{entry_count}i', raw, 20))
    return SubselectTable(table_type=table_type, unkn0=unkn0, entries=entries)


# ─────────────────────────────────────────────────────────────────────────────
# §3  面板算子：增删 Subselect 成员
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_subselect_member_add(Operator):
    """向当前 Subselect 表追加空成员。"""

    bl_idname      = "efx.subselect_member_add"
    bl_label       = "Add Member"
    bl_description = "Append an empty slot to the end of the Subselect table's members list"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_SUBSELECT"

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_subselect
        props.members.add()
        props.active_member_index = len(props.members) - 1
        return {"FINISHED"}


class EFX_OT_subselect_member_remove(Operator):
    """删除当前激活的 Subselect 成员"""

    bl_idname      = "efx.subselect_member_remove"
    bl_label       = "Remove Member"
    bl_description = "Delete the currently active member from the Subselect table's members list"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_SUBSELECT":
            return False
        try:
            props = obj.efx_subselect
            return len(props.members) > 0
        except AttributeError:
            return False

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_subselect
        idx = props.active_member_index
        if 0 <= idx < len(props.members):
            props.members.remove(idx)
            # 删除后将活动索引限制在有效范围。
            props.active_member_index = min(idx, max(0, len(props.members) - 1))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §3a  UIList：Subselect 成员列表
# ─────────────────────────────────────────────────────────────────────────────

class EFX_UL_subselect_members(bpy.types.UIList):
    """显示和编辑 Subselect 成员列表。"""

    bl_idname = "EFX_UL_subselect_members"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index}:", icon="BLANK1")
        entry_obj = item.body_ptr
        if entry_obj is not None:
            row.prop(item, "body_ptr", text="", icon="OBJECT_DATA")
        else:
            # 悬空成员仍显示可编辑指针槽。
            row.prop(item, "body_ptr", text=T("sub.unset"), icon="ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# §3b  面板：N 面板 EFX 标签 Subselect 成员编辑
# ─────────────────────────────────────────────────────────────────────────────

def _draw_subselect_content(layout, context):
    """绘制 N 面板和 Data 面板共用的 Subselect 编辑内容。"""
    obj = context.active_object

    try:
        props = obj.efx_subselect
    except AttributeError:
        layout.label(text=T("sub.no_data"), icon="ERROR")
        return

    # ── 元数据 ─────────────────────────────────────────────────────────────
    meta_box = layout.box()
    meta_box.label(text=T("sub.table_meta"), icon="INFO")
    meta_box.prop(props, "table_type_str")
    # 只读展示 table_type 的十六进制和置位信息。
    hint_row = meta_box.row()
    hint_row.enabled = False
    hint_row.label(text=_table_type_hint(props.table_type_str))
    meta_box.prop(props, "unkn0_0_str")
    row1 = meta_box.row(align=True)
    row1.prop(props, "unkn0_1_str")
    row1.label(text="(usually 0)")
    row2 = meta_box.row(align=True)
    row2.prop(props, "unkn0_2_str")
    row2.label(text="(usually 0)")

    layout.separator()

    # ── 成员列表 ───────────────────────────────────────────────────────────
    list_box = layout.box()
    list_box.label(text=f"{T('sub.members')}({len(props.members)})", icon="OUTLINER_OB_EMPTY")

    row = list_box.row()
    row.template_list(
        "EFX_UL_subselect_members",
        "",
        props,
        "members",
        props,
        "active_member_index",
        rows=4,
    )

    col = row.column(align=True)
    col.operator("efx.subselect_member_add",    text="", icon="ADD")
    col.operator("efx.subselect_member_remove", text="", icon="REMOVE")

    # ── 活动成员 ────────────────────────────────────────────────────────────
    idx = props.active_member_index
    if 0 <= idx < len(props.members):
        active_item = props.members[idx]
        detail_row = list_box.row()
        detail_row.prop(active_item, "body_ptr", text=T("sub.entry_object"))

    # ── 悬空成员警告 ────────────────────────────────────────────────────────
    dangling = sum(1 for m in props.members if m.body_ptr is None)
    if dangling > 0:
        warn_row = layout.row()
        warn_row.alert = True
        warn_row.label(
            text=f"⚠ {dangling} {T('sub.members_dangling')}",
            icon="ERROR",
        )


class EFX_PT_subselect(bpy.types.Panel):
    """VIEW_3D N 面板中的 Subselect 成员编辑入口。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Subselect Ownership"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_SUBSELECT"

    def draw(self, context):
        _draw_subselect_content(self.layout, context)


class EFX_PT_subselect_data(bpy.types.Panel):
    """Subselect 归属（属性编辑器 → Object Data Properties，选中 EFX_SUBSELECT 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Subselect Ownership"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_SUBSELECT"

    def draw(self, context):
        _draw_subselect_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# PropertyGroup 必须先于依赖它的 UIList/Operator 注册。
_CLASSES_CORE = (
    EFXSubselectMember,
    EFXSubselectProps,
    EFX_UL_subselect_members,
    EFX_OT_subselect_member_add,
    EFX_OT_subselect_member_remove,
)

# EFX_PT_subselect 由 panels.py 在父面板之后注册。


def register():
    """注册 Subselect 数据与编辑核心；面板由 panels.py 注册。"""
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_subselect = PointerProperty(
        name="EFX Subselect Properties",
        description="Structured Subselect data for the EFX_SUBSELECT object",
        type=EFXSubselectProps,
    )


def unregister():
    """注销核心类并移除对象 PointerProperty。"""
    try:
        del bpy.types.Object.efx_subselect
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
