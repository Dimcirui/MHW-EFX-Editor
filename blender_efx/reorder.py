"""
blender_efx/reorder.py  —  L2 #3a：entry / attribute 的重排（上移/下移）

算子：
  efx.move_entry  —  对 EFX_ENTRY 对象执行上移/下移（direction='UP'/'DOWN'）
  efx.move_attribute —  对 EFX_ATTRIBUTE 对象执行上移/下移（direction='UP'/'DOWN'）

设计要点：
  1. 重排只交换相邻对象的 efx_index——导出时 export_efx_tree 已按 efx_index 排序，
     引用指针化也是导出时经"对象→段局部 index"映射重算，因此重排无需做任何指针修改。
  2. 交换后必须重建两个对象的显示名 NN 前缀（大纲显示顺序由名字前缀控制）。
     显示名格式（见 io_tree.py 命名规则）：
       entry：  "{nn} {raw_label}"
       attribute：    "[{parent_label}] {nn} {type_name}"
  3. 原始标签/类型名从对象的自定义属性 efx_raw_label（entry）/ type_hash（attribute）读取，
     导入时写入；类型名通过 HASH_TO_NAME 查询。
  4. byte-perfect：重排→排回 ≡ 没有重排，efx_index 换回原值、名字前缀重生成
     结果与原导入完全一致，导出字节不变。

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集
  - 不改 efx_format/，不改 io_tree.py
  - bl_options = {"REGISTER", "UNDO"}
"""

import bpy
from bpy.props import EnumProperty

from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数：收集同级对象、重建显示名
# ─────────────────────────────────────────────────────────────────────────────

def _collect_siblings_by_type(parent_obj: bpy.types.Object, type_tag: str) -> list:
    """
    收集 parent_obj 的直接子对象中 ~TYPE == type_tag 的全部对象，
    按 efx_index 升序排列后返回。
    """
    result = []
    for obj in bpy.data.objects:
        if obj.parent == parent_obj and obj.get("~TYPE") == type_tag:
            result.append(obj)
    result.sort(key=lambda o: int(o.get("efx_index", 0)))
    return result


def _hash_display_name(type_hash: int) -> str:
    """用 hash 查已知属性类型名；未注册的用 0x 十六进制。"""
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        return HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")
    except (ImportError, Exception):
        return f"0x{type_hash:08X}"


def _entry_renderer_suffix(entry_obj) -> str:
    """扫描 entry_obj 现有 EFX_ATTRIBUTE 子对象（按 efx_index 序），返回渲染主体
    后缀（如 " (Mesh)"），见 efx_format.categories.renderer_suffix。entry_obj 为
    None 时返回空串（供导入期还没有子对象的路径复用同一签名）。"""
    if entry_obj is None:
        return ""
    from ..efx_format import categories as _cat
    children = [o for o in bpy.data.objects
                if o.parent == entry_obj and o.get("~TYPE") == "EFX_ATTRIBUTE"]
    children.sort(key=lambda o: int(o.get("efx_index", 0)))
    type_hashes = []
    for o in children:
        try:
            type_hashes.append(int(str(o.get("type_hash", "0"))))
        except (ValueError, TypeError):
            pass
    return _cat.renderer_suffix(type_hashes)


def _entry_display_name(efx_index: int, raw_label: str, entry_obj=None) -> str:
    """
    按 io_tree.py 规则生成 entry 的显示名："{nn} {raw_label}{renderer_suffix}"。
    nn 是零填充 2 位序号（>99 时自动扩展）。entry_obj 给出时附加渲染主体后缀
    （见 _entry_renderer_suffix），不给出时省略（如未建子对象前的场景）。
    """
    nn = str(efx_index).zfill(2) if efx_index < 100 else str(efx_index)
    suffix = _entry_renderer_suffix(entry_obj)
    return f"{nn} {raw_label}{suffix}"


def _attribute_display_name(efx_index: int, parent_label: str, type_name: str) -> str:
    """
    按 io_tree.py 规则生成属性的显示名：
      有父标签：  "[{parent_label}] {nn} {type_name}"
      无父标签：  "{nn} {type_name}"

    type_name 在此转成正常大小写显示形式（如 "TRANSFORM2D" → "Transform2D"）——
    仅影响这里拼出的显示字符串，不影响调用方传入的原始值（efx_type_name 等内部
    标识仍保持大写，见 efx_format.hashes.pretty_type_name）。
    """
    from ..efx_format.hashes import pretty_type_name
    nn = str(efx_index).zfill(2) if efx_index < 100 else str(efx_index)
    display_name = pretty_type_name(type_name)
    if parent_label:
        return f"[{parent_label}] {nn} {display_name}"
    else:
        return f"{nn} {display_name}"


