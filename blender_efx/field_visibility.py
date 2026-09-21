# -*- coding: utf-8 -*-
"""
blender_efx/field_visibility.py — 按 mode 字段过滤生效字段（Route 2，纯 UI 层）

某些块由一个"模式"字段决定其余字段是否生效（游戏忽略非生效字段）。这里按模式值过滤显示：
选定模式只暴露对应生效字段，其余隐藏。**纯视觉、非破坏**——隐藏字段的字节原样保留，
导出不受影响；面板有"显示全部字段"开关兜底。

表结构：type_name -> { conditional_field: (mode_field, predicate) }
  predicate(mode_value:int) -> True 显示 / False 隐藏。
未列出的字段恒显示；mode 字段本身恒显示；读不到模式值时保守显示。

⚠ 置信度：VELOCITY3D/2D 的 velocityType 门控有 schema 注释/实测支撑（velocityType=0 方向类
字段、=1 offset/size 类字段）。EMITTERSHAPE3D 的 shapeType 门控、HOMING 的三条门控均为实机
测试确认。UVCONTROL（uv2_enable 直接开关 uv2 组）、TRANSFORM3D（enableVelocityBitflag 位名
即"启用速度/加速度"）为强语义推断。RANDOMFIX 因 mode→字段关系尚不明确，**暂不门控**
（默认全显示），待实机/RE 补充。RGBFIRE/RGBWATER 的 UseLife 门控为强语义推断
（devlecture 面板分组 + 语料侧 useLife=0 时 keep/vanish 停在默认值不变，双重支撑）。
"""

# ── 谓词（模块级具名，便于复用/可读）───────────────────────────────────────────
def _eq0(v): return v == 0          # 枚举取 0
def _eq1(v): return v == 1          # 枚举取 1
def _eq3(v): return v == 3          # 枚举取 3
def _in01(v): return v in (0, 1)    # 枚举取 0 或 1
def _in23(v): return v in (2, 3)    # 枚举取 2 或 3
def _in24(v): return v in (2, 4)    # 枚举取 2 或 4
def _truthy(v): return v != 0       # 布尔/开关（≠0 生效）
def _bit0(v): return bool(v & 0x1)  # 位 0
def _bit1(v): return bool(v & 0x2)  # 位 1
def _bit5(v): return bool(v & 0x20)  # 位 5


def _shape3d(*allowed):
    """EMITTERSHAPE3D 专用谓词工厂：shapeType 在允许集合内才显示；shapeType>=3（点，非严格
    枚举，实测 3/4/5 均表现为点，见 schema 注释）恒豁免——用户实机测试确认(2026-07-30) Point
    不套用任何过滤规则，全部字段照常显示。"""
    allowed_set = set(allowed)
    return lambda v: v in allowed_set or v >= 3


