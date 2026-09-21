"""属性预设的序列化、保存、选择与插入。

维护约束：
- 属性字节必须通过 io_tree 的导出侧解析取得，不能使用导入快照。
- 新属性按规范顺序插入；导出端按实际属性重算 attr_count。
- category/subgroup 是类型元数据，不决定用户预设的位置；用户预设只写入 custom 目录。
"""

import base64
import json
import os
import time

import bpy
from bpy.props import EnumProperty, StringProperty

from .presets import _presets_root, _unique_ascii_filename, _read_display_name, _encode_path_ident, _decode_path_ident
from ..efx_format.categories import (
    category_of, subgroup_of, category_label, ATTRIBUTE_CATEGORY_LABELS, ATTRIBUTE_SUBGROUP_LABELS,
)
from . import i18n
from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

# UI 子组排序基准。
_SUBGROUP_ORDER = list(ATTRIBUTE_SUBGROUP_LABELS)


def _attribute_preset_dir() -> str:
    """返回属性预设根目录 presets/__attributes__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__attributes__")


def _attribute_category_dir(slug: str) -> str:
    """返回某分类的属性预设子目录 presets/__attributes__/<slug>/。"""
    return os.path.join(_attribute_preset_dir(), slug)


def _iter_preset_files(category_dir: str) -> list:
    """返回分类目录内的预设文件及其一级子组，按 UI 子组顺序和文件名排序。"""
    items = []
    if not os.path.isdir(category_dir):
        return items
    for dirpath, _dirs, files in os.walk(category_dir):
        rel = os.path.relpath(dirpath, category_dir)
        subgroup = "" if rel == "." else rel.split(os.sep)[0]
        for fname in files:
            if fname.lower().endswith(".json"):
                items.append((os.path.join(dirpath, fname), subgroup))

    def _rank(item):
        path, subgroup = item
        if not subgroup:
            order = -1
        elif subgroup in _SUBGROUP_ORDER:
            order = _SUBGROUP_ORDER.index(subgroup)
        else:
            order = len(_SUBGROUP_ORDER)
        return (order, os.path.basename(path).lower())

    items.sort(key=_rank)
    return items


def _preset_display_item(path: str) -> tuple:
    """读取单个预设 JSON，返回 EnumProperty item 元组 (_encode_path_ident(path), label, type_name)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        type_name = d.get("type_name", "")
        stored_display = d.get("display_name", "")
    except Exception:
        type_name, stored_display = "", ""
    # 自动名按当前语言显示；用户自定义名保持原样。
    if type_name and _is_autogen_name(stored_display, type_name):
        label = i18n.type_label(type_name)
    else:
        label = stored_display or _read_display_name(path)
    return (_encode_path_ident(path), label, type_name)


# ─────────────────────────────────────────────────────────────────────────────
# build_attribute_preset_dict / save_attribute_preset
# ─────────────────────────────────────────────────────────────────────────────

def build_attribute_preset_dict(blk_obj: bpy.types.Object) -> dict:
    """磁盘预设和会话剪贴板共用的属性序列化路径。"""
    if blk_obj is None or blk_obj.get("~TYPE") != "EFX_ATTRIBUTE":
        raise ValueError("build_attribute_preset_dict：目标对象不是 EFX_ATTRIBUTE")

    from . import io_tree
    from ..efx_format.hashes import HASH_TO_NAME

    # 导出侧解析所需的段索引映射。
    root = _rc.find_root_collection(blk_obj)

    def _localmap(type_tag):
        if root is None:
            return {}
        objs = _rc.collect_top_level(root, type_tag)
        return {o: i for i, o in enumerate(objs)}

    extern_map = _localmap("EFX_EXTERN")
    entry_map   = _localmap("EFX_ENTRY")
    play_map   = _localmap("EFX_ACTION")

    try:
        data = io_tree._resolve_attribute_data_bytes(blk_obj, extern_map, entry_map, play_map)
    except Exception:
        data = base64.b64decode(str(blk_obj.get("data_bytes", "")))

    try:
        type_hash = int(str(blk_obj.get("type_hash", "")))
    except (ValueError, TypeError):
        type_hash = 0
    type_name = HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")

    return {
        "efx_preset_kind": "attribute",
        "type_hash": str(type_hash),
        "type_name": type_name,
        "display_name": type_name,
        "category": category_of(type_hash),
        "subgroup": subgroup_of(type_hash),
        "data_bytes": base64.b64encode(data).decode("ascii"),
    }


