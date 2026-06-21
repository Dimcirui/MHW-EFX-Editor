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
from .subselect import EFX_PT_subselect        # L2 #1a：Subselect 归属面板
from .play_emitter import EFX_PT_play          # L2 #1b：Play 数据面板
from .extern_ref import EFX_PT_extern_ref      # L2 #1c：ExternReference 指针面板
from .body_play_ref import (                   # L2 #1d：PtLife/PtCollision/eof_ints 指针面板
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
    EFX_PT_eof_list,
    EFX_OT_eof_toggle_body,
    EFX_OT_eof_remove_entry,
    EFX_OT_eof_add_body,
    is_body_in_eof,
)
from .backref import (                          # L2 反向引用视图（只读）
    EFX_PT_extern_backref,
    EFX_PT_body_backref,
    EFX_PT_root_states,
    is_body_action_triggered,
    classify_body_activation,
)
from .add_ops import get_active_efx_root
# L2 #3a：重排面板（body + block 上移/下移按钮）
from . import reorder as _reorder
# 中英双语化：T() 查表 + 语言切换行
from . import i18n
from .i18n import T
# Extern 字段展开面板
from . import extern_props as _extern_props


# ─────────────────────────────────────────────────────────────────────────────
# 友好字段名工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _friendly_name(ori_name: str, type_name: str = "") -> str:
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

    # 中文模式：优先查中文标签表，命中即返回；未命中回退英文友好名（下方派生）。
    from .i18n import get_lang
    if get_lang() == "ZH":
        from .field_labels import label_zh
        zh = label_zh(ori_name, type_name or None)
        if zh:
            return zh

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


# SPAWN 块中不符合 Jitter 后缀约定、但语义上是抖动字段的名称
_SPAWN_JITTER_NAMES = frozenset({
    "randomizedSpawnsPerFrame",
    "randomizedDelay",
    "randomizedLifespan",
    "occur2",
})


def _is_jitter_name(name: str) -> bool:
    """字段名是否为 jitter（camelCase 'XJitter' / snake 'x_jitter' / SPAWN 特例）。"""
    return name.endswith("Jitter") or name.endswith("_jitter") or name in _SPAWN_JITTER_NAMES


def _draw_value_jitter_pair(layout, vitem, jitem, type_name: str = ""):
    """
    把 value 字段与紧随其后的 jitter 字段合并成一行两列：友好名 | 值 | Jitter。
    与 XYZ Fixed/Random 的分组风格一致（rotation X/Y/Z 等各成一行）。
    """
    fname = _friendly_name(vitem.ori_name, type_name)
    vattr = _SCALAR_PROP_ATTR[vitem.data_type]
    jattr = _SCALAR_PROP_ATTR[jitem.data_type]

    row = layout.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=fname)
    sub = split.row(align=True)
    sub.prop(vitem, vattr, text=T("field.value"))
    sub.prop(jitem, jattr, text=T("field.jitter"))
    _draw_info_icon(row, type_name, vitem.ori_name)


def _xyz_prop_name(item, base_prop):
    """选择绘制哪个属性：Scene.efx_blender_coords 开 且 该字段有单位映射时用 *_display
    （Blender 约定显示/编辑），否则用原 *_value（游戏原值）。返回 (prop_name, is_blender)。"""
    try:
        if getattr(bpy.context.scene, "efx_blender_coords", False):
            from . import fields as _f
            if _f.xyz_unit_for_item(item) is not None:
                return base_prop.replace("_value", "_display"), True
    except Exception:
        pass
    return base_prop, False


