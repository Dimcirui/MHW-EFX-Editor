# -*- coding: utf-8 -*-
"""
efx_format/attributes.py — 定长 attribute 块的 typed schema 定义

 hash 常量晚于此处导入 → Attribute 定义时 hash 留空，由 structs 装配层导入 hashes 后回填 + register。
"""
from .fields_model import (
    Attribute, Int, UInt, Short, UShort, Byte, SByte, Float, Int64, UInt64,
    Enum, EnumVec3, Bool, Bitmask, Raw,
)
from .enums import (
    ENUM_SHAPE_TYPE3D, ENUM_RANGE_DIVIDE_AXIS, ENUM_RANGE_DIVIDE_AXIS_2D,
    ENUM_ROTATION_CORRECT_TYPE,
    ENUM_SHAPE_TYPE2D, ENUM_COLLISION_PHYSICS, ENUM_IMPACT_PLAY_TRIGGER_MODE, ENUM_PTLIFE_STATUS,
    ENUM_RAYCAST_DIR, ENUM_HOMING_TARGET, ENUM_HOMING_FORCEFIELD, ENUM_HOMING_VANISH,
    ENUM_RENDER_LAYER, ENUM_SHADER_CONTROL, ENUM_ROTATION_MODE,
    ENUM_TRACKING_POS, ENUM_TRACKING_ANGLE, ENUM_REFRACTION_OFFSET,
    BITS_ENABLE_VELOCITY, BITS_SPIN_AXIS, BITS_RANDOMFIX_TABLE, BITS_FADEBYANGLE_FLAGS,
    BITS_SPAWN_UNKN31,
    _AXIS_DIRECTION6, _ROT_ORDER6, _VELOCITY_TYPE, _TRANSFORM_ROT_ORDER,
)
from .codec import _schema_size

# ─────────────────────────────────────────────────────────────────────────────
# ExternTransform3D schema  (228 B)
#
# BT (EFX_Subtypes.bt):
#   int     unkn0                                    4 B
#   XYZ     translate(0)   6 floats                 24 B
#   XYZ     rotate(0)      6 floats                 24 B
#   XYZ     resize(0)      6 floats                 24 B
#   int     rotationOrder (unkn1)                     4 B
#   XYZ     Translation_Velocity(0)                 24 B
#   XYZ     Translation_Velocity_Modifier(0)        24 B
#   XYZ     Rotation_Velocity(0)                    24 B
#   XYZ     Rotation_Velocity_Modifier(0)           24 B
#   XYZ     Scale_Velocity(0)                       24 B
#   XYZ     Scale_Velocity_Modifier(0)              24 B
#   int     enableVelocityBitflag                    4 B
# Total: 4 + 24*3 + 4 + 24*6 + 4 = 4+72+4+144+4 = 228 B
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_TRANSFORM3D_ATTR = Attribute(size=228, fields=[
    Int("typeFlag"),  # 原 unkn0
    Raw("translate", ('XYZ', 0), label_zh="平移"),
    Raw("rotate", ('XYZ', 0), label_zh="旋转"),
    Raw("resize", ('XYZ', 0), label_zh="缩放"),
    Enum("rotationOrder", _TRANSFORM_ROT_ORDER, label_zh="旋转顺序"),
    Raw("translation_velocity", ('XYZ', 0), label_zh="平移速度"),
    Raw("translation_velocity_modifier", ('XYZ', 0), label_zh="平移速度修正"),
    Raw("rotation_velocity", ('XYZ', 0), label_zh="旋转速度"),
    Raw("rotation_velocity_modifier", ('XYZ', 0), label_zh="旋转速度修正"),
    Raw("scale_velocity", ('XYZ', 0), label_zh="缩放速度"),
    Raw("scale_velocity_modifier", ('XYZ', 0), label_zh="缩放速度修正"),
    # 全语料 111993/111993 穷举：取值只有 0/1/2/3，即 bit0/bit1 各自独立开关+组合，
    # bit2 及以上从未出现过——确认是纯 2 位可混合掩码，非 4 值枚举，strict=True 不留残留位框。
    Bitmask("enableVelocityBitflag", BITS_ENABLE_VELOCITY, label_zh="启用速度位标志", strict=True),
])
EXTERN_TRANSFORM3D_SCHEMA = EXTERN_TRANSFORM3D_ATTR.schema
assert _schema_size(EXTERN_TRANSFORM3D_SCHEMA) == 228, \
    f"EXTERN_TRANSFORM3D_SCHEMA size mismatch: {_schema_size(EXTERN_TRANSFORM3D_SCHEMA)}"

# Transform3D block data_bytes schema (excludes the 4-byte type hash already
# stripped by AttrBlock).  Total must equal 232-4 = 228 B.
TRANSFORM3D_SCHEMA = EXTERN_TRANSFORM3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# ParentOptions schema  (data_bytes = 60 B; full block = 64 B)
#
# BT (EFX_Subtypes.bt):
#   long    type                              4 B  ← in type_hash, not in data_bytes
#   int     unkn0                             4 B
#   XYZ     relationPos(1)          12 B  (int x,y,z)
#   XYZ     relationRot(1)                12 B
#   XYZ     relationScl(1)                12 B
#   int     particleUseLocal                        4 B
#   int     unkn1                             4 B
#   int     spawnLock                         4 B
#   int     bleedPos                          4 B
#   int     jointNo                          4 B
# data_bytes total: 4 + 36 + 4*5 = 4+36+20 = 60 B  ✓  (full block = 64 B)
# ─────────────────────────────────────────────────────────────────────────────

PARENTOPTIONS_ATTR = Attribute(size=60, fields=[
    Int("typeFlag"),  # 原 unkn0
    EnumVec3("relationPos", ENUM_TRACKING_POS, label_zh="平移跟踪"),
    EnumVec3("relationRot", ENUM_TRACKING_ANGLE, label_zh="角度跟踪"),
    EnumVec3("relationScl", ENUM_TRACKING_POS, label_zh="缩放跟踪"),
    Bool("particleUseLocal", label_en="Follow Emitter", label_zh="跟随发射器"),
    Bool("unknFlag1"),
    # 原 spawnLock/bleedPos：实为一对 fixed+jitter，作用是"跨生成追踪启用后，达到该帧数即
    # 停止追踪"（0=始终追踪），并非各自独立的"锁定位置/渗出位置"。
    Int("constRelease", label_zh="停止追踪帧数"),
    Int("constReleaseJitter", label_zh="停止追踪帧数抖动"),
    Int("jointNo", label_zh="绑定骨骼"),  # 绑定骨骼的序号
])
PARENTOPTIONS_SCHEMA = PARENTOPTIONS_ATTR.schema
assert _schema_size(PARENTOPTIONS_SCHEMA) == 60, \
    f"PARENTOPTIONS_SCHEMA size mismatch: {_schema_size(PARENTOPTIONS_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternSpawn schema  (72 B)
#
# BT 原字段名（EFX_Subtypes.bt）见各字段行内注释；下面是 2026-07-26 用户实机测试
# （详见 docs/ATTRIBUTE_BEHAVIOR_NOTES.md「SPAWN」一节）后按 emitter/particle 三层模型
# （SPAWN属性本身 → emitter实例/轮次 → particle个体）重新命名的结果：
#
#   maxParticles/burstInterval/burstsPerCycle/emitterRepeatCount/emitterStartDelay
#   均为 emitter 实例层字段；particleSpawnDelay 是唯一的 particle 层字段。
#
# 核心机制（完整模型见 docs）：
#   - maxParticles：同时存活粒子数软上限（非终身总量，Little's Law 验证：
#     稳态同存数=生成速率×粒子寿命）
#   - burstsPerCycle(+Jitter)：每轮（每次换新位置）重新抽取，三态：
#     0=永不换位置+burstInterval节奏无限生成；1=改用altBurstInterval节奏；
#     ≥2=仍用burstInterval节奏。非0时总批次数=该值+emitterRepeatCount-1，
#     最后一批固定按粒子寿命(LIFE duration+fadeOutDuration)节奏，随后立即换位置
#   - emitterRepeatCount：0=无论burstsPerCycle是什么都永不换位置；
#     非0时与burstsPerCycle相加决定总批次数。没有Jitter搭档
#   - altBurstInterval(+Jitter)：仅当burstsPerCycle抽到1时，取代burstInterval
#     作为批次间隔（原名ringBufferInterval，2026-07-26根据精确模型改名——它就是
#     burstInterval的替代取值，跟"环形缓冲"式的容量回收逻辑无关，那是maxParticles的职责）
#   - instanceCountUnknLimit(+Jitter)/unknBitmask31：仍未测试，保留原名
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_SPAWN_ATTR = Attribute(size=72, fields=[
    Int("typeFlag"),  # 原 unkn0
    Int("maxParticles", label_zh="同时存活上限"),  # 原 instancesSpawnedTotal，同时存活软上限
    Int("particlesPerBurst", label_zh="单批生成数"),  # 原 instancesSpawnedPerFrame
    Int("particlesPerBurstJitter", label_zh="单批生成数抖动"),  # 原 randomizedSpawnsPerFrame
    Int("burstInterval", label_zh="批次间隔（帧）"),  # 原 frameDelayBetweenSpawns
    Int("burstIntervalJitter", label_zh="批次间隔抖动（帧）"),  # 原 randomizedDelay
    Int("burstsPerCycle", label_zh="每轮批次数"),  # 原 durationOfSpawnerLifespan，三态模式选择+计数基准
    Int("burstsPerCycleJitter", label_zh="每轮批次数抖动"),  # 原 randomizedLifespan
    Int("instanceCountUnknLimit"),
    Int("instanceCountUnknLimitJitter"),
    Int("emitterStartDelay", label_zh="发射器启动延迟（帧）"),  # 原 occur，发射器首次生成前的一次性延迟
    Int("emitterStartDelayJitter", label_zh="发射器启动延迟抖动（帧）"),  # 原 occur2
    # BT 原标 uint32；实测全语料从未接近 2^31，改签名 int 换取原生数值控件（原字符串输入框）  
    Int("particleSpawnDelay", label_zh="粒子生成延迟（帧）"),  # 原 unkn10，粒子个体独立生成延迟
    Int("particleSpawnDelayJitter", label_zh="粒子生成延迟抖动（帧）"),  # 原 unknEnum11
    Int("emitterRepeatCount", label_zh="重复次数"),  # 原 repeatAtribute，批次数加成+换位置总开关
    Int("altBurstInterval", label_zh="替代批次间隔（帧）"),  # 原 unkn21（一度改名 ringBufferInterval，已订正），burstsPerCycle=1时的专属批次间隔
    Int("altBurstIntervalJitter", label_zh="替代批次间隔抖动（帧）"),  # 原 unkn30
    # 官方全语料(112573 块)穷举：可混合位只到 bit5（值 32），bit6+ 从未出现，strict=True。
    Bitmask("unknBitmask31", BITS_SPAWN_UNKN31, strict=True),
])
EXTERN_SPAWN_SCHEMA = EXTERN_SPAWN_ATTR.schema
assert _schema_size(EXTERN_SPAWN_SCHEMA) == 72, \
    f"EXTERN_SPAWN_SCHEMA size mismatch: {_schema_size(EXTERN_SPAWN_SCHEMA)}"

# Spawn block data_bytes schema (excludes type hash)
SPAWN_SCHEMA = EXTERN_SPAWN_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# Life schema  (data_bytes = 48 B; full block = 52 B)
#
# BT (EFX_Subtypes.bt):
#   long type                                4 B  ← in type_hash
#   long unkn0                               4 B
#   long fadeInDuration                      4 B
#   long fadeInDurationJitter                4 B
#   long duration                            4 B
#   long durationJitter                      4 B
#   long unkn2[2]                            8 B
#   long fadeOutDuration                     4 B
#   long fadeOutDurationJitter               4 B
#   long timeToDeath                         4 B
#   long timeToDeathJitter                   4 B
#   long indefiniteLifespan                  4 B
# data_bytes: 12 × 4 = 48 B ✓
#
# unknFrame/unknFrameJitter（原 unkn2[2]/unkn2_0+unknEnum2_1）：语义仍未确认，但字段位置
# 正好夹在其他几组 duration/durationJitter 之间，形态上是同一种 static/random 配对，
# 先按这套惯例改名挂起（"Frame" 只是命名占位，不代表已确认是帧数）。
# ─────────────────────────────────────────────────────────────────────────────

LIFE_ATTR = Attribute(size=48, fields=[
    Int("typeFlag"),  # 原 unkn0
    Int("fadeInDuration", label_zh="淡入时长"),
    Int("fadeInDurationJitter", label_zh="淡入时长抖动"),
    Int("duration", label_zh="持续时间"),
    Int("durationJitter", label_zh="持续时间抖动"),
    Int("unknFrame"),
    Int("unknFrameJitter"),
    Int("fadeOutDuration", label_zh="淡出时长"),
    Int("fadeOutDurationJitter", label_zh="淡出时长抖动"),
    Int("timeToDeath", label_zh="死亡时间"),
    Int("timeToDeathJitter", label_zh="死亡时间抖动"),
    Bool("indefiniteLifespan", label_zh="无限寿命"),
])
LIFE_SCHEMA = LIFE_ATTR.schema
assert _schema_size(LIFE_SCHEMA) == 48, \
    f"LIFE_SCHEMA size mismatch: {_schema_size(LIFE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ShaderSettings schema  (data_bytes = 116 B; full block = 120 B)
#
# BT (EFX_Subtypes.bt):
#   long type                                4 B  ← in type_hash
#   int  unkn0                               4 B
#   int  unkn1                               4 B
#   int  spacer                              4 B  
#   int  unkn2                               4 B
#   float zDepthModifierStart                4 B
#   float zDepthModifierEnd                  4 B
#   int  unkn3_0                             4 B
#   int  unkn3_1                             4 B
#   int  controlBitflag                      4 B
#   float unkn4[16]                         64 B
#   byte  objectInteractionFlag0             1 B
#   byte  objectInteractionFlag1             1 B
#   byte  objectInteractionFlag2             1 B
#   byte  objectInteractionFlag3             1 B
#   byte  unknBool0  ) 原 int visibleOnPreview 语料统计显示实为
#   byte  unknBool1  ) 4 个各自独立的 0/1 字节（十六进制每字节恒
#   byte  unknBool2  ) 0x00 或 0x01），非单一"预览可见"标志，拆
#   byte  unknBool3  ) 分为 4 个布尔字节，语义待实机确认        1 B×4
#   int   unkn5[2]                           8 B
# data_bytes: 9×4 + 64 + 4 + 4 + 8 = 36 + 64 + 16 = 116 B ✓
# ─────────────────────────────────────────────────────────────────────────────

