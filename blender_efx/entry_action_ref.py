"""
blender_efx/entry_action_ref.py  —  L2 #1d：补完 entry/action 引用层指针化

涵盖三项：
  1. PtLife.relationIndex     → action 指针（int16，偏移 8）
  2. PtCollision.ieIndex      → action 指针（int32，偏移 96）
  3. eof_ints（End 段）       → 有序 entry 指针列表（CollectionProperty）

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
§ 3  eof_ints（End 段，entry 索引列表）
────────────────────────────────────────────────────────────────────────────
当前（L1.0）存储：root_obj["eof_ints"] = 逗号分隔十进制字符串（如 "0,1,2,9"）。
L2 #1d 升级：改为 CollectionProperty（有序列表），每项：
  body_ptr   : PointerProperty(poll=EFX_ENTRY) — 有效 entry 指针（is_ptr=True 时）
  raw_value  : IntProperty                    — 无法映射的原始整数（is_ptr=False 时）
  is_ptr     : BoolProperty                   — True=entry 指针；False=原始整数

导入：每个 eof 值 v：
  0 <= v < count_body → entry 指针（is_ptr=True）
  其他               → raw_value（is_ptr=False）
保持顺序。

导出：按顺序，
  is_ptr=True   → body_ptr 经 build_local_index_map 解析回 Entry 局部 index
  is_ptr=False  → raw_value 原样
结果为 uint32 列表，与 export_efx_tree §3 拼接 struct.pack('<I', v) 字节。

byte-perfect 保证：
  - 有效 entry 指针未变 → efx_index == 局部 index == 原始值
  - 无效原始值（99/33/20 等）is_ptr=False → raw_value 原样输出
  - 顺序由 CollectionProperty 顺序决定（导入按 eof_ints 原序填入）

后向兼容：
  若 root_obj 无 efx_eof_list 属性（旧场景/升级），
  导出时回退到 root_obj["eof_ints"] 字符串路径（维持旧行为）。
"""

import struct
import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    PointerProperty,
    CollectionProperty,
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


def _entry_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_ENTRY'，且限定同一 EFX 文件
    （多 EFX 集合并存时防串文件）。已从所有集合解链的孤儿对象（Purge 可清除）排除。"""
    if obj.get("~TYPE") != "EFX_ENTRY":
        return False
    if not obj.users_collection:
        return False
    return _same_root_as_active(obj)


def _action_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_ACTION'，且限定同一 EFX 文件
    （多 EFX 集合并存时防串文件）。"""
    return obj.get("~TYPE") == "EFX_ACTION" and _same_root_as_active(obj)


def _relation_ptr_update(self, context):
    """选中 action 目标后，自动把越界/死属性（pointerized=False）翻转为已指针化，
    使 N 面板成为可恢复入口而非死胡同。清空（None）不改变 pointerized，
    以免误清掉悬空指针的已指针化状态（由现有 dangling 警告负责）。"""
    if self.relation_play_ptr is not None and not self.relation_pointerized:
        self.relation_pointerized = True


def _ie_ptr_update(self, context):
    """PtCollision 版本：选中 action 后从越界/死属性翻转为已指针化。"""
    if self.ie_play_ptr is not None and not self.ie_pointerized:
        self.ie_pointerized = True


# ─────────────────────────────────────────────────────────────────────────────
# §1  PtLife.relationIndex → EFX_ENTRY 指针
# ─────────────────────────────────────────────────────────────────────────────

class EFXPtLifeRefProps(PropertyGroup):
    """
    挂在 EFX_ATTRIBUTE（PTLIFE 类型）对象上（obj.efx_ptlife_ref）。

    字段
    ----
    relation_play_ptr    : PointerProperty → EFX_ACTION 对象（poll=EFX_ACTION）
                           pointerized=True 时有效（非负有效范围内的 action）
    relation_pointerized : BoolProperty    — True=已指针化；False=死属性/越界，原样保留
    """

    relation_play_ptr: PointerProperty(
        name="Relation Action",
        description="The EFX_ACTION (action) object this PtLife attribute's relationIndex points to (action section local index = actionID)",
        type=bpy.types.Object,
        poll=_action_object_poll,
        update=_relation_ptr_update,
    )

    relation_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = relationIndex has been pointerized (0 <= v < count_play); "
            "False = out of range / negative / dead attribute, preserve original bytes (byte-perfect fallback)"
        ),
        default=False,
    )


