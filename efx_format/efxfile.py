"""
EFXFile: faithful roundtrip parser for MHW .efx effect files (serialize(parse(x)) == x).

Known structures are fully parsed; anything uncertain is stored as raw bytes and
written back verbatim (opaque fallback) — both satisfy exact byte roundtrip.

File layout (parse order):
  - Header (72 B) → fully parsed
  - EFX_Type (labelSize B) → kept as raw bytes + label list
  - Play (countPlay entries) → parsed per BT (with opaque fallback)
  - Extern (countExtern entries) → parsed header, Extern_Data kept opaque
  - Main (countBody entries) → each body:
      - Root (type==ROOT_MARKER): header + opaque payload
      - Main_Data: 20-byte header + timl_length opaque TIML + attr blocks
        - Known attr types: fully parsed for exact size
        - Unknown attr types: opaque blob (forward-scan to next known hash)
  - Subselect (subselectionSize B) → parsed per BT
  - End (countEOF ints) → list of ints

Type widths (BT convention, little-endian):
  long/ulong = 4 B,  int/uint = 4 B,  short = 2 B,  byte = 1 B
  int64/uint64 = 8 B,  float = 4 B
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .hashes import (
    ROOT_MARKER, PLAYEFX, PLAYEMITTER, ATTR_HASHES,
    HASH_TO_NAME, TIML,
    # known attr types with fixed sizes
    TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE, EMITTERSHAPE3D, VELOCITY3D,
    FADEBYDEPTH, BILLBOARD3D, SCALEANIM, UVSEQUENCE, ALPHACORRECTION,
    SHADERSETTINGS, RGBFIRE, MESH, ROTATEANIM, PLEMISSIVE, GUIDE, LIGHTNING,
    PARENTEMISSIVE, PTCOLLISION, PLSNOW, PTBEHAVIOR, PLANE, RGBWATER,
    TURBULENCE, FADEBYEMITTERANGLE, RIBBON, NOISE, UVCONTROL, FADEBYANGLE,
    EMITTERBOUNDARY, PTLIFE, STRAINRIBBON, SCREENSPACECOLLISION, RAYCAST,
    EXTERNREFERENCE, FAKEPLANE, DUMMY, RANDOMFIX, TRANSFORM2D, BILLBOARD2D,
    BLINK, LUMINANCEBLEED, EMITTERSHAPE2D, VELOCITY2D, REFRACTION, MASTERONLY,
    TUBELIGHT, SHOVEL, LAYOUT, FAKEDOF, REPEATAREA, LINKPARTSVISIBLE, PTTRIGGER,
    PATHCHAIN, HOMING, EMITTERSHAPEMESH, SPAWNBYANGLE, CHECKPUREATTRIBUTE,
    TONEMAPFILTER, COLORCORRECTFILTER, SPAWNBYOCCLUSION, FADEBYOCCLUSION,
    PARENTSNOW, OTOMOSNOW, PARENTMATERIAL, RIBBONBLADE, MATERIAL,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper: compute exact byte size of a known attr block (INCLUDING 4-byte type hash)
# Returns None for unknown types → caller must forward-scan.
# ─────────────────────────────────────────────────────────────────────────────

def _xyz_size(xyz_type: int) -> int:
    """Return byte size of an XYZ struct body (EFX_Utils.bt) for given type."""
    if xyz_type == 0:
        return 24  # float fixed_x, random_x, fixed_y, random_y, fixed_z, random_z
    elif xyz_type == 1:
        return 12  # int x, y, z
    elif xyz_type == 2:
        return 4   # ubyte x, y, z, pad
    elif xyz_type == 3:
        return 12  # float x, y, z
    return 0

def _known_attr_size(data: bytes, pos: int, type_hash: int) -> Optional[int]:
    """
    Return total byte size (including the 4-byte type hash prefix) of a known
    attribute block at *pos*.  Returns None if type is unknown or has variable
    length that requires byte inspection (will be handled by forward-scan fallback).

    Fixed-size types: on-disk length = 4 (type hash) + data_bytes size, taken from ATTR_SCHEMA_MAP.
    Only variable / dispatch types (path_len or nested, '_custom' in the map) are sized by reading bytes below.
    """
    def rd_i(offset: int) -> int:
        return struct.unpack_from('<i', data, pos + offset)[0]

    h = type_hash

    # Fixed-size types
    from .structs import ATTR_SCHEMA_MAP
    _entry = ATTR_SCHEMA_MAP.get(h)
    if _entry is not None and _entry[1] is not None:
        return 4 + _entry[1]

    # Variable/dispatch types
    # In ATTR_SCHEMA_MAP, marked as '_custom'/size=None, need to read bytes to determine length.

    # Variable length blocks derive size from codec schema: custom_on_disk_size handles path_len tails,
    # custom_nullstr_size handles fixed-prefix + null-terminated string families.
    # If neither recognizes the type, return None and fall through to the specialized walker below.
    from .structs import custom_on_disk_size, custom_nullstr_size
    _s = custom_on_disk_size(h, data, pos)
    if _s is None:
        _s = custom_nullstr_size(h, data, pos)
    if _s is not None:
        return _s

    # PtBehavior: long type(4) + EFX_Behavior
    # EFX_Behavior: int unkn0(4) + int behav_type_len(4) + int para_count(4) + char b_type[behav_type_len]
    #               + EFX_Behav[para_count]
    # EFX_Behav: long unkn(4) + long const0(4) + int t(4) + data depending on t
    if h == PTBEHAVIOR:
        behav_type_len = rd_i(4 + 4)  # type(4) + unkn0(4) + behav_type_len(4) = at pos+8
        para_count = rd_i(4 + 8)      # at pos+12
        if behav_type_len < 0 or behav_type_len > 200 or para_count < 0 or para_count > 200:
            return None  # fallback to forward scan
        p = 4 + 12 + behav_type_len   # pos offset to first EFX_Behav
        for _ in range(para_count):
            t = rd_i(p + 8)           # int t at offset 8 within each EFX_Behav
            base = 12                  # long unkn(4) + long const0(4) + int t(4)
            if t == 0x03:
                extra = 4             # long NULL
            elif t == 0x05:
                extra = 2             # short unkn0
            elif t == 0x06:
                extra = 4             # int decal_epv_color_slot
            elif t == 0x0C:
                extra = 4             # float unkn0
            elif t == 0x0F:
                extra = 4             # XYZ(2) = ubyte[3]+pad = 4B
            elif t == 0x14:
                extra = 12            # XYZ(3) = float[3] = 12B
            elif t == 0x15:
                extra = 16            # float+long+float+long = 16B
            elif t in (0x36, 0x37):
                extra = 8             # 0x36=int[2], 0x37=float[2]; same 8B width either way
            elif t == 0x40:
                extra = 8             # int64
            elif t == 0x80:
                # long file_type(4) + int path_len(4) + char p[path_len]
                # Note: BT says "long NULL" for path_len field but the 4B at p+16 IS path_len
                path_len_val = rd_i(p + 12 + 4)  # path_len at p+16 (file_type=4B then path_len)
                extra = 4 + 4 + path_len_val     # file_type(4) + path_len_field(4) + path bytes
            else:
                extra = 4             # long unkn_type fallback
            p += base + extra
        return p                      # total size from pos

    # Material: long type(4) + int64 unkn00(8) + int block_count(4) = 16B header
    # Then block_count Tex_Block entries:
    #   Tex_Block: long mat_name_hash(4) + long mat_shader(4) + long unkn03(4) + int set_count(4) = 16B
    #   Then set_count Tex_Set entries:
    #     Tex_Set: long set(4) + int unkn0(4) + long t(4) + int type(4) = 16B base
    #     type=0x80: long head(4)+long NULL(4)+int path_len(4)+char p[path_len]
    #     type=0x06: int64 NULL(8)+int unkn(4) = 12B
    #     type=0x03/0x0A/0x0C: long NULL[3] = 12B
    #     type=0x15: float[6] = 24B
    #     else: long unkn_type = 4B
    if h == MATERIAL:
        block_count = rd_i(12)     # at pos+12
        p = 16                     # skip type(4)+int64(8)+block_count(4)
        for _ in range(block_count):
            set_count = rd_i(p + 12)   # int set_count at offset 12 within Tex_Block
            p += 16                     # Tex_Block header
            for _ in range(set_count):
                type_ = rd_i(p + 12)   # int type at offset 12 within Tex_Set
                p += 16                 # Tex_Set base
                if type_ == 0x80:
                    path_len_val = rd_i(p + 4 + 4)  # head(4)+NULL(4)+path_len
                    p += 4 + 4 + 4 + path_len_val
                elif type_ == 0x06:
                    p += 12             # int64(8) + int(4)
                elif type_ in (0x03, 0x0A, 0x0C):
                    p += 12             # long[3]
                elif type_ == 0x15:
                    p += 24             # float[6]
                else:
                    p += 4              # long unkn_type
        return p                    # total size from pos

    # Layout: 4(type) + int*2(8) + long*4(16) + LayoutBank_Block(variable_length).
    if h == LAYOUT:
        from .structs import _walk_layoutbank_block
        try:
            p = pos + 4 + 8 + 16  # skip type + int unkn0[2] + long unkn1[4]
            end = _walk_layoutbank_block(data, p)
        except (struct.error, ValueError, IndexError):
            return None
        return end - pos

    return None  # truly unknown type

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EFXHeader:
    """72-byte file header (fully parsed)。
    """
    signature: bytes        # b"EFX\x00"
    version: int
    constant: tuple         # 5 ints
    efxr: bytes             # b"efxr"
    is_3d: int              # 0=2D, 1=3D. mismatch with entry will cause CTD
    unkn1: int
    count_body: int         # count entry
    label_size: int
    count_play: int         # count action
    count_extern: int
    count_subselect: int
    subselect_size: int
    count_eof: int          # count direct-activation list
    double_buffer: int

    STRUCT = struct.Struct('<4s i 5i 4s 10I')
    SIZE = 72

    def serialize(self) -> bytes:
        return self.STRUCT.pack(
            self.signature, self.version,
            *self.constant,
            self.efxr,
            self.is_3d, self.unkn1,
            self.count_body, self.label_size,
            self.count_play, self.count_extern,
            self.count_subselect, self.subselect_size,
            self.count_eof, self.double_buffer,
        )

@dataclass
class ActionEntry:
    """One entry within a ActionData block: either PlayEFX or PlayEmitter."""
    type_hash: int
    raw: bytes  # the entry bytes EXCLUDING the 4-byte type_hash prefix

    def serialize(self) -> bytes:
        return struct.pack('<I', self.type_hash) + self.raw

@dataclass
class ActionData:
    """One countPlay entry in the Play section."""
    play_type: int      # the 'long type' of ActionData
    entries: List[ActionEntry]

    def serialize(self) -> bytes:
        out = struct.pack('<Ii', self.play_type, len(self.entries))
        for e in self.entries:
            out += e.serialize()
        return out

@dataclass
class ExternDataItem:
    """One Extern_Data sub-item within an Extern_Attribute (opaque payload)."""
    type_hash: int
    unkn: int           # int (4B) after type hash
    attr_count: int     # int (4B): number of structs in data_bytes
    data_bytes: bytes   # attr_count * struct_size bytes (opaque)

    def serialize(self) -> bytes:
        return struct.pack('<Iii', self.type_hash, self.unkn, self.attr_count) + self.data_bytes

@dataclass
class ExternAttribute:
    """One entry in the Extern section (Extern_Attribute)."""
    attr_type: int      # long (4B)
    null0: int          # long (4B) = 0
    null1: int          # long (4B) = 0
    items: List[ExternDataItem]

    def serialize(self) -> bytes:
        out = struct.pack('<IiIi', self.attr_type, self.null0, len(self.items), self.null1)
        for item in self.items:
            out += item.serialize()
        return out

@dataclass
class AttrBlock:
    """One attribute block within a Main_Data body."""
    type_hash: int
    data_bytes: bytes   # bytes AFTER the 4-byte type hash

    @property
    def name(self) -> str:
        return HASH_TO_NAME.get(self.type_hash, f'0x{self.type_hash:08X}')

    def serialize(self) -> bytes:
        return struct.pack('<I', self.type_hash) + self.data_bytes

    def decode(self) -> Optional[dict]:
        """
        Decode data_bytes into a named-field dict using the registered schema
        for this block's type_hash.  Returns None if no schema is registered
        (block stays opaque).

        For fixed-size types, uses the schema from ATTR_SCHEMA_MAP.
        For variable/dispatch types (schema == '_custom'), uses ATTR_CUSTOM_CODEC.
        """
        from .structs import ATTR_SCHEMA_MAP, ATTR_CUSTOM_CODEC, unpack
        entry = ATTR_SCHEMA_MAP.get(self.type_hash)
        if entry is None:
            return None
        schema, expected_size = entry

        # Variable/dispatch types: route to custom codec
        if schema == '_custom':
            custom = ATTR_CUSTOM_CODEC.get(self.type_hash)
            if custom is None:
                return None
            unpack_fn, _ = custom
            values, consumed = unpack_fn(self.data_bytes, 0)
            if consumed != len(self.data_bytes):
                raise ValueError(
                    f'AttrBlock.decode (custom): {self.name} '
                    f'consumed {consumed} bytes but data_bytes is {len(self.data_bytes)} bytes'
                )
            return values

        # Fixed-size schema
        if len(self.data_bytes) != expected_size:
            raise ValueError(
                f'AttrBlock.decode: {self.name} '
                f'data_bytes length {len(self.data_bytes)} '
                f'!= expected {expected_size}'
            )
        values, consumed = unpack(schema, self.data_bytes, 0)
        if consumed != expected_size:
            raise ValueError(
                f'AttrBlock.decode: {self.name} '
                f'schema consumed {consumed} bytes but data_bytes is {expected_size} bytes'
            )
        return values

    def encode(self, values: dict) -> None:
        """
        Re-encode *values* (as returned by decode()) back into data_bytes
        in-place, using the registered schema.  Raises ValueError if the
        resulting bytes differ in length from the original data_bytes.
        """
        from .structs import ATTR_SCHEMA_MAP, ATTR_CUSTOM_CODEC, pack
        entry = ATTR_SCHEMA_MAP.get(self.type_hash)
        if entry is None:
            raise ValueError(
                f'AttrBlock.encode: no schema for {self.name} '
                f'(0x{self.type_hash:08X})'
            )
        schema, expected_size = entry

        # Variable/dispatch types: route to custom codec
        if schema == '_custom':
            custom = ATTR_CUSTOM_CODEC.get(self.type_hash)
            if custom is None:
                raise ValueError(
                    f'AttrBlock.encode: no custom codec for {self.name} '
                    f'(0x{self.type_hash:08X})'
                )
            _, pack_fn = custom
            encoded = pack_fn(values)
            if len(encoded) != len(self.data_bytes):
                raise ValueError(
                    f'AttrBlock.encode (custom): {self.name} '
                    f'encoded {len(encoded)} bytes but original data_bytes is '
                    f'{len(self.data_bytes)} bytes'
                )
            self.data_bytes = encoded
            return

        # Fixed-size schema
        encoded = pack(schema, values)
        if len(encoded) != expected_size:
            raise ValueError(
                f'AttrBlock.encode: {self.name} '
                f'encoded {len(encoded)} bytes but expected {expected_size}'
            )
        self.data_bytes = encoded

@dataclass
class EntryData:
    """A Main_Data body (non-Root)."""
    body_type: int          # type hash (= jamcrc32 of label)
    unkn0: int
    attr_count: int         # expected number of attr blocks
    null: int
    timl_length: int
    timl_bytes: bytes       # timl_length bytes (opaque)
    attr_blocks: List[AttrBlock]

    def serialize(self) -> bytes:
        # evc dummy: attr_count is negative → range() is empty → parse 0 blocks, but original field value must be preserved
        count = self.attr_count if (not self.attr_blocks and self.attr_count != 0) else len(self.attr_blocks)
        head = struct.pack('<IiiiI', self.body_type, self.unkn0,
                           count, self.null, self.timl_length)
        out = head + self.timl_bytes
        for blk in self.attr_blocks:
            out += blk.serialize()
        return out

@dataclass
class EntryDataExtended:
    """
    A Main_Data body with an extended 36-byte header (body_type == 1).

    Extended header layout (36 B):
      +0:  body_type (4B) = 1
      +4:  unkn0     (4B) = 0
      +8:  null0     (4B) = 0
      +12: null1     (4B) = 0
      +16: unkn1     (4B) = opaque (sometimes equals jamcrc32 of a label)
      +20: unkn2     (4B)
      +24: attr_count(4B)
      +28: null2     (4B) = 0
      +32: timl_length(4B)
      +36: timl data (timl_length bytes, opaque)
    followed by attr_count attribute blocks.
    """
    body_type: int       # = 1
    unkn0: int           # = 0
    null0: int           # = 0
    null1: int           # = 0
    unkn1: int           # opaque
    unkn2: int           # opaque
    attr_count: int      # number of attr blocks
    null2: int           # = 0
    timl_length: int
    timl_bytes: bytes    # timl_length bytes
    attr_blocks: List[AttrBlock]

    def serialize(self) -> bytes:
        head = struct.pack(
            '<IiiiIiiIi',
            self.body_type, self.unkn0, self.null0, self.null1,
            self.unkn1, self.unkn2, len(self.attr_blocks), self.null2,
            self.timl_length,
        )
        out = head + self.timl_bytes
        for blk in self.attr_blocks:
            out += blk.serialize()
        return out

@dataclass
class RootUnitBoundary:
    """
    Root Subentry UnitBoundary (EFX_Root.bt). Fixed 44 bytes:
      long type(4) = ROOT_UNITBOUNDARY
      int  ints[2] (8)        —— unit/boundary related integers (unexplained)
      float floats[8] (32)    —— contains bounding-box-like values (8 floats).
    """
    ints: tuple    # (int0, int1)
    floats: tuple  # 8 floats

    def serialize(self) -> bytes:
        return (struct.pack('<i', RootBody.UNITBOUNDARY)
                + struct.pack('<2i', *self.ints)
                + struct.pack('<8f', *self.floats))

@dataclass
class RootOpaqueEntry:
    """Root Subentry with unstructured type (RenderTarget / LayoutBank), stored as-is."""
    raw: bytes   # Entire subentry bytes (including leading type)

    def serialize(self) -> bytes:
        return self.raw

@dataclass
class RootBody:
    """
    Root body (type == ROOT_MARKER)
    
    16B header (root_type + const0 + count + const1) followed by count subentries.
    UnitBoundary is structured into editable fields; RenderTarget/LayoutBank are opaque.
    If raw is not None (legacy/unstructured opaque fallback), serialize() returns raw verbatim.
    """
    # Subentry type markers
    UNITBOUNDARY = 1413509420
    RENDERTARGET = 2083659062
    LAYOUTBANK   = 2050487542

    root_type: int = ROOT_MARKER
    const0: int = 1
    const1: int = 0
    entries: list = field(default_factory=list)   # RootUnitBoundary | RootOpaqueEntry
    raw: bytes = None   # opaque fallback for unknown root bodies

    def serialize(self) -> bytes:
        if self.raw is not None:
            return self.raw
        out = struct.pack('<iiii', self.root_type, self.const0,
                          len(self.entries), self.const1)
        for e in self.entries:
            out += e.serialize()
        return out

@dataclass
class SubselectTable:
    """One table in the Subselect section."""
    table_type: int     # long (4B)
    unkn0: tuple        # long[3] (12B)
    entries: List[int]  # int[count]

    def serialize(self) -> bytes:
        out = struct.pack('<I3I', self.table_type, *self.unkn0)
        out += struct.pack('<i', len(self.entries))
        for e in self.entries:
            out += struct.pack('<i', e)
        return out

# ─────────────────────────────────────────────────────────────────────────────
# Main EFX parser/serializer
# ─────────────────────────────────────────────────────────────────────────────

class EFXFile:
    """
    Parses and re-serializes a MHW .efx file.

    Usage::

        efx = EFXFile.parse(open('foo.efx', 'rb').read())
        assert efx.serialize() == open('foo.efx', 'rb').read()
    """

    def __init__(self):
        self.header: EFXHeader = None
        self.label_bytes: bytes = b''         # raw EFX_Type section
        self.labels: List[str] = []
        self.play: List[ActionData] = []
        self.extern: List[ExternAttribute] = []
        self.main: List = []                  # List[EntryData | RootBody]
        self.subselect: List[SubselectTable] = []
        self.eof_ints: List[int] = []
        self.eof_tail: bytes = b''     # end-of-file tail bytes after EOF

        # ── opaque fallback when main section is unparseable ──────────────────────────────────────
        # some files have main section blocks that cannot yet delimit (forward_scan heuristic overrun),
        # causing the whole parse to crash. In this case, store all bytes from main start to EOF
        # as an opaque blob, and serialize() will verbatim re-emit it → still byte-perfect and importable.
        # Cost: main section cannot be edited block-by-block in Blender (read-only).
        self.main_opaque: bool = False
        self.opaque_main_tail: bytes = b''

    # ── Public API ──────────────────────────────────────────────────────────

    @classmethod
    def parse(cls, data: bytes) -> 'EFXFile':
        obj = cls()
        pos = 0

        # ── Header ──────────────────────────────────────────────────────────
        raw = EFXHeader.STRUCT.unpack_from(data, pos)
        pos += EFXHeader.SIZE
        sig, ver, c0, c1, c2, c3, c4, efxr, u0, u1, cb, ls, cp, ce, cs, ss, ceof, db = raw
        obj.header = EFXHeader(
            signature=sig, version=ver,
            constant=(c0, c1, c2, c3, c4),
            efxr=efxr,
            is_3d=u0, unkn1=u1,
            count_body=cb, label_size=ls,
            count_play=cp, count_extern=ce,
            count_subselect=cs, subselect_size=ss,
            count_eof=ceof, double_buffer=db,
        )
        hdr = obj.header

        # ── EFX_Type (label table) ───────────────────────────────────────────
        obj.label_bytes = data[pos:pos + hdr.label_size]
        obj.labels = [
            s.decode('utf-8', errors='replace')
            for s in obj.label_bytes.rstrip(b'\x00').split(b'\x00')
            if s
        ]
        pos += hdr.label_size

        # ── Play ─────────────────────────────────────────────────────────────
        obj.play, pos = cls._parse_play(data, pos, hdr.count_play)

        # ── Extern ───────────────────────────────────────────────────────────
        obj.extern, pos = cls._parse_extern(data, pos, hdr.count_extern)

        # ── Main（+ Subselect + End）─────────────────────────────────────────
        # If _parse_main crashes due to undelimited blocks, the entire segment (from main start to EOF)
        # is treated as opaque fallback, ensuring the file can still be imported byte-perfectly
        main_start = pos
        try:
            obj.main, pos = cls._parse_main(data, pos, hdr.count_body)

            # ── Subselect ────────────────────────────────────────────────────
            if hdr.subselect_size > 0:
                obj.subselect, pos = cls._parse_subselect(data, pos, hdr.count_subselect)
            else:
                obj.subselect = []

            # ── End ──────────────────────────────────────────────────────────
            obj.eof_ints = list(struct.unpack_from(f'<{hdr.count_eof}I', data, pos))
            pos += hdr.count_eof * 4

            # end-of-file tail bytes: some game files have opaque footer bytes after EOF
            # These are captured as opaque tail bytes and preserved verbatim (78 sample tail is empty).
            obj.eof_tail = data[pos:]
        except Exception:
            # main parsing failed: treat the entire segment (including subselect/eof/tail) as opaque, re-emit verbatim.
            obj.main = []
            obj.subselect = []
            obj.eof_ints = []
            obj.eof_tail = b''
            obj.main_opaque = True
            obj.opaque_main_tail = data[main_start:]

        return obj

    def serialize(self) -> bytes:
        out = self.header.serialize()
        out += self.label_bytes

        for pd in self.play:
            out += pd.serialize()

        for ea in self.extern:
            out += ea.serialize()

        # main section is unparseable: fall back to opaque handling
        if self.main_opaque:
            out += self.opaque_main_tail
            return out

        for body in self.main:
            out += body.serialize()

        for tbl in self.subselect:
            out += tbl.serialize()

        for v in self.eof_ints:
            out += struct.pack('<I', v)

        out += self.eof_tail   # end-of-file tail bytes (most files are empty)

        return out

    # ── Internal section parsers ─────────────────────────────────────────────

    @staticmethod
    def _parse_play(data: bytes, pos: int, count: int):
        """Parse countPlay ActionData entries."""
        results = []
        for _ in range(count):
            play_type = struct.unpack_from('<I', data, pos)[0]
            entry_count = struct.unpack_from('<i', data, pos + 4)[0]
            pos += 8
            entries = []
            for _ in range(entry_count):
                type_hash = struct.unpack_from('<I', data, pos)[0]
                pos += 4
                if type_hash == PLAYEFX:
                    # PlayEFX layout (all fields after type_hash):
                    # int unkn0(4) + int path_len(4) + long type(4) + int unkn[7](28)
                    # + XYZ xyz(3)(12) + int NULL[3](12) + char p[path_len]
                    # = 4+4+4+28+12+12 = 64B fixed + path_len
                    path_len = struct.unpack_from('<i', data, pos + 4)[0]
                    entry_size = 64 + path_len
                    entry_raw = data[pos:pos + entry_size]
                    pos += entry_size
                elif type_hash == PLAYEMITTER:
                    # PlayEmitter layout:
                    # int unkn[7](28) + XYZ xyz(3)(12) + int NULL[3](12) + int target_count(4) + int targets[target_count]
                    # = 28+12+12+4 = 56B fixed + 4*target_count
                    target_count = struct.unpack_from('<i', data, pos + 52)[0]
                    entry_size = 56 + 4 * target_count
                    entry_raw = data[pos:pos + entry_size]
                    pos += entry_size
                else:
                    raise ValueError(
                        f'Unknown Play typeHash 0x{type_hash:08X} at offset {pos-4}'
                    )
                entries.append(ActionEntry(type_hash=type_hash, raw=entry_raw))
            results.append(ActionData(play_type=play_type, entries=entries))
        return results, pos

    @staticmethod
    def _parse_extern(data: bytes, pos: int, count: int):
        """Parse countExtern Extern_Attribute entries."""
        results = []
        for _ in range(count):
            # Extern_Attribute: long type(4) + long NULL0(4) + int count(4) + long NULL1(4)
            attr_type = struct.unpack_from('<I', data, pos)[0]
            null0 = struct.unpack_from('<i', data, pos + 4)[0]
            item_count = struct.unpack_from('<i', data, pos + 8)[0]
            null1 = struct.unpack_from('<i', data, pos + 12)[0]
            pos += 16

            items = []
            for _ in range(item_count):
                # Extern_Data: long t(4) + int unkn(4) + int attri_count(4) + data
                t = struct.unpack_from('<I', data, pos)[0]
                unkn = struct.unpack_from('<i', data, pos + 4)[0]
                attri_count = struct.unpack_from('<i', data, pos + 8)[0]
                pos += 12
                item_size = EFXFile._extern_data_size(t, attri_count, data, pos)
                item_bytes = data[pos:pos + item_size]
                pos += item_size
                items.append(ExternDataItem(
                    type_hash=t, unkn=unkn, attr_count=attri_count, data_bytes=item_bytes
                ))
            results.append(ExternAttribute(
                attr_type=attr_type, null0=null0, null1=null1, items=items
            ))
        return results, pos

    @staticmethod
    def _efx_behavior_size(data: bytes, pos: int) -> int:
        """
        Return the byte size of one EFX_Behavior struct at *pos*:
          int unkn0(4) + int behav_type_len(4) + int para_count(4)
          + char b_type[behav_type_len] + EFX_Behav[para_count]
        EFX_Behav = long unkn(4) + long const0(4) + int t(4) + variable-length data (dispatched by t).
        Shares the same encoding with the main PTBEHAVIOR block's EFX_Behavior (see _known_attr_size::PTBEHAVIOR).
        """
        behav_type_len = struct.unpack_from('<i', data, pos + 4)[0]
        para_count = struct.unpack_from('<i', data, pos + 8)[0]
        p = pos + 12 + behav_type_len   # skip unkn0/behav_type_len/para_count + b_type
        for _ in range(para_count):
            t = struct.unpack_from('<i', data, p + 8)[0]  # int t at offset 8 in EFX_Behav
            base = 12                  # long unkn(4) + long const0(4) + int t(4)
            if t == 0x03:
                extra = 4              # long NULL
            elif t == 0x05:
                extra = 2              # short unkn0
            elif t == 0x06:
                extra = 4              # int decal_epv_color_slot
            elif t == 0x0C:
                extra = 4              # float unkn0
            elif t == 0x0F:
                extra = 4              # XYZ(2) = ubyte[3]+pad
            elif t == 0x14:
                extra = 12            # XYZ(3) = float[3]
            elif t == 0x15:
                extra = 16            # float+long+float+long
            elif t in (0x36, 0x37):
                extra = 8             # 0x36=int[2], 0x37=float[2]; same 8B width either way
            elif t == 0x40:
                extra = 8             # int64
            elif t == 0x80:
                path_len_val = struct.unpack_from('<i', data, p + 12 + 4)[0]
                extra = 4 + 4 + path_len_val  # file_type(4) + path_len(4) + path
            else:
                extra = 4             # long unkn_type fallback
            p += base + extra
        return p - pos

    @staticmethod
    def _extern_data_size(type_hash: int, attri_count: int,
                          data: bytes = b'', pos: int = 0) -> int:
        """Return total data bytes (after the 12-byte Extern_Data header) for a known extern type.
        data/pos are required for variable-length types."""
        # Fixed sizes (bytes per element)
        FIXED = {
            500644368: 228,   # EXTERNTRANSFORM3D  (ExternTransform3D)
            351887441: 108,   # EXTERNVELOCITY3D
            786529163: 76,    # EXTERNSCALEANIM
            2069124466: 112,  # EXTERNRGBFIRE
            28559457: 72,     # EXTERNSPAWN (EFX_Crimson.bt: ExternSpawn = long unkn[18] = 72B)
            1880343637: 88,   # EXTERNEMITTERSHAPE3D (EFX_Crimson.bt: long unkn[22] = 88B)
            725249589: 76,    # EXTERNPLEMISSIVE
            1338793878: 48,   # EXTERNVELOCITY3D0 (long unkn[12] = 48B)
            283026906: 84,    # EXTERNVELOCITY3D2 (long unkn[21] = 84B)
            705591903: 72,    # EXTERNVELOCITY3D5 (long unkn[18] = 72B)
            1879331968: 80,   # EXTERNVELOCITY3D6 (long unkn[20] = 80B)

            0x3002E4CE: 157,  # EXTERNVELOCITY3D7 (long unkn[39] + byte unkn1 = 39*4+1 = 157B)
            0x295D488A: 133,  # EXTERNBILLBOARD3D (133B/elem, confirmed via structural analysis)
            0x320E3177: 361,  # EXTERNVELOCITY3D1 (361B/elem, confirmed via structural analysis)
            0x1CC2BE3A: 161,  # EXTERNRGBWATER (161B/elem, roundtrip verified)
            0x7CFF28CC: 45,   # EXTERNUVSEQUENCE (45B/elem, confirmed via structural analysis)
        }
        if type_hash in FIXED:
            return attri_count * FIXED[type_hash]

        # Variable-length: EXTERNMESH - each element has 175B fixed + 2 null-terminated strings
        # ExternMesh = Mod3Properties(174B) + byte BeginMod3(1) + string path + string placement
        if type_hash == 1850314036:  # EXTERNMESH
            p = pos
            for _ in range(attri_count):
                path1_start = p + 175
                null1 = data.index(b'\x00', path1_start)
                null2 = data.index(b'\x00', null1 + 1)
                p = null2 + 1
            return p - pos

        # Variable-length: EXTERNPTBEHAVIOR - data = EFX_Behavior efx_behavior[attri_count]
        # EFX_Behavior is the same as the main PTBEHAVIOR block: int unkn0(4) +
        # int behav_type_len(4) + int para_count(4) + char
        # b_type[behav_type_len] + EFX_Behav[para_count] (each parameter is variable-length, dispatched by t).
        if type_hash == 0x5FFC3E36:  # EXTERNPTBEHAVIOR
            p = pos
            for _ in range(attri_count):
                p += EFXFile._efx_behavior_size(data, p)
            return p - pos

        # Variable-length types that are not yet seen in samples - raise for diagnosis
        raise ValueError(
            f'Cannot compute size for unknown Extern_Data type 0x{type_hash:08X} '
            f'({HASH_TO_NAME.get(type_hash, "UNKNOWN")}). '
            f'attri_count={attri_count}. '
            f'This type needs manual size implementation.'
        )

    @staticmethod
    def _parse_main(data: bytes, pos: int, count: int):
        """Parse countBody Main bodies."""
        results = []
        for body_idx in range(count):
            if pos + 4 > len(data):
                raise ValueError(f'EOF reached while reading Main body {body_idx} at pos {pos}')
            first_int = struct.unpack_from('<I', data, pos)[0]
            if first_int == ROOT_MARKER:
                body, pos = EFXFile._parse_root_body(data, pos)
            else:
                body, pos = EFXFile._parse_main_data_body(data, pos)
            results.append(body)
        return results, pos

    @staticmethod
    def _parse_root_body(data: bytes, start_pos: int):
        """
        Parse a Root body opaquely.

        Root body structure (EFX_Root.bt):
          long type (4B, = ROOT_MARKER)
          int CONST0 (4B, = 1)
          int count  (4B)
          int CONST1 (4B, = 0)
          for count sub-entries: each starts with a known hash and has its own fixed/variable size.

        The header (16 B) is parsed; the sub-entry payload is kept opaque (bounded by
        _known_attr_size / forward-scan), so the Root body round-trips byte-for-byte.
        """
        pos = start_pos
        root_type = struct.unpack_from('<I', data, pos)[0]   # = ROOT_MARKER
        const0 = struct.unpack_from('<i', data, pos + 4)[0]  # = 1
        count = struct.unpack_from('<i', data, pos + 8)[0]
        const1 = struct.unpack_from('<i', data, pos + 12)[0] # = 0
        pos += 16

        # Parse count sub-entries (UnitBoundary, RenderTarget, LayoutBank)
        UNITBOUNDARY = RootBody.UNITBOUNDARY
        RENDERTARGET = RootBody.RENDERTARGET
        LAYOUTBANK   = RootBody.LAYOUTBANK

        entries = []
        for i in range(count):
            sub_type = struct.unpack_from('<i', data, pos)[0]
            ent_start = pos
            if sub_type == UNITBOUNDARY:
                # long type(4) + int*2(8) + float*8(32) = 44B
                ints = struct.unpack_from('<2i', data, pos + 4)
                floats = struct.unpack_from('<8f', data, pos + 12)
                entries.append(RootUnitBoundary(ints=ints, floats=floats))
                pos += 44
            elif sub_type == RENDERTARGET:
                # long type(4) + int path_count(4, = 6 hardcoded) + 6*RenderTarget_Path + long NULL(4) + int*6(24) + float*9(36)
                # RenderTarget_Path = int path_len(4) + char p[path_len]
                pos += 4 + 4  # type + path_count
                for _ in range(6):
                    p_len = struct.unpack_from('<i', data, pos)[0]
                    pos += 4 + p_len
                pos += 4 + 24 + 36  # NULL + unkn0[6] + unkn1[9]
                entries.append(RootOpaqueEntry(raw=data[ent_start:pos]))
            elif sub_type == LAYOUTBANK:
                # LayoutBank: long type(4) + int unkn0(4) + int block_count(4) + block_count*LayoutBank_Block
                # LayoutBank_Block = int count(4) + if count>0: while ReadInt()!=-1: LayoutBank_B; long end
                # LayoutBank_B = int block_type(4) + data depending on block_type
                pos = EFXFile._parse_layout_bank(data, pos)
                entries.append(RootOpaqueEntry(raw=data[ent_start:pos]))
            else:
                # Unknown sub-type in Root body - should not happen in well-formed files
                raise ValueError(
                    f'Unknown Root sub-entry type 0x{sub_type:08X} at pos {pos}'
                )

        return RootBody(root_type=root_type, const0=const0, const1=const1,
                        entries=entries), pos

    @staticmethod
    def _parse_layout_bank(data: bytes, pos: int) -> int:
        """Parse a LayoutBank struct (long type + int unkn0 + int block_count +
        block_count*LayoutBank_Block) and return the new position."""
        from .structs import _walk_layoutbank_block
        block_count = struct.unpack_from('<i', data, pos + 8)[0]  # int block_count
        pos += 12

        for _ in range(block_count):
            pos = _walk_layoutbank_block(data, pos)
        return pos

    @staticmethod
    def _parse_main_data_body(data: bytes, start_pos: int):
        """Parse a Main_Data body (20B header + TIML + attr blocks)."""
        pos = start_pos
        body_type = struct.unpack_from('<I', data, pos)[0]

        # Detect extended 36-byte header: body_type < 256 is not a valid jamcrc32 result,
        # so it indicates the extended header format used by body_type=1 bodies.
        if body_type < 256:
            # Extended 36-byte header layout:
            # type(4)+unkn0(4)+null0(4)+null1(4)+unkn1(4)+unkn2(4)+attr_count(4)+null2(4)+timl_length(4)
            unkn0  = struct.unpack_from('<i', data, pos + 4)[0]
            null0  = struct.unpack_from('<i', data, pos + 8)[0]
            null1  = struct.unpack_from('<i', data, pos + 12)[0]
            unkn1  = struct.unpack_from('<I', data, pos + 16)[0]
            unkn2  = struct.unpack_from('<i', data, pos + 20)[0]
            attr_count = struct.unpack_from('<i', data, pos + 24)[0]
            null2  = struct.unpack_from('<i', data, pos + 28)[0]
            timl_length = struct.unpack_from('<i', data, pos + 32)[0]
            pos += 36

            timl_bytes = data[pos:pos + timl_length]
            pos += timl_length

            attr_blocks, pos = EFXFile._parse_attr_blocks(data, pos, attr_count)

            return EntryDataExtended(
                body_type=body_type, unkn0=unkn0, null0=null0, null1=null1,
                unkn1=unkn1, unkn2=unkn2, attr_count=attr_count, null2=null2,
                timl_length=timl_length, timl_bytes=timl_bytes,
                attr_blocks=attr_blocks,
            ), pos

        # Standard 20-byte header
        unkn0 = struct.unpack_from('<i', data, pos + 4)[0]
        attr_count = struct.unpack_from('<i', data, pos + 8)[0]
        null = struct.unpack_from('<i', data, pos + 12)[0]
        timl_length = struct.unpack_from('<i', data, pos + 16)[0]
        pos += 20

        # TIML (opaque)
        timl_bytes = data[pos:pos + timl_length]
        pos += timl_length

        # Attribute blocks
        attr_blocks, pos = EFXFile._parse_attr_blocks(data, pos, attr_count)

        return EntryData(
            body_type=body_type, unkn0=unkn0, attr_count=attr_count,
            null=null, timl_length=timl_length,
            timl_bytes=timl_bytes, attr_blocks=attr_blocks,
        ), pos

    @staticmethod
    def _parse_attr_blocks(data: bytes, pos: int, attr_count: int):
        """Parse attr_count attribute blocks; use forward-scan for unknown types."""
        blocks = []
        for blk_idx in range(attr_count):
            if pos + 4 > len(data):
                raise ValueError(
                    f'EOF reached reading attr block {blk_idx}/{attr_count} at pos {pos}'
                )
            type_hash = struct.unpack_from('<I', data, pos)[0]
            block_size = _known_attr_size(data, pos, type_hash)

            if block_size is not None:
                # Known type: exact size
                block_data = data[pos + 4:pos + block_size]
                blocks.append(AttrBlock(type_hash=type_hash, data_bytes=block_data))
                pos += block_size
            else:
                # Unknown or variable type: forward-scan to find next block boundary
                scan_start = pos + 4  # after the type hash we just read
                remaining_blocks = attr_count - blk_idx - 1
                end_pos = EFXFile._forward_scan(
                    data, scan_start, remaining_blocks
                )
                block_data = data[pos + 4:end_pos]
                blocks.append(AttrBlock(type_hash=type_hash, data_bytes=block_data))
                pos = end_pos

        return blocks, pos

    @staticmethod
    def _forward_scan(data: bytes, scan_start: int, remaining_blocks: int) -> int:
        """
        Scan forward from scan_start to find the position of the NEXT attribute block's
        type hash (if remaining_blocks > 0) or the end of this body's attribute data.

        The heuristic: the next block starts at the first 4B-aligned offset that reads
        a value in ATTR_HASHES (and is preceded by valid data).  We scan every 4B.

        If remaining_blocks == 0, there is no next block; we must guess the end.
        In that case we scan for any known hash OR body/section boundary.

        Since we don't have explicit body end markers, we can only scan for known hashes.
        If no known hash is found before EOF, return remaining data up to EOF
        (this would be wrong for the middle of a file, but safe for opaque storage).
        """
        if remaining_blocks > 0:
            # Scan for the next known attr hash
            i = scan_start
            while i + 4 <= len(data):
                candidate = struct.unpack_from('<I', data, i)[0]
                if candidate in ATTR_HASHES:
                    return i
                i += 4
            # No next known hash found - return to end of data (edge case)
            return len(data)
        else:
            # Last block in body: scan for next body's type hash OR next known hash
            # We don't have a body boundary marker, so just return scan_start
            # and record the remaining body bytes.
            # This is tricky without explicit lengths.  For now, return scan_start
            # (zero bytes for the payload), which will be wrong but detectable.
            # TODO: improve this case if needed for specific types.
            i = scan_start
            while i + 4 <= len(data):
                candidate = struct.unpack_from('<I', data, i)[0]
                if candidate in ATTR_HASHES or candidate == ROOT_MARKER:
                    return i
                i += 4
            return len(data)

    @staticmethod
    def _parse_subselect(data: bytes, pos: int, count: int):
        """Parse countSubselect Subselect_Table entries."""
        results = []
        for _ in range(count):
            tbl_type = struct.unpack_from('<I', data, pos)[0]
            unkn0 = struct.unpack_from('<3I', data, pos + 4)
            entry_count = struct.unpack_from('<i', data, pos + 16)[0]
            pos += 20
            entries = list(struct.unpack_from(f'<{entry_count}i', data, pos))
            pos += 4 * entry_count
            results.append(SubselectTable(table_type=tbl_type, unkn0=unkn0, entries=entries))
        return results, pos
