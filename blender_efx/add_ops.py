"""
blender_efx/add_ops.py  —  L2 #3c：从「整 body 预设」新增 body + Active EFX 选择器

功能：
  - save_body_preset(body_obj, name)：把整个 body（头字段 + 块列表）存为 JSON 预设
  - add_body_from_preset(preset_path, root_obj)：按预设新建一个 EFX_BODY 对象树
  - list_body_presets()：扫 __bodies__/ 目录生成 EnumProperty items
  - 算子：efx.save_body_preset / efx.add_body_from_preset / efx.open_body_preset_folder
  - Scene.efx_active_efx：当前操作的 EFX 文件集合（新增 body / 导出目标，PointerProperty → Collection）
  - get_active_efx_root(context)：解析当前活动 EFX 根

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2），bpy 只用长期稳定子集
  - 包内相对导入；不改 efx_format/ 与 io_tree.py（仅复用其函数）
  - 新增 body 只需：建对象、设好 efx_index、置 root["labels_dirty"]=1，
    导出端会按实际内容自动重算 header 计数/size。
  - #3c 跨文件引用增强：从预设新增 body 时，对块内 EXTERNREFERENCE/PTLIFE/
    PTCOLLISION 三类引用重指针化到**目标文件**的段。目标范围内→指向目标对象；
    源有效但目标越界（真·跨文件断引用）→悬空（pointerized=True, ptr=None，由
    #4 校验报告供用户重连）；源也越界/死块→verbatim（pointerized=False，原样保留）。
    需预设记录源文件段计数（save_body_preset 写入 "source_counts"）。
  - body 头字段名与 io_tree.py 导入端（第 238-276 行）完全一致：
      standard：body_type / unkn0 / attr_count / null / timl_length / timl_bytes
      extended：body_type / unkn0 / null0 / null1 / unkn1 / unkn2 / attr_count /
                null2 / timl_length / timl_bytes
      root / unknown：raw
    （attr_count 仅作记录，新增时忽略——导出端按实际块数重算）

预设 JSON schema：
{
  "efx_preset_kind": "body",
  "body_kind": "standard",
  "props": {"body_type": "...", "unkn0": "...", ...},   # 除 timl_bytes 外的头字段（十进制字符串）
  "timl_bytes": "<b64>",
  "raw": "",                                            # root/unknown 才用
  "source_label": "原 raw_label（仅供默认命名，新增不进标签表）",
  "source_counts": {"extern": <int>, "body": <int>, "play": <int>},  # 源文件段计数（#3c 跨文件断引用判定）
  "blocks": [ {"type_hash": "<十进制str>", "data_bytes": "<b64>"}, ... ]
}
"""

import json
import os

import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty

from .presets import _presets_root


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

