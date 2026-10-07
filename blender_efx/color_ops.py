"""Color Editor 的全局颜色与亮度工具。

维护约束：
- 仅修改可编辑颜色字段的 RGB，保留 alpha；字段更新走 PropertyGroup 以标记导出重打包。
- 颜色根优先显式目标、活动对象所属根，最后才接受场景唯一的颜色根。
- 色彩运算和按 Entry 的改色规则在 color_math，不依赖 bpy。
"""

import colorsys
import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty

from . import color_fields as _cf
from . import color_math as _cm
from . import root_collection as _rc
from . import timl_io as _tio
from ..efx_format import hashes as _h
from ..efx_format import timl as _timl
from ..efx_format.timl import names as _tn
from .i18n import T


# Blender 数据访问

# 与染色层相乘的渲染体类型。
_RENDER_TYPES = frozenset({
    _h.BILLBOARD3D, _h.BILLBOARD2D, _h.PLANE, _h.RIBBON, _h.RIBBONBLADE,
    _h.STRAINRIBBON, _h.LIGHTNING, _h.MESH,
})
_LAYER_TYPES = frozenset({_h.RGBFIRE, _h.RGBWATER})

# 变暗时按混合方式分类：加法和反相乘法显示不出暗色，不绘制的 Entry 不处理；
# 其余（含没有 SHADERSETTINGS 的 Entry）都能显示暗色。
_BRIGHT_ONLY_STATES = frozenset({2, 3, 7})
_NO_DRAW_STATES = frozenset({6})

# TIML 轨道归属：TLP 哈希 → 属性类型哈希。
_TLP_TO_TYPE = {tlp: getattr(_h, blk) for blk, tlp in _tn.BLOCK_TO_TLP.items() if hasattr(_h, blk)}

# 对应亮度字段的 TIML 浮点轨道：(TLP, DT)。
_BRIGHTNESS_KEYS = frozenset(
    (_tn.BLOCK_TO_TLP[blk], dt)
    for (blk, name), dts in _tn.FIELD_TO_DT.items()
    if isinstance(name, str) and blk in _tn.BLOCK_TO_TLP and name in _cf._BRIGHTNESS_NAMES
    for dt, dtype in dts if dtype == 2
)


def _role(type_hash):
    if type_hash in _RENDER_TYPES:
        return _cm.RENDER
    if type_hash in _LAYER_TYPES:
        return _cm.LAYER
    return _cm.OTHER


class _Group:
    """一个 Entry 的颜色项与亮度项。

    颜色项为 ("field", item, kind, 角色) 或 ("key", transform, keyframe, 解码值, 角色)；
    亮度项为 ("field", item) 或 ("key", transform, keyframe, 解码值)。
    """

    __slots__ = ("body", "refraction", "blend_state", "colors", "brightness", "epv_slots",
                 "timl", "timl_changed")

    def __init__(self, body):
        self.body = body
        self.refraction = False
        self.blend_state = None
        self.colors = []
        self.epv_slots = []
        self.brightness = []
        self.timl = None
        self.timl_changed = False


def _has_timl_targets(t):
    for d in t.animations:
        if d is None:
            continue
        for ty in d.types:
            for tf in ty.transforms:
                if tf.data_type == 3 or (ty.timeline_param_hash, tf.datatype_hash) in _BRIGHTNESS_KEYS:
                    return True
    return False


def _collect_timl(g):
    """把 Entry TIML 里的颜色轨道和亮度轨道关键帧加入分组。"""
    from . import io_tree as _iot
    from . import timl_edit as _te
    t = _timl.parse_timl(_tio._entry_timl_bytes(g.body))
    if t is None or not _has_timl_targets(t):
        return
    # 按 F 曲线的当前值解析，只读不写回。
    h = _iot.find_timl_handle(g.body)
    if h is not None:
        t = _timl.parse_timl(_te.sync_fcurves_to_bytes(h, g.body))
        if t is None:
            return
    g.timl = t
    for d in t.animations:
        if d is None:
            continue
        for ty in d.types:
            tlp = ty.timeline_param_hash
            role = _role(_TLP_TO_TYPE.get(tlp, 0))
            for tf in ty.transforms:
                if tf.data_type == 3:
                    for kf in tf.keyframes:
                        dec = _timl.decode_keyframe(kf.raw, 3, tf.datatype_hash)
                        g.colors.append(("key", tf, kf, dec, role))
                elif tf.data_type == 2 and (tlp, tf.datatype_hash) in _BRIGHTNESS_KEYS:
                    for kf in tf.keyframes:
                        dec = _timl.decode_keyframe(kf.raw, 2, tf.datatype_hash)
                        g.brightness.append(("key", tf, kf, dec))


