"""
blender_efx/extern_props.py — Extern 段字段展开

EFX_EXTERN 对象上挂 efx_extern (EFXExternProps)：
  items: CollectionProperty(EFXExternItemProps)        ← 对应 ExternDataItem
    instances: CollectionProperty(EFXExternInstanceProps) ← 对应每个元素实例
      field_items: CollectionProperty(EFXFieldItem)    ← 复用体块字段基础设施

已有完整 schema 的 14 个定长 EXTERN 类型支持字段展开（flat schema，一次性按
elem_size 等分）：
  EXTERNSPAWN / EXTERNVELOCITY3D / EXTERNSCALEANIM /
  EXTERNEMITTERSHAPE3D / EXTERNRGBFIRE / EXTERNTRANSFORM3D / EXTERNPLEMISSIVE /
  EXTERNUVSEQUENCE / EXTERNBILLBOARD3D / EXTERNRGBWATER /
  EXTERNLIFE / EXTERNPLSNOW / EXTERNPARENTEMISSIVE / EXTERNROTATEANIM
（EXTERNPLEMISSIVE 与主属性 PLEMISSIVE 尺寸/布局完全相同，76B 语料验证零反例；
 EXTERNUVSEQUENCE / EXTERNBILLBOARD3D / EXTERNRGBWATER 与各自主属性的定长前缀
 同构，多出固定 5B 尾巴（int32+byte，语义未知），语料验证零反例，见
 schema/attributes.py 对应 SCHEMA 上方注释与 memory extern-tier1-plus5-byte-tail。
 EXTERNLIFE/PLSNOW/PARENTEMISSIVE/ROTATEANIM 原以"VELOCITY3D0/2/5/6"命名当 opaque
 处理，实为对应主属性 LIFE/PLSNOW/PARENTEMISSIVE/ROTATEANIM 的 Extern 覆盖版
 （尺寸精确匹配，pack(unpack(x))==x 全语料零反例），直接复用主属性 schema，见
 schema/attributes.py 对应位置注释与 memory extern-velocity3d-misnomer-corrected。）

另外 4 个变长 EXTERN 类型（每元素尺寸不定，不能等分）复用同名主属性的现成
编解码 + Blender 侧字段展开函数（EFXExternInstanceProps 与 EFXAttributeProps
共享 field_items/raw_b64/is_editable 接口，可直接传 inst 代替 bp）：
  EXTERNMESH        → 每元素 = unpack_mesh/pack_mesh（Mod3Properties 174B +
                      BeginMod3 + 2 条 null 结尾路径），init 走
                      fields._init_path_attribute_props
  EXTERNPTBEHAVIOR  → 每元素 = unpack_ptbehavior/pack_ptbehavior（与主属性
                      PTBEHAVIOR 同源 EFX_Behavior 编码），init 走
                      fields._init_path_attribute_props（内部会分派到 Phase B）
  EXTERNTYPERIBBON  → 每元素 = unpack_ribbon/pack_ribbon（主属性 RIBBON 的
                      360B 定长前缀 + 1 条 null 结尾路径），曾以
                      "EXTERNVELOCITY3D1"命名、按 361B 定长硬编码——语料里路径
                      恰好全为空才凑出"看似定长"的假象，2026-09-20 改按真实
                      变长处理，见 efxfile.py::_extern_data_size
  EXTERNTYPEPLANE   → 每元素 = unpack_plane/pack_plane（主属性 PLANE 的
                      104B DDS 段 + int32 path_len + 48B extras + 显式长度
                      路径），曾以"EXTERNVELOCITY3D7"命名、按 157B 定长硬编码，
                      2026-09-20 同上改按真实变长处理
四者导出统一走 fields.rebuild_extern_instance_bytes(inst, type_hash)。
语料验证（tools/ 内脚本，未入库）：PLEMISSIVE 36/36、MESH 285/285、
PTBEHAVIOR 127/127、RIBBON 73/73、PLANE 6/6 元素级 pack(unpack(x))==x 零反例。

⚠ 另外 8 个类型是 FABRICATED（虚构，无真实样本）——全部 efx_samples/ 语料从未出现过，
社区 BT 参考模板把它们写成空 typedef、RE Engine DTI 转储也不提供可区分的结构信息。
尺寸/布局是照抄"已确认"条目的规律外推猜测的（详见 efxfile.py::_extern_data_size
顶部大段注释），当作 FIXED 类型接进同一套 flat schema 展开路径：
  EXTERNFADEBYANGLE / EXTERNFADEBYDEPTH / EXTERNUVCONTROL / EXTERNGUIDE /
  EXTERNPARENTSNOW / EXTERNOTOMOSNOW —— 主属性本身不含路径，原样等长复制。
  EXTERNSTRAINRIBBON / EXTERNTURBULENCE —— 主属性含内嵌路径，仿照 UVSEQUENCE/
  BILLBOARD3D/RGBWATER 的"路径换 5 字节尾巴"规律外推，尾巴全填 0。
这 8 个在 UI 里名字带 "?" 后缀（见 panels.py 用 structs.FABRICATED_EXTERN_HASHES
判断），提醒用户这不是坐实结论。一旦真的遇到样本，先核对字节是否吻合再决定要不要改。

其余类型（EXTERNITEM 等）显示 "Not supported yet"——连主属性 schema 都没有，
没有任何依据可以外推，不勉强猜。

Export 策略：
  - is_editable=True 的实例：rebuild_data_bytes（逐字段；edited=True 的才 repack）
  - 其余：raw_b64 原样（byte-perfect 保底）
  - 任何 except：整个 ExternAttribute 回退到 efx_extern.raw_b64
"""

