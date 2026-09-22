"""在 EFX 二进制结构与 Blender 对象树之间导入、导出。

维护约束：
- EFX_ROOT 是顶层集合而非对象；段对象通过集合归属解析所属文件，属性和 TIML
  句柄仍以 parent 连接到 Entry。
- Header、未知 body、标签尾部及无法安全结构化的字节必须保留原始表示，以支持
  未编辑路径的原样导出。
- 导出依据对象树重新组织可编辑段；跨段引用使用各自段内索引，不能依赖显示名。
- efx_format 负责二进制模型，本模块只负责 Blender 映射。
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
    RootBody,
    RootUnitBoundary,
    ROOT_SUBENTRY_HASHES,
    SubselectTable,
)
from ..efx_format.hashes import HASH_TO_NAME
from ..efx_format.hashes import pretty_type_name as _pretty_type_name

# 字段模型在调用处使用，避免模块注册顺序形成循环依赖。
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


def _root_entry_to_attr_block(e) -> AttrBlock:
    """将可按 AttrBlock 编码表示的 Root 子条目映射为属性块。"""
    if isinstance(e, RootUnitBoundary):
        data = struct.pack('<2i', *e.ints) + struct.pack('<8f', *e.floats)
        return AttrBlock(type_hash=RootBody.UNITBOUNDARY, data_bytes=data)
    type_hash = struct.unpack_from('<I', e.raw, 0)[0]
    return AttrBlock(type_hash=type_hash, data_bytes=e.raw[4:])


def _new_empty(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    """在指定集合里建 Empty 对象，返回对象。"""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    collection.objects.link(obj)
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# EFX_TIML 句柄对象（TIML 统一入口）
# ─────────────────────────────────────────────────────────────────────────────
# TIML 字节归 Entry 所有；EFX_TIML 只是面板和算子的子对象句柄，必须先解析回父
# Entry，且不能作为独立属性块参与段操作。

def find_timl_handle(entry_obj: bpy.types.Object):
    """返回 body 的 TIML 句柄；独立 TIML 句柄本身也可作为结果。"""
    if entry_obj is None:
        return None
    if entry_obj.get("~TYPE") == "EFX_TIML":
        return entry_obj
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


# 由本次导出选项控制，导出过程不重入。
_EXPORT_RECALC_TIML_LEN = False


def _recalc_timl_length(data: bytes) -> bytes:
    """将存在的 TIML 动画长度更新为各自最后关键帧加一。"""
    from ..efx_format.timl import meta as _tm
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
    """导出 TIML 字节；同步失败时保留 Entry 中的原始字节。"""
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
    """将标签区拆成连续标签前缀和必须原样保留的不透明尾部。"""
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
    """解析 EFX 并建立顶层文件集合；颜色模式仅改变当前视图呈现。"""
    ctx = context if context is not None else bpy.context

    # ── 1. 解析文件 ─────────────────────────────────────────────────────────
    with open(filepath, "rb") as f:
        raw_data = f.read()
    efx = EFXFile.parse(raw_data)
    hdr = efx.header

    file_stem = os.path.splitext(os.path.basename(filepath))[0]
    file_name = os.path.basename(filepath)

    scene_col = ctx.scene.collection
    # 颜色编辑器导入使用独立根集合，避免与完整编辑器视图混淆。
    root_col_name = f"{file_stem}_color.efx" if color_editor_mode else file_name
    root_col = _rc.new_root_collection(root_col_name, scene_col)
    root_col["color_editor_mode"] = 1 if color_editor_mode else 0
    # 仅供关联资源解析使用，导出不读取源路径。
    root_col["src_path"] = os.path.abspath(filepath)

    # ── 3. header 全部字段直接存 root_col 自定义属性（不再建 Empty）────────────
    # uint32 以字符串保存，避免 Blender C int 溢出。
    root_col["hdr_signature"]       = hdr.signature.hex()          # "45465800"
    root_col["hdr_version"]         = str(hdr.version)
    root_col["hdr_constant"]        = ",".join(str(x) for x in hdr.constant)
    root_col["hdr_efxr"]            = hdr.efxr.hex()               # "65667872"
    root_col["hdr_is_3d"]           = str(hdr.is_3d)
    root_col["hdr_unkn1"]           = str(hdr.unkn1)
    root_col["hdr_count_body"]      = str(hdr.count_body)
    root_col["hdr_label_size"]      = str(hdr.label_size)
    root_col["hdr_count_play"]      = str(hdr.count_play)
    root_col["hdr_count_extern"]    = str(hdr.count_extern)
    root_col["hdr_count_subselect"] = str(hdr.count_subselect)
    root_col["hdr_subselect_size"]  = str(hdr.subselect_size)
    root_col["hdr_count_eof"]       = str(hdr.count_eof)
    root_col["hdr_double_buffer"]   = str(hdr.double_buffer)

    # 未修改标签时导出原始 blob；重建时仅替换连续标签前缀。
    root_col["label_bytes"]         = _b64enc(efx.label_bytes)
    # 标签按 Action、Extern、Entry 的连续前缀映射；尾部不参与标签解析。
    _clean_labels, _label_tail = split_labels_tail(
        efx.label_bytes, hdr.count_play + hdr.count_extern + hdr.count_body)
    root_col["label_tail"]          = _b64enc(_label_tail)
    # 标签或相关结构变更后必须从对象树重建标签区。
    root_col["labels_dirty"]        = 0
    _n_labels                       = len(_clean_labels)  # 全局有标签条目数 k
    root_col["eof_ints"]            = ",".join(str(x) for x in efx.eof_ints)
    # EOF 后的不透明字节必须保留。
    root_col["eof_tail"]            = _b64enc(efx.eof_tail)

    # Main 段无法解析时保留整文件，供只读原样导出回退。
    if getattr(efx, "main_opaque", False):
        root_col["main_opaque_file_b64"] = _b64enc(raw_data)

    # 固定的段集合顺序也是导出段顺序。
    col_entry     = _rc.new_leaf_collection(file_stem + "_2 Entry",     root_col, "EFX_ENTRY")
    col_action    = _rc.new_leaf_collection(file_stem + "_0 Action",    root_col, "EFX_ACTION")
    col_extern    = _rc.new_leaf_collection(file_stem + "_1 Extern",    root_col, "EFX_EXTERN")
    col_subselect = _rc.new_leaf_collection(file_stem + "_3 Subselect", root_col, "EFX_SUBSELECT")

    # ── 5. Main：每个 body 建 Empty ─────────────────────────────────────────
    #
    # 标签前缀按 Action、Extern、Entry 的段顺序分配。
    play_label_count   = hdr.count_play
    extern_label_count = hdr.count_extern
    main_label_offset  = play_label_count + extern_label_count

    from ..efx_format import categories as _cat

    for body_idx, body in enumerate(efx.main):
        # 只有全局连续标签前缀中的条目拥有原始标签。
        label_idx = main_label_offset + body_idx
        has_label = label_idx < _n_labels
        if has_label:
            label_name = _clean_labels[label_idx]
        else:
            label_name = f"body_{body_idx}"  # 合成名（不进标签表）

        nn = str(body_idx).zfill(2) if body_idx < 100 else str(body_idx)
        raw_label = label_name or f"body_{body_idx}"
        _attr_blocks = getattr(body, "attr_blocks", None) or []
        renderer_suffix = _cat.renderer_suffix(blk.type_hash for blk in _attr_blocks)
        display_name = f"{nn} {raw_label}{renderer_suffix}"

        entry_obj = _new_empty(display_name, col_entry)
        entry_obj.empty_display_type = 'ARROWS'
        entry_obj["~TYPE"]         = "EFX_ENTRY"
        entry_obj["efx_index"]     = body_idx
        entry_obj["efx_raw_label"] = raw_label
        entry_obj["efx_has_label"] = int(has_label)

        if isinstance(body, RootBody):
            entry_obj["entry_kind"] = "root"
            if body.raw is not None:
                # 无法拆分的 Root body 仅保留原始字节。
                entry_obj["raw"] = _b64enc(body.raw)
            else:
                # 可按 AttrBlock 表示的 Root 子项复用属性对象和编辑路径。
                attr_blocks = [_root_entry_to_attr_block(e) for e in body.entries]
                _build_attr_attribute_children(attr_blocks, entry_obj, col_entry, raw_label)

        elif isinstance(body, EntryData):
            # 数值字段以字符串保存，避免 uint32 溢出。
            entry_obj["entry_kind"]   = "standard"
            entry_obj["body_type"]   = str(body.body_type)
            entry_obj["unkn0"]       = str(body.unkn0)
            entry_obj["attr_count"]  = str(body.attr_count)
            entry_obj["null"]        = str(body.null)
            entry_obj["timl_length"] = str(body.timl_length)
            entry_obj["timl_bytes"]  = _b64enc(body.timl_bytes)
            _build_attr_attribute_children(body.attr_blocks, entry_obj, col_entry, raw_label)
            if body.timl_length > 0:
                _h = make_timl_handle(entry_obj, col_entry)
                try:
                    from . import timl_edit as _te
                    _te.build_persistent_fcurves(_h, entry_obj)
                except Exception:
                    pass

        else:
            # 未知类型：保守存整段 serialize()
            entry_obj["entry_kind"] = "unknown"
            entry_obj["raw"]       = _b64enc(body.serialize())

    # Action 解析依赖已创建的 Entry 映射。
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

        # ── action_emitter.py：结构化初始化 ──────────────────────────────────────────────
        try:
            _action_emitter.init_action_props(obj, pd, _action_entries_by_index)
        except Exception:
            # 任何异常均安全回退：raw_b64 保证 byte-perfect
            pass

    # ── 7. Extern：每个 ExternAttribute 存 serialize() 字节 ──────
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
        # 原始 item 数区分文件中的空 Extern 与编辑后变空的 Extern。
        obj["hdr_item_count"] = len(ea.items)
        try:
            from . import extern_props as _ep
            _ep.init_extern_props(obj, ea)
        except Exception:
            pass  # 任何异常安全跳过，raw_b64 保底

    # Main 在 Extern 前创建；现有 Extern 对象后再解析 EXTERNREFERENCE 指针。
    _extern_objs_by_index = {
        int(_eo["efx_index"]): _eo
        for _eo in _rc.collect_top_level(root_col, "EFX_EXTERN")
    }

    _count_extern = hdr.count_extern  # 文件头的 count_extern

    # 只扫描当前文件的 Entry 集合，避免跨文件错误绑定。
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

    # Action 已创建后，才能将 PTLIFE/PTCOLLISION 的段内索引解析为指针。
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

    # 只扫描当前文件的属性对象。
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

    # Subselect 的引用目标是 Entry 段的局部索引。
    main_bodies_by_index = {
        int(entry_obj["efx_index"]): entry_obj
        for entry_obj in _rc.collect_top_level(root_col, "EFX_ENTRY")
    }

    for i, tbl in enumerate(efx.subselect):
        nn = str(i).zfill(2) if i < 100 else str(i)
        obj = _new_empty(f"{nn} subselect_{i}", col_subselect)
        obj["~TYPE"]     = "EFX_SUBSELECT"
        obj["efx_index"] = i
        # 结构化解析失败时使用原始字节回退。
        obj["raw_b64"]   = _b64enc(tbl.serialize())

        # ── subselect.py：结构化初始化 ──────────────────────────────────────────────
        try:
            _subselect.init_subselect_props(obj, tbl, main_bodies_by_index)
        except Exception:
            # 任何异常均安全回退：raw_b64 保证 byte-perfect
            pass

    # EOF 以 Entry 归属的嵌套集合表示；导入时规范为唯一、升序且范围内的索引集合。
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

    # 补齐标签时只更新标签层，身份哈希保持原值，并标记标签表需要重建。
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
    """仅调整颜色编辑器的 View Layer 呈现，不改变集合归属或导出数据。"""
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
    """创建 Entry 属性子对象并初始化字段模型。

    属性的 ``efx_index`` 与父子关系决定导出顺序；显示名不参与序列化。
    """
    if extern_objs_by_index is None:
        extern_objs_by_index = {}

    for blk_idx, blk in enumerate(attr_blocks):
        type_name = _hash_display_name(blk.type_hash)
        display_type_name = _pretty_type_name(type_name)
        nn = str(blk_idx).zfill(2) if blk_idx < 100 else str(blk_idx)
        if parent_label:
            blk_name = f"[{parent_label}] {nn} {display_type_name}"
        else:
            blk_name = f"{nn} {display_type_name}"
        blk_obj  = _new_empty(blk_name, collection)
        blk_obj["~TYPE"]          = "EFX_ATTRIBUTE"
        blk_obj["efx_index"]      = blk_idx
        blk_obj["type_hash"]      = str(blk.type_hash)
        blk_obj["data_bytes"]     = _b64enc(blk.data_bytes)
        blk_obj["efx_type_name"]  = type_name
        blk_obj.parent            = parent_obj

        # 传入 Extern 映射以解析 EXTERNREFERENCE；失败保留原始属性字节。
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
    """从顶层 EFX 集合序列化文件；可选地按最后关键帧重算 TIML 长度。"""
    global _EXPORT_RECALC_TIML_LEN
    r = root_object
    _EXPORT_RECALC_TIML_LEN = bool(recalc_timl_length)

    # 无法解析 Main 段的文件没有可安全重建的结构，只能原样导出。
    _opaque_file = r.get("main_opaque_file_b64")
    if _opaque_file:
        return _b64dec(str(_opaque_file))

    # uint32 自定义属性以十进制字符串保存。
    hdr = EFXHeader(
        signature       = bytes.fromhex(str(r["hdr_signature"])),
        version         = int(str(r["hdr_version"])),
        constant        = tuple(int(x) for x in str(r["hdr_constant"]).split(",")),
        efxr            = bytes.fromhex(str(r["hdr_efxr"])),
        is_3d           = int(str(r["hdr_is_3d"])),
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

    label_bytes = None
    label_size  = None

    # EOF 依赖 Main 段局部索引，待收集 Entry 后再生成。
    eof_ints = None

    # 段对象经集合归属和类型标记定位。
    body_objs = _rc.collect_top_level(r, "EFX_ENTRY")
    # Root body 必须位于 Main 段首位；其余条目维持既有相对顺序。
    body_objs.sort(key=lambda o: 0 if str(o.get("entry_kind", "")) == "root" else 1)

    # 预建属性映射供导出循环复用，且限定在当前 EFX 集合。
    _attr_children_map = _build_attr_children_map(_rc.get_leaf_collection(r, "EFX_ENTRY"))

    # 仅删除后遗留的空壳（导入时属性数为正）可过滤；原生合法空 Entry 必须保留。
    def _is_native_delete_leftover(o):
        if str(o.get("entry_kind", "")) != "standard":
            return False
        if _collect_children_by_type(o, "EFX_ATTRIBUTE", _attr_children_map):
            return False  # 还有块 → 不是空壳
        try:
            return int(str(o.get("attr_count", "0"))) > 0
        except (ValueError, TypeError):
            return False
    body_objs = [o for o in body_objs if not _is_native_delete_leftover(o)]

    # 过滤必须先于建索引：写出顺序、引用索引、header 计数和标签位置必须共用此列表。
    def _extern_bytes(o):
        """一个 EFX_EXTERN 对象最终写出的字节（结构化失败则回退原始字节）。"""
        try:
            from . import extern_props as _ep
            return _ep.export_extern_data(o)
        except Exception:
            return _b64dec(str(o["raw_b64"]))

    def _is_empty_extern(o):
        """判断是否应丢弃编辑后为空的 Extern；源文件中的空 Extern 必须保留。"""
        hdr = o.get("hdr_item_count")
        if hdr is not None:
            try:
                if int(str(hdr)) == 0:
                    return False        # 导入时本就为空 → 原样保留
            except (ValueError, TypeError):
                pass
        data = _extern_bytes(o)
        if len(data) < 12:
            return False                # 字节异常，不敢丢
        return struct.unpack_from("<i", data, 8)[0] == 0   # EA 头 +8 = item_count

    _all_extern_objs = _rc.collect_top_level(r, "EFX_EXTERN")
    dropped_extern_objs = [o for o in _all_extern_objs if _is_empty_extern(o)]
    extern_objs = [o for o in _all_extern_objs if o not in dropped_extern_objs]
    # {EFX_EXTERN Object → extern 段局部 0-based index}（只含真正写出的）
    extern_index_map = {obj: idx for idx, obj in enumerate(extern_objs)}

    # ── 4b. 构建 entry_index_map 和 play_index_map（entry_action_ref.py）─────────────────────
    # body_objs 已排序，enumerate 序号 == Main 局部 index（与导出顺序一致）
    body_index_map_export = {obj: idx for idx, obj in enumerate(body_objs)}

    # play_objs 在 §5 收集；此处先收集排序以便 _resolve_attribute_data_bytes 使用
    play_objs_prescan = _rc.collect_top_level(r, "EFX_ACTION")
    play_index_map_export = {obj: idx for idx, obj in enumerate(play_objs_prescan)}

    # subselect_objs 在 §5b 才用，这里提前收集只为下面的结构变化检测；§5b 直接复用。
    subselect_objs_prescan = _rc.collect_top_level(r, "EFX_SUBSELECT")

    # 与导入时的 header 快照比较，确保绕过插件算子的结构改动也会重建关联数据。
    _entry_count_changed = len(body_objs) != int(str(r.get("hdr_count_body", len(body_objs))))
    _play_count_changed = len(play_objs_prescan) != int(str(r.get("hdr_count_play", len(play_objs_prescan))))
    _extern_count_changed = len(extern_objs) != int(str(r.get("hdr_count_extern", len(extern_objs))))
    _subselect_count_changed = len(subselect_objs_prescan) != int(str(r.get("hdr_count_subselect", len(subselect_objs_prescan))))
    _labels_need_rebuild = _entry_count_changed or _play_count_changed or _extern_count_changed
    # Entry 数变化也会改变 Subselect 中可写出的成员。
    _subselect_need_rebuild = _subselect_count_changed or _entry_count_changed

    # 未改标签和结构时保留原始 blob；否则从连续标签前缀和原始尾部重建。
    if int(r.get("labels_dirty", 0)) or _labels_need_rebuild:
        # 仅写有标签的连续前缀，顺序为 Action、Extern、Entry。
        _ordered = list(play_objs_prescan) + list(extern_objs) + list(body_objs)
        _labels  = [str(o.get("efx_raw_label", ""))
                    for o in _ordered if int(o.get("efx_has_label", 1))]
        _tail    = _b64dec(str(r.get("label_tail", "")))
        label_bytes = b''.join(s.encode('utf-8') + b'\x00' for s in _labels) + _tail
    else:
        # 原始 blob 包含不透明尾部。
        label_bytes = _b64dec(str(r["label_bytes"]))
    label_size = len(label_bytes)

    # EOF 由 Entry 归属集合重建为 Main 段局部索引；旧数据使用字符串回退。
    try:
        eof_ints = _entry_action_ref.export_eof_per_entry(r, body_index_map_export)
    except Exception:
        # 回退：旧字符串路径
        _eof_str = str(r["eof_ints"]).strip()
        eof_ints = [int(x) for x in _eof_str.split(",") if x] if _eof_str else []

    # 没有 Main body 时不能写出 EOF 引用。
    if len(body_objs) == 0:
        eof_ints = []
    elif len(eof_ints) > len(body_objs):
        # 防止遗留的越界 EOF 值使 count_eof 超出可引用的 Entry 数。
        eof_ints = eof_ints[:len(body_objs)]

    # Root 专属子项与普通属性不能跨 Entry 类型写出；丢弃记录供校验界面报告。
    _root_attr_dropped = []

    main_bodies = []
    for entry_obj in body_objs:
        kind = str(entry_obj["entry_kind"])

        if kind == "root":
            # Root 子项使用 AttrBlock 的等价编码；没有可编辑子项时回退原始字节。
            blk_objs = _collect_children_by_type(entry_obj, "EFX_ATTRIBUTE", _attr_children_map)
            if blk_objs:
                blk_objs.sort(key=lambda o: int(o["efx_index"]))
                valid_objs, bad_objs = [], []
                for blk in blk_objs:
                    (valid_objs if int(str(blk["type_hash"])) in ROOT_SUBENTRY_HASHES
                     else bad_objs).append(blk)
                for blk in bad_objs:
                    _root_attr_dropped.append(
                        f"{blk.get('efx_type_name', blk.name)} on Root entry "
                        f"'{entry_obj.name}' (not a Root sub-entry type)"
                    )
                if valid_objs:
                    attr_blocks = [
                        AttrBlock(type_hash=int(str(blk["type_hash"])),
                                 data_bytes=_b64dec(str(blk["data_bytes"])))
                        for blk in valid_objs
                    ]
                    main_bodies.append(RootBody(entries=attr_blocks))
                elif "raw" in entry_obj:
                    raw = _b64dec(str(entry_obj["raw"]))
                    main_bodies.append(RootBody(raw=raw))
                else:
                    main_bodies.append(RootBody(entries=[]))
            else:
                raw = _b64dec(str(entry_obj["raw"]))
                main_bodies.append(RootBody(raw=raw))

        elif kind == "standard":
            blk_objs = _collect_children_by_type(entry_obj, "EFX_ATTRIBUTE", _attr_children_map)
            blk_objs.sort(key=lambda o: int(o["efx_index"]))
            good_objs = []
            for blk in blk_objs:
                if int(str(blk["type_hash"])) in ROOT_SUBENTRY_HASHES:
                    _root_attr_dropped.append(
                        f"{blk.get('efx_type_name', blk.name)} on non-root entry "
                        f"'{entry_obj.name}' (Root-only sub-entry type)"
                    )
                else:
                    good_objs.append(blk)
            blk_objs = good_objs
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
            _std_timl = _export_timl_bytes(entry_obj)
            main_bodies.append(EntryData(
                body_type   = int(str(entry_obj["body_type"])),
                unkn0       = int(str(entry_obj["unkn0"])),
                attr_count  = len(attr_blocks),
                null        = int(str(entry_obj["null"])),
                timl_length = len(_std_timl),
                timl_bytes  = _std_timl,
                attr_blocks = attr_blocks,
            ))

        else:
            # unknown：raw 存的是完整 serialize()，直接当 RootBody 原样拼接
            raw = _b64dec(str(entry_obj["raw"]))
            main_bodies.append(RootBody(raw=raw))

    # 将无法写出的错位属性记录在根集合，供校验界面报告。
    if _root_attr_dropped:
        r["root_attr_dropped"] = "; ".join(_root_attr_dropped)
    elif "root_attr_dropped" in r:
        del r["root_attr_dropped"]

    # Action 导出使用已按 Main 段顺序建立的 Entry 局部索引。
    play_objs = play_objs_prescan  # §4b 已收集并排序，复用

    _action_entry_index_map = body_index_map_export

    play_raw = b""
    for po in play_objs:
        try:
            pd = _action_emitter.export_action_data(po, _action_entry_index_map)
            play_raw += pd.serialize()
        except Exception:
            # 结构化导出失败时保留原始 Action 字节。
            play_raw += _b64dec(str(po["raw_b64"]))

    extern_raw = b"".join(_extern_bytes(o) for o in extern_objs)

    # Subselect 使用 Main 段局部索引，结构化导出失败时回退原始字节。
    subselect_objs = subselect_objs_prescan

    entry_index_map = {obj: idx for idx, obj in enumerate(body_objs)}

    subselect_raw = b""
    for ss_obj in subselect_objs:
        try:
            tbl = _subselect.export_subselect_table(ss_obj, entry_index_map)
            subselect_raw += tbl.serialize()
        except Exception:
            # 结构化导出失败时保留原始 Subselect 字节。
            subselect_raw += _b64dec(str(ss_obj["raw_b64"]))

    # 所有段计数必须由实际写出的对象数重算。
    hdr.count_body      = len(body_objs)
    hdr.count_play      = len(play_objs)
    hdr.count_extern    = len(extern_objs)
    hdr.count_subselect = len(subselect_objs)
    hdr.count_eof       = len(eof_ints)
    hdr.label_size      = label_size           # = len(label_bytes)，verbatim 或重建

    # subselect_size 和 double_buffer 的含义未完全结构化；前者仅在段变化时重算，后者保留原值。
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
    """取得属性导出字节。

    可编辑属性始终由字段模型重建；opaque 或编码失败时使用原始字节。两条路径都
    会叠加已指针化的 Extern、Entry 与 Action 段内索引。
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
    # Opaque 或编码异常时仍需应用已指针化引用的索引覆盖。
    data = _b64dec(str(blk_obj["data_bytes"]))
    if extern_index_map is not None:
        data = _fields._apply_extern_ref_overlay(blk_obj, data, extern_index_map)
    if entry_index_map is not None or play_index_map is not None:
        data = _fields._apply_entry_action_ref_overlays(
            blk_obj, data, entry_index_map, play_index_map,
        )
    return data


