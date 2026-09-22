"""Color Editor 的全局颜色与亮度工具。

维护约束：
- 仅修改可编辑颜色字段的 RGB，保留 alpha；字段更新走 PropertyGroup 以标记导出重打包。
- 颜色根优先显式目标、活动对象所属根，最后才接受场景唯一的颜色根。
- 色彩数学不依赖 bpy。
"""

import colorsys
import math

import bpy
from bpy.props import FloatProperty, FloatVectorProperty

from . import color_fields as _cf
from . import root_collection as _rc
from .i18n import T


# 色彩数学

def _dominant_hue(colors):
    """返回按 S×V 加权的圆周平均色相；全中性时返回 None。"""
    sx = sy = 0.0
    for r, g, b in colors:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        w = s * v
        if w <= 0.0:
            continue
        ang = h * 2.0 * math.pi
        sx += w * math.cos(ang)
        sy += w * math.sin(ang)
    if sx == 0.0 and sy == 0.0:
        return None
    return (math.atan2(sy, sx) / (2.0 * math.pi)) % 1.0


def shift_hue(colors, target_hue):
    """将主色相旋转至目标色相，保留每个颜色的 S/V。"""
    dom = _dominant_hue(colors)
    if dom is None:
        return [tuple(c) for c in colors], None
    delta = (target_hue - dom) % 1.0
    out = []
    for r, g, b in colors:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        out.append(colorsys.hsv_to_rgb((h + delta) % 1.0, s, v))
    return out, dom


def align_hue(colors, target_hue):
    """将每个颜色的色相对齐到目标值，保留 S/V。"""
    out = []
    for r, g, b in colors:
        _h, s, v = colorsys.rgb_to_hsv(r, g, b)
        out.append(colorsys.hsv_to_rgb(target_hue, s, v))
    return out


# Blender 数据访问

def _iter_color_items(root_col):
    """遍历根内可编辑的 RGB 项；read_only 项不得写入。"""
    col_entry = _rc.get_leaf_collection(root_col, "EFX_ENTRY")
    if col_entry is None:
        return
    for obj in col_entry.all_objects:
        if obj.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            type_hash = int(str(obj.get("type_hash", "0")))
            items = obj.efx_block.field_items
        except Exception:
            continue
        for it in items:
            if getattr(it, "read_only", False):
                continue
            if it.data_type == "COLOR_RGBA":
                yield it, "rgba"
            elif (type_hash, it.ori_name) in _cf._PACKED_INT_COLOR_FIELDS:
                yield it, "packed"


def _iter_brightness_items(root_col):
    """遍历根内可编辑的亮度或强度 FLOAT 项。"""
    col_entry = _rc.get_leaf_collection(root_col, "EFX_ENTRY")
    if col_entry is None:
        return
    for obj in col_entry.all_objects:
        if obj.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            type_hash = int(str(obj.get("type_hash", "0")))
            items = obj.efx_block.field_items
        except Exception:
            continue
        for it in items:
            if getattr(it, "read_only", False):
                continue
            if _cf.is_brightness_field(type_hash, it.ori_name, it.data_type):
                yield it


def _read_rgb(item, kind):
    v = item.int_as_color_display if kind == "packed" else item.color_rgba_value
    return (v[0], v[1], v[2])


def _write_rgb(item, kind, rgb):
    """写入 RGB 并保留 alpha。"""
    if kind == "packed":
        v = item.int_as_color_display
        item.int_as_color_display = (rgb[0], rgb[1], rgb[2], v[3])
    else:
        v = item.color_rgba_value
        item.color_rgba_value = (rgb[0], rgb[1], rgb[2], v[3])


def _resolve_root(context):
    """按显式目标、活动对象、唯一颜色根的顺序解析根；歧义时返回 None。"""
    scn = getattr(context, "scene", None)
    root = getattr(scn, "efx_active_efx", None) if scn is not None else None
    if root is not None and _rc.root_is_color_editor_mode(root):
        return root

    obj = getattr(context, "active_object", None)
    if obj is not None:
        r = _rc.find_root_collection(obj)
        if r is not None and _rc.root_is_color_editor_mode(r):
            return r

    cols = [c for c in _rc.all_root_collections() if _rc.root_is_color_editor_mode(c)]
    if len(cols) == 1:
        return cols[0]
    return None


# 算子

def _prep_target(op, context):
    """解析目标根和色相，并收集颜色项；失败时报告并返回 None。"""
    root = _resolve_root(context)
    if root is None:
        op.report({"ERROR"}, T("colortool.no_root"))
        return None
    tgt = tuple(context.scene.efx_recolor_target)
    th, ts, tv = colorsys.rgb_to_hsv(tgt[0], tgt[1], tgt[2])
    if ts * tv <= 0.0:
        op.report({"WARNING"}, T("colortool.target_neutral"))
        return None
    pairs = list(_iter_color_items(root))
    if not pairs:
        op.report({"WARNING"}, T("colortool.no_colors"))
        return None
    return root, th, pairs


