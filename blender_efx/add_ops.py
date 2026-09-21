"""Entry 预设与活动 EFX 目标选择。

维护约束：
- 段引用按目标 EFX 解析；source_counts 区分待重连的越界引用与原样保留的值。
- 预设头字段与导入端一致，attr_count 仅作记录，导出时按实际属性重算。
- 兼容预设只从 __bodies__ 读取并规范化；新预设只能写入 __entries__。
- 属性字节从导出侧字段解析取得，不能直接使用导入快照。
"""

import json
import os
import time

import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty

from .presets import _presets_root
from . import root_collection as _rc

# poll_message_set 是 4.0+ API（3.6 上不存在），用于给禁用状态的按钮显示原因提示。
_HAS_POLL_MESSAGE_SET = hasattr(bpy.types.Operator, "poll_message_set")


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

def _archetypes_preset_dir() -> str:
    """
    返回 archetype 模板目录 presets/__archetypes__/ 的绝对路径。

    该目录只放随扩展分发的模板；用户保存的预设必须写入 __entries__，以免升级覆盖。
    """
    return os.path.join(_presets_root(), "__archetypes__")


def _entries_preset_dir() -> str:
    """返回用户 entry 预设目录 presets/__entries__/ 的绝对路径（保存目标）。"""
    return os.path.join(_presets_root(), "__entries__")


def _bodies_preset_dir_legacy() -> str:
    """
    返回旧 entry 预设目录 presets/__bodies__/ 的绝对路径（只读兼容）。

    枚举时仍扫描该目录，并在载入时规范化旧 schema；新预设一律写入 __entries__。
    """
    return os.path.join(_presets_root(), "__bodies__")


# 预设头字段须与导入端保持一致；attr_count 由导出端按实际属性重算。
_STANDARD_PROP_KEYS = ("body_type", "unkn0", "attr_count", "null", "timl_length")
_EXTENDED_PROP_KEYS = (
    "body_type", "unkn0", "null0", "null1", "unkn1", "unkn2",
    "attr_count", "null2", "timl_length",
)


# ─────────────────────────────────────────────────────────────────────────────
# Active EFX root helper
# ─────────────────────────────────────────────────────────────────────────────

def get_active_efx_root(context):
    """
    优先使用显式目标，其次使用活动对象所在根；仅有一个根时才自动选取，
    歧义时返回 None，以避免跨文件操作落到错误目标。
    """
    scn = getattr(context, "scene", None)
    if scn is not None:
        active = getattr(scn, "efx_active_efx", None)
        if _rc.is_root_collection(active):
            return active

    try:
        from .operators import _find_efx_root
        root = _find_efx_root(context)
        if root is not None:
            return root
    except Exception:
        pass

    roots = _rc.all_root_collections()
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
    """磁盘预设和会话剪贴板共用的唯一 Entry 序列化路径。"""
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
    使用与导出端相同的字段解析取得当前字节，而非导入快照，
    以保留字段编辑和引用覆写。局部段索引也须与导出顺序一致。
    """
    import base64
    from . import io_tree

    root = _rc.find_root_collection(entry_obj)  # 顶层文件集合

    def _localmap(type_tag):
        objs = _rc.collect_top_level(root, type_tag)
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
    从 entry_obj 所属的根集合读出源文件段计数，
    用于 #3c 跨文件断引用判定（区分"源有效但目标越界"与"源也越界"）。

    根属性 hdr_count_extern / hdr_count_body / hdr_count_play 都是十进制字符串。
    取不到（防御）→ 该项存 0。
    """
    counts = {"extern": 0, "entry": 0, "action": 0}
    root = _rc.find_root_collection(entry_obj)
    if root is None:
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
    """entry_obj 是否在所属 EFX_ROOT 的 eof 直接触发集中（模型无关，委托 entry_action_ref）。"""
    try:
        from . import entry_action_ref
        return entry_action_ref.is_entry_in_eof(entry_obj)
    except Exception:
        return False


def _normalize_legacy_entry_preset(preset: dict) -> dict:
    """
    兼容 3.0 重命名前的旧 entry 预设 schema（efx_preset_kind == "body"，来自
    presets/__bodies__/）：把旧 key 名规整成当前 schema，使 add_entry_from_preset_dict
    余下的逻辑不必关心新旧格式差异。已是新 schema（efx_preset_kind == "entry"）或
    不认识的格式原样返回。

    旧→新 key 对照（值本身不变，只是 key 名跟着 3.0 重命名走）：
      efx_preset_kind: "body" → "entry"
      body_kind        → entry_kind
      blocks           → attributes
      source_counts.body/play → source_counts.entry/action
    """
    if preset.get("efx_preset_kind") != "body":
        return preset
    out = dict(preset)
    out["efx_preset_kind"] = "entry"
    if "body_kind" in out:
        out["entry_kind"] = out.pop("body_kind")
    if "blocks" in out:
        out["attributes"] = out.pop("blocks")
    sc = out.get("source_counts")
    if isinstance(sc, dict):
        new_sc = dict(sc)
        if "body" in new_sc:
            new_sc["entry"] = new_sc.pop("body")
        if "play" in new_sc:
            new_sc["action"] = new_sc.pop("play")
        out["source_counts"] = new_sc
    return out


