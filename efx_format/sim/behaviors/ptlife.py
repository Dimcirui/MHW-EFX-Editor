# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/ptlife.py  —  PTLIFE（粒子在某个生命阶段触发一个 Action）

一个 PTLIFE 属性说的是：**本 entry 的每个粒子**，在指定的生命阶段，触发
`relationIndex` 指的那个 ACTION —— 那个 action 里的 PLAYEMITTER 再点名一组目标
entry，于是「粒子生出来又生出一堆子特效」。

字段
----
    status(Trigger On)   ENUM_PTLIFE_STATUS：0=生成时 1=淡入时 2=持续时 3=淡出时 4=死亡时
                         官方语料 8904 块里 0 占 92%（8188），其余 3/2/4/1 合计 716。
    relationIndex        ACTION 段的局部下标；-1 = 不触发（语料 416 块）。
                         语料里**没有越界值**，8488 块全部落在 action 数内。
    unknFrame0/1(+Jitter) 疑似延迟/间隔的帧数对，99.4% 为 0，本 behavior 暂不参与计算
                         （非 0 时 note 一条，别让人以为算进去了）。

阶段判定复用 LIFE 已经算好的边界（`p.rolled` 里的 life_fade_in / life_total /
life_fade_out），所以本 behavior 排在 LIFE 之后（SHADE / ORDER=200）。每个粒子
**只触发一次**（子特效是一次性生出来的，不是每帧刷一个）。

「淡入时」这一档的确切时机（进入淡入段 = 出生那一刻，还是淡入**结束**那一刻）
没有实测依据；这里按**进入该阶段**统一处理，于是 fadeIn=0 时它与「生成时」等价。
语料里这一档只有 15 块，先不为它加开关。

本 behavior 只**产出请求**（`em.spawn_requests`），真正建子实例、让子实例跟着父粒子
走、父粒子死后失去 parent 就地留下——全在 `sim/scene.py`。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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

#: 需要在 step 里等阶段边界的那几档（0 在 spawn 里发、4 在 death 里发）
_PHASE_STATUS = (ON_FADE_IN, ON_SUSTAIN, ON_FADE_OUT)


@register(PTLIFE)
class PtLife(Behavior):
    """SHADE 阶段（排在 LIFE 之后）：按生命阶段产出 action 触发请求。"""

    STAGE = SHADE
    ORDER = 200

    _status = ON_SPAWN
    _action = -1
    _armed = False          # relationIndex 有效才需要干活

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
            return                      # 一个粒子只触发一次
        if p.age >= self._phase_start(p):
            self._fire(p, em)

    def on_particle_death(self, p, em):
        if not self._armed or self._status != ON_DEATH:
            return None
        if p.user.get(PtLife):
            return None
        # 死亡这一档直接产出（返回值由 Simulator 收进 em.spawn_requests）
        p.user[PtLife] = True
        return [self._request(p)]

    # ── 内部 ─────────────────────────────────────────────────────────────────
    def _phase_start(self, p):
        """该 status 对应的阶段**起始** age。"""
        rolled = p.rolled
        fade_in = rolled.get("life_fade_in", 0)
        if self._status == ON_FADE_IN:
            return 0
        if self._status == ON_SUSTAIN:
            return fade_in
        # ON_FADE_OUT：无限寿命没有淡出段，退化成「淡出段起点 = 永不到达」
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
