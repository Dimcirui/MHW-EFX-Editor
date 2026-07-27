# -*- coding: utf-8 -*-
"""
efx_format/codec.py — 核心字段编解码（纯 Python，零 bpy）。

schema 是 (name, spec) 列表；codec 按序读写每个字段，保证 pack(unpack(data)) == data。
本模块是编解码基座，被 attributes / custom_codecs / structs 装配层依赖，自身不依赖它们。

spec 原子
---------
标量（Python struct 格式字符，小端）：
    'i' int32   'I' uint32   'f' float32   'h' int16   'H' uint16
    'b' int8    'B' uint8    'q' int64     'Q' uint64
定长数组：('i', 3) → 3×int32；任意标量字母都可搭配个数。
XYZ 变体（EFX_Utils.bt，按类型码参数化）：
    ('XYZ',0) → 6 floats：fixed/random ×3          (24 B)
    ('XYZ',1) → 3×int32 x,y,z                       (12 B)
    ('XYZ',2) → 3 ubyte + 1 pad                     ( 4 B)
    ('XYZ',3) → 3 floats x,y,z                      (12 B)
'colour'       → 4 ubyte r,g,b,a                    ( 4 B，等价 ('B',4) 但语义命名)
'EPVColorSlot' → 定长 36 B 结构（见 _unpack_epvcolorslot）
('XYZ[]',code,count) / ('colour[]',count) → 连续数组
('path','i')   → int32 长度 + 该长度字节（存为 bytes）

存储约定
--------
值以纯 Python 标量/列表/bytes 存进 dict：
    XYZ(0)=[fx,rx,fy,ry,fz,rz]  XYZ(1/3)=[x,y,z]  XYZ(2)=[x,y,z,pad]
    colour=[r,g,b,a]           EPVColorSlot=具名子字段 dict

API
---
    unpack(schema, data, off=0) -> (values_dict, new_off)
    pack(schema, values)        -> bytes
    _schema_size(schema)        -> int   （定长 schema 总字节数）
"""
from __future__ import annotations
import struct
from typing import Any, Dict, List, Tuple

_SCALAR_SIZE: Dict[str, int] = {
    'i': 4, 'I': 4,
    'f': 4,
    'h': 2, 'H': 2,
    'b': 1, 'B': 1,
    'q': 8, 'Q': 8,
}

# ─────────────────────────────────────────────────────────────────────────────
# XYZ helpers
# ─────────────────────────────────────────────────────────────────────────────

_XYZ_FMT = {
    0: ('<6f', 24),   # float fixed_x random_x fixed_y random_y fixed_z random_z
    1: ('<3i', 12),   # int x y z
    2: ('<4B',  4),   # ubyte x y z pad
    3: ('<3f', 12),   # float x y z
}


def _unpack_xyz(t: int, data: bytes, off: int) -> Tuple[list, int]:
    fmt, size = _XYZ_FMT[t]
    vals = list(struct.unpack_from(fmt, data, off))
    return vals, off + size


def _pack_xyz(t: int, vals: list) -> bytes:
    fmt, _ = _XYZ_FMT[t]
    return struct.pack(fmt, *vals)


def _xyz_size(t: int) -> int:
    return _XYZ_FMT[t][1]


# ─────────────────────────────────────────────────────────────────────────────
# EPVColorSlot helper (36 B)
# EFX_Utils.bt:
#   long  EPVColorSlotHead     (4 B)  # schema 字段名 epvColorSlot
#   XYZ   color1(2)            (4 B)  ubyte x,y,z + pad
#   long  NULL2                (4 B)
#   XYZ   color2(2)            (4 B)  ubyte x,y,z + pad
#   int   spacer4               (4 B)
#   int   unkn15               (4 B)
#   float size                 (4 B)
#   int   unkn17               (4 B)
#   byte  unkn18[2]            (2 B)
#   short spacer5              (2 B)
# Total: 4+4+4+4+4+4+4+4+2+2 = 36 B
# ─────────────────────────────────────────────────────────────────────────────

_EPVCSLOT_FIELDS = [
    ('epvColorSlot', 'i'),
    ('color1', ('XYZ', 2)),
    ('null2', 'i'),
    ('color2', ('XYZ', 2)),
    # 恒为 0xcdcdcd00（head/tailEnd 各 62/62）。
    ('spacer4', 'i'),
    ('unkn15', 'i'),
    ('size', 'f'),
    ('unkn17', 'i'),
    ('unkn18_0', 'B'),
    ('unkn18_1', 'B'),
    ('spacer5', 'h'),
]
_EPVCSLOT_SIZE = 36


def _unpack_epvcolorslot(data: bytes, off: int) -> Tuple[dict, int]:
    """Decode one EPVColorSlot from *data* at *off*; returns (dict, new_off)."""
    d, new_off = unpack(_EPVCSLOT_FIELDS, data, off)
    return d, new_off


def _pack_epvcolorslot(vals: dict) -> bytes:
    return pack(_EPVCSLOT_FIELDS, vals)


# ─────────────────────────────────────────────────────────────────────────────
# Core codec
# ─────────────────────────────────────────────────────────────────────────────