SHADERSETTINGS_ATTR = Attribute(size=116, fields=[
    Int("typeFlag"),  # 原 unkn0
    Int("unknEnum1"),  # 不满足 section_length 公式(99.9%恒104,应为108)，未改名
    Int("spacer"),
    Bool("unknFlag2"),
    Float("zDepthModifierStart", label_zh="Z 深度修正（起始）"),
    Float("zDepthModifierEnd", label_zh="Z 深度修正（结束）"),
    Int("unknBitmask3_0"),
    # 暂不作 enum：RenderLayerMode 标签尚存疑；controlBitflag 官方语料见 5/7/8/9 等组合值
    # （5=1+4、9=1+8…），实为位掩码而非枚举，待 bitmask 编辑器再定。保持原始整数编辑。
    Int("unknEnum3_1", label_zh="渲染层 / Billboard 模式"),
    Int("controlBitflag", label_zh="控制位标志"),
    Float("unkn4_0"),
    Float("unkn4_1"),
    Float("unkn4_2"),
    Float("unkn4_3"),
    Float("unkn4_4"),
    Float("unkn4_5"),
    Float("unkn4_6"),
    Float("unkn4_7"),
    Int("unknEnum4_8"),  # BT 模板标为 float，但仅 10 种取值，63.6% 恒为 -1（sentinel），
                        # 其余为看似随机的大整数（疑似哈希/ID），无一落在正常浮点参数范围，改回 int
    Float("unkn4_9"),
    Float("unkn4_10"),
    Float("unkn4_11"),
    Float("unknFixed4_12"),
    Float("unkn4_13"),
    Int("unknBitmask4_14"),
    Int("unkn4_15"),
    Byte("objectInteractionFlag0", label_zh="物体交互标志0"),
    Byte("objectInteractionFlag1", label_zh="物体交互标志1"),
    Byte("objectInteractionFlag2", label_zh="物体交互标志2"),
    Byte("objectInteractionFlag3", label_zh="物体交互标志3"),
    Bool("unknBool0", backing='B'),  # 原 visibleOnPreview 拆分（4 字节各恒 0/1，非单一标志）
    Bool("unknBool1", backing='B'),
    Bool("unknBool2", backing='B'),
    Bool("unknBool3", backing='B'),
    Int("unknEnum5_0"),
    Int("unknBitmask5_1"),
])
SHADERSETTINGS_SCHEMA = SHADERSETTINGS_ATTR.schema
assert _schema_size(SHADERSETTINGS_SCHEMA) == 116, \
    f"SHADERSETTINGS_SCHEMA size mismatch: {_schema_size(SHADERSETTINGS_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternVelocity3D schema  (108 B)
#
# 2026-07 定稿依据：用户多轮实机测试 + RE Engine 续作 schema（EFXAttributeVelocity3D，
# kagenocookie/RE-Engine-Lib 社区反查）三方交叉印证，字段名尽量直接采用续作命名：
#   Speed→initialVelocity, SpeedCoef→acceleration, SpeedDelayFrame→initialVelocityDelay,
#   GravityRate/GravityDelayFrame→gravity/gravityDelay, VelocityType→velocityType
#   （TIML DTI 名"Speed"也独立佐证了 initialVelocity）。
#
#   int   typeFlag                           4 B
#   int   initialVelocityAxis（原 unknBitmask0_1）：initialVelocity 的基准轴，
#         与 rotationX/Y/Z 复合决定最终朝向，仅在 velocityType=0(Direction) 时有意义。
#         AxisDirection6 枚举（0=左,1=上,2=前,3=右,4=下,5=后），与 RIBBONBLADE.
#         widthDirection / RIBBON.baseAxis 同款；仅confirmed 3/4 两点。
#         用"Axis"而非"Direction"命名以区分它是"选六个基准轴之一"而非自由方向向量 4 B
#   int   unknAxis（原 unknBitmask0_2）：疑似旋转顺序（结构上跟 EMITTERSHAPE3D.
#         rotationOrder 一样 6 值以 4 为主流），但实机测试（固定 rotationX=rotationY=90，
#         逐个切换该字段 0~5）结果对不上 TRANSFORM3D 已知的 0~5→XYZ/YZX/ZXY/ZYX/YXZ/XZY
#         顺序表（无论正读反读都只对上部分），暂缓深究，先按未知处理                4 B
#   float rotationX                          4 B  ─┐ 实机排除"向量"假说，确认是旋转角度
#   float rotationXJitter                    4 B   │（360°/720°抖动上限即是证据）；且实测
#   float rotationY                          4 B   │出局部坐标系：X轴=左右旋转轴，Y轴=上下
#   float rotationYJitter                    4 B   │旋转轴（旋转"上"不变），Z轴=前后旋转轴，
#   float rotationZ                          4 B   │与 AxisDirection6 三对方向一一对应。
#   float rotationZJitter                    4 B  ─┘同样仅在 velocityType=0(Direction) 有意义
#   float initialVelocity（原 expansion_radius_limit）                    4 B
#   float initialVelocityJitter（原 expansion_radius_jitter）             4 B
#   float acceleration（原 expansion_radius_elasticity）：1=匀速，>1=加速并突破
#         initialVelocity 原值持续增长，<1=减速直至0                     4 B
#   float accelerationJitter（原 expansion_radius_elasticity_jitter）    4 B
#   float offsetX                            4 B  ─┐ 仅在搭配生成方式类属性（如
#   float offsetY                            4 B   │ EMITTERSHAPE3D/EMITTERSHAPEMESH等，
#   float offsetZ                            4 B  ─┘ 理论上不限于ES3D）且 velocityType=1
#         (Normal) 时生效；确认对应续作 Offset（原 velocityX/Y/Z）
#   float sizeX                              4 B  ─┐ 同上条件下生效；确认对应续作
#   float sizeY                              4 B   │ Size（原 energyOnAxisX/Y/Z）。
#   float sizeZ                              4 B  ─┘ 与 offsetX/Y/Z 共同决定每个粒子
#         的运动方向：先按公式 Vi=(sizeI−1)×该粒子在i轴的生成坐标+offsetI（i=X/Y/Z）
#         算出一个三维向量，再归一化——方向=normalize(Vx,Vy,Vz)，速度恒定（与
#         Vx/Vy/Vz 的具体大小无关，只看方向）。三轴 size 相等时退化为真正的径向
#         收拢/发散（<1收拢穿心而过继续到对面，>1发散，=1该轴无效果）；三轴不等时
#         方向连续过渡（不是离散分区）。offsetI=0 时该轴的"零点"精确落在真正几何
#         中心；offsetI≠0 会把零点挪开，实机数值验证：临界 offsetI = (sizeI−1)×该轴
#         实际坐标范围（如 ES3D 的 rangeXYZ，含 radiusEnd 等相对倍数换算后的实际值）
#   int   velocityType（原 expansionType）：RE Engine 续作 VelocityType 枚举。本质是
#         "决定粒子运动方向如何确定"（速度始终由 initialVelocity/acceleration 决定，
#         重力独立于此始终生效）——0=Direction(由 initialVelocityAxis+rotation 决定方向),
#         1=Normal(常规，仅由 offset+size 共同决定方向；实测更可能是"常规/标准"而非字面
#         "表面法线"——offset/size 全中性时完全静止), 2=Radial(始终向外运动，无视
#         offset/size/方向字段), 3=Spread(运动方向=生成瞬间发射器的速度方向),
#         4=ScreenSpace, 5=Max(C# 数组哨兵值，从不出现——全语料 82756 条零个=5，与此吻合)
#         【velocityType 其实更贴切叫 velocityDirectionType，但保留续作原名 VelocityType
#          以维持可追溯性，方向语义写进 tooltip】                              4 B
#   float gravity                            4 B  # 重力，不论 velocityType 如何始终生效；TIML DT 0x6A5FE3C4("Gravity") 已确认
#   float gravity_jitter                     4 B
#   int   initialVelocityDelay（原 expansionDelay）：initialVelocity 生效前的延迟帧数  4 B
#   int   initialVelocityDelayJitter（原 expansionDelayJitter）           4 B
#   int   gravityDelay：gravity 生效前的延迟帧数                          4 B
#   int   gravityDelayJitter                 4 B
#   float unknFloat（原 NULL2）：名字像占位，但实测非零值干净重解读为 40.0，语义未确认  4 B  
# Total: 12 + 6×4 + 4×4 + 3×4 + 3×4 + 4 + 2×4 + 4×4 + 4 = 108 B
#
# 续作 schema 里还有 InheritRate/InheritDistance/Spread 等字段没能对应到我们这 108B
# 里，可能是 MHW 这代（MT Framework）压根没有的后加功能。RE Engine 的 uint Flags
# 字段是否对应 typeFlag/initialVelocityAxis/unknAxis 这三个头部字段的合并，
# 风险较大，未采信。
#
# 待补充测试：unknAxis 的完整规律、velocityType=2/3/4 与生成方式类属性共现时的
# 细节、offset/size 三轴同时生效时总速度是否会跟单轴时不同（目前只验证过方向公式，
# 未验证多轴同时生效的合速度大小）。见 docs/ATTRIBUTE_BEHAVIOR_NOTES.md「与生成方式
# 共现」一节；交互式演示见 docs/interactive/velocity3d_offset_size_model.html。
# ─────────────────────────────────────────────────────────────────────────────

# ── VELOCITY3D：typed field-object 模型（类型即语义，enum 用 EnumDef，标签内嵌）──
# Attribute.schema 降级成与旧 tuple 逐字节等价的 [(name, spec)]，codec 无感。
# hash 常量晚于此处导入（见文件末 hashes import），故 Attribute 定义时 hash 留空、导入后回填。
#
# 字段考据保留在这里（研究记录，非用户 tooltip；tooltip 只写结论，见记忆 annotation-tone）：
#   typeFlag         原 unkn0_0（续作 schema 叫 uniqueID，为统一全仓库 typeFlag 惯例未改名）
#   baseAxis         原 initialVelocityAxis/unknBitmask0_1；枚举 0=左1=上2=前3=右4=下5=后 为旧假说，
#                    与续作 AxisType 的 0=+X..5=-Z 笛卡尔映射有出入，未定论
#   rotOrder         原 unknAxis/unknBitmask0_2；依续作 schema RotOrder 坐实 0=XYZ..5=ZYX
#                    （跟 TRANSFORM3D 惯例不是同一套映射）
#   speed/speedJitter        原 initialVelocity/expansion_radius_limit（+jitter），依续作改名，语义不变
#   acceleration(+Jitter)    原 expansion_radius_elasticity（+jitter）；续作叫 drag（1=匀速/0=瞬停），
#                            本质同一个力，用户 2026-07-26 决定保留 acceleration 名字
#   velocityX/Y/Z            原 offsetX/Y/Z；仅 velocityType=DirectionalSpread 时生效，方向性、量级无关
#   divergenceX/Y/Z          原 sizeX/Y/Z（energyOnAxis*）；1=该轴无效果，<1 朝基准点，>1 背离基准点
#   velocityType             原 expansionType；续作 0=Directional/1=DirectionalSpread(原"Normal")/
#                            2=Radial/3=EmitterMotion(原"Spread")。⚠ 语料曾观测 4/5(旧注释 ScreenSpace/Unkn)，  
#                            超出 0~3 集合，UI 层需对越界值回退显示原整数
#   movementDelay(+Jitter)   原 initialVelocityDelay/expansionDelay（+jitter），依续作改名，语义不变
#   minMovementThreshold     原 unknFloat/NULL2；仅 velocityType=EmitterMotion 有意义（emitter 速度  
#                            低于此阈值不施加给粒子）


VELOCITY3D_ATTR = Attribute(size=108, native_timl_axis=0, fields=[
    Int("typeFlag"),
    Enum("baseAxis", _AXIS_DIRECTION6, label_zh="基准轴"),
    Enum("rotOrder", _ROT_ORDER6, label_zh="旋转顺序"),
    Float("rotationX", label_zh="X 旋转"),
    Float("rotationXJitter", label_zh="X 旋转抖动"),
    Float("rotationY", label_zh="Y 旋转"),
    Float("rotationYJitter", label_zh="Y 旋转抖动"),
    Float("rotationZ", label_zh="Z 旋转"),
    Float("rotationZJitter", label_zh="Z 旋转抖动"),
    Float("speed", label_zh="初速度"),
    Float("speedJitter", label_zh="初速度偏差"),
    Float("speedCoef", label_zh="加速度"),
    Float("speedCoefJitter", label_zh="加速度偏差"),
    Float("velocityX", label_zh="X 基准点偏置"),
    Float("velocityY", label_zh="Y 基准点偏置"),
    Float("velocityZ", label_zh="Z 基准点偏置"),
    Float("divergenceX", label_zh="X 基准点伸缩"),
    Float("divergenceY", label_zh="Y 基准点伸缩"),
    Float("divergenceZ", label_zh="Z 基准点伸缩"),
    Enum("velocityType", _VELOCITY_TYPE, label_zh="速度类型"),
    Float("gravity", label_zh="重力"),
    Float("gravity_jitter", label_zh="重力抖动"),
    Int("movementDelay", label_zh="运动延迟"),
    Int("movementDelayJitter", label_zh="运动延迟抖动"),
    Int("gravityDelay", label_zh="重力延迟"),
    Int("gravityDelayJitter", label_zh="重力延迟抖动"),
    Float("minMovementThreshold", label_zh="最小移动阈值"),
])

EXTERN_VELOCITY3D_SCHEMA = VELOCITY3D_ATTR.schema
assert _schema_size(EXTERN_VELOCITY3D_SCHEMA) == 108, \
    f"EXTERN_VELOCITY3D_SCHEMA size mismatch: {_schema_size(EXTERN_VELOCITY3D_SCHEMA)}"

# Velocity3D block data_bytes schema (excludes type hash)
VELOCITY3D_SCHEMA = EXTERN_VELOCITY3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# EXTERNVELOCITY3D0 / EXTERNVELOCITY3D1 / EXTERNVELOCITY3D6（2026-07，纯统计推断）
#
# 这三个编号变体在主属性里没有同名对象可抄（跟 EXTERN_VELOCITY3D_SCHEMA 不是
# 同一类型），原先在 efxfile.py 里只标了字节数、字段全是占位 long unkn[N]。  
# 下面的逐字段 int/float 类型判定纯粹来自对官方语料的统计推断（无主属性、无
# 社区 .bt、无实机验证），方法：对每个 4 字节列，取该列在全部真实样本里的
# 原始值集合，按下列规则分类：
#   全部恒为 0                              → 判 'i'（保留位/未使用，按 int 编辑无害）  
#   八字节 CD 掩码占多数（0xCD 填充特征）    → 判 'i'（保留填充，同 reserved-fill 惯例）  
#   重新按 float32 解释后全部落在"正常浮点"区间
#     （排除 subnormal——小整数按 float 位模式重解释总落在 1e-38 以下的极小
#      denormal 区，那其实是"小整数误判成浮点"的假阳性，必须排除）           → 判 'f'  
#   其余（大数值/看似哈希或位掩码）          → 判 'i'
# 字段名一律 unkn{i}，不做语义命名——这批字段的具体含义未知，只是把"一坨
# opaque 字节"换成"可编辑的、类型大概率正确的独立字段"，比继续 opaque 更有用，
# 但语义置信度明显低于本文件其它有主属性/社区 .bt 支持的类型，需要实机验证。
# 语料样本量：V0=567 元素/51 文件（较可靠）、V1=73 元素/25 文件（尚可）、
# V6=15 元素/5 文件（偏少，谨慎对待）。V2(4元素)/V5(2元素)/V7(6元素) 样本
# 过少，类型判定不可靠，暂不落 schema，继续 opaque（见 extern_props.py 注释）。
# ─────────────────────────────────────────────────────────────────────────────

