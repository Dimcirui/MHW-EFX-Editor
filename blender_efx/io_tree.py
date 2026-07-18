"""
blender_efx/io_tree.py  —  L1.0：EFX ↔ Blender 对象树 导入/导出

设计原则（参照 CLAUDE.md）：
  - 只使用 Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：collections.new / objects.new(Empty) / collection.objects.link
    / obj.parent / obj["key"] / empty_display_size
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：拿不准的结构全部 base64 原样保存

对象树结构（COLOR_06 紫色，~TYPE 标记类型）：
  <文件名集合> [COLOR_06]  (~TYPE='EFX_ROOT')   # 顶层集合本身即"文件"，存 header 全字段
  ├── _0 Action  子集合 (~TYPE='EFX_ACTION_COLLECTION')
  │   └── EFX_ACTION  (~TYPE='EFX_ACTION')
  ├── _1 Extern  子集合 (~TYPE='EFX_EXTERN_COLLECTION')
  │   └── EFX_EXTERN  (~TYPE='EFX_EXTERN')
  ├── _2 Entry   子集合 (~TYPE='EFX_ENTRY_COLLECTION')
  │   └── EFX_ENTRY  (~TYPE='EFX_ENTRY')  # 每个 Main body
  │       └── <hash_name>  (~TYPE='EFX_ATTRIBUTE')  # 每个 AttrBlock（.parent=entry，嵌套关系不变）
  └── _3 Subselect 子集合 (~TYPE='EFX_SUBSELECT_COLLECTION')
      └── EFX_SUBSELECT (~TYPE='EFX_SUBSELECT')

2026-07 起 EFX_ROOT 不再是 Empty 对象——"entry/action/extern/subselect 属于哪个文件"
不再靠 `obj.parent == root_obj`，改靠集合归属（见 root_collection.py）。
attribute→entry / EFX_TIML→entry 这两层嵌套 parent 完全不受影响。
"""

import bpy
import base64
import os
import struct

from ..efx_format.efxfile import (
    EFXFile,
    EFXHeader,
    ActionData,
    ActionEntry,
    ExternAttribute,
    ExternDataItem,
    AttrBlock,
    EntryData,
    EntryDataExtended,
    RootBody,
    RootUnitBoundary,
    RootOpaqueEntry,
    SubselectTable,
)
from ..efx_format.hashes import HASH_TO_NAME
from ..efx_format.hashes import pretty_type_name as _pretty_type_name

# 导入字段模型模块（延迟导入，避免注册顺序问题）
# init_attribute_props 和 get_attribute_data_bytes 在实际调用时才被解析
from . import fields as _fields
from . import subselect as _subselect
from . import action_emitter as _action_emitter
from . import extern_ref as _extern_ref
from . import entry_action_ref as _entry_action_ref
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    """bytes → base64 字符串（存入自定义属性）。"""
    return base64.b64encode(data).decode("ascii")


def _b64dec(s: str) -> bytes:
    """base64 字符串 → bytes（从自定义属性还原）。"""
    return base64.b64decode(s)


def _new_collection(name: str, parent_col) -> bpy.types.Collection:
    """建新集合并链接到父集合，返回新集合。"""
    col = bpy.data.collections.new(name)
    parent_col.children.link(col)
    return col


