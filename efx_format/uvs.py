"""
efx_format/uvs.py  –  MHW UV Sequence (.uvs) parser / serializer.

Format summary
--------------
Header (0x28 bytes, padded to 0x30):
    magic       4 B  b'UVS\\x00'
    ibSig       4 B  [0, 7, 18, 22]
    groupOffset q    absolute offset to GroupHead array
    groupCount  q
    stringOffset q   absolute offset to StringHead array
    stringCount  q

GroupHead (0x40 bytes each):
    frameDataOffset  q   → Primary[] (each 0x20 bytes)
    frameCount       q
    frameIndexOffset q   → Int32sl[] (always [0..n-1])
    frameIndexCount  q   (== frameCount)
    dataOffset       q   → Int32sl[4] path indices (only when frameCount != 0)
    mapCount         q   number of valid path slots (1-4)
    unkn32_0         f   always 32.0
    unkn32_1         f   always 32.0
    unkn3            q   Dynamic value

Primary frame (0x20 bytes):
    uv0_u, uv0_v     f f   top-left UV
    uv1_u, uv1_v     f f   bottom-right UV
    unkn[4]          f*4   always [0.5, 0.5, 0.0, 0.0]

StringHead (0x14 bytes + 0x04 inter-entry padding, last entry has no padding):
    blank            q   always 0
    stringOffset     q   absolute offset to null-terminated UTF-8 string
    type             i   texture slot type (1 = Diffuse, etc.)

All values little-endian.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List


MAGIC   = b'UVS\x00'
IB_SIG  = bytes([0, 7, 18, 22])

_HDR_SZ  = 0x28
_HDR_PAD = 0x30   # header padded to 16-byte boundary
_GRP_SZ  = 0x40
_PRI_SZ  = 0x20
_MAP_SZ  = 0x10   # 4 × int32
_STR_HD  = 0x14   # StringHead without inter-entry padding
_STR_PAD = 0x04   # padding between StringHead entries (not after last)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UVSFrame:
    """One UV animation keyframe: a rectangle on the sprite sheet."""
    uv0: tuple   # (u, v) top-left,     floats in [0, 1]
    uv1: tuple   # (u, v) bottom-right, floats in [0, 1]
    # unkn[4] is always [0.5, 0.5, 0.0, 0.0]; preserved for roundtrip
    _unkn: tuple = field(default=(0.5, 0.5, 0.0, 0.0), repr=False)


@dataclass
class UVSGroup:
    """One animation channel: UV frames + up to 4 texture path references."""
    frames: List[UVSFrame]
    # indices into UVSFile.strings (length <= 4, padded to 4 with 0 on write)
    path_indices: List[int]
    map_count: int         # number of valid slots (len(path_indices))
    dynamic: int           # unkn3
    unkn32_0: float = 32.0
    unkn32_1: float = 32.0
    # frame_indices stored verbatim for roundtrip; normally [0..n-1]
    _frame_indices: List[int] = field(default_factory=list, repr=False)
    # padding bytes between end of frameIndex array and start of mapIndices;
    # preserved from original for byte-perfect roundtrip.
    # new groups default to -1 = use 16-byte alignment heuristic.
    _fi_dat_gap: int = field(default=-1, repr=False)


@dataclass
class UVSString:
    """One entry in the shared string table."""
    path: str
    type: int   # texture slot type (1 = Diffuse, …)


@dataclass
class UVSFile:
    """Parsed representation of a .uvs file."""
    groups:  List[UVSGroup]
    strings: List[UVSString]

    # ── parse ────────────────────────────────────────────────────────────────

    @classmethod
    def parse(cls, data: bytes) -> 'UVSFile':
        magic, ibsig = data[:4], data[4:8]
        if magic != MAGIC or ibsig != IB_SIG:
            raise ValueError(f'Not a UVS file (magic={magic!r} ibsig={ibsig!r})')

        grp_off, grp_cnt, str_off, str_cnt = struct.unpack_from('<qqqq', data, 8)

        groups  = _parse_groups(data, grp_off, grp_cnt)
        strings = _parse_strings(data, str_off, str_cnt)
        return cls(groups=groups, strings=strings)

    # ── serialize ────────────────────────────────────────────────────────────

    def serialize(self) -> bytes:
        return _serialize(self)


# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_groups(data: bytes, grp_off: int, grp_cnt: int) -> List[UVSGroup]:
    groups = []
    pos = grp_off
    for _ in range(grp_cnt):
        (fd_off, fd_cnt, fi_off, fi_cnt,
         dat_off, map_cnt, u0, u1, unkn3) = struct.unpack_from('<qqqqqqffq', data, pos)
        pos += _GRP_SZ

        frames = _parse_frames(data, fd_off, fd_cnt)

        if fi_cnt > 0:
            fi = list(struct.unpack_from(f'<{fi_cnt}i', data, fi_off))
        else:
            fi = []

        if fd_cnt != 0:
            raw = list(struct.unpack_from('<4i', data, dat_off))
        else:
            raw = [0, 0, 0, 0]
        path_indices = raw[:map_cnt]

        fi_end = fi_off + fi_cnt * 4
        fi_dat_gap = dat_off - fi_end if fd_cnt != 0 else 0

        groups.append(UVSGroup(
            frames=frames,
            path_indices=path_indices,
            map_count=map_cnt,
            dynamic=unkn3,
            unkn32_0=u0,
            unkn32_1=u1,
            _frame_indices=fi,
            _fi_dat_gap=fi_dat_gap,
        ))
    return groups


def _parse_frames(data: bytes, off: int, cnt: int) -> List[UVSFrame]:
    frames = []
    pos = off
    for _ in range(cnt):
        vals = struct.unpack_from('<8f', data, pos)
        frames.append(UVSFrame(
            uv0=(vals[0], vals[1]),
            uv1=(vals[2], vals[3]),
            _unkn=(vals[4], vals[5], vals[6], vals[7]),
        ))
        pos += _PRI_SZ
    return frames


def _parse_strings(data: bytes, str_off: int, str_cnt: int) -> List[UVSString]:
    strings = []
    pos = str_off
    for i in range(str_cnt):
        blank, s_off, s_type = struct.unpack_from('<qqi', data, pos)
        pos += _STR_HD
        if i < str_cnt - 1:
            pos += _STR_PAD   # inter-entry padding (not after last)

        end = data.index(b'\x00', s_off)
        path = data[s_off:end].decode('utf-8')
        strings.append(UVSString(path=path, type=s_type))
    return strings


# ─────────────────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────────────────

def _pad_to(data: bytes, alignment: int) -> bytes:
    rem = len(data) % alignment
    if rem:
        data += b'\x00' * (alignment - rem)
    return data


def _serialize(uvs: UVSFile) -> bytes:
    groups  = uvs.groups
    strings = uvs.strings
    grp_cnt = len(groups)
    str_cnt = len(strings)

    # ── compute offsets ──────────────────────────────────────────────────────
    grp_off = _HDR_PAD                          # groups start right after padded header
    data_off = grp_off + grp_cnt * _GRP_SZ      # frame/index/mapdata area

    # walk groups to assign offsets for frame data, frame indices, map indices
    fd_offsets  = []
    fi_offsets  = []
    map_offsets = []
    cursor = data_off
    for g in groups:
        n = len(g.frames)
        fd_offsets.append(cursor)
        cursor += n * _PRI_SZ

        fi_offsets.append(cursor)
        cursor += n * 4                         # frameIndexCount == frameCount

        # preserve original gap; for new groups (-1) use 16-byte alignment
        gap = g._fi_dat_gap
        if gap < 0:
            rem = cursor % 16
            gap = (16 - rem) % 16

        cursor += gap
        map_offsets.append(cursor)
        if n != 0:
            cursor += _MAP_SZ                   # 4 × int32

    # string heads start at cursor
    str_head_off = cursor
    # string data starts after all string heads
    # each StringHead = 0x14, plus 0x04 padding except last
    str_heads_bytes = str_cnt * _STR_HD + (str_cnt - 1) * _STR_PAD if str_cnt else 0
    str_data_base = str_head_off + str_heads_bytes

    # compute per-string absolute offsets (4-byte aligned between strings)
    str_data_offsets = []
    scursor = str_data_base
    for s in strings:
        str_data_offsets.append(scursor)
        scursor += len(s.path.encode('utf-8')) + 1   # +1 for null terminator
        # align to 4 between entries (not strictly needed after last, but matches original)
        rem = scursor % 4
        if rem:
            scursor += 4 - rem

    # ── build bytes ──────────────────────────────────────────────────────────
    out = bytearray()

    # header
    out += MAGIC
    out += IB_SIG
    out += struct.pack('<q', grp_off)
    out += struct.pack('<q', grp_cnt)
    out += struct.pack('<q', str_head_off)
    out += struct.pack('<q', str_cnt)
    # pad header to 0x30
    while len(out) < _HDR_PAD:
        out += b'\x00'

    # group heads
    for i, g in enumerate(groups):
        n = len(g.frames)
        out += struct.pack('<qqqqqqffq',
            fd_offsets[i], n,
            fi_offsets[i], n,
            map_offsets[i], g.map_count,
            g.unkn32_0, g.unkn32_1,
            g.dynamic,
        )

    # frame data + frame indices + map indices
    for i, g in enumerate(groups):
        n = len(g.frames)
        # frame data
        for f in g.frames:
            out += struct.pack('<8f',
                f.uv0[0], f.uv0[1],
                f.uv1[0], f.uv1[1],
                f._unkn[0], f._unkn[1], f._unkn[2], f._unkn[3],
            )
        # frame indices
        fi = g._frame_indices if g._frame_indices else list(range(n))
        out += struct.pack(f'<{n}i', *fi)

        # padding before map indices (gap preserved from original or 16-byte aligned)
        gap = g._fi_dat_gap if g._fi_dat_gap >= 0 else (16 - (len(out) % 16)) % 16
        out += b'\x00' * gap

        # map indices (only when frameCount != 0)
        if n != 0:
            padded = (g.path_indices + [0, 0, 0, 0])[:4]
            out += struct.pack('<4i', *padded)

    # string heads
    for i, (s, s_off) in enumerate(zip(strings, str_data_offsets)):
        out += struct.pack('<qqi', 0, s_off, s.type)
        if i < str_cnt - 1:
            out += b'\x00' * _STR_PAD

    # string data
    for i, s in enumerate(strings):
        out += s.path.encode('utf-8') + b'\x00'
        if i < str_cnt - 1:
            while len(out) % 4:
                out += b'\x00'

    return bytes(out)
