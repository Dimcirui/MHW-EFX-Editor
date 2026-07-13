"""
blender_efx/normalize.py  —  顶层段的规范化设施（重编号 + 满命名）

本模块是「结构权威下放」重构的公共基础，供 io_tree 导入端、operators 导出端、
reorder 重排算子共用。三件事：

1. renumber_group / renumber_all_groups —— efx_index 撞车规范化
   每个同级组（EFX_ENTRY / EFX_ACTION / EFX_EXTERN / EFX_SUBSELECT）按
   (efx_index, name) 稳定排序后重赋 efx_index = 0..n-1，并重建显示名。
   - 排序次级键用 name：Blender 原生 Shift+D 的副本带 ".001" 后缀，天然排在源之后，
     使"复制出的副本紧跟源"这一直觉成立。
   - 幂等：已是 0..n-1 连续序时不改动（返回 False）。
   - 主要解决原生复制（Shift+D）导致两个同级对象 efx_index 撞车的问题——
     导出端调用一次即化解；reorder/delete 各自也走全组重编号，故撞车只是瞬态。

2. ensure_all_named —— 满命名（反查真名优先，绝不重算身份哈希）
   给所有 efx_has_label==0 的 action/entry（standard）补 has_label=1 + 标签。
   ⚠ EFX_ACTION.play_type / EFX_ENTRY(standard).body_type 是 jamcrc(段名) 派生的
   **权威身份哈希**（语料实证 100%/99.7%，见 memory play-type-is-jamcrc-of-name）
   ——未命名段仍带着真实非零哈希（"有名字但没进标签表"，非零装饰）。**本函数只
   反查/合成标签字符串，绝不改动 body_type/play_type**：
     ① 优先用 efx_format.jamcrc_names.JAMCRC_TO_NAME 反查现有哈希 → 命中则用
        反查出的真名（body_type/play_type 与新标签天然自洽，语料验证 47/47 命中）；
     ② 未命中（当前语料 0 例）→ 退回合成 "类型_序号"（哈希与标签不一致但哈希
        本就已保留，不构成新问题）。
   EFX_EXTERN 的 attr_type 是固定类型常量（如 EXTERNSPAWN），与 label 名无关，
   无身份哈希顾虑，合成命名永远安全。EFX_ENTRY 非 standard（extended/root）的
   body_type 也不是名字哈希（extended≡1，root≡ROOT_MARKER），同样直接合成。
   满命名后标签表变为"全命名"（连续前缀退化为满），copy/duplicate 永不破坏前缀，
   can_label 前缀边界机器随之作废。

   **用户手动改名**（reorder.py EFX_OT_rename_entry/rename_action_extern）走
   不同规则：改名即改身份，**必须重算** body_type/play_type = jamcrc(新名)——
   与 ensure_all_named 的"反查/保留哈希"正好相反，两条规则各管一段生命周期
   （导入时的自动命名 vs 用户主动改名），互不冲突。

约束（CLAUDE.md）：Python 3.10 语法、bpy 稳定子集、不改 efx_format/。
"""

import bpy

from . import root_collection as _rc


# 顶层段（归属 root 所在文件集合、参与 efx_index 重编号）
_ROOT_GROUP_TYPES = ("EFX_ENTRY", "EFX_ACTION", "EFX_EXTERN", "EFX_SUBSELECT")

# 满命名合成标签前缀（仅 label 表条目：action/extern/entry；subselect 不在标签表）
_NAME_PREFIX = {
    "EFX_ACTION": "action",
    "EFX_EXTERN": "extern",
    "EFX_ENTRY":  "entry",
}


def _nn(idx: int) -> str:
    """零填充 2 位序号（>99 不填充），与 io_tree/reorder/delete_ops 命名一致。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _collect_group(root, type_tag: str) -> list:
    """收集 root 文件集合下 ~TYPE==type_tag 的顶层对象，按 (efx_index, name) 稳定排序
    （root_collection.collect_top_level 已按 efx_index 排序，这里补 name 次级键，
    保证 Shift+D 撞车出的同 index 副本按 name 拆出确定前后顺序）。"""
    objs = _rc.collect_top_level(root, type_tag)
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
    # entry / action / extern：{nn} {raw_label}
    raw_label = str(obj.get("efx_raw_label", "") or "")
    return "%s %s" % (_nn(idx), raw_label) if raw_label else "%s %s" % (_nn(idx), type_tag.lower())


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
            return None  # extended≡1 / root≡ROOT_MARKER，非名字哈希
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
        from ..efx_format.jamcrc_names import JAMCRC_TO_NAME
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
