"""为 SHADERSETTINGS 的 ``presetId`` 提供已知名称选择菜单。

维护约束：本模块只写字段模型的显示属性，不拥有或改变底层 int32 存储。
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Menu, Operator

from .fields import SHADERSETTINGS_KNOWN_PRESETS, preset_menu_label


def _find_field_item(bp, ori_name):
    for it in bp.field_items:
        if it.ori_name == ori_name:
            return it
    return None


class EFX_OT_shadersettings_set_preset(Operator):
    """通过字段显示属性设置预设名称或数值。"""

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
    """显示全部已知预设。"""

    bl_idname = "EFX_MT_shadersettings_preset_picker"
    bl_label  = "Presets"

    def draw(self, context):
        layout = self.layout
        for name, _v, hint_en, hint_zh in SHADERSETTINGS_KNOWN_PRESETS:
            op = layout.operator("efx.shadersettings_set_preset",
                                 text=preset_menu_label(name, hint_en, hint_zh))
            op.field = "presetId"
            op.value = name
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
