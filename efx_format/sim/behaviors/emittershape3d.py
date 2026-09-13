# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/emittershape3d.py  —  EMITTERSHAPE3D（生成位置）

字段语义依作者的《特效教程·七：生成方式》，下面每条都对得上原文。

    shapeType         0=立方体 1=球体 2=圆柱体 3=点（点是 bug 值，正常不用）
    rangeXYZ          FLOAT6 = 偏移 / 尺寸（见下）
    localRotationX/Y/Z + rotationOrder   生成形状自身的整体旋转
    scanAngleHorizontal   横向扫描角度：只有球/圆柱用，360=全向、180=一半、90=1/4
    scanAngleVertical     纵向扫描角度：**只有球用**，0=全向、180=一半、360=不生成
    rangeDivideVerticalNum    纵向等分数量：绕竖轴切扇形（立方体/球/圆柱都用）
    rangeDivideHorizontalNum  横向等分数量：只有球/圆柱用（球=圆锥面，圆柱=水平切片）
    radiusOrigin / radiusEnd  起始/结束半径：**只有圆柱用**，沿高度的锥度
    rangeDivideAxis   0=X 1=Z 2=Y，立方体下决定 12 条边里哪一组参与
    rotationCorrect   旋转修正方式：作用不明（会改变朝向，可能与摄像机有关），未模拟

生成范围 = 偏移 / 尺寸（不是 Min/Max）
--------------------------------------
原文：「偏移决定这个形状从多大的**内边界**开始，尺寸是在这个内边界基础上**向外延伸
的具体厚度**」。所以

    内边界 = 偏移(idx 0/2/4)      外边界 = 偏移 + 尺寸(idx 1/3/5)

立方体给「偏移=10 尺寸=0」是一个立方体边框；再给尺寸=10 就是厚度 10、内部掏空的
填充立方体。三种形状同一套读法。

⚠ RE DTI dump 的官方名是 `RangeMinX/RangeMaxX`，与实机行为对不上，别被官方名带回
Min/Max（`SimConfig.es3d_range_mode='minmax'` 保留旧读法只作对照）。

圆柱体多一次位置偏移
--------------------
原文：「圆柱体…要比单纯的偏移+尺寸更复杂一些，他会在内部掏空的基础上、**再进行
实际位置的偏移**」。这里实现为：横截面（XZ）是内径=偏移、厚度=尺寸的圆环；竖直方向
（Y）**不是对称壳层**——偏移 Y 是底面位置、尺寸 Y 是往 +Y 长出去的高度：

    y ∈ [偏移Y, 偏移Y + 尺寸Y]

即尺寸 Y=20 就是从底面向 +Y 延伸 20，不是上下各 20（用户 2026-09-12 指出）。锥度的
起始半径在底面（y=偏移Y）、结束半径在顶面。

等分数量：纵向切扇形，横向切纬度/高度
-------------------------------------
原文：纵向等分「沿纵向等分成 n 份切片」，立方体/球/圆柱都是**从正上方看**分成 n 份
（球侧面看是 n 个叶片）；横向等分只有球和圆柱用——圆柱是「正面看上去把圆柱等分
切片」（沿高度），球是「6 等分 = 横向上拆成 6 个圆锥面（其中 2 个锥角为 0 退化成
线段）」（沿极角）。

起始/结束半径 = 锥度
--------------------
原文：「只有圆锥会用，起始结束半径默认为 1 就是圆柱体，如果把其中一个缩小，就变成
圆台甚至圆锥」。所以它是**沿高度插值的半径倍率**，不是半径区间：起始半径 0.2 →
顶/底直径 5:1 的圆台。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

import math

from ...hashes import EMITTERSHAPE3D
from ..registry import Behavior, register
from ._common import emitter_place
from ..stages import FORCE
from ..state import Vec3
#: 掏空盒子的拒绝采样最多试几次（试不出来就用最后一个点，形态略偏但不卡死）
_BOX_TRIES = 8


def _lerp(a, b, t):
    return a + (b - a) * t


from ..vecmath import (ROT_ORDER_TRANSFORM, quantize_angle, rot_order_name,
                       rotate_euler, sweep_fraction, unit_from_spherical)

