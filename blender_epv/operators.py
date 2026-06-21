"""
blender_epv/operators.py — EPV3 导入 / 导出算子（+ FileHandler 拖入）。

镜像 blender_efx/operators.py 的稳定 API 子集：
  - Operator / ImportHelper / ExportHelper / register_class
  - FileHandler：4.1+ 才有，用 _HAS_FILEHANDLER 守卫类定义 + 注册（3.6 无此 API）。
"""
import os

import bpy
from bpy.props import StringProperty, CollectionProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import io_tree


# ─────────────────────────────────────────────────────────────────────────────
# EPV_ROOT 定位
# ─────────────────────────────────────────────────────────────────────────────

def _parent_collection_of(target_col):
    """返回 target_col 的父集合（扫描法；找不到返回 None）。"""
    for col in bpy.data.collections:
        for child in col.children:
            if child == target_col:
                return col
    # 也可能直接挂在 scene 根集合下
    for scene in bpy.data.scenes:
        for child in scene.collection.children:
            if child == target_col:
                return scene.collection
    return None


def find_epv_root(context):
    """从活动对象推断所属 EPV_ROOT；找不到时若全场景只有一个 EPV_ROOT 则用它。"""
    obj = context.active_object
    if obj is not None:
        if obj.get("~TYPE") == "EPV_ROOT":
            return obj
        # record 对象：其集合(group)的父集合即根集合，内含 EPV_ROOT empty
        for gcol in obj.users_collection:
            root_col = _parent_collection_of(gcol)
            if root_col is not None:
                for o in root_col.objects:
                    if o.get("~TYPE") == "EPV_ROOT":
                        return o
    # 兜底：全场景唯一 EPV_ROOT
    roots = [o for o in bpy.data.objects if o.get("~TYPE") == "EPV_ROOT"]
    if len(roots) == 1:
        return roots[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 导入
# ─────────────────────────────────────────────────────────────────────────────

class EPV_OT_import(bpy.types.Operator, ImportHelper):
    """导入 MHW .epv3 特效提供器文件，在场景中建立对象树"""

    bl_idname      = "epv.import_epv"
    bl_label       = "Import EPV"
    bl_description = "Import an MHW EPV3 effect-provider file (.epv3)"
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".epv3"
    filter_glob: StringProperty(default="*.epv3", options={"HIDDEN"}, maxlen=255)

    # FileHandler 拖入：directory + files
    files: CollectionProperty(type=bpy.types.OperatorFileListElement,
                              options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        if self.directory and self.files:
            return self.execute(context)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        paths = []
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(self.directory, f.name))
        if not paths and self.filepath:
            paths = [self.filepath]
        if not paths:
            self.report({"ERROR"}, "EPV import: no file path specified")
            return {"CANCELLED"}

        imported = []
        for filepath in paths:
            try:
                root_obj = io_tree.import_epv_tree(filepath, context)
                imported.append(root_obj.name)
            except Exception as exc:
                import traceback
                self.report({"ERROR"},
                            f"EPV import failed: {filepath}\n{traceback.format_exc()}")

        if imported:
            self.report({"INFO"}, "EPV import complete: " + ", ".join(imported))
            return {"FINISHED"}
        return {"CANCELLED"}


# ─────────────────────────────────────────────────────────────────────────────
# 导出
# ─────────────────────────────────────────────────────────────────────────────

class EPV_OT_export(bpy.types.Operator, ExportHelper):
    """将当前 EPV 对象树导出为 .epv3 文件"""

    bl_idname      = "epv.export_epv"
    bl_label       = "Export EPV"
    bl_description = "Export the EPV object tree to an MHW .epv3 file"
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".epv3"
    filter_glob: StringProperty(default="*.epv3", options={"HIDDEN"}, maxlen=255)

    def execute(self, context):
        root = find_epv_root(context)
        if root is None:
            self.report({"ERROR"},
                        "No EPV specified: select the EPV_ROOT or any record in the EPV tree")
            return {"CANCELLED"}

        try:
            data = io_tree.export_epv_tree(root)
        except Exception as exc:
            import traceback
            self.report({"ERROR"},
                        f"EPV export serialization failed: {exc}\n{traceback.format_exc()}")
            return {"CANCELLED"}

        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to write file: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"},
                    f"EPV export complete: {self.filepath} ({len(data)} bytes)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# FileHandler 拖入（4.1+ 守卫）
# ─────────────────────────────────────────────────────────────────────────────

_HAS_FILEHANDLER = hasattr(bpy.types, "FileHandler")
EPV_FH_import = None

if _HAS_FILEHANDLER:
    class EPV_FH_import(bpy.types.FileHandler):
        bl_idname          = "EPV_FH_import"
        bl_label           = "Import EPV"
        bl_import_operator = "epv.import_epv"
        bl_file_extensions = ".epv3"

        @classmethod
        def poll_drop(cls, context):
            return (context.area is not None
                    and context.area.type == "VIEW_3D"
                    and context.region is not None
                    and context.region.type == "WINDOW")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EPV_OT_import,
    EPV_OT_export,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _HAS_FILEHANDLER and EPV_FH_import is not None:
        bpy.utils.register_class(EPV_FH_import)


def unregister():
    if _HAS_FILEHANDLER and EPV_FH_import is not None:
        try:
            bpy.utils.unregister_class(EPV_FH_import)
        except RuntimeError:
            pass
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
