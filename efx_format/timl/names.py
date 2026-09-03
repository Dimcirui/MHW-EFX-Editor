"""
efx_format/timl_names.py  —  TIML hash → 可读名 + game↔Blender 坐标换算

TIML 通道名由两段 hash 组成：
  - timelineParameterHash：这条动画**影响哪个对象/块**（Transform3D / RgbFire / TypeRibbon…）。
    来源：Ezekial711 MHW Modding wiki + DTI dump（refs/dti_effect_fields.json）逐一验证。
    hash 公式（语料反推 + DTI 28 条全验证）：
        jamcrc("nEffect::nTimelineParam::<DTI短名>") & 0x7FFFFFFF
    未知 hash（15 条，语料出现但 DTI dump 缺项）保留十六进制，部分有共现推断注释。
  - datatypeHash：动画的**哪个属性**（pos:X / rot:Z / 颜色…）。wiki 未列；transform 九条来自
    hash（jamcrc）。未知 hash 回退十六进制。

供 timl 通道编辑/预览的友好命名与（后续）transform3d → 真实属性映射使用。
"""

# ── timelineParameterHash → 名称 ──────────────────────────────────────────────
# hash 公式：jamcrc("nEffect::nTimelineParam::<DTI短名>") & 0x7FFFFFFF
# 已验证：
TLP_NAMES = {
    # ── 已确认 ──
    0x65004e2a: "MhEffectDecalBehavior",
    0x6da6e5d1: "MhPointLightBehavior",
    0x75963575: "MhSpotLightBehavior",
    0x540a2572: "Transform2D",
    0x4d111433: "Transform3D",
    0x2bda85f5: "Velocity2D",
    0x32c1b4b4: "Velocity3D",
    0x2b61b0ed: "Billboard2D",
    0x327a81ac: "Billboard3D",
    0x3481666b: "Plane",
    0x538af627: "Mesh",
    0x1436e592: "Ribbon",
    0x1f09850e: "StrainRibbon",
    0x5ac7fc29: "UVSequence",
    0x563c8065: "RotateAnim",
    0x2a62f92e: "ScaleAnim",
    0x2a0363d4: "EmitterShape2D",
    0x33185295: "EmitterShape3D",
    0x4a0d2b6a: "Life",
    0x60ba9117: "RgbFire",
    0x2101c529: "RgbWater",
    0x39c68fb4: "TubeLight",
    0x42e48dde: "PointLightBehavior",
    0x582ba062: "RadialBlurFilterBehavior",
    0x2ed89bcc: "ParentMaterial",
    # ── 已确认（但实际未见）──
    0x4cdb308a: "Item",
    0x3f2b8294: "EffectEvent",
    0x06e8d4c3: "DecalBehavior",
    0x0235f20e: "LightBehavior",
    0x3de576dc: "SpotLightBehavior",
    0x2c154dca: "FilterBehavior",
    0x13a0f54f: "TonemapFilter",
    0x096cabc4: "ColorCorrectFilter",
    # ── 未知（语料出现，但不清楚名称；括号为共现推断，低置信度）──
    0x399db6a9: "0x399DB6A9",        # 384次，无强信号
    0x598272e1: "0x598272E1",        # 278次，PARENTEMISSIVE/PLEMISSIVE 共现(3.5x)
    0x66c62149: "0x66C62149",        # 76次，无强信号
    0x5e8d9ee9: "0x5E8D9EE9",        # 72次，EMITTERSHAPEMESH 共现(8.1x)
    0x2c78b827: "0x2C78B827",        # 66次，无强信号
    0x4e64d91c: "0x4E64D91C",        # 59次，PLANE 共现(1.4x)
    0x09c466dc: "0x09C466DC",        # 59次，PTCOLLISION 共现(2.1x)
    0x5752ed69: "0x5752ED69",        # 51次，无强信号
    0x0b8924da: "0x0B8924DA",        # 43次，PTTRIGGER 共现(6.9x)
    0x70c7b1f1: "0x70C7B1F1",        # 12次，无强信号
    0x3e880466: "0x3E880466",        # 9次，无强信号
    0x17359e0c: "0x17359E0C",        # 6次，UVCONTROL 共现(1.2x)
    0x465acf70: "0x465ACF70",        # 3次，无强信号
    0x7e51f5bd: "0x7E51F5BD",        # 2次，EMITTERBOUNDARY 共现(2.9x)
    0x0fe12549: "0x0FE12549",        # 1次，EXTERNREFERENCE 共现(1.8x)
}

import math

from ..hashes import jamcrc