import base64
import struct

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
            EXTERNPLEMISSIVE,
            EXTERNLIFE, EXTERNPLSNOW, EXTERNPARENTEMISSIVE, EXTERNROTATEANIM,
            EXTERNFADEBYANGLE, EXTERNFADEBYDEPTH, EXTERNUVCONTROL, EXTERNGUIDE,
            EXTERNPARENTSNOW, EXTERNOTOMOSNOW,
        )
        from ..efx_format.structs import (
            EXTERN_SPAWN_SCHEMA, EXTERN_VELOCITY3D_SCHEMA, EXTERN_SCALEANIM_SCHEMA,
            EXTERN_EMITTERSHAPE3D_SCHEMA, EXTERN_RGBFIRE_SCHEMA, EXTERN_TRANSFORM3D_SCHEMA,
            PLEMISSIVE_SCHEMA, LIFE_SCHEMA, PLSNOW_SCHEMA, PARENTEMISSIVE_SCHEMA,
            ROTATEANIM_SCHEMA, FADEBYANGLE_SCHEMA, FADEBYDEPTH_SCHEMA, UVCONTROL_SCHEMA,
            GUIDE_SCHEMA, PARENTSNOW_SCHEMA, OTOMOSNOW_SCHEMA,
        )
        _EXTERN_SCHEMA_MAP_CACHE = {
            EXTERNSPAWN:           (EXTERN_SPAWN_SCHEMA,           72),
            EXTERNVELOCITY3D:      (EXTERN_VELOCITY3D_SCHEMA,      108),
            EXTERNSCALEANIM:       (EXTERN_SCALEANIM_SCHEMA,        76),
            EXTERNEMITTERSHAPE3D:  (EXTERN_EMITTERSHAPE3D_SCHEMA,   88),
            EXTERNRGBFIRE:         (EXTERN_RGBFIRE_SCHEMA,          112),
            EXTERNTRANSFORM3D:     (EXTERN_TRANSFORM3D_SCHEMA,      228),
            # 与主属性 PLEMISSIVE 尺寸/布局完全相同（76B，无 path），语料验证零反例。
            EXTERNPLEMISSIVE:      (PLEMISSIVE_SCHEMA,              76),
            # 与主属性 fixed schema 前缀完全同构 + 固定 5B 尾巴（int32+byte，语义未知，
            # 语料验证：值恒定/取值集合稳定，零反例），见 structs.py 对应 SCHEMA 注释。
            # 曾以 EXTERNVELOCITY3D0/2/5/6 命名、按纯统计推断处理，2026-09-20 查明是
            # 对应主属性的 Extern 覆盖版，尺寸精确匹配 + 全语料 pack(unpack(x))==x
            # 零反例，直接复用主属性 schema，见 schema/attributes.py 对应位置注释。
            EXTERNLIFE:            (LIFE_SCHEMA,                    48),
            EXTERNPLSNOW:          (PLSNOW_SCHEMA,                  84),
            EXTERNPARENTEMISSIVE:  (PARENTEMISSIVE_SCHEMA,          72),
            EXTERNROTATEANIM:      (ROTATEANIM_SCHEMA,              80),
            # ⚠ FABRICATED（虚构，无真实样本）：从未在任何语料里出现过，尺寸/布局是按
            # 上面这些"已确认"条目的规律外推猜测的，见 efxfile.py::_extern_data_size
            # 顶部大段注释与 memory extern-alias-field-registry-gap。
            EXTERNFADEBYANGLE:     (FADEBYANGLE_SCHEMA,             40),
            EXTERNFADEBYDEPTH:     (FADEBYDEPTH_SCHEMA,             20),
            EXTERNUVCONTROL:       (UVCONTROL_SCHEMA,              236),
            EXTERNGUIDE:           (GUIDE_SCHEMA,                  112),
            EXTERNPARENTSNOW:      (PARENTSNOW_SCHEMA,              80),
            EXTERNOTOMOSNOW:       (OTOMOSNOW_SCHEMA,               84),
        }
    except Exception:
        _EXTERN_SCHEMA_MAP_CACHE = {}
    return _EXTERN_SCHEMA_MAP_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# 变长 EXTERN 类型（每元素尺寸不定）→ (元素分割函数, 主属性 type_hash) 映射
