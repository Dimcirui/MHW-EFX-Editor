# -*- coding: utf-8 -*-
"""追加内置 MHW VFX 工作区预设。

维护约束：追加前必须只读模板的工作区名称；当前文件已有同名工作区时直接切换，
不得再次 append，以避免重复数据块和 Blender 自动改名。
"""

import os

import bpy

from . import i18n
from .i18n import T


def _template_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "mhw_vfx_workspace.blend")


class EFX_OT_add_mhw_vfx_workspace(bpy.types.Operator):
    """追加内置工作区，或切换到现有同名工作区。"""

    bl_idname  = "efx.add_mhw_vfx_workspace"
    bl_label   = "Add MHW VFX Workspace"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = _template_path()
        if not os.path.isfile(path):
            self.report({"ERROR"}, T("entry.workspace_missing"))
            return {"CANCELLED"}

        # 读取模板名称不会导入数据块，可用于避免重复追加。
        with bpy.data.libraries.load(path, link=False) as (data_from, _data_to):
            template_names = list(data_from.workspaces)
        if not template_names:
            self.report({"ERROR"}, T("entry.workspace_missing"))
            return {"CANCELLED"}

        existing = bpy.data.workspaces.get(template_names[0])
        if existing is not None:
            context.window.workspace = existing
            self.report({"INFO"}, f"{T('entry.workspace_switched')}: {existing.name}")
            return {"FINISHED"}

        before = set(bpy.data.workspaces.keys())
        with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
            data_to.workspaces = list(data_from.workspaces)
        added = [n for n in bpy.data.workspaces.keys() if n not in before]

        ws = bpy.data.workspaces.get(added[0]) if added else None
        if ws is None:
            self.report({"ERROR"}, T("entry.workspace_missing"))
            return {"CANCELLED"}

        context.window.workspace = ws
        self.report({"INFO"}, f"{T('entry.workspace_added')}: {ws.name}")
        return {"FINISHED"}


_CLASSES = (EFX_OT_add_mhw_vfx_workspace,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
