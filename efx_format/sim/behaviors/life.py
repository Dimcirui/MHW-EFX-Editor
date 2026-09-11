# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/life.py  —  LIFE（寿命与淡入淡出）

字段（efx_format/schema/attributes.py）：
    fadeInDuration(+Jitter) / duration(+Jitter) / fadeOutDuration(+Jitter)
    timeToDeath(+Jitter) / indefiniteLifespan
    unknFrame(+Jitter) —— schema 注释写明「"Frame" 只是命名占位，不代表已确认是帧数」，
                          这里不使用。

待标定（SimConfig.life_model）
-----------------------------
总寿命 = fadeIn + duration + fadeOut（'sum'，默认），还是 duration 本身就是总长、
淡入淡出包含在内（'duration'）？语料里 fadeIn/fadeOut 多为 0，两种算法给出相同
结果，区分不开——等有一个 fadeIn≠0 的样本实机对拍即可定。

`timeToDeath` 语义未确认（名字像「死亡时间」，但和 duration 的关系不明），
当前**不参与**寿命计算，只在非 0 时记一条 note 提醒预览不完整。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import LIFE
from ..registry import Behavior, register
from ..rng import jitter_int
from ..stages import SHADE


@register(LIFE)
class Life(Behavior):
    """写 alpha（SHADE 阶段），并负责把粒子标成死亡。"""

    STAGE = SHADE
    ORDER = 10      # 淡入淡出是基准 alpha，别的调制（BLINK 等）排在后面

    def on_particle_spawn(self, p, em, rng):
        f = em.f(LIFE, p)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode

        fade_in = max(0, jitter_int(f.get("fadeInDuration"), f.get("fadeInDurationJitter"),
                                    rng, mode))
        duration = max(0, jitter_int(f.get("duration"), f.get("durationJitter"),
                                     rng, mode))
        fade_out = max(0, jitter_int(f.get("fadeOutDuration"), f.get("fadeOutDurationJitter"),
                                     rng, mode))

        if cfg.life_model == "duration":
            total = duration
            # 淡出段贴着总长的尾巴
            fade_out = min(fade_out, max(0, total - fade_in))
        else:                                    # 'sum'（默认）
            total = fade_in + duration + fade_out

        p.rolled["life_fade_in"] = fade_in
        p.rolled["life_fade_out"] = fade_out
        p.rolled["life_total"] = total
        p.life = total

        if f.i("indefiniteLifespan"):
            p.rolled["life_indefinite"] = True
            p.life = 0                            # 0 = 不按寿命判死

        if f.i("timeToDeath"):
            em.note("LIFE.timeToDeath 非 0，语义未确认，未参与寿命计算")

    def on_particle_step(self, p, em):
        indefinite = p.rolled.get("life_indefinite", False)
        total = p.rolled.get("life_total", 0)
        fade_in = p.rolled.get("life_fade_in", 0)
        fade_out = p.rolled.get("life_fade_out", 0)

        if not indefinite and total > 0 and p.age >= total:
            p.alive = False
            p.alpha = 0.0
            return

        a = 1.0
        if fade_in > 0 and p.age < fade_in:
            a = float(p.age) / float(fade_in)
        elif not indefinite and fade_out > 0:
            fade_start = total - fade_out
            if p.age >= fade_start:
                remain = total - p.age
                a = max(0.0, float(remain) / float(fade_out))
        p.alpha = a