def _collect_groups(root_col):
    """按 Entry 收集可编辑颜色项和亮度项（含 TIML 关键帧）；read_only 项不得写入。"""
    col_entry = _rc.get_leaf_collection(root_col, "EFX_ENTRY")
    if col_entry is None:
        return []
    groups = {}
    for obj in col_entry.all_objects:
        typ = obj.get("~TYPE")
        if typ == "EFX_ENTRY":
            groups.setdefault(obj.name, _Group(obj))
            continue
        if typ != "EFX_ATTRIBUTE":
            continue
        try:
            type_hash = int(str(obj.get("type_hash", "0")))
            items = obj.efx_block.field_items
        except Exception:
            continue
        parent = obj.parent
        key = parent.name if parent is not None else obj.name
        g = groups.get(key)
        if g is None:
            g = groups[key] = _Group(parent)
        if type_hash == _h.REFRACTION:
            g.refraction = True
        elif type_hash == _h.SHADERSETTINGS:
            from . import fields as _fields
            for it in items:
                if it.ori_name == "blendStateType":
                    g.blend_state = _fields._enum_backing_read(it)
        role = _role(type_hash)
        for it in items:
            if getattr(it, "read_only", False):
                continue
            if it.data_type == "COLOR_RGBA":
                g.colors.append(("field", it, "rgba", role))
            elif (type_hash, it.ori_name) in _cf._PACKED_INT_COLOR_FIELDS:
                g.colors.append(("field", it, "packed", role))
            elif _cf.is_brightness_field(type_hash, it.ori_name, it.data_type):
                g.brightness.append(("field", it))
            elif _cf.is_epv_slot_field(it.ori_name, it.data_type):
                g.epv_slots.append(it)
    out = []
    for g in groups.values():
        if g.body is not None and g.body.get("~TYPE") == "EFX_ENTRY":
            _collect_timl(g)
        if g.colors or g.brightness:
            out.append(g)
    return out


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


def _member_rgb(m):
    if m[0] == "field":
        return _read_rgb(m[1], m[2])
    subs = m[3]["subs"]
    return tuple(subs[i]["value"] / 255.0 for i in range(3))


def _encode_key(tf, kf, dec):
    kf.raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, dec["frame"],
                                   dec["transition"], dec["kf_dtype"], dec["subs"])


def _to_math(groups):
    return [(g.refraction, [(m[-1], _member_rgb(m)) for m in g.colors]) for g in groups]


def _flush_timl(groups):
    """把改过的关键帧写回 Entry 的 TIML。"""
    from . import timl_edit as _te
    for g in groups:
        if g.timl_changed and g.timl is not None:
            g.timl.dirty = True
            _te.set_entry_timl(g.body, g.timl.serialize())
            g.timl_changed = False


def _release_epv_slots(g):
    """关掉 Entry 的 EPV 颜色槽，让改过的本地颜色生效。"""
    from . import fields as _fields
    for it in g.epv_slots:
        if _fields._enum_backing_read(it) != 0:
            _fields._enum_backing_write(it, 0)


def _apply_plan(groups, plan):
    """写入规划结果，返回改动的颜色数。改过颜色的 Entry 同时关掉 EPV 颜色槽。"""
    n = 0
    for g, new in zip(groups, plan):
        if any(rgb is not None for rgb in new):
            _release_epv_slots(g)
        for m, rgb in zip(g.colors, new):
            if rgb is None:
                continue
            if m[0] == "field":
                _write_rgb(m[1], m[2], rgb)
            else:
                dec = m[3]
                for i in range(3):
                    dec["subs"][i]["value"] = int(round(min(1.0, max(0.0, rgb[i])) * 255.0))
                _encode_key(m[1], m[2], dec)
                g.timl_changed = True
            n += 1
    _flush_timl(groups)
    return n


def _selected_entry_names(context):
    """选中对象对应的 Entry 名；选中属性或 TIML 句柄时取其所属 Entry。"""
    names = set()
    for obj in getattr(context, "selected_objects", None) or ():
        typ = obj.get("~TYPE")
        if typ == "EFX_ENTRY":
            names.add(obj.name)
        elif typ in ("EFX_ATTRIBUTE", "EFX_TIML") and obj.parent is not None:
            names.add(obj.parent.name)
    return names


def _detect_hue(groups):
    """按当前颜色识别主色相；全中性时返回 None。"""
    return _cm.dominant_hue(_cm.effective_colors(_to_math(groups)))


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

_MODE_DESCRIPTIONS = {
    "SHIFT": ("Rotate every color so the effect's main hue lands on the target hue, keeping saturation, "
              "brightness and the differences between colors. Uncolored distortion is left unchanged"),
    "ALIGN": ("Set every color to the target hue, keeping each color's own saturation and brightness. "
              "Neutral colors and uncolored distortion are left unchanged"),
    "REPLACE": ("Set every color to the target color, keeping each color's alpha. "
                "Uncolored distortion is left unchanged"),
    "DARKEN": "Set colors to the dark color",
}