class EFX_OT_recolor_shift(bpy.types.Operator):
    """色系偏移：整个色系朝目标色相旋转，保留内部明暗与色相层次"""

    bl_idname      = "efx.recolor_shift"
    bl_label       = "Shift Palette"
    bl_description = ("Rotate every color so the palette's dominant hue lands on the target hue, "
                      "keeping saturation, brightness and internal hue variation")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def execute(self, context):
        prep = _prep_target(self, context)
        if prep is None:
            return {"CANCELLED"}
        _root, th, pairs = prep

        colors = [_read_rgb(it, kind) for it, kind in pairs]
        new_colors, dom = shift_hue(colors, th)
        if dom is None:
            self.report({"WARNING"}, T("colortool.all_neutral"))
            return {"CANCELLED"}
        for (it, kind), rgb in zip(pairs, new_colors):
            _write_rgb(it, kind, rgb)
        self.report({"INFO"}, T("colortool.shifted").format(n=len(pairs)))
        return {"FINISHED"}


class EFX_OT_recolor_align(bpy.types.Operator):
    """仅修改色相：所有颜色收敛到目标单一色相，各自明暗/饱和度保留"""

    bl_idname      = "efx.recolor_align"
    bl_label       = "Hue Only"
    bl_description = ("Set every color to the target's single hue while keeping each color's own "
                      "saturation and brightness (glow/shading is preserved). Neutral colors stay neutral")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def execute(self, context):
        prep = _prep_target(self, context)
        if prep is None:
            return {"CANCELLED"}
        _root, th, pairs = prep

        colors = [_read_rgb(it, kind) for it, kind in pairs]
        new_colors = align_hue(colors, th)
        for (it, kind), rgb in zip(pairs, new_colors):
            _write_rgb(it, kind, rgb)
        self.report({"INFO"}, T("colortool.aligned").format(n=len(pairs)))
        return {"FINISHED"}


class EFX_OT_recolor_replace(bpy.types.Operator):
    """直接替换：所有颜色的 RGB 设为目标色，各自 alpha 保留"""

    bl_idname      = "efx.recolor_replace"
    bl_label       = "Replace All Colors"
    bl_description = "Set every color's RGB to the target color (each keeps its own alpha)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def execute(self, context):
        root = _resolve_root(context)
        if root is None:
            self.report({"ERROR"}, T("colortool.no_root"))
            return {"CANCELLED"}

        tgt = tuple(context.scene.efx_recolor_target)
        n = 0
        for it, kind in _iter_color_items(root):
            _write_rgb(it, kind, tgt[:3])
            n += 1
        if n == 0:
            self.report({"WARNING"}, T("colortool.no_colors"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("colortool.replaced").format(n=n))
        return {"FINISHED"}


class EFX_OT_recolor_brightness(bpy.types.Operator):
    """亮度乘数：把所有亮度/强度字段乘以指定系数（可累积，1.0 不变）"""

    bl_idname      = "efx.recolor_brightness"
    bl_label       = "Apply Brightness"
    bl_description = ("Multiply every brightness / intensity field by the factor (cumulative on "
                      "repeat; 1.0 = no change). Colors themselves are untouched")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def execute(self, context):
        root = _resolve_root(context)
        if root is None:
            self.report({"ERROR"}, T("colortool.no_root"))
            return {"CANCELLED"}

        mult = float(context.scene.efx_brightness_mult)
        n = 0
        for it in _iter_brightness_items(root):
            it.float_value = it.float_value * mult
            n += 1
        if n == 0:
            self.report({"WARNING"}, T("colortool.no_brightness"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("colortool.brightness_done").format(n=n, m=mult))
        return {"FINISHED"}


# 面板

class EFX_PT_color_tool(bpy.types.Panel):
    """Color Editor 的全局改色工具。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Color Tool"
    bl_order       = -3

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "efx_recolor_target", text=T("colortool.target"))
        layout.separator(factor=0.3)
        layout.operator("efx.recolor_shift",   text=T("colortool.shift"),   icon="COLOR")
        layout.operator("efx.recolor_align",   text=T("colortool.align"),   icon="MOD_HUE_SATURATION")
        layout.operator("efx.recolor_replace", text=T("colortool.replace"), icon="BRUSH_DATA")

        layout.separator()
        layout.label(text=T("colortool.brightness_header"))
        layout.prop(context.scene, "efx_brightness_mult", text=T("colortool.brightness_mult"))
        layout.operator("efx.recolor_brightness", text=T("colortool.brightness_apply"), icon="LIGHT_SUN")


_CLASSES = (
    EFX_OT_recolor_shift,
    EFX_OT_recolor_align,
    EFX_OT_recolor_replace,
    EFX_OT_recolor_brightness,
    EFX_PT_color_tool,
)


def register():
    bpy.types.Scene.efx_recolor_target = FloatVectorProperty(
        name="Target Color",
        description="Target color for the global recolor tools",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0, 1.0),
    )
    bpy.types.Scene.efx_brightness_mult = FloatProperty(
        name="Brightness x",
        description="Multiplier applied to every brightness / intensity field (cumulative; 1.0 = no change)",
        default=1.0,
        min=0.0, soft_max=10.0,
        precision=3,
    )
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
    for prop in ("efx_recolor_target", "efx_brightness_mult"):
        try:
            delattr(bpy.types.Scene, prop)
        except Exception:
            pass
