# -*- coding: utf-8 -*-
"""变长或分派型属性块的手写编解码。

维护约束：
- ``'_custom'`` schema 哨兵必须在本模块提供成对的 ``unpack_<TYPE>`` 与 ``pack_<TYPE>``。
- 每个 decoder 返回 ``(values, new_off)``；encoder 必须按输入字段和原有布局重建等价字节。
- path 等变长尾部的长度字段由 encoder 从 bytes 计算，不能信任编辑字典中的旧长度。
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
    BITS_APPLICATION_RULE, BITS_LOOPING_MODE, BITS_LIGHT_GROUP, BITS_MESH_DRAW,
    BITS_PLANE_UNKN5_1,
    ENUM_LOOPING_ORIENTATION, ENUM_MESH_TRACKING_FLAGS, ENUM_RIBBON_MODE,
    ENUM_RIBBON_UV_SCALE_MODE,
    _AXIS_DIRECTION6, _TRANSFORM_ROT_ORDER,
)
from ..hashes import *  # noqa: F401,F403  —— 各 custom 类型 hash 常量

# 变长类型以 ``('_custom', None)`` 哨兵分派到本模块的成对 codec


# UVSequence：固定字段、path 长度和 path bytes

_UVSEQUENCE_FIXED_SCHEMA = [
    ('typeFlag',                'i'),
    # 与 sequenceNoJitter 保持命名配对，供 UI 合并 value/jitter
    ('sequenceNo',                'i'),
    ('sequenceNoJitter',          'i'),
    ('patternNo',           'i'),
    ('patternNoJitter',     'i'),
    ('playSpeed',          'f'),
    ('playSpeedJitter',    'f'),
    ('playSpeedCoef',   'f'),
    ('playSpeedCoefJitter', 'f'),
    # 4 字节字段拆为 loopingMode、loopingOrientation 与保留 padding
    ('loopingMode',             'B'),
    ('loopingOrientation',      'B'),
    ('loopingPad',              'h'),
]

_UVSEQUENCE_FIXED_SIZE = _schema_size(_UVSEQUENCE_FIXED_SCHEMA)  # = 40

EXTERN_UVSEQUENCE_SCHEMA = _UVSEQUENCE_FIXED_SCHEMA + [
    ('unkn_tail0', 'i'),
    ('unkn_tail1', 'B'),
]
assert _schema_size(EXTERN_UVSEQUENCE_SCHEMA) == 45, \
    f"EXTERN_UVSEQUENCE_SCHEMA size mismatch: {_schema_size(EXTERN_UVSEQUENCE_SCHEMA)}"

# loopingMode 由 Bitmask 的四个 BitEnum 段建模；codec 保持裸字节
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


# Billboard3D：固定字段、path 长度、extra 字段和 path bytes

_BILLBOARD3D_FIXED_SCHEMA = [
    ('typeFlag',                   'i'),
    ('applicationRule',            'i'),
    ('color',                      ('XYZ', 2)),  # TIML DT 0x58689812("Color")
    ('colorRange',                 ('XYZ', 2)),  # TIML DT 0xC216C23D("ColorRange")
    ('brightness',                 'f'),  # TIML DT 0x9F1E012E("ColorRate")
    # 实际抖动幅度是本字段值的两倍
    ('brightnessJitter',           'f'),
    ('useColorRange',              'i'),  # bool
    ('blendMode',                  'i'),
    ('correctColorNo',             'i'),
    ('colorRangeCorrectColorNo',   'i'),
    ('rotation',                   'f'),  # TIML DT 0x2FF50558("Rotation")
    ('rotationJitter',             'f'),
    ('scale',                      'f'),  # TIML DT 0x0EBAEC37("SizeScalar")
    ('scaleJitter',                'f'),
    ('width',                      'f'),  # TIML DT 0x241CAED2("SizeX")
    ('widthJitter',                'f'),
    ('height',                     'f'),  # TIML DT 0x531B9E44("SizeY")
    ('heightJitter',               'f'),
    ('flowmapSpeed',               'f'),
    ('flowmapSpeedJitter',         'f'),
    ('flowmapSpeedCoef',        'f'),
    ('flowmapSpeedCoefJitter',  'f'),
    ('flowmapStrength',            'f'),
    ('flowmapStrengthJitter',      'f'),
    ('flowmapStrengthCoef','f'),
    ('flowmapStrengthCoefJitter', 'f'),
]

# Billboard3D extras：flag、数值/倍率对和 LightGroup。
_BILLBOARD3D_EXTRAS_SCHEMA = [
    ('divideNum', 'i'),
    ('enableGPUParticle', 'i'),
    ('fieldInfluenceRate', 'f'),
    ('fieldInfluenceRateMultiplier', 'f'),
    ('lightGroup', 'i'),
    ('unknFlag9', 'i'),
]

EXTERN_BILLBOARD3D_SCHEMA = (
    _BILLBOARD3D_FIXED_SCHEMA + _BILLBOARD3D_EXTRAS_SCHEMA + [
        ('unkn_tail0', 'i'),
        ('unkn_tail1', 'B'),
    ]
)
assert _schema_size(EXTERN_BILLBOARD3D_SCHEMA) == 133, \
    f"EXTERN_BILLBOARD3D_SCHEMA size mismatch: {_schema_size(EXTERN_BILLBOARD3D_SCHEMA)}"


# applicationRule 由 Bitmask/BitEnum 建模；codec 保持裸 int


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


# 编辑 schema 排除 path/path_len；UI 字段与此 schema 对应
_BILLBOARD3D_EDIT_SCHEMA = [
    e for e in (_BILLBOARD3D_FIXED_SCHEMA + _BILLBOARD3D_EXTRAS_SCHEMA)
    if e[0] not in ('path', 'path_len')
]
BILLBOARD3D_ATTR = attr_from_legacy(
    _schema_size(_BILLBOARD3D_EDIT_SCHEMA), _BILLBOARD3D_EDIT_SCHEMA,
    overrides={
        'applicationRule': Bitmask('applicationRule', BITS_APPLICATION_RULE, label_zh="应用规则"),
        'useColorRange':   Bool('useColorRange', label_zh="启用颜色范围"),
        # 底层为 0/1，作为自发光开关显示
        'blendMode':       Bool('blendMode', label_en="Enable Emissive", label_zh="启用自发光"),
        'enableGPUParticle': Bool('enableGPUParticle', label_zh="启用 GPU 粒子"),
        'lightGroup': Bitmask('lightGroup', BITS_LIGHT_GROUP, all_value=255, strict=True,
                               label_zh="光照组"),
        'correctColorNo': Int('correctColorNo', label_zh="EPV 颜色修正槽位"),
        # colorRange 的专属槽位为位置推断，保留 ``?`` 标记
        'colorRangeCorrectColorNo': Int('colorRangeCorrectColorNo', label_en="Correct Color Range No?",
                                         label_zh="EPV 颜色修正槽位?"),
    },
)


# Billboard2D：固定字段和 path bytes

_BILLBOARD2D_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('applicationRule', 'i'),
    ('color',             ('XYZ', 2)),
    ('colorRange',        ('XYZ', 2)),
    ('brightness',        'f'),
    ('brightnessJitter',  'f'),
    ('useColorRange',     'i'),
    ('blendMode',         'i'),
    ('correctColorNo',            'i'),
    ('colorRangeCorrectColorNo',  'i'),
    # 固定值与 jitter 成对，供 UI 作为单个显示单元
    ('rotation', 'f'),
    ('rotationJitter', 'f'),
    ('scale',    'f'),
    ('scaleJitter',      'f'),
    ('width',            'f'),
    ('widthJitter',      'f'),
    ('height',           'f'),
    ('heightJitter',     'f'),
    ('flowmapSpeed', 'f'),
    ('flowmapSpeedJitter', 'f'),
    ('flowmapSpeedCoef', 'f'),
    ('flowmapSpeedCoefJitter', 'f'),
    ('flowmapStrength', 'f'),
    ('flowmapStrengthJitter', 'f'),
    ('flowmapStrengthCoef', 'f'),
    ('flowmapStrengthCoefJitter', 'f'),
    ('path_len',         'i'),
    ('unknFixed5_0', 'i'),
    ('unknEnum5_1', 'i'),
]
assert _schema_size(_BILLBOARD2D_FIXED_SCHEMA) == 116, \
    f"_BILLBOARD2D_FIXED_SCHEMA size mismatch: {_schema_size(_BILLBOARD2D_FIXED_SCHEMA)}"
# 编辑 schema 排除 path_len
_BILLBOARD2D_EDIT_SCHEMA = [e for e in _BILLBOARD2D_FIXED_SCHEMA if e[0] != 'path_len']
BILLBOARD2D_ATTR = attr_from_legacy(
    _schema_size(_BILLBOARD2D_EDIT_SCHEMA), _BILLBOARD2D_EDIT_SCHEMA,
    overrides={
        'useColorRange': Bool('useColorRange', label_zh="启用颜色范围"),
        # 底层为 0/1，作为自发光开关显示
        'blendMode':     Bool('blendMode', label_en="Enable Emissive", label_zh="启用自发光"),
        # colorRange 的专属槽位为结构类推，保留 ``?`` 标记
        'correctColorNo': Int('correctColorNo', label_zh="EPV 颜色修正槽位"),
        'colorRangeCorrectColorNo': Int('colorRangeCorrectColorNo', label_en="Correct Color Range No?",
                                         label_zh="EPV 颜色修正槽位?"),
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


# Mesh：174 B 固定段、BeginMod3 和两个 NUL 终止路径。
# color/colorRange 与 emissiveColor/emissiveColorRange 是独立通道；范围禁用位同时
# 使两条通道使用静态颜色。

_MOD3_PROPERTIES_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed0_1', 'i'),
    ('CD1',                     'i'),
    # color 通道的强度系数与其 jitter
    ('colorRate',               'f'),  # TIML DT 0x9F1E012E("ColorRate")
    ('colorRateJitter',         'f'),
    # emissiveColor 通道的强度系数与其 jitter
    ('emissiveColorRate',       'f'),  # TIML DT 0x18C577DE("EmissiveColorRate")
    ('emissiveColorRateJitter', 'f'),
    # 不属于 rotation；三轴 rotation 紧随其后
    ('unknFloat0',              'f'),
    ('unknFloat1',              'f'),
    # rotation 为三组 value/jitter，前两个 float 不可并入该字段
    ('rotation',                ('XYZ', 0)),
    ('scale',                   ('XYZ', 0)),
    ('global_scale',            'f'),  # TIML DT 0x0EBAEC37("SizeScalar")
    ('global_scale_jitter',     'f'),
    ('visconIndex',             'i'),
    ('visconIndexJitter',       'i'),
    ('color',                   'colour'),  # TIML DT 0x58689812("Color")
    ('colorRange',              'colour'),
    ('emissiveColor',           'colour'),
    ('emissiveColorRange',      'colour'),
    ('unknEnum7_0', 'i'),
    ('unknFlag7_1', 'i'),
    ('rotationOrder', 'i'),
    ('tracking_flags',          'i'),
    ('baseAxis',                'i'),
    ('affectedByLight',         'i'),
    ('shadowCastBitflag',       'i'),
    ('epv_color_slot1',         'i'),
    ('unknEnum5',                   'i'),
    ('epv_color_slot2',         'i'),
    ('unknFixed6_1',                 'i'),
    ('enableIntensity1',        'B'),
    ('useColorRange',           'B'),
    ('enableIntensity2',        'B'),
    ('useEmissiveColor',        'B'),
    ('useEmissiveColorRange',   'B'),
    ('enableEmissiveIntensity', 'B'),
    # 非零时强制 color 与 emissiveColor 取静态值，覆盖两个 useColorRange 开关
    ('disableAllColorRange',    'B'),
    ('unknFlag_cm2_3',              'B'),
    # unknBool0~3 由一个 int randommizeViscon 拆开，unknBool4~5 由一个 short NULL1 拆开
    ('unknBool0',                    'B'),
    ('unknBool1',                    'B'),
    ('unknBool2',                    'B'),
    ('unknBool3',                    'B'),
    ('unknBool4',                    'B'),
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
    'affectedByLight', BITS_LIGHT_GROUP, all_value=255, strict=True,
    label_zh="受光照影响",
)
_mesh_ovr['baseAxis'] = Enum('baseAxis', _AXIS_DIRECTION6, label_zh="基准轴")
_mesh_ovr['shadowCastBitflag'] = Bitmask(
    'shadowCastBitflag', BITS_MESH_DRAW, strict=True, label_zh="绘制位标志",
)
_mesh_ovr['visconIndex'] = Int('visconIndex', label_zh="可见条件索引")
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


# Ribbon：360 B 固定段和 NUL 终止路径

_RIBBON_FIXED_SCHEMA = [
    ('typeFlag',                 'i'),
    ('section_length',           'i'),
    ('spacer0',                  'i'),
    ('color',                    ('XYZ', 2)),
    # 低字节为真实 bool，剩余三个字节为保留填充
    ('useColorRange',            'B'),
    ('spacer1',                  ('B', 3)),
    ('colorRange',               ('XYZ', 2)),
    ('blendMode',                'B'),
    ('spacer2',                  ('B', 3)),
    ('brightness',               'f'),
    ('brightnessJitter',         'f'),
    ('ribbonMode',                   'i'),
    ('scale',                    'f'),  # TIML DT 0x0EBAEC37("SizeScalar")
    ('scale_jitter',             'f'),
    ('width',                    'f'),  # TIML DT 0xF0DF339B("WidthSize")
    ('width_jitter',             'f'),
    ('length',                   'f'),  # TIML DT 0xF92E647B("Length")
    ('length_jitter',            'f'),
    # 长度方向的贴图缩放由 uvScaleMode 决定是否生效；宽度方向以中心缩放
    ('uvScaleMode',              'i'),
    ('uvScaleLength',            'f'),
    ('uvScaleLengthJitter',      'f'),
    ('uvScaleWidth',             'f'),
    # 沿条带长度方向的细分数
    ('subdivisionCount',         'i'),
    # 开启后每段覆盖的轨迹时长随 trailTimeScale 缩放，与细分数相乘决定条带长度
    ('useTrailTimeScale',        'i'),
    ('trailTimeScale',           'f'),
    ('baseAxis',                 'i'),
    ('rotationOrder',            'i'),
    # rotationX/Y/Z 的 value 与 jitter 在字节上交错排列，不是顺序成对，改动顺序会错位。
    # ⚠ 三轴与物理 X/Y/Z 的对应关系未坐实
    ('rotationX',                'f'),
    ('rotationXJitter',          'f'),
    ('rotationYJitter',          'f'),
    ('rotationY',                'f'),
    ('rotationZJitter',          'f'),
    ('rotationZ',                'f'),
    ('unknFlag16_0_1', 'i'),
    # 低字节固定为 1，高字节为真实 bool
    ('unknFixed16_1_lo',         'B'),
    ('unknBool16_1',             'B'),
    ('unknBool16_2_0',           'B'),
    ('unknBool16_2_1',           'B'),
    # 两个真实 bool，后两个字节为保留填充
    ('unknBool3a',               'B'),
    ('unknBool3b',               'B'),
    ('spacer3',                  ('B', 2)),
    ('unknFixed17',                   'f'),
    ('spacer4',                  'i'),
    ('lengthwise_offset_relative_to_camera', 'f'),
    # 0 时 ribbon 最前端贴近生成位置，1 时整体前移一个相对长度、改为最后端贴近。
    ('spawnAnchorOffset',        'f'),

    # RibbonChain 的恢复、惯性和弹性参数
    ('restoreStrength',          'f'),
    ('restoreStrengthJitter',    'f'),
    ('inertia',                  'f'),
    ('inertiaJitter',            'f'),
    ('springiness',              'f'),
    ('springiness_jitter',       'f'),
    # 低字节为未知 bool，剩余字节为保留填充
    ('unknBool5',                'B'),
    ('spacer5',                  ('B', 3)),
    ('unkn20_0', 'f'),
    ('unkn20_1', 'f'),
    ('unkn20_2', 'f'),
    ('unkn20_3', 'f'),
    ('unkn21',                   'f'),
    ('unkn22_0', 'f'),
    ('lightGroup', 'i'),
    ('unknFlag22_2', 'i'),
    # 低字节为 Flowmap 总开关，剩余字节为保留填充
    ('enableFlowmap',            'B'),
    ('spacer6',                  ('B', 3)),
    # Flowmap 的四组 value/jitter 参数
    ('flowmapSpeed',                     'f'),
    ('flowmapSpeedJitter',               'f'),
    ('flowmapSpeedCoef',              'f'),
    ('flowmapSpeedCoefJitter',        'f'),
    ('flowmapStrength',                  'f'),
    ('flowmapStrengthJitter',            'f'),
    ('flowmapStrengthCoef',      'f'),
    ('flowmapStrengthCoefJitter','f'),
    # flowmapReverse 仅在 flowmapPlayOnce 启用时生效；仍保留无效组合
    ('flowmapPlayOnce',          'B'),
    ('flowmapReverse',           'B'),
    ('unkn24',                   ('B', 2)),
    ('epvcolor_0',               'i'),
    ('epvcolor_1',               'i'),
    # 低字节为未知 bool，剩余字节为保留填充
    ('unknBool7',                'B'),
    ('spacer7',                  ('B', 3)),
    ('base_width_multiplier',    'f'),
    ('base_opacity',             'f'),
    ('tip_width_multiplier',     'f'),
    ('tip_opacity',              'f'),
    # 低字节为渐隐长度开关，剩余字节为保留填充
    ('enableFadeLength',         'B'),
    ('spacer8',                  ('B', 3)),
    # 从两端 opacity 过渡至中段的相对长度；enableFadeLength 关闭时两者均按 1 计
    ('base_fade_length',         'f'),
    ('tip_fade_length',          'f'),
    # 两个独立字节：可见性修正和 flap 总开关
    ('visiblePreview',           'B'),
    ('enableFlap',               'B'),
    ('spacer9',                  'h'),
    # 两组可叠加的 flap 参数，不按条带首尾区分
    ('flap1Frequency',           'f'),
    ('flap1FrequencyJitter',     'f'),
    ('flap1Amount',              'f'),
    ('flap1AmountJitter',        'f'),
    ('flap2Frequency',           'f'),
    ('flap2FrequencyJitter',     'f'),
    ('flap2Amount',              'f'),
    ('flap2AmountJitter',        'f'),
    ('unknFixed28_0',            'B'),
    ('enableGravity',            'B'),
    ('gravityLocalSpace',        'B'),
    ('spacer28',                 ('B', 13)),
    ('gravityX',                 'f'),
    ('gravityY',                 'f'),
    ('gravityZ',                 'f'),
    ('unknFixed28_param3',      'f'),
]
assert _schema_size(_RIBBON_FIXED_SCHEMA) == 360, \
    f"_RIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBON_FIXED_SCHEMA)}"
RIBBON_ATTR = attr_from_legacy(
    _schema_size(_RIBBON_FIXED_SCHEMA), _RIBBON_FIXED_SCHEMA,
    overrides={
        'baseAxis':       Enum('baseAxis', _AXIS_DIRECTION6, label_zh="基准轴"),
        'rotationOrder':  Enum('rotationOrder', _TRANSFORM_ROT_ORDER, label_zh="旋转顺序"),
        'enableFlowmap':  Bool('enableFlowmap', backing='B', label_zh="启用流动贴图"),
        'unknFlag16_0_1':          Bool('unknFlag16_0_1'),
        'unknBool16_1':            Bool('unknBool16_1', backing='B'),
        'unknBool16_2_0':          Bool('unknBool16_2_0', backing='B'),
        'unknBool16_2_1':          Bool('unknBool16_2_1', backing='B'),
        # 不设 all_value；只有 BILLBOARD3D / MESH 有 255 全选哨兵
        'lightGroup':              Bitmask('lightGroup', BITS_LIGHT_GROUP, strict=True,
                                            label_zh="光照组"),
        'unknFlag22_2':            Bool('unknFlag22_2'),
        'visiblePreview':          Bool('visiblePreview', backing='B', label_zh="可见性修正"),
        'enableFlap':              Bool('enableFlap', backing='B', label_zh="启用抖动"),
        'enableGravity':           Bool('enableGravity', backing='B', label_zh="启用重力"),
        'gravityLocalSpace':       Bool('gravityLocalSpace', backing='B',
                                        label_en="Gravity In Local Space",
                                        label_zh="重力使用本地坐标系"),
        'useColorRange': Bool('useColorRange', backing='B', label_zh="启用颜色范围"),
        'ribbonMode':    Enum('ribbonMode', ENUM_RIBBON_MODE, label_zh="条带模式"),
        'uvScaleMode':   Enum('uvScaleMode', ENUM_RIBBON_UV_SCALE_MODE,
                              label_en="UV Scale Mode", label_zh="长度缩放方式"),
        'uvScaleLength': Float('uvScaleLength', label_en="UV Scale Length",
                               label_zh="长度方向贴图缩放"),
        'uvScaleWidth':  Float('uvScaleWidth', label_en="UV Scale Width",
                               label_zh="宽度方向贴图缩放"),
        # 只有 0/1 两值：开启后亮度生效；混合方式由 SHADERSETTINGS.blendStateType 决定
        'blendMode':     Bool('blendMode', backing='B', label_en="Enable Emissive", label_zh="启用自发光"),
        'useTrailTimeScale': Bool('useTrailTimeScale', label_zh="启用条带时间缩放"),
        'trailTimeScale':    Float('trailTimeScale', label_zh="条带时间缩放"),
        'unknBool3a':  Bool('unknBool3a', backing='B'),
        'unknBool3b':  Bool('unknBool3b', backing='B'),
        'unknBool5':   Bool('unknBool5', backing='B'),
        'unknBool7':   Bool('unknBool7', backing='B'),
        'enableFadeLength': Bool('enableFadeLength', backing='B', label_zh="启用渐隐长度"),
        'flowmapPlayOnce': Bool('flowmapPlayOnce', backing='B', label_zh="流动只播放一次"),
        'flowmapReverse':  Bool('flowmapReverse', backing='B', label_zh="流动逆向播放"),
        # epvcolor_0 覆盖 color，epvcolor_1 覆盖 colorRange
        'epvcolor_0': Int('epvcolor_0', label_zh="EPV 颜色修正槽位"),
        'epvcolor_1': Int('epvcolor_1', label_zh="EPV 颜色修正槽位"),
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


# Plane：固定字段、extra 字段和 path bytes

_PLANE_DDS_SCHEMA = [
    ('typeFlag',           'i'),
    ('applicationRule',    'i'),
    ('color',              ('XYZ', 2)),
    ('colorRange',         ('XYZ', 2)),
    ('brightness',         'f'),
    ('brightnessJitter',  'f'),
    ('useColorRange',      'i'),
    ('blendMode',          'i'),
    ('correctColorNo',            'i'),
    ('colorRangeCorrectColorNo',  'i'),
    # 独立于 XYZ rotation 的平面法线自旋
    ('rotation2',          'f'),
    ('rotation2Jitter',    'f'),
    ('scale',              'f'),
    ('scaleJitter',        'f'),
    ('width',              'f'),
    ('widthJitter',        'f'),
    ('height',             'f'),
    ('heightJitter',       'f'),
    ('flowmapSpeed',       'f'),
    ('flowmapSpeedJitter', 'f'),
    ('flowmapSpeedCoef','f'),
    ('flowmapSpeedCoefJitter', 'f'),
    ('flowmapStrength',    'f'),
    ('flowmapStrengthJitter','f'),
    ('flowmapStrengthCoef','f'),
    ('flowmapStrengthCoefJitter','f'),
]

_PLANE_EXTRAS_SCHEMA = [
    ('unknBitmask5_0', 'i'),
    ('unknEnum5_1', 'i'),
    ('baseAxis', 'i'),
    ('rotationOrder', 'i'),
    ('rotation',('XYZ', 0)),
    ('lightGroup', 'i'),
    ('unknFlag7_1', 'i'),
]


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


# applicationRule 与 BILLBOARD3D 共用位定义
_PLANE_EDIT_SCHEMA = [
    e for e in (_PLANE_DDS_SCHEMA + _PLANE_EXTRAS_SCHEMA)
    if e[0] not in ('path', 'path_len')
]
PLANE_ATTR = attr_from_legacy(
    _schema_size(_PLANE_EDIT_SCHEMA), _PLANE_EDIT_SCHEMA,
    overrides={
        'applicationRule': Bitmask('applicationRule', BITS_APPLICATION_RULE, label_zh="应用规则"),
        'useColorRange':   Bool('useColorRange', label_zh="启用颜色范围"),
        # 底层为 0/1，作为自发光开关显示
        'blendMode':       Bool('blendMode', label_en="Enable Emissive", label_zh="启用自发光"),
        'unknEnum5_1':     Bitmask('unknEnum5_1', BITS_PLANE_UNKN5_1, gate_first=True),
        'baseAxis':        Enum('baseAxis', _AXIS_DIRECTION6, label_zh="基准轴"),
        'rotationOrder':   Enum('rotationOrder', _TRANSFORM_ROT_ORDER, label_zh="旋转顺序"),
        # 没有全选哨兵的证据，不能设置 all_value
        'lightGroup':      Bitmask('lightGroup', BITS_LIGHT_GROUP, strict=True, label_zh="光照组"),
        # colorRange 的专属槽位为结构类推，保留 ``?`` 标记
        'correctColorNo':           Int('correctColorNo', label_zh="EPV 颜色修正槽位"),
        'colorRangeCorrectColorNo': Int('colorRangeCorrectColorNo', label_en="Correct Color Range No?",
                                         label_zh="EPV 颜色修正槽位?"),
    },
)


# RibbonBlade：固定字段、path 长度和 path bytes

_RIBBONBLADE_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed0_1', 'i'),
    ('spacer0',     'i'),
    ('widthDirection', 'i'),
    ('width',       'f'),
    ('length', 'i'),
    ('unknEnum05_1', 'i'),
    ('spacer1',     'i'),
    ('unknFlag07_0', 'i'),
    ('lengthMode', 'i'),
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
    ('spacer3',     'i'),
    ('head',        'EPVColorSlot'),
    ('tailEnd',     'EPVColorSlot'),
    # Flowmap 的四组 value/jitter 参数
    ('flowmapSpeed',                    'f'),
    ('flowmapSpeedJitter',              'f'),
    ('flowmapSpeedCoef',             'f'),
    ('flowmapSpeedCoefJitter',       'f'),
    ('flowmapStrength',                 'f'),
    ('flowmapStrengthJitter',           'f'),
    ('flowmapStrengthCoef',     'f'),
    ('flowmapStrengthCoefJitter', 'f'),
    ('NULL9',       'h'),
]
assert _schema_size(_RIBBONBLADE_FIXED_SCHEMA) == 194, \
    f"_RIBBONBLADE_FIXED_SCHEMA size mismatch: {_schema_size(_RIBBONBLADE_FIXED_SCHEMA)}"
# widthDirection 复用 6 向枚举；length 是连续幅值而非枚举
RIBBONBLADE_ATTR = attr_from_legacy(
    _schema_size(_RIBBONBLADE_FIXED_SCHEMA), _RIBBONBLADE_FIXED_SCHEMA,
    overrides={
        'widthDirection': Enum('widthDirection', _AXIS_DIRECTION6, label_zh="宽度延伸方向"),
        # 开关决定 length 或 maxLengthLimit/contractionSpeed 的编辑路径；可见性规则在 field_visibility
        'lengthMode': Bool('lengthMode', label_zh="启用自定义长度", label_en="Enable Custom Length"),
    },
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


# StrainRibbon：340 B 固定段和末尾 path。
# color、colorRange、useColorRange 构成颜色范围组；相邻四字节拆为两个端点开关、
# Flowmap 总开关和保留字节。spacer00/01/02 的低字节是独立字段，不能合并为 int。
_STRAINRIBBON_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed00_1', 'i'),
    ('unknFixed00_2',               'B'),
    ('spacer00',               ('B', 3)),
    ('color',                  ('XYZ', 2)),
    ('useColorRange',          'B'),
    ('spacer01',               ('B', 3)),
    ('colorRange',             ('XYZ', 2)),
    ('useEmission',            'B'),
    ('spacer02',               ('B', 3)),
    ('emissionStrength',       'f'),
    ('emissionStrengthJitter', 'f'),
    ('spacer03',               'i'),
    ('startPosition',          ('XYZ', 3)),
    ('unknFixed03_06',              'f'),
    ('endPosition',            ('XYZ', 3)),
    ('unknFixed03_10',              'f'),
    ('width',                  'f'),  # TIML DT 0xF0DF339B("WidthSize")
    ('widthJitter',            'f'),
    ('length',                 'f'),  # TIML DT 0xF92E647B("Length")
    ('lengthJitter',           'f'),
    ('startWidth',             'f'),
    ('startOpacity',           'f'),
    ('endWidth',               'f'),
    ('endOpacity',             'f'),
    ('subdivisionCount',       'i'),
    ('unknFixed04_01',              'i'),
    ('uvRepetition',           'i'),
    ('widthwiseUVScalingAlpha','f'),
    ('spacer04',               'f'),  # 出现过非零值，不能当纯占位处理
    ('widthwiseUVScalingBML',  'f'),
    ('endPointScatter',        'B'),        # color3.x（终点扩散开关）
    ('originReleaseFlag',      'B'),        # color3.y（起点解锁标志）
    ('enableFlowmap',          'B'),
    ('color3_w',               'B'),        # 真保留，恒为 0xCD
    # Flowmap 的四组 value/jitter 参数
    ('flowmapSpeed',                     'f'),
    ('flowmapSpeedJitter',               'f'),
    ('flowmapSpeedCoef',              'f'),
    ('flowmapSpeedCoefJitter',        'f'),
    ('flowmapStrength',                  'f'),
    ('flowmapStrengthJitter',            'f'),
    ('flowmapStrengthCoef',      'f'),
    ('flowmapStrengthCoefJitter','f'),
    ('unknEnum06_08_00',           'h'),
    ('unknEnum06_08_01',           'h'),
    # 物理相关参数
    ('lengthBreakpoint',       'f'),
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
    ('endBoneID',              'i'),
    ('positionalAberration_01','i'),
    ('positionalAberration_02','i'),
    # 非零 EPV 槽位覆盖本属性颜色；slot1 对应 color，slot2 对应 colorRange
    ('epv_color_slot1',        'i'),
    ('epv_color_slot2',        'i'),
    ('positionalAberration_05','i'),
    ('displacement',           ('XYZ', 0)), # MT 遗留，24B
    ('displacementToggle',     'i'),
    ('unknEnum09_0', 'i'),
    ('unknFixed09_1', 'f'),
    ('unkn09_2', 'f'),
    ('unkn09_3', 'f'),
    ('unkn09_4', 'f'),   # 20B
    ('unknEnum10_00',              'i'),
    ('angleRelated',           'f'),
    ('angleRelatedJitter',     'f'),
    ('unknEnum11',                 'i'),
    ('unknEnum12_00',              'i'),
    ('unknFixed12_01',              'f'),
    ('unknFixed12_02',              'f'),
    ('unknFixed12_03',              'f'),
    ('unknFixed13',                 'i'),
]
assert _schema_size(_STRAINRIBBON_FIXED_SCHEMA) == 340, \
    f"_STRAINRIBBON_FIXED_SCHEMA size mismatch: {_schema_size(_STRAINRIBBON_FIXED_SCHEMA)}"
# B-backed 开关须保留 backing，确保 schema 字节等价
_STRAINRIBBON_OVR = {
    'enableFlowmap': Bool('enableFlowmap', backing='B', label_zh="启用流动贴图"),
    'useColorRange': Bool('useColorRange', backing='B', label_zh="启用颜色范围"),
    'useEmission':   Bool('useEmission',   backing='B', label_zh="启用自发光"),
}
STRAINRIBBON_ATTR = attr_from_legacy(
    _schema_size(_STRAINRIBBON_FIXED_SCHEMA), _STRAINRIBBON_FIXED_SCHEMA,
    overrides=_STRAINRIBBON_OVR,
)


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


# Turbulence：typeFlag、长度前缀路径和路径后的固定字段

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
]


def unpack_turbulence(data: bytes, off: int = 0):
    """Unpack Turbulence data_bytes (variable-length). Returns (dict, new_off)."""
    (typeFlag,) = struct.unpack_from('<i', data, off)
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


# 编辑 schema 包含 typeFlag 与路径后的固定字段；未知整数保持 int
_TURBULENCE_EDIT_SCHEMA = [('typeFlag', 'i')] + _TURBULENCE_AFTER_PATH_SCHEMA
TURBULENCE_ATTR = attr_from_legacy(_schema_size(_TURBULENCE_EDIT_SCHEMA), _TURBULENCE_EDIT_SCHEMA)


# EXTERNSTRAINRIBBON / EXTERNTURBULENCE 是无真实样本支撑的外推 schema。
# 其布局假设为主属性去除内嵌路径后追加 5 字节尾巴；遇到真实样本前不得将其视为格式事实。

EXTERN_STRAINRIBBON_ATTR = Attribute(
    size=345,
    fields=list(STRAINRIBBON_ATTR.fields) + [
        Int("unkn_tail0"),
        Byte("unkn_tail1"),
    ],
)
assert _schema_size(EXTERN_STRAINRIBBON_ATTR.schema) == 345, \
    f"EXTERN_STRAINRIBBON_ATTR size mismatch: {_schema_size(EXTERN_STRAINRIBBON_ATTR.schema)}"

EXTERN_TURBULENCE_ATTR = Attribute(
    size=161,
    fields=list(TURBULENCE_ATTR.fields) + [
        Int("unkn_tail0"),
        Byte("unkn_tail1"),
    ],
)
assert _schema_size(EXTERN_TURBULENCE_ATTR.schema) == 161, \
    f"EXTERN_TURBULENCE_ATTR size mismatch: {_schema_size(EXTERN_TURBULENCE_ATTR.schema)}"


# Lightning：固定字段 + 长度前缀路径。

_LIGHTNING_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed00_1', 'i'),
    ('spacer0',             'i'),
    ('color1',              ('XYZ', 2)),
    ('unkn02',              'i'),
    ('color2',              ('XYZ', 2)),
    ('unkn03',              'i'),
    ('emissive',            ('XYZ', 2)),
    ('unkn04',              'f'),
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
    ('inflectionPointCount',          'i'),
    ('uInflectionAngleLimit',         'f'),
    ('uInflectionAngleLimitJitter',   'f'),
    ('vInflectionAngleLimit',         'f'),
    ('vInflectionAngleLimitJitter',   'f'),
    ('inflectionPointCount2',         'i'),
    ('uInflectionAngleLimit2',        'f'),
    ('uInflectionAngleLimitJitter2',  'f'),
    ('vInflectionAngleLimit2',        'f'),
    ('vInflectionAngleLimitJitter2',  'f'),
    ('glow',            'f'),
    ('glowJitter',      'f'),
    ('length',          'f'),
    ('lengthJitter',    'f'),
    ('width',           'f'),
    ('widthJitter',     'f'),
    ('startWidth',              'f'),
    ('uvRepetitionStart',       'f'),
    ('endWidth',                'f'),
    ('uvRepetitionEnd',         'f'),
    ('unknFixed05_45',   'i'),
    ('unkn05_46',   'i'),
    ('unknBitmask05_47',   'i'),
    ('unknFlag05_48',   'i'),
    ('unknBitmask06_0', 'i'),
    ('unknBitmask06_1', 'i'),
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
    ('unknFixed08_0', 'i'),
    ('unknEnum08_1', 'i'),
    ('unkn09',      ('f', 20)),
    ('unkn10_0', 'f'),
    ('unknEnum10_1', 'i'),
    ('unknFlag10_2', 'i'),
    ('unknFixed10_3', 'i'),
    ('unkn11_0', 'f'),
    ('unkn11_1', 'f'),
    ('unknFixed12_0', 'i'),
    ('unknEnum12_1', 'i'),
    ('unknAngle13_0',   'f'),
    ('unknFixed13_1',   'f'),
    ('unknFixed13_2',   'f'),
    ('unknEnum13_3',    'i'),
    ('unknFixed13_4',   'f'),
    ('unknFixed13_5',   'f'),
    ('unknEnum14_0', 'i'),
    ('unknFlag14_1', 'i'),
    ('unknFixed14_2', 'i'),
    ('unknFixed15_0a',                   'B'),
    ('enableFlowmap',                    'B'),
    ('spacer15_0',                       ('B', 2)),
    ('flowmapSpeed',                     'f'),
    ('flowmapSpeedJitter',               'f'),
    ('flowmapSpeedCoef',              'f'),
    ('flowmapSpeedCoefJitter',        'f'),
    ('flowmapStrength',                  'f'),
    ('flowmapStrengthJitter',            'f'),
    ('flowmapStrengthCoef',      'f'),
    ('flowmapStrengthCoefJitter','f'),
    ('unknEnum16',      'h'),
]
assert _schema_size(_LIGHTNING_FIXED_SCHEMA) == 546, \
    f"_LIGHTNING_FIXED_SCHEMA size mismatch: {_schema_size(_LIGHTNING_FIXED_SCHEMA)}"
# B-backed 开关须保留 backing，确保 schema 字节等价
_LIGHTNING_OVR = {
    'enableFlowmap': Bool('enableFlowmap', backing='B', label_zh="启用流动贴图"),
}
LIGHTNING_ATTR = attr_from_legacy(
    _schema_size(_LIGHTNING_FIXED_SCHEMA), _LIGHTNING_FIXED_SCHEMA,
    overrides=_LIGHTNING_OVR,
)


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


# RgbWater：固定字段 + 长度前缀路径。

_RGBWATER_FIXED_SCHEMA = [
    # waterLerpGtoB 的字段名对应 TIML 通道名，标签按其实际的 Alpha/Blue 混合行为写
    ('typeFlag',                 'i'),
    # 两个颜色分开写，合并成数组后界面只能显示 color[0]/color[1]
    # 头部 8 个字段可被 TIML 驱动，DT hash 见 timl/names.py::FIELD_TO_DT
    ('colorSpecular',            ('XYZ', 2)),
    ('colorSheet',               ('XYZ', 2)),
    ('colorRate',                'f'),
    ('waterLerpGtoB',            'f'),
    ('intensityCubeMap',         'f'),
    ('intensitySpecular',        'f'),
    ('intensitySheet',           'f'),
    ('intensityAlpha',           'f'),
    ('normalSharpness',          'f'),   # 不可动画，无对应 DT 通道
    ('specularColorParam_useLife', 'i'),
    ('specularColorParam_appearFrame', 'i'),
    ('specularColorParam_appearFrameJitter', 'i'),
    ('specularColorParam_keepFrame', 'i'),
    ('specularColorParam_keepFrameJitter', 'i'),
    ('specularColorParam_vanishFrame', 'i'),
    ('specularColorParam_vanishFrameJitter', 'i'),
    ('specularColorParam_lighting', 'i'),
    ('specularColorParam_lifeType', 'i'),
    ('specularColorParam_correctColorNo', 'i'),
    ('sheetColorParam_useLife', 'i'),
    ('sheetColorParam_appearFrame', 'i'),
    ('sheetColorParam_appearFrameJitter', 'i'),
    ('sheetColorParam_keepFrame', 'i'),
    ('sheetColorParam_keepFrameJitter', 'i'),
    ('sheetColorParam_vanishFrame', 'i'),
    ('sheetColorParam_vanishFrameJitter', 'i'),
    ('sheetColorParam_lighting', 'i'),
    ('sheetColorParam_lifeType', 'i'),
    ('sheetColorParam_correctColorNo', 'i'),
    ('waterLerpParam_useLife', 'i'),
    ('waterLerpParam_appearFrame', 'i'),
    ('waterLerpParam_appearFrameJitter', 'i'),
    ('waterLerpParam_keepFrame', 'i'),
    ('waterLerpParam_keepFrameJitter', 'i'),
    ('waterLerpParam_vanishFrame', 'i'),
    ('waterLerpParam_vanishFrameJitter', 'i'),
    ('waterLerpParam_lighting', 'i'),
    ('waterLerpParam_lifeType', 'i'),
]
assert _schema_size(_RGBWATER_FIXED_SCHEMA) == 156, \
    f"_RGBWATER_FIXED_SCHEMA size mismatch: {_schema_size(_RGBWATER_FIXED_SCHEMA)}"
RGBWATER_ATTR = attr_from_legacy(
    _schema_size(_RGBWATER_FIXED_SCHEMA), _RGBWATER_FIXED_SCHEMA,
    # 标签不带"高光/水膜"前缀：panels.py 分组绘制，小标题已给出上下文，不要补前缀
    labels={
        'colorSpecular': '颜色',
        'colorSheet': '颜色',
        'colorRate': '总体亮度',
        'waterLerpGtoB': 'Alpha 混入蓝通道比例',
        'intensityCubeMap': '环境反射强度',
        'intensitySpecular': '强度',
        'intensitySheet': '强度',
        'intensityAlpha': '总体透明度',
        'specularColorParam_appearFrame': '淡入',
        'specularColorParam_keepFrame': '持续',
        'specularColorParam_vanishFrame': '淡出',
        'specularColorParam_lifeType': '生命期模式',
        'specularColorParam_correctColorNo': 'EPV 颜色修正槽位',
        'sheetColorParam_appearFrame': '淡入',
        'sheetColorParam_keepFrame': '持续',
        'sheetColorParam_vanishFrame': '淡出',
        'sheetColorParam_lifeType': '生命期模式',
        'sheetColorParam_correctColorNo': 'EPV 颜色修正槽位',
        'waterLerpParam_appearFrame': '淡入',
        'waterLerpParam_keepFrame': '持续',
        'waterLerpParam_vanishFrame': '淡出',
        'waterLerpParam_lifeType': '生命期模式',
    },
    overrides={
        'specularColorParam_useLife':  Bool('specularColorParam_useLife',  label_en='Use Life',  label_zh='启用生命周期'),
        'specularColorParam_lighting': Bool('specularColorParam_lighting', label_en='Lighting', label_zh='受光照影响'),
        'sheetColorParam_useLife':  Bool('sheetColorParam_useLife',  label_en='Use Life',  label_zh='启用生命周期'),
        'sheetColorParam_lighting': Bool('sheetColorParam_lighting', label_en='Lighting', label_zh='受光照影响'),
        'waterLerpParam_useLife':  Bool('waterLerpParam_useLife',  label_en='Use Life',  label_zh='启用生命周期'),
        'waterLerpParam_lighting': Bool('waterLerpParam_lighting', label_en='Lighting', label_zh='受光照影响'),
    },
)

# EXTERNRGBWATER：与主属性 schema 同构、无 path，每元素多出 5 B 尾巴，语义未知。
EXTERN_RGBWATER_SCHEMA = list(_RGBWATER_FIXED_SCHEMA)
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


# 分派型 custom codec：内部元素按类型决定布局


# PtBehavior：行为类型字符串与按 ``t`` 分派的参数列表

def unpack_ptbehavior(data: bytes, off: int = 0):
    """Unpack PtBehavior data_bytes. Returns (dict, new_off)."""
    (typeFlag,) = struct.unpack_from('<i', data, off); off += 4
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


# Material：Tex_Block / Tex_Set 的嵌套类型分派

def unpack_material(data: bytes, off: int = 0):
    """Unpack Material data_bytes. Returns (dict, new_off)."""
    (typeFlag,) = struct.unpack_from('<q', data, off); off += 8
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


# TonemapFilter：24 B 固定字段和长度前缀路径

_TONEMAPFILTER_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed0_1', 'i'),
    ('unkn1', 'i'),
    ('intensity', 'f'),
    ('triggerRadius', 'f'),
    ('unknFixed2_2', 'f'),
]
TONEMAPFILTER_ATTR = attr_from_legacy(
    _schema_size(_TONEMAPFILTER_FIXED_SCHEMA), _TONEMAPFILTER_FIXED_SCHEMA,
    labels={'intensity': "生效强度", 'triggerRadius': "生效范围"},
)


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


# TUBELIGHT 的 typed Attribute；降级 schema 必须与 on-disk 字节布局等价
TUBELIGHT_ATTR = Attribute(size=124, fields=[
    Int("typeFlag"),
    Int("unknFixed0_1"),                               # off4
    # 该 int 拆为固定 byte、未知 bool、填充 byte、固定 byte
    Byte("unknFixed0_2a"),
    Bool("unknBool0_2", backing='B'),
    Byte("unknFixed0_2_cd"),
    Byte("unknFixed0_2b"),
    Float("unkn1_0"),
    # 这两个稳定字段名已指向明确偏移；不能复用旧名称，否则旧 .blend 会写入错误字段
    Float("lightIntensity", label_zh="光照强度"),
    Float("coreIntensity", label_zh="核心亮度"),
    Float("coreIntensityJitter", label_zh="核心亮度抖动"),  # off24
    Float("columnLengthModifier", label_zh="光柱长度修正"),  # off28
    # 不将其重命名为 CoreThickness，避免和旧 .blend 字段名冲突
    Float("columnRadius", label_zh="光柱半径"),
    Float("columnRadiusJitter", label_zh="光柱半径抖动"),    # off36
    Float("columnEdgeSoftness", label_zh="光柱边缘柔化"),    # off40
    Float("effectiveRadius", label_zh="光照有效半径"),  # off44 DT EffectiveRadius
    Float("unknFixed1_9"),                             # off48
    Float("unkn1_10"),                                 # off52
    Float("unkn2_0"),                                  # off56
    Float("textureScrollSpeed", label_zh="贴图滚动速度"),  # off60
    Int("unknFixed3_0"),                               # off64
    Int("unknFixed3_1"),                               # off68
    Int("unkn3_2"),                                    # off72
    Int("headColorEpvSlot", label_zh="EPV 颜色修正槽位"),  # off76
    Int("headColor", label_zh="光柱起点颜色"),          # off80 打包 RGBA int
    # ⚠ head/tail 这组命名未经确认，可能与实际的头尾相反。改这四个字段的行为前，
    #   先用具体数值确认哪一端是起点，不要按名字推断。
    Float("columnLength", label_zh="光柱长度"),         # off84
    Float("tailGlowSpread", label_zh="尾光扩散(变长+边缘虚化)"),  # off88
    Float("tailEffectiveRadius", label_zh="终点有效半径"),  # off92
    Int("unknFixed5_0"),                               # off96
    Int("unkn5_1"),                                    # off100 保留填充（0xCD 占位）
    Int("unknFixed6a_0"),                              # off104
    Int("tailColor", label_zh="光柱终点颜色"),          # off108 打包 RGBA int
    Float("tailPlaneOffset", label_zh="终点发光面前后位置"),  # off112
    Float("unkn6b_1"),                                 # off116
    Float("headEffectiveRadius", label_zh="起点有效半径"),  # off120
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


# EmitterShapeMesh：32 B 固定字段和 NUL 终止路径

_EMITTERSHAPEMESH_FIXED_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed0_1', 'i'),
    ('unkn1_0', 'i'),
    ('unkn1_1', 'i'),
    ('unkn1_2', 'i'),
    ('unknFlag2_0', 'b'),
    ('ddsUsageType', 'b'),
    ('unknFlag2_2', 'b'),
    ('visconIndex', 'b'),
    ('unknEnum2_4', 'b'),
    ('unknEnum2_5', 'b'),
    ('unknEnum2_6', 'b'),
    ('unknEnum2_7', 'b'),
    ('unknBitmask3', 'i'),
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


# Layout：可编辑前缀 + 嵌套 LayoutBank_Block。
# LayoutBank_Block 以 -1 sentinel 定界，长度只能靠遍历求出，必须原样保留。

def _walk_layoutbank_block(data: bytes, pos: int) -> int:
    """返回紧跟这个 LayoutBank_Block 之后的位置。

    由 Root 的 LayoutBank 子条目解析与 Layout 主属性共用，两处的块边界判定必须一致。
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


