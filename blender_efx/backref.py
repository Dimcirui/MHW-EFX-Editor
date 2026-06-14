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
   扫描同一 EFX 树内所有 EFX_BLOCK，找出 type_hash==EXTERNREFERENCE
   且 efx_extern_ref.extern_ref_ptr == 当前 extern 的块，
   显示"被 N 个块引用"+ 每个块（块名 + 所属 body 名）+ 跳转按钮。

4. ``EFX_PT_body_backref``
   Body 对象反向视图（VIEW_3D N 面板，poll: EFX_BODY）。
   扫描同一 EFX 树，列出引用该 body 的：
     - Subselect 表（其 members 有指向该 body 的）
     - Play emitter（其 entries[*].targets 有指向该 body 的）
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


# ─────────────────────────────────────────────────────────────────────────────
# §1  同树范围 helper
# ─────────────────────────────────────────────────────────────────────────────

def _find_root_collection(obj: bpy.types.Object):
    """
    给任意 EFX 对象，找到它所属的顶层 EFX 集合（即紫色 .efx 集合）。

    策略
    ----
    顶层 EFX 集合命名约定：文件名含 '.efx'（如 'boom.efx'）。
    从 bpy.data.collections 中找到包含 obj 或其祖先的、名含 '.efx' 的集合。

    若找不到（极端情况），返回 None。
    """
    # 收集 obj 所有直接所在的集合
    obj_cols = set()
    for col in bpy.data.collections:
        if obj in col.objects.values():
            obj_cols.add(col)

    if not obj_cols:
        return None

    # 向上找：哪个顶级集合包含这些集合（直接或间接）
    # 顶级 EFX 集合名含 '.efx'（来自 io_tree.py §2：file_name = basename(filepath)）
    for root_col in bpy.data.collections:
        if ".efx" not in root_col.name:
            continue
        if _collection_contains_obj(root_col, obj):
            return root_col

    return None


def _collection_contains_obj(col, obj: bpy.types.Object) -> bool:
    """递归检查集合（含子集合）是否包含 obj。"""
    if obj in col.objects.values():
        return True
    for child in col.children:
        if _collection_contains_obj(child, obj):
            return True
    return False


def _collect_all_from_collection(col, out_by_type: dict) -> None:
    """
    递归收集集合及子集合内所有 EFX 对象，按 ~TYPE 分类存入 out_by_type。

    out_by_type : dict[str, list[bpy.types.Object]]
        key = ~TYPE 字符串（如 'EFX_BLOCK'），value = 对象列表（按收集顺序）
    """
    for obj in col.objects:
        t = obj.get("~TYPE")
        if t:
            if t not in out_by_type:
                out_by_type[t] = []
            out_by_type[t].append(obj)
    for child in col.children:
        _collect_all_from_collection(child, out_by_type)