class EFX_OT_recolor_apply(bpy.types.Operator):
    """按当前模式改色，作用于整个 EFX 或选中的 Entry"""

    bl_idname      = "efx.recolor_apply"
    bl_label       = "Apply"
    bl_options     = {"REGISTER", "UNDO"}

    selected_only: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return _MODE_DESCRIPTIONS.get(context.scene.efx_recolor_mode, "")

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def execute(self, context):
        root = _resolve_root(context)
        if root is None:
            self.report({"ERROR"}, T("colortool.no_root"))
            return {"CANCELLED"}
        groups = [g for g in _collect_groups(root) if g.colors]
        if self.selected_only:
            names = _selected_entry_names(context)
            if not names:
                self.report({"WARNING"}, T("colortool.no_selection"))
                return {"CANCELLED"}
            groups = [g for g in groups if g.body is not None and g.body.name in names]
        if not groups:
            self.report({"WARNING"}, T("colortool.no_colors"))
            return {"CANCELLED"}

        scn = context.scene
        mode = scn.efx_recolor_mode
        if mode == "DARKEN":
            groups = [g for g in groups if g.blend_state not in _NO_DRAW_STATES]
            if scn.efx_recolor_black_white:
                dark = [g for g in groups if g.blend_state not in _BRIGHT_ONLY_STATES]
                white = [g for g in groups if g.blend_state in _BRIGHT_ONLY_STATES]
            else:
                dark, white = groups, []
            tgt = tuple(scn.efx_recolor_dark)[:3]
            n = _apply_plan(dark, _cm.plan_recolor(_to_math(dark), _cm.REPLACE, tgt))
            w = _apply_plan(white, _cm.plan_recolor(_to_math(white), _cm.REPLACE, (1.0, 1.0, 1.0)))
            if n + w == 0:
                self.report({"WARNING"}, T("colortool.darken_none"))
                return {"CANCELLED"}
            msg = T("colortool.darkened").format(n=n)
            if w:
                msg += T("colortool.whitened").format(n=w)
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        if mode == "REPLACE":
            tgt = tuple(scn.efx_recolor_target)[:3]
            op = _cm.REPLACE_KEEP_V if scn.efx_recolor_keep_value else _cm.REPLACE
            n = _apply_plan(groups, _cm.plan_recolor(_to_math(groups), op, tgt))
            msg = T("colortool.replaced")
        else:
            th = _hue_of(scn)
            tgt = colorsys.hsv_to_rgb(th, 1.0, 1.0)
            if mode == "SHIFT":
                # 主色相按本次作用范围内的当前颜色识别。
                src = _detect_hue(groups)
                if src is None:
                    self.report({"WARNING"}, T("colortool.all_neutral"))
                    return {"CANCELLED"}
                plan = _cm.plan_recolor(_to_math(groups), _cm.SHIFT, tgt, delta=(th - src) % 1.0)
                msg = T("colortool.shifted")
            else:
                plan = _cm.plan_recolor(_to_math(groups), _cm.ALIGN, tgt)
                msg = T("colortool.aligned")
            n = _apply_plan(groups, plan)
        if n == 0:
            self.report({"WARNING"}, T("colortool.no_colors"))
            return {"CANCELLED"}
        self.report({"INFO"}, msg.format(n=n))
        return {"FINISHED"}


