"""
efx_editor/__init__.py  —  MHW EFX 编辑器 Blender 扩展根入口

此文件与 blender_manifest.toml 同级，是 Blender 扩展系统识别的入口。
Blender 加载时此目录被视为包 bl_ext.user_default.efx_editor。

结构：
  efx_editor/             ← 扩展包根（本文件所在目录）
  ├── __init__.py         ← 本文件（扩展入口，委托给 blender_efx）
  ├── blender_manifest.toml
  ├── blender_efx/        ← Blender 胶水层（operators / panels / io_tree / fields）
  │   └── __init__.py
  └── efx_format/         ← 纯 Python 解析层（零 bpy 依赖）
      └── __init__.py

开发期 importlib 加载片段（供 MCP / Blender Python 解释器使用）：
  import importlib.util, sys
  ROOT = r"E:\\Data\\Github\\Python\\EFX-Editor"
  spec = importlib.util.spec_from_file_location(
      "efx_editor",
      ROOT + r"\\__init__.py",
      submodule_search_locations=[ROOT],
  )
  mod = importlib.util.module_from_spec(spec)
  sys.modules["efx_editor"] = mod
  spec.loader.exec_module(mod)
  # 加载完毕后：
  #   efx_editor.register()   →  注册全部算子/面板
  #   efx_editor.unregister() →  注销
  #   efx_editor.blender_efx.import_efx_tree(path)  →  导入
  #   efx_editor.blender_efx.export_efx_tree(root)  →  导出
"""

# 版本号常量：与 blender_manifest.toml 的 version 同步改（两处）。
# ⚠ 单独抽常量的原因：4.2+ 扩展系统加载时会**剥离/忽略模块里的 bl_info**（扩展用 manifest），
# 故 register() 里绝不能引用 `bl_info` 这个名字（扩展路径下 NameError）——改用本常量。
_VERSION = (0, 5, 5)

# bl_info：仅供 Blender 老式 addon 系统（<4.2，如 3.6）识别。
# 4.2+ 扩展系统忽略它、改用 blender_manifest.toml。两者并存无冲突。
# 老式 addon 打包变体（tools/build_extension.py --legacy）会把本包套进 efx_editor/ 文件夹。
bl_info = {
    "name": "MHW EFX Editor",
    "author": "Dimcirui",
    "version": _VERSION,
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > EFX",
    "description": "Import and export Monster Hunter World EFX effect files",
    "category": "Import-Export",
}

import bpy
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, IntProperty

from . import addon_updater_ops   # CGCookie Blender Add-on Updater（从 Modding-Toolkit 移植）
from . import blender_efx
from . import blender_epv


# ── 插件偏好设置（Edit > Preferences > Add-ons > MHW EFX Editor）──────────────
# CGCookie addon_updater：检查 GitHub 发行版（Dimcirui/MHW-EFX-Editor）并可下载/安装。
# ⚠ 更新器主要面向老式 addon（zip 手动安装）分发；4.2+ 扩展由 Blender 扩展系统管理更新，
#   自动就地安装未必可靠，但"检查更新 + 打开下载页"两版本都可用。扩展需 manifest 声明网络权限。
class EFX_Preferences(AddonPreferences):
    """插件偏好设置（编辑器选项 + 更新器）。`bl_idname` 必须是顶层包名，别改。"""

    bl_idname = __name__

    # ── 编辑器选项 ────────────────────────────────────────────────────────────
    # 默认关：字段按**字节序**原样显示。字节序本身带语义（同类字段是挨着的），
    # 分档会把「不常用」的字段从它原本的邻居里拽走，逆向字段作用时反而碍事。
    # 想要更干净的面板再手动打开。
    field_tiers: BoolProperty(
        name="Group rarely-edited fields under \"Advanced\"",
        description=(
            "Fold placeholder / never-changed fields into a collapsible "
            "\"Advanced\" section. Off by default: the byte order carries meaning "
            "(related fields sit next to each other), and tiering pulls fields out "
            "of that neighbourhood"
        ),
        default=False,
    )

    auto_check_update: BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=False,
    )
    updater_interval_months: IntProperty(
        name="Months", description="Number of months between checking for updates",
        default=0, min=0)
    updater_interval_days: IntProperty(
        name="Days", description="Number of days between checking for updates",
        default=7, min=0)
    updater_interval_hours: IntProperty(
        name="Hours", description="Number of hours between checking for updates",
        default=0, min=0, max=23)
    updater_interval_minutes: IntProperty(
        name="Minutes", description="Number of minutes between checking for updates",
        default=0, min=0, max=59)

    def draw(self, context):
        layout = self.layout
        try:
            from .blender_efx.i18n import get_lang
            zh = get_lang() == "ZH"
        except Exception:
            zh = False
        box = layout.box()
        box.label(text="编辑器" if zh else "Editor",
                  icon="PREFERENCES")
        box.prop(self, "field_tiers",
                 text=("字段分档：把不常改的字段折进「高级」" if zh
                       else "Group rarely-edited fields under \"Advanced\""))
        sub = box.row()
        sub.enabled = False
        sub.label(text=("关闭时字段按字节序原样显示——字节序本身带语义，逆向字段作用时别开"
                        if zh else
                        "When off, fields keep their raw byte order, which carries meaning"))
        layout.separator()
        addon_updater_ops.update_settings_ui(self, context)


def register():
    """注册扩展（Blender 扩展系统入口）。"""
    # 更新器须先注册（clear_state + 读取版本），再注册偏好设置类。
    # ⚠ 传 {"version": _VERSION} 而非 bl_info——扩展路径下 bl_info 名字可能已被剥离（见上）。
    addon_updater_ops.register({"version": _VERSION})
    bpy.utils.register_class(EFX_Preferences)
    blender_efx.register()
    blender_epv.register()


def unregister():
    """注销扩展（Blender 扩展系统入口）。"""
    blender_epv.unregister()
    blender_efx.unregister()
    bpy.utils.unregister_class(EFX_Preferences)
    addon_updater_ops.unregister()
