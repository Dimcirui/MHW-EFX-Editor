"""
efx_format/structs.py  –  Phase 1 field-level schema codec.

Design
------
A *schema* is a list of (name, spec) pairs.  The codec walks the schema in
order, reading/writing each field so that ``pack(unpack(data)) == data``.

Spec atoms
~~~~~~~~~~
Scalars (single Python struct format chars, little-endian):
    'i'  int32       'I'  uint32      (BT: int / long / uint / ulong)
    'f'  float32     (BT: float)
    'h'  int16       'H'  uint16      (BT: short / ushort)
    'b'  int8        'B'  uint8       (BT: byte / ubyte / char)
    'q'  int64       'Q'  uint64      (BT: int64 / uint64)

Fixed arrays:
    ('i', 3)   → 3 × int32 (stored as list of ints)
    ('B', 4)   → 4 × ubyte (stored as list)
    … any scalar letter can be paired with a count.

XYZ variants  (from EFX_Utils.bt, parameterised by type code):
    ('XYZ', 0) → 6 floats: fixed_x, random_x, fixed_y, random_y, fixed_z, random_z  (24 B)
    ('XYZ', 1) → 3 int32:  x, y, z                                                  (12 B)
    ('XYZ', 2) → 3 ubyte + 1 pad byte                                                ( 4 B)
    ('XYZ', 3) → 3 floats: x, y, z                                                  (12 B)

Packed colour  (EFX_Utils.bt  colour):
    'colour'   → 4 ubytes: red, green, blue, alpha                                   ( 4 B)
    (identical to ('B', 4) but semantically named)

EPVColorSlot  (EFX_Utils.bt  EPVColorSlot):
    'EPVColorSlot' → fixed 36-byte structure (see _unpack_epvcolorslot)

XYZ array:
    ('XYZ[]', type_code, count) → count consecutive XYZ structs

ColourArray:
    ('colour[]', count) → count consecutive colour structs (4 B each)

Variable-length path (NOT used in the priority set; included for future use):
    ('path', 'i') → int32 length then that many bytes; stored as bytes

All values are stored in the returned dict as plain Python scalars/lists/bytes.
XYZ(0) is stored as a 6-element list [fx, rx, fy, ry, fz, rz].
XYZ(1) / XYZ(3) are stored as a 3-element list.
XYZ(2) is stored as a 4-element list [x, y, z, pad].
EPVColorSlot is stored as a dict with the named subfields.
colour is stored as a 4-element list [r, g, b, a].

API
---
unpack(schema, data, offset=0) -> (dict, new_offset)
    Walk schema, decode fields from *data* starting at *offset*.
    Returns the populated dict and the offset just past the last byte read.

pack(schema, values) -> bytes
    Walk schema, encode each field from *values*, return concatenated bytes.

_schema_size(schema) -> int
    Return total byte size of the schema (must equal _known_attr_size - 4 for
    schemas that exclude the leading 4-byte type hash).
"""

from __future__ import annotations
import struct
from typing import Any, Dict, List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Primitive sizes
# ─────────────────────────────────────────────────────────────────────────────

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
#   long  EPVColorSlotHead     (4 B)
#   XYZ   color1(2)            (4 B)  ubyte x,y,z + pad
#   long  NULL2                (4 B)
#   XYZ   color2(2)            (4 B)  ubyte x,y,z + pad
#   int   spacer4              (4 B)
#   int   unkn15               (4 B)
#   float size                 (4 B)
#   int   unkn17               (4 B)
#   byte  unkn18[2]            (2 B)
#   short spacer5              (2 B)
# Total: 4+4+4+4+4+4+4+4+2+2 = 36 B
# ─────────────────────────────────────────────────────────────────────────────