def init_ptlife_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    play_objs_by_index: dict,
    count_play: int,
) -> None:
    """
    初始化 blk_obj.efx_ptlife_ref PropertyGroup。

    参数
    ----
    blk_obj : bpy.types.Object
        EFX_ATTRIBUTE Empty（PTLIFE 类型）。
    data_bytes : bytes
        该属性的 data_bytes（20 字节）。
    play_objs_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_ACTION 对象} 映射。
    count_play : int
        文件头的 count_play 字段值（hdr.count_play）。

    三种情况：
      1. 0 <= v < count_play → ptr 指向 efx_index==v 的 EFX_ACTION；pointerized=True
      2. 其他（负值/越界）   → pointerized=False（原样，byte-perfect）
    """
    props = blk_obj.efx_ptlife_ref

    # 防御：data_bytes 至少 10 字节（偏移 8 的 int16 需要 8+2=10）
    if len(data_bytes) < 10:
        props.relation_pointerized = False
        return

    # 读 relationIndex（有符号 int16，小端）= actionID（action 段局部 index）
    v = struct.unpack_from('<h', data_bytes, _RELATION_INDEX_OFFSET)[0]

    # 只指针化 [0, count_play) 范围内的值
    if count_play > 0 and 0 <= v < count_play:
        target_obj = play_objs_by_index.get(v)
        if target_obj is not None:
            props.relation_play_ptr = target_obj
            props.relation_pointerized = True
        else:
            # 映射缺失（理论上不该发生），安全回退
            props.relation_pointerized = False
    else:
        # 越界/负值（含 count_play==0 的死属性）→ 原样保留
        props.relation_pointerized = False


def overlay_ptlife_relation_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """
    若 blk_obj.efx_ptlife_ref.relation_pointerized==True，
    覆写 data_bytes 偏移 8 处的 int16（relationIndex）为重算的 action 局部 index。

    参数
    ----
    data_bytes : bytes
        PTLIFE 属性的 data_bytes（20 字节）。
    blk_obj : bpy.types.Object
        EFX_ATTRIBUTE Empty（PTLIFE 类型）。
    play_index_map : dict[bpy.types.Object, int]
        {EFX_ACTION Object → Action 段局部 0-based index}，
        由 build_local_index_map(col_action, 'EFX_ACTION') 或 enumerate(play_objs) 构建。

    返回
    ----
    bytes — 覆写后的 data_bytes；不指针化则原样返回。

    注意
    ----
    - int16：struct.pack_into('<h', buf, 8, new_index)
    - 悬空指针（relation_play_ptr=None）：安全回退，原样返回。
    """
    try:
        props = blk_obj.efx_ptlife_ref
    except AttributeError:
        return data_bytes

    if not props.relation_pointerized:
        return data_bytes

    play_obj = props.relation_play_ptr
    if play_obj is None:
        # 悬空：安全回退
        return data_bytes

    new_index = play_index_map.get(play_obj)
    if new_index is None:
        # play_obj 不在当前 Action 段（跨文件等极端情况）
        return data_bytes

    if len(data_bytes) < 10:
        return data_bytes

    buf = bytearray(data_bytes)
    struct.pack_into('<h', buf, _RELATION_INDEX_OFFSET, new_index)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# §2  PtCollision.ieIndex → EFX_ACTION 指针
# ─────────────────────────────────────────────────────────────────────────────

class EFXPtCollisionRefProps(PropertyGroup):
    """
    挂在 EFX_ATTRIBUTE（PTCOLLISION 类型）对象上（obj.efx_ptcollision_ref）。

    字段
    ----
    ie_play_ptr        : PointerProperty → EFX_ACTION 对象（poll=EFX_ACTION）
                         pointerized=True 且 ie_none=False 时有效
    ie_none            : BoolProperty   — True = ieIndex == -1（哨兵/无目标）
    ie_pointerized     : BoolProperty   — True=已指针化；False=死属性/越界，原样保留
    """

    ie_play_ptr: PointerProperty(
        name="IE Action",
        description="The EFX_ACTION object this PtCollision attribute's ieIndex points to (action section local index)",
        type=bpy.types.Object,
        poll=_action_object_poll,
        update=_ie_ptr_update,
    )

    ie_none: BoolProperty(
        name="No Target (-1)",
        description="True = ieIndex == -1 (sentinel, no action target)",
        default=False,
    )

    ie_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = ieIndex has been pointerized (valid range / -1 sentinel); "
            "False = dead attribute / out of range, preserve original bytes (byte-perfect fallback)"
        ),
        default=False,
    )


