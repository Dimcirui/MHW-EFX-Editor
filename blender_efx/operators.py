"""EFX 导入、导出与辅助算子。

维护约束：
- FileHandler 和文件浏览器都必须复用同一导入执行路径。
- 可选 mod3/UVS 联动失败不得影响 EFX 导入，未解析项目须汇总报告。
- 导出目标按显式活动 EFX、活动对象所属根的顺序解析；没有明确目标时交由用户选择。
- 导出选项只控制导出前修正，原始字段和未知结构仍由 io_tree/fields 的回退路径处理。
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


def _find_efx_root(context):
    """按活动对象、当前集合的顺序解析 EFX 根。"""
    obj = context.active_object
    if obj is not None:
        root = _rc.find_root_collection(obj)
        if root is not None:
            return root

    col = getattr(context, "collection", None)
    if _rc.is_root_collection(col):
        return col

    return None


class EFX_OT_import(bpy.types.Operator, ImportHelper):
    """导入 MHW .efx 特效文件，在场景中建立对象树"""

    bl_idname      = "efx.import_efx"
    bl_label       = "Import EFX"
    bl_description = "Import an MHW EFX effect file (.efx)"
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".efx"
    filter_glob: StringProperty(
        default="*.efx",
        options={"HIDDEN"},
        maxlen=255,
    )

    # 拖入使用 directory/files，文件浏览器使用 filepath。
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(
        subtype="DIR_PATH",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    import_meshes: BoolProperty(
        name="Import referenced meshes (mod3)",
        description="同时把每个 MESH 属性引用的 mod3（含 mrl3 与材质）经 MHW Model Editor 导入并绑定到预览。"
                    "需安装 Model Editor。提取根目录默认从 efx 位置向上自动找 nativePC，找不到时再用下方 Chunk Root",
        default=False,
        options={"SKIP_SAVE"},
    )

    import_uvs: BoolProperty(
        name="Import referenced .uvs (+ sprite sheets)",
        description="顺着每个 UVSEQUENCE 属性填的路径载入 .uvs；并按该属性的 sequenceNo 取对应 group 的"
                    "贴图路径，把序列帧大图（.tex）转出来绑成参考图。提取根同 mod3：默认自动找 nativePC",
        default=False,
        options={"SKIP_SAVE"},
    )

    # 颜色模式隐藏非颜色内容，但保留完整对象树用于导出。
    import_only_colors: BoolProperty(
        name="Import Only Colors",
        description="只暴露含颜色/亮度字段的 entry 与 attribute，其余内容（结构编辑/TIML/"
                    "预设等）在此文件里隐藏——供只想改色、不想碰其他任何东西的场景使用。"
                    "导出仍是完整合法的 .efx",
        default=False,
        options={"SKIP_SAVE"},
    )

    def invoke(self, context, event):
        if self.directory and self.files:
            return context.window_manager.invoke_props_dialog(self)
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "import_only_colors")
        if self.import_only_colors:
            return
        from . import mod3_link, uvs_link
        if mod3_link.model_editor_available():
            layout.prop(self, "import_meshes")
        else:
            layout.label(text="装 MHW Model Editor 后可勾选「一并导入 mod3」", icon="INFO")
        layout.prop(self, "import_uvs", text=T("uvslink.import_opt"))
        if self.import_uvs and not uvs_link.tex_loader_available():
            layout.label(text=T("uvslink.need_editor"), icon="INFO")
        if self.import_meshes or self.import_uvs:
            box = layout.box()
            box.label(text="提取根：默认自动找 nativePC；找不到才用下方", icon="FILE_FOLDER")
            box.prop(context.scene, "efx_chunk_root", text="Chunk Root")

    def execute(self, context):
        import os

        paths = []
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(self.directory, f.name))

        if not paths:
            if self.filepath:
                paths = [self.filepath]

        if not paths:
            self.report({"ERROR"}, "EFX import: no file path specified")
            return {"CANCELLED"}

        imported = []
        imported_roots = []
        imported_paths = []
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
                traceback.print_exc()
                errors.append(f"{os.path.basename(filepath)}: {exc}")
                self.report(
                    {"ERROR"},
                    f"Failed to import '{os.path.basename(filepath)}'. The file may be "
                    "corrupted or use an unsupported format; see the system console for details.",
                )

        if imported_roots:
            try:
                from . import transform_sync
                armature = getattr(context.scene, "efx_armature", None)
                use_anchor = getattr(context.scene, "efx_anchor_placement", True)
                for root_obj in imported_roots:
                    transform_sync.sync_all_transform3d(root_obj, armature, use_anchor=use_anchor)
            except Exception:
                pass

        # 可选资源联动不得阻断 EFX 导入。
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

        if imported_roots and self.import_uvs and not self.import_only_colors:
            from . import uvs_link
            chunk_root = getattr(context.scene, "efx_chunk_root", "") or ""
            tot_uvs = tot_tex = 0
            all_problems = []
            for root_obj, fpath in zip(imported_roots, imported_paths):
                try:
                    n_uvs, n_tex, problems = uvs_link.link_root(
                        root_obj, chunk_root, os.path.dirname(fpath), True)
                    tot_uvs += n_uvs
                    tot_tex += n_tex
                    all_problems.extend(problems)
                except Exception:
                    pass
            uvs_link.report_problems(self, all_problems, tot_uvs, tot_tex)

        if imported:
            names = ", ".join(imported)
            self.report({"INFO"}, f"EFX import complete: {names}")

        if imported:
            return {"FINISHED"}
        return {"CANCELLED"}


# 导出名称、目录和目标选择的会话状态。
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
    """从集合名生成无 Blender 重名后缀和扩展名的默认文件名。"""
    if collection is None:
        return "untitled"
    name = re.sub(r'\.\d{3}$', '', collection.name)
    if name.lower().endswith(".efx"):
        name = name[:-4]
    return name or "untitled"


def _resolve_default_export_collection(context):
    """按活动 EFX、活动对象所属根的顺序选择导出目标。"""
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

    filename_ext = ".efx"
    filter_glob: StringProperty(
        default="*.efx",
        options={"HIDDEN"},
        maxlen=255,
    )

    # 自动值不得小于已有值或 16 对齐的两倍文件大小。
    recompute_double_buffer: BoolProperty(
        name=T("export.recompute_db"),
        description=T("export.recompute_db_tip"),
        default=True,
    )

    # 仅在内容维度单一时自动校正 is_3d。
    auto_fix_is_3d: BoolProperty(
        name=T("export.auto_fix_is3d"),
        description=T("export.auto_fix_is3d_tip"),
        default=True,
    )

    auto_sort_attributes: BoolProperty(
        name=T("export.auto_sort"),
        description=T("export.auto_sort_tip"),
        default=True,
    )

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

        # 目标变化时重置为对应的默认文件名。
        cur = wm.efx_export_target
        if cur is not _last_export_target_seen:
            _last_export_target_seen = cur
            _last_export_name = None
            base = _default_export_basename(cur)
            directory = os.path.dirname(self.filepath) if self.filepath else (_last_export_dir or "")
            self.filepath = os.path.join(directory, base + self.filename_ext) if directory else base + self.filename_ext

        layout.prop(self, "recompute_double_buffer")
        if not self.recompute_double_buffer and cur is not None and "hdr_double_buffer" in cur:
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
        from .add_ops import get_active_efx_root
        target_col = context.window_manager.efx_export_target
        root = _efx_root_in_collection(target_col) or get_active_efx_root(context) or _find_efx_root(context)
        if root is None:
            self.report(
                {"ERROR"},
                "No EFX specified for export: select an Active EFX collection in the N-panel EFX area, or select any object in the EFX object tree",
            )
            return {"CANCELLED"}

        # 仅 ERROR 级校验阻断导出；其他问题在成功后汇总报告。
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

        skipped = [p for p in problems
                   if p.get("category") in ("dangling", "eof_raw")]

        # 先规范索引与标签，再按类型排序属性。
        try:
            from . import normalize
            if normalize.normalize_root(root):
                root["labels_dirty"] = 1  # 满命名/重编号可能改标签表 → 导出重建
        except Exception:
            pass  # 规范化失败不阻断导出

        # 混用 2D/3D 时没有安全的自动值，保留原设置。
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
                pass

        if self.auto_sort_attributes:
            try:
                from .reorder import auto_sort_entry_attributes
                auto_sort_entry_attributes(root)
            except Exception:
                pass

        try:
            data = io_tree.export_efx_tree(root, recalc_timl_length=self.recalc_timl_length)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report(
                {"ERROR"},
                "Failed to export this EFX. See the system console for details.",
            )
            return {"CANCELLED"}

        # root 属性删除信息仅能在导出后取得。
        _root_attr_dropped = str(root.get("root_attr_dropped", ""))
        if _root_attr_dropped:
            skipped.append({
                "category": "root_attr_dropped",
                "msg": f"Attribute(s) dropped (wrong entry type for their kind): {_root_attr_dropped}",
            })

        _db_note = ""
        if self.recompute_double_buffer:
            import math
            old_db = struct.unpack_from("<I", data, 68)[0]
            new_db = max(old_db, (math.ceil(2.0 * len(data)) + 15) // 16 * 16)
            if new_db != old_db:
                data = data[:68] + struct.pack("<I", new_db) + data[72:]
                # 保持 UI 与写出字节一致。
                root["hdr_double_buffer"] = str(new_db)
            _db_note = f", filesize_double {old_db}→{new_db}"

        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"Failed to write '{self.filepath}'. Check disk space and "
                                    "whether the file is open in another program.")
            return {"CANCELLED"}

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

        # 仅记忆不同于自动默认名的用户自定义文件名。
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


# 模块级字段剪贴板，不写磁盘。
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
        """仅在剪贴板非空且活动属性类型匹配时启用。"""
        if not _FIELD_CLIPBOARD:
            return False
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            bp = obj.efx_block
            if not bp.is_editable:
                return False
            return _FIELD_CLIPBOARD.get("type_hash", "") == bp.type_hash_str
        except AttributeError:
            return False

    def execute(self, context):
        from .presets import _json_value_to_item
        from . import fields as _fields
        global _FIELD_CLIPBOARD

        clip_hash = _FIELD_CLIPBOARD.get("type_hash", "")
        fields_dict = _FIELD_CLIPBOARD.get("fields", {})

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

        # 加载守卫避免逐字段写入重复触发更新回调。
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


# 动态 EnumProperty 项必须由 Python 持有，避免 Blender 引用失效。
_PTB_ADD_ENUM_CACHE = []


def _ptb_add_enum_items(self, context):
    """添加覆盖下拉的 items 回调：列出当前属性 b_type 尚未覆盖的属性。"""
    global _PTB_ADD_ENUM_CACHE
    obj = context.active_object
    items = []
    if _is_ptbehavior_attribute(obj):
        from . import fields as _fields
        for key, t, label, dti_only in _fields.ptbehavior_addable_items(obj.efx_block):
            ident = str(key)
            desc = "type=0x{:02X}".format(t)
            if dti_only:
                desc += "  ·  not used in any official file"
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
        from ..efx_format.ptbehavior.edit import add_override

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


class EFX_OT_ptb_add_override_search(bpy.types.Operator):
    """通过原生搜索弹窗选择并新增 PTBEHAVIOR 覆盖属性。"""

    bl_idname      = "efx.ptb_add_override_search"
    bl_label       = "Search Property"
    bl_description = "Fuzzy-search this behavior type's properties by name and add on pick"
    bl_options     = {"REGISTER", "UNDO"}
    bl_property    = "key_choice"

    key_choice: EnumProperty(
        name="Property",
        description="Property to add (from this behavior type's catalog)",
        items=_ptb_add_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_ptbehavior_attribute(context.active_object)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        return bpy.ops.efx.ptb_add_override(key_choice=self.key_choice)


# b_type 枚举项保活。
_PTB_BTYPE_ENUM_CACHE = []


def _ptb_btype_enum_items(self, context):
    """列出已知行为类，并保留当前未知值。"""
    global _PTB_BTYPE_ENUM_CACHE
    from ..efx_format.ptbehavior.edit import known_btypes, catalog_for_btype

    cur = ""
    obj = context.active_object
    if _is_ptbehavior_attribute(obj):
        for it in obj.efx_block.field_items:
            if it.ori_name == "b_type":
                cur = it.string_value
                break
    names = list(known_btypes())
    if cur and cur not in names:
        names.append(cur)
    items = []
    for n in names:
        n_fields = len(catalog_for_btype(n))
        items.append((n, n.rsplit("::", 1)[-1], "%s  (%d properties)" % (n, n_fields)))
    if not items:
        items = [("__none__", "(no behavior type)", "")]
    _PTB_BTYPE_ENUM_CACHE = items
    return _PTB_BTYPE_ENUM_CACHE


class EFX_OT_ptb_set_btype(bpy.types.Operator):
    """切换行为类；不在新类目录中的覆盖项会被删除并报告。"""

    bl_idname      = "efx.ptb_set_btype"
    bl_label       = "Behavior Type"
    bl_description = "Change this PTBEHAVIOR's behavior class (properties missing from the new class are dropped)"
    bl_options     = {"REGISTER", "UNDO"}

    b_type_choice: EnumProperty(
        name="Behavior Type",
        description="Behavior class for this attribute",
        items=_ptb_btype_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_ptbehavior_attribute(context.active_object)

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_ptbehavior, pack_ptbehavior
        from ..efx_format.ptbehavior.edit import catalog_for_btype

        new_bt = self.b_type_choice
        if not new_bt or new_bt == "__none__":
            return {"CANCELLED"}
        bp = context.active_object.efx_block
        d, _ = unpack_ptbehavior(_fields.ptbehavior_current_bytes(bp))
        old_bt = d["b_type"].decode("latin-1").rstrip("\x00")
        if new_bt == old_bt:
            return {"CANCELLED"}

        order = {k & 0xFFFFFFFF: i for i, (k, _t, _f) in enumerate(catalog_for_btype(new_bt))}
        kept, dropped = [], 0
        for prm in d["params"]:
            if (prm["unkn"] & 0xFFFFFFFF) in order:
                kept.append(prm)
            else:
                dropped += 1
        kept.sort(key=lambda prm: order[prm["unkn"] & 0xFFFFFFFF])
        d["params"] = kept
        d["b_type"] = (new_bt + "\x00").encode("utf-8")

        if not _fields.reinit_ptbehavior_from_bytes(bp, pack_ptbehavior(d)):
            self.report({"ERROR"}, "Re-init failed after behavior type change")
            return {"CANCELLED"}
        bp.efx_dirty = True
        if dropped:
            self.report({"WARNING"}, "Behavior type changed; %d propert%s dropped"
                        % (dropped, "y" if dropped == 1 else "ies"))
        else:
            self.report({"INFO"}, "Behavior type changed")
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
        from ..efx_format.ptbehavior.edit import remove_override

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


# 动态 EnumProperty 项保活。
_MATERIAL_SHADER_ENUM_CACHE = []


def _material_shader_enum_items(self, context):
    """返回可搜索的材质类型枚举项。"""
    global _MATERIAL_SHADER_ENUM_CACHE
    from ..efx_format.material import meta as _mm

    entries = sorted(_mm.MATERIAL_TYPE_NAMES.items(), key=lambda kv: kv[1])
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
        from ..efx_format.material import edit as _me

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


def _material_bound_mesh_objects(material_obj):
    """收集同一 Entry 内 MESH 属性绑定的网格对象。"""
    objs = []
    parent = getattr(material_obj, "parent", None)
    if parent is None:
        return objs
    try:
        from ..efx_format.hashes import MESH as _MESH_HASH
    except ImportError:
        return objs
    for sib in parent.children:
        if sib.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            if int(sib.efx_block.type_hash_str) != _MESH_HASH:
                continue
        except (AttributeError, ValueError):
            continue
        for item in getattr(sib, "efx_mesh_targets", []):
            if item.obj is not None and item.obj.type == "MESH":
                objs.append(item.obj)
    return objs


# 动态 EnumProperty 项保活。
_MATERIAL_NAME_ENUM_CACHE = []


def _material_name_enum_items(self, context):
    """从绑定网格收集去重后的材质名候选。"""
    global _MATERIAL_NAME_ENUM_CACHE
    names = []
    seen = set()
    for obj in _material_bound_mesh_objects(context.active_object):
        for slot in obj.material_slots:
            if slot.material and slot.material.name not in seen:
                seen.add(slot.material.name)
                names.append(slot.material.name)
    items = [(n, n, "") for n in sorted(names)]
    _MATERIAL_NAME_ENUM_CACHE = items
    return _MATERIAL_NAME_ENUM_CACHE


class EFX_OT_material_set_name(bpy.types.Operator):
    """把材质槽绑定到指定名字的 mrl3 材质槽（mat_name_hash = jamcrc(name)）"""

    bl_idname      = "efx.material_set_name"
    bl_label       = "Set Material Slot Name"
    bl_description = (
        "Bind this material slot to a named material in the mesh's .mrl3 "
        "(mat_name_hash = jamcrc(name)). Without a matching name, the game "
        "cannot find which mrl3 material to override and this slot has no effect"
    )
    bl_options     = {"REGISTER", "UNDO"}

    block_index: IntProperty(name="Block Index", default=-1, options={'HIDDEN'})
    material_name: StringProperty(
        name="Material Name",
        description="Name of the target material slot, exactly as it appears in the mesh's .mod3/.mrl3 (case-sensitive)",
    )
    name_choice: EnumProperty(
        name="Pick from Bound Mesh",
        description="Material slot names found on the mesh(es) bound to this entry's MESH attribute",
        items=_material_name_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _is_material_attribute(context.active_object)

    def invoke(self, context, event):
        self.material_name = ""
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        if _material_name_enum_items(self, context):
            col.prop(self, "name_choice")
            col.separator()
        col.prop(self, "material_name")

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format.material import edit as _me
        from . import material_name_cache as _mnc

        name = (self.material_name or "").strip()
        if not name:
            try:
                name = self.name_choice
            except Exception:
                name = ""
        if not name:
            self.report({"ERROR"}, "Material name is empty")
            return {"CANCELLED"}

        bp = context.active_object.efx_block
        cur = _fields.material_current_bytes(bp)   # 烘焙待编辑值
        d, _ = unpack_material(cur)
        if not (0 <= self.block_index < len(d["blocks"])):
            self.report({"ERROR"}, "Block index out of range")
            return {"CANCELLED"}
        _me.set_block_material_name(d["blocks"][self.block_index], name)
        _mnc.record(name)  # 顺手记进会话缓存，供别处同哈希复用
        new_bytes = pack_material(d)
        if not _fields.reinit_material_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after setting material name")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report({"INFO"}, f'Bound to material "{name}"')
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
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "shader_choice")

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format.material import edit as _me

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
        from ..efx_format.material import edit as _me

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


# 参考 .mrl3 新建材质槽；独立于网格联动和 Model Editor。

class EFX_OT_material_pick_mrl3_reference(bpy.types.Operator, ImportHelper):
    """选一个 .mrl3 文件作为参考，供"从 mrl3 添加材质槽"读取里面的具体材质"""

    bl_idname      = "efx.material_pick_mrl3_reference"
    bl_label       = "Reference .mrl3..."
    bl_description = "Pick a .mrl3 file to read its materials from (name, type, texture paths)"
    bl_options     = {"REGISTER"}

    filename_ext = ".mrl3"
    filter_glob: StringProperty(default="*.mrl3", options={'HIDDEN'})

    def execute(self, context):
        from ..efx_format.material.mrl3_reader import read_materials, Mrl3ParseError
        from ..efx_format.hashes import jamcrc
        from . import material_name_cache as _mnc

        try:
            with open(self.filepath, "rb") as f:
                data = f.read()
            materials = read_materials(data)
        except (Mrl3ParseError, OSError):
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to read this .mrl3 file. It may be corrupted or use "
                                    "an unsupported format; see the system console for details.")
            return {"CANCELLED"}

        if not materials:
            self.report({"WARNING"}, "No materials found in this .mrl3")
            return {"CANCELLED"}

        # 同名 mod3 可补充 mrl3 未携带的材质名。
        n_named = 0
        mod3_path = os.path.splitext(self.filepath)[0] + ".mod3"
        if os.path.isfile(mod3_path):
            from ..efx_format.material.mod3_names import read_material_names, Mod3ParseError
            try:
                with open(mod3_path, "rb") as f:
                    mod3_names = read_material_names(f.read())
            except (Mod3ParseError, OSError):
                mod3_names = []
            name_by_hash = {jamcrc(n) & 0xFFFFFFFF: n for n in mod3_names}
            for m in materials:
                name = name_by_hash.get(m['material_name_hash'] & 0xFFFFFFFF)
                if name:
                    _mnc.record(name)
                    n_named += 1

        context.scene.efx_material_ref_mrl3_path = self.filepath
        suffix = f", {n_named} with real names (from sibling .mod3)" if n_named else ""
        self.report(
            {"INFO"},
            f"Found {len(materials)} material(s) in {os.path.basename(self.filepath)}{suffix} — use \"Add from .mrl3\" to pick one",
        )
        return {"FINISHED"}


class EFX_OT_material_clear_mrl3_reference(bpy.types.Operator):
    """清除参考 .mrl3，"从 mrl3 添加材质槽"按钮恢复禁用"""

    bl_idname      = "efx.material_clear_mrl3_reference"
    bl_label       = "Clear .mrl3 Reference"
    bl_description = "Clear the referenced .mrl3 file"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, "efx_material_ref_mrl3_path", ""))

    def execute(self, context):
        context.scene.efx_material_ref_mrl3_path = ""
        return {"FINISHED"}


# 动态 EnumProperty 项保活。
_MATERIAL_REF_ENUM_CACHE = []


def _read_ref_materials(context):
    """读 Scene.efx_material_ref_mrl3_path 指向的 .mrl3；路径为空或解析失败返回 []。"""
    path = getattr(context.scene, "efx_material_ref_mrl3_path", "")
    if not path:
        return []
    from ..efx_format.material.mrl3_reader import read_materials, Mrl3ParseError
    try:
        with open(path, "rb") as f:
            data = f.read()
        return read_materials(data)
    except (Mrl3ParseError, OSError):
        return []


def _material_ref_enum_items(self, context):
    """为参考 mrl3 的每条材质生成选择项。"""
    global _MATERIAL_REF_ENUM_CACHE
    from ..efx_format.material import meta as _mm
    from . import material_name_cache as _mnc

    materials = _read_ref_materials(context)
    items = []
    for i, m in enumerate(materials):
        type_name = _mm.material_type_name(m['mmtr_hash'])
        type_label = type_name if type_name else f"Hash {m['mmtr_hash']}"
        real_name = _mnc.lookup(m['material_name_hash'])
        label = f"[{i}] {type_label} ({real_name})" if real_name else f"[{i}] {type_label}"
        n_tex = len(m['textures'])
        n_par = len(m['params'])
        tip = f"materialNameHash={m['material_name_hash']}, {n_tex} texture(s), {n_par} parameter(s)"
        items.append((str(i), label, tip))
    _MATERIAL_REF_ENUM_CACHE = items  # 保活
    return _MATERIAL_REF_ENUM_CACHE


class EFX_OT_material_add_from_mrl3(bpy.types.Operator):
    """按参考 .mrl3 里选中的具体材质新建材质槽：材质类型/材质名/贴图路径/着色器参数全部照抄"""

    bl_idname      = "efx.material_add_from_mrl3"
    bl_label       = "Add from .mrl3"
    bl_description = (
        "Add a material slot copied from a material in the referenced .mrl3 — shader type, "
        "material name binding, texture paths, and shader parameters are all filled in "
        "automatically from the real values stored in that .mrl3 file "
        "(only available for shader types with a known schema)"
    )
    bl_options     = {"REGISTER", "UNDO"}

    material_choice: EnumProperty(
        name="Material",
        description="Material entry from the referenced .mrl3",
        items=_material_ref_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return (_is_material_attribute(context.active_object)
                and bool(getattr(context.scene, "efx_material_ref_mrl3_path", "")))

    def execute(self, context):
        from . import fields as _fields
        from ..efx_format.structs import unpack_material, pack_material
        from ..efx_format.material import edit as _me
        from ..efx_format.material import meta as _mm
        from ..efx_format.material import params as _mp

        materials = _read_ref_materials(context)
        try:
            idx = int(self.material_choice)
            mat = materials[idx]
        except (ValueError, IndexError):
            self.report({"ERROR"}, "Invalid material choice (re-pick the .mrl3 reference?)")
            return {"CANCELLED"}

        bp = context.active_object.efx_block
        cur = _fields.material_current_bytes(bp)
        d, _ = unpack_material(cur)
        block = _me.add_block(d, mat['mmtr_hash'])
        block['mat_name_hash'] = _me._to_signed32(mat['material_name_hash'])

        n_filled = 0
        for s in block['sets']:
            if s['type'] != 0x80:
                continue
            slot_name = _mm.texture_slot_name(s['t'])
            path = mat['textures'].get(slot_name) if slot_name else None
            if path:
                _me.fill_slot_path(block, s['t'], path)
                n_filled += 1

        # 仅为参考文件提供的参数创建默认值。
        n_params = 0
        shader_hash = mat['mmtr_hash'] & 0xFFFFFFFF
        schema = _mp.MATERIAL_SHADER_PARAMS.get(shader_hash, {})
        for t_hash, (field_name, type_str) in schema.items():
            if field_name not in mat['params']:
                continue
            _me.add_param(block, t_hash, type_str, mat['params'][field_name])
            n_params += 1

        new_bytes = pack_material(d)
        if not _fields.reinit_material_from_bytes(bp, new_bytes):
            self.report({"ERROR"}, "Re-init failed after add")
            return {"CANCELLED"}
        bp.efx_dirty = True
        self.report(
            {"INFO"},
            f"Material slot added, {n_filled} texture path(s) and {n_params} parameter(s) pre-filled",
        )
        return {"FINISHED"}


class EFX_OT_field_help(bpy.types.Operator):
    """只读字段说明提示算子。"""

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


# FileHandler 仅在 Blender 提供该 API 时定义与注册。

_HAS_FILEHANDLER = hasattr(bpy.types, "FileHandler")
EFX_FH_import = None

if _HAS_FILEHANDLER:
    class EFX_FH_import(bpy.types.FileHandler):
        """将 3D 视口的 .efx 拖入转交给导入算子。"""

        bl_idname          = "EFX_FH_import"
        bl_label           = "Import EFX"
        bl_import_operator = "efx.import_efx"
        bl_file_extensions = ".efx"

        @classmethod
        def poll_drop(cls, context):
            """仅允许在 3D 视口内容区拖放。"""
            return (
                context.area is not None
                and context.area.type == "VIEW_3D"
                and context.region is not None
                and context.region.type == "WINDOW"
            )


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

        scene_col = context.scene.collection
        root_col = _rc.new_root_collection(col_name, scene_col)

        root_col["hdr_signature"]       = "45465800"
        root_col["hdr_version"]         = "711800"
        root_col["hdr_constant"]        = "402786304,0,1254190883,402786304,402786304"
        root_col["hdr_efxr"]            = "65667872"
        root_col["hdr_is_3d"]           = "1"
        root_col["hdr_unkn1"]           = "4294967295"
        root_col["hdr_count_body"]      = "0"
        root_col["hdr_label_size"]      = "1"
        root_col["hdr_count_play"]      = "0"
        root_col["hdr_count_extern"]    = "0"
        root_col["hdr_count_subselect"] = "0"
        root_col["hdr_subselect_size"]  = "0"
        root_col["hdr_count_eof"]       = "0"
        root_col["hdr_double_buffer"]   = "15000"

        # 新文件的标签表由导出端按实际内容重建。
        root_col["label_bytes"]  = _b64.b64encode(b"\x00").decode("ascii")
        root_col["label_tail"]   = ""
        root_col["labels_dirty"] = 1
        root_col["eof_ints"]     = ""
        root_col["eof_tail"]     = ""
        root_col["eof_model"]    = "per_entry"

        _rc.new_leaf_collection(stem + "_2 Entry",     root_col, "EFX_ENTRY")
        _rc.new_leaf_collection(stem + "_0 Action",    root_col, "EFX_ACTION")
        _rc.new_leaf_collection(stem + "_1 Extern",    root_col, "EFX_EXTERN")
        _rc.new_leaf_collection(stem + "_3 Subselect", root_col, "EFX_SUBSELECT")

        # 新 Entry 必须能归属到两个直接触发集合之一。
        _rc.ensure_direct_trigger_collection(root_col)
        _rc.ensure_not_direct_trigger_collection(root_col)

        context.scene.efx_active_efx = root_col

        self.report({"INFO"}, f"New EFX created: {col_name}")
        return {"FINISHED"}


_CLASSES = (
    EFX_OT_import,
    EFX_OT_export,
    EFX_OT_new_efx,
    EFX_OT_copy_attribute_fields,
    EFX_OT_paste_attribute_fields,
    EFX_OT_ptb_add_override,
    EFX_OT_ptb_add_override_search,
    EFX_OT_ptb_set_btype,
    EFX_OT_ptb_remove_override,
    EFX_OT_material_add_block,
    EFX_OT_material_set_name,
    EFX_OT_material_set_shader,
    EFX_OT_material_remove_block,
    EFX_OT_material_pick_mrl3_reference,
    EFX_OT_material_clear_mrl3_reference,
    EFX_OT_material_add_from_mrl3,
    EFX_OT_field_help,
    EFX_OT_randomize_seed,
    EFX_OT_randomfix_set_table_group,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        bpy.utils.register_class(EFX_FH_import)

    # WindowManager 属性提供原生 Collection ID 搜索控件。
    bpy.types.WindowManager.efx_export_target = PointerProperty(
        name=T("export.target_efx"),
        description=T("export.target_efx_tip"),
        type=bpy.types.Collection,
        poll=_export_target_poll,
        options={"SKIP_SAVE"},
    )

    # 参考 mrl3 是会话状态，不属于 EFX 数据。
    bpy.types.Scene.efx_material_ref_mrl3_path = StringProperty(
        name="Reference .mrl3",
        description="Path to a .mrl3 file whose materials can be added as material slots",
        default="",
    )


def unregister():
    if hasattr(bpy.types.Scene, "efx_material_ref_mrl3_path"):
        del bpy.types.Scene.efx_material_ref_mrl3_path

    if hasattr(bpy.types.WindowManager, "efx_export_target"):
        del bpy.types.WindowManager.efx_export_target

    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        try:
            bpy.utils.unregister_class(EFX_FH_import)
        except RuntimeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
