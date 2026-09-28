# -*- coding: utf-8 -*-
"""跨属性类型共用的字段分组：组标题、组内简化标签与虚拟行。

同一组字段在多个属性类型里语义相同（例如流动贴图），面板按本表统一绘制：整组按组内
顺序挪到面板末尾，首行之前画分隔线和组标题，组内行改用去掉前缀的短标签，位掩码里的
开关拆成独立的行。组外字段的顺序仍由 `efx_format/field_order.py` 的锚点表决定。

维护约束：
- 纯数据与纯函数，不 import bpy；Blender 控件在 panels.py 里绘制。
- 组内标签只改显示文字，注释查找仍用字段原名（虚拟行用 `anno` 指定的键）。
"""


class FieldGroup(object):
    """一组跨类型共用的字段。

    header       (中文, 英文) 组标题
    types        适用的属性类型名
    order        组内字段的显示顺序；各类型字段不同时写成 类型名 → 顺序
    labels       字段名 → (中文, 英文) 组内标签
    lead         类型名 → 组首行字段名；组标题画在它之前（该字段被隐藏时也画）。
                 省略时取各类型组内顺序的第一个字段
    at_end       True：整组挪到面板末尾；False：留在原位，组员集中到第一个组员的位置
    bit_rows     类型名 → {"lead": [...], "after": {字段名: [...]}, "own": [...]}
                 lead  画在组标题之后、组首行之前的位行
                 after 画在某字段（或 value/jitter 行）之后的位行，同一列表内的位画在同一行
                 own   位掩码字段自身位置上仍保留的位行；省略时自身位置不画
    paired       (前一字段, 后一字段)：两个 Bool 画在同一行，后者在前者关闭时置灰
    """

    __slots__ = ("header", "types", "order", "labels", "lead", "bit_rows", "paired", "at_end")

    def __init__(self, header, types, order, labels=None, lead=None, bit_rows=None,
                 paired=None, at_end=True):
        self.header = header
        self.types = frozenset(types)
        self.order = (dict((t, tuple(o)) for t, o in order.items()) if isinstance(order, dict)
                      else tuple(order))
        self.labels = labels or {}
        self.lead = lead if lead is not None else dict(
            (t, self.order_for(t)[0]) for t in self.types)
        self.bit_rows = bit_rows or {}
        self.paired = paired
        self.at_end = at_end

    def order_for(self, type_name):
        return self.order.get(type_name, ()) if isinstance(self.order, dict) else self.order


_FLOW_BIT_TYPES = ("BILLBOARD3D", "PLANE", "BILLBOARD2D")
_FLOW_FIELD_TYPES = ("RIBBON", "STRAINRIBBON", "LIGHTNING", "RIBBONBLADE", "UVCONTROL")

#: 位掩码拆出的一行：(字段名, 位序号, 中文标签, 英文标签, 注释键)。
#: 注释键形如 "applicationRule.flowOnce"，登记在 annotations.py。
_AR_ENABLE = ("applicationRule", 2, "启用", "Enable", "applicationRule.enableFlowmap")
_AR_ONCE = ("applicationRule", 3, "播放一次后冻结", "Freeze After One Play",
            "applicationRule.flowOnce")
_AR_REVERSE = ("applicationRule", 4, "逆向播放", "Reverse Playback",
               "applicationRule.flowReverse")
_AR_UNKNOWN = ("applicationRule", 5, "未知位 0x20", "Unknown Bit 0x20", "applicationRule")

FLOWMAP = FieldGroup(
    header=("流动贴图", "Flowmap"),
    types=_FLOW_BIT_TYPES + _FLOW_FIELD_TYPES,
    order=("enableFlowmap", "flowmapPath",
           "flowSpeed", "flowSpeedJitter", "flowSpeedCoef", "flowSpeedCoefJitter",
           "flowStrength", "flowStrengthJitter", "flowStrengthCoef", "flowStrengthCoefJitter",
           "flowOnce", "flowReverse"),
    labels={
        "enableFlowmap":    ("启用", "Enable"),
        "flowmapPath":      ("贴图", "Texture"),
        "flowSpeed":        ("速度", "Speed"),
        "flowSpeedCoef":    ("加速度", "Acceleration"),
        "flowStrength":     ("强度", "Strength"),
        "flowStrengthCoef": ("强度加速度", "Strength Acceleration"),
        "flowOnce":         ("播放一次后冻结", "Freeze After One Play"),
        "flowReverse":      ("逆向播放", "Reverse Playback"),
    },
    lead={
        **{t: "flowmapPath" for t in _FLOW_BIT_TYPES},
        "RIBBON": "enableFlowmap",
        "STRAINRIBBON": "enableFlowmap",
        "LIGHTNING": "enableFlowmap",
        "UVCONTROL": "enableFlowmap",
        "RIBBONBLADE": "enableFlowmap",
    },
    bit_rows={
        t: {"lead": [_AR_ENABLE],
            "after": {"flowStrengthCoef": [_AR_ONCE, _AR_REVERSE]}}
        for t in _FLOW_BIT_TYPES
    },
    paired=("flowOnce", "flowReverse"),
)

