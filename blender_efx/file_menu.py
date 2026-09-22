"""Blender File 菜单与拖放入口。

本模块只挂接既有导入导出算子。EPV 算子按注册状态显示；FileHandler 仅在 API 可用时
定义并注册，以兼容不提供该类型的 Blender 版本。
"""

import bpy

from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# File > Import / Export 菜单项
# ─────────────────────────────────────────────────────────────────────────────

def _has_epv() -> bool:
    """返回 EPV 导入算子的 RNA 类是否已注册。"""
    return hasattr(bpy.types, "EPV_OT_import_epv")


def _menu_func_import(self, context):
    layout = self.layout
    layout.operator("efx.import_efx",        text=T("filemenu.efx"))
    layout.operator("efx.import_entry_timl", text=T("filemenu.timl"))
    layout.operator("efx.uvs_import",        text=T("filemenu.uvs"))
    if _has_epv():
        layout.operator("epv.import_epv",    text=T("filemenu.epv"))


def _menu_func_export(self, context):
    layout = self.layout
    layout.operator("efx.export_efx",        text=T("filemenu.efx"))
    layout.operator("efx.export_entry_timl", text=T("filemenu.timl"))
    layout.operator("efx.uvs_export",        text=T("filemenu.uvs"))
    if _has_epv():
        layout.operator("epv.export_epv",    text=T("filemenu.epv"))


# ─────────────────────────────────────────────────────────────────────────────
# 拖入 3D 视口：.timl / .uvs
# ─────────────────────────────────────────────────────────────────────────────

_HAS_FILEHANDLER = hasattr(bpy.types, "FileHandler")
EFX_FH_import_timl = None
EFX_FH_import_uvs = None


def _drop_area_ok(context) -> bool:
    """仅允许在 3D 视口的 WINDOW 区域拖放。"""
    return (
        context.area is not None
        and context.area.type == "VIEW_3D"
        and context.region is not None
        and context.region.type == "WINDOW"
    )


if _HAS_FILEHANDLER:
    class EFX_FH_import_timl(bpy.types.FileHandler):
        """TIML 拖放入口。"""

        bl_idname          = "EFX_FH_import_timl"
        bl_label           = "Import TIML"
        bl_import_operator = "efx.import_entry_timl"
        bl_file_extensions = ".timl"

        @classmethod
        def poll_drop(cls, context):
            return _drop_area_ok(context)

    class EFX_FH_import_uvs(bpy.types.FileHandler):
        """UVS 拖放入口。"""

        bl_idname          = "EFX_FH_import_uvs"
        bl_label           = "Import UVS"
        bl_import_operator = "efx.uvs_import"
        bl_file_extensions = ".uvs"

        @classmethod
        def poll_drop(cls, context):
            return _drop_area_ok(context)


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)
    # 仅在 FileHandler API 可用时注册拖放入口。
    if _HAS_FILEHANDLER:
        for cls in (EFX_FH_import_timl, EFX_FH_import_uvs):
            if cls is not None:
                bpy.utils.register_class(cls)


def unregister():
    if _HAS_FILEHANDLER:
        for cls in (EFX_FH_import_uvs, EFX_FH_import_timl):
            if cls is not None:
                try:
                    bpy.utils.unregister_class(cls)
                except RuntimeError:
                    pass
    try:
        bpy.types.TOPBAR_MT_file_export.remove(_menu_func_export)
    except Exception:
        pass
    try:
        bpy.types.TOPBAR_MT_file_import.remove(_menu_func_import)
    except Exception:
        pass