_EPVCSLOT_FIELDS = [
    ('head', 'I'),
    ('color1', ('XYZ', 2)),
    ('null2', 'I'),
    ('color2', ('XYZ', 2)),
    ('spacer4', 'i'),
    ('unkn15', 'i'),
    ('size', 'f'),
    ('unkn17', 'i'),
    ('unkn18', ('B', 2)),
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


# ─────────────────────────────────────────────────────────────────────────────
# ColorParam (from EFX_Subtypes.bt – used in ExternRgbFire)
# 10 ints = 40 B
# ─────────────────────────────────────────────────────────────────────────────

_COLOR_PARAM_SCHEMA = [
    ('enable', 'i'),
    ('fadeIn', 'i'),
    ('fadeInJitter', 'i'),
    ('duration', 'i'),
    ('durationJitter', 'i'),
    ('fadeOut', 'i'),
    ('fadeOutJitter', 'i'),
    ('unkn7', 'i'),
    ('unkn8', 'i'),
    ('unkn9', 'i'),
]  # 40 B


def _unpack_color_param(data: bytes, off: int) -> Tuple[dict, int]:
    return unpack(_COLOR_PARAM_SCHEMA, data, off)


def _pack_color_param(vals: dict) -> bytes:
    return pack(_COLOR_PARAM_SCHEMA, vals)


# ─────────────────────────────────────────────────────────────────────────────
# ExternTransform3D schema  (228 B)
#
# BT (EFX_Subtypes.bt):
#   int     unkn0                                    4 B
#   XYZ     translate(0)   6 floats                 24 B
#   XYZ     rotate(0)      6 floats                 24 B
#   XYZ     resize(0)      6 floats                 24 B
#   int     unkn1                                    4 B
#   XYZ     Translation_Velocity(0)                 24 B
#   XYZ     Translation_Velocity_Modifier(0)        24 B
#   XYZ     Rotation_Velocity(0)                    24 B
#   XYZ     Rotation_Velocity_Modifier(0)           24 B
#   XYZ     Scale_Velocity(0)                       24 B
#   XYZ     Scale_Velocity_Modifier(0)              24 B
#   int     enableVelocityBitflag                    4 B
# Total: 4 + 24*3 + 4 + 24*6 + 4 = 4+72+4+144+4 = 228 B
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_TRANSFORM3D_SCHEMA = [
    ('unkn0', 'i'),
    ('translate', ('XYZ', 0)),
    ('rotate', ('XYZ', 0)),
    ('resize', ('XYZ', 0)),
    ('unkn1', 'i'),
    ('translation_velocity', ('XYZ', 0)),
    ('translation_velocity_modifier', ('XYZ', 0)),
    ('rotation_velocity', ('XYZ', 0)),
    ('rotation_velocity_modifier', ('XYZ', 0)),
    ('scale_velocity', ('XYZ', 0)),
    ('scale_velocity_modifier', ('XYZ', 0)),
    ('enableVelocityBitflag', 'i'),
]
assert _schema_size(EXTERN_TRANSFORM3D_SCHEMA) == 228, \
    f"EXTERN_TRANSFORM3D_SCHEMA size mismatch: {_schema_size(EXTERN_TRANSFORM3D_SCHEMA)}"

# Transform3D block data_bytes schema (excludes the 4-byte type hash already
# stripped by AttrBlock).  Total must equal 232-4 = 228 B.
TRANSFORM3D_SCHEMA = EXTERN_TRANSFORM3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# ParentOptions schema  (data_bytes = 60 B; full block = 64 B)
#
# BT (EFX_Subtypes.bt):
#   long    type                              4 B  ← in type_hash, not in data_bytes
#   int     unkn0                             4 B
#   XYZ     translation_tracking(1)          12 B  (int x,y,z)
#   XYZ     angle_tracking(1)                12 B
#   XYZ     scale_tracking(1)                12 B
#   int     spawnTrack                        4 B
#   int     unkn1                             4 B
#   int     spawnLock                         4 B
#   int     bleedPos                          4 B
#   int     bone_lim                          4 B
# data_bytes total: 4 + 36 + 4*5 = 4+36+20 = 60 B  ✓  (full block = 64 B)
# ─────────────────────────────────────────────────────────────────────────────

PARENTOPTIONS_SCHEMA = [
    ('unkn0', 'i'),
    ('translation_tracking', ('XYZ', 1)),
    ('angle_tracking', ('XYZ', 1)),
    ('scale_tracking', ('XYZ', 1)),
    ('spawnTrack', 'i'),
    ('unkn1', 'i'),
    ('spawnLock', 'i'),
    ('bleedPos', 'i'),
    ('bone_lim', 'i'),
]
assert _schema_size(PARENTOPTIONS_SCHEMA) == 60, \
    f"PARENTOPTIONS_SCHEMA size mismatch: {_schema_size(PARENTOPTIONS_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternSpawn schema  (72 B)
#
# BT (EFX_Subtypes.bt):
#   int  unkn0                               4 B
#   int  instancesSpawnedTotal               4 B
#   int  instancesSpawnedPerFrame            4 B
#   int  randomizedSpawnsPerFrame            4 B
#   int  frameDelayBetweenSpawns             4 B
#   int  randomizedDelay                     4 B
#   int  durationOfSpawnerLifespan           4 B
#   int  randomizedLifespan                  4 B
#   int  instanceCountUnknLimit              4 B
#   int  instanceCountUnknLimitJitter        4 B
#   int  occur                               4 B
#   int  occur2                              4 B
#   uint unkn10                              4 B
#   uint unkn11                              4 B
#   uint repeatAtribute                      4 B
#   uint unkn21                              4 B
#   uint unkn30                              4 B
#   uint unkn31                              4 B
# Total: 18 × 4 = 72 B
#
# Note: efxfile.py computes Spawn block = 4(type) + 4*18 = 76 B.
# data_bytes = 72 B ✓
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_SPAWN_SCHEMA = [
    ('unkn0', 'i'),
    ('instancesSpawnedTotal', 'i'),
    ('instancesSpawnedPerFrame', 'i'),
    ('randomizedSpawnsPerFrame', 'i'),
    ('frameDelayBetweenSpawns', 'i'),
    ('randomizedDelay', 'i'),
    ('durationOfSpawnerLifespan', 'i'),
    ('randomizedLifespan', 'i'),
    ('instanceCountUnknLimit', 'i'),
    ('instanceCountUnknLimitJitter', 'i'),
    ('occur', 'i'),
    ('occur2', 'i'),
    ('unkn10', 'I'),
    ('unkn11', 'I'),
    ('repeatAtribute', 'I'),
    ('unkn21', 'I'),
    ('unkn30', 'I'),
    ('unkn31', 'I'),
]
assert _schema_size(EXTERN_SPAWN_SCHEMA) == 72, \
    f"EXTERN_SPAWN_SCHEMA size mismatch: {_schema_size(EXTERN_SPAWN_SCHEMA)}"

# Spawn block data_bytes schema (excludes type hash)
SPAWN_SCHEMA = EXTERN_SPAWN_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# Life schema  (data_bytes = 48 B; full block = 52 B)
#
# BT (EFX_Subtypes.bt):
#   long type                                4 B  ← in type_hash
#   long unkn0                               4 B
#   long fadeInDuration                      4 B
#   long fadeInDurationJitter                4 B
#   long duration                            4 B
#   long durationJitter                      4 B
#   long unkn2[2]                            8 B
#   long fadeOutDuration                     4 B
#   long fadeOutDurationJitter               4 B
#   long timeToDeath                         4 B
#   long timeToDeathJitter                   4 B
#   long indefiniteLifespan                  4 B
# data_bytes: 12 × 4 = 48 B ✓
# ─────────────────────────────────────────────────────────────────────────────

LIFE_SCHEMA = [
    ('unkn0', 'i'),
    ('fadeInDuration', 'i'),
    ('fadeInDurationJitter', 'i'),
    ('duration', 'i'),
    ('durationJitter', 'i'),
    ('unkn2', ('i', 2)),
    ('fadeOutDuration', 'i'),
    ('fadeOutDurationJitter', 'i'),
    ('timeToDeath', 'i'),
    ('timeToDeathJitter', 'i'),
    ('indefiniteLifespan', 'i'),
]
assert _schema_size(LIFE_SCHEMA) == 48, \
    f"LIFE_SCHEMA size mismatch: {_schema_size(LIFE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ShaderSettings schema  (data_bytes = 116 B; full block = 120 B)
#
# BT (EFX_Subtypes.bt):
#   long type                                4 B  ← in type_hash
#   int  unkn0                               4 B
#   int  unkn1                               4 B
#   int  spacer                              4 B
#   int  unkn2                               4 B
#   float zDepthModifierStart                4 B
#   float zDepthModifierEnd                  4 B
#   int  unkn3_0                             4 B
#   int  unkn3_1                             4 B
#   int  controlBitflag                      4 B
#   float unkn4[16]                         64 B
#   byte  objectInteractionFlag0             1 B
#   byte  objectInteractionFlag1             1 B
#   byte  objectInteractionFlag2             1 B
#   byte  objectInteractionFlag3             1 B
#   int   visibleOnPreview                   4 B
#   int   unkn5[2]                           8 B
# data_bytes: 9×4 + 64 + 4 + 4 + 8 = 36 + 64 + 16 = 116 B ✓
# ─────────────────────────────────────────────────────────────────────────────

SHADERSETTINGS_SCHEMA = [
    ('unkn0', 'i'),
    ('unkn1', 'i'),
    ('spacer', 'i'),
    ('unkn2', 'i'),
    ('zDepthModifierStart', 'f'),
    ('zDepthModifierEnd', 'f'),
    ('unkn3_0', 'i'),
    ('unkn3_1', 'i'),
    ('controlBitflag', 'i'),
    ('unkn4', ('f', 16)),
    ('objectInteractionFlag0', 'B'),
    ('objectInteractionFlag1', 'B'),
    ('objectInteractionFlag2', 'B'),
    ('objectInteractionFlag3', 'B'),
    ('visibleOnPreview', 'i'),
    ('unkn5', ('i', 2)),
]
assert _schema_size(SHADERSETTINGS_SCHEMA) == 116, \
    f"SHADERSETTINGS_SCHEMA size mismatch: {_schema_size(SHADERSETTINGS_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternVelocity3D schema  (108 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0[3]                          12 B
#   float rotationX                          4 B
#   float rotationXJitter                    4 B
#   float rotationY                          4 B
#   float rotationYJitter                    4 B
#   float rotationZ                          4 B
#   float rotationZJitter                    4 B
#   float expansion_radius_limit             4 B
#   float expansion_radius_jitter            4 B
#   float expansion_radius_elasticity        4 B
#   float expansion_radius_elasticity_jitter 4 B
#   float velocityX                          4 B
#   float velocityY                          4 B
#   float velocityZ                          4 B
#   float energyOnAxisX                      4 B
#   float energyOnAxisY                      4 B
#   float energyOnAxisZ                      4 B
#   int   expansionType                      4 B
#   float gravity                            4 B
#   float gravity_jitter                     4 B
#   int   expansionDelay                     4 B
#   int   expansionDelayJitter               4 B
#   int   gravityDelay                       4 B
#   int   gravityDelayJitter                 4 B
#   long  NULL2                              4 B
# Total: 12 + 6×4 + 4×4 + 3×4 + 3×4 + 4 + 2×4 + 4×4 + 4 = 108 B
# Count: 3i + 18f + 1i + 2f + 4i + 1i = 12+72+4+8+16+4 = 116? Let me count carefully:
#   unkn0[3]=12, rot*6=24, exp_rad*4=16, vel*3=12, energy*3=12,
#   expansionType=4, grav+j=8, delays*4=16, NULL2=4
#   = 12+24+16+12+12+4+8+16+4 = 108 B ✓
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_VELOCITY3D_SCHEMA = [
    ('unkn0', ('i', 3)),
    ('rotationX', 'f'),
    ('rotationXJitter', 'f'),
    ('rotationY', 'f'),
    ('rotationYJitter', 'f'),
    ('rotationZ', 'f'),
    ('rotationZJitter', 'f'),
    ('expansion_radius_limit', 'f'),
    ('expansion_radius_jitter', 'f'),
    ('expansion_radius_elasticity', 'f'),
    ('expansion_radius_elasticity_jitter', 'f'),
    ('velocityX', 'f'),
    ('velocityY', 'f'),
    ('velocityZ', 'f'),
    ('energyOnAxisX', 'f'),
    ('energyOnAxisY', 'f'),
    ('energyOnAxisZ', 'f'),
    ('expansionType', 'i'),
    ('gravity', 'f'),
    ('gravity_jitter', 'f'),
    ('expansionDelay', 'i'),
    ('expansionDelayJitter', 'i'),
    ('gravityDelay', 'i'),
    ('gravityDelayJitter', 'i'),
    ('NULL2', 'i'),
]
assert _schema_size(EXTERN_VELOCITY3D_SCHEMA) == 108, \
    f"EXTERN_VELOCITY3D_SCHEMA size mismatch: {_schema_size(EXTERN_VELOCITY3D_SCHEMA)}"

# Velocity3D block data_bytes schema (excludes type hash)
VELOCITY3D_SCHEMA = EXTERN_VELOCITY3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# ExternEmitterShape3D schema  (88 B; full block = 92 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0                              4 B
#   XYZ   transform(0)   6 floats           24 B
#   int   patternControl                     4 B
#   int   unkn2                              4 B
#   float unkn3_f0                           4 B
#   float trayectoryRotationX               4 B
#   float trayectoryRotationY               4 B
#   float trayectoryRotationZ               4 B
#   int   unkn3_i0                           4 B
#   float spawnAngleLimits                  4 B
#   float unkn3_f1                          4 B
#   int   spawnPerCycle                      4 B
#   int   spawnTotal                         4 B
#   float radiusEnd                         4 B
#   float radiusOrigin                      4 B
#   float unknRadiusRelated                 4 B
#   int   unkn4                              4 B
# Total: 4+24+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 4+24+15×4 = 88 B ✓
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_EMITTERSHAPE3D_SCHEMA = [
    ('unkn0', 'i'),
    ('transform', ('XYZ', 0)),
    ('patternControl', 'i'),
    ('unkn2', 'i'),
    ('unkn3_f0', 'f'),
    ('trayectoryRotationX', 'f'),
    ('trayectoryRotationY', 'f'),
    ('trayectoryRotationZ', 'f'),
    ('unkn3_i0', 'i'),
    ('spawnAngleLimits', 'f'),
    ('unkn3_f1', 'f'),
    ('spawnPerCycle', 'i'),
    ('spawnTotal', 'i'),
    ('radiusEnd', 'f'),
    ('radiusOrigin', 'f'),
    ('unknRadiusRelated', 'f'),
    ('unkn4', 'i'),
]
assert _schema_size(EXTERN_EMITTERSHAPE3D_SCHEMA) == 88, \
    f"EXTERN_EMITTERSHAPE3D_SCHEMA size mismatch: {_schema_size(EXTERN_EMITTERSHAPE3D_SCHEMA)}"

# EmitterShape3D block data_bytes schema (excludes type hash)
EMITTERSHAPE3D_SCHEMA = EXTERN_EMITTERSHAPE3D_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# ExternScaleAnim schema  (76 B; full block = 80 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0                              4 B
#   float animationSpeed                     4 B
#   long  NULL                               4 B
#   float scaleSpeed                         4 B
#   float scaleSpeedJitter                   4 B
#   float unkn1[2]                           8 B
#   float scaleAccel                         4 B
#   float scaleAccelJitter                   4 B
#   float unkn2[8]                          32 B
#   int   delay                              4 B
#   int   delayJitter                        4 B
# Total: 4+4+4+4+4+8+4+4+32+4+4 = 76 B ✓
# ─────────────────────────────────────────────────────────────────────────────

# 社区实测（《世界特效注释解析》，验证版）：原模板对 SCALEANIM 误读很多，此为正确语义。
# 两阶段缩放：初始整体扩散（速度+加速度）+ 播放过程中的逐轴缩放（X/Y/Z 各 速度/加速度 + 偏差）。
# 字段宽度与原版完全一致（仅拆分 unkn1=('f',2)→X、unkn2=('f',8)→Y/Z，重命名，不改类型/字节）。
EXTERN_SCALEANIM_SCHEMA = [
    ('unkn0', 'i'),
    ('initialScaleSpeed', 'f'),        # 初始扩散速度（原 animationSpeed）
    ('NULL', 'i'),
    ('initialScaleAccel', 'f'),        # 初始扩散加速度（原 scaleSpeed）
    ('initialScaleAccelJitter', 'f'),  # 原 scaleSpeedJitter
    ('scaleSpeedX', 'f'),              # X 轴缩放速度（原 unkn1[0]）
    ('scaleSpeedXJitter', 'f'),        # 原 unkn1[1]
    ('scaleAccelX', 'f'),              # X 轴缩放加速度（原 scaleAccel）
    ('scaleAccelXJitter', 'f'),        # 原 scaleAccelJitter
    ('scaleSpeedY', 'f'),              # Y 轴缩放速度（原 unkn2[0]）
    ('scaleSpeedYJitter', 'f'),        # unkn2[1]
    ('scaleAccelY', 'f'),              # Y 轴缩放加速度 unkn2[2]
    ('scaleAccelYJitter', 'f'),        # unkn2[3]
    ('scaleSpeedZ', 'f'),              # Z 轴缩放速度 unkn2[4]（仅模型有 Z）
    ('scaleSpeedZJitter', 'f'),        # unkn2[5]
    ('scaleAccelZ', 'f'),              # Z 轴缩放加速度 unkn2[6]
    ('scaleAccelZJitter', 'f'),        # unkn2[7]
    ('animUpdateStart', 'i'),          # 动画更新开始时间（原 delay）
    ('animUpdateStartJitter', 'i'),    # 原 delayJitter
]
assert _schema_size(EXTERN_SCALEANIM_SCHEMA) == 76, \
    f"EXTERN_SCALEANIM_SCHEMA size mismatch: {_schema_size(EXTERN_SCALEANIM_SCHEMA)}"

SCALEANIM_SCHEMA = EXTERN_SCALEANIM_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# FadeByDepth schema  (data_bytes = 20 B; full block = 24 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   float viewAngleLimit                     4 B
#   float clipMin                            4 B
#   float fadeStart                          4 B
#   float clipMax                            4 B
# data_bytes: 4+4×4 = 20 B ✓
# ─────────────────────────────────────────────────────────────────────────────

FADEBYDEPTH_SCHEMA = [
    ('unkn0', 'i'),
    ('viewAngleLimit', 'f'),
    ('clipMin', 'f'),
    ('fadeStart', 'f'),
    ('clipMax', 'f'),
]
assert _schema_size(FADEBYDEPTH_SCHEMA) == 20, \
    f"FADEBYDEPTH_SCHEMA size mismatch: {_schema_size(FADEBYDEPTH_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternRgbFire schema  (112 B; full block = 116 B)
#
# BT (EFX_Subtypes.bt):
#   int   unkn0                              4 B
#   XYZ   color1(2)   ubyte×3+pad            4 B
#   float brightness1                        4 B
#   XYZ   color2(2)   ubyte×3+pad            4 B
#   float brightness2                        4 B
#   float unkn4                              4 B
#   float brightness3                        4 B
#   float brightness4                        4 B
#   ColorParam color1Param   10×int         40 B
#   ColorParam color2Param   10×int         40 B
# Total: 4+4+4+4+4+4+4+4+40+40 = 112 B ✓
#
# ColorParam decoded as flat named fields with prefix to avoid collision.
# ─────────────────────────────────────────────────────────────────────────────

EXTERN_RGBFIRE_SCHEMA = [
    ('unkn0', 'i'),
    ('color1', ('XYZ', 2)),
    ('brightness1', 'f'),
    ('color2', ('XYZ', 2)),
    ('brightness2', 'f'),
    ('unkn4', 'f'),
    ('brightness3', 'f'),
    ('brightness4', 'f'),
    # ColorParam color1Param (10 ints)
    ('color1Param_enable', 'i'),
    ('color1Param_fadeIn', 'i'),
    ('color1Param_fadeInJitter', 'i'),
    ('color1Param_duration', 'i'),
    ('color1Param_durationJitter', 'i'),
    ('color1Param_fadeOut', 'i'),
    ('color1Param_fadeOutJitter', 'i'),
    ('color1Param_unkn7', 'i'),
    ('color1Param_unkn8', 'i'),
    ('color1Param_unkn9', 'i'),
    # ColorParam color2Param (10 ints)
    ('color2Param_enable', 'i'),
    ('color2Param_fadeIn', 'i'),
    ('color2Param_fadeInJitter', 'i'),
    ('color2Param_duration', 'i'),
    ('color2Param_durationJitter', 'i'),
    ('color2Param_fadeOut', 'i'),
    ('color2Param_fadeOutJitter', 'i'),
    ('color2Param_unkn7', 'i'),
    ('color2Param_unkn8', 'i'),
    ('color2Param_unkn9', 'i'),
]
assert _schema_size(EXTERN_RGBFIRE_SCHEMA) == 112, \
    f"EXTERN_RGBFIRE_SCHEMA size mismatch: {_schema_size(EXTERN_RGBFIRE_SCHEMA)}"

RGBFIRE_SCHEMA = EXTERN_RGBFIRE_SCHEMA


# ─────────────────────────────────────────────────────────────────────────────
# RotateAnim schema  (data_bytes = 80 B; full block = 84 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0[2]                           8 B
#   long  NULL[2]                            8 B
#   XYZ   spin_velocity(0)   6 floats       24 B
#   float unkn1_0                            4 B
#   float unkn1_1                            4 B
#   float momentum_conservation              4 B
#   XYZ   spin_acceleration(0)              24 B
#   float unkn1_2                            4 B
# data_bytes: 8+8+24+12+24+4 = 80 B ✓
# ─────────────────────────────────────────────────────────────────────────────

ROTATEANIM_SCHEMA = [
    ('unkn0', ('i', 2)),
    # 社区实测：这两个专门控制 BILLBOARD3D 平面类的旋转，模板原标为 int，实为 float。
    ('billboardRotation', 'f'),
    ('billboardRotationSpeed', 'f'),
    ('spin_velocity', ('XYZ', 0)),
    ('unkn1_0', 'f'),
    ('unkn1_1', 'f'),
    ('momentum_conservation', 'f'),
    ('spin_acceleration', ('XYZ', 0)),
    ('unkn1_2', 'f'),
]
assert _schema_size(ROTATEANIM_SCHEMA) == 80, \
    f"ROTATEANIM_SCHEMA size mismatch: {_schema_size(ROTATEANIM_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# AlphaCorrection schema  (data_bytes = 20 B; full block = 24 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   float unkn1                              4 B
#   float transparentness                    4 B
#   long  NULL                               4 B
#   int   unkn2                              4 B
# data_bytes: 5×4 = 20 B ✓
# ─────────────────────────────────────────────────────────────────────────────

ALPHACORRECTION_SCHEMA = [
    ('unkn0', 'i'),
    ('unkn1', 'f'),
    ('transparentness', 'f'),
    ('NULL', 'i'),
    ('unkn2', 'i'),
]
assert _schema_size(ALPHACORRECTION_SCHEMA) == 20, \
    f"ALPHACORRECTION_SCHEMA size mismatch: {_schema_size(ALPHACORRECTION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# LuminanceBleed schema  (data_bytes = 16 B; full block = 20 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   long  unkn0                              4 B
#   float unkn1[3]                          12 B
# data_bytes: 4+12 = 16 B ✓
# ─────────────────────────────────────────────────────────────────────────────

LUMINANCEBLEED_SCHEMA = [
    ('unkn0', 'i'),
    ('unkn1', ('f', 3)),
]
assert _schema_size(LUMINANCEBLEED_SCHEMA) == 16, \
    f"LUMINANCEBLEED_SCHEMA size mismatch: {_schema_size(LUMINANCEBLEED_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Refraction schema  (data_bytes = 12 B; full block = 16 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   int   unkn0                              4 B
#   int   pixelNormalOffset                  4 B
#   int   unkn2                              4 B
# data_bytes: 3×4 = 12 B ✓
# ─────────────────────────────────────────────────────────────────────────────

REFRACTION_SCHEMA = [
    ('unkn0', 'i'),
    ('pixelNormalOffset', 'i'),
    ('unkn2', 'i'),
]
assert _schema_size(REFRACTION_SCHEMA) == 12, \
    f"REFRACTION_SCHEMA size mismatch: {_schema_size(REFRACTION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Noise schema  (data_bytes = 44 B; full block = 48 B)
#
# BT (EFX_Subtypes.bt):
#   long  type                               4 B  ← in type_hash
#   long  NULL                               4 B
#   int   section_length                     4 B
#   long  spacer                             4 B
#   float main_axis_speed                    4 B
#   float secondary_axis_speed              4 B
#   float teleport_radius                   4 B
#   float smooth_radius_randomized          4 B
#   float main_axis_speed2                  4 B
#   float secondary_axis_speed2             4 B
#   float teleport_radius2                  4 B
#   float smooth_radius_randomized2         4 B
# data_bytes: 4+4+4+8×4 = 44 B ✓
# ─────────────────────────────────────────────────────────────────────────────

NOISE_SCHEMA = [
    ('NULL', 'i'),
    ('section_length', 'i'),
    ('spacer', 'i'),
    ('main_axis_speed', 'f'),
    ('secondary_axis_speed', 'f'),
    ('teleport_radius', 'f'),
    ('smooth_radius_randomized', 'f'),
    ('main_axis_speed2', 'f'),
    ('secondary_axis_speed2', 'f'),
    ('teleport_radius2', 'f'),
    ('smooth_radius_randomized2', 'f'),
]
assert _schema_size(NOISE_SCHEMA) == 44, \
    f"NOISE_SCHEMA size mismatch: {_schema_size(NOISE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Guide schema  (data_bytes = 104 B; full block = 108 B)
#
# BT (EFX_Subtypes.bt):
#   float initialPosition/Jitter(8) + speed/Jitter(8) + accel/Jitter(8) +
#   innerRadius/Jitter(8) + outerRadius/Jitter(8) = 10 floats = 40 B
#   float restitutionDelay/Jitter(8) + restitutionEcc/Jitter(8) +
#   restitutionElasticity/Jitter(8) = 6 floats = 24 B
#   float unkn16-19 (4 floats = 16 B) + unkn20-22 (3 floats = 12 B)
#   int int_unkn1[2] (8 B) + float float_unkn2[3] (12 B)
# Total: 40+24+16+12+8+12 = 112 B?  But _known_attr_size returns 108-4=104.
# From efxfile.py: 4+40+16+16+12+8+12 = 108 full, so data_bytes = 104.
# Schema:
#   10 floats (initialPos/Jitter, speed/Jitter, accel/Jitter,
#              innerRadius/Jitter, outerRadius/Jitter) = 40 B
#   6 floats (restitutionDelay/Jitter, restitutionEcc/Jitter,
#             restitutionElasticity/Jitter) = 24 B
#   4 floats (unkn16-unkn19) = 16 B
#   3 floats (unkn20-unkn22) = 12 B
#   2 ints   (int_unkn1[2]) = 8 B
#   3 floats (float_unkn2[3]) = 12 B
# Total: 40+24+16+12+8+12 = 112 B  ← but expected is 104 B
# Actual: efxfile.py says 4 + 40 + 16 + 16 + 12 + 8 + 12 = 108 full = 104 data
# That's: 40 + 16 + 16 + 12 + 8 + 12 = 104 → only 6 restitution floats missing
# Counting BT fields: 23 floats + 2 ints + 3 floats = 26 floats + 2 ints = 112 B
# But efxfile computed 108. Let's trust the efxfile.py value:
#   10 floats = 40 B
#   4 floats = 16 B  (restitution: delay/j, ecc/j — only 4 not 6?)
# Actually from efxfile.py: 4+40+16+16+12+8+12 = 108:
#   type(4) + 10floats(40) + 4floats(16) + 4floats(16) + 3floats(12) + 2ints(8) + 3floats(12)
# = 4+40+16+16+12+8+12 = 108 full, 104 data_bytes
# ─────────────────────────────────────────────────────────────────────────────

GUIDE_SCHEMA = [
    ('initialPosition',           'f'),
    ('initialPositionJitter',      'f'),
    ('speed',                     'f'),
    ('speedJitter',                'f'),
    ('accel',                     'f'),
    ('accelJitter',                'f'),
    ('innerRadius',               'f'),
    ('innerRadiusJitter',          'f'),
    ('outerRadius',               'f'),
    ('outerRadiusJitter',          'f'),
    # efxfile.py: 4+40+40+12+8+12 = 116 full → data_bytes = 112
    # (EFX_Crimson.bt Guide: type + 23 floats + int[2] + float[3])
    # restitution 组共 10 floats（40B）
    ('restitutionDelay',          'f'),
    ('restitutionDelayJitter',     'f'),
    ('restitutionEccentricity',   'f'),
    ('restitutionEccentricityJitter', 'f'),
    ('restitutionElasticity',     'f'),
    ('restitutionElasticityJitter','f'),
    ('unkn16',                    'f'),
    ('unkn17',                    'f'),
    ('unkn18',                    'f'),
    ('unkn19',                    'f'),
    # unkn20/21/22 共 3 floats (12B)
    ('unkn20',                    'f'),
    ('unkn21',                    'f'),
    ('unkn22',                    'f'),
    # 2 ints (8B)
    ('int_unkn1',                 ('i', 2)),
    # 3 floats (12B)
    ('float_unkn2',               ('f', 3)),
]
assert _schema_size(GUIDE_SCHEMA) == 112, \
    f"GUIDE_SCHEMA size mismatch: {_schema_size(GUIDE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PlEmissive schema  (data_bytes = 76 B; full block = 80 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1(4) + ubyte body_p(1) + ubyte wp_p(1) + short NULL(2) +
#   int epv_color_slot(4) + XYZ color(2)(4) + float unkn4(4) + float area[2](8) +
#   float bright(4) + int area_of_aura(4) + float radii[3](12) + float unkn5[5](20)
# = 8+4+4+4+4+8+4+4+12+20 = 76 B ✓
# ─────────────────────────────────────────────────────────────────────────────

PLEMISSIVE_SCHEMA = [
    ('unkn0',            ('i', 2)),
    ('unkn1',            'f'),
    ('body_p',           'B'),
    ('wp_p',             'B'),
    ('NULL',             'h'),
    ('epv_color_slot',   'i'),
    ('color',            ('XYZ', 2)),
    ('unkn4',            'f'),
    ('area',             ('f', 2)),
    ('bright',           'f'),
    ('area_of_aura',     'i'),
    ('radii_effect_unkn0', 'f'),
    ('radii_effect_unkn1', 'f'),
    ('radii_effect_unkn2', 'f'),
    ('unkn5',            ('f', 5)),
]
assert _schema_size(PLEMISSIVE_SCHEMA) == 76, \
    f"PLEMISSIVE_SCHEMA size mismatch: {_schema_size(PLEMISSIVE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ParentEmissive schema  (data_bytes = 72 B; full block = 76 B)
#
# BT (EFX_Subtypes.bt):
#   long unkn0(4) + long unkn1(4) + float unkn2(4) + long unkn3(4) +
#   XYZ color(2)(4) + float brightness(4) + float rimParam[3](12) +
#   long unkn4(4) + float blendParam[3](12) + float unkn8[5](20)
# = 4+4+4+4+4+4+12+4+12+20 = 72 B ✓
# ─────────────────────────────────────────────────────────────────────────────

PARENTEMISSIVE_SCHEMA = [
    ('unkn0',       'i'),
    ('unkn1',       'i'),
    ('unkn2',       'f'),
    ('unkn3',       'i'),
    ('color',       ('XYZ', 2)),
    ('brightness',  'f'),
    ('rimParam',    ('f', 3)),
    ('unkn4',       'i'),
    ('blendParam',  ('f', 3)),
    ('unkn8',       ('f', 5)),
]
assert _schema_size(PARENTEMISSIVE_SCHEMA) == 72, \
    f"PARENTEMISSIVE_SCHEMA size mismatch: {_schema_size(PARENTEMISSIVE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PlSnow schema  (data_bytes = 80 B; full block = 84 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + long spacer(4) + int body_part_id(4) + int weapon_id(4) +
#   colour color(4) + int epvcolorslot(4) + int alpha_effect(4) +
#   float normal_map_strength(4) + float alpha_threshold(4) +
#   float unkn4_0(4) + float unkn4_1(4) + long unkn5(4) +
#   float roughness_multiplier(4) + float metallicness_multiplier(4) +
#   float subsurface_multipler(4) + float unkn6_0(4) +
#   float craquelure_effect_diffumination(4) + float craquelure_threshold(4) +
#   float unkn6_1(4) + float craquelure_smoothing_threshold(4)
# = 8+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 8+4+19*4 = 84 → minus 4 = 80 ✓
# Wait: 8+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 8 + 19*4 = 8+76 = 84? No:
# unkn0[2]=8, spacer=4, body_part_id=4, weapon_id=4, colour=4, epv=4, alpha=4,
# normal_map=4, alpha_thresh=4, unkn4_0=4, unkn4_1=4, unkn5=4,
# roughness=4, metallic=4, subsurface=4, unkn6_0=4, craquelure=4, craq_thresh=4,
# unkn6_1=4, craq_smooth=4
# = 8+4*19 = 8+76 = 84 full... but that means data_bytes = 80.
# Count: 2+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1 ints = 20 ints = 80B ✓
# ─────────────────────────────────────────────────────────────────────────────

PLSNOW_SCHEMA = [
    # BT has int unkn0[2](8B) + long spacer(4B) + 17 × 4B fields = 20 × 4B = 80 B data_bytes
    # Note: efxfile.py returns 4(type) + 20*4 = 84B full; data_bytes = 80B = 20 ints
    ('unkn0',                          ('i', 2)),   # int unkn0[2] = 8 B
    ('spacer',                         'i'),
    ('body_part_id',                   'i'),
    ('weapon_id',                      'i'),
    ('color',                          'colour'),
    ('epvcolorslot',                   'i'),
    ('alpha_effect',                   'i'),
    ('normal_map_strength',            'f'),
    ('alpha_threshold',                'f'),
    ('unkn4_0',                        'f'),
    ('unkn4_1',                        'f'),
    ('unkn5',                          'i'),
    ('roughness_multiplier',           'f'),
    ('metallicness_multiplier',        'f'),
    ('subsurface_multipler',           'f'),
    ('unkn6_0',                        'f'),
    ('craquelure_effect_diffumination','f'),
    ('craquelure_threshold',           'f'),
    ('unkn6_1',                        'f'),
]  # 8+4*18 = 8+72 = 80 B ✓
assert _schema_size(PLSNOW_SCHEMA) == 80, \
    f"PLSNOW_SCHEMA size mismatch: {_schema_size(PLSNOW_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PtCollision schema  (data_bytes = 112 B; full block = 116 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn00-07 (8 ints = 32 B) + float unkn1[3](12) + int unkn2[2](8) +
#   float bounceElasticity(4)+j(4)+Mult(4)+horizontal(4)+unkn34-37(16) +
#   int unkn38(4) + int unkn4[2](8) + int ieIndex(4) + int unkn6[3](12)
# = 32+12+8+32+4+8+4+12 = 112 B ✓
# ─────────────────────────────────────────────────────────────────────────────

PTCOLLISION_SCHEMA = [
    ('unkn00',                    'i'),
    ('physicsEnum',               'i'),
    ('unkn02',                    'i'),
    ('unkn03',                    'i'),
    ('unkn04',                    'i'),
    ('unkn05',                    'i'),
    ('unkn06',                    'f'),
    ('unkn07',                    'i'),
    ('unkn1',                     ('f', 3)),
    ('unkn2',                     ('i', 2)),
    ('bounceElasticity',          'f'),
    ('bounceElasticityJitter',    'f'),
    ('bounceElasticityMultiplier','f'),
    ('horizontalBounce',          'f'),
    ('unkn34',                    'f'),
    ('unkn35',                    'f'),
    ('unkn36',                    'f'),
    ('unkn37',                    'f'),
    ('unkn38',                    'i'),
    ('unkn4',                     ('i', 2)),
    ('ieIndex',                   'i'),
    ('unkn6',                     ('i', 3)),
]
assert _schema_size(PTCOLLISION_SCHEMA) == 112, \
    f"PTCOLLISION_SCHEMA size mismatch: {_schema_size(PTCOLLISION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# RandomFix schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[10]  (10 × 4 = 40 B)
# ─────────────────────────────────────────────────────────────────────────────

RANDOMFIX_SCHEMA = [
    ('unkn0', ('i', 10)),
]
assert _schema_size(RANDOMFIX_SCHEMA) == 40, \
    f"RANDOMFIX_SCHEMA size mismatch: {_schema_size(RANDOMFIX_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Dummy schema  (data_bytes = 9 B; full block = 13 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + byte unkn1(1) = 9 B
# ─────────────────────────────────────────────────────────────────────────────

DUMMY_SCHEMA = [
    ('unkn0', ('i', 2)),
    ('unkn1', 'B'),
]
assert _schema_size(DUMMY_SCHEMA) == 9, \
    f"DUMMY_SCHEMA size mismatch: {_schema_size(DUMMY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ExternReference schema  (data_bytes = 36 B; full block = 40 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0(4) + int referenceIndex(4) + int unkn1[7](28) = 36 B
# ─────────────────────────────────────────────────────────────────────────────

EXTERNREFERENCE_SCHEMA = [
    ('unkn0',           'i'),
    ('referenceIndex',  'i'),
    ('unkn1',           ('i', 7)),
]
assert _schema_size(EXTERNREFERENCE_SCHEMA) == 36, \
    f"EXTERNREFERENCE_SCHEMA size mismatch: {_schema_size(EXTERNREFERENCE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# PtLife schema  (data_bytes = 20 B; full block = 24 B)
#
# BT (EFX_Subtypes.bt):
#   short unkn0-9  (10 × 2 = 20 B)
# ─────────────────────────────────────────────────────────────────────────────

PTLIFE_SCHEMA = [
    ('unkn0',        'h'),
    ('unkn1',        'h'),
    ('timing',       'h'),
    ('unkn3',        'h'),
    ('relationIndex','h'),
    ('unkn5',        'h'),
    ('unkn6',        'h'),
    ('unkn7',        'h'),
    ('unkn8',        'h'),
    ('unkn9',        'h'),
]
assert _schema_size(PTLIFE_SCHEMA) == 20, \
    f"PTLIFE_SCHEMA size mismatch: {_schema_size(PTLIFE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# EmitterBoundary schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[8](32) = 40 B
# ─────────────────────────────────────────────────────────────────────────────

EMITTERBOUNDARY_SCHEMA = [
    ('unkn0', ('i', 2)),
    ('unkn1', ('f', 8)),
]
assert _schema_size(EMITTERBOUNDARY_SCHEMA) == 40, \
    f"EMITTERBOUNDARY_SCHEMA size mismatch: {_schema_size(EMITTERBOUNDARY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# FadeByAngle schema  (data_bytes = 40 B; full block = 44 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[4](16) + int64 NULL(8) + int unkn2[2](8) = 40 B
# ─────────────────────────────────────────────────────────────────────────────

FADEBYANGLE_SCHEMA = [
    ('unkn0', ('i', 2)),
    ('unkn1', ('f', 4)),
    ('NULL',  'q'),
    ('unkn2', ('i', 2)),
]
assert _schema_size(FADEBYANGLE_SCHEMA) == 40, \
    f"FADEBYANGLE_SCHEMA size mismatch: {_schema_size(FADEBYANGLE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# MasterOnly schema  (data_bytes = 4 B; full block = 8 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0(4) = 4 B
# ─────────────────────────────────────────────────────────────────────────────

MASTERONLY_SCHEMA = [
    ('unkn0', 'i'),
]
assert _schema_size(MASTERONLY_SCHEMA) == 4, \
    f"MASTERONLY_SCHEMA size mismatch: {_schema_size(MASTERONLY_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Blink schema  (data_bytes = 52 B; full block = 56 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + float unkn1[11](44) = 52 B
# ─────────────────────────────────────────────────────────────────────────────

BLINK_SCHEMA = [
    ('unkn0', ('i', 2)),
    ('unkn1', ('f', 11)),
]
assert _schema_size(BLINK_SCHEMA) == 52, \
    f"BLINK_SCHEMA size mismatch: {_schema_size(BLINK_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# FadeByEmitterAngle schema  (data_bytes = 28 B; full block = 32 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + long unkn(4) + float unkn2[4](16) = 28 B
# ─────────────────────────────────────────────────────────────────────────────

FADEBYEMITTERANGLE_SCHEMA = [
    ('unkn0', ('i', 2)),
    ('unkn',  'i'),
    ('unkn2', ('f', 4)),
]
assert _schema_size(FADEBYEMITTERANGLE_SCHEMA) == 28, \
    f"FADEBYEMITTERANGLE_SCHEMA size mismatch: {_schema_size(FADEBYEMITTERANGLE_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# RayCast schema  (data_bytes = 78 B; full block = 82 B)
#
# BT (EFX_Subtypes.bt):
#   int unknown(4) + int fixed70(4) + long spacer0(4) +
#   float distanceMod0/j(8) + float prop1/j(8) +
#   long spacer1/2/3(12) + float prop2(4) + XYZ prop3(3)(12) +
#   int direction(4) + float distanceMod1/j(8) +
#   long spacer(4) + int unknown1(4) + short unknown2(2)
# = 4+4+4+8+8+12+4+12+4+8+4+4+2 = 78 B ✓
# ─────────────────────────────────────────────────────────────────────────────

RAYCAST_SCHEMA = [
    ('unknown0',        'i'),
    ('fixed70',         'i'),
    ('spacer0',         'i'),
    ('distanceMod0',    'f'),
    ('distanceMod0Jitter','f'),
    ('prop1',           'f'),
    ('prop1Jitter',     'f'),
    ('spacer1',         'i'),
    ('spacer2',         'i'),
    ('spacer3',         'i'),
    ('prop2',           'f'),
    ('prop3',           ('XYZ', 3)),
    ('direction',       'i'),
    ('distanceMod1',    'f'),
    ('distanceMod1Jitter','f'),
    ('spacer',          'i'),
    ('unknown1',        'i'),
    ('unknown2',        'h'),
]
assert _schema_size(RAYCAST_SCHEMA) == 78, \
    f"RAYCAST_SCHEMA size mismatch: {_schema_size(RAYCAST_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Homing schema  (data_bytes = 52 B; full block = 56 B)
#
# BT (EFX_Subtypes.bt):
#   int unknown(4) + int unknown0(4) + long spacer(4) +
#   float f0(4) + float speed(4) + float speedMultiplier(4) +
#   float f3(4) + float f4(4) + float radius(4) +
#   long i0(4) + long i1(4) +
#   int enableRadialVanish(4) + int unknown1(4)
# = 4+4+4+4+4+4+4+4+4+4+4+4+4 = 52 B ✓
# Note: SPEC.md confirms HOMING = 56 B (with +12 offset often 0xCDCDCD00),
# matches efxfile.py: 4(type)+4+4+4+24+8+8 = 4+52 = 56 full.
# ─────────────────────────────────────────────────────────────────────────────

HOMING_SCHEMA = [
    ('unknown',              'i'),
    ('unknown0',             'i'),
    ('spacer',               'i'),
    ('f0',                   'f'),
    ('speed',                'f'),
    ('speedMultiplier',      'f'),
    ('f3',                   'f'),
    ('f4',                   'f'),
    ('radius',               'f'),
    ('i0',                   'i'),
    ('i1',                   'i'),
    ('enableRadialVanish',   'i'),
    ('unknown1',             'i'),
]
assert _schema_size(HOMING_SCHEMA) == 52, \
    f"HOMING_SCHEMA size mismatch: {_schema_size(HOMING_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ScreenSpaceCollision schema  (data_bytes = 36 B; full block = 40 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0[2](8) + long spacer(4) + float unkn1(4) + float bounce(4) +
#   float bounceJitter(4) + int lifespan(4) + int lifespanJitter(4) +
#   float bounceConditional(4) = 36 B ✓
# ─────────────────────────────────────────────────────────────────────────────

SCREENSPACECOLLISION_SCHEMA = [
    ('unkn0',             ('i', 2)),
    ('spacer',            'i'),
    ('unkn1',             'f'),
    ('bounce',            'f'),
    ('bounceJitter',      'f'),
    ('lifespan',          'i'),
    ('lifespanJitter',    'i'),
    ('bounceConditional', 'f'),
]
assert _schema_size(SCREENSPACECOLLISION_SCHEMA) == 36, \
    f"SCREENSPACECOLLISION_SCHEMA size mismatch: {_schema_size(SCREENSPACECOLLISION_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# Shovel schema  (data_bytes = 70 B; full block = 74 B)
#
# BT (EFX_Subtypes.bt):
#   long unkn00(4) + long unkn01(4) + long spacer(4) +
#   float width/j(8) + float height/j(8) + float length/j(8) +
#   long unkn09(4) + long unkn10(4) + float unkn11(4) +
#   long unkn12-14(12) + long pattern(4) + long unkn16(4) + short unkn17(2)
# = 4+4+4+8+8+8+4+4+4+12+4+4+2 = 70 B ✓
# ─────────────────────────────────────────────────────────────────────────────

SHOVEL_SCHEMA = [
    ('unkn00',  'i'),
    ('unkn01',  'i'),
    ('spacer',  'i'),
    ('width',   'f'),
    ('widthJitter', 'f'),
    ('height',  'f'),
    ('heightJitter','f'),
    ('length',  'f'),
    ('lengthJitter','f'),
    ('unkn09',  'i'),
    ('unkn10',  'i'),
    ('unkn11',  'f'),
    ('unkn12',  'i'),
    ('unkn13',  'i'),
    ('unkn14',  'i'),
    ('pattern', 'i'),
    ('unkn16',  'i'),
    ('unkn17',  'h'),
]
assert _schema_size(SHOVEL_SCHEMA) == 70, \
    f"SHOVEL_SCHEMA size mismatch: {_schema_size(SHOVEL_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# UVControl schema  (data_bytes = 236 B; full block = 240 B)
#
# BT (EFX_Subtypes.bt):
#   Material_Animation_Data uv1 (100 B) + Material_Animation_Data uv2 (100 B) +
#   int unkn2(4) + float[8] extra (32 B) = 236 B
#
# Material_Animation_Data (100 B):
#   int unkn0(4) + uv_transform[6](96) where uv_transform = float u/uJ/v/vJ (16 B)
#   = 4 + 6*16 = 100 B
# ─────────────────────────────────────────────────────────────────────────────

UVCONTROL_SCHEMA = [
    # uv1 Material_Animation_Data
    ('uv1_unkn0',               'i'),
    ('uv1_initialPosition',     ('f', 4)),
    ('uv1_speed',               ('f', 4)),
    ('uv1_acceleration',        ('f', 4)),
    ('uv1_scale',               ('f', 4)),
    ('uv1_scaleSpeed',          ('f', 4)),
    ('uv1_scaleAcceleration',   ('f', 4)),
    # uv2 Material_Animation_Data
    ('uv2_unkn0',               'i'),
    ('uv2_initialPosition',     ('f', 4)),
    ('uv2_speed',               ('f', 4)),
    ('uv2_acceleration',        ('f', 4)),
    ('uv2_scale',               ('f', 4)),
    ('uv2_scaleSpeed',          ('f', 4)),
    ('uv2_scaleAcceleration',   ('f', 4)),
    # extra fields
    ('unkn2',                          'i'),
    ('extraMaterialInitialPosition',   'f'),
    ('extraMaterialInitialPositionJ',  'f'),
    ('extraMaterialSpeed',             'f'),
    ('extraMaterialSpeedJitter',       'f'),
    ('opacity',                        'f'),
    ('opacityJitter',                  'f'),
    ('opacityAcceleration',            'f'),
    ('opacityAccelerationJitter',      'f'),
]
assert _schema_size(UVCONTROL_SCHEMA) == 236, \
    f"UVCONTROL_SCHEMA size mismatch: {_schema_size(UVCONTROL_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# EmitterShape2D schema  (data_bytes = 32 B; full block = 36 B)
#
# BT (EFX_Subtypes.bt):
#   int unkn0(4) + float offsetX/j(8) + float offsetY/j(8) +
#   int unkn20(4) + int spawnCount(4) + int unkn22[2](8) = 36 B? Let me recount:
#   unkn0(4)+offsetX(4)+offsetXJitter(4)+offsetY(4)+offsetYJitter(4)+
#   unkn20(4)+spawnCount(4)+unkn22(4)+unkn22(4)
#   = 4+4+4+4+4+4+4+4+4 = 36 B, but efxfile.py returns 4+4+16+12=36 full.
#   data_bytes = 36-4 = 32. But _schema_size gives: 4+16+12=32 → correct.
# ─────────────────────────────────────────────────────────────────────────────

EMITTERSHAPE2D_SCHEMA = [
    ('unkn0',       'i'),
    ('offsetX',     'f'),
    ('offsetXJitter','f'),
    ('offsetY',     'f'),
    ('offsetYJitter','f'),
    ('unkn20',      'i'),
    ('spawnCount',  'i'),
    ('unkn22_0',    'i'),
    ('unkn22_1',    'i'),
]
assert _schema_size(EMITTERSHAPE2D_SCHEMA) == 36, \
    f"EMITTERSHAPE2D_SCHEMA expected 32 or 36: {_schema_size(EMITTERSHAPE2D_SCHEMA)}"
# efxfile returns 4+4+16+12=36 full, so data_bytes=32; fix:
EMITTERSHAPE2D_SCHEMA = [
    ('unkn0',       'i'),
    ('offsetX',     'f'),
    ('offsetXJitter','f'),
    ('offsetY',     'f'),
    ('offsetYJitter','f'),
    ('unkn20',      'i'),
    ('spawnCount',  'i'),
    ('unkn22_0',    'i'),
]
assert _schema_size(EMITTERSHAPE2D_SCHEMA) == 32, \
    f"EMITTERSHAPE2D_SCHEMA size mismatch: {_schema_size(EMITTERSHAPE2D_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# 原 opaque 定长类型 schema（新增）
# 字段布局来源：EFX_Crimson.bt；字节数由 _known_attr_size 实测往返验证。
# 字段命名以 unknN 为主，语义待后续逆向补全。
# ─────────────────────────────────────────────────────────────────────────────

# PathChain (81B total, 77B data)
PATHCHAIN_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', 'f'),        # 4B
    ('unkn3', 'i'),        # 4B
    ('unkn4', ('f', 6)),   # 24B
    ('unkn5', ('i', 8)),   # 32B
    ('unkn6', 'b'),        # 1B
]
assert _schema_size(PATHCHAIN_SCHEMA) == 77, \
    f"PATHCHAIN_SCHEMA size mismatch: {_schema_size(PATHCHAIN_SCHEMA)}"

