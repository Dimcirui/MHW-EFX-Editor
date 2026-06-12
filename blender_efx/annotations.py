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
        "EN": "Spawn Start Delay",
        "ZH": "生成起始延迟",
    },
    ("SPAWN", "occur2"): {
        "EN": "Randomized Spawn Start Delay",
        "ZH": "随机化的生成起始延迟",
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
        "EN": "0=Completely dampened (instantly at position), "
              "1=No dampening (continues moving)",
        "ZH": "0=完全阻尼（瞬间到位），"
              "1=无阻尼（持续运动）",
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
        "EN": "1=Radial, 2=Directional, 5=No Expansion",
        "ZH": "1=径向, 2=定向, 5=无扩张",
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

    # ─── FADEBYDEPTH ──────────────────────────────────────────────────────────
    # FadeByDepth (EFX_Subtypes.bt)
    ("FADEBYDEPTH", "viewAngleLimit"): {
        "EN": "360 = visible from every angle",
        "ZH": "360 = 从每个角度都可见",
    },

    # ─── SCALEANIM ────────────────────────────────────────────────────────────
    # ExternScaleAnim (EFX_Subtypes.bt)
    ("SCALEANIM", "animationSpeed"): {
        "EN": "Speed (name attribute in BT)",
        "ZH": "速度（BT 中的 name 属性）",
    },

    # ─── ROTATEANIM ───────────────────────────────────────────────────────────
    # RotateAnim — no distinct field comments in BT beyond field names

    # ─── ALPHACORRECTION ──────────────────────────────────────────────────────
    # AlphaCorrection (EFX_Subtypes.bt)
    ("ALPHACORRECTION", "transparentness"): {
        "EN": "Transparentness & Brightness",
        "ZH": "透明度与亮度",
    },

    # ─── RGBFIRE ──────────────────────────────────────────────────────────────
    # ExternRgbFire (EFX_Subtypes.bt)
    ("RGBFIRE", "color1"): {
        "EN": "Color Channel 1 (Alpha)",
        "ZH": "颜色通道 1（Alpha）",
    },
    ("RGBFIRE", "brightness1"): {
        "EN": "Brightness 1 (Alpha) — colors will combine",
        "ZH": "亮度 1（Alpha）—— 颜色会叠加混合",
    },
    ("RGBFIRE", "color2"): {
        "EN": "Color Channel 2 (RGB)",
        "ZH": "颜色通道 2（RGB）",
    },
    ("RGBFIRE", "brightness3"): {
        "EN": "Color Balance 1 — brings out color 1 without lowering overall brightness",
        "ZH": "色彩平衡 1 —— 在不降低整体亮度的情况下突出颜色 1",
    },
    ("RGBFIRE", "brightness4"): {
        "EN": "Color Balance 2 — setting either balance to 0 makes all disappear",
        "ZH": "色彩平衡 2 —— 任一平衡设为 0 都会让全部消失",
    },
    ("RGBFIRE", "color1Param_enable"): {
        "EN": "Color 1 Params (Green channel control)",
        "ZH": "颜色 1 参数（绿色通道控制）",
    },
    ("RGBFIRE", "color1Param_unkn9"): {
        "EN": "Setting to 1 kills color 1",
        "ZH": "设为 1 会消除颜色 1",
    },
    ("RGBFIRE", "color2Param_enable"): {
        "EN": "Color 2 Params (Red channel control)",
        "ZH": "颜色 2 参数（红色通道控制）",
    },
    ("RGBFIRE", "color2Param_unkn9"): {
        "EN": "Setting to 1 kills color 2",
        "ZH": "设为 1 会消除颜色 2",
    },

    # ─── GUIDE ────────────────────────────────────────────────────────────────
    # Guide (EFX_Subtypes.bt) — field names are descriptive, few inline comments

    # ─── PLEMISSIVE ───────────────────────────────────────────────────────────
    # ExternPlEmissive (EFX_Subtypes.bt)
    ("PLEMISSIVE", "body_p"): {
        "EN": "Player Aura Part — see /wiki/EFX-Effect-Editing#aura-parts",
        "ZH": "玩家光圈部位 —— 见 /wiki/EFX-Effect-Editing#aura-parts",
    },
    ("PLEMISSIVE", "wp_p"): {
        "EN": "Weapon Aura Part — see /wiki/EFX-Effect-Editing#aura-parts",
        "ZH": "武器光圈部位 —— 见 /wiki/EFX-Effect-Editing#aura-parts",
    },
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
    # Homing (EFX_Subtypes.bt)
    ("HOMING", "enableRadialVanish"): {
        "EN": "1=Freak Speed,  3=Disappear on inner radius",
        "ZH": "1=异常加速,  3=在内半径处消失",
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
        "EN": "Byte controls for material colorize slot 1",
        "ZH": "材质染色槽 1 的字节控制",
    },
    ("MESH", "colorize_material2"): {
        "EN": "Byte controls for material colorize slot 2. "
              "Second byte tied to EPV Slot colour with NFH plugin.",
        "ZH": "材质染色槽 2 的字节控制。"
              "第二个字节在使用 NFH 插件时绑定到 EPV 槽颜色。",
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

    # ─── UVSEQUENCE (fixed part fields) ───────────────────────────────────────
    ("UVSEQUENCE", "uvs_index"): {
        "EN": "UVS File Path Index",
        "ZH": "UVS 文件路径索引",
    },
    ("UVSEQUENCE", "loopingEnum"): {
        "EN": "0=Not Animated,  2=Random Restart,  8=?,  9=Continuous",
        "ZH": "0=不播放动画,  2=随机重启,  8=?,  9=连续循环",
    },

    # ─── BILLBOARD3D (fixed part fields) ──────────────────────────────────────
    ("BILLBOARD3D", "applicationRule"): {
        "EN": "Enum — determines how long and how many times it applies",
        "ZH": "枚举 —— 决定它应用的时长与次数",
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
        "EN": "Enum — determines how long and how many times it applies",
        "ZH": "枚举 —— 决定它应用的时长与次数",
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

}


# ─────────────────────────────────────────────────────────────────────────────
# 公共查询函数
# ─────────────────────────────────────────────────────────────────────────────

def get_annotation(type_name: str, field_name: str) -> str:
    """
    按 (type_name, field_name) 查注释，并按当前 UI 语言返回字符串。
    type_name 大写（如 "EMITTERSHAPE3D"）；field_name 为 schema ori_name。
    值为 {"EN":.., "ZH":..} 字典，按 i18n.get_lang() 选取，缺语种回退英文。
    找不到返回空字符串。
    """
    entry = FIELD_ANNOTATIONS.get((type_name.upper(), field_name))
    if not entry:
        return ""
    if isinstance(entry, dict):
        from . import i18n
        lang = i18n.get_lang()
        return entry.get(lang) or entry.get("EN") or ""
    return entry  # backward safety
