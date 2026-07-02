"""
blender_efx/annotations.py  —  L1.3 BT 注释接入

从 010 Editor BT 模板（refs/EFX_Subtypes.bt、EFX_Utils.bt）提取的字段注释。
手工解析并清洗，与 efx_format/structs.py 的 schema ori_name 对齐。

字典键格式：(type_name, field_ori_name)
  - type_name  : HASH_TO_NAME 对应的哈希名（大写，如 "EMITTERSHAPE3D"）
  - field_ori_name : schema 中的 ori_name（即 structs.py 里各 Schema 的字段名）

值：双语注释字典 {"EN": "<english>", "ZH": "<中文>"}（单行，去除多余空白）。
  get_annotation() 按当前 UI 语言（i18n.get_lang()）返回对应字符串，缺语种回退英文。

覆盖范围：
  - 30 种 flat 可编辑类型（有 schema 的类型）
  - 9 种含路径的 _custom 类型（fixed 部分字段）
  - 重点：枚举字段、bitflag 字段、有语义的 unkn 字段

注意：
  - 数组字段（如 unkn0[3]）在 schema 里是单个字段名 "unkn0"，注释也映射到该名。
  - 路径字段（path/path1/path2）由 io_tree 负责，面板显示 STRING 类型，注释不重复。
  - EXTERN 变体与主类型共用同一 schema 名（如 EXTERNVELOCITY3D → "VELOCITY3D" 注释不适用），
    Extern 块在 io_tree 中以不同 type_hash 存储，不在本字典；仅主 attr-block 类型有注释。
"""

# ─────────────────────────────────────────────────────────────────────────────
# RE Engine 官方字段名交叉参考（来自 DTI type dump，refs/dti_effect_fields.json）
# 键：(TYPE_NAME 大写, schema ori_name)  值：(官方字段名, CRC32 十六进制串, 置信度)
# 置信度："确认"（偏移对齐，铁定）/ "高" / "中" / "低"（语义推断）/ 省略=确认。
#   UI tip 渲染："确认"不加限定词；高/中/低 显示"X可能为 <名>"。
#
# 仅在注释 tooltip 末尾追加，作权威交叉参考——label / ori_name / 索引全不变。
# dump 的字段名是内存结构名（m/mp 前缀 或 nTimelineParam 动画参数名），与 .efx
# 文件布局非 1:1（内存≠文件，尾部常分歧），故逐字段人工核对、按置信度标注后录入。
#
# 注：哈希算法 jamcrc（zlib.crc32 ^ 0xFFFFFFFF）。数据源 refs/dti_effect_fields.json。
# ─────────────────────────────────────────────────────────────────────────────

FIELD_OFFICIAL_NAMES = {
    # ── PARENTOPTIONS（nEffect::ParentOptions，按内存偏移 0x30–0x50 铁对齐）──
    ("PARENTOPTIONS", "translation_tracking"): ("mRelationPos[XYZ]", "0xC8E41E1E", "确认"),
    ("PARENTOPTIONS", "angle_tracking"):       ("mRelationRot[XYZ]", "0x2DAC4052", "确认"),
    ("PARENTOPTIONS", "scale_tracking"):       ("mRelationScl[XYZ]", "0x1E11460A", "确认"),

    # ── 语义映射（nTimelineParam 动画参数 ↔ schema 字段，按置信度标注）──────────
    # TRANSFORM3D：translate/rotate/resize = 位置/旋转/缩放（XYZ 三连）铁定确认
    ("TRANSFORM3D", "translate"): ("pos[XYZ]", "0x8E8AFE06", "确认"),
    ("TRANSFORM3D", "rotate"):    ("rot[XYZ]", "0xF105BBE3", "确认"),
    ("TRANSFORM3D", "resize"):    ("scl[XYZ]", "0x9486DF23", "确认"),
    # BILLBOARD3D：color = 显示颜色 RGBA（nadao_qian.efx 实测：TIML 从红→蓝紫渐变确认）
    ("BILLBOARD3D", "color"):     ("Color",    "0x58689812", "确认"),
    # MESH：scale/rotation → SizeX/Y/Z / RotationX/Y/Z（nadao_qian.efx SizeY 0x531B9E44 实测确认，余轴同理）
    ("MESH", "scale"):            ("SizeX/Y/Z",    "0x241CAED2", "确认"),
    ("MESH", "rotation"):         ("RotationX/Y/Z","0x002FF505",  "确认"),
    # VELOCITY3D：gravity 名称精确吻合
    ("VELOCITY3D", "gravity"):    ("Gravity", "0x6A5FE3C4", "高"),
    # EMITTERSHAPE3D：transform ↔ Range 盒（注释确认定尺寸/范围，升高）；
    # trayectoryRotation 注释强调"轨迹"旋转，与泛指 LocalRotation 有微妙差异，降中
    ("EMITTERSHAPE3D", "trayectoryRotationX"): ("LocalRotationX", "0x701FE225", "中"),
    ("EMITTERSHAPE3D", "trayectoryRotationY"): ("LocalRotationY", "0x0718D2B3", "中"),
    ("EMITTERSHAPE3D", "trayectoryRotationZ"): ("LocalRotationZ", "0x9E118309", "中"),
    ("EMITTERSHAPE3D", "transform"):           ("RangeMin/Max[XYZ]", "0x760F3D43", "高"),
    # SCALEANIM：Size*Add 动画增量 ↔ 缩放速度（注释佐证整体/按轴，且 dump 无 Accel 参数）
    ("SCALEANIM", "initialScaleSpeed"): ("SizeScalarAdd", "0xC24DF97C", "高"),
    ("SCALEANIM", "scaleSpeedX"):       ("SizeXAdd", "0x909EC047", "高"),
    ("SCALEANIM", "scaleSpeedY"):       ("SizeYAdd", "0x2822A722", "高"),
    ("SCALEANIM", "scaleSpeedZ"):       ("SizeZAdd", "0x3A9708CC", "高"),
    # ROTATEANIM：单字段 spin_velocity 与按轴 RotationAdd 存在歧义
    ("ROTATEANIM", "spin_velocity"):    ("RotationAdd", "0xE81961E4", "低"),
    # LIFE：KeepFrame ≈ 存活时长
    ("LIFE", "duration"):               ("KeepFrame", "0xBD8D5203", "中"),
}


# ─────────────────────────────────────────────────────────────────────────────
# 注释字典
# 键：(type_name: str, field_name: str)
# 值：双语字典 {"EN": "...", "ZH": "..."}
# ─────────────────────────────────────────────────────────────────────────────

