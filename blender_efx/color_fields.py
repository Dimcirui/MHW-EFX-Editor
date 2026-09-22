"""颜色编辑器的字段与属性筛选。

COLOR_RGBA 字段、已知的打包颜色字段及颜色相关字段名都会被收录。名称按 ori_name 的
末段匹配，便于处理嵌套字段；规则表可随新增 schema 增量扩展。
"""

from ..efx_format.hashes import TUBELIGHT as _TUBELIGHT

# 按 schema 原始拼写精确匹配，不做大小写或下划线归一化。
_COLOR_ADJACENT_NAMES = frozenset({
    "brightness",
    "brightnessSlot1", "brightnessSlot2",
    "brightnessSlotMultiplier1", "brightnessSlotMultiplier2",
    "brightnessJitter", "bright",
    "lightIntensity", "lightIntensityJitter",
    "enableIntensity1", "enableIntensity2", "enableEmissiveIntensity",
    "emissiveMultiplier", "emissiveStrength",
    "emissionStrength", "emissionStrengthJitter",
    "emissiveColorRate", "emissiveColorRateJitter",
    "colorRate", "colorRateJitter",
    "colorScaler",
    "fireFactor", "redChFactor", "alphaFactor",
    "useColorRange", "useEmissiveColor", "useEmissiveColorRange",
    "disableAllColorRange", "colourTransitionPoint",
    "lerpAlphaToBlue",
    "epv_color_slot", "epvcolorslot", "epv_color_slot1", "epv_color_slot2",
    "EPVColorSlot1", "EPVColorSlot2", "epvColorSlot",
    "epvcolor_0", "epvcolor_1",
    "headColorEpvSlot", "tailColorEpvSlot",
    "correctColorNo",
    "colorRangeCorrectColorNo",
})

# 颜色时序参数块按前缀归类。
_COLOR_ADJACENT_PREFIXES = ("fireColorParam_", "smokeColorParam_",
                            "specularColorParam_", "sheetColorParam_", "waterLerpParam_")

# 打包 RGBA 的非 COLOR_RGBA 特例。
_PACKED_INT_COLOR_FIELDS = frozenset({
    (_TUBELIGHT, "headColor"),
    (_TUBELIGHT, "tailColor"),
})


# 可整体乘算的亮度/强度浮点字段；data_type 仍须为 FLOAT。
_BRIGHTNESS_NAMES = frozenset({
    "brightness",
    "fireFactor", "redChFactor",
    "brightnessSlotMultiplier1", "brightnessSlotMultiplier2",
    "brightnessJitter", "bright",
    "lightIntensity", "lightIntensityJitter",
    "emissiveMultiplier", "emissiveStrength",
    "emissionStrength", "emissionStrengthJitter",
    "colorRate", "colorRateJitter",
    "emissiveColorRate", "emissiveColorRateJitter",
    "colorScaler",
})


def is_brightness_field(type_hash, ori_name: str, data_type: str) -> bool:
    """字段是否为可整体乘算的亮度/强度浮点（供 Color Tool 的亮度乘数使用）。"""
    if data_type != "FLOAT":
        return False
    suffix = ori_name.rsplit(".", 1)[-1] if ori_name else ori_name
    return suffix in _BRIGHTNESS_NAMES


def is_color_field(type_hash, ori_name: str, data_type: str) -> bool:
    """字段是否该在 EFX Color Editor 里露出。"""
    if data_type == "COLOR_RGBA":
        return True
    if (type_hash, ori_name) in _PACKED_INT_COLOR_FIELDS:
        return True
    suffix = ori_name.rsplit(".", 1)[-1] if ori_name else ori_name
    if suffix in _COLOR_ADJACENT_NAMES:
        return True
    return suffix.startswith(_COLOR_ADJACENT_PREFIXES)


def attribute_has_color(type_hash, field_items) -> bool:
    """attribute 是否含至少一个颜色字段。
    field_items：任意可迭代，逐项需有 .ori_name / .data_type（EFXFieldItem 或等价对象）。"""
    for item in field_items:
        if is_color_field(type_hash, item.ori_name, item.data_type):
            return True
    return False
