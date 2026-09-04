# -*- coding: utf-8 -*-
"""
efx_format/schema/enums.py — 共享枚举 / 位定义
"""
from .fields_model import EnumDef, BitDef, BitEnum

# ─────────────────────────────────────────────────────────────────────────────
# 共享枚举 / 位定义——选项据 annotations.py / 实机记忆 / 行内考据。
# 供各块字段引用；enum/bitmask 只改 UI widget 元数据，底层 spec（int/short）不变→byte 不变。
# ⚠ 越界值（如 shapeType≥3、homingTarget 的 cycle 值）由 Blender 层回退显示原整数。
# ─────────────────────────────────────────────────────────────────────────────

ENUM_SHAPE_TYPE3D = EnumDef("ShapeType3D", [
    (0, "Box", "立方体"),
    (1, "Sphere", "球体"),
    (2, "Cylinder", "圆柱体"),
    (3, "Point", "点"),
])
# EMITTERSHAPE3D.rangeDivideAxis：仅 Box 生效，选沿哪个轴细分；不受 localRotation 影响。
ENUM_RANGE_DIVIDE_AXIS = EnumDef("RangeDivideAxis", [
    (0, "X-axis", "X 轴"),
    (1, "Z-axis", "Z 轴"),
    (2, "Y-axis", "Y 轴"),
])
# EMITTERSHAPE2D 的同名字段**编号不一样**：用户 2026-09-04 实测 0=Y、1=X（2D 没有 Z 轴，
# 3D 那张表照搬过来第 1 项就是错的）。语料 292 例取值 {0:94%, 1:2%, 2:4%}，2 的含义未知，
# 不列进枚举——越界值由 Blender 层回退显示原整数。
ENUM_RANGE_DIVIDE_AXIS_2D = EnumDef("RangeDivideAxis2D", [
    (0, "Y-axis", "Y 轴"),
    (1, "X-axis", "X 轴"),
])
# EMITTERSHAPE3D.rotationCorrect：照搬续作(RE Engine) EFXEnums.cs 的 RotationCorrectType。
# 官方语料取值 [0,1,3,5,7] 不完全落在 0~4 内，越界值由 Blender 层回退显示原整数。
ENUM_ROTATION_CORRECT_TYPE = EnumDef("RotationCorrectType", [
    (0, "None", "不修正"),
    (1, "Parallel Camera", "与摄像机平行"),
    (2, "Parallel Camera (Y axis only)", "与摄像机平行（仅 Y 轴）"),
    (3, "To Camera", "朝向摄像机"),
    (4, "To Camera (Y axis only)", "朝向摄像机（仅 Y 轴）"),
])
ENUM_SHAPE_TYPE2D = EnumDef("ShapeType2D", [
    (0, "Square", "方形"), 
    (1, "Circle", "圆形"), 
    (2, "Point", "点"),
])
# 2026-07-31 用户实机测试重新整理（旧 5 个名字都不准）：反弹次数(bounceCount)次后，
# 最后一次接触地面（例如反弹 2 次，实际共接触地面 3 次）触发下列收尾行为：
# 0=直接穿透，不反弹；1=反弹完毕后最后一次触地强制消亡；2=反弹完毕后直接渐隐+消亡；
# 3=反弹完毕后停留在地面；4=反弹完毕后直接坠落穿透（不再判定地面碰撞），不强制消亡——
# 若粒子寿命无限则持续存在，跟 2 的区别就是不强制杀死粒子。
ENUM_COLLISION_PHYSICS = EnumDef("CollisionPhysics", [
    (0, "Fall Through", "穿透坠落"),
    (1, "Bounce Then Kill", "反弹后强制消亡"),
    (2, "Bounce Then Fade", "反弹后渐隐消亡"),
    (3, "Bounce Then Stay", "反弹后停留地面"),
    (4, "Bounce Then Fall Through", "反弹后穿透坠落"),
])
# PTCOLLISION.impactPlayTriggerMode：ieIndex 引用的 Play 在反弹序列里何时触发。
# 2026-07-31 用户实机测试确认；具体行为见 attributes.py PtCollision schema 头注释。
ENUM_IMPACT_PLAY_TRIGGER_MODE = EnumDef("ImpactPlayTriggerMode", [
    (0, "Every Impact", "每次触地"),
    (1, "Early Impacts", "前 N 次触地"),
    (2, "Final Impact", "仅最后一次触地"),
])
#  2026-08 用户实机确认：与 LIFE 的淡入/持续/淡出三段寿命节奏一一对应
#  （fadeInDuration/duration/fadeOutDuration，见 attributes.py LIFE_ATTR）。
ENUM_PTLIFE_STATUS = EnumDef("PtLifeStatus", [
    (0, "On Spawn", "生成时"),
    (1, "Fade In", "淡入时"),
    (2, "Sustain", "持续时"),
    (3, "Fade Out", "淡出时"),
    (4, "On Death", "死亡时"),
    (-1, "Unknown", "未知"),
])
ENUM_HOMING_TARGET = EnumDef("HomingTarget", [
    (0, "Spawn Point", "生成点"), 
    (1, "Model Origin", "模型原点"),
    (2, "World Origin", "世界原点"), 
    (3, "World Origin", "世界原点"),
])
# 2026-07-30 实测重命名：五个值不是五种"力"，而是「以归航目标为球心、半径 =
# forceFieldRadius 的球」上挂的五种规则。1/3 都会剔除**在球内出生**的粒子（3 额外
# 关掉球内的转向力）；2/4 是一对，用 forceFieldSpeedScale 缩放速度，2 作用于球内、
# 4 作用于球外。旧名 Normal/Exclusion/Deceleration/Escape-Catch/Acceleration 里
# "Acceleration"（加速场）尤其误导——它不加速任何东西，只是把球外的速度缩放掉。
ENUM_HOMING_FORCEFIELD = EnumDef("HomingForceFieldMode", [
    (0, "None", "无"),
    (1, "Cull Spawn Inside", "内部出生剔除"),
    (2, "Slow Inside", "内部减速"),
    (3, "No Turn Inside", "内部不转向"),
    (4, "Slow Outside", "外部减速"),
])
ENUM_HOMING_VANISH = EnumDef("HomingVanishMode", [
    (0, "None", "不触发"), 
    (1, "Cancel Infinite Life", "取消无限寿命"),
    (2, "Vanish Immediately", "立即消失"),
])
ENUM_RENDER_LAYER = EnumDef("RenderLayerMode", [
    (0, "3D Billboard", "3D Billboard"), 
    (2, "Plane", "Plane"),
    (3, "Bypass Tonemap", "无视色调滤镜"),
    (6, "3D Billboard v6", "3D Billboard 变体6"), 
    (7, "3D Billboard v7", "3D Billboard 变体7"),
    (8, "3D Billboard v8", "3D Billboard 变体8"), 
    (9, "3D Billboard v9", "3D Billboard 变体9"),
])
ENUM_SHADER_CONTROL = EnumDef("ShaderControlFlag", [
    (0, "No Alpha", "无 alpha"), 
    (1, "Alpha Enabled", "启用 alpha"),
    (2, "Emissive", "自发光"), 
    (3, "Inverted Color + Alpha", "反色 + alpha"), 
    (6, "Greyscale", "灰度"),
])
ENUM_ROTATION_MODE = EnumDef("RotationMode", [
    (0, "Plane Rotation", "平面旋转系"), 
    (1, "Plane + Random Dir", "平面旋转 + 随机正反"),
    (2, "Spin Velocity", "自旋速度系"), 
    (3, "Spin + Random Dir", "自旋速度 + 随机正反"),
])

