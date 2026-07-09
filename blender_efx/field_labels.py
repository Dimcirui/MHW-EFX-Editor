# -*- coding: utf-8 -*-
"""
blender_efx/field_labels.py — 字段中文标签表（纯数据，零 bpy 依赖）

字段标签默认走 panels._friendly_name（英文友好名，从 schema ori_name 机械派生）。
中文模式（i18n.get_lang()=='ZH'）时改查本表的中文标签；查不到回退英文友好名。

键 = schema ori_name（与 structs.py 的 ATTR_SCHEMA_MAP 字段名一致）。
按 ori_name 单键（同名字段跨类型语义一致，共用一个中文标签）。

刻意不收录的（回退英文）：
  - 单字母 / 占位（_, c, f0, i0, m, o, s, t, u …）、spacer*、fixed70：结构占位/不透明，无语义。
  - unkn* / *_unkn* / int_unkn / float_unkn：未知字段，保留英文观测名更诚实。
覆盖范围：250 个有意义 ori_name 中的可命名项；增改 schema 字段时同步维护本表。
"""

FIELD_LABELS_ZH = {
    # ── 运动 / 速度 / 加速度 ───────────────────────────────────────────────
    "accel": "加速度",
    "accelJitter": "加速度抖动",
    "speed": "速度",
    "speedJitter": "速度抖动",
    "speedMultiplier": "速度倍率",
    "velocityX": "X 速率",
    "velocityY": "Y 速率",
    "velocityZ": "Z 速率",
    "translation_velocity": "平移速度",
    "translation_velocity_modifier": "平移速度修正",
    "rotation_velocity": "旋转速度",
    "rotation_velocity_modifier": "旋转速度修正",
    "scale_velocity": "缩放速度",
    "scale_velocity_modifier": "缩放速度修正",
    "spin_velocity": "自旋速度",
    "spin_acceleration": "自旋加速度",
    "main_axis_speed": "主轴速度",
    "main_axis_speed2": "主轴速度2",
    "secondary_axis_speed": "次轴速度",
    "secondary_axis_speed2": "次轴速度2",
    "energyOnAxisX": "X 轴能量",
    "energyOnAxisY": "Y 轴能量",
    "energyOnAxisZ": "Z 轴能量",
    "momentum_retention": "动量保留率",

    # ── 变换 ───────────────────────────────────────────────────────────────
    "transform": "变换",
    "translate": "平移",
    "rotate": "旋转",
    "resize": "缩放",
    "rotationOrder": "旋转顺序",
    "direction": "方向",
    "rotation": "旋转",
    "rotationJitter": "旋转抖动",
    "rotationX": "X 旋转",
    "rotationXJitter": "X 旋转抖动",
    "rotationY": "Y 旋转",
    "rotationYJitter": "Y 旋转抖动",
    "rotationZ": "Z 旋转",
    "rotationZJitter": "Z 旋转抖动",
    "trayectoryRotationX": "轨迹旋转 X",
    "trayectoryRotationY": "轨迹旋转 Y",
    "trayectoryRotationZ": "轨迹旋转 Z",
    "offsetX": "X 偏移",
    "offsetXJitter": "X 偏移抖动",
    "offsetY": "Y 偏移",
    "offsetYJitter": "Y 偏移抖动",
    "initialPosition": "初始位置",
    "initialPositionJitter": "初始位置抖动",
    "scaleAccel": "缩放加速度",
    "scaleAccelJitter": "缩放加速度抖动",
    "scaleSpeed": "缩放速度",
    "scaleSpeedJitter": "缩放速度抖动",
    # SCALEANIM 社区验证语义（初始 + 逐轴 X/Y/Z）
    "initialScaleSpeed": "初始扩散速度",
    "initialScaleAccel": "初始扩散加速度",
    "initialScaleAccelJitter": "初始扩散加速度抖动",
    "scaleSpeedX": "X 缩放速度",
    "scaleSpeedXJitter": "X 缩放速度抖动",
    "scaleAccelX": "X 缩放加速度",
    "scaleAccelXJitter": "X 缩放加速度抖动",
    "scaleSpeedY": "Y 缩放速度",
    "scaleSpeedYJitter": "Y 缩放速度抖动",
    "scaleAccelY": "Y 缩放加速度",
    "scaleAccelYJitter": "Y 缩放加速度抖动",
    "scaleSpeedZ": "Z 缩放速度",
    "scaleSpeedZJitter": "Z 缩放速度抖动",
    "scaleAccelZ": "Z 缩放加速度",
    "scaleAccelZJitter": "Z 缩放加速度抖动",
    "animUpdateStart": "动画更新开始时间",
    "animUpdateStartJitter": "动画更新开始时间抖动",

    # ── 跟踪 ───────────────────────────────────────────────────────────────
    "translation_tracking": "平移跟踪",
    "angle_tracking": "角度跟踪",
    "scale_tracking": "缩放跟踪",
    "spawnTrack": "跨生成追踪",

    # ── 生成 / 寿命 ─────────────────────────────────────────────────────────
    "instancesSpawnedTotal": "生成总数",
    "instancesSpawnedPerFrame": "每帧生成数",
    "frameDelayBetweenSpawns": "生成间隔（帧）",
    "durationOfSpawnerLifespan": "发射器寿命（帧）",
    "randomizedDelay": "生成间隔抖动（帧）",
    "randomizedLifespan": "发射器寿命抖动（帧）",
    "randomizedSpawnsPerFrame": "每帧随机生成数",
    "instanceCountUnknLimit": "实例数上限",
    "instanceCountUnknLimitJitter": "实例数上限抖动",
    "repeatAtribute": "重复属性",
    "occur": "生成延迟（帧）",
    "occur2": "生成延迟抖动（帧）",
    "spawnAngleLimits": "生成角度限制",
    "spawnCount": "生成数量",
    "spawnLock": "锁定到位置",
    "spawnPerCycle": "每周期生成数",
    "spawnTotal": "生成总数",
    "lifespan": "寿命",
    "lifespanJitter": "寿命抖动",
    "duration": "持续时间",
    "durationJitter": "持续时间抖动",
    "delay": "延迟",
    "delayJitter": "延迟抖动",
    "indefiniteLifespan": "无限寿命",
    "timeToDeath": "死亡时间",
    "timeToDeathJitter": "死亡时间抖动",
    "fadeInDuration": "淡入时长",
    "fadeInDurationJitter": "淡入时长抖动",
    "fadeOutDuration": "淡出时长",
    "fadeOutDurationJitter": "淡出时长抖动",
    "fadeStart": "淡出起点",
    "status": "状态",

    # ── 引用 / 索引 ─────────────────────────────────────────────────────────
    "ieIndex": "碰撞触发 Play",
    "relationIndex": "关联 Play",
    "referenceIndex": "Extern 引用",
    "body_p": "关联 Body",
    "wp_p": "关联武器",
    "body_part_id": "身体部位 ID",
    "weapon_id": "武器 ID",
    "bone_lim": "绑定骨骼",

    # ── 颜色 / 亮度 / 透明 ─────────────────────────────────────────────────
    "color": "颜色",
    "color1": "颜色1",
    "color2": "颜色2",
    "colorRange": "颜色范围",
    "useColorRange": "启用颜色范围",
    "emissiveColor": "自发光颜色",
    "emissiveColorRange": "自发光颜色范围",
    "useEmissiveColor": "启用自发光颜色",
    "useEmissiveColorRange": "启用自发光颜色范围",
    "enableIntensity1": "亮度增强1",
    "enableIntensity2": "亮度增强2",
    "enableEmissiveIntensity": "自发光亮度增强",
    "disableAllColorRange": "禁用所有颜色范围",
    # RGBFIRE 实机确认：fireColor=外缘荧光色（会给 smokeColor 染色），smokeColor=内部色
    "fireColor": "火焰色",
    "smokeColor": "烟雾色",
    "fireColorParam_enable": "火焰色 启用",
    "fireColorParam_duration": "火焰色 持续时间",
    "fireColorParam_durationJitter": "火焰色 持续时间抖动",
    "fireColorParam_fadeIn": "火焰色 淡入",
    "fireColorParam_fadeInJitter": "火焰色 淡入抖动",
    "fireColorParam_fadeOut": "火焰色 淡出",
    "fireColorParam_fadeOutJitter": "火焰色 淡出抖动",
    "smokeColorParam_enable": "烟雾色 启用",
    "smokeColorParam_duration": "烟雾色 持续时间",
    "smokeColorParam_durationJitter": "烟雾色 持续时间抖动",
    "smokeColorParam_fadeIn": "烟雾色 淡入",
    "smokeColorParam_fadeInJitter": "烟雾色 淡入抖动",
    "smokeColorParam_fadeOut": "烟雾色 淡出",
    "smokeColorParam_fadeOutJitter": "烟雾色 淡出抖动",
    "epv_color_slot": "EPV 颜色槽",
    "epvcolorslot": "EPV 颜色槽",
    "bright": "亮度",
    "brightness": "亮度",
    "brightness1": "亮度1",
    "brightness2": "亮度2",
    "brightness3": "亮度3",
    "brightness4": "亮度4",
    "opacity": "不透明度",
    "opacityJitter": "不透明度抖动",
    "opacityAcceleration": "不透明度加速度",
    "opacityAccelerationJitter": "不透明度加速度抖动",
    "alpha_effect": "透明度效果",
    "alpha_threshold": "透明度阈值",
    "lowPass": "低通阈值",
    "contrast_gamma": "对比度/伽马修正",

    # ── TUBELIGHT 专属 ─────────────────────────────────────────────────────
    "headColor": "光柱起点颜色",
    "tailColor": "光柱终点颜色",
    "headColorEpvSlot": "起点颜色 EPV 颜色槽",
    "columnLength": "光柱长度",
    "columnLengthModifier": "光柱长度修正",
    "columnRadius": "光柱半径",
    "columnRadiusJitter": "光柱半径抖动",
    "columnEdgeSoftness": "光柱边缘柔化",
    "lightIntensity": "光照强度",
    "lightIntensityJitter": "光照强度抖动",
    "tailGlowSpread": "尾光扩散(变长+边缘虚化)",
    "backFaceTintMode": "反向区域受起点色染色",
    "frontFaceTintMode": "朝向区域受终点色染色",
    "tailPlaneOffset": "终点发光面前后位置",

    # ── 材质 / 着色 ─────────────────────────────────────────────────────────
    "metallicness_multiplier": "金属度倍率",
    "roughness_multiplier": "粗糙度倍率",
    "subsurface_multipler": "次表面倍率",
    "normal_map_strength": "法线贴图强度",
    "pixelNormalOffset": "像素法线偏移",
    "rimParam": "边缘光参数",
    "blendParam": "混合参数",
    "animationSpeed": "动画速度",
    "extraMaterialInitialPosition": "附加材质初始位置",
    "extraMaterialInitialPositionJ": "附加材质初始位置抖动",
    "extraMaterialSpeed": "附加材质速度",
    "extraMaterialSpeedJitter": "附加材质速度抖动",

    # ── 几何 / 尺寸 / 半径 ─────────────────────────────────────────────────
    "width": "宽度",
    "widthJitter": "宽度抖动",
    "height": "高度",
    "heightJitter": "高度抖动",
    "length": "长度",
    "lengthJitter": "长度抖动",
    "section_length": "段长度",
    "radius": "半径",
    "radiusOrigin": "起始半径",
    "radiusEnd": "结束半径",
    "innerRadius": "内半径",
    "innerRadiusJitter": "内半径抖动",
    "outerRadius": "外半径",
    "outerRadiusJitter": "外半径抖动",
    "area": "区域",
    "area_of_aura": "光环范围",
    "teleport_radius": "传送半径",
    "teleport_radius2": "传送半径2",
    "smooth_radius_randomized": "平滑半径随机",
    "smooth_radius_randomized2": "平滑半径随机2",
    "expansion_radius_limit": "扩散范围",
    "expansion_radius_jitter": "扩散范围偏差",
    "expansion_radius_elasticity": "扩散弹性",
    "expansion_radius_elasticity_jitter": "扩散弹性偏差",
    "expansionDelay": "扩散延迟",
    "expansionDelayJitter": "扩散延迟抖动",
    "expansionType": "扩散类型",
    "pattern": "图案",
    "patternControl": "图案控制",

    # ── 物理 / 碰撞 / 弹跳 ─────────────────────────────────────────────────
    "physicsEnum": "物理类型",
    "gravity": "重力",
    "gravity_jitter": "重力抖动",
    "gravityDelay": "重力延迟",
    "gravityDelayJitter": "重力延迟抖动",
    "bounce": "弹跳",
    "bounceJitter": "弹跳抖动",
    "bounceConditional": "条件弹跳",
    "bounceElasticity": "弹跳弹性",
    "bounceElasticityJitter": "弹跳弹性抖动",
    "bounceElasticityMultiplier": "弹跳弹性倍率",
    "horizontalBounce": "水平弹跳",
    "restitutionDelay": "回弹延迟",
    "restitutionDelayJitter": "回弹延迟抖动",
    "restitutionEccentricity": "回弹偏心率",
    "restitutionEccentricityJitter": "回弹偏心率抖动",
    "restitutionElasticity": "回弹弹性",
    "restitutionElasticityJitter": "回弹弹性抖动",
    "objectInteractionFlag0": "物体交互标志0",
    "objectInteractionFlag1": "物体交互标志1",
    "objectInteractionFlag2": "物体交互标志2",
    "objectInteractionFlag3": "物体交互标志3",

    # ── 位标志 / 控制 ───────────────────────────────────────────────────────
    "controlBitflag": "控制位标志",
    "enableVelocityBitflag": "启用速度位标志",
    "enableRadialVanish": "归航力控制",
    "viewAngleLimit": "视角限制",
    "visibleOnPreview": "预览中可见",
    # RIBBON 实测：原观测名 visiblePreview，实为"可见性修正"。非 0 会破坏 TIML 正常
    # 读取（条带读不到 animation1 颜色）并导致条带莫名缺失；安全值 0。
    "visiblePreview": "可见性修正",
    "clipMax": "裁剪上限",
    "clipMin": "裁剪下限",
    "zDepthModifierStart": "Z 深度修正（起始）",
    "zDepthModifierEnd": "Z 深度修正（结束）",

    # ── UV ──────────────────────────────────────────────────────────────────
    "uv1_initialPosition": "UV1 初始位置",
    "uv1_speed": "UV1 速度",
    "uv1_acceleration": "UV1 加速度",
    "uv1_scale": "UV1 缩放",
    "uv1_scaleSpeed": "UV1 缩放速度",
    "uv1_scaleAcceleration": "UV1 缩放加速度",
    "uv2_initialPosition": "UV2 初始位置",
    "uv2_speed": "UV2 速度",
    "uv2_acceleration": "UV2 加速度",
    "uv2_scale": "UV2 缩放",
    "uv2_scaleSpeed": "UV2 缩放速度",
    "uv2_scaleAcceleration": "UV2 缩放加速度",

    # ── 裂纹 / 渗出 / 其它效果 ─────────────────────────────────────────────
    "craquelure_threshold": "裂纹阈值",
    "craquelure_effect_diffumination": "裂纹效果扩散",
    "bleedPos": "渗出位置",
    "distanceMod0": "距离调制0",
    "distanceMod0Jitter": "距离调制0抖动",
    "distanceMod1": "距离调制1",
    "distanceMod1Jitter": "距离调制1抖动",

    # ── 通用属性 ───────────────────────────────────────────────────────────
    "randomBrightnessMult": "随机亮度乘数",
    "blendMode": "混合模式",
    "billboardRotation": "平面旋转",
    "billboardRotationSpeed": "平面旋转速度",
    "prop1": "属性1",
    "prop1Jitter": "属性1抖动",
    "prop2": "属性2",
    "prop3": "属性3",
    # ── UVSEQUENCE loopingEnum 拆分字段 ────────────────────────────────────
    "loopingMode": "循环模式",
    "loopingOrientation": "贴图朝向",
    "loopingPad": "保留",
}