def _draw_field_item(layout, item, type_name: str = "", label_override=None):
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
    # 保留填充字段（0xCD 占位）→ 关闭编辑：把 layout 重指向一个 enabled=False 的子列，
    # 后续所有控件都画进它（只读灰显）。导出时该字段未编辑 → 走原字节，byte-perfect 不变。
    from .field_labels import is_reserved_fill
    if is_reserved_fill(type_name, item.ori_name):
        layout = layout.column(align=True)
        layout.enabled = False
    # 友好显示名（仅显示，逻辑用 ori_name）；label_override 优先（如 MATERIAL 路径的槽名）
    fname = label_override if label_override else _friendly_name(item.ori_name, type_name)

    # ── FLOAT6（XYZ type 0）：固定+随机/轴，3×2 展开 ─────────────────────────
    # 顺序：[fixed_x(0), random_x(1), fixed_y(2), random_y(3), fixed_z(4), random_z(5)]
    if dtype == "FLOAT6":
        prop6, is_b = _xyz_prop_name(item, "float6_value")
        # 字段名标题行（含 ⓘ）；Blender 坐标模式下标注
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=(fname + (" [Blender]" if is_b else "")), icon="ORIENTATION_GLOBAL")
        _draw_info_icon(title_row, type_name, item.ori_name)

        # X 行：Fixed index=0  Random index=1
        x_row = layout.row(align=True)
        x_row.scale_y = 1.1
        x_row.use_property_split = False
        x_row.label(text="X", icon="BLANK1")
        x_row.prop(item, prop6, index=0, text="Fixed")
        x_row.prop(item, prop6, index=1, text="Random")

        # Y 行：Fixed index=2  Random index=3
        y_row = layout.row(align=True)
        y_row.scale_y = 1.1
        y_row.use_property_split = False
        y_row.label(text="Y", icon="BLANK1")
        y_row.prop(item, prop6, index=2, text="Fixed")
        y_row.prop(item, prop6, index=3, text="Random")

        # Z 行：Fixed index=4  Random index=5
        z_row = layout.row(align=True)
        z_row.scale_y = 1.1
        z_row.use_property_split = False
        z_row.label(text="Z", icon="BLANK1")
        z_row.prop(item, prop6, index=4, text="Fixed")
        z_row.prop(item, prop6, index=5, text="Random")
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
        prop3, is_b = _xyz_prop_name(item, "float3_value")
        # 字段名标题行（含 ⓘ）
        title_row = layout.row(align=True)
        title_row.scale_y = 1.1
        title_row.use_property_split = False
        title_row.label(text=(fname + (" [Blender]" if is_b else "")), icon="ORIENTATION_GLOBAL")
        _draw_info_icon(title_row, type_name, item.ori_name)

        # X/Y/Z 分量行
        comp_row = layout.row(align=True)
        comp_row.scale_y = 1.1
        comp_row.use_property_split = False
        comp_row.label(text="", icon="BLANK1")
        comp_row.prop(item, prop3, index=0, text="X")
        comp_row.prop(item, prop3, index=1, text="Y")
        comp_row.prop(item, prop3, index=2, text="Z")
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
        # 死块/越界：只读提示 + 强制解锁按钮
        val_row = split.row(align=True)
        sub = val_row.row(align=True)
        sub.enabled = False
        sub.label(text="[dead block]", icon="ERROR")
        val_row.operator("efx.force_pointerize_extern_ref", text="", icon="UNLOCKED")
        return

    if props.extern_ref_none:
        # 哨兵 -1：无目标
        val_row = split.row(align=True)
        val_row.label(text=T("block.sentinel_no_target"), icon="X")
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
        layout.label(text=T("block.select_hint"), icon="INFO")
        return

    # ── 获取 efx_block PropertyGroup ────────────────────────────────────────
    try:
        bp = obj.efx_block
    except AttributeError:
        layout.label(text=T("block.not_registered"), icon="ERROR")
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

    # ── PTLIFE / PTCOLLISION：指针化时隐藏原始 relationIndex / ieIndex 字段 ────
    # 这两个字节由专用指针面板（Relation Index / IE Play Reference）控制，导出时
    # overlay 在字段编码之后覆写，故原始字段编辑会被静默丢弃 → 二者竞争、不同步。
    # 指针化时跳过原始字段（仅留指针面板这一处编辑源）；未指针化（越界死块）则照常
    # 显示原始字段供查看/编辑（此时 overlay 不生效，字段即真值）。
    _ptlife_ptr_hidden = False
    _ptcoll_ptr_hidden = False
    try:
        from ..efx_format.hashes import PTLIFE as _PTLIFE_HASH, PTCOLLISION as _PTCOLLISION_HASH
        _th = int(bp.type_hash_str)
        if _th == _PTLIFE_HASH:
            pl = getattr(obj, "efx_ptlife_ref", None)
            _ptlife_ptr_hidden = bool(pl and pl.relation_pointerized)
        elif _th == _PTCOLLISION_HASH:
            pc = getattr(obj, "efx_ptcollision_ref", None)
            _ptcoll_ptr_hidden = bool(pc and pc.ie_pointerized)
    except (ValueError, ImportError):
        pass

    # ── MATERIAL：解析槽位（mrl3 同源），把每条 path_N 标注为其贴图槽名 ─────────
    # _material_slots[i] = 第 i 条路径的槽名（tAlbedoMap/... 或 None）；_material_type = 主材质类型。
    _material_slots = None
    _material_type = None
    try:
        from ..efx_format.hashes import MATERIAL as _MATERIAL_HASH
        if int(bp.type_hash_str) == _MATERIAL_HASH:
            import base64 as _b64
            from ..efx_format import material_meta as _mm
            _summary = _mm.parse_material(_b64.b64decode(str(bp.raw_b64)))
            if _summary is not None:
                _material_slots = []
                for _blk in _summary["blocks"]:
                    if _material_type is None:
                        _material_type = _blk["type_name"]
                    for _s in _blk["sets"]:
                        if _s["path"] is not None:
                            _material_slots.append(_s["slot"])
    except Exception:
        _material_slots = None

    # ── PTBEHAVIOR 检测（用于灰字提示 + param 标签）────────────────────────────
    _is_ptbehavior = False
    try:
        from ..efx_format.hashes import PTBEHAVIOR as _PTBEHAVIOR_HASH_P
        _is_ptbehavior = (int(bp.type_hash_str) == _PTBEHAVIOR_HASH_P)
    except (ValueError, ImportError):
        pass

    _is_plemissive = False
    try:
        from ..efx_format.hashes import PLEMISSIVE as _PLEMISSIVE_HASH_P
        _is_plemissive = (int(bp.type_hash_str) == _PLEMISSIVE_HASH_P)
    except (ValueError, ImportError):
        pass

    # ── 可编辑块：展示字段列表 ────────────────────────────────────────────────
    if bp.is_editable:
        if len(bp.field_items) == 0:
            layout.label(text=T("block.no_fields"), icon="INFO")
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
            # MATERIAL：在标题下显示主材质类型（mrl3 同源，shader_id_hash 反查）
            if _material_type:
                mt_row = col.row(align=True)
                mt_row.scale_y = 1.0
                mt_row.label(text=T("material.type") + " " + _material_type, icon="MATERIAL")
            # 部分可编辑（含 __opaque_hint__）：块名下一行灰字提示
            _has_partial = any(
                it.ori_name == "__opaque_hint__" for it in bp.field_items
            )
            if _has_partial:
                _hint_row = col.row(align=True)
                _hint_row.enabled = False
                _hint_row.label(text=T("block.partial_edit"))
            # PTBEHAVIOR：param 数量因文件而异，仅支持现存 param 的修改
            if _is_ptbehavior:
                _ptb_hint_row = col.row(align=True)
                _ptb_hint_row.enabled = False
                _ptb_hint_row.label(text=T("block.ptbehavior_hint"))
            col.separator(factor=0.5)
            # 逐字段绘制（带 value+jitter 位置配对：jitter 字段与紧邻前一个
            # 同类型标量 value 合并一行，模拟 XYZ Fixed/Random 分组风格）
            items = list(bp.field_items)
            n = len(items)
            i = 0
            while i < n:
                item = items[i]
                # __opaque_hint__ 是内部 sentinel，不渲染为字段行
                if item.ori_name.startswith("__") and item.ori_name.endswith("__"):
                    i += 1
                    continue
                # L2 #1c：EXTERNREFERENCE 的 referenceIndex 字段替换为 extern 指针 UI
                if _is_extern_ref and item.ori_name == "referenceIndex":
                    _draw_extern_ref_field(col, obj)
                    i += 1
                    continue
                # PTLIFE/PTCOLLISION 指针化时隐藏原始索引字段（由专用指针面板控制），
                # 改为一行只读提示，避免与指针面板竞争、互不同步。
                if ((_ptlife_ptr_hidden and item.ori_name == "relationIndex")
                        or (_ptcoll_ptr_hidden and item.ori_name == "ieIndex")):
                    hint = col.row()
                    hint.enabled = False
                    hint.label(
                        text=f"{_friendly_name(item.ori_name, type_name)}: "
                             + T("field.ref_via_pointer"),
                        icon="LINKED",
                    )
                    i += 1
                    continue
                # PTBEHAVIOR：param 行用属性 key 标签（hint_name=已知名/0x%08X）+ 行尾移除按钮
                if _is_ptbehavior and item.hint_name and item.ori_name.startswith('p'):
                    _rest = item.ori_name[1:]  # "5" or "5_v2"
                    try:
                        _pord = int(_rest.split('_')[0])
                    except ValueError:
                        _pord = -1
                    _is_first_sub = ('_v' not in _rest) or _rest.endswith('_v0')
                    # 0x15 子值加 [vN] 后缀以区分；其余直接用 key 标签
                    if '_v' in _rest:
                        _lbl = f"{item.hint_name} [{_rest.split('_v')[1]}]"
                    else:
                        _lbl = item.hint_name
                    _prow = col.row(align=True)
                    _fcol = _prow.column(align=True)
                    _draw_field_item(_fcol, item, type_name=type_name, label_override=_lbl)
                    if _is_first_sub and _pord >= 0:
                        _bcol = _prow.column(align=True)
                        _op = _bcol.operator("efx.ptb_remove_override", text="", icon="X")
                        _op.param_index = _pord
                    i += 1
                    continue
                # PLEMISSIVE：body_p / wp_p（光圈部位掩码）保留原数值字段（直接可看/改），
                # 行尾附勾选弹窗按钮作为计算辅助。下拉拉开即显示部位，无需额外摘要行。
                if _is_plemissive and item.ori_name in ("body_p", "wp_p"):
                    _aura_lbl = ("Aura Part (Player)" if item.ori_name == "body_p"
                                 else "Aura Part (Weapon)")
                    _pm_row = col.row(align=True)
                    _fcol = _pm_row.column(align=True)
                    _draw_field_item(_fcol, item, type_name=type_name, label_override=_aura_lbl)
                    _bcol = _pm_row.column(align=True)
                    _op = _bcol.operator("efx.set_part_mask", text="", icon="DOWNARROW_HLT")
                    _op.field = item.ori_name
                    i += 1
                    continue
                # MATERIAL：path_N 用其贴图槽名（tAlbedoMap…）当标签，取代独立只读面板
                if _material_slots is not None and item.ori_name.startswith("path_"):
                    try:
                        _pidx = int(item.ori_name.split("_", 1)[1])
                        _slot = _material_slots[_pidx] if _pidx < len(_material_slots) else None
                    except (ValueError, IndexError):
                        _slot = None
                    _draw_field_item(col, item, type_name=type_name, label_override=_slot)
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

            # PTBEHAVIOR：参数列表底部「添加覆盖」下拉（按 b_type 目录列可加属性）
            if _is_ptbehavior:
                col.separator(factor=0.5)
                _add_row = col.row(align=True)
                _add_row.operator_menu_enum(
                    "efx.ptb_add_override", "key_choice",
                    text=T("block.ptbehavior_add"), icon="ADD",
                )

    else:
        # 不可编辑（_custom / 未知 / 含嵌套结构）
        box = layout.box()
        col = box.column(align=True)
        # 块类型名称区块标题行
        title_row = col.row(align=True)
        title_row.scale_y = 1.0
        block_title = type_name if type_name else f"Hash {bp.type_hash_str}"
        title_row.label(text=block_title, icon="MODIFIER")
        _hint_row = col.row(align=True)
        _hint_row.enabled = False
        _hint_row.label(text=T("block.partial_edit"))


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

        # ── 语言切换行（English / 中文）──────────────────────────────────────
        i18n.draw_language_toggle(layout)
        layout.separator(factor=0.5)

        # ── 顶部：Import / Export / New EFX ──────────────────────────────────
        row = layout.row(align=True)
        row.operator("efx.import_efx", text=T("main.import"), icon="IMPORT")
        row.operator("efx.export_efx", text=T("main.export"), icon="EXPORT")
        layout.operator("efx.new_efx", text=T("main.new_efx"), icon="ADD")

        # ── Active EFX 选择器（新增 body 的目标根）────────────────────────────
        layout.prop(context.scene, "efx_active_efx", text=T("main.active_efx"))

        # ── 骨架选择器 + 刷新特效体位置（按 TRANSFORM3D + bone_lim 绑定骨骼摆位）─
        layout.prop(context.scene, "efx_armature", text=T("main.armature"))
        layout.prop(context.scene, "efx_anchor_placement", text=T("main.anchor_placement"))
        layout.prop(context.scene, "efx_blender_coords", text=T("main.blender_coords"))
        row = layout.row(align=True)
        row.operator("efx.sync_transform_to_view",
                     text=T("main.sync_transform"), icon="ORIENTATION_GLOBAL")
        row.operator("efx.validate", text=T("validate.run_btn"), icon="CHECKMARK")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_presets  —  统一「预设」面板（Body 预设 / Block 预设，顶部模式切换）