_BILLBOARD_COLOR = ("correctColorNo", "color", "useColorRange", "colorRangeCorrectColorNo",
                    "colorRange", "blendMode", "brightness", "brightnessJitter")

#: 颜色：修正槽位 → 颜色 → 颜色范围 → 自发光 → 亮度。MESH 的颜色另有一套未知显示量，暂不接入。
COLOR = FieldGroup(
    header=("颜色", "Color"),
    types=("BILLBOARD3D", "BILLBOARD2D", "PLANE", "RIBBON", "STRAINRIBBON", "LIGHTNING"),
    order={
        "BILLBOARD3D": _BILLBOARD_COLOR,
        "BILLBOARD2D": _BILLBOARD_COLOR,
        "PLANE": _BILLBOARD_COLOR,
        "RIBBON": ("epvcolor_0", "color", "useColorRange", "epvcolor_1", "colorRange",
                   "blendMode", "brightness", "brightnessJitter"),
        "STRAINRIBBON": ("epv_color_slot1", "color", "useColorRange", "epv_color_slot2",
                         "colorRange", "useEmission", "emissionStrength",
                         "emissionStrengthJitter"),
        "LIGHTNING": ("color", "useColorRange", "colorRange", "blendMode", "brightness",
                      "brightnessJitter", "EPVColorSlot1", "EPVColorSlot2"),
    },
    bit_rows={t: {"after": {"brightness": [_AR_UNKNOWN]}} for t in _FLOW_BIT_TYPES},
    at_end=False,
)

_BILLBOARD_SIZE = ("scale", "scaleJitter", "width", "widthJitter", "height", "heightJitter")

#: 尺寸：整体缩放 → 逐轴尺寸
SIZE = FieldGroup(
    header=("尺寸", "Size"),
    types=("BILLBOARD3D", "BILLBOARD2D", "PLANE", "RIBBON", "STRAINRIBBON", "MESH"),
    order={
        "BILLBOARD3D": _BILLBOARD_SIZE,
        "BILLBOARD2D": _BILLBOARD_SIZE,
        "PLANE": _BILLBOARD_SIZE,
        "RIBBON": ("scale", "scale_jitter", "width", "width_jitter", "length", "length_jitter"),
        "STRAINRIBBON": ("width", "widthJitter", "length", "lengthJitter"),
        "MESH": ("global_scale", "global_scale_jitter", "scale"),
    },
    at_end=False,
)

#: 朝向：基准轴经欧拉旋转定出渲染体朝向。法线自旋（PLANE.rotation2）、MESH 追踪标志不在组内。
ORIENTATION = FieldGroup(
    header=("朝向", "Orientation"),
    types=("RIBBON", "PLANE", "MESH"),
    order={
        "RIBBON": ("faceVelocity", "fixedDirection", "lockInitialVelocity",
                   "baseAxis", "rotationOrder", "rotationX", "rotationXJitter",
                   "rotationY", "rotationYJitter", "rotationZ", "rotationZJitter",
                   "unknFlag16_0_1", "unknBool16_1", "unknBool16_2_0"),
        "PLANE": ("baseAxis", "rotationOrder", "rotation"),
        "MESH": ("baseAxis", "rotationOrder", "rotation"),
    },
    at_end=False,
)

GROUPS = (COLOR, SIZE, ORIENTATION, FLOWMAP)