# PARENTOPTIONS 逐轴跟随模式：0/1/2 三字段共享，值 3 各字段不同（见下）
_TRACKING_BASE = [
    (0, "Track Map Center Absolutely", "绝对追踪地图中心"),
    (1, "Track Player Movement", "追踪玩家移动"),
    (2, "Do not track further", "不再追踪后续移动"),
]
ENUM_TRACKING_POS = EnumDef("TrackingModePos",
    _TRACKING_BASE + [(3, "Ignore Basic Transform", "忽略基础变换")])   # translation / scale
ENUM_TRACKING_ANGLE = EnumDef("TrackingModeAngle",
    _TRACKING_BASE + [(3, "Snap to Angle And Track", "对齐到角度并追踪")])  # angle

# MESH.tracking_flags：社区文档给的 9 个值(0~8)各自含义互不相关（如 5/7 都叫
# "Disappears" 但仍是两个独立编号），非可叠加位——语料只观测到 0/1/2/4/6/8/10，
# 10 不在文档表内，暂标 Unknown；官方语料从未见 9，非文档遗漏即引擎未使用。
ENUM_MESH_TRACKING_FLAGS = EnumDef("MeshTrackingFlags", [
    (0, "Guide Source", "引导源"),
    (1, "Away from Source", "远离源"),
    (2, "Look Away From Camera", "背对摄像机"),
    (3, "WTF Occupies Entire Map", "WTF 占满整张地图"),
    (4, "Guide Camera", "引导摄像机"),
    (5, "Disappears", "消失"),
    (6, "Don't Track Rotation At All", "完全不追踪旋转"),
    (7, "Disappears", "消失"),
    (8, "Perpendicular to Ground, Don't Track", "垂直于地面且不追踪"),
    (10, "Unknown (10)", "未知 (10)"),
])