# EXTERNVELOCITY3D0：48B = 12 × int32（全部按 int 处理；语料里没有一列表现出
# 正常浮点特征——12 列里 6 列恒为 0，其余 6 列是小范围变化的整数，像是延迟/计数  
# 类参数，同 EXTERN_VELOCITY3D_SCHEMA 的 expansionDelay 等字段）。
EXTERN_VELOCITY3D0_SCHEMA = [(f'unkn{_i}', 'i') for _i in range(12)]
assert _schema_size(EXTERN_VELOCITY3D0_SCHEMA) == 48, \
    f"EXTERN_VELOCITY3D0_SCHEMA size mismatch: {_schema_size(EXTERN_VELOCITY3D0_SCHEMA)}"

# EXTERNVELOCITY3D1：361B = 90 × int32/float32（按上述统计规则逐列判定）+
# 末尾 1B（语料里恒为 0）。  
_V1_TYPES = (
    'iiiiiiiffiffffffififiifiifiiiiiiiififffififiiiiiifiiiifififffiiiiiffffiffiiiiiiiiiiiiiiiii'
)
EXTERN_VELOCITY3D1_SCHEMA = [
    (f'unkn{_i}', _t) for _i, _t in enumerate(_V1_TYPES)
] + [('unkn_tail', 'B')]
assert _schema_size(EXTERN_VELOCITY3D1_SCHEMA) == 361, \
    f"EXTERN_VELOCITY3D1_SCHEMA size mismatch: {_schema_size(EXTERN_VELOCITY3D1_SCHEMA)}"

# EXTERNVELOCITY3D6：80B = 20 × int32/float32。
_V6_TYPES = 'iiffiiiiiifffififiii'
EXTERN_VELOCITY3D6_SCHEMA = [(f'unkn{_i}', _t) for _i, _t in enumerate(_V6_TYPES)]
assert _schema_size(EXTERN_VELOCITY3D6_SCHEMA) == 80, \
    f"EXTERN_VELOCITY3D6_SCHEMA size mismatch: {_schema_size(EXTERN_VELOCITY3D6_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternEmitterShape3D schema  (88 B; full block = 92 B)
#
# 字段名对齐 RE Engine 续作 schema（同名 Emitter Shape 3D 类型，kagenocookie/RE-Engine-Lib）：
#   RangeX/Y/Z→rangeXYZ, ShapeType→shapeType, RangeDivideAxis→rangeDivideAxis,
#   LocalRotation→localRotationX/Y/Z, RotationOrder→rotationOrder, RotationCorrect→
#   rotationCorrect, RangeDivideHorizontalNum/VerticalNum→同名。
# radiusEnd/radiusOrigin 未对齐续作的 ScaleHorizontal/ScaleVertical（结构吻合，但那个名字
# 对"半径"这个实际功能不直观）；本仓库 scanAngleHorizontal/Vertical 是横/纵扫描角度，跟续作
# 同名的 ScaleHorizontal/ScaleVertical 语义未必相同。
# 续作的 RangeDivideNum（单轴细分）MHW 没有——MHW 早就是横纵双轴独立细分。
#
#   int   typeFlag                           4 B
#   XYZ   rangeXYZ(0)   6 floats            24 B  # 每轴 offset/size：offset=内边界（空腔），
#         size=生成壳层厚度，外边界=offset+size。用户 2026-07-30 实机测试（offset=20 配
#         size=0/10/20，壳厚分别为 0/空腔一半/与空腔等厚）确认 Box/Sphere/Cylinder 一致，
#         推翻旧的"Box/Sphere 是 min/max、只有 Cylinder 是 offset/size"分叉说；RE DTI
#         dump 的官方名 RangeMinX/RangeMaxX 与此行为对不上，以实测为准
#   int   shapeType：0=Box,1=Sphere,2=Cylinder,≥3=Point（非严格枚举，3/4/5 均为点）   4 B
#   int   rangeDivideAxis（原 unknEnum2）：仅 Box 生效，选沿哪个轴细分；不受
#         localRotation 影响                                                4 B
#   int   rotationCorrect（原 unknEnum3_0）：全形状生效，照搬续作 RotationCorrectType；
#         官方语料取值 [0,1,3,5,7] 不完全落在 0~4 内                            4 B
#   float localRotationX                    4 B  ─┐ 生成形状的总体旋转，全形状生效
#   float localRotationY                    4 B   │（RE Engine LocalRotation，Vector3）；
#   float localRotationZ                    4 B  ─┘ 不影响生成对象自身法线/切线
#   int   rotationOrder：全形状生效，与 TRANSFORM3D/RIBBON 共用 _TRANSFORM_ROT_ORDER   4 B
#   float scanAngleHorizontal（原 spawnAngleLimits）：仅 Sphere/Cylinder 生效，
#         横向扫描角度，180=半球/半环，360/0(等效)=整圆                          4 B
#   float scanAngleVertical（原 unkn3_f1）：仅 Sphere 生效，纵向扫描角度，180=上半球  4 B
#   int   rangeDivideHorizontalNum（原 spawnPerCycle）：仅 Sphere/Cylinder 生效，沿横向
#         等分；细分作用在 rangeXYZ+扫描角度定出的最终形状之上（先定形状再细分）      4 B
#   int   rangeDivideVerticalNum（原 spawnTotal）：全形状生效，沿纵向等分，0=连续铺满；
#         同上作用在最终形状之上；Box 下小值(1~3)表现为位掩码（1=边中点族/2=角族/
#         3=并集），大值(如16)细分方式待研究                                    4 B
#   float radiusEnd                         4 B  ─┐ 仅 Cylinder 生效。两者构成内外半径
#   float radiusOrigin                      4 B  ─┘ band，顺序互换结果一致（引擎按
#         min/max 取用，不看谁存在哪个字段）；实际半径 = rangeXYZ 该轴的外边界 × 该比例
#         （旧注释写作 "rangeXYZ.max"，rangeXYZ 改判 offset/size 后需复测确认基准取的是
#          外边界 offset+size 还是 size 本身）
#   int   unknBitmaskRadiusRelated：目前视为全形状生效。枚举 0~5，机制不明            4 B
#   int   unknFlag4：目前视为全形状生效。0/1，机制不明，多数为 1                     4 B
# Point(shapeType≥3) 例外：以上按形状的过滤规则对它一律不生效（全部字段照常显示）。
# Total: 4+24+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 4+24+15×4 = 88 B ✓
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_EMITTERSHAPE3D_ATTR = Attribute(size=88, fields=[
    Int("typeFlag"),  # 原 unkn0
    Raw("rangeXYZ", ('XYZ', 0), label_zh="生成范围"),  # 原 transform
    Enum("shapeType", ENUM_SHAPE_TYPE3D, label_zh="形状类型"),  # 原 patternControl
    Enum("rangeDivideAxis", ENUM_RANGE_DIVIDE_AXIS, label_zh="细分轴向"),  # 原 unknEnum2
    Enum("rotationCorrect", ENUM_ROTATION_CORRECT_TYPE, label_zh="旋转修正方式"),  # 原 unknEnum3_0
    Float("localRotationX", label_zh="局部旋转 X"),  # 原 trayectoryRotationX
    Float("localRotationY", label_zh="局部旋转 Y"),  # 原 trayectoryRotationY
    Float("localRotationZ", label_zh="局部旋转 Z"),  # 原 trayectoryRotationZ
    Enum("rotationOrder", _TRANSFORM_ROT_ORDER, label_zh="旋转顺序"),
    Float("scanAngleHorizontal", label_zh="横向扫描角度"),  # 原 scaleHorizontal/spawnAngleLimits
    Float("scanAngleVertical", label_zh="纵向扫描角度"),  # 原 scaleVertical/unkn3_f1
    Int("rangeDivideHorizontalNum", label_zh="横向等分数量"),  # 原 spawnPerCycle
    Int("rangeDivideVerticalNum", label_zh="纵向等分数量"),  # 原 spawnTotal
    Float("radiusEnd", label_zh="结束半径"),
    Float("radiusOrigin", label_zh="起始半径"),
    Int("unknBitmaskRadiusRelated"),
    Bool("unknFlag4"),
])
EXTERN_EMITTERSHAPE3D_SCHEMA = EXTERN_EMITTERSHAPE3D_ATTR.schema
assert _schema_size(EXTERN_EMITTERSHAPE3D_SCHEMA) == 88, \
    f"EXTERN_EMITTERSHAPE3D_SCHEMA size mismatch: {_schema_size(EXTERN_EMITTERSHAPE3D_SCHEMA)}"

# EmitterShape3D block data_bytes schema (excludes type hash)
EMITTERSHAPE3D_SCHEMA = EXTERN_EMITTERSHAPE3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# ExternScaleAnim schema  (76 B; full block = 80 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0                              4 B
#   float animationSpeed                4 B
#   long  NULL                               4 B  
#   float scaleSpeed                         4 B
#   float scaleSpeedJitter                   4 B
#   float unkn1[2]                           8 B
#   float scaleAccel                         4 B
#   float scaleAccelJitter                   4 B
#   float unkn2[8]                          32 B
#   int   delay                              4 B
#   int   delayJitter                        4 B
# Total: 4+4+4+4+4+8+4+4+32+4+4 = 76 B ✓
# ─────────────────────────────────────────────────────────────────────────────

# 社区实测（《世界特效注释解析》，验证版）：原模板对 SCALEANIM 误读很多，此为正确语义。
# 两阶段缩放：初始整体扩散（速度+加速度）+ 播放过程中的逐轴缩放（X/Y/Z 各 速度/加速度 + 偏差）。
# 字段宽度与原版完全一致（仅拆分 unkn1=('f',2)→X、unkn2=('f',8)→Y/Z，重命名，不改类型/字节）。
EXTERN_SCALEANIM_ATTR = Attribute(size=76, fields=[
    Int("typeFlag"),  # 原 unkn0
    Float("initialScaleSpeed", label_zh="初始扩散速度"),  # 初始扩散速度（原 animationSpeed）TIML DT 0xC24DF97C("SizeScalarAdd") 已确认
    # 原 unknFloat/NULL：紧跟 initialScaleSpeed、恰好是它缺的 Jitter 搭档（该字段本身
    # 约 30% 非零，clean 小数如 0.02/0.04/0.1/0.2，符合 jitter 数值特征），按 static/random
    # 配对约定改名，未实机验证。
    Float("initialScaleSpeedJitter", label_zh="初始扩散速度抖动"),

    Float("initialScaleAccel", label_zh="初始扩散加速度"),  # 初始扩散加速度（原 scaleSpeed）
    Float("initialScaleAccelJitter", label_zh="初始扩散加速度抖动"),  # 原 scaleSpeedJitter
    Float("scaleSpeedX", label_zh="X 缩放速度"),  # X 轴缩放速度（原 unkn1[0]）TIML DT 0x909EC047("SizeXAdd") 已确认
    Float("scaleSpeedXJitter", label_zh="X 缩放速度抖动"),  # 原 unkn1[1]
    Float("scaleAccelX", label_zh="X 缩放加速度"),  # X 轴缩放加速度（原 scaleAccel）
    Float("scaleAccelXJitter", label_zh="X 缩放加速度抖动"),  # 原 scaleAccelJitter
    Float("scaleSpeedY", label_zh="Y 缩放速度"),  # Y 轴缩放速度（原 unkn2[0]）TIML DT 0x2822A722("SizeYAdd") 已确认
    Float("scaleSpeedYJitter", label_zh="Y 缩放速度抖动"),  # unkn2[1]
    Float("scaleAccelY", label_zh="Y 缩放加速度"),  # Y 轴缩放加速度 unkn2[2]
    Float("scaleAccelYJitter", label_zh="Y 缩放加速度抖动"),  # unkn2[3]
    Float("scaleSpeedZ", label_zh="Z 缩放速度"),  # Z 轴缩放速度 unkn2[4]（仅模型有 Z）TIML DT 0x3A9708CC("SizeZAdd") 已确认
    Float("scaleSpeedZJitter", label_zh="Z 缩放速度抖动"),  # unkn2[5]
    Float("scaleAccelZ", label_zh="Z 缩放加速度"),  # Z 轴缩放加速度 unkn2[6]
    Float("scaleAccelZJitter", label_zh="Z 缩放加速度抖动"),  # unkn2[7]
    Int("animUpdateStart", label_zh="动画更新开始时间"),  # 动画更新开始时间（原 delay）
    Int("animUpdateStartJitter", label_zh="动画更新开始时间抖动"),  # 原 delayJitter
])
EXTERN_SCALEANIM_SCHEMA = EXTERN_SCALEANIM_ATTR.schema
assert _schema_size(EXTERN_SCALEANIM_SCHEMA) == 76, \
    f"EXTERN_SCALEANIM_SCHEMA size mismatch: {_schema_size(EXTERN_SCALEANIM_SCHEMA)}"

SCALEANIM_SCHEMA = EXTERN_SCALEANIM_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# FadeByDepth schema  (data_bytes = 20 B; full block = 24 B)
#
# （2026-07-23）：跟摄像机距离相关，与"角度"/"裁剪"这两个原 BT
# 命名的字面含义都对不上，是两段独立的距离渐隐区间：
#   - 近端：低于 nearFadeInStart 硬消失；nearFadeInStart~nearFadeInEnd 之间
#     软过渡淡入；高于 nearFadeInEnd 全程可见。两者同置 0 时近端渐隐整体关闭
#     （不管多近都不消失），实机验证。
#   - 远端：低于 farFadeOutStart 全程可见；farFadeOutStart~farFadeOutEnd 之间
#     软过渡淡出；高于 farFadeOutEnd 硬消失。farFadeOutStart=0/farFadeOutEnd=500
#     实机验证：约 400 距离处已接近不可见，拉近变清晰，与该模型吻合。
#   两段区间彼此独立（近端清零不影响远端），全语料 44321 块统计 fadeOutStart/
#   fadeOutEnd 会成对打到 ~1e10 当"关闭远端渐隐"的哨兵值用，近端两个字段则
#   从未见到同等量级的哨兵值。
# 原 BT (EFX_Subtypes.bt) 命名（已被推翻，仅留存查）：
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   float viewAngleLimit（原名，实为近端硬消失阈值，与角度无关）      4 B
#   float clipMin（原名，实为近端淡入终点）                          4 B
#   float fadeStart（原名，实为远端淡出起点，命名恰好蒙对）           4 B
#   float clipMax（原名，实为远端硬消失阈值，命名恰好蒙对）          4 B
# data_bytes: 4+4×4 = 20 B ✓
# ─────────────────────────────────────────────────────────────────────────────

FADEBYDEPTH_ATTR = Attribute(size=20, fields=[
    Int("typeFlag"),  # 原 unkn0
    Float("nearFadeInStart", label_zh="近处淡入起点"),
    Float("nearFadeInEnd", label_zh="近处淡入终点"),
    Float("farFadeOutStart", label_zh="远处淡出起点"),
    Float("farFadeOutEnd", label_zh="远处淡出终点"),
])
FADEBYDEPTH_SCHEMA = FADEBYDEPTH_ATTR.schema
assert _schema_size(FADEBYDEPTH_SCHEMA) == 20, \
    f"FADEBYDEPTH_SCHEMA size mismatch: {_schema_size(FADEBYDEPTH_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternRgbFire schema  (112 B; full block = 116 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0                              4 B
