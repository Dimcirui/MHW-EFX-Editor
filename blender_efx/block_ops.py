"""
blender_efx/block_ops.py  —  块级组装：单块的复制/粘贴与块预设保存/新增

功能：
  - build_block_preset_dict(blk_obj)：把单个 EFX_BLOCK 构建为预设 dict（供保存/复制共用）
  - save_block_preset(blk_obj, name)：落盘到 presets/__blocks__/
  - add_block_to_body(body_obj, preset_dict)：按预设在 body 末尾追加单个块
  - list_block_categories() / list_block_presets(slug)：两级下拉的 items（分类 / 类内块）
  - 算子：efx.save_block_preset / efx.add_block_from_block_preset /
          efx.open_block_preset_folder / efx.copy_block / efx.paste_block

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2），bpy 只用长期稳定子集
  - 包内相对导入；不改 efx_format/ 与 io_tree.py（仅复用其函数）
  - 新增块只需：建对象、设好 efx_index，导出端会按实际块数自动重算 attr_count。
  - data_bytes 用 io_tree._resolve_block_data_bytes（与保存 body 预设同款），
    抓到的是用户修改后的当前实际字节。

预设 JSON schema：
{
    "efx_preset_kind": "block",
    "type_hash": "<十进制str>",
    "type_name": "<TRANSFORM3D / 0x... 等>",
    "display_name": "<用户命名（utf-8）>",
    "category": "<分类 slug，如 transform/render；见 efx_format/categories.py>",
    "data_bytes": "<base64>"
}

存盘布局：presets/__blocks__/<category>/<NAME>.json
  按块类型的功能分类自动归入子目录，配合面板两级下拉（先选分类，再选块）。
  根目录下的旧扁平 *.json 仍被 list_block_presets('misc') 兜底读取（向后兼容）。
"""

import base64
import json
import os

import bpy
from bpy.props import EnumProperty, StringProperty

from .presets import _presets_root, _unique_ascii_filename, _read_display_name, _encode_path_ident, _decode_path_ident
from ..efx_format.categories import category_of, category_label, BLOCK_CATEGORY_LABELS
from . import i18n
from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 路径工具
# ─────────────────────────────────────────────────────────────────────────────

def _blocks_preset_dir() -> str:
    """返回块预设根目录 presets/__blocks__/ 的绝对路径。"""
    return os.path.join(_presets_root(), "__blocks__")


def _block_category_dir(slug: str) -> str:
    """返回某分类的块预设子目录 presets/__blocks__/<slug>/。"""
    return os.path.join(_blocks_preset_dir(), slug)


# ─────────────────────────────────────────────────────────────────────────────
# build_block_preset_dict / save_block_preset
# ─────────────────────────────────────────────────────────────────────────────

def build_block_preset_dict(blk_obj: bpy.types.Object) -> dict:
    """
    把 blk_obj（EFX_BLOCK）构建为 preset dict（不落盘）。
    供 save_block_preset（写文件）与 复制块（内存剪贴板）共用。

    data_bytes 用 io_tree._resolve_block_data_bytes 取当前实际字节（含字段编辑）。
    """
    if blk_obj is None or blk_obj.get("~TYPE") != "EFX_BLOCK":
        raise ValueError("build_block_preset_dict：目标对象不是 EFX_BLOCK")

    from . import io_tree
    from ..efx_format.hashes import HASH_TO_NAME

    # 构建导出端所需的 index 映射（与 _collect_block_dicts 同款）
    root = blk_obj.parent.parent if blk_obj.parent else None  # body → root

    def _localmap(type_tag):
        if root is None:
            return {}
        objs = [o for o in bpy.data.objects
                if o.parent == root and o.get("~TYPE") == type_tag]
        objs.sort(key=lambda o: int(o.get("efx_index", 0)))
        return {o: i for i, o in enumerate(objs)}

    extern_map = _localmap("EFX_EXTERN")
    body_map   = _localmap("EFX_BODY")
    play_map   = _localmap("EFX_PLAY")

    try:
        data = io_tree._resolve_block_data_bytes(blk_obj, extern_map, body_map, play_map)
    except Exception:
        data = base64.b64decode(str(blk_obj.get("data_bytes", "")))

    try:
        type_hash = int(str(blk_obj.get("type_hash", "")))
    except (ValueError, TypeError):
        type_hash = 0
    type_name = HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")

    return {
        "efx_preset_kind": "block",
        "type_hash": str(type_hash),
        "type_name": type_name,
        "display_name": type_name,  # 可被 save_block_preset 用用户输入覆盖
        "category": category_of(type_hash),
        "data_bytes": base64.b64encode(data).decode("ascii"),
    }