BITS_ENABLE_VELOCITY = [(0x1, "Enable Velocity", "启用速度"), (0x2, "Enable Acceleration", "启用加速度")]

# SPAWN.unknBitmask31：官方全语料(112573 块)穷举，可混合位只到 bit5（值 32），bit6 及以上
# 从未出现——6 个占位未知位，per-bit 语义待确认。
BITS_SPAWN_UNKN31 = [(1 << _i, "Unknown %d" % _i, "未知 %d" % _i) for _i in range(6)]

# RIBBON.unknBitmask22_1：官方语料(14677 块)穷举，可混合位到 bit6（值 64），bit0 单独占大多数，
# per-bit 语义待确认。
BITS_RIBBON_UNKN22_1 = [(1 << _i, "Unknown %d" % _i, "未知 %d" % _i) for _i in range(7)]
BITS_SPIN_AXIS = [(0x1, "X", "X"), (0x2, "Y", "Y"), (0x4, "Z", "Z")]
BITS_RANDOMFIX_TABLE = [(1 << _i, "Table %d" % _i, "表 %d" % _i) for _i in range(8)]

# FADEBYANGLE.coneVisibilityFlags：2026-07-29 用户实机全 8 组合穷举确认 bit0/bit1，
# bit2 仍未知（真值表见 attributes.py 内联注释）。
BITS_FADEBYANGLE_FLAGS = [
    (0x1, "Enable Double Cone", "启用双锥（镜像对立角）"),
    (0x2, "Exclude Cone", "排除锥体（反转可见性）"),
    (0x4, "Unknown", "未知"),
]

# PLANE.unknEnum5_1：全语料非零值恒含 bit0（{1,3,5,7}，从未出现 2/4/6），bit0 是总开关，
# bit1/bit2 是仅在 bit0 开启时才有意义的子模式；用户实机确认与朝向-摄像机关系有关，
# 具体子位语义未确认。gate_first=True。
BITS_PLANE_UNKN5_1 = [
    (0x1, "Enable", "启用（总开关）"),
    (0x2, "Unknown", "未知"),
    (0x4, "Unknown", "未知"),
]

# BILLBOARD3D / PLANE 的 applicationRule（打包 int32）。official 10084 文件实测干净：
# bit2/bit3 两个独立可混合开关（{0,4,8,12} 全组合出现）；bit4-5 三值互斥（{0,16,32}，never 48）；
# 其余位官方恒 0（残留可编辑保留）。混合/互斥判据据语义注释 + 全语料数据双证。
BITS_APPLICATION_RULE = [
    BitDef(0x04, "Enable Flowmap", "启用流动贴图"),
    BitDef(0x08, "Freeze After One Play", "播放一次后冻结"),
    BitEnum(0x30, [
        (0, "Default", "默认"),
        (1, "Mode 1", "模式1"),
        (2, "Mode 2", "模式2"),
    ], "Application Mode", "应用模式"),
]

# UVSEQUENCE 的 loopingMode（打包单字节）。四个互斥 2 位组（用户实机 + 全语料实测）：
# playbackMode(bit0-1) / flipHorizontal(bit2-3) / flipVertical(bit4-5) / direction(bit6-7)。
# 翻转两轴各 0=不翻/1=固定翻/2=随机翻（3 非法）。此建模顺带把原 flipCode 拆成两轴独立下拉。
_FLIP_OPTS = [(0, "No Flip", "不翻转"), (1, "Flip", "固定翻转"), (2, "Random Flip", "随机翻转")]
BITS_LOOPING_MODE = [
    BitEnum(0x03, [
        (0, "Start Frame Only", "只显示起始帧"),
        (1, "Loop", "循环"),
        (2, "Play Once Then Vanish", "播放一次后消亡"),
        (3, "Play Once Then Hold", "播放一次后定格"),
    ], "Playback Mode", "播放模式"),
    BitEnum(0x0C, _FLIP_OPTS, "Flip Horizontal", "水平翻转"),
    BitEnum(0x30, _FLIP_OPTS, "Flip Vertical", "垂直翻转"),
    BitEnum(0xC0, [
        (0, "Forward", "正向"),
        (1, "Reverse", "倒放"),
        (2, "Random Direction", "随机正倒"),
    ], "Direction", "播放方向"),
]

