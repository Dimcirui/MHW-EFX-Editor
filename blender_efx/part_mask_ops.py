"""PLEMISSIVE body_p 与 wp_p 的位掩码编辑器。

维护约束：
- 两字段都是完整的 8 位掩码，直接读写 byte1_value，不做额外换算。
- 未确认的部位名称以 `?` 标示；未知位仍以独立复选框保留。
"""

import bpy
from bpy.props import BoolProperty, StringProperty


# 掩码项：(属性名、位、中文标签、英文标签)。
_BODY_PARTS = [
    ("head",  0x01, "头 Head",   "Head"),
    ("body",  0x02, "身 Body",   "Body"),
    ("arms",  0x04, "臂 Arms",   "Arms"),
    ("waist", 0x08, "腰 Waist",  "Waist"),
    ("legs",  0x10, "腿 Legs",   "Legs"),
    ("acce",  0x20, "饰 Acce?",  "Acce?"),
    ("hair",  0x40, "发 Hair?",  "Hair?"),
    ("face",  0x80, "脸 Face?",  "Face?"),
]

_WP_PARTS = [
    ("wpSub0",   0x01, "WP_SUB0?",  "WP_SUB0?"),
    ("wpMain",   0x02, "WP_MAIN?",  "WP_MAIN?"),
    ("wpSub1",   0x04, "WP_SUB1?",  "WP_SUB1?"),
    ("wp_unkn3", 0x08, "未知 3", "Unknown 3"),
    ("wp_unkn4", 0x10, "未知 4", "Unknown 4"),
    ("wp_unkn5", 0x20, "未知 5", "Unknown 5"),
    ("wp_unkn6", 0x40, "未知 6", "Unknown 6"),
    ("wp_unkn7", 0x80, "未知 7", "Unknown 7"),
]


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
    names = [zh.split(" ")[0] for _key, bit, zh, _en in parts if value & bit]
    return "+".join(names) if names else "无"


class EFX_OT_set_part_mask(bpy.types.Operator):
    """以勾选框编辑 PLEMISSIVE 的关联部位 / 关联武器位掩码"""

    bl_idname      = "efx.set_part_mask"
    bl_label       = "Edit Part Mask"
    bl_description = "Edit the related-body / related-weapon bitmask via checkboxes"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    field: StringProperty(name="Field", default="body_p")

    head:  BoolProperty(name="头 Head",  default=False)
    body:  BoolProperty(name="身 Body",  default=False)
    arms:  BoolProperty(name="臂 Arms",  default=False)
    waist: BoolProperty(name="腰 Waist", default=False)
    legs:  BoolProperty(name="腿 Legs",  default=False)
    acce: BoolProperty(name="饰 Acce?", default=False)
    hair: BoolProperty(name="发 Hair?", default=False)
    face: BoolProperty(name="脸 Face?", default=False)

    wpSub0: BoolProperty(name="WP_SUB0?", default=False)
    wpMain: BoolProperty(name="WP_MAIN?", default=False)
    wpSub1: BoolProperty(name="WP_SUB1?", default=False)
    wp_unkn3: BoolProperty(name="未知 3", default=False)
    wp_unkn4: BoolProperty(name="未知 4", default=False)
    wp_unkn5: BoolProperty(name="未知 5", default=False)
    wp_unkn6: BoolProperty(name="未知 6", default=False)
    wp_unkn7: BoolProperty(name="未知 7", default=False)

    @classmethod
    def poll(cls, context):
        return _is_plemissive_attribute(context.active_object)

    def invoke(self, context, event):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        val = int(item.byte1_value) if item is not None else 0
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        for key, bit, _zh, _en in parts:
            setattr(self, key, bool(val & bit))
        return context.window_manager.invoke_props_dialog(self, width=240)

    def draw(self, context):
        layout = self.layout
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        layout.label(text="关联 body 部位 (body_p)" if self.field == "body_p"
                     else "关联武器 (wp_p)")
        for key, _bit, _zh, _en in parts:
            layout.prop(self, key)

    def execute(self, context):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        if item is None:
            self.report({"ERROR"}, f"Field '{self.field}' not found")
            return {"CANCELLED"}
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        mask = 0
        for key, bit, _zh, _en in parts:
            if getattr(self, key):
                mask |= bit
        item.byte1_value = mask & 0xFF
        self.report({"INFO"}, f"{self.field} = 0x{mask:02X} ({part_mask_summary(mask, self.field)})")
        return {"FINISHED"}


_CLASSES = (EFX_OT_set_part_mask,)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