#   XYZ   color1(2)   ubyte×3+pad            4 B
#   float brightness1                        4 B
#   XYZ   color2(2)   ubyte×3+pad            4 B
#   float brightness2                        4 B
#   float unkn4                              4 B
#   float brightness3                        4 B
#   float brightness4                        4 B
#   ColorParam color1Param   10×int         40 B
#   ColorParam color2Param   10×int         40 B
# Total: 4+4+4+4+4+4+4+4+40+40 = 112 B ✓
#
# ColorParam decoded as flat named fields with prefix to avoid collision.
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_RGBFIRE_ATTR = Attribute(size=112, fields=[
    Int("typeFlag"),  # 原 unkn0
    Raw("fireColor", ('XYZ', 2), label_zh="火焰色"),  # 原 color1；TIML DT 0x39A1E557("FireColor") 已确认
    Float("brightness1", label_zh="亮度1"),
    Raw("smokeColor", ('XYZ', 2), label_zh="烟雾色"),  # 原 color2；TIML DT 0x5A8C6820("SmokeColor") 已确认
    Float("brightness2", label_zh="亮度2"),  # TIML DT 0x9F1E012E("ColorRate") 已确认
    Float("unkn4"),
    Float("brightness3", label_zh="亮度3"),
    Float("brightness4", label_zh="亮度4"),
    # ColorParam fireColorParam (10 ints)：fireColor 的生命期时序块。
    # 内部名对齐官方 DTI（nEffect::MhEffectDecalBehavior 的 fire 段）：
    #   useLife←mUseFireLife / appearFrame(+Jitter)←mFireAppearFrame(range) /
    #   keepFrame←mFireKeepFrame / vanishFrame←mFireVanishFrame /
    #   lighting←mFireLighting(原 unkn7) / lifeType←mFireLifeType(原 unkn8)。
    # 三个 range 字段各占两格（值+抖动），正是官方 range 类型的字节展开。
    # ⚠ 前缀 fireColorParam_/smokeColorParam_ 保留：color_fields.py 靠它把整块
    #   归类为「颜色相关」（Color Editor 模式过滤依据）。
    # UI 措辞：淡入/持续时间/淡出三对沿用旧称不动；useLife/lighting/lifeType 三项
    #   因原本无中文标签（界面显示派生英文名 "…unkn7"）故直接给正式标签。
    Bool("fireColorParam_useLife", label_en="Use Fire Life", label_zh="启用火焰生命期"),
    Int("fireColorParam_appearFrame", label_zh="火焰色 淡入"),
    Int("fireColorParam_appearFrameJitter", label_zh="火焰色 淡入抖动"),
    Int("fireColorParam_keepFrame", label_zh="火焰色 持续时间"),
    Int("fireColorParam_keepFrameJitter", label_zh="火焰色 持续时间抖动"),
    Int("fireColorParam_vanishFrame", label_zh="火焰色 淡出"),
    Int("fireColorParam_vanishFrameJitter", label_zh="火焰色 淡出抖动"),
    Bool("fireColorParam_lighting", label_en="Fire Lighting", label_zh="火焰受光照"),
    Int("fireColorParam_lifeType", label_en="Fire Life Type", label_zh="火焰生命期模式"),
    # unkn9：官方 fire 段只有 9 格、我们有 10 格，这一格没有对应官方名。取值
    # {0,1,2,7,8,9}，按 int32 位重解读成 float 全为 0（次正规噪声），确认是整数。
    Int("fireColorParam_unkn9"),
    # ColorParam smokeColorParam (10 ints)：smokeColor 的生命期时序块，与 fire 段同构
    # （mUseSmokeLife / mSmokeAppearFrame / KeepFrame / VanishFrame / mSmokeLighting /
    # mSmokeLifeType）。
    Bool("smokeColorParam_useLife", label_en="Use Smoke Life", label_zh="启用烟雾生命期"),
    Int("smokeColorParam_appearFrame", label_zh="烟雾色 淡入"),
    Int("smokeColorParam_appearFrameJitter", label_zh="烟雾色 淡入抖动"),
    Int("smokeColorParam_keepFrame", label_zh="烟雾色 持续时间"),
    Int("smokeColorParam_keepFrameJitter", label_zh="烟雾色 持续时间抖动"),
    Int("smokeColorParam_vanishFrame", label_zh="烟雾色 淡出"),
    Int("smokeColorParam_vanishFrameJitter", label_zh="烟雾色 淡出抖动"),
    Bool("smokeColorParam_lighting", label_en="Smoke Lighting", label_zh="烟雾受光照"),
    Int("smokeColorParam_lifeType", label_en="Smoke Life Type", label_zh="烟雾生命期模式"),
    Int("smokeColorParam_unkn9"),
])
EXTERN_RGBFIRE_SCHEMA = EXTERN_RGBFIRE_ATTR.schema
assert _schema_size(EXTERN_RGBFIRE_SCHEMA) == 112, \
    f"EXTERN_RGBFIRE_SCHEMA size mismatch: {_schema_size(EXTERN_RGBFIRE_SCHEMA)}"

RGBFIRE_SCHEMA = EXTERN_RGBFIRE_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# RotateAnim schema  (data_bytes = 80 B; full block = 84 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0_0                            4 B  ← 轴掩码（bitmask：bit0=X, bit1=Y, bit2=Z）
#   int   unkn0_1                            4 B  ← 旋转模式（0/1=billboard平面旋转；2/3=启用自旋速度）
#   long  NULL[2]                            8 B  
#   XYZ   spin_velocity(0)   6 floats       24 B
#   float unkn1_0                            4 B
#   float unkn1_1                            4 B
#   float momentum_retention                 4 B
#   XYZ   spin_acceleration(0)              24 B
#   float unkn1_2                            4 B
# data_bytes: 8+8+24+12+24+4 = 80 B ✓
# ─────────────────────────────────────────────────────────────────────────────

ROTATEANIM_ATTR = Attribute(size=80, fields=[
    Bitmask("spinAxisMask", BITS_SPIN_AXIS),  # 原 unkn0_0；轴掩码 bitmask：bit0=X, bit1=Y, bit2=Z（已确认，非 typeFlag 候选）
    # rotationModeMask（原 unknBitmask0_1）：用户实机确认 4 态——0=仅平面旋转系(billboardRotation+
    # billboardRotationCoef)；1=同上+随机正反向；2=仅自旋速度系(spin_velocity+spinSpeedCoef+
    # 已废弃的 momentum_retention 概念)；3=同上+随机正反向(每轴独立随机)。
    Enum("rotationModeMask", ENUM_ROTATION_MODE, label_zh="旋转模式"),
    # 社区实测+用户实机(2026-07)：这两个专门控制 BILLBOARD3D 平面类的旋转，模板原标为 int，实为 float。
    # billboardRotation + billboardRotationJitter(原 billboardRotationSpeed) 是一组 static/random。
    Float("billboardRotation", label_zh="平面旋转"),
    Float("billboardRotationJitter", label_zh="平面旋转抖动"),  # 原 billboardRotationSpeed，实为 billboardRotation 的 random 分量
    Raw("spin_velocity", ('XYZ', 0), label_zh="自旋速度"),
    # billboardRotationCoef + Jitter(原 unkn1_0/unkn1_1)：billboardRotation 的加速度 static/random，
    Float("billboardRotationCoef", label_zh="平面旋转加速度"),  # 原 unkn1_0
    Float("billboardRotationCoefJitter", label_zh="平面旋转加速度抖动"),  # 原 unkn1_1
    # 用户实机(2026-07-26)：原 momentum_retention + spin_acceleration(XYZ) + unknEnum1_2 整体错位一格。
    # 全语料实测证实：spinSpeedCoefX/Y/Z 的 static 分布集中在 0.9~1.0，random 分布 96%+ 为 0（偶尔
    # 干净小数）；原 spin_acceleration.random_z 当 float 解读 100% 恒为 0.0（denormal 假象），当 int32  
    # 解读呈现 5/10/15/20/30/100/512 等干净帧数刻度，与 unknEnum1_2（帧数刻度一致）组成 static/random
    # 一对，改名 rotateDelayStart(+Jitter)，字段类型由 float 改为 int。
    Float("spinSpeedCoefX", label_zh="自旋加速度 X"),  # 原 momentum_retention
    Float("spinSpeedCoefXJitter", label_zh="自旋加速度 X 抖动"),  # 原 spin_acceleration.fixed_x
    Float("spinSpeedCoefY", label_zh="自旋加速度 Y"),  # 原 spin_acceleration.random_x
    Float("spinSpeedCoefYJitter", label_zh="自旋加速度 Y 抖动"),  # 原 spin_acceleration.fixed_y
    Float("spinSpeedCoefZ", label_zh="自旋加速度 Z"),  # 原 spin_acceleration.random_y
    Float("spinSpeedCoefZJitter", label_zh="自旋加速度 Z 抖动"),  # 原 spin_acceleration.fixed_z
    Int("rotateDelayStart", label_zh="旋转延迟起始帧"),  # 原 spin_acceleration.random_z（float 恒 0.0，实为 int 帧数）
    Int("rotateDelayStartJitter", label_zh="旋转延迟起始帧抖动"),  # 原 unknEnum1_2
])
ROTATEANIM_SCHEMA = ROTATEANIM_ATTR.schema
assert _schema_size(ROTATEANIM_SCHEMA) == 80, \
    f"ROTATEANIM_SCHEMA size mismatch: {_schema_size(ROTATEANIM_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# AlphaCorrection schema  (data_bytes = 20 B; full block = 24 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   float unkn1                              4 B
#   float transparentness                    4 B
#   float unkn3 (原 NULL，BT 误标，实为 float)  4 B  
#   int   unkn2                              4 B
# data_bytes: 5×4 = 20 B ✓
# ─────────────────────────────────────────────────────────────────────────────

ALPHACORRECTION_ATTR = Attribute(size=20, fields=[
    Int("unkn0"),
    Float("lowPass", label_zh="低通阈值"),  # 原 unkn1 / alpha_clip_threshold；硬阈值裁切(类 PS Threshold)：<此值的 alpha 直接归 0，0=不裁
    Float("contrast_gamma", label_zh="对比度/伽马修正"),  # 原 transparentness；对比度/伽马修正，无上限：越大边缘(低/中alpha)越快变透明、核心保留
    Float("unkn3"),  # 原 NULL（int）；BT 模板误标，实为 float，语义未确认  
    Bool("unknFlag2"),
])
ALPHACORRECTION_SCHEMA = ALPHACORRECTION_ATTR.schema
assert _schema_size(ALPHACORRECTION_SCHEMA) == 20, \
    f"ALPHACORRECTION_SCHEMA size mismatch: {_schema_size(ALPHACORRECTION_SCHEMA)}"


LUMINANCEBLEED_ATTR = Attribute(size=16, fields=[
    Int("unkn0"),
    Float("bleed"),
    Float("colorScaler"),
    Float("texelScaler"),
])
LUMINANCEBLEED_SCHEMA = LUMINANCEBLEED_ATTR.schema
assert _schema_size(LUMINANCEBLEED_SCHEMA) == 16, \
    f"LUMINANCEBLEED_SCHEMA size mismatch: {_schema_size(LUMINANCEBLEED_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Refraction schema  (data_bytes = 12 B; full block = 16 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   int   pixelNormalOffset                  4 B
#   int   unkn2                              4 B
# data_bytes: 3×4 = 12 B ✓
# ─────────────────────────────────────────────────────────────────────────────

REFRACTION_ATTR = Attribute(size=12, fields=[
    Int("typeFlag"),  # 原 unkn0
    Enum("pixelNormalOffset", ENUM_REFRACTION_OFFSET, label_zh="像素法线偏移"),
    Float("seeThroughBlend", label_zh="透视混合系数"),  # 原 unkn2
])
REFRACTION_SCHEMA = REFRACTION_ATTR.schema
assert _schema_size(REFRACTION_SCHEMA) == 12, \
    f"REFRACTION_SCHEMA size mismatch: {_schema_size(REFRACTION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Noise schema  (data_bytes = 44 B; full block = 48 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   long  NULL                               4 B  
#   int   section_length                     4 B
#   long  spacer                             4 B  
#   float main_axis_speed                    4 B
#   float main_axis_speed_jitter            4 B
#   float teleport_radius                   4 B
#   float teleport_radius_jitter            4 B
#   float main_axis_speed2                  4 B
#   float main_axis_speed2_jitter           4 B
#   float teleport_radius2                  4 B
#   float teleport_radius2_jitter           4 B
# data_bytes: 4+4+4+8×4 = 44 B ✓
# main_axis_speed_jitter/2（原 secondary_axis_speed/2）、teleport_radius_jitter/2
# （原 smooth_radius_randomized/2）实测确认（2026-07-11）：分别是前一个字段的 jitter，
# 不是独立的"次轴速度"/"平滑半径随机"字段。
# ─────────────────────────────────────────────────────────────────────────────

NOISE_ATTR = Attribute(size=44, fields=[
    Int("typeFlag"),  # 原 NULL（名字错，语料 35 种取值，非空）  
    Int("section_length", label_zh="段长度"),
    Int("spacer"),
    Float("main_axis_speed", label_zh="主轴速度"),
    Float("main_axis_speed_jitter", label_zh="主轴速度抖动"),  # 原 secondary_axis_speed
    Float("teleport_radius", label_zh="传送半径"),
    Float("teleport_radius_jitter", label_zh="传送半径抖动"),  # 原 smooth_radius_randomized
    Float("main_axis_speed2", label_zh="主轴速度2"),
    Float("main_axis_speed2_jitter", label_zh="主轴速度2抖动"),  # 原 secondary_axis_speed2
    Float("teleport_radius2", label_zh="传送半径2"),
    Float("teleport_radius2_jitter", label_zh="传送半径2抖动"),  # 原 smooth_radius_randomized2
])
NOISE_SCHEMA = NOISE_ATTR.schema
assert _schema_size(NOISE_SCHEMA) == 44, \
    f"NOISE_SCHEMA size mismatch: {_schema_size(NOISE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Guide schema  (data_bytes = 104 B; full block = 108 B)
