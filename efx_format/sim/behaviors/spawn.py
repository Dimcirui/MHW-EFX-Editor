# -*- coding: utf-8 -*-
"""SPAWN —— 发射节奏。

三层结构：SPAWN 属性 → 轮（一个发射器实例，连续发若干批）→ particle 个体。

字段职能：

    maxParticles                **同时存活**数量的软上限，而非总生成数
    spawnNum(+Jitter)           每批的粒子数，每批重新抽取
    loopNum(+Jitter)            每轮批次数，每轮重新抽取；0 = 这一轮不结束，一直发
    intervalFrame(+Jitter)      同一轮内的批间隔
    revivalLoop                 总轮数；1 = 不复活，0 = 无限。无 Jitter
    revivalInterval(+Jitter)    一轮最后一批之后到下一轮第一批的帧数，不等粒子消失
    emitterDelayFrame(+Jitter)  第一批之前的一次性延迟，复活时不再等
    particleDelayFrame(+Jitter) 唯一的 particle 层字段，逐粒子独立延迟

`spawnFrame`(+Jitter) 与 `spawnFlags` 的六个位（UseSpawnFrame / RingBufferMode /
RayCastHitOnly / RayCastDependency / InitializeFull / Interpolate）模拟层不读取。

维护约束：
- 复活开始新一轮时推进 `em.cycle`；换位置的实际偏移未模拟，只供其它 behavior 重新采样。
- `intervalFrame` 的抖动默认每批重新抽取（`SimConfig.spawn_interval_jitter='per_burst'`），
  与 `spawnNum` 的抽取方式一致；`per_cycle` 档则整轮等距。
- 发射器级的随机数（每批的数量与间隔）必须使用 `em` 自身的随机流，不得占用逐粒子的随机流。
"""

from ...hashes import SPAWN
from ..registry import Behavior, register
from ..rng import emitter_stream_rng, jitter_int
from ..stages import FORCE


@register(SPAWN)
class Spawn(Behavior):
    """只处理发射器时间轴，不参与逐粒子 step，因此 STAGE 的取值不影响结果。"""

    STAGE = FORCE
    ORDER = 0

    # ── 发射器 ───────────────────────────────────────────────────────────────
    def on_emitter_init(self, em, rng):
        f = em.f(SPAWN)
        if f is None:
            return
        srng = emitter_stream_rng(em.seed)
        st = {
            "rng": srng,
            "delay": jitter_int(f.get("emitterDelayFrame"),
                                f.get("emitterDelayFrameJitter"),
                                srng),
            "wait": 0,
            "bursts_left": None,     # None 表示本轮不结束，持续生成
            "burst_index": 0,
            "rounds_done": 0,
            "interval": 0,
            "done": False,           # 全部轮次发完后，该发射器停止发射
        }
        em.user[Spawn] = st
        self._begin_cycle(em, st)

    def _begin_cycle(self, em, st):
        """开始新一轮：重新抽取 loopNum 与本轮的批间隔。"""
        f = em.f(SPAWN)
        per_cycle = jitter_int(f.get("loopNum"), f.get("loopNumJitter"), st["rng"])
        st["bursts_left"] = per_cycle if per_cycle > 0 else None
        st["burst_index"] = 0
        self._roll_interval(em, st)

    def _roll_interval(self, em, st):
        """抽取一次批间隔；`per_burst` 下每批调用一次。"""
        f = em.f(SPAWN)
        v = jitter_int(f.get("intervalFrame"), f.get("intervalFrameJitter"), st["rng"])
        st["interval"] = max(0, v)
        return st["interval"]

    def _next_interval(self, em, st):
        if getattr(em.config, "spawn_interval_jitter", "per_burst") == "per_cycle":
            return st["interval"]
        return self._roll_interval(em, st)

    def on_emitter_step(self, em):
        st = em.user.get(Spawn)
        if st is None:
            return
        if st["done"]:
            return
        if st["delay"] > 0:
            st["delay"] -= 1
            return
        if st["wait"] > 0:
            st["wait"] -= 1
            return

        f = em.f(SPAWN)
        rng = st["rng"]

        count = jitter_int(f.get("spawnNum"), f.get("spawnNumJitter"),
                           rng)
        if count > 0:
            cap = f.i("maxParticles")
            if cap > 0:
                count = min(count, max(0, cap - em.alive_count))
            em.request_spawn(count)

        st["burst_index"] += 1

        if st["bursts_left"] is None or st["burst_index"] < st["bursts_left"]:
            st["wait"] = self._gap(self._next_interval(em, st))
            return

        # 本轮最后一批：发完全部轮次就停，否则等 revivalInterval 后复活
        st["rounds_done"] += 1
        rounds = f.i("revivalLoop")
        if rounds != 0 and st["rounds_done"] >= rounds:
            st["done"] = True
            return
        st["wait"] = self._gap(jitter_int(f.get("revivalInterval"),
                                          f.get("revivalIntervalJitter"), rng))
        em.cycle += 1
        if em.cycle == 1:
            em.note("SPAWN 进入复活（换位置的实际偏移未模拟）")
        self._begin_cycle(em, st)

    @staticmethod
    def _gap(interval):
        """将 `interval` 帧的间隔换算为倒计时初值。

        倒计时先判断 >0 再递减，初值须减 1 才能得到恰好 `interval` 帧的间距：interval=10 时
        第 0 帧发一批、第 10 帧发下一批；interval=0 时每帧发射。
        """
        return max(0, int(interval) - 1)

    # ── 粒子 ─────────────────────────────────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        f = em.f(SPAWN, p)
        if f is None:
            return
        p.delay_left = max(0, jitter_int(f.get("particleDelayFrame"),
                                         f.get("particleDelayFrameJitter"),
                                         rng))
