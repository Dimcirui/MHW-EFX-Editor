"""
blender_efx/operators.py  —  L1.0 + L1.2 + L1.3 扩展：导入/导出算子 + 预设算子 + FileHandler

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：Operator / ImportHelper / ExportHelper / register_class
  - FileHandler：Blender 4.1+ 稳定 API（4.3.2 / 5.1 均有）
  - 不使用 5.x 新增 API
  - 不改 io_tree.py / efx_format/

字段复用：efx.copy_block_fields / efx.paste_block_fields（即时内存剪贴板）。
  （旧「字段值预设」算子 save/apply_block_preset 已移除，整块预设见 block_ops。）

L1.3 拖入导入（FileHandler）：
  EFX_FH_import  —  注册 .efx 文件拖入 3D 视口时调用 efx.import_efx
  efx.import_efx 补充 files+directory 属性支持 FileHandler 调用约定，
  同时保持原有"文件浏览器/按钮选文件导入"用法不变。
"""

import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import StringProperty, CollectionProperty

from . import io_tree
from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具：从 context 解析 EFX_ROOT 对象
# ─────────────────────────────────────────────────────────────────────────────

def _find_efx_root(context):
    """
    从 context.active_object 向上查找 ~TYPE == 'EFX_ROOT' 的对象。

    搜索策略：
      1. 先检查 active_object 本身是否就是 EFX_ROOT。
      2. 沿 parent 链向上爬，找到第一个 ~TYPE == 'EFX_ROOT'。
      3. 若上述均未找到，在 active_object 所在的全部集合中
         枚举集合里的对象，寻找 ~TYPE == 'EFX_ROOT'。
      4. 仍找不到则返回 None。

    返回
    ----
    bpy.types.Object 或 None
    """
    obj = context.active_object
    if obj is None:
        return None

    # ── 策略 1 & 2：自身或祖先链 ────────────────────────────────────────────
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent

    # ── 策略 3：同集合内搜索 ─────────────────────────────────────────────────
    # 收集 active_object 所属的全部集合（对象可属于多个集合）
    for col in obj.users_collection:
        # 向上找顶层集合（parent_recursive），也检查同集合兄弟
        for candidate in col.objects:
            if candidate.get("~TYPE") == "EFX_ROOT":
                return candidate
        # 遍历父集合层级
        for parent_col in _parent_collections(col, context.scene.collection):
            for candidate in parent_col.objects:
                if candidate.get("~TYPE") == "EFX_ROOT":
                    return candidate

    return None


def _parent_collections(col, scene_collection):
    """
    生成 col 在场景集合树中所有祖先集合（不含 col 自身）。
    用于策略 3 向上枚举集合层级。
    """
    results = []
    _walk_for_parent(scene_collection, col, results)
    return results


