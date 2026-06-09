"""
blender_efx/play_emitter.py  —  L2 #1b：PlayEmitter targets 指针化

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
  offset 56: int targets[N]    4*N B  ← 由 body 指针映射 → 局部 index 重写

PlayEFX：raw 整体保留，完全 opaque，不解析。

PropertyGroup 层级：
  obj.efx_play  (EFXPlayProps)
    ├── play_type_str : str        # PlayData.play_type (uint32 十进制)
    └── entries       : CollectionProperty[EFXPlayEntryProps]
          ├── type_hash_str : str  # 十进制字符串
          ├── raw_b64       : str  # 完整 entry raw（typeHash 之后），始终保留
          ├── is_emitter    : bool # type_hash == PLAYEMITTER
          └── targets       : CollectionProperty[EFXPlayTarget]  # 仅 PLAYEMITTER 有效
                └── body_ptr : PointerProperty(poll=EFX_BODY)

byte-perfect 保证：
  - PlayEFX：raw_b64 原样序列化，不经任何解析。
  - PlayEmitter：prefix_bytes（raw[:56]，即 unkn[7]+xyz+NULL[3]+target_count 位置前）
    + 重建的 target_count + 重建的 targets[]。
    实际上把 raw[:52] 保留（unkn[7]+xyz+NULL[3]），
    再 pack('<i', N) 写 target_count，再 pack('<i', idx) * N 写 targets。
    非 targets 字节（含 target_count 字节原值）只要数量不变就逐字复现。
  - bodies 未变时：target 指针 → efx_index == 导出的局部 index → byte-perfect。

悬空 target 处理（TODO）：
  body_ptr 为 None 的 target 当前导出时跳过（不写入），
  与 subselect.py 保持一致。后续校验阶段应改为报错。
"""

import struct
import base64

import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    CollectionProperty,
    PointerProperty,
    IntProperty,
)
from bpy.types import PropertyGroup, Operator

from ..efx_format.hashes import PLAYEMITTER


# ─────────────────────────────────────────────────────────────────────────────
# §1  poll 函数
# ─────────────────────────────────────────────────────────────────────────────

def _body_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_BODY' 的对象。"""
    return obj.get("~TYPE") == "EFX_BODY"


# ─────────────────────────────────────────────────────────────────────────────
# §2  PropertyGroup：Play 结构化存储
# ─────────────────────────────────────────────────────────────────────────────

class EFXPlayTarget(PropertyGroup):
    """
    PlayEmitter 的单个 target：指向一个 EFX_BODY 对象的指针。

    CollectionProperty 元素，挂在 EFXPlayEntryProps.targets 上。
    """
    body_ptr: PointerProperty(
        name="Body 对象",
        description="此 PlayEmitter target 引用的 EFX_BODY 对象",
        type=bpy.types.Object,
        poll=_body_object_poll,
    )


class EFXPlayEntryProps(PropertyGroup):
    """
    PlayData 中单个 PlayEntry 的结构化存储。

    字段
    ----
    type_hash_str : 十进制字符串（uint32，避免 Blender int32 溢出）
    raw_b64       : base64 字符串，entry raw（type_hash 之后的字节），始终保留
    is_emitter    : bool，True = PLAYEMITTER，False = PLAYEFX（或其他）
    targets       : CollectionProperty[EFXPlayTarget]，仅 PLAYEMITTER 解析填充
    active_target_index : 供 template_list 使用
    """
    type_hash_str: StringProperty(
        name="Type Hash",
        description="PlayEntry.type_hash（uint32，十进制字符串）",
        default="0",
    )
    raw_b64: StringProperty(
        name="Raw (b64)",
        description="PlayEntry.raw 的 base64 编码，始终保留作 byte-perfect 回退",
        default="",
    )
    is_emitter: BoolProperty(
        name="Is PlayEmitter",
        description="True = PLAYEMITTER（targets 有效），False = PLAYEFX（raw 整体保留）",
        default=False,
    )
    targets: CollectionProperty(
        name="Targets",
        description="PlayEmitter 引用的 EFX_BODY 列表（对应 targets[] 数组）",
        type=EFXPlayTarget,
    )
    active_target_index: IntProperty(
        name="激活 Target 序号",
        description="当前激活的 target（供列表 UI 使用）",
        default=0,
        min=0,
    )


