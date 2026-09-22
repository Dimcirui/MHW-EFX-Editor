"""管理 EFX 根集合、段叶集合及其归属关系。

维护约束：
- EFX_ROOT 是顶层文件集合；Header、标签和 EOF 数据归根集合所有。
- 段对象通过所在集合的 ``efx_root_ptr`` 解析所属根，属性与 TIML 仍以 parent
  连接到 Entry。
- Entry 的 Direct Trigger 与 Not Direct Trigger 嵌套集合均须保留根反向指针；
  收集 Entry 时需要递归并去重，以免异常多重归属重复写出。
- 无法确定根归属的对象不得被跨文件引用限制误拒绝。
"""

import bpy
from bpy.props import PointerProperty


# ~TYPE 值 → 叶子子集合的 ~TYPE 标记
_TYPE_TO_MARKER = {
    "EFX_ENTRY":     "EFX_ENTRY_COLLECTION",
    "EFX_ACTION":    "EFX_ACTION_COLLECTION",
    "EFX_EXTERN":    "EFX_EXTERN_COLLECTION",
    "EFX_SUBSELECT": "EFX_SUBSELECT_COLLECTION",
}

# EOF 的两个嵌套集合都属于 Entry 段并保留根反向指针。
_DIRECT_TRIGGER_MARKER = "EFX_DIRECT_TRIGGER_COLLECTION"
_DIRECT_TRIGGER_NAME = "Direct Trigger"
_NOT_DIRECT_TRIGGER_MARKER = "EFX_NOT_DIRECT_TRIGGER_COLLECTION"
_NOT_DIRECT_TRIGGER_NAME = "Not Direct Trigger"


def new_root_collection(name: str, parent_col) -> bpy.types.Collection:
    """建顶层文件集合（紫色 COLOR_06），标记 ~TYPE=EFX_ROOT，link 进 parent_col。"""
    col = bpy.data.collections.new(name)
    parent_col.children.link(col)
    col.color_tag = "COLOR_06"
    col["~TYPE"] = "EFX_ROOT"
    return col


def new_leaf_collection(name: str, root_col: bpy.types.Collection, type_tag: str) -> bpy.types.Collection:
    """创建段叶集合并设置类型标记和指向根集合的反向指针。"""
    marker = _TYPE_TO_MARKER.get(type_tag)
    if marker is None:
        raise ValueError("new_leaf_collection：未知 type_tag %r" % (type_tag,))
    col = bpy.data.collections.new(name)
    root_col.children.link(col)
    col["~TYPE"] = marker
    col.efx_root_ptr = root_col
    return col


def get_leaf_collection(root_col: bpy.types.Collection, type_tag: str):
    """在 root_col 的直接子集合里找对应 type_tag 的叶子集合，没有返回 None。"""
    if root_col is None:
        return None
    marker = _TYPE_TO_MARKER.get(type_tag)
    if marker is None:
        return None
    for c in root_col.children:
        if c.get("~TYPE") == marker:
            return c
    return None


def ensure_leaf_collection(name: str, root_col: bpy.types.Collection, type_tag: str) -> bpy.types.Collection:
    """取得段叶集合，缺失时创建。"""
    existing = get_leaf_collection(root_col, type_tag)
    if existing is not None:
        return existing
    return new_leaf_collection(name, root_col, type_tag)


def ensure_linked_collection(root_col: bpy.types.Collection, marker: str, name: str,
                              color_tag: str) -> bpy.types.Collection:
    """取得或创建根下的旁支资产集合。

    其 marker 不得属于 EFX 段集合标记，因此导出与校验会自然忽略其对象。
    """
    for c in root_col.children:
        if c.get("~TYPE") == marker:
            return c
    col = bpy.data.collections.new(name)
    root_col.children.link(col)
    col["~TYPE"] = marker
    col.color_tag = color_tag
    col.efx_root_ptr = root_col
    return col


def _get_nested_entry_collection(root_col: bpy.types.Collection, marker: str):
    """只读查找 Entry 叶子集合下、标记为 marker 的嵌套子集合，没有返回 None。"""
    entry_col = get_leaf_collection(root_col, "EFX_ENTRY")
    if entry_col is None:
        return None
    for child in entry_col.children:
        if child.get("~TYPE") == marker:
            return child
    return None


