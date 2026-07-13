"""
blender_efx/root_collection.py  —  ROOT 集合化：文件归属改由 Collection 承载

2026-07 结构权威下放的收尾：EFX_ROOT 不再是一个 Empty 对象。取而代之，每个
.efx 文件对应的顶层紫色集合（root_col，import 时以文件名建立，COLOR_06）
本身即"文件"——header/label/eof(legacy 或 opaque) 字段直接存在 root_col 的
自定义属性上；"entry/action/extern/subselect 属于哪个文件"不再靠
`obj.parent == root_obj` 判断，改靠**集合归属**判断。

标记约定
--------
- `root_col["~TYPE"] = "EFX_ROOT"`：顶层文件集合。
- 四个（未来第五个 Direct Trigger）叶子子集合各自：
    `col["~TYPE"] = "EFX_xxx_COLLECTION"`（见 _TYPE_TO_MARKER）
    `col.efx_root_ptr = root_col`（真正的 PointerProperty，指回 root_col）
  entry/action/extern/subselect/attribute/EFX_TIML 对象全部直接 link 进这些
  叶子集合（跟以前一样，这一层"对象在哪个集合里"从来没变过——变的只是不再
  额外维护一份 `.parent==root_obj` 的冗余关系）。

查找是 O(1)：`obj.users_collection` 通常只有 1 个叶子集合，读它的
`efx_root_ptr` 直接拿到 root_col，不需要扫场景、不需要递归集合树。
（对比 backref.py 里旧的 `_find_root_collection`——那是按名字含 ".efx" 全场景
扫 `bpy.data.collections` 的兜底实现，正确但是 O(集合数×每集合对象数)；
本模块的版本是维护型反向指针，供全仓库统一复用，backref.py 已改为委托本模块。）

attribute→entry、EFX_TIML→entry 这两层嵌套 parent **完全不受影响**——只是
"顶层段→文件"这一层的归属载体从 parent 换成集合，嵌套层级不动。

约束（CLAUDE.md）：Python 3.10 语法、bpy 稳定子集、不改 efx_format/。
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

# 反向：子集合标记 → 段类型（供人类可读场景用，正向表已够用，此表暂不需要）


def new_root_collection(name: str, parent_col) -> bpy.types.Collection:
    """建顶层文件集合（紫色 COLOR_06），标记 ~TYPE=EFX_ROOT，link 进 parent_col。"""
    col = bpy.data.collections.new(name)
    parent_col.children.link(col)
    col.color_tag = "COLOR_06"
    col["~TYPE"] = "EFX_ROOT"
    return col


def new_leaf_collection(name: str, root_col: bpy.types.Collection, type_tag: str) -> bpy.types.Collection:
    """
    建一个叶子子集合（Entry/Action/Extern/Subselect 之一），link 进 root_col，
    标记 ~TYPE + 设 efx_root_ptr 反向指针指回 root_col。

    type_tag : "EFX_ENTRY" / "EFX_ACTION" / "EFX_EXTERN" / "EFX_SUBSELECT"
    """
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
    """find-or-create：已存在则直接返回，否则新建（供"新增段"类算子在section缺失时按需建）。"""
    existing = get_leaf_collection(root_col, type_tag)
    if existing is not None:
        return existing
    return new_leaf_collection(name, root_col, type_tag)


def is_root_collection(col) -> bool:
    return col is not None and col.get("~TYPE") == "EFX_ROOT"


def find_root_collection(obj: bpy.types.Object):
    """
    给任意 EFX 对象（entry/attribute/action/extern/subselect/EFX_TIML 句柄），
    O(1) 找到它所属的顶层文件集合（root_col）。

    机制：obj 直接 link 在某个叶子集合里（entry 和它的 attribute/TIML 句柄
    都直接 link 在同一个 Entry 叶子集合里，嵌套关系纯靠 .parent 表达，跟
    集合归属无关）——读该叶子集合的 efx_root_ptr 反向指针即得，不扫场景。

    找不到（对象未挂在任何 EFX 叶子集合下，或叶子集合缺反向指针）返回 None。
    """
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
    """
    收集 root_col 下某类型的全部顶层对象（entry/action/extern/subselect），
    按 efx_index 升序排列。

    递归子集合（不仅扫叶子集合的直接 .objects，也扫其子集合）——为将来
    EOF 嵌套集合（"_2 Entry/Direct Trigger"）兼容，entry 无论挂在 Entry 叶子
    集合本身还是嵌套的 Direct Trigger 子集合下，都能被收集到。
    """
    col = get_leaf_collection(root_col, type_tag)
    if col is None:
        return []
    out = []

    def _walk(c):
        for o in c.objects:
            if o.get("~TYPE") == type_tag:
                out.append(o)
        for child in c.children:
            _walk(child)

    _walk(col)
    out.sort(key=lambda o: int(o.get("efx_index", 0)))
    return out


def same_root(obj_a: bpy.types.Object, obj_b: bpy.types.Object) -> bool:
    """判断两个 EFX 对象是否属于同一个文件（同一 root_col）。任一方找不到 root 时保守返回 True
    （不限制，与旧 _same_root_as_active 的保守策略一致，只在确属不同文件时才排除）。"""
    root_a = find_root_collection(obj_a)
    root_b = find_root_collection(obj_b)
    if root_a is not None and root_b is not None and root_a is not root_b:
        return False
    return True


def all_root_collections() -> list:
    """场景中全部顶层 EFX 文件集合（~TYPE==EFX_ROOT）。"""
    return [c for c in bpy.data.collections if is_root_collection(c)]


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