# ── datatypeHash → 显示名（DT_NAMES）─────────────────────────────────────────────────
# 来源：refs/dti_effect_fields.json 字段 hash 直接对比语料 datatypeHash，83/130 命中。
# 未命中的 47 条由 datatype_name() 回退到 0x 十六进制。
# 注：同名 DT_TRANSFORM 条目优先（transform 九条有 Blender 属性映射，DT_NAMES 只做展示）。
DT_NAMES = {
    # ── Color / 颜色属性 ──────────────────────────────────────────
    0x58689812: "Color",                   # cnt=1645 Color[RGBA]      TLP:Billboard3D,Ribbon
    0x5A8C6820: "SmokeColor",              # cnt=122  Color[RGBA]      TLP:RgbFire
    0x39A1E557: "FireColor",               # cnt=87   Color[RGBA]      TLP:RgbFire
    0xCBDB6622: "EmissiveMapFactorColor",  # cnt=228  Color[RGBA]      TLP:MhEffectDecalBehavior
    0xAFE95AC0: "ColorBase",              # cnt=157  Color[RGBA]      TLP:unknown
    0x26BD5CC2: "BlendFactor",             # cnt=20   Color[RGBA]      TLP:MhEffectDecalBehavior
    0xFA79B1CD: "Emissive",               # cnt=7    Color[RGBA]      TLP:0x598272E1
    0x608DCF8D: "EmissiveColor",          # cnt=13   Color[RGBA]      TLP:Mesh
    0x3BA67E7C: "HeadColor",              # cnt=1    Color[RGBA]      TLP:TubeLight
    0x2AA40DE9: "TailColor",              # cnt=1    Color[RGBA]      TLP:TubeLight
    0xC216C23D: "ColorRange",             # cnt=1    Color[RGBA]      TLP:Billboard3D
    0x60D69856: "ColorSpecular",          # cnt=1    Color[RGBA]      TLP:RgbWater
    0x0FF5554F: "mDistortionFactor",      # cnt=1    Color[RGBA]      TLP:0x3E880466
    0xA01B7821: "mEmissiveMapFactor",     # cnt=11   Color[RGBA]      TLP:0x09C466DC
    # ── Float / 数值属性 ──────────────────────────────────────────
    0x9F1E012E: "ColorRate",              # cnt=1303 Float            TLP:Ribbon,RgbFire
    # 0xAFE95AC0 未命中（cnt=157, 归属未知 TLP）——留回退
    0x94BCC5CE: "Intensity",             # cnt=701  Float            TLP:0x598272E1,MhPointLightBehavior
    0x7D235C30: "EmissiveMapFactorIntensity",  # cnt=296 Float       TLP:MhEffectDecalBehavior
    0x531B9E44: "SizeY",                 # cnt=241  Float            TLP:Billboard3D,Mesh
    0x0EBAEC37: "SizeScalar",            # cnt=150  Float            TLP:Ribbon,Billboard3D
    0x1383E9BA: "RangeMaxY",             # cnt=141  Float            TLP:EmitterShape3D
    0x8A8AB800: "RangeMaxZ",             # cnt=125  Float            TLP:EmitterShape3D
    0x6484D92C: "RangeMaxX",             # cnt=124  Float            TLP:EmitterShape3D
    0x18C577DE: "EmissiveColorRate",     # cnt=114  Float            TLP:Mesh
    0x98015C6F: "RangeMinZ",             # cnt=113  Float            TLP:EmitterShape3D
    0x760F3D43: "RangeMinX",             # cnt=112  Float            TLP:EmitterShape3D
    0x3775827A: "RangeY",               # cnt=100  Float            TLP:MhEffectDecalBehavior
    0x4072B2EC: "RangeX",               # cnt=99   Float            TLP:MhEffectDecalBehavior
    0x01080DD5: "RangeMinY",             # cnt=96   Float            TLP:EmitterShape3D
    0x435F3054: "EffectiveRadius",       # cnt=92   Float            TLP:PointLightBehavior
    0xE5C92264: "PlaySpeed",             # cnt=91   Float            TLP:UVSequence
    0x31182E0D: "Speed",                # cnt=85   Float            TLP:Velocity2D,Velocity3D
    0xC32F9493: "Radius",               # cnt=75   Float            TLP:PointLightBehavior
    0x241CAED2: "SizeX",                # cnt=69   Float            TLP:Mesh,Billboard3D
    0xBF160652: "AlphaCorrectionMin",    # cnt=68   Float            TLP:MhEffectDecalBehavior
    0x371BBC04: "mRoughness",            # cnt=54   Float            TLP:0x09C466DC
    0xF0DF339B: "WidthSize",            # cnt=54   Float            TLP:Ribbon,StrainRibbon
    0xA7EDA21C: "WaterLerpGtoB",        # cnt=50   Float            TLP:RgbWater
    0x002FF505: "RotationX",            # cnt=40   Float            TLP:Mesh
    0xCA12CFFE: "SizeZ",                # cnt=38   Float            TLP:Mesh
    0xEE219429: "RotationZ",            # cnt=36   Float            TLP:Mesh
    0xC24DF97C: "SizeScalarAdd",        # cnt=35   Float            TLP:ScaleAnim
    0x6A5FE3C4: "Gravity",              # cnt=34   Float            TLP:Velocity3D
    0xF92E647B: "Length",               # cnt=32   Float            TLP:Ribbon,StrainRibbon
    0xC207B8B4: "mFlowStrength",        # cnt=27   Float            TLP:0x5E8D9EE9
    0x2822A722: "SizeYAdd",             # cnt=22   Float            TLP:ScaleAnim
    0xE81961E4: "RotationAdd",          # cnt=21   Float            TLP:RotateAnim
    0x1D95BB54: "BlurWidth",            # cnt=19   Float            TLP:RadialBlurFilterBehavior
    0x909EC047: "SizeXAdd",             # cnt=18   Float            TLP:ScaleAnim
    0x1BB0EB80: "mEmissiveMapFactorIntensity",  # cnt=18 Float      TLP:0x09C466DC
    0x316D89C5: "CoreThickness",        # cnt=17   Float            TLP:TubeLight
    0x7728C593: "RotationY",            # cnt=16   Float            TLP:Mesh
    0x085BC9D5: "LightIntensity",       # cnt=16   Float            TLP:TubeLight
    0xC23FE6C6: "RotationAddX",         # cnt=12   Float            TLP:RotateAnim
    0xAB9D6334: "ColorIntensity",       # cnt=11   Float            TLP:RadialBlurFilterBehavior
    0xB538D650: "RotationAddY",         # cnt=9    Float            TLP:RotateAnim
    0x2C3187EA: "RotationAddZ",         # cnt=7    Float            TLP:RotateAnim
    0xB6C0BDF8: "CoreIntensity",        # cnt=7    Float            TLP:TubeLight
    0x8A565263: "TerminatePositionZ",   # cnt=6    Float            TLP:StrainRibbon
    0x0718D2B3: "LocalRotationY",       # cnt=6    Float            TLP:StrainRibbon
    0x6458334F: "TerminatePositionX",   # cnt=6    Float            TLP:StrainRibbon
    0x135F03D9: "TerminatePositionY",   # cnt=6    Float            TLP:StrainRibbon
    0x33A4A86B: "PlaySpeedCoef",        # cnt=5    Float            TLP:UVSequence
    0x0ECBFA29: "BrightThreshold",      # cnt=4    Float            TLP:RadialBlurFilterBehavior
    0x3A9708CC: "SizeZAdd",             # cnt=4    Float            TLP:ScaleAnim
    0x4E00491F: "IntensitySheet",       # cnt=4    Float            TLP:RgbWater
    0x0EF6ABF4: "BlurStart",            # cnt=3    Float            TLP:RadialBlurFilterBehavior
    0x4279F094: "mMaxIntensityRate",    # cnt=2    Float            TLP:0x7E51F5BD
    0x9E118309: "LocalRotationZ",       # cnt=2    Float            TLP:EmitterShape3D
    0x13804BC9: "mMinIntensityRate",    # cnt=2    Float            TLP:0x7E51F5BD
    0x4D41A06B: "NormalBlendRate",      # cnt=1    Float            TLP:MhEffectDecalBehavior
    0x71BCF0AA: "mFlowSpeed",           # cnt=1    Float            TLP:0x399DB6A9
    0x831B390B: "AlphaCorrectionMax",   # cnt=1    Float            TLP:MhEffectDecalBehavior
    0x16814F1C: "Roughness",            # cnt=1    Float            TLP:MhEffectDecalBehavior
    0x2FF50558: "Rotation",             # cnt=1    Float            TLP:Billboard3D
    0xAE7CD3C0: "RangeZ",              # cnt=1    Float            TLP:MhEffectDecalBehavior
    # ── 以下 102 条来自 RE DTI dump 的 nTimelineParam 类，**全语料 0 例**（官方一次没用过）。
    # hash 由 dump 直接给出，不是反查/合成。类型只取 f32/color 两种——它们与 TIML
    # dataType 的对应已被语料标定（f32→2 n=5647 / color→3 n=2106）；u32/bool/vector2 等
    # 没有任何语料样本可标定 dataType，写错会产出垃圾关键帧，故一律跳过（44 条）。
    0x086567E1: "InitialPositionZ",          # cnt=0    Float
    0x0E24B8A2: "mMultiplyRadiusSquare",     # cnt=0    Float
    0x102FFF8B: "HeadEffectiveRadius",       # cnt=0    Float
    0x1204171A: "OcclusionSphereRadius",     # cnt=0    Float
    0x19DCE197: "IntensityAlpha",            # cnt=0    Float
    0x275F8C25: "UVRangeZ",                  # cnt=0    Float
    0x28342187: "ToneCurveBy4",              # cnt=0    Float
    0x29922775: "ToneCurveGy0",              # cnt=0    Float
    0x2A6477AF: "ToneCurveRx0",              # cnt=0    Float
    0x2AD90E22: "ShadowDepthBias",           # cnt=0    Float
    0x2B0CF983: "CenterW",                   # cnt=0    Float
    0x2D09B3B6: "ToneCurveRx4",              # cnt=0    Float
    0x2EFFE36C: "ToneCurveGy4",              # cnt=0    Float
    0x2F59E59E: "ToneCurveBy0",              # cnt=0    Float
    0x2FCE3B02: "StartH",                    # cnt=0    Float
    0x30891634: "ToneCurveGx0",              # cnt=0    Float
    0x312F10C6: "ToneCurveBx4",              # cnt=0    Float
    0x337F46EE: "ToneCurveRy0",              # cnt=0    Float
    0x341282F7: "ToneCurveRy4",              # cnt=0    Float
    0x34B93272: "VignettingOffset",          # cnt=0    Float
    0x353D6FFC: "Fresnel",                   # cnt=0    Float
    0x3642D4DF: "ToneCurveBx0",              # cnt=0    Float
    0x37E4D22D: "ToneCurveGx4",              # cnt=0    Float
    0x40E3E2BB: "ToneCurveGx5",              # cnt=0    Float
    0x4145E449: "ToneCurveBx1",              # cnt=0    Float
    0x4315B261: "ToneCurveRy5",              # cnt=0    Float
    0x44787678: "ToneCurveRy1",              # cnt=0    Float
    0x46282050: "ToneCurveBx5",              # cnt=0    Float
    0x478E26A2: "ToneCurveGx1",              # cnt=0    Float
    0x49AE09C7: "EndH",                      # cnt=0    Float
    0x55BD853E: "CenterZ",                   # cnt=0    Float
    0x585ED508: "ToneCurveBy1",              # cnt=0    Float
    0x59EEF098: "UVRangeW",                  # cnt=0    Float
    0x59F8D3FA: "ToneCurveGy5",              # cnt=0    Float
    0x5A0E8320: "ToneCurveRx5",              # cnt=0    Float
    0x5D634739: "ToneCurveRx1",              # cnt=0    Float
    0x5E9517E3: "ToneCurveGy1",              # cnt=0    Float
    0x5F331111: "ToneCurveBy5",              # cnt=0    Float
    0x6ACAAAD7: "CoreLength",                # cnt=0    Float
    0x701FE225: "LocalRotationX",            # cnt=0    Float
    0x7516AA5D: "LocalRotation",             # cnt=0    Float
    0x7AF2755D: "ProjectionRotationZ",       # cnt=0    Float
    0x7D0FD331: "TailEffectiveRadius",       # cnt=0    Float
    0x7E6555E0: "FrameInfluence",            # cnt=0    Float
    0x7F2CEB57: "EmissiveColorRange",        # cnt=0    Color[RGBA]
    0x7F2FEA9B: "Falloff",                   # cnt=0    Float
    0x84E65AB1: "Spread",                    # cnt=0    Float
    0x916C365B: "InitialPositionY",          # cnt=0    Float
    0x931E7E65: "TextureScrollSpeed",        # cnt=0    Float
    0x93A7FACA: "VignettingPow",             # cnt=0    Float
    0x994333F2: "VertexInfluence",           # cnt=0    Float
    0x9DB8917C: "Acceleration",              # cnt=0    Float
    0xA2C636F7: "StartW",                    # cnt=0    Float
    0xA826417C: "ToneCurveBx7",              # cnt=0    Float
    0xA980478E: "ToneCurveGx3",              # cnt=0    Float
    0xAA2229C3: "LimitAngle",                # cnt=0    Float
    0xAA761754: "ToneCurveRy3",              # cnt=0    Float
    0xAD1BD34D: "ToneCurveRy7",              # cnt=0    Float
    0xAEED8397: "ToneCurveGx7",              # cnt=0    Float
    0xAF4B8565: "ToneCurveBx3",              # cnt=0    Float
    0xAFB51DF4: "IntensityCubeMap",          # cnt=0    Float
    0xB09B76CF: "ToneCurveGy3",              # cnt=0    Float
    0xB13D703D: "ToneCurveBy7",              # cnt=0    Float
    0xB1F7AEF0: "Metalic",                   # cnt=0    Float
    0xB36D2615: "ToneCurveRx3",              # cnt=0    Float
    0xB400E20C: "ToneCurveRx7",              # cnt=0    Float
    0xB650B424: "ToneCurveBy3",              # cnt=0    Float
    0xB78EE6DA: "BlendRate",                 # cnt=0    Float
    0xB7F6B2D6: "ToneCurveGy7",              # cnt=0    Float
    0xBA17788F: "EndZ",                      # cnt=0    Float
    0xBBB3E412: "CenterX",                   # cnt=0    Float
    0xBE56DD9F: "UVRangeY",                  # cnt=0    Float
    0xC0F18240: "ToneCurveGy6",              # cnt=0    Float
    0xC126B7BD: "MinRoughness",              # cnt=0    Float
    0xC15784B2: "ToneCurveBy2",              # cnt=0    Float
    0xC307D29A: "ToneCurveRx6",              # cnt=0    Float
    0xC46A1683: "ToneCurveRx2",              # cnt=0    Float
    0xC4A60432: "EndW",                      # cnt=0    Float
    0xC63A40AB: "ToneCurveBy6",              # cnt=0    Float
    0xC79C4659: "ToneCurveGy2",              # cnt=0    Float
    0xC893EE17: "OcclusionBlurWidthScale",   # cnt=0    Float
    0xC951ED09: "UVRangeX",                  # cnt=0    Float
    0xCCB4D484: "CenterY",                   # cnt=0    Float
    0xCDBCBB7E: "EmissionColorRange",        # cnt=0    Color[RGBA]
    0xCF5D2EDD: "ShadowSlopedDepthBias",     # cnt=0    Float
    0xD23788D3: "Cone",                      # cnt=0    Float
    0xD62C2891: "IntensitySpecular",         # cnt=0    Float
    0xD6AD0996: "ColorSheet",                # cnt=0    Color[RGBA]
    0xD84CB5F3: "ToneCurveBx2",              # cnt=0    Float
    0xD9EAB301: "ToneCurveGx6",              # cnt=0    Float
    0xDA1CE3DB: "ToneCurveRy6",              # cnt=0    Float
    0xDC774A4A: "StartZ",                    # cnt=0    Float
    0xDD7127C2: "ToneCurveRy2",              # cnt=0    Float
    0xDE877718: "ToneCurveGx2",              # cnt=0    Float
    0xDF2171EA: "ToneCurveBx6",              # cnt=0    Float
    0xE22A3268: "OcclusionBlurWidthOffset",  # cnt=0    Float
    0xE2C6589E: "rot",                       # cnt=0    Float
    0xE609DBFA: "ShadowMaxDepthBias",        # cnt=0    Float
    0xE66B06CD: "InitialPositionX",          # cnt=0    Float
    0xE7DF422D: "NearClipDistance",          # cnt=0    Float
    0xEEBD5618: "EmissionRate",              # cnt=0    Float
    0xF80CE653: "EmissionColor",             # cnt=0    Color[RGBA]
}

