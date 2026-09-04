"""
blender_efx/file_menu.py  —  外部文件的统一入口层：File > Import / Export + 拖入

本模块不定义任何新的算子逻辑，只把已有的导入/导出算子挂到 Blender 的标准入口上：

  File > Import >  MHW Effect (.efx)              → efx.import_efx
                   MHW Timeline (.timl)           → efx.import_entry_timl
                   MHW UV Sequence (.uvs)         → efx.uvs_import
                   MHW Effect Provider (.epv3)    → epv.import_epv
  File > Export >  同四条 → efx.export_efx / efx.export_entry_timl / efx.uvs_export / epv.export_epv

⚠ .epv3 两条的算子在**兄弟包 blender_epv** 里，而它在根 __init__.py 里排在 blender_efx
之后注册。菜单项只在 draw 时按 bl_idname 解析，正常情况没问题；但为防部分注册状态下
画出报错的菜单项，这里仍按存在性守卫（_has_epv）。

.timl / .uvs 两条按当前选中对象二选一：选中了合适的宿主（entry / UVSEQUENCE 属性）就灌进去，
否则**无宿主独立打开**（见 standalone.py），两种情况都在文件浏览器侧栏给出勾选可改。
故这两条菜单项恒可用，不会灰显。

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

def _has_epv() -> bool:
    """blender_epv 的算子是否已注册（它在根 __init__.py 里排在 blender_efx 之后）。

    ⚠ 查的名字是 bl_idname 推导出来的 RNA 名（"epv.import_epv" → EPV_OT_import_epv），
    **不是** Python 类名（那个叫 EPV_OT_import，查它恒为假）。
    """
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
    """仅在 3D 视口（VIEW_3D）的 WINDOW 区域允许拖放（同 operators.py 的 .efx 拖入）。"""
    return (
        context.area is not None
        and context.area.type == "VIEW_3D"
        and context.region is not None
        and context.region.type == "WINDOW"
    )


if _HAS_FILEHANDLER:
    class EFX_FH_import_timl(bpy.types.FileHandler):
        """.timl 拖入 3D 视口 → 写进当前选中 entry，或无宿主时独立打开（弹窗确认）。"""

        bl_idname          = "EFX_FH_import_timl"
        bl_label           = "Import TIML"
        bl_import_operator = "efx.import_entry_timl"
        bl_file_extensions = ".timl"

        @classmethod
        def poll_drop(cls, context):
            # 不再要求先选中 entry：没有合适宿主时算子会走无主打开（standalone.py），
            # 落地总有结果，故这里只限定可拖放区域。
            return _drop_area_ok(context)

    class EFX_FH_import_uvs(bpy.types.FileHandler):
        """.uvs 拖入 3D 视口 → 载入当前选中 UVSEQUENCE 属性，或无宿主时独立打开（弹窗确认）。"""

        bl_idname          = "EFX_FH_import_uvs"
        bl_label           = "Import UVS"
        bl_import_operator = "efx.uvs_import"
        bl_file_extensions = ".uvs"

        @classmethod
        def poll_drop(cls, context):
            # 同上：没有 UVSEQUENCE 宿主时走无主打开。
            return _drop_area_ok(context)


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
