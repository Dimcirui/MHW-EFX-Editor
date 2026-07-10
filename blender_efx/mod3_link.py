r"""
blender_efx/mod3_link.py  —  EFX MESH 属性引用的 mod3 自动导入 + 绑定（联动 MHW Model Editor，添头功能）

定位（与用户确认的边界）
------------------------
- **可勾选、非默认**：导入 EFX 时「同时导入引用的 mesh」是导入算子上的一个开关，**默认关**。
  拖入导入也不静默——弹窗让用户勾选后才导（见 operators.py 的 invoke）。
- **Model Editor 是添头非依赖**：检测到 `mhw_mod3.import_mhw_mod3` 才解锁；缺席则开关禁用、提示安装。
- **一个算子搞定 mod3+mrl3+材质**：Model Editor 的导入算子带 `loadMaterials`（默认开）+ `mrl3Path`
  留空自动找——正是「一键装备」式联动。本模块只负责：把 EFX MESH 属性的相对路径解析成磁盘上的
  .mod3，调它导入，再把导入出的网格回填到该 MESH 属性的 `efx_mesh_target`（与 UVC / TIML 浏览共用绑定）。

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
import base64

import bpy

from ..efx_format.hashes import MESH
from ..efx_format.structs import extract_paths


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
    for body in root_obj.children:
        if body.get("~TYPE") != "EFX_ENTRY":
            continue
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

def _import_one_mod3(filepath):
    """调 Model Editor 导入一个 .mod3（含 mrl3+材质），返回本次新建的网格对象列表。

    经 bpy.ops 默认 EXEC_DEFAULT → 只走 execute()，operator 的 invoke()/setMod3ImportDefaults
    不触发，故这里传的 kwargs 即最终值（不会被偏好默认覆盖）。
    显式开 loadMaterials + loadMrl3Data：mrl3 是贴图指引，不一起导入材质就找不到贴图。
    mrl3Path 留空 → Model Editor 自动在 mod3 旁找 mrl3。
    """
    before = {o.name for o in bpy.data.objects}
    bpy.ops.mhw_mod3.import_mhw_mod3(
        filepath=filepath,
        files=[{"name": os.path.basename(filepath)}],
        directory=os.path.dirname(filepath),
        loadMaterials=True,    # 从 mrl3 加载网格材质（贴图）
        loadMrl3Data=True,     # 一并导入 mrl3 材质数据
        mrl3Path="",           # 留空 = 自动找相邻 mrl3
    )
    new_meshes = [
        o for o in bpy.data.objects
        if o.name not in before and o.type == "MESH"
    ]
    return new_meshes


def import_and_bind(root_obj, context, chunk_root, efx_dir=None):
    """对 EFX_ROOT 下每个带 mod3 路径的 MESH 属性：解析→导入→绑定 efx_mesh_target。

    返回 (n_bound, unresolved)：
      n_bound    = 成功导入并绑定的 MESH 属性数
      unresolved = [(blk_name, relpath)]  —— 路径解析失败，未导入
    同一 mod3 路径只导入一次（去重），多个 MESH 属性引用同一 mod3 时共绑首个导入网格。
    """
    n_bound = 0
    unresolved = []
    imported_cache = {}  # 绝对路径 → 首个网格对象（去重）

    for blk, rel in iter_mesh_attributes(root_obj):
        abspath = resolve_mod3_path(rel, chunk_root, efx_dir)
        if abspath is None:
            unresolved.append((blk.name, rel))
            continue
        mesh = imported_cache.get(abspath)
        if mesh is None:
            try:
                new_meshes = _import_one_mod3(abspath)
            except Exception:
                unresolved.append((blk.name, rel))
                continue
            if not new_meshes:
                unresolved.append((blk.name, rel))
                continue
            mesh = new_meshes[0]
            imported_cache[abspath] = mesh
        try:
            blk.efx_mesh_target = mesh
            n_bound += 1
        except Exception:
            pass

    return n_bound, unresolved


# ─────────────────────────────────────────────────────────────────────────────
# 注册：Scene.efx_chunk_root（提取根目录）
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.types.Scene.efx_chunk_root = bpy.props.StringProperty(
        name="Chunk Root",
        description="MHW 提取根目录（含 vfx/ 等）。MESH 属性的 mod3 相对路径据此解析成磁盘文件",
        subtype="DIR_PATH",
        default="",
    )


def unregister():
    if hasattr(bpy.types.Scene, "efx_chunk_root"):
        del bpy.types.Scene.efx_chunk_root
