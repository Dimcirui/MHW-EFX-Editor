# -*- coding: utf-8 -*-
"""RIBBON 贴图缩放的几何切分。

长度方向按 `uvScaleMode` 重复贴图，宽度方向以中线缩放、超出部分取边缘像素。两者都在
几何上切分实现，不依赖采样器的寻址模式：贴图可能是序列帧大图里的一个子格，采样器的
重复或钳制作用于整张大图，无法限制在子格内。

- 长度方向在每个整数重复边界处切开，每一片内的局部 v 落在 [0, 1]，边界两侧分别取 1 和 0。
- 宽度方向在 u' = 0 与 u' = 1 处切开，u' = 0.5 + (s − 0.5) × w；超出 [0, 1] 的列 u 恒为
  边缘值，即拉伸边缘像素。

本模块零 bpy 依赖，只输出参数，由 glue 层展开为三角形。
"""

import math

#: uvScaleMode 取值
UV_SCALE_OFF = 0
UV_SCALE_FIXED = 1
UV_SCALE_ASPECT = 2


def repeat_count(mode, scale, length, width):
    """长度方向的贴图重复次数。

    - 不缩放：恒为 1。
    - 固定次数：等于 `scale`。
    - 按长宽比：`scale` × 长 / 宽，长宽相等时与固定次数相同。宽度不大于 0 时退回固定次数。
    """
    if mode == UV_SCALE_FIXED:
        return max(0.0, scale)
    if mode == UV_SCALE_ASPECT:
        if width <= 1e-9:
            return max(0.0, scale)
        return max(0.0, scale * length / width)
    return 1.0


def width_columns(w):
    """宽度方向的列划分，返回 `[(s0, s1, u0, u1), …]`。

    s 为横向参数（0=左，1=右），u 为贴图横坐标。w = 1 时为单列 (0, 1, 0, 1)。
    """
    if w == 0.0:
        return [(0.0, 1.0, 0.5, 0.5)]
    cuts = [0.0, 1.0]
    for x in (0.0, 1.0):
        s = 0.5 + (x - 0.5) / w
        if 1e-9 < s < 1.0 - 1e-9:
            cuts.append(s)
    cuts.sort()

    def u_at(s):
        return min(1.0, max(0.0, 0.5 + (s - 0.5) * w))

    return [(a, b, u_at(a), u_at(b)) for a, b in zip(cuts, cuts[1:]) if b - a > 1e-9]


def length_pieces(n, repeat):
    """长度方向的分片，返回 `[(段号 i, fa, fb, va, vb), …]`。

    第 i 段连接第 i 与第 i+1 行（0 为 base 端），fa/fb 为片在该段内的起止比例，va/vb 为
    片两端的局部 v。重复从 base 端起算；repeat = 1 时每段一片，v 与原先按行号均分一致。
    """
    m = n - 1
    if m < 1:
        return []
    r = max(0.0, repeat)
    out = []
    for i in range(m):
        ra = i * r / m
        rb = (i + 1) * r / m
        if rb - ra <= 1e-12:
            v = ra - math.floor(ra)
            out.append((i, 0.0, 1.0, v, v))
            continue
        cuts = [ra]
        k = math.floor(ra) + 1
        while k < rb - 1e-9:
            if k > ra + 1e-9:
                cuts.append(float(k))
            k += 1
        cuts.append(rb)
        span = rb - ra
        for x0, x1 in zip(cuts, cuts[1:]):
            tile = math.floor(0.5 * (x0 + x1))
            out.append((i, (x0 - ra) / span, (x1 - ra) / span, x0 - tile, x1 - tile))
    return out


def corner_uv(corners, u, v):
    """在四角 UV（BL, BR, TR, TL）围成的格内按 (u, v) 双线性取点。"""
    bl, br, tr, tl = corners
    bx = bl[0] + (br[0] - bl[0]) * u
    by = bl[1] + (br[1] - bl[1]) * u
    tx = tl[0] + (tr[0] - tl[0]) * u
    ty = tl[1] + (tr[1] - tl[1]) * u
    return (bx + (tx - bx) * v, by + (ty - by) * v)