#: 单一类型内的分段：类型名 → [((中文, 英文), [成员字段, ...]), ...]。只画组标题，不改标签；
#: 顺序由 efx_format/field_order.py 的锚点表决定。标题画在本段第一个实际画出的成员之前，
#: 整段都被隐藏或都落在高级区时不画。成员只需列 value 字段，配对的 Jitter 随 value 同行。
_OSC_SECTIONS = [
    (("低频", "Low Frequency"), ["lowFrequency", "lowFrequencyWidth"]),
    (("高频", "High Frequency"), ["highFrequency", "highFrequencyWidth"]),
]
#: VELOCITY3D / VELOCITY2D 共用段名；运动延迟不作用于重力，重力段放在它后面
_VEL_SPEED = ("速度", "Speed")
_VEL_DIR = ("方向", "Direction")
_VEL_DELAY = ("运动延迟", "Movement Delay")
_VEL_GRAVITY = ("重力", "Gravity")

#: RIBBONBLADE 头部/尾部 EPVColorSlot 的子字段，按显示顺序；尾部结构没有末 4 字节
_EPV_SLOT_KEYS = ("epvColorSlot", "color1", "null2", "color2", "spacer4", "unkn15", "size",
                  "unkn17", "unkn18_0", "unkn18_1", "spacer5")
_EPV_TAIL_KEYS = _EPV_SLOT_KEYS[:8]

def _emissive_sections(mask_extra, emissive_extra):
    """PLEMISSIVE / PARENTEMISSIVE 共用基类的三段；两者只有遮罩段里的字段名不同。"""
    return [
        (("自发光", "Emissive"), ["blend", "correctColorNo", "emissive", "intensity"]
         + emissive_extra),
        (("边缘光", "Rim Light"), ["rimWidth", "rimPower", "rimAlpha"]),
        (("发光遮罩", "Emit Mask"), ["emitMaskFlags", "mask0", "mask1", "addMask0", "addMask1"]
         + mask_extra),
    ]


def _lightning_branch_members(n):
    """LIGHTNING 第 n 代分支（0 = 主干）的 value 字段。"""
    return ["branch%d_%s" % (n, f) for f in (
        "size", "flags", "count", "unkn2", "unkn3",
        "lowDetailNum", "lowDetailWidth", "lowDetailWidthCoef",
        "highDetailNum", "highDetailWidth", "highDetailWidthCoef",
        "intensity", "length", "thickness",
        "headScale", "tailScale", "headAlpha", "tailAlpha")]


