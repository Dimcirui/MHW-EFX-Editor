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
    Extern 属性在 io_tree 中以不同 type_hash 存储，不在本字典；仅主 attribute 类型有注释。
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
    ("PARENTOPTIONS", "relationPos"): ("mRelationPos[XYZ]", "0xC8E41E1E", "确认"),
    ("PARENTOPTIONS", "relationRot"):       ("mRelationRot[XYZ]", "0x2DAC4052", "确认"),
    ("PARENTOPTIONS", "relationScl"):       ("mRelationScl[XYZ]", "0x1E11460A", "确认"),

    # ── 语义映射（nTimelineParam 动画参数 ↔ schema 字段，按置信度标注）──────────
    # TRANSFORM3D：translate/rotate/resize = 位置/旋转/缩放（XYZ 三连）铁定确认
    ("TRANSFORM3D", "translate"): ("pos[XYZ]", "0x8E8AFE06", "确认"),
    ("TRANSFORM3D", "rotate"):    ("rot[XYZ]", "0xF105BBE3", "确认"),
    ("TRANSFORM3D", "resize"):    ("scl[XYZ]", "0x9486DF23", "确认"),
    # BILLBOARD3D：color = 显示颜色 RGBA（nadao_qian.efx 实测：TIML 从红→蓝紫渐变确认）
    ("BILLBOARD3D", "color"):     ("Color",    "0x58689812", "确认"),
    # BILLBOARD3D：colorRange，与 color 同源自官方 dump 的 nEffect::nTimelineParam::TypeBillboard3D
    ("BILLBOARD3D", "colorRange"): ("ColorRange", "0xC216C23D", "确认"),
    # PLANE：与 BILLBOARD3D 同源自官方 dump 的 nEffect::nTimelineParam::TypePlane，实机确认同一套机制
    ("PLANE", "color"):      ("Color",      "0x58689812", "确认"),
    ("PLANE", "colorRange"): ("ColorRange", "0xC216C23D", "确认"),
    # MESH：scale/rotation → SizeX/Y/Z / RotationX/Y/Z（nadao_qian.efx SizeY 0x531B9E44 实测确认，余轴同理）
    ("MESH", "scale"):            ("SizeX/Y/Z",    "0x241CAED2", "确认"),
    ("MESH", "rotation"):         ("RotationX/Y/Z","0x002FF505",  "确认"),
    # MESH：color/colorRange、emissiveColor/emissiveColorRange 两组 —— 实机组合排除测试确认
    # (2026-07-06)，与官方 dump 里 nEffect::nTimelineParam::TypeMesh 的字段名逐个对上
    ("MESH", "color"):               ("Color",              "0x58689812", "确认"),
    ("MESH", "colorRange"):          ("ColorRange",          "0xC216C23D", "确认"),
    ("MESH", "emissiveColor"):       ("EmissiveColor",       "0x608DCF8D", "确认"),
    ("MESH", "emissiveColorRange"):  ("EmissiveColorRange",  "0x7F2CEB57", "确认"),
    # VELOCITY3D：gravity 名称精确吻合
    ("VELOCITY3D", "gravity"):    ("Gravity", "0x6A5FE3C4", "高"),
    # EMITTERSHAPE3D：rangeXYZ ↔ Range 盒（注释确认定尺寸/范围，升高；2026-07 改名
    # localRotationX/Y/Z 后与 DTI 名 LocalRotationX/Y/Z 直接一致，独立佐证改名）
    ("EMITTERSHAPE3D", "localRotationX"): ("LocalRotationX", "0x701FE225", "中"),
    ("EMITTERSHAPE3D", "localRotationY"): ("LocalRotationY", "0x0718D2B3", "中"),
    ("EMITTERSHAPE3D", "localRotationZ"): ("LocalRotationZ", "0x9E118309", "中"),
    # ⚠ dump 里叫 RangeMin/Max，但 MHW 实机行为是 offset/size（内边界+厚度，用户
    #   2026-07-30 测试确认全形状通用）——名字保留 dump 原文，语义以实测为准。
    ("EMITTERSHAPE3D", "rangeXYZ"):       ("RangeMin/Max[XYZ]", "0x760F3D43", "高"),
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
    ("TRANSFORM3D", "rotationOrder"): {
        "EN": "4 is the most common value. 0-XYZ, 1-YZX, 2-ZXY, 3-ZYX, 4-YXZ, 5-XZY",
        "ZH": "4 为最常见值。0-XYZ，1-YZX，2-ZXY，3-ZYX，4-YXZ，5-XZY",
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
    # ParentOptions (EFX_Subtypes.bt)
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
        "EN": "Formerly spawnLock. Only meaningful when spawnTrack is enabled — after this "
              "many frames, tracking stops and the effect locks to its current position. "
              "0 = always keep tracking.",
        "ZH": "原名 spawnLock。仅在 spawnTrack 启用时生效——达到该帧数后停止追踪，"
              "特效锁定在当前位置。0 = 始终追踪。",
    },
    ("PARENTOPTIONS", "constReleaseJitter"): {
        "EN": "Formerly bleedPos. Jitter paired with lockToPositionFrame.",
        "ZH": "原名 bleedPos。与 lockToPositionFrame 配对的抖动量。",
    },
    ("PARENTOPTIONS", "jointNo"): {
        "EN": "Bone Limitation. The index/serial number of the bone this is bound to. "
              "-1 = not bound to any bone, the most common setting; a bone index is "
              "specific to the model the effect was authored for, so it rarely "
              "transfers when the entry is reused elsewhere.",
        "ZH": "骨骼限制。绑定到的骨骼的序号。−1 = 不绑定任何骨骼，是最常见的设置；"
              "骨骼序号是针对特效原本所属模型的，把 entry 复用到别处时通常不通用。",
    },
    ("PARENTOPTIONS", "unknFlag1"): {
        "EN": "Unknown. Observed: {0:20433, 1:9199}",
        "ZH": "未知。观测：{0:20433, 1:9199}",
    },

    # ─── SPAWN ────────────────────────────────────────────────────────────────
    # ExternSpawn (EFX_Subtypes.bt)；2026-07-26 用户实机测试确认完整 emitter/particle
    # 三层模型（SPAWN属性本身 → emitter实例/轮次 → particle个体），字段名与下方 tooltip
    # 已按测试结果更新，详见 structs.py EXTERN_SPAWN_SCHEMA 行内注释总览。
    ("SPAWN", "emitterStartDelay"): {
        "EN": "Frames to wait before the spawner's very first burst ever fires. "
              "One-time delay applied once at activation — unrelated to burstInterval "
              "or altBurstInterval.",
        "ZH": "发射器有史以来第一次生成前的等待帧数。只在激活时生效一次，跟 burstInterval "
              "/ altBurstInterval 无关。",
    },
    ("SPAWN", "emitterStartDelayJitter"): {
        "EN": "Random jitter added to emitterStartDelay.",
        "ZH": "叠加到 emitterStartDelay 上的随机抖动。",
    },
    ("SPAWN", "emitterRepeatCount"): {
        "EN": "0 = spawner never relocates, bursts continue forever regardless of "
              "burstsPerCycle. Non-zero = added to burstsPerCycle to set total bursts "
              "per cycle before relocating (see burstsPerCycle). Has no jitter of its own.",
        "ZH": "0=发射器永不换位置，无论 burstsPerCycle 是什么都持续生成；非0时与 "
              "burstsPerCycle 相加，决定每轮换位置前的总批次数（见 burstsPerCycle）。"
              "没有自己的随机抖动。",
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
        "EN": "Number of divisions along the horizontal dimension. Applied to the final "
              "shape, after the generation range and sweep angles have shaped it.",
        "ZH": "沿横向维度的等分数量。作用在生成范围与扫描角度定出的最终形状之上。",
    },

    # ─── VELOCITY3D ───────────────────────────────────────────────────────────
    # ExternVelocity3D (EFX_Subtypes.bt)
    ("VELOCITY3D", "baseAxis"): {
        "EN": "Base axis for speed (one of six cardinal axes, not a free direction vector), combined with rotationX/Y/Z to give the final direction. Only meaningful when velocityType=Directional. : 0=left,1=up,2=front,3=right,4=down,5=back — equivalent to the community RE Engine sequel schema's Cartesian AxisType (0=+X,1=+Y,2=+Z,3=-X,4=-Y,5=-Z), since in the game's default coordinate system +X=left, +Y=up, +Z=front. The two descriptions are the same mapping, just phrased differently — not a real disagreement.",
        "ZH": 'speed 的基准轴（六个基准轴之一，不是自由方向向量），与 rotationX/Y/Z 复合得到最终方向。仅在 velocityType=Directional 时有意义。0=左,1=上,2=前,3=右,4=下,5=后——跟社区 RE Engine 续作 schema 的笛卡尔 AxisType（0=+X,1=+Y,2=+Z,3=-X,4=-Y,5=-Z）是同一套映射，因为游戏默认坐标系下 +X=左,+Y=上,+Z=前。两种描述只是措辞不同，不是真的分歧。',
    },
    ("VELOCITY3D", "rotOrder"): {
        "EN": "A rotation-order enum: 0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX. Not the same numeric mapping as TRANSFORM3D's rotation order convention.",
        "ZH": "旋转顺序枚举："
              "0=XYZ,1=XZY,2=YXZ,3=YZX,4=ZXY,5=ZYX。跟 TRANSFORM3D 的旋转顺序惯例不是同一套数值映射。",
    },
    ("VELOCITY3D", "speedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("VELOCITY3D", "velocityType"): {
        "EN": "Decides how the particle's movement DIRECTION is determined (speed always comes "
              "from speed/acceleration; gravity is independent and always applies). "
              "0=Directional (direction from baseAxis + rotation), 1=DirectionalSpread (Vi=(divergence-1)*spawnPos+velocity, normalized, model — "
              "formerly mislabeled \"Normal\"), 2=Radial (always moves outward, rotation/velocity/"
              "divergence have no effect), 3=EmitterMotion (inherits the emitter's own movement; "
              "gated by minMovementThreshold; formerly labeled \"Spread\"). ⚠ Our corpus has also "
              "shown values 4/5 (previously documented as ScreenSpace/Unkn) that a community RE "
              "Engine sequel schema's 4-value enum doesn't include — unreconciled, needs re-check "
              "against the corpus before trusting either side fully.",
        "ZH": '决定粒子运动方向如何确定（速度始终由 speed/acceleration 决定，重力独立于此始终生效）。0=Directional(由 baseAxis + rotation 决定方向)，1=DirectionalSpread(即 Vi=(divergence-1)*生成坐标+velocity 归一化模型，原误标为"Normal")，2=Radial(始终向外运动，rotation/velocity/divergence 均无效)，3=EmitterMotion(继承 emitter 自身移动，受 minMovementThreshold 门控，原标为"Spread")。⚠ 我们语料还观测到 4/5 取值（旧注释里叫 ScreenSpace/Unkn），社区一份 RE Engine 续作 schema 只有 0~3 四态、没有这两个——两边没对上，回查语料前不能全信任何一边。',
    },
    ("VELOCITY3D", "gravity"): {
        "EN": "Gravity. Always applies regardless of velocityType.",
        "ZH": "重力，不论 Velocity Type 如何，始终生效。",
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
    ("SHADERSETTINGS", "unknEnum3_1"): {
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
    # FadeByDepth（实机确认，见 structs.py 注释）
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
    # ExternScaleAnim (EFX_Subtypes.bt)
    ("SCALEANIM", "initialScaleSpeed"): {
        "EN": "Initial expansion speed (the overall scale-in at animation start).",
        "ZH": "初始扩散速度（动画刚进来时的整体缩放）。",
    },

    # ─── ROTATEANIM ───────────────────────────────────────────────────────────
    ("ROTATEANIM", "spinAxisMask"): {
        "EN": "Axis mask (bitmask): bit0=X, bit1=Y, bit2=Z. Controls which axes receive spin.",
        "ZH": "轴掩码（bitmask）：bit0=X，bit1=Y，bit2=Z。控制哪些轴参与自旋。",
    },
    ("ROTATEANIM", "rotationModeMask"): {
        "EN": ': 0=billboard plane rotation system only (billboardRotation + billboardRotationAccel); 1=same + randomized forward/reverse direction; 2=spin velocity system only (spin_velocity + spinAcceleration); 3=same + randomized forward/reverse direction (each axis independently randomized).',
        "ZH": '0=仅启用平面旋转系(billboardRotation+billboardRotationAccel)；1=同上+随机正反向；2=仅启用自旋速度系(spin_velocity+spinAcceleration)；3=同上+随机正反向(每个轴独立随机)。',
    },

    # ─── ALPHACORRECTION ──────────────────────────────────────────────────────
    # AlphaCorrection (EFX_Subtypes.bt)
    ("ALPHACORRECTION", "lowPass"): {
        "EN": "Hard alpha clip threshold (like Photoshop's Threshold tool; field formerly named 'alpha_clip_threshold') — alpha below this value is cut to 0. 0 = no clipping.",
        "ZH": "Alpha 硬裁切阈值（类似 PS 的 Threshold 工具；原字段名 alpha_clip_threshold）——低于此值的 alpha 直接归 0。0 = 不裁切。",
    },
    ("ALPHACORRECTION", "contrast_gamma"): {
        "EN": "Contrast/gamma correction on alpha (field formerly named 'transparentness'). Unbounded — higher values fade out low/mid alpha (edges) while keeping high alpha (core) intact; values can exceed 1, where almost everything fades to transparent.",
        "ZH": "对 alpha 做对比度/伽马修正（原字段名 transparentness）。无上限——值越大，低/中 alpha（边缘）越快变透明，高 alpha（核心）保留；可超过 1，过大时几乎全图变透明。",
    },
    ("ALPHACORRECTION", "unkn3"): {
        "EN": "Unnamed float parameter (BT template mislabels it 'NULL' — it is not a fixed constant). Usually 0 (unset); other values seen roughly in [-3.0, 3.0]. Purpose unknown.",
        "ZH": "未命名的浮点参数（BT 模板误标为 NULL，实际并非恒定值）。通常为 0（未设置）；其余取值大致落在 [-3.0, 3.0] 之间。具体作用未知。",
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
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
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
        "ZH": "语料里恒为 24，可能只是常见的默认值。",
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
    # ExternRgbFire (EFX_Subtypes.bt)
    ("RGBFIRE", "fireColor"): {
        "EN": "Uses the texture's RGB channel — usually the outer glowing edge; also tints the inner smoke color.",
        "ZH": "使用贴图的RGB通道——一般是外缘的荧光色；同时会给内部的烟雾色染色。",
    },
    ("RGBFIRE", "brightness1"): {
        "EN": "Fire color brightness — colors will combine.",
        "ZH": "火焰色亮度——颜色会叠加混合。",
    },
    ("RGBFIRE", "smokeColor"): {
        "EN": "Uses the texture's Alpha channel — usually the inner core color.",
        "ZH": "使用贴图的Alpha通道——一般是内部的核心色。",
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
    ("RGBFIRE", "fireColorParam_useLife"): {
        "EN": "Fire color timing params (fade-in / duration / fade-out).",
        "ZH": "火焰色时序参数（淡入 / 持续 / 淡出）。",
    },
    ("RGBFIRE", "fireColorParam_lifeType"): {
        "EN": "Usually 0. Values 1 and 2 also occur, meaning unknown.",
        "ZH": "通常为 0。另有取值 1 和 2，含义未确认。",
    },
    ("RGBFIRE", "fireColorParam_unkn9"): {
        "EN": 'Setting to 1 kills the fire color. Values 2/8/9 also occur, meaning unknown.',
        "ZH": "设为 1 会消除火焰色。另有取值 2/8/9，含义未确认。",
    },
    ("RGBFIRE", "smokeColorParam_useLife"): {
        "EN": "Smoke color timing params (fade-in / duration / fade-out). Note: even a short duration can tint a persistent effect permanently.",
        "ZH": "烟雾色时序参数（淡入 / 持续 / 淡出）。注意：即使持续时间很短，也可能对常驻特效造成持久染色。",
    },
    ("RGBFIRE", "smokeColorParam_lifeType"): {
        "EN": "Usually 0. Values 1 and 2 also occur, meaning unknown.",
        "ZH": "通常为 0。另有取值 1 和 2，含义未确认。",
    },
    ("RGBFIRE", "smokeColorParam_unkn9"): {
        "EN": 'Setting to 1 kills the smoke color. Values 2/7/8/9 also occur, meaning unknown.',
        "ZH": "设为 1 会消除烟雾色。另有取值 2/7/8/9，含义未确认。",
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
    # PtLife (EFX_Subtypes.bt)
    ("PTLIFE", "status"): {
        "EN": "Determines when the specified Action is triggered, matching the particle's "
              "fade-in / sustain / fade-out lifecycle stages (LIFE.fadeInDuration/duration/"
              "fadeOutDuration). 0=On spawn, 1=Fade in, 2=Sustain, 3=Fade out, 4=On death, "
              "-1=Unknown",
        "ZH": "决定何时触发指定的 Action，对应粒子淡入/持续/淡出三段生命周期"
              "（LIFE.fadeInDuration/duration/fadeOutDuration）。0=生成时，1=淡入时，"
              "2=持续时，3=淡出时，4=死亡时，-1=未知",
    },
    ("PTLIFE", "relationIndex"): {
        "EN": "Action Emitter / Action EFX Index that declares the children",
        "ZH": "声明子级的 Action Emitter / Action EFX 索引",
    },

    # ─── EMITTERBOUNDARY ──────────────────────────────────────────────────────
    # EmitterBoundary — no inline comments in BT

    # ─── FADEBYANGLE ──────────────────────────────────────────────────────────
    # FadeByAngle — no inline comments in BT

    # ─── FADEBYEMITTERANGLE ───────────────────────────────────────────────────
    # FadeByEmitterAngle — cone angle, alpha rate, fade-in range
    # 用户实机确认（2026-07-23）：fadeInStart/fadeInEnd 其实是距离而非角度
    # （量级跟 cone 的 0~360 完全不同，跟 FADEBYDEPTH 同尺度），机制是
    # fadeInStart(远/大值)~fadeInEnd(近/小值) 单段淡入区间——跟 FADEBYDEPTH
    # 不同，这里只有一对值，不是两段近/远分开的区间，故不需要 near/far 前缀。
    ("FADEBYEMITTERANGLE", "fadeInStart"): {
        "EN": "Fade-in start (distance, not angle). Below this distance, gradually appears.",
        "ZH": "淡入起点（是距离不是角度），小于此距离逐渐显现。",
    },
    ("FADEBYEMITTERANGLE", "fadeInEnd"): {
        "EN": "Fade-in end (distance, not angle). Below this distance, fully visible.",
        "ZH": "淡入终点（是距离不是角度），小于此距离完全可见。",
    },

    # ─── NOISE ────────────────────────────────────────────────────────────────
    # Noise — no inline comments in BT

    # ─── UVCONTROL ────────────────────────────────────────────────────────────
    # UVControl (EFX_Subtypes.bt)
    ("UVCONTROL", "uv1_offsetCoef"): {
        "EN": "Multiplies speed every second (UV1)",
        "ZH": "每秒对速度做乘法（UV1）",
    },
    ("UVCONTROL", "uv2_offsetCoef"): {
        "EN": "Multiplies speed every second (UV2)",
        "ZH": "每秒对速度做乘法（UV2）",
    },
    ("UVCONTROL", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },

    # ─── EMITTERSHAPE2D ───────────────────────────────────────────────────────
    # EmitterShape2D — no inline comments in BT

    # ─── RAYCAST ──────────────────────────────────────────────────────────────
    # RayCast (EFX_Subtypes.bt)
    ("RAYCAST", "direction"): {
        "EN": "Ray direction. Same AxisDirection6 enum as VELOCITY3D/RIBBON/RIBBONBLADE: "
              "0=Left, 1=Up, 2=Front, 3=Right, 4=Down, 5=Back. Casting downward to find "
              "the ground is the most common use (4 alone is 36% of all RAYCAST blocks).",
        "ZH": "射线方向。与 VELOCITY3D/RIBBON/RIBBONBLADE 同一套 AxisDirection6 枚举："
              "0=左, 1=上, 2=前, 3=右, 4=下, 5=后。朝下探地面是最常见的用法"
              "（光是 4 就占全部 RAYCAST 块的 36%）。",
    },
    ("RAYCAST", "unknownEnum1"): {
        "EN": "Usually -1; occasionally 0",
        "ZH": "通常为 -1；偶尔为 0",
    },
    ("RAYCAST", "unknownBitmask2"): {
        "EN": "Observed value 256 — may be flag or enum",
        "ZH": "观测值 256 —— 可能是标志或枚举",
    },

    # ─── HOMING ───────────────────────────────────────────────────────────────
    # 字段语义来自全语料 212 个块统计 + 八角探针系统实测（2026-07-30 定稿）。
    # 运动学模型与改名依据见 efx_format/schema/attributes.py 的 Homing schema 注释；
    # 调查过程记在 docs/ATTRIBUTE_BEHAVIOR_NOTES.md。
    # typeFlag/section_length/spacer 是大部分 attribute 都有的头部字段，见下方通用说明。
    ("HOMING", "typeFlag"): {
        "EN": 'Header field present in most attribute types, likely a type/category marker rather than a tunable value. Exact value semantics unknown.',
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数，具体数值"
              "语义未确认。",
    },
    ("HOMING", "section_length"): {
        "EN": "Always 44 across the whole corpus — do not modify",
        "ZH": "全语料恒为 44，请勿修改",
    },
    ("HOMING", "spacer"): {
        "EN": "Always 0xCDCDCD00 — do not modify",
        "ZH": "恒为 0xCDCDCD00，请勿修改",
    },
    ("HOMING", "turnRate"): {
        "EN": "The particle first flies straight at the homing target; the moment it "
              "arrives it gains a velocity perpendicular to its incoming path, then "
              "circles in that plane, returning to the target once per revolution. This "
              "field is the angular rate of that turn, in degrees per second (360 = one "
              "full revolution per second). Orbit radius = speed / turn rate, so higher "
              "values turn tighter and faster.",
        "ZH": "粒子先径直飞向归航目标；到达目标的瞬间获得一个与入射方向垂直的速度，之后"
              "在这个平面内转圈，每绕一圈回到目标点，如此往复。本字段是转弯的角速度，"
              "单位是度/秒（360 = 每秒转一整圈）。轨道半径 = 速度 ÷ 转向速率，所以数值"
              "越大，转得越快、圈子越小。",
    },
    ("HOMING", "initialSpeed"): {
        "EN": "The starting speed of the homing motion, capped by the target speed — a "
              "higher value has no extra effect, the particle simply starts at the target "
              "speed. Below the target speed the orbit starts small and spirals outward. "
              "If this or the target speed is 0 the particle does not move.",
        "ZH": "归航运动的起始速度，上限被终速度钳住——填得比终速度大不会有额外效果，粒子"
              "一开始就以终速度运动。低于终速度时，轨道从小圈开始向外旋开。本字段或终"
              "速度为 0 时，粒子不会运动。",
    },
    ("HOMING", "targetSpeed"): {
        "EN": "The speed the homing motion settles at, which sets the orbit size "
              "(radius = speed / turn rate). Equal to the initial speed, the orbit is a "
              "closed circle; larger than it, the orbit spirals outward and approaches "
              "the size this speed implies. If this or the initial speed is 0 the "
              "particle does not move.",
        "ZH": "归航运动最终稳定到的速度，决定轨道大小（半径 = 速度 ÷ 转向速率）。与起始"
              "速度相等时轨道是严格闭合的圆；大于起始速度时，轨道从小圈向外旋开、逐渐"
              "逼近这个速度对应的大小。本字段或起始速度为 0 时，粒子不会运动。",
    },
    ("HOMING", "forceFieldSpeedScale"): {
        "EN": "The factor applied to particle speed inside the force field's affected "
              "region; only used when the force field mode is Slow Inside or Slow "
              "Outside. 0 stops the particle, 1 leaves the speed untouched, and values "
              "above 1 have no extra effect. Which side of the sphere is affected is set "
              "by the mode.",
        "ZH": "力场作用区域内粒子速度的缩放比例，仅在力场模式为「内部减速」或「外部减速」"
              "时生效。0 = 速度归零，1 = 不缩放，大于 1 没有额外效果。作用在球内还是球外"
              "由力场模式决定。",
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
        "ZH": "力场球体的半径，球心在归航目标上。这个球做什么由力场模式决定。",
    },
    ("HOMING", "homingTarget"): {
        "EN": "Homing target = (homingTarget mod 4): 0=spawn point (emitter pos), "
              "1=model/character origin (feet), 2/3=world origin (map center). Cycles "
              "every 4 (4=spawn, 5=model, …). Motion always tracks the target's "
              "real-time position (not captured once at trigger time). "
              "Official: 0=83%, 1=14%, 2=4%.",
        "ZH": "归航目标 = (homingTarget mod 4)：0=生成点（发射器位置），1=模型/角色原点"
              "（脚下），2/3=世界原点（地图中心）。每 4 循环（4=生成点, 5=模型原点…）。"
              "运动始终指向目标点的**实时**位置（不是触发时捕获定住）。"
              "官方用值：0=83%，1=14%，2=4%。",
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
              "straight, then snaps them back the moment they leave; it also culls "
              "particles born inside, which you can avoid by moving the spawn range "
              "outside the sphere. Slow Inside and Slow Outside scale particle speed by "
              "the force field speed scale, acting inside and outside the sphere "
              "respectively.",
        "ZH": "挂在力场球体（球心=归航目标，半径见力场半径）上的规则。「内部出生剔除」= 在"
              "球内出生的粒子直接消失，从球外飞进来的不受影响。「内部不转向」= 球内不受"
              "转向力、粒子直线滑行，一出球立刻被拉回；球内出生的粒子同样会消失，把生成"
              "范围挪到球外即可避免。「内部减速」和「外部减速」= 用力场速度倍率缩放粒子"
              "速度，前者作用于球内，后者作用于球外。",
    },
    ("HOMING", "unknownEnum1"): {
        "EN": "Almost always 0 (97% of official attributes)",
        "ZH": "几乎恒为 0（官方 97%）",
    },

    # ─── typeFlag/section_length 通用头字段（2026-07-23，19 个类型统一改名）───────
    # 绝大多数 attribute 类型开头都是这两个 4B 字段：field[0]（typeFlag）语料呈小基数
    # 离散分布，疑似类型/分类标记；field[1]（section_length）100% 恒等于「该 attribute
    # 总字节数 - 8」，是引擎自描述的剩余长度标记，不是可调参数（判据见 field_labels.py
    # RESERVED_FILL_FIELDS 注释）。这里补上尚无独立注释的类型。
    ("NOISE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("RIBBON", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("DUMMY", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Always 1 across official data.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。官方语料恒为 1。",
    },
    ("DUMMY", "section_length"): {
        "EN": "Structural remaining-length marker; computed by the engine, not a "
              "tunable parameter — do not modify",
        "ZH": "结构性剩余长度标记，由引擎计算，非可调参数——请勿修改",
    },
    ("FADEBYEMITTERANGLE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Always 0 across official data.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。官方语料恒为 0。",
    },
    ("FADEBYEMITTERANGLE", "section_length"): {
        "EN": "Always 20 across the whole corpus — do not modify",
        "ZH": "全语料恒为 20，请勿修改",
    },
    ("RAYCAST", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("RAYCAST", "section_length"): {
        "EN": "Always 70 across the whole corpus — do not modify",
        "ZH": "全语料恒为 70，请勿修改",
    },
    ("SCREENSPACECOLLISION", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("SCREENSPACECOLLISION", "section_length"): {
        "EN": "Always 28 across the whole corpus — do not modify",
        "ZH": "全语料恒为 28，请勿修改",
    },
    ("SHOVEL", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("SHOVEL", "section_length"): {
        "EN": "Always 62 across the whole corpus — do not modify",
        "ZH": "全语料恒为 62，请勿修改",
    },
    ("PTTRIGGER", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("PTTRIGGER", "section_length"): {
        "EN": "Always 8 across the whole corpus — do not modify",
        "ZH": "全语料恒为 8，请勿修改",
    },
    ("SPAWNBYANGLE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("SPAWNBYANGLE", "section_length"): {
        "EN": "Always 14 across the whole corpus — do not modify",
        "ZH": "全语料恒为 14，请勿修改",
    },
    ("CHECKPUREATTRIBUTE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("CHECKPUREATTRIBUTE", "section_length"): {
        "EN": "Always 32 across the whole corpus — do not modify",
        "ZH": "全语料恒为 32，请勿修改",
    },
    ("SPAWNBYOCCLUSION", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("SPAWNBYOCCLUSION", "section_length"): {
        "EN": "Always 12 in the single official sample observed — do not modify",
        "ZH": "已观测的唯一官方样本中恒为 12——请勿修改",
    },
    ("PARENTSNOW", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("PARENTSNOW", "section_length"): {
        "EN": "Always 72 in the official samples observed — do not modify",
        "ZH": "已观测的官方样本中恒为 72——请勿修改",
    },
    ("OTOMOSNOW", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("OTOMOSNOW", "section_length"): {
        "EN": "Always 76 in the official samples observed — do not modify",
        "ZH": "已观测的官方样本中恒为 76——请勿修改",
    },
    ("FAKEPLANE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("FAKEPLANE", "section_length"): {
        "EN": "Always 52 across the whole corpus — do not modify",
        "ZH": "全语料恒为 52，请勿修改",
    },
    ("FAKEDOF", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: 1~5.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值 1~5。",
    },
    ("STRAINRIBBON", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: 1~13.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值 1~13。",
    },
    # 2026-07-23 第三轮：变长(_custom codec)类型的固定前缀部分同样核实
    ("RGBWATER", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("TURBULENCE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("BILLBOARD3D", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("TUBELIGHT", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Always 0 in the small sample "
              "observed (22 instances).",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。已观测的少量"
              "样本（22 例）中恒为 0。",
    },
    ("TONEMAPFILTER", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Only 1 official sample observed.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。官方语料仅 1 例。",
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
        "EN": 'Meaning unknown. Only 1 official sample observed (value 16); doesn\'t cleanly match the path length (32), the path length without its trailing null (31), or the fixed header size (24), so a possible "byte length excluding the path" reading isn\'t supported by this single data point.',
        "ZH": "含义未确认。官方语料仅 1 例（取值 16）：跟路径长度（32）、去掉末尾 null 的路径长度"
              "（31）、固定头部大小（24）都对不上，单个样本不支持\"路径之外的字节长\"这个猜测。",
    },
    ("TONEMAPFILTER", "unknFixed2_2"): {
        "EN": "Meaning unknown.",
        "ZH": "含义未确认。",
    },
    ("LAYOUT", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。",
    },
    ("MATERIAL", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Unusually stored as a 64-bit value "
              "(most other typeFlag fields are 32-bit) but still shows the same "
              "small-cardinality distribution.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。此字段较特殊，"
              "以 64 位存储（其余大多数 typeFlag 字段为 32 位），但取值分布形态相同（小基数离散）。",
    },
    ("PTBEHAVIOR", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Not the same field as the "
              "per-parameter unkn0 seen elsewhere in this block.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。跟本块内每个"
              "参数各自的 unkn0 是不同字段，不要混淆。",
    },

    # ─── SCREENSPACECOLLISION ─────────────────────────────────────────────────
    # ScreenSpaceCollision (EFX_Subtypes.bt)
    ("SCREENSPACECOLLISION", "lifespan"): {
        "EN": "0=No interaction; higher values = more bounce",
        "ZH": "0=无交互；数值越大反弹越多",
    },

    # ─── SHOVEL ───────────────────────────────────────────────────────────────
    # Shovel — no inline comments in BT for most fields
    # 取值统计依据见 docs/BLOCK_BEHAVIOR_NOTES.md「SHOVEL」节（tools/scan_shovel.py）
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
    # ExternReference — no inline comments in BT

    # ─── DUMMY / RANDOMFIX / MASTERONLY / BLINK / LUMINANCEBLEED / REFRACTION ─
    # No significant inline comments in BT
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
    ("RANDOMFIX", "useRandomSeedTableCount"): {
        "EN": "Number of times this effect draws from the random seed table below.",
        "ZH": "该特效从下方随机种子表中抽取的次数。",
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
        "EN": "Shadow casting bitflag",
        "ZH": "投影位标志",
    },
    ("MESH", "affectedByLight"): {
        "EN": "Which lights affect the mesh. Per-bit meaning unknown.",
        "ZH": "哪些光照会影响该模型。各位含义未知。",
    },

    # ─── RIBBON (fixed part fields) ───────────────────────────────────────────
    ("RIBBON", "material_tesselation_density"): {
        "EN": "Material Repeating Density",
        "ZH": "材质重复密度",
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
    ("RIBBON", "unknBool16_2_1"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "unknBool3a"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "unknBool3b"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "unknBool5"): {
        "EN": "Hides the back half of the ribbon — only the front half renders.",
        "ZH": "隐藏条带的后半部分，只显示前半部分。",
    },
    ("RIBBON", "unknBool7"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "unknBool8"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "flowmapPlayOnce"): {
        "EN": "Plays the flowmap scroll once instead of looping.",
        "ZH": "流动贴图只播放一次，不循环。",
    },
    ("RIBBON", "flowmapReverse"): {
        "EN": "Plays the flowmap scroll backwards. Only takes effect when Play Once is "
              "also enabled.",
        "ZH": "逆向播放流动贴图。仅在同时启用「流动只播放一次」时才生效。",
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
    ("RIBBON", "unknGlobalForceEnable"): {
        "EN": "Master switch for the three global force fields below.",
        "ZH": "下面三个全局力字段的总开关。",
    },
    ("RIBBON", "unknBool28_2"): {
        "EN": "Purpose unknown — appears to layer on top of the global force switch.",
        "ZH": "作用未知——似乎是叠加在全局力开关之上的。",
    },
    ("RIBBON", "unknGlobalForceX"): {
        "EN": 'Force applied to the ribbon from its tail end, along a fixed axis. The three force axes are orthogonal and their directions never change — they follow neither the local rotation nor the TRANSFORM3D rotation. Which way each axis points is unknown.',
        "ZH": '自尾端施加到条带上的力，沿一个固定轴向。三个力的轴向互相正交、方向恒定不变——既不跟随局部旋转，也不跟随 TRANSFORM3D 的旋转。各轴具体指向哪一侧未知。',
    },
    ("RIBBON", "unknGlobalForceY"): {
        "EN": "Force along the vertical axis. A negative value behaves much like gravity. "
              "See unknGlobalForceX for the shared behaviour of this group.",
        "ZH": "沿竖直轴的力。填负值时表现近似重力。这一组的共同行为说明见 unknGlobalForceX。",
    },
    ("RIBBON", "unknGlobalForceZ"): {
        "EN": "Force along a fixed axis. See unknGlobalForceX for the shared behaviour of "
              "this group.",
        "ZH": "沿一个固定轴向的力。这一组的共同行为说明见 unknGlobalForceX。",
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
    ("BILLBOARD3D", "applicationRule"): {
        "EN": 'Packed flags edited via the popup: two mixable toggles (enable flowmap / play once then freeze) plus a 3-way application mode (default / mode 1 / mode 2).',
        "ZH": '打包标志，用弹窗编辑：两个可混合开关（启用流动贴图／播一次后冻结）加一个三选一应用模式（默认／模式1／模式2）。模式具体含义未知。',
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
        "EN": 'Packed flags edited via the popup: two mixable toggles (enable flowmap / play once then freeze) plus a 3-way application mode (default / mode 1 / mode 2).',
        "ZH": '打包标志，用弹窗编辑：两个可混合开关（启用流动贴图／播一次后冻结）加一个三选一应用模式（默认／模式1／模式2）。模式具体含义未知。',
    },
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
              "(displayed color randomly varies between color and colorRange). "
              "(RE Engine's own name for the equivalent field is 'EdgeBlendRange'.)",
        "ZH": "颜色随机范围开关。0=禁用（始终显示 color）；1=启用（最终显示的颜色会在 "
              "color 与 colorRange 之间随机变化）。（RE Engine 里对应字段叫 'EdgeBlendRange'。）",
    },
    ("PLANE", "blendMode"): {
        "EN": "Shader blend mode: 0 = alpha blend (can show black at normal brightness), "
              "1 = additive blend. (RE Engine's own name for the equivalent field is 'AlphaRate'.)",
        "ZH": "着色器混合模式：0=alpha 混合（正常亮度下可显示黑色），1=add 叠加混合。"
              "（RE Engine 里对应字段叫 'AlphaRate'。）",
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
        "EN": "Blade streak's lengthwise edge width. Formerly unkn04.",
        "ZH": "刀光的纵边宽度。原名 unkn04。",
    },
    ("RIBBONBLADE", "contractionSpeed"): {
        "EN": "0=Lingers,  1=Retracts,  ∞=Retracts instantly",
        "ZH": "0=驻留,  1=回缩,  ∞=瞬间回缩",
    },
    ("RIBBONBLADE", "colourTransitionPoint"): {
        "EN": "0=Instantly start transition,  1=Start at the end",
        "ZH": "0=立即开始过渡,  1=在末端开始",
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
        "EN": "Head color. Mostly pure white; occasionally tinted (e.g. blue).",
        "ZH": "头部颜色。大多为纯白，偶见染色（如蓝色）。",
    },
    ("RIBBONBLADE", "head.color2"): {
        "EN": "Head color range. Almost always white (rarely touched).",
        "ZH": "头部颜色范围。几乎恒为白色（很少被使用）。",
    },
    ("RIBBONBLADE", "tailEnd.color1"): {
        "EN": "Tail color. Usually white with varying alpha — commonly used for a fade-out "
              "on the trailing edge rather than a color tint.",
        "ZH": "尾部颜色。通常为白色但 alpha 不同——多用于尾部渐隐效果，而非染色。",
    },
    ("RIBBONBLADE", "tailEnd.color2"): {
        "EN": "Tail color range. Almost always white (rarely touched).",
        "ZH": "尾部颜色范围。几乎恒为白色（很少被使用）。",
    },
    ("RIBBONBLADE", "tailEnd.unkn18_1"): {
        "EN": "Boolean-looking (0/1 across the corpus). Purpose not yet identified.",
        "ZH": "布尔型取值（全语料 0/1）。用途尚未确定。",
    },
    ("RIBBONBLADE", "head.unkn18_1"): {
        "EN": 'Always 0xCD across the whole corpus on the head side (the tailEnd-side counterpart is a real 0/1 boolean).',
        "ZH": '头部侧全语料恒为 0xCD（尾部侧同名字段是真实的 0/1 布尔）。参照 flowmap jitter 字段的先例暴露出来供。',
    },

    # ─── TURBULENCE (fixed part fields) ───────────────────────────────────────
    # Turbulence — no inline comments in BT for non-path fields

    # ─── LIGHTNING (fixed part fields) ────────────────────────────────────────
    # Lightning — no significant inline comments in BT for fixed fields

    # ─── STRAINRIBBON（拔刀链条，社区注释 EFX_Crimson.bt）─────────────────────
    ("STRAINRIBBON", "unknFixed00_2"): {
        "EN": 'Flag byte extracted from what was treated as padding; always 0 in official data so far',
        "ZH": "从原视为占位的字节中拆出的标志位；官方语料中恒为 0（待确认）",
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
        "EN": "Length random jitter",
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
        "EN": "Number of segments the drooping curve (start→end) is divided into, "
              "also the physics node count. Higher = smoother droop; 1 = straight "
              "line with no droop",
        "ZH": "链条起点到终点的下垂曲线被分成的段数，同时也是物理节点数。数值越大下垂"
              "曲线越平滑；1=直线无下垂",
    },
    ("STRAINRIBBON", "uvRepetition"): {
        "EN": "Number of texture repeats along the chain's length. 0=default (most "
              "common value in official data); 1=texture covers the whole chain once; "
              "larger=denser tiling that becomes a smooth line",
        "ZH": "贴图沿链条长度方向重复次数。0=默认（官方语料最常见取值）；1=贴图完整覆盖"
              "整条；越大锯齿越密变光滑线条",
    },
    ("STRAINRIBBON", "widthwiseUVScalingAlpha"): {
        "EN": "Texture widthwise alpha-channel scaling. 0.1=ultra-thin laser line; "
              "1=default (most common value in official data); 5=extreme expansion, "
              "dense texture",
        "ZH": "贴图宽度方向透明通道缩放。0.1=极细激光线状；1=默认（官方语料最常见取值）；"
              "5=极度扩张纹理密集",
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
    ("STRAINRIBBON", "epv_color_slot1"): {
        "EN": "EPV colour slot id for `color`. Non-zero means: take the colour from that slot of the calling .epv instead of the value on this attribute, so editing the local colour has no effect while a slot id is set.",
        "ZH": "`color` 的 EPV 颜色槽位 id。写非 0 就改用调用方 .epv 里对应槽位的颜色，顶掉本属性上的值——所以槽位 id 非 0 时，在这里改颜色是不生效的。",
    },
    ("STRAINRIBBON", "epv_color_slot2"): {
        "EN": "EPV colour slot id for `colorRange`. Same mechanism as epv_color_slot1.",
        "ZH": "`colorRange` 的 EPV 颜色槽位 id，机制同 epv_color_slot1。",
    },
    ("STRAINRIBBON", "angleRelated"): {
        "EN": "Angle-related parameter (per BT); always 360.0 across official data "
              "(full circle), suggesting an unused default rather than an authored value",
        "ZH": "角度相关参数（据 BT）；官方语料中恒为 360.0（整圆），疑为未被使用的默认值",
    },
    ("STRAINRIBBON", "angleRelatedJitter"): {
        "EN": "Jitter for the angle-related parameter (per BT); always 0.0 across "
              "official data",
        "ZH": "角度相关参数的随机偏差（据 BT）；官方语料中恒为 0.0",
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

    # ─── 行为补充（社区实测，世界特效注释解析）────────────────────────────
    # SPAWN（2026-07-26 实机测试重新定型，取代旧的"burst次数"猜测）
    ("SPAWN", "burstsPerCycle"): {
        "EN": "Re-rolled each time the spawner starts a new cycle (new position). "
              "0 = never relocates, bursts continue forever at burstInterval pacing. "
              "1 = bursts use altBurstInterval pacing instead; total bursts this cycle "
              "= emitterRepeatCount. ≥2 = normal burstInterval pacing; total bursts this "
              "cycle = this value + emitterRepeatCount − 1. All bursts in a finite cycle "
              "(including the last) fire at the same pacing selected above — the last "
              "burst's own trigger timing is not special. What IS special is what "
              "happens after the last burst fires: instead of another burst, the "
              "spawner waits for that burst's particles to die (LIFE duration+"
              "fadeOutDuration) and then immediately relocates.",
        "ZH": "发射器每次开始新一轮（换新位置）时重新抽取。0=永不换位置，按 burstInterval "
              "节奏无限生成；1=改用 altBurstInterval 节奏，本轮总批次数=emitterRepeatCount；"
              "≥2=仍用 burstInterval 节奏，本轮总批次数=该值+emitterRepeatCount−1。有限轮次里"
              "包括最后一批在内，全部批次都按上面选中的同一套节奏触发——最后一批本身的触发时机"
              "并无特殊；特殊的是最后一批触发之后：不是再等一次间隔去触发下一批，而是等这批粒子"
              "死亡(按LIFE的duration+fadeOutDuration)后立即换位置。",
    },
    ("SPAWN", "burstsPerCycleJitter"): {
        "EN": "Random jitter added to burstsPerCycle, re-rolled together with it each cycle.",
        "ZH": "叠加到 burstsPerCycle 上的随机抖动，随每轮一起重新抽取。",
    },
    ("SPAWN", "burstInterval"): {
        "EN": "Frames between consecutive bursts within one spawner cycle. Only applies "
              "when burstsPerCycle rolls to 0 or ≥2 — when it rolls to 1, altBurstInterval "
              "is used instead.",
        "ZH": "同一轮发射周期内，连续两次生成批次之间的帧数间隔。仅在 burstsPerCycle 抽到 "
              "0 或 ≥2 时生效；抽到1时改用 altBurstInterval。",
    },
    ("SPAWN", "burstIntervalJitter"): {
        "EN": "Random jitter added to burstInterval.",
        "ZH": "叠加到 burstInterval 上的随机抖动。",
    },
    ("SPAWN", "altBurstInterval"): {
        "EN": "Frames between bursts, used instead of burstInterval specifically when "
              "burstsPerCycle rolls to 1.",
        "ZH": "当 burstsPerCycle 抽到1时，用来代替 burstInterval 的批次间隔帧数。",
    },
    ("SPAWN", "altBurstIntervalJitter"): {
        "EN": "Random jitter added to altBurstInterval.",
        "ZH": "叠加到 altBurstInterval 上的随机抖动。",
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
    ("EMITTERSHAPE3D", "rangeXYZ"): {
        "EN": "Per-axis spawn range, given as offset + size for every shape. Offset is the "
              "inner boundary (the hollow core), size is the thickness of the shell particles "
              "spawn in, so the outer boundary sits at offset + size. Size 0 spawns particles "
              "on the inner surface only.",
        "ZH": "逐轴的生成范围，所有形状都是偏移+尺寸的组合。偏移是内边界（中间的空腔），"
              "尺寸是粒子生成的那层壳的厚度，外边界位于偏移+尺寸处。尺寸为 0 时粒子只在"
              "内边界表面上生成。",
    },
    ("EMITTERSHAPE3D", "scanAngleHorizontal"): {
        "EN": "Horizontal sweep angle.",
        "ZH": "横向扫描角度。",
    },
    ("EMITTERSHAPE3D", "rangeDivideVerticalNum"): {
        "EN": "Number of divisions along the vertical dimension, 0 = continuous. Applied "
              "to the final shape, same as rangeDivideHorizontalNum.",
        "ZH": "沿纵向维度的等分数量，0=连续铺满。跟横向等分数量一样作用在最终形状之上。",
    },
    ("EMITTERSHAPE3D", "radiusEnd"): {
        "EN": "Radius at the far end, as a ratio of the generation range. With radiusOrigin "
              "these form the two ends of the cylinder — set them unequal for a frustum, or "
              "one to 0 for a cone.",
        "ZH": "远端半径，取值是生成范围的比例。与起始半径共同构成圆柱体的两端——两者不等"
              "即为圆台，其中一个为 0 即为圆锥。",
    },
    ("EMITTERSHAPE3D", "radiusOrigin"): {
        "EN": "Radius at the near end, as a ratio of the generation range. Swapping it with "
              "radiusEnd gives the same shape.",
        "ZH": "近端半径，取值是生成范围的比例。与结束半径互换取值得到的形状相同。",
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
        "EN": "Grants particles their initial velocity. Formerly initialVelocity.",
        "ZH": "赋予粒子初速度。原 initialVelocity。",
    },
    ("VELOCITY3D", "speedJitter"): {
        "EN": "Random addend on speed. Formerly initialVelocityJitter.",
        "ZH": "初速度偏差（speed 的随机加数）。原 initialVelocityJitter。",
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
        "EN": "Frames before speed takes effect. Formerly initialVelocityDelay.",
        "ZH": "speed 生效前的延迟帧数。原 initialVelocityDelay。",
    },
    ("VELOCITY3D", "velocityX"): {
        "EN": "Each particle's direction is computed per axis as "
              "V_i = (divergence_i - 1) x i0 + velocity_i, where i0 is that particle's own "
              "spawn coordinate on axis i, then normalized — only the direction is used, the "
              "speed comes from speed/acceleration. velocity is simply the common movement "
              "direction shared by all particles, regardless of where each one spawned.",
        "ZH": "每个粒子的运动方向按下式逐轴算出：V_i =（divergence_i − 1）× i0 + velocity_i，"
              "其中 i0 是该粒子生成时在 i 轴上的坐标；算完再归一化——只取方向，速度大小由"
              "初速度/加速度决定。velocity 可以简单视作全体粒子共同的运动方向，与各自在哪"
              "生成无关。",
    },
    ("VELOCITY3D", "velocityY"): {
        "EN": "See velocityX.",
        "ZH": "见 velocityX。",
    },
    ("VELOCITY3D", "velocityZ"): {
        "EN": "See velocityX.",
        "ZH": "见 velocityX。",
    },
    ("VELOCITY3D", "divergenceX"): {
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
    ("VELOCITY3D", "divergenceY"): {
        "EN": "See divergenceX.",
        "ZH": "见 divergenceX。",
    },
    ("VELOCITY3D", "divergenceZ"): {
        "EN": "See divergenceX.",
        "ZH": "见 divergenceX。",
    },
    # BILLBOARD3D（含本版新拆分字段）
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
        # 原名 randomBrightnessMult；改判定为 jitter（取值范围与 brightness 同量级，非 0~1 比例）。
        "EN": "Jitter paired with brightness.",
        "ZH": "与亮度配对的抖动量。",
    },
    ("BILLBOARD3D", "blendMode"): {
        "EN": "Shader blend mode: 0 = alpha blend (can show black at normal brightness), "
              "1 = additive blend.",
        "ZH": "着色器混合模式：0=alpha 混合（正常亮度下可显示黑色），1=add 叠加混合。",
    },
    # SCALEANIM（社区验证语义：初始整体扩散 + 播放过程逐轴 X/Y/Z 速度/加速度）
    ("SCALEANIM", "initialScaleAccel"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("SCALEANIM", "initialScaleSpeedJitter"): {
        # 原名 NULL/unknFloat；按位置+取值形态判定为 initialScaleSpeed 的 jitter，未实机确认。
        "EN": "Jitter paired with initialScaleSpeed.",
        "ZH": "与初始扩散速度配对的抖动量。未知。",
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
        "EN": "BILLBOARD3D plane rotation (static value; pairs with billboardRotationJitter as "
              "the random). (Was mistyped as int in the template; corrected to float.)",
        "ZH": "BILLBOARD3D 平面旋转（固定值；与 billboardRotationJitter 组成 static/random 一组）。"
              "（原模板误标为 int，已改为 float。）",
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
    # ⚠ = 危险/崩溃字段。
    ("LIGHTNING", "spacer0"): {
        "EN": "Memory-alignment padding (-842150656). Do not edit.",
        "ZH": "内存对齐占位符（-842150656）。请勿编辑。",
    },
    ("LIGHTNING", "unkn02"): {
        "EN": "Memory-alignment padding between color attributes. Do not edit.",
        "ZH": "颜色块之间的内存对齐占位符。请勿编辑。",
    },
    ("LIGHTNING", "unkn03"): {
        "EN": "Memory-alignment padding between color attributes. Do not edit.",
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
    ("LIGHTNING", "unknFixed00_1"): {
        "EN": "Always 108 across official data. Likely a max node count / subdivision "
              "precision cap.",
        "ZH": "官方语料中恒为 108。疑似最大节点数 / 细分精度上限。",
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
        "EN": 'Float (corpus values 0.0/0.4/1.0…100.0); guessed emissive intensity multiplier (unknown).',
        "ZH": "浮点（全语料取值 0.0/0.4/1.0…100.0）；推测是发光强度倍率（未确认）。",
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
        "EN": "Reserved. No visible change at 0/1/10/negative.",
        "ZH": "保留字段。测 0/1/10/负数均无明显变化。",
    },
    ("LIGHTNING", "targetBoneID"): {
        "EN": "Target bone ID (default 200). Lightning extends from origin to this bone.",
        "ZH": "靶骨 ID（默认 200）。闪电从起点延伸到此骨骼位置。",
    },
    ("LIGHTNING", "unknEnum05_16"): {
        "EN": "Reserved. No visible change across many values.",
        "ZH": "保留字段。测多个数值均无明显变化。",
    },
    ("LIGHTNING", "unknFlag05_17"): {
        "EN": "Reserved. No visible change at 1/2/3/5/10/100/1000/negative.",
        "ZH": "保留字段。测 1/2/3/5/10/100/1000/负数均无明显变化。",
    },
    ("LIGHTNING", "EPVColorSlot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("LIGHTNING", "EPVColorSlot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("LIGHTNING", "unknFixed05_20"): {
        "EN": "⚠ Caution: do NOT set to 0 (possible crash). Likely memory layout / render "
              "batch related. Default 96.",
        "ZH": "⚠ 谨慎：不要归0（可能崩溃）。推测与内存布局/渲染批次相关。默认 96。",
    },
    ("LIGHTNING", "unkn05_21"): {
        "EN": "⚠ DO NOT MODIFY. 0xCCCCCD00 = uninitialized-memory fill pattern / engine "
              "internal pointer. Modifying crashes the game.",
        "ZH": "⚠ 禁止修改。0xCCCCCD00 = 未初始化内存填充值/引擎内部指针，修改导致崩溃。",
    },
    ("LIGHTNING", "unknFixed05_22"): {
        "EN": "⚠ DO NOT MODIFY. Setting to 0 crashes the game; engine-internal key system "
              "parameter (likely pointer/struct-ref table with unkn05_23/24).",
        "ZH": "⚠ 禁止修改。归0直接崩溃；引擎内部关键系统参数（疑与 unkn05_23/24 同属指针/结构体表）。",
    },
    ("LIGHTNING", "unknFixed05_23"): {
        "EN": "⚠ DO NOT MODIFY. Modifying crashes the game; engine-internal pointer / "
              "struct reference.",
        "ZH": "⚠ 禁止修改。修改导致崩溃；引擎内部指针/结构体引用。",
    },
    ("LIGHTNING", "unknFixed05_24"): {
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
        "EN": "Second-layer U angle limit (default 2). Exact effect unknown.",
        "ZH": "第二层倾角范围（默认 2）。具体作用未知。",
    },
    ("LIGHTNING", "uInflectionAngleLimitJitter2"): {
        "EN": "Random component of uInflectionAngleLimit2 (default 0). Exact effect "
              "unknown.",
        "ZH": "uInflectionAngleLimit2 的随机分量（默认 0）。具体作用未知。",
    },
    ("LIGHTNING", "vInflectionAngleLimit2"): {
        "EN": "Second-layer V angle limit (default 0.6). Exact effect unknown.",
        "ZH": "第二层弯曲角范围（默认 0.6）。具体作用未知。",
    },
    ("LIGHTNING", "vInflectionAngleLimitJitter2"): {
        "EN": "Random component of vInflectionAngleLimit2 (default 0). Exact effect "
              "unknown.",
        "ZH": "vInflectionAngleLimit2 的随机分量（默认 0）。具体作用未知。",
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
    ("LIGHTNING", "unknFixed05_45"): {
        "EN": "⚠ Caution: do NOT set to 0 (possible crash). No visible change at 95/97/100/50. "
              "Default 96.",
        "ZH": "⚠ 谨慎：不要归0（可能崩溃）。测 95/97/100/50 无明显变化。默认 96。",
    },
    ("LIGHTNING", "unkn05_46"): {
        "EN": "⚠ DO NOT MODIFY. 0xCCCCCC00 = uninitialized-memory fill / engine internal "
              "pointer. Modifying crashes the game.",
        "ZH": "⚠ 禁止修改。0xCCCCCC00 = 未初始化内存填充值/引擎内部指针，修改导致崩溃。",
    },
    ("LIGHTNING", "unknBitmask05_47"): {
        "EN": "Branch lightning count A (branchLightningCount, default 1). 0=sharply fewer "
              "(not gone); 10/100=more; ≥500=invisible + GLOBAL render crash (all scene FX "
              "flicker). ⚠ Negative crashes. Safe range 0~100.",
        "ZH": "支路闪电数量A（默认 1）。0=锐减但不消失；10/100=增多；≥500=不可见+触发全局渲染崩溃"
              "（场景所有特效闪烁）。⚠ 负数崩溃。安全范围 0~100。",
    },
    ("LIGHTNING", "unknFlag05_48"): {
        "EN": "Branch lightning count B (branchLightningCountB, default 1). Affects main+branch "
              "render layer; too high=local render glitch (distance-limited, FX flicker when "
              "near, occasionally visible per viewing angle).",
        "ZH": "支路闪电数量B（默认 1）。同时影响主/支渲染层级；过高=局部渲染层级异常"
              "（受距离限制，越近影响越大，特定视角偶尔可见）。",
    },
    ("LIGHTNING", "unknBitmask06_0"): {
        "EN": "Branch double mode: 0 = one branch per point, non-0 = two per point.",
        "ZH": "支路双倍模式：0=每点 1 条分支，非 0=每点 2 条。",
    },
    ("LIGHTNING", "unknBitmask06_1"): {
        "EN": "Branch complexity and flow mode (default 3). Controls branch inflection "
              "count plus sine frequency; larger values switch on dynamic flow. "
              "⚠ Negative values crash the game.",
        "ZH": "支路复杂度与流动模式（默认 3）。控制分支拐点数与正弦频率，增大则激活动态流光。"
              "⚠ 负数会导致游戏崩溃。",
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
    ("LIGHTNING", "unknFixed07_03"): {
        "EN": "Random jitter on unkn07_02 (branch-only, default 0). Positive ~ negative.",
        "ZH": "支线弯曲角极限抖动（仅影响支线，默认 0）。正负相近，可与 unkn07_02 叠加。",
    },
    ("LIGHTNING", "unknBitmask07_04"): {
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
    ("LIGHTNING", "unknFixed07_08"): {
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
    ("LIGHTNING", "unknFixed07_19"): {
        "EN": "⚠ DO NOT MODIFY. Extreme float (~1.3e-43); guessed engine pointer/special flag.",
        "ZH": "⚠ 禁止修改。极端浮点（约 1.3e-43）；推测引擎内部指针/特殊标志。",
    },
    ("LIGHTNING", "unkn07_20"): {
        "EN": "⚠ DO NOT MODIFY. Extreme float (~-1.35e+08); guessed engine pointer/flag.",
        "ZH": "⚠ 禁止修改。极端浮点（约 -1.35e+08）；推测引擎内部指针/标志。",
    },
    ("LIGHTNING", "unknEnum07_21"): {
        "EN": "⚠ DO NOT MODIFY. Setting non-0 crashes (alone or with 22/23/26); pointer/"
              "struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃（单独或与 22/23/26 同改）；指针/结构体引用区。",
    },
    ("LIGHTNING", "unknFlag07_22"): {
        "EN": "⚠ DO NOT MODIFY. Crashes when set non-0; pointer/struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃；指针/结构体引用区。",
    },
    ("LIGHTNING", "unknEnum07_23"): {
        "EN": "⚠ DO NOT MODIFY. Crashes when set non-0; pointer/struct-ref region.",
        "ZH": "⚠ 禁止修改。改非0崩溃；指针/结构体引用区。",
    },
    ("LIGHTNING", "unknBitmask07_24"): {
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
    ("LIGHTNING", "unknFixed08_0"): {
        "EN": "Always 0 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 0。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unkn09"): {
        "EN": "Reserved/padding array (20 floats) — not read by lightning (no effect).",
        "ZH": "保留/填充数组（20 个 float）——lightning 未读取（无效果）。",
    },
    ("LIGHTNING", "unkn10_0"): {
        "EN": "Lightning does not read it — changing it has no effect.",
        "ZH": "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknEnum10_1"): {
        "EN": "Lightning does not read it — changing it has no effect.",
        "ZH": "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFixed10_3"): {
        "EN": "Always 0 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 0。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unkn11_1"): {
        "EN": "Expansion slot, 0 in almost all official data — no effect.",
        "ZH": "预留位，官方语料中绝大多数为 0——无效果。",
    },
    ("LIGHTNING", "unknFixed12_0"): {
        "EN": "Always 0 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 0。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknAngle13_0"): {
        "EN": "Angle value, 360 in almost all official data. The closest thing to a "
              "'rotation angle' in this block, but 0/90/180/720 all look identical — the "
              "slight twist of a bolt comes from the texture/shader, not from here.",
        "ZH": "角度值，官方语料中绝大多数为 360。本块里最像\"旋转角度\"的一项，但 0/90/180/720 "
              "看上去完全一样——闪电的细微扭转来自贴图/shader，与此无关。",
    },
    ("LIGHTNING", "unknFixed13_1"): {
        "EN": "Always 0 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 0。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFixed13_2"): {
        "EN": "Always 0 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 0。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknEnum13_3"): {
        "EN": "Almost always 0 across official data (rarely 2 or 3). Lightning does not "
              "read it — changing it has no effect.",
        "ZH": "官方语料中绝大多数为 0（罕见 2 或 3）。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFixed13_4"): {
        "EN": "Always 1 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 1。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFixed13_5"): {
        "EN": "Always 1 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 1。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFixed14_2"): {
        "EN": "Always 38 across official data. Lightning does not read it — changing it "
              "has no effect.",
        "ZH": "官方语料中恒为 38。lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknEnum16"): {
        "EN": "Reserved. No change at 1/100/-1.",
        "ZH": "保留字段。测 1/100/-1 无变化。",
    },

    # -----------------------------------------------------------------------
    # 批量生成：BOOLEAN/NORMALIZED/PERCENTAGE/ENUM 常见取值提示
    # 来源：stats/field_classification.json（confidence>=0.6），仅提示"通常取值"，
    # 不代表字段被锁定为该范围/取值——语料未覆盖到的其他取值同样合法。
    # -----------------------------------------------------------------------
    # ALPHACORRECTION 的头部槽位 schema 名仍是 unkn0（其它类型都叫 typeFlag）。
    ("ALPHACORRECTION", "unkn0"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common range: 1~11 (rare outliers up to 45).",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见范围 "
              "1~11（个别情况可达 45）。",
    },
    ("ALPHACORRECTION", "unknFlag2"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("BILLBOARD2D", "scaleJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("BILLBOARD2D", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [1, 5, 6, 7, 8, 10].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 5, 6, 7, 8, 10]。",
    },
    ("BILLBOARD2D", "applicationRule"): {
        "EN": "Enum. Common values: [0, 4, 12, 32]. 4=Flowmap animates continuously "
              "(loops). 12=Flowmap plays once and stops at the end.",
        "ZH": "枚举。常见取值为 [0, 4, 12, 32]。4=流动贴图持续循环流动；"
              "12=流动贴图只播放一次，到终点后停止。",
    },
    ("BILLBOARD2D", "useColorRange"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("BILLBOARD2D", "blendMode"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("BILLBOARD2D", "EPVColorSlot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD2D", "EPVColorSlot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD2D", "flowmapSpeedJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD2D", "flowmapStrength"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD2D", "flowmapStrengthJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD2D", "unknEnum5_1"): {
        "EN": "Common values: [0, 1, 3].",
        "ZH": "常见取值为 [0, 1, 3]。",
    },
    ("BILLBOARD3D", "EPVColorSlot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD3D", "SlotOverride1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD3D", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("BILLBOARD3D", "flowmapSpeedCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD3D", "flowmapSpeedJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("BILLBOARD3D", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("BILLBOARD3D", "flowmapStrengthCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD3D", "flowmapStrengthJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("BILLBOARD3D", "unknEnum5"): {
        "EN": "Common values: [0, 1, 2, 3, 4, 10].",
        "ZH": "常见取值为 [0, 1, 2, 3, 4, 10]。",
    },
    ("BILLBOARD3D", "unknFlag6_0"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("BILLBOARD3D", "unkn6_1"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("BILLBOARD3D", "unkn7"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
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
    ("BLINK", "minAlpha"): {
        "EN": "Lower bound of the flicker range — the blink always spans the full minAlpha~maxAlpha range, not just the edges of it.",
        "ZH": "闪烁摆动范围的下限——闪烁始终会撑满 minAlpha~maxAlpha 之间的整个区间，不只是碰到边缘。",
    },
    ("BLINK", "maxAlpha"): {
        "EN": "Upper bound of the flicker range (pairs with minAlpha).",
        "ZH": "闪烁摆动范围的上限（与 minAlpha 配对使用）。",
    },
    ("BLINK", "lowFreq"): {
        "EN": "Blink speed of the low-frequency channel; adds together with the high-frequency channel. Setting this to 0 does NOT turn the channel off — it freezes it at half of lowFreqAmplitude. Set lowFreqAmplitude to 0 to actually disable it.",
        "ZH": "低频通道的闪烁速度，与高频通道叠加生效。把这里设为 0 并不会关闭该通道——只会让它固定停在 lowFreqAmplitude 一半的位置。要真正关闭该通道，请把 lowFreqAmplitude 设为 0。",
    },
    ("BLINK", "lowFreqAmplitude"): {
        "EN": "Blink depth of the low-frequency channel — the higher, the more pronounced. Set to 0 to fully disable this channel.",
        "ZH": "低频通道的闪烁深度，越大摆动越明显。设为 0 即可彻底关闭这一通道。",
    },
    ("BLINK", "highFreq"): {
        "EN": "Blink speed of the high-frequency channel; adds together with the low-frequency channel. Setting this to 0 does NOT turn the channel off — it freezes it at half of highFreqAmplitude. Set highFreqAmplitude to 0 to actually disable it.",
        "ZH": "高频通道的闪烁速度，与低频通道叠加生效。把这里设为 0 并不会关闭该通道——只会让它固定停在 highFreqAmplitude 一半的位置。要真正关闭该通道，请把 highFreqAmplitude 设为 0。",
    },
    ("BLINK", "highFreqAmplitude"): {
        "EN": "Blink depth of the high-frequency channel — the higher, the more pronounced. Set to 0 to fully disable this channel.",
        "ZH": "高频通道的闪烁深度，越大摆动越明显。设为 0 即可彻底关闭这一通道。",
    },
    ("BLINK", "lowFreqJitter"): {
        "EN": "Per-particle random offset applied to lowFreq, so particles don't blink in sync. Common range: 0~100.",
        "ZH": "对 lowFreq 施加的逐粒子随机偏移，避免多个粒子同步闪烁。常见取值在 0~100 之间。",
    },
    ("BLINK", "lowFreqAmplitudeJitter"): {
        "EN": "Per-particle random offset applied to lowFreqAmplitude. Common range: 0~100.",
        "ZH": "对 lowFreqAmplitude 施加的逐粒子随机偏移。常见取值在 0~100 之间。",
    },
    ("BLINK", "highFreqJitter"): {
        "EN": "Per-particle random offset applied to highFreq, so particles don't blink in sync. Common range: 0~100.",
        "ZH": "对 highFreq 施加的逐粒子随机偏移，避免多个粒子同步闪烁。常见取值在 0~100 之间。",
    },
    ("BLINK", "highFreqAmplitudeJitter"): {
        "EN": "Per-particle random offset applied to highFreqAmplitude. Common range: 0~100.",
        "ZH": "对 highFreqAmplitude 施加的逐粒子随机偏移。常见取值在 0~100 之间。",
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
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 7, 8, 9, 13].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 2, 3, 7, 8, 9, 13]。",
    },
    ("EMITTERSHAPE2D", "shapeType"): {
        "EN": 'Formerly unknFlag20. It is the 2D counterpart of EMITTERSHAPE3D.shapeType: 0=square, 1=circle, 2+=point. Corpus scan (292 samples) has only observed 0/1 so far — the 2+ case is unknown by our data.',
        "ZH": '原 unknFlag20。对应 EMITTERSHAPE3D.shapeType 同一概念：0=方形，1=圆形，2及以上=点。全语料 292 例目前只观测到 0/1，2+ 的情况暂无数据佐证。',
    },
    ("EMITTERSHAPE2D", "rangeDivideAxis"): {
        "EN": "Which axis the square spawn range is subdivided along. 0=Y axis, 1=X axis; the corpus also has 4% with value 2, meaning unknown. 94% of blocks use 0.",
        "ZH": "方形生成范围沿哪个轴细分。0=Y 轴，1=X 轴；语料里还有 4% 取值 2，含义未知。全语料 94% 用 0。",
    },
    ("EMITTERSHAPE2D", "unknFixed22_1"): {
        "EN": "Always 0 across the entire 292-sample corpus.",
        "ZH": "全语料 292 例恒为 0。",
    },
    ("EMITTERSHAPE3D", "rotationOrder"): {
        "EN": "Order the local rotation axes are applied in.",
        "ZH": "局部旋转各轴的应用顺序。",
    },
    ("EMITTERSHAPE3D", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]。",
    },
    ("EMITTERSHAPE3D", "rangeDivideAxis"): {
        "EN": "Which axis the box is subdivided along. Not affected by localRotation.",
        "ZH": "立方体沿哪个轴细分。不受局部旋转影响。",
    },
    ("EMITTERSHAPE3D", "scanAngleVertical"): {
        "EN": "Vertical sweep angle.",
        "ZH": "纵向扫描角度。",
    },
    ("EMITTERSHAPE3D", "unknFlag4"): {
        "EN": "0/1, exact mechanism unclear. Mostly 1.",
        "ZH": "0/1，具体机制不明，大部分情况下取 1。",
    },
    ("EMITTERSHAPE3D", "unknBitmaskRadiusRelated"): {
        "EN": "Enum 0~5, exact mechanism unclear.",
        "ZH": "枚举值 0~5，具体机制不明。",
    },
    ("EMITTERSHAPEMESH", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 4, 5, 6, 7, 9].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
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
        "EN": "Common values: [0, 1, 3, 4146].",
        "ZH": "常见取值为 [0, 1, 3, 4146]。",
    },
    ("EXTERNREFERENCE", "unknEnum1_1"): {
        "EN": "Common values: [0, 1, 2, 4].",
        "ZH": "常见取值为 [0, 1, 2, 4]。",
    },
    ("EXTERNREFERENCE", "unknEnum1_2"): {
        "EN": "Common values: [0, 1, 2, 3, 5].",
        "ZH": "常见取值为 [0, 1, 2, 3, 5]。",
    },
    ("EXTERNREFERENCE", "unkn1_3"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("EXTERNREFERENCE", "unknFlag1_6"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
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
    ("FAKEPLANE", "unknFlag1_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("FAKEPLANE", "unknFlag1_2"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("FAKEPLANE", "unknFlag1_3"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("FAKEPLANE", "unknEnum3"): {
        "EN": "Common values: [1, 2, 4].",
        "ZH": "常见取值为 [1, 2, 4]。",
    },
    ("GUIDE", "initialPositionJitter"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
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
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 5, 6, 7, 8, 9, 10, 12].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
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
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 3, 4, 7].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 2, 3, 4, 7]。",
    },
    ("LIGHTNING", "unknEnum08_1"): {
        "EN": "Common values: [0, 1, 2, 3, 5]."
              " Lightning does not read it — changing it has no effect.",
        "ZH": "常见取值为 [0, 1, 2, 3, 5]。"
              "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFlag10_2"): {
        "EN": "Common values: 0/1."
              " Lightning does not read it — changing it has no effect.",
        "ZH": "常见取值为 0/1。"
              "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unkn11_0"): {
        "EN": "Common range: 0~100."
              " Expansion slot — no effect.",
        "ZH": "常见取值在 0~100 之间。"
              "预留位——无效果。",
    },
    ("LIGHTNING", "unknEnum12_1"): {
        "EN": "Common values: [0, 4]."
              " Lightning does not read it — changing it has no effect.",
        "ZH": "常见取值为 [0, 4]。"
              "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknEnum14_0"): {
        "EN": "Common values: [0, 5]."
              " Lightning does not read it — changing it has no effect.",
        "ZH": "常见取值为 [0, 5]。"
              "lightning 未读取——改动无效果。",
    },
    ("LIGHTNING", "unknFlag14_1"): {
        "EN": "Common values: 0/1."
              " Lightning does not read it — changing it has no effect.",
        "ZH": "常见取值为 0/1。"
              "lightning 未读取——改动无效果。",
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
        "EN": "Common values: [0, 1, 2, 4, 12, 16].",
        "ZH": "常见取值为 [0, 1, 2, 4, 12, 16]。",
    },
    ("MESH", "emissive_saturation_j"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("MESH", "epv_color_slot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("MESH", "epv_color_slot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("MESH", "global_scale_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("MESH", "rotation2"): {
        "EN": "Formerly unkn5_2. A scalar rotation value distinct from the XYZ 'rotation' field above it — angle-like numbers, most commonly -180 or 0 (occasionally -360 or other degree values). Exact axis/purpose unknown.",
        "ZH": '原名 unkn5_2。与上方 XYZ 的 rotation 字段不同，是一个独立的标量旋转值——呈角度状数字，最常见为 -180 或 0（偶见 -360 等其他角度）。具体作用的轴向未知。',
    },
    ("MESH", "rotation2Jitter"): {
        "EN": "Formerly unkn5_3. Jitter paired with rotation2 — most commonly 360 or 0 "
              "(360 reads as 'fully random rotation', matching rotation2's -360 outlier); "
              "occasionally other degree values.",
        "ZH": "原名 unkn5_3。与 rotation2 配对的抖动量——最常见为 360 或 0（360 即"
              "「完全随机旋转」，与 rotation2 偶见的 -360 呼应）；偶见其他角度值。",
    },
    ("MESH", "rotationOrder"): {
        "EN": "Formerly unkn7_2. Exactly 6 observed values (0~5, dominated by 4 at ~88%) — same value shape as EMITTERSHAPE3D's rotationOrder (also dominated by 4), suggesting they may share the same engine-wide rotation-order enum. Exact meaning per value unknown.",
        "ZH": '原名 unkn7_2。恰好观测到 6 种取值（0~5，4 占约 88%）——与 EMITTERSHAPE3D 的 rotationOrder 分布形态相同（同样以 4 为主流值），推测两者可能共用引擎内同一套旋转顺序枚举。各取值具体含义未知。',
    },
    ("MESH", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 8, 9]。",
    },
    ("MESH", "unknFixed0_1"): {
        "EN": "Always 167 across all observed samples — likely a fixed format/version "
              "marker rather than a tunable parameter.",
        "ZH": "观测样本中恒为 167——很可能是固定的格式/版本标记，而非可调参数。",
    },
    ("MESH", "unknBitmask40"): {
        "EN": "Observed values: [0, 1, 2, 3, 4, 5]; overwhelmingly 2 (~92%).",
        "ZH": "观测取值为 [0, 1, 2, 3, 4, 5]；绝大多数为 2（约 92%）。",
    },
    ("MESH", "unknEnum5"): {
        "EN": "Common values: [0, 2, 6, 7].",
        "ZH": "常见取值为 [0, 2, 6, 7]。",
    },
    ("MESH", "unknFixed6_1"): {
        "EN": "Always 0 across all observed samples. Likely reserved/unused.",
        "ZH": "观测样本中恒为 0。可能是保留/未使用字段。",
    },
    ("MESH", "unknEnum7_0"): {
        "EN": "Common values: [0, 1, 2, 3, 180, 4112].",
        "ZH": "常见取值为 [0, 1, 2, 3, 180, 4112]。",
    },
    ("MESH", "unknFlag7_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("NOISE", "main_axis_speed_jitter"): {
        "EN": "Jitter for main_axis_speed. Common range: 0~100. Formerly secondary_axis_speed.",
        "ZH": "main_axis_speed 的抖动。常见取值在 0~100 之间。原名 secondary_axis_speed。",
    },
    ("NOISE", "main_axis_speed2_jitter"): {
        "EN": "Jitter for main_axis_speed2. Common range: 0~100. Formerly secondary_axis_speed2.",
        "ZH": "main_axis_speed2 的抖动。常见取值在 0~100 之间。原名 secondary_axis_speed2。",
    },
    ("NOISE", "teleport_radius_jitter"): {
        "EN": "Jitter for teleport_radius. Formerly smooth_radius_randomized.",
        "ZH": "teleport_radius 的抖动。原名 smooth_radius_randomized。",
    },
    ("NOISE", "teleport_radius2_jitter"): {
        "EN": "Jitter for teleport_radius2. Formerly smooth_radius_randomized2.",
        "ZH": "teleport_radius2 的抖动。原名 smooth_radius_randomized2。",
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
    ("PARENTEMISSIVE", "unkn2"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PARENTEMISSIVE", "unknEnum3"): {
        "EN": "Common values: [0, 1, 2, 9].",
        "ZH": "常见取值为 [0, 1, 2, 9]。",
    },
    ("PARENTEMISSIVE", "unknEnum4"): {
        "EN": "Common values: [0, 1, 4, 9, 13, 15].",
        "ZH": "常见取值为 [0, 1, 4, 9, 13, 15]。",
    },
    ("PARENTEMISSIVE", "unkn8_1"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PARENTEMISSIVE", "unkn8_2"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
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
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[0, 1, 2, 3, 4, 5, 7, 17].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[0, 1, 2, 3, 4, 5, 7, 17]。",
    },
    ("PATHCHAIN", "unkn4_0"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PATHCHAIN", "unkn4_2"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PATHCHAIN", "unkn4_4"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PATHCHAIN", "unkn5_2"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PATHCHAIN", "unknEnum5_7"): {
        "EN": "Common values: [2, 4].",
        "ZH": "常见取值为 [2, 4]。",
    },
    ("PATHCHAIN", "unknFlag6"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("PLANE", "EPVColorSlot1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("PLANE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common range: 1~13 (rare outliers up to 41).",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见范围 "
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
    ("PLANE", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("PLANE", "flowmapSpeedCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PLANE", "flowmapSpeedJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PLANE", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("PLANE", "flowmapStrengthCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PLANE", "flowmapStrengthJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLANE", "heightJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLANE", "brightnessJitter"): {
        # 原名 randomBrightnessMult；同 BILLBOARD3D 的字段位置，PLANE 上的行为未实机确认。
        "EN": "Jitter paired with brightness. Exact behavior on PLANE unknown.",
        "ZH": "与亮度配对的抖动量。在 PLANE 上的具体行为未知。",
    },
    ("PLANE", "unknBitmask5_0"): {
        "EN": "Common values: [0, 1, 2, 3, 4, 6].",
        "ZH": "常见取值为 [0, 1, 2, 3, 4, 6]。",
    },
    ("PLANE", "unknEnum5_1"): {
        "EN": 'Bitmask (bit0 = master toggle, bits 1/2 sub-modes only meaningful when bit0 is on; non-zero values in official data are always odd, e.g. 1/3/5/7). Related to orientation relative to the camera; per-bit meaning unknown.',
        "ZH": '位掩码（bit0 为总开关，bit1/bit2 是仅在 bit0 开启时才有意义的子模式；官方语料非零值恒为奇数，如 1/3/5/7）。与朝向-摄像机的关系有关，各 bit 具体含义未知。',
    },
    ("PLANE", "baseAxis"): {
        "EN": "Same AxisDirection6 enum as VELOCITY3D/FADEBYANGLE (0=left,1=up,2=front,3=right,"
              "4=down,5=back).",
        "ZH": "与 VELOCITY3D/FADEBYANGLE 同一套 AxisDirection6 枚举（0=左,1=上,2=前,3=右,4=下,5=后）。",
    },
    ("PLANE", "rotationOrder"): {
        "EN": "Same rotation-order enum as MESH.rotationOrder (0=XYZ,1=YZX,2=YXZ,3=ZYX,4=ZXY,"
              "5=XZY); overwhelmingly 4(ZXY) in official data, same shape as MESH.rotationOrder.",
        "ZH": "与 MESH.rotationOrder 同一套旋转顺序枚举（0=XYZ,1=YZX,2=YXZ,3=ZYX,4=ZXY,5=XZY）；"
              "官方语料压倒性取值 4(ZXY)，与 MESH.rotationOrder 分布形状一致。",
    },
    ("PLANE", "unknBitmask7_0"): {
        "EN": 'Observed values [0, 1, 2, 3, 4, 8, 32, 33, 36] look like a bitmask (1/2/4/8/32 present, plus combinations 33=32+1, 36=32+4). Per-bit meaning unknown.',
        "ZH": '观测取值 [0, 1, 2, 3, 4, 8, 32, 33, 36] 呈现位掩码特征（含 1/2/4/8/32 及其组合 33=32+1、36=32+4）。各 bit 含义未知。',
    },
    ("PLANE", "unknFlag7_1"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("PLANE", "widthJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLEMISSIVE", "radii_effect_unkn2"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("PLEMISSIVE", "unkn1"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("PLEMISSIVE", "unkn5_1"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("PLEMISSIVE", "unkn5_2"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
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
        "EN": "Genuinely constant: 0 in all 8904 official blocks.",
        "ZH": "确实恒定：官方语料 8904 个块全部为 0。",
    },
    ("PTLIFE", "unknEnum5"): {
        "EN": "Always exactly mirrors relationIndex's -1 sentinel (0 whenever relationIndex "
              "is set, -1 whenever relationIndex is -1; official corpus, 0/8904 mismatches). "
              "Likely the unused upper half of a 32-bit relationIndex slot rather than an "
              "independent value.",
        "ZH": "恒与 relationIndex 的 -1 哨兵值同步（relationIndex 有值时恒为 0，relationIndex "
              "为 -1 时恒为 -1；官方语料 8904 例 0 个例外）。更像是 relationIndex 这个 32 位槽位"
              "里没用到的高 16 位，而非独立取值。",
    },
    ("PTLIFE", "unknFrame0"): {
        "EN": "Common values: [0, 10, 30, 60, 70, 90, 240, 490] — all multiples of 10, consistent with a frame count. No clean match found against the sibling LIFE block's fadeInDuration/duration/fadeOutDuration/timeToDeath in the same entry, so it isn't simply a copy of one of those. Paired with unknFrame0Jitter below, same static/random convention as LIFE.unknFrame/unknFrameJitter; the jitter side is 0 in all 8961 known blocks so its effect is unknown.",
        "ZH": '常见取值为 [0, 10, 30, 60, 70, 90, 240, 490]——全是 10 的倍数，符合帧数特征。跟同一 entry 内 LIFE 块的 fadeInDuration/duration/fadeOutDuration/timeToDeath 都对不上，不是这几个字段的简单复制。与下方 unknFrame0Jitter 配对，同 LIFE.unknFrame/unknFrameJitter 一样是 static/random 惯例；随机一侧在全部 8961 个已知块里恒为 0，实际效果未知。',
    },
    ("PTLIFE", "unknFrame1"): {
        "EN": "Only 1 non-zero occurrence in the official corpus (value 20, alongside "
              "unknFrame0=30 in the same block) — a multiple of 10 like unknFrame0, but too "
              "rare to establish a reliable correlation. Paired with unknFrame1Jitter below, "
              "same static/random convention; the jitter side is 0 in all 8961 known blocks.",
        "ZH": "官方语料里非零仅 1 例（取值 20，同一块里 unknFrame0=30）——跟 unknFrame0 一样是 "
              "10 的倍数，但样本太少建立不了可靠关联。与下方 unknFrame1Jitter 配对，同一套 "
              "static/random 惯例；随机一侧在全部 8961 个已知块里恒为 0。",
    },
    ("PTTRIGGER", "unknEnum2"): {
        "EN": "Common values: [1, 2, 4, 8].",
        "ZH": "常见取值为 [1, 2, 4, 8]。",
    },
    ("RAYCAST", "spacer"): {
        "EN": "Common values: [-4, -3, -2, -1].",
        "ZH": "常见取值为 [-4, -3, -2, -1]。",
    },
    ("REFRACTION", "seeThroughBlend"): {
        "EN": "See-through blend factor, range 0~1. 0 = background content is "
              "completely obscured; 1 = distortion while still seeing through to "
              "the original background content (blended).",
        "ZH": "透视混合系数，取值 0~1。0=背后内容被完全遮挡不可见；1=扭曲的同时，"
              "可以透过看到背后原本内容（混合叠加）。",
    },
    ("REPEATAREA", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [0, 1, 2, 3, 4, 7, 10].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[0, 1, 2, 3, 4, 7, 10]。",
    },
    ("REPEATAREA", "unknEnum4"): {
        "EN": "Common values: [1, 2, 5, 7].",
        "ZH": "常见取值为 [1, 2, 5, 7]。",
    },
    # fire/smoke 的 lighting 两项不再挂 tooltip：标签「火焰受光照 / 烟雾受光照」已经说完，
    # 原先的「作用尚未确认」与新标签矛盾，删除。
    ("RGBFIRE", "unkn4"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RGBWATER", "specularColorParam_keepFrameJitter"): {
        "EN": "Common values: [0, 5, 10, 14, 30, 40, 62].",
        "ZH": "常见取值为 [0, 5, 10, 14, 30, 40, 62]。",
    },
    ("RGBWATER", "sheetColorParam_lighting"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "sheetColorParam_unkn9"): {
        "EN": "Common values: [0, 1, 2, 6, 7, 8].",
        "ZH": "常见取值为 [0, 1, 2, 6, 7, 8]。",
    },
    ("RGBWATER", "waterLerpParam_useLife"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "waterLerpParam_appearFrameJitter"): {
        "EN": "Common values: [0, 5].",
        "ZH": "常见取值为 [0, 5]。",
    },
    ("RGBWATER", "waterLerpParam_lighting"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "specularColorParam_vanishFrameJitter"): {
        "EN": "Common values: [0, 5, 10, 14, 20, 24, 25, 30].",
        "ZH": "常见取值为 [0, 5, 10, 14, 20, 24, 25, 30]。",
    },
    ("RGBWATER", "specularColorParam_lighting"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "specularColorParam_lifeType"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "specularColorParam_unkn9"): {
        "EN": "Common values: [0, 2].",
        "ZH": "常见取值为 [0, 2]。",
    },
    ("RGBWATER", "sheetColorParam_useLife"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RGBWATER", "sheetColorParam_appearFrame"): {
        "EN": "Common values: [0, 5, 10, 15, 25, 40, 50, 60].",
        "ZH": "常见取值为 [0, 5, 10, 15, 25, 40, 50, 60]。",
    },
    ("RGBWATER", "sheetColorParam_appearFrameJitter"): {
        "EN": "Common values: [0, 25].",
        "ZH": "常见取值为 [0, 25]。",
    },
    ("RGBWATER", "unknownFloat"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RGBWATER", "specularColorParam_useLife"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
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
        "EN": "Opacity at the rear end (away from the direction of travel).",
        "ZH": "后端（远离前进方向的一端）的不透明度。",
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
    ("RIBBON", "material_tesselation_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
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
        "EN": "Opacity at the front end (in the direction of travel).",
        "ZH": "前端（前进方向的一端）的不透明度。",
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
        "EN": "Always 1 in observed data. Purpose unknown.",
        "ZH": "观测样本中恒为 1。作用未知。",
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
    ("RIBBON", "unknBitmask22_1"): {
        "EN": "Bitmask over bits 0~6. Per-bit meaning unknown.",
        "ZH": "位 0~6 的位掩码。各位含义未知。",
    },
    ("RIBBON", "unknFlag22_2"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBON", "enableFlowmap"): {
        "EN": "Master switch for the flowmap scroll — the flowmap speed/strength fields and "
              "the play-once/reverse toggles only do anything while this is on.",
        "ZH": "流动贴图的总开关——下面的流动速度／强度以及只播一次／逆向播放等开关，只有"
              "在它开启时才起作用。",
    },
    ("RIBBON", "unkn27_0"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "unkn27_1"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "spawnAnchorOffset"): {
        "EN": "Where along the ribbon's length the spawn point sits, in ribbon-length units. "
              "0 puts the front tip at the spawn point; 1 shifts forward by one full length "
              "so the rear end sits there instead.",
        "ZH": "生成点落在条带长度方向上的位置，以条带自身长度为单位。0=前端贴住生成点；"
              "1=向前偏移一个完整长度，改由后端贴住生成点。",
    },
    ("RIBBON", "uv_map_width"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("RIBBON", "unknBool15"): {
        "EN": "Purpose unknown.",
        "ZH": "作用未知。",
    },
    ("RIBBONBLADE", "NULL9"): {
        "EN": "Common values: [0, 1, 256].",
        "ZH": "常见取值为 [0, 1, 256]。",
    },
    ("RIBBONBLADE", "widthDirection"): {
        "EN": "Direction the streak's width extends toward. AxisDirection6: 0=Left, 1=Up, "
              "2=Forward, 3=Right, 4=Down, 5=Backwards. Same enum as RIBBON.baseAxis "
              "and VELOCITY3D.baseAxis (equivalent to the Cartesian "
              "0=+X,1=+Y,2=+Z,3=-X,4=-Y,5=-Z mapping — in the game's default coordinate system "
              "+X=left, +Y=up, +Z=front). Formerly unkn03.",
        "ZH": "刀光宽度延伸的朝向。AxisDirection6：0=左, 1=上, 2=前, 3=右, 4=下, 5=后。与 RIBBON."
              "baseAxis、VELOCITY3D.baseAxis 是同一套枚举（等价于笛卡尔 "
              "0=+X,1=+Y,2=+Z,3=-X,4=-Y,5=-Z 映射——游戏默认坐标系下 +X=左,+Y=上,+Z=前）。"
              "原名 unkn03。",
    },
    ("RIBBONBLADE", "length"): {
        "EN": "Tail length, only effective when lengthMode=0 (contraction speed is then "
              "fixed internally). Roughly proportional: higher = longer tail. Formerly unkn05_0.",
        "ZH": "拖尾长度，仅当 lengthMode=0 时生效（此时收缩速度固定内置）。近似成正比："
              "值越高拖尾越长。原名 unkn05_0。",
    },
    ("RIBBONBLADE", "unknEnum05_1"): {
        "EN": "Common values: [0, 2, 3, 4, 6, 20].",
        "ZH": "常见取值为 [0, 2, 3, 4, 6, 20]。",
    },
    ("RIBBONBLADE", "unknFlag07_0"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RIBBONBLADE", "lengthMode"): {
        "EN": "Off: tail length is driven by the length field (fixed internal contraction "
              "speed). On: driven by maxLengthLimit + contractionSpeed together "
              "(contractionSpeed=0 means no active contraction unless maxLengthLimit is hit). "
              "Formerly unkn07_1.",
        "ZH": "关：拖尾长度由 length 字段决定（收缩速度固定内置）。开：由 "
              "maxLengthLimit + contractionSpeed 共同决定（contractionSpeed=0 时不主动收缩，"
              "除非到达 maxLengthLimit 上限）。原名 unkn07_1。",
    },
    ("RIBBONBLADE", "unknFlag08"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("RIBBONBLADE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: [1, 2, 4].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
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
    ("RIBBONBLADE", "flowmapSpeed"): {
        "EN": "Flowmap speed. Common range: 0~1. Part of the flowmap quartet "
              "(speed/acceleration/strength/strengthAcceleration). Formerly unkn23.",
        "ZH": "流光贴图速度。常见取值在 0~1 之间。属于 flowmap 四件套"
              "（速度/加速度/强度/强度加速度）之一。原名 unkn23。",
    },
    ("RIBBONBLADE", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("RIBBONBLADE", "flowmapStrength"): {
        "EN": "Flowmap strength. Common range: 0~100. Formerly unkn25.",
        "ZH": "流光贴图强度。常见取值在 0~100 之间。已。原名 unkn25。",
    },
    ("RIBBONBLADE", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("RIBBONBLADE", "flowmapSpeedJitter"): {
        "EN": "Jitter for flowmapSpeed. Formerly NULL5.",
        "ZH": "flowmapSpeed 的抖动。已为 float。原名 NULL5。",
    },
    ("RIBBONBLADE", "flowmapSpeedCoefJitter"): {
        "EN": "Jitter for flowmapAcceleration. Formerly NULL6.",
        "ZH": "flowmapAcceleration 的抖动。已为 float。原名 NULL6。",
    },
    ("RIBBONBLADE", "flowmapStrengthJitter"): {
        "EN": "Jitter for flowmapStrength. Formerly NULL7.",
        "ZH": "flowmapStrength 的抖动。已为 float。原名 NULL7。",
    },
    ("RIBBONBLADE", "flowmapStrengthCoefJitter"): {
        "EN": "Jitter for flowmapStrengthAcceleration. Formerly NULL8.",
        "ZH": "flowmapStrengthAcceleration 的抖动。已为 float。原名 NULL8。",
    },
    ("RIBBONBLADE", "uvRepetition"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("ROTATEANIM", "billboardRotationCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("ROTATEANIM", "billboardRotationCoefJitter"): {
        "EN": "Random component of billboardRotationAccel.",
        "ZH": "billboardRotationAccel 的随机分量。",
    },
    ("ROTATEANIM", "spinSpeedCoefX"): {
        "EN": "Spin acceleration on X, static value (formerly momentum_retention — this "
              "and the following 5 fields were regrouped into X/Y/Z static+random pairs). "
              "Mostly 0.9~1.0.",
        "ZH": "X 轴自旋加速度，固定值（原 momentum_retention——本字段起 6 个字段已重新按 "
              "X/Y/Z 的固定/随机配对分组）。多集中在 0.9~1.0。",
    },
    ("ROTATEANIM", "spinSpeedCoefXJitter"): {
        "EN": "Random component of spinAccelerationX. Mostly 0; occasionally a clean small decimal.",
        "ZH": "spinAccelerationX 的随机分量。多为 0；偶尔是干净的小数。",
    },
    ("ROTATEANIM", "spinSpeedCoefY"): {
        "EN": "Y-axis counterpart of spinAccelerationX (static value).",
        "ZH": "spinAccelerationX 的 Y 轴对应（static 值）。",
    },
    ("ROTATEANIM", "spinSpeedCoefYJitter"): {
        "EN": "Random component of spinAccelerationY.",
        "ZH": "spinAccelerationY 的随机分量。",
    },
    ("ROTATEANIM", "spinSpeedCoefZ"): {
        "EN": "Z-axis counterpart of spinAccelerationX (static value).",
        "ZH": "spinAccelerationX 的 Z 轴对应（static 值）。",
    },
    ("ROTATEANIM", "spinSpeedCoefZJitter"): {
        "EN": "Random component of spinAccelerationZ.",
        "ZH": "spinAccelerationZ 的随机分量。",
    },
    ("ROTATEANIM", "rotateDelayStart"): {
        "EN": "Formerly the last float of the (mis-shifted) spin_acceleration XYZ group — always "
              "reads as 0.0 as float32 (denormal artifact), but as int32 shows clean frame-count "
              "values (5/10/15/20/30/100/512...). Static half of a static/random pair with "
              "rotateDelayStartJitter; likely delay frames before rotation starts.",
        "ZH": "原 spin_acceleration XYZ 分组(错位)的最后一个 float——按 float32 解读恒为 0.0"
              "（denormal 假象），按 int32 解读呈现干净帧数(5/10/15/20/30/100/512...)。是与 "
              "rotateDelayStartJitter 组成的 static/random 一对，疑似旋转开始前的延迟帧数。",
    },
    ("ROTATEANIM", "rotateDelayStartJitter"): {
        "EN": "Formerly unknEnum1_2. Random component of rotateDelayStart; usually 0. Other common "
              "values: [1, 2, 5, 10, 15, 20, 30, 60, 128].",
        "ZH": "原 unknEnum1_2。rotateDelayStart 的随机分量；通常为 0；其余常见取值为 "
              "[1, 2, 5, 10, 15, 20, 30, 60, 128]。",
    },
    ("SCALEANIM", "initialScaleAccelJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "scaleAccelXJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "scaleAccelYJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "scaleAccelZ"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("SCALEANIM", "scaleSpeedXJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SCALEANIM", "scaleSpeedYJitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("SCALEANIM", "scaleSpeedZJitter"): {
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
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 3, 4, 5, 6, 7, 10, 11, 12].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[1, 2, 3, 4, 5, 6, 7, 10, 11, 12]。",
    },
    ("SHADERSETTINGS", "unknEnum1"): {
        "EN": "Always 104 in observed data. Purpose unknown.",
        "ZH": "观测样本中恒为 104。具体作用未知。",
    },
    ("SHADERSETTINGS", "unknFlag2"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("SHADERSETTINGS", "unknBitmask3_0"): {
        "EN": "Observed values: [0, 1, 2, 3]; most commonly 0 or 1.",
        "ZH": "观测取值为 [0, 1, 2, 3]；最常见为 0 或 1。",
    },
    ("SHADERSETTINGS", "unkn4_0"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_1"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_2"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_3"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_4"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_5"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_6"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("SHADERSETTINGS", "unkn4_7"): {
        "EN": "Common values: [0, 15, 80, 100, 200, 250, 300, 500, 1000, 1200].",
        "ZH": "常见取值为 [0, 15, 80, 100, 200, 250, 300, 500, 1000, 1200]。",
    },
    ("SHADERSETTINGS", "unknEnum4_8"): {
        # 取值中两个非哨兵值匹配 jamcrc("Smoke")/jamcrc("Default")，疑似类别/分组名哈希。
        "EN": '-1 = unset. Other values look like name hashes, possibly a category or group identifier. Purpose unknown.',
        "ZH": "-1=未设置。其余取值形似名字哈希，可能是某种类别／分组标识。作用未知。",
    },
    ("SHADERSETTINGS", "unkn4_9"): {
        "EN": "Usually 0; other common values: [-1000, -500, -200, -100, -50, 20, 50, 100, 200].",
        "ZH": "通常为 0；其余常见取值为 [-1000, -500, -200, -100, -50, 20, 50, 100, 200]。",
    },
    ("SHADERSETTINGS", "unkn4_10"): {
        "EN": "Usually 0; other common values: [20, 25, 50, 80, 100, 150, 200, 300, 1000].",
        "ZH": "通常为 0；其余常见取值为 [20, 25, 50, 80, 100, 150, 200, 300, 1000]。",
    },
    ("SHADERSETTINGS", "unkn4_11"): {
        "EN": "Usually 0; other common values: [-200, -100, -50, -20, 50, 80, 100, 150, 200].",
        "ZH": "通常为 0；其余常见取值为 [-200, -100, -50, -20, 50, 80, 100, 150, 200]。",
    },
    ("SHADERSETTINGS", "unknFixed4_12"): {
        "EN": "Always 0.0 in observed data. Purpose unknown.",
        "ZH": "观测样本中恒为 0.0。具体作用未知。",
    },
    ("SHADERSETTINGS", "unkn4_13"): {
        "EN": "Usually 0; other common values: [15, 17, 20, 25, 50, 100, 150, 200, 300].",
        "ZH": "通常为 0；其余常见取值为 [15, 17, 20, 25, 50, 100, 150, 200, 300]。",
    },
    ("SHADERSETTINGS", "unknBitmask4_14"): {
        "EN": "Observed values: [0, 1, 2, 3]; almost always 0.",
        "ZH": "观测取值为 [0, 1, 2, 3]；绝大多数为 0。",
    },
    ("SHADERSETTINGS", "unkn4_15"): {
        "EN": "Usually 0; other common values are large round numbers: "
              "[1, 100, 500, 1000, 2500, 5000, 8000, 10000, -10000].",
        "ZH": "通常为 0；其余常见取值为较大的整数：[1, 100, 500, 1000, 2500, 5000, 8000, 10000, -10000]。",
    },
    ("SHADERSETTINGS", "unknEnum5_0"): {
        "EN": "Common values: [0, 1, 65536, 16777216].",
        "ZH": "常见取值为 [0, 1, 65536, 16777216]。",
    },
    ("SHADERSETTINGS", "unknBitmask5_1"): {
        "EN": "Observed values: [0, 1, 2, 3, 4, 5, 7, 8, 9] (6 never observed); most commonly 0 or 1.",
        "ZH": "观测取值为 [0, 1, 2, 3, 4, 5, 7, 8, 9]（从未出现 6）；最常见为 0 或 1。",
    },
    ("SPAWN", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[2, 3, 4, 5, 6, 7, 8, 9, 10]; overwhelmingly 2.",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
              "[2, 3, 4, 5, 6, 7, 8, 9, 10]；绝大多数为 2。",
    },
    ("SPAWN", "particleSpawnDelay"): {
        "EN": "Extra delay applied independently to each individual particle after its "
              "burst fires, staggering when particles from the same burst actually "
              "become visible. Independent of all emitter-level timing (burstInterval, "
              "burstsPerCycle, altBurstInterval, emitterStartDelay).",
        "ZH": "每个粒子个体独立叠加的额外生成延迟，让同一批次里的粒子实际出现的时间彼此"
              "错开。跟所有 emitter 层面的节奏（burstInterval、burstsPerCycle、"
              "altBurstInterval、emitterStartDelay）无关。",
    },
    ("SPAWN", "particleSpawnDelayJitter"): {
        "EN": "Random jitter added to particleSpawnDelay, rolled independently per particle.",
        "ZH": "叠加到 particleSpawnDelay 上的随机抖动，每个粒子独立抽取。",
    },
    ("SPAWN", "maxParticles"): {
        "EN": 'Soft cap on particles allowed alive at once for this spawner (concurrent count = burst rate × particle lifespan, i.e. duration+fadeOutDuration). Not a lifetime total — bursts are throttled once this cap would be exceeded, and resume in full once earlier particles die off.',
        "ZH": '该发射器同时存活粒子数的软上限。不是终身生成总量——超出上限时本批会被削减，等早前粒子死亡腾出空间后又能满额生成。',
    },
    ("SPAWN", "unknBitmask31"): {
        "EN": "Bitmask over bits 0~5, usually 0. Per-bit meaning unknown.",
        "ZH": "位 0~5 的位掩码，通常为 0。各位含义未知。",
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
    ("STRAINRIBBON", "enableFlowmap"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
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
    ("STRAINRIBBON", "unknEnum06_08_00"): {
        "EN": "Common values: [0, 256].",
        "ZH": "常见取值为 [0, 256]。",
    },
    ("STRAINRIBBON", "unknEnum06_08_01"): {
        "EN": "Common values: [0, 1, 257].",
        "ZH": "常见取值为 [0, 1, 257]。",
    },
    ("STRAINRIBBON", "flowmapSpeedJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("STRAINRIBBON", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("STRAINRIBBON", "flowmapStrength"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },
    ("STRAINRIBBON", "flowmapStrengthJitter"): {
        "EN": "Common values: 0/1.",
        "ZH": "常见取值为 0/1。",
    },
    ("STRAINRIBBON", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("STRAINRIBBON", "flowmapStrengthCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
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
        # 原 unknEnum0_2 int 拆出的唯一真实数据字节；语料样本量小（22 块 / 17 文件）。
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
    ("UVCONTROL", "flowmapSpeedJitter"): {
        "EN": "Jitter for flowmapSpeed. Part of the flowmap octet. Common range: 0~1. "
              "Formerly extraMaterialInitialPositionJitter.",
        "ZH": "flowmapSpeed 的抖动。属于 flowmap 八件套之一。常见取值在 0~1 之间。"
              "原名 extraMaterialInitialPositionJitter。",
    },
    ("UVCONTROL", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("UVCONTROL", "flowmapStrengthJitter"): {
        "EN": "Jitter for flowmapStrength. Part of the flowmap octet. Common range: 0~100. "
              "Formerly opacityJitter.",
        "ZH": "flowmapStrength 的抖动。属于 flowmap 八件套之一。常见取值在 0~100 之间。"
              "原名 opacityJitter。",
    },
    ("UVCONTROL", "enableFlowmap"): {
        "EN": "Master switch for the flowmap scroll. Common values: 0/1. Formerly unknFlag2.",
        "ZH": "流动贴图的总开关。常见取值为 0/1。原名 unknFlag2。",
    },
    ("UVCONTROL", "uv2_enable"): {
        "EN": "Enables the second UV channel. A mod3 mesh may carry two UV sets; this switches on the uv2 group's own offset/scale/speed controls. (Not vertex-animation related.)",
        "ZH": '启用第二套 UV。mod3 网格允许同时存在两套 UV，打开后下面的 uv2 组（偏移/缩放/速度）才生效。（与顶点动画无关。）',
    },
    ("UVSEQUENCE", "playSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
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
        "EN": "Padding byte, always 0 in observed data (part of the loopingEnum "
              "byte layout, see playbackMode/flipCode/direction/loopingOrientation).",
        "ZH": "填充字节，观测样本中恒为 0（属于 loopingEnum 的字节布局，参见 "
              "playbackMode/flipCode/direction/loopingOrientation）。",
    },
    ("UVSEQUENCE", "typeFlag"): {
        "EN": "Header field present in most attribute types, likely a type/category "
              "marker rather than a tunable value. Common values: "
              "[1, 2, 5, 6, 7, 8, 9, 11, 13, 14].",
        "ZH": "大部分 attribute 都有的头部字段，疑似类型/分类标记而非可调参数。常见取值为 "
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
        "EN": "Common values: [0, 1, 2, 5, 16, 20]. Formerly initialVelocityDelay.",
        "ZH": "常见取值为 [0, 1, 2, 5, 16, 20]。原 initialVelocityDelay。",
    },
    ("VELOCITY2D", "movementDelayJitter"): {
        "EN": "Common values: [0, 1, 3, 4, 5, 10, 20]. Formerly initialVelocityDelayJitter.",
        "ZH": "常见取值为 [0, 1, 3, 4, 5, 10, 20]。原 initialVelocityDelayJitter。",
    },
    ("VELOCITY2D", "speedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("VELOCITY2D", "speedCoefJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("VELOCITY2D", "speedJitter"): {
        "EN": "Common range: 0~100. Formerly initialVelocityJitter.",
        "ZH": "常见取值在 0~100 之间。原 initialVelocityJitter。",
    },
    ("VELOCITY2D", "gravityJitter"): {
        "EN": "Common range: 0~1.",
        "ZH": "常见取值在 0~1 之间。",
    },
    ("VELOCITY3D", "minMovementThreshold"): {
        "EN": "Formerly unknFloat/NULL2. Acts as a threshold: only relevant when velocityType=EmitterMotion — the emitter's own velocity must exceed this before it's applied to particles. Mostly 0 (~98% of the corpus); range 0~40 when non-zero.",
        "ZH": '原 unknFloat/NULL2。为阈值：仅在 velocityType=EmitterMotion 时有意义——emitter 自身速度需超过这个阈值才会施加给粒子。语料里多数为 0（约98%）；非零时取值范围 0~40。',
    },
    ("VELOCITY3D", "gravity_jitter"): {
        "EN": "Common range: 0~100.",
        "ZH": "常见取值在 0~100 之间。",
    },

    ("PLANE", "EPVColorSlot2"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("PLEMISSIVE", "epv_color_slot"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("PLSNOW", "epvcolorslot"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("RIBBON", "epvcolor_0"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("RIBBON", "epvcolor_1"): {
        "EN": 'EPV colour slot id. The .epv (Effect Provider) that calls this .efx carries 7 slots; each slot stores colour / brightness style attributes under a self-assigned id. **Non-zero here means: take the attribute from that slot instead of the value on this attribute.** 0 = use the local value, so editing the local colour has no effect while a slot id is set.',
        "ZH": 'EPV 颜色槽位 id。调用本 .efx 的 .epv（Effect Provider）里带 7 个槽位，每个槽位按自定义 id 存着颜色/亮度一类属性。**这里写非 0 就表示：改用对应 id 槽位里的属性，顶掉本属性上的值。** 0 = 用本地值——所以只要槽位 id 非 0，在这里改颜色是不生效的。',
    },
    ("BILLBOARD2D", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("BILLBOARD3D", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("LIGHTNING", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("PLANE", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("RIBBONBLADE", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("STRAINRIBBON", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("RIBBON", "flowmapPath"): {
        "EN": "Flowmap texture path. **This is the flow/distortion map, not the visible artwork** — every UVS-system body pairs it with flowmapSpeed / flowmapStrength. What you actually see comes from UVSEQUENCE's own path. (These files are named *_F_NM.tex, which is why older docs call it a normal map.)",
        "ZH": '流动贴图（flowmap）路径。**这是流动/扰动图，不是看得见的画面** —— UVS 系每个渲染主体都配着 flowmapSpeed / flowmapStrength 一起用。真正显色的图来自 UVSEQUENCE 自己的 path。（这类文件名以 *_F_NM.tex 结尾，旧资料因此误称它为法线贴图。）',
    },
    ("RGBWATER", "colorRate"): {
        "EN": "Overall colour rate, driven by the ColorRate timeline parameter — animating it only works on the A0 (emitter) axis.",
        "ZH": '整体颜色比率。对应 ColorRate 时间线参数，动画只在 A0（发射轴）上生效。',
    },
    ("RGBWATER", "waterLerpGtoB"): {
        "EN": "Blends the water colour from green towards blue, driven by WaterLerpGtoB — by far the most animated parameter on this attribute (50 of the 60 RgbWater tracks in the whole corpus).",
        "ZH": '把水色从绿向蓝插值。对应 WaterLerpGtoB，是本属性最常被做动画的参数（全语料 60 条 RgbWater 轨道里占 50 条）。',
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
    ("RGBWATER", "unknownFloat"): {
        "EN": "Unknown. The only header float with no timeline parameter behind it — the engine declares six float parameters and this attribute has seven floats, so exactly one cannot be animated, and this is it. Mode 0.3 (73%), which does not look like an intensity value.",
        "ZH": '未知。头部唯一一个背后没有时间线参数的 float——引擎只声明了六个 float 参数、本属性有七个 float，恰好有一个不可做动画，就是它。众数 0.3（73%），不像强度量。',
    },
    ("UVSEQUENCE", "uvsPath"): {
        "EN": "Path to the .uvs sequence file — **this is the artwork you actually see**. The .uvs itself is a frame table pointing at a sprite-sheet .tex; playSpeed / patternNo pick which cell plays. Nearly every UVSEQUENCE has one (99% of blocks non-empty).",
        "ZH": '指向 .uvs 序列文件的路径 —— **真正显色的图就是这张**。.uvs 本身是一张帧表，指向序列帧大图（.tex）；playSpeed / patternNo 决定放哪一格。几乎每个 UVSEQUENCE 都填了（全语料 99% 非空）。',
    },
    ("RGBWATER", "cubemapPath"): {
        "EN": "Cube map path for the water surface's environment reflection. The corpus only ever uses two official maps (cm_cube_000_CM / cm_cube_001_CM); 68% of blocks leave it empty. Pairs with brightnessSlot2 — that field is non-zero in 78% of blocks that have a cube map versus 30% of those that don't.",
        "ZH": '水面环境反射用的立方贴图。全语料只用过两张官方图（cm_cube_000_CM / cm_cube_001_CM），68% 的块留空。与 brightnessSlot2 配套：填了贴图的块里该字段 78% 非零，没填的只有 30%。',
    },
    ("TURBULENCE", "tfaPath"): {
        "EN": "Path to the .tfa vector-field file that drives the turbulence. Only five are used across the whole corpus — mostly cm_exMap\\turbulance_000_T and curlnoise_000_T. Effectively always filled (100% of blocks).",
        "ZH": '驱动湍流的 .tfa 向量场文件路径。全语料只用过五张，主要是 cm_exMap\\turbulance_000_T 和 curlnoise_000_T。基本总是填着的（全语料 100%）。',
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
        "ZH": '可选的 .pl 摆位表：一张（子网格序号, XYZ 偏移）列表，把模型的各个部件分别挪位。很少用（全语料 6%），且通常与 .mod3 同目录同名。',
    },
    ("EMITTERSHAPEMESH", "mod3Path"): {
        "EN": "Path to the .mod3 whose surface is used as the emitter shape — particles spawn on this mesh rather than on a primitive.",
        "ZH": '用作发射器形状的 .mod3 路径 —— 粒子从这个网格表面上生成，而不是从基本体上。',
    },
    ("BILLBOARD2D", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("BILLBOARD2D", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("LIGHTNING", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("LIGHTNING", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("RIBBON", "flowmapSpeedCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("RIBBON", "flowmapStrengthCoef"): {
        "EN": 'Per-frame speed multiplier: the corresponding speed is multiplied by this every frame, so 1 = constant speed, >1 accelerates, <1 decelerates. Mode is 1.0 across the whole corpus for every field in this family.',
        "ZH": '逐帧速度倍率：对应的速度每帧乘一次这个值，所以 1 = 匀速，>1 越来越快，<1 越来越慢。这一族字段在全语料的众数一律是 1.0。',
    },
    ("UVSEQUENCE", "patternNo"): {
        "EN": 'Starting frame of the sprite sheet (0 = top-left). Pair it with the Jitter field to randomise the start: an 8x8 sheet has 64 cells, so Jitter=63 picks any cell at spawn.',
        "ZH": '序列帧的起始帧（0 = 左上第一格）。配旁边的 Jitter 可让每个粒子随机起手：8×8 的图共 64 格，Jitter 给 63 就是全随机抽一格。',
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