# ─────────────────────────────────────────────────────────────────────────────

def _draw_body_presets_content(layout, context):
    """Body 预设模式：复制/粘贴 Body + 保存 + 选预设新增 + 打开文件夹。
    目标 EFX 由 EFX_PT_main 顶部的 Active EFX 选择器决定。"""
    wm = context.window_manager

    # 1. 复制 Body / 粘贴 Body（整 body 内存剪贴板；算子 poll 自动灰）
    row = layout.row(align=True)
    row.operator("efx.copy_body", text=T("body.copy"), icon="COPYDOWN")
    row.operator("efx.paste_body", text=T("body.paste"), icon="PASTEDOWN")

    # 2. 保存当前 body 为预设（需选中 EFX_BODY，poll 自动灰）
    layout.operator("efx.save_body_preset", text=T("body.save_preset"), icon="ADD")

    layout.separator()

    # 3. body 预设下拉 + 新增
    root = get_active_efx_root(context)
    if root is not None:
        efx_name = getattr(context.scene, "efx_active_efx", None)
        efx_label = efx_name.name if efx_name is not None else root.name
        layout.label(text=T("body.add_to_prefix") + efx_label, icon="PLUS")
    else:
        row2 = layout.row()
        row2.enabled = False
        row2.label(text=T("body.add_to_prefix") + T("body.add_to_no_efx"), icon="PLUS")
    row = layout.row(align=True)
    row.prop(wm, "efx_body_preset_enum", text="")
    selected = wm.efx_body_preset_enum
    if selected:
        op = row.operator("efx.add_body_from_preset", text=T("body.add"), icon="PLAY")
        op.preset_path = selected
    else:
        sub = row.row()
        sub.enabled = False
        sub.operator("efx.add_body_from_preset", text=T("body.add"), icon="PLAY")

    layout.separator()

    # 4. 打开预设文件夹
    layout.operator("efx.open_body_preset_folder", text=T("body.open_folder"), icon="FILE_FOLDER")


