# -*- coding: utf-8 -*-
"""LAYOUT 属性内嵌布局表的编辑：增删行、增删列、逐行改值。

维护约束：
- 字节以 ``efx_block.raw_b64`` 为准。每次编辑先烘焙前缀字段的待编辑值，再解表、修改、打包，
  最后按导入流程重建字段项；结构规则全部在 ``efx_format.assembly.layoutbank``。
- 增删列只同步被改动列的开关，其余开关保持原值。
- 动态 EnumProperty 的 items 必须保存在模块级列表里，否则下拉文字会被回收成乱码。
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty, \
    IntVectorProperty

from .i18n import T

#: 每页显示的行数
PAGE_ROWS = 16
#: 逐行编辑弹窗一次最多容纳的值个数（列 7 为 subCount×4）
_MAX_VALUES = 32

_BLOCK_CACHE = {}
_COLUMN_ENUM_CACHE = []


def _layout_hash():
    from ..efx_format.hashes import LAYOUT
    return LAYOUT


def is_layout_attribute(obj) -> bool:
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    bp = getattr(obj, "efx_block", None)
    if bp is None or not bp.is_editable:
        return False
    try:
        return int(bp.type_hash_str) == _layout_hash()
    except ValueError:
        return False


def _decode(data: bytes):
    from ..efx_format.schema.custom_codecs import unpack_layout, unpack_layoutbank_block
    values, _ = unpack_layout(data, 0)
    block, _ = unpack_layoutbank_block(values.pop("layoutbank_bytes"), 0)
    return values, block


def cached_block(bp):
    """供绘制用的布局表（只读）；以 raw_b64 为键缓存，字节变了才重新解。"""
    import base64
    key = bp.raw_b64
    block = _BLOCK_CACHE.get(key)
    if block is None:
        _prefix, block = _decode(base64.b64decode(key))
        if len(_BLOCK_CACHE) >= 8:
            _BLOCK_CACHE.pop(next(iter(_BLOCK_CACHE)))
        _BLOCK_CACHE[key] = block
    return block


def _edit(op, obj, fn, touched_columns=None):
    """烘焙 → 解表 → fn(block) → 同步开关 → 打包写回并重建字段项。"""
    from . import fields as _fields
    from ..efx_format.assembly import layoutbank as lb
    from ..efx_format.schema.custom_codecs import pack_layout, pack_layoutbank_block

    bp = obj.efx_block
    layout_hash = _layout_hash()
    prefix, block = _decode(_fields.rebuild_custom_field_attribute(bp, layout_hash))
    try:
        fn(block)
    except lb.LayoutBankError as e:
        op.report({"WARNING"}, str(e))
        return {"CANCELLED"}
    if touched_columns is not None:
        prefix = lb.sync_layout_flags(prefix, block, columns=touched_columns)
    prefix["layoutbank_bytes"] = pack_layoutbank_block(block)
    if not _fields.reinit_custom_field_from_bytes(bp, layout_hash, pack_layout(prefix)):
        op.report({"ERROR"}, "Layout table could not be rebuilt")
        return {"CANCELLED"}
    bp.efx_dirty = True
    return {"FINISHED"}


def _page(obj) -> int:
    return max(0, int(obj.get("efx_layoutbank_page", 0)))


# ── 算子 ────────────────────────────────────────────────────────────────────

class _LayoutOp:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return is_layout_attribute(context.active_object)


class EFX_OT_layoutbank_row_add(_LayoutOp, bpy.types.Operator):
    """在布局表中插入一行"""

    bl_idname = "efx.layoutbank_row_add"
    bl_label = "Add Row"
    bl_description = "Insert a row after this one, copying its values"

    row: IntProperty(default=-1, options={"HIDDEN"})
    copy: BoolProperty(default=True, options={"HIDDEN"})

    def execute(self, context):
        from ..efx_format.assembly import layoutbank as lb
        row = self.row

        def fn(block):
            count = int(block["count"])
            src = row if 0 <= row < count else (count - 1 if count else None)
            index = (row + 1) if 0 <= row < count else count
            lb.add_row(block, index=index, copy_from=src if self.copy else None)
        return _edit(self, context.active_object, fn)


class EFX_OT_layoutbank_row_remove(_LayoutOp, bpy.types.Operator):
    """删除布局表中的一行"""

    bl_idname = "efx.layoutbank_row_remove"
    bl_label = "Remove Row"
    bl_description = "Remove this row from every column"

    row: IntProperty(default=0, options={"HIDDEN"})

    def execute(self, context):
        from ..efx_format.assembly import layoutbank as lb
        return _edit(self, context.active_object, lambda b: lb.remove_row(b, self.row))


def _column_items(self, context):
    global _COLUMN_ENUM_CACHE
    items = []
    obj = context.active_object
    if is_layout_attribute(obj):
        from ..efx_format.assembly import layoutbank as lb
        try:
            block = cached_block(obj.efx_block)
        except Exception:
            block = None
        if block is not None and int(block["count"]) > 0:
            for bt in lb.addable_columns(block):
                items.append((str(bt), T("layoutbank.column").format(bt=bt),
                              _column_shape(bt, 2 if bt == 7 else 1)))
    if not items:
        items = [("__none__", T("layoutbank.no_addable"), "")]
    _COLUMN_ENUM_CACHE = items
    return _COLUMN_ENUM_CACHE


class EFX_OT_layoutbank_column_add(_LayoutOp, bpy.types.Operator):
    """新增一列"""

    bl_idname = "efx.layoutbank_column_add"
    bl_label = "Add Column"
    bl_description = "Add a column filled with zeros; a dependent column needs its parent column first"

    block_type: EnumProperty(name="Column", items=_column_items)
    sub_count: IntProperty(name="Groups per Row", default=2, min=1, max=_MAX_VALUES // 4)

    def execute(self, context):
        from ..efx_format.assembly import layoutbank as lb
        if self.block_type == "__none__":
            return {"CANCELLED"}
        bt = int(self.block_type)
        return _edit(self, context.active_object,
                     lambda b: lb.add_column(b, bt, sub_count=self.sub_count),
                     touched_columns=[bt])


class EFX_OT_layoutbank_column_remove(_LayoutOp, bpy.types.Operator):
    """删除一列"""

    bl_idname = "efx.layoutbank_column_remove"
    bl_label = "Remove Column"
    bl_description = "Remove this column; its dependent column is removed with it"

    block_type: IntProperty(default=0, options={"HIDDEN"})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from ..efx_format.assembly import layoutbank as lb
        bt = self.block_type
        dropped = [bt] + [c for c, p in lb.COLUMN_PARENT.items() if p == bt]
        return _edit(self, context.active_object, lambda b: lb.remove_column(b, bt),
                     touched_columns=dropped)


class EFX_OT_layoutbank_row_edit(_LayoutOp, bpy.types.Operator):
    """编辑某一列在某一行上的值"""

    bl_idname = "efx.layoutbank_row_edit"
    bl_label = "Edit Values"
    bl_description = "Edit this column's values in this row"

    block_type: IntProperty(default=0, options={"HIDDEN"})
    row: IntProperty(default=0, options={"HIDDEN"})
    width: IntProperty(default=0, options={"HIDDEN"})
    fvals: FloatVectorProperty(size=_MAX_VALUES, precision=4, options={"HIDDEN"})
    ivals: IntVectorProperty(size=3, options={"HIDDEN"})

    def invoke(self, context, event):
        from ..efx_format.assembly import layoutbank as lb
        block = cached_block(context.active_object.efx_block)
        try:
            vals = lb.get_row(block, self.block_type, self.row)
        except lb.LayoutBankError as e:
            self.report({"WARNING"}, str(e))
            return {"CANCELLED"}
        if len(vals) > _MAX_VALUES:
            self.report({"WARNING"}, "Too many values in one row to edit here")
            return {"CANCELLED"}
        self.width = len(vals)
        if lb.column_kind(self.block_type) == "i32":
            self.ivals = [int(v) for v in vals]
        else:
            fv = list(self.fvals)
            fv[:len(vals)] = vals
            self.fvals = fv
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        from ..efx_format.assembly import layoutbank as lb
        layout = self.layout
        layout.label(text=T("layoutbank.edit_title").format(bt=self.block_type, row=self.row))
        is_int = lb.column_kind(self.block_type) == "i32"
        per_line = 3 if self.block_type in (0, 6) else 4
        for start in range(0, self.width, per_line):
            r = layout.row(align=True)
            for k in range(start, min(start + per_line, self.width)):
                r.prop(self, "ivals" if is_int else "fvals", index=k, text="")

    def execute(self, context):
        from ..efx_format.assembly import layoutbank as lb
        is_int = lb.column_kind(self.block_type) == "i32"
        vals = list(self.ivals)[:self.width] if is_int else list(self.fvals)[:self.width]
        return _edit(self, context.active_object,
                     lambda b: lb.set_row(b, self.block_type, self.row, vals))


class EFX_OT_layoutbank_page(_LayoutOp, bpy.types.Operator):
    """翻页"""

    bl_idname = "efx.layoutbank_page"
    bl_label = "Change Page"
    bl_description = "Show the previous or next rows"
    bl_options = {"INTERNAL"}

    delta: IntProperty(default=1, options={"HIDDEN"})

    def execute(self, context):
        obj = context.active_object
        block = cached_block(obj.efx_block)
        last = max(0, (int(block["count"]) - 1) // PAGE_ROWS)
        obj["efx_layoutbank_page"] = min(last, max(0, _page(obj) + self.delta))
        return {"FINISHED"}


# ── 绘制 ────────────────────────────────────────────────────────────────────

def _column_shape(bt, sub_count=1) -> str:
    from ..efx_format.assembly import layoutbank as lb
    kind = {"f32": "float", "f16": "half", "i32": "int"}[lb.column_kind(bt)]
    return "%d×%s" % (lb.row_width(bt, sub_count), kind)


def _fmt(v) -> str:
    return str(v) if isinstance(v, int) else ("%.4g" % v)


def draw_layout_bank_editor(layout, obj) -> None:
    """在 LAYOUT 前缀字段下方绘制布局表。"""
    from ..efx_format.assembly import layoutbank as lb

    bp = obj.efx_block
    try:
        block = cached_block(bp)
    except Exception:
        layout.label(text=T("attribute.layoutbank_decode_failed"), icon="ERROR")
        return
    count = int(block["count"])
    cols = block.get("columns", [])

    layout.separator(factor=0.5)
    box = layout.box()
    head = box.row(align=True)
    head.label(text=T("layoutbank.title").format(n=count), icon="MESH_GRID")
    head.operator_menu_enum("efx.layoutbank_column_add", "block_type",
                            text=T("layoutbank.add_column"), icon="ADD")
    hint = box.row()
    hint.enabled = False
    hint.label(text=T("layoutbank.flags_hint"))

    if cols:
        crow = box.row(align=True)
        for c in cols:
            bt = int(c["blockType"])
            sub = crow.row(align=True)
            sub.label(text="%d (%s)" % (bt, _column_shape(bt, c.get("subCount", 1))))
            op = sub.operator("efx.layoutbank_column_remove", text="", icon="X", emboss=False)
            op.block_type = bt
    else:
        box.label(text=T("layoutbank.no_columns"))

    if count <= 0:
        op = box.operator("efx.layoutbank_row_add", text=T("layoutbank.add_row"), icon="ADD")
        op.row = -1
        op.copy = False
        return

    last_page = (count - 1) // PAGE_ROWS
    page = min(_page(obj), last_page)
    start = page * PAGE_ROWS
    end = min(count, start + PAGE_ROWS)
    nav = box.row(align=True)
    prev = nav.row(align=True)
    prev.enabled = page > 0
    prev.operator("efx.layoutbank_page", text="", icon="TRIA_LEFT").delta = -1
    nav.label(text=T("layoutbank.page").format(a=start, b=end - 1, n=count))
    nxt = nav.row(align=True)
    nxt.enabled = page < last_page
    nxt.operator("efx.layoutbank_page", text="", icon="TRIA_RIGHT").delta = 1

    for r in range(start, end):
        rb = box.column(align=True)
        rh = rb.row(align=True)
        rh.label(text=T("layoutbank.row").format(i=r))
        add = rh.operator("efx.layoutbank_row_add", text="", icon="DUPLICATE", emboss=False)
        add.row = r
        add.copy = True
        rm = rh.row(align=True)
        rm.enabled = count > 1
        rm.operator("efx.layoutbank_row_remove", text="", icon="REMOVE", emboss=False).row = r
        for c in cols:
            bt = int(c["blockType"])
            vals = lb.get_row(block, bt, r)
            vr = rb.row(align=True)
            vr.label(text="%d:  %s" % (bt, ", ".join(_fmt(v) for v in vals)))
            ed = vr.operator("efx.layoutbank_row_edit", text="", icon="GREASEPENCIL",
                             emboss=False)
            ed.block_type = bt
            ed.row = r


_CLASSES = (
    EFX_OT_layoutbank_row_add,
    EFX_OT_layoutbank_row_remove,
    EFX_OT_layoutbank_column_add,
    EFX_OT_layoutbank_column_remove,
    EFX_OT_layoutbank_row_edit,
    EFX_OT_layoutbank_page,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
    _BLOCK_CACHE.clear()