TYPE_SECTIONS = {
    "SPAWN": [
        (("数量", "Count"), ["maxParticles", "spawnNum"]),
        (("每轮", "Per Round"), ["loopNum", "intervalFrame", "spawnFrame"]),
        (("复活", "Revival"), ["revivalLoop", "revivalInterval"]),
        (("延迟", "Delay"), ["emitterDelayFrame", "particleDelayFrame"]),
        (("标志", "Flags"), ["spawnFlags"]),
    ],
    "LIFE": [
        (("淡入", "Appear"), ["appearFrame"]),
        (("持续", "Keep"), ["keepFrame"]),
        (("淡出", "Vanish"), ["vanishFrame"]),
        (("永生", "Indefinite"), ["indefiniteLifespan", "timeToDeath"]),
        (("其他", "Other"), ["unknFrame"]),
    ],
    "BLINK": [(("透明度范围", "Alpha Rate"), ["minAlphaRate", "maxAlphaRate"])] + _OSC_SECTIONS,
    "NOISE": list(_OSC_SECTIONS),
    "UVSEQUENCE": [
        (("UVS", "UVS"), ["uvsPath", "sequenceNo"]),
        (("动画", "Animation"), ["patternNo", "playSpeed", "playSpeedCoef",
                                 "loopingMode", "loopingOrientation"]),
    ],
    "UVCONTROL": [
        (("UV1", "UV1"), ["uv1_offset", "uv1_offsetAdd", "uv1_offsetCoef",
                          "uv1_scale", "uv1_scaleAdd", "uv1_scaleCoef"]),
        (("UV2", "UV2"), ["uv2_enable", "uv2_offset", "uv2_offsetAdd", "uv2_offsetCoef",
                          "uv2_scale", "uv2_scaleAdd", "uv2_scaleCoef"]),
    ],
    "EMITTERSHAPE3D": [
        (("形状", "Shape"), ["shapeType", "rangeXYZ"]),
        (("细分", "Subdivision"), ["rangeDivideAxis", "rangeDivideHorizontalNum",
                                   "rangeDivideVerticalNum"]),
        (("旋转", "Rotation"), ["rotationCorrect", "localRotationX", "localRotationY",
                                "localRotationZ", "rotationOrder"]),
        (("扫描范围", "Scan Range"), ["scanAngleHorizontal", "scanAngleVertical"]),
        (("半径渐变", "Radius Taper"), ["radiusOrigin", "radiusEnd"]),
        (("射线检测", "Ray Cast"), ["rayCastDependency"]),
    ],
    "LIGHTNING": [
        (("主干", "Trunk"), _lightning_branch_members(0)),
        (("第 1 代分支", "Branch Tier 1"), _lightning_branch_members(1)),
        (("第 2 代分支", "Branch Tier 2"), _lightning_branch_members(2)),
        (("末端形状", "Terminal Shape"), ["useTerminalShape", "terminal_shapeType",
                                          "terminal_rangeXYZ", "terminal_rayCastDependency",
                                          "terminal_rotationCorrect", "terminal_localRotationX",
                                          "terminal_localRotationY", "terminal_localRotationZ",
                                          "terminal_rotationOrder",
                                          "terminal_scanAngleHorizontal",
                                          "terminal_scanAngleVertical",
                                          "terminal_rangeDivideAxis",
                                          "terminal_rangeDivideHorizontalNum",
                                          "terminal_rangeDivideVerticalNum",
                                          "terminal_radiusOrigin", "terminal_radiusEnd",
                                          "terminal_unknFlag"]),
    ],
    "EMITTERSHAPE2D": [
        (("形状", "Shape"), ["shapeType", "rangeX", "rangeY"]),
        (("细分", "Subdivision"), ["rangeDivideAxis", "rangeDivideHorizontalNum"]),
    ],
    "RAYCAST": [
        (("起点与方向", "Origin and Direction"), ["direction", "startOffset", "startDistance"]),
        (("射程", "Range"), ["maxDistance", "speed"]),
        (("检测", "Detection"), ["rayCastAttr", "rayCastID", "rayCastFlags", "prop2"]),
    ],
    "HOMING": [
        (("归航运动", "Homing"), ["homingTarget", "turnRate", "acceleration", "maxSpeed"]),
        (("消失场", "Vanish Field"), ["vanishMode", "vanishRadius"]),
        (("作用场", "Effect Field"), ["forceFieldMode", "forceFieldRadius",
                                      "forceFieldSpeedScale"]),
    ],
    "ROTATEANIM": [
        (("平面旋转", "Billboard Rotation"), ["billboardRotation", "billboardRotationCoef"]),
        (("三轴自旋", "Spin"), ["spin_velocity", "spinSpeedCoefX",
                                "spinSpeedCoefY", "spinSpeedCoefZ"]),
        (("旋转延迟", "Rotation Delay"), ["rotateDelayStart"]),
    ],
    "SCALEANIM": [
        (("整体缩放", "Uniform Scale"), ["sizeScalarAdd", "sizeScalarAddCoef"]),
        (("单轴缩放", "Per-axis Scale"), ["sizeXAdd", "sizeXAddCoef", "sizeYAdd", "sizeYAddCoef",
                                         "sizeZAdd", "sizeZAddCoef"]),
        (("缩放延迟", "Scale Delay"), ["animUpdateStart"]),
    ],
    "VELOCITY3D": [
        (_VEL_SPEED, ["speed", "speedCoef", "minMovementThreshold"]),
        (_VEL_DIR, ["velocityType", "baseAxis", "rotOrder", "rotationX", "rotationY", "rotationZ",
                    "offsetX", "offsetY", "offsetZ", "sizeX", "sizeY", "sizeZ"]),
        (_VEL_DELAY, ["movementDelay"]),
        (_VEL_GRAVITY, ["gravity", "gravityDelay"]),
    ],
    "VELOCITY2D": [
        (_VEL_SPEED, ["speed", "speedCoef"]),
        (_VEL_DIR, ["velocityType", "rotation", "velocityX", "velocityY",
                    "divergenceX", "divergenceY"]),
        (_VEL_DELAY, ["movementDelay"]),
        (_VEL_GRAVITY, ["gravity", "gravityDelay"]),
    ],
    "FADEBYANGLE": [
        (("锥角", "Cone Angle"), ["coneVisibilityFlags", "cutoffConeAngle", "fadeConeAngle",
                                  "minAlpha"]),
        (("锥体朝向", "Cone Direction"), ["baseAxis", "rotOrder", "rotation"]),
    ],
    "FADEBYDEPTH": [
        (("近处淡入", "Near Fade-in"), ["nearFadeInStart", "nearFadeInEnd"]),
        (("远处淡出", "Far Fade-out"), ["farFadeOutStart", "farFadeOutEnd"]),
    ],
    "RIBBONBLADE": [
        (("形状", "Shape"), ["widthDirection", "width", "length", "interpolationCount",
                             "lengthMode", "maxLengthLimit", "contractionSpeed", "uvRepetition"]),
        (("颜色", "Color"), ["colourTransitionPoint", "emissiveStrength", "useEmissiveRange",
                             "emissiveStrengthRange"]),
        (("头部", "Head"), ["head." + _k for _k in _EPV_SLOT_KEYS]),
        (("尾部", "Tail"), ["tailEnd." + _k for _k in _EPV_TAIL_KEYS] + ["tailUnkn18_0"]),
    ],
    "RANDOMFIX": [
        (("种子表", "Seed Tables"), ["tableSelectionGroup"]
         + ["randomSeedTable%d" % k for k in range(8)]),
    ],
    "RIBBON": [
        (("UV", "UV"), ["uvScaleMode", "uvScaleLength", "uvScaleWidth"]),
        (("细分", "Subdivision"), ["subdivisionCount", "useTrailTimeScale", "trailTimeScale"]),
        (("位置与物理", "Position and Physics"), ["lengthwise_offset_relative_to_camera",
                                                  "spawnAnchorOffset", "restoreStrength",
                                                  "inertia", "springiness", "unkn21",
                                                  "unkn22_0"]),
        (("拉伸", "Stretch"), ["stretchFromSpawn", "spacer5", "stretchMaxLength",
                               "stretchResetDistance"]),
        (("光照", "Lighting"), ["lightGroup", "unknFlag22_2"]),
        (("首尾渐变", "Base and Tip Fade"), ["unknBool7", "spacer7", "base_width_multiplier", "base_opacity",
                                            "tip_width_multiplier", "tip_opacity",
                                            "enableFadeLength", "spacer8", "base_fade_length",
                                            "tip_fade_length"]),
        (("摆动", "Flap"), ["enableFlap", "spacer9", "flap1Frequency", "flap1Amount", "flap2Frequency",
                            "flap2Amount"]),
        (("重力", "Gravity"), ["enableGravity", "gravityLocalSpace", "spacer28", "gravityX", "gravityY",
                               "gravityZ"]),
    ],
    "STRAINRIBBON": [
        (("端点", "Endpoints"), ["startPosition", "unknFixed03_06", "endPosition",
                                 "unknFixed03_10"]),
        (("首尾", "Start and End"), ["startWidth", "startOpacity", "endWidth", "endOpacity"]),
        (("细分与 UV", "Subdivision and UV"), ["subdivisionCount", "unknFixed04_01",
                                               "uvRepetition",
                                               "widthwiseUVScalingAlpha", "spacer04",
                                               "widthwiseUVScalingBML"]),
        (("端点散布与释放", "Endpoint Scatter and Release"), ["endPointScatter",
                                                              "originReleaseFlag"]),
        (("断裂", "Break"), ["lengthBreakpoint", "breakpointLocation", "breakDelay"]),
        (("物理", "Physics"), ["tension", "unkn06_17", "unkn06_18", "gravityMultiplier",
                               "inertia", "poseSnapping", "endBoneID",
                               "positionalAberration_01", "positionalAberration_02",
                               "positionalAberration_05"]),
        (("位移", "Displacement"), ["displacement", "displacementToggle"]),
    ],
    "PTCOLLISION": [
        (("物理模式", "Physics Mode"), ["physicsEnum", "unkn02", "unkn03", "unknEnum04"]),
        (("投影", "Projection"), ["projectionOffset", "projectionDist"]),
        (("反弹", "Bounce"), ["bounceElasticity", "bounceElasticityMultiplier",
                              "horizontalBounce", "bounceCount"]),
        (("撞击触发", "Impact Trigger"), ["impactPlayTriggerMode", "impactPlayTriggerCount",
                                          "ieIndex", "unknEnum6_0", "unknEnum6_1"]),
    ],
    "MESH": [
        (("选项", "Options"), ["unknEnum7_0", "unknFlag7_1", "tracking_flags", "affectedByLight",
                               "shadowCastBitflag", "epv_color_slot1", "unknEnum5",
                               "epv_color_slot2", "unknFixed6_1"]),
        (("颜色开关", "Color Switches"), ["enableIntensity1", "enableIntensity2",
                                          "enableEmissiveIntensity", "disableAllColorRange",
                                          "unknFlag_cm2_3"]),
        (("未知开关", "Unknown Switches"), ["unknBool%d" % k for k in range(6)] + ["BeginMod3"]),
    ],
    "PLEMISSIVE": _emissive_sections(["enableUseEmitMask", "unknFixed5_0", "unknFixed5_3",
                                      "unknFixed5_4"], ["NULL"])
    + [(("光圈部位", "Aura Parts"), ["body_p", "wp_p"])],
    "PARENTEMISSIVE": _emissive_sections(["unkn7_2", "unknFixed8_0", "unknFixed8_3",
                                          "unknFixed8_4"], []),
}


