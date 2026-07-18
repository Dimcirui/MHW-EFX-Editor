"""
blender_efx/delete_ops.py  —  L2 #3b：删除条目（entry / attribute / action / extern / subselect）

算子（全部 bl_options={"REGISTER","UNDO"}，invoke 用 invoke_confirm 弹确认，均支持多选批量删除）：
  efx.delete_entry      —  删除所有选中 EFX_ENTRY（连带其全部 EFX_ATTRIBUTE 子属性）
  efx.delete_attribute     —  删除所有选中 EFX_ATTRIBUTE
  efx.delete_action      —  删除所有选中 EFX_ACTION
  efx.delete_extern    —  删除所有选中 EFX_EXTERN
  efx.delete_subselect —  删除所有选中 EFX_SUBSELECT

设计要点（参照 CLAUDE.md / reorder.py）：
  1. 删除职责只有三件：
       ① 干净移除对象（entry 连带 attribute）；
       ② 剩余同级重新连续编号（efx_index 0..n-1）+ 重建显示名；
       ③ 置 dirty 标志（labels_dirty / subselect_dirty），供导出端重算计数/标签/size；
          eof（Direct Trigger 归属）不需要 dirty 标志，entry 被删即自动从其所在集合消失。
  2. 引用是对象指针，删除后悬空指针（None）由导出端安全跳过、由 #4 校验报告。
     删除算子不主动清理引用（Extern 多对一，清理需用户决策）。
  3. 计数/size/eof 由 io_tree 导出端从实际内容重算，删除算子无需触碰头部数据。

原生删除（用户直接选中对象按 X / Delete Hierarchy，不经过本文件的算子）：
  ① 干净移除同样成立——attribute/entry 是父子对象树，Blender 自己的递归删除即可；
     action/extern/subselect 是 root 下的平级对象，直接删除即可。
  ② efx_index 不会被重排（会留空洞），但 io_tree.py 收集同级时只把它当排序 key，
     不要求连续，空洞不影响导出正确性。
  ③ 本文件算子显式置的 dirty 标志会被跳过（原生删除根本不知道有这几个自定义
     属性）——但 io_tree.py §4d 独立做了结构变化自动检测（对比 hdr_count_* 这些
     只在导入时写一次的"原始计数"和当前实际对象数），只要数量对不上就自动强制
     走重建路径，不依赖任何删除算子有没有主动置位。三个 dirty 属性现在是
     "算子显式置位 OR 自动检测" 里的第一项，冗余但无害，继续保留。
  ④ 唯一的例外是删 entry 时不删子属性（普通 Delete 而非 Delete Hierarchy）：
     子属性会变成 parent=None 的孤儿对象，io_tree.py 按 parent 关系逐 entry 收集
     子属性，孤儿不属于任何 entry，从此在导出里彻底不可见（不报错，也不会被
     误挂到别的 entry 下）——是预期行为，不是 bug。

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集
  - 不改 efx_format/
  - bl_options = {"REGISTER", "UNDO"}
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


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _nn(idx: int) -> str:
    """零填充 2 位序号（>99 不填充），与 io_tree.py / reorder.py 命名规则一致。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _reindex_siblings(parent_obj, type_tag: str, rebuild_name_fn) -> int:
    """
    收集 parent_obj 下 type_tag 类型的剩余同级（已按 efx_index 排序），
    重新赋 efx_index = 0,1,2,... 并用 rebuild_name_fn(obj, new_idx) 重建显示名。

    parent_obj 是顶层文件集合（Collection，entry/action/extern/subselect 场景）时走
    集合归属收集；是 EFX_ENTRY 对象（attribute 场景）时走原 parent 收集（不受本次
    ROOT 集合化影响）。

    返回剩余数量。
    """
    if isinstance(parent_obj, bpy.types.Collection):
        siblings = _rc.collect_top_level(parent_obj, type_tag)
    else:
        siblings = _collect_siblings_by_type(parent_obj, type_tag)
    for new_idx, o in enumerate(siblings):
        o["efx_index"] = new_idx
        o.name = rebuild_name_fn(o, new_idx)
    return len(siblings)


