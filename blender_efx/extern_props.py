"""
blender_efx/extern_props.py — Extern 段字段展开

EFX_EXTERN 对象上挂 efx_extern (EFXExternProps)：
  items: CollectionProperty(EFXExternItemProps)        ← 对应 ExternDataItem
    instances: CollectionProperty(EFXExternInstanceProps) ← 对应每个元素实例
      field_items: CollectionProperty(EFXFieldItem)    ← 复用体块字段基础设施

已有完整 schema 的 6 个 EXTERN 类型支持字段展开：
  EXTERNSPAWN / EXTERNVELOCITY3D / EXTERNSCALEANIM /
  EXTERNEMITTERSHAPE3D / EXTERNRGBFIRE / EXTERNTRANSFORM3D
其余类型显示 "Not supported yet"。

Export 策略：
  - is_editable=True 的实例：rebuild_data_bytes（逐字段；edited=True 的才 repack）
  - 其余：raw_b64 原样（byte-perfect 保底）
  - 任何 except：整个 ExternAttribute 回退到 efx_extern.raw_b64
"""

import base64
import struct

import bpy
from bpy.props import (
    StringProperty, BoolProperty, IntProperty,
    CollectionProperty, PointerProperty,
)
from bpy.types import PropertyGroup, Operator


# ─────────────────────────────────────────────────────────────────────────────
# EXTERN 类型 hash → (schema, elem_size) 映射
# ─────────────────────────────────────────────────────────────────────────────

_EXTERN_SCHEMA_MAP_CACHE = None


def _get_extern_schema_map() -> dict:
    global _EXTERN_SCHEMA_MAP_CACHE
    if _EXTERN_SCHEMA_MAP_CACHE is not None:
        return _EXTERN_SCHEMA_MAP_CACHE
    try:
        from ..efx_format.hashes import (
            EXTERNSPAWN, EXTERNVELOCITY3D, EXTERNSCALEANIM,
            EXTERNEMITTERSHAPE3D, EXTERNRGBFIRE, EXTERNTRANSFORM3D,
        )
        from ..efx_format.structs import (
            EXTERN_SPAWN_SCHEMA, EXTERN_VELOCITY3D_SCHEMA, EXTERN_SCALEANIM_SCHEMA,
            EXTERN_EMITTERSHAPE3D_SCHEMA, EXTERN_RGBFIRE_SCHEMA, EXTERN_TRANSFORM3D_SCHEMA,
        )
        _EXTERN_SCHEMA_MAP_CACHE = {
            EXTERNSPAWN:           (EXTERN_SPAWN_SCHEMA,           72),
            EXTERNVELOCITY3D:      (EXTERN_VELOCITY3D_SCHEMA,      108),
            EXTERNSCALEANIM:       (EXTERN_SCALEANIM_SCHEMA,        76),
            EXTERNEMITTERSHAPE3D:  (EXTERN_EMITTERSHAPE3D_SCHEMA,   88),
            EXTERNRGBFIRE:         (EXTERN_RGBFIRE_SCHEMA,          112),
            EXTERNTRANSFORM3D:     (EXTERN_TRANSFORM3D_SCHEMA,      228),
        }
    except Exception:
        _EXTERN_SCHEMA_MAP_CACHE = {}
    return _EXTERN_SCHEMA_MAP_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup 层次结构
# ─────────────────────────────────────────────────────────────────────────────

class EFXExternInstanceProps(PropertyGroup):
    """ExternDataItem 中的单个元素实例（attr_count 个之一）。"""

    raw_b64: StringProperty(
        name="Raw Bytes",
        description="该实例的原始字节（base64），导出 fallback",
    )

    is_editable: BoolProperty(
        name="Editable",
        default=False,
    )

    # field_items 在 register() 里通过延迟注解挂上，以避免循环引用问题。
    # 实际在类体外用 __annotations__ 注入。


