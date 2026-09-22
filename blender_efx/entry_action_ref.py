"""PTLIFE/PTCOLLISION 的 Action 引用及 EOF 直接触发集合。

维护约束：
- PTLIFE relationIndex（偏移 8，int16）和 PTCOLLISION ieIndex（偏移 96，int32）
  都是 Action 段局部索引；无效或未解析目标导出为 -1。
- Action 指针只允许同一 EFX 根内的对象。
- EOF 在导入时规范为唯一、升序、范围内的 Entry 索引集合，并由 Direct Trigger / Not
  Direct Trigger 两个嵌套集合表达。Entry 与其属性、TIML 子对象必须整体移动。
- 既不在两个 EOF 子集合中的 Entry 导出为直接触发；旧 opaque 模型仅原样回退。
"""

import struct
import bpy
from bpy.props import (
    BoolProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup

from .subselect import build_local_index_map
from .i18n import T
from . import root_collection as _rc


_RELATION_INDEX_OFFSET = 8
_IE_INDEX_OFFSET = 96
_SENTINEL_INT32 = -1


def _same_root_as_active(obj):
    """仅在两个对象都属于不同根时拒绝。"""
    editing = getattr(bpy.context, "active_object", None)
    if editing is None:
        return True
    return _rc.same_root(editing, obj)


def _action_object_poll(self, obj):
    """仅允许选择同一 EFX 根内的 Action。"""
    return obj.get("~TYPE") == "EFX_ACTION" and _same_root_as_active(obj)


class EFXPtLifeRefProps(PropertyGroup):
    """PTLIFE 的可空 Action 指针；空值导出为 -1。"""

    relation_play_ptr: PointerProperty(
        name="Relation Action",
        description="The EFX_ACTION (action) object this PtLife attribute's relationIndex points to (action section local index = actionID). Empty = no target, writes -1 on export",
        type=bpy.types.Object,
        poll=_action_object_poll,
    )


def init_ptlife_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    play_objs_by_index: dict,
    count_play: int,
) -> None:
    """从有效 Action 段索引初始化 PTLIFE 指针。"""
    props = blk_obj.efx_ptlife_ref
    if len(data_bytes) < 10:
        return
    v = struct.unpack_from('<h', data_bytes, _RELATION_INDEX_OFFSET)[0]
    if count_play > 0 and 0 <= v < count_play:
        target_obj = play_objs_by_index.get(v)
        if target_obj is not None:
            props.relation_play_ptr = target_obj


def overlay_ptlife_relation_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """以 PTLIFE 指针覆写 Action 索引；无目标写 -1。"""
    if len(data_bytes) < 10:
        return data_bytes
    try:
        play_obj = blk_obj.efx_ptlife_ref.relation_play_ptr
    except AttributeError:
        play_obj = None
    new_index = play_index_map.get(play_obj) if play_obj is not None else None
    if new_index is None:
        new_index = -1
    buf = bytearray(data_bytes)
    struct.pack_into('<h', buf, _RELATION_INDEX_OFFSET, new_index)
    return bytes(buf)


class EFXPtCollisionRefProps(PropertyGroup):
    """挂在 EFX_ATTRIBUTE（PTCOLLISION 类型）对象上（obj.efx_ptcollision_ref）。

    ie_play_ptr : PointerProperty → EFX_ACTION 对象（poll=EFX_ACTION）。
                  None = 无目标（导出写 -1）。
    """

    ie_play_ptr: PointerProperty(
        name="IE Action",
        description="The EFX_ACTION object this PtCollision attribute's ieIndex points to (action section local index). Empty = no target, writes -1 on export",
        type=bpy.types.Object,
        poll=_action_object_poll,
    )