def _read_layoutbank_block_columns(data: bytes, pos: int):
    """与 _walk_layoutbank_block 走同一遍字节，同时把每列的值读出，供只读展示用。

    返回 (columns, new_pos)；columns = [{'block_type', 'count', 'values'}, ...]。
    与 _walk_layoutbank_block 的步进必须保持一致，否则展示结果与块边界会对不上。
    """
    columns = []
    count = struct.unpack_from('<i', data, pos)[0]
    pos += 4
    if count > 0:
        while True:
            sentinel = struct.unpack_from('<i', data, pos)[0]
            if sentinel == -1:
                pos += 4
                break
            block_type = sentinel
            pos += 4
            if block_type == 0 or block_type == 6:
                n = count * 3
                if block_type == 0:
                    values = list(struct.unpack_from(f'<{n}f', data, pos))
                else:
                    values = list(struct.unpack_from(f'<{n}i', data, pos))
                pos += n * 4
            elif 0 < block_type < 6:
                n16 = count * 2 * 2
                values = list(struct.unpack_from(f'<{n16}h', data, pos))
                pos += n16 * 2
            elif block_type == 7:
                sub_unkn0 = struct.unpack_from('<i', data, pos)[0]
                pos += 4
                n16 = count * 2 * sub_unkn0 * 2
                values = list(struct.unpack_from(f'<{n16}h', data, pos))
                pos += n16 * 2
                block_type = f'7(sub={sub_unkn0})'
            else:
                raise ValueError(f'LayoutBank_B: unknown block_type={block_type} at pos {pos-4}')
            columns.append({'block_type': block_type, 'count': count, 'values': values})
    return columns, pos