def _draw_block_presets_content(layout, context):
    """Block 预设模式：复制/保存整块 + 分类选择 + 选预设新增 + 粘贴块 + 打开文件夹。
    新增块需选中 EFX_BODY，保存/复制需选中 EFX_BLOCK，算子 poll 自动灰。"""
    wm = context.window_manager

    # 1. 复制整块 / 粘贴块（需选中 EFX_BLOCK / EFX_BODY，poll 自动灰）
    row = layout.row(align=True)
    row.operator("efx.copy_block", text=T("block.copy_whole"), icon="COPYDOWN")
    row.operator("efx.paste_block", text=T("block.paste"), icon="PASTEDOWN")

    # 2. 保存为块预设（需选中 EFX_BLOCK，poll 自动灰）
    layout.operator("efx.save_block_preset", text=T("block.save_preset"), icon="ADD")

    layout.separator()

    # 2. 分类 + 块预设下拉 + 新增（需选中 EFX_BODY，poll 自动灰）
    obj = context.active_object
    if obj is not None and obj.get("~TYPE") == "EFX_BODY":
        body_label = obj.get("efx_raw_label", "") or obj.name
        layout.label(text=T("block.add_to_prefix") + body_label, icon="PLUS")
    else:
        row_lbl = layout.row()
        row_lbl.enabled = False
        row_lbl.label(text=T("block.add_to_prefix") + T("block.add_to_no_body"), icon="PLUS")
    layout.prop(wm, "efx_block_category_enum", text=T("block.category"))
    row = layout.row(align=True)
    row.prop(wm, "efx_block_whole_preset_enum", text="")
    selected = wm.efx_block_whole_preset_enum
    if selected:
        op = row.operator("efx.add_block_from_block_preset", text=T("block.add"), icon="PLAY")
        op.preset_path = selected
    else:
        sub = row.row()
        sub.enabled = False
        sub.operator("efx.add_block_from_block_preset", text=T("block.add"), icon="PLAY")

    layout.separator()

    # 3. 打开文件夹
    layout.operator("efx.open_block_preset_folder", text=T("body.open_folder"), icon="FILE_FOLDER")