# 分割函数签名：(data: bytes, off: int) -> (element_bytes, new_off)
# ─────────────────────────────────────────────────────────────────────────────

_EXTERN_VARLEN_MAP_CACHE = None


def _get_extern_varlen_map() -> dict:
    global _EXTERN_VARLEN_MAP_CACHE
    if _EXTERN_VARLEN_MAP_CACHE is not None:
        return _EXTERN_VARLEN_MAP_CACHE
    try:
        from ..efx_format.hashes import (
            EXTERNMESH, EXTERNPTBEHAVIOR, MESH, PTBEHAVIOR,
            EXTERNTYPERIBBON, EXTERNTYPEPLANE, RIBBON, PLANE,
            EXTERNUVSEQUENCE, EXTERNBILLBOARD3D, EXTERNRGBWATER,
            EXTERNSTRAINRIBBON, EXTERNTURBULENCE,
            UVSEQUENCE, BILLBOARD3D, RGBWATER, STRAINRIBBON, TURBULENCE,
        )
        from ..efx_format.structs import (
            unpack_mesh, unpack_ptbehavior, unpack_ribbon, unpack_plane,
            unpack_uvsequence, unpack_billboard3d, unpack_rgbwater,
            unpack_strainribbon, unpack_turbulence,
        )

        def _split_mesh(data, off):
            start = off
            _, off = unpack_mesh(data, off)
            return data[start:off], off

        def _split_ptbehavior(data, off):
            start = off
            _, off = unpack_ptbehavior(data, off)
            return data[start:off], off

        def _split_ribbon(data, off):
            start = off
            _, off = unpack_ribbon(data, off)
            return data[start:off], off

        def _split_plane(data, off):
            start = off
            _, off = unpack_plane(data, off)
            return data[start:off], off

        def _make_split(fn):
            def _split(data, off):
                start = off
                _, off = fn(data, off)
                return data[start:off], off
            return _split

        _split_uvsequence   = _make_split(unpack_uvsequence)
        _split_billboard3d  = _make_split(unpack_billboard3d)
        _split_rgbwater     = _make_split(unpack_rgbwater)
        _split_strainribbon = _make_split(unpack_strainribbon)
        _split_turbulence   = _make_split(unpack_turbulence)

        _EXTERN_VARLEN_MAP_CACHE = {
            EXTERNMESH:       (_split_mesh,       MESH),
            EXTERNPTBEHAVIOR: (_split_ptbehavior, PTBEHAVIOR),
            # 2026-09-20 订正：这 5 个此前当"主属性定长前缀 + 5B 未知尾巴"按定长处理。
            # 那个尾巴是误读——它是主属性自己的 path_len + 一条空路径。全语料 1049 个
            # 元素实测：直接用主属性 codec 解，消耗字节恰好等于元素长度且 pack(unpack(x))
            # == x 零反例，即 extern 元素就是主属性编码本身。改走变长后顺带修好了字段
            # 错位（旧 schema 解出的 lightGroup 恒为 0x3F800000=float 1.0，明显不是位
            # 掩码；现在是 {1,0,33,32,2}，与主属性侧同形）。见 efxfile.py::_extern_data_size。
            EXTERNUVSEQUENCE:   (_split_uvsequence,  UVSEQUENCE),
            EXTERNBILLBOARD3D:  (_split_billboard3d, BILLBOARD3D),
            EXTERNRGBWATER:     (_split_rgbwater,    RGBWATER),
            EXTERNSTRAINRIBBON: (_split_strainribbon, STRAINRIBBON),
            EXTERNTURBULENCE:   (_split_turbulence,  TURBULENCE),
            # 曾以 EXTERNVELOCITY3D1/7 命名、按定长硬编码（语料里内嵌路径恰好全为空才
            # 凑出"看似定长"的假象），2026-09-20 查明是主属性 RIBBON/PLANE 的 Extern
            # 覆盖版，改按真实变长处理，见 efxfile.py::_extern_data_size。
            EXTERNTYPERIBBON: (_split_ribbon,     RIBBON),
            EXTERNTYPEPLANE:  (_split_plane,      PLANE),
        }
    except Exception:
        _EXTERN_VARLEN_MAP_CACHE = {}
    return _EXTERN_VARLEN_MAP_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup 层次结构
