"""
blender_efx/entry_action_ref.py  —  L2 #1d：补完 entry/action 引用层指针化

涵盖三项：
  1. PtLife.relationIndex     → action 指针（int16，偏移 8）
  2. PtCollision.ieIndex      → action 指针（int32，偏移 96）
  3. eof_ints（End 段）       → 直接触发 entry 索引集合（嵌套集合归属）

设计原则（参照 CLAUDE.md / extern_ref.py 模式）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集（PropertyGroup / CollectionProperty / PointerProperty /
    BoolProperty / IntProperty / Panel）
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：死属性/越界/哨兵均原样往返

────────────────────────────────────────────────────────────────────────────
§ 1  PtLife.relationIndex（int16）
────────────────────────────────────────────────────────────────────────────
PTLIFE_SCHEMA：short[10]，共 20 字节（no leading type_hash）。
  offset  0: h unkn0
  offset  2: h unkn1
  offset  4: h status
  offset  6: h unkn3
  offset  8: h relationIndex   ← 指针化目标字段（int16 有符号）
  ...

实测语义（社区教程 + 语料复核，2026-06 修正）：
  值 v（int16 有符号）= **actionID** = ACTION 段局部 0-based index（EFX_ACTION）。
  依据：canni《ACTION 结构》《延迟火》教程均写 relationIndex=actionID；
  178 样本复核——18 个"有 action"（count_play>0）的文件里，每个
  max(relationIndex)==count_play-1，无一越过 count_play（count_body 是
  7~23 的大范围却从不被触及，如 ymt006 cp=3 用到 2、boom cp=2 用 1）。
  若是 entry index，值本应散布 [0,count_body)，但全部紧贴 [0,count_play)。
  早先误判 entry 的 5 个样本全来自 count_play==0 的文件 = 死 PTLIFE 残留属性。

int16 哨兵：无样本观测到哨兵（-1=0xFFFF），但因为 0xFFFF 是 int16 的 -1，
  若出现则应视为"无目标"，保守处理 → 不指针化（pointerized=False），原样保留。
  实际上 0 <= v < count_play 才指针化；其他情况（含负值/越界）保守原样。

导出覆写：struct.pack_into('<h', buf, 8, new_index)  （int16，偏移 8）

────────────────────────────────────────────────────────────────────────────
§ 2  PtCollision.ieIndex（int32）
────────────────────────────────────────────────────────────────────────────
PTCOLLISION_SCHEMA：112 字节。
  offset 96: i ieIndex   ← 指针化目标字段（int32 有符号）

实测语义：
  boom.efx entry[4/5] ieIndex=0 → action[0]="ACT_PTC"（粒子碰撞播放器）
  ymt006 entry[3] ieIndex=1     → action[1]="ACT_PTC"
  → action 段局部 index（EFX_ACTION）

0xFFFFFFFF / -1 哨兵：corpus 中未观测，但按设计保守支持（参照 BLUEPRINT §9）。
  若 v == -1（有符号）：none=True；pointerized=True。
  0 <= v < count_play：有效 action 指针；pointerized=True。
  其他（越界/count_play=0）：pointerized=False，原样保留。

导出覆写：struct.pack_into('<i', buf, 96, new_index)  （int32，偏移 96）

────────────────────────────────────────────────────────────────────────────
§ 3  eof_ints（End 段，entry 索引集合）→ per_entry（对称嵌套集合）
────────────────────────────────────────────────────────────────────────────
EOF 段的语义是「哪些 entry 直接触发」的**索引集合**，顺序不承载信息——official
语料 10084 文件全量实测坐实（10075 严格升序无重复全 in-range + 9 个 count_eof==0
的空 main；越界/重复/非升序各 0 例，见 normalize_eof_ints 文档串）。因此导入时
一律先 normalize_eof_ints 规范化（丢弃越界与重复、升序归一），再走 "per_entry"。

per_entry：直接触发的载体是**集合归属**——
Entry 叶子集合下嵌两个对称子集合 "Direct Trigger" / "Not Direct Trigger"
（root_collection.py ensure_direct_trigger_collection / ensure_not_direct_
trigger_collection）。entry **100% 分流**进其中一个——Entry 叶子集合自身直接
子级永远清空，避免"直接触发的单独有集合、不直接触发的却混在一起"的模糊状态
（2026-07 二期用户反馈：光有 Direct Trigger 一个子集合分不清"不触发"和"忘了分类"）。
悬空/越界从原理上不存在（entry 被删=从 bpy.data.objects 移除=自动从其所在
集合消失）。

fail-safe：若 entry 异常地既不在 Direct Trigger 也不在 Not Direct Trigger
（手动拖拽失误，直接留在 Entry 叶子集合本身）→ 导出时**视为直接触发**（宁可
多触发、不漏触发）。若同时在两处（另一种拖拽失误）→ Direct Trigger 优先。
validate.py 对这两种异常状态都有 WARN。

"opaque" 模型（整段原样存 root_col["eof_ints"] 字符串、只读）**导入端已不再产生**
（2026-08）。代码里保留的 opaque 分支只服务一种情况：本次改动之前保存的 .blend
里可能存着 eof_model="opaque" 的 root 集合，那种集合根本没有 DT/NDT 两个子集合，
按 per_entry 的 fail-safe 规则会被判成"全部 entry 都触发"而写坏 EOF；读回原字符串
才能保持它 byte-perfect。新导入的文件永远走 per_entry，这些分支对其不可达。

导出：
  per_entry → 遍历 entry_index_map，按上述 fail-safe 规则判定每个 entry 是否
              触发，取其局部 index，升序返回。
  opaque    → root_col["eof_ints"] 字符串原样解析回整数列表（仅旧 .blend）。

2026-07 二期改动：早期版本载体是每个 entry 的 efx_direct_trigger 布尔
（BoolProperty）+ 一套已废弃的 efx_eof_list CollectionProperty 遗留层
（后者自 hybrid 模型上线后就从未被 io_tree.py 调用，纯死代码）。本次改为
嵌套集合后，两者一并删除——ROOT 集合化已经让"旧 .blend 没有 eof_model"这个
分支彻底不可达（旧 .blend 连 root_col 都没有），不需要再保留后向兼容分支。
三期（本次）从单一 Direct Trigger 子集合升级为对称两个子集合 + fail-safe 规则。
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


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# PtLife.relationIndex：偏移 8，int16 有符号 '<h'
_RELATION_INDEX_OFFSET = 8

# PtCollision.ieIndex：偏移 96，int32 有符号 '<i'
_IE_INDEX_OFFSET = 96

# int32 哨兵（-1）
_SENTINEL_INT32 = -1


# ─────────────────────────────────────────────────────────────────────────────
# poll 函数
# ─────────────────────────────────────────────────────────────────────────────

def _same_root_as_active(obj):
    """obj 是否与当前活动对象处于同一 EFX 文件（同一 root_col）。
    活动对象或任一方无 root 时不限制（返回 True），仅在确属不同 root 时排除。"""
    editing = getattr(bpy.context, "active_object", None)
    if editing is None:
        return True
    return _rc.same_root(editing, obj)


def _action_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_ACTION'，且限定同一 EFX 文件
    （多 EFX 集合并存时防串文件）。"""
    return obj.get("~TYPE") == "EFX_ACTION" and _same_root_as_active(obj)