# transform 九条 hash（jamcrc）。MHW Y-up → Blender Z-up：游戏 Y↔Z 轴**置换**
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

# ── DT_NEUTRAL：新增 TIML 轨道的首帧兜底值 ────────────────────────────────────────
# 新增一条轨道时首帧应当是**中性值**——加轨道本身不改变特效当下的外观，之后由用户
# 编关键帧。dataclass 式的全 0 默认在乘算类属性上是错的：亮度/强度/缩放系数填 0
# 等于让特效直接消失，根本不能作为编辑起点。
#
# ⚠ 不要用"语料里这个 DT 的首帧值分布"来定这张表——会被 TIML 轨道做动画的字段，
#   恰恰是那些要动的字段，其首帧是别人动画的起点而非中性值（SizeY 语料首帧最常见
#   130.0 就是这么来的）。选择偏差，测的是错的总体。
#
# 优先级：add_transform 的 seed 参数（调用方从该属性当前静态字段值取，见
#   blender_efx/timl_tracks.py::_field_seed_values）> 本表 > 0.0。
# Color（data_type==3）不走本表，恒 255,255,255,255（白色不透明）。
DT_NEUTRAL = {
    # ── 纯乘算系数 / 比率：1.0 就是语义上的恒等值 ──────────────────────────
    0x9F1E012E: 1.0,   # ColorRate
    0x18C577DE: 1.0,   # EmissiveColorRate
    0x94BCC5CE: 1.0,   # Intensity
    0x7D235C30: 1.0,   # EmissiveMapFactorIntensity
    0x1BB0EB80: 1.0,   # mEmissiveMapFactorIntensity
    0xAB9D6334: 1.0,   # ColorIntensity
    0xB6C0BDF8: 1.0,   # CoreIntensity
    0x085BC9D5: 1.0,   # LightIntensity
    0x4E00491F: 1.0,   # IntensitySheet
    0x4279F094: 1.0,   # mMaxIntensityRate
    0x13804BC9: 1.0,   # mMinIntensityRate
    0x4D41A06B: 1.0,   # NormalBlendRate
    0x0EBAEC37: 1.0,   # SizeScalar
    0x9486DF23: 1.0,   # scl:X
    0xE381EFB5: 1.0,   # scl:Y
    0x7A88BE0F: 1.0,   # scl:Z
    0xE5C92264: 1.0,   # PlaySpeed
    0x33A4A86B: 1.0,   # PlaySpeedCoef
    0x831B390B: 1.0,   # AlphaCorrectionMax（配对的 Min 中性值是 0.0，不入表）
    # ── 绝对量级（游戏单位下的实际尺寸/半径/速度）───────────────────────────
    # 这些字段没有"恒等值"——真实特效里 SizeY≈130、Radius≈350、EffectiveRadius≈1000，
    # 1.0 只是"1 个单位"，视觉上几乎看不见。正常路径由 seed 从属性当前字段值取到
    # 正确量级；这里给 1.0 仅作调色板按钮（只给 raw hash、拿不到字段）的兜底，
    # 取非 0 是为了不让特效直接消失。
    0x241CAED2: 1.0,   # SizeX
    0x531B9E44: 1.0,   # SizeY
    0xCA12CFFE: 1.0,   # SizeZ
    0xF0DF339B: 1.0,   # WidthSize
    0xF92E647B: 1.0,   # Length
    0x316D89C5: 1.0,   # CoreThickness
    0xC32F9493: 1.0,   # Radius
    0x435F3054: 1.0,   # EffectiveRadius
    # 未列出的一律 0.0：加法偏移（*Add）、位置（pos:*）、角度（rot:*/Rotation*）、
    # Gravity/Speed/Blur*/AlphaCorrectionMin/Roughness 等，以及 45 条未具名 hex DT
    # ——没有语义依据，猜不如不猜。
}


