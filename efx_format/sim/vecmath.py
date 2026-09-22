# -*- coding: utf-8 -*-
"""旋转与角度采样的工具函数。

维护约束：
- 两张 rotationOrder 表不可混用，调用方按属性类型选；取错表时结果错误且不报错。
- ⚠ 顺序串里先写的轴是先作用还是后作用未经确认，由 SimConfig.rot_order_applied
  选择，其默认值是折中选定的，不是结论。
"""

import math

from .state import Vec3

#: VELOCITY3D.rotOrder
ROT_ORDER_VELOCITY = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")

#: TRANSFORM3D / EMITTERSHAPE3D / RIBBON 的 rotationOrder
ROT_ORDER_TRANSFORM = ("XYZ", "YZX", "YXZ", "ZYX", "ZXY", "XZY")


def _rot_x(v, c, s):
    return Vec3(v.x, v.y * c - v.z * s, v.y * s + v.z * c)


def _rot_y(v, c, s):
    return Vec3(v.x * c + v.z * s, v.y, -v.x * s + v.z * c)


def _rot_z(v, c, s):
    return Vec3(v.x * c - v.y * s, v.x * s + v.y * c, v.z)


_ROT_FN = {"X": _rot_x, "Y": _rot_y, "Z": _rot_z}


def rotate_euler(v, deg_x, deg_y, deg_z, order="XYZ", applied="forward"):
    """依次绕三轴旋转 v；applied='forward' 表示顺序串里先写的轴先作用。"""
    if not deg_x and not deg_y and not deg_z:
        return v.copy()
    ang = {"X": math.radians(deg_x), "Y": math.radians(deg_y), "Z": math.radians(deg_z)}
    seq = order if applied == "forward" else order[::-1]
    out = v.copy()
    for axis in seq:
        a = ang[axis]
        if a:
            out = _ROT_FN[axis](out, math.cos(a), math.sin(a))
    return out


def rot_order_name(value, table):
    """枚举值 → 顺序串；越界退回 'XYZ'。"""
    v = int(value)
    if 0 <= v < len(table):
        return table[v]
    return "XYZ"


# ─────────────────────────────────────────────────────────────────────────────
# 角度采样
# ─────────────────────────────────────────────────────────────────────────────

def quantize_angle(t, divisions):
    """把 [0,1) 的归一化角度量化到 divisions 个等分点；divisions <= 1 时原样返回。"""
    n = int(divisions)
    if n <= 1:
        return t
    return math.floor(t * n) / float(n)


def slice_fraction(index, divisions):
    """按出生序号轮转占位：第 index 颗粒子占第 index % divisions 个等分槽位。

    确定性轮转而非独立随机抽样，否则粒子数少时会出现同槽位堆叠、其他槽位落空。
    divisions <= 1 时返回 None，调用方应退回随机取值。
    """
    n = int(divisions)
    if n <= 1:
        return None
    return (int(index) % n) / float(n)


def sweep_fraction(rng, sweep_deg, divisions=0, full=360.0, index=None):
    """在 sweep_deg 度的扇形内取归一化角度 [0,1)。

    divisions > 1 且给了 index 时走确定性轮转，否则随机取值再量化。
    sweep_deg <= 0 或 >= full 视为整圈。
    """
    n = int(divisions)
    if n > 1 and index is not None:
        t = slice_fraction(index, n)
    else:
        t = rng.random()
        t = quantize_angle(t, divisions)
    if sweep_deg <= 0.0 or sweep_deg >= full:
        return t
    return t * (sweep_deg / full)


def unit_from_spherical(azimuth_t, polar_t):
    """(方位角比例, 极角比例) → 单位向量；polar_t 取 [-1, 1]。

    +Y 为上，极角绕 Y 轴量：polar_t 为 0 在赤道、±1 在两极。y 直接取 polar_t、
    水平半径取 sqrt(1 - y²)，使采样点在球面上均匀分布。
    """
    az = azimuth_t * 2.0 * math.pi
    y = max(-1.0, min(1.0, polar_t))
    r = math.sqrt(max(0.0, 1.0 - y * y))
    return Vec3(math.cos(az) * r, y, math.sin(az) * r)
