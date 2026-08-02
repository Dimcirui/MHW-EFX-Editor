# -*- coding: utf-8 -*-
"""
blender_efx/field_rename_aliases.py — 字段改名导出兼容表

背景：EFXFieldItem.ori_name 是导入时按当时 schema 烘死进 .blend 的（见 fields.py::
dict_to_items）。改 schema 字段名之后，已经导入、尚未重新导入的 .blend 里，item.ori_name
还是旧名字——rebuild_data_bytes / rebuild_custom_field_attribute 按当前 schema 的名字表
查不到，本来会安全退回整块 raw_b64（不会崩、不会错位，但会静默丢弃用户在旧名字段上做的
编辑，见 memory schema-change-requires-reimport）。

这张表是重建路径失败前的最后一步兜底：按 (type_name, 旧字段名) 查当前字段名，再用当前
字段名的 spec 重试。调用方还会额外核对新旧 dtype 是否一致才敢用（见 fields.py 的
_resolve_renamed_spec/_resolve_renamed_entry），所以就算这张表记错、记漏、或者字段其实是
被拆分/合并过的（形状变了、根本对不上），也只是安全地查不到/核对不过，等价于没有这张
表——不会比现状更差。

⚠ 维护约定：只登记"纯改名"——同一个字段、同一个字节位置、同一个存储大小，只是换了个
identifier。字段拆分（1 个旧字段拆成多个新字段，如 SHADERSETTINGS.visibleOnPreview →
unknBool0~3）或合并（多个旧字段并成 1 个，如 FADEBYANGLE.unkn_angle2/3/4 → rotation）
不满足"同一个字段"，查了也用不上，不要塞进来。

⚠ 以后每次在 schema/attributes.py 或 schema/custom_codecs.py 里给字段改名，顺手在这里
补一条 (TYPE_NAME, 旧名): 新名。如果同一个字段这一轮又改了第二次（比如上一版才把 A 改成
B，这一版又把 B 改成 C），两条都要留：{(TYPE, "A"): "C", (TYPE, "B"): "C"}——旧名统一直接
指向"当前"名字，不做链式查找。
"""