# PtTrigger (20B total, 16B data)
PTTRIGGER_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', 'i'),        # 4B
]
assert _schema_size(PTTRIGGER_SCHEMA) == 16, \
    f"PTTRIGGER_SCHEMA size mismatch: {_schema_size(PTTRIGGER_SCHEMA)}"

# LinkPartsVisible (16B total, 12B data)
LINKPARTSVISIBLE_SCHEMA = [
    ('unkn0', ('i', 3)),   # 12B
]
assert _schema_size(LINKPARTSVISIBLE_SCHEMA) == 12, \
    f"LINKPARTSVISIBLE_SCHEMA size mismatch: {_schema_size(LINKPARTSVISIBLE_SCHEMA)}"

# SpawnByAngle (26B total, 22B data)
SPAWNBYANGLE_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', 'f'),        # 4B
    ('unkn3', 'i'),        # 4B
    ('unkn4', 'h'),        # 2B
]
assert _schema_size(SPAWNBYANGLE_SCHEMA) == 22, \
    f"SPAWNBYANGLE_SCHEMA size mismatch: {_schema_size(SPAWNBYANGLE_SCHEMA)}"

# CheckPureAttribute (44B total, 40B data)
CHECKPUREATTRIBUTE_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', ('i', 7)),   # 28B
]
assert _schema_size(CHECKPUREATTRIBUTE_SCHEMA) == 40, \
    f"CHECKPUREATTRIBUTE_SCHEMA size mismatch: {_schema_size(CHECKPUREATTRIBUTE_SCHEMA)}"

