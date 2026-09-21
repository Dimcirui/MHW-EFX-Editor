"""创建 Action、Extern 与 Subselect 段条目。

维护约束：
- 新对象使用最小合法结构和段内索引，并设置相应脏标记。导出端依据实际对象
  重算各段计数和标签表；Subselect 变更时另外重算 subselect_size。
- Action 创建时包含一个初始 PlayEmitter 或 PlayEFX Entry。
- Entry 的创建统一由 add_ops.py 负责，并要求提供完整结构；本模块不创建零属性 Entry。
- Action、Extern 与 Entry 的标签构成全局连续前缀。新增 Action 或 Extern 仅在此前
  全局条目均有标签时自动获得标签；Subselect 不参与标签表。
- Extern 从零 item 的 ExternAttribute 开始；item 的类型与初始数据由
  extern_props.py 按需创建。
"""

import base64
import struct

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .i18n import T
from .add_ops import get_active_efx_root
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 模板常量
# ─────────────────────────────────────────────────────────────────────────────

# 新建条目的种子字节。
# `unkn[N]` 是社区 EFX_Play.bt 的下标，只为对照模板时溯源，不代表该槽仍未知。

# PlayEmitter raw[0:28]：
#   @0  Type Flags        = 2    作用未知。
#   @4  SetLandAttribute  = 0    取命中地面的属性，供按标志位过滤特效
#   @8  SetLandDirection  = 0    让生成实例的矩阵贴合地面倾斜
#   @12 Order             = 4    ZXY
#   @16/20/24 Rotation XYZ = 0.0 float
_BLANK_EMITTER_UNKN7 = bytes.fromhex(
    "02000000000000000000000004000000000000000000000000000000"
)

