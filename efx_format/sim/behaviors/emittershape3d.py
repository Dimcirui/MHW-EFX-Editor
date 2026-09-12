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
实际位置的偏移**」。这里实现为：横截面（XZ）是内径=偏移、厚度=尺寸的圆环，竖直方向
（Y）整体平移偏移量、半高取尺寸。**哪一个轴承担那次平移未经实测**，形态对不上时先
从这里查。

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
        # 高度：横向等分数量 = 沿高度的水平切片；圆柱在掏空之外还有一次位置偏移
        h_t = rng.random()
        h_div = f.i("rangeDivideHorizontalNum")
        if h_div > 1:
            h_t = quantize_angle(h_t, h_div)
        size_y = max(0.0, outer.y - inner.y)
        y = inner.y + (h_t * 2.0 - 1.0) * size_y
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
