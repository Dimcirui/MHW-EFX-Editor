# -*- coding: utf-8 -*-
"""EMITTERSHAPE3D —— 生成位置。

字段职能：

    shapeType                 0=立方体 1=球体 2=圆柱体 3=点（点为 bug 值，正常不使用）
    rangeXYZ                  FLOAT6，解释为偏移 / 尺寸，见下
    localRotationX/Y/Z +      生成形状自身的整体旋转
    rotationOrder
    scanAngleHorizontal       横向扫描角度。仅球与圆柱使用，360=全方向、180=一半、90=1/4
    scanAngleVertical         纵向扫描角度。**仅球使用**，0=全方向、180=一半、360=不生成
    rangeDivideVerticalNum    纵向等分数：绕竖轴划分扇区，立方体／球／圆柱均使用
    rangeDivideHorizontalNum  横向等分数。仅球与圆柱使用：球划分为 n 个圆锥面（其中 2 个锥角
                              为 0，退化为线段），圆柱沿高度划分为水平切片
    radiusOrigin / radiusEnd  起始／结束半径。**仅圆柱使用**，为沿高度插值的半径倍率而非半径
                              区间：两者均为 1 时为圆柱，缩小其一则为圆台乃至圆锥
    rangeDivideAxis           0=X 1=Z 2=Y，决定立方体 12 条棱中参与的一组
    rotationCorrect           旋转修正方式，作用不明（会改变朝向），未模拟

生成范围为**偏移 / 尺寸**而非 Min/Max：偏移决定形状的内边界，尺寸为在内边界基础上向外延伸的
厚度。

    内边界 = 偏移(idx 0/2/4)        外边界 = 偏移 + 尺寸(idx 1/3/5)

立方体取「偏移=10 尺寸=0」为立方体边框；尺寸取 10 时为厚度 10、内部中空的立方体壳。三种形状
采用同一解释。

⚠ RE DTI dump 中的官方名为 `RangeMinX` / `RangeMaxX`，与实机行为不符，不得据此恢复 Min/Max
解释。

等分采用确定性分配：方位角或高度按粒子出生序号轮流分配到 n 份之一，而非随机落入。立方体没有
半径概念，径向长度由拒绝采样取得，仅方位角按序号分配。

线框（`outline`）表示**封闭区域**，而非两条独立轮廓：

    立方体   内外两个盒子的 12 条棱，以及连接对应角的 8 条径向棱
    球       内外两层的赤道／纬线环与经线，以及径向棱；扫描角度形成的两个截面由两端经线与
             该处的径向棱封闭
    圆柱     内外两个半径的上下底环与竖棱，以及上下底的径向棱；半径按起始／结束半径沿高度
             插值
    点       一个小十字

径向棱不可省略：这类形状由「内边界 + 向外延伸的厚度」定义，只画内外两层而不连接，线框无法
表示壳层厚度，扫描截面也不封闭。尺寸=0 时内外重合，径向棱长度为 0。

维护约束：
- 圆柱的 Y 方向**不是对称壳层**：偏移 Y 为底面位置，尺寸 Y 为向 +Y 延伸的高度，即
  `y ∈ [偏移Y, 偏移Y + 尺寸Y]`。X / Z 才是「内半径 + 厚度」的对称壳层，Y 不得按 ±尺寸处理。
  锥度的起始半径位于底面（y=偏移Y），结束半径位于顶面。
- `outline()` 必须与 `on_particle_spawn` 共用 `_region` 以及同一套旋转与摆放：线框与粒子
  位置不一致时，线框会误导使用者。
"""

import math

from ...hashes import EMITTERSHAPE3D
from ..registry import Behavior, register
from ._common import emitter_place
from ..stages import FORCE
from ..state import Vec3
#: 中空盒子拒绝采样的最大尝试次数；未命中时使用最后一个点，分布略有偏差但不会阻塞
_BOX_TRIES = 8


def _lerp(a, b, t):
    return a + (b - a) * t


from ..vecmath import (ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler,
                       slice_fraction, sweep_fraction, unit_from_spherical)

SHAPE_BOX = 0
SHAPE_SPHERE = 1
SHAPE_CYLINDER = 2
SHAPE_POINT = 3

#: rangeDivideAxis：0=X 1=Z 2=Y（1 与 2 的顺序相反，与 enums.ENUM_RANGE_DIVIDE_AXIS 一致）
_DIVIDE_AXIS = {0: "x", 1: "z", 2: "y"}


