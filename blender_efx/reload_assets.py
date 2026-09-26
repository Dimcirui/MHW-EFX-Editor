# -*- coding: utf-8 -*-
"""按磁盘重新载入场景里所有 EFX 引用的 .uvs、贴图与 mod3，并让模拟预览重建。

维护约束：已绑定网格的 MESH 属性不重新导入模型，只重读网格缓存，避免重复导入和删除用户场景里的对象。
"""

import bpy

from .i18n import T
from . import mod3_link as _mod3
from . import root_collection as _rc
from . import sim_preview as _sim
from . import uvs_link as _ul


def _reload_images(names):
    """按名字重读图像像素；返回成功重读的数量。"""
    n = 0
    for name in names:
        img = bpy.data.images.get(name)
        if img is None or not img.filepath:
            continue
        try:
            img.reload()
            n += 1
        except Exception:
            pass
    return n


def _uvs_image_names(roots):
    """各 UVSEQUENCE 宿主当前绑定的序列帧贴图名。"""
    names = set()
    for root in roots:
        for blk, _rel in _ul.iter_uvsequence_attributes(root):
            host = getattr(blk, "efx_uvs_target", None) or blk
            name = getattr(getattr(host, "efx_uvs", None), "ref_image_name", "") or ""
            if name:
                names.add(name)
    return names


def _bound_mesh_image_names(roots):
    """已绑定网格的材质里用到的图像名。"""
    names = set()
    for root in roots:
        for blk, _rel in _mod3.iter_mesh_attributes(root):
            for item in getattr(blk, "efx_mesh_targets", ()):
                obj = item.obj
                if obj is None:
                    continue
                for slot in obj.material_slots:
                    mat = slot.material
                    if mat is None or not mat.use_nodes or mat.node_tree is None:
                        continue
                    for node in mat.node_tree.nodes:
                        img = getattr(node, "image", None)
                        if img is not None:
                            names.add(img.name)
    return names


class EFX_OT_reload_all_effects(bpy.types.Operator):
    """重新载入场景里所有 EFX 的 .uvs、贴图与模型"""

    bl_idname = "efx.reload_all_effects"
    bl_label = "Reload All Effects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return T("entry.reload_all_tip")

    @classmethod
    def poll(cls, context):
        return bool(_rc.all_root_collections())

    def execute(self, context):
        roots = _rc.all_root_collections()
        chunk_root = getattr(context.scene, "efx_chunk_root", "") or ""

        cached = _sim.reset_resources()

        # .uvs 与序列帧贴图：已载入的按磁盘刷新，新加入的 Entry 首次载入
        tot_uvs = 0
        problems = []
        for root in roots:
            try:
                n_uvs, _n_tex, probs = _ul.link_root(root, chunk_root, _ul.efx_dir_of(root), True)
            except Exception:
                continue
            tot_uvs += n_uvs
            problems.extend(probs)
            _ul.hide_link_collection(context, root)

        # 模型：只给没有绑定网格的 MESH 属性导入
        n_mesh = 0
        missing_mesh = []
        mesh_skipped = False
        if any(True for root in roots for _ in _mod3.iter_mesh_attributes(root)):
            if _mod3.model_editor_available():
                for root in roots:
                    try:
                        n, unresolved = _mod3.import_and_bind(
                            root, context, chunk_root, _ul.efx_dir_of(root), only_unbound=True)
                    except Exception:
                        continue
                    n_mesh += n
                    missing_mesh.extend(unresolved)
            else:
                mesh_skipped = True

        # 像素数据：缓存里出现过的、序列帧和网格材质用到的图像全部按文件重读
        names = cached | _uvs_image_names(roots) | _bound_mesh_image_names(roots)
        n_img = _reload_images(names)

        for area in getattr(context.screen, "areas", ()):
            if area.type == "VIEW_3D":
                area.tag_redraw()

        self.report({"INFO"}, T("entry.reload_all_done").format(tot_uvs, n_img, n_mesh))
        if problems:
            detail = "；".join("%s（%s）" % (name, T("uvslink.reason_" + reason))
                              for name, _rel, reason in problems[:5])
            self.report({"WARNING"}, T("uvslink.failed").format(len(problems), detail))
        if missing_mesh:
            detail = "；".join("%s（%s）" % (n, r) for n, r in missing_mesh[:5])
            self.report({"WARNING"}, T("entry.reload_all_mesh_missing").format(
                len(missing_mesh), detail))
        if mesh_skipped:
            self.report({"WARNING"}, T("entry.reload_all_no_editor"))
        return {"FINISHED"}


_CLASSES = (EFX_OT_reload_all_effects,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
