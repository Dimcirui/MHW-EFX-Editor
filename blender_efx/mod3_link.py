r"""
blender_efx/mod3_link.py  —  EFX MESH 属性引用的 mod3 自动导入 + 绑定（联动 MHW Model Editor，添头功能）

定位（与用户确认的边界）
------------------------
- **可勾选、非默认**：导入 EFX 时「同时导入引用的 mesh」是导入算子上的一个开关，**默认关**。
  拖入导入也不静默——弹窗让用户勾选后才导（见 operators.py 的 invoke）。
- **Model Editor 是添头非依赖**：检测到 `mhw_mod3.import_mhw_mod3` 才解锁；缺席则开关禁用、提示安装。
- **一个算子搞定 mod3+mrl3+材质**：Model Editor 的导入算子带 `loadMaterials`（默认开）+ `mrl3Path`
  留空自动找——正是「一键装备」式联动。本模块只负责：把 EFX MESH 属性的相对路径解析成磁盘上的
  .mod3，调它导入，再按该属性的 visconIndex/visconIndexJitter（Visible Condition 组号 + 随机范围）
  从导入出的网格里挑出落在范围内的那些，写进 `efx_mesh_targets`（多网格；见 `_bind_viscon_range`）。
  `efx_mesh_target`（单体，与 UVC / TIML 浏览共用绑定）仍指向第一个命中对象，供尚未走多网格
  路径的消费方（mesh_align 等）兼容用。

路径解析
--------
- MESH 属性 path1 形如 `vfx\mod\wp\wp03\md_wp03_000`（游戏内相对路径，反斜杠，**无扩展名**）；path2 多为空。
- 解析 = `<根>/vfx/mod/.../md_wp03_000.mod3`。根的优先级：① 手设 `Scene.efx_chunk_root`（填了才用）
  ② **从 efx 位置向上追溯到的第一个 nativePC（默认、自动）** ③ efx 同目录兜底。
  全找不到 → 收集到 unresolved 列表，导入结束统一提示，**不静默失败**。

约束（CLAUDE.md）
-----------------
- 纯胶水层；只读 EFX 解析（extract_paths），不重序列化 → 不碰 byte-perfect。
- Python 3.10 兼容；bpy 稳定子集；Model Editor 调用经 `_model_editor_available` 守卫，缺席即降级。
"""

import os
import re
import base64

import bpy
from bpy.props import CollectionProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from ..efx_format.hashes import MESH
from ..efx_format.structs import extract_paths
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 多网格绑定：一个 MESH 属性可能要绑同一 mod3 里好几个 Visible Condition 组
# ─────────────────────────────────────────────────────────────────────────────

class EFXMeshTargetItem(PropertyGroup):
    """`efx_mesh_targets` 的一项：一个绑定网格 + 它所属的 Visible Condition 组号。"""

    obj: PointerProperty(
        name="Mesh",
        type=bpy.types.Object,
        poll=lambda self, o: o.type == "MESH",
    )
    viscon: IntProperty(name="Visible Condition", default=0)


#: mod3 网格命名里的组号（Model Editor 命名约定：`[LOD_n_]Group_<id>_Sub_<m>__<material>`，
#: 见 mod3_functions.py::exportMod3 与其 re.search(r"Group_(\d+)", ...) 反查）。
_GROUP_RE = re.compile(r"Group_(\d+)")


def _parse_group_id(name):
    """从导入网格对象名解析它所属的 Visible Condition 组号；解析不到返回 None
    （自定义命名 / 非 Model Editor 生成的网格）。"""
    m = _GROUP_RE.search(name or "")
    return int(m.group(1)) if m else None


def _attribute_viscon_range(blk):
    """读 MESH 属性的 visconIndex（static）/ visconIndexJitter（random，ONESIDED 抖动，
    见 efx_format/sim/rng.py::jitter_int），返回运行时可能选中的组号闭区间 (lo, hi)。
    没有 jitter 就是单点 (v, v)。"""
    lo = hi = 0
    try:
        for item in blk.efx_block.field_items:
            if item.ori_name == "visconIndex":
                lo = hi = int(item.int_value)
            elif item.ori_name == "visconIndexJitter":
                hi = lo + max(0, int(item.int_value))
    except Exception:
        pass
    return lo, hi


