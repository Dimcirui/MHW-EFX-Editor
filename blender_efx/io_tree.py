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
  <文件名集合> [COLOR_06]
  └── EFX_ROOT  (~TYPE='EFX_ROOT')          # 顶层 Empty，存 header 全字段
      ├── Main   子集合
      │   └── EFX_BODY  (~TYPE='EFX_BODY')  # 每个 Main body
      │       └── <hash_name>  (~TYPE='EFX_BLOCK')  # 每个 AttrBlock
      ├── Play   子集合
      │   └── EFX_PLAY  (~TYPE='EFX_PLAY')  # L1.0：b64 原始字节
      ├── Extern 子集合
      │   └── EFX_EXTERN (~TYPE='EFX_EXTERN')
      └── Subselect 子集合
          └── EFX_SUBSELECT (~TYPE='EFX_SUBSELECT')
"""

import bpy
import base64
import os
import struct

from ..efx_format.efxfile import (
    EFXFile,
    EFXHeader,
    PlayData,
    PlayEntry,
    ExternAttribute,
    ExternDataItem,
    AttrBlock,
    MainDataBody,
    MainDataBodyExtended,
    RootBody,
    RootUnitBoundary,
    RootOpaqueEntry,
    SubselectTable,
)
from ..efx_format.hashes import HASH_TO_NAME

# 导入字段模型模块（延迟导入，避免注册顺序问题）
# init_block_props 和 get_block_data_bytes 在实际调用时才被解析
from . import fields as _fields
from . import subselect as _subselect
from . import play_emitter as _play_emitter
from . import extern_ref as _extern_ref
from . import body_play_ref as _body_play_ref


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
# 故 byte-perfect 不受影响；EFX_TIML 既非 EFX_BODY 也非 EFX_BLOCK，被导出/重排/删除/校验
# 的类型过滤天然忽略）。所有面板/算子经 resolve_timl_body() 把句柄解析回父 body 后操作。

def find_timl_handle(body_obj: bpy.types.Object):
    """返回 body 下的 EFX_TIML 句柄对象，无则 None。"""
    if body_obj is None:
        return None
    for c in bpy.data.objects:
        if c.parent == body_obj and c.get("~TYPE") == "EFX_TIML":
            return c
    return None


def make_timl_handle(body_obj: bpy.types.Object, collection: bpy.types.Collection = None):
    """为 body 创建（或复用）EFX_TIML 句柄子对象。"""
    existing = find_timl_handle(body_obj)
    if existing is not None:
        return existing
    if collection is None:
        cols = body_obj.users_collection
        collection = cols[0] if cols else bpy.context.scene.collection
    label = str(body_obj.get("efx_raw_label", "")) or body_obj.name
    h = bpy.data.objects.new("%s TIML" % label, None)
    h.empty_display_type = 'SPHERE'
    h.empty_display_size = 0.12
    collection.objects.link(h)
    h["~TYPE"] = "EFX_TIML"
    h.parent = body_obj
    return h


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

def import_efx_tree(filepath: str, context=None) -> bpy.types.Object:
    """
    解析 .efx 文件，在场景里建立对象树。

    参数
    ----
    filepath : str
        .efx 文件的绝对路径。
    context : bpy.types.Context, optional
        Blender 上下文。若为 None，用 bpy.context。

    返回
    ----
    bpy.types.Object
        顶层 EFX_ROOT Empty 对象。
    """
    ctx = context if context is not None else bpy.context

    # ── 1. 解析文件 ─────────────────────────────────────────────────────────
    with open(filepath, "rb") as f:
        raw_data = f.read()
    efx = EFXFile.parse(raw_data)
    hdr = efx.header

    file_stem = os.path.splitext(os.path.basename(filepath))[0]
    file_name = os.path.basename(filepath)   # 含 .efx 后缀，用作顶层集合名（仿 mrl3）

    # ── 2. 建顶层集合（紫色 COLOR_06）──────────────────────────────────────
    scene_col = ctx.scene.collection
    root_col = _new_collection(file_name, scene_col)
    root_col.color_tag = "COLOR_06"

    # ── 3. 建 EFX_ROOT Empty，存 header 全部字段 ──────────────────────────
    root_obj = _new_empty(file_stem + "_ROOT", root_col)
    root_obj["~TYPE"] = "EFX_ROOT"

    # header 字段：signature/efxr 存 hex；
    # 所有 uint32 字段存十进制字符串（避免 Blender C int 32 位溢出）；
    # constant（5 × uint32）存逗号分隔十进制字符串。
    root_obj["hdr_signature"]       = hdr.signature.hex()          # "45465800"
    root_obj["hdr_version"]         = str(hdr.version)
    root_obj["hdr_constant"]        = ",".join(str(x) for x in hdr.constant)
    root_obj["hdr_efxr"]            = hdr.efxr.hex()               # "65667872"
    root_obj["hdr_unkn0"]           = str(hdr.unkn0)
    root_obj["hdr_unkn1"]           = str(hdr.unkn1)
    root_obj["hdr_count_body"]      = str(hdr.count_body)
    root_obj["hdr_label_size"]      = str(hdr.label_size)
    root_obj["hdr_count_play"]      = str(hdr.count_play)
    root_obj["hdr_count_extern"]    = str(hdr.count_extern)
    root_obj["hdr_count_subselect"] = str(hdr.count_subselect)
    root_obj["hdr_subselect_size"]  = str(hdr.subselect_size)
    root_obj["hdr_count_eof"]       = str(hdr.count_eof)
    root_obj["hdr_double_buffer"]   = str(hdr.double_buffer)

    # label_bytes：整段 base64（label 表是 opaque blob，导出默认 verbatim 走它）
    root_obj["label_bytes"]         = _b64enc(efx.label_bytes)
    # 干净切分标签 + tail（重建路径用）：标签位置性映射到 [Play|Extern|Main] 前 k 个条目，
    # tail 是不透明尾字节（含非零字节，须 verbatim 保留）。详见 split_labels_tail。
    _clean_labels, _label_tail = split_labels_tail(
        efx.label_bytes, hdr.count_play + hdr.count_extern + hdr.count_body)
    root_obj["label_tail"]          = _b64enc(_label_tail)
    # labels_dirty：0=未编辑标签/结构 → 导出 emit verbatim blob；1=改名/增删 → 重建。
    root_obj["labels_dirty"]        = 0
    _n_labels                       = len(_clean_labels)  # 全局有标签条目数 k
    # eof_ints：每个元素是 uint32，存逗号分隔十进制字符串；空列表存 ""
    root_obj["eof_ints"]            = ",".join(str(x) for x in efx.eof_ints)
    # eof 后不透明 footer（部分游戏文件有，如 jichu1.efx 末尾 4 字节）；多数为空
    root_obj["eof_tail"]            = _b64enc(efx.eof_tail)

    # main 段不可解析的 opaque 回退文件：整段（main 起点→EOF）无法逐块解析，
    # 存整文件原始字节，导出时 verbatim 透传（保证 byte-perfect，但此文件只读）。
    if getattr(efx, "main_opaque", False):
        root_obj["main_opaque_file_b64"] = _b64enc(raw_data)

    # ── 4. 建 4 个子集合（含序号前缀，控制大纲排序）────────────────────────
    # 按 EFX 文件段顺序：0 Play、1 Extern、2 Main、3 Subselect
    col_main      = _new_collection(file_stem + "_2 Main",      root_col)
    col_play      = _new_collection(file_stem + "_0 Play",      root_col)
    col_extern    = _new_collection(file_stem + "_1 Extern",    root_col)
    col_subselect = _new_collection(file_stem + "_3 Subselect", root_col)

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
        body_obj = _new_empty(display_name, col_main)
        body_obj.empty_display_type = 'ARROWS'   # XYZ 三色轴，使特效体朝向直观可见
        body_obj["~TYPE"]         = "EFX_BODY"
        body_obj["efx_index"]     = body_idx  # 原始顺序，还原时用
        body_obj["efx_raw_label"] = raw_label  # L2 #3a：原始标签，重排重建显示名用
        body_obj["efx_has_label"] = int(has_label)  # 1=有原始标签, 0=合成标签
        body_obj.parent           = root_obj

        if isinstance(body, RootBody):
            body_obj["body_kind"] = "root"
            # 仅当全部子条目都是 UnitBoundary（实测 100% 官方样本如此）才结构化为
            # 可编辑字段；含 RenderTarget/LayoutBank 或整段不透明回退时存 base64 只读。
            structurable = (
                body.raw is None
                and all(isinstance(e, RootUnitBoundary) for e in body.entries)
            )
            if structurable:
                body_obj["root_structured"] = 1
                body_obj["root_const0"]     = str(body.const0)
                body_obj["root_const1"]     = str(body.const1)
                body_obj["root_ub_count"]   = len(body.entries)
                for j, e in enumerate(body.entries):
                    # 原生数组 IDProperty → panel 可直接 layout.prop 编辑
                    body_obj["root_ub%d_ints" % j]   = list(e.ints)
                    body_obj["root_ub%d_floats" % j] = list(e.floats)
            else:
                body_obj["root_structured"] = 0
                body_obj["raw"]             = _b64enc(body.serialize())

        elif isinstance(body, MainDataBodyExtended):
            # 扩展头（body_type < 256，36B 头）
            # 所有数值字段存十进制字符串（uint32 可 ≥ 2^31，Blender C int 会溢出）
            body_obj["body_kind"]    = "extended"
            body_obj["body_type"]    = str(body.body_type)
            body_obj["unkn0"]        = str(body.unkn0)
            body_obj["null0"]        = str(body.null0)
            body_obj["null1"]        = str(body.null1)
            body_obj["unkn1"]        = str(body.unkn1)
            body_obj["unkn2"]        = str(body.unkn2)
            body_obj["attr_count"]   = str(body.attr_count)
            body_obj["null2"]        = str(body.null2)
            body_obj["timl_length"]  = str(body.timl_length)
            body_obj["timl_bytes"]   = _b64enc(body.timl_bytes)
            # AttrBlock 子对象（extern 指针化在 §7b 二次 pass 完成）
            _build_attr_block_children(body.attr_blocks, body_obj, col_main, raw_label)
            if body.timl_length > 0:
                make_timl_handle(body_obj, col_main)   # TIML 统一入口句柄

        elif isinstance(body, MainDataBody):
            # 标准头（20B 头）
            # 所有数值字段存十进制字符串（uint32 可 ≥ 2^31，Blender C int 会溢出）
            body_obj["body_kind"]   = "standard"
            body_obj["body_type"]   = str(body.body_type)
            body_obj["unkn0"]       = str(body.unkn0)
            body_obj["attr_count"]  = str(body.attr_count)
            body_obj["null"]        = str(body.null)
            body_obj["timl_length"] = str(body.timl_length)
            body_obj["timl_bytes"]  = _b64enc(body.timl_bytes)
            # AttrBlock 子对象（extern 指针化在 §7b 二次 pass 完成）
            _build_attr_block_children(body.attr_blocks, body_obj, col_main, raw_label)
            if body.timl_length > 0:
                make_timl_handle(body_obj, col_main)   # TIML 统一入口句柄

        else:
            # 未知类型：保守存整段 serialize()
            body_obj["body_kind"] = "unknown"
            body_obj["raw"]       = _b64enc(body.serialize())

    # ── 6. Play：L2 #1b 结构化存储（替换纯 opaque）────────────────────────────
    #
    # main_bodies_by_index 在 §8（Subselect）构建前暂不可用，
    # 但 §5 Main 段已建完——提前在此处用相同逻辑构建一次，供 PlayEmitter 解析用。
    # （Subselect 的 main_bodies_by_index 在 §8 再次独立构建，逻辑不重叠）
    _play_bodies_by_index = {}
    for _bo in bpy.data.objects:
        if _bo.get("~TYPE") == "EFX_BODY" and _bo.parent == root_obj:
            try:
                _play_bodies_by_index[int(_bo["efx_index"])] = _bo
            except (KeyError, ValueError, TypeError):
                pass

    for i, pd in enumerate(efx.play):
        # Play 段全局位置 = i（[Play|Extern|Main] 最前）；前 _n_labels 个才有标签
        has_label = i < _n_labels
        play_label = _clean_labels[i] if has_label else f"play_{i}"
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj_name = f"{nn} {play_label}" if play_label else f"{nn} play_{i}"
        obj = _new_empty(obj_name, col_play)
        obj["~TYPE"]         = "EFX_PLAY"
        obj["efx_index"]     = i
        obj["efx_raw_label"] = play_label       # 标签重建用
        obj["efx_has_label"] = int(has_label)   # 1=有原始标签, 0=合成名（不进标签表）
        obj["raw_b64"]       = _b64enc(pd.serialize())
        obj.parent           = root_obj

        # ── L2 #1b：结构化初始化 ──────────────────────────────────────────────
        try:
            _play_emitter.init_play_props(obj, pd, _play_bodies_by_index)
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
        obj.parent           = root_obj
        try:
            from . import extern_props as _ep
            _ep.init_extern_props(obj, ea)
        except Exception:
            pass  # 任何异常安全跳过，raw_b64 保底

    # ── 7b. ExternReference 指针化二次 pass（L2 #1c）──────────────────────────
    #
    # §5 Main 段建立时 Extern 对象尚未存在，所以 init_block_props 当时拿不到
    # extern_objs_by_index。现在 §7 Extern 段已建完，补做二次 pass：
    # 遍历所有 EXTERNREFERENCE 块，调用 extern_ref.init_extern_ref_props 完成指针化。
    #
    # 构建 {efx_index → EFX_EXTERN 对象} 映射
    _extern_objs_by_index = {}
    for _eo in bpy.data.objects:
        if _eo.get("~TYPE") == "EFX_EXTERN" and _eo.parent == root_obj:
            try:
                _extern_objs_by_index[int(_eo["efx_index"])] = _eo
            except (KeyError, ValueError, TypeError):
                pass

    _count_extern = hdr.count_extern  # 文件头的 count_extern

    # 遍历所有 EFX_BLOCK，找 EXTERNREFERENCE 类型补做指针化
    try:
        from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
        for _blk_obj in bpy.data.objects:
            if _blk_obj.get("~TYPE") != "EFX_BLOCK":
                continue
            # 仅当父 body 的 parent == root_obj（属于本次导入的文件）
            if _blk_obj.parent is None or _blk_obj.parent.parent != root_obj:
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
    # 构建 {efx_index → EFX_BODY} 和 {efx_index → EFX_PLAY} 映射
    _main_bodies_by_index_1d = {}
    for _bo in bpy.data.objects:
        if _bo.get("~TYPE") == "EFX_BODY" and _bo.parent == root_obj:
            try:
                _main_bodies_by_index_1d[int(_bo["efx_index"])] = _bo
            except (KeyError, ValueError, TypeError):
                pass

    _play_objs_by_index_1d = {}
    for _po in bpy.data.objects:
        if _po.get("~TYPE") == "EFX_PLAY" and _po.parent == root_obj:
            try:
                _play_objs_by_index_1d[int(_po["efx_index"])] = _po
            except (KeyError, ValueError, TypeError):
                pass

    _count_body_1d = hdr.count_body
    _count_play_1d = hdr.count_play

    try:
        from ..efx_format.hashes import (
            PTLIFE as _PTLIFE_HASH,
            PTCOLLISION as _PTCOLLISION_HASH,
        )
        for _blk_obj in bpy.data.objects:
            if _blk_obj.get("~TYPE") != "EFX_BLOCK":
                continue
            # 仅属于本次导入的文件
            if _blk_obj.parent is None or _blk_obj.parent.parent != root_obj:
                continue
            try:
                bp = _blk_obj.efx_block
                _type_hash = int(bp.type_hash_str)
                _data_bytes_1d = base64.b64decode(str(bp.raw_b64))

                if _type_hash == _PTLIFE_HASH:
                    _body_play_ref.init_ptlife_ref_props(
                        _blk_obj,
                        _data_bytes_1d,
                        _play_objs_by_index_1d,
                        _count_play_1d,
                    )
                elif _type_hash == _PTCOLLISION_HASH:
                    _body_play_ref.init_ptcollision_ref_props(
                        _blk_obj,
                        _data_bytes_1d,
                        _play_objs_by_index_1d,
                        _count_play_1d,
                    )
            except Exception:
                # 任何异常安全跳过（props 保持默认 pointerized=False）
                pass
    except (ImportError, Exception):
        pass

    # ── 8. Subselect：L2 #1a 结构化存储（替换 opaque）──────────────────────────
    #
    # 构建 {efx_index → EFX_BODY 对象} 映射，供 init_subselect_props 解析 entries。
    # 此时 body_objs 列表已按 efx_index 排序（§5 中建立）；
    # 如未能在此处获取，则兜底用 bpy.data.objects 遍历。
    main_bodies_by_index = {}
    for body_obj in bpy.data.objects:
        if body_obj.get("~TYPE") == "EFX_BODY" and body_obj.parent == root_obj:
            try:
                idx = int(body_obj["efx_index"])
                main_bodies_by_index[idx] = body_obj
            except (KeyError, ValueError, TypeError):
                pass

    for i, tbl in enumerate(efx.subselect):
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj = _new_empty(f"{nn} subselect_{i}", col_subselect)
        obj["~TYPE"]     = "EFX_SUBSELECT"
        obj["efx_index"] = i
        # raw_b64：byte-perfect 回退（始终写入，与 L1.0 一致；结构化导出优先）
        obj["raw_b64"]   = _b64enc(tbl.serialize())
        obj.parent       = root_obj

        # ── L2 #1a：结构化初始化 ──────────────────────────────────────────────
        try:
            _subselect.init_subselect_props(obj, tbl, main_bodies_by_index)
        except Exception:
            # 任何异常均安全回退：raw_b64 保证 byte-perfect
            pass

    # ── 9. eof_ints：L2 #1d 指针化（替换逗号字符串存储）────────────────────────
    #
    # 此时 main_bodies_by_index 已在 §8 构建完毕，可直接复用。
    try:
        _body_play_ref.init_eof_list_props(
            root_obj,
            efx.eof_ints,
            main_bodies_by_index,
            hdr.count_body,
        )
    except Exception:
        # 任何异常安全跳过：root_obj["eof_ints"] 字符串仍在，导出回退路径保证 byte-perfect
        pass

    # ── 导入后：按 TRANSFORM3D 基础变换摆放各 body empty（单向可视化，不影响导出）──
    try:
        from . import transform_sync
        transform_sync.sync_all_transform3d(root_obj)
    except Exception:
        pass

    return root_obj


def _build_attr_block_children(
    attr_blocks,
    parent_obj: bpy.types.Object,
    collection: bpy.types.Collection,
    parent_label: str = "",
    extern_objs_by_index: dict = None,
    count_extern: int = 0,
) -> None:
    """
    为 body 对象建 AttrBlock 子 Empty 列表（EFX_BLOCK）。
    子块保持原始顺序（存 efx_index）。
    必须把子对象也 link 到同一集合里（Blender 要求对象必须在集合里才可见）。

    L1.1a 新增：
      - 调用 fields.init_block_props 初始化 obj.efx_block PropertyGroup
        （含字段展开或 opaque 回退，加载完后 efx_dirty=False）
      - 继续保留自定义属性 data_bytes 用于不依赖 PropertyGroup 的场景

    L2 #1c 新增：
      - extern_objs_by_index / count_extern 传入 init_block_props，
        供 EXTERNREFERENCE 块的 extern 指针化使用。

    命名方案（显示用，不影响导出顺序）：
      [父body标签] NN 类型名
      NN = 块在该 body 内的序号（零填充 2 位，>99 则自动 3 位）
    """
    if extern_objs_by_index is None:
        extern_objs_by_index = {}

    for blk_idx, blk in enumerate(attr_blocks):
        type_name = _hash_display_name(blk.type_hash)
        # 序号前缀（同 body 命名规则）
        nn = str(blk_idx).zfill(2) if blk_idx < 100 else str(blk_idx)
        # 父标签前缀（方括号包裹，用于大纲分组识别）
        if parent_label:
            blk_name = f"[{parent_label}] {nn} {type_name}"
        else:
            blk_name = f"{nn} {type_name}"
        blk_obj  = _new_empty(blk_name, collection)
        blk_obj["~TYPE"]          = "EFX_BLOCK"
        blk_obj["efx_index"]      = blk_idx
        blk_obj["type_hash"]      = str(blk.type_hash)   # uint32：存十进制字符串防溢出
        blk_obj["data_bytes"]     = _b64enc(blk.data_bytes)
        blk_obj["efx_type_name"]  = type_name  # L2 #3a：类型名，重排重建显示名用
        blk_obj.parent            = parent_obj

        # ── L1.1a + L2 #1c：初始化 efx_block PropertyGroup ──────────────────
        # init_block_props 内部管理 _LOADING 守卫，填完后重置 efx_dirty=False。
        # L2 #1c：extra args extern_objs_by_index/count_extern 供 EXTERNREFERENCE 使用。
        try:
            _fields.init_block_props(
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

def export_efx_tree(root_object: bpy.types.Object) -> bytes:
    """
    从 EFX_ROOT 对象树还原 .efx 文件字节。

    参数
    ----
    root_object : bpy.types.Object
        由 import_efx_tree 创建的 EFX_ROOT Empty。

    返回
    ----
    bytes
        完整 .efx 文件字节（byte-perfect）。
    """
    r = root_object  # 简写

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

    # ── 3. 还原 eof_ints（L2 #1d：优先走 efx_eof_list 指针路径）────────────────
    # L2 #1d 前：逗号分隔十进制字符串；空字符串表示空列表
    # L2 #1d 后：由 export_eof_ints 从 CollectionProperty 还原（body 指针 + raw 值）。
    # 注意：eof_ints 依赖 body_index_map，该 map 在 §4 收集 body_objs 后才能构建。
    # 故此处先占位，§4b 补填；最终在 §6 拼接字节前使用。
    eof_ints = None  # 占位，§4b 补填

    # ── 4. 收集 Main body 对象（按 efx_index 排序）────────────────────────
    #   子对象通过 parent == root_object 且 ~TYPE == EFX_BODY 来找
    body_objs = _collect_children_by_type(r, "EFX_BODY")
    body_objs.sort(key=lambda o: int(o["efx_index"]))

    # ── 4a. 提前构建 extern_index_map（L2 #1c）─────────────────────────────────
    # 需要在遍历 main_bodies 时传给 _resolve_block_data_bytes，
    # 所以在 §4 主循环开始前先收集并排序 EFX_EXTERN 对象。
    extern_objs = _collect_children_by_type(r, "EFX_EXTERN")
    extern_objs.sort(key=lambda o: int(o["efx_index"]))
    # {EFX_EXTERN Object → extern 段局部 0-based index}
    extern_index_map = {obj: idx for idx, obj in enumerate(extern_objs)}

    # ── 4b. 构建 body_index_map 和 play_index_map（L2 #1d）─────────────────────
    # body_objs 已排序，enumerate 序号 == Main 局部 index（与导出顺序一致）
    body_index_map_export = {obj: idx for idx, obj in enumerate(body_objs)}

    # play_objs 在 §5 收集；此处先收集排序以便 _resolve_block_data_bytes 使用
    play_objs_prescan = _collect_children_by_type(r, "EFX_PLAY")
    play_objs_prescan.sort(key=lambda o: int(o["efx_index"]))
    play_index_map_export = {obj: idx for idx, obj in enumerate(play_objs_prescan)}

    # ── 2b. 决定 label_bytes（play/extern/body 对象均已收集）──────────────────
    # 混合策略（契合本仓库"未编辑走 verbatim"哲学）：
    #   labels_dirty==0（未改名/未增删）→ emit 原始 blob，保证 byte-perfect。
    #   labels_dirty==1（改名/增删/结构变）→ 从对象重建 = join(有标签条目) + tail。
    # 重建已证明对未编辑文件 == verbatim（78/78），故增删走重建路径安全。
    if int(r.get("labels_dirty", 0)):
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

    # ── 4c. 还原 eof_ints（L2 #1d：body 指针 → 局部 index）────────────────────
    # eof_dirty=1（用户编辑过激活集 / 删过 body）→ sanitize：丢弃越界 raw 哨兵（陈旧错误索引）。
    # 未编辑（=0）→ 原样还原，保 byte-perfect。
    try:
        _eof_sanitize = bool(int(r.get("eof_dirty", 0)))
    except (ValueError, TypeError):
        _eof_sanitize = False
    try:
        eof_ints = _body_play_ref.export_eof_ints(
            r, body_index_map_export, sanitize=_eof_sanitize)
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
        # 修复：截断到 n_body，丢弃尾部多余条目（哨兵总在末尾；已有指针的 body 删除
        # 会走悬空跳过路径，不产生此问题）。78/78 不受影响（未编辑文件 len==count_body）。
        eof_ints = eof_ints[:len(body_objs)]

    main_bodies = []
    for body_obj in body_objs:
        kind = str(body_obj["body_kind"])

        if kind == "root":
            if int(body_obj.get("root_structured", 0)) == 1:
                n = int(body_obj.get("root_ub_count", 0))
                entries = []
                for j in range(n):
                    ints = tuple(int(x) for x in body_obj["root_ub%d_ints" % j])
                    floats = tuple(float(x) for x in body_obj["root_ub%d_floats" % j])
                    entries.append(RootUnitBoundary(ints=ints, floats=floats))
                main_bodies.append(RootBody(
                    const0=int(str(body_obj["root_const0"])),
                    const1=int(str(body_obj["root_const1"])),
                    entries=entries,
                ))
            else:
                raw = _b64dec(str(body_obj["raw"]))
                main_bodies.append(RootBody(raw=raw))

        elif kind == "extended":
            # 收集 AttrBlock 子对象
            blk_objs = _collect_children_by_type(body_obj, "EFX_BLOCK")
            blk_objs.sort(key=lambda o: int(o["efx_index"]))
            attr_blocks = [
                AttrBlock(
                    type_hash  = int(str(blk["type_hash"])),
                    data_bytes = _resolve_block_data_bytes(
                        blk, extern_index_map,
                        body_index_map_export, play_index_map_export,
                    ),
                )
                for blk in blk_objs
            ]
            main_bodies.append(MainDataBodyExtended(
                body_type   = int(str(body_obj["body_type"])),
                unkn0       = int(str(body_obj["unkn0"])),
                null0       = int(str(body_obj["null0"])),
                null1       = int(str(body_obj["null1"])),
                unkn1       = int(str(body_obj["unkn1"])),
                unkn2       = int(str(body_obj["unkn2"])),
                attr_count  = len(attr_blocks),  # L2 #3b：从实际块数重算（增删块后正确）
                null2       = int(str(body_obj["null2"])),
                timl_length = len(_b64dec(str(body_obj["timl_bytes"]))),  # 从实际 timl 字节重算（支持编辑后变长；未编辑 == 原值）
                timl_bytes  = _b64dec(str(body_obj["timl_bytes"])),
                attr_blocks = attr_blocks,
            ))

        elif kind == "standard":
            blk_objs = _collect_children_by_type(body_obj, "EFX_BLOCK")
            blk_objs.sort(key=lambda o: int(o["efx_index"]))
            attr_blocks = [
                AttrBlock(
                    type_hash  = int(str(blk["type_hash"])),
                    data_bytes = _resolve_block_data_bytes(
                        blk, extern_index_map,
                        body_index_map_export, play_index_map_export,
                    ),
                )
                for blk in blk_objs
            ]
            main_bodies.append(MainDataBody(
                body_type   = int(str(body_obj["body_type"])),
                unkn0       = int(str(body_obj["unkn0"])),
                attr_count  = len(attr_blocks),  # L2 #3b：从实际块数重算（增删块后正确）
                null        = int(str(body_obj["null"])),
                timl_length = len(_b64dec(str(body_obj["timl_bytes"]))),  # 从实际 timl 字节重算（支持编辑后变长；未编辑 == 原值）
                timl_bytes  = _b64dec(str(body_obj["timl_bytes"])),
                attr_blocks = attr_blocks,
            ))

        else:
            # unknown：raw 存的是完整 serialize()，直接当 RootBody 原样拼接
            raw = _b64dec(str(body_obj["raw"]))
            main_bodies.append(RootBody(raw=raw))

    # ── 5. Play：L2 #1b 结构化导出（PLAYEMITTER targets 经 body_index_map 重算）──
    #   body_objs 已在 §4 按 efx_index 排序；body_index_map 在 §4b 构建。
    #   此处提前构建，以便 Play 导出也能用（Play 段在 Subselect 之前）。
    #   extern_objs 已在 §4a 收集并排序；extern_index_map 已在 §4a 构建。
    play_objs = play_objs_prescan  # §4b 已收集并排序，复用

    # body_index_map：{EFX_BODY Object → main_local_index}（§4b 已构建）
    _play_body_index_map = body_index_map_export

    play_raw = b""
    for po in play_objs:
        try:
            pd = _play_emitter.export_play_data(po, _play_body_index_map)
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
    subselect_objs = _collect_children_by_type(r, "EFX_SUBSELECT")
    subselect_objs.sort(key=lambda o: int(o["efx_index"]))

    # 构建 {EFX_BODY object → main_local_index} 映射
    # body_objs 已在 §4 按 efx_index 排序并 enumerate → 局部 index == enumerate 序号
    body_index_map = {obj: idx for idx, obj in enumerate(body_objs)}

    subselect_raw = b""
    for ss_obj in subselect_objs:
        try:
            tbl = _subselect.export_subselect_table(ss_obj, body_index_map)
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
    if int(r.get("subselect_dirty", 0)):
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


def _resolve_block_data_bytes(blk_obj: bpy.types.Object,
                              extern_index_map: dict = None,
                              body_index_map: dict = None,
                              play_index_map: dict = None) -> bytes:
    """
    L1.1a + L2 #1c + L2 #1d：决定导出时 EFX_BLOCK 的 data_bytes 来源。

    优先级：
      1. 若 efx_block.efx_dirty=True 且 is_editable=True
         → fields.get_block_data_bytes（重新 encode 用户修改；
           对 EXTERNREFERENCE/PTLIFE/PTCOLLISION + pointerized=True 额外覆写字段）
      2. 否则 → 自定义属性 data_bytes（base64 原始，byte-perfect 回退；
           对 EXTERNREFERENCE/PTLIFE/PTCOLLISION + pointerized=True 同样覆写）

    自定义属性 data_bytes 始终在导入时写入，作为保险。

    extern_index_map : dict[bpy.types.Object, int] | None — L2 #1c
    body_index_map   : dict[bpy.types.Object, int] | None — L2 #1d PTLIFE
    play_index_map   : dict[bpy.types.Object, int] | None — L2 #1d PTCOLLISION
    """
    try:
        bp = blk_obj.efx_block
        if bp.efx_dirty and bp.is_editable:
            return _fields.get_block_data_bytes(
                blk_obj,
                extern_index_map=extern_index_map,
                body_index_map=body_index_map,
                play_index_map=play_index_map,
            )
    except Exception:
        pass
    # 回退：原始自定义属性，再走 L2 #1c / #1d overlay
    data = _b64dec(str(blk_obj["data_bytes"]))
    if extern_index_map is not None:
        data = _fields._apply_extern_ref_overlay(blk_obj, data, extern_index_map)
    if body_index_map is not None or play_index_map is not None:
        data = _fields._apply_body_play_ref_overlays(
            blk_obj, data, body_index_map, play_index_map,
        )
    return data


def _collect_children_by_type(
    parent_obj: bpy.types.Object,
    type_tag: str,
) -> list:
    """
    收集 parent_obj 的直接子对象中 ~TYPE == type_tag 的所有对象。
    注意：Blender 没有直接的"children"列表，需遍历 bpy.data.objects。
    """
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