#
# BT (EFX_Subtypes.bt):
#   float initialPosition/Jitter(8) + speed/Jitter(8) + accel/Jitter(8) +
#   innerRadius/Jitter(8) + outerRadius/Jitter(8) = 10 floats = 40 B
#   float restitutionDelay/Jitter(8) + restitutionEcc/Jitter(8) +
#   restitutionElasticity/Jitter(8) = 6 floats = 24 B
#   float unkn16-19 (4 floats = 16 B) + unkn20-22 (3 floats = 12 B)
#   int int_unkn1[2] (8 B) + float float_unkn2[3] (12 B)
# Total: 40+24+16+12+8+12 = 112 B?  But _known_attr_size returns 108-4=104.
# From efxfile.py: 4+40+16+16+12+8+12 = 108 full, so data_bytes = 104.
# Schema:
#   10 floats (initialPos/Jitter, speed/Jitter, accel/Jitter,
#              innerRadius/Jitter, outerRadius/Jitter) = 40 B
#   6 floats (restitutionDelay/Jitter, restitutionEcc/Jitter,
#             restitutionElasticity/Jitter) = 24 B
#   4 floats (unkn16-unkn19) = 16 B
#   3 floats (unkn20-unkn22) = 12 B
#   2 ints   (int_unkn1[2]) = 8 B
#   3 floats (float_unkn2[3]) = 12 B
# Total: 40+24+16+12+8+12 = 112 B  ← but expected is 104 B
# Actual: efxfile.py says 4 + 40 + 16 + 16 + 12 + 8 + 12 = 108 full = 104 data
# That's: 40 + 16 + 16 + 12 + 8 + 12 = 104 → only 6 restitution floats missing
# Counting BT fields: 23 floats + 2 ints + 3 floats = 26 floats + 2 ints = 112 B
# But efxfile computed 108. Let's trust the efxfile.py value:
#   10 floats = 40 B
#   4 floats = 16 B  (restitution: delay/j, ecc/j — only 4 not 6?)
# Actually from efxfile.py: 4+40+16+16+12+8+12 = 108:
#   type(4) + 10floats(40) + 4floats(16) + 4floats(16) + 3floats(12) + 2ints(8) + 3floats(12)
# = 4+40+16+16+12+8+12 = 108 full, 104 data_bytes
# ─────────────────────────────────────────────────────────────────────────────

GUIDE_ATTR = Attribute(size=112, fields=[
    Float("initialPosition", label_zh="初始位置"),
    Int("initialPositionJitter", label_zh="初始位置抖动"),
    Float("speed", label_zh="初速度"),
    Float("speedJitter", label_zh="初速度偏差"),
    Float("accel", label_zh="加速度"),
    Float("accelJitter", label_zh="加速度抖动"),
    Float("innerRadius", label_zh="内半径"),
    Float("innerRadiusJitter", label_zh="内半径抖动"),
    Float("outerRadius", label_zh="外半径"),
    Float("outerRadiusJitter", label_zh="外半径抖动"),
    # efxfile.py: 4+40+40+12+8+12 = 116 full → data_bytes = 112
    # (EFX_Crimson.bt Guide: type + 23 floats + int[2] + float[3])
    # restitution 组共 10 floats（40B）
    Float("restitutionDelay", label_zh="回弹延迟"),
    Float("restitutionDelayJitter", label_zh="回弹延迟抖动"),
    Float("restitutionEccentricity", label_zh="回弹偏心率"),
    Float("restitutionEccentricityJitter", label_zh="回弹偏心率抖动"),
    Float("restitutionElasticity", label_zh="回弹弹性"),
    Float("restitutionElasticityJitter", label_zh="回弹弹性抖动"),
    Float("unkn16"),
    Float("unkn17"),
    Float("unkn18"),
    Float("unkn19"),
    # unkn20/21/22 共 3 floats (12B)
    Float("unknFixed20"),
    Float("unkn21"),
    Float("unkn22"),
    # 2 ints (8B)
    Int("int_unkn1_0"),
    Int("int_unkn1_1"),
    # 3 floats (12B)
    Float("float_unkn2_0"),
    Float("float_unkn2_1"),
    Float("float_unkn2_2"),
])
GUIDE_SCHEMA = GUIDE_ATTR.schema
assert _schema_size(GUIDE_SCHEMA) == 112, \
    f"GUIDE_SCHEMA size mismatch: {_schema_size(GUIDE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PlEmissive schema  (data_bytes = 76 B; full block = 80 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1(4) + ubyte body_p(1) + ubyte wp_p(1) + short NULL(2) +  
#   int epv_color_slot(4) + XYZ color(2)(4) + float unkn4(4) + float area[2](8) +
#   float bright(4) + int area_of_aura(4) + float radii[3](12) + float unkn5[5](20)
# = 8+4+4+4+4+8+4+4+12+20 = 76 B ✓
# ─────────────────────────────────────────────────────────────────────────────

PLEMISSIVE_ATTR = Attribute(size=76, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("unknEnum0_1"),
    Float("unkn1"),
    Byte("body_p", label_zh="关联 Body"),
    Byte("wp_p", label_zh="关联武器"),
    Short("NULL"),
    Int("epv_color_slot", label_zh="EPV 颜色槽"),
    Raw("color", ('XYZ', 2), label_zh="颜色"),
    Float("unkn4"),
    Raw("area", ('f', 2), label_zh="区域"),
    Float("bright", label_zh="亮度"),
    Int("area_of_aura", label_zh="光环范围"),
    Float("radii_effect_unkn0"),
    Float("radii_effect_unkn1"),
    Float("radii_effect_unkn2"),
    Float("unknFixed5_0"),
    Float("unkn5_1"),
    Float("unkn5_2"),
    Float("unknFixed5_3"),
    Float("unknFixed5_4"),
])
PLEMISSIVE_SCHEMA = PLEMISSIVE_ATTR.schema
assert _schema_size(PLEMISSIVE_SCHEMA) == 76, \
    f"PLEMISSIVE_SCHEMA size mismatch: {_schema_size(PLEMISSIVE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ParentEmissive schema  (data_bytes = 72 B; full block = 76 B)
#
# BT (EFX_Subtypes.bt):
#   long unkn0(4) + long unkn1(4) + float unkn2(4) + long unkn3(4) +
#   XYZ color(2)(4) + float brightness(4) + float rimParam[3](12) +
#   long unkn4(4) + float blendParam[3](12) + float unkn8[5](20)
# = 4+4+4+4+4+4+12+4+12+20 = 72 B ✓
# ─────────────────────────────────────────────────────────────────────────────

PARENTEMISSIVE_ATTR = Attribute(size=72, fields=[
    Int("typeFlag"),  # 原 unkn0
    Int("unknEnum1"),
    Float("unkn2"),
    Int("unknEnum3"),
    Raw("color", ('XYZ', 2), label_zh="颜色"),
    Float("brightness", label_zh="亮度"),
    Raw("rimParam", ('f', 3), label_zh="边缘光参数"),
    Int("unknEnum4"),
    Raw("blendParam", ('f', 3), label_zh="混合参数"),
    Float("unknFixed8_0"),
    Float("unkn8_1"),
    Float("unkn8_2"),
    Float("unknFixed8_3"),
    Float("unknFixed8_4"),
])
PARENTEMISSIVE_SCHEMA = PARENTEMISSIVE_ATTR.schema
assert _schema_size(PARENTEMISSIVE_SCHEMA) == 72, \
    f"PARENTEMISSIVE_SCHEMA size mismatch: {_schema_size(PARENTEMISSIVE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PlSnow schema  (data_bytes = 84 B; full block = 88 B)
#
# ⚠ 2026-07 修：原 schema 漏掉 BT 描述的最后一个字段 craquelure_smoothing_threshold  
# （20 项写成了 19 项，注释自己都写出了"84"却在结尾错算成"80"）——导致 PLSNOW
# 恒少算 4B，凡是 entry 里 PLSNOW 后面紧跟别的属性/entry 的文件，从这里起
# 全部错位 4 字节，最终整个 main 段解析失败退化到 main_opaque（语料实测：
# 6 个 DEGRADED 文件里至少这一个根因已确认，修复后 roundtrip.py --all 的
# DEGRADED 计数下降）。
#
# BT (EFX_Subtypes.bt)：
#   int unkn0[2](8) + long spacer(4) + int body_part_id(4) + int weapon_id(4) +  
#   colour color(4) + int epvcolorslot(4) + int alpha_effect(4) +
#   float normal_map_strength(4) + float alpha_threshold(4) +
#   float unkn4_0(4) + float unkn4_1(4) + long unkn5(4) +
#   float roughness_multiplier(4) + float metallicness_multiplier(4) +
#   float subsurface_multipler(4) + float unkn6_0(4) +
#   float craquelure_effect_diffumination(4) + float craquelure_threshold(4) +
#   float unkn6_1(4) + float craquelure_smoothing_threshold(4)
# = unkn0[2](8) + 19×4B(76) = 84 B data_bytes ✓（20 个 4B 字段，非 19 个）
# ─────────────────────────────────────────────────────────────────────────────

PLSNOW_ATTR = Attribute(size=84, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("unknFixed0_1"),  # int unkn0[2] = 8 B
    Int("spacer"),
    Int("body_part_id", label_zh="身体部位 ID"),
    Int("weapon_id", label_zh="武器 ID"),
    Raw("color", 'colour', label_zh="颜色"),
    Int("epvcolorslot", label_zh="EPV 颜色槽"),
    Int("alpha_effect", label_zh="透明度效果"),
    Float("normal_map_strength", label_zh="法线贴图强度"),
    Float("alpha_threshold", label_zh="透明度阈值"),
    Float("unkn4_0"),
    Float("unkn4_1"),
    Int("unkn5"),
    Float("roughness_multiplier", label_zh="粗糙度倍率"),
    Float("metallicness_multiplier", label_zh="金属度倍率"),
    Float("subsurface_multipler", label_zh="次表面倍率"),
    Float("unkn6_0"),
    Float("craquelure_effect_diffumination", label_zh="裂纹效果扩散"),
    Float("craquelure_threshold", label_zh="裂纹阈值"),
    Float("unkn6_1"),
    Float("craquelure_smoothing_threshold"),
])
PLSNOW_SCHEMA = PLSNOW_ATTR.schema
assert _schema_size(PLSNOW_SCHEMA) == 84, \
    f"PLSNOW_SCHEMA size mismatch: {_schema_size(PLSNOW_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PtCollision schema  (data_bytes = 112 B; full block = 116 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn00-07 (8 ints = 32 B) + float unkn1[3](12) + int unkn2[2](8) +
#   float bounceElasticity(4)+j(4)+Mult(4)+horizontal(4)+unkn34-37(16) +
#   int unkn38(4) + int unkn4[2](8) + int ieIndex(4) + int unkn6[3](12)
# = 32+12+8+32+4+8+4+12 = 112 B ✓
#
# unkn2[2] 的第一个 int（原 unknEnum2_0→bounceCountLimit）2026-07-31 用户实机测试确认为
# bounceCount：反弹次数，如=2则反弹2次，第3次触地触发 physicsEnum 收尾行为（不再是纯粹未知枚举）。
# 语料分布 0~5 集中(98.8%)，个别到 20/25，与"反弹次数"语义吻合。
#
# 2026-07-31 用户实机测试确认 impactPlayTriggerMode 组（原 unkn38/unknBitmask4_0/unknFlag4_1）：
# ieIndex 引用的 Play 在反弹序列中的触发时机，行为随 physicsEnum 而不同——physicsEnum=0（穿透）
# 时一次性判定全部反弹，其余 physicsEnum 值下逐次反弹判定：
#   0=每次触地都触发；
#   1=前 N 次触地触发，N 由 impactPlayTriggerCount ± impactPlayTriggerCountJitter 决定；
#   2=仅最后一次触地触发。
# impactPlayTriggerCountJitter（原疑似 impactPlayTriggerCountRandom 布尔开关）2026-07-31
# 用户实机测试确认实为 impactPlayTriggerCount 的 jitter，非开关，已并入该组按 value+jitter 惯例改名。
# ─────────────────────────────────────────────────────────────────────────────

PTCOLLISION_ATTR = Attribute(size=112, fields=[
    Int("typeFlag"),  # 原 unkn00
    Enum("physicsEnum", ENUM_COLLISION_PHYSICS, label_zh="物理类型"),
    Int("unkn02"),
    Int("unkn03"),
    Int("unknEnum04"),
    Int("unknFixed05"),
    # 2026-07-31 用户实机测试确认：碰撞面沿 -Y 轴的投影偏移，正值向下偏移、负值向上偏移。
    Float("projectionOffset", label_zh="投影偏移"),  # 原 unkn06
    # 2026-07-31 用户实机测试：固定同一个值不产生不同表现（排除 jitter），但不同取值会
    # 产生"无变化"/"产生水平碰撞"/"抬高碰撞水平面"/"改变 action 触发点"等多种质变效果——
    # 疑似跨越不同数值区间触发不同行为模式，非线性距离参数。具体分段边界未测。
    Float("projectionDist", label_zh="投影距离"),  # 原 unkn07
    Float("unkn1_0"),  # 2026-07-31 用户实机测试排除：不是碰撞判定 radius
    Float("unkn1_1"),  # 2026-07-31 用户实机测试排除：不是碰撞判定 radius
    Float("unkn1_2"),  # 2026-07-31 用户实机测试排除：不是碰撞判定 radius
    Int("bounceCount", label_zh="反弹次数"),  # 原 unknEnum2_0→bounceCountLimit，2026-07-31 用户建议去掉"上限"（配合 physicsEnum 收尾行为，反弹满该次数后触发对应收尾）
    Int("bounceCountJitter", label_zh="反弹次数抖动"),  # 原 unknEnum2_1→bounceCountLimitJitter，2026-07-31 用户实机测试确认为 bounceCount 的抖动
    Float("bounceElasticity", label_zh="弹跳弹性"),
    Float("bounceElasticityJitter", label_zh="弹跳弹性抖动"),
    # 2026-07-31 用户实机测试确认：跟 bounceElasticity 效果完全相同，两者是叠加关系（非倍率，维持原名）。
    Float("bounceElasticityMultiplier", label_zh="弹跳弹性倍率"),
    Float("horizontalBounce", label_zh="水平弹跳"),
    Float("unkn34"),
    Float("unkn35"),
    Float("unkn36"),
    Float("unkn37"),
    Enum("impactPlayTriggerMode", ENUM_IMPACT_PLAY_TRIGGER_MODE, label_zh="触地触发模式"),  # 原 unknEnum38
    Int("impactPlayTriggerCount", label_zh="触地触发次数"),  # 原 unknBitmask4_0，非位掩码——实测是次数 N，配合 impactPlayTriggerMode=1 使用
    Int("impactPlayTriggerCountJitter", label_zh="触地触发次数抖动"),  # 原 unknFlag4_1→impactPlayTriggerCountRandom，2026-07-31 用户实机测试确认为 impactPlayTriggerCount 的 jitter
    Int("ieIndex", label_zh="碰撞触发 Play"),
    Int("unknEnum6_0"),
    Int("unknEnum6_1"),
    Int("unknFixed6_2"),
])
PTCOLLISION_SCHEMA = PTCOLLISION_ATTR.schema
assert _schema_size(PTCOLLISION_SCHEMA) == 112, \
    f"PTCOLLISION_SCHEMA size mismatch: {_schema_size(PTCOLLISION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# RandomFix schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[10]  (10 × 4 = 40 B)
#
# 用户对照 RE Engine（Wilds 同构）的命名逐一核对（2026-07-10，22946 个官方块）：
# useRandomSeedTableCount + randomSeedTable0~7 + tableSelectionGroup，刚好 10 个字段。
#   randomSeedTable0~7（原 seed/unkn0_2~8）：8 个位置形状一致——大多数为 0（未用槎位），
#     非零时 67%~98% 落在 |v|>=1000（真随机 int32 种子的典型信号，不是设计师手填小数）。
#   useRandomSeedTableCount（原 unkn0_0）：小整数，众数 1~9，但范围 0~69，并不严格 ≤8
#     （8 个 table 槎位的上限）——不是"已填槎位数"，更像"抽取/复用次数"计数器
#     （允许循环复用 8 个槎位），故字段名里的"count"仍成立，只是不是槎位计数。
#   tableSelectionGroup（原 unkn0_9）：取值全部是 2 的幂/位组合（1/2/4/8/16/32/64/128/
#     255/15/31/63/240…），上限恰好 255（8-bit 全开）——8 个 table 槎位的选择位掩码。
# ─────────────────────────────────────────────────────────────────────────────