class EFXPlayProps(PropertyGroup):
    """
    挂在 EFX_PLAY Empty 对象上（obj.efx_play）的 PropertyGroup。

    字段
    ----
    play_type_str : PlayData.play_type（uint32 十进制字符串）
    entries       : CollectionProperty[EFXPlayEntryProps]，该 PlayData 的全部 entry
    active_entry_index : 供 template_list 使用
    """
    play_type_str: StringProperty(
        name="Play Type",
        description="PlayData.play_type（uint32，十进制字符串）",
        default="0",
    )
    entries: CollectionProperty(
        name="Entries",
        description="该 PlayData 的全部 PlayEntry（PLAYEFX / PLAYEMITTER）",
        type=EFXPlayEntryProps,
    )
    active_entry_index: IntProperty(
        name="激活 Entry 序号",
        description="当前激活的 entry（供列表 UI 使用）",
        default=0,
        min=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# §3  导入：PlayData → EFXPlayProps
# ─────────────────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64dec(s: str) -> bytes:
    return base64.b64decode(s)


def init_play_props(play_obj: bpy.types.Object,
                    pd,
                    main_bodies_by_index: dict) -> None:
    """
    把解析好的 PlayData 内容写入 play_obj.efx_play PropertyGroup。

    参数
    ----
    play_obj : bpy.types.Object
        EFX_PLAY Empty 对象（将被写入 .efx_play）。
    pd : PlayData
        已解析的 PlayData 数据对象（来自 efx_format/efxfile.py）。
    main_bodies_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_BODY bpy Object} 映射（由 import_efx_tree 构建）。
        用于将 PlayEmitter targets 的整数索引解析为具体的 body 对象。

    副作用
    ------
    - 填写 play_obj.efx_play.{play_type_str, entries}。
    - 每个 PLAYEMITTER entry 的 targets 解析为 body 指针列表。
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
            # ── 解析 targets ──────────────────────────────────────────────────
            # PlayEmitter raw 布局：
            #   [0:52]  unkn[7](28B) + xyz(12B) + NULL[3](12B)
            #   [52:56] target_count (int32, 4B)
            #   [56:]   targets[target_count] (int32 each)
            raw = entry.raw
            if len(raw) >= 56:
                target_count = struct.unpack_from('<i', raw, 52)[0]
                for ti in range(target_count):
                    offset = 56 + ti * 4
                    if offset + 4 > len(raw):
                        break
                    body_idx = struct.unpack_from('<i', raw, offset)[0]
                    t = item.targets.add()
                    body_obj = main_bodies_by_index.get(body_idx)
                    if body_obj is not None:
                        t.body_ptr = body_obj
                    # 若找不到对应 body（异常情况），body_ptr 留 None
        else:
            # PLAYEFX 或其他：raw 整体保留，is_emitter=False
            item.is_emitter = False


# ─────────────────────────────────────────────────────────────────────────────
# §4  导出：EFXPlayProps → PlayData
# ─────────────────────────────────────────────────────────────────────────────

def export_play_data(play_obj: bpy.types.Object,
                     body_index_map: dict):
    """
    从 EFX_PLAY 对象重建 PlayData 数据对象。

    参数
    ----
    play_obj : bpy.types.Object
        EFX_PLAY Empty 对象。
    body_index_map : dict[bpy.types.Object, int]
        {EFX_BODY Object → Main 段局部 0-based index}，
        由 build_local_index_map(col_main, 'EFX_BODY') 或 io_tree 的 enumerate 构建。

    返回
    ----
    PlayData（来自 efx_format.efxfile）

    回退策略
    --------
    若 play_obj 不存在 efx_play 属性（旧场景/兼容），
    则从自定义属性 raw_b64 还原原始字节（byte-perfect 回退）。

    悬空 target 处理（TODO）
    -----------------------
    body_ptr 为 None（指针悬空）的 target 当前跳过（不写入 targets），
    以保证导出不崩溃。后续校验阶段应改为报错。
    """
    from ..efx_format.efxfile import PlayData, PlayEntry

    try:
        props = play_obj.efx_play
    except AttributeError:
        return _fallback_raw_play(play_obj)

    # ── play_type ─────────────────────────────────────────────────────────────
    try:
        play_type = int(str(props.play_type_str))
    except (ValueError, TypeError):
        return _fallback_raw_play(play_obj)

    # ── 重建 entries ──────────────────────────────────────────────────────────
    entries = []
    for item in props.entries:
        try:
            type_hash = int(str(item.type_hash_str))
        except (ValueError, TypeError):
            # 异常：走单 entry 的 raw_b64 回退
            raw = _b64dec(str(item.raw_b64))
            entries.append(PlayEntry(type_hash=type_hash, raw=raw))
            continue

        if item.is_emitter:
            # ── PLAYEMITTER：只替换 targets 段，其余字节逐字保留 ──────────────
            raw = _rebuild_emitter_raw(item, body_index_map)
        else:
            # ── PLAYEFX（或其他）：raw 原样 ────────────────────────────────────
            raw = _b64dec(str(item.raw_b64))

        entries.append(PlayEntry(type_hash=type_hash, raw=raw))

    return PlayData(play_type=play_type, entries=entries)


def _rebuild_emitter_raw(item: EFXPlayEntryProps,
                         body_index_map: dict) -> bytes:
    """
    重建 PlayEmitter entry 的 raw 字节。

    策略：
      1. 从 raw_b64 取出原始字节，保留 raw[:52]（unkn[7]+xyz+NULL[3]）逐字不动。
      2. 从 item.targets 解析出 body 指针 → 局部 index 列表。
      3. pack('<i', N) 写 target_count（bytes 52-55）。
      4. 依次 pack('<i', idx) 写 targets（bytes 56+）。

    悬空 target（body_ptr=None 或不在 body_index_map）静默跳过。
    """
    orig_raw = _b64dec(str(item.raw_b64))

    # 构建 target 索引列表
    target_indices = []
    for t in item.targets:
        body_obj = t.body_ptr
        if body_obj is None:
            # TODO: 后续校验阶段改为报错，当前静默跳过
            continue
        local_idx = body_index_map.get(body_obj)
        if local_idx is None:
            # body_obj 不在当前文件的 Main 段里
            # TODO: 同上
            continue
        target_indices.append(local_idx)

    # 保留前缀字节（offset 0..51，含 unkn[7]+xyz+NULL[3]，共 52 字节）
    prefix = orig_raw[:52]

    # 重写 target_count + targets
    N = len(target_indices)
    new_raw = prefix + struct.pack('<i', N)
    for idx in target_indices:
        new_raw += struct.pack('<i', idx)

    return new_raw


def _fallback_raw_play(play_obj: bpy.types.Object):
    """
    兼容回退：从自定义属性 raw_b64 原样还原 PlayData（旧 opaque 路径）。
    用于 play_obj 没有 efx_play PropertyGroup 数据的情况（旧 .blend / 兼容）。
    """
    from ..efx_format.efxfile import PlayData, PlayEntry

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
        entries.append(PlayEntry(type_hash=type_hash, raw=entry_raw))

    return PlayData(play_type=play_type, entries=entries)


# ─────────────────────────────────────────────────────────────────────────────
# §5  面板算子（当前阶段：仅支持编辑已有 target 指向，不支持增删）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_play_target_add(Operator):
    """向当前 PlayEmitter entry 新增一个空 target（body_ptr 待用户指定）"""

    bl_idname      = "efx.play_target_add"
    bl_label       = "添加 Target"
    bl_description = "向 PlayEmitter targets 列表末尾追加一个空槽位"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: IntProperty(name="Entry Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_PLAY"

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


class EFX_OT_play_target_remove(Operator):
    """删除当前激活的 PlayEmitter target"""

    bl_idname      = "efx.play_target_remove"
    bl_label       = "移除 Target"
    bl_description = "删除 PlayEmitter targets 列表中当前激活的 target"
    bl_options     = {"REGISTER", "UNDO"}

    entry_index: IntProperty(name="Entry Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_PLAY":
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
# §6  UIList：PlayEmitter target 列表
# ─────────────────────────────────────────────────────────────────────────────

class EFX_UL_play_targets(bpy.types.UIList):
    """
    UIList 显示 EFXPlayTarget 列表。
    每行显示：序号 + body_ptr 指向的对象名（悬空时显示 <未设置>）。
    """

    bl_idname = "EFX_UL_play_targets"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index}:", icon="BLANK1")
        body_obj = item.body_ptr
        if body_obj is not None:
            row.prop(item, "body_ptr", text="", icon="OBJECT_DATA")
        else:
            row.prop(item, "body_ptr", text="<未设置>", icon="ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# §7  面板：N 面板 EFX 标签 Play 数据显示
# ─────────────────────────────────────────────────────────────────────────────

def _extract_playefx_path(raw: bytes) -> str:
    """
    从 PlayEFX entry raw 字节中提取路径字符串（只读显示用）。

    PlayEFX raw 布局（type_hash 之后）：
      offset  0: int unkn0      (4B)
      offset  4: int path_len   (4B)
      offset  8: long type      (4B)
      offset 12: int unkn[7]    (28B)
      offset 40: XYZ xyz(3)     (12B)   float[3]
      offset 52: int NULL[3]    (12B)
      offset 64: char p[path_len]
    """
    if len(raw) < 8:
        return "(raw 太短)"
    try:
        path_len = struct.unpack_from('<i', raw, 4)[0]
        if path_len <= 0 or 64 + path_len > len(raw):
            return "(路径偏移越界)"
        path_bytes = raw[64:64 + path_len]
        # null-terminated
        null_pos = path_bytes.find(b'\x00')
        if null_pos >= 0:
            path_bytes = path_bytes[:null_pos]
        return path_bytes.decode('utf-8', errors='replace')
    except Exception as e:
        return f"(解析失败: {e})"


class EFX_PT_play(bpy.types.Panel):
    """
    Play 数据面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_PLAY 对象时显示：
      - play_type 元数据（只读）
      - 各 entry 列表：
          PLAYEFX  → 路径（只读字符串）
          PLAYEMITTER → target body 指针列表（可编辑指向）
      - 悬空 target 指针警告

    设计理念（CLAUDE §4）：
      Play ↔ body 归属关系是结构关系（工具功能），放 N 面板。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Play 数据"
    bl_parent_id   = "EFX_PT_main"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_PLAY"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_play
        except AttributeError:
            layout.label(text="（无 efx_play 数据）", icon="ERROR")
            return

        # ── 元数据行（只读）─────────────────────────────────────────────────────
        meta_box = layout.box()
        meta_box.label(text="Play 元数据", icon="INFO")
        meta_box.label(text=f"Play Type: {props.play_type_str}")
        meta_box.label(text=f"Entries: {len(props.entries)} 个")

        layout.separator()

        # ── 各 entry 展开 ────────────────────────────────────────────────────────
        total_dangling = 0
        for ei, entry in enumerate(props.entries):
            entry_box = layout.box()

            if entry.is_emitter:
                # ── PLAYEMITTER：显示 target 指针列表 ─────────────────────────
                header_row = entry_box.row(align=True)
                header_row.label(
                    text=f"Entry {ei}  PLAYEMITTER",
                    icon="LINKED",
                )
                # targets 列表
                tgt_count = len(entry.targets)
                entry_box.label(
                    text=f"Targets（{tgt_count} 个）",
                    icon="OUTLINER_OB_EMPTY",
                )

                list_row = entry_box.row()
                list_row.template_list(
                    "EFX_UL_play_targets",       # UIList bl_idname
                    f"play_targets_{ei}",         # list_id（区分多个 entry）
                    entry,                        # data
                    "targets",                    # propname
                    entry,                        # active_data
                    "active_target_index",        # active_propname
                    rows=3,
                )

                # 增删按钮列
                btn_col = list_row.column(align=True)
                add_op = btn_col.operator(
                    "efx.play_target_add", text="", icon="ADD"
                )
                add_op.entry_index = ei
                rem_op = btn_col.operator(
                    "efx.play_target_remove", text="", icon="REMOVE"
                )
                rem_op.entry_index = ei

                # 激活 target 详情
                ati = entry.active_target_index
                if 0 <= ati < tgt_count:
                    active_tgt = entry.targets[ati]
                    detail_row = entry_box.row()
                    detail_row.prop(active_tgt, "body_ptr", text="Body 对象")

                # 统计悬空
                dangling = sum(1 for t in entry.targets if t.body_ptr is None)
                total_dangling += dangling
                if dangling > 0:
                    warn = entry_box.row()
                    warn.alert = True
                    warn.label(
                        text=f"⚠ {dangling} 个 target 指针悬空（导出时跳过）",
                        icon="ERROR",
                    )

            else:
                # ── PLAYEFX：只读显示路径 ─────────────────────────────────────
                header_row = entry_box.row(align=True)
                header_row.label(
                    text=f"Entry {ei}  PLAYEFX",
                    icon="FILE_BLEND",
                )
                raw = base64.b64decode(str(entry.raw_b64))
                path_str = _extract_playefx_path(raw)
                path_row = entry_box.row()
                path_row.label(text=f"Path: {path_str}", icon="LINKED")

        # ── 整体悬空警告 ─────────────────────────────────────────────────────────
        if total_dangling > 0:
            layout.separator()
            warn_row = layout.row()
            warn_row.alert = True
            warn_row.label(
                text=f"⚠ 共 {total_dangling} 个 target 指针悬空",
                icon="ERROR",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 注册顺序：PropertyGroup 子类先于容器类；UIList/Operator/Panel 次之。
# EFXPlayTarget 必须在 EFXPlayEntryProps 之前，EFXPlayEntryProps 在 EFXPlayProps 之前。
_CLASSES_CORE = (
    EFXPlayTarget,
    EFXPlayEntryProps,
    EFXPlayProps,
    EFX_UL_play_targets,
    EFX_OT_play_target_add,
    EFX_OT_play_target_remove,
)

# EFX_PT_play 导出给 panels.py，由 panels.register() 在 EFX_PT_main 之后注册。


def register():
    """
    注册 Play 核心类（PropertyGroup + UIList + Operator）。
    并把 EFXPlayProps 挂到 Object 上。

    注意：EFX_PT_play 面板由 panels.py 在 EFX_PT_main 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_play = PointerProperty(
        name="EFX Play 属性",
        description="EFX_PLAY 对象的结构化 Play 数据",
        type=EFXPlayProps,
    )


def unregister():
    """
    注销 Play 核心类并清理 PointerProperty。
    EFX_PT_play 由 panels.py 先注销。
    """
    try:
        del bpy.types.Object.efx_play
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
