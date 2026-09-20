"""
blender_efx/part_mask_ops.py  —  PLEMISSIVE body_p / wp_p 位掩码勾选编辑器

PLEMISSIVE 的关联部位字段 body_p / wp_p 各是一个完整字节（8 位），无额外的"cycle"高位——
2026-09 用 official 全语料（185 个 PLEMISSIVE 块）核对后推翻了旧版"低位掩码+高位 cycle
计数器"读法：那个所谓的"cycle"在 wp_p 里最常见的取值（如 0x20→cycle 8、0x38→cycle 14）
是跨大量不同文件反复出现的固定常数，不是会递增的计数器；而 evc0020_031.efx 里
body_p=wp_p=0x3F（配 color=白、bright=1.0）明显是个"全选"测试样本，直接证明两个字段
就是纯粹的按位选择，不需要额外的乘法换算。

现状（2026-09 语料统计，见 docs/OFFICIAL_DEFAULTS_AND_ENUMS.md §3.1）：
  body_p：官方讲座列出 8 个防具项（HELM/BODY/ARM/WAIST/LEG/ACCE/HAIR/FACE），旧代码
    bit0~4 已用 head/body/arms/waist/legs 对应前 5 项，用户 2026-09-19 指出这个顺序
    跟官方列表前 5 项顺序一致不像巧合，故 bit5~7 按同一顺序接着排 ACCE/HAIR/FACE。
    仍是假设（bit5 只在"全选"样本里出现过一次，bit6/7 全语料零命中，未实机验证），
    但比单纯占位名有更强的顺序依据。
  wp_p：官方讲座列了 3 个武器项（WP_MAIN/WP_SUB0/WP_SUB1，均是数字编号；此前一度
    误记成"WP_SUBO"末位是字母O，用户 2026-09-19 核对原图确认末位就是数字 0，已订正）。
    语料里 bit0~5 全部有实质使用（bit5 单独出现率高达 62.7%），明显超出 3 位——旧名
    "左手/右手"本身无独立证据支撑，按用户 2026-09-19 给出的假设改名：bit1(原
    right_hand)→wpMain（较有把握），bit0(原 left_hand)→wpSub0（临时假设），
    bit2→wpSub1（临时假设）。bit3~7 仍未定位，占位名 wp_unkn3~7，等游戏内逐位实机
    测试（逐个切换装备部位/武器槽、导出对比字节变化——MHW 是 MT Framework，没有
    REFramework 之类的脚本化探测手段）后再回填/纠正。

⚠ 8 个勾选框只是把同一个字节按位拆开显示/编辑，不涉及任何换算——底层仍是单字节
  item.byte1_value，byte-perfect 不受影响。
"""

import bpy
from bpy.props import BoolProperty, StringProperty


# ── 掩码常量 ──────────────────────────────────────────────────────────────────
# (attr_key, bit, 中文简称, 英文簡稱)；body_p bit0~4 沿用旧名，与官方 8 防具项前 5 位
# （HELM/BODY/ARM/WAIST/LEG）顺序一致，故 bit5~7 按同一顺序接排 ACCE/HAIR/FACE
# （用户 2026-09-19 假设，未实机验证，标"（假设）"）。
_BODY_PARTS = [
    ("head",  0x01, "头 Head",   "Head"),
    ("body",  0x02, "身 Body",   "Body"),
    ("arms",  0x04, "臂 Arms",   "Arms"),
    ("waist", 0x08, "腰 Waist",  "Waist"),
    ("legs",  0x10, "腿 Legs",   "Legs"),
    ("acce",  0x20, "饰 Acce（假设）",  "Acce (assumed)"),
    ("hair",  0x40, "发 Hair（假设）",  "Hair (assumed)"),
    ("face",  0x80, "脸 Face（假设）",  "Face (assumed)"),
]

# wp_p：bit0~2 按用户 2026-09-19 假设改名（bit1=wpMain 较有把握，bit0=wpSub0/
# bit2=wpSub1 是临时假设，均未实机验证），bit3~7 仍未定位，按 unkn{位号} 占位。
_WP_PARTS = [
    ("wpSub0",   0x01, "WP_SUB0（假设）",  "WP_SUB0 (assumed)"),
    ("wpMain",   0x02, "WP_MAIN（假设）",  "WP_MAIN (assumed)"),
    ("wpSub1",   0x04, "WP_SUB1（假设）",  "WP_SUB1 (assumed)"),
    ("wp_unkn3", 0x08, "未知 3", "Unknown 3"),
    ("wp_unkn4", 0x10, "未知 4", "Unknown 4"),
    ("wp_unkn5", 0x20, "未知 5", "Unknown 5"),
    ("wp_unkn6", 0x40, "未知 6", "Unknown 6"),
    ("wp_unkn7", 0x80, "未知 7", "Unknown 7"),
]