def save_block_preset(blk_obj: bpy.types.Object, name: str) -> str:
    """
    把 blk_obj 存为块预设 JSON 文件。

    返回保存的路径；name 用于显示名（可含中文），文件名 ASCII 化。
    """
    if not name or not name.strip():
        raise ValueError("save_block_preset：预设名称不能为空")

    preset = build_block_preset_dict(blk_obj)
    preset["display_name"] = name

    # 按块类型的分类存入对应子目录（presets/__blocks__/<slug>/）。
    slug = preset.get("category") or "misc"
    save_dir = _block_category_dir(slug)
    os.makedirs(save_dir, exist_ok=True)

    fallback = str(preset.get("type_name", "block"))
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


def list_block_categories() -> list:
    """
    扫 __blocks__/ 的子目录，返回有预设的分类 EnumProperty items：
      [(slug, 中文名, ""), ...]，按 BLOCK_CATEGORY_LABELS 顺序排列。
    无任何预设时返回 [("", "（无块预设）", "")]。
    """
    root = _blocks_preset_dir()
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
    for slug in BLOCK_CATEGORY_LABELS:
        if slug in have:
            result.append((slug, category_label(slug, lang), ""))
    # 出现了未登记的 slug（用户手建目录）也列出来
    for slug in sorted(have):
        if slug not in BLOCK_CATEGORY_LABELS:
            result.append((slug, slug, ""))

    if not result:
        return [("", T("block.no_preset"), "")]
    return result


def list_block_presets(category_slug: str) -> list:
    """
    列举某分类子目录下的块预设 EnumProperty items：
      [(_encode_path_ident(path), display_name, type_name), ...]
    misc 额外包含 __blocks__/ 根下的旧扁平预设（向后兼容）。
    """
    if not category_slug:
        return [("", T("block.pick_category"), "")]

    dirs = [_block_category_dir(category_slug)]
    if category_slug == "misc":
        dirs.append(_blocks_preset_dir())  # 旧扁平预设兜底

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
        return [("", T("block.cat_empty"), "")]
    return result


def _is_autogen_name(display_name: str, type_name: str) -> bool:
    """display_name 是否为自动生成式（空 / 等于 type_name / 「TYPE（中文）」），而非用户自定义。"""
    if display_name in ("", type_name):
        return True
    return display_name.startswith(type_name + "（") and display_name.endswith("）")


# ─────────────────────────────────────────────────────────────────────────────
# add_block_to_body  —  核心新增逻辑
# ─────────────────────────────────────────────────────────────────────────────

