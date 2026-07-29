# -*- coding: utf-8 -*-
"""
efx_format/custom_codecs.py — 变长 / 分派型 custom 块的手写编解码
"""
from __future__ import annotations
import struct
from typing import Any, Dict, List, Tuple

from .codec import (
    unpack, pack, _schema_size,
    _unpack_xyz, _pack_xyz, _xyz_size,
    _EPVCSLOT_FIELDS, _EPVCSLOT_SIZE, _unpack_epvcolorslot, _pack_epvcolorslot,
    _SCALAR_SIZE, _XYZ_FMT,
)
from .fields_model import Attribute, Int, Float, Enum, Bool, Bitmask, Byte, attr_from_legacy
from .enums import (
    BITS_APPLICATION_RULE, BITS_LOOPING_MODE, BITS_AFFECTED_BY_LIGHT, BITS_RIBBON_UNKN22_1,
    ENUM_BLEND_MODE, ENUM_LOOPING_ORIENTATION, ENUM_MESH_TRACKING_FLAGS, ENUM_RIBBON_MODE,
    _AXIS_DIRECTION6, _TRANSFORM_ROT_ORDER,
)
from ..hashes import *  # noqa: F401,F403  —— 各 custom 类型 hash 常量

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
    ('typeFlag',                'i'),   # 原 unkn0
    ('uvs_index',               'i'),
    ('uvsIndexJitter',          'i'),  # 原 unkn2/NULL，实测为 uvs_index 的抖动量
    ('startingFrame',           'i'),
    ('startingFrameJitter',     'i'),
    ('animationSpeed',          'f'),
    ('animationSpeedJitter',    'f'),
    ('animationAcceleration',   'f'),
    ('animationAccelerationJitter', 'f'),
    # loopingEnum（4B）按语义拆分：byte0=动画模式，byte1=贴图朝向，byte2-3=padding（恒0）。
    # 用户实机测试（2026-07-10，配合 BILLBOARD2D 当稳定测试画布）坐实 byte0 三段结构：
    # value = direction×64 + flipCode×4 + playbackMode。
    #   playbackMode（bit0-1）：0=只显示起始帧，1=循环，2=播放一次后强制消亡，
    #     3=播放一次后定格最后一帧直到 Life 结束。
    #   direction（bit6-7）：0=正向播放，1=倒放，2=正/倒随机取一种。全语料实测确认：
    #     direction=1(倒放)+flipCode=10 → 值 104~107；direction=2(随机正倒)+flipCode=
    #     0/2/10 → 值 128~131/136~139/168~171。direction=1/2 搭配其余 flipCode 值尚未测试。
    #   flipCode（bit2-5）= 两个 2 位子字段：flipHorizontal(bit2-3) + flipVertical(bit4-5)，
    #     flipCode = flipVertical×4 + flipHorizontal。每轴取值 0=不翻转 / 1=固定翻转 / 2=随机翻转
    #     （3 为非法，实际只有 0~2）。故 flipCode 有效值 = {0,1,2,4,5,6,8,9,10}；含某轴=3 的
    #     3/7/11/12/13/14/15 均为非法组合。随机项在粒子生成时取一次，循环期间不重取。
    ('loopingMode',             'B'),
    ('loopingOrientation',      'B'),   # byte1：0=正常/1=顺时针90°/2=逆时针90°/3=随机
    ('loopingPad',              'h'),   # byte2-3：保留（实测恒 0）
]  # 11 fields = 40 B

_UVSEQUENCE_FIXED_SIZE = _schema_size(_UVSEQUENCE_FIXED_SCHEMA)  # = 40

EXTERN_UVSEQUENCE_SCHEMA = _UVSEQUENCE_FIXED_SCHEMA + [
    ('unkn_tail0', 'i'),
    ('unkn_tail1', 'B'),
]
assert _schema_size(EXTERN_UVSEQUENCE_SCHEMA) == 45, \
    f"EXTERN_UVSEQUENCE_SCHEMA size mismatch: {_schema_size(EXTERN_UVSEQUENCE_SCHEMA)}"

# loopingMode 是打包字节位域，用 Bitmask + 4 个 BitEnum 段建模
# （playbackMode/flipHorizontal/flipVertical/direction），UI 经位掩码弹窗按段渲染下拉。
# codec 只读/写裸字节（1:1 恒等，byte-perfect 由构造保证）。
UVSEQUENCE_ATTR = attr_from_legacy(
    _schema_size(_UVSEQUENCE_FIXED_SCHEMA), _UVSEQUENCE_FIXED_SCHEMA,
    overrides={
        'loopingMode': Bitmask('loopingMode', BITS_LOOPING_MODE, backing='B', label_zh="循环模式"),
        'loopingOrientation': Enum('loopingOrientation', ENUM_LOOPING_ORIENTATION,
                                   backing='B', label_zh="贴图朝向"),
    },
)