# PlayEFX raw：64B 固定段 + 1B 路径终止符。槽位布局与 PlayEmitter 同构，多一个 @8 Type。
# 下列非零常量是**必须**的——语料里这些槽没有一例为 0，填 0 的条目游戏内大概率不生效。
_BLANK_PLAYEFX_RAW = (
    struct.pack('<i', 1)                 # @0  Type Flags（unkn0）
    + struct.pack('<i', 1)               # @4  path_len = 1（null path）
    + struct.pack('<I', 1082828692)      # @8  Type = 0x408AA794
    + b'\x00' * 8                        # @12 SetLandAttribute / @16 SetLandDirection
    + struct.pack('<i', 2)               # @20 Unknown 2（unkn[2]）
    + b'\x00' * 12                       # @24/28/32 Rotation X/Y/Z（unkn[3..5]）
    + struct.pack('<i', 4)               # @36 Order（unkn[6]）= 4 ZXY
    + struct.pack('<3f', 1.0, 1.0, 1.0)  # @40 Scale
    + b'\x00' * 12                       # @52 Translate（属性标识符 pefx_null 是 BT 错名）
    + b'\x00'                            # @64 path[1] = null terminator
)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _nn(idx: int) -> str:
    """零填充 2 位序号（>99 不填充），与 io_tree.py / delete_ops.py 命名规则一致。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _sorted_children(root_obj, type_tag):
    """收集 root_obj（顶层文件集合）下 ~TYPE==type_tag 的顶层对象，按 efx_index 升序。"""
    return _rc.collect_top_level(root_obj, type_tag)


def _next_index(root_obj, type_tag) -> int:
    """该段现有最大 efx_index + 1（空段 → 0）。"""
    mx = -1
    for o in _sorted_children(root_obj, type_tag):
        try:
            mx = max(mx, int(o.get("efx_index", 0)))
        except (ValueError, TypeError):
            pass
    return mx + 1


_SUFFIX_TO_TYPE = {
    "_0 Action":    "EFX_ACTION",
    "_1 Extern":    "EFX_EXTERN",
    "_2 Entry":     "EFX_ENTRY",
    "_3 Subselect": "EFX_SUBSELECT",
}


def _section_collection(root_obj, suffix: str):
    """
    找 root_obj（顶层文件集合）下对应 suffix 段的叶子集合（按 ~TYPE 标记）；
    找不到则按 <stem><suffix> 新建（~TYPE + efx_root_ptr 反向指针一并设好）。
    """
    type_tag = _SUFFIX_TO_TYPE.get(suffix)
    if type_tag is None:
        return None
    stem = root_obj.name
    if stem.lower().endswith(".efx"):
        stem = stem[:-4]
    return _rc.ensure_leaf_collection(stem + suffix, root_obj, type_tag)


def _new_empty(name: str, collection) -> bpy.types.Object:
    """建 Empty 对象（与 io_tree._new_empty 一致）。"""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    collection.objects.link(obj)
    return obj


def _all_labeled(objs) -> bool:
    """objs 是否全部 efx_has_label==1（缺省 1，与导出标签重建默认一致）。"""
    return all(int(o.get("efx_has_label", 1)) == 1 for o in objs)


def _select_only(context, obj) -> None:
    """取消其它选择，选中并激活 obj。"""
    try:
        for o in context.selected_objects:
            o.select_set(False)
    except Exception:
        pass
    obj.select_set(True)
    context.view_layer.objects.active = obj


# ─────────────────────────────────────────────────────────────────────────────
# 核心：新建各段条目
# ─────────────────────────────────────────────────────────────────────────────

def add_subselect(root_obj) -> bpy.types.Object:
    """
    新建一个空白 Subselect 表（0 成员）。成员由用户在面板里增删。

    subselect 不在标签表内，故只需：建对象 + raw_b64 + init props + 置 subselect_dirty。
    导出端：count_subselect=len(对象) 自动重算；subselect_dirty=1 → subselect_size 重算。
    """
    from ..efx_format.efxfile import SubselectTable
    from . import subselect as _subselect

    col = _section_collection(root_obj, "_3 Subselect")
    if col is None:
        raise RuntimeError("找不到/无法新建 Subselect 集合")

    idx = _next_index(root_obj, "EFX_SUBSELECT")
    # table_type 智能默认 = 下一个槽位 bit（1,2,4,8…）
    n_existing = len(_sorted_children(root_obj, "EFX_SUBSELECT"))
    next_bit = (1 << n_existing) if n_existing < 32 else 1   # 溢出兜底
    tbl = SubselectTable(table_type=next_bit, unkn0=(0xFFFFFFFF, 0, 0), entries=[])

    obj = _new_empty(f"{_nn(idx)} subselect_{idx}", col)
    obj["~TYPE"]     = "EFX_SUBSELECT"
    obj["efx_index"] = idx
    obj["raw_b64"]   = _b64enc(tbl.serialize())

    try:
        _subselect.init_subselect_props(obj, tbl, {})
    except Exception:
        pass

    root_obj["subselect_dirty"] = 1
    return obj


def add_action(root_obj, entry_type='PLAYEMITTER') -> bpy.types.Object:
    """
    新建一个 Action：含 1 个初始 entry，类型由 entry_type 决定。
      'PLAYEMITTER'：空白 PlayEmitter（0 targets，xyz=1,1,1）
      'PLAYEFX'    ：空白 PlayEFX（path=""，xyz=1,1,1）
    targets / 路径由用户在 Action 面板里接线。
    """
    from ..efx_format.efxfile import ActionData, ActionEntry
    from ..efx_format.hashes import PLAYEMITTER, PLAYEFX
    from . import action_emitter as _action_emitter

    col = _section_collection(root_obj, "_0 Action")
    if col is None:
        raise RuntimeError("找不到/无法新建 Action 集合")

    idx = _next_index(root_obj, "EFX_ACTION")

    if entry_type == 'PLAYEFX':
        first_entry = ActionEntry(type_hash=PLAYEFX, raw=_BLANK_PLAYEFX_RAW)
    else:
        emitter_raw = (_BLANK_EMITTER_UNKN7
                       + struct.pack("<3f", 1.0, 1.0, 1.0)
                       + b"\x00" * 12
                       + struct.pack("<i", 0))
        first_entry = ActionEntry(type_hash=PLAYEMITTER, raw=emitter_raw)

    # 标签前缀规则：新 action 追加在 action 组末尾，前面=现有所有 action。
    has_label = _all_labeled(_sorted_children(root_obj, "EFX_ACTION"))
    raw_label = f"action_{idx}"

    # play_type = jamcrc(action 名)；重命名时由 EFX_OT_rename_action_extern 同步重算。
    from ..efx_format.hashes import jamcrc
    pd = ActionData(play_type=jamcrc(raw_label), entries=[first_entry])

    obj = _new_empty(f"{_nn(idx)} {raw_label}", col)
    obj["~TYPE"]         = "EFX_ACTION"
    obj["efx_index"]     = idx
    obj["efx_raw_label"] = raw_label
    obj["efx_has_label"] = int(has_label)
    obj["raw_b64"]       = _b64enc(pd.serialize())

    try:
        _action_emitter.init_action_props(obj, pd, {})
    except Exception:
        pass

    root_obj["labels_dirty"] = 1
    return obj


def add_extern(root_obj) -> bpy.types.Object:
    """
    新建一个零 item 的 Extern 容器。

    Extern 的 item 类型和数据只能由 extern_props.py 创建；其覆盖辅助入口会同时
    建立对应的 EXTERNREFERENCE。
    """
    col = _section_collection(root_obj, "_1 Extern")
    if col is None:
        raise RuntimeError("找不到/无法新建 Extern 集合")

    idx = _next_index(root_obj, "EFX_EXTERN")

    # 标签前缀规则：新 extern 追加在 extern 组末尾，前面=所有 action + 现有 extern。
    before = _sorted_children(root_obj, "EFX_ACTION") + _sorted_children(root_obj, "EFX_EXTERN")
    has_label = _all_labeled(before)
    raw_label = f"extern_{idx}"

    from ..efx_format.hashes import jamcrc as _jamcrc
    attr_type = _jamcrc(raw_label)

    obj = _new_empty(f"{_nn(idx)} {raw_label}", col)
    obj["~TYPE"]         = "EFX_EXTERN"
    obj["efx_index"]     = idx
    obj["efx_raw_label"] = raw_label
    obj["efx_has_label"] = int(has_label)

    # 空白 ExternAttribute：只有 16B header（attr_type/null0/item_count=0/null1），
    # 与 export_extern_data 的 header 格式（struct.pack('<IiIi', ...)）完全一致。
    raw_b64 = _b64enc(struct.pack('<IiIi', attr_type, 0, 0, 0))
    obj["raw_b64"] = raw_b64

    ep = obj.efx_extern
    ep.attr_type_str = str(attr_type)
    ep.null0 = 0
    ep.null1 = 0
    ep.active_instance = 0
    ep.items.clear()
    ep.raw_b64 = raw_b64

    root_obj["labels_dirty"] = 1
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_action(Operator):
    """在 Active EFX 下新建一个 Action，弹窗选择首条目类型"""

    bl_idname      = "efx.add_action"
    bl_label       = "Add Action"
    bl_description = ("Create a new Action; a dialog lets you choose PlayEmitter or PlayEFX "
                      "as the first entry. The exporter recomputes the header and label table automatically.")
    bl_options     = {"REGISTER", "UNDO"}

    entry_type: EnumProperty(
        name="Entry Type",
        description="Type of the first entry in the new Action",
        items=[
            ('PLAYEMITTER', "PlayEmitter", "Internal entry reference (targets[] pointing to Main entries)"),
            ('PLAYEFX',     "PlayEFX",     "External .efx file call (path + XYZ offset)"),
        ],
        default='PLAYEMITTER',
    )

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "entry_type")

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_action(root, self.entry_type)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add this Action. See the system console for details.")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Action: {obj.name}")
        return {"FINISHED"}


class EFX_OT_add_extern(Operator):
    """在 Active EFX 下新建一个空白 Extern（0 item），item 在其属性面板里再加"""

    bl_idname      = "efx.add_extern"
    bl_label       = "Add Extern"
    bl_description = ("Create a new empty Extern (0 items); add items of a specific type "
                      "later from its Extern Properties panel.")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_extern(root)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add this Extern. See the system console for details.")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Extern: {obj.name}")
        return {"FINISHED"}


class EFX_OT_add_subselect(Operator):
    """在 Active EFX 下新建一个 Subselect 表（空成员，成员在面板里增删）"""

    bl_idname      = "efx.add_subselect"
    bl_label       = "Add Subselect"
    bl_description = ("Create a new empty Subselect table; add member entries in its panel. "
                      "The exporter recomputes count_subselect and subselect_size automatically")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_subselect(root)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add this Subselect. See the system console for details.")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Subselect: {obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_add_action,
    EFX_OT_add_extern,
    EFX_OT_add_subselect,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