def init_ptcollision_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    play_objs_by_index: dict,
    count_play: int,
) -> None:
    """从有效 Action 段索引初始化 PTCOLLISION 指针。"""
    props = blk_obj.efx_ptcollision_ref
    if len(data_bytes) < 100:
        return
    v = struct.unpack_from('<i', data_bytes, _IE_INDEX_OFFSET)[0]
    if count_play > 0 and 0 <= v < count_play:
        target_obj = play_objs_by_index.get(v)
        if target_obj is not None:
            props.ie_play_ptr = target_obj


def overlay_ptcollision_ie_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """以 PTCOLLISION 指针覆写 Action 索引；无目标写 -1。"""
    if len(data_bytes) < 100:
        return data_bytes
    try:
        play_obj = blk_obj.efx_ptcollision_ref.ie_play_ptr
    except AttributeError:
        play_obj = None
    new_index = play_index_map.get(play_obj) if play_obj is not None else None
    if new_index is None:
        new_index = _SENTINEL_INT32
    buf = bytearray(data_bytes)
    struct.pack_into('<i', buf, _IE_INDEX_OFFSET, new_index)
    return bytes(buf)


def normalize_eof_ints(eof_ints: list, count_body: int):
    """返回范围内、去重且升序的 EOF 索引，以及被丢弃和重排状态。"""
    keep = []
    dropped = []
    seen = set()
    for v in eof_ints:
        v = int(v)
        if not (0 <= v < count_body) or v in seen:
            dropped.append(v)
            continue
        seen.add(v)
        keep.append(v)
    return sorted(keep), dropped, keep != sorted(keep)


def _entry_subtree_objects(entry_obj: bpy.types.Object, children_by_parent: dict = None) -> list:
    """返回 Entry 及其直属属性、TIML；批量调用可复用 parent 映射。"""
    if children_by_parent is not None:
        return [entry_obj] + children_by_parent.get(entry_obj, [])
    out = [entry_obj]
    for o in bpy.data.objects:
        if o.parent == entry_obj and o.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML"):
            out.append(o)
    return out


def _build_children_by_parent() -> dict:
    """构建供批量 Entry 子树迁移复用的 parent 映射。"""
    out = {}
    for o in bpy.data.objects:
        p = o.parent
        if p is not None and o.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML"):
            out.setdefault(p, []).append(o)
    return out


def _move_entry_subtree(entry_obj: bpy.types.Object, src_cols, dst_col,
                         children_by_parent: dict = None) -> None:
    """将 Entry 子树从所有候选源集合迁移至目标集合。"""
    if isinstance(src_cols, bpy.types.Collection) or src_cols is None:
        src_cols = (src_cols,)
    for member in _entry_subtree_objects(entry_obj, children_by_parent):
        for sc in src_cols:
            if sc is not None and sc in member.users_collection:
                sc.objects.unlink(member)
        if dst_col is not None and dst_col not in member.users_collection:
            dst_col.objects.link(member)


def init_eof_per_entry(
    root_obj: bpy.types.Object,
    eof_ints: list,
    main_bodies_by_index: dict,
    count_body: int,
) -> None:
    """规范 EOF 索引并将全部 Entry 子树分流到两个直接触发集合。"""
    active_sorted, dropped, reordered = normalize_eof_ints(eof_ints, count_body)

    root_obj["eof_model"] = "per_entry"
    if dropped:
        root_obj["eof_dropped"] = ",".join(str(v) for v in dropped)
    elif "eof_dropped" in root_obj:
        del root_obj["eof_dropped"]
    if reordered:
        root_obj["eof_reordered"] = 1
    elif "eof_reordered" in root_obj:
        del root_obj["eof_reordered"]

    active = set(active_sorted)

    entry_col = _rc.get_leaf_collection(root_obj, "EFX_ENTRY")
    if entry_col is None:
        return
    dt_col = _rc.ensure_direct_trigger_collection(root_obj)
    ndt_col = _rc.ensure_not_direct_trigger_collection(root_obj)
    if dt_col is None or ndt_col is None:
        return

    children_by_parent = _build_children_by_parent()
    for idx, obj in main_bodies_by_index.items():
        dst = dt_col if idx in active else ndt_col
        _move_entry_subtree(obj, entry_col, dst, children_by_parent)