# ─────────────────────────────────────────────────────────────────────────────
# Model Editor 在场检测
# ─────────────────────────────────────────────────────────────────────────────

def model_editor_available() -> bool:
    """MHW Model Editor 是否已安装并注册了 mod3 导入算子。"""
    try:
        return "import_mhw_mod3" in dir(bpy.ops.mhw_mod3)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MESH 属性路径读取
# ─────────────────────────────────────────────────────────────────────────────

def _attribute_mod3_relpath(blk_obj):
    """读 EFX_ATTRIBUTE（MESH 类型）的 mod3 相对路径（path1）；非 MESH / 空 / 异常返回 None。"""
    if blk_obj is None or blk_obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return None
    try:
        if int(blk_obj.get("type_hash", "0")) != MESH:
            return None
        data_bytes = base64.b64decode(str(blk_obj.get("data_bytes", "")))
        paths = extract_paths(MESH, data_bytes)
    except Exception:
        return None
    if not paths:
        return None
    rel = (paths[0] or "").strip()
    return rel or None


def iter_mesh_attributes(root_obj):
    """遍历 EFX_ROOT 下所有 MESH 属性对象，yield (blk_obj, mod3_relpath)（仅含非空路径的）。"""
    for body in _rc.collect_top_level(root_obj, "EFX_ENTRY"):
        for blk in body.children:
            rel = _attribute_mod3_relpath(blk)
            if rel is not None:
                yield blk, rel


# ─────────────────────────────────────────────────────────────────────────────
# 相对路径 → 磁盘 .mod3 绝对路径
# ─────────────────────────────────────────────────────────────────────────────

def find_native_root(efx_dir):
    """从 efx 所在目录向上追溯，返回第一个名为 nativePC 的目录（绝对路径）；没有返回 None。

    MHW 提取布局里 MESH 属性的相对路径（vfx\\mod\\...）正是相对 nativePC 的，故据此自动重定位，
    免去手设 Chunk Root。大小写不敏感（Windows / 某些提取工具用小写）。
    """
    if not efx_dir:
        return None
    cur = os.path.abspath(efx_dir)
    while True:
        if os.path.basename(cur).lower() == "nativepc":
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:   # 到盘符根，停
            return None
        cur = parent


def resolve_mod3_path(relpath, chunk_root, efx_dir=None):
    """把 MESH 相对路径解析成磁盘上存在的 .mod3 绝对路径；找不到返回 None。

    解析根优先级：① 手设 Chunk Root（若填了）② 从 efx 位置向上追溯到的 nativePC（自动）
    ③ efx 文件目录兜底。relpath 反斜杠归一化、补 .mod3。
    """
    rel = relpath.replace("\\", "/").lstrip("/")
    if not rel.lower().endswith(".mod3"):
        rel += ".mod3"
    candidates = []
    if chunk_root:
        candidates.append(os.path.join(bpy.path.abspath(chunk_root), rel))
    native = find_native_root(efx_dir)
    if native:
        candidates.append(os.path.join(native, rel))
    if efx_dir:
        candidates.append(os.path.join(efx_dir, rel))
        # efx 同目录直接放 mod3 的情况：只取文件名
        candidates.append(os.path.join(efx_dir, os.path.basename(rel)))
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.normpath(c)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 导入 + 绑定
# ─────────────────────────────────────────────────────────────────────────────

def _mesh_collection_name(root_obj):
    """外层总集合名：EFX 顶层集合名去掉 .efx 后缀 + "_mesh"（如 em001_000_mesh）。"""
    name = getattr(root_obj, "name", "") or "efx"
    if name.lower().endswith(".efx"):
        name = name[:-4]
    return name + "_mesh"


_MESH_LINK_MARKER = "EFX_MESH_LINK"