# ─────────────────────────────────────────────────────────────────────────────
# §1  PtLife.relationIndex → EFX_ENTRY 指针
# ─────────────────────────────────────────────────────────────────────────────
#
# 2026-07 简化：不再区分"已指针化/死属性/越界"三态，只留一个可空指针
# relation_play_ptr——None 统一表示"无目标"（不管是本来就没有、越界/死值、还是
# 悬空），导出时自动写 -1 哨兵（int16 全 1）。不再假设"语料未观测到 -1 就不能
# 用 -1"——用户决定：不合法就写 -1 更安全，也让字段在合并进 Attribute
# Properties 后始终可编辑，不需要"越界/死属性"这种只读中间态。

class EFXPtLifeRefProps(PropertyGroup):
    """挂在 EFX_ATTRIBUTE（PTLIFE 类型）对象上（obj.efx_ptlife_ref）。

    relation_play_ptr : PointerProperty → EFX_ACTION 对象（poll=EFX_ACTION）。
                         None = 无目标（导出写 -1）。
    """

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
    """
    初始化 blk_obj.efx_ptlife_ref PropertyGroup。

    0 <= v < count_play 且能映射到对象 → relation_play_ptr 指向该 EFX_ACTION；
    其他（负值/越界/count_play==0/映射缺失）→ 留空（None，无目标）。
    """
    props = blk_obj.efx_ptlife_ref
    if len(data_bytes) < 10:
        return
    # 读 relationIndex（有符号 int16，小端）= actionID（action 段局部 index）
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
    """
    把 data_bytes 偏移 8 处的 int16（relationIndex）覆写为 relation_play_ptr 对应的
    action 局部 index；无目标/悬空/跨文件解析不到 → 写 -1 哨兵。

    参数同旧版；返回覆写后的 data_bytes（字节不足 10 时原样返回，防御性兜底）。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# §2  PtCollision.ieIndex → EFX_ACTION 指针
# ─────────────────────────────────────────────────────────────────────────────

# 2026-07 简化：跟 §1 PtLife 同款——只留一个可空指针 ie_play_ptr，None 统一表示
# "无目标"（原本就是 -1 哨兵 / 越界死值 / 悬空，三者不再区分），导出时自动写 -1。

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
    """
    初始化 blk_obj.efx_ptcollision_ref PropertyGroup。

    v == -1（哨兵）或负值/越界/count_play==0/映射缺失 → 留空（None，无目标）；
    0 <= v < count_play 且能映射到对象 → ie_play_ptr 指向该 EFX_ACTION。
    """
    props = blk_obj.efx_ptcollision_ref
    if len(data_bytes) < 100:
        return
    # 读 ieIndex（有符号 int32，小端）
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
    """
    把 data_bytes 偏移 96 处的 int32（ieIndex）覆写为 ie_play_ptr 对应的
    action 局部 index；无目标/悬空/跨文件解析不到 → 写 -1 哨兵。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# §3  eof_ints（End 段）→ 直接触发 entry 索引集合（顺序无语义，见文件头 §3）