def _get_entry_raw_label(entry_obj: bpy.types.Object) -> str:
    """
    从 entry 对象获取原始标签（不含 NN 前缀）。

    优先读 efx_raw_label 自定义属性（导入时写入）；
    若不存在则从现有名字中解析（去掉 "NN " 前缀）。
    """
    # 优先用 efx_raw_label（若已存）
    raw = entry_obj.get("efx_raw_label")
    if raw is not None:
        return str(raw)

    # 从现有名字中去掉 "NN " 前缀（NN 是 1 位或多位数字）
    name = entry_obj.name
    # 去掉 Blender 自动加的 .001 后缀
    if "." in name:
        name = name.rsplit(".", 1)[0]

    import re
    m = re.match(r'^\d+\s+(.*)', name)
    if m:
        return m.group(1)
    return name


def _get_attribute_type_name(block_obj: bpy.types.Object) -> str:
    """
    从属性对象获取类型名（如 "EMITTERSHAPE3D"）。

    优先读 efx_type_name 自定义属性（导入时写入）；
    若不存在则从 type_hash 查表；若均无则从现有名字中解析。
    """
    # 优先用 efx_type_name（若已存）
    stored = block_obj.get("efx_type_name")
    if stored is not None:
        return str(stored)

    # 从 type_hash 查表
    type_hash_str = block_obj.get("type_hash")
    if type_hash_str is not None:
        try:
            return _hash_display_name(int(str(type_hash_str)))
        except (ValueError, TypeError):
            pass

    # 从现有名字解析（去掉 "[xxx] NN " 前缀）
    name = block_obj.name
    if "." in name:
        name = name.rsplit(".", 1)[0]

    import re
    # 格式："[parent_label] NN type_name" 或 "NN type_name"
    m = re.match(r'^\[.*?\]\s+\d+\s+(.*)', name)
    if m:
        return m.group(1)
    m = re.match(r'^\d+\s+(.*)', name)
    if m:
        return m.group(1)
    return name


def _get_attribute_parent_label(block_obj: bpy.types.Object) -> str:
    """
    获取属性对象所属 entry 的原始标签（方括号内的部分）。

    优先从父 EFX_ENTRY 对象的 efx_raw_label 或显示名解析。
    """
    parent = block_obj.parent
    if parent is not None and parent.get("~TYPE") == "EFX_ENTRY":
        return _get_entry_raw_label(parent)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 顶层带标签条目（entry / action / extern）通用重排核心
#
# 三者命名同格式 "{nn} {efx_raw_label}"、parent 都是 EFX_ROOT、都活在
# [Action|Extern|Entry] 全局标签前缀里。重排要正确必须：
#   1. 标签前缀守卫：相邻两条 efx_has_label 不同 → 拒绝（交换会破坏"有标签条目是
#      连续前缀"的不变量，导出重建标签表会错位）。
#   2. 交换 efx_index + 重建显示名。
#   3. 若任一条有标签 → 置 root["labels_dirty"]=1，使导出按新顺序重建标签表
#      （否则导出发原始 verbatim 标签字节＝旧顺序，标签会贴到错误条目上）。
# ─────────────────────────────────────────────────────────────────────────────

