# -*- coding: utf-8 -*-
"""BLINK —— 以双重正弦振荡器调制粒子的 alpha。

BLINK 与 NOISE 共用同一组振荡器字段（Low / High 两重，各有一个频率与一个振幅），输出作用于
alpha，并钳制在 MinRate ~ MaxRate 之间：

    raw(t)  = lowFrequencyWidth  · sin(ω_low  · t + φ0)
            + highFrequencyWidth · sin(ω_high · t + φ1)
    rate(t) = clamp(raw(t), minRate, maxRate)
    alpha  *= rate(t)

ω 由 `_common.oscillator_omega` 按 `SimConfig.oscillator_freq_unit` 换算，t 为粒子年龄（帧）。
初相位 φ0、φ1 由 `SimConfig.blink_phase` 决定。

字段职能：

    minRate / maxRate                       alpha 系数的下限与上限，默认 0 ~ 1
    lowFrequency / highFrequency            两重各自的频率
    lowFrequencyWidth / highFrequencyWidth  两重各自的振幅，alpha 量级
    各字段的 Jitter                         仅在粒子出生时抽取一次
    typeFlag / unkn1_0                      语义未知，不读取

维护约束：
- 必须排在 LIFE 之后：LIFE 写入基准 alpha，BLINK 在其上相乘。
- 不得对同一基准 alpha 逐帧累乘。未被其它属性重写时，本 behavior 以上一帧记录的基准值
  重新计算，而不是在已乘过的结果上再乘一次。
"""

import math

from ...hashes import BLINK
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import SHADE
from ._common import oscillator_omega


@register(BLINK)
class Blink(Behavior):
    """SHADE 阶段将振荡器输出钳制后乘入 p.alpha。"""

    STAGE = SHADE
    ORDER = 20      # 必须排在 LIFE（10）之后、RGBWATER（61）之前

    def on_particle_spawn(self, p, em, rng):
        f = em.f(BLINK, p)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode
        random_phase = getattr(cfg, "blink_phase", "zero") == "random"
        groups = []
        for prefix in ("low", "high"):
            freq = jitter(f.get(prefix + "Frequency"),
                          f.get(prefix + "FrequencyJitter"), rng, mode)
            width = jitter(f.get(prefix + "FrequencyWidth"),
                           f.get(prefix + "FrequencyWidthJitter"), rng, mode)
            # 相位无论是否启用都抽取，使两种模式消耗的随机数数量一致
            phase = rng.uniform(0.0, 2.0 * math.pi)
            groups.append((oscillator_omega(cfg, freq), width,
                           phase if random_phase else 0.0))
        lo = float(f.get("minRate", 0.0))
        hi = float(f.get("maxRate", 1.0))
        if lo > hi:
            lo, hi = hi, lo
        p.user[Blink] = {"groups": groups, "lo": lo, "hi": hi,
                         "base": None, "written": None}

    def on_particle_step(self, p, em):
        st = p.user.get(Blink)
        if st is None:
            return
        raw = 0.0
        for omega, width, phase in st["groups"]:
            if width:
                raw += width * math.sin(omega * p.age + phase)
        rate = min(st["hi"], max(st["lo"], raw))

        # 其它属性（通常是 LIFE）本帧已重写 alpha 时以新值为基准；否则沿用上一帧的基准，
        # 避免逐帧累乘
        if st["written"] is not None and p.alpha == st["written"]:
            base = st["base"]
        else:
            base = p.alpha
        out = base * rate
        st["base"] = base
        st["written"] = out
        p.alpha = out