# MESH.affectedByLight：官方语料实测 7 个可混合位（bit0~6，值 1/2/4/8/16/32/64，各种
# 组合都出现），加一个从不单独出现的 bit7（值 128）——只在 all_value=255（全位）时才出现，
# 说明 255 是独立的"全部受光照影响"哨兵，非 7 位勾选框自然并集(127)。各位具体对应哪种光源
# /光照类型尚未确认，暂用占位标签。
BITS_AFFECTED_BY_LIGHT = [(1 << _i, "Light Bit %d" % _i, "光照位 %d" % _i) for _i in range(7)]

_AXIS_DIRECTION6 = EnumDef("AxisDirection6", [
    (0, "Left", "左"),  # +X
    (1, "Up", "上"),    # +Y
    (2, "Front", "前"), # +Z
    (3, "Right", "右"), # -X
    (4, "Down", "下"),  # -Y
    (5, "Back", "后"),  # -Z
])
# RAYCAST.direction 并入 AxisDirection6（2026-08-18，用户定调）。
# 原先 RAYCAST 自带一张表，1/4 与 AxisDirection6 互换（旧表 1=下 4=上）。两边只可能对一个，
# 用户判断是 RAYCAST 那张错了；语料也支持：1363 个 RAYCAST 块里 1 和 4 合计占 66.7%，
# 按 AxisDirection6 读，占比最高的 4(36.0%) 是「下」——射线朝下探地面是最合理的主用法，
# 按旧表则变成「上」最多。⚠ 仍未实机确认，若日后测出 RAYCAST 确实自成一套，改回独立 EnumDef 即可。
ENUM_RAYCAST_DIR = _AXIS_DIRECTION6

_ROT_ORDER6 = EnumDef("RotOrder", [
    (0, "XYZ", "XYZ"), (1, "XZY", "XZY"), (2, "YXZ", "YXZ"),
    (3, "YZX", "YZX"), (4, "ZXY", "ZXY"), (5, "ZYX", "ZYX"),
])
# TRANSFORM3D/EMITTERSHAPE3D/RIBBON 的 rotationOrder 用另一套取值→顺序映射（据 TRANSFORM3D 注释；
# 与 VELOCITY3D 的 _ROT_ORDER6 不同，两者实测不一致，见记忆 velocity3d-unknaxis-rotation-order-test）。
# 2026-07-30 用户实机测试 EMITTERSHAPE3D 确认 4=ZXY（原表误标为 4=YXZ、2=ZXY，已对调两项；
# 三个 attr 共用此表，同步生效）。
_TRANSFORM_ROT_ORDER = EnumDef("TransformRotOrder", [
    (0, "XYZ", "XYZ"), (1, "YZX", "YZX"), (2, "YXZ", "YXZ"),
    (3, "ZYX", "ZYX"), (4, "ZXY", "ZXY"), (5, "XZY", "XZY"),
])
_VELOCITY_TYPE = EnumDef("VelocityType", [
    (0, "Directional", "定向"),
    (1, "DirectionalSpread", "定向扩散"),
    (2, "Radial", "径向"),
    (3, "EmitterMotion", "发射器运动"),
])

# BILLBOARD3D / PLANE / BILLBOARD2D 的 blendMode（着色器混合模式；RE Engine 对应 'AlphaRate'）。
ENUM_BLEND_MODE = EnumDef("BlendMode", [
    (0, "Alpha Blend", "Alpha 混合"),
    (1, "Additive", "Add 叠加"),
])

# RIBBON.ribbonMode（原 unknEnum4_1）：三种条带形态，用户实机确认(2026-07-30)。命名对齐续作
# (RE Engine) 拆分出的同族 ribbon 类型——续作把 MHW 这个"一个属性 + 模式开关"的设计重构成了
# 各自独立的类型（TypeRibbonFollow/Length/Chain…），故此处直接沿用其类型名。
ENUM_RIBBON_MODE = EnumDef("RibbonMode", [
    (0, "Ribbon Follow", "轨迹跟随"),
    (1, "Ribbon Length", "定长面片"),
    (2, "Ribbon Chain", "柔体链"),
])

# UVSEQUENCE 的 loopingOrientation（贴图朝向；与水平/垂直翻转独立）。
ENUM_LOOPING_ORIENTATION = EnumDef("LoopingOrientation", [
    (0, "Normal", "正常"),
    (1, "Rotate 90° CW", "顺时针90°"),
    (2, "Rotate 90° CCW", "逆时针90°"),
    (3, "Random", "随机"),
])

# REFRACTION.pixelNormalOffset：官方语料仅见 0/1/2，用户实机确认(2026-08-02)三档效果。
ENUM_REFRACTION_OFFSET = EnumDef("RefractionOffset", [
    (0, "None", "不偏移"),
    (1, "Single", "单次偏移"),
    (2, "Multiple", "多重偏移"),
])
