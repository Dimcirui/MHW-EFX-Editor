"""
blender_efx/attribute_ops.py  —  属性级组装：单属性的复制/粘贴与属性预设保存/新增

功能：
  - build_attribute_preset_dict(blk_obj)：把单个 EFX_ATTRIBUTE 构建为预设 dict（供保存/复制共用）
  - save_attribute_preset(blk_obj, name)：落盘到 presets/__attributes__/
  - add_attribute_to_entry(entry_obj, preset_dict)：按预设在 entry 末尾追加单个属性
  - list_attribute_categories() / list_attribute_presets(slug)：两级下拉的 items（分类 / 类内属性）
  - 算子：efx.save_attribute_preset / efx.add_attribute_from_preset /
          efx.open_attribute_preset_folder / efx.copy_attribute / efx.paste_attribute

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2），bpy 只用长期稳定子集
  - 包内相对导入；不改 efx_format/ 与 io_tree.py（仅复用其函数）
  - 新增属性只需：建对象、设好 efx_index，导出端会按实际属性数自动重算 attr_count。
  - data_bytes 用 io_tree._resolve_attribute_data_bytes（与保存 entry 预设同款），
    抓到的是用户修改后的当前实际字节。

预设 JSON schema：
{
    "efx_preset_kind": "attribute",
    "type_hash": "<十进制str>",
    "type_name": "<TRANSFORM3D / 0x... 等>",
    "display_name": "<用户命名（utf-8）>",
    "category": "<分类 slug，如 transform/render；见 efx_format/categories.py>",
    "data_bytes": "<base64>"
}

存盘布局：presets/__attributes__/<category>/<NAME>.json
  按属性类型的功能分类自动归入子目录，配合面板两级下拉（先选分类，再选属性）。
  根目录下的旧扁平 *.json 仍被 list_attribute_presets('misc') 兜底读取（向后兼容）。
"""

import base64
import json
import os
import time

import bpy
from bpy.props import EnumProperty, StringProperty

from .presets import _presets_root, _unique_ascii_filename, _read_display_name, _encode_path_ident, _decode_path_ident
from ..efx_format.categories import category_of, category_label, ATTRIBUTE_CATEGORY_LABELS
from . import i18n
from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