def init_ptcollision_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    play_objs_by_index: dict,
    count_play: int,
) -> None:
    """
    初始化 blk_obj.efx_ptcollision_ref PropertyGroup。

    参数
    ----
    blk_obj : bpy.types.Object
        EFX_ATTRIBUTE Empty（PTCOLLISION 类型）。
    data_bytes : bytes
        该属性的 data_bytes（112 字节）。
    play_objs_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_ACTION 对象} 映射。
    count_play : int
        文件头的 count_play 字段值（hdr.count_play）。

    三种情况：
      1. v == -1                → none=True；pointerized=True（哨兵）
      2. 0 <= v < count_play   → ptr 指向 efx_index==v 的 EFX_ACTION；pointerized=True
      3. 其他（越界/count_play=0）→ pointerized=False（原样，byte-perfect）
    """
    props = blk_obj.efx_ptcollision_ref

    # 防御：data_bytes 至少 100 字节（偏移 96 的 int32 需要 96+4=100）
    if len(data_bytes) < 100:
        props.ie_pointerized = False
        return

    # 读 ieIndex（有符号 int32，小端）
    v = struct.unpack_from('<i', data_bytes, _IE_INDEX_OFFSET)[0]

    if v == _SENTINEL_INT32:
        # 哨兵 -1：无目标
        props.ie_none = True
        props.ie_pointerized = True
        return

    if count_play > 0 and 0 <= v < count_play:
        target_obj = play_objs_by_index.get(v)
        if target_obj is not None:
            props.ie_play_ptr = target_obj
            props.ie_pointerized = True
        else:
            props.ie_pointerized = False
        return

    # 越界/count_play=0：死属性路径
    props.ie_pointerized = False


def overlay_ptcollision_ie_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """
    若 blk_obj.efx_ptcollision_ref.ie_pointerized==True，
    覆写 data_bytes 偏移 96 处的 int32（ieIndex）为重算的 action 局部 index。

    参数
    ----
    data_bytes : bytes
        PTCOLLISION 属性的 data_bytes（112 字节）。
    blk_obj : bpy.types.Object
        EFX_ATTRIBUTE Empty（PTCOLLISION 类型）。
    play_index_map : dict[bpy.types.Object, int]
        {EFX_ACTION Object → Action 段局部 0-based index}，
        由 build_local_index_map(col_action, 'EFX_ACTION') 或 enumerate(play_objs) 构建。

    返回
    ----
    bytes — 覆写后的 data_bytes；不指针化则原样返回。

    哨兵路径：ie_none=True → 写 -1（0xFFFFFFFF 有符号补码）。
    悬空指针：ie_play_ptr=None 且 ie_none=False → 安全回退，原样返回。
    """
    try:
        props = blk_obj.efx_ptcollision_ref
    except AttributeError:
        return data_bytes

    if not props.ie_pointerized:
        return data_bytes

    if props.ie_none:
        new_index = _SENTINEL_INT32  # -1
    else:
        play_obj = props.ie_play_ptr
        if play_obj is None:
            return data_bytes
        new_index = play_index_map.get(play_obj)
        if new_index is None:
            return data_bytes

    if len(data_bytes) < 100:
        return data_bytes

    buf = bytearray(data_bytes)
    struct.pack_into('<i', buf, _IE_INDEX_OFFSET, new_index)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# §3  eof_ints（End 段）→ 有序 entry 指针列表
# ─────────────────────────────────────────────────────────────────────────────

class EFXEofItem(PropertyGroup):
    """
    eof_ints 列表中的单个条目。

    is_ptr=True  → body_ptr 有效，导出时解析为 entry 局部 index
    is_ptr=False → raw_value 有效，导出时原样输出（保留 99/33 等无法映射的值）
    """

    body_ptr: PointerProperty(
        name="Entry Object",
        description="The EFX_ENTRY object this eof entry references (valid when is_ptr=True)",
        type=bpy.types.Object,
        poll=_entry_object_poll,
    )

    raw_value: IntProperty(
        name="Raw Value",
        description="Raw integer value that cannot be mapped to a valid entry (valid when is_ptr=False, e.g. 99/33)",
        default=0,
    )

    is_ptr: BoolProperty(
        name="Is Entry Pointer",
        description="True = entry pointer; False = raw integer (unmappable value)",
        default=False,
    )


class EFXEofListProps(PropertyGroup):
    """
    挂在 EFX_ROOT 对象上（root_obj.efx_eof_list）。

    字段
    ----
    items         : CollectionProperty[EFXEofItem]
                    按 eof_ints 原序填入，每项为 entry 指针或原始整数
    active_index  : IntProperty（供 UIList/面板使用，可选）
    """

    items: CollectionProperty(
        name="EOF Items",
        description="List of eof_ints entries in the End section (entry pointers or raw integers, order preserved)",
        type=EFXEofItem,
    )

    active_index: IntProperty(
        name="Active Entry Index",
        description="The currently active eof entry (for UI use)",
        default=0,
        min=0,
    )


