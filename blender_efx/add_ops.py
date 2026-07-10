"""
blender_efx/add_ops.py  —  L2 #3c：从「整 entry 预设」新增 entry + Active EFX 选择器

功能：
  - save_entry_preset(entry_obj, name)：把整个 entry（头字段 + 属性列表）存为 JSON 预设
  - add_entry_from_preset(preset_path, root_obj)：按预设新建一个 EFX_ENTRY 对象树
  - list_entry_presets()：扫 __entries__/ 目录生成 EnumProperty items
  - 算子：efx.save_entry_preset / efx.add_entry_from_preset / efx.open_entry_preset_folder
  - Scene.efx_active_efx：当前操作的 EFX 文件集合（新增 entry / 导出目标，PointerProperty → Collection）
  - get_active_efx_root(context)：解析当前活动 EFX 根

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2），bpy 只用长期稳定子集
  - 包内相对导入；不改 efx_format/ 与 io_tree.py（仅复用其函数）
  - 新增 entry 只需：建对象、设好 efx_index、置 root["labels_dirty"]=1，
    导出端会按实际内容自动重算 header 计数/size。
  - #3c 跨文件引用增强：从预设新增 entry 时，对属性内 EXTERNREFERENCE/PTLIFE/
    PTCOLLISION 三类引用重指针化到**目标文件**的段。目标范围内→指向目标对象；
    源有效但目标越界（真·跨文件断引用）→悬空（pointerized=True, ptr=None，由
    #4 校验报告供用户重连）；源也越界/死属性→verbatim（pointerized=False，原样保留）。
    需预设记录源文件段计数（save_entry_preset 写入 "source_counts"）。
  - entry 头字段名与 io_tree.py 导入端（第 238-276 行）完全一致：
      standard：body_type / unkn0 / attr_count / null / timl_length / timl_bytes
      extended：body_type / unkn0 / null0 / null1 / unkn1 / unkn2 / attr_count /
                null2 / timl_length / timl_bytes
      root / unknown：raw
    （attr_count 仅作记录，新增时忽略——导出端按实际属性数重算）

预设 JSON schema：
{
  "efx_preset_kind": "entry",
  "entry_kind": "standard",
  "props": {"body_type": "...", "unkn0": "...", ...},   # 除 timl_bytes 外的头字段（十进制字符串）
  "timl_bytes": "<b64>",
  "raw": "",                                            # root/unknown 才用
  "source_label": "原 raw_label（仅供默认命名，新增不进标签表）",
  "source_counts": {"extern": <int>, "entry": <int>, "action": <int>},  # 源文件段计数（#3c 跨文件断引用判定）
  "attributes": [ {"type_hash": "<十进制str>", "data_bytes": "<b64>"}, ... ]
}
"""

import json
import os
import re
import time

import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty

from .presets import _presets_root

# poll_message_set 是 4.0+ API（3.6 上不存在），用于给禁用状态的按钮显示原因提示。
_HAS_POLL_MESSAGE_SET = hasattr(bpy.types.Operator, "poll_message_set")


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