# SpawnByOcclusion (24B total, 20B data)
SPAWNBYOCCLUSION_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', 'f'),        # 4B
    ('unkn3', 'i'),        # 4B
]
assert _schema_size(SPAWNBYOCCLUSION_SCHEMA) == 20, \
    f"SPAWNBYOCCLUSION_SCHEMA size mismatch: {_schema_size(SPAWNBYOCCLUSION_SCHEMA)}"

# FadeByOcclusion (28B total, 24B data)
FADEBYOCCLUSION_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', ('f', 3)),   # 12B
]
assert _schema_size(FADEBYOCCLUSION_SCHEMA) == 24, \
    f"FADEBYOCCLUSION_SCHEMA size mismatch: {_schema_size(FADEBYOCCLUSION_SCHEMA)}"

# ParentMaterial (16B total, 12B data)
PARENTMATERIAL_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'f'),        # 4B
]
assert _schema_size(PARENTMATERIAL_SCHEMA) == 12, \
    f"PARENTMATERIAL_SCHEMA size mismatch: {_schema_size(PARENTMATERIAL_SCHEMA)}"

# Transform2D (28B total, 24B data)
# BT: int64 unkn0[2](16B) + float unkn1[2](8B)
TRANSFORM2D_SCHEMA = [
    ('unkn0', ('q', 2)),   # 16B
    ('unkn1', ('f', 2)),   # 8B
]
assert _schema_size(TRANSFORM2D_SCHEMA) == 24, \
    f"TRANSFORM2D_SCHEMA size mismatch: {_schema_size(TRANSFORM2D_SCHEMA)}"

# ColorCorrectFilter (692B total, 688B data)
COLORCORRECTFILTER_SCHEMA = [
    ('unkn0', ('i', 4)),     # 16B
    ('unkn1', ('f', 168)),   # 672B
]
assert _schema_size(COLORCORRECTFILTER_SCHEMA) == 688, \
    f"COLORCORRECTFILTER_SCHEMA size mismatch: {_schema_size(COLORCORRECTFILTER_SCHEMA)}"

# ParentSnow (84B total, 80B data)
PARENTSNOW_SCHEMA = [
    ('unkn0', ('i', 2)),    # 8B
    ('unkn1', 'i'),         # 4B
    ('unkn2', 'i'),         # 4B
    ('color', ('XYZ', 2)),  # 4B
    ('unkn3', ('i', 2)),    # 8B
    ('unkn4', ('f', 13)),   # 52B
]
assert _schema_size(PARENTSNOW_SCHEMA) == 80, \
    f"PARENTSNOW_SCHEMA size mismatch: {_schema_size(PARENTSNOW_SCHEMA)}"

# OtomoSnow (88B total, 84B data)
# 注：Crimson BT 记载 84B，实测往返 88B（多一个 XYZ color 字段），以实测为准。
OTOMOSNOW_SCHEMA = [
    ('unkn0', ('i', 2)),    # 8B
    ('unkn1', 'i'),         # 4B
    ('unkn2', ('i', 2)),    # 8B
    ('color', ('XYZ', 2)),  # 4B
    ('unkn3', 'i'),         # 4B
    ('unkn4', 'i'),         # 4B
    ('unkn5', ('f', 4)),    # 16B
    ('unkn6', 'i'),         # 4B
    ('unkn7', ('f', 8)),    # 32B
]
assert _schema_size(OTOMOSNOW_SCHEMA) == 84, \
    f"OTOMOSNOW_SCHEMA size mismatch: {_schema_size(OTOMOSNOW_SCHEMA)}"


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# VARIABLE-LENGTH TYPES
#
# For variable-length blocks, we cannot use a static schema and _schema_size.
# Instead we provide custom unpack_<TYPE>/pack_<TYPE> functions plus
# a None-schema sentinel in ATTR_SCHEMA_MAP that routes to these functions
# via AttrBlock.decode/encode.
#
# The ATTR_SCHEMA_MAP entry for these types uses the sentinel:
#   HASH: ('_custom', None)
# and the custom functions are called by the extended decode/encode below.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# UVSequence (variable: fixed 44 B header + int path_len + path bytes)
#
# BT: unkn0(4)+uvs_index(4)+NULL(4)+startFrame(4)+startFrameJ(4)+
#     animSpeed(4)+animSpeedJ(4)+animAccel(4)+animAccelJ(4)+loopEnum(4)+path_len(4)
#     = 11 fields = 44 B, then path[path_len]
# data_bytes layout: [0..43] = fixed, [44] = path_len int, [48..] = path bytes
# ─────────────────────────────────────────────────────────────────────────────

_UVSEQUENCE_FIXED_SCHEMA = [
    ('unkn0',                   'i'),
    ('uvs_index',               'i'),
    ('NULL',                    'i'),
    ('startingFrame',           'i'),
    ('startingFrameJitter',     'i'),
    ('animationSpeed',          'f'),
    ('animationSpeedJitter',    'f'),
    ('animationAcceleration',   'f'),
    ('animationAccelerationJitter', 'f'),
    ('loopingEnum',             'i'),
]  # 10 fields = 40 B

_UVSEQUENCE_FIXED_SIZE = _schema_size(_UVSEQUENCE_FIXED_SCHEMA)  # = 40


