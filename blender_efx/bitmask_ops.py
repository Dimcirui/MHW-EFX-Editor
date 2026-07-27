"""
blender_efx/bitmask_ops.py  —  通用位掩码弹窗编辑器（泛化自 part_mask_ops）

由 typed Field 模型驱动：字段标 widget='bitmask'、`Field.bits` 是有序段列表，元素两类：
  · **BitDef（可混合 toggle 位）** → 勾选框；
  · **BitEnum（互斥位组）** → 下拉（同 enum，选项即该组编码的 one-of-N 值）。
段外的**残留位**（不在任何段 mask 内）另用整数框暴露并保留——确保未定义位零丢失、可精确
还原（bitmask 版的越界回退）。BitEnum 子值若越出选项集，下拉动态注入原值合成项（同 enum_proxy）。

值存于 field_item 的 int 背板槽（int_value/byte1_value/…，由 fields._enum_backing_read/write
按 data_type 选槽），其 update 回调自动置脏 → 导出重 pack。
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty, EnumProperty

_MAX_BITS  = 16   # toggle 勾选框池上限
_MAX_ENUMS = 8    # 互斥组下拉池上限（当前最多 loopingMode 4 组，留余量）

# BitEnum 下拉的 items 缓存（避免动态 EnumProperty 的 GC 陷阱：持有 list 对象引用）。
_BENUM_ITEMS_CACHE = {}


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
    """字段里的可混合位（BitDef）——勾选框段。"""
    from ..efx_format.schema.fields_model import BitDef
    return [b for b in field.bits if isinstance(b, BitDef)]


def _bitenums(field):
    """字段里的互斥位组（BitEnum）——下拉段。"""
    from ..efx_format.schema.fields_model import BitEnum
    return [b for b in field.bits if isinstance(b, BitEnum)]


def _defined_mask(field):
    """所有段 mask 的并集（BitDef.bit ∪ BitEnum.mask）——残留 = 值 & ~此。"""
    from ..efx_format.schema.fields_model import BitDef, BitEnum
    m = 0
    for b in field.bits:
        m |= b.bit if isinstance(b, BitDef) else b.mask
    return m


def _benum_items_factory(idx):
    """生成第 idx 个 BitEnum 下拉的 items 回调（闭包捕获 idx）。回调据当前字段与语言返回
    选项；当前子值越界则注入合成项。列表缓存进 _BENUM_ITEMS_CACHE 防 GC。"""
    def _items(self, context):
        field = _bitmask_field(self.type_name, self.field)
        benums = _bitenums(field) if field else []
        if idx >= len(benums):
            return [('0', '—', '')]
        be = benums[idx]
        from .i18n import get_lang
        zh = (get_lang() == "ZH")
        items = [(str(o.value), (o.zh if zh else o.en), '') for o in be.options]
        # 当前子值（从 item 背板读）越界 → 注入原值合成项，避免 setattr 失败
        obj = context.active_object if context else None
        if obj is not None:
            it = _find_item(obj.efx_block, self.field)
            if it is not None:
                from .fields import _enum_backing_read
                cur = (_enum_backing_read(it) & be.mask) >> be.shift
                if all(o.value != cur for o in be.options):
                    items.append((str(cur), ("值 %d (?)" % cur) if zh else ("value %d (?)" % cur), ''))
        _BENUM_ITEMS_CACHE[(self.type_name, self.field, idx, zh)] = items
        return _BENUM_ITEMS_CACHE[(self.type_name, self.field, idx, zh)]
    return _items


def bitmask_summary(value, field, zh=True):
    """把位掩码值转成面板按钮上的可读摘要（混合位名 + 互斥组当前项 + 残留）。"""
    from ..efx_format.schema.fields_model import BitDef, BitEnum
    parts = []
    for b in field.bits:
        if isinstance(b, BitDef):
            if value & b.bit:
                parts.append(b.zh if zh else b.en)
        else:  # BitEnum
            sub = (value & b.mask) >> b.shift
            lbl = next((o.zh if zh else o.en for o in b.options if o.value == sub), None)
            grp = b.zh if zh else b.en
            parts.append("%s:%s" % (grp, lbl if lbl is not None else ("值%d" % sub if zh else "v%d" % sub)))
    resid = value & ~_defined_mask(field)
    base = "  ".join(parts) if parts else ("无" if zh else "none")
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
        for i, be in enumerate(_bitenums(field)[:_MAX_ENUMS]):
            sub = (val & be.mask) >> be.shift
            try:
                setattr(self, "benum_%d" % i, str(sub))
            except TypeError:
                pass  # 子值暂不在 items 中（items 回调会注入后重试无碍）
        self.residual = val & ~_defined_mask(field)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        from ..efx_format.schema.fields_model import BitDef
        layout = self.layout
        field = _bitmask_field(self.type_name, self.field)
        if field is None:
            return
        from .i18n import get_lang
        zh = (get_lang() == "ZH")
        ti = ei = 0
        for b in field.bits:   # 按声明顺序渲染，勾选框与下拉交错
            if isinstance(b, BitDef):
                if ti < _MAX_BITS:
                    layout.prop(self, "bit_%d" % ti, text=(b.zh if zh else b.en))
                ti += 1
            else:  # BitEnum
                if ei < _MAX_ENUMS:
                    layout.prop(self, "benum_%d" % ei, text=(b.zh if zh else b.en))
                ei += 1
        resid_mask = _defined_mask(field)
        if resid_mask != -1 and (~resid_mask) & 0xFFFFFFFF:   # 尚有未定义位才显示残留框
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
        for i, be in enumerate(_bitenums(field)[:_MAX_ENUMS]):
            sub = int(getattr(self, "benum_%d" % i))
            val |= (sub << be.shift) & be.mask
        val |= int(self.residual)
        from .fields import _enum_backing_write
        _enum_backing_write(item, val)   # update=_mark_attribute_dirty 自动置脏
        return {"FINISHED"}


# toggle 勾选框池：给类追加 bit_0..bit_{_MAX_BITS-1} 布尔属性（label 在 draw 里动态覆盖）。
for _i in range(_MAX_BITS):
    EFX_OT_edit_bitmask.__annotations__["bit_%d" % _i] = BoolProperty(name="bit %d" % _i, default=False)
# 互斥组下拉池：benum_0..benum_{_MAX_ENUMS-1}，每个 items 由 _benum_items_factory 动态给出。
for _i in range(_MAX_ENUMS):
    EFX_OT_edit_bitmask.__annotations__["benum_%d" % _i] = EnumProperty(
        name="enum %d" % _i, items=_benum_items_factory(_i))
del _i


_CLASSES = (EFX_OT_edit_bitmask,)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