SHAPE_BOX = 0
SHAPE_SPHERE = 1
SHAPE_CYLINDER = 2
SHAPE_POINT = 3

#: rangeDivideAxis: 0=X 1=Z 2=Y（1 和 2 是反的，照 enums.ENUM_RANGE_DIVIDE_AXIS）
_DIVIDE_AXIS = {0: "x", 1: "z", 2: "y"}


@register(EMITTERSHAPE3D)
class EmitterShape3D(Behavior):
    """只在出生时决定位置；不参与逐帧 step。"""

    STAGE = FORCE
    ORDER = 10

    def on_emitter_init(self, em, rng):
        f = em.f(EMITTERSHAPE3D)
        if f is None:
            return
        shape = f.i("shapeType")
        if shape > SHAPE_POINT:
            em.note("EMITTERSHAPE3D.shapeType=%d 超出已知四态，按 Point 处理" % shape)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(EMITTERSHAPE3D, p)
        if f is None:
            return
        cfg = em.config

        center, inner, outer = self._region(f, cfg)
        shape = f.i("shapeType")
        local = center + self._sample(shape, inner, outer, f, rng)

        # 局部旋转（rangeDivideAxis 不受它影响——annotations 里写明了）
        rot_order = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)
        local = rotate_euler(local,
                             f.get("localRotationX"), f.get("localRotationY"),
                             f.get("localRotationZ"),
                             order=rot_order, applied=cfg.rot_order_applied)

        # 发射器自己的动态旋转/缩放（TRANSFORM3D 的 rotation_velocity / scale_velocity）
        local = emitter_place(em, local)

        p.spawn_pos = local
        p.pos = em.origin + local

    # ── rangeXYZ → 内边界 / 外边界 ────────────────────────────────────────────
    @staticmethod
    def _region(f, cfg):
        """返回 (中心, 内边界, 外边界)，逐轴。"""
        lo = f.xyz_lo("rangeXYZ")
        hi = f.xyz_hi("rangeXYZ")
        if cfg.es3d_range_mode == "minmax":
            # 旧读法（官方通道名 RangeMin*/RangeMax*），留作对照
            center = Vec3((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, (lo.z + hi.z) * 0.5)
            half = Vec3((hi.x - lo.x) * 0.5, (hi.y - lo.y) * 0.5, (hi.z - lo.z) * 0.5)
            return center, Vec3(), half
        # 'shell'（默认）：偏移=内边界、尺寸=向外延伸的厚度
        inner = lo
        outer = Vec3(lo.x + hi.x, lo.y + hi.y, lo.z + hi.z)
        return Vec3(), inner, outer

    # ── 各形状在「内边界 → 外边界」的壳层内采样 ──────────────────────────────
    def _sample(self, shape, inner, outer, f, rng):
        if shape == SHAPE_BOX:
            return self._sample_box(inner, outer, f, rng)
        if shape == SHAPE_SPHERE:
            return self._sample_sphere(inner, outer, f, rng)
        if shape == SHAPE_CYLINDER:
            return self._sample_cylinder(inner, outer, f, rng)
        # Point（3）及未知值：退化成一个点，落在偏移处。教程说点「严格来讲是一个
        # bug 值，并不能算」，所以这里只求一个确定的退化行为，不追求还原。
        return inner.copy()

    @staticmethod
    def _fan_slice(t, f):
        """纵向等分数量：绕竖轴把 [0,1) 的方位角量化成 n 份扇形切片。"""
        return quantize_angle(t, f.i("rangeDivideVerticalNum"))

    def _sample_box(self, inner, outer, f, rng):
        """内部掏空的盒子：落在外盒内、且不在内盒内（尺寸=0 时退化成盒子表面/边框）。

        纵向等分（绕竖轴的扇形切片）用**拒绝采样**实现：抽到的点按它的方位角落在
        哪一份切片上，量化到该切片的角度再按半径投回去——立方体没有半径概念，故
        这里只把方位角量化，径向长度保持原样。
        """
        div_n = f.i("rangeDivideVerticalNum")
        for _ in range(_BOX_TRIES):
            v = Vec3((rng.random() * 2.0 - 1.0) * outer.x,
                     (rng.random() * 2.0 - 1.0) * outer.y,
                     (rng.random() * 2.0 - 1.0) * outer.z)
            if (abs(v.x) >= inner.x or abs(v.y) >= inner.y or abs(v.z) >= inner.z):
                break
        if div_n > 1:
            # 绕竖轴（Y）把方位角量化到等分切片上，半径与高度不动
            r = math.hypot(v.x, v.z)
            t = (math.atan2(v.z, v.x) / (2.0 * math.pi)) % 1.0
            a = self._fan_slice(t, f) * 2.0 * math.pi
            v = Vec3(math.cos(a) * r, v.y, math.sin(a) * r)
        return v

    def _sample_sphere(self, inner, outer, f, rng):
        # 方位角：横向扫描角度限制范围，纵向等分数量切扇形
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideVerticalNum"))
        # 极角：横向等分数量 = 圆锥面（n 等分把球拆成 n 个圆锥面）
        pt = rng.random() * 2.0 - 1.0
        h_div = f.i("rangeDivideHorizontalNum")
        if h_div > 1:
            pt = quantize_angle((pt + 1.0) * 0.5, h_div) * 2.0 - 1.0
        # 纵向扫描角度：0=全向、180=一半、360=不生成 → 保留的极角带 = 1 - v/360
        v_sweep = f.get("scanAngleVertical", 0.0)
        if v_sweep > 0.0:
            pt *= max(0.0, 1.0 - min(1.0, v_sweep / 360.0))
        d = unit_from_spherical(az, pt)
        t = self._shell_fraction(rng)
        return Vec3(d.x * _lerp(inner.x, outer.x, t),
                    d.y * _lerp(inner.y, outer.y, t),
                    d.z * _lerp(inner.z, outer.z, t))

    def _sample_cylinder(self, inner, outer, f, rng):
        # 方位角：横向扫描角度限制范围，纵向等分数量切扇形
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideVerticalNum"))
        a = az * 2.0 * math.pi
        # 高度：横向等分数量 = 沿高度的水平切片。
        # ⚠ 高度是**单向**的：偏移 Y 是底面位置、尺寸 Y 是往 +Y 长出去的高度，
        # 即 y ∈ [偏移, 偏移+尺寸]。X/Z 那两轴是「内半径 + 厚度」的对称壳层，Y 不是
        # ——别照着它写成 ±尺寸（用户 2026-09-12 指出：尺寸 Y=20 是向 +Y 延伸 20）。
        h_t = rng.random()
        h_div = f.i("rangeDivideHorizontalNum")
        if h_div > 1:
            h_t = quantize_angle(h_t, h_div)
        size_y = max(0.0, outer.y - inner.y)
        y = inner.y + h_t * size_y
        # 半径：内径=偏移、厚度=尺寸的圆环，再乘沿高度插值的锥度（起始/结束半径）
        t = self._shell_fraction(rng)
        taper = _lerp(f.get("radiusOrigin", 1.0), f.get("radiusEnd", 1.0),
                      (h_t + 0.0))
        return Vec3(math.cos(a) * _lerp(inner.x, outer.x, t) * taper,
                    y,
                    math.sin(a) * _lerp(inner.z, outer.z, t) * taper)

    @staticmethod
    def _shell_fraction(rng):
        """在「内边界 → 外边界」之间取的比例。尺寸=0 时内外重合，自然退化成表面。"""
        return rng.random()

    # ── 轮廓（给预览画线框用）────────────────────────────────────────────────
    def outline(self, em, segments=28):
        """生成区域的线框，返回**成对**的点（p0,p1, p0,p1, …），与粒子同一坐标空间。

        刻意和 `on_particle_spawn` 共用 `_region` 和同一套旋转/摆位——线框和粒子
        真正落点必须来自同一份读法，否则「看着框在这儿、粒子却生在那儿」比不画
        还糟。形状分支逐条对应 `_sample_*`，而且画的是**封闭的区域**、不是两条
        孤立的轮廓：

            立方体   内外两个盒子的 12 棱 + 8 条角对角的径向棱
            球       内外两层的赤道/极带环 + 经线 + 径向棱；扫描角度切出来的两个
                     切面由「两端的经线 + 那里的径向棱」封口
            圆柱     内外两半径的上下底环 + 竖棱 + 上下底的径向棱，半径按
                     起始/结束半径沿高度锥度插值
            点       一个小十字

        ⚠ 径向棱不是装饰。这一族形状是「内边界 + 向外延伸的厚度」，只画内外两层
        却不连起来的话，**壳层这个概念在画面上根本不存在**——看着就是两个互不相干
        的框，既读不出厚度，扫描角度切出来的切面也没有封口。尺寸=0 时内外重合，
        径向棱自然退化成零长度，看到的就是一个面/框，符合预期。

        `segments` 是圆/环的分段数，只影响线框精细度。
        """
        f = em.f(EMITTERSHAPE3D)
        if f is None:
            return []
        cfg = em.config
        center, inner, outer = self._region(f, cfg)
        shape = f.i("shapeType")
        n = max(6, int(segments))

        if shape == SHAPE_BOX:
            pts = _box_lines(inner, outer)
        elif shape == SHAPE_SPHERE:
            pts = _sphere_lines(inner, outer, f, n)
        elif shape == SHAPE_CYLINDER:
            pts = _cylinder_lines(inner, outer, f, n)
        else:
            pts = _point_lines(inner)

        rot_order = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)
        rx, ry, rz = (f.get("localRotationX"), f.get("localRotationY"),
                      f.get("localRotationZ"))
        out = []
        for v in pts:
            v = center + v
            v = rotate_euler(v, rx, ry, rz, order=rot_order,
                             applied=cfg.rot_order_applied)
            v = emitter_place(em, v)
            out.append(em.origin + v)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 线框构造（纯几何，不抽随机数）