# ─────────────────────────────────────────────────────────────────────────────

def normalize_eof_ints(eof_ints: list, count_body: int):
    """把 EOF 段规范化成「直接触发 entry 索引集合」：丢弃越界值、去重，升序返回。

    返回 (indices, dropped, reordered)：
      indices   : list — 规范化后的升序索引，供集合分流使用
      dropped   : list — 被丢弃的原始值（越界或重复），按出现顺序，供 WARN 报告
      reordered : bool — 原列表的有效值本来就不是升序（顺序被规范化掉了）

    为什么可以无损丢弃 —— official 语料 10084 个文件全量实测（2026-08）：
      10075 个 EOF 严格升序、无重复、全 in-range；另 9 个 count_eof==0（其
      count_body 同为 0，即 main 段本身是空的）。越界 0 例、重复 0 例、非升序
      0 例。也就是说官方从未在 EOF 里写入索引之外的东西，这段的语义就是
      「哪些 entry 直接触发」的集合，顺序不承载信息。
      反面对照：efx_samples/ 根目录 78 个社区/手工样本里有 11 个越界（如
      fire.efx 的 [99,99,...,0,9,10,11,99,...]、ymt00x 系列删 entry 后没重编号
      的末位越界 1），nadao_qian.efx 则是 14/15 互换。这些都是编辑工具/手工改动
      的产物，规范化后输出成官方唯一使用过的形状，方向上是修好而非破坏。

    ⚠ 本函数只服务 Blender 编辑模型。efx_format/ 侧保持绝对忠实（裸 unpack /
      裸 pack，越界值原样往返），codec 的 serialize(parse(x))==x 不受影响。
    """
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
    """entry_obj 本身 + 其直属 EFX_ATTRIBUTE/EFX_TIML 子对象。root_collection.py 的
    不变式是"entry 和它的 attribute/TIML 句柄都直接 link 在同一个叶子集合里"——
    EOF 归属在 Entry 叶子集合 ↔ 嵌套 Direct Trigger 子集合之间挪动时，必须整棵子树
    一起挪，只挪 entry 本身会让属性/TIML 句柄留在原集合，破坏该不变式。

    children_by_parent（可选）：预先按 .parent 分组好的 {parent_obj: [children]}
    映射（见 _build_children_by_parent）。不传则现场全量扫 bpy.data.objects——
    单个 entry 调用（toggle/新建）这样没问题，但对**很多** entry 逐个调用
    （如 init_eof_per_entry 遍历全部 entry）是 O(entry 数 × 场景对象数) 的性能
    陷阱（2026-07 曾把导入拖慢，已修：批量场景改传预建映射）。
    """
    if children_by_parent is not None:
        return [entry_obj] + children_by_parent.get(entry_obj, [])
    out = [entry_obj]
    for o in bpy.data.objects:
        if o.parent == entry_obj and o.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML"):
            out.append(o)
    return out