def unpack_layoutbank_block(data: bytes, pos: int):
    """结构化解出一个 LayoutBank_Block，步进与 _walk_layoutbank_block 一致。"""
    (count,) = struct.unpack_from('<i', data, pos)
    pos += 4
    columns = []
    if count > 0:
        while True:
            (block_type,) = struct.unpack_from('<i', data, pos)
            pos += 4
            if block_type == -1:
                break
            col = {'blockType': block_type}
            if block_type == 0 or block_type == 6:
                n, fmt = count * 3, ('f' if block_type == 0 else 'i')
                col['values'] = list(struct.unpack_from(f'<{n}{fmt}', data, pos))
                pos += n * 4
            elif 0 < block_type < 6:
                n = count * 4
                col['values'] = list(struct.unpack_from(f'<{n}h', data, pos))
                pos += n * 2
            elif block_type == 7:
                (sub,) = struct.unpack_from('<i', data, pos)
                pos += 4
                n = count * 4 * sub
                col['subCount'] = sub
                col['values'] = list(struct.unpack_from(f'<{n}h', data, pos))
                pos += n * 2
            else:
                raise ValueError(f'LayoutBank_B: unknown block_type={block_type} at pos {pos-4}')
            columns.append(col)
    return {'count': count, 'columns': columns}, pos


