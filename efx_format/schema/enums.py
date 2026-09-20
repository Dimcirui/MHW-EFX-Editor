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
# EMITTERSHAPE3D.rayCastDependency：官方讲座 Inspector 完整下拉（docs/OFFICIAL_DEFAULTS_AND_ENUMS.md
# §2.1），是一种运算模式（决定生成范围如何与地面/障碍物的射线检测结果结合），不是引用。
# TypeLightning.TerminalShape 里同名字段目前未能在 schema 里定位（该结构仍是一整块 opaque
# float 数组），暂不落地。
ENUM_RAYCAST_DEPENDENCY = EnumDef("RayCastDependency", [
    (0, "None", "无"),
    (1, "Min", "取最小值"),
    (2, "Max", "取最大值"),
    (3, "Multiply", "相乘"),
    (4, "Equal", "相等"),
    (5, "Offset", "偏移"),
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

# RAYCAST.rayCastAttr（原 spacer，2026-09-19 用户截图核对+全语料 1363 块位分布坐实）：
# 官方讲座截图 §10.5.1 显示 SCR 默认勾选、OBJ 默认不勾选；语料里这个字段恒为
# 0xFFFFFFxx（bit2 以上恒 1，此前误判为纯占位），只有 bit0/bit1 变化——bit0 置位率
# 97.1%（=SCR，默认勾选），bit1 置位率 23.5%（=OBJ，少数勾选）。
BITS_RAYCAST_ATTR = [(0x1, "SCR", "SCR"), (0x2, "OBJ", "OBJ")]

# RAYCAST.rayCastFlags（原 unknownBitmask2，2026-09-19 用户截图核对）：官方讲座显示
# SyncSpawnFrame/RayCastOnce 均默认不勾选；语料里这个字段 90.8% 恒为 0，bit0/bit8
# 各自独立偶尔置位（2.1%/7.1%），与"两个默认关闭的独立勾选框"形态吻合。
BITS_RAYCAST_FLAGS = [(0x1, "SyncSpawnFrame", "同步生成帧"), (0x100, "RayCastOnce", "仅一次")]

# SPAWN.spawnFlags（原 unknBitmask31）：官方全语料(112573 块)穷举，可混合位只到 bit5
# （值 32），bit6 及以上从未出现——数量正好对上官方讲座 Spawn 面板截图的 6 个默认不勾选
# 的独立勾选框（UseSpawnFrame/RingBufferMode/RayCastHitOnly/RayCastDependency/
# InitializeFull/InterporatePos，2026-09-19 用户提供截图）。
# 三条交叉验证坐实了 4 个位：
#   ① 用"该 entry 是否同时挂了 RAYCAST 属性"验证：bit1/bit2 与 RAYCAST 共现率分别是
#      无 RAYCAST 时的 105x/144x（其余位无此相关性），确认 bit1/bit2 是 RayCastHitOnly/
#      RayCastDependency 这一对——具体谁是谁未定，按截图顺序定为 bit1=RayCastHitOnly、
#      bit2=RayCastDependency（弱证据：两位几乎互斥、极少同时为1，不是"依赖"关系那种
#      强共现，只是按名字顺序占位）。
#   ② 用户提出 SPAWN.spawnFrame（原 instanceCountUnknLimit）非零 vs 本字段各位共现：
#      bit5 命中率是其余位的 24~730 倍（bit5=167.1x，其余位 0.2x~6.8x），确认 bit5=
#      UseSpawnFrame——3770 个 bit5=1 的块里 3505 个(93%) spawnFrame 确实非零，是
#      spawnFrame 的启用开关。
#   ③ 用户提供《怪物猎人：荒野》（RE Engine，设计理念一脉相承可作参考）里 RingBufferMode
#      的实测画像，跟 bit0 交叉核对：启用频率几乎一致（0.7346% vs 荒野 0.74%）、搭配
#      "无限循环"(loopNum=(0,0)) 的比例高度吻合（69.9% vs 24.0% 基线，对应荒野
#      68.6% vs 24.0%）、entry 命名同样大量出现 GPU/GPUP/GPUP_yoin 及水/电/碎片一类
#      "持续流"效果名。唯一方向相反的是 MaxParticles——MHW 这边关联的是大缓冲池
#      （中位数 240 vs 基线 4），不是荒野那种"单粒子反复重画"，推测两代引擎具体实现
#      方式不同（MHW 没有荒野那套 GPU 渲染管线块类型，只能用传统大缓冲池模拟持续流），
#      但另外三条证据够强，确认 bit0=RingBufferMode。
# 剩余 bit3/4：把已确认的 4 个位摆在一起看——RingBufferMode(bit0)→RayCastHitOnly(bit1)→
# RayCastDependency(bit2) 正好是截图顺序里"从 RingBufferMode 开始"的连续三项，
# UseSpawnFrame(bit5) 则是绕到最后——相当于截图顺序整体左移一位、UseSpawnFrame 转到
# 末尾的循环排列。按同一个循环规律续下去，bit3/4 自然落在 InitializeFull/InterporatePos，
# 不再是孤立的截图顺序猜测，但仍未实机验证。
BITS_SPAWN_FLAGS = [
    (0x01, "RingBufferMode", "RingBufferMode"),
    (0x02, "RayCastHitOnly", "RayCastHitOnly（弱假设）"),
    (0x04, "RayCastDependency", "RayCastDependency（弱假设）"),
    (0x08, "InitializeFull", "InitializeFull（假设）"),
    (0x10, "InterporatePos", "InterporatePos（假设）"),
    (0x20, "UseSpawnFrame", "UseSpawnFrame"),
]

# PLEMISSIVE.emitMaskFlags（原 area_of_aura）：4 位掩码，全语料从未出现 bit4 及以上。
# devlecture 面板在这个区域一共有 3 个勾选框（RimAlphaCorrect/OverrideSecondaryEmitControl/
# EnableMaskAnim；第 4 个 EnableUseEmitMask 已确认落在独立字段 enableUseEmitMask 上，不在
# 这个位掩码里）。bit1/bit2 关联检验方向清晰，bit0/bit3 证据打平分不清谁是 EnableMaskAnim，
# 只标一个"弱假设"、另一个先留空——2026-09-19。
BITS_PLEMISSIVE_EMIT_MASK = [
    (0x1, "EnableMaskAnim", "启用遮罩动画（弱假设，也可能是 bit3）"),
    (0x2, "OverrideSecondaryEmitControl", "覆盖次级发光控制"),
    (0x4, "RimAlphaCorrect", "边缘光透明度修正"),
    (0x8, "unkn3", "未知（可能是 EnableMaskAnim）"),
]

# ROTATEANIM 的 spinAxisMask：**不是** XYZ 轴掩码。原先按 bit0=X/bit1=Y/bit2=Z 读，
# 与官方语料对不上——31535 个块里用到 bit0~bit6（OR=127，36 种取值，最大 88，0 从未出现），
# 而 mask 与 spin_velocity 哪几轴非零毫无对应关系（mask=1 配三轴全非零 872 块、mask=3 配
# 只有 X 非零 887 块…）。按旧读法，自旋模式里 67.6% 的块会有「给了角速度的轴被掩码挡掉」，
# 作者不会这么写。各位含义未知，故用中性标签。
# ⚠ 模拟层（sim/behaviors/rotateanim.py）因此**不看**这个字段，只按 spin_velocity 逐轴取值。
# 逐位占比：bit0 64.0% / bit1 47.6% / bit2 21.7% / bit3 16.4% / bit4 7.8% / bit5 0.05% / bit6 0.01%
BITS_ROTATEANIM_SPIN_FLAGS = [
    (1 << _i, "Bit %d" % _i, "位 %d" % _i) for _i in range(7)
]
#: 旧名（曾被当成 XYZ 轴掩码）。保留别名免得外部引用炸掉，新代码用上面那个名字。
BITS_SPIN_AXIS = BITS_ROTATEANIM_SPIN_FLAGS
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

# LightGroup（MESH.affectedByLight 与 BILLBOARD3D.lightGroup 共用，2026-09-19 用户核对
# 官方讲座 Type Billboard 面板截图坐实）：官方双列布局
#   左列：VFX  NPC  LIGHT_OBJ  GROUP_6
#   右列：PLAYER/OTOMO  ENEMY  SCR  EYE/LENS
# 用户指出若按"从0计数、横着读"（每行先左列再右列）排列，GROUP_6 恰好落在 idx=6，
# 不像巧合，故按行优先顺序定位序：
#   bit0=VFX bit1=PLAYER/OTOMO bit2=NPC bit3=ENEMY bit4=LIGHT_OBJ bit5=SCR
#   bit6=GROUP_6 bit7=EYE/LENS
# 全语料交叉验证：BILLBOARD3D.unkn8 中 bit0 置位率 78.94%（=VFX，与截图"默认勾选"
# 一致）、bit5 15.32%（=SCR，二者第二常见，与文档"SCR 这个标识在 LightGroup 里也
# 出现"的旁注吻合）；MESH.affectedByLight 中同样是 bit0(46.9%)/bit5(47.8%) 两位独大，
# 两个块用的是同一套位序。bit7(EYE/LENS) 只出现在 all_value=255（全选哨兵）里，从不
# 单独出现——255 是独立的"全部受光照影响"值，非 7 位勾选框的自然并集(127)。
# 2026-09-19 排查其余渲染主体（BILLBOARD2D/PLANE/RIBBON/RIBBONBLADE/STRAINRIBBON/
# TUBELIGHT/LIGHTNING）后确认还有两处用同一张表：RIBBON.unknBitmask22_1（原
# BITS_RIBBON_UNKN22_1 占位表，bit0 73.94%/bit5 11.39%）、PLANE.unknBitmask7_0
# （bit0 77.19%/bit5 16.72%）——同一批 render body 共用的字段，已统一改名 lightGroup。
# 其余几个块的候选字段逐个核对过位分布，都对不上这个签名（没有"bit0 占七成+bit5 第二"
# 的形态），判定没有 LightGroup。
BITS_LIGHT_GROUP = [
    (0x01, "VFX", "VFX"),
    (0x02, "Player/Otomo", "玩家/艾路"),
    (0x04, "NPC", "NPC"),
    (0x08, "Enemy", "敌人"),
    (0x10, "Light Object", "光照物体"),
    (0x20, "SCR", "SCR"),
    (0x40, "Group 6", "组 6"),
    (0x80, "Eye/Lens", "眼睛/镜头"),
]

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
# 2026-09-19 按官方讲座 §2.1 完整下拉核对，EN 标签改用官方词面（DIRECTION/NORMAL/
# RADIAL/EMITTER_MOVE），ZH 保留实机考据措辞不变（NORMAL 曾实测更接近"常规/标准"而非
# 字面"表面法线"，见 VELOCITY3D schema 注释，故不直译成"法线"）。
_VELOCITY_TYPE = EnumDef("VelocityType", [
    (0, "Direction", "定向"),
    (1, "Normal", "定向扩散"),
    (2, "Radial", "径向"),
    (3, "Emitter Move", "发射器运动"),
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