def init_eof_list_props(
    root_obj: bpy.types.Object,
    eof_ints: list,
    main_bodies_by_index: dict,
    count_body: int,
) -> None:
    """
    把 eof_ints 整数列表写入 root_obj.efx_eof_list CollectionProperty。

    参数
    ----
    root_obj : bpy.types.Object
        EFX_ROOT Empty 对象。
    eof_ints : list[int]
        解析后的 eof_ints 整数列表（来自 EFXFile.eof_ints）。
    main_bodies_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_ENTRY 对象} 映射。
    count_body : int
        文件头的 count_body 字段值（hdr.count_body）。

    副作用
    ------
    填写 root_obj.efx_eof_list.items（有序）。
    每个值 v：
      0 <= v < count_body → is_ptr=True，body_ptr=对应 entry 对象
      其他               → is_ptr=False，raw_value=v
    """
    props = root_obj.efx_eof_list
    props.items.clear()

    for v in eof_ints:
        item = props.items.add()
        if count_body > 0 and 0 <= v < count_body:
            entry_obj = main_bodies_by_index.get(v)
            if entry_obj is not None:
                item.body_ptr = entry_obj
                item.is_ptr = True
            else:
                # 映射缺失（理论上不该发生），退为原始值
                item.raw_value = v
                item.is_ptr = False
        else:
            # 越界（99/33/20 等）→ 原始整数
            item.raw_value = v
            item.is_ptr = False


def export_eof_ints(
    root_obj: bpy.types.Object,
    entry_index_map: dict,
    sanitize: bool = False,
) -> list:
    """
    从 root_obj.efx_eof_list 还原 eof_ints 整数列表。

    参数
    ----
    root_obj : bpy.types.Object
        EFX_ROOT Empty 对象。
    entry_index_map : dict[bpy.types.Object, int]
        {EFX_ENTRY Object → Main 段局部 0-based index}，
        由 build_local_index_map(col_entry, 'EFX_ENTRY') 或 enumerate(entry_objs) 构建。
    sanitize : bool
        是否清理越界 raw 值（见下）。默认 False（保 byte-perfect）。
        由 io_tree 在 root["eof_dirty"] 时传 True。

    返回
    ----
    list[int]
        eof_ints 整数列表。未编辑时顺序与导入一致（byte-perfect）。

    回退策略
    --------
    若 root_obj 无 efx_eof_list 属性（旧场景），回退到 root_obj["eof_ints"] 字符串路径。

    指针 / raw 处理
    ---------------
    is_ptr=True 但 body_ptr=None（悬空）或不在 entry_index_map → 始终跳过（不写入）。
    is_ptr=False（raw 值）：
      - sanitize=False（未编辑）：原样写回，保 byte-perfect。
      - sanitize=True（eof 被编辑过）：**丢弃越界 raw 值**（< 0 或 >= entry 数）。
        这些是原始文件的"空槽哨兵"（33/99/==count_body 等），不指向真实 entry；编辑激活集/
        增删 entry 后它们成为陈旧的错误索引，会破坏游戏直接触发集 → 特效不生效。
        in-range 的 raw 值（理论上不出现，因 init 时 in-range 必指针化）保守保留。
    """
    try:
        props = root_obj.efx_eof_list
    except AttributeError:
        # 旧场景兼容回退
        return _fallback_eof_ints(root_obj)

    # 防御：若 items 为空且旧字符串存在，用旧路径（避免空列表覆盖）
    if len(props.items) == 0:
        # 尝试从旧字符串恢复（升级兼容）
        fallback = _fallback_eof_ints(root_obj)
        if fallback:
            return fallback
        return []

    n_bodies = len(entry_index_map)
    result = []
    for item in props.items:
        if item.is_ptr:
            entry_obj = item.body_ptr
            if entry_obj is None:
                # 悬空：跳过
                continue
            local_idx = entry_index_map.get(entry_obj)
            if local_idx is None:
                # entry_obj 不在当前 Main 段
                continue
            result.append(local_idx)
        else:
            rv = item.raw_value
            if sanitize and (rv < 0 or rv >= n_bodies):
                # eof 被编辑过：丢弃越界空槽哨兵（陈旧错误索引）
                continue
            result.append(rv)

    return result


