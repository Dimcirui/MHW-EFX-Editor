"""
blender_efx/attribute_ops.py  —  属性级组装：单属性的复制/粘贴与属性预设保存/新增

功能：
  - build_attribute_preset_dict(blk_obj)：把单个 EFX_ATTRIBUTE 构建为预设 dict（供保存/复制共用）
  - save_attribute_preset(blk_obj, name)：落盘到 presets/__attributes__/
  - add_attribute_to_entry(entry_obj, preset_dict)：按预设在 entry 末尾追加单个属性
  - 两级选择：list_attribute_categories()（第一级分类 EnumProperty items）+
    EFX_MT_attribute_preset_picker（第二级具体预设，Menu，按子组分组显示灰字标题，
    点击预设行直接新增，不需要额外的"Add"确认按钮）
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
    "category": "<该属性类型的官方分类 slug；见 efx_format/categories.py>",
    "subgroup": "<该分类内的子组 slug，无子组则空串>",
    "data_bytes": "<base64>"
}
"category"/"subgroup" 只是该属性类型本身的官方分类元数据（供人读/供迁移脚本用），
2026-07 分类重构后不再决定存盘位置——所有 save_attribute_preset 新建的预设统一存 custom/，
跟官方分类目录彻底隔离。

存盘布局：presets/__attributes__/<category>[/<subgroup>]/<NAME>.json（官方分类，部分分类下
再按子组分子目录）；presets/__attributes__/custom/<NAME>.json（用户新建预设，扁平不分子组）。
根目录下的旧扁平 *.json 仍被 EFX_MT_attribute_preset_picker 在 misc 分类下兜底读取（向后兼容）。
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

# 子组排序基准（按 ATTRIBUTE_SUBGROUP_LABELS 插入顺序），供 _iter_preset_files 分组排序用。
_SUBGROUP_ORDER = list(ATTRIBUTE_SUBGROUP_LABELS)


def _attribute_preset_dir() -> str:
    """返回属性预设根目录 presets/__attributes__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__attributes__")


def _attribute_category_dir(slug: str) -> str:
    """返回某分类的属性预设子目录 presets/__attributes__/<slug>/。"""
    return os.path.join(_attribute_preset_dir(), slug)


def _iter_preset_files(category_dir: str) -> list:
    """递归扫描 category_dir 下所有 .json 预设文件，按 (子组顺序, 文件名) 排好序返回
    [(文件绝对路径, 子组slug), ...]；子组 slug 取自相对 category_dir 的一级子目录名，
    直接落在 category_dir 根下（分类本身不分子组）则子组 slug 为空串，排最前。
    子组间顺序按 ATTRIBUTE_SUBGROUP_LABELS 插入顺序，不在表里的未知子组排最后。"""
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
    # 自动生成的预设（display_name 为空 / 等于 type_name / 「TYPE（…）」式）→
    # 按当前语言用 type_label 显示；用户自定义名则原样保留。
    if type_name and _is_autogen_name(stored_display, type_name):
        label = i18n.type_label(type_name)
    else:
        label = stored_display or _read_display_name(path)
    return (_encode_path_ident(path), label, type_name)


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
        "category": category_of(type_hash),      # 元数据：该类型的官方分类，不决定存盘位置
        "subgroup": subgroup_of(type_hash),       # 元数据：该分类内的子组，无子组则空串
        "data_bytes": base64.b64encode(data).decode("ascii"),
    }


def save_attribute_preset(blk_obj: bpy.types.Object, name: str) -> str:
    """
    把 blk_obj 存为属性预设 JSON 文件，统一存进 presets/__attributes__/custom/。

    返回保存的路径；name 用于显示名（可含中文），文件名 ASCII 化。

    2026-07 分类重构起：用户新建预设不再按 category_of(type_hash) 落进官方分类目录
    （那些目录只放插件内置预设，未来版本更新时会被强制覆盖同步）——统一存 custom/，
    跟官方内容彻底隔离，保证不会被更新覆盖，也让"custom 分类=用户内容"的边界清晰可判。
    """
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
# 分类与预设列举（两级下拉）
# ─────────────────────────────────────────────────────────────────────────────