def dt_neutral_value(h: int) -> float:
    """新增轨道首帧的兜底中性值（无 seed 时用）。未收录的 DT → 0.0。"""
    return DT_NEUTRAL.get(h & 0xFFFFFFFF, 0.0)


# game↔Blender 数值换算（MHW Y-up↔Blender Z-up 标准换算，互为精确逆）。
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


# ── PTBEHAVIOR：TLP / DT 运行时计算（不需要静态映射表）────────────────────────────
# 语料实证（2026-08）：MhEffectDecalBehavior / MhPointLightBehavior /
# MhSpotLightBehavior / PointLightBehavior / RadialBlurFilterBehavior 这五个 TLP
# 与 PTBEHAVIOR 100% 共现（lift 15.5x）——它们不是独立的属性块，而是 PTBEHAVIOR
# 的**类型变体**：PTBEHAVIOR 的 b_type 字段直接存 DTI 类名字符串
# （"nEffect::PointLightBehavior" 或裸 "MhPointLightBehavior"）。
#
# 两条哈希规则都已在语料上验证，因此这一整类不需要枚举映射表：
#   TLP = jamcrc("nEffect::nTimelineParam::<b_type 短名>") & 0x7FFFFFFF
#   DT  = jamcrc(<参数名去掉前导 m>)   —— PTBEHAVIOR 的参数 key 是 jamcrc("mFoo")，
#         而 TIML 的 datatypeHash 是 jamcrc("Foo")，同一命名空间、差一个 m 前缀。
#         18/18 抽样命中（mIntensity→Intensity、mEmissiveMapFactorIntensity→…等）。

def _short_class(b_type: str) -> str:
    """b_type 字符串 → DTI 短类名（去掉 nEffect:: 之类的命名空间前缀和尾部 NUL）。"""
    s = (b_type or "").split("\x00")[0].strip()
    return s.split("::")[-1]


def ptbehavior_tlp_candidates(b_type: str) -> list:
    """b_type → 候选 TLP hash 列表（按优先级）。

    首选自身类名推出的 TLP；若是 Mh* 子类，再追加去掉 Mh 的基类 TLP —— 实测
    b_type=MhPointLightBehavior 的 PTBEHAVIOR 会二选一地把轨道挂在
    MhPointLightBehavior(327 entry) 或基类 PointLightBehavior(222 entry) 下，
    从不并存。调用方应优先复用该 TIML 里已存在的那个，避免同一属性被拆到两个 TLP。
    """
    short = _short_class(b_type)
    if not short:
        return []
    out = [jamcrc(("nEffect::nTimelineParam::" + short).encode()) & 0x7FFFFFFF]
    if short.startswith("Mh") and len(short) > 2:
        base = short[2:]
        h = jamcrc(("nEffect::nTimelineParam::" + base).encode()) & 0x7FFFFFFF
        if h not in out:
            out.append(h)
    return out


def ptbehavior_param_dt(param_name: str):
    """PTBEHAVIOR 参数名（如 'mIntensity'）→ TIML datatypeHash；名字未知则 None。

    未知名在 UI 里是 '0x%08X' 形式（PTBEHAVIOR_NAMES 没收录），此时算不出 DT——
    真名未知就没法去 m 前缀，返回 None 让调用方不显示 +TIML 按钮。
    """
    s = (param_name or "").strip()
    if not s or s.startswith("0x"):
        return None
    bare = s[1:] if (len(s) > 1 and s[0] == "m" and s[1].isupper()) else s
    return jamcrc(bare.encode()) & 0xFFFFFFFF


def timeline_param_name(h: int) -> str:
    """timelineParameterHash → 名称，未知回退 0x 十六进制。"""
    return TLP_NAMES.get(h & 0xFFFFFFFF, "0x%08X" % (h & 0xFFFFFFFF))


def datatype_name(h: int) -> str:
    """datatypeHash → 友好属性名，未知回退 0x 十六进制。
    优先级：DT_TRANSFORM(transform 九条，含 Blender 映射) > DT_NAMES(DTI 字段名) > hex 回退。"""
    h &= 0xFFFFFFFF
    if h in DT_TRANSFORM:
        return DT_TRANSFORM[h][0]
    if h in DT_NAMES:
        return DT_NAMES[h]
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


# ── BLOCK_TO_TLP：块类型名（大写）→ timelineParameterHash ─────────────────────────
# 用于 T2 字段侧 +TIML 按钮按块类型查 TLP hash。只列已知映射（TLP 名与块类型名对应）。
BLOCK_TO_TLP = {
    "TRANSFORM3D":    0x4D111433,
    "TRANSFORM2D":    0x540A2572,
    "BILLBOARD3D":    0x327A81AC,
    "BILLBOARD2D":    0x2B61B0ED,
    "PLANE":          0x3481666B,
    "MESH":           0x538AF627,
    "RIBBON":         0x1436E592,
    "STRAINRIBBON":   0x1F09850E,
    "VELOCITY3D":     0x32C1B4B4,
    "VELOCITY2D":     0x2BDA85F5,
    "EMITTERSHAPE3D": 0x33185295,
    "EMITTERSHAPE2D": 0x2A0363D4,
    "RGBFIRE":        0x60BA9117,
    "RGBWATER":       0x2101C529,
    "SCALEANIM":      0x2A62F92E,
    "ROTATEANIM":     0x563C8065,
    "UVSEQUENCE":     0x5AC7FC29,
    "TUBELIGHT":      0x39C68FB4,
    "LIFE":           0x4A0D2B6A,
}

