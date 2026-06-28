"""
efx_format/timl_meta.py  —  TIML 头部元字段的轻量解析 + 原地编辑（纯 Python，零 bpy）

定位
----
TIML 整体过去刻意当 opaque（详细 4 层 offset 间接寻址的关键帧树交给 FreeKinetics）。
本模块**只解析到能定位每条 animation 的 TIML_Data**，不展开 Type/Transform/Keyframe 树，
用于读写三个头部元字段：

  - animationLength (float, TIML_Data +24)
  - loopStartPoint  (float, TIML_Data +28)
  - loopControl     (int32, TIML_Data +32)

**关键性质**：这三个字段都定长 4 字节，改它们**不改 timl 总长度**——故 set_* 是原地 patch
（struct.pack_into 回等长 bytes），与"hex 同长覆盖"同性质，**完全不碰 byte-perfect 底线，
无需任何 offset 重算或 16 字节对齐**（那是增删关键帧才需要的，本模块不做）。

animationLength 的"自动=最后关键帧"需要走到 Keyframe 层取 max(frameTiming)，故本模块也提供
一个**只读**的 `last_keyframe_time(...)`，沿 TIML_Data→Type→Transform→Keyframe 走一遍。

字节结构（三方确认：refs/EFX_TIML.bt + FK struct/EFX_Timl.py + Raw_TIML.py）
---------------------------------------------------------------------------
    base = 'timl' 起点（= timl_bytes[0]）
    +0   "timl"                              (4)
    +4   const [402786304,402786304,0]       (12)
    +16  enabled int32  (0x20=启用)          (4)
    +20  NULL int32                          (4)
    +24  count int32   (animation 条数)       (4)
    +28  countNull int32 (仅 count>0 时存在)  (4)
    +32  animations[count]: 每条 = int64 offset
            offset!=0 → base+offset 处是 TIML_Data:
              +0  offset(i64) +8 count(i64)
              +16 typeIndex(i32) +20 metadataIndex(i32)
              +24 animationLength(f32)  +28 loopStartPoint(f32)
              +32 loopControl(i32)      +36 labelHash(u32)
                每个 TIML_Type:
                  +0 offset(i64) +8 count(i64) +16 timelineParamHash(u32) +20 NULL(i32)
                    每个 TIML_Transform:
                      +0 offset(i64) +8 count(i64) +16 datatypeHash(u32) +20 dataType(i32)
                        每个 TIML_Keyframe (定长 20 字节):
                          +0 data(f32/i32) +4 bounceFwd(f32) +8 bounceBwd(f32)
                          +12 frameTiming(f32) +16 interp1(i16) +18 dataType(i16)

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；long=4 字节，int64=8，全小端。
"""

import struct
from dataclasses import dataclass
from typing import List, Optional

_TIML_MAGIC = b"timl"

# loopControl 已知取值（仅观测到 0~3）。0/2 单次，1/3 循环（疑 bit0=loop）。
LOOP_CONTROL_VALUES = {
    0: "No Loop",
    1: "Loop",
    2: "Unkn",
    3: "Unkn Loop",
}

# TIML_Data 内字段相对偏移
_DATA_ANIMLEN_OFF = 24   # float
_DATA_LOOPSTART_OFF = 28  # float
_DATA_LOOPCTRL_OFF = 32   # int32

_KEYFRAME_SIZE = 20
_KEYFRAME_FRAMETIMING_OFF = 12  # float


@dataclass
class TimlAnimation:
    """一条 TIML animation 的头部元信息（指向其 TIML_Data 的绝对偏移 + 当前字段值）。"""
    index: int               # animations[] 中的序号
    data_offset: int         # TIML_Data 在 timl_bytes 内的绝对偏移（0 = 空动画，无 TIML_Data）
    animation_length: float
    loop_start_point: float
    loop_control: int
    label_hash: int