# ─────────────────────────────────────────────────────────────────────────────
# 类型专属标签：键 = (TYPE_NAME, ori_name)，优先于全局表。
# 用于"同名字段在不同类型语义不同"或"unkn_* 经逆向有了语义名"的场景。
# 例：LIGHTNING 的 unkn05_*/unkn07_* 是闪电专属语义，绝不能用全局键（会误标到
# PTCOLLISION/SHOVEL 等共用 unkn 名的类型）。详细行为见 annotations.py 的 ⓘ 注释。
# ─────────────────────────────────────────────────────────────────────────────

FIELD_LABELS_ZH_BY_TYPE = {
    # ── LIGHTNING（闪电，社区逆向，2026-06）──────────────────────────────────
    ("LIGHTNING", "unkn05_01"): "实例模式标志",
    ("LIGHTNING", "sineWaveFreq"): "正弦波频率",
    ("LIGHTNING", "sineWaveFreqJitter"): "正弦波频率抖动",
    ("LIGHTNING", "alphaThreshold"): "alpha 阈值",
    ("LIGHTNING", "unkn05_05"): "分支禁用标志",
    ("LIGHTNING", "unkn05_06"): "分支起始偏移距离",
    ("LIGHTNING", "outwardsExpansionSpeed"): "向外扩展速度",
    ("LIGHTNING", "outwardsExpansionSpeedJitter"): "向外扩展速度抖动",
    ("LIGHTNING", "unkn05_10"): "闪电不透明度",
    ("LIGHTNING", "unkn05_11"): "闪电透明度等级B",
    ("LIGHTNING", "unkn05_12"): "流光与淡出模式",
    ("LIGHTNING", "targetBoneID"): "靶骨 ID",
    ("LIGHTNING", "inflectionPointCount"): "拐点计数",
    ("LIGHTNING", "uInflectionAngleLimit"): "倾角限制",
    ("LIGHTNING", "uInflectionAngleLimitJitter"): "倾角限制抖动",
    ("LIGHTNING", "vInflectionAngleLimit"): "弯曲角极限",
    ("LIGHTNING", "vInflectionAngleLimitJitter"): "弯曲角极限抖动",
    ("LIGHTNING", "inflectionPointCount2"): "拐点计数2",
    ("LIGHTNING", "uInflectionAngleLimit2"): "倾角限制2",
    ("LIGHTNING", "uInflectionAngleLimitJitter2"): "倾角限制2抖动",
    ("LIGHTNING", "vInflectionAngleLimit2"): "弯曲角极限2",
    ("LIGHTNING", "vInflectionAngleLimitJitter2"): "弯曲角极限2抖动",
    ("LIGHTNING", "glow"): "发光",
    ("LIGHTNING", "glowJitter"): "发光抖动",
    ("LIGHTNING", "startWidth"): "开始宽度",
    ("LIGHTNING", "uvRepetitionStart"): "UV 重复开始",
    ("LIGHTNING", "endWidth"): "结束宽度",
    ("LIGHTNING", "uvRepetitionEnd"): "UV 重复结束",
    ("LIGHTNING", "unkn05_47"): "支路闪电数量A",
    ("LIGHTNING", "unkn05_48"): "支路闪电数量B",
    ("LIGHTNING", "radiusLimit"): "半径极限",
    ("LIGHTNING", "radiusLimitJitter"): "半径极限抖动",
    ("LIGHTNING", "unkn07_02"): "支线弯曲角极限",
    ("LIGHTNING", "unkn07_03"): "支线弯曲角极限抖动",
    ("LIGHTNING", "unkn07_04"): "支线流动模式B开关",
    ("LIGHTNING", "unkn07_05"): "支线复杂度/扩散随机性",
    ("LIGHTNING", "unkn07_06"): "支线复杂度抖动",
    ("LIGHTNING", "unkn07_09"): "支线发光",
    ("LIGHTNING", "unkn07_10"): "支线发光抖动",
    ("LIGHTNING", "branchLength"): "支路长度",
    ("LIGHTNING", "branchLengthJitter"): "支路长度抖动",
    ("LIGHTNING", "unkn07_13"): "支线开始宽度",
    ("LIGHTNING", "unkn07_14"): "支线结束宽度",
    ("LIGHTNING", "unkn07_15"): "支线开始宽度抖动",
    ("LIGHTNING", "unkn07_16"): "支线 UV 重复开始",
    ("LIGHTNING", "unkn07_17"): "支线 UV 重复结束",
    ("LIGHTNING", "unkn07_18"): "支线结束宽度抖动",
    ("LIGHTNING", "emissive"): "自发光颜色",
    ("LIGHTNING", "EPVColorSlot1"): "EPV 颜色槽1",
    ("LIGHTNING", "EPVColorSlot2"): "EPV 颜色槽2",

    # ── HOMING（归航，系统实测逆向，2026-06）─────────────────────────────────
    ("HOMING", "f0"):              "归航角速度",
    ("HOMING", "f3"):              "渲染衰减系数",
    ("HOMING", "f4"):              "归航激活距离",
    ("HOMING", "radius"):          "力场衰减距离",
    ("HOMING", "i0"):              "归航模式",
    ("HOMING", "i1"):              "可见性标志",

    # ── VELOCITY2D（2D 速度，来源 EFX_Subtypes.bt）────────────────────────────
    ("VELOCITY2D", "unkn10"):                          "未知10",
    ("VELOCITY2D", "expansionRadius"):                 "扩张半径",
    ("VELOCITY2D", "expansionRadiusJitter"):           "扩张半径抖动",
    ("VELOCITY2D", "expansionRadiusElasticity"):       "扩张半径弹性",
    ("VELOCITY2D", "expansionRadiusElasticityJitter"): "扩张半径弹性抖动",
    ("VELOCITY2D", "energyOnAxisX"):                   "X 轴能量",
    ("VELOCITY2D", "energyOnAxisY"):                   "Y 轴能量",
    ("VELOCITY2D", "expansionType"):                   "扩张类型(0-1线性 2-3静止)",
    ("VELOCITY2D", "gravity"):                         "重力",
    ("VELOCITY2D", "gravityJitter"):                   "重力抖动",
    ("VELOCITY2D", "expansionDelay"):                  "扩张延迟",
    ("VELOCITY2D", "expansionDelayJitter"):            "扩张延迟抖动",
    ("VELOCITY2D", "gravityDelay"):                    "重力延迟",
    ("VELOCITY2D", "gravityDelayJitter"):              "重力延迟抖动",

    # ── BILLBOARD2D（2D 公告板，来源 EFX_Subtypes.bt）─────────────────────────
    ("BILLBOARD2D", "color1"):           "颜色1",
    ("BILLBOARD2D", "color2"):           "颜色2",
    ("BILLBOARD2D", "emissionMin"):      "自发光最小值",
    ("BILLBOARD2D", "emissionMax"):      "自发光最大值",
    ("BILLBOARD2D", "rotationJitterMin"):"旋转抖动最小值",
    ("BILLBOARD2D", "rotationJitterMax"):"旋转抖动最大值",
    ("BILLBOARD2D", "scaleJitterMin"):   "缩放抖动最小值",
    ("BILLBOARD2D", "scaleJitterMax"):   "缩放抖动最大值",
    ("BILLBOARD2D", "imageResolutionX"): "图像分辨率 X",
    ("BILLBOARD2D", "scaleX"):           "缩放 X",
    ("BILLBOARD2D", "imageResolutionY"): "图像分辨率 Y",
    ("BILLBOARD2D", "scaleY"):           "缩放 Y",

    # PLEMISSIVE body_p/wp_p 的显示名由面板 label_override 给出（Aura Part (Player)/(Weapon)），不在此表。

    # ── EMITTERSHAPE2D（2D 发射形状，来源 EFX_Subtypes.bt）────────────────────
    ("EMITTERSHAPE2D", "offsetX"):       "偏移 X",
    ("EMITTERSHAPE2D", "offsetXJitter"): "偏移 X 抖动",
    ("EMITTERSHAPE2D", "offsetY"):       "偏移 Y",
    ("EMITTERSHAPE2D", "offsetYJitter"): "偏移 Y 抖动",
    ("EMITTERSHAPE2D", "spawnCount"):    "生成数量",

    # ── RANDOMFIX ──────────────────────────────────────────────────────────
    ("RANDOMFIX", "useRandomSeedTableCount"): "种子表使用次数",
    ("RANDOMFIX", "randomSeedTable0"): "随机种子表 0",
    ("RANDOMFIX", "randomSeedTable1"): "随机种子表 1",
    ("RANDOMFIX", "randomSeedTable2"): "随机种子表 2",
    ("RANDOMFIX", "randomSeedTable3"): "随机种子表 3",
    ("RANDOMFIX", "randomSeedTable4"): "随机种子表 4",
    ("RANDOMFIX", "randomSeedTable5"): "随机种子表 5",
    ("RANDOMFIX", "randomSeedTable6"): "随机种子表 6",
    ("RANDOMFIX", "randomSeedTable7"): "随机种子表 7",
    ("RANDOMFIX", "tableSelectionGroup"): "种子表选择组",
}