# ── FIELD_TO_DT：(块类型名大写, schema ori_name) → [(dt_hash, data_type), ...] ────
# 只收录"确认"级字段（FIELD_OFFICIAL_NAMES 中 "确认" 置信度的映射）。
# 向量字段按 X/Y/Z 顺序；data_type: 0=SInt 1=Int 2=Float 3=Color(RGBA) 4=Bool。
FIELD_TO_DT = {
    ("TRANSFORM3D", "translate"): [(0x8E8AFE06, 2), (0xF98DCE90, 2), (0x60849F2A, 2)],
    ("TRANSFORM3D", "rotate"):    [(0xF105BBE3, 2), (0x86028B75, 2), (0x1F0BDACF, 2)],
    ("TRANSFORM3D", "resize"):    [(0x9486DF23, 2), (0xE381EFB5, 2), (0x7A88BE0F, 2)],
    ("BILLBOARD3D", "color"):      [(0x58689812, 3)],
    ("BILLBOARD3D", "colorRange"): [(0xC216C23D, 3)],
    ("BILLBOARD3D", "rotation"):   [(0x2FF50558, 2)],
    ("BILLBOARD3D", "brightness"): [(0x9F1E012E, 2)],
    ("BILLBOARD3D", "height"):     [(0x531B9E44, 2)],
    ("BILLBOARD3D", "scale"):      [(0x0EBAEC37, 2)],
    ("BILLBOARD3D", "width"):      [(0x241CAED2, 2)],
    # Color/ColorRange/ColorRate/Rotation/SizeScalar/rotation/scale 五个哈希跟 BILLBOARD3D 完全同名同值；
    ("BILLBOARD2D", "color"):      [(0x58689812, 3)],
    ("BILLBOARD2D", "colorRange"): [(0xC216C23D, 3)],
    ("BILLBOARD2D", "brightness"): [(0x9F1E012E, 2)],
    ("BILLBOARD2D", "rotation"):   [(0x2FF50558, 2)],
    ("BILLBOARD2D", "scale"):      [(0x0EBAEC37, 2)],
    ("PLANE", "color"):           [(0x58689812, 3)],
    ("PLANE", "colorRange"):      [(0xC216C23D, 3)],
    ("PLANE", "brightness"):      [(0x9F1E012E, 2)],
    ("PLANE", "scale"):           [(0x0EBAEC37, 2)],
    ("PLANE", "height"):          [(0x531B9E44, 2)],
    ("MESH", "scale"):            [(0x241CAED2, 2), (0x531B9E44, 2), (0xCA12CFFE, 2)],
    ("MESH", "rotation"):         [(0x002FF505, 2), (0x7728C593, 2), (0xEE219429, 2)],
    ("MESH", "emissive_brightness"): [(0x18C577DE, 2)],
    ("MESH", "color"):               [(0x58689812, 3)],
    ("MESH", "colorRange"):          [(0xC216C23D, 3)],
    ("MESH", "emissiveColor"):       [(0x608DCF8D, 3)],
    ("MESH", "emissiveColorRange"):  [(0x7F2CEB57, 3)],
    ("MESH", "global_scale"):        [(0x0EBAEC37, 2)],
    ("RIBBON", "brightness"):     [(0x9F1E012E, 2)],
    ("RIBBON", "width"):          [(0xF0DF339B, 2)],
    ("RIBBON", "scale"):          [(0x0EBAEC37, 2)],
    ("RIBBON", "length"):         [(0xF92E647B, 2)],
    ("STRAINRIBBON", "length"):   [(0xF92E647B, 2)],
    ("STRAINRIBBON", "width"):    [(0xF0DF339B, 2)],
    ("VELOCITY3D", "gravity"):    [(0x6A5FE3C4, 2)],
    ("RGBFIRE", "fireColor"):     [(0x39A1E557, 3)],
    ("RGBFIRE", "smokeColor"):    [(0x5A8C6820, 3)],
    ("RGBFIRE", "brightness2"):   [(0x9F1E012E, 2)],
    # ── RGBWATER（2026-09-03 用户实机逐条确认；轨道只在 A0 生效，见 BLOCK_NATIVE_AXIS）──
    # 官方 8 个 TimelineParam 与本块头部 8 个字段**全部实机逐条确认**，无遗留。
    # 头部的第 9 个 float（unknownFloat）没有对应 DT——引擎只声明 6 个 float 参数，
    # 这里有 7 个 float，多出来的那个不可动画。
    ("RGBWATER", "colorRate"):         [(0x9F1E012E, 2)],
    ("RGBWATER", "waterLerpGtoB"):     [(0xA7EDA21C, 2)],
    ("RGBWATER", "intensitySheet"):    [(0x4E00491F, 2)],
    ("RGBWATER", "intensityCubeMap"):  [(0xAFB51DF4, 2)],
    ("RGBWATER", "intensitySpecular"): [(0xD62C2891, 2)],
    ("RGBWATER", "intensityAlpha"):    [(0x19DCE197, 2)],
    ("RGBWATER", "colorSpecular"):     [(0x60D69856, 3)],
    ("RGBWATER", "colorSheet"):        [(0xD6AD0996, 3)],
    ("SCALEANIM", "initialScaleSpeed"): [(0xC24DF97C, 2)],
    ("SCALEANIM", "scaleSpeedY"):       [(0x2822A722, 2)],
    ("SCALEANIM", "scaleSpeedX"):       [(0x909EC047, 2)],
    ("SCALEANIM", "scaleSpeedZ"):       [(0x3A9708CC, 2)],
    ("TUBELIGHT", "headColor"):   [(0x3BA67E7C, 3)],
    ("TUBELIGHT", "tailColor"):   [(0x2AA40DE9, 3)],
    # ── 2026-08 补漏：已有 BLOCK_TO_TLP 映射、但字段表漏掉的 DT ────────────────
    # 缺口来源：官方语料按 (TLP, DT) 统计，+TIML 按钮原先只覆盖 47.3% 的轨道。
    # 只补"字段名与 DT 官方名精确一致"或"与已映射块结构完全同构"的条目；
    # 语义拿不准的见本表下方 FIELD_TO_DT_UNRESOLVED。
    # TRANSFORM2D：与 TRANSFORM3D 同构，但 2D 是拆开的标量字段而非 XYZ 向量
    ("TRANSFORM2D", "offsetX"):   [(0x8E8AFE06, 2)],   # pos:X
    ("TRANSFORM2D", "offsetY"):   [(0xF98DCE90, 2)],   # pos:Y
    ("TRANSFORM2D", "scaleX"):    [(0x9486DF23, 2)],   # scl:X
    ("TRANSFORM2D", "scaleY"):    [(0xE381EFB5, 2)],   # scl:Y
    # BILLBOARD2D：width/height ↔ SizeX/SizeY，与 BILLBOARD3D 同名同哈希
    ("BILLBOARD2D", "width"):     [(0x241CAED2, 2)],   # SizeX
    ("BILLBOARD2D", "height"):    [(0x531B9E44, 2)],   # SizeY
    # UVSEQUENCE：DTI 改名后字段名与 DT 名精确一致
    ("UVSEQUENCE", "playSpeed"):     [(0xE5C92264, 2)],
    ("UVSEQUENCE", "playSpeedCoef"): [(0x33A4A86B, 2)],
    # VELOCITY2D/3D：speed ↔ Speed（两块共用同一 DT hash）
    ("VELOCITY2D", "speed"):      [(0x31182E0D, 2)],
    ("VELOCITY3D", "speed"):      [(0x31182E0D, 2)],
    # EMITTERSHAPE3D：localRotationY/Z 与 DT 名精确一致（X 在语料里未出现）
    ("EMITTERSHAPE3D", "localRotationY"): [(0x0718D2B3, 2)],
    ("EMITTERSHAPE3D", "localRotationZ"): [(0x9E118309, 2)],
    # EMITTERSHAPE3D.rangeXYZ ↔ RangeMin/Max XYZ：官方名的 Min/Max 就是我们实测
    # 改判出的 offset/size（Min=offset、Max=size），两种叫法指同一对，此前记为
    # 矛盾是误会。rangeXYZ 是 XYZ type 0（FLOAT6），背板按游戏序逐轴成对交错
    # [offsetX,sizeX, offsetY,sizeY, offsetZ,sizeZ]，故 DT 也按这个顺序排——
    # 挂 6 条而非 3 条，_field_seed_values 对 6 条走逐位对齐。
    ("EMITTERSHAPE3D", "rangeXYZ"): [
        (0x760F3D43, 2), (0x6484D92C, 2),   # RangeMinX(offsetX), RangeMaxX(sizeX)
        (0x01080DD5, 2), (0x1383E9BA, 2),   # RangeMinY(offsetY), RangeMaxY(sizeY)
        (0x98015C6F, 2), (0x8A8AB800, 2),   # RangeMinZ(offsetZ), RangeMaxZ(sizeZ)
    ],
    # RIBBON：color ↔ Color（XYZ type 2 = RGBA），该块 361 条轨道里 136 条是它
    ("RIBBON", "color"):          [(0x58689812, 3)],
    # TUBELIGHT：lightIntensity 与 DT 名精确一致
    ("TUBELIGHT", "lightIntensity"): [(0x085BC9D5, 2)],
    # STRAINRIBBON：endPosition(XYZ type 3) ↔ TerminatePosition X/Y/Z，游戏分量序
    ("STRAINRIBBON", "endPosition"): [(0x6458334F, 2), (0x135F03D9, 2), (0x8A565263, 2)],
    # ROTATEANIM：官方名里的 "Add" 是**速度**不是加速度，按语料量级判定（2026-08）——
    #   加速度/系数类字段被结构性钉在 1 附近（billboardRotationCoef 中位 1.000/最大
    #   1.20，spinSpeedCoef* 最大 1.10，SCALEANIM 的 scaleAccel* 最大 2.0），而
    #   Add 类 DT 的关键帧值 routinely 冲到 6/10/20（RotationAdd 最大 20、
    #   RotationAddX 最大 10、SizeScalarAdd 最大 6），给"最大只到 1.2 的系数"做的
    #   动画不可能跑到 20。速度类字段则是小中位+宽范围（billboardRotation 中位
    #   0.65/最大 500，spin_velocity 中位 2~3/最大 300），与 DT 分布吻合。
    #   同一判据也确认了 SCALEANIM 既有的 SizeXAdd↔scaleSpeedX 等四条是对的。
    ("ROTATEANIM", "billboardRotation"): [(0xE81961E4, 2)],                          # RotationAdd
    ("ROTATEANIM", "spin_velocity"): [(0xC23FE6C6, 2), (0xB538D650, 2), (0x2C3187EA, 2)],  # RotationAdd X/Y/Z
}