def unpack_uvsequence(data: bytes, off: int = 0):
    """Unpack UVSequence data_bytes (variable-length). Returns (dict, new_off)。
    loopingMode 保持裸字节（位分解移到 UI 弹窗）。"""
    values, off = unpack(_UVSEQUENCE_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_uvsequence(values: dict) -> bytes:
    """Pack UVSequence values dict back to bytes。"""
    out = pack(_UVSEQUENCE_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Billboard3D (variable: billboard_data 108 B + extras 24 B + path)
#
# billboard_data (108 B, includes the path_len field at offset +104):
#   unkn0(4)+applicationRule(4)+XYZ color(2)(4)+XYZ colorRange(2)(4)+brightness(4)+
#   unkn2[3](12)+EPVColorSlot1(4)+SlotOverride1(4)+rotation(4)+rotationJitter(4)+
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
    ('typeFlag',                   'i'),   # 原 unkn0
    ('applicationRule',            'i'),
    ('color',                      ('XYZ', 2)),  # TIML DT 0x58689812("Color") 已确认
    ('colorRange',                 ('XYZ', 2)),  # TIML DT 0xC216C23D("ColorRange") 已确认
    ('brightness',                 'f'),  # TIML DT 0x9F1E012E("ColorRate") 已确认
    # 原 randomBrightnessMult：全语料实测取值 0~240，跟 brightness 本身(0~255)同一量级，
    # 并非 0~1 的"乘数"，是 brightness 的 jitter 一半，2026-07-30 改名（RIBBON 同款字段
    # 同理改名，见 RIBBON schema 注释）。
    ('brightnessJitter',           'f'),  # 原 randomBrightnessMult
    ('useColorRange',              'i'),  # bool
    ('blendMode',                  'i'),
    ('EPVColorSlot1',              'i'),
    ('SlotOverride1',              'i'),
    ('rotation',                   'f'),  # TIML DT 0x2FF50558("Rotation") 实机确认
    ('rotationJitter',             'f'),
    ('scale',                      'f'),  # TIML DT 0x0EBAEC37("SizeScalar") 已确认
    ('scaleJitter',                'f'),
    ('width',                      'f'),  # TIML DT 0x241CAED2("SizeX") 已确认
    ('widthJitter',                'f'),
    ('height',                     'f'),  # TIML DT 0x531B9E44("SizeY") 已确认
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
]  # = 4+4+4+4+4+12+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 104 B

_BILLBOARD3D_EXTRAS_SCHEMA = [
    ('unknEnum5', 'i'),
    # 拆分自原 uint64 unkn6：低32位=int/flag，高32位=float（实测 60842 个 BILLBOARD3D 块核对）
    ('unknFlag6_0', 'i'),
    ('unkn6_1', 'f'),
    ('unkn7', 'f'),
    ('unkn8', 'i'),
    ('unknFlag9', 'i'),
]  # = 4+8+4+4+4 = 24 B

EXTERN_BILLBOARD3D_SCHEMA = (
    _BILLBOARD3D_FIXED_SCHEMA + _BILLBOARD3D_EXTRAS_SCHEMA + [
        ('unkn_tail0', 'i'),
        ('unkn_tail1', 'B'),
    ]
)
assert _schema_size(EXTERN_BILLBOARD3D_SCHEMA) == 133, \
    f"EXTERN_BILLBOARD3D_SCHEMA size mismatch: {_schema_size(EXTERN_BILLBOARD3D_SCHEMA)}"


# applicationRule（BILLBOARD3D / PLANE 共用 int32 位域）现由 typed Bitmask + BitEnum 段建模
# （见 enums.BITS_APPLICATION_RULE），UI 经位掩码弹窗按段渲染；codec 只读/写裸 int（1:1 恒等）。
# 原先的手写拆分/合并（_split_application_rule / _merge_application_rule / _split_apprule_schema）
# 已随之退休——声明式段模型取代之。


def unpack_billboard3d(data: bytes, off: int = 0):
    """Unpack Billboard3D data_bytes (variable-length). Returns (dict, new_off)。
    applicationRule 保持裸 int（位分解移到 UI 弹窗）。"""
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
    """Pack Billboard3D values dict back to bytes。"""
    out = pack(_BILLBOARD3D_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += pack(_BILLBOARD3D_EXTRAS_SCHEMA, values)
    out += path
    return out


# BILLBOARD3D 固定段+extras（去 path/path_len）；applicationRule 用 Bitmask +
# BitDef×2（flowmap 混合位）+ BitEnum（mode 互斥）建模。UI 编辑段 == 此 schema。
_BILLBOARD3D_EDIT_SCHEMA = [
    e for e in (_BILLBOARD3D_FIXED_SCHEMA + _BILLBOARD3D_EXTRAS_SCHEMA)
    if e[0] not in ('path', 'path_len')
]
BILLBOARD3D_ATTR = attr_from_legacy(
    _schema_size(_BILLBOARD3D_EDIT_SCHEMA), _BILLBOARD3D_EDIT_SCHEMA,
    overrides={
        'applicationRule': Bitmask('applicationRule', BITS_APPLICATION_RULE, label_zh="应用规则"),
        'useColorRange':   Bool('useColorRange', label_zh="启用颜色范围"),
        'blendMode':       Enum('blendMode', ENUM_BLEND_MODE, label_zh="混合模式"),
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# Billboard2D (variable: 116B 固定 + path[path_len])
# EFX_Subtypes.bt: data_bytes(type 之后) =
#   long unkn0_0,applicationRule(8) + XYZ(2) color,colorRange(8) + float brightness,randomBrightnessMult(8) +
#   int useColorRange,blendMode,EPVColorSlot1,EPVColorSlot2(16) + float rotation,rotationJitter + scale,scaleJitter +
#   width + widthJitter + height + heightJitter (8 floats=32) +
#   float flowmapSpeed/Jitter,flowmapAcceleration/Jitter,flowmapStrength/Jitter,
#   flowmapStrengthAcceleration/Jitter(32) + int path_len(4) + int unkn5[2](8) + char p[path_len]
# 固定部分 116B；path_len 在 data 偏移 104。
# ─────────────────────────────────────────────────────────────────────────────

_BILLBOARD2D_FIXED_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn0_0
    # 用户直接投喂（2026-07-10，未测）：位置/取值集合都跟 BILLBOARD3D.applicationRule
    # 对应（BILLBOARD2D 只出现 [0,4,12,32]，是 BILLBOARD3D 枚举集合 [0,4,8,12,16,32,36,40…]
    # 的子集）。
    ('applicationRule', 'i'),   # 8
    ('color',             ('XYZ', 2)), # 4
    ('colorRange',        ('XYZ', 2)), # 4
    ('brightness',        'f'),
    ('brightnessJitter',  'f'),     # 8  原 randomBrightnessMult，2026-07-30 改名（见 RIBBON schema 注释）
    ('useColorRange',     'i'),
    ('blendMode',         'i'),
    ('EPVColorSlot1',     'i'),
    ('EPVColorSlot2',     'i'),   # 16
    # （2026-07-10）：原名 rotationJitterMin/Max、scaleJitterMin/Max 其实
    # 不是"抖动范围的 min/max"，是"固定值 + 抖动量"这套本仓库到处都在用的 value/valueJitter
    # 配对（同 BILLBOARD3D 的 rotation/rotationJitter、scale/scaleJitter）。
    ('rotation', 'f'),
    ('rotationJitter', 'f'),
    ('scale',    'f'),
    ('scaleJitter',      'f'),
    ('width',            'f'),
    ('widthJitter',      'f'),
    ('height',           'f'),
    ('heightJitter',     'f'),        # 8 floats = 32
    # 用户确认（2026-07-10）：flowmap 八件套，位置+全语料统计形态跟 BILLBOARD3D 同名
    # 字段逐一对应（"值有变化 + 紧跟的 Jitter 恒/几乎恒为 0"这套模式四对齐用）。  
    ('flowmapSpeed', 'f'),
    ('flowmapSpeedJitter', 'f'),
    ('flowmapAcceleration', 'f'),
    ('flowmapAccelerationJitter', 'f'),
    ('flowmapStrength', 'f'),
    ('flowmapStrengthJitter', 'f'),
    ('flowmapStrengthAcceleration', 'f'),
    ('flowmapStrengthAccelerationJitter', 'f'),   # 32
    ('path_len',         'i'),        # 4
    # 位置跟 BILLBOARD3D 的 path_len 之后、path 字节之前那段 extras（unkn5/unkn6_0…）
    # 完全对应（都是"path_len 后、path 前"这个槎位）。
    # 全语料核对：unkn5_0 全部恒为 0（580/580 无一例外）；unkn5_1 跟 applicationRule  
    # 有统计相关（rule=4 时 76.8% 为 1，rule=12 时 100% 为 1，rule=0/32 时几乎全为 0），
    # 曾猜测是 BILLBOARD3D.unkn6_0（"启用 flowmap 还需 unkn6=1"）的对应物——用户实机
    # 测试（2026-07-10）证伪：flowmap 效果不需要 unkn5_1=1 就能生效，applicationRule
    # 本身的 4/12 区别才是关键（4=持续循环流动，12=只播一次到终点停）。unkn5_1 跟
    # applicationRule 的相关性仍然存在，但具体作用未知，不再套用 unkn6_0 的"开关"解读。
    ('unknFixed5_0', 'i'),
    ('unknEnum5_1', 'i'),   # 8
]
assert _schema_size(_BILLBOARD2D_FIXED_SCHEMA) == 116, \
    f"_BILLBOARD2D_FIXED_SCHEMA size mismatch: {_schema_size(_BILLBOARD2D_FIXED_SCHEMA)}"
# 编辑段（去 path_len，同 CUSTOM_FIELD_SCHEMA_MAP[BILLBOARD2D]）；useColorRange/blendMode 同
# BILLBOARD3D/PLANE 语义（bool / 混合模式枚举）。
_BILLBOARD2D_EDIT_SCHEMA = [e for e in _BILLBOARD2D_FIXED_SCHEMA if e[0] != 'path_len']
BILLBOARD2D_ATTR = attr_from_legacy(
    _schema_size(_BILLBOARD2D_EDIT_SCHEMA), _BILLBOARD2D_EDIT_SCHEMA,
    overrides={
        'useColorRange': Bool('useColorRange', label_zh="启用颜色范围"),
        'blendMode':     Enum('blendMode', ENUM_BLEND_MODE, label_zh="混合模式"),
    },
)


def unpack_billboard2d(data: bytes, off: int = 0):
    """Unpack Billboard2D data_bytes (variable-length). Returns (dict, new_off)."""
    values, off = unpack(_BILLBOARD2D_FIXED_SCHEMA, data, off)
    path_len = values['path_len']
    values['path'] = data[off:off + path_len]
    off += path_len
    return values, off


def pack_billboard2d(values: dict) -> bytes:
    """Pack Billboard2D values dict back to bytes."""
    path = values['path']
    # path_len 字段以实际 path 长度为准（避免编辑路径后长度字段失同步）
    values = dict(values)
    values['path_len'] = len(path)
    out = pack(_BILLBOARD2D_FIXED_SCHEMA, values)
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
#   float rotation2/Jitter(8)（原 unkn5_2/3；实测为角度状数值，rotation2 常见 -180/0，
#     rotation2Jitter 常见 360/0——360 即"全范围随机"，语义上是 rotation 之外的一对
#     标量旋转+抖动，具体轴/用途未确认）+
#   XYZ scale(0)(24) + float global_scale/j(8) +
#   int starting/end_model_viscon(8) + colour*4(16) + int unkn7_0/1(8) +
#   int rotationOrder（原 unkn7_2；恰好 6 种取值 0~5，与 EMITTERSHAPE3D.rotationOrder
#     同构且同样以 4 为主流值，猜测为共享的旋转轴顺序枚举，语义未确认）(4) +
#   int tracking_flags（互斥模式选择,已转 Enum,官方语料见 0/1/2/4/6/8/10,10 不在
#     社区文档表内待确认,9 从未出现）(4) + int unkn40(4) +
#   int affectedByLight（官方语料证实为可混合位掩码：bit0~6 各种组合都出现,
#     bit7 从不单独/局部出现,只在 all_value=255 时整体置位,已转 Bitmask+all_value)(4) +
#   int shadowCastBitflag(4) + int epv_color_slot1(4) + int unkn5(4) +
#   int epv_color_slot2(4) + int unkn6_1(4) + byte colorize1[4](4) +
#   byte colorize2[4](4) +
#   byte unknBool0..3（原 int randommizeViscon 拆分：4 字节各恒 0/1，同
#     SHADERSETTINGS.visibleOnPreview 的打包字节模式，非单一标志）(4) +
#   byte unknBool4..5（原 short NULL1 拆分：2 字节各恒 0/1，同上）(2)
# = 8+4+8+8+24+8+24+8+8+16+12+4+4+4+4+4+4+4+4+4+4+4+2 = 174 B ✓
#
# （2026-07-06，色相/亮度组合排除测试）：color/colorRange 与
# emissiveColor/emissiveColorRange 是两组独立的 Color/ColorRange 对（同
# BILLBOARD3D/PLANE 机制），分别由 colorize_material1/2 里的开关控制：
#   colorize_material1[0]/[2]（enableIntensity1/2）：各自独立地让 color 通道
#     变亮，效果可叠加，不影响色相，只影响这条通道的亮度。
#   colorize_material1[1]（useColorRange）：启用 color↔colorRange 随机插值。
#   colorize_material1[3]（useEmissiveColor）：启用 emissiveColor 通道（不开
#     则该通道零贡献）。
#   colorize_material2[0]（useEmissiveColorRange）：启用 emissiveColor↔
#     emissiveColorRange 随机插值，独立于 [1]，不依赖它才生效。
#   colorize_material2[1]（enableEmissiveIntensity）：emissiveColor 通道的
#     亮度开关（严格布尔，只有暗/亮两档，不是连续数值；已排除"混合模式切换"
#     假设——纯黑 emissiveColor 在两档下都不会覆盖/压暗其它通道）。
#   两条通道之间是纯加法叠加。
#   colorize_material2[2]（disableAllColorRange）：实机确认，非零时同时强制
#     color 和 emissiveColor 都变成静态值，无视 useColorRange/
#     useEmissiveColorRange 各自的开关状态（一次性覆盖两条通道的随机插值）。
#   colorize_material2[3]：曾疑似对应 emissiveColorRange，但该次测试被证实
#     是场景雾气颜色污染导致的误判，已撤回，暂无可靠结论。  
# ─────────────────────────────────────────────────────────────────────────────

_MOD3_PROPERTIES_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn0_0
    ('unknFixed0_1', 'i'),   # 恒 167，接近但不满足 section_length 公式(174-8=166,差1)，未改名
    ('CD1',                     'i'),
    ('emissive_saturation',     'f'),
    ('emissive_saturation_j',   'f'),
    ('emissive_brightness',     'f'),  # TIML DT 0x18C577DE("EmissiveColorRate") 已确认
    ('emissive_brightness_j',   'f'),
    ('rotation',                ('XYZ', 0)),
    ('rotation2',               'f'),
    ('rotation2Jitter',         'f'),
    ('scale',                   ('XYZ', 0)),
    ('global_scale',            'f'),  # TIML DT 0x0EBAEC37("SizeScalar") 已确认
    ('global_scale_jitter',     'f'),
    ('starting_model_viscon',   'i'),
    ('end_model_viscon',        'i'),
    ('color',                   'colour'),  # TIML DT 0x58689812("Color") 已确认
    ('colorRange',              'colour'),
    ('emissiveColor',           'colour'),
    ('emissiveColorRange',      'colour'),
    ('unknEnum7_0', 'i'),
    ('unknFlag7_1', 'i'),
    ('rotationOrder', 'i'),
    ('tracking_flags',          'i'),
    ('unknBitmask40',                  'i'),
    ('affectedByLight',         'i'),
    ('shadowCastBitflag',       'i'),
    ('epv_color_slot1',         'i'),
    ('unknEnum5',                   'i'),
    ('epv_color_slot2',         'i'),
    ('unknFixed6_1',                 'i'),
    ('enableIntensity1',        'B'),  # 原 colorize_material1[0]
    ('useColorRange',           'B'),  # 原 colorize_material1[1]
    ('enableIntensity2',        'B'),  # 原 colorize_material1[2]
    ('useEmissiveColor',        'B'),  # 原 colorize_material1[3]
    ('useEmissiveColorRange',   'B'),  # 原 colorize_material2[0]
    ('enableEmissiveIntensity', 'B'),  # 原 colorize_material2[1]
    ('disableAllColorRange',    'B'),  # 原 colorize_material2[2]：实机确认(2026-07-06)，非零时同时
                                        # 强制 color 和 emissiveColor 都变成静态值，忽略
                                        # useColorRange/useEmissiveColorRange，无视两者各自的开关状态
    ('unknFlag_cm2_3',              'B'),  # 原 colorize_material2[3]：未确认（曾疑似color4，被场景雾误导后撤回）
    ('unknBool0',                    'B'),  # 原 int randommizeViscon 拆分（4 字节各恒 0/1，
    ('unknBool1',                    'B'),  # 同 SHADERSETTINGS.visibleOnPreview 的打包字节模式，
    ('unknBool2',                    'B'),  # 非单一"随机/全范围"标志），语义待实机确认
    ('unknBool3',                    'B'),
    ('unknBool4',                    'B'),  # 原 short NULL1 拆分（2 字节各恒 0/1，同上）
    ('unknBool5',                    'B'),
]
assert _schema_size(_MOD3_PROPERTIES_SCHEMA) == 174, \
    f"_MOD3_PROPERTIES_SCHEMA size mismatch: {_schema_size(_MOD3_PROPERTIES_SCHEMA)}"
# MESH 固定段 = Mod3Properties(174B) + BeginMod3(1B)（同 CUSTOM_FIELD_SCHEMA_MAP[MESH]）；
# path1/path2 由 codec 的 \0 扫描处理，不入 registry。
# rotationOrder 6 值枚举（同 EMITTERSHAPE3D）；8 个 colorize 标志位为 bool。
_MESH_BOOL_FIELDS = (
    'enableIntensity1', 'useColorRange', 'enableIntensity2', 'useEmissiveColor',
    'useEmissiveColorRange', 'enableEmissiveIntensity', 'disableAllColorRange', 'unknFlag_cm2_3',
    'unknBool0', 'unknBool1', 'unknBool2', 'unknBool3', 'unknBool4', 'unknBool5',
)
_mesh_ovr = {n: Bool(n, backing='B') for n in _MESH_BOOL_FIELDS}
_mesh_ovr['rotationOrder'] = Enum('rotationOrder', _TRANSFORM_ROT_ORDER, label_zh="旋转顺序")
_mesh_ovr['tracking_flags'] = Enum('tracking_flags', ENUM_MESH_TRACKING_FLAGS, label_zh="追踪标志")
_mesh_ovr['affectedByLight'] = Bitmask(
    'affectedByLight', BITS_AFFECTED_BY_LIGHT, all_value=255, strict=True,
    label_zh="受光照影响",
)
MESH_ATTR = attr_from_legacy(
    _schema_size(_MOD3_PROPERTIES_SCHEMA) + 1,
    _MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')],
    overrides=_mesh_ovr,
)


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
# ⚠ 下面这张 breakdown 用的是改名前的旧字段名（仅作字节偏移对照用），当前权威字段名见
#   _RIBBON_FIXED_SCHEMA 本体；其中 unkn23[8] 已确认是 flowmap 8 件套、tailTiedToBone
#   实为 enableFlowmap、unkn24 低 2 字节实为 flowmapPlayOnce/flowmapReverse。
# Structure breakdown (360 B fixed before path):
#   unkn0(4) + section_length(4) + spacer0(4) +  
#   XYZ color(2)(4) + spacer1(4) + XYZ color2(2)(4) + spacer2(4) +  
#   brightness(4) + unkn4_0(f,4) + unkn4_1(i,4) + scale(8) + width(8) + length(8) +
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
#     [现 flap1Frequency/Amount + flap2Frequency/Amount，各带 Jitter]
#   byte unkn0(1) + byte flow_enable_a/b(2) + byte reserved[13](13) +  
#   float flow_param0..3(16)   [原 ib_junk[32]，2026-07-21 拆分，见下方 schema 内注释]
# Total fixed: verify = 360 B
# ─────────────────────────────────────────────────────────────────────────────

_RIBBON_FIXED_SCHEMA = [
    ('typeFlag',                 'i'),   # 原 unkn0
    ('section_length',           'i'),
    ('spacer0',                  'i'),
    ('color',                    ('XYZ', 2)),
    # 原 int spacer1：全语料只有 0xCDCDCD00/01，低字节真实变化(12.6%非零)，其余 3 字节纯
    # 0xCD 占位——拆出 1 个真实 bool，2026-07-30。用户实机确认(2026-07-30)：启用颜色范围，
    # 同 BILLBOARD2D/BILLBOARD3D/PLANE 的 useColorRange 同一套语义，改名。
    ('useColorRange',            'B'),  # 原 unknBool1
    ('spacer1',                  ('B', 3)),
    ('colorRange',               ('XYZ', 2)),  # 原 color2；由 useColorRange 启用的随机范围端点
    # 原 int spacer2 的低字节（其余 3 字节纯 0xCD 占位）：blendMode，同 BILLBOARD3D/
    # BILLBOARD2D/PLANE 的 ENUM_BLEND_MODE。
    ('blendMode',                'B'),  # 原 unknBool2
    ('spacer2',                  ('B', 3)),
    ('brightness',               'f'),  # TIML DT 0x9F1E012E("ColorRate") 已确认
    # 原 unkn4(int[2]) 拆为两个独立字段：
    # [0] 原名 randomBrightnessMult——全语料实测取值 0~240，跟 brightness 本身(0~255)同一
    #     量级，并非 0~1 的"乘数"，是 brightness 的 static+jitter 配对里的 jitter 一半，
    #     2026-07-30 改名（BILLBOARD3D/BILLBOARD2D/PLANE 的同名字段同样改名，见各自 schema）。
    # [1] ribbonMode（原 unknEnum4_1）：三种条带形态，用户实机确认(2026-07-30)，命名对齐
    #     续作(RE Engine)对应的 ribbon 类型族——0=RibbonFollow(轨迹跟随)、
    #     1=RibbonLength(定长面片)、2=RibbonChain(柔体链)。
    ('brightnessJitter',         'f'),  # 原 unkn4_0 / randomBrightnessMult
    ('ribbonMode',                   'i'),  # 原 unknEnum4_1
    ('scale',                    'f'),  # TIML DT 0x0EBAEC37("SizeScalar") 已确认
    ('scale_jitter',             'f'),
    ('width',                    'f'),  # TIML DT 0xF0DF339B("WidthSize") 已确认
    ('width_jitter',             'f'),
    ('length',                   'f'),  # TIML DT 0xF92E647B("Length") 已确认
    ('length_jitter',            'f'),
    ('uv_map_height',            'i'),
    ('material_tesselation_density', 'f'),
    ('material_tesselation_jitter',  'f'),
    ('uv_map_width',             'f'),
    # subdivisionCount（原 horizontal_physics_subdivision_count）：沿条带长度方向的横向切边
    # 数量，N 条切边分出 N-1 段、每段 2 个三角面（用户实机确认 2026-07-30：设 4 得到 4 条边、
    # 3 段）。语料 1~150，主流值 2（即单个四边形）。命名对齐 STRAINRIBBON.subdivisionCount。
    ('subdivisionCount',         'i'),
    # 原 vertical_physics_subdivision_count：全语料只有 0/1（同一属性里 subdivisionCount 却用到
    # 1~150 共 33 种取值），"count"不成立，按 bool 处理；具体作用未确认，退回 unkn 命名。
    ('unknBool15',               'i'),
    ('unkn15',                   'f'),
    # baseAxis：原 restitution_direction，值分布同 VELOCITY3D/FADEBYANGLE 共用的
    # AxisDirection6（0左1上2前3右4下5后），非"反弹方向"专属语义，2026-07-30 改通用名。
    ('baseAxis',                 'i'),
    # rotationOrder：原 unknEnum16arr_0，98.83% 恒为 4，与 TRANSFORM3D/EMITTERSHAPE3D
    # 共用同一套 _TRANSFORM_ROT_ORDER 枚举（2026-07-30 用户确认，不再单独猜测）。
    ('rotationOrder',            'i'),
    # rotationX/Y/Z + Jitter：原 unkn16arr_1~3 + startingAngle/startingAngleJitter + unkn16_0_0，
    # 2026-07-30 用户实机测试确认为 rotOrder 复合旋转的 XYZ 三轴 static+random（byte 布局本身
    # 交错、非顺序对齐：X=(arr_1,arr_2)/Y=(startingAngle,arr_3)/Z=(unkn16_0_0,startingAngleJitter)）。
    # ⚠ 哪个是物理 X/Y/Z 轴仍受 ribbon 强制朝相机的自转干扰、未最终坐实，仅结构分组已确认。
    ('rotationX',                'f'),  # 原 unkn16arr_1
    ('rotationXJitter',          'f'),  # 原 unkn16arr_2
    ('rotationYJitter',          'f'),  # 原 unkn16arr_3
    ('rotationY',                'f'),  # 原 startingAngle
    ('rotationZJitter',          'f'),  # 原 startingAngleJitter
    ('rotationZ',                'f'),  # 原 unkn16_0_0
    ('unknFlag16_0_1', 'i'),
    # 原 short unknEnum16_1：全语料只有 0x0101/0x0001，低字节恒为 1（非通常的 0/0xCD 填充），
    # 只有高字节真正在 0/1 之间变化——拆出 1 个真实 bool，2026-07-30。
    ('unknFixed16_1_lo',         'B'),  # 恒 1
    ('unknBool16_1',             'B'),  # 真实数据
    # 原 short unknBitmask16_2：{0,1,256,257} 全部有意义比例出现，两字节各自独立的真实
    # bool（非填充），2026-07-30 拆分。低字节实机表现是"关闭后无法朝向摄像机"（一度误判为
    # 启用 Y 轴移动，已撤销该命名）；两个字节的确切语义都未定，保持 unkn 命名。
    ('unknBool16_2_0',           'B'),
    ('unknBool16_2_1',           'B'),
    # 原 int spacer3：0xCDCD0000/0100/0001/0101，低 2 字节各自真实变化（byte0 罕见 0.43%，
    # byte1 常见 27.24%），高 2 字节恒 0xCD 纯占位——拆出 2 个真实 bool，2026-07-30。
    ('unknBool3a',               'B'),
    ('unknBool3b',               'B'),
    ('spacer3',                  ('B', 2)),
    ('unknFixed17',                   'f'),
    ('spacer4',                  'i'),
    ('lengthwise_offset_relative_to_camera', 'f'),
    # 原 unknown19_0：用户实机测试确认(2026-07-30)——0 时前后向 ribbon 的最前端贴近生成
    # 位置；1 时前移 1 个相对长度，变成最后端贴近生成位置。数值分布跟
    # lengthwise_offset_relative_to_camera（几乎恒 0.5，仅偶见其他值）差异很大（本字段
    # 广泛分布 0~1 且可超出到 5.0），不像是同一种取值，判断是两个独立参数。
    ('spawnAnchorOffset',        'f'),  # 原 unknown19_0

    # ribbonMode=2(RibbonChain) 的弹簧-阻尼参数组。用户实机测试(2026-07-30)四组对照
    # （restoreStrength 0/1 × inertia 1/0.5 × springiness 0/1）的表现与标准阻尼振子一致：
    #   restoreStrength=0 → 无回复力，退化成与 ribbonMode=0(RibbonFollow) 高度相似的拖尾；
    #   restoreStrength=1 → 缓慢归位为平直；再加 inertia=1 → 定形为硬长条；
    #   再加 springiness=1 → 永不停歇地弹（等效无阻尼）；此时 inertia 降到 0.5 → 停止弹跳、
    #   以一定速度归位（阻尼比 ζ=c/(2√(km))，降低 m 即提高 ζ——反证 inertia 是质量项而
    #   非阻尼项，否则调低它会加剧振荡）。
    # restitution→restoreStrength 改名原因：物理上 restitution(恢复系数)指"弹性/弹力"，
    # 而该字段调高反而让条带**收敛**到平直，弹性其实在 springiness，旧名会误导。
    ('restoreStrength',          'f'),  # 原 restitution
    ('restoreStrengthJitter',    'f'),  # 原 restitution_jitter
    ('inertia',                  'f'),  # 原 inertial_excess
    ('inertiaJitter',            'f'),  # 原 inertial_excess_jitter
    ('springiness',              'f'),
    ('springiness_jitter',       'f'),
    # 原 int spacer5：同 spacer1 模式，低字节真实变化(12.2%非零)，其余 3 字节纯 0xCD 占位。
    # 实机表现是设为 1 后只显示条带前半部分（后半被隐藏），但确切语义未定，保持 unkn 命名。
    ('unknBool5',                'B'),
    ('spacer5',                  ('B', 3)),
    ('unkn20_0', 'f'),
    ('unkn20_1', 'f'),
    ('unkn20_2', 'f'),
    ('unkn20_3', 'f'),
    ('unkn21',                   'f'),
    ('unkn22_0', 'f'),
    # 原 unknEnum22_1：全语料 17 种取值全部可干净分解为 2 的幂之和(bit0~6, 值1~64)，
    # 是可混合位掩码而非枚举，2026-07-30 改名 + 转 Bitmask。
    ('unknBitmask22_1', 'i'),
    ('unknFlag22_2', 'i'),
    # 原 4B int 恒为 0xCDCDCD00/0xCDCDCD01（未初始化填充）；只有最低字节（文件里的第 1 个
    # 字节）在 0/1 之间变化，其余 3 字节恒为 0xCD 纯占位（2026-07-10）。用户实机确认
    # (2026-07-30)：该字节是 flowmap 总开关（原名 tailTiedToBone 是误读），改名。
    ('enableFlowmap',            'B'),  # 原 tailTiedToBone
    ('spacer6',                  ('B', 3)),
    # 用户实机确认(2026-07-30)：原 unkn23_0~7 就是 flowmap 8 件套，字段顺序与 BILLBOARD2D
    # 的 flowmap 组逐项吻合（两边取值分布形态一一对应，含 acceleration 两项同为 100% 恒 1.0）。
    ('flowmapSpeed',                     'f'),  # 原 unkn23_0
    ('flowmapSpeedJitter',               'f'),  # 原 unkn23_1
    ('flowmapAcceleration',              'f'),  # 原 unkn23_2
    ('flowmapAccelerationJitter',        'f'),  # 原 unknFixed23_3
    ('flowmapStrength',                  'f'),  # 原 unkn23_4
    ('flowmapStrengthJitter',            'f'),  # 原 unkn23_5
    ('flowmapStrengthAcceleration',      'f'),  # 原 unkn23_6
    ('flowmapStrengthAccelerationJitter','f'),  # 原 unknFixed23_7
    # 原 int unkn24 的低 2 字节（高 2 字节恒 0xCD 纯占位）。用户实机确认(2026-07-30)：
    # flowmapPlayOnce=流动只播放一次；flowmapReverse=逆向播放，且必须 flowmapPlayOnce
    # 启用才生效（官方语料存在 reverse=1/playOnce=0 的无效组合 48 例，故不做可见性门控，
    # 依赖关系写在 tooltip 里）。
    ('flowmapPlayOnce',          'B'),  # 原 unknBool24a
    ('flowmapReverse',           'B'),  # 原 unknBool24b
    ('unkn24',                   ('B', 2)),
    ('epvcolor_0',               'i'),
    ('epvcolor_1',               'i'),
    # 原 int spacer7：同 spacer1 模式，低字节真实变化(1.8%非零，比较罕见)。
    ('unknBool7',                'B'),
    ('spacer7',                  ('B', 3)),
    ('base_width_multiplier',    'f'),
    ('base_opacity',             'f'),
    ('tip_width_multiplier',     'f'),
    ('tip_opacity',              'f'),
    # 原 int spacer8：同 spacer1 模式，低字节真实变化(3.8%非零)。
    ('unknBool8',                'B'),
    ('spacer8',                  ('B', 3)),
    ('unkn27_0', 'f'),
    ('unkn27_1', 'f'),
    # 原 short visiblePreview：全语料 {0,1,256,257} 均有意义比例出现，实为 2 个独立字节，
    # 2026-07-30 拆分。低字节=已实机确认的"可见性修正"(非0破坏TIML变色+条带消失)；
    # 高字节经实机确认是下面 flap 抖动组的总开关，改名 enableFlap（语料佐证：开关=1 的
    # 270 块里 229 块确有 flap 取值；另有 111 块设了 flap 值但开关=0，属无效残留）。
    ('visiblePreview',           'B'),
    ('enableFlap',               'B'),  # 原 unknFlag_visiblePreview2
    ('spacer9',                  'h'),
    # flap 抖动组：给旗帜（ribbonMode=2 RibbonChain）一个恒定速率的来回摆动。用户实机确认
    # (2026-07-30)：原 base_*/tip_* 两组效果基本相同、可叠加（类似 BLINK 的叠加式），并**不是**
    # 名字暗示的"一组从根部起振、一组从尖端起振"，故改名 flap1/flap2 以免误导。
    # 语料佐证：两组多为同时使用(251)，其次只用 flap1(77)，只用 flap2 极少(12)。
    ('flap1Frequency',           'f'),  # 原 base_flap_frequency
    ('flap1FrequencyJitter',     'f'),  # 原 base_flap_frequency_jitter
    ('flap1Amount',              'f'),  # 原 base_flap_amount
    ('flap1AmountJitter',        'f'),  # 原 base_flap_amount_jitter
    ('flap2Frequency',           'f'),  # 原 tip_flap_frequency
    ('flap2FrequencyJitter',     'f'),  # 原 tip_flap_frequency_jitter
    ('flap2Amount',              'f'),  # 原 tip_flap_amount
    ('flap2AmountJitter',        'f'),  # 原 tip_flap_amount_jitter
    # 原 ib_junk[32] 拆分（2026-07-21 全语料 15015 块统计）：
    # byte[0] 恒为 0（15015/15015 无一例外）。
    # byte[1]/byte[2] 是两个独立 bool 标志：只要任一为 1，后面 3 个 float 里非零
    # 的比例从基线 0.15%（两者都 0 时）跳到 80%~99%——近乎完美的 enable 门控关系。
    # byte[3:16] 13 字节恒为 0xCD（未初始化占位，同 reserved-fill-fields 判据）。
    # 第 4 个 float 恒为 0.0（15015/15015 无一例外）。已排除"其实是 flap 8 件套的重复/错位"假说。
    # ⚠ 这批字段一度按"疑似 flowmap 参数"命名为 ribbon_flow_*，2026-07-30 已证伪——
    #   真正的 flowmap 8 件套是上面的 flowmapSpeed~flowmapStrengthAccelerationJitter
    #   （原 unkn23_*），总开关是 enableFlowmap。
    # 用户实机确认(2026-07-30)：byte[1] 是后 3 个 float 的开关；byte[2] 疑似叠在 byte[1] 之上。
    # 后 3 个 float 是三个正交方向的力（自尾端施力），方向恒定——不受 localRotation 也不受
    # TRANSFORM3D 旋转影响，故为世界/全局方向，命名 unknGlobalForceX/Y/Z（param1=竖直轴→Y）。
    # 具体各轴指向哪一侧仍未确认，保留 unkn 前缀。
    ('unknFixed28_0',            'B'),
    ('unknGlobalForceEnable',    'B'),  # 原 unknBool28_1
    ('unknBool28_2',             'B'),
    ('spacer28',                 ('B', 13)),
    ('unknGlobalForceX',         'f'),  # 原 unkn28_param0
    ('unknGlobalForceY',         'f'),  # 原 unkn28_param1（竖直轴，负值近似重力）
    ('unknGlobalForceZ',         'f'),  # 原 unkn28_param2
    ('unknFixed28_param3',      'f'),
]
assert _schema_size(_RIBBON_FIXED_SCHEMA) == 360, \
    f"_RIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBON_FIXED_SCHEMA)}"
RIBBON_ATTR = attr_from_legacy(
    _schema_size(_RIBBON_FIXED_SCHEMA), _RIBBON_FIXED_SCHEMA,
    overrides={
        # baseAxis：原 restitution_direction，同 VELOCITY3D/FADEBYANGLE/RIBBONBLADE 共享的
        # 通用 AxisDirection6。（2026-07-30 一度误判要建独立枚举——当时的测试其实是
        # rotationZ=90 复合旋转后的表观方向，baseAxis 本身取值没有问题，已撤销。）
        'baseAxis':       Enum('baseAxis', _AXIS_DIRECTION6, label_zh="基准轴"),
        # rotationOrder：原 unknEnum16arr_0，同 TRANSFORM3D/EMITTERSHAPE3D 共享的旋转顺序枚举。
        'rotationOrder':  Enum('rotationOrder', _TRANSFORM_ROT_ORDER, label_zh="旋转顺序"),
        'enableFlowmap':  Bool('enableFlowmap', backing='B', label_zh="启用流动贴图"),
        # 2026-07-30 批量取值调查后落地：干净 0/1 → Bool；可混合位掩码 → Bitmask。
        'unknFlag16_0_1':          Bool('unknFlag16_0_1'),
        'unknBool16_1':            Bool('unknBool16_1', backing='B'),
        'unknBool16_2_0':          Bool('unknBool16_2_0', backing='B'),
        'unknBool16_2_1':          Bool('unknBool16_2_1', backing='B'),
        'unknBitmask22_1':         Bitmask('unknBitmask22_1', BITS_RIBBON_UNKN22_1, strict=True),
        'unknFlag22_2':            Bool('unknFlag22_2'),
        'visiblePreview':          Bool('visiblePreview', backing='B', label_zh="可见性修正"),
        'enableFlap':              Bool('enableFlap', backing='B', label_zh="启用抖动"),
        'unknGlobalForceEnable':   Bool('unknGlobalForceEnable', backing='B'),
        'unknBool28_2':            Bool('unknBool28_2', backing='B'),
        # 原 spacer0/1/2/3/5/7/8、unkn24 拆出的真实 bool（0xCD 占位掩盖的低字节数据）。
        'useColorRange': Bool('useColorRange', backing='B', label_zh="启用颜色范围"),
        'ribbonMode':    Enum('ribbonMode', ENUM_RIBBON_MODE, label_zh="条带模式"),
        'blendMode':     Enum('blendMode', ENUM_BLEND_MODE, backing='B', label_zh="混合模式"),
        'unknBool15':  Bool('unknBool15'),
        'unknBool3a':  Bool('unknBool3a', backing='B'),
        'unknBool3b':  Bool('unknBool3b', backing='B'),
        'unknBool5':   Bool('unknBool5', backing='B'),
        'unknBool7':   Bool('unknBool7', backing='B'),
        'unknBool8':   Bool('unknBool8', backing='B'),
        'flowmapPlayOnce': Bool('flowmapPlayOnce', backing='B', label_zh="流动只播放一次"),
        'flowmapReverse':  Bool('flowmapReverse', backing='B', label_zh="流动逆向播放"),
    },
)


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
#   unkn0(4)+applicationRule(4)+XYZ color(2)(4)+XYZ colorRange(2)(4)+brightness(4)+
#   randomBrightnessMult(4)+useColorRange(4)+blendMode(4)+EPVColorSlot1(4)+EPVColorSlot2(4)+
#   rotation2/j(8)+
#   scale/j(8)+width/j(8)+height/j(8)+
#   flowmapSpeed/j(8)+flowmapAccel/j(8)+flowmapStrength/j(8)+flowmapStrAccel/j(8)+
#   path_len(4) = 108 B (path_len at +104 within data_bytes)
# Extras (48 B): int unkn5[4](16) + XYZ rotation(0)(24) + uint64 unkn7(8)
# Then: path[path_len]
# ─────────────────────────────────────────────────────────────────────────────

_PLANE_DDS_SCHEMA = [
    ('typeFlag',           'i'),   # 原 unkn0
    ('applicationRule',    'i'),
    # （同 BILLBOARD3D 的 color/colorRange/useColorRange 机制，见该注释）：
    # 原 EPVColorBlend 实为 useColorRange，原 unkn22 实为 blendMode。
    ('color',              ('XYZ', 2)),  # TIML DT 0x58689812("Color") 已确认
    ('colorRange',         ('XYZ', 2)),
    ('brightness',         'f'),  # TIML DT 0x9F1E012E("ColorRate") 已确认
    # 原 unkn20，位置与 BILLBOARD3D 的 brightnessJitter 相同，暂按同名归类；语义未
    # confirmed（不同于 BILLBOARD3D 那条已实机验证的注释，这里先只搬名字）。全语料实测
    # 取值 0~100，跟 brightness(0~255) 同量级，支持"jitter 而非 0~1 乘数"这一改名，
    # 2026-07-30。
    ('brightnessJitter',  'f'),  # 原 randomBrightnessMult
    ('useColorRange',      'i'),
    ('blendMode',          'i'),
    ('EPVColorSlot1',      'i'),
    ('EPVColorSlot2',      'i'),
    # 与顶部 XYZ 朝向独立的一对标量旋转+抖动（平面沿自身垂线的自旋），
    # 同 MESH.rotation2/rotation2Jitter 命名（原 SlotOverride1/2，2026-07-08 已排除
    # 整数槽位覆盖语义，重解读为 float）。
    ('rotation2',          'f'),
    ('rotation2Jitter',    'f'),
    ('scale',              'f'),  # TIML DT 0x0EBAEC37("SizeScalar") 已确认
    ('scaleJitter',        'f'),
    ('width',              'f'),
    ('widthJitter',        'f'),
    ('height',             'f'),  # TIML DT 0x531B9E44("SizeY") 已确认
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
]  # = 4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 104 B

_PLANE_EXTRAS_SCHEMA = [
    ('unknBitmask5_0', 'i'),
    ('unknEnum5_1', 'i'),
    ('unknBitmask5_2', 'i'),
    ('unknEnum5_3', 'i'),
    ('rotation',('XYZ', 0)),
    # 拆分自原 uint64 unkn7：低32位=小整数/位掩码，高32位=0/1 标志（实测 4328 个 PLANE 块核对）
    ('unknBitmask7_0', 'i'),
    ('unknFlag7_1', 'i'),
]  # = 16+24+8 = 48 B


def unpack_plane(data: bytes, off: int = 0):
    """Unpack Plane data_bytes (variable-length). Returns (dict, new_off)。
    applicationRule 保持裸 int（位分解移到 UI 弹窗）。"""
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
    """Pack Plane values dict back to bytes。"""
    out = pack(_PLANE_DDS_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += pack(_PLANE_EXTRAS_SCHEMA, values)
    out += path
    return out


# PLANE 同 BILLBOARD3D，applicationRule 共用 BITS_APPLICATION_RULE。
_PLANE_EDIT_SCHEMA = [
    e for e in (_PLANE_DDS_SCHEMA + _PLANE_EXTRAS_SCHEMA)
    if e[0] not in ('path', 'path_len')
]
PLANE_ATTR = attr_from_legacy(
    _schema_size(_PLANE_EDIT_SCHEMA), _PLANE_EDIT_SCHEMA,
    overrides={
        'applicationRule': Bitmask('applicationRule', BITS_APPLICATION_RULE, label_zh="应用规则"),
        'useColorRange':   Bool('useColorRange', label_zh="启用颜色范围"),
        'blendMode':       Enum('blendMode', ENUM_BLEND_MODE, label_zh="混合模式"),
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# RibbonBlade (variable: fixed 198 B header + path_len(int) + path)
#
# From efxfile.py: path_len at offset 198 from block start (= offset 194 in data_bytes)
# fixed structure before path_len (194 B in data_bytes):
#   unkn0[2](8)+spacer0(4)+widthDirection(4)+width(4)+length+unkn05_1(8)+spacer1(4)+unkn07_0+lengthMode(8)+  
#   5 floats(20)+spacer2(4)+unkn10(4)+uvRep(4)+unkn12[3](12)+spacer3(4)+  
#   EPVColorSlot head(36)+EPVColorSlot tailEnd(36)+
#   flowmap 4*(value+jitter)(32)+short NULL9(2)  
# = 8+4+4+4+8+4+8+20+4+4+4+12+4+36+36+32+2 = 198 B total data before path_len
# Then: path_len(4) + path[path_len]
# ─────────────────────────────────────────────────────────────────────────────

_RIBBONBLADE_FIXED_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn0_0，样本少(62例)且几乎恒为1，弱证据但同机制
    ('unknFixed0_1', 'i'),
    ('spacer0',     'i'),
    ('widthDirection', 'i'),  # 原 unkn03
    ('width',       'f'),  # 原 unkn04；刀光纵边宽度（用户命名，2026-07-10）
    ('length', 'i'),  # 原 unkn05_0
    ('unknEnum05_1', 'i'),
    ('spacer1',     'i'),
    ('unknFlag07_0', 'i'),
    ('lengthMode', 'i'),  # 原 unkn07_1
    # 5 floats: maxLengthLimit, contractionSpeed, colourTransitionPoint, emissiveStrength, unkn08
    ('maxLengthLimit',          'f'),
    ('contractionSpeed',        'f'),
    ('colourTransitionPoint',   'f'),
    ('emissiveStrength',        'f'),
    ('unknFlag08',                  'f'),
    ('spacer2',     'i'),
    ('unknEnum10',      'i'),
    ('uvRepetition','f'),
    ('unknFlag12_0', 'f'),
    ('unknFlag12_1', 'i'),
    ('unknFixed12_2', 'i'),
    # 恒为 0xcdcdcd00（62/62）。曾拆出最低字节暴露实机测试（unkn13，2026-07-11），  
    # 用户测试无效果，已改回纯占位（2026-07-11）。  
    ('spacer3',     'i'),
    ('head',        'EPVColorSlot'),
    ('tailEnd',     'EPVColorSlot'),
    # flowmap 四件套 + jitter：实测确认（2026-07-11，用户系统测试 unkn25/26，其余按同结构类推）。
    # NULL5~8 全语料恒为 0（int/float 位模式相同,无法从静态数据判定类型),按 jitter 惯例先定为 float,  
    # 待实机测试非零值验证。
    ('flowmapSpeed',                    'f'),  # 原 unkn23
    ('flowmapSpeedJitter',              'f'),  # 原 NULL5 (i->f)  
    ('flowmapAcceleration',             'f'),  # 原 unkn24
    ('flowmapAccelerationJitter',       'f'),  # 原 NULL6 (i->f)  
    ('flowmapStrength',                 'f'),  # 原 unkn25
    ('flowmapStrengthJitter',           'f'),  # 原 NULL7 (i->f)  
    ('flowmapStrengthAcceleration',     'f'),  # 原 unkn26
    ('flowmapStrengthAccelerationJitter', 'f'),  # 原 NULL8 (i->f)  
    ('NULL9',       'h'),
]
assert _schema_size(_RIBBONBLADE_FIXED_SCHEMA) == 194, \
    f"_RIBBONBLADE_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBONBLADE_FIXED_SCHEMA)}"
# widthDirection：全语料 {1,2,4,5} ⊂ 0-5，同 6 向枚举。length（拖尾长度）语料 {2..35} 为
# 连续幅值、非离散选择器，保持 int。
RIBBONBLADE_ATTR = attr_from_legacy(
    _schema_size(_RIBBONBLADE_FIXED_SCHEMA), _RIBBONBLADE_FIXED_SCHEMA,
    overrides={'widthDirection': Enum('widthDirection', _AXIS_DIRECTION6, label_zh="宽度延伸方向")},
)


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
# color/colorRange 是字节 RGBA 色（XYZ type 2），与其他渲染主体（BILLBOARD3D/MESH 等）
# 同款 color+colorRange+useColorRange 三件套（用户实机确认，2026-07-23）；color3 实为
# endPointScatter/originReleaseFlag 两个开关 + color3_z（真实 0/1 标志，语料 69.6%/30.4%，
# 模板误标成保留字节）+ color3_w（真保留，恒为 0xCD），共拆成 4 个 byte。  
# 含一片 MT Framework 物理参数（tension/gravity/inertia/displacement 等）——
# MHW 即 MT Framework 引擎，这些在 MHW 内有效；unkn/spacer 为保留/对齐字段。  
# ⚠ spacer00/01/02 同源 bug：原按 4B int 读取恒为 0xCDCDCD00 系列，但 MSB==0xCD 判据  
# 只看最高字节，藏住了最低字节的真实数据——仿 RIBBON.tailTiedToBone 先例拆出最低字节。
# spacer01→useColorRange、spacer02→useEmission 均已用户实机确认（2026-07-23）；spacer00  
# 拆出的 unkn00_2 语料中恒为 0（暂无变化样本），语义仍待确认。  
# ─────────────────────────────────────────────────────────────────────────────
_STRAINRIBBON_FIXED_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn00_0，语料 1~13 小基数分布，符合类型标记形态
    ('unknFixed00_1', 'i'),   # 8，语料恒 244，不满足"总字节-8"公式，不套 section_length
    ('unknFixed00_2',               'B'),        # spacer00 最低字节，语料恒 0，语义待确认  
    ('spacer00',               ('B', 3)),   # 高 3 字节，纯 0xCD 占位  
    ('color',                  ('XYZ', 2)), # 固定色 RGBA（原 color1）
    ('useColorRange',          'B'),        # 原 unkn01_0/spacer01 最低字节；启用 color↔colorRange  
    ('spacer01',               ('B', 3)),   # 高 3 字节，纯 0xCD 占位  
    ('colorRange',             ('XYZ', 2)), # 随机颜色范围 RGBA（原 color2，与 color 配对）
    ('useEmission',            'B'),        # 原 unkn02_0/spacer02 最低字节；启用自发光  
    ('spacer02',               ('B', 3)),   # 高 3 字节，纯 0xCD 占位  
    ('emissionStrength',       'f'),
    ('emissionStrengthJitter', 'f'),        # unkn03_01
    ('spacer03',               'i'),
    ('startPosition',          ('XYZ', 3)), # 起点（绑定骨骼/生成位置）XYZ 偏移，原 startDirectionX/Y/Z（用户实机确认为真实偏移量，非开关）
    ('unknFixed03_06',              'f'),
    ('endPosition',            ('XYZ', 3)), # 末端骨骼 XYZ 偏移
    ('unknFixed03_10',              'f'),
    ('width',                  'f'),  # TIML DT 0xF0DF339B("WidthSize") 已确认
    ('widthJitter',            'f'),
    ('length',                 'f'),  # TIML DT 0xF92E647B("Length") 已确认
    ('lengthJitter',           'f'),
    ('startWidth',             'f'),
    ('startOpacity',           'f'),
    ('endWidth',               'f'),
    ('endOpacity',             'f'),
    ('subdivisionCount',       'i'),
    ('unknFixed04_01',              'i'),
    ('uvRepetition',           'i'),
    ('widthwiseUVScalingAlpha','f'),
    ('spacer04',               'f'),  # 名字像占位，但实测非零值干净重解读为 5.0，可能并非纯占位  
    ('widthwiseUVScalingBML',  'f'),
    ('endPointScatter',        'B'),        # color3.x（终点扩散开关）
    ('originReleaseFlag',      'B'),        # color3.y（起点解锁标志）
    ('color3_z',               'B'),        # 真实 0/1 标志（语料 69.6%/30.4%，非保留，模板误标成颜色）
    ('color3_w',               'B'),        # 真保留，恒为 0xCD  
    ('unkn06_0', 'f'),
    ('unkn06_1', 'f'),
    ('unkn06_2', 'f'),
    ('unknFixed06_3', 'f'),
    ('unkn06_4', 'f'),
    ('unknFlag06_5', 'f'),
    ('unkn06_6', 'f'),
    ('unkn06_7', 'f'),   # unkn06_00..07，32B
    ('unknEnum06_08_00',           'h'),
    ('unknEnum06_08_01',           'h'),
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
    ('unknEnum09_0', 'i'),
    ('unknFixed09_1', 'f'),
    ('unkn09_2', 'f'),
    ('unkn09_3', 'f'),
    ('unkn09_4', 'f'),   # 20B
    ('unknEnum10_00',              'i'),
    ('angleRelated',           'f'),        # 原 unkn10_01，bt 注释+语料恒 360.0 双证实
    ('angleRelatedJitter',     'f'),        # 原 unkn10_02，bt 注释+语料恒 0.0 双证实
    ('unknEnum11',                 'i'),
    ('unknEnum12_00',              'i'),
    ('unknFixed12_01',              'f'),
    ('unknFixed12_02',              'f'),
    ('unknFixed12_03',              'f'),
    ('unknFixed13',                 'i'),
]
assert _schema_size(_STRAINRIBBON_FIXED_SCHEMA) == 340, \
    f"_STRAINRIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_STRAINRIBBON_FIXED_SCHEMA)}"
STRAINRIBBON_ATTR = attr_from_legacy(_schema_size(_STRAINRIBBON_FIXED_SCHEMA), _STRAINRIBBON_FIXED_SCHEMA)


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
    ('unkn1_0', 'f'),
    ('unknEnum1_1', 'i'),
    ('offsetPos',       ('XYZ', 0)),
    ('offsetPosVel',    ('XYZ', 0)),
    ('offsetAngle',     ('XYZ', 0)),
    ('offsetAngleVel',  ('XYZ', 0)),
    ('offsetScale',     ('XYZ', 0)),
    ('unkn3_0', 'f'),
    ('unkn3_1', 'f'),
    ('unkn3_2', 'i'),
    ('unknEnum3_3', 'i'),
    ('unknFlag3_4', 'i'),
]  # = 4+8+24*5+20 = 4+8+120+20 = 152 B


def unpack_turbulence(data: bytes, off: int = 0):
    """Unpack Turbulence data_bytes (variable-length). Returns (dict, new_off)."""
    (typeFlag,) = struct.unpack_from('<i', data, off)   # 原 unkn0
    off += 4
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    path = data[off:off + path_len]
    off += path_len
    values = {'typeFlag': typeFlag, 'path_len': path_len, 'path': path}
    rest, off = unpack(_TURBULENCE_AFTER_PATH_SCHEMA, data, off)
    values.update(rest)
    return values, off


def pack_turbulence(values: dict) -> bytes:
    """Pack Turbulence values dict back to bytes."""
    out = struct.pack('<i', values['typeFlag'])
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    out += pack(_TURBULENCE_AFTER_PATH_SCHEMA, values)
    return out


# TURBULENCE 固定字段（typeFlag + path 之后的固定段，同 CUSTOM_FIELD_SCHEMA_MAP[TURBULENCE]）；
# path 由 codec 单独处理。unknEnum*/unknFlag* 值集未确认，暂按 int。
_TURBULENCE_EDIT_SCHEMA = [('typeFlag', 'i')] + _TURBULENCE_AFTER_PATH_SCHEMA
TURBULENCE_ATTR = attr_from_legacy(_schema_size(_TURBULENCE_EDIT_SCHEMA), _TURBULENCE_EDIT_SCHEMA)


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
    ('typeFlag', 'i'),   # 原 unkn00_0
    ('unknFixed00_1', 'i'),
    ('spacer0',             'i'),
    # XYZ color1/2/emissive as (2) type = 4B each: 3*4=12B, then unkn02-04 = 3*4=12B
    ('color1',              ('XYZ', 2)),
    ('unkn02',              'i'),
    ('color2',              ('XYZ', 2)),
    ('unkn03',              'i'),
    ('emissive',            ('XYZ', 2)),
    ('unkn04',              'f'),   # 原 unknEnum04：实为 float（全语料位模式=0.0/0.4/1.0…100.0 干净浮点）
    # group05 block: spacer05_00+unkn05_01+sineFreq/j+alphaThreshold+05_05-07+  
    #   outExp/j+05_10+05_11-13+spacer05_14+targetBone+05_16+05_17+EPV1/2+05_20-24  
    # = 4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4+4 = 25*4=100B
    ('spacer05_00',         'i'),
    ('unknEnum05_01',           'i'),
    ('sineWaveFreq',        'f'),
    ('sineWaveFreqJitter',  'f'),
    ('alphaThreshold',      'f'),
    ('unkn05_05',           'f'),
    ('unkn05_06',           'f'),
    ('unkn05_07',           'f'),
    ('outwardsExpansionSpeed',      'f'),
    ('outwardsExpansionSpeedJitter','f'),
    ('unkn05_10',           'f'),
    ('unknEnum05_11',           'i'),
    ('unknFlag05_12',           'i'),
    ('unknEnum05_13',           'i'),
    ('spacer05_14',         'i'),
    ('targetBoneID',        'i'),
    ('unknEnum05_16',           'i'),
    ('unknFlag05_17',           'i'),
    ('EPVColorSlot1',       'i'),
    ('EPVColorSlot2',       'i'),
    ('unknFixed05_20',           'i'),
    ('unkn05_21',           'i'),
    ('unknFixed05_22',           'i'),
    ('unknFixed05_23',           'f'),
    ('unknFixed05_24',           'f'),
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
    ('unknFixed05_45',   'i'),
    ('unkn05_46',   'i'),
    ('unknBitmask05_47',   'i'),
    ('unknFlag05_48',   'i'),
    # unkn06[2]: 2*4=8B
    ('unknBitmask06_0', 'i'),
    ('unknBitmask06_1', 'i'),
    # unkn07_00-09: 10*4=40B
    ('radiusLimit',         'f'),
    ('radiusLimitJitter',   'f'),
    ('unkn07_02',           'f'),
    ('unknFixed07_03',           'f'),
    ('unknBitmask07_04',           'i'),
    ('unkn07_05',           'f'),
    ('unkn07_06',           'f'),
    ('unkn07_07',           'f'),
    ('unknFixed07_08',           'f'),
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
    ('unknFixed07_19',   'f'),
    ('unkn07_20',   'f'),
    ('unknEnum07_21',   'i'),
    ('unknFlag07_22',   'i'),
    ('unknEnum07_23',   'i'),
    ('unknBitmask07_24',   'i'),
    ('unkn07_25',   'f'),
    ('unkn07_26',   'f'),
    ('unkn07_27',   'f'),
    # unkn08[2]: 2*4=8B
    ('unknFixed08_0', 'i'),
    ('unknEnum08_1', 'i'),
    # unkn09[20]: 20*4=80B
    ('unkn09',      ('f', 20)),
    # unkn10[4]: 4*4=16B
    ('unkn10_0', 'f'),
    ('unknEnum10_1', 'i'),
    ('unknFlag10_2', 'i'),
    ('unknFixed10_3', 'i'),
    # unkn11[2]: 2*4=8B
    ('unkn11_0', 'f'),
    ('unkn11_1', 'f'),
    # unkn12[2]: 2*4=8B
    ('unknFixed12_0', 'i'),
    ('unknEnum12_1', 'i'),
    # unkn13[6]: 6*4=24B
    ('unkn13',      ('f', 6)),
    # unkn14[3]: 3*4=12B
    ('unknEnum14_0', 'i'),
    ('unknFlag14_1', 'i'),
    ('unknFixed14_2', 'i'),
    # unkn15[9]: 9*4=36B
    ('unkn15',      ('f', 9)),
    # short unkn16: 2B
    ('unknEnum16',      'h'),
]
assert _schema_size(_LIGHTNING_FIXED_SCHEMA) == 546, \
    f"_LIGHTNING_FIXED_SCHEMA size mismatch: {_schema_size(_LIGHTNING_FIXED_SCHEMA)}"
LIGHTNING_ATTR = attr_from_legacy(_schema_size(_LIGHTNING_FIXED_SCHEMA), _LIGHTNING_FIXED_SCHEMA)


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
    ('typeFlag',                 'i'),   # 原 unkn0
    ('color',                    ('XYZ[]', 2, 2)),
    ('brightnessSlot1',          'f'),
    ('emissiveMultiplier',       'f'),
    ('brightnessSlot2',          'f'),
    ('brightnessSlotMultiplier1','f'),
    ('brightnessSlotMultiplier2','f'),
    ('opacity',                  'f'),
    ('unknownFloat',             'f'),
    ('unknownFlagInt_0', 'i'),
    ('unknownEnumInt_1', 'i'),
    ('unknownEnumInt_2', 'i'),
    ('unknEnum2_0', 'i'),
    ('unknEnum2_1', 'i'),
    ('unknEnum2_2', 'i'),
    ('unknEnum2_3', 'i'),
    ('unknFlag2_4', 'i'),
    ('unknFlag2_5', 'i'),
    ('unknEnum2_6', 'i'),
    ('unknFlag2_7', 'i'),
    ('unknEnum2_8', 'i'),
    ('unknEnum2_9', 'i'),
    ('unkn2_10', 'i'),
    ('unknEnum2_11', 'i'),
    ('unkn2_12', 'i'),
    ('unknEnum2_13', 'i'),
    ('unknFlag2_14', 'i'),
    ('unknEnum2_15', 'i'),
    ('unknEnum2_16', 'i'),
    ('unknFlag2_17', 'i'),
    ('unknEnum2_18', 'i'),
    ('unknEnum2_19', 'i'),
    ('unkn2_20', 'i'),
    ('unknEnum2_21', 'i'),
    ('unkn2_22', 'i'),
    ('unknEnum2_23', 'i'),
    ('unknFlag2_24', 'i'),
    ('unknEnum2_25', 'i'),
]  # = 4+8+28+12+104 = 156 B
assert _schema_size(_RGBWATER_FIXED_SCHEMA) == 156, \
    f"_RGBWATER_FIXED_SCHEMA size mismatch: {_schema_size(_RGBWATER_FIXED_SCHEMA)}"
