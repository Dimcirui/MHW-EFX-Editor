"""
blender_efx/shadersettings_preset_ops.py  —  SHADERSETTINGS.presetId 已知预设名下拉

presetId 本身仍是普通 int32 字段（见 blender_efx/fields.py 的 preset_name_display
影子属性），这里只提供一个"选个已知名字直接填进去"的快捷菜单，不涉及底层存储。
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Menu, Operator

from .fields import SHADERSETTINGS_KNOWN_PRESETS, SHADERSETTINGS_UNCONFIRMED_PRESET_VALUES


def _find_field_item(bp, ori_name):
    for it in bp.field_items:
        if it.ori_name == ori_name:
            return it
    return None


class EFX_OT_shadersettings_set_preset(Operator):
    """把 presetId 的显示文本设为给定名字/数值（转发到 preset_name_display 的 get/set）"""

    bl_idname      = "efx.shadersettings_set_preset"
    bl_label       = "Set Preset"
    bl_description = "Fill the preset field with this name/value"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    field: StringProperty(name="Field", default="presetId")
    value: StringProperty(name="Value", default="")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def execute(self, context):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        if item is None:
            self.report({"ERROR"}, f"Field '{self.field}' not found")
            return {"CANCELLED"}
        item.preset_name_display = self.value
        return {"FINISHED"}


class EFX_MT_shadersettings_preset_picker(Menu):
    """presetId 已知预设下拉：4 个已知名字 + 4 个原始数值（名字未知）。"""

    bl_idname = "EFX_MT_shadersettings_preset_picker"
    bl_label  = "Presets"

    def draw(self, context):
        layout = self.layout
        for name, _v in SHADERSETTINGS_KNOWN_PRESETS:
            op = layout.operator("efx.shadersettings_set_preset", text=name)
            op.field = "presetId"
            op.value = name
        if SHADERSETTINGS_UNCONFIRMED_PRESET_VALUES:
            layout.separator()
            for v in SHADERSETTINGS_UNCONFIRMED_PRESET_VALUES:
                op = layout.operator("efx.shadersettings_set_preset", text=str(v))
                op.field = "presetId"
                op.value = str(v)
        layout.separator()
        op = layout.operator("efx.shadersettings_set_preset", text="None (-1)")
        op.field = "presetId"
        op.value = ""


_CLASSES = (EFX_OT_shadersettings_set_preset, EFX_MT_shadersettings_preset_picker)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
