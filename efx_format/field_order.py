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
    # ── use*/enable* 开关离它管的字段太远 ──────────────────────────────────
    # 语义读法是「颜色 / 颜色范围 / 启用颜色范围」，官方结构却把开关甩在几行之后
    # （MESH 最远，隔了 15~16 行，中间横着 rotation/scale/flags）。
    "BILLBOARD2D":  {"useColorRange": "colorRange"},
    "BILLBOARD3D":  {"useColorRange": "colorRange"},
    "PLANE":        {"useColorRange": "colorRange"},
    "RIBBON":       {"useColorRange": "colorRange"},
    "STRAINRIBBON": {"useColorRange": "colorRange"},
    "MESH": {
        "useColorRange":         "colorRange",
        "useEmissiveColor":      "emissiveColor",
        "useEmissiveColorRange": "emissiveColorRange",
    },

    # ── 一组被别的字段插了一脚 ────────────────────────────────────────────
    # billboardRotation 和它的 Coef 中间卡着 spin_velocity；挪开后
    # 「公告板旋转 + 系数」连上，spin_velocity 正好接到 spinSpeedCoef* 前面。
    "ROTATEANIM": {"spin_velocity": "billboardRotationCoef"},
    # distanceMod0 / distanceMod1 被 prop2/prop3/direction 隔开 10 行。
    "RAYCAST": {"distanceMod1": "distanceMod0"},
    # rangeDivideAxis（分几段的轴）离 rangeDivideHorizontal/VerticalNum（分几段）
    # 隔了 8 行，中间是 localRotation/scanAngle。挪到 scanAngleVertical 之后
    # 就紧贴着它那两个 Num。⚠ 这条是判断，不是实测；觉得不对删掉即可。
    "EMITTERSHAPE3D": {"rangeDivideAxis": "scanAngleVertical"},
}


def display_anchors(type_name: str) -> dict:
    """某属性类型的顺序订正表；没登记的类型返回空字典（=保持字节序）。"""
    return FIELD_ORDER_ANCHORS.get(type_name) or {}
