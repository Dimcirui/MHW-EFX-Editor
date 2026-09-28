"""属性字段的双语 tooltip 与 RE 字段名对照表。

FIELD_ANNOTATIONS 的键为 (大写类型名, schema ori_name)，值为 EN/ZH 文本。数组字段按其
单个 schema 字段名查找；get_annotation() 按当前 UI 语言选取文本，缺失时回退英文。

FIELD_OFFICIAL_NAMES 只供开发对照，不进入 tooltip，也不改变 schema 标签、字段索引或文件布局解释。
"""

# ─────────────────────────────────────────────────────────────────────────────
# RE Engine 字段名交叉参考。
# 键：(TYPE_NAME 大写, schema ori_name)；值：(字段名, 哈希字符串, 置信度)。
# 内存字段名与 .efx 文件布局不必一一对应，因此该表不能替代 schema 定义。
# ─────────────────────────────────────────────────────────────────────────────

FIELD_OFFICIAL_NAMES = {
    # ── PARENTOPTIONS ─────────────────────────────────────────────────────────
    ("PARENTOPTIONS", "relationPos"): ("mRelationPos[XYZ]", "0xC8E41E1E", "确认"),
    ("PARENTOPTIONS", "relationRot"):       ("mRelationRot[XYZ]", "0x2DAC4052", "确认"),
    ("PARENTOPTIONS", "relationScl"):       ("mRelationScl[XYZ]", "0x1E11460A", "确认"),

    # ── 语义映射 ───────────────────────────────────────────────────────────────
    ("TRANSFORM3D", "translate"): ("pos[XYZ]", "0x8E8AFE06", "确认"),
    ("TRANSFORM3D", "rotate"):    ("rot[XYZ]", "0xF105BBE3", "确认"),
    ("TRANSFORM3D", "resize"):    ("scl[XYZ]", "0x9486DF23", "确认"),
    ("BILLBOARD3D", "color"):     ("Color",    "0x58689812", "确认"),
    ("BILLBOARD3D", "colorRange"): ("ColorRange", "0xC216C23D", "确认"),
    ("PLANE", "color"):      ("Color",      "0x58689812", "确认"),
    ("PLANE", "colorRange"): ("ColorRange", "0xC216C23D", "确认"),
    ("MESH", "scale"):            ("SizeX/Y/Z",    "0x241CAED2", "确认"),
    ("MESH", "rotation"):         ("RotationX/Y/Z","0x002FF505",  "确认"),
    ("MESH", "color"):               ("Color",              "0x58689812", "确认"),
    ("MESH", "colorRange"):          ("ColorRange",          "0xC216C23D", "确认"),
    ("MESH", "emissiveColor"):       ("EmissiveColor",       "0x608DCF8D", "确认"),
    ("MESH", "emissiveColorRange"):  ("EmissiveColorRange",  "0x7F2CEB57", "确认"),
    ("VELOCITY3D", "gravity"):    ("Gravity", "0x6A5FE3C4", "确认"),
    ("EMITTERSHAPE3D", "localRotationX"): ("LocalRotationX", "0x701FE225", "确认"),
    ("EMITTERSHAPE3D", "localRotationY"): ("LocalRotationY", "0x0718D2B3", "确认"),
    ("EMITTERSHAPE3D", "localRotationZ"): ("LocalRotationZ", "0x9E118309", "确认"),
    ("EMITTERSHAPE3D", "rangeXYZ"):       ("RangeMin/Max[XYZ]", "0x760F3D43", "确认"),
    ("SCALEANIM", "sizeScalarAdd"): ("SizeScalarAdd", "0xC24DF97C", "确认"),
    ("SCALEANIM", "sizeXAdd"):       ("SizeXAdd", "0x909EC047", "确认"),
    ("SCALEANIM", "sizeYAdd"):       ("SizeYAdd", "0x2822A722", "确认"),
    ("SCALEANIM", "sizeZAdd"):       ("SizeZAdd", "0x3A9708CC", "确认"),
    ("ROTATEANIM", "spin_velocity"):    ("RotationAdd", "0xE81961E4", "确认"),
    ("LIFE", "keepFrame"):               ("KeepFrame", "0xBD8D5203", "确认"),
}


# ─────────────────────────────────────────────────────────────────────────────
    # 双语 tooltip 字典
# ─────────────────────────────────────────────────────────────────────────────

#: 各渲染体「启用自发光」（ori_name 仍为 blendMode）共用的提示
_EMISSIVE_TIP_EN = ("Makes Brightness take effect: the colour is multiplied by Brightness and "
                    "high values bloom. How the particle combines with the background is set by "
                    "Shader Settings' Blend State.")
_EMISSIVE_TIP_ZH = ("开启后亮度生效：颜色乘以亮度，亮度高时会溢光。与背景的混合方式由 Shader "
                    "Settings 的混合方式决定。")

#: LIGHTNING 三代分支（0 = 主干）通用提示；_LIGHTNING_BRANCH_TIPS_BY_TIER 按代覆盖
_LIGHTNING_BRANCH_TIPS = {
    "size": ("Section length, fixed at 96. Do not change it; 0 may crash the game.",
             "段长度，固定为 96，请勿修改；设为 0 可能崩溃。"),
    "flags": ("Structure flags. Do not modify; changing them crashes the game.",
              "结构标志，请勿修改，改动会导致崩溃。"),
    "count": ("Purpose unknown; may be the number of bolts in this tier.",
              "作用未知，可能是这一代的条数。"),
    "unkn2": ("Purpose unknown.", "作用未知。"),
    "unkn3": ("Purpose unknown.", "作用未知。"),
    "lowDetailNum": ("Number of coarse kinks along the bolt.", "闪电上粗折点的数量。"),
    "lowDetailWidth": ("How far the coarse kinks stray from a straight line. Smaller is "
                       "straighter; larger spreads wider and looks more random.",
                       "粗折点偏离直线的幅度。越小越直，越大越散、随机感越强。"),
    "lowDetailWidthCoef": ("Works like Low Detail Width with a stronger effect. Common values "
                           "0.25~1.",
                           "作用与粗折幅度相近，影响更明显。常见值为 0.25～1。"),
    "highDetailNum": ("Number of fine kinks layered on top of the coarse ones. At 0, High "
                      "Detail Width has no effect.",
                      "叠加在粗折之上的细折点数量。为 0 时细折幅度不生效。"),
    "highDetailWidth": ("How far the fine kinks stray. Only works when High Detail Num is "
                        "not 0.",
                        "细折点偏离的幅度。仅在细折点数不为 0 时生效。"),
    "highDetailWidthCoef": ("Purpose unknown.", "作用未知。"),
    "intensity": ("Brightness. 0 = no glow, larger = stronger glow, negative turns the bolt "
                  "black. A jitter close to or above the value makes bolts flicker.",
                  "亮度。0 不发光，越大辉光越强，负值变黑。抖动接近或超过亮度时会忽明忽暗。"),
    "length": ("Length. With jitter 0 every bolt has the same length.",
               "长度。抖动为 0 时每道长度相同。"),
    "thickness": ("Line thickness.", "线条粗细。"),
    "headScale": ("Possibly the width multiplier at the head. Common value 1.",
                  "可能是头端的宽度倍率。常见值为 1。"),
    "tailScale": ("Possibly the width multiplier at the tail. Common value 1.",
                  "可能是尾端的宽度倍率。常见值为 1。"),
    "headAlpha": ("Possibly the opacity at the head. Common value 1.",
                  "可能是头端的不透明度。常见值为 1。"),
    "tailAlpha": ("Possibly the opacity at the tail. Common values 1 or 0.",
                  "可能是尾端的不透明度。常见值为 1 或 0。"),
}
_LIGHTNING_BRANCH_TIPS_BY_TIER = {
    0: {
        "count": ("Fixed at 1; setting it to 0 crashes the game.",
                  "固定为 1；设为 0 会导致崩溃。"),
        "unkn2": ("Do not modify; changing it crashes the game.", "请勿修改，改动会导致崩溃。"),
        "unkn3": ("Do not modify; changing it crashes the game.", "请勿修改，改动会导致崩溃。"),
        "lowDetailNum": ("Number of coarse kinks along the trunk. 0 makes the motion stutter, "
                         "1 is nearly straight, very large values coil into a ball. Stacks "
                         "with High Detail Num; either one too low makes it stutter.",
                         "主干上粗折点的数量。0 时运动顿挫，1 接近直线，很大时缠成一团。与细折点"
                         "数叠加，任一过低都会顿挫。"),
        "highDetailNum": ("Number of fine kinks layered on the trunk. -1 hides the trunk.",
                          "叠加在主干粗折之上的细折点数量。设为 -1 时主干消失。"),
        "headScale": ("Possibly the width multiplier at the head. Setting it to 0 hides the "
                      "trunk and leaves only the branches. Common value 1.",
                      "可能是头端的宽度倍率。设为 0 时主干消失，只留分支。常见值为 1。"),
        "tailScale": ("Possibly the width multiplier at the tail. Setting it to 0 hides the "
                      "bolt. Common value 1.",
                      "可能是尾端的宽度倍率。设为 0 时闪电消失。常见值为 1。"),
    },
    1: {
        "count": ("Number of branches per trunk. 0 cuts them down sharply but not to none; "
                  "500 or more makes them invisible and makes all effects in the scene "
                  "flicker; negative values crash. Keep it within 0~100.",
                  "每条主干上的分支数量。0 时明显减少但不会消失；500 以上分支不可见，并导致场景"
                  "内所有特效闪烁；负数会崩溃。建议 0～100。"),
        "unkn2": ("Affects the draw layer of both trunk and branches; too high makes nearby "
                  "effects flicker. Exact purpose unknown. Common values 0/1.",
                  "同时影响主干与分支的绘制层级，过大时近处特效会闪烁。具体作用未知。常见值为 "
                  "0/1。"),
        "unkn3": ("0 = one branch per spawn point, non-0 = two.",
                  "0 时每个生成点 1 条分支，非 0 时 2 条。"),
        "lowDetailNum": ("Number of coarse kinks along each branch; also changes the branch "
                         "wave frequency. Negative values crash.",
                         "分支上粗折点的数量，同时影响分支的波动频率。负数会崩溃。"),
        "lowDetailWidth": ("Maximum spread of the branches. At 0 they gather in but never "
                           "become a straight line.",
                           "分支扩散的最大范围。0 时收拢，但不会完全成直线。"),
        "lowDetailWidthCoef": ("Larger values give branches fewer kinks and a wider spread.",
                               "增大时分支折点变少、扩散变大。"),
        "highDetailNum": ("Number of fine kinks on each branch. At 0, High Detail Width has no "
                          "effect. 1~150 is typical; larger values make scene effects "
                          "flicker, negative values crash.",
                          "分支上细折点的数量。为 0 时细折幅度不生效；常用 1～150，过大会让场景特"
                          "效闪烁，负数会崩溃。"),
        "highDetailWidthCoef": ("No visible effect.", "修改后无可见效果。"),
        "length": ("Branch length. 0 hides the branches, negative reverses them. Branches "
                   "only grow sideways or backwards, never along the trunk's direction.",
                   "分支长度。0 时分支消失，负值反向。分支只朝侧面或后方生成，不沿主干前进方向。"),
    },
    2: {
        "count": ("Usually 0, occasionally 1~2. Changing it may crash the game.",
                  "通常为 0，偶尔为 1～2；改动可能崩溃。"),
        "unkn2": ("Usually 0. Changing it may crash the game.", "通常为 0；改动可能崩溃。"),
        "unkn3": ("Usually 0~2. Changing it may crash the game.", "常见值为 0～2；改动可能崩溃。"),
    },
}

#: LIGHTNING 末端形状字段 → Emitter Shape 3D 同名字段的显示名
_LIGHTNING_TERMINAL_NAMES = {
    "rangeXYZ": ("spawn range (offset / size)", "生成范围（偏移 / 尺寸）"),
    "shapeType": ("shape type", "形状类型"),
    "rangeDivideAxis": ("subdivision axis", "细分轴向"),
    "rotationCorrect": ("rotation correction", "旋转修正方式"),
    "localRotationX": ("local X rotation", "局部旋转 X"),
    "localRotationY": ("local Y rotation", "局部旋转 Y"),
    "localRotationZ": ("local Z rotation", "局部旋转 Z"),
    "rotationOrder": ("rotation order", "旋转顺序"),
    "scanAngleHorizontal": ("horizontal scan angle", "横向扫描角度"),
    "scanAngleVertical": ("vertical scan angle", "纵向扫描角度"),
    "rangeDivideHorizontalNum": ("horizontal division count", "横向等分数量"),
    "rangeDivideVerticalNum": ("vertical division count", "纵向等分数量"),
    "radiusEnd": ("end radius", "结束半径"),
    "radiusOrigin": ("start radius", "起始半径"),
    "rayCastDependency": ("ray cast dependency", "射线检测依赖"),
}


def _lightning_annotations():
    out = {}
    for n in range(3):
        tips = dict(_LIGHTNING_BRANCH_TIPS, **_LIGHTNING_BRANCH_TIPS_BY_TIER[n])
        for name, (en, zh) in tips.items():
            out[("LIGHTNING", "branch%d_%s" % (n, name))] = {"EN": en, "ZH": zh}
    for name, (en, zh) in _LIGHTNING_TERMINAL_NAMES.items():
        out[("LIGHTNING", "terminal_" + name)] = {
            "EN": "The terminal shape's %s; same meaning as in Emitter Shape 3D." % en,
            "ZH": "末端形状的%s，含义与 Emitter Shape 3D 的同名字段相同。" % zh,
        }
    out[("LIGHTNING", "terminal_unknFlag")] = {
        "EN": "Purpose unknown. Usually on.", "ZH": "作用未知，大多开启。"}
    out[("LIGHTNING", "useTerminalShape")] = {
        "EN": "Possibly turns on the terminal shape settings below. Usually off.",
        "ZH": "可能用于启用下方的末端形状设置。通常关闭。"}
    return out