def _build_children_by_parent() -> dict:
    """一次性扫 bpy.data.objects，按 .parent 分组 EFX_ATTRIBUTE/EFX_TIML 子对象，
    返回 {parent_obj: [children]}。供批量场景（如 init_eof_per_entry 遍历全部
    entry）替代"每个 entry 各扫一遍全场景"的 O(n²) 写法，摊薄成一次 O(n) 扫描。"""
    out = {}
    for o in bpy.data.objects:
        p = o.parent
        if p is not None and o.get("~TYPE") in ("EFX_ATTRIBUTE", "EFX_TIML"):
            out.setdefault(p, []).append(o)
    return out


def _move_entry_subtree(entry_obj: bpy.types.Object, src_cols, dst_col,
                         children_by_parent: dict = None) -> None:
    """把 entry_obj 整棵子树（自身+attribute+TIML）从 src_cols 挪到 dst_col。

    src_cols 可传单个 Collection，也可传多个（list/tuple）——挪动前依次尝试从
    每一个里解链，不在其中的直接跳过。用于"不确定 entry 当前实际挂在哪"的场景
    （如 toggle 时它可能在 Direct Trigger / Not Direct Trigger / 异常孤儿状态
    三者之一，一次调用把三处都清干净）。

    children_by_parent：批量调用（多个 entry）时传 _build_children_by_parent()
    的结果，避免逐 entry 重复全场景扫描（见 _entry_subtree_objects）。
    """
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
    """
    导入端：设 root_obj["eof_model"]="per_entry"，把**每一个** entry（及其
    attribute/TIML 子对象）从 Entry 叶子集合分流进 "Direct Trigger" 或
    "Not Direct Trigger" 子集合之一（100% 分流，Entry 叶子集合自身直接子级导入后
    永远清空）。

    2026-08 起无条件走 per_entry —— EOF 先经 normalize_eof_ints 规范化（丢弃越界/
    重复、顺序归一），依据是 official 10084 文件全量实测该段纯为索引集合（详见
    normalize_eof_ints 文档串）。此前对"不干净"列表回退 opaque 只读，实测那条
    分支在官方语料上完全不可达，只有 ~12 个畸形社区文件会踩到，代价是它们在插件
    里完全不能编辑触发分组。现在改为规范化后照常编辑，被丢弃的值记在
    root_obj["eof_dropped"]，由 validate.py + Direct Trigger List 面板报 WARN，
    不静默。
    """
    active_sorted, dropped, reordered = normalize_eof_ints(eof_ints, count_body)

    root_obj["eof_model"] = "per_entry"
    # 诊断记录：被丢弃的原始值 / 顺序是否被归一化。空则清掉键，避免 .blend 里
    # 残留上一次导入的陈旧记录（同一 root 集合被复用时）。
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

    # 批量场景：一次性建 {parent: [children]} 映射，避免每个 entry 各扫一遍
    # 全场景 bpy.data.objects（entry 数多的文件导入曾因此明显变慢，已修）。
    children_by_parent = _build_children_by_parent()
    for idx, obj in main_bodies_by_index.items():
        dst = dt_col if idx in active else ndt_col
        _move_entry_subtree(obj, entry_col, dst, children_by_parent)


