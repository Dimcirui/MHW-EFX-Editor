# -*- coding: utf-8 -*-
"""UVCONTROL —— UV 的滚动与缩放。

公式必须与 `blender_efx/uvc_preview.py` 保持一致，否则同一特效在两个预览中的表现不同：

    位置   accel≈1  → pos = init + speed·t
           accel≠1  → speed(τ) = speed·accel^τ，位移 = speed·(accel^t − 1)/ln(accel)
    缩放   scale + scale_speed·t

`accel` 为每秒作用于速度的乘法倍率。四元组字段（`('f', 4)`）的布局为 **[U值, ?, V值, ?]**：
U 位于 index 0，**V 位于 index 2**，index 1 / 3 恒为 0。若以 index 1 作为 V，V 方向会退化为
条纹。

uv1 与 uv2 两套通道共用同一批贴图，布局相同，启用开关分别为 `uv1_unknFlag` 与 `uv2_enable`
（字段名不对称）。两套同时启用时叠加：**偏移相加，缩放相乘**；均未启用时按 uv1 的静态值处理。
时间基准由 `SimConfig.uvc_clock` 决定，默认取粒子自身的年龄。

输出 `item.extra["uv_xform"] = (su, sv, ou, ov)`，由 glue 变换顶点 UV：
`uv' = uv × (su, sv) + (ou, ov)`。没有贴图的渲染路径不含 UV，本属性在这些路径上不生效。
flowmap 字段不参与计算，预览中没有流动贴图的对应实现。
"""

import math

from ...hashes import UVCONTROL
from ..registry import Behavior, register
from ..stages import RENDER_MOD


def _comp(vec, i, default=0.0):
    try:
        return float(vec[i])
    except (TypeError, IndexError, ValueError):
        return default


def _advance(init, speed, accel, t):
    """返回 `t` 秒时的偏移量；accel 不大于 0 或接近 1 时按匀速计算。"""
    if accel is None or accel <= 0.0 or abs(accel - 1.0) < 1e-6:
        return init + speed * t
    try:
        return init + speed * (accel ** t - 1.0) / math.log(accel)
    except (OverflowError, ValueError):
        return init + speed * t


@register(UVCONTROL)
class UVControl(Behavior):
    """RENDER_MOD 阶段计算 UV 的缩放与偏移并写入渲染项，实际变换由 glue 完成。"""

    STAGE = RENDER_MOD
    ORDER = 55          # 必须排在 UVSEQUENCE 之后：先确定使用哪一格，再在该格内滚动

    def on_particle_spawn(self, p, em, rng):
        f = em.f(UVCONTROL, p)
        if f is None:
            return
        uv1_on = bool(f.i("uv1_unknFlag"))
        uv2_on = bool(f.i("uv2_enable"))
        names = []
        if uv1_on:
            names.append("uv1")
        if uv2_on:
            names.append("uv2")
        if not names:
            names.append("uv1")         # 均未启用时按 uv1 的静态值
        chans = []
        for pre in names:
            chans.append((f.raw(pre + "_offset"), f.raw(pre + "_offsetAdd"),
                          f.raw(pre + "_offsetCoef"), f.raw(pre + "_scale"),
                          f.raw(pre + "_scaleAdd")))
        p.rolled["uvc"] = chans

    def build_render(self, p, em, view, item):
        chans = p.rolled.get("uvc")
        if item is None or item.kind == "NONE" or not chans:
            return item
        cfg = em.config
        fps = float(getattr(cfg, "fps", 60) or 60)
        frames = (em.frame if getattr(cfg, "uvc_clock", "particle_age") == "emitter_frame"
                  else p.age)
        t = max(0.0, frames / fps)

        ou = ov = 0.0
        su = sv = 1.0
        for init, speed, accel, scale, sspeed in chans:
            ou += _advance(_comp(init, 0), _comp(speed, 0), _comp(accel, 0, 1.0), t)
            ov += _advance(_comp(init, 2), _comp(speed, 2), _comp(accel, 2, 1.0), t)
            su *= _comp(scale, 0, 1.0) + _comp(sspeed, 0) * t
            sv *= _comp(scale, 2, 1.0) + _comp(sspeed, 2) * t

        if su == 1.0 and sv == 1.0 and ou == 0.0 and ov == 0.0:
            return item                 # 中性值不写入，glue 无需逐顶点计算
        item.extra["uv_xform"] = (su, sv, ou, ov)
        return item
