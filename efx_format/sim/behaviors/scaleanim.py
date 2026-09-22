# -*- coding: utf-8 -*-
"""SCALEANIM —— 逐帧缩放动画。

两组相互独立的缩放，均为**加法累积 + 逐帧乘法衰减**：

    整体（三轴同步）  initialScaleSpeed(+Jitter)  每帧加到三个轴上的增量
                      initialScaleAccel(+Jitter)  该增量每帧乘以此值；1 为匀速，小于 1 逐渐减慢
    逐轴              scaleSpeed{X,Y,Z}(+Jitter) / scaleAccel{X,Y,Z}(+Jitter)
                      animUpdateStart(+Jitter)    逐轴一组的起始延迟帧数

缩放为加法而非乘法：官方 TimelineParam 的通道名为 SizeScalarAdd / SizeXAdd / SizeYAdd /
SizeZAdd。两组各自加在对应的尺寸字段上：SizeScalarAdd 作用于总倍率 `scale`，SizeXAdd 作用于
`width`。因此两组速度的量级差异很大：同样取 -0.1，前者需要把 `scale` 从 30 减到 0。

维护约束：
- 必须同时写入两种结果：`p.scale`（从 1 起的归一化倍率）与 `p.rolled["sa_scalar"]` /
  `["sa_axis"]`（绝对增量）。目前只有 BILLBOARD3D 按 `SimConfig.scaleanim_add_target='size'`
  读取绝对增量，PLANE / MESH / RIBBON 仍读取 `p.scale`，不受该开关影响。
"""

from ...hashes import SCALEANIM
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import XFORM


@register(SCALEANIM)
class ScaleAnim(Behavior):
    """XFORM 阶段写入 p.scale 与绝对增量。"""

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
        p.rolled["sa_scalar"] = 0.0
        p.rolled["sa_axis"] = [0.0, 0.0, 0.0]

    def on_particle_step(self, p, em):
        st = p.user.get(ScaleAnim)
        if st is None:
            return

        uv = st["uv"]
        if uv:
            p.scale.x += uv
            p.scale.y += uv
            p.scale.z += uv
            p.rolled["sa_scalar"] += uv
        st["uv"] = uv * st["ua"]

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
