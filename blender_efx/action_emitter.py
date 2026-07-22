"""
blender_efx/action_emitter.py  —  L2 #1b：PlayEmitter targets 指针化

设计原则（参照 CLAUDE.md / subselect.py 模式）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集（PropertyGroup / CollectionProperty / PointerProperty /
    StringProperty / IntProperty / Panel / UIList / Operator）
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件不改 efx_format/
  - byte-perfect：PlayEmitter 导出时只替换 targets 段，其余字节逐字保留

PlayEmitter 结构（raw = type_hash 之后的字节，来自 efxfile.py _parse_play）：
  offset  0: int unkn[7]       28 B   ← 始终保留原始字节
  offset 28: XYZ xyz(3)        12 B   ← float[3]，始终保留原始字节
  offset 40: int NULL[3]       12 B   ← 始终保留原始字节
  offset 52: int target_count   4 B   ← 重建时更新（当前阶段数量不变）
  offset 56: int targets[N]    4*N B  ← 由 entry 指针映射 → 局部 index 重写

PlayEFX：raw 整体保留，完全 opaque，不解析。

PropertyGroup 层级：
  obj.efx_play  (EFXActionProps)
    ├── play_type_str : str        # ActionData.play_type (uint32 十进制)
    └── entries       : CollectionProperty[EFXActionEntryProps]
          ├── type_hash_str : str  # 十进制字符串
          ├── raw_b64       : str  # 完整 entry raw（typeHash 之后），始终保留
          ├── is_emitter    : bool # type_hash == PLAYEMITTER
          └── targets       : CollectionProperty[EFXActionTarget]  # 仅 PLAYEMITTER 有效
                └── body_ptr : PointerProperty(poll=EFX_ENTRY)

byte-perfect 保证：
  - PlayEFX：raw_b64 原样序列化，不经任何解析。
  - PlayEmitter：prefix_bytes（raw[:56]，即 unkn[7]+xyz+NULL[3]+target_count 位置前）
    + 重建的 target_count + 重建的 targets[]。
    实际上把 raw[:52] 保留（unkn[7]+xyz+NULL[3]），
    再 pack('<i', N) 写 target_count，再 pack('<i', idx) * N 写 targets。
    非 targets 字节（含 target_count 字节原值）只要数量不变就逐字复现。
  - entries 未变时：target 指针 → efx_index == 导出的局部 index → byte-perfect。

悬空 target 处理：
  body_ptr 为 None 的 target 导出时跳过（不写入），与 subselect.py 保持一致。
  validate.py 统一扫描报 WARN（导出后弹窗报告，不阻断导出）——0.2.57 定型的既定设计。
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
        description="Base64 encoding of ActionEntry.raw; always preserves unknown bytes for byte-perfect fallback",
        default="",
    )
    is_emitter: BoolProperty(
        name="Is PlayEmitter",
        description="True = PLAYEMITTER (targets valid), False = PLAYEFX (path + XYZ editable)",
        default=False,
    )
    xyz: FloatVectorProperty(
        name="Position Offset XYZ",
        description="Position offset of the ActionEntry (float[3])",
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
            # PlayEmitter raw 布局（type_hash 之后）：
            #   [0:28]  unkn[7] (28B)
            #   [28:40] XYZ float[3] (12B)  ← 可编辑
            #   [40:52] NULL[3] (12B)
            #   [52:56] target_count (int32)
            #   [56:]   targets[N] (int32 each)
            raw = entry.raw
            if len(raw) >= 40:
                item.xyz = struct.unpack_from('<3f', raw, 28)
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
            # PlayEFX raw 布局（type_hash 之后）：
            #   [0:4]   unkn0 (4B)
            #   [4:8]   path_len (int32)
            #   [8:12]  type (4B)
            #   [12:40] unkn[7] (28B)
            #   [40:52] XYZ float[3] (12B)  ← 可编辑
            #   [52:64] NULL[3] (12B)
            #   [64:]   path[path_len]       ← 可编辑
            item.is_emitter = False
            raw = entry.raw
            if len(raw) >= 52:
                item.xyz = struct.unpack_from('<3f', raw, 40)
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
    则从自定义属性 raw_b64 还原原始字节（byte-perfect 回退）。

    悬空 target 处理
    -----------------
    body_ptr 为 None（指针悬空）的 target 跳过（不写入 targets），以保证导出不崩溃。
    validate.py 统一扫描报 WARN（导出后弹窗报告，不阻断导出）——0.2.57 定型的既定设计，
    不是待补的校验缺口。
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

    策略：
      raw[:28]  unkn[7] 原样保留
      raw[28:40] 用 item.xyz 重写（float[3]）
      raw[40:52] NULL[3] 原样保留
      target_count + targets 由 entry 指针映射重建

    悬空 target（body_ptr=None 或不在 entry_index_map）静默跳过。
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

    # 保留 unkn[7]（0-27），写入 XYZ（28-39），保留 NULL[3]（40-51）
    prefix = (orig_raw[:28]
              + struct.pack('<3f', *item.xyz)
              + orig_raw[40:52])

    N = len(target_indices)
    new_raw = prefix + struct.pack('<i', N)
    for idx in target_indices:
        new_raw += struct.pack('<i', idx)

    return new_raw


def _rebuild_actionefx_raw(item: EFXActionEntryProps) -> bytes:
    """
    重建 PlayEFX entry 的 raw 字节。

    策略：
      raw[0:4]   unkn0 原样保留
      raw[4:8]   path_len 按新路径重算
      raw[8:40]  type + unkn[7] 原样保留
      raw[40:52] 用 item.xyz 重写（float[3]）
      raw[52:64] NULL[3] 原样保留
      raw[64:]   用 item.efx_path 重写（UTF-8 + null 终止符）
    """
    orig_raw = _b64dec(str(item.raw_b64))

    path_bytes = item.efx_path.encode('utf-8') + b'\x00'
    path_len = len(path_bytes)

    new_raw = (orig_raw[:4]
               + struct.pack('<i', path_len)
               + orig_raw[8:40]
               + struct.pack('<3f', *item.xyz)
               + orig_raw[52:64]
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
# §5  面板算子（当前阶段：仅支持编辑已有 target 指向，不支持增删）
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
            item.xyz           = (0.0, 0.0, 0.0)
            item.efx_path      = ""
        else:
            emitter_raw = (_BLANK_EMITTER_UNKN7
                           + struct.pack("<3f", 1.0, 1.0, 1.0)
                           + b"\x00" * 12
                           + struct.pack("<i", 0))
            item.type_hash_str = str(PLAYEMITTER)
            item.is_emitter    = True
            item.raw_b64       = _b64mod.b64encode(emitter_raw).decode('ascii')
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
    被 EFX_PT_action（N 面板）和 EFX_PT_action_props/_object（属性编辑器）共用。

    选中 EFX_ACTION 对象时显示：
      - play_type 元数据（只读）
      - 各 entry 列表：
          PLAYEFX  → 路径（只读字符串）
          PLAYEMITTER → target entry 指针列表（可编辑指向）
      - 悬空 target 指针警告
    """
    obj = context.active_object

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

            entry_box.prop(entry, "xyz", text=T("action.pos_offset_xyz"))

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
            entry_box.prop(entry, "xyz", text=T("action.pos_offset_xyz"))

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


class EFX_PT_action_object(bpy.types.Panel):
    """Action 数据（属性编辑器 → Object Properties，保底版本）"""

    bl_space_type   = "PROPERTIES"
    bl_region_type  = "WINDOW"
    bl_context      = "object"
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