FIELD_ANNOTATIONS = {

    # ─── TRANSFORM3D ──────────────────────────────────────────────────────────
    ("TRANSFORM3D", "rotationOrder"): {
        "EN": "4 is the most common value. 0-XYZ, 1-YZX, 2-YXZ, 3-ZYX, 4-ZXY, 5-XZY",
        "ZH": "4 为最常见值。0-XYZ，1-YZX，2-YXZ，3-ZYX，4-ZXY，5-XZY",
    },
    ("TRANSFORM3D", "translation_velocity_modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "rotation_velocity_modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "scale_velocity_modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "enableVelocityBitflag"): {
        "EN": "Two independent switches that can be combined: enable velocity, "
              "enable acceleration.",
        "ZH": "两个可同时开启的独立开关：启用速度、启用加速度。",
    },

    # ─── PARENTOPTIONS ────────────────────────────────────────────────────────
    ("PARENTOPTIONS", "relationPos"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Ignore Basic Transform",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=忽略基础变换",
    },
    ("PARENTOPTIONS", "relationRot"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Snap to Angle And Track",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=对齐到角度并追踪",
    },
    ("PARENTOPTIONS", "relationScl"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Ignore Basic Transform",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=忽略基础变换",
    },
    ("PARENTOPTIONS", "particleUseLocal"): {
        "EN": "When enabled, all particles will follow the emitter's movement.",
        "ZH": "启用后，所有粒子将会跟随发射器运动。",
    },
    ("PARENTOPTIONS", "constRelease"): {
        "EN": "Only meaningful when spawnTrack is enabled — after this "
              "many frames, tracking stops and the effect locks to its current position. "
              "0 = always keep tracking.",
        "ZH": "仅在 spawnTrack 启用时生效——达到该帧数后停止追踪，"
              "特效锁定在当前位置。0 = 始终追踪。",
    },
    ("PARENTOPTIONS", "constReleaseJitter"): {
        "EN": "Random variation paired with lockToPositionFrame.",
        "ZH": "与 lockToPositionFrame 配对的随机偏差。",
    },
    ("PARENTOPTIONS", "jointNo"): {
        "EN": "Bone Limitation. The index/serial number of the bone this is bound to. "
              "-1 = not bound to any bone, the most common setting; a bone index is "
              "specific to the model the effect was authored for, so it rarely "
              "transfers when the entry is reused elsewhere.",
        "ZH": "骨骼限制。绑定到的骨骼的序号。−1 = 不绑定任何骨骼，是最常见的设置；"
              "骨骼序号是针对特效原本所属模型的，把 entry 复用到别处时通常不通用。",
    },
    ("PARENTOPTIONS", "invalidParticleScale"): {
        "EN": "When on, particle size does not change with the Transform3D scale.",
        "ZH": "开启后，粒子大小不随 Transform3D 的缩放而变化。",
    },

    # ─── SPAWN ────────────────────────────────────────────────────────────────
    ("SPAWN", "emitterDelayFrame"): {
        "EN": "Frames to wait before the first burst. Applied once when the effect starts; "
              "revivals do not wait for it again.",
        "ZH": "第一批生成前的等待帧数。只在特效开始时生效一次，复活时不会再等。",
    },
    ("SPAWN", "emitterDelayFrameJitter"): {
        "EN": "Random jitter added to emitterDelayFrame.",
        "ZH": "叠加到 emitterDelayFrame 上的随机抖动。",
    },
    ("SPAWN", "revivalLoop"): {
        "EN": "Total number of rounds. After a round's last burst, the emitter waits Revival "
              "Interval frames and starts a new round at a new position. 1 = one round, no "
              "revival; 0 = revive forever.",
        "ZH": "一共跑几轮。一轮的最后一批发出后，等「复活间隔」帧，在新位置开始下一轮。"
              "1 = 只跑一轮、不复活；0 = 无限复活。",
    },

    # ─── LIFE ─────────────────────────────────────────────────────────────────
    ("LIFE", "timeToDeath"): {
        "EN": "Overrides indefinite lifespan",
        "ZH": "覆盖无限寿命",
    },
    ("LIFE", "timeToDeathJitter"): {
        "EN": "Overrides indefinite lifespan",
        "ZH": "覆盖无限寿命",
    },

    # ─── EMITTERSHAPE3D ───────────────────────────────────────────────────────
    ("EMITTERSHAPE3D", "localRotationX"): {
        "EN": "Overall rotation of the emitter shape.",
        "ZH": "生成形状的总体旋转。",
    },
    ("EMITTERSHAPE3D", "localRotationY"): {
        "EN": "Overall rotation of the emitter shape.",
        "ZH": "生成形状的总体旋转。",
    },
    ("EMITTERSHAPE3D", "localRotationZ"): {
        "EN": "Overall rotation of the emitter shape.",
        "ZH": "生成形状的总体旋转。",
    },
    ("EMITTERSHAPE3D", "rangeDivideHorizontalNum"): {
        "EN": "Number of horizontal divisions. Only the sphere and the cylinder use it: on a "
              "cylinder it slices the shape along its height (as seen from the side), on a "
              "sphere it splits the shape into that many cone surfaces (two of them degenerate "
              "to a line, their cone angle being 0). 0 or 1 = no division.",
        "ZH": "横向等分数量。只有球体和圆柱体用：圆柱体是沿高度把形状切成这么多片（正面"
              "看过去的切片），球体是把形状拆成这么多个圆锥面（其中两个锥角为 0、退化成"
              "线段）。0 或 1 = 不等分。",
    },

    # ─── VELOCITY3D ───────────────────────────────────────────────────────────
    ("VELOCITY3D", "baseAxis"): {
        "EN": "Base axis for speed (one of six cardinal axes, not a free direction vector), combined with rotationX/Y/Z to give the final direction. Only meaningful when velocityType=Directional. 0=left,1=up,2=front,3=right,4=down,5=back (in the game's default coordinate system +X=left, +Y=up, +Z=front).",
        "ZH": 'speed 的基准轴（六个基准轴之一，不是自由方向向量），与 rotationX/Y/Z 复合得到最终方向。仅在 velocityType=Directional 时有意义。0=左,1=上,2=前,3=右,4=下,5=后（游戏默认坐标系下 +X=左,+Y=上,+Z=前）。',
    },
    ("VELOCITY3D", "rotOrder"): {
        "EN": "A rotation-order enum: 0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX. Not the same numeric mapping as TRANSFORM3D's rotation order convention.",
        "ZH": "旋转顺序枚举："
              "0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX。跟 TRANSFORM3D 的旋转顺序惯例不是同一套数值映射。",
    },
    ("VELOCITY3D", "speedCoef"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("VELOCITY3D", "velocityType"): {
        "EN": "Decides how the particle's movement DIRECTION is determined (speed always comes "
              "from speed/acceleration; gravity is independent and always applies). "
              "0=DIRECTION (direction from baseAxis + rotation), 1=NORMAL "
              "(Vi=(size-1)*spawnPos+offset, normalized), 2=RADIAL (always moves outward, "
              "rotation/offset/size have no effect), 3=EMITTER_MOVE (inherits the "
              "emitter's own movement, gated by minMovementThreshold). ⚠ Values 4 and 5 also "
              "occur; their meaning is unknown.",
        "ZH": '决定粒子运动方向如何确定（速度始终由 speed/acceleration 决定，重力独立于此始终生效）。0=DIRECTION(由 baseAxis + rotation 决定方向)，1=NORMAL(即 Vi=(size-1)*生成坐标+offset 归一化模型)，2=RADIAL(始终向外运动，rotation/offset/size 均无效)，3=EMITTER_MOVE(继承 emitter 自身移动，受 minMovementThreshold 门控)。⚠ 另有 4/5 两个取值，含义未知。',
    },
    ("VELOCITY3D", "gravity"): {
        "EN": "Gravity. Always applies regardless of velocityType.",
        "ZH": "重力，不论 Velocity Type 如何，始终生效。",
    },

    # ─── SHADERSETTINGS ───────────────────────────────────────────────────────
    ("SHADERSETTINGS", "blendStateType"): {
        "EN": "How the particle is combined with the background; overrides the renderer's "
              "own setting. Opaque: alpha is ignored. Alpha: normal transparency. Additive: "
              "brightens the background and black disappears. Inverse Multiply: background "
              "× (1 − colour), so white turns it black. Multiply: background × colour, so "
              "white leaves it unchanged. PtBehavior (decal): used by decals. NoDraw: the "
              "particle itself is not drawn.",
        "ZH": "粒子与背景的混合方式，覆盖渲染体自身的设置。不透明：忽略 alpha。Alpha 混合："
              "普通半透明。加法：提亮背景，黑色部分不可见。反相乘法：背景 × (1 − 颜色)，白色会"
              "把背景压黑。乘法：背景 × 颜色，白色不改变背景。PtBehavior (decal)：贴花使用。"
              "不绘制(dummy)：粒子本身不绘制。",
    },
    ("SHADERSETTINGS", "objectInteractionFlag0"): {
        "EN": "Player Weapons and Interactables",
        "ZH": "玩家武器与可交互物",
    },
    ("SHADERSETTINGS", "objectInteractionFlag1"): {
        "EN": "Map geometry",
        "ZH": "地图几何体",
    },
    ("SHADERSETTINGS", "objectInteractionFlag2"): {
        "EN": "Weapon SubParts and Skybox",
        "ZH": "武器子部件与天空盒",
    },
    ("SHADERSETTINGS", "objectInteractionFlag3"): {
        "EN": "Player Skin",
        "ZH": "玩家皮肤",
    },
    ("SHADERSETTINGS", "unknBool0"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("SHADERSETTINGS", "unknBool1"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("SHADERSETTINGS", "unknBool2"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("SHADERSETTINGS", "unknBool3"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("SHADERSETTINGS", "drawMode"): {
        "EN": "How the particle is drawn. Water Ripple: draws nothing itself; its texture "
              "ripples any water surface behind it on screen. Overlay: drawn on top of other "
              "effects and unaffected by tone mapping and colour filters. Lighting Transition "
              "6–9: look the same as Default; may change how light and shadow ease in. "
              "Other values behave as Default.",
        "ZH": "粒子的绘制方式。水面波纹：自身不显示，贴图作为波纹作用于屏幕上其后方的水面。"
              "覆盖层：画在其他特效之上，不受色调处理和色彩滤镜影响。光暗过渡 6～9：画面与默认"
              "相同，可能改变光暗过渡的曲线。其余取值按默认处理。",
    },

    # ─── FADEBYDEPTH ──────────────────────────────────────────────────────────
    ("FADEBYDEPTH", "nearFadeInStart"): {
        "EN": "Near fade-in start. Below this distance, fully invisible.",
        "ZH": "近处淡入起点，小于此距离完全不可见。",
    },
    ("FADEBYDEPTH", "nearFadeInEnd"): {
        "EN": "Near fade-in end. Above this distance, fully visible.",
        "ZH": "近处淡入终点，大于此距离完全可见。",
    },
    ("FADEBYDEPTH", "farFadeOutStart"): {
        "EN": "Far fade-out start. Below this distance, fully visible.",
        "ZH": "远处淡出起点，小于此距离完全可见。",
    },
    ("FADEBYDEPTH", "farFadeOutEnd"): {
        "EN": "Far fade-out end. Above this distance, fully invisible.",
        "ZH": "远处淡出终点，大于此距离完全不可见。",
    },

    # ─── SCALEANIM ────────────────────────────────────────────────────────────
    ("SCALEANIM", "sizeScalarAdd"): {
        "EN": "Added to the renderer's Scale every frame. Negative values shrink the particle.",
        "ZH": "每帧加到渲染体「缩放」上的量，负值收缩。",
    },

    # ─── ROTATEANIM ───────────────────────────────────────────────────────────
    ("ROTATEANIM", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category marker rather "
              "than a tunable value. Never 0.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。不会取 0。",
    },
    ("ROTATEANIM", "rotationModeMask"): {
        "EN": "Selects which rotation settings apply: Rotation Type picks in-plane rotation or "
              "per-axis spin. Random Direction makes each particle randomly turn forward or "
              "backward (per axis when spinning).",
        "ZH": "选择使用哪组旋转设置：「旋转方式」选平面旋转或各轴自旋；"
              "「随机正反」让每个粒子随机正转或反转（自旋时各轴分别随机）。",
    },

    # ─── ALPHACORRECTION ──────────────────────────────────────────────────────
    ("ALPHACORRECTION", "lowPass"): {
        "EN": "Hard alpha clip threshold (like Photoshop's Threshold tool) — alpha below this value is cut to 0. 0 = no clipping.",
        "ZH": "Alpha 硬裁切阈值（类似 PS 的 Threshold 工具）——低于此值的 alpha 直接归 0。0 = 不裁切。",
    },
    ("ALPHACORRECTION", "contrast_gamma"): {
        "EN": "Contrast/gamma correction on alpha. Unbounded — higher values fade out low/mid alpha (edges) while keeping high alpha (core) intact; values can exceed 1, where almost everything fades to transparent.",
        "ZH": "对 alpha 做对比度/伽马修正。无上限——值越大，低/中 alpha（边缘）越快变透明，高 alpha（核心）保留；可超过 1，过大时几乎全图变透明。",
    },
    ("ALPHACORRECTION", "unkn3"): {
        "EN": "Unnamed float parameter, not a fixed constant. Usually 0 (unset); other values seen roughly in [-3.0, 3.0]. Purpose unknown.",
        "ZH": "未命名的浮点参数，并非恒定值。通常为 0（未设置）；其余取值大致落在 [-3.0, 3.0] 之间。具体作用未知。",
    },

    # ─── TUBELIGHT ────────────────────────────────────────────────────────────
    ("TUBELIGHT", "headColor"): {
        "EN": "Light column start color.",
        "ZH": "光柱起点颜色。",
    },
    ("TUBELIGHT", "tailColor"): {
        "EN": "Light column end color.",
        "ZH": "光柱终点颜色。",
    },
    ("TUBELIGHT", "headColorEpvSlot"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("TUBELIGHT", "columnLength"): {
        "EN": "Length of the light column (start=headColor, end=tailColor).",
        "ZH": "光柱长度（起点 headColor，终点 tailColor）。",
    },
    ("TUBELIGHT", "columnLengthModifier"): {
        "EN": "Also affects the light column's length; exact relation to columnLength not yet determined.",
        "ZH": "也会影响光柱长度，跟 columnLength 具体是什么关系还不确定。",
    },
    ("TUBELIGHT", "columnRadius"): {
        "EN": "Light column radius.",
        "ZH": "光柱半径。",
    },
    ("TUBELIGHT", "columnRadiusJitter"): {
        "EN": "Random jitter on the column radius.",
        "ZH": "光柱半径的随机抖动。",
    },
    ("TUBELIGHT", "columnEdgeSoftness"): {
        "EN": "Affects how soft/blurred the column's edge looks.",
        "ZH": "影响光柱边缘的柔化程度。",
    },
    ("TUBELIGHT", "lightIntensity"): {
        "EN": "Light intensity.",
        "ZH": "光照强度。",
    },
    ("TUBELIGHT", "coreIntensity"): {
        "EN": "Brightness of the core running down the middle of the tube.",
        "ZH": "光柱中央那条亮芯的亮度。",
    },
    ("TUBELIGHT", "coreIntensityJitter"): {
        "EN": "Random jitter on the core brightness.",
        "ZH": "亮芯亮度的随机抖动。",
    },
    ("TUBELIGHT", "tailGlowSpread"): {
        "EN": "Makes the tail glow longer with softer/blurrier edges.",
        "ZH": "让尾光变得更长、边缘更虚。",
    },
    ("TUBELIGHT", "headEffectiveRadius"): {
        "EN": "How far the light reaches around the head end of the tube. Raising it brightens the surrounding glow and spreads the headColor tint further.",
        "ZH": "光柱起点端的光照覆盖半径。调大会让四周的辉光更亮、起点色染得更远。",
    },
    ("TUBELIGHT", "tailEffectiveRadius"): {
        "EN": "Same as headEffectiveRadius but for the tail end.",
        "ZH": "同 headEffectiveRadius，作用在光柱终点端。",
    },
    ("TUBELIGHT", "tailPlaneOffset"): {
        "EN": "Front-back position of the tailColor emitting plane.",
        "ZH": "tailColor 发光平面的前后位置。",
    },
    ("TUBELIGHT", "unkn6b_1"): {
        "EN": "Possibly related to the brightness/glow halo of the emission",
        "ZH": "可能跟发光的明暗光圈相关，未知。",
    },
    ("TUBELIGHT", "unknFixed5_0"): {
        "EN": "Always 24 in the sample data — likely just a common default value.",
        "ZH": "固定为 24，可能只是常用默认值。",
    },
    ("TUBELIGHT", "unkn1_0"): {
        "EN": "Related to whether the light from the head/tail ends spills onto the surroundings. Exact behaviour unknown.",
        "ZH": "与起点/终点的光是否照亮周围环境有关，具体行为未知。",
    },
    ("TUBELIGHT", "textureScrollSpeed"): {
        "EN": "How fast the tube's texture scrolls along its length.",
        "ZH": "光柱贴图沿长度方向滚动的速度。",
    },
    ("TUBELIGHT", "effectiveRadius"): {
        "EN": "Overall reach of the light this tube casts on its surroundings.",
        "ZH": "本光柱对周围环境的整体光照半径。",
    },
    ("TUBELIGHT", "unkn1_10"): {
        "EN": "Possibly related to the light column's length; relation to columnLength/columnLengthModifier not yet determined.",
        "ZH": "可能与光柱长度有关，跟 columnLength/columnLengthModifier 的关系还不确定。",
    },

    # ─── RGBFIRE ──────────────────────────────────────────────────────────────
    ("RGBFIRE", "fireColor"): {
        "EN": "Tints the texture's Green channel — usually the outer glowing edge; also tints the inner smoke color.",
        "ZH": "给贴图的绿通道染色——一般是外缘的荧光色；同时会给内部的烟雾色染色。",
    },
    ("RGBFIRE", "fireFactor"): {
        "EN": "Fire (GreenCh) layer intensity. 0 turns the fire layer off entirely; smoke is unaffected.",
        "ZH": "火焰（绿通道）层的强度。设为 0 会把火焰这一层整个关掉，不影响烟雾层。",
    },
    ("RGBFIRE", "smokeColor"): {
        "EN": "Tints the texture's Red channel — usually the inner core color.",
        "ZH": "给贴图的红通道染色——一般是内部的核心色。",
    },
    ("RGBFIRE", "redChFactor"): {
        "EN": "Smoke (RedCh) layer intensity, mirrors Fire (GreenCh) Factor.",
        "ZH": "烟雾（红通道）层的强度，跟火焰（绿通道）系数镜像对称。",
    },
    ("RGBFIRE", "alphaFactor"): {
        "EN": "Overall alpha (transparency) intensity — setting either this or Color Rate to 0 makes everything disappear.",
        "ZH": "整体透明度强度——这个和亮度强度任一设为 0 都会让画面全部消失。",
    },
    ("RGBFIRE", "colorRate"): {
        "EN": "Overall color brightness intensity — setting either this or Alpha Rate to 0 makes everything disappear.",
        "ZH": "整体亮度强度——这个和透明度强度任一设为 0 都会让画面全部消失。",
    },
    ("RGBFIRE", "fireColorParam_useLife"): {
        "EN": "Fire color timing params (fade-in / duration / fade-out).",
        "ZH": "火焰色时序参数（淡入 / 持续 / 淡出）。",
    },
    ("RGBFIRE", "fireColorParam_lifeType"): {
        "EN": "Usually 0. Values 1 and 2 also occur, meaning unknown.",
        "ZH": "通常为 0。另有取值 1 和 2，含义未知。",
    },
    ("RGBFIRE", "fireColorParam_correctColorNo"): {
        "EN": 'EPV colour slot id, same mechanism as BILLBOARD3D correctColorNo: 0 = use the local fire colour; non-zero = take it from that slot in the calling .epv instead. Setting to 1 makes the fire colour disappear when the .epv has no data for that slot (values 2/8/9 also occur).',
        "ZH": "EPV 颜色槽位 id，跟 BILLBOARD3D 的 correctColorNo 是同一机制：0 = 用本地火焰色；非 0 = 改用调用方 .epv 对应槽位的颜色。若 .epv 没有该槽位数据，设为 1 会导致火焰色消失（另有取值 2/8/9）。",
    },
    ("RGBFIRE", "smokeColorParam_useLife"): {
        "EN": "Smoke color timing params (fade-in / duration / fade-out). Note: even a short duration can tint a persistent effect permanently.",
        "ZH": "烟雾色时序参数（淡入 / 持续 / 淡出）。注意：即使持续时间很短，也可能对常驻特效造成持久染色。",
    },
    ("RGBFIRE", "smokeColorParam_lifeType"): {
        "EN": "Usually 0. Values 1 and 2 also occur, meaning unknown.",
        "ZH": "通常为 0。另有取值 1 和 2，含义未知。",
    },
    ("RGBFIRE", "smokeColorParam_correctColorNo"): {
        "EN": 'EPV colour slot id, same mechanism as BILLBOARD3D correctColorNo: 0 = use the local smoke colour; non-zero = take it from that slot in the calling .epv instead. Setting to 1 makes the smoke colour disappear when the .epv has no data for that slot (values 2/7/8/9 also occur).',
        "ZH": "EPV 颜色槽位 id，跟 BILLBOARD3D 的 correctColorNo 是同一机制：0 = 用本地烟雾色；非 0 = 改用调用方 .epv 对应槽位的颜色。若 .epv 没有该槽位数据，设为 1 会导致烟雾色消失（另有取值 2/7/8/9）。",
    },

    # ─── GUIDE ────────────────────────────────────────────────────────────────

    # ─── PLEMISSIVE ───────────────────────────────────────────────────────────
    ("PLEMISSIVE", "rimWidth"): {
        "EN": "Rim light width. Can be animated via a TIML track.",
        "ZH": "边缘光宽度。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "rimPower"): {
        "EN": "Rim light falloff power. Can be animated via a TIML track.",
        "ZH": "边缘光衰减强度。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "rimAlpha"): {
        "EN": "Rim light opacity (can be negative). Can be animated via a TIML track.",
        "ZH": "边缘光透明度（可为负值）。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "intensity"): {
        "EN": "Emissive intensity. Can be animated via a TIML track.",
        "ZH": "自发光强度。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "mask0"): {
        "EN": "Emit-mask threshold 0 (default 15.0). Can be animated via a TIML track.",
        "ZH": "发光遮罩阈值 0（默认 15.0）。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "mask1"): {
        "EN": "Emit-mask threshold 1 (default 250.0). Can be animated via a TIML track.",
        "ZH": "发光遮罩阈值 1（默认 250.0）。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "emitMaskFlags"): {
        "EN": "Emit-mask related toggles (4 bits used); bit0 and bit3 have no known effect.",
        "ZH": "发光遮罩相关的开关组合（用到 4 位）；bit0 和 bit3 没有已知作用。",
    },

    # ─── PARENTEMISSIVE ───────────────────────────────────────────────────────
    ("PARENTEMISSIVE", "intensity"): {
        "EN": "Emissive intensity. Same mechanism as PLEMISSIVE.intensity; can be animated via a TIML track.",
        "ZH": "自发光强度。机制与 PLEMISSIVE.intensity 相同，可通过 TIML 轨道做动画。",
    },
    ("PARENTEMISSIVE", "rimWidth"): {
        "EN": "Rim light width — same PlEmissive TimelineParam concept as PLEMISSIVE.rimWidth.",
        "ZH": "边缘光宽度——跟 PLEMISSIVE.rimWidth 是同一个 PlEmissive TimelineParam 概念。",
    },
    ("PARENTEMISSIVE", "rimPower"): {
        "EN": "Rim light falloff power — same PlEmissive TimelineParam concept as PLEMISSIVE.rimPower.",
        "ZH": "边缘光衰减强度——跟 PLEMISSIVE.rimPower 是同一个 PlEmissive TimelineParam 概念。",
    },
    ("PARENTEMISSIVE", "rimAlpha"): {
        "EN": "Rim light opacity — same PlEmissive TimelineParam concept as PLEMISSIVE.rimAlpha.",
        "ZH": "边缘光透明度——跟 PLEMISSIVE.rimAlpha 是同一个 PlEmissive TimelineParam 概念。",
    },
    ("PARENTEMISSIVE", "mask0"): {
        "EN": "Emit-mask threshold 0. Common value is 15.0.",
        "ZH": "发光遮罩阈值 0。常见取值为 15.0。",
    },
    ("PARENTEMISSIVE", "mask1"): {
        "EN": "Emit-mask threshold 1. Common value is 250.0.",
        "ZH": "发光遮罩阈值 1。常见取值为 250.0。",
    },

    # ─── PLSNOW ───────────────────────────────────────────────────────────────
    ("PLSNOW", "body_part_id"): {
        "EN": "1F=Everything, 1/2/3/4/5=body parts as usual",
        "ZH": "1F=全部, 1/2/3/4/5=照常对应身体部位",
    },
    ("PLSNOW", "weapon_id"): {
        "EN": "Same as PlEmissive weapon slot",
        "ZH": "与 PlEmissive 的武器槽相同",
    },
    ("PLSNOW", "alpha_threshold"): {
        "EN": "Higher values cover less area",
        "ZH": "数值越大覆盖区域越小",
    },
    ("PLSNOW", "subsurface_multipler"): {
        "EN": "Transparency / Subsurface multiplier",
        "ZH": "透明度 / 次表面乘数",
    },
    ("PLSNOW", "craquelure_effect_diffumination"): {
        "EN": "Craquelure diffusion strength",
        "ZH": "裂纹效果扩散强度",
    },

    # ─── PTCOLLISION ──────────────────────────────────────────────────────────
    ("PTCOLLISION", "projectionOffset"): {
        "EN": "Offsets the collision plane along -Y. Positive values shift it down, "
              "negative values shift it up.",
        "ZH": "沿 -Y 轴偏移碰撞面。正值向下偏移，负值向上偏移。",
    },
    ("PTCOLLISION", "projectionDist"): {
        "EN": "Complex mechanism, affects multiple behaviors, not yet clear.",
        "ZH": "机制复杂，会改变多种表现，暂时不明确。",
    },
    ("PTCOLLISION", "bounceElasticity"): {
        "EN": "Bounce Elasticity On Collision",
        "ZH": "碰撞时的反弹弹性",
    },
    ("PTCOLLISION", "bounceElasticityJitter"): {
        "EN": "Bounce Elasticity Jitter",
        "ZH": "反弹弹性随机偏差",
    },
    ("PTCOLLISION", "bounceElasticityMultiplier"): {
        "EN": "Same effect as bounceElasticity, the two add together.",
        "ZH": "作用与 bounceElasticity 类似，叠加。",
    },
    ("PTCOLLISION", "impactPlayTriggerMode"): {
        "EN": "0=Triggers on every check.  1=Triggers on the first N checks, N determined "
              "jointly by impactPlayTriggerCount and impactPlayTriggerCountJitter.  "
              "2=Triggers only on the last check.",
        "ZH": "0=每次判定都触发。1=前 N 次判定触发，具体次数由 impactPlayTriggerCount 和 "
              "impactPlayTriggerCountJitter 共同决定。2=仅最后一次判定触发。",
    },
    ("PTCOLLISION", "impactPlayTriggerCount"): {
        "EN": "Fixed number of checks when impactPlayTriggerMode=1.",
        "ZH": "impactPlayTriggerMode=1 时的固定判定次数。",
    },
    ("PTCOLLISION", "ieIndex"): {
        "EN": "0=Call ActionEFX Index?,  0xFFFFFFFF=Null",
        "ZH": "0=调用 ActionEFX 索引？,  0xFFFFFFFF=空",
    },

    # ─── PTLIFE ───────────────────────────────────────────────────────────────
    ("PTLIFE", "status"): {
        "EN": "Determines when the specified Action is triggered, matching the particle's "
              "Appear / Keep / Vanish lifecycle stages set in LIFE. 0=On spawn, 1=Fade in, 2=Sustain, 3=Fade out, 4=On death, "
              "-1=Unknown",
        "ZH": "决定何时触发指定的 Action，对应 LIFE 里淡入 / 持续 / 淡出三段生命周期。"
              "0=生成时，1=淡入时，"
              "2=持续时，3=淡出时，4=死亡时，-1=未知",
    },
    ("PTLIFE", "relationIndex"): {
        "EN": "Action Emitter / Action EFX Index that declares the children",
        "ZH": "声明子级的 Action Emitter / Action EFX 索引",
    },

    # ─── EMITTERBOUNDARY ──────────────────────────────────────────────────────

    # ─── FADEBYANGLE ──────────────────────────────────────────────────────────

    # ─── FADEBYEMITTERANGLE ───────────────────────────────────────────────────
    # fadeInStart/fadeInEnd 组成单段距离淡入区间，不使用 near/far 前缀。
    ("FADEBYEMITTERANGLE", "fadeInStart"): {
        "EN": "Fade-in start (distance, not angle). Below this distance, gradually appears.",
        "ZH": "淡入起点（是距离不是角度），小于此距离逐渐显现。",
    },
    ("FADEBYEMITTERANGLE", "fadeInEnd"): {
        "EN": "Fade-in end (distance, not angle). Below this distance, fully visible.",
        "ZH": "淡入终点（是距离不是角度），小于此距离完全可见。",
    },

    # ─── NOISE ────────────────────────────────────────────────────────────────

    # ─── UVCONTROL ────────────────────────────────────────────────────────────
    ("UVCONTROL", "uv1_offsetCoef"): {
        "EN": "The UV1 scroll speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "UV1 滚动速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("UVCONTROL", "uv2_offsetCoef"): {
        "EN": "The UV2 scroll speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "UV2 滚动速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },

    # ─── EMITTERSHAPE2D ───────────────────────────────────────────────────────

    # ─── RAYCAST ──────────────────────────────────────────────────────────────
    ("RAYCAST", "direction"): {
        "EN": "Ray direction. Same AxisDirection6 enum as VELOCITY3D/RIBBON/RIBBONBLADE: "
              "0=Left, 1=Up, 2=Front, 3=Right, 4=Down, 5=Back. Casting downward to find "
              "the ground is the most common use (4 alone is 36% of all RAYCAST blocks).",
        "ZH": "射线方向。与 VELOCITY3D/RIBBON/RIBBONBLADE 同一套 AxisDirection6 枚举："
              "0=左, 1=上, 2=前, 3=右, 4=下, 5=后。朝下探地面是最常见的用法"
              "（光是 4 就占全部 RAYCAST 块的 36%）。",
    },
    ("RAYCAST", "rayCastID"): {
        "EN": "Shown as a dropdown defaulting to NONE. Only 4 values are used in practice "
              "(-1/0/1/2); -1 = NONE. The meaning of 0/1/2 is unknown, possibly used for "
              "program-side identification.",
        "ZH": "以下拉框显示，默认 NONE。实际只会用到 4 种取值（-1/0/1/2）；-1 = NONE。0/1/2 "
              "的具体含义未知，可能用于程序侧识别。",
    },
    ("RAYCAST", "rayCastFlags"): {
        "EN": "Two independent switches: bit0 = SyncSpawnFrame, bit8 = RayCastOnce.",
        "ZH": "两个独立开关：bit0 = SyncSpawnFrame，bit8 = RayCastOnce。",
    },

    # ─── HOMING ───────────────────────────────────────────────────────────────
    ("HOMING", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("HOMING", "section_length"): {
        "EN": "Fixed at 44 — do not modify",
        "ZH": "固定为 44，请勿修改。",
    },
    ("HOMING", "spacer"): {
        "EN": "Always 0xCDCDCD00 — do not modify",
        "ZH": "恒为 0xCDCDCD00，请勿修改",
    },
    ("HOMING", "turnRate"): {
        "EN": "How fast the particle's direction turns toward the homing target, in "
              "degrees per second (360 = one full turn per second). Past the target the "
              "particle circles back through it; orbit radius = speed / turn rate, so "
              "higher values give tighter, faster circles.",
        "ZH": "粒子运动方向朝归航目标转过去的速度，单位是度/秒（360 = 每秒转一整圈）。"
              "越过目标后粒子会绕回来再次经过它；轨道半径 = 速度 ÷ 转向速率，数值越大，"
              "圈越小、转得越快。",
    },
    ("HOMING", "acceleration"): {
        "EN": "Speed added per second, starting from the particle's initial speed set "
              "by VELOCITY3D, until Max Speed is reached. 0 keeps that initial speed; "
              "with a high Max Speed the orbit keeps widening in an evenly spaced spiral.",
        "ZH": "每秒增加的速度，从 VELOCITY3D 给出的初速度开始加，直到最大速度为止。"
              "0 表示保持初速度不变；最大速度很大时，轨道会以等距螺旋一直向外扩。",
    },
    ("HOMING", "maxSpeed"): {
        "EN": "Upper limit of the homing speed; a larger initial speed is capped to it. "
              "Once reached, the orbit settles into a closed circle "
              "(radius = speed / turn rate). 0 stops the particle.",
        "ZH": "归航速度的上限，初速度超过它时也按它算。达到上限后轨道稳定为闭合的圆"
              "（半径 = 速度 ÷ 转向速率）。为 0 时粒子不动。",
    },
    ("HOMING", "forceFieldSpeedScale"): {
        "EN": "The factor applied to particle speed inside the force field's affected "
              "region; only used when the force field mode is Slow Inside or Slow "
              "Outside. 0 stops the particle, 1 leaves the speed untouched, and values "
              "above 1 have no extra effect. Which side of the sphere is affected is set "
              "by the mode.",
        "ZH": "作用场作用区域内粒子速度的缩放比例，仅在作用场模式为「内部减速」或「外部减速」"
              "时生效。0 = 速度归零，1 = 不缩放，大于 1 没有额外效果。作用在球内还是球外"
              "由作用场模式决定。",
    },
    ("HOMING", "vanishRadius"): {
        "EN": "Radius of the vanish-check sphere, centred on the homing target. A "
              "particle entering it triggers the vanish check; the consequence is set by "
              "the vanish mode. Set it close to the emitter's spawn radius and particles "
              "vanish almost as soon as they spawn; set it very small (below ~5) and a "
              "few particles never get close enough to trigger at all.",
        "ZH": "消失判定球体的半径，球心在归航目标上。粒子进入这个球即触发消失判定，后果由"
              "消失模式决定。取值接近发射器的出生半径时，粒子几乎刚出生就消失；取值很小"
              "（低于 5 左右）时会有少部分粒子始终靠不够近、不触发判定。",
    },
    ("HOMING", "forceFieldRadius"): {
        "EN": "Radius of the force field sphere, centred on the homing target. What the "
              "sphere does is chosen by the force field mode.",
        "ZH": "作用场球体的半径，球心在归航目标上。这个球做什么由作用场模式决定。",
    },
    ("HOMING", "homingTarget"): {
        "EN": "Homing target = (homingTarget mod 4): 0=spawn point (emitter pos), "
              "1=model/character origin (feet), 2/3=world origin (map center). Cycles "
              "every 4 (4=spawn, 5=model, …). Motion always tracks the target's "
              "real-time position (not captured once at trigger time). "
              "Common values: 0=83%, 1=14%, 2=4%.",
        "ZH": "归航目标 = (homingTarget mod 4)：0=生成点（发射器位置），1=模型/角色原点"
              "（脚下），2/3=世界原点（地图中心）。每 4 循环（4=生成点, 5=模型原点…）。"
              "运动始终指向目标点的实时位置（不是触发时捕获定住）。"
              "用值：0=83%，1=14%，2=4%。",
    },
    ("HOMING", "vanishMode"): {
        "EN": "What happens when a particle enters the vanish-check sphere (see vanish "
              "radius). None performs no check and particles never vanish this way. "
              "Cancel Infinite Life drops an otherwise-endless LIFE at that moment, but "
              "LIFE's duration timer has been running from spawn and is not reset — if "
              "the duration has already elapsed the particle vanishes at once, otherwise "
              "it keeps counting down and vanishes when the duration ends. Vanish "
              "Immediately removes the particle on the spot.",
        "ZH": "粒子进入消失判定球（半径见消失半径）后的后果。「不触发」= 不做判定，粒子不会"
              "因此消失；「取消无限寿命」= 触发那一刻取消原本的无限寿命，但 LIFE 的持续时间"
              "计时器从出生起就正常走时、不会重置——如果触发时持续时间已经到了，粒子立即"
              "消失，没到就继续计时到时间再消失；「立即消失」= 触发瞬间当场消失。",
    },
    ("HOMING", "forceFieldMode"): {
        "EN": "The rule attached to the force field sphere (centred on the homing "
              "target, see force field radius). Cull Spawn Inside removes particles born "
              "inside the sphere and leaves ones flying in from outside untouched. No "
              "Turn Inside removes the turning force inside the sphere so particles coast "
              "straight, then snaps them back the moment they leave; particles born inside "
              "are kept. Slow Inside and Slow Outside scale particle speed by "
              "the force field speed scale, acting inside and outside the sphere "
              "respectively.",
        "ZH": "挂在作用场球体（球心=归航目标，半径见作用场半径）上的规则。「内部出生剔除」= 在"
              "球内出生的粒子直接消失，从球外飞进来的不受影响。「内部不转向」= 球内不受"
              "转向力、粒子直线滑行，一出球立刻被拉回；球内出生的粒子保留。「内部减速」和"
              "「外部减速」= 用作用场速度倍率缩放粒子"
              "速度，前者作用于球内，后者作用于球外。",
    },
    ("HOMING", "unknownEnum1"): {
        "EN": "Usually 0 (about 97%)",
        "ZH": "通常为 0（约 97%）。",
    },

    # ─── typeFlag/section_length 通用头字段 ─────────────────────────────────────
    # typeFlag 是类型/分类标记；section_length 记录该属性剩余字节长度，均非可调参数。
    ("NOISE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("RIBBON", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("DUMMY", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Fixed at 1.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。固定为 1。",
    },
    ("DUMMY", "section_length"): {
        "EN": "Structural remaining-length marker; computed by the engine, not a "
              "tunable parameter — do not modify",
        "ZH": "结构性剩余长度标记，由引擎计算，非可调参数——请勿修改",
    },
    ("FADEBYEMITTERANGLE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Fixed at 0.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。固定为 0。",
    },
    ("FADEBYEMITTERANGLE", "section_length"): {
        "EN": "Fixed at 20 — do not modify",
        "ZH": "固定为 20，请勿修改。",
    },
    ("RAYCAST", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("RAYCAST", "section_length"): {
        "EN": "Fixed at 70 — do not modify",
        "ZH": "固定为 70，请勿修改。",
    },
    ("SCREENSPACECOLLISION", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("SCREENSPACECOLLISION", "section_length"): {
        "EN": "Fixed at 28 — do not modify",
        "ZH": "固定为 28，请勿修改。",
    },
    ("SHOVEL", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("SHOVEL", "section_length"): {
        "EN": "Fixed at 62 — do not modify",
        "ZH": "固定为 62，请勿修改。",
    },
    ("PTTRIGGER", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("PTTRIGGER", "section_length"): {
        "EN": "Fixed at 8 — do not modify",
        "ZH": "固定为 8，请勿修改。",
    },
    ("SPAWNBYANGLE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("SPAWNBYANGLE", "section_length"): {
        "EN": "Fixed at 14 — do not modify",
        "ZH": "固定为 14，请勿修改。",
    },
    ("CHECKPUREATTRIBUTE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("CHECKPUREATTRIBUTE", "section_length"): {
        "EN": "Fixed at 32 — do not modify",
        "ZH": "固定为 32，请勿修改。",
    },
    ("SPAWNBYOCCLUSION", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("SPAWNBYOCCLUSION", "section_length"): {
        "EN": "Fixed at 12 — do not modify",
        "ZH": "固定为 12，请勿修改。",
    },
    ("PARENTSNOW", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("PARENTSNOW", "section_length"): {
        "EN": "Fixed at 72 — do not modify",
        "ZH": "固定为 72，请勿修改。",
    },
    ("OTOMOSNOW", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("OTOMOSNOW", "section_length"): {
        "EN": "Fixed at 76 — do not modify",
        "ZH": "固定为 76，请勿修改。",
    },
    ("FAKEPLANE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("FAKEPLANE", "section_length"): {
        "EN": "Fixed at 52 — do not modify",
        "ZH": "固定为 52，请勿修改。",
    },
    ("FAKEDOF", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: 1~5.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值 1~5。",
    },
    ("STRAINRIBBON", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: 1~13.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值 1~13。",
    },
    ("RGBWATER", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("TURBULENCE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("BILLBOARD3D", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("TUBELIGHT", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Fixed at 0.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。固定为 0。",
    },
    ("TONEMAPFILTER", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Value is 0.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。取值为 0。",
    },
    ("TONEMAPFILTER", "intensity"): {
        "EN": "Effect intensity.",
        "ZH": "滤镜生效强度。",
    },
    ("TONEMAPFILTER", "triggerRadius"): {
        "EN": "Effect range: only takes effect while the camera is within this radius.",
        "ZH": "生效范围：镜头进入这个范围内才会触发生效。",
    },
    ("TONEMAPFILTER", "unknFixed0_1"): {
        "EN": 'Meaning unknown. Value 16 does not match the path length (32), the path length without its trailing null (31), or the fixed header size (24).',
        "ZH": "含义未知。取值 16 与路径长度（32）、去掉末尾 null 的路径长度（31）以及固定头部大小（24）均不对应。",
    },
    ("TONEMAPFILTER", "unknFixed2_2"): {
        "EN": "Meaning unknown.",
        "ZH": "含义未知。",
    },
    ("LAYOUT", "useColumn0"): {
        "EN": "Switch for column 0 of the layout table below. Updates automatically when "
              "that column is added or removed.",
        "ZH": "下方布局表列 0 的开关。增删该列时自动同步。",
    },
    ("LAYOUT", "useColumn1"): {
        "EN": "Switch for column 1 of the layout table below. Updates automatically when "
              "that column is added or removed.",
        "ZH": "下方布局表列 1 的开关。增删该列时自动同步。",
    },
    ("LAYOUT", "useColumn2"): {
        "EN": "Switch for columns 2 and 3 of the layout table below; follows column 2. "
              "Updates automatically when column 2 or 3 is added or removed.",
        "ZH": "下方布局表列 2/3 的开关，随列 2 的有无。增删列 2 或列 3 时自动同步。",
    },
    ("LAYOUT", "useColumn4"): {
        "EN": "Switch for columns 4 and 5 of the layout table below; follows column 4. "
              "Updates automatically when column 4 or 5 is added or removed.",
        "ZH": "下方布局表列 4/5 的开关，随列 4 的有无。增删列 4 或列 5 时自动同步。",
    },
    ("LAYOUT", "useColumn6"): {
        "EN": "Switch for column 6 of the layout table below. Updates automatically when "
              "that column is added or removed.",
        "ZH": "下方布局表列 6 的开关。增删该列时自动同步。",
    },
    ("LAYOUT", "useColumn7"): {
        "EN": "Switch for column 7 of the layout table below. Updates automatically when "
              "that column is added or removed.",
        "ZH": "下方布局表列 7 的开关。增删该列时自动同步。",
    },
    ("LAYOUT", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("MATERIAL", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    # PTBEHAVIOR 参数按 hint_name 查 tooltip，不按序号占位的 ori_name。
    ("PTBEHAVIOR", "mBrightThreshold"): {
        "EN": "Brightness cutoff for the filter's bright pass: screen pixels darker than "
              "this are dropped before the radial blur, leaving only the brightest parts. "
              "Raising it crushes dark areas to solid black and lets the bright ones through "
              "untouched, which on screen reads like a very hard contrast boost. Values sit "
              "between 0 and 0.5, most often 0 or 0.1.",
        "ZH": "滤镜取亮部时的亮度门槛：比它暗的画面像素在径向模糊之前就被丢掉，只留下最亮的部分。"
              "调高会把暗部整块压成纯黑、亮部照常穿过，观感接近一次非常硬的对比度拉伸。"
              "取值在 0~0.5 之间，最常见是 0 或 0.1。",
    },
    ("PTBEHAVIOR", "mColor"): {
        "EN": "RGBA tint multiplied into the filter's output. Not limited to 0-1 — values go "
              "up to 20, so it doubles as a strength multiplier; the colour swatch can only "
              "reach 1, use the raw RGB row below it for anything brighter. Alpha is 1.0 in "
              "almost every case.",
        "ZH": "乘进滤镜输出的 RGBA 着色。不限于 0~1——最大可到 20，因此它同时充当强度倍率；"
              "色块本身只能拖到 1，更亮的值用它下面那行原始 RGB 数值改。Alpha 几乎总是 1.0。",
    },
    ("PTBEHAVIOR", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Not the same field as the "
              "per-parameter unkn0 seen elsewhere in this block.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。跟本块内每个"
              "参数各自的 unkn0 是不同字段，不要混淆。",
    },

    # ─── SCREENSPACECOLLISION ─────────────────────────────────────────────────
    ("SCREENSPACECOLLISION", "lifespan"): {
        "EN": "0=No interaction; higher values = more bounce",
        "ZH": "0=无交互；数值越大反弹越多",
    },

    # ─── SHOVEL ───────────────────────────────────────────────────────────────
    ("SHOVEL", "unkn09"): {
        "EN": "Range roughly -180 to 90 (degrees); most commonly -180 or 0.",
        "ZH": "取值范围约 -180~90（角度）；最常见为 -180 或 0。",
    },
    ("SHOVEL", "unkn10"): {
        "EN": "Range 0 to 360 (degrees); most commonly 0 or 360, paired with unkn09.",
        "ZH": "取值范围 0~360（角度）；最常见为 0 或 360，与 unkn09 成对使用。",
    },
    ("SHOVEL", "unkn11"): {
        "EN": "Range 0 to 6; default is usually 0.5.",
        "ZH": "取值范围 0~6；默认通常为 0.5。",
    },
    ("SHOVEL", "unknFixed12"): {
        "EN": "Usually 0.",
        "ZH": "通常为 0。",
    },
    ("SHOVEL", "unknEnum13"): {
        "EN": "Range 0 to 100; usually 0.",
        "ZH": "取值范围 0~100；通常为 0。",
    },
    ("SHOVEL", "unknEnum14"): {
        "EN": "Range 0 to 30; usually 0.",
        "ZH": "取值范围 0~30；通常为 0。",
    },
    ("SHOVEL", "pattern"): {
        "EN": "Enum, range -1 to 7.",
        "ZH": "枚举值，范围 -1~7。",
    },
    ("SHOVEL", "unknBitmask16"): {
        "EN": "Packed as 4 independent on/off byte flags.",
        "ZH": "由 4 个独立的开/关字节标志打包而成。",
    },
    ("SHOVEL", "unknEnum17"): {
        "EN": "Packed as 2 independent on/off byte flags; usually 0.",
        "ZH": "由 2 个独立的开/关字节标志打包而成；通常为 0。",
    },

    # ─── EXTERNREFERENCE ──────────────────────────────────────────────────────

    # ─── DUMMY / RANDOMFIX / MASTERONLY / BLINK / LUMINANCEBLEED / REFRACTION ─
    ("LUMINANCEBLEED", "bleed"): {
        "EN": "Bleed strength — how far/strongly bright pixels bleed into surrounding "
              "pixels. 0 = no effect; increasing toward 1 gives a natural bloom-like glow. "
              "Unclamped: values above 1 cause runaway overexposure. Practical range: 0~1.",
        "ZH": "辉光强度——亮部像素向周围渗出的强度。0=无效果；增大到 1 产生自然的辉光效果。"
              "无上限裁切：超过 1 会导致失控过曝。实际取值范围为 0~1。",
    },
    ("LUMINANCEBLEED", "colorScaler"): {
        "EN": "Multiplies the bled-out light's own color/brightness (not its spread). "
              "0 = pure black; 1 = neutral/unchanged (the overwhelming majority of usage); "
              "high values (10+) blow it out to white and can overflow render bounds.",
        "ZH": "对辉光本身的颜色/亮度做倍乘（不影响辉光范围）。0=纯黑；1=中性不变"
              "（绝大多数实际取值）；调高（10+）会冲成纯白，甚至溢出渲染边界。",
    },
    ("LUMINANCEBLEED", "texelScaler"): {
        "EN": "Sampling/blur radius for the bleed, in texels. Larger = wider spread into "
              "neighboring pixels (soft gradient expansion, distinct from colorScaler's hard "
              "overflow). Usage clusters at small integers (1/2/3 texels).",
        "ZH": "辉光效果的取样/模糊半径，以纹素为单位。数值越大扩散越宽（渐变式柔和扩散，"
              "区别于 colorScaler 的硬边界溢出）。实际取值集中在 1/2/3 等小整数。",
    },
    ("RANDOMFIX", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。",
    },
    ("RANDOMFIX", "randomSeedTable0"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable1"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable2"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable3"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable4"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable5"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable6"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "randomSeedTable7"): {
        "EN": "One of 8 slots in the random seed table. Click the dice button to generate a new random value.",
        "ZH": "随机种子表的 8 个槎位之一。点击骰子按钮可生成新的随机值。",
    },
    ("RANDOMFIX", "tableSelectionGroup"): {
        "EN": "Bitmask selecting which of the 8 randomSeedTable slots belong to this group. "
              "Click the button on the left to edit via checkboxes.",
        "ZH": "位掩码，选择 8 个 randomSeedTable 槎位中的哪些属于该组。点击左侧按钮可用勾选框编辑。",
    },

    # ─── MESH (Mod3Properties fields — _custom type, flat part) ───────────────
    ("MESH", "visconIndex"): {
        "EN": "Selects which mesh(es) in the linked mod3 to display — matches "
              "mesh(es) whose Visible Condition equals this value.",
        "ZH": "指定调用所链接 mod3 内 Visible Condition 与此值相同的网格。",
    },
    ("MESH", "tracking_flags"): {
        "EN": "Tracking mode. Pick one — these are not combinable.",
        "ZH": "追踪模式。单选，各项不可叠加。",
    },
    ("MESH", "color"): {
        "EN": "Base color (RGBA). Shown as-is when useColorRange is off.",
        "ZH": "基准颜色（RGBA）。useColorRange 关闭时固定显示这个颜色。",
    },
    ("MESH", "colorRange"): {
        "EN": "The other end of the color range (RGBA). Only used when useColorRange "
              "is on — the displayed color then randomly varies between color and "
              "colorRange.",
        "ZH": "颜色范围的另一端（RGBA）。仅在 useColorRange 开启时生效——开启后，最终"
              "显示的颜色会在 color 与 colorRange 之间随机变化。",
    },
    ("MESH", "emissiveColor"): {
        "EN": "Emissive glow color (RGBA), added on top of color. Only visible when "
              "useEmissiveColor is on.",
        "ZH": "自发光颜色（RGBA），叠加在 color 上面。只有 useEmissiveColor 开启时才会显示。",
    },
    ("MESH", "emissiveColorRange"): {
        "EN": "The other end of the emissive color range (RGBA). Only used when "
              "useEmissiveColorRange is on — the emissive glow then randomly varies "
              "between emissiveColor and emissiveColorRange.",
        "ZH": "自发光颜色范围的另一端（RGBA）。仅在 useEmissiveColorRange 开启时生效——"
              "开启后，自发光颜色会在 emissiveColor 与 emissiveColorRange 之间随机变化。",
    },
    ("MESH", "enableIntensity1"): {
        "EN": "Brightens the color channel. Independent of enableIntensity2 — turning "
              "both on stacks (brighter than either alone).",
        "ZH": "让 color 通道变亮。跟 enableIntensity2 相互独立——两个都开会叠加变得更亮。",
    },
    ("MESH", "useColorRange"): {
        "EN": "Color random-range switch. 0 = off (always shows color). 1 = on "
              "(displayed color randomly varies between color and colorRange).",
        "ZH": "颜色随机范围开关。0=禁用（始终显示 color）；1=启用（最终显示的颜色会在 "
              "color 与 colorRange 之间随机变化）。",
    },
    ("MESH", "enableIntensity2"): {
        "EN": "Brightens the color channel. Independent of enableIntensity1 — turning "
              "both on stacks (brighter than either alone).",
        "ZH": "让 color 通道变亮。跟 enableIntensity1 相互独立——两个都开会叠加变得更亮。",
    },
    ("MESH", "useEmissiveColor"): {
        "EN": "Enables the emissive channel. 0 = emissiveColor/emissiveColorRange are "
              "completely ignored. 1 = emissiveColor is added on top of color.",
        "ZH": "启用自发光通道。0=完全不显示 emissiveColor/emissiveColorRange；1=把 "
              "emissiveColor 叠加到 color 上面。",
    },
    ("MESH", "useEmissiveColorRange"): {
        "EN": "Emissive color random-range switch, same idea as useColorRange but for "
              "the emissive channel. Only has an effect when useEmissiveColor is on; "
              "independent of enableEmissiveIntensity.",
        "ZH": "自发光颜色的随机范围开关，跟 useColorRange 是同一种机制，只是作用于自发光"
              "通道。只有 useEmissiveColor 开启时才有效果；跟 enableEmissiveIntensity 相互独立。",
    },
    ("MESH", "enableEmissiveIntensity"): {
        "EN": "Brightness switch for the emissive channel: 0 = dim, 1 = full brightness. "
              "Only has an effect when useEmissiveColor is on.",
        "ZH": "自发光通道的亮度开关：0=暗，1=满亮度。只有 useEmissiveColor 开启时才有效果。",
    },
    ("MESH", "disableAllColorRange"): {
        "EN": "When on, forces both color and emissiveColor to their static values, "
              "ignoring useColorRange and useEmissiveColorRange regardless of how "
              "those two are set.",
        "ZH": "开启时会强制 color 和 emissiveColor 都变成静态值，无视 useColorRange 和 "
              "useEmissiveColorRange 各自的开关状态。",
    },
    ("MESH", "unknFlag_cm2_3"): {
        "EN": "Fourth colorize_material2 toggle. Purpose unknown.",
        "ZH": "colorize_material2 的第四个开关。作用未知。",
    },
    ("MESH", "unknBool0"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "unknBool1"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "unknBool2"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "unknBool3"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "unknBool4"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "unknBool5"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("MESH", "shadowCastBitflag"): {
        "EN": "Bit 0 draws the model and bit 1 draws its shadow. With both off, nothing is drawn.",
        "ZH": "位 0 绘制模型，位 1 绘制阴影；两者都关闭时什么都不绘制。",
    },
    ("MESH", "affectedByLight"): {
        "EN": "Which lights affect the mesh. Per-bit meaning unknown.",
        "ZH": "哪些光照会影响该模型。各位含义未知。",
    },

    # ─── RIBBON (fixed part fields) ───────────────────────────────────────────
    ("RIBBON", "uvScaleMode"): {
        "EN": "How the texture is scaled along the ribbon's length. Off: UV Scale Length "
              "has no effect. Fixed Count: the texture repeats UV Scale Length times over the "
              "whole ribbon. By Aspect Ratio: the repeat count is UV Scale Length times the "
              "ribbon's length-to-width ratio, so the texture keeps its proportions — at "
              "twice the length it tiles twice as often.",
        "ZH": "长度缩放方式。不缩放：长度方向贴图缩放不生效。固定次数：整条带上贴图重复"
              "「长度方向贴图缩放」次。按长宽比：重复次数为「长度方向贴图缩放」乘以条带的长宽比，贴图保持"
              "原比例——条带长度翻倍时平铺次数也翻倍。",
    },
    ("RIBBON", "uvScaleLength"): {
        "EN": "Texture repeat count along the length: 1 shows the whole texture once, 2 shows "
              "two copies end to end, 0.5 shows only half. Takes effect only when UV Scale "
              "Mode is not Off.",
        "ZH": "长度方向的贴图重复次数：1 显示整张贴图，2 首尾相接显示两张，0.5 只显示一半。"
              "仅在缩放方式不为「不缩放」时生效。",
    },
    ("RIBBON", "subdivisionCount"): {
        "EN": "Number of cross-edges along the ribbon's length. N edges give N-1 segments of "
              "2 triangles each, so 2 is a single quad.",
        "ZH": "沿条带长度方向的切边数量。N 条边分出 N-1 段，每段 2 个三角面，因此 2 即单个"
              "四边形。",
    },
    ("RIBBON", "unknBool16_2_0"): {
        "EN": "Purpose unknown. Turning it off stops the ribbon from facing the camera.",
        "ZH": "作用未知。关闭后将无法朝向摄像机。",
    },
    ("RIBBON", "faceVelocity"): {
        "EN": "The ribbon always points along the particle's current motion, including gravity "
              "and homing but not Transform3D velocity. Invisible while the particle is still.",
        "ZH": "条带始终指向粒子当前的运动方向，包括重力与追踪的影响，不含 Transform3D 的速度。"
              "粒子静止时不可见。",
    },
    ("RIBBON", "fixedDirection"): {
        "EN": "The ribbon's direction is set by Base Axis, Rotation Order and Rotation and does "
              "not follow the velocity. No effect when Face Velocity is on.",
        "ZH": "条带朝向由基准轴、旋转顺序与旋转决定，不随速度改变。开启朝向运动方向时无效。",
    },
    ("RIBBON", "lockInitialVelocity"): {
        "EN": "With Face Velocity on, the ribbon keeps the direction the particle was born "
              "moving in, ignoring later gravity and homing.",
        "ZH": "与朝向运动方向同时开启时，朝向固定为粒子出生时的速度方向，不再受重力与追踪影响。",
    },
    ("RIBBON", "stretchFromSpawn"): {
        "EN": "The start of the ribbon stays at the spawn point while the front moves with the "
              "particle, stretching into one straight strip.",
        "ZH": "条带起点固定在生成点，前端随粒子移动，拉伸成一条直的长条。",
    },
    ("RIBBON", "stretchMaxLength"): {
        "EN": "Longest distance from the spawn point to the front; beyond it the start is dragged "
              "along behind. 0 = no limit. Needs Stretch From Spawn.",
        "ZH": "生成点到条带前端的最大距离，超出后起点被拖着跟上。0 为不限制。需开启从生成点拉伸。",
    },
    ("RIBBON", "stretchResetDistance"): {
        "EN": "When the front gets this far from the spawn point, the ribbon starts stretching "
              "again from where it is. Small values make it flicker. 0 = never resets. Needs "
              "Stretch From Spawn.",
        "ZH": "条带前端离生成点超过该距离时，从当前位置重新拉伸；值越小刷新越频繁、越像闪烁。"
              "0 为不重置。需开启从生成点拉伸。",
    },
    ("RIBBON", "unknBool7"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "enableFadeLength"): {
        "EN": "Switch for the two fade lengths. When off, both fade lengths count as 1, "
              "so each end's opacity fades across the whole ribbon.",
        "ZH": "两个渐隐长度的开关。关闭时两个渐隐长度都按 1 计，两端的不透明度沿整条带子渐变。",
    },
    ("RIBBON", "ribbonMode"): {
        "EN": "Ribbon Follow draws the shape along the path the emitter actually travelled. "
              "Ribbon Length is a plain rigid rectangle that faces the camera by rotating on "
              "one axis only — so it flips a full 180° when the camera passes its edge-on "
              "side, which is inherent to that construction. Ribbon Chain extends out from "
              "the emitter and reacts elastically, driven by the restore strength / inertia / "
              "springiness group, with the flap group adding a steady back-and-forth sway.",
        "ZH": "轨迹跟随：沿发射器实际划过的轨迹绘制条带形状。定长面片：单纯的刚性矩形面片，"
              "只靠单个轴的转动来朝向摄像机——因此摄像机经过其侧边时会整体翻转 180°，这是该"
              "构造本身的固有表现。柔体链：从发射器向外延伸并带有弹性，由归位强度／惯性／"
              "弹性三个参数驱动，另有抖动组提供恒定速率的来回摆动。",
    },
    ("RIBBON", "visiblePreview"): {
        "EN": "Visibility correction. Safe value: 0. A non-zero value moves the rear end "
              "forward to the spawn point and brightens the ribbon, but breaks TIML color "
              "animation on the animation1 / particle-lifetime axis and can make strips "
              "go missing.",
        "ZH": "可见性修正。安全值：0。非 0 时会把尾端前移到生成点并让条带变亮，但会破坏 "
              "TIML 在 animation1／粒子寿命轴上的颜色变换，还可能让条带缺失。",
    },
    ("RIBBON", "enableFlap"): {
        "EN": "Master switch for the flap oscillation group — the flap frequency/amount "
              "fields only do anything while this is on.",
        "ZH": "抖动组的总开关——下面的抖动频率／幅度字段只有在它开启时才起作用。",
    },
    ("RIBBON", "enableGravity"): {
        "EN": "Switch for the gravity applied to the ribbon chain. The three gravity axes "
              "below only take effect while this is on.",
        "ZH": "柔体链所受重力的开关。下面三个重力分量只在它开启时生效。",
    },
    ("RIBBON", "gravityLocalSpace"): {
        "EN": "When on, gravity is measured in the emitter's local space: rotating the "
              "emitter turns the gravity direction with it, while the particle's own "
              "direction does not. When off, gravity uses fixed world axes. Only takes "
              "effect while Enable Gravity is on.",
        "ZH": "开启后重力改按发射器的本地坐标系计算：发射器旋转时重力方向跟着转，粒子自身的朝向"
              "不影响重力方向。关闭时重力沿固定的世界轴。只在启用重力时生效。",
    },
    ("RIBBON", "gravityX"): {
        "EN": "Gravity along the X axis, applied to the ribbon from its tail end.",
        "ZH": "沿 X 轴的重力分量，自尾端施加到条带上。",
    },
    ("RIBBON", "gravityY"): {
        "EN": "Gravity along the vertical axis. A negative value pulls the ribbon downward.",
        "ZH": "沿竖直轴的重力分量。填负值时把条带往下拉。",
    },
    ("RIBBON", "gravityZ"): {
        "EN": "Gravity along the Z axis, applied to the ribbon from its tail end.",
        "ZH": "沿 Z 轴的重力分量，自尾端施加到条带上。",
    },

    # ─── UVSEQUENCE (fixed part fields) ───────────────────────────────────────
    ("UVSEQUENCE", "sequenceNo"): {
        "EN": "UVS File Path Index (see the paired Jitter field for spawn-time variance).",
        "ZH": "UVS 文件路径索引（生成时的随机抖动量见旁边的 Jitter 字段）。",
    },
    ("UVSEQUENCE", "loopingMode"): {
        "EN": "Packed playback byte, edited via the popup as four groups: playback mode "
              "(first frame only / loop / play once then vanish / play once then hold), "
              "horizontal flip, vertical flip (each none / flip / random), and direction "
              "(forward / reverse / random). Random picks happen once at spawn.",
        "ZH": "打包的播放字节，用弹窗按四组编辑：播放模式（只显示起始帧／循环／播一次后消亡／"
              "播一次后定格）、水平翻转、垂直翻转（各：不翻／固定翻／随机翻）、播放方向"
              "（正向／倒放／随机）。随机项在粒子生成时取一次。",
    },
    ("UVSEQUENCE", "loopingOrientation"): {
        "EN": "Texture rotation on the particle, independent of the horizontal/vertical "
              "flip (a flipped texture still rotates the same direction): 0=Normal,  "
              "1=Rotate 90° clockwise,  2=Rotate 90° counter-clockwise,  "
              "3=Randomly pick one of the first three.",
        "ZH": "贴图在粒子上的旋转，与水平/垂直翻转相互独立（即使贴图已翻转，1/2 仍分别是"
              "顺/逆时针旋转，不会因翻转而互换）：0=正常朝向，1=顺时针旋转 90°，"
              "2=逆时针旋转 90°，3=前三种随机取一种。",
    },

    # ─── BILLBOARD3D (fixed part fields) ──────────────────────────────────────
    ("BILLBOARD3D", "brightness"): {
        "EN": "Brightness",
        "ZH": "亮度",
    },
    ("BILLBOARD3D", "scale"): {
        "EN": "Scale",
        "ZH": "缩放",
    },
    ("BILLBOARD3D", "width"): {
        "EN": "Width",
        "ZH": "宽度",
    },
    ("BILLBOARD3D", "height"): {
        "EN": "Height",
        "ZH": "高度",
    },

    # ─── PLANE (fixed part fields — same layout as BILLBOARD3D dds_data) ──────
    ("PLANE", "brightness"): {
        "EN": "Brightness",
        "ZH": "亮度",
    },
    ("PLANE", "color"): {
        "EN": "Base color (RGBA). Shown as-is when useColorRange is off.",
        "ZH": "基准颜色（RGBA）。useColorRange 关闭时固定显示这个颜色。",
    },
    ("PLANE", "colorRange"): {
        "EN": "The other end of the color range (RGBA). Only used when useColorRange "
              "is on — the displayed color then randomly varies between color and "
              "colorRange.",
        "ZH": "颜色范围的另一端（RGBA）。仅在 useColorRange 开启时生效——开启后，最终"
              "显示的颜色会在 color 与 colorRange 之间随机变化。",
    },
    ("PLANE", "useColorRange"): {
        "EN": "Color random-range switch. 0 = off (always shows color). 1 = on "
              "(displayed color randomly varies between color and colorRange).",
        "ZH": "颜色随机范围开关。0=禁用（始终显示 color）；1=启用（最终显示的颜色会在 "
              "color 与 colorRange 之间随机变化）。",
    },
    ("PLANE", "blendMode"): {
        "EN": _EMISSIVE_TIP_EN,
        "ZH": _EMISSIVE_TIP_ZH,
    },
    ("PLANE", "scale"): {
        "EN": "Scale",
        "ZH": "缩放",
    },
    ("PLANE", "width"): {
        "EN": "Width",
        "ZH": "宽度",
    },
    ("PLANE", "height"): {
        "EN": "Height",
        "ZH": "高度",
    },

    # ─── RIBBONBLADE (fixed part fields) ──────────────────────────────────────
    ("RIBBONBLADE", "width"): {
        "EN": "Length of the blade sticking out from the trail along the width direction. "
              "Negative values extend the opposite way.",
        "ZH": "刀身从轨迹沿宽度延伸方向伸出的长度，负值向反方向伸出。",
    },
    ("RIBBONBLADE", "contractionSpeed"): {
        "EN": "How much the trail shrinks per second, all the time. Only used when "
              "Distance-Based Length is on. 0 keeps the trail after the blade stops; a value "
              "larger than the distance moved per second keeps the trail invisible.",
        "ZH": "刀光每秒持续缩短的长度，仅在开启「按距离计算长度」时生效。0 表示停下后刀光一直保留；"
              "大于每秒移动距离时刀光始终不可见。",
    },
    ("RIBBONBLADE", "colourTransitionPoint"): {
        "EN": "Portion of the trail, measured from the head, that keeps the head color; the "
              "rest blends into the tail color. 0 blends along the whole trail, 1 uses the "
              "head color throughout.",
        "ZH": "从头部起保持头部颜色的长度比例，其余部分逐渐过渡到尾部颜色。0 表示整条渐变，1 "
              "表示整条为头部颜色。",
    },
    ("RIBBONBLADE", "emissiveStrength"): {
        "EN": "Brightness of the trail. At 1 pure white shows as mid grey, around 5 it is close "
              "to the set color, and from 10 up it saturates to white with a glow.",
        "ZH": "刀光亮度。1 时纯白只显示为中灰，5 左右接近设定颜色，10 以上饱和为白色并带光晕。",
    },
    ("RIBBONBLADE", "useEmissiveRange"): {
        "EN": "When on, each trail's brightness is picked at random between Emissive Strength "
              "and Emissive Strength Range. Usually off.",
        "ZH": "开启后，刀光亮度在自发光强度与自发光强度范围之间随机取值。通常关闭。",
    },
    ("RIBBONBLADE", "emissiveStrengthRange"): {
        "EN": "Other end of the random brightness range; only used when Use Emissive Range is "
              "on. Common value is 1.",
        "ZH": "随机亮度范围的另一端，仅在开启「启用自发光强度范围」时生效。常见取值为 1。",
    },
    ("RIBBONBLADE", "maxLengthLimit"): {
        "EN": "Maximum trail length. Only used when Distance-Based Length is on.",
        "ZH": "刀光的最大长度，仅在开启「按距离计算长度」时生效。",
    },
    ("RIBBONBLADE", "head.size"): {
        "EN": "Width multiplier at the head; the blade width blends linearly toward the tail.",
        "ZH": "头部处的宽度倍率，刀身宽度向尾部线性过渡。",
    },
    ("RIBBONBLADE", "tailEnd.size"): {
        "EN": "Width multiplier at the tail. Common values are 0.1–1.0; lower values taper the "
              "tail.",
        "ZH": "尾部处的宽度倍率。常见取值为 0.1～1.0，越小尾部越尖。",
    },
    ("RIBBONBLADE", "head.epvColorSlot"): {
        "EN": "EPV color slot for the blade streak's head (the leading edge).",
        "ZH": "刀光头部（前端）对应的 EPV 颜色槽。",
    },
    ("RIBBONBLADE", "tailEnd.epvColorSlot"): {
        "EN": "EPV color slot for the blade streak's tail (the trailing edge).",
        "ZH": "刀光尾部（后端）对应的 EPV 颜色槽。",
    },
    ("RIBBONBLADE", "head.color1"): {
        "EN": "Head color; blends into the tail color along the trail.",
        "ZH": "头部颜色，沿刀光过渡到尾部颜色。",
    },
    ("RIBBONBLADE", "head.color2"): {
        "EN": "Head color range. Almost always white (rarely touched).",
        "ZH": "头部颜色范围。几乎恒为白色（很少被使用）。",
    },
    ("RIBBONBLADE", "tailEnd.color1"): {
        "EN": "Tail color. White with a low alpha is commonly used to fade out the tail.",
        "ZH": "尾部颜色。常用白色配较低 alpha 做尾部渐隐。",
    },
    ("RIBBONBLADE", "tailEnd.color2"): {
        "EN": "Tail color range. Almost always white (rarely touched).",
        "ZH": "尾部颜色范围。几乎恒为白色（很少被使用）。",
    },
    ("RIBBONBLADE", "head.unkn18_1"): {
        "EN": "Head-side fixed value (0xCD). This field is not intended for adjustment.",
        "ZH": "头部侧固定值（0xCD），不建议调整。",
    },

    # ─── TURBULENCE (fixed part fields) ───────────────────────────────────────

    # ─── LIGHTNING (fixed part fields) ────────────────────────────────────────

    # ─── STRAINRIBBON ─────────────────────────────────────────────────────────
    ("STRAINRIBBON", "unknFixed00_2"): {
        "EN": "Flag byte. Usually 0; its effect is unknown.",
        "ZH": "标志位，通常为 0；具体作用未知。",
    },
    ("STRAINRIBBON", "color"): {
        "EN": "Fixed chain color RGBA (0~255); pairs with Color Range the same way "
              "as other renderer bodies (e.g. Billboard3D/Mesh)",
        "ZH": "链条固定颜色 RGBA（0~255）；与颜色范围配对，同其他渲染主体（如 "
              "Billboard3D/Mesh）的用法一致",
    },
    ("STRAINRIBBON", "colorRange"): {
        "EN": "Random color range paired with the fixed color; only takes effect "
              "when Use Color Range is on",
        "ZH": "与固定颜色配对的随机颜色范围；只有启用颜色范围开关时才生效",
    },
    ("STRAINRIBBON", "useColorRange"): {
        "EN": "Enables random interpolation between Color and Color Range",
        "ZH": "启用固定颜色与颜色范围之间的随机插值",
    },
    ("STRAINRIBBON", "useEmission"): {
        "EN": "Enables self-illumination (emission)",
        "ZH": "启用自发光",
    },
    ("STRAINRIBBON", "emissionStrength"): {
        "EN": "Chain emission strength; also controls base visibility. 0=completely "
              "vanishes (not rendered); 1~39=normal display, brighter as it rises; "
              "40+=produces glow/bloom; 100+=large-area halo",
        "ZH": "链条发光强度，同时控制基础可见性。0=完全消失不渲染；1~39=正常显示，"
              "越大越亮；40+=产生辉光曝光；100+=大范围光晕",
    },
    ("STRAINRIBBON", "emissionStrengthJitter"): {
        "EN": "Emission-strength random jitter. Positive=some frames brighter, "
              "producing glow; negative (e.g. -100)=some frames go black, alternating "
              "blue-black flicker, good for an unstable arc feel",
        "ZH": "发光强度随机偏差。正数=部分帧更亮产生辉光；负数（如 -100）=部分帧变黑，"
              "蓝黑交替闪烁，适合不稳定电弧感",
    },
    ("STRAINRIBBON", "startPosition"): {
        "EN": "Start-point XYZ offset (relative to the bound bone/spawn position); "
              "pairs with End Position — larger offset = larger curve arc at the "
              "start end",
        "ZH": "起点（相对绑定骨骼/生成位置）XYZ 偏移量，与末端偏移互为对应；偏移越大"
              "起始端弯曲弧度越大",
    },
    ("STRAINRIBBON", "endPosition"): {
        "EN": "End-bone XYZ offset. Important: when non-zero the chain curves normally "
              "while sheathed, but straightens once drawn into combat (animation bones "
              "override the offset calculation); when all-zero the sheathed/drawn shape "
              "is consistent. Larger offset = larger curve arc",
        "ZH": "末端骨骼 XYZ 偏移量。重要：非 0 时收刀链条弯曲正常，但拔刀进战斗后链条变直"
              "（动画骨骼覆盖偏移计算）；全 0 时收/拔刀形态一致。偏移越大弯曲弧度越大",
    },
    ("STRAINRIBBON", "width"): {
        "EN": "Overall chain width; larger=thicker; combine with start/end width for "
              "thickness variation",
        "ZH": "链条整体宽度，越大越粗；配合开始/结束宽度做粗细变化",
    },
    ("STRAINRIBBON", "widthJitter"): {
        "EN": "Width random jitter",
        "ZH": "宽度随机偏差。",
    },
    ("STRAINRIBBON", "length"): {
        "EN": "Total chain length. =actual distance between the two bones makes it taut "
              "and flush; >the distance lets the excess fold into a natural arc and "
              "droop; combine with subdivision count to control the fold shape",
        "ZH": "链条总长度。=两骨骼实际距离时绷直贴合；>距离时多余部分弯折产生自然弧度和垂落；"
              "配合细分计数控制弯折形态",
    },
    ("STRAINRIBBON", "lengthJitter"): {
        "EN": "Length random jitter",
        "ZH": "长度随机偏差。",
    },
    ("STRAINRIBBON", "startWidth"): {
        "EN": "Start-end width factor, multiplied with width. 0=contracts to a point; "
              "1=same as width",
        "ZH": "起始端宽度系数，与宽度相乘。0=收缩为尖点；1=与宽度相同",
    },
    ("STRAINRIBBON", "startOpacity"): {
        "EN": "Start-end opacity. 0=fully transparent (fade-in); 1=fully opaque",
        "ZH": "起始端透明度。0=完全透明（渐入）；1=完全不透明",
    },
    ("STRAINRIBBON", "endWidth"): {
        "EN": "End width factor, same as start width",
        "ZH": "末端宽度系数，同起始宽度",
    },
    ("STRAINRIBBON", "endOpacity"): {
        "EN": "End opacity, same as start opacity",
        "ZH": "末端透明度，同起始不透明度",
    },
    ("STRAINRIBBON", "subdivisionCount"): {
        "EN": "Number of segments the drooping curve (start→end) is divided into, "
              "also the physics node count. Higher = smoother droop; 1 = straight "
              "line with no droop",
        "ZH": "链条起点到终点的下垂曲线被分成的段数，同时也是物理节点数。数值越大下垂"
              "曲线越平滑；1=直线无下垂",
    },
    ("STRAINRIBBON", "uvRepetition"): {
        "EN": "Number of texture repeats along the chain's length. 0=default (most "
              "common value usually); 1=texture covers the whole chain once; "
              "larger=denser tiling that becomes a smooth line",
        "ZH": "贴图沿链条长度方向重复次数。0=默认（最常见取值）；1=贴图完整覆盖"
              "整条；越大锯齿越密变光滑线条",
    },
    ("STRAINRIBBON", "widthwiseUVScalingAlpha"): {
        "EN": "Texture widthwise alpha-channel scaling. 0.1=ultra-thin laser line; "
              "1=default (most common value usually); 5=extreme expansion, "
              "dense texture",
        "ZH": "贴图宽度方向透明通道缩放。0.1=极细激光线状；1=默认（最常见取值）；"
              "5=极度扩张纹理密集",
    },
    ("STRAINRIBBON", "widthwiseUVScalingBML"): {
        "EN": "Texture widthwise lighting-channel scaling. 0.1=ultra-thin line; "
              "1=default; 5=greatly widened emissive texture with strong aliasing; pair "
              "with Alpha scaling for thickness/halo variation",
        "ZH": "贴图宽度方向光照通道缩放。0.1=极细线；1=默认；5=发光纹理宽度大增锯齿感强；与 Alpha 缩放配合做粗细/光晕变化",
    },
    # 下列字段是开关，不作为颜色处理。
    ("STRAINRIBBON", "endPointScatter"): {
        "EN": "Endpoint-scatter switch. 0=endpoint "
              "anchored to the end bone; non-zero=endpoint unanchored, multiple bolts "
              "appear at random surrounding positions scattering outward (magnitude has "
              "no effect, 0~255)",
        "ZH": "终点扩散开关。0=终点锚定到结束骨骼；非 0=终点不锚定，"
              "在四周随机位置出现多条闪电向外扩散（数值大小无影响，0~255）",
    },
    ("STRAINRIBBON", "originReleaseFlag"): {
        "EN": "Origin-release flag. 0=origin "
              "anchored to bone #1; non-zero=origin released, all chains emit from the "
              "end-bone position toward the map's world center",
        "ZH": "起点解锁标志。0=起点锚定到 1 号骨骼；非 0=起点解锁，"
              "所有链条从结束骨骼位置朝地图世界中心方向发射",
    },
    ("STRAINRIBBON", "endBoneID"): {
        "EN": "Chain end-bound bone ID; extends from bone #1 to this bone, deciding the "
              "covered weapon-region extent (1=1-1, 3=higher per BT)",
        "ZH": "链条末端绑定骨骼编号，从 1 号骨骼延伸到此骨骼，决定覆盖的武器区域范围（BT：1=1-1，3=更远）",
    },
    ("STRAINRIBBON", "epv_color_slot1"): {
        "EN": "EPV colour slot id for `color`. Non-zero means: take the colour from that slot of the calling .epv instead of the value on this attribute, so editing the local colour has no effect while a slot id is set.",
        "ZH": "`color` 的 EPV 颜色槽位 id。写非 0 就改用调用方 .epv 里对应槽位的颜色，顶掉本属性上的值——所以槽位 id 非 0 时，在这里改颜色是不生效的。",
    },
    ("STRAINRIBBON", "epv_color_slot2"): {
        "EN": "EPV colour slot id for `colorRange`. Same mechanism as epv_color_slot1.",
        "ZH": "`colorRange` 的 EPV 颜色槽位 id，机制同 epv_color_slot1。",
    },
    ("STRAINRIBBON", "angleRelated"): {
        "EN": "Angle-related parameter. Fixed at 360.0 (a full circle), likely an unused default.",
        "ZH": "角度相关参数，固定为 360.0（整圆），可能是未使用的默认值。",
    },
    ("STRAINRIBBON", "angleRelatedJitter"): {
        "EN": "Random variation of the angle-related parameter. Fixed at 0.0.",
        "ZH": "角度相关参数的随机偏差，固定为 0.0。",
    },
    # 链条物理参数
    ("STRAINRIBBON", "lengthBreakpoint"): {
        "EN": "Length breakpoint (chain-break-related physics parameter)",
        "ZH": "长度断点（链条断裂相关物理参数）",
    },
    ("STRAINRIBBON", "tension"): {
        "EN": "Tension (chain physics parameter)",
        "ZH": "张力（链条物理参数）",
    },
    ("STRAINRIBBON", "gravityMultiplier"): {
        "EN": "Gravity multiplier (chain-droop physics parameter)",
        "ZH": "重力乘数（链条下垂物理参数）",
    },
    ("STRAINRIBBON", "inertia"): {
        "EN": "Inertia (chain physics parameter)",
        "ZH": "惯性（链条物理参数）",
    },
    ("STRAINRIBBON", "poseSnapping"): {
        "EN": "Pose snapping (chain physics parameter)",
        "ZH": "姿势捕捉（链条物理参数）",
    },
    ("STRAINRIBBON", "displacement"): {
        "EN": "Displacement (chain physics parameter; Z does not seem to work per BT)",
        "ZH": "位移（链条物理参数；据 BT，Z 似乎无效）",
    },
    ("STRAINRIBBON", "displacementToggle"): {
        "EN": "Displacement toggle. Per BT: 0=everything works; 1/2=kills the previous "
              "displacement; 3=kills displacement",
        "ZH": "位移开关。据 BT：0=一切正常；1/2=消除前一个位移；3=消除位移",
    },

    # ─── 行为补充 ─────────────────────────────────────────────────────────────
    # SPAWN
    ("SPAWN", "loopNum"): {
        "EN": "Bursts per round, re-rolled at the start of every round. 0 = the round never "
              "ends and bursts continue forever, so revival never happens.",
        "ZH": "每轮发几批，每轮开始时重新抽取。0 = 这一轮不会结束、一直发下去，"
              "也就不会复活。",
    },
    ("SPAWN", "loopNumJitter"): {
        "EN": "Random range added to Loop Num, re-rolled every round.",
        "ZH": "叠加到每轮批次数上的随机量，每轮重新抽取。",
    },
    ("SPAWN", "intervalFrame"): {
        "EN": "Frames between bursts within one round.",
        "ZH": "同一轮里相邻两批之间的帧数。",
    },
    ("SPAWN", "intervalFrameJitter"): {
        "EN": "Random jitter added to intervalFrame.",
        "ZH": "叠加到 intervalFrame 上的随机抖动。",
    },
    ("SPAWN", "revivalInterval"): {
        "EN": "Frames from a round's last burst to the start of the next round. Particle "
              "lifetime does not delay it; 0 = the next round starts on the next frame. "
              "Only applies when Revival Loop is not 1.",
        "ZH": "一轮的最后一批发出后，到下一轮开始的帧数，不等粒子消失；0 = 下一帧就开始。"
              "复活轮数为 1 时不生效。",
    },
    ("SPAWN", "revivalIntervalJitter"): {
        "EN": "Random range added to Revival Interval.",
        "ZH": "叠加到复活间隔上的随机量。",
    },
    # LIFE
    ("LIFE", "indefiniteLifespan"): {
        "EN": "1 → particle ignores fade-in/out and lives forever; only disappears when the "
              "weapon's major state switches or an action force-clears all FX (disappearance "
              "still obeys the Vanish time). ⚠ Combine with high SPAWN counts = accumulation.",
        "ZH": "1 → 无视渐入渐出、粒子永久存在；除非切换武器大状态或动作强制关闭所有特效才消失"
              "（消失仍遵循淡出时间）。⚠ 与高 SPAWN 数量组合会累积。",
    },
    # EMITTERSHAPE3D
    ("EMITTERSHAPE3D", "rangeXYZ"): {
        "EN": "Per-axis spawn range, given as offset + size for every shape. Offset is the "
              "inner boundary (the hollow core), size is the thickness of the shell particles "
              "spawn in, so the outer boundary sits at offset + size. Size 0 spawns particles "
              "on the inner surface only. Exception: on the cylinder the Y pair is its height "
              "and grows one way — offset Y is the base, size Y is how far it rises "
              "towards +Y.",
        "ZH": "逐轴的生成范围，所有形状都是偏移+尺寸的组合。偏移是内边界（中间的空腔），"
              "尺寸是粒子生成的那层壳的厚度，外边界位于偏移+尺寸处。尺寸为 0 时粒子只在"
              "内边界表面上生成。例外：圆柱体的 Y 那一对是高度，且只朝一个方向长——"
              "偏移 Y 是底面位置，尺寸 Y 是向 +Y 长出去的高度。",
    },
    ("EMITTERSHAPE3D", "scanAngleHorizontal"): {
        "EN": "Horizontal sweep angle, used by the sphere and the cylinder. 360 = all round, "
              "180 = half of it, 90 = a quarter (a watermelon-slice shape).",
        "ZH": "横向扫描角度，球体和圆柱体使用。360=全向生成，180=只生成一半，"
              "90=只生成 1/4（西瓜片那样的形状）。",
    },
    ("EMITTERSHAPE3D", "rangeDivideVerticalNum"): {
        "EN": "Number of vertical divisions: fan slices around the upright axis, i.e. what you "
              "see cut into n pieces when looking straight down. Every shape uses it (box, "
              "sphere, cylinder) - a sphere sliced this way looks like n leaves from the side. "
              "0 or 1 = no division.",
        "ZH": "纵向等分数量：绕竖轴切出的扇形切片，也就是从正上方看下去被分成 n 份。"
              "立方体、球体、圆柱体都用它——球体这样切，从侧面看就是 n 个叶片。"
              "0 或 1 = 不等分。",
    },
    ("EMITTERSHAPE3D", "radiusEnd"): {
        "EN": "Radius at the far end, as a ratio of the generation range. The cylinder is the "
              "only shape that uses it: with radiusOrigin these are the radii of its two ends, "
              "so 1 and 1 is a plain cylinder, unequal values give a frustum, and 0 gives a cone.",
        "ZH": "远端半径，取值是生成范围的比例。只有圆柱体用得上：它和起始半径是圆柱两端的"
              "半径，两者都是 1 就是圆柱，不相等就是圆台，其中一个给 0 就是圆锥。",
    },
    ("EMITTERSHAPE3D", "radiusOrigin"): {
        "EN": "Radius at the near end, as a ratio of the generation range (cylinder only). "
              "Set it to 0.2 against radiusEnd 1.0 and you get a frustum whose two ends are "
              "5:1 in diameter.",
        "ZH": "近端半径，取值是生成范围的比例（只有圆柱体用）。设成 0.2、结束半径留 1.0，"
              "得到的就是两端直径 5:1 的圆台。",
    },
    # VELOCITY3D
    ("VELOCITY3D", "rotationX"): {
        "EN": "Rotates speed's direction, around the X axis. Only meaningful when "
              "velocityType=Directional.",
        "ZH": "旋转 speed 的朝向，绕 X 轴旋转。仅在 velocityType=Directional 时有意义。",
    },
    ("VELOCITY3D", "rotationY"): {
        "EN": "Rotates speed's direction, around the Y axis. Only meaningful when "
              "velocityType=Directional.",
        "ZH": "旋转 speed 的朝向，绕 Y 轴旋转。仅在 velocityType=Directional 时有意义。",
    },
    ("VELOCITY3D", "rotationZ"): {
        "EN": "Rotates speed's direction, around the Z axis. Only meaningful when "
              "velocityType=Directional.",
        "ZH": "旋转 speed 的朝向，绕 Z 轴旋转。仅在 velocityType=Directional 时有意义。",
    },
    ("VELOCITY3D", "speed"): {
        "EN": "Grants particles their initial velocity.",
        "ZH": "赋予粒子初速度。",
    },
    ("VELOCITY3D", "speedJitter"): {
        "EN": "Random variation added to the initial speed.",
        "ZH": "初速度的随机偏差。",
    },
    ("VELOCITY3D", "speedCoefJitter"): {
        "EN": "Random jitter on acceleration (same nature as the velocity jitter).",
        "ZH": "加速度偏差（性质同初速度偏差）。",
    },
    ("VELOCITY3D", "gravityDelay"): {
        "EN": "Frames before gravity takes effect.",
        "ZH": "gravity 生效前的延迟帧数。",
    },
    ("VELOCITY3D", "movementDelay"): {
        "EN": "Frames before speed takes effect.",
        "ZH": "速度生效前的延迟帧数。",
    },
    ("VELOCITY3D", "offsetX"): {
        "EN": "Each particle's direction is computed per axis as "
              "V_i = (size_i - 1) x i0 + offset_i, where i0 is that particle's own "
              "spawn coordinate on axis i, then normalized — only the direction is used, the "
              "speed comes from speed/acceleration. offset is simply the common movement "
              "direction shared by all particles, regardless of where each one spawned.",
        "ZH": "每个粒子的运动方向按下式逐轴算出：V_i =（size_i − 1）× i0 + offset_i，"
              "其中 i0 是该粒子生成时在 i 轴上的坐标；算完再归一化——只取方向，速度大小由"
              "初速度/加速度决定。offset 可以简单视作全体粒子共同的运动方向，与各自在哪"
              "生成无关。",
    },
    ("VELOCITY3D", "offsetY"): {
        "EN": "See offsetX.",
        "ZH": "见 offsetX。",
    },
    ("VELOCITY3D", "offsetZ"): {
        "EN": "See offsetX.",
        "ZH": "见 offsetX。",
    },
    ("VELOCITY3D", "sizeX"): {
        "EN": "Direction is computed per axis as V_i = (size_i - 1) x i0 + offset_i, "
              "where i0 is that particle's own spawn coordinate on axis i. size is simply "
              "how strongly particles spread out from / collapse toward the center, scaled by "
              "where each one spawned: 1 = no effect on this axis; >1 = spreads outward; "
              "<1 = converges inward, passing through to the other side. Direction only — the "
              "magnitude does not change the speed.",
        "ZH": "运动方向按下式逐轴算出：V_i =（size_i − 1）× i0 + offset_i，其中 i0 是"
              "该粒子生成时在 i 轴上的坐标。size 可以简单视作以生成位置为基础的发散/"
              "收拢强度：1=该轴无效果；>1 向外发散；<1 向内收拢（会穿过中心继续到对面）。"
              "只影响方向，数值大小不影响速度。",
    },
    ("VELOCITY3D", "sizeY"): {
        "EN": "See sizeX.",
        "ZH": "见 sizeX。",
    },
    ("VELOCITY3D", "sizeZ"): {
        "EN": "See sizeX.",
        "ZH": "见 sizeX。",
    },
    # BILLBOARD3D
    ("BILLBOARD3D", "color"): {
        "EN": "Base color (RGBA). Shown as-is when useColorRange is off.",
        "ZH": "基准颜色（RGBA）。useColorRange 关闭时固定显示这个颜色。",
    },
    ("BILLBOARD3D", "colorRange"): {
        "EN": "The other end of the color range (RGBA). Only used when useColorRange "
              "is on — the displayed color then randomly varies between color and "
              "colorRange.",
        "ZH": "颜色范围的另一端（RGBA）。仅在 useColorRange 开启时生效——开启后，最终"
              "显示的颜色会在 color 与 colorRange 之间随机变化。",
    },
    ("BILLBOARD3D", "useColorRange"): {
        "EN": "Color random-range switch. 0 = off (always shows color). 1 = on "
              "(displayed color randomly varies between color and colorRange).",
        "ZH": "颜色随机范围开关。0=禁用（始终显示 color）；1=启用（最终显示的颜色会在 "
              "color 与 colorRange 之间随机变化）。",
    },
    ("BILLBOARD3D", "brightnessJitter"): {
        "EN": "Jitter paired with brightness.",
        "ZH": "与亮度配对的抖动量。",
    },
    ("BILLBOARD3D", "blendMode"): {
        "EN": _EMISSIVE_TIP_EN,
        "ZH": _EMISSIVE_TIP_ZH,
    },
    # SCALEANIM
    ("SCALEANIM", "sizeScalarAddCoef"): {
        "EN": "The speed above is multiplied by this every frame. 1 = constant speed, below 1 slows down; 0 counts as 1.",
        "ZH": "上面的速度每帧乘一次此值。1 为匀速，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("SCALEANIM", "sizeXAdd"): {
        "EN": "Added to the X size ratio every frame; the ratio starts at 1. -0.0167 shrinks to 0 in about 1 second.",
        "ZH": "每帧加到 X 方向尺寸倍率上的量，倍率从 1 开始。-0.0167 约 1 秒缩到 0。",
    },
    ("SCALEANIM", "sizeXAddCoef"): {
        "EN": "The speed above is multiplied by this every frame. 1 = constant speed, below 1 slows down; 0 counts as 1.",
        "ZH": "上面的速度每帧乘一次此值。1 为匀速，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("SCALEANIM", "sizeYAdd"): {
        "EN": "Added to the Y size ratio every frame; the ratio starts at 1.",
        "ZH": "每帧加到 Y 方向尺寸倍率上的量，倍率从 1 开始。",
    },
    ("SCALEANIM", "sizeYAddCoef"): {
        "EN": "The speed above is multiplied by this every frame. 1 = constant speed, below 1 slows down; 0 counts as 1.",
        "ZH": "上面的速度每帧乘一次此值。1 为匀速，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("SCALEANIM", "sizeZAdd"): {
        "EN": "Added to the Z size ratio every frame; the ratio starts at 1. Only affects meshes.",
        "ZH": "每帧加到 Z 方向尺寸倍率上的量，倍率从 1 开始。仅对模型有效。",
    },
    ("SCALEANIM", "sizeZAddCoef"): {
        "EN": "The speed above is multiplied by this every frame. 1 = constant speed, below 1 slows down; 0 counts as 1.",
        "ZH": "上面的速度每帧乘一次此值。1 为匀速，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("SCALEANIM", "animUpdateStart"): {
        "EN": "Frames to wait before any scaling starts.",
        "ZH": "开始缩放前等待的帧数。",
    },
    # ROTATEANIM
    ("ROTATEANIM", "billboardRotation"): {
        "EN": "BILLBOARD3D plane rotation (static value; pairs with billboardRotationJitter as "
              "the random).",
        "ZH": "BILLBOARD3D 平面旋转（固定值；与 billboardRotationJitter 组成 static/random 一组）。",
    },
    ("ROTATEANIM", "billboardRotationJitter"): {
        "EN": "Random component of billboardRotation.",
        "ZH": "billboardRotation 的随机分量。",
    },
    ("ROTATEANIM", "spin_velocity"): {
        "EN": "Model/plane rotation along three axes (with spinAccelerationX/Y/Z below for each).",
        "ZH": "模型/平面的三轴旋转方式（下方 spinAccelerationX/Y/Z 为各自加速度）。",
    },

    # ─── LIGHTNING ────────────────────────────────────────────────────────────
    ("LIGHTNING", "spacer0"): {
        "EN": "Memory-alignment padding (-842150656). Do not edit.",
        "ZH": "内存对齐占位符（-842150656）。请勿编辑。",
    },
    ("LIGHTNING", "useColorRange"): {
        "EN": "Each bolt picks a random color between Color and Color Range.",
        "ZH": "开启后每道闪电在颜色与颜色范围之间随机取色。",
    },
    ("LIGHTNING", "blendMode"): {
        "EN": _EMISSIVE_TIP_EN,
        "ZH": _EMISSIVE_TIP_ZH,
    },
    ("LIGHTNING", "unknBool05_00"): {
        "EN": "Unknown switch. Usually off.",
        "ZH": "作用未知的开关，通常关闭。",
    },
    ("LIGHTNING", "unknBool05_14"): {
        "EN": "Unknown switch. Usually off (on in about 16% of effects).",
        "ZH": "作用未知的开关，通常关闭（约 16% 开启）。",
    },
    ("LIGHTNING", "section_length"): {
        "EN": "Section length, fixed at 108. Do not change it.",
        "ZH": "段长度，固定为 108，请勿修改。",
    },
    ("LIGHTNING", "color"): {
        "EN": "Bolt color RGBA (0~255). With Use Color Range on, each bolt picks a "
              "random color between Color and Color Range.",
        "ZH": "闪电颜色 RGBA（0～255）。开启颜色范围后，每道闪电在颜色与颜色范围之间"
              "随机取色。",
    },
    ("LIGHTNING", "colorRange"): {
        "EN": "Random color range paired with Color; only works when Use Color Range "
              "is on.",
        "ZH": "与颜色配对的随机颜色范围；仅在启用颜色范围时生效。",
    },
    ("LIGHTNING", "brightness"): {
        "EN": "Brightness. Only works when Enable Emissive is on. Common values 1~10, "
              "occasionally above 200.",
        "ZH": "亮度。仅在启用自发光时生效。常见值为 1～10，个别高于 200。",
    },
    ("LIGHTNING", "brightnessJitter"): {
        "EN": "Jitter paired with brightness.",
        "ZH": "与亮度配对的抖动量。",
    },
    ("LIGHTNING", "unknEnum05_01"): {
        "EN": "Instance mode flag (lightningInstanceModeFlag). 1=standard single instance; "
              "2=high-complexity triple instance; any other value=high-complexity double "
              "instance. Controls instance count AND waveform complexity together.",
        "ZH": "闪电实例模式标志。1=标准单实例；2=高复杂度三实例；其余值=高复杂度双实例。"
              "同时控制实例数量与波形弯曲复杂度。",
    },
    ("LIGHTNING", "sineWaveFreq"): {
        "EN": "Sine wave frequency. 0=lightning disappears (also a spawn precondition); "
              "0.15≈near-straight; 0.5=default; 10=dense zigzag. Negative = abs value. "
              "Regular wave shape (vs inflectionPointCount's random jaggedness).",
        "ZH": "正弦波频率。0=闪电消失（同时是生成必要条件）；0.15≈接近直线；0.5默认；"
              "10=密集锯齿；负数取绝对值。规律正弦波形（区别于 inflectionPointCount 的随机折线）。",
    },
    ("LIGHTNING", "sineWaveFreqJitter"): {
        "EN": "Random jitter on sineWaveFreq; larger = more per-bolt frequency variation.",
        "ZH": "正弦波频率随机抖动；越大每条闪电弯折密度差异越大。",
    },
    ("LIGHTNING", "alphaThreshold"): {
        "EN": "Alpha cutoff threshold (default 0.2). Higher → overall less visible (edges "
              "clipped); lower → loses texture detail, shows raw geometry. Suggested 0.2~2.",
        "ZH": "alpha 截断阈值（默认 0.2）。调高→整体越不可见（边缘被截断）；调低→丢失贴图纹理"
              "细节、呈现几何形态。双向都增透明。建议 0.2~2。",
    },
    ("LIGHTNING", "spawnBranchRangeMin"): {
        "EN": "Start of the stretch of trunk that grows branches, as a ratio of its "
              "length (0~1). Usually 0.",
        "ZH": "主干上长出分支的区间起点，按主干长度的比例计（0～1）。通常为 0。",
    },
    ("LIGHTNING", "spawnBranchRangeMax"): {
        "EN": "End of the stretch of trunk that grows branches, as a ratio of its "
              "length (0~1). Usually 1.",
        "ZH": "主干上长出分支的区间终点，按主干长度的比例计（0～1）。通常为 1。",
    },
    ("LIGHTNING", "spawnBranchCone"): {
        "EN": "Cone angle for branch directions, in degrees. Common values 0, 45, 120; "
              "up to 360.",
        "ZH": "分支生成方向的锥角（度）。常见值为 0、45、120，最大 360。",
    },
    ("LIGHTNING", "outwardsExpansionSpeed"): {
        "EN": "Outward expansion speed/radius (NOT path flow speed). 1=default; 100=expands "
              "outward fast/wide — straight bolts arc outward, complex bolts coil outward.",
        "ZH": "向外扩展速度/半径（非沿路径流速）。1默认；100=整体大速度大半径外扩——"
              "直线形态→圆弧扩展，复杂形态→缠绕扩展。",
    },
    ("LIGHTNING", "outwardsExpansionSpeedJitter"): {
        "EN": "Random jitter on outwardsExpansionSpeed; default 1 gives large per-bolt spread.",
        "ZH": "向外扩展速度随机抖动；默认 1，每条闪电外扩速度/半径差异较大，产生自然不规则感。",
    },
    ("LIGHTNING", "unkn05_10"): {
        "EN": "Lightning opacity (lightningOpacity). 0=invisible, 10=normal; effective 0~10. "
              "⚠ Negative triggers int16 overflow (unstable, e.g. -42000 wraps to invisible) "
              "— do not use negatives.",
        "ZH": "闪电不透明度。0=消失，10=正常；有效区间 0~10。"
              "⚠ 负数触发 int16 溢出（不稳定，如 -42000 回绕变消失）——勿用负数。",
    },
    ("LIGHTNING", "unknEnum05_11"): {
        "EN": "Transparency level B (lightningTransparencyLevel). 1=most opaque, 3=default, "
              "higher=more transparent; effective 1~300+. Negative=fully transparent "
              "(stable). Integer only. Low precision (vs unkn05_10).",
        "ZH": "闪电透明度等级B。1最不透明，3默认，越大越透明；有效 1~300+。"
              "负数=完全透明（稳定无溢出）。仅整数。精度低于 unkn05_10。",
    },
    ("LIGHTNING", "unknFlag05_12"): {
        "EN": "Flow & fade mode (lightningFlowAndFadeMode). 0=faster flow + keep fade-out; "
              "1=default (standard flow + fade); any other value=no flow change + fade-out "
              "cancelled (hard cut at end of life). Integer only.",
        "ZH": "流光与淡出模式。0=流光加速+保留淡出；1=默认（标准流光+淡出渐隐）；"
              "非0非1=流光无变化+淡出取消（生命周期结束直接硬切消失）。仅整数。",
    },
    ("LIGHTNING", "unknEnum05_13"): {
        "EN": "No visible effect.",
        "ZH": "修改后无可见效果。",
    },
    ("LIGHTNING", "terminalJointNo"): {
        "EN": "Bone the end of the bolt reaches. -1 = no bone.",
        "ZH": "闪电末端连接的骨骼编号；-1 表示不连接骨骼。",
    },
    ("LIGHTNING", "unknEnum05_16"): {
        "EN": "No visible effect.",
        "ZH": "修改后无可见效果。",
    },
    ("LIGHTNING", "unknFlag05_17"): {
        "EN": "No visible effect.",
        "ZH": "修改后无可见效果。",
    },
    ("LIGHTNING", "EPVColorSlot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("LIGHTNING", "EPVColorSlot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    **_lightning_annotations(),
    ("LIGHTNING", "unknFixed14_2"): {
        "EN": "Section length, fixed at 38. Do not change it.",
        "ZH": "段长度，固定为 38，请勿修改。",
    },
    ("LIGHTNING", "unknEnum16"): {
        "EN": "No visible effect.",
        "ZH": "修改后无可见效果。",
    },

    # ─── 常见取值提示 ──────────────────────────────────────────────────────────
    # 提示的常见范围不是字段的合法值限制。
    # ALPHACORRECTION 的对应头字段名为 unkn0。
    ("ALPHACORRECTION", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common range: 1~11 (rare outliers up to 45).",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见范围 "
              "1~11（个别情况可达 45）。",
    },
    ("BILLBOARD2D", "scaleJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("BILLBOARD2D", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [1, 5, 6, 7, 8, 10].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 5, 6, 7, 8, 10]。",
    },
    ("BILLBOARD2D", "blendMode"): {
        "EN": _EMISSIVE_TIP_EN,
        "ZH": _EMISSIVE_TIP_ZH,
    },
    ("BILLBOARD2D", "correctColorNo"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD2D", "colorRangeCorrectColorNo"): {
        "EN": 'EPV colour slot id, same mechanism as correctColorNo. Exactly which attribute this targets is unknown; non-zero takes the attribute from that slot instead of the value here. 0 = use the local value.',
        "ZH": 'EPV 颜色槽位 id，机制同 correctColorNo。具体对应哪个属性未知；写非 0 就改用对应 id 槽位里的属性，顶掉本属性上的值；0 = 用本地值。',
    },
    ("BILLBOARD2D", "unknEnum5_1"): {
        "EN": "Common values: [0, 1, 3].",
        "ZH": "常见取值为 [0, 1, 3]。",
    },
    ("BILLBOARD3D", "correctColorNo"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD3D", "colorRangeCorrectColorNo"): {
        "EN": 'EPV colour slot id, same mechanism as correctColorNo. Exactly which attribute this targets is unknown; non-zero takes the attribute from that slot instead of the value here. 0 = use the local value.',
        "ZH": 'EPV 颜色槽位 id，机制同 correctColorNo。具体对应哪个属性未知；写非 0 就改用对应 id 槽位里的属性，顶掉本属性上的值；0 = 用本地值。',
    },
    ("BILLBOARD3D", "enableGPUParticle"): {
        "EN": "When on, extra brightness is added on top of Brightness; the particle glows even at Brightness 0.",
        "ZH": "开启后在亮度之外叠加额外的亮度，亮度为 0 时也会发光。",
    },
    ("BILLBOARD3D", "divideNum"): {
        "EN": "Common values: [0, 1, 2, 3, 4, 10].",
        "ZH": "常见取值为 [0, 1, 2, 3, 4, 10]。",
    },
    ("BILLBOARD3D", "fieldInfluenceRate"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD3D", "fieldInfluenceRateMultiplier"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD3D", "lightGroup"): {
        "EN": 'Packed flags edited via the popup: which light groups this billboard reacts to. All 8 bits are independently used; a value of 255 is a distinct "affected by all groups" sentinel, not just the union of the 8 individual bits.',
        "ZH": '打包标志，用弹窗编辑：这个 Billboard 对哪些光照组作出反应。8 位全部独立使用；255 是单独的"对全部光照组都反应"哨兵值，不只是 8 个独立位的自然并集。',
    },
    ("BILLBOARD3D", "unknFlag9"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("BLINK", "section_length"): {
        "EN": "Structural remaining-length marker (== total block size - 8), computed "
              "by the engine; not a tunable parameter. Common values: [5, 30, 44].",
        "ZH": "结构性剩余长度标记（=块总字节数-8），由引擎计算，非可调参数。常见取值为 "
              "[5, 30, 44]。",
    },
    ("BLINK", "minAlphaRate"): {
        "EN": "Lowest alpha multiplier the blink reaches. The blink always sweeps the whole range between the min and max, not just its ends.",
        "ZH": "闪烁时透明度倍率的下限。闪烁会扫过最小到最大之间的整个区间，不只停在两端。",
    },
    ("BLINK", "maxAlphaRate"): {
        "EN": "Highest alpha multiplier the blink reaches.",
        "ZH": "闪烁时透明度倍率的上限。",
    },
    ("BLINK", "lowFrequency"): {
        "EN": "Blink speed of the low-frequency channel; adds together with the high-frequency channel. At 0 this channel stops oscillating. To turn the channel off, set lowFrequencyWidth to 0.",
        "ZH": "低频通道的闪烁速度，与高频通道叠加生效。设为 0 时该通道不再摆动。要关闭该通道，请把 lowFrequencyWidth 设为 0。",
    },
    ("BLINK", "lowFrequencyWidth"): {
        "EN": "Blink depth of the low-frequency channel — the higher, the more pronounced. Set to 0 to fully disable this channel.",
        "ZH": "低频通道的闪烁深度，越大摆动越明显。设为 0 即可彻底关闭这一通道。",
    },
    ("BLINK", "highFrequency"): {
        "EN": "Blink speed of the high-frequency channel; adds together with the low-frequency channel. At 0 this channel stops oscillating. To turn the channel off, set highFrequencyWidth to 0.",
        "ZH": "高频通道的闪烁速度，与低频通道叠加生效。设为 0 时该通道不再摆动。要关闭该通道，请把 highFrequencyWidth 设为 0。",
    },
    ("BLINK", "highFrequencyWidth"): {
        "EN": "Blink depth of the high-frequency channel — the higher, the more pronounced. Set to 0 to fully disable this channel.",
        "ZH": "高频通道的闪烁深度，越大摆动越明显。设为 0 即可彻底关闭这一通道。",
    },
    ("BLINK", "lowFrequencyJitter"): {
        "EN": "Per-particle random offset applied to lowFrequency, so particles don't blink in sync. Common range: 0~100.",
        "ZH": "对 lowFrequency 施加的逐粒子随机偏移，避免多个粒子同步闪烁。常见取值在 0~100 之间。",
    },
    ("BLINK", "lowFrequencyWidthJitter"): {
        "EN": "Per-particle random offset applied to lowFrequencyWidth. Common range: 0~100.",
        "ZH": "对 lowFrequencyWidth 施加的逐粒子随机偏移。常见取值在 0~100 之间。",
    },
    ("BLINK", "highFrequencyJitter"): {
        "EN": "Per-particle random offset applied to highFrequency, so particles don't blink in sync. Common range: 0~100.",
        "ZH": "对 highFrequency 施加的逐粒子随机偏移，避免多个粒子同步闪烁。常见取值在 0~100 之间。",
    },
    ("BLINK", "highFrequencyWidthJitter"): {
        "EN": "Per-particle random offset applied to highFrequencyWidth. Common range: 0~100.",
        "ZH": "对 highFrequencyWidth 施加的逐粒子随机偏移。常见取值在 0~100 之间。",
    },
    ("EMITTERSHAPE2D", "rangeX"): {
        "EN": "X spawn range, the 2D counterpart of EMITTERSHAPE3D.rangeXYZ: offset is the "
              "inner boundary (the hollow core), size is the thickness of the band particles "
              "spawn in, so the outer boundary sits at offset + size. Size 0 spawns particles "
              "on the inner edge only.",
        "ZH": "X 轴生成范围，EMITTERSHAPE3D.rangeXYZ 的 2D 版本：偏移是内边界（中间的空腔），"
              "尺寸是粒子生成的那圈带的厚度，外边界位于偏移+尺寸处。尺寸为 0 时粒子只在内"
              "边界上生成。",
    },
    ("EMITTERSHAPE2D", "rangeXJitter"): {
        "EN": "See rangeX — this is the size half of the pair, not a random jitter.",
        "ZH": "见 rangeX——这是配对里的「尺寸」半边，不是随机抖动量。",
    },
    ("EMITTERSHAPE2D", "rangeY"): {
        "EN": "Y-axis counterpart of rangeX.",
        "ZH": "rangeX 的 Y 轴对应。",
    },
    ("EMITTERSHAPE2D", "rangeYJitter"): {
        "EN": "See rangeX — this is the size half of the pair, not a random jitter.",
        "ZH": "见 rangeX——这是配对里的「尺寸」半边，不是随机抖动量。",
    },
    ("EMITTERSHAPE2D", "rangeDivideHorizontalNum"): {
        "EN": "Number of divisions along the shape, 0 = continuous. The 2D counterpart of "
              "EMITTERSHAPE3D.rangeDivideHorizontalNum — it subdivides the spawn range, it is "
              "not a particle count. Common values: [0, 3, 5, 6, 8, 10, 16, 18].",
        "ZH": "沿形状的等分数量，0=连续铺满。EMITTERSHAPE3D.横向等分数量的 2D 版本——它切分的"
              "是生成范围，不是粒子个数。常见取值为 [0, 3, 5, 6, 8, 10, 16, 18]。",
    },
    ("EMITTERSHAPE2D", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 7, 8, 9, 13].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 7, 8, 9, 13]。",
    },
    ("EMITTERSHAPE2D", "shapeType"): {
        "EN": "2D spawn shape: 0=square, 1=circle. The meaning of values 2 and above is unknown.",
        "ZH": "二维生成形状：0=方形，1=圆形。取值 2 及以上的含义未知。",
    },
    ("EMITTERSHAPE2D", "rangeDivideAxis"): {
        "EN": "Which axis the square spawn range is subdivided along. 0=Y axis, 1=X axis; value 2 occurs in about 4% of cases and its meaning is unknown. About 94% use 0.",
        "ZH": "方形生成范围沿哪个轴细分。0=Y 轴，1=X 轴；约 4% 使用取值 2，其含义未知。约 94% 使用 0。",
    },
    ("EMITTERSHAPE2D", "unknFixed22_1"): {
        "EN": "Fixed at 0.",
        "ZH": "固定为 0。",
    },
    ("EMITTERSHAPE3D", "rotationOrder"): {
        "EN": "Order the local rotation axes are applied in.",
        "ZH": "局部旋转各轴的应用顺序。",
    },
    ("EMITTERSHAPE3D", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]。",
    },
    ("EMITTERSHAPE3D", "rangeDivideAxis"): {
        "EN": "Which axis the box is subdivided along. Not affected by localRotation.",
        "ZH": "立方体沿哪个轴细分。不受局部旋转影响。",
    },
    ("EMITTERSHAPE3D", "scanAngleVertical"): {
        "EN": "Vertical sweep angle - the sphere only. It works the other way round from the "
              "horizontal one: 0 = all round, 180 = half of it, 360 = nothing spawns at all. "
              "Combined with a horizontal limit this is how you carve out a corner of a sphere.",
        "ZH": "纵向扫描角度，只有球体使用。方向与横向那个相反：0=全向生成，180=生成一半，"
              "360=完全不生成。配上横向限制就能切出球体的一个角。",
    },
    ("EMITTERSHAPE3D", "unknFlag4"): {
        "EN": "Purpose unknown. Usually on.",
        "ZH": "作用未知，大多开启。",
    },
    ("EMITTERSHAPE3D", "rayCastDependency"): {
        "EN": "How a RayCast hit distance is applied to the spawn range. "
              "0 = None (range unchanged); 1 = Equal (range becomes the distance the ray has "
              "travelled); 2 = Multiply (that distance times the offset); 3 = Min (clamped at "
              "the offset, stops growing); 4 = Max (keeps growing past the offset); "
              "5 = Offset (the whole range shifts along the ray, ending at the ray's max distance).",
        "ZH": "射线检测的命中距离以何种运算作用到生成范围上。"
              "0 = 无（范围不变）；1 = 相等（范围等于射线已行进的距离）；"
              "2 = 相乘（该距离 × 偏移量）；3 = 取最小值（到达偏移量后不再增长）；"
              "4 = 取最大值（超过偏移量后继续增长）；"
              "5 = 偏移（范围整体随射线平移，终点为射线的最大距离）。",
    },
    ("EMITTERSHAPEMESH", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 4, 5, 6, 7, 9].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 9]。",
    },
    ("EMITTERSHAPEMESH", "unknFlag2_0"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "ddsUsageType"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "unknFlag2_2"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "visconIndex"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "unknEnum2_5"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "unknEnum2_6"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EMITTERSHAPEMESH", "unknEnum2_7"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("EXTERNREFERENCE", "trigger_condition"): {
        "EN": "Off: pick Index0/Index1 directly, no transition. Over Lifetime: switches on an "
              "external event, transitioning over transitionDuration after triggerDelay. "
              "Use Particle Lifetime (requires Over Lifetime): transitions automatically over "
              "transitionDuration, no external event needed.",
        "ZH": "全部关闭：直接按 Index0/Index1 取值，不做过渡。随生命周期过渡：由外部事件触发切换，"
              "在 triggerDelay 之后用 transitionDuration 完成过渡。按粒子生命周期（需同时开启随生命周期过渡）："
              "自动过渡，用 transitionDuration 完成，无需外部事件。",
    },
    ("EXTERNREFERENCE", "index0"): {
        "EN": "Common values: [0, 1, 2, 4].",
        "ZH": "常见取值为 [0, 1, 2, 4]。",
    },
    ("EXTERNREFERENCE", "index1"): {
        "EN": "Common values: [0, 1, 2, 3, 5].",
        "ZH": "常见取值为 [0, 1, 2, 3, 5]。",
    },
    ("EXTERNREFERENCE", "lerp"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("EXTERNREFERENCE", "transitionDuration"): {
        "EN": "Frame count over which Lerp interpolates from Index0 to Index1.",
        "ZH": "Lerp 从 Index0 过渡到 Index1 所用的帧数。",
    },
    ("EXTERNREFERENCE", "triggerDelay"): {
        "EN": "Frame count to wait after the trigger event before the transition starts.",
        "ZH": "触发事件发生后，等待多少帧再开始过渡。",
    },
    ("FADEBYANGLE", "cutoffConeAngle"): {
        "EN": 'half-angle of the cone (around baseAxis) inside which the effect is fully invisible.',
        "ZH": "以 baseAxis 为中心的锥角（半角），落在这个角度以内特效完全不可见。",
    },
    ("FADEBYANGLE", "fadeConeAngle"): {
        "EN": 'half-angle of the outer fade boundary — between cutoffConeAngle and this angle the effect fades gradually; beyond it, fully visible.',
        "ZH": '渐隐过渡区外边界的锥角（半角）——在 cutoffConeAngle 到这个角度之间做渐隐过渡，超出则完全可见。',
    },
    ("FADEBYANGLE", "minAlpha"): {
        "EN": 'floor alpha the fade can reach. 1 = never fades out; 0.5 = fades to half opacity at most.',
        "ZH": '渐隐能达到的最低 alpha。设为 1 时完全不触发消失，设为 0.5 时最多只淡到一半透明度。',
    },
    ("FADEBYANGLE", "baseAxis"): {
        "EN": 'The same AxisDirection6 enum as VELOCITY3D (0=left,1=up,2=front,3=right,4=down,5=back). Combined with axisRotationX/Y/Z + rotOrder to give the direction that triggers the fade.',
        "ZH": "与 VELOCITY3D 同一套 AxisDirection6 枚举"
              "（0=左,1=上,2=前,3=右,4=下,5=后）。与 axisRotationX/Y/Z + rotOrder 复合得到"
              "触发渐隐的朝向。",
    },
    ("FADEBYANGLE", "rotOrder"): {
        "EN": "The same rotation-order enum as VELOCITY3D (0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX). Composition: v' = Ry(axisRotationY)·Rx(axisRotationX)·Rz(axisRotationZ)·baseAxis.",
        "ZH": "与 VELOCITY3D 同一套旋转顺序枚举"
              "（0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX）。复合公式："
              "v' = Ry(axisRotationY)·Rx(axisRotationX)·Rz(axisRotationZ)·baseAxis。",
    },
    ("FADEBYANGLE", "coneVisibilityFlags"): {
        "EN": "All 8 bit combinations behave as follows. bit0 (Enable Double Cone): always mirrors the same rule onto the opposite cone (-baseAxis), independent of the other bits. bit1 (Exclude Cone): always swaps inside/outside visibility, independent of the other bits. bit2: alone it also swaps visibility, but is silently overridden (no effect) whenever bit0 is set — overall inversion = bit1 OR (bit2 AND NOT bit0). bit2's exact purpose is still unknown.",
        "ZH": '8 种位组合的行为如下。bit0（启用双锥）：恒定生效，把同一条规则镜像到对立角（-baseAxis），不受其他位影响。bit1（排除锥体）：恒定生效，互换锥角内/外的可见性，不受其他位影响。bit2：单独置位时也会反转可见性，但只要bit0=1 就完全失效——整体反转 = bit1 OR (bit2 且 bit0 为假)。bit2 具体作用未知。',
    },
    ("FADEBYOCCLUSION", "occlusionRadius"): {
        "EN": 'detection volume for occlusion — the larger this is, the more easily the shrink effect triggers.',
        "ZH": "遮挡判定体积——设得越大，越容易触发缩小效果。",
    },
    ("FADEBYOCCLUSION", "minScale"): {
        "EN": "minimum scale ratio the effect can shrink to. 1 = never shrinks.",
        "ZH": "特效被遮挡时允许缩小到的最小比例。设为 1 时完全不缩小。",
    },
    ("FADEBYOCCLUSION", "minAlpha"): {
        "EN": 'minimum alpha the effect can fade to while shrinking. 1 = shrinks only, never fades; 0 = fades out fully while shrinking.',
        "ZH": '特效缩小的同时允许淡到的最小透明度。设为 1 时只缩小不渐隐，设为 0 时缩小的同时会完全渐隐。',
    },
    ("FAKEDOF", "unkn4"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("FAKEPLANE", "unknEnum3"): {
        "EN": "Common values: [1, 2, 4].",
        "ZH": "常见取值为 [1, 2, 4]。",
    },
    ("GUIDE", "unkn1"): {
        "EN": "Not used by the game. Usually 0.",
        "ZH": "游戏不读取此值。通常为 0。",
    },
    ("GUIDE", "restitutionDelay"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("GUIDE", "restitutionDelayJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("GUIDE", "restitutionEccentricity"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "restitutionEccentricityJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "restitutionElasticity"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "restitutionElasticityJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "speed"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "speedJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn16"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn17"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn18"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn19"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn21"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("GUIDE", "unkn22"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("LIFE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 5, 6, 7, 8, 9, 10, 12].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 5, 6, 7, 8, 9, 10, 12]。",
    },
    ("LIFE", "unknFrame"): {
        "EN": "Usually 0; other common values: [2, 5, 10, 20, 30, 35, 40, 50, 100].",
        "ZH": "通常为 0；其余常见取值为 [2, 5, 10, 20, 30, 35, 40, 50, 100]。",
    },
    ("LIFE", "unknFrameJitter"): {
        "EN": "Usually 0; other common values: [5, 6, 10, 15, 20, 30, 40, 50, 60].",
        "ZH": "通常为 0；其余常见取值为 [5, 6, 10, 15, 20, 30, 40, 50, 60]。",
    },
    ("LIGHTNING", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 4, 7].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 4, 7]。",
    },
    ("LINKPARTSVISIBLE", "unknEnum0_2"): {
        "EN": "Common values: [2, 13, 15].",
        "ZH": "常见取值为 [2, 13, 15]。",
    },
    ("MATERIAL", "block_count"): {
        "EN": "Common values: [0, 1, 2, 3, 5, 6, 7].",
        "ZH": "常见取值为 [0, 1, 2, 3, 5, 6, 7]。",
    },
    ("MESH", "BeginMod3"): {
        "EN": "Five independent switches; effect unknown. Usually all off; Unknown Bit 4 is the most common one set.",
        "ZH": "五个独立开关，作用未知。通常全部关闭；最常开启的是未知位 4。",
    },
    ("MESH", "colorRate"): {
        "EN": "Overall intensity coefficient for the colour channel (the `color` / `colorRange` pair, not the emissive one). 1 = unchanged; 53% of blocks leave it at 1.0, but values well past 100 occur. Driven by the ColorRate timeline parameter on the A1 (lifetime) axis. Among blocks that move it off 1.0, 84% also have enableIntensity2 switched on.",
        "ZH": '`color` / `colorRange` 那条通道的整体强度系数（不是自发光那条）。1 = 原样，约 53% 使用 1.0，但可超过 100。对应 ColorRate 时间线参数，走 A1（寿命轴）。调离 1.0 时，常同时启用 enableIntensity2。',
    },
    ("MESH", "colorRateJitter"): {
        "EN": "Random spread for colorRate — the actual value lands somewhere in [colorRate, colorRate + this]. 0 means no spread; 92% of blocks leave it at 0.",
        "ZH": 'colorRate 的随机量 —— 实际取值落在 [colorRate, colorRate + 本值] 之间。0 = 不随机，约 92% 使用 0。',
    },
    ("MESH", "emissiveColorRate"): {
        "EN": "Intensity coefficient for the emissive channel (the `emissiveColor` / `emissiveColorRange` pair). Neutral value is 0 and 92% of blocks leave it there — it only does anything once non-zero. Every block with useEmissiveColorRange on has it non-zero. Driven by the EmissiveColorRate timeline parameter on the A1 (lifetime) axis.",
        "ZH": '自发光通道（`emissiveColor` / `emissiveColorRange`）的强度系数。中性值是 0，约 92% 使用 0；只有非 0 才起作用。启用 useEmissiveColorRange 时通常为非 0。对应 EmissiveColorRate 时间线参数，走 A1（寿命轴）。',
    },
    ("MESH", "emissiveColorRateJitter"): {
        "EN": "Random spread for emissiveColorRate — the actual value lands somewhere in [emissiveColorRate, emissiveColorRate + this]. 98% of blocks leave it at 0.",
        "ZH": 'emissiveColorRate 的随机量 —— 实际取值落在 [emissiveColorRate, emissiveColorRate + 本值] 之间。约 98% 使用 0。',
    },
    ("MESH", "epv_color_slot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("MESH", "epv_color_slot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("MESH", "global_scale_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("MESH", "rotationOrder"): {
        "EN": "Order the rotation axes are applied in. ZXY is the usual choice (about 88%).",
        "ZH": "旋转各轴的应用顺序。常用 ZXY（约 88%）。",
    },
    ("MESH", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9]。",
    },
    ("MESH", "unknFixed0_1"): {
        "EN": "Always 167 usually — likely a fixed format/version "
              "marker rather than a tunable parameter.",
        "ZH": "恒为 167——很可能是固定的格式/版本标记，而非可调参数。",
    },
    ("MESH", "baseAxis"): {
        "EN": "Direction the mesh faces. Same AxisDirection6 enum as PLANE/VELOCITY3D "
              "(0=left,1=up,2=front,3=right,4=down,5=back); usually 2.",
        "ZH": "网格的朝向。与 PLANE/VELOCITY3D 同一套 AxisDirection6 枚举"
              "（0=左,1=上,2=前,3=右,4=下,5=后），通常为 2。",
    },
    ("MESH", "unknEnum5"): {
        "EN": "Common values: [0, 2, 6, 7].",
        "ZH": "常见取值为 [0, 2, 6, 7]。",
    },
    ("MESH", "unknFixed6_1"): {
        "EN": "Unknown. Usually 0.",
        "ZH": "作用未知。通常为 0。",
    },
    ("MESH", "unknEnum7_0"): {
        "EN": "Common values: [0, 1, 2, 3, 180, 4112].",
        "ZH": "常见取值为 [0, 1, 2, 3, 180, 4112]。",
    },
    ("MESH", "unknFlag7_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("NOISE", "lowFrequencyJitter"): {
        "EN": "Per-particle random offset applied to lowFrequency, so particles don't jitter in sync. Common range: 0~100.",
        "ZH": "对 lowFrequency 施加的逐粒子随机偏移，避免多个粒子的抖动同步。常见取值在 0~100 之间。",
    },
    ("NOISE", "highFrequencyJitter"): {
        "EN": "Per-particle random offset applied to highFrequency, so particles don't jitter in sync. Common range: 0~100.",
        "ZH": "对 highFrequency 施加的逐粒子随机偏移，避免多个粒子的抖动同步。常见取值在 0~100 之间。",
    },
    ("NOISE", "lowFrequencyWidthJitter"): {
        "EN": "Per-particle random offset applied to lowFrequencyWidth, so particles don't jitter by the same amount.",
        "ZH": "对 lowFrequencyWidth 施加的逐粒子随机偏移，避免多个粒子的抖动幅度完全一致。",
    },
    ("NOISE", "highFrequencyWidthJitter"): {
        "EN": "Per-particle random offset applied to highFrequencyWidth, so particles don't jitter by the same amount.",
        "ZH": "对 highFrequencyWidth 施加的逐粒子随机偏移，避免多个粒子的抖动幅度完全一致。",
    },
    ("NOISE", "section_length"): {
        "EN": "Common values: [0, 36].",
        "ZH": "常见取值为 [0, 36]。",
    },
    ("OTOMOSNOW", "unkn7_1"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("OTOMOSNOW", "unkn7_3"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("OTOMOSNOW", "unkn7_4"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("OTOMOSNOW", "unkn7_7"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTEMISSIVE", "blend"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTEMISSIVE", "correctColorNo"): {
        "EN": "Common values: [0, 1, 2, 9].",
        "ZH": "常见取值为 [0, 1, 2, 9]。",
    },
    ("PARENTEMISSIVE", "emitMaskFlags"): {
        "EN": "Emit-mask related toggles (4 bits used); bit0 and bit3 have no known effect.",
        "ZH": "发光遮罩相关的开关组合（用到 4 位）；bit0 和 bit3 没有已知作用。",
    },
    ("PARENTEMISSIVE", "addMask0"): {
        "EN": "May be a secondary (\"Add\") emit-mask threshold; exact purpose unknown. "
              "Common range: 0~100.",
        "ZH": "可能是次级（\"Add\"）发光遮罩阈值；具体作用未知。常见取值在 0~100 之间。",
    },
    ("PARENTEMISSIVE", "addMask1"): {
        "EN": "May be a secondary (\"Add\") emit-mask threshold; exact purpose unknown. "
              "Common range: 0~1.",
        "ZH": "可能是次级（\"Add\"）发光遮罩阈值；具体作用未知。常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_10"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_12"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PARENTSNOW", "unkn4_2"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_3"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_5"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unknFlag4_6"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("PARENTSNOW", "unkn4_7"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_8"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTSNOW", "unkn4_9"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PATHCHAIN", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[0, 1, 2, 3, 4, 5, 7, 17].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[0, 1, 2, 3, 4, 5, 7, 17]。",
    },
    ("PATHCHAIN", "unkn4"): {
        "EN": "Unknown; one static/random pair per axis. Common values: X 0.3~4, Y 0.5~1, "
              "Z 0.02~0.3; random amounts are usually 0.",
        "ZH": "作用未知；每轴一组固定值 + 随机量。常见取值：X 0.3～4、Y 0.5～1、Z 0.02～0.3；"
              "随机量通常为 0。",
    },
    ("PATHCHAIN", "unknEnum5_7"): {
        "EN": "Common values: [2, 4].",
        "ZH": "常见取值为 [2, 4]。",
    },
    ("PLANE", "correctColorNo"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("PLANE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common range: 1~13 (rare outliers up to 41).",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见范围 "
              "1~13（个别情况可达 41）。",
    },
    ("PLANE", "rotation2"): {
        "EN": "Plane's rotation around its own perpendicular axis (spin), independent from "
              "the XYZ orientation above.",
        "ZH": "平面沿自身垂线的旋转（自旋），与上面的 XYZ 朝向字段独立。",
    },
    ("PLANE", "rotation2Jitter"): {
        "EN": "Random jitter added to rotation2 each time the effect plays.",
        "ZH": "rotation2 的随机抖动范围，每次播放特效时随机浮动。",
    },
    ("PLANE", "heightJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLANE", "brightnessJitter"): {
        "EN": "Jitter paired with brightness. Exact behavior on PLANE unknown.",
        "ZH": "与亮度配对的抖动量。在 PLANE 上的具体行为未知。",
    },
    ("PLANE", "divideNum"): {
        "EN": "Common values: [0, 1, 2, 3, 4, 6].",
        "ZH": "常见取值为 [0, 1, 2, 3, 4, 6]。",
    },
    ("PLANE", "unknEnum5_1"): {
        "EN": 'Bitmask (bit0 = master toggle, bits 1/2 sub-modes only meaningful when bit0 is on; non-zero values usually are always odd, e.g. 1/3/5/7). Related to orientation relative to the camera; per-bit meaning unknown.',
        "ZH": '位掩码（bit0 为总开关，bit1/bit2 是仅在 bit0 开启时才有意义的子模式；非零值恒为奇数，如 1/3/5/7）。与朝向-摄像机的关系有关，各 bit 具体含义未知。',
    },
    ("PLANE", "baseAxis"): {
        "EN": "Same AxisDirection6 enum as VELOCITY3D/FADEBYANGLE (0=left,1=up,2=front,3=right,"
              "4=down,5=back).",
        "ZH": "与 VELOCITY3D/FADEBYANGLE 同一套 AxisDirection6 枚举（0=左,1=上,2=前,3=右,4=下,5=后）。",
    },
    ("PLANE", "rotationOrder"): {
        "EN": "Same rotation-order enum as MESH.rotationOrder (0=XYZ,1=YZX,2=YXZ,3=ZYX,4=ZXY,"
              "5=XZY); overwhelmingly 4(ZXY) usually, same shape as MESH.rotationOrder.",
        "ZH": "与 MESH.rotationOrder 同一套旋转顺序枚举（0=XYZ,1=YZX,2=YXZ,3=ZYX,4=ZXY,5=XZY）；"
              "压倒性取值 4(ZXY)，与 MESH.rotationOrder 分布形状一致。",
    },
    ("PLANE", "lightGroup"): {
        "EN": 'Packed flags edited via the popup: which light groups this plane reacts to (same table as BILLBOARD3D/MESH/RIBBON).',
        "ZH": '打包标志，用弹窗编辑：这个 Plane 对哪些光照组作出反应（与 BILLBOARD3D/MESH/RIBBON 共用同一张表）。',
    },
    ("PLANE", "unknFlag7_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("PLANE", "widthJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLEMISSIVE", "enableUseEmitMask"): {
        "EN": "Master switch for the emit mask. 0 = mask0/mask1 stay at their default; 1 = they take the customized values.",
        "ZH": "发光遮罩功能的总开关。为 0 时 mask0/mask1 保持默认值；为 1 时使用自定义的数值。",
    },
    ("PLEMISSIVE", "blend"): {
        "EN": "Blend factor. Can be animated via a TIML track.",
        "ZH": "混合系数。可通过 TIML 轨道做动画。",
    },
    ("PLEMISSIVE", "addMask0"): {
        "EN": "May be a secondary (\"Add\") emit-mask threshold; exact purpose unknown.",
        "ZH": "可能是次级（\"Add\"）发光遮罩阈值；具体作用未知。",
    },
    ("PLEMISSIVE", "addMask1"): {
        "EN": "May be a secondary (\"Add\") emit-mask threshold; exact purpose unknown.",
        "ZH": "可能是次级（\"Add\"）发光遮罩阈值；具体作用未知。",
    },
    ("PTBEHAVIOR", "behav_type_len"): {
        "EN": "Common values: [20, 21, 28, 31, 34].",
        "ZH": "常见取值为 [20, 21, 28, 31, 34]。",
    },
    ("PTCOLLISION", "unknEnum04"): {
        "EN": "Common values: [0, 1, 10, 15].",
        "ZH": "常见取值为 [0, 1, 10, 15]。",
    },
    ("PTCOLLISION", "unkn1_1"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PTCOLLISION", "unkn1_2"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PTCOLLISION", "unkn34"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PTCOLLISION", "unkn35"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PTCOLLISION", "unkn36"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PTCOLLISION", "unkn37"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PTCOLLISION", "unknEnum6_0"): {
        "EN": "Common values: [0, 2, 3, 4, 5].",
        "ZH": "常见取值为 [0, 2, 3, 4, 5]。",
    },
    ("PTCOLLISION", "unknEnum6_1"): {
        "EN": "Common values: [0, 1, 2, 7, 40, 50, 1000].",
        "ZH": "常见取值为 [0, 1, 2, 7, 40, 50, 1000]。",
    },
    ("PTLIFE", "unknEnum3"): {
        "EN": "Common values: [0, 2, 3, 4, 5].",
        "ZH": "常见取值为 [0, 2, 3, 4, 5]。",
    },
    ("PTLIFE", "unknFixed1"): {
        "EN": "Fixed at 0.",
        "ZH": "固定为 0。",
    },
    ("PTLIFE", "useRelation"): {
        "EN": "Whether the Relation Play link takes effect. When Disabled, the linked Action "
              "is not triggered.",
        "ZH": "关联 Play 是否生效。停用时不会触发关联的 Action。",
    },
    ("PTLIFE", "unknFrame0"): {
        "EN": "Unknown; likely a frame count. Common values: 0, 10, 30, 60, 90. Paired with unknFrame0Jitter as a static/random pair.",
        "ZH": "作用未知，可能是帧数。常见取值 0、10、30、60、90。与 unknFrame0Jitter 组成 static/random 一对。",
    },
    ("PTLIFE", "unknFrame1"): {
        "EN": "Unknown. Almost always 0. Paired with unknFrame1Jitter as a static/random pair.",
        "ZH": "作用未知。几乎恒为 0。与 unknFrame1Jitter 组成 static/random 一对。",
    },
    ("PTTRIGGER", "unknEnum2"): {
        "EN": "Common values: [1, 2, 4, 8].",
        "ZH": "常见取值为 [1, 2, 4, 8]。",
    },
    ("RAYCAST", "rayCastAttr"): {
        "EN": "Common values: [-4, -3, -2, -1].",
        "ZH": "常见取值为 [-4, -3, -2, -1]。",
    },
    ("REFRACTION", "distortionType"): {
        "EN": "How the background behind the particle is distorted along the flowmap. "
              "Light Refraction shifts it slightly, Refraction shifts it about six times "
              "as far, Directional Blur smears it along the flow. Needs the renderer's "
              "flowmap enabled.",
        "ZH": "背后画面沿流动贴图方向的畸变方式。轻度折射小幅平移，折射平移约为其 6 倍，"
              "方向模糊沿流向拖影。需开启渲染体的流动贴图。",
    },
    ("REFRACTION", "alphaBlend"): {
        "EN": "Blends the undistorted background back into the distorted one; at 1 both show "
              "about equally. No effect on Directional Blur. Common values 0~0.5.",
        "ZH": "把未畸变的背景按比例混回畸变结果，取 1 时两者大致各占一半。对方向模糊无效。"
              "常见取值 0～0.5。",
    },
    ("REPEATAREA", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [0, 1, 2, 3, 4, 7, 10].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[0, 1, 2, 3, 4, 7, 10]。",
    },
    ("REPEATAREA", "unknEnum4"): {
        "EN": "Common values: [1, 2, 5, 7].",
        "ZH": "常见取值为 [1, 2, 5, 7]。",
    },
    ("RGBFIRE", "lerpAlphaToBlue"): {
        "EN": "Switches which texture channels drive the smoke layer. 0 = smoke shape from Red, coverage from Alpha; 1 = both from Blue, Red and Alpha no longer matter. The fire layer (Green) always stays opaque.",
        "ZH": "切换烟雾层取自贴图的哪个通道。0 = 烟雾形状取 R、覆盖范围取 Alpha；1 = 两者都改取 B，R 与 Alpha 不再起作用。火焰层（G）所在处始终不透明。",
    },
    ("RGBWATER", "specularColorParam_keepFrameJitter"): {
        "EN": "Common values: [0, 5, 10, 14, 30, 40, 62].",
        "ZH": "常见取值为 [0, 5, 10, 14, 30, 40, 62]。",
    },
    ("RGBWATER", "sheetColorParam_correctColorNo"): {
        "EN": "EPV colour slot id, same mechanism as BILLBOARD3D correctColorNo: 0 = use the local sheet colour; non-zero = take it from that slot in the calling .epv instead. Common values: [0, 1, 2, 6, 7, 8].",
        "ZH": "EPV 颜色槽位 id，跟 BILLBOARD3D 的 correctColorNo 是同一机制：0 = 用本地水膜色；非 0 = 改用调用方 .epv 对应槽位的颜色。常见取值为 [0, 1, 2, 6, 7, 8]。",
    },
    ("RGBWATER", "waterLerpParam_appearFrameJitter"): {
        "EN": "Common values: [0, 5].",
        "ZH": "常见取值为 [0, 5]。",
    },
    ("RGBWATER", "specularColorParam_vanishFrameJitter"): {
        "EN": "Common values: [0, 5, 10, 14, 20, 24, 25, 30].",
        "ZH": "常见取值为 [0, 5, 10, 14, 20, 24, 25, 30]。",
    },
    ("RGBWATER", "specularColorParam_lifeType"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "specularColorParam_correctColorNo"): {
        "EN": "EPV colour slot id, same mechanism as BILLBOARD3D correctColorNo: 0 = use the local specular colour; non-zero = take it from that slot in the calling .epv instead. Common values: [0, 2].",
        "ZH": "EPV 颜色槽位 id，跟 BILLBOARD3D 的 correctColorNo 是同一机制：0 = 用本地高光色；非 0 = 改用调用方 .epv 对应槽位的颜色。常见取值为 [0, 2]。",
    },
    ("RGBWATER", "sheetColorParam_appearFrame"): {
        "EN": "Common values: [0, 5, 10, 15, 25, 40, 50, 60].",
        "ZH": "常见取值为 [0, 5, 10, 15, 25, 40, 50, 60]。",
    },
    ("RGBWATER", "sheetColorParam_appearFrameJitter"): {
        "EN": "Common values: [0, 25].",
        "ZH": "常见取值为 [0, 25]。",
    },
    ("RGBWATER", "specularColorParam_appearFrame"): {
        "EN": "Common values: [0, 10, 16, 20, 25, 30, 60].",
        "ZH": "常见取值为 [0, 10, 16, 20, 25, 30, 60]。",
    },
    ("RGBWATER", "specularColorParam_appearFrameJitter"): {
        "EN": "Common values: [0, 16].",
        "ZH": "常见取值为 [0, 16]。",
    },
    ("RIBBON", "flap1Amount"): {
        "EN": "How far the flag swings. Stacks additively with the flap2 group, which has the same effect.",
        "ZH": "旗帜摆动的幅度。与效果相同的抖动2组叠加生效。",
    },
    ("RIBBON", "flap1AmountJitter"): {
        "EN": "Jitter paired with flap1Amount.",
        "ZH": "与抖动1幅度配对的抖动量。",
    },
    ("RIBBON", "flap1Frequency"): {
        "EN": "How fast the flag oscillates back and forth. Stacks additively with the flap2 group, which has the same effect.",
        "ZH": "旗帜来回摆动的快慢。与效果相同的抖动2组叠加生效。",
    },
    ("RIBBON", "flap1FrequencyJitter"): {
        "EN": "Jitter paired with flap1Frequency.",
        "ZH": "与抖动1频率配对的抖动量。",
    },
    ("RIBBON", "base_opacity"): {
        "EN": "Opacity right at the rear end (away from the direction of travel). This is an "
              "endpoint value, not a value for the whole ribbon — the middle stays fully "
              "opaque and only the rear fades toward this value, over the span set by "
              "Rear Fade Length. 1 leaves the rear edge hard.",
        "ZH": "后端（远离前进方向的一端）**端点处**的不透明度。它只管端点，不是整条带子的"
              "不透明度——中间始终是实心的，只有后端在「后端渐隐长度」那一段里渐变到这个值。"
              "为 1 则后端是硬边、不渐隐。",
    },
    ("RIBBON", "base_width_multiplier"): {
        "EN": "Width multiplier at the rear end (away from the direction of travel).",
        "ZH": "后端（远离前进方向的一端）的宽度乘数。",
    },
    ("RIBBON", "inertia"): {
        "EN": "Segment inertia for Ribbon Chain. Higher values hold the extended shape more "
              "stiffly and keep it oscillating longer; lowering it settles the ribbon faster "
              "without visible bouncing.",
        "ZH": "柔体链的分段惯性。数值越高，越能撑住伸展开的形状、振荡持续得越久；调低则更快"
              "归位、看不到明显弹跳。",
    },
    ("RIBBON", "inertiaJitter"): {
        "EN": "Jitter paired with inertia.",
        "ZH": "与惯性配对的抖动量。",
    },
    ("RIBBON", "lengthwise_offset_relative_to_camera"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "uvScaleLengthJitter"): {
        "EN": "Random range added to the length-direction texture scale.",
        "ZH": "长度方向贴图缩放的随机范围。",
    },
    ("RIBBON", "restoreStrength"): {
        "EN": "How strongly Ribbon Chain pulls back toward a straight shape. At 0 there is no "
              "pull at all and the ribbon behaves much like Ribbon Follow; raising it makes "
              "the ribbon straighten out.",
        "ZH": "柔体链回归平直形态的力度。为 0 时完全没有回复力，表现与轨迹跟随高度相似；"
              "调高则会让条带逐渐归位为平直。",
    },
    ("RIBBON", "restoreStrengthJitter"): {
        "EN": "Jitter paired with restoreStrength.",
        "ZH": "与归位强度配对的抖动量。",
    },
    ("RIBBON", "scale_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("RIBBON", "springiness"): {
        "EN": "Spring stiffness for Ribbon Chain. Raising it adds bouncy, jelly-like "
              "oscillation; combined with high inertia the ribbon can keep bouncing without "
              "ever settling.",
        "ZH": "柔体链的弹簧刚度。调高会带来果冻般的弹跳振荡；与高惯性组合时条带可能一直弹、"
              "永不归位。",
    },
    ("RIBBON", "springiness_jitter"): {
        "EN": "Jitter paired with springiness.",
        "ZH": "与弹性配对的抖动量。",
    },
    ("RIBBON", "flap2Amount"): {
        "EN": "How far the flag swings. Same effect as the flap1 group; the two stack additively.",
        "ZH": "旗帜摆动的幅度。与抖动1组效果相同，两组叠加生效。",
    },
    ("RIBBON", "flap2AmountJitter"): {
        "EN": "Jitter paired with flap2Amount.",
        "ZH": "与抖动2幅度配对的抖动量。",
    },
    ("RIBBON", "flap2Frequency"): {
        "EN": "How fast the flag oscillates back and forth. Same effect as the flap1 group; the two stack additively.",
        "ZH": "旗帜来回摆动的快慢。与抖动1组效果相同，两组叠加生效。",
    },
    ("RIBBON", "flap2FrequencyJitter"): {
        "EN": "Jitter paired with flap2Frequency.",
        "ZH": "与抖动2频率配对的抖动量。",
    },
    ("RIBBON", "tip_opacity"): {
        "EN": "Opacity right at the front end (in the direction of travel). This is an "
              "endpoint value, not a value for the whole ribbon — the middle stays fully "
              "opaque and only the front fades toward this value, over the span set by "
              "Front Fade Length. 1 leaves the front edge hard.",
        "ZH": "前端（前进方向的一端）**端点处**的不透明度。它只管端点，不是整条带子的"
              "不透明度——中间始终是实心的，只有前端在「前端渐隐长度」那一段里渐变到这个值。"
              "为 1 则前端是硬边、不渐隐。",
    },
    ("RIBBON", "tip_width_multiplier"): {
        "EN": "Width multiplier at the front end (in the direction of travel).",
        "ZH": "前端（前进方向的一端）的宽度乘数。",
    },
    ("RIBBON", "unknFlag16_0_1"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "unknFixed16_1_lo"): {
        "EN": "Fixed at 1. Purpose unknown.",
        "ZH": "固定为 1。作用未知。",
    },
    ("RIBBON", "unknBool16_1"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "rotationOrder"): {
        "EN": "Order the rotation axes are applied in.",
        "ZH": "旋转各轴的应用顺序。",
    },
    ("RIBBON", "rotationX"): {
        "EN": "One of three static rotation components, composed via rotationOrder and baseAxis. Which physical axis it maps to is unknown — the ribbon's forced camera-facing behavior makes this hard to observe.",
        "ZH": '三个静态旋转分量之一，与旋转顺序、基准轴复合作用。具体对应哪个物理轴未知——条带强制朝向相机的行为让这一点难以观察。',
    },
    ("RIBBON", "rotationXJitter"): {
        "EN": "Jitter paired with rotationX.",
        "ZH": "与 rotationX 配对的抖动量。",
    },
    ("RIBBON", "rotationY"): {
        "EN": 'One of three static rotation components. Which physical axis it maps to is unknown.',
        "ZH": "三个静态旋转分量之一。具体对应哪个物理轴未知。",
    },
    ("RIBBON", "rotationYJitter"): {
        "EN": "Jitter paired with rotationY.",
        "ZH": "与 rotationY 配对的抖动量。",
    },
    ("RIBBON", "rotationZ"): {
        "EN": 'One of three static rotation components. Which physical axis it maps to is unknown.',
        "ZH": "三个静态旋转分量之一。具体对应哪个物理轴未知。",
    },
    ("RIBBON", "rotationZJitter"): {
        "EN": "Jitter paired with rotationZ.",
        "ZH": "与 rotationZ 配对的抖动量。",
    },
    ("RIBBON", "unkn21"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "unkn22_0"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "lightGroup"): {
        "EN": 'Packed flags edited via the popup: which light groups this ribbon reacts to (same table as BILLBOARD3D/MESH/PLANE).',
        "ZH": '打包标志，用弹窗编辑：这个 Ribbon 对哪些光照组作出反应（与 BILLBOARD3D/MESH/PLANE 共用同一张表）。',
    },
    ("RIBBON", "unknFlag22_2"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "base_fade_length"): {
        "EN": "How far the rear fade reaches, as a fraction of the ribbon's total length. "
              "The rear end sits at Rear Opacity and climbs back to fully opaque across this "
              "span; 0 makes the rear edge a hard cut. Common range: 0~1, most often 0.3. "
              "Only used when Enable Fade Length is on; otherwise it counts as 1.",
        "ZH": "后端的渐隐延伸多长，按条带全长的比例算。端点处是「后端不透明度」，在这段"
              "长度里回到完全不透明；为 0 则后端是硬边。常见取值在 0~1 之间，多数为 0.3。"
              "仅在「启用渐隐长度」开启时生效，否则按 1 计。",
    },
    ("RIBBON", "tip_fade_length"): {
        "EN": "How far the front fade reaches, as a fraction of the ribbon's total length. "
              "The front end sits at Front Opacity and climbs back to fully opaque across "
              "this span; 0 makes the front edge a hard cut. Common range: 0~1, most often 0.4. "
              "Only used when Enable Fade Length is on; otherwise it counts as 1.",
        "ZH": "前端的渐隐延伸多长，按条带全长的比例算。端点处是「前端不透明度」，在这段"
              "长度里回到完全不透明；为 0 则前端是硬边。常见取值在 0~1 之间，多数为 0.4。"
              "仅在「启用渐隐长度」开启时生效，否则按 1 计。",
    },
    ("RIBBON", "spawnAnchorOffset"): {
        "EN": "Where the spawn point sits along the ribbon. 1: the ribbon grows out of the "
              "spawn point; 0.5: the spawn point is in the middle; 0: the whole ribbon lies on "
              "the other side. No effect in Trail mode. Common values 1 and 0.5.",
        "ZH": "生成点在条带上的位置。1：条带从生成点伸出；0.5：生成点在条带正中；0：整条落在"
              "生成点另一侧。轨迹跟随模式下无效。常见值 1、0.5。",
    },
    ("RIBBON", "uvScaleWidth"): {
        "EN": "Texture scale across the width, centred on the ribbon's middle line. 2 squeezes "
              "the whole texture into the middle half and stretches the edge pixels out to "
              "both sides; 0.5 shows only the middle half of the texture across the full width.",
        "ZH": "宽度方向的贴图缩放，以条带中线为基准。2 时整张贴图压到中间一半，两侧拉伸边缘像素；"
              "0.5 时只显示贴图中间一半并铺满整个宽度。",
    },
    ("RIBBON", "useTrailTimeScale"): {
        "EN": "Ribbon Follow only. When on, the stretch of motion history each segment covers "
              "is scaled by Trail Time Scale, so the ribbon's length depends on both that value "
              "and the subdivision count. When off, each segment covers one frame.",
        "ZH": "仅轨迹跟随模式有效。开启后每一段覆盖的轨迹时长按「条带时间缩放」缩放，条带长度由该值"
              "与细分数共同决定；关闭时每段对应一帧。",
    },
    ("RIBBON", "trailTimeScale"): {
        "EN": "Scales how much motion history each segment covers: larger values make the "
              "ribbon longer, smaller values shorter. At 0 or below the ribbon collapses into a "
              "straight line from the spawn point to the particle's current position.",
        "ZH": "每段覆盖的轨迹时长的缩放：值越大条带越长，越小越短。0 及负值时条带退化为从生成点直线"
              "连到粒子当前位置。",
    },
    ("RIBBONBLADE", "widthDirection"): {
        "EN": "Direction the blade extends from the trail; fixed and does not turn with the "
              "motion. 0=Left, 1=Up, 2=Front, 3=Right, 4=Down, 5=Back.",
        "ZH": "刀身从轨迹伸出的方向，固定不随运动方向转动。0=左、1=上、2=前、3=右、4=下、"
              "5=后。",
    },
    ("RIBBONBLADE", "length"): {
        "EN": "The trail covers the last (this value + 1) frames of movement. Only used when "
              "Distance-Based Length is off. Right after spawning, the part before the spawn "
              "point is not shown.",
        "ZH": "刀光覆盖最近（此值 + 1）帧的移动轨迹，仅在关闭「按距离计算长度」时生效。刚生成时，"
              "生成点之前的部分不显示。",
    },
    ("RIBBONBLADE", "interpolationCount"): {
        "EN": "Extra points inserted along a smooth curve between every two frames of the "
              "trail. 0 draws straight segments, so fast swings look polygonal; higher values "
              "round them off. Common values are 2–4, 20 for very smooth trails.",
        "ZH": "在拖尾每两帧之间沿平滑曲线补的点数。0 时为逐帧直线段，快速挥动会呈多边形；数值越大越圆滑。"
              "常见取值为 2～4，要求极平滑时用 20。",
    },
    ("RIBBONBLADE", "unknFlag07_0"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RIBBONBLADE", "lengthMode"): {
        "EN": "On: the trail grows with the distance moved, limited by Max Length Limit and shrunk "
              "by Contraction Speed; Trail Frames is ignored. Off: the trail keeps the last "
              "Trail Frames of movement.",
        "ZH": "开启：刀光随移动距离变长，受最大长度限制并按回缩速度缩短，拖尾帧数不生效。"
              "关闭：刀光保留最近拖尾帧数的轨迹。",
    },
    ("RIBBONBLADE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 4].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 4]。",
    },
    ("RIBBONBLADE", "unknFlag12_0"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RIBBONBLADE", "unknFlag12_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RIBBONBLADE", "uvRepetition"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("ROTATEANIM", "billboardRotationCoef"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("ROTATEANIM", "billboardRotationCoefJitter"): {
        "EN": "Random component of billboardRotationAccel.",
        "ZH": "billboardRotationAccel 的随机分量。",
    },
    ("ROTATEANIM", "spinSpeedCoefX"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("ROTATEANIM", "spinSpeedCoefXJitter"): {
        "EN": "Random component of spinAccelerationX. Mostly 0; occasionally a clean small decimal.",
        "ZH": "spinAccelerationX 的随机分量。多为 0；偶尔是干净的小数。",
    },
    ("ROTATEANIM", "spinSpeedCoefY"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("ROTATEANIM", "spinSpeedCoefYJitter"): {
        "EN": "Random component of spinAccelerationY.",
        "ZH": "spinAccelerationY 的随机分量。",
    },
    ("ROTATEANIM", "spinSpeedCoefZ"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("ROTATEANIM", "spinSpeedCoefZJitter"): {
        "EN": "Random component of spinAccelerationZ.",
        "ZH": "spinAccelerationZ 的随机分量。",
    },
    ("ROTATEANIM", "rotateDelayStart"): {
        "EN": "Likely the fixed delay, in frames, before rotation starts. Common values: 5/10/15/20/30/100/512.",
        "ZH": "可能是旋转开始前的固定延迟帧数。常见取值为 5/10/15/20/30/100/512。",
    },
    ("ROTATEANIM", "rotateDelayStartJitter"): {
        "EN": "Random variation of rotateDelayStart; usually 0. Other common "
              "values: [1, 2, 5, 10, 15, 20, 30, 60, 128].",
        "ZH": "rotateDelayStart 的随机分量；通常为 0；其余常见取值为 "
              "[1, 2, 5, 10, 15, 20, 30, 60, 128]。",
    },
    ("SCALEANIM", "sizeScalarAddCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "sizeXAddCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "sizeYAddCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "sizeXAddJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "sizeYAddJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("SCALEANIM", "sizeZAddJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCREENSPACECOLLISION", "bounce"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCREENSPACECOLLISION", "bounceJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 10, 11, 12].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 10, 11, 12]。",
    },
    ("SHADERSETTINGS", "section_length"): {
        "EN": "Fixed at 104 — do not modify",
        "ZH": "固定为 104，请勿修改。",
    },
    ("SHADERSETTINGS", "versionRelated"): {
        "EN": "Separates effects made before and after the game's release: files for "
              "effects added later have 1 throughout.",
        "ZH": "区分本体发售前后，后来新增的特效整文件此值全取1。",
    },
    ("SHADERSETTINGS", "particleLighting"): {
        "EN": "How scene light and shadow affect the particle. Unlit: ignores lighting. "
              "Per Particle: the whole particle brightens or darkens together, starting about "
              "0.2 s after the change and easing over about 1 s. Per Pixel: updates instantly, "
              "and a shadow edge can cross the particle. Fire, glow and sparks usually use "
              "Unlit; smoke and water usually use Per Particle.",
        "ZH": "场景光照与阴影如何作用于粒子。不受光：忽略光照。逐粒子：整个粒子一起明暗变化，"
              "变化后约 0.2 秒开始、约 1 秒过渡完。逐像素：即时生效，阴影边缘可以落在粒子中间。"
              "火、光、火花通常不受光，烟和水通常逐粒子。",
    },
    ("SHADERSETTINGS", "reflectance"): {
        "EN": "Scales how much direct light the particle reflects. 0 leaves it almost unlit in "
              "sunlight; ambient light is unaffected. Default 1.",
        "ZH": "粒子反射直射光的比例。为 0 时在阳光下几乎不亮，环境光不受影响。默认 1。",
    },
    ("SHADERSETTINGS", "transmittance"): {
        "EN": "How much light passes through the particle; lower values make lit particles slightly "
              "darker. Common values: Static 1, or Static 0.1 with Random 0.9.",
        "ZH": "光线透过粒子的程度，越小受光时越暗。常见取值：固定 1，或固定 0.1、随机 0.9。",
    },
    ("SHADERSETTINGS", "transmittanceJitter"): {
        "EN": "Random amount added to Transmittance per particle. Static plus Random is usually no more "
              "than 1.",
        "ZH": "每个粒子在透光率上叠加的随机量。固定与随机之和通常不超过 1。",
    },
    ("SHADERSETTINGS", "envLightFactor"): {
        "EN": "Strength of ambient (sky) light on the particle. 0 turns it black in shade while sunlit "
              "areas stay normal. Default 1.",
        "ZH": "环境光（天空光）的强度。为 0 时阴影中全黑，阳光下正常。默认 1。",
    },
    ("SHADERSETTINGS", "envSaturation"): {
        "EN": "Colour saturation of the ambient light. 0 removes its tint, such as the blue of "
              "skylight, without changing brightness. Default 1.",
        "ZH": "环境光的色彩饱和度。为 0 时去掉环境光的色调（如天空光的蓝色），亮度不变。默认 1。",
    },
    ("SHADERSETTINGS", "lightFactor"): {
        "EN": "Strength of direct light such as sunlight. 0 keeps the particle unlit even in sunlight. "
              "Default 1.",
        "ZH": "直射光（如阳光）的强度。为 0 时即使在阳光下也不亮。默认 1。",
    },
    ("SHADERSETTINGS", "shadowFactor"): {
        "EN": "How much shadows darken the particle. 0 ignores shadows, so it stays fully lit in shade. "
              "Default 1.",
        "ZH": "阴影使粒子变暗的程度。为 0 时忽略阴影，在阴影中也保持全亮。默认 1。",
    },
    ("SHADERSETTINGS", "unkn4_7"): {
        "EN": "Common values: [0, 15, 80, 100, 200, 250, 300, 500, 1000, 1200].",
        "ZH": "常见取值为 [0, 15, 80, 100, 200, 250, 300, 500, 1000, 1200]。",
    },
    ("SHADERSETTINGS", "presetId"): {
        "EN": "Lighting preset that bundles Reflectance, Light Factor, Shadow Factor, Env Light "
              "Factor and Env Saturation. Known presets: Default, Smoke, test02 (often water), "
              "test03 (debris), test04 (dirt), test05 (snow and ice), test06 (aura), Hit_test "
              "(blood). Pick one from the dropdown or type its name; leave empty for none.",
        "ZH": "打包反射率、直射光系数、阴影系数、环境光系数和环境光饱和度的光照预设。已知预设："
              "Default、Smoke、test02（常用于水）、test03（碎片）、test04（泥土）、test05（雪和冰）、"
              "test06（气场）、Hit_test（血）。可从下拉选择或输入名字，留空表示不使用预设。",
    },
    ("SHADERSETTINGS", "lightSamplingOffset"): {
        "EN": "Moves the point where lighting is sampled, in cm; Y is up. Raising it lets low particles "
              "such as ground smoke pick up light from above. Rotates with the emitter unless Light "
              "Sampling Rotate Fix is on. Usually 0.",
        "ZH": "光照取样点的偏移，单位 cm，Y 向上。抬高后贴地的烟等低处粒子能取到上方的光照。未开启「取样偏"
              "移不随旋转」时随发射器旋转。通常为 0。",
    },
    ("SHADERSETTINGS", "unknFixed4_12"): {
        "EN": "Fixed at 0.0. Purpose unknown.",
        "ZH": "固定为 0.0。具体作用未知。",
    },
    ("SHADERSETTINGS", "lightSamplingDistance"): {
        "EN": "Purpose unknown. Usually 0; often set to the same value as Light Sampling Offset Y (50, "
              "100, 150).",
        "ZH": "作用未知。通常为 0；常与光照取样偏移 Y 取相同的值（50、100、150）。",
    },
    ("SHADERSETTINGS", "drawTarget"): {
        "EN": "Where a 2D screen overlay layer is drawn. Screen: shown directly. Overlay "
              "buffers: not shown by themselves; used by other screen effects, such as "
              "raindrops distorting the view. Usually Screen.",
        "ZH": "2D 屏幕叠加层绘制到哪里。屏幕：直接显示。叠加层缓冲：本身不显示，供其他屏幕效果"
              "使用，例如雨滴扭曲画面。通常为屏幕。",
    },
    ("SHADERSETTINGS", "drawPriority"): {
        "EN": "Front-to-back order against other particles where they overlap. The higher "
              "value is drawn on top only when the two differ by more than 4096; otherwise "
              "the later Entry is on top. Usually 0.",
        "ZH": "与其他粒子重叠时的前后顺序。两者相差超过 4096 时数值大的在上面，否则按 Entry "
              "顺序，靠后的在上面。通常为 0。",
    },
    ("SHADERSETTINGS", "lightSamplingRotateFix"): {
        "EN": "When on, the light sampling offset ignores the emitter's rotation and keeps its world "
              "direction. When off, it rotates with the emitter.",
        "ZH": "开启后光照取样偏移不随发射器旋转，保持世界方向；关闭时随发射器旋转。",
    },
    ("SHADERSETTINGS", "unknFixed5_0_1"): {
        "EN": "Fixed at 0. Purpose unknown.",
        "ZH": "固定为 0。具体作用未知。",
    },
    ("SHADERSETTINGS", "unknFlag5_0_2"): {
        "EN": "Purpose unknown. Usually off.",
        "ZH": "作用未知。通常关闭。",
    },
    ("SHADERSETTINGS", "unknFlag5_0_3"): {
        "EN": "Purpose unknown. Usually off.",
        "ZH": "作用未知。通常关闭。",
    },
    ("SHADERSETTINGS", "unknBitmask5_1"): {
        "EN": "Common values: [0, 1, 2, 3, 4, 5, 7, 8, 9]; most commonly 0 or 1.",
        "ZH": "常见取值为 [0, 1, 2, 3, 4, 5, 7, 8, 9]；最常见为 0 或 1。",
    },
    ("SPAWN", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[2, 3, 4, 5, 6, 7, 8, 9, 10]; overwhelmingly 2.",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[2, 3, 4, 5, 6, 7, 8, 9, 10]；绝大多数为 2。",
    },
    ("SPAWN", "particleDelayFrame"): {
        "EN": "Delay before each particle appears after its burst fires, rolled per particle. "
              "Use with its random range to stagger particles from the same burst.",
        "ZH": "每个粒子在所属批次发出后，再等多少帧才出现，逐粒子独立抽取。配合随机量"
              "可以让同一批的粒子错开出现。",
    },
    ("SPAWN", "particleDelayFrameJitter"): {
        "EN": "Random range added to Particle Delay Frame, rolled per particle.",
        "ZH": "叠加到粒子延迟上的随机量，每个粒子独立抽取。",
    },
    ("SPAWN", "maxParticles"): {
        "EN": 'Soft cap on particles allowed alive at once for this spawner (concurrent count = burst rate × particle lifespan, i.e. Keep + Vanish). Not a lifetime total — bursts are throttled once this cap would be exceeded, and resume in full once earlier particles die off.',
        "ZH": '该发射器同时存活粒子数的软上限。不是终身生成总量——超出上限时本批会被削减，等早前粒子死亡腾出空间后又能满额生成。',
    },
    ("SPAWN", "spawnFlags"): {
        "EN": 'Packed flags edited via the popup: UseSpawnFrame / RingBufferMode / RayCastHitOnly / RayCastDependency / InitializeFull / Interpolate (all default off). The exact effect of InitializeFull / Interpolate is unknown.',
        "ZH": '打包标志，用弹窗编辑：UseSpawnFrame / RingBufferMode / RayCastHitOnly / RayCastDependency / InitializeFull / Interpolate（均默认关闭）。InitializeFull / Interpolate 的具体作用未知。',
    },
    ("SPAWN", "spawnFrame"): {
        "EN": "The emitter only spawns particles during its first N frames. Only applies when UseSpawnFrame is on in spawnFlags.",
        "ZH": "发射器只在开始后的前 N 帧内生成粒子。仅在 spawnFlags 的 UseSpawnFrame 开启时生效。",
    },
    ("SPAWNBYANGLE", "unknEnum3"): {
        "EN": "Common values: [1, 4].",
        "ZH": "常见取值为 [1, 4]。",
    },
    ("STRAINRIBBON", "breakDelay"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "breakDelayJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "breakpointLocation"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("STRAINRIBBON", "breakpointLocationJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("STRAINRIBBON", "gravityMultiplierJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "inertiaJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("STRAINRIBBON", "poseSnappingJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("STRAINRIBBON", "positionalAberration_01"): {
        "EN": "Common values: [0, 1, 8, 32, 33, 36].",
        "ZH": "常见取值为 [0, 1, 8, 32, 33, 36]。",
    },
    ("STRAINRIBBON", "positionalAberration_02"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("STRAINRIBBON", "spacer04"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "unknBool06_08_0"): {
        "EN": "Unknown. Usually 0.",
        "ZH": "作用未知。通常为 0。",
    },
    ("STRAINRIBBON", "unknBool06_08_1"): {
        "EN": "Unknown. Almost always 0.",
        "ZH": "作用未知。几乎恒为 0。",
    },
    ("STRAINRIBBON", "unknBool06_08_2"): {
        "EN": "Unknown. About 64% use 1.",
        "ZH": "作用未知。约 64% 取 1。",
    },
    ("STRAINRIBBON", "unknBool06_08_3"): {
        "EN": "Unknown. About 10% use 1.",
        "ZH": "作用未知。约 10% 取 1。",
    },
    ("STRAINRIBBON", "unkn09_3"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "unknEnum11"): {
        "EN": "Common values: [0, 2, 3, 6].",
        "ZH": "常见取值为 [0, 2, 3, 6]。",
    },
    ("STRAINRIBBON", "unknEnum12_00"): {
        "EN": "Common values: [0, 2, 3, 4, 5, 8, 10, 50].",
        "ZH": "常见取值为 [0, 2, 3, 4, 5, 8, 10, 50]。",
    },
    ("TRANSFORM2D", "scaleX"): {
        "EN": "Usually 1.0 (no scaling); occasionally 0.5 or 2.0.",
        "ZH": "通常为 1.0（不缩放）；偶见 0.5 或 2.0。",
    },
    ("TRANSFORM2D", "scaleY"): {
        "EN": "Usually 1.0 (no scaling); occasionally 0.5 or 2.0.",
        "ZH": "通常为 1.0（不缩放）；偶见 0.5 或 2.0。",
    },
    ("TUBELIGHT", "unknBool0_2"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("TUBELIGHT", "unkn2_0"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("TURBULENCE", "unkn1_0"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("TURBULENCE", "unknEnum1_1"): {
        "EN": "Common values: [0, 4].",
        "ZH": "常见取值为 [0, 4]。",
    },
    ("TURBULENCE", "unknFlag3_4"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("UVCONTROL", "uv2_enable"): {
        "EN": "Enables the second UV channel. A mod3 mesh may carry two UV sets; this switches on the uv2 group's own offset/scale/speed controls. (Not vertex-animation related.)",
        "ZH": '启用第二套 UV。mod3 网格允许同时存在两套 UV，打开后下面的 uv2 组（偏移/缩放/速度）才生效。（与顶点动画无关。）',
    },
    ("UVSEQUENCE", "playSpeedCoef"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("UVSEQUENCE", "playSpeedCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("UVSEQUENCE", "playSpeedJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("UVSEQUENCE", "loopingPad"): {
        "EN": "Padding byte, fixed at 0 (part of the loopingEnum "
              "byte layout, see playbackMode/flipCode/direction/loopingOrientation).",
        "ZH": "填充字节，固定为 0（属于 loopingEnum 的字节布局，参见 "
              "playbackMode/flipCode/direction/loopingOrientation）。",
    },
    ("UVSEQUENCE", "typeFlag"): {
        "EN": "Header field present in most attribute types, a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 5, 6, 7, 8, 9, 11, 13, 14].",
        "ZH": "大部分 attribute 都有的头部字段，是类型/分类标记，非可调参数。常见取值为 "
              "[1, 2, 5, 6, 7, 8, 9, 11, 13, 14]。",
    },
    ("UVSEQUENCE", "sequenceNoJitter"): {
        "EN": "Jitter added to the UVS file path index at spawn. Usually 0; other "
              "values are small integers 1~8.",
        "ZH": "生成时叠加到 UVS 文件路径索引上的抖动量。通常为 0；其余取值为 1~8 的小整数。",
    },
    ("VELOCITY2D", "velocityX"): {
        "EN": "Each particle's direction is computed per axis as "
              "V_i = (divergence_i - 1) x i0 + velocity_i, where i0 is that particle's own "
              "spawn coordinate on axis i, then normalized — only the direction is used, the "
              "speed comes from speed/acceleration. velocity is simply the common movement "
              "direction shared by all particles, regardless of where each one spawned. Values "
              "here are ~100x the scale of the spawn coordinates "
              "(EMITTERSHAPE2D.rangeX/Y units).",
        "ZH": "每个粒子的运动方向按下式逐轴算出：V_i =（divergence_i − 1）× i0 + velocity_i，"
              "其中 i0 是该粒子生成时在 i 轴上的坐标；算完再归一化——只取方向，速度大小由"
              "初速度/加速度决定。velocity 可以简单视作全体粒子共同的运动方向，与各自在哪"
              "生成无关。这里的数值量级约为生成坐标（EMITTERSHAPE2D.rangeX/Y 单位）的 100 倍。",
    },
    ("VELOCITY2D", "velocityY"): {
        "EN": "See velocityX.",
        "ZH": "见 velocityX。",
    },
    ("VELOCITY2D", "divergenceX"): {
        "EN": "Direction is computed per axis as V_i = (divergence_i - 1) x i0 + velocity_i, "
              "where i0 is that particle's own spawn coordinate on axis i. divergence is simply "
              "how strongly particles spread out from / collapse toward the center, scaled by "
              "where each one spawned: 1 = no effect on this axis; >1 = spreads outward; "
              "<1 = converges inward, passing through to the other side. Direction only — the "
              "magnitude does not change the speed.",
        "ZH": "运动方向按下式逐轴算出：V_i =（divergence_i − 1）× i0 + velocity_i，其中 i0 是"
              "该粒子生成时在 i 轴上的坐标。divergence 可以简单视作以生成位置为基础的发散/"
              "收拢强度：1=该轴无效果；>1 向外发散；<1 向内收拢（会穿过中心继续到对面）。"
              "只影响方向，数值大小不影响速度。",
    },
    ("VELOCITY2D", "divergenceY"): {
        "EN": "See divergenceX.",
        "ZH": "见 divergenceX。",
    },
    ("VELOCITY2D", "movementDelay"): {
        "EN": "Common values: [0, 1, 2, 5, 16, 20].",
        "ZH": "常见取值为 [0, 1, 2, 5, 16, 20]。",
    },
    ("VELOCITY2D", "movementDelayJitter"): {
        "EN": "Common values: [0, 1, 3, 4, 5, 10, 20].",
        "ZH": "常见取值为 [0, 1, 3, 4, 5, 10, 20]。",
    },
    ("VELOCITY2D", "speedCoef"): {
        "EN": "The speed is multiplied by this every frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次此值。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    ("VELOCITY2D", "speedCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("VELOCITY2D", "speedJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("VELOCITY2D", "gravityJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("VELOCITY3D", "minMovementThreshold"): {
        "EN": "Threshold for applying emitter motion to particles. Only relevant when velocityType=EmitterMotion: the emitter's velocity must exceed this value. Usually 0; non-zero values commonly range from 0~40.",
        "ZH": "将发射器运动施加给粒子的阈值。仅在 velocityType=EmitterMotion 时有意义：发射器速度需超过此值。通常为 0；非零时常见范围为 0~40。",
    },
    ("VELOCITY3D", "gravity_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },

    ("PLANE", "colorRangeCorrectColorNo"): {
        "EN": 'EPV colour slot id, same mechanism as correctColorNo. Exactly which attribute this targets is unknown; non-zero takes the attribute from that slot instead of the value here. 0 = use the local value.',
        "ZH": 'EPV 颜色槽位 id，机制同 correctColorNo。具体对应哪个属性未知；写非 0 就改用对应 id 槽位里的属性，顶掉本属性上的值；0 = 用本地值。',
    },
    ("PLEMISSIVE", "correctColorNo"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("PLSNOW", "epvcolorslot"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("RIBBON", "epvcolor_0"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("RIBBON", "epvcolor_1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. Non-zero here means: take the attribute from that slot instead of the value on this attribute. 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    # Flowmap 与法线贴图是不同输入，tooltip 只说明该区别。
    ("RGBWATER", "colorRate"): {
        "EN": "Overall colour rate, driven by the ColorRate timeline parameter — animating it only works on the A0 (emitter) axis.",
        "ZH": '整体颜色比率。对应 ColorRate 时间线参数，动画只在 A0（发射轴）上生效。',
    },
    ("RGBWATER", "waterLerpGtoB"): {
        "EN": "Blends the water colour from green towards blue, driven by WaterLerpGtoB. This parameter is often animated.",
        "ZH": '把水色从绿向蓝插值，对应 WaterLerpGtoB，也是本属性常用于动画的参数。',
    },
    ("RGBWATER", "intensitySheet"): {
        "EN": "Strength of the water-sheet layer, driven by IntensitySheet.",
        "ZH": '水膜层的强度。对应 IntensitySheet。',
    },
    ("RGBWATER", "colorSpecular"): {
        "EN": "Specular highlight colour, driven by ColorSpecular.",
        "ZH": '高光颜色。对应 ColorSpecular。',
    },
    ("RGBWATER", "colorSheet"): {
        "EN": "Water-sheet colour — the colour of the film itself, as opposed to the specular highlight.",
        "ZH": '水膜颜色——水膜本身的颜色，区别于高光颜色。',
    },
    ("RGBWATER", "intensityCubeMap"): {
        "EN": "Strength of the environment reflection taken from the cube map. Pairs with cubemapPath — it is non-zero in 78% of blocks that set a cube map versus 30% of those that don't.",
        "ZH": '取自立方贴图的环境反射强度。与 cubemapPath 配套：填了立方贴图的块里它 78% 非零，没填的只有 30%。',
    },
    ("RGBWATER", "intensitySpecular"): {
        "EN": "Strength of the specular highlight layer (colour comes from colorSpecular).",
        "ZH": '高光层的强度（颜色取自 colorSpecular）。',
    },
    ("RGBWATER", "intensityAlpha"): {
        "EN": "Overall transparency strength of the water surface.",
        "ZH": '水面的整体透明度强度。',
    },
    ("RGBWATER", "normalSharpness"): {
        "EN": "Sharpness of the normal map reconstructed from the R/G channels. Common value is 0.3. Unlike the other header floats, this one cannot be animated via a TIML track.",
        "ZH": '由 R/G 通道重建出的法线贴图的锐度。常见取值为 0.3。与其它头部 float 字段不同，这个字段不能通过 TIML 轨道做动画。',
    },
    ("UVSEQUENCE", "uvsPath"): {
        "EN": "Path to the .uvs sequence file — this is the artwork you actually see. The .uvs itself is a frame table pointing at a sprite-sheet .tex; playSpeed / patternNo pick which cell plays. Nearly every UVSEQUENCE has one (99% of blocks non-empty).",
        "ZH": '指向 .uvs 序列文件的路径 —— 真正显色的图就是这张。.uvs 本身是一张帧表，指向序列帧大图（.tex）；playSpeed / patternNo 决定放哪一格。通常需要填写。',
    },
    ("RGBWATER", "cubemapPath"): {
        "EN": "Cube map path for the water surface's environment reflection. Common paths include cm_cube_000_CM and cm_cube_001_CM. This is often left empty; pairs with intensityCubeMap.",
        "ZH": '水面环境反射用的立方贴图。常见路径包括 cm_cube_000_CM 和 cm_cube_001_CM，通常可留空；与 intensityCubeMap 配套使用。',
    },
    ("TURBULENCE", "tfaPath"): {
        "EN": "Path to the .tfa vector-field file that drives the turbulence. Common paths include cm_exMap\\turbulance_000_T and curlnoise_000_T. Usually required.",
        "ZH": '驱动湍流的 .tfa 向量场文件路径。常见路径包括 cm_exMap\\turbulance_000_T 和 curlnoise_000_T，通常需要填写。',
    },
    ("TUBELIGHT", "albedoPath"): {
        "EN": "Base-colour texture for the light column (*_BM.tex). Always filled.",
        "ZH": '光柱的基础色贴图（*_BM.tex）。总是填着的。',
    },
    ("TONEMAPFILTER", "lutPath"): {
        "EN": "Colour lookup table (*_LUTM) under light\\LUT\\ — the grading curve this filter applies to the screen.",
        "ZH": 'light\\LUT\\ 下的颜色查找表（*_LUTM）—— 本滤镜对画面应用的调色曲线。',
    },
    ("MESH", "mod3Path"): {
        "EN": "Path to the .mod3 model this attribute renders (game-relative, no extension). Import can pull the model in and bind it — see the mod3 link option in the N panel.",
        "ZH": '本属性渲染的 .mod3 模型路径（游戏内相对路径，不带扩展名）。导入时可以连模型一起拉进来并绑定 —— 见 N 面板的 mod3 联动开关。',
    },
    ("MESH", "plPath"): {
        "EN": "Optional .pl placement table: a list of (submesh index, XYZ offset) that shifts individual parts of the model. Rarely used (6% of blocks) and normally sits next to the .mod3 under the same name.",
        "ZH": '可选的 .pl 摆位表：一张（子网格序号, XYZ 偏移）列表，把模型的各个部件分别挪位。较少使用，通常与 .mod3 同目录同名。',
    },
    ("EMITTERSHAPEMESH", "mod3Path"): {
        "EN": "Path to the .mod3 whose surface is used as the emitter shape — particles spawn on this mesh rather than on a primitive.",
        "ZH": '用作发射器形状的 .mod3 路径 —— 粒子从这个网格表面上生成，而不是从基本体上。',
    },
    ("UVSEQUENCE", "patternNo"): {
        "EN": 'Starting frame of the sprite sheet (0 = top-left). Pair it with the Jitter field to randomise the start: an 8x8 sheet has 64 cells, so Jitter=63 picks any cell at spawn.',
        "ZH": '序列帧的起始帧（0 = 左上第一格）。配旁边的 Jitter 可让每个粒子随机起手：8×8 的图共 64 格，Jitter 给 63 就是全随机抽一格。',
    },
}

# ─── 流动贴图组（BILLBOARD3D / PLANE / BILLBOARD2D / RIBBON / STRAINRIBBON / LIGHTNING /
#     RIBBONBLADE / UVCONTROL 共用）────────────────────────────────────────────────
# 前三类的开关是 applicationRule 的位，面板拆成独立行，注释键为 "applicationRule.<开关>"。
_FLOWMAP_ANNOTATIONS = {
    "enableFlowmap": {
        "EN": "Distorts the main texture's UVs along the flowmap.",
        "ZH": "按流动贴图扭曲主贴图的 UV。",
    },
    "flowmapPath": {
        "EN": "The flowmap texture. Its R and G channels give the direction pixels are "
              "pushed; 0.5 means no movement.",
        "ZH": "流动贴图。R、G 通道给出像素被推开的方向，0.5 表示不动。",
    },
    "flowSpeed": {
        "EN": "Flow cycles per second. When looping, two layers half a cycle apart fade "
              "in and out in turn. 0 holds a fixed distortion.",
        "ZH": "每秒播放的轮数。循环时两层错开半轮交替淡入淡出；为 0 时保持固定扭曲。",
    },
    "flowSpeedCoef": {
        "EN": "Multiplies the speed once per frame. 1 = constant speed, above 1 speeds up, below 1 slows down; 0 counts as 1.",
        "ZH": "速度每帧乘一次的倍率。1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢；0 按 1 计。",
    },
    "flowStrength": {
        "EN": "How far pixels are pushed. At 1 a full-length flow direction moves them one "
              "whole texture cell by the end of a cycle; negative values push the other way.",
        "ZH": "扭曲幅度。强度 1 时，满幅的流动方向在一轮末尾推开一整格贴图；负值反向。",
    },
    "flowStrengthCoef": {
        "EN": "Multiplies the strength once per frame. 1 = unchanged, below 1 fades the distortion out; 0 counts as 1.",
        "ZH": "强度每帧乘一次的倍率。1 为不变，小于 1 逐渐减弱；0 按 1 计。",
    },
    "flowOnce": {
        "EN": "Plays a single cycle and holds the final distortion. Off = loop.",
        "ZH": "只播放一轮，停在最后的扭曲上；关闭时循环播放。",
    },
    "flowReverse": {
        "EN": "Plays the cycle backwards. Only works with Freeze After One Play.",
        "ZH": "反向播放这一轮。仅在「播放一次后冻结」开启时生效。",
    },
}

FIELD_ANNOTATIONS.update({
    (_t, _f): _v
    for _t in ('RIBBON', 'STRAINRIBBON', 'LIGHTNING', 'RIBBONBLADE', 'UVCONTROL')
    for _f, _v in _FLOWMAP_ANNOTATIONS.items()
    if (_f not in ("flowOnce", "flowReverse") or _t in ("RIBBON", "RIBBONBLADE"))
    and (_t, _f) != ("UVCONTROL", "flowmapPath")
})
FIELD_ANNOTATIONS.update({
    (_t, "applicationRule." + _f): _FLOWMAP_ANNOTATIONS[_f]
    for _t in ('BILLBOARD3D', 'PLANE', 'BILLBOARD2D')
    for _f in ("enableFlowmap", "flowOnce", "flowReverse")
})
FIELD_ANNOTATIONS.update({
    (_t, _f): _FLOWMAP_ANNOTATIONS[_f]
    for _t in ('BILLBOARD3D', 'PLANE', 'BILLBOARD2D')
    for _f in ("flowmapPath", "flowSpeed", "flowSpeedCoef", "flowStrength", "flowStrengthCoef")
})
FIELD_ANNOTATIONS.update({
    (_t, "applicationRule"): {
        "EN": "Unknown effect; not part of the flowmap settings. Usually off.",
        "ZH": "作用未知，不属于流动贴图设置。通常关闭。",
    }
    for _t in ('BILLBOARD3D', 'PLANE', 'BILLBOARD2D')
})
# UVCONTROL 的流动贴图取材质里的 FlowMap 槽，扭曲的是网格 UV
FIELD_ANNOTATIONS[("UVCONTROL", "enableFlowmap")] = {
    "EN": "Distorts the mesh UVs along the material's flowmap.",
    "ZH": "按材质里的流动贴图扭曲网格 UV。",
}


# ─────────────────────────────────────────────────────────────────────────────
# 公共查询函数
# ─────────────────────────────────────────────────────────────────────────────


def get_annotation(type_name: str, field_name: str) -> str:
    """
    按 (type_name, field_name) 查注释，并按当前 UI 语言返回字符串。
    type_name 大写（如 "EMITTERSHAPE3D"）；field_name 为 schema ori_name。
    值为 {"EN":.., "ZH":..} 字典，按 i18n.get_lang() 选取，缺语种回退英文。

    """
    base = ""
    entry = FIELD_ANNOTATIONS.get((type_name.upper(), field_name))
    if entry:
        if isinstance(entry, dict):
            from . import i18n
            lang = i18n.get_lang()
            base = entry.get(lang) or entry.get("EN") or ""
        else:
            base = entry  # backward safety

    return base
