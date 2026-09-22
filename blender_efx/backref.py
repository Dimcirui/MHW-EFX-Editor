"""同一 EFX 树内的只读引用导航与 Entry 激活状态摘要。

维护约束：
- 扫描必须限定在对象所属的根集合，不能跨 EFX 文件匹配引用。
- 面板和跳转算子不修改引用数据或导出状态。
- 激活状态仅根据 EOF、Action 和 Subselect 的可见关系归类；运行时状态选择不在此推断。
"""

import base64
import struct

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# §1  同树范围 helper
# ─────────────────────────────────────────────────────────────────────────────

def _find_root_collection(obj: bpy.types.Object):
    """返回对象所属的 EFX 根集合。"""
    return _rc.find_root_collection(obj)


def _collect_all_from_collection(col, out_by_type: dict) -> None:
    """递归收集集合内对象，并按 ~TYPE 分类。"""
    for obj in col.objects:
        t = obj.get("~TYPE")
        if t:
            if t not in out_by_type:
                out_by_type[t] = []
            out_by_type[t].append(obj)
    for child in col.children:
        _collect_all_from_collection(child, out_by_type)


def get_efx_tree_objects(obj) -> dict:
    """返回对象或根集合所在 EFX 树的 ~TYPE 分组；无法定位根时为空。"""
    if isinstance(obj, bpy.types.Collection):
        root_col = obj if _rc.is_root_collection(obj) else None
    else:
        root_col = _find_root_collection(obj)
    if root_col is None:
        return {}
    out = {}
    _collect_all_from_collection(root_col, out)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# §2  跳转算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_select_object(Operator):
    """唯一选中并激活反向引用列表中的目标对象。"""

    bl_idname      = "efx.select_object"
    bl_label       = "Jump to Object"
    bl_description = "Clear current selection, select and activate the target EFX object"
    bl_options     = {"REGISTER"}

    target_name: StringProperty(
        name="Target Object Name",
        description="Name of the Blender object to select",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        target_name = self.target_name
        if not target_name:
            self.report({"WARNING"}, "target_name is empty, cannot jump")
            return {"CANCELLED"}

        target_obj = bpy.data.objects.get(target_name)
        if target_obj is None:
            self.report({"WARNING"}, f"Object not found: {target_name}")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")
        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §3  Extern 对象反向视图
# ─────────────────────────────────────────────────────────────────────────────

def _scan_extern_backrefs(extern_obj: bpy.types.Object) -> list:
    """返回同树内指向该 Extern 的 EXTERNREFERENCE 属性。"""
    results = []

    tree = get_efx_tree_objects(extern_obj)
    block_objs = tree.get("EFX_ATTRIBUTE", [])

    try:
        from ..efx_format.hashes import EXTERNREFERENCE
    except ImportError:
        return results

    for blk in block_objs:
        try:
            bp = blk.efx_block
            if int(bp.type_hash_str) != EXTERNREFERENCE:
                continue
        except (AttributeError, ValueError):
            continue

        try:
            ref_props = blk.efx_extern_ref
            if not ref_props.extern_ref_pointerized:
                continue
            if ref_props.extern_ref_none:
                continue
            if ref_props.extern_ref_ptr is not extern_obj:
                continue
        except AttributeError:
            continue

        body_name = ""
        if blk.parent is not None:
            body_name = blk.parent.name

        results.append({
            "block_obj": blk,
            "block_name": blk.name,
            "body_name": body_name,
        })

    return results


class EFX_PT_extern_backref(bpy.types.Panel):
    """显示指向当前 Extern 的属性，并提供跳转。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Extern Referenced By"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def draw(self, context):
        layout = self.layout
        extern_obj = context.active_object

        info_box = layout.box()
        ext_idx = extern_obj.get("efx_index", "?")
        info_row = info_box.row()
        info_row.label(
            text=T("backref.extern_object") + f" {extern_obj.name}  (index {ext_idx})",
            icon="LINKED",
        )

        layout.separator()

        refs = _scan_extern_backrefs(extern_obj)

        header_row = layout.row()
        if refs:
            header_row.label(
                text=T("backref.referenced_by_n_prefix") + f" {len(refs)} " + T("backref.referenced_by_n_suffix"),
                icon="RESTRICT_SELECT_OFF",
            )
        else:
            header_row.label(
                text=T("backref.not_referenced_by_extern"),
                icon="INFO",
            )
            return

        for ref in refs:
            ref_box = layout.box()
            col = ref_box.column(align=True)

            row_name = col.row(align=True)
            row_name.label(text=T("backref.attribute") + f" {ref['block_name']}", icon="MODIFIER")

            row_entry = col.row(align=True)
            if ref["body_name"]:
                row_entry.label(
                    text=T("backref.entry") + f" {ref['body_name']}",
                    icon="OBJECT_DATA",
                )
            else:
                row_entry.label(text=T("backref.entry_unknown"), icon="QUESTION")

            row_jump = col.row(align=True)
            op = row_jump.operator(
                "efx.select_object",
                text=T("backref.jump_to_attribute"),
                icon="VIEWZOOM",
            )
            op.target_name = ref["block_name"]


# ─────────────────────────────────────────────────────────────────────────────
# §4  Entry 关系视图
# ─────────────────────────────────────────────────────────────────────────────

# PTLIFE timing 的 short 字段偏移。
_PTLIFE_TIMING_OFFSET = 4


def _attribute_type_hash(blk) -> int:
    """读 EFX_ATTRIBUTE 的 type_hash（失败返回 -1）。"""
    try:
        return int(blk.efx_block.type_hash_str)
    except (AttributeError, ValueError, TypeError):
        return -1


def _read_ptlife_timing(blk):
    """读 PTLIFE 属性的 timing（short @ offset 4）；失败返回 None。"""
    try:
        raw = base64.b64decode(str(blk.efx_block.raw_b64))
        if len(raw) >= _PTLIFE_TIMING_OFFSET + 2:
            return struct.unpack_from("<h", raw, _PTLIFE_TIMING_OFFSET)[0]
    except Exception:
        pass
    return None


def _action_children(play_obj):
    """返回 play_obj 的子引用：(child_entry 对象列表, 外部 efx 路径列表)。"""
    children, paths = [], []
    try:
        props = play_obj.efx_play
    except AttributeError:
        return children, paths
    for entry in props.entries:
        if entry.is_emitter:
            for tgt in entry.targets:
                if tgt.body_ptr is not None:
                    children.append(tgt.body_ptr)
        else:
            p = str(entry.efx_path or "").strip()
            if p:
                paths.append(p)
    return children, paths


def is_entry_action_triggered(entry_obj: bpy.types.Object) -> bool:
    """True if any Action in the same EFX tree has entry_obj as a target."""
    tree = get_efx_tree_objects(entry_obj)
    for play in tree.get("EFX_ACTION", []):
        children, _ = _action_children(play)
        if entry_obj in children:
            return True
    return False


def count_entry_subselect_tables(entry_obj: bpy.types.Object) -> int:
    """返回该 Entry 在同树中出现的 Subselect 表数量。"""
    tree = get_efx_tree_objects(entry_obj)
    n = 0
    for ss_obj in tree.get("EFX_SUBSELECT", []):
        try:
            props = ss_obj.efx_subselect
        except AttributeError:
            continue
        for member in props.members:
            if member.body_ptr is entry_obj:
                n += 1
                break
    return n


def classify_entry_activation(entry_obj: bpy.types.Object) -> dict:
    """汇总 EOF、Action 和 Subselect 的可见关系，供 UI 状态提示使用。

    返回的 gated 状态只表示 Entry 被某张 Subselect 表收录，不能推断运行时的状态选择。
    """
    from .entry_action_ref import is_entry_in_eof

    in_eof    = is_entry_in_eof(entry_obj)
    in_action = is_entry_action_triggered(entry_obj)
    n_tables  = count_entry_subselect_tables(entry_obj)

    if in_eof and in_action:
        source = "both"
    elif in_eof:
        source = "direct"
    elif in_action:
        source = "action"
    else:
        source = "none"

    return {
        "source": source,
        "gated": n_tables > 0,
        "n_tables": n_tables,
        "in_eof": in_eof,
        "in_action": in_action,
    }


def _scan_entry_relations(entry_obj: bpy.types.Object) -> dict:
    """扫描 Entry 的触发、被触发、Extern 和 Subselect 关系。"""
    from ..efx_format.hashes import PTLIFE, PTCOLLISION, EXTERNREFERENCE

    tree = get_efx_tree_objects(entry_obj)
    attrs   = tree.get("EFX_ATTRIBUTE", [])
    plays   = tree.get("EFX_ACTION", [])
    result  = {"triggers": [], "triggered_by": [], "externs": [], "subselects": []}

    my_attributes = [b for b in attrs if b.parent is entry_obj]

    def _ptlife_action(blk):
        """PTLIFE 属性 → 触发的 action 对象（None = 无目标）。"""
        try:
            return blk.efx_ptlife_ref.relation_play_ptr
        except AttributeError:
            return None

    def _ptcollision_action(blk):
        """PTCOLLISION 属性 → 触发的 action 对象（None = 无目标）。"""
        try:
            return blk.efx_ptcollision_ref.ie_play_ptr
        except AttributeError:
            return None

    # (type hash, relation label, action resolver, timing resolver)
    _TRIGGER_KINDS = (
        (PTLIFE,      "ptlife",      _ptlife_action,      _read_ptlife_timing),
        (PTCOLLISION, "ptcollision", _ptcollision_action, lambda _blk: None),
    )

    for blk in my_attributes:
        th = _attribute_type_hash(blk)
        for type_hash, kind, get_action, get_timing in _TRIGGER_KINDS:
            if th != type_hash:
                continue
            play = get_action(blk)
            if play is None:
                continue
            children, paths = _action_children(play)
            result["triggers"].append({
                "play_obj": play,
                "play_name": play.name,
                "kind": kind,
                "timing": get_timing(blk),
                "children": children,
                "paths": paths,
            })

    plays_targeting_me = set()
    for play in plays:
        children, _ = _action_children(play)
        if entry_obj in children:
            plays_targeting_me.add(play)
    if plays_targeting_me:
        for blk in attrs:
            if blk.parent is None or blk.parent is entry_obj:
                continue
            th = _attribute_type_hash(blk)
            for type_hash, kind, get_action, get_timing in _TRIGGER_KINDS:
                if th != type_hash:
                    continue
                play = get_action(blk)
                if play in plays_targeting_me:
                    result["triggered_by"].append({
                        "entry_obj": blk.parent,
                        "body_name": blk.parent.name,
                        "play_obj": play,
                        "play_name": play.name,
                        "kind": kind,
                        "timing": get_timing(blk),
                    })

    for blk in my_attributes:
        if _attribute_type_hash(blk) != EXTERNREFERENCE:
            continue
        try:
            er = blk.efx_extern_ref
            if not er.extern_ref_pointerized or er.extern_ref_none:
                continue
            ext = er.extern_ref_ptr
        except AttributeError:
            continue
        if ext is not None:
            result["externs"].append({
                "extern_obj": ext,
                "extern_name": ext.name,
                "block_name": blk.name,
            })

    for ss_obj in tree.get("EFX_SUBSELECT", []):
        try:
            props = ss_obj.efx_subselect
        except AttributeError:
            continue
        for member in props.members:
            if member.body_ptr is entry_obj:
                result["subselects"].append({
                    "ss_obj": ss_obj,
                    "ss_name": ss_obj.name,
                })
                break

    return result


def _timing_label(timing) -> str:
    """timing → 人类可读（生成/结束/原值）。"""
    if timing == 0:
        return T("entryref.timing_spawn")
    if timing == 4:
        return T("entryref.timing_death")
    return T("entryref.timing_other") + f"={timing}"


def _trigger_label(t) -> str:
    """触发条目 → 方括号内标签：PTCOLLISION 显示"碰撞时"，PTLIFE 按 timing。"""
    if t.get("kind") == "ptcollision":
        return T("entryref.trigger_collision")
    return _timing_label(t.get("timing"))


def _jump_button(row, target_name, text="", icon="VIEWZOOM"):
    op = row.operator("efx.select_object", text=text, icon=icon)
    op.target_name = target_name


class EFX_PT_entry_backref(bpy.types.Panel):
    """显示当前 Entry 的只读关系图，并提供跳转。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Entry References"
    bl_parent_id   = "EFX_PT_entry_status"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.get("~TYPE") == "EFX_ENTRY"
                and not _rc.is_color_editor_mode(obj))

    def draw(self, context):
        layout = self.layout
        entry_obj = context.active_object

        info_box = layout.box()
        body_idx = entry_obj.get("efx_index", "?")
        info_box.row().label(
            text=T("backref.entry_object") + f" {entry_obj.name}  (index {body_idx})",
            icon="OBJECT_DATA",
        )

        rel = _scan_entry_relations(entry_obj)
        triggers     = rel["triggers"]
        triggered_by = rel["triggered_by"]
        externs      = rel["externs"]
        subselects   = rel["subselects"]

        if not (triggers or triggered_by or externs or subselects):
            layout.label(text=T("entryref.none"), icon="INFO")
            return

        if triggers:
            box = layout.box()
            box.row().label(text=T("entryref.triggers_header"), icon="FORWARD")
            for t in triggers:
                row = box.row(align=True)
                row.label(text=f"{t['play_name']}  [{_trigger_label(t)}]", icon="PLAY")
                _jump_button(row, t["play_name"])
                sub = box.column(align=True)
                for child in t["children"]:
                    r = sub.row(align=True)
                    r.separator(factor=2.0)
                    r.label(text=child.name, icon="OBJECT_DATA")
                    _jump_button(r, child.name)
                for p in t["paths"]:
                    r = sub.row(align=True)
                    r.separator(factor=2.0)
                    r.label(text=p, icon="FILE_BLEND")

        if triggered_by:
            box = layout.box()
            box.row().label(text=T("entryref.triggered_by_header"), icon="BACK")
            for t in triggered_by:
                row = box.row(align=True)
                row.label(
                    text=f"{t['body_name']}  ({t['play_name']} [{_trigger_label(t)}])",
                    icon="OBJECT_DATA",
                )
                _jump_button(row, t["body_name"])

        if externs:
            box = layout.box()
            box.row().label(text=T("entryref.externs_header") + f" ({len(externs)})", icon="LINKED")
            for e in externs:
                row = box.row(align=True)
                row.label(text=e["extern_name"], icon="FILE_BLEND")
                _jump_button(row, e["extern_name"])

        if subselects:
            box = layout.box()
            box.row().label(text=T("entryref.subselect_header") + f" ({len(subselects)})", icon="OUTLINER_OB_EMPTY")
            for s in subselects:
                row = box.row(align=True)
                row.label(text=s["ss_name"], icon="MODIFIER")
                _jump_button(row, s["ss_name"])


