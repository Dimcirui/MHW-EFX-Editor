"""
blender_efx/panels.py  —  L1.1a + L1.2 预设 UI + L1.3 BT 注释接入 + L1.4 预设面板重构
                           + L1.5 块字段显示重设计（语义化绘制 + ctc 现代风 + 友好字段名）

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：Panel / layout.operator / layout.box / layout.label /
    layout.prop / layout.row / layout.column / BoolProperty / WindowManager /
    EnumProperty（动态 items 回调）
  - 不使用 5.x 新增 API

L1.4 预设 UI 重构：
  - EFX_PT_main 顶部：移除旧预设按钮，只保留 Import/Export。
  - _draw_block_fields_content 底部：移除旧 _draw_preset_ui 嵌入调用。
  - 新增独立可展开面板 EFX_PT_block_presets（VIEW_3D N 面板），
    与块字段面板平级，poll 要求 is_editable=True 的 EFX_BLOCK。
    （属性编辑器预设变体 _props/_object 已按设计理念移除，工具功能仅保留在 N 面板）
  - 新面板内容从上到下：
      1. Copy / Paste 按钮行（即时内存剪贴板）
      2. 保存当前字段为预设按钮
      3. 预设下拉 + 应用按钮行
      4. 打开预设文件夹按钮

#2 字段说明 tooltip（替代旧 efx_show_annotations toggle）：
  有注释的字段旁显示 ⓘ（INFO）图标按钮。
  悬停该图标即在 Blender 原生 tooltip 中显示 BT 注释（通过 EFX_OT_field_help 动态 description）。
  无注释字段不渲染图标，布局保持紧凑。
  已移除：WindowManager.efx_show_annotations / header toggle / label 行渲染。

#3 COLOR_RGBA alpha 可编辑：
  FloatVectorProperty size=4 subtype='COLOR' 的色块点开后含 Alpha 滑块，
  但内联色块本身不显示 alpha 通道。
  补充：在色块旁追加一个 index=3 数值条（text="A"，slider=True），使 alpha 直接可见可编辑。
  COLOR_RGBA 同时用于 spec='colour'（真 RGBA）和 spec=('XYZ',2)（XYZ type 2，第4字节为 alpha）。
  两者绘制逻辑统一，alpha 通道对两类字段均可见可编辑。

L1.5 块字段显示重设计：
  - 友好字段名：下划线→空格、camelCase 拆词、首字母大写（仅显示，逻辑仍用 ori_name）。
  - FLOAT6（XYZ type 0，6个float，顺序=[fixed_x,random_x,fixed_y,random_y,fixed_z,random_z]）：
    字段名一行 + 3 行（X Fixed/Random、Y Fixed/Random、Z Fixed/Random），
    用 index= 分量绘制，不开 property_split，保证布局不乱。
  - INT3（XYZ type 1，3个int=x,y,z）：字段名一行 + 1行 X/Y/Z 分量。
  - FLOAT3（XYZ type 3 或 float[3]，x,y,z）：字段名一行 + 1行 X/Y/Z 分量。
  - 标量/颜色/字符串等：保持现有绘制（友好名 + 值 + ⓘ + 色块+alpha）。
  - 整体风格（ctc 风）：字段列表包在 box() 里，scale_y=1.1 放大行高，
    手动 index 分量行不开 property_split（row.use_property_split=False）。
"""

import re
import bpy
from .presets import reload_presets, _type_name_from_hash
from .subselect import EFX_PT_subselect        # L2 #1a：Subselect 归属面板
from .play_emitter import EFX_PT_play          # L2 #1b：Play 数据面板
from .extern_ref import EFX_PT_extern_ref      # L2 #1c：ExternReference 指针面板
from .body_play_ref import (                   # L2 #1d：PtLife/PtCollision/eof_ints 指针面板
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
    EFX_PT_eof_list,
    EFX_OT_eof_toggle_body,
    EFX_OT_eof_remove_entry,
    is_body_in_eof,
)
from .backref import (                          # L2 反向引用视图（只读）
    EFX_PT_extern_backref,
    EFX_PT_body_backref,
)
# L2 #3a：重排面板（body + block 上移/下移按钮）
from . import reorder as _reorder


