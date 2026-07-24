"""
blender_efx/operators.py  —  L1.0 + L1.2 + L1.3 扩展：导入/导出算子 + 预设算子 + FileHandler

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：Operator / ImportHelper / ExportHelper / register_class
  - FileHandler：Blender 4.1+ 稳定 API（4.3.2 / 5.1 均有）
  - 不使用 5.x 新增 API
  - 不改 io_tree.py / efx_format/

字段复用：efx.copy_attribute_fields / efx.paste_attribute_fields（即时内存剪贴板）。
  （旧「字段值预设」算子 save/apply_attribute_preset 已移除，整属性预设见 attribute_ops。）

L1.3 拖入导入（FileHandler）：
  EFX_FH_import  —  注册 .efx 文件拖入 3D 视口时调用 efx.import_efx
  efx.import_efx 补充 files+directory 属性支持 FileHandler 调用约定，
  同时保持原有"文件浏览器/按钮选文件导入"用法不变。
"""

import os
import re
import struct

import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import (
    StringProperty, CollectionProperty, EnumProperty, IntProperty, BoolProperty,
    PointerProperty,
)

from . import io_tree
from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具：从 context 解析 EFX_ROOT 集合
# ─────────────────────────────────────────────────────────────────────────────

def _find_efx_root(context):
    """
    解析当前活动 EFX 顶层文件集合（root_col）。

    优先 context.active_object 归属的集合（O(1)，见 root_collection.find_root_collection）；
    若无活动对象或解析不到，退回 context.collection（大纲当前选中的集合，可能就是
    某个 EFX_ROOT 集合本身，比如用户直接点了顶层紫色集合）。

    返回
    ----
    bpy.types.Collection 或 None
    """
    obj = context.active_object
    if obj is not None:
        root = _rc.find_root_collection(obj)
        if root is not None:
            return root

    col = getattr(context, "collection", None)
    if _rc.is_root_collection(col):
        return col

    return None


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_import
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_import(bpy.types.Operator, ImportHelper):
    """导入 MHW .efx 特效文件，在场景中建立对象树"""

    bl_idname      = "efx.import_efx"
    bl_label       = "Import EFX"
    bl_description = "Import an MHW EFX effect file (.efx)"
    bl_options     = {"REGISTER", "UNDO"}

    # ImportHelper 所需：文件扩展名与过滤器
    filename_ext = ".efx"
    filter_glob: StringProperty(
        default="*.efx",
        options={"HIDDEN"},
        maxlen=255,
    )

    # L1.3 FileHandler 支持：FileHandler 调用时传入 directory + files（OperatorFileListElement 列表）
    # ImportHelper 提供的 filepath 在单文件菜单路径下使用；
    # FileHandler 拖入时使用 directory + files 约定（Blender 4.1+ FileHandler 标准）。
    # 两种调用路径均由同一个 execute 统一处理。
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(
        subtype="DIR_PATH",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    # 可勾选项（默认关）：导入时一并把 MESH 属性引用的 mod3（含 mrl3+材质）经 Model Editor 导入并绑定。
    # Model Editor 缺席时此项无效（draw 里禁用）。
    import_meshes: BoolProperty(
        name="Import referenced meshes (mod3)",
        description="同时把每个 MESH 属性引用的 mod3（含 mrl3 与材质）经 MHW Model Editor 导入并绑定到预览。"
                    "需安装 Model Editor。提取根目录默认从 efx 位置向上自动找 nativePC，找不到时再用下方 Chunk Root",
        default=False,
        options={"SKIP_SAVE"},
    )

    # EFX Color Editor 分支：勾选后整个工具切换成"只管颜色"的傻瓜调色模式——
    # 完整解析+建树完全不变（数据 100% 保留，导出仍是完整合法 .efx），只是把
    # 非颜色内容从 Outliner 隐藏（View Layer 排除，不删数据）。见 io_tree.py
    # ::import_efx_tree 的 color_editor_mode 参数 + _apply_color_editor_view。
    import_only_colors: BoolProperty(
        name="Import Only Colors",
        description="只暴露含颜色/亮度字段的 entry 与 attribute，其余内容（结构编辑/TIML/"
                    "预设等）在此文件里隐藏——供只想改色、不想碰其他任何东西的场景使用。"
                    "导出仍是完整合法的 .efx",
        default=False,
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, event):
        # FileHandler 拖入：不再静默导入，弹一个属性对话框让用户确认 / 勾选是否一并导入 mesh。
        # （ImportHelper 默认 invoke 总是开浏览器，会让拖入"无反应"——故拖入走 props_dialog。）
        if self.directory and self.files:
            return context.window_manager.invoke_props_dialog(self)
        # 普通菜单/按钮：走 ImportHelper 的文件浏览器（选项显示在浏览器侧栏的 draw 里）。
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        # 文件浏览器侧栏 / 拖入对话框共用：仅颜色开关 + mesh 导入开关 + chunk root。
        # 两者互斥（Color Editor 是傻瓜调色模式，不需要 mod3 相关控件）：勾了
        # "仅导入颜色"就不再显示 mesh 导入选项。
        layout = self.layout
        layout.prop(self, "import_only_colors")
        if self.import_only_colors:
            return
        from . import mod3_link
        if mod3_link.model_editor_available():
            layout.prop(self, "import_meshes")
            if self.import_meshes:
                box = layout.box()
                box.label(text="提取根：默认自动找 nativePC；找不到才用下方", icon="FILE_FOLDER")
                box.prop(context.scene, "efx_chunk_root", text="Chunk Root")
        else:
            layout.label(text="装 MHW Model Editor 后可勾选「一并导入 mod3」", icon="INFO")

    def execute(self, context):
        import os

        # ── 收集要导入的路径列表 ─────────────────────────────────────────────
        # 优先使用 files+directory（FileHandler 拖入路径）；
        # 若 files 为空则退回到 ImportHelper 的 self.filepath（菜单选文件路径）。
        paths = []
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(self.directory, f.name))

        if not paths:
            # 菜单/按钮单文件路径
            if self.filepath:
                paths = [self.filepath]

        if not paths:
            self.report({"ERROR"}, "EFX import: no file path specified")
            return {"CANCELLED"}

        # ── 逐文件导入 ───────────────────────────────────────────────────────
        imported = []
        imported_roots = []
        imported_paths = []   # 与 imported_roots 一一对应的源文件路径（用于 mod3 同目录兜底）
        errors = []
        for filepath in paths:
            try:
                root_obj = io_tree.import_efx_tree(
                    filepath, context, color_editor_mode=self.import_only_colors,
                )
                imported.append(root_obj.name)
                imported_roots.append(root_obj)
                imported_paths.append(filepath)
            except Exception as exc:
                import traceback
                errors.append(f"{os.path.basename(filepath)}: {exc}")
                self.report(
                    {"ERROR"},
                    f"EFX import failed: {filepath}\n{traceback.format_exc()}",
                )

        # ── 导入后按 TRANSFORM3D + 绑定骨骼(bone_lim) 摆放各特效体 ────────────
        # 骨架取 N 面板的 Scene.efx_armature（未选则以世界原点为基准）。
        if imported_roots:
            try:
                from . import transform_sync
                armature = getattr(context.scene, "efx_armature", None)
                use_anchor = getattr(context.scene, "efx_anchor_placement", True)
                for root_obj in imported_roots:
                    transform_sync.sync_all_transform3d(root_obj, armature, use_anchor=use_anchor)
            except Exception:
                pass  # 摆位是可视化增强，失败不影响导入本身

        # ── 可勾选：一并导入 MESH 属性引用的 mod3（含 mrl3+材质）并绑定 ──────────────
        # 默认关；仅当用户勾选 + Model Editor 在场时执行。失败不影响 EFX 导入本身。
        if imported_roots and self.import_meshes and not self.import_only_colors:
            from . import mod3_link
            if not mod3_link.model_editor_available():
                self.report({"WARNING"}, "未检测到 MHW Model Editor，已跳过 mod3 导入")
            else:
                chunk_root = getattr(context.scene, "efx_chunk_root", "") or ""
                total_bound = 0
                all_unresolved = []
                for root_obj, fpath in zip(imported_roots, imported_paths):
                    try:
                        n, unresolved = mod3_link.import_and_bind(
                            root_obj, context, chunk_root, os.path.dirname(fpath)
                        )
                        total_bound += n
                        all_unresolved.extend(unresolved)
                    except Exception:
                        pass
                if total_bound:
                    self.report({"INFO"}, f"已导入并绑定 {total_bound} 个 mod3 网格")
                if all_unresolved:
                    detail = "；".join(f"{n}（{r}）" for n, r in all_unresolved[:6])
                    self.report({"WARNING"}, f"{len(all_unresolved)} 个 mod3 未找到（检查 Chunk Root）：{detail}")

        if imported:
            names = ", ".join(imported)
            self.report({"INFO"}, f"EFX import complete: {names}")

        # 有任何成功导入则返回 FINISHED；全部失败才返回 CANCELLED
        if imported:
            return {"FINISHED"}
        return {"CANCELLED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_export：目标 EFX 集合选择 + 文件名默认值/"记住自定义名"
# ─────────────────────────────────────────────────────────────────────────────

# 会话级记忆（模块全局，跨多次导出调用持续，Blender 重启清空）：
#   _last_export_name  用户上次手动改过的导出文件名（不含扩展名）；None = 跟随目标集合名自动生成。
#   _last_export_dir    用户上次导出用的目录，下次默认沿用；None = 回退到 .blend 所在目录。
#   _last_export_target_seen  draw() 里检测"用户是否手动改了目标集合下拉"的基准值
#     （WindowManager 属性的 update 回调收到的是 wm 而非算子实例，摸不到 self.filepath，
#     故改在 draw() 里逐帧比对；invoke() 设默认值后同步这个值，避免首次绘制误判为用户改动）。
_last_export_name = None
_last_export_dir = None
_last_export_target_seen = None


def _efx_root_in_collection(col):
    """col 本身是否是合法 EFX_ROOT 顶层文件集合；是则原样返回，否则 None。"""
    return col if _rc.is_root_collection(col) else None


def _export_target_poll(self, col):
    """WindowManager.efx_export_target 的 poll：只允许选 EFX_ROOT 顶层文件集合本身。"""
    return _efx_root_in_collection(col) is not None


def _default_export_basename(collection) -> str:
    """
    按集合名生成默认导出文件名（不含扩展名）：
      去掉 Blender 因重名追加的 ".001" 等后缀，再去掉集合名里已带的 ".efx" 后缀。
    collection 为 None（未选定目标）时返回 "untitled"。
    """
    if collection is None:
        return "untitled"
    name = re.sub(r'\.\d{3}$', '', collection.name)
    if name.lower().endswith(".efx"):
        name = name[:-4]
    return name or "untitled"


def _resolve_default_export_collection(context):
    """
    导出目标集合的默认值解析：
      1. Scene.efx_active_efx（N 面板 Active EFX 选择器）已指向合法 EFX 集合 → 用它。
      2. 否则回退：当前活动对象所属的 EFX 顶层文件集合（_find_efx_root 解析）。
      3. 都没有 → None（留给用户在导出弹窗里自己选）。
    """
    scn = getattr(context, "scene", None)
    active_col = getattr(scn, "efx_active_efx", None) if scn is not None else None
    if _efx_root_in_collection(active_col) is not None:
        return active_col

    root = _find_efx_root(context)
    if root is not None:
        return root
    return None


class EFX_OT_export(bpy.types.Operator, ExportHelper):
    """将当前选中的 EFX 对象树导出为 .efx 文件"""

    bl_idname      = "efx.export_efx"
    bl_label       = "Export EFX"
    bl_description = "Export the EFX object tree to an MHW .efx file"
    bl_options     = {"REGISTER", "UNDO"}

    # ExportHelper 所需：文件扩展名
    filename_ext = ".efx"
    filter_glob: StringProperty(
        default="*.efx",
        options={"HIDDEN"},
        maxlen=255,
    )

    # 自动重算 filesize_double（doubleBuffer，header 偏移 68）。
    # 勾选：导出后将其设为 max(Root 值, ceil16(2.0 × 文件大小))，防止增量编辑后缓冲偏小
    # 导致特效消失。⚠ 系数曾用 2.75，实测 buffer 过大也会 CTD（wp09_050），已下调到 2.0。
    # 不勾：原样使用 Root 里 hdr_double_buffer 的值（byte-perfect 往返）。
    recompute_double_buffer: BoolProperty(
        name=T("export.recompute_db"),
        description=T("export.recompute_db_tip"),
        default=True,
    )

    # 自动校正 header.is_3d（2D/3D 特效类型标志，header 偏移 32）。
    # 勾选：文件内容只有 2D 或只有 3D 类型时，自动把 is_3d 设为匹配值（0/1）；
    # 内容混用 2D+3D 时不动，交给导出校验的 WARN 提示手动处理。
    # 不勾：原样使用 Root 里 hdr_is_3d 的值——刻意测试 mismatch 场景时应关闭。
    auto_fix_is_3d: BoolProperty(
        name=T("export.auto_fix_is3d"),
        description=T("export.auto_fix_is3d_tip"),
        default=True,
    )

    # 导出前按游戏惯用顺序静默重排每个 entry 内的属性（见 reorder.py::auto_sort_entry_attributes）。
    # 不勾：保留用户自己排的属性顺序，不做任何调整。
    auto_sort_attributes: BoolProperty(
        name=T("export.auto_sort"),
        description=T("export.auto_sort_tip"),
        default=True,
    )

    # 导出时把每条 TIML 动画长度精确设为 末关键帧+1（逐轴 A0/A1）。
    # 理由：帧长 ≤ 实际结束帧会导致游戏内动画播不完，+1 刚好覆盖到末帧之后。
    recalc_timl_length: BoolProperty(
        name=T("export.recalc_timl_len"),
        description=T("export.recalc_timl_len_tip"),
        default=True,
    )

    def draw(self, context):
        global _last_export_name, _last_export_target_seen
        layout = self.layout
        wm = context.window_manager
        layout.prop(wm, "efx_export_target", text=T("export.target_efx"))

        # WindowManager 属性没法在 update 回调里摸到这个算子实例（收到的是 wm 不是 self），
        # 改在 draw() 里逐帧比对：目标集合变了就刷新文件名为该集合默认名（放弃自定义名）。
        cur = wm.efx_export_target
        if cur is not _last_export_target_seen:
            _last_export_target_seen = cur
            _last_export_name = None
            base = _default_export_basename(cur)
            directory = os.path.dirname(self.filepath) if self.filepath else (_last_export_dir or "")
            self.filepath = os.path.join(directory, base + self.filename_ext) if directory else base + self.filename_ext

        layout.prop(self, "recompute_double_buffer")
        if not self.recompute_double_buffer and cur is not None and "hdr_double_buffer" in cur:
            # 不自动重算：手填 filesize_double（doubleBuffer）原样使用的值。
            # 挪到导出弹窗里紧跟勾选框下面，免去单独开 ROOT 面板找这一个字段。
            box = layout.box()
            box.prop(cur, '["hdr_double_buffer"]', text=T("entry.double_buffer"))
            tip = box.row()
            tip.enabled = False
            tip.label(text=T("entry.double_buffer_tip"))
        layout.prop(self, "auto_sort_attributes")
        layout.prop(self, "recalc_timl_length")
        layout.prop(self, "auto_fix_is_3d")

    def invoke(self, context, event):
        global _last_export_target_seen
        default_col = _resolve_default_export_collection(context)
        context.window_manager.efx_export_target = default_col
        _last_export_target_seen = default_col   # 首次绘制时不算"用户手动改动"

        base = _last_export_name or _default_export_basename(default_col)
        directory = _last_export_dir
        if not directory:
            blend_path = context.blend_data.filepath
            directory = os.path.dirname(blend_path) if blend_path else ""
        self.filepath = os.path.join(directory, base + self.filename_ext) if directory else base + self.filename_ext

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        # ── 1. 解析要导出的 EFX_ROOT ─────────────────────────────────────────
        # 优先用导出弹窗里选的 efx_export_target；否则 N 面板的 Active EFX；否则活动对象所属的 EFX。
        # 这样不必非得选中 EFX 内某个对象——选好任一个即可导出。
        from .add_ops import get_active_efx_root
        target_col = context.window_manager.efx_export_target
        root = _efx_root_in_collection(target_col) or get_active_efx_root(context) or _find_efx_root(context)
        if root is None:
            self.report(
                {"ERROR"},
                "No EFX specified for export: select an Active EFX collection in the N-panel EFX area, or select any object in the EFX object tree",
            )
            return {"CANCELLED"}

        # ── 1.5 导出前校验（#4）：仅真正的 ERROR（重复 index / 互斥块等）取消导出 ──
        # 悬空指针 / EOF 越界 raw 哨兵已降级为 WARN：导出端安全跳过/清理，不挡导出，
        # 仅在导出后弹窗报告（让用户知道哪些引用被跳过/清理）。
        from .validate import validate_efx_tree, detect_dimension_entries
        problems = validate_efx_tree(root)
        errors = [p for p in problems if p["level"] == "ERROR"]
        if errors:
            def _draw(self_menu, ctx):
                col = self_menu.layout.column()
                col.label(text=T("op.export_validation_failed_header"), icon="ERROR")
                for p in errors[:20]:
                    col.label(text="• " + p["msg"])
            context.window_manager.popup_menu(
                _draw, title=T("op.export_validation_failed_title"), icon="ERROR",
            )
            self.report({"ERROR"}, f"EFX export cancelled: {len(errors)} validation error(s)")
            return {"CANCELLED"}

        # 收集导出会跳过/清理的引用（悬空指针 + EOF 越界 raw），导出成功后报告
        skipped = [p for p in problems
                   if p.get("category") in ("dangling", "eof_raw")]

        # ── 1.65 导出前规范化：efx_index 撞车重编号 + 满命名（结构权威下放）────────────
        # 兜底原生 Shift+D 造成的同级 index 撞车（重编号成唯一 0..n-1）+ 给会话中新增/
        # 未命名段补标签。放在 auto_sort 之前：先化解撞车，再由 auto_sort 施加类型顺序。
        try:
            from . import normalize
            if normalize.normalize_root(root):
                root["labels_dirty"] = 1  # 满命名/重编号可能改标签表 → 导出重建
        except Exception:
            pass  # 规范化失败不阻断导出

        # ── 1.66 导出前自动校正 header.is_3d（可通过 auto_fix_is_3d 关闭）───────────
        # is_3d 是文件级 2D/3D 特效类型标志（见 memory header-is-3d-flag-discovery）：
        # 语料库 10162 样本零例外——含 TRANSFORM2D 的 entry 只出现在 is_3d=0 文件，
        # 含 TRANSFORM3D 的只出现在 is_3d=1 文件；实机确认 mismatch（尤其叠加
        # SHADERSETTINGS/ALPHACORRECTION 等修饰属性后）会导致游戏闪退。
        # 只在文件内容单一（只有 2D 或只有 3D）时才自动改；两者都有（混用）不动，
        # 留给 validate 的 (5l) WARN 提示用户手动决定——这种情况没有"正确"的自动值。
        if self.auto_fix_is_3d:
            try:
                dim_2d, dim_3d = detect_dimension_entries(root)
                if dim_2d and not dim_3d:
                    correct_is_3d = "0"
                elif dim_3d and not dim_2d:
                    correct_is_3d = "1"
                else:
                    correct_is_3d = None
                if correct_is_3d is not None and str(root.get("hdr_is_3d", "")) != correct_is_3d:
                    root["hdr_is_3d"] = correct_is_3d
            except Exception:
                pass  # 校正失败不阻断导出

        # ── 1.7 导出前静默规范化属性顺序（可通过 auto_sort_attributes 关闭）────────────
        if self.auto_sort_attributes:
            try:
                from .reorder import auto_sort_entry_attributes
                auto_sort_entry_attributes(root)
            except Exception:
                pass  # 排序失败不阻断导出

        # ── 2. 导出为字节 ───────────────────────────────────────────────────
        try:
            data = io_tree.export_efx_tree(root, recalc_timl_length=self.recalc_timl_length)
        except Exception as exc:
            import traceback
            self.report(
                {"ERROR"},
                f"EFX export serialization failed: {exc}\n{traceback.format_exc()}",
            )
            return {"CANCELLED"}

        # ── 2.5 自动重算 filesize_double（doubleBuffer @ header 偏移 68，uint LE）──
        # 公式：max(原值, ceil16(2.0 × 文件大小))。原地覆写 4 字节（不改文件长度，
        # 故 len(data) 即最终文件大小）。只增不减：未变大的文件仍保留原值。
        # ⚠ 系数从 2.75 下调到 2.0：实测 buffer 过大同样会 CTD（wp09_050 原值 1.55×
        #   工作正常，2.75×→21040 崩），2.75 并非安全上界；2.0 折中降低超额风险。
        _db_note = ""
        if self.recompute_double_buffer:
            import math
            old_db = struct.unpack_from("<I", data, 68)[0]
            new_db = max(old_db, (math.ceil(2.0 * len(data)) + 15) // 16 * 16)
            if new_db != old_db:
                data = data[:68] + struct.pack("<I", new_db) + data[72:]
                # 同步回写 Root，保持 UI 显示与文件一致
                root["hdr_double_buffer"] = str(new_db)
            _db_note = f", filesize_double {old_db}→{new_db}"

        # ── 3. 写文件 ───────────────────────────────────────────────────────
        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to write file: {exc}")
            return {"CANCELLED"}

        # ── 3.5 报告被跳过/清理的引用（悬空指针 + EOF 越界 raw 哨兵）──────────────
        if skipped:
            def _draw_skipped(self_menu, ctx):
                col = self_menu.layout.column()
                col.label(
                    text=T("op.export_skipped_header").format(n=len(skipped)),
                    icon="INFO",
                )
                for p in skipped[:20]:
                    col.label(text="• " + p["msg"])
                if len(skipped) > 20:
                    col.label(text="… (+%d more)" % (len(skipped) - 20))
            context.window_manager.popup_menu(
                _draw_skipped, title=T("op.export_skipped_title"), icon="INFO",
            )

        # ── 3.6 记住本次用的文件名/目录，供下次导出弹窗默认值使用 ─────────────────
        # 与自动默认名一致 → 视为"跟随目标集合"，下次继续自动生成；
        # 不一致 → 视为用户自定义，下次沿用（除非用户在弹窗里手动重选 efx_export_target）。
        global _last_export_name, _last_export_dir
        _last_export_dir = os.path.dirname(self.filepath)
        used_base = os.path.splitext(os.path.basename(self.filepath))[0]
        _last_export_name = None if used_base == _default_export_basename(target_col) else used_base

        _skip_note = f", {len(skipped)} ref(s) skipped" if skipped else ""
        self.report(
            {"INFO"},
            f"EFX export complete: {self.filepath} ({len(data)} bytes, root object: {root.name}{_db_note}{_skip_note})",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# L1.4 即时复制/粘贴（内存剪贴板）
#   （旧「字段值预设」算子 EFX_OT_save/apply_attribute_preset 已移除：属性预设改为
#    attribute_ops 的整属性增删机制；字段复用保留为下方的即时复制/粘贴。）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级内存剪贴板：{"type_hash": str, "fields": {...同 preset JSON fields 结构...}}
# 不写磁盘，会话级生命周期（Blender 重启清空）。
_FIELD_CLIPBOARD = {}


class EFX_OT_copy_attribute_fields(bpy.types.Operator):
    """把当前 EFX_ATTRIBUTE 的可编辑字段值复制到内存剪贴板"""

    bl_idname      = "efx.copy_attribute_fields"
    bl_label       = "Copy Field Values"
    bl_description = "Copy all editable field values of the current EFX_ATTRIBUTE to the in-memory clipboard (for pasting into an attribute of the same type)"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            return obj.efx_block.is_editable
        except AttributeError:
            return False

    def execute(self, context):
        from .presets import _item_to_json_value
        global _FIELD_CLIPBOARD

        obj = context.active_object
        bp = obj.efx_block

        fields = {}
        for item in bp.field_items:
            if item.ori_name.startswith("__"):
                continue
            json_val = _item_to_json_value(item)
            if json_val is None:
                continue
            fields[item.ori_name] = {
                "data_type": item.data_type,
                "value": json_val,
            }

        _FIELD_CLIPBOARD = {
            "type_hash": bp.type_hash_str,
            "fields": fields,
        }

        self.report({"INFO"}, f"EFX fields copied ({len(fields)} field(s), type hash={bp.type_hash_str})")
        return {"FINISHED"}


class EFX_OT_paste_attribute_fields(bpy.types.Operator):
    """把内存剪贴板的字段值粘贴到所有选中的同类型 EFX_ATTRIBUTE"""

    bl_idname      = "efx.paste_attribute_fields"
    bl_label       = "Paste Field Values"
    bl_description = "Write the clipboard field values into every selected EFX_ATTRIBUTE of the same type as the copy source"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """剪贴板为空、或当前属性不可编辑、或类型不符时灰显。"""
        if not _FIELD_CLIPBOARD:
            return False
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            bp = obj.efx_block
            if not bp.is_editable:
                return False
            # 类型不匹配时灰显
            return _FIELD_CLIPBOARD.get("type_hash", "") == bp.type_hash_str
        except AttributeError:
            return False

    def execute(self, context):
        from .presets import _json_value_to_item
        from . import fields as _fields
        global _FIELD_CLIPBOARD

        clip_hash = _FIELD_CLIPBOARD.get("type_hash", "")
        fields_dict = _FIELD_CLIPBOARD.get("fields", {})

        # 收集选中的、类型匹配且可编辑的 EFX_ATTRIBUTE；未多选（或选中里没有匹配类型）
        # 时退化为只粘贴到 active（execute 再守一次类型校验，同 poll 逻辑）。
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ATTRIBUTE"
            and hasattr(o, "efx_block")
            and o.efx_block.is_editable
            and o.efx_block.type_hash_str == clip_hash
        ]
        if not targets:
            active = context.active_object
            if active is None or active.get("~TYPE") != "EFX_ATTRIBUTE" \
                    or active.efx_block.type_hash_str != clip_hash:
                self.report(
                    {"ERROR"},
                    f"Paste failed: type mismatch (clipboard hash={clip_hash!r})",
                )
                return {"CANCELLED"}
            targets = [active]

        # 写入字段值（复用 presets.py 的 _json_value_to_item + _LOADING 守卫）
        total_written = 0
        old_loading = _fields._LOADING
        _fields._LOADING = True
        try:
            for obj in targets:
                bp = obj.efx_block
                item_by_name = {
                    item.ori_name: item for item in bp.field_items
                    if not item.ori_name.startswith("__")
                }
                written = 0
                for ori_name, field_entry in fields_dict.items():
                    item = item_by_name.get(ori_name)
                    if item is None or item.read_only:
                        continue
                    data_type = field_entry.get("data_type", "")
                    if data_type != item.data_type:
                        continue
                    value = field_entry.get("value")
                    if value is None:
                        continue
                    if _json_value_to_item(item, data_type, value):
                        item.edited = True
                        written += 1
                if written > 0:
                    bp.efx_dirty = True
                total_written += written
        finally:
            _fields._LOADING = old_loading

        self.report(
            {"INFO"},
            f"EFX fields pasted into {len(targets)} attribute(s): {total_written} field write(s) total",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# #2 字段说明 tooltip 算子
# ─────────────────────────────────────────────────────────────────────────────

def _is_ptbehavior_attribute(obj) -> bool:
    """obj 是否为可编辑的 PTBEHAVIOR EFX_ATTRIBUTE。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        from ..efx_format.hashes import PTBEHAVIOR
        bp = obj.efx_block
        return bp.is_editable and int(bp.type_hash_str) == PTBEHAVIOR
    except (AttributeError, ValueError, ImportError):
        return False


# 动态 EnumProperty items 引用保活（防 GC：见 memory enum-callback-gc-trap）。
# identifier/name 全 ASCII（key 为十进制串、label 为已知英文名或 0x%08X），规避中文乱码。
_PTB_ADD_ENUM_CACHE = []


def _ptb_add_enum_items(self, context):
    """添加覆盖下拉的 items 回调：列出当前属性 b_type 尚未覆盖的属性。"""
    global _PTB_ADD_ENUM_CACHE
    obj = context.active_object
    items = []
    if _is_ptbehavior_attribute(obj):
        from . import fields as _fields
        for key, t, label in _fields.ptbehavior_addable_items(obj.efx_block):
            ident = str(key)
            desc = "type=0x{:02X}".format(t)
            items.append((ident, label, desc))
    if not items:
        items = [("__none__", "(no addable property)", "")]
    _PTB_ADD_ENUM_CACHE = items  # 保活
    return _PTB_ADD_ENUM_CACHE


class EFX_OT_ptb_add_override(bpy.types.Operator):
    """向 PTBEHAVIOR 添加一条覆盖属性（按规范顺序插入）"""

    bl_idname      = "efx.ptb_add_override"
    bl_label       = "Add Override"
    bl_description = "Add an override property to this PTBEHAVIOR attribute (inserted in canonical order)"
    bl_options     = {"REGISTER", "UNDO"}

    key_choice: EnumProperty(
        name="Property",
        description="Property to add (from this behavior type's catalog)",
        items=_ptb_add_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_ptbehavior_attribute(context.active_object)

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_ptbehavior, pack_ptbehavior
        from ..efx_format.ptbehavior_edit import add_override

        if self.key_choice == "__none__":
            self.report({"WARNING"}, "No property selected")
            return {"CANCELLED"}

        bp = context.active_object.efx_block
        try:
            key = int(self.key_choice)
        except ValueError:
            self.report({"ERROR"}, "Invalid property key")
            return {"CANCELLED"}

        cur = _fields.ptbehavior_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_ptbehavior(cur)
        if not add_override(d, key):
            self.report({"WARNING"}, "Property already present or not in catalog")
            return {"CANCELLED"}
        new_bytes = pack_ptbehavior(d)
        if not _fields.reinit_ptbehavior_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after add")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, "Override added (0x{:08X})".format(key))
        return {"FINISHED"}


class EFX_OT_ptb_remove_override(bpy.types.Operator):
    """从 PTBEHAVIOR 移除指定下标的覆盖属性"""

    bl_idname      = "efx.ptb_remove_override"
    bl_label       = "Remove Override"
    bl_description = "Remove this override property from the PTBEHAVIOR attribute"
    bl_options     = {"REGISTER", "UNDO"}

    param_index: IntProperty(name="Param Index", default=-1)

    @classmethod
    def poll(cls, context):
        return _is_ptbehavior_attribute(context.active_object)

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_ptbehavior, pack_ptbehavior
        from ..efx_format.ptbehavior_edit import remove_override

        bp = context.active_object.efx_block
        cur = _fields.ptbehavior_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_ptbehavior(cur)
        params = d["params"]
        if not (0 <= self.param_index < len(params)):
            self.report({"ERROR"}, "Param index out of range")
            return {"CANCELLED"}
        key = params[self.param_index]["unkn"] & 0xFFFFFFFF
        if not remove_override(d, key):
            self.report({"WARNING"}, "Property not found")
            return {"CANCELLED"}
        new_bytes = pack_ptbehavior(d)
        if not _fields.reinit_ptbehavior_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after remove")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, "Override removed (0x{:08X})".format(key))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# MATERIAL 材质槽增删（Phase C，核心逻辑 fields.material_current_bytes /
# reinit_material_from_bytes + efx_format/material_edit.py，对称于 PTBEHAVIOR
# 覆盖项增删）
# ─────────────────────────────────────────────────────────────────────────────

def _is_material_attribute(obj) -> bool:
    """obj 是否为可编辑的 MATERIAL EFX_ATTRIBUTE。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        from ..efx_format.hashes import MATERIAL
        bp = obj.efx_block
        return bp.is_editable and int(bp.type_hash_str) == MATERIAL
    except (AttributeError, ValueError, ImportError):
        return False


# 动态 EnumProperty items 引用保活（防 GC：见 memory enum-callback-gc-trap）。
_MATERIAL_SHADER_ENUM_CACHE = []


def _material_shader_enum_items(self, context):
    """材质类型下拉：112 种已知类型（identifier=十进制 hash 串，规避中文乱码；
    Blender 长列表原生自带搜索过滤框，不需要额外实现）。

    若 Scene.efx_material_filter_enabled=True（用户导入过 .mrl3 独立过滤器，
    见 EFX_OT_material_import_mrl3_filter），列表收窄到该 mrl3 实际用到的类型；
    收窄后为空（mrl3 只用了未知类型）则安全退回全样，不留用户对着空下拉卡住。
    """
    global _MATERIAL_SHADER_ENUM_CACHE
    from ..efx_format import material_meta as _mm

    entries = sorted(_mm.MATERIAL_TYPE_NAMES.items(), key=lambda kv: kv[1])

    scene = getattr(context, "scene", None)
    if scene is not None and getattr(scene, "efx_material_filter_enabled", False):
        raw = getattr(scene, "efx_material_filter_hashes", "")
        try:
            allowed = {int(x) for x in raw.split(",") if x}
        except ValueError:
            allowed = set()
        if allowed:
            filtered = [(h, name) for h, name in entries if h in allowed]
            if filtered:
                entries = filtered

    items = [(str(h), name, "0x{:08X}".format(h)) for h, name in entries]
    _MATERIAL_SHADER_ENUM_CACHE = items  # 保活
    return _MATERIAL_SHADER_ENUM_CACHE


class EFX_OT_material_add_block(bpy.types.Operator):
    """向 MATERIAL 属性添加一个材质槽（按所选材质类型的已知贴图槽 schema 铺满，初始为空）"""

    bl_idname      = "efx.material_add_block"
    bl_label       = "Add Material Slot"
    bl_description = "Add a material slot (Tex_Block) to this MATERIAL attribute, pre-filled with the chosen shader type's known texture slots (empty)"
    bl_options     = {"REGISTER", "UNDO"}

    shader_choice: EnumProperty(
        name="Material Type",
        description="Shader type for the new material slot",
        items=_material_shader_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_material_attribute(context.active_object)

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format import material_edit as _me

        try:
            shader_hash = int(self.shader_choice)
        except ValueError:
            self.report({"ERROR"}, "Invalid material type")
            return {"CANCELLED"}

        bp = context.active_object.efx_block
        cur = _fields.material_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_material(cur)
        _me.add_block(d, shader_hash)
        new_bytes = pack_material(d)
        if not _fields.reinit_material_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after add")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, "Material slot added")
        return {"FINISHED"}


class EFX_OT_material_set_shader(bpy.types.Operator):
    """修改指定材质槽的材质类型，贴图槽位联动换成新类型的 schema（重合槽位路径保留）"""

    bl_idname      = "efx.material_set_shader"
    bl_label       = "Set Material Type"
    bl_description = (
        "Change this material slot's shader type. Its texture slots switch to the new "
        "type's known schema (paths for slots present in both types are kept; others are dropped)"
    )
    bl_options     = {"REGISTER", "UNDO"}

    block_index: IntProperty(name="Block Index", default=-1, options={'HIDDEN'})
    shader_choice: EnumProperty(
        name="Material Type",
        description="New shader type for this material slot",
        items=_material_shader_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_material_attribute(context.active_object)

    def invoke(self, context, event):
        # block_index 由调用方（面板按钮）在弹窗前预设好，invoke_props_dialog
        # 只弹 shader_choice 的选择框（原生长列表自带搜索）。
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "shader_choice")

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format import material_edit as _me

        try:
            shader_hash = int(self.shader_choice)
        except ValueError:
            self.report({"ERROR"}, "Invalid material type")
            return {"CANCELLED"}

        bp = context.active_object.efx_block
        cur = _fields.material_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_material(cur)
        if not (0 <= self.block_index < len(d["blocks"])):
            self.report({"ERROR"}, "Block index out of range")
            return {"CANCELLED"}
        _me.set_block_shader(d["blocks"][self.block_index], shader_hash)
        new_bytes = pack_material(d)
        if not _fields.reinit_material_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after changing material type")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, "Material type changed")
        return {"FINISHED"}


class EFX_OT_material_remove_block(bpy.types.Operator):
    """从 MATERIAL 属性移除指定下标的材质槽"""

    bl_idname      = "efx.material_remove_block"
    bl_label       = "Remove Material Slot"
    bl_description = "Remove this material slot (Tex_Block) from the MATERIAL attribute"
    bl_options     = {"REGISTER", "UNDO"}

    block_index: IntProperty(name="Block Index", default=-1)

    @classmethod
    def poll(cls, context):
        return _is_material_attribute(context.active_object)

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format import material_edit as _me

        bp = context.active_object.efx_block
        cur = _fields.material_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_material(cur)
        if not _me.remove_block(d, self.block_index):
            self.report({"ERROR"}, "Block index out of range")
            return {"CANCELLED"}
        new_bytes = pack_material(d)
        if not _fields.reinit_material_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after remove")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, "Material slot removed")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# MATERIAL 独立 mrl3 过滤器（2026-07，与用户确认：mrl3 只当独立过滤器用，
# 跟 mod3/mesh 完全解耦——不联动 efx_mesh_target，不需要 Model Editor 插件。
# 核心解析见 efx_format/mrl3_reader.py）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_material_import_mrl3_filter(bpy.types.Operator, ImportHelper):
    """选一个 .mrl3 文件，把材质类型下拉收窄到这个文件实际用到的类型"""

    bl_idname      = "efx.material_import_mrl3_filter"
    bl_label       = "Filter by .mrl3"
    bl_description = "Pick a .mrl3 file; narrow the material type dropdown to only the types it actually uses"
    bl_options     = {"REGISTER"}

    filename_ext = ".mrl3"
    filter_glob: StringProperty(default="*.mrl3", options={'HIDDEN'})

    def execute(self, context):
        from ..efx_format.mrl3_reader import read_material_type_hashes, Mrl3ParseError

        try:
            with open(self.filepath, "rb") as f:
                data = f.read()
            hashes = read_material_type_hashes(data)
        except (Mrl3ParseError, OSError) as e:
            self.report({"ERROR"}, f"Failed to parse .mrl3: {e}")
            return {"CANCELLED"}

        if not hashes:
            self.report({"WARNING"}, "No known material types found in this .mrl3")
            return {"CANCELLED"}

        context.scene.efx_material_filter_hashes = ",".join(str(h) for h in sorted(hashes))
        context.scene.efx_material_filter_enabled = True
        context.scene.efx_material_filter_source = os.path.basename(self.filepath)
        self.report(
            {"INFO"},
            f"Material type dropdown filtered to {len(hashes)} type(s) from {os.path.basename(self.filepath)}",
        )
        return {"FINISHED"}


class EFX_OT_material_clear_mrl3_filter(bpy.types.Operator):
    """取消 mrl3 过滤，材质类型下拉恢复全部 112 种"""

    bl_idname      = "efx.material_clear_mrl3_filter"
    bl_label       = "Clear mrl3 Filter"
    bl_description = "Clear the .mrl3 filter; the material type dropdown shows all known types again"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, "efx_material_filter_enabled", False)

    def execute(self, context):
        context.scene.efx_material_filter_enabled = False
        return {"FINISHED"}


class EFX_OT_field_help(bpy.types.Operator):
    """
    纯提示算子：执行无副作用，description 动态返回字段注释。
    在 EFX_ATTRIBUTE 字段面板中，有注释的字段旁会显示 ⓘ 图标；
    悬停该图标即可在 tooltip 中读取 BT 注释说明。
    """

    bl_idname      = "efx.field_help"
    bl_label       = "Field Description"
    bl_options     = {"REGISTER"}

    type_name: bpy.props.StringProperty(
        name="Type Name",
        description="Attribute type name corresponding to HASH_TO_NAME (uppercase, e.g. EMITTERSHAPE3D)",
        default="",
        options={"SKIP_SAVE"},
    )

    field_name: bpy.props.StringProperty(
        name="Field Name",
        description="schema ori_name (original field name)",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def description(cls, context, properties):
        """动态 description 回调：按 (type_name, field_name) 查注释并返回。"""
        from .annotations import get_annotation
        ann = get_annotation(properties.type_name, properties.field_name)
        return ann if ann else ""

    def execute(self, context):
        # 纯提示算子，不做任何修改
        return {"CANCELLED"}


class EFX_OT_randomize_seed(bpy.types.Operator):
    """给 RANDOMFIX 的指定 randomSeedTable{N} 字段填入一个新的随机 int32 值"""

    bl_idname  = "efx.randomize_seed"
    bl_label   = "Randomize Seed"
    bl_options = {"REGISTER", "UNDO"}

    field: bpy.props.StringProperty(name="Field", default="randomSeedTable0")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            from ..efx_format.hashes import RANDOMFIX
            if int(str(obj.get("type_hash", ""))) != RANDOMFIX:
                return False
        except (AttributeError, ValueError, ImportError):
            return False
        return True

    def execute(self, context):
        import random
        obj = context.active_object
        for item in obj.efx_block.field_items:
            if item.ori_name == self.field:
                item.int_value = random.randint(-2147483648, 2147483647)
                self.report({"INFO"}, f"{self.field} = {item.int_value}")
                return {"FINISHED"}
        self.report({"ERROR"}, f"Field '{self.field}' not found")
        return {"CANCELLED"}


class EFX_OT_randomfix_set_table_group(bpy.types.Operator):
    """以勾选框编辑 RANDOMFIX 的 tableSelectionGroup（8-bit 掩码，bit i = randomSeedTable{i} 属于该组）"""

    bl_idname      = "efx.randomfix_set_table_group"
    bl_label       = "Edit Table Selection Group"
    bl_description = "Edit tableSelectionGroup via checkboxes (bit i = randomSeedTable{i} belongs to this group)"
    bl_options     = {"REGISTER", "UNDO", "INTERNAL"}

    t0: bpy.props.BoolProperty(name="Table 0")
    t1: bpy.props.BoolProperty(name="Table 1")
    t2: bpy.props.BoolProperty(name="Table 2")
    t3: bpy.props.BoolProperty(name="Table 3")
    t4: bpy.props.BoolProperty(name="Table 4")
    t5: bpy.props.BoolProperty(name="Table 5")
    t6: bpy.props.BoolProperty(name="Table 6")
    t7: bpy.props.BoolProperty(name="Table 7")

    _BITS = ("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            from ..efx_format.hashes import RANDOMFIX
            return int(str(obj.get("type_hash", ""))) == RANDOMFIX
        except (AttributeError, ValueError, ImportError):
            return False

    def invoke(self, context, event):
        bp = context.active_object.efx_block
        val = 0
        for item in bp.field_items:
            if item.ori_name == "tableSelectionGroup":
                val = int(item.int_value)
                break
        for i, attr in enumerate(self._BITS):
            setattr(self, attr, bool(val & (1 << i)))
        return context.window_manager.invoke_props_dialog(self, width=200)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Table Selection Group")
        for attr in self._BITS:
            layout.prop(self, attr)

    def execute(self, context):
        bp = context.active_object.efx_block
        mask = 0
        for i, attr in enumerate(self._BITS):
            if getattr(self, attr):
                mask |= (1 << i)
        for item in bp.field_items:
            if item.ori_name == "tableSelectionGroup":
                item.int_value = mask
                self.report({"INFO"}, f"tableSelectionGroup = {mask} (0b{mask:08b})")
                return {"FINISHED"}
        self.report({"ERROR"}, "Field 'tableSelectionGroup' not found")
        return {"CANCELLED"}


# ─────────────────────────────────────────────────────────────────────────────
# L1.3 FileHandler：拖入 3D 视口导入 .efx
# ─────────────────────────────────────────────────────────────────────────────
#
# ⚠ 版本守卫：FileHandler 是 Blender 4.1+ API。3.6 等老版本 bpy.types.FileHandler
# 不存在，直接 `class X(bpy.types.FileHandler)` 会在模块加载期 AttributeError，
# 导致整个插件导入失败。故仅当存在时才定义 + 注册（老版本无拖入导入，菜单导入照常）。

_HAS_FILEHANDLER = hasattr(bpy.types, "FileHandler")
EFX_FH_import = None

if _HAS_FILEHANDLER:
    class EFX_FH_import(bpy.types.FileHandler):
        """
        .efx 文件拖入 3D 视口时触发的 FileHandler（Blender 4.1+）。

        把 .efx 拖到 3D 视口（VIEW_3D / WINDOW）即调用 efx.import_efx。
        bl_import_operator 必须是已注册算子的 bl_idname；poll_drop 决定可拖放区域。
        """

        bl_idname          = "EFX_FH_import"
        bl_label           = "Import EFX"
        bl_import_operator = "efx.import_efx"
        bl_file_extensions = ".efx"

        @classmethod
        def poll_drop(cls, context):
            """仅在 3D 视口（VIEW_3D）的 WINDOW 区域允许拖放。"""
            return (
                context.area is not None
                and context.area.type == "VIEW_3D"
                and context.region is not None
                and context.region.type == "WINDOW"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 从零新建 EFX 集合（无需导入文件）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_new_efx(bpy.types.Operator):
    """新建一个空白 EFX 集合（根对象 + 4 个空子集合），之后可直接添加 Action/Extern/Entry"""

    bl_idname  = "efx.new_efx"
    bl_label   = "New EFX"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(
        name="Name",
        description="EFX collection name (used as file stem)",
        default="new_efx",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import base64 as _b64

        stem = self.name.strip() or "new_efx"
        col_name = stem + ".efx"

        # ── 顶层文件集合（紫色，~TYPE=EFX_ROOT，本身即"文件"，不再建 Empty）────────
        scene_col = context.scene.collection
        root_col = _rc.new_root_collection(col_name, scene_col)

        # header：使用语料库最普遍值（从 78 精选样本统计）
        root_col["hdr_signature"]       = "45465800"      # "EFX\x00"
        root_col["hdr_version"]         = "711800"
        root_col["hdr_constant"]        = "402786304,0,1254190883,402786304,402786304"
        root_col["hdr_efxr"]            = "65667872"      # "efxr"
        root_col["hdr_is_3d"]           = "1"
        root_col["hdr_unkn1"]           = "4294967295"    # 0xFFFFFFFF
        root_col["hdr_count_body"]      = "0"
        root_col["hdr_label_size"]      = "1"
        root_col["hdr_count_play"]      = "0"
        root_col["hdr_count_extern"]    = "0"
        root_col["hdr_count_subselect"] = "0"
        root_col["hdr_subselect_size"]  = "0"
        root_col["hdr_count_eof"]       = "0"
        root_col["hdr_double_buffer"]   = "15000"

        # label_bytes：单 null 字节；labels_dirty=1 让导出端按实际内容重建
        root_col["label_bytes"]  = _b64.b64encode(b"\x00").decode("ascii")
        root_col["label_tail"]   = ""
        root_col["labels_dirty"] = 1
        root_col["eof_ints"]     = ""
        root_col["eof_tail"]     = ""
        # 空 eof 列表天然"干净"（见 entry_action_ref.eof_is_clean）→ per_entry 模型，
        # 使新增 entry 后可用 Direct Trigger 切换（efx.eof_toggle_entry）。
        root_col["eof_model"]    = "per_entry"

        # ── 4 个空叶子子集合（与导入时命名一致，~TYPE + efx_root_ptr 反向指针）───────
        _rc.new_leaf_collection(stem + "_2 Entry",     root_col, "EFX_ENTRY")
        _rc.new_leaf_collection(stem + "_0 Action",    root_col, "EFX_ACTION")
        _rc.new_leaf_collection(stem + "_1 Extern",    root_col, "EFX_EXTERN")
        _rc.new_leaf_collection(stem + "_3 Subselect", root_col, "EFX_SUBSELECT")

        # Entry 下预建两个对称子集合（Direct Trigger / Not Direct Trigger），跟导入
        # 一致：即使还没有任何 entry，也先把结构摆出来，避免用户第一次加 entry 时
        # 才第一次看到这套约定。
        _rc.ensure_direct_trigger_collection(root_col)
        _rc.ensure_not_direct_trigger_collection(root_col)

        # Active EFX 自动切换到新建集合
        context.scene.efx_active_efx = root_col

        self.report({"INFO"}, f"New EFX created: {col_name}")
        return {"FINISHED"}


_CLASSES = (
    EFX_OT_import,
    EFX_OT_export,
    EFX_OT_new_efx,
    # 旧字段值预设算子（save/apply_attribute_preset、open_preset_folder）已删：
    # 属性预设改为 attribute_ops 整属性机制；字段复用保留为即时复制/粘贴。
    EFX_OT_copy_attribute_fields,
    EFX_OT_paste_attribute_fields,
    EFX_OT_ptb_add_override,
    EFX_OT_ptb_remove_override,
    EFX_OT_material_add_block,
    EFX_OT_material_set_shader,
    EFX_OT_material_remove_block,
    EFX_OT_material_import_mrl3_filter,
    EFX_OT_material_clear_mrl3_filter,
    EFX_OT_field_help,
    EFX_OT_randomize_seed,
    EFX_OT_randomfix_set_table_group,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # FileHandler 仅在 4.1+ 注册（老版本无此 API，跳过拖入导入）
    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        bpy.utils.register_class(EFX_FH_import)

    # 导出弹窗的目标 EFX 集合选择器：算子属性不支持 PointerProperty 指向 datablock
    # 类型（Collection），故挂在 WindowManager 上（同 add_ops.py::efx_active_efx 的做法），
    # 换来原生的 ID 搜索控件（图标+名字+清空按钮），而不是普通下拉框。
    bpy.types.WindowManager.efx_export_target = PointerProperty(
        name=T("export.target_efx"),
        description=T("export.target_efx_tip"),
        type=bpy.types.Collection,
        poll=_export_target_poll,
        options={"SKIP_SAVE"},
    )

    # MATERIAL 独立 mrl3 过滤器状态（会话级，非 EFX 数据的一部分，挂 Scene）
    bpy.types.Scene.efx_material_filter_enabled = BoolProperty(
        name="mrl3 Filter Enabled",
        description="Narrow the material type dropdown to types used by an imported .mrl3",
        default=False,
    )
    bpy.types.Scene.efx_material_filter_hashes = StringProperty(
        name="mrl3 Filter Hashes",
        description="Comma-separated material type hashes from the last imported .mrl3",
        default="",
    )
    bpy.types.Scene.efx_material_filter_source = StringProperty(
        name="mrl3 Filter Source",
        description="Filename of the .mrl3 the current filter was loaded from",
        default="",
    )


def unregister():
    if hasattr(bpy.types.Scene, "efx_material_filter_source"):
        del bpy.types.Scene.efx_material_filter_source
    if hasattr(bpy.types.Scene, "efx_material_filter_hashes"):
        del bpy.types.Scene.efx_material_filter_hashes
    if hasattr(bpy.types.Scene, "efx_material_filter_enabled"):
        del bpy.types.Scene.efx_material_filter_enabled

    if hasattr(bpy.types.WindowManager, "efx_export_target"):
        del bpy.types.WindowManager.efx_export_target

    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        try:
            bpy.utils.unregister_class(EFX_FH_import)
        except RuntimeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