def add_block_to_body(body_obj: bpy.types.Object, preset_dict: dict) -> bpy.types.Object:
    """
    按 preset_dict 在 body 末尾追加单个 EFX_BLOCK。

    参数
    ----
    body_obj    : ~TYPE == 'EFX_BODY' 的对象
    preset_dict : {"efx_preset_kind":"block","type_hash":str,"data_bytes":b64,...}

    返回
    ----
    新建的 EFX_BLOCK 对象。

    说明
    ----
    - 新块 efx_index = 同 body 内现有块最大 index + 1
    - attr_count 由导出端（io_tree §4c）按实际块数重算，无需手动维护
    - EXTERNREFERENCE 引用指针在 init_block_props 内初始化；PTLIFE/PTCOLLISION
      在本函数末尾补充指针化（越界 baked 值强制转可编辑悬空，供用户指定 Play）
    """
    from . import io_tree
    from . import fields as _fields
    from ..efx_format.efxfile import AttrBlock
    from ..efx_format.hashes import HASH_TO_NAME

    if body_obj is None or body_obj.get("~TYPE") != "EFX_BODY":
        raise ValueError("add_block_to_body：目标对象不是 EFX_BODY")
    if preset_dict.get("efx_preset_kind") != "block":
        raise ValueError("add_block_to_body：不是块预设（efx_preset_kind != 'block'）")

    try:
        type_hash = int(str(preset_dict["type_hash"]))
        data_bytes = base64.b64decode(preset_dict["data_bytes"])
    except (KeyError, ValueError, Exception) as exc:
        raise ValueError(f"add_block_to_body：预设格式错误：{exc}")

    # ── 找集合（block 与 body 同集合）────────────────────────────────────────
    cols = body_obj.users_collection
    collection = cols[0] if cols else bpy.context.scene.collection

    # ── 计算新 efx_index ─────────────────────────────────────────────────────
    max_idx = -1
    for obj in bpy.data.objects:
        if obj.parent == body_obj and obj.get("~TYPE") == "EFX_BLOCK":
            try:
                max_idx = max(max_idx, int(obj.get("efx_index", 0)))
            except (ValueError, TypeError):
                pass
    new_idx = max_idx + 1

    # ── 构建显示名 ────────────────────────────────────────────────────────────
    type_name = HASH_TO_NAME.get(type_hash, f"0x{type_hash:08X}")
    parent_label = str(body_obj.get("efx_raw_label", ""))
    nn = str(new_idx).zfill(2) if new_idx < 100 else str(new_idx)
    blk_name = f"[{parent_label}] {nn} {type_name}" if parent_label else f"{nn} {type_name}"

    # ── 建 EFX_BLOCK 对象 ─────────────────────────────────────────────────────
    blk_obj = io_tree._new_empty(blk_name, collection)
    blk_obj["~TYPE"]         = "EFX_BLOCK"
    blk_obj["efx_index"]     = new_idx
    blk_obj["type_hash"]     = str(type_hash)
    blk_obj["data_bytes"]    = base64.b64encode(data_bytes).decode("ascii")
    blk_obj["efx_type_name"] = type_name
    blk_obj.parent           = body_obj

    # ── 初始化 efx_block PropertyGroup ────────────────────────────────────────
    # 构建 extern 映射（供 EXTERNREFERENCE 块指针化）
    root_obj = body_obj.parent
    extern_objs = {}
    if root_obj is not None and root_obj.get("~TYPE") == "EFX_ROOT":
        for obj in bpy.data.objects:
            if obj.parent == root_obj and obj.get("~TYPE") == "EFX_EXTERN":
                try:
                    extern_objs[int(obj.get("efx_index", 0))] = obj
                except (ValueError, TypeError):
                    pass

    blk = AttrBlock(type_hash=type_hash, data_bytes=data_bytes)
    try:
        _fields.init_block_props(
            blk_obj, blk,
            extern_objs_by_index=extern_objs,
            count_extern=len(extern_objs),
        )
    except Exception:
        # 安全回退：efx_block 保持 is_editable=False
        pass

    # ── PTLIFE / PTCOLLISION 引用指针化 ───────────────────────────────────────
    # init_block_props 只处理 EXTERNREFERENCE；PTLIFE/PTCOLLISION 在 io_tree 导入时
    # 由独立第二 pass 指针化，而单块新增路径没有该 pass → 此处补上。
    # 关键：预设里 baked 的 relationIndex/ieIndex 来自源文件，对新文件几乎必然越界，
    # init_*_ref_props 会因此置 pointerized=False（不可编辑、导出保留陈旧值）。
    # 新增块无 byte-perfect 义务，故越界时**强制指针化为悬空**，让用户能在面板里
    # 指定合法 Play（导出按段局部 index 重写；未指定则 validate 报悬空挡导出）。
    if root_obj is not None and root_obj.get("~TYPE") == "EFX_ROOT":
        play_objs = {}
        for obj in bpy.data.objects:
            if obj.parent == root_obj and obj.get("~TYPE") == "EFX_PLAY":
                try:
                    play_objs[int(obj.get("efx_index", 0))] = obj
                except (ValueError, TypeError):
                    pass
        count_play = len(play_objs)
        if count_play > 0:
            try:
                from ..efx_format.hashes import PTLIFE as _PTLIFE, PTCOLLISION as _PTCOLLISION
                from . import body_play_ref as _bpr
                if type_hash == _PTLIFE:
                    _bpr.init_ptlife_ref_props(blk_obj, data_bytes, play_objs, count_play)
                    p = blk_obj.efx_ptlife_ref
                    if not p.relation_pointerized:
                        p.relation_pointerized = True   # 越界 baked 值 → 转可编辑悬空
                        p.relation_play_ptr = None
                elif type_hash == _PTCOLLISION:
                    _bpr.init_ptcollision_ref_props(blk_obj, data_bytes, play_objs, count_play)
                    p = blk_obj.efx_ptcollision_ref
                    if not p.ie_pointerized:
                        p.ie_pointerized = True
                        p.ie_none = False
                        p.ie_play_ptr = None
            except Exception:
                # 任何异常安全跳过（保持默认 pointerized=False）
                pass

    # attr_count 由导出端自动重算，无需设 labels_dirty（块不在标签表）
    return blk_obj