def pack_layoutbank_block(block: dict) -> bytes:
    """按 unpack_layoutbank_block 的结构写回；count > 0 时总以 -1 结尾。"""
    count = int(block['count'])
    columns = block.get('columns', [])
    out = struct.pack('<i', count)
    if count <= 0:
        if columns:
            raise ValueError('LayoutBank_B: count <= 0 的块不能带列')
        return out
    for col in columns:
        block_type = int(col['blockType'])
        values = col['values']
        out += struct.pack('<i', block_type)
        if block_type == 0 or block_type == 6:
            n, fmt = count * 3, ('f' if block_type == 0 else 'i')
        elif 0 < block_type < 6:
            n, fmt = count * 4, 'h'
        elif block_type == 7:
            sub = int(col['subCount'])
            out += struct.pack('<i', sub)
            n, fmt = count * 4 * sub, 'h'
        else:
            raise ValueError(f'LayoutBank_B: unknown block_type={block_type}')
        if len(values) != n:
            raise ValueError(
                f'LayoutBank_B: block_type={block_type} 需要 {n} 个值，实际 {len(values)} 个')
        out += struct.pack(f'<{n}{fmt}', *values)
    return out + struct.pack('<i', -1)


def describe_layoutbank(data: bytes) -> list:
    """解出 Root LayoutBank 子条目的全部列，按出现顺序摊平成一份平铺列表。

    LayoutBank 逐文件变长，套不进固定 schema，因此只做只读展示，不提供字段级编辑。
    返回 [{'block_idx', 'block_type', 'count', 'values'}, ...]。
    """
    (unkn0,) = struct.unpack_from('<i', data, 0)
    (block_count,) = struct.unpack_from('<i', data, 4)
    pos = 8
    out = []
    for bi in range(block_count):
        columns, pos = _read_layoutbank_block_columns(data, pos)
        for col in columns:
            col['block_idx'] = bi
            out.append(col)
    return out