# ─────────────────────────────────────────────────────────────────────────────
# 友好字段名工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _friendly_name(ori_name: str) -> str:
    """
    把 schema 原始字段名转换为友好的显示名称（仅用于 UI，不影响任何逻辑）。

    规则：
      1. 下划线替换为空格。
      2. camelCase → 拆分（在小写→大写的边界插入空格）。
      3. 连续空格压缩，首字母大写，其余词小写保留（不强制小写，保留缩写如 UV）。

    例：
      translation_velocity   → "Translation Velocity"
      unkn0                  → "Unkn0"
      patternControl         → "Pattern Control"
      enableVelocityBitflag  → "Enable Velocity Bitflag"
      uv1_acceleration       → "Uv1 Acceleration"
      __opaque_hint__        → "__opaque_hint__"（原样返回，勿转换）
    """
    # 特殊内部名称（opaque hint 等）直接返回
    if ori_name.startswith("__") and ori_name.endswith("__"):
        return ori_name

    s = ori_name

    # camelCase 拆词：在 小写/数字→大写 的边界插入空格
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)

    # 下划线→空格
    s = s.replace("_", " ")

    # 压缩连续空格
    s = re.sub(r' +', ' ', s).strip()

    # 首字母大写（capitalize() 会把其余字母变小写，改用 title() 逻辑的变体：
    # 仅首词首字母大写，保留后续词的原始大小写）
    if s:
        s = s[0].upper() + s[1:]

    return s


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具：ⓘ 图标辅助
# ─────────────────────────────────────────────────────────────────────────────

def _draw_info_icon(row, type_name: str, ori_name: str) -> None:
    """
    若 (type_name, ori_name) 有 BT 注释，在 row 末尾添加 ⓘ 图标按钮（EFX_OT_field_help）。
    悬停即显示 BT 注释 tooltip。无注释时不添加任何控件。
    """
    if not type_name:
        return
    from .annotations import get_annotation
    ann = get_annotation(type_name, ori_name)
    if ann:
        op = row.operator(
            "efx.field_help",
            text="",
            icon="INFO",
            emboss=False,
        )
        op.type_name = type_name
        op.field_name = ori_name


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具：按 data_type 绘制字段控件
# ─────────────────────────────────────────────────────────────────────────────

# 可配对的标量 dtype → 其值控件属性名（value+jitter 同行显示用）
_SCALAR_PROP_ATTR = {
    "FLOAT":  "float_value",
    "INT":    "int_value",
    "UINT":   "uint_str",
    "BYTE1":  "byte1_value",
    "SHORT1": "short1_value",
}


def _is_jitter_name(name: str) -> bool:
    """字段名是否为 jitter（两种命名：camelCase 'XJitter' / snake 'x_jitter'）。"""
    return name.endswith("Jitter") or name.endswith("_jitter")


def _draw_value_jitter_pair(layout, vitem, jitem, type_name: str = ""):
    """
    把 value 字段与紧随其后的 jitter 字段合并成一行两列：友好名 | 值 | Jitter。
    与 XYZ Fixed/Random 的分组风格一致（rotation X/Y/Z 等各成一行）。
    """
    fname = _friendly_name(vitem.ori_name)
    vattr = _SCALAR_PROP_ATTR[vitem.data_type]
    jattr = _SCALAR_PROP_ATTR[jitem.data_type]

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=fname)
    sub = split.row(align=True)
    sub.prop(vitem, vattr, text="值")
    sub.prop(jitem, jattr, text="Jitter")
    _draw_info_icon(row, type_name, vitem.ori_name)