def _move_labeled_entry(obj, direction: str, type_tag: str, report) -> set:
    """
    上移/下移顶层带标签条目（EFX_ENTRY / EFX_ACTION / EFX_EXTERN）。

    重构（结构权威下放）：从"交换两个 efx_index"改为"列表重排 + 全组重编号"——
      1. 同级按 (efx_index, name) 稳定排序成列表（撞车的两个副本靠 name 拆成确定前后）；
      2. 目标与相邻项交换列表位置；
      3. 全组按新列表顺序重赋 efx_index = 0..n-1 + 重建显示名。
    这样：① 永不"转移失败"（同名同 index 也已被 name 拆序，必动）；
         ② 永不留撞车（末尾恒 0..n-1 唯一）——撞车不再是需处理的 case。
    满命名后所有条目都在标签表内，原"标签前缀守卫"作废，已移除。
    """
    from . import normalize
    root = _rc.find_root_collection(obj)
    if root is None:
        report({"ERROR"}, "EFX_ROOT not found")
        return {"CANCELLED"}

    sibs = normalize._collect_group(root, type_tag)  # (efx_index, name) 稳定序
    if len(sibs) < 2:
        report({"INFO"}, "Only 1 entry, cannot move")
        return {"CANCELLED"}

    try:
        pos = sibs.index(obj)
    except ValueError:
        report({"ERROR"}, "Cannot find current entry's position in the sibling list")
        return {"CANCELLED"}

    if direction == "UP":
        if pos == 0:
            report({"INFO"}, "Already at the top, cannot move up")
            return {"CANCELLED"}
        npos = pos - 1
    else:
        if pos == len(sibs) - 1:
            report({"INFO"}, "Already at the bottom, cannot move down")
            return {"CANCELLED"}
        npos = pos + 1

    # 交换列表位置 → 全组重赋 efx_index=0..n-1 + 重建显示名
    sibs[pos], sibs[npos] = sibs[npos], sibs[pos]
    for i, o in enumerate(sibs):
        o["efx_index"] = i
        try:
            o.name = normalize._display_name(o, type_tag, i)
        except Exception:
            pass

    # 顶层条目在标签表内 → 顺序变，导出需按新序重建标签表
    root["labels_dirty"] = 1

    dir_str = "up" if direction == "UP" else "down"
    report({"INFO"}, f"Moved {dir_str}: {obj.name}")
    return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_entry  —  entry 上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_entry(bpy.types.Operator):
    """上移或下移选中的 EFX_ENTRY（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_entry"
    bl_label       = "Move Entry"
    bl_description = "Move the selected EFX_ENTRY up or down within the Main section"
    bl_options     = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        description="Move direction",
        items=[
            ("UP",   "Up", "Move forward (index decreases)"),
            ("DOWN", "Down", "Move backward (index increases)"),
        ],
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        """仅当 active_object 是 EFX_ENTRY 时启用。"""
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            return False
        # 需要能解析出所属文件集合才能找同级
        return _rc.find_root_collection(obj) is not None

    def execute(self, context):
        return _move_labeled_entry(context.active_object, self.direction, "EFX_ENTRY", self.report)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_attribute  —  属性上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_attribute(bpy.types.Operator):
    """上移或下移选中 EFX_ENTRY 内的 EFX_ATTRIBUTE（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_attribute"
    bl_label       = "Move Attribute"
    bl_description = "Move the selected EFX_ATTRIBUTE up or down within the same EFX_ENTRY"
    bl_options     = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        description="Move direction",
        items=[
            ("UP",   "Up", "Move forward (index decreases)"),
            ("DOWN", "Down", "Move backward (index increases)"),
        ],
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        """仅当 active_object 是 EFX_ATTRIBUTE 时启用。"""
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        # 需要有父 EFX_ENTRY
        parent = obj.parent
        return parent is not None and parent.get("~TYPE") == "EFX_ENTRY"

    def execute(self, context):
        # 重构：列表重排 + 全组重编号（同 _move_labeled_entry），撞车/失败均不可能。
        from . import normalize
        obj = context.active_object
        body = obj.parent  # EFX_ENTRY

        # 同一 entry 下的 EFX_ATTRIBUTE 按 (efx_index, name) 稳定排序
        sibs = [o for o in bpy.data.objects
                if o.parent == body and o.get("~TYPE") == "EFX_ATTRIBUTE"]
        sibs.sort(key=lambda o: (int(o.get("efx_index", 0)), o.name))
        if len(sibs) < 2:
            self.report({"INFO"}, "Only 1 attribute, cannot move")
            return {"CANCELLED"}

        try:
            pos = sibs.index(obj)
        except ValueError:
            self.report({"ERROR"}, "Cannot find current attribute's position in the sibling list")
            return {"CANCELLED"}

        if self.direction == "UP":
            if pos == 0:
                self.report({"INFO"}, "Already at the top, cannot move up")
                return {"CANCELLED"}
            npos = pos - 1
        else:  # DOWN
            if pos == len(sibs) - 1:
                self.report({"INFO"}, "Already at the bottom, cannot move down")
                return {"CANCELLED"}
            npos = pos + 1

        # 交换列表位置 → 全组重赋 efx_index=0..n-1 + 重建显示名
        sibs[pos], sibs[npos] = sibs[npos], sibs[pos]
        for i, o in enumerate(sibs):
            o["efx_index"] = i
            try:
                o.name = normalize._display_name(o, "EFX_ATTRIBUTE", i)
            except Exception:
                pass

        dir_str = "up" if self.direction == "UP" else "down"
        self.report({"INFO"}, f"EFX_ATTRIBUTE moved {dir_str}: {obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_action_extern  —  Action / Extern 上移/下移（与 entry 同源核心）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_action_extern(bpy.types.Operator):
    """上移或下移选中的 EFX_ACTION / EFX_EXTERN（交换 efx_index、重建显示名、
    跨标签边界守卫 + labels_dirty）。引用（PTLIFE/PTCOLLISION→action、
    ExternReference→extern）均已指针化，导出按段局部 index 自动重算，重排安全。"""

    bl_idname      = "efx.move_action_extern"
    bl_label       = "Move Entry"
    bl_description = "Move the selected Action/Extern up or down within its segment"
    bl_options     = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        description="Move direction",
        items=[
            ("UP",   "Up", "Move forward (index decreases)"),
            ("DOWN", "Down", "Move backward (index increases)"),
        ],
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None
                and obj.get("~TYPE") in ("EFX_ACTION", "EFX_EXTERN")
                and _rc.find_root_collection(obj) is not None)

    def execute(self, context):
        obj = context.active_object
        return _move_labeled_entry(obj, self.direction, obj.get("~TYPE"), self.report)