# ─────────────────────────────────────────────────────────────────────────────
# 重建显示名回调（各类型）
# ─────────────────────────────────────────────────────────────────────────────

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
    # io_tree 导入命名："{nn} subselect_{i}"。subselect 对象无 efx_raw_label，
    # 用 subselect_{new_idx} 维持原命名风格。
    return f"{_nn(new_idx)} subselect_{new_idx}"


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_entry
# ─────────────────────────────────────────────────────────────────────────────

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

        # 收集选中的同 root 下所有 EFX_ENTRY；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ENTRY" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        # 批量删除（先删子属性再删 entry 本身）
        for obj in targets:
            children = [
                c for c in bpy.data.objects
                if c.parent == obj and c.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML")
            ]
            for child in children:
                bpy.data.objects.remove(child, do_unlink=True)
            bpy.data.objects.remove(obj, do_unlink=True)

        # 统一重排剩余 entry
        remaining = _reindex_siblings(root, "EFX_ENTRY", _rebuild_entry_name)

        # entry 计数变 → 标签表变；导出端按 labels_dirty 重建 label_bytes/label_size
        root["labels_dirty"] = 1
        # eof 载体是集合归属（Direct Trigger 嵌套子集合），entry 对象被删除即自动
        # 从其所在集合消失，不再需要额外 dirty 标志触发陈旧索引清理。

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ENTRY(s), {remaining} entry(s) remaining",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_attribute
# ─────────────────────────────────────────────────────────────────────────────

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
        # 收集选中的所有 EFX_ATTRIBUTE（跨 entry 均可）；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ATTRIBUTE"
            and o.parent is not None
            and o.parent.get("~TYPE") == "EFX_ENTRY"
        ]
        if not targets:
            targets = [context.active_object]

        # 记录受影响的 entry（删完后各自重排一次）
        affected_bodies = {o.parent for o in targets}

        # 属性不在标签表，不设 labels_dirty；attr_count 由导出端自动重算。
        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        # 对每个受影响的 entry 统一重排 + 重建 entry 自身显示名（渲染主体后缀可能变化）
        for body in affected_bodies:
            _reindex_siblings(body, "EFX_ATTRIBUTE", _rebuild_attribute_name)
            body.name = _rebuild_entry_name(body, int(body.get("efx_index", 0)))

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ATTRIBUTE(s) across {len(affected_bodies)} entry(s)",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_action
# ─────────────────────────────────────────────────────────────────────────────

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

        # 收集选中的同 root 下所有 EFX_ACTION；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_ACTION" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_ACTION", _rebuild_action_name)

        # action 计数变 → 标签表变
        root["labels_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_ACTION(s), {remaining} action(s) remaining",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_extern
# ─────────────────────────────────────────────────────────────────────────────

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

        # 收集选中的同 root 下所有 EFX_EXTERN；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_EXTERN" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        # ⚠ Extern 多对一：被多个 EXTERNREFERENCE 属性引用的对象删除后，
        # 这些属性的 extern_ref_ptr 变 None（悬空）——这是预期行为，由 #4 校验报告。
        # 删除算子不主动清理引用。
        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_EXTERN", _rebuild_extern_name)

        # extern 计数变 → 标签表变
        root["labels_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_EXTERN(s), {remaining} extern(s) remaining",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_subselect
# ─────────────────────────────────────────────────────────────────────────────

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

        # 收集选中的同 root 下所有 EFX_SUBSELECT；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_SUBSELECT" and _rc.find_root_collection(o) is root
        ]
        if not targets:
            targets = [active]

        # subselect 不在标签表，不设 labels_dirty；
        # 但 subselect 段字节变 → subselect_size 要重算 → 置 subselect_dirty。
        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        remaining = _reindex_siblings(root, "EFX_SUBSELECT", _rebuild_subselect_name)

        root["subselect_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_SUBSELECT(s), {remaining} subselect(s) remaining",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

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