def _entries_preset_dir() -> str:
    """返回 entry 预设目录 presets/__entries__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__entries__")


# 各 kind 的头字段名（除 timl_bytes/raw 外）——与 io_tree.py 导入端完全一致。
_STANDARD_PROP_KEYS = ("body_type", "unkn0", "attr_count", "null", "timl_length")
_EXTENDED_PROP_KEYS = (
    "body_type", "unkn0", "null0", "null1", "unkn1", "unkn2",
    "attr_count", "null2", "timl_length",
)


# ─────────────────────────────────────────────────────────────────────────────
# Active EFX root helper
# ─────────────────────────────────────────────────────────────────────────────

def _root_obj_in_collection(col):
    """返回集合内直接的 EFX_ROOT 对象（root_obj 直接 link 在 EFX 文件集合里），无则 None。"""
    if col is None:
        return None
    for o in col.objects:
        if o.get("~TYPE") == "EFX_ROOT":
            return o
    return None


def get_active_efx_root(context):
    """
    解析当前活动 EFX 根对象（供新增 entry / 复制粘贴 / 导出等用）。

    优先 scene.efx_active_efx（用户在 N 面板选的 EFX 文件**集合**）→ 取其内的 EFX_ROOT 对象；
    否则回退：活动对象所属的 EFX 顶层（向上找 EFX_ROOT）——这样跨文件复制/粘贴 entry 时，
    只要点一下目标文件里的任意对象就行，不必来回切 Active EFX 选择器；
    否则扫场景：若恰好有一个 EFX_ROOT 对象，返回它；
    否则返回 None（让用户显式选择）。
    """
    scn = getattr(context, "scene", None)
    if scn is not None:
        root = _root_obj_in_collection(getattr(scn, "efx_active_efx", None))
        if root is not None:
            return root

    try:
        from .operators import _find_efx_root
        root = _find_efx_root(context)
        if root is not None:
            return root
    except Exception:
        pass

    roots = [o for o in bpy.data.objects if o.get("~TYPE") == "EFX_ROOT"]
    if len(roots) == 1:
        return roots[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# save_entry_preset
# ─────────────────────────────────────────────────────────────────────────────

def save_entry_preset(entry_obj: bpy.types.Object, name: str) -> str:
    """
    把 entry_obj（整个 entry：头字段 + 属性列表）存为 JSON 预设文件。

    参数
    ----
    entry_obj : Object — ~TYPE == 'EFX_ENTRY' 的 Blender 对象
    name     : str    — 预设名称（不含 .json）

    返回
    ----
    str — 保存的 JSON 文件路径

    异常
    ----
    ValueError — 对象不是 EFX_ENTRY 或 name 非法
    """
    if not name or not name.strip():
        raise ValueError(f"save_entry_preset：预设名称不能为空")

    preset = build_entry_preset_dict(entry_obj)
    # 用户输入名作为显示名（可含中文，存进 JSON，下拉从这里 utf-8 读）
    preset["display_name"] = name

    save_dir = _entries_preset_dir()
    os.makedirs(save_dir, exist_ok=True)

    # 文件名一律 ASCII：净化用户名 → 空则退回 entry 标签名 → 仍空用 "entry"；重名加 _0/_1…
    from .presets import _unique_ascii_filename
    fallback = str(entry_obj.get("efx_raw_label", "")) or "entry"
    fname = _unique_ascii_filename(save_dir, name, fallback)
    json_path = os.path.join(save_dir, fname + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=4)

    return json_path


def build_entry_preset_dict(entry_obj: bpy.types.Object) -> dict:
    """
    把 entry_obj（整个 entry：头字段 + 属性列表）构建为 preset dict（不落盘）。
    供 save_entry_preset（写文件）与 复制Entry（内存剪贴板）共用。
    """
    if entry_obj is None or entry_obj.get("~TYPE") != "EFX_ENTRY":
        raise ValueError("build_entry_preset_dict：目标对象不是 EFX_ENTRY")

    entry_kind = str(entry_obj.get("entry_kind", "unknown"))

    preset = {
        "efx_preset_kind": "entry",
        "entry_kind": entry_kind,
        # display_name：下拉显示用（utf-8 从 JSON 读，免疫文件名编码）；
        # 默认用 entry 自身的标签名，save_entry_preset 可用用户输入覆盖。
        "display_name": str(entry_obj.get("efx_raw_label", "")),
        "props": {},
        "timl_bytes": "",
        "raw": "",
        "source_label": str(entry_obj.get("efx_raw_label", "")),
        "source_counts": _read_source_counts(entry_obj),
        "in_eof": _is_entry_in_eof(entry_obj),
        "attributes": [],
    }

    if entry_kind == "standard":
        for key in _STANDARD_PROP_KEYS:
            preset["props"][key] = str(entry_obj.get(key, ""))
        preset["timl_bytes"] = str(entry_obj.get("timl_bytes", ""))
        preset["attributes"] = _collect_attribute_dicts(entry_obj)

    elif entry_kind == "extended":
        for key in _EXTENDED_PROP_KEYS:
            preset["props"][key] = str(entry_obj.get(key, ""))
        preset["timl_bytes"] = str(entry_obj.get("timl_bytes", ""))
        preset["attributes"] = _collect_attribute_dicts(entry_obj)

    else:
        # root / unknown：整段 raw（b64），无属性子对象
        preset["raw"] = str(entry_obj.get("raw", ""))

    return preset


def _collect_attribute_dicts(entry_obj: bpy.types.Object) -> list:
    """
    收集 entry_obj 的 EFX_ATTRIBUTE 子对象（按 efx_index 升序），
    每个存 {"type_hash": <十进制str>, "data_bytes": <b64>}。

    ⚠ data_bytes 用**导出端同款的字段感知解析**（io_tree._resolve_attribute_data_bytes）
    取当前实际字节——脏属性按字段模型重打包、引用属性按指针覆写——而非读
    obj["data_bytes"]（那是导入快照、不含用户编辑）。这样预设/复制Entry 抓到的是修改后的值。
    源文件段局部 index 映射（按 efx_index 排序 enumerate）与导出一致，供引用覆写。
    """
    import base64
    from . import io_tree

    root = entry_obj.parent  # EFX_ROOT

    def _localmap(type_tag):
        objs = [o for o in bpy.data.objects
                if o.parent == root and o.get("~TYPE") == type_tag]
        objs.sort(key=lambda o: int(o.get("efx_index", 0)))
        return {o: i for i, o in enumerate(objs)}

    extern_map = _localmap("EFX_EXTERN") if root is not None else {}
    entry_map   = _localmap("EFX_ENTRY")   if root is not None else {}
    play_map   = _localmap("EFX_ACTION")   if root is not None else {}

    attrs = [o for o in bpy.data.objects
             if o.parent == entry_obj and o.get("~TYPE") == "EFX_ATTRIBUTE"]
    attrs.sort(key=lambda o: int(o.get("efx_index", 0)))

    out = []
    for b in attrs:
        try:
            data = io_tree._resolve_attribute_data_bytes(b, extern_map, entry_map, play_map)
        except Exception:
            # 回退：原始快照（至少不崩）
            data = base64.b64decode(str(b.get("data_bytes", "")))
        out.append({
            "type_hash": str(b.get("type_hash", "")),
            "data_bytes": base64.b64encode(data).decode("ascii"),
        })
    return out


def _read_source_counts(entry_obj: bpy.types.Object) -> dict:
    """
    从 entry_obj 的根对象（parent，~TYPE=='EFX_ROOT'）读出源文件段计数，
    用于 #3c 跨文件断引用判定（区分"源有效但目标越界"与"源也越界"）。

    根属性 hdr_count_extern / hdr_count_body / hdr_count_play 都是十进制字符串。
    取不到（防御）→ 该项存 0。
    """
    counts = {"extern": 0, "entry": 0, "action": 0}
    root = entry_obj.parent
    if root is None or root.get("~TYPE") != "EFX_ROOT":
        return counts
    for key, attr in (("extern", "hdr_count_extern"),
                      ("entry", "hdr_count_body"),
                      ("action", "hdr_count_play")):
        try:
            counts[key] = int(str(root.get(attr)))
        except (ValueError, TypeError):
            counts[key] = 0
    return counts


def _is_entry_in_eof(entry_obj: bpy.types.Object) -> bool:
    """entry_obj 的 efx_index 是否出现在所属 EFX_ROOT 的 efx_eof_list 中。"""
    root = entry_obj.parent
    if root is None or root.get("~TYPE") != "EFX_ROOT":
        return False
    try:
        props = root.efx_eof_list
    except AttributeError:
        return False
    try:
        my_idx = int(entry_obj.get("efx_index", -1))
    except (ValueError, TypeError):
        return False
    for item in props.items:
        if item.is_ptr and item.body_ptr == entry_obj:
            return True
    return False


def _append_to_eof(root_obj: bpy.types.Object,
                   entry_obj: bpy.types.Object) -> None:
    """向 root_obj.efx_eof_list 末尾追加一条指向 entry_obj 的指针条目。"""
    try:
        props = root_obj.efx_eof_list
    except AttributeError:
        return
    item = props.items.add()
    item.is_ptr = True
    item.body_ptr = entry_obj


# ─────────────────────────────────────────────────────────────────────────────
# add_entry_from_preset
# ─────────────────────────────────────────────────────────────────────────────

def add_entry_from_preset(preset_path: str,
                         root_obj: bpy.types.Object) -> bpy.types.Object:
    """
    按 entry 预设新建一个 EFX_ENTRY 对象（含属性子对象），挂到 root_obj 下。

    复用 io_tree 的构建逻辑，属性 data_bytes 逐字保留为 raw（v1 不跨文件指针化）。
    新增后置 root_obj["labels_dirty"]=1，导出端按实际内容重算 header。

    参数
    ----
    preset_path : str    — entry 预设 JSON 路径
    root_obj    : Object — 目标 EFX_ROOT 对象

    返回
    ----
    Object — 新建的 EFX_ENTRY 对象

    异常
    ----
    ValueError — 预设非法 / root_obj 无效 / 读取失败
    """
    if root_obj is None or root_obj.get("~TYPE") != "EFX_ROOT":
        raise ValueError("add_entry_from_preset：root_obj 不是 EFX_ROOT")

    # ── 读 JSON ────────────────────────────────────────────────────────────────
    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            preset = json.load(f)
    except Exception as exc:
        raise ValueError(f"add_entry_from_preset：读取预设失败：{exc}")

    return add_entry_from_preset_dict(preset, root_obj)


def add_entry_from_preset_dict(preset: dict,
                              root_obj: bpy.types.Object) -> bpy.types.Object:
    """
    按 preset dict 新建 entry（add_entry_from_preset 的核心；供文件版与"粘贴Entry"内存版共用）。
    """
    from . import io_tree
    from ..efx_format.efxfile import AttrBlock

    if root_obj is None or root_obj.get("~TYPE") != "EFX_ROOT":
        raise ValueError("add_entry_from_preset_dict：root_obj 不是 EFX_ROOT")
    if preset.get("efx_preset_kind") != "entry":
        raise ValueError("add_entry_from_preset_dict：不是 entry 预设（efx_preset_kind != 'entry'）")

    entry_kind = str(preset.get("entry_kind", "unknown"))
    source_label = str(preset.get("source_label", ""))

    # ── 找目标 Main 集合 ──────────────────────────────────────────────────────
    col_entry = _find_entry_collection(root_obj)

    # ── 计算新 efx_index = 现有 entry 最大 index + 1 ───────────────────────────
    max_idx = -1
    for obj in bpy.data.objects:
        if obj.parent == root_obj and obj.get("~TYPE") == "EFX_ENTRY":
            try:
                max_idx = max(max_idx, int(obj.get("efx_index", 0)))
            except (ValueError, TypeError):
                pass
    new_index = max_idx + 1

    # ── 建 entry 对象 ──────────────────────────────────────────────────────────
    nn = str(new_index).zfill(2) if new_index < 100 else str(new_index)
    raw_label = source_label or f"entry_{new_index}"
    display_name = f"{nn} {source_label or 'entry'}"
    entry_obj = io_tree._new_empty(display_name, col_entry)
    entry_obj.empty_display_type = 'ARROWS'   # XYZ 三色轴，使特效体朝向直观可见

    entry_obj["~TYPE"]         = "EFX_ENTRY"
    entry_obj["efx_index"]     = new_index
    entry_obj["efx_raw_label"] = raw_label
    entry_obj["efx_has_label"] = 0           # 先置 0；下方在安全时提升
    entry_obj["entry_kind"]     = entry_kind
    entry_obj.parent           = root_obj

    # 若预设源 entry 有名字、且追加位置处于标签前缀边界（前面条目全有标签），
    # 给新 entry 一个真正的标签槽——名字才能持久化、也可被重命名。
    # 否则（文件本身有无标签 entry）保持 has_label=0（名字仅 Blender 显示，不进文件）。
    if source_label:
        try:
            from .reorder import can_label_entry
            if can_label_entry(entry_obj):
                entry_obj["efx_has_label"] = 1
        except Exception:
            pass

    props = preset.get("props", {}) or {}

    if entry_kind == "standard":
        for key in _STANDARD_PROP_KEYS:
            entry_obj[key] = str(props.get(key, "0"))
        entry_obj["timl_bytes"] = str(preset.get("timl_bytes", ""))
        _build_attributes(io_tree, AttrBlock, preset.get("attributes", []),
                      entry_obj, col_entry, raw_label)

    elif entry_kind == "extended":
        for key in _EXTENDED_PROP_KEYS:
            entry_obj[key] = str(props.get(key, "0"))
        entry_obj["timl_bytes"] = str(preset.get("timl_bytes", ""))
        _build_attributes(io_tree, AttrBlock, preset.get("attributes", []),
                      entry_obj, col_entry, raw_label)

    else:
        # root / unknown：整段 raw（b64）
        entry_obj["raw"] = str(preset.get("raw", ""))

    # #3c 跨文件引用重指针化：把新增 entry 内属性的段局部引用重指向目标文件的段。
    if entry_kind in ("standard", "extended"):
        _repointerize_refs(preset, entry_obj, root_obj)

    # 若源 entry 在源文件 eof 中，将新 entry 追加到目标文件 eof 列表
    if preset.get("in_eof"):
        _append_to_eof(root_obj, entry_obj)

    # entry 数量变化 → 标签表变 → 触发导出端重算
    root_obj["labels_dirty"] = 1

    return entry_obj


def _repointerize_refs(preset: dict,
                       entry_obj: bpy.types.Object,
                       root_obj: bpy.types.Object) -> None:
    """
    对刚新增 entry（entry_obj）下的引用属性（EXTERNREFERENCE/PTLIFE/PTCOLLISION），
    按**目标文件**（root_obj）的段重新指针化。

    复用 extern_ref / entry_action_ref 的 init 函数（不修改它们）：
      - 目标范围内 → init 已指向目标对象（pointerized=True）。
      - 哨兵 -1     → init 已设 none（pointerized=True）。
      - init 留 pointerized=False = 越界/死属性；再用 _flag_if_cross_file_broken
        借源计数区分"源有效但目标越界（→悬空）"与"源也越界（→verbatim）"。

    包一层 try/except：任何属性异常都安全跳过，保证新增不因引用问题失败。
    """
    from . import io_tree
    from . import extern_ref, entry_action_ref
    from ..efx_format.hashes import EXTERNREFERENCE, PTLIFE, PTCOLLISION

    # 1. 构建目标文件的段映射（按 efx_index）+ 计数
    target_extern_map = {}
    target_entry_map = {}
    target_play_map = {}
    for obj in bpy.data.objects:
        if obj.parent is not root_obj:
            continue
        t = obj.get("~TYPE")
        try:
            idx = int(obj.get("efx_index", 0))
        except (ValueError, TypeError):
            continue
        if t == "EFX_EXTERN":
            target_extern_map[idx] = obj
        elif t == "EFX_ENTRY":
            target_entry_map[idx] = obj
        elif t == "EFX_ACTION":
            target_play_map[idx] = obj

    target_count_extern = len(target_extern_map)
    target_count_entry = len(target_entry_map)
    target_count_play = len(target_play_map)

    # 2. 源计数（旧预设无此键 → 各项 None → 跳过 override，保持 init 行为）
    sc = preset.get("source_counts") or {}
    src_extern = sc.get("extern")
    src_entry = sc.get("entry")
    src_action = sc.get("action")

    # 3. 遍历刚新增 entry 下的 EFX_ATTRIBUTE 子对象
    for blk in bpy.data.objects:
        if blk.parent is not entry_obj or blk.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            data_bytes = io_tree._b64dec(str(blk.get("data_bytes", "")))
            th = int(str(blk.get("type_hash", "")))
        except (ValueError, TypeError):
            continue

        try:
            if th == EXTERNREFERENCE:
                extern_ref.init_extern_ref_props(
                    blk, data_bytes, target_extern_map, target_count_extern)
                _flag_if_cross_file_broken(
                    blk.efx_extern_ref, "extern_ref_ptr",
                    "extern_ref_pointerized", data_bytes, offset=4,
                    fmt='<i', target_count=target_count_extern,
                    src_count=src_extern)
            elif th == PTLIFE:
                entry_action_ref.init_ptlife_ref_props(
                    blk, data_bytes, target_play_map, target_count_play)
                _flag_if_cross_file_broken(
                    blk.efx_ptlife_ref, "relation_play_ptr",
                    "relation_pointerized", data_bytes, offset=8,
                    fmt='<h', target_count=target_count_play,
                    src_count=src_action)
            elif th == PTCOLLISION:
                entry_action_ref.init_ptcollision_ref_props(
                    blk, data_bytes, target_play_map, target_count_play)
                _flag_if_cross_file_broken(
                    blk.efx_ptcollision_ref, "ie_play_ptr",
                    "ie_pointerized", data_bytes, offset=96,
                    fmt='<i', target_count=target_count_play,
                    src_count=src_action)
        except Exception:
            # 单属性引用问题不阻断整个新增流程
            continue


def _flag_if_cross_file_broken(props, ptr_attr, pointerized_attr,
                               data_bytes, offset, fmt,
                               target_count, src_count) -> None:
    """
    判定并标记「真·跨文件断引用」。在对应 init 之后调用。

    - init 已成功指针化（pointerized==True，含指向目标/哨兵）→ 无需处理。
    - init 留 pointerized=False = 越界/死属性。借源计数区分：
        * 源有效（v < src_count）但目标越界（v >= target_count）
          → 真·跨文件断引用 → 标记悬空（pointerized=True, ptr=None），#4 校验列出。
        * 源也越界/死属性（v >= src_count）→ 不动，保持 verbatim（pointerized=False）。
    - 旧预设无源计数（src_count is None）/ 负值哨兵 / 字节不足 → 保持 init 行为。
    """
    import struct

    if getattr(props, pointerized_attr):
        return
    if src_count is None:
        return
    if len(data_bytes) < offset + struct.calcsize(fmt):
        return
    v = struct.unpack_from(fmt, data_bytes, offset)[0]
    if v < 0:
        return
    if v < src_count and v >= target_count:
        # 源有效但目标越界 → 悬空
        setattr(props, pointerized_attr, True)
        setattr(props, ptr_attr, None)
    # 否则（v >= src_count）→ 源也越界/死属性，保持 pointerized=False（verbatim）


def _build_attributes(io_tree, AttrBlock, attribute_list, entry_obj,
                  col_entry, raw_label) -> None:
    """从预设的 attributes 列表重建 AttrBlock 子对象（复用 io_tree 构建器）。"""
    attr_blocks = []
    for b in (attribute_list or []):
        try:
            th = int(b["type_hash"])
            db = io_tree._b64dec(b["data_bytes"])
        except (KeyError, ValueError, TypeError):
            continue
        attr_blocks.append(AttrBlock(type_hash=th, data_bytes=db))

    # 默认 extern 参数：v1 不跨文件指针化，属性 data_bytes 逐字保留为 raw。
    io_tree._build_attr_attribute_children(attr_blocks, entry_obj, col_entry, raw_label)


def _find_entry_collection(root_obj: bpy.types.Object):
    """
    找新增 entry 应落入的 Entry 集合：
      1. 优先：任一现有 EFX_ENTRY 子对象的 users_collection[0]。
      2. 回退：root_obj 集合树里名字以 "_2 Entry" 结尾的集合。
      3. 兜底：root_obj 的 users_collection[0]（保证对象可见）。
    """
    # 1. 现有 entry 所在集合
    for obj in bpy.data.objects:
        if obj.parent == root_obj and obj.get("~TYPE") == "EFX_ENTRY":
            cols = obj.users_collection
            if cols:
                return cols[0]

    # 2. root 集合树里找 "_2 Entry" 集合
    root_cols = list(root_obj.users_collection)
    visited = set()
    stack = list(root_cols)
    while stack:
        col = stack.pop()
        if col.name in visited:
            continue
        visited.add(col.name)
        if re.search(r'_2 Entry(\.\d+)?$', col.name):
            return col
        stack.extend(col.children)

    # 3. 兜底
    if root_cols:
        return root_cols[0]

    # 极端兜底：场景主集合
    return bpy.context.scene.collection


# ─────────────────────────────────────────────────────────────────────────────
# list_entry_presets
# ─────────────────────────────────────────────────────────────────────────────

def list_entry_presets():
    """
    扫 __entries__/*.json，返回 EnumProperty items 列表：
      [(完整路径, 文件名去.json, ""), ...]
    空目录返回 [("", "（无预设）", "")]。
    """
    preset_dir = _entries_preset_dir()
    result = []
    if os.path.isdir(preset_dir):
        from .presets import _encode_path_ident, _read_display_name
        for entry in sorted(os.scandir(preset_dir), key=lambda e: e.name):
            if entry.is_file() and entry.name.lower().endswith(".json"):
                # 显示名从 JSON 的 display_name 读（utf-8）；identifier 用 base64 路径
                display = _read_display_name(entry.path)
                result.append((_encode_path_ident(entry.path), display, ""))
    if not result:
        return [("", "（无预设）", "")]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 算子：保存 entry 预设
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_save_entry_preset(bpy.types.Operator):
    """把当前选中的 EFX_ENTRY（含属性）保存为整 entry 预设"""

    bl_idname      = "efx.save_entry_preset"
    bl_label       = "Save as Entry Preset"
    bl_description = "Save the current EFX_ENTRY's header fields and attribute list as a reusable entry preset"
    bl_options     = {"REGISTER"}

    preset_name: StringProperty(
        name="Preset Name",
        description="Saved preset file name (without .json)",
        default="my_entry",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ENTRY"

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            label = str(obj.get("efx_raw_label", "")).strip()
            self.preset_name = label or "my_entry"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        obj = context.active_object
        try:
            path = save_entry_preset(obj, self.preset_name)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to save entry preset: {exc}")
            return {"CANCELLED"}
        _invalidate_entry_preset_cache()
        self.report({"INFO"}, f"Saved entry preset: {os.path.basename(path)}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：从预设新增 entry
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_entry_from_preset(bpy.types.Operator):
    """按选中的 entry 预设，在 Active EFX 下新增一个 entry"""

    bl_idname      = "efx.add_entry_from_preset"
    bl_label       = "Add Entry"
    bl_description = "Create a new EFX_ENTRY (with attributes) from the selected entry preset; the exporter recomputes the header automatically"
    bl_options     = {"REGISTER", "UNDO"}

    preset_path: StringProperty(
        name="Preset Path",
        description="JSON path of the entry preset to add",
        default="",
    )

    @classmethod
    def poll(cls, context):
        root = get_active_efx_root(context)
        if root is None:
            if _HAS_POLL_MESSAGE_SET:
                cls.poll_message_set(
                    "No target EFX resolved: select the target file's collection in 'Active EFX' above, "
                    "or click any object belonging to it in the target file first"
                )
            return False
        return True

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "No target EFX resolved: set Active EFX above, or select an object in the target file first")
            return {"CANCELLED"}

        if not self.preset_path:
            self.report({"ERROR"}, "No entry preset selected")
            return {"CANCELLED"}

        from .presets import _decode_path_ident
        actual_path = _decode_path_ident(self.preset_path)
        try:
            new_obj = add_entry_from_preset(actual_path, root)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add entry: {exc}")
            return {"CANCELLED"}

        # 选中并激活新对象
        try:
            for o in context.selected_objects:
                o.select_set(False)
        except Exception:
            pass
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report({"INFO"}, f"Added entry: {new_obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：打开 entry 预设文件夹
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_open_entry_preset_folder(bpy.types.Operator):
    """打开 entry 预设所在文件夹（资源管理器 / Finder）"""

    bl_idname      = "efx.open_entry_preset_folder"
    bl_label       = "Open Entry Preset Folder"
    bl_description = "Open the __entries__ preset directory in the system file manager"
    bl_options     = {"REGISTER"}

    def execute(self, context):
        folder = _entries_preset_dir()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 复制 / 粘贴 Entry（内存剪贴板，会话级；快速搬 entry 而不必存预设）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级整-entry 剪贴板：build_entry_preset_dict 的结果（含 source_counts/in_eof）。
_ENTRY_CLIPBOARD = {}


class EFX_OT_copy_entry(bpy.types.Operator):
    """把当前 EFX_ENTRY（含所有属性）复制到内存剪贴板（供"粘贴Entry"快速新增）"""

    bl_idname      = "efx.copy_entry"
    bl_label       = "Copy Entry"
    bl_description = "Copy the current EFX_ENTRY (header fields + all attributes) to the in-memory clipboard"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ENTRY"

    def execute(self, context):
        global _ENTRY_CLIPBOARD
        try:
            _ENTRY_CLIPBOARD = build_entry_preset_dict(context.active_object)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to copy Entry: {exc}")
            return {"CANCELLED"}
        nblk = len(_ENTRY_CLIPBOARD.get("attributes", []))
        self.report({"INFO"}, f"Copied Entry ({nblk} attributes) to clipboard")
        return {"FINISHED"}


class EFX_OT_paste_entry(bpy.types.Operator):
    """把剪贴板的 Entry 粘贴（新增）到 Active EFX，不必另存预设"""

    bl_idname      = "efx.paste_entry"
    bl_label       = "Paste Entry"
    bl_description = "Add the whole entry from the clipboard to the Active EFX (with cross-file reference re-pointerization)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not _ENTRY_CLIPBOARD:
            if _HAS_POLL_MESSAGE_SET:
                cls.poll_message_set("Clipboard is empty — use Copy Entry first")
            return False
        if get_active_efx_root(context) is None:
            if _HAS_POLL_MESSAGE_SET:
                cls.poll_message_set(
                    "No target EFX resolved: select the target file's collection in 'Active EFX' above, "
                    "or click any object belonging to it in the target file first"
                )
            return False
        return True

    def execute(self, context):
        if not _ENTRY_CLIPBOARD:
            self.report({"ERROR"}, "Clipboard is empty (use Copy Entry first)")
            return {"CANCELLED"}
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "No target EFX resolved: set Active EFX above, or select an object in the target file first")
            return {"CANCELLED"}
        try:
            new_obj = add_entry_from_preset_dict(_ENTRY_CLIPBOARD, root)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to paste Entry: {exc}")
            return {"CANCELLED"}
        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_obj.select_set(True)
            context.view_layer.objects.active = new_obj
        except Exception:
            pass
        self.report({"INFO"}, f"Pasted Entry: {new_obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_save_entry_preset,
    EFX_OT_add_entry_from_preset,
    EFX_OT_open_entry_preset_folder,
    EFX_OT_copy_entry,
    EFX_OT_paste_entry,
)


def _active_efx_poll(self, col):
    """Scene.efx_active_efx 的 poll：仅允许选含 EFX_ROOT 对象的 EFX 文件集合。"""
    return any(o.get("~TYPE") == "EFX_ROOT" for o in col.objects)


# EnumProperty 动态回调缓存（GC 陷阱说明见 panels.py 顶部）。
# 脏标志 + 2 秒 TTL 双重机制：保存预设时立即失效；用户手动改文件夹后 2 秒内刷新。
_entry_preset_items_cache = [("", "（无预设）", "")]
_entry_preset_dirty = True        # 保存后置 True → 下次 redraw 立即重扫
_entry_preset_cache_time = 0.0    # 上次扫描时间戳
_ENTRY_CACHE_TTL = 2.0            # 秒


def _invalidate_entry_preset_cache():
    global _entry_preset_dirty
    _entry_preset_dirty = True


def _get_entry_preset_items(self, context):
    """WindowManager.efx_entry_preset_enum 的动态 items 回调（带缓存）。"""
    global _entry_preset_items_cache, _entry_preset_dirty, _entry_preset_cache_time
    now = time.monotonic()
    if _entry_preset_dirty or (now - _entry_preset_cache_time) > _ENTRY_CACHE_TTL:
        try:
            _entry_preset_items_cache = list_entry_presets()
        except Exception:
            _entry_preset_items_cache = [("", "（加载预设出错）", "")]
        _entry_preset_dirty = False
        _entry_preset_cache_time = now
    return _entry_preset_items_cache


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # Active EFX 选择器：挂在 Scene 上（场景级，随 .blend 保存）。
    # 选 EFX 文件**集合**（大纲里那个紫色 .efx 集合，比选 header 对象直观）；
    # 新增 entry / 导出都以它为目标。
    bpy.types.Scene.efx_active_efx = PointerProperty(
        name="Active EFX",
        description="The EFX file collection currently being operated on (target for adding entries / exporting)",
        type=bpy.types.Collection,
        poll=_active_efx_poll,
    )

    # entry 预设下拉：挂 WindowManager（会话级，不污染场景数据）。
    # SKIP_SAVE 避免把跨机器可能失效的路径字符串写入 .blend。
    bpy.types.WindowManager.efx_entry_preset_enum = EnumProperty(
        name="Entry Preset",
        description="Select the whole-entry preset to add",
        items=_get_entry_preset_items,
        options={"SKIP_SAVE"},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "efx_entry_preset_enum"):
        del bpy.types.WindowManager.efx_entry_preset_enum

    try:
        del bpy.types.Scene.efx_active_efx
    except AttributeError:
        pass

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