class EFXExternItemProps(PropertyGroup):
    """一个 ExternDataItem（某 EXTERN* 类型 + 若干元素实例）。"""

    type_hash_str: StringProperty(
        name="Type Hash",
        description="ExternDataItem 类型 hash（十进制字符串）",
    )

    unkn_str: StringProperty(
        name="Unkn",
        description="ExternDataItem.unkn（保留原值）",
        default="0",
    )

    orig_attr_count: IntProperty(
        name="Original Attr Count",
        description=(
            "ExternDataItem.attr_count 原始值（权威，导出直接用这个，不用 len(instances)）。"
            "未落 schema 的类型（如 EXTERNMESH）不管 attr_count 多大都只建 1 个 opaque "
            "instance（整块 data_bytes 存一起），len(instances) 恒为 1，跟真实元素数无关——"
            "这个字段是唯一记住真实数量的地方，不存会导致导出把 attr_count 错写成 1。"
        ),
        default=0,
    )

    active_instance: IntProperty(
        name="Active Instance",
        description="当前编辑的实例索引",
        default=0,
        min=0,
    )

    is_editable: BoolProperty(
        name="Editable",
        default=False,
    )

    # raw_b64: 该 item 所有实例的原始 data_bytes（不含 12B header），
    # 供 is_editable=False 或整体 fallback 时使用。
    raw_b64: StringProperty(
        name="Item Raw Bytes",
        description="ExternDataItem.data_bytes（base64），导出 fallback",
    )

    instances: CollectionProperty(
        type=EFXExternInstanceProps,
        name="Instances",
    )


class EFXExternProps(PropertyGroup):
    """挂到 bpy.types.Object.efx_extern（EFX_EXTERN Empty）。"""

    attr_type_str: StringProperty(
        name="Attr Type",
        description="ExternAttribute.attr_type（十进制字符串）",
    )

    null0: IntProperty(name="null0", default=0)
    null1: IntProperty(name="null1", default=0)

    active_item: IntProperty(
        name="Active Item",
        default=0,
        min=0,
    )

    items: CollectionProperty(
        type=EFXExternItemProps,
        name="Items",
    )

    # 完整 ExternAttribute 序列化字节（最终 fallback）
    raw_b64: StringProperty(
        name="Raw Bytes",
        description="完整 ExternAttribute 原始字节（base64），导出最终 fallback",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 实例导航算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_extern_instance_prev(Operator):
    bl_idname = "efx.extern_instance_prev"
    bl_label  = "Previous Instance"
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
        it = ep.items[min(ep.active_item, len(ep.items) - 1)]
        if it.active_instance > 0:
            it.active_instance -= 1
        return {"FINISHED"}


class EFX_OT_extern_instance_next(Operator):
    bl_idname = "efx.extern_instance_next"
    bl_label  = "Next Instance"
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
        it = ep.items[min(ep.active_item, len(ep.items) - 1)]
        if it.active_instance < len(it.instances) - 1:
            it.active_instance += 1
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
        ep.active_item = 0

        schema_map = _get_extern_schema_map()

        for item_data in ea.items:
            it = ep.items.add()
            it.type_hash_str = str(item_data.type_hash)
            it.unkn_str = str(item_data.unkn)
            it.orig_attr_count = int(item_data.attr_count)
            it.active_instance = 0
            it.raw_b64 = base64.b64encode(item_data.data_bytes).decode("ascii")
            it.instances.clear()

            entry = schema_map.get(item_data.type_hash)
            if entry is None:
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

        attr_type = int(ep.attr_type_str)
        item_count = len(ep.items)
        out = struct.pack('<IiIi', attr_type, ep.null0, item_count, ep.null1)

        schema_map = _get_extern_schema_map()

        for it in ep.items:
            type_hash = int(it.type_hash_str)
            unkn = int(it.unkn_str)
            # ⚠ 用 orig_attr_count（导入时记的原始值），不能用 len(it.instances)——
            # 未落 schema 的类型（EXTERNMESH 等）不管真实 attr_count 多大都只建 1 个
            # opaque instance，len(instances) 恒为 1，会把 attr_count 错写成 1
            # （2026-07 修，见 GitHub issue #1：EXTERNMESH attr_count 2→1 导致 MHW 崩溃）。
            attr_count = it.orig_attr_count

            if it.is_editable and type_hash in schema_map:
                schema, _elem_size = schema_map[type_hash]
                inst_bytes = b""
                for inst in it.instances:
                    if inst.is_editable:
                        try:
                            inst_bytes += _fields.rebuild_data_bytes(inst, schema)
                        except Exception:
                            inst_bytes += base64.b64decode(inst.raw_b64)
                    else:
                        inst_bytes += base64.b64decode(inst.raw_b64)
                out += struct.pack('<Iii', type_hash, unkn, attr_count) + inst_bytes
            else:
                item_data = base64.b64decode(it.raw_b64)
                out += struct.pack('<Iii', type_hash, unkn, attr_count) + item_data

        return out

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