def _attribute_preset_dir() -> str:
    """返回属性预设根目录 presets/__attributes__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__attributes__")


def _attribute_category_dir(slug: str) -> str:
    """返回某分类的属性预设子目录 presets/__attributes__/<slug>/。"""
    return os.path.join(_attribute_preset_dir(), slug)


# ─────────────────────────────────────────────────────────────────────────────
# build_attribute_preset_dict / save_attribute_preset
# ─────────────────────────────────────────────────────────────────────────────

def build_attribute_preset_dict(blk_obj: bpy.types.Object) -> dict:
    """
    把 blk_obj（EFX_ATTRIBUTE）构建为 preset dict（不落盘）。
    供 save_attribute_preset（写文件）与 复制属性（内存剪贴板）共用。

    data_bytes 用 io_tree._resolve_attribute_data_bytes 取当前实际字节（含字段编辑）。
    """
    if blk_obj is None or blk_obj.get("~TYPE") != "EFX_ATTRIBUTE":
        raise ValueError("build_attribute_preset_dict：目标对象不是 EFX_ATTRIBUTE")

    from . import io_tree
    from ..efx_format.hashes import HASH_TO_NAME

    # 构建导出端所需的 index 映射（与 _collect_attribute_dicts 同款）
    root = _rc.find_root_collection(blk_obj)  # attribute 直接归属该 root（同集合）

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
        "display_name": type_name,  # 可被 save_attribute_preset 用用户输入覆盖
        "category": category_of(type_hash),
        "data_bytes": base64.b64encode(data).decode("ascii"),
    }


def save_attribute_preset(blk_obj: bpy.types.Object, name: str) -> str:
    """
    把 blk_obj 存为属性预设 JSON 文件。

    返回保存的路径；name 用于显示名（可含中文），文件名 ASCII 化。
    """
    if not name or not name.strip():
        raise ValueError("save_attribute_preset：预设名称不能为空")

    preset = build_attribute_preset_dict(blk_obj)
    preset["display_name"] = name

    # 按属性类型的分类存入对应子目录（presets/__attributes__/<slug>/）。
    slug = preset.get("category") or "misc"
    save_dir = _attribute_category_dir(slug)
    os.makedirs(save_dir, exist_ok=True)

    fallback = str(preset.get("type_name", "attribute"))
    fname = _unique_ascii_filename(save_dir, name, fallback)
    json_path = os.path.join(save_dir, fname + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=4)
    return json_path


# ─────────────────────────────────────────────────────────────────────────────
# 分类与预设列举（两级下拉）
# ─────────────────────────────────────────────────────────────────────────────

def _category_of_dir(dirname: str) -> str:
    """子目录名即 slug；扁平根目录下的旧预设视为 'misc'。"""
    return dirname


def list_attribute_categories() -> list:
    """
    扫 __attributes__/ 的子目录，返回有预设的分类 EnumProperty items：
      [(slug, 中文名, ""), ...]，按 ATTRIBUTE_CATEGORY_LABELS 顺序排列。
    无任何预设时返回 [("", "（无属性预设）", "")]。
    """
    root = _attribute_preset_dir()
    have = set()
    if os.path.isdir(root):
        for entry in os.scandir(root):
            if entry.is_dir():
                # 该子目录下是否有 .json
                for sub in os.scandir(entry.path):
                    if sub.is_file() and sub.name.lower().endswith(".json"):
                        have.add(entry.name)
                        break
            elif entry.is_file() and entry.name.lower().endswith(".json"):
                have.add("misc")  # 兼容旧扁平预设

    lang = i18n.get_lang()
    result = []
    for slug in ATTRIBUTE_CATEGORY_LABELS:
        if slug in have:
            result.append((slug, category_label(slug, lang), ""))
    # 出现了未登记的 slug（用户手建目录）也列出来
    for slug in sorted(have):
        if slug not in ATTRIBUTE_CATEGORY_LABELS:
            result.append((slug, slug, ""))

    if not result:
        return [("", T("attribute.no_preset"), "")]
    return result


def list_attribute_presets(category_slug: str) -> list:
    """
    列举某分类子目录下的属性预设 EnumProperty items：
      [(_encode_path_ident(path), display_name, type_name), ...]
    misc 额外包含 __attributes__/ 根下的旧扁平预设（向后兼容）。
    """
    if not category_slug:
        return [("", T("attribute.pick_category"), "")]

    dirs = [_attribute_category_dir(category_slug)]
    if category_slug == "misc":
        dirs.append(_attribute_preset_dir())  # 旧扁平预设兜底

    result = []
    seen = set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for entry in sorted(os.scandir(d), key=lambda e: e.name):
            if not (entry.is_file() and entry.name.lower().endswith(".json")):
                continue
            if entry.path in seen:
                continue
            seen.add(entry.path)
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    d2 = json.load(f)
                type_name = d2.get("type_name", "")
                stored_display = d2.get("display_name", "")
            except Exception:
                type_name, stored_display = "", ""
            # 自动生成的预设（display_name 为空 / 等于 type_name / 「TYPE（…）」式）→
            # 按当前语言用 type_label 显示；用户自定义名则原样保留。
            if type_name and _is_autogen_name(stored_display, type_name):
                label = i18n.type_label(type_name)
            else:
                label = stored_display or _read_display_name(entry.path)
            result.append((_encode_path_ident(entry.path), label, type_name))

    if not result:
        return [("", T("attribute.cat_empty"), "")]
    return result


def _is_autogen_name(display_name: str, type_name: str) -> bool:
    """display_name 是否为自动生成式（空 / 等于 type_name / 「TYPE（中文）」），而非用户自定义。"""
    if display_name in ("", type_name):
        return True
    return display_name.startswith(type_name + "（") and display_name.endswith("）")


# ─────────────────────────────────────────────────────────────────────────────
# add_attribute_to_entry  —  核心新增逻辑
# ─────────────────────────────────────────────────────────────────────────────

def add_attribute_to_entry(entry_obj: bpy.types.Object, preset_dict: dict) -> bpy.types.Object:
    """
    按 preset_dict 在 entry 末尾追加单个 EFX_ATTRIBUTE。

    参数
    ----
    entry_obj    : ~TYPE == 'EFX_ENTRY' 的对象
    preset_dict : {"efx_preset_kind":"attribute","type_hash":str,"data_bytes":b64,...}

    返回
    ----
    新建的 EFX_ATTRIBUTE 对象。

    说明
    ----
    - 新属性 efx_index = 同 entry 内现有属性最大 index + 1
    - attr_count 由导出端（io_tree §4c）按实际属性数重算，无需手动维护
    - EXTERNREFERENCE 引用指针在 init_attribute_props 内初始化；PTLIFE/PTCOLLISION
      在本函数末尾补充指针化（越界 baked 值强制转可编辑悬空，供用户指定 Action）
    """
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

    # ── 计算新 efx_index ─────────────────────────────────────────────────────
    max_idx = -1
    for obj in bpy.data.objects:
        if obj.parent == entry_obj and obj.get("~TYPE") == "EFX_ATTRIBUTE":
            try:
                max_idx = max(max_idx, int(obj.get("efx_index", 0)))
            except (ValueError, TypeError):
                pass
    new_idx = max_idx + 1

    # ── 构建显示名 ────────────────────────────────────────────────────────────
    from ..efx_format.hashes import pretty_type_name
    type_name = HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")
    display_type_name = pretty_type_name(type_name)  # 大纲显示用，非内部标识
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
    blk_obj["efx_type_name"] = type_name  # 原始大写，内部标识/重排重建显示名用
    blk_obj.parent           = entry_obj

    # ── 初始化 efx_block PropertyGroup ────────────────────────────────────────
    # 构建 extern 映射（供 EXTERNREFERENCE 属性指针化）
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
        # 安全回退：efx_block 保持 is_editable=False
        pass

    # ── PTLIFE / PTCOLLISION 引用指针化 ───────────────────────────────────────
    # init_attribute_props 只处理 EXTERNREFERENCE；PTLIFE/PTCOLLISION 在 io_tree 导入时
    # 由独立第二 pass 指针化，而单属性新增路径没有该 pass → 此处补上。
    # 2026-07 简化后 init_*_ref_props 本身就总是留下可编辑状态（越界/死值 → play_ptr
    # 留空=无目标，导出自动写 -1），不再需要额外"强制转悬空"补丁。
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

    # attr_count 由导出端自动重算，无需设 labels_dirty（属性不在标签表）

    # entry 自身显示名可能要变（新属性若是渲染主体，需在 entry 名后补/改后缀）
    from . import reorder as _reorder
    entry_obj.name = _reorder._entry_display_name(
        int(entry_obj.get("efx_index", 0)),
        str(entry_obj.get("efx_raw_label", "")),
        entry_obj=entry_obj,
    )

    return blk_obj


def add_attribute_to_entry_from_path(entry_obj: bpy.types.Object, path: str) -> bpy.types.Object:
    """从 JSON 文件路径读取预设并新增到 entry 末尾。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            preset = json.load(f)
    except Exception as exc:
        raise ValueError(f"add_attribute_to_entry_from_path：读取预设失败：{exc}")
    return add_attribute_to_entry(entry_obj, preset)


