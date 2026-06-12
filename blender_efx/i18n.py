"""
blender_efx/i18n.py  —  中英双语化基础设施（自定义面板内切换，不依赖 Blender 原生翻译）

设计
----
- 语言状态是模块级全局 _LANG（'EN' / 'ZH'），默认 'EN'。
  用模块全局而非 PropertyGroup 字段，好处是 T() 在算子里也能用、无需 context。
- 持久化：写入 Blender 用户配置目录下的 efx_editor_lang.txt（跨版本稳定、可写）。
  register() 时读回；切换算子写入。
- T(key) 按当前语言查 STRINGS 表；缺键回退英文、再回退 key 本身。
- UI 绘制（draw 里的 text=）、动态 tooltip、下拉项标签都走 T()/查表，运行时即时切换。
- 注册期静态值（Panel.bl_label / Operator.bl_label / 属性 name=）切不了，统一用英文。

约束（CLAUDE.md）
----------------
- Python 3.10+ 语法；bpy 只用稳定子集；本文件属胶水层，可 import bpy。
- efx_format/ 仍保持零 bpy；分类的双语标签作为纯数据放 efx_format/categories.py，本层只取用。
"""

import os

import bpy
from bpy.props import StringProperty


# ─────────────────────────────────────────────────────────────────────────────
# 语言状态 + 持久化
# ─────────────────────────────────────────────────────────────────────────────

_LANG = "EN"          # 当前语言：'EN' / 'ZH'
_DEFAULT_LANG = "EN"


def _config_path() -> str:
    """语言偏好持久化文件路径（用户配置目录，跨 Blender 版本稳定）。"""
    try:
        cfg = bpy.utils.user_resource("CONFIG")
    except Exception:
        cfg = os.path.expanduser("~")
    return os.path.join(cfg, "efx_editor_lang.txt")


def load_lang() -> str:
    """从配置文件读回语言偏好（register 时调用）。"""
    global _LANG
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            val = f.read().strip().upper()
        _LANG = val if val in ("EN", "ZH") else _DEFAULT_LANG
    except Exception:
        _LANG = _DEFAULT_LANG
    return _LANG


def save_lang(lang: str) -> None:
    """把语言偏好写入配置文件。"""
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            f.write(lang)
    except Exception:
        pass


def get_lang() -> str:
    """返回当前语言 'EN' / 'ZH'。"""
    return _LANG


def set_lang(lang: str) -> None:
    """设置当前语言并持久化。"""
    global _LANG
    _LANG = lang if lang in ("EN", "ZH") else _DEFAULT_LANG
    save_lang(_LANG)


def T(key: str) -> str:
    """
    翻译查表：按当前语言返回字符串。
    缺键时回退英文，再回退 key 本身（便于发现漏翻）。
    """
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(_LANG) or entry.get("EN") or key


def type_label(type_name: str) -> str:
    """
    返回块类型的本地化友好标签，如 'TRANSFORM3D（位置/变换）' / 'TRANSFORM3D – Position/Transform'。
    用于块预设下拉项；type_name 始终保留（玩家需要类型名）。
    """
    lab = TYPE_LABELS.get(type_name, {})
    cn = lab.get("ZH")
    en = lab.get("EN")
    if _LANG == "ZH":
        return f"{type_name}（{cn}）" if cn else type_name
    return f"{type_name} – {en}" if en else type_name


# ─────────────────────────────────────────────────────────────────────────────
# 语言切换算子（两个小按钮 / 一个循环切换）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_set_language(bpy.types.Operator):
    """Toggle EFX editor UI language between English and 中文"""

    bl_idname = "efx.set_language"
    bl_label = "EFX Language"
    bl_description = "Switch the EFX editor interface language (English / 中文)"
    bl_options = {"REGISTER"}

    lang: StringProperty(default="")  # 'EN' / 'ZH' / '' = 循环切换

    def execute(self, context):
        target = self.lang
        if target not in ("EN", "ZH"):
            target = "ZH" if get_lang() == "EN" else "EN"
        set_lang(target)
        # 触发所有区域重绘
        try:
            for win in context.window_manager.windows:
                for area in win.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass
        return {"FINISHED"}