RGBWATER_ATTR = attr_from_legacy(_schema_size(_RGBWATER_FIXED_SCHEMA), _RGBWATER_FIXED_SCHEMA)

# EXTERNRGBWATER（Extern 覆盖版，2026-07）：与主属性 _RGBWATER_FIXED_SCHEMA (156B)
# 完全同构，无 path；语料实测（48/48 元素）额外多出固定 5B 尾巴 int32(恒为1)+
# byte(恒0)，语义未知。161B/元素（156+5）。
# 'color' 原 spec 是 ('XYZ[]', 2, 2)（嵌套数组，_check_schema_all_flat 判定不可
# 平铺展开）——按字节序原样拆成两个独立 ('XYZ', 2) 字段（unpack/pack 内部本就是
# 逐个循环 _unpack_xyz/_pack_xyz，拆开纯属重命名，字节布局不变），使整个 schema
# 可平铺表示，从而复用跟其它 6 个已支持 EXTERN 类型一样的通用 flat schema 编辑路径。
EXTERN_RGBWATER_SCHEMA = []
for _name, _spec in _RGBWATER_FIXED_SCHEMA:
    if _name == 'color':
        EXTERN_RGBWATER_SCHEMA.append(('color_0', ('XYZ', 2)))
        EXTERN_RGBWATER_SCHEMA.append(('color_1', ('XYZ', 2)))
    else:
        EXTERN_RGBWATER_SCHEMA.append((_name, _spec))