def _resolve_target_entry(obj):
    """新增属性的目标 entry 解析：obj 本身是 EFX_ENTRY 则直接用；
    obj 是 EFX_ATTRIBUTE 则取其父 EFX_ENTRY（连续新增属性时无需先切回 entry）。
    都不满足返回 None。
    """
    if obj is None:
        return None
    t = obj.get("~TYPE")
    if t == "EFX_ENTRY":
        return obj
    if t == "EFX_ATTRIBUTE":
        parent = obj.parent
        if parent is not None and parent.get("~TYPE") == "EFX_ENTRY":
            return parent
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 内存剪贴板（会话级）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级整-属性剪贴板：build_attribute_preset_dict 的结果（会话内有效）。
_ATTRIBUTE_CLIPBOARD: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：保存属性预设
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_save_attribute_preset(bpy.types.Operator):
    """把当前选中的 EFX_ATTRIBUTE 保存为整属性预设（供其他 entry 新增使用）"""

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
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to save attribute preset: {exc}")
            return {"CANCELLED"}
        _invalidate_attribute_preset_cache()
        self.report({"INFO"}, f"Attribute preset saved: {os.path.basename(path)}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：从预设新增属性
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_attribute_from_preset(bpy.types.Operator):
    """按选中的属性预设，在当前 EFX_ENTRY 末尾新增一个属性"""

    bl_idname      = "efx.add_attribute_from_preset"
    bl_label       = "Add Attribute"
    bl_description = "Append an attribute to the end of the current EFX_ENTRY from the selected whole-attribute preset (attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    preset_path: StringProperty(
        name="Preset Path (encoded)",
        description="Attribute preset JSON path to add (base64-encoded)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return _resolve_target_entry(context.active_object) is not None

    def execute(self, context):
        entry_obj = _resolve_target_entry(context.active_object)
        if entry_obj is None:
            self.report({"ERROR"}, "Select an EFX_ENTRY (or one of its EFX_ATTRIBUTE) object first")
            return {"CANCELLED"}
        if not self.preset_path:
            self.report({"ERROR"}, "No attribute preset selected")
            return {"CANCELLED"}

        actual_path = _decode_path_ident(self.preset_path)
        try:
            new_blk = add_attribute_to_entry_from_path(entry_obj, actual_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add attribute: {exc}")
            return {"CANCELLED"}

        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_blk.select_set(True)
            context.view_layer.objects.active = new_blk
        except Exception:
            pass

        self.report({"INFO"}, f"Attribute added: {new_blk.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：打开属性预设文件夹
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_open_attribute_preset_folder(bpy.types.Operator):
    """打开属性预设所在文件夹（资源管理器 / Finder）"""

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
    """把当前 EFX_ATTRIBUTE 复制到内存剪贴板（供"粘贴属性"快速新增）"""

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
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to copy attribute: {exc}")
            return {"CANCELLED"}
        type_name = _ATTRIBUTE_CLIPBOARD.get("type_name", "")
        self.report({"INFO"}, f"Attribute copied to clipboard ({type_name})")
        return {"FINISHED"}


class EFX_OT_paste_attribute(bpy.types.Operator):
    """把剪贴板的属性粘贴（新增）到当前 EFX_ENTRY 末尾"""

    bl_idname      = "efx.paste_attribute"
    bl_label       = "Paste Attribute"
    bl_description = "Append the clipboard attribute to the end of the current EFX_ENTRY (attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_ATTRIBUTE_CLIPBOARD) and _resolve_target_entry(context.active_object) is not None

    def execute(self, context):
        if not _ATTRIBUTE_CLIPBOARD:
            self.report({"ERROR"}, "Clipboard is empty (use Copy Attribute first)")
            return {"CANCELLED"}
        entry_obj = _resolve_target_entry(context.active_object)
        if entry_obj is None:
            self.report({"ERROR"}, "Select an EFX_ENTRY (or one of its EFX_ATTRIBUTE) object first")
            return {"CANCELLED"}
        try:
            new_blk = add_attribute_to_entry(entry_obj, _ATTRIBUTE_CLIPBOARD)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to paste attribute: {exc}")
            return {"CANCELLED"}
        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_blk.select_set(True)
            context.view_layer.objects.active = new_blk
        except Exception:
            pass
        self.report({"INFO"}, f"Attribute pasted: {new_blk.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_save_attribute_preset,
    EFX_OT_add_attribute_from_preset,
    EFX_OT_open_attribute_preset_folder,
    EFX_OT_copy_attribute,
    EFX_OT_paste_attribute,
)

# EnumProperty 动态回调缓存（GC 陷阱说明见 panels.py 顶部）。
# 脏标志 + 2 秒 TTL：保存后立即失效；手动改文件夹 2 秒内刷新。
_attribute_category_items_cache = [("", "(no attribute presets)", "")]
_attribute_whole_preset_items_cache = [("", "(pick a category)", "")]
_attribute_category_dirty = True
_attribute_preset_dirty = True
_attribute_category_cache_time = 0.0
_attribute_preset_cache_time = 0.0
_last_preset_slug = None          # 上次构建 preset list 时用的 category slug
_ATTRIBUTE_CACHE_TTL = 2.0            # 秒


def _invalidate_attribute_preset_cache():
    global _attribute_category_dirty, _attribute_preset_dirty
    _attribute_category_dirty = True
    _attribute_preset_dirty = True


def _get_attribute_category_items(self, context):
    """WindowManager.efx_block_category_enum 的动态 items 回调（带缓存）。"""
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


def _get_attribute_whole_preset_items(self, context):
    """
    WindowManager.efx_block_whole_preset_enum 的动态 items 回调（带缓存）。
    分类切换或脏标志时重扫。
    """
    global _attribute_whole_preset_items_cache, _attribute_preset_dirty, _attribute_preset_cache_time, _last_preset_slug
    wm = context.window_manager if context else None
    slug = getattr(wm, "efx_block_category_enum", "") if wm else ""
    now = time.monotonic()
    if _attribute_preset_dirty or slug != _last_preset_slug or (now - _attribute_preset_cache_time) > _ATTRIBUTE_CACHE_TTL:
        try:
            _attribute_whole_preset_items_cache = list_attribute_presets(slug)
        except Exception:
            _attribute_whole_preset_items_cache = [("", "(preset load error)", "")]
        _attribute_preset_dirty = False
        _attribute_preset_cache_time = now
        _last_preset_slug = slug
    return _attribute_whole_preset_items_cache


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
    bpy.types.WindowManager.efx_block_whole_preset_enum = EnumProperty(
        name="Attribute Preset",
        description="Pick the whole-attribute preset to add within the selected category",
        items=_get_attribute_whole_preset_items,
        options={"SKIP_SAVE"},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "efx_block_whole_preset_enum"):
        del bpy.types.WindowManager.efx_block_whole_preset_enum
    if hasattr(bpy.types.WindowManager, "efx_block_category_enum"):
        del bpy.types.WindowManager.efx_block_category_enum
    if hasattr(bpy.types.WindowManager, "efx_preset_mode"):
        del bpy.types.WindowManager.efx_preset_mode

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