@register(EMITTERSHAPE3D)
class EmitterShape3D(Behavior):
    """只在出生时决定位置，不参与逐帧 step。"""

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
        local = center + self._sample(shape, inner, outer, f, rng, p.index)

        # 局部旋转；rangeDivideAxis 不受其影响
        rot_order = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)
        local = rotate_euler(local,
                             f.get("localRotationX"), f.get("localRotationY"),
                             f.get("localRotationZ"),
                             order=rot_order, applied=cfg.rot_order_applied)

        # 发射器自身的动态旋转与缩放
        local = emitter_place(em, local)

        p.spawn_pos = local
        p.pos = em.origin + local

    # ── rangeXYZ → 内边界 / 外边界 ────────────────────────────────────────────
    @staticmethod
    def _region(f, cfg):
        """逐轴返回 (中心, 内边界, 外边界)。"""
        lo = f.xyz_lo("rangeXYZ")
        hi = f.xyz_hi("rangeXYZ")
        # 偏移为内边界，尺寸为向外延伸的厚度
        inner = lo
        outer = Vec3(lo.x + hi.x, lo.y + hi.y, lo.z + hi.z)
        return Vec3(), inner, outer

    # ── 各形状在内边界与外边界之间的壳层内采样 ─────────────────────────────
    def _sample(self, shape, inner, outer, f, rng, index):
        if shape == SHAPE_BOX:
            return self._sample_box(inner, outer, f, rng, index)
        if shape == SHAPE_SPHERE:
            return self._sample_sphere(inner, outer, f, rng, index)
        if shape == SHAPE_CYLINDER:
            return self._sample_cylinder(inner, outer, f, rng, index)
        # Point（3）及未知值退化为偏移处的一个点。该值为 bug 值，只需确定的退化行为
        return inner.copy()

    def _sample_box(self, inner, outer, f, rng, index):
        """在中空盒子内采样：位于外盒内且不在内盒内；尺寸=0 时退化为盒子表面。"""
        div_n = f.i("rangeDivideVerticalNum")
        for _ in range(_BOX_TRIES):
            v = Vec3((rng.random() * 2.0 - 1.0) * outer.x,
                     (rng.random() * 2.0 - 1.0) * outer.y,
                     (rng.random() * 2.0 - 1.0) * outer.z)
            if (abs(v.x) >= inner.x or abs(v.y) >= inner.y or abs(v.z) >= inner.z):
                break
        if div_n > 1:
            # 绕竖轴（Y）按出生序号分配到等分扇区，半径与高度不变
            r = math.hypot(v.x, v.z)
            a = slice_fraction(index, div_n) * 2.0 * math.pi
            v = Vec3(math.cos(a) * r, v.y, math.sin(a) * r)
        return v

    def _sample_sphere(self, inner, outer, f, rng, index):
        # 方位角：由横向扫描角度限定范围，按纵向等分数与出生序号分配扇区
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideVerticalNum"), index=index)
        # 极角：横向等分数对应圆锥面数，同样按出生序号分配
        pt = rng.random() * 2.0 - 1.0
        h_div = f.i("rangeDivideHorizontalNum")
        if h_div > 1:
            pt = slice_fraction(index, h_div) * 2.0 - 1.0
        # 纵向扫描角度：0=全方向、180=一半、360=不生成，保留的极角范围为 1 - v/360
        v_sweep = f.get("scanAngleVertical", 0.0)
        if v_sweep > 0.0:
            pt *= max(0.0, 1.0 - min(1.0, v_sweep / 360.0))
        d = unit_from_spherical(az, pt)
        t = self._shell_fraction(rng)
        return Vec3(d.x * _lerp(inner.x, outer.x, t),
                    d.y * _lerp(inner.y, outer.y, t),
                    d.z * _lerp(inner.z, outer.z, t))

    def _sample_cylinder(self, inner, outer, f, rng, index):
        # 方位角：由横向扫描角度限定范围，按纵向等分数与出生序号分配扇区
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideVerticalNum"), index=index)
        a = az * 2.0 * math.pi
        # 高度：横向等分数对应沿高度的水平切片，同样按出生序号分配。
        # 高度为**单向**，y ∈ [偏移, 偏移+尺寸]，见模块 docstring
        h_t = rng.random()
        h_div = f.i("rangeDivideHorizontalNum")
        if h_div > 1:
            h_t = slice_fraction(index, h_div)
        size_y = max(0.0, outer.y - inner.y)
        y = inner.y + h_t * size_y
        # 半径：内径为偏移、厚度为尺寸的圆环，再乘以沿高度插值的锥度（起始／结束半径）
        t = self._shell_fraction(rng)
        taper = _lerp(f.get("radiusOrigin", 1.0), f.get("radiusEnd", 1.0),
                      (h_t + 0.0))
        return Vec3(math.cos(a) * _lerp(inner.x, outer.x, t) * taper,
                    y,
                    math.sin(a) * _lerp(inner.z, outer.z, t) * taper)

    @staticmethod
    def _shell_fraction(rng):
        """返回内边界到外边界之间的插值比例；尺寸=0 时内外重合，退化为表面。"""
        return rng.random()

    # ── 轮廓（用于预览线框）───────────────────────────────────────────────
    def outline(self, em, segments=28):
        """返回生成区域的线框：**成对**的点（p0,p1, p0,p1, …），与粒子处于同一坐标空间。

        `segments` 为圆与环的分段数，只影响线框精度。
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
# 线框构造（纯几何计算，不使用随机数）
# ─────────────────────────────────────────────────────────────────────────────

#: 立方体 12 条棱的顶点对，下标指向 8 个角
_BOX_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0),
              (4, 5), (5, 7), (7, 6), (6, 4),
              (0, 4), (1, 5), (2, 6), (3, 7))


def _box_corners(h):
    return [Vec3(x * h.x, y * h.y, z * h.z)
            for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]


def _hollow(inner):
    return bool(inner.x or inner.y or inner.z)


def _box_lines(inner, outer):
    """返回外盒 12 条棱；中空时再加内盒 12 条棱与 8 条径向棱。"""
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
    """返回绕竖轴的一段水平弧（或整圈）上的点列；`elev` 为仰角的正弦值。"""
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
        out[-1] = out[0]        # 闭合
    return out


def _strip(pts):
    """将点列转换为首尾相接的线段对。"""
    out = []
    for i in range(len(pts) - 1):
        out.append(pts[i])
        out.append(pts[i + 1])
    return out


def _azimuths(h_frac, full=4, swept=3):
    """返回绘制经线与竖棱的方位角列表。

    扫描不满一整圈时**必须包含两个端点**，两端的经线与径向棱构成截面的边界。
    """
    if h_frac >= 0.999:
        return [2.0 * math.pi * (k / float(full)) for k in range(full)]
    span = 2.0 * math.pi * h_frac
    return [span * (k / float(swept - 1)) for k in range(swept)]


def _sphere_lines(inner, outer, f, n):
    """返回球壳线框：内外两层的赤道与纬线环、经线，以及连接两层的径向棱。"""
    h_frac = max(0.0, min(1.0, (f.get("scanAngleHorizontal", 360.0) or 360.0) / 360.0))
    v_keep = max(0.0, 1.0 - min(1.0, (f.get("scanAngleVertical", 0.0) or 0.0) / 360.0))
    hollow = _hollow(inner)
    shells = [outer] + ([inner] if hollow else [])
    azs = _azimuths(h_frac)
    # 极角方向取中间与两端三处；纵向扫描使两端从极点向内收缩
    elevs = [0.0] if v_keep <= 0.0 else [-v_keep, 0.0, v_keep]

    out = []
    for r in shells:
        for ev in elevs:
            if abs(abs(ev) - 1.0) < 1e-6:
                continue                    # 极点处的环退化为一个点
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
    """返回圆柱／圆台壳线框：上下底的内外环、竖棱，以及连接内外的径向棱。

    底面使用起始半径、顶面使用结束半径，与 `_sample_cylinder` 中 `h_t=0` 对应 `y_lo` 一致。
    """
    h_frac = max(0.0, min(1.0, (f.get("scanAngleHorizontal", 360.0) or 360.0) / 360.0))
    r0 = f.get("radiusOrigin", 1.0)
    r1 = f.get("radiusEnd", 1.0)
    size_y = max(0.0, outer.y - inner.y)
    y_lo, y_hi = inner.y, inner.y + size_y      # 单向：底面位于偏移处，向 +Y 延伸
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

    if hollow:                              # 径向棱：上下底各一组
        for a in azs:
            out.append(at(inner, r0, y_lo, a))
            out.append(at(outer, r0, y_lo, a))
            out.append(at(inner, r1, y_hi, a))
            out.append(at(outer, r1, y_hi, a))
    return out


def _point_lines(at):
    d = 5.0     # 游戏单位，仅用于显示
    return [Vec3(at.x - d, at.y, at.z), Vec3(at.x + d, at.y, at.z),
            Vec3(at.x, at.y - d, at.z), Vec3(at.x, at.y + d, at.z),
            Vec3(at.x, at.y, at.z - d), Vec3(at.x, at.y, at.z + d)]