def label_zh(ori_name, type_name=None):
    """返回字段中文标签；无则返回 None（由调用方回退英文友好名）。

    优先 (type_name, ori_name) 类型专属表，再回退 ori_name 全局表。
    """
    if type_name is not None:
        zh = FIELD_LABELS_ZH_BY_TYPE.get((type_name, ori_name))
        if zh is not None:
            return zh
    return FIELD_LABELS_ZH.get(ori_name)


# ─────────────────────────────────────────────────────────────────────────────
# 保留填充字段（0xCD 未初始化占位）——UI 中关闭编辑（只读灰显）
#
# 判据：tools/scan_fill_fields.py 全语料(10163 文件)统计，字段最高字节(MSB)==0xCD
# 的比例 ≥99%（基本 100%）。这些是引擎从不写入的保留/填充位（spacer*/unkn*/CD1 等），
# 编辑无意义且易写坏；导出时未编辑字段走原始字节，byte-perfect 不受影响。
# 键 = (type_name, ori_name)。如需放行某字段，删对应行即可。
# 重新生成：python3 tools/scan_fill_fields.py --all --emit-set
# ⚠ 已手动排除 3 个名字像真实字段、可能有语义的项（--emit-set 会再次列出它们，
#   重生成后需重新删除）：PLSNOW.alpha_effect、RIBBON.tailTiedToBone、STRAINRIBBON.color3_w。
# ─────────────────────────────────────────────────────────────────────────────

