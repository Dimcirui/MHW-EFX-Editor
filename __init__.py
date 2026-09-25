"""MHW EFX Editor 的 Blender 扩展入口。

维护约束：
- 扩展入口只协调注册与偏好设置，功能实现归属 blender_efx 与 blender_epv。
- 版本常量与 blender_manifest.toml 保持同步；扩展路径不能依赖 bl_info。
- Chunk Root 独立于 AddonPreferences 持久化，以跨扩展更新保留用户配置。
"""

# 与 blender_manifest.toml 保持同步；扩展路径使用此常量而非 bl_info。
_VERSION = (0, 7, 6)

# bl_info 供传统 addon 加载路径使用；扩展路径使用 manifest。
bl_info = {
    "name": "MHW EFX Editor",
    "author": "Dimcirui",
    "version": _VERSION,
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > EFX",
    "description": "Import and export Monster Hunter World EFX effect files",
    "category": "Import-Export",
}

import os

import bpy
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import addon_updater_ops
from . import blender_efx
from . import blender_epv


# Chunk Root 使用独立配置文件，避免扩展重装时丢失用户路径。
def _chunk_root_config_path() -> str:
    try:
        cfg = bpy.utils.user_resource("CONFIG")
    except Exception:
        cfg = os.path.expanduser("~")
    return os.path.join(cfg, "efx_editor_chunk_root.txt")


def _get_chunk_root_pref(self) -> str:
    try:
        with open(_chunk_root_config_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _set_chunk_root_pref(self, value: str) -> None:
    try:
        with open(_chunk_root_config_path(), "w", encoding="utf-8") as f:
            f.write(value)
    except Exception:
        pass


# 插件偏好设置。
class EFX_Preferences(AddonPreferences):
    """编辑器与更新器偏好；bl_idname 必须为扩展顶层包名。"""

    bl_idname = __name__

    # 默认保留字段字节序，分档仅作为可选展示方式。
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

    # 场景未设置 Chunk Root 时使用此跨文件默认值。
    chunk_root: StringProperty(
        name="Chunk Root",
        description="MHW 提取根目录默认值（含 vfx/ 等），跨文件永久生效。"
                    "场景里的 Chunk Root 留空时用这里的值；填了场景值则场景值优先",
        subtype="DIR_PATH",
        get=_get_chunk_root_pref,
        set=_set_chunk_root_pref,
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

        box2 = layout.box()
        box2.label(text="导入" if zh else "Import", icon="IMPORT")
        box2.prop(self, "chunk_root",
                  text=("默认 Chunk Root（提取根目录）" if zh else "Default Chunk Root"))
        sub2 = box2.row()
        sub2.enabled = False
        sub2.label(text=("跨文件永久生效；场景里另填了 Chunk Root 时以场景值为准"
                          if zh else
                          "Persists across files; a per-scene Chunk Root overrides this"))
        layout.separator()
        addon_updater_ops.update_settings_ui(self, context)


def register():
    """注册扩展（Blender 扩展系统入口）。"""
    # 扩展路径不保证 bl_info 可用，更新器使用版本常量。
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