def _draw_field_item(layout, item, type_name: str = ""):
    """
    按 item.data_type 在 layout 上绘制对应控件（L1.5 重设计版）。

    FLOAT6（XYZ type 0）：
      字段名一行（友好名 + ⓘ）+ 3 行（X/Y/Z，每行 Fixed index 和 Random index）。
      float6_value 顺序 = [fixed_x(0), random_x(1), fixed_y(2), random_y(3), fixed_z(4), random_z(5)]

    INT3（XYZ type 1）：
      字段名一行（友好名 + ⓘ）+ 1 行（X index=0, Y index=1, Z index=2）。

    FLOAT3（XYZ type 3 / float[3]）：
      字段名一行（友好名 + ⓘ）+ 1 行（X index=0, Y index=1, Z index=2）。

    COLOR_RGBA：
      字段名一行（友好名）+ 色块行（色块 + A 滑块 + ⓘ）。

    标量/字符串/OPAQUE 等：
      单行：友好名 | 值控件 | ⓘ（若有）。

    所有行 scale_y=1.1（ctc 风格）。
    手动 index 分量行强制 use_property_split=False，防止 property_split 打乱布局。
    """
    dtype = item.data_type
    fname = _friendly_name(item.ori_name)  # 友好显示名（仅显示，逻辑用 ori_name）

    # ── FLOAT6（XYZ type 0）：固定+随机/轴，3×2 展开 ─────────────────────────
    # 顺序：[fixed_x(0), random_x(1), fixed_y(2), random_y(3), fixed_z(4), random_z(5)]
    if dtype == "FLOAT6":
        # 字段名标题行（含 ⓘ）
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
        _draw_info_icon(title_row, type_name, item.ori_name)

        # X 行：Fixed index=0  Random index=1
        x_row = layout.row(align=True)
        x_row.scale_y = 1.1
        x_row.use_property_split = False
        x_row.label(text="X", icon="BLANK1")
        x_row.prop(item, "float6_value", index=0, text="Fixed")
        x_row.prop(item, "float6_value", index=1, text="Random")

        # Y 行：Fixed index=2  Random index=3
        y_row = layout.row(align=True)
        y_row.scale_y = 1.1
        y_row.use_property_split = False
        y_row.label(text="Y", icon="BLANK1")
        y_row.prop(item, "float6_value", index=2, text="Fixed")
        y_row.prop(item, "float6_value", index=3, text="Random")

        # Z 行：Fixed index=4  Random index=5
        z_row = layout.row(align=True)
        z_row.scale_y = 1.1
        z_row.use_property_split = False
        z_row.label(text="Z", icon="BLANK1")
        z_row.prop(item, "float6_value", index=4, text="Fixed")
        z_row.prop(item, "float6_value", index=5, text="Random")
        return

    # ── INT3（XYZ type 1）：x,y,z 三分量整数 ─────────────────────────────────
    if dtype == "INT3":
        # 字段名标题行（含 ⓘ）
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
        _draw_info_icon(title_row, type_name, item.ori_name)

        # X/Y/Z 分量行
        comp_row = layout.row(align=True)
        comp_row.scale_y = 1.1
        comp_row.use_property_split = False
        comp_row.label(text="", icon="BLANK1")
        comp_row.prop(item, "int3_value", index=0, text="X")
        comp_row.prop(item, "int3_value", index=1, text="Y")
        comp_row.prop(item, "int3_value", index=2, text="Z")
        return

    # ── FLOAT3（XYZ type 3 / float[3]）：x,y,z 三分量浮点 ───────────────────
    if dtype == "FLOAT3":
        # 字段名标题行（含 ⓘ）
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=fname, icon="ORIENTATION_GLOBAL")
        _draw_info_icon(title_row, type_name, item.ori_name)

        # X/Y/Z 分量行
        comp_row = layout.row(align=True)
        comp_row.scale_y = 1.1
        comp_row.use_property_split = False
        comp_row.label(text="", icon="BLANK1")
        comp_row.prop(item, "float3_value", index=0, text="X")
        comp_row.prop(item, "float3_value", index=1, text="Y")
        comp_row.prop(item, "float3_value", index=2, text="Z")
        return

    # ── COLOR_RGBA：色块 + A 滑块 ─────────────────────────────────────────────
    # 用于 spec='colour' 和 spec=('XYZ',2)，两者第4字节均为 alpha
    if dtype == "COLOR_RGBA":
        row = layout.row(align=True)
        row.scale_y = 1.1
        row.use_property_split = False
        split = row.split(factor=0.45)
        split.label(text=fname)
        val_row = split.row(align=True)
        # 色块（点击打开色轮，含 Alpha 面板）
        val_row.prop(item, "color_rgba_value", text="")
        # alpha 数值条，使 alpha 在内联行就可见可编辑
        val_row.prop(item, "color_rgba_value", index=3, text="A", slider=True)
        # ⓘ 图标（仅有注释时）
        _draw_info_icon(row, type_name, item.ori_name)
        return

    # ── 通用单行布局 ──────────────────────────────────────────────────────────
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=fname)

    if dtype == "FLOAT":
        split.prop(item, "float_value", text="")
    elif dtype == "INT":
        split.prop(item, "int_value", text="")
    elif dtype == "UINT":
        split.prop(item, "uint_str", text="")
    elif dtype == "BOOL":
        split.prop(item, "bool_value", text="")
    elif dtype == "BYTE1":
        split.prop(item, "byte1_value", text="")
    elif dtype == "SHORT1":
        split.prop(item, "short1_value", text="")
    elif dtype == "FLOAT2":
        split.prop(item, "float2_value", text="")
    elif dtype == "FLOAT4":
        split.prop(item, "float4_value", text="")
    elif dtype == "COLOUR":
        split.prop(item, "colour_value", text="")
    elif dtype == "INT2":
        split.prop(item, "int2_value", text="")
    elif dtype == "INT4":
        split.prop(item, "int4_value", text="")
    elif dtype == "INT_PAIR":
        split.prop(item, "int_pair_str", text="")
    elif dtype == "FLOAT2_STR":
        split.prop(item, "float2_str", text="")
    elif dtype == "FLOAT3_STR":
        split.prop(item, "float3_str", text="")
    elif dtype == "FLOAT5_STR":
        split.prop(item, "float5_str", text="")
    elif dtype == "FLOAT8_STR":
        split.prop(item, "float8_str", text="")
    elif dtype == "FLOAT16_STR":
        split.prop(item, "float16_str", text="")
    elif dtype == "INT10_STR":
        split.prop(item, "int10_str", text="")
    elif dtype == "INT16_STR":
        split.prop(item, "int16_str", text="")
    elif dtype == "ARRAY_STR":
        split.prop(item, "array_str", text="")
    elif dtype == "OPAQUE":
        # opaque hint 项（路径块的提示行，ori_name 以 '__' 开头）
        if item.ori_name.startswith("__"):
            split.label(text=item.opaque_str)
        else:
            split.label(text="[opaque]")
    elif dtype == "STRING":
        # 路径字段：可编辑文本框（用于 custom-codec 含路径类型）
        split.prop(item, "string_value", text="")
    else:
        split.label(text=f"[未知类型 {dtype}]")

    # ⓘ 图标（有注释，且非 OPAQUE 内部提示行）
    if dtype not in ("OPAQUE",) and not item.ori_name.startswith("__"):
        _draw_info_icon(row, type_name, item.ori_name)