def _ensure_mesh_collection(context, root_col, cache):
    """懒建外层总集合，同一次导入复用。

    嵌在 root_col（紫色 EFX 顶层集合）内部作为子集合（红色，区别于 EFX 紫 / mrl3
    蓝）——它不是 .efx 结构的一部分（marker 不进 `_TYPE_TO_MARKER`），导出/校验的
    收集入口天然跳过，纯粹是"这个 mod3 是哪个 .efx 带进来的"这一层归属的可视化。
    """
    col = cache.get("col")
    if col is None:
        col = _rc.ensure_linked_collection(
            root_col, _MESH_LINK_MARKER, _mesh_collection_name(root_col), "COLOR_01")
        cache["col"] = col
    return col


def _import_one_mod3(filepath, context, root_obj, col_cache):
    """调 Model Editor 导入一个 .mod3（含 mrl3+材质），返回本次新建的网格对象列表。

    经 bpy.ops 默认 EXEC_DEFAULT → 只走 execute()，operator 的 invoke()/setMod3ImportDefaults
    不触发，故这里传的 kwargs 即最终值（不会被偏好默认覆盖）。
    显式开 loadMaterials + loadMrl3Data：mrl3 是贴图指引，不一起导入材质就找不到贴图。
    mrl3Path 留空 → Model Editor 自动在 mod3 旁找 mrl3。

    Model Editor 的 createCollection 没有父集合时一律 link 到场景根，所以导入前后 diff
    场景根的**子集合**与**直属对象**（createCollections 关掉时网格直接落在场景根），
    把新增的一并收进 {efx}_mesh 总集合。
    """
    before = {o.name for o in bpy.data.objects}
    scene_col = context.scene.collection
    cols_before = {c.name for c in scene_col.children}
    objs_before = {o.name for o in scene_col.objects}

    bpy.ops.mhw_mod3.import_mhw_mod3(
        filepath=filepath,
        files=[{"name": os.path.basename(filepath)}],
        directory=os.path.dirname(filepath),
        loadMaterials=True,    # 从 mrl3 加载网格材质（贴图）
        loadMrl3Data=True,     # 一并导入 mrl3 材质数据
        mrl3Path="",           # 留空 = 自动找相邻 mrl3
    )

    new_cols = [c for c in scene_col.children if c.name not in cols_before]
    new_objs = [o for o in scene_col.objects if o.name not in objs_before]
    if new_cols or new_objs:
        try:
            wrapper = _ensure_mesh_collection(context, root_obj, col_cache)
            for c in new_cols:
                scene_col.children.unlink(c)
                wrapper.children.link(c)
            for o in new_objs:
                scene_col.objects.unlink(o)
                wrapper.objects.link(o)
        except Exception:
            pass   # 归拢失败只是摆放不整齐，导入本身照常

    new_meshes = [
        o for o in bpy.data.objects
        if o.name not in before and o.type == "MESH"
    ]
    return new_meshes


def _bind_viscon_range(blk, meshes):
    """按 blk 的 visconIndex/visconIndexJitter 范围，从这个 mod3 导入出的 meshes 里
    挑出所有落在该范围内的网格，写进 blk.efx_mesh_targets（多网格：同一个 Visible
    Condition 组常常由好几个 Sub 网格拼成，随机量 > 0 时更是要覆盖好几组）。

    efx_mesh_target（单体，旧模型）仍指向第一个命中的对象，供 mesh_align /
    uvc_preview 等尚未走多网格路径的消费方继续用。解析不出任何 Group_ 编号的网格
    （自定义命名 / 非 Model Editor 导出）时不过滤——全部当命中，保底不丢绑定。

    返回是否至少绑定成功一个网格。
    """
    lo, hi = _attribute_viscon_range(blk)
    tagged = [(m, _parse_group_id(m.name)) for m in meshes]
    if any(g is not None for _m, g in tagged):
        picked = [(m, g) for m, g in tagged if g is None or lo <= g <= hi]
    else:
        picked = tagged  # 一个都解析不到组号：退回全绑，好过不绑

    try:
        blk.efx_mesh_targets.clear()
        for m, g in picked:
            item = blk.efx_mesh_targets.add()
            item.obj = m
            item.viscon = g if g is not None else lo
    except Exception:
        pass

    if picked:
        try:
            blk.efx_mesh_target = picked[0][0]
        except Exception:
            pass
    return bool(picked)


