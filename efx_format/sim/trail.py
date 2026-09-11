# -*- coding: utf-8 -*-
"""
efx_format/sim/trail.py  —  位置历史的裁剪与重采样（条带类渲染体用）

`Particle.trail` 存的是**逐帧**位置（旧→新）。条带要的却是**按弧长**均分的一串点：
粒子快时一帧走很远、慢时几乎不动，直接拿帧点当顶点会让条带的分段疏密随速度乱跳。
所以先按长度裁剪，再按弧长均匀重采样。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
"""

from .state import Vec3


def clip_by_length(trail, max_len):
    """从最新的一端往回走，累计弧长不超过 `max_len`。

    返回 **新→旧** 的点串（至少 1 个点）。在恰好超出的那一段上插值切断，
    这样条带长度是连续变化的，不会随帧点的进出一跳一跳。
    """
    if not trail:
        return []
    out = [trail[-1].copy()]
    if max_len <= 0.0:
        return out

    acc = 0.0
    for i in range(len(trail) - 1, 0, -1):
        a = trail[i]
        b = trail[i - 1]
        seg = b - a
        d = seg.length()
        if d <= 1e-9:
            continue
        if acc + d >= max_len:
            t = (max_len - acc) / d
            out.append(a + seg * t)
            return out
        acc += d
        out.append(b.copy())
    return out


def polyline_length(pts):
    total = 0.0
    for i in range(len(pts) - 1):
        total += (pts[i + 1] - pts[i]).length()
    return total


def resample(pts, n):
    """把折线按弧长均分成 `n` 个点（含两端），保持原顺序。

    点不够或总长为 0 时退化：返回把首点重复 n 次（条带会收缩成一点，而不是崩）。
    """
    n = max(2, int(n))
    if not pts:
        return []
    if len(pts) == 1:
        return [pts[0].copy() for _ in range(n)]

    total = polyline_length(pts)
    if total <= 1e-9:
        return [pts[0].copy() for _ in range(n)]

    step = total / (n - 1)
    out = [pts[0].copy()]
    seg_i = 0
    seg_used = 0.0
    for k in range(1, n):
        want = step
        while want > 0.0 and seg_i < len(pts) - 1:
            a, b = pts[seg_i], pts[seg_i + 1]
            seg = b - a
            d = seg.length()
            left = d - seg_used
            if left <= 1e-9:
                seg_i += 1
                seg_used = 0.0
                continue
            if left >= want:
                seg_used += want
                want = 0.0
                out.append(a + seg * (seg_used / d))
            else:
                want -= left
                seg_i += 1
                seg_used = 0.0
        if len(out) <= k:                 # 走到头了，补末点
            out.append(pts[-1].copy())
    return out


def straight(origin, direction, length, n):
    """一条从 `origin` 沿 `direction` 伸出 `length` 的直线，均分 n 点。

    RIBBON 的「定长面片」模式和 RIBBONBLADE 在没有轨迹时都用它兜底。
    """
    n = max(2, int(n))
    d = direction.normalized(fallback=Vec3(0.0, 1.0, 0.0))
    step = float(length) / (n - 1)
    return [origin + d * (step * i) for i in range(n)]
