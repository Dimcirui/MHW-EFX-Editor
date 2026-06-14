"""
blender_efx/body_play_ref.py  —  L2 #1d：补完 body/play 引用层指针化

涵盖三项：
  1. PtLife.relationIndex     → play(action) 指针（int16，偏移 8）
  2. PtCollision.ieIndex      → play 指针（int32，偏移 96）
  3. eof_ints（End 段）       → 有序 body 指针列表（CollectionProperty）

设计原则（参照 CLAUDE.md / extern_ref.py 模式）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集（PropertyGroup / CollectionProperty / PointerProperty /
    BoolProperty / IntProperty / Panel）
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：死块/越界/哨兵均原样往返

────────────────────────────────────────────────────────────────────────────
§ 1  PtLife.relationIndex（int16）
────────────────────────────────────────────────────────────────────────────
PTLIFE_SCHEMA：short[10]，共 20 字节（no leading type_hash）。
  offset  0: h unkn0
  offset  2: h unkn1
  offset  4: h timing
  offset  6: h unkn3
  offset  8: h relationIndex   ← 指针化目标字段（int16 有符号）
  ...

实测语义（社区教程 + 语料复核，2026-06 修正）：
  值 v（int16 有符号）= **actionID** = PLAY 段局部 0-based index（EFX_PLAY）。
  依据：canni《ACTION 结构》《延迟火》教程均写 relationIndex=actionID；
  178 样本复核——18 个"有 action"（count_play>0）的文件里，每个
  max(relationIndex)==count_play-1，无一越过 count_play（count_body 是
  7~23 的大范围却从不被触及，如 ymt006 cp=3 用到 2、boom cp=2 用 1）。
  若是 body index，值本应散布 [0,count_body)，但全部紧贴 [0,count_play)。
  早先误判 body 的 5 个样本全来自 count_play==0 的文件 = 死 PTLIFE 残留块。

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
  boom.efx body[4/5] ieIndex=0 → play[0]="ACT_PTC"（粒子碰撞播放器）
  ymt006 body[3] ieIndex=1     → play[1]="ACT_PTC"
  → play 段局部 index（EFX_PLAY）

0xFFFFFFFF / -1 哨兵：corpus 中未观测，但按设计保守支持（参照 BLUEPRINT §9）。
  若 v == -1（有符号）：none=True；pointerized=True。
  0 <= v < count_play：有效 play 指针；pointerized=True。
  其他（越界/count_play=0）：pointerized=False，原样保留。

导出覆写：struct.pack_into('<i', buf, 96, new_index)  （int32，偏移 96）

────────────────────────────────────────────────────────────────────────────
§ 3  eof_ints（End 段，body 索引列表）
────────────────────────────────────────────────────────────────────────────
当前（L1.0）存储：root_obj["eof_ints"] = 逗号分隔十进制字符串（如 "0,1,2,9"）。
L2 #1d 升级：改为 CollectionProperty（有序列表），每项：
  body_ptr   : PointerProperty(poll=EFX_BODY) — 有效 body 指针（is_ptr=True 时）
  raw_value  : IntProperty                    — 无法映射的原始整数（is_ptr=False 时）
  is_ptr     : BoolProperty                   — True=body 指针；False=原始整数

导入：每个 eof 值 v：
  0 <= v < count_body → body 指针（is_ptr=True）
  其他               → raw_value（is_ptr=False）
保持顺序。

导出：按顺序，
  is_ptr=True   → body_ptr 经 build_local_index_map 解析回 Main 局部 index
  is_ptr=False  → raw_value 原样
结果为 uint32 列表，与 export_efx_tree §3 拼接 struct.pack('<I', v) 字节。

byte-perfect 保证：
  - 有效 body 指针未变 → efx_index == 局部 index == 原始值
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

def _find_root_obj(obj):
    """沿 parent 链向上找 ~TYPE == 'EFX_ROOT' 的对象，找不到返回 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _same_root_as_active(obj):
    """obj 是否与当前活动对象处于同一 EFX 文件（同一 EFX_ROOT）。
    活动对象或任一方无 root 时不限制（返回 True），仅在确属不同 root 时排除。"""
    editing = getattr(bpy.context, "active_object", None)
    if editing is None:
        return True
    root_self = _find_root_obj(editing)
    root_obj = _find_root_obj(obj)
    if root_self is not None and root_obj is not None and root_self is not root_obj:
        return False
    return True


