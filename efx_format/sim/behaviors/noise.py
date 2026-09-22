# -*- coding: utf-8 -*-
"""NOISE —— 绕生成点的两组匀速圆周运动叠加。

NOISE 为粒子叠加两组相互独立的匀速圆周运动。两组圆心均固定于**粒子的生成点**（spawn 时
`p.pos` 的绝对值，此后不随发射器或其它运动更新），旋转平面的朝向随机，由两组各自在出生时抽取。
两组的角速度与半径通常不同，叠加后呈准周期轨迹；noise 的视觉效果来自这一叠加，而非伪随机扰动。

字段职能：

    lowFrequency / highFrequency            两组各自的角速度，单位度/秒
    lowFrequencyWidth / highFrequencyWidth  两组各自的圆周半径，而非瞬移距离
    各字段的 Jitter                         仅在粒子出生时抽取一次
    typeFlag                                35 种取值均未观察到影响，不读取

维护约束：
- 位置在 CONSTRAIN 阶段直接覆写，而非写入切向速度后由 VELOCITY3D 积分：圆心固定、角速度恒定，
  存在精确闭式解，直接覆写不会产生离散积分导致的半径漂移。
- 直接覆写意味着 NOISE 独占位置，同一粒子上 VELOCITY3D / HOMING / PARENTOPTIONS 对位置的贡献
  将被覆盖。目前没有同时启用这些属性的实机样本可供对照，本实现按 NOISE 独占位置处理。
"""

import math

from ...hashes import NOISE
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import CONSTRAIN
from ..state import Vec3


def _random_unit(rng):
    """球面上均匀随机的单位向量。"""
    z = rng.uniform(-1.0, 1.0)
    a = rng.uniform(0.0, 2.0 * math.pi)
    r = math.sqrt(max(0.0, 1.0 - z * z))
    return Vec3(math.cos(a) * r, z, math.sin(a) * r)


def _fallback_perp(axis):
    ref = Vec3(0.0, 1.0, 0.0)
    if abs(axis.dot(ref)) > 0.99:
        ref = Vec3(1.0, 0.0, 0.0)
    return ref.cross(axis).normalized(fallback=Vec3(1.0, 0.0, 0.0))


def _random_perp(axis, rng):
    """返回 `axis` 垂面内随机方向的单位向量，用作圆周运动的起始半径方向。"""
    ref = _random_unit(rng)
    e1 = ref - axis * axis.dot(ref)
    return e1.normalized(fallback=_fallback_perp(axis))


@register(NOISE)
class Noise(Behavior):
    """CONSTRAIN 阶段叠加两组随机取向的匀速圆周运动，并直接覆写 p.pos。"""

    STAGE = CONSTRAIN
    #: 必须排在 PARENTOPTIONS 之后：跟随发射器只提供基准位置，约束类属性在其后覆写。
    ORDER = 20

    def on_particle_spawn(self, p, em, rng):
        f = em.f(NOISE, p)
        if f is None:
            return
        mode = em.config.jitter_mode
        groups = []
        for prefix in ("low", "high"):
            speed = jitter(f.get(prefix + "Frequency"),
                           f.get(prefix + "FrequencyJitter"), rng, mode)
            radius = jitter(f.get(prefix + "FrequencyWidth"),
                            f.get(prefix + "FrequencyWidthJitter"), rng, mode)
            axis = _random_unit(rng)
            e1 = _random_perp(axis, rng)
            e2 = axis.cross(e1)
            groups.append({
                "e1": e1, "e2": e2,
                "radius": radius, "speed": speed, "theta": 0.0,
            })
        p.user[Noise] = {"center": p.pos.copy(), "groups": groups}

    def on_particle_step(self, p, em):
        st = p.user.get(Noise)
        if st is None:
            return
        fps = max(1, em.config.fps)
        offset = Vec3()
        for g in st["groups"]:
            g["theta"] += math.radians(g["speed"]) / fps
            c, s = math.cos(g["theta"]), math.sin(g["theta"])
            offset = offset + g["e1"] * (g["radius"] * c) + g["e2"] * (g["radius"] * s)
        p.pos = st["center"] + offset