# ─────────────────────────────────────────────────────────────────────────────
# L1.4 预设面板 — 动态 EnumProperty items 回调
# ─────────────────────────────────────────────────────────────────────────────

# Blender EnumProperty 动态回调的 GC 陷阱：Blender C 层持有的是 list 对象的
# 指针，而不是 Python 变量的引用。若每次返回新建的 list，旧对象会被 GC 导致
# 乱码。正确做法：始终对同一个模块级 list 对象做 .clear() + .extend()，
# 保证对象地址不变，Blender 的指针永远有效。
_block_preset_items_cache = [("__none__", "（无预设）", "")]


def _get_preset_items(self, context):
    """
    EnumProperty 动态 items 回调：扫当前块类型的预设目录，返回列表。
    self 是 WindowManager 实例，context 是当前 context。
    若没有可用预设，返回一个占位条目（EnumProperty 不接受空列表）。
    """
    obj = context.active_object if context else None
    if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
        _block_preset_items_cache.clear()
        _block_preset_items_cache.extend([("__none__", "（无预设）", "")])
        return _block_preset_items_cache
    try:
        bp = obj.efx_block
        if not bp.is_editable:
            _block_preset_items_cache.clear()
            _block_preset_items_cache.extend([("__none__", "（块不可编辑）", "")])
            return _block_preset_items_cache
        type_name = _type_name_from_hash(bp.type_hash_str)
        items = reload_presets(type_name)
        _block_preset_items_cache.clear()
        _block_preset_items_cache.extend(items if items else [("__none__", "（无预设）", "")])
        return _block_preset_items_cache
    except Exception:
        _block_preset_items_cache.clear()
        _block_preset_items_cache.extend([("__none__", "（加载预设出错）", "")])
        return _block_preset_items_cache


# ─────────────────────────────────────────────────────────────────────────────
# L2 #1c：EXTERNREFERENCE referenceIndex 字段的内联指针 UI
# ─────────────────────────────────────────────────────────────────────────────