def export_eof_per_entry(root_obj: bpy.types.Object, entry_index_map: dict) -> list:
    """按集合归属导出 EOF 索引；孤儿 Entry 按直接触发处理。"""
    model = str(root_obj.get("eof_model", ""))
    if model == "per_entry":
        dt_col = _rc.get_direct_trigger_collection(root_obj)
        ndt_col = _rc.get_not_direct_trigger_collection(root_obj)
        out = []
        for obj, idx in entry_index_map.items():
            in_dt = dt_col is not None and dt_col in obj.users_collection
            in_ndt = ndt_col is not None and ndt_col in obj.users_collection
            if in_dt or not in_ndt:
                out.append(idx)
        return sorted(out)
    if model == "opaque":
        return _fallback_eof_ints(root_obj)
    return []


def _fallback_eof_ints(root_obj: bpy.types.Object) -> list:
    """还原 opaque 旧模型保存的 EOF 索引。"""
    try:
        s = str(root_obj["eof_ints"]).strip()
        return [int(x) for x in s.split(",") if x] if s else []
    except (KeyError, ValueError, TypeError):
        return []


def apply_attribute_ref_overlays(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    entry_index_map: dict,
    play_index_map: dict,
) -> bytes:
    """为 PTLIFE/PTCOLLISION 应用 Action 索引覆写，其余类型原样返回。"""
    try:
        from ..efx_format.hashes import PTLIFE as _PTLIFE_HASH, PTCOLLISION as _PTCOLLISION_HASH
        bp = blk_obj.efx_block
        type_hash = int(bp.type_hash_str)
    except Exception:
        return data_bytes

    if type_hash == _PTLIFE_HASH:
        return overlay_ptlife_relation_index(data_bytes, blk_obj, play_index_map)
    if type_hash == _PTCOLLISION_HASH:
        return overlay_ptcollision_ie_index(data_bytes, blk_obj, play_index_map)
    return data_bytes


class EFX_OT_eof_toggle_entry(bpy.types.Operator):
    """Toggle whether the current EFX_ENTRY is in the root file's eof active list"""

    bl_idname      = "efx.eof_toggle_entry"
    bl_label       = "Toggle Direct Trigger"
    bl_description = "Add/remove this Entry to/from the direct-trigger (EOF) list. Direct-trigger entries fire with the EFX unless gated by a subselect state; entries absent here can still be summoned by Action calls"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            return False
        return _rc.find_root_collection(obj) is not None

    def execute(self, context):
        entry_obj = context.active_object
        root = _rc.find_root_collection(entry_obj)

        # opaque 模型没有可编辑的集合归属。
        if str(root.get("eof_model", "")) == "opaque":
            self.report({"WARNING"},
                        "This EFX was imported by an older plugin version with a read-only "
                        "EOF section. Re-import the .efx to enable trigger editing")
            return {"CANCELLED"}

        # 源集合覆盖正常和孤儿位置，迁移后恢复唯一归属。
        entry_col = _rc.get_leaf_collection(root, "EFX_ENTRY")
        dt_col = _rc.ensure_direct_trigger_collection(root)
        ndt_col = _rc.ensure_not_direct_trigger_collection(root)
        in_dt = dt_col in entry_obj.users_collection
        in_ndt = ndt_col in entry_obj.users_collection
        currently_triggered = in_dt or not in_ndt

        dst = ndt_col if currently_triggered else dt_col
        _move_entry_subtree(entry_obj, (entry_col, dt_col, ndt_col), dst)

        self.report({"INFO"},
                    f"{'Removed' if currently_triggered else 'Added'} {entry_obj.name} "
                    f"{'from' if currently_triggered else 'to'} direct-trigger set")
        return {"FINISHED"}