RANDOMFIX_ATTR = Attribute(size=40, fields=[
    Int("useRandomSeedTableCount", label_zh="种子表使用次数"),
    Int("randomSeedTable0", label_zh="随机种子表 0"),
    Int("randomSeedTable1", label_zh="随机种子表 1"),
    Int("randomSeedTable2", label_zh="随机种子表 2"),
    Int("randomSeedTable3", label_zh="随机种子表 3"),
    Int("randomSeedTable4", label_zh="随机种子表 4"),
    Int("randomSeedTable5", label_zh="随机种子表 5"),
    Int("randomSeedTable6", label_zh="随机种子表 6"),
    Int("randomSeedTable7", label_zh="随机种子表 7"),
    Bitmask("tableSelectionGroup", BITS_RANDOMFIX_TABLE, label_zh="种子表选择组"),
])
RANDOMFIX_SCHEMA = RANDOMFIX_ATTR.schema
assert _schema_size(RANDOMFIX_SCHEMA) == 40, \
    f"RANDOMFIX_SCHEMA size mismatch: {_schema_size(RANDOMFIX_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Dummy schema  (data_bytes = 9 B; full block = 13 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + byte unkn1(1) = 9 B
# ─────────────────────────────────────────────────────────────────────────────

DUMMY_ATTR = Attribute(size=9, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1
    Byte("unknFixed1"),
])
DUMMY_SCHEMA = DUMMY_ATTR.schema
assert _schema_size(DUMMY_SCHEMA) == 9, \
    f"DUMMY_SCHEMA size mismatch: {_schema_size(DUMMY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternReference schema  (data_bytes = 36 B; full block = 40 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0(4) + int referenceIndex(4) + int unkn1[7](28) = 36 B
# ─────────────────────────────────────────────────────────────────────────────

EXTERNREFERENCE_ATTR = Attribute(size=36, fields=[
    Int("typeFlag"),  # 原 unkn0，语料恒为 0（该类型场景下无变体）  
    Int("referenceIndex", label_zh="Extern 引用"),
    Int("trigger_condition", label_zh="触发条件"),
    Int("unknEnum1_1"),
    Int("unknEnum1_2"),
    Float("unkn1_3"),
    Int("unkn1_4"),
    Int("unkn1_5"),
    Bool("unknFlag1_6"),
])
EXTERNREFERENCE_SCHEMA = EXTERNREFERENCE_ATTR.schema
assert _schema_size(EXTERNREFERENCE_SCHEMA) == 36, \
    f"EXTERNREFERENCE_SCHEMA size mismatch: {_schema_size(EXTERNREFERENCE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PtLife schema  (data_bytes = 20 B; full block = 24 B)
#
# BT (EFX_Subtypes.bt):
#   short unkn0-9  (10 × 2 = 20 B)
# ─────────────────────────────────────────────────────────────────────────────

PTLIFE_ATTR = Attribute(size=20, fields=[
    Short("typeFlag"),  # 原 unkn0
    Short("unknFixed1"),
    Enum("status", ENUM_PTLIFE_STATUS, backing='h', label_en="Trigger On", label_zh="触发条件"),
    Short("unknEnum3"),
    Short("relationIndex", label_zh="关联 Play"),
    Short("unknEnum5"),
    # unknFrame0/1 及各自 Jitter：原 unknEnum6/unknFixed7、unknEnum8/unknFixed9。位置相邻 +
    # 数值特征（unknFrame0/1 非零时恒为 10 的倍数，像帧数）同 LIFE.unknFrame/unknFrameJitter
    # 一样按 static/random 配对改名；Jitter 一侧全部已知语料（8961 块）恒为 0，是否真的承担
    # 随机量仍未证实，仅按位置+数值形态归类。
    Short("unknFrame0"),
    Short("unknFrame0Jitter"),
    Short("unknFrame1"),
    Short("unknFrame1Jitter"),
])
PTLIFE_SCHEMA = PTLIFE_ATTR.schema
assert _schema_size(PTLIFE_SCHEMA) == 20, \
    f"PTLIFE_SCHEMA size mismatch: {_schema_size(PTLIFE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# EmitterBoundary schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[8](32) = 40 B
# ─────────────────────────────────────────────────────────────────────────────

EMITTERBOUNDARY_ATTR = Attribute(size=40, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("unknEnum0_1"),
    Float("unkn1_0"),
    Float("unkn1_1"),
    Float("unkn1_2"),
    Float("unkn1_3"),
    Float("unkn1_4"),
    Float("unkn1_5"),
    Float("unkn1_6"),
    Float("unkn1_7"),
])
EMITTERBOUNDARY_SCHEMA = EMITTERBOUNDARY_ATTR.schema
assert _schema_size(EMITTERBOUNDARY_SCHEMA) == 40, \
    f"EMITTERBOUNDARY_SCHEMA size mismatch: {_schema_size(EMITTERBOUNDARY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# FadeByAngle schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[4](16) + int64 NULL(8) + int unkn2[2](8) = 40 B
#
# 2026-07-29 用户实机测试全部确认（视角朝基轴方向看时特效渐隐/消失）：
#   cutoffConeAngle (原 unkn_angle0)：完全消失锥角（半角）——落在这个角度以内完全不可见
#   fadeConeAngle   (原 unkn_angle1)：渐隐锥角（半角）——cutoffConeAngle 到这个角度之间做渐隐过渡
#   minAlpha        (原 unkn1_2)：渐隐允许达到的最小 alpha（=1 时完全不触发消失，=0.5 时只淡到一半）
#   rotation.xyz (原 axisRotationX/Y/Z / unkn_angle2/3/4)：基轴的旋转分量，与 baseAxis/rotOrder 复合
#   baseAxis   (原 unknBitmask2_0)：基准轴，AxisDirection6（0左1上2前3右4下5后），与 VELOCITY3D
#              同一套枚举，6 个值全部逐一实机验证通过
#   rotOrder   (原 unknEnum2_1)：旋转顺序，_ROT_ORDER6（0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX），
#              与 VELOCITY3D 同一套枚举，复合公式 v' = Ry(rotation.y)·Rx(rotation.x)·
#              Rz(rotation.z)·baseAxis，实机验证通过（含分组验证 0/1/4 vs 2/3/5）
# 三者共同确定"往哪个方向看会触发渐隐/消失"，跟 VELOCITY3D 的 [baseAxis, rotOrder] 是同一套
# 底层机制的另一处复用。
#
# coneVisibilityFlags（原 unkn0_1）：2026-07-29 用户实机穷举全部 8 种位组合确认：
#   bit0=enableDoubleCone：独立生效，不受 bit1/bit2 影响——置位后额外在对立角（-baseAxis）
#     追加一份与主锥角完全相同的可见性规则（镜像）。
#   bit1=excludeCone：真正的"反转"开关，恒定生效——置位后"锥角内/外"的可见性互换
#     （变成锥角内不可见、外可见），不受 bit0/bit2 影响。
#   bit2（未知）：单独置位时表现跟 bit1 一样是反转，但只要 bit0=1 就完全失效（被盖掉，
#     不再反转）——即整体反转 = bit1 OR (bit2 AND NOT bit0)。这个"被 bit0 单向遮蔽"的
#     不对称行为无法用一个独立同等地位的开关解释，具体内部语义仍不清楚，先保留占位标签。
# ─────────────────────────────────────────────────────────────────────────────

FADEBYANGLE_ATTR = Attribute(size=40, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Bitmask("coneVisibilityFlags", BITS_FADEBYANGLE_FLAGS, label_zh="锥体可见性标志", strict=True),
    Float("cutoffConeAngle", label_zh="完全消失锥角"),
    Float("fadeConeAngle", label_zh="渐隐锥角"),
    Float("minAlpha", label_zh="最小透明度"),
    Raw("rotation", ('XYZ', 3), label_zh="旋转"),  # 原 axisRotationX/Y/Z
    Enum("baseAxis", _AXIS_DIRECTION6, label_zh="基准轴"),
    Enum("rotOrder", _ROT_ORDER6, label_zh="旋转顺序"),
])
FADEBYANGLE_SCHEMA = FADEBYANGLE_ATTR.schema
assert _schema_size(FADEBYANGLE_SCHEMA) == 40, \
    f"FADEBYANGLE_SCHEMA size mismatch: {_schema_size(FADEBYANGLE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# MasterOnly schema  (data_bytes = 4 B; full block = 8 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0(4) = 4 B
# ─────────────────────────────────────────────────────────────────────────────

MASTERONLY_ATTR = Attribute(size=4, fields=[
    Int("typeFlag"),  # 原 unkn0
])
MASTERONLY_SCHEMA = MASTERONLY_ATTR.schema
assert _schema_size(MASTERONLY_SCHEMA) == 4, \
    f"MASTERONLY_SCHEMA size mismatch: {_schema_size(MASTERONLY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Blink schema  (data_bytes = 52 B; full block = 56 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[11](44) = 52 B
# ─────────────────────────────────────────────────────────────────────────────

BLINK_ATTR = Attribute(size=52, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1
    Float("unkn1_0"),  # bool (byte 0) + 0xCD×3 padding  
    Float("minAlpha"),
    Float("maxAlpha"),
    Float("lowFreq"),
    Float("lowFreqJitter"),
    Float("lowFreqAmplitude"),
    Float("lowFreqAmplitudeJitter"),
    Float("highFreq"),
    Float("highFreqJitter"),
    Float("highFreqAmplitude"),
    Float("highFreqAmplitudeJitter"),
])
BLINK_SCHEMA = BLINK_ATTR.schema
assert _schema_size(BLINK_SCHEMA) == 52, \
    f"BLINK_SCHEMA size mismatch: {_schema_size(BLINK_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# FadeByEmitterAngle schema  (data_bytes = 28 B; full block = 32 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + long unkn(4) + float unkn2[4](16) = 28 B
#
# 原 cone/alphaRate 改名 outerConeAngle/innerConeAngle（2026-07-23，全语料
# 10131 块统计：innerConeAngle ≤ outerConeAngle 占 10116/10131=99.85%，二者
# 同为 0~360 量级，最高频组合 (180,20) 占比 73%——形态是一对锥角，"alphaRate"
# 这个原名容易让人误以为是透明度变化速率，故直接改名）。
# ⚠ 待验证：只有统计证据，未像 fadeInStart/fadeInEnd 那样经过实机操作确认——  
# 还没人转到发射器侧后方实测过角度跨过这两个值时透明度是否真的在变。
# ─────────────────────────────────────────────────────────────────────────────

FADEBYEMITTERANGLE_ATTR = Attribute(size=28, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1
    Int("unkn"),  # bool (byte 0) + 0xCD×3 padding  
    Float("outerConeAngle", label_zh="外锥角"),
    Float("innerConeAngle", label_zh="内锥角"),
    Float("fadeInStart", label_zh="淡入起点"),
    Float("fadeInEnd", label_zh="淡入终点"),
])
FADEBYEMITTERANGLE_SCHEMA = FADEBYEMITTERANGLE_ATTR.schema
assert _schema_size(FADEBYEMITTERANGLE_SCHEMA) == 28, \
    f"FADEBYEMITTERANGLE_SCHEMA size mismatch: {_schema_size(FADEBYEMITTERANGLE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# RayCast schema  (data_bytes = 78 B; full block = 82 B)
#
# BT (EFX_Subtypes.bt):
#   int unknown(4) + int fixed70(4) + long spacer0(4) +  
#   float distanceMod0/j(8) + float prop1/j(8) +
#   long spacer1/2/3(12) + float prop2(4) + XYZ prop3(3)(12) +  
#   int direction(4) + float distanceMod1/j(8) +
#   long spacer(4) + int unknown1(4) + short unknown2(2)  
# = 4+4+4+8+8+12+4+12+4+8+4+4+2 = 78 B ✓
# ─────────────────────────────────────────────────────────────────────────────

RAYCAST_ATTR = Attribute(size=78, fields=[
    Int("typeFlag"),  # 原 unknown0
    Int("section_length", label_zh="段长度"),  # 原 fixed70
    Int("spacer0"),
    Float("distanceMod0", label_zh="距离调制0"),
    Float("distanceMod0Jitter", label_zh="距离调制0抖动"),
    Float("prop1", label_zh="属性1"),
    Float("prop1Jitter", label_zh="属性1抖动"),
    Int("spacer1"),
    Int("spacer2"),
    Int("spacer3"),
    Float("prop2", label_zh="属性2"),
    Raw("prop3", ('XYZ', 3), label_zh="属性3"),
    Enum("direction", ENUM_RAYCAST_DIR, label_zh="方向"),
    Float("distanceMod1", label_zh="距离调制1"),
    Float("distanceMod1Jitter", label_zh="距离调制1抖动"),
    Int("spacer"),
    Int("unknownEnum1"),
    Short("unknownBitmask2"),
])
RAYCAST_SCHEMA = RAYCAST_ATTR.schema
assert _schema_size(RAYCAST_SCHEMA) == 78, \
    f"RAYCAST_SCHEMA size mismatch: {_schema_size(RAYCAST_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Homing schema  (data_bytes = 52 B; full block = 56 B)
#
# BT (EFX_Subtypes.bt):
#   int unknown(4) + int unknown0(4) + long spacer(4) +  
#   float restoringForce(4) + float speed(4) + float speedMultiplier(4) +
#     ↑ 本仓库现名 turnRate / initialSpeed / targetSpeed（见下方改名说明）
#   float f3(4) + float vanishDistance(4) + float forceFieldDistance(4) +
#     ↑ 现名 forceFieldSpeedScale / vanishRadius / forceFieldRadius
#   long homingTarget(4) + long vanishMode(4) +
#   int forceFieldMode(4) + int unknown1(4)
# = 4+4+4+4+4+4+4+4+4+4+4+4+4 = 52 B ✓
# Note: SPEC.md confirms HOMING = 56 B (with +12 offset often 0xCDCDCD00),  
# matches efxfile.py: 4(type)+4+4+4+24+8+8 = 4+52 = 56 full.
# homingTarget 原名 i0，（2026-07-11）：归航运动始终指向目标点的**实时**位置
# （非旧假说所说的"触发时捕获定住"）。vanishMode/forceFieldMode 原名 i1/
# enableRadialVanish，2026-07-11 按实测语义改名。
#
# ── 运动学模型（2026-07-30 用八角探针系统实测坐实，取代此前的"回复力/弹簧"读法）──
# 单个粒子的行为：
#   ① 从生成位置**径直飞向**归航目标，这一段是直线、不转弯；
#   ② 到达目标的瞬间，获得一个与入射方向**垂直（90°）**的速度；
#   ③ 之后在这个平面内转圈，角速度 = turnRate，半径 r = v / turnRate，圆在目标点
#      与入射方向相切，转一整圈回到目标点，如此往复、无衰减。
#   ④ v 从 initialSpeed 出发（上限被 targetSpeed 钳住）乘法式逼近 targetSpeed：
#      两者相等 → 严格闭合圆；initialSpeed 更小 → 从小圈向外旋开；任一为 0 → 不动。
# ⚠ 多粒子的**合成剪影**会呈现四叶草/扁球/圆盘/水平线等图案，那些都不是单粒子行为，
#   早期基于球形发射器剪影推出的"逐轴简谐振荡 + 绕局部 Y 涡旋"结论已被证伪。
# ⚠ HOMING 硬依赖同 entry 的 VELOCITY3D（哪怕 V3D 字段全 0），否则粒子没有惯性、
#   跑到目标点即停。validate.py (5m) 已有对应 WARN。
#
# 改名（2026-07-30，依上述实测）：
#   restoringForce  → turnRate            不是力度，是转弯角速度，单位**度/秒**
#                                         （rF=360 实测正好每秒一整圈）
#   speed           → initialSpeed        起始速度，取 min(自身, targetSpeed)
#   speedMultiplier → targetSpeed         不是倍率，是速度最终收敛到的值；
#                                         终半径 = targetSpeed / turnRate（线性）
#   f3              → forceFieldSpeedScale 力场作用区内的速度倍率，0=停住、
#                                         ≥1=不缩放；仅 forceFieldMode 2/4 用得到
#                                         （语料 21/21 零例外：mode 2/4 必配 <1，
#                                          mode 0 的 149 条一个 <1 都没有）
#   vanishDistance  → vanishRadius        是球半径不是距离，球心=归航目标
#   forceFieldDistance → forceFieldRadius 同上
# ─────────────────────────────────────────────────────────────────────────────

