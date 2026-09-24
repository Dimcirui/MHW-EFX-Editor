"""载入 UVSEQUENCE 引用的 .uvs 与可选的 .tex 参考图。

维护约束：
- 宿主 Empty 挂在源属性下、放在 `_uvs` 集合，仅保存 UVS 编辑数据；游戏路径和 sequenceNo 始终由源属性持有。
- 路径按配置根、nativePC、Model Editor 配置与 EFX 目录的优先级解析。
- Model Editor 仅为可选转换器；不可用时尝试已转换图像，仍失败则保留已载入的 .uvs。
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from .i18n import T
from . import mod3_link as _mod3
from . import root_collection as _rc
from . import uvs_io as _uvs_io

#: .tex 转换不可用时查找已转换图像的优先级。
_IMAGE_EXTS = (".dds", ".png", ".tga", ".tif", ".tiff", ".exr")


# 属性与外部宿主。

def _is_uvsequence(obj):
    from ..efx_format.hashes import UVSEQUENCE

    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        return int(obj.efx_block.type_hash_str) == UVSEQUENCE
    except Exception:
        return False


def _resolve_attribute(obj):
    """将 UVSEQUENCE 属性或其宿主解析为源属性；无有效来源时返回 None。"""
    if _is_uvsequence(obj):
        return obj
    src = source_attribute_of(obj)
    return src if _is_uvsequence(src) else None


#: EFX 根内的外部 UVS 宿主集合标记。
_UVS_LINK_MARKER = "EFX_UVS_LINK"
#: 区分有源属性的宿主与 standalone.py 管理的无主 UVS。
_UVS_LINK_ITEM_MARKER = "EFX_UVS_LINK_ITEM"


def _uvs_link_collection_name(root_col):
    """外层总集合名：EFX 顶层集合名去掉 .efx 后缀 + "_uvs"（如 em001_000_uvs）。"""
    name = getattr(root_col, "name", "") or "efx"
    if name.lower().endswith(".efx"):
        name = name[:-4]
    return name + "_uvs"


def ensure_host_for_attribute(blk_obj, context=None):
    """返回属性的外部宿主；缺失时创建，并保持宿主到源属性的反向指针。"""
    existing = getattr(blk_obj, "efx_uvs_target", None)
    if existing is not None:
        if getattr(existing, "efx_uvs_source", None) is None:
            existing.efx_uvs_source = blk_obj  # 兼容缺少反向指针的已有宿主。
        if existing.parent is None:
            existing.parent = blk_obj
        return existing

    host = bpy.data.objects.new("%s [uvs]" % blk_obj.name, None)
    host.empty_display_type = "PLAIN_AXES"
    host.empty_display_size = 0.1
    host["~TYPE"] = _UVS_LINK_ITEM_MARKER
    host.efx_uvs_source = blk_obj
    # 挂在源属性下便于在大纲里找到；集合归属仍是 `_uvs`。
    host.parent = blk_obj

    root_col = _rc.find_root_collection(blk_obj)
    if root_col is not None:
        col = _rc.ensure_linked_collection(
            root_col, _UVS_LINK_MARKER, _uvs_link_collection_name(root_col), "COLOR_04")
        col.objects.link(host)
    else:
        # 无根集合时仍保留宿主，避免丢失已载入的数据。
        (context or bpy.context).scene.collection.objects.link(host)

    blk_obj.efx_uvs_target = host
    return host


def hide_link_collection(context, root_col):
    """隐藏 EFX 根下的 `_uvs` 集合。"""
    for c in getattr(root_col, "children", ()):
        if c.get("~TYPE") == _UVS_LINK_MARKER:
            _mod3.hide_collection(context, c)


def source_attribute_of(obj):
    """返回外部宿主指向的 UVSEQUENCE 属性；无来源时返回 None。"""
    if obj is None:
        return None
    return getattr(obj, "efx_uvs_source", None)


def _uvs_relpath(blk_obj):
    """返回当前属性树中的 .uvs 相对路径，包含尚未保存的编辑。"""
    return (_uvs_io._get_uvsequence_path(blk_obj) or "").strip()


def _sequence_no(blk_obj):
    """返回 sequenceNo 对应的 group 下标；缺失时为 0。"""
    try:
        for item in blk_obj.efx_block.field_items:
            if item.ori_name == "sequenceNo":
                return int(item.int_value)
    except Exception:
        pass
    return 0


def iter_uvsequence_attributes(root_obj):
    """EFX_ROOT 下所有填了 uvsPath 的 UVSEQUENCE 属性，yield (blk_obj, relpath)。"""
    for entry in _rc.collect_top_level(root_obj, "EFX_ENTRY"):
        for blk in entry.children:
            if not _is_uvsequence(blk):
                continue
            rel = _uvs_relpath(blk)
            if rel:
                yield blk, rel


def efx_dir_of(obj_or_col):
    """返回导入源目录；缺少有效 src_path 时返回 None，不猜测路径。"""
    col = obj_or_col
    if not isinstance(col, bpy.types.Collection):
        col = _rc.find_root_collection(obj_or_col)
    if col is None:
        return None
    src = col.get("src_path") or ""
    if not src:
        return None
    d = os.path.dirname(src)
    return d if os.path.isdir(d) else None


# 路径解析。

def model_editor_chunk_paths():
    """返回 Model Editor 偏好中有效的 chunk 目录，不依赖其 addon 名称。"""
    out = []
    try:
        addons = bpy.context.preferences.addons
    except Exception:
        return out
    for addon in addons:
        prefs = getattr(addon, "preferences", None)
        items = getattr(prefs, "chunkPathList_items", None)
        if not items:
            continue
        for it in items:
            p = bpy.path.abspath(getattr(it, "path", "") or "")
            if p and os.path.isdir(p) and p not in out:
                out.append(p)
    return out


def resolve_game_path(relpath, ext, chunk_root, efx_dir=None):
    """游戏相对路径 → 磁盘绝对路径；找不到返回 None。

    `ext` 形如 ".uvs" / ".tex"：相对路径通常不带扩展名，带了就不重复补。
    """
    rel = (relpath or "").replace("\\", "/").lstrip("/")
    if not rel:
        return None
    if not rel.lower().endswith(ext):
        rel += ext

    candidates = []
    if chunk_root:
        candidates.append(os.path.join(bpy.path.abspath(chunk_root), rel))
    native = _mod3.find_native_root(efx_dir)
    if native:
        candidates.append(os.path.join(native, rel))
    # 复用 Model Editor 配置的提取目录。
    for p in model_editor_chunk_paths():
        candidates.append(os.path.join(p, rel))
    if efx_dir:
        candidates.append(os.path.join(efx_dir, rel))
        candidates.append(os.path.join(efx_dir, os.path.basename(rel)))
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    return None


# .tex 转换与回退加载。

def _model_editor_tex_api():
    """返回可用的 Model Editor tex 载入接口；未安装或不可用时返回 None。"""
    import importlib
    import sys

    def _pack(mod):
        root = mod.__name__.split(".modules.tex.tex_function")[0]
        load = getattr(mod, "loadTex", None)
        if load is None:
            return None
        try:
            tc = importlib.import_module(root + ".modules.ddsconv.texconv").Texconv
        except Exception:
            tc = None
        addon_name = ""
        try:
            addon_name = getattr(importlib.import_module(root + ".config"),
                                 "__addon_name__", "") or ""
        except Exception:
            pass
        return (load, tc, addon_name)

    for key, mod in list(sys.modules.items()):
        if key.endswith(".modules.tex.tex_function") and mod is not None:
            got = _pack(mod)
            if got:
                return got

    if not hasattr(bpy.ops, "mhw_tex") and not hasattr(bpy.ops, "mhw_mod3"):
        return None
    try:
        import addon_utils
    except Exception:
        return None
    for mod in addon_utils.modules():
        pkg = getattr(mod, "__package__", None) or getattr(mod, "__name__", "")
        if not pkg:
            continue
        try:
            tm = importlib.import_module(pkg + ".modules.tex.tex_function")
        except Exception:
            continue
        got = _pack(tm)
        if got:
            return got
    return None


def tex_loader_available():
    """返回当前是否可通过 Model Editor 转换 .tex。"""
    return _model_editor_tex_api() is not None


def _tex_cache_dir(addon_name):
    """返回持久缓存目录；仅在无法创建用户缓存时退回 Blender 临时目录。"""
    if addon_name:
        try:
            prefs = bpy.context.preferences.addons[addon_name].preferences
            d = bpy.path.abspath(getattr(prefs, "textureCachePath", "") or "")
            if d:
                return d
        except Exception:
            pass
    base = os.path.join(os.path.expanduser("~"), ".efx_editor")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = bpy.app.tempdir or base
    return os.path.join(base, "efx_tex_cache")


def _use_dds(addon_name):
    """按当前 Blender 能力及 Model Editor 偏好决定是否直接读取 DDS。"""
    auto = bpy.app.version >= (4, 2, 0)
    if addon_name:
        try:
            prefs = bpy.context.preferences.addons[addon_name].preferences
            return bool(getattr(prefs, "useDDS", auto)) and auto
        except Exception:
            pass
    return auto


def _find_converted_sibling(texpath, cache_dir):
    """返回 .tex 同目录或缓存中的同名已转换图像。"""
    stem = os.path.splitext(os.path.basename(texpath))[0]
    dirs = [os.path.dirname(texpath)]
    if cache_dir and os.path.isdir(cache_dir):
        dirs.append(cache_dir)
    for d in dirs:
        for ext in _IMAGE_EXTS:
            cand = os.path.join(d, stem + ext)
            if os.path.isfile(cand):
                return cand
    return None


def _mark_persistent(img):
    """保留非真实引用的参考图，且不将像素数据打包进 .blend。"""
    if img is not None:
        try:
            img.use_fake_user = True
        except Exception:
            pass
    return img


def load_tex_image(texpath, rel_for_cache=None):
    """载入 .tex 对应图像；优先使用转换器，随后查找已转换的同名图。"""
    if not texpath or not os.path.isfile(texpath):
        return None

    api = _model_editor_tex_api()
    addon_name = api[2] if api else ""
    cache_dir = _tex_cache_dir(addon_name)

    if api is not None:
        load_tex, texconv_cls, _ = api
        rel = (rel_for_cache or os.path.basename(texpath)).replace("\\", "/").lstrip("/")
        out_path = os.path.join(cache_dir, os.path.normpath(rel))
        if not out_path.lower().endswith(".tex"):
            out_path += ".tex"
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass
        stale = _cache_is_stale(texpath, out_path)
        for use_dds in _dds_attempts(addon_name):
            try:
                conv = texconv_cls() if texconv_cls is not None else None
                images = load_tex(texpath, out_path, conv, stale, use_dds)
                for img in images or ():
                    if img is not None:
                        if stale:
                            img = _reload_same_path(img)
                        return _mark_persistent(img)
            except Exception:
                continue

    sib = _find_converted_sibling(texpath, cache_dir)
    if sib:
        try:
            return _mark_persistent(bpy.data.images.load(sib, check_existing=True))
        except Exception:
            return None
    return None


def _cache_is_stale(texpath, out_path):
    """转换缓存比 .tex 旧时返回 True；没有缓存返回 False（转换器会自行生成）。"""
    try:
        src = os.path.getmtime(texpath)
    except OSError:
        return False
    base = os.path.splitext(out_path)[0]
    for ext in (".dds", ".tif", ".tga", ".exr"):
        p = base + ext
        if os.path.isfile(p):
            try:
                if os.path.getmtime(p) < src:
                    return True
            except OSError:
                pass
    return False


def _reload_same_path(img):
    """缓存重新生成后重读已有的同路径图像，并删掉转换器新建的副本。"""
    path = bpy.path.abspath(img.filepath)
    same = [i for i in bpy.data.images
            if i is not img and bpy.path.abspath(i.filepath) == path]
    if not same:
        img.reload()
        return img
    keep = same[0]
    keep.reload()
    if img.users - (1 if img.use_fake_user else 0) == 0:
        bpy.data.images.remove(img)
    return keep


def _dds_attempts(addon_name):
    """返回转换尝试顺序，在可直接读取 DDS 时保留该回退。"""
    first = _use_dds(addon_name)
    if first or bpy.app.version < (4, 2, 0):
        return (first,)
    return (first, True)


# 链式载入。

def link_one(blk_obj, chunk_root, efx_dir=None, with_texture=True, uvs_cache=None):
    """载入一个属性的 .uvs 与可选参考图，并返回可汇总的结果状态。"""
    out = {"uvs": False, "tex": False, "rel": "", "reason": ""}
    rel = _uvs_relpath(blk_obj)
    out["rel"] = rel
    if not rel:
        out["reason"] = "no_path"
        return out

    abspath = resolve_game_path(rel, ".uvs", chunk_root, efx_dir)
    if abspath is None:
        out["reason"] = "uvs_not_found"
        return out

    host = ensure_host_for_attribute(blk_obj)
    props = getattr(host, "efx_uvs", None)
    if props is None:
        out["reason"] = "no_props"
        return out

    data = uvs_cache.get(abspath) if uvs_cache is not None else None
    if data is None:
        try:
            with open(abspath, "rb") as f:
                data = f.read()
        except OSError:
            out["reason"] = "uvs_read_failed"
            return out
        if uvs_cache is not None:
            uvs_cache[abspath] = data

    try:
        _uvs_io._populate_props(props, data)
        props.filepath = abspath
    except Exception:
        out["reason"] = "uvs_parse_failed"
        return out
    out["uvs"] = True

    if not with_texture:
        return out

    # sequenceNo 选择 group；该 group 的首个非空路径作为参考图。
    group_idx = _sequence_no(blk_obj)
    if not (0 <= group_idx < len(props.groups)):
        out["reason"] = "group_out_of_range"
        return out
    grp = props.groups[group_idx]
    tex_rel = ""
    for i in range(max(0, int(grp.map_count))):
        cand = (getattr(grp, "path%d" % i, "") or "").strip()
        if cand:
            tex_rel = cand
            break
    if not tex_rel:
        out["reason"] = "no_tex_path"
        return out

    tex_abs = resolve_game_path(tex_rel, ".tex", chunk_root, efx_dir)
    if tex_abs is None:
        out["reason"] = "tex_not_found"
        return out
    img = load_tex_image(tex_abs, tex_rel)
    if img is None:
        out["reason"] = "tex_convert_failed"
        return out
    try:
        props.ref_image_name = img.name
        # 编辑器显示的组必须与属性实际引用的 sequenceNo 一致。
        props.group_index = group_idx
    except Exception:
        pass
    out["tex"] = True
    return out


def link_root(root_col, chunk_root, efx_dir=None, with_texture=True):
    """载入根下所有 UVSEQUENCE；同一路径的 .uvs 在本次操作中只读取一次。"""
    n_uvs = n_tex = 0
    problems = []
    cache = {}
    for blk, _rel in iter_uvsequence_attributes(root_col):
        r = link_one(blk, chunk_root, efx_dir, with_texture, cache)
        if r["uvs"]:
            n_uvs += 1
        if r["tex"]:
            n_tex += 1
        if r["reason"]:
            problems.append((blk.name, r["rel"], r["reason"]))
    return n_uvs, n_tex, problems


def report_problems(op, problems, n_uvs, n_tex):
    """报告载入计数及未解决项。"""
    if n_uvs or n_tex:
        op.report({"INFO"}, T("uvslink.done").format(n_uvs, n_tex))
    if problems:
        detail = "；".join("%s（%s）" % (name, T("uvslink.reason_" + reason))
                          for name, _rel, reason in problems[:5])
        op.report({"WARNING"}, T("uvslink.failed").format(len(problems), detail))
    elif not n_uvs:
        op.report({"WARNING"}, T("uvslink.nothing"))


# 算子。

class EFX_OT_uvs_link_load(Operator):
    """按 UVSEQUENCE 的游戏路径自动载入 .uvs（并尽量把序列帧贴图一起载入）"""

    bl_idname = "efx.uvs_link_load"
    bl_label = "Quick Load .uvs"
    bl_options = {"REGISTER", "UNDO"}

    scope: EnumProperty(
        name="Scope",
        items=[("ATTRIBUTE", "This attribute", "Only the selected UVSEQUENCE attribute"),
               ("ROOT", "Whole EFX", "Every UVSEQUENCE attribute in this EFX")],
        default="ATTRIBUTE",
        options={"SKIP_SAVE"},
    )
    with_texture: BoolProperty(
        name="Also load the sprite sheet",
        description="Convert the .tex referenced by the .uvs group and bind it as the "
                    "reference image (needs MHW Model Editor; falls back to an already "
                    "converted image sitting next to the .tex)",
        default=True,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if _resolve_attribute(obj) is not None:
            return True
        return _rc.find_root_collection(obj) is not None

    def execute(self, context):
        obj = context.active_object
        chunk_root = getattr(context.scene, "efx_chunk_root", "") or ""

        # 单属性路径始终使用持有游戏字段的源属性。
        attr = _resolve_attribute(obj)
        if self.scope == "ATTRIBUTE" and attr is not None:
            efx_dir = efx_dir_of(attr)
            r = link_one(attr, chunk_root, efx_dir, self.with_texture, {})
            problems = [(attr.name, r["rel"], r["reason"])] if r["reason"] else []
            report_problems(self, problems, 1 if r["uvs"] else 0, 1 if r["tex"] else 0)
            return {"FINISHED"} if r["uvs"] else {"CANCELLED"}

        root_col = _rc.find_root_collection(obj)
        if root_col is None:
            self.report({"ERROR"}, T("uvslink.no_root"))
            return {"CANCELLED"}
        n_uvs, n_tex, problems = link_root(
            root_col, chunk_root, efx_dir_of(root_col), self.with_texture)
        report_problems(self, problems, n_uvs, n_tex)
        return {"FINISHED"} if n_uvs else {"CANCELLED"}


_CLASSES = (EFX_OT_uvs_link_load,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # 属性持有指向其外部 UVS 数据宿主的指针。
    bpy.types.Object.efx_uvs_target = bpy.props.PointerProperty(
        name="UVS Data Host",
        description="External object holding this UVSEQUENCE attribute's UVS data",
        type=bpy.types.Object,
    )
    # 宿主通过反向指针解析持有游戏字段的源属性。
    bpy.types.Object.efx_uvs_source = bpy.props.PointerProperty(
        name="UVS Source Attribute",
        description="The UVSEQUENCE attribute this external UVS host was created for",
        type=bpy.types.Object,
    )


def unregister():
    if hasattr(bpy.types.Object, "efx_uvs_source"):
        del bpy.types.Object.efx_uvs_source
    if hasattr(bpy.types.Object, "efx_uvs_target"):
        del bpy.types.Object.efx_uvs_target
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