_LAYOUT_PREFIX_SCHEMA = [
    ('typeFlag', 'i'),
    ('unknFixed0_1', 'i'),
    # 两个 int 按字节拆开，其中六个字节是嵌套 LayoutBank_Block 各列的开关：
    # useColumn2 管列 2/3，useColumn4 管列 4/5，其余一字节对一列
    ('unknFixed1_0_0', 'B'),
    ('useColumn0', 'B'),
    ('useColumn1', 'B'),
    ('unknFlag1_0_3', 'B'),
    ('useColumn2', 'B'),
    ('useColumn4', 'B'),
    ('useColumn6', 'B'),
    ('useColumn7', 'B'),
    ('unknFixed1_2', 'i'),
    ('unknFixed1_3', 'i'),
]
assert _schema_size(_LAYOUT_PREFIX_SCHEMA) == 24, \
    f"_LAYOUT_PREFIX_SCHEMA size mismatch: {_schema_size(_LAYOUT_PREFIX_SCHEMA)}"
LAYOUT_ATTR = attr_from_legacy(
    _schema_size(_LAYOUT_PREFIX_SCHEMA), _LAYOUT_PREFIX_SCHEMA,
    overrides={
        'useColumn0': Bool('useColumn0', backing='B', label_zh="启用列 0"),
        'useColumn1': Bool('useColumn1', backing='B', label_zh="启用列 1"),
        'useColumn2': Bool('useColumn2', backing='B', label_zh="启用列 2/3"),
        'useColumn4': Bool('useColumn4', backing='B', label_zh="启用列 4/5"),
        'useColumn6': Bool('useColumn6', backing='B', label_zh="启用列 6"),
        'useColumn7': Bool('useColumn7', backing='B', label_zh="启用列 7"),
        'unknFlag1_0_3': Bool('unknFlag1_0_3', backing='B'),
    },
)

