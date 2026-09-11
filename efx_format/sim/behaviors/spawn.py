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

未使用的字段：`instanceCountUnknLimit`(+Jitter) / `unknBitmask31`——schema 注释写明
「仍未测试」，这里不猜。

⚠ 发射器没有「停」的条件
------------------------
三态里没有任何一态会让发射停下来：0 态无限生成，1/≥2 态在最后一批之后换位置、
重抽 burstsPerCycle、开下一轮——也是无限。所以**「播放一次」的长度不由 SPAWN 决定**，
得由播放器自己定（见 `Simulator.suggested_duration()`）。如果以后实测发现确实存在
停止条件（例如 instanceCountUnknLimit 就是终身总量上限），补在 `_begin_cycle` 里。

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

        if per_cycle == 1:
            # 三态之二：改用 altBurstInterval 作为节奏
            interval = jitter_int(f.get("altBurstInterval"), f.get("altBurstIntervalJitter"),
                                  rng, mode)
        else:
            interval = jitter_int(f.get("burstInterval"), f.get("burstIntervalJitter"),
                                  rng, mode)

        if per_cycle == 0 or repeat == 0:
            # 三态之一 / emitterRepeatCount=0：永不换位置，按节奏无限生成
            st["bursts_left"] = None
        else:
            st["bursts_left"] = max(1, per_cycle + repeat - 1)

        st["interval"] = max(0, interval)
        st["burst_index"] = 0

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
            st["wait"] = self._gap(self._last_burst_interval(em))
            em.cycle += 1
            if em.cycle == 1:
                # ⚠ 「换位置」本身要靠 TRANSFORM3D/RANDOMFIX 决定新原点，那部分语义
                # 还没模拟；这里只推进轮次号，供别的 behavior 据此换一批采样。
                em.note("SPAWN 进入多轮模式（换位置的实际偏移未模拟）")
            self._begin_cycle(em, st)
        else:
            st["wait"] = self._gap(st["interval"])

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
