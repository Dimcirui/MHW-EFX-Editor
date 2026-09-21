"""
blender_efx/action_emitter.py  —  Action 段的字段编辑 + PlayEmitter targets 指针化

Action 有两种条目，两种的字段都已完全展开可编辑：

  PLAYEMITTER  调用本文件内的 entry。targets 之外是一整套作用于被调用 entry 的 transform：

                   官方名              本文件属性
                   SetLandAttribute    em_unkn1   取命中地面的属性，供按标志位过滤特效
                   SetLandDirection    em_unkn2   让生成实例的矩阵贴合地面倾斜（与 RayCast 并用），这两个对应情况不确定，可能要和上面一个互换
                   Rotation  X/Y/Z     em_rotation
                   Order               em_rotation_order   旋转顺序
                   Scale     X/Y/Z     xyz
                   Translate X/Y/Z     em_position

  PLAYEFX      调用外部 .efx 文件。路径 + Scale(@40) / Translate(@52)，其余槽位与
               PLAYEMITTER 同构。

  ⚠ 内部属性名里的 `unkn*` 对齐 `EFX_Play.bt` 的数组下标（`unkn[0..6]`），只是对照社区模板
    时的溯源线索——**界面上显示的是各自 `name=` 的语义名**，不是 unkn。改属性标识符会让已存
    .blend 里的值回落默认，所以只改 label/description，标识符保持不动。

  字段偏移见 `load_entry_fields_from_raw`（`struct.unpack_from` 的字面量就是权威，
  不在这里复述一遍）。

PropertyGroup 层级：

    obj.efx_play  (EFXActionProps)
      ├── play_type_str : str                        # ActionData.play_type
      └── entries       : [EFXActionEntryProps]
            ├── raw_b64      : str                   # 原始字节，重建失败时的兜底
            ├── is_emitter   : bool                  # 决定走 em_* 还是 pefx_* 那组字段
            ├── fields_loaded: bool                  # ⚠ 见下
            └── targets      : [EFXActionTarget]     # 仅 PLAYEMITTER
                  └── body_ptr : PointerProperty(poll=EFX_ENTRY)

⚠ `fields_loaded=False` 时（raw 长度不足、解析异常或旧 `.blend` 尚未保存这些属性），
  两类 entry 的头部字段沿用原始字节，防止默认 0 覆盖 rotation / rotationOrder 等数据。
  size、PlayEmitter targets 和 PlayEFX 路径仍按现有编辑模型重建；改重建函数时不要绕过
  头部字段的门控。

⚠ 悬空 target（`body_ptr is None`）导出时**跳过不写**，与 subselect.py 一致；
  由 validate.py 统一报 WARN，不阻断导出。

字节行为：PlayEmitter 重建 target_count + targets[]，PlayEFX 重建 path_len + 路径；
其余区间在 fields_loaded 时按属性重写，否则沿用原字节。
"""

import struct
import base64

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    PointerProperty,
    IntProperty,
    FloatProperty,
    FloatVectorProperty,
)
from bpy.types import PropertyGroup, Operator

from ..efx_format.hashes import PLAYEMITTER, PLAYEFX
from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# §1  poll 函数
# ─────────────────────────────────────────────────────────────────────────────

