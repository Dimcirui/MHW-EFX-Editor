"""
blender_efx/color_fields.py — 判定字段/属性是否"含颜色内容"

EFX Color Editor（导入 Only Colors 分支）的地基：判定哪些字段该在颜色编辑器里露出、
哪些 attribute 该被判定为"含颜色"（进而其所在 entry 该被暴露）。纯判定函数，不碰
bpy 数据结构本身（只读 ori_name/data_type 字符串 + type_hash 整数），可独立单测。

判据（任一命中即算颜色字段）
----------------------------
1. data_type == "COLOR_RGBA"：由 schema spec（'colour' 或 ('XYZ',2)）在 decode 阶段
   权威推出（见 fields.py::_spec_to_dtype），覆盖绝大多数颜色字段——
   color/color1/color2/colorRange/emissiveColor/emissiveColorRange/fireColor/
   smokeColor/EPVColorSlot 嵌套的 head.color1 等。零猜测，字段本身就是色块。
2. (type_hash, ori_name) 特例：TUBELIGHT.headColor/tailColor 是打包 int32 RGBA，
   dtype 是 INT 非 COLOR_RGBA（见 panels.py::_draw_tubelight_int_as_color 同一判据）。
3. 名字表 `_COLOR_ADJACENT_NAMES`：亮度/强度/颜色开关/EPV 颜色槽——字段本身不是色块，
   但和颜色/亮度显示直接绑定（用户原话："颜色、颜色范围、启用颜色范围、光强、
   Epv Color Slot"）。按 `ori_name` 最后一个 "." 分段匹配（EPVColorSlot 嵌套字段
   如 "head.epvColorSlot" 取 "epvColorSlot" 分段）。

⚠ 已知不完整：这张名字表是根据当前已 schema 化的类型（RGBFIRE/BILLBOARD3D/
PLEMISSIVE/PARENTEMISSIVE/MESH/TUBELIGHT/RGBWATER/LIGHTNING…）核对出来的起点，
不保证覆盖每个属性类型的每个亮度/颜色关联字段——新增/核对以此表为准迭代补充，
不影响已收录字段的行为（纯增量表，不改判定逻辑）。
"""

from ..efx_format.hashes import TUBELIGHT as _TUBELIGHT

# 名字精确匹配（按 schema 原始拼写，不做大小写/下划线归一化——ori_name 是权威原名）
# 交叉核对来源：全部 67 个 ATTR_SCHEMA_MAP + CUSTOM_FIELD_SCHEMA_MAP 类型逐字段扫描
# （2026-07-14），非纯拍脑袋列表。
_COLOR_ADJACENT_NAMES = frozenset({
    # 亮度 / 强度
    "brightness", "brightness1", "brightness2", "brightness3", "brightness4",
    "brightnessSlot1", "brightnessSlot2",
    "brightnessSlotMultiplier1", "brightnessSlotMultiplier2",
    "brightnessJitter", "bright",   # brightnessJitter 原名 randomBrightnessMult
    "lightIntensity", "lightIntensityJitter",
    "enableIntensity1", "enableIntensity2", "enableEmissiveIntensity",
    "emissiveMultiplier", "emissiveStrength",
    "emissionStrength", "emissionStrengthJitter",
    "emissive_brightness", "emissive_brightness_j",
    "emissive_saturation", "emissive_saturation_j",
    "colorScaler",
    # 颜色范围 / 颜色相关开关 / 模式
    "useColorRange", "useEmissiveColor", "useEmissiveColorRange",
    "disableAllColorRange", "colorModeFlag", "colourTransitionPoint",
    # 染色开关（TUBELIGHT：发射面是否受 headColor/tailColor 染色）
    "backFaceTintMode", "frontFaceTintMode",
    # EPV 颜色槽（含 EPVColorSlot 嵌套字段的 "head.epvColorSlot" 等，按末段匹配）
    "epv_color_slot", "epvcolorslot", "epv_color_slot1", "epv_color_slot2",
    "EPVColorSlot1", "EPVColorSlot2", "epvColorSlot",
    "epvcolor_0", "epvcolor_1",
    "headColorEpvSlot", "tailColorEpvSlot",
})

# 前缀匹配：火焰/烟雾色时序参数块（RGBFIRE，跟随 fireColor/smokeColor 通道生效/
# 淡入淡出，含 unkn7/unkn8 等未完全确认的同块兄弟字段——同块即算颜色相关，不逐个列举）
# RGBFIRE 的 fire/smoke 与 RGBWATER 的 specular/sheet 是同一套「颜色的生命期时序块」，
# 靠前缀把整段归类为颜色相关（Color Editor 模式的过滤依据）。RGBWATER 三段此前一直漏在
# 表外——它的段名 2026-09-03 才定下来（colorParam2_ 归属未定，但同属该结构，一并收）。
_COLOR_ADJACENT_PREFIXES = ("fireColorParam_", "smokeColorParam_",
                            "specularColorParam_", "sheetColorParam_", "colorParam2_")

# (type_hash, ori_name) 特例：打包 int32 RGBA，dtype 非 COLOR_RGBA
_PACKED_INT_COLOR_FIELDS = frozenset({
    (_TUBELIGHT, "headColor"),
    (_TUBELIGHT, "tailColor"),
})


# 可整体乘算的"亮度/强度"浮点字段（_COLOR_ADJACENT_NAMES 的严格子集）：
# 只收真正表示亮度/发光强度、乘一个系数语义成立的**浮点标量**。刻意排除——
#   · 开关/布尔：enable*/use*/disableAllColorRange
#   · 枚举/模式：colorModeFlag / backFaceTintMode / frontFaceTintMode
#   · 位置/占比：colourTransitionPoint（0-1 过渡点，乘会越界）
#   · 槽位索引：epv*Slot / brightnessSlot1/2（是槽编号不是强度值，含义不明保守排除）
#   · 饱和度：emissive_saturation*（是饱和不是亮度）
# 乘算时另有 data_type=="FLOAT" 的硬门控，双保险：即便名字命中、非浮点也跳过。
_BRIGHTNESS_NAMES = frozenset({
    "brightness", "brightness1", "brightness2", "brightness3", "brightness4",
    "brightnessSlotMultiplier1", "brightnessSlotMultiplier2",
    "brightnessJitter", "bright",   # brightnessJitter 原名 randomBrightnessMult
    "lightIntensity", "lightIntensityJitter",
    "emissiveMultiplier", "emissiveStrength",
    "emissionStrength", "emissionStrengthJitter",
    "emissive_brightness", "emissive_brightness_j",
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
