"""
efx_format/timl.py  —  TIML 完整 4 层树解析 + 序列化（纯 Python，零 bpy）

定位
----
[[timl_meta.py]] 只解析 TIML 头部三字段（animationLength/loopControl/loopStartPoint）做原地
patch。本模块解析**完整 4 层关键帧树**，供「自建 TIML 编辑体系」（不依赖任何外部工具）
的核心层使用：

    TIML
      └─ animations[≤2]            animation0=粒子发射轴 / animation1=粒子更新(寿命)轴
           └─ TimlData             (animationLength / loopControl / labelHash …)
                └─ types[]         timelineParameterHash（影响哪个对象：mesh/material…）
                     └─ transforms[]  datatypeHash + dataType（哪个属性：pos:X / rot:Z / 颜色 / flag）
                          └─ keyframes[]  value + frameTiming + interp（20 字节定长）

实测结论（语料 6157 个 animation，见 PROGRESS）：永远只有这 4 层（无更深嵌套、无环、无共享
节点），只有**扇出数量**变化（types≤4 / transforms≤9 / keyframes≤27）。故 TIML 不需要节点图，
是一棵纯包含树。

byte-perfect 策略（与本仓库 labels_dirty / eof_dirty / opaque 一致）
-------------------------------------------------------------------
- 解析时**保留原始字节** `raw`。
- `serialize()`：未编辑（`dirty=False`）→ 原样回吐 raw → **100% byte-perfect**。
  已编辑 → 结构化重建（16 字节对齐布局）。
- 全语料实测：clean 路径 6095/6095 byte-perfect；结构化重建对常规布局 ~99% 字节吻合，
  极少数文件（~0.9%）头部 dataHeaders 偏移异常 + 含「未被引用的死数据」（按游戏读法
  dataHeaders@32 即为空动画），重建会丢死字节——这类只要不编辑就走 verbatim，无损。

字节结构（权威：refs/EFX_TIML.bt（010 BT 模板）+ 实测）
--------------------------------------------------------------------------
    Header(28B): timl[4] signature[3×i32]=(402786304,402786304,0)恒定 enabled(i32)=32
                 NULL(i32)=0 count(u32@24)
    （2026-07-01 用 232 个真实 TIML 头核对修正：signature 是 3 个 int32、非 8 字节；
    enabled 是 i32=32 不是 i64；NULL 紧跟在 enabled 后面。之前的字段切法凑够 28 字节但
    顺序/宽度全错——parse_timl 只把这段当不透明字节存，真实文件不受影响，但
    make_blank_timl() 曾经按错误切法手填这些字节，导致新建的 TIML 游戏内不生效。）
    → align16 → dataHeaders: uint64[count]（各 animation 的 Data 绝对偏移，0=空）
    → align16 → 各 Data 结构（按 BT 模板 TIML_Data 布局顺序）：
        [pad16] Data(40B) [pad16] 所有 type 头(24B×) [pad16]
        每 type 的 transform 头(24B×)+[pad16]
        每 transform 的 keyframe(20B×)+[pad16]（末尾 pad 去掉）
    Data(40B): offset(i64) count(i64) dataIx0(i32) dataIx1(i32) animLen(f) loopStart(f) loopControl(i32) labelHash(u32)
    Type(24B): offset(i64) count(i64) timelineParameterHash(u32) NULL(i32)
    Transform(24B): offset(i64) count(i64) datatypeHash(u32) dataType(i32)
    Keyframe(20B): value(4) controlL(i32) controlR(i32) frameTiming(f) transition(i16) dataType(i16)
    所有 offset 相对 timl 起点。dataType: 0=SInt 1=Int 2=Float 3=Color(ubyte[4]) 4=Bool。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；long=4B/int64=8B，全小端。
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .hashes import jamcrc
from .timl_names import DT_TRANSFORM

_MAGIC = b"timl"

# 各结构定长
_HEADER_SIZE = 28
_DATA_SIZE = 40
_TYPE_SIZE = 24
_TRANSFORM_SIZE = 24
_KEYFRAME_SIZE = 20

# dataType → 友好名
DATATYPE_NAMES = {0: "SInt", 1: "Int", 2: "Float", 3: "Color", 4: "Bool"}
# transition（= easingMethod，插值方式）整数 → 友好名（仅显示用）。
# 权威：refs/EFX_Crimson.bt 的 easingMethod 注释（0-Binary/Stuck, 1-Constant,
# 2-Linear, 3-Quadratic, 4-Cubic）+ refs/EFX_TIML.bt 记录的合法值范围
# （Float/Color dataType 合法值 [0,1,2,3,4]，与 Crimson 的 0-4 恰好吻合）。
# 5/6 仅在 Int/Flag dataType 出现（合法值 [1,4,5,6]），语义未确认。
# ⚠ 旧表 ["CONSTANT","LINEAR","QUAD","CUBIC","QUART","EXPO","SINE"] 整个错位一格，
#   会把 Blender 的「二次(QUAD)」写成整数 2，而游戏里 2=Linear → 表现为「设二次得线性」。
INTERP_NAMES = ["STUCK", "CONSTANT", "LINEAR", "QUAD", "CUBIC", "UNK5", "UNK6"]

# datatypeHash ∈ BIG_FLAGS → 该 transform 是「标志位」通道，value/controlL/controlR
# 各按低/高 16 位拆成 2 条子通道（标志位 hash 表）。
BIG_FLAGS = frozenset({
    150806694, 2575924291, 4027018852, 2154666731, 4150962813,
    1852046279, 503910216, 1762541534, 2768909048, 3787782803,
})


def channel_sublabels(data_type: int, datatype_hash: int) -> List[str]:
    """该 transform 拆成几条可编辑子通道及其标签：
    Color(dataType3) → R/G/B/A；标志位(hash∈BIG_FLAGS) → lo/hi；其余 → 单通道。"""
    if data_type == 3:
        return ["R", "G", "B", "A"]
    if datatype_hash in BIG_FLAGS:
        return ["lo", "hi"]
    return [""]


def _val_fmt(data_type: int) -> str:
    """单值字段的 struct 格式（标量通道用；Color/Flag 另行处理）。"""
    return {0: "<i", 1: "<I", 2: "<f", 4: "<I"}.get(data_type, "<i")


def decode_keyframe(raw: bytes, data_type: int, datatype_hash: int) -> dict:
    """把 20 字节关键帧解码成可编辑结构：
        {frame, transition, kf_dtype, subs:[{value, back, period}, ...]}
    subs 按 channel_sublabels 顺序。value/back(controlL)/period(controlR) 已按
    dataType/flag 语义解出（Color=0-255 各通道、Flag=低/高 16 位、标量=int/float）。"""
    frame = struct.unpack_from("<f", raw, 12)[0]
    transition = struct.unpack_from("<h", raw, 16)[0]
    kf_dtype = struct.unpack_from("<h", raw, 18)[0]
    vraw, lraw, rraw = raw[0:4], raw[4:8], raw[8:12]
    if data_type == 3:
        back = struct.unpack("<f", lraw)[0]
        period = struct.unpack("<f", rraw)[0]
        subs = [{"value": vraw[i], "back": back, "period": period} for i in range(4)]
    elif datatype_hash in BIG_FLAGS:
        v = struct.unpack("<I", vraw)[0]
        cl = struct.unpack("<I", lraw)[0]
        cr = struct.unpack("<I", rraw)[0]
        subs = [
            {"value": v & 0xFFFF, "back": cl & 0xFFFF, "period": cr & 0xFFFF},
            {"value": (v >> 16) & 0xFFFF, "back": (cl >> 16) & 0xFFFF, "period": (cr >> 16) & 0xFFFF},
        ]
    else:
        fmt = _val_fmt(data_type)
        v = struct.unpack(fmt, vraw)[0]
        cl = struct.unpack(fmt, lraw)[0]
        cr = struct.unpack(fmt, rraw)[0]
        subs = [{"value": v, "back": cl, "period": cr}]
    return {"frame": frame, "transition": transition, "kf_dtype": kf_dtype, "subs": subs}


def _u32_bits(data_type: int, x) -> int:
    """把单值按 dataType 转成 32 位字节模式（float→IEEE 位，int→截断）。"""
    if data_type == 2:
        return struct.unpack("<I", struct.pack("<f", float(x)))[0]
    return int(round(x)) & 0xFFFFFFFF


def encode_keyframe(data_type: int, datatype_hash: int, frame: float,
                    transition: int, kf_dtype: int, subs: List[dict]) -> bytes:
    """decode_keyframe 的逆：重建 20 字节关键帧。subs 长度须与 channel_sublabels 一致。"""
    if data_type == 3:
        vb = bytes(int(round(subs[i]["value"])) & 0xFF for i in range(4))
        lraw = struct.pack("<f", float(subs[0]["back"]))
        rraw = struct.pack("<f", float(subs[0]["period"]))
        vraw = vb
    elif datatype_hash in BIG_FLAGS:
        lo, hi = subs[0], subs[1]
        v = (int(round(lo["value"])) & 0xFFFF) | ((int(round(hi["value"])) & 0xFFFF) << 16)
        cl = (int(round(lo["back"])) & 0xFFFF) | ((int(round(hi["back"])) & 0xFFFF) << 16)
        cr = (int(round(lo["period"])) & 0xFFFF) | ((int(round(hi["period"])) & 0xFFFF) << 16)
        vraw = struct.pack("<I", v); lraw = struct.pack("<I", cl); rraw = struct.pack("<I", cr)
    else:
        s = subs[0]
        vraw = struct.pack("<I", _u32_bits(data_type, s["value"]))
        lraw = struct.pack("<I", _u32_bits(data_type, s["back"]))
        rraw = struct.pack("<I", _u32_bits(data_type, s["period"]))
    return (vraw + lraw + rraw + struct.pack("<f", float(frame))
            + struct.pack("<h", int(transition)) + struct.pack("<h", int(kf_dtype)))


def _align16(pos: int) -> int:
    return (pos + 15) & ~15


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TimlKeyframe:
    """一个关键帧（20 字节定长）。value 按所属 transform 的 dataType 解释。"""
    raw: bytes                 # 原始 20 字节（byte-perfect 兜底 + 未解码字段保真）
    frame_timing: float = 0.0
    transition: int = 0        # 插值类型（见 INTERP_NAMES）
    data_type: int = 0         # 与所属 transform.dataType 一致

    @property
    def interp_name(self) -> str:
        return INTERP_NAMES[self.transition] if 0 <= self.transition < len(INTERP_NAMES) else "?"

    def serialize(self) -> bytes:
        return self.raw


@dataclass
class TimlTransform:
    """一条属性子通道（datatypeHash，如 pos:X / 颜色 / flag）。"""
    datatype_hash: int = 0
    data_type: int = 0
    keyframes: List[TimlKeyframe] = field(default_factory=list)


@dataclass
class TimlType:
    """一个 timelineParameter 通道（影响哪个对象）。"""
    timeline_param_hash: int = 0
    null: int = 0
    transforms: List[TimlTransform] = field(default_factory=list)


@dataclass
class TimlData:
    """一条 animation 的数据（animation0=发射轴 / animation1=更新寿命轴）。"""
    anim_index: int = 0        # 在 dataHeaders 中的槽位（animation id）
    data_ix0: int = 0
    data_ix1: int = 0
    animation_length: float = 0.0
    loop_start_point: float = 0.0
    loop_control: int = 0
    label_hash: int = 0
    types: List[TimlType] = field(default_factory=list)


@dataclass
class Timl:
    """整个 TIML 块。`raw` 保留原始字节；未编辑序列化走 verbatim。"""
    raw: bytes
    header: bytes              # 原始 header[0:28]，verbatim 保留 signature/enabled
    count: int = 0             # dataHeaders 槽位数（= animation 槽位数，含空槽）
    animations: List[Optional[TimlData]] = field(default_factory=list)  # 槽位序，空槽=None
    dirty: bool = False        # True=结构变（增删 type/transform/keyframe）→ 重建

    # ── 序列化 ────────────────────────────────────────────────────────────────
    def serialize(self) -> bytes:
        """未编辑 → 原样回吐（byte-perfect）；已编辑 → 结构化重建。"""
        if not self.dirty:
            return self.raw
        return self._rebuild()

    def _header_bytes(self) -> bytes:
        """原始 28 字节 header，但把 count(@24,uint32) patch 成当前 self.count
        （animation 增删后 count 变，header 须同步，否则 dataHeaders 数对不上）。"""
        return self.header[:24] + struct.pack("<I", self.count & 0xFFFFFFFF)

    def _rebuild(self) -> bytes:
        """结构化重建（BT 模板布局 + 16 字节对齐）。"""
        datas = [d for d in self.animations if d is not None]
        if self.count == 0 or not datas:
            # 空 TIML：header(count 同步) + 对齐填充
            return self._header_bytes() + b"\x00" * (_align16(_HEADER_SIZE) - _HEADER_SIZE)

        # —— pass 1：按 BT 模板布局顺序排布、计算每个结构的绝对偏移 ——
        # 布局项：('pad',) / ('data',d) / ('type',t) / ('tf',f) / ('kfg',f)
        items = []
        items.append(("hdr", None))
        items.append(("pad", None))
        items.append(("dh", None))
        for d in self.animations:           # 含空槽（None）→ 只占 dataHeaders 一个 0
            if d is None:
                continue
            items.append(("pad", None))
            items.append(("pad", None))     # 循环的 pad + 布局起始 pad（连续两 pad，第二个为 0）
            items.append(("data", d))
            items.append(("pad", None))
            for t in d.types:
                items.append(("type", t))
            items.append(("pad", None))
            for t in d.types:
                for f in t.transforms:
                    items.append(("tf", f))
                items.append(("pad", None))
            for t in d.types:
                for f in t.transforms:
                    items.append(("kfg", f))
                    items.append(("pad", None))
            if items and items[-1][0] == "pad":
                items.pop()                 # 去掉最后一个关键帧 pad（与 BT 布局一致）

        # 分配偏移
        pos = 0
        offmap = {}                          # id(obj) → 绝对偏移
        for kind, obj in items:
            if kind == "pad":
                pos = _align16(pos)
                continue
            if kind == "hdr":
                pos += _HEADER_SIZE
            elif kind == "dh":
                pos += self.count * 8
            elif kind == "data":
                offmap[("data", id(obj))] = pos; pos += _DATA_SIZE
            elif kind == "type":
                offmap[("type", id(obj))] = pos; pos += _TYPE_SIZE
            elif kind == "tf":
                offmap[("tf", id(obj))] = pos; pos += _TRANSFORM_SIZE
            elif kind == "kfg":
                offmap[("kfg", id(obj))] = pos; pos += _KEYFRAME_SIZE * len(obj.keyframes)

        # —— pass 2：发射字节，回填各结构的 offset 字段 ——
        out = bytearray()
        for kind, obj in items:
            if kind == "pad":
                out += b"\x00" * (_align16(len(out)) - len(out))
            elif kind == "hdr":
                out += self._header_bytes()
            elif kind == "dh":
                for d in self.animations:
                    out += struct.pack("<q", offmap[("data", id(d))] if d is not None else 0)
            elif kind == "data":
                first_type_off = offmap[("type", id(obj.types[0]))] if obj.types else 0
                lbl = obj.label_hash if obj.types else 0
                out += struct.pack("<qqiiffiI", first_type_off, len(obj.types),
                                   obj.data_ix0, obj.data_ix1, obj.animation_length,
                                   obj.loop_start_point, obj.loop_control, lbl)
            elif kind == "type":
                first_tf_off = offmap[("tf", id(obj.transforms[0]))] if obj.transforms else 0
                out += struct.pack("<qqIi", first_tf_off, len(obj.transforms),
                                   obj.timeline_param_hash, obj.null)
            elif kind == "tf":
                kf_off = offmap[("kfg", id(obj))] if obj.keyframes else 0
                out += struct.pack("<qqIi", kf_off, len(obj.keyframes),
                                   obj.datatype_hash, obj.data_type)
            elif kind == "kfg":
                for kf in obj.keyframes:
                    out += kf.serialize()
        return bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# 解析
# ─────────────────────────────────────────────────────────────────────────────

def make_blank_timl() -> bytes:
    """生成最小合法 TIML 字节（count=0，32 字节）作为从头新建的起点。
    可在此基础上用 enable_axis 启用轴、再用 add_transform 添加轨道。

    header 中间 20 字节（signature/enabled/NULL）不是随便填的占位——2026-07-01 用
    232 个真实 TIML 头核对：signature（3×int32）恒为 (402786304, 402786304, 0)，
    enabled（int32）恒为 32，NULL（int32）恒为 0，全语料无一例外。之前这里错填成
    全零 signature + 顺序/宽度都错的 enabled/NULL，游戏引擎会拒绝识别，新建的 TIML
    完全不生效——parse_timl 对真实文件只是把这段当不透明字节保留，从没验证过具体
    数值，所以这个 bug 一直没被现有 roundtrip 测试发现。"""
    header = (
        _MAGIC                                          # b"timl"  [4]
        + struct.pack("<3i", 402786304, 402786304, 0)    # signature [12]，全语料恒定
        + struct.pack("<i", 32)                          # enabled  [4]，全语料恒定 = 0x20
        + struct.pack("<i", 0)                           # NULL     [4]，全语料恒定
        + struct.pack("<I", 0)                           # count=0  [4]
    )  # = _HEADER_SIZE = 28 bytes
    return header + b"\x00" * (_align16(_HEADER_SIZE) - _HEADER_SIZE)  # → 32 bytes


def is_timl(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == _MAGIC


def parse_timl(data: bytes) -> Optional[Timl]:
    """解析完整 TIML 树。非 timl 返回 None。

    指针读法与游戏一致（dataHeaders @32，各级按 offset 字段间接寻址）。保留 raw
    供 byte-perfect verbatim。极少数文件 dataHeaders@32 为 0 但含未引用死数据 → 按空动画
    解析（与游戏一致），死字节由 raw verbatim 保留。
    """
    if not is_timl(data):
        return None
    count = struct.unpack_from("<I", data, 24)[0]
    timl = Timl(raw=bytes(data), header=bytes(data[:_HEADER_SIZE]), count=count)
    if count == 0:
        return timl

    dh_base = _align16(_HEADER_SIZE)         # 32
    n = len(data)
    for ai in range(count):
        ptr = dh_base + ai * 8
        if ptr + 8 > n:
            timl.animations.append(None); continue
        data_off = struct.unpack_from("<q", data, ptr)[0]
        if data_off <= 0 or data_off + _DATA_SIZE > n:
            timl.animations.append(None); continue
        timl.animations.append(_parse_data(data, data_off, ai, n))
    return timl


def _parse_data(data: bytes, off: int, anim_index: int, n: int) -> TimlData:
    type_off, type_count, ix0, ix1, animlen, loopstart, loopctrl, lblhash = \
        struct.unpack_from("<qqiiffiI", data, off)
    d = TimlData(anim_index=anim_index, data_ix0=ix0, data_ix1=ix1,
                 animation_length=animlen, loop_start_point=loopstart,
                 loop_control=loopctrl, label_hash=lblhash)
    if type_off <= 0 or type_count <= 0:
        return d
    for ti in range(type_count):
        toff = type_off + ti * _TYPE_SIZE
        if toff + _TYPE_SIZE > n:
            break
        d.types.append(_parse_type(data, toff, n))
    return d


def _parse_type(data: bytes, off: int, n: int) -> TimlType:
    tf_off, tf_count, tlp_hash, null = struct.unpack_from("<qqIi", data, off)
    t = TimlType(timeline_param_hash=tlp_hash, null=null)
    if tf_off <= 0 or tf_count <= 0:
        return t
    for fi in range(tf_count):
        foff = tf_off + fi * _TRANSFORM_SIZE
        if foff + _TRANSFORM_SIZE > n:
            break
        t.transforms.append(_parse_transform(data, foff, n))
    return t


def _parse_transform(data: bytes, off: int, n: int) -> TimlTransform:
    kf_off, kf_count, dt_hash, dtype = struct.unpack_from("<qqIi", data, off)
    f = TimlTransform(datatype_hash=dt_hash, data_type=dtype)
    if kf_off <= 0 or kf_count <= 0:
        return f
    for ki in range(kf_count):
        koff = kf_off + ki * _KEYFRAME_SIZE
        if koff + _KEYFRAME_SIZE > n:
            break
        raw = bytes(data[koff:koff + _KEYFRAME_SIZE])
        ft = struct.unpack_from("<f", raw, 12)[0]
        trans, kdt = struct.unpack_from("<hh", raw, 16)
        f.keyframes.append(TimlKeyframe(raw=raw, frame_timing=ft, transition=trans, data_type=kdt))
    return f


# ─────────────────────────────────────────────────────────────────────────────
# 轨道增删复制（供 Blender 胶水层调用；timl.dirty=True 门控序列化走重建）
# ─────────────────────────────────────────────────────────────────────────────

# label_hash / data_ix0 / data_ix1 的 dataclass 默认值是 0，但 2026-07-01 用 6180 条
# 真实 animation 核对：label_hash 恒非 0（0/6180），同一 TIML 内 A0/A1 两条轴的
# label_hash 恒不相同（0/116 相同）；data_ix0/data_ix1 也恒非 0（min=1）。具体数值
# 看起来是原作者工具里任意的曲线/剪辑书签（同一 hash 会被完全不同的 body 复用，
# 如全语料最高频的一个 label_hash 出现在 267 个语义无关的文件里），推测引擎不校验
# 具体数值、但把 0 当"未初始化"处理而跳过——从零新建的 TimlData 若留 0 默认值，
# 很可能是"新建 TIML / 新增轨道游戏内不生效"的头号嫌疑。只是从语料统计推出的
# 头号嫌疑，不是实机确认的定论，修复效果有待实机验证。
_NEW_LABEL_HASH = {0: jamcrc(b"EFX_EDITOR_NEW_TIMELINE_A0"), 1: jamcrc(b"EFX_EDITOR_NEW_TIMELINE_A1")}
_NEW_DATA_IX = (1, 2)


def make_blank_animdata(slot: int) -> "TimlData":
    """新建一条空动画数据（供 enable_axis 无源可复制 / add_transform 从零建轴使用）。
    label_hash/data_ix0/data_ix1 用非零占位值，而非 dataclass 默认的 0（见上方注释）。"""
    lbl = _NEW_LABEL_HASH.get(slot, _NEW_LABEL_HASH[0])
    return TimlData(anim_index=slot, animation_length=30.0,
                    data_ix0=_NEW_DATA_IX[0], data_ix1=_NEW_DATA_IX[1], label_hash=lbl)


def _make_default_keyframes(data_type: int, dt_hash: int,
                            anim_length: float = 30.0) -> "List[TimlKeyframe]":
    """生成两个默认关键帧（frame=0 和 frame=anim_length），作为新轨道起始内容。"""
    frames = [0.0, max(1.0, anim_length)]
    xform = DT_TRANSFORM.get(dt_hash & 0xFFFFFFFF)
    default_value = 1.0 if (xform is not None and xform[3] == "scl") else 0.0
    kfs = []
    for fr in frames:
        if data_type == 3:  # Color RGBA：白色全透
            subs = [{"value": 255, "back": 0.0, "period": 0.0} for _ in range(4)]
        else:               # Float/SInt/Int/Bool：scl 轴默认 1.0(缩放系数)，其余 0.0
            subs = [{"value": default_value, "back": 0.0, "period": 0.0}]
        raw = encode_keyframe(data_type, dt_hash, fr, 2, data_type, subs)  # transition=2=LINEAR
        kfs.append(TimlKeyframe(raw=raw, frame_timing=fr, transition=2, data_type=data_type))
    return kfs


def add_transform(timl: "Timl", slot: int, tlp_hash: int,
                  dt_hash: int, data_type: int) -> bool:
    """在 slot 轴（0=A0, 1=A1）下新增 (tlp_hash, dt_hash) 通道。
    已存在返回 False；成功返回 True 并设 timl.dirty=True。"""
    tlp_hash &= 0xFFFFFFFF
    dt_hash &= 0xFFFFFFFF
    # 补槽（None 占位，count 跟随）
    while len(timl.animations) <= slot:
        timl.animations.append(None)
    timl.count = max(timl.count, slot + 1)

    if timl.animations[slot] is None:
        timl.animations[slot] = make_blank_animdata(slot)
    anim = timl.animations[slot]
    anim.anim_index = slot

    # 查找或创建 TimlType
    tlp = None
    for t in anim.types:
        if (t.timeline_param_hash & 0xFFFFFFFF) == tlp_hash:
            tlp = t
            break
    if tlp is None:
        tlp = TimlType(timeline_param_hash=tlp_hash)
        anim.types.append(tlp)

    # 检查 dt_hash 是否已存在
    for tf in tlp.transforms:
        if (tf.datatype_hash & 0xFFFFFFFF) == dt_hash:
            return False

    anim_len = anim.animation_length if anim.animation_length > 0.0 else 30.0
    kfs = _make_default_keyframes(data_type, dt_hash, anim_len)
    tlp.transforms.append(TimlTransform(datatype_hash=dt_hash, data_type=data_type, keyframes=kfs))
    timl.dirty = True
    return True


def delete_transform(timl: "Timl", slot: int, tlp_hash: int, dt_hash: int) -> bool:
    """删除 slot 轴的 (tlp_hash, dt_hash) 通道；空 type 一并删除。返回是否找到。"""
    tlp_hash &= 0xFFFFFFFF
    dt_hash &= 0xFFFFFFFF
    if slot >= len(timl.animations) or timl.animations[slot] is None:
        return False
    anim = timl.animations[slot]
    for t in list(anim.types):
        if (t.timeline_param_hash & 0xFFFFFFFF) != tlp_hash:
            continue
        before = len(t.transforms)
        t.transforms = [tf for tf in t.transforms
                        if (tf.datatype_hash & 0xFFFFFFFF) != dt_hash]
        if len(t.transforms) < before:
            if not t.transforms:
                anim.types.remove(t)
            timl.dirty = True
            return True
    return False


def copy_transform(timl: "Timl", src_slot: int, dst_slot: int,
                   tlp_hash: int, dt_hash: int) -> bool:
    """把 src_slot 的 (tlp_hash, dt_hash) 通道（含关键帧）复制到 dst_slot；已有则覆盖。
    src 不存在返回 False。"""
    import copy as _copy
    tlp_hash &= 0xFFFFFFFF
    dt_hash &= 0xFFFFFFFF
    # 找源 transform
    if src_slot >= len(timl.animations) or timl.animations[src_slot] is None:
        return False
    src_tf = None
    for t in timl.animations[src_slot].types:
        if (t.timeline_param_hash & 0xFFFFFFFF) != tlp_hash:
            continue
        for tf in t.transforms:
            if (tf.datatype_hash & 0xFFFFFFFF) == dt_hash:
                src_tf = tf
                break
        if src_tf is not None:
            break
    if src_tf is None:
        return False

    # 先删目标（若存在）；delete_transform 会设 dirty，但我们总会再设一次
    delete_transform(timl, dst_slot, tlp_hash, dt_hash)

    # 补槽
    while len(timl.animations) <= dst_slot:
        timl.animations.append(None)
    timl.count = max(timl.count, dst_slot + 1)
    if timl.animations[dst_slot] is None:
        timl.animations[dst_slot] = make_blank_animdata(dst_slot)
    dst_anim = timl.animations[dst_slot]
    dst_anim.anim_index = dst_slot

    dst_t = None
    for t in dst_anim.types:
        if (t.timeline_param_hash & 0xFFFFFFFF) == tlp_hash:
            dst_t = t
            break
    if dst_t is None:
        dst_t = TimlType(timeline_param_hash=tlp_hash)
        dst_anim.types.append(dst_t)

    dst_t.transforms.append(_copy.deepcopy(src_tf))
    timl.dirty = True
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 自检（供 tools / 测试调用）
# ─────────────────────────────────────────────────────────────────────────────

def verify_roundtrip(data: bytes) -> bool:
    """clean 路径 byte-perfect 自检：parse → serialize（未编辑）== 原字节。"""
    t = parse_timl(data)
    if t is None:
        return False
    return t.serialize() == data