def _body_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_BODY'，且限定同一 EFX 文件
    （多 EFX 集合并存时防串文件）。"""
    return obj.get("~TYPE") == "EFX_BODY" and _same_root_as_active(obj)


def _play_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_PLAY'，且限定同一 EFX 文件
    （多 EFX 集合并存时防串文件）。"""
    return obj.get("~TYPE") == "EFX_PLAY" and _same_root_as_active(obj)


# ─────────────────────────────────────────────────────────────────────────────
# §1  PtLife.relationIndex → EFX_BODY 指针
# ─────────────────────────────────────────────────────────────────────────────

class EFXPtLifeRefProps(PropertyGroup):
    """
    挂在 EFX_BLOCK（PTLIFE 类型）对象上（obj.efx_ptlife_ref）。

    字段
    ----
    relation_play_ptr    : PointerProperty → EFX_PLAY 对象（poll=EFX_PLAY）
                           pointerized=True 时有效（非负有效范围内的 play/action）
    relation_pointerized : BoolProperty    — True=已指针化；False=死块/越界，原样保留
    """

    relation_play_ptr: PointerProperty(
        name="Relation Action",
        description="The EFX_PLAY (action) object this PtLife block's relationIndex points to (play section local index = actionID)",
        type=bpy.types.Object,
        poll=_play_object_poll,
    )

    relation_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = relationIndex has been pointerized (0 <= v < count_play); "
            "False = out of range / negative / dead block, preserve original bytes (byte-perfect fallback)"
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
        EFX_BLOCK Empty（PTLIFE 类型）。
    data_bytes : bytes
        该块的 data_bytes（20 字节）。
    play_objs_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_PLAY 对象} 映射。
    count_play : int
        文件头的 count_play 字段值（hdr.count_play）。

    三种情况：
      1. 0 <= v < count_play → ptr 指向 efx_index==v 的 EFX_PLAY；pointerized=True
      2. 其他（负值/越界）   → pointerized=False（原样，byte-perfect）
    """
    props = blk_obj.efx_ptlife_ref

    # 防御：data_bytes 至少 10 字节（偏移 8 的 int16 需要 8+2=10）
    if len(data_bytes) < 10:
        props.relation_pointerized = False
        return

    # 读 relationIndex（有符号 int16，小端）= actionID（play 段局部 index）
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
        # 越界/负值（含 count_play==0 的死块）→ 原样保留
        props.relation_pointerized = False


def overlay_ptlife_relation_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """
    若 blk_obj.efx_ptlife_ref.relation_pointerized==True，
    覆写 data_bytes 偏移 8 处的 int16（relationIndex）为重算的 play 局部 index。

    参数
    ----
    data_bytes : bytes
        PTLIFE 块的 data_bytes（20 字节）。
    blk_obj : bpy.types.Object
        EFX_BLOCK Empty（PTLIFE 类型）。
    play_index_map : dict[bpy.types.Object, int]
        {EFX_PLAY Object → Play 段局部 0-based index}，
        由 build_local_index_map(col_play, 'EFX_PLAY') 或 enumerate(play_objs) 构建。

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
        # play_obj 不在当前 Play 段（跨文件等极端情况）
        return data_bytes

    if len(data_bytes) < 10:
        return data_bytes

    buf = bytearray(data_bytes)
    struct.pack_into('<h', buf, _RELATION_INDEX_OFFSET, new_index)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# §2  PtCollision.ieIndex → EFX_PLAY 指针
# ─────────────────────────────────────────────────────────────────────────────

class EFXPtCollisionRefProps(PropertyGroup):
    """
    挂在 EFX_BLOCK（PTCOLLISION 类型）对象上（obj.efx_ptcollision_ref）。

    字段
    ----
    ie_play_ptr        : PointerProperty → EFX_PLAY 对象（poll=EFX_PLAY）
                         pointerized=True 且 ie_none=False 时有效
    ie_none            : BoolProperty   — True = ieIndex == -1（哨兵/无目标）
    ie_pointerized     : BoolProperty   — True=已指针化；False=死块/越界，原样保留
    """

    ie_play_ptr: PointerProperty(
        name="IE Play",
        description="The EFX_PLAY object this PtCollision block's ieIndex points to (play section local index)",
        type=bpy.types.Object,
        poll=_play_object_poll,
    )

    ie_none: BoolProperty(
        name="No Target (-1)",
        description="True = ieIndex == -1 (sentinel, no play target)",
        default=False,
    )

    ie_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = ieIndex has been pointerized (valid range / -1 sentinel); "
            "False = dead block / out of range, preserve original bytes (byte-perfect fallback)"
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
        EFX_BLOCK Empty（PTCOLLISION 类型）。
    data_bytes : bytes
        该块的 data_bytes（112 字节）。
    play_objs_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_PLAY 对象} 映射。
    count_play : int
        文件头的 count_play 字段值（hdr.count_play）。

    三种情况：
      1. v == -1                → none=True；pointerized=True（哨兵）
      2. 0 <= v < count_play   → ptr 指向 efx_index==v 的 EFX_PLAY；pointerized=True
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

    # 越界/count_play=0：死块路径
    props.ie_pointerized = False


