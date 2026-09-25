# -*- coding: utf-8 -*-
"""跨属性类型共用的字段分组：组标题、组内简化标签与虚拟行。

同一组字段在多个属性类型里语义相同（例如流动贴图），面板按本表统一绘制：整组按组内
顺序挪到面板末尾，首行之前画分隔线和组标题，组内行改用去掉前缀的短标签，位掩码里的
开关拆成独立的行。组外字段的顺序仍由 `efx_format/field_order.py` 的锚点表决定。

维护约束：
- 纯数据与纯函数，不 import bpy；Blender 控件在 panels.py 里绘制。
- 组内标签只改显示文字，注释查找仍用字段原名（虚拟行用 `anno` 指定的键）。
"""


class FieldGroup(object):
    """一组跨类型共用的字段。

    header       (中文, 英文) 组标题
    types        适用的属性类型名
    order        组内字段的显示顺序；整组挪到面板末尾
    labels       字段名 → (中文, 英文) 组内标签
    lead         类型名 → 组首行字段名；组标题画在它之前（该字段被隐藏时也画）
    bit_rows     类型名 → {"lead": [...], "after": {字段名: [...]}, "own": [...]}
                 lead  画在组标题之后、组首行之前的位行
                 after 画在某字段（或 value/jitter 行）之后的位行，同一列表内的位画在同一行
                 own   位掩码字段自身位置上仍保留的位行
    paired       (前一字段, 后一字段)：两个 Bool 画在同一行，后者在前者关闭时置灰
    """

    __slots__ = ("header", "types", "order", "labels", "lead", "bit_rows", "paired")

    def __init__(self, header, types, order, labels, lead, bit_rows=None, paired=None):
        self.header = header
        self.types = frozenset(types)
        self.order = tuple(order)
        self.labels = labels
        self.lead = lead
        self.bit_rows = bit_rows or {}
        self.paired = paired


_FLOW_BIT_TYPES = ("BILLBOARD3D", "PLANE", "BILLBOARD2D")
_FLOW_FIELD_TYPES = ("RIBBON", "STRAINRIBBON", "LIGHTNING", "RIBBONBLADE", "UVCONTROL")

#: 位掩码拆出的一行：(字段名, 位序号, 中文标签, 英文标签, 注释键)。
#: 注释键形如 "applicationRule.flowOnce"，登记在 annotations.py。
_AR_ENABLE = ("applicationRule", 2, "启用", "Enable", "applicationRule.enableFlowmap")
_AR_ONCE = ("applicationRule", 3, "播放一次后冻结", "Freeze After One Play",
            "applicationRule.flowOnce")
_AR_REVERSE = ("applicationRule", 4, "逆向播放", "Reverse Playback",
               "applicationRule.flowReverse")
_AR_UNKNOWN = ("applicationRule", 5, "未知位 0x20", "Unknown Bit 0x20", "applicationRule")

FLOWMAP = FieldGroup(
    header=("流动贴图", "Flowmap"),
    types=_FLOW_BIT_TYPES + _FLOW_FIELD_TYPES,
    order=("enableFlowmap", "flowmapPath",
           "flowSpeed", "flowSpeedJitter", "flowSpeedCoef", "flowSpeedCoefJitter",
           "flowStrength", "flowStrengthJitter", "flowStrengthCoef", "flowStrengthCoefJitter",
           "flowOnce", "flowReverse"),
    labels={
        "enableFlowmap":    ("启用", "Enable"),
        "flowmapPath":      ("贴图", "Texture"),
        "flowSpeed":        ("速度", "Speed"),
        "flowSpeedCoef":    ("加速度", "Acceleration"),
        "flowStrength":     ("强度", "Strength"),
        "flowStrengthCoef": ("强度加速度", "Strength Acceleration"),
        "flowOnce":         ("播放一次后冻结", "Freeze After One Play"),
        "flowReverse":      ("逆向播放", "Reverse Playback"),
    },
    lead={
        **{t: "flowmapPath" for t in _FLOW_BIT_TYPES},
        "RIBBON": "enableFlowmap",
        "STRAINRIBBON": "enableFlowmap",
        "LIGHTNING": "enableFlowmap",
        "UVCONTROL": "enableFlowmap",
        "RIBBONBLADE": "flowmapPath",
    },
    bit_rows={
        t: {"lead": [_AR_ENABLE],
            "after": {"flowStrengthCoef": [_AR_ONCE, _AR_REVERSE]},
            "own": [_AR_UNKNOWN]}
        for t in _FLOW_BIT_TYPES
    },
    paired=("flowOnce", "flowReverse"),
)

