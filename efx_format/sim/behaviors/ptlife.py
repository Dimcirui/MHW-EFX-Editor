# -*- coding: utf-8 -*-
"""PTLIFE —— 粒子在指定生命阶段触发一个 ACTION。

PTLIFE 表示：**本 entry 的每个粒子**在指定生命阶段触发 `relationIndex` 所指的 ACTION；该
ACTION 中的 PLAYEMITTER 再指定一组目标 entry，由此形成「粒子派生子特效」的结构。

字段职能：

    status（Trigger On）    0=生成时 1=淡入时 2=持续时 3=淡出时 4=死亡时
    relationIndex           ACTION 段的局部下标，-1 表示不触发
    unknFrame0/1(+Jitter)   疑似延迟或间隔的帧数对，不参与计算，非 0 时记录 note

「淡入时」按**进入该阶段**的时刻处理，因此 fadeIn=0 时与「生成时」等价。

本 behavior 只产生请求（`em.spawn_requests`）。子实例的创建、子实例跟随父粒子、父粒子死亡后
子实例脱离并留在原处，均由 `sim/scene.py` 负责。

维护约束：
- 阶段判定使用 LIFE 计算的边界（`p.rolled` 中的 life_fade_in / life_total / life_fade_out），
  因此必须排在 LIFE 之后。
- 每个粒子只触发一次：子特效一次性生成，而非每帧生成。
"""

from ...hashes import PTLIFE
from ..registry import Behavior, register
from ..stages import SHADE
from ..state import SpawnRequest

# ENUM_PTLIFE_STATUS
ON_SPAWN = 0
ON_FADE_IN = 1
ON_SUSTAIN = 2
ON_FADE_OUT = 3
ON_DEATH = 4

#: 需在 step 中等待阶段边界的取值；0 在 spawn 中触发，4 在 death 中触发
_PHASE_STATUS = (ON_FADE_IN, ON_SUSTAIN, ON_FADE_OUT)


@register(PTLIFE)
class PtLife(Behavior):
    """SHADE 阶段按粒子的生命阶段产出 ACTION 触发请求。"""

    STAGE = SHADE
    ORDER = 200

    _status = ON_SPAWN
    _action = -1
    _armed = False          # 仅在 relationIndex 有效时启用

    def on_emitter_init(self, em, rng):
        f = em.f(PTLIFE)
        if f is None:
            return
        self._status = f.i("status")
        self._action = f.i("relationIndex", -1)
        self._armed = self._action >= 0
        if not self._armed:
            em.note("PTLIFE.relationIndex = -1：不触发任何 Action")
        if f.i("unknFrame0") or f.i("unknFrame1"):
            em.note("PTLIFE 的 unknFrame0/1 非 0（疑似延迟/间隔），未参与模拟")
        if self._status not in (ON_SPAWN, ON_FADE_IN, ON_SUSTAIN, ON_FADE_OUT, ON_DEATH):
            em.note("PTLIFE.status=%d 含义未知，按「生成时」处理" % self._status)
            self._status = ON_SPAWN

    # ── 触发点 ───────────────────────────────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        if self._armed and self._status == ON_SPAWN:
            self._fire(p, em)

    def on_particle_step(self, p, em):
        if not self._armed or self._status not in _PHASE_STATUS:
            return
        if p.user.get(PtLife):
            return
        if p.age >= self._phase_start(p):
            self._fire(p, em)

    def on_particle_death(self, p, em):
        if not self._armed or self._status != ON_DEATH:
            return None
        if p.user.get(PtLife):
            return None
        # 死亡阶段以返回值产生请求，由 Simulator 收入 em.spawn_requests
        p.user[PtLife] = True
        return [self._request(p)]

    # ── 内部 ─────────────────────────────────────────────────────────────────
    def _phase_start(self, p):
        """该 status 对应的阶段起始 age。"""
        rolled = p.rolled
        fade_in = rolled.get("life_fade_in", 0)
        if self._status == ON_FADE_IN:
            return 0
        if self._status == ON_SUSTAIN:
            return fade_in
        # ON_FADE_OUT：无限寿命没有淡出段，起点取为不可达
        if rolled.get("life_indefinite", False):
            return 1 << 30
        total = rolled.get("life_total", 0)
        return max(fade_in, total - rolled.get("life_out", rolled.get("life_fade_out", 0)))

    def _request(self, p):
        return SpawnRequest("action", self._action, pos=p.pos.copy(), particle=p,
                            source_hash=PTLIFE)

    def _fire(self, p, em):
        p.user[PtLife] = True
        em.spawn_requests.append(self._request(p))