HOMING_ATTR = Attribute(size=52, fields=[
    Int("typeFlag"),  # 原 unknown
    Int("section_length", label_zh="段长度"),  # 原 unknown0
    Int("spacer"),
    Float("turnRate", label_zh="转向速率"),  # 原 restoringForce / f0；单位度/秒
    Float("initialSpeed", label_zh="起始速度"),  # 原 speed
    Float("targetSpeed", label_zh="终速度"),  # 原 speedMultiplier
    Float("forceFieldSpeedScale", label_zh="力场速度倍率"),  # 原 f3
    Float("vanishRadius", label_zh="消失半径"),  # 原 vanishDistance / f4 / activationDistance
    Float("forceFieldRadius", label_zh="力场半径"),  # 原 forceFieldDistance / radius
    Enum("homingTarget", ENUM_HOMING_TARGET, label_zh="归航目标"),  # 原 i0
    Enum("vanishMode", ENUM_HOMING_VANISH, label_zh="消失模式"),  # 原 i1
    Enum("forceFieldMode", ENUM_HOMING_FORCEFIELD, label_zh="力场模式"),  # 原 enableRadialVanish
    Int("unknownEnum1"),
])
HOMING_SCHEMA = HOMING_ATTR.schema
assert _schema_size(HOMING_SCHEMA) == 52, \
    f"HOMING_SCHEMA size mismatch: {_schema_size(HOMING_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ScreenSpaceCollision schema  (data_bytes = 36 B; full block = 40 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + long spacer(4) + float unkn1(4) + float bounce(4) +  
#   float bounceJitter(4) + int lifespan(4) + int lifespanJitter(4) +
#   float bounceConditional(4) = 36 B ✓
# ─────────────────────────────────────────────────────────────────────────────

SCREENSPACECOLLISION_ATTR = Attribute(size=36, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1
    Int("spacer"),
    Int("unknEnum1"),
    Float("bounce", label_zh="弹跳"),
    Float("bounceJitter", label_zh="弹跳抖动"),
    Int("lifespan", label_zh="寿命"),
    Int("lifespanJitter", label_zh="寿命抖动"),
    Float("bounceConditional", label_zh="条件弹跳"),
])
SCREENSPACECOLLISION_SCHEMA = SCREENSPACECOLLISION_ATTR.schema
assert _schema_size(SCREENSPACECOLLISION_SCHEMA) == 36, \
    f"SCREENSPACECOLLISION_SCHEMA size mismatch: {_schema_size(SCREENSPACECOLLISION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Shovel schema  (data_bytes = 70 B; full block = 74 B)
#
# BT (EFX_Subtypes.bt):
#   long unkn00(4) + long unkn01(4) + long spacer(4) +  
#   float width/j(8) + float height/j(8) + float length/j(8) +
#   long unkn09(4) + long unkn10(4) + float unkn11(4) +
#   long unkn12-14(12) + long pattern(4) + long unkn16(4) + short unkn17(2)
# = 4+4+4+8+8+8+4+4+4+12+4+4+2 = 70 B ✓
#
# ⚠ unkn09/unkn10 实测非 BT 标注的 long，是 float（角度对，见 549/549 官方样本统计）。  
# ─────────────────────────────────────────────────────────────────────────────

SHOVEL_ATTR = Attribute(size=70, fields=[
    Int("typeFlag"),  # 原 unkn00
    Int("section_length", label_zh="段长度"),  # 原 unkn01
    Int("spacer"),
    Float("width", label_zh="宽度"),
    Float("widthJitter", label_zh="宽度抖动"),
    Float("height", label_zh="高度"),
    Float("heightJitter", label_zh="高度抖动"),
    Float("length", label_zh="长度"),
    Float("lengthJitter", label_zh="长度抖动"),
    Float("unkn09"),
    Float("unkn10"),
    Float("unkn11"),
    Int("unknFixed12"),
    Int("unknEnum13"),
    Int("unknEnum14"),
    Int("pattern", label_zh="图案"),
    Int("unknBitmask16"),
    Short("unknEnum17"),
])
SHOVEL_SCHEMA = SHOVEL_ATTR.schema
assert _schema_size(SHOVEL_SCHEMA) == 70, \
    f"SHOVEL_SCHEMA size mismatch: {_schema_size(SHOVEL_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# UVControl schema  (data_bytes = 236 B; full block = 240 B)
#
# BT (EFX_Subtypes.bt):
#   Material_Animation_Data uv1 (100 B) + Material_Animation_Data uv2 (100 B) +
#   int unkn2(4) + float[8] extra (32 B) = 236 B
#
# Material_Animation_Data (100 B):
#   int unkn0(4) + uv_transform[6](96) where uv_transform = float u/uJ/v/vJ (16 B)
#   = 4 + 6*16 = 100 B
# ─────────────────────────────────────────────────────────────────────────────

UVCONTROL_ATTR = Attribute(size=236, fields=[
    # uv1 Material_Animation_Data
    # 2026-07-31 全语料扫描(official 1784例)：18 种取值(1~26)从未为 0，覆盖低4位几乎
    # 全部非零组合+罕见第5位；具备位掩码特征但具体位含义未实机确认，先只改名不拆位。
    Int("uv1_unknFlag", label_zh="UV1 未知标志"),  # 原 uv1_unkn0
    Raw("uv1_offset", ('f', 4), label_zh="UV1 初始位置"),
    Raw("uv1_offsetAdd", ('f', 4), label_zh="UV1 速度"),
    Raw("uv1_offsetCoef", ('f', 4), label_zh="UV1 加速度"),
    Raw("uv1_scale", ('f', 4), label_zh="UV1 缩放"),
    Raw("uv1_scaleAdd", ('f', 4), label_zh="UV1 缩放速度"),
    Raw("uv1_scaleCoef", ('f', 4), label_zh="UV1 缩放加速度"),
    # uv2 Material_Animation_Data
    Bool("uv2_enable"),  # 原 uv2_unkn0，实测 1860 例仅 0/1 两种取值，干净二元
    Raw("uv2_offset", ('f', 4), label_zh="UV2 初始位置"),
    Raw("uv2_offsetAdd", ('f', 4), label_zh="UV2 速度"),
    Raw("uv2_offsetCoef", ('f', 4), label_zh="UV2 加速度"),
    Raw("uv2_scale", ('f', 4), label_zh="UV2 缩放"),
    Raw("uv2_scaleAdd", ('f', 4), label_zh="UV2 缩放速度"),
    Raw("uv2_scaleCoef", ('f', 4), label_zh="UV2 缩放加速度"),
    # extra fields — flowmap 8 件套（2026-07-31 改名，命名对齐 RIBBON/RIBBONBLADE/
    # BILLBOARD2D/BILLBOARD3D/PLANE 同款 flowmap 组：Speed/Acceleration/Strength/
    # StrengthAcceleration 各配 Jitter，另加 enableFlowmap 总开关）。
    Bool("enableFlowmap", label_zh="启用流动贴图"),  # 原 unknFlag2
    Float("flowmapSpeed", label_zh="流动贴图速度"),  # 原 extraMaterialInitialPosition
    Float("flowmapSpeedJitter", label_zh="流动贴图速度抖动"),  # 原 extraMaterialInitialPositionJitter
    Float("flowmapSpeedCoef", label_zh="流动贴图加速度"),  # 原 extraMaterialSpeed
    Float("flowmapSpeedCoefJitter", label_zh="流动贴图加速度抖动"),  # 原 extraMaterialSpeedJitter
    Float("flowmapStrength", label_zh="流动贴图强度"),  # 原 opacity
    Float("flowmapStrengthJitter", label_zh="流动贴图强度抖动"),  # 原 opacityJitter
    Float("flowmapStrengthCoef", label_zh="流动贴图强度加速度"),  # 原 opacityAcceleration
    Float("flowmapStrengthCoefJitter", label_zh="流动贴图强度加速度抖动"),  # 原 opacityAccelerationJitter
])
UVCONTROL_SCHEMA = UVCONTROL_ATTR.schema
assert _schema_size(UVCONTROL_SCHEMA) == 236, \
    f"UVCONTROL_SCHEMA size mismatch: {_schema_size(UVCONTROL_SCHEMA)}"


EMITTERSHAPE2D_ATTR = Attribute(size=36, fields=[
    Int("typeFlag"),  # 原 unkn0
    # rangeX/Y(+Jitter)：原 offsetX/Y(+Jitter)，用户 2026-07-26 确认对应 EMITTERSHAPE3D.rangeXYZ
    # 同一概念（生成范围），只是 2D 版本存成独立标量而非 XYZ 复合类型（少一根 Z 轴）。
    # ⚠ 与 rangeXYZ 一样是 offset/size（内边界+厚度，外边界=offset+size），**不是** 固定/随机；
    # ori_name 的 *Jitter 后缀是历史命名，保留不动（改名会波及预设与已导入的 .blend），
    # UI 措辞由 panels.py::_OFFSET_SIZE_PAIRS 覆盖成 偏移/尺寸。
    Float("rangeX", label_zh="生成范围 X"),
    Float("rangeXJitter", label_zh="生成范围 X 抖动"),
    Float("rangeY", label_zh="生成范围 Y"),
    Float("rangeYJitter", label_zh="生成范围 Y 抖动"),
    # shapeType：原 unknFlag20，用户 2026-07-26 确认对应 EMITTERSHAPE3D.shapeType：
    # 0=方形，1=圆形，2+=点。⚠ 全语料 292 例目前只观测到 0/1，未见过 ≥2 的实例。
    Enum("shapeType", ENUM_SHAPE_TYPE2D, label_zh="形状类型"),
    # rangeDivideHorizontalNum：原 spawnCount（"生成数量"）。用户 2026-07-30 实机测试确认
    # 它是**等分数量**而非生成个数，与 EMITTERSHAPE3D.rangeDivideHorizontalNum 同一概念的
    # 2D 版本（2D 只有一根横向维度，故没有 Vertical 对应字段）。
    Int("rangeDivideHorizontalNum", label_zh="横向等分数量"),
    # rangeDivideAxis：原 unknEnum22_0。用户 2026-09-03 按与 EMITTERSHAPE3D 同构推定为
    # 「方形的细分轴向」——2D 版与 3D 版逐字段对应，3D 那边同位置就是 rangeDivideAxis
    # （仅 Box 生效、选沿哪个轴细分）。取值 {0:94%, 1:2%, 2:4%}。
    # ⚠ 用 2D 专属枚举：3D 那张是 0=X/1=Z/2=Y，2D 实测是 **0=Y、1=X**，编号不一样。
    #   语料还有 4% 取值 2，含义未知，未列进枚举（越界值回退显示原整数）。
    Enum("rangeDivideAxis", ENUM_RANGE_DIVIDE_AXIS_2D, label_zh="细分轴向"),
    # unknFixed22_1：全语料 292 例恒为 0。曾被列为 EmitterShape2D 的 LocalRotation
    # （TIML DT 0x7516AA5D）的候选宿主，但用户 2026-09-03 实机改它看不到变化，未坐实。
    Int("unknFixed22_1"),
])
EMITTERSHAPE2D_SCHEMA = EMITTERSHAPE2D_ATTR.schema
assert _schema_size(EMITTERSHAPE2D_SCHEMA) == 36, \
    f"EMITTERSHAPE2D_SCHEMA size mismatch: {_schema_size(EMITTERSHAPE2D_SCHEMA)}"

VELOCITY2D_ATTR = Attribute(size=72, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Float("rotation", label_zh="旋转"),  # 原 unkn0_1，2026-07-26 用户确认为旋转角度
    Float("rotationJitter", label_zh="旋转抖动"),  # 原 unkn10
    Float("speed", label_zh="初速度"),  # 原 initialVelocity/expansionRadius，2026-07-26 依续作 schema 改名
    Float("speedJitter", label_zh="初速度偏差"),  # 原 initialVelocityJitter/expansionRadiusJitter
    Float("speedCoef", label_zh="加速度"),  # 原 expansionRadiusElasticity（用户 2026-07-26 决定保留此名，
                                               # 不跟随续作 schema 的 drag 命名，二者本质是同一个力）
    Float("speedCoefJitter", label_zh="加速度偏差"),  # 原 expansionRadiusElasticityJitter
    Float("velocityX", label_zh="X 基准点偏置"),  # 原 offsetX/unkn15，2026-07-26 依续作 schema 改回 velocityX
    Float("velocityY", label_zh="Y 基准点偏置"),  # 原 offsetY/unkn16
    Float("divergenceX", label_zh="X 基准点伸缩"),  # 原 sizeX/energyOnAxisX，2026-07-26 依续作 schema 改名
    Float("divergenceY", label_zh="Y 基准点伸缩"),  # 原 sizeY/energyOnAxisY，9 floats = 36
    Enum("velocityType", _VELOCITY_TYPE, label_zh="速度类型"),  # 原 expansionType，同 V3D 改名（枚举语义见 V3D 注释）
    Float("gravity", label_zh="重力"),
    Float("gravityJitter", label_zh="重力抖动"),  # 8
    Int("movementDelay", label_zh="运动延迟"),  # 原 initialVelocityDelay/expansionDelay，2026-07-26 依续作 schema 改名
    Int("movementDelayJitter", label_zh="运动延迟抖动"),  # 原 initialVelocityDelayJitter/expansionDelayJitter
    Int("gravityDelay", label_zh="重力延迟"),
    Int("gravityDelayJitter", label_zh="重力延迟抖动"),  # 16
])
VELOCITY2D_SCHEMA = VELOCITY2D_ATTR.schema
assert _schema_size(VELOCITY2D_SCHEMA) == 72, \
    f"VELOCITY2D_SCHEMA size mismatch: {_schema_size(VELOCITY2D_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# 原 opaque 定长类型 schema（新增）