# ── FIELD_TO_DT_UNRESOLVED：语料里有轨道、但字段归属没定论的 DT ─────────────────
# 不进 FIELD_TO_DT（+TIML 按钮不显示），登记在此免得反复重新调查。要加进主表
# 必须先坐实"这条 DT 对应哪个字段"，光看名字像不够——错的映射会让用户以为在给
# A 字段做动画、实际写进了 B 字段的通道。
FIELD_TO_DT_UNRESOLVED = {
    # RGBWATER 原在此（4 条全未定）——2026-09-03 用户实机逐条测出归属，已迁进 FIELD_TO_DT。
    # TUBELIGHT：CoreThickness（17 条）候选 columnRadius / columnEdgeSoftness；
    #   CoreIntensity（7 条）无对应字段。columnRadius 已实机确认过语义，正因如此
    #   不能凭"thickness≈radius"就把 DT 挂上去。
    ("TUBELIGHT", "?"): [(0x316D89C5, 2), (0xB6C0BDF8, 2)],
    # STRAINRIBBON：ColorRate 候选 emissionStrength（RIBBON 那边是 brightness，
    #   本块没有同名字段）；LocalRotationY 在本块字段表里没有对应项。
    ("STRAINRIBBON", "?"): [(0x9F1E012E, 2), (0x0718D2B3, 2)],
    # MESH：ColorRate（24 条）—— emissive_brightness 已占 EmissiveColorRate，
    #   剩下 emissive_saturation 是配对的另一半，不像整体亮度系数。
    ("MESH", "?ColorRate"): [(0x9F1E012E, 2)],
}

# ── BLOCK_NATIVE_AXIS：块类型名(大写) → 该块 TIML 动画在真实语料里锁定的轴 slot ──────
# 绝大多数块类型的动画几乎只出现在单一轴上（A0=发射轴/系统时间线，A1=寿命轴/每粒子）。
# 强烈线索：游戏似乎只在母轴上应用对应块的动画——把轨道加到另一条轴会静默无效。
# 实测佐证：TubeLight/Transform3D/RgbFire（均 A0 锁定）加到 A1 全不生效，
# 而 Billboard3D 加哪条都生效。
#   0 = A0 母轴 / 1 = A1 母轴 / None = 两轴都常见（不限制，如 Billboard3D）
# 锁定率（>90% 的视为"母轴"）：
#   A0: Transform3D 98% / RgbFire 100% / RgbWater 98% / TubeLight 100% /
#       EmitterShape3D 93% / Transform2D 100% / Velocity2D 100%
#   A1: Mesh 98% / Ribbon 96% / Plane 91% / StrainRibbon 100% / UVSequence 99% /
#       RotateAnim 97% / ScaleAnim 92% / Velocity3D 95% / Billboard2D 100%
BLOCK_NATIVE_AXIS = {
    "TRANSFORM3D":    0,
    "TRANSFORM2D":    0,
    "RGBFIRE":        0,
    "RGBWATER":       0,
    "TUBELIGHT":      0,
    "EMITTERSHAPE3D": 0,
    "VELOCITY2D":     0,
    "MESH":           1,
    "RIBBON":         1,
    "PLANE":          1,
    "STRAINRIBBON":   1,
    "UVSEQUENCE":     1,
    "ROTATEANIM":     1,
    "SCALEANIM":      1,
    "VELOCITY3D":     1,
    "BILLBOARD2D":    1,
    "BILLBOARD3D":    None,   # 两轴都常见（350:1657），不限制
}


def block_native_axis(block_type: str):
    """块类型的 TIML 母轴 slot（0=A0/1=A1），两轴都常见或未知 → None。"""
    return BLOCK_NATIVE_AXIS.get((block_type or "").upper())


