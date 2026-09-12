# -*- coding: utf-8 -*-
"""
efx_format/sim/trail.py  —  位置历史的裁剪与重采样（条带类渲染体用）

`Particle.trail` 存的是**逐帧**位置（旧→新）。条带要的却是**按弧长**均分的一串点：
粒子快时一帧走很远、慢时几乎不动，直接拿帧点当顶点会让条带的分段疏密随速度乱跳。
所以先按长度裁剪，再按弧长均匀重采样。

⚠ 性能：这是整个模拟里调用最密的一段——一条带一帧一趟，一个 PtLife 子树里同时
活着上千条带是常态。所以这里**全程在平铺 float 上算**，只在返回时才造 `Vec3`：
`Vec3` 本身约 0.1 µs 一个，中间结果照 `a + seg * t` 那样写，一次重采样就要造三百
多个临时对象，占掉整个 `build_render` 的一半。对外的签名和语义没变。

`clip_resample()` 是给条带用的**合并入口**：裁剪→算弧长→重采样一趟走完，中间不
落地成 `Vec3` 列表，也不会像「先 clip_by_length 再 polyline_length 再 resample」
那样把弧长算两遍。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
⚠ numpy 在这里是**可选加速**，不是依赖：`clip_resample_many` 有 numpy 就整批过
数组、没有就逐条退回标量路，两条路结果一致（`tools/trail_batch_diff.py` 对拍）。
模块本身照旧能在没有 numpy 的环境里 import。
"""

import math

from .state import Vec3

_sqrt = math.sqrt
#: None = 还没试过，False = 环境里没有
_NUMPY = None


def _numpy():
    global _NUMPY
    if _NUMPY is None:
        try:
            import numpy
            _NUMPY = numpy
        except Exception:
            _NUMPY = False
    return _NUMPY or None


#: 对外的同名出口：调用方（behaviors）要拿 numpy 自己做数组活时用它，
#: 拿到 None 就说明环境里没有，走纯 Python 那条路。
numpy_backend = _numpy
#: 绕开 `Vec3.__init__` 里的三次 `float()`。这里的入参全是算出来的 float，
#: 不需要再转一道。省得不多（约 5%），但这条路一帧要走几万次。
_new_vec = Vec3.__new__


def _mk(x, y, z):
    v = _new_vec(Vec3)
    v.x = x
    v.y = y
    v.z = z
    return v


def _flatten(pts):
    """点串 → (xs, ys, zs) 三条平铺 float 列表。"""
    xs = []
    ys = []
    zs = []
    for p in pts:
        xs.append(p.x)
        ys.append(p.y)
        zs.append(p.z)
    return xs, ys, zs


def _seg_lengths(xs, ys, zs):
    """逐段弧长 + 总弧长。"""
    segs = []
    total = 0.0
    ax = xs[0]
    ay = ys[0]
    az = zs[0]
    for i in range(1, len(xs)):
        bx = xs[i]
        by = ys[i]
        bz = zs[i]
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        d = _sqrt(dx * dx + dy * dy + dz * dz)
        segs.append(d)
        total += d
        ax = bx
        ay = by
        az = bz
    return segs, total


def _clip_flat(trail, max_len):
    """`clip_by_length` 的平铺版。

    返回 `(xs, ys, zs, segs, 弧长)`，顺序**新→旧**。逐段弧长顺手带出来——重采样
    正好要它，不带出去就得再过一遍 sqrt。
    """
    if not trail:
        return [], [], [], [], 0.0
    last = trail[-1]
    xs = [last.x]
    ys = [last.y]
    zs = [last.z]
    segs = []
    if max_len <= 0.0:
        return xs, ys, zs, segs, 0.0

    acc = 0.0
    ax = last.x
    ay = last.y
    az = last.z
    for i in range(len(trail) - 2, -1, -1):
        b = trail[i]
        bx = b.x
        by = b.y
        bz = b.z
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        d = _sqrt(dx * dx + dy * dy + dz * dz)
        if d <= 1e-9:
            continue            # 原地不动的那一帧不占段，也不推进 a
        if acc + d >= max_len:
            rest = max_len - acc
            t = rest / d
            xs.append(ax + dx * t)
            ys.append(ay + dy * t)
            zs.append(az + dz * t)
            segs.append(rest)
            return xs, ys, zs, segs, max_len
        acc += d
        xs.append(bx)
        ys.append(by)
        zs.append(bz)
        segs.append(d)
        ax = bx
        ay = by
        az = bz
    return xs, ys, zs, segs, acc


