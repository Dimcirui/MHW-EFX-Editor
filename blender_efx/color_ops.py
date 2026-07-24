"""
blender_efx/color_ops.py  —  EFX Color Editor 全局改色工具

仅在 Color Editor 模式（导入时勾"仅导入颜色"，见 io_tree.py::_apply_color_editor_view）
下暴露的两个全局改色算子，面向"完全不懂 efx"的调色用户：

  · 色系偏移 (Shift)——相对色相旋转。算全体颜色的主色相 → 目标色相的差 Δ，每个颜色
    的色相各转同一个 Δ，饱和度/明度原样保留。红芯黄边 → 蓝芯青边：主色相精确落到目标，
    而内部明暗结构与色相层次全部保留。近中性色（S·V≈0）旋转色相后 RGB 不变，天然不被染色。
  · 直接替换 (Replace)——所有颜色的 RGB 直接设为目标色，各自 alpha 保留。

写值走 EFXFieldItem.color_rgba_value（COLOR_RGBA 字段）或 int_as_color_display
（TUBELIGHT headColor/tailColor 打包 int32），其 update 回调（_mark_attribute_dirty）
自动置 edited=True → 导出时该字段重新 pack；未触及的字段仍走 orig_b64 原样还原。
因此本工具不破坏 byte-perfect：改过的重打包、没改的逐字节原样（同普通字段编辑）。

作用域：Scene.efx_active_efx 指向的那个 EFX 文件（N 面板 Active EFX 选择器，导入时
已自动指向新导入的 root）。只处理颜色的 RGB 三通道，亮度/强度类标量（is_color_field
命中但非 RGB）与 alpha 通道不动。TIML 动画色 / mrl3 内联材质色不在 v1 范围。

纯色彩数学（shift_hue / _dominant_hue）只用 colorsys 标准库、零 bpy，可独立单测。
"""

import colorsys
import math

import bpy
from bpy.props import FloatVectorProperty

from . import color_fields as _cf
from . import root_collection as _rc
from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 纯色彩数学（零 bpy，可单测）
# ─────────────────────────────────────────────────────────────────────────────

def _dominant_hue(colors):
    """全体颜色按 S·V 加权的圆周平均色相（0-1）。

    权重取 S·V：高饱和、高亮度的颜色主导整体观感，近中性/近黑（S·V≈0）几乎不参与。
    色相是圆周量，直接算术平均会在 0/1 接缝出错，故转单位向量求和再取角。
    全部为中性色（累计向量为零）时无主色相，返回 None。

    colors：[(r, g, b), ...]，各分量 0-1。
    """
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
    """相对色相旋转（色系偏移）：主色相精确落到 target_hue，其余颜色各转同一个 Δ，
    S/V 保留——保留内部明暗结构与色相层次（红芯黄边 → 蓝芯青边）。

    返回 (new_colors, dominant_hue)。dominant_hue 为 None（全中性、无主色相）时
    原样返回 colors 副本，由调用方决定如何提示。

    colors：[(r, g, b), ...]；target_hue：0-1。
    """
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
    """绝对对齐（使用单一颜色）：每个颜色的色相直接设为 target_hue，S/V 保留。

    所有颜色收敛到同一个色相，只保留各自的明暗/饱和差异——红芯与黄边都变成目标色相
    的深浅两档（PS"着色"式）。近中性色（S≈0）色相无意义、设 hue 后 RGB 仍不变，
    故黑白/灰不被染色（与相对偏移一致，避免中性烟雾/黑边被莫名上色）。

    colors：[(r, g, b), ...]；target_hue：0-1。
    """
    out = []
    for r, g, b in colors:
        _h, s, v = colorsys.rgb_to_hsv(r, g, b)
        out.append(colorsys.hsv_to_rgb(target_hue, s, v))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# bpy 胶水：收集颜色字段 + 读写 RGB
# ─────────────────────────────────────────────────────────────────────────────

def _iter_color_items(root_col):
    """遍历 root_col 下全部 attribute，产出携带 RGB 的 (field_item, kind)。

    kind ∈ {'rgba', 'packed'}：
      'rgba'   → COLOR_RGBA 字段，值在 color_rgba_value（4 float，第4通道 alpha）。
      'packed' → TUBELIGHT headColor/tailColor 打包 int32，经 int_as_color_display 影子属性。

    遍历方式复用 io_tree._apply_color_editor_view 的 col_entry.all_objects（一次性、
    不做全场景反查，见 [[onchange-full-scene-scan-perf-bug]]）。read_only 字段跳过
    （其导出恒走 orig_b64，写值无效且会误导）。
    """
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


def _read_rgb(item, kind):
    v = item.int_as_color_display if kind == "packed" else item.color_rgba_value
    return (v[0], v[1], v[2])


def _write_rgb(item, kind, rgb):
    """写回 RGB 三通道，保留原 alpha（第4通道）。触发 update → edited=True。"""
    if kind == "packed":
        v = item.int_as_color_display
        item.int_as_color_display = (rgb[0], rgb[1], rgb[2], v[3])
    else:
        v = item.color_rgba_value
        item.color_rgba_value = (rgb[0], rgb[1], rgb[2], v[3])


def _resolve_root(context):
    """当前操作的 Color Editor 根，按优先级解析（找不到 → None）：

      1. Scene.efx_active_efx（N 面板 Active EFX 选择器）指向的颜色根；
      2. 当前活动对象所属的颜色根；
      3. 场景中唯一的颜色根——「仅导入颜色」后通常只有一个文件，导入算子并不会
         自动把它设成 active_efx，靠这条兜底让面板/算子导入后即可用，无需手动选。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

def _prep_target(op, context):
    """三个算子共用的前置：解析颜色根 + 校验目标色有色相 + 收集颜色字段。

    成功返回 (root, target_hue, pairs)；失败已 report 并返回 None。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# 面板（VIEW_3D N 面板 → EFX 标签，仅 Color Editor 模式）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_color_tool(bpy.types.Panel):
    """全局改色工具（仅 Color Editor 模式出现）"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Color Tool"
    bl_order       = -3   # 紧跟主面板 MHW EFX(-4) 之后

    @classmethod
    def poll(cls, context):
        return _resolve_root(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "efx_recolor_target", text=T("colortool.target"))
        layout.separator(factor=0.3)
        # 三个平行操作：色系偏移 → 仅修改色相 → 直接替换全部
        layout.operator("efx.recolor_shift",   text=T("colortool.shift"),   icon="COLOR")
        layout.operator("efx.recolor_align",   text=T("colortool.align"),   icon="MOD_HUE_SATURATION")
        layout.operator("efx.recolor_replace", text=T("colortool.replace"), icon="BRUSH_DATA")


_CLASSES = (
    EFX_OT_recolor_shift,
    EFX_OT_recolor_align,
    EFX_OT_recolor_replace,
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
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
    try:
        del bpy.types.Scene.efx_recolor_target
    except Exception:
        pass
