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
# EFX_OT_move_body  —  body 上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_body(bpy.types.Operator):
    """上移或下移选中的 EFX_BODY（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_body"
    bl_label       = "移动 Body"
    bl_description = "在 Main 段内上移或下移选中的 EFX_BODY"
    bl_options     = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="方向",
        description="移动方向",
        items=[
            ("UP",   "上移", "向前（索引减小）移动"),
            ("DOWN", "下移", "向后（索引增大）移动"),
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
        obj = context.active_object
        root = obj.parent  # EFX_ROOT

        # 收集同级 EFX_BODY，已按 efx_index 升序排列
        siblings = _collect_siblings_by_type(root, "EFX_BODY")
        if len(siblings) < 2:
            self.report({"INFO"}, "只有 1 个 body，无法移动")
            return {"CANCELLED"}

        # 找当前 body 在列表中的位置
        cur_idx = None
        for i, sibling in enumerate(siblings):
            if sibling == obj:
                cur_idx = i
                break

        if cur_idx is None:
            self.report({"ERROR"}, "无法找到当前 body 在同级列表中的位置")
            return {"CANCELLED"}

        if self.direction == "UP":
            if cur_idx == 0:
                self.report({"INFO"}, "已在最顶部，无法上移")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx - 1]
        else:  # DOWN
            if cur_idx == len(siblings) - 1:
                self.report({"INFO"}, "已在最底部，无法下移")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx + 1]

        # 执行交换（efx_index + 显示名）
        _swap_objects(obj, neighbor, is_body=True)

        dir_str = "上移" if self.direction == "UP" else "下移"
        self.report(
            {"INFO"},
            f"EFX_BODY 已{dir_str}：{obj.name} ↔ {neighbor.name}",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_move_block  —  块上移/下移
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_move_block(bpy.types.Operator):
    """上移或下移选中 EFX_BODY 内的 EFX_BLOCK（交换 efx_index 并重建显示名）"""

    bl_idname      = "efx.move_block"
    bl_label       = "移动块"
    bl_description = "在同一 EFX_BODY 内上移或下移选中的 EFX_BLOCK"
    bl_options     = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="方向",
        description="移动方向",
        items=[
            ("UP",   "上移", "向前（索引减小）移动"),
            ("DOWN", "下移", "向后（索引增大）移动"),
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
            self.report({"INFO"}, "只有 1 个块，无法移动")
            return {"CANCELLED"}

        # 找当前块在列表中的位置
        cur_idx = None
        for i, sibling in enumerate(siblings):
            if sibling == obj:
                cur_idx = i
                break

        if cur_idx is None:
            self.report({"ERROR"}, "无法找到当前块在同级列表中的位置")
            return {"CANCELLED"}

        if self.direction == "UP":
            if cur_idx == 0:
                self.report({"INFO"}, "已在最顶部，无法上移")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx - 1]
        else:  # DOWN
            if cur_idx == len(siblings) - 1:
                self.report({"INFO"}, "已在最底部，无法下移")
                return {"CANCELLED"}
            neighbor = siblings[cur_idx + 1]

        # 执行交换（efx_index + 显示名）
        _swap_objects(obj, neighbor, is_body=False)

        dir_str = "上移" if self.direction == "UP" else "下移"
        self.report(
            {"INFO"},
            f"EFX_BLOCK 已{dir_str}：{obj.name} ↔ {neighbor.name}",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_rename_body  —  body 改名（仅限文件中已有标签的 body）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_rename_body(bpy.types.Operator):
    """重命名 EFX_BODY（改 EFX_Type 标签表里的名字，导出生效）

    ⚠ 仅支持文件中已有标签的 body（efx_has_label=1）。标签表是 [Play|Extern|Main]
    顺序的前缀，无标签 body 在前缀之外，硬给名字会破坏位置映射，故不支持（v1）。
    """

    bl_idname      = "efx.rename_body"
    bl_label       = "重命名 Body"
    bl_description = "修改该 body 在 EFX 文件标签表中的名字（仅限已有标签的 body）"
    bl_options     = {"REGISTER", "UNDO"}

    new_name: bpy.props.StringProperty(
        name="新名字",
        description="该 body 的新标签名（写入 EFX_Type 标签表）",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BODY":
            return False
        # 仅已有标签的 body 可改名
        return int(obj.get("efx_has_label", 0)) == 1

    def invoke(self, context, event):
        obj = context.active_object
        self.new_name = str(obj.get("efx_raw_label", ""))
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BODY":
            self.report({"ERROR"}, "请选中 EFX_BODY")
            return {"CANCELLED"}
        if int(obj.get("efx_has_label", 0)) != 1:
            self.report({"ERROR"}, "该 body 在文件中无名字槽（无标签），不可改名")
            return {"CANCELLED"}

        new_name = self.new_name.strip()
        if not new_name:
            self.report({"ERROR"}, "名字不能为空")
            return {"CANCELLED"}
        if "\x00" in new_name:
            self.report({"ERROR"}, "名字不能含 NUL 字符")
            return {"CANCELLED"}

        # 找 EFX_ROOT（沿 parent 链）
        root = obj
        while root is not None and root.get("~TYPE") != "EFX_ROOT":
            root = root.parent
        if root is None:
            self.report({"ERROR"}, "未找到 EFX_ROOT")
            return {"CANCELLED"}

        # 更新标签 + 重建显示名 + 置 labels_dirty（导出重建标签表）
        idx = int(obj.get("efx_index", 0))
        obj["efx_raw_label"] = new_name
        obj.name = _body_display_name(idx, new_name)
        root["labels_dirty"] = 1

        self.report({"INFO"}, f"已重命名为：{new_name}（导出时写入标签表）")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_move_body,
    EFX_OT_move_block,
    EFX_OT_rename_body,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
