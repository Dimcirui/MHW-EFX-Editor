# -*- coding: utf-8 -*-
"""
blender_efx/material_view.py — MATERIAL 块的只读槽位标注面板

MATERIAL 是 mrl3 同源的内嵌材质覆盖（见 docs/BLOCK_BEHAVIOR_NOTES、SPEC）。本面板
把 opaque 的 MATERIAL 字节解析成可读结构：主材质类型 + 每条贴图路径的槽位名
（tAlbedoMap / tNormalMap / ...）。**纯只读**，不碰字节/导出（路径编辑仍走原有路径 UI）。

槽位/类型名经 efx_format.material_meta 反查（解包自 mrl3 字典）。
"""

import base64
import bpy

from .i18n import T


def _material_hash():
    from ..efx_format.hashes import MATERIAL
    return MATERIAL


def _block_data_bytes(obj):
    """从 EFX_BLOCK 取 data_bytes（efx_block.raw_b64）；失败返回 None。"""
    try:
        return base64.b64decode(str(obj.efx_block.raw_b64))
    except Exception:
        return None


def _is_material_block(obj):
    if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
        return False
    try:
        return int(obj.efx_block.type_hash_str) == _material_hash()
    except (AttributeError, ValueError, ImportError):
        return False


class EFX_PT_material_slots(bpy.types.Panel):
    """MATERIAL 块的只读槽位视图（VIEW_3D N 面板，选中 MATERIAL 块时显示）。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "MATERIAL Slots"
    bl_parent_id   = "EFX_PT_main"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _is_material_block(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        data = _block_data_bytes(obj)
        if data is None:
            layout.label(text=T("material.parse_fail"), icon="ERROR")
            return

        from ..efx_format import material_meta
        summary = material_meta.parse_material(data)
        if summary is None:
            layout.label(text=T("material.parse_fail"), icon="ERROR")
            return

        for bi, blk in enumerate(summary["blocks"]):
            box = layout.box()
            tname = blk["type_name"] or ("0x%08X" % blk["shader_hash"])
            box.label(text=T("material.type") + " " + tname, icon="MATERIAL")

            paths = [s for s in blk["sets"] if s["path"]]
            params = len(blk["sets"]) - len(paths)
            if not paths:
                box.label(text=T("material.no_paths"), icon="INFO")
            for s in paths:
                slot = s["slot"] or ("0x%08X" % s["t"])
                row = box.row(align=True)
                row.label(text=slot, icon="TEXTURE")
                row.label(text=s["path"])
            box.label(
                text=T("material.set_count").format(p=len(paths), n=params),
                icon="DOT",
            )


_CLASSES = (
    EFX_PT_material_slots,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