def overlay_ptcollision_ie_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    play_index_map: dict,
) -> bytes:
    """
    若 blk_obj.efx_ptcollision_ref.ie_pointerized==True，
    覆写 data_bytes 偏移 96 处的 int32（ieIndex）为重算的 play 局部 index。

    参数
    ----
    data_bytes : bytes
        PTCOLLISION 块的 data_bytes（112 字节）。
    blk_obj : bpy.types.Object
        EFX_BLOCK Empty（PTCOLLISION 类型）。
    play_index_map : dict[bpy.types.Object, int]
        {EFX_PLAY Object → Play 段局部 0-based index}，
        由 build_local_index_map(col_play, 'EFX_PLAY') 或 enumerate(play_objs) 构建。

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
# §3  eof_ints（End 段）→ 有序 body 指针列表
# ─────────────────────────────────────────────────────────────────────────────

class EFXEofItem(PropertyGroup):
    """
    eof_ints 列表中的单个条目。

    is_ptr=True  → body_ptr 有效，导出时解析为 body 局部 index
    is_ptr=False → raw_value 有效，导出时原样输出（保留 99/33 等无法映射的值）
    """

    body_ptr: PointerProperty(
        name="Body Object",
        description="The EFX_BODY object this eof entry references (valid when is_ptr=True)",
        type=bpy.types.Object,
        poll=_body_object_poll,
    )

    raw_value: IntProperty(
        name="Raw Value",
        description="Raw integer value that cannot be mapped to a valid body (valid when is_ptr=False, e.g. 99/33)",
        default=0,
    )

    is_ptr: BoolProperty(
        name="Is Body Pointer",
        description="True = body pointer; False = raw integer (unmappable value)",
        default=False,
    )


class EFXEofListProps(PropertyGroup):
    """
    挂在 EFX_ROOT 对象上（root_obj.efx_eof_list）。

    字段
    ----
    items         : CollectionProperty[EFXEofItem]
                    按 eof_ints 原序填入，每项为 body 指针或原始整数
    active_index  : IntProperty（供 UIList/面板使用，可选）
    """

    items: CollectionProperty(
        name="EOF Items",
        description="List of eof_ints entries in the End section (body pointers or raw integers, order preserved)",
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
        {efx_index → EFX_BODY 对象} 映射。
    count_body : int
        文件头的 count_body 字段值（hdr.count_body）。

    副作用
    ------
    填写 root_obj.efx_eof_list.items（有序）。
    每个值 v：
      0 <= v < count_body → is_ptr=True，body_ptr=对应 body 对象
      其他               → is_ptr=False，raw_value=v
    """
    props = root_obj.efx_eof_list
    props.items.clear()

    for v in eof_ints:
        item = props.items.add()
        if count_body > 0 and 0 <= v < count_body:
            body_obj = main_bodies_by_index.get(v)
            if body_obj is not None:
                item.body_ptr = body_obj
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
    body_index_map: dict,
) -> list:
    """
    从 root_obj.efx_eof_list 还原 eof_ints 整数列表。

    参数
    ----
    root_obj : bpy.types.Object
        EFX_ROOT Empty 对象。
    body_index_map : dict[bpy.types.Object, int]
        {EFX_BODY Object → Main 段局部 0-based index}，
        由 build_local_index_map(col_main, 'EFX_BODY') 或 enumerate(body_objs) 构建。

    返回
    ----
    list[int]
        eof_ints 整数列表（顺序与导入时一致，byte-perfect）。

    回退策略
    --------
    若 root_obj 无 efx_eof_list 属性（旧场景），回退到 root_obj["eof_ints"] 字符串路径。

    悬空 body_ptr 处理
    ------------------
    is_ptr=True 但 body_ptr=None（悬空）→ 静默跳过（不写入）。
    后续校验阶段应改为报错。
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

    result = []
    for item in props.items:
        if item.is_ptr:
            body_obj = item.body_ptr
            if body_obj is None:
                # 悬空：跳过（后续校验阶段应报错）
                continue
            local_idx = body_index_map.get(body_obj)
            if local_idx is None:
                # body_obj 不在当前 Main 段
                continue
            result.append(local_idx)
        else:
            result.append(item.raw_value)

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
# §4  覆写 helper（供 io_tree 导出时调用）
# ─────────────────────────────────────────────────────────────────────────────

def apply_block_ref_overlays(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    body_index_map: dict,
    play_index_map: dict,
) -> bytes:
    """
    对单个 EFX_BLOCK 对象，按其类型应用 L2 #1d 的字段覆写：
      - PTLIFE      → overlay_ptlife_relation_index（play index，int16，偏移 8）
      - PTCOLLISION → overlay_ptcollision_ie_index（play index，int32，偏移 96）
      - 其他        → 原样返回

    参数
    ----
    data_bytes     : bytes     — 块当前的 data_bytes（已由 fields 层处理完毕）
    blk_obj        : Object    — EFX_BLOCK Empty
    body_index_map : dict      — {EFX_BODY Object → main 局部 index}
    play_index_map : dict      — {EFX_PLAY Object → play 局部 index}

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
    PtLife 块的 relationIndex action(play) 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_BLOCK（PTLIFE 类型）时显示：
      - pointerized=False：显示"越界/死块"警告（原始字节保留）
      - pointerized=True ：EFX_PLAY(action) 对象选择器
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Relation Action Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
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
            row = box.row()
            row.enabled = False
            row.label(text=T("ptref.relation_oob"), icon="ERROR")
            return

        row = box.row(align=True)
        row.prop(props, "relation_play_ptr", text=T("ptref.play_object"))

        if props.relation_play_ptr is None:
            warn = box.row()
            warn.alert = True
            warn.label(text=T("ptref.dangling"), icon="ERROR")
        else:
            play_obj = props.relation_play_ptr
            play_idx = play_obj.get("efx_index", "?")
            info = box.row()
            info.label(text=T("ptref.play_local_index") + " " + str(play_idx), icon="INFO")