def _fallback_eof_ints(root_obj: bpy.types.Object) -> list:
    """
    从旧的逗号字符串自定义属性 eof_ints 还原列表（后向兼容）。
    """
    try:
        s = str(root_obj["eof_ints"]).strip()
        return [int(x) for x in s.split(",") if x] if s else []
    except (KeyError, ValueError, TypeError):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# §3b  eof 载体下放到 entry（hybrid 闸门）—— 结构权威下放重构
# ─────────────────────────────────────────────────────────────────────────────
#
# eof 段（End 直接触发集）语义**不统一**（语料实证，见 memory
# official-samples-authoritative）：99.8% 文件 = 干净的 entry 索引激活集；
# ~0.2%（全是 evc 事件/过场特效）= 装浮点结构的数据，不是索引。故 hybrid：
#
#   干净 = (eof_ints == sorted(set(eof_ints)) 且全部 0<=v<count_body)
#     → 模型 "per_entry"：载体下放到每个 entry 的 efx_direct_trigger 布尔。
#       悬空指针从原理上消失（entry 在则 flag 在，删 entry flag 随之走）；
#       raw 哨兵噪声自动清零。导出按 entry 局部 index **升序**重建。
#   不干净（evc 浮点结构等）
#     → 模型 "opaque"：整个 eof 段作为 root["eof_ints"] 字符串原样直通，
#       不建 bool。这些文件保持 byte-perfect、完全不动。
#
# 后向兼容：旧 .blend 无 eof_model → export 回退到 §3 的 export_eof_ints（efx_eof_list）。

def eof_is_clean(eof_ints: list, count_body: int) -> bool:
    """判定 eof 是否"干净"（可下放 per-entry bool）：升序 + 无重复 + 全部 in-range。
    空列表视为干净（sorted(set([]))==[] 且 all() 空真）。"""
    lst = list(eof_ints)
    if any(not (0 <= v < count_body) for v in lst):
        return False
    return lst == sorted(set(lst))


def init_eof_per_entry(
    root_obj: bpy.types.Object,
    eof_ints: list,
    main_bodies_by_index: dict,
    count_body: int,
) -> None:
    """
    导入端 hybrid：干净 → 设 root["eof_model"]="per_entry" + 每个 entry 的
    efx_direct_trigger；不干净 → "opaque"，保留 root["eof_ints"] 字符串直通。
    """
    if eof_is_clean(eof_ints, count_body):
        root_obj["eof_model"] = "per_entry"
        active = set(int(v) for v in eof_ints)
        for idx, obj in main_bodies_by_index.items():
            try:
                obj.efx_direct_trigger = (idx in active)
            except (AttributeError, TypeError):
                pass
    else:
        root_obj["eof_model"] = "opaque"
        # root["eof_ints"] 字符串已在 io_tree §3 写入，原样直通即可。


def export_eof_per_entry(
    root_obj: bpy.types.Object,
    entry_index_map: dict,
    sanitize: bool = False,
) -> list:
    """
    导出端 hybrid：
      per_entry → 收集 efx_direct_trigger==True 的 entry，经 entry_index_map 映射到
                  导出局部 index，**升序**返回（忠实重建）。
      opaque    → root["eof_ints"] 字符串原样。
      无 eof_model（旧 .blend）→ 回退 §3 的 export_eof_ints。
    """
    model = str(root_obj.get("eof_model", ""))
    if model == "per_entry":
        out = []
        for obj, idx in entry_index_map.items():
            try:
                if obj.efx_direct_trigger:
                    out.append(idx)
            except AttributeError:
                pass
        return sorted(out)
    if model == "opaque":
        return _fallback_eof_ints(root_obj)
    # 旧 .blend：回退到 efx_eof_list / 字符串路径
    return export_eof_ints(root_obj, entry_index_map, sanitize=sanitize)


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


