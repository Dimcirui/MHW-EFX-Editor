"""
blender_efx/reorder.py  —  L2 #3a：body / 块的重排（上移/下移）

算子：
  efx.move_body  —  对 EFX_BODY 对象执行上移/下移（direction='UP'/'DOWN'）
  efx.move_block —  对 EFX_BLOCK 对象执行上移/下移（direction='UP'/'DOWN'）

设计要点：
  1. 重排只交换相邻对象的 efx_index——导出时 export_efx_tree 已按 efx_index 排序，
     引用指针化也是导出时经"对象→段局部 index"映射重算，因此重排无需做任何指针修改。
  2. 交换后必须重建两个对象的显示名 NN 前缀（大纲显示顺序由名字前缀控制）。
     显示名格式（见 io_tree.py 命名规则）：
       body：  "{nn} {raw_label}"
       块：    "[{parent_label}] {nn} {type_name}"
  3. 原始标签/类型名从对象的自定义属性 efx_raw_label（body）/ type_hash（block）读取，
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
    """用 hash 查已知块类型名；未注册的用 0x 十六进制。"""
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        return HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")
    except (ImportError, Exception):
        return f"0x{type_hash:08X}"


def _body_display_name(efx_index: int, raw_label: str) -> str:
    """
    按 io_tree.py 规则生成 body 的显示名："{nn} {raw_label}"。
    nn 是零填充 2 位序号（>99 时自动扩展）。
    """
    nn = str(efx_index).zfill(2) if efx_index < 100 else str(efx_index)
    return f"{nn} {raw_label}"


def _block_display_name(efx_index: int, parent_label: str, type_name: str) -> str:
    """
    按 io_tree.py 规则生成块的显示名：
      有父标签：  "[{parent_label}] {nn} {type_name}"
      无父标签：  "{nn} {type_name}"
    """
    nn = str(efx_index).zfill(2) if efx_index < 100 else str(efx_index)
    if parent_label:
        return f"[{parent_label}] {nn} {type_name}"
    else:
        return f"{nn} {type_name}"


def _get_body_raw_label(body_obj: bpy.types.Object) -> str:
    """
    从 body 对象获取原始标签（不含 NN 前缀）。

    优先读 efx_raw_label 自定义属性（导入时写入）；
    若不存在则从现有名字中解析（去掉 "NN " 前缀）。
    """
    # 优先用 efx_raw_label（若已存）
    raw = body_obj.get("efx_raw_label")
    if raw is not None:
        return str(raw)

    # 从现有名字中去掉 "NN " 前缀（NN 是 1 位或多位数字）
    name = body_obj.name
    # 去掉 Blender 自动加的 .001 后缀
    if "." in name:
        name = name.rsplit(".", 1)[0]

    import re
    m = re.match(r'^\d+\s+(.*)', name)
    if m:
        return m.group(1)
    return name


def _get_block_type_name(block_obj: bpy.types.Object) -> str:
    """
    从块对象获取类型名（如 "EMITTERSHAPE3D"）。

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


def _get_block_parent_label(block_obj: bpy.types.Object) -> str:
    """
    获取块对象所属 body 的原始标签（方括号内的部分）。

    优先从父 EFX_BODY 对象的 efx_raw_label 或显示名解析。
    """
    parent = block_obj.parent
    if parent is not None and parent.get("~TYPE") == "EFX_BODY":
        return _get_body_raw_label(parent)
    return ""


def _swap_objects(obj_a: bpy.types.Object, obj_b: bpy.types.Object,
                  is_body: bool) -> None:
    """
    交换 obj_a 和 obj_b 的 efx_index，并重建两者的显示名。

    is_body=True  → body 规则；
    is_body=False → block 规则。
    """
    idx_a = int(obj_a.get("efx_index", 0))
    idx_b = int(obj_b.get("efx_index", 0))

    # 交换 efx_index
    obj_a["efx_index"] = idx_b
    obj_b["efx_index"] = idx_a

    # 重建显示名
    if is_body:
        label_a = _get_body_raw_label(obj_a)
        label_b = _get_body_raw_label(obj_b)
        obj_a.name = _body_display_name(idx_b, label_a)
        obj_b.name = _body_display_name(idx_a, label_b)
    else:
        parent_label_a = _get_block_parent_label(obj_a)
        parent_label_b = _get_block_parent_label(obj_b)
        type_name_a = _get_block_type_name(obj_a)
        type_name_b = _get_block_type_name(obj_b)
        obj_a.name = _block_display_name(idx_b, parent_label_a, type_name_a)
        obj_b.name = _block_display_name(idx_a, parent_label_b, type_name_b)