class EFX_OT_recolor_brightness(bpy.types.Operator):
    """亮度乘数：把所有亮度/强度字段乘以指定系数（可累积，1.0 不变）"""

    bl_idname      = "efx.recolor_brightness"
    bl_label       = "Apply Brightness"
    bl_description = ("Multiply every brightness / intensity field by the factor (cumulative on "
                      "repeat; 1.0 = no change). Colors themselves are untouched, "
                      "and uncolored distortion is left unchanged")
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
        groups = _collect_groups(root)
        n = 0
        for g, entry in zip(groups, _to_math(groups)):
            if _cm.is_skipped(entry):
                continue
            for m in g.brightness:
                if m[0] == "field":
                    m[1].float_value = m[1].float_value * mult
                else:
                    dec = m[3]
                    dec["subs"][0]["value"] = dec["subs"][0]["value"] * mult
                    _encode_key(m[1], m[2], dec)
                    g.timl_changed = True
                n += 1
        _flush_timl(groups)
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
        scn = context.scene
        mode = scn.efx_recolor_mode

        row = layout.row(align=True)
        for value, key in (("SHIFT", "colortool.shift"), ("ALIGN", "colortool.align"),
                           ("REPLACE", "colortool.replace"), ("DARKEN", "colortool.darken")):
            row.prop_enum(scn, "efx_recolor_mode", value, text=T(key))

        col = layout.column()
        if mode in ("SHIFT", "ALIGN"):
            row = col.row(align=True)
            row.prop(scn, "efx_recolor_hue", text=T("colortool.hue"), slider=True)
            sub = row.row(align=True)
            sub.ui_units_x = 2
            sub.prop(scn, "efx_recolor_hue_swatch", text="")
        elif mode == "REPLACE":
            col.prop(scn, "efx_recolor_target", text=T("colortool.target"))
            col.prop(scn, "efx_recolor_keep_value", text=T("colortool.keep_value"))
        else:
            col.prop(scn, "efx_recolor_dark", text=T("colortool.dark_color"))
            col.prop(scn, "efx_recolor_black_white", text=T("colortool.black_white"))
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = bool(_selected_entry_names(context))
        sub.operator("efx.recolor_apply", text=T("colortool.apply_selected")).selected_only = True
        row.operator("efx.recolor_apply", text=T("colortool.apply_all")).selected_only = False

        layout.separator()
        layout.label(text=T("colortool.brightness_header"))
        layout.prop(context.scene, "efx_brightness_mult", text=T("colortool.brightness_mult"))
        layout.operator("efx.recolor_brightness", text=T("colortool.brightness_apply"), icon="LIGHT_SUN")


_CLASSES = (
    EFX_OT_recolor_apply,
    EFX_OT_recolor_brightness,
    EFX_PT_color_tool,
)


_TWO_PI = 2.0 * math.pi
_syncing = False


def _hue_of(scn):
    return (scn.efx_recolor_hue / _TWO_PI) % 1.0


def _on_hue(self, context):
    global _syncing
    if _syncing:
        return
    _syncing = True
    try:
        self.efx_recolor_hue_swatch = colorsys.hsv_to_rgb(_hue_of(self), 1.0, 1.0)
    finally:
        _syncing = False


def _on_swatch(self, context):
    """色块被改（含吸管取色）时，把它的色相同步回滑条；中性色不改滑条。"""
    global _syncing
    if _syncing:
        return
    h, s, v = colorsys.rgb_to_hsv(*tuple(self.efx_recolor_hue_swatch))
    _syncing = True
    try:
        if s * v > 0.0:
            self.efx_recolor_hue = h * _TWO_PI
        self.efx_recolor_hue_swatch = colorsys.hsv_to_rgb(_hue_of(self), 1.0, 1.0)
    finally:
        _syncing = False


def register():
    bpy.types.Scene.efx_recolor_mode = EnumProperty(
        name="Recolor Mode",
        items=(
            ("SHIFT", "Shift Palette", _MODE_DESCRIPTIONS["SHIFT"]),
            ("ALIGN", "Hue Only", _MODE_DESCRIPTIONS["ALIGN"]),
            ("REPLACE", "Replace", _MODE_DESCRIPTIONS["REPLACE"]),
            ("DARKEN", "Darken", _MODE_DESCRIPTIONS["DARKEN"]),
        ),
        default="SHIFT",
    )
    bpy.types.Scene.efx_recolor_hue = FloatProperty(
        name="Target Hue",
        description="Hue to apply",
        subtype="ANGLE",
        min=0.0, max=_TWO_PI,
        default=0.0,
        update=_on_hue,
    )
    bpy.types.Scene.efx_recolor_hue_swatch = FloatVectorProperty(
        name="Target Hue",
        description="Preview of the target hue. Pick a color here to take its hue",
        subtype="COLOR",
        size=3,
        min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0),
        update=_on_swatch,
    )
    bpy.types.Scene.efx_recolor_target = FloatVectorProperty(
        name="Target Color",
        description="Color to apply",
        subtype="COLOR",
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0, 1.0),
    )
    bpy.types.Scene.efx_recolor_dark = FloatVectorProperty(
        name="Dark Color",
        description="Dark color to apply",
        subtype="COLOR",
        size=3,
        min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0),
    )
    bpy.types.Scene.efx_recolor_black_white = BoolProperty(
        name="Black and White",
        description=("Parts that can't show dark colors turn pure white. "
                     "When off, every part is set to the dark color"),
        default=True,
    )
    bpy.types.Scene.efx_recolor_keep_value = BoolProperty(
        name="Keep Lightness",
        description="Keep each color's own lightness and only take the target's hue and saturation",
        default=True,
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
    for prop in ("efx_recolor_mode", "efx_recolor_hue", "efx_recolor_hue_swatch",
                 "efx_recolor_target", "efx_recolor_dark", "efx_recolor_black_white",
                 "efx_recolor_keep_value",
                 "efx_brightness_mult"):
        try:
            delattr(bpy.types.Scene, prop)
        except Exception:
            pass