def export_eof_per_entry(root_obj: bpy.types.Object, entry_index_map: dict) -> list:
    """
    导出端 hybrid：
      per_entry → 按 fail-safe 规则判定每个 entry 是否触发：link 在 Direct Trigger
                  里 → 触发；不在 Not Direct Trigger 里（含误留在 Entry 叶子集合
                  直接子级的异常孤儿）→ 也触发（宁可多触发不漏触发）；否则不触发。
                  取局部 index，升序返回。
      opaque    → root_obj["eof_ints"] 字符串原样（**仅**本次改动前保存的旧
                  .blend；新导入一律 per_entry，见文件头 §3）。
      无 eof_model（不该出现——ROOT 集合化后旧 .blend 早已不兼容）→ 空列表兜底。
    """
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
    """从 eof_ints 逗号字符串自定义属性还原整数列表（opaque 模型 byte-perfect 直通用）。"""
    try:
        s = str(root_obj["eof_ints"]).strip()
        return [int(x) for x in s.split(",") if x] if s else []
    except (KeyError, ValueError, TypeError):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# §4  覆写 helper（供 io_tree 导出时调用）
# ─────────────────────────────────────────────────────────────────────────────

def apply_attribute_ref_overlays(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    entry_index_map: dict,
    play_index_map: dict,
) -> bytes:
    """
    对单个 EFX_ATTRIBUTE 对象，按其类型应用 L2 #1d 的字段覆写：
      - PTLIFE      → overlay_ptlife_relation_index（action index，int16，偏移 8）
      - PTCOLLISION → overlay_ptcollision_ie_index（action index，int32，偏移 96）
      - 其他        → 原样返回

    参数
    ----
    data_bytes     : bytes     — 块当前的 data_bytes（已由 fields 层处理完毕）
    blk_obj        : Object    — EFX_ATTRIBUTE Empty
    entry_index_map : dict      — {EFX_ENTRY Object → main 局部 index}
    play_index_map : dict      — {EFX_ACTION Object → action 局部 index}

    返回
    ----
    bytes — 覆写后的 data_bytes（或原样）
    """
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


# 独立的 "Relation Action Reference" / "IE Action Reference" 面板已删除
# （2026-07）：relation_play_ptr / ie_play_ptr 的编辑控件合并进 Attribute
# Properties 面板内联渲染（见 panels.py::_draw_ptlife_ref_field /
# _draw_ptcollision_ref_field，替换原 relationIndex/ieIndex 字段行）。

