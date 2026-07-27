"""
blender_efx/part_mask_ops.py  —  PLEMISSIVE body_p / wp_p 位掩码勾选编辑器

PLEMISSIVE 的关联部位字段是二进制掩码（byte），文档：
  body_p（关联 body 部位）：低 5 位 = 部位掩码，每 32 进一个 cycle
    bit0 head(0x01) / bit1 body(0x02) / bit2 arms(0x04) / bit3 waist(0x08) / bit4 legs(0x10)
    value = cycle*32 + partmask（cycle = value>>5）
  wp_p（关联武器手）：低 2 位 = 手掩码，每 4 进一个 cycle
    bit0 left hand(0x01) / bit1 right hand(0x02)（both = 0x03）
    value = cycle*4 + handmask（cycle = value>>2）

⚠ 实测语料 wp_p 高位（cycle）被大量使用（0x20/0x38 等占一半以上），携带真实数据，
  故 UI 既给低位勾选框、又额外暴露 cycle 数字，确保零数据丢失、可精确还原。

实现：弹窗算子读取 active attribute 对应 field_item 的 int_value，拆成勾选框 + cycle，
  确认后重组写回 int_value（其 update=_mark_block_dirty 会自动置脏 → 导出重 pack）。
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty


# ── 掩码常量 ──────────────────────────────────────────────────────────────────

_BODY_PARTS = [
    ("head",  0x01, "头 Head"),
    ("body",  0x02, "身 Body"),
    ("arms",  0x04, "臂 Arms"),
    ("waist", 0x08, "腰 Waist"),
    ("legs",  0x10, "腿 Legs"),
]
_BODY_MASK  = 0x1F   # 低 5 位
_BODY_CYCLE = 32     # cycle 步长

_WP_PARTS = [
    ("left_hand",  0x01, "左手 Left hand"),
    ("right_hand", 0x02, "右手 Right hand"),
]
_WP_MASK  = 0x03     # 低 2 位
_WP_CYCLE = 4        # cycle 步长


def _find_field_item(bp, ori_name):
    """在 attribute PropertyGroup 的 field_items 里按 ori_name 找字段项。"""
    for it in bp.field_items:
        if it.ori_name == ori_name:
            return it
    return None


def _is_plemissive_attribute(obj):
    """obj 是否为 PLEMISSIVE 属性对象。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        from ..efx_format.hashes import PLEMISSIVE
        return int(obj.efx_block.type_hash_str) == PLEMISSIVE
    except (ValueError, AttributeError, ImportError):
        return False


def part_mask_summary(value, field):
    """把掩码值转成可读摘要字符串（供面板行展示）。"""
    parts = _BODY_PARTS if field == "body_p" else _WP_PARTS
    cyc_step = _BODY_CYCLE if field == "body_p" else _WP_CYCLE
    mask = _BODY_MASK if field == "body_p" else _WP_MASK
    names = [lbl.split(" ")[0] for key, bit, lbl in parts if value & bit]
    if field == "wp_p" and (value & _WP_MASK) == 0x03:
        names = ["双手"]
    cycle = value // cyc_step
    base = "+".join(names) if names else "无"
    if cycle:
        base += f" (cycle {cycle})"
    return base


# ── 勾选弹窗算子 ──────────────────────────────────────────────────────────────

class EFX_OT_set_part_mask(bpy.types.Operator):
    """以勾选框编辑 PLEMISSIVE 的关联部位 / 武器位掩码（保留 cycle 高位）"""

    bl_idname      = "efx.set_part_mask"
    bl_label       = "Edit Part Mask"
    bl_description = "Edit the related-body / related-weapon bitmask via checkboxes"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    field: StringProperty(name="Field", default="body_p")  # "body_p" / "wp_p"

    # body_p 部位
    head:  BoolProperty(name="头 Head",  default=False)
    body:  BoolProperty(name="身 Body",  default=False)
    arms:  BoolProperty(name="臂 Arms",  default=False)
    waist: BoolProperty(name="腰 Waist", default=False)
    legs:  BoolProperty(name="腿 Legs",  default=False)
    # wp_p 手
    left_hand:  BoolProperty(name="左手 Left hand",  default=False)
    right_hand: BoolProperty(name="右手 Right hand", default=False)
    # 高位 cycle（保留真实数据 / 可编辑）
    cycle: IntProperty(name="Cycle", default=0, min=0, max=255,
                       description="高位倍数：value = cycle×步长 + 部位掩码")

    @classmethod
    def poll(cls, context):
        return _is_plemissive_attribute(context.active_object)

    def invoke(self, context, event):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        # body_p / wp_p 是 'B'(byte) 字段 → 值存于 byte1_value 槽（非 int_value）
        val = int(item.byte1_value) if item is not None else 0
        if self.field == "body_p":
            self.head  = bool(val & 0x01)
            self.body  = bool(val & 0x02)
            self.arms  = bool(val & 0x04)
            self.waist = bool(val & 0x08)
            self.legs  = bool(val & 0x10)
            self.cycle = val // _BODY_CYCLE
        else:
            self.left_hand  = bool(val & 0x01)
            self.right_hand = bool(val & 0x02)
            self.cycle = val // _WP_CYCLE
        return context.window_manager.invoke_props_dialog(self, width=240)

    def draw(self, context):
        layout = self.layout
        if self.field == "body_p":
            layout.label(text="关联 body 部位 (body_p)")
            for key, _bit, _lbl in _BODY_PARTS:
                layout.prop(self, key)
        else:
            layout.label(text="关联武器手 (wp_p)")
            for key, _bit, _lbl in _WP_PARTS:
                layout.prop(self, key)
        layout.separator()
        row = layout.row()
        row.prop(self, "cycle")
        row.label(text="(高位，保留原值)")

    def execute(self, context):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        if item is None:
            self.report({"ERROR"}, f"Field '{self.field}' not found")
            return {"CANCELLED"}
        if self.field == "body_p":
            mask = (0x01 if self.head else 0) | (0x02 if self.body else 0) \
                 | (0x04 if self.arms else 0) | (0x08 if self.waist else 0) \
                 | (0x10 if self.legs else 0)
            new_val = (self.cycle * _BODY_CYCLE + mask) & 0xFF
        else:
            mask = (0x01 if self.left_hand else 0) | (0x02 if self.right_hand else 0)
            new_val = (self.cycle * _WP_CYCLE + mask) & 0xFF
        item.byte1_value = new_val   # update=_mark_block_dirty 自动置脏
        self.report({"INFO"}, f"{self.field} = 0x{new_val:02X} ({part_mask_summary(new_val, self.field)})")
        return {"FINISHED"}


_CLASSES = (EFX_OT_set_part_mask,)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
