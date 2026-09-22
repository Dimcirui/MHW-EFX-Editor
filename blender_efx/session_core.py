"""会话和预览对象的标记式清理与生命周期基础设施。

维护约束：场景对象及其自定义属性是会话状态的权威来源，Python 缓存只能派生。
对象删除仅可在算子上下文执行；load handler 只处理 Python 侧状态。
"""

import bpy
from bpy.app.handlers import persistent


# ─────────────────────────────────────────────────────────────────────────────
# 场景中的标记对象是会话产物的权威记录。
# ─────────────────────────────────────────────────────────────────────────────

def iter_marked(marker_key):
    """返回带 marker_key 的对象；标记值为 0 时也属于结果。"""
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
    # 同时回收无用户的临时网格。
    try:
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    except Exception:
        pass
    return True


def purge_marked(marker_key, keep=None):
    """删除标记对象（keep 除外）；仅可在算子上下文调用。"""
    keep = keep or set()
    removed = 0
    for o in list(iter_marked(marker_key)):
        if o.name in keep:
            continue
        if remove_object(o.name):
            removed += 1
    return removed


def restore_hidden(flag_key):
    """从对象标记恢复可见性，并清除该标记。"""
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
    """隐藏对象并记录原可见性；已有标记时不得覆盖原始状态。"""
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
# load_post 分发器只允许调用纯 Python 缓存复位函数。

_cache_resets = []


@persistent
def _on_load(*_args):
    for fn in list(_cache_resets):
        try:
            fn()
        except Exception:
            pass


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