# ─────────────────────────────────────────────────────────────────────────────
# §6  EOF Entry 激活切换算子 + 面板
# ─────────────────────────────────────────────────────────────────────────────

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

        # opaque 只可能来自本次改动前保存的旧 .blend（新导入一律 per_entry）。
        # 那种 root 没有 DT/NDT 子集合，无法表达归属 → 保持只读，提示重新导入。
        if str(root.get("eof_model", "")) == "opaque":
            self.report({"WARNING"},
                        "This EFX was imported by an older plugin version with a read-only "
                        "EOF section. Re-import the .efx to enable trigger editing")
            return {"CANCELLED"}

        # per_entry 模型：在 Direct Trigger ↔ Not Direct Trigger 两个嵌套子集合
        # 之间挪动整棵子树（entry + attribute + TIML）。当前有效触发态按 fail-safe
        # 规则判定（不在 Not Direct Trigger 里的孤儿也算触发），取反后目标集合
        # 二选一；源集合传全部三处候选（Entry 叶子集合本身+两个子集合），不管
        # entry 实际在哪个都能正确清干净——顺带把异常孤儿状态一起修复掉。
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
    """查询 entry_obj 是否在所属根文件的 eof 直接触发集中（与 export_eof_per_entry
    同款 fail-safe 规则：不在 Not Direct Trigger 里的孤儿也算触发）。供面板绘制使用。"""
    root = _rc.find_root_collection(entry_obj) if entry_obj else None
    if root is None:
        return False
    if str(root.get("eof_model", "")) != "per_entry":
        return False  # opaque：非索引数据，"是否在 eof 里"这个问题本身不成立
    dt_col = _rc.get_direct_trigger_collection(root)
    ndt_col = _rc.get_not_direct_trigger_collection(root)
    in_dt = dt_col is not None and dt_col in entry_obj.users_collection
    in_ndt = ndt_col is not None and ndt_col in entry_obj.users_collection
    return in_dt or not in_ndt


def place_new_entry(root_obj: bpy.types.Object, entry_obj: bpy.types.Object, in_eof: bool) -> None:
    """新建/粘贴的 entry 刚建好时（仍原样挂在 Entry 叶子集合本身），按 eof_model 归位：
      opaque    → 不动（该模型没有嵌套子集合概念，读者只读 eof_ints 字符串）。
      per_entry → 挪进 Direct Trigger（in_eof=True）或 Not Direct Trigger（否则），
                  确保"Entry 叶子集合直接子级永远清空"对新建 entry 同样成立。
      无 eof_model（不该出现）→ 不动。
    供 add_ops.py 新建 entry（预设/粘贴）时调用。
    """
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
    """
    Direct Trigger 只读总览（VIEW_3D N 面板，选中 ROOT 集合时显示）。

    2026-07 二期：EOF 载体从 per-entry 布尔改为嵌套集合归属（Entry 叶子集合下的
    "Direct Trigger" 子集合），大纲拖拽本身就是主编辑入口——本面板降级为只读汇总
    （不展开集合树也能一眼看全部直接触发 entry），编辑走大纲拖拽或 Entry Status
    → Activation 面板的切换按钮（efx.eof_toggle_entry）。
    """

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

        # opaque 仅存在于本次改动前保存的旧 .blend（新导入一律 per_entry）
        if model == "opaque":
            box = layout.box()
            box.label(text="EOF imported as read-only by an older version", icon="INFO")
            box.label(text="Re-import the .efx to enable trigger editing")
            return

        # 规范化提示：该文件的 EOF 段原本含越界/重复索引（手工编辑或旧工具的产物），
        # 导入时已丢弃。导出会写成规范形状，与原文件不再逐字节相同 —— 明确告知。
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


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 核心类（PropertyGroup）：先于面板注册
_CLASSES_CORE = (
    EFXPtLifeRefProps,
    EFXPtCollisionRefProps,
)

# 算子类：由 panels.py 注册
_OPERATOR_CLASSES = (
    EFX_OT_eof_toggle_entry,
)

# 面板类：由 panels.py 在 EFX_PT_entry 之后注册（bl_parent_id='EFX_PT_entry'）
_PANEL_CLASSES = (
    EFX_PT_eof_list,
)


def register():
    """
    注册 entry_action_ref 核心类（PropertyGroup）并把属性挂到 Object 上。
    面板类由 panels.py 在 EFX_PT_entry 之后注册。
    """
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
    """
    注销 entry_action_ref 核心类并清理 PointerProperty。
    面板类由 panels.py 先注销。
    """
    for attr in ("efx_ptlife_ref", "efx_ptcollision_ref"):
        try:
            delattr(bpy.types.Object, attr)
        except AttributeError:
            pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