class EFX_PT_ptcollision_ref(bpy.types.Panel):
    """
    PtCollision 块的 ieIndex play 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_BLOCK（PTCOLLISION 类型）时显示：
      - pointerized=False：显示"越界/死块"警告
      - pointerized=True + ie_none=True：显示"无目标（-1 哨兵）"
      - pointerized=True + ie_none=False：EFX_PLAY 对象选择器
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "IE Play Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
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
            row = box.row()
            row.enabled = False
            row.label(text=T("ptref.ie_oob"), icon="ERROR")
            return

        row = box.row(align=True)
        row.prop(props, "ie_none", text=T("ptref.no_target_sentinel"))

        if props.ie_none:
            row2 = box.row(align=True)
            row2.enabled = False
            row2.prop(props, "ie_play_ptr", text=T("ptref.play_object"))
        else:
            row2 = box.row(align=True)
            row2.prop(props, "ie_play_ptr", text=T("ptref.play_object"))
            if props.ie_play_ptr is None:
                warn = box.row()
                warn.alert = True
                warn.label(text=T("ptref.dangling"), icon="ERROR")
            else:
                play_obj = props.ie_play_ptr
                play_idx = play_obj.get("efx_index", "?")
                info = box.row()
                info.label(text=T("ptref.play_local_index") + " " + str(play_idx), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# §6  EOF Body 激活切换算子 + 面板
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_eof_toggle_body(bpy.types.Operator):
    """Toggle whether the current EFX_BODY is in the root file's eof active list"""

    bl_idname      = "efx.eof_toggle_body"
    bl_label       = "Toggle Direct Trigger"
    bl_description = "Add/remove this Body to/from the direct-trigger list (bodies in this list fire automatically when the EFX loads; others can still be activated via Play calls)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BODY":
            return False
        root = obj.parent
        return root is not None and root.get("~TYPE") == "EFX_ROOT"

    def execute(self, context):
        body_obj = context.active_object
        root = body_obj.parent
        try:
            props = root.efx_eof_list
        except AttributeError:
            self.report({"ERROR"}, "Root object has no efx_eof_list property")
            return {"CANCELLED"}

        # 查找已有条目
        found_idx = None
        for i, item in enumerate(props.items):
            if item.is_ptr and item.body_ptr == body_obj:
                found_idx = i
                break

        if found_idx is not None:
            props.items.remove(found_idx)
            self.report({"INFO"}, f"Removed {body_obj.name} from EOF list")
        else:
            item = props.items.add()
            item.is_ptr = True
            item.body_ptr = body_obj
            self.report({"INFO"}, f"Added {body_obj.name} to EOF list")

        return {"FINISHED"}


