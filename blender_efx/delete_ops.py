"""
blender_efx/delete_ops.py  —  L2 #3b：删除条目（body / 块 / play / extern / subselect）

算子（全部 bl_options={"REGISTER","UNDO"}，invoke 用 invoke_confirm 弹确认）：
  efx.delete_body      —  删除选中 EFX_BODY（连带其全部 EFX_BLOCK 子块）
  efx.delete_block     —  删除选中 EFX_BLOCK
  efx.delete_play      —  删除选中 EFX_PLAY
  efx.delete_extern    —  删除选中 EFX_EXTERN
  efx.delete_subselect —  删除选中 EFX_SUBSELECT

设计要点（参照 CLAUDE.md / reorder.py）：
  1. 删除职责只有三件：
       ① 干净移除对象（body 连带块）；
       ② 剩余同级重新连续编号（efx_index 0..n-1）+ 重建显示名；
       ③ 置 dirty 标志（labels_dirty / subselect_dirty），供导出端重算计数/标签/size。
  2. 引用是对象指针，删除后悬空指针（None）由导出端安全跳过、由 #4 校验报告。
     删除算子不主动清理引用（Extern 多对一，清理需用户决策）。
  3. 计数/size/eof 由 io_tree 导出端从实际内容重算，删除算子无需触碰头部数据。

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集
  - 不改 efx_format/，不改 io_tree.py
  - bl_options = {"REGISTER", "UNDO"}
"""

import bpy

from .reorder import (
    _collect_siblings_by_type,
    _body_display_name,
    _block_display_name,
    _get_body_raw_label,
    _get_block_type_name,
    _get_block_parent_label,
)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _nn(idx: int) -> str:
    """零填充 2 位序号（>99 不填充），与 io_tree.py / reorder.py 命名规则一致。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _find_root(obj):
    """沿 parent 链向上找 ~TYPE == 'EFX_ROOT' 的对象，找不到返回 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _reindex_siblings(parent_obj, type_tag: str, rebuild_name_fn) -> int:
    """
    收集 parent_obj 下 type_tag 类型的剩余同级（已按 efx_index 排序），
    重新赋 efx_index = 0,1,2,... 并用 rebuild_name_fn(obj, new_idx) 重建显示名。

    返回剩余数量。
    """
    siblings = _collect_siblings_by_type(parent_obj, type_tag)
    for new_idx, o in enumerate(siblings):
        o["efx_index"] = new_idx
        o.name = rebuild_name_fn(o, new_idx)
    return len(siblings)


def _delete_and_reindex(obj, parent, type_tag: str, is_body: bool,
                        rebuild_name_fn) -> int:
    """
    通用删除流程：
      1. 若是 EFX_BODY：先递归删除其全部 EFX_BLOCK 子对象。
      2. 删除 obj 本身。
      3. 重排剩余同级（重赋 efx_index + 重建显示名）。

    参数
    ----
    obj            : 待删除对象。
    parent         : obj 的父对象（root 或 body），用于收集剩余同级。
    type_tag       : obj 的 ~TYPE（用于收集同级）。
    is_body        : True 时先删子块。
    rebuild_name_fn: fn(o, new_idx) -> str，重建剩余同级显示名。

    返回
    ----
    int — 重排后剩余同级数量。
    """
    # ── 1. body：先递归删子块 ───────────────────────────────────────────────
    if is_body:
        children = [
            c for c in bpy.data.objects
            if c.parent == obj and c.get("~TYPE") == "EFX_BLOCK"
        ]
        for child in children:
            bpy.data.objects.remove(child, do_unlink=True)

    # ── 2. 删除 obj 本身 ─────────────────────────────────────────────────────
    bpy.data.objects.remove(obj, do_unlink=True)

    # ── 3. 重排剩余同级 ──────────────────────────────────────────────────────
    return _reindex_siblings(parent, type_tag, rebuild_name_fn)


# ─────────────────────────────────────────────────────────────────────────────
# 重建显示名回调（各类型）
# ─────────────────────────────────────────────────────────────────────────────

def _rebuild_body_name(o, new_idx):
    return _body_display_name(new_idx, _get_body_raw_label(o))


def _rebuild_block_name(o, new_idx):
    return _block_display_name(
        new_idx, _get_block_parent_label(o), _get_block_type_name(o)
    )