def list_attribute_categories() -> list:
    """
    扫 __attributes__/ 的子目录，返回有预设的分类 EnumProperty items：
      [(slug, 中文名, ""), ...]，按 ATTRIBUTE_CATEGORY_LABELS 顺序排列。
    无任何预设时返回 [("", "（无属性预设）", "")]。

    递归检查每个分类目录下是否有 .json（部分分类的预设落在子组子目录下，不是直接
    在分类根目录里），custom 分类初始为空目录，天然不会出现在结果里。
    """
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
    # 出现了未登记的 slug（用户手建目录）也列出来
    for slug in sorted(have):
        if slug not in ATTRIBUTE_CATEGORY_LABELS:
            result.append((slug, slug, ""))

    if not result:
        return [("", T("attribute.no_preset"), "")]
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
    - 新属性 efx_index 按**规范顺序**插入（`categories.canonical_insert_index`），
      插入点之后的兄弟属性整体后移一位并重建显示名；不再一律追加到末尾
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

    # ── 计算新 efx_index：插到规范顺序对应的位置，而不是一律追加到末尾 ────────
    # 规范顺序表见 efx_format/categories.py::ATTRIBUTE_CANONICAL_ORDER（官方语料
    # 拓扑排序得出，99.5% 的 entry 符合）。追加到末尾会让新属性落在几乎必然错误的
    # 位置（例如在 RGBFIRE/PTLIFE 这些惯例末位属性之后）。
    from ..efx_format.categories import canonical_insert_index

    siblings = []
    for obj in bpy.data.objects:
        if obj.parent == entry_obj and obj.get("~TYPE") == "EFX_ATTRIBUTE":
            try:
                idx = int(obj.get("efx_index", 0))
            except (ValueError, TypeError):
                idx = 0
            try:
                h = int(str(obj.get("type_hash", "0")))
            except (ValueError, TypeError):
                h = 0
            siblings.append((idx, h, obj))
    siblings.sort(key=lambda t: t[0])

    new_idx = canonical_insert_index([h for _, h, _ in siblings], type_hash)

    # 插入点及其之后的兄弟属性整体后移一位，腾出 new_idx；显示名含序号，需同步重建
    from .delete_ops import _rebuild_attribute_name
    for pos, (_, _, obj) in enumerate(siblings):
        shifted = pos if pos < new_idx else pos + 1
        obj["efx_index"] = shifted
        try:
            obj.name = _rebuild_attribute_name(obj, shifted)
        except Exception:
            pass  # 名字重建失败不阻断新增（efx_index 才是导出权威）

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

# EnumProperty 动态回调缓存（GC 陷阱说明见 panels.py 顶部）。
# 脏标志 + 2 秒 TTL：保存后立即失效；手动改文件夹 2 秒内刷新。
# 第二级"具体预设"选择改用 EFX_MT_attribute_preset_picker（Menu，见下方）现场扫描，
# 不再需要 EnumProperty 缓存（Menu.draw 只在用户点开菜单时才调用，不像动态 EnumProperty
# items 那样每次界面重绘都触发，没有同等的缓存必要）。
_attribute_category_items_cache = [("", "(no attribute presets)", "")]
_attribute_category_dirty = True
_attribute_category_cache_time = 0.0
_ATTRIBUTE_CACHE_TTL = 2.0            # 秒


def _invalidate_attribute_preset_cache():
    global _attribute_category_dirty
    _attribute_category_dirty = True


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


class EFX_MT_attribute_preset_picker(bpy.types.Menu):
    """第二级"具体预设"选择菜单：按子组分组，灰字标题（layout.label，不可点）+
    具体预设行（点击直接触发 efx.add_attribute_from_preset，无需再单独点 Add）。

    子组分组顺序/标签见 efx_format.categories.ATTRIBUTE_SUBGROUP_LABELS；分类本身不分
    子组（如 skeleton/spawn_method）则不出现任何标题，所有预设平铺一列。
    """

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
            # 旧扁平预设兜底：__attributes__/ 根目录下早于分类系统的遗留文件
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