def import_and_bind(root_obj, context, chunk_root, efx_dir=None):
    """对 EFX_ROOT 下每个带 mod3 路径的 MESH 属性：解析→导入→按 viscon 范围绑定。

    返回 (n_bound, unresolved)：
      n_bound    = 成功导入并绑定的 MESH 属性数
      unresolved = [(blk_name, relpath)]  —— 路径解析失败，未导入
    同一 mod3 路径只导入一次（去重）；多个 MESH 属性引用同一 mod3 时，各自按自己的
    visconIndex/Jitter 范围从这同一批导入网格里挑自己的子集（见 `_bind_viscon_range`），
    不再像旧版那样所有引用者共绑「第一个」。
    导入出来的一排 mod3/mrl3 集合统一收进这个 .efx 顶层集合下的 `{efx 文件名}_mesh`
    子集合（红色），免得几个 MESH 属性就在大纲里铺一长条。
    """
    n_bound = 0
    unresolved = []
    imported_cache = {}  # 绝对路径 → 这个 mod3 导入出的全部网格对象（去重，只导一次）
    col_cache = {}       # 本次导入共用的 {efx}_mesh 总集合（懒建）

    for blk, rel in iter_mesh_attributes(root_obj):
        abspath = resolve_mod3_path(rel, chunk_root, efx_dir)
        if abspath is None:
            unresolved.append((blk.name, rel))
            continue
        meshes = imported_cache.get(abspath)
        if meshes is None:
            try:
                meshes = _import_one_mod3(abspath, context, root_obj, col_cache)
            except Exception:
                unresolved.append((blk.name, rel))
                continue
            if not meshes:
                unresolved.append((blk.name, rel))
                continue
            imported_cache[abspath] = meshes

        if _bind_viscon_range(blk, meshes):
            n_bound += 1
        else:
            unresolved.append((blk.name, rel))

    return n_bound, unresolved


# ─────────────────────────────────────────────────────────────────────────────
# 注册：Scene.efx_chunk_root（提取根目录）
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (EFXMeshTargetItem,)


def _addon_preferences():
    """取插件 AddonPreferences 实例；取不到（未注册/独立跑 CLI）时返回 None。"""
    try:
        root_pkg = __package__.rsplit(".", 1)[0]
        return bpy.context.preferences.addons[root_pkg].preferences
    except Exception:
        return None


def _get_chunk_root(self):
    # 场景里手填了 Chunk Root 就用场景值；留空则回退到插件偏好设置里的永久默认值。
    raw = self.get("efx_chunk_root_raw", "")
    if raw:
        return raw
    prefs = _addon_preferences()
    return getattr(prefs, "chunk_root", "") if prefs else ""


def _set_chunk_root(self, value):
    self["efx_chunk_root_raw"] = value


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_chunk_root = bpy.props.StringProperty(
        name="Chunk Root",
        description="MHW 提取根目录（含 vfx/ 等）。MESH 属性的 mod3 相对路径据此解析成磁盘文件。"
                    "留空时使用插件偏好设置里的永久默认值",
        subtype="DIR_PATH",
        get=_get_chunk_root,
        set=_set_chunk_root,
    )
    # 多网格绑定：同一 MESH 属性按 viscon 范围绑的全部对象（efx_mesh_target 单体
    # 指针仍保留在 uvc_preview.py，供未走多网格路径的消费方兼容用）。
    bpy.types.Object.efx_mesh_targets = CollectionProperty(
        name="Preview Meshes",
        description="Mesh objects bound to this MESH attribute by Visible Condition group",
        type=EFXMeshTargetItem,
    )


def unregister():
    if hasattr(bpy.types.Object, "efx_mesh_targets"):
        del bpy.types.Object.efx_mesh_targets
    if hasattr(bpy.types.Scene, "efx_chunk_root"):
        del bpy.types.Scene.efx_chunk_root
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
