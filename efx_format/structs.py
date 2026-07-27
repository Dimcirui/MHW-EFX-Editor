"""
efx_format/structs.py — schema codec's assembly layer / external facade.

The actual encoding/decoding and schema definitions have been split into the efx_format/schema/ subpackage:
    codec         Core encode/decode unpack/pack/_schema_size (+ spec atomic description)
    fields_model  Typed Field object model
    enums         Shared enum / bit definitions
    attributes    Fixed-length typed Attribute schema
    custom_codecs Variable-length / dispatch custom block encode/decode
    
This module does three things and maintains the original import interface externally (`from .structs import ...` remains unchanged):
  1. Re-export all public names from the schema/ subpackage + hashes (unpack/pack/various *_SCHEMA/unpack_*/…);
  2. Assemble the dispatch tables ATTR_SCHEMA_MAP (hash → (schema, size)) and ATTR_CUSTOM_CODEC (hash → encode/decode functions);
  3. Fill in the hash for typed Attributes and register them into FIELD_REGISTRY / ATTR_REGISTRY.
"""

from __future__ import annotations
import struct
from typing import Any, Dict, List, Tuple

from .schema.fields_model import (
    Attribute, EnumDef, BitDef,
    Int, UInt, Short, UShort, Byte, SByte, Float, Int64, UInt64,
    Enum, EnumVec3, Bool, Bitmask, Raw, register,
)

from .schema.enums import (
    ENUM_SHAPE_TYPE3D, ENUM_SHAPE_TYPE2D, ENUM_COLLISION_PHYSICS, ENUM_PTLIFE_STATUS,
    ENUM_RAYCAST_DIR, ENUM_HOMING_TARGET, ENUM_HOMING_FORCEFIELD, ENUM_HOMING_VANISH,
    ENUM_RENDER_LAYER, ENUM_SHADER_CONTROL, ENUM_ROTATION_MODE,
    ENUM_TRACKING_POS, ENUM_TRACKING_ANGLE,
    BITS_ENABLE_VELOCITY, BITS_SPIN_AXIS, BITS_RANDOMFIX_TABLE,
    _AXIS_DIRECTION6, _ROT_ORDER6, _VELOCITY_TYPE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Primitive sizes
# ─────────────────────────────────────────────────────────────────────────────

from .schema.codec import (
    _SCALAR_SIZE, _XYZ_FMT, _unpack_xyz, _pack_xyz, _xyz_size,
    _EPVCSLOT_FIELDS, _EPVCSLOT_SIZE, _unpack_epvcolorslot, _pack_epvcolorslot,
    unpack, pack, _schema_size,
)


from .schema.attributes import *  # noqa: F401,F403


from .schema.custom_codecs import *  # noqa: F401,F403
from .schema.custom_codecs import _walk_layoutbank_block  # 下划线名，import * 不含，显式 re-export
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
    # fixed-length types (51 types)
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
    VELOCITY2D,
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
    FAKEPLANE,
    REPEATAREA,
    FAKEDOF,
    # variable-length and dispatch types (17 types)
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
    TONEMAPFILTER,
    TUBELIGHT,
    EMITTERSHAPEMESH,
    BILLBOARD2D,
    LAYOUT,
)

# ── typed field-object model: fill in hash and register (see schema/fields_model.py) ──
# Attribute is defined above this file, before the hashes import, so the hash is filled in here and registered into the registry.
VELOCITY3D_ATTR.hash = VELOCITY3D
register(VELOCITY3D_ATTR)