GROUPS = (FLOWMAP,)

#: 单一类型内的分段标题：类型名 → [(组首字段, (中文, 英文)), ...]。只画标题，不改标签和
#: 顺序；顺序由 efx_format/field_order.py 的锚点表决定。组首字段被隐藏时标题照画。
TYPE_SECTIONS = {
    "SPAWN": [
        ("maxParticles",      ("数量", "Count")),
        ("loopNum",           ("每轮", "Per Round")),
        ("revivalLoop",       ("复活", "Revival")),
        ("emitterDelayFrame", ("延迟", "Delay")),
        ("spawnFlags",        ("标志", "Flags")),
    ],
}


def groups_for(type_name):
    """该类型适用的分组。"""
    return [g for g in GROUPS if type_name in g.types]


def move_groups_to_end(type_name, items):
    """把各分组的字段按组内顺序挪到列表末尾；items 为带 ori_name 的对象列表。"""
    for g in groups_for(type_name):
        rank = dict((name, k) for k, name in enumerate(g.order))
        grp = [it for it in items if it.ori_name in rank]
        if grp:
            grp.sort(key=lambda it: rank[it.ori_name])
            items = [it for it in items if it.ori_name not in rank] + grp
    return items


def section_header(type_name, field_name):
    """以该字段为组首的分段标题 (中文, 英文)；没有返回 None。"""
    for lead, header in TYPE_SECTIONS.get(type_name, ()):
        if lead == field_name:
            return header
    return None


def is_first_section(type_name, field_name):
    sections = TYPE_SECTIONS.get(type_name)
    return bool(sections) and sections[0][0] == field_name


def row_label(type_name, field_name, zh):
    """组内标签；不属于任何组返回 None。"""
    for g in GROUPS:
        if type_name in g.types:
            lbl = g.labels.get(field_name)
            if lbl:
                return lbl[0] if zh else lbl[1]
    return None


def group_led_by(type_name, field_name):
    """以该字段为首行的分组；没有返回 None。"""
    for g in GROUPS:
        if type_name in g.types and g.lead.get(type_name) == field_name:
            return g
    return None


def lead_bit_rows(group, type_name):
    return group.bit_rows.get(type_name, {}).get("lead", [])


def bit_rows_after(type_name, field_name):
    """画在该字段之后的位行（同一列表画成一行）。"""
    for g in GROUPS:
        if type_name in g.types:
            rows = g.bit_rows.get(type_name, {}).get("after", {}).get(field_name)
            if rows:
                return rows
    return []


def own_bit_rows(type_name, field_name):
    """位掩码字段自身位置上保留的位行；该字段不由分组接管时返回 None。"""
    for g in GROUPS:
        if type_name in g.types:
            spec = g.bit_rows.get(type_name)
            if spec and spec.get("own") and spec["own"][0][0] == field_name:
                return spec["own"]
    return None


def paired_partner(type_name, field_name):
    """(前一字段, 后一字段)：field_name 是前一字段时返回该对，否则 None。"""
    for g in GROUPS:
        if type_name in g.types and g.paired and g.paired[0] == field_name:
            return g.paired
    return None


def is_paired_follower(type_name, field_name):
    return any(type_name in g.types and g.paired and g.paired[1] == field_name
               for g in GROUPS)