def _new_empty(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    """在指定集合里建 Empty 对象，返回对象。"""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    collection.objects.link(obj)
    return obj


def _set_parent(child: bpy.types.Object, parent: bpy.types.Object) -> None:
    """设置父子关系（不移动位置）。"""
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


# ─────────────────────────────────────────────────────────────────────────────
# EFX_TIML 句柄对象（TIML 统一入口）
# ─────────────────────────────────────────────────────────────────────────────
# TIML 在字节上从属于 body（timl_length 界定，先于 attr_blocks），不是独立 attr block。
# 为收敛割裂的 TIML 入口（导入导出 / 长度循环 / 预览），给每个**含 TIML 的 body** 建一个
# ~TYPE="EFX_TIML" 子 Empty 作 UI 句柄：选中它即可在面板里访问全部 TIML 操作。
# 它**不持有数据**——timl_bytes/timl_length 仍权威存于 body（导出字节逻辑原封不动，
# 故 byte-perfect 不受影响；EFX_TIML 既非 EFX_ENTRY 也非 EFX_ATTRIBUTE，被导出/重排/删除/校验
# 的类型过滤天然忽略）。所有面板/算子经 resolve_timl_entry() 把句柄解析回父 body 后操作。

def find_timl_handle(entry_obj: bpy.types.Object):
    """返回 body 下的 EFX_TIML 句柄对象，无则 None。"""
    if entry_obj is None:
        return None
    for c in bpy.data.objects:
        if c.parent == entry_obj and c.get("~TYPE") == "EFX_TIML":
            return c
    return None


def make_timl_handle(entry_obj: bpy.types.Object, collection: bpy.types.Collection = None):
    """为 body 创建（或复用）EFX_TIML 句柄子对象。"""
    existing = find_timl_handle(entry_obj)
    if existing is not None:
        return existing
    if collection is None:
        cols = entry_obj.users_collection
        collection = cols[0] if cols else bpy.context.scene.collection
    label = str(entry_obj.get("efx_raw_label", "")) or entry_obj.name
    h = bpy.data.objects.new("%s TIML" % label, None)
    h.empty_display_type = 'SPHERE'
    h.empty_display_size = 0.12
    collection.objects.link(h)
    h["~TYPE"] = "EFX_TIML"
    h.parent = entry_obj
    return h


# 导出时是否把 TIML 长度重算为末帧+1（由 export_efx_tree 的 recalc_timl_length 逐次设置）
_EXPORT_RECALC_TIML_LEN = False


def _recalc_timl_length(data: bytes) -> bytes:
    """把每条存在的 TIML 动画的 animation_length 精确设为 末关键帧+1（逐轴）。定长原地 patch。"""
    from ..efx_format import timl_meta as _tm
    try:
        anims = _tm.parse_animations(data)
    except Exception:
        return data
    for slot, a in enumerate(anims):
        if getattr(a, "data_offset", 0) == 0:
            continue
        lk = _tm.last_keyframe_time(data, slot)
        if lk is not None:
            data = _tm.set_animation_length(data, slot, float(lk) + 1.0)
    return data


def _export_timl_bytes(entry_obj: bpy.types.Object) -> bytes:
    """Phase 3 导出用 TIML 字节：句柄有持久 fcurve → 从 fcurve 同步回字节（含用户编辑）；
    无 fcurve / 空 / 非-timl → 存储的 timl_bytes verbatim（sync_fcurves_to_bytes 内部已兜底）。
    最后若开启 recalc_timl_length，逐轴把长度设为末帧+1。"""
    stored = _b64dec(str(entry_obj.get("timl_bytes", "")))
    if not stored:
        return stored
    data = stored
    try:
        from . import timl_edit as _te
        h = find_timl_handle(entry_obj)
        if h is not None:
            data = bytes(_te.sync_fcurves_to_bytes(h, entry_obj))
    except Exception:
        data = stored
    if _EXPORT_RECALC_TIML_LEN and data[:4] == b"timl":
        data = _recalc_timl_length(data)
    return data


def _hash_display_name(type_hash: int) -> str:
    """用 hash 查已知名；没注册的用 0x 十六进制。"""
    return HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")


def split_labels_tail(label_bytes: bytes, n_max: int):
    """
    切分 EFX_Type 标签区为 (labels, tail)。

    标签区真实结构（实测 78/78 byte-perfect）：
        [k 个 null 结尾标签] + [tail 不透明尾字节]
      - 标签位置性映射到 [Play|Extern|Main] 顺序的前 k 个条目（k ≤ n_max）；
        第 k 个之后的条目没有标签（不占字节，非空槽）。
      - tail 是标签耗尽后剩余的字节，可能含非零字节（如 0x3c/0x3e，
        旧 split+filter 会误当成单字符标签 '<'/'>'）。

    切分规则：逐个读 null 结尾串，遇第一个空串即停，剩余即 tail。
    最多读 n_max 个（= count_play + count_extern + count_body）。

    重建（byte-perfect）：b''.join(s + b'\\x00' for s in labels) + tail == label_bytes
    """
    labels = []
    pos = 0
    while len(labels) < n_max:
        end = label_bytes.find(b'\x00', pos)
        if end == -1:
            break  # 没有终止 null 了
        seg = label_bytes[pos:end]
        if seg == b'':
            break  # 空串 → tail 开始
        labels.append(seg.decode('utf-8', errors='replace'))
        pos = end + 1
    tail = label_bytes[pos:]
    return labels, tail


# ─────────────────────────────────────────────────────────────────────────────
# import_efx_tree
# ─────────────────────────────────────────────────────────────────────────────

def import_efx_tree(filepath: str, context=None, color_editor_mode: bool = False) -> bpy.types.Collection:
    """
    解析 .efx 文件，在场景里建立对象树。

    参数
    ----
    filepath : str
        .efx 文件的绝对路径。
    context : bpy.types.Context, optional
        Blender 上下文。若为 None，用 bpy.context。
    color_editor_mode : bool, optional
        True＝"仅导入颜色"（EFX Color Editor）。完整解析/建树完全不变（数据
        100% 保留、导出路径不动，byte-perfect 天然保住）；仅在建树完成后追加一步
        UI 精简：含颜色字段的 entry/attribute 额外 link 进 root_col 本身（多重
        归属，不从原叶子集合 unlink），其余四个正常叶子集合从当前场景全部 View
        Layer 排除（仅隐藏 Outliner 显示）。见 `_apply_color_editor_view`。

    返回
    ----
    bpy.types.Collection
        顶层文件集合（root_col，~TYPE=='EFX_ROOT'）。2026-07 起 ROOT 不再是
        Empty 对象，调用方若期望 Object 需相应更新（见 root_collection.py）。
    """
    ctx = context if context is not None else bpy.context

    # ── 1. 解析文件 ─────────────────────────────────────────────────────────
    with open(filepath, "rb") as f:
        raw_data = f.read()
    efx = EFXFile.parse(raw_data)
    hdr = efx.header

    file_stem = os.path.splitext(os.path.basename(filepath))[0]
    file_name = os.path.basename(filepath)   # 含 .efx 后缀，用作顶层集合名（仿 mrl3）

    # ── 2. 建顶层集合（紫色 COLOR_06，本身即"文件"，~TYPE=EFX_ROOT）────────────
    scene_col = ctx.scene.collection
    # Color Editor 模式：集合名加 "_color" 后缀区分（同样紫色 COLOR_06，用户
    # 描述的"一个紫色的 XXX_color.efx 集合"——root_col 本身即是它）。
    root_col_name = f"{file_stem}_color.efx" if color_editor_mode else file_name
    root_col = _rc.new_root_collection(root_col_name, scene_col)
    root_col["color_editor_mode"] = 1 if color_editor_mode else 0

    # ── 3. header 全部字段直接存 root_col 自定义属性（不再建 Empty）────────────
    # header 字段：signature/efxr 存 hex；
    # 所有 uint32 字段存十进制字符串（避免 Blender C int 32 位溢出）；
    # constant（5 × uint32）存逗号分隔十进制字符串。
    root_col["hdr_signature"]       = hdr.signature.hex()          # "45465800"
    root_col["hdr_version"]         = str(hdr.version)
    root_col["hdr_constant"]        = ",".join(str(x) for x in hdr.constant)
    root_col["hdr_efxr"]            = hdr.efxr.hex()               # "65667872"
    root_col["hdr_unkn0"]           = str(hdr.unkn0)
    root_col["hdr_unkn1"]           = str(hdr.unkn1)
    root_col["hdr_count_body"]      = str(hdr.count_body)
    root_col["hdr_label_size"]      = str(hdr.label_size)
    root_col["hdr_count_play"]      = str(hdr.count_play)
    root_col["hdr_count_extern"]    = str(hdr.count_extern)
    root_col["hdr_count_subselect"] = str(hdr.count_subselect)
    root_col["hdr_subselect_size"]  = str(hdr.subselect_size)
    root_col["hdr_count_eof"]       = str(hdr.count_eof)
    root_col["hdr_double_buffer"]   = str(hdr.double_buffer)

    # label_bytes：整段 base64（label 表是 opaque blob，导出默认 verbatim 走它）
    root_col["label_bytes"]         = _b64enc(efx.label_bytes)
    # 干净切分标签 + tail（重建路径用）：标签位置性映射到 [Play|Extern|Main] 前 k 个条目，
    # tail 是不透明尾字节（含非零字节，须 verbatim 保留）。详见 split_labels_tail。
    _clean_labels, _label_tail = split_labels_tail(
        efx.label_bytes, hdr.count_play + hdr.count_extern + hdr.count_body)
    root_col["label_tail"]          = _b64enc(_label_tail)
    # labels_dirty：0=未编辑标签/结构 → 导出 emit verbatim blob；1=改名/增删 → 重建。
    root_col["labels_dirty"]        = 0
    _n_labels                       = len(_clean_labels)  # 全局有标签条目数 k
    # eof_ints：每个元素是 uint32，存逗号分隔十进制字符串；空列表存 ""
    root_col["eof_ints"]            = ",".join(str(x) for x in efx.eof_ints)
    # eof 后不透明 footer（部分游戏文件有，如 jichu1.efx 末尾 4 字节）；多数为空
    root_col["eof_tail"]            = _b64enc(efx.eof_tail)

    # main 段不可解析的 opaque 回退文件：整段（main 起点→EOF）无法逐块解析，
    # 存整文件原始字节，导出时 verbatim 透传（保证 byte-perfect，但此文件只读）。
    if getattr(efx, "main_opaque", False):
        root_col["main_opaque_file_b64"] = _b64enc(raw_data)

    # ── 4. 建 4 个叶子子集合（含序号前缀，控制大纲排序；~TYPE + efx_root_ptr 反向指针）──
    # 按 EFX 文件段顺序：0 Action、1 Extern、2 Entry、3 Subselect
    col_entry     = _rc.new_leaf_collection(file_stem + "_2 Entry",     root_col, "EFX_ENTRY")
    col_action    = _rc.new_leaf_collection(file_stem + "_0 Action",    root_col, "EFX_ACTION")
    col_extern    = _rc.new_leaf_collection(file_stem + "_1 Extern",    root_col, "EFX_EXTERN")
    col_subselect = _rc.new_leaf_collection(file_stem + "_3 Subselect", root_col, "EFX_SUBSELECT")

    # ── 5. Main：每个 body 建 Empty ─────────────────────────────────────────
    #
    # 标签顺序：efx.labels 对应 [Play | Extern | Main] 三段顺序拼合的 labels。
    # Play 段标签数 = count_play；Extern 段标签数 = count_extern；
    # Main 段标签从 (count_play + count_extern) 起。
    # 注：实际上 labels 的构建方式是 label_bytes.split('\0')，
    #   其中包含 Play + Extern + Main 全部标签，顺序与各段条目一一对应。
    play_label_count   = hdr.count_play
    extern_label_count = hdr.count_extern
    main_label_offset  = play_label_count + extern_label_count

    for body_idx, body in enumerate(efx.main):
        # 全局位置 = [Play|Extern|Main] 顺序的偏移；前 _n_labels 个条目才有标签
        label_idx = main_label_offset + body_idx
        has_label = label_idx < _n_labels
        if has_label:
            label_name = _clean_labels[label_idx]
        else:
            label_name = f"body_{body_idx}"  # 合成名（不进标签表）

        # 序号前缀：零填充 2 位（>99 时自动扩展），控制大纲排序
        # 仅影响 Blender 显示名，不影响 efx_index（导出排序依据）
        nn = str(body_idx).zfill(2) if body_idx < 100 else str(body_idx)
        raw_label = label_name or f"body_{body_idx}"
        display_name = f"{nn} {raw_label}"

        # Blender 会自动给重名对象加 .001 后缀，这里不做额外处理
        entry_obj = _new_empty(display_name, col_entry)
        entry_obj.empty_display_type = 'ARROWS'   # XYZ 三色轴，使特效体朝向直观可见
        entry_obj["~TYPE"]         = "EFX_ENTRY"
        entry_obj["efx_index"]     = body_idx  # 原始顺序，还原时用
        entry_obj["efx_raw_label"] = raw_label  # L2 #3a：原始标签，重排重建显示名用
        entry_obj["efx_has_label"] = int(has_label)  # 1=有原始标签, 0=合成标签
        # 归属靠 col_entry（其 efx_root_ptr 指回 root_col），不再额外 parent 到 ROOT

        if isinstance(body, RootBody):
            entry_obj["entry_kind"] = "root"
            # 仅当全部子条目都是 UnitBoundary（实测 100% 官方样本如此）才结构化为
            # 可编辑字段；含 RenderTarget/LayoutBank 或整段不透明回退时存 base64 只读。
            structurable = (
                body.raw is None
                and all(isinstance(e, RootUnitBoundary) for e in body.entries)
            )
            if structurable:
                entry_obj["root_structured"] = 1
                entry_obj["root_const0"]     = str(body.const0)
                entry_obj["root_const1"]     = str(body.const1)
                entry_obj["root_ub_count"]   = len(body.entries)
                for j, e in enumerate(body.entries):
                    # 原生数组 IDProperty → panel 可直接 layout.prop 编辑
                    entry_obj["root_ub%d_ints" % j]   = list(e.ints)
                    entry_obj["root_ub%d_floats" % j] = list(e.floats)
            else:
                entry_obj["root_structured"] = 0
                entry_obj["raw"]             = _b64enc(body.serialize())

        elif isinstance(body, EntryDataExtended):
            # 扩展头（body_type < 256，36B 头）
            # 所有数值字段存十进制字符串（uint32 可 ≥ 2^31，Blender C int 会溢出）
            entry_obj["entry_kind"]    = "extended"
            entry_obj["body_type"]    = str(body.body_type)
            entry_obj["unkn0"]        = str(body.unkn0)
            entry_obj["null0"]        = str(body.null0)
            entry_obj["null1"]        = str(body.null1)
            entry_obj["unkn1"]        = str(body.unkn1)
            entry_obj["unkn2"]        = str(body.unkn2)
            entry_obj["attr_count"]   = str(body.attr_count)
            entry_obj["null2"]        = str(body.null2)
            entry_obj["timl_length"]  = str(body.timl_length)
            entry_obj["timl_bytes"]   = _b64enc(body.timl_bytes)
            # AttrBlock 子对象（extern 指针化在 §7b 二次 pass 完成）
            _build_attr_attribute_children(body.attr_blocks, entry_obj, col_entry, raw_label)
            if body.timl_length > 0:
                _h = make_timl_handle(entry_obj, col_entry)   # TIML 统一入口句柄
                # Phase 3：导入即把 TIML 持久化为句柄上的原生 fcurve（值编辑面；导出时同步回字节）
                try:
                    from . import timl_edit as _te
                    _te.build_persistent_fcurves(_h, entry_obj)
                except Exception:
                    pass

        elif isinstance(body, EntryData):
            # 标准头（20B 头）
            # 所有数值字段存十进制字符串（uint32 可 ≥ 2^31，Blender C int 会溢出）
            entry_obj["entry_kind"]   = "standard"
            entry_obj["body_type"]   = str(body.body_type)
            entry_obj["unkn0"]       = str(body.unkn0)
            entry_obj["attr_count"]  = str(body.attr_count)
            entry_obj["null"]        = str(body.null)
            entry_obj["timl_length"] = str(body.timl_length)
            entry_obj["timl_bytes"]  = _b64enc(body.timl_bytes)
            # AttrBlock 子对象（extern 指针化在 §7b 二次 pass 完成）
            _build_attr_attribute_children(body.attr_blocks, entry_obj, col_entry, raw_label)
            if body.timl_length > 0:
                _h = make_timl_handle(entry_obj, col_entry)   # TIML 统一入口句柄
                # Phase 3：导入即把 TIML 持久化为句柄上的原生 fcurve（值编辑面；导出时同步回字节）
                try:
                    from . import timl_edit as _te
                    _te.build_persistent_fcurves(_h, entry_obj)
                except Exception:
                    pass

        else:
            # 未知类型：保守存整段 serialize()
            entry_obj["entry_kind"] = "unknown"
            entry_obj["raw"]       = _b64enc(body.serialize())

    # ── 6. Play：L2 #1b 结构化存储（替换纯 opaque）────────────────────────────
    #
    # main_bodies_by_index 在 §8（Subselect）构建前暂不可用，
    # 但 §5 Main 段已建完——提前在此处用相同逻辑构建一次，供 PlayEmitter 解析用。
    # （Subselect 的 main_bodies_by_index 在 §8 再次独立构建，逻辑不重叠）
    _action_entries_by_index = {
        int(_bo["efx_index"]): _bo
        for _bo in _rc.collect_top_level(root_col, "EFX_ENTRY")
    }

    for i, pd in enumerate(efx.play):
        # Play 段全局位置 = i（[Play|Extern|Main] 最前）；前 _n_labels 个才有标签
        has_label = i < _n_labels
        play_label = _clean_labels[i] if has_label else f"play_{i}"
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj_name = f"{nn} {play_label}" if play_label else f"{nn} play_{i}"
        obj = _new_empty(obj_name, col_action)
        obj["~TYPE"]         = "EFX_ACTION"
        obj["efx_index"]     = i
        obj["efx_raw_label"] = play_label       # 标签重建用
        obj["efx_has_label"] = int(has_label)   # 1=有原始标签, 0=合成名（不进标签表）
        obj["raw_b64"]       = _b64enc(pd.serialize())

        # ── L2 #1b：结构化初始化 ──────────────────────────────────────────────
        try:
            _action_emitter.init_action_props(obj, pd, _action_entries_by_index)
        except Exception:
            # 任何异常均安全回退：raw_b64 保证 byte-perfect
            pass

    # ── 7. Extern：L1.0 简化，每个 ExternAttribute 存 serialize() 字节 ──────
    for i, ea in enumerate(efx.extern):
        # Extern 段全局位置 = play_label_count + i；前 _n_labels 个才有标签
        extern_label_idx = play_label_count + i
        has_label = extern_label_idx < _n_labels
        extern_label = _clean_labels[extern_label_idx] if has_label else f"extern_{i}"
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj_name = f"{nn} {extern_label}" if extern_label else f"{nn} extern_{i}"
        obj = _new_empty(obj_name, col_extern)
        obj["~TYPE"]         = "EFX_EXTERN"
        obj["efx_index"]     = i
        obj["efx_raw_label"] = extern_label     # 标签重建用
        obj["efx_has_label"] = int(has_label)   # 1=有原始标签, 0=合成名（不进标签表）
        obj["raw_b64"]       = _b64enc(ea.serialize())
        try:
            from . import extern_props as _ep
            _ep.init_extern_props(obj, ea)
        except Exception:
            pass  # 任何异常安全跳过，raw_b64 保底

    # ── 7b. ExternReference 指针化二次 pass（L2 #1c）──────────────────────────
    #
    # §5 Main 段建立时 Extern 对象尚未存在，所以 init_attribute_props 当时拿不到
    # extern_objs_by_index。现在 §7 Extern 段已建完，补做二次 pass：
    # 遍历所有 EXTERNREFERENCE 块，调用 extern_ref.init_extern_ref_props 完成指针化。
    #
    # 构建 {efx_index → EFX_EXTERN 对象} 映射
    _extern_objs_by_index = {
        int(_eo["efx_index"]): _eo
        for _eo in _rc.collect_top_level(root_col, "EFX_EXTERN")
    }

    _count_extern = hdr.count_extern  # 文件头的 count_extern

    # 遍历所有 EFX_ATTRIBUTE，找 EXTERNREFERENCE 类型补做指针化
    # 只扫 col_entry.objects（本次导入这一个文件的 Entry 叶子集合，attribute 与其
    # 所属 entry 同挂在这里）——不扫全场景 bpy.data.objects。曾经错误地扫全场景，
    # 导入耗时随场景里已加载的其它 EFX 文件数量线性增长，累计多文件导入接近
    # O(n²)，已修（find_root_collection 校验因此也变得多余，直接删掉）。
    try:
        from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
        for _blk_obj in col_entry.objects:
            if _blk_obj.get("~TYPE") != "EFX_ATTRIBUTE":
                continue
            try:
                bp = _blk_obj.efx_block
                if int(bp.type_hash_str) != _EXTERNREFERENCE_HASH:
                    continue
                # 从 raw_b64 恢复 data_bytes 用于读 referenceIndex
                _data_bytes = base64.b64decode(str(bp.raw_b64))
                _extern_ref.init_extern_ref_props(
                    _blk_obj,
                    _data_bytes,
                    _extern_objs_by_index,
                    _count_extern,
                )
            except Exception:
                # 任何异常安全跳过（efx_extern_ref 保持默认 pointerized=False）
                pass
    except (ImportError, Exception):
        pass

    # ── 7c. PTLIFE/PTCOLLISION 指针化二次 pass（L2 #1d）─────────────────────────
    #
    # Main 段已建完（§5），Play 段已建完（§6）——现在可以做 PTLIFE / PTCOLLISION 块
    # 的引用指针化：
    #   PTLIFE.relationIndex     → play(action) 指针（Play 局部 index）
    #   PTCOLLISION.ieIndex      → play 指针（Play 局部 index）
    #
    # 构建 {efx_index → EFX_ENTRY} 和 {efx_index → EFX_ACTION} 映射
    _main_bodies_by_index_1d = {
        int(_bo["efx_index"]): _bo
        for _bo in _rc.collect_top_level(root_col, "EFX_ENTRY")
    }
    _action_objs_by_index_1d = {
        int(_po["efx_index"]): _po
        for _po in _rc.collect_top_level(root_col, "EFX_ACTION")
    }

    _count_body_1d = hdr.count_body
    _count_play_1d = hdr.count_play

    # 同上：只扫 col_entry.objects，不扫全场景（见 §7b 同款修复说明）。
    try:
        from ..efx_format.hashes import (
            PTLIFE as _PTLIFE_HASH,
            PTCOLLISION as _PTCOLLISION_HASH,
        )
        for _blk_obj in col_entry.objects:
            if _blk_obj.get("~TYPE") != "EFX_ATTRIBUTE":
                continue
            try:
                bp = _blk_obj.efx_block
                _type_hash = int(bp.type_hash_str)
                _data_bytes_1d = base64.b64decode(str(bp.raw_b64))

                if _type_hash == _PTLIFE_HASH:
                    _entry_action_ref.init_ptlife_ref_props(
                        _blk_obj,
                        _data_bytes_1d,
                        _action_objs_by_index_1d,
                        _count_play_1d,
                    )
                elif _type_hash == _PTCOLLISION_HASH:
                    _entry_action_ref.init_ptcollision_ref_props(
                        _blk_obj,
                        _data_bytes_1d,
                        _action_objs_by_index_1d,
                        _count_play_1d,
                    )
            except Exception:
                # 任何异常安全跳过（props 保持默认 pointerized=False）
                pass
    except (ImportError, Exception):
        pass

    # ── 8. Subselect：L2 #1a 结构化存储（替换 opaque）──────────────────────────
    #
    # 构建 {efx_index → EFX_ENTRY 对象} 映射，供 init_subselect_props 解析 entries。
    main_bodies_by_index = {
        int(entry_obj["efx_index"]): entry_obj
        for entry_obj in _rc.collect_top_level(root_col, "EFX_ENTRY")
    }

    for i, tbl in enumerate(efx.subselect):
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj = _new_empty(f"{nn} subselect_{i}", col_subselect)
        obj["~TYPE"]     = "EFX_SUBSELECT"
        obj["efx_index"] = i
        # raw_b64：byte-perfect 回退（始终写入，与 L1.0 一致；结构化导出优先）
        obj["raw_b64"]   = _b64enc(tbl.serialize())

        # ── L2 #1a：结构化初始化 ──────────────────────────────────────────────
        try:
            _subselect.init_subselect_props(obj, tbl, main_bodies_by_index)
        except Exception:
            # 任何异常均安全回退：raw_b64 保证 byte-perfect
            pass

    # ── 9. eof：载体下放到 entry 归属的嵌套集合（hybrid 闸门，结构权威下放重构）───
    #
    # 干净(升序+无重复+全 in-range) → per_entry：激活 entry 移入 Entry 叶子集合下嵌套的
    #   Direct Trigger 子集合，悬空指针从原理上消失、raw 噪声清零。不干净(evc 浮点结构)
    #   → opaque：root_col["eof_ints"] 字符串原样直通（§3 已写入）。
    #   main_bodies_by_index 已在 §8 构建完毕。
    try:
        _entry_action_ref.init_eof_per_entry(
            root_col,
            efx.eof_ints,
            main_bodies_by_index,
            hdr.count_body,
        )
    except Exception:
        # 任何异常安全跳过：root_col["eof_ints"] 字符串仍在，导出回退路径保证 byte-perfect
        pass

    # ── 10. 满命名（结构权威下放）：给未命名 action/extern/entry 补标签 ─────────
    # 只写标签层（has_label/raw_label/显示名），不动 body_type/play_type 身份哈希
    # （未命名段的哈希是权威身份，语料实证保留即可）。满命名后标签前缀恒满，
    # copy/duplicate 不再破坏前缀。有补名 → labels_dirty=1 使导出按全命名重建标签表。
    try:
        from . import normalize
        if normalize.ensure_all_named(root_col):
            root_col["labels_dirty"] = 1
    except Exception:
        pass

    # ── 导入后：按 TRANSFORM3D 基础变换摆放各 body empty（单向可视化，不影响导出）──
    try:
        from . import transform_sync
        transform_sync.sync_all_transform3d(root_col)
    except Exception:
        pass

    # ── 12. Color Editor 模式收尾（见函数 docstring；失败安全，不影响数据完整性）──
    if color_editor_mode:
        _apply_color_editor_view(root_col, ctx)

    return root_col


def _find_layer_collection(layer_coll: bpy.types.LayerCollection, target: bpy.types.Collection):
    """在 layer_coll 为根的 LayerCollection 树里找 .collection is target 的节点。"""
    if layer_coll.collection is target:
        return layer_coll
    for child in layer_coll.children:
        found = _find_layer_collection(child, target)
        if found is not None:
            return found
    return None


def _apply_color_editor_view(root_col: bpy.types.Collection, ctx) -> None:
    """
    Color Editor 模式收尾（仅在 color_editor_mode=True 时调用）：

    1. 含颜色字段的 entry/attribute 额外 link 进 root_col 本身（多重归属，不从
       原叶子集合 unlink）。`collect_top_level(root_col, type_tag)` 从叶子集合
       起 walk，从不扫 root_col.objects 直接子级，故本步骤对导出路径零影响，
       byte-perfect 天然保住（同 opaque 兜底一个道理：没碰的东西必然没变）。
    2. 四个正常叶子集合（Entry/Action/Extern/Subselect，含 Entry 下嵌套的
       Direct/Not Direct Trigger）从当前场景全部 View Layer 排除——只影响
       Outliner 显示（LayerCollection.exclude 是纯 View Layer 状态，不是集合
       归属，find_root_collection/collect_top_level/export 都不看这个），
       不删/不动任何数据。

    entry→attribute 子对象查找避免 `obj.children`（全场景反查扫描，同
    onchange-full-scene-scan-perf-bug 教训）：改一次性用 `col_entry.all_objects`
    建 parent→children map。

    失败安全：任何异常都不该让导入失败——本步骤只是 UI 精简，出错最坏情况是
    退化成看起来像普通编辑器视图，不影响数据完整性。
    """
    from . import color_fields as _cf

    try:
        col_entry = _rc.get_leaf_collection(root_col, "EFX_ENTRY")
        if col_entry is not None:
            attrs_by_entry = {}
            for obj in col_entry.all_objects:
                if obj.get("~TYPE") == "EFX_ATTRIBUTE" and obj.parent is not None:
                    attrs_by_entry.setdefault(obj.parent.name, []).append(obj)

            for entry_obj in _rc.collect_top_level(root_col, "EFX_ENTRY"):
                entry_has_color = False
                for attr_obj in attrs_by_entry.get(entry_obj.name, []):
                    try:
                        type_hash = int(str(attr_obj.get("type_hash", "0")))
                        field_items = attr_obj.efx_block.field_items
                    except Exception:
                        continue
                    if _cf.attribute_has_color(type_hash, field_items):
                        entry_has_color = True
                        if attr_obj.name not in root_col.objects:
                            root_col.objects.link(attr_obj)
                if entry_has_color and entry_obj.name not in root_col.objects:
                    root_col.objects.link(entry_obj)
    except Exception:
        pass

    try:
        leaf_types = ("EFX_ENTRY", "EFX_ACTION", "EFX_EXTERN", "EFX_SUBSELECT")
        leaf_cols = [c for c in (_rc.get_leaf_collection(root_col, t) for t in leaf_types) if c is not None]
        scene = getattr(ctx, "scene", None)
        if scene is not None:
            for vl in scene.view_layers:
                for col in leaf_cols:
                    lc = _find_layer_collection(vl.layer_collection, col)
                    if lc is not None:
                        lc.exclude = True
    except Exception:
        pass


def _build_attr_attribute_children(
    attr_blocks,
    parent_obj: bpy.types.Object,
    collection: bpy.types.Collection,
    parent_label: str = "",
    extern_objs_by_index: dict = None,
    count_extern: int = 0,
) -> None:
    """
    为 body 对象建 AttrBlock 子 Empty 列表（EFX_ATTRIBUTE）。
    子块保持原始顺序（存 efx_index）。
    必须把子对象也 link 到同一集合里（Blender 要求对象必须在集合里才可见）。

    L1.1a 新增：
      - 调用 fields.init_attribute_props 初始化 obj.efx_block PropertyGroup
        （含字段展开或 opaque 回退，加载完后 efx_dirty=False）
      - 继续保留自定义属性 data_bytes 用于不依赖 PropertyGroup 的场景

    L2 #1c 新增：
      - extern_objs_by_index / count_extern 传入 init_attribute_props，
        供 EXTERNREFERENCE 块的 extern 指针化使用。

    命名方案（显示用，不影响导出顺序）：
      [父body标签] NN 类型名
      NN = 块在该 body 内的序号（零填充 2 位，>99 则自动 3 位）
    """
    if extern_objs_by_index is None:
        extern_objs_by_index = {}

    for blk_idx, blk in enumerate(attr_blocks):
        type_name = _hash_display_name(blk.type_hash)
        display_type_name = _pretty_type_name(type_name)  # 大纲显示用，非内部标识
        # 序号前缀（同 body 命名规则）
        nn = str(blk_idx).zfill(2) if blk_idx < 100 else str(blk_idx)
        # 父标签前缀（方括号包裹，用于大纲分组识别）
        if parent_label:
            blk_name = f"[{parent_label}] {nn} {display_type_name}"
        else:
            blk_name = f"{nn} {display_type_name}"
        blk_obj  = _new_empty(blk_name, collection)
        blk_obj["~TYPE"]          = "EFX_ATTRIBUTE"
        blk_obj["efx_index"]      = blk_idx
        blk_obj["type_hash"]      = str(blk.type_hash)   # uint32：存十进制字符串防溢出
        blk_obj["data_bytes"]     = _b64enc(blk.data_bytes)
        blk_obj["efx_type_name"]  = type_name  # 原始大写，L2 #3a：内部标识/重排重建显示名用
        blk_obj.parent            = parent_obj

        # ── L1.1a + L2 #1c：初始化 efx_block PropertyGroup ──────────────────
        # init_attribute_props 内部管理 _LOADING 守卫，填完后重置 efx_dirty=False。
        # L2 #1c：extra args extern_objs_by_index/count_extern 供 EXTERNREFERENCE 使用。
        try:
            _fields.init_attribute_props(
                blk_obj, blk,
                extern_objs_by_index=extern_objs_by_index,
                count_extern=count_extern,
            )
        except Exception:
            # 任何异常均安全回退：efx_block 保持 is_editable=False
            pass


# ─────────────────────────────────────────────────────────────────────────────
# export_efx_tree
# ─────────────────────────────────────────────────────────────────────────────

def export_efx_tree(root_object: bpy.types.Collection, recalc_timl_length: bool = False) -> bytes:
    """
    从 EFX_ROOT 对象树还原 .efx 文件字节。

    参数
    ----
    root_object : bpy.types.Collection
        由 import_efx_tree 创建的顶层文件集合（root_col，2026-07 起 ROOT
        不再是 Empty 对象；形参名沿用 root_object 只是历史命名，不改调用方签名）。
    recalc_timl_length : bool
        True 时导出把每条 TIML 动画的 animation_length 精确设为 末关键帧+1（逐轴 A0/A1）。
        理由：帧长 ≤ 实际结束帧会导致游戏内动画播不完，+1 刚好覆盖到末帧之后。

    返回
    ----
    bytes
        完整 .efx 文件字节（byte-perfect）。
    """
    global _EXPORT_RECALC_TIML_LEN
    r = root_object  # 简写
    _EXPORT_RECALC_TIML_LEN = bool(recalc_timl_length)  # _export_timl_bytes 读取（导出非重入）

    # ── 0. main 段不可解析的 opaque 回退文件：整文件 verbatim 透传 ───────────
    # 这类文件 main 段含我们无法定界的块，导入时整段存为 opaque blob。无法重建
    # 结构，直接重发原始字节（byte-perfect）。此文件在 Blender 内为只读透传。
    _opaque_file = r.get("main_opaque_file_b64")
    if _opaque_file:
        return _b64dec(str(_opaque_file))

    # ── 1. 重建 EFXHeader ───────────────────────────────────────────────────
    # 所有 uint32 字段存的是十进制字符串，需先 str() 再 int()
    hdr = EFXHeader(
        signature       = bytes.fromhex(str(r["hdr_signature"])),
        version         = int(str(r["hdr_version"])),
        constant        = tuple(int(x) for x in str(r["hdr_constant"]).split(",")),
        efxr            = bytes.fromhex(str(r["hdr_efxr"])),
        unkn0           = int(str(r["hdr_unkn0"])),
        unkn1           = int(str(r["hdr_unkn1"])),
        count_body      = int(str(r["hdr_count_body"])),
        label_size      = int(str(r["hdr_label_size"])),
        count_play      = int(str(r["hdr_count_play"])),
        count_extern    = int(str(r["hdr_count_extern"])),
        count_subselect = int(str(r["hdr_count_subselect"])),
        subselect_size  = int(str(r["hdr_subselect_size"])),
        count_eof       = int(str(r["hdr_count_eof"])),
        double_buffer   = int(str(r["hdr_double_buffer"])),
    )

    # ── 2. label_bytes 占位（§4a 后重建）
    label_bytes = None  # 占位，§4a 之后重建
    label_size  = None  # 占位

    # ── 3. 还原 eof_ints（hybrid：export_eof_per_entry 从 Direct Trigger 嵌套集合
    #    归属还原 / opaque 字符串原样）────────────────────────────────────────
    # 注意：eof_ints 依赖 entry_index_map，该 map 在 §4 收集 body_objs 后才能构建。
    # 故此处先占位，§4b 补填；最终在 §6 拼接字节前使用。
    eof_ints = None  # 占位，§4b 补填

    # ── 4. 收集 Main body 对象（按 efx_index 排序）────────────────────────
    #   子对象通过集合归属（root_col 下 _2 Entry 叶子集合）+ ~TYPE == EFX_ENTRY 来找
    body_objs = _rc.collect_top_level(r, "EFX_ENTRY")

    # 一次性建 {entry: [attribute 子对象]} 映射，本函数下面多处按 entry 逐个取
    # attribute 子对象都查这张表（O(1)），不再各自现场扫全场景 bpy.data.objects——
    # 那样是 O(entry 数 × 场景对象数)，随场景里已加载的其它 EFX 文件数量增长明显变慢。
    _attr_children_map = _build_attr_children_map(_rc.get_leaf_collection(r, "EFX_ENTRY"))

    # ── 4a0. 剔除零块的 standard/extended body（原生 Delete Hierarchy 的残留空壳）──
    # 2026-07-01 实测坐实：Blender 原生「Delete Hierarchy」在某些集合结构下只删掉
    # body 的子对象（EFX_ATTRIBUTE/EFX_TIML），body 这个 Empty 本身却原样留在
    # bpy.data.objects 里（默认 Outliner「View Layer」视图不可见，Purge Unused Data
    # 也清不掉——它仍链接在集合里，不算孤儿），把它当"真删掉了"完全是错觉。这类零块
    # body 在真实游戏内容里没有意义（不做任何事），直接在导出时当它不存在：不写进
    # 文件。root 类型 body 本来就没有块，不受影响。
    # 引用它的 Play/PtLife/PtCollision/Subselect/EOF 一律走既有的悬空指针安全路径
    # （保留原字节/跳过，见各 export_* 与 validate.py 的"悬空不阻断导出"设计），
    # 不需要额外清理——跟"真的用插件删除按钮删掉这个 body"效果一致。
    #
    # ⚠ 2026-07 修正：判据从"零块"收紧为"零块 **且 导入时 attr_count>0**"。
    # 成因：原判据误伤 **合法的空 entry**——如 evc 事件特效 evc1005_008 的 entry[13]
    # 本就 attr_count==0（格式层 byte-perfect 已证其合法），却被当成删除残留丢掉，
    # 导致 count_body 少 1、后续 eof/引用索引整体错位。区分依据：
    #   - 合法空 entry：导入时 attr_count==0（文件本就无块）→ 保留。
    #   - 原生 Delete Hierarchy 残留：导入时 attr_count>0（原本有块），原生删子对象
    #     不更新此快照，故 children==0 而 attr_count>0 → 剔除。
    #   - attr_count 为负（evc 哨兵）视同非正 → 保留。
    def _is_native_delete_leftover(o):
        if str(o.get("entry_kind", "")) not in ("standard", "extended"):
            return False
        if _collect_children_by_type(o, "EFX_ATTRIBUTE", _attr_children_map):
            return False  # 还有块 → 不是空壳
        try:
            return int(str(o.get("attr_count", "0"))) > 0
        except (ValueError, TypeError):
            return False
    body_objs = [o for o in body_objs if not _is_native_delete_leftover(o)]

    # ── 4a. 提前构建 extern_index_map（L2 #1c）─────────────────────────────────
    # 需要在遍历 main_bodies 时传给 _resolve_attribute_data_bytes，
    # 所以在 §4 主循环开始前先收集并排序 EFX_EXTERN 对象。
    extern_objs = _rc.collect_top_level(r, "EFX_EXTERN")
    # {EFX_EXTERN Object → extern 段局部 0-based index}
    extern_index_map = {obj: idx for idx, obj in enumerate(extern_objs)}

    # ── 4b. 构建 entry_index_map 和 play_index_map（L2 #1d）─────────────────────
    # body_objs 已排序，enumerate 序号 == Main 局部 index（与导出顺序一致）
    body_index_map_export = {obj: idx for idx, obj in enumerate(body_objs)}

    # play_objs 在 §5 收集；此处先收集排序以便 _resolve_attribute_data_bytes 使用
    play_objs_prescan = _rc.collect_top_level(r, "EFX_ACTION")
    play_index_map_export = {obj: idx for idx, obj in enumerate(play_objs_prescan)}

    # subselect_objs 在 §5b 才用，这里提前收集只为下面的结构变化检测；§5b 直接复用。
    subselect_objs_prescan = _rc.collect_top_level(r, "EFX_SUBSELECT")

    # ── 4d. 结构变化自动兜底（原生 Blender 删除的安全网）──────────────────────
    # labels_dirty/subselect_dirty 只由本插件自己的删除/增删算子显式置位（eof 不需要，
    # 归属靠集合成员关系，entry 被删自动从其所在集合消失）；用户若改用 Blender 原生
    # 删除（选中对象按 X，或 Delete Hierarchy）删掉 body/play/extern/subselect，这几个
    # 自定义属性根本不会被触碰，但 §6 的 count_* 早已无条件按实际对象数重算——如果
    # label_bytes/subselect_size 仍走 verbatim 分支，就会和已经变化的 count_* 对不上，
    # 产出结构错误的文件。
    # hdr_count_body/play/extern/subselect 只在导入时写一次、之后再不更新，天然
    # 就是"最后一次已知结构"的快照，不需要额外状态：跟当前实际对象数一比对，
    # 不管是走自定义算子还是原生删除/增加触发的变化，都能查出来。
    _entry_count_changed = len(body_objs) != int(str(r.get("hdr_count_body", len(body_objs))))
    _play_count_changed = len(play_objs_prescan) != int(str(r.get("hdr_count_play", len(play_objs_prescan))))
    _extern_count_changed = len(extern_objs) != int(str(r.get("hdr_count_extern", len(extern_objs))))
    _subselect_count_changed = len(subselect_objs_prescan) != int(str(r.get("hdr_count_subselect", len(subselect_objs_prescan))))
    _labels_need_rebuild = _entry_count_changed or _play_count_changed or _extern_count_changed
    # subselect 表内部会跳过 body_ptr 悬空的成员（见 subselect.py），所以 body 数变化
    # 也可能让某张表的字节变短，即使没有直接增删 subselect 对象本身，同样要重算。
    _subselect_need_rebuild = _subselect_count_changed or _entry_count_changed

    # ── 2b. 决定 label_bytes（play/extern/body 对象均已收集）──────────────────
    # 混合策略（契合本仓库"未编辑走 verbatim"哲学）：
    #   labels_dirty==0（未改名/未增删）→ emit 原始 blob，保证 byte-perfect。
    #   labels_dirty==1（改名/增删/结构变）→ 从对象重建 = join(有标签条目) + tail。
    # 重建已证明对未编辑文件 == verbatim（78/78），故增删走重建路径安全。
    if int(r.get("labels_dirty", 0)) or _labels_need_rebuild:
        # 顺序：[Play | Extern | Main]，按全局位置取 efx_has_label==1 的条目标签。
        # has_label 是前缀性质（增删保持前缀），所以拼出来仍是合法标签前缀。
        _ordered = list(play_objs_prescan) + list(extern_objs) + list(body_objs)
        _labels  = [str(o.get("efx_raw_label", ""))
                    for o in _ordered if int(o.get("efx_has_label", 1))]
        _tail    = _b64dec(str(r.get("label_tail", "")))
        label_bytes = b''.join(s.encode('utf-8') + b'\x00' for s in _labels) + _tail
    else:
        # verbatim：原始整段 blob（含 tail，byte-perfect）
        label_bytes = _b64dec(str(r["label_bytes"]))
    label_size = len(label_bytes)

    # ── 4c. 还原 eof_ints（body 归属的 Direct Trigger 嵌套集合 → 局部 index）───────
    # per_entry：collect Direct Trigger 子集合成员，升序重建（悬空/越界从原理上不存在，
    # entry 被删即从其所在集合消失，无需额外 sanitize 逻辑）。opaque：字符串原样。
    try:
        eof_ints = _entry_action_ref.export_eof_per_entry(r, body_index_map_export)
    except Exception:
        # 回退：旧字符串路径
        _eof_str = str(r["eof_ints"]).strip()
        eof_ints = [int(x) for x in _eof_str.split(",") if x] if _eof_str else []

    # 0-body EFX 不应有任何顶层 body 引用：强制清空 eof，否则残留的越界原始值
    # （如删光 body 后留下的 [16]）会让游戏访问不存在的 body → 闪退。
    # 实测两个正常 0-body 游戏文件 eof 均为空；多 body 文件不受影响（byte-perfect 保持）。
    if len(body_objs) == 0:
        eof_ints = []
    elif len(eof_ints) > len(body_objs):
        # count_eof > count_body → 游戏闪退。
        # 成因：被删 body 的 eof 槽是哨兵原始值（非 body 指针），无法随 body 删除自动消失。
        # 例：fine 的 body[3] eof 值=16（越界哨兵），删 body[3] 后哨兵残留 → ceof=4>cb=3。
        # 修复：截断到 n_entry，丢弃尾部多余条目（哨兵总在末尾；已有指针的 body 删除
        # 会走悬空跳过路径，不产生此问题）。78/78 不受影响（未编辑文件 len==count_body）。
        eof_ints = eof_ints[:len(body_objs)]

    main_bodies = []
    for entry_obj in body_objs:
        kind = str(entry_obj["entry_kind"])

        if kind == "root":
            if int(entry_obj.get("root_structured", 0)) == 1:
                n = int(entry_obj.get("root_ub_count", 0))
                entries = []
                for j in range(n):
                    ints = tuple(int(x) for x in entry_obj["root_ub%d_ints" % j])
                    floats = tuple(float(x) for x in entry_obj["root_ub%d_floats" % j])
                    entries.append(RootUnitBoundary(ints=ints, floats=floats))
                main_bodies.append(RootBody(
                    const0=int(str(entry_obj["root_const0"])),
                    const1=int(str(entry_obj["root_const1"])),
                    entries=entries,
                ))
            else:
                raw = _b64dec(str(entry_obj["raw"]))
                main_bodies.append(RootBody(raw=raw))

        elif kind == "extended":
            # 收集 AttrBlock 子对象
            blk_objs = _collect_children_by_type(entry_obj, "EFX_ATTRIBUTE", _attr_children_map)
            blk_objs.sort(key=lambda o: int(o["efx_index"]))
            attr_blocks = [
                AttrBlock(
                    type_hash  = int(str(blk["type_hash"])),
                    data_bytes = _resolve_attribute_data_bytes(
                        blk, extern_index_map,
                        body_index_map_export, play_index_map_export,
                    ),
                )
                for blk in blk_objs
            ]
            _ext_timl = _export_timl_bytes(entry_obj)   # Phase 3：句柄有 fcurve → 同步回字节
            main_bodies.append(EntryDataExtended(
                body_type   = int(str(entry_obj["body_type"])),
                unkn0       = int(str(entry_obj["unkn0"])),
                null0       = int(str(entry_obj["null0"])),
                null1       = int(str(entry_obj["null1"])),
                unkn1       = int(str(entry_obj["unkn1"])),
                unkn2       = int(str(entry_obj["unkn2"])),
                attr_count  = len(attr_blocks),  # L2 #3b：从实际块数重算（增删块后正确）
                null2       = int(str(entry_obj["null2"])),
                timl_length = len(_ext_timl),  # 从实际 timl 字节重算（支持编辑后变长；未编辑 == 原值）
                timl_bytes  = _ext_timl,
                attr_blocks = attr_blocks,
            ))

        elif kind == "standard":
            blk_objs = _collect_children_by_type(entry_obj, "EFX_ATTRIBUTE", _attr_children_map)
            blk_objs.sort(key=lambda o: int(o["efx_index"]))
            attr_blocks = [
                AttrBlock(
                    type_hash  = int(str(blk["type_hash"])),
                    data_bytes = _resolve_attribute_data_bytes(
                        blk, extern_index_map,
                        body_index_map_export, play_index_map_export,
                    ),
                )
                for blk in blk_objs
            ]
            _std_timl = _export_timl_bytes(entry_obj)   # Phase 3：句柄有 fcurve → 同步回字节
            main_bodies.append(EntryData(
                body_type   = int(str(entry_obj["body_type"])),
                unkn0       = int(str(entry_obj["unkn0"])),
                attr_count  = len(attr_blocks),  # L2 #3b：从实际块数重算（增删块后正确）
                null        = int(str(entry_obj["null"])),
                timl_length = len(_std_timl),  # 从实际 timl 字节重算（支持编辑后变长；未编辑 == 原值）
                timl_bytes  = _std_timl,
                attr_blocks = attr_blocks,
            ))

        else:
            # unknown：raw 存的是完整 serialize()，直接当 RootBody 原样拼接
            raw = _b64dec(str(entry_obj["raw"]))
            main_bodies.append(RootBody(raw=raw))

    # ── 5. Play：L2 #1b 结构化导出（PLAYEMITTER targets 经 entry_index_map 重算）──
    #   body_objs 已在 §4 按 efx_index 排序；entry_index_map 在 §4b 构建。
    #   此处提前构建，以便 Play 导出也能用（Play 段在 Subselect 之前）。
    #   extern_objs 已在 §4a 收集并排序；extern_index_map 已在 §4a 构建。
    play_objs = play_objs_prescan  # §4b 已收集并排序，复用

    # entry_index_map：{EFX_ENTRY Object → main_local_index}（§4b 已构建）
    _action_entry_index_map = body_index_map_export

    play_raw = b""
    for po in play_objs:
        try:
            pd = _action_emitter.export_action_data(po, _action_entry_index_map)
            play_raw += pd.serialize()
        except Exception:
            # 回退：用 raw_b64 原样拼接（byte-perfect 保底）
            play_raw += _b64dec(str(po["raw_b64"]))

    try:
        from . import extern_props as _ep
        def _extern_bytes(o):
            try:
                return _ep.export_extern_data(o)
            except Exception:
                return _b64dec(str(o["raw_b64"]))
    except Exception:
        def _extern_bytes(o):
            return _b64dec(str(o["raw_b64"]))
    extern_raw = b"".join(_extern_bytes(o) for o in extern_objs)

    # ── 5b. Subselect：L2 #1a 结构化导出 ─────────────────────────────────────
    #   构建 Main 段局部索引映射，供 export_subselect_table 解析 body_ptr → 整数 index。
    #   §4d 已收集排序过（结构变化检测用），直接复用。
    subselect_objs = subselect_objs_prescan

    # 构建 {EFX_ENTRY object → main_local_index} 映射
    # body_objs 已在 §4 按 efx_index 排序并 enumerate → 局部 index == enumerate 序号
    entry_index_map = {obj: idx for idx, obj in enumerate(body_objs)}

    subselect_raw = b""
    for ss_obj in subselect_objs:
        try:
            tbl = _subselect.export_subselect_table(ss_obj, entry_index_map)
            subselect_raw += tbl.serialize()
        except Exception:
            # 回退：用 raw_b64 原样拼接（byte-perfect 保底）
            subselect_raw += _b64dec(str(ss_obj["raw_b64"]))

    # ── 6. header 计数/size 重算（L2 #3b：增删后必须重算）────────────────────
    # 计数（count_*）对全 78 样本恒 == 实际条目数，安全重算（删除后即为新计数）。
    hdr.count_body      = len(body_objs)
    hdr.count_play      = len(play_objs)
    hdr.count_extern    = len(extern_objs)
    hdr.count_subselect = len(subselect_objs)
    hdr.count_eof       = len(eof_ints)
    hdr.label_size      = label_size           # = len(label_bytes)，verbatim 或重建

    # subselect_size 是不透明值：实测 4 个文件原始值 ≠ 实际段字节长（164 vs 188 等，
    # 差值不固定，与 double_buffer 同类）。故默认 verbatim 保留原值，仅 subselect
    # 段被编辑（删/增条目）时才重算。double_buffer 公式未知，恒原样保留。
    if int(r.get("subselect_dirty", 0)) or _subselect_need_rebuild:
        hdr.subselect_size = len(subselect_raw)
    # else：hdr.subselect_size 保持 §1 从 hdr_subselect_size 读入的原值

    # ── 手动拼接最终字节（顺序：header/label/play/extern/main/subselect/eof）
    out = hdr.serialize()
    out += label_bytes
    out += play_raw
    out += extern_raw
    for body in main_bodies:
        out += body.serialize()
    out += subselect_raw
    for v in eof_ints:
        out += struct.pack("<I", v)
    out += _b64dec(str(r.get("eof_tail", "")))   # eof 后不透明 footer（多数为空）

    return out


def _resolve_attribute_data_bytes(blk_obj: bpy.types.Object,
                              extern_index_map: dict = None,
                              entry_index_map: dict = None,
                              play_index_map: dict = None) -> bytes:
    """
    L1.1a + L2 #1c + L2 #1d：决定导出时 EFX_ATTRIBUTE 的 data_bytes 来源。

    2026-07 退休 block 级 efx_dirty 门控（结构权威下放收尾，见 memory
    attribute-dirty-gate-retired）：
      1. is_editable=True → 永远走 fields.get_attribute_data_bytes（不再看 efx_dirty）。
         安全性由 rebuild_data_bytes 的**逐字段** orig_b64 兜底保证——未编辑字段
         （item.edited=False）本就重建为原字节，block 级"整体走 raw 还是走重建"
         这道外层开关在数学上是冗余的短路优化。语料实测 650 官方文件 83045 个
         可编辑属性强制重建 0 处不一致，与逐字段兜底的架构保证一致（非偶然）。
         对 EXTERNREFERENCE/PTLIFE/PTCOLLISION + pointerized=True 额外覆写字段。
      2. is_editable=False（opaque）→ 自定义属性 data_bytes（base64 原始，唯一回退；
         对 EXTERNREFERENCE/PTLIFE/PTCOLLISION + pointerized=True 同样覆写）。

    efx_dirty 本身保留（仍是面板"● 已修改"徽章的唯一数据源），只是不再影响
    本函数的路径选择——与 efx_format.timl.Timl.dirty 的转型（"有模型就强制重建"）
    同一哲学。

    extern_index_map : dict[bpy.types.Object, int] | None — L2 #1c
    entry_index_map   : dict[bpy.types.Object, int] | None — L2 #1d PTLIFE
    play_index_map   : dict[bpy.types.Object, int] | None — L2 #1d PTCOLLISION
    """
    try:
        bp = blk_obj.efx_block
        if bp.is_editable:
            return _fields.get_attribute_data_bytes(
                blk_obj,
                extern_index_map=extern_index_map,
                entry_index_map=entry_index_map,
                play_index_map=play_index_map,
            )
    except Exception:
        pass
    # 回退：opaque（is_editable=False）或编码异常 → 原始自定义属性，再走 L2 #1c / #1d overlay
    data = _b64dec(str(blk_obj["data_bytes"]))
    if extern_index_map is not None:
        data = _fields._apply_extern_ref_overlay(blk_obj, data, extern_index_map)
    if entry_index_map is not None or play_index_map is not None:
        data = _fields._apply_entry_action_ref_overlays(
            blk_obj, data, entry_index_map, play_index_map,
        )
    return data


def _build_attr_children_map(entry_col) -> dict:
    """一次性递归扫 entry_col（含嵌套的 Direct Trigger/Not Direct Trigger 子集合），
    按 .parent 分组 EFX_ATTRIBUTE 子对象，返回 {parent_entry: [attrs]}。

    供导出主循环替代"每个 entry 各扫一遍全场景 bpy.data.objects"的写法——后者是
    O(entry 数 × 场景对象数)，场景里已加载的其它 EFX 文件越多，单次导出越慢
    （跟 import 端 §7b/§7c 是同一类 bug，一并修）。"""
    out = {}
    if entry_col is None:
        return out

    def _walk(c):
        for o in c.objects:
            if o.get("~TYPE") == "EFX_ATTRIBUTE" and o.parent is not None:
                out.setdefault(o.parent, []).append(o)
        for child in c.children:
            _walk(child)

    _walk(entry_col)
    return out


def _collect_children_by_type(
    parent_obj: bpy.types.Object,
    type_tag: str,
    children_map: dict = None,
) -> list:
    """
    收集 parent_obj 的直接子对象中 ~TYPE == type_tag 的所有对象。

    children_map（可选）：_build_attr_children_map() 的结果，仅当 type_tag ==
    "EFX_ATTRIBUTE" 时可用；传了就直接查表（O(1)），不传则现场全量扫
    bpy.data.objects（注意：批量场景——如导出主循环里对多个 entry 逐个调用——
    不传会退化成 O(entry 数 × 场景对象数)，务必传）。
    """
    if children_map is not None and type_tag == "EFX_ATTRIBUTE":
        return list(children_map.get(parent_obj, []))
    results = []
    for obj in bpy.data.objects:
        if obj.parent == parent_obj and obj.get("~TYPE") == type_tag:
            results.append(obj)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# roundtrip_corpus  —  测试用，供主会话通过 MCP 调用
# ─────────────────────────────────────────────────────────────────────────────

def roundtrip_corpus(samples_dir: str) -> dict:
    """
    对 samples_dir 下全部 .efx 文件执行往返测试：
      import_efx_tree → export_efx_tree → 断言 == 原文件字节。

    每个文件处理完后删除创建的集合和对象，避免场景爆炸。

    参数
    ----
    samples_dir : str
        包含 .efx 文件的目录路径。

    返回
    ----
    dict
        {"total": N, "passed": N, "failed": [(name, reason), ...]}
    """
    import os

    efx_files = [
        os.path.join(samples_dir, fn)
        for fn in os.listdir(samples_dir)
        if fn.lower().endswith(".efx")
    ]
    efx_files.sort()

    total  = len(efx_files)
    passed = 0
    failed = []

    for filepath in efx_files:
        name = os.path.basename(filepath)
        try:
            # ── 读原始字节 ────────────────────────────────────────────────
            with open(filepath, "rb") as f:
                original = f.read()

            # ── 导入 → 建立对象树 ─────────────────────────────────────────
            root_obj = import_efx_tree(filepath)

            # ── 导出 → 还原字节 ───────────────────────────────────────────
            result = export_efx_tree(root_obj)

            # ── 断言 byte-perfect ─────────────────────────────────────────
            if result == original:
                passed += 1
            else:
                # 找出第一个不同字节的位置
                diff_pos = _first_diff(original, result)
                failed.append((
                    name,
                    f"字节不一致：原始 {len(original)}B，导出 {len(result)}B，"
                    f"首个差异在偏移 {diff_pos}",
                ))

        except Exception as exc:
            import traceback
            failed.append((name, f"异常：{exc}\n{traceback.format_exc()}"))

        finally:
            # ── 清理：删除本次创建的集合和对象 ──────────────────────────
            _cleanup_efx_tree(name)

    return {"total": total, "passed": passed, "failed": failed}


def _first_diff(a: bytes, b: bytes) -> int:
    """返回两个 bytes 对象首个不同位置；若长度相同且内容相同返回 -1。"""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return len(a) if len(a) != len(b) else -1


def _cleanup_efx_tree(file_stem_or_name: str) -> None:
    """
    清理由 import_efx_tree 创建的所有集合和对象。
    根据顶层集合名（文件 stem）定位，递归删除其下全部对象和集合。
    """
    # 顶层集合名 = 完整文件名（含 .efx）；兼容传入 stem 的情况
    root_col = (bpy.data.collections.get(file_stem_or_name)
                or bpy.data.collections.get(os.path.splitext(file_stem_or_name)[0]))
    if root_col is None:
        return  # 不存在则跳过

    # 收集集合内全部对象（递归子集合）
    all_objects = _collect_all_objects_in_collection(root_col)

    # 先解除父子关系（防止删除时报错）
    for obj in all_objects:
        obj.parent = None

    # 删除对象
    for obj in all_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

    # 递归删除子集合，再删顶层集合
    _remove_collection_recursive(root_col)


def _collect_all_objects_in_collection(col: bpy.types.Collection) -> list:
    """递归收集集合及其子集合内的全部对象。"""
    objects = list(col.objects)
    for child_col in col.children:
        objects.extend(_collect_all_objects_in_collection(child_col))
    return objects


def _remove_collection_recursive(col: bpy.types.Collection) -> None:
    """递归删除集合及其子集合（先删子再删父）。"""
    for child in list(col.children):
        _remove_collection_recursive(child)
    bpy.data.collections.remove(col)
