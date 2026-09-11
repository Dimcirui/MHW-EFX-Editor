# -*- coding: utf-8 -*-
"""
efx_format/sim/vecmath.py  —  旋转与采样的小工具

两套旋转顺序表
--------------
EFX 里 rotationOrder 有**两套不同的取值→顺序映射**（见 efx_format/schema/enums.py）：

    VELOCITY3D.rotOrder      (_ROT_ORDER6)        0=XYZ 1=XZY 2=YXZ 3=YZX 4=ZXY 5=ZYX
    TRANSFORM3D/ES3D/RIBBON  (_TRANSFORM_ROT_ORDER) 0=XYZ 1=YZX 2=YXZ 3=ZYX 4=ZXY 5=XZY

两者实测不一致，不能混用。本模块各给一张表，调用方按属性选。

⚠ 待标定：顺序串 "XYZ" 里「先写的先作用于向量」还是相反，没有实测。
`SimConfig.rot_order_applied` 是这个开关，默认 'forward'（先写的先作用）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
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
    """把向量 `v` 依次绕三个轴旋转。角度是**度**。

    `applied='forward'` → 顺序串里先写的先作用于向量。
    """
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
    """把 [0,1) 的归一化角度量化到 `divisions` 个等分点上。

    对应 EMITTERSHAPE3D.rangeDivideHorizontalNum/VerticalNum——注释写明它是
    **等分数量**而非生成个数（见 attributes.py EMITTERSHAPE2D 一节的同概念说明）。
    `divisions <= 1` 时不量化。
    """
    n = int(divisions)
    if n <= 1:
        return t
    return math.floor(t * n) / float(n)


def sweep_fraction(rng, sweep_deg, divisions=0, full=360.0):
    """在 `sweep_deg` 度的扇形内取一个归一化角度 [0,1)，可按 `divisions` 等分量化。

    `sweep_deg >= full` 或 <= 0 → 视为整圈。
    """
    t = rng.random()
    t = quantize_angle(t, divisions)
    if sweep_deg <= 0.0 or sweep_deg >= full:
        return t
    return t * (sweep_deg / full)


def unit_from_spherical(azimuth_t, polar_t):
    """(方位角比例, 极角比例) → 单位向量。

    游戏坐标系 +Y=上，故极角绕 Y 轴量：polar_t=0 → 赤道，±1 → 两极。
    `polar_t` 取 [-1, 1]，用 cos 映射保证球面均匀（避免两极堆积）。
    """
    az = azimuth_t * 2.0 * math.pi
    # polar_t ∈ [-1,1] → y = polar_t，水平半径 = sqrt(1 - y²)
    y = max(-1.0, min(1.0, polar_t))
    r = math.sqrt(max(0.0, 1.0 - y * y))
    return Vec3(math.cos(az) * r, y, math.sin(az) * r)