def draw_language_toggle(layout):
    """在面板里画语言切换行：[English][中文]，高亮当前语言。"""
    cur = get_lang()
    row = layout.row(align=True)
    op_en = row.operator("efx.set_language", text="English", depress=(cur == "EN"))
    op_en.lang = "EN"
    op_zh = row.operator("efx.set_language", text="中文", depress=(cur == "ZH"))
    op_zh.lang = "ZH"


# ─────────────────────────────────────────────────────────────────────────────
# 块类型友好标签（type_name → {EN, ZH}）
# 来源：docs/BLOCK_TYPES.md。用于块预设下拉、（可选）块标题。
# ─────────────────────────────────────────────────────────────────────────────

TYPE_LABELS = {
    "TRANSFORM3D":          {"EN": "Position/Transform", "ZH": "位置/变换"},
    "PARENTOPTIONS":        {"EN": "Parent Tracking",    "ZH": "父级跟随"},
    "SCALEANIM":            {"EN": "Scale Animation",    "ZH": "缩放动画"},
    "ROTATEANIM":           {"EN": "Rotate Animation",   "ZH": "旋转动画"},
    "SPAWN":                {"EN": "Spawn / Bone Attach","ZH": "生成/挂骨"},
    "EMITTERSHAPE3D":       {"EN": "Emitter Shape 3D",   "ZH": "发射器形状"},
    "EMITTERSHAPE2D":       {"EN": "Emitter Shape 2D",   "ZH": "2D发射器形状"},
    "LIFE":                 {"EN": "Lifespan",           "ZH": "生命周期"},
    "EMITTERBOUNDARY":      {"EN": "Emitter Boundary",   "ZH": "发射边界"},
    "VELOCITY3D":           {"EN": "Velocity / Motion",  "ZH": "速度/运动"},
    "TURBULENCE":           {"EN": "Turbulence",         "ZH": "湍流扰动"},
    "NOISE":                {"EN": "Noise",              "ZH": "噪声"},
    "HOMING":               {"EN": "Homing",             "ZH": "追踪目标"},
    "GUIDE":                {"EN": "Path Guide",         "ZH": "路径引导"},
    "RAYCAST":              {"EN": "Raycast",            "ZH": "射线检测"},
    "SCREENSPACECOLLISION": {"EN": "Screen-space Collision", "ZH": "屏幕空间碰撞"},
    "BILLBOARD3D":          {"EN": "Billboard (Camera)", "ZH": "摄像机面片"},
    "PLANE":                {"EN": "Fixed Plane",        "ZH": "固定平面片"},
    "RIBBON":               {"EN": "Ribbon",             "ZH": "丝带粒子"},
    "RIBBONBLADE":          {"EN": "Blade Trail",        "ZH": "刀刃拖尾"},
    "STRAINRIBBON":         {"EN": "Strain Ribbon (Chain)", "ZH": "拔刀链条"},
    "MESH":                 {"EN": "Model Mesh",         "ZH": "模型网格"},
    "LIGHTNING":            {"EN": "Lightning",          "ZH": "闪电"},
    "MATERIAL":             {"EN": "Embedded Material",  "ZH": "内嵌材质"},
    "UVSEQUENCE":           {"EN": "UV Sequence",        "ZH": "UV序列帧"},
    "UVCONTROL":            {"EN": "UV Scroll Control",  "ZH": "UV滚动控制"},
    "ALPHACORRECTION":      {"EN": "Alpha Correction",   "ZH": "透明度修正"},
    "SHADERSETTINGS":       {"EN": "Shader Settings",    "ZH": "着色设置"},
    "RGBFIRE":              {"EN": "RGB Fire",           "ZH": "火焰双色"},
    "RGBWATER":             {"EN": "RGB Water",          "ZH": "水面颜色"},
    "BLINK":                {"EN": "Blink",              "ZH": "闪烁"},
    "LUMINANCEBLEED":       {"EN": "Luminance Bleed",    "ZH": "亮度溢出"},
    "REFRACTION":           {"EN": "Refraction",         "ZH": "折射"},
    "FADEBYDEPTH":          {"EN": "Fade by Depth",      "ZH": "按深度渐隐"},
    "FADEBYANGLE":          {"EN": "Fade by Angle",      "ZH": "按角度渐隐"},
    "FADEBYEMITTERANGLE":   {"EN": "Fade by Emitter Angle", "ZH": "按发射角渐隐"},
    "PLEMISSIVE":           {"EN": "Player Aura/Glow",   "ZH": "玩家光圈"},
    "PARENTEMISSIVE":       {"EN": "Parent Emissive",    "ZH": "父级自发光"},
    "PLSNOW":               {"EN": "Player Snow",        "ZH": "玩家积雪"},
    "PTCOLLISION":          {"EN": "Particle Collision", "ZH": "粒子碰撞"},
    "PTLIFE":               {"EN": "Particle Life Event","ZH": "粒子生命事件"},
    "PTBEHAVIOR":           {"EN": "Particle Behavior",  "ZH": "粒子行为"},
    "EXTERNREFERENCE":      {"EN": "Extern Reference",   "ZH": "外部引用"},
    "MASTERONLY":           {"EN": "Master Player Only", "ZH": "仅主玩家可见"},
    "DUMMY":                {"EN": "Dummy (Placeholder)","ZH": "占位空块"},
    "RANDOMFIX":            {"EN": "Random Seed Fix",    "ZH": "固定随机种子"},
    "SHOVEL":               {"EN": "Shovel (Snow)",      "ZH": "铲雪扰动"},
}


