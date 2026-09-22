# -*- coding: utf-8 -*-
"""PTCOLLISION —— 粒子落地后停留在地面，可选触发一次 ACTION。

模拟只实现两项：落地即停止，以及落地当帧触发一次 `ieIndex` 指向的 ACTION。反弹次数、弹性、
水平弹跳、触发模式与次数等字段的语义与结束行为均未确认，不予模拟。停留地面是反弹弹性为 0 时
唯一确定的终态，因此作为落地行为。

地面为游戏坐标系的 Y=0。落地时位置固定在落地当帧（Y 限定为 0），速度清零，此后不再下落或
滑动。`ieIndex` 为 ACTION 段下标，取 -1 时不触发 ACTION，但仍固定落地位置：固定位置是物理
表现，触发是附加效果，两者相互独立。

维护约束：
- 触发判据必须是「越过地面」而非「当前 Y <= 0」：记录上一帧的 Y，仅当上一帧 Y>0 且本帧 Y<=0
  时判定落地。因此在地面或地面以下出生的粒子不会触发，且每个粒子一生只落地一次。
- 必须位于 CONSTRAIN 阶段：须在 INTEGRATE 计算本帧位置之后、XFORM 之前覆写 `p.pos` /
  `p.vel`。
"""

from ...hashes import PTCOLLISION
from ..registry import Behavior, register
from ..stages import CONSTRAIN
from ..state import SpawnRequest, Vec3


@register(PTCOLLISION)
class PtCollision(Behavior):
    """CONSTRAIN 阶段在粒子越过地面时固定其位置，可选触发一次 ACTION。"""

    STAGE = CONSTRAIN
    ORDER = 200

    _action = -1
    _armed = False

    def on_emitter_init(self, em, rng):
        f = em.f(PTCOLLISION)
        if f is None:
            return
        self._action = f.i("ieIndex", -1)
        self._armed = self._action >= 0
        if not self._armed:
            em.note("PTCOLLISION.ieIndex = -1：不触发任何 Action（落地冻结仍生效）")
        em.note("PTCOLLISION 仅模拟落地冻结 + 单次触发，反弹/弹性/触发次数等字段未模拟")

    def on_particle_spawn(self, p, em, rng):
        p.user[PtCollision] = {"prev_y": p.pos.y, "landed": False, "rest_pos": None}

    def on_particle_step(self, p, em):
        st = p.user.get(PtCollision)
        if st is None:
            return
        if st["landed"]:
            # 无论本帧积分结果如何，均固定在落地点
            p.pos = st["rest_pos"].copy()
            p.vel = Vec3(0.0, 0.0, 0.0)
            return
        prev_y = st["prev_y"]
        cur_y = p.pos.y
        if prev_y > 0.0 and cur_y <= 0.0:
            p.pos.y = 0.0
            st["landed"] = True
            st["rest_pos"] = p.pos.copy()
            p.vel = Vec3(0.0, 0.0, 0.0)
            if self._armed:
                em.spawn_requests.append(
                    SpawnRequest("action", self._action, pos=p.pos.copy(), particle=p,
                                 source_hash=PTCOLLISION))
        st["prev_y"] = p.pos.y