EXTERN_RGBWATER_SCHEMA.append(('unkn_tail0', 'i'))
EXTERN_RGBWATER_SCHEMA.append(('unkn_tail1', 'B'))
assert _schema_size(EXTERN_RGBWATER_SCHEMA) == 161, \
    f"EXTERN_RGBWATER_SCHEMA size mismatch: {_schema_size(EXTERN_RGBWATER_SCHEMA)}"


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
    (typeFlag,) = struct.unpack_from('<i', data, off); off += 4   # 原 unkn0（块级头字段，跟下面每个参数各自的 unkn0 无关）
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
            v1, = struct.unpack_from('<f', data, off); off += 4
            v2, = struct.unpack_from('<f', data, off); off += 4
            v3, = struct.unpack_from('<f', data, off); off += 4
            param['unkn0'] = v0
            param['unkn1'] = v1
            param['unkn2'] = v2
            param['unkn3'] = v3
        elif t == 0x36:
            vals = list(struct.unpack_from('<2i', data, off)); off += 8
            param['unkn1'] = vals
        elif t == 0x37:
            vals = list(struct.unpack_from('<2f', data, off)); off += 8
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
    return {'typeFlag': typeFlag, 'behav_type_len': behav_type_len,
            'para_count': para_count, 'b_type': b_type, 'params': params}, off


