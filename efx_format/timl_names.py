"""
efx_format/timl_names.py  —  TIML hash → 可读名 + game↔Blender 坐标换算（纯 Python，零 bpy）

TIML 通道名由两段 hash 组成：
  - timelineParameterHash：这条动画**影响哪个对象/块**（Transform3D / RgbFire / TypeRibbon…）。
    来源：Ezekial711 MHW Modding wiki「TIML Effect and Material Animation Hashes」声明表。
  - datatypeHash：动画的**哪个属性**（pos:X / rot:Z / 颜色…）。wiki 未列；transform 九条来自
    FreeKinetics defaultProps（jamcrc）。未知 hash 回退十六进制。

供 timl 通道编辑/预览的友好命名与（后续）transform3d → 真实属性映射使用。
"""

# ── timelineParameterHash → 名称（wiki Effect Declarations）─────────────────────
TLP_NAMES = {
    0x65004e2a: "MhEffectDecalBehavior", 0x6da6e5d1: "MhPointLightBehavior",
    0x75963575: "MhSpotLightBehavior",   0x4cdb308a: "Item",
    0x540a2572: "Transform2D",           0x4d111433: "Transform3D",
    0x2bda85f5: "Velocity2D",            0x32c1b4b4: "Velocity3D",
    0x2b61b0ed: "Billboard2D",           0x327a81ac: "Billboard3D",
    0x3481666b: "Plane",                 0x538af627: "Mesh",
    0x1436e592: "Ribbon",                0x1f09850e: "StrainRibbon",
    0x5ac7fc29: "UVSequence",            0x563c8065: "RotateAnim",
    0x2a62f92e: "ScaleAnim",             0x2a0363d4: "EmitterShape2D",
    0x33185295: "EmitterShape3D",        0x4a0d2b6a: "Life",
    0x60ba9117: "RgbFire",               0x2101c529: "RgbWater",
    0x39c68fb4: "TubeLight",             0x13a0f54f: "TonemapFilter",
    0x3f2b8294: "EffectEvent",           0x06e8d4c3: "DecalBehavior",
    0x0235f20e: "LightBehavior",         0x42e48dde: "PointLightBehavior",
    0x3de576dc: "SpotLightBehavior",     0x2c154dca: "FilterBehavior",
    0x582ba062: "RadialBlurFilterBehavior", 0x2ed89bcc: "ParentMaterial",
    0x096cabc4: "ColorCorrectFilter",
}

import math

# ── datatypeHash → (友好名, blender 属性, blender_array_index, kind)─────────────────
# transform 九条来自 FK defaultProps（jamcrc）。MHW Y-up → Blender Z-up：游戏 Y↔Z 轴**置换**
# （game Y→blender Z[index2]、game Z→blender Y[index1]），位置/旋转适用、缩放不置换。
# 这里直接存**置换后的 blender array_index** + kind（loc/rot/scl，决定单位/符号换算）。
# 元组：(label, bl_prop, bl_index, kind)
DT_TRANSFORM = {
    0x8E8AFE06: ("pos:X", "location", 0, "loc"),
    0xF98DCE90: ("pos:Y", "location", 2, "loc"),   # game Y → blender Z
    0x60849F2A: ("pos:Z", "location", 1, "loc"),   # game Z → blender Y
    0xF105BBE3: ("rot:X", "rotation_euler", 0, "rot"),
    0x86028B75: ("rot:Y", "rotation_euler", 2, "rot"),
    0x1F0BDACF: ("rot:Z", "rotation_euler", 1, "rot"),
    0x9486DF23: ("scl:X", "scale", 0, "scl"),
    0xE381EFB5: ("scl:Y", "scale", 1, "scl"),
    0x7A88BE0F: ("scl:Z", "scale", 2, "scl"),
}

# game↔Blender 数值换算（FK common/Constants 同款，互为精确逆）。
# AXIS_SIGN 按 blender 轴：blender Y(index1) 取负（game Z → blender -Y）。
_AXIS_SIGN = (1.0, -1.0, 1.0)
_LOC_UNIT = 100.0   # 游戏单位(cm) / 米


def game_to_blender(kind: str, bl_index: int, v: float) -> float:
    if kind == "loc":
        return v * _AXIS_SIGN[bl_index] / _LOC_UNIT
    if kind == "rot":
        return math.radians(v * _AXIS_SIGN[bl_index])
    return v   # scl 原样


def blender_to_game(kind: str, bl_index: int, v: float) -> float:
    if kind == "loc":
        return v * _AXIS_SIGN[bl_index] * _LOC_UNIT
    if kind == "rot":
        return math.degrees(v) * _AXIS_SIGN[bl_index]
    return v


def timeline_param_name(h: int) -> str:
    """timelineParameterHash → 名称，未知回退 0x 十六进制。"""
    return TLP_NAMES.get(h & 0xFFFFFFFF, "0x%08X" % (h & 0xFFFFFFFF))


def datatype_name(h: int) -> str:
    """datatypeHash → 友好属性名，未知回退 0x 十六进制。"""
    h &= 0xFFFFFFFF
    if h in DT_TRANSFORM:
        return DT_TRANSFORM[h][0]
    return "0x%08X" % h


def transform_mapping(h: int):
    """若 datatypeHash 是 transform 九条之一，返回 (bl_prop, bl_index, kind)，否则 None。
    供 transform3d 原生播放映射到真实 location/rotation_euler/scale。"""
    info = DT_TRANSFORM.get(h & 0xFFFFFFFF)
    if info is None:
        return None
    return info[1], info[2], info[3]


def channel_label(tlp_hash: int, dt_hash: int) -> str:
    """组合通道友好名：'Transform3D · pos:X'。"""
    return "%s · %s" % (timeline_param_name(tlp_hash), datatype_name(dt_hash))