def save_attribute_preset(blk_obj: bpy.types.Object, name: str) -> str:
    """将属性预设保存到 custom 目录，避免与分发预设混写。"""
    if not name or not name.strip():
        raise ValueError("save_attribute_preset：预设名称不能为空")

    preset = build_attribute_preset_dict(blk_obj)
    preset["display_name"] = name

    save_dir = _attribute_category_dir("custom")
    os.makedirs(save_dir, exist_ok=True)

    fallback = str(preset.get("type_name", "attribute"))
    fname = _unique_ascii_filename(save_dir, name, fallback)
    json_path = os.path.join(save_dir, fname + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=4)
    return json_path


# ─────────────────────────────────────────────────────────────────────────────
# 分类与预设列举
# ─────────────────────────────────────────────────────────────────────────────

def list_attribute_categories() -> list:
    """返回含预设的分类；子组目录中的预设也计入所属分类。"""
    root = _attribute_preset_dir()
    have = set()
    if os.path.isdir(root):
        for entry in os.scandir(root):
            if entry.is_dir():
                has_json = False
                for dirpath, _dirs, files in os.walk(entry.path):
                    if any(f.lower().endswith(".json") for f in files):
                        has_json = True
                        break
                if has_json:
                    have.add(entry.name)
            elif entry.is_file() and entry.name.lower().endswith(".json"):
                have.add("misc")  # 兼容旧扁平预设

    lang = i18n.get_lang()
    result = []
    for slug in ATTRIBUTE_CATEGORY_LABELS:
        if slug in have:
            result.append((slug, category_label(slug, lang), ""))
    # 同时列出未登记的自定义目录。
    for slug in sorted(have):
        if slug not in ATTRIBUTE_CATEGORY_LABELS:
            result.append((slug, slug, ""))

    if not result:
        return [("", T("attribute.no_preset"), "")]
    return result


def list_all_attribute_presets() -> list:
    """返回全部预设的扁平搜索列表，按显示名排序。"""
    root = _attribute_preset_dir()
    out = []
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            for fname in files:
                if fname.lower().endswith(".json"):
                    out.append(_preset_display_item(os.path.join(dirpath, fname)))
    out.sort(key=lambda item: item[1].lower())
    return out


def _is_autogen_name(display_name: str, type_name: str) -> bool:
    """判断显示名是否为类型派生的自动名。"""
    if display_name in ("", type_name):
        return True
    return display_name.startswith(type_name + "（") and display_name.endswith("）")


# ─────────────────────────────────────────────────────────────────────────────
# add_attribute_to_entry  —  核心新增逻辑
# ─────────────────────────────────────────────────────────────────────────────