RESERVED_FILL_FIELDS = frozenset({
    ('BLINK', 'unkn1_0'),
    ('CHECKPUREATTRIBUTE', 'unkn1'),
    ('EMITTERSHAPEMESH', 'unkn1_0'),
    ('EMITTERSHAPEMESH', 'unkn1_1'),
    ('EMITTERSHAPEMESH', 'unkn1_2'),
    ('FADEBYEMITTERANGLE', 'unkn'),
    ('FADEBYOCCLUSION', 'unkn1'),
    ('FAKEDOF', 'unkn2'),
    ('FAKEPLANE', 'unkn4'),
    ('HOMING', 'spacer'),
    ('LIGHTNING', 'spacer0'),
    ('LIGHTNING', 'spacer05_00'),
    ('LIGHTNING', 'spacer05_14'),
    ('LIGHTNING', 'unkn02'),
    ('LIGHTNING', 'unkn03'),
    ('LIGHTNING', 'unkn05_21'),
    ('LIGHTNING', 'unkn05_46'),
    ('LIGHTNING', 'unkn07_20'),
    ('LUMINANCEBLEED', 'unkn0'),
    ('MESH', 'CD1'),
    ('NOISE', 'spacer'),
    ('OTOMOSNOW', 'unkn1'),
    ('OTOMOSNOW', 'unkn4'),
    ('OTOMOSNOW', 'unkn6'),
    ('PARENTSNOW', 'unkn1'),
    ('PARENTSNOW', 'unkn3_1'),
    ('PARENTSNOW', 'unkn4_4'),
    ('PATHCHAIN', 'unkn1'),
    ('PLSNOW', 'spacer'),
    ('PLSNOW', 'unkn5'),
    ('PTTRIGGER', 'unkn1'),
    ('RAYCAST', 'spacer0'),
    ('RAYCAST', 'spacer1'),
    ('RAYCAST', 'spacer2'),
    ('RAYCAST', 'spacer3'),
    ('RIBBON', 'spacer0'),
    ('RIBBON', 'spacer1'),
    ('RIBBON', 'spacer2'),
    ('RIBBON', 'spacer3'),
    ('RIBBON', 'spacer4'),
    ('RIBBON', 'spacer5'),
    ('RIBBON', 'spacer7'),
    ('RIBBON', 'spacer8'),
    ('RIBBON', 'spacer9'),
    ('RIBBON', 'unkn24'),
    ('RIBBONBLADE', 'spacer0'),
    ('RIBBONBLADE', 'spacer1'),
    ('RIBBONBLADE', 'spacer2'),
    ('RIBBONBLADE', 'spacer3'),
    ('SCREENSPACECOLLISION', 'spacer'),
    ('SHADERSETTINGS', 'spacer'),
    ('SHOVEL', 'spacer'),
    ('SPAWNBYANGLE', 'unkn1'),
    ('SPAWNBYOCCLUSION', 'unkn1'),
    ('STRAINRIBBON', 'spacer00'),
    ('STRAINRIBBON', 'spacer01'),
    ('STRAINRIBBON', 'spacer02'),
    ('STRAINRIBBON', 'spacer03'),
    ('TONEMAPFILTER', 'unkn1'),
    ('TUBELIGHT', 'unkn3_2'),
    ('TUBELIGHT', 'unkn5_1'),  # 恒 0xCDCDCDCD 未初始化标记（2026-07-01 实机测试确认，schema 拆分后新增）
})


def is_reserved_fill(type_name, ori_name) -> bool:
    """该字段是否为保留填充位（UI 关闭编辑）。"""
    return (type_name, ori_name) in RESERVED_FILL_FIELDS
