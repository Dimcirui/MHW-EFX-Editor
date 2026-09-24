# -*- coding: utf-8 -*-
"""字段显示顺序的局部订正表。

维护约束：
- 未登记的字段保持字节序；本表仅影响显示，不参与二进制导出。
- 键为类型名，值为 ``{字段: 前置锚点}``。移动以显示单元进行，value/jitter 配对不可拆开。
- 锚点必须是显示单元的 lead 字段；多个字段不能直接锚定同一字段，应改为链式锚定。
"""

FIELD_ORDER_ANCHORS = {
    # 开关应紧邻其控制字段。流动贴图组的位置由 blender_efx/field_groups.py 决定。
    "BILLBOARD2D":  {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
    },
    "BILLBOARD3D":  {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
    },
    "PLANE":        {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
    },
    "RIBBON":       {
        # 两个 EPV 色槽分别紧邻 color 与 colorRange。
        "epvcolor_0": "spacer0",
        "epvcolor_1": "spacer1",
    },
    "STRAINRIBBON": {
        # 两个 EPV 色槽分别紧邻 color 与 colorRange。
        "epv_color_slot1": "spacer00",
        "epv_color_slot2": "useColorRange",
    },
    # MESH 的颜色、发光和旋转控制按其所属字段组显示。
    "MESH": {
        "useColorRange":         "color",
        "colorRate":             "colorRange",
        "useEmissiveColor":      "colorRate",
        "useEmissiveColorRange": "emissiveColor",
        "emissiveColorRate":     "emissiveColorRange",
        "rotationOrder":         "rotation",
    },

    # 成组字段保持相邻显示。
    "ROTATEANIM": {"spin_velocity": "billboardRotationCoef"},
    "RAYCAST": {"speed": "maxDistance"},
    # VELOCITY3D 按控制项、运动参数和类型专属字段分组显示。
    "VELOCITY3D": {
        "speed":                 "typeFlag",
        "speedCoef":             "speed",
        "movementDelay":         "speedCoef",
        "velocityType":          "movementDelay",
        "minMovementThreshold":  "sizeZ",
    },
    # EMITTERSHAPE3D 的分段和射线依赖控制贴近所属字段。
    "EMITTERSHAPE3D": {
        "rangeDivideAxis": "scanAngleVertical",
        "rayCastDependency": "rangeXYZ",
    },
    # RGBFIRE 按全局、火焰、烟雾与插值字段分组显示。
    "RGBFIRE": {
        "colorRate":                       "typeFlag",
        "alphaFactor":                     "colorRate",
        "fireColorParam_correctColorNo":   "alphaFactor",
        "fireColor":                       "fireColorParam_correctColorNo",
        "fireFactor":                      "fireColor",
        "fireColorParam_lighting":         "fireFactor",
        "fireColorParam_useLife":          "fireColorParam_lighting",
        "fireColorParam_appearFrame":      "fireColorParam_useLife",
        "fireColorParam_keepFrame":        "fireColorParam_appearFrame",
        "fireColorParam_vanishFrame":      "fireColorParam_keepFrame",
        "fireColorParam_lifeType":         "fireColorParam_vanishFrame",
        "smokeColorParam_correctColorNo":  "fireColorParam_lifeType",
        "smokeColor":                      "smokeColorParam_correctColorNo",
        "redChFactor":                     "smokeColor",
        "smokeColorParam_lighting":        "redChFactor",
        "smokeColorParam_useLife":         "smokeColorParam_lighting",
        "smokeColorParam_appearFrame":     "smokeColorParam_useLife",
        "smokeColorParam_keepFrame":       "smokeColorParam_appearFrame",
        "smokeColorParam_vanishFrame":     "smokeColorParam_keepFrame",
        "smokeColorParam_lifeType":        "smokeColorParam_vanishFrame",
        "lerpAlphaToBlue":                 "smokeColorParam_lifeType",
    },

    # RGBWATER 按全局、高光、水膜、反射与插值字段分组显示。
    "RGBWATER": {
        "colorRate":                       "typeFlag",
        "intensityAlpha":                  "colorRate",
        "normalSharpness":                 "intensityAlpha",
        "specularColorParam_correctColorNo": "normalSharpness",
        "colorSpecular":                   "specularColorParam_correctColorNo",
        "intensitySpecular":               "colorSpecular",
        "specularColorParam_lighting":     "intensitySpecular",
        "specularColorParam_useLife":      "specularColorParam_lighting",
        "specularColorParam_appearFrame":  "specularColorParam_useLife",
        "specularColorParam_keepFrame":    "specularColorParam_appearFrame",
        "specularColorParam_vanishFrame":  "specularColorParam_keepFrame",
        "specularColorParam_lifeType":     "specularColorParam_vanishFrame",
        "sheetColorParam_correctColorNo":  "specularColorParam_lifeType",
        "colorSheet":                      "sheetColorParam_correctColorNo",
        "intensitySheet":                  "colorSheet",
        "sheetColorParam_lighting":        "intensitySheet",
        "sheetColorParam_useLife":         "sheetColorParam_lighting",
        "sheetColorParam_appearFrame":     "sheetColorParam_useLife",
        "sheetColorParam_keepFrame":       "sheetColorParam_appearFrame",
        "sheetColorParam_vanishFrame":     "sheetColorParam_keepFrame",
        "sheetColorParam_lifeType":        "sheetColorParam_vanishFrame",
        "cubemapPath":                     "sheetColorParam_lifeType",
        "intensityCubeMap":                "cubemapPath",
        "waterLerpGtoB":                   "intensityCubeMap",
        "waterLerpParam_lighting":         "waterLerpGtoB",
        "waterLerpParam_useLife":          "waterLerpParam_lighting",
        "waterLerpParam_appearFrame":      "waterLerpParam_useLife",
        "waterLerpParam_keepFrame":        "waterLerpParam_appearFrame",
        "waterLerpParam_vanishFrame":      "waterLerpParam_keepFrame",
        "waterLerpParam_lifeType":         "waterLerpParam_vanishFrame",
    },

    # TRANSFORM3D 将速度与修正量分别分组，供对应位开关控制显示。
    "TRANSFORM3D": {
        "rotation_velocity":             "translation_velocity",
        "scale_velocity":                "rotation_velocity",
        "translation_velocity_modifier": "scale_velocity",
        "rotation_velocity_modifier":    "translation_velocity_modifier",
        "scale_velocity_modifier":       "rotation_velocity_modifier",
    },
}


def display_anchors(type_name: str) -> dict:
    """某属性类型的顺序订正表；没登记的类型返回空字典（=保持字节序）。"""
    return FIELD_ORDER_ANCHORS.get(type_name) or {}