# ─────────────────────────────────────────────────────────────────────────────
# §5  Root Subselect 总览
# ─────────────────────────────────────────────────────────────────────────────

def _table_members(ss_obj):
    """返回 subselect 表的成员 entry 对象列表（按 members 顺序，跳过悬空）。"""
    out = []
    try:
        props = ss_obj.efx_subselect
    except AttributeError:
        return out
    for m in props.members:
        if m.body_ptr is not None:
            out.append(m.body_ptr)
    return out


def _eof_direct_bodies(root_obj):
    """返回 Root 中直接触发的 Entry。"""
    from .entry_action_ref import is_entry_in_eof
    return [b for b in _rc.collect_top_level(root_obj, "EFX_ENTRY") if is_entry_in_eof(b)]


class EFX_PT_root_states(bpy.types.Panel):
    """显示 Subselect 成员及未被 Subselect 收录的直接触发 Entry。"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Subselect States"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        col = context.collection
        return _rc.is_root_collection(col) and not _rc.root_is_color_editor_mode(col)

    def draw(self, context):
        layout = self.layout
        root_obj = context.collection

        tree = get_efx_tree_objects(root_obj)
        ss_objs = tree.get("EFX_SUBSELECT", [])

        gated_bodies = set()
        if not ss_objs:
            layout.label(text=T("rootstate.no_states"), icon="INFO")
        else:
            layout.label(text=T("rootstate.header") + f" ({len(ss_objs)})", icon="PRESET")
            for i, ss in enumerate(ss_objs):
                members = _table_members(ss)
                gated_bodies.update(members)
                box = layout.box()
                hrow = box.row(align=True)
                hrow.label(text=f"{T('rootstate.state_prefix')} {i}: {ss.name}",
                           icon="OUTLINER_OB_EMPTY")
                _jump_button(hrow, ss.name)
                if not members:
                    box.label(text=T("rootstate.empty_table"), icon="DOT")
                for b in members:
                    r = box.row(align=True)
                    r.separator(factor=1.5)
                    bidx = b.get("efx_index", "?")
                    r.label(text=f"[{bidx}] {b.name}", icon="OBJECT_DATA")
                    _jump_button(r, b.name)

        always_on = [b for b in _eof_direct_bodies(root_obj) if b not in gated_bodies]
        box = layout.box()
        box.label(text=T("rootstate.always_on_header") + f" ({len(always_on)})",
                  icon="RADIOBUT_ON")
        if not always_on:
            box.label(text=T("rootstate.always_on_empty"), icon="DOT")
        for b in always_on:
            r = box.row(align=True)
            r.separator(factor=1.5)
            bidx = b.get("efx_index", "?")
            r.label(text=f"[{bidx}] {b.name}", icon="OBJECT_DATA")
            _jump_button(r, b.name)

        layout.label(text=T("rootstate.hint"), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 面板依赖父面板，须由 panels.py 在父面板之后注册。

_CLASSES_CORE = (
    EFX_OT_select_object,
)



def register():
    """注册 backref 核心类（算子）。面板由 panels.py 注册。"""
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)


def unregister():
    """注销 backref 核心类。面板由 panels.py 先注销。"""
    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
