# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/spawn.py  —  SPAWN（发射节奏）

模型照搬 efx_format/schema/attributes.py 里 2026-07-26 实机测试记下的三层结构
（SPAWN 属性 → emitter 实例/轮次 → particle 个体）：

  - `maxParticles`：**同时存活**软上限（不是终身总量）。
  - `burstsPerCycle`(+Jitter)：每轮（每次换位置）重抽，三态——
        0  → 永不换位置，按 burstInterval 节奏无限生成
        1  → 改用 altBurstInterval 节奏
        ≥2 → 仍用 burstInterval 节奏
    非 0 时总批次数 = 该值 + emitterRepeatCount - 1，最后一批固定按粒子寿命
    （LIFE.duration + fadeOutDuration）节奏，随后立即换位置。
  - `emitterRepeatCount`：0 = 无论 burstsPerCycle 是什么都永不换位置。无 Jitter 搭档。
  - `particleSpawnDelay`(+Jitter)：唯一的 particle 层字段，逐粒子独立延迟。

`burstInterval` 的抖动每批重抽
------------------------------
`SimConfig.spawn_interval_jitter`（默认 `per_burst`）。`particlesPerBurst` 的抖动本来就是
每批重抽的，间隔没理由是另一套；而且「每批重抽」会让一串粒子的间距参差不齐，这与
`burstIntervalJitter` 非 0 的特效在游戏里看到的不均匀排布一致。`per_cycle` 保留改动前的
行为（一轮只抽一次，整轮等距）。

未使用的字段：`instanceCountUnknLimit`(+Jitter) / `unknBitmask31`——schema 注释写明
「仍未测试」，这里不猜。

发射会停
--------
`emitterRepeatCount` 非 0 **且** `burstsPerCycle` 非 0 时，那 `per_cycle + repeat - 1`
批发完就**不再发了**（`SimConfig.spawn_after_cycle`，默认 `stop`）。这是实机行为：
用户的 `05 spell` 是 10 批、游戏里就只有 10 个符文，之后再没有新的。

两个「无限」态照旧永不停：`burstsPerCycle == 0`、或 `emitterRepeatCount == 0`
（后者的「否决权」语义见 schema 注释）。`repeat` 开关值切到 `recycle` 可以退回改动前的
行为（等一个粒子寿命后换位置、重抽、再开一轮）。

发射器级的随机（每批重抽的数量/间隔）走 `em` 自己的随机流，不占用逐粒子的流，
见 rng.emitter_stream_rng 的说明。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import LIFE, SPAWN
from ..registry import Behavior, register
from ..rng import emitter_stream_rng, jitter_int
from ..stages import FORCE


@register(SPAWN)
class Spawn(Behavior):
    """只跑发射器时间轴；不参与逐粒子 step，故 STAGE 取什么都行。"""

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
            "delay": jitter_int(f.get("emitterStartDelay"),
                                f.get("emitterStartDelayJitter"),
                                srng, em.config.jitter_mode),
            "wait": 0,
            "bursts_left": None,     # None = 本轮不计数（永不换位置，无限生成）
            "burst_index": 0,
            "interval": 0,
            "done": False,           # 有限轮次跑完 = 这个发射器不再发了
        }
        em.user[Spawn] = st
        self._begin_cycle(em, st)

    def _begin_cycle(self, em, st):
        """开一轮：重抽 burstsPerCycle，定这一轮的节奏与批次数。"""
        f = em.f(SPAWN)
        cfg = em.config
        rng = st["rng"]
        mode = cfg.jitter_mode

        per_cycle = jitter_int(f.get("burstsPerCycle"), f.get("burstsPerCycleJitter"),
                               rng, mode)
        repeat = f.i("emitterRepeatCount")

        # 三态之二（per_cycle==1）：节奏改用 altBurstInterval
        st["interval_field"] = ("altBurstInterval", "altBurstIntervalJitter")             if per_cycle == 1 else ("burstInterval", "burstIntervalJitter")
        interval = self._roll_interval(em, st)

        if per_cycle == 0 or repeat == 0:
            # 三态之一 / emitterRepeatCount=0：永不换位置，按节奏无限生成
            st["bursts_left"] = None
        else:
            st["bursts_left"] = max(1, per_cycle + repeat - 1)

        st["interval"] = max(0, interval)
        st["burst_index"] = 0

    def _roll_interval(self, em, st):
        """抽一次批间隔。`per_burst` 下每批都会重新调用这里（见模块 docstring）。"""
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
        """最后一批之后的等待：按粒子寿命（LIFE.duration + fadeOutDuration）。"""
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

        count = jitter_int(f.get("particlesPerBurst"), f.get("particlesPerBurstJitter"),
                           rng, cfg.jitter_mode)
        if count > 0:
            cap = f.i("maxParticles")
            if cap > 0:
                count = min(count, max(0, cap - em.alive_count))
            em.request_spawn(count)

        st["burst_index"] += 1

        # 本轮最后一批 → 按粒子寿命等一段，然后换位置、开下一轮
        # （`bursts_left is None` 就是「永不换位置」那两态，一直按 interval 走）
        if st["bursts_left"] is not None and st["burst_index"] >= st["bursts_left"]:
            if getattr(cfg, "spawn_after_cycle", "stop") == "stop":
                st["done"] = True       # 批次发完就收工（见模块 docstring「发射会停」）
                return
            st["wait"] = self._gap(self._last_burst_interval(em))
            em.cycle += 1
            if em.cycle == 1:
                # ⚠ 「换位置」本身要靠 TRANSFORM3D/RANDOMFIX 决定新原点，那部分语义
                # 还没模拟；这里只推进轮次号，供别的 behavior 据此换一批采样。
                em.note("SPAWN 进入多轮模式（换位置的实际偏移未模拟）")
            self._begin_cycle(em, st)
        else:
            st["wait"] = self._gap(self._next_interval(em, st))

    @staticmethod
    def _gap(interval):
        """`interval` 帧的间隔 → 倒计时初值。

        倒计时是「先判 >0 再减」，所以初值要少 1 才能得到正好 `interval` 帧的间距：
        interval=10 时 frame0 发一批、frame10 发下一批。interval=0 → 每帧都发。
        """
        return max(0, int(interval) - 1)

    # ── 粒子 ─────────────────────────────────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        f = em.f(SPAWN, p)
        if f is None:
            return
        p.delay_left = max(0, jitter_int(f.get("particleSpawnDelay"),
                                         f.get("particleSpawnDelayJitter"),
                                         rng, em.config.jitter_mode))
