"""
blender_efx/file_menu.py  —  外部文件的统一入口层：File > Import / Export + 拖入

本模块不定义任何新的算子逻辑，只把已有的导入/导出算子挂到 Blender 的标准入口上：

  File > Import >  MHW Effect (.efx)        → efx.import_efx
                   MHW Timeline (.timl)     → efx.import_entry_timl
                   MHW UV Sequence (.uvs)   → efx.uvs_import
  File > Export >  同三条 → efx.export_efx / efx.export_entry_timl / efx.uvs_export

.timl / .uvs 两条仍是「灌进/取自当前选中对象」的语义（TIML 进 entry、UVS 进
UVSEQUENCE 属性），选中目标不对时菜单项按算子 poll 自动灰显，灰显原因由算子的
poll_message_set 给出。

拖入（FileHandler）：.efx 的拖入在 operators.py 里；本模块补 .timl / .uvs 两个。
⚠ 版本守卫：FileHandler 是 Blender 4.1+ API，3.6 上 bpy.types.FileHandler 不存在，
直接继承会在模块加载期 AttributeError——故类定义与注册都要守卫（同 CLAUDE.md §1 规则 3）。

约束（CLAUDE.md）：Python 3.10 语法、bpy 稳定子集、包内相对导入。
"""

import bpy

from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# File > Import / Export 菜单项
# ─────────────────────────────────────────────────────────────────────────────
#
# 菜单里的算子按各自 poll 自动灰显；.efx 两条无 poll 限制恒可用，
# .timl / .uvs 需要先选中对应宿主对象。

def _menu_func_import(self, context):
    layout = self.layout
    layout.operator("efx.import_efx",        text=T("filemenu.efx"))
    layout.operator("efx.import_entry_timl", text=T("filemenu.timl"))
    layout.operator("efx.uvs_import",        text=T("filemenu.uvs"))


def _menu_func_export(self, context):
    layout = self.layout
    layout.operator("efx.export_efx",        text=T("filemenu.efx"))
    layout.operator("efx.export_entry_timl", text=T("filemenu.timl"))
    layout.operator("efx.uvs_export",        text=T("filemenu.uvs"))


# ─────────────────────────────────────────────────────────────────────────────
# 拖入 3D 视口：.timl / .uvs
# ─────────────────────────────────────────────────────────────────────────────

_HAS_FILEHANDLER = hasattr(bpy.types, "FileHandler")
EFX_FH_import_timl = None
EFX_FH_import_uvs = None


def _drop_area_ok(context) -> bool:
    """仅在 3D 视口（VIEW_3D）的 WINDOW 区域允许拖放（同 operators.py 的 .efx 拖入）。"""
    return (
        context.area is not None
        and context.area.type == "VIEW_3D"
        and context.region is not None
        and context.region.type == "WINDOW"
    )


if _HAS_FILEHANDLER:
    class EFX_FH_import_timl(bpy.types.FileHandler):
        """.timl 拖入 3D 视口 → 写进当前选中 entry 的 TIML 段（弹窗确认）。"""

        bl_idname          = "EFX_FH_import_timl"
        bl_label           = "Import TIML"
        bl_import_operator = "efx.import_entry_timl"
        bl_file_extensions = ".timl"

        @classmethod
        def poll_drop(cls, context):
            # 目标不对时不接收拖放（避免落地后算子 poll 失败、看起来"没反应"）
            if not _drop_area_ok(context):
                return False
            from .timl_io import _entry_is_timl_capable, resolve_timl_entry
            return _entry_is_timl_capable(resolve_timl_entry(context.active_object))

    class EFX_FH_import_uvs(bpy.types.FileHandler):
        """.uvs 拖入 3D 视口 → 载入当前选中 UVSEQUENCE 属性（弹窗确认）。"""

        bl_idname          = "EFX_FH_import_uvs"
        bl_label           = "Import UVS"
        bl_import_operator = "efx.uvs_import"
        bl_file_extensions = ".uvs"

        @classmethod
        def poll_drop(cls, context):
            if not _drop_area_ok(context):
                return False
            from .uvs_io import _is_uvsequence_attribute
            return _is_uvsequence_attribute(context.active_object)


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)
    # FileHandler 仅在 4.1+ 注册（老版本无此 API，跳过拖入导入）
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