class EFX_PT_presets(bpy.types.Panel):
    """EFX 预设（Body 预设 / Block 预设，顶部模式切换）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Presets"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.row().prop(wm, "efx_preset_mode", expand=True)
        layout.separator(factor=0.3)
        if wm.efx_preset_mode == "BLOCK":
            _draw_block_presets_content(layout, context)
        else:
            _draw_body_presets_content(layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_body_status  —  Body Status 面板（选中 EFX_BODY 时显示）
#   子栏：Activation / Body References。
#   排序/重命名操作在 EFX_PT_delete（Edit 面板）。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_body_status(bpy.types.Panel):
    """EFX Body Status 父面板（容器）。子栏：Activation / Body References 同级附于其下。"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Body Status"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        idx = obj.get("efx_index", "?")
        layout.label(text=f"[{idx}] {obj.name}", icon="OBJECT_DATA")


class EFX_PT_body_activation(bpy.types.Panel):
    """Body 激活态子栏：综合 EOF（直接触发）+ Play 召唤 + subselect 门控的派生有效态。

    放在 Body 父面板下，与 Body References、TIML 同级。
    """

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Activation"
    bl_parent_id    = "EFX_PT_body_status"
    bl_options      = {"DEFAULT_CLOSED"}

    # 触发来源 → (i18n key, 图标)
    _SOURCE_UI = {
        "both":   ("body.src_both",   "RADIOBUT_ON"),
        "direct": ("body.src_direct", "RADIOBUT_ON"),
        "action": ("body.src_action", "PLAY"),
        "none":   ("body.src_none",   "RADIOBUT_OFF"),
    }

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        info = classify_body_activation(obj)

        # ── 有效行为（派生结论，模型推测）：来源(并) + 门控(与) 修饰 ───────────────
        box = layout.box()
        key, icon = self._SOURCE_UI.get(info["source"], ("body.src_none", "QUESTION"))
        box.label(text=T("body.effective_label"), icon="INFO")
        eff_text = T(key)
        if info["gated"]:
            eff_text += T("body.gate_qualifier")
            if info["source"] != "none":
                icon = "PROP_CON"
        box.label(text=eff_text, icon=icon)

        # ── 来源 1：直接触发（EOF），可切换 ─────────────────────────────────────
        in_eof = info["in_eof"]
        row = layout.row(align=True)
        row.label(
            text=T("body.game_active_yes") if in_eof else T("body.game_active_no"),
            icon="RADIOBUT_ON" if in_eof else "RADIOBUT_OFF",
        )
        toggle_text = T("body.remove_from_active") if in_eof else T("body.add_to_active")
        row.operator("efx.eof_toggle_body", text=toggle_text,
                     icon="PAUSE" if in_eof else "PLAY")

        # ── 来源 2：动作触发（被 Play 召唤，只读）────────────────────────────────
        in_action = info["in_action"]
        layout.label(
            text=T("body.action_trigger_yes") if in_action else T("body.action_trigger_no"),
            icon="RADIOBUT_ON" if in_action else "RADIOBUT_OFF",
        )

        # ── 门控层：subselect 状态掩码 ──────────────────────────────────────────
        n = info["n_tables"]
        if n > 0:
            layout.label(text=T("body.gating_yes").format(n=n), icon="PROP_CON")
        else:
            layout.label(text=T("body.gating_no"), icon="CHECKMARK")



# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_body_properties / EFX_PT_body_unkn  —  Body 原始属性面板
#   Body Properties：单行只读 Type + 子栏 Unkn Attributes + TIML 挂在其下。
#   Body Status（EFX_PT_body_status）管激活状态和引用，Body Properties 管原始数据。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_body_properties(bpy.types.Panel):
    """EFX Body 原始属性面板（Type / Unkn / TIML）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Body Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        body_kind = str(obj.get("body_kind", "unknown"))
        kind_label = {
            "standard": T("body.type_standard"),
            "extended": T("body.type_extended"),
        }.get(body_kind, body_kind)
        row = layout.row()
        row.enabled = False
        row.label(text=T("body.type_label") + kind_label, icon="INFO")

        # Root body 的 UnitBoundary 子条目（结构化时可编辑；含 RT/LayoutBank 的
        # root 走 opaque 只读，不显示）。语义未完全逆向：ints[2] + floats[8]。
        if body_kind == "root" and int(obj.get("root_structured", 0)) == 1:
            n = int(obj.get("root_ub_count", 0))
            if n == 0:
                layout.label(text="(empty root — no sub-entries)", icon="DOT")
            for j in range(n):
                box = layout.box()
                box.label(text="Unit Boundary %d" % j, icon="SHADING_BBOX")
                ik = "root_ub%d_ints" % j
                fk = "root_ub%d_floats" % j
                if ik in obj:
                    box.prop(obj, '["%s"]' % ik, text="Ints")
                if fk in obj:
                    box.prop(obj, '["%s"]' % fk, text="Floats")


class EFX_PT_body_unkn(bpy.types.Panel):
    """Body 未知属性子栏（unkn0 / unkn1 / unkn2）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Unkn Attributes"
    bl_parent_id    = "EFX_PT_body_properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        body_kind = str(obj.get("body_kind", "unknown"))
        col = layout.column(align=True)
        if "unkn0" in obj:
            col.prop(obj, '["unkn0"]', text="Unkn0")
        if body_kind == "extended":
            if "unkn1" in obj:
                col.prop(obj, '["unkn1"]', text="Unkn1")
            if "unkn2" in obj:
                col.prop(obj, '["unkn2"]', text="Unkn2")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_block_fields  —  属性栏（Properties > Object 或 N 面板子面板）
