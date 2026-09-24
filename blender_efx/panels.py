"""绘制 EFX 数据、属性字段和编辑面板。

维护约束：
- 面板仅展示或调用既有算子；字段名转换与布局分组不改变底层 schema 或字节布局。
- 字段注释、动画和专用控件必须仍以原始 ``ori_name`` 查找数据。
- 复杂的纯布局规则归属 layout_model.py，本模块只负责 Blender UI 适配。
"""

import os
import re
import bpy
from .subselect import EFX_PT_subselect, EFX_PT_subselect_data
from .action_emitter import EFX_PT_action, EFX_PT_action_props
from .extern_ref import EFX_PT_extern_ref
from .entry_action_ref import (
    EFX_PT_eof_list,
    EFX_OT_eof_toggle_entry,
    is_entry_in_eof,
)
from .backref import (
    EFX_PT_extern_backref,
    EFX_PT_entry_backref,
    EFX_PT_root_states,
    is_entry_action_triggered,
    classify_entry_activation,
)
from .add_ops import get_active_efx_root
from . import reorder as _reorder
from . import i18n
from .i18n import T
from . import root_collection as _rc
from . import extern_props as _extern_props
from . import color_fields as _cf


# 字段显示基础设施。

def _friendly_name(ori_name: str, type_name: str = "") -> str:
    """返回字段显示名；内部提示字段与数据查找键保持原样。"""
    # 内部提示字段不是用户可编辑字段。
    if ori_name.startswith("__") and ori_name.endswith("__"):
        return ori_name

    # 中文标签缺失时回退英文显示名。
    from .i18n import get_lang
    if get_lang() == "ZH":
        from ..efx_format.schema.labels import field_label_zh
        zh = field_label_zh(type_name or None, ori_name)
        if zh:
            return zh

    # 标签表优先于自动拆词，维持既有 UI 名称。
    from ..efx_format.schema.labels import field_label_en
    en = field_label_en(type_name or None, ori_name)
    if en:
        return en

    s = ori_name

    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)

    s = s.replace("_", " ")

    s = re.sub(r' +', ' ', s).strip()

    if s:
        s = s[0].upper() + s[1:]

    return s



def _draw_field_row_buttons(row, type_name: str, ori_name: str,
                            item=None, timl: bool = True,
                            anno_name: str = "") -> None:
    """绘制字段注释与 TIML 按钮；两者可使用不同的原始查找名。"""
    if not type_name:
        return
    from .annotations import get_annotation
    _aname = anno_name or ori_name
    if get_annotation(type_name, _aname):
        op = row.operator(
            "efx.field_help",
            text="",
            icon="INFO",
            emboss=False,
        )
        op.type_name = type_name
        op.field_name = _aname
    if timl:
        try:
            from . import timl_tracks as _tt
            _tt.draw_field_timl_buttons(row, type_name, ori_name, item)
        except Exception:
            pass


# 纯布局规则由 layout_model.py 提供；此处只适配 Blender 控件。
from .layout_model import (
    SCALAR_PROP_ATTR as _SCALAR_PROP_ATTR,
    AXIS_GROUPS,
    is_jitter_name as _is_jitter_name,
    is_matching_jitter as _is_matching_jitter,
    resolve_axis_groups as _resolve_axis_groups,
)


def reorder_items_for_display(type_name: str, items):
    """查 `efx_format/field_order.py` 的锚点表，订正字段显示顺序（算法见 layout_model）。"""
    from . import layout_model as _lm
    try:
        from ..efx_format.field_order import display_anchors
    except ImportError:
        return list(items)
    return _lm.reorder_units(items, display_anchors(type_name))


def addon_prefs():
    """返回插件偏好；包名变化或未注册时返回 None。"""
    try:
        key = __package__.rsplit(".", 1)[0] if "." in __package__ else __package__
        return bpy.context.preferences.addons[key].preferences
    except Exception:
        return None


def field_tiers_enabled() -> bool:
    """返回是否启用常用/高级字段分档。"""
    prefs = addon_prefs()
    return bool(getattr(prefs, "field_tiers", False)) if prefs else False


def classify_field_tiers(type_name: str, items, axis_group_at: dict, axis_group_consumed):
    """查 `efx_format/field_tiers.py` 的分档表，分出常用/高级（算法见 layout_model）。"""
    from . import layout_model as _lm
    try:
        from ..efx_format.field_tiers import advanced_names
    except ImportError:
        return set(), set()
    return _lm.classify_tiers(items, advanced_names(type_name),
                              axis_group_at, axis_group_consumed)


# 这些字段复用 jitter 布局，但显示为 offset/size，不能改动原始字段名。
_OFFSET_SIZE_PAIRS = {
    ("EMITTERSHAPE2D", "rangeX"),
    ("EMITTERSHAPE2D", "rangeY"),
}


def _draw_value_jitter_pair(layout, vitem, jitem, type_name: str = "", label_override=None):
    """将 value/jitter 配对绘制为同一行；特定字段显示为 offset/size。"""
    fname = label_override if label_override else _friendly_name(vitem.ori_name, type_name)
    vattr = _SCALAR_PROP_ATTR[vitem.data_type]
    jattr = _SCALAR_PROP_ATTR[jitem.data_type]

    if (type_name, vitem.ori_name) in _OFFSET_SIZE_PAIRS:
        lbl_a, lbl_b = T("field.offset"), T("field.size")
    else:
        lbl_a, lbl_b = T("field.static"), T("field.random")

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=fname)
    sub = split.row(align=True)
    sub.prop(vitem, vattr, text=lbl_a)
    sub.prop(jitem, jattr, text=lbl_b)
    _draw_field_row_buttons(row, type_name, vitem.ori_name, item=vitem)


def _draw_axis_group(layout, type_name: str, group, item_by_name: dict):
    """绘制一个虚拟轴向组合控件：标题行 + 逐轴行（跟 FLOAT6 同款）。"""
    title_key, axes = group
    fname = _friendly_name(title_key, type_name)
    first_base = axes[0][1]

    title_row = layout.row(align=True)
    title_row.scale_y = 1.1
    title_row.use_property_split = False
    title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
    # 标题借首轴注释；动画按钮必须对应各轴自身字段。
    _draw_field_row_buttons(title_row, type_name, first_base, timl=False)

    for axis_label, base in axes:
        vitem = item_by_name[base]
        jitem = item_by_name.get(base + "Jitter")
        vattr = _SCALAR_PROP_ATTR[vitem.data_type]

        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        row.label(text=axis_label, icon="BLANK1")
        vals = row.row(align=True)
        if jitem is not None:
            jattr = _SCALAR_PROP_ATTR[jitem.data_type]
            vals.prop(vitem, vattr, text=T("field.static"))
            vals.prop(jitem, jattr, text=T("field.random"))
        else:
            vals.prop(vitem, vattr, text="")
        _draw_field_row_buttons(row, type_name, base, item=vitem)


def _xyz_prop_name(item, base_prop):
    """选择绘制哪个属性：Scene.efx_blender_coords 开 且 该字段有单位映射时用 *_display
    （Blender 约定显示/编辑），否则用原 *_value（游戏原值）。返回 (prop_name, is_blender)。"""
    try:
        if getattr(bpy.context.scene, "efx_blender_coords", False):
            from . import fields as _f
            if _f.xyz_unit_for_item(item) is not None:
                return base_prop.replace("_value", "_display"), True
    except Exception:
        pass
    return base_prop, False


def _field_is_enum(type_name: str, ori_name: str) -> bool:
    """该字段是否被 typed Field 模型标为 enum widget（据 FIELD_REGISTRY 反查）。"""
    if not type_name:
        return False
    try:
        from ..efx_format.hashes import NAME_TO_HASH
        from ..efx_format.schema.fields_model import FIELD_REGISTRY
        h = NAME_TO_HASH.get(type_name)
        if h is None:
            return False
        f = FIELD_REGISTRY.get((h, ori_name))
        return f is not None and getattr(f, "widget", None) == "enum"
    except Exception:
        return False


def _field_is_enum_vec3(type_name: str, ori_name: str) -> bool:
    """该字段是否被 typed Field 模型标为 enum_vec3（逐轴枚举）。"""
    if not type_name:
        return False
    try:
        from ..efx_format.hashes import NAME_TO_HASH
        from ..efx_format.schema.fields_model import FIELD_REGISTRY
        h = NAME_TO_HASH.get(type_name)
        if h is None:
            return False
        f = FIELD_REGISTRY.get((h, ori_name))
        return f is not None and getattr(f, "widget", None) == "enum_vec3"
    except Exception:
        return False


def _field_is_bool(type_name: str, ori_name: str) -> bool:
    """该字段是否被 typed Field 模型标为 bool（勾选框）。"""
    if not type_name:
        return False
    try:
        from ..efx_format.hashes import NAME_TO_HASH
        from ..efx_format.schema.fields_model import FIELD_REGISTRY
        h = NAME_TO_HASH.get(type_name)
        if h is None:
            return False
        f = FIELD_REGISTRY.get((h, ori_name))
        return f is not None and getattr(f, "widget", None) == "bool"
    except Exception:
        return False


def _bitmask_field(type_name: str, ori_name: str):
    """该字段的 Bitmask Field（widget=='bitmask'），否则 None。"""
    if not type_name:
        return None
    try:
        from ..efx_format.hashes import NAME_TO_HASH
        from ..efx_format.schema.fields_model import FIELD_REGISTRY
        h = NAME_TO_HASH.get(type_name)
        if h is None:
            return None
        f = FIELD_REGISTRY.get((h, ori_name))
        if f is not None and getattr(f, "widget", None) == "bitmask":
            return f
    except Exception:
        pass
    return None