def add_attribute_to_entry(entry_obj: bpy.types.Object, preset_dict: dict) -> bpy.types.Object:
    """从预设向 Entry 插入属性，并重建其可编辑引用。"""
    from . import io_tree
    from . import fields as _fields
    from ..efx_format.efxfile import AttrBlock
    from ..efx_format.hashes import HASH_TO_NAME

    if entry_obj is None or entry_obj.get("~TYPE") != "EFX_ENTRY":
        raise ValueError("add_attribute_to_entry：目标对象不是 EFX_ENTRY")
    if preset_dict.get("efx_preset_kind") != "attribute":
        raise ValueError("add_attribute_to_entry：不是属性预设（efx_preset_kind != 'attribute'）")

    try:
        type_hash = int(str(preset_dict["type_hash"]))
        data_bytes = base64.b64decode(preset_dict["data_bytes"])
    except (KeyError, ValueError, Exception) as exc:
        raise ValueError(f"add_attribute_to_entry：预设格式错误：{exc}")

    # ── 找集合（attribute 与 entry 同集合）────────────────────────────────────────
    cols = entry_obj.users_collection
    collection = cols[0] if cols else bpy.context.scene.collection

    # ── 按规范顺序计算插入位置 ────────────────────────────────────────────────
    from ..efx_format.categories import canonical_insert_index

    siblings = iter_entry_attributes(entry_obj)
    sib_hashes = []
    for obj in siblings:
        try:
            sib_hashes.append(int(str(obj.get("type_hash", "0"))))
        except (ValueError, TypeError):
            sib_hashes.append(0)

    new_idx = canonical_insert_index(sib_hashes, type_hash)

    # efx_index 是导出顺序；后移属性时同步刷新其序号显示名。
    from .delete_ops import _rebuild_attribute_name
    for pos, obj in enumerate(siblings):
        shifted = pos if pos < new_idx else pos + 1
        obj["efx_index"] = shifted
        try:
            obj.name = _rebuild_attribute_name(obj, shifted)
        except Exception:
            pass  # 名字仅供显示，不能阻断索引更新。

    # ── 构建显示名 ────────────────────────────────────────────────────────────
    from ..efx_format.hashes import pretty_type_name
    type_name = HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")
    display_type_name = pretty_type_name(type_name)
    parent_label = str(entry_obj.get("efx_raw_label", ""))
    nn = str(new_idx).zfill(2) if new_idx < 100 else str(new_idx)
    blk_name = (f"[{parent_label}] {nn} {display_type_name}" if parent_label
                else f"{nn} {display_type_name}")

    # ── 建 EFX_ATTRIBUTE 对象 ─────────────────────────────────────────────────────
    blk_obj = io_tree._new_empty(blk_name, collection)
    blk_obj["~TYPE"]         = "EFX_ATTRIBUTE"
    blk_obj["efx_index"]     = new_idx
    blk_obj["type_hash"]     = str(type_hash)
    blk_obj["data_bytes"]    = base64.b64encode(data_bytes).decode("ascii")
    blk_obj["efx_type_name"] = type_name
    blk_obj.parent           = entry_obj

    # ── 初始化 efx_block PropertyGroup ────────────────────────────────────────
    # EXTERNREFERENCE 初始化需要 Extern 索引映射。
    root_obj = _rc.find_root_collection(entry_obj)
    extern_objs = {}
    if root_obj is not None:
        for obj in _rc.collect_top_level(root_obj, "EFX_EXTERN"):
            try:
                extern_objs[int(obj.get("efx_index", 0))] = obj
            except (ValueError, TypeError):
                pass

    blk = AttrBlock(type_hash=type_hash, data_bytes=data_bytes)
    try:
        _fields.init_attribute_props(
            blk_obj, blk,
            extern_objs_by_index=extern_objs,
            count_extern=len(extern_objs),
        )
    except Exception:
        # 回退为不可编辑的原始属性。
        pass

    # ── PTLIFE / PTCOLLISION 引用 ─────────────────────────────────────────────
    # 单属性新增不会经过导入的第二阶段，须在此初始化 Action 引用。
    if root_obj is not None:
        play_objs = {}
        for obj in _rc.collect_top_level(root_obj, "EFX_ACTION"):
            try:
                play_objs[int(obj.get("efx_index", 0))] = obj
            except (ValueError, TypeError):
                pass
        count_play = len(play_objs)
        try:
            from ..efx_format.hashes import PTLIFE as _PTLIFE, PTCOLLISION as _PTCOLLISION
            from . import entry_action_ref as _bpr
            if type_hash == _PTLIFE:
                _bpr.init_ptlife_ref_props(blk_obj, data_bytes, play_objs, count_play)
            elif type_hash == _PTCOLLISION:
                _bpr.init_ptcollision_ref_props(blk_obj, data_bytes, play_objs, count_play)
        except Exception:
            pass

    # 属性不参与标签表；attr_count 由导出端重算。

    # 渲染主体变化可能影响 Entry 显示名。
    from . import reorder as _reorder
    entry_obj.name = _reorder._entry_display_name(
        int(entry_obj.get("efx_index", 0)),
        str(entry_obj.get("efx_raw_label", "")),
        entry_obj=entry_obj,
    )

    return blk_obj