def unpack(schema: list, data: bytes, off: int = 0) -> Tuple[Dict[str, Any], int]:
    """
    Decode *schema* fields from *data* starting at *off*.
    Returns (values_dict, new_offset).
    """
    values: Dict[str, Any] = {}
    for name, spec in schema:
        if isinstance(spec, str):
            if spec in _SCALAR_SIZE:
                # single scalar
                size = _SCALAR_SIZE[spec]
                (val,) = struct.unpack_from('<' + spec, data, off)
                values[name] = val
                off += size
            elif spec == 'colour':
                # 4 ubytes: red green blue alpha
                vals = list(struct.unpack_from('<4B', data, off))
                values[name] = vals
                off += 4
            elif spec == 'EPVColorSlot':
                d, off = _unpack_epvcolorslot(data, off)
                values[name] = d
            else:
                raise ValueError(f'Unknown scalar spec {spec!r} for field {name!r}')
        elif isinstance(spec, tuple):
            tag = spec[0]
            if tag == 'XYZ':
                xyz_type = spec[1]
                vals, off = _unpack_xyz(xyz_type, data, off)
                values[name] = vals
            elif tag == 'XYZ[]':
                # ('XYZ[]', type_code, count)
                xyz_type, count = spec[1], spec[2]
                arr = []
                for _ in range(count):
                    vals, off = _unpack_xyz(xyz_type, data, off)
                    arr.append(vals)
                values[name] = arr
            elif tag == 'colour[]':
                count = spec[1]
                arr = []
                for _ in range(count):
                    vals = list(struct.unpack_from('<4B', data, off))
                    arr.append(vals)
                    off += 4
                values[name] = arr
            elif tag == 'EPVColorSlot[]':
                count = spec[1]
                arr = []
                for _ in range(count):
                    d, off = _unpack_epvcolorslot(data, off)
                    arr.append(d)
                values[name] = arr
            elif tag == 'path':
                # variable-length path: int32 length + that many bytes
                (path_len,) = struct.unpack_from('<i', data, off)
                off += 4
                values[name] = data[off:off + path_len]
                off += path_len
            elif tag in _SCALAR_SIZE or (len(tag) == 1 and tag in 'iIfFhHbBqQ'):
                # fixed array ('i', count) etc.
                scalar, count = spec
                size = _SCALAR_SIZE[scalar]
                vals = list(struct.unpack_from(f'<{count}{scalar}', data, off))
                values[name] = vals
                off += size * count
            else:
                raise ValueError(f'Unknown compound spec {spec!r} for field {name!r}')
        else:
            raise ValueError(f'Bad spec type {type(spec)} for field {name!r}')
    return values, off


def pack(schema: list, values: Dict[str, Any]) -> bytes:
    """
    Encode *values* according to *schema*; returns bytes.
    """
    parts: List[bytes] = []
    for name, spec in schema:
        val = values[name]
        if isinstance(spec, str):
            if spec in _SCALAR_SIZE:
                parts.append(struct.pack('<' + spec, val))
            elif spec == 'colour':
                parts.append(struct.pack('<4B', *val))
            elif spec == 'EPVColorSlot':
                parts.append(_pack_epvcolorslot(val))
            else:
                raise ValueError(f'Unknown scalar spec {spec!r} for field {name!r}')
        elif isinstance(spec, tuple):
            tag = spec[0]
            if tag == 'XYZ':
                parts.append(_pack_xyz(spec[1], val))
            elif tag == 'XYZ[]':
                xyz_type, count = spec[1], spec[2]
                for item in val:
                    parts.append(_pack_xyz(xyz_type, item))
            elif tag == 'colour[]':
                for item in val:
                    parts.append(struct.pack('<4B', *item))
            elif tag == 'EPVColorSlot[]':
                for item in val:
                    parts.append(_pack_epvcolorslot(item))
            elif tag == 'path':
                path_bytes = val
                parts.append(struct.pack('<i', len(path_bytes)))
                parts.append(path_bytes)
            elif tag in _SCALAR_SIZE or (len(tag) == 1 and tag in 'iIfFhHbBqQ'):
                scalar, count = spec
                parts.append(struct.pack(f'<{count}{scalar}', *val))
            else:
                raise ValueError(f'Unknown compound spec {spec!r} for field {name!r}')
        else:
            raise ValueError(f'Bad spec type {type(spec)} for field {name!r}')
    return b''.join(parts)


def _schema_size(schema: list) -> int:
    """Return total byte size of this schema (sum of all field sizes)."""
    total = 0
    for _name, spec in schema:
        if isinstance(spec, str):
            if spec in _SCALAR_SIZE:
                total += _SCALAR_SIZE[spec]
            elif spec == 'colour':
                total += 4
            elif spec == 'EPVColorSlot':
                total += _EPVCSLOT_SIZE
            else:
                raise ValueError(f'Cannot compute size for dynamic spec {spec!r}')
        elif isinstance(spec, tuple):
            tag = spec[0]
            if tag == 'XYZ':
                total += _xyz_size(spec[1])
            elif tag == 'XYZ[]':
                total += _xyz_size(spec[1]) * spec[2]
            elif tag == 'colour[]':
                total += 4 * spec[1]
            elif tag == 'EPVColorSlot[]':
                total += _EPVCSLOT_SIZE * spec[1]
            elif tag == 'path':
                raise ValueError('Cannot compute static size for variable-length path spec')
            else:
                # fixed array ('i', n) etc.
                scalar, count = spec
                total += _SCALAR_SIZE[scalar] * count
        else:
            raise ValueError(f'Bad spec type {type(spec)}')
    return total