def _draw_extern_ref_field(layout, obj) -> None:
    """
    在块字段列表中，把 EXTERNREFERENCE 的 referenceIndex 字段
    替换为 extern 指针选择器（内联在字段列表里，风格与其他字段一致）。

    三种显示情况：
      - pointerized=False（死块）：显示只读标签"[dead block]"
      - pointerized=True + none=True：显示"(-1 哨兵)"标签
      - pointerized=True + none=False：显示 EFX_EXTERN 对象选择器
    """
    try:
        props = obj.efx_extern_ref
    except AttributeError:
        # efx_extern_ref 未注册或对象无此属性：回退到普通 INT 显示（由调用方继续）
        return

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text="Reference Index")

    if not props.extern_ref_pointerized:
        # 死块/越界：只读提示
        val_row = split.row(align=True)
        val_row.enabled = False
        val_row.label(text="[dead block / out of range]", icon="ERROR")
        return

    if props.extern_ref_none:
        # 哨兵 -1：无目标
        val_row = split.row(align=True)
        val_row.label(text="(-1 哨兵，无目标)", icon="X")
        # 勾选 none 的按钮放在右侧
        row.prop(props, "extern_ref_none", text="", icon="X")
        return

    # 有效指针：EFX_EXTERN 对象选择器
    val_row = split.row(align=True)
    val_row.prop(props, "extern_ref_ptr", text="", icon="LINKED")
    # none 勾选（取消指向 → 变为哨兵）
    row.prop(props, "extern_ref_none", text="", icon="X")


# ─────────────────────────────────────────────────────────────────────────────
# 公共绘制函数：块字段内容（两个 Panel 共用，避免重复代码）
# ─────────────────────────────────────────────────────────────────────────────

