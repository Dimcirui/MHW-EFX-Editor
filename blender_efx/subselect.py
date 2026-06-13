"""
blender_efx/subselect.py  —  L2 #1a：Subselect 结构化存储 + 段局部索引映射地基

设计原则（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：PropertyGroup / CollectionProperty / PointerProperty /
    StringProperty / IntProperty / Operator / Panel / UIList
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：Subselect 导出时重建的 entries 索引列表必须与原文件一致

Subselect 结构（efx_format/efxfile.py SubselectTable）：
  table_type : uint32（4B）
  unkn0      : uint32[3]（12B）
  entry_count: int32（4B）
  entries    : int32[entry_count]  ← 每个值是 Main 段的局部 0-based body 索引

索引映射约定（已实测，BLUEPRINT §9）：
  entries[i] 是 Main 段的 0-based body 序号（efx_index == 该序号的 EFX_BODY 对象）。
  导入时：entries[i] → 找 Main 段里 efx_index==entries[i] 的 EFX_BODY 对象，存 PointerProperty。
  导出时：member.body_ptr → 通过段局部索引映射 → 还原整数 index → 重建 SubselectTable.entries。

byte-perfect 保证：
  - table_type / unkn0 原样存储（字符串，避免 uint32 溢出）。
  - entries 顺序由 members CollectionProperty 顺序决定，导入时按 entries 原序填入。
  - 悬空 member（body_ptr=None）导出时跳过（TODO: 后续校验阶段改为报错）。
  - bodies 未变时：entries[i] == 该对象的 efx_index == Main 段局部序号，精确往返。
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


# ─────────────────────────────────────────────────────────────────────────────
# §1  段局部索引映射地基（通用 helper，导出路径共用）
# ─────────────────────────────────────────────────────────────────────────────

def build_local_index_map(segment_collection, type_tag: str) -> dict:
    """
    构建段局部索引映射：{Object → 0-based local index}。

    参数
    ----
    segment_collection : bpy.types.Collection
        段集合（如 col_main），包含该段全部 Empty 对象。
        函数会递归收集集合及子集合里的所有对象。
    type_tag : str
        对象的 ~TYPE 自定义属性值（如 'EFX_BODY'）。

    返回
    ----
    dict[bpy.types.Object, int]
        键：段内对象；值：按 efx_index 排序后的 0-based 序号。

    用法示例（导出 Subselect 段之前）：
        body_index_map = build_local_index_map(col_main, 'EFX_BODY')
        # body_index_map[some_body_obj] → 该 body 在 Main 段的局部序号

    注意
    ----
    - 只收集拥有 efx_index 自定义属性的对象（防御性过滤）。
    - 排序依据是 int(obj['efx_index'])，与导出路径对 body_objs.sort() 完全一致。
    - 返回值序号 == 导出 Main 数组里该 body 的最终位置 == SubselectTable.entries 期望值。
    """
    # 递归收集集合内全部匹配 type_tag 的对象
    raw_objs = []
    _collect_typed_objects(segment_collection, type_tag, raw_objs)

    # 只保留有 efx_index 的对象（防御）
    valid = [o for o in raw_objs if o.get("efx_index") is not None]

    # 按 efx_index 升序排序（与 export_efx_tree 中 body_objs.sort() 逻辑一致）
    valid.sort(key=lambda o: int(o["efx_index"]))

    # 枚举：局部 index = 排序后的位置
    return {obj: idx for idx, obj in enumerate(valid)}


def _collect_typed_objects(col, type_tag: str, out: list) -> None:
    """递归收集集合及其子集合里 ~TYPE == type_tag 的对象（就地追加到 out）。"""
    for obj in col.objects:
        if obj.get("~TYPE") == type_tag:
            out.append(obj)
    for child_col in col.children:
        _collect_typed_objects(child_col, type_tag, out)


def find_main_collection(root_obj: bpy.types.Object):
    """
    从 EFX_ROOT 对象出发，找到 Main 段集合（名含 ' Main' 后缀的子集合）。

    返回 bpy.types.Collection 或 None（找不到时）。
    在导出时用于构建 body_index_map。
    """
    for col in bpy.data.collections:
        # Main 集合命名规则：<file_stem>_2 Main（见 io_tree.py §4）
        if col.name.endswith("_2 Main"):
            # 验证：该集合是 root_obj 所在根集合的子集合
            for parent_col in bpy.data.collections:
                if col.name in [c.name for c in parent_col.children]:
                    # 再验证 root_obj 在 parent_col 里
                    if root_obj in list(parent_col.objects):
                        return col
    # 宽松回退：只匹配名字
    for col in bpy.data.collections:
        if col.name.endswith("_2 Main"):
            return col
    return None


# ─────────────────────────────────────────────────────────────────────────────
# §2  PropertyGroup：Subselect 结构化存储
# ─────────────────────────────────────────────────────────────────────────────

def _find_root_obj(obj):
    """沿 parent 链向上找 ~TYPE == 'EFX_ROOT' 的对象，找不到返回 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _body_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_BODY'，且限定为活动对象
    所在 EFX 文件（同一 EFX_ROOT）内的 body——多 EFX 集合并存时防串文件。"""
    if obj.get("~TYPE") != "EFX_BODY":
        return False
    editing = getattr(bpy.context, "active_object", None)
    if editing is not None:
        root_self = _find_root_obj(editing)
        root_obj = _find_root_obj(obj)
        if root_self is not None and root_obj is not None and root_self is not root_obj:
            return False
    return True


class EFXSubselectMember(PropertyGroup):
    """
    SubselectTable 的单条成员：指向一个 EFX_BODY 对象的指针。

    CollectionProperty 元素，挂在 EFXSubselectProps.members 上。
    """
    body_ptr: PointerProperty(
        name="Body Object",
        description="EFX_BODY object referenced by this Subselect table",
        type=bpy.types.Object,
        poll=_body_object_poll,
    )


class EFXSubselectProps(PropertyGroup):
    """
    挂在 EFX_SUBSELECT Empty 对象上（obj.efx_subselect）的 PropertyGroup。

    字段
    ----
    table_type_str  : 十进制字符串（uint32，避免 Blender int32 溢出）
    unkn0_str       : 三个 uint32，逗号分隔十进制字符串
    members         : CollectionProperty[EFXSubselectMember]
                      每个元素对应 SubselectTable.entries 里的一个 body 索引
    active_member_index : 当前激活的 member 序号（供 template_list 使用）
    """
    table_type_str: StringProperty(
        name="Table Type",
        description="SubselectTable.table_type (uint32, decimal string)",
        default="0",
    )

    unkn0_str: StringProperty(
        name="unkn0",
        description="SubselectTable.unkn0 three uint32, comma-separated decimal",
        default="0,0,0",
    )

    members: CollectionProperty(
        name="Members",
        description="List of EFX_BODY referenced by this Subselect table (corresponds to entries[])",
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
    """
    把解析好的 SubselectTable 内容写入 ss_obj.efx_subselect PropertyGroup。

    参数
    ----
    ss_obj : bpy.types.Object
        EFX_SUBSELECT Empty 对象（将被写入 .efx_subselect）。
    tbl : SubselectTable
        已解析的 SubselectTable 数据对象（来自 efx_format/efxfile.py）。
    main_bodies_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_BODY bpy Object} 映射（由 import_efx_tree 构建）。
        用于将 tbl.entries 的整数索引解析为具体的 body 对象。

    副作用
    ------
    - 填写 ss_obj.efx_subselect.{table_type_str, unkn0_str, members}。
    - 保留自定义属性 raw_b64（由 io_tree 写入，作为 byte-perfect 回退）。
    """
    props = ss_obj.efx_subselect

    # ── table_type（uint32 → 十进制字符串）────────────────────────────────────
    props.table_type_str = str(tbl.table_type)

    # ── unkn0（3个 uint32 → 逗号分隔十进制字符串）────────────────────────────
    props.unkn0_str = ",".join(str(v) for v in tbl.unkn0)

    # ── members：按 entries 原序填入 PointerProperty ──────────────────────────
    props.members.clear()
    for entry_idx in tbl.entries:
        item = props.members.add()
        body_obj = main_bodies_by_index.get(entry_idx)
        if body_obj is not None:
            item.body_ptr = body_obj
        # 若找不到对应 body（异常情况），body_ptr 留 None
        # 导出时悬空成员会被跳过（见 export_subselect_table 的 TODO 注释）


# ─────────────────────────────────────────────────────────────────────────────
# §2b  导出：EFXSubselectProps → SubselectTable
# ─────────────────────────────────────────────────────────────────────────────

def export_subselect_table(ss_obj: bpy.types.Object,
                           body_index_map: dict):
    """
    从 EFX_SUBSELECT 对象重建 SubselectTable 数据对象。

    参数
    ----
    ss_obj : bpy.types.Object
        EFX_SUBSELECT Empty 对象。
    body_index_map : dict[bpy.types.Object, int]
        {EFX_BODY Object → Main 段局部 0-based index}，
        由 build_local_index_map(col_main, 'EFX_BODY') 构建。

    返回
    ----
    SubselectTable（来自 efx_format.efxfile）

    回退策略
    --------
    若 ss_obj 不存在 efx_subselect 属性（旧场景/兼容），
    则从自定义属性 raw_b64 还原原始字节（byte-perfect 回退）。

    悬空 member 处理（TODO）
    -----------------------
    body_ptr 为 None（指针悬空）的成员当前跳过（不写入 entries），
    以保证导出不崩溃。后续校验阶段应改为报错（BLUEPRINT §13 引用完整性检查）。
    """
    from ..efx_format.efxfile import SubselectTable

    try:
        props = ss_obj.efx_subselect
    except AttributeError:
        # 回退：直接走 raw_b64（不应发生在新导入的场景，但兼容旧 .blend）
        return _fallback_raw_subselect(ss_obj)

    # ── table_type ────────────────────────────────────────────────────────────
    try:
        table_type = int(str(props.table_type_str))
    except (ValueError, TypeError):
        return _fallback_raw_subselect(ss_obj)

    # ── unkn0（三个 uint32）──────────────────────────────────────────────────
    try:
        parts = str(props.unkn0_str).split(",")
        unkn0 = tuple(int(p) for p in parts)
        if len(unkn0) != 3:
            raise ValueError(f"unkn0 需要 3 个值，实际 {len(unkn0)}")
    except (ValueError, TypeError):
        return _fallback_raw_subselect(ss_obj)

    # ── entries：从 members 的 body_ptr 解析回局部整数索引 ──────────────────
    entries = []
    for item in props.members:
        body_obj = item.body_ptr
        if body_obj is None:
            # TODO: 后续校验阶段改为 raise ValueError 或 report ERROR，当前静默跳过
            continue
        local_idx = body_index_map.get(body_obj)
        if local_idx is None:
            # body_obj 不在当前文件的 Main 段里（极端情况：跨文件拖拽等）
            # TODO: 同上，后续改报错
            continue
        entries.append(local_idx)

    return SubselectTable(
        table_type=table_type,
        unkn0=unkn0,
        entries=entries,
    )


def _fallback_raw_subselect(ss_obj: bpy.types.Object):
    """
    兼容回退：从自定义属性 raw_b64 原样还原 SubselectTable（旧 opaque 路径）。
    用于 ss_obj 没有 efx_subselect PropertyGroup 数据的情况。
    """
    import base64
    from ..efx_format.efxfile import SubselectTable
    import struct

    raw = base64.b64decode(str(ss_obj["raw_b64"]))
    # 手动解析（与 efxfile._parse_subselect 逻辑一致）
    table_type = struct.unpack_from('<I', raw, 0)[0]
    unkn0 = struct.unpack_from('<3I', raw, 4)
    entry_count = struct.unpack_from('<i', raw, 16)[0]
    entries = list(struct.unpack_from(f'<{entry_count}i', raw, 20))
    return SubselectTable(table_type=table_type, unkn0=unkn0, entries=entries)


# ─────────────────────────────────────────────────────────────────────────────
# §3  面板算子：增删 Subselect 成员
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_subselect_member_add(Operator):
    """向当前 Subselect 表新增一个空成员（body_ptr 待用户指定）"""

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
            # 激活序号钳制
            props.active_member_index = min(idx, max(0, len(props.members) - 1))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §3a  UIList：Subselect 成员列表
# ─────────────────────────────────────────────────────────────────────────────

class EFX_UL_subselect_members(bpy.types.UIList):
    """
    UIList 显示 EFXSubselectMember 列表。
    每行显示：序号 + body_ptr 指向的对象名（悬空时显示 <未设置>）。
    """

    bl_idname = "EFX_UL_subselect_members"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index}:", icon="BLANK1")
        body_obj = item.body_ptr
        if body_obj is not None:
            row.prop(item, "body_ptr", text="", icon="OBJECT_DATA")
        else:
            # 悬空状态：显示可编辑的指针槽（允许用户选择）
            row.prop(item, "body_ptr", text=T("sub.unset"), icon="ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# §3b  面板：N 面板 EFX 标签 Subselect 成员编辑
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_subselect(bpy.types.Panel):
    """
    Subselect 归属面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_SUBSELECT 对象时显示：
      - table_type / unkn0 元数据（只读显示，显示原始十进制字符串）
      - members 列表（可编辑：增删成员、改 body_ptr 指向）
      - 当前成员的 body_ptr 对象名（方便确认指向）

    设计理念（CLAUDE §4）：
      Subselect ↔ body 归属关系是结构关系（工具功能），放 N 面板，不放属性编辑器。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Subselect Ownership"
    bl_parent_id   = "EFX_PT_main"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_SUBSELECT"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_subselect
        except AttributeError:
            layout.label(text=T("sub.no_data"), icon="ERROR")
            return

        # ── 元数据行（只读显示）────────────────────────────────────────────────
        meta_box = layout.box()
        meta_box.label(text=T("sub.table_meta"), icon="INFO")
        row = meta_box.row()
        row.label(text=f"Table Type: {props.table_type_str}")
        row2 = meta_box.row()
        row2.label(text=f"unkn0: [{props.unkn0_str}]")

        layout.separator()

        # ── members 列表 ────────────────────────────────────────────────────────
        list_box = layout.box()
        list_box.label(text=f"{T('sub.members')}({len(props.members)})", icon="OUTLINER_OB_EMPTY")

        # template_list：UIList + 增删按钮
        row = list_box.row()
        row.template_list(
            "EFX_UL_subselect_members",   # UIList bl_idname
            "",                            # list_id（空字符串即可）
            props,                         # data（含 members 的 PropertyGroup）
            "members",                     # propname（CollectionProperty 字段名）
            props,                         # active_data
            "active_member_index",         # active_propname
            rows=4,
        )

        # 增删按钮列（右侧垂直排列）
        col = row.column(align=True)
        col.operator("efx.subselect_member_add",    text="", icon="ADD")
        col.operator("efx.subselect_member_remove", text="", icon="REMOVE")

        # ── 激活成员详情 ─────────────────────────────────────────────────────────
        idx = props.active_member_index
        if 0 <= idx < len(props.members):
            active_item = props.members[idx]
            detail_row = list_box.row()
            detail_row.prop(active_item, "body_ptr", text=T("sub.body_object"))

        # ── 悬空成员警告 ─────────────────────────────────────────────────────────
        dangling = sum(1 for m in props.members if m.body_ptr is None)
        if dangling > 0:
            warn_row = layout.row()
            warn_row.alert = True
            warn_row.label(
                text=f"⚠ {dangling} {T('sub.members_dangling')}",
                icon="ERROR",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 注册顺序：PropertyGroup 子类先于容器类；UIList/Operator 次之；
# EFX_PT_subselect 依赖 EFX_PT_main（bl_parent_id），故单独由 panels.py 注册。
_CLASSES_CORE = (
    EFXSubselectMember,
    EFXSubselectProps,
    EFX_UL_subselect_members,
    EFX_OT_subselect_member_add,
    EFX_OT_subselect_member_remove,
)

# EFX_PT_subselect 导出给 panels.py，由 panels.register() 在 EFX_PT_main 之后注册。
# 这样确保 bl_parent_id = "EFX_PT_main" 的父面板已存在。


def register():
    """
    注册 Subselect 核心类（PropertyGroup + UIList + Operator）。
    并把 EFXSubselectProps 挂到 Object 上。

    注意：EFX_PT_subselect 面板由 panels.py 在 EFX_PT_main 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_subselect = PointerProperty(
        name="EFX Subselect Properties",
        description="Structured Subselect data for the EFX_SUBSELECT object",
        type=EFXSubselectProps,
    )


def unregister():
    """
    注销 Subselect 核心类并清理 PointerProperty。
    EFX_PT_subselect 由 panels.py 先注销。
    """
    try:
        del bpy.types.Object.efx_subselect
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