def _ensure_nested_entry_collection(root_col: bpy.types.Collection, marker: str, name: str):
    """取得或创建 Entry 下的嵌套集合，并写入根反向指针。"""
    existing = _get_nested_entry_collection(root_col, marker)
    if existing is not None:
        return existing
    entry_col = get_leaf_collection(root_col, "EFX_ENTRY")
    if entry_col is None:
        return None
    col = bpy.data.collections.new(name)
    entry_col.children.link(col)
    col["~TYPE"] = marker
    col.efx_root_ptr = root_col
    return col


def get_direct_trigger_collection(root_col: bpy.types.Collection):
    """只读查找 "Direct Trigger" 嵌套子集合；没有返回 None（opaque 模型文件没有）。"""
    return _get_nested_entry_collection(root_col, _DIRECT_TRIGGER_MARKER)


def ensure_direct_trigger_collection(root_col: bpy.types.Collection):
    """find-or-create "Direct Trigger" 嵌套子集合。"""
    return _ensure_nested_entry_collection(root_col, _DIRECT_TRIGGER_MARKER, _DIRECT_TRIGGER_NAME)


def get_not_direct_trigger_collection(root_col: bpy.types.Collection):
    """只读查找 "Not Direct Trigger" 嵌套子集合；没有返回 None（opaque 模型文件没有）。"""
    return _get_nested_entry_collection(root_col, _NOT_DIRECT_TRIGGER_MARKER)


def ensure_not_direct_trigger_collection(root_col: bpy.types.Collection):
    """find-or-create "Not Direct Trigger" 嵌套子集合。"""
    return _ensure_nested_entry_collection(root_col, _NOT_DIRECT_TRIGGER_MARKER, _NOT_DIRECT_TRIGGER_NAME)


def is_root_collection(col) -> bool:
    return col is not None and col.get("~TYPE") == "EFX_ROOT"


def find_root_collection(obj: bpy.types.Object):
    """通过对象所属集合的反向指针查找 EFX 根集合。"""
    if obj is None:
        return None
    for col in obj.users_collection:
        if is_root_collection(col):
            return col
        root = getattr(col, "efx_root_ptr", None)
        if root is not None:
            return root
    return None


def collect_top_level(root_col: bpy.types.Collection, type_tag: str) -> list:
    """递归收集指定段对象并按索引排序。

    必须按对象身份去重，避免异常多重归属导致重复导出。
    """
    col = get_leaf_collection(root_col, type_tag)
    if col is None:
        return []
    out = []
    seen = set()

    def _walk(c):
        for o in c.objects:
            if o.get("~TYPE") == type_tag and o.name not in seen:
                seen.add(o.name)
                out.append(o)
        for child in c.children:
            _walk(child)

    _walk(col)
    out.sort(key=lambda o: int(o.get("efx_index", 0)))
    return out


def same_root(obj_a: bpy.types.Object, obj_b: bpy.types.Object) -> bool:
    """判断对象是否同属一个根；未知归属时保守允许。"""
    root_a = find_root_collection(obj_a)
    root_b = find_root_collection(obj_b)
    if root_a is not None and root_b is not None and root_a is not root_b:
        return False
    return True


def all_root_collections() -> list:
    """场景中全部顶层 EFX 文件集合（~TYPE==EFX_ROOT）。"""
    return [c for c in bpy.data.collections if is_root_collection(c)]


def is_color_editor_mode(obj: bpy.types.Object) -> bool:
    """判断对象所属根是否处于颜色编辑器模式；未知根时返回 False。"""
    root = find_root_collection(obj)
    return root is not None and int(root.get("color_editor_mode", 0)) == 1


def root_is_color_editor_mode(root_col: bpy.types.Collection) -> bool:
    """直接判断根集合是否处于颜色编辑器模式。"""
    return root_col is not None and int(root_col.get("color_editor_mode", 0)) == 1


def register():
    bpy.types.Collection.efx_root_ptr = PointerProperty(
        name="EFX Root Collection",
        description="Back-pointer to the top-level EFX file collection this leaf collection belongs to",
        type=bpy.types.Collection,
    )


def unregister():
    try:
        del bpy.types.Collection.efx_root_ptr
    except AttributeError:
        pass
