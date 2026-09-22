"""删除 Entry、属性、Action、Extern 与 Subselect。

维护约束：
- 本模块的删除路径会重排同级 efx_index 和显示名，并设置标签或 Subselect 脏标记；
  导出端从实际对象重算计数、大小与 EOF。
- 删除 Entry 时必须同时删除直属属性和 TIML 子对象。
- 删除 Extern 不主动清理引用；对象指针可变为悬空，需由用户决定是否重连。
- 原生删除可保留不连续索引；失去 parent 的属性不会被导出为其他 Entry 的属性。
"""

import bpy

from .reorder import (
    _collect_siblings_by_type,
    _entry_display_name,
    _attribute_display_name,
    _get_entry_raw_label,
    _get_attribute_type_name,
    _get_attribute_parent_label,
)
from . import root_collection as _rc


def _nn(idx: int) -> str:
    """返回显示名使用的两位序号。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _reindex_siblings(parent_obj, type_tag: str, rebuild_name_fn) -> int:
    """重排同级索引和显示名，并返回剩余数量。"""
    if isinstance(parent_obj, bpy.types.Collection):
        siblings = _rc.collect_top_level(parent_obj, type_tag)
    else:
        siblings = _collect_siblings_by_type(parent_obj, type_tag)
    for new_idx, o in enumerate(siblings):
        o["efx_index"] = new_idx
        o.name = rebuild_name_fn(o, new_idx)
    return len(siblings)


def _rebuild_entry_name(o, new_idx):
    return _entry_display_name(new_idx, _get_entry_raw_label(o), entry_obj=o)


def _rebuild_attribute_name(o, new_idx):
    return _attribute_display_name(
        new_idx, _get_attribute_parent_label(o), _get_attribute_type_name(o)
    )


def _rebuild_action_name(o, new_idx):
    label = str(o.get("efx_raw_label", ""))
    return f"{_nn(new_idx)} {label}"


def _rebuild_extern_name(o, new_idx):
    label = str(o.get("efx_raw_label", ""))
    return f"{_nn(new_idx)} {label}"


def _rebuild_subselect_name(o, new_idx):
    return f"{_nn(new_idx)} subselect_{new_idx}"


class EFX_OT_delete_entry(bpy.types.Operator):
    """删除所有选中的 EFX_ENTRY（连带各自全部 EFX_ATTRIBUTE 子属性），重排剩余 entry"""

    bl_idname      = "efx.delete_entry"
    bl_label       = "Delete Entry"
    bl_description = (
        "Delete all selected EFX_ENTRY objects (including their attributes); remaining entries "
        "are renumbered consecutively. Safer than Blender's native Delete Hierarchy, which "
        "deletes the hierarchy of every currently selected object — a stray selected attribute "
        "belonging to a different entry gets silently swept away too"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_ENTRY"
            and _rc.find_root_collection(obj) is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = context.active_object
        root = _rc.find_root_collection(active)

        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ENTRY" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        for obj in targets:
            children = [
                c for c in bpy.data.objects
                if c.parent == obj and c.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML")
            ]
            for child in children:
                bpy.data.objects.remove(child, do_unlink=True)
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_ENTRY", _rebuild_entry_name)

        root["labels_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ENTRY(s), {remaining} entry(s) remaining",
        )
        return {"FINISHED"}


class EFX_OT_delete_attribute(bpy.types.Operator):
    """删除所有选中的 EFX_ATTRIBUTE，重排各自所属 entry 内剩余属性"""

    bl_idname      = "efx.delete_attribute"
    bl_label       = "Delete Attribute"
    bl_description = "Delete all selected EFX_ATTRIBUTE objects; remaining attributes in each affected entry are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        parent = obj.parent
        return parent is not None and parent.get("~TYPE") == "EFX_ENTRY"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ATTRIBUTE"
            and o.parent is not None
            and o.parent.get("~TYPE") == "EFX_ENTRY"
        ]
        if not targets:
            targets = [context.active_object]

        affected_bodies = {o.parent for o in targets}

        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        for body in affected_bodies:
            _reindex_siblings(body, "EFX_ATTRIBUTE", _rebuild_attribute_name)
            body.name = _rebuild_entry_name(body, int(body.get("efx_index", 0)))

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ATTRIBUTE(s) across {len(affected_bodies)} entry(s)",
        )
        return {"FINISHED"}


class EFX_OT_delete_action(bpy.types.Operator):
    """删除所有选中的 EFX_ACTION，重排剩余 action"""

    bl_idname      = "efx.delete_action"
    bl_label       = "Delete Action"
    bl_description = "Delete all selected EFX_ACTION objects; remaining actions are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_ACTION"
            and _rc.find_root_collection(obj) is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = context.active_object
        root = _rc.find_root_collection(active)

        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ACTION" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_ACTION", _rebuild_action_name)

        root["labels_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ACTION(s), {remaining} action(s) remaining",
        )
        return {"FINISHED"}


class EFX_OT_delete_extern(bpy.types.Operator):
    """删除所有选中的 EFX_EXTERN，重排剩余 extern（被引用的属性指针变悬空，由校验报告）"""

    bl_idname      = "efx.delete_extern"
    bl_label       = "Delete Extern"
    bl_description = (
        "Delete all selected EFX_EXTERN objects; remaining externs are renumbered consecutively. "
        "Note: pointers referenced by ExternReference attributes will dangle (check with pre-export validation)"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_EXTERN"
            and _rc.find_root_collection(obj) is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = context.active_object
        root = _rc.find_root_collection(active)

        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_EXTERN" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_EXTERN", _rebuild_extern_name)

        root["labels_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_EXTERN(s), {remaining} extern(s) remaining",
        )
        return {"FINISHED"}


class EFX_OT_delete_subselect(bpy.types.Operator):
    """删除所有选中的 EFX_SUBSELECT，重排剩余 subselect"""

    bl_idname      = "efx.delete_subselect"
    bl_label       = "Delete Subselect"
    bl_description = "Delete all selected EFX_SUBSELECT objects; remaining subselects are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_SUBSELECT"
            and _rc.find_root_collection(obj) is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = context.active_object
        root = _rc.find_root_collection(active)

        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_SUBSELECT" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_SUBSELECT", _rebuild_subselect_name)

        root["subselect_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_SUBSELECT(s), {remaining} subselect(s) remaining",
        )
        return {"FINISHED"}


_CLASSES = (
    EFX_OT_delete_entry,
    EFX_OT_delete_attribute,
    EFX_OT_delete_action,
    EFX_OT_delete_extern,
    EFX_OT_delete_subselect,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