def _draw_field_item(layout, item, type_name: str = "", label_override=None, obj=None,
                     anno_name: str = ""):
    """
    按 item.data_type 在 layout 上绘制对应控件（属性字段显示重设计版）。

    FLOAT6（XYZ type 0）：
      字段名一行（友好名 + ⓘ）+ 3 行（X/Y/Z，每行 Static index 和 Random index）。
      float6_value 顺序 = [fixed_x(0), random_x(1), fixed_y(2), random_y(3), fixed_z(4), random_z(5)]

    INT3（XYZ type 1）：
      字段名一行（友好名 + ⓘ）+ 1 行（X index=0, Y index=1, Z index=2）。

    FLOAT3（XYZ type 3 / float[3]）：
      字段名一行（友好名 + ⓘ）+ 1 行（X index=0, Y index=1, Z index=2）。

    COLOR_RGBA：
      字段名一行（友好名）+ 色块行（色块 + A 滑块 + ⓘ）。

    标量/字符串/OPAQUE 等：
      单行：友好名 | 值控件 | ⓘ（若有）。

    所有行 scale_y=1.1（ctc 风格）。
    手动 index 分量行强制 use_property_split=False，防止 property_split 打乱布局。
    """
    dtype = item.data_type
    # ⓘ 注释查表用的字段名：默认 ori_name；PTBEHAVIOR 的 param 行 ori_name 是
    # 'p3' 这样的序号占位，由调用方传参数真名（hint_name）进来。
    _anno = anno_name or item.ori_name
    # 保留填充字段（0xCD 占位）→ 关闭编辑：把 layout 重指向一个 enabled=False 的子列，
    # 后续所有控件都画进它（只读灰显）。导出时该字段未编辑 → 走原字节，byte-perfect 不变。
    from .field_labels import is_reserved_fill
    if is_reserved_fill(type_name, item.ori_name):
        layout = layout.column(align=True)
        layout.enabled = False
    # 友好显示名（仅显示，逻辑用 ori_name）；label_override 优先（如 MATERIAL 路径的槽名）
    fname = label_override if label_override else _friendly_name(item.ori_name, type_name)

    # ── 枚举字段 → 下拉（纯显示层，值仍存 int 槽）─────────────────────────────────
    # 仅定长块（FIELD_REGISTRY 标了 enum widget）的 int 背板字段；read_only 字段回退普通渲染。
    if (dtype in ("INT", "BYTE1", "SHORT1", "UINT") and not item.read_only
            and _field_is_enum(type_name, item.ori_name)):
        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        split = row.split(factor=0.45)
        split.label(text=fname)
        split.prop(item, "enum_proxy", text="")
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=_anno)
        return

    # ── Bool 字段 → 勾选框（纯显示层，值仍存 int 槽）────────────────────────────────
    if (dtype in ("INT", "BYTE1", "SHORT1", "UINT") and not item.read_only
            and _field_is_bool(type_name, item.ori_name)):
        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        split = row.split(factor=0.45)
        split.label(text=fname)
        split.prop(item, "bool_proxy", text="")
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=_anno)
        return

    # ── Bitmask 字段 → 摘要 + 弹窗编辑按钮（纯显示层，值仍存 int 槽）─────────────────
    _bm = _bitmask_field(type_name, item.ori_name) if dtype in ("INT", "BYTE1", "SHORT1", "UINT") else None
    if _bm is not None and not item.read_only:
        from . import bitmask_ops, fields as _f
        from .i18n import get_lang
        val = _f._enum_backing_read(item)
        summ = bitmask_ops.bitmask_summary(val, _bm, zh=(get_lang() == "ZH"))
        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        split = row.split(factor=0.45)
        split.label(text=fname)
        op = split.operator("efx.edit_bitmask", text=(summ or "…"), icon="CHECKBOX_HLT")
        op.type_name = type_name
        op.field = item.ori_name
        if obj is not None:
            op.obj_name = obj.name
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=_anno)
        return

    # EnumVec3 以三个轴向下拉控件显示。
    if (dtype == "INT3" and not item.read_only
            and _field_is_enum_vec3(type_name, item.ori_name)):
        title = layout.row(align=True)
        title.scale_y = 1.1
        title.use_property_split = False
        title.label(text=fname)
        _draw_field_row_buttons(title, type_name, item.ori_name, item=item, anno_name=_anno)
        for axis, prop in (("X", "enum_vec3_x"), ("Y", "enum_vec3_y"), ("Z", "enum_vec3_z")):
            r = layout.row(align=True)
            r.scale_y = 1.1
            r.use_property_split = False
            r.label(text=axis, icon="BLANK1")
            r.prop(item, prop, text="")
        return

    # FLOAT6 分量按 X/Y/Z 的固定值与随机值配对。
    if dtype == "FLOAT6":
        prop6, is_b = _xyz_prop_name(item, "float6_value")
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=(fname + (" [Blender]" if is_b else "")), icon="ORIENTATION_GLOBAL")
        _draw_field_row_buttons(title_row, type_name, item.ori_name, item=item, anno_name=_anno)

        # rangeXYZ 使用 offset/size，而非 static/random 语义。
        if type_name == "EMITTERSHAPE3D" and item.ori_name == "rangeXYZ":
            lbl_a, lbl_b = T("field.offset"), T("field.size")
        else:
            lbl_a, lbl_b = T("field.static"), T("field.random")

        # X 行：index=0 / index=1
        x_row = layout.row(align=True)
        x_row.scale_y = 1.1
        x_row.use_property_split = False
        x_row.label(text="X", icon="BLANK1")
        x_row.prop(item, prop6, index=0, text=lbl_a)
        x_row.prop(item, prop6, index=1, text=lbl_b)

        # Y 行：index=2 / index=3
        y_row = layout.row(align=True)
        y_row.scale_y = 1.1
        y_row.use_property_split = False
        y_row.label(text="Y", icon="BLANK1")
        y_row.prop(item, prop6, index=2, text=lbl_a)
        y_row.prop(item, prop6, index=3, text=lbl_b)

        # Z 行：index=4 / index=5
        z_row = layout.row(align=True)
        z_row.scale_y = 1.1
        z_row.use_property_split = False
        z_row.label(text="Z", icon="BLANK1")
        z_row.prop(item, prop6, index=4, text=lbl_a)
        z_row.prop(item, prop6, index=5, text=lbl_b)
        return

    # INT3 以 X/Y/Z 分量显示。
    if dtype == "INT3":
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
        _draw_field_row_buttons(title_row, type_name, item.ori_name, item=item, anno_name=_anno)

        comp_row = layout.row(align=True)
        comp_row.scale_y = 1.1
        comp_row.use_property_split = False
        comp_row.label(text="", icon="BLANK1")
        comp_row.prop(item, "int3_value", index=0, text="X")
        comp_row.prop(item, "int3_value", index=1, text="Y")
        comp_row.prop(item, "int3_value", index=2, text="Z")
        return

    # FLOAT3 以 X/Y/Z 分量显示。
    if dtype == "FLOAT3":
        prop3, is_b = _xyz_prop_name(item, "float3_value")
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=(fname + (" [Blender]" if is_b else "")), icon="ORIENTATION_GLOBAL")
        _draw_field_row_buttons(title_row, type_name, item.ori_name, item=item, anno_name=_anno)

        comp_row = layout.row(align=True)
        comp_row.scale_y = 1.1
        comp_row.use_property_split = False
        comp_row.label(text="", icon="BLANK1")
        comp_row.prop(item, prop3, index=0, text="X")
        comp_row.prop(item, prop3, index=1, text="Y")
        comp_row.prop(item, prop3, index=2, text="Z")
        return

    # COLOR_RGBA 的第四分量始终显示为 alpha。
    if dtype == "COLOR_RGBA":
        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        split = row.split(factor=0.45)
        split.label(text=fname)
        val_row = split.row(align=True)
        val_row.prop(item, "color_rgba_value", text="")
        val_row.prop(item, "color_rgba_value", index=3, text="A", slider=True)
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=_anno)
        return

    # FLOAT4 分量按 X/Y 的固定值与随机值配对。
    if dtype == "FLOAT4":
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
        _draw_field_row_buttons(title_row, type_name, item.ori_name, item=item, anno_name=_anno)

        x_row = layout.row(align=True)
        x_row.scale_y = 1.1
        x_row.use_property_split = False
        x_row.label(text="X", icon="BLANK1")
        x_row.prop(item, "float4_value", index=0, text=T("field.static"))
        x_row.prop(item, "float4_value", index=1, text=T("field.random"))

        y_row = layout.row(align=True)
        y_row.scale_y = 1.1
        y_row.use_property_split = False
        y_row.label(text="Y", icon="BLANK1")
        y_row.prop(item, "float4_value", index=2, text=T("field.static"))
        y_row.prop(item, "float4_value", index=3, text=T("field.random"))
        return

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=fname)

    if dtype == "FLOAT":
        split.prop(item, "float_value", text="")
    elif dtype == "INT":
        split.prop(item, "int_value", text="")
    elif dtype == "UINT":
        split.prop(item, "uint_str", text="")
    elif dtype == "BOOL":
        split.prop(item, "bool_value", text="")
    elif dtype == "BYTE1":
        split.prop(item, "byte1_value", text="")
    elif dtype == "SHORT1":
        split.prop(item, "short1_value", text="")
    elif dtype == "FLOAT2":
        split.prop(item, "float2_value", text="")
    elif dtype == "COLOUR":
        split.prop(item, "colour_value", text="")
    elif dtype == "INT2":
        split.prop(item, "int2_value", text="")
    elif dtype == "INT4":
        split.prop(item, "int4_value", text="")
    elif dtype == "INT_PAIR":
        split.prop(item, "int_pair_str", text="")
    elif dtype == "FLOAT2_STR":
        split.prop(item, "float2_str", text="")
    elif dtype == "FLOAT3_STR":
        split.prop(item, "float3_str", text="")
    elif dtype == "FLOAT5_STR":
        split.prop(item, "float5_str", text="")
    elif dtype == "FLOAT8_STR":
        split.prop(item, "float8_str", text="")
    elif dtype == "FLOAT16_STR":
        split.prop(item, "float16_str", text="")
    elif dtype == "INT10_STR":
        split.prop(item, "int10_str", text="")
    elif dtype == "INT16_STR":
        split.prop(item, "int16_str", text="")
    elif dtype == "ARRAY_STR":
        split.prop(item, "array_str", text="")
    elif dtype == "OPAQUE":
        if item.ori_name.startswith("__"):
            split.label(text=item.opaque_str)
        else:
            split.label(text=T("field.read_only"))
    elif dtype == "STRING":
        split.prop(item, "string_value", text="")
    else:
        split.label(text=T("field.unknown_type"))

    if type_name == "RANDOMFIX":
        if item.ori_name.startswith("randomSeedTable"):
            _seed_op = row.operator("efx.randomize_seed", text="", icon="RNDCURVE")
            _seed_op.field = item.ori_name
        elif item.ori_name == "tableSelectionGroup":
            row.operator("efx.randomfix_set_table_group", text="", icon="DOWNARROW_HLT")

    if dtype not in ("OPAQUE",) and not item.ori_name.startswith("__"):
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=_anno)


# 专用字段控件。

# 位掩码的各行共享底层整数槽；注释仍指向完整位掩码字段。

def _draw_bitmask_bit_row(layout, item, type_name, bit_index, label, *, anno_name=None, show_info=True):
    """画一行：标签 | 单个位的勾选框 | （可选）ⓘ 提示按钮。"""
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=label)
    split.prop(item, "bitmask_bools", index=bit_index, text="")
    if show_info:
        _draw_field_row_buttons(row, type_name, item.ori_name, item=item,
                                 anno_name=anno_name or item.ori_name)


def _draw_tubelight_int_as_color(layout, item, type_name, label):
    """headColor/tailColor：打包 RGBA 颜色选择器。"""
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=label)
    val_row = split.row(align=True)
    val_row.prop(item, "int_as_color_display", text="")
    val_row.prop(item, "int_as_color_display", index=3, text="A", slider=True)
    _draw_field_row_buttons(row, type_name, item.ori_name, item=item)



def _draw_shadersettings_preset_id(layout, item, type_name, label):
    """presetId：预设名字符串输入框 + 已知名字下拉。"""
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=label)
    val_row = split.row(align=True)
    val_row.prop(item, "preset_name_display", text="")
    val_row.menu("EFX_MT_shadersettings_preset_picker", text="", icon="DOWNARROW_HLT")
    _draw_field_row_buttons(row, type_name, item.ori_name, item=item)


# RGBFIRE/RGBWATER 分组只改变显示标签，注释查找仍使用 ori_name。

_RGBFIRE_ROW_LABELS = {
    "colorRate":   ("总体亮度", "Overall Brightness"),
    "alphaFactor": ("总体透明度", "Overall Alpha"),
    "fireColorParam_correctColorNo":  ("EPV 颜色修正槽位", "EPV Color Slot"),
    "fireColor":                      ("颜色", "Color"),
    "fireFactor":                     ("强度", "Factor"),
    "fireColorParam_lighting":        ("受光照影响", "Lighting"),
    "fireColorParam_useLife":         ("启用生命周期", "Use Life"),
    "fireColorParam_appearFrame":     ("淡入", "Appear"),
    "fireColorParam_keepFrame":       ("持续", "Keep"),
    "fireColorParam_vanishFrame":     ("淡出", "Vanish"),
    "fireColorParam_lifeType":        ("生命期模式", "Life Type"),
    "smokeColorParam_correctColorNo": ("EPV 颜色修正槽位", "EPV Color Slot"),
    "smokeColor":                     ("颜色", "Color"),
    "redChFactor":                    ("强度", "Factor"),
    "smokeColorParam_lighting":       ("受光照影响", "Lighting"),
    "smokeColorParam_useLife":        ("启用生命周期", "Use Life"),
    "smokeColorParam_appearFrame":    ("淡入", "Appear"),
    "smokeColorParam_keepFrame":      ("持续", "Keep"),
    "smokeColorParam_vanishFrame":    ("淡出", "Vanish"),
    "smokeColorParam_lifeType":       ("生命期模式", "Life Type"),
}


def _draw_section_header(layout, zh: bool, text_zh: str, text_en: str):
    """绘制 RGBFIRE/RGBWATER 共用的次要分组标题。"""
    row = layout.row()
    row.active = False
    row.label(text=text_zh if zh else text_en)



_RGBWATER_ROW_LABELS = {
    "colorRate":      ("总体亮度", "Overall Brightness"),
    "intensityAlpha": ("总体透明度", "Overall Alpha"),
    "specularColorParam_correctColorNo": ("EPV 颜色修正槽位", "EPV Color Slot"),
    "colorSpecular":                     ("颜色", "Color"),
    "intensitySpecular":                 ("强度", "Factor"),
    "specularColorParam_lighting":       ("受光照影响", "Lighting"),
    "specularColorParam_useLife":        ("启用生命周期", "Use Life"),
    "specularColorParam_appearFrame":    ("淡入", "Appear"),
    "specularColorParam_keepFrame":      ("持续", "Keep"),
    "specularColorParam_vanishFrame":    ("淡出", "Vanish"),
    "specularColorParam_lifeType":       ("生命期模式", "Life Type"),
    "sheetColorParam_correctColorNo": ("EPV 颜色修正槽位", "EPV Color Slot"),
    "colorSheet":                     ("颜色", "Color"),
    "intensitySheet":                 ("强度", "Factor"),
    "sheetColorParam_lighting":       ("受光照影响", "Lighting"),
    "sheetColorParam_useLife":        ("启用生命周期", "Use Life"),
    "sheetColorParam_appearFrame":    ("淡入", "Appear"),
    "sheetColorParam_keepFrame":      ("持续", "Keep"),
    "sheetColorParam_vanishFrame":    ("淡出", "Vanish"),
    "sheetColorParam_lifeType":       ("生命期模式", "Life Type"),
    "cubemapPath":      ("环境反射贴图", "Environment Reflection Map"),
    "intensityCubeMap": ("环境反射强度", "CubeMap Factor"),
    "waterLerpGtoB":            ("Alpha 混入蓝通道比例", "Lerp Alpha To Blue"),
    "waterLerpParam_lighting":  ("受光照影响", "Lighting"),
    "waterLerpParam_useLife":   ("启用生命周期", "Use Life"),
    "waterLerpParam_appearFrame": ("淡入", "Appear"),
    "waterLerpParam_keepFrame":   ("持续", "Keep"),
    "waterLerpParam_vanishFrame": ("淡出", "Vanish"),
    "waterLerpParam_lifeType":    ("生命期模式", "Life Type"),
}


def _ptb_item_is_color(item) -> bool:
    """PTBEHAVIOR 的 FLOAT4 param 是不是颜色（名字以 Color 结尾，同 names.is_color_param）。"""
    nm = getattr(item, "hint_name", "") or ""
    return nm.endswith("Color")


# PTBEHAVIOR 里元素数 ≤4 的数组值槽 → (属性名, 元素数)。通用块那边 FLOAT3 是
# 「标题行 + XYZ 行」两行、FLOAT4 是 static/random 2×2 四行，那套排版为 XYZ 轴向字段
# 设计，套在 behavior 的 vector 参数上只是白占地方——这里一律压成一行。
_PTB_VECTOR_PROPS = {
    "FLOAT2": ("float2_value", 2),
    "FLOAT3": ("float3_value", 3),
    "FLOAT4": ("float4_value", 4),
    "INT2":   ("int2_value", 2),
    "INT3":   ("int3_value", 3),
    "INT4":   ("int4_value", 4),
}