def is_body_in_eof(body_obj: bpy.types.Object) -> bool:
    """查询 body_obj 是否在所属根文件的 eof 列表中。供面板绘制使用。"""
    root = body_obj.parent if body_obj else None
    if root is None or root.get("~TYPE") != "EFX_ROOT":
        return False
    try:
        props = root.efx_eof_list
    except AttributeError:
        return False
    for item in props.items:
        if item.is_ptr and item.body_ptr == body_obj:
            return True
    return False


class EFX_OT_eof_remove_entry(bpy.types.Operator):
    """Remove a specific entry from the root file's EOF list"""

    bl_idname      = "efx.eof_remove_entry"
    bl_label       = "Remove EOF Entry"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: bpy.props.IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ROOT"

    def execute(self, context):
        root = context.active_object
        try:
            props = root.efx_eof_list
        except AttributeError:
            return {"CANCELLED"}
        if 0 <= self.entry_index < len(props.items):
            props.items.remove(self.entry_index)
        return {"FINISHED"}


class EFX_PT_eof_list(bpy.types.Panel):
    """EFX_ROOT 对象的 EOF 激活 body 列表面板（可编辑）"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Direct Trigger List"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ROOT"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_eof_list
        except AttributeError:
            layout.label(text=T("ptref.no_eof_data"), icon="ERROR")
            return

        n = len(props.items)
        layout.label(text=T("ptref.game_activated_bodies") + f"({n})", icon="SORTBYEXT")

        if n == 0:
            layout.label(text=T("ptref.eof_empty"), icon="INFO")
            return

        col = layout.column(align=True)
        for i, item in enumerate(props.items):
            row = col.row(align=True)
            row.scale_y = 0.85
            if item.is_ptr:
                body_obj = item.body_ptr
                if body_obj is not None:
                    body_idx = body_obj.get("efx_index", "?")
                    row.label(
                        text=f"[{body_idx}] {body_obj.name}",
                        icon="OBJECT_DATA",
                    )
                else:
                    row.label(text=T("ptref.dangling_pointer"), icon="ERROR")
            else:
                row.label(text=f"raw={item.raw_value}", icon="DOT")
            op = row.operator("efx.eof_remove_entry", text="", icon="X")
            op.entry_index = i


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
    EFX_OT_eof_toggle_body,
    EFX_OT_eof_remove_entry,
)

# 面板类：由 panels.py 在 EFX_PT_main 之后注册（bl_parent_id='EFX_PT_main'）
_PANEL_CLASSES = (
    EFX_PT_ptlife_ref,
    EFX_PT_ptcollision_ref,
    EFX_PT_eof_list,
)


def register():
    """
    注册 body_play_ref 核心类（PropertyGroup）并把属性挂到 Object 上。
    面板类由 panels.py 在 EFX_PT_main 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_ptlife_ref = PointerProperty(
        name="EFX PtLife Reference Properties",
        description="relationIndex play(action) pointer data for EFX_BLOCK (PTLIFE type)",
        type=EFXPtLifeRefProps,
    )

    bpy.types.Object.efx_ptcollision_ref = PointerProperty(
        name="EFX PtCollision Reference Properties",
        description="ieIndex play pointer data for EFX_BLOCK (PTCOLLISION type)",
        type=EFXPtCollisionRefProps,
    )

    bpy.types.Object.efx_eof_list = PointerProperty(
        name="EFX EOF Body List",
        description="Ordered eof_ints body pointer list for the EFX_ROOT object",
        type=EFXEofListProps,
    )


def unregister():
    """
    注销 body_play_ref 核心类并清理 PointerProperty。
    面板类由 panels.py 先注销。
    """
    for attr in ("efx_ptlife_ref", "efx_ptcollision_ref", "efx_eof_list"):
        try:
            delattr(bpy.types.Object, attr)
        except AttributeError:
            pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