# ─────────────────────────────────────────────────────────────────────────────

#: 立方体 12 条棱的顶点对（下标进 8 个角）
_BOX_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0),
              (4, 5), (5, 7), (7, 6), (6, 4),
              (0, 4), (1, 5), (2, 6), (3, 7))


def _box_corners(h):
    return [Vec3(x * h.x, y * h.y, z * h.z)
            for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]


def _hollow(inner):
    return bool(inner.x or inner.y or inner.z)


def _box_lines(inner, outer):
    """外盒 12 棱；掏空时再加内盒 12 棱 + **8 条角对角的径向棱**。

    那 8 条是「这是个有厚度的壳、不是两个不相干的框」的唯一线索。
    """
    out = []
    co = _box_corners(outer)
    for a, b in _BOX_EDGES:
        out.append(co[a])
        out.append(co[b])
    if _hollow(inner):
        ci = _box_corners(inner)
        for a, b in _BOX_EDGES:
            out.append(ci[a])
            out.append(ci[b])
        for k in range(8):
            out.append(ci[k])
            out.append(co[k])
    return out


def _arc_pts(radius, n, frac, y_scale=0.0, elev=0.0):
    """绕竖轴的一段水平弧（或整圈）上的点列。`elev` 是仰角的 sin 值。"""
    cy = math.sqrt(max(0.0, 1.0 - elev * elev))
    yy = elev * y_scale
    span = 2.0 * math.pi * max(0.0, min(1.0, frac))
    closed = frac >= 0.999
    steps = n if closed else max(3, int(n * max(0.08, frac)))
    out = []
    for i in range(steps + 1):
        a = span * (i / float(steps))
        out.append(Vec3(math.cos(a) * radius.x * cy, yy, math.sin(a) * radius.z * cy))
    if closed:
        out[-1] = out[0]        # 收口
    return out