# ─────────────────────────────────────────────────────────────────────────────
# §5  面板：PtLife relationIndex / PtCollision ieIndex
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_ptlife_ref(bpy.types.Panel):
    """
    PtLife 属性的 relationIndex action 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_ATTRIBUTE（PTLIFE 类型）时显示：
      - pointerized=False：显示"越界/死块"警告（原始字节保留）
      - pointerized=True ：EFX_ACTION(action) 对象选择器
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Relation Action Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            from ..efx_format.hashes import PTLIFE as _PTLIFE_HASH
            bp = obj.efx_block
            return int(bp.type_hash_str) == _PTLIFE_HASH
        except (AttributeError, ValueError, ImportError):
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_ptlife_ref
        except AttributeError:
            layout.label(text=T("ptref.no_ptlife_data"), icon="ERROR")
            return

        box = layout.box()
        box.label(text=T("ptref.relation_index_title"), icon="LINKED")

        if not props.relation_pointerized:
            # 越界/死属性：原始字节保留。提供 action 选择器作为恢复入口——
            # 选中后 _relation_ptr_update 翻转 pointerized=True，导出时 overlay
            # 在 fallback 路径写回正确索引（不依赖 efx_dirty）。
            warn = box.row()
            warn.enabled = False
            warn.label(text=T("ptref.relation_oob"), icon="ERROR")
            box.prop(props, "relation_play_ptr", text=T("ptref.assign_action"))
            hint = box.row()
            hint.enabled = False
            hint.label(text=T("ptref.assign_hint"))
            return

        row = box.row(align=True)
        row.prop(props, "relation_play_ptr", text=T("ptref.action_object"))

        if props.relation_play_ptr is None:
            warn = box.row()
            warn.alert = True
            warn.label(text=T("ptref.dangling"), icon="ERROR")
        else:
            play_obj = props.relation_play_ptr
            play_idx = play_obj.get("efx_index", "?")
            info = box.row()
            info.label(text=T("ptref.action_local_index") + " " + str(play_idx), icon="INFO")


class EFX_PT_ptcollision_ref(bpy.types.Panel):
    """
    PtCollision 属性的 ieIndex action 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_ATTRIBUTE（PTCOLLISION 类型）时显示：
      - pointerized=False：显示"越界/死块"警告
      - pointerized=True + ie_none=True：显示"无目标（-1 哨兵）"
      - pointerized=True + ie_none=False：EFX_ACTION 对象选择器
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "IE Action Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            from ..efx_format.hashes import PTCOLLISION as _PTCOLLISION_HASH
            bp = obj.efx_block
            return int(bp.type_hash_str) == _PTCOLLISION_HASH
        except (AttributeError, ValueError, ImportError):
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_ptcollision_ref
        except AttributeError:
            layout.label(text=T("ptref.no_ptcollision_data"), icon="ERROR")
            return

        box = layout.box()
        box.label(text=T("ptref.ie_index_title"), icon="LINKED")

        if not props.ie_pointerized:
            # 越界/死属性：原始字节保留。提供 action 选择器作为恢复入口——
            # 选中后 _ie_ptr_update 翻转 ie_pointerized=True，导出时 overlay 写回。
            warn = box.row()
            warn.enabled = False
            warn.label(text=T("ptref.ie_oob"), icon="ERROR")
            box.prop(props, "ie_play_ptr", text=T("ptref.assign_action"))
            hint = box.row()
            hint.enabled = False
            hint.label(text=T("ptref.assign_hint"))
            return

        row = box.row(align=True)
        row.prop(props, "ie_none", text=T("ptref.no_target_sentinel"))

        if props.ie_none:
            row2 = box.row(align=True)
            row2.enabled = False
            row2.prop(props, "ie_play_ptr", text=T("ptref.action_object"))
        else:
            row2 = box.row(align=True)
            row2.prop(props, "ie_play_ptr", text=T("ptref.action_object"))
            if props.ie_play_ptr is None:
                warn = box.row()
                warn.alert = True
                warn.label(text=T("ptref.dangling"), icon="ERROR")
            else:
                play_obj = props.ie_play_ptr
                play_idx = play_obj.get("efx_index", "?")
                info = box.row()
                info.label(text=T("ptref.action_local_index") + " " + str(play_idx), icon="INFO")


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

        # per_entry 模型（新导入）：直接翻转 entry 的 efx_direct_trigger 布尔。
        if str(root.get("eof_model", "")) == "per_entry":
            cur = bool(getattr(entry_obj, "efx_direct_trigger", False))
            entry_obj.efx_direct_trigger = not cur
            self.report({"INFO"},
                        f"{'Removed' if cur else 'Added'} {entry_obj.name} "
                        f"{'from' if cur else 'to'} direct-trigger set")
            return {"FINISHED"}

        # opaque（evc 事件特效）：不可编辑 eof。
        if str(root.get("eof_model", "")) == "opaque":
            self.report({"WARNING"},
                        "This EFX's EOF section holds non-index (event) data and is read-only")
            return {"CANCELLED"}

        # 旧 .blend（无 eof_model）：走原 efx_eof_list 路径。
        try:
            props = root.efx_eof_list
        except AttributeError:
            self.report({"ERROR"}, "Root object has no efx_eof_list property")
            return {"CANCELLED"}
        found_idx = None
        for i, item in enumerate(props.items):
            if item.is_ptr and item.body_ptr == entry_obj:
                found_idx = i
                break
        if found_idx is not None:
            props.items.remove(found_idx)
            self.report({"INFO"}, f"Removed {entry_obj.name} from EOF list")
        else:
            item = props.items.add()
            item.is_ptr = True
            item.body_ptr = entry_obj
            self.report({"INFO"}, f"Added {entry_obj.name} to EOF list")
        root["eof_dirty"] = 1
        return {"FINISHED"}


