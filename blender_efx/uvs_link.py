r"""
blender_efx/uvs_link.py  —  UVSEQUENCE 引用的 .uvs（以及它引用的 .tex）链式自动载入

定位（与 mod3_link 对称）
------------------------
EFX 里序列帧是**三层引用**：

    .efx（UVSEQUENCE.uvsPath） → .uvs（group 的贴图槽） → .tex（真正的序列帧大图）

手动一层层找太麻烦，所以照 `mod3_link.py`（MESH → mod3 → mrl3 → 材质）那套「正
层级快速载入」做一条链：解析路径 → 载入 .uvs → 取 sequenceNo 指的那个 group 的
贴图路径 → 载入 .tex 转成 Blender 图像 → 回填到该属性的参考图槽
（`EFXUVSProps.ref_image_name`，UVS 编辑器本来就用它当参考图）。
之后用户照旧可以手动换 .uvs / 换图，这里只负责「一键先给个正确的默认」。

路径解析
--------
与 mod3_link 完全同一套根优先级（直接复用 `mod3_link.find_native_root`）：
① 手设 `Scene.efx_chunk_root`（填了才用）② 从 .efx 位置向上追溯到的第一个
nativePC（默认、自动）③ .efx 同目录兜底。找不到不静默失败，收集进 unresolved
统一提示。**比 mod3_link 多一档**：中间插一条「Model Editor 里已存的 chunk 目录
列表」——官方资源（vfx/uvs、vfx/dds）在游戏提取目录里，而 mod 工程目录里只有
自己新做的那几个文件，装了 Model Editor 的人那边早就设过了，不必再填一遍。

.tex → 图像
-----------
MHW 的 `.tex` 容器 Blender 读不了，得先转 DDS。这一步**不自己实现**：MHW Model
Editor 已经有整条 tex→dds→(tif/tga)→`bpy.data.images` 的实现
（`modules/tex/tex_function.loadTex`），它在场就借用，跟 mod3 联动同一个边界——
**添头非依赖**，缺席就降级：退回「在 .tex 旁边/缓存目录里找一张已经转好的
.dds/.png/.tga/.tif」，也找不到就只载 .uvs、如实报一句。

约束（CLAUDE.md）
-----------------
- 纯胶水层；只读属性字段（不重序列化）→ 不碰 byte-perfect。
- Python 3.10 兼容；bpy 稳定子集；对 Model Editor 的调用全部经在场检测 + try 守卫。
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from .i18n import T
from . import mod3_link as _mod3
from . import root_collection as _rc
from . import uvs_io as _uvs_io

#: .tex 转不了时，退而求其次去找的已转好格式（按优先级）
_IMAGE_EXTS = (".dds", ".png", ".tga", ".tif", ".tiff", ".exr")


# ─────────────────────────────────────────────────────────────────────────────
# 属性侧读取
# ─────────────────────────────────────────────────────────────────────────────

def _is_uvsequence(obj):
    from ..efx_format.hashes import UVSEQUENCE

    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        return int(obj.efx_block.type_hash_str) == UVSEQUENCE
    except Exception:
        return False


#: 批量导入/一键载入共用的外部 UVS 载体集合标记（绿色，嵌在其 EFX 根集合内，
#: 导出/校验天然忽略，见 root_collection.ensure_linked_collection）。
_UVS_LINK_MARKER = "EFX_UVS_LINK"
#: 挂在载体 Empty 自己身上的标记：与 standalone.py 的 "EFX_UVS"（完全无主）区分开，
#: 否则会被 standalone.is_standalone() 误认成「无主 UVS」而给出关闭入口/丢进
#: 无 root 的独立场景（那边的判据是纯看 ~TYPE，不看 parent/归属）。
_UVS_LINK_ITEM_MARKER = "EFX_UVS_LINK_ITEM"


def _uvs_link_collection_name(root_col):
    """外层总集合名：EFX 顶层集合名去掉 .efx 后缀 + "_uvs"（如 em001_000_uvs）。"""
    name = getattr(root_col, "name", "") or "efx"
    if name.lower().endswith(".efx"):
        name = name[:-4]
    return name + "_uvs"


def ensure_host_for_attribute(blk_obj, context=None):
    """UVSEQUENCE 属性缺外部宿主（`efx_uvs_target`）时新建一个：数据不再存在属性
    对象自己身上，而是一个独立 Empty，收进这个 .efx 的绿色 `{efx}_uvs` 子集合——
    同一个 .efx 下批量导入的多个 UVSEQUENCE 共用这一个集合，不是各建各的。
    已有宿主（不管是不是本函数建的）直接返回，不重复建。
    """
    existing = getattr(blk_obj, "efx_uvs_target", None)
    if existing is not None:
        return existing

    host = bpy.data.objects.new("%s [uvs]" % blk_obj.name, None)
    host.empty_display_type = "PLAIN_AXES"
    host.empty_display_size = 0.1
    host["~TYPE"] = _UVS_LINK_ITEM_MARKER

    root_col = _rc.find_root_collection(blk_obj)
    if root_col is not None:
        col = _rc.ensure_linked_collection(
            root_col, _UVS_LINK_MARKER, _uvs_link_collection_name(root_col), "COLOR_04")
        col.objects.link(host)
    else:
        # 理论上不会发生（属性必属于某个 EFX_ROOT）——退回场景根，好歹别丢东西
        (context or bpy.context).scene.collection.objects.link(host)

    blk_obj.efx_uvs_target = host
    return host


def _uvs_relpath(blk_obj):
    """UVSEQUENCE 属性的 .uvs 游戏相对路径（**读的是当前属性树，反映未保存的编辑**）。"""
    return (_uvs_io._get_uvsequence_path(blk_obj) or "").strip()


def _sequence_no(blk_obj):
    """该属性的 sequenceNo（= .uvs 里的 group 下标，用户确认）。读不到按 0。"""
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
    """这个 EFX 是从哪个目录导进来的（导入时记在 root 集合的 `src_path` 上）。

    老 .blend 里没有这个自定义属性（0.6.5 之前导入的），那就返回 None，路径解析
    退回「手设 Chunk Root」那一条——不猜。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# 路径解析（.uvs / .tex 共用一套根优先级，见模块 docstring）