# 字段布局来源：EFX_Crimson.bt；字节数由 _known_attr_size 实测往返验证。
# 字段命名以 unknN 为主，语义待后续补全。
# ─────────────────────────────────────────────────────────────────────────────

# PathChain (81B total, 77B data)
PATHCHAIN_ATTR = Attribute(size=77, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Float("unkn2"),  # 4B
    Int("unknEnum3"),  # 4B
    Float("unkn4_0"),
    Float("unknFixed4_1"),
    Float("unkn4_2"),
    Float("unknFixed4_3"),
    Float("unkn4_4"),
    Float("unknFixed4_5"),  # 24B
    Int("unknBitmask5_0"),
    Float("unkn5_1"),
    Float("unkn5_2"),
    Float("unkn5_3"),
    Int("unknFixed5_4"),
    Float("unkn5_5"),
    Int("unknFixed5_6"),
    Int("unknEnum5_7"),  # 32B
    Bool("unknFlag6", backing='b'),  # 1B
])
PATHCHAIN_SCHEMA = PATHCHAIN_ATTR.schema
assert _schema_size(PATHCHAIN_SCHEMA) == 77, \
    f"PATHCHAIN_SCHEMA size mismatch: {_schema_size(PATHCHAIN_SCHEMA)}"

# PtTrigger (20B total, 16B data)
PTTRIGGER_ATTR = Attribute(size=16, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Int("unknEnum2"),  # 4B
])
PTTRIGGER_SCHEMA = PTTRIGGER_ATTR.schema
assert _schema_size(PTTRIGGER_SCHEMA) == 16, \
    f"PTTRIGGER_SCHEMA size mismatch: {_schema_size(PTTRIGGER_SCHEMA)}"

# LinkPartsVisible (16B total, 12B data)
LINKPARTSVISIBLE_ATTR = Attribute(size=12, fields=[
    Int("typeFlag"),  # 原 unkn0_0，语料恒为 1（样本少，仅 87 例）
    Int("unknFixed0_1"),
    Int("unknEnum0_2"),  # 12B
])
LINKPARTSVISIBLE_SCHEMA = LINKPARTSVISIBLE_ATTR.schema
assert _schema_size(LINKPARTSVISIBLE_SCHEMA) == 12, \
    f"LINKPARTSVISIBLE_SCHEMA size mismatch: {_schema_size(LINKPARTSVISIBLE_SCHEMA)}"

# SpawnByAngle (26B total, 22B data)
SPAWNBYANGLE_ATTR = Attribute(size=22, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Float("unkn2"),  # 4B
    Int("unknEnum3"),  # 4B
    Short("unknFixed4"),  # 2B
])
SPAWNBYANGLE_SCHEMA = SPAWNBYANGLE_ATTR.schema
assert _schema_size(SPAWNBYANGLE_SCHEMA) == 22, \
    f"SPAWNBYANGLE_SCHEMA size mismatch: {_schema_size(SPAWNBYANGLE_SCHEMA)}"

# CheckPureAttribute (44B total, 40B data)
CHECKPUREATTRIBUTE_ATTR = Attribute(size=40, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Int("unknEnum2_0"),
    Int("unknEnum2_1"),
    Int("unknEnum2_2"),
    Int("unknEnum2_3"),
    Int("unknEnum2_4"),
    Int("unknEnum2_5"),
    Int("unknFixed2_6"),  # 28B
])
CHECKPUREATTRIBUTE_SCHEMA = CHECKPUREATTRIBUTE_ATTR.schema
assert _schema_size(CHECKPUREATTRIBUTE_SCHEMA) == 40, \
    f"CHECKPUREATTRIBUTE_SCHEMA size mismatch: {_schema_size(CHECKPUREATTRIBUTE_SCHEMA)}"

# SpawnByOcclusion (24B total, 20B data)
SPAWNBYOCCLUSION_ATTR = Attribute(size=20, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Float("unknFixed2"),  # 4B
    Int("unknFixed3"),  # 4B
])
SPAWNBYOCCLUSION_SCHEMA = SPAWNBYOCCLUSION_ATTR.schema
assert _schema_size(SPAWNBYOCCLUSION_SCHEMA) == 20, \
    f"SPAWNBYOCCLUSION_SCHEMA size mismatch: {_schema_size(SPAWNBYOCCLUSION_SCHEMA)}"

# FadeByOcclusion (28B total, 24B data)
#
# 2026-07-29 用户实机测试确认：这个块不是靠隐藏/透明度渐隐，是"被遮挡时把特效缩小"，
# 跟续作 schema 的 Radius/MinSize 对应（见 fadebyocclusion-shrink-mechanism 记忆）：
#   occlusionRadius (原 unkn2_0)：判定体积，设得越大越容易触发缩小
#   minScale        (原 unknFlag2_1)：允许缩小到的最小比例（=1 时完全不缩小）
#   minAlpha        (原 unknFlag2_2)：缩小时允许淡到的最小透明度（=1 时只缩小不渐隐，
#                    =0 时缩小的同时会渐隐）
# 顺带核对：unknFixed0_1 全语料恒为 16（=24B 总长-8，跟其他类型的 section_length 同一套
# 结构性标记，非可调数据）；unkn1 全语料恒为 0xCDCDCDCD（未初始化填充，非可调数据）。
FADEBYOCCLUSION_ATTR = Attribute(size=24, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unknFixed0_1，8B
    Int("spacer0"),  # 原 unkn1，恒 0xCDCDCDCD，4B
    Float("occlusionRadius", label_zh="遮挡判定半径"),
    Float("minScale", label_zh="最小缩放比例"),
    Float("minAlpha", label_zh="最小透明度"),  # 12B
])
FADEBYOCCLUSION_SCHEMA = FADEBYOCCLUSION_ATTR.schema
assert _schema_size(FADEBYOCCLUSION_SCHEMA) == 24, \
    f"FADEBYOCCLUSION_SCHEMA size mismatch: {_schema_size(FADEBYOCCLUSION_SCHEMA)}"

# ParentMaterial (16B total, 12B data)
PARENTMATERIAL_ATTR = Attribute(size=12, fields=[
    Int("typeFlag"),  # 原 unkn0_0，语料仅 1 例
    Int("unknFixed0_1"),  # 8B
    Float("unknFixed1"),  # 4B
])
PARENTMATERIAL_SCHEMA = PARENTMATERIAL_ATTR.schema
assert _schema_size(PARENTMATERIAL_SCHEMA) == 12, \
    f"PARENTMATERIAL_SCHEMA size mismatch: {_schema_size(PARENTMATERIAL_SCHEMA)}"

# Transform2D (28B total, 24B data)
# 原 BT 猜测 int64 unkn0[2](16B) + float unkn1[2](8B)（两个 int64，各拆低32位int+高32位
# float）——2026-07-10 用户对照 RE Engine（Wilds 同构，Type=0x1987C7EC）反编译结构证实
# 该猜测是错的：实际是扁平的 6 个标量，根本没有"int64 对"这层结构：
#   int unknown(4) + float offsetXY[2](8) + float rotation(4) + float scaleXY[2](8) = 24B
# 第一个字段确实是 int（该引擎里很多块的头一个字段习惯性是 int/flags，REE 自己也没解出
# 具体含义、仍标"unknown"，故未强行杜撰名字）；offsetXY/scaleXY 按本仓库惯例拆成 X/Y
# 后缀（同 BILLBOARD2D 的 scaleX/scaleY）。
TRANSFORM2D_ATTR = Attribute(size=24, fields=[
    Int("typeFlag"),  # 原 unknown
    Float("offsetX", label_zh="X 偏移"),
    Float("offsetY", label_zh="Y 偏移"),
    Float("rotation", label_zh="旋转"),  # 16B
    Float("scaleX"),
    Float("scaleY"),  # 8B
])
TRANSFORM2D_SCHEMA = TRANSFORM2D_ATTR.schema
assert _schema_size(TRANSFORM2D_SCHEMA) == 24, \
    f"TRANSFORM2D_SCHEMA size mismatch: {_schema_size(TRANSFORM2D_SCHEMA)}"

# ColorCorrectFilter (692B total, 688B data)
COLORCORRECTFILTER_ATTR = Attribute(size=688, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("unknEnum0_1"),
    Int("unknFixed0_2"),
    Int("unknFixed0_3"),  # 16B
    Raw("unkn1", ('f', 168)),  # 672B
])
COLORCORRECTFILTER_SCHEMA = COLORCORRECTFILTER_ATTR.schema
assert _schema_size(COLORCORRECTFILTER_SCHEMA) == 688, \
    f"COLORCORRECTFILTER_SCHEMA size mismatch: {_schema_size(COLORCORRECTFILTER_SCHEMA)}"

# ParentSnow (84B total, 80B data)
PARENTSNOW_ATTR = Attribute(size=80, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Int("unknFixed2"),  # 4B
    Raw("color", ('XYZ', 2), label_zh="颜色"),  # 4B
    Int("unknEnum3_0"),
    Int("unkn3_1"),  # 8B
    Float("unkn4_0"),
    Float("unkn4_1"),
    Float("unkn4_2"),
    Float("unkn4_3"),
    Float("unkn4_4"),
    Float("unkn4_5"),
    Float("unknFlag4_6"),
    Float("unkn4_7"),
    Float("unkn4_8"),
    Float("unkn4_9"),
    Float("unkn4_10"),
    Float("unknFixed4_11"),
    Float("unkn4_12"),  # 52B
])
PARENTSNOW_SCHEMA = PARENTSNOW_ATTR.schema
assert _schema_size(PARENTSNOW_SCHEMA) == 80, \
    f"PARENTSNOW_SCHEMA size mismatch: {_schema_size(PARENTSNOW_SCHEMA)}"

OTOMOSNOW_ATTR = Attribute(size=84, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    Int("unkn1"),  # 4B
    Int("unknFixed2_0"),
    Int("unknFixed2_1"),  # 8B
    Raw("color", ('XYZ', 2), label_zh="颜色"),  # 4B
    Int("unknEnum3"),  # 4B
    Int("unkn4"),  # 4B
    Float("unknFixed5_0"),
    Float("unknFixed5_1"),
    Float("unknFixed5_2"),
    Float("unknFixed5_3"),  # 16B
    Int("unkn6"),  # 4B
    Float("unknFixed7_0"),
    Float("unkn7_1"),
    Float("unknFixed7_2"),
    Float("unkn7_3"),
    Float("unkn7_4"),
    Float("unknFixed7_5"),
    Float("unknFixed7_6"),
    Float("unkn7_7"),  # 32B
])
OTOMOSNOW_SCHEMA = OTOMOSNOW_ATTR.schema
assert _schema_size(OTOMOSNOW_SCHEMA) == 84, \
    f"OTOMOSNOW_SCHEMA size mismatch: {_schema_size(OTOMOSNOW_SCHEMA)}"

# FakePlane (64B total, 60B data)
# BT (EFX_Crimson.bt): int unkn0[2](8) + byte unkn1[4](4) + float unkn2(4) +
#   int unkn3(4) + long unkn4(4) + float unkn5[9](36)
FAKEPLANE_ATTR = Attribute(size=60, fields=[
    Int("typeFlag"),  # 原 unkn0_0
    Int("section_length", label_zh="段长度"),  # 原 unkn0_1，8B
    SByte("unknFixed1_0"),
    Bool("unknFlag1_1", backing='b'),
    Bool("unknFlag1_2", backing='b'),
    Bool("unknFlag1_3", backing='b'),  # 4B
    Float("unkn2"),  # 4B
    Int("unknEnum3"),  # 4B
    Int("unkn4"),  # 4B  (long=4B)
    Float("unkn5_0"),
    Float("unkn5_1"),
    Float("unkn5_2"),
    Float("unknFixed5_3"),
    Float("unkn5_4"),
    Float("unkn5_5"),
    Float("unkn5_6"),
    Float("unknFixed5_7"),
    Int("unknEnum5_8"),  # 36B
])
FAKEPLANE_SCHEMA = FAKEPLANE_ATTR.schema
assert _schema_size(FAKEPLANE_SCHEMA) == 60, \
    f"FAKEPLANE_SCHEMA size mismatch: {_schema_size(FAKEPLANE_SCHEMA)}"

# RepeatArea (56B total, 52B data) — 无 BT，按全 135 实例列分析推断字段类型：
#   off0 小整数(0~10) / off4 恒为 44 / off8..23 为 0xcd 未初始化区(16B) /  
#   off24..47 为 6 个 float / off48 小整数。
# EFX.bt(新，refs/EFX_Subtypes.bt)把这个类型按变长结构描述：
#   int unkn0; int length; long unkn1[length/4-5]; float unkn2[3]; int unkn3[2];
# 即 off4 是"剩余字节数"自描述长度标记（跟 NOISE.section_length 等同一机制，已在
# field_labels.py RESERVED_FILL_FIELDS 里按此归类），全语料 135/135 恒为 44，故正式
# 改名 section_length。新 bt 认为 off8..23 是变长 long 数组的一部分，但实测这 16 字节
# 每份样本都是固定的 `00 CD CD ... CD`（首字节 0x00 + 其余 0xCD），是保留未用容量，  
# 不是有效数据，故沿用 unkn2 原名（已在 RESERVED_FILL_FIELDS 标注只读）。
REPEATAREA_ATTR = Attribute(size=52, fields=[
    Int("typeFlag"),  # 4B  原 unkn0，索引/计数
    Int("section_length", label_zh="段长度"),  # 4B  原 unkn1；恒 44，剩余字节数自描述标记（非可调参数）
    Raw("unkn2", ('b', 16)),  # 16B 0xcd 未初始化区（首字节固定 0x00，其余固定 0xCD）  
    Float("unkn3_0"),
    Float("unkn3_1"),
    Float("unknFixed3_2"),
    Float("unknFixed3_3"),
    Float("unkn3_4"),
    Float("unkn3_5"),  # 24B
    Int("unknEnum4"),  # 4B
])
REPEATAREA_SCHEMA = REPEATAREA_ATTR.schema
assert _schema_size(REPEATAREA_SCHEMA) == 52, \
    f"REPEATAREA_SCHEMA size mismatch: {_schema_size(REPEATAREA_SCHEMA)}"


# FakeDoF：恒 32B 定长（曾误判有"可选 20B 尾巴"而登记为 _custom，实为 LAYOUT 同源 bug，
# 下一 entry 头被误吞——已查实无尾，转正为普通定长块，退掉空壳 custom codec）。
FAKEDOF_ATTR = Attribute(size=32, fields=[
    Int("typeFlag"),          # 原 unkn0，索引/计数 1~5
    Int("section_length", label_zh="段长度"),    # 原 unkn1，恒 24（自描述剩余字节标记，非可调参数）
    Int("unkn2"),             # 0xcd 未初始化
    Float("unkn3_0"),
    Float("unkn3_1"),
    Float("unkn4"),
    Int("unknBitmask5"),
    Int("unknFixed6"),
])
FAKEDOF_SCHEMA = FAKEDOF_ATTR.schema
assert _schema_size(FAKEDOF_SCHEMA) == 32, \
    f"FAKEDOF_SCHEMA size mismatch: {_schema_size(FAKEDOF_SCHEMA)}"
