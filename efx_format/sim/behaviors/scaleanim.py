# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/scaleanim.py  —  SCALEANIM（逐帧缩放动画）

两组独立的缩放，都是**加法累积 + 逐帧乘法衰减**：

  1. 整体（三轴同步）
        initialScaleSpeed(+Jitter)   每帧加到三个轴上的量
        initialScaleAccel(+Jitter)   该量每帧乘一次（annotations 原话：
                                     「逐帧速度倍率……1=匀速，<1 越来越慢」）
  2. 逐轴
        scaleSpeed{X,Y,Z}(+Jitter) / scaleAccel{X,Y,Z}(+Jitter)
        animUpdateStart(+Jitter)     逐轴那组延迟多少帧才开始

「加法」不是猜的：官方 TimelineParam 通道名是 **SizeScalarAdd / SizeXAdd /
SizeYAdd / SizeZAdd**（见 FIELD_TO_DT），Add 写在名字里。

模型：`p.scale` 是**倍率**，出生时 (1,1,1)，本 behavior 往上加。真实尺寸由渲染体
（BILLBOARD3D 的 width×scale 等）乘上它得到。

数量级自检（floating_particle_fire，实测值 iv=0.02 / ia=0.99 / 寿命 60 帧）：
    Σ 0.02·0.99ⁿ (n=0..59) ≈ 0.91  →  倍率 1.0 → 1.9，一生里长大一倍。
配上该原型 BILLBOARD3D 的 width=100 × scale=0.4 = 40 游戏单位（= 0.4 Blender 单位），
整条链算出来的尺寸是合理的——这是三个属性各自独立解出来的值凑在一起对上的，
不是调出来的。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import SCALEANIM
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import XFORM


@register(SCALEANIM)
class ScaleAnim(Behavior):
    """XFORM 阶段：写 p.scale。"""

    STAGE = XFORM
    ORDER = 100

    def on_particle_spawn(self, p, em, rng):
        f = em.f(SCALEANIM, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        uniform_v = jitter(f.get("initialScaleSpeed"), f.get("initialScaleSpeedJitter"),
                           rng, mode)
        uniform_a = jitter(f.get("initialScaleAccel", 1.0),
                           f.get("initialScaleAccelJitter"), rng, mode)

        axis_v = []
        axis_a = []
        for ax in ("X", "Y", "Z"):
            axis_v.append(jitter(f.get("scaleSpeed" + ax),
                                 f.get("scaleSpeed" + ax + "Jitter"), rng, mode))
            axis_a.append(jitter(f.get("scaleAccel" + ax, 1.0),
                                 f.get("scaleAccel" + ax + "Jitter"), rng, mode))

        delay = max(0, jitter_int(f.get("animUpdateStart"),
                                  f.get("animUpdateStartJitter"), rng, mode))

        p.user[ScaleAnim] = {
            "uv": uniform_v, "ua": uniform_a,
            "av": axis_v, "aa": axis_a,
            "delay": delay,
        }

    def on_particle_step(self, p, em):
        st = p.user.get(ScaleAnim)
        if st is None:
            return

        # ① 整体：三轴同步加同一个量
        uv = st["uv"]
        if uv:
            p.scale.x += uv
            p.scale.y += uv
            p.scale.z += uv
        st["uv"] = uv * st["ua"]

        # ② 逐轴：过了 animUpdateStart 才开始
        if p.age < st["delay"]:
            return
        av, aa = st["av"], st["aa"]
        if av[0]:
            p.scale.x += av[0]
        if av[1]:
            p.scale.y += av[1]
        if av[2]:
            p.scale.z += av[2]
        av[0] *= aa[0]
        av[1] *= aa[1]
        av[2] *= aa[2]
