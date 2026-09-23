"""Extern 段的实例字段展开、编辑与导出。

维护约束：
- 每个 Extern item 的实例数由 orig_attr_count 定义；同一状态列必须跨全部 item 对齐。
- 定长类型按元素大小拆分；变长类型必须使用对应主属性 codec 切分，不能按固定长度猜测。
- 无法展开或未编辑的实例保留 raw_b64；重建失败时整个 ExternAttribute 回退原始数据。
- 仅纯定长 schema 映射可直接复用；标为 FABRICATED 的映射必须在 UI 中保持不确定标识。
"""

import base64

import bpy
from bpy.props import (
    StringProperty, BoolProperty, IntProperty, EnumProperty,
    CollectionProperty, PointerProperty,
)
from bpy.types import PropertyGroup, Operator

from .i18n import T

# poll_message_set 是 4.0+ API（3.6 上没有），用于给禁用按钮显示原因
_HAS_POLL_MESSAGE_SET = hasattr(bpy.types.Operator, "poll_message_set")


# ─────────────────────────────────────────────────────────────────────────────
# EXTERN 类型布局：数据取自 efx_format.assembly.extern，这里只换成胶水层的形状
# ─────────────────────────────────────────────────────────────────────────────

_EXTERN_SCHEMA_MAP_CACHE = None
_EXTERN_VARLEN_MAP_CACHE = None


def _get_extern_schema_map() -> dict:
    """定长 EXTERN 类型 hash → (schema, elem_size)。FABRICATED 类型仍须由 UI 标为不确定。"""
    global _EXTERN_SCHEMA_MAP_CACHE
    if _EXTERN_SCHEMA_MAP_CACHE is None:
        from ..efx_format.assembly.extern import EXTERN_FIXED_SCHEMA
        from ..efx_format.structs import _schema_size
        _EXTERN_SCHEMA_MAP_CACHE = {h: (schema, _schema_size(schema))
                                    for h, schema in EXTERN_FIXED_SCHEMA.items()}
    return _EXTERN_SCHEMA_MAP_CACHE


def _get_extern_varlen_map() -> dict:
    """变长 EXTERN 类型 hash → (元素切分函数, 主属性类型)。"""
    global _EXTERN_VARLEN_MAP_CACHE
    if _EXTERN_VARLEN_MAP_CACHE is None:
        from ..efx_format.assembly.extern import EXTERN_VARLEN_MAIN
        from ..efx_format.structs import ATTR_CUSTOM_CODEC

        def _make_split(unpack_fn):
            def _split(data, off):
                start = off
                _, off = unpack_fn(data, off)
                return data[start:off], off
            return _split

        _EXTERN_VARLEN_MAP_CACHE = {
            h: (_make_split(ATTR_CUSTOM_CODEC[main][0]), main)
            for h, main in EXTERN_VARLEN_MAIN.items()
        }
    return _EXTERN_VARLEN_MAP_CACHE


# PropertyGroup 层次结构

class EFXExternInstanceProps(PropertyGroup):
    """ExternDataItem 中的单个元素实例（attr_count 个之一）。"""

    raw_b64: StringProperty(
        name="Raw Bytes",
        description="该实例的原始数据（base64），只读或未编辑时导出直接使用",
    )

    is_editable: BoolProperty(
        name="Editable",
        default=False,
    )

    # field_items 延迟注入，避免循环引用。


class EFXExternItemProps(PropertyGroup):
    """一个 ExternDataItem（某 EXTERN* 类型 + 若干元素实例）。"""

    type_hash_str: StringProperty(
        name="Type Hash",
        description="此项数据的类型哈希（十进制字符串）",
    )

    unkn_str: StringProperty(
        name="Unkn",
        description="原样保留的未知字段",
        default="0",
    )

    orig_attr_count: IntProperty(
        name="Original Attr Count",
        description=(
            "导出时使用的元素数量（权威值）。部分类型暂不按元素拆分显示，仍会作为一整块"
            "数据处理，但这个数量会原样保留，不会在导出时丢失。"
        ),
        default=0,
    )

    ui_expand: BoolProperty(
        name="Expand",
        description="是否展开显示此项的字段",
        default=False,
    )

    is_editable: BoolProperty(
        name="Editable",
        default=False,
    )

    raw_b64: StringProperty(
        name="Item Raw Bytes",
        description="该项的原始数据（base64），只读或未编辑时导出直接使用",
    )

    instances: CollectionProperty(
        type=EFXExternInstanceProps,
        name="Instances",
    )