# ─────────────────────────────────────────────────────────────────────────────

def model_editor_chunk_paths():
    """MHW Model Editor 里用户已经存好的 chunk 目录列表（存在的那些）。

    装了 Model Editor 的人基本都在那边设过提取目录了，再让他们在这里填一遍
    Chunk Root 是重复劳动。按偏好里有没有 `chunkPathList_items` 认人，不写死
    addon 名（扩展/老式 addon 装出来的名字不一样）。
    """
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
    # Model Editor 那边存的 chunk 目录：官方资源（.efx 引用的 vfx/uvs、vfx/dds）
    # 基本都在游戏提取目录里，而 mod 工程目录里只有自己新做的那几个文件。
    for p in model_editor_chunk_paths():
        candidates.append(os.path.join(p, rel))
    if efx_dir:
        candidates.append(os.path.join(efx_dir, rel))
        candidates.append(os.path.join(efx_dir, os.path.basename(rel)))
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# .tex → Blender 图像（借 MHW Model Editor 的实现；缺席则降级）
# ─────────────────────────────────────────────────────────────────────────────

def _model_editor_tex_api():
    """找 Model Editor 的 tex 载入实现，返回 (loadTex, Texconv, addon_name)；没有返回 None。

    先扫 `sys.modules`（Model Editor 已启用时它就在里面），再退回遍历 addon 模块
    按包名拼路径——同 Modding-Toolkit 借这份实现时的做法。
    """
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
    """能不能把 .tex 直接转出来（决定 UI 上要不要提示装 Model Editor）。"""
    return _model_editor_tex_api() is not None


def _tex_cache_dir(addon_name):
    """转换产物放哪。优先用 Model Editor 自己的贴图缓存目录（用户已经设过了，
    而且那边转过的图能直接命中缓存）；读不到就用 Blender 的临时目录。"""
    if addon_name:
        try:
            prefs = bpy.context.preferences.addons[addon_name].preferences
            d = bpy.path.abspath(getattr(prefs, "textureCachePath", "") or "")
            if d:
                return d
        except Exception:
            pass
    base = bpy.app.tempdir or os.path.join(os.path.expanduser("~"), ".efx_editor")
    return os.path.join(base, "efx_tex_cache")


def _use_dds(addon_name):
    """4.2+ 的 Blender 能直接读 DDS，就不必再转 tif/tga（也就不依赖 texconv）。
    Model Editor 的偏好里用户已经选过一次，尊重它；读不到按版本自动判。"""
    auto = bpy.app.version >= (4, 2, 0)
    if addon_name:
        try:
            prefs = bpy.context.preferences.addons[addon_name].preferences
            return bool(getattr(prefs, "useDDS", auto)) and auto
        except Exception:
            pass
    return auto