def _resample_flat(xs, ys, zs, n, segs=None, total=None):
    """平铺 float 版重采样；返回 `Vec3` 列表（唯一造对象的地方）。"""
    m = len(xs)
    if m == 0:
        return []
    if m == 1:
        return [_mk(xs[0], ys[0], zs[0]) for _ in range(n)]

    if segs is None:
        segs, arc = _seg_lengths(xs, ys, zs)
        if total is None:
            total = arc
    elif total is None:
        total = sum(segs)
    if total <= 1e-9:
        return [_mk(xs[0], ys[0], zs[0]) for _ in range(n)]

    step = total / (n - 1)
    out = [_mk(xs[0], ys[0], zs[0])]
    si = 0
    base = 0.0                  # xs[si] 处的累计弧长
    last = m - 2
    for k in range(1, n - 1):
        want = step * k
        while si < last and base + segs[si] < want:
            base += segs[si]
            si += 1
        d = segs[si]
        t = ((want - base) / d) if d > 1e-12 else 0.0
        if t > 1.0:
            t = 1.0
        j = si + 1
        ax = xs[si]
        ay = ys[si]
        az = zs[si]
        out.append(_mk(ax + (xs[j] - ax) * t,
                       ay + (ys[j] - ay) * t,
                       az + (zs[j] - az) * t))
    out.append(_mk(xs[-1], ys[-1], zs[-1]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 对外接口
# ─────────────────────────────────────────────────────────────────────────────

def clip_by_length(trail, max_len):
    """从最新的一端往回走，累计弧长不超过 `max_len`。

    返回 **新→旧** 的点串（至少 1 个点）。在恰好超出的那一段上插值切断，
    这样条带长度是连续变化的，不会随帧点的进出一跳一跳。
    """
    xs, ys, zs, _segs, _arc = _clip_flat(trail, max_len)
    return [_mk(xs[i], ys[i], zs[i]) for i in range(len(xs))]


def polyline_length(pts):
    total = 0.0
    n = len(pts)
    if n < 2:
        return total
    a = pts[0]
    ax = a.x
    ay = a.y
    az = a.z
    for i in range(1, n):
        b = pts[i]
        bx = b.x
        by = b.y
        bz = b.z
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        total += _sqrt(dx * dx + dy * dy + dz * dz)
        ax = bx
        ay = by
        az = bz
    return total


def resample(pts, n):
    """把折线按弧长均分成 `n` 个点（含两端），保持原顺序。

    点不够或总长为 0 时退化：返回把首点重复 n 次（条带会收缩成一点，而不是崩）。
    """
    n = max(2, int(n))
    if not pts:
        return []
    xs, ys, zs = _flatten(pts)
    return _resample_flat(xs, ys, zs, n)


def clip_resample(trail, max_len, n, min_arc=0.0):
    """裁剪 + 重采样一趟做完，返回 `(点串, 裁剪后弧长)`，顺序 **新→旧**。

    点数不足 2、或裁出来的弧长不超过 `min_arc` 时返回 `([], 弧长)`——调用方据此
    判断「发射器没动过」。这两种情况都在重采样**之前**短路，别白算一趟。
    """
    n = max(2, int(n))
    xs, ys, zs, segs, arc = _clip_flat(trail, max_len)
    if len(xs) < 2 or arc <= min_arc:
        return [], arc
    return _resample_flat(xs, ys, zs, n, segs, arc), arc


def straight(origin, direction, length, n):
    """一条从 `origin` 沿 `direction` 伸出 `length` 的直线，均分 n 点。

    RIBBON 的「定长面片」模式和 RIBBONBLADE 在没有轨迹时都用它兜底。
    """
    n = max(2, int(n))
    d = direction.normalized(fallback=Vec3(0.0, 1.0, 0.0))
    step = float(length) / (n - 1)
    ox, oy, oz = origin.x, origin.y, origin.z
    dx, dy, dz = d.x * step, d.y * step, d.z * step
    return [_mk(ox + dx * i, oy + dy * i, oz + dz * i) for i in range(n)]


def clip_resample_batch(trails, max_lens, counts, min_arc=0.0, reverse=False):
    """批量裁剪 + 重采样的 **numpy 原生**出口。没有 numpy 时返回 `None`。

    返回 `(Q, starts, sizes)`：

    * ``Q``       —— `(总点数, 3)` float64，所有条目的重采样点首尾相接
    * ``starts``  —— 长度 = `len(trails)`；第 i 条在 Q 里的起点，**-1 = 没有结果**
    * ``sizes``   —— 长度 = `len(trails)`；第 i 条的点数，0 = 没有结果

    `reverse=False` 输出 **新→旧**（同 `clip_resample`）；`True` 直接吐 **旧→新**
    （条带要的 base→tip），省掉调用方逐条再翻一次。

    做法：把所有轨迹**首尾相接**摊成一个大数组，逐段求长，再把跨轨迹的那些
    「接缝」段清零——这样一条全局 cumsum 就同时是每条轨迹各自的累计弧长，
    重采样退化成一次 `searchsorted` + 线性插值。
    """
    numpy = _numpy()
    if numpy is None:
        return None
    k = len(trails)
    starts = [-1] * k
    sizes = [0] * k
    if not k:
        return None, starts, sizes

    # ── 摊平 ─────────────────────────────────────────────────────────────────
    sel = []                     # 参与批处理的原始下标
    flat = []
    ex = flat.extend
    offs = []
    lens = []
    pos = 0
    for i in range(k):
        t = trails[i]
        n = len(t) if t is not None else 0
        if n < 2:
            continue
        for q in t:
            ex((q.x, q.y, q.z))
        sel.append(i)
        offs.append(pos)
        lens.append(n)
        pos += n
    if not sel:
        return None, starts, sizes

    # 弧长用 f8：f4 的累加误差在几十段之后就能让重采样点肉眼可见地偏
    P = numpy.array(flat, dtype="f8").reshape(-1, 3)
    off = numpy.array(offs, dtype=numpy.intp)
    last = off + numpy.array(lens, dtype=numpy.intp) - 1

    dv = P[1:] - P[:-1]
    seg = numpy.sqrt((dv * dv).sum(axis=1))
    if len(off) > 1:
        seg[last[:-1]] = 0.0            # 接缝：上一条的末点 → 下一条的首点
    C = numpy.empty(len(P), dtype="f8")
    C[0] = 0.0
    numpy.cumsum(seg, out=C[1:])

    total = C[last] - C[off]
    ml = numpy.array([float(max_lens[i]) for i in sel], dtype="f8")
    numpy.maximum(ml, 0.0, out=ml)
    arc = numpy.minimum(ml, total)

    keep = numpy.nonzero(arc > float(min_arc))[0]
    if not len(keep):
        return None, starts, sizes

    # ── 查询点：第 j 个输出落在「离最新端 j·arc/(n-1)」处 ────────────────────
    ns = numpy.array([max(2, int(counts[sel[j]])) for j in keep], dtype=numpy.intp)
    n_out = int(ns.sum())
    ent = numpy.repeat(numpy.arange(len(keep)), ns)         # 每个输出点属于第几条
    run = numpy.zeros(len(ns), dtype=numpy.intp)
    numpy.cumsum(ns[:-1], out=run[1:])
    kpos = numpy.arange(n_out, dtype=numpy.intp) - numpy.repeat(run, ns)
    if reverse:
        kpos = numpy.repeat(ns - 1, ns) - kpos              # 直接吐 旧→新

    k_last = last[keep]
    step = arc[keep] / (ns - 1).astype("f8")
    a = C[k_last][ent] - step[ent] * kpos.astype("f8")

    # side='right' 让重复值（原地不动的那些帧）自然落到有长度的那一段上，
    # 等价于标量路里「d <= 1e-9 就 continue」
    j = numpy.searchsorted(C, a, side="right") - 1
    numpy.clip(j, off[keep][ent], k_last[ent] - 1, out=j)
    base = C[j]
    dseg = C[j + 1] - base
    # 用 where= 而不是 numpy.where(...)：后者两个分支都会先算出来，零长度段
    # 照样触发除零警告刷屏
    frac = numpy.zeros(len(j), dtype="f8")
    numpy.divide(a - base, dseg, out=frac, where=(dseg > 1e-12))
    numpy.clip(frac, 0.0, 1.0, out=frac)
    Q = P[j] + (P[j + 1] - P[j]) * frac[:, None]

    for jj in range(len(keep)):
        i = sel[int(keep[jj])]
        starts[i] = int(run[jj])
        sizes[i] = int(ns[jj])
    return Q, starts, sizes


def clip_resample_many(trails, max_lens, counts, min_arc=0.0):
    """`clip_resample` 的**批量版**，返回 `Vec3` 点串。

    返回与入参等长的列表，每项是 `Vec3` 点串（**新→旧**，同 `clip_resample`）
    或 `[]`（点不足 2 个 / 裁出来的弧长不超过 `min_arc`）。

    有 numpy 就走 `clip_resample_batch`，没有就逐条退回标量路——两条路结果一致
    （`tools/trail_batch_diff.py` 对拍）。
    """
    k = len(trails)
    out = [[] for _ in range(k)]
    if not k:
        return out

    got = clip_resample_batch(trails, max_lens, counts, min_arc)
    if got is None:
        for i in range(k):
            out[i] = clip_resample(trails[i], max_lens[i], counts[i], min_arc)[0]
        return out

    Q, starts, sizes = got
    if Q is None:
        return out
    rows = Q.tolist()
    for i in range(k):
        s = starts[i]
        if s < 0:
            continue
        out[i] = [_mk(r[0], r[1], r[2]) for r in rows[s:s + sizes[i]]]
    return out