# ─────────────────────────────────────────────────────────────────────────────
# 顶层带标签条目（body / play / extern）通用重排核心
#
# 三者命名同格式 "{nn} {efx_raw_label}"、parent 都是 EFX_ROOT、都活在
# [Play|Extern|Main] 全局标签前缀里。重排要正确必须：
#   1. 标签前缀守卫：相邻两条 efx_has_label 不同 → 拒绝（交换会破坏"有标签条目是
#      连续前缀"的不变量，导出重建标签表会错位）。
#   2. 交换 efx_index + 重建显示名。
#   3. 若任一条有标签 → 置 root["labels_dirty"]=1，使导出按新顺序重建标签表
#      （否则导出发原始 verbatim 标签字节＝旧顺序，标签会贴到错误条目上）。
# ─────────────────────────────────────────────────────────────────────────────

def _move_labeled_entry(obj, direction: str, type_tag: str, report) -> set:
    """上移/下移顶层带标签条目（EFX_BODY / EFX_PLAY / EFX_EXTERN）。"""
    root = obj.parent
    if root is None:
        report({"ERROR"}, "EFX_ROOT not found")
        return {"CANCELLED"}

    siblings = _collect_siblings_by_type(root, type_tag)
    if len(siblings) < 2:
        report({"INFO"}, "Only 1 entry, cannot move")
        return {"CANCELLED"}

    cur_idx = next((i for i, s in enumerate(siblings) if s == obj), None)
    if cur_idx is None:
        report({"ERROR"}, "Cannot find current entry's position in the sibling list")
        return {"CANCELLED"}

    if direction == "UP":
        if cur_idx == 0:
            report({"INFO"}, "Already at the top, cannot move up")
            return {"CANCELLED"}
        neighbor = siblings[cur_idx - 1]
    else:
        if cur_idx == len(siblings) - 1:
            report({"INFO"}, "Already at the bottom, cannot move down")
            return {"CANCELLED"}
        neighbor = siblings[cur_idx + 1]

    # 标签前缀守卫
    if int(obj.get("efx_has_label", 0)) != int(neighbor.get("efx_has_label", 0)):
        report(
            {"WARNING"},
            "Cannot reorder across a label boundary: one entry has a label and the "
            "other does not — swapping would corrupt the positional label table. "
            "Name the unlabeled entry first, or move within a labeled/unlabeled group.",
        )
        return {"CANCELLED"}

    # 交换 efx_index + 重建显示名（顶层条目命名同 body 规则）
    idx_a = int(obj.get("efx_index", 0))
    idx_b = int(neighbor.get("efx_index", 0))
    obj["efx_index"] = idx_b
    neighbor["efx_index"] = idx_a
    obj.name = _body_display_name(idx_b, _get_body_raw_label(obj))
    neighbor.name = _body_display_name(idx_a, _get_body_raw_label(neighbor))

    # 任一有标签 → 导出需按新顺序重建标签表
    if int(obj.get("efx_has_label", 0)) or int(neighbor.get("efx_has_label", 0)):
        root["labels_dirty"] = 1

    dir_str = "up" if direction == "UP" else "down"
    report({"INFO"}, f"Moved {dir_str}: {obj.name} ↔ {neighbor.name}")
    return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_body  —  body 上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_body(bpy.types.Operator):
    """上移或下移选中的 EFX_BODY（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_body"
    bl_label       = "Move Body"
    bl_description = "Move the selected EFX_BODY up or down within the Main section"
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
        """仅当 active_object 是 EFX_BODY 时启用。"""
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BODY":
            return False
        # 需要有父对象（EFX_ROOT）才能找同级
        return obj.parent is not None

    def execute(self, context):
        return _move_labeled_entry(context.active_object, self.direction, "EFX_BODY", self.report)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_block  —  块上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_block(bpy.types.Operator):
    """上移或下移选中 EFX_BODY 内的 EFX_BLOCK（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_block"
    bl_label       = "Move Block"
    bl_description = "Move the selected EFX_BLOCK up or down within the same EFX_BODY"
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
        """仅当 active_object 是 EFX_BLOCK 时启用。"""
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
            return False
        # 需要有父 EFX_BODY
        parent = obj.parent
        return parent is not None and parent.get("~TYPE") == "EFX_BODY"

    def execute(self, context):
        obj = context.active_object
        body = obj.parent  # EFX_BODY

        # 收集同一 body 下的全部 EFX_BLOCK，已按 efx_index 升序排列
        siblings = _collect_siblings_by_type(body, "EFX_BLOCK")
        if len(siblings) < 2:
            self.report({"INFO"}, "Only 1 block, cannot move")
            return {"CANCELLED"}

        # 找当前块在列表中的位置
        cur_idx = None
        for i, sibling in enumerate(siblings):
            if sibling == obj:
                cur_idx = i
                break

        if cur_idx is None:
            self.report({"ERROR"}, "Cannot find current block's position in the sibling list")
            return {"CANCELLED"}

        if self.direction == "UP":
            if cur_idx == 0:
                self.report({"INFO"}, "Already at the top, cannot move up")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx - 1]
        else:  # DOWN
            if cur_idx == len(siblings) - 1:
                self.report({"INFO"}, "Already at the bottom, cannot move down")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx + 1]

        # 执行交换（efx_index + 显示名）
        _swap_objects(obj, neighbor, is_body=False)

        dir_str = "up" if self.direction == "UP" else "down"
        self.report(
            {"INFO"},
            f"EFX_BLOCK moved {dir_str}: {obj.name} ↔ {neighbor.name}",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_entry  —  Play / Extern 上移/下移（与 body 同源核心）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_entry(bpy.types.Operator):
    """上移或下移选中的 EFX_PLAY / EFX_EXTERN（交换 efx_index、重建显示名、
    跨标签边界守卫 + labels_dirty）。引用（PTLIFE/PTCOLLISION→play、
    ExternReference→extern）均已指针化，导出按段局部 index 自动重算，重排安全。"""

    bl_idname      = "efx.move_entry"
    bl_label       = "Move Entry"
    bl_description = "Move the selected Play/Extern up or down within its segment"
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
                and obj.get("~TYPE") in ("EFX_PLAY", "EFX_EXTERN")
                and obj.parent is not None)

    def execute(self, context):
        obj = context.active_object
        return _move_labeled_entry(obj, self.direction, obj.get("~TYPE"), self.report)