def add_attribute_to_entry_from_path(entry_obj: bpy.types.Object, path: str) -> bpy.types.Object:
    """读取 JSON 预设并插入 Entry。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            preset = json.load(f)
    except Exception as exc:
        raise ValueError(f"add_attribute_to_entry_from_path：读取预设失败：{exc}")
    return add_attribute_to_entry(entry_obj, preset)


def _resolve_target_entry(obj):
    """从 Entry 或其属性解析目标；Root Entry 不接受普通属性插入。"""
    if obj is None:
        return None
    t = obj.get("~TYPE")
    if t == "EFX_ENTRY":
        return obj if str(obj.get("entry_kind", "")) != "root" else None
    if t == "EFX_ATTRIBUTE":
        parent = obj.parent
        if (parent is not None and parent.get("~TYPE") == "EFX_ENTRY"
                and str(parent.get("entry_kind", "")) != "root"):
            return parent
    return None


def _resolve_target_entries(context):
    """返回去重的目标 Entry，活动对象所属 Entry 排在首位。"""
    entries = []
    seen = set()

    def _push(obj):
        e = _resolve_target_entry(obj)
        if e is not None and e.name not in seen:
            seen.add(e.name)
            entries.append(e)

    _push(getattr(context, "active_object", None))
    for o in (getattr(context, "selected_objects", None) or []):
        _push(o)
    return entries


def _load_attribute_preset(path: str) -> dict:
    """读取属性预设 JSON。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise ValueError(f"读取预设失败：{exc}")


def _add_to_entries(entries, preset: dict):
    """逐个插入预设并收集结果；单项失败不回滚其他目标。"""
    added = []
    failed = []
    for e in entries:
        try:
            added.append(add_attribute_to_entry(e, preset))
        except Exception as exc:
            failed.append((e.name, str(exc)))
    return added, failed


def _select_added(context, added):
    """清空选择并选中所有新建属性，活动对象设为第一个（对应活动 entry 那份）。"""
    try:
        for o in context.selected_objects:
            o.select_set(False)
        for blk in added:
            blk.select_set(True)
        context.view_layer.objects.active = added[0]
    except Exception:
        pass


def _report_batch(op, verb: str, added, failed, skipped: int = 0):
    """批量结果报告：单个报名字，多个报计数，有失败/跳过则追加说明。"""
    if len(added) == 1 and not failed and not skipped:
        op.report({"INFO"}, f"Attribute {verb}: {added[0].name}")
        return
    parts = [f"{len(added)} attributes {verb}"]
    if skipped:
        parts.append(f"{skipped} entries already had it")
    if failed:
        parts.append(f"{len(failed)} failed: " + ", ".join(n for n, _ in failed[:3]))
    op.report({"WARNING"} if failed else {"INFO"}, "; ".join(parts))


# ─────────────────────────────────────────────────────────────────────────────
# 内存剪贴板
# ─────────────────────────────────────────────────────────────────────────────

