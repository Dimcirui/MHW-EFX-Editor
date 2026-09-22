# -*- coding: utf-8 -*-
"""SPAWN —— 发射节奏。

三层结构：SPAWN 属性 → emitter 实例／轮次 → particle 个体。

字段职能：

    maxParticles                **同时存活**数量的软上限，而非总生成数
    spawnNum(+Jitter)           每批的粒子数，每批重新抽取
    intervalFrame(+Jitter)      批间隔
    altBurstInterval(+Jitter)   loopNum 取 1 时使用的批间隔
    loopNum(+Jitter)            每轮（每次换位置）重新抽取，取值分三种情形：
                                  0  不换位置，按 intervalFrame 节奏持续生成
                                  1  改用 altBurstInterval 节奏
                                  ≥2 仍用 intervalFrame 节奏
                                非 0 时总批次数 = 该值 + emitterRepeatCount − 1；最后一批之后
                                按粒子寿命（LIFE.duration + fadeOutDuration）等待，随后换位置
    emitterRepeatCount          取 0 时无论 loopNum 如何都不换位置。无对应的 Jitter 字段
    emitterDelayFrame(+Jitter)  发射器自身的起始延迟
    spawnWaitFrame(+Jitter)     唯一的 particle 层字段，逐粒子独立延迟

`spawnFrame`(+Jitter) 与 `spawnFlags` 的六个位（UseSpawnFrame / RingBufferMode /
RayCastHitOnly / RayCastDependency / InitializeFull / InterporatePos）的实际效果均未测试，
模拟层不读取。

维护约束：
- `emitterRepeatCount` 与 `loopNum` 均非 0 时，发完 `loopNum + repeat − 1` 批后停止发射
  （`SimConfig.spawn_after_cycle`，默认 `stop`），这是实机行为。`loopNum == 0` 或
  `emitterRepeatCount == 0` 两种情形持续发射，不会停止。
- `intervalFrame` 的抖动默认每批重新抽取（`SimConfig.spawn_interval_jitter='per_burst'`），
  与 `spawnNum` 的抽取方式一致；`per_cycle` 档则整轮等距。
- 发射器级的随机数（每批的数量与间隔）必须使用 `em` 自身的随机流，不得占用逐粒子的随机流。
"""

from ...hashes import LIFE, SPAWN
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
                                srng, em.config.jitter_mode),
            "wait": 0,
            "bursts_left": None,     # None 表示本轮不计数：不换位置，持续生成
            "burst_index": 0,
            "interval": 0,
            "done": False,           # 有限轮次结束后，该发射器停止发射
        }
        em.user[Spawn] = st
        self._begin_cycle(em, st)

    def _begin_cycle(self, em, st):
        """开始新一轮：重新抽取 loopNum，确定本轮的节奏与批次数。"""
        f = em.f(SPAWN)
        cfg = em.config
        rng = st["rng"]
        mode = cfg.jitter_mode

        per_cycle = jitter_int(f.get("loopNum"), f.get("loopNumJitter"),
                               rng, mode)
        repeat = f.i("emitterRepeatCount")

        st["interval_field"] = ("altBurstInterval", "altBurstIntervalJitter")             if per_cycle == 1 else ("intervalFrame", "intervalFrameJitter")
        interval = self._roll_interval(em, st)

        if per_cycle == 0 or repeat == 0:
            st["bursts_left"] = None        # 不换位置，按节奏持续生成
        else:
            st["bursts_left"] = max(1, per_cycle + repeat - 1)

        st["interval"] = max(0, interval)
        st["burst_index"] = 0

    def _roll_interval(self, em, st):
        """抽取一次批间隔；`per_burst` 下每批调用一次。"""
        f = em.f(SPAWN)
        key, jkey = st["interval_field"]
        v = jitter_int(f.get(key), f.get(jkey), st["rng"], em.config.jitter_mode)
        st["interval"] = max(0, v)
        return st["interval"]

    def _next_interval(self, em, st):
        if getattr(em.config, "spawn_interval_jitter", "per_burst") == "per_cycle":
            return st["interval"]
        return self._roll_interval(em, st)

    def _last_burst_interval(self, em):
        """返回最后一批之后的等待帧数，即粒子寿命（LIFE.duration + fadeOutDuration）。"""
        lf = em.f(LIFE)
        if lf is None:
            return 0
        return max(0, lf.i("duration") + lf.i("fadeOutDuration"))

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
        cfg = em.config
        rng = st["rng"]

        count = jitter_int(f.get("spawnNum"), f.get("spawnNumJitter"),
                           rng, cfg.jitter_mode)
        if count > 0:
            cap = f.i("maxParticles")
            if cap > 0:
                count = min(count, max(0, cap - em.alive_count))
            em.request_spawn(count)

        st["burst_index"] += 1

        # 本轮最后一批之后按粒子寿命等待，然后换位置开始下一轮；
        # bursts_left 为 None 对应不换位置的两种情形，始终按 interval 发射
        if st["bursts_left"] is not None and st["burst_index"] >= st["bursts_left"]:
            if getattr(cfg, "spawn_after_cycle", "stop") == "stop":
                st["done"] = True
                return
            st["wait"] = self._gap(self._last_burst_interval(em))
            em.cycle += 1
            if em.cycle == 1:
                # 换位置所需的新原点由 TRANSFORM3D / RANDOMFIX 决定，该部分未模拟；
                # 此处只推进轮次号，供其它 behavior 据此重新采样
                em.note("SPAWN 进入多轮模式（换位置的实际偏移未模拟）")
            self._begin_cycle(em, st)
        else:
            st["wait"] = self._gap(self._next_interval(em, st))

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
        p.delay_left = max(0, jitter_int(f.get("spawnWaitFrame"),
                                         f.get("spawnWaitFrameJitter"),
                                         rng, em.config.jitter_mode))