# ─────────────────────────────────────────────────────────────────────────────

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

    # field_items 在 register() 里通过延迟注解挂上，以避免循环引用问题。
    # 实际在类体外用 __annotations__ 注入。


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

    # raw_b64: 该 item 所有实例的原始数据（不含 12B header），
    # 供只读或未编辑时导出使用。
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

    # EA 级的"状态/列"下标：同一个 EFX_EXTERN 下所有 item（Spawn/Velocity3D/...）
    # 共用一个下标，一次切换让全部 item 同步切到第 N 个实例（同一列=一个完整状态）。
    # 少数 EA 各 item 槽数不一致时，各 item 按自己的范围 clamp，见 panels.py。
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

    # 整个 Extern 的原始数据（最终兜底）
    raw_b64: StringProperty(
        name="Raw Bytes",
        description="整个 Extern 的原始数据（base64），只读或未编辑时导出直接使用",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 实例导航算子
# ─────────────────────────────────────────────────────────────────────────────

def _unsplit_extern_items(ep) -> list:
    """返回没有拆成独立槽的 item 的显示名（instances 数与权威的 orig_attr_count 对不上）。

    两种成因：类型不在 schema_map/varlen_map 里（整块 opaque），或变长类型拆分失败
    降级成了单个 opaque instance（见 _init_varlen_extern_item 的 except 分支）。
    这类 item 的"某一列"在工具层面取不出来，任何按列增删都必须先排除它们。
    """
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
    """
    处理变长 EXTERN 类型（EXTERNMESH / EXTERNPTBEHAVIOR）：按 attr_count 把
    data_bytes 拆成独立元素，每个元素包一层 AttrBlock(type_hash=同名主属性)，
    复用 fields._init_path_attribute_props 展开字段（该函数只认 field_items/
    raw_b64/is_editable 接口，EFXExternInstanceProps 与 EFXAttributeProps 都满足，
    不需要额外适配）。

    任何一步不满足（拆分异常/越界剩余字节）→ 整体退回单个 opaque instance，
    与其余未落 schema 类型的兜底行为一致。
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# create_extern_item — 新建/编辑用：给某个 EA 加一个 item（ExternDataItem）
# ─────────────────────────────────────────────────────────────────────────────

# ── 变长类型的空白元素模板 ────────────────────────────────────────────────────
# 变长元素不能像定长那样"补零到 elem_size"——定长头、内嵌路径的终止符都得在，
# 空字节喂给 unpack_* 必然抛异常。这里各存一份从 efx_samples/official 抓的**最小**
# 真实元素（均已验证 pack(unpack(x)) == x），新建 item 无种子时用它起手。
# 路径字段在这些模板里本来就是空的（全语料 491 个 extern 变长元素路径无一非空）。
_BLANK_VARLEN_B64 = {
    "EXTERNMESH":       "AAAAAKcAAAAAzc3NAACgQAAAAAAAQJxFAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAAAAAAAAAAAAP///////////////wAAAP8AAAAAAAAAAAQAAAAAAAAAAgAAAAEAAAABAAAACQAAAAAAAAAJAAAAAAAAAAAAAQEAAQEAAAAAAAAAAAAA",  # noqa: E501
    "EXTERNPTBEHAVIOR": "AAAAABUAAAABAAAATWhQb2ludExpZ2h0QmVoYXZpb3IAKNLim+LZ8KsPAAAACAQE/w==",
    "EXTERNTYPEPLANE":  "AAAAAAAAAACjqsHm/////wAAwD8AAIA/AAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAA7FE4Po/CdT4AAKBBAACgQQAAjEIAAHBCAACAPwAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAABAAAAAAAAAAAAAAAAAAAABAAAAAAAIEIAAKBBAABwwgAA8EIAAKDBAAAgQiAAAAABAAAAAA==",  # noqa: E501
    "EXTERNTYPERIBBON": "AAAAAGABAAAAzc3NfFyy/wHNzc1gXLL/Ac3NzQAAyEIAAAAAAQAAAAAA4D8AAAA/AABAPwAAAD8AAIA/AACAQAAAAAAAAIA/AAAAAAAAgD8CAAAAAAAAAM3MzD0BAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAABAQABAADNzQAAgD/Nzc3NAAAAPwAAAD8AAIA/AAAAAGZmZj8AAAAAzczMPQAAAAAAzc3NAAAAAAAAAAAAAAAAAAAAAM3MzD0AAAAAAAAAAAAAAAAAzc3NAACAPwAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAAAAM3NAAAAAAAAAAAAzc3NAACAPwAAgD8AAIA/AACAPwDNzc2amZk+zczMPgEAzc0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM3Nzc3Nzc3Nzc3Nzc0AAAAAAAAAAAAAAAAAAAAAAA==",  # noqa: E501
}


def _blank_varlen_element(extern_type_hash: int) -> bytes:
    """变长类型的空白元素字节；没有模板时返回 b""（调用方的实例会退成不可编辑）。"""
    from ..efx_format.hashes import HASH_TO_NAME
    b64 = _BLANK_VARLEN_B64.get(HASH_TO_NAME.get(extern_type_hash, ""))
    return base64.b64decode(b64) if b64 else b""


def fill_extern_instance(inst, base: bytes, extern_type_hash: int) -> None:
    """把 base 这段字节灌进一个 instance（槽），并展开成可编辑字段。

    新建 item、复制状态列都走这一份——两处各写一遍迟早会漂开，而且字段展开的
    roundtrip 闸门（重建字节 ≠ 原字节就退回不可编辑）必须处处一致，否则会出现
    "看着能编辑、导出却和显示的值对不上"。
    """
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
                # roundtrip 闸门，同 init_extern_props 导入路径同一套纪律
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
    """一个槽当前的实际字节——可编辑的按字段重建（反映用户改过的值），否则用原始字节。

    与 export_extern_data 取字节的口径保持一致：复制出来的新列必须等于导出时会写
    出去的那一份，不能是导入时的旧值。
    """
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


def create_extern_item(ep, extern_type_hash: int, seed_bytes: bytes = None,
                        n_slots: int = None) -> "EFXExternItemProps":
    """
    在 ep（EFXExternProps，某 EFX_EXTERN 对象的 efx_extern）下新建一个 item
    （对应一个 ExternDataItem），补齐所有槛位并同步 orig_attr_count（导出权威值，
    见 export_extern_data 顶部注释——两者不一致会产出崩游戏的文件，2026-07 修的
    GitHub issue #1 就是这个坑）。

    参数
    ----
    ep : EFXExternProps
        目标 EA。
    extern_type_hash : int
        新 item 的类型（EXTERN* 哈希）。必须在 `_get_extern_schema_map()` 或
        `_get_extern_varlen_map()` 里，否则退化为不可编辑的单槛 opaque item
        （调用方应先按这两张表筛选候选，不要把不支持的类型传进来）。
    seed_bytes : bytes | None
        单槛的种子字节：
          - flat schema 类型（14 个，含 8 个 FABRICATED）：按 elem_size 补 0 /
            截断——"同尺寸"和"+5B 尾巴"两档统一处理：尾巴档种子天然比 elem_size
            短 5B，补 0 后正好等价于"补上 5B 尾巴"。
          - 变长类型（4 个）：原样整段使用（一个元素本身就是主属性的完整编码，
            不需要额外处理）。
          - None：等价于全 0 字节（空白 item）。
        所有槛用同一份种子（状态 A=B=…=现值），用户再自行改其它槛。
    n_slots : int | None
        新 item 的槛数。None 时：EA 已有 item → 取现有最大槛数（对齐既有列）；
        EA 还是空的 → 默认 2（语料 93.3% 的槛数）。

    返回
    ----
    新建的 EFXExternItemProps。
    """
    from . import fields as _fields
    from ..efx_format.structs import unpack
    from ..efx_format.efxfile import AttrBlock

    if n_slots is None:
        # 用权威的 orig_attr_count 对齐既有列数，而不是 len(instances)——不可拆的
        # opaque item 只有 1 个显示用 instance，拿它当列数会让新 item 比实际列数短。
        n_slots = max((int(i.orig_attr_count) for i in ep.items), default=0) or 2
    n_slots = max(1, int(n_slots))

    it = ep.items.add()
    it.type_hash_str = str(int(extern_type_hash))
    it.unkn_str = "0"
    it.ui_expand = True
    # 权威值——下面两个分支各自填 n_slots 个 instance，必须与之同步。
    it.orig_attr_count = n_slots

    schema_map = _get_extern_schema_map()
    varlen_map = _get_extern_varlen_map()

    entry = schema_map.get(extern_type_hash)
    if entry is not None:
        schema, elem_size = entry
        base = seed_bytes if seed_bytes is not None else b""
        if len(base) < elem_size:
            base = base + b"\x00" * (elem_size - len(base))
        elif len(base) > elem_size:
            base = base[:elem_size]

        it.is_editable = True
        it.raw_b64 = base64.b64encode(base * n_slots).decode("ascii")
        for _ in range(n_slots):
            fill_extern_instance(it.instances.add(), base, extern_type_hash)
        return it

    varlen_entry = varlen_map.get(extern_type_hash)
    if varlen_entry is not None:
        # 变长类型没有"补零到 elem_size"这回事——一个元素至少要有合法的定长头和
        # 路径终止符，空字节喂进 unpack 必然抛异常，实例会被标成不可编辑，
        # 表现就是"新加的 ExternMesh 显示只读"。所以无种子时用真实样本模板起手。
        base = seed_bytes if seed_bytes is not None else _blank_varlen_element(extern_type_hash)
        it.is_editable = True
        it.raw_b64 = base64.b64encode(base * n_slots).decode("ascii")
        for _ in range(n_slots):
            fill_extern_instance(it.instances.add(), base, extern_type_hash)
        return it

    # 未落 schema 的类型：调用方本不该把这种类型传进来，这里只做安全兜底——
    # 退化为不可编辑的 opaque 单槛，槛数强制回 1，保持 orig_attr_count 与实际
    # instances 数量一致（同上，这是不能破的不变量）。
    it.is_editable = False
    it.orig_attr_count = 1
    it.ui_expand = False
    base = seed_bytes if seed_bytes is not None else b""
    it.raw_b64 = base64.b64encode(base).decode("ascii")
    inst = it.instances.add()
    inst.raw_b64 = it.raw_b64
    inst.is_editable = False
    return it


def _extern_item_candidate_hashes() -> set:
    """"添加 Item" 的候选类型全集：schema_map ∪ varlen_map（含 FABRICATED，
    与主属性一键覆盖入口不同——那里只用 18 个坐实类型，见 _get_main_to_extern_map）。"""
    return set(_get_extern_schema_map()) | set(_get_extern_varlen_map())


_EXTERN_ITEM_CANDIDATE_ITEMS_CACHE = None


def _get_extern_item_candidate_items(self, context):
    """EFX_OT_extern_item_add_search 的动态 EnumProperty items 回调。

    候选类型集合只取决于 schema_map/varlen_map（进程启动后不变），缓存一次即可，
    不需要 attribute_ops.py 那套 TTL 失效（那边缓存的是随时可能被用户编辑的
    预设文件目录，这里没有对应的外部可变状态）。
    """
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
    都有对应常量，直接靠名字反查，不需要额外维护一张手写表。
    """
    global _MAIN_TO_EXTERN_CACHE
    if _MAIN_TO_EXTERN_CACHE is not None:
        return _MAIN_TO_EXTERN_CACHE
    try:
        from ..efx_format.hashes import HASH_TO_NAME, NAME_TO_HASH
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
    try:
        seed_bytes = _io_tree._resolve_attribute_data_bytes(attr_obj, extern_map, entry_map, play_map)
    except Exception:
        seed_bytes = base64.b64decode(str(attr_obj.get("data_bytes", "")))

    ep = ea_obj.efx_extern
    create_extern_item(ep, extern_hash, seed_bytes=seed_bytes,
                        n_slots=2 if new_ea_created else None)

    repointed = current_ea is not None and current_ea is not ea_obj

    if er_obj is None:
        # unkn0=0，referenceIndex=-1（哨兵）；后面立刻覆写为指向 ea_obj，这里的
        # 初值只是让 add_attribute_to_entry 内部的 init_extern_ref_props 走一条
        # 干净的路径，不依赖它猜出什么有意义的值。
        preset = {
            "efx_preset_kind": "attribute",
            "type_hash": str(_EXTERNREFERENCE_HASH),
            "data_bytes": base64.b64encode(struct.pack('<ii', 0, -1) + b"\x00" * 28).decode("ascii"),
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

        attr_type = int(ep.attr_type_str)
        item_count = len(ep.items)
        out = struct.pack('<IiIi', attr_type, ep.null0, item_count, ep.null1)

        schema_map = _get_extern_schema_map()
        varlen_map = _get_extern_varlen_map()

        for it in ep.items:
            type_hash = int(it.type_hash_str)
            unkn = int(it.unkn_str)
            # ⚠ 用 orig_attr_count（导入时记的原始值），不能用 len(it.instances)——
            # 未落 schema 的类型不管真实 attr_count 多大都只建 1 个 opaque instance，
            # len(instances) 恒为 1，会把 attr_count 错写成 1（2026-07 修，见 GitHub
            # issue #1：EXTERNMESH attr_count 2→1 导致 MHW 崩溃）。变长类型
            # （EXTERNMESH/EXTERNPTBEHAVIOR）导入时按真实元素数建 instance，两者
            # 恰好相等，但仍用 orig_attr_count 保持同一套防御逻辑。
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
            elif it.is_editable and type_hash in varlen_map:
                _split_fn, main_type_hash = varlen_map[type_hash]
                inst_bytes = b""
                for inst in it.instances:
                    if inst.is_editable:
                        try:
                            inst_bytes += _fields.rebuild_extern_instance_bytes(inst, main_type_hash)
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