# custom-codec 变长块的固定段也注册进 FIELD_REGISTRY，解锁 label/控件/过滤（块本身仍走
# ATTR_CUSTOM_CODEC，在 ATTR_SCHEMA_MAP 里保持 '_custom' 哨兵；这里只登记固定字段的 typed
# 元数据）。TUBELIGHT 手写显式 Field，其余经 attr_from_legacy 降级；applicationRule/
# loopingMode 用 Bitmask+BitEnum 段建模。MATERIAL/PTBEHAVIOR 有专属编辑器，不并入。
for _catt, _chash in (
    (TUBELIGHT_ATTR,        TUBELIGHT),
    (RGBWATER_ATTR,         RGBWATER),
    (STRAINRIBBON_ATTR,     STRAINRIBBON),
    (TONEMAPFILTER_ATTR,    TONEMAPFILTER),
    (LIGHTNING_ATTR,        LIGHTNING),
    (RIBBONBLADE_ATTR,      RIBBONBLADE),
    (MESH_ATTR,             MESH),
    (RIBBON_ATTR,           RIBBON),
    (EMITTERSHAPEMESH_ATTR, EMITTERSHAPEMESH),
    (BILLBOARD3D_ATTR,      BILLBOARD3D),
    (PLANE_ATTR,            PLANE),
    (UVSEQUENCE_ATTR,       UVSEQUENCE),
    (BILLBOARD2D_ATTR,      BILLBOARD2D),
    (TURBULENCE_ATTR,       TURBULENCE),
    (LAYOUT_ATTR,           LAYOUT),
):
    _catt.hash = _chash
    register(_catt)

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
    GUIDE:              (GUIDE_SCHEMA,               112),
    PLEMISSIVE:         (PLEMISSIVE_SCHEMA,           76),
    PARENTEMISSIVE:     (PARENTEMISSIVE_SCHEMA,       72),
    PLSNOW:             (PLSNOW_SCHEMA,               84),
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
    EMITTERSHAPE2D:     (EMITTERSHAPE2D_SCHEMA,       36),
    VELOCITY2D:         (VELOCITY2D_SCHEMA,           72),
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
    FAKEPLANE:          (FAKEPLANE_SCHEMA,            60),
    REPEATAREA:         (REPEATAREA_SCHEMA,           52),
    FAKEDOF:            (FAKEDOF_SCHEMA,              32),
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
    TUBELIGHT:        ('_custom', None),
    EMITTERSHAPEMESH: ('_custom', None),
    BILLBOARD2D:      ('_custom', None),
    LAYOUT:           ('_custom', None),
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
    TUBELIGHT:        (unpack_tubelight,        pack_tubelight),
    EMITTERSHAPEMESH: (unpack_emittershapemesh, pack_emittershapemesh),
    BILLBOARD2D:      (unpack_billboard2d,      pack_billboard2d),
    LAYOUT:           (unpack_layout,           pack_layout),
}


# ─────────────────────────────────────────────────────────────────────────────
# Fill in the hash by looking up the schema list object identity from ATTR_SCHEMA_MAP,
# and register it into FIELD_REGISTRY/ATTR_REGISTRY for the Blender layer
# to look up enum/bool/bitmask/label metadata by (hash, field_name).
# ─────────────────────────────────────────────────────────────────────────────
_MIGRATED_ATTRS = [
    EXTERN_TRANSFORM3D_ATTR,
    PARENTOPTIONS_ATTR,
    EXTERN_SPAWN_ATTR,
    LIFE_ATTR,
    SHADERSETTINGS_ATTR,
    EXTERN_EMITTERSHAPE3D_ATTR,
    EXTERN_SCALEANIM_ATTR,
    FADEBYDEPTH_ATTR,
    EXTERN_RGBFIRE_ATTR,
    ROTATEANIM_ATTR,
    ALPHACORRECTION_ATTR,
    LUMINANCEBLEED_ATTR,
    REFRACTION_ATTR,
    NOISE_ATTR,
    GUIDE_ATTR,
    PLEMISSIVE_ATTR,
    PARENTEMISSIVE_ATTR,
    PLSNOW_ATTR,
    PTCOLLISION_ATTR,
    RANDOMFIX_ATTR,
    DUMMY_ATTR,
    EXTERNREFERENCE_ATTR,
    PTLIFE_ATTR,
    EMITTERBOUNDARY_ATTR,
    FADEBYANGLE_ATTR,
    MASTERONLY_ATTR,
    BLINK_ATTR,
    FADEBYEMITTERANGLE_ATTR,
    RAYCAST_ATTR,
    HOMING_ATTR,
    SCREENSPACECOLLISION_ATTR,
    SHOVEL_ATTR,
    UVCONTROL_ATTR,
    EMITTERSHAPE2D_ATTR,
    VELOCITY2D_ATTR,
    PATHCHAIN_ATTR,
    PTTRIGGER_ATTR,
    LINKPARTSVISIBLE_ATTR,
    SPAWNBYANGLE_ATTR,
    CHECKPUREATTRIBUTE_ATTR,
    SPAWNBYOCCLUSION_ATTR,
    FADEBYOCCLUSION_ATTR,
    PARENTMATERIAL_ATTR,
    TRANSFORM2D_ATTR,
    COLORCORRECTFILTER_ATTR,
    PARENTSNOW_ATTR,
    OTOMOSNOW_ATTR,
    FAKEPLANE_ATTR,
    REPEATAREA_ATTR,
    FAKEDOF_ATTR,
]
_schema_id_to_hash = {id(_sch): _h for _h, (_sch, _sz) in ATTR_SCHEMA_MAP.items() if isinstance(_sch, list)}
for _a in _MIGRATED_ATTRS:
    _h = _schema_id_to_hash.get(id(_a.schema))
    if _h is not None:
        _a.hash = _h
        register(_a)