def groups_for(type_name):
    """该类型适用的分组。"""
    return [g for g in GROUPS if type_name in g.types]


def arrange_groups(type_name, items):
    """按分组重排 items（带 ori_name 的对象列表）：组内按组内顺序排列；at_end 的组整组挪到
    末尾，其余留在第一个组员原来的位置。"""
    for g in groups_for(type_name):
        rank = dict((name, k) for k, name in enumerate(g.order_for(type_name)))
        grp = [it for it in items if it.ori_name in rank]
        if not grp:
            continue
        grp.sort(key=lambda it: rank[it.ori_name])
        rest = [it for it in items if it.ori_name not in rank]
        if g.at_end:
            items = rest + grp
        else:
            first = next(k for k, it in enumerate(items) if it.ori_name in rank)
            pos = sum(1 for it in items[:first] if it.ori_name not in rank)
            items = rest[:pos] + grp + rest[pos:]
    return items


def is_grouped(type_name, field_name):
    """字段是否属于某个跨类型分组或类型内分段。"""
    if section_of(type_name, field_name) is not None:
        return True
    return any(field_name in g.order_for(type_name) for g in groups_for(type_name))


def section_of(type_name, field_name):
    """字段所在分段的序号；不属于任何分段返回 None。"""
    for k, (_header, members) in enumerate(TYPE_SECTIONS.get(type_name, ())):
        if field_name in members:
            return k
    return None