def _build_attr_children_map(entry_col) -> dict:
    """按父对象收集 Entry 集合及其嵌套集合中的属性，供导出主循环复用。"""
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
    """收集 parent_obj 的指定直接子对象；属性优先使用预建映射。"""
    if children_map is not None and type_tag == "EFX_ATTRIBUTE":
        return list(children_map.get(parent_obj, []))
    results = []
    for obj in bpy.data.objects:
        if obj.parent == parent_obj and obj.get("~TYPE") == type_tag:
            results.append(obj)
    return results


def roundtrip_corpus(samples_dir: str) -> dict:
    """返回目录中 EFX 文件往返序列化的统计与失败详情。"""
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
            with open(filepath, "rb") as f:
                original = f.read()
            root_obj = import_efx_tree(filepath)
            result = export_efx_tree(root_obj)
            if result == original:
                passed += 1
            else:
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
            _cleanup_efx_tree(name)

    return {"total": total, "passed": passed, "failed": failed}


def _first_diff(a: bytes, b: bytes) -> int:
    """返回两个 bytes 对象首个不同位置；若长度相同且内容相同返回 -1。"""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return len(a) if len(a) != len(b) else -1


def _cleanup_efx_tree(file_stem_or_name: str) -> None:
    """删除指定导入树及其递归子集合；接受文件名或 stem。"""
    root_col = (bpy.data.collections.get(file_stem_or_name)
                or bpy.data.collections.get(os.path.splitext(file_stem_or_name)[0]))
    if root_col is None:
        return  # 不存在则跳过

    all_objects = _collect_all_objects_in_collection(root_col)
    for obj in all_objects:
        obj.parent = None

    for obj in all_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

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
