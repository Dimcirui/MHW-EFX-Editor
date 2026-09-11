# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/emittershape3d.py  —  EMITTERSHAPE3D（生成位置）

字段来源：efx_format/schema/attributes.py + enums.py + blender_efx/annotations.py

    shapeType         0=Box 1=Sphere 2=Cylinder 3=Point   (ENUM_SHAPE_TYPE3D)
    rangeXYZ          FLOAT6 —— 见下
    localRotationX/Y/Z + rotationOrder                     (_TRANSFORM_ROT_ORDER)
    scanAngleHorizontal / scanAngleVertical                （角度制，360=整圈）
    rangeDivideHorizontalNum / rangeDivideVerticalNum      （**等分数量**，非生成个数）
    rangeDivideAxis   0=X 1=Z 2=Y，仅 Box 生效             (ENUM_RANGE_DIVIDE_AXIS)
    radiusOrigin / radiusEnd                                （半径比例区间）

rangeXYZ 是 Min/Max，不是 offset/size
-------------------------------------
证据是**官方 TimelineParam 通道名**：`FIELD_TO_DT[("EMITTERSHAPE3D","rangeXYZ")]`
挂着 6 条通道，逐轴交错——

    RangeMinX / RangeMaxX / RangeMinY / RangeMaxY / RangeMinZ / RangeMaxZ

配上 FLOAT6 的字节布局（codec._XYZ_FMT[0] = `a_x b_x a_y b_y a_z b_z`），即

    idx 0/2/4 = Min X/Y/Z      idx 1/3/5 = Max X/Y/Z

以 floating_particle_fire 为例，rangeXYZ = [0, 150, 0, 0, 0, 30] → X∈[0,150]、
Y∈[0,0]、Z∈[0,30]：一个从原点朝 +X/+Z 铺开的扁平区域。

  ⚠ 这跟仓库里另外两处读法都不同，三者只可能对一个：
     - blender_efx/es3d_preview.py `_read_range_xyz` 取 idx 0/2/4 当**尺寸**
       → 对这个原型会得到全 0 的退化盒子（预览里看不见东西）。
     - blender_efx/timl_tracks.py 的注释写这一对是「offset/size」
       → 只有 Min 恒为 0 时才和 Min/Max 等价。
    本模块按通道名走 Min/Max，并留了 `SimConfig.es3d_range_mode` 开关可切回
    offset/size 读法，等实机确认后三处统一。

几何模型
--------
先把 rangeXYZ 化成「中心 + 半轴」的轴对齐包围盒，三种形状都内接于它：
    center = (min + max) / 2      half = (max - min) / 2
这样 Box 退化成逐轴 uniform(min, max)，Sphere/Cylinder 自动变成椭球/椭柱，
Min 恒为 0 的常见情形下也和直觉一致。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

import math

from ...hashes import EMITTERSHAPE3D
from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3
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

        center, half = self._region(f, cfg)
        shape = f.i("shapeType")
        local = center + self._sample(shape, half, f, rng)

        # 局部旋转（rangeDivideAxis 不受它影响——annotations 里写明了）
        rot_order = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)
        local = rotate_euler(local,
                             f.get("localRotationX"), f.get("localRotationY"),
                             f.get("localRotationZ"),
                             order=rot_order, applied=cfg.rot_order_applied)

        p.spawn_pos = local
        p.pos = em.origin + local

    # ── rangeXYZ → 中心 + 半轴 ────────────────────────────────────────────────
    @staticmethod
    def _region(f, cfg):
        lo = f.xyz_lo("rangeXYZ")
        hi = f.xyz_hi("rangeXYZ")
        if cfg.es3d_range_mode == "offset_size":
            # 备选读法：前一半是中心偏移，后一半是尺寸（对称展开）
            return lo, Vec3(hi.x * 0.5, hi.y * 0.5, hi.z * 0.5)
        # 'minmax'（默认，据官方通道名 RangeMin*/RangeMax*）
        center = Vec3((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, (lo.z + hi.z) * 0.5)
        half = Vec3((hi.x - lo.x) * 0.5, (hi.y - lo.y) * 0.5, (hi.z - lo.z) * 0.5)
        return center, half

    # ── 各形状在「半轴」包围盒内的采样 ───────────────────────────────────────
    def _sample(self, shape, half, f, rng):
        if shape == SHAPE_BOX:
            return self._sample_box(half, f, rng)
        if shape == SHAPE_SPHERE:
            return self._sample_sphere(half, f, rng)
        if shape == SHAPE_CYLINDER:
            return self._sample_cylinder(half, f, rng)
        return Vec3()          # Point 及未知值

    def _sample_box(self, half, f, rng):
        div_axis = _DIVIDE_AXIS.get(f.i("rangeDivideAxis"), "x")
        div_n = f.i("rangeDivideHorizontalNum")
        out = {}
        for axis in ("x", "y", "z"):
            t = rng.random()
            if axis == div_axis and div_n > 1:
                t = quantize_angle(t, div_n)
            out[axis] = (t * 2.0 - 1.0) * getattr(half, axis)
        return Vec3(out["x"], out["y"], out["z"])

    def _sample_sphere(self, half, f, rng):
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideHorizontalNum"))
        # scanAngleVertical：0 = 不限制（语料里绝大多数如此），非 0 则收窄极角带
        v_sweep = f.get("scanAngleVertical", 0.0)
        pt = rng.random() * 2.0 - 1.0
        v_div = f.i("rangeDivideVerticalNum")
        if v_div > 1:
            pt = quantize_angle((pt + 1.0) * 0.5, v_div) * 2.0 - 1.0
        if 0.0 < v_sweep < 360.0:
            pt *= max(0.0, min(1.0, v_sweep / 360.0))
        d = unit_from_spherical(az, pt)
        r = self._radius_fraction(f, rng)
        return Vec3(d.x * half.x, d.y * half.y, d.z * half.z) * r

    def _sample_cylinder(self, half, f, rng):
        az = sweep_fraction(rng, f.get("scanAngleHorizontal", 360.0),
                            f.i("rangeDivideHorizontalNum"))
        a = az * 2.0 * math.pi
        r = self._radius_fraction(f, rng)
        h_t = rng.random()
        h_div = f.i("rangeDivideVerticalNum")
        if h_div > 1:
            h_t = quantize_angle(h_t, h_div)
        return Vec3(math.cos(a) * half.x * r,
                    (h_t * 2.0 - 1.0) * half.y,
                    math.sin(a) * half.z * r)

    @staticmethod
    def _radius_fraction(f, rng):
        """radiusOrigin/radiusEnd 给出的半径比例。两者相等（语料常见 1.0/1.0）
        = 只在表面；不等则在壳层内均匀取。"""
        r0 = f.get("radiusOrigin", 1.0)
        r1 = f.get("radiusEnd", 1.0)
        if r0 == r1:
            return r0
        lo, hi = (r0, r1) if r0 <= r1 else (r1, r0)
        return rng.uniform(lo, hi)