FIELD_ANNOTATIONS = {

    # ─── TRANSFORM3D ──────────────────────────────────────────────────────────
    # ExternTransform3D (EFX_Subtypes.bt)
    ("TRANSFORM3D", "unkn1"): {
        "EN": "Unknown. Observed frequency distribution: {0:236, 1:49, 2:233, 3:295, 4:28783, 5:36}",
        "ZH": "未知。观测频率分布：{0:236, 1:49, 2:233, 3:295, 4:28783, 5:36}",
    },
    ("TRANSFORM3D", "Translation_Velocity_Modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "Rotation_Velocity_Modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "Scale_Velocity_Modifier"): {
        "EN": "Multiplier / Acceleration? Range [0, 1]",
        "ZH": "乘数 / 加速度？范围 [0, 1]",
    },
    ("TRANSFORM3D", "enableVelocityBitflag"): {
        "EN": "Bitflag — Bit 0: Enable Velocity, Bit 1: Enable Acceleration?"
              "  | Observed: {0:26795, 1:2438, 2:340, 3:59}",
        "ZH": "位标志 —— 位 0：启用速度，位 1：启用加速度？"
              "  | 观测：{0:26795, 1:2438, 2:340, 3:59}",
    },

    # ─── PARENTOPTIONS ────────────────────────────────────────────────────────
    # ParentOptions (EFX_Subtypes.bt)
    ("PARENTOPTIONS", "translation_tracking"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Ignore Basic Transform",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=忽略基础变换",
    },
    ("PARENTOPTIONS", "angle_tracking"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Snap to Angle And Track",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=对齐到角度并追踪",
    },
    ("PARENTOPTIONS", "scale_tracking"): {
        "EN": "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
              "  1=Track Player Movement,  2=Do not track further movements,"
              "  3=Ignore Basic Transform",
        "ZH": "XYZ —— 每轴的跟随模式：  0=绝对追踪地图中心，"
              "  1=追踪玩家移动，  2=不再追踪后续移动，"
              "  3=忽略基础变换",
    },
    ("PARENTOPTIONS", "spawnTrack"): {
        "EN": "Track Across Spawns",
        "ZH": "跨生成追踪",
    },
    ("PARENTOPTIONS", "spawnLock"): {
        "EN": "Lock To Position (Frames)",
        "ZH": "锁定到位置（帧数）",
    },
    ("PARENTOPTIONS", "bleedPos"): {
        "EN": "Progressively Lock Elements to Position (Frames)",
        "ZH": "逐步将元素锁定到位置（帧数）",
    },
    ("PARENTOPTIONS", "bone_lim"): {
        "EN": "Bone Limitation",
        "ZH": "骨骼限制",
    },
    ("PARENTOPTIONS", "unkn1"): {
        "EN": "Unknown. Observed: {0:20433, 1:9199}",
        "ZH": "未知。观测：{0:20433, 1:9199}",
    },

    # ─── SPAWN ────────────────────────────────────────────────────────────────
    # ExternSpawn (EFX_Subtypes.bt)
    ("SPAWN", "occur"): {
        "EN": "Frames to wait before the effect first appears. occur2 adds random jitter.",
        "ZH": "指定帧数后才会出现。occur2 为随机抖动范围。",
    },
    ("SPAWN", "occur2"): {
        "EN": "Frames to wait before the effect first appears. occur2 adds random jitter.",
        "ZH": "指定帧数后才会出现。occur2 为随机抖动范围。",
    },
    ("SPAWN", "repeatAtribute"): {
        "EN": "0=Repeat indefinitely; higher value=number of repetitions. "
              "unkn21 must be ≥1 to allow other attributes to cycle. "
              "Combined with durationOfSpawnerLifespan for finite cycles.",
        "ZH": "0=无限重复；数值越大=重复次数越多。"
              "unkn21 必须 ≥1 才能让其他属性循环。"
              "与 durationOfSpawnerLifespan 配合实现有限循环。",
    },

    # ─── LIFE ─────────────────────────────────────────────────────────────────
    # Life (EFX_Subtypes.bt)
    ("LIFE", "timeToDeath"): {
        "EN": "Overrides indefinite lifespan",
        "ZH": "覆盖无限寿命",
    },
    ("LIFE", "timeToDeathJitter"): {
        "EN": "Overrides indefinite lifespan",
        "ZH": "覆盖无限寿命",
    },

    # ─── EMITTERSHAPE3D ───────────────────────────────────────────────────────
    # ExternEmitterShape3D (EFX_Subtypes.bt)
    ("EMITTERSHAPE3D", "patternControl"): {
        "EN": "Emitter shape: 0=Cube, 1=Sphere, 2=Ring, 3=Spot",
        "ZH": "发射器形状：0=立方体, 1=球, 2=环, 3=点",
    },
    ("EMITTERSHAPE3D", "trayectoryRotationX"): {
        "EN": "Rotates the trajectory over which spawned entries are copied. "
              "Does NOT reorient the normal or tangent vector of the spawn object.",
        "ZH": "旋转生成条目被复制所沿的轨迹。"
              "不会重新定向生成对象的法线或切线向量。",
    },
    ("EMITTERSHAPE3D", "trayectoryRotationY"): {
        "EN": "Rotates trajectory Y. Does not reorient spawn object normal/tangent.",
        "ZH": "旋转轨迹 Y。不会重新定向生成对象的法线/切线。",
    },
    ("EMITTERSHAPE3D", "trayectoryRotationZ"): {
        "EN": "Rotates trajectory Z. Does not reorient spawn object normal/tangent.",
        "ZH": "旋转轨迹 Z。不会重新定向生成对象的法线/切线。",
    },
    ("EMITTERSHAPE3D", "spawnPerCycle"): {
        "EN": "Entries spawned per cycle; next cycle offsets by one position",
        "ZH": "每周期生成的条目数；下一周期偏移一个位置",
    },

    # ─── VELOCITY3D ───────────────────────────────────────────────────────────
    # ExternVelocity3D (EFX_Subtypes.bt)
    ("VELOCITY3D", "unkn0"): {
        "EN": "Neutral direction is (0, 1, 0)",
        "ZH": "中性方向为 (0, 1, 0)",
    },
    ("VELOCITY3D", "expansion_radius_elasticity"): {
        "EN": "1/−1 are the peak values. Above 1 or below −1: velocity surges and ignores "
              "expansion_radius_limit. Below 1: decelerates, consuming initial velocity until 0. "
              "0=Completely dampened (instantly at position); 1=No dampening (uniform motion).",
        "ZH": "1/−1 为顶值。高于1/低于−1：速度急剧加快并无视扩散范围限制。低于1：减速，"
              "消耗初速度直到0。0=完全阻尼（瞬间到位）；1=无阻尼（匀速运动）。",
    },
    ("VELOCITY3D", "velocityX"): {
        "EN": "Subtracts from system net energy; higher values restrict radial motion",
        "ZH": "从系统净能量中扣除；数值越大越限制径向运动",
    },
    ("VELOCITY3D", "energyOnAxisX"): {
        "EN": "(1-x): above 1 = traditional emission radially, "
              "below 1 = implosion, 1 = no energy. Higher = faster.",
        "ZH": "(1-x)：大于 1=传统径向发射，"
              "小于 1=向内坍缩，1=无能量。越大越快。",
    },
    ("VELOCITY3D", "energyOnAxisY"): {
        "EN": "(1-y): above 1 = traditional emission radially, "
              "below 1 = implosion, 1 = no energy.",
        "ZH": "(1-y)：大于 1=传统径向发射，"
              "小于 1=向内坍缩，1=无能量。",
    },
    ("VELOCITY3D", "energyOnAxisZ"): {
        "EN": "(1-z): above 1 = traditional emission radially, "
              "below 1 = implosion, 1 = no energy.",
        "ZH": "(1-z)：大于 1=传统径向发射，"
              "小于 1=向内坍缩，1=无能量。",
    },
    ("VELOCITY3D", "expansionType"): {
        "EN": "0=No initial velocity (all axis speed lost); "
              "1=Linear radial: gains axis energy + initial velocity, moves toward high-energy axis; "
              "2=Omnidirectional sphere: gains axis energy but no initial velocity, expands outward as sphere/ring; "
              "higher values cycle — odd=same as 1, even=same as 2.",
        "ZH": "0=丢失所有初速度，无论上面数值是多少；"
              "1=线性径向：获得轴能量+初速度，向能量高处线性运动；"
              "2=球状扩散：获得轴能量但无初速度，向四周运动、粒子呈球状/环状；"
              "更高值循环——奇数效果同1，偶数效果同2。",
    },

    # ─── SHADERSETTINGS ───────────────────────────────────────────────────────
    # ShaderSettings (EFX_Subtypes.bt)
    ("SHADERSETTINGS", "controlBitflag"): {
        "EN": "0=No alpha, 1=Alpha enabled, 2=Emissive behavior, "
              "3=Inverted color + alpha, 6=Greyscale",
        "ZH": "0=无 alpha, 1=启用 alpha, 2=自发光行为, "
              "3=反色 + alpha, 6=灰度",
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
    ("SHADERSETTINGS", "visibleOnPreview"): {
        "EN": "Bitflag — controls preview visibility",
        "ZH": "位标志 —— 控制预览可见性",
    },
    ("SHADERSETTINGS", "unkn3_1"): {
        "EN": "Render layer / billboard mode. "
              "0=3D billboard (default); 2=Plane; "
              "3=certain render subjects (e.g. BILLBOARD2D) bypass TONEMAPFILTER color grading; "
              "6/7/8/9=3D billboard variants.",
        "ZH": "渲染层 / billboard 模式。"
              "0=3D billboard（默认）；2=Plane；"
              "3=部分渲染主体（如 BILLBOARD2D）可无视 TONEMAPFILTER 色调滤镜；"
              "6/7/8/9=3D billboard 变体。",
    },

    # ─── FADEBYDEPTH ──────────────────────────────────────────────────────────
    # FadeByDepth (EFX_Subtypes.bt)
    ("FADEBYDEPTH", "viewAngleLimit"): {
        "EN": "360 = visible from every angle",
        "ZH": "360 = 从每个角度都可见",
    },

    # ─── SCALEANIM ────────────────────────────────────────────────────────────
    # ExternScaleAnim (EFX_Subtypes.bt)
    ("SCALEANIM", "initialScaleSpeed"): {
        "EN": "Initial expansion speed (the overall scale-in at animation start).",
        "ZH": "初始扩散速度（动画刚进来时的整体缩放）。",
    },

    # ─── ROTATEANIM ───────────────────────────────────────────────────────────
    ("ROTATEANIM", "unkn0_0"): {
        "EN": "Axis mask (bitmask): bit0=X, bit1=Y, bit2=Z. Controls which axes receive spin.",
        "ZH": "轴掩码（bitmask）：bit0=X，bit1=Y，bit2=Z。控制哪些轴参与自旋。",
    },
    ("ROTATEANIM", "unkn0_1"): {
        "EN": "Rotation mode: 0/1=billboard plane rotation only; 2 or 3=spin velocity enabled.",
        "ZH": "旋转模式：0/1=仅 billboard 平面旋转；取 2 或 3 时 spin_velocity 生效。",
    },

    # ─── ALPHACORRECTION ──────────────────────────────────────────────────────
    # AlphaCorrection (EFX_Subtypes.bt)
    ("ALPHACORRECTION", "alpha_clip_threshold"): {
        "EN": "Hard alpha clip threshold (like Photoshop's Threshold tool) — alpha below this value is cut to 0. 0 = no clipping.",
        "ZH": "Alpha 硬裁切阈值（类似 PS 的 Threshold 工具）——低于此值的 alpha 直接归 0。0 = 不裁切。",
    },
    ("ALPHACORRECTION", "contrast_gamma"): {
        "EN": "Contrast/gamma correction on alpha (field formerly named 'transparentness'). Unbounded — higher values fade out low/mid alpha (edges) while keeping high alpha (core) intact; values can exceed 1, where almost everything fades to transparent.",
        "ZH": "对 alpha 做对比度/伽马修正（原字段名 transparentness）。无上限——值越大，低/中 alpha（边缘）越快变透明，高 alpha（核心）保留；可超过 1，过大时几乎全图变透明。",
    },

    # ─── TUBELIGHT ────────────────────────────────────────────────────────────
    # TubeLight 由一个面（tailColor 发光平面）+ 一根光柱（起点 headColor，终点 tailColor）组成。
    ("TUBELIGHT", "headColor"): {
        "EN": "Light column start color.",
        "ZH": "光柱起点颜色。",
    },
    ("TUBELIGHT", "tailColor"): {
        "EN": "Light column end color.",
        "ZH": "光柱终点颜色。",
    },
    ("TUBELIGHT", "headColorEpvSlot"): {
        "EN": "EPV color slot associated with headColor.",
        "ZH": "起点颜色对应的 EPV 颜色槽。",
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
    ("TUBELIGHT", "lightIntensityJitter"): {
        "EN": "Random jitter on the light intensity.",
        "ZH": "光照强度的随机抖动。",
    },
    ("TUBELIGHT", "tailGlowSpread"): {
        "EN": "Makes the tail glow longer with softer/blurrier edges.",
        "ZH": "让尾光变得更长、边缘更虚。",
    },
    ("TUBELIGHT", "frontFaceTintMode"): {
        "EN": "0=emission-facing direction unaffected by the tube's own light. 1=surrounding glow brightens, facing direction tinted by tailColor.",
        "ZH": "0=发射面朝向方向不受自身光影响；1=发光区域四周变亮，朝向方向受 tailColor 染色。",
    },
    ("TUBELIGHT", "backFaceTintMode"): {
        "EN": "Same as frontFaceTintMode but inverted — controls whether the region opposite the facing direction is tinted by headColor.",
        "ZH": "跟 frontFaceTintMode 一样但反过来——控制发射面反向区域是否受 headColor 染色。",
    },
    ("TUBELIGHT", "tailPlaneOffset"): {
        "EN": "Front-back position of the tailColor emitting plane.",
        "ZH": "tailColor 发光平面的前后位置。",
    },
    ("TUBELIGHT", "unkn6b_1"): {
        "EN": "Possibly related to the brightness/glow halo of the emission — not confirmed.",
        "ZH": "可能跟发光的明暗光圈相关，尚未确认。",
    },
    ("TUBELIGHT", "unkn5_0"): {
        "EN": "Always 24 in the sample data — likely just a common default value.",
        "ZH": "语料里恒为 24，可能只是常见的默认值。",
    },
    ("TUBELIGHT", "unkn1_0"): {
        "EN": "Possibly texture scroll speed.",
        "ZH": "可能为纹理滚动速度。",
    },
    ("TUBELIGHT", "unkn1_8"): {
        "EN": "Possibly core brightness.",
        "ZH": "可能为核心亮度。",
    },
    ("TUBELIGHT", "unkn1_10"): {
        "EN": "Possibly related to the light column's length; relation to columnLength/columnLengthModifier not yet determined.",
        "ZH": "可能与光柱长度有关，跟 columnLength/columnLengthModifier 的关系还不确定。",
    },

    # ─── RGBFIRE ──────────────────────────────────────────────────────────────
    # ExternRgbFire (EFX_Subtypes.bt)
    ("RGBFIRE", "fireColor"): {
        "EN": "Fire color — the outer glowing edge; also tints the inner smoke color.",
        "ZH": "火焰色——外缘的荧光色；同时会给内部的烟雾色染色。",
    },
    ("RGBFIRE", "brightness1"): {
        "EN": "Fire color brightness — colors will combine.",
        "ZH": "火焰色亮度——颜色会叠加混合。",
    },
    ("RGBFIRE", "smokeColor"): {
        "EN": "Smoke color — the inner core color.",
        "ZH": "烟雾色——内部的核心色。",
    },
    ("RGBFIRE", "brightness2"): {
        "EN": "Smoke color brightness rate.",
        "ZH": "烟雾色的亮度速率。",
    },
    ("RGBFIRE", "brightness3"): {
        "EN": "Color Balance 1 — brings out color 1 without lowering overall brightness",
        "ZH": "色彩平衡 1 —— 在不降低整体亮度的情况下突出颜色 1",
    },
    ("RGBFIRE", "brightness4"): {
        "EN": "Color Balance 2 — setting either balance to 0 makes all disappear",
        "ZH": "色彩平衡 2 —— 任一平衡设为 0 都会让全部消失",
    },
    ("RGBFIRE", "fireColorParam_enable"): {
        "EN": "Fire color timing params (fade-in / duration / fade-out).",
        "ZH": "火焰色时序参数（淡入 / 持续 / 淡出）。",
    },
    ("RGBFIRE", "fireColorParam_unkn9"): {
        "EN": "Setting to 1 kills the fire color.",
        "ZH": "设为 1 会消除火焰色。",
    },
    ("RGBFIRE", "smokeColorParam_enable"): {
        "EN": "Smoke color timing params (fade-in / duration / fade-out). Note: even a short duration can tint a persistent effect permanently.",
        "ZH": "烟雾色时序参数（淡入 / 持续 / 淡出）。注意：即使持续时间很短，也可能对常驻特效造成持久染色。",
    },
    ("RGBFIRE", "smokeColorParam_unkn9"): {
        "EN": "Setting to 1 kills the smoke color.",
        "ZH": "设为 1 会消除烟雾色。",
    },

    # ─── GUIDE ────────────────────────────────────────────────────────────────
    # Guide (EFX_Subtypes.bt) — field names are descriptive, few inline comments

    # ─── PLEMISSIVE ───────────────────────────────────────────────────────────
    # ExternPlEmissive (EFX_Subtypes.bt)
    # body_p / wp_p 已重命名为 Aura Part (Player)/(Weapon) 并配勾选弹窗，名称自明，无需注释。
    ("PLEMISSIVE", "area"): {
        "EN": "Area of Aura (2 floats)",
        "ZH": "光圈区域（2 个 float）",
    },
    ("PLEMISSIVE", "bright"): {
        "EN": "Brightness (can be negative)",
        "ZH": "亮度（可为负值）",
    },
    ("PLEMISSIVE", "area_of_aura"): {
        "EN": "9=Front half,  8-1=Everything",
        "ZH": "9=前半部分,  8-1=全部",
    },

    # ─── PARENTEMISSIVE ───────────────────────────────────────────────────────
    # ParentEmissive (EFX_Subtypes.bt)
    ("PARENTEMISSIVE", "brightness"): {
        "EN": "Brightness",
        "ZH": "亮度",
    },
    ("PARENTEMISSIVE", "rimParam"): {
        "EN": "Emissive Rim Parameters (3 floats)",
        "ZH": "自发光边缘光参数（3 个 float）",
    },
    ("PARENTEMISSIVE", "blendParam"): {
        "EN": "Emissive Rim Blend Parameters (3 floats)",
        "ZH": "自发光边缘光混合参数（3 个 float）",
    },

    # ─── PLSNOW ───────────────────────────────────────────────────────────────
    # PlSnow (EFX_Subtypes.bt)
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
    # PtCollision (EFX_Subtypes.bt)
    ("PTCOLLISION", "physicsEnum"): {
        "EN": "0=Fall Through,  1=Bounce and Fade,  "
              "2=Bounce and Fall Through,  3=For Remaining after Bouncing (set multiplier to 0)",
        "ZH": "0=穿透坠落,  1=反弹并渐隐,  "
              "2=反弹后穿透坠落,  3=用于反弹后的残留（将乘数设为 0）",
    },
    ("PTCOLLISION", "bounceElasticity"): {
        "EN": "Bounce Elasticity On Collision",
        "ZH": "碰撞时的反弹弹性",
    },
    ("PTCOLLISION", "bounceElasticityJitter"): {
        "EN": "Bounce Elasticity Jitter",
        "ZH": "反弹弹性随机偏差",
    },
    ("PTCOLLISION", "horizontalBounce"): {
        "EN": "Multiplier of bounce elasticity",
        "ZH": "反弹弹性的乘数",
    },
    ("PTCOLLISION", "ieIndex"): {
        "EN": "0=Call PlayEFX Index?,  0xFFFFFFFF=Null",
        "ZH": "0=调用 PlayEFX 索引？,  0xFFFFFFFF=空",
    },

    # ─── PTLIFE ───────────────────────────────────────────────────────────────
    # PtLife (EFX_Subtypes.bt)
    ("PTLIFE", "timing"): {
        "EN": "0=Attaches at spawn,  4=Attaches after the end",
        "ZH": "0=在生成时附加,  4=在结束后附加",
    },
    ("PTLIFE", "relationIndex"): {
        "EN": "Play Emitter / Play EFX Index that declares the children",
        "ZH": "声明子级的 Play Emitter / Play EFX 索引",
    },

    # ─── EMITTERBOUNDARY ──────────────────────────────────────────────────────
    # EmitterBoundary — no inline comments in BT

    # ─── FADEBYANGLE ──────────────────────────────────────────────────────────
    # FadeByAngle — no inline comments in BT

    # ─── FADEBYEMITTERANGLE ───────────────────────────────────────────────────
    # FadeByEmitterAngle — marked "#UNKNOWN STRUCT" in BT

    # ─── NOISE ────────────────────────────────────────────────────────────────
    # Noise — no inline comments in BT

    # ─── UVCONTROL ────────────────────────────────────────────────────────────
    # UVControl (EFX_Subtypes.bt)
    ("UVCONTROL", "uv1_acceleration"): {
        "EN": "Multiplies speed every second (UV1)",
        "ZH": "每秒对速度做乘法（UV1）",
    },
    ("UVCONTROL", "uv2_acceleration"): {
        "EN": "Multiplies speed every second (UV2)",
        "ZH": "每秒对速度做乘法（UV2）",
    },
    ("UVCONTROL", "opacityAcceleration"): {
        "EN": "Multiplies opacity every second",
        "ZH": "每秒对不透明度做乘法",
    },

    # ─── EMITTERSHAPE2D ───────────────────────────────────────────────────────
    # EmitterShape2D — no inline comments in BT

    # ─── RAYCAST ──────────────────────────────────────────────────────────────
    # RayCast (EFX_Subtypes.bt)
    ("RAYCAST", "direction"): {
        "EN": "0=Left, 1=Down, 2=Forward, 3=Right, 4=Up, 5=Backward",
        "ZH": "0=左, 1=下, 2=前, 3=右, 4=上, 5=后",
    },
    ("RAYCAST", "unknown1"): {
        "EN": "Usually -1; occasionally 0",
        "ZH": "通常为 -1；偶尔为 0",
    },
    ("RAYCAST", "unknown2"): {
        "EN": "Observed value 256 — may be flag or enum",
        "ZH": "观测值 256 —— 可能是标志或枚举",
    },

    # ─── HOMING ───────────────────────────────────────────────────────────────
    # 字段语义来自 207 个官方块的统计 + 系统性实测逆向（2026-06）。
    ("HOMING", "unknown"): {
        "EN": "Observed range 1–29. Testing showed NO observable effect on homing "
              "behavior (not a bone index). Purpose unknown.",
        "ZH": "观测范围 1–29。实测对归航行为无可观影响（非骨骼索引）。用途未知。",
    },
    ("HOMING", "unknown0"): {
        "EN": "Always 44 in all 207 observed blocks — do not modify",
        "ZH": "207 个块中恒为 44，请勿修改",
    },
    ("HOMING", "spacer"): {
        "EN": "Always 0xCDCDCD00 — do not modify",
        "ZH": "恒为 0xCDCDCD00，请勿修改",
    },
    ("HOMING", "f0"): {
        "EN": "Angular velocity: ω ∝ F0 (linear). Rotates velocity vector each frame. "
              "Best range 90–360. Above ~18000 force overflows and fails.",
        "ZH": "角速度参数，ω ∝ F0（线性）；每帧旋转速度向量方向。"
              "推荐范围 90~360，超过约 18000 引力溢出失效。",
    },
    ("HOMING", "speed"): {
        "EN": "Damping / convergence rate. Higher = faster spiral to orbit, "
              "does NOT change final orbit size. 0 = particles invisible (no motion, trail hidden).",
        "ZH": "阻尼/收敛速率，值越大越快螺旋到轨道，不影响最终轨道大小。"
              "0=粒子不可见（静止，拖尾渲染不显示）。",
    },
    ("HOMING", "speedMultiplier"): {
        "EN": "Per-frame tangential force (not initial velocity). "
              "Sets natural orbit radius: r ∝ speedMultiplier^1.5 / F0. "
              "Large values cause outward spiral over many loops before settling.",
        "ZH": "每帧持续切向力（非初始速度）。决定自然轨道半径：r ∝ speedMultiplier^1.5 / F0。"
              "值过大时粒子需要多圈螺旋才能收敛到轨道。",
    },
    ("HOMING", "f3"): {
        "EN": "No observed effect on orbit (0.0–1.0 tested). "
              "Likely render-layer fade: opacity/brightness decay multiplier per frame. "
              "Official use: 84% = 1.0 (no decay).",
        "ZH": "对轨道无可见影响（已测 0.0–1.0）。"
              "推测为渲染衰减：每帧透明度/亮度乘数。官方 84% 使用 1.0（不衰减）。",
    },
    ("HOMING", "f4"): {
        "EN": "Homing force activation distance threshold. "
              "f4 < natural orbit radius → orbit expands (particles exit activation zone). "
              "f4 > natural orbit radius → orbit constrained to natural radius. "
              "Official default 50 (73%).",
        "ZH": "归航力激活距离阈值。f4 < 自然轨道半径 → 轨道膨胀（粒子飞出激活区）；"
              "f4 > 自然轨道半径 → 轨道约束到自然半径。官方默认 50（73%）。",
    },
    ("HOMING", "radius"): {
        "EN": "Force falloff distance — minimal effect on orbit in tests (50–1000 range tested). "
              "Official default 1000 (71%).",
        "ZH": "力场衰减距离，实测对轨道影响极小（已测 50–1000）。官方默认 1000（71%）。",
    },
    ("HOMING", "i0"): {
        "EN": "Homing target = (i0 mod 4): 0=spawn point (emitter pos), "
              "1=model/character origin (feet), 2/3=world origin (map center). "
              "Cycles every 4 (4=spawn, 5=model, …). Target captured at trigger time. "
              "Trajectory: 0/2=straight, 1=arc. Orbit plane = surface normal at trigger point. "
              "Official: 0=84%, 1=13%, 2=4%.",
        "ZH": "归航目标 = (i0 mod 4)：0=生成点（发射器位置），"
              "1=模型/角色原点（脚下），2/3=世界原点（地图中心）。"
              "每 4 循环（4=生成点, 5=模型原点…）。目标在触发时捕获。"
              "轨迹：0/2=直线，1=弧线。轨道面由触发面法线决定。官方用值：0=84%，1=13%，2=4%。",
    },
    ("HOMING", "i1"): {
        "EN": "Visibility flag. bit0=1 AND bit1=1 (values 3,7,11…) = normal; "
              "bit0=0 AND bit1=1 (values 2,6,10…) = particles disappear. "
              "Official: 0=73%, 2=26%, 1=2%.",
        "ZH": "可见性标志。bit0=1且bit1=1（3,7,11…）=正常；"
              "bit0=0且bit1=1（2,6,10…）=粒子消失。官方：0=73%，2=26%，1=2%。",
    },
    ("HOMING", "enableRadialVanish"): {
        "EN": "Orbit escape behavior. 0=normal (particle ejected radially after a few orbits). "
              "1=homing force disabled (free expansion). 2/4=persistent orbit (no ejection). "
              "3=periodic radial escape: orbit one loop → dash outward radially → orbit again, repeating. "
              "Official: 0=72%, 3=11%, 2=8%, 1=7%, 4=2%.",
        "ZH": "轨道逃逸行为。0=正常（绕几圈后径向甩出）；1=归航引力失效（自由扩散）；"
              "2/4=持续轨道（不甩出）；3=周期性径向逃逸：绕一圈→径向冲出一段→再绕一圈，反复。"
              "官方：0=72%，3=11%，2=8%，1=7%，4=2%。",
    },
    ("HOMING", "unknown1"): {
        "EN": "Almost always 0 (97% of official blocks)",
        "ZH": "几乎恒为 0（官方 97%）",
    },

    # ─── SCREENSPACECOLLISION ─────────────────────────────────────────────────
    # ScreenSpaceCollision (EFX_Subtypes.bt)
    ("SCREENSPACECOLLISION", "lifespan"): {
        "EN": "0=No interaction; higher values = more bounce",
        "ZH": "0=无交互；数值越大反弹越多",
    },

    # ─── SHOVEL ───────────────────────────────────────────────────────────────
    # Shovel — no inline comments in BT for most fields

    # ─── EXTERNREFERENCE ──────────────────────────────────────────────────────
    # ExternReference — no inline comments in BT

    # ─── DUMMY / RANDOMFIX / MASTERONLY / BLINK / LUMINANCEBLEED / REFRACTION ─
    # No significant inline comments in BT

    # ─── MESH (Mod3Properties fields — _custom type, flat part) ───────────────
    ("MESH", "end_model_viscon"): {
        "EN": "Picks between starting/end at random",
        "ZH": "在起始/结束之间随机选取",
    },
    ("MESH", "tracking_flags"): {
        "EN": "0=Guide Source,  1=Away from Source,  2=Look Away From Camera,  "
              "3=WTF Occupies entire map,  4=Guide Camera,  5=Disappears,  "
              "6=Don't Track Rotation At All,  7=Disappears,  "
              "8=Perpendicular to Ground Don't Track",
        "ZH": "0=引导源,  1=远离源,  2=背对摄像机,  "
              "3=WTF 占满整张地图,  4=引导摄像机,  5=消失,  "
              "6=完全不追踪旋转,  7=消失,  "
              "8=垂直于地面且不追踪",
    },
    ("MESH", "colorize_material1"): {
        "EN": "4 bytes controlling how the mesh is colorized. Byte 0 and byte 2 are two "
              "channels that both tint with color1 (having both on makes it brighter). "
              "Byte 1 needs byte 0 or byte 2 turned on too, and makes the color randomly "
              "cycle through a mix of color1/color2/color3 each time the effect plays "
              "(color4 never takes part). Byte 3 is a separate, usually near-invisible "
              "channel whose color can be set via colorize_material2.",
        "ZH": "4 个字节，控制网格如何染色。byte 0 和 byte 2 是两条都用 color1 染色的通道"
              "（两个都开会让颜色更亮）。byte 1 需要 byte 0 或 byte 2 也打开，会让颜色在 "
              "color1/color2/color3 之间随机混合，每次特效播放都可能不同（color4 不参与）。"
              "byte 3 是独立的一条通道，默认几乎看不见，颜色可以通过 colorize_material2 指定。",
    },
    ("MESH", "colorize_material2"): {
        "EN": "4 bytes. Byte 1 sets colorize_material1's byte-3 channel to color3. "
              "Byte 2, when non-zero, forces the main channel to solid color1, overriding "
              "any random color mix. Byte 0 has no confirmed effect.",
        "ZH": "4 个字节。byte 1 会把 colorize_material1 里 byte 3 那条通道的颜色设为 "
              "color3。byte 2 非零时会把主通道强制锁定为纯 color1，覆盖随机混色。byte 0 目前"
              "没有观察到效果。",
    },
    ("MESH", "randommizeViscon"): {
        "EN": "0=Spawn random sample of range,  1=Spawn all of the range",
        "ZH": "0=生成范围内的随机样本,  1=生成整个范围",
    },
    ("MESH", "shadowCastBitflag"): {
        "EN": "Shadow casting bitflag",
        "ZH": "投影位标志",
    },

    # ─── RIBBON (fixed part fields) ───────────────────────────────────────────
    ("RIBBON", "material_tesselation_density"): {
        "EN": "Material Repeating Density",
        "ZH": "材质重复密度",
    },
    ("RIBBON", "horizontal_physics_subdivision_count"): {
        "EN": "Number of Subdivisions +1 (horizontal dividers, minimum 2). "
              "Disney magic at 5000.",
        "ZH": "细分数 +1（水平分隔，最小为 2）。"
              "5000 时出现迪士尼级魔法效果。",
    },
    ("RIBBON", "restitution_direction"): {
        "EN": "0=Left, 1=Up, 2=Forward, 3=Right, 4=Down, 5=Backwards, 6=None",
        "ZH": "0=左, 1=上, 2=前, 3=右, 4=下, 5=后, 6=无",
    },
    ("RIBBON", "unkn16_2"): {
        "EN": "0=Align to World,  Anything else=Align to Source",
        "ZH": "0=对齐到世界,  其他任何值=对齐到源",
    },
    ("RIBBON", "unkn4_0"): {
        # 实测：原 unkn4 第一个值，其实是 float 标量（全语料 0.0–30.0，零 NaN，常见 ±0.0）。语义未定。
        "EN": "Float scalar (split from the old unkn4[0]). Observed clean values "
              "0.0–30.0 across all samples (commonly 0.0 / -0.0). Purpose not yet "
              "identified. The -2147483648 you may have seen as an int is actually "
              "-0.0 read as a float.",
        "ZH": "浮点标量（由旧 unkn4[0] 拆出）。全语料取值 0.0–30.0、零 NaN，常见 0.0 / -0.0。"
              "用途尚未确定。之前以 int 看到的 -2147483648 实际是 float 的 -0.0。",
    },
    ("RIBBON", "unkn4_1"): {
        # 实测：原 unkn4 第二个值 = 形态/速度对齐开关（int 枚举，语料含 0/1/2）。
        "EN": "Shape / velocity alignment (split from the old unkn4[1]): 0 = normal "
              "bendable ribbon strip; 1 = flag form (rigid, no bend) — auto-aligns to "
              "the velocity direction and generates a flat sheet; 2 also observed. "
              "Initial length/size relate to the scale/width/length fields below.",
        "ZH": "形态/速度对齐开关（由旧 unkn4[1] 拆出，int 枚举，语料含 0/1/2）："
              "0 = 正常条带（可弯折）；1 = 旗帜形态（刚性不弯）——自动对齐速度方向、"
              "生成一个面片；另观测到 2。初始长度/大小与下方 scale/width/length 等字段相关。",
    },
    ("RIBBON", "visiblePreview"): {
        # 实测（游戏内验证）：原观测名 visiblePreview，实为"可见性修正"。
        "EN": "Visibility Correction. Recommended value: 0. A non-zero value not only "
              "breaks normal TIML use (the ribbon won't read the color animation on "
              "animation1 / particle-lifetime axis) but also causes ribbon strips to go "
              "mysteriously missing. Keep at 0.",
        "ZH": "可见性修正。安全值：0。非 0 不仅会破坏 TIML 正常使用（条带读不到 "
              "animation1 / 粒子寿命轴上的颜色变换），还会让条带生成莫名缺失。请保持为 0。",
    },

    # ─── UVSEQUENCE (fixed part fields) ───────────────────────────────────────
    ("UVSEQUENCE", "uvs_index"): {
        "EN": "UVS File Path Index",
        "ZH": "UVS 文件路径索引",
    },
    ("UVSEQUENCE", "loopingMode"): {
        "EN": "Animation mode (loopingEnum byte 0). Key values: "
              "0=Not Animated (freeze frame),  2=Random Reset,  9=Continuous forward loop,  "
              "16=Continuous reverse loop.",
        "ZH": "动画模式（loopingEnum 第 0 字节）。关键值："
              "0=不播放动画（定格），2=随机重置，9=连续正向循环，16=连续反向循环。",
    },
    ("UVSEQUENCE", "loopingOrientation"): {
        "EN": "Texture orientation on particle (loopingEnum byte 1): "
              "0=Up,  1=Right,  2=Left,  3=Random (never down).",
        "ZH": "贴图显现在粒子上的方向（loopingEnum 第 1 字节）："
              "0=正向上，1=正向右，2=正向左，3=随机（绝不向下）。",
    },

    # ─── BILLBOARD3D (fixed part fields) ──────────────────────────────────────
    ("BILLBOARD3D", "applicationRule"): {
        "EN": "Enum — determines how long and how many times it applies. "
              "4=Enables flowmap effect (requires unkn6=1 to take effect).",
        "ZH": "枚举 —— 决定它应用的时长与次数。"
              "4=启用流动贴图效果（还需 unkn6=1 才生效）。",
    },
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
    ("PLANE", "applicationRule"): {
        "EN": "Enum — determines how long and how many times it applies. "
              "4=Enables flowmap effect (requires unkn6=1 to take effect).",
        "ZH": "枚举 —— 决定它应用的时长与次数。"
              "4=启用流动贴图效果（还需 unkn6=1 才生效）。",
    },
    ("PLANE", "brightness"): {
        "EN": "Brightness",
        "ZH": "亮度",
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
    ("RIBBONBLADE", "contractionSpeed"): {
        "EN": "0=Lingers,  1=Retracts,  ∞=Retracts instantly",
        "ZH": "0=驻留,  1=回缩,  ∞=瞬间回缩",
    },
    ("RIBBONBLADE", "colourTransitionPoint"): {
        "EN": "0=Instantly start transition,  1=Start at the end",
        "ZH": "0=立即开始过渡,  1=在末端开始",
    },

    # ─── TURBULENCE (fixed part fields) ───────────────────────────────────────
    # Turbulence — no inline comments in BT for non-path fields

    # ─── LIGHTNING (fixed part fields) ────────────────────────────────────────
    # Lightning — no significant inline comments in BT for fixed fields

    # ─── STRAINRIBBON（拔刀链条，社区注释 EFX_Crimson.bt）─────────────────────
    ("STRAINRIBBON", "color1"): {
        "EN": "Chain start-segment color RGBA (0~255)",
        "ZH": "链条起始段颜色 RGBA（0~255）",
    },
    ("STRAINRIBBON", "color2"): {
        "EN": "Chain middle-segment color RGBA (0~255)",
        "ZH": "链条中间段颜色 RGBA（0~255）",
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
    ("STRAINRIBBON", "startDirectionX"): {
        "EN": "Switch to extend the start end along the X axis (blade up/down); any "
              "non-zero triggers it (magnitude has no effect)",
        "ZH": "起始端朝 X 轴（刀身上下）延伸开关，非 0 即触发（数值大小无影响）",
    },
    ("STRAINRIBBON", "startDirectionY"): {
        "EN": "Switch to extend the start end along the Y axis (blade left/right); any "
              "non-zero triggers it; can stack with X/Z to compose a direction",
        "ZH": "起始端朝 Y 轴（刀身左右）延伸开关，非 0 即触发；可与 X/Z 叠加合成方向",
    },
    ("STRAINRIBBON", "startDirectionZ"): {
        "EN": "Switch to extend the start end along the Z axis (blade front/back); any "
              "non-zero triggers it; enabling all three axes composes a 3D direction",
        "ZH": "起始端朝 Z 轴（刀身前后）延伸开关，非 0 即触发；三轴同开产生立体合成方向",
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
        "EN": "Width random jitter (to be confirmed)",
        "ZH": "宽度随机偏差（待确认）",
    },
    ("STRAINRIBBON", "length"): {
        "EN": "Total chain length. =actual distance between the two bones makes it taut "
              "and flush; >the distance lets the excess fold into a natural arc and "
              "droop; combine with subdivision count to control the fold shape",
        "ZH": "链条总长度。=两骨骼实际距离时绷直贴合；>距离时多余部分弯折产生自然弧度和垂落；"
              "配合细分计数控制弯折形态",
    },
    ("STRAINRIBBON", "lengthJitter"): {
        "EN": "Length random jitter (to be confirmed)",
        "ZH": "长度随机偏差（待确认）",
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
        "EN": "Controls both physics-node count and visual smoothness. 1=degenerates to "
              "a straight line (physics bending disabled); 4=default; 16+=extremely "
              "smooth (energy ribbon). Lightning: 2~4 to keep edges; energy whip: 8~16",
        "ZH": "同时控制物理节点数与视觉平滑度。1=退化为直线（物理弯曲失效）；4=默认；"
              "16+=极圆滑（能量光带）。闪电建议 2~4 保留棱角，能量鞭建议 8~16",
    },
    ("STRAINRIBBON", "uvRepetition"): {
        "EN": "Number of texture repeats along the chain's length. 1=texture covers the "
              "whole chain once; larger=denser tiling that becomes a smooth line",
        "ZH": "贴图沿链条长度方向重复次数。1=贴图完整覆盖整条；越大锯齿越密变光滑线条",
    },
    ("STRAINRIBBON", "widthwiseUVScalingAlpha"): {
        "EN": "Texture widthwise alpha-channel scaling. 0.1=ultra-thin laser line; "
              "0.8=default; 5=extreme expansion, dense texture",
        "ZH": "贴图宽度方向透明通道缩放。0.1=极细激光线状；0.8=默认；5=极度扩张纹理密集",
    },
    ("STRAINRIBBON", "widthwiseUVScalingBML"): {
        "EN": "Texture widthwise lighting-channel scaling. 0.1=ultra-thin line; "
              "1=default; 5=greatly widened emissive texture with strong aliasing; pair "
              "with Alpha scaling for thickness/halo variation",
        "ZH": "贴图宽度方向光照通道缩放。0.1=极细线；1=默认；5=发光纹理宽度大增锯齿感强；与 Alpha 缩放配合做粗细/光晕变化",
    },
    ("STRAINRIBBON", "endPointScatter"): {
        "EN": "Endpoint-scatter switch (mislabeled as color in the template). 0=endpoint "
              "anchored to the end bone; non-zero=endpoint unanchored, multiple bolts "
              "appear at random surrounding positions scattering outward (magnitude has "
              "no effect, 0~255)",
        "ZH": "终点扩散开关（模板误标为颜色）。0=终点锚定到结束骨骼；非 0=终点不锚定，"
              "在四周随机位置出现多条闪电向外扩散（数值大小无影响，0~255）",
    },
    ("STRAINRIBBON", "originReleaseFlag"): {
        "EN": "Origin-release flag (mislabeled as color in the template). 0=origin "
              "anchored to bone #1; non-zero=origin released, all chains emit from the "
              "end-bone position toward the map's world center",
        "ZH": "起点解锁标志（模板误标为颜色）。0=起点锚定到 1 号骨骼；非 0=起点解锁，"
              "所有链条从结束骨骼位置朝地图世界中心方向发射",
    },
    ("STRAINRIBBON", "endBoneID"): {
        "EN": "Chain end-bound bone ID; extends from bone #1 to this bone, deciding the "
              "covered weapon-region extent (1=1-1, 3=higher per BT)",
        "ZH": "链条末端绑定骨骼编号，从 1 号骨骼延伸到此骨骼，决定覆盖的武器区域范围（BT：1=1-1，3=更远）",
    },
    ("STRAINRIBBON", "colorModeFlag"): {
        "EN": "Color-mode flag (positionalAberration_03). 2=cyan shift, 10+=disappears",
        "ZH": "颜色模式标志（positionalAberration_03）。2=青色偏移，10+=消失",
    },
    # 链条物理参数（MT Framework，即 MHW 引擎）
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

    # ─── 行为逆向补充（社区实测，世界特效注释解析）────────────────────────────
    # SPAWN
    ("SPAWN", "durationOfSpawnerLifespan"): {
        "EN": "0 + repeatAtribute=1 + LIFE.indefinite=0 → continuous emission. Non-0 → "
              "burst mode: the value = number of bursts (interval via frameDelayBetweenSpawns).",
        "ZH": "为 0 且 repeatAtribute=1、LIFE 无限寿命=0 → 持续发射；非 0 → 爆发模式，"
              "其值=爆发次数（间隔由 frameDelayBetweenSpawns 控制）。",
    },
    ("SPAWN", "randomizedLifespan"): {
        "EN": "0 + repeatAtribute=1 + LIFE.indefinite=0 → continuous emission. Non-0 → "
              "burst mode: the value = number of bursts (interval via frameDelayBetweenSpawns).",
        "ZH": "为 0 且 repeatAtribute=1、LIFE 无限寿命=0 → 持续发射；非 0 → 爆发模式，"
              "其值=爆发次数（间隔由 frameDelayBetweenSpawns 控制）。",
    },
    ("SPAWN", "frameDelayBetweenSpawns"): {
        "EN": "Frames between each spawn/burst. Together with durationOfSpawnerLifespan "
              "shapes the emission rhythm.",
        "ZH": "每次生成/爆发之间的帧间隔；与 durationOfSpawnerLifespan 共同决定发射节奏。",
    },
    ("SPAWN", "randomizedDelay"): {
        "EN": "Frames between each spawn/burst. Together with durationOfSpawnerLifespan "
              "shapes the emission rhythm.",
        "ZH": "每次生成/爆发之间的帧间隔；与 durationOfSpawnerLifespan 共同决定发射节奏。",
    },
    # LIFE
    ("LIFE", "indefiniteLifespan"): {
        "EN": "1 → particle ignores fade-in/out and lives forever; only disappears when the "
              "weapon's major state switches or an action force-clears all FX (disappearance "
              "still obeys fadeOutDuration). ⚠ Combine with high SPAWN counts = accumulation.",
        "ZH": "1 → 无视渐入渐出、粒子永久存在；除非切换武器大状态或动作强制关闭所有特效才消失"
              "（消失仍遵循淡出时间）。⚠ 与高 SPAWN 数量组合会累积。",
    },
    # EMITTERSHAPE3D
    ("EMITTERSHAPE3D", "transform"): {
        "EN": "Coupling depends on patternControl: Sphere/Cube → transform sets size/radius; "
              "Ring → y = ring world height, x/z = ring shape; Point → transform acts as a "
              "plain position offset.",
        "ZH": "与 patternControl 联动：球/立方体→transform 定尺寸/半径；圆环→y 是圆环世界高度、"
              "x/z 是圆环形状；point 点状→transform 直接当位移用。",
    },
    ("EMITTERSHAPE3D", "spawnAngleLimits"): {
        "EN": "Spawn angle limit in degrees. 360 = full ring; reducing it removes particles "
              "over part of the arc, packing the rest more densely.",
        "ZH": "粒子生成角度限制（角度制）。360=生成一圈；调小可删除某段弧的粒子，让排列更紧密。",
    },
    ("EMITTERSHAPE3D", "spawnTotal"): {
        "EN": "Total particles, split into equal groups; group count via spawnTotal, "
              "particles-per-group via spawnPerCycle (even distribution).",
        "ZH": "粒子总份数：与 spawnPerCycle 配合做平均分配——total 分几份、每份粒子数由 perCycle 控制。",
    },
    ("EMITTERSHAPE3D", "radiusEnd"): {
        "EN": "With radiusOrigin, controls spawn position in the shape. end=1,origin=1 → on "
              "the surface; end=1,origin=0 → filled solid interior.",
        "ZH": "与 radiusOrigin 一起控制在形状中的生成位置。都=1→生成在表面；end=1 origin=0→实心填满内部。",
    },
    ("EMITTERSHAPE3D", "radiusOrigin"): {
        "EN": "See radiusEnd. Inner bound of the spawn radius band.",
        "ZH": "见 radiusEnd。生成半径范围的内边界。",
    },
    # VELOCITY3D
    ("VELOCITY3D", "rotationX"): {
        "EN": "Rotates the particle RELEASE direction. If particles move along y, adjusting "
              "x/z biases them toward those axes.",
        "ZH": "旋转粒子的释放方向。粒子沿 y 走时，调 x/z 会让它向这两轴偏。",
    },
    ("VELOCITY3D", "expansion_radius_limit"): {
        "EN": "Caps the farthest spread distance during particle motion.",
        "ZH": "扩散范围：限制粒子运动时的最远扩散距离。",
    },
    ("VELOCITY3D", "expansion_radius_jitter"): {
        "EN": "Random addend on expansion_radius_limit.",
        "ZH": "扩散范围偏差（expansion_radius_limit 的随机加数）。",
    },
    ("VELOCITY3D", "expansion_radius_elasticity_jitter"): {
        "EN": "Random jitter on expansion_radius_elasticity (same nature as the radius jitter).",
        "ZH": "扩散弹性偏差（性质同扩散范围偏差）。",
    },
    ("VELOCITY3D", "gravity"): {
        "EN": "Adds a straight-down force to particles.",
        "ZH": "重力：给粒子一个向正下的力。",
    },
    ("VELOCITY3D", "gravityDelay"): {
        "EN": "Frames after spawn before gravity takes effect.",
        "ZH": "重力延迟：粒子生成后一段时间再受重力。",
    },
    ("VELOCITY3D", "expansionDelay"): {
        "EN": "Frames after spawn before initial velocity takes effect.",
        "ZH": "扩散延迟：粒子生成后一段时间再受初速度。",
    },
    # 运动模型：轴速率×各轴能量=初速度 → 经弹性(1匀速/>1加速/<1减速) → 受扩散范围限制最远位置。
    ("VELOCITY3D", "velocityY"): {
        "EN": "Per-axis speed multiplier (Y). Higher=faster; negative=opposite direction. "
              "Model: velocity × energyOnAxis = initial speed → elasticity → radius limit.",
        "ZH": "Y 轴速率（总计算乘数）。越高越快、负值反向。运动模型：轴速率×轴能量=初速度→弹性→扩散限制。",
    },
    ("VELOCITY3D", "velocityZ"): {
        "EN": "Per-axis speed multiplier (Z). See velocityY.",
        "ZH": "Z 轴速率。见 velocityY。",
    },
    # BILLBOARD3D（含本版新拆分字段）
    ("BILLBOARD3D", "randomBrightnessMult"): {
        "EN": "Random brightness multiplier: brightness is picked between 'not×this' and "
              "'×this'. (Was mistyped as int in the template; corrected to float.)",
        "ZH": "随机亮度乘数：亮度在「不×该值」与「×该值」之间随机取。（原模板误标为 int，已改为 float。）",
    },
    ("BILLBOARD3D", "blendMode"): {
        "EN": "Shader blend mode: 0 = alpha blend (can show black at normal brightness), "
              "1 = additive blend.",
        "ZH": "着色器混合模式：0=alpha 混合（正常亮度下可显示黑色），1=add 叠加混合。",
    },
    # SCALEANIM（社区验证语义：初始整体扩散 + 播放过程逐轴 X/Y/Z 速度/加速度）
    ("SCALEANIM", "initialScaleAccel"): {
        "EN": "Initial expansion acceleration, paired with initialScaleSpeed (the shrink-in "
              "at animation start; negative = shrinking).",
        "ZH": "初始扩散加速度，与 initialScaleSpeed 配对（动画刚进来的缩小效果，负值=缩小）。",
    },
    ("SCALEANIM", "scaleSpeedX"): {
        "EN": "X-axis scale speed during playback (billboard = X/Y; mesh = X/Y/Z).",
        "ZH": "播放过程中 X 轴缩放速度（billboard 用 X/Y 两轴；模型用 X/Y/Z 三轴）。",
    },
    ("SCALEANIM", "scaleAccelX"): {
        "EN": "X-axis scale acceleration during playback.",
        "ZH": "播放过程中 X 轴缩放加速度。",
    },
    ("SCALEANIM", "scaleSpeedY"): {
        "EN": "Y-axis scale speed during playback.",
        "ZH": "播放过程中 Y 轴缩放速度。",
    },
    ("SCALEANIM", "scaleSpeedZ"): {
        "EN": "Z-axis scale speed during playback (meshes only).",
        "ZH": "播放过程中 Z 轴缩放速度（仅模型有 Z 轴）。",
    },
    ("SCALEANIM", "animUpdateStart"): {
        "EN": "Frame time when the per-axis scale animation starts updating.",
        "ZH": "逐轴缩放动画开始更新的时间（帧）。",
    },
    # ROTATEANIM（含本版新拆分字段）
    ("ROTATEANIM", "billboardRotation"): {
        "EN": "Controls BILLBOARD3D plane rotation. (Was mistyped as int in the template; "
              "corrected to float.)",
        "ZH": "控制 BILLBOARD3D 平面类的旋转。（原模板误标为 int，已改为 float。）",
    },
    ("ROTATEANIM", "billboardRotationSpeed"): {
        "EN": "Second BILLBOARD3D plane-rotation parameter (rotation speed). (Corrected to "
              "float; exact role vs billboardRotation not fully confirmed.)",
        "ZH": "BILLBOARD3D 平面旋转的第二个参数（旋转速度）。（已改为 float；与 billboardRotation "
              "的具体分工待确认。）",
    },
    ("ROTATEANIM", "spin_velocity"): {
        "EN": "Model/plane rotation along three axes (with spin_acceleration below for each).",
        "ZH": "模型/平面的三轴旋转方式（下方 spin_acceleration 为各自加速度）。",
    },

    # ─── LIGHTNING ────────────────────────────────────────────────────────────
    # 社区逆向实测（010 Editor + 进游戏观察，MHW:Iceborne）。⚠ = 危险/崩溃字段。
    ("LIGHTNING", "spacer0"): {
        "EN": "Memory-alignment padding (-842150656). Do not edit.",
        "ZH": "内存对齐占位符（-842150656）。请勿编辑。",
    },
    ("LIGHTNING", "unkn02"): {
        "EN": "Memory-alignment padding between color blocks. Do not edit.",
        "ZH": "颜色块之间的内存对齐占位符。请勿编辑。",
    },
    ("LIGHTNING", "unkn03"): {
        "EN": "Memory-alignment padding between color blocks. Do not edit.",
        "ZH": "颜色块之间的内存对齐占位符。请勿编辑。",
    },
    ("LIGHTNING", "spacer05_00"): {
        "EN": "Memory-alignment padding (-842150656). Do not edit.",
        "ZH": "内存对齐占位符（-842150656）。请勿编辑。",
    },
    ("LIGHTNING", "spacer05_14"): {
        "EN": "Memory-alignment padding (-842150656). Do not edit.",
        "ZH": "内存对齐占位符（-842150656）。请勿编辑。",
    },
    ("LIGHTNING", "unkn00"): {
        "EN": "[0]=1 base config flag (untested); [1]=108 guessed max node count / "
              "subdivision precision (untested).",
        "ZH": "[0]=1 基础配置标志（待测）；[1]=108 推测为最大节点数 / 细分精度（待测）。",
    },
    ("LIGHTNING", "color1"): {
        "EN": "Lightning color 1 (RGBA). color1/color2 are two INDEPENDENT lightning "
              "palettes: the engine spawns instances in each color AND blends them into a "
              "third mixed color (red+blue→purple). Shared by both main and branch bolts.",
        "ZH": "闪电配色1（RGBA）。color1/color2 是两套独立配色：引擎按概率分别生成两色闪电，"
              "并叠加出第三种混合色（红+蓝→紫）。主线和支线共享此配色系统。",
    },
    ("LIGHTNING", "color2"): {
        "EN": "Lightning color 2 (RGBA). See color1 — independent palette, blends with "
              "color1 into a third color. Affects both main and branch bolts.",
        "ZH": "闪电配色2（RGBA）。见 color1——独立配色，与 color1 叠加出第三色，主支线共享。",
    },
    ("LIGHTNING", "emissive"): {
        "EN": "Self-emission color (RGB) + overall emissive alpha coefficient (A).",
        "ZH": "自发光颜色（RGB）+ 整体自发光透明度系数（A）。",
    },
    ("LIGHTNING", "unkn04"): {
        "EN": "≈4.0 as float; guessed emissive intensity multiplier (unconfirmed).",
        "ZH": "转为浮点约等于 4.0；推测是发光强度倍率（未确认）。",
    },
    ("LIGHTNING", "unkn05_01"): {
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
    ("LIGHTNING", "unkn05_05"): {
        "EN": "Branch disable flag (branchDisableFlag). 0=branches on; non-0=branches fully "
              "off (hard switch, ignores branch length/radius).",
        "ZH": "分支禁用标志。0=分支启用；非0=分支完全消失（硬开关，不受支路长度/半径影响）。",
    },
    ("LIGHTNING", "unkn05_06"): {
        "EN": "Branch origin offset (branchOriginOffset, default 0.6). 0=branches spawn far "
              "from main bolt (hedgehog radial look). Handy debug knob to isolate branches.",
        "ZH": "分支起始偏移距离（默认 0.6）。0=分支离主线很远、像刺猬向四周放射。"
              "常用调试：归0 拉开主支线便于单独观察。正负相近。",
    },
    ("LIGHTNING", "unkn05_07"): {
        "EN": "Reserved. No change observed at 0/3/300/3000/-3000.",
        "ZH": "保留字段。测 0/3/300/3000/-3000 均无变化。",
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
    ("LIGHTNING", "unkn05_11"): {
        "EN": "Transparency level B (lightningTransparencyLevel). 1=most opaque, 3=default, "
              "higher=more transparent; effective 1~300+. Negative=fully transparent "
              "(stable). Integer only. Low precision (vs unkn05_10).",
        "ZH": "闪电透明度等级B。1最不透明，3默认，越大越透明；有效 1~300+。"
              "负数=完全透明（稳定无溢出）。仅整数。精度低于 unkn05_10。",
    },
    ("LIGHTNING", "unkn05_12"): {
        "EN": "Flow & fade mode (lightningFlowAndFadeMode). 0=faster flow + keep fade-out; "
              "1=default (standard flow + fade); any other value=no flow change + fade-out "
              "cancelled (hard cut at end of life). Integer only.",
        "ZH": "流光与淡出模式。0=流光加速+保留淡出；1=默认（标准流光+淡出渐隐）；"
              "非0非1=流光无变化+淡出取消（生命周期结束直接硬切消失）。仅整数。",
    },
    ("LIGHTNING", "unkn05_13"): {
        "EN": "Reserved. No visible change at 0/1/10/negative.",
        "ZH": "保留字段。测 0/1/10/负数均无明显变化。",
    },
    ("LIGHTNING", "targetBoneID"): {
        "EN": "Target bone ID (default 200). Lightning extends from origin to this bone.",
        "ZH": "靶骨 ID（默认 200）。闪电从起点延伸到此骨骼位置。",
    },
    ("LIGHTNING", "unkn05_16"): {
        "EN": "Reserved. No visible change across many values.",
        "ZH": "保留字段。测多个数值均无明显变化。",
    },
    ("LIGHTNING", "unkn05_17"): {
        "EN": "Reserved. No visible change at 1/2/3/5/10/100/1000/negative.",
        "ZH": "保留字段。测 1/2/3/5/10/100/1000/负数均无明显变化。",
    },
    ("LIGHTNING", "EPVColorSlot1"): {
        "EN": "EPV color variable slot 1. 0=don't use EPV color, use fixed color1/color2.",
        "ZH": "EPV 特效颜色变量插槽1。0=不使用 EPV 颜色，用固定 color1/color2。",
    },
    ("LIGHTNING", "EPVColorSlot2"): {
        "EN": "EPV color variable slot 2. 0=don't use EPV color.",
        "ZH": "EPV 特效颜色变量插槽2。0=不使用 EPV 颜色。",
    },
    ("LIGHTNING", "unkn05_20"): {
        "EN": "⚠ Caution: do NOT set to 0 (possible crash). Guessed memory layout / render "
              "batch related. Default 96.",
        "ZH": "⚠ 谨慎：不要归0（可能崩溃）。推测与内存布局/渲染批次相关。默认 96。",
    },
    ("LIGHTNING", "unkn05_21"): {
        "EN": "⚠ DO NOT MODIFY. 0xCCCCCD00 = uninitialized-memory fill pattern / engine "
              "internal pointer. Modifying crashes the game.",
        "ZH": "⚠ 禁止修改。0xCCCCCD00 = 未初始化内存填充值/引擎内部指针，修改导致崩溃。",
    },
    ("LIGHTNING", "unkn05_22"): {
        "EN": "⚠ DO NOT MODIFY. Setting to 0 crashes the game; engine-internal key system "
              "parameter (likely pointer/struct-ref table with unkn05_23/24).",
        "ZH": "⚠ 禁止修改。归0直接崩溃；引擎内部关键系统参数（疑与 unkn05_23/24 同属指针/结构体表）。",
    },
    ("LIGHTNING", "unkn05_23"): {
        "EN": "⚠ DO NOT MODIFY. Modifying crashes the game; engine-internal pointer / "
              "struct reference.",
        "ZH": "⚠ 禁止修改。修改导致崩溃；引擎内部指针/结构体引用。",
    },
    ("LIGHTNING", "unkn05_24"): {
        "EN": "⚠ DO NOT MODIFY. Modifying crashes the game; engine-internal pointer / "
              "struct reference.",
        "ZH": "⚠ 禁止修改。修改导致崩溃；引擎内部指针/结构体引用。",
    },
    ("LIGHTNING", "inflectionPointCount"): {
        "EN": "Main-bolt 1st-layer inflection point count (default 9). 0=no disappear but "
              "stuttery motion; 1≈straight; 200=dense coiled ball. Low=straight+stutter, "
              "high=complex+smooth. Pairs with inflectionPointCount2 (both layers).",
        "ZH": "主线第一层拐点数量（默认 9）。0=不消失但运动顿挫；1≈直线；200=密集螺旋团。"
              "低=变直+顿挫，高=复杂+丝滑。与 inflectionPointCount2 双层叠加，任一过低都顿挫。",
    },
    ("LIGHTNING", "uInflectionAngleLimit"): {
        "EN": "U inflection angle limit (default 14). Small=distribution收束 near straight "
              "(complexity unaffected); large=wide random spread + complexity drops (side "
              "effect). Subtle/gentle vs vInflectionAngleLimit. Negative ~ positive.",
        "ZH": "倾角限制（默认 14）。小=分布收束趋直线（复杂度不变）；大=分布范围大、随机感强、"
              "复杂度降低（高值副作用）。影响细腻温和（v 版影响更大）。正负相近。",
    },
    ("LIGHTNING", "uInflectionAngleLimitJitter"): {
        "EN": "Random jitter on uInflectionAngleLimit (default 4).",
        "ZH": "倾角限制随机抖动（默认 4）。",
    },
    ("LIGHTNING", "vInflectionAngleLimit"): {
        "EN": "V inflection angle limit (default 0.9). Same role as uInflectionAngleLimit "
              "but STRONGER/more visible. Use u for coarse, v for fine control. Negative ~ "
              "positive.",
        "ZH": "弯曲角极限（默认 0.9）。与倾角限制功能相同但影响更大更明显。u 粗调、v 精调。正负相近。",
    },
    ("LIGHTNING", "vInflectionAngleLimitJitter"): {
        "EN": "Random jitter on vInflectionAngleLimit (default 0).",
        "ZH": "弯曲角极限随机抖动（默认 0）。",
    },
    ("LIGHTNING", "inflectionPointCount2"): {
        "EN": "Main-bolt 2nd-layer inflection point count (default 10) — controls the MAIN "
              "bolt (not branches). -1=main bolt vanishes. Stacks with inflectionPointCount "
              "(dual-layer system); either too low → stutter.",
        "ZH": "主线第二层拐点数量（默认 10）——控制主线（非分支）。-1=主线消失。"
              "与 inflectionPointCount 双层叠加，任一过低都顿挫。",
    },
    ("LIGHTNING", "uInflectionAngleLimit2"): {
        "EN": "Guessed 2nd-layer U angle limit (default 2, untested).",
        "ZH": "推测第二层倾角范围（默认 2，待测）。",
    },
    ("LIGHTNING", "uInflectionAngleLimitJitter2"): {
        "EN": "Guessed jitter on uInflectionAngleLimit2 (default 0, untested).",
        "ZH": "推测 uInflectionAngleLimit2 的抖动（默认 0，待测）。",
    },
    ("LIGHTNING", "vInflectionAngleLimit2"): {
        "EN": "Guessed 2nd-layer V angle limit (default 0.6, untested).",
        "ZH": "推测第二层弯曲角范围（默认 0.6，待测）。",
    },
    ("LIGHTNING", "vInflectionAngleLimitJitter2"): {
        "EN": "Guessed jitter on vInflectionAngleLimit2 (default 0, untested).",
        "ZH": "推测 vInflectionAngleLimit2 的抖动（默认 0，待测）。",
    },
    ("LIGHTNING", "glow"): {
        "EN": "Main-bolt glow (default 0.6). 0=none, larger=stronger halo. Negative=main "
              "bolt turns black (branches unaffected — main/branch glow are independent).",
        "ZH": "主线发光（默认 0.6）。0=无，越大辉光越强。负数=主线变黑（支线不受影响——"
              "主/支发光系统独立，支线见 unkn07_09）。",
    },
    ("LIGHTNING", "glowJitter"): {
        "EN": "Random jitter on glow (default 0.4). Key for flicker — near/over glow value, "
              "some bolts dim to ~0 (simulates unstable real lightning halo).",
        "ZH": "发光随机抖动（默认 0.4）。模拟真实闪电不稳定光晕的关键——接近/超过 glow 时部分闪电"
              "亮度趋0，明显忽明忽暗。",
    },
    ("LIGHTNING", "length"): {
        "EN": "Main-bolt total length (default 70).",
        "ZH": "闪电主线总长度（默认 70）。",
    },
    ("LIGHTNING", "lengthJitter"): {
        "EN": "Random length jitter (default 140 > base 70 → large per-bolt variation). "
              "0=all bolts identical length.",
        "ZH": "长度随机抖动（默认 140，大于基础 70 → 长短差异极大）。0=所有闪电长度一致。",
    },
    ("LIGHTNING", "width"): {
        "EN": "Bolt line width (default 7).",
        "ZH": "闪电线条宽度（默认 7）。",
    },
    ("LIGHTNING", "widthJitter"): {
        "EN": "Random width jitter (default 6). 0=all bolts identical width.",
        "ZH": "宽度随机抖动（默认 6）。0=所有闪电宽度一致。",
    },
    ("LIGHTNING", "startWidth"): {
        "EN": "Start width (default 1). Gradient coefficient affecting the WHOLE main bolt's "
              "width+glow, strongest at start, decaying to the end. Does NOT affect "
              "branches. Set to 0 → main bolt vanishes, only branches remain (cleanest "
              "main-bolt off switch).",
        "ZH": "开始宽度（默认 1）。渐变系数，影响整条主线的宽度+辉光，起始端最强、向末端递减。"
              "不影响支线。归0=主线消失只留支线（最干净的主线开关）。",
    },
    ("LIGHTNING", "uvRepetitionStart"): {
        "EN": "UV repetition start (default 1). 0=lightning disappears (bad UV); large=texture "
              "stretched/repeated along the bolt (knot look), more segments. Geometry "
              "unaffected, texture-only.",
        "ZH": "UV 重复开始（默认 1）。0=闪电消失（UV 异常）；越大贴图沿绳方向拉伸重复、段数增多"
              "（绳结感）。不影响几何形态，纯贴图效果。",
    },
    ("LIGHTNING", "endWidth"): {
        "EN": "End width (default 1). Stretches main-bolt texture width near the end "
              "(bottom/end影响更大). Geometry unaffected; does not affect branches.",
        "ZH": "结束宽度（默认 1）。拉伸主线末端贴图宽度（末端影响更大，上下不对称）。"
              "不影响几何形态，不影响支线。",
    },
    ("LIGHTNING", "uvRepetitionEnd"): {
        "EN": "UV repetition end (default 0). Non-0=bolt splits into segment pieces (segment "
              "split look, vs uvRepetitionStart's knot look). Geometry unaffected.",
        "ZH": "UV 重复结束（默认 0）。非0=闪电变成数段线段（线段分割感，区别于 uvRepetitionStart"
              "的绳结感）。不影响几何形态。正负相近。",
    },
    ("LIGHTNING", "unkn05_45"): {
        "EN": "⚠ Caution: do NOT set to 0 (possible crash). No visible change at 95/97/100/50. "
              "Default 96.",
        "ZH": "⚠ 谨慎：不要归0（可能崩溃）。测 95/97/100/50 无明显变化。默认 96。",
    },
    ("LIGHTNING", "unkn05_46"): {
        "EN": "⚠ DO NOT MODIFY. 0xCCCCCC00 = uninitialized-memory fill / engine internal "
              "pointer. Modifying crashes the game.",
        "ZH": "⚠ 禁止修改。0xCCCCCC00 = 未初始化内存填充值/引擎内部指针，修改导致崩溃。",
    },
    ("LIGHTNING", "unkn05_47"): {
        "EN": "Branch lightning count A (branchLightningCount, default 1). 0=sharply fewer "
              "(not gone); 10/100=more; ≥500=invisible + GLOBAL render crash (all scene FX "
              "flicker). ⚠ Negative crashes. Safe range 0~100.",
        "ZH": "支路闪电数量A（默认 1）。0=锐减但不消失；10/100=增多；≥500=不可见+触发全局渲染崩溃"
              "（场景所有特效闪烁）。⚠ 负数崩溃。安全范围 0~100。",
    },
    ("LIGHTNING", "unkn05_48"): {
        "EN": "Branch lightning count B (branchLightningCountB, default 1). Affects main+branch "
              "render layer; too high=local render glitch (distance-limited, FX flicker when "
              "near, occasionally visible per viewing angle).",
        "ZH": "支路闪电数量B（默认 1）。同时影响主/支渲染层级；过高=局部渲染层级异常"
              "（受距离限制，越近影响越大，特定视角偶尔可见）。",
    },
    ("LIGHTNING", "unkn06"): {
        "EN": "[0]=branch double-mode flag (branchDoubleModeFlag): 0=1 branch per point, "
              "non-0=2 per point (switch). [1]=branch complexity & flow mode "
              "(branchComplexityAndFlowMode, default 3): controls branch inflection count + "
              "sine freq; larger activates dynamic flow. ⚠ [1] negative crashes.",
        "ZH": "[0]=支路双倍模式标志：0=每点 1 条分支，非0=每点 2 条（开关）。"
              "[1]=支路复杂度与流动模式（默认 3）：控制分支拐点数+正弦频率，增大激活动态流光。"
              "⚠ [1] 负数崩溃。",
    },
    ("LIGHTNING", "radiusLimit"): {
        "EN": "Branch spread max radius (default 5). 0=收束 but not fully gone (other params "
              "contribute); 250=huge sphere/box spread. Positive ~ negative.",
        "ZH": "分支扩散最大半径（默认 5）。0=收束但未完全消失（受 unkn05_06 等影响）；"
              "250=球/方形大范围包围。正负相同。",
    },
    ("LIGHTNING", "radiusLimitJitter"): {
        "EN": "Random jitter on radiusLimit (default 4). Even at 0, branches don't fully "
              "collapse to a line (other params contribute).",
        "ZH": "半径极限随机抖动（默认 4）。归0 仍不能让分支完全收束成线（受其它参数共同影响）。",
    },
    ("LIGHTNING", "unkn07_02"): {
        "EN": "Branch inflection angle limit (branchInflectionAngleLimit, default 0.8). Large "
              "→ branch complexity drops to ~1 inflection + bigger spread. BRANCH-ONLY "
              "(branch counterpart of vInflectionAngleLimit). Positive ~ negative.",
        "ZH": "支线弯曲角极限（默认 0.8）。大=支线复杂度降为约 1 个拐点+扩散增大。仅影响支线"
              "（= vInflectionAngleLimit 的支线版）。正负相近。",
    },
    ("LIGHTNING", "unkn07_03"): {
        "EN": "Random jitter on unkn07_02 (branch-only, default 0). Positive ~ negative.",
        "ZH": "支线弯曲角极限抖动（仅影响支线，默认 0）。正负相近，可与 unkn07_02 叠加。",
    },
    ("LIGHTNING", "unkn07_04"): {
        "EN": "Branch complexity/flow mode B switch (branchComplexityFlowModeB, default 0). "
              "0=off (unkn07_05 inert); 1~150=on (recommended); >150 affects GLOBAL FX "
              "flicker. ⚠ Negative crashes. Also feeds complexity calc; pair high 07_04 + "
              "moderate 07_05 for arc-flow look.",
        "ZH": "支线复杂度流动模式B开关（默认 0）。0=关（unkn07_05 无效）；1~150=开（建议）；"
              ">150 影响全局闪烁。⚠ 负数崩溃。数值也参与复杂度计算；高 07_04+适中 07_05=电弧流动扩散。",
    },
    ("LIGHTNING", "unkn07_05"): {
        "EN": "Branch complexity/spread randomness (default 0.1). Requires unkn07_04≥1. High "
              "values increase spread/randomness (apparent complexity drops to big simple "
              "folds at 100+, ~unkn07_02=800).",
        "ZH": "支线复杂度/扩散范围随机性（默认 0.1）。需 unkn07_04≥1 才生效。值越大扩散/随机越强"
              "（100+ 时趋向大范围简单折线，≈unkn07_02=800）。",
    },
    ("LIGHTNING", "unkn07_06"): {
        "EN": "Random jitter on unkn07_05 (default 0.2). Requires unkn07_04≥1.",
        "ZH": "unkn07_05 的随机抖动（默认 0.2）。需 unkn07_04≥1 才生效。",
    },
    ("LIGHTNING", "unkn07_07"): {
        "EN": "Reserved. No visible change at positive/negative values.",
        "ZH": "保留字段。测正负数值均无明显变化。",
    },
    ("LIGHTNING", "unkn07_08"): {
        "EN": "Reserved. No visible change across many values.",
        "ZH": "保留字段。测多个数值均无明显变化。",
    },
    ("LIGHTNING", "unkn07_09"): {
        "EN": "Branch glow (branchGlow, default 1). Larger=brighter branches; negative=branch "
              "turns black (main bolt unaffected). Branch counterpart of glow.",
        "ZH": "支线发光（默认 1）。越大支线越亮；负数=支线变黑（主线不受影响）。对应主线 glow。",
    },
    ("LIGHTNING", "unkn07_10"): {
        "EN": "Branch glow jitter (branchGlowJitter, default 0). Non-0=per-branch brightness "
              "flicker. Branch counterpart of glowJitter.",
        "ZH": "支线发光抖动（默认 0）。非0=支线亮度随机闪烁。对应主线 glowJitter。",
    },
    ("LIGHTNING", "branchLength"): {
        "EN": "Branch length (default 30). 0=branches gone; negative=direction reversed. "
              "Branch inflection/sine are independent of main bolt (stay near-straight "
              "unless driven by unkn07_04/05). Branches never extend in the main's forward "
              "direction (only sideways/backward).",
        "ZH": "支路长度（默认 30）。0=分支消失；负数=方向反转。分支拐点/正弦频率不受主线影响、"
              "趋直线（除非配合 unkn07_04/05）。分支永不朝主干正向延伸，只向侧/反向生成。",
    },
    ("LIGHTNING", "branchLengthJitter"): {
        "EN": "Random branch length jitter (default 20).",
        "ZH": "支路长度随机抖动（默认 20）。",
    },
    ("LIGHTNING", "unkn07_13"): {
        "EN": "Branch start width (default 6). Stretches branch texture start width. "
              "Counterpart of main startWidth. Positive ~ negative.",
        "ZH": "支线开始宽度（默认 6）。拉伸支线起始端贴图宽度。对应主线 startWidth。正负相同。",
    },
    ("LIGHTNING", "unkn07_14"): {
        "EN": "Branch end width (default 4). Counterpart of main endWidth.",
        "ZH": "支线结束宽度（默认 4）。对应主线 endWidth。",
    },
    ("LIGHTNING", "unkn07_15"): {
        "EN": "Branch start width jitter (default 1). Branch-only (no main counterpart).",
        "ZH": "支线开始宽度抖动（默认 1）。支线独有，主线无对应。",
    },
    ("LIGHTNING", "unkn07_16"): {
        "EN": "Branch UV repetition start (default 1). More segment splits, concentrated "
              "near start. Texture-only. Counterpart of uvRepetitionStart.",
        "ZH": "支线 UV 重复开始（默认 1）。分割点增多、集中在起始段。纯贴图效果。对应主线 "
              "uvRepetitionStart。正负相近。",
    },
    ("LIGHTNING", "unkn07_17"): {
        "EN": "Branch UV repetition end (default 1). Segment splits concentrated near the "
              "end (opposite of unkn07_16). Counterpart of uvRepetitionEnd.",
        "ZH": "支线 UV 重复结束（默认 1）。分割点集中在结束段（与 unkn07_16 位置相反）。"
              "对应主线 uvRepetitionEnd。",
    },
    ("LIGHTNING", "unkn07_18"): {
        "EN": "Branch end width jitter (default 1). Branch-only (no main counterpart).",
        "ZH": "支线结束宽度抖动（默认 1）。支线独有，主线无对应。",
    },
    ("LIGHTNING", "unkn07_19"): {
        "EN": "⚠ DO NOT MODIFY. Extreme float (~1.3e-43); guessed engine pointer/special flag.",
        "ZH": "⚠ 禁止修改。极端浮点（约 1.3e-43）；推测引擎内部指针/特殊标志。",
    },
    ("LIGHTNING", "unkn07_20"): {
        "EN": "⚠ DO NOT MODIFY. Extreme float (~-1.35e+08); guessed engine pointer/flag.",
        "ZH": "⚠ 禁止修改。极端浮点（约 -1.35e+08）；推测引擎内部指针/标志。",
    },
    ("LIGHTNING", "unkn07_21"): {
        "EN": "⚠ DO NOT MODIFY. Setting non-0 crashes (alone or with 22/23/26); pointer/"
              "struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃（单独或与 22/23/26 同改）；指针/结构体引用区。",
    },
    ("LIGHTNING", "unkn07_22"): {
        "EN": "⚠ DO NOT MODIFY. Crashes when set non-0; pointer/struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃；指针/结构体引用区。",
    },
    ("LIGHTNING", "unkn07_23"): {
        "EN": "⚠ DO NOT MODIFY. Crashes when set non-0; pointer/struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃；指针/结构体引用区。",
    },
    ("LIGHTNING", "unkn07_24"): {
        "EN": "⚠ DO NOT MODIFY. Extreme float (~4.2e-45); guessed engine pointer.",
        "ZH": "⚠ 禁止修改。极端浮点（约 4.2e-45）；推测引擎内部指针。",
    },
    ("LIGHTNING", "unkn07_25"): {
        "EN": "Reserved. No visible change across many values (default 20).",
        "ZH": "保留字段。测多个数值均无明显变化（默认 20）。",
    },
    ("LIGHTNING", "unkn07_26"): {
        "EN": "⚠ DO NOT MODIFY. Crashes when set non-0 (same region as 21/22/23).",
        "ZH": "⚠ 禁止修改。改非0崩溃（与 21/22/23 同区）。",
    },
    ("LIGHTNING", "unkn07_27"): {
        "EN": "Reserved. No visible change across many values (default 0.5).",
        "ZH": "保留字段。测多个数值均无明显变化（默认 0.5）。",
    },
    ("LIGHTNING", "unkn08"): {
        "EN": "Reserved/padding array — lightning type does not read it (no effect in "
              "exhaustive testing).",
        "ZH": "保留/填充数组——lightning 类型未读取（地毯式测试无任何效果）。",
    },
    ("LIGHTNING", "unkn09"): {
        "EN": "Reserved/padding array (20 floats) — not read by lightning (no effect).",
        "ZH": "保留/填充数组（20 个 float）——lightning 未读取（无效果）。",
    },
    ("LIGHTNING", "unkn10"): {
        "EN": "Reserved/padding array — not read by lightning (no effect).",
        "ZH": "保留/填充数组——lightning 未读取（无效果）。",
    },
    ("LIGHTNING", "unkn11"): {
        "EN": "Reserved/padding array (all-zero, expansion slots) — no effect.",
        "ZH": "保留/填充数组（全零预留位）——无效果。",
    },
    ("LIGHTNING", "unkn12"): {
        "EN": "Reserved/padding array — not read by lightning (no effect).",
        "ZH": "保留/填充数组——lightning 未读取（无效果）。",
    },
    ("LIGHTNING", "unkn13"): {
        "EN": "Reserved/padding array — strongest 'rotation angle' candidate ([0]=360) but "
              "0/90/180/720 all show no effect. Bolt twist is texture/shader, not this.",
        "ZH": "保留/填充数组——曾是最强'旋转角度'候选（[0]=360），但 0/90/180/720 均无效果。"
              "闪电的细微扭转来自贴图/shader，与此无关。",
    },
    ("LIGHTNING", "unkn14"): {
        "EN": "Reserved/padding array — not read by lightning (no effect; [2]=38).",
        "ZH": "保留/填充数组——lightning 未读取（无效果；[2]=38）。",
    },
    ("LIGHTNING", "unkn15"): {
        "EN": "⚠ [0]=-4.3e+08 (0xCD fill pattern, debug-heap uninitialized memory) — DO NOT "
              "MODIFY. Rest of array is reserved/padding (no effect).",
        "ZH": "⚠ [0]=-4.3e+08（0xCD 调试堆未初始化内存填充值）——禁止修改。数组其余为保留/填充（无效果）。",
    },
    ("LIGHTNING", "unkn16"): {
        "EN": "Reserved. No change at 1/100/-1.",
        "ZH": "保留字段。测 1/100/-1 无变化。",
    },

}


# ─────────────────────────────────────────────────────────────────────────────
# 公共查询函数
# ─────────────────────────────────────────────────────────────────────────────

def get_annotation(type_name: str, field_name: str) -> str:
    """
    按 (type_name, field_name) 查注释，并按当前 UI 语言返回字符串。
    type_name 大写（如 "EMITTERSHAPE3D"）；field_name 为 schema ori_name。
    值为 {"EN":.., "ZH":..} 字典，按 i18n.get_lang() 选取，缺语种回退英文。

    若 (type_name, field_name) 有对应的 RE Engine 官方字段名（FIELD_OFFICIAL_NAMES，
    来自 DTI type dump），在注释末尾追加一行权威交叉参考；label / ori_name / 索引均不变。
    无 BT 注释但有官方名时，仅返回官方名行（使 ⓘ 仍可显示）。
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

    official = FIELD_OFFICIAL_NAMES.get((type_name.upper(), field_name))
    if official:
        name, crc = official[0], official[1]
        conf = official[2] if len(official) > 2 else None   # "确认"/"高"/"中"/"低"/None
        from . import i18n
        lang = i18n.get_lang()
        if lang == "ZH":
            tag = "RE 官方字段名"
            if conf and conf != "确认":
                line = f"[{tag}] {conf}可能为 {name}"
            else:
                line = f"[{tag}] {name}"
        else:
            tag = "RE field"
            conf_en = {"高": "high", "中": "medium", "低": "low"}.get(conf or "")
            if conf_en:
                line = f"[{tag}] likely({conf_en}): {name}"
            else:
                line = f"[{tag}] {name}"
        return f"{base}\n{line}" if base else line

    return base
