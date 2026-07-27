"""
blender_efx/bitmask_ops.py  —  通用位掩码弹窗编辑器（P2，泛化自 part_mask_ops）

由 typed Field 模型驱动：字段标 widget='bitmask'、`Field.bits` 是有序段列表。本弹窗把
每个 **BitDef（可混合 toggle 位）** 画成勾选框，段外的**残留位**（不在任何段 mask 内）另用
一个整数框暴露并保留——确保未定义位零丢失、可精确还原（bitmask 版的 enum 越界回退）。

⚠ **BitEnum（互斥位组 → 下拉）暂未接入**：当前所有 bitmask 字段实测都是纯可混合位
（spinAxisMask / enableVelocityBitflag / tableSelectionGroup），没有互斥组可测。等出现真正的
互斥字段（如 controlBitflag / UVSEQUENCE 打包字节）再据其语义补下拉渲染。届时那些 mask 会
从"残留"里分出来。现在遇到 BitEnum 段：其 mask 归入残留（仍可编辑、数据安全），只是没下拉。

值存于 field_item 的 int 背板槽（int_value/byte1_value/…，由 fields._enum_backing_read/write
按 data_type 选槽），其 update 回调自动置脏 → 导出重 pack。
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

_MAX_BITS = 16   # toggle 勾选框池上限（当前最大 tableSelectionGroup 8 位，留余量）


def _find_item(bp, ori_name):
    for it in bp.field_items:
        if it.ori_name == ori_name:
            return it
    return None


def _bitmask_field(type_name, field_name):
    """返回该字段的 Bitmask Field（widget=='bitmask'），否则 None。"""
    try:
        from ..efx_format.hashes import NAME_TO_HASH
        from ..efx_format.schema.fields_model import FIELD_REGISTRY
        h = NAME_TO_HASH.get(type_name)
        if h is None:
            return None
        f = FIELD_REGISTRY.get((h, field_name))
        if f is None or getattr(f, "widget", None) != "bitmask":
            return None
        return f
    except Exception:
        return None


def _toggles(field):
    """字段里的可混合位（BitDef）——当前唯一支持渲染的段类型。"""
    from ..efx_format.schema.fields_model import BitDef
    return [b for b in field.bits if isinstance(b, BitDef)]


def _defined_mask(field):
    """所有段 mask 的并集（BitDef.bit ∪ BitEnum.mask）——残留 = 值 & ~此。"""
    from ..efx_format.schema.fields_model import BitDef, BitEnum
    m = 0
    for b in field.bits:
        m |= b.bit if isinstance(b, BitDef) else b.mask
    return m


def bitmask_summary(value, field, zh=True):
    """把位掩码值转成面板按钮上的可读摘要。"""
    toggles = _toggles(field)
    names = [(b.zh if zh else b.en) for b in toggles if value & b.bit]
    resid = value & ~_defined_mask(field)
    base = "+".join(names) if names else ("无" if zh else "none")
    if resid:
        base += "  +0x%X" % resid
    return base


class EFX_OT_edit_bitmask(bpy.types.Operator):
    """以勾选框编辑位掩码字段（保留段外残留位）"""

    bl_idname      = "efx.edit_bitmask"
    bl_label       = "Edit Bitmask"
    bl_description = "Edit this bitmask field via checkboxes (undefined bits preserved)"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    type_name: StringProperty()
    field: StringProperty()
    residual: IntProperty(name="Other bits", default=0, min=0,
                          description="段外未定义位（原值保留，可编辑）")
    # bit_0..bit_{_MAX_BITS-1} 勾选框池在类定义后追加（见下）；draw 时按字段实际位数用前 N 个。

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def invoke(self, context, event):
        obj = context.active_object
        field = _bitmask_field(self.type_name, self.field)
        if field is None or obj is None:
            self.report({"ERROR"}, "Not a bitmask field")
            return {"CANCELLED"}
        item = _find_item(obj.efx_block, self.field)
        if item is None:
            self.report({"ERROR"}, "Field '%s' not found" % self.field)
            return {"CANCELLED"}
        from .fields import _enum_backing_read
        val = _enum_backing_read(item)
        for i, b in enumerate(_toggles(field)[:_MAX_BITS]):
            setattr(self, "bit_%d" % i, bool(val & b.bit))
        self.residual = val & ~_defined_mask(field)
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        layout = self.layout
        field = _bitmask_field(self.type_name, self.field)
        if field is None:
            return
        from .i18n import get_lang
        zh = (get_lang() == "ZH")
        for i, b in enumerate(_toggles(field)[:_MAX_BITS]):
            layout.prop(self, "bit_%d" % i, text=(b.zh if zh else b.en))
        layout.separator()
        row = layout.row()
        row.prop(self, "residual")
        row.label(text="(未定义位，保留)" if zh else "(undefined bits, preserved)")

    def execute(self, context):
        obj = context.active_object
        field = _bitmask_field(self.type_name, self.field)
        if field is None or obj is None:
            return {"CANCELLED"}
        item = _find_item(obj.efx_block, self.field)
        if item is None:
            self.report({"ERROR"}, "Field '%s' not found" % self.field)
            return {"CANCELLED"}
        val = 0
        for i, b in enumerate(_toggles(field)[:_MAX_BITS]):
            if getattr(self, "bit_%d" % i):
                val |= b.bit
        val |= int(self.residual)
        from .fields import _enum_backing_write
        _enum_backing_write(item, val)   # update=_mark_attribute_dirty 自动置脏
        return {"FINISHED"}


# toggle 勾选框池：给类追加 bit_0..bit_{_MAX_BITS-1} 布尔属性（label 在 draw 里动态覆盖）。
for _i in range(_MAX_BITS):
    EFX_OT_edit_bitmask.__annotations__["bit_%d" % _i] = BoolProperty(name="bit %d" % _i, default=False)
del _i


_CLASSES = (EFX_OT_edit_bitmask,)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