def section_header(type_name, index):
    """分段标题 (中文, 英文)。"""
    return TYPE_SECTIONS[type_name][index][0]


def row_label(type_name, field_name, zh):
    """组内标签；不属于任何组返回 None。"""
    for g in GROUPS:
        if type_name in g.types:
            lbl = g.labels.get(field_name)
            if lbl:
                return lbl[0] if zh else lbl[1]
    return None


def group_led_by(type_name, field_name):
    """以该字段为首行的分组；没有返回 None。"""
    for g in GROUPS:
        if type_name in g.types and g.lead.get(type_name) == field_name:
            return g
    return None


def lead_bit_rows(group, type_name):
    return group.bit_rows.get(type_name, {}).get("lead", [])


def bit_rows_after(type_name, field_name):
    """画在该字段之后的位行（同一列表画成一行）。"""
    for g in GROUPS:
        if type_name in g.types:
            rows = g.bit_rows.get(type_name, {}).get("after", {}).get(field_name)
            if rows:
                return rows
    return []


def own_bit_rows(type_name, field_name):
    """位掩码字段自身位置上保留的位行（可为空列表）；该字段不由分组接管时返回 None。"""
    for g in GROUPS:
        if type_name in g.types:
            spec = g.bit_rows.get(type_name)
            if not spec:
                continue
            rows = list(spec.get("lead", [])) + list(spec.get("own", []))
            for after in spec.get("after", {}).values():
                rows += after
            if any(r[0] == field_name for r in rows):
                return spec.get("own", [])
    return None


def paired_partner(type_name, field_name):
    """(前一字段, 后一字段)：field_name 是前一字段时返回该对，否则 None。"""
    for g in GROUPS:
        if type_name in g.types and g.paired and g.paired[0] == field_name:
            return g.paired
    return None


def is_paired_follower(type_name, field_name):
    return any(type_name in g.types and g.paired and g.paired[1] == field_name
               for g in GROUPS)