def pack_ptbehavior(values: dict) -> bytes:
    """Pack PtBehavior values dict back to bytes."""
    out = struct.pack('<i', values['typeFlag'])
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
            out += struct.pack('<f', param['unkn1'])
            out += struct.pack('<f', param['unkn2'])
            out += struct.pack('<f', param['unkn3'])
        elif t == 0x36:
            out += struct.pack('<2i', *param['unkn1'])
        elif t == 0x37:
            out += struct.pack('<2f', *param['unkn1'])
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
    (typeFlag,) = struct.unpack_from('<q', data, off); off += 8   # 原 unkn00（8B/int64，语料仍呈小基数分布）
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
    return {'typeFlag': typeFlag, 'block_count': block_count, 'blocks': blocks}, off


def pack_material(values: dict) -> bytes:
    """Pack Material values dict back to bytes."""
    out = struct.pack('<q', values['typeFlag'])
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
    ('typeFlag', 'i'),   # 原 unkn0_0，语料仅 1 例
    ('unknFixed0_1', 'i'),   # 8B
    ('unkn1', 'i'),        # 4B
    ('unknFixed2_0', 'f'),
    ('unknFixed2_1', 'f'),
    ('unknFixed2_2', 'f'),   # 12B
]  # 24B
TONEMAPFILTER_ATTR = attr_from_legacy(_schema_size(_TONEMAPFILTER_FIXED_SCHEMA), _TONEMAPFILTER_FIXED_SCHEMA)


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


