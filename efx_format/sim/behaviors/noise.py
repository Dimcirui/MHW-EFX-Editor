# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/noise.py  —  NOISE（噪声：绕生成点的双组匀速圆周运动）

2026-09-17 用户实机描述定案：
    · `typeFlag`（35 种取值）对表现**没有任何观测到的影响**，本 behavior 不读它。
    · `lowFrequencyWidth`/`highFrequencyWidth`（原 teleport_radius/teleport_radius2）
      是圆周运动的**半径**，不是真的瞬移。
    · 效果是给粒子叠加**两组独立的匀速圆周运动**，每组的圆心都固定在**粒子的
      生成点**（`p.pos` 在 spawn 那一刻的绝对值，出生之后不再跟随发射器/其它
      运动重新定位），旋转平面朝向随机、每组各自独立抽一次。
    · 两组转速/半径通常不同，叠加起来肉眼就看不出规律的圆周运动，这就是「noise」
      的观感来源——不是伪随机抖动，是两个频率不同的圆叠加出的准周期轨迹。

2026-09-19 devlecture 确认官方字段名是 `low/highFrequency`(+`Width`)，跟 BLINK
共用同一套双重 sin 命名（BLINK 作用于 alpha，NOISE 作用于位置/运动）。

`low/highFrequency` 按本仓库既有惯例（HOMING.turnRate、ROTATEANIM.spin_velocity）
当角速度读，单位度/秒；`Jitter` 一律走 `rng.jitter`，逐粒子只抽一次。

因为圆心是绝对定住的生成点、半径匀速转动是精确闭式解，直接覆写 `p.pos`
（CONSTRAIN 阶段）比「写一个近似的切向速度再靠 VELOCITY3D 积分」更准，不会有
离散积分带来的半径漂移。代价是它会覆盖掉同一粒子上其它运动（VELOCITY3D/
HOMING/PARENTOPTIONS 的跟随）对位置的贡献——目前没有同时开 NOISE 与它们的
实机样本可对照，先按“NOISE 独占位置”实现，等有反例再改。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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
    """`axis` 垂面内一个随机方向的单位向量（当圆周运动的起始半径方向用）。"""
    ref = _random_unit(rng)
    e1 = ref - axis * axis.dot(ref)
    return e1.normalized(fallback=_fallback_perp(axis))


@register(NOISE)
class Noise(Behavior):
    """CONSTRAIN 阶段：两组各自随机取向的匀速圆周运动叠加，直接覆写 p.pos。"""

    STAGE = CONSTRAIN
    #: 排在 PARENTOPTIONS(10) 之后：跟随发射器只是给个基准位置，真正的约束类
    #: （PATHCHAIN/REPEATAREA/碰撞/这里）再覆写它。
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