def _draw_ptb_vector_row(layout, item, type_name, label):
    """PTBEHAVIOR 的非颜色小数组（vector2/3/4、2×int32）：一行画完。"""
    prop, n = _PTB_VECTOR_PROPS[item.data_type]
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=label)
    val_row = split.row(align=True)
    for idx in range(n):
        val_row.prop(item, prop, index=idx, text="")
    _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=item.hint_name)


def _draw_ptb_float4_as_color(layout, item, type_name, label):
    """PTBEHAVIOR 的 4×float32 颜色参数（mColor）：色块 + A 滑块。

    底层值仍是 float4_value 四个原始 float（非 0-1 归一），色块只是显示层。这类颜色是
    HDR 倍率，色块属性只设 soft_max=1、不设硬上限，所以能拖/输入到 1 以上。
    """
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=label)
    val_row = split.row(align=True)
    val_row.prop(item, "float4_as_color_display", text="")
    val_row.prop(item, "float4_as_color_display", index=3, text="A", slider=True)
    _draw_field_row_buttons(row, type_name, item.ori_name, item=item, anno_name=item.hint_name)


# ─────────────────────────────────────────────────────────────────────────────
# MATERIAL（Phase C）：结构化材质槽编辑器
#
# _material_groups: {block_index: {'shader_item': EFXFieldItem,
#                                    'slots': [(t_hash, EFXFieldItem), ...]}}
# 见 fields._init_material_attribute 的 item 命名约定（matshader_{j} / slotpath_{j}_{t}）。
# ─────────────────────────────────────────────────────────────────────────────

def _draw_material_param_row(layout, pit, label) -> None:
    """画一条着色器参数：FLOAT4 且名字带 "__uiColor" 后缀（mrl3 属性名自带的
    UI 部件类型提示，同一套还有 __uiUNorm/__uiSNorm/__uiDirection——这些是原版
    游戏 shader 定义里自带的、不是我们猜的）的画色块（复用 PTBEHAVIOR 的
    float4_as_color_display，HDR 不做 0-1 硬夹取，同一套值槽/风格）；其余 FLOAT4
    用通用向量单行（不套 XYZ/Static-Random 语义，那套是给位置/速度这类场信息
    用的）；BOOL/UINT/FLOAT 走 _draw_field_item 的通用单行分支（对这几个 dtype
    没有特殊语义分叉，直接复用安全）。"""
    if pit.data_type == "FLOAT4":
        if label.endswith("__uiColor"):
            _draw_ptb_float4_as_color(layout, pit, "MATERIAL", label)
        else:
            _draw_ptb_vector_row(layout, pit, "MATERIAL", label)
    else:
        _draw_field_item(layout, pit, type_name="MATERIAL", label_override=label)


def _draw_material_editor(layout, context, material_groups: dict) -> None:
    """绘制材质槽列表：每槽一个框（主材质/材质名/更改类型/删除），槽内先是贴图
    路径，再是槽末尾"其它参数"区平铺全部值得展示的着色器参数（曾按命名约定把
    参数分组挂在对应贴图行下面折叠展开，因分类还不够可靠先退回平铺，见
    [[material-panel-redesign-and-mrl3-reference-add]]）。末尾是参考 mrl3 新建
    材质槽的入口（跟 mesh/Model Editor 完全解耦）。"""
    from ..efx_format.material import meta as _mm
    from ..efx_format.material import params as _mparams

    if not material_groups:
        row = layout.row(align=True)
        row.enabled = False
        row.label(text=T("material.no_slots"), icon="INFO")
    else:
        for j in sorted(material_groups):
            info = material_groups[j]
            sh_item = info.get("shader_item")
            shader_hash = int(sh_item.uint_str) if sh_item and sh_item.uint_str else 0
            type_name_disp = _mm.material_type_name(shader_hash)
            label = type_name_disp if type_name_disp else f"Hash {shader_hash}"

            slot_box = layout.box()
            slot_col = slot_box.column(align=True)

            # ── 标题行：[材质槽 N] 主材质：XXX ──────────────────────────────
            header_row = slot_col.row(align=True)
            header_row.scale_y = 1.1
            header_row.label(
                text=f"[{T('material.slot')} {j}] {T('material.main_type')}: {label}",
                icon="MATERIAL",
            )
            op_change = header_row.operator(
                "efx.material_set_shader", text="", icon="TRIA_DOWN_BAR",
            )
            op_change.block_index = j
            op_remove = header_row.operator("efx.material_remove_block", text="", icon="X")
            op_remove.block_index = j

            if type_name_disp is None:
                hint_row = slot_col.row(align=True)
                hint_row.enabled = False
                hint_row.label(text=T("material.unknown_schema"))

            # ── 材质名行：材质名：XXX（可编辑/绑定）─────────────────────────
            name_item = info.get("name_item")
            name_hash = int(name_item.uint_str) if name_item and name_item.uint_str else 0
            name_row = slot_col.row(align=True)
            name_row.scale_y = 1.1
            name_row.use_property_split = False
            name_split = name_row.split(factor=0.45)
            name_split.label(text=T("material.name_field"))
            val_row = name_split.row(align=True)
            if name_hash == 0:
                val_row.alert = True
                val_row.prop(name_item, "material_name_proxy", text="", icon="ERROR")
            else:
                val_row.prop(name_item, "material_name_proxy", text="", icon="LINKED")
            # 从联动导入绑定的实际网格材质槽名里挑一个（保证不打错字），文本框
            # 本身也能直接手打任意名字（同 MHW_Model_Editor 材质名字段的用法）。
            op_name = name_row.operator("efx.material_set_name", text="", icon="DOWNARROW_HLT")
            op_name.block_index = j
            if name_hash == 0:
                unbound_row = slot_col.row(align=True)
                unbound_row.enabled = False
                unbound_row.label(text=T("material.name_unbound"), icon="BLANK1")

            slot_col.separator(factor=0.3)

            # ── 贴图槽：只画路径 ─────────────────────────────────────────────
            # 曾经按命名约定（tEmissiveMap ~ fEmissiveMapFactor）把参数分组挂在
            # 贴图行下面折叠展开；用户反馈这套子串匹配还没分类清楚（漏配/错配，
            # 见 [[material-panel-redesign-and-mrl3-reference-add]]），先退回
            # 全部参数平铺进"其它参数"区，等分类规则更可靠了再考虑重新分组。
            params_list = info.get("params", [])

            for t, sit in info.get("slots", []):
                slot_name = _mm.texture_slot_name(t)
                slot_label = slot_name if slot_name else f"Hash 0x{t:08X}"

                row = slot_col.row(align=True)
                row.scale_y = 1.1
                row.use_property_split = False
                split = row.split(factor=0.45)
                split.label(text=slot_label)
                val_row = split.row(align=True)
                val_row.prop(sit, "string_value", text="")
                _draw_field_row_buttons(row, "MATERIAL", sit.ori_name, item=sit)

            # ── 其它参数：全部值得展示的可调参数 ─────────────────────────────
            leftover = [
                (t, pit) for t, pit in params_list
                if _mparams.param_is_notable(shader_hash, t)
            ]
            if leftover:
                slot_col.separator(factor=0.3)
                other_row = slot_col.row(align=True)
                other_row.enabled = False
                other_row.label(text=T("material.other_params"))
                for t, pit in leftover:
                    hit = _mparams.param_name_type(shader_hash, t)
                    plabel = hit[0] if hit else f"Hash 0x{t:08X}"
                    _draw_material_param_row(slot_col, pit, plabel)

    add_row = layout.row(align=True)
    add_row.operator_menu_enum(
        "efx.material_add_block", "shader_choice",
        text=T("material.add_slot"), icon="ADD",
    )

    # 参考 mrl3 新建材质槽：选中的具体材质类型/材质名/贴图路径全部照抄，跟本 EFX
    # 文件、mesh/Model Editor 完全无关，纯读一个独立文件（见 mrl3_reader.py）。
    scene = getattr(context, "scene", None)
    ref_path = getattr(scene, "efx_material_ref_mrl3_path", "") if scene is not None else ""
    filter_row = layout.row(align=True)
    filter_row.operator("efx.material_pick_mrl3_reference", text=T("material.pick_mrl3"), icon="FILEBROWSER")
    if ref_path:
        filter_row.operator("efx.material_clear_mrl3_reference", text="", icon="X")
        add_ref_row = layout.row(align=True)
        add_ref_row.operator_menu_enum(
            "efx.material_add_from_mrl3", "material_choice",
            text=T("material.add_from_mrl3").format(src=os.path.basename(ref_path)), icon="ADD",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 预设面板 — 动态 EnumProperty items 回调
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# EXTERNREFERENCE referenceIndex 字段的内联指针 UI
# ─────────────────────────────────────────────────────────────────────────────

def _draw_extern_ref_field(layout, obj) -> None:
    """
    在属性字段列表中，把 EXTERNREFERENCE 的 referenceIndex 字段
    替换为 extern 指针选择器（内联在字段列表里，风格与其他字段一致）。

    三种显示情况：
      - pointerized=False（死属性）：显示只读标签"[dead attribute]"
      - pointerized=True + none=True：显示"(-1 哨兵)"标签
      - pointerized=True + none=False：显示 EFX_EXTERN 对象选择器
    """
    try:
        props = obj.efx_extern_ref
    except AttributeError:
        # efx_extern_ref 未注册或对象无此属性：回退到普通 INT 显示（由调用方继续）
        return

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=T("extern.reference_index"))

    if not props.extern_ref_pointerized:
        # 死属性/越界：只读提示 + 强制解锁按钮
        val_row = split.row(align=True)
        sub = val_row.row(align=True)
        sub.enabled = False
        sub.label(text=T("extern.dead_title"), icon="ERROR")
        val_row.operator("efx.force_pointerize_extern_ref", text="", icon="UNLOCKED")
        return

    if props.extern_ref_none:
        # 哨兵 -1：无目标
        val_row = split.row(align=True)
        val_row.label(text=T("attribute.sentinel_no_target"), icon="X")
        # 勾选 none 的按钮放在右侧
        row.prop(props, "extern_ref_none", text="", icon="X")
        return

    # 有效指针：EFX_EXTERN 对象选择器
    val_row = split.row(align=True)
    val_row.prop(props, "extern_ref_ptr", text="", icon="LINKED")
    # none 勾选（取消指向 → 变为哨兵）
    row.prop(props, "extern_ref_none", text="", icon="X")


def _draw_ptlife_ref_field(layout, obj) -> None:
    """
    在属性字段列表中，把 PTLIFE 的 relationIndex 字段替换为 action 指针选择器
    （2026-07 从独立的 Relation Action Reference 面板合并进来）。

    只留一个可空指针：None = 无目标（导出自动写 -1），不再有"越界/死属性"这种
    只读中间态——不合法就是没有目标，直接在这里选一个即可。
    """
    try:
        props = obj.efx_ptlife_ref
    except AttributeError:
        return

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text="Relation Index")
    val_row = split.row(align=True)
    val_row.prop(props, "relation_play_ptr", text="", icon="LINKED")
    if props.relation_play_ptr is None:
        hint = val_row.row(align=True)
        hint.enabled = False
        hint.label(text=T("attribute.sentinel_no_target"), icon="X")


def _draw_ptcollision_ref_field(layout, obj) -> None:
    """PTCOLLISION 版本：把 ieIndex 字段替换为 action 指针选择器（同上，None=无目标）。"""
    try:
        props = obj.efx_ptcollision_ref
    except AttributeError:
        return

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text="IE Index")
    val_row = split.row(align=True)
    val_row.prop(props, "ie_play_ptr", text="", icon="LINKED")
    if props.ie_play_ptr is None:
        hint = val_row.row(align=True)
        hint.enabled = False
        hint.label(text=T("attribute.sentinel_no_target"), icon="X")


def _draw_layoutbank_summary(layout, bp) -> None:
    """LayoutBank 只读列摘要：逐 Block 列出每一列的类型/行数/前几个值。

    不接受编辑——变长表放不进 EFXFieldItem 模型，见 describe_layoutbank 的
    文档串。数值宽度已按 2026-09 全语料统计坐实的原生类型解出，但语义未知。
    """
    import base64
    from ..efx_format.schema.custom_codecs import describe_layoutbank

    row = layout.row()
    row.enabled = False
    row.label(text=T("attribute.layoutbank_readonly_note"), icon="INFO")

    try:
        raw = base64.b64decode(bp.raw_b64)
        columns = describe_layoutbank(raw)
    except Exception:
        layout.label(text=T("attribute.layoutbank_decode_failed"), icon="ERROR")
        return

    last_block = None
    for col in columns:
        if col["block_idx"] != last_block:
            last_block = col["block_idx"]
            layout.label(text=f"Block {last_block}", icon="ANIM_DATA")
        box = layout.box()
        vals = col["values"]
        preview = ", ".join(
            (f"{v:.3g}" if isinstance(v, float) else str(v)) for v in vals[:8]
        )
        if len(vals) > 8:
            preview += ", …"
        box.label(text=f"col type={col['block_type']}  n={col['count']}")
        box.label(text=preview)


# 属性字段内容。