class EFXExternProps(PropertyGroup):
    """挂到 bpy.types.Object.efx_extern（EFX_EXTERN Empty）。"""

    attr_type_str: StringProperty(
        name="Attr Type",
        description="此 Extern 的类型（十进制字符串）",
    )

    null0: IntProperty(name="null0", default=0)
    null1: IntProperty(name="null1", default=0)

    # 所有 item 共用的状态列索引。
    active_instance: IntProperty(
        name="Active State",
        description="当前编辑的状态（列）索引，作用于此 Extern 下的所有项",
        default=0,
        min=0,
    )

    items: CollectionProperty(
        type=EFXExternItemProps,
        name="Items",
    )

    raw_b64: StringProperty(
        name="Raw Bytes",
        description="整个 Extern 的原始数据（base64），只读或未编辑时导出直接使用",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 实例导航算子
# ─────────────────────────────────────────────────────────────────────────────

def _unsplit_extern_items(ep) -> list:
    """返回无法按状态列拆分的 item；列编辑必须拒绝它们。"""
    from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name
    out = []
    for it in ep.items:
        try:
            if len(it.instances) != int(it.orig_attr_count):
                th = int(it.type_hash_str)
                out.append(pretty_type_name(HASH_TO_NAME.get(th, "")) or "0x%08X" % th)
        except (ValueError, TypeError):
            continue
    return out


def _extern_max_instance_count(ep) -> int:
    """跨该 EA 全部 item 的最大槽数（用于 EA 级状态切换器的上界）。"""
    return max((len(it.instances) for it in ep.items), default=0)


class EFX_OT_extern_instance_prev(Operator):
    bl_idname = "efx.extern_instance_prev"
    bl_label  = "Previous State"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def execute(self, context):
        obj = context.active_object
        ep  = obj.efx_extern
        if not ep.items:
            return {"CANCELLED"}
        if ep.active_instance > 0:
            ep.active_instance -= 1
        return {"FINISHED"}


class EFX_OT_extern_instance_next(Operator):
    bl_idname = "efx.extern_instance_next"
    bl_label  = "Next State"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def execute(self, context):
        obj = context.active_object
        ep  = obj.efx_extern
        if not ep.items:
            return {"CANCELLED"}
        if ep.active_instance < _extern_max_instance_count(ep) - 1:
            ep.active_instance += 1
        return {"FINISHED"}


def _init_varlen_extern_item(it, item_data, varlen_entry, _fields) -> None:
    """用主属性 codec 拆分变长元素；失败时整体回退 opaque 实例。"""
    from ..efx_format.efxfile import AttrBlock

    split_fn, main_type_hash = varlen_entry
    data = item_data.data_bytes
    attr_count = item_data.attr_count

    elements = []
    off = 0
    try:
        for _ in range(attr_count):
            elem_bytes, off = split_fn(data, off)
            elements.append(elem_bytes)
        if off != len(data):
            raise ValueError("varlen extern split leftover bytes")
    except Exception:
        it.is_editable = False
        inst = it.instances.add()
        inst.raw_b64 = it.raw_b64
        inst.is_editable = False
        return

    it.is_editable = True
    for elem_bytes in elements:
        inst = it.instances.add()
        inst.raw_b64 = base64.b64encode(elem_bytes).decode("ascii")
        blk = AttrBlock(type_hash=main_type_hash, data_bytes=elem_bytes)
        try:
            _fields._init_path_attribute_props(blk, inst)
        except Exception:
            inst.is_editable = False
            inst.field_items.clear()


def fill_extern_instance(inst, base: bytes, extern_type_hash: int) -> None:
    """以字节初始化实例；重建不一致时保持不可编辑。"""
    from . import fields as _fields
    from ..efx_format.structs import unpack
    from ..efx_format.efxfile import AttrBlock

    inst.raw_b64 = base64.b64encode(base).decode("ascii")

    entry = _get_extern_schema_map().get(extern_type_hash)
    if entry is not None:
        schema, _elem_size = entry
        try:
            values, _off = unpack(schema, base)
            ok = _fields.dict_to_items(values, schema, inst, data_bytes=base)
            inst.is_editable = bool(ok)
            if inst.is_editable:
                if _fields.rebuild_data_bytes(inst, schema) != base:
                    inst.is_editable = False
                    inst.field_items.clear()
        except Exception:
            inst.is_editable = False
            inst.field_items.clear()
        return

    varlen_entry = _get_extern_varlen_map().get(extern_type_hash)
    if varlen_entry is not None:
        _split_fn, main_type_hash = varlen_entry
        try:
            _fields._init_path_attribute_props(
                AttrBlock(type_hash=main_type_hash, data_bytes=base), inst)
        except Exception:
            inst.is_editable = False
            inst.field_items.clear()
        return

    inst.is_editable = False


def extern_instance_bytes(it, inst) -> bytes:
    """返回实例当前导出字节；不可编辑时使用原始字节。"""
    from . import fields as _fields

    if inst.is_editable:
        try:
            type_hash = int(it.type_hash_str)
        except (ValueError, TypeError):
            type_hash = 0
        entry = _get_extern_schema_map().get(type_hash)
        try:
            if entry is not None:
                return _fields.rebuild_data_bytes(inst, entry[0])
            varlen_entry = _get_extern_varlen_map().get(type_hash)
            if varlen_entry is not None:
                return _fields.rebuild_extern_instance_bytes(inst, varlen_entry[1])
        except Exception:
            pass
    return base64.b64decode(inst.raw_b64)


def create_extern_item(ep, extern_type_hash: int, seed_values: dict = None,
                        n_slots: int = None) -> "EFXExternItemProps":
    """创建 item 并同步所有状态列与 orig_attr_count。

    每个 Set 由 ``seed_values``（Set 字段值）组装；未给出时取该类型的默认值。
    没有 Extern codec 的类型抛 ValueError。
    """
    from ..efx_format import assembly as _asm

    if extern_type_hash not in _get_extern_schema_map()             and extern_type_hash not in _get_extern_varlen_map():
        raise ValueError(f"create_extern_item：0x{extern_type_hash:08X} 没有 Extern codec")

    if n_slots is None:
        # opaque item 的显示实例数不能代表实际列数。
        n_slots = max((int(i.orig_attr_count) for i in ep.items), default=0) or 2
    n_slots = max(1, int(n_slots))

    values = seed_values if seed_values is not None else _asm.default_extern_set(extern_type_hash)
    base = _asm.encode_extern_sets(extern_type_hash, [values])

    it = ep.items.add()
    it.type_hash_str = str(int(extern_type_hash))
    it.unkn_str = "0"
    it.ui_expand = True
    it.orig_attr_count = n_slots
    it.is_editable = True
    it.raw_b64 = base64.b64encode(base * n_slots).decode("ascii")
    for _ in range(n_slots):
        fill_extern_instance(it.instances.add(), base, extern_type_hash)
    return it


def _extern_item_candidate_hashes() -> set:
    """返回可手动添加的定长与变长 Extern 类型。"""
    return set(_get_extern_schema_map()) | set(_get_extern_varlen_map())


_EXTERN_ITEM_CANDIDATE_ITEMS_CACHE = None


def _get_extern_item_candidate_items(self, context):
    """返回可缓存的 Extern 类型枚举项。"""
    global _EXTERN_ITEM_CANDIDATE_ITEMS_CACHE
    if _EXTERN_ITEM_CANDIDATE_ITEMS_CACHE is None:
        try:
            from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name
            items = [(str(h), pretty_type_name(HASH_TO_NAME.get(h, "")) or "0x%08X" % h, "")
                     for h in _extern_item_candidate_hashes()]
            items.sort(key=lambda t: t[1])
            _EXTERN_ITEM_CANDIDATE_ITEMS_CACHE = items or [("0", "(no supported extern types)", "")]
        except Exception:
            _EXTERN_ITEM_CANDIDATE_ITEMS_CACHE = [("0", "(load error)", "")]
    return _EXTERN_ITEM_CANDIDATE_ITEMS_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# main_type_hash ↔ extern_type_hash（供"选中属性一键加对应 extern 覆盖"用）
# ─────────────────────────────────────────────────────────────────────────────

_MAIN_TO_EXTERN_CACHE = None


def _get_main_to_extern_map() -> dict:
    """main_type_hash → extern_type_hash，只覆盖 CLAUDE.md 数据模型坐实的 18 个类型
    （11 同尺寸 + 3 +5B 尾巴 + 4 变长），不含 8 个 FABRICATED——未坐实结构不该被
    "一键"鼓励，这些类型仍然只能通过"添加 Item"搜索手动加（并在标题里看到
    "?" 后缀提醒）。

    命名规则：extern 类型名去掉 "EXTERN" 前缀 == 对应主属性名，hashes 模块里两边
    都有对应常量，直接靠名字反查，不需要额外维护一张手写表——但 EXTERNTYPERIBBON/
    EXTERNTYPEPLANE 是例外：历史遗留的 "TYPE" 中缀让名字反查落空（"TYPERIBBON"/
    "TYPEPLANE" 在 hashes 模块里都不存在），这两个已确认（非 FABRICATED，byte-size
    + 全语料 pack/unpack 验证过，见 efx_format/structs.py 的 EXTERN_HASH_ALIASES）
    却因为这个命名反查漏洞一直没能"一键"，2026-09-21 补上显式覆盖。
    """
    global _MAIN_TO_EXTERN_CACHE
    if _MAIN_TO_EXTERN_CACHE is not None:
        return _MAIN_TO_EXTERN_CACHE
    try:
        from ..efx_format.hashes import (
            HASH_TO_NAME, NAME_TO_HASH, RIBBON, PLANE,
            EXTERNTYPERIBBON, EXTERNTYPEPLANE,
        )
        from ..efx_format.structs import FABRICATED_EXTERN_HASHES
        out = {}
        for h in _extern_item_candidate_hashes():
            if h in FABRICATED_EXTERN_HASHES:
                continue
            name = HASH_TO_NAME.get(h, "")
            if name.startswith("EXTERN"):
                main_hash = NAME_TO_HASH.get(name[len("EXTERN"):])
                if main_hash is not None:
                    out[main_hash] = h
        # 命名反查够不到的例外，直接补：
        out[RIBBON] = EXTERNTYPERIBBON
        out[PLANE] = EXTERNTYPEPLANE
        _MAIN_TO_EXTERN_CACHE = out
    except Exception:
        _MAIN_TO_EXTERN_CACHE = {}
    return _MAIN_TO_EXTERN_CACHE


def main_to_extern_hash(main_type_hash: int):
    """main_type_hash → 对应 extern 类型哈希；查不到（无对应类型 / 是 FABRICATED）
    返回 None。"""
    try:
        return _get_main_to_extern_map().get(int(main_type_hash))
    except (ValueError, TypeError):
        return None


class ExternItemAlreadyExists(Exception):
    """目标 EA 已经有同类型 item，调用方应展示 ea_obj/extern_hash 并直接放弃，
    不做任何改动（见 add_extern_override_for_attribute 规则 5）。"""

    def __init__(self, ea_obj, extern_hash):
        super().__init__(f"{ea_obj.name} already has this item type")
        self.ea_obj = ea_obj
        self.extern_hash = extern_hash


def _find_entry_extern_ref(entry_obj):
    """该 entry 现有的 EXTERNREFERENCE 属性对象；没有则 None（entry 内至多 1 个，
    全语料 114914 个 entry 无一例外，见模块顶部数据模型说明）。"""
    from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
    from . import attribute_ops as _attr_ops
    for sib in _attr_ops.iter_entry_attributes(entry_obj):
        try:
            if int(str(sib.get("type_hash", "0"))) == _EXTERNREFERENCE_HASH:
                return sib
        except (ValueError, TypeError):
            continue
    return None


def _er_target_ea(er_obj):
    """er_obj（EXTERNREFERENCE 属性）当前指向的有效 EA；没有/悬空/哨兵则 None。"""
    if er_obj is None:
        return None
    try:
        props = er_obj.efx_extern_ref
        if (props.extern_ref_pointerized and not props.extern_ref_none
                and props.extern_ref_ptr is not None):
            return props.extern_ref_ptr
    except AttributeError:
        pass
    return None


def default_target_ea_ident(attr_obj: bpy.types.Object) -> str:
    """选择弹窗的默认候选值：该 entry 的 ER 当前指向的 EA（有效时用它的对象名），
    否则默认「新建一个 EA」（用 "NEW" 哨兵）。"""
    entry_obj = attr_obj.parent if attr_obj is not None else None
    if entry_obj is None or entry_obj.get("~TYPE") != "EFX_ENTRY":
        return "NEW"
    ea_obj = _er_target_ea(_find_entry_extern_ref(entry_obj))
    return ea_obj.name if ea_obj is not None else "NEW"


def _extern_override_target_label(ea_obj: bpy.types.Object) -> str:
    """EA 选择弹窗里一项的显示标签：名字 + 已有 item 类型（去重）+ 列数，
    例如 "extern_0 — Spawn, RgbFire (2 states)"，方便用户分辨选哪个。"""
    from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name
    ep = ea_obj.efx_extern
    type_names = []
    for it in ep.items:
        try:
            th = int(it.type_hash_str)
        except (ValueError, TypeError):
            continue
        name = pretty_type_name(HASH_TO_NAME.get(th, "")) or "0x%08X" % th
        if name not in type_names:
            type_names.append(name)
    types_part = ", ".join(type_names) if type_names else T("extern.override_empty_ea")
    n_state = _extern_max_instance_count(ep)
    label = str(ea_obj.get("efx_raw_label", "")) or ea_obj.name
    return f"{label} — {types_part} ({n_state} {T('extern.override_states_suffix')})"


# 动态 EnumProperty items 缓存：必须由 Python 侧持有返回的元组列表，否则里面的
# 字符串会被 GC，下拉里的中文标签会花掉——同 attribute_ops.py 那套写法，见
# memory enum-callback-gc-trap。候选集合随选中对象变化，不设 TTL，每次都
# 重新算，只是把结果存回同一个全局变量而不是纯局部变量。
_EXTERN_OVERRIDE_TARGET_ITEMS_CACHE = [("NEW", "New Extern", "")]


def _get_extern_override_target_items(self, context):
    """EFX_OT_add_extern_override_for_attribute.target_ea 的动态 items 回调。
    候选 = 「新建一个 EA」+ 选中属性所在文件（root）里全部已存在的 EA。"""
    global _EXTERN_OVERRIDE_TARGET_ITEMS_CACHE
    from . import root_collection as _rc
    items = [("NEW", T("extern.override_new_ea"), "")]
    try:
        obj = bpy.data.objects.get(getattr(self, "attr_name", ""))
        root_obj = _rc.find_root_collection(obj) if obj is not None else None
        if root_obj is not None:
            for ea in _rc.collect_top_level(root_obj, "EFX_EXTERN"):
                items.append((ea.name, _extern_override_target_label(ea), ""))
    except Exception:
        pass
    _EXTERN_OVERRIDE_TARGET_ITEMS_CACHE = items
    return _EXTERN_OVERRIDE_TARGET_ITEMS_CACHE


def add_extern_override_for_attribute(attr_obj: bpy.types.Object,
                                       target_ea_ident: str = "NEW"):
    """
    给选中的 EFX_ATTRIBUTE 加一个对应类型的 extern 覆盖，目标 EA 由调用方（弹窗）
    指定，不再静默决定。

    参数
    ----
    target_ea_ident : "NEW"（新建一个空白 EA）或某个已存在 EFX_EXTERN 对象的名字。

    规则（与 entry 内至多 1 个 EXTERNREFERENCE 的不变量一致——entry 只能被一个
    EA 驱动，所以"item 放哪"实质是"这个 entry 改由哪个 EA 驱动"）：
      - target 是已存在的 EA 且已经有同类型 item → 不做任何改动，抛
        ExternItemAlreadyExists（调用方据此报告并放弃，不算错误）。
      - 否则：往 target EA（新建或已存在）里加对应 item；若该 entry 原来的
        EXTERNREFERENCE 指向的是另一个 EA（或还没有 ER），把 ER 重新指向 target——
        返回值里 `repointed=True` 且带上旧 EA，调用方必须就此发出警告：旧 EA 里
        对这个 entry 的其它覆盖将不再生效。
    新 item 的种子字节取自该 attribute 当前实际字节（含字段编辑）；新建 EA 时
    强制 2 槛（状态 A=B=现值），复用已存在 EA 时对齐它现有的槛数（交给
    create_extern_item 的既有逻辑，这里不重复实现）。

    返回
    ----
    (ea_obj, repointed, old_ea_obj) —— repointed=True 时 old_ea_obj 是原来的目标
    EA（可能为 None，表示原来没有有效目标）。
    """
    from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
    from . import attribute_ops as _attr_ops
    from . import io_tree as _io_tree
    from . import root_collection as _rc

    if attr_obj is None or attr_obj.get("~TYPE") != "EFX_ATTRIBUTE":
        raise ValueError("add_extern_override_for_attribute：目标不是 EFX_ATTRIBUTE")

    try:
        main_hash = int(str(attr_obj.get("type_hash", "0")))
    except (ValueError, TypeError):
        raise ValueError("add_extern_override_for_attribute：属性类型哈希无效")

    extern_hash = main_to_extern_hash(main_hash)
    if extern_hash is None:
        raise ValueError("add_extern_override_for_attribute：该属性类型没有对应的 extern 类型")

    entry_obj = attr_obj.parent
    if entry_obj is None or entry_obj.get("~TYPE") != "EFX_ENTRY":
        raise ValueError("add_extern_override_for_attribute：该属性没有所属 entry")

    root_obj = _rc.find_root_collection(attr_obj)

    er_obj = _find_entry_extern_ref(entry_obj)
    current_ea = _er_target_ea(er_obj)

    # 解析目标 EA：先看用户选的是不是一个仍然有效的已存在 EA；无效/选了 NEW 就新建。
    ea_obj = None
    if target_ea_ident and target_ea_ident != "NEW":
        candidate = bpy.data.objects.get(target_ea_ident)
        if candidate is not None and candidate.get("~TYPE") == "EFX_EXTERN":
            ea_obj = candidate

    new_ea_created = False
    if ea_obj is None:
        from . import add_section_ops as _add_section
        if root_obj is None:
            raise ValueError("add_extern_override_for_attribute：找不到所属 EFX 根集合")
        ea_obj = _add_section.add_extern(root_obj)
        new_ea_created = True
    else:
        # 复用已存在的 EA：先查重，命中就直接拒绝，不做任何改动（规则 5）。
        existing_types = set()
        for it in ea_obj.efx_extern.items:
            try:
                existing_types.add(int(it.type_hash_str))
            except (ValueError, TypeError):
                pass
        if extern_hash in existing_types:
            raise ExternItemAlreadyExists(ea_obj, extern_hash)

    # 该属性当前实际字节（含字段编辑），同 attribute_ops.build_attribute_preset_dict
    # 取字节的方式一致——种子必须反映用户已经改过的值，不能只用最初导入的原始字节。
    extern_map, entry_map, play_map = {}, {}, {}
    if root_obj is not None:
        extern_map = {o: i for i, o in enumerate(_rc.collect_top_level(root_obj, "EFX_EXTERN"))}
        entry_map = {o: i for i, o in enumerate(_rc.collect_top_level(root_obj, "EFX_ENTRY"))}
        play_map = {o: i for i, o in enumerate(_rc.collect_top_level(root_obj, "EFX_ACTION"))}
    from ..efx_format import assembly as _asm
    try:
        main_bytes = _io_tree._resolve_attribute_data_bytes(attr_obj, extern_map, entry_map, play_map)
    except Exception:
        main_bytes = base64.b64decode(str(attr_obj.get("data_bytes", "")))
    seed_values = _asm.extern_set_from_main(
        extern_hash, _asm.decode_attribute(main_hash, main_bytes))

    ep = ea_obj.efx_extern
    create_extern_item(ep, extern_hash, seed_values=seed_values,
                        n_slots=2 if new_ea_created else None)

    repointed = current_ea is not None and current_ea is not ea_obj

    if er_obj is None:
        # 全部字段取默认值（referenceIndex 为 -1）；随后立即指向 ea_obj。
        preset = {
            "efx_preset_kind": "attribute",
            "format_version": _asm.FORMAT_VERSION,
            "attribute": {"type": _asm.type_key(_EXTERNREFERENCE_HASH), "fields": {}},
        }
        er_obj = _attr_ops.add_attribute_to_entry(entry_obj, preset)

    er_props = er_obj.efx_extern_ref
    er_props.extern_ref_pointerized = True
    er_props.extern_ref_none = False
    er_props.extern_ref_ptr = ea_obj

    return ea_obj, repointed, current_ea


class EFX_OT_extern_item_add_search(Operator):
    """按名字模糊搜索 extern item 类型并直接新增到当前 EA（照抄
    attribute_ops.EFX_OT_attribute_add_search 的 invoke_search_popup 写法）。"""

    bl_idname      = "efx.extern_item_add_search"
    bl_label       = "Add Extern Item"
    bl_description = "Fuzzy-search extern item types and add one to this Extern"
    bl_options     = {"REGISTER", "UNDO"}
    bl_property    = "type_hash_str"

    type_hash_str: EnumProperty(
        name="Type",
        description="要新增的 extern item 类型",
        items=_get_extern_item_candidate_items,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.active_object
        try:
            h = int(self.type_hash_str)
        except (ValueError, TypeError):
            self.report({"ERROR"}, "Invalid extern item type")
            return {"CANCELLED"}
        try:
            create_extern_item(obj.efx_extern, h)
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add this item. See the system console for details.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Extern item added")
        return {"FINISHED"}


class EFX_OT_extern_item_remove(Operator):
    """从当前 EA 里移除一个 item（按下标，来自面板折叠头的 X 按钮）"""

    bl_idname      = "efx.extern_item_remove"
    bl_label       = "Remove Extern Item"
    bl_description = "Remove this item from the Extern"
    bl_options     = {"REGISTER", "UNDO"}

    item_index: IntProperty(name="Item Index", default=-1)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_EXTERN"

    def execute(self, context):
        obj = context.active_object
        ep = obj.efx_extern
        idx = self.item_index
        if idx < 0 or idx >= len(ep.items):
            self.report({"ERROR"}, "Invalid item index")
            return {"CANCELLED"}
        ep.items.remove(idx)
        n_state = _extern_max_instance_count(ep)
        if n_state == 0:
            ep.active_instance = 0
        elif ep.active_instance >= n_state:
            ep.active_instance = n_state - 1
        return {"FINISHED"}


class EFX_OT_extern_state_duplicate(Operator):
    """把当前状态（列）复制一份插到它后面——对该 EA 下的**每一个** item 同步做，
    因为一列横跨全部 item 才构成一个完整状态（见模块顶部数据模型说明）。

    典型用法：一个 EA 只有 1 列时复制出第 2 列，再改第 2 列的值，就得到
    「状态 A → 状态 B」这对可供 EXTERNREFERENCE 的 index0/index1 插值的端点。
    """

    bl_idname      = "efx.extern_state_duplicate"
    bl_label       = "Duplicate State"
    bl_description = ("Copy the current state (column) and insert it right after, "
                      "for every item in this Extern")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_EXTERN":
            return False
        ep = obj.efx_extern
        if not ep.items:
            return False
        # 与删列同一道闸：没拆成独立槽的 item 取不出"某一列的字节"，复制会让
        # 各 item 的列数错开，进而破坏"一列=一个完整状态"的前提。
        if _unsplit_extern_items(ep):
            if _HAS_POLL_MESSAGE_SET:
                cls.poll_message_set(
                    "This Extern has an item whose states cannot be edited separately, "
                    "so a state cannot be duplicated")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        ep = obj.efx_extern
        unsplit = _unsplit_extern_items(ep)
        if unsplit:
            self.report({"ERROR"}, T("extern.state_dup_blocked").format(name=unsplit[0]))
            return {"CANCELLED"}

        n_state = _extern_max_instance_count(ep)
        if n_state <= 0:
            return {"CANCELLED"}
        src_idx = min(ep.active_instance, n_state - 1)

        for it in ep.items:
            n = len(it.instances)
            if n == 0:
                continue
            i = min(src_idx, n - 1)
            base = extern_instance_bytes(it, it.instances[i])
            try:
                type_hash = int(it.type_hash_str)
            except (ValueError, TypeError):
                type_hash = 0
            # CollectionProperty 只能追加，加完再挪到源列紧后面
            fill_extern_instance(it.instances.add(), base, type_hash)
            it.instances.move(len(it.instances) - 1, i + 1)
            # 导出权威值，必须跟着槽数走（export_extern_data 顶部注释里的坑）
            it.orig_attr_count = len(it.instances)

        ep.active_instance = src_idx + 1     # 跳到新复制出来的那一列
        return {"FINISHED"}


class EFX_OT_extern_state_remove(Operator):
    """从当前 EA 的**每一个** item 里移除当前状态（列）——instance 下标横跨全部
    item，必须同步删，否则某些 item 的列会比其它 item 少一格（见模块顶部数据
    模型说明）。"""

    bl_idname      = "efx.extern_state_remove"
    bl_label       = "Remove State"
    bl_description = "Remove the current state (column) from every item in this Extern"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_EXTERN":
            return False
        ep = obj.efx_extern
        if _extern_max_instance_count(ep) <= 0:
            return False
        if _unsplit_extern_items(ep):
            if _HAS_POLL_MESSAGE_SET:
                cls.poll_message_set(
                    "This Extern has an item whose states cannot be edited separately, "
                    "so a state cannot be removed from it")
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        ep = obj.efx_extern
        n_state = _extern_max_instance_count(ep)
        if n_state <= 0:
            return {"CANCELLED"}
        # 没拆成独立槽的 item（不支持的类型、或变长拆分失败降级成整块 opaque）
        # 拿不出"某一列的字节"，删了它的唯一 instance 会把 orig_attr_count 写成 0，
        # 而 raw_b64 里仍是 N 份数据 → 导出的 header 与实际负载对不上，文件结构崩。
        # 这种情况直接拒绝，不做"跳过它只删别人"——那会让各 item 的列数错开。
        unsplit = _unsplit_extern_items(ep)
        if unsplit:
            self.report({"ERROR"}, T("extern.state_remove_blocked").format(
                name=unsplit[0]))
            return {"CANCELLED"}
        state_idx = min(ep.active_instance, n_state - 1)

        for it in ep.items:
            n = len(it.instances)
            if n == 0:
                continue
            it.instances.remove(min(state_idx, n - 1))
            # orig_attr_count 是导出权威值，必须跟着 instances 数量同步——
            # 见 export_extern_data 顶部注释（GitHub issue #1 的坑）。
            it.orig_attr_count = len(it.instances)

        new_max = _extern_max_instance_count(ep)
        if new_max == 0:
            ep.active_instance = 0
        elif ep.active_instance >= new_max:
            ep.active_instance = new_max - 1
        return {"FINISHED"}


class EFX_OT_add_extern_override_for_attribute(Operator):
    """选中一个有对应 extern 类型的 EFX_ATTRIBUTE，弹窗选目标 EA 后加一个 extern
    覆盖（见 add_extern_override_for_attribute 的完整规则说明）。

    弹窗问的实质是"这个 entry 改由哪个 EA 驱动"——entry 内至多 1 个
    EXTERNREFERENCE，所以选哪个 EA 不是"item 放哪"这么简单，选了另一个 EA 会
    让这个 entry 脱离原来的 EA（若有），必须让用户自己决定、自己看到警告。
    """

    bl_idname      = "efx.add_extern_override_for_attribute"
    bl_label       = "Add Extern Override"
    bl_description = ("Add an Extern override for the selected attribute's type; a dialog lets "
                      "you pick which Extern (new or existing) should drive this entry, seeding "
                      "the new item from the attribute's current bytes")
    bl_options     = {"REGISTER", "UNDO"}

    # HIDDEN：只是给动态 items 回调传上下文（选中对象在 invoke 时定住），不进
    # redo 面板重复编辑——重编辑应该重新走一次弹窗，而不是改个名字字符串。
    attr_name: StringProperty(options={"HIDDEN"})
    target_ea: EnumProperty(
        name="Target Extern",
        description="Which Extern should drive this entry (new one, or an existing one already in this file)",
        items=_get_extern_override_target_items,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return False
        try:
            main_hash = int(str(obj.get("type_hash", "0")))
        except (ValueError, TypeError):
            return False
        return main_to_extern_hash(main_hash) is not None

    def invoke(self, context, event):
        obj = context.active_object
        self.attr_name = obj.name
        self.target_ea = default_target_ea_ident(obj)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "target_ea", text=T("extern.override_target_label"))

    def execute(self, context):
        obj = bpy.data.objects.get(self.attr_name)
        if obj is None:
            self.report({"ERROR"}, "Failed to add extern override: attribute object not found")
            return {"CANCELLED"}
        try:
            ea_obj, repointed, old_ea = add_extern_override_for_attribute(obj, self.target_ea)
        except ExternItemAlreadyExists as exc:
            from ..efx_format.hashes import HASH_TO_NAME
            type_name = HASH_TO_NAME.get(exc.extern_hash, f"0x{exc.extern_hash:08X}")
            self.report({"WARNING"}, T("extern.override_already_exists").format(
                ea=exc.ea_obj.name, type=type_name))
            return {"CANCELLED"}
        except Exception:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, "Failed to add this Extern override. See the system console for details.")
            return {"CANCELLED"}

        if repointed:
            old_name = old_ea.name if old_ea is not None else "?"
            self.report({"WARNING"}, T("extern.override_repointed_warning").format(
                new=ea_obj.name, old=old_name))
        else:
            self.report({"INFO"}, f"Extern override added: {ea_obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# init_extern_props — 导入时填充（供 io_tree 调用）
# ─────────────────────────────────────────────────────────────────────────────

def init_extern_props(obj: bpy.types.Object, ea) -> None:
    """
    从解析好的 ExternAttribute ea 填充 obj.efx_extern。

    ea: efx_format.efxfile.ExternAttribute
      .attr_type: int
      .null0 / .null1: int
      .items: List[ExternDataItem]
        each: .type_hash, .unkn, .attr_count, .data_bytes
    """
    from . import fields as _fields
    from ..efx_format.structs import unpack
    try:
        from .fields import _check_schema_all_flat
    except ImportError:
        _check_schema_all_flat = None

    _fields._LOADING = True
    try:
        ep = obj.efx_extern
        ep.attr_type_str = str(ea.attr_type)
        ep.null0 = int(ea.null0)
        ep.null1 = int(ea.null1)
        ep.raw_b64 = base64.b64encode(ea.serialize()).decode("ascii")
        ep.items.clear()
        ep.active_instance = 0

        schema_map = _get_extern_schema_map()

        for item_data in ea.items:
            it = ep.items.add()
            it.type_hash_str = str(item_data.type_hash)
            it.unkn_str = str(item_data.unkn)
            it.orig_attr_count = int(item_data.attr_count)
            it.ui_expand = False
            it.raw_b64 = base64.b64encode(item_data.data_bytes).decode("ascii")
            it.instances.clear()

            entry = schema_map.get(item_data.type_hash)
            if entry is None:
                varlen_entry = _get_extern_varlen_map().get(item_data.type_hash)
                if varlen_entry is not None:
                    _init_varlen_extern_item(it, item_data, varlen_entry, _fields)
                    continue
                it.is_editable = False
                inst = it.instances.add()
                inst.raw_b64 = it.raw_b64
                inst.is_editable = False
                continue

            schema, elem_size = entry

            # 检查 schema 所有字段均可平铺表示
            if _check_schema_all_flat is not None and not _check_schema_all_flat(schema):
                it.is_editable = False
                inst = it.instances.add()
                inst.raw_b64 = it.raw_b64
                inst.is_editable = False
                continue

            attr_count = item_data.attr_count
            total = len(item_data.data_bytes)
            if elem_size <= 0 or total != elem_size * attr_count:
                it.is_editable = False
                inst = it.instances.add()
                inst.raw_b64 = it.raw_b64
                inst.is_editable = False
                continue

            it.is_editable = True
            all_ok = True
            for idx in range(attr_count):
                inst = it.instances.add()
                inst_bytes = item_data.data_bytes[idx * elem_size: (idx + 1) * elem_size]
                inst.raw_b64 = base64.b64encode(inst_bytes).decode("ascii")
                try:
                    values, _ = unpack(schema, inst_bytes)
                    ok = _fields.dict_to_items(values, schema, inst, data_bytes=inst_bytes)
                    if ok:
                        # roundtrip gate
                        rebuilt = _fields.rebuild_data_bytes(inst, schema)
                        if rebuilt == inst_bytes:
                            inst.is_editable = True
                        else:
                            inst.is_editable = False
                            inst.field_items.clear()
                            all_ok = False
                    else:
                        inst.is_editable = False
                        all_ok = False
                except Exception:
                    inst.is_editable = False
                    inst.field_items.clear()
                    all_ok = False

            if not all_ok:
                it.is_editable = False

    finally:
        _fields._LOADING = False


# ─────────────────────────────────────────────────────────────────────────────
# export_extern_data — 导出时重建字节（供 io_tree 调用）
# ─────────────────────────────────────────────────────────────────────────────

def export_extern_data(obj: bpy.types.Object) -> bytes:
    """
    从 obj.efx_extern 重建 ExternAttribute 的序列化字节。

    策略：
    - is_editable=True 的实例：rebuild_data_bytes（edited=False 走 orig_b64，byte-perfect）
    - 否则：raw_b64 原样
    - 任何异常：整体回退到 efx_extern.raw_b64
    """
    ep = obj.efx_extern
    try:
        from . import fields as _fields
        from ..efx_format.efxfile import ExternAttribute, ExternDataItem

        schema_map = _get_extern_schema_map()
        varlen_map = _get_extern_varlen_map()

        items = []
        for it in ep.items:
            type_hash = int(it.type_hash_str)
            # attr_count 用导入时记录的 orig_attr_count：opaque item 只建 1 个实例，
            # len(instances) 不代表真实 Set 数，写错会导致游戏崩溃。
            attr_count = it.orig_attr_count

            if it.is_editable and (type_hash in schema_map or type_hash in varlen_map):
                inst_bytes = b""
                for inst in it.instances:
                    if inst.is_editable:
                        try:
                            if type_hash in schema_map:
                                inst_bytes += _fields.rebuild_data_bytes(inst, schema_map[type_hash][0])
                            else:
                                inst_bytes += _fields.rebuild_extern_instance_bytes(
                                    inst, varlen_map[type_hash][1])
                            continue
                        except Exception:
                            pass
                    inst_bytes += base64.b64decode(inst.raw_b64)
            else:
                inst_bytes = base64.b64decode(it.raw_b64)
            items.append(ExternDataItem(type_hash=type_hash, unkn=int(it.unkn_str),
                                        attr_count=attr_count, data_bytes=inst_bytes))

        return ExternAttribute(attr_type=int(ep.attr_type_str), null0=ep.null0,
                               null1=ep.null1, items=items).serialize()

    except Exception:
        return base64.b64decode(ep.raw_b64)


# ─────────────────────────────────────────────────────────────────────────────
# register / unregister
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFXExternInstanceProps,
    EFXExternItemProps,
    EFXExternProps,
    EFX_OT_extern_instance_prev,
    EFX_OT_extern_instance_next,
    EFX_OT_extern_item_add_search,
    EFX_OT_extern_item_remove,
    EFX_OT_extern_state_duplicate,
    EFX_OT_extern_state_remove,
    EFX_OT_add_extern_override_for_attribute,
)


def register():
    from .fields import EFXFieldItem

    # 延迟注入 field_items 到 EFXExternInstanceProps（避免定义时循环引用）
    if "field_items" not in EFXExternInstanceProps.__annotations__:
        EFXExternInstanceProps.__annotations__["field_items"] = CollectionProperty(
            type=EFXFieldItem,
            name="Field List",
        )

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_extern = PointerProperty(
        name="EFX Extern Properties",
        description="Extern attribute field model (EFX_EXTERN objects only)",
        type=EFXExternProps,
    )


def unregister():
    try:
        del bpy.types.Object.efx_extern
    except AttributeError:
        pass

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