def is_timl(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == _TIML_MAGIC


def _header_count_and_anim_base(data: bytes):
    """返回 (count, anim_array_offset)。非法/空返回 (0, None)。"""
    if not is_timl(data) or len(data) < 28:
        return 0, None
    count = struct.unpack_from("<i", data, 24)[0]
    if count <= 0:
        return 0, None
    # count>0 时多一个 countNull(int32)，animations[] 从 +32 开始
    return count, 32


def parse_animations(data: bytes) -> List[TimlAnimation]:
    """解析所有 animation 的头部元字段（不展开关键帧树）。空/非 timl 返回 []。"""
    count, anim_base = _header_count_and_anim_base(data)
    if anim_base is None:
        return []
    out = []
    for i in range(count):
        ptr_off = anim_base + i * 8
        if ptr_off + 8 > len(data):
            break
        data_offset = struct.unpack_from("<q", data, ptr_off)[0]
        if data_offset <= 0 or data_offset + 40 > len(data):
            # 空动画（offset==0）或越界：记一条占位，字段取默认
            out.append(TimlAnimation(i, 0, 0.0, 0.0, 0, 0))
            continue
        anim_len = struct.unpack_from("<f", data, data_offset + _DATA_ANIMLEN_OFF)[0]
        loop_start = struct.unpack_from("<f", data, data_offset + _DATA_LOOPSTART_OFF)[0]
        loop_ctrl = struct.unpack_from("<i", data, data_offset + _DATA_LOOPCTRL_OFF)[0]
        label_hash = struct.unpack_from("<I", data, data_offset + 36)[0]
        out.append(TimlAnimation(i, data_offset, anim_len, loop_start, loop_ctrl, label_hash))
    return out


def _animation_data_offset(data: bytes, anim_index: int) -> Optional[int]:
    """取第 anim_index 条 animation 的 TIML_Data 绝对偏移；空/越界返回 None。"""
    count, anim_base = _header_count_and_anim_base(data)
    if anim_base is None or not (0 <= anim_index < count):
        return None
    ptr_off = anim_base + anim_index * 8
    if ptr_off + 8 > len(data):
        return None
    data_offset = struct.unpack_from("<q", data, ptr_off)[0]
    if data_offset <= 0 or data_offset + 40 > len(data):
        return None
    return data_offset


# ─────────────────────────────────────────────────────────────────────────────
# 原地写（length-stable）
# ─────────────────────────────────────────────────────────────────────────────

def set_animation_length(data: bytes, anim_index: int, value: float) -> bytes:
    """原地写 animationLength。返回等长 bytes；无法定位则原样返回。"""
    off = _animation_data_offset(data, anim_index)
    if off is None:
        return data
    buf = bytearray(data)
    struct.pack_into("<f", buf, off + _DATA_ANIMLEN_OFF, float(value))
    return bytes(buf)


def set_loop_start_point(data: bytes, anim_index: int, value: float) -> bytes:
    off = _animation_data_offset(data, anim_index)
    if off is None:
        return data
    buf = bytearray(data)
    struct.pack_into("<f", buf, off + _DATA_LOOPSTART_OFF, float(value))
    return bytes(buf)


def set_loop_control(data: bytes, anim_index: int, value: int) -> bytes:
    off = _animation_data_offset(data, anim_index)
    if off is None:
        return data
    buf = bytearray(data)
    struct.pack_into("<i", buf, off + _DATA_LOOPCTRL_OFF, int(value))
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# 只读：走到 Keyframe 层取最后一帧时间（用于 animationLength 自动重算）
# ─────────────────────────────────────────────────────────────────────────────

def auto_grow_lengths(data: bytes) -> bytes:
    """对每条 animation 应用 grow-only：若最后关键帧时间 > 当前 animationLength，则增长到它。

    **只增不减**——保留官方动画末尾的 hold 帧（语料 6157 条里约 60% animLen>lastKf）。
    无关键帧/无法定位的动画跳过。返回（可能改动的）等长 bytes。
    """
    anims = parse_animations(data)
    out = data
    for a in anims:
        if a.data_offset == 0:
            continue
        lk = last_keyframe_time(out, a.index)
        if lk is not None and lk > a.animation_length:
            out = set_animation_length(out, a.index, lk)
    return out


def last_keyframe_time(data: bytes, anim_index: int) -> Optional[float]:
    """该 animation 下所有 transform 的全部关键帧里 max(frameTiming)。无关键帧返回 None。

    沿 TIML_Data → Type[count] → Transform[count] → Keyframe[count].frameTiming 走一遍。
    各层 offset 均相对 timl base（= data[0]）。越界即静默跳过该分支（只读，不抛）。
    """
    data_off = _animation_data_offset(data, anim_index)
    if data_off is None:
        return None
    n = len(data)
    best = None

    def _read_children(struct_off):
        # 通用：读一个 (offset i64, count i64) 头，返回 (child_base, child_count) 或 None
        if struct_off < 0 or struct_off + 16 > n:
            return None
        rel = struct.unpack_from("<q", data, struct_off)[0]
        cnt = struct.unpack_from("<q", data, struct_off + 8)[0]
        if rel <= 0 or cnt <= 0:
            return None
        return rel, cnt

    types = _read_children(data_off)
    if types is None:
        return None
    type_base, type_count = types
    for ti in range(type_count):
        type_off = type_base + ti * 24   # TIML_Type = 24 字节
        transforms = _read_children(type_off)
        if transforms is None:
            continue
        tf_base, tf_count = transforms
        for fi in range(tf_count):
            tf_off = tf_base + fi * 24   # TIML_Transform = 24 字节
            kfs = _read_children(tf_off)
            if kfs is None:
                continue
            kf_base, kf_count = kfs
            for ki in range(kf_count):
                ft_off = kf_base + ki * _KEYFRAME_SIZE + _KEYFRAME_FRAMETIMING_OFF
                if ft_off + 4 > n:
                    continue
                ft = struct.unpack_from("<f", data, ft_off)[0]
                if best is None or ft > best:
                    best = ft
    return best
