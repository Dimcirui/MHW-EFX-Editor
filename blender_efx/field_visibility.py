# -*- coding: utf-8 -*-
"""按模式字段过滤 UI 中当前适用的字段。

隐藏不修改字段字节或导出结果；未列字段、读不到模式值的字段均保守显示。
"""

# 谓词
def _eq0(v): return v == 0
def _eq1(v): return v == 1
def _eq3(v): return v == 3
def _in01(v): return v in (0, 1)
def _in23(v): return v in (2, 3)
def _in24(v): return v in (2, 4)
def _truthy(v): return v != 0
def _bit0(v): return bool(v & 0x1)
def _bit1(v): return bool(v & 0x2)
def _bit5(v): return bool(v & 0x20)


def _shape3d(*allowed):
    """EMITTERSHAPE3D 谓词：允许形状或 Point 变体均显示。"""
    allowed_set = set(allowed)
    return lambda v: v in allowed_set or v >= 3


FIELD_VISIBILITY = {
    "VELOCITY3D": {
        "baseAxis":        ("velocityType", _eq0),
        "rotOrder":        ("velocityType", _eq0),
        "rotationX":       ("velocityType", _eq0),
        "rotationXJitter": ("velocityType", _eq0),
        "rotationY":       ("velocityType", _eq0),
        "rotationYJitter": ("velocityType", _eq0),
        "rotationZ":       ("velocityType", _eq0),
        "rotationZJitter": ("velocityType", _eq0),
        "offsetX":         ("velocityType", _eq1),
        "offsetY":         ("velocityType", _eq1),
        "offsetZ":         ("velocityType", _eq1),
        "sizeX":           ("velocityType", _eq1),
        "sizeY":           ("velocityType", _eq1),
        "sizeZ":           ("velocityType", _eq1),
        "minMovementThreshold": ("velocityType", _eq3),
    },
    "VELOCITY2D": {
        "velocityX":   ("velocityType", _eq1),
        "velocityY":   ("velocityType", _eq1),
        "divergenceX": ("velocityType", _eq1),
        "divergenceY": ("velocityType", _eq1),
    },
    "UVCONTROL": {
        "uv2_offset":  ("uv2_enable", _truthy),
        "uv2_offsetAdd":            ("uv2_enable", _truthy),
        "uv2_offsetCoef":     ("uv2_enable", _truthy),
        "uv2_scale":            ("uv2_enable", _truthy),
        "uv2_scaleAdd":       ("uv2_enable", _truthy),
        "uv2_scaleCoef":("uv2_enable", _truthy),
        "flowmapSpeed":              ("enableFlowmap", _truthy),
        "flowmapSpeedJitter":        ("enableFlowmap", _truthy),
        "flowmapSpeedCoef":          ("enableFlowmap", _truthy),
        "flowmapSpeedCoefJitter":    ("enableFlowmap", _truthy),
        "flowmapStrength":           ("enableFlowmap", _truthy),
        "flowmapStrengthJitter":     ("enableFlowmap", _truthy),
        "flowmapStrengthCoef":       ("enableFlowmap", _truthy),
        "flowmapStrengthCoefJitter": ("enableFlowmap", _truthy),
    },
    "TRANSFORM3D": {
        "translation_velocity":          ("enableVelocityBitflag", _bit0),
        "rotation_velocity":             ("enableVelocityBitflag", _bit0),
        "scale_velocity":                ("enableVelocityBitflag", _bit0),
        "translation_velocity_modifier": ("enableVelocityBitflag", _bit1),
        "rotation_velocity_modifier":    ("enableVelocityBitflag", _bit1),
        "scale_velocity_modifier":       ("enableVelocityBitflag", _bit1),
    },
    "HOMING": {
        "vanishRadius":          ("vanishMode", _truthy),
        "forceFieldRadius":      ("forceFieldMode", _truthy),
        "forceFieldSpeedScale":  ("forceFieldMode", _in24),
    },
    "EMITTERSHAPE3D": {
        "rangeDivideAxis":          ("shapeType", _shape3d(0)),
        "scanAngleHorizontal":      ("shapeType", _shape3d(1, 2)),
        "scanAngleVertical":        ("shapeType", _shape3d(1)),
        "rangeDivideHorizontalNum": ("shapeType", _shape3d(1, 2)),
        "radiusEnd":                ("shapeType", _shape3d(2)),
        "radiusOrigin":             ("shapeType", _shape3d(2)),
    },
    "ROTATEANIM": {
        "billboardRotation":            ("rotationModeMask", _in01),
        "billboardRotationJitter":      ("rotationModeMask", _in01),
        "billboardRotationCoef":       ("rotationModeMask", _in01),
        "billboardRotationCoefJitter": ("rotationModeMask", _in01),
        "spinSpeedCoefX":            ("rotationModeMask", _in23),
        "spinSpeedCoefXJitter":      ("rotationModeMask", _in23),
        "spinSpeedCoefY":            ("rotationModeMask", _in23),
        "spinSpeedCoefYJitter":      ("rotationModeMask", _in23),
        "spinSpeedCoefZ":            ("rotationModeMask", _in23),
        "spinSpeedCoefZJitter":      ("rotationModeMask", _in23),
        "spin_velocity":             ("rotationModeMask", _in23),
    },
    "SPAWN": {
        "spawnFrame":       ("spawnFlags", _bit5),
        "spawnFrameJitter": ("spawnFlags", _bit5),
    },
    "RIBBON": {
        "colorRange":              ("useColorRange", _truthy),
        "epvcolor_1":              ("useColorRange", _truthy),
        "brightness":              ("blendMode", _truthy),
        "brightnessJitter":        ("blendMode", _truthy),
        "flowmapPath":             ("enableFlowmap", _truthy),
        "flowmapSpeed":            ("enableFlowmap", _truthy),
        "flowmapSpeedJitter":      ("enableFlowmap", _truthy),
        "flowmapSpeedCoef":        ("enableFlowmap", _truthy),
        "flowmapSpeedCoefJitter":  ("enableFlowmap", _truthy),
        "flowmapStrength":         ("enableFlowmap", _truthy),
        "flowmapStrengthJitter":   ("enableFlowmap", _truthy),
        "flowmapStrengthCoef":     ("enableFlowmap", _truthy),
        "flowmapStrengthCoefJitter": ("enableFlowmap", _truthy),
        "flowmapPlayOnce":         ("enableFlowmap", _truthy),
        "flowmapReverse":          ("enableFlowmap", _truthy),
    },
    "STRAINRIBBON": {
        "colorRange":              ("useColorRange", _truthy),
        "epv_color_slot2":         ("useColorRange", _truthy),
        "emissionStrength":        ("useEmission", _truthy),
        "emissionStrengthJitter":  ("useEmission", _truthy),
        "flowmapPath":             ("enableFlowmap", _truthy),
        "flowmapSpeed":            ("enableFlowmap", _truthy),
        "flowmapSpeedJitter":      ("enableFlowmap", _truthy),
        "flowmapSpeedCoef":        ("enableFlowmap", _truthy),
        "flowmapSpeedCoefJitter":  ("enableFlowmap", _truthy),
        "flowmapStrength":         ("enableFlowmap", _truthy),
        "flowmapStrengthJitter":   ("enableFlowmap", _truthy),
        "flowmapStrengthCoef":     ("enableFlowmap", _truthy),
        "flowmapStrengthCoefJitter": ("enableFlowmap", _truthy),
    },
    "LIGHTNING": {
        "flowmapPath":             ("enableFlowmap", _truthy),
        "flowmapSpeed":            ("enableFlowmap", _truthy),
        "flowmapSpeedJitter":      ("enableFlowmap", _truthy),
        "flowmapSpeedCoef":        ("enableFlowmap", _truthy),
        "flowmapSpeedCoefJitter":  ("enableFlowmap", _truthy),
        "flowmapStrength":         ("enableFlowmap", _truthy),
        "flowmapStrengthJitter":   ("enableFlowmap", _truthy),
        "flowmapStrengthCoef":     ("enableFlowmap", _truthy),
        "flowmapStrengthCoefJitter": ("enableFlowmap", _truthy),
    },
    "BILLBOARD3D": {
        "colorRange":              ("useColorRange", _truthy),
        "colorRangeCorrectColorNo": ("useColorRange", _truthy),
        "brightness":              ("blendMode", _truthy),
        "brightnessJitter":        ("blendMode", _truthy),
    },
    "BILLBOARD2D": {
        "colorRange":              ("useColorRange", _truthy),
        "colorRangeCorrectColorNo": ("useColorRange", _truthy),
        "brightness":              ("blendMode", _truthy),
        "brightnessJitter":        ("blendMode", _truthy),
    },
    "PLANE": {
        "colorRange":              ("useColorRange", _truthy),
        "colorRangeCorrectColorNo": ("useColorRange", _truthy),
        "brightness":              ("blendMode", _truthy),
        "brightnessJitter":        ("blendMode", _truthy),
    },
    "MESH": {
        "colorRange":            ("useColorRange", _truthy),
        "emissiveColor":         ("useEmissiveColor", _truthy),
        "emissiveColorRange":    ("useEmissiveColorRange", _truthy),
    },
    "RIBBONBLADE": {
        "length":          ("lengthMode", _eq0),
        "maxLengthLimit":  ("lengthMode", _eq1),
        "contractionSpeed": ("lengthMode", _eq1),
    },
    "RGBFIRE": {
        "fireColorParam_appearFrame":       ("fireColorParam_useLife", _truthy),
        "fireColorParam_appearFrameJitter": ("fireColorParam_useLife", _truthy),
        "fireColorParam_keepFrame":         ("fireColorParam_useLife", _truthy),
        "fireColorParam_keepFrameJitter":   ("fireColorParam_useLife", _truthy),
        "fireColorParam_vanishFrame":       ("fireColorParam_useLife", _truthy),
        "fireColorParam_vanishFrameJitter": ("fireColorParam_useLife", _truthy),
        "fireColorParam_lifeType":          ("fireColorParam_useLife", _truthy),
        "smokeColorParam_appearFrame":       ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_appearFrameJitter": ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_keepFrame":         ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_keepFrameJitter":   ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_vanishFrame":       ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_vanishFrameJitter": ("smokeColorParam_useLife", _truthy),
        "smokeColorParam_lifeType":          ("smokeColorParam_useLife", _truthy),
    },
    "RGBWATER": {
        "specularColorParam_appearFrame":       ("specularColorParam_useLife", _truthy),
        "specularColorParam_appearFrameJitter": ("specularColorParam_useLife", _truthy),
        "specularColorParam_keepFrame":         ("specularColorParam_useLife", _truthy),
        "specularColorParam_keepFrameJitter":   ("specularColorParam_useLife", _truthy),
        "specularColorParam_vanishFrame":       ("specularColorParam_useLife", _truthy),
        "specularColorParam_vanishFrameJitter": ("specularColorParam_useLife", _truthy),
        "specularColorParam_lifeType":          ("specularColorParam_useLife", _truthy),
        "sheetColorParam_appearFrame":       ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_appearFrameJitter": ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_keepFrame":         ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_keepFrameJitter":   ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_vanishFrame":       ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_vanishFrameJitter": ("sheetColorParam_useLife", _truthy),
        "sheetColorParam_lifeType":          ("sheetColorParam_useLife", _truthy),
        "waterLerpParam_appearFrame":       ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_appearFrameJitter": ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_keepFrame":         ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_keepFrameJitter":   ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_vanishFrame":       ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_vanishFrameJitter": ("waterLerpParam_useLife", _truthy),
        "waterLerpParam_lifeType":          ("waterLerpParam_useLife", _truthy),
    },
}


def field_hidden(type_name, ori_name, get_value) -> bool:
    """该字段当前是否应隐藏（据其模式字段的当前值）。get_value(field_name)->int|None。"""
    rules = FIELD_VISIBILITY.get(type_name)
    if not rules:
        return False
    r = rules.get(ori_name)
    if r is None:
        return False
    mode_field, pred = r
    cur = get_value(mode_field)
    if cur is None:
        return False   # 读不到模式值 → 保守显示
    try:
        return not pred(int(cur))
    except Exception:
        return False