# ─────────────────────────────────────────────────────────────────────────────
# body 命名能力判定 + EFX_OT_rename_body
# ─────────────────────────────────────────────────────────────────────────────

def _find_root(obj):
    """沿 parent 链找 EFX_ROOT。"""
    cur = obj
    while cur is not None and cur.get("~TYPE") != "EFX_ROOT":
        cur = cur.parent
    return cur


def can_label_body(obj) -> bool:
    """
    该 body 能否安全获得/拥有标签槽。

    EFX 标签表是 [Play|Extern|Main] 全局顺序的**连续前缀**。一个 body 要有标签，
    它前面的所有条目（play/extern + 在它之前的 body）必须都已有标签——否则给它
    标签会让标签错位（落到前面那个无标签条目上）。

    返回 True 表示：它已在前缀内（has_label=1），或恰好在前缀边界（前面全有标签，
    可安全扩展前缀把它纳入）。
    """
    if obj is None or obj.get("~TYPE") != "EFX_BODY":
        return False
    if int(obj.get("efx_has_label", 0)) == 1:
        return True
    root = _find_root(obj)
    if root is None:
        return False

    def _children(type_tag):
        objs = [o for o in bpy.data.objects
                if o.parent == root and o.get("~TYPE") == type_tag]
        objs.sort(key=lambda o: int(o.get("efx_index", 0)))
        return objs

    bodies = _children("EFX_BODY")
    if obj not in bodies:
        return False
    bi = bodies.index(obj)
    before = _children("EFX_PLAY") + _children("EFX_EXTERN") + bodies[:bi]
    return all(int(e.get("efx_has_label", 0)) == 1 for e in before)