FIELD_VISIBILITY = {
    # VELOCITY3D：velocityType=0(Direction) 用 axis+rotation 定方向；=1(Normal) 用 offset+size。
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
        # minMovementThreshold 属 velocityType=3(EmitterMotion/发射器运动)
        "minMovementThreshold": ("velocityType", _eq3),
    },
    # VELOCITY2D：offset/size 同 V3D 门控（velocityType=1）；rotation 未确认，默认显示。
    "VELOCITY2D": {
        "velocityX":   ("velocityType", _eq1),
        "velocityY":   ("velocityType", _eq1),
        "divergenceX": ("velocityType", _eq1),
        "divergenceY": ("velocityType", _eq1),
    },
    # UVCONTROL：uv2_enable 关时 uv2 子组不生效（强语义推断）；enableFlowmap 关时
    # flowmap 八件套不生效，同 RIBBON/STRAINRIBBON/LIGHTNING/BILLBOARD*/PLANE 同款开关。
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
    # TRANSFORM3D：enableVelocityBitflag bit0=启用速度、bit1=启用加速度（强语义推断）。
    "TRANSFORM3D": {
        "translation_velocity":          ("enableVelocityBitflag", _bit0),
        "rotation_velocity":             ("enableVelocityBitflag", _bit0),
        "scale_velocity":                ("enableVelocityBitflag", _bit0),
        "translation_velocity_modifier": ("enableVelocityBitflag", _bit1),
        "rotation_velocity_modifier":    ("enableVelocityBitflag", _bit1),
        "scale_velocity_modifier":       ("enableVelocityBitflag", _bit1),
    },
    # HOMING：消失模式=0(不触发)时隐藏消失半径；力场模式=0(无)时隐藏力场半径；
    # 力场速度倍率只被「内部减速(2)」「外部减速(4)」两个模式用到，其余模式隐藏
    # （用户 2026-07-30 实测：mode 1/3 下改它看不出任何变化；语料 21/21 零例外，
    #  mode 2/4 必配 <1，mode 0 的 149 条一个 <1 都没有）。
    "HOMING": {
        "vanishRadius":          ("vanishMode", _truthy),
        "forceFieldRadius":      ("forceFieldMode", _truthy),
        "forceFieldSpeedScale":  ("forceFieldMode", _in24),
    },
    # EMITTERSHAPE3D：各字段按 shapeType（0=Box/1=Sphere/2=Cylinder/>=3=Point）适用范围
    # 门控，用户实机测试确认(2026-07-30)。Point 全豁免不过滤（_shape3d 已内置）。
    # rangeXYZ/rotationCorrect/localRotation*/rotationOrder/rangeDivideVerticalNum/
    # unknBitmaskRadiusRelated/unknFlag4 全形状生效，不在此列（不门控 = 恒显示）。
    "EMITTERSHAPE3D": {
        "rangeDivideAxis":          ("shapeType", _shape3d(0)),
        "scanAngleHorizontal":      ("shapeType", _shape3d(1, 2)),
        "scanAngleVertical":        ("shapeType", _shape3d(1)),
        "rangeDivideHorizontalNum": ("shapeType", _shape3d(1, 2)),
        "radiusEnd":                ("shapeType", _shape3d(2)),
        "radiusOrigin":             ("shapeType", _shape3d(2)),
    },
    # ROTATEANIM：rotationModeMask 0/1=平面旋转系 → billboardRotation(+加速度)；
    # 2/3=自旋速度系 → spinSpeedCoef X/Y/Z；rotateDelayStart 全局生效（不门控）。
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
        # spin_velocity 只服务自旋速度系两个模式(2/3)；旋转模式在平面旋转系(0/1)时
        # 这个字段无意义，之前只挪了位置没接门控，2026-09-20 补上。
        "spin_velocity":             ("rotationModeMask", _in23),
    },
    # SPAWN：spawnFlags.bit5(UseSpawnFrame) 关闭时 spawnFrame(+Jitter) 不生效——语料
    # 交叉验证 93% 的相关性支撑这对"开关+参数"关系（见 attributes.py 的 EXTERN_SPAWN_ATTR
    # 注释）。2026-09-20 把 UseSpawnFrame 从弹窗里的一个位挪成 spawnFrame 上面单独一行
    # 勾选框（panels.py），这里补上门控让它真正起到"总开关"的作用。
    "SPAWN": {
        "spawnFrame":       ("spawnFlags", _bit5),
        "spawnFrameJitter": ("spawnFlags", _bit5),
    },
    # 2026-09-20 用户要求的批量整理：给一批已经确认是"开关+被控字段"的 Bool 字段补上
    # 可见性门控（之前这些开关字段本来就存在，只是没有把关掉的时候隐藏对应字段）。
    # colorRange 系：useColorRange 早已是 Bool，只是没接门控。
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
    # RANDOMFIX：randomSeedTable 由 tableSelectionGroup 还是 useRandomSeedTableCount 决定
    # 尚不明确，暂不门控（默认全显示）。
    # RIBBONBLADE：lengthMode 现渲成"启用自定义长度"勾选框（全语料 10084 文件仅 0/1 两值，
    # 2026-08-18 确认）。关(0)=length 生效；开(1)=maxLengthLimit+contractionSpeed 生效。
    "RIBBONBLADE": {
        "length":          ("lengthMode", _eq0),
        "maxLengthLimit":  ("lengthMode", _eq1),
        "contractionSpeed": ("lengthMode", _eq1),
    },
    # RGBFIRE / RGBWATER：每段 ColorParam 生命期时序块（Appear/Keep/Vanish + LifeType）
    # 只在对应 UseLife 打开时才生效——devlecture 面板上这几行本就紧跟在 Use*Life
    # 下面、同属一个分组；useLife 关着时 keep/vanish 语料侧也确实停在默认值上不变
    # （见 sim/behaviors/_common.py::roll_color_param）。Lighting/CorrectColorNo
    # 在面板上是独立的行（不在 Use*Life 分组内），不门控。
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