def is_entry_in_eof(entry_obj: bpy.types.Object) -> bool:
    """查询 entry_obj 是否在所属根文件的 eof 直接触发集中。供面板绘制使用。"""
    root = _rc.find_root_collection(entry_obj) if entry_obj else None
    if root is None:
        return False
    # per_entry 模型：直接读布尔。
    if str(root.get("eof_model", "")) == "per_entry":
        return bool(getattr(entry_obj, "efx_direct_trigger", False))
    # opaque / 旧 .blend：走 efx_eof_list。
    try:
        props = root.efx_eof_list
    except AttributeError:
        return False
    for item in props.items:
        if item.is_ptr and item.body_ptr == entry_obj:
            return True
    return False


class EFX_OT_eof_add_entry(bpy.types.Operator):
    """Add an entry selected in the picker to the root file's EOF direct-trigger list"""

    bl_idname      = "efx.eof_add_entry"
    bl_label       = "Add Entry to Direct Trigger List"
    bl_description = "Add the selected EFX_ENTRY to the direct-trigger (EOF) list"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not _rc.is_root_collection(context.collection):
            return False
        wm = context.window_manager
        return getattr(wm, "efx_eof_entry_to_add", None) is not None

    def execute(self, context):
        root = context.collection
        wm = context.window_manager
        entry_obj = wm.efx_eof_entry_to_add
        if entry_obj is None:
            return {"CANCELLED"}
        try:
            props = root.efx_eof_list
        except AttributeError:
            self.report({"ERROR"}, "Root object has no efx_eof_list property")
            return {"CANCELLED"}
        for item in props.items:
            if item.is_ptr and item.body_ptr == entry_obj:
                self.report({"WARNING"}, f"{entry_obj.name} is already in the list")
                return {"CANCELLED"}
        item = props.items.add()
        item.is_ptr = True
        item.body_ptr = entry_obj
        root["eof_dirty"] = 1  # 激活集被编辑 → 导出端清理越界 raw 哨兵
        self.report({"INFO"}, f"Added {entry_obj.name} to EOF list")
        return {"FINISHED"}


class EFX_OT_eof_remove_entry(bpy.types.Operator):
    """Remove a specific entry from the root file's EOF list"""

    bl_idname      = "efx.eof_remove_entry"
    bl_label       = "Remove EOF Entry"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: bpy.props.IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        return _rc.is_root_collection(context.collection)

    def execute(self, context):
        root = context.collection
        try:
            props = root.efx_eof_list
        except AttributeError:
            return {"CANCELLED"}
        if 0 <= self.entry_index < len(props.items):
            props.items.remove(self.entry_index)
            root["eof_dirty"] = 1  # 激活集被编辑 → 导出端清理越界 raw 哨兵
        return {"FINISHED"}


