"""
blender_efx/backref.py  —  L2 反向引用视图（只读）

功能概览
--------
1. ``get_efx_tree_objects(obj)``
   同树范围 helper：给场景中任意 EFX 对象，找到它所属的顶层 .efx 集合，
   再收集该集合下全部 EFX 对象（按 ~TYPE 分类），供反向扫描使用。

2. ``EFX_OT_select_object``（efx.select_object）
   跳转算子：StringProperty 传目标对象名，execute 里清除当前选择、
   选中目标对象并设为 active。供反向列表中的按钮调用。

3. ``EFX_PT_extern_backref``
   Extern 对象反向视图（VIEW_3D N 面板，poll: EFX_EXTERN）。
   扫描同一 EFX 树内所有 EFX_ATTRIBUTE，找出 type_hash==EXTERNREFERENCE
   且 efx_extern_ref.extern_ref_ptr == 当前 extern 的属性，
   显示"被 N 个属性引用"+ 每个属性（属性名 + 所属 entry 名）+ 跳转按钮。

4. ``EFX_PT_entry_backref``
   Entry 对象反向视图（VIEW_3D N 面板，poll: EFX_ENTRY）。
   扫描同一 EFX 树，列出引用该 entry 的：
     - Subselect 表（其 members 有指向该 entry 的）
     - Action emitter（其 entries[*].targets 有指向该 entry 的）
   分组显示 + 跳转按钮。

约束
----
- 纯只读显示：不修改任何引用数据、不碰导出路径、不改 efx_format/。
- Python 3.11 语法（目标 Blender 4.3.2）。
- bpy 稳定子集（Panel / Operator / StringProperty / layout.box 等）。
- 不使用 5.x 新增 API。
- 跳转算子不需要 UNDO（纯选择操作，不改场景数据）。
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
    """给任意 EFX 对象，O(1) 找到它所属的顶层 EFX 集合（委托 root_collection，
    2026-07 ROOT 集合化后的规范实现——反向指针，不再需要全场景按名字扫描）。"""
    return _rc.find_root_collection(obj)


def _collect_all_from_collection(col, out_by_type: dict) -> None:
    """
    递归收集集合及子集合内所有 EFX 对象，按 ~TYPE 分类存入 out_by_type。

    out_by_type : dict[str, list[bpy.types.Object]]
        key = ~TYPE 字符串（如 'EFX_ATTRIBUTE'），value = 对象列表（按收集顺序）
    """
    for obj in col.objects:
        t = obj.get("~TYPE")
        if t:
            if t not in out_by_type:
                out_by_type[t] = []
            out_by_type[t].append(obj)
    for child in col.children:
        _collect_all_from_collection(child, out_by_type)


def get_efx_tree_objects(obj) -> dict:
    """
    给任意 EFX 对象**或**顶层文件集合本身，返回同一 EFX 树内按 ~TYPE 分类的全部对象。

    返回
    ----
    dict[str, list[bpy.types.Object]]
        key = ~TYPE 字符串（如 'EFX_ATTRIBUTE'、'EFX_ENTRY' 等）
        value = 该类型的对象列表

    若无法确定树根，返回空 dict（防御性）。

    用途
    ----
    反向扫描只在同树内进行，避免多个导入的 EFX 文件之间混淆。
    """
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
    """
    跳转并选中目标 EFX 对象（反向引用列表专用）。

    将目标对象设为 active 并唯一选中，方便在视口中定位。
    纯选择操作，不修改任何场景数据，不在 UNDO 历史中留记录。
    """

    bl_idname      = "efx.select_object"
    bl_label       = "Jump to Object"
    bl_description = "Clear current selection, select and activate the target EFX object"
    bl_options     = {"REGISTER"}  # 不含 UNDO：纯选择，不改场景数据

    # 目标对象名（由面板按钮在调用时赋值）
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

        # 清除当前选择，选中并激活目标对象
        bpy.ops.object.select_all(action="DESELECT")
        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §3  Extern 对象反向视图
# ─────────────────────────────────────────────────────────────────────────────

def _scan_extern_backrefs(extern_obj: bpy.types.Object) -> list:
    """
    扫描同一 EFX 树内所有 EXTERNREFERENCE 属性，
    找出 efx_extern_ref.extern_ref_ptr == extern_obj 的属性。

    返回
    ----
    list of dict：
        {
            'block_obj': bpy.types.Object,   # EFX_ATTRIBUTE 对象
            'block_name': str,               # 属性对象名
            'body_name': str,                # 所属 entry 名（parent 对象名）
        }

    只读扫描，不修改任何数据。
    """
    results = []

    tree = get_efx_tree_objects(extern_obj)
    block_objs = tree.get("EFX_ATTRIBUTE", [])

    try:
        from ..efx_format.hashes import EXTERNREFERENCE
    except ImportError:
        return results

    for blk in block_objs:
        # 检查是否是 EXTERNREFERENCE 类型
        try:
            bp = blk.efx_block
            if int(bp.type_hash_str) != EXTERNREFERENCE:
                continue
        except (AttributeError, ValueError):
            continue

        # 检查 extern_ref_ptr 是否指向当前 extern_obj
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

        # 找所属 entry（attribute 的 parent 是 entry）
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
    """
    Extern 对象反向引用视图（VIEW_3D N 面板，选中 EFX_EXTERN 时显示）。

    显示"被 N 个 EXTERNREFERENCE 属性引用"，
    以及每个引用属性（属性名 + 所属 entry 名）+ 跳转按钮。

    纯只读：不在此编辑引用关系，不触碰任何字节/导出路径。
    """

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

        # ── Extern 基本信息 ──────────────────────────────────────────────────
        info_box = layout.box()
        ext_idx = extern_obj.get("efx_index", "?")
        info_row = info_box.row()
        info_row.label(
            text=T("backref.extern_object") + f" {extern_obj.name}  (index {ext_idx})",
            icon="LINKED",
        )

        layout.separator()

        # ── 扫描反向引用 ──────────────────────────────────────────────────────
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

        # ── 逐条显示引用属性 ────────────────────────────────────────────────────
        for ref in refs:
            ref_box = layout.box()
            col = ref_box.column(align=True)

            # 属性名行
            row_name = col.row(align=True)
            row_name.label(text=T("backref.attribute") + f" {ref['block_name']}", icon="MODIFIER")

            # 所属 entry 行
            row_entry = col.row(align=True)
            if ref["body_name"]:
                row_entry.label(
                    text=T("backref.entry") + f" {ref['body_name']}",
                    icon="OBJECT_DATA",
                )
            else:
                row_entry.label(text=T("backref.entry_unknown"), icon="QUESTION")

            # 跳转按钮行
            row_jump = col.row(align=True)
            op = row_jump.operator(
                "efx.select_object",
                text=T("backref.jump_to_attribute"),
                icon="VIEWZOOM",
            )
            op.target_name = ref["block_name"]


# ─────────────────────────────────────────────────────────────────────────────
# §4  Entry 对象双向关系视图（Entry References）
#
# 把单纯的"被谁引用"升级为以 entry 为中心的双向关系导航（仍纯只读、不碰导出）：
#   ⬇ 我触发谁     ：本 entry 的 PTLIFE（status 区分生成/结束型）/ PTCOLLISION（碰撞时）
#                    属性 → action → 该 action 的子 entry(PLAYEMITTER targets) /
#                    外部 efx(PLAYEFX path)
#   ⬆ 谁触发我     ：哪些父 entry 的 PTLIFE / PTCOLLISION → 某个 targets 含本 entry 的 action
#   ⬔ 我引用的 Extern：本 entry 的 EXTERNREFERENCE 属性 → extern 对象
#   ⬓ 我所属的 Subselect：哪些 Subselect 表把本 entry 列为成员
# 全部边最终都落在 entry 这个公共节点上（关系是 DAG，不是树），所以按"边的类型"
# 分组列出 + 可跳转，天然处理多对一/共享，不需要枚举"谁套谁"。
# ─────────────────────────────────────────────────────────────────────────────

# PTLIFE status：short @ offset 4（0=生成时、4=结束时）
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
    """本 entry 出现在同一 EFX 树的多少张 subselect 表里（每表至多计一次）。

    subselect 是叠在激活集上的「状态掩码」：出现在某表里的 entry 只在选中该表的
    状态下触发；不在任何表里的 direct-active entry 恒触发。参见
    memory: subselect-is-active-set-mask。
    """
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
    """综合 EOF（direct）+ action 召唤 + subselect 门控，推断 entry 的「有效激活态」。

    触发模型（用户确认）：
      - **触发来源是「并」/OR**：direct（随 EFX 加载触发）与 action（被 Action 召唤触发）
        各自独立生效；两者都有的属性在「加载时」和「被召唤时」都会触发。
      - **subselect 是更上层的「与」/AND 门控**：在某 subselect 表里的属性，除来源条件外
        还须满足该表对应的状态条件才触发；不在任何表里 = 无条件（来源满足即触发）。

    返回 dict：
      'source'    : str — 触发来源并集（both / direct / action / none）
      'gated'     : bool — 是否被 subselect 门控（n_tables > 0）
      'n_tables'  : int  — 出现在几张 subselect 表里
      'in_eof'    : bool — 是否在直接触发列表（EOF）
      'in_action' : bool — 是否被任意 Action target 召唤

    注意：这是基于语料逆向的**模型推断**，不是字节铁律——运行时由哪个状态选中哪张
    subselect 表，取决于 EFX 之外的游戏逻辑（动画事件/战斗状态）。UI 文案据此用
    "推测"口吻。
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
    """
    以 entry_obj 为中心扫描同一 EFX 树的四类关系（只读）。

    返回 dict：
      'triggers'     : list {play_obj, play_name, timing, children:[obj], paths:[str]}
      'triggered_by' : list {entry_obj, body_name, play_obj, play_name, timing}
      'externs'      : list {extern_obj, extern_name, block_name}
      'subselects'   : list {ss_obj, ss_name}
    """
    from ..efx_format.hashes import PTLIFE, PTCOLLISION, EXTERNREFERENCE

    tree = get_efx_tree_objects(entry_obj)
    attrs   = tree.get("EFX_ATTRIBUTE", [])
    plays   = tree.get("EFX_ACTION", [])
    result  = {"triggers": [], "triggered_by": [], "externs": [], "subselects": []}

    # 本 entry 直属的属性（parent==entry_obj）
    my_attributes = [b for b in attrs if b.parent is entry_obj]

    def _ptlife_action(blk):
        """PTLIFE 属性 → 触发的 action 对象（pointerized 且非空才返回），否则 None。"""
        try:
            ref = blk.efx_ptlife_ref
            if not ref.relation_pointerized:
                return None
            return ref.relation_play_ptr
        except AttributeError:
            return None

    def _ptcollision_action(blk):
        """PTCOLLISION 属性 → 触发的 action 对象（pointerized、非哨兵、非空才返回），否则 None。"""
        try:
            ref = blk.efx_ptcollision_ref
            if not ref.ie_pointerized or ref.ie_none:
                return None
            return ref.ie_play_ptr
        except AttributeError:
            return None

    # 触发属性种类表：(type_hash, kind 标识, 取 action 的函数, 取 timing 的函数)
    _TRIGGER_KINDS = (
        (PTLIFE,      "ptlife",      _ptlife_action,      _read_ptlife_timing),
        (PTCOLLISION, "ptcollision", _ptcollision_action, lambda _blk: None),
    )

    # ── ⬇ 我触发谁：本 entry 的 PTLIFE / PTCOLLISION → action → 子 entry / 外部 efx ──
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

    # ── ⬆ 谁触发我：父 entry 的 PTLIFE / PTCOLLISION → 某个 targets 含本 entry 的 action ──
    # 先找出 targets 含本 entry 的 action 集合
    plays_targeting_me = set()
    for play in plays:
        children, _ = _action_children(play)
        if entry_obj in children:
            plays_targeting_me.add(play)
    # 再找哪些 entry 的 PTLIFE / PTCOLLISION 指向这些 action
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

    # ── ⬔ 我引用的 Extern：本 entry 的 EXTERNREFERENCE 属性 → extern ─────────────
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

    # ── ⬓ 我所属的 Subselect ─────────────────────────────────────────────────
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
    """
    Entry 双向关系视图（VIEW_3D N 面板，选中 EFX_ENTRY 时显示）。

    以本 entry 为中心展示四类关系（我触发谁 / 谁触发我 / 我引用的 Extern /
    我所属的 Subselect），每条可跳转。纯只读，不碰任何字节/导出路径。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Entry References"
    bl_parent_id   = "EFX_PT_entry_status"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ENTRY"

    def draw(self, context):
        layout = self.layout
        entry_obj = context.active_object

        # ── Entry 基本信息 ────────────────────────────────────────────────────
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

        # ── ⬇ 我触发谁 ────────────────────────────────────────────────────────
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

        # ── ⬆ 谁触发我 ────────────────────────────────────────────────────────
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

        # ── ⬔ 我引用的 Extern ────────────────────────────────────────────────
        if externs:
            box = layout.box()
            box.row().label(text=T("entryref.externs_header") + f" ({len(externs)})", icon="LINKED")
            for e in externs:
                row = box.row(align=True)
                row.label(text=e["extern_name"], icon="FILE_BLEND")
                _jump_button(row, e["extern_name"])

        # ── ⬓ 我所属的 Subselect ─────────────────────────────────────────────
        if subselects:
            box = layout.box()
            box.row().label(text=T("entryref.subselect_header") + f" ({len(subselects)})", icon="OUTLINER_OB_EMPTY")
            for s in subselects:
                row = box.row(align=True)
                row.label(text=s["ss_name"], icon="MODIFIER")
                _jump_button(row, s["ss_name"])


# ─────────────────────────────────────────────────────────────────────────────
# §5  ROOT subselect 状态总览面板（把 subselect 表呈现为「状态/变体」）
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
    """返回 root 的 EOF（直接触发）entry 对象列表（按 efx_index 顺序）。
    委托 entry_action_ref.is_entry_in_eof——该函数已知道 per_entry（Direct Trigger
    嵌套集合）/ opaque（非索引数据，恒空）两种模型，这里不需要关心内部载体。"""
    from .entry_action_ref import is_entry_in_eof
    return [b for b in _rc.collect_top_level(root_obj, "EFX_ENTRY") if is_entry_in_eof(b)]


class EFX_PT_root_states(bpy.types.Panel):
    """
    EFX_ROOT 的 subselect 状态总览（VIEW_3D N 面板，选中 EFX_ROOT 时显示）。

    把每张 subselect 表呈现为一个「状态/变体」，列出其成员 entry（带跳转）；
    再单列「恒触发」集合 = 在 EOF 直接触发列表里、却不在任何 subselect 表里的 entry。

    纯只读、纯导航。文案用"推测模型"口吻——运行时由哪个状态被选中触发取决于
    EFX 之外的游戏逻辑（见 memory: subselect-is-active-set-mask）。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Subselect States"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _rc.is_root_collection(context.collection)

    def draw(self, context):
        layout = self.layout
        root_obj = context.collection

        tree = get_efx_tree_objects(root_obj)
        ss_objs = tree.get("EFX_SUBSELECT", [])

        # ── 状态（subselect 表）─────────────────────────────────────────────────
        gated_bodies = set()   # 出现在任意表里的 entry，用于算「恒触发」
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

        # ── 恒触发：在 EOF 直接触发列表、却不在任何 subselect 表里 ───────────────
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

# 算子：可在 panels.register() 之前单独注册（无依赖）。
# 面板：bl_parent_id="EFX_PT_entry"，必须在 EFX_PT_entry 之后注册（由 panels.py 统一处理）。

_CLASSES_CORE = (
    EFX_OT_select_object,
)

# EFX_PT_extern_backref 和 EFX_PT_entry_backref 导出给 panels.py，
# 由 panels.register() 在 EFX_PT_entry 之后注册。


def register():
    """注册 backref 核心类（算子）。面板由 panels.py 注册。"""
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)


def unregister():
    """注销 backref 核心类。面板由 panels.py 先注销。"""
    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