def _entry_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_ENTRY' 的对象，
    且限定为当前编辑的 action 对象**同一个 EFX 文件**（同一 root_col）内的 entry——
    多个 EFX 集合并存时，避免把别的文件的 entry 列进下拉。
    已从所有集合解链的孤儿对象（Purge 可清除）排除。"""
    if obj.get("~TYPE") != "EFX_ENTRY":
        return False
    if not obj.users_collection:
        return False
    # 当前正在编辑 targets 的 action 对象 = 活动对象；按它的 root 限定范围。
    editing = getattr(bpy.context, "active_object", None)
    if editing is not None and not _rc.same_root(editing, obj):
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# §2  PropertyGroup：Action 结构化存储
# ─────────────────────────────────────────────────────────────────────────────

class EFXActionTarget(PropertyGroup):
    """
    PlayEmitter 的单个 target：指向一个 EFX_ENTRY 对象的指针。

    CollectionProperty 元素，挂在 EFXActionEntryProps.targets 上。
    """
    body_ptr: PointerProperty(
        name="Entry Object",
        description="EFX_ENTRY object referenced by this PlayEmitter target",
        type=bpy.types.Object,
        poll=_entry_object_poll,
    )


class EFXActionEntryProps(PropertyGroup):
    """
    ActionData 中单个 ActionEntry 的结构化存储。

    字段
    ----
    type_hash_str : 十进制字符串（uint32，避免 Blender int32 溢出）
    raw_b64       : base64 字符串，entry raw（type_hash 之后的字节），始终保留
    is_emitter    : bool，True = PLAYEMITTER，False = PLAYEFX（或其他）
    targets       : CollectionProperty[EFXActionTarget]，仅 PLAYEMITTER 解析填充
    active_target_index : 供 template_list 使用
    """
    type_hash_str: StringProperty(
        name="Type Hash",
        description="ActionEntry.type_hash (uint32, decimal string)",
        default="0",
    )
    raw_b64: StringProperty(
        name="Raw (b64)",
        description="Base64-encoded raw data for this entry, preserved for any part not exposed as editable fields",
        default="",
    )
    is_emitter: BoolProperty(
        name="Is PlayEmitter",
        description="True = PLAYEMITTER (targets valid), False = PLAYEFX (path + XYZ editable)",
        default=False,
    )
    xyz: FloatVectorProperty(
        name="Size XYZ",
        description="Uniform size scale applied to whatever this entry calls - the entries for "
                    "PlayEmitter, the external .efx for PlayEFX (1.0 = unchanged). Both types "
                    "keep the position offset in a separate slot. (float[3])",
        size=3,
        default=(1.0, 1.0, 1.0),
    )

    # 旧 .blend 可能没有以下结构化字段；仅在成功解析后写回，
    # 避免默认值覆盖 raw_b64 中的原始数据。
    fields_loaded: BoolProperty(
        name="Fields Loaded",
        description="True once the fields below have been loaded from this entry's data. "
                    "Prevents .blend files saved before these fields existed from having "
                    "their data overwritten with zeros",
        default=False,
    )

    # ── PlayEmitter 专属（偏移基于 emitter raw）────────────────────────────────
    em_unkn0: IntProperty(
        name="Type Flags",
        description="Effect unknown. Usually 0; common range is 0~23",
        default=0,
    )
    em_unkn1: BoolProperty(
        name="Set Land Attribute",
        description="Likely sets a land-attribute flag; exact effect unknown",
        default=False,
    )
    em_unkn2: BoolProperty(
        name="Set Land Direction",
        description="Likely sets a land-direction flag; exact effect unknown",
        default=False,
    )
    em_rotation_order: IntProperty(
        name="Rotation Order",
        description="Uses the same rotation-order enum as TRANSFORM3D/EMITTERSHAPE3D "
                    "(default and most common value is 4 = ZXY). What it actually affects "
                    "here is unknown",
        default=4,
    )
    em_rotation: FloatVectorProperty(
        name="Rotation XYZ",
        description="Holds degree-like values (most often -90), but editing it has no "
                    "visible effect in-game — it does not rotate the entries this Action "
                    "calls. Its actual purpose is unknown",
        size=3,
        default=(0.0, 0.0, 0.0),
    )
    em_position: FloatVectorProperty(
        name="Position XYZ",
        description="Position offset applied to the entries this Action calls",
        size=3,
        default=(0.0, 0.0, 0.0),
    )

    # ── PlayEFX 专属（偏移基于 playefx raw；命名对齐 EFX_Play.bt 的字段下标）────
    pefx_unkn0: IntProperty(
        name="Type Flags",
        description="Effect unknown. Shares the same slot as PlayEmitter's Type Flags",
        default=0,
    )
    pefx_type_str: StringProperty(
        name="Type",
        description="Fixed identifier value (decimal); should not need to be changed",
        default="0",
    )
    pefx_unkn_0: BoolProperty(
        name="Set Land Attribute",
        description="Likely sets a land-attribute flag; exact effect unknown. Shares the "
                    "same slot as PlayEmitter's Set Land Attribute",
        default=False,
    )
    pefx_unkn_1: BoolProperty(
        name="Set Land Direction",
        description="Likely sets a land-direction flag; exact effect unknown. Shares the "
                    "same slot as PlayEmitter's Set Land Direction",
        default=False,
    )
    pefx_unkn_2: IntProperty(
        name="Unknown 2",
        description="Fixed at 2 in practice. Has no counterpart in PlayEmitter; its "
                    "purpose is unknown",
        default=2,
    )
    pefx_unkn_3: FloatProperty(
        name="Rotation X",
        description="Common values are 0, -90 or 90. Shares the same slot as PlayEmitter's "
                    "Rotation X. Its actual effect is unknown",
        default=0.0,
    )
    pefx_unkn_4: FloatProperty(
        name="Rotation Y",
        description="Usually 0. Shares the same slot as PlayEmitter's Rotation Y. Its "
                    "actual effect is unknown",
        default=0.0,
    )
    pefx_unkn_5: FloatProperty(
        name="Rotation Z",
        description="Usually 0. Shares the same slot as PlayEmitter's Rotation Z. Its "
                    "actual effect is unknown",
        default=0.0,
    )
    pefx_unkn_6: IntProperty(
        name="Rotation Order",
        description="Uses the same rotation-order enum as PlayEmitter's Rotation Order "
                    "(default 4 = ZXY). What it actually affects here is unknown",
        default=4,
    )
    pefx_null: FloatVectorProperty(
        name="Position XYZ",
        description="Position offset applied to the external .efx this entry calls",
        size=3,
        default=(0.0, 0.0, 0.0),
    )

    efx_path: StringProperty(
        name="EFX Path",
        description="Path to the external .efx file referenced by PlayEFX (null-terminated string)",
        default="",
    )
    targets: CollectionProperty(
        name="Targets",
        description="List of EFX_ENTRY referenced by PlayEmitter (corresponds to the targets[] array)",
        type=EFXActionTarget,
    )
    active_target_index: IntProperty(
        name="Active Target Index",
        description="Currently active target (used by the list UI)",
        default=0,
        min=0,
    )


class EFXActionProps(PropertyGroup):
    """
    挂在 EFX_ACTION Empty 对象上（obj.efx_play）的 PropertyGroup。

    字段
    ----
    play_type_str : ActionData.play_type（uint32 十进制字符串）
    entries       : CollectionProperty[EFXActionEntryProps]，该 ActionData 的全部 entry
    active_entry_index : 供 template_list 使用
    """
    play_type_str: StringProperty(
        name="Play Type",
        description="ActionData.play_type (uint32, decimal string)",
        default="0",
    )
    entries: CollectionProperty(
        name="Entries",
        description="All ActionEntry of this ActionData (PLAYEFX / PLAYEMITTER)",
        type=EFXActionEntryProps,
    )
    active_entry_index: IntProperty(
        name="Active Entry Index",
        description="Currently active entry (used by the list UI)",
        default=0,
        min=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# §3  导入：ActionData → EFXActionProps
# ─────────────────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64dec(s: str) -> bytes:
    return base64.b64decode(s)


def load_entry_fields_from_raw(item, raw: bytes, is_emitter: bool) -> None:
    """
    把一个 ActionEntry 的 raw 字节解成 item 上的可编辑属性，并置 fields_loaded=True。

    导入（init_action_props）与新建 entry（EFX_OT_action_entry_add）共用本函数，保证
    两条路径填出来的属性完全一致——新建的 entry 也因此立刻可编辑全部字段。

    偏移见本文件头部结构说明。任何长度不足/解析异常都保持 fields_loaded=False，
    此时重建路径沿用原始字节（见 _rebuild_emitter_raw / _rebuild_actionefx_raw）。
    """
    try:
        if is_emitter:
            if len(raw) < 52:
                return
            item.em_unkn0 = struct.unpack_from('<i', raw, 0)[0]
            item.em_unkn1 = bool(struct.unpack_from('<i', raw, 4)[0])
            item.em_unkn2 = bool(struct.unpack_from('<i', raw, 8)[0])
            item.em_rotation_order = struct.unpack_from('<i', raw, 12)[0]
            item.em_rotation = struct.unpack_from('<3f', raw, 16)
            item.xyz = struct.unpack_from('<3f', raw, 28)
            item.em_position = struct.unpack_from('<3f', raw, 40)
        else:
            if len(raw) < 64:
                return
            item.pefx_unkn0 = struct.unpack_from('<i', raw, 0)[0]
            item.pefx_type_str = str(struct.unpack_from('<I', raw, 8)[0])
            item.pefx_unkn_0 = bool(struct.unpack_from('<i', raw, 12)[0])
            item.pefx_unkn_1 = bool(struct.unpack_from('<i', raw, 16)[0])
            item.pefx_unkn_2 = struct.unpack_from('<i', raw, 20)[0]
            item.pefx_unkn_3 = struct.unpack_from('<f', raw, 24)[0]
            item.pefx_unkn_4 = struct.unpack_from('<f', raw, 28)[0]
            item.pefx_unkn_5 = struct.unpack_from('<f', raw, 32)[0]
            item.pefx_unkn_6 = struct.unpack_from('<i', raw, 36)[0]
            item.xyz = struct.unpack_from('<3f', raw, 40)
            item.pefx_null = struct.unpack_from('<3f', raw, 52)
    except Exception:
        return
    item.fields_loaded = True


def init_action_props(play_obj: bpy.types.Object,
                    pd,
                    main_bodies_by_index: dict) -> None:
    """
    把解析好的 ActionData 内容写入 play_obj.efx_play PropertyGroup。

    参数
    ----
    play_obj : bpy.types.Object
        EFX_ACTION Empty 对象（将被写入 .efx_play）。
    pd : ActionData
        已解析的 ActionData 数据对象（来自 efx_format/efxfile.py）。
    main_bodies_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_ENTRY bpy Object} 映射（由 import_efx_tree 构建）。
        用于将 PlayEmitter targets 的整数索引解析为具体的 entry 对象。

    副作用
    ------
    - 填写 play_obj.efx_play.{play_type_str, entries}。
    - 每个 PLAYEMITTER entry 的 targets 解析为 entry 指针列表。
    - 保留自定义属性 raw_b64（由 io_tree 写入，作为 byte-perfect 回退）。
    """
    props = play_obj.efx_play

    # ── play_type（uint32 → 十进制字符串）──────────────────────────────────────
    props.play_type_str = str(pd.play_type)

    # ── entries：按原序填入 ─────────────────────────────────────────────────────
    props.entries.clear()
    for entry in pd.entries:
        item = props.entries.add()
        item.type_hash_str = str(entry.type_hash)
        item.raw_b64 = _b64enc(entry.raw)

        if entry.type_hash == PLAYEMITTER:
            item.is_emitter = True
            raw = entry.raw
            load_entry_fields_from_raw(item, raw, True)
            if len(raw) >= 56:
                target_count = struct.unpack_from('<i', raw, 52)[0]
                for ti in range(target_count):
                    offset = 56 + ti * 4
                    if offset + 4 > len(raw):
                        break
                    body_idx = struct.unpack_from('<i', raw, offset)[0]
                    t = item.targets.add()
                    entry_obj = main_bodies_by_index.get(body_idx)
                    if entry_obj is not None:
                        t.body_ptr = entry_obj
        else:
            item.is_emitter = False
            raw = entry.raw
            load_entry_fields_from_raw(item, raw, False)
            if len(raw) >= 8:
                path_len = struct.unpack_from('<i', raw, 4)[0]
                if path_len > 0 and 64 + path_len <= len(raw):
                    path_bytes = raw[64:64 + path_len]
                    null_pos = path_bytes.find(b'\x00')
                    if null_pos >= 0:
                        path_bytes = path_bytes[:null_pos]
                    item.efx_path = path_bytes.decode('utf-8', errors='replace')


# ─────────────────────────────────────────────────────────────────────────────
# §4  导出：EFXActionProps → ActionData
# ─────────────────────────────────────────────────────────────────────────────

def export_action_data(play_obj: bpy.types.Object,
                     entry_index_map: dict):
    """
    从 EFX_ACTION 对象重建 ActionData 数据对象。

    参数
    ----
    play_obj : bpy.types.Object
        EFX_ACTION Empty 对象。
    entry_index_map : dict[bpy.types.Object, int]
        {EFX_ENTRY Object → Main 段局部 0-based index}，
        由 build_local_index_map(col_entry, 'EFX_ENTRY') 或 io_tree 的 enumerate 构建。

    返回
    ----
    ActionData（来自 efx_format.efxfile）

    回退策略
    --------
    若 play_obj 不存在 efx_play 属性（旧场景/兼容），
    则从自定义属性 raw_b64 还原原始字节。

    悬空 target 处理
    -----------------
    body_ptr 为 None（指针悬空）的 target 跳过（不写入 targets；
    validate.py 统一报告 WARN，不阻断导出。
    """
    from ..efx_format.efxfile import ActionData, ActionEntry

    try:
        props = play_obj.efx_play
    except AttributeError:
        return _fallback_raw_action(play_obj)

    # ── play_type ─────────────────────────────────────────────────────────────
    try:
        play_type = int(str(props.play_type_str))
    except (ValueError, TypeError):
        return _fallback_raw_action(play_obj)

    # ── 重建 entries ──────────────────────────────────────────────────────────
    entries = []
    for item in props.entries:
        try:
            type_hash = int(str(item.type_hash_str))
        except (ValueError, TypeError):
            # 异常：走单 entry 的 raw_b64 回退
            raw = _b64dec(str(item.raw_b64))
            entries.append(ActionEntry(type_hash=type_hash, raw=raw))
            continue

        if item.is_emitter:
            # PLAYEMITTER：替换 XYZ + targets，其余字节逐字保留
            raw = _rebuild_emitter_raw(item, entry_index_map)
        else:
            # PLAYEFX：替换 XYZ + 路径，其余字节逐字保留
            raw = _rebuild_actionefx_raw(item)

        entries.append(ActionEntry(type_hash=type_hash, raw=raw))

    return ActionData(play_type=play_type, entries=entries)


def _rebuild_emitter_raw(item: EFXActionEntryProps,
                         entry_index_map: dict) -> bytes:
    """
    重建 PlayEmitter entry 的 raw 字节。

    fields_loaded=False 时保留头部和 Position 的原始字节。
    targets 按当前 entry 指针重建；悬空或不属于当前 EFX 的目标会被跳过。
    """
    orig_raw = _b64dec(str(item.raw_b64))

    # 构建 target 索引列表
    target_indices = []
    for t in item.targets:
        entry_obj = t.body_ptr
        if entry_obj is None:
            continue
        local_idx = entry_index_map.get(entry_obj)
        if local_idx is None:
            continue
        target_indices.append(local_idx)

    if item.fields_loaded:
        head = (struct.pack('<i', int(item.em_unkn0))
                + struct.pack('<i', 1 if item.em_unkn1 else 0)
                + struct.pack('<i', 1 if item.em_unkn2 else 0)
                + struct.pack('<i', int(item.em_rotation_order))
                + struct.pack('<3f', *item.em_rotation))
        pos = struct.pack('<3f', *item.em_position)
    else:
        head = orig_raw[:28]
        pos = orig_raw[40:52]

    prefix = head + struct.pack('<3f', *item.xyz) + pos

    N = len(target_indices)
    new_raw = prefix + struct.pack('<i', N)
    for idx in target_indices:
        new_raw += struct.pack('<i', idx)

    return new_raw


def _rebuild_actionefx_raw(item: EFXActionEntryProps) -> bytes:
    """
    重建 PlayEFX entry 的 raw 字节。

    fields_loaded 控制可编辑字段是否写回原始数据。
    路径未修改时保留原始 path_len 和路径字节，以保护空路径与尾部填充。
    """
    orig_raw = _b64dec(str(item.raw_b64))

    # 还原原始路径串（与 init_action_props 的解码逻辑一致），判断用户是否真的改过
    orig_path_len = struct.unpack_from('<i', orig_raw, 4)[0] if len(orig_raw) >= 8 else 0
    orig_path_bytes = (orig_raw[64:64 + orig_path_len]
                       if orig_path_len > 0 and 64 + orig_path_len <= len(orig_raw)
                       else b'')
    _nz = orig_path_bytes.find(b'\x00')
    orig_path_str = (orig_path_bytes[:_nz] if _nz >= 0 else orig_path_bytes) \
        .decode('utf-8', errors='replace')

    if item.efx_path == orig_path_str:
        path_len_bytes = orig_raw[4:8]
        path_bytes = orig_path_bytes
    else:
        path_bytes = item.efx_path.encode('utf-8') + b'\x00'
        path_len_bytes = struct.pack('<i', len(path_bytes))

    head = orig_raw[:4]        # Type Flags
    mid = orig_raw[8:40]       # Type、标志位、旋转字段
    tail = orig_raw[52:64]     # Position XYZ
    if item.fields_loaded:
        try:
            type_val = int(str(item.pefx_type_str)) & 0xFFFFFFFF
            head = struct.pack('<i', int(item.pefx_unkn0))
            mid = (struct.pack('<I', type_val)
                   + struct.pack('<i', 1 if item.pefx_unkn_0 else 0)
                   + struct.pack('<i', 1 if item.pefx_unkn_1 else 0)
                   + struct.pack('<i', int(item.pefx_unkn_2))
                   + struct.pack('<f', item.pefx_unkn_3)
                   + struct.pack('<f', item.pefx_unkn_4)
                   + struct.pack('<f', item.pefx_unkn_5)
                   + struct.pack('<i', int(item.pefx_unkn_6)))
            tail = struct.pack('<3f', *item.pefx_null)
        except (ValueError, TypeError, struct.error):
            head = orig_raw[:4]
            mid = orig_raw[8:40]
            tail = orig_raw[52:64]

    new_raw = (head
               + path_len_bytes
               + mid
               + struct.pack('<3f', *item.xyz)
               + tail
               + path_bytes)

    return new_raw


def _fallback_raw_action(play_obj: bpy.types.Object):
    """
    兼容回退：从自定义属性 raw_b64 原样还原 ActionData（旧 opaque 路径）。
    用于 play_obj 没有 efx_play PropertyGroup 数据的情况（旧 .blend / 兼容）。
    """
    from ..efx_format.efxfile import ActionData, ActionEntry

    raw_all = _b64dec(str(play_obj["raw_b64"]))
    # raw_b64 存的是 pd.serialize() = pack('<Ii', play_type, entry_count) + entries
    play_type = struct.unpack_from('<I', raw_all, 0)[0]
    entry_count = struct.unpack_from('<i', raw_all, 4)[0]
    pos = 8
    entries = []
    for _ in range(entry_count):
        type_hash = struct.unpack_from('<I', raw_all, pos)[0]
        pos += 4
        from ..efx_format.hashes import PLAYEFX
        if type_hash == PLAYEFX:
            path_len = struct.unpack_from('<i', raw_all, pos + 4)[0]
            entry_size = 64 + path_len
        elif type_hash == PLAYEMITTER:
            target_count = struct.unpack_from('<i', raw_all, pos + 52)[0]
            entry_size = 56 + 4 * target_count
        else:
            # 未知类型：尽力回退（不应发生）
            break
        entry_raw = raw_all[pos:pos + entry_size]
        pos += entry_size
        entries.append(ActionEntry(type_hash=type_hash, raw=entry_raw))

    return ActionData(play_type=play_type, entries=entries)


# ─────────────────────────────────────────────────────────────────────────────
# §5  Action Entry 与 PlayEmitter Target 编辑算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_action_target_add(Operator):
    """向当前 PlayEmitter entry 新增一个空 target（body_ptr 待用户指定）"""

    bl_idname      = "efx.action_target_add"
    bl_label       = "Add Target"
    bl_description = "Append an empty slot to the end of the PlayEmitter targets list"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: IntProperty(name="Entry Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ACTION"

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_play
        idx = self.entry_index
        if 0 <= idx < len(props.entries):
            entry = props.entries[idx]
            if entry.is_emitter:
                entry.targets.add()
                entry.active_target_index = len(entry.targets) - 1
        return {"FINISHED"}


class EFX_OT_action_target_remove(Operator):
    """删除当前激活的 PlayEmitter target"""

    bl_idname      = "efx.action_target_remove"
    bl_label       = "Remove Target"
    bl_description = "Delete the currently active target from the PlayEmitter targets list"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: IntProperty(name="Entry Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ACTION":
            return False
        try:
            props = obj.efx_play
            return len(props.entries) > 0
        except AttributeError:
            return False

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_play
        ei = self.entry_index
        if 0 <= ei < len(props.entries):
            entry = props.entries[ei]
            if entry.is_emitter:
                ti = entry.active_target_index
                if 0 <= ti < len(entry.targets):
                    entry.targets.remove(ti)
                    entry.active_target_index = min(
                        ti, max(0, len(entry.targets) - 1)
                    )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §6  算子：Action entry 新增 / 删除
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_action_entry_add(Operator):
    """向当前 Action 追加一个新 entry（弹窗选择 PlayEmitter / PlayEFX）"""

    bl_idname      = "efx.action_entry_add"
    bl_label       = "Add Entry"
    bl_description = "Append a new PlayEmitter or PlayEFX entry to this Action"
    bl_options     = {"REGISTER", "UNDO"}

    entry_type: EnumProperty(
        name="Entry Type",
        description="Type of the new entry",
        items=[
            ('PLAYEMITTER', "PlayEmitter", "Internal entry reference (targets[] pointing to Main entries)"),
            ('PLAYEFX',     "PlayEFX",     "External .efx file call (path + XYZ offset)"),
        ],
        default='PLAYEMITTER',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ACTION"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "entry_type", text=T("action.entry_type"))

    def execute(self, context):
        import base64 as _b64mod
        from .add_section_ops import _BLANK_PLAYEFX_RAW, _BLANK_EMITTER_UNKN7

        obj = context.active_object
        props = obj.efx_play
        item = props.entries.add()

        if self.entry_type == 'PLAYEFX':
            item.type_hash_str = str(PLAYEFX)
            item.is_emitter    = False
            item.raw_b64       = _b64mod.b64encode(_BLANK_PLAYEFX_RAW).decode('ascii')
            item.efx_path      = ""
            # 模板已经包含 Size=(1,1,1)；解析后不要再用默认值覆盖 xyz。
            load_entry_fields_from_raw(item, _BLANK_PLAYEFX_RAW, False)
        else:
            emitter_raw = (_BLANK_EMITTER_UNKN7
                           + struct.pack("<3f", 1.0, 1.0, 1.0)
                           + b"\x00" * 12
                           + struct.pack("<i", 0))
            item.type_hash_str = str(PLAYEMITTER)
            item.is_emitter    = True
            item.raw_b64       = _b64mod.b64encode(emitter_raw).decode('ascii')
            load_entry_fields_from_raw(item, emitter_raw, True)
            item.xyz           = (1.0, 1.0, 1.0)

        props.active_entry_index = len(props.entries) - 1
        return {"FINISHED"}


class EFX_OT_action_entry_remove(Operator):
    """从当前 Action 删除指定 entry"""

    bl_idname      = "efx.action_entry_remove"
    bl_label       = "Remove Entry"
    bl_description = "Remove this entry from the Action"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: IntProperty(name="Entry Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ACTION":
            return False
        try:
            return len(obj.efx_play.entries) > 0
        except AttributeError:
            return False

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_play
        ei = self.entry_index
        if 0 <= ei < len(props.entries):
            props.entries.remove(ei)
            props.active_entry_index = min(ei, max(0, len(props.entries) - 1))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §7  UIList：PlayEmitter target 列表
# ─────────────────────────────────────────────────────────────────────────────

class EFX_UL_action_targets(bpy.types.UIList):
    """
    UIList 显示 EFXActionTarget 列表。
    每行显示：序号 + body_ptr 指向的对象名（悬空时显示 <未设置>）。
    """

    bl_idname = "EFX_UL_action_targets"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index}:", icon="BLANK1")
        entry_obj = item.body_ptr
        if entry_obj is not None:
            row.prop(item, "body_ptr", text="", icon="OBJECT_DATA")
        else:
            row.prop(item, "body_ptr", text=T("action.unset"), icon="ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# §7  面板：N 面板 EFX 标签 Action 数据显示
# ─────────────────────────────────────────────────────────────────────────────


def _draw_action_content(layout, context):
    """
    绘制 EFX_ACTION 的数据内容。
    由 N 面板和属性编辑器 Data 标签共用，提供 Action 重命名、
    PlayEmitter/PlayEFX Entry 编辑与 target 管理。
    """
    from .reorder import draw_rename_field

    obj = context.active_object
    draw_rename_field(layout, obj)

    try:
        props = obj.efx_play
    except AttributeError:
        layout.label(text=T("action.no_data"), icon="ERROR")
        return

    # ── 元数据行（只读）─────────────────────────────────────────────────────
    meta_box = layout.box()
    meta_box.label(text=T("action.meta"), icon="INFO")
    meta_box.label(text=f"Play Type: {props.play_type_str}")
    meta_box.label(text=f"Entries: {len(props.entries)}")

    layout.separator()

    # ── 各 entry 展开 ────────────────────────────────────────────────────────
    total_dangling = 0
    for ei, entry in enumerate(props.entries):
        entry_box = layout.box()

        if entry.is_emitter:
            # ── PLAYEMITTER ────────────────────────────────────────────────
            hdr = entry_box.row(align=True)
            hdr.label(text=f"Entry {ei}  PLAYEMITTER", icon="LINKED")
            rem_op = hdr.operator("efx.action_entry_remove", text="", icon="X")
            rem_op.entry_index = ei

            entry_box.prop(entry, "xyz", text=T("action.size_xyz"))
            entry_box.prop(entry, "em_position", text=T("action.position_xyz"))
            unk_col = entry_box.column(align=True)
            unk_col.label(text=T("action.unknown_fields"))
            unk_col.prop(entry, "em_unkn0")
            unk_row = unk_col.row(align=True)
            unk_row.prop(entry, "em_unkn1", toggle=False)
            unk_row.prop(entry, "em_unkn2", toggle=False)
            unk_col.prop(entry, "em_rotation_order")
            unk_col.prop(entry, "em_rotation", text=T("action.unkn_angles"))
            if not entry.fields_loaded:
                warn = entry_box.row()
                warn.alert = True
                warn.label(text=T("action.reimport_needed"), icon="ERROR")

            tgt_count = len(entry.targets)
            entry_box.label(
                text=f"{T('action.targets')}({tgt_count})",
                icon="OUTLINER_OB_EMPTY",
            )

            list_row = entry_box.row()
            list_row.template_list(
                "EFX_UL_action_targets",
                f"play_targets_{ei}",
                entry, "targets",
                entry, "active_target_index",
                rows=3,
            )

            btn_col = list_row.column(align=True)
            add_op = btn_col.operator("efx.action_target_add", text="", icon="ADD")
            add_op.entry_index = ei
            rem_op2 = btn_col.operator("efx.action_target_remove", text="", icon="REMOVE")
            rem_op2.entry_index = ei

            ati = entry.active_target_index
            if 0 <= ati < tgt_count:
                entry_box.row().prop(entry.targets[ati], "body_ptr", text=T("action.entry_object"))

            dangling = sum(1 for t in entry.targets if t.body_ptr is None)
            total_dangling += dangling
            if dangling > 0:
                warn = entry_box.row()
                warn.alert = True
                warn.label(
                    text=f"⚠ {dangling} {T('action.targets_dangling')}",
                    icon="ERROR",
                )

        else:
            # ── PLAYEFX ────────────────────────────────────────────────────
            hdr = entry_box.row(align=True)
            hdr.label(text=f"Entry {ei}  PLAYEFX", icon="FILE_BLEND")
            rem_op = hdr.operator("efx.action_entry_remove", text="", icon="X")
            rem_op.entry_index = ei

            entry_box.prop(entry, "efx_path", text=T("action.efx_path"))
            entry_box.prop(entry, "xyz", text=T("action.size_xyz"))
            entry_box.prop(entry, "pefx_null", text=T("action.position_xyz"))
            entry_box.prop(entry, "pefx_type_str", text=T("action.playefx_type"))
            unk_col = entry_box.column(align=True)
            unk_col.label(text=T("action.unknown_fields"))
            unk_col.prop(entry, "pefx_unkn0")
            unk_row = unk_col.row(align=True)
            unk_row.prop(entry, "pefx_unkn_0", toggle=False)
            unk_row.prop(entry, "pefx_unkn_1", toggle=False)
            unk_col.prop(entry, "pefx_unkn_2")
            unk_col.prop(entry, "pefx_unkn_3")
            unk_col.prop(entry, "pefx_unkn_4")
            unk_col.prop(entry, "pefx_unkn_5")
            unk_col.prop(entry, "pefx_unkn_6")
            if not entry.fields_loaded:
                warn = entry_box.row()
                warn.alert = True
                warn.label(text=T("action.reimport_needed"), icon="ERROR")

    # ── 新增 entry 按钮 ──────────────────────────────────────────────────────
    layout.separator()
    layout.operator("efx.action_entry_add", text=T("action.add_entry"), icon="ADD")

    # ── 整体悬空警告 ─────────────────────────────────────────────────────────
    if total_dangling > 0:
        layout.separator()
        warn_row = layout.row()
        warn_row.alert = True
        warn_row.label(
            text=f"⚠ {total_dangling} {T('action.targets_dangling_total')}",
            icon="ERROR",
        )


class EFX_PT_action(bpy.types.Panel):
    """
    Action 数据面板（VIEW_3D N 面板 EFX 标签）。

    设计理念（CLAUDE §4）：
      Action ↔ entry 归属关系是结构关系（工具功能），放 N 面板。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Action Data"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ACTION"

    def draw(self, context):
        _draw_action_content(self.layout, context)


