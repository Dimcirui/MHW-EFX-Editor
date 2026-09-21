# -*- coding: utf-8 -*-
"""
efx_format/field_order.py — 字段显示顺序的定点订正表（锚点）。

**默认信字节序。** 2026-08-18 拿全语料核过：结构体里的字段顺序本来就是语义序——
`VELOCITY3D` 的 `baseAxis·rotOrder·rotationXYZ | speed·speedCoef | velocityXYZ·divergenceXYZ`、
`RIBBON` 的 flowmap 八件套 / `base_*`+`tip_*` / `flap1*`+`flap2*` 都是连在一起的。
所以这里**不做全局重排**，只登记少数确实错位的字段：「这一行画到那一行后面」。

新增一条前先确认它真的错位（`tools/scan_field_order.py` 会列出候选），别凭感觉搬——
搬错了比不搬更难认。全部只影响显示：`field_items` 的次序仍是字节序，导出走
`rebuild_data_bytes`，跟本表无关。

键 = 类型名，值 = {要搬的字段: 搬到哪个字段之后}。搬动以「行」为单位——
value+jitter 配对会整对一起走，锚点字段带 jitter 时也落在它那一对之后。
"""

FIELD_ORDER_ANCHORS = {
    # ── use*/enable* 开关：2026-09-20 起统一改成"开关在它管的字段**前面**、
    # 当门控用"（勾了才显示下面的字段），取代早期"开关跟在字段后面、纯读顺序"
    # 的老约定（那套只管顺序、不做门控，见 git 历史）。RIBBON/STRAINRIBBON 的
    # useColorRange 官方字节序本来就已经在 colorRange 前面，不需要搬。
    # ⚠ flowmapPath 锚点目标必须是 value+jitter 配对里的「值」半边（如 height），
    # 不能写 jitter 半边（heightJitter）——jitter 名不是 unit 的 lead 名，reorder_units
    # 的 lead_at 查表会找不到，锚点整条静默失效（2026-09-20 排查用户反馈"PLANE 流动
    # 贴图路径没挪"时发现，BILLBOARD2D/3D 有同款笔误，一并修）。
    "BILLBOARD2D":  {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
        "flowmapPath":             "height",
    },
    "BILLBOARD3D":  {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
        "flowmapPath":             "height",
    },
    "PLANE":        {
        "correctColorNo":          "applicationRule",
        "useColorRange":           "color",
        "colorRangeCorrectColorNo": "useColorRange",
        "blendMode":               "colorRange",
        "flowmapPath":             "height",
    },
    "RIBBON":       {
        "flowmapPath": "enableFlowmap",
        # epvcolor_0/1：同 STRAINRIBBON 的 epv_color_slot1/2 一套机制（见 custom_codecs.py
        # 该字段注释），0 管 color、1 管 colorRange，按 correctColorNo 家族同款规则
        # 搬到各自对应颜色上面。spacer0/spacer1 分别是 color/colorRange 前面那个
        # 只读填充字段，借来当锚点。
        "epvcolor_0": "spacer0",
        "epvcolor_1": "spacer1",
    },
    "STRAINRIBBON": {
        "flowmapPath": "enableFlowmap",
        # epv_color_slot1/2：官方注释已经写明"slot1 管 color、slot2 管 colorRange"
        # （见 custom_codecs.py 该字段注释），不是位置类推——离 color/colorRange
        # 有 90+ 行远，按 correctColorNo 家族同款规则搬到各自对应的颜色上面。
        "epv_color_slot1": "spacer00",
        "epv_color_slot2": "useColorRange",
    },
    "LIGHTNING":    {"flowmapPath": "enableFlowmap"},
    # RIBBONBLADE：没有独立的 flowmap 总开关（全语料没找到），只搬路径字段。
    # tailEnd.spacer5 是 EPVColorSlot 结构体展开后紧贴 flowmapSpeed 前面的最后一个
    # 叶子字段（保留填充位，UI 上默认灰显，但字节序位置仍在这里，可以当锚点用）。
    "RIBBONBLADE":  {"flowmapPath": "tailEnd.spacer5"},
    # MESH：color/colorRange 与 emissiveColor/emissiveColorRange 各自的开关都是
    # "紧跟主字段之后、紧挨随机范围字段之前"这套（color→useColorRange→colorRange→
    # useEmissiveColor→emissiveColor→useEmissiveColorRange→emissiveColorRange），
    # 官方字节序把三个开关甩到 11 行之后（中间横着 rotationOrder/tracking_flags/
    # epv_color_slot* 等一堆不相关字段），搬到这里跟它们各自门控的字段贴在一起。
    # ⚠ 这个 dict 字面量以前意外重复写了两次"MESH"键（Python 静默用后一个覆盖
    # 前一个），导致这三条锚点从写下的那天起就从未真正生效过，2026-09-20 发现
    # 后合并成一条。
    # colorRate/emissiveColorRate（"颜色强度"/"自发光强度"）官方字节序甩在最前面
    # （紧跟 CD1，比 color/colorRange 还早），2026-09-20 按用户要求分别搬到各自
    # 归属的组尾（colorRange 之后 / emissiveColorRange 之后）。⚠ 同一个锚点目标
    # 不能被两条锚点同时指向——reorder_units 每条锚点只保证"直接落在目标后面"，
    # 两条都指向同一个目标时，后处理的那条会插进去把先处理的那条挤开，导致先处理
    # 那条不再紧贴目标（ui_layout_sim.py 的"锚点没落位"检查能抓到）。改用链式：
    # colorRate 先接到 colorRange 后面，useEmissiveColor 再接到 colorRate 后面，
    # 保证 colorRange→colorRate→useEmissiveColor 逐个都紧贴前一个。
    # rotationOrder 原锚点写的是"emissiveColorRate"——2026-09-20 发现这是笔误
    # （emissiveColorRate 当时改名前的位置就在最前面，导致 rotationOrder 被搬到
    # 整个块顶部，而不是本来想要的"贴在 rotation 后面"），改成锚定 "rotation"。
    "MESH": {
        "useColorRange":         "color",
        "colorRate":             "colorRange",
        "useEmissiveColor":      "colorRate",
        "useEmissiveColorRange": "emissiveColor",
        "emissiveColorRate":     "emissiveColorRange",
        "rotationOrder":         "rotation",
    },

    # ── 一组被别的字段插了一脚 ────────────────────────────────────────────
    # billboardRotation 和它的 Coef 中间卡着 spin_velocity；挪开后
    # 「公告板旋转 + 系数」连上，spin_velocity 正好接到 spinSpeedCoef* 前面。
    "ROTATEANIM": {"spin_velocity": "billboardRotationCoef"},
    # maxDistance / speed（原 distanceMod0/distanceMod1，2026-09-19 三向对调改名后
    # 锚点同步更新）被 prop2/startOffset/direction 隔开 10 行。
    "RAYCAST": {"speed": "maxDistance"},
    # VELOCITY3D：2026-09-20 用户要求的整体重排（非局部纠错，例外）。官方字节序是
    # baseAxis·rotOrder·rotationXYZ | speed·speedCoef | offset·size | velocityType |
    # gravity | movementDelay | gravityDelay | minMovementThreshold——方向/位移两组
    # 专属字段夹在 typeFlag 和 speed 之间，gravity 也被夹在 velocityType 和
    # movementDelay 中间。改成 typeFlag → 初速度/加速度/运动延迟 → velocityType →
    # 各类型专属字段（方向组 / 位移组 / minMovementThreshold，三组本身门控见
    # field_visibility.py）→ 重力/重力延迟垫底。只影响显示，字节序不变。
    "VELOCITY3D": {
        "speed":                 "typeFlag",
        "speedCoef":             "speed",
        "movementDelay":         "speedCoef",
        "velocityType":          "movementDelay",
        "minMovementThreshold":  "sizeZ",
    },
    # rangeDivideAxis（分几段的轴）离 rangeDivideHorizontal/VerticalNum（分几段）
    # 隔了 8 行，中间是 localRotation/scanAngle。挪到 scanAngleVertical 之后
    # 就紧贴着它那两个 Num。⚠ 这条是判断，不是实测；觉得不对删掉即可。
    # rayCastDependency（原 unknBitmaskRadiusRelated）2026-09-20 用户要求挪到 shapeType
    # 上面——rangeXYZ 和 shapeType 中间只隔这一行，锚到 rangeXYZ 即可紧贴 shapeType 前面。
    "EMITTERSHAPE3D": {
        "rangeDivideAxis": "scanAngleVertical",
        "rayCastDependency": "rangeXYZ",
    },
    # （MESH.rotationOrder 落在 rotation 之后 13 行的锚点已经合并进上面那个
    # "MESH" 字典条目，理由见那里的注释——以前这里单独重复了一次"MESH"键，
    # Python 字面量里同名键后者覆盖前者，导致这条锚点一直没生效，2026-09-20 修。）

    # ── RGBFIRE：2026-09-20 用户要求的整体重排（非局部纠错，例外）────────────
    # 官方字节序把两个全局旋钮（colorRate/alphaFactor）、两组生命期时序块
    # （fire/smoke）和 lerpAlphaToBlue 混在一起，读起来要来回跳。按用户指定的
    # 分组重排：全局亮度/透明度在最前 → 火焰组（EPV槽位/颜色/强度/受光照/启用
    # 生命周期/淡入淡出/生命期模式）→ 烟雾组（同构）→ lerpAlphaToBlue 单独垫底。
    # 面板侧对应加了分组小标题/分隔线和行内简化标签，见 panels.py
    # `_draw_rgbfire_group_header`/相关分支。只影响显示，字节序不变。
    "RGBFIRE": {
        "colorRate":                       "typeFlag",
        "alphaFactor":                     "colorRate",
        "fireColorParam_correctColorNo":   "alphaFactor",
        "fireColor":                       "fireColorParam_correctColorNo",
        "fireFactor":                      "fireColor",
        "fireColorParam_lighting":         "fireFactor",
        "fireColorParam_useLife":          "fireColorParam_lighting",
        "fireColorParam_appearFrame":      "fireColorParam_useLife",
        "fireColorParam_keepFrame":        "fireColorParam_appearFrame",
        "fireColorParam_vanishFrame":      "fireColorParam_keepFrame",
        "fireColorParam_lifeType":         "fireColorParam_vanishFrame",
        "smokeColorParam_correctColorNo":  "fireColorParam_lifeType",
        "smokeColor":                      "smokeColorParam_correctColorNo",
        "redChFactor":                     "smokeColor",
        "smokeColorParam_lighting":        "redChFactor",
        "smokeColorParam_useLife":         "smokeColorParam_lighting",
        "smokeColorParam_appearFrame":     "smokeColorParam_useLife",
        "smokeColorParam_keepFrame":       "smokeColorParam_appearFrame",
        "smokeColorParam_vanishFrame":     "smokeColorParam_keepFrame",
        "smokeColorParam_lifeType":        "smokeColorParam_vanishFrame",
        "lerpAlphaToBlue":                 "smokeColorParam_lifeType",
    },

    # ── RGBWATER：2026-09-20 用户要求的整体重排，跟 RGBFIRE 同一批（非局部纠错，
    # 例外）。全局旋钮（colorRate/intensityAlpha/normalSharpness）在最前 → 高光组
    # → 水膜组（同构）→ 环境反射组（cubemapPath+intensityCubeMap）→ 插值组
    # （waterLerpGtoB 单独垫底，同 RGBFIRE 的 lerpAlphaToBlue）。面板侧对应的分组
    # 小标题/分隔线/行内简化标签见 panels.py 的 RGBWATER 专属分支。只影响显示，
    # 字节序不变。
    "RGBWATER": {
        "colorRate":                       "typeFlag",
        "intensityAlpha":                  "colorRate",
        "normalSharpness":                 "intensityAlpha",
        "specularColorParam_correctColorNo": "normalSharpness",
        "colorSpecular":                   "specularColorParam_correctColorNo",
        "intensitySpecular":               "colorSpecular",
        "specularColorParam_lighting":     "intensitySpecular",
        "specularColorParam_useLife":      "specularColorParam_lighting",
        "specularColorParam_appearFrame":  "specularColorParam_useLife",
        "specularColorParam_keepFrame":    "specularColorParam_appearFrame",
        "specularColorParam_vanishFrame":  "specularColorParam_keepFrame",
        "specularColorParam_lifeType":     "specularColorParam_vanishFrame",
        "sheetColorParam_correctColorNo":  "specularColorParam_lifeType",
        "colorSheet":                      "sheetColorParam_correctColorNo",
        "intensitySheet":                  "colorSheet",
        "sheetColorParam_lighting":        "intensitySheet",
        "sheetColorParam_useLife":         "sheetColorParam_lighting",
        "sheetColorParam_appearFrame":     "sheetColorParam_useLife",
        "sheetColorParam_keepFrame":       "sheetColorParam_appearFrame",
        "sheetColorParam_vanishFrame":     "sheetColorParam_keepFrame",
        "sheetColorParam_lifeType":        "sheetColorParam_vanishFrame",
        "cubemapPath":                     "sheetColorParam_lifeType",
        "intensityCubeMap":                "cubemapPath",
        "waterLerpGtoB":                   "intensityCubeMap",
        "waterLerpParam_lighting":         "waterLerpGtoB",
        "waterLerpParam_useLife":          "waterLerpParam_lighting",
        "waterLerpParam_appearFrame":      "waterLerpParam_useLife",
        "waterLerpParam_keepFrame":        "waterLerpParam_appearFrame",
        "waterLerpParam_vanishFrame":      "waterLerpParam_keepFrame",
        "waterLerpParam_lifeType":         "waterLerpParam_vanishFrame",
    },

    # ── TRANSFORM3D：2026-09-20 用户要求的整体重排（非局部纠错，例外）──────────
    # 官方字节序把 velocity/modifier 三对 XYZ 交错排列（translation_velocity,
    # translation_velocity_modifier, rotation_velocity, rotation_velocity_modifier,
    # scale_velocity, scale_velocity_modifier），改成 3 个 velocity 连续在一起、
    # 3 个 modifier 连续在一起，这样才能在两组前面各插一行"启用速度"/"启用加速度"
    # 勾选框（拆自 enableVelocityBitflag，见 panels.py 的 TRANSFORM3D 专属分支），
    # 勾哪个对应那组字段就跟着冒出来，而不是勾选框画在所有字段后面。只影响显示，
    # 字节序不变；enableVelocityBitflag 本身不再单独成行（两个位分别画在这两组
    # 前面），不需要再挪它的位置。
    "TRANSFORM3D": {
        "rotation_velocity":             "translation_velocity",
        "scale_velocity":                "rotation_velocity",
        "translation_velocity_modifier": "scale_velocity",
        "rotation_velocity_modifier":    "translation_velocity_modifier",
        "scale_velocity_modifier":       "rotation_velocity_modifier",
    },
}


def display_anchors(type_name: str) -> dict:
    """某属性类型的顺序订正表；没登记的类型返回空字典（=保持字节序）。"""
    return FIELD_ORDER_ANCHORS.get(type_name) or {}