# TUBELIGHT 固定段的 typed Attribute（字段进 FIELD_REGISTRY → label/控件/过滤）。
# .schema 降级与原裸 tuple 逐字节等价（Int→'i'/Float→'f'），codec 与 on-disk 尺寸不变。
TUBELIGHT_ATTR = Attribute(size=124, fields=[
    Int("typeFlag"),                                   # off0  原 unkn0_0
    Int("unknFixed0_1"),                               # off4
    # off8 原 int unknEnum0_2：全语料(22 块/17 文件)只有 2 种取值 13434880/13435136=
    # 0x00CD0000/0x00CD0100，拆成 4 字节可见：byte0 恒 0x00，byte2 恒 0xCD（未初始化占位，
    # 同 off100 unkn5_1 的签名），byte3 恒 0x00——只有 byte1(0/1) 是真实数据，仿
    # RIBBON.tailTiedToBone 先例拆分。样本量小（仅 22 块），结论待更多语料验证。
    Byte("unknFixed0_2a"),                             # off8  恒 0x00
    Bool("unknBool0_2", backing='B'),                  # off9  真实数据，含义未知
    Byte("unknFixed0_2_cd"),                           # off10 恒 0xCD，未初始化占位
    Byte("unknFixed0_2b"),                              # off11 恒 0x00
    Float("unkn1_0"),                                  # off12 可能为纹理滚动速度
    Float("unknFixed1_1"),                             # off16 含义不明
    Float("lightIntensity", label_zh="光照强度"),      # off20
    Float("lightIntensityJitter", label_zh="光照强度抖动"),  # off24
    Float("columnLengthModifier", label_zh="光柱长度修正"),  # off28
    Float("columnRadius", label_zh="光柱半径"),        # off32
    Float("columnRadiusJitter", label_zh="光柱半径抖动"),    # off36
    Float("columnEdgeSoftness", label_zh="光柱边缘柔化"),    # off40
    Float("unkn1_8"),                                  # off44 可能为核心亮度
    Float("unknFixed1_9"),                             # off48 含义不明
    Float("unkn1_10"),                                 # off52 可能与光柱长度有关
    Float("unkn2_0"),                                  # off56
    Float("unkn2_1"),                                  # off60 含义不明
    Int("unknFixed3_0"),                               # off64
    Int("unknFixed3_1"),                               # off68
    Int("unkn3_2"),                                    # off72
    Int("headColorEpvSlot", label_zh="起点颜色 EPV 颜色槽"),  # off76
    Int("headColor", label_zh="光柱起点颜色"),          # off80 打包 RGBA int
    Float("columnLength", label_zh="光柱长度"),         # off84 起点 headColor→终点 tailColor
    Float("tailGlowSpread", label_zh="尾光扩散(变长+边缘虚化)"),  # off88 一参两效
    Float("backFaceTintMode", label_zh="反向区域受起点色染色"),   # off92 与 front 镜像
    Int("unknFixed5_0"),                               # off96  通常为 24
    Int("unkn5_1"),                                    # off100 恒 0xCDCDCDCD 未初始化标记
    Int("unknFixed6a_0"),                              # off104
    Int("tailColor", label_zh="光柱终点颜色"),          # off108 打包 RGBA int
    Float("tailPlaneOffset", label_zh="终点发光面前后位置"),  # off112
    Float("unkn6b_1"),                                 # off116 可能与发光光圈相关
    Float("frontFaceTintMode", label_zh="朝向区域受终点色染色"),  # off120 0=不受影响 1=受影响
])
_TUBELIGHT_FIXED_SCHEMA = TUBELIGHT_ATTR.schema
assert _schema_size(_TUBELIGHT_FIXED_SCHEMA) == 124, \
    f"_TUBELIGHT_FIXED_SCHEMA size mismatch: {_schema_size(_TUBELIGHT_FIXED_SCHEMA)}"