def _draw_block_fields_content(layout, context):
    """
    绘制 EFX_BLOCK 的字段内容。
    被 EFX_PT_block_fields（N 面板）和 EFX_PT_block_fields_props（属性编辑器）共用。
    """
    obj = context.active_object

    if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
        layout.label(text="请选中 EFX_BLOCK 对象", icon="INFO")
        return

    # ── L2 #3a：块上移/下移按钮（始终在字段面板顶部显示）─────────────────────
    reorder_row = layout.row(align=True)
    op_up = reorder_row.operator("efx.move_block", text="上移", icon="TRIA_UP")
    op_up.direction = "UP"
    op_dn = reorder_row.operator("efx.move_block", text="下移", icon="TRIA_DOWN")
    op_dn.direction = "DOWN"
    layout.separator(factor=0.5)

    # ── 获取 efx_block PropertyGroup ────────────────────────────────────────
    try:
        bp = obj.efx_block
    except AttributeError:
        layout.label(text="efx_block 未注册（请重载扩展）", icon="ERROR")
        return

    # ── 解析当前块的类型名（用于查注释字典）────────────────────────────────────
    # bp.type_hash_str 存的是十进制 uint32 字符串（如 "1003792849"）。
    # 通过 HASH_TO_NAME 查出名称（如 "EMITTERSHAPE3D"），再大写作为字典键。
    # 注释现在始终传给 _draw_field_item，由其内部按需显示 ⓘ 图标。
    type_name = ""
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        type_hash_int = int(bp.type_hash_str)
        type_name = HASH_TO_NAME.get(type_hash_int, "").upper()
    except (ValueError, ImportError):
        type_name = ""

    # ── 检测是否为 EXTERNREFERENCE 块（用于 referenceIndex 字段替换）──────────
    _is_extern_ref = False
    try:
        from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
        _is_extern_ref = (int(bp.type_hash_str) == _EXTERNREFERENCE_HASH)
    except (ValueError, ImportError):
        pass

    # ── 可编辑块：展示字段列表 ────────────────────────────────────────────────
    if bp.is_editable:
        if len(bp.field_items) == 0:
            layout.label(text="（无字段）", icon="INFO")
        else:
            # ctc 风格：字段列表包在 box 里，用 column 统一管理行高
            box = layout.box()
            col = box.column(align=True)
            # 块类型名称区块标题行（含 dirty 标记）
            title_row = col.row(align=True)
            title_row.scale_y = 1.0
            block_title = type_name if type_name else f"Hash {bp.type_hash_str}"
            if bp.efx_dirty:
                title_row.label(text=f"{block_title}  ● 已修改", icon="MODIFIER")
            else:
                title_row.label(text=block_title, icon="MODIFIER")
            col.separator(factor=0.5)
            # 逐字段绘制（带 value+jitter 位置配对：jitter 字段与紧邻前一个
            # 同类型标量 value 合并一行，模拟 XYZ Fixed/Random 分组风格）
            items = list(bp.field_items)
            n = len(items)
            i = 0
            while i < n:
                item = items[i]
                # L2 #1c：EXTERNREFERENCE 的 referenceIndex 字段替换为 extern 指针 UI
                if _is_extern_ref and item.ori_name == "referenceIndex":
                    _draw_extern_ref_field(col, obj)
                    i += 1
                    continue
                # value + jitter 配对（位置性：下一个是同类型 jitter 标量）
                nxt = items[i + 1] if i + 1 < n else None
                if (nxt is not None
                        and item.data_type in _SCALAR_PROP_ATTR
                        and not _is_jitter_name(item.ori_name)
                        and not item.ori_name.startswith("__")
                        and nxt.data_type == item.data_type
                        and _is_jitter_name(nxt.ori_name)):
                    _draw_value_jitter_pair(col, item, nxt, type_name=type_name)
                    i += 2
                    continue
                _draw_field_item(col, item, type_name=type_name)
                i += 1

    else:
        # 不可编辑（_custom / 未知 / 含嵌套结构）
        box = layout.box()
        col = box.column(align=True)
        # 块类型名称区块标题行
        title_row = col.row(align=True)
        title_row.scale_y = 1.0
        block_title = type_name if type_name else f"Hash {bp.type_hash_str}"
        title_row.label(text=block_title, icon="MODIFIER")
        col.separator(factor=0.5)
        row = col.row(align=True)
        row.scale_y = 1.1
        row.label(text="（opaque，暂不可编辑）", icon="LOCKED")
        row2 = col.row(align=True)
        row2.scale_y = 1.0
        row2.label(text="此块类型含复杂结构，本轮仅保留原始字节。")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_main  —  VIEW_3D 侧边栏 "EFX" 标签页
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_main(bpy.types.Panel):
    """MHW EFX 编辑器主面板（N 面板 → EFX 标签页）"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "MHW EFX"

    def draw(self, context):
        layout = self.layout

        # ── 顶部一行两个按钮：Import / Export ────────────────────────────────
        row = layout.row(align=True)
        row.operator("efx.import_efx", text="导入 EFX", icon="IMPORT")
        row.operator("efx.export_efx", text="导出 EFX", icon="EXPORT")

        # ── Active EFX 选择器（新增 body 的目标根）────────────────────────────
        layout.prop(context.scene, "efx_active_efx", text="Active EFX")

        # ── TRANSFORM3D → 视口：按基础变换摆放各 body empty（纯可视，不影响导出）─
        layout.operator("efx.sync_transform_to_view", icon="ORIENTATION_GLOBAL")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_presets  —  统一「预设」面板（块预设 / Body 预设，顶部模式下拉）
#   布局两模式统一：复制/粘贴(属性|Body) → 保存当前为预设 → 选预设+应用/新增 → 打开文件夹
# ─────────────────────────────────────────────────────────────────────────────

def _draw_body_presets_content(layout, context):
    """Body 预设模式：复制/粘贴 Body + 保存 + 选预设新增 + 打开文件夹。
    目标 EFX 由 EFX_PT_main 顶部的 Active EFX 选择器决定。"""
    wm = context.window_manager

    # 1. 复制 Body / 粘贴 Body（整 body 内存剪贴板；算子 poll 自动灰）
    row = layout.row(align=True)
    row.operator("efx.copy_body", text="复制 Body", icon="COPYDOWN")
    row.operator("efx.paste_body", text="粘贴 Body", icon="PASTEDOWN")

    layout.separator()

    # 2. 保存当前 body 为预设（需选中 EFX_BODY，poll 自动灰）
    layout.operator("efx.save_body_preset", text="保存当前 body 为预设", icon="ADD")

    layout.separator()

    # 3. body 预设下拉 + 新增
    row = layout.row(align=True)
    row.prop(wm, "efx_body_preset_enum", text="")
    selected = wm.efx_body_preset_enum
    if selected:
        op = row.operator("efx.add_body_from_preset", text="新增", icon="PLAY")
        op.preset_path = selected
    else:
        sub = row.row()
        sub.enabled = False
        sub.operator("efx.add_body_from_preset", text="新增", icon="PLAY")

    layout.separator()

    # 4. 打开预设文件夹
    layout.operator("efx.open_body_preset_folder", text="打开预设文件夹", icon="FILE_FOLDER")


class EFX_PT_presets(bpy.types.Panel):
    """EFX 预设（顶部下拉切换：块预设 / Body 预设）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "预设"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # ── 顶部模式切换 ─────────────────────────────────────────────────────
        layout.prop(wm, "efx_preset_mode", expand=True)
        layout.separator()

        if wm.efx_preset_mode == "BODY":
            _draw_body_presets_content(layout, context)
        else:
            _draw_block_presets_content(layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_body_reorder  —  body 上移/下移按钮（选中 EFX_BODY 时显示）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_body_reorder(bpy.types.Panel):
    """EFX Body 属性（重排、重命名、EOF 激活状态）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Body 属性"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # ── EOF 激活状态 ──────────────────────────────────────────────────────
        in_eof = is_body_in_eof(obj)
        row = layout.row(align=True)
        icon = "RADIOBUT_ON" if in_eof else "RADIOBUT_OFF"
        label = "游戏激活：是" if in_eof else "游戏激活：否"
        row.label(text=label, icon=icon)
        toggle_text = "移出激活列表" if in_eof else "加入激活列表"
        row.operator("efx.eof_toggle_body", text=toggle_text, icon="PLAY" if not in_eof else "PAUSE")

        layout.separator(factor=0.5)

        # ── 排序 ──────────────────────────────────────────────────────────────
        row = layout.row(align=True)
        op_up = row.operator("efx.move_body", text="上移", icon="TRIA_UP")
        op_up.direction = "UP"
        op_dn = row.operator("efx.move_body", text="下移", icon="TRIA_DOWN")
        op_dn.direction = "DOWN"

        # ── 重命名 ────────────────────────────────────────────────────────────
        from .reorder import can_label_body
        if can_label_body(obj):
            layout.operator("efx.rename_body", text="重命名", icon="GREASEPENCIL")
        else:
            sub = layout.column()
            sub.enabled = False
            sub.operator("efx.rename_body", text="重命名（前有未命名条目）", icon="GREASEPENCIL")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_block_fields  —  属性栏（Properties > Object 或 N 面板子面板）
# 在 VIEW_3D N 面板 EFX 标签页下挂一个子面板，当选中 EFX_BLOCK 时展示字段。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_block_fields(bpy.types.Panel):
    """EFX 块字段属性栏（选中 EFX_BLOCK 对象时显示）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "块属性"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_BLOCK 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def draw(self, context):
        _draw_block_fields_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_block_fields_props  —  属性编辑器 Object Data Properties 标签
#
# bl_context = 'data'：Empty 物体的 Object Data Properties（空物体设置页）。
# 在 4.3.2 / 5.1 上，Empty 的 'data' 上下文是有效的（显示 Empty 尺寸/类型等），
# 因此 'data' 是首选。
#
# 保底版本 EFX_PT_block_fields_object（bl_context='object'）同时注册：
# 万一 'data' 在某版本的 Empty 上不渲染，用户仍可在 Object Properties 标签找到字段面板。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_block_fields_props(bpy.types.Panel):
    """EFX 块字段（属性编辑器 → Object Data Properties，选中 EFX_BLOCK 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX 块属性"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_BLOCK 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def draw(self, context):
        _draw_block_fields_content(self.layout, context)


class EFX_PT_block_fields_object(bpy.types.Panel):
    """EFX 块字段（属性编辑器 → Object Properties，保底版本）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "object"
    bl_label        = "EFX 块属性"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_BLOCK 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def draw(self, context):
        _draw_block_fields_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# L1.4 新建独立"字段预设"面板内容（三个 Panel 变体共用）
# ─────────────────────────────────────────────────────────────────────────────

def _draw_block_presets_content(layout, context):
    """
    绘制"字段预设"面板内容（EFX_PT_block_presets 系列共用）。

    布局从上到下：
      1. [Copy] [Paste]  ← 即时内存剪贴板
      2. [保存当前字段为预设]
      3. [预设下拉] [应用]
      4. [打开预设文件夹]
    """
    from .operators import _FIELD_CLIPBOARD

    obj = context.active_object
    if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
        layout.label(text="请选中 EFX_BLOCK 对象", icon="INFO")
        return

    try:
        bp = obj.efx_block
    except AttributeError:
        layout.label(text="efx_block 未注册（请重载扩展）", icon="ERROR")
        return

    # ── 1. Copy / Paste 按钮行 ────────────────────────────────────────────────
    row = layout.row(align=True)
    row.operator("efx.copy_block_fields", text="复制字段", icon="COPYDOWN")
    row.operator("efx.paste_block_fields", text="粘贴字段", icon="PASTEDOWN")

    layout.separator()

    # ── 2. 保存当前字段为预设 ─────────────────────────────────────────────────
    layout.operator("efx.save_block_preset", text="保存当前字段为预设", icon="ADD")

    layout.separator()

    # ── 3. 预设下拉 + 应用按钮 ────────────────────────────────────────────────
    wm = context.window_manager
    row = layout.row(align=True)
    row.prop(wm, "efx_preset_enum", text="")
    selected = wm.efx_preset_enum
    if selected and selected != "__none__":
        op = row.operator("efx.apply_block_preset", text="应用", icon="PLAY")
        op.preset_path = selected
    else:
        sub = row.row()
        sub.enabled = False
        sub.operator("efx.apply_block_preset", text="应用", icon="PLAY")

    layout.separator()

    # ── 4. 打开预设文件夹 ─────────────────────────────────────────────────────
    layout.operator("efx.open_preset_folder", text="打开预设文件夹", icon="FILE_FOLDER")


# （旧 EFX_PT_block_presets 面板已并入统一的 EFX_PT_presets；
#   _draw_block_presets_content 仍由其"块预设"模式复用。）


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_delete  —  删除条目 + 导出前校验（L2 #3b / #4）
#   按 active_object 的 ~TYPE 显示对应删除按钮；始终提供"导出前校验"按钮。
# ─────────────────────────────────────────────────────────────────────────────

# ~TYPE → (算子 idname, 按钮文案)
_DELETE_BY_TYPE = {
    "EFX_BODY":      ("efx.delete_body",      "删除 Body"),
    "EFX_BLOCK":     ("efx.delete_block",     "删除块"),
    "EFX_PLAY":      ("efx.delete_play",      "删除 Play"),
    "EFX_EXTERN":    ("efx.delete_extern",    "删除 Extern"),
    "EFX_SUBSELECT": ("efx.delete_subselect", "删除 Subselect"),
}


class EFX_PT_delete(bpy.types.Panel):
    """EFX 删除 / 校验（选中任意 EFX 对象时显示）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "删除 / 校验"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        t = obj.get("~TYPE")
        return t in _DELETE_BY_TYPE or t == "EFX_ROOT"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        t = obj.get("~TYPE") if obj is not None else None

        # ── 删除按钮（按类型）─────────────────────────────────────────────────
        entry = _DELETE_BY_TYPE.get(t)
        if entry is not None:
            idname, text = entry
            row = layout.row()
            row.operator(idname, text=text, icon="TRASH")

        # ── 导出前校验（始终显示）─────────────────────────────────────────────
        layout.separator()
        layout.operator("efx.validate", text="导出前校验", icon="CHECKMARK")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_PT_main,
    # 统一「预设」面板：块预设 / Body 预设（bl_parent_id='EFX_PT_main'，必须在其后注册）
    EFX_PT_presets,
    # L2 #3b / #4：删除 + 校验面板（bl_parent_id='EFX_PT_main'，必须在其后注册）
    EFX_PT_delete,
    # L2 #3a：body 重排面板（选中 EFX_BODY 时显示）
    EFX_PT_body_reorder,
    EFX_PT_block_fields,
    EFX_PT_block_fields_props,
    EFX_PT_block_fields_object,
    # L2 #1a：Subselect 归属面板（bl_parent_id='EFX_PT_main'，必须在 EFX_PT_main 之后注册）
    EFX_PT_subselect,
    # L2 #1b：Play 数据面板（bl_parent_id='EFX_PT_main'，必须在 EFX_PT_main 之后注册）
    EFX_PT_play,
    # L2 #1c：ExternReference 指针面板（bl_parent_id='EFX_PT_main'，必须在 EFX_PT_main 之后注册）
    EFX_PT_extern_ref,
    # L2 #1d：PtLife/PtCollision/eof_ints 指针面板（bl_parent_id='EFX_PT_main'）
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
    EFX_PT_eof_list,
    # L2 #1d EOF 算子
    EFX_OT_eof_toggle_body,
    EFX_OT_eof_remove_entry,
    # L2 反向引用视图（只读，bl_parent_id='EFX_PT_main'，必须在 EFX_PT_main 之后注册）
    EFX_PT_extern_backref,
    EFX_PT_body_backref,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # L1.2：预设下拉——挂在 WindowManager 上（会话级，不污染场景数据）。
    # 使用动态 items 回调，每次绘制时根据当前选中块的类型重新扫目录。
    # SKIP_SAVE 避免把路径字符串写入 .blend 文件（路径跨机器可能失效）。
    bpy.types.WindowManager.efx_preset_enum = bpy.props.EnumProperty(
        name="预设",
        description="选择要应用的字段预设（按当前 EFX_BLOCK 类型过滤）",
        items=_get_preset_items,
        options={"SKIP_SAVE"},
    )


def unregister():
    # 先注销面板（面板可能在绘制时访问该属性）
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    # 再移除 WindowManager 属性
    if hasattr(bpy.types.WindowManager, "efx_preset_enum"):
        del bpy.types.WindowManager.efx_preset_enum
