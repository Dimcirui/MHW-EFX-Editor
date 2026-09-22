"""顶层段的重编号与补全标签。

维护约束：
- 同级对象按 (efx_index, name) 稳定排序后重编号；Root Entry 必须优先。
- 自动补名只修改标签与显示名，绝不重算 Action 或 standard Entry 的身份哈希。
- 用户显式改名的身份哈希更新属于其他模块，不能与自动补名混用。
- 补名后调用方须重建标签表。
"""

import bpy

from . import root_collection as _rc


_ROOT_GROUP_TYPES = ("EFX_ENTRY", "EFX_ACTION", "EFX_EXTERN", "EFX_SUBSELECT")

_NAME_PREFIX = {
    "EFX_ACTION": "action",
    "EFX_EXTERN": "extern",
    "EFX_ENTRY":  "entry",
}


def _nn(idx: int) -> str:
    """返回显示名使用的两位序号。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _collect_group(root, type_tag: str) -> list:
    """按稳定顺序收集顶层对象；Root Entry 始终优先。"""
    objs = _rc.collect_top_level(root, type_tag)
    if type_tag == "EFX_ENTRY":
        objs.sort(key=lambda o: (0 if str(o.get("entry_kind", "")) == "root" else 1,
                                  int(o.get("efx_index", 0)), o.name))
    else:
        objs.sort(key=lambda o: (int(o.get("efx_index", 0)), o.name))
    return objs


def _display_name(obj, type_tag: str, idx: int) -> str:
    """按各类型约定生成显示名（与 io_tree 导入端一致）。"""
    if type_tag == "EFX_SUBSELECT":
        # subselect 无 efx_raw_label，沿用 io_tree 导入命名 "{nn} subselect_{idx}"
        return "%s subselect_%d" % (_nn(idx), idx)
    if type_tag == "EFX_ATTRIBUTE":
        # 属性显示名需父标签 + 类型名，交给 reorder._attribute_display_name（惰性导入）
        from .reorder import (_attribute_display_name, _get_attribute_parent_label,
                              _get_attribute_type_name)
        return _attribute_display_name(idx, _get_attribute_parent_label(obj),
                                       _get_attribute_type_name(obj))
    # entry / action / extern：{nn} {raw_label}{renderer_suffix}
    raw_label = str(obj.get("efx_raw_label", "") or "")
    base = raw_label if raw_label else type_tag.lower()
    if type_tag == "EFX_ENTRY":
        # 渲染主体后缀（如 " (Mesh)"）：entry 独有，action/extern 无渲染主体概念
        from .reorder import _entry_renderer_suffix
        base += _entry_renderer_suffix(obj)
    return "%s %s" % (_nn(idx), base)


def renumber_group(root, type_tag: str) -> bool:
    """
    把 root 下 type_tag 组的 efx_index 重赋 0..n-1（按 (efx_index,name) 稳定序），
    并重建显示名。返回是否有 efx_index 发生变化（撞车/空洞被修复）。
    """
    objs = _collect_group(root, type_tag)
    changed = False
    for new_idx, o in enumerate(objs):
        if int(o.get("efx_index", -1)) != new_idx:
            o["efx_index"] = new_idx
            changed = True
        try:
            o.name = _display_name(o, type_tag, new_idx)
        except Exception:
            pass
    return changed


def renumber_attributes(entry_obj) -> bool:
    """把单个 entry 下 EFX_ATTRIBUTE 的 efx_index 重赋 0..n-1（按 (efx_index,name) 序）。
    供撞车化解——auto_sort 的类型排序在此之后/之前跑均可（都产出唯一 0..n-1）。"""
    objs = [o for o in bpy.data.objects
            if o.parent == entry_obj and o.get("~TYPE") == "EFX_ATTRIBUTE"]
    objs.sort(key=lambda o: (int(o.get("efx_index", 0)), o.name))
    changed = False
    for new_idx, o in enumerate(objs):
        if int(o.get("efx_index", -1)) != new_idx:
            o["efx_index"] = new_idx
            changed = True
        try:
            o.name = _display_name(o, "EFX_ATTRIBUTE", new_idx)
        except Exception:
            pass
    return changed


def renumber_all_groups(root) -> bool:
    """对 root 下全部 4 个顶层组 + 每个 entry 的属性做撞车重编号。返回是否有任何变动。"""
    changed = False
    for tag in _ROOT_GROUP_TYPES:
        if renumber_group(root, tag):
            changed = True
    for e in _collect_group(root, "EFX_ENTRY"):
        if renumber_attributes(e):
            changed = True
    return changed


def _identity_hash(o, type_tag: str):
    """读取 o 当前的身份哈希（play_type / body_type），取不到或该类型无身份哈希
    语义（extern / entry 非 standard）时返回 None。"""
    if type_tag == "EFX_ACTION":
        try:
            return int(str(o.efx_play.play_type_str)) & 0xFFFFFFFF
        except Exception:
            return None
    if type_tag == "EFX_ENTRY":
        if str(o.get("entry_kind", "")) != "standard":
            return None  # root≡ROOT_MARKER，非名字哈希
        try:
            return int(str(o.get("body_type", ""))) & 0xFFFFFFFF
        except (ValueError, TypeError):
            return None
    return None  # EFX_EXTERN：attr_type 是固定类型常量，与名字无关


def _lookup_real_name(hash_val):
    """反查 jamcrc_names 字典；无该模块/未命中返回 None。"""
    if hash_val is None:
        return None
    try:
        from ..efx_format.hashes.jamcrc_names import JAMCRC_TO_NAME
    except ImportError:
        return None
    return JAMCRC_TO_NAME.get(hash_val)


def ensure_all_named(root) -> bool:
    """
    给 root 下所有 efx_has_label==0 的 action/extern/entry 补名（has_label=1 +
    标签字符串），并重建显示名。**绝不改动 body_type/play_type 身份哈希**：

      - EFX_ACTION / EFX_ENTRY(standard)：反查 jamcrc_names 字典 → 命中用真名
        （哈希与新标签天然自洽）；未命中退回合成 "类型_序号"（哈希不受影响）。
      - EFX_EXTERN / EFX_ENTRY(非 standard)：无身份哈希语义，直接合成 "类型_序号"。

    返回是否有任何补名发生（调用方据此置 labels_dirty=1）。
    满命名后所有段都在标签表内 → 前缀恒满 → copy/duplicate 不再破坏前缀。
    """
    changed = False
    for type_tag, prefix in _NAME_PREFIX.items():
        for o in _collect_group(root, type_tag):
            if int(o.get("efx_has_label", 0)) != 0:
                continue
            idx = int(o.get("efx_index", 0))
            real_name = _lookup_real_name(_identity_hash(o, type_tag))
            o["efx_raw_label"] = real_name if real_name else "%s_%s" % (prefix, _nn(idx))
            o["efx_has_label"] = 1
            try:
                o.name = _display_name(o, type_tag, idx)
            except Exception:
                pass
            changed = True
    return changed


def normalize_root(root) -> bool:
    """导出前兜底 / 导入后初始化的统一入口：撞车重编号 + 满命名。返回是否有变动。
    满命名若有变动，调用方应置 root['labels_dirty']=1 使导出重建标签表。"""
    c1 = renumber_all_groups(root)
    c2 = ensure_all_named(root)
    return c1 or c2