def unpack_tubelight(data: bytes, off: int = 0):
    """Unpack TubeLight data_bytes (124B fixed + length-prefixed path)。"""
    values, off = unpack(_TUBELIGHT_FIXED_SCHEMA, data, off)
    (path_len,) = struct.unpack_from('<i', data, off)
    off += 4
    values['path_len'] = path_len
    values['path'] = data[off:off + path_len]   # 原始字节（含末尾 null）
    off += path_len
    return values, off


def pack_tubelight(values: dict) -> bytes:
    """Pack TubeLight values dict back to bytes（path verbatim，含其 null）。"""
    out = pack(_TUBELIGHT_FIXED_SCHEMA, values)
    path = values['path']
    out += struct.pack('<i', len(path))
    out += path
    return out


# ─────────────────────────────────────────────────────────────────────────────
# EmitterShapeMesh (variable: 32B fixed + null-terminated path1，块在 null 处结束)
#
# BT (EFX_Crimson.bt)：int unkn0[2](8)+long unkn1[3](12)+byte unkn2[8](8)+
#   int unkn3(4) = 32B fixed，随后 null-terminated path1（Mod3 路径）。
# 空路径时块为 33B（32B fixed + 单个 null）。全字段 int/byte → 天然字节完美。
# ─────────────────────────────────────────────────────────────────────────────

_EMITTERSHAPEMESH_FIXED_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn0_0
    ('unknFixed0_1', 'i'),   # 8B
    ('unkn1_0', 'i'),
    ('unkn1_1', 'i'),
    ('unkn1_2', 'i'),   # 12B (long=4B)
    ('unknFlag2_0', 'b'),
    ('ddsUsageType', 'b'),  # 原 unkn2_1；EFX.bt(新，refs/EFX_Subtypes.bt)具名，语义未实机验证
    ('unknFlag2_2', 'b'),
    ('visconIndex', 'b'),   # 原 unkn2_3；EFX.bt(新)具名，语义未实机验证
    ('unknEnum2_4', 'b'),
    ('unknEnum2_5', 'b'),
    ('unknEnum2_6', 'b'),
    ('unknEnum2_7', 'b'),   # 8B
    ('unknBitmask3', 'i'),        # 4B
]
assert _schema_size(_EMITTERSHAPEMESH_FIXED_SCHEMA) == 32, \
    f"_EMITTERSHAPEMESH_FIXED_SCHEMA size mismatch: {_schema_size(_EMITTERSHAPEMESH_FIXED_SCHEMA)}"
EMITTERSHAPEMESH_ATTR = attr_from_legacy(_schema_size(_EMITTERSHAPEMESH_FIXED_SCHEMA), _EMITTERSHAPEMESH_FIXED_SCHEMA)


def unpack_emittershapemesh(data: bytes, off: int = 0):
    """Unpack EmitterShapeMesh（32B fixed + null-term path1）。"""
    values, off = unpack(_EMITTERSHAPEMESH_FIXED_SCHEMA, data, off)
    null = data.index(b'\x00', off)
    values['path1'] = data[off:null]   # 不含 null
    off = null + 1
    return values, off


def pack_emittershapemesh(values: dict) -> bytes:
    """Pack EmitterShapeMesh values dict back to bytes（path1 + null）。"""
    out = pack(_EMITTERSHAPEMESH_FIXED_SCHEMA, values)
    out += values['path1'] + b'\x00'
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Layout (变长: 24B fixed prefix + LayoutBank_Block(嵌套变长，opaque)，恒无尾巴)
#
# EFX_Crimson.bt（MHW-EFX-Template-master）：
#   long type + int unkn0[2] + long unkn1[4] + LayoutBank_Block spb。
# LayoutBank_Block 是 Root 的 LayoutBank 子条目共用的同一个 nested
# repeat-until-sentinel 编码（见 _walk_layoutbank_block），本身不可平铺展开成
# 标量字段，原样 opaque 存取——只有前面固定的 24B 前缀是真正的标量。
#
# ⚠ 2026-07 曾误判"LayoutBank_Block 结束后偶尔多出的 20B 是具名引用尾巴"——  
# 实为 bug：那 20B 其实是*下一个 Main Entry 自己的 20B 头*（type+unkn0+
# attr_count+null+timl_length）。触发条件：LAYOUT 恰好是所在 entry 的最后一个
# 属性时，边界判定误把"下一个 entry 的任意 body_type 哈希"当成"不像边界"，
# 从而多吞 20B，错位了下一个 entry 的头部（用户拿官方 010 模板实测反证：被
# 误判"孤儿空属性"的 entry 实际有 14 个属性）。结论：LAYOUT 没有可选尾巴，  
# 恒为 24B 前缀 + LayoutBank_Block，见 efxfile.py::_known_attr_size 的 LAYOUT
# 分支（已改回直接返回，不做落点猜测）。
# ─────────────────────────────────────────────────────────────────────────────

def _walk_layoutbank_block(data: bytes, pos: int) -> int:
    """
    Walk one LayoutBank_Block starting at *pos*, return the position right after it.
    供 Root 的 LayoutBank 子条目解析（efxfile.py::_parse_layout_bank）与 Layout
    主属性（unpack_layout/_known_attr_size 的 LAYOUT 分支）共用。

    LayoutBank_Block = int count(4);
        if count>0: repeated LayoutBank_B until ReadInt()==-1, then long end(4).
    LayoutBank_B = int block_type(4) + type-dependent UN 数组:
        0<block_type<6 → UN p[count*2]
        block_type==0 or ==6 → UN p[count*3]
        block_type==7 → int unkn0 + UN p[count*2*unkn0]
    """
    count = struct.unpack_from('<i', data, pos)[0]
    pos += 4
    if count > 0:
        while True:
            sentinel = struct.unpack_from('<i', data, pos)[0]
            if sentinel == -1:
                pos += 4  # consume the -1 sentinel (long end)
                break
            block_type = sentinel
            pos += 4
            if 0 < block_type < 6:
                pos += count * 2 * 4
            elif block_type == 0 or block_type == 6:
                pos += count * 3 * 4
            elif block_type == 7:
                sub_unkn0 = struct.unpack_from('<i', data, pos)[0]
                pos += 4
                pos += count * 2 * sub_unkn0 * 4
            else:
                raise ValueError(f'LayoutBank_B: unknown block_type={block_type} at pos {pos-4}')
    return pos


_LAYOUT_PREFIX_SCHEMA = [
    ('typeFlag', 'i'),   # 原 unkn0_0
    ('unknFixed0_1', 'i'),
    ('unknEnum1_0', 'i'),
    ('unknEnum1_1', 'i'),
    ('unknFixed1_2', 'i'),
    ('unknFixed1_3', 'i'),
]
assert _schema_size(_LAYOUT_PREFIX_SCHEMA) == 24, \
    f"_LAYOUT_PREFIX_SCHEMA size mismatch: {_schema_size(_LAYOUT_PREFIX_SCHEMA)}"
# LAYOUT 恒在的 24B 固定前缀（可编辑）；嵌套 LayoutBank_Block + 条件尾巴仍 opaque。
LAYOUT_ATTR = attr_from_legacy(_schema_size(_LAYOUT_PREFIX_SCHEMA), _LAYOUT_PREFIX_SCHEMA)