class EFX_PT_eof_list(bpy.types.Panel):
    """EFX_ROOT 对象的 EOF 激活 entry 列表面板（可编辑）"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Direct Trigger List"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _rc.is_root_collection(context.collection)

    def draw(self, context):
        layout = self.layout
        obj = context.collection
        model = str(obj.get("eof_model", ""))

        # ── per_entry 模型（新导入的干净文件）：每个 entry 一个直接触发勾选 ──────────
        # 载体下放到 entry 的 efx_direct_trigger，悬空/raw 噪声从原理上不存在。
        if model == "per_entry":
            entries = _rc.collect_top_level(obj, "EFX_ENTRY")
            n_active = sum(1 for e in entries if getattr(e, "efx_direct_trigger", False))
            layout.label(text=T("ptref.game_activated_entries") + f"({n_active})", icon="SORTBYEXT")
            col = layout.column(align=True)
            for e in entries:
                row = col.row(align=True)
                row.scale_y = 0.85
                row.prop(e, "efx_direct_trigger",
                         text=f"[{e.get('efx_index', '?')}] {e.name}")
            return

        # ── opaque 模型（evc 事件特效，EOF 装非索引浮点结构）：只读 ───────────────
        if model == "opaque":
            box = layout.box()
            box.label(text="EOF holds non-index (event) data", icon="INFO")
            box.label(text="Read-only; preserved verbatim on export")
            return

        # ── 旧 .blend（无 eof_model）：原 efx_eof_list 路径（后向兼容）────────────
        try:
            props = obj.efx_eof_list
        except AttributeError:
            layout.label(text=T("ptref.no_eof_data"), icon="ERROR")
            return

        # ── 选择器 + 添加按钮 ────────────────────────────────────────────────
        add_row = layout.row(align=True)
        add_row.prop(context.window_manager, "efx_eof_entry_to_add", text="", icon="OBJECT_DATA")
        add_row.operator("efx.eof_add_entry", text="", icon="ADD")

        layout.separator(factor=0.3)

        n = len(props.items)
        layout.label(text=T("ptref.game_activated_entries") + f"({n})", icon="SORTBYEXT")

        if n == 0:
            layout.label(text=T("ptref.eof_empty"), icon="INFO")
            return

        # 当前 entry 数（有效 eof 索引上界）：判定 raw 值是否越界空槽哨兵
        n_bodies = len(_rc.collect_top_level(obj, "EFX_ENTRY"))
        has_oob_raw = False

        col = layout.column(align=True)
        for i, item in enumerate(props.items):
            row = col.row(align=True)
            row.scale_y = 0.85
            if item.is_ptr:
                entry_obj = item.body_ptr
                if entry_obj is not None:
                    body_idx = entry_obj.get("efx_index", "?")
                    row.label(
                        text=f"[{body_idx}] {entry_obj.name}",
                        icon="OBJECT_DATA",
                    )
                else:
                    row.label(text=T("ptref.dangling_pointer"), icon="ERROR")
            else:
                rv = item.raw_value
                if rv < 0 or rv >= n_bodies:
                    # 越界空槽哨兵：不指向真实 entry，编辑激活集后导出会清理
                    has_oob_raw = True
                    row.label(text=T("ptref.eof_sentinel").format(v=rv), icon="UNLINKED")
                else:
                    row.label(text=f"raw={rv}", icon="DOT")
            op = row.operator("efx.eof_remove_entry", text="", icon="X")
            op.entry_index = i

        if has_oob_raw:
            note = layout.box()
            note.label(text=T("ptref.eof_sentinel_hint"), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 核心类（PropertyGroup）：先于面板注册
_CLASSES_CORE = (
    EFXPtLifeRefProps,
    EFXPtCollisionRefProps,
    EFXEofItem,
    EFXEofListProps,
)

# 算子类：由 panels.py 注册
_OPERATOR_CLASSES = (
    EFX_OT_eof_toggle_entry,
    EFX_OT_eof_remove_entry,
    EFX_OT_eof_add_entry,
)

# 面板类：由 panels.py 在 EFX_PT_entry 之后注册（bl_parent_id='EFX_PT_entry'）
_PANEL_CLASSES = (
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
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

    bpy.types.Object.efx_eof_list = PointerProperty(
        name="EFX EOF Entry List",
        description="Ordered eof_ints entry pointer list for the EFX_ROOT object (legacy / opaque fallback)",
        type=EFXEofListProps,
    )

    # eof 载体下放到 entry（hybrid "per_entry" 模型）：每个 EFX_ENTRY 一个布尔，
    # 表示是否在 EOF 直接触发集内。悬空指针从原理上消失（见 init_eof_per_entry）。
    bpy.types.Object.efx_direct_trigger = BoolProperty(
        name="Direct Trigger",
        description=(
            "Whether this entry is in the EOF direct-trigger set — direct-trigger entries "
            "fire with the EFX unless gated by a subselect state; entries absent here can "
            "still be summoned by Action calls. Per-entry EOF carrier (clean files)"
        ),
        default=False,
    )

    bpy.types.WindowManager.efx_eof_entry_to_add = PointerProperty(
        name="Entry to Add",
        description="Select an EFX_ENTRY to add to the direct-trigger (EOF) list",
        type=bpy.types.Object,
        poll=_entry_object_poll,
    )


def unregister():
    """
    注销 entry_action_ref 核心类并清理 PointerProperty。
    面板类由 panels.py 先注销。
    """
    for attr in ("efx_ptlife_ref", "efx_ptcollision_ref", "efx_eof_list", "efx_direct_trigger"):
        try:
            delattr(bpy.types.Object, attr)
        except AttributeError:
            pass

    try:
        delattr(bpy.types.WindowManager, "efx_eof_entry_to_add")
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