def unpack_layout(data: bytes, off: int = 0):
    """解出固定前缀字段；LayoutBank_Block 整段存入 layoutbank_bytes 原样保留。"""
    values, off = unpack(_LAYOUT_PREFIX_SCHEMA, data, off)
    bank_start = off
    bank_end = _walk_layoutbank_block(data, bank_start)
    values['layoutbank_bytes'] = data[bank_start:bank_end]
    off = bank_end
    return values, off


def pack_layout(values: dict) -> bytes:
    """回写固定前缀并接上原始 layoutbank_bytes。"""
    out = pack(_LAYOUT_PREFIX_SCHEMA, values)
    out += values['layoutbank_bytes']
    return out


# 含路径 custom 类型的提取与保真重建。
# rebuild 只能替换路径长度与路径字节，其余字节逐字复制；传入原路径必须原样返回。
# extract 与 rebuild 的路径顺序必须一致，嵌套的 MATERIAL / PTBEHAVIOR 按遍历顺序配对。

def _path_bytes_to_str(b: bytes) -> str:
    """路径 bytes → UTF-8 字符串（宽容解码）。"""
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('latin-1')


def _str_to_path_bytes(s: str) -> bytes:
    """路径字符串 → bytes（UTF-8）。"""
    return s.encode('utf-8')


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
    # UVSEQUENCE
    if type_hash == UVSEQUENCE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 40)
        path_b = data_bytes[44:44 + path_len]
        return [_path_bytes_to_str(path_b)]

    # BILLBOARD3D
    if type_hash == BILLBOARD3D:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_start = 104 + 4 + 24  # = 132
        path_b = data_bytes[path_start:path_start + path_len]
        return [_path_bytes_to_str(path_b)]

    # PLANE
    if type_hash == PLANE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_start = 104 + 4 + 48  # = 156
        path_b = data_bytes[path_start:path_start + path_len]
        return [_path_bytes_to_str(path_b)]

    # RIBBONBLADE
    if type_hash == RIBBONBLADE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 194)
        path_b = data_bytes[198:198 + path_len]
        return [_path_bytes_to_str(path_b)]

    # BILLBOARD2D：path_len 与 path 之间夹着 unkn5
    if type_hash == BILLBOARD2D:
        (path_len,) = struct.unpack_from('<i', data_bytes, 104)
        path_b = data_bytes[116:116 + path_len]
        return [_path_bytes_to_str(path_b)]

    # STRAINRIBBON
    if type_hash == STRAINRIBBON:
        (path_len,) = struct.unpack_from('<i', data_bytes, 340)
        path_b = data_bytes[344:344 + path_len]
        return [_path_bytes_to_str(path_b)]

    # RGBWATER
    if type_hash == RGBWATER:
        (path_len,) = struct.unpack_from('<i', data_bytes, 156)
        path_b = data_bytes[160:160 + path_len]
        return [_path_bytes_to_str(path_b)]

    # LIGHTNING
    if type_hash == LIGHTNING:
        (path_len,) = struct.unpack_from('<i', data_bytes, 546)
        path_b = data_bytes[550:550 + path_len]
        return [_path_bytes_to_str(path_b)]

    # TURBULENCE：path 在块中部
    if type_hash == TURBULENCE:
        (path_len,) = struct.unpack_from('<i', data_bytes, 4)
        path_b = data_bytes[8:8 + path_len]
        return [_path_bytes_to_str(path_b)]

    # TUBELIGHT：path_len 计入末尾的 null
    if type_hash == TUBELIGHT:
        (path_len,) = struct.unpack_from('<i', data_bytes, 124)
        path_b = data_bytes[128:128 + path_len].rstrip(b'\x00')
        return [_path_bytes_to_str(path_b)]

    # EMITTERSHAPEMESH：无 path_len，块在 null 处结束
    if type_hash == EMITTERSHAPEMESH:
        null = data_bytes.index(b'\x00', 32)
        path_b = data_bytes[32:null]
        return [_path_bytes_to_str(path_b)]

    # TONEMAPFILTER：path_len 计入末尾的 null
    if type_hash == TONEMAPFILTER:
        (path_len,) = struct.unpack_from('<i', data_bytes, 24)
        path_b = data_bytes[28:28 + path_len].rstrip(b'\x00')
        return [_path_bytes_to_str(path_b)]

    # RIBBON：无 path_len，null 结尾
    if type_hash == RIBBON:
        null = data_bytes.index(b'\x00', 360)
        path_b = data_bytes[360:null]
        return [_path_bytes_to_str(path_b)]

    # MESH
    if type_hash == MESH:
        off = 175  # skip 174B Mod3 + 1B BeginMod3
        null1 = data_bytes.index(b'\x00', off)
        path1_b = data_bytes[off:null1]
        off = null1 + 1
        null2 = data_bytes.index(b'\x00', off)
        path2_b = data_bytes[off:null2]
        return [_path_bytes_to_str(path1_b), _path_bytes_to_str(path2_b)]

    # ── MATERIAL ─────────────────────────────────────────────────────────
    # 只有 type==0x80 的 Tex_Set 带路径；返回顺序即其出现顺序。
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

    # ── PTBEHAVIOR ───────────────────────────────────────────────────────
    # 只有 t==0x80 的参数带路径；返回顺序即其出现顺序。
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


    # LAYOUT 没有嵌入路径，返回空列表；列在支持表里只为让固定前缀字段能展开编辑。
    if type_hash == LAYOUT:
        return []

    # 固定返回 6 项，空槽也占位，调用方按下标对应槽位
    if type_hash == RENDERTARGET:
        paths = []
        off = 4  # 跳过 path_count
        for _ in range(6):
            (path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4
            path_b = data_bytes[off:off + path_len].rstrip(b'\x00'); off += path_len
            paths.append(_path_bytes_to_str(path_b))
        return paths

    raise ValueError(f"extract_paths: 不支持的类型 hash 0x{type_hash:08X}")


def rebuild_with_paths(type_hash: int, data_bytes: bytes, new_paths: 'List[str]') -> bytes:
    """用 new_paths 替换路径段，其余字节逐字复制。

    只更新 path_len 与路径字节；非路径字节一律取自 data_bytes，绝不经过 pack_*。
    传入与原路径相同的值时必须原样返回 data_bytes。
    """
    # ── UVSEQUENCE ──
    if type_hash == UVSEQUENCE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:40]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── BILLBOARD3D ──
    if type_hash == BILLBOARD3D:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:132]
                + new_path_b)

    # ── PLANE ──
    if type_hash == PLANE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:156]
                + new_path_b)

    # ── RIBBONBLADE ──
    if type_hash == RIBBONBLADE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:194]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── BILLBOARD2D ──
    if type_hash == BILLBOARD2D:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:104]
                + struct.pack('<i', len(new_path_b))
                + data_bytes[108:116]
                + new_path_b)

    # ── STRAINRIBBON ──
    if type_hash == STRAINRIBBON:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:340]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── RGBWATER ──
    if type_hash == RGBWATER:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:156]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── LIGHTNING ──
    if type_hash == LIGHTNING:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return (data_bytes[:546]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── TURBULENCE ──
    # path 在中部：其后的固定段整段平移，不能按固定偏移切
    if type_hash == TURBULENCE:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        (old_path_len,) = struct.unpack_from('<i', data_bytes, 4)
        old_path_end = 8 + old_path_len
        return (data_bytes[:4]
                + struct.pack('<i', len(new_path_b))
                + new_path_b
                + data_bytes[old_path_end:])

    # ── TUBELIGHT ──
    # path_len 计入末尾 null，所以先补 null 再取长度
    if type_hash == TUBELIGHT:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0]) + b'\x00'
        return (data_bytes[:124]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── EMITTERSHAPEMESH ──
    if type_hash == EMITTERSHAPEMESH:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return data_bytes[:32] + new_path_b + b'\x00'

    # ── TONEMAPFILTER ──
    # path_len 计入末尾 null，所以先补 null 再取长度
    if type_hash == TONEMAPFILTER:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0]) + b'\x00'
        return (data_bytes[:24]
                + struct.pack('<i', len(new_path_b))
                + new_path_b)

    # ── RIBBON ──
    if type_hash == RIBBON:
        assert len(new_paths) == 1
        new_path_b = _str_to_path_bytes(new_paths[0])
        return data_bytes[:360] + new_path_b + b'\x00'

    # ── MESH ──
    if type_hash == MESH:
        assert len(new_paths) == 2
        new_path1_b = _str_to_path_bytes(new_paths[0])
        new_path2_b = _str_to_path_bytes(new_paths[1])
        return (data_bytes[:175]
                + new_path1_b + b'\x00'
                + new_path2_b + b'\x00')

    # ── MATERIAL ─────────────────────────────────────────────────────────
    # path_idx 按 type==0x80 的出现顺序递增，必须与 extract_paths 的返回顺序一致。
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

    # ── PTBEHAVIOR ───────────────────────────────────────────────────────
    # path_idx 按 t==0x80 的出现顺序递增，必须与 extract_paths 的返回顺序一致。
    # file_type 原样保留，只替换其后的 path_len 与路径字节。
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


    # LAYOUT 无嵌入路径，原样返回；固定前缀字段的改动不经过这里。
    if type_hash == LAYOUT:
        return data_bytes

    # ── RenderTarget ──
    # 6 个路径槽全部重写（path_len 计入末尾 null），头尾的固定段原样保留。
    if type_hash == RENDERTARGET:
        assert len(new_paths) == 6
        off = 4
        for _ in range(6):
            (path_len,) = struct.unpack_from('<i', data_bytes, off); off += 4 + path_len
        tail = data_bytes[off:]
        out = data_bytes[:4]
        for p in new_paths:
            pb = _str_to_path_bytes(p) + b'\x00'
            out += struct.pack('<i', len(pb)) + pb
        return out + tail

    raise ValueError(f"rebuild_with_paths: 不支持的类型 hash 0x{type_hash:08X}")