# 在 VIEW_3D N 面板 EFX 标签页下挂一个子面板，当选中 EFX_BLOCK 时展示字段。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_block_fields(bpy.types.Panel):
    """EFX 块字段属性栏（选中 EFX_BLOCK 对象时显示）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Block Properties"
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
    bl_label        = "EFX Block Properties"
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
    bl_label        = "EFX Block Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        """仅当选中对象是 EFX_BLOCK 时显示此面板。"""
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def draw(self, context):
        _draw_block_fields_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_root_props  —  属性编辑器 Object Properties（选中 EFX_ROOT 时显示）
#   只在 ROOT 对象上暴露 filesize_double（doubleBuffer）编辑，避免主面板臃肿。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_root_props(bpy.types.Panel):
    """EFX 根属性（属性编辑器 → Object Properties，选中 EFX_ROOT 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "object"
    bl_label        = "EFX Root"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ROOT"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        # filesize_double（doubleBuffer）：运行时内存缓冲提示，过小会致特效消失。
        # 导出对话框勾「自动重算」会按 2.75× 文件大小自动抬高（默认开）。
        if obj is not None and "hdr_double_buffer" in obj:
            box = layout.box()
            box.label(text=T("main.double_buffer"), icon="MODIFIER")
            box.prop(obj, '["hdr_double_buffer"]', text="")
            tip = box.row()
            tip.enabled = False
            tip.label(text=T("main.double_buffer_tip"))


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_add_section  —  从无到有新建 Play / Extern / Subselect 段条目
#   poll = 已选 Active EFX；三个按钮各建一个带合法空白模板的容器对象。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_add_section(bpy.types.Panel):
    """EFX 新建段条目（Play / Extern / Subselect）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Add Section Entry"
    bl_parent_id    = "EFX_PT_main"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        from .add_ops import get_active_efx_root
        return get_active_efx_root(context) is not None

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("efx.add_play",      text=T("addsec.play"),      icon="PLAY")
        col.operator("efx.add_extern",    text=T("addsec.extern"),    icon="FILE_BLEND")
        col.operator("efx.add_subselect", text=T("addsec.subselect"), icon="OUTLINER_OB_EMPTY")


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_delete  —  删除条目 + 导出前校验（L2 #3b / #4）
#   按 active_object 的 ~TYPE 显示对应删除按钮；始终提供"导出前校验"按钮。
# ─────────────────────────────────────────────────────────────────────────────

# ~TYPE → (算子 idname, 按钮文案 i18n key)
_DELETE_BY_TYPE = {
    "EFX_BODY":      ("efx.delete_body",      "del.body_btn"),
    "EFX_BLOCK":     ("efx.delete_block",     "del.block_btn"),
    "EFX_PLAY":      ("efx.delete_play",      "del.play_btn"),
    "EFX_EXTERN":    ("efx.delete_extern",    "del.extern_btn"),
    "EFX_SUBSELECT": ("efx.delete_subselect", "del.subselect_btn"),
}


class EFX_PT_delete(bpy.types.Panel):
    """EFX Edit panel — reorder / rename / copy fields / delete (shown when any EFX object is active)"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Edit"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        return obj.get("~TYPE") in _DELETE_BY_TYPE

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        t = obj.get("~TYPE") if obj is not None else None

        # ── EFX_BLOCK：排序 + 字段复制/粘贴 ──────────────────────────────────
        if t == "EFX_BLOCK":
            row = layout.row(align=True)
            op_up = row.operator("efx.move_block", text=T("block.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_block", text=T("block.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            row2 = layout.row(align=True)
            row2.operator("efx.copy_block_fields", text=T("block.copy_fields"), icon="COPYDOWN")
            row2.operator("efx.paste_block_fields", text=T("block.paste_fields"), icon="PASTEDOWN")

        # ── EFX_BODY：排序 + 重命名 ───────────────────────────────────────────
        elif t == "EFX_BODY":
            row = layout.row(align=True)
            op_up = row.operator("efx.move_body", text=T("block.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_body", text=T("block.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            from .reorder import can_label_body
            if can_label_body(obj):
                layout.operator("efx.rename_body", text=T("body.rename"), icon="GREASEPENCIL")
            else:
                sub = layout.column()
                sub.enabled = False
                sub.operator("efx.rename_body", text=T("body.rename_blocked"), icon="GREASEPENCIL")

        # ── EFX_PLAY / EFX_EXTERN：排序 + 重命名 ─────────────────────────────
        elif t in ("EFX_PLAY", "EFX_EXTERN"):
            row = layout.row(align=True)
            op_up = row.operator("efx.move_entry", text=T("block.move_up"), icon="TRIA_UP")
            op_up.direction = "UP"
            op_dn = row.operator("efx.move_entry", text=T("block.move_down"), icon="TRIA_DOWN")
            op_dn.direction = "DOWN"

            from .reorder import can_label_entry
            if can_label_entry(obj):
                layout.operator("efx.rename_entry", text=T("entry.rename"), icon="GREASEPENCIL")
            else:
                sub = layout.column()
                sub.enabled = False
                sub.operator("efx.rename_entry", text=T("entry.rename_blocked"), icon="GREASEPENCIL")

        # ── 删除按钮（按类型，始终显示）──────────────────────────────────────
        entry = _DELETE_BY_TYPE.get(t)
        if entry is not None:
            layout.separator(factor=0.5)
            row = layout.row()
            row.operator(entry[0], text=T(entry[1]), icon="TRASH")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# _draw_plain_field_list — 纯字段列表渲染（value+jitter 配对，无体块专属逻辑）
# 供 Extern 面板复用
# ─────────────────────────────────────────────────────────────────────────────

def _draw_plain_field_list(col, field_items, type_name: str = "") -> None:
    """渲染 field_items 列表（含 value+jitter 配对），无 EXTERNREFERENCE / PTLIFE 等体块专属逻辑。"""
    items = list(field_items)
    n = len(items)
    i = 0
    while i < n:
        item = items[i]
        if item.ori_name.startswith("__") and item.ori_name.endswith("__"):
            i += 1
            continue
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


# ─────────────────────────────────────────────────────────────────────────────
# EFX_PT_extern_props — Extern 段字段展开面板（选中 EFX_EXTERN 时显示）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_extern_props(bpy.types.Panel):
    """EFX Extern 属性展开面板"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "Extern Properties"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object

        try:
            ep = obj.efx_extern
        except AttributeError:
            layout.label(text="Extern props not registered", icon="ERROR")
            return

        if len(ep.items) == 0:
            layout.label(text="No extern data", icon="INFO")
            return

        # 多 item 时显示 item 切换器（实测语料通常只有 1 个）
        if len(ep.items) > 1:
            row = layout.row(align=True)
            row.label(text=f"Item {ep.active_item + 1} / {len(ep.items)}", icon="NODETREE")
            sub = row.row(align=True)
            decr = sub.operator("efx.extern_item_prev", text="", icon="TRIA_LEFT")  # noqa: F841
            incr = sub.operator("efx.extern_item_next", text="", icon="TRIA_RIGHT")  # noqa: F841

        ai = min(ep.active_item, len(ep.items) - 1)
        it = ep.items[ai]

        # 解析 type_name 用于字段注释查表
        type_name = ""
        try:
            from ..efx_format.hashes import HASH_TO_NAME
            type_name = HASH_TO_NAME.get(int(it.type_hash_str), "").upper()
        except Exception:
            pass
        display_name = type_name or f"0x{int(it.type_hash_str):08X}"

        if not it.is_editable:
            box = layout.box()
            col = box.column(align=True)
            col.label(text=display_name, icon="MODIFIER")
            col.label(text="Not supported yet", icon="INFO")
            return

        # 实例切换器（attr_count 个实例）
        n_inst = len(it.instances)
        if n_inst > 1:
            row = layout.row(align=True)
            row.label(text=f"Instance {it.active_instance + 1} / {n_inst}")
            nav = row.row(align=True)
            nav.operator("efx.extern_instance_prev", text="", icon="TRIA_LEFT")
            nav.operator("efx.extern_instance_next", text="", icon="TRIA_RIGHT")

        inst_idx = min(it.active_instance, n_inst - 1)
        inst = it.instances[inst_idx]

        box = layout.box()
        col = box.column(align=True)

        title = display_name
        if n_inst > 1:
            title += f"  [{inst_idx + 1}/{n_inst}]"
        col.label(text=title, icon="MODIFIER")
        col.separator(factor=0.5)

        if not inst.is_editable:
            col.label(text="Not supported yet", icon="INFO")
            return

        if len(inst.field_items) == 0:
            col.label(text="No fields", icon="INFO")
            return

        _draw_plain_field_list(col, inst.field_items, type_name=type_name)


_CLASSES = (
    # 主面板（Import/Export/Active EFX/Armature）
    EFX_PT_main,
    # 子面板（挂在 EFX_PT_main 下，无上下文依赖）
    EFX_PT_presets,
    EFX_PT_add_section,
    # 顶级上下文面板（选中特定对象时出现，与 EFX_PT_main 同级）
    EFX_PT_delete,
    EFX_PT_body_status,
    EFX_PT_body_activation,
    EFX_PT_body_properties,
    EFX_PT_body_unkn,
    EFX_PT_block_fields,
    EFX_PT_block_fields_props,
    EFX_PT_block_fields_object,
    EFX_PT_root_props,
    EFX_PT_subselect,
    EFX_PT_play,
    EFX_PT_extern_props,
    EFX_PT_extern_ref,
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
    EFX_PT_eof_list,
    # EOF 算子
    EFX_OT_eof_toggle_body,
    EFX_OT_eof_remove_entry,
    EFX_OT_eof_add_body,
    # 反向引用视图（只读）
    EFX_PT_extern_backref,
    EFX_PT_body_backref,
    EFX_PT_root_states,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
