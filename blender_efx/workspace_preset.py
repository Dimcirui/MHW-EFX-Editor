# -*- coding: utf-8 -*-
"""
blender_efx/workspace_preset.py — 一键添加"MHW VFX"工作区预设

模板是随包分发的 assets/mhw_vfx_workspace.blend（只含一个 Workspace 数据块，
Dope Sheet 在上、3D 视口+大纲视图+属性编辑器在下，跟官方讲座截图的布局一致）。
算子把这个 Workspace 追加进当前文件并切到它，不改动用户已有的任何工作区。

重复点击不会重复追加：先只读模板里的工作区名字，若当前文件已有同名工作区就直接
切过去；否则才真的 append（避免 Blender 对同名数据块默认加 .001 后缀，越点越多）。
"""

import os

import bpy

from . import i18n
from .i18n import T


def _template_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "mhw_vfx_workspace.blend")


class EFX_OT_add_mhw_vfx_workspace(bpy.types.Operator):
    """追加内置的 MHW VFX 工作区预设并切换过去"""

    bl_idname  = "efx.add_mhw_vfx_workspace"
    bl_label   = "Add MHW VFX Workspace"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = _template_path()
        if not os.path.isfile(path):
            self.report({"ERROR"}, T("entry.workspace_missing"))
            return {"CANCELLED"}

        # 先只读模板里的工作区名字（不赋值给 data_to 就不会真的导入），已存在同名工作区
        # 就直接切过去，不重复 append——否则 Blender 对同名数据块的默认处理是自动加
        # .001 后缀新建一份，连点几次工作区列表里就会堆出一串重复项。
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