def _find_field_item(bp, ori_name):
    """在 attribute PropertyGroup 的 field_items 里按 ori_name 找字段项。"""
    for it in bp.field_items:
        if it.ori_name == ori_name:
            return it
    return None


def _is_plemissive_attribute(obj):
    """obj 是否为 PLEMISSIVE 属性对象。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        from ..efx_format.hashes import PLEMISSIVE
        return int(obj.efx_block.type_hash_str) == PLEMISSIVE
    except (ValueError, AttributeError, ImportError):
        return False


def part_mask_summary(value, field):
    """把掩码值转成可读摘要字符串（供面板行展示）。"""
    parts = _BODY_PARTS if field == "body_p" else _WP_PARTS
    names = [zh.split(" ")[0] for _key, bit, zh, _en in parts if value & bit]
    return "+".join(names) if names else "无"


# ── 勾选弹窗算子 ──────────────────────────────────────────────────────────────

class EFX_OT_set_part_mask(bpy.types.Operator):
    """以勾选框编辑 PLEMISSIVE 的关联部位 / 关联武器位掩码"""

    bl_idname      = "efx.set_part_mask"
    bl_label       = "Edit Part Mask"
    bl_description = "Edit the related-body / related-weapon bitmask via checkboxes"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    field: StringProperty(name="Field", default="body_p")  # "body_p" / "wp_p"

    head:  BoolProperty(name="头 Head",  default=False)
    body:  BoolProperty(name="身 Body",  default=False)
    arms:  BoolProperty(name="臂 Arms",  default=False)
    waist: BoolProperty(name="腰 Waist", default=False)
    legs:  BoolProperty(name="腿 Legs",  default=False)
    body_unkn5: BoolProperty(name="未知 5", default=False)
    body_unkn6: BoolProperty(name="未知 6", default=False)
    body_unkn7: BoolProperty(name="未知 7", default=False)

    wpSub0: BoolProperty(name="WP_SUB0（假设）", default=False)
    wpMain: BoolProperty(name="WP_MAIN（假设）", default=False)
    wp_unkn2: BoolProperty(name="未知 2", default=False)
    wp_unkn3: BoolProperty(name="未知 3", default=False)
    wp_unkn4: BoolProperty(name="未知 4", default=False)
    wp_unkn5: BoolProperty(name="未知 5", default=False)
    wp_unkn6: BoolProperty(name="未知 6", default=False)
    wp_unkn7: BoolProperty(name="未知 7", default=False)

    @classmethod
    def poll(cls, context):
        return _is_plemissive_attribute(context.active_object)

    def invoke(self, context, event):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        # body_p / wp_p 是 'B'(byte) 字段 → 值存于 byte1_value 槽（非 int_value）
        val = int(item.byte1_value) if item is not None else 0
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        for key, bit, _zh, _en in parts:
            setattr(self, key, bool(val & bit))
        return context.window_manager.invoke_props_dialog(self, width=240)

    def draw(self, context):
        layout = self.layout
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        layout.label(text="关联 body 部位 (body_p)" if self.field == "body_p"
                     else "关联武器 (wp_p)")
        for key, _bit, _zh, _en in parts:
            layout.prop(self, key)

    def execute(self, context):
        bp = context.active_object.efx_block
        item = _find_field_item(bp, self.field)
        if item is None:
            self.report({"ERROR"}, f"Field '{self.field}' not found")
            return {"CANCELLED"}
        parts = _BODY_PARTS if self.field == "body_p" else _WP_PARTS
        mask = 0
        for key, bit, _zh, _en in parts:
            if getattr(self, key):
                mask |= bit
        item.byte1_value = mask & 0xFF   # update=_mark_block_dirty 自动置脏
        self.report({"INFO"}, f"{self.field} = 0x{mask:02X} ({part_mask_summary(mask, self.field)})")
        return {"FINISHED"}


_CLASSES = (EFX_OT_set_part_mask,)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
