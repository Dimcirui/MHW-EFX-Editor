"""
blender_efx/annotations.py  —  L1.3 BT 注释接入

从 010 Editor BT 模板（refs/EFX_Subtypes.bt、EFX_Utils.bt）提取的字段注释。
手工解析并清洗，与 efx_format/structs.py 的 schema ori_name 对齐。

字典键格式：(type_name, field_ori_name)
  - type_name  : HASH_TO_NAME 对应的哈希名（大写，如 "EMITTERSHAPE3D"）
  - field_ori_name : schema 中的 ori_name（即 structs.py 里各 Schema 的字段名）

值：清洗后的注释字符串（单行，去除多余空白）。

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
# 值：注释字符串
# ─────────────────────────────────────────────────────────────────────────────

FIELD_ANNOTATIONS = {

    # ─── TRANSFORM3D ──────────────────────────────────────────────────────────
    # ExternTransform3D (EFX_Subtypes.bt)
    ("TRANSFORM3D", "unkn1"): (
        "Frequency distribution: {0:236, 1:49, 2:233, 3:295, 4:28783, 5:36}"
    ),
    ("TRANSFORM3D", "Translation_Velocity_Modifier"): (
        "Multiplier / Acceleration? Range [0, 1]"
    ),
    ("TRANSFORM3D", "Rotation_Velocity_Modifier"): (
        "Multiplier / Acceleration? Range [0, 1]"
    ),
    ("TRANSFORM3D", "Scale_Velocity_Modifier"): (
        "Multiplier / Acceleration? Range [0, 1]"
    ),
    ("TRANSFORM3D", "enableVelocityBitflag"): (
        "Bitflag — Bit 0: Enable Velocity, Bit 1: Enable Acceleration?"
        "  | Observed: {0:26795, 1:2438, 2:340, 3:59}"
    ),

    # ─── PARENTOPTIONS ────────────────────────────────────────────────────────
    # ParentOptions (EFX_Subtypes.bt)
    ("PARENTOPTIONS", "translation_tracking"): (
        "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
        "  1=Track Player Movement,  2=Do not track further movements,"
        "  3=Ignore Basic Transform"
    ),
    ("PARENTOPTIONS", "angle_tracking"): (
        "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
        "  1=Track Player Movement,  2=Do not track further movements,"
        "  3=Snap to Angle And Track"
    ),
    ("PARENTOPTIONS", "scale_tracking"): (
        "XYZ — per-axis tracking mode:  0=Track Map Center Absolutely,"
        "  1=Track Player Movement,  2=Do not track further movements,"
        "  3=Ignore Basic Transform"
    ),
    ("PARENTOPTIONS", "spawnTrack"): "Track Across Spawns",
    ("PARENTOPTIONS", "spawnLock"): "Lock To Position (Frames)",
    ("PARENTOPTIONS", "bleedPos"): "Progressively Lock Elements to Position (Frames)",
    ("PARENTOPTIONS", "bone_lim"): "Bone Limitation",
    ("PARENTOPTIONS", "unkn1"): "Observed: {0:20433, 1:9199}",

    # ─── SPAWN ────────────────────────────────────────────────────────────────
    # ExternSpawn (EFX_Subtypes.bt)
    ("SPAWN", "occur"): "Spawn Start Delay",
    ("SPAWN", "occur2"): "Randomized Spawn Start Delay",
    ("SPAWN", "repeatAtribute"): (
        "0=Repeat indefinitely; higher value=number of repetitions. "
        "unkn21 must be ≥1 to allow other attributes to cycle. "
        "Combined with durationOfSpawnerLifespan for finite cycles."
    ),

    # ─── LIFE ─────────────────────────────────────────────────────────────────
    # Life (EFX_Subtypes.bt)
    ("LIFE", "timeToDeath"): "Overrides indefinite lifespan",
    ("LIFE", "timeToDeathJitter"): "Overrides indefinite lifespan",

    # ─── EMITTERSHAPE3D ───────────────────────────────────────────────────────
    # ExternEmitterShape3D (EFX_Subtypes.bt)
    ("EMITTERSHAPE3D", "patternControl"): (
        "Emitter shape: 0=Cube, 1=Sphere, 2=Ring, 3=Spot"
    ),
    ("EMITTERSHAPE3D", "trayectoryRotationX"): (
        "Rotates the trajectory over which spawned entries are copied. "
        "Does NOT reorient the normal or tangent vector of the spawn object."
    ),
    ("EMITTERSHAPE3D", "trayectoryRotationY"): (
        "Rotates trajectory Y. Does not reorient spawn object normal/tangent."
    ),
    ("EMITTERSHAPE3D", "trayectoryRotationZ"): (
        "Rotates trajectory Z. Does not reorient spawn object normal/tangent."
    ),
    ("EMITTERSHAPE3D", "spawnPerCycle"): (
        "Entries spawned per cycle; next cycle offsets by one position"
    ),

    # ─── VELOCITY3D ───────────────────────────────────────────────────────────
    # ExternVelocity3D (EFX_Subtypes.bt)
    ("VELOCITY3D", "unkn0"): "Neutral direction is (0, 1, 0)",
    ("VELOCITY3D", "expansion_radius_elasticity"): (
        "0=Completely dampened (instantly at position), "
        "1=No dampening (continues moving)"
    ),
    ("VELOCITY3D", "velocityX"): (
        "Subtracts from system net energy; higher values restrict radial motion"
    ),
    ("VELOCITY3D", "energyOnAxisX"): (
        "(1-x): above 1 = traditional emission radially, "
        "below 1 = implosion, 1 = no energy. Higher = faster."
    ),
    ("VELOCITY3D", "energyOnAxisY"): (
        "(1-y): above 1 = traditional emission radially, "
        "below 1 = implosion, 1 = no energy."
    ),
    ("VELOCITY3D", "energyOnAxisZ"): (
        "(1-z): above 1 = traditional emission radially, "
        "below 1 = implosion, 1 = no energy."
    ),
    ("VELOCITY3D", "expansionType"): (
        "1=Radial, 2=Directional, 5=No Expansion"
    ),

    # ─── SHADERSETTINGS ───────────────────────────────────────────────────────
    # ShaderSettings (EFX_Subtypes.bt)
    ("SHADERSETTINGS", "controlBitflag"): (
        "0=No alpha, 1=Alpha enabled, 2=Emissive behavior, "
        "3=Inverted color + alpha, 6=Greyscale"
    ),
    ("SHADERSETTINGS", "objectInteractionFlag0"): "Player Weapons and Interactables",
    ("SHADERSETTINGS", "objectInteractionFlag1"): "Map geometry",
    ("SHADERSETTINGS", "objectInteractionFlag2"): "Weapon SubParts and Skybox",
    ("SHADERSETTINGS", "objectInteractionFlag3"): "Player Skin",
    ("SHADERSETTINGS", "visibleOnPreview"): "Bitflag — controls preview visibility",

    # ─── FADEBYDEPTH ──────────────────────────────────────────────────────────
    # FadeByDepth (EFX_Subtypes.bt)
    ("FADEBYDEPTH", "viewAngleLimit"): "360 = visible from every angle",

    # ─── SCALEANIM ────────────────────────────────────────────────────────────
    # ExternScaleAnim (EFX_Subtypes.bt)
    ("SCALEANIM", "animationSpeed"): "Speed (name attribute in BT)",

    # ─── ROTATEANIM ───────────────────────────────────────────────────────────
    # RotateAnim — no distinct field comments in BT beyond field names

    # ─── ALPHACORRECTION ──────────────────────────────────────────────────────
    # AlphaCorrection (EFX_Subtypes.bt)
    ("ALPHACORRECTION", "transparentness"): "Transparentness & Brightness",

    # ─── RGBFIRE ──────────────────────────────────────────────────────────────
    # ExternRgbFire (EFX_Subtypes.bt)
    ("RGBFIRE", "color1"): "Color Channel 1 (Alpha)",
    ("RGBFIRE", "brightness1"): "Brightness 1 (Alpha) — colors will combine",
    ("RGBFIRE", "color2"): "Color Channel 2 (RGB)",
    ("RGBFIRE", "brightness3"): (
        "Color Balance 1 — brings out color 1 without lowering overall brightness"
    ),
    ("RGBFIRE", "brightness4"): (
        "Color Balance 2 — setting either balance to 0 makes all disappear"
    ),
    ("RGBFIRE", "color1Param_enable"): "Color 1 Params (Green channel control)",
    ("RGBFIRE", "color1Param_unkn9"): "Setting to 1 kills color 1",
    ("RGBFIRE", "color2Param_enable"): "Color 2 Params (Red channel control)",
    ("RGBFIRE", "color2Param_unkn9"): "Setting to 1 kills color 2",

    # ─── GUIDE ────────────────────────────────────────────────────────────────
    # Guide (EFX_Subtypes.bt) — field names are descriptive, few inline comments

    # ─── PLEMISSIVE ───────────────────────────────────────────────────────────
    # ExternPlEmissive (EFX_Subtypes.bt)
    ("PLEMISSIVE", "body_p"): "Player Aura Part — see /wiki/EFX-Effect-Editing#aura-parts",
    ("PLEMISSIVE", "wp_p"): "Weapon Aura Part — see /wiki/EFX-Effect-Editing#aura-parts",
    ("PLEMISSIVE", "area"): "Area of Aura (2 floats)",
    ("PLEMISSIVE", "bright"): "Brightness (can be negative)",
    ("PLEMISSIVE", "area_of_aura"): "9=Front half,  8-1=Everything",

    # ─── PARENTEMISSIVE ───────────────────────────────────────────────────────
    # ParentEmissive (EFX_Subtypes.bt)
    ("PARENTEMISSIVE", "brightness"): "Brightness",
    ("PARENTEMISSIVE", "rimParam"): "Emissive Rim Parameters (3 floats)",
    ("PARENTEMISSIVE", "blendParam"): "Emissive Rim Blend Parameters (3 floats)",

    # ─── PLSNOW ───────────────────────────────────────────────────────────────
    # PlSnow (EFX_Subtypes.bt)
    ("PLSNOW", "body_part_id"): "1F=Everything, 1/2/3/4/5=body parts as usual",
    ("PLSNOW", "weapon_id"): "Same as PlEmissive weapon slot",
    ("PLSNOW", "alpha_threshold"): "Higher values cover less area",
    ("PLSNOW", "subsurface_multipler"): "Transparency / Subsurface multiplier",
    ("PLSNOW", "craquelure_effect_diffumination"): "Craquelure diffusion strength",

    # ─── PTCOLLISION ──────────────────────────────────────────────────────────
    # PtCollision (EFX_Subtypes.bt)
    ("PTCOLLISION", "physicsEnum"): (
        "0=Fall Through,  1=Bounce and Fade,  "
        "2=Bounce and Fall Through,  3=For Remaining after Bouncing (set multiplier to 0)"
    ),
    ("PTCOLLISION", "bounceElasticity"): "Bounce Elasticity On Collision",
    ("PTCOLLISION", "bounceElasticityJitter"): "Bounce Elasticity Jitter",
    ("PTCOLLISION", "horizontalBounce"): "Multiplier of bounce elasticity",
    ("PTCOLLISION", "ieIndex"): "0=Call PlayEFX Index?,  0xFFFFFFFF=Null",

    # ─── PTLIFE ───────────────────────────────────────────────────────────────
    # PtLife (EFX_Subtypes.bt)
    ("PTLIFE", "timing"): "0=Attaches at spawn,  4=Attaches after the end",
    ("PTLIFE", "relationIndex"): "Play Emitter / Play EFX Index that declares the children",

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
    ("UVCONTROL", "uv1_acceleration"): "Multiplies speed every second (UV1)",
    ("UVCONTROL", "uv2_acceleration"): "Multiplies speed every second (UV2)",
    ("UVCONTROL", "opacityAcceleration"): "Multiplies opacity every second",

    # ─── EMITTERSHAPE2D ───────────────────────────────────────────────────────
    # EmitterShape2D — no inline comments in BT

    # ─── RAYCAST ──────────────────────────────────────────────────────────────
    # RayCast (EFX_Subtypes.bt)
    ("RAYCAST", "direction"): (
        "0=Left, 1=Down, 2=Forward, 3=Right, 4=Up, 5=Backward"
    ),
    ("RAYCAST", "unknown1"): "Usually -1; occasionally 0",
    ("RAYCAST", "unknown2"): "Observed value 256 — may be flag or enum",

    # ─── HOMING ───────────────────────────────────────────────────────────────
    # Homing (EFX_Subtypes.bt)
    ("HOMING", "enableRadialVanish"): (
        "1=Freak Speed,  3=Disappear on inner radius"
    ),

    # ─── SCREENSPACECOLLISION ─────────────────────────────────────────────────
    # ScreenSpaceCollision (EFX_Subtypes.bt)
    ("SCREENSPACECOLLISION", "lifespan"): (
        "0=No interaction; higher values = more bounce"
    ),

    # ─── SHOVEL ───────────────────────────────────────────────────────────────
    # Shovel — no inline comments in BT for most fields

    # ─── EXTERNREFERENCE ──────────────────────────────────────────────────────
    # ExternReference — no inline comments in BT

    # ─── DUMMY / RANDOMFIX / MASTERONLY / BLINK / LUMINANCEBLEED / REFRACTION ─
    # No significant inline comments in BT

    # ─── MESH (Mod3Properties fields — _custom type, flat part) ───────────────
    ("MESH", "end_model_viscon"): "Picks between starting/end at random",
    ("MESH", "tracking_flags"): (
        "0=Guide Source,  1=Away from Source,  2=Look Away From Camera,  "
        "3=WTF Occupies entire map,  4=Guide Camera,  5=Disappears,  "
        "6=Don't Track Rotation At All,  7=Disappears,  "
        "8=Perpendicular to Ground Don't Track"
    ),
    ("MESH", "colorize_material1"): "Byte controls for material colorize slot 1",
    ("MESH", "colorize_material2"): (
        "Byte controls for material colorize slot 2. "
        "Second byte tied to EPV Slot colour with NFH plugin."
    ),
    ("MESH", "randommizeViscon"): (
        "0=Spawn random sample of range,  1=Spawn all of the range"
    ),
    ("MESH", "shadowCastBitflag"): "Shadow casting bitflag",

    # ─── RIBBON (fixed part fields) ───────────────────────────────────────────
    ("RIBBON", "material_tesselation_density"): "Material Repeating Density",
    ("RIBBON", "horizontal_physics_subdivision_count"): (
        "Number of Subdivisions +1 (horizontal dividers, minimum 2). "
        "Disney magic at 5000."
    ),
    ("RIBBON", "restitution_direction"): (
        "0=Left, 1=Up, 2=Forward, 3=Right, 4=Down, 5=Backwards, 6=None"
    ),
    ("RIBBON", "unkn16_2"): (
        "0=Align to World,  Anything else=Align to Source"
    ),

    # ─── UVSEQUENCE (fixed part fields) ───────────────────────────────────────
    ("UVSEQUENCE", "uvs_index"): "UVS File Path Index",
    ("UVSEQUENCE", "loopingEnum"): (
        "0=Not Animated,  2=Random Restart,  8=?,  9=Continuous"
    ),

    # ─── BILLBOARD3D (fixed part fields) ──────────────────────────────────────
    ("BILLBOARD3D", "applicationRule"): (
        "Enum — determines how long and how many times it applies"
    ),
    ("BILLBOARD3D", "brightness"): "Brightness",
    ("BILLBOARD3D", "scale"): "Scale",
    ("BILLBOARD3D", "width"): "Width",
    ("BILLBOARD3D", "height"): "Height",

    # ─── PLANE (fixed part fields — same layout as BILLBOARD3D dds_data) ──────
    ("PLANE", "applicationRule"): (
        "Enum — determines how long and how many times it applies"
    ),
    ("PLANE", "brightness"): "Brightness",
    ("PLANE", "scale"): "Scale",
    ("PLANE", "width"): "Width",
    ("PLANE", "height"): "Height",

    # ─── RIBBONBLADE (fixed part fields) ──────────────────────────────────────
    ("RIBBONBLADE", "contractionSpeed"): (
        "0=Lingers,  1=Retracts,  ∞=Retracts instantly"
    ),
    ("RIBBONBLADE", "colourTransitionPoint"): (
        "0=Instantly start transition,  1=Start at the end"
    ),

    # ─── TURBULENCE (fixed part fields) ───────────────────────────────────────
    # Turbulence — no inline comments in BT for non-path fields

    # ─── LIGHTNING (fixed part fields) ────────────────────────────────────────
    # Lightning — no significant inline comments in BT for fixed fields

}


# ─────────────────────────────────────────────────────────────────────────────
# 公共查询函数
# ─────────────────────────────────────────────────────────────────────────────

def get_annotation(type_name: str, field_name: str) -> str:
    """
    按 (type_name, field_name) 查注释。
    type_name 大写（如 "EMITTERSHAPE3D"）；field_name 为 schema ori_name。
    找不到返回空字符串。
    """
    return FIELD_ANNOTATIONS.get((type_name.upper(), field_name), "")