def _rebuild_play_name(o, new_idx):
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
# EFX_OT_delete_body
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_body(bpy.types.Operator):
    """删除所有选中的 EFX_BODY（连带各自全部 EFX_BLOCK 子块），重排剩余 body"""

    bl_idname      = "efx.delete_body"
    bl_label       = "Delete Body"
    bl_description = "Delete all selected EFX_BODY objects (including their blocks); remaining bodies are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_BODY"
            and obj.parent is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        active = context.active_object
        root = active.parent  # EFX_ROOT

        # 收集选中的同 root 下所有 EFX_BODY；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_BODY" and o.parent == root
        ]
        if not targets:
            targets = [active]

        # 批量删除（先删子块再删 body 本身）
        for obj in targets:
            children = [
                c for c in bpy.data.objects
                if c.parent == obj and c.get("~TYPE") in ("EFX_BLOCK", "EFX_TIML")
            ]
            for child in children:
                bpy.data.objects.remove(child, do_unlink=True)
            bpy.data.objects.remove(obj, do_unlink=True)

        # 统一重排剩余 body
        remaining = _reindex_siblings(root, "EFX_BODY", _rebuild_body_name)

        # body 计数变 → 标签表变；导出端按 labels_dirty 重建 label_bytes/label_size
        root["labels_dirty"] = 1
        # body 数变 → eof 里残留的越界 raw 哨兵成为陈旧错误索引，导出端 sanitize 清理
        # （取代旧的 eof_ints[:len(bodies)] 长度截断，能去掉列表中部的哨兵）
        root["eof_dirty"] = 1

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_BODY(s), {remaining} body(s) remaining",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_block
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_block(bpy.types.Operator):
    """删除所有选中的 EFX_BLOCK，重排各自所属 body 内剩余块"""

    bl_idname      = "efx.delete_block"
    bl_label       = "Delete Block"
    bl_description = "Delete all selected EFX_BLOCK objects; remaining blocks in each affected body are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
            return False
        parent = obj.parent
        return parent is not None and parent.get("~TYPE") == "EFX_BODY"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        # 收集选中的所有 EFX_BLOCK（跨 body 均可）；未多选时退化为只删 active
        targets = [
            o for o in context.selected_objects
            if o.get("~TYPE") == "EFX_BLOCK"
            and o.parent is not None
            and o.parent.get("~TYPE") == "EFX_BODY"
        ]
        if not targets:
            targets = [context.active_object]

        # 记录受影响的 body（删完后各自重排一次）
        affected_bodies = {o.parent for o in targets}

        # 块不在标签表，不设 labels_dirty；attr_count 由导出端自动重算。
        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        # 对每个受影响的 body 统一重排
        for body in affected_bodies:
            _reindex_siblings(body, "EFX_BLOCK", _rebuild_block_name)

        self.report(
            {"INFO"},
            f"Deleted {len(targets)} EFX_BLOCK(s) across {len(affected_bodies)} body(s)",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_play
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_play(bpy.types.Operator):
    """删除选中的 EFX_PLAY，重排剩余 play"""

    bl_idname      = "efx.delete_play"
    bl_label       = "Delete Play"
    bl_description = "Delete the selected EFX_PLAY; remaining plays are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_PLAY"
            and obj.parent is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        root = obj.parent  # EFX_ROOT

        remaining = _delete_and_reindex(
            obj, root, "EFX_PLAY", is_body=False,
            rebuild_name_fn=_rebuild_play_name,
        )

        # play 计数变 → 标签表变
        root["labels_dirty"] = 1

        self.report({"INFO"}, f"Deleted EFX_PLAY, {remaining} play(s) remaining")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_extern
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_extern(bpy.types.Operator):
    """删除选中的 EFX_EXTERN，重排剩余 extern（被引用的块指针变悬空，由校验报告）"""

    bl_idname      = "efx.delete_extern"
    bl_label       = "Delete Extern"
    bl_description = (
        "Delete the selected EFX_EXTERN; remaining externs are renumbered consecutively. "
        "Note: pointers referenced by ExternReference blocks will dangle (check with pre-export validation)"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_EXTERN"
            and obj.parent is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        root = obj.parent  # EFX_ROOT

        # ⚠ Extern 多对一：被多个 EXTERNREFERENCE 块引用的对象删除后，
        # 这些块的 extern_ref_ptr 变 None（悬空）——这是预期行为，由 #4 校验报告。
        # 删除算子不主动清理引用。
        remaining = _delete_and_reindex(
            obj, root, "EFX_EXTERN", is_body=False,
            rebuild_name_fn=_rebuild_extern_name,
        )

        # extern 计数变 → 标签表变
        root["labels_dirty"] = 1

        self.report({"INFO"}, f"Deleted EFX_EXTERN, {remaining} extern(s) remaining")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# EFX_OT_delete_subselect
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_subselect(bpy.types.Operator):
    """删除选中的 EFX_SUBSELECT，重排剩余 subselect"""

    bl_idname      = "efx.delete_subselect"
    bl_label       = "Delete Subselect"
    bl_description = "Delete the selected EFX_SUBSELECT; remaining subselects are renumbered consecutively"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.get("~TYPE") == "EFX_SUBSELECT"
            and obj.parent is not None
        )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        root = obj.parent  # EFX_ROOT

        # subselect 不在标签表，不设 labels_dirty；
        # 但 subselect 段字节变 → subselect_size 要重算 → 置 subselect_dirty。
        remaining = _delete_and_reindex(
            obj, root, "EFX_SUBSELECT", is_body=False,
            rebuild_name_fn=_rebuild_subselect_name,
        )

        root["subselect_dirty"] = 1

        self.report({"INFO"}, f"Deleted EFX_SUBSELECT, {remaining} subselect(s) remaining")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_delete_body,
    EFX_OT_delete_block,
    EFX_OT_delete_play,
    EFX_OT_delete_extern,
    EFX_OT_delete_subselect,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