class EFX_OT_rename_body(bpy.types.Operator):
    """重命名 EFX_BODY（改 EFX_Type 标签表里的名字，导出生效）

    标签表是 [Play|Extern|Main] 顺序的连续前缀。可命名条件（can_label_body）：
      - 已有标签（efx_has_label=1）→ 直接改名；
      - 或处于前缀边界（前面条目全有标签）→ 提升为有标签（has_label=1）。
    前面有无标签条目的 body 不可命名（会破坏位置映射），面板会禁用。
    """

    bl_idname      = "efx.rename_body"
    bl_label       = "Rename Body"
    bl_description = "Change this body's name in the EFX file label table (all preceding entries must have labels)"
    bl_options     = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="New Name",
        description="The body's new label name (written to the EFX_Type label table)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return can_label_body(context.active_object)

    def invoke(self, context, event):
        obj = context.active_object
        self.new_name = str(obj.get("efx_raw_label", ""))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        obj = context.active_object
        if not can_label_body(obj):
            self.report({"ERROR"}, "This body cannot be named (preceding unnamed entries would break the label position mapping)")
            return {"CANCELLED"}

        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "Name cannot be empty")
            return {"CANCELLED"}
        if "\x00" in new_name:
            self.report({"ERROR"}, "Name cannot contain NUL characters")
            return {"CANCELLED"}

        root = _find_root(obj)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found")
            return {"CANCELLED"}

        # 更新标签 + 提升为有标签 + 重建显示名 + 置 labels_dirty
        idx = int(obj.get("efx_index", 0))
        obj["efx_raw_label"] = new_name
        obj["efx_has_label"] = 1   # 边界 body 提升为有标签
        obj.name = _body_display_name(idx, new_name)
        root["labels_dirty"] = 1

        self.report({"INFO"}, f"Renamed to: {new_name} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Play / Extern 重命名（与 body 同理；解决"前导 play/extern 未命名锁死全体"的问题）
#
# EFX_Type 标签表是 [Play|Extern|Main] 全局顺序的连续前缀。此前只有 body 能重命名，
# 于是无标签文件里位于最前的 play/extern 永远无法获得标签 → 它后面的所有 body 也
# 因 can_label_body 的"前面条目须全有标签"而永久锁死。给 play/extern 加重命名后，
# 先命名前导 play/extern，body 即随之解锁（前缀逐个向后扩展）。
# ─────────────────────────────────────────────────────────────────────────────

_LABELED_TYPES = ("EFX_PLAY", "EFX_EXTERN", "EFX_BODY")


def _global_ordered_entries(root):
    """root 下按 [Play|Extern|Main] 全局顺序排列的有标签段条目（各段内按 efx_index）。"""
    def _children(type_tag):
        objs = [o for o in bpy.data.objects
                if o.parent == root and o.get("~TYPE") == type_tag]
        objs.sort(key=lambda o: int(o.get("efx_index", 0)))
        return objs
    return _children("EFX_PLAY") + _children("EFX_EXTERN") + _children("EFX_BODY")


def can_label_entry(obj) -> bool:
    """
    通用版 can_label_body：play / extern / body 均适用。

    条件：已有标签（efx_has_label=1）→ True；否则处于标签前缀边界
    （[Play|Extern|Main] 全局顺序里它前面的条目全部已有标签）→ True。
    """
    if obj is None or obj.get("~TYPE") not in _LABELED_TYPES:
        return False
    if int(obj.get("efx_has_label", 0)) == 1:
        return True
    root = _find_root(obj)
    if root is None:
        return False
    ordered = _global_ordered_entries(root)
    if obj not in ordered:
        return False
    pos = ordered.index(obj)
    return all(int(e.get("efx_has_label", 0)) == 1 for e in ordered[:pos])


class EFX_OT_rename_entry(bpy.types.Operator):
    """重命名 EFX_PLAY / EFX_EXTERN（改 EFX_Type 标签表里的名字，导出生效）

    可命名条件同 body（can_label_entry）：已有标签，或处于标签前缀边界。
    显示名格式：'{nn} {label}'（与 io_tree / delete_ops 一致）。
    """

    bl_idname      = "efx.rename_entry"
    bl_label       = "Rename Entry"
    bl_description = "Change this Play/Extern's name in the EFX label table (all preceding entries must have labels)"
    bl_options     = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="New Name",
        description="The entry's new label name (written to the EFX_Type label table)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") in ("EFX_PLAY", "EFX_EXTERN") \
            and can_label_entry(obj)

    def invoke(self, context, event):
        obj = context.active_object
        self.new_name = str(obj.get("efx_raw_label", ""))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") not in ("EFX_PLAY", "EFX_EXTERN"):
            self.report({"ERROR"}, "Select a Play or Extern object")
            return {"CANCELLED"}
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

        root = _find_root(obj)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found")
            return {"CANCELLED"}

        idx = int(obj.get("efx_index", 0))
        nn = str(idx).zfill(2) if idx < 100 else str(idx)
        obj["efx_raw_label"] = new_name
        obj["efx_has_label"] = 1
        obj.name = f"{nn} {new_name}"
        root["labels_dirty"] = 1

        self.report({"INFO"}, f"Renamed to: {new_name} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# auto_sort_body_blocks  —  导出前静默规范化块顺序
#
# 规范顺序层（sort key）：
#    0  EXTERNREFERENCE           (声明块，永远最前)
#   10  TRANSFORM3D/PARENTOPTIONS/SPAWN/LIFE  (body 骨架)
#   20  Renderer blocks           (渲染主体，互斥选一)
#   40  Sprite modifiers          (BILLBOARD3D/RIBBON 专属修饰)
#   50  Mesh overrides            (MESH 专属覆盖)
#   60  Emitters                  (发射器/空间约束)
#   70  Motion                    (运动/速度/动画)
#   80  Visibility                (可见性/渐隐)
#   90  Char effects              (角色附着效果)
#  100  Behavior                  (PTBEHAVIOR 孤立行为系统)
#  110  Misc/control              (特殊/控制)
#  150  (未知类型默认值)
#  200  RGBFIRE / RGBWATER / NOISE (总是最后的全局染色/噪声)
#  210  Lifecycle triggers         (PTCOLLISION/PTLIFE/PTTRIGGER，总是最后)
# ─────────────────────────────────────────────────────────────────────────────

def _build_block_sort_key_map() -> dict:
    """Lazy-build hash→sort_key；导入失败返回空字典。"""
    try:
        from ..efx_format.hashes import (
            EXTERNREFERENCE,
            TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE,
            BILLBOARD3D, RIBBON, MESH, PLANE, FAKEPLANE,
            LIGHTNING, DUMMY, RIBBONBLADE, STRAINRIBBON, TUBELIGHT, BILLBOARD2D,
            UVSEQUENCE, ALPHACORRECTION, REFRACTION, BLINK, LUMINANCEBLEED,
            MATERIAL, UVCONTROL,
            EMITTERSHAPE3D, EMITTERSHAPE2D, EMITTERSHAPEMESH, EMITTERBOUNDARY,
            SPAWNBYANGLE, SPAWNBYOCCLUSION,
            VELOCITY3D, VELOCITY2D, SCALEANIM, ROTATEANIM, TURBULENCE,
            HOMING, GUIDE, PATHCHAIN, SCREENSPACECOLLISION,
            FADEBYDEPTH, FADEBYANGLE, FADEBYEMITTERANGLE, FADEBYOCCLUSION,
            SHADERSETTINGS, MASTERONLY, RAYCAST, LINKPARTSVISIBLE,
            PLEMISSIVE, PARENTEMISSIVE, PLSNOW, PARENTSNOW, OTOMOSNOW,
            PARENTMATERIAL, SHOVEL,
            PTBEHAVIOR,
            RANDOMFIX, TIML, CHECKPUREATTRIBUTE, REPEATAREA, LAYOUT,
            TRANSFORM2D, FAKEDOF, TONEMAPFILTER, COLORCORRECTFILTER,
            RGBFIRE, RGBWATER, NOISE,
            PTCOLLISION, PTLIFE, PTTRIGGER,
        )
    except ImportError:
        return {}
    return {
        EXTERNREFERENCE:        0,
        TRANSFORM3D:            10,
        PARENTOPTIONS:          11,
        SPAWN:                  12,
        LIFE:                   13,
        BILLBOARD3D:            20,
        RIBBON:                 21,
        MESH:                   22,
        PLANE:                  23,
        FAKEPLANE:              24,
        LIGHTNING:              25,
        DUMMY:                  26,
        RIBBONBLADE:            27,
        STRAINRIBBON:           28,
        TUBELIGHT:              29,
        BILLBOARD2D:            30,
        UVSEQUENCE:             40,
        ALPHACORRECTION:        41,
        REFRACTION:             42,
        BLINK:                  43,
        LUMINANCEBLEED:         44,
        MATERIAL:               50,
        UVCONTROL:              51,
        EMITTERSHAPE3D:         60,
        EMITTERSHAPE2D:         61,
        EMITTERSHAPEMESH:       62,
        EMITTERBOUNDARY:        63,
        SPAWNBYANGLE:           64,
        SPAWNBYOCCLUSION:       65,
        VELOCITY3D:             70,
        VELOCITY2D:             71,
        SCALEANIM:              72,
        ROTATEANIM:             73,
        TURBULENCE:             74,
        HOMING:                 75,
        GUIDE:                  76,
        PATHCHAIN:              77,
        SCREENSPACECOLLISION:   78,
        FADEBYDEPTH:            80,
        FADEBYANGLE:            81,
        FADEBYEMITTERANGLE:     82,
        FADEBYOCCLUSION:        83,
        SHADERSETTINGS:         84,
        MASTERONLY:             85,
        RAYCAST:                86,
        LINKPARTSVISIBLE:       87,
        PLEMISSIVE:             90,
        PARENTEMISSIVE:         91,
        PLSNOW:                 92,
        PARENTSNOW:             93,
        OTOMOSNOW:              94,
        PARENTMATERIAL:         95,
        SHOVEL:                 96,
        PTBEHAVIOR:             100,
        RANDOMFIX:              110,
        TIML:                   111,
        CHECKPUREATTRIBUTE:     112,
        REPEATAREA:             113,
        LAYOUT:                 114,
        TRANSFORM2D:            115,
        FAKEDOF:                116,
        TONEMAPFILTER:          117,
        COLORCORRECTFILTER:     118,
        RGBFIRE:                200,
        RGBWATER:               201,
        NOISE:                  202,
        PTCOLLISION:            210,
        PTLIFE:                 211,
        PTTRIGGER:              212,
    }


_BLOCK_SORT_KEY_MAP = None  # lazy-initialized on first export


def auto_sort_body_blocks(root_obj) -> int:
    """
    静默对 root_obj 下每个 body 的 EFX_BLOCK 按规范顺序排序（就地修改 efx_index）。

    规范顺序：EXTERNREFERENCE → 骨架 → 渲染 → 面片修饰 → MESH覆盖 →
             发射器 → 运动 → 可见性 → 角色特效 → 行为 → 杂项 →
             RGBFIRE/RGBWATER/NOISE → 生命周期触发

    只修改 efx_index；io_tree.export_efx_tree 按 efx_index 排序序列化，无需重建显示名。
    返回被重新排序的 body 数量（未变动的 body 不计）。
    """
    global _BLOCK_SORT_KEY_MAP
    if _BLOCK_SORT_KEY_MAP is None:
        _BLOCK_SORT_KEY_MAP = _build_block_sort_key_map()
    sort_map = _BLOCK_SORT_KEY_MAP
    _DEFAULT_KEY = 150

    if root_obj is None:
        return 0

    modified = 0
    bodies = _collect_siblings_by_type(root_obj, "EFX_BODY")
    for body in bodies:
        try:
            blocks = _collect_siblings_by_type(body, "EFX_BLOCK")
            if len(blocks) < 2:
                continue

            def _sort_key(blk, _sm=sort_map, _dk=_DEFAULT_KEY):
                try:
                    h = int(str(blk.get("type_hash", "0")))
                except (ValueError, TypeError):
                    return _dk
                return _sm.get(h, _dk)

            sorted_blocks = sorted(blocks, key=_sort_key)

            # 顺序已正确时跳过（避免无意义的属性写入）
            if all(b is s for b, s in zip(blocks, sorted_blocks)):
                continue

            modified += 1
            for new_idx, blk in enumerate(sorted_blocks):
                blk["efx_index"] = new_idx
        except Exception:
            pass  # 单个 body 失败不阻断其余 body

    return modified


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_move_body,
    EFX_OT_move_block,
    EFX_OT_move_entry,
    EFX_OT_rename_body,
    EFX_OT_rename_entry,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
