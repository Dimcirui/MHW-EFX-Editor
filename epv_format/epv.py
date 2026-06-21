"""
epv_format/epv.py — MHW EPV3 (.epv3) 解析 / 序列化。

格式全貌（全小端、全定长、无偏移表，纯顺序读取）
--------------------------------------------------------------------
header:
    signature   uint64

body (blockSection):
    count       uint32                 group 数量
    groups[count]:
        recordCount uint32
        groupID     ushort
        records[recordCount]:          见 EPVRecord，每条定长

trail:
    padding     uint64
    trailCount  uint32
    trails[trailCount]:
        trailID  int32
        blockID  uint32
        recordID uint32
    epvPath     CString utf-8          (null 结尾)
    ONE         byte
    NULL        uint32

EPVRecord 布局
--------------------------------------------------------------------
    packed_path   CString utf-8 × 4    指向 efx 的路径槽（空槽=空串），各以 \0 结尾
    padding       int32
    unknownID     int32                通常 0 或 5
    recordID      ushort
    parameterBlock1:
        paramU0   int32[3]
        paramU1   float32
        paramU2   int32[4]
        EFXSubIndex   short[2]         指向 efx 内部子索引
        paramU3   short[2]
        EFXSubIndex2  short[2]
        paramU4   short[2]
    position        float32[3]
    positionJitter  float32[3]
    rotation        float32[3]
    rotationJitter  float32[3]
    paramW3       int32[2]
    boneID        int32                挂点骨骼，通常 -1
    paramW4       int32[3]
    epvColor      EPVColor × 8         efx 外观覆盖 slot 表
    paramW5       float32[2]
    parameterBlock2:
        f1 float32; b1..b4 byte; i1 int32; f2 float32; i2 int32; i3 int32
    paramV        int32[4]

EPVColor (epvc) 布局
--------------------------------------------------------------------
    efxslot     int32
    hexcolor    ubyte[4]   (RGBA)
    saturation  float32
    size        int32
    frequency   float32

注：record 不存 trailID；trail 段通过 (blockID, recordID) 反向关联。
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EPVColor:
    """epvc — 一个 efx 外观覆盖槽（截图里的一行 EFX Slot）。"""
    efxslot: int = 0
    hexcolor: Tuple[int, int, int, int] = (255, 255, 255, 255)  # RGBA, 0-255
    saturation: float = 0.0
    size: int = 0
    frequency: float = 1.0

    _SZ = 4 + 4 + 4 + 4 + 4  # 20 bytes


@dataclass
class ParameterBlock1:
    paramU0: Tuple[int, int, int] = (1, 0, 0)
    paramU1: float = 0.0
    paramU2: Tuple[int, int, int, int] = (0, 0, 1, 120)
    EFXSubIndex: Tuple[int, int] = (-1, -1)
    paramU3: Tuple[int, int] = (-1, -1)
    EFXSubIndex2: Tuple[int, int] = (-1, -1)
    paramU4: Tuple[int, int] = (0, 0)

    # 3*int32 + float + 4*int32 + 4*(2*short) = 12+4+16+16 = 48
    _SZ = 3 * 4 + 4 + 4 * 4 + 2 * 2 + 2 * 2 + 2 * 2 + 2 * 2


@dataclass
class ParameterBlock2:
    f1: float = 1.0
    b1: int = -128
    b2: int = 13
    b3: int = 1
    b4: int = 0
    i1: int = 6
    f2: float = 100.0
    i2: int = 512
    i3: int = -1

    # float + 4*byte + int32 + float + int32 + int32 = 4+4+4+4+4+4 = 24
    _SZ = 4 + 4 + 4 + 4 + 4 + 4


@dataclass
class EPVRecord:
    packed_path: List[str] = field(default_factory=lambda: ["", "", "", ""])  # 长度恒 4
    padding: int = 0
    unknownID: int = 0
    recordID: int = 0
    parameterBlock1: ParameterBlock1 = field(default_factory=ParameterBlock1)
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    positionJitter: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotationJitter: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    paramW3: Tuple[int, int] = (0, 0)
    boneID: int = -1
    paramW4: Tuple[int, int, int] = (0, 0, -1)
    epvColor: List[EPVColor] = field(default_factory=lambda: [EPVColor() for _ in range(8)])
    paramW5: Tuple[float, float] = (1.0, 0.0)
    parameterBlock2: ParameterBlock2 = field(default_factory=ParameterBlock2)
    paramV: Tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class EPVGroup:
    """一个 block / group：共享 groupID 的一批 record。"""
    groupID: int
    records: List[EPVRecord] = field(default_factory=list)


@dataclass
class EPVTrail:
    trailID: int
    blockID: int
    recordID: int


@dataclass
class EPVFile:
    signature: int
    groups: List[EPVGroup] = field(default_factory=list)
    trails: List[EPVTrail] = field(default_factory=list)
    epvPath: str = ""
    trail_padding: int = 0   # trail 段开头的 uint64，通常 0
    trail_one: int = 1       # ONE byte
    trail_null: int = 0      # NULL uint32

    # ── parse ──────────────────────────────────────────────────────────────
    @classmethod
    def parse(cls, data: bytes) -> "EPVFile":
        pos = 0
        (signature,) = struct.unpack_from("<Q", data, pos); pos += 8

        (count,) = struct.unpack_from("<I", data, pos); pos += 4
        groups: List[EPVGroup] = []
        for _ in range(count):
            (record_count,) = struct.unpack_from("<I", data, pos); pos += 4
            (group_id,) = struct.unpack_from("<H", data, pos); pos += 2
            records = []
            for _ in range(record_count):
                rec, pos = _parse_record(data, pos)
                records.append(rec)
            groups.append(EPVGroup(groupID=group_id, records=records))

        # trail 段
        (trail_padding,) = struct.unpack_from("<Q", data, pos); pos += 8
        (trail_count,) = struct.unpack_from("<I", data, pos); pos += 4
        trails = []
        for _ in range(trail_count):
            tid, bid, rid = struct.unpack_from("<iII", data, pos); pos += 12
            trails.append(EPVTrail(trailID=tid, blockID=bid, recordID=rid))
        epv_path, pos = _read_cstring(data, pos)
        (trail_one,) = struct.unpack_from("<b", data, pos); pos += 1
        (trail_null,) = struct.unpack_from("<I", data, pos); pos += 4

        return cls(
            signature=signature,
            groups=groups,
            trails=trails,
            epvPath=epv_path,
            trail_padding=trail_padding,
            trail_one=trail_one,
            trail_null=trail_null,
        )

    # ── serialize ──────────────────────────────────────────────────────────
    def serialize(self) -> bytes:
        out = bytearray()
        out += struct.pack("<Q", self.signature)
        out += struct.pack("<I", len(self.groups))
        for g in self.groups:
            out += struct.pack("<I", len(g.records))
            out += struct.pack("<H", g.groupID)
            for rec in g.records:
                _build_record(out, rec)

        out += struct.pack("<Q", self.trail_padding)
        out += struct.pack("<I", len(self.trails))
        for t in self.trails:
            out += struct.pack("<iII", t.trailID, t.blockID, t.recordID)
        out += self.epvPath.encode("utf-8") + b"\x00"
        out += struct.pack("<b", self.trail_one)
        out += struct.pack("<I", self.trail_null)
        return bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# 解析 / 构建 helper
# ─────────────────────────────────────────────────────────────────────────────

def _read_cstring(data: bytes, pos: int) -> Tuple[str, int]:
    end = data.index(b"\x00", pos)
    s = data[pos:end].decode("utf-8")
    return s, end + 1


def _parse_record(data: bytes, pos: int) -> Tuple[EPVRecord, int]:
    packed_path = []
    for _ in range(4):
        s, pos = _read_cstring(data, pos)
        packed_path.append(s)

    padding, unknownID = struct.unpack_from("<ii", data, pos); pos += 8
    (recordID,) = struct.unpack_from("<H", data, pos); pos += 2

    pb1, pos = _parse_pb1(data, pos)

    position = struct.unpack_from("<3f", data, pos); pos += 12
    positionJitter = struct.unpack_from("<3f", data, pos); pos += 12
    rotation = struct.unpack_from("<3f", data, pos); pos += 12
    rotationJitter = struct.unpack_from("<3f", data, pos); pos += 12

    paramW3 = struct.unpack_from("<2i", data, pos); pos += 8
    (boneID,) = struct.unpack_from("<i", data, pos); pos += 4
    paramW4 = struct.unpack_from("<3i", data, pos); pos += 12

    epvColor = []
    for _ in range(8):
        col, pos = _parse_color(data, pos)
        epvColor.append(col)

    paramW5 = struct.unpack_from("<2f", data, pos); pos += 8
    pb2, pos = _parse_pb2(data, pos)
    paramV = struct.unpack_from("<4i", data, pos); pos += 16

    rec = EPVRecord(
        packed_path=packed_path,
        padding=padding,
        unknownID=unknownID,
        recordID=recordID,
        parameterBlock1=pb1,
        position=position,
        positionJitter=positionJitter,
        rotation=rotation,
        rotationJitter=rotationJitter,
        paramW3=paramW3,
        boneID=boneID,
        paramW4=paramW4,
        epvColor=epvColor,
        paramW5=paramW5,
        parameterBlock2=pb2,
        paramV=paramV,
    )
    return rec, pos


def _build_record(out: bytearray, rec: EPVRecord) -> None:
    pp = list(rec.packed_path) + ["", "", "", ""]
    for s in pp[:4]:
        out += s.encode("utf-8") + b"\x00"
    out += struct.pack("<ii", rec.padding, rec.unknownID)
    out += struct.pack("<H", rec.recordID)
    _build_pb1(out, rec.parameterBlock1)
    out += struct.pack("<3f", *rec.position)
    out += struct.pack("<3f", *rec.positionJitter)
    out += struct.pack("<3f", *rec.rotation)
    out += struct.pack("<3f", *rec.rotationJitter)
    out += struct.pack("<2i", *rec.paramW3)
    out += struct.pack("<i", rec.boneID)
    out += struct.pack("<3i", *rec.paramW4)
    cols = list(rec.epvColor) + [EPVColor() for _ in range(8)]
    for col in cols[:8]:
        _build_color(out, col)
    out += struct.pack("<2f", *rec.paramW5)
    _build_pb2(out, rec.parameterBlock2)
    out += struct.pack("<4i", *rec.paramV)


def _parse_pb1(data: bytes, pos: int) -> Tuple[ParameterBlock1, int]:
    paramU0 = struct.unpack_from("<3i", data, pos); pos += 12
    (paramU1,) = struct.unpack_from("<f", data, pos); pos += 4
    paramU2 = struct.unpack_from("<4i", data, pos); pos += 16
    EFXSubIndex = struct.unpack_from("<2h", data, pos); pos += 4
    paramU3 = struct.unpack_from("<2h", data, pos); pos += 4
    EFXSubIndex2 = struct.unpack_from("<2h", data, pos); pos += 4
    paramU4 = struct.unpack_from("<2h", data, pos); pos += 4
    return ParameterBlock1(
        paramU0=paramU0, paramU1=paramU1, paramU2=paramU2,
        EFXSubIndex=EFXSubIndex, paramU3=paramU3,
        EFXSubIndex2=EFXSubIndex2, paramU4=paramU4,
    ), pos


def _build_pb1(out: bytearray, pb: ParameterBlock1) -> None:
    out += struct.pack("<3i", *pb.paramU0)
    out += struct.pack("<f", pb.paramU1)
    out += struct.pack("<4i", *pb.paramU2)
    out += struct.pack("<2h", *pb.EFXSubIndex)
    out += struct.pack("<2h", *pb.paramU3)
    out += struct.pack("<2h", *pb.EFXSubIndex2)
    out += struct.pack("<2h", *pb.paramU4)


def _parse_pb2(data: bytes, pos: int) -> Tuple[ParameterBlock2, int]:
    (f1,) = struct.unpack_from("<f", data, pos); pos += 4
    b1, b2, b3, b4 = struct.unpack_from("<4b", data, pos); pos += 4
    (i1,) = struct.unpack_from("<i", data, pos); pos += 4
    (f2,) = struct.unpack_from("<f", data, pos); pos += 4
    i2, i3 = struct.unpack_from("<2i", data, pos); pos += 8
    return ParameterBlock2(f1=f1, b1=b1, b2=b2, b3=b3, b4=b4, i1=i1, f2=f2, i2=i2, i3=i3), pos


def _build_pb2(out: bytearray, pb: ParameterBlock2) -> None:
    out += struct.pack("<f", pb.f1)
    out += struct.pack("<4b", pb.b1, pb.b2, pb.b3, pb.b4)
    out += struct.pack("<i", pb.i1)
    out += struct.pack("<f", pb.f2)
    out += struct.pack("<2i", pb.i2, pb.i3)


def _parse_color(data: bytes, pos: int) -> Tuple[EPVColor, int]:
    (efxslot,) = struct.unpack_from("<i", data, pos); pos += 4
    hexcolor = struct.unpack_from("<4B", data, pos); pos += 4
    (saturation,) = struct.unpack_from("<f", data, pos); pos += 4
    (size,) = struct.unpack_from("<i", data, pos); pos += 4
    (frequency,) = struct.unpack_from("<f", data, pos); pos += 4
    return EPVColor(
        efxslot=efxslot, hexcolor=hexcolor,
        saturation=saturation, size=size, frequency=frequency,
    ), pos


def _build_color(out: bytearray, col: EPVColor) -> None:
    out += struct.pack("<i", col.efxslot)
    out += struct.pack("<4B", *col.hexcolor)
    out += struct.pack("<f", col.saturation)
    out += struct.pack("<i", col.size)
    out += struct.pack("<f", col.frequency)