# 模块级属性剪贴板，不随 .blend 保存。
_ATTRIBUTE_CLIPBOARD: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：保存属性预设
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_save_attribute_preset(bpy.types.Operator):
    """将当前属性保存为可复用预设。"""

    bl_idname      = "efx.save_attribute_preset"
    bl_label       = "Save as Attribute Preset"
    bl_description = "Save the current EFX_ATTRIBUTE (with edited field values) as a reusable whole-attribute preset"
    bl_options     = {"REGISTER"}

    preset_name: StringProperty(
        name="Preset Name",
        description="Preset name to save (without .json)",
        default="my_attribute",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            type_name = str(obj.get("efx_type_name", "attribute")).strip()
            self.preset_name = type_name or "my_attribute"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        obj = context.active_object
        try:
            path = save_attribute_preset(obj, self.preset_name)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to save attribute preset. See the system console for details.")
            return {"CANCELLED"}
        _invalidate_attribute_preset_cache()
        self.report({"INFO"}, f"Attribute preset saved: {os.path.basename(path)}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：从预设新增属性
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_attribute_from_preset(bpy.types.Operator):
    """将选中预设插入每个目标 Entry。"""

    bl_idname      = "efx.add_attribute_from_preset"
    bl_label       = "Add Attribute"
    bl_description = "Add an attribute from the selected whole-attribute preset to every selected EFX_ENTRY (inserted at its canonical position, attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    preset_path: StringProperty(
        name="Preset Path (encoded)",
        description="Attribute preset JSON path to add (base64-encoded)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return bool(_resolve_target_entries(context))

    def execute(self, context):
        entries = _resolve_target_entries(context)
        if not entries:
            self.report({"ERROR"}, "Select an EFX_ENTRY (or one of its EFX_ATTRIBUTE) object first")
            return {"CANCELLED"}
        if not self.preset_path:
            self.report({"ERROR"}, "No attribute preset selected")
            return {"CANCELLED"}

        actual_path = _decode_path_ident(self.preset_path)
        try:
            preset = _load_attribute_preset(actual_path)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add attribute from preset. See the system console for details.")
            return {"CANCELLED"}

        added, failed = _add_to_entries(entries, preset)
        if not added:
            self.report({"ERROR"}, f"Failed to add attribute: {failed[0][1]}")
            return {"CANCELLED"}

        _select_added(context, added)
        _report_batch(self, "added", added, failed)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 缺失属性建议
# ─────────────────────────────────────────────────────────────────────────────

def default_attribute_preset_path(type_hash: int):
    """返回随扩展分发的该类型默认预设路径；不存在时返回 None。"""
    from ..efx_format.hashes import HASH_TO_NAME
    from ..efx_format.categories import attribute_preset_relpath
    name = HASH_TO_NAME.get(type_hash)
    if not name:
        return None
    path = os.path.join(_attribute_preset_dir(),
                        *attribute_preset_relpath(type_hash),
                        name + ".json")
    return path if os.path.isfile(path) else None


def iter_entry_attributes(entry_obj):
    """按 efx_index 返回 Entry 属性，优先限定在所属集合内。"""
    pool = None
    try:
        cols = entry_obj.users_collection
        if cols:
            pool = cols[0].all_objects
    except Exception:
        pool = None
    if pool is None:
        pool = bpy.data.objects

    out = []
    for obj in pool:
        if obj.parent is not entry_obj or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            idx = int(obj.get("efx_index", 0))
        except (ValueError, TypeError):
            idx = 0
        out.append((idx, obj))
    out.sort(key=lambda t: t[0])
    return [o for _, o in out]


def entry_body_hash(entry_obj):
    """返回首个 renderer_body 类型哈希；不存在时返回 None。"""
    from ..efx_format.categories import ATTRIBUTE_CATEGORY_OF
    for obj in iter_entry_attributes(entry_obj):
        try:
            h = int(str(obj.get("type_hash", "0")))
        except (ValueError, TypeError):
            continue
        if ATTRIBUTE_CATEGORY_OF.get(h) == "renderer_body":
            return h
    return None


def entry_present_hashes(entry_obj):
    """返回该 entry 现有全部属性的 type_hash 集合。"""
    out = set()
    for obj in iter_entry_attributes(entry_obj):
        try:
            out.add(int(str(obj.get("type_hash", "0"))))
        except (ValueError, TypeError):
            pass
    return out


def suggested_for_entry(entry_obj, min_rate=40):
    """返回常用但缺失且存在默认预设的属性建议；不参与校验。"""
    from ..efx_format.categories import suggest_missing_attributes
    body = entry_body_hash(entry_obj)
    present = entry_present_hashes(entry_obj)
    out = []
    for h, rate in suggest_missing_attributes(body, present, min_rate=min_rate):
        path = default_attribute_preset_path(h)
        if path:
            out.append((h, rate, path))
    return out


class EFX_OT_add_suggested_attribute(bpy.types.Operator):
    """把某个"常用但缺失"的属性按默认预设补进每个选中的 entry（插到规范顺序位，多选即批量）"""

    bl_idname      = "efx.add_suggested_attribute"
    bl_label       = "Add Suggested Attribute"
    bl_description = "Add this commonly-used attribute to every selected entry, inserted at its canonical position (entries that already have it are skipped)"
    bl_options     = {"REGISTER", "UNDO"}

    type_hash: StringProperty(name="Type Hash", default="")

    @classmethod
    def poll(cls, context):
        return bool(_resolve_target_entries(context))

    def execute(self, context):
        entries = _resolve_target_entries(context)
        if not entries:
            self.report({"ERROR"}, "Select an EFX_ENTRY (or one of its EFX_ATTRIBUTE) object first")
            return {"CANCELLED"}
        try:
            h = int(self.type_hash)
        except (ValueError, TypeError):
            self.report({"ERROR"}, "Invalid type hash")
            return {"CANCELLED"}
        path = default_attribute_preset_path(h)
        if not path:
            self.report({"ERROR"}, "No default preset shipped for this attribute type")
            return {"CANCELLED"}
        try:
            preset = _load_attribute_preset(path)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add attribute from preset. See the system console for details.")
            return {"CANCELLED"}

        # 批量建议不重复添加已有类型。
        targets = [e for e in entries
                   if len(entries) == 1 or h not in entry_present_hashes(e)]
        if not targets:
            self.report({"INFO"}, "All selected entries already have this attribute")
            return {"CANCELLED"}

        added, failed = _add_to_entries(targets, preset)
        if not added:
            print(f"[EFX] Failed to add attribute to '{failed[0][0]}': {failed[0][1]}")
            self.report({"ERROR"}, "Failed to add this attribute. See the system console for details.")
            return {"CANCELLED"}

        _select_added(context, added)
        _report_batch(self, "added", added, failed, skipped=len(entries) - len(targets))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：打开属性预设文件夹
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_open_attribute_preset_folder(bpy.types.Operator):
    """打开属性预设目录。"""

    bl_idname      = "efx.open_attribute_preset_folder"
    bl_label       = "Open Attribute Preset Folder"
    bl_description = "Open the __attributes__ preset directory in the system file manager"
    bl_options     = {"REGISTER"}

    def execute(self, context):
        folder = _attribute_preset_dir()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：复制 / 粘贴 属性（内存剪贴板）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_copy_attribute(bpy.types.Operator):
    """将当前属性复制到内存剪贴板。"""

    bl_idname      = "efx.copy_attribute"
    bl_label       = "Copy Attribute"
    bl_description = "Copy the current EFX_ATTRIBUTE (with edited field values) to the in-memory clipboard"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE"

    def execute(self, context):
        global _ATTRIBUTE_CLIPBOARD
        try:
            _ATTRIBUTE_CLIPBOARD = build_attribute_preset_dict(context.active_object)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to copy this attribute. See the system console for details.")
            return {"CANCELLED"}
        type_name = _ATTRIBUTE_CLIPBOARD.get("type_name", "")
        self.report({"INFO"}, f"Attribute copied to clipboard ({type_name})")
        return {"FINISHED"}


class EFX_OT_paste_attribute(bpy.types.Operator):
    """将剪贴板属性插入每个目标 Entry。"""

    bl_idname      = "efx.paste_attribute"
    bl_label       = "Paste Attribute"
    bl_description = "Add the clipboard attribute to every selected EFX_ENTRY (inserted at its canonical position, attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_ATTRIBUTE_CLIPBOARD) and bool(_resolve_target_entries(context))

    def execute(self, context):
        if not _ATTRIBUTE_CLIPBOARD:
            self.report({"ERROR"}, "Clipboard is empty (use Copy Attribute first)")
            return {"CANCELLED"}
        entries = _resolve_target_entries(context)
        if not entries:
            self.report({"ERROR"}, "Select an EFX_ENTRY (or one of its EFX_ATTRIBUTE) object first")
            return {"CANCELLED"}

        added, failed = _add_to_entries(entries, _ATTRIBUTE_CLIPBOARD)
        if not added:
            self.report({"ERROR"}, f"Failed to paste attribute: {failed[0][1]}")
            return {"CANCELLED"}

        _select_added(context, added)
        _report_batch(self, "pasted", added, failed)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 动态 EnumProperty 项缓存；保存后通过脏标志立即失效。
_attribute_category_items_cache = [("", "(no attribute presets)", "")]
_attribute_category_dirty = True
_attribute_category_cache_time = 0.0
_ATTRIBUTE_CACHE_TTL = 2.0            # 秒

# 全局搜索列表与分类缓存共享失效标志。
_attribute_search_items_cache = [("", "(no attribute presets)", "")]
_attribute_search_dirty = True
_attribute_search_cache_time = 0.0


def _invalidate_attribute_preset_cache():
    global _attribute_category_dirty, _attribute_search_dirty
    _attribute_category_dirty = True
    _attribute_search_dirty = True


def _get_attribute_category_items(self, context):
    """分类动态 items 回调。"""
    global _attribute_category_items_cache, _attribute_category_dirty, _attribute_category_cache_time
    now = time.monotonic()
    if _attribute_category_dirty or (now - _attribute_category_cache_time) > _ATTRIBUTE_CACHE_TTL:
        try:
            _attribute_category_items_cache = list_attribute_categories()
        except Exception:
            _attribute_category_items_cache = [("", "(category load error)", "")]
        _attribute_category_dirty = False
        _attribute_category_cache_time = now
    return _attribute_category_items_cache


def _get_attribute_search_items(self, context):
    """搜索动态 items 回调。"""
    global _attribute_search_items_cache, _attribute_search_dirty, _attribute_search_cache_time
    now = time.monotonic()
    if _attribute_search_dirty or (now - _attribute_search_cache_time) > _ATTRIBUTE_CACHE_TTL:
        try:
            _attribute_search_items_cache = list_all_attribute_presets()
        except Exception:
            _attribute_search_items_cache = [("", "(preset load error)", "")]
        _attribute_search_dirty = False
        _attribute_search_cache_time = now
    return _attribute_search_items_cache


class EFX_OT_attribute_add_search(bpy.types.Operator):
    """搜索已具备默认预设的属性类型，并复用预设插入流程。"""

    bl_idname      = "efx.attribute_add_search"
    bl_label       = "Search Attribute Type"
    bl_description = "Fuzzy-search attribute types by name and add on pick"
    bl_options     = {"REGISTER", "UNDO"}
    bl_property    = "preset_path"

    preset_path: EnumProperty(
        name="Type",
        description="要新增的属性类型",
        items=_get_attribute_search_items,
    )

    @classmethod
    def poll(cls, context):
        return bool(_resolve_target_entries(context))

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        return bpy.ops.efx.add_attribute_from_preset(preset_path=self.preset_path)


class EFX_MT_attribute_preset_picker(bpy.types.Menu):
    """按子组显示具体属性预设的二级菜单。"""

    bl_idname = "EFX_MT_attribute_preset_picker"
    bl_label  = "Attribute Preset"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        slug = getattr(wm, "efx_block_category_enum", "") if wm else ""
        if not slug:
            layout.label(text=T("attribute.pick_category"))
            return

        from ..efx_format.categories import subgroup_label

        items = _iter_preset_files(_attribute_category_dir(slug))
        if slug == "misc":
            # 兼容属性预设根目录中的扁平文件。
            root = _attribute_preset_dir()
            if os.path.isdir(root):
                for entry in sorted(os.scandir(root), key=lambda e: e.name):
                    if entry.is_file() and entry.name.lower().endswith(".json"):
                        items.append((entry.path, ""))

        if not items:
            layout.label(text=T("attribute.cat_empty"))
            return

        lang = i18n.get_lang()
        _sentinel = object()
        last_sub = _sentinel
        for path, sub in items:
            if sub != last_sub:
                if sub:
                    layout.label(text=subgroup_label(sub, lang))
                last_sub = sub
            ident, label, _type_name = _preset_display_item(path)
            op = layout.operator("efx.add_attribute_from_preset", text=label)
            op.preset_path = ident


_CLASSES = (
    EFX_OT_save_attribute_preset,
    EFX_OT_add_attribute_from_preset,
    EFX_OT_attribute_add_search,
    EFX_OT_add_suggested_attribute,
    EFX_OT_open_attribute_preset_folder,
    EFX_OT_copy_attribute,
    EFX_OT_paste_attribute,
    EFX_MT_attribute_preset_picker,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.efx_preset_mode = EnumProperty(
        name="Preset Mode",
        items=[
            ("ENTRY",     "Entry",     ""),
            ("ATTRIBUTE", "Attribute", ""),
        ],
        default="ENTRY",
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.efx_block_category_enum = EnumProperty(
        name="Attribute Category",
        description="Pick the functional category of the attribute first",
        items=_get_attribute_category_items,
        options={"SKIP_SAVE"},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "efx_block_category_enum"):
        del bpy.types.WindowManager.efx_block_category_enum
    if hasattr(bpy.types.WindowManager, "efx_preset_mode"):
        del bpy.types.WindowManager.efx_preset_mode

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