def _bodies_preset_dir() -> str:
    """返回 body 预设目录 presets/__bodies__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__bodies__")


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
    解析当前活动 EFX 根对象（供新增 body / 导出等用）。

    优先 scene.efx_active_efx（用户在 N 面板选的 EFX 文件**集合**）→ 取其内的 EFX_ROOT 对象；
    否则扫场景：若恰好有一个 EFX_ROOT 对象，返回它；
    否则返回 None（让用户显式选择）。
    """
    scn = getattr(context, "scene", None)
    if scn is not None:
        root = _root_obj_in_collection(getattr(scn, "efx_active_efx", None))
        if root is not None:
            return root

    roots = [o for o in bpy.data.objects if o.get("~TYPE") == "EFX_ROOT"]
    if len(roots) == 1:
        return roots[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# save_body_preset
# ─────────────────────────────────────────────────────────────────────────────

def save_body_preset(body_obj: bpy.types.Object, name: str) -> str:
    """
    把 body_obj（整个 body：头字段 + 块列表）存为 JSON 预设文件。

    参数
    ----
    body_obj : Object — ~TYPE == 'EFX_BODY' 的 Blender 对象
    name     : str    — 预设名称（不含 .json）

    返回
    ----
    str — 保存的 JSON 文件路径

    异常
    ----
    ValueError — 对象不是 EFX_BODY 或 name 非法
    """
    if (not name or "/" in name or "\\" in name or ":" in name
            or ".." in name):
        raise ValueError(f"save_body_preset：非法预设名称 {name!r}")

    preset = build_body_preset_dict(body_obj)

    save_dir = _bodies_preset_dir()
    os.makedirs(save_dir, exist_ok=True)
    json_path = os.path.join(save_dir, name + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=4)

    return json_path


def build_body_preset_dict(body_obj: bpy.types.Object) -> dict:
    """
    把 body_obj（整个 body：头字段 + 块列表）构建为 preset dict（不落盘）。
    供 save_body_preset（写文件）与 复制Body（内存剪贴板）共用。
    """
    if body_obj is None or body_obj.get("~TYPE") != "EFX_BODY":
        raise ValueError("build_body_preset_dict：目标对象不是 EFX_BODY")

    body_kind = str(body_obj.get("body_kind", "unknown"))

    preset = {
        "efx_preset_kind": "body",
        "body_kind": body_kind,
        "props": {},
        "timl_bytes": "",
        "raw": "",
        "source_label": str(body_obj.get("efx_raw_label", "")),
        "source_counts": _read_source_counts(body_obj),
        "in_eof": _is_body_in_eof(body_obj),
        "blocks": [],
    }

    if body_kind == "standard":
        for key in _STANDARD_PROP_KEYS:
            preset["props"][key] = str(body_obj.get(key, ""))
        preset["timl_bytes"] = str(body_obj.get("timl_bytes", ""))
        preset["blocks"] = _collect_block_dicts(body_obj)

    elif body_kind == "extended":
        for key in _EXTENDED_PROP_KEYS:
            preset["props"][key] = str(body_obj.get(key, ""))
        preset["timl_bytes"] = str(body_obj.get("timl_bytes", ""))
        preset["blocks"] = _collect_block_dicts(body_obj)

    else:
        # root / unknown：整段 raw（b64），无块子对象
        preset["raw"] = str(body_obj.get("raw", ""))

    return preset


def _collect_block_dicts(body_obj: bpy.types.Object) -> list:
    """
    收集 body_obj 的 EFX_BLOCK 子对象（按 efx_index 升序），
    每个存 {"type_hash": <十进制str>, "data_bytes": <b64>}。

    ⚠ data_bytes 用**导出端同款的字段感知解析**（io_tree._resolve_block_data_bytes）
    取当前实际字节——脏块按字段模型重打包、引用块按指针覆写——而非读
    obj["data_bytes"]（那是导入快照、不含用户编辑）。这样预设/复制Body 抓到的是修改后的值。
    源文件段局部 index 映射（按 efx_index 排序 enumerate）与导出一致，供引用覆写。
    """
    import base64
    from . import io_tree

    root = body_obj.parent  # EFX_ROOT

    def _localmap(type_tag):
        objs = [o for o in bpy.data.objects
                if o.parent == root and o.get("~TYPE") == type_tag]
        objs.sort(key=lambda o: int(o.get("efx_index", 0)))
        return {o: i for i, o in enumerate(objs)}

    extern_map = _localmap("EFX_EXTERN") if root is not None else {}
    body_map   = _localmap("EFX_BODY")   if root is not None else {}
    play_map   = _localmap("EFX_PLAY")   if root is not None else {}

    blocks = [o for o in bpy.data.objects
              if o.parent == body_obj and o.get("~TYPE") == "EFX_BLOCK"]
    blocks.sort(key=lambda o: int(o.get("efx_index", 0)))

    out = []
    for b in blocks:
        try:
            data = io_tree._resolve_block_data_bytes(b, extern_map, body_map, play_map)
        except Exception:
            # 回退：原始快照（至少不崩）
            data = base64.b64decode(str(b.get("data_bytes", "")))
        out.append({
            "type_hash": str(b.get("type_hash", "")),
            "data_bytes": base64.b64encode(data).decode("ascii"),
        })
    return out


def _read_source_counts(body_obj: bpy.types.Object) -> dict:
    """
    从 body_obj 的根对象（parent，~TYPE=='EFX_ROOT'）读出源文件段计数，
    用于 #3c 跨文件断引用判定（区分"源有效但目标越界"与"源也越界"）。

    根属性 hdr_count_extern / hdr_count_body / hdr_count_play 都是十进制字符串。
    取不到（防御）→ 该项存 0。
    """
    counts = {"extern": 0, "body": 0, "play": 0}
    root = body_obj.parent
    if root is None or root.get("~TYPE") != "EFX_ROOT":
        return counts
    for key, attr in (("extern", "hdr_count_extern"),
                      ("body", "hdr_count_body"),
                      ("play", "hdr_count_play")):
        try:
            counts[key] = int(str(root.get(attr)))
        except (ValueError, TypeError):
            counts[key] = 0
    return counts


def _is_body_in_eof(body_obj: bpy.types.Object) -> bool:
    """body_obj 的 efx_index 是否出现在所属 EFX_ROOT 的 efx_eof_list 中。"""
    root = body_obj.parent
    if root is None or root.get("~TYPE") != "EFX_ROOT":
        return False
    try:
        props = root.efx_eof_list
    except AttributeError:
        return False
    try:
        my_idx = int(body_obj.get("efx_index", -1))
    except (ValueError, TypeError):
        return False
    for item in props.items:
        if item.is_ptr and item.body_ptr == body_obj:
            return True
    return False


def _append_to_eof(root_obj: bpy.types.Object,
                   body_obj: bpy.types.Object) -> None:
    """向 root_obj.efx_eof_list 末尾追加一条指向 body_obj 的指针条目。"""
    try:
        props = root_obj.efx_eof_list
    except AttributeError:
        return
    item = props.items.add()
    item.is_ptr = True
    item.body_ptr = body_obj


# ─────────────────────────────────────────────────────────────────────────────
# add_body_from_preset
# ─────────────────────────────────────────────────────────────────────────────

def add_body_from_preset(preset_path: str,
                         root_obj: bpy.types.Object) -> bpy.types.Object:
    """
    按 body 预设新建一个 EFX_BODY 对象（含块子对象），挂到 root_obj 下。

    复用 io_tree 的构建逻辑，块 data_bytes 逐字保留为 raw（v1 不跨文件指针化）。
    新增后置 root_obj["labels_dirty"]=1，导出端按实际内容重算 header。

    参数
    ----
    preset_path : str    — body 预设 JSON 路径
    root_obj    : Object — 目标 EFX_ROOT 对象

    返回
    ----
    Object — 新建的 EFX_BODY 对象

    异常
    ----
    ValueError — 预设非法 / root_obj 无效 / 读取失败
    """
    if root_obj is None or root_obj.get("~TYPE") != "EFX_ROOT":
        raise ValueError("add_body_from_preset：root_obj 不是 EFX_ROOT")

    # ── 读 JSON ────────────────────────────────────────────────────────────────
    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            preset = json.load(f)
    except Exception as exc:
        raise ValueError(f"add_body_from_preset：读取预设失败：{exc}")

    return add_body_from_preset_dict(preset, root_obj)


def add_body_from_preset_dict(preset: dict,
                              root_obj: bpy.types.Object) -> bpy.types.Object:
    """
    按 preset dict 新建 body（add_body_from_preset 的核心；供文件版与"粘贴Body"内存版共用）。
    """
    from . import io_tree
    from ..efx_format.efxfile import AttrBlock

    if root_obj is None or root_obj.get("~TYPE") != "EFX_ROOT":
        raise ValueError("add_body_from_preset_dict：root_obj 不是 EFX_ROOT")
    if preset.get("efx_preset_kind") != "body":
        raise ValueError("add_body_from_preset_dict：不是 body 预设（efx_preset_kind != 'body'）")

    body_kind = str(preset.get("body_kind", "unknown"))
    source_label = str(preset.get("source_label", ""))

    # ── 找目标 Main 集合 ──────────────────────────────────────────────────────
    col_main = _find_main_collection(root_obj)

    # ── 计算新 efx_index = 现有 body 最大 index + 1 ───────────────────────────
    max_idx = -1
    for obj in bpy.data.objects:
        if obj.parent == root_obj and obj.get("~TYPE") == "EFX_BODY":
            try:
                max_idx = max(max_idx, int(obj.get("efx_index", 0)))
            except (ValueError, TypeError):
                pass
    new_index = max_idx + 1

    # ── 建 body 对象 ──────────────────────────────────────────────────────────
    nn = str(new_index).zfill(2) if new_index < 100 else str(new_index)
    raw_label = source_label or f"body_{new_index}"
    display_name = f"{nn} {source_label or 'body'}"
    body_obj = io_tree._new_empty(display_name, col_main)

    body_obj["~TYPE"]         = "EFX_BODY"
    body_obj["efx_index"]     = new_index
    body_obj["efx_raw_label"] = raw_label
    body_obj["efx_has_label"] = 0           # 先置 0；下方在安全时提升
    body_obj["body_kind"]     = body_kind
    body_obj.parent           = root_obj

    # 若预设源 body 有名字、且追加位置处于标签前缀边界（前面条目全有标签），
    # 给新 body 一个真正的标签槽——名字才能持久化、也可被重命名。
    # 否则（文件本身有无标签 body）保持 has_label=0（名字仅 Blender 显示，不进文件）。
    if source_label:
        try:
            from .reorder import can_label_body
            if can_label_body(body_obj):
                body_obj["efx_has_label"] = 1
        except Exception:
            pass

    props = preset.get("props", {}) or {}

    if body_kind == "standard":
        for key in _STANDARD_PROP_KEYS:
            body_obj[key] = str(props.get(key, "0"))
        body_obj["timl_bytes"] = str(preset.get("timl_bytes", ""))
        _build_blocks(io_tree, AttrBlock, preset.get("blocks", []),
                      body_obj, col_main, raw_label)

    elif body_kind == "extended":
        for key in _EXTENDED_PROP_KEYS:
            body_obj[key] = str(props.get(key, "0"))
        body_obj["timl_bytes"] = str(preset.get("timl_bytes", ""))
        _build_blocks(io_tree, AttrBlock, preset.get("blocks", []),
                      body_obj, col_main, raw_label)

    else:
        # root / unknown：整段 raw（b64）
        body_obj["raw"] = str(preset.get("raw", ""))

    # #3c 跨文件引用重指针化：把新增 body 内块的段局部引用重指向目标文件的段。
    if body_kind in ("standard", "extended"):
        _repointerize_refs(preset, body_obj, root_obj)

    # 若源 body 在源文件 eof 中，将新 body 追加到目标文件 eof 列表
    if preset.get("in_eof"):
        _append_to_eof(root_obj, body_obj)

    # body 数量变化 → 标签表变 → 触发导出端重算
    root_obj["labels_dirty"] = 1

    return body_obj


def _repointerize_refs(preset: dict,
                       body_obj: bpy.types.Object,
                       root_obj: bpy.types.Object) -> None:
    """
    对刚新增 body（body_obj）下的引用块（EXTERNREFERENCE/PTLIFE/PTCOLLISION），
    按**目标文件**（root_obj）的段重新指针化。

    复用 extern_ref / body_play_ref 的 init 函数（不修改它们）：
      - 目标范围内 → init 已指向目标对象（pointerized=True）。
      - 哨兵 -1     → init 已设 none（pointerized=True）。
      - init 留 pointerized=False = 越界/死块；再用 _flag_if_cross_file_broken
        借源计数区分"源有效但目标越界（→悬空）"与"源也越界（→verbatim）"。

    包一层 try/except：任何块异常都安全跳过，保证新增不因引用问题失败。
    """
    from . import io_tree
    from . import extern_ref, body_play_ref
    from ..efx_format.hashes import EXTERNREFERENCE, PTLIFE, PTCOLLISION

    # 1. 构建目标文件的段映射（按 efx_index）+ 计数
    target_extern_map = {}
    target_body_map = {}
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
        elif t == "EFX_BODY":
            target_body_map[idx] = obj
        elif t == "EFX_PLAY":
            target_play_map[idx] = obj

    target_count_extern = len(target_extern_map)
    target_count_body = len(target_body_map)
    target_count_play = len(target_play_map)

    # 2. 源计数（旧预设无此键 → 各项 None → 跳过 override，保持 init 行为）
    sc = preset.get("source_counts") or {}
    src_extern = sc.get("extern")
    src_body = sc.get("body")
    src_play = sc.get("play")

    # 3. 遍历刚新增 body 下的 EFX_BLOCK 子对象
    for blk in bpy.data.objects:
        if blk.parent is not body_obj or blk.get("~TYPE") != "EFX_BLOCK":
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
                body_play_ref.init_ptlife_ref_props(
                    blk, data_bytes, target_body_map, target_count_body)
                _flag_if_cross_file_broken(
                    blk.efx_ptlife_ref, "relation_body_ptr",
                    "relation_pointerized", data_bytes, offset=8,
                    fmt='<h', target_count=target_count_body,
                    src_count=src_body)
            elif th == PTCOLLISION:
                body_play_ref.init_ptcollision_ref_props(
                    blk, data_bytes, target_play_map, target_count_play)
                _flag_if_cross_file_broken(
                    blk.efx_ptcollision_ref, "ie_play_ptr",
                    "ie_pointerized", data_bytes, offset=96,
                    fmt='<i', target_count=target_count_play,
                    src_count=src_play)
        except Exception:
            # 单块引用问题不阻断整个新增流程
            continue


def _flag_if_cross_file_broken(props, ptr_attr, pointerized_attr,
                               data_bytes, offset, fmt,
                               target_count, src_count) -> None:
    """
    判定并标记「真·跨文件断引用」。在对应 init 之后调用。

    - init 已成功指针化（pointerized==True，含指向目标/哨兵）→ 无需处理。
    - init 留 pointerized=False = 越界/死块。借源计数区分：
        * 源有效（v < src_count）但目标越界（v >= target_count）
          → 真·跨文件断引用 → 标记悬空（pointerized=True, ptr=None），#4 校验列出。
        * 源也越界/死块（v >= src_count）→ 不动，保持 verbatim（pointerized=False）。
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
    # 否则（v >= src_count）→ 源也越界/死块，保持 pointerized=False（verbatim）


def _build_blocks(io_tree, AttrBlock, block_list, body_obj,
                  col_main, raw_label) -> None:
    """从预设的 blocks 列表重建 AttrBlock 子对象（复用 io_tree 构建器）。"""
    attr_blocks = []
    for b in (block_list or []):
        try:
            th = int(b["type_hash"])
            db = io_tree._b64dec(b["data_bytes"])
        except (KeyError, ValueError, TypeError):
            continue
        attr_blocks.append(AttrBlock(type_hash=th, data_bytes=db))

    # 默认 extern 参数：v1 不跨文件指针化，块 data_bytes 逐字保留为 raw。
    io_tree._build_attr_block_children(attr_blocks, body_obj, col_main, raw_label)


def _find_main_collection(root_obj: bpy.types.Object):
    """
    找新增 body 应落入的 Main 集合：
      1. 优先：任一现有 EFX_BODY 子对象的 users_collection[0]。
      2. 回退：root_obj 集合树里名字以 "_2 Main" 结尾的集合。
      3. 兜底：root_obj 的 users_collection[0]（保证对象可见）。
    """
    # 1. 现有 body 所在集合
    for obj in bpy.data.objects:
        if obj.parent == root_obj and obj.get("~TYPE") == "EFX_BODY":
            cols = obj.users_collection
            if cols:
                return cols[0]

    # 2. root 集合树里找 "_2 Main" 集合
    root_cols = list(root_obj.users_collection)
    visited = set()
    stack = list(root_cols)
    while stack:
        col = stack.pop()
        if col.name in visited:
            continue
        visited.add(col.name)
        if col.name.endswith("_2 Main"):
            return col
        stack.extend(col.children)

    # 3. 兜底
    if root_cols:
        return root_cols[0]

    # 极端兜底：场景主集合
    return bpy.context.scene.collection


# ─────────────────────────────────────────────────────────────────────────────
# list_body_presets
# ─────────────────────────────────────────────────────────────────────────────

def list_body_presets():
    """
    扫 __bodies__/*.json，返回 EnumProperty items 列表：
      [(完整路径, 文件名去.json, ""), ...]
    空目录返回 [("", "（无预设）", "")]。
    """
    preset_dir = _bodies_preset_dir()
    result = []
    if os.path.isdir(preset_dir):
        for entry in sorted(os.scandir(preset_dir), key=lambda e: e.name):
            if entry.is_file() and entry.name.lower().endswith(".json"):
                display = os.path.splitext(entry.name)[0]
                from .presets import _encode_path_ident
                result.append((_encode_path_ident(entry.path), display, ""))
    if not result:
        return [("", "（无预设）", "")]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 算子：保存 body 预设
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_save_body_preset(bpy.types.Operator):
    """把当前选中的 EFX_BODY（含块）保存为整 body 预设"""

    bl_idname      = "efx.save_body_preset"
    bl_label       = "保存为 Body 预设"
    bl_description = "把当前 EFX_BODY 的头字段与块列表保存为可复用的 body 预设"
    bl_options     = {"REGISTER"}

    preset_name: StringProperty(
        name="预设名称",
        description="保存的预设文件名（不含 .json）",
        default="my_body",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            label = str(obj.get("efx_raw_label", "")).strip()
            self.preset_name = label or "my_body"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        obj = context.active_object
        try:
            path = save_body_preset(obj, self.preset_name)
        except Exception as exc:
            self.report({"ERROR"}, f"保存 body 预设失败：{exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已保存 body 预设：{os.path.basename(path)}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：从预设新增 body
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_body_from_preset(bpy.types.Operator):
    """按选中的 body 预设，在 Active EFX 下新增一个 body"""

    bl_idname      = "efx.add_body_from_preset"
    bl_label       = "新增 Body"
    bl_description = "按选中的 body 预设新建一个 EFX_BODY（含块），导出端自动重算 header"
    bl_options     = {"REGISTER", "UNDO"}

    preset_path: StringProperty(
        name="预设路径",
        description="要新增的 body 预设 JSON 路径",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "请先在 EFX 工具区选择 Active EFX 集合")
            return {"CANCELLED"}

        if not self.preset_path:
            self.report({"ERROR"}, "未选择 body 预设")
            return {"CANCELLED"}

        from .presets import _decode_path_ident
        actual_path = _decode_path_ident(self.preset_path)
        try:
            new_obj = add_body_from_preset(actual_path, root)
        except Exception as exc:
            self.report({"ERROR"}, f"新增 body 失败：{exc}")
            return {"CANCELLED"}

        # 选中并激活新对象
        try:
            for o in context.selected_objects:
                o.select_set(False)
        except Exception:
            pass
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report({"INFO"}, f"已新增 body：{new_obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：打开 body 预设文件夹
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_open_body_preset_folder(bpy.types.Operator):
    """打开 body 预设所在文件夹（资源管理器 / Finder）"""

    bl_idname      = "efx.open_body_preset_folder"
    bl_label       = "打开 Body 预设文件夹"
    bl_description = "在系统文件管理器中打开 __bodies__ 预设目录"
    bl_options     = {"REGISTER"}

    def execute(self, context):
        folder = _bodies_preset_dir()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 复制 / 粘贴 Body（内存剪贴板，会话级；快速搬 body 而不必存预设）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级整-body 剪贴板：build_body_preset_dict 的结果（含 source_counts/in_eof）。
_BODY_CLIPBOARD = {}


class EFX_OT_copy_body(bpy.types.Operator):
    """把当前 EFX_BODY（含所有块）复制到内存剪贴板（供"粘贴Body"快速新增）"""

    bl_idname      = "efx.copy_body"
    bl_label       = "复制 Body"
    bl_description = "把当前 EFX_BODY（头字段 + 所有块）复制到内存剪贴板"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def execute(self, context):
        global _BODY_CLIPBOARD
        try:
            _BODY_CLIPBOARD = build_body_preset_dict(context.active_object)
        except Exception as exc:
            self.report({"ERROR"}, f"复制 Body 失败：{exc}")
            return {"CANCELLED"}
        nblk = len(_BODY_CLIPBOARD.get("blocks", []))
        self.report({"INFO"}, f"已复制 Body（{nblk} 块）到剪贴板")
        return {"FINISHED"}


class EFX_OT_paste_body(bpy.types.Operator):
    """把剪贴板的 Body 粘贴（新增）到 Active EFX，不必另存预设"""

    bl_idname      = "efx.paste_body"
    bl_label       = "粘贴 Body"
    bl_description = "把剪贴板里的整 body 新增到 Active EFX（含跨文件引用重指针化）"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_BODY_CLIPBOARD) and get_active_efx_root(context) is not None

    def execute(self, context):
        if not _BODY_CLIPBOARD:
            self.report({"ERROR"}, "剪贴板为空（先用“复制 Body”）")
            return {"CANCELLED"}
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "未指定 Active EFX 集合")
            return {"CANCELLED"}
        try:
            new_obj = add_body_from_preset_dict(_BODY_CLIPBOARD, root)
        except Exception as exc:
            self.report({"ERROR"}, f"粘贴 Body 失败：{exc}")
            return {"CANCELLED"}
        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_obj.select_set(True)
            context.view_layer.objects.active = new_obj
        except Exception:
            pass
        self.report({"INFO"}, f"已粘贴 Body：{new_obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_save_body_preset,
    EFX_OT_add_body_from_preset,
    EFX_OT_open_body_preset_folder,
    EFX_OT_copy_body,
    EFX_OT_paste_body,
)


def _active_efx_poll(self, col):
    """Scene.efx_active_efx 的 poll：仅允许选含 EFX_ROOT 对象的 EFX 文件集合。"""
    return any(o.get("~TYPE") == "EFX_ROOT" for o in col.objects)


# 同 panels.py _block_preset_items_cache：对同一 list 对象原地修改防止 GC 乱码
_body_preset_items_cache = [("", "（无预设）", "")]


def _get_body_preset_items(self, context):
    """WindowManager.efx_body_preset_enum 的动态 items 回调。"""
    try:
        items = list_body_presets()
        _body_preset_items_cache.clear()
        _body_preset_items_cache.extend(items)
        return _body_preset_items_cache
    except Exception:
        _body_preset_items_cache.clear()
        _body_preset_items_cache.extend([("", "（加载预设出错）", "")])
        return _body_preset_items_cache


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # Active EFX 选择器：挂在 Scene 上（场景级，随 .blend 保存）。
    # 选 EFX 文件**集合**（大纲里那个紫色 .efx 集合，比选 header 对象直观）；
    # 新增 body / 导出都以它为目标。
    bpy.types.Scene.efx_active_efx = PointerProperty(
        name="Active EFX",
        description="当前操作的 EFX 文件集合（新增 body / 导出的目标）",
        type=bpy.types.Collection,
        poll=_active_efx_poll,
    )

    # body 预设下拉：挂 WindowManager（会话级，不污染场景数据）。
    # SKIP_SAVE 避免把跨机器可能失效的路径字符串写入 .blend。
    bpy.types.WindowManager.efx_body_preset_enum = EnumProperty(
        name="Body 预设",
        description="选择要新增的整 body 预设",
        items=_get_body_preset_items,
        options={"SKIP_SAVE"},
    )

    # 统一「预设」面板的模式切换：块预设 / Body 预设。
    bpy.types.WindowManager.efx_preset_mode = EnumProperty(
        name="预设模式",
        description="切换块字段预设 / 整 body 预设",
        items=[
            ("BLOCK", "块预设", "块字段值的复制/粘贴与预设"),
            ("BODY",  "Body 预设", "整 body 的复制/粘贴与预设"),
        ],
        default="BLOCK",
        options={"SKIP_SAVE"},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "efx_preset_mode"):
        del bpy.types.WindowManager.efx_preset_mode
    if hasattr(bpy.types.WindowManager, "efx_body_preset_enum"):
        del bpy.types.WindowManager.efx_body_preset_enum

    try:
        del bpy.types.Scene.efx_active_efx
    except AttributeError:
        pass

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