# ─────────────────────────────────────────────────────────────────────────────
# add_entry_from_preset
# ─────────────────────────────────────────────────────────────────────────────

def add_entry_from_preset(preset_path: str,
                         root_obj: bpy.types.Collection) -> bpy.types.Object:
    """
    按 entry 预设新建一个 EFX_ENTRY 对象（含属性子对象），归属 root_obj 文件集合。

    复用 io_tree 的构建逻辑，属性 data_bytes 逐字保留为 raw（v1 不跨文件指针化）。
    新增后置 root_obj["labels_dirty"]=1，导出端按实际内容重算 header。

    参数
    ----
    preset_path : str    — entry 预设 JSON 路径
    root_obj    : Collection — 目标 EFX_ROOT 顶层文件集合

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
                              root_obj: bpy.types.Collection) -> bpy.types.Object:
    """
    按 preset dict 新建 entry（add_entry_from_preset 的核心；供文件版与"粘贴Entry"内存版共用）。

    自动兼容 __bodies__/ 里的旧 schema 预设（efx_preset_kind == "body"），
    见 _normalize_legacy_entry_preset。
    """
    from . import io_tree
    from ..efx_format.efxfile import AttrBlock

    preset = _normalize_legacy_entry_preset(preset)

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
    for obj in _rc.collect_top_level(root_obj, "EFX_ENTRY"):
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
    # 归属靠 col_entry（其 efx_root_ptr 指回 root_obj），不再额外 parent 到 ROOT

    # 若预设源 entry 有名字、且追加位置处于标签前缀边界（前面条目全有标签），
    # 给新 entry 一个真正的标签槽——名字才能持久化、也可被重命名。
    # 否则（文件本身有无标签 entry）保持 has_label=0（名字仅 Blender 显示）。
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
        # 咽喉点：从预设写 TIML（新建/替换）→ 写字节 + 建句柄 + 从新字节建持久 fcurve
        import base64 as _b64
        from . import timl_edit as _te
        _te.set_entry_timl(entry_obj, _b64.b64decode(str(preset.get("timl_bytes", "")) or ""))
        _build_attributes(io_tree, AttrBlock, preset.get("attributes", []),
                      entry_obj, col_entry, raw_label)

    elif entry_kind == "extended":
        for key in _EXTENDED_PROP_KEYS:
            entry_obj[key] = str(props.get(key, "0"))
        # 咽喉点：从预设写 TIML（新建/替换）→ 写字节 + 建句柄 + 从新字节建持久 fcurve
        import base64 as _b64
        from . import timl_edit as _te
        _te.set_entry_timl(entry_obj, _b64.b64decode(str(preset.get("timl_bytes", "")) or ""))
        _build_attributes(io_tree, AttrBlock, preset.get("attributes", []),
                      entry_obj, col_entry, raw_label)

    else:
        # root：尝试跟 io_tree 导入端同一套逻辑拆成 AttrBlock 子对象
        # （UnitBoundary/RenderTarget/LayoutBank 伪装成属性，可见、可删）；
        # 拆不动（非 root 或数据本身就不合法）才退回整段 raw 只读存底。
        raw_str = str(preset.get("raw", ""))
        decomposed = False
        if entry_kind == "root" and raw_str:
            try:
                from ..efx_format.efxfile import EFXFile
                raw_bytes = io_tree._b64dec(raw_str)
                body, end_pos = EFXFile._parse_root_body(raw_bytes, 0)
                if end_pos == len(raw_bytes):
                    attr_blocks = [io_tree._root_entry_to_attr_block(e) for e in body.entries]
                    io_tree._build_attr_attribute_children(attr_blocks, entry_obj, col_entry, raw_label)
                    decomposed = True
            except Exception:
                decomposed = False
        if not decomposed:
            entry_obj["raw"] = raw_str

    # #3c 跨文件引用重指针化：把新增 entry 内属性的段局部引用重指向目标文件的段。
    if entry_kind in ("standard", "extended"):
        _repointerize_refs(preset, entry_obj, root_obj)

    # 按源 entry 在源文件里的 eof 状态，把新 entry 分流进目标文件对应的子集合
    # （per_entry 模型：Direct Trigger / Not Direct Trigger 二选一；opaque 不动）。
    from . import entry_action_ref
    entry_action_ref.place_new_entry(root_obj, entry_obj, bool(preset.get("in_eof")))

    # entry 数量变化 → 标签表变 → 触发导出端重算
    root_obj["labels_dirty"] = 1

    return entry_obj


def _repointerize_refs(preset: dict,
                       entry_obj: bpy.types.Object,
                       root_obj: bpy.types.Collection) -> None:
    """
    按目标文件的段重建引用属性。源计数用于将跨文件越界引用标为悬空，
    而将源中已无效的值保持原样。
    """
    from . import io_tree
    from . import extern_ref, entry_action_ref
    from ..efx_format.hashes import EXTERNREFERENCE, PTLIFE, PTCOLLISION

    # 1. 构建目标文件的段映射（按 efx_index）+ 计数
    def _idx_map(type_tag):
        out = {}
        for obj in _rc.collect_top_level(root_obj, type_tag):
            try:
                out[int(obj.get("efx_index", 0))] = obj
            except (ValueError, TypeError):
                pass
        return out

    target_extern_map = _idx_map("EFX_EXTERN")
    target_entry_map = _idx_map("EFX_ENTRY")
    target_play_map = _idx_map("EFX_ACTION")

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
            elif th == PTCOLLISION:
                entry_action_ref.init_ptcollision_ref_props(
                    blk, data_bytes, target_play_map, target_count_play)
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


def _find_entry_collection(root_obj: bpy.types.Collection):
    """按类型定位目标根的 Entry 叶子集合；缺失时回退到场景主集合。"""
    col = _rc.get_leaf_collection(root_obj, "EFX_ENTRY")
    if col is not None:
        return col
    return bpy.context.scene.collection


# ─────────────────────────────────────────────────────────────────────────────
# list_entry_presets
# ─────────────────────────────────────────────────────────────────────────────

def list_entry_presets():
    """
    返回按内置模板、分发模板、用户预设和兼容预设排序的 EnumProperty items。
    """
    from .presets import _encode_path_ident, _read_display_name
    from .i18n import T
    from . import builtin_entries

    # 零属性模板不显示计数后缀。
    result = [(ident, ("%s (%d)" % (T(key), n)) if n else T(key), "")
              for ident, key, n in builtin_entries.items()]
    for preset_dir in (_archetypes_preset_dir(),
                       _entries_preset_dir(),
                       _bodies_preset_dir_legacy()):
        if not os.path.isdir(preset_dir):
            continue
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
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to save entry preset. See the system console for details.")
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

        from . import builtin_entries
        try:
            if builtin_entries.is_builtin(self.preset_path):
                new_obj = add_entry_from_preset_dict(
                    builtin_entries.get(self.preset_path), root)
            else:
                from .presets import _decode_path_ident
                new_obj = add_entry_from_preset(
                    _decode_path_ident(self.preset_path), root)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add entry from preset. See the system console for details.")
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
# 复制 / 粘贴 Entry
# ─────────────────────────────────────────────────────────────────────────────

# 模块级整-entry 剪贴板：build_entry_preset_dict 的结果，不随 .blend 保存。
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
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to copy this entry. See the system console for details.")
            return {"CANCELLED"}
        nblk = len(_ENTRY_CLIPBOARD.get("attributes", []))
        self.report({"INFO"}, f"Copied Entry ({nblk} attributes) to clipboard")
        return {"FINISHED"}


class EFX_OT_paste_entry(bpy.types.Operator):
    """把剪贴板的 Entry 粘贴（新增）到 Active EFX"""

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
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to paste this entry. See the system console for details.")
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
    """Scene.efx_active_efx 的 poll：仅允许选顶层 EFX 文件集合本身（~TYPE==EFX_ROOT）。"""
    return _rc.is_root_collection(col)


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

    # 在播种包内预设后，只清理逐字节一致的内置副本，保留用户修改。
    try:
        from . import builtin_entries
        builtin_entries.purge_superseded_copies(_presets_root())
    except Exception:
        pass  # 清理失败最多多几个重复项，不该拦住插件启用

    # 场景级目标必须是 EFX 文件集合，供新增和导出共用。
    bpy.types.Scene.efx_active_efx = PointerProperty(
        name="Active EFX",
        description="The EFX file collection currently being operated on (target for adding entries / exporting)",
        type=bpy.types.Collection,
        poll=_active_efx_poll,
    )

    # 预设标识包含路径，故只保留在会话中，避免写入 .blend。
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
