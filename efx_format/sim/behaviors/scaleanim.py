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

加在**谁**身上：各自对应的那个尺寸字段
--------------------------------------
用户在 test.efx（BILLBOARD3D `scale`=30、`width`=`height`=1）上的计时，三条都对上
「每帧加、加在同名的那个尺寸字段上」：

    scaleSpeedX      = -0.1   →  10 帧缩没   （width 1 → 0，0.1/帧）
    scaleSpeedX      = -0.01  → 100 帧缩没   （同上，0.01/帧）
    initialScaleSpeed= -0.1   → 300 帧缩没   （**scale 30 → 0**，0.1/帧）

也就是 SizeScalarAdd 加的是 `scale` 那个总倍率字段（这里 30），SizeXAdd 加的是
`width`（这里 1）——同样是 -0.1，前者要走 30 倍长的路，所以慢 30 倍。这解释了
为什么两组速度「量级差很远」。

`SimConfig.scaleanim_add_target`：'size'=按上面这套加在尺寸字段上（默认）；
'multiplier'=改动前的行为（都加进一个从 1 起的归一化倍率 `p.scale`）。
⚠ 目前只有 BILLBOARD3D 走 'size' 这条路（实测数据只覆盖了它）；PLANE/MESH/RIBBON
仍读 `p.scale`，两条路都会写，切换开关不影响它们。

数量级自检（floating_particle_fire，实测值 iv=0.02 / ia=0.99 / 寿命 60 帧）：
    Σ 0.02·0.99ⁿ (n=0..59) ≈ 0.91  →  scale 0.4 → 1.31，一生里长大三倍。

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
        # 绝对加量：渲染体拿它直接加到自己的尺寸字段上（见模块 docstring）
        p.rolled["sa_scalar"] = 0.0
        p.rolled["sa_axis"] = [0.0, 0.0, 0.0]

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
            p.rolled["sa_scalar"] += uv
        st["uv"] = uv * st["ua"]

        # ② 逐轴：过了 animUpdateStart 才开始
        if p.age < st["delay"]:
            return
        av, aa = st["av"], st["aa"]
        ax = p.rolled["sa_axis"]
        if av[0]:
            p.scale.x += av[0]
            ax[0] += av[0]
        if av[1]:
            p.scale.y += av[1]
            ax[1] += av[1]
        if av[2]:
            p.scale.z += av[2]
            ax[2] += av[2]
        av[0] *= aa[0]
        av[1] *= aa[1]
        av[2] *= aa[2]
