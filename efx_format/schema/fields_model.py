# -*- coding: utf-8 -*-
"""
efx_format/schema/fields_model.py — typed field-object schema 模型

设计
────────────────────────────────────────────────────────────────────────────
参照 RE-Engine-Lib EFX：把 structs.py 里裸 tuple `('name', 'i')` 升级成**带语义的
Field 对象**（Enum/Bool/Bitmask/Float…），**类型即语义**，标签 / tooltip / 枚举选项 /
位定义全挂在字段声明这一处，不再靠 field_labels.py / annotations.py 两张并行表补。

核心不变量：**Field 只是元数据层，降级(lower)成现有 structs.py codec 认识的
`(name, spec)` tuple**。codec（unpack / pack / _schema_size）一行都不用改——lower 后的
spec 与手写 tuple 逐字节等价，故 `serialize(parse(x)) == x` 由构造保证。

用法
────
    ax = EnumDef("AxisDirection6", [(0, "Left", "左"), (1, "Up", "上"), ...])
    attr = Attribute(size=108, fields=[
        Int("typeFlag"),
        Enum("baseAxis", ax, label_zh="基准轴"),
        Float("speed", label_zh="速度"),
        ...
    ])
    attr.schema     # → [('typeFlag','i'), ('baseAxis','i'), ('speed','f'), ...]
                    #    直接喂给 ATTR_SCHEMA_MAP / structs.unpack / structs.pack

迁移期新旧共存：ATTR_SCHEMA_MAP 里既可放 Attribute.schema（新），也可放手写 tuple
list（旧），逐块迁移，codec 无感。
"""

from __future__ import annotations
from typing import Any, Callable, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 枚举 / 位定义（语义元数据，可跨字段复用）
# ─────────────────────────────────────────────────────────────────────────────

class EnumOption(object):
    """单个枚举取值：value=底层整数，en/zh=显示标签。"""
    __slots__ = ("value", "en", "zh")

    def __init__(self, value, en, zh=""):
        self.value = int(value)
        self.en = en
        self.zh = zh or en


class EnumDef(object):
    """命名枚举定义。options 元素接受 (value, en[, zh]) 或 EnumOption。"""
    __slots__ = ("name", "options")

    def __init__(self, name, options):
        self.name = name
        self.options = [
            o if isinstance(o, EnumOption) else EnumOption(*o)
            for o in options
        ]

    def label(self, value, zh=False):
        """value→标签；超出集合返回 None（UI 层据此回退显示原值）。"""
        for o in self.options:
            if o.value == value:
                return o.zh if zh else o.en
        return None


class BitDef(object):
    """单个位定义（**可混合** toggle 位）：bit=位掩码整数，en/zh=显示标签。UI 渲成勾选框。"""
    __slots__ = ("bit", "en", "zh")

    def __init__(self, bit, en, zh=""):
        self.bit = int(bit)
        self.en = en
        self.zh = zh or en