# ─────────────────────────────────────────────────────────────────────────────
# RenderTarget 是 Root 的专属子条目，被包成 AttrBlock 以复用属性子对象基建；
# 类型哈希在 AttrBlock.type_hash 上，不进 data_bytes。
# ─────────────────────────────────────────────────────────────────────────────

def unpack_rendertarget(data: bytes, off: int = 0):
    """解出 6 个路径与其后的标量字段。"""
    values = {}
    (values['path_count'],) = struct.unpack_from('<i', data, off)
    off += 4
    for i in range(6):
        (path_len,) = struct.unpack_from('<i', data, off)
        off += 4
        values[f'path{i}'] = data[off:off + path_len]
        off += path_len
    (values['nullField'],) = struct.unpack_from('<i', data, off)
    off += 4
    for i in range(6):
        (values[f'unkn0_{i}'],) = struct.unpack_from('<i', data, off)
        off += 4
    for i in range(9):
        (values[f'unkn1_{i}'],) = struct.unpack_from('<f', data, off)
        off += 4
    return values, off


def pack_rendertarget(values: dict) -> bytes:
    """按解析顺序回写路径与标量字段。"""
    out = struct.pack('<i', values['path_count'])
    for i in range(6):
        p = values[f'path{i}']
        out += struct.pack('<i', len(p)) + p
    out += struct.pack('<i', values['nullField'])
    for i in range(6):
        out += struct.pack('<i', values[f'unkn0_{i}'])
    for i in range(9):
        out += struct.pack('<f', values[f'unkn1_{i}'])
    return out