def _walk_for_parent(current, target, acc):
    """递归：若 current 的子集合包含 target，把 current 加入 acc 并向上继续。"""
    for child in current.children:
        if child == target:
            acc.append(current)
            return True
        if _walk_for_parent(child, target, acc):
            acc.append(current)
            return True
    return False


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

    def invoke(self, context, event):
        # FileHandler 拖入：Blender 已把 directory + files 填好 → 直接执行，不弹文件浏览器。
        # （ImportHelper 默认 invoke 总是开浏览器，会让拖入"无反应"——这是拖入失效的根因。）
        if self.directory and self.files:
            return self.execute(context)
        # 普通菜单/按钮：走 ImportHelper 的文件浏览器。
        return ImportHelper.invoke(self, context, event)

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
        errors = []
        for filepath in paths:
            try:
                root_obj = io_tree.import_efx_tree(filepath, context)
                imported.append(root_obj.name)
                imported_roots.append(root_obj)
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
                for root_obj in imported_roots:
                    transform_sync.sync_all_transform3d(root_obj, armature)
            except Exception:
                pass  # 摆位是可视化增强，失败不影响导入本身

        if imported:
            names = ", ".join(imported)
            self.report({"INFO"}, f"EFX import complete: {names}")

        # 有任何成功导入则返回 FINISHED；全部失败才返回 CANCELLED
        if imported:
            return {"FINISHED"}
        return {"CANCELLED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_export
# ─────────────────────────────────────────────────────────────────────────────

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

    def execute(self, context):
        # ── 1. 解析要导出的 EFX_ROOT ─────────────────────────────────────────
        # 优先用 N 面板的 Active EFX（选中的 .efx 集合）；否则回退到活动对象所属的 EFX。
        # 这样不必非得选中 EFX 内某个对象——选好 Active EFX 即可导出。
        from .add_ops import get_active_efx_root
        root = get_active_efx_root(context) or _find_efx_root(context)
        if root is None:
            self.report(
                {"ERROR"},
                "No EFX specified for export: select an Active EFX collection in the N-panel EFX area, or select any object in the EFX object tree",
            )
            return {"CANCELLED"}

        # ── 1.5 导出前校验（#4）：悬空指针 / 重复 index 等 ERROR → 取消导出 ────
        from .validate import validate_efx_tree
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

        # ── 1.7 导出前静默规范化块顺序 ────────────────────────────────────────
        try:
            from .reorder import auto_sort_body_blocks
            auto_sort_body_blocks(root)
        except Exception:
            pass  # 排序失败不阻断导出

        # ── 2. 导出为字节 ───────────────────────────────────────────────────
        try:
            data = io_tree.export_efx_tree(root)
        except Exception as exc:
            import traceback
            self.report(
                {"ERROR"},
                f"EFX export serialization failed: {exc}\n{traceback.format_exc()}",
            )
            return {"CANCELLED"}

        # ── 3. 写文件 ───────────────────────────────────────────────────────
        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to write file: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"EFX export complete: {self.filepath} ({len(data)} bytes, root object: {root.name})",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# L1.4 即时复制/粘贴（内存剪贴板）
#   （旧「字段值预设」算子 EFX_OT_save/apply_block_preset 已移除：块预设改为
#    block_ops 的整块增删机制；字段复用保留为下方的即时复制/粘贴。）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级内存剪贴板：{"type_hash": str, "fields": {...同 preset JSON fields 结构...}}
# 不写磁盘，会话级生命周期（Blender 重启清空）。
_FIELD_CLIPBOARD = {}


class EFX_OT_copy_block_fields(bpy.types.Operator):
    """把当前 EFX_BLOCK 的可编辑字段值复制到内存剪贴板"""

    bl_idname      = "efx.copy_block_fields"
    bl_label       = "Copy Field Values"
    bl_description = "Copy all editable field values of the current EFX_BLOCK to the in-memory clipboard (for pasting into a block of the same type)"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
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


class EFX_OT_paste_block_fields(bpy.types.Operator):
    """把内存剪贴板的字段值粘贴到当前 EFX_BLOCK（类型必须一致）"""

    bl_idname      = "efx.paste_block_fields"
    bl_label       = "Paste Field Values"
    bl_description = "Write the clipboard field values into the current EFX_BLOCK (only for blocks of the same type as the copy source)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """剪贴板为空、或当前块不可编辑、或类型不符时灰显。"""
        if not _FIELD_CLIPBOARD:
            return False
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
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

        obj = context.active_object
        bp = obj.efx_block

        # type_hash 双重校验（poll 已做过，execute 再守一次）
        clip_hash = _FIELD_CLIPBOARD.get("type_hash", "")
        if clip_hash != bp.type_hash_str:
            self.report(
                {"ERROR"},
                f"Paste failed: type mismatch (clipboard hash={clip_hash!r}, "
                f"current block hash={bp.type_hash_str!r})",
            )
            return {"CANCELLED"}

        # 建 name→item 映射
        item_by_name = {}
        for item in bp.field_items:
            if not item.ori_name.startswith("__"):
                item_by_name[item.ori_name] = item

        # 写入字段值（复用 presets.py 的 _json_value_to_item + _LOADING 守卫）
        fields_dict = _FIELD_CLIPBOARD.get("fields", {})
        written = 0

        old_loading = _fields._LOADING
        _fields._LOADING = True
        try:
            for ori_name, field_entry in fields_dict.items():
                item = item_by_name.get(ori_name)
                if item is None:
                    continue
                if item.read_only:
                    continue
                data_type = field_entry.get("data_type", "")
                if data_type != item.data_type:
                    continue
                value = field_entry.get("value")
                if value is None:
                    continue
                ok = _json_value_to_item(item, data_type, value)
                if ok:
                    item.edited = True
                    written += 1
        finally:
            _fields._LOADING = old_loading

        if written > 0:
            bp.efx_dirty = True

        self.report({"INFO"}, f"EFX fields pasted: {written} field(s) written")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# #2 字段说明 tooltip 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_field_help(bpy.types.Operator):
    """
    纯提示算子：执行无副作用，description 动态返回字段注释。
    在 EFX_BLOCK 字段面板中，有注释的字段旁会显示 ⓘ 图标；
    悬停该图标即可在 tooltip 中读取 BT 注释说明。
    """

    bl_idname      = "efx.field_help"
    bl_label       = "Field Description"
    bl_options     = {"REGISTER"}

    type_name: bpy.props.StringProperty(
        name="Type Name",
        description="Block type name corresponding to HASH_TO_NAME (uppercase, e.g. EMITTERSHAPE3D)",
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

_CLASSES = (
    EFX_OT_import,
    EFX_OT_export,
    # 旧字段值预设算子（save/apply_block_preset、open_preset_folder）已删：
    # 块预设改为 block_ops 整块机制；字段复用保留为即时复制/粘贴。
    EFX_OT_copy_block_fields,
    EFX_OT_paste_block_fields,
    EFX_OT_field_help,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # FileHandler 仅在 4.1+ 注册（老版本无此 API，跳过拖入导入）
    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        bpy.utils.register_class(EFX_FH_import)


def unregister():
    if _HAS_FILEHANDLER and EFX_FH_import is not None:
        try:
            bpy.utils.unregister_class(EFX_FH_import)
        except RuntimeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