def is_entry_in_eof(entry_obj: bpy.types.Object) -> bool:
    """按 EOF fail-safe 规则判断 Entry 是否直接触发。"""
    root = _rc.find_root_collection(entry_obj) if entry_obj else None
    if root is None:
        return False
    if str(root.get("eof_model", "")) != "per_entry":
        return False
    dt_col = _rc.get_direct_trigger_collection(root)
    ndt_col = _rc.get_not_direct_trigger_collection(root)
    in_dt = dt_col is not None and dt_col in entry_obj.users_collection
    in_ndt = ndt_col is not None and ndt_col in entry_obj.users_collection
    return in_dt or not in_ndt


def place_new_entry(root_obj: bpy.types.Object, entry_obj: bpy.types.Object, in_eof: bool) -> None:
    """将新建或粘贴的 Entry 放入对应的 EOF 子集合。"""
    model = str(root_obj.get("eof_model", ""))
    if model != "per_entry":
        return
    entry_col = _rc.get_leaf_collection(root_obj, "EFX_ENTRY")
    dst = (_rc.ensure_direct_trigger_collection(root_obj) if in_eof
           else _rc.ensure_not_direct_trigger_collection(root_obj))
    if dst is None:
        return
    _move_entry_subtree(entry_obj, entry_col, dst)


class EFX_PT_eof_list(bpy.types.Panel):
    """直接触发 Entry 的只读总览。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Direct Trigger List"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        col = context.collection
        return _rc.is_root_collection(col) and not _rc.root_is_color_editor_mode(col)

    def draw(self, context):
        layout = self.layout
        root = context.collection
        model = str(root.get("eof_model", ""))

        if model == "opaque":
            box = layout.box()
            box.label(text="EOF imported as read-only by an older version", icon="INFO")
            box.label(text="Re-import the .efx to enable trigger editing")
            return

        _dropped = str(root.get("eof_dropped", ""))
        if _dropped or root.get("eof_reordered", 0):
            box = layout.box()
            if _dropped:
                box.label(text="Repaired invalid EOF indices: " + _dropped, icon="ERROR")
            if root.get("eof_reordered", 0):
                box.label(text="EOF order normalized to ascending", icon="INFO")

        entries = _rc.collect_top_level(root, "EFX_ENTRY")
        triggered = [e for e in entries if is_entry_in_eof(e)]
        layout.label(text=T("ptref.game_activated_entries") + f"({len(triggered)})", icon="SORTBYEXT")

        if not triggered:
            layout.label(text=T("ptref.eof_empty"), icon="INFO")
            return

        col = layout.column(align=True)
        for e in triggered:
            row = col.row(align=True)
            row.scale_y = 0.85
            row.label(text=f"[{e.get('efx_index', '?')}] {e.name}", icon="OBJECT_DATA")
            op = row.operator("efx.select_object", text="", icon="VIEWZOOM")
            op.target_name = e.name

        hint = layout.row()
        hint.enabled = False
        hint.label(text=T("ptref.eof_edit_hint"))


_CLASSES_CORE = (
    EFXPtLifeRefProps,
    EFXPtCollisionRefProps,
)

_OPERATOR_CLASSES = (
    EFX_OT_eof_toggle_entry,
)

_PANEL_CLASSES = (
    EFX_PT_eof_list,
)


def register():
    """注册引用 PropertyGroup 并挂接到 Object。"""
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_ptlife_ref = PointerProperty(
        name="EFX PtLife Reference Properties",
        description="relationIndex action pointer data for EFX_ATTRIBUTE (PTLIFE type)",
        type=EFXPtLifeRefProps,
    )

    bpy.types.Object.efx_ptcollision_ref = PointerProperty(
        name="EFX PtCollision Reference Properties",
        description="ieIndex action pointer data for EFX_ATTRIBUTE (PTCOLLISION type)",
        type=EFXPtCollisionRefProps,
    )


def unregister():
    """移除 Object 属性并注销引用 PropertyGroup。"""
    for attr in ("efx_ptlife_ref", "efx_ptcollision_ref"):
        try:
            delattr(bpy.types.Object, attr)
        except AttributeError:
            pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
