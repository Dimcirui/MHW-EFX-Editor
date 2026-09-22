"""重排 Entry、Action、Extern 与属性对象。

维护约束：重排后必须按列表顺序为整个段重新编号并刷新显示名；导出时引用依据
对象到段内索引的映射重算，不能手工交换引用。顶层条目顺序变化必须置
``labels_dirty``，使标签表按新顺序重建。Root body 的位置规则由 normalize 维护。
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
    """返回 Entry 属性决定的显示后缀；没有 Entry 时返回空串。"""
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
    """生成 Entry 显示名；渲染后缀仅用于大纲呈现。"""
    nn = str(efx_index).zfill(2) if efx_index < 100 else str(efx_index)
    suffix = _entry_renderer_suffix(entry_obj)
    return f"{nn} {raw_label}{suffix}"


def _attribute_display_name(efx_index: int, parent_label: str, type_name: str) -> str:
    """生成属性显示名；类型名称格式化不改变内部类型标识。"""
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
# 顶层段重排共享同一全组重编号与标签表失效逻辑。

def _move_labeled_entry(obj, direction: str, type_tag: str, report) -> set:
    """移动顶层段对象并为整个段稳定重编号。

    ``(efx_index, name)`` 定义异常重复索引时的确定顺序；重排后必须重建显示名并
    标记标签表失效。
    """
    from . import normalize
    root = _rc.find_root_collection(obj)
    if root is None:
        report({"ERROR"}, "EFX_ROOT not found")
        return {"CANCELLED"}

    sibs = normalize._collect_group(root, type_tag)
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

    sibs[pos], sibs[npos] = sibs[npos], sibs[pos]
    for i, o in enumerate(sibs):
        o["efx_index"] = i
        try:
            o.name = normalize._display_name(o, type_tag, i)
        except Exception:
            pass

    root["labels_dirty"] = 1

    dir_str = "up" if direction == "UP" else "down"
    report({"INFO"}, f"Moved {dir_str}: {obj.name}")
    return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_entry  —  entry 上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_entry(bpy.types.Operator):
    """移动选中的 Entry 并刷新 Main 段顺序。"""

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
        return _rc.find_root_collection(obj) is not None

    def execute(self, context):
        return _move_labeled_entry(context.active_object, self.direction, "EFX_ENTRY", self.report)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_attribute  —  属性上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_attribute(bpy.types.Operator):
    """移动选中属性并刷新所属 Entry 的属性顺序。"""

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
        parent = obj.parent
        return parent is not None and parent.get("~TYPE") == "EFX_ENTRY"

    def execute(self, context):
        from . import normalize
        obj = context.active_object
        body = obj.parent

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
    """移动选中的 Action 或 Extern；引用在导出时按段内索引重算。"""

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
    """判断 Entry 能否安全占用标签前缀中的位置；Root 不可命名。"""
    if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
        return False
    if str(obj.get("entry_kind", "")) == "root":
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
    """重命名 Entry 并更新 EFX 标签表数据。"""

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
        ok, msg = apply_rename(context.active_object, self.new_name)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed to: {msg} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Action、Extern 与 Entry 共享全局连续标签前缀。

_LABELED_TYPES = ("EFX_ACTION", "EFX_EXTERN", "EFX_ENTRY")


def _global_ordered_entries(root):
    """root 下按 [Action|Extern|Entry] 全局顺序排列的有标签段条目（各段内按 efx_index）。"""
    return (_rc.collect_top_level(root, "EFX_ACTION")
            + _rc.collect_top_level(root, "EFX_EXTERN")
            + _rc.collect_top_level(root, "EFX_ENTRY"))


def can_label_action_extern(obj) -> bool:
    """判断顶层条目能否安全占用或扩展连续标签前缀。"""
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
    """重命名 Action 或 Extern 并更新 EFX 标签表数据。"""

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
        ok, msg = apply_rename(context.active_object, self.new_name)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed to: {msg} (written to label table on export)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 属性规范顺序由 efx_format.categories 的纯 Python 表定义。

def _build_attribute_sort_key_map() -> dict:
    """Lazy-build hash→sort_key；导入失败返回空字典（调用方退化为不排序）。"""
    try:
        from ..efx_format.categories import ATTRIBUTE_CANONICAL_ORDER
    except ImportError:
        return {}
    return dict(ATTRIBUTE_CANONICAL_ORDER)


_ATTRIBUTE_SORT_KEY_MAP = None  # lazy-initialized on first export


def auto_sort_entry_attributes(root_obj) -> int:
    """按规范表稳定排序各 Entry 的属性，仅更新 efx_index。

    相同 rank 和未知类型保留相对顺序；规范排序是可选导出修正而非格式硬约束。
    """
    global _ATTRIBUTE_SORT_KEY_MAP
    if _ATTRIBUTE_SORT_KEY_MAP is None:
        _ATTRIBUTE_SORT_KEY_MAP = _build_attribute_sort_key_map()
    sort_map = _ATTRIBUTE_SORT_KEY_MAP
    if not sort_map:
        return 0
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

            if all(b is s for b, s in zip(blocks, sorted_attributes)):
                continue

            modified += 1
            for new_idx, blk in enumerate(sorted_attributes):
                blk["efx_index"] = new_idx
        except Exception:
            pass

    return modified


# ─────────────────────────────────────────────────────────────────────────────
# 重命名：共用内核 + 两种画法（Edit 面板的弹窗按钮 / 属性面板的就地输入框）
# ─────────────────────────────────────────────────────────────────────────────

def can_rename(obj) -> bool:
    """obj 现在能不能改名（按类型分派到对应的标签前缀判定）。非可命名类型 → False。"""
    t = obj.get("~TYPE") if obj is not None else None
    if t == "EFX_ENTRY":
        return can_label_entry(obj)
    if t in ("EFX_ACTION", "EFX_EXTERN"):
        return can_label_action_extern(obj)
    return False


def apply_rename(obj, new_name: str):
    """应用标签改名及其派生状态，返回成功标记和消息。

    必须同步标签、显示名、标签表脏标记和名称派生的身份哈希。
    """
    t = obj.get("~TYPE") if obj is not None else None
    if t not in ("EFX_ENTRY", "EFX_ACTION", "EFX_EXTERN"):
        return False, "Select an Entry, Action or Extern"
    if not can_rename(obj):
        return False, "This item cannot be named (a preceding item is unnamed, which would break the label position mapping)"

    new_name = new_name.strip()
    if not new_name:
        return False, "Name cannot be empty"
    if "\x00" in new_name:
        return False, "Name cannot contain NUL characters"

    root = _rc.find_root_collection(obj)
    if root is None:
        return False, "EFX_ROOT not found"

    idx = int(obj.get("efx_index", 0))
    obj["efx_raw_label"] = new_name
    obj["efx_has_label"] = 1
    root["labels_dirty"] = 1

    if t == "EFX_ENTRY":
        obj.name = _entry_display_name(idx, new_name, entry_obj=obj)
        # Root Entry 的 body_type 不是名称哈希。
        if str(obj.get("entry_kind", "")) == "standard":
            try:
                from ..efx_format.hashes import jamcrc
                obj["body_type"] = str(jamcrc(new_name) & 0xFFFFFFFF)
            except Exception:
                pass
    else:
        nn = str(idx).zfill(2) if idx < 100 else str(idx)
        obj.name = f"{nn} {new_name}"
        try:
            from ..efx_format.hashes import jamcrc
            if t == "EFX_ACTION":
                obj.efx_play.play_type_str = str(jamcrc(new_name))
            else:
                # Extern 类型同样由标签名称派生。
                obj.efx_extern.attr_type_str = str(jamcrc(new_name))
        except Exception:
            pass

    return True, new_name


def _label_edit_get(self):
    return str(self.get("efx_raw_label", ""))


def _label_edit_set(self, value):
    # 输入框必须走与弹窗相同的改名副作用链。
    apply_rename(self, value)


def draw_rename_field(layout, obj) -> None:
    """绘制就地标签编辑控件；不可命名时禁用。"""
    from .i18n import T

    t = obj.get("~TYPE") if obj is not None else None
    if t not in ("EFX_ENTRY", "EFX_ACTION", "EFX_EXTERN"):
        return
    if t == "EFX_ENTRY" and str(obj.get("entry_kind", "")) == "root":
        return

    allowed = can_rename(obj)
    row = layout.row()
    row.enabled = allowed
    row.prop(obj, "efx_label_edit", text=T("entry.name_field"))
    if not allowed:
        hint = layout.row()
        hint.enabled = False
        hint.label(text=T("entry.name_blocked_hint"), icon="INFO")


def draw_rename_button(layout, obj) -> None:
    """绘制弹窗式改名按钮，与就地控件共享命名判定。"""
    from .i18n import T

    t = obj.get("~TYPE") if obj is not None else None
    if t == "EFX_ENTRY" and str(obj.get("entry_kind", "")) == "root":
        return
    if t == "EFX_ENTRY":
        op_id, ok_key, blocked_key = "efx.rename_entry", "entry.rename", "entry.rename_blocked"
    elif t in ("EFX_ACTION", "EFX_EXTERN"):
        op_id, ok_key, blocked_key = ("efx.rename_action_extern", "actionextern.rename",
                                      "actionextern.rename_blocked")
    else:
        return

    if can_rename(obj):
        layout.operator(op_id, text=T(ok_key), icon="GREASEPENCIL")
    else:
        sub = layout.column()
        sub.enabled = False
        sub.operator(op_id, text=T(blocked_key), icon="GREASEPENCIL")


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

    # 输入框直接读写标签属性，并统一经 apply_rename 更新派生状态。
    bpy.types.Object.efx_label_edit = bpy.props.StringProperty(
        name="Name",
        description="This item's name in the EFX label table (applied to the file on export)",
        get=_label_edit_get,
        set=_label_edit_set,
    )


def unregister():
    if hasattr(bpy.types.Object, "efx_label_edit"):
        del bpy.types.Object.efx_label_edit
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