def unpack_uvsequence(data: bytes, off: int = 0):
    """Unpack UVSequence data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_UVSEQUENCE_FIXED_SCHEMA, data, off)
    # path_len field (int) + path bytes
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_uvsequence(values: dict) -> bytes:
    """Pack UVSequence values dict back to bytes."""
    out = pack(_UVSEQUENCE_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Billboard3D (variable: billboard_data 108 B + extras 24 B + path)
#
# billboard_data (108 B, includes the path_len field at offset +104):
#   unkn0(4)+applicationRule(4)+XYZ color(2)[2](8)+brightness(4)+
#   unkn2[3](12)+EPVColorSlot1(4)+SlotOverride1(4)+unknDimension(4)+unknDimJ(4)+
#   scale(4)+scaleJ(4)+width(4)+widthJ(4)+height(4)+heightJ(4)+
#   flowmapSpeed(4)+flowmapSpeedJ(4)+flowmapAccel(4)+flowmapAccelJ(4)+
#   flowmapStrength(4)+flowmapStrengthJ(4)+flowmapStrAccel(4)+flowmapStrAccelJ(4)+
#   path_len(4) = 108 B total
# Extras (24 B): unkn5(4) + unkn6(uint64=8) + unkn7(4) + unkn8(4) + unkn9(4)
# Then: path[path_len]
#
# data_bytes: [0..107] = billboard_data (path_len at +104),
#             [108..131] = extras,
#             [132..131+path_len] = path
# ─────────────────────────────────────────────────────────────────────────────

_BILLBOARD3D_FIXED_SCHEMA = [
    ('unkn0',                      'i'),
    ('applicationRule',            'i'),
    ('color',                      ('XYZ[]', 2, 2)),
    ('brightness',                 'f'),
    # 社区实测：原模板 unkn2 = 3×int 有误。[0] 是随机亮度乘数（float）；
    # [2] 是混合模式开关（0=alpha 混合，1=add 混合）。拆成三个独立字段。
    ('randomBrightnessMult',       'f'),
    ('unkn2_1',                    'i'),
    ('blendMode',                  'i'),
    ('EPVColorSlot1',              'i'),
    ('SlotOverride1',              'i'),
    ('unknDimension',              'f'),
    ('unknDimensionJitter',        'f'),
    ('scale',                      'f'),
    ('scaleJitter',                'f'),
    ('width',                      'f'),
    ('widthJitter',                'f'),
    ('height',                     'f'),
    ('heightJitter',               'f'),
    ('flowmapSpeed',               'f'),
    ('flowmapSpeedJitter',         'f'),
    ('flowmapAcceleration',        'f'),
    ('flowmapAccelerationJitter',  'f'),
    ('flowmapStrength',            'f'),
    ('flowmapStrengthJitter',      'f'),
    ('flowmapStrengthAcceleration','f'),
    ('flowmapStrengthAccelerationJitter', 'f'),
    # path_len is next (part of billboard_data), then extras, then path
    # we handle path_len + extras + path manually below
]  # = 4+4+8+4+12+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 104 B

_BILLBOARD3D_EXTRAS_SCHEMA = [
    ('unkn5', 'i'),
    ('unkn6', 'Q'),  # uint64
    ('unkn7', 'f'),
    ('unkn8', 'i'),
    ('unkn9', 'i'),
]  # = 4+8+4+4+4 = 24 B


def unpack_billboard3d(data: bytes, off: int = 0):
    """Unpack Billboard3D data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_BILLBOARD3D_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    extras, off = unpack(_BILLBOARD3D_EXTRAS_SCHEMA, data, off)
    values.update(extras)
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_billboard3d(values: dict) -> bytes:
    """Pack Billboard3D values dict back to bytes."""
    out = pack(_BILLBOARD3D_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += pack(_BILLBOARD3D_EXTRAS_SCHEMA, values)
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Mesh (variable: Mod3Properties 174 B + BeginMod3 1 B + path1 (null-term) + path2 (null-term))
#
# data_bytes layout (includes BeginMod3 at +174, then null-terminated strings):
# [0..173] = Mod3Properties, [174] = BeginMod3 byte,
# [175..null1] = path1 (null-terminated, null at null1),
# [null1+1..null2] = path2 (null-terminated, null at null2)
#
# Mod3Properties (174 B) fields from BT (counted carefully):
#   int unkn0[2](8) + long CD1(4) + float emissive_saturation/j(8) +
#   float emissive_brightness/j(8) + XYZ rotation(0)(24) +
#   float unkn5_2/3(8) + XYZ scale(0)(24) + float global_scale/j(8) +
#   int starting/end_model_viscon(8) + colour*4(16) + int unkn7[3](12) +
#   int tracking_flags(4) + int unkn40(4) + int affectedByLight(4) +
#   int shadowCastBitflag(4) + int epv_color_slot1(4) + int unkn5(4) +
#   int epv_color_slot2(4) + int unkn6_1(4) + byte colorize1[4](4) +
#   byte colorize2[4](4) + int randommizeViscon(4) + short NULL1(2)
# = 8+4+8+8+24+8+24+8+8+16+12+4+4+4+4+4+4+4+4+4+4+4+2 = 174 B ✓
# ─────────────────────────────────────────────────────────────────────────────

_MOD3_PROPERTIES_SCHEMA = [
    ('unkn0',                   ('i', 2)),
    ('CD1',                     'i'),
    ('emissive_saturation',     'f'),
    ('emissive_saturation_j',   'f'),
    ('emissive_brightness',     'f'),
    ('emissive_brightness_j',   'f'),
    ('rotation',                ('XYZ', 0)),
    ('unkn5_2',                 'f'),
    ('unkn5_3',                 'f'),
    ('scale',                   ('XYZ', 0)),
    ('global_scale',            'f'),
    ('global_scale_jitter',     'f'),
    ('starting_model_viscon',   'i'),
    ('end_model_viscon',        'i'),
    ('color1',                  'colour'),
    ('color2',                  'colour'),
    ('color3',                  'colour'),
    ('color4',                  'colour'),
    ('unkn7',                   ('i', 3)),
    ('tracking_flags',          'i'),
    ('unkn40',                  'i'),
    ('affectedByLight',         'i'),
    ('shadowCastBitflag',       'i'),
    ('epv_color_slot1',         'i'),
    ('unkn5',                   'i'),
    ('epv_color_slot2',         'i'),
    ('unkn6_1',                 'i'),
    ('colorize_material1',      ('B', 4)),
    ('colorize_material2',      ('B', 4)),
    ('randommizeViscon',        'i'),
    ('NULL1',                   'h'),
]
assert _schema_size(_MOD3_PROPERTIES_SCHEMA) == 174, \
    f"_MOD3_PROPERTIES_SCHEMA size mismatch: {_schema_size(_MOD3_PROPERTIES_SCHEMA)}"


def unpack_mesh(data: bytes, off: int = 0):
    """Unpack Mesh data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_MOD3_PROPERTIES_SCHEMA, data, off)
    values['BeginMod3'] = data[off]
    off += 1
    # Null-terminated path1
    null1 = data.index(b'\x00', off)
    values['path1'] = data[off:null1]
    off = null1 + 1
    # Null-terminated path2
    null2 = data.index(b'\x00', off)
    values['path2'] = data[off:null2]
    off = null2 + 1
    return values, off


def pack_mesh(values: dict) -> bytes:
    """Pack Mesh values dict back to bytes."""
    out = pack(_MOD3_PROPERTIES_SCHEMA, values)
    out += bytes([values['BeginMod3']])
    out += values['path1'] + b'\x00'
    out += values['path2'] + b'\x00'
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Ribbon (variable: fixed 360 B + null-terminated path)
#
# From efxfile.py: Ribbon full = 364 + null-term path, data_bytes = full - 4 = 360 + path
# Structure breakdown (360 B fixed before path):
#   unkn0(4) + section_length(4) + spacer0(4) +
#   XYZ color(2)(4) + spacer1(4) + XYZ color2(2)(4) + spacer2(4) +
#   brightness(4) + unkn4[2](8) + scale(8) + width(8) + length(8) +
#   uv_map_height(4) + mat_tess_density(4) + mat_tess_j(4) + uv_map_width(4) +
#   horiz_physics(4) + vert_physics(4) + unkn15(4) +
#   restitution_dir(4) + unkn16[4](16) + startingAngle(4) + startingAngleJ(4) +
#   unkn16_0[2](8) + short unkn16_1(2) + short unkn16_2(2) + spacer3(4) +
#   unkn17(4) + spacer4(4) + lengthwise_offset(4) + unknown19_0(4) +
#   restitution(4) + restitutionJ(4) + inertial_excess(4) + inertialJ(4) +
#   springiness(4) + springinessJ(4) + spacer5(4) +
#   unkn20[4](16) + unkn21(4) + unkn22[3](12) + tailTiedToBone(4) + unkn23[8](32) +
#   unkn24(4) + epvcolor[2](8) + spacer7(4) +
#   base_width_mult(4) + base_opacity(4) + tip_width_mult(4) + tip_opacity(4) +
#   spacer8(4) + unkn27[2](8) + short visiblePreview(2) + short spacer9(2) +
#   base_flap_freq(8) + base_flap_amount(8) + tip_flap_freq(8) + tip_flap_amount(8) +
#   ib_junk[32](32)
# Total fixed: verify = 360 B
# ─────────────────────────────────────────────────────────────────────────────

_RIBBON_FIXED_SCHEMA = [
    ('unkn0',                    'i'),
    ('section_length',           'i'),
    ('spacer0',                  'i'),
    ('color',                    ('XYZ', 2)),
    ('spacer1',                  'i'),
    ('color2',                   ('XYZ', 2)),
    ('spacer2',                  'i'),
    ('brightness',               'f'),
    ('unkn4',                    ('i', 2)),
    ('scale',                    'f'),
    ('scale_jitter',             'f'),
    ('width',                    'f'),
    ('width_jitter',             'f'),
    ('length',                   'f'),
    ('length_jitter',            'f'),
    ('uv_map_height',            'i'),
    ('material_tesselation_density', 'f'),
    ('material_tesselation_jitter',  'f'),
    ('uv_map_width',             'f'),
    ('horizontal_physics_subdivision_count', 'i'),
    ('vertical_physics_subdivision_count',   'i'),
    ('unkn15',                   'f'),
    ('restitution_direction',    'i'),
    ('unkn16',                   ('i', 4)),
    ('startingAngle',            'i'),
    ('startingAngleJitter',      'i'),
    ('unkn16_0',                 ('i', 2)),
    ('unkn16_1',                 'h'),
    ('unkn16_2',                 'h'),
    ('spacer3',                  'i'),
    ('unkn17',                   'f'),
    ('spacer4',                  'i'),
    ('lengthwise_offset_relative_to_camera', 'f'),
    ('unknown19_0',              'f'),
    ('restitution',              'f'),
    ('restitution_jitter',       'f'),
    ('inertial_excess',          'f'),
    ('inertial_excess_jitter',   'f'),
    ('springiness',              'f'),
    ('springiness_jitter',       'f'),
    ('spacer5',                  'i'),
    ('unkn20',                   ('i', 4)),
    ('unkn21',                   'f'),
    ('unkn22',                   ('i', 3)),
    ('tailTiedToBone',           'i'),
    ('unkn23',                   ('f', 8)),
    ('unkn24',                   'i'),
    ('epvcolor',                 ('i', 2)),
    ('spacer7',                  'i'),
    ('base_width_multiplier',    'f'),
    ('base_opacity',             'f'),
    ('tip_width_multiplier',     'f'),
    ('tip_opacity',              'f'),
    ('spacer8',                  'i'),
    ('unkn27',                   ('f', 2)),
    ('visiblePreview',           'h'),
    ('spacer9',                  'h'),
    ('base_flap_frequency',      'f'),
    ('base_flap_frequency_jitter','f'),
    ('base_flap_amount',         'f'),
    ('base_flap_amount_jitter',  'f'),
    ('tip_flap_frequency',       'f'),
    ('tip_flap_frequency_jitter','f'),
    ('tip_flap_amount',          'f'),
    ('tip_flap_amount_jitter',   'f'),
    ('ib_junk',                  ('B', 32)),
]
assert _schema_size(_RIBBON_FIXED_SCHEMA) == 360, \
    f"_RIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBON_FIXED_SCHEMA)}"


def unpack_ribbon(data: bytes, off: int = 0):
    """Unpack Ribbon data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_RIBBON_FIXED_SCHEMA, data, off)
    null = data.index(b'\x00', off)
    values['path1'] = data[off:null]
    off = null + 1
    return values, off


def pack_ribbon(values: dict) -> bytes:
    """Pack Ribbon values dict back to bytes."""
    out = pack(_RIBBON_FIXED_SCHEMA, values)
    out += values['path1'] + b'\x00'
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Plane (variable: dds_data 108 B + extras 48 B + path)
#
# dds_data (108 B, same layout as billboard_data):
#   unkn0(4)+applicationRule(4)+XYZ color(2)[2](8)+brightness(4)+unkn20(4)+
#   EPVColorBlend(4)+unkn22(4)+EPVColorSlot1(4)+EPVColorSlot2(4)+
#   SlotOverride1(4)+SlotOverride2(4)+
#   scale/j(8)+width/j(8)+height/j(8)+
#   flowmapSpeed/j(8)+flowmapAccel/j(8)+flowmapStrength/j(8)+flowmapStrAccel/j(8)+
#   path_len(4) = 108 B (path_len at +104 within data_bytes)
# Extras (48 B): int unkn5[4](16) + XYZ rotation(0)(24) + uint64 unkn7(8)
# Then: path[path_len]
# ─────────────────────────────────────────────────────────────────────────────

_PLANE_DDS_SCHEMA = [
    ('unkn0',              'i'),
    ('applicationRule',    'i'),
    ('color',              ('XYZ[]', 2, 2)),
    ('brightness',         'f'),
    ('unkn20',             'i'),
    ('EPVColorBlend',      'i'),
    ('unkn22',             'i'),
    ('EPVColorSlot1',      'i'),
    ('EPVColorSlot2',      'i'),
    ('SlotOverride1',      'i'),
    ('SlotOverride2',      'i'),
    ('scale',              'f'),
    ('scaleJitter',        'f'),
    ('width',              'f'),
    ('widthJitter',        'f'),
    ('height',             'f'),
    ('heightJitter',       'f'),
    ('flowmapSpeed',       'f'),
    ('flowmapSpeedJitter', 'f'),
    ('flowmapAcceleration','f'),
    ('flowmapAccelerationJitter', 'f'),
    ('flowmapStrength',    'f'),
    ('flowmapStrengthJitter','f'),
    ('flowmapStrengthAcceleration','f'),
    ('flowmapStrengthAccelerationJitter','f'),
    # path_len handled separately
]  # = 4+4+8+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 104 B

_PLANE_EXTRAS_SCHEMA = [
    ('unkn5',   ('i', 4)),
    ('rotation',('XYZ', 0)),
    ('unkn7',   'Q'),
]  # = 16+24+8 = 48 B