# ─────────────────────────────────────────────────────────────────────────────
# entry 命名能力判定 + EFX_OT_rename_entry
# ─────────────────────────────────────────────────────────────────────────────

def can_label_entry(obj) -> bool:
    """
    该 entry 能否安全获得/拥有标签槽。

    EFX 标签表是 [Action|Extern|Entry] 全局顺序的**连续前缀**。一个 entry 要有标签，
    它前面的所有条目（action/extern + 在它之前的 entry）必须都已有标签——否则给它
    标签会让标签错位（落到前面那个无标签条目上）。

    返回 True 表示：它已在前缀内（has_label=1），或恰好在前缀边界（前面全有标签，
    可安全扩展前缀把它纳入）。
    """
    if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
        return False
    if int(obj.get("efx_has_label", 0)) == 1:
        return True
    root = _rc.find_root_collection(obj)
    if root is None:
        return False

    def _children(type_tag):
        return _rc.collect_top_level(root, type_tag)

    bodies = _children("EFX_ENTRY")
    if obj not in bodies:
        return False
    bi = bodies.index(obj)
    before = _children("EFX_ACTION") + _children("EFX_EXTERN") + bodies[:bi]
    return all(int(e.get("efx_has_label", 0)) == 1 for e in before)


class EFX_OT_rename_entry(bpy.types.Operator):
    """重命名 EFX_ENTRY（改 EFX_Type 标签表里的名字，导出生效）

    标签表是 [Action|Extern|Entry] 顺序的连续前缀。可命名条件（can_label_entry）：
      - 已有标签（efx_has_label=1）→ 直接改名；
      - 或处于前缀边界（前面条目全有标签）→ 提升为有标签（has_label=1）。
    前面有无标签条目的 entry 不可命名（会破坏位置映射），面板会禁用。
    """

    bl_idname      = "efx.rename_entry"
    bl_label       = "Rename Entry"
    bl_description = "Change this entry's name in the EFX file label table (all preceding entries must have labels)"
    bl_options     = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="New Name",
        description="The entry's new label name (written to the EFX_Type label table)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return can_label_entry(context.active_object)

    def invoke(self, context, event):
        obj = context.active_object
        self.new_name = str(obj.get("efx_raw_label", ""))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        obj = context.active_object
        if not can_label_entry(obj):
            self.report({"ERROR"}, "This entry cannot be named (preceding unnamed entries would break the label position mapping)")
            return {"CANCELLED"}

        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "Name cannot be empty")
            return {"CANCELLED"}
        if "\x00" in new_name:
            self.report({"ERROR"}, "Name cannot contain NUL characters")
            return {"CANCELLED"}

        root = _rc.find_root_collection(obj)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found")
            return {"CANCELLED"}

        # 更新标签 + 提升为有标签 + 重建显示名 + 置 labels_dirty
        idx = int(obj.get("efx_index", 0))
        obj["efx_raw_label"] = new_name
        obj["efx_has_label"] = 1   # 边界 entry 提升为有标签
        obj.name = _entry_display_name(idx, new_name, entry_obj=obj)
        root["labels_dirty"] = 1

        # body_type = jamcrc(entry 名)（standard entry，实测 99.7%+ 命中，见
        # memory play-type-is-jamcrc-of-name）。用户手动改名 = 改身份，必须重算，
        # 否则名↔哈希不一致，按名字哈希定位该 entry 的外部工具会失效。
        # extended（body_type≡1）/ root（≡ROOT_MARKER）不是名字哈希，不动。
        if str(obj.get("entry_kind", "")) == "standard":
            try:
                from ..efx_format.hashes import jamcrc
                obj["body_type"] = str(jamcrc(new_name) & 0xFFFFFFFF)
            except Exception:
                pass

        self.report({"INFO"}, f"Renamed to: {new_name} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Action / Extern 重命名（与 entry 同理；解决"前导 action/extern 未命名锁死全体"的问题）
#
# EFX_Type 标签表是 [Action|Extern|Entry] 全局顺序的连续前缀。此前只有 entry 能重命名，
# 于是无标签文件里位于最前的 action/extern 永远无法获得标签 → 它后面的所有 entry 也
# 因 can_label_entry 的"前面条目须全有标签"而永久锁死。给 action/extern 加重命名后，
# 先命名前导 action/extern，entry 即随之解锁（前缀逐个向后扩展）。
# ─────────────────────────────────────────────────────────────────────────────

_LABELED_TYPES = ("EFX_ACTION", "EFX_EXTERN", "EFX_ENTRY")


def _global_ordered_entries(root):
    """root 下按 [Action|Extern|Entry] 全局顺序排列的有标签段条目（各段内按 efx_index）。"""
    return (_rc.collect_top_level(root, "EFX_ACTION")
            + _rc.collect_top_level(root, "EFX_EXTERN")
            + _rc.collect_top_level(root, "EFX_ENTRY"))


def can_label_action_extern(obj) -> bool:
    """
    通用版 can_label_entry：action / extern / entry 均适用。

    条件：已有标签（efx_has_label=1）→ True；否则处于标签前缀边界
    （[Action|Extern|Entry] 全局顺序里它前面的条目全部已有标签）→ True。
    """
    if obj is None or obj.get("~TYPE") not in _LABELED_TYPES:
        return False
    if int(obj.get("efx_has_label", 0)) == 1:
        return True
    root = _rc.find_root_collection(obj)
    if root is None:
        return False
    ordered = _global_ordered_entries(root)
    if obj not in ordered:
        return False
    pos = ordered.index(obj)
    return all(int(e.get("efx_has_label", 0)) == 1 for e in ordered[:pos])


class EFX_OT_rename_action_extern(bpy.types.Operator):
    """重命名 EFX_ACTION / EFX_EXTERN（改 EFX_Type 标签表里的名字，导出生效）

    可命名条件同 entry（can_label_action_extern）：已有标签，或处于标签前缀边界。
    显示名格式：'{nn} {label}'（与 io_tree / delete_ops 一致）。
    """

    bl_idname      = "efx.rename_action_extern"
    bl_label       = "Rename Entry"
    bl_description = "Change this Action/Extern's name in the EFX label table (all preceding entries must have labels)"
    bl_options     = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="New Name",
        description="The entry's new label name (written to the EFX_Type label table)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") in ("EFX_ACTION", "EFX_EXTERN") \
            and can_label_action_extern(obj)

    def invoke(self, context, event):
        obj = context.active_object
        self.new_name = str(obj.get("efx_raw_label", ""))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") not in ("EFX_ACTION", "EFX_EXTERN"):
            self.report({"ERROR"}, "Select an Action or Extern object")
            return {"CANCELLED"}
        if not can_label_action_extern(obj):
            self.report({"ERROR"}, "This entry cannot be named (preceding unnamed entries would break the label position mapping)")
            return {"CANCELLED"}

        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "Name cannot be empty")
            return {"CANCELLED"}
        if "\x00" in new_name:
            self.report({"ERROR"}, "Name cannot contain NUL characters")
            return {"CANCELLED"}

        root = _rc.find_root_collection(obj)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found")
            return {"CANCELLED"}

        idx = int(obj.get("efx_index", 0))
        nn = str(idx).zfill(2) if idx < 100 else str(idx)
        obj["efx_raw_label"] = new_name
        obj["efx_has_label"] = 1
        obj.name = f"{nn} {new_name}"
        root["labels_dirty"] = 1

        # play_type = jamcrc(action 名)（实测 5251/5251）。重命名 EFX_ACTION 必须同步
        # 重算 play_type，否则名↔哈希不一致，按名字哈希调用 action 的引用会失效。
        if obj.get("~TYPE") == "EFX_ACTION":
            try:
                from ..efx_format.hashes import jamcrc
                obj.efx_play.play_type_str = str(jamcrc(new_name))
            except Exception:
                pass

        self.report({"INFO"}, f"Renamed to: {new_name} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# auto_sort_entry_attributes  —  按规范顺序重排 entry 内属性
#
# ⚠ 顺序表已于 2026-08-18 整体替换。旧表来自 2026-06 的「中位归一化位置」统计，
#   与官方语料实际顺序冲突严重：拿它重排 official 语料，24.6% 的 entry（52.0% 的
#   文件）会被改动顺序，其中最大一处是 ALPHACORRECTION 排在 UVSEQUENCE 之前——
#   而语料里 7426 次都是 UVSEQUENCE 在前。由于本函数在导出前无条件跑（可用
#   auto_sort_attributes 关掉），旧表实际上会静默破坏这半数文件的 byte-perfect，
#   且 CLI 的两套 roundtrip 都走不到这条路径（不经过 io_tree/operators），测不出来。
#
# 现表下沉到 efx_format/categories.py::ATTRIBUTE_CANONICAL_ORDER（纯 Python，
# 零 bpy），由支配关系图拓扑排序得出，全语料仅 0.48% 的 entry 会被改动。
# 依据与统计口径见 docs/ATTRIBUTE_STATS.md「Entry 内属性的规范顺序」。
# ─────────────────────────────────────────────────────────────────────────────

def _build_attribute_sort_key_map() -> dict:
    """Lazy-build hash→sort_key；导入失败返回空字典（调用方退化为不排序）。"""
    try:
        from ..efx_format.categories import ATTRIBUTE_CANONICAL_ORDER
    except ImportError:
        return {}
    return dict(ATTRIBUTE_CANONICAL_ORDER)


_ATTRIBUTE_SORT_KEY_MAP = None  # lazy-initialized on first export


def auto_sort_entry_attributes(root_obj) -> int:
    """
    对 root_obj 下每个 entry 的 EFX_ATTRIBUTE 按规范顺序排序（就地修改 efx_index）。

    规范顺序表 = efx_format.categories.ATTRIBUTE_CANONICAL_ORDER（语料拓扑排序得出，
    见该文件顶部注释）。排序是**稳定**的：同 rank 或未知类型保持相互间的原有先后。

    只修改 efx_index；io_tree.export_efx_tree 按 efx_index 排序序列化，无需重建显示名。
    返回被重新排序的 entry 数量（未变动的 entry 不计）。

    ⚠ 规范顺序是惯例（官方语料 99.5% 符合）而非格式硬约束，本函数会改动那 0.48%
    本就"逆序"的官方 entry。导出算子的 auto_sort_attributes 开关可整体关掉。
    """
    global _ATTRIBUTE_SORT_KEY_MAP
    if _ATTRIBUTE_SORT_KEY_MAP is None:
        _ATTRIBUTE_SORT_KEY_MAP = _build_attribute_sort_key_map()
    sort_map = _ATTRIBUTE_SORT_KEY_MAP
    if not sort_map:
        return 0  # 表加载失败：不排序，保持用户原顺序
    try:
        from ..efx_format.categories import CANONICAL_ORDER_DEFAULT as _DEFAULT_KEY
    except ImportError:
        _DEFAULT_KEY = 999

    if root_obj is None:
        return 0

    modified = 0
    bodies = _rc.collect_top_level(root_obj, "EFX_ENTRY")
    for body in bodies:
        try:
            blocks = _collect_siblings_by_type(body, "EFX_ATTRIBUTE")
            if len(blocks) < 2:
                continue

            def _sort_key(blk, _sm=sort_map, _dk=_DEFAULT_KEY):
                try:
                    h = int(str(blk.get("type_hash", "0")))
                except (ValueError, TypeError):
                    return _dk
                return _sm.get(h, _dk)

            sorted_attributes = sorted(blocks, key=_sort_key)

            # 顺序已正确时跳过（避免无意义的属性写入）
            if all(b is s for b, s in zip(blocks, sorted_attributes)):
                continue

            modified += 1
            for new_idx, blk in enumerate(sorted_attributes):
                blk["efx_index"] = new_idx
        except Exception:
            pass  # 单个 entry 失败不阻断其余 entry

    return modified


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_move_entry,
    EFX_OT_move_attribute,
    EFX_OT_move_action_extern,
    EFX_OT_rename_entry,
    EFX_OT_rename_action_extern,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