def get_efx_tree_objects(obj: bpy.types.Object) -> dict:
    """
    给任意 EFX 对象，返回同一 EFX 树内按 ~TYPE 分类的全部对象。

    返回
    ----
    dict[str, list[bpy.types.Object]]
        key = ~TYPE 字符串（如 'EFX_BLOCK'、'EFX_BODY' 等）
        value = 该类型的对象列表

    若无法确定树根，返回空 dict（防御性）。

    用途
    ----
    反向扫描只在同树内进行，避免多个导入的 EFX 文件之间混淆。
    """
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
    扫描同一 EFX 树内所有 EXTERNREFERENCE 块，
    找出 efx_extern_ref.extern_ref_ptr == extern_obj 的块。

    返回
    ----
    list of dict：
        {
            'block_obj': bpy.types.Object,   # EFX_BLOCK 对象
            'block_name': str,               # 块对象名
            'body_name': str,                # 所属 body 名（parent 对象名）
        }

    只读扫描，不修改任何数据。
    """
    results = []

    tree = get_efx_tree_objects(extern_obj)
    block_objs = tree.get("EFX_BLOCK", [])

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

        # 找所属 body（block 的 parent 是 body）
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

    显示"被 N 个 EXTERNREFERENCE 块引用"，
    以及每个引用块（块名 + 所属 body 名）+ 跳转按钮。

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

        # ── 逐条显示引用块 ────────────────────────────────────────────────────
        for ref in refs:
            ref_box = layout.box()
            col = ref_box.column(align=True)

            # 块名行
            row_name = col.row(align=True)
            row_name.label(text=T("backref.block") + f" {ref['block_name']}", icon="MODIFIER")

            # 所属 body 行
            row_body = col.row(align=True)
            if ref["body_name"]:
                row_body.label(
                    text=T("backref.body") + f" {ref['body_name']}",
                    icon="OBJECT_DATA",
                )
            else:
                row_body.label(text=T("backref.body_unknown"), icon="QUESTION")

            # 跳转按钮行
            row_jump = col.row(align=True)
            op = row_jump.operator(
                "efx.select_object",
                text=T("backref.jump_to_block"),
                icon="VIEWZOOM",
            )
            op.target_name = ref["block_name"]


# ─────────────────────────────────────────────────────────────────────────────
# §4  Body 对象双向关系视图（Body References）
#
# 把单纯的"被谁引用"升级为以 body 为中心的双向关系导航（仍纯只读、不碰导出）：
#   ⬇ 我触发谁     ：本 body 的 PTLIFE（timing 区分生成/结束型）/ PTCOLLISION（碰撞时）
#                    块 → action(play) → 该 play 的子 body(PLAYEMITTER targets) /
#                    外部 efx(PLAYEFX path)
#   ⬆ 谁触发我     ：哪些父 body 的 PTLIFE / PTCOLLISION → 某个 targets 含本 body 的 action
#   ⬔ 我引用的 Extern：本 body 的 EXTERNREFERENCE 块 → extern 对象
#   ⬓ 我所属的 Subselect：哪些 Subselect 表把本 body 列为成员
# 全部边最终都落在 body 这个公共节点上（关系是 DAG，不是树），所以按"边的类型"
# 分组列出 + 可跳转，天然处理多对一/共享，不需要枚举"谁套谁"。
# ─────────────────────────────────────────────────────────────────────────────

# PTLIFE timing：short @ offset 4（0=生成时、4=结束时）
_PTLIFE_TIMING_OFFSET = 4


def _block_type_hash(blk) -> int:
    """读 EFX_BLOCK 的 type_hash（失败返回 -1）。"""
    try:
        return int(blk.efx_block.type_hash_str)
    except (AttributeError, ValueError, TypeError):
        return -1


def _read_ptlife_timing(blk):
    """读 PTLIFE 块的 timing（short @ offset 4）；失败返回 None。"""
    try:
        raw = base64.b64decode(str(blk.efx_block.raw_b64))
        if len(raw) >= _PTLIFE_TIMING_OFFSET + 2:
            return struct.unpack_from("<h", raw, _PTLIFE_TIMING_OFFSET)[0]
    except Exception:
        pass
    return None


def _play_children(play_obj):
    """返回 play_obj 的子引用：(child_body 对象列表, 外部 efx 路径列表)。"""
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


def _scan_body_relations(body_obj: bpy.types.Object) -> dict:
    """
    以 body_obj 为中心扫描同一 EFX 树的四类关系（只读）。

    返回 dict：
      'triggers'     : list {play_obj, play_name, timing, children:[obj], paths:[str]}
      'triggered_by' : list {body_obj, body_name, play_obj, play_name, timing}
      'externs'      : list {extern_obj, extern_name, block_name}
      'subselects'   : list {ss_obj, ss_name}
    """
    from ..efx_format.hashes import PTLIFE, PTCOLLISION, EXTERNREFERENCE

    tree = get_efx_tree_objects(body_obj)
    blocks  = tree.get("EFX_BLOCK", [])
    plays   = tree.get("EFX_PLAY", [])
    result  = {"triggers": [], "triggered_by": [], "externs": [], "subselects": []}

    # 本 body 直属的块（parent==body_obj）
    my_blocks = [b for b in blocks if b.parent is body_obj]

    def _ptlife_play(blk):
        """PTLIFE 块 → 触发的 play 对象（pointerized 且非空才返回），否则 None。"""
        try:
            ref = blk.efx_ptlife_ref
            if not ref.relation_pointerized:
                return None
            return ref.relation_play_ptr
        except AttributeError:
            return None

    def _ptcollision_play(blk):
        """PTCOLLISION 块 → 触发的 play 对象（pointerized、非哨兵、非空才返回），否则 None。"""
        try:
            ref = blk.efx_ptcollision_ref
            if not ref.ie_pointerized or ref.ie_none:
                return None
            return ref.ie_play_ptr
        except AttributeError:
            return None

    # 触发块种类表：(type_hash, kind 标识, 取 play 的函数, 取 timing 的函数)
    _TRIGGER_KINDS = (
        (PTLIFE,      "ptlife",      _ptlife_play,      _read_ptlife_timing),
        (PTCOLLISION, "ptcollision", _ptcollision_play, lambda _blk: None),
    )

    # ── ⬇ 我触发谁：本 body 的 PTLIFE / PTCOLLISION → play → 子 body / 外部 efx ──
    for blk in my_blocks:
        th = _block_type_hash(blk)
        for type_hash, kind, get_play, get_timing in _TRIGGER_KINDS:
            if th != type_hash:
                continue
            play = get_play(blk)
            if play is None:
                continue
            children, paths = _play_children(play)
            result["triggers"].append({
                "play_obj": play,
                "play_name": play.name,
                "kind": kind,
                "timing": get_timing(blk),
                "children": children,
                "paths": paths,
            })

    # ── ⬆ 谁触发我：父 body 的 PTLIFE / PTCOLLISION → 某个 targets 含本 body 的 play ──
    # 先找出 targets 含本 body 的 play 集合
    plays_targeting_me = set()
    for play in plays:
        children, _ = _play_children(play)
        if body_obj in children:
            plays_targeting_me.add(play)
    # 再找哪些 body 的 PTLIFE / PTCOLLISION 指向这些 play
    if plays_targeting_me:
        for blk in blocks:
            if blk.parent is None or blk.parent is body_obj:
                continue
            th = _block_type_hash(blk)
            for type_hash, kind, get_play, get_timing in _TRIGGER_KINDS:
                if th != type_hash:
                    continue
                play = get_play(blk)
                if play in plays_targeting_me:
                    result["triggered_by"].append({
                        "body_obj": blk.parent,
                        "body_name": blk.parent.name,
                        "play_obj": play,
                        "play_name": play.name,
                        "kind": kind,
                        "timing": get_timing(blk),
                    })

    # ── ⬔ 我引用的 Extern：本 body 的 EXTERNREFERENCE 块 → extern ─────────────
    for blk in my_blocks:
        if _block_type_hash(blk) != EXTERNREFERENCE:
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
            if member.body_ptr is body_obj:
                result["subselects"].append({
                    "ss_obj": ss_obj,
                    "ss_name": ss_obj.name,
                })
                break

    return result


def _timing_label(timing) -> str:
    """timing → 人类可读（生成/结束/原值）。"""
    if timing == 0:
        return T("bodyref.timing_spawn")
    if timing == 4:
        return T("bodyref.timing_death")
    return T("bodyref.timing_other") + f"={timing}"


def _trigger_label(t) -> str:
    """触发条目 → 方括号内标签：PTCOLLISION 显示"碰撞时"，PTLIFE 按 timing。"""
    if t.get("kind") == "ptcollision":
        return T("bodyref.trigger_collision")
    return _timing_label(t.get("timing"))


def _jump_button(row, target_name, text="", icon="VIEWZOOM"):
    op = row.operator("efx.select_object", text=text, icon=icon)
    op.target_name = target_name


class EFX_PT_body_backref(bpy.types.Panel):
    """
    Body 双向关系视图（VIEW_3D N 面板，选中 EFX_BODY 时显示）。

    以本 body 为中心展示四类关系（我触发谁 / 谁触发我 / 我引用的 Extern /
    我所属的 Subselect），每条可跳转。纯只读，不碰任何字节/导出路径。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Body References"
    bl_parent_id   = "EFX_PT_body_reorder"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        body_obj = context.active_object

        # ── Body 基本信息 ────────────────────────────────────────────────────
        info_box = layout.box()
        body_idx = body_obj.get("efx_index", "?")
        info_box.row().label(
            text=T("backref.body_object") + f" {body_obj.name}  (index {body_idx})",
            icon="OBJECT_DATA",
        )

        rel = _scan_body_relations(body_obj)
        triggers     = rel["triggers"]
        triggered_by = rel["triggered_by"]
        externs      = rel["externs"]
        subselects   = rel["subselects"]

        if not (triggers or triggered_by or externs or subselects):
            layout.label(text=T("bodyref.none"), icon="INFO")
            return

        # ── ⬇ 我触发谁 ────────────────────────────────────────────────────────
        if triggers:
            box = layout.box()
            box.row().label(text=T("bodyref.triggers_header"), icon="FORWARD")
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
            box.row().label(text=T("bodyref.triggered_by_header"), icon="BACK")
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
            box.row().label(text=T("bodyref.externs_header") + f" ({len(externs)})", icon="LINKED")
            for e in externs:
                row = box.row(align=True)
                row.label(text=e["extern_name"], icon="FILE_BLEND")
                _jump_button(row, e["extern_name"])

        # ── ⬓ 我所属的 Subselect ─────────────────────────────────────────────
        if subselects:
            box = layout.box()
            box.row().label(text=T("bodyref.subselect_header") + f" ({len(subselects)})", icon="OUTLINER_OB_EMPTY")
            for s in subselects:
                row = box.row(align=True)
                row.label(text=s["ss_name"], icon="MODIFIER")
                _jump_button(row, s["ss_name"])


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 算子：可在 panels.register() 之前单独注册（无依赖）。
# 面板：bl_parent_id="EFX_PT_main"，必须在 EFX_PT_main 之后注册（由 panels.py 统一处理）。

_CLASSES_CORE = (
    EFX_OT_select_object,
)

# EFX_PT_extern_backref 和 EFX_PT_body_backref 导出给 panels.py，
# 由 panels.register() 在 EFX_PT_main 之后注册。


def register():
    """注册 backref 核心类（算子）。面板由 panels.py 注册。"""
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)


def unregister():
    """注销 backref 核心类。面板由 panels.py 先注销。"""
    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