# ── CORPUS_PAIRS：TLP hash → [(dt_hash, data_type), ...] ─────────────────────────
# 只收录有命名的 DT hash（DT_NAMES 或 DT_TRANSFORM 覆盖的条目）。
CORPUS_PAIRS = {
    0x327A81AC: [  # Billboard3D，1645次最多
        (0x58689812, 3), (0x9F1E012E, 2), (0x531B9E44, 2), (0x0EBAEC37, 2),
        (0x241CAED2, 2), (0x2FF50558, 2), (0xC216C23D, 3),
    ],
    0x4D111433: [  # Transform3D，pos/rot/scl 9条
        (0xF98DCE90, 2), (0x60849F2A, 2), (0x8E8AFE06, 2),
        (0xE381EFB5, 2), (0x9486DF23, 2), (0x7A88BE0F, 2),
        (0x86028B75, 2), (0xF105BBE3, 2), (0x1F0BDACF, 2),
    ],
    0x65004E2A: [  # MhEffectDecalBehavior
        (0x7D235C30, 2), (0xCBDB6622, 3), (0x3775827A, 2), (0x4072B2EC, 2),
        (0xBF160652, 2), (0x26BD5CC2, 3), (0xAE7CD3C0, 2), (0x831B390B, 2),
        (0x4D41A06B, 2), (0x16814F1C, 2),
    ],
    0x538AF627: [  # Mesh
        (0x18C577DE, 2), (0x531B9E44, 2), (0x58689812, 3), (0x241CAED2, 2),
        (0x002FF505, 2), (0xCA12CFFE, 2), (0xEE219429, 2), (0x9F1E012E, 2),
        (0x7728C593, 2), (0x608DCF8D, 3), (0x0EBAEC37, 2),
    ],
    0x33185295: [  # EmitterShape3D
        (0x1383E9BA, 2), (0x8A8AB800, 2), (0x6484D92C, 2),
        (0x98015C6F, 2), (0x760F3D43, 2), (0x01080DD5, 2),
        (0x0718D2B3, 2), (0x9E118309, 2),
    ],
    0x1436E592: [  # Ribbon
        (0x9F1E012E, 2), (0x58689812, 3), (0xF0DF339B, 2), (0x0EBAEC37, 2), (0xF92E647B, 2),
    ],
    0x60BA9117: [  # RgbFire
        (0x9F1E012E, 2), (0x5A8C6820, 3), (0x39A1E557, 3),
    ],
    0x6DA6E5D1: [  # MhPointLightBehavior
        (0x94BCC5CE, 2), (0x58689812, 3), (0x435F3054, 2), (0xC32F9493, 2),
    ],
    0x42E48DDE: [  # PointLightBehavior
        (0x94BCC5CE, 2), (0x435F3054, 2), (0xC32F9493, 2), (0x58689812, 3),
    ],
    0x598272E1: [  # 未知（PARENTEMISSIVE/PLEMISSIVE 共现）
        (0x94BCC5CE, 2), (0xFA79B1CD, 3),
    ],
    0x32C1B4B4: [  # Velocity3D
        (0x31182E0D, 2), (0x6A5FE3C4, 2),
    ],
    0x09C466DC: [  # 未知（PTCOLLISION 共现）
        (0x371BBC04, 2), (0xAFE95AC0, 3), (0xA01B7821, 3), (0x1BB0EB80, 2),
    ],
    0x5AC7FC29: [  # UVSequence
        (0xE5C92264, 2), (0x33A4A86B, 2),
    ],
    0x2A62F92E: [  # ScaleAnim
        (0xC24DF97C, 2), (0x2822A722, 2), (0x909EC047, 2), (0x3A9708CC, 2),
    ],
    0x540A2572: [  # Transform2D
        (0x8E8AFE06, 2), (0xF98DCE90, 2), (0x9486DF23, 2), (0xE381EFB5, 2),
    ],
    0x1F09850E: [  # StrainRibbon
        (0xF92E647B, 2), (0xF0DF339B, 2), (0x6458334F, 2), (0x135F03D9, 2),
        (0x8A565263, 2), (0x9F1E012E, 2), (0x0718D2B3, 2),
    ],
    0x5E8D9EE9: [  # 未知（EMITTERSHAPEMESH 共现）
        (0xC207B8B4, 2), (0xAFE95AC0, 3), (0x1BB0EB80, 2), (0xA01B7821, 3),
    ],
    0x2101C529: [  # RgbWater
        (0xA7EDA21C, 2), (0x9F1E012E, 2), (0x4E00491F, 2), (0x60D69856, 3),
    ],
    0x563C8065: [  # RotateAnim
        (0xE81961E4, 2), (0xC23FE6C6, 2), (0xB538D650, 2), (0x2C3187EA, 2),
    ],
    0x582BA062: [  # RadialBlurFilterBehavior
        (0x1D95BB54, 2), (0xAB9D6334, 2), (0x58689812, 3), (0x0ECBFA29, 2), (0x0EF6ABF4, 2),
    ],
    0x39C68FB4: [  # TubeLight
        (0x316D89C5, 2), (0x085BC9D5, 2), (0xB6C0BDF8, 2), (0x3BA67E7C, 3), (0x2AA40DE9, 3),
    ],
    0x3481666B: [  # Plane
        (0x9F1E012E, 2), (0x58689812, 3), (0x0EBAEC37, 2), (0x531B9E44, 2),
    ],
    0x75963575: [  # MhSpotLightBehavior
        (0x94BCC5CE, 2), (0x58689812, 3),
    ],
    0x399DB6A9: [  # 未知
        (0x71BCF0AA, 2), (0xC207B8B4, 2),
    ],
    0x7E51F5BD: [  # 未知（EMITTERBOUNDARY 共现）
        (0x4279F094, 2), (0x13804BC9, 2),
    ],
    0x2B61B0ED: [  # Billboard2D
        (0x241CAED2, 2), (0x531B9E44, 2),
    ],
    0x66C62149: [  # 未知
        (0xA01B7821, 3), (0x1BB0EB80, 2),
    ],
    0x2C78B827: [  # 未知
        (0xA01B7821, 3), (0x1BB0EB80, 2),
    ],
    0x4E64D91C: [  # 未知（PLANE 共现）
        (0xAFE95AC0, 3), (0x1BB0EB80, 2),
    ],
    0x2BDA85F5: [  # Velocity2D
        (0x31182E0D, 2),
    ],
    0x0B8924DA: [  # 未知（PTTRIGGER 共现）
        (0xAFE95AC0, 3),
    ],
    0x3E880466: [  # 未知
        (0x0FF5554F, 3),
    ],
    0x5752ED69: [  # 未知
        (0xAFE95AC0, 3),
    ],
}

