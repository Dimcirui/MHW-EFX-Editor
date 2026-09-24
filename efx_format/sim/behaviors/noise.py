# -*- coding: utf-8 -*-
"""NOISE —— 以双重正弦振荡器为粒子的位置与运动附加摇曳。

NOISE 与 BLINK 共用同一组字段与同一个振荡器：Low / High 两重，各有一个频率与一个振幅
（Width）。NOISE 的输出作用于位置，BLINK 的输出作用于 alpha。

每一重在粒子出生时抽取一个随机平面（正交基 e1、e2），在该平面内按

    offset_k(t) = Width_k · (cos(ω_k·t)·e1 + sin(ω_k·t)·e2)

做匀速圆周运动，两重相加即为总偏移。两重的角速度与半径通常不同，叠加后为准周期轨迹。
ω 由 `_common.oscillator_omega` 将频率（每秒周期数）换算，t 为粒子年龄（帧）。

偏移以**增量**叠加到位置上：每帧只施加本帧与上一帧偏移之差。因此摇曳附加在 VELOCITY3D、
PARENTOPTIONS 等其它运动之上，而非取代它们；条带类渲染体的轴向随之向摇曳方向倾斜。出生时
施加 t=0 的偏移，即生成位置本身也带有摇曳。

字段职能：

    lowFrequency / highFrequency            两重各自的频率，每秒周期数
    lowFrequencyWidth / highFrequencyWidth  两重各自的振幅（圆周半径），游戏单位
    各字段的 Jitter                         仅在粒子出生时抽取一次
    typeFlag                                35 种取值均未观察到影响，不读取

维护约束：
- 必须按增量施加偏移，不得以「生成点 + 偏移」覆写 `p.pos`：覆写会抹去同一粒子上其它属性对
  位置的贡献。
- 两重在出生时必须消耗相同数量的随机数，与振幅是否为 0 无关；否则一重的取值会改变另一重
  抽到的平面。
"""

import math

from ...hashes import NOISE
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import CONSTRAIN
from ..state import Vec3
from ._common import oscillator_omega


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


def _offset(groups, t):
    """返回年龄为 `t` 帧时两重振荡的总偏移。"""
    out = Vec3()
    for g in groups:
        if not g["width"]:
            continue
        a = g["omega"] * t
        out = out + g["e1"] * (g["width"] * math.cos(a)) + g["e2"] * (g["width"] * math.sin(a))
    return out


@register(NOISE)
class Noise(Behavior):
    """CONSTRAIN 阶段将两重圆周振荡的偏移增量叠加到 p.pos。"""

    STAGE = CONSTRAIN
    #: 排在 PARENTOPTIONS 之后：跟随发射器的位移先施加，摇曳再叠加其上。
    ORDER = 20

    def on_particle_spawn(self, p, em, rng):
        f = em.f(NOISE, p)
        if f is None:
            return
        cfg = em.config
        groups = []
        for prefix in ("low", "high"):
            freq = jitter(f.get(prefix + "Frequency"),
                          f.get(prefix + "FrequencyJitter"), rng)
            width = jitter(f.get(prefix + "FrequencyWidth"),
                           f.get(prefix + "FrequencyWidthJitter"), rng)
            axis = _random_unit(rng)
            e1 = _random_perp(axis, rng)
            groups.append({
                "e1": e1, "e2": axis.cross(e1),
                "width": width, "omega": oscillator_omega(cfg, freq),
            })
        off = _offset(groups, 0)
        p.pos = p.pos + off
        p.user[Noise] = {"groups": groups, "t": 0, "last": off}

    def on_particle_step(self, p, em):
        st = p.user.get(Noise)
        if st is None:
            return
        st["t"] += 1
        off = _offset(st["groups"], st["t"])
        p.pos = p.pos + (off - st["last"])
        st["last"] = off
