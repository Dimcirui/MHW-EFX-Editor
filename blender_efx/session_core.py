"""
blender_efx/session_core.py  —  会话/预览类的公共基础设施：标记式孤儿清理 + 生命周期缓存复位

设计原则（见 memory `timl-fcurve-persistence-refactor-plan` / `byte-perfect-doctrine-shift`）
--------------------------------------------------------------------------------------------
预览/会话类此前把状态放在**不随 undo/reload/模块热重载走的 Python 全局 `_state`**，却驱动
undo 追踪的真实场景数据（实例对象、隐藏态、约束）→ 两者脱钩即残留悬空引用/孤儿，表现为
"频繁进出后越来越乱"。本模块把这类会话状态归约为**场景事实的派生量**：

1. **真相在场景**：会话产物（实例对象、被隐藏的源）一律打**自定义属性标记**，"是否活跃 /
   有哪些产物"由**标记扫描**（`iter_marked`）派生，不信任可能脱节的 `_state` 布尔。
2. **清理按标记**（`purge_marked` / `restore_hidden`），不按缓存引用 → undo/reload/热重载
   把 Python 状态清零也不会残留：下次进入先清场即根治累积。
3. ⚠ **对象删除只在算子上下文做**（enter 先清场 / exit 清场），**不在 undo/redo/load handler
   里删数据块**（handler 里改数据块有污染 undo 栈的风险）。本模块的 handler 只复位缓存 dict
   （纯 Python，无对象操作，安全）。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层；包内相对导入。
"""

import bpy
from bpy.app.handlers import persistent


# ─────────────────────────────────────────────────────────────────────────────
# 标记式对象记账（真相源：场景里带标记的对象）
# ─────────────────────────────────────────────────────────────────────────────

def iter_marked(marker_key):
    """场景内所有带 `marker_key` 自定义属性的对象（值为 0 也算——`is not None` 判据）。"""
    return [o for o in bpy.data.objects if o.get(marker_key) is not None]


def remove_object(name):
    """按名安全删除对象；顺带回收因此变孤儿的 mesh 数据。返回是否删除。"""
    obj = bpy.data.objects.get(name) if name else None
    if obj is None:
        return False
    data = obj.data
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        return False
    # es3d 等生成的临时几何：删对象后 mesh 无人引用则一并回收，避免 .blend 里堆孤儿 mesh
    try:
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    except Exception:
        pass
    return True


def purge_marked(marker_key, keep=None):
    """删除所有带 `marker_key` 的对象（`keep` 名单除外）。返回删除数。**仅算子上下文调用。**"""
    keep = keep or set()
    removed = 0
    for o in list(iter_marked(marker_key)):
        if o.name in keep:
            continue
        if remove_object(o.name):
            removed += 1
    return removed


def restore_hidden(flag_key):
    """还原所有带 `flag_key` 的对象可见性并清除该标记。

    隐藏源对象的预览类（如 mesh_align 隐藏源网格）把原 `hide_viewport` 值存进对象自定义属性
    `flag_key`（而非 Python 快照），退出/清场时据此还原——即便 Python 状态早已脱节也能恢复。
    """
    for o in list(iter_marked(flag_key)):
        try:
            o.hide_viewport = bool(o.get(flag_key))
        except Exception:
            pass
        try:
            del o[flag_key]
        except Exception:
            pass


def flag_hidden(obj, flag_key):
    """隐藏 obj，并把其原 `hide_viewport` 值存进自定义属性 `flag_key`（供 restore_hidden 还原）。
    已带标记则不覆盖（幂等：多次进入不把"已隐藏"当原态）。"""
    try:
        if obj.get(flag_key) is None:
            obj[flag_key] = int(bool(obj.hide_viewport))
        obj.hide_viewport = True
    except Exception:
        pass


def get_or_create_collection(name):
    """按名取/建集合并挂到场景根集合。返回集合。"""
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        try:
            bpy.context.scene.collection.children.link(col)
        except Exception:
            pass
    return col


def remove_collection_named(name):
    if not name:
        return
    col = bpy.data.collections.get(name)
    if col is not None:
        try:
            bpy.data.collections.remove(col)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 生命周期缓存复位分发器（load_post；只复位缓存 dict，绝不碰对象/数据块）
# ─────────────────────────────────────────────────────────────────────────────
# 各模块注册一个"清缓存"回调；换文件时统一触发。故意不注册 undo/redo_post 做对象清理——
# handler 里删数据块有风险，孤儿清理交给 enter 先清场 / exit 清场（算子上下文，安全）。

_cache_resets = []


@persistent
def _on_load(*_args):
    for fn in list(_cache_resets):
        try:
            fn()
        except Exception:
            pass


def register_cache_reset(fn):
    if fn not in _cache_resets:
        _cache_resets.append(fn)


def unregister_cache_reset(fn):
    if fn in _cache_resets:
        _cache_resets.remove(fn)


def register():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load)
        except Exception:
            pass
    _cache_resets.clear()
