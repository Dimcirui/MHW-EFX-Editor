# -*- coding: utf-8 -*-
"""LIFE —— 粒子寿命与淡入淡出。

字段职能：

    fadeInDuration / duration / fadeOutDuration  三段时长，各带一个 Jitter
    timeToDeath                                  语义未确认，不参与寿命计算
    indefiniteLifespan                           置位时不按寿命判定死亡
    unknFrame                                    名称中的 Frame 仅为占位，不使用

总寿命为 fadeIn + duration + fadeOut。

维护约束：
- `indefiniteLifespan` 以 `p.life = 0` 实现，其含义是不按寿命判定死亡，而非寿命为零。
"""

from ...hashes import LIFE
from ..registry import Behavior, register
from ..rng import jitter_int
from ..stages import SHADE


@register(LIFE)
class Life(Behavior):
    """SHADE 阶段写入 alpha，并负责将粒子标记为死亡。"""

    STAGE = SHADE
    ORDER = 10      # 淡入淡出是基准 alpha，其它 alpha 调制必须排在其后

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

        total = fade_in + duration + fade_out

        p.rolled["life_fade_in"] = fade_in
        p.rolled["life_fade_out"] = fade_out
        p.rolled["life_total"] = total
        p.life = total

        if f.i("indefiniteLifespan"):
            p.rolled["life_indefinite"] = True
            p.life = 0

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
