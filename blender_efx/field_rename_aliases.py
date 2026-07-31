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
    ("UVCONTROL", "extraMaterialSpeed"): "flowmapAcceleration",
    ("UVCONTROL", "extraMaterialSpeedJitter"): "flowmapAccelerationJitter",
    ("UVCONTROL", "opacity"): "flowmapStrength",
    ("UVCONTROL", "opacityJitter"): "flowmapStrengthJitter",
    ("UVCONTROL", "opacityAcceleration"): "flowmapStrengthAcceleration",
    ("UVCONTROL", "opacityAccelerationJitter"): "flowmapStrengthAccelerationJitter",

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
    ("RIBBON", "unkn23_2"): "flowmapAcceleration",
    ("RIBBON", "unknFixed23_3"): "flowmapAccelerationJitter",
    ("RIBBON", "unkn23_4"): "flowmapStrength",
    ("RIBBON", "unkn23_5"): "flowmapStrengthJitter",
    ("RIBBON", "unkn23_6"): "flowmapStrengthAcceleration",
    ("RIBBON", "unknFixed23_7"): "flowmapStrengthAccelerationJitter",
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
    ("STRAINRIBBON", "unkn06_2"): "flowmapAcceleration",
    ("STRAINRIBBON", "unknFixed06_3"): "flowmapAccelerationJitter",
    ("STRAINRIBBON", "unkn06_4"): "flowmapStrength",
    ("STRAINRIBBON", "unknFlag06_5"): "flowmapStrengthJitter",
    ("STRAINRIBBON", "unkn06_6"): "flowmapStrengthAcceleration",
    ("STRAINRIBBON", "unkn06_7"): "flowmapStrengthAccelerationJitter",
    # ⚠ LIGHTNING 的 unkn15 / unkn13 是**字段拆分**（一个 ('f',N) 拆成多个），dtype 与
    #   大小都变了，本表覆盖不了——那两处只能靠重新导入，故意不在这里登记。
}