def _find_converted_sibling(texpath, cache_dir):
    """.tex 旁边、或缓存目录里已经转好的同名图（Model Editor 缺席时的退路）。"""
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


def load_tex_image(texpath, rel_for_cache=None):
    """.tex → `bpy.types.Image`；失败返回 None。

    两条路：① Model Editor 在场 → 借它的 loadTex（tex→dds→图像，含色彩空间处理）；
    ② 缺席 → 找一张已经转好的同名图直接 load。两条都不通就返回 None（调用方如实报）。
    """
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
        for use_dds in _dds_attempts(addon_name):
            try:
                conv = texconv_cls() if texconv_cls is not None else None
                images = load_tex(texpath, out_path, conv, False, use_dds)
                for img in images or ():
                    if img is not None:
                        return img
            except Exception:
                continue

    sib = _find_converted_sibling(texpath, cache_dir)
    if sib:
        try:
            return bpy.data.images.load(sib, check_existing=True)
        except Exception:
            return None
    return None


def _dds_attempts(addon_name):
    """先按偏好/版本试一次；若那次要走 texconv（DLL 可能缺）而 Blender 又能读 DDS，
    再用 DDS 兜一次。"""
    first = _use_dds(addon_name)
    if first or bpy.app.version < (4, 2, 0):
        return (first,)
    return (first, True)


# ─────────────────────────────────────────────────────────────────────────────
# 一条链：属性 → .uvs → .tex → 参考图
# ─────────────────────────────────────────────────────────────────────────────

def link_one(blk_obj, chunk_root, efx_dir=None, with_texture=True, uvs_cache=None):
    """单个 UVSEQUENCE 属性走完整条链。

    返回 dict：`{"uvs": bool, "tex": bool, "rel": str, "reason": str}`
    —— `reason` 只在这一层没成时填，供调用方汇总提示。
    """
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

    # ── .uvs → .tex：取 sequenceNo 指的那个 group 的第一条贴图路径 ────────────
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
        # group_index 跟着 sequenceNo 走：一键载入之后编辑器直接停在这个特效真正
        # 用的那一组上，不必用户自己去数第几组。
        props.group_index = group_idx
    except Exception:
        pass
    out["tex"] = True
    return out


def link_root(root_col, chunk_root, efx_dir=None, with_texture=True):
    """整个 EFX_ROOT 下所有 UVSEQUENCE 走一遍。

    返回 (n_uvs, n_tex, problems)，`problems = [(属性名, 相对路径, reason)]`。
    同一个 .uvs 只读盘一次（多个属性引用同一份很常见）。
    """
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
    """把结果统一报给用户：成功计数一条 INFO，未解决的一条 WARNING（不静默失败）。"""
    if n_uvs or n_tex:
        op.report({"INFO"}, T("uvslink.done").format(n_uvs, n_tex))
    if problems:
        detail = "；".join("%s（%s）" % (name, T("uvslink.reason_" + reason))
                          for name, _rel, reason in problems[:5])
        op.report({"WARNING"}, T("uvslink.failed").format(len(problems), detail))
    elif not n_uvs:
        op.report({"WARNING"}, T("uvslink.nothing"))


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

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
        if _is_uvsequence(obj):
            return True
        return _rc.find_root_collection(obj) is not None

    def execute(self, context):
        obj = context.active_object
        chunk_root = getattr(context.scene, "efx_chunk_root", "") or ""

        if self.scope == "ATTRIBUTE" and _is_uvsequence(obj):
            efx_dir = efx_dir_of(obj)
            r = link_one(obj, chunk_root, efx_dir, self.with_texture, {})
            problems = [(obj.name, r["rel"], r["reason"])] if r["reason"] else []
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
    # UVSEQUENCE 属性 → 外部 UVS 载体（数据不再存在属性对象自己身上，见
    # ensure_host_for_attribute）。standalone.py 的 `efx_uvs` 本身仍留在 Object 上
    # 不变，只是现在"谁的 efx_uvs 才算数"要经这层指针。
    bpy.types.Object.efx_uvs_target = bpy.props.PointerProperty(
        name="UVS Data Host",
        description="External object holding this UVSEQUENCE attribute's UVS data",
        type=bpy.types.Object,
    )


def unregister():
    if hasattr(bpy.types.Object, "efx_uvs_target"):
        del bpy.types.Object.efx_uvs_target
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