def add_block_to_body_from_path(body_obj: bpy.types.Object, path: str) -> bpy.types.Object:
    """从 JSON 文件路径读取预设并新增到 body 末尾。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            preset = json.load(f)
    except Exception as exc:
        raise ValueError(f"add_block_to_body_from_path：读取预设失败：{exc}")
    return add_block_to_body(body_obj, preset)


# ─────────────────────────────────────────────────────────────────────────────
# 内存剪贴板（会话级）
# ─────────────────────────────────────────────────────────────────────────────

# 模块级整-块剪贴板：build_block_preset_dict 的结果（会话内有效）。
_BLOCK_CLIPBOARD: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：保存块预设
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_save_block_preset(bpy.types.Operator):
    """把当前选中的 EFX_BLOCK 保存为整块预设（供其他 body 新增使用）"""

    bl_idname      = "efx.save_block_preset"
    bl_label       = "Save as Block Preset"
    bl_description = "Save the current EFX_BLOCK (with edited field values) as a reusable whole-block preset"
    bl_options     = {"REGISTER"}

    preset_name: StringProperty(
        name="Preset Name",
        description="Preset name to save (without .json)",
        default="my_block",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def invoke(self, context, event):
        obj = context.active_object
        if obj is not None:
            type_name = str(obj.get("efx_type_name", "block")).strip()
            self.preset_name = type_name or "my_block"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        obj = context.active_object
        try:
            path = save_block_preset(obj, self.preset_name)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to save block preset: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Block preset saved: {os.path.basename(path)}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：从预设新增块
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_block_from_block_preset(bpy.types.Operator):
    """按选中的块预设，在当前 EFX_BODY 末尾新增一个块"""

    bl_idname      = "efx.add_block_from_block_preset"
    bl_label       = "Add Block"
    bl_description = "Append a block to the end of the current EFX_BODY from the selected whole-block preset (attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    preset_path: StringProperty(
        name="Preset Path (encoded)",
        description="Block preset JSON path to add (base64-encoded)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def execute(self, context):
        body_obj = context.active_object
        if body_obj is None or body_obj.get("~TYPE") != "EFX_BODY":
            self.report({"ERROR"}, "Select an EFX_BODY object first")
            return {"CANCELLED"}
        if not self.preset_path:
            self.report({"ERROR"}, "No block preset selected")
            return {"CANCELLED"}

        actual_path = _decode_path_ident(self.preset_path)
        try:
            new_blk = add_block_to_body_from_path(body_obj, actual_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add block: {exc}")
            return {"CANCELLED"}

        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_blk.select_set(True)
            context.view_layer.objects.active = new_blk
        except Exception:
            pass

        self.report({"INFO"}, f"Block added: {new_blk.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：打开块预设文件夹
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_open_block_preset_folder(bpy.types.Operator):
    """打开块预设所在文件夹（资源管理器 / Finder）"""

    bl_idname      = "efx.open_block_preset_folder"
    bl_label       = "Open Block Preset Folder"
    bl_description = "Open the __blocks__ preset directory in the system file manager"
    bl_options     = {"REGISTER"}

    def execute(self, context):
        folder = _blocks_preset_dir()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 算子：复制 / 粘贴 块（内存剪贴板）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_copy_block(bpy.types.Operator):
    """把当前 EFX_BLOCK 复制到内存剪贴板（供"粘贴块"快速新增）"""

    bl_idname      = "efx.copy_block"
    bl_label       = "Copy Block"
    bl_description = "Copy the current EFX_BLOCK (with edited field values) to the in-memory clipboard"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BLOCK"

    def execute(self, context):
        global _BLOCK_CLIPBOARD
        try:
            _BLOCK_CLIPBOARD = build_block_preset_dict(context.active_object)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to copy block: {exc}")
            return {"CANCELLED"}
        type_name = _BLOCK_CLIPBOARD.get("type_name", "")
        self.report({"INFO"}, f"Block copied to clipboard ({type_name})")
        return {"FINISHED"}


class EFX_OT_paste_block(bpy.types.Operator):
    """把剪贴板的块粘贴（新增）到当前 EFX_BODY 末尾"""

    bl_idname      = "efx.paste_block"
    bl_label       = "Paste Block"
    bl_description = "Append the clipboard block to the end of the current EFX_BODY (attr_count auto-recomputed)"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (bool(_BLOCK_CLIPBOARD)
                and obj is not None
                and obj.get("~TYPE") == "EFX_BODY")

    def execute(self, context):
        if not _BLOCK_CLIPBOARD:
            self.report({"ERROR"}, "Clipboard is empty (use Copy Block first)")
            return {"CANCELLED"}
        body_obj = context.active_object
        if body_obj is None or body_obj.get("~TYPE") != "EFX_BODY":
            self.report({"ERROR"}, "Select an EFX_BODY object first")
            return {"CANCELLED"}
        try:
            new_blk = add_block_to_body(body_obj, _BLOCK_CLIPBOARD)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to paste block: {exc}")
            return {"CANCELLED"}
        try:
            for o in context.selected_objects:
                o.select_set(False)
            new_blk.select_set(True)
            context.view_layer.objects.active = new_blk
        except Exception:
            pass
        self.report({"INFO"}, f"Block pasted: {new_blk.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_save_block_preset,
    EFX_OT_add_block_from_block_preset,
    EFX_OT_open_block_preset_folder,
    EFX_OT_copy_block,
    EFX_OT_paste_block,
)

# EnumProperty 动态回调的 GC 陷阱修法（见 panels.py 顶部完整说明）：
# 每个 enum 用各自独立的模块级全局缓存 + 回调里 global 重新赋值再 return 全局变量本身。
_block_category_items_cache = [("", "(no block presets)", "")]
_block_whole_preset_items_cache = [("", "(pick a category)", "")]


def _get_block_category_items(self, context):
    """WindowManager.efx_block_category_enum 的动态 items 回调（第一级：分类）。"""
    global _block_category_items_cache
    try:
        _block_category_items_cache = list_block_categories()
    except Exception:
        _block_category_items_cache = [("", "(category load error)", "")]
    return _block_category_items_cache


def _get_block_whole_preset_items(self, context):
    """
    WindowManager.efx_block_whole_preset_enum 的动态 items 回调（第二级：类内块）。
    读取第一级 efx_block_category_enum 的当前值来过滤。
    """
    global _block_whole_preset_items_cache
    try:
        wm = context.window_manager if context else None
        slug = getattr(wm, "efx_block_category_enum", "") if wm else ""
        _block_whole_preset_items_cache = list_block_presets(slug)
    except Exception:
        _block_whole_preset_items_cache = [("", "(preset load error)", "")]
    return _block_whole_preset_items_cache


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.efx_preset_mode = EnumProperty(
        name="Preset Mode",
        items=[
            ("BODY",  "Body",  ""),
            ("BLOCK", "Block", ""),
        ],
        default="BODY",
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.efx_block_category_enum = EnumProperty(
        name="Block Category",
        description="Pick the functional category of the block first",
        items=_get_block_category_items,
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.efx_block_whole_preset_enum = EnumProperty(
        name="Block Preset",
        description="Pick the whole-block preset to add within the selected category",
        items=_get_block_whole_preset_items,
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