# ── DTI_EXTRA_PAIRS：DTI 里声明、但全语料 0 例的 (TLP → [(DT, dataType)]) ────────
# CORPUS_PAIRS 只收语料实测到的组合，是「官方确实这么用过」的证据表，语义要保持干净
# （tools/lib/timl_engine.py、tools/scan_tubelight.py 按这个含义在用）。但「官方没用过」
# 不等于「引擎不支持」——不把这些放进调色板，用户就永远没法给它们建轨道做实机测试，
# 而这正是往下推语义的主要手段（RgbWater 的 4 条字段映射就是这么测出来的）。
# 故另立此表，仅供 UI 调色板 DT_PALETTE 合并使用。
#
# ⚠ 这里的每一条都**未经任何验证**：既没有官方用例，也没有实机确认。加了轨道游戏里
#   是否生效、对应哪个字段，都要自己测。（多数块还受 BLOCK_NATIVE_AXIS 的母轴限制。）
DTI_EXTRA_PAIRS = {
    0x2B61B0ED: [  # Billboard2D（DTI: TypeBillboard2D），+8
        (0x0EBAEC37, 2), (0x2FF50558, 2), (0xEEBD5618, 2), (0xCDBCBB7E, 3), (0xF80CE653, 3),
        (0x9F1E012E, 2), (0xC216C23D, 3), (0x58689812, 3)
    ],
    0x327A81AC: [  # Billboard3D（DTI: TypeBillboard3D），+3
        (0xEEBD5618, 2), (0xCDBCBB7E, 3), (0xF80CE653, 3)
    ],
    0x096CABC4: [  # ColorCorrectFilter，+51
        (0x93A7FACA, 2), (0x34B93272, 2), (0xB13D703D, 2), (0xA826417C, 2), (0xC63A40AB, 2),
        (0xDF2171EA, 2), (0x5F331111, 2), (0x46282050, 2), (0x28342187, 2), (0x312F10C6, 2),
        (0xB650B424, 2), (0xAF4B8565, 2), (0xC15784B2, 2), (0xD84CB5F3, 2), (0x585ED508, 2),
        (0x4145E449, 2), (0x2F59E59E, 2), (0x3642D4DF, 2), (0xB7F6B2D6, 2), (0xAEED8397, 2),
        (0xC0F18240, 2), (0xD9EAB301, 2), (0x59F8D3FA, 2), (0x40E3E2BB, 2), (0x2EFFE36C, 2),
        (0x37E4D22D, 2), (0xB09B76CF, 2), (0xA980478E, 2), (0xC79C4659, 2), (0xDE877718, 2),
        (0x5E9517E3, 2), (0x478E26A2, 2), (0x29922775, 2), (0x30891634, 2), (0xAD1BD34D, 2),
        (0xB400E20C, 2), (0xDA1CE3DB, 2), (0xC307D29A, 2), (0x4315B261, 2), (0x5A0E8320, 2),
        (0x341282F7, 2), (0x2D09B3B6, 2), (0xAA761754, 2), (0xB36D2615, 2), (0xDD7127C2, 2),
        (0xC46A1683, 2), (0x44787678, 2), (0x5D634739, 2), (0x337F46EE, 2), (0x2A6477AF, 2),
        (0xB78EE6DA, 2)
    ],
    0x2A0363D4: [  # EmitterShape2D，+5
        (0x7516AA5D, 2), (0x1383E9BA, 2), (0x01080DD5, 2), (0x6484D92C, 2), (0x760F3D43, 2)
    ],
    0x33185295: [  # EmitterShape3D，+1
        (0x701FE225, 2)
    ],
    0x538AF627: [  # Mesh（DTI: TypeMesh），+3
        (0xE5C92264, 2), (0x7F2CEB57, 3), (0xC216C23D, 3)
    ],
    0x65004E2A: [  # MhEffectDecalBehavior，+7
        (0xAA2229C3, 2), (0x59EEF098, 2), (0x275F8C25, 2), (0xBE56DD9F, 2), (0xC951ED09, 2),
        (0x353D6FFC, 2), (0xB1F7AEF0, 2)
    ],
    0x6DA6E5D1: [  # MhPointLightBehavior，+6
        (0x0E24B8A2, 2), (0xE609DBFA, 2), (0xCF5D2EDD, 2), (0x2AD90E22, 2), (0xE7DF422D, 2),
        (0xC126B7BD, 2)
    ],
    0x75963575: [  # MhSpotLightBehavior，+12
        (0x0E24B8A2, 2), (0x7AF2755D, 2), (0x7F2FEA9B, 2), (0x84E65AB1, 2), (0xD23788D3, 2),
        (0x435F3054, 2), (0xC32F9493, 2), (0xE609DBFA, 2), (0xCF5D2EDD, 2), (0x2AD90E22, 2),
        (0xE7DF422D, 2), (0xC126B7BD, 2)
    ],
    0x2ED89BCC: [  # ParentMaterial，+2
        (0x94BCC5CE, 2), (0xFA79B1CD, 3)
    ],
    0x3481666B: [  # Plane（DTI: TypePlane），+5
        (0x241CAED2, 2), (0xEEBD5618, 2), (0xCDBCBB7E, 3), (0xF80CE653, 3), (0xC216C23D, 3)
    ],
    0x42E48DDE: [  # PointLightBehavior，+5
        (0xE609DBFA, 2), (0xCF5D2EDD, 2), (0x2AD90E22, 2), (0xE7DF422D, 2), (0xC126B7BD, 2)
    ],
    0x582BA062: [  # RadialBlurFilterBehavior，+13
        (0xE22A3268, 2), (0xC893EE17, 2), (0x1204171A, 2), (0xBA17788F, 2), (0xDC774A4A, 2),
        (0x49AE09C7, 2), (0x2FCE3B02, 2), (0xC4A60432, 2), (0xA2C636F7, 2), (0x2B0CF983, 2),
        (0x55BD853E, 2), (0xCCB4D484, 2), (0xBBB3E412, 2)
    ],
    # ⚠ RgbWater 这 4 条已被实机验证**确实可用**（用户 2026-09-03 建轨道逐条测出对应字段）
    #   —— 这是「DTI 有、语料 0 例」的条目并非死数据的直接证据，本表其余条目同理可测。
    0x2101C529: [  # RgbWater，+4
        (0x19DCE197, 2), (0xD62C2891, 2), (0xAFB51DF4, 2), (0xD6AD0996, 3)
    ],
    0x1436E592: [  # Ribbon（DTI: TypeRibbon），+7
        (0x994333F2, 2), (0x7E6555E0, 2), (0x9DB8917C, 2), (0xEEBD5618, 2), (0xCDBCBB7E, 3),
        (0xF80CE653, 3), (0xC216C23D, 3)
    ],
    0x3DE576DC: [  # SpotLightBehavior，+13
        (0x7AF2755D, 2), (0x7F2FEA9B, 2), (0x84E65AB1, 2), (0xD23788D3, 2), (0x435F3054, 2),
        (0xC32F9493, 2), (0xE609DBFA, 2), (0xCF5D2EDD, 2), (0x2AD90E22, 2), (0xE7DF422D, 2),
        (0xC126B7BD, 2), (0x94BCC5CE, 2), (0x58689812, 3)
    ],
    0x1F09850E: [  # StrainRibbon（DTI: TypeStrainRibbon），+20
        (0x9E118309, 2), (0x701FE225, 2), (0x8A8AB800, 2), (0x1383E9BA, 2), (0x6484D92C, 2),
        (0x98015C6F, 2), (0x01080DD5, 2), (0x760F3D43, 2), (0x086567E1, 2), (0x916C365B, 2),
        (0xE66B06CD, 2), (0x994333F2, 2), (0x7E6555E0, 2), (0x9DB8917C, 2), (0x0EBAEC37, 2),
        (0xEEBD5618, 2), (0xCDBCBB7E, 3), (0xF80CE653, 3), (0xC216C23D, 3), (0x58689812, 3)
    ],
    0x13A0F54F: [  # TonemapFilter，+1
        (0x94BCC5CE, 2)
    ],
    0x540A2572: [  # Transform2D，+1
        (0xE2C6589E, 2)
    ],
    0x39C68FB4: [  # TubeLight，+5
        (0x7D0FD331, 2), (0x102FFF8B, 2), (0x931E7E65, 2), (0x435F3054, 2), (0x6ACAAAD7, 2)
    ],
    0x2BDA85F5: [  # Velocity2D，+1
        (0x6A5FE3C4, 2)
    ],
}


def _merge_pairs():
    """CORPUS_PAIRS ∪ DTI_EXTRA_PAIRS —— UI 调色板用的完整 (TLP → DT 列表)。

    语料条目在前、DTI 补充在后，所以下拉里官方用过的排前面。"""
    out = {h: list(v) for h, v in CORPUS_PAIRS.items()}
    for h, v in DTI_EXTRA_PAIRS.items():
        out.setdefault(h, []).extend(v)
    return out


DT_PALETTE = _merge_pairs()