class EFX_PT_action_props(bpy.types.Panel):
    """Action 数据（属性编辑器 → Object Data Properties，选中 EFX_ACTION 时显示）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "data"
    bl_label        = "EFX Action Data"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ACTION"

    def draw(self, context):
        _draw_action_content(self.layout, context)


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 注册顺序：PropertyGroup 子类先于容器类；UIList/Operator/Panel 次之。
# EFXActionTarget 必须在 EFXActionEntryProps 之前，EFXActionEntryProps 在 EFXActionProps 之前。
_CLASSES_CORE = (
    EFXActionTarget,
    EFXActionEntryProps,
    EFXActionProps,
    EFX_UL_action_targets,
    EFX_OT_action_target_add,
    EFX_OT_action_target_remove,
    EFX_OT_action_entry_add,
    EFX_OT_action_entry_remove,
)

# EFX_PT_action 导出给 panels.py，由 panels.register() 在 EFX_PT_entry 之后注册。


def register():
    """
    注册 Action 核心类（PropertyGroup + UIList + Operator）。
    并把 EFXActionProps 挂到 Object 上。

    注意：EFX_PT_action 面板由 panels.py 在 EFX_PT_entry 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_play = PointerProperty(
        name="EFX Action Properties",
        description="Structured Action data for the EFX_ACTION object",
        type=EFXActionProps,
    )


def unregister():
    """
    注销 Action 核心类并清理 PointerProperty。
    EFX_PT_action 由 panels.py 先注销。
    """
    try:
        del bpy.types.Object.efx_play
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
