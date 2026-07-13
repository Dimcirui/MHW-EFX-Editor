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
- 四个叶子子集合各自：
    `col["~TYPE"] = "EFX_xxx_COLLECTION"`（见 _TYPE_TO_MARKER）
    `col.efx_root_ptr = root_col`（真正的 PointerProperty，指回 root_col）
  entry/action/extern/subselect/attribute/EFX_TIML 对象全部直接 link 进这些
  叶子集合（跟以前一样，这一层"对象在哪个集合里"从来没变过——变的只是不再
  额外维护一份 `.parent==root_obj` 的冗余关系）。
- EOF 嵌套集合（2026-07 二期）：Entry 叶子集合下再嵌两个对称子集合 "Direct Trigger" /
  "Not Direct Trigger"（`get_direct_trigger_collection`/`ensure_direct_trigger_collection`
  及其 `not_direct_trigger` 对应版本），同样有 `efx_root_ptr` 反向指回 root_col。
  entry（per_entry 模型）100% 分流进其中一个，Entry 叶子集合自身直接子级永远清空——
  大纲拖拽即编辑。误留在 Entry 集合直接子级的（异常/拖拽失误）导出时 fail-safe 视为
  直接触发（entry_action_ref.py::export_eof_per_entry / is_entry_in_eof 处理）。

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

# EOF 嵌套集合：挂在 Entry 叶子集合下的两个对称子集合，entry 100% 分流进其中一个
# （Entry 叶子集合自身直接子级永远清空）。误留在 Entry 集合直接子级的（异常/手动
# 拖拽失误）按 fail-safe 规则在导出时视为直接触发（entry_action_ref.py 处理）。
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
    """find-or-create：嵌套在 Entry 叶子集合下（不是 root_col 的直接子集合），
    同样设 efx_root_ptr 反向指回 root_col，使其内的 entry 仍能被 find_root_collection 找到。
    Entry 叶子集合不存在时返回 None（不该发生，任何文件都有 Entry 段）。"""
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

    递归子集合（不仅扫叶子集合的直接 .objects，也扫其子集合）——Entry 类型下
    还会扫到嵌套的 "Direct Trigger"/"Not Direct Trigger" 子集合，entry 无论挂在
    哪一层（含误留在 Entry 叶子集合直接子级的异常/孤儿情况）都能被收集到。

    去重（`seen`）：正常情况下一个对象只会出现在其中一层，但异常状态——entry
    被手动 Ctrl+drag 同时链进 Direct Trigger 和 Not Direct Trigger 两个子集合
    （validate.py 的 eof_dual_membership 警告专门检测这种情况）——会让递归遍历
    在两层各命中一次。不去重会导致该 entry 在导出的 Main 段里重复写入两遍
    （数据损坏，不只是列表里的视觉重复），故这里防御性去重。
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
