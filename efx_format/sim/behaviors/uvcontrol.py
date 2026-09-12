# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/uvcontrol.py  —  UVCONTROL（UV 滚动 / 缩放）

公式与 `blender_efx/uvc_preview.py` **同一套**（那边是实测标定过的，两边保持一致，
省得同一个特效在两个预览里对不上）：

    位置   accel≈1  → pos = init + speed·t
           accel≠1  → speed(τ)=speed·accel^τ，位移 = speed·(accel^t − 1)/ln(accel)
    缩放   scale + scale_speed·t

⚠ `('f', 4)` 的布局是 **[U值, ?, V值, ?]** —— U 在 index 0、**V 在 index 2**
（index 1/3 实测恒为 0，疑似 jitter/保留）。实证：`uv1_scale=(4,0,4,0)` 是 U/V 各 4 倍、
`uv1_offset=(0,0,0.6,0)` 是 V 偏移 0.6。早期误读 index 1 会让 V 方向塌成条纹。

两套通道
--------
逐通道开关：uv1 看 `uv1_unknFlag`、uv2 看 `uv2_enable`（字段名不对称是历史原因）。
两套共用同一批贴图、布局一致，同时启用就叠加：**偏移相加、缩放相乘**。都不启用时
按 uv1 的静态值处理。

时间基准：`SimConfig.uvc_clock`，默认按**粒子自己的年龄**数（与 UVSEQUENCE 一致）。

输出 `item.extra["uv_xform"] = (su, sv, ou, ov)`，由 glue 变换顶点 UV：
`uv' = uv × (su, sv) + (ou, ov)`。没有贴图的渲染路径拿不到 UV，那里这一块不生效。

未参与：flowmap 八件套（需要一张额外的流动贴图，预览里没有对应概念）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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
    """位置随时间演化。accel 是「每秒对速度做乘法」的倍率（annotations 原话）。"""
    if accel is None or accel <= 0.0 or abs(accel - 1.0) < 1e-6:
        return init + speed * t
    try:
        return init + speed * (accel ** t - 1.0) / math.log(accel)
    except (OverflowError, ValueError):
        return init + speed * t


@register(UVCONTROL)
class UVControl(Behavior):
    """RENDER_MOD：算出 UV 的缩放/偏移挂到渲染项上，实际变换由 glue 做。"""

    STAGE = RENDER_MOD
    ORDER = 55          # UVSEQUENCE(50) 之后：先定用哪一格，再在那一格里滚

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
            names.append("uv1")         # 都不启用 → 按 uv1 的静态值
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
            return item                 # 中性 → 不挂，glue 就不必逐顶点算一遍
        item.extra["uv_xform"] = (su, sv, ou, ov)
        return item