def unpack_plane(data: bytes, off: int = 0):
    """Unpack Plane data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_PLANE_DDS_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    extras, off = unpack(_PLANE_EXTRAS_SCHEMA, data, off)
    values.update(extras)
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_plane(values: dict) -> bytes:
    """Pack Plane values dict back to bytes."""
    out = pack(_PLANE_DDS_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += pack(_PLANE_EXTRAS_SCHEMA, values)
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# RibbonBlade (variable: fixed 198 B header + path_len(int) + path)
#
# From efxfile.py: path_len at offset 198 from block start (= offset 194 in data_bytes)
# fixed structure before path_len (194 B in data_bytes):
#   unkn0[2](8)+spacer0(4)+unkn03(4)+unkn04(4)+unkn05[2](8)+spacer1(4)+unkn07[2](8)+
#   5 floats(20)+spacer2(4)+unkn10(4)+uvRep(4)+unkn12[3](12)+spacer3(4)+
#   EPVColorSlot head(36)+EPVColorSlot tailEnd(36)+
#   4*(float+long)(32)+short NULL9(2)
# = 8+4+4+4+8+4+8+20+4+4+4+12+4+36+36+32+2 = 198 B total data before path_len
# Then: path_len(4) + path[path_len]
# ─────────────────────────────────────────────────────────────────────────────

_RIBBONBLADE_FIXED_SCHEMA = [
    ('unkn0',       ('i', 2)),
    ('spacer0',     'i'),
    ('unkn03',      'i'),
    ('unkn04',      'i'),
    ('unkn05',      ('i', 2)),
    ('spacer1',     'i'),
    ('unkn07',      ('i', 2)),
    # 5 floats: maxLengthLimit, contractionSpeed, colourTransitionPoint, emissiveStrength, unkn08
    ('maxLengthLimit',          'f'),
    ('contractionSpeed',        'f'),
    ('colourTransitionPoint',   'f'),
    ('emissiveStrength',        'f'),
    ('unkn08',                  'f'),
    ('spacer2',     'i'),
    ('unkn10',      'i'),
    ('uvRepetition','f'),
    ('unkn12',      ('i', 3)),
    ('spacer3',     'i'),
    ('head',        'EPVColorSlot'),
    ('tailEnd',     'EPVColorSlot'),
    # 4*(float+long) = 4*(4+4) = 32 B
    ('unkn23',      'f'),
    ('NULL5',       'i'),
    ('unkn24',      'f'),
    ('NULL6',       'i'),
    ('unkn25',      'f'),
    ('NULL7',       'i'),
    ('unkn26',      'f'),
    ('NULL8',       'i'),
    ('NULL9',       'h'),
]
assert _schema_size(_RIBBONBLADE_FIXED_SCHEMA) == 194, \
    f"_RIBBONBLADE_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBONBLADE_FIXED_SCHEMA)}"


def unpack_ribbonblade(data: bytes, off: int = 0):
    """Unpack RibbonBlade data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_RIBBONBLADE_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_ribbonblade(values: dict) -> bytes:
    """Pack RibbonBlade values dict back to bytes."""
    out = pack(_RIBBONBLADE_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# StrainRibbon（拔刀链条，0x3F4DA1D6）—— 固定 340B（type 之后）+ 末尾 path
# 字段布局对照 EFX_Crimson.bt 的 StrainRibbon struct（社区注释验证）。
# color1/color2 是字节 RGBA 色（XYZ type 2）；color3 实为 endPointScatter /
# originReleaseFlag 两个开关 + 2 保留字节（模板误标成颜色），故拆成 4 个 byte。
# 含一片 MT Framework 物理参数（tension/gravity/inertia/displacement 等）——
# MHW 即 MT Framework 引擎，这些在 MHW 内有效；unkn/spacer 为保留/对齐字段。
# ─────────────────────────────────────────────────────────────────────────────
_STRAINRIBBON_FIXED_SCHEMA = [
    ('unkn00',                 ('i', 2)),   # 8
    ('spacer00',               'i'),
    ('color1',                 ('XYZ', 2)), # 链条起始段颜色 RGBA
    ('spacer01',               'i'),
    ('color2',                 ('XYZ', 2)), # 链条中间段颜色 RGBA
    ('spacer02',               'i'),
    ('emissionStrength',       'f'),
    ('emissionStrengthJitter', 'f'),        # unkn03_01
    ('spacer03',               'i'),
    ('startDirectionX',        'f'),        # unkn03_03
    ('startDirectionY',        'f'),        # unkn03_04
    ('startDirectionZ',        'f'),        # unkn03_05
    ('unkn03_06',              'f'),
    ('endPosition',            ('XYZ', 3)), # 末端骨骼 XYZ 偏移
    ('unkn03_10',              'f'),
    ('width',                  'f'),
    ('widthJitter',            'f'),
    ('length',                 'f'),
    ('lengthJitter',           'f'),
    ('startWidth',             'f'),
    ('startOpacity',           'f'),
    ('endWidth',               'f'),
    ('endOpacity',             'f'),
    ('subdivisionCount',       'i'),
    ('unkn04_01',              'i'),
    ('uvRepetition',           'i'),
    ('widthwiseUVScalingAlpha','f'),
    ('spacer04',               'i'),
    ('widthwiseUVScalingBML',  'f'),
    ('endPointScatter',        'B'),        # color3.x（终点扩散开关）
    ('originReleaseFlag',      'B'),        # color3.y（起点解锁标志）
    ('color3_z',               'B'),        # 保留（模板误标颜色）
    ('color3_w',               'B'),        # 保留
    ('unkn06',                 ('f', 8)),   # unkn06_00..07，32B
    ('unkn06_08_00',           'h'),
    ('unkn06_08_01',           'h'),
    ('lengthBreakpoint',       'f'),        # 以下一片为 MT Framework 物理参数（MHW 引擎）
    ('lengthBreakpointJitter', 'f'),
    ('breakpointLocation',     'f'),
    ('breakpointLocationJitter','f'),
    ('breakDelay',             'f'),
    ('breakDelayJitter',       'f'),
    ('tension',                'f'),
    ('tensionJitter',          'f'),
    ('unkn06_17',              'f'),
    ('unkn06_18',              'f'),
    ('gravityMultiplier',      'f'),
    ('gravityMultiplierJitter','f'),
    ('inertia',                'f'),
    ('inertiaJitter',          'f'),
    ('poseSnapping',           'f'),
    ('poseSnappingJitter',     'f'),
    ('endBoneID',              'i'),        # 链条末端绑定骨骼 ID（有效）
    ('positionalAberration_01','i'),
    ('positionalAberration_02','i'),
    ('colorModeFlag',          'i'),        # positionalAberration_03（有效：2=青色偏移,10+=消失）
    ('positionalAberration_04','i'),
    ('positionalAberration_05','i'),
    ('displacement',           ('XYZ', 0)), # MT 遗留，24B
    ('displacementToggle',     'i'),
    ('unkn09',                 ('f', 5)),   # 20B
    ('unkn10_00',              'i'),
    ('unkn10_01',              'f'),
    ('unkn10_02',              'f'),
    ('unkn11',                 'i'),
    ('unkn12_00',              'i'),
    ('unkn12_01',              'f'),
    ('unkn12_02',              'f'),
    ('unkn12_03',              'f'),
    ('unkn13',                 'i'),
]
assert _schema_size(_STRAINRIBBON_FIXED_SCHEMA) == 340, \
    f"_STRAINRIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_STRAINRIBBON_FIXED_SCHEMA)}"


def unpack_strainribbon(data: bytes, off: int = 0):
    """Unpack StrainRibbon data_bytes (variable-length, trailing path)."""
    values, off = unpack(_STRAINRIBBON_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_strainribbon(values: dict) -> bytes:
    """Pack StrainRibbon values dict back to bytes."""
    out = pack(_STRAINRIBBON_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Turbulence (variable: type(4) + unkn0(4) + path_len(4) + path + floats...)
#
# From efxfile.py: path_len at data_bytes offset 4; after path: 4+8+24*5+20 = 152 B more
# BT layout (from data_bytes offset 0):
#   unkn0(4) + path_len(4) + path[path_len] +
#   forceMultiplier(4) + unkn1[2](8) +
#   XYZ offsetPos(0)(24) + XYZ offsetPosVel(0)(24) +
#   XYZ offsetAngle(0)(24) + XYZ offsetAngleVel(0)(24) +
#   XYZ offsetScale(0)(24) + float unkn3[5](20)
# ─────────────────────────────────────────────────────────────────────────────

_TURBULENCE_AFTER_PATH_SCHEMA = [
    ('forceMultiplier', 'f'),
    ('unkn1',           ('f', 2)),
    ('offsetPos',       ('XYZ', 0)),
    ('offsetPosVel',    ('XYZ', 0)),
    ('offsetAngle',     ('XYZ', 0)),
    ('offsetAngleVel',  ('XYZ', 0)),
    ('offsetScale',     ('XYZ', 0)),
    ('unkn3',           ('f', 5)),
]  # = 4+8+24*5+20 = 4+8+120+20 = 152 B


def unpack_turbulence(data: bytes, off: int = 0):
    """Unpack Turbulence data_bytes (variable-length). Returns (dict, new_off)."""
    (unkn0,) = struct.unpack_from('<i', data, off)
    off += 4
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    path = data[off:off + path_len]
    off += path_len
    values = {'unkn0': unkn0, 'path_len': path_len, 'path': path}
    rest, off = unpack(_TURBULENCE_AFTER_PATH_SCHEMA, data, off)
    values.update(rest)
    return values, off


def pack_turbulence(values: dict) -> bytes:
    """Pack Turbulence values dict back to bytes."""
    out = struct.pack('<i', values['unkn0'])
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    out += pack(_TURBULENCE_AFTER_PATH_SCHEMA, values)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Lightning (variable: fixed 550 B in data_bytes + path_len(4) + path)
#
# data_bytes: [0..545] = fixed fields, [546] = int path_len, [550..] = path
# From efxfile.py: path_len at offset 550 from block start = offset 546 in data_bytes
#
# Lightning fixed structure (546 B in data_bytes):
# From BT: unkn00[2](8)+spacer0(4)+XYZ color1/2/emissive(2)(4 each = 12)+unkn02-04(12)+
#   spacer05_00(4)+unkn05_01(4)+sineWaveFreq/j(8)+alphaThreshold(4)+unkn05_05-07(12)+
#   outwardsExpansion/j(8)+unkn05_10(4)+unkn05_11-13(12)+spacer05_14(4)+
#   targetBoneID(4)+unkn05_16(4)+unkn05_17(4)+EPVColorSlot1/2(8)+unkn05_20-24(20)+
#   inflection groups (2x20=40)+glow/length/width(16)+startWidth group(16)+
#   unkn05_45-48(16)+unkn06[2](8)+unkn07_00-09(40)+unkn07_10-27(72)+
#   unkn08[2](8)+unkn09[20](80)+unkn10[4](16)+unkn11[2](8)+unkn12[2](8)+
#   unkn13[6](24)+unkn14[3](12)+unkn15[9](36)+short unkn16(2)
# Let me not enumerate field-by-field: just use fixed blob + path for safety
# since the block is correct from _known_attr_size already.
# Actually: we need byte-perfect unpack. Let me define the full fixed schema.
# ─────────────────────────────────────────────────────────────────────────────

_LIGHTNING_FIXED_SCHEMA = [
    # header: unkn00[2](8) + spacer0(4)
    ('unkn00',              ('i', 2)),
    ('spacer0',             'i'),
    # XYZ color1/2/emissive as (2) type = 4B each: 3*4=12B, then unkn02-04 = 3*4=12B
    ('color1',              ('XYZ', 2)),
    ('unkn02',              'i'),
    ('color2',              ('XYZ', 2)),
    ('unkn03',              'i'),
    ('emissive',            ('XYZ', 2)),
    ('unkn04',              'i'),
    # group05 block: spacer05_00+unkn05_01+sineFreq/j+alphaThreshold+05_05-07+
    #   outExp/j+05_10+05_11-13+spacer05_14+targetBone+05_16+05_17+EPV1/2+05_20-24
    # = 4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 25*4=100B
    ('spacer05_00',         'i'),
    ('unkn05_01',           'i'),
    ('sineWaveFreq',        'f'),
    ('sineWaveFreqJitter',  'f'),
    ('alphaThreshold',      'f'),
    ('unkn05_05',           'f'),
    ('unkn05_06',           'f'),
    ('unkn05_07',           'f'),
    ('outwardsExpansionSpeed',      'f'),
    ('outwardsExpansionSpeedJitter','f'),
    ('unkn05_10',           'f'),
    ('unkn05_11',           'i'),
    ('unkn05_12',           'i'),
    ('unkn05_13',           'i'),
    ('spacer05_14',         'i'),
    ('targetBoneID',        'i'),
    ('unkn05_16',           'i'),
    ('unkn05_17',           'f'),
    ('EPVColorSlot1',       'i'),
    ('EPVColorSlot2',       'i'),
    ('unkn05_20',           'i'),
    ('unkn05_21',           'i'),
    ('unkn05_22',           'i'),
    ('unkn05_23',           'f'),
    ('unkn05_24',           'f'),
    # inflection1 group: inflectionPointCount+uInfl/j+vInfl/j = 5*4=20B
    ('inflectionPointCount',          'i'),
    ('uInflectionAngleLimit',         'f'),
    ('uInflectionAngleLimitJitter',   'f'),
    ('vInflectionAngleLimit',         'f'),
    ('vInflectionAngleLimitJitter',   'f'),
    # inflection2 group: 5*4=20B
    ('inflectionPointCount2',         'i'),
    ('uInflectionAngleLimit2',        'f'),
    ('uInflectionAngleLimitJitter2',  'f'),
    ('vInflectionAngleLimit2',        'f'),
    ('vInflectionAngleLimitJitter2',  'f'),
    # glow/length/width group: glow/j + length/j = 4*4=16B
    ('glow',            'f'),
    ('glowJitter',      'f'),
    ('length',          'f'),
    ('lengthJitter',    'f'),
    # width group: width/j = 2*4=8B
    ('width',           'f'),
    ('widthJitter',     'f'),
    # startWidth group: startWidth+uvRepetitionStart+endWidth+uvRepetitionEnd = 4*4=16B
    ('startWidth',              'f'),
    ('uvRepetitionStart',       'f'),
    ('endWidth',                'f'),
    ('uvRepetitionEnd',         'f'),
    # unkn05_45-48: 4*4=16B
    ('unkn05_45',   'i'),
    ('unkn05_46',   'i'),
    ('unkn05_47',   'i'),
    ('unkn05_48',   'i'),
    # unkn06[2]: 2*4=8B
    ('unkn06',      ('i', 2)),
    # unkn07_00-09: 10*4=40B
    ('radiusLimit',         'f'),
    ('radiusLimitJitter',   'f'),
    ('unkn07_02',           'f'),
    ('unkn07_03',           'f'),
    ('unkn07_04',           'i'),
    ('unkn07_05',           'f'),
    ('unkn07_06',           'f'),
    ('unkn07_07',           'f'),
    ('unkn07_08',           'f'),
    ('unkn07_09',           'f'),
    # unkn07_10-27: 18*4=72B
    ('unkn07_10',   'f'),
    ('branchLength','f'),
    ('branchLengthJitter','f'),
    ('unkn07_13',   'f'),
    ('unkn07_14',   'f'),
    ('unkn07_15',   'f'),
    ('unkn07_16',   'f'),
    ('unkn07_17',   'f'),
    ('unkn07_18',   'f'),
    ('unkn07_19',   'f'),
    ('unkn07_20',   'f'),
    ('unkn07_21',   'f'),
    ('unkn07_22',   'f'),
    ('unkn07_23',   'f'),
    ('unkn07_24',   'f'),
    ('unkn07_25',   'f'),
    ('unkn07_26',   'f'),
    ('unkn07_27',   'f'),
    # unkn08[2]: 2*4=8B
    ('unkn08',      ('i', 2)),
    # unkn09[20]: 20*4=80B
    ('unkn09',      ('f', 20)),
    # unkn10[4]: 4*4=16B
    ('unkn10',      ('i', 4)),
    # unkn11[2]: 2*4=8B
    ('unkn11',      ('f', 2)),
    # unkn12[2]: 2*4=8B
    ('unkn12',      ('i', 2)),
    # unkn13[6]: 6*4=24B
    ('unkn13',      ('f', 6)),
    # unkn14[3]: 3*4=12B
    ('unkn14',      ('i', 3)),
    # unkn15[9]: 9*4=36B
    ('unkn15',      ('f', 9)),
    # short unkn16: 2B
    ('unkn16',      'h'),
]
assert _schema_size(_LIGHTNING_FIXED_SCHEMA) == 546, \
    f"_LIGHTNING_FIXED_SCHEMA size mismatch: {_schema_size(_LIGHTNING_FIXED_SCHEMA)}"


def unpack_lightning(data: bytes, off: int = 0):
    """Unpack Lightning data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_LIGHTNING_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_lightning(values: dict) -> bytes:
    """Pack Lightning values dict back to bytes."""
    out = pack(_LIGHTNING_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# RgbWater (variable: fixed 156 B + path_len(4) + path)
#
# From efxfile.py: path_len at offset 4+156 in block = offset 156 in data_bytes
# BT ExternRgbWater:
#   unkn0(4)+XYZ color(2)[2](8)+
#   brightnessSlot1(4)+emissiveMultiplier(4)+brightnessSlot2(4)+
#   brightnessSlotMult1(4)+brightnessSlotMult2(4)+opacity(4)+unknownFloat(4)+
#   unknownInt[3](12)+unkn2[26](104)+path_len(4)+path
# Fixed before path: 4+8+7*4+12+104 = 4+8+28+12+104 = 156 B
# ─────────────────────────────────────────────────────────────────────────────

_RGBWATER_FIXED_SCHEMA = [
    ('unkn0',                    'i'),
    ('color',                    ('XYZ[]', 2, 2)),
    ('brightnessSlot1',          'f'),
    ('emissiveMultiplier',       'f'),
    ('brightnessSlot2',          'f'),
    ('brightnessSlotMultiplier1','f'),
    ('brightnessSlotMultiplier2','f'),
    ('opacity',                  'f'),
    ('unknownFloat',             'f'),
    ('unknownInt',               ('i', 3)),
    ('unkn2',                    ('i', 26)),
]  # = 4+8+28+12+104 = 156 B
assert _schema_size(_RGBWATER_FIXED_SCHEMA) == 156, \
    f"_RGBWATER_FIXED_SCHEMA size mismatch: {_schema_size(_RGBWATER_FIXED_SCHEMA)}"


def unpack_rgbwater(data: bytes, off: int = 0):
    """Unpack RgbWater data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_RGBWATER_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_rgbwater(values: dict) -> bytes:
    """Pack RgbWater values dict back to bytes."""
    out = pack(_RGBWATER_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# DISPATCH TYPES: custom unpack/pack (not expressible as flat schemas)
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# PtBehavior (variable: EFX_Behavior with per-element dispatch)
#
# data_bytes layout:
#   unkn0(4) + behav_type_len(4) + para_count(4) +
#   char b_type[behav_type_len] +
#   EFX_Behav[para_count] (each: long unkn(4)+long const0(4)+int t(4)+data(t-dependent))
# ─────────────────────────────────────────────────────────────────────────────

def unpack_ptbehavior(data: bytes, off: int = 0):
    """Unpack PtBehavior data_bytes. Returns (dict, new_off)."""
    (unkn0,) = struct.unpack_from('<i', data, off); off += 4
    (behav_type_len,) = struct.unpack_from('<i', data, off); off += 4
    (para_count,) = struct.unpack_from('<i', data, off); off += 4
    b_type = data[off:off + behav_type_len]
    off += behav_type_len
    params = []
    for _ in range(para_count):
        (unkn,)  = struct.unpack_from('<i', data, off); off += 4
        (const0,)= struct.unpack_from('<i', data, off); off += 4
        (t,)     = struct.unpack_from('<i', data, off); off += 4
        param = {'unkn': unkn, 'const0': const0, 't': t}
        if t == 0x03:
            (v,) = struct.unpack_from('<i', data, off); off += 4
            param['NULL'] = v
        elif t == 0x05:
            (v,) = struct.unpack_from('<h', data, off); off += 2
            param['unkn0'] = v
        elif t == 0x06:
            (v,) = struct.unpack_from('<i', data, off); off += 4
            param['decal_epv_color_slot'] = v
        elif t == 0x0C:
            (v,) = struct.unpack_from('<f', data, off); off += 4
            param['unkn0'] = v
        elif t == 0x0F:
            vals = list(struct.unpack_from('<4B', data, off)); off += 4
            param['color'] = vals
        elif t == 0x14:
            vals = list(struct.unpack_from('<3f', data, off)); off += 12
            param['unkn1'] = vals
        elif t == 0x15:
            v0, = struct.unpack_from('<f', data, off); off += 4
            v1, = struct.unpack_from('<i', data, off); off += 4
            v2, = struct.unpack_from('<f', data, off); off += 4
            v3, = struct.unpack_from('<i', data, off); off += 4
            param['unkn0'] = v0
            param['unkn1'] = v1
            param['unkn2'] = v2
            param['unkn3'] = v3
        elif t in (0x36, 0x37):
            vals = list(struct.unpack_from('<2i', data, off)); off += 8
            param['unkn1'] = vals
        elif t == 0x40:
            (v,) = struct.unpack_from('<q', data, off); off += 8
            param['unkn0'] = v
        elif t == 0x80:
            (file_type,) = struct.unpack_from('<i', data, off); off += 4
            (path_len,)  = struct.unpack_from('<i', data, off); off += 4
            path = data[off:off + path_len]; off += path_len
            param['file_type'] = file_type
            param['path_len']  = path_len
            param['path']      = path
        else:
            (v,) = struct.unpack_from('<i', data, off); off += 4
            param['unkn_type'] = v
        params.append(param)
    return {'unkn0': unkn0, 'behav_type_len': behav_type_len,
            'para_count': para_count, 'b_type': b_type, 'params': params}, off


def pack_ptbehavior(values: dict) -> bytes:
    """Pack PtBehavior values dict back to bytes."""
    out = struct.pack('<i', values['unkn0'])
    b_type = values['b_type']
    out += struct.pack('<i', len(b_type))
    params = values['params']
    out += struct.pack('<i', len(params))
    out += b_type
    for param in params:
        t = param['t']
        out += struct.pack('<i', param['unkn'])
        out += struct.pack('<i', param['const0'])
        out += struct.pack('<i', t)
        if t == 0x03:
            out += struct.pack('<i', param['NULL'])
        elif t == 0x05:
            out += struct.pack('<h', param['unkn0'])
        elif t == 0x06:
            out += struct.pack('<i', param['decal_epv_color_slot'])
        elif t == 0x0C:
            out += struct.pack('<f', param['unkn0'])
        elif t == 0x0F:
            out += struct.pack('<4B', *param['color'])
        elif t == 0x14:
            out += struct.pack('<3f', *param['unkn1'])
        elif t == 0x15:
            out += struct.pack('<f', param['unkn0'])
            out += struct.pack('<i', param['unkn1'])
            out += struct.pack('<f', param['unkn2'])
            out += struct.pack('<i', param['unkn3'])
        elif t in (0x36, 0x37):
            out += struct.pack('<2i', *param['unkn1'])
        elif t == 0x40:
            out += struct.pack('<q', param['unkn0'])
        elif t == 0x80:
            path = param['path']
            out += struct.pack('<i', param['file_type'])
            out += struct.pack('<i', len(path))
            out += path
        else:
            out += struct.pack('<i', param['unkn_type'])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Material (variable: nested Tex_Block→Tex_Set dispatch)
#
# data_bytes layout:
#   int64 unkn00(8) + int block_count(4) +
#   block_count × Tex_Block:
#     long mat_name_hash(4) + long mat_shader(4) + long unkn03(4) + int set_count(4) +
#     set_count × Tex_Set:
#       long set(4) + int unkn0(4) + long t(4) + int type(4) +
#       type-dependent data:
#         0x80: long head(4)+long NULL(4)+int path_len(4)+char p[path_len]
#         0x06: int64 NULL(8)+int unkn(4)
#         0x03/0x0A/0x0C: long NULL[3](12)
#         0x15: float unkn[6](24)
#         else: long unkn_type(4)
# ─────────────────────────────────────────────────────────────────────────────

def unpack_material(data: bytes, off: int = 0):
    """Unpack Material data_bytes. Returns (dict, new_off)."""
    (unkn00,) = struct.unpack_from('<q', data, off); off += 8
    (block_count,) = struct.unpack_from('<i', data, off); off += 4
    blocks = []
    for _ in range(block_count):
        (mat_name_hash,) = struct.unpack_from('<i', data, off); off += 4
        (mat_shader,)    = struct.unpack_from('<i', data, off); off += 4
        (unkn03,)        = struct.unpack_from('<i', data, off); off += 4
        (set_count,)     = struct.unpack_from('<i', data, off); off += 4
        sets = []
        for _ in range(set_count):
            (set_val,) = struct.unpack_from('<i', data, off); off += 4
            (unkn0,)   = struct.unpack_from('<i', data, off); off += 4
            (t,)       = struct.unpack_from('<i', data, off); off += 4
            (type_,)   = struct.unpack_from('<i', data, off); off += 4
            tex = {'set': set_val, 'unkn0': unkn0, 't': t, 'type': type_}
            if type_ == 0x80:
                (head,) = struct.unpack_from('<i', data, off); off += 4
                (null,) = struct.unpack_from('<i', data, off); off += 4
                (path_len,) = struct.unpack_from('<i', data, off); off += 4
                path = data[off:off + path_len]; off += path_len
                tex['head'] = head
                tex['null'] = null
                tex['path_len'] = path_len
                tex['path'] = path
            elif type_ == 0x06:
                (null,) = struct.unpack_from('<q', data, off); off += 8
                (unkn,) = struct.unpack_from('<i', data, off); off += 4
                tex['null'] = null
                tex['unkn'] = unkn
            elif type_ in (0x03, 0x0A, 0x0C):
                vals = list(struct.unpack_from('<3i', data, off)); off += 12
                tex['NULL'] = vals
            elif type_ == 0x15:
                vals = list(struct.unpack_from('<6f', data, off)); off += 24
                tex['unkn'] = vals
            else:
                (v,) = struct.unpack_from('<i', data, off); off += 4
                tex['unkn_type'] = v
            sets.append(tex)
        blocks.append({'mat_name_hash': mat_name_hash, 'mat_shader': mat_shader,
                        'unkn03': unkn03, 'set_count': set_count, 'sets': sets})
    return {'unkn00': unkn00, 'block_count': block_count, 'blocks': blocks}, off


def pack_material(values: dict) -> bytes:
    """Pack Material values dict back to bytes."""
    out = struct.pack('<q', values['unkn00'])
    blocks = values['blocks']
    out += struct.pack('<i', len(blocks))
    for blk in blocks:
        out += struct.pack('<i', blk['mat_name_hash'])
        out += struct.pack('<i', blk['mat_shader'])
        out += struct.pack('<i', blk['unkn03'])
        sets = blk['sets']
        out += struct.pack('<i', len(sets))
        for tex in sets:
            out += struct.pack('<i', tex['set'])
            out += struct.pack('<i', tex['unkn0'])
            out += struct.pack('<i', tex['t'])
            type_ = tex['type']
            out += struct.pack('<i', type_)
            if type_ == 0x80:
                path = tex['path']
                out += struct.pack('<i', tex['head'])
                out += struct.pack('<i', tex['null'])
                out += struct.pack('<i', len(path))
                out += path
            elif type_ == 0x06:
                out += struct.pack('<q', tex['null'])
                out += struct.pack('<i', tex['unkn'])
            elif type_ in (0x03, 0x0A, 0x0C):
                out += struct.pack('<3i', *tex['NULL'])
            elif type_ == 0x15:
                out += struct.pack('<6f', *tex['unkn'])
            else:
                out += struct.pack('<i', tex['unkn_type'])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TonemapFilter (variable: fixed 24B data + int path_len + path bytes)
# BT: int unkn0[2](8B) + long unkn1(4B) + float unkn2[3](12B) + int path_len(4B) + char p[path_len]
# ─────────────────────────────────────────────────────────────────────────────

_TONEMAPFILTER_FIXED_SCHEMA = [
    ('unkn0', ('i', 2)),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unkn2', ('f', 3)),   # 12B
]  # 24B


def unpack_tonemapfilter(data: bytes, off: int = 0):
    values, off = unpack(_TONEMAPFILTER_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_tonemapfilter(values: dict) -> bytes:
    out = pack(_TONEMAPFILTER_FIXED_SCHEMA, values)
    path = values.get('path', b'')
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Custom-codec registry
#
# Maps type_hash → (unpack_fn, pack_fn)
# AttrBlock.decode/encode uses this when schema is '_custom'.
# ─────────────────────────────────────────────────────────────────────────────

ATTR_CUSTOM_CODEC: Dict[int, tuple] = {}  # populated after hash imports below


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table: attr type hash → (schema, expected_data_bytes_size)
# The expected size = full_block_size - 4 (type hash is already stripped).
#
# For variable/dispatch types, schema = '_custom' and expected_size = None;
# they are handled via ATTR_CUSTOM_CODEC.
# ─────────────────────────────────────────────────────────────────────────────

from .hashes import (
    TRANSFORM3D,
    PARENTOPTIONS,
    SPAWN,
    LIFE,
    SHADERSETTINGS,
    VELOCITY3D,
    EMITTERSHAPE3D,
    SCALEANIM,
    FADEBYDEPTH,
    RGBFIRE,
    ROTATEANIM,
    ALPHACORRECTION,
    LUMINANCEBLEED,
    REFRACTION,
    NOISE,
    # new fixed-size types
    GUIDE,
    PLEMISSIVE,
    PARENTEMISSIVE,
    PLSNOW,
    PTCOLLISION,
    RANDOMFIX,
    DUMMY,
    EXTERNREFERENCE,
    PTLIFE,
    EMITTERBOUNDARY,
    FADEBYANGLE,
    MASTERONLY,
    BLINK,
    FADEBYEMITTERANGLE,
    RAYCAST,
    HOMING,
    SCREENSPACECOLLISION,
    SHOVEL,
    UVCONTROL,
    EMITTERSHAPE2D,
    # 原 opaque 定长类型（新增 schema）
    PATHCHAIN,
    PTTRIGGER,
    LINKPARTSVISIBLE,
    SPAWNBYANGLE,
    CHECKPUREATTRIBUTE,
    SPAWNBYOCCLUSION,
    FADEBYOCCLUSION,
    PARENTMATERIAL,
    TRANSFORM2D,
    COLORCORRECTFILTER,
    PARENTSNOW,
    OTOMOSNOW,
    # 原 opaque 变长类型（新增 custom codec）
    TONEMAPFILTER,
    # variable-length and dispatch types
    UVSEQUENCE,
    BILLBOARD3D,
    MESH,
    RIBBON,
    PLANE,
    RIBBONBLADE,
    STRAINRIBBON,
    TURBULENCE,
    LIGHTNING,
    RGBWATER,
    PTBEHAVIOR,
    MATERIAL,
)

ATTR_SCHEMA_MAP: Dict[int, Tuple[list, int]] = {
    # ── Previously schema-ised (15 types) ─────────────────────────────────────
    TRANSFORM3D:    (TRANSFORM3D_SCHEMA,    228),
    PARENTOPTIONS:  (PARENTOPTIONS_SCHEMA,   60),
    SPAWN:          (SPAWN_SCHEMA,           72),
    LIFE:           (LIFE_SCHEMA,            48),
    SHADERSETTINGS: (SHADERSETTINGS_SCHEMA, 116),
    VELOCITY3D:     (VELOCITY3D_SCHEMA,     108),
    EMITTERSHAPE3D: (EMITTERSHAPE3D_SCHEMA,  88),
    SCALEANIM:      (SCALEANIM_SCHEMA,       76),
    FADEBYDEPTH:    (FADEBYDEPTH_SCHEMA,     20),
    RGBFIRE:        (RGBFIRE_SCHEMA,        112),
    ROTATEANIM:     (ROTATEANIM_SCHEMA,      80),
    ALPHACORRECTION:(ALPHACORRECTION_SCHEMA, 20),
    LUMINANCEBLEED: (LUMINANCEBLEED_SCHEMA,  16),
    REFRACTION:     (REFRACTION_SCHEMA,      12),
    NOISE:          (NOISE_SCHEMA,           44),
    # ── New fixed-size types (Phase 1 completion) ─────────────────────────────
    GUIDE:              (GUIDE_SCHEMA,              112),
    PLEMISSIVE:         (PLEMISSIVE_SCHEMA,           76),
    PARENTEMISSIVE:     (PARENTEMISSIVE_SCHEMA,       72),
    PLSNOW:             (PLSNOW_SCHEMA,               80),
    PTCOLLISION:        (PTCOLLISION_SCHEMA,         112),
    RANDOMFIX:          (RANDOMFIX_SCHEMA,            40),
    DUMMY:              (DUMMY_SCHEMA,                 9),
    EXTERNREFERENCE:    (EXTERNREFERENCE_SCHEMA,      36),
    PTLIFE:             (PTLIFE_SCHEMA,               20),
    EMITTERBOUNDARY:    (EMITTERBOUNDARY_SCHEMA,      40),
    FADEBYANGLE:        (FADEBYANGLE_SCHEMA,          40),
    MASTERONLY:         (MASTERONLY_SCHEMA,            4),
    BLINK:              (BLINK_SCHEMA,                52),
    FADEBYEMITTERANGLE: (FADEBYEMITTERANGLE_SCHEMA,   28),
    RAYCAST:            (RAYCAST_SCHEMA,              78),
    HOMING:             (HOMING_SCHEMA,               52),
    SCREENSPACECOLLISION:(SCREENSPACECOLLISION_SCHEMA,36),
    SHOVEL:             (SHOVEL_SCHEMA,               70),
    UVCONTROL:          (UVCONTROL_SCHEMA,           236),
    EMITTERSHAPE2D:     (EMITTERSHAPE2D_SCHEMA,       32),
    # ── 原 opaque 定长类型（新增）────────────────────────────────────────────
    PATHCHAIN:          (PATHCHAIN_SCHEMA,            77),
    PTTRIGGER:          (PTTRIGGER_SCHEMA,            16),
    LINKPARTSVISIBLE:   (LINKPARTSVISIBLE_SCHEMA,     12),
    SPAWNBYANGLE:       (SPAWNBYANGLE_SCHEMA,         22),
    CHECKPUREATTRIBUTE: (CHECKPUREATTRIBUTE_SCHEMA,   40),
    SPAWNBYOCCLUSION:   (SPAWNBYOCCLUSION_SCHEMA,     20),
    FADEBYOCCLUSION:    (FADEBYOCCLUSION_SCHEMA,      24),
    PARENTMATERIAL:     (PARENTMATERIAL_SCHEMA,       12),
    TRANSFORM2D:        (TRANSFORM2D_SCHEMA,          24),
    COLORCORRECTFILTER: (COLORCORRECTFILTER_SCHEMA,  688),
    PARENTSNOW:         (PARENTSNOW_SCHEMA,           80),
    OTOMOSNOW:          (OTOMOSNOW_SCHEMA,            84),
    # ── Variable/dispatch types: sentinel '_custom', size=None ────────────────
    # These are routed to ATTR_CUSTOM_CODEC by decode/encode on AttrBlock.
    UVSEQUENCE:  ('_custom', None),
    BILLBOARD3D: ('_custom', None),
    MESH:        ('_custom', None),
    RIBBON:      ('_custom', None),
    PLANE:       ('_custom', None),
    RIBBONBLADE: ('_custom', None),
    STRAINRIBBON:('_custom', None),
    TURBULENCE:  ('_custom', None),
    LIGHTNING:   ('_custom', None),
    RGBWATER:    ('_custom', None),
    PTBEHAVIOR:  ('_custom', None),
    MATERIAL:    ('_custom', None),
    TONEMAPFILTER:('_custom', None),
}

# Populate custom codec registry after the hash imports above
ATTR_CUSTOM_CODEC = {
    UVSEQUENCE:  (unpack_uvsequence,  pack_uvsequence),
    BILLBOARD3D: (unpack_billboard3d, pack_billboard3d),
    MESH:        (unpack_mesh,        pack_mesh),
    RIBBON:      (unpack_ribbon,      pack_ribbon),
    PLANE:       (unpack_plane,       pack_plane),
    RIBBONBLADE: (unpack_ribbonblade, pack_ribbonblade),
    STRAINRIBBON:(unpack_strainribbon,pack_strainribbon),
    TURBULENCE:  (unpack_turbulence,  pack_turbulence),
    LIGHTNING:   (unpack_lightning,   pack_lightning),
    RGBWATER:    (unpack_rgbwater,    pack_rgbwater),
    PTBEHAVIOR:   (unpack_ptbehavior,   pack_ptbehavior),
    MATERIAL:     (unpack_material,     pack_material),
    TONEMAPFILTER:(unpack_tonemapfilter,pack_tonemapfilter),
}


# ─────────────────────────────────────────────────────────────────────────────
# L1.1b：含路径 custom 类型的路径感知 extract / rebuild
#
# 设计原则：
#   - extract_paths(type_hash, data_bytes) → list[str]   （UTF-8 解码路径）
#   - rebuild_with_paths(type_hash, data_bytes, new_paths) → bytes
#     非路径字节逐字从原 data_bytes verbatim 拷贝，只更新 path_len 字段和路径段。
#     若 new_paths == original_paths，输出 == 原 data_bytes（identity）。
#   - 不调用整体 pack_* 函数，绝对不 re-pack 非路径部分。
#   - PTBEHAVIOR / MATERIAL 已在 L1.1c 加入（嵌套/变长分派，多路径按序重建）。
#
# 支持类型：
#   UVSEQUENCE   —— 末尾 length-prefixed path（path_len @ offset 40, path @ 44）
#   BILLBOARD3D  —— path_len 在结构中部（@ offset 104），extras 24B，path 在末尾
#   PLANE        —— 与 BILLBOARD3D 同模式（path_len @ 104）
#   RIBBONBLADE  —— path_len @ offset 194，path 在末尾
#   RGBWATER     —— path_len @ offset 156，path 在末尾
#   LIGHTNING    —— path_len @ offset 546，path 在末尾
#   MESH         —— Mod3Properties 174B + BeginMod3 1B + null-term path1 + null-term path2
#   RIBBON       —— 固定 360B header + null-term path（key='path1'）
#   TURBULENCE   —— path_len @ offset 4（data_bytes[4:8]），路径在固定前缀后 / 后续字节后
# ─────────────────────────────────────────────────────────────────────────────

def _path_bytes_to_str(b: bytes) -> str:
    """路径 bytes → UTF-8 字符串（宽容解码）。"""
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('latin-1')


def _str_to_path_bytes(s: str) -> bytes:
    """路径字符串 → bytes（UTF-8）。"""
    return s.encode('utf-8')


# ── 类型信息：各 custom 类型的路径位置描述 ───────────────────────────────────

# 对于 length-prefixed path，path_len 在 data_bytes 的固定 offset 处（int32 LE），
# path 紧跟其后；after_path_size 是 path 之后还有几个字节（用于验证 / 尾部拷贝）。
# BILLBOARD3D / PLANE：path_len @ 104，extras 24B 在 path 之前（即 [108..131]），
#   path 在末尾；这与 UVSEQUENCE / RIBBONBLADE 等不同。
# 具体见每个 rebuild_* 函数注释。

_PATH_TYPE_LAYOUT = {
    # type_hash: 'kind'
    # kind: 'length_prefix_tail'  (path_len + path 在块末尾)
    #       'length_prefix_mid'   (path_len 在中部，extras 在 path_len 之后，path 在末尾)
    #       'null_term_single'    (360B header + null-term path，key='path1')
    #       'null_term_double'    (174B Mod3 + 1B BeginMod3 + 2 null-term paths)
    #       'turbulence'          (path_len @ data[4:8]，后续字节在 path 后)
}


def extract_paths(type_hash: int, data_bytes: bytes) -> 'List[str]':
    """
    从 data_bytes 中提取该类型的路径字符串列表。

    参数
    ----
    type_hash  : int   — 块类型 hash
    data_bytes : bytes — AttrBlock.data_bytes（不含 type_hash 前缀）

    返回
    ----
    list[str] — 路径字符串（MESH 返回 2 个；MATERIAL/PTBEHAVIOR 返回 0~N 个；其余返回 1 个）

    异常
    ----
    ValueError — 若 type_hash 不在支持列表内，或 data_bytes 格式异常
    """
    # UVSEQUENCE: fixed 40B + path_len(4) + path
    if type_hash == UVSEQUENCE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 40)
        path_b = data_bytes[44:44 + path_len]
        return [_path_bytes_to_str(path_b)]

    # BILLBOARD3D: fixed 104B + path_len(4) + extras 24B + path[path_len]
    if type_hash == BILLBOARD3D:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_start = 104 + 4 + 24  # = 132
        path_b = data_bytes[path_start:path_start + path_len]
        return [_path_bytes_to_str(path_b)]

    # PLANE: fixed 104B + path_len(4) + extras 48B + path[path_len]
    if type_hash == PLANE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_start = 104 + 4 + 48  # = 156
        path_b = data_bytes[path_start:path_start + path_len]
        return [_path_bytes_to_str(path_b)]

    # RIBBONBLADE: fixed 194B + path_len(4) + path
    if type_hash == RIBBONBLADE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 194)
        path_b = data_bytes[198:198 + path_len]
        return [_path_bytes_to_str(path_b)]

    # STRAINRIBBON: fixed 340B + path_len(4) + path
    if type_hash == STRAINRIBBON:
        (path_len,) = struct.unpack_from('<i', data_bytes, 340)
        path_b = data_bytes[344:344 + path_len]
        return [_path_bytes_to_str(path_b)]

    # RGBWATER: fixed 156B + path_len(4) + path
    if type_hash == RGBWATER:
        (path_len,) = struct.unpack_from('<i', data_bytes, 156)
        path_b = data_bytes[160:160 + path_len]
        return [_path_bytes_to_str(path_b)]

    # LIGHTNING: fixed 546B + path_len(4) + path
    if type_hash == LIGHTNING:
        (path_len,) = struct.unpack_from('<i', data_bytes, 546)
        path_b = data_bytes[550:550 + path_len]
        return [_path_bytes_to_str(path_b)]

    # TURBULENCE: unkn0(4) + path_len(4) + path + after_path(152B)
    if type_hash == TURBULENCE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 4)
        path_b = data_bytes[8:8 + path_len]
        return [_path_bytes_to_str(path_b)]

    # RIBBON: fixed 360B + null-term path
    if type_hash == RIBBON:
        null = data_bytes.index(b'\x00', 360)
        path_b = data_bytes[360:null]
        return [_path_bytes_to_str(path_b)]

    # MESH: Mod3Properties 174B + BeginMod3 1B + null-term path1 + null-term path2
    if type_hash == MESH:
        off = 175  # skip 174B Mod3 + 1B BeginMod3
        null1 = data_bytes.index(b'\x00', off)
        path1_b = data_bytes[off:null1]
        off = null1 + 1
        null2 = data_bytes.index(b'\x00', off)
        path2_b = data_bytes[off:null2]
        return [_path_bytes_to_str(path1_b), _path_bytes_to_str(path2_b)]

    # ── L1.1c：MATERIAL ─────────────────────────────────────────────────────────
    # 结构：int64 unkn00(8) + int block_count(4) +
    #   block_count × Tex_Block:
    #     long mat_name_hash(4)+long mat_shader(4)+long unkn03(4)+int set_count(4)
    #     + set_count × Tex_Set:
    #         long set(4)+int unkn0(4)+long t(4)+int type(4)
    #         type==0x80: long head(4)+long NULL(4)+int path_len(4)+char p[path_len]
    #         …其余类型按固定宽度跳过（不含路径）
    # 遍历所有 type==0x80 的 Tex_Set，按出现顺序返回路径列表。
    if type_hash == MATERIAL:
        paths = []
        off = 0
        off += 8  # int64 unkn00
        (block_count,) = struct.unpack_from('<i', data_bytes, off); off += 4
        for _bi in range(block_count):
            off += 12  # mat_name_hash(4)+mat_shader(4)+unkn03(4)
            (set_count,) = struct.unpack_from('<i', data_bytes, off); off += 4
            for _si in range(set_count):
                off += 12  # set(4)+unkn0(4)+t(4)
                (type_,) = struct.unpack_from('<i', data_bytes, off); off += 4
                if type_ == 0x80:
                    off += 8  # head(4)+NULL(4)
                    (path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
                    path_b = data_bytes[off:off + path_len]; off += path_len
                    paths.append(_path_bytes_to_str(path_b))
                elif type_ == 0x06:
                    off += 12  # int64 NULL(8)+int unkn(4)
                elif type_ in (0x03, 0x0A, 0x0C):
                    off += 12  # long NULL[3]
                elif type_ == 0x15:
                    off += 24  # float unkn[6]
                else:
                    off += 4   # long unkn_type
        return paths

    # ── L1.1c：PTBEHAVIOR ───────────────────────────────────────────────────────
    # 结构：int unkn0(4)+int behav_type_len(4)+int para_count(4)+
    #   char b_type[behav_type_len] +
    #   para_count × EFX_Behav:
    #     long unkn(4)+long const0(4)+int t(4)+type-dependent data
    #     t==0x80: long file_type(4)+int path_len(4)+char p[path_len]
    # 遍历所有 t==0x80 的 EFX_Behav，按出现顺序返回路径列表。
    if type_hash == PTBEHAVIOR:
        paths = []
        off = 0
        off += 4  # unkn0
        (behav_type_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
        (para_count,) = struct.unpack_from('<i', data_bytes, off); off += 4
        off += behav_type_len  # b_type 字符串
        for _pi in range(para_count):
            off += 8  # unkn(4)+const0(4)
            (t,) = struct.unpack_from('<i', data_bytes, off); off += 4
            if t == 0x03:
                off += 4
            elif t == 0x05:
                off += 2
            elif t == 0x06:
                off += 4
            elif t == 0x0C:
                off += 4
            elif t == 0x0F:
                off += 4
            elif t == 0x14:
                off += 12
            elif t == 0x15:
                off += 16
            elif t in (0x36, 0x37):
                off += 8
            elif t == 0x40:
                off += 8
            elif t == 0x80:
                off += 4  # file_type
                (path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
                path_b = data_bytes[off:off + path_len]; off += path_len
                paths.append(_path_bytes_to_str(path_b))
            else:
                off += 4  # unkn_type
        return paths

    raise ValueError(f"extract_paths: 不支持的类型 hash 0x{type_hash:08X}")


def rebuild_with_paths(type_hash: int, data_bytes: bytes, new_paths: 'List[str]') -> bytes:
    """
    用 new_paths 替换路径段，非路径字节逐字从原 data_bytes verbatim 拷贝。

    原则：
      - 若 new_paths == original_paths，输出 == data_bytes（identity）
      - 只更新 path_len 字段（int32 LE）和路径字节段
      - 非路径字节全部来自 data_bytes（verbatim copy），绝不调用 pack_*

    参数
    ----
    type_hash  : int
    data_bytes : bytes — 原始 data_bytes
    new_paths  : list[str] — 新路径字符串

    返回
    ----
    bytes — 重建后的 data_bytes
    """
    # ── UVSEQUENCE ──
    if type_hash == UVSEQUENCE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        # [0..39] verbatim + new path_len + new path
        return (data_bytes[:40]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── BILLBOARD3D ──
    # 结构：[0..103]=fixed verbatim + path_len(4) + [108..131]=extras verbatim + path
    if type_hash == BILLBOARD3D:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        # verbatim [0..103], 新 path_len, verbatim extras [108..131], 新 path
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:132]
                + new_path_b)

    # ── PLANE ──
    # 结构：[0..103]=fixed verbatim + path_len(4) + [108..155]=extras verbatim + path
    if type_hash == PLANE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:156]
                + new_path_b)

    # ── RIBBONBLADE ──
    # 结构：[0..193] verbatim + path_len(4) + path
    if type_hash == RIBBONBLADE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:194]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── STRAINRIBBON ──
    # 结构：[0..339] verbatim + path_len(4) + path
    if type_hash == STRAINRIBBON:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:340]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── RGBWATER ──
    # 结构：[0..155] verbatim + path_len(4) + path
    if type_hash == RGBWATER:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:156]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── LIGHTNING ──
    # 结构：[0..545] verbatim + path_len(4) + path
    if type_hash == LIGHTNING:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:546]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── TURBULENCE ──
    # 结构：unkn0(4) verbatim + path_len(4) + new_path + after_path（原来 path 后到末尾）
    if type_hash == TURBULENCE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        (old_path_len,) = struct.unpack_from('<i', data_bytes, 4)
        old_path_end = 8 + old_path_len
        # verbatim unkn0[0:4], 新 path_len, 新 path, verbatim after_path[old_path_end:]
        return (data_bytes[:4]
                + struct.pack('<i', len(new_path_b))
                + new_path_b
                + data_bytes[old_path_end:])

    # ── RIBBON ──
    # 结构：[0..359] verbatim + new_path + \x00
    if type_hash == RIBBON:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return data_bytes[:360] + new_path_b + b'\x00'

    # ── MESH ──
    # 结构：[0..174] verbatim (174B Mod3 + 1B BeginMod3) + path1\x00 + path2\x00
    if type_hash == MESH:
        assert len(new_paths) == 2
        new_path1_b = _str_to_path_bytes(new_paths[0])
        new_path2_b = _str_to_path_bytes(new_paths[1])
        return (data_bytes[:175]
                + new_path1_b + b'\x00'
                + new_path2_b + b'\x00')

    # ── L1.1c：MATERIAL ─────────────────────────────────────────────────────────
    # 策略：遍历嵌套结构，逐字节拷贝所有非路径部分，对 type==0x80 的 Tex_Set
    # 用 new_paths[path_idx] 替换 path_len+path 段，其余字节 verbatim。
    # path_idx 按 type==0x80 出现顺序递增，对齐 extract_paths 的返回顺序。
    if type_hash == MATERIAL:
        parts = []
        off = 0
        path_idx = 0
        # verbatim: int64 unkn00(8) + int block_count(4)
        parts.append(data_bytes[off:off + 12]); off += 12
        (block_count,) = struct.unpack_from('<i', data_bytes, 0 + 8)
        for _bi in range(block_count):
            # verbatim: mat_name_hash(4)+mat_shader(4)+unkn03(4)+set_count(4)
            (set_count,) = struct.unpack_from('<i', data_bytes, off + 12)
            parts.append(data_bytes[off:off + 16]); off += 16
            for _si in range(set_count):
                # verbatim: set(4)+unkn0(4)+t(4)+type(4)
                (type_,) = struct.unpack_from('<i', data_bytes, off + 12)
                parts.append(data_bytes[off:off + 16]); off += 16
                if type_ == 0x80:
                    # verbatim: head(4)+NULL(4)
                    parts.append(data_bytes[off:off + 8]); off += 8
                    # 旧 path_len
                    (old_path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
                    # 新路径
                    new_path_b = _str_to_path_bytes(new_paths[path_idx])
                    path_idx += 1
                    parts.append(struct.pack('<i', len(new_path_b)))
                    parts.append(new_path_b)
                    # 跳过原始路径字节
                    off += old_path_len
                elif type_ == 0x06:
                    parts.append(data_bytes[off:off + 12]); off += 12
                elif type_ in (0x03, 0x0A, 0x0C):
                    parts.append(data_bytes[off:off + 12]); off += 12
                elif type_ == 0x15:
                    parts.append(data_bytes[off:off + 24]); off += 24
                else:
                    parts.append(data_bytes[off:off + 4]); off += 4
        return b''.join(parts)

    # ── L1.1c：PTBEHAVIOR ───────────────────────────────────────────────────────
    # 策略：遍历 EFX_Behav 列表，逐字节拷贝非路径部分，对 t==0x80 的参数
    # 用 new_paths[path_idx] 替换 file_type 后面的 path_len+path 段。
    # file_type(4) verbatim，只替换 path_len(4)+path[path_len]。
    if type_hash == PTBEHAVIOR:
        parts = []
        off = 0
        path_idx = 0
        # verbatim: unkn0(4)+behav_type_len(4)+para_count(4)
        (behav_type_len,) = struct.unpack_from('<i', data_bytes, 4)
        (para_count,) = struct.unpack_from('<i', data_bytes, 8)
        # verbatim: unkn0(4)+behav_type_len_field(4)+para_count_field(4)+b_type[behav_type_len]
        header_size = 12 + behav_type_len
        parts.append(data_bytes[off:off + header_size]); off += header_size
        for _pi in range(para_count):
            # verbatim: unkn(4)+const0(4)+t(4)
            (t,) = struct.unpack_from('<i', data_bytes, off + 8)
            parts.append(data_bytes[off:off + 12]); off += 12
            if t == 0x03:
                parts.append(data_bytes[off:off + 4]); off += 4
            elif t == 0x05:
                parts.append(data_bytes[off:off + 2]); off += 2
            elif t == 0x06:
                parts.append(data_bytes[off:off + 4]); off += 4
            elif t == 0x0C:
                parts.append(data_bytes[off:off + 4]); off += 4
            elif t == 0x0F:
                parts.append(data_bytes[off:off + 4]); off += 4
            elif t == 0x14:
                parts.append(data_bytes[off:off + 12]); off += 12
            elif t == 0x15:
                parts.append(data_bytes[off:off + 16]); off += 16
            elif t in (0x36, 0x37):
                parts.append(data_bytes[off:off + 8]); off += 8
            elif t == 0x40:
                parts.append(data_bytes[off:off + 8]); off += 8
            elif t == 0x80:
                # verbatim: file_type(4)
                parts.append(data_bytes[off:off + 4]); off += 4
                # 旧 path_len
                (old_path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
                # 新路径
                new_path_b = _str_to_path_bytes(new_paths[path_idx])
                path_idx += 1
                parts.append(struct.pack('<i', len(new_path_b)))
                parts.append(new_path_b)
                # 跳过原始路径字节
                off += old_path_len
            else:
                parts.append(data_bytes[off:off + 4]); off += 4
        return b''.join(parts)

    raise ValueError(f"rebuild_with_paths: 不支持的类型 hash 0x{type_hash:08X}")


# 支持路径编辑的 custom 类型集合（L1.1b：9 种；L1.1c 新增 MATERIAL + PTBEHAVIOR）
PATH_EDITABLE_CUSTOM_HASHES = frozenset({
    UVSEQUENCE,
    BILLBOARD3D,
    MESH,
    RIBBON,
    PLANE,
    RIBBONBLADE,
    STRAINRIBBON,
    TURBULENCE,
    LIGHTNING,
    RGBWATER,
    # L1.1c：嵌套/分派类型，含多个嵌入路径
    MATERIAL,
    PTBEHAVIOR,
})


# ─────────────────────────────────────────────────────────────────────────────
# Phase A：custom 块固定字段展开编辑
#
# 9 个 custom-codec 类型的"可编辑标量字段 schema" —— 即各 unpack_* 用到的 fixed
# 子 schema（排除 path / path_len / path1 / path2 等路径条目；路径由 codec 单独
# 处理）。字段名与 decode() 返回 dict 的键完全一致，使得 dict_to_items 能取值、
# rebuild_custom_field_block 能按名覆盖。
#
# rebuild 策略：decode → 覆盖被编辑标量字段 → 覆盖被编辑路径 → pack。未编辑字段
# 由 decode 原值经 pack 精确还原（NaN / 精度 / 哨兵全免疫），因 field_roundtrip
# 已证 pack(unpack(data)) == data 位精确。
#
# 注意：MATERIAL / PTBEHAVIOR 是嵌套分派结构，不在此表（Phase B 另做）。
# 拼接顺序仅影响 UI 显示顺序，不影响正确性（rebuild 按字段名覆盖，pack 按 dict 布局）。
# ─────────────────────────────────────────────────────────────────────────────

CUSTOM_FIELD_SCHEMA_MAP: Dict[int, list] = {
    RIBBON:      _RIBBON_FIXED_SCHEMA,
    UVSEQUENCE:  _UVSEQUENCE_FIXED_SCHEMA,
    # MESH：174B Mod3Properties + 1B BeginMod3（unpack_mesh 单独读 BeginMod3，
    # 故拼上 ('BeginMod3','B') 使其也可编辑）；path1/path2 由 codec 处理，不在 schema。
    MESH:        _MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')],
    RIBBONBLADE: _RIBBONBLADE_FIXED_SCHEMA,
    STRAINRIBBON:_STRAINRIBBON_FIXED_SCHEMA,
    LIGHTNING:   _LIGHTNING_FIXED_SCHEMA,
    RGBWATER:    _RGBWATER_FIXED_SCHEMA,
    TURBULENCE:  [('unkn0', 'i')] + _TURBULENCE_AFTER_PATH_SCHEMA,
    BILLBOARD3D: [e for e in (_BILLBOARD3D_FIXED_SCHEMA + _BILLBOARD3D_EXTRAS_SCHEMA)
                  if e[0] not in ('path', 'path_len')],
    PLANE:       [e for e in (_PLANE_DDS_SCHEMA + _PLANE_EXTRAS_SCHEMA)
                  if e[0] not in ('path', 'path_len')],
}


def custom_field_schema(type_hash: int):
    """返回该 custom 类型的可编辑标量字段 schema；不在表内返回 None。"""
    return CUSTOM_FIELD_SCHEMA_MAP.get(type_hash)