# 可编辑标量字段 schema；path0..5 由 codec 单独处理，不入 schema。
_RENDERTARGET_TAIL_SCHEMA = [
    ('path_count', 'i'),
    ('nullField', 'i'),
    ('unkn0_0', 'i'), ('unkn0_1', 'i'), ('unkn0_2', 'i'),
    ('unkn0_3', 'i'), ('unkn0_4', 'i'), ('unkn0_5', 'i'),
    ('unkn1_0', 'f'), ('unkn1_1', 'f'), ('unkn1_2', 'f'), ('unkn1_3', 'f'),
    ('unkn1_4', 'f'), ('unkn1_5', 'f'), ('unkn1_6', 'f'), ('unkn1_7', 'f'),
    ('unkn1_8', 'f'),
]


# 支持路径编辑的 custom 类型集合。
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
    # 嵌套/分派类型，含多个嵌入路径
    MATERIAL,
    PTBEHAVIOR,
    TUBELIGHT,
    EMITTERSHAPEMESH,
    BILLBOARD2D,
    TONEMAPFILTER,
    # 无嵌入路径，列在此处只为让固定字段展开生效
    LAYOUT,
    RENDERTARGET,
})


# ─────────────────────────────────────────────────────────────────────────────
# custom 块的可编辑标量字段 schema：各 unpack_* 用到的 fixed 子 schema，排除路径条目。
#
# 维护约束：
# - 字段名必须与 unpack_* 返回 dict 的键一致，取值与按名覆盖都依赖这一点。
# - 重建走 unpack → 覆盖被编辑字段 → pack；未编辑字段由原值经 pack 还原。
# - MATERIAL 与 PTBEHAVIOR 是嵌套分派结构，不进此表，由 fields.py 各自的重建函数处理。
# - 表内各 schema 的拼接顺序只影响 UI 显示顺序。
# ─────────────────────────────────────────────────────────────────────────────

CUSTOM_FIELD_SCHEMA_MAP: Dict[int, list] = {
    RIBBON:      _RIBBON_FIXED_SCHEMA,
    UVSEQUENCE:  _UVSEQUENCE_FIXED_SCHEMA,
    # BeginMod3 由 unpack_mesh 单独读，这里拼上才能编辑
    MESH:        _MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')],
    RIBBONBLADE: _RIBBONBLADE_FIXED_SCHEMA,
    STRAINRIBBON:_STRAINRIBBON_FIXED_SCHEMA,
    LIGHTNING:   _LIGHTNING_FIXED_SCHEMA,
    RGBWATER:    _RGBWATER_FIXED_SCHEMA,
    TURBULENCE:  [('typeFlag', 'i')] + _TURBULENCE_AFTER_PATH_SCHEMA,
    # 编辑段用 _*_EDIT_SCHEMA：它把 path_len 之后的固定段也并了进来
    BILLBOARD3D: _BILLBOARD3D_EDIT_SCHEMA,
    PLANE:       _PLANE_EDIT_SCHEMA,
    TUBELIGHT:        _TUBELIGHT_FIXED_SCHEMA,
    EMITTERSHAPEMESH: _EMITTERSHAPEMESH_FIXED_SCHEMA,
    BILLBOARD2D:      [e for e in _BILLBOARD2D_FIXED_SCHEMA if e[0] != 'path_len'],
    TONEMAPFILTER:    _TONEMAPFILTER_FIXED_SCHEMA,
    # 只暴露固定前缀；LayoutBank_Block 由 unpack_layout/pack_layout 原样保留
    LAYOUT:           _LAYOUT_PREFIX_SCHEMA,
    RENDERTARGET:     _RENDERTARGET_TAIL_SCHEMA,
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
    """BILLBOARD2D 的 path_len 是固定 schema 内的一个字段，在该处切成 before/after。"""
    s = _BILLBOARD2D_FIXED_SCHEMA
    i = next(k for k, e in enumerate(s) if e[0] == 'path_len')
    return s[:i], [e for e in s[i + 1:] if e[0] != 'path']


# on-disk 布局为 `4(类型哈希) + before + path_len(4) + after(+path)`，after 可为空。
# before/after 必须取 codec 侧的 `_XXX_FIXED_SCHEMA`，不能用 CUSTOM_FIELD_SCHEMA_MAP：
# 后者是 UI 编辑版，已把 after 段并进 before，用它计算会把那段字节数算两遍。
# TURBULENCE 的 path 物理上在 after 之前，但尺寸只取决于两段字节数，公式一致。
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
    """path_len 尾巴族的 on-disk 总字节数（含 4 B 类型哈希）；不属此族返回 None。

    path_len 为负或异常大时也返回 None，让调用方回退到 forward-scan，以保留对损坏
    数据的降级行为。
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


# 定长前缀 + N 个 null 结尾字符串，无 path_len。前缀同样取 codec schema，尾巴只能扫 null。
_NULLSTR_TAIL_LAYOUT = {
    MESH:             (_MOD3_PROPERTIES_SCHEMA + [('BeginMod3', 'B')], 2),  # path1 + path2
    RIBBON:           (_RIBBON_FIXED_SCHEMA, 1),
    EMITTERSHAPEMESH: (_EMITTERSHAPEMESH_FIXED_SCHEMA, 1),
}


def custom_nullstr_size(type_hash: int, data: bytes, pos: int):
    """null 结尾字符串族的 on-disk 总字节数（含 4 B 类型哈希）；不属此族返回 None。

    逐个扫 null 并计入终止符；扫不到时返回 None，让调用方回退到 forward-scan。
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