def _strip(pts):
    """点列 → 首尾相接的线段对。"""
    out = []
    for i in range(len(pts) - 1):
        out.append(pts[i])
        out.append(pts[i + 1])
    return out


def _azimuths(h_frac, full=4, swept=3):
    """要在哪几个方位角上画经线/竖棱。扫描不满整圈时**必须包含两个端点**，
    那两条经线加上径向棱就是切面的封口。"""
    if h_frac >= 0.999:
        return [2.0 * math.pi * (k / float(full)) for k in range(full)]
    span = 2.0 * math.pi * h_frac
    return [span * (k / float(swept - 1)) for k in range(swept)]


def _sphere_lines(inner, outer, f, n):
    """球壳：内外两层的赤道/极带环 + 经线，再用径向棱把两层连起来。

    扫描角度切出来的两个切面由「两端的经线 + 那里的径向棱」封口。
    """
    h_frac = max(0.0, min(1.0, (f.get("scanAngleHorizontal", 360.0) or 360.0) / 360.0))
    v_keep = max(0.0, 1.0 - min(1.0, (f.get("scanAngleVertical", 0.0) or 0.0) / 360.0))
    hollow = _hollow(inner)
    shells = [outer] + ([inner] if hollow else [])
    azs = _azimuths(h_frac)
    # 极角上取几个采样：中间 + 两端（纵向扫描把两端从极点收进来）
    elevs = [0.0] if v_keep <= 0.0 else [-v_keep, 0.0, v_keep]

    out = []
    for r in shells:
        for ev in elevs:
            if abs(abs(ev) - 1.0) < 1e-6:
                continue                    # 极点上的环退化成一个点
            out.extend(_strip(_arc_pts(r, n, h_frac, r.y, ev)))
        if v_keep > 0.0:
            for a in azs:                   # 经线
                ca, sa = math.cos(a), math.sin(a)
                pts = []
                for i in range(n + 1):
                    ev = ((i / float(n)) * 2.0 - 1.0) * v_keep
                    cy = math.sqrt(max(0.0, 1.0 - ev * ev))
                    pts.append(Vec3(ca * cy * r.x, ev * r.y, sa * cy * r.z))
                out.extend(_strip(pts))

    if hollow:                              # 径向棱：内 ↔ 外
        for a in azs:
            ca, sa = math.cos(a), math.sin(a)
            for ev in elevs:
                cy = math.sqrt(max(0.0, 1.0 - ev * ev))
                out.append(Vec3(ca * cy * inner.x, ev * inner.y, sa * cy * inner.z))
                out.append(Vec3(ca * cy * outer.x, ev * outer.y, sa * cy * outer.z))
    return out