# ─────────────────────────────────────────────────────────────────────────────
# UI 字符串表：key → {EN, ZH}
# 命名约定：<区域>.<用途>，如 main.import / block.add / cat.render
# ─────────────────────────────────────────────────────────────────────────────

STRINGS = {
    # ── 语言 ──────────────────────────────────────────────────────────────────
    "lang.label":            {"EN": "Language",            "ZH": "语言"},

    # ── 主面板 EFX_PT_main ───────────────────────────────────────────────────
    "main.import":           {"EN": "Import EFX",          "ZH": "导入 EFX"},
    "main.export":           {"EN": "Export EFX",          "ZH": "导出 EFX"},
    "main.active_efx":       {"EN": "Active EFX",          "ZH": "当前 EFX"},
    "main.armature":         {"EN": "Armature",            "ZH": "骨架"},
    "main.sync_transform":   {"EN": "Refresh Body Positions", "ZH": "刷新特效体位置"},

    # ── 块预设 / 分类（block_ops + 新增块面板）───────────────────────────────
    "block.add_section":     {"EN": "Add Block",           "ZH": "新增块"},
    "block.category":        {"EN": "Category",            "ZH": "分类"},
    "block.add":             {"EN": "Add",                 "ZH": "新增"},
    "block.paste":           {"EN": "Paste Block",         "ZH": "粘贴块"},
    "block.copy_fields":     {"EN": "Copy Fields",         "ZH": "复制字段"},
    "block.paste_fields":    {"EN": "Paste Fields",        "ZH": "粘贴字段"},
    "block.copy_whole":      {"EN": "Copy Block",          "ZH": "复制整块"},
    "block.save_preset":     {"EN": "Save as Block Preset","ZH": "保存为块预设"},
    "block.move_up":         {"EN": "Up",                  "ZH": "上移"},
    "block.move_down":       {"EN": "Down",                "ZH": "下移"},
    "block.no_preset":       {"EN": "(no block presets)",  "ZH": "（无块预设）"},
    "block.pick_category":   {"EN": "(pick a category)",   "ZH": "（先选分类）"},
    "block.cat_empty":       {"EN": "(category empty)",    "ZH": "（该分类无预设）"},

    # ── 占位 / 通用 ──────────────────────────────────────────────────────────
    "block.opaque":          {"EN": "(opaque, not editable yet)", "ZH": "（opaque，暂不可编辑）"},
    "block.opaque_hint":     {"EN": "This block type has complex structure; raw bytes preserved.",
                              "ZH": "此块类型含复杂结构，本轮仅保留原始字节。"},
    "block.no_fields":       {"EN": "(no fields)",         "ZH": "（无字段）"},
    "block.select_hint":     {"EN": "Select an EFX_BLOCK object", "ZH": "请选中 EFX_BLOCK 对象"},

    # ── 导入/导出算子（operators.py）弹窗 ─────────────────────────────────────
    "op.export_validation_failed_header": {"EN": "Pre-export validation found errors, cancelled:", "ZH": "导出前校验发现错误，已取消："},
    "op.export_validation_failed_title":  {"EN": "EFX Validation Failed", "ZH": "EFX 校验失败"},

    # ── 导出前校验（validate.py）弹窗 ─────────────────────────────────────────
    "validate.found_errors":   {"EN": "Found {n} error(s):",   "ZH": "发现 {n} 个错误："},
    "validate.found_warnings": {"EN": "Found {n} warning(s):", "ZH": "发现 {n} 个警告："},
    "validate.popup_title":    {"EN": "EFX Validation Results", "ZH": "EFX 校验结果"},

    # ── TIML 互导（timl_io.py）─────────────────────────────────────────────────
    "timl.segment_bytes": {"EN": "TIML segment: {n} bytes", "ZH": "TIML 段：{n} 字节"},
    "timl.export_btn":    {"EN": "Export as .timl File",    "ZH": "导出为 .timl 文件"},
    "timl.import_btn":    {"EN": "Reimport from .timl File","ZH": "从 .timl 文件回填"},
    "timl.hint":          {"EN": "Open the exported .timl in FreeKinetics, edit, then reimport",
                           "ZH": "用 FreeKinetics 打开导出的 .timl 编辑后再回填"},

    # ── Subselect 面板（subselect.py）─────────────────────────────────────────
    "sub.unset":            {"EN": "<Unset>",               "ZH": "<未设置>"},
    "sub.no_data":          {"EN": "(No efx_subselect data)", "ZH": "（无 efx_subselect 数据）"},
    "sub.table_meta":       {"EN": "Table Metadata",        "ZH": "表元数据"},
    "sub.members":          {"EN": "Members",               "ZH": "成员"},
    "sub.body_object":      {"EN": "Body Object",           "ZH": "Body 对象"},
    "sub.members_dangling": {"EN": "member pointer(s) dangling (skipped on export)",
                             "ZH": "个成员指针悬空（导出时跳过）"},

    # ── Play 面板（play_emitter.py）───────────────────────────────────────────
    "play.unset":                 {"EN": "<Unset>",         "ZH": "<未设置>"},
    "play.no_data":               {"EN": "(No efx_play data)", "ZH": "（无 efx_play 数据）"},
    "play.play_meta":             {"EN": "Play Metadata",   "ZH": "Play 元数据"},
    "play.pos_offset_xyz":        {"EN": "Position Offset XYZ", "ZH": "位置偏移 XYZ"},
    "play.targets":               {"EN": "Targets",         "ZH": "目标"},
    "play.body_object":           {"EN": "Body Object",     "ZH": "Body 对象"},
    "play.targets_dangling":      {"EN": "target pointer(s) dangling (skipped on export)",
                                   "ZH": "个 target 指针悬空（导出时跳过）"},
    "play.efx_path":              {"EN": "EFX Path",        "ZH": "EFX 路径"},
    "play.targets_dangling_total":{"EN": "target pointer(s) dangling in total",
                                   "ZH": "个 target 指针悬空"},

    # ── ExternReference 指针面板（extern_ref.py）──────────────────────────────
    "extern.no_data":            {"EN": "(No efx_extern_ref data)", "ZH": "（无 efx_extern_ref 数据）"},
    "extern.dead_title":         {"EN": "Reference Index (dead block)", "ZH": "Reference Index（死块）"},
    "extern.dead_line1":         {"EN": "This block's referenceIndex is out of extern range,",
                                  "ZH": "此块的 referenceIndex 超出 extern 范围，"},
    "extern.dead_line2":         {"EN": "original bytes preserved (not editable).",
                                  "ZH": "原始字节已保留（不可编辑）。"},
    "extern.no_target_sentinel": {"EN": "No Target (-1 sentinel)", "ZH": "无目标（-1 哨兵）"},
    "extern.extern_object":      {"EN": "Extern Object",    "ZH": "Extern 对象"},
    "extern.dangling":           {"EN": "Dangling pointer (uses original bytes on export)",
                                  "ZH": "⚠ 指针悬空（导出时使用原始字节）"},
    "extern.local_index":        {"EN": "Extern local index:", "ZH": "Extern 局部 index:"},

    # ── PtLife / PtCollision / EOF 指针面板（body_play_ref.py）────────────────
    "ptref.no_ptlife_data":      {"EN": "(No efx_ptlife_ref data)", "ZH": "（无 efx_ptlife_ref 数据）"},
    "ptref.relation_index_title":{"EN": "Relation Index (action reference)", "ZH": "Relation Index (action 引用)"},
    "ptref.relation_oob":        {"EN": "[Out of range/negative, original bytes preserved]",
                                  "ZH": "[越界/负值，原始字节保留]"},
    "ptref.body_object":         {"EN": "Body Object",      "ZH": "Body 对象"},
    "ptref.dangling":            {"EN": "Dangling pointer (uses original bytes on export)",
                                  "ZH": "⚠ 指针悬空（导出时使用原始字节）"},
    "ptref.body_local_index":    {"EN": "Body local index:", "ZH": "Body 局部 index:"},
    "ptref.no_ptcollision_data": {"EN": "(No efx_ptcollision_ref data)", "ZH": "（无 efx_ptcollision_ref 数据）"},
    "ptref.ie_index_title":      {"EN": "IE Index (play reference)", "ZH": "IE Index (play 引用)"},
    "ptref.ie_oob":              {"EN": "[Out of range/count_play=0, original bytes preserved]",
                                  "ZH": "[越界/count_play=0，原始字节保留]"},
    "ptref.no_target_sentinel":  {"EN": "No Target (-1 sentinel)", "ZH": "无目标（-1 哨兵）"},
    "ptref.play_object":         {"EN": "Play Object",      "ZH": "Play 对象"},
    "ptref.play_local_index":    {"EN": "Play local index:", "ZH": "Play 局部 index:"},
    "ptref.no_eof_data":         {"EN": "(No efx_eof_list data)", "ZH": "（无 efx_eof_list 数据）"},
    "ptref.game_activated_bodies":{"EN": "Bodies activated directly by the game", "ZH": "游戏直接激活的 Body"},
    "ptref.eof_empty":           {"EN": "(Empty - effect will not be triggered by the game)",
                                  "ZH": "（空——特效不会被游戏触发）"},
    "ptref.dangling_pointer":    {"EN": "[Dangling pointer]", "ZH": "[悬空指针]"},

    # ── 反向引用视图（backref.py）─────────────────────────────────────────────
    "backref.extern_object":          {"EN": "Extern object:", "ZH": "Extern 对象："},
    "backref.referenced_by_n_prefix": {"EN": "Referenced by", "ZH": "被"},
    "backref.referenced_by_n_suffix": {"EN": "EXTERNREFERENCE block(s):", "ZH": "个 EXTERNREFERENCE 块引用："},
    "backref.not_referenced_by_extern":{"EN": "Not referenced by any EXTERNREFERENCE block",
                                       "ZH": "未被任何 EXTERNREFERENCE 块引用"},
    "backref.block":                  {"EN": "Block:",       "ZH": "块："},
    "backref.body":                   {"EN": "Body:",        "ZH": "Body："},
    "backref.body_unknown":           {"EN": "Body: (unknown)", "ZH": "Body：（未知）"},
    "backref.jump_to_block":          {"EN": "Jump to this block", "ZH": "跳转到此块"},
    "backref.body_object":            {"EN": "Body object:", "ZH": "Body 对象："},
    "backref.not_referenced_by_ss_play":{"EN": "Not referenced by any Subselect / Play",
                                        "ZH": "未被任何 Subselect / Play 引用"},
    "backref.referenced_total_prefix":{"EN": "Referenced",  "ZH": "共被引用"},
    "backref.referenced_total_mid":   {"EN": "time(s) (Subselect", "ZH": "次（Subselect"},
    "backref.subselect_tables_prefix":{"EN": "Subselect tables", "ZH": "Subselect 表"},
    "backref.play_emitter_prefix":    {"EN": "Play Emitter", "ZH": "Play Emitter"},

    # ── Hex 视图（hexview.py）─────────────────────────────────────────────────
    "hex.no_raw_bytes":  {"EN": "(no raw bytes)",  "ZH": "（无原始字节）"},
    "hex.total_length":  {"EN": "Total length: ",  "ZH": "总长度："},
    "hex.bytes":         {"EN": "bytes",           "ZH": "字节"},
    "hex.copy_hex":      {"EN": "Copy Hex",        "ZH": "复制 hex"},
    "hex.paste_hex":     {"EN": "Paste Hex",       "ZH": "粘贴 hex"},
    "hex.trunc_prefix":  {"EN": "… showing first ", "ZH": "… 仅显示前 "},
    "hex.trunc_suffix":  {"EN": " bytes only; use Copy Full Hex above for the full content",
                          "ZH": " 字节，完整请用上方“复制完整 hex”"},

    # ── Body 预设区 + Body 属性区（panels.py）────────────────────────────────
    "body.copy":             {"EN": "Copy Body",            "ZH": "复制 Body"},
    "body.paste":            {"EN": "Paste Body",           "ZH": "粘贴 Body"},
    "body.save_preset":      {"EN": "Save Current Body as Preset", "ZH": "保存当前 body 为预设"},
    "body.add":              {"EN": "Add",                  "ZH": "新增"},
    "body.open_folder":      {"EN": "Open Preset Folder",   "ZH": "打开预设文件夹"},
    "body.game_active_yes":  {"EN": "Game-activated: Yes",  "ZH": "游戏激活：是"},
    "body.game_active_no":   {"EN": "Game-activated: No",   "ZH": "游戏激活：否"},
    "body.remove_from_active":{"EN": "Remove from Active List", "ZH": "移出激活列表"},
    "body.add_to_active":    {"EN": "Add to Active List",   "ZH": "加入激活列表"},
    "body.rename":           {"EN": "Rename",               "ZH": "重命名"},
    "body.rename_blocked":   {"EN": "Rename (preceding item unnamed)", "ZH": "重命名（前有未命名条目）"},

    # ── 校验按钮（panels 删除/校验面板）──────────────────────────────────────
    "validate.run_btn":      {"EN": "Pre-export Validation", "ZH": "导出前校验"},

    # ── 字段绘制 + 面板内通用提示（panels.py）────────────────────────────────
    "field.value":           {"EN": "Value",                "ZH": "值"},
    "block.not_registered":  {"EN": "efx_block not registered (reload the extension)",
                              "ZH": "efx_block 未注册（请重载扩展）"},
    "block.sentinel_no_target":{"EN": "(-1 sentinel, no target)", "ZH": "(-1 哨兵，无目标)"},

    # ── 删除按钮（panels 删除/校验面板，按对象类型）──────────────────────────
    "del.body_btn":      {"EN": "Delete Body",      "ZH": "删除 Body"},
    "del.block_btn":     {"EN": "Delete Block",     "ZH": "删除块"},
    "del.play_btn":      {"EN": "Delete Play",      "ZH": "删除 Play"},
    "del.extern_btn":    {"EN": "Delete Extern",    "ZH": "删除 Extern"},
    "del.subselect_btn": {"EN": "Delete Subselect", "ZH": "删除 Subselect"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.utils.register_class(EFX_OT_set_language)
    load_lang()


def unregister():
    bpy.utils.unregister_class(EFX_OT_set_language)
