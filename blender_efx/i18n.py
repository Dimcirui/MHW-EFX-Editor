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
    "main.new_efx":          {"EN": "New EFX",             "ZH": "新建 EFX"},
    "main.import":           {"EN": "Import EFX",          "ZH": "导入 EFX"},
    "main.export":           {"EN": "Export EFX",          "ZH": "导出 EFX"},
    "main.active_efx":       {"EN": "Active EFX",          "ZH": "当前 EFX"},
    "main.armature":         {"EN": "Armature",            "ZH": "骨架"},
    "main.sync_transform":   {"EN": "Refresh Body Positions", "ZH": "刷新特效体位置"},
    "main.anchor_placement": {"EN": "Anchor to triggering body", "ZH": "锚定到触发它的特效体"},
    "main.blender_coords":   {"EN": "Blender coordinate display", "ZH": "按 Blender 坐标显示 XYZ"},
    "main.double_buffer":    {"EN": "Buffer Size (filesize_double)", "ZH": "缓冲大小 (filesize_double)"},
    "main.double_buffer_tip":{"EN": "Runtime memory buffer hint. Too small → effect disappears. ~2-3.5x filesize.",
                              "ZH": "运行时内存缓冲提示。过小→特效消失。约为文件大小的 2~3.5 倍。"},
    "export.recompute_db":   {"EN": "Auto-recompute filesize_double",
                              "ZH": "自动重算 filesize_double"},
    "export.recompute_db_tip":{"EN": "On export, set filesize_double = max(Root value, ceil16(2.75 x filesize)). "
                                     "Unchecked: use the value stored in Root.",
                               "ZH": "导出时将 filesize_double 设为 max(Root 值, 向上取整到16(2.75 × 文件大小))。"
                                     "不勾：用 Root 里写的值。"},

    # ── 块预设 / 分类（block_ops + 新增块面板）───────────────────────────────
    "block.add_section":     {"EN": "Add Block",           "ZH": "新增块"},
    "block.add_to_prefix":   {"EN": "Add Block to: ",      "ZH": "新增块到："},
    "block.add_to_no_body":  {"EN": "(select a Body)",     "ZH": "（请选中 Body）"},
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
    "block.partial_edit":    {"EN": "Not fully editable",        "ZH": "不支持完全编辑"},
    "block.ptbehavior_hint": {"EN": "Typed sparse override: each property = (key, type, value). Add/remove overrides below; unknown property names show as hash.",
                              "ZH": "类型化稀疏覆盖：每条属性 = (key, 类型, 值)。可在下方增删覆盖项；未知属性名以哈希显示。"},
    "block.ptbehavior_add":  {"EN": "Add Override",          "ZH": "添加覆盖属性"},
    "block.no_fields":       {"EN": "(no fields)",         "ZH": "（无字段）"},
    "block.select_hint":     {"EN": "Select an EFX_BLOCK object", "ZH": "请选中 EFX_BLOCK 对象"},

    # ── 导入/导出算子（operators.py）弹窗 ─────────────────────────────────────
    "op.export_validation_failed_header": {"EN": "Pre-export validation found errors, cancelled:", "ZH": "导出前校验发现错误，已取消："},
    "op.export_validation_failed_title":  {"EN": "EFX Validation Failed", "ZH": "EFX 校验失败"},
    "op.export_skipped_header": {"EN": "Export complete. {n} reference(s) were skipped/cleaned (dangling pointers / out-of-range EOF sentinels):",
                                 "ZH": "导出完成。{n} 个引用被跳过/清理（悬空指针 / EOF 越界哨兵）："},
    "op.export_skipped_title":  {"EN": "EFX Export: References Skipped", "ZH": "EFX 导出：引用已跳过"},

    # ── 导出前校验（validate.py）弹窗 ─────────────────────────────────────────
    "validate.found_errors":   {"EN": "Found {n} error(s):",   "ZH": "发现 {n} 个错误："},
    "validate.found_warnings": {"EN": "Found {n} warning(s):", "ZH": "发现 {n} 个警告："},
    "validate.popup_title":    {"EN": "EFX Validation Results", "ZH": "EFX 校验结果"},

    # ── TIML 互导（timl_io.py）─────────────────────────────────────────────────
    "timl.segment_bytes": {"EN": "TIML segment: {n} bytes", "ZH": "TIML 段：{n} 字节"},
    "timl.none":          {"EN": "No TIML segment in this body", "ZH": "本 body 无 TIML 段"},
    "timl.export_btn":    {"EN": "Export as .timl File",    "ZH": "导出为 .timl 文件"},
    "timl.import_btn":    {"EN": "Reimport from .timl File","ZH": "从 .timl 文件回填"},
    "timl.add_btn":          {"EN": "Add TIML",          "ZH": "添加 TIML"},
    "timl.replace_btn":      {"EN": "Replace TIML",      "ZH": "替换 TIML"},
    "timl.import_file_btn":  {"EN": "Import from File",  "ZH": "从文件导入"},
    "timl.create_blank_btn": {"EN": "Create Blank",      "ZH": "新建空 TIML"},
    "timl.replace_file_btn": {"EN": "Replace from File", "ZH": "从文件替换"},
    "timl.delete_btn":       {"EN": "Delete TIML",       "ZH": "删除 TIML"},
    "timl.hint":          {"EN": ".timl file exchange: Import loads a .timl, Export writes one out. Channel editing is below.",
                           "ZH": ".timl 文件互导：从文件导入载入 .timl，导出写出 .timl。通道编辑见下方。"},

    # ── TIML 头部元字段编辑面板（timl_meta_ui.py，Dope Sheet 侧栏 EFX TIML）────────
    "timlm.panel":          {"EN": "EFX TIML",                "ZH": "EFX TIML"},
    "timlm.no_body":        {"EN": "Select an EFX body with a TIML segment", "ZH": "请选中带 TIML 段的 EFX 特效体"},
    "timlm.no_timl":        {"EN": "This body has no TIML segment", "ZH": "本特效体无 TIML 段"},
    "timlm.anim":           {"EN": "Animation {i}",           "ZH": "动画 {i}"},
    "timlm.length":         {"EN": "Animation Length",        "ZH": "动画长度"},
    "timlm.loop":           {"EN": "Loop Control",            "ZH": "循环控制"},
    "timlm.set_last_kf":    {"EN": "Fit to Last Keyframe",    "ZH": "贴合最后关键帧"},
    "timlm.last_kf":        {"EN": "last keyframe @ {f:g}",   "ZH": "最后关键帧 @ {f:g}"},
    "timlm.no_kf":          {"EN": "(no keyframes)",          "ZH": "（无关键帧）"},
    "timlm.empty_anim":     {"EN": "(empty animation)",       "ZH": "（空动画）"},
    "timlm.auto_grow":      {"EN": "Auto-grow length on edit", "ZH": "编辑时自动增长长度"},
    "timlm.auto_grow_desc": {"EN": "On TIML edit/writeback, grow each animation length to fit its last keyframe (never shrinks; preserves trailing hold frames)",
                             "ZH": "TIML 编辑/回写时，把每条动画长度增长到贴合其最后关键帧（只增不减，保留末尾保持帧）"},
    "timlm.grow_only":      {"EN": "grow-only", "ZH": "只增不减"},
    "timlm.loopstart":      {"EN": "Loop Start", "ZH": "循环起点"},
    # A0/A1 两个固定独立的时间轴（非可增删的动画列表）
    "timlm.axis0":          {"EN": "Emission axis (A0)", "ZH": "发射轴 (A0)"},
    "timlm.axis1":          {"EN": "Lifetime axis (A1)", "ZH": "寿命轴 (A1)"},
    "timlm.axis0_tip":      {"EN": "t=0 at effect trigger — changes over the system's timeline",
                             "ZH": "以特效触发为 0 帧——整条特效随系统时间的变化"},
    "timlm.axis1_tip":      {"EN": "t=0 at each particle's birth — changes over each particle's life",
                             "ZH": "以单粒子诞生为 0 帧——每个粒子一生中的变化"},
    "timlm.axis_empty":     {"EN": "(not used)", "ZH": "（未使用）"},
    "timlm.short0":         {"EN": "Emit", "ZH": "发射"},
    "timlm.short1":         {"EN": "Life", "ZH": "寿命"},
    "timlm.enable_axis":    {"EN": "Enable", "ZH": "启用"},
    "timlm.enabled_axis":   {"EN": "{0} enabled", "ZH": "已启用{0}"},
    "timlm.cleared_axis":   {"EN": "{0} cleared", "ZH": "已清空{0}"},
    "timlm.edit_active":    {"EN": "Channel edit in progress — exit it to enable/clear axes",
                             "ZH": "通道编辑进行中——退出后才能启用/清空轴"},

    # ── TIML 通道编辑会话（timl_edit.py，阶段2b，自建零 FK）──────────────────────
    "timle.enter":          {"EN": "Edit TIML",               "ZH": "编辑 TIML"},
    "timle.enter_hint":     {"EN": "Parses TIML into native F-curves; edit in Dope Sheet / Graph Editor, then Apply",
                             "ZH": "把 TIML 解析成原生 F 曲线；在 Dope Sheet / Graph Editor 编辑后点应用"},
    "timle.editing":        {"EN": "Editing {0} channel(s) in {1} body(ies) — open Dope Sheet/Graph",
                             "ZH": "正在编辑 {0} 条通道（{1} 个特效体）——打开 Dope Sheet/Graph"},
    "timle.editor_hint":    {"EN": "Select an EFX_TIML handle's action in the Dope Sheet / Graph Editor",
                             "ZH": "在 Dope Sheet / Graph Editor 中编辑各 EFX_TIML 句柄的 Action"},
    "timle.apply":          {"EN": "Apply & Exit",            "ZH": "应用并退出"},
    "timle.cancel":         {"EN": "Cancel",                  "ZH": "取消"},
    "timle.all_bodies":     {"EN": "All bodies in this EFX",  "ZH": "同时编辑本 EFX 内所有特效体"},
    "timle.focus":          {"EN": "Focus", "ZH": "焦点"},
    "timle.focus_note":     {"EN": "Switch A0/A1 live (edits kept across switches)", "ZH": "可会话内切 A0/A1（编辑跨切换不丢）"},
    "timle.entered":        {"EN": "TIML channel edit: {0} channel(s) built", "ZH": "TIML 通道编辑：已建 {0} 条通道"},
    "timle.applied":        {"EN": "TIML written back: {0} body(ies)", "ZH": "已回写 TIML：{0} 个特效体"},

    # ── 统一预览面板（efx_preview.py，点5）────────────────────────────────────────
    "efxprev.scope":        {"EN": "Scope", "ZH": "作用域"},
    "efxprev.scope_all":    {"EN": "All bodies in this EFX", "ZH": "本 EFX 内所有特效体"},
    "efxprev.targets":      {"EN": "Targets", "ZH": "启用项"},
    "efxprev.t_uvc":        {"EN": "UVCONTROL UV scroll", "ZH": "UVCONTROL UV 滚动"},
    "efxprev.t_timl":       {"EN": "TIML transform playback", "ZH": "TIML transform 播放"},
    "efxprev.t_mesh":       {"EN": "Mesh placement (TRANSFORM3D+MESH)", "ZH": "网格摆放（TRANSFORM3D+MESH）"},
    "efxprev.enter":        {"EN": "Enter Preview", "ZH": "进入预览"},
    "efxprev.exit":         {"EN": "Exit Preview", "ZH": "退出预览"},
    "efxprev.started":      {"EN": "Preview started: {0}", "ZH": "已进入预览：{0}"},
    "efxprev.none_started": {"EN": "Nothing started (check targets / selection)", "ZH": "未启用任何项（检查勾选/选择）"},
    "efxprev.exited":       {"EN": "Preview exited", "ZH": "已退出预览"},
    "efxprev.discard_note": {"EN": "Read-only preview: exiting always discards. To edit & write back, use Edit TIML in the TIML panel.",
                             "ZH": "只读预览：退出一律丢弃。要编辑并回写请用 TIML 面板的「编辑 TIML」。"},
    "timle.applied_nochange": {"EN": "No changes — TIML left byte-identical", "ZH": "无改动——TIML 保持逐字节一致"},
    "timle.cancelled":      {"EN": "TIML channel edit cancelled (discarded)", "ZH": "已取消 TIML 通道编辑（丢弃）"},
    "timle.no_timl":        {"EN": "Select an EFX_TIML handle (or a body with TIML) first", "ZH": "请先选中 EFX_TIML 句柄（或带 TIML 的特效体）"},
    "timle.no_content":     {"EN": "No editable TIML channels found", "ZH": "未找到可编辑的 TIML 通道"},
    "timle.build_failed":   {"EN": "Failed to build channels: {0}", "ZH": "建通道失败：{0}"},
    "timle.writeback_failed": {"EN": "Writeback failed: {0}", "ZH": "回写失败：{0}"},

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
    "play.entry_type":            {"EN": "Entry Type",      "ZH": "条目类型"},
    "play.add_entry":             {"EN": "Add Entry",       "ZH": "新增条目"},
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
    "extern.force_unlock":       {"EN": "Force Unlock (dangling)", "ZH": "强制解锁（悬空指针）"},

    # ── PtLife / PtCollision / EOF 指针面板（body_play_ref.py）────────────────
    "ptref.no_ptlife_data":      {"EN": "(No efx_ptlife_ref data)", "ZH": "（无 efx_ptlife_ref 数据）"},
    "ptref.relation_index_title":{"EN": "Relation Index (action reference)", "ZH": "Relation Index (action 引用)"},
    "ptref.relation_oob":        {"EN": "[Out of range/negative, original bytes preserved]",
                                  "ZH": "[越界/负值，原始字节保留]"},
    "ptref.assign_play":         {"EN": "Assign Play target", "ZH": "指定 Play 目标"},
    "ptref.assign_hint":         {"EN": "Pick a Play to re-link this block (original bytes kept until you do)",
                                  "ZH": "选择一个 Play 重新关联本块（未选前保留原始字节）"},
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
    "ptref.game_activated_bodies":{"EN": "Bodies triggered directly on EFX load", "ZH": "EFX 加载时直接触发的 Body"},
    "ptref.eof_empty":           {"EN": "(Empty - effect will not be triggered directly on load)",
                                  "ZH": "（空——EFX 加载时不会直接触发任何 Body）"},
    "ptref.dangling_pointer":    {"EN": "[Dangling pointer]", "ZH": "[悬空指针]"},
    "ptref.eof_sentinel":        {"EN": "raw={v} (out-of-range sentinel)", "ZH": "raw={v}（越界空槽）"},
    "ptref.eof_sentinel_hint":   {"EN": "Out-of-range entries are inactive-slot sentinels (no such body); dropped on export once the active set is edited",
                                  "ZH": "越界条目是空槽哨兵（无对应 body）；编辑激活集后导出时会被清理"},

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

    # ── Body 双向关系视图（Body References，backref.py §4）────────────────────
    "bodyref.none":                {"EN": "No references to/from this body", "ZH": "此 body 无任何引用关系"},
    "bodyref.triggers_header":     {"EN": "Triggers (this body spawns):", "ZH": "我触发谁（本 body 生成）："},
    "bodyref.triggered_by_header": {"EN": "Triggered by (spawned by):", "ZH": "谁触发我（本 body 被生成）："},
    "bodyref.externs_header":      {"EN": "Externs referenced", "ZH": "我引用的 Extern"},
    "bodyref.subselect_header":    {"EN": "In Subselect tables", "ZH": "我所属的 Subselect"},
    "bodyref.timing_spawn":        {"EN": "on spawn", "ZH": "生成时"},
    "bodyref.timing_death":        {"EN": "on death", "ZH": "消亡时"},
    "bodyref.timing_other":        {"EN": "timing", "ZH": "timing"},
    "bodyref.trigger_collision":   {"EN": "on collision", "ZH": "碰撞时"},

    # ── ROOT subselect 状态总览（backref.py §5；模型推测）──────────────────────
    "rootstate.no_states":        {"EN": "No subselect tables (no state gating)", "ZH": "无 subselect 表（无状态门控）"},
    "rootstate.header":           {"EN": "Subselect states (variants)", "ZH": "Subselect 状态（变体）"},
    "rootstate.state_prefix":     {"EN": "State",  "ZH": "状态"},
    "rootstate.empty_table":      {"EN": "(empty table)", "ZH": "（空表）"},
    "rootstate.always_on_header": {"EN": "Always-on (direct, ungated)", "ZH": "恒触发（直接、无门控）"},
    "rootstate.always_on_empty":  {"EN": "(none)", "ZH": "（无）"},
    "rootstate.hint":             {"EN": "Inferred model: the game picks which state fires at runtime; bodies in no table always fire",
                                   "ZH": "推测模型：运行时由游戏选中触发哪个状态；不在任何表里的 body 恒触发"},

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
    "body.game_active_yes":  {"EN": "Direct trigger: Yes",  "ZH": "直接触发：是"},
    "body.game_active_no":   {"EN": "Direct trigger: No",   "ZH": "直接触发：否"},
    "body.action_trigger_yes": {"EN": "Action trigger: Yes",  "ZH": "动作触发：是"},
    "body.action_trigger_no":  {"EN": "Action trigger: No",   "ZH": "动作触发：否"},
    # ── 有效激活态（派生，backref.classify_body_activation；模型推测）─────────────
    "body.effective_label":    {"EN": "Effective (inferred):", "ZH": "有效行为（推测）："},
    # 触发来源（direct 与 action 是「并」/OR：两者都有则两种时机都触发）
    "body.src_both":           {"EN": "Fires on load AND when summoned", "ZH": "加载时与被召唤时均触发"},
    "body.src_direct":         {"EN": "Fires on load",               "ZH": "加载即触发"},
    "body.src_action":         {"EN": "Fires when summoned by Play",  "ZH": "被 Play 召唤时触发"},
    "body.src_none":           {"EN": "No trigger source",           "ZH": "无触发来源（孤儿/死块）"},
    # subselect 是更上层的「与」/AND 门控：还须满足该状态条件才触发
    "body.gate_qualifier":     {"EN": " — only if its state is selected", "ZH": " — 还须其状态被选中"},
    "body.gating_yes":         {"EN": "State-gated (AND) by {n} subselect table(s)", "ZH": "受 {n} 张 subselect 表门控（与）"},
    "body.gating_no":          {"EN": "No subselect gating (fires unconditionally)",   "ZH": "无 subselect 门控（无条件触发）"},
    "body.add_to_prefix":    {"EN": "Add Body to: ",         "ZH": "新增 Body 到："},
    "body.add_to_no_efx":    {"EN": "(no active EFX)",       "ZH": "（未选中 EFX 文件）"},
    "body.remove_from_active":{"EN": "Remove from Direct Trigger", "ZH": "移出直接触发列表"},
    "body.add_to_active":    {"EN": "Add to Direct Trigger",   "ZH": "加入直接触发列表"},
    "body.rename":           {"EN": "Rename",               "ZH": "重命名"},
    "body.rename_blocked":   {"EN": "Rename (preceding item unnamed)", "ZH": "重命名（前有未命名条目）"},
    "body.type_label":       {"EN": "Type: ",               "ZH": "类型："},
    "body.type_standard":    {"EN": "Standard",             "ZH": "标准"},
    "body.type_extended":    {"EN": "Extended",             "ZH": "扩展"},

    # ── 校验按钮（panels 删除/校验面板）──────────────────────────────────────
    "validate.run_btn":      {"EN": "Pre-export Validation", "ZH": "导出前校验"},

    # ── 字段绘制 + 面板内通用提示（panels.py）────────────────────────────────
    "field.value":           {"EN": "Value",                "ZH": "值"},
    "field.jitter":          {"EN": "Jitter",               "ZH": "抖动"},
    "field.ref_via_pointer": {"EN": "set in the Play pointer panel below", "ZH": "在下方 Play 指针面板设置"},
    "material.type":         {"EN": "Material type:", "ZH": "主材质类型："},
    "block.not_registered":  {"EN": "efx_block not registered (reload the extension)",
                              "ZH": "efx_block 未注册（请重载扩展）"},
    "block.sentinel_no_target":{"EN": "(-1 sentinel, no target)", "ZH": "(-1 哨兵，无目标)"},

    # ── 删除按钮（panels 删除/校验面板，按对象类型）──────────────────────────
    "del.body_btn":      {"EN": "Delete Body",      "ZH": "删除 Body"},
    "del.block_btn":     {"EN": "Delete Block",     "ZH": "删除块"},
    "del.play_btn":      {"EN": "Delete Play",      "ZH": "删除 Play"},
    "del.extern_btn":    {"EN": "Delete Extern",    "ZH": "删除 Extern"},
    "del.subselect_btn": {"EN": "Delete Subselect", "ZH": "删除 Subselect"},

    # ── 新建段条目（panels 新建面板）──────────────────────────────────────────
    "addsec.play":      {"EN": "Add Play (Action)", "ZH": "新建 Play(动作)"},
    "addsec.extern":    {"EN": "Add Extern",        "ZH": "新建 Extern"},
    "addsec.subselect": {"EN": "Add Subselect",     "ZH": "新建 Subselect"},
    "addsec.hint":      {"EN": "Exporter recomputes header automatically",
                         "ZH": "导出端自动重算 header/标签"},

    # ── Play / Extern 重命名 ─────────────────────────────────────────────────
    "entry.rename":         {"EN": "Rename", "ZH": "重命名"},
    "entry.rename_blocked": {"EN": "Rename (blocked: a preceding Play/Extern is unnamed)",
                             "ZH": "重命名（被前导未命名 Play/Extern 锁定）"},

    # ── UVCONTROL 预览（uvc_preview.py）───────────────────────────────────────
    "uvc.bind_target_hint":  {"EN": "Preview target mesh (your own; a material with base textures is enough)",
                              "ZH": "预览目标网格（用户自备、接好基础贴图的材质即可）"},
    "uvc.previewable":       {"EN": "Previewable ({0})",      "ZH": "可预览（{0}）"},
    "uvc.not_previewable":   {"EN": "Cannot preview: {0}",    "ZH": "无法预览：{0}"},
    "uvc.need_texture":      {"EN": "Material needs an image texture (Mapping auto-connected on preview)",
                              "ZH": "材质需含图像纹理（进入预览时自动接 Mapping 滚动）"},
    "uvc.reason_has_mapping":{"EN": "has Mapping node",       "ZH": "已有 Mapping 节点"},
    "uvc.reason_auto_mapping":{"EN": "Mapping auto-inserted to drive textures", "ZH": "可自动插入 Mapping 驱动图像纹理"},
    "uvc.reason_no_node_mat":{"EN": "mesh has no node-based material", "ZH": "网格没有启用节点的材质"},
    "uvc.reason_no_texture": {"EN": "no scrollable image texture in material", "ZH": "材质里找不到可滚动的图像纹理"},
    "uvc.timeline_hint":     {"EN": "Drag/play the timeline to preview", "ZH": "进入后拖动/播放时间线即预览"},
    "uvc.previewing":        {"EN": "Previewing ({0} pair(s))", "ZH": "预览中（{0} 个配对）"},
    "uvc.enter":             {"EN": "Enter Preview (all bound)", "ZH": "进入预览（全部已绑定）"},
    "uvc.exit":              {"EN": "Exit Preview",          "ZH": "退出预览"},
    "uvc.all_efx":           {"EN": "Preview all EFX at once", "ZH": "同时播放所有 EFX"},
    "uvc.scope_all":         {"EN": "Will drive bound meshes of ALL EFX in the scene",
                              "ZH": "将驱动场景内所有 EFX 的已绑定网格"},
    "uvc.scope_one":         {"EN": "Will drive all bound meshes of this EFX (bind on the MESH block)",
                              "ZH": "将驱动本 EFX 全部已绑定网格（绑定在 MESH 块上设置）"},
    "uvc.entered":           {"EN": "Preview started (UV {0}, transformed mesh {1})",
                              "ZH": "已进入预览（UV {0} 个，变换网格 {1} 个）"},
    "uvc.exited":            {"EN": "Preview ended, materials restored", "ZH": "已退出预览，材质已还原"},
    "uvc.no_content":        {"EN": "Nothing to preview (bind a mesh on the MESH block first)",
                              "ZH": "没有可预览的内容（请先在 MESH 块上绑定网格）"},
    "uvc.no_efx_scene":      {"EN": "No EFX found in the scene", "ZH": "场景里找不到任何 EFX"},
    "uvc.no_root":           {"EN": "EFX root not found (select an EFX body/block)",
                              "ZH": "找不到 EFX 根集合（请选中某个 EFX 的 body/块）"},
    "uvc.missing_header":    {"EN": "These bound meshes can't preview, fix their materials first: {0}",
                              "ZH": "以下绑定网格无法预览，请先处理好材质：{0}"},

    # ── 绑定网格实时对齐预览（mesh_align） ─────────────────────────────────────
    "align.hint":            {"EN": "Spawns instances of bound meshes placed by TRANSFORM3D + MESH rotation/scale; edits realign live",
                              "ZH": "按 TRANSFORM3D + MESH 旋转/缩放摆放绑定网格的实例；会话内编辑实时重对齐"},
    "align.all_efx":         {"EN": "Align all EFX in scene", "ZH": "所有 EFX 一起对齐"},
    "align.enter":           {"EN": "Enter Mesh Align", "ZH": "进入网格对齐"},
    "align.exit":            {"EN": "Exit Mesh Align", "ZH": "退出网格对齐"},
    "align.previewing":      {"EN": "Aligning {0} instance(s)", "ZH": "正在对齐 {0} 个实例"},
    "align.entered":         {"EN": "Mesh align started ({0} instance)", "ZH": "已进入网格对齐（{0} 个实例）"},
    "align.exited":          {"EN": "Mesh align ended, instances removed", "ZH": "已退出网格对齐，实例已清除"},
    "align.no_content":      {"EN": "Nothing to align (bind a mesh on a MESH block first)",
                              "ZH": "没有可对齐的内容（请先在 MESH 块上绑定网格）"},
    "align.no_root":         {"EN": "EFX root not found (select an EFX body/block)",
                              "ZH": "找不到 EFX 根集合（请选中某个 EFX 的 body/块）"},
    "align.failed":          {"EN": "Mesh align failed: {0}", "ZH": "网格对齐失败：{0}"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.utils.register_class(EFX_OT_set_language)
    load_lang()


def unregister():
    bpy.utils.unregister_class(EFX_OT_set_language)