FIELD_RENAME_ALIASES = {
    # ── HOMING（2026-07-30 六字段改名，运动学模型定案）──────────────────────
    ("HOMING", "restoringForce"): "turnRate",
    ("HOMING", "speed"): "initialSpeed",
    ("HOMING", "speedMultiplier"): "targetSpeed",
    ("HOMING", "f3"): "forceFieldSpeedScale",
    ("HOMING", "vanishDistance"): "vanishRadius",
    ("HOMING", "forceFieldDistance"): "forceFieldRadius",

    # ── EMITTERSHAPE3D ───────────────────────────────────────────────────────
    ("EMITTERSHAPE3D", "unknOrientation"): "rotationCorrect",
    ("EMITTERSHAPE3D", "scaleHorizontal"): "scanAngleHorizontal",
    ("EMITTERSHAPE3D", "scaleVertical"): "scanAngleVertical",

    # ── EMITTERSHAPE2D ───────────────────────────────────────────────────────
    ("EMITTERSHAPE2D", "spawnCount"): "rangeDivideHorizontalNum",

    # ── SCALEANIM ────────────────────────────────────────────────────────────
    ("SCALEANIM", "unknFloat"): "initialScaleSpeedJitter",

    # ── FADEBYANGLE ──────────────────────────────────────────────────────────
    ("FADEBYANGLE", "unknBitmask0_1"): "coneVisibilityFlags",
    ("FADEBYANGLE", "unkn_angle0"): "cutoffConeAngle",
    ("FADEBYANGLE", "unkn_angle1"): "fadeConeAngle",
    ("FADEBYANGLE", "unkn1_2"): "minAlpha",
    ("FADEBYANGLE", "unknBitmask2_0"): "baseAxis",
    ("FADEBYANGLE", "unknEnum2_1"): "rotOrder",

    # ── FADEBYOCCLUSION ──────────────────────────────────────────────────────
    ("FADEBYOCCLUSION", "unknFixed0_1"): "section_length",
    ("FADEBYOCCLUSION", "unkn1"): "spacer0",
    ("FADEBYOCCLUSION", "unkn2_0"): "occlusionRadius",
    ("FADEBYOCCLUSION", "unknFlag2_1"): "minScale",
    ("FADEBYOCCLUSION", "unknFlag2_2"): "minAlpha",

    # ── LIFE ─────────────────────────────────────────────────────────────────
    ("LIFE", "unkn2_0"): "unknFrame",
    ("LIFE", "unknEnum2_1"): "unknFrameJitter",

    # ── PTCOLLISION（2026-07-31）─────────────────────────────────────────────
    ("PTCOLLISION", "unkn06"): "projectionOffset",
    ("PTCOLLISION", "unkn07"): "projectionDist",
    ("PTCOLLISION", "unknEnum2_0"): "bounceCount",
    ("PTCOLLISION", "bounceCountLimit"): "bounceCount",
    ("PTCOLLISION", "unknEnum2_1"): "bounceCountJitter",
    ("PTCOLLISION", "unknEnum38"): "impactPlayTriggerMode",
    ("PTCOLLISION", "unknBitmask4_0"): "impactPlayTriggerCount",
    ("PTCOLLISION", "unknFlag4_1"): "impactPlayTriggerCountJitter",

    # ── UVCONTROL（2026-07-31，flowmap 8 件套改名）───────────────────────────
    ("UVCONTROL", "uv1_unkn0"): "uv1_unknFlag",
    ("UVCONTROL", "unknFlag2"): "enableFlowmap",
    ("UVCONTROL", "extraMaterialInitialPosition"): "flowmapSpeed",
    ("UVCONTROL", "extraMaterialInitialPositionJitter"): "flowmapSpeedJitter",
    ("UVCONTROL", "extraMaterialSpeed"): "flowmapSpeedCoef",
    ("UVCONTROL", "extraMaterialSpeedJitter"): "flowmapSpeedCoefJitter",
    ("UVCONTROL", "opacity"): "flowmapStrength",
    ("UVCONTROL", "opacityJitter"): "flowmapStrengthJitter",
    ("UVCONTROL", "opacityAcceleration"): "flowmapStrengthCoef",
    ("UVCONTROL", "opacityAccelerationJitter"): "flowmapStrengthCoefJitter",

    # ── BILLBOARD3D / BILLBOARD2D / PLANE ───────────────────────────────────
    ("BILLBOARD3D", "randomBrightnessMult"): "brightnessJitter",
    ("BILLBOARD2D", "randomBrightnessMult"): "brightnessJitter",
    ("PLANE", "randomBrightnessMult"): "brightnessJitter",

    # ── RIBBON（2026-07-30 大批改名）─────────────────────────────────────────
    ("RIBBON", "color2"): "colorRange",
    ("RIBBON", "unkn4_0"): "brightnessJitter",
    ("RIBBON", "unknEnum4_1"): "ribbonMode",
    ("RIBBON", "horizontal_physics_subdivision_count"): "subdivisionCount",
    ("RIBBON", "vertical_physics_subdivision_count"): "unknBool15",
    ("RIBBON", "restitution_direction"): "baseAxis",
    ("RIBBON", "unknEnum16arr_0"): "rotationOrder",
    ("RIBBON", "unkn16arr_1"): "rotationX",
    ("RIBBON", "unkn16arr_2"): "rotationXJitter",
    ("RIBBON", "unkn16arr_3"): "rotationYJitter",
    ("RIBBON", "startingAngle"): "rotationY",
    ("RIBBON", "startingAngleJitter"): "rotationZJitter",
    ("RIBBON", "unkn16_0_0"): "rotationZ",
    ("RIBBON", "unknown19_0"): "spawnAnchorOffset",
    ("RIBBON", "restitution"): "restoreStrength",
    ("RIBBON", "restitution_jitter"): "restoreStrengthJitter",
    ("RIBBON", "inertial_excess"): "inertia",
    ("RIBBON", "inertial_excess_jitter"): "inertiaJitter",
    ("RIBBON", "unknEnum22_1"): "unknBitmask22_1",
    ("RIBBON", "tailTiedToBone"): "enableFlowmap",
    ("RIBBON", "unkn23_0"): "flowmapSpeed",
    ("RIBBON", "unkn23_1"): "flowmapSpeedJitter",
    ("RIBBON", "unkn23_2"): "flowmapSpeedCoef",
    ("RIBBON", "unknFixed23_3"): "flowmapSpeedCoefJitter",
    ("RIBBON", "unkn23_4"): "flowmapStrength",
    ("RIBBON", "unkn23_5"): "flowmapStrengthJitter",
    ("RIBBON", "unkn23_6"): "flowmapStrengthCoef",
    ("RIBBON", "unknFixed23_7"): "flowmapStrengthCoefJitter",
    ("RIBBON", "base_flap_frequency"): "flap1Frequency",
    ("RIBBON", "base_flap_frequency_jitter"): "flap1FrequencyJitter",
    ("RIBBON", "base_flap_amount"): "flap1Amount",
    ("RIBBON", "base_flap_amount_jitter"): "flap1AmountJitter",
    ("RIBBON", "tip_flap_frequency"): "flap2Frequency",
    ("RIBBON", "tip_flap_frequency_jitter"): "flap2FrequencyJitter",
    ("RIBBON", "tip_flap_amount"): "flap2Amount",
    ("RIBBON", "tip_flap_amount_jitter"): "flap2AmountJitter",
    ("RIBBON", "ribbon_flow_unkn0"): "unknFixed28_0",
    ("RIBBON", "ribbon_flow_enable_a"): "unknGlobalForceEnable",
    ("RIBBON", "ribbon_flow_enable_b"): "unknBool28_2",
    ("RIBBON", "ribbon_flow_reserved"): "spacer28",
    ("RIBBON", "ribbon_flow_param0"): "unknGlobalForceX",
    ("RIBBON", "ribbon_flow_param1"): "unknGlobalForceY",
    ("RIBBON", "ribbon_flow_param2"): "unknGlobalForceZ",
    ("RIBBON", "ribbon_flow_param3"): "unknFixed28_param3",

    # ── STRAINRIBBON（2026-07-31，flowmap 8 件套 + 总开关）─────────────────────
    # 9 条全是纯改名（同偏移、同大小、同 dtype），可安全走本表。
    ("STRAINRIBBON", "color3_z"): "enableFlowmap",
    ("STRAINRIBBON", "unkn06_0"): "flowmapSpeed",
    ("STRAINRIBBON", "unkn06_1"): "flowmapSpeedJitter",
    ("STRAINRIBBON", "unkn06_2"): "flowmapSpeedCoef",
    ("STRAINRIBBON", "unknFixed06_3"): "flowmapSpeedCoefJitter",
    ("STRAINRIBBON", "unkn06_4"): "flowmapStrength",
    ("STRAINRIBBON", "unknFlag06_5"): "flowmapStrengthJitter",
    ("STRAINRIBBON", "unkn06_6"): "flowmapStrengthCoef",
    ("STRAINRIBBON", "unkn06_7"): "flowmapStrengthCoefJitter",
    # ⚠ 同一未发布周期内二次改名产生的中间名——这些名字进过发给用户的中间测试
    #   构建，用那些包导入过的 .blend 里烘的就是它们，故必须一并登记（补漏）。
    ("PTCOLLISION", "bounceCountLimitJitter"): "bounceCountJitter",
    ("PTCOLLISION", "impactPlayTriggerCountRandom"): "impactPlayTriggerCountJitter",
    ("PTCOLLISION", "bounceElasticityBonus"): "bounceElasticityMultiplier",

    # ── 0.5.0 之前的历史改名（2026-07-31 批量补录）─────────────────────────────
    # 由脚本从 schema 行内「原 X」注释抽取并逐条过滤：类型名与新字段名都必须真实存在
    # 于 FIELD_REGISTRY、老名不能仍是该类型的合法字段、老名映射到多个新名的（拆分）
    # 一律丢弃；另人工剔除拆分/合并/类型变更/注释里的幽灵名共 12 条。
    ("ALPHACORRECTION", "transparentness"): "contrast_gamma",
    ("ALPHACORRECTION", "unkn1"): "lowPass",
    ("BILLBOARD2D", "unkn0_0"): "typeFlag",
    ("BILLBOARD3D", "unkn0"): "typeFlag",
    ("BLINK", "unkn0_0"): "typeFlag",
    ("BLINK", "unkn0_1"): "section_length",
    ("CHECKPUREATTRIBUTE", "unkn0_0"): "typeFlag",
    ("CHECKPUREATTRIBUTE", "unkn0_1"): "section_length",
    ("COLORCORRECTFILTER", "unkn0_0"): "typeFlag",
    ("DUMMY", "unkn0_0"): "typeFlag",
    ("DUMMY", "unkn0_1"): "section_length",
    ("EMITTERBOUNDARY", "unkn0_0"): "typeFlag",
    ("EMITTERSHAPE2D", "unkn0"): "typeFlag",
    ("EMITTERSHAPE3D", "unkn0"): "typeFlag",
    ("EMITTERSHAPE3D", "patternControl"): "shapeType",
    ("EMITTERSHAPE3D", "spawnPerCycle"): "rangeDivideHorizontalNum",
    ("EMITTERSHAPE3D", "spawnTotal"): "rangeDivideVerticalNum",
    ("EMITTERSHAPE3D", "transform"): "rangeXYZ",
    ("EMITTERSHAPE3D", "trayectoryRotationX"): "localRotationX",
    ("EMITTERSHAPE3D", "trayectoryRotationY"): "localRotationY",
    ("EMITTERSHAPE3D", "trayectoryRotationZ"): "localRotationZ",
    ("EMITTERSHAPE3D", "unknEnum2"): "rangeDivideAxis",
    ("EMITTERSHAPE3D", "unknEnum3_0"): "rotationCorrect",
    ("EMITTERSHAPEMESH", "unkn0_0"): "typeFlag",
    ("EMITTERSHAPEMESH", "unkn2_1"): "ddsUsageType",
    ("EMITTERSHAPEMESH", "unkn2_3"): "visconIndex",
    ("EXTERNREFERENCE", "unkn0"): "typeFlag",
    ("FADEBYANGLE", "unkn0_0"): "typeFlag",
    ("FADEBYDEPTH", "unkn0"): "typeFlag",
    ("FADEBYEMITTERANGLE", "unkn0_0"): "typeFlag",
    ("FADEBYEMITTERANGLE", "unkn0_1"): "section_length",
    ("FADEBYOCCLUSION", "unkn0_0"): "typeFlag",
    ("FAKEDOF", "unkn0"): "typeFlag",
    ("FAKEDOF", "unkn1"): "section_length",
    ("FAKEPLANE", "unkn0_0"): "typeFlag",
    ("FAKEPLANE", "unkn0_1"): "section_length",
    ("HOMING", "unknown"): "typeFlag",
    ("HOMING", "unknown0"): "section_length",
    ("HOMING", "enableRadialVanish"): "forceFieldMode",
    ("HOMING", "i0"): "homingTarget",
    ("HOMING", "i1"): "vanishMode",
    ("LIFE", "unkn0"): "typeFlag",
    ("LIGHTNING", "unkn00_0"): "typeFlag",
    ("LINKPARTSVISIBLE", "unkn0_0"): "typeFlag",
    ("MASTERONLY", "unkn0"): "typeFlag",
    ("NOISE", "secondary_axis_speed"): "main_axis_speed_jitter",
    ("NOISE", "secondary_axis_speed2"): "main_axis_speed2_jitter",
    ("NOISE", "smooth_radius_randomized"): "teleport_radius_jitter",
    ("NOISE", "smooth_radius_randomized2"): "teleport_radius2_jitter",
    ("OTOMOSNOW", "unkn0_0"): "typeFlag",
    ("OTOMOSNOW", "unkn0_1"): "section_length",
    ("PARENTEMISSIVE", "unkn0"): "typeFlag",
    ("PARENTMATERIAL", "unkn0_0"): "typeFlag",
    ("PARENTOPTIONS", "unkn0"): "typeFlag",
    ("PARENTSNOW", "unkn0_0"): "typeFlag",
    ("PARENTSNOW", "unkn0_1"): "section_length",
    ("PATHCHAIN", "unkn0_0"): "typeFlag",
    ("PATHCHAIN", "unkn0_1"): "section_length",
    ("PLEMISSIVE", "unkn0_0"): "typeFlag",
    ("PLSNOW", "unkn0_0"): "typeFlag",
    ("PTCOLLISION", "unkn00"): "typeFlag",
    ("PTLIFE", "unkn0"): "typeFlag",
    ("PTTRIGGER", "unkn0_0"): "typeFlag",
    ("PTTRIGGER", "unkn0_1"): "section_length",
    ("RAYCAST", "fixed70"): "section_length",
    ("RAYCAST", "unknown0"): "typeFlag",
    ("REFRACTION", "unkn0"): "typeFlag",
    ("REFRACTION", "unkn2"): "seeThroughBlend",
    ("RGBFIRE", "unkn0"): "typeFlag",
    ("RGBFIRE", "color1"): "fireColor",
    ("RGBFIRE", "color2"): "smokeColor",
    ("RGBWATER", "unkn0"): "typeFlag",
    ("RIBBON", "unkn0"): "typeFlag",
    ("RIBBONBLADE", "unkn0_0"): "typeFlag",
    ("RIBBONBLADE", "NULL5"): "flowmapSpeedJitter",
    ("RIBBONBLADE", "NULL6"): "flowmapSpeedCoefJitter",
    ("RIBBONBLADE", "NULL7"): "flowmapStrengthJitter",
    ("RIBBONBLADE", "NULL8"): "flowmapStrengthCoefJitter",
    ("RIBBONBLADE", "unkn03"): "widthDirection",
    ("RIBBONBLADE", "unkn04"): "width",
    ("RIBBONBLADE", "unkn05_0"): "length",
    ("RIBBONBLADE", "unkn07_1"): "lengthMode",
    ("RIBBONBLADE", "unkn23"): "flowmapSpeed",
    ("RIBBONBLADE", "unkn24"): "flowmapSpeedCoef",
    ("RIBBONBLADE", "unkn25"): "flowmapStrength",
    ("RIBBONBLADE", "unkn26"): "flowmapStrengthCoef",
    ("ROTATEANIM", "billboardRotationSpeed"): "billboardRotationJitter",
    ("ROTATEANIM", "momentum_retention"): "spinSpeedCoefX",
    ("ROTATEANIM", "unkn0_0"): "spinAxisMask",
    ("ROTATEANIM", "unkn1_0"): "billboardRotationCoef",
    ("ROTATEANIM", "unkn1_1"): "billboardRotationCoefJitter",
    ("ROTATEANIM", "unknEnum1_2"): "rotateDelayStartJitter",
    ("SCALEANIM", "unkn0"): "typeFlag",
    ("SCALEANIM", "delayJitter"): "animUpdateStartJitter",
    ("SCALEANIM", "scaleAccelJitter"): "scaleAccelXJitter",
    ("SCALEANIM", "scaleSpeedJitter"): "initialScaleAccelJitter",
    ("SCREENSPACECOLLISION", "unkn0_0"): "typeFlag",
    ("SCREENSPACECOLLISION", "unkn0_1"): "section_length",
    ("SHADERSETTINGS", "unkn0"): "typeFlag",
    ("SHOVEL", "unkn00"): "typeFlag",
    ("SHOVEL", "unkn01"): "section_length",
    ("SPAWN", "unkn0"): "typeFlag",
    ("SPAWN", "durationOfSpawnerLifespan"): "burstsPerCycle",
    ("SPAWN", "frameDelayBetweenSpawns"): "burstInterval",
    ("SPAWN", "instancesSpawnedPerFrame"): "particlesPerBurst",
    ("SPAWN", "instancesSpawnedTotal"): "maxParticles",
    ("SPAWN", "occur"): "emitterStartDelay",
    ("SPAWN", "occur2"): "emitterStartDelayJitter",
    ("SPAWN", "randomizedDelay"): "burstIntervalJitter",
    ("SPAWN", "randomizedLifespan"): "burstsPerCycleJitter",
    ("SPAWN", "randomizedSpawnsPerFrame"): "particlesPerBurstJitter",
    ("SPAWN", "repeatAtribute"): "emitterRepeatCount",
    ("SPAWN", "unkn10"): "particleSpawnDelay",
    ("SPAWN", "unkn21"): "altBurstInterval",
    ("SPAWN", "unkn30"): "altBurstIntervalJitter",
    ("SPAWN", "unknEnum11"): "particleSpawnDelayJitter",
    ("SPAWNBYANGLE", "unkn0_0"): "typeFlag",
    ("SPAWNBYANGLE", "unkn0_1"): "section_length",
    ("SPAWNBYOCCLUSION", "unkn0_0"): "typeFlag",
    ("SPAWNBYOCCLUSION", "unkn0_1"): "section_length",
    ("STRAINRIBBON", "unkn00_0"): "typeFlag",
    ("STRAINRIBBON", "unkn01_0"): "useColorRange",
    ("STRAINRIBBON", "unkn02_0"): "useEmission",
    ("STRAINRIBBON", "unkn10_01"): "angleRelated",
    ("STRAINRIBBON", "unkn10_02"): "angleRelatedJitter",
    ("TONEMAPFILTER", "unkn0_0"): "typeFlag",
    ("TRANSFORM2D", "unknown"): "typeFlag",
    ("TRANSFORM3D", "unkn0"): "typeFlag",
    ("UVCONTROL", "uv2_unkn0"): "uv2_enable",
    ("UVSEQUENCE", "unkn0"): "typeFlag",
    ("VELOCITY2D", "unkn0_0"): "typeFlag",
    ("VELOCITY2D", "expansionRadiusElasticity"): "speedCoef",
    ("VELOCITY2D", "expansionRadiusElasticityJitter"): "speedCoefJitter",
    ("VELOCITY2D", "expansionType"): "velocityType",
    ("VELOCITY2D", "initialVelocity"): "speed",
    ("VELOCITY2D", "initialVelocityDelay"): "movementDelay",
    ("VELOCITY2D", "initialVelocityDelayJitter"): "movementDelayJitter",
    ("VELOCITY2D", "initialVelocityJitter"): "speedJitter",
    ("VELOCITY2D", "offsetX"): "velocityX",
    ("VELOCITY2D", "offsetY"): "velocityY",
    ("VELOCITY2D", "sizeX"): "divergenceX",
    ("VELOCITY2D", "sizeY"): "divergenceY",
    ("VELOCITY2D", "unkn0_1"): "rotation",
    ("VELOCITY2D", "unkn10"): "rotationJitter",

    # ── 2026-08-03 官方 DTI 名对齐（UI 措辞不变，只改内部名）─────────────────
    # flowmap 八件套：Acceleration 实为每帧乘算系数（中性值 1.0），官方名 mFlowSpeedCoef /
    # mFlowStrengthCoef。8 个类型共用同一套字段名。
    **{
        (_t, _old): _new
        for _t in ("BILLBOARD2D", "BILLBOARD3D", "LIGHTNING", "PLANE",
                   "RIBBON", "RIBBONBLADE", "STRAINRIBBON", "UVCONTROL")
        for _old, _new in (
            ("flowmapAcceleration",               "flowmapSpeedCoef"),
            ("flowmapAccelerationJitter",         "flowmapSpeedCoefJitter"),
            ("flowmapStrengthAcceleration",       "flowmapStrengthCoef"),
            ("flowmapStrengthAccelerationJitter", "flowmapStrengthCoefJitter"),
        )
    },

    # UVCONTROL：官方 Offset / OffsetAdd / OffsetCoef（Scale 同构）三件套
    ("UVCONTROL", "uv1_initialPosition"): "uv1_offset",
    ("UVCONTROL", "uv1_speed"): "uv1_offsetAdd",
    ("UVCONTROL", "uv1_acceleration"): "uv1_offsetCoef",
    ("UVCONTROL", "uv1_scaleSpeed"): "uv1_scaleAdd",
    ("UVCONTROL", "uv1_scaleAcceleration"): "uv1_scaleCoef",
    ("UVCONTROL", "uv2_initialPosition"): "uv2_offset",
    ("UVCONTROL", "uv2_speed"): "uv2_offsetAdd",
    ("UVCONTROL", "uv2_acceleration"): "uv2_offsetCoef",
    ("UVCONTROL", "uv2_scaleSpeed"): "uv2_scaleAdd",
    ("UVCONTROL", "uv2_scaleAcceleration"): "uv2_scaleCoef",

    # UVSEQUENCE：官方 mSequenceNo / mPatternNo / mPlaySpeed / mPlaySpeedCoef
    ("UVSEQUENCE", "uvs_index"): "sequenceNo",          # 0.5.3 中间名 uvsIndex 见下条
    ("UVSEQUENCE", "uvsIndex"): "sequenceNo",
    ("UVSEQUENCE", "uvsIndexJitter"): "sequenceNoJitter",
    ("UVSEQUENCE", "unkn2"): "sequenceNoJitter",        # 覆盖上一轮 unkn2→uvsIndexJitter
    ("UVSEQUENCE", "startingFrame"): "patternNo",
    ("UVSEQUENCE", "startingFrameJitter"): "patternNoJitter",
    ("UVSEQUENCE", "animationSpeed"): "playSpeed",
    ("UVSEQUENCE", "animationSpeedJitter"): "playSpeedJitter",
    ("UVSEQUENCE", "animationAcceleration"): "playSpeedCoef",
    ("UVSEQUENCE", "animationAccelerationJitter"): "playSpeedCoefJitter",

    # ROTATEANIM：两组 Accel 语料上均为 1.0 中性 → 系数
    ("ROTATEANIM", "billboardRotationAccel"): "billboardRotationCoef",
    ("ROTATEANIM", "billboardRotationAccelJitter"): "billboardRotationCoefJitter",
    ("ROTATEANIM", "spinAccelerationX"): "spinSpeedCoefX",
    ("ROTATEANIM", "spinAccelerationXJitter"): "spinSpeedCoefXJitter",
    ("ROTATEANIM", "spinAccelerationY"): "spinSpeedCoefY",
    ("ROTATEANIM", "spinAccelerationYJitter"): "spinSpeedCoefYJitter",
    ("ROTATEANIM", "spinAccelerationZ"): "spinSpeedCoefZ",
    ("ROTATEANIM", "spinAccelerationZJitter"): "spinSpeedCoefZJitter",

    # VELOCITY2D / VELOCITY3D：同族系数（推翻 2026-07-26 保留 acceleration 的命名）
    ("VELOCITY3D", "acceleration"): "speedCoef",
    ("VELOCITY3D", "accelerationJitter"): "speedCoefJitter",
    ("VELOCITY3D", "elasticity"): "speedCoef",               # 0.5.0 前的更早旧名
    ("VELOCITY3D", "elasticityJitter"): "speedCoefJitter",
    ("VELOCITY2D", "acceleration"): "speedCoef",
    ("VELOCITY2D", "accelerationJitter"): "speedCoefJitter",

    # PARENTOPTIONS：官方 mRelationPos/Rot/Scl、mParticleUseLocal、mConstRelease、mJointNo
    ("PARENTOPTIONS", "translation_tracking"): "relationPos",
    ("PARENTOPTIONS", "angle_tracking"): "relationRot",
    ("PARENTOPTIONS", "scale_tracking"): "relationScl",
    ("PARENTOPTIONS", "spawnTrack"): "particleUseLocal",
    ("PARENTOPTIONS", "lockToPositionFrame"): "constRelease",
    ("PARENTOPTIONS", "lockToPositionFrameJitter"): "constReleaseJitter",
    ("PARENTOPTIONS", "spawnLock"): "constRelease",          # 0.5.0 前的更早旧名
    ("PARENTOPTIONS", "bleedPos"): "constReleaseJitter",
    ("PARENTOPTIONS", "bone_lim"): "jointNo",

    # ⚠ LIGHTNING 的 unkn15 / unkn13 是**字段拆分**（一个 ('f',N) 拆成多个），dtype 与
    #   大小都变了，本表覆盖不了——那两处只能靠重新导入，故意不在这里登记。
}