def _cylinder_lines(inner, outer, f, n):
    """圆柱/圆台壳：上下底的内外环 + 竖棱，再用径向棱把内外连起来。

    半径按起始/结束半径沿高度锥度插值——底面用起始、顶面用结束，与
    `_sample_cylinder` 里 `h_t=0 → y_lo` 的对应关系一致。
    """
    h_frac = max(0.0, min(1.0, (f.get("scanAngleHorizontal", 360.0) or 360.0) / 360.0))
    r0 = f.get("radiusOrigin", 1.0)
    r1 = f.get("radiusEnd", 1.0)
    size_y = max(0.0, outer.y - inner.y)
    y_lo, y_hi = inner.y, inner.y + size_y      # 单向：底面在偏移处，往 +Y 长
    hollow = bool(inner.x or inner.z)
    shells = [outer] + ([inner] if hollow else [])
    azs = _azimuths(h_frac)

    def at(r, taper, y, a):
        return Vec3(math.cos(a) * r.x * taper, y, math.sin(a) * r.z * taper)

    out = []
    for r in shells:
        for y, taper in ((y_lo, r0), (y_hi, r1)):
            ring = _arc_pts(Vec3(r.x * taper, 0.0, r.z * taper), n, h_frac)
            out.extend(_strip([Vec3(p.x, y, p.z) for p in ring]))
        for a in azs:                       # 竖棱
            out.append(at(r, r0, y_lo, a))
            out.append(at(r, r1, y_hi, a))

    if hollow:                              # 径向棱：上下底各一圈
        for a in azs:
            out.append(at(inner, r0, y_lo, a))
            out.append(at(outer, r0, y_lo, a))
            out.append(at(inner, r1, y_hi, a))
            out.append(at(outer, r1, y_hi, a))
    return out


def _point_lines(at):
    d = 5.0     # 游戏单位，纯显示尺寸
    return [Vec3(at.x - d, at.y, at.z), Vec3(at.x + d, at.y, at.z),
            Vec3(at.x, at.y - d, at.z), Vec3(at.x, at.y + d, at.z),
            Vec3(at.x, at.y, at.z - d), Vec3(at.x, at.y, at.z + d)]