class BitEnum(object):
    """**互斥**位组：mask 覆盖的（通常连续）几位编码一个 one-of-N 值，UI 渲成下拉（同 enum）。
    options 元素接受 (subval, en[, zh]) 或 EnumOption；subval 是 (value & mask) >> shift 后的值。
    en/zh 是这一组的显示名（组标签）。"""
    __slots__ = ("mask", "shift", "en", "zh", "options")

    def __init__(self, mask, options, en="", zh=""):
        self.mask = int(mask)
        # shift = mask 最低置位的位号
        self.shift = (self.mask & -self.mask).bit_length() - 1 if self.mask else 0
        self.en = en
        self.zh = zh or en
        self.options = [
            o if isinstance(o, EnumOption) else EnumOption(*o)
            for o in options
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Field 基类 + 便捷子类
# ─────────────────────────────────────────────────────────────────────────────

class Field(object):
    """
    带语义的字段声明。降级成 codec 认识的 (name, spec) tuple。

    属性
      name       : ori_name —— 全仓库锚点（标签表 / 预设 key / TIML DT 映射都靠它）
      spec       : 降级后的 legacy spec atom（'i'/'f'/('XYZ',0)/'colour'…）
      widget     : Blender 层控件提示（'int'/'float'/'uint'/'enum'/'bool'/'bitmask'/'raw'）
      label_en/zh: 显示标签（可选；未来取代 field_labels.py）
      tip_en/zh  : tooltip（可选；未来取代 annotations.py；只写结论不写研究记录）
      readonly   : 只读（0xCD 填充 / padding 等）
    """
    widget = "raw"

    def __init__(self, name, spec, *, label_en=None, label_zh=None,
                 tip_en=None, tip_zh=None, readonly=False, widget=None):
        self.name = name
        self.spec = spec
        self.label_en = label_en
        self.label_zh = label_zh
        self.tip_en = tip_en
        self.tip_zh = tip_zh
        self.readonly = readonly
        if widget is not None:
            self.widget = widget

    def __repr__(self):
        return "%s(%r, spec=%r)" % (type(self).__name__, self.name, self.spec)


class _Scalar(Field):
    """标量便捷基类：子类设 _SPEC / _WIDGET。"""
    _SPEC = None
    _WIDGET = "raw"

    def __init__(self, name, **kw):
        super().__init__(name, self._SPEC, widget=self._WIDGET, **kw)


class Int(_Scalar):    _SPEC = 'i';  _WIDGET = "int"     # int32
class UInt(_Scalar):   _SPEC = 'I';  _WIDGET = "uint"    # uint32（存字符串避免溢出）
class Short(_Scalar):  _SPEC = 'h';  _WIDGET = "int"     # int16
class UShort(_Scalar): _SPEC = 'H';  _WIDGET = "int"     # uint16
class Byte(_Scalar):   _SPEC = 'B';  _WIDGET = "int"     # uint8
class SByte(_Scalar):  _SPEC = 'b';  _WIDGET = "int"     # int8
class Float(_Scalar):  _SPEC = 'f';  _WIDGET = "float"   # float32
class Int64(_Scalar):  _SPEC = 'q';  _WIDGET = "uint"    # int64（存字符串）
class UInt64(_Scalar): _SPEC = 'Q';  _WIDGET = "uint"    # uint64（存字符串）


class Enum(Field):
    """枚举字段：底层整数（默认 int32），UI 渲成下拉。"""
    def __init__(self, name, enum_def, *, backing='i', **kw):
        super().__init__(name, backing, widget="enum", **kw)
        self.enum = enum_def


class EnumVec3(Field):
    """
    逐轴枚举字段：底层是一组 3 个整数（默认 ('XYZ', 1) = 3×int32），每个分量各自是同一
    EnumDef 的独立枚举取值。UI 渲成 X/Y/Z 三个并排下拉。
    典型：PARENTOPTIONS 的 translation/angle/scale tracking（每轴独立的跟随模式）。
    """
    def __init__(self, name, enum_def, *, spec=('XYZ', 1), **kw):
        super().__init__(name, spec, widget="enum_vec3", **kw)
        self.enum = enum_def


class Bool(Field):
    """布尔字段：底层整数（默认 int32），UI 渲成勾选框。"""
    def __init__(self, name, *, backing='i', **kw):
        super().__init__(name, backing, widget="bool", **kw)


class Bitmask(Field):
    """位掩码字段：底层整数，UI 渲成弹窗（勾选框 = 可混合 BitDef，下拉 = 互斥 BitEnum；
    段外残留位保留并可编辑）。bits 是有序列表，元素可为 BitDef / BitEnum / (bit,en[,zh]) 元组。"""
    def __init__(self, name, bits, *, backing='i', **kw):
        super().__init__(name, backing, widget="bitmask", **kw)
        self.bits = [
            b if isinstance(b, (BitDef, BitEnum)) else BitDef(*b)
            for b in bits
        ]


class Raw(Field):
    """
    任意 legacy spec 原样包装（('XYZ',n) / 'colour' / 'EPVColorSlot' / ('f',N) 数组…）。
    迁移期的逃生舱：让任何块都能先迁进模型，专用字段类（Vec/Color…）作为语法糖后补。
    """
    def __init__(self, name, spec, **kw):
        super().__init__(name, spec, widget="raw", **kw)


# ─────────────────────────────────────────────────────────────────────────────
# Attribute 记录（hybrid：list-of-Field + 每块专属元数据集中一处）
# ─────────────────────────────────────────────────────────────────────────────

class Attribute(object):
    """
    一个 EFX attribute 块类型的 typed 声明。

      hash             : 块类型哈希（可选；structs.py 里 hash 常量晚于 schema 定义导入，
                         故允许定义时留空、导入后回填）
      size             : data_bytes 字节数（不含 4 字节类型哈希）；变长块传 None
      fields           : List[Field]
      label_zh         : 块级中文名（可选）
      native_timl_axis : TIML 动画锁定轴（见记忆 timl-block-native-axis）
      validate         : 可选的每块校验钩子 validate(values: dict) -> None
    """
    __slots__ = ("hash", "size", "fields", "label_zh",
                 "native_timl_axis", "validate", "_schema_cache")

    def __init__(self, size, fields, *, hash=None, label_zh=None,
                 native_timl_axis=None, validate=None):
        self.hash = hash
        self.size = size
        self.fields = list(fields)
        self.label_zh = label_zh
        self.native_timl_axis = native_timl_axis
        self.validate = validate
        self._schema_cache = None

    @property
    def schema(self):
        """降级成 codec 认识的 [(name, spec), ...]。缓存单一 list 对象（供按身份反查
        hash / 避免每次重建；schema 定义后 fields 不再变动，缓存安全）。"""
        if self._schema_cache is None:
            self._schema_cache = [(f.name, f.spec) for f in self.fields]
        return self._schema_cache

    def field_by_name(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 全局注册表（供 Blender 层 / 标签 shim 按 hash 反查字段元数据）
# ─────────────────────────────────────────────────────────────────────────────

ATTR_REGISTRY = {}                    # type_hash -> Attribute
FIELD_REGISTRY = {}                   # (type_hash, field_name) -> Field


def register(attr):
    """把已回填 hash 的 Attribute 登记进全局注册表；返回该 attr（便于链式）。"""
    if attr.hash is None:
        raise ValueError("register(): Attribute.hash 未回填，无法登记")
    ATTR_REGISTRY[attr.hash] = attr
    for f in attr.fields:
        FIELD_REGISTRY[(attr.hash, f.name)] = f
    return attr


# ─────────────────────────────────────────────────────────────────────────────
# legacy tuple schema → typed Attribute 的机械降级
# ─────────────────────────────────────────────────────────────────────────────

_SPEC_TO_FIELD = {
    'i': Int, 'I': UInt, 'h': Short, 'H': UShort,
    'B': Byte, 'b': SByte, 'f': Float, 'q': Int64, 'Q': UInt64,
}


def attr_from_legacy(size, schema, *, labels=None, overrides=None, hash=None):
    """把 legacy `(name, spec)` tuple schema **机械**降级成 typed Attribute：
    标量单字符 spec 映射到对应 Field 子类，其余（('XYZ',n) / 'EPVColorSlot' / ('f',N)
    / 嵌套数组…）包 Raw，spec 一律原样保留 → `.schema` 与输入逐字节等价。

    用途：尚未逐字段手写语义的 custom 变长块——只需把固定段字段注册进 FIELD_REGISTRY
    即可解锁标签/控件/过滤，无需一次性把上百个 unkn 字段手写成显式 Field。已确认语义的
    字段可后续逐一改成显式 Enum/Bool 等（tuple 仍是该块 on-disk 权威，ATTR 是派生视图）。
    labels: 可选 {name: 中文标签}。
    overrides: 可选 {name: Field}，对指定字段用显式 Field 取代自动降级（如 Enum/Bitmask）。
      override Field 的 spec 必须与 tuple spec 一致，否则报错——保证字节等价不被破坏。"""
    labels = labels or {}
    overrides = overrides or {}
    fields = []
    for name, spec in schema:
        ov = overrides.get(name)
        if ov is not None:
            if ov.spec != spec:
                raise ValueError(
                    "attr_from_legacy: override %r spec %r != schema spec %r"
                    % (name, ov.spec, spec))
            fields.append(ov)
            continue
        lz = labels.get(name)
        cls = _SPEC_TO_FIELD.get(spec) if isinstance(spec, str) else None
        if cls is not None:
            fields.append(cls(name, label_zh=lz))
        else:
            fields.append(Raw(name, spec, label_zh=lz))
    return Attribute(size=size, fields=fields, hash=hash)