def unpack_layout(data: bytes, off: int = 0):
    """Unpack Layout（24B fixed + LayoutBank_Block(opaque)，恒无尾巴）。"""
    values, off = unpack(_LAYOUT_PREFIX_SCHEMA, data, off)
    bank_start = off
    bank_end = _walk_layoutbank_block(data, bank_start)
    values['layoutbank_bytes'] = data[bank_start:bank_end]
    off = bank_end
    return values, off


def pack_layout(values: dict) -> bytes:
    """Pack Layout values dict back to bytes。"""
    out = pack(_LAYOUT_PREFIX_SCHEMA, values)
    out += values['layoutbank_bytes']
    return out


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

    # BILLBOARD2D: fixed 116B（path_len @ 104, unkn5 @ 108-115）+ path[path_len] @ 116
    if type_hash == BILLBOARD2D:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_b = data_bytes[116:116 + path_len]
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

    # TUBELIGHT: fixed 124B + path_len(4)@124 + path[path_len]（path_len 含末尾 null）
    if type_hash == TUBELIGHT:
        (path_len,) = struct.unpack_from('<i', data_bytes, 124)
        path_b = data_bytes[128:128 + path_len].rstrip(b'\x00')
        return [_path_bytes_to_str(path_b)]

    # EMITTERSHAPEMESH: fixed 32B + null-term path1（块在 null 处结束）
    if type_hash == EMITTERSHAPEMESH:
        null = data_bytes.index(b'\x00', 32)
        path_b = data_bytes[32:null]
        return [_path_bytes_to_str(path_b)]

    # TONEMAPFILTER: fixed 24B + path_len(4)@24 + path[path_len]（path_len 含末尾 null）
    if type_hash == TONEMAPFILTER:
        (path_len,) = struct.unpack_from('<i', data_bytes, 24)
        path_b = data_bytes[28:28 + path_len].rstrip(b'\x00')
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


    # Layout：无嵌入路径（24B fixed + LayoutBank_Block(opaque) + 可选 20B tail），
    # 返回空列表，只为了让 CUSTOM_FIELD_SCHEMA_MAP 里的 24B 固定前缀字段展开生效。
    if type_hash == LAYOUT:
        return []

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

    # ── BILLBOARD2D ──
    # 结构：[0..103]=fixed verbatim + path_len(4)@104 + [108..115]=unkn5 verbatim + path  
    if type_hash == BILLBOARD2D:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:116]
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

    # ── TUBELIGHT ──
    # 结构：[0..123] verbatim + path_len(4) + path（含末尾 null）。  
    # path_len 计入 null，故新 path 字节 = new_path + \x00，path_len = 其长度。
    if type_hash == TUBELIGHT:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0]) + b'\x00'
        return (data_bytes[:124]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── EMITTERSHAPEMESH ──
    # 结构：[0..31] verbatim (32B fixed) + new_path + \x00  
    if type_hash == EMITTERSHAPEMESH:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return data_bytes[:32] + new_path_b + b'\x00'

    # ── TONEMAPFILTER ──
    # 结构：[0..23] verbatim (24B fixed) + path_len(4) + path（含末尾 null）。  
    # path_len 计入 null，故新 path 字节 = new_path + \x00，path_len = 其长度。
    if type_hash == TONEMAPFILTER:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0]) + b'\x00'
        return (data_bytes[:24]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

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


    # Layout：无嵌入路径，new_paths 恒为空，原样返回（24B 前缀字段
    # 改动走 Phase A 的 rebuild_custom_field_attribute 覆盖，不经过这里）
    if type_hash == LAYOUT:
        return data_bytes

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
    # 新增变长路径类型
    TUBELIGHT,
    EMITTERSHAPEMESH,
    BILLBOARD2D,
    TONEMAPFILTER,
    # 无嵌入路径但需要 Phase A 固定字段展开：extract_paths/rebuild_with_paths 均按 0 路径处理
    LAYOUT,
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
    # loopingMode 现为单字节 Bitmask（4 个 BitEnum 段），UI 经弹窗渲染；不再拆成 3 个子字节。
    UVSEQUENCE:  _UVSEQUENCE_FIXED_SCHEMA,
    # MESH：174B Mod3Properties + 1B BeginMod3（unpack_mesh 单独读 BeginMod3，
    # 故拼上 ('BeginMod3','B') 使其也可编辑）；path1/path2 由 codec 处理，不在 schema。
    MESH:        _MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')],
    RIBBONBLADE: _RIBBONBLADE_FIXED_SCHEMA,
    STRAINRIBBON:_STRAINRIBBON_FIXED_SCHEMA,
    LIGHTNING:   _LIGHTNING_FIXED_SCHEMA,
    RGBWATER:    _RGBWATER_FIXED_SCHEMA,
    TURBULENCE:  [('typeFlag', 'i')] + _TURBULENCE_AFTER_PATH_SCHEMA,
    # applicationRule 现为 int Bitmask（BitDef×2 混合位 + BitEnum 互斥组），UI 经弹窗渲染；
    # 不再拆成 3 个子 int 字段。编辑段 == 各自的 _*_EDIT_SCHEMA（与 ATTR/codec 同字段序）。
    BILLBOARD3D: _BILLBOARD3D_EDIT_SCHEMA,
    PLANE:       _PLANE_EDIT_SCHEMA,
    TUBELIGHT:        _TUBELIGHT_FIXED_SCHEMA,
    EMITTERSHAPEMESH: _EMITTERSHAPEMESH_FIXED_SCHEMA,
    BILLBOARD2D:      [e for e in _BILLBOARD2D_FIXED_SCHEMA if e[0] != 'path_len'],
    # TonemapFilter：3 个 fixed 标量字段（unkn0[2]/unkn1/unkn2[3]）；path/path_len
    # 由 codec 处理、不入 schema，path 走通用 STRING-item↔bytes-key 路径回写。
    TONEMAPFILTER:    _TONEMAPFILTER_FIXED_SCHEMA,
    # Layout：暴露恒在的 24B fixed 前缀；LayoutBank_Block(嵌套变长) 与尾段
    # （20B，present-conditional，见 unpack_layout 顶部注释）都不在此表，但
    # unpack_layout/pack_layout 会原样保留（未编辑字段精确回填）。
    LAYOUT:           _LAYOUT_PREFIX_SCHEMA,
}


def custom_field_schema(type_hash: int):
    """返回该 custom 类型的可编辑标量字段 schema；不在表内返回 None。"""
    return CUSTOM_FIELD_SCHEMA_MAP.get(type_hash)


# ─────────────────────────────────────────────────────────────────────────────
# 变长块 on-disk 尺寸：从 codec schema 派生，供 efxfile._known_attr_size 定位块边界。
# ─────────────────────────────────────────────────────────────────────────────

def _sz_no_path(schema):
    """schema 字节数，排除 path/path_len（这两者由 codec 单独处理，不计入 fixed 段）。"""
    return _schema_size([e for e in schema if e[0] not in ('path', 'path_len')])


def _bb2d_before_after():
    """BILLBOARD2D 的 path_len 是 _BILLBOARD2D_FIXED_SCHEMA 内的一个字段——在它处切成
    before/after 两段（after 去掉 path）。"""
    s = _BILLBOARD2D_FIXED_SCHEMA
    i = next(k for k, e in enumerate(s) if e[0] == 'path_len')
    return s[:i], [e for e in s[i + 1:] if e[0] != 'path']


# path_len 尾巴族：on-disk 布局 `4(类型哈希) + before + path_len(4) + after(+path[path_len])`，
# after 为空即 path_len 紧贴 before 末尾，非空即 path_len 夹在中间（其后还有固定字段）。
# ⚠ before/after 一律取 **CODEC 侧** `_XXX_FIXED_SCHEMA`（on-disk 真相）——**不能**用
#   CUSTOM_FIELD_SCHEMA_MAP：那是 UI 编辑版，会把单字段拆成多个（applicationRule→3×int/+8B、
#   UVSEQUENCE.loopingMode→3×byte/+2B），字节数对不上。TURBULENCE 的 path 物理上在 after 之前，
#   但 size/偏移只看 before/after 字节数，公式一致。
_PATHLEN_TAIL_LAYOUT = {
    # after 为空（path_len 紧贴 before 末尾）
    LIGHTNING:     (_LIGHTNING_FIXED_SCHEMA,     []),
    RGBWATER:      (_RGBWATER_FIXED_SCHEMA,      []),
    STRAINRIBBON:  (_STRAINRIBBON_FIXED_SCHEMA,  []),
    TUBELIGHT:     (_TUBELIGHT_FIXED_SCHEMA,     []),
    TONEMAPFILTER: (_TONEMAPFILTER_FIXED_SCHEMA, []),
    RIBBONBLADE:   (_RIBBONBLADE_FIXED_SCHEMA,   []),
    UVSEQUENCE:    (_UVSEQUENCE_FIXED_SCHEMA,    []),
    # after 非空（path_len 夹在中间，其后还有固定字段）
    BILLBOARD3D:   (_BILLBOARD3D_FIXED_SCHEMA,   _BILLBOARD3D_EXTRAS_SCHEMA),
    PLANE:         (_PLANE_DDS_SCHEMA,           _PLANE_EXTRAS_SCHEMA),
    TURBULENCE:    ([('typeFlag', 'i')],         _TURBULENCE_AFTER_PATH_SCHEMA),
    BILLBOARD2D:   _bb2d_before_after(),
}


def custom_on_disk_size(type_hash: int, data: bytes, pos: int):
    """变长块（path_len 尾巴族）的 on-disk 总字节数（含 4B 类型哈希）；不属此族返回 None。

    布局 `4(类型哈希) + before + path_len(4) + after(+path[path_len])`，before/after 取 codec schema：
    size = 4 + sz(before) + 4 + sz(after) + path_len；path_len 读在 pos + 4 + sz(before)。
    path_len 越界（负/异常大）返回 None，交由调用方 forward-scan 兜底（保留原分支对损坏数据的降级行为）。
    """
    layout = _PATHLEN_TAIL_LAYOUT.get(type_hash)
    if layout is None:
        return None
    before, after = layout
    base = 4 + _sz_no_path(before)
    try:
        (path_len,) = struct.unpack_from('<i', data, pos + base)
    except struct.error:
        return None
    if path_len < 0 or path_len > 0x100000:
        return None
    return base + 4 + _sz_no_path(after) + path_len


# null 结尾字符串族：定长前缀 + N 个 `\0` 结尾字符串（无 path_len）。前缀字节数从 **codec**
# schema 派生（同上，不用 UI 版 CUSTOM_FIELD_SCHEMA_MAP），尾巴长度不可 schema 化、保留 `\0`
# 扫描。值 =(fixed_schema, n_strings)。
_NULLSTR_TAIL_LAYOUT = {
    MESH:             (_MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')], 2),  # path1 + path2
    RIBBON:           (_RIBBON_FIXED_SCHEMA, 1),
    EMITTERSHAPEMESH: (_EMITTERSHAPEMESH_FIXED_SCHEMA, 1),
}


def custom_nullstr_size(type_hash: int, data: bytes, pos: int):
    """定长前缀 + N 个 `\\0` 结尾字符串的变长块 on-disk 总字节数（含 4B 类型哈希）；不属此族返回
    None。前缀 = 4 + _sz_no_path(fixed)，尾巴逐个扫 `\\0`（含终止符）。找不到 `\\0`（越界/损坏）
    → None，交调用方 forward-scan 兜底。
    """
    layout = _NULLSTR_TAIL_LAYOUT.get(type_hash)
    if layout is None:
        return None
    fixed, n = layout
    p = pos + 4 + _sz_no_path(fixed)
    try:
        for _ in range(n):
            p = data.index(b'\x00', p) + 1
    except ValueError:
        return None
    return p - pos