def _draw_attribute_fields_content(layout, context, obj=None):
    """
    绘制 EFX_ATTRIBUTE 的字段内容。
    被 EFX_PT_attribute_fields（N 面板）和 EFX_PT_attribute_fields_props（属性编辑器）共用。

    obj 为 None 时取 `context.active_object`（上面两个面板的原有行为）；
    **Entry Inspector 会显式传入非活动的属性对象**，逐个画出整个 entry 的模块栈——
    那里被画的属性并不是 active_object，所以这个形参不能省。
    """
    if obj is None:
        obj = context.active_object

    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        layout.label(text=T("attribute.select_hint"), icon="INFO")
        return

    try:
        bp = obj.efx_block
    except AttributeError:
        layout.label(text=T("attribute.not_registered"), icon="ERROR")
        return

    # 类型名是字段注释和专用布局的查找键。
    type_name = ""
    type_hash_int = 0
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        type_hash_int = int(bp.type_hash_str)
        type_name = HASH_TO_NAME.get(type_hash_int, "").upper()
    except (ValueError, ImportError):
        type_name = ""

    # LayoutBank 为变长表，仅提供只读摘要。
    if type_name == "LAYOUTBANK":
        _draw_layoutbank_summary(layout, bp)
        return

    # ── EFX Color Editor 模式：只画颜色/亮度相关字段（is_color_field 判据）───────
    _color_only = _rc.is_color_editor_mode(obj)

    # ── 检测是否为 EXTERNREFERENCE 属性（用于 referenceIndex 字段替换）──────────
    _is_extern_ref = False
    try:
        from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
        _is_extern_ref = (int(bp.type_hash_str) == _EXTERNREFERENCE_HASH)
    except (ValueError, ImportError):
        pass

    # ── PTLIFE / PTCOLLISION：relationIndex / ieIndex 字段替换为 action 指针选择器
    # （2026-07 从独立的 Relation/IE Action Reference 面板合并进来，见
    # _draw_ptlife_ref_field / _draw_ptcollision_ref_field）。overlay 在字段编码
    # 之后总是覆写这两个字节，原始数值字段编辑会被静默丢弃，故始终替换、不显示原始字段。
    _is_ptlife = False
    _is_ptcollision = False
    try:
        from ..efx_format.hashes import PTLIFE as _PTLIFE_HASH, PTCOLLISION as _PTCOLLISION_HASH
        _th = int(bp.type_hash_str)
        _is_ptlife = (_th == _PTLIFE_HASH)
        _is_ptcollision = (_th == _PTCOLLISION_HASH)
    except (ValueError, ImportError):
        pass

    # ── MATERIAL（Phase C）：按 __material__ 哨兵识别结构化材质槽编辑布局 ────────
    # _material_groups: {block_index: {'shader_item': item, 'slots': [(t, item), ...]}}
    # 非 None 时面板绘制专用材质槽编辑器（_draw_material_editor），并让通用逐字段
    # 循环跳过 matshader_*/slotpath_*/__material__ 这几个 item（避免重复渲染）。
    _material_groups = None
    try:
        from ..efx_format.hashes import MATERIAL as _MATERIAL_HASH
        if (int(bp.type_hash_str) == _MATERIAL_HASH
                and any(it.ori_name == "__material__" for it in bp.field_items)):
            _material_groups = {}
            for it in bp.field_items:
                if it.ori_name.startswith("matshader_"):
                    j = int(it.ori_name.split("_", 1)[1])
                    _material_groups.setdefault(j, {})["shader_item"] = it
                elif it.ori_name.startswith("matnamehash_"):
                    j = int(it.ori_name.split("_", 1)[1])
                    _material_groups.setdefault(j, {})["name_item"] = it
                elif it.ori_name.startswith("slotpath_"):
                    _, j_str, t_str = it.ori_name.split("_", 2)
                    j = int(j_str)
                    _material_groups.setdefault(j, {}).setdefault("slots", []).append(
                        (int(t_str), it)
                    )
                elif it.ori_name.startswith("matparam_"):
                    _, j_str, t_str = it.ori_name.split("_", 2)
                    j = int(j_str)
                    _material_groups.setdefault(j, {}).setdefault("params", []).append(
                        (int(t_str), it)
                    )
    except Exception:
        _material_groups = None

    # ── PTBEHAVIOR 检测（用于灰字提示 + param 标签）────────────────────────────
    _is_ptbehavior = False
    try:
        from ..efx_format.hashes import PTBEHAVIOR as _PTBEHAVIOR_HASH_P
        _is_ptbehavior = (int(bp.type_hash_str) == _PTBEHAVIOR_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_plemissive = False
    try:
        from ..efx_format.hashes import PLEMISSIVE as _PLEMISSIVE_HASH_P
        _is_plemissive = (int(bp.type_hash_str) == _PLEMISSIVE_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_tubelight = False
    try:
        from ..efx_format.hashes import TUBELIGHT as _TUBELIGHT_HASH_P
        _is_tubelight = (int(bp.type_hash_str) == _TUBELIGHT_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_ribbonblade = False
    try:
        from ..efx_format.hashes import RIBBONBLADE as _RIBBONBLADE_HASH_P
        _is_ribbonblade = (int(bp.type_hash_str) == _RIBBONBLADE_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_shadersettings = False
    try:
        from ..efx_format.hashes import SHADERSETTINGS as _SHADERSETTINGS_HASH_P
        _is_shadersettings = (int(bp.type_hash_str) == _SHADERSETTINGS_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_rgbfire = False
    try:
        from ..efx_format.hashes import RGBFIRE as _RGBFIRE_HASH_P
        _is_rgbfire = (int(bp.type_hash_str) == _RGBFIRE_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_rgbwater = False
    try:
        from ..efx_format.hashes import RGBWATER as _RGBWATER_HASH_P
        _is_rgbwater = (int(bp.type_hash_str) == _RGBWATER_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_transform3d = False
    try:
        from ..efx_format.hashes import TRANSFORM3D as _TRANSFORM3D_HASH_P
        _is_transform3d = (int(bp.type_hash_str) == _TRANSFORM3D_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_spawn = False
    try:
        from ..efx_format.hashes import SPAWN as _SPAWN_HASH_P
        _is_spawn = (int(bp.type_hash_str) == _SPAWN_HASH_P)
    except (ValueError, ImportError):
        pass

    # ── 可编辑属性：展示字段列表 ────────────────────────────────────────────────
    if bp.is_editable:
        if len(bp.field_items) == 0:
            layout.label(text=T("attribute.no_fields"), icon="INFO")
        elif _color_only and not _cf.attribute_has_color(type_hash_int, bp.field_items):
            # Color Editor 模式下这个 attribute 没有任何颜色/亮度字段——正常工作流不该
            # 选到它（Outliner 只暴露含颜色内容），但防御性处理，避免渲染出空标题框。
            layout.label(text=T("attribute.no_color_fields"), icon="INFO")
        else:
            # ctc 风格：字段列表包在 box 里，用 column 统一管理行高
            box = layout.box()
            col = box.column(align=True)
            # 属性类型名称区块标题行（含 dirty 标记）
            title_row = col.row(align=True)
            title_row.scale_y = 1.0
            block_title = type_name if type_name else f"Hash {bp.type_hash_str}"
            if bp.efx_dirty:
                title_row.label(text=f"{block_title}  ● {T('common.modified')}", icon="MODIFIER")
            else:
                title_row.label(text=block_title, icon="MODIFIER")
            # MATERIAL（Phase C）：材质槽编辑器（增删材质槽 + 类型下拉 + 贴图路径填/清）
            if _material_groups is not None:
                _draw_material_editor(col, context, _material_groups)
            # 部分可编辑（含 __opaque_hint__）：属性名下一行灰字提示
            _has_partial = any(
                it.ori_name == "__opaque_hint__" for it in bp.field_items
            )
            if _has_partial:
                _hint_row = col.row(align=True)
                _hint_row.enabled = False
                _hint_row.label(text=T("attribute.partial_edit"))
            # PTBEHAVIOR：param 数量因文件而异，仅支持现存 param 的修改
            if _is_ptbehavior:
                _ptb_hint_row = col.row(align=True)
                _ptb_hint_row.enabled = False
                _ptb_hint_row.label(text=T("attribute.ptbehavior_hint"))
            # "显示全部字段"开关：当该块有可隐藏字段时显示——模式过滤规则
            # 或保留填充灰字段（0xCD 占位 / section_length 等只读位）。默认隐藏这些字段。
            from . import field_visibility as _fv_hdr
            from .field_labels import is_reserved_fill as _irf_hdr
            _hdr_has_vis = type_name in _fv_hdr.FIELD_VISIBILITY
            _hdr_has_reserved = any(_irf_hdr(type_name, it.ori_name) for it in bp.field_items)
            if _hdr_has_vis or _hdr_has_reserved:
                from .i18n import get_lang as _gl
                _tog = col.row(align=True)
                _tog.prop(context.scene, "efx_show_all_fields",
                          text=("显示全部字段" if _gl() == "ZH" else "Show all fields"),
                          icon="HIDE_OFF")
            col.separator(factor=0.5)
            # 逐字段绘制（带 value+jitter 位置配对：jitter 字段与紧邻前一个
            # 同类型标量 value 合并一行，模拟 XYZ Static/Random 分组风格）
            # 显示顺序订正（锚点表，默认保持字节序；只影响显示不影响导出）
            items = reorder_items_for_display(type_name, list(bp.field_items))
            n = len(items)
            _item_by_name = {it.ori_name: it for it in items}
            _axis_group_at, _axis_group_consumed = _resolve_axis_groups(type_name, _item_by_name)
            # 按模式字段过滤生效字段（"显示全部字段"开关可关闭过滤）。
            from . import field_visibility as _fv
            from . import fields as _fld
            from .field_labels import is_reserved_fill as _irf
            _show_all_fields = getattr(context.scene, "efx_show_all_fields", False)
            _has_vis_rules = type_name in _fv.FIELD_VISIBILITY

            def _mode_getter(fname, _ibn=_item_by_name, _rd=_fld._enum_backing_read):
                _it = _ibn.get(fname)
                return _rd(_it) if _it is not None else None

            # ── 字段分档（常用 / 高级）───────────────────────────────────────
            # 分档是**可选项**（偏好设置里默认关）：关掉时全部字段按字节序原样画。
            _adv_lead, _adv_follow = (set(), set()) if not field_tiers_enabled() else classify_field_tiers(
                type_name, items, _axis_group_at, _axis_group_consumed)
            # 常用区一行都没有（字段全是占位名的类型：DUMMY/PATHCHAIN/FAKEPLANE…）时
            # 放弃折叠，直接内联画——藏起来面板上就只剩一个孤零零的「高级 (N)」。
            def _row_hidden(_name, _tn=type_name, _sa=_show_all_fields):
                if _name.startswith("__") and _name.endswith("__"):
                    return True
                if not _sa and _has_vis_rules and _fv.field_hidden(_tn, _name, _mode_getter):
                    return True
                if not _sa and _irf(_tn, _name):
                    return True
                if _color_only:
                    _it = _item_by_name.get(_name)
                    if _it is not None and not _cf.is_color_field(
                            type_hash_int, _name, _it.data_type):
                        return True
                return False

            from . import layout_model as _lm_panel
            if _lm_panel.all_rows_advanced(items, _adv_lead, _adv_follow, _row_hidden):
                _adv_lead, _adv_follow = set(), set()

            _adv_expanded = bool(getattr(obj, "efx_ui_advanced", False))
            # 三个子 column 按创建顺序占位：折叠头要等循环跑完才知道该不该画（也才知道
            # 计数），先把槽位占住，回填时仍排在高级字段之前。
            _common_col = col.column(align=True)
            _adv_hdr_col = col.column(align=True)
            _adv_body_col = col.column(align=True)
            _adv_count = 0

            i = 0
            while i < n:
                item = items[i]
                # MATERIAL（Phase C）：全部 item 已由 _draw_material_editor 统一绘制，
                # 通用逐字段循环全部跳过（matshader_*/slotpath_*/__material__）。
                if _material_groups is not None:
                    i += 1
                    continue
                # __opaque_hint__ 是内部 sentinel，不渲染为字段行
                if item.ori_name.startswith("__") and item.ori_name.endswith("__"):
                    i += 1
                    continue
                # TRANSFORM3D / SPAWN：从位掩码里拆出来、挪到别的字段前面当门控开关的
                # 勾选框，必须画在"模式过滤隐藏判定"**之前**——它们门控的字段（velocity/
                # modifier 组、spawnFrame）关着的时候会被下面那条隐藏判定跳过，如果勾选
                # 框跟着一起判断就会连自己也被隐藏，等于没法再打开，字段永远显示不出来。
                # enableVelocityBitflag/spawnFlags 本身不受这条隐藏判定影响（不在
                # FIELD_VISIBILITY 表里），所以它们自己该怎么画（弹窗/其余位）仍在下面
                # 原来的位置处理，不受影响。
                if _is_transform3d and item.ori_name in (
                        "translation_velocity", "translation_velocity_modifier"):
                    _flag_item = _item_by_name.get("enableVelocityBitflag")
                    if _flag_item is not None:
                        from .i18n import get_lang as _get_lang_t3d
                        _zh_t3d = _get_lang_t3d() == "ZH"
                        if item.ori_name == "translation_velocity":
                            _draw_bitmask_bit_row(_tcol, _flag_item, type_name, 0,
                                                  "启用速度" if _zh_t3d else "Enable Velocity")
                        else:
                            _draw_bitmask_bit_row(_tcol, _flag_item, type_name, 1,
                                                  "启用加速度" if _zh_t3d else "Enable Acceleration")
                    # 不 continue：velocity/modifier 字段本身照常往下走（含隐藏判定）
                if _is_spawn and item.ori_name == "spawnFrame":
                    _spawnflags_item = _item_by_name.get("spawnFlags")
                    if _spawnflags_item is not None:
                        from ..efx_format.schema.enums import BITS_SPAWN_FLAGS as _BITS_SF
                        from .i18n import get_lang as _get_lang_sp
                        _zh_sp = _get_lang_sp() == "ZH"
                        _en_uf, _zh_uf = next((e, z) for m, e, z in _BITS_SF if m == 0x20)
                        _draw_bitmask_bit_row(_tcol, _spawnflags_item, type_name, 5,
                                              _zh_uf if _zh_sp else _en_uf,
                                              anno_name="spawnFlags")
                    # 不 continue：spawnFrame 本身照常往下走（含 jitter 配对/隐藏判定）
                # TRANSFORM3D：enableVelocityBitflag 本身到了它原来的字节位置不再单独
                # 画（两个位已经画在上面两组前面了）。
                if _is_transform3d and item.ori_name == "enableVelocityBitflag":
                    i += 1
                    continue
                # 模式过滤：非生效字段隐藏（show_all 关时）。放在 axis-group 判定前，
                # 使被隐藏的组首字段（如 velocityX）连带整组不绘制。
                if (_has_vis_rules and not _show_all_fields
                        and _fv.field_hidden(type_name, item.ori_name, _mode_getter)):
                    i += 1
                    continue
                # 保留填充/只读灰字段（0xCD 占位 / section_length 等）：默认隐藏，
                # "显示全部字段"开关可显示。放在 axis-group 判定前（保留字段非轴组成员）。
                if not _show_all_fields and _irf(type_name, item.ori_name):
                    i += 1
                    continue
                # Color Editor 模式：非颜色/亮度字段直接跳过，不进入任何特例渲染分支
                # （TUBELIGHT headColor/tailColor、RIBBONBLADE head.*/tailEnd.* 等颜色
                # 特例字段本身就会通过 is_color_field 判据，特例渲染分支正常生效）。
                if _color_only and not _cf.is_color_field(type_hash_int, item.ori_name, item.data_type):
                    i += 1
                    continue
                # 分档路由：高级字段进折叠子区（收起时直接跳过，只计数）。
                # 放在所有"隐藏类"过滤之后——被隐藏的字段本就不该计入高级区计数。
                _tcol = _common_col
                if item.ori_name in _adv_lead or item.ori_name in _adv_follow:
                    if item.ori_name in _adv_lead:
                        _adv_count += 1
                    if not _adv_expanded:
                        i += 1
                        continue
                    _tcol = _adv_body_col
                # 虚拟轴向组合控件（AXIS_GROUPS）：分组首字段触发整组绘制，其余成员跳过
                if item.ori_name in _axis_group_at:
                    _draw_axis_group(_tcol, type_name, _axis_group_at[item.ori_name], _item_by_name)
                    i += 1
                    continue
                if item.ori_name in _axis_group_consumed:
                    i += 1
                    continue
                # EXTERNREFERENCE 的 referenceIndex 字段替换为 extern 指针 UI
                if _is_extern_ref and item.ori_name == "referenceIndex":
                    _draw_extern_ref_field(_tcol, obj)
                    i += 1
                    continue
                # PTLIFE/PTCOLLISION：relationIndex/ieIndex 原始字段替换为 action
                # 指针选择器（内联，样式跟 EXTERNREFERENCE 的 referenceIndex 一致）。
                if _is_ptlife and item.ori_name == "relationIndex":
                    _draw_ptlife_ref_field(_tcol, obj)
                    i += 1
                    continue
                if _is_ptcollision and item.ori_name == "ieIndex":
                    _draw_ptcollision_ref_field(_tcol, obj)
                    i += 1
                    continue
                # PTBEHAVIOR：b_type 画成行为类下拉（原来是裸字符串框，手打类名既难又易错）
                if _is_ptbehavior and item.ori_name == 'b_type':
                    _bt_row = _tcol.row(align=True)
                    _bt_row.scale_y = 1.1
                    _bt_row.use_property_split = False
                    _bt_split = _bt_row.split(factor=0.45)
                    _bt_split.label(text="B type")
                    _bt_split.operator_menu_enum(
                        "efx.ptb_set_btype", "b_type_choice",
                        text=item.string_value.rsplit("::", 1)[-1] or "(none)",
                    )
                    i += 1
                    continue
                # PTBEHAVIOR：param 行用属性 key 标签（hint_name=已知名/0x%08X）+ 行尾移除按钮
                if _is_ptbehavior and item.hint_name and item.ori_name.startswith('p'):
                    try:
                        _pord = int(item.ori_name[1:])
                    except ValueError:
                        _pord = -1
                    _lbl = item.hint_name
                    _prow = _tcol.row(align=True)
                    _fcol = _prow.column(align=True)
                    # 颜色（vector4，名字以 Color 结尾）画色轮 + A 滑块；
                    # 其余元素数 ≤4 的数组一律一行画完；标量/字符串走通用渲染。
                    if item.data_type == 'FLOAT4' and _ptb_item_is_color(item):
                        _draw_ptb_float4_as_color(_fcol, item, type_name, _lbl)
                    elif item.data_type in _PTB_VECTOR_PROPS:
                        _draw_ptb_vector_row(_fcol, item, type_name, _lbl)
                    else:
                        _draw_field_item(_fcol, item, type_name=type_name, label_override=_lbl,
                                         obj=obj, anno_name=item.hint_name)
                    if _pord >= 0:
                        _bcol = _prow.column(align=True)
                        _op = _bcol.operator("efx.ptb_remove_override", text="", icon="X")
                        _op.param_index = _pord
                    i += 1
                    continue
                # TUBELIGHT：headColor/tailColor 是打包 int32 RGBA（非现成支持的
                # 4-ubyte-list 格式），拆成颜色选择器（2026-07-01 schema 重构后，
                # unkn5/unkn6a 已拆成独立标量字段，交给通用引擎+RESERVED_FILL_FIELDS
                # 处理即可，不再需要专属分支）。
                if _is_tubelight and item.ori_name in ("headColor", "tailColor"):
                    _lbl = "HeadColor" if item.ori_name == "headColor" else "TailColor"
                    _draw_tubelight_int_as_color(_tcol, item, type_name, _lbl)
                    i += 1
                    continue
                # SHADERSETTINGS：presetId 换成字符串输入 + 已知名字下拉（见上方函数注释）。
                if _is_shadersettings and item.ori_name == "presetId":
                    _draw_shadersettings_preset_id(_tcol, item, type_name,
                                                    _friendly_name("presetId", type_name))
                    i += 1
                    continue
                # PLEMISSIVE：body_p / wp_p（光圈部位掩码）保留原数值字段（直接可看/改），
                # 行尾附勾选弹窗按钮作为计算辅助。下拉拉开即显示部位，无需额外摘要行。
                if _is_plemissive and item.ori_name in ("body_p", "wp_p"):
                    _aura_lbl = ("Aura Part (Player)" if item.ori_name == "body_p"
                                 else "Aura Part (Weapon)")
                    _pm_row = _tcol.row(align=True)
                    _fcol = _pm_row.column(align=True)
                    _draw_field_item(_fcol, item, type_name=type_name, label_override=_aura_lbl, obj=obj)
                    _bcol = _pm_row.column(align=True)
                    _op = _bcol.operator("efx.set_part_mask", text="", icon="DOWNARROW_HLT")
                    _op.field = item.ori_name
                    i += 1
                    continue
                # RIBBONBLADE：head.*/tailEnd.*（EPVColorSlot 嵌套字段）统一加
                # [Head]/[Tail] 前缀标签，避免内层 "head" 字段跟外层槽位名撞车看不清。
                if _is_ribbonblade and "." in item.ori_name and item.ori_name.split(".", 1)[0] in ("head", "tailEnd"):
                    _slot_key, _sub_key = item.ori_name.split(".", 1)
                    from .i18n import get_lang as _get_lang_rb
                    _zh_rb = _get_lang_rb() == "ZH"
                    _prefix_rb = ("[头部]" if _zh_rb else "[Head]") if _slot_key == "head" else ("[尾部]" if _zh_rb else "[Tail]")
                    _sub_overrides_rb = {
                        "epvColorSlot": ("EPV 颜色槽" if _zh_rb else "EPV Color Slot"),
                        "color1":       ("颜色" if _zh_rb else "Color"),
                        "color2":       ("颜色范围" if _zh_rb else "Color Range"),
                    }
                    _sub_lbl_rb = _sub_overrides_rb.get(_sub_key) or _friendly_name(_sub_key, type_name)
                    _draw_field_item(_tcol, item, type_name=type_name, label_override=f"{_prefix_rb} {_sub_lbl_rb}", obj=obj)
                    i += 1
                    continue
                # RGBFIRE：分组小标题/分隔线 + 组内简化标签（见上方函数/表注释；
                # 字段实际显示顺序已由 field_order.py 的锚点表重排过）。
                if _is_rgbfire:
                    from .i18n import get_lang as _get_lang_rf
                    _zh_rf = _get_lang_rf() == "ZH"
                    if item.ori_name == "colorRate":
                        _tcol.separator(factor=1.0)
                    elif item.ori_name == "fireColorParam_correctColorNo":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rf, "火焰色（绿通道）", "Fire (GreenCh)")
                    elif item.ori_name == "smokeColorParam_correctColorNo":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rf, "烟雾色（红通道）", "Smoke (RedCh)")
                    elif item.ori_name == "lerpAlphaToBlue":
                        _tcol.separator(factor=1.0)
                    _rf_lbl = _RGBFIRE_ROW_LABELS.get(item.ori_name)
                    if _rf_lbl:
                        _lbl_text = _rf_lbl[0] if _zh_rf else _rf_lbl[1]
                        _nxt_rf = items[i + 1] if i + 1 < n else None
                        if (_nxt_rf is not None and item.data_type in _SCALAR_PROP_ATTR
                                and not _is_jitter_name(item.ori_name)
                                and not item.ori_name.startswith("__")
                                and _nxt_rf.data_type == item.data_type
                                and _is_matching_jitter(item.ori_name, _nxt_rf.ori_name)):
                            _draw_value_jitter_pair(_tcol, item, _nxt_rf, type_name=type_name,
                                                     label_override=_lbl_text)
                            i += 2
                        else:
                            _draw_field_item(_tcol, item, type_name=type_name,
                                              label_override=_lbl_text, obj=obj)
                            i += 1
                        continue
                # RGBWATER：分组小标题/分隔线 + 组内简化标签（同上，见 field_order.py
                # 的 RGBWATER 锚点表 + 上方 _RGBWATER_ROW_LABELS 注释）。
                if _is_rgbwater:
                    from .i18n import get_lang as _get_lang_rw
                    _zh_rw = _get_lang_rw() == "ZH"
                    if item.ori_name == "colorRate":
                        _tcol.separator(factor=1.0)
                    elif item.ori_name == "specularColorParam_correctColorNo":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rw, "高光", "Specular")
                    elif item.ori_name == "sheetColorParam_correctColorNo":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rw, "水膜", "Sheet")
                    elif item.ori_name == "cubemapPath":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rw, "环境反射", "Environment Reflection")
                    elif item.ori_name == "waterLerpGtoB":
                        _tcol.separator(factor=1.0)
                        _draw_section_header(_tcol, _zh_rw, "插值", "Lerp")
                    _rw_lbl = _RGBWATER_ROW_LABELS.get(item.ori_name)
                    if _rw_lbl:
                        _lbl_text = _rw_lbl[0] if _zh_rw else _rw_lbl[1]
                        _nxt_rw = items[i + 1] if i + 1 < n else None
                        if (_nxt_rw is not None and item.data_type in _SCALAR_PROP_ATTR
                                and not _is_jitter_name(item.ori_name)
                                and not item.ori_name.startswith("__")
                                and _nxt_rw.data_type == item.data_type
                                and _is_matching_jitter(item.ori_name, _nxt_rw.ori_name)):
                            _draw_value_jitter_pair(_tcol, item, _nxt_rw, type_name=type_name,
                                                     label_override=_lbl_text)
                            i += 2
                        else:
                            _draw_field_item(_tcol, item, type_name=type_name,
                                              label_override=_lbl_text, obj=obj)
                            i += 1
                        continue
                # SPAWN：spawnFlags 6 个位拆开平铺——UseSpawnFrame(bit5) 单独挪到
                # spawnFrame 上面当门控（field_visibility.py 已配置 spawnFrame/-Jitter
                # 只在它打开时显示），其余 5 位留在 spawnFlags 原本的字节位置。
                # ⚠ 挪到 spawnFrame 上面那颗勾选框的绘制代码在**更前面**（模式过滤/
                # 隐藏判定之前），不在这里——spawnFrame 自己会被同一个门控隐藏，如果
                # 勾选框跟它绑在一起判断，字段一隐藏勾选框也会跟着消失，就没法再打开了。
                if _is_spawn and item.ori_name == "spawnFlags":
                    from ..efx_format.schema.enums import BITS_SPAWN_FLAGS as _BITS_SF2
                    from .i18n import get_lang as _get_lang_sp2
                    _zh_sp2 = _get_lang_sp2() == "ZH"
                    for _mask, _en_b, _zh_b in _BITS_SF2:
                        if _mask == 0x20:
                            continue  # UseSpawnFrame 已经挪到 spawnFrame 上面画过了
                        _bit = _mask.bit_length() - 1
                        _draw_bitmask_bit_row(_tcol, item, type_name, _bit,
                                              _zh_b if _zh_sp2 else _en_b,
                                              anno_name="spawnFlags")
                    i += 1
                    continue
                # value + jitter 配对（位置性：下一个是同类型 jitter 标量）
                nxt = items[i + 1] if i + 1 < n else None
                if (nxt is not None
                        and item.data_type in _SCALAR_PROP_ATTR
                        and not _is_jitter_name(item.ori_name)
                        and not item.ori_name.startswith("__")
                        and nxt.data_type == item.data_type
                        and _is_matching_jitter(item.ori_name, nxt.ori_name)):
                    _draw_value_jitter_pair(_tcol, item, nxt, type_name=type_name)
                    i += 2
                    continue
                _draw_field_item(_tcol, item, type_name=type_name, obj=obj)
                i += 1

            # 「高级」折叠头回填：循环跑完才知道计数，但 _adv_hdr_col 的槽位在循环前
            # 就占好了，所以它仍然渲染在高级字段之前。
            if _adv_count:
                _adv_hdr_col.separator(factor=0.3)
                _ahdr = _adv_hdr_col.row(align=True)
                _ahdr.prop(
                    obj, "efx_ui_advanced",
                    text="%s (%d)" % (T("attribute.advanced"), _adv_count),
                    icon="TRIA_DOWN" if _adv_expanded else "TRIA_RIGHT",
                    emboss=False,
                )
                if _adv_expanded:
                    # 提示行也进 _adv_hdr_col：body 里已经画满字段了，塞进去会掉到最底下
                    _atip = _adv_hdr_col.row(align=True)
                    _atip.enabled = False
                    _atip.label(text=T("attribute.advanced_hint"))

            # PTBEHAVIOR：参数列表底部「添加覆盖」——左边下拉列全表，右边放大镜按名字搜。
            # 合并目录动辄上百项（DTI 补项进来之后），纯下拉翻不动，故照 attribute 那边的
            # efx.attribute_add_search 加一个 invoke_search_popup 入口。
            if _is_ptbehavior:
                col.separator(factor=0.5)
                _add_row = col.row(align=True)
                _add_row.operator_menu_enum(
                    "efx.ptb_add_override", "key_choice",
                    text=T("attribute.ptbehavior_add"), icon="ADD",
                )
                _add_row.operator("efx.ptb_add_override_search", text="", icon="VIEWZOOM")

            # LAYOUT：前缀字段之后是内嵌布局表的表格编辑器
            if type_name == "LAYOUT" and not _color_only:
                from . import layoutbank_ops as _lbo
                _lbo.draw_layout_bank_editor(col, obj)

    else:
        # 不可编辑（_custom / 未知 / 含嵌套结构）
        box = layout.box()
        col = box.column(align=True)
        # 属性类型名称区块标题行
        title_row = col.row(align=True)
        title_row.scale_y = 1.0
        block_title = type_name if type_name else f"Hash {bp.type_hash_str}"
        title_row.label(text=block_title, icon="MODIFIER")
        _hint_row = col.row(align=True)
        _hint_row.enabled = False
        _hint_row.label(text=T("attribute.partial_edit"))



class EFX_PT_entry(bpy.types.Panel):
    """MHW EFX 编辑器主面板（N 面板 → EFX 标签页）"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "MHW EFX"
    # 负值确保此面板位于未设置顺序的默认面板之前。
    bl_order       = -4

    def draw(self, context):
        layout = self.layout

        # ── 语言切换行（English / 中文）──────────────────────────────────────
        i18n.draw_language_toggle(layout)
        layout.separator(factor=0.5)

        # ── 顶部：New EFX / Import / Export ──────────────────────────────────
        layout.operator("efx.new_efx", text=T("entry.new_efx"), icon="ADD")
        row = layout.row(align=True)
        row.operator("efx.import_efx", text=T("entry.import"), icon="IMPORT")
        row.operator("efx.export_efx", text=T("entry.export"), icon="EXPORT")

        # ── Active EFX 选择器（新增 entry 的目标根）────────────────────────────
        layout.prop(context.scene, "efx_active_efx", text=T("entry.active_efx"))

        # ── 骨架选择器 + 刷新特效体位置（按 TRANSFORM3D + jointNo 绑定骨骼摆位）─
        layout.prop(context.scene, "efx_armature", text=T("entry.armature"))
        layout.prop(context.scene, "efx_anchor_placement", text=T("entry.anchor_placement"))
        layout.prop(context.scene, "efx_blender_coords", text=T("entry.blender_coords"))
        row = layout.row(align=True)
        row.operator("efx.sync_transform_to_view",
                     text=T("entry.sync_transform"), icon="ORIENTATION_GLOBAL")
        row.operator("efx.validate", text=T("validate.run_btn"), icon="CHECKMARK")

        layout.operator("efx.add_mhw_vfx_workspace",
                         text=T("entry.add_workspace"), icon="WORKSPACE")



def _draw_entry_tab(layout, context):
    """Entry 标签页：复制/粘贴 Entry + 保存 + 选预设新增 + 打开文件夹。
    目标 EFX 由 EFX_PT_entry 顶部的 Active EFX 选择器决定。

    新增只有"选预设"这一条路径——下拉最前面两项是代码内置的基础 3D / 2D Entry
    （见 builtin_entries），"零属性空白 entry"没有使用价值，已不再提供。"""
    wm = context.window_manager

    # 1. 复制 Entry / 粘贴 Entry（整 entry 内存剪贴板；算子 poll 自动灰）
    row = layout.row(align=True)
    row.operator("efx.copy_entry", text=T("entry.copy"), icon="COPYDOWN")
    row.operator("efx.paste_entry", text=T("entry.paste"), icon="PASTEDOWN")

    # 2. 保存当前 entry 为预设（需选中 EFX_ENTRY，poll 自动灰）
    layout.operator("efx.save_entry_preset", text=T("entry.save_preset"), icon="ADD")

    layout.separator()

    # 3. entry 预设下拉 + 新增
    root = get_active_efx_root(context)
    if root is not None:
        efx_name = getattr(context.scene, "efx_active_efx", None)
        efx_label = efx_name.name if efx_name is not None else root.name
        layout.label(text=T("entry.add_to_prefix") + efx_label, icon="PLUS")
    else:
        row2 = layout.row()
        row2.enabled = False
        row2.label(text=T("entry.add_to_prefix") + T("entry.add_to_no_efx"), icon="PLUS")
    row = layout.row(align=True)
    row.prop(wm, "efx_entry_preset_enum", text="")
    selected = wm.efx_entry_preset_enum
    if selected:
        op = row.operator("efx.add_entry_from_preset", text=T("entry.add"), icon="PLAY")
        op.preset_path = selected
    else:
        sub = row.row()
        sub.enabled = False
        sub.operator("efx.add_entry_from_preset", text=T("entry.add"), icon="PLAY")

    layout.separator()

    # 4. 打开预设文件夹
    layout.operator("efx.open_entry_preset_folder", text=T("entry.open_folder"), icon="FILE_FOLDER")


def _draw_suggested_attributes(layout, entry_obj):
    """
    画「这条渲染主体线上常用、但本 entry 缺失」的属性建议行，每行一个一键补按钮。

    数据来自官方语料按主体线统计的出现率（efx_format/categories.py::
    ATTRIBUTE_LINE_RECIPES，依据见 docs/ATTRIBUTE_STATS.md「配方模板」）。
    **只是建议**——官方自己也大量存在不带这些属性的 entry，缺了不是错误，
    所以这里不用警告色、也不进 validate。
    """
    try:
        from .attribute_ops import suggested_for_entry
        from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name
        items = suggested_for_entry(entry_obj)
    except Exception:
        return  # 建议是锦上添花，任何异常都不该影响面板其余部分
    if not items:
        return

    box = layout.box()
    box.label(text=T("attribute.suggest_title"), icon="INFO")
    for type_hash, rate, _path in items:
        raw = HASH_TO_NAME.get(type_hash, "")
        row = box.row(align=True)
        op = row.operator("efx.add_suggested_attribute",
                          text=pretty_type_name(raw) if raw else str(type_hash),
                          icon="ADD")
        op.type_hash = str(type_hash)
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.enabled = False          # 出现率只是信息，画成灰字
        sub.label(text="%d%%" % rate)


def _draw_add_attribute_block(layout, context):
    """「给当前 entry 加一个属性」这一块：目标提示 + 缺失建议 + 搜索 + 分类菜单。

    两处共用：Add 面板的 Attribute 标签页，和属性编辑器 Data 标签的 Entry 面板
    （在那儿看着 entry 的属性栈顺手加，不用切回 N 面板）。

    目标 entry 由 `_resolve_target_entries` 解析——选中 EFX_ATTRIBUTE 时算它的父
    entry，所以连续加好几个属性不用每次点回 entry；多选时一次作用到全部。
    """
    wm = context.window_manager

    try:
        from .attribute_ops import _resolve_target_entries
        targets = _resolve_target_entries(context)
    except Exception:
        targets = []

    if len(targets) > 1:
        layout.label(text=T("attribute.add_to_prefix")
                     + T("attribute.add_to_multi").format(n=len(targets)), icon="PLUS")
    elif targets:
        body_label = targets[0].get("efx_raw_label", "") or targets[0].name
        layout.label(text=T("attribute.add_to_prefix") + body_label, icon="PLUS")
    else:
        row_lbl = layout.row()
        row_lbl.enabled = False
        row_lbl.label(text=T("attribute.add_to_prefix") + T("attribute.add_to_no_entry"), icon="PLUS")

    # 「常用但缺失」建议：按该 entry 的渲染主体线，列出官方通常还会带、但这里没有的
    # 属性，一键补上（插到规范顺序位）。纯建议，不是校验——见
    # efx_format/categories.py::suggest_missing_attributes。默认收起，勾选才列出。
    if targets:
        layout.prop(wm, "efx_show_suggested_attributes",
                    text=T("attribute.suggest_toggle"))
        if wm.efx_show_suggested_attributes:
            _draw_suggested_attributes(layout, targets[0])

    # 全局模糊搜索新增：不用先猜类型归在哪个分类，键盘打字过滤全部 72 个预设。
    layout.operator("efx.attribute_add_search", text=T("attribute.search_add"), icon="VIEWZOOM")

    layout.prop(wm, "efx_block_category_enum", text=T("attribute.category"))
    # 第二级"具体预设"用 Menu（按子组分组、灰字标题），点击预设行直接新增，
    # 不再需要单独的下拉选中 + Add 确认两步。
    layout.menu("EFX_MT_attribute_preset_picker", text=T("attribute.add"), icon="PLAY")


def _draw_add_extern_override_block(layout, context):
    """选中的 EFX_ATTRIBUTE 若属于 CLAUDE.md 数据模型坐实的 18 个类型（有对应
    extern 类型），一键给它加一个 extern 覆盖：复用/新建同 entry 的
    EXTERNREFERENCE + 目标 EA 里的对应 item，种子取该属性当前实际字节。
    没有对应类型（包括 8 个 FABRICATED）时不显示任何东西——按钮出现本身就是
    "这个类型支持"的信号，不需要额外的灰态提示。

    见 extern_props.py::add_extern_override_for_attribute 的完整规则。
    """
    obj = context.active_object
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return
    try:
        from .extern_props import main_to_extern_hash
        from ..efx_format.hashes import HASH_TO_NAME
        main_hash = int(str(obj.get("type_hash", "0")))
    except (ValueError, TypeError, ImportError):
        return
    extern_hash = main_to_extern_hash(main_hash)
    if extern_hash is None:
        return
    from ..efx_format.hashes import pretty_type_name as _pretty_ext
    extern_name = (_pretty_ext(HASH_TO_NAME.get(extern_hash, ""))
                   or f"0x{extern_hash:08X}")
    layout.operator("efx.add_extern_override_for_attribute",
                     text=T("extern.add_override").format(name=extern_name),
                     icon="LINKED")


def _draw_attribute_tab(layout, context):
    """Attribute 标签页：复制/保存整属性 + 加 extern 覆盖 + 新增属性 + 粘贴属性 + 打开文件夹。
    新增属性需选中 EFX_ENTRY 或其下的 EFX_ATTRIBUTE（连续新增属性免切回 entry），
    保存/复制/加 extern 覆盖需选中 EFX_ATTRIBUTE，算子 poll 自动灰。"""
    # 1. 复制整属性（需选中 EFX_ATTRIBUTE）/ 粘贴属性（需选中 EFX_ENTRY 或其 EFX_ATTRIBUTE），poll 自动灰
    row = layout.row(align=True)
    row.operator("efx.copy_attribute", text=T("attribute.copy_whole"), icon="COPYDOWN")
    row.operator("efx.paste_attribute", text=T("attribute.paste"), icon="PASTEDOWN")

    # 2. 保存为属性预设（需选中 EFX_ATTRIBUTE，poll 自动灰）
    layout.operator("efx.save_attribute_preset", text=T("attribute.save_preset"), icon="ADD")

    # 2b. 给当前属性加对应的 extern 覆盖（只有支持的类型才显示按钮）
    _draw_add_extern_override_block(layout, context)

    layout.separator()

    # 3. 新增属性
    _draw_add_attribute_block(layout, context)

    layout.separator()

    # 4. 打开文件夹
    layout.operator("efx.open_attribute_preset_folder", text=T("entry.open_folder"), icon="FILE_FOLDER")


class EFX_PT_add(bpy.types.Panel):
    """EFX 新建：Action / Extern / Subselect 一键新建 + Entry / Attribute 标签页

    分界线是「点完就结束」还是「点之前得先在面板里选」，不是类型的重要程度或子类型多少：
      - Action 的分支发生在算子自己的 invoke_props_dialog 里；Extern 新建不再弹窗，
        直接建一个空白 EA（item 类型改在 Extern Properties 面板里"添加 Item"搜索选），
        面板上只需要一个入口 → 顶部一排按钮；
      - Entry 的预设下拉、Attribute 的目标提示 + 搜索 + 分类菜单必须常驻面板，
        才需要一块可切换的版面 → 标签页。
    以后哪种类型长出了需要常驻的选择器，它自己就该从按钮升成标签页。
    """

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Add"
    bl_options      = {"DEFAULT_CLOSED"}
    bl_order        = -3  # 固定顺序：MHW EFX > Add > Edit > 其他

    @classmethod
    def poll(cls, context):
        from .add_ops import get_active_efx_root
        root = get_active_efx_root(context)
        # Color Editor 模式：新建是结构编辑功能，不属于"只管颜色"范围，隐藏。
        return root is not None and not _rc.root_is_color_editor_mode(root)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # 一排「点完就结束」的新建（子类型在各自算子的弹窗里选，不占面板）
        row = layout.row(align=True)
        row.operator("efx.add_action",    text=T("addsec.action"),    icon="ADD")
        row.operator("efx.add_extern",    text=T("addsec.extern"),    icon="ADD")
        row.operator("efx.add_subselect", text=T("addsec.subselect"), icon="ADD")

        layout.separator()

        layout.row().prop(wm, "efx_preset_mode", expand=True)
        layout.separator(factor=0.3)
        if wm.efx_preset_mode == "ATTRIBUTE":
            _draw_attribute_tab(layout, context)
        else:
            _draw_entry_tab(layout, context)



class EFX_PT_entry_status(bpy.types.Panel):
    """EFX Entry Status 父面板（容器）。子栏：Activation / Entry References 同级附于其下。"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Entry Status"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        idx = obj.get("efx_index", "?")
        layout.label(text=f"[{idx}] {obj.name}", icon="OBJECT_DATA")


class EFX_PT_entry_activation(bpy.types.Panel):
    """Entry 激活态子栏：综合 EOF（直接触发）+ Action 召唤 + subselect 门控的派生有效态。

    放在 Entry 父面板下，与 Entry References、TIML 同级。
    """

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Activation"
    bl_parent_id    = "EFX_PT_entry_status"
    bl_options      = {"DEFAULT_CLOSED"}

    # 触发来源 → (i18n key, 图标)
    _SOURCE_UI = {
        "both":   ("entry.src_both",   "RADIOBUT_ON"),
        "direct": ("entry.src_direct", "RADIOBUT_ON"),
        "action": ("entry.src_action", "PLAY"),
        "none":   ("entry.src_none",   "RADIOBUT_OFF"),
    }

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        info = classify_entry_activation(obj)

        # ── 有效行为（派生结论，模型推测）：来源(并) + 门控(与) 修饰 ───────────────
        box = layout.box()
        key, icon = self._SOURCE_UI.get(info["source"], ("entry.src_none", "QUESTION"))
        box.label(text=T("entry.effective_label"), icon="INFO")
        eff_text = T(key)
        if info["gated"]:
            eff_text += T("entry.gate_qualifier")
            if info["source"] != "none":
                icon = "PROP_CON"
        box.label(text=eff_text, icon=icon)

        # ── 来源 1：直接触发（EOF），可切换 ─────────────────────────────────────
        in_eof = info["in_eof"]
        row = layout.row(align=True)
        row.label(
            text=T("entry.game_active_yes") if in_eof else T("entry.game_active_no"),
            icon="RADIOBUT_ON" if in_eof else "RADIOBUT_OFF",
        )
        toggle_text = T("entry.remove_from_active") if in_eof else T("entry.add_to_active")
        row.operator("efx.eof_toggle_entry", text=toggle_text,
                     icon="PAUSE" if in_eof else "PLAY")

        # ── 来源 2：动作触发（被 Action 召唤，只读）────────────────────────────────
        in_action = info["in_action"]
        layout.label(
            text=T("entry.action_trigger_yes") if in_action else T("entry.action_trigger_no"),
            icon="RADIOBUT_ON" if in_action else "RADIOBUT_OFF",
        )

        # ── 门控层：subselect 状态掩码 ──────────────────────────────────────────
        n = info["n_tables"]
        if n > 0:
            layout.label(text=T("entry.gating_yes").format(n=n), icon="PROP_CON")
        else:
            layout.label(text=T("entry.gating_no"), icon="CHECKMARK")




def _describe_root_subentries(raw_b64: str) -> list:
    """解出 opaque Root 的子条目类型名列表（['UnitBoundary', 'RenderTarget', ...]）。

    只读子条目类型，不展开字段——RenderTarget/LayoutBank 仍是 opaque。解不出（空/
    格式不对）时返回空列表，调用方据此隐藏整块，不报错。
    """
    import base64
    from ..efx_format.efxfile import EFXFile, RootBody, RootUnitBoundary
    try:
        raw = base64.b64decode(raw_b64)
        if not raw:
            return []
        body, end_pos = EFXFile._parse_root_body(raw, 0)
    except Exception:
        return []
    if end_pos != len(raw):
        return []  # 没能精确耗尽整段字节，说明解析假设不成立，宁可不显示
    names = []
    for e in body.entries:
        if isinstance(e, RootUnitBoundary):
            names.append("UnitBoundary")
        else:
            t = int.from_bytes(e.raw[:4], "little")
            names.append({RootBody.RENDERTARGET: "RenderTarget",
                          RootBody.LAYOUTBANK: "LayoutBank"}.get(t, "Unknown"))
    return names


def _draw_entry_properties_content(layout, context):
    """
    绘制 EFX_ENTRY 的原始属性内容（重命名 / Type / Root UnitBoundary）。
    被 EFX_PT_entry_properties（N 面板）和 EFX_PT_entry_properties_data
    （属性编辑器 Data 标签）共用。

    名字是 entry 自己的属性（写进 EFX_Type 标签表），所以重命名放在这里；
    Edit 面板那份弹窗按钮保留不动，两条路径共用 reorder.apply_rename 的副作用链。
    """
    from .reorder import draw_rename_field

    obj = context.active_object
    entry_kind = str(obj.get("entry_kind", "unknown"))
    kind_label = {
        "standard": T("entry.type_standard"),
    }.get(entry_kind, entry_kind)
    row = layout.row()
    row.enabled = False
    row.label(text=T("entry.type_label") + kind_label, icon="INFO")

    draw_rename_field(layout, obj)

    # Root entry 的子条目（UnitBoundary/RenderTarget/LayoutBank）现伪装成
    # EFX_ATTRIBUTE 子对象（见 io_tree.py::_root_entry_to_attr_block），跟其它
    # 属性一样出现在下面的 "EFX Entry Inspector" 里——可见、按 efx.delete_attribute
    # 删除、Inspector 自动重排。这里只处理拆不动、整段只读回退的罕见情况
    # （raw 有值：非法/未知的 root 数据，见 add_ops.py 的 decomposed 分支）。
    if entry_kind == "root" and obj.get("raw"):
        names = _describe_root_subentries(str(obj.get("raw", "")))
        if names:
            layout.label(text=T("entry.root_subentries") + ", ".join(names),
                         icon="SHADING_BBOX")
        row = layout.row()
        row.enabled = False
        row.label(text=T("entry.root_opaque_note"))


class EFX_PT_entry_properties(bpy.types.Panel):
    """EFX Entry 原始属性面板（Type / Unkn / TIML，VIEW_3D N 面板）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Entry Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        _draw_entry_properties_content(self.layout, context)


class EFX_PT_entry_properties_data(bpy.types.Panel):
    """EFX Entry 原始属性（属性编辑器 → Object Data Properties，选中 EFX_ENTRY 时显示）

    这里额外挂一块「新增属性」：Data 标签下面紧跟着就是 Entry Inspector（整个属性栈），
    看着栈顺手加一个比切回 N 面板顺。N 面板不加这块——那边 Add 面板就在同一列里。
    """

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Entry Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        _draw_entry_properties_content(self.layout, context)
        self.layout.separator()
        _draw_add_attribute_block(self.layout, context)


class EFX_PT_entry_unkn(bpy.types.Panel):
    """Entry 未知属性子栏（unkn0 / unkn1 / unkn2）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Unkn Attributes"
    bl_parent_id    = "EFX_PT_entry_properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        col = layout.column(align=True)
        if "unkn0" in obj:
            col.prop(obj, '["unkn0"]', text="Unkn0")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_attribute_fields  —  属性栏（Properties > Object 或 N 面板子面板）
# 在 VIEW_3D N 面板 EFX 标签页下挂一个子面板，当选中 EFX_ATTRIBUTE 时展示字段。
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Entry Inspector  —  在一个面板里按规范顺序展示整个 entry 的属性模块栈
#
# 现状（本面板要解决的问题）：属性字段按 CLAUDE.md §4 的约定挂在属性编辑器的 Data
# 标签下，**一次只显示被选中的那一个属性**。看完一个 12 属性的 entry 要在大纲里逐个
# 点 12 次，也看不出它们的相对关系。参照 Unity 的 ParticleSystem Inspector：整个系统
# 在一个 Inspector 里，模块可折叠、默认收起。
#
# 这是**加法不是替换**：逐属性的 EFX_PT_attribute_fields* 面板原样保留，两处共用
# 同一个 _draw_attribute_fields_content，避免绘制逻辑分叉。
#
# 设计决定见 PROGRESS.md「Entry Inspector（UI 布局）」。
# ─────────────────────────────────────────────────────────────────────────────

def _attribute_title(attr_obj, hash_to_name, pretty):
    """属性对象 -> 显示标题（类型友好名；查不到就退回对象上的记录/对象名）。"""
    try:
        h = int(str(attr_obj.get("type_hash", "0")))
    except (ValueError, TypeError):
        h = 0
    raw = hash_to_name.get(h, "")
    return (pretty(raw) if raw
            else (attr_obj.get("efx_type_name") or attr_obj.name)), h


def _draw_inspector_module(container, context, attr_obj, title, boxed=True):
    """画一个属性模块：折叠头（三角 + 类型名）+ 展开后的字段。

    boxed=False 用于「主模块」带内部——那里外层已经有一个 box，再嵌一层会让
    box 套到三层深（带 > 模块 > 字段），3.6 上的嵌套表现没验过，能浅就浅。
    """
    slot = container.box() if boxed else container.column(align=True)
    header = slot.row(align=True)
    expanded = bool(attr_obj.efx_ui_expanded)
    # emboss=False：折叠箭头画成纯图标，跟 Blender 原生子面板头一致
    header.prop(attr_obj, "efx_ui_expanded", text="",
                icon="TRIA_DOWN" if expanded else "TRIA_RIGHT", emboss=False)
    header.label(text=title)
    if expanded:
        _draw_attribute_fields_content(slot, context, obj=attr_obj)


def _draw_entry_inspector_content(layout, context):
    """画整个 entry 的属性模块栈。每个属性一个可折叠的 box。

    顶部是「主模块」带（`ENTRY_MAIN_MODULE` 的骨架属性：Transform / ParentOptions /
    Spawn / Life，出现率 100/100/99.5/99.4%），对应 Unity ParticleSystem 的 main
    module；其余属性按规范顺序跟在后面。**只是显示上的归并**——底层仍是各自独立的
    属性对象，增删/重排/引用都不受影响。

    ⚠ 带里的四个仍各自可折叠、不强制展开：它们合计约 29~40 行，常驻展开会把下面的
    渲染主体挤出屏幕两三屏，比不归并更难用。

    子对象收集走 `attribute_ops.iter_entry_attributes`（作用域限定在 entry 所在集合，
    见该函数的性能说明）——本函数每次面板重绘都会跑，不能全场景扫描。
    """
    entry_obj = context.active_object
    if entry_obj is None or entry_obj.get("~TYPE") != "EFX_ENTRY":
        return

    try:
        from .attribute_ops import iter_entry_attributes
        attrs = iter_entry_attributes(entry_obj)
    except Exception:
        return
    if not attrs:
        layout.label(text=T("inspector.no_attributes"), icon="INFO")
        return

    try:
        from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name
    except ImportError:
        HASH_TO_NAME, pretty_type_name = {}, lambda s: s
    try:
        from ..efx_format.categories import is_main_module
    except ImportError:
        is_main_module = lambda _h: False

    titled = [(_attribute_title(a, HASH_TO_NAME, pretty_type_name), a) for a in attrs]
    skeleton = [(t, a) for (t, h), a in titled if is_main_module(h)]
    others = [(t, a) for (t, h), a in titled if not is_main_module(h)]

    if skeleton:
        band = layout.box()
        band_hdr = band.row(align=True)
        band_hdr.label(text=T("inspector.main_module"), icon="PARTICLES")
        for title, a in skeleton:
            _draw_inspector_module(band, context, a, title, boxed=False)

    for title, a in others:
        _draw_inspector_module(layout, context, a, title)


class EFX_PT_entry_inspector(bpy.types.Panel):
    """Entry Inspector（属性编辑器 → Object Data Properties，选中 EFX_ENTRY 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Entry Inspector"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ENTRY"

    def draw(self, context):
        _draw_entry_inspector_content(self.layout, context)


class EFX_PT_attribute_fields(bpy.types.Panel):
    """EFX 属性字段属性栏（选中 EFX_ATTRIBUTE 对象时显示）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Attribute Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_ATTRIBUTE 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def draw(self, context):
        _draw_attribute_fields_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_attribute_fields_props  —  属性编辑器 Object Data Properties 标签
#
# bl_context = 'data'：Empty 物体的 Object Data Properties（空物体设置页）。
# 3.6～5.x 上 Empty 的 'data' 上下文一直有效（显示 Empty 尺寸/类型等），所以
# 只在这一个标签下挂——Object 标签本身内容已经很多，不再放重复的一份。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_attribute_fields_props(bpy.types.Panel):
    """EFX 属性字段（属性编辑器 → Object Data Properties，选中 EFX_ATTRIBUTE 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Attribute Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_ATTRIBUTE 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def draw(self, context):
        _draw_attribute_fields_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# filesize_double（doubleBuffer）编辑已挪到导出弹窗（operators.py::EFX_OT_export.draw，
# 取消勾选"自动重算"时紧邻出现），不再单独占用 ROOT 集合的 N 面板一栏。
# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_delete  —  删除条目（delete_ops.py） + 导出前校验（validate.py）
#   按 active_object 的 ~TYPE 显示对应删除按钮；始终提供"导出前校验"按钮。
# ─────────────────────────────────────────────────────────────────────────────

# ~TYPE → (算子 idname, 按钮文案 i18n key)
_DELETE_BY_TYPE = {
    "EFX_ENTRY":      ("efx.delete_entry",      "del.entry_btn"),
    "EFX_ATTRIBUTE":     ("efx.delete_attribute",     "del.attribute_btn"),
    "EFX_ACTION":      ("efx.delete_action",      "del.action_btn"),
    "EFX_EXTERN":    ("efx.delete_extern",    "del.extern_btn"),
    "EFX_SUBSELECT": ("efx.delete_subselect", "del.subselect_btn"),
}


class EFX_PT_delete(bpy.types.Panel):
    """EFX Edit panel — reorder / rename / copy fields / delete (shown when any EFX object is active)"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Edit"
    bl_options      = {"DEFAULT_CLOSED"}
    bl_order        = -1  # 固定顺序：MHW EFX > Add > Edit > 其他

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        # Color Editor 模式：重排/改名/删除是结构编辑功能，不属于"只管颜色"范围，隐藏。
        if _rc.is_color_editor_mode(obj):
            return False
        return obj.get("~TYPE") in _DELETE_BY_TYPE

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        t = obj.get("~TYPE") if obj is not None else None

        # ── EFX_ATTRIBUTE：排序 + 字段复制/粘贴 ──────────────────────────────────
        if t == "EFX_ATTRIBUTE":
            row = layout.row(align=True)
            op_up = row.operator("efx.move_attribute", text=T("attribute.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_attribute", text=T("attribute.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            row2 = layout.row(align=True)
            row2.operator("efx.copy_attribute_fields", text=T("attribute.copy_fields"), icon="COPYDOWN")
            row2.operator("efx.paste_attribute_fields", text=T("attribute.paste_fields"), icon="PASTEDOWN")

        # ── EFX_ENTRY：排序 + 重命名 ───────────────────────────────────────────
        elif t == "EFX_ENTRY":
            row = layout.row(align=True)
            op_up = row.operator("efx.move_entry", text=T("attribute.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_entry", text=T("attribute.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            from .reorder import draw_rename_button
            draw_rename_button(layout, obj)

        # ── EFX_ACTION / EFX_EXTERN：排序 + 重命名 ─────────────────────────────
        elif t in ("EFX_ACTION", "EFX_EXTERN"):
            row = layout.row(align=True)
            op_up = row.operator("efx.move_action_extern", text=T("attribute.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_action_extern", text=T("attribute.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            from .reorder import draw_rename_button
            draw_rename_button(layout, obj)

        # ── 删除按钮（按类型，始终显示）──────────────────────────────────────
        entry = _DELETE_BY_TYPE.get(t)
        if entry is not None:
            layout.separator(factor=0.5)
            row = layout.row()
            row.operator(entry[0], text=T(entry[1]), icon="TRASH")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# _draw_plain_field_list — 纯字段列表渲染（value+jitter 配对，无属性专属逻辑）
# 供 Extern 面板复用
# ─────────────────────────────────────────────────────────────────────────────

def _draw_plain_field_list(col, field_items, type_name: str = "") -> None:
    """渲染 field_items 列表（含 value+jitter 配对），无 EXTERNREFERENCE / PTLIFE 等属性专属逻辑。"""
    items = list(field_items)
    n = len(items)
    _item_by_name = {it.ori_name: it for it in items}
    _axis_group_at, _axis_group_consumed = _resolve_axis_groups(type_name, _item_by_name)
    i = 0
    while i < n:
        item = items[i]
        if item.ori_name.startswith("__") and item.ori_name.endswith("__"):
            i += 1
            continue
        if item.ori_name in _axis_group_at:
            _draw_axis_group(col, type_name, _axis_group_at[item.ori_name], _item_by_name)
            i += 1
            continue
        if item.ori_name in _axis_group_consumed:
            i += 1
            continue
        nxt = items[i + 1] if i + 1 < n else None
        if (nxt is not None
                and item.data_type in _SCALAR_PROP_ATTR
                and not _is_jitter_name(item.ori_name)
                and not item.ori_name.startswith("__")
                and nxt.data_type == item.data_type
                and _is_matching_jitter(item.ori_name, nxt.ori_name)):
            _draw_value_jitter_pair(col, item, nxt, type_name=type_name)
            i += 2
            continue
        _draw_field_item(col, item, type_name=type_name)
        i += 1


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_extern_props — Extern 段字段展开面板（选中 EFX_EXTERN 时显示）
# ─────────────────────────────────────────────────────────────────────────────

def _extern_item_display_name(it) -> tuple:
    """返回 (display_name, type_name)：type_name 供字段注释查表，display_name 供标题显示。"""
    type_name = ""
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        type_name = HASH_TO_NAME.get(int(it.type_hash_str), "").upper()
    except Exception:
        pass
    # 标题用正常大小写（ExternPtBehavior），type_name 保持大写原名——字段注释和
    # schema 都按原名查表，两者不能混用
    from ..efx_format.hashes import pretty_type_name as _pretty
    display_name = _pretty(type_name) if type_name else f"0x{int(it.type_hash_str):08X}"
    # 无真实样本支撑的类型在标题后追加"?"，不改 type_name 本身（避免影响字段注释查表）。
    # 沿用 part_mask_ops.py 的措辞约定：不确定的东西标"?"，不写置信度/来源括注。
    try:
        from ..efx_format.structs import FABRICATED_EXTERN_HASHES
        if int(it.type_hash_str) in FABRICATED_EXTERN_HASHES:
            display_name += "?"
    except Exception:
        pass
    return display_name, type_name


def _draw_extern_item_block(layout, it, state_idx: int, item_index: int) -> None:
    """画一个 item（某 EXTERN* 类型）的可折叠块：折叠头（三角 + 类型名 + 删除按钮）+
    展开后当前状态的字段。

    state_idx 是 EA 级的状态/列下标，按该 item 自己的槛数 clamp——这是各 item 槛数
    不一致时的边界处理（详见 _draw_extern_props_content 里的提示行）。折叠头写法照抄
    _draw_inspector_module。item_index 是它在 ep.items 里的下标，供删除按钮定位。
    """
    display_name, type_name = _extern_item_display_name(it)

    box = layout.box()
    header = box.row(align=True)
    expanded = bool(it.ui_expand)
    header.prop(it, "ui_expand", text="",
                icon="TRIA_DOWN" if expanded else "TRIA_RIGHT", emboss=False)
    header.label(text=display_name, icon="MODIFIER")
    op = header.operator("efx.extern_item_remove", text="", icon="X", emboss=False)
    op.item_index = item_index

    if not expanded:
        return

    col = box.column(align=True)

    if not it.is_editable:
        col.label(text=T("extern.read_only"), icon="INFO")
        return

    n_inst = len(it.instances)
    if n_inst == 0:
        col.label(text=T("extern.no_fields"), icon="INFO")
        return

    inst_idx = min(state_idx, n_inst - 1)
    inst = it.instances[inst_idx]

    if not inst.is_editable:
        col.label(text=T("extern.read_only"), icon="INFO")
        return

    if len(inst.field_items) == 0:
        col.label(text=T("extern.no_fields"), icon="INFO")
        return

    # Extern 覆盖里填了路径 —— 官方语料 1540 个 extern 变长元素路径**无一非空**
    # （Mesh 285 / TypeRibbon 73 / TypePlane 6 / UVSequence 127 / Billboard3D 874 /
    # RGBWater 48 …），所以这是个没有先例的写法，给红字警告但不阻止。
    if any(fi.data_type == "STRING" and fi.string_value for fi in inst.field_items):
        warn = col.row()
        warn.alert = True
        warn.label(text=T("extern.path_warning"), icon="ERROR")

    _draw_plain_field_list(col, inst.field_items, type_name=type_name)


def _draw_extern_props_content(layout, context):
    """
    绘制 EFX_EXTERN 的属性内容。
    被 EFX_PT_extern_props（N 面板）和 EFX_PT_extern_props_data（属性编辑器 Data 标签）共用。

    名字写进 EFX_Type 标签表，是 extern 自己的属性，所以重命名也画在这里
    （Edit 面板那份弹窗按钮保留，两条路径共用 reorder.apply_rename 的副作用链）。

    状态/列切换器画在 EA 级：instance 下标横跨同一个 EA 内全部 item，代表一个完整
    状态（同一列上 Spawn/Velocity3D/RgbFire 等一起从状态 i 切到状态 j），不是"选中
    某个 item 再单独翻它的实例"。下面逐个列出该 EA 下的全部 item，每个可折叠。
    """
    from .reorder import draw_rename_field
    from .extern_props import _extern_max_instance_count

    obj = context.active_object
    draw_rename_field(layout, obj)

    try:
        ep = obj.efx_extern
    except AttributeError:
        layout.label(text=T("extern.data_unavailable"), icon="ERROR")
        return

    if len(ep.items) == 0:
        layout.label(text=T("extern.no_data"), icon="INFO")
        return

    n_state = _extern_max_instance_count(ep)

    # EA 级状态/列切换器（多数 EA 只有 1 列，切换器只在 >1 时显示）
    if n_state > 1:
        row = layout.row(align=True)
        row.label(text="%s %d / %d" % (T("extern.state_label"),
                                       ep.active_instance + 1, n_state),
                  icon="NODETREE")
        nav = row.row(align=True)
        nav.operator("efx.extern_instance_prev", text="", icon="TRIA_LEFT")
        nav.operator("efx.extern_instance_next", text="", icon="TRIA_RIGHT")

    if n_state > 0:
        srow = layout.row(align=True)
        srow.operator("efx.extern_state_duplicate", text=T("extern.dup_state"), icon="DUPLICATE")
        srow.operator("efx.extern_state_remove", text=T("extern.remove_state"), icon="REMOVE")

    # 边界：各 item 槽数不一致时，明确提示——用户切到某一列，槽数不够的 item
    # 会静默 clamp 到自己的最后一槽，不加提示会让人以为它也切到了同一状态。
    counts = {len(it.instances) for it in ep.items}
    if len(counts) > 1:
        layout.label(text=T("extern.uneven_instance_counts"), icon="INFO")

    state_idx = min(ep.active_instance, n_state - 1) if n_state > 0 else 0

    for idx, it in enumerate(ep.items):
        _draw_extern_item_block(layout, it, state_idx, idx)

    layout.separator()
    layout.operator("efx.extern_item_add_search", text=T("extern.add_item"), icon="ADD")


class EFX_PT_extern_props(bpy.types.Panel):
    """EFX Extern 属性展开面板（VIEW_3D N 面板）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Extern Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def draw(self, context):
        _draw_extern_props_content(self.layout, context)


class EFX_PT_extern_props_data(bpy.types.Panel):
    """EFX Extern 属性（属性编辑器 → Object Data Properties，选中 EFX_EXTERN 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Extern Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def draw(self, context):
        _draw_extern_props_content(self.layout, context)


_CLASSES = (
    # 主面板（Import/Export/Active EFX/Armature）
    EFX_PT_entry,
    # 子面板（挂在 EFX_PT_entry 下，无上下文依赖）
    EFX_PT_add,
    # 顶级上下文面板（选中特定对象时出现，与 EFX_PT_entry 同级）
    EFX_PT_delete,
    EFX_PT_entry_status,
    EFX_PT_entry_activation,
    EFX_PT_entry_properties,
    EFX_PT_entry_properties_data,
    EFX_PT_entry_unkn,
    EFX_PT_entry_inspector,
    EFX_PT_attribute_fields,
    EFX_PT_attribute_fields_props,
    EFX_PT_subselect,
    EFX_PT_subselect_data,
    EFX_PT_action,
    EFX_PT_action_props,
    EFX_PT_extern_props,
    EFX_PT_extern_props_data,
    EFX_PT_extern_ref,
    EFX_PT_eof_list,
    # EOF 算子
    EFX_OT_eof_toggle_entry,
    # 反向引用视图（只读）
    EFX_PT_extern_backref,
    EFX_PT_entry_backref,
    EFX_PT_root_states,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # Entry Inspector 的模块折叠状态。**挂在属性对象上**而不是 window_manager——
    # 折叠是"这个模块"的状态，跟着对象走才能在切换 entry / 存盘重开后保持一致；
    # 放 WM 会导致切个 entry 折叠状态就串了。
    bpy.types.Object.efx_ui_expanded = bpy.props.BoolProperty(
        name="Expanded",
        description="Whether this attribute's module is expanded in the Entry Inspector",
        default=False,
    )
    # 「高级」字段子折叠，同理挂在属性对象上：每个属性各记各的。
    bpy.types.Object.efx_ui_advanced = bpy.props.BoolProperty(
        name="Advanced",
        description="Show rarely-edited fields (placeholders, reserved bits, "
                    "and fields the official files never change)",
        default=False,
    )


def unregister():
    for _pn in ("efx_ui_expanded", "efx_ui_advanced"):
        try:
            delattr(bpy.types.Object, _pn)
        except AttributeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
