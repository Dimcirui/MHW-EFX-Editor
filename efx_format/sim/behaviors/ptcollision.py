# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/ptcollision.py  —  PTCOLLISION（粒子撞地→停在地面，可选触发一次 Action）

范围收窄（用户 2026-09-13 定调，2026-09-13 追加"停留地面"）：PTCOLLISION 的
绝大多数字段（反弹次数/弹性/水平弹跳/触发模式次数……）语义或收尾行为都还没
实机坐实，全部实现风险太高。这里做两件事，都不涉及那些未坐实字段：

    1. **落地即停**：粒子越过地面（游戏坐标系 Y=0，对应 Blender Z=0，见
       `state.py` 顶部坐标系说明 + `sim_preview.py::_to_blender` 的
       (X,Y,Z)→(X,-Z,Y) 换算）那一刻，位置整体冻结在落地那一帧的坐标（Y 钳到
       0），速度清零——之后不再继续下落/滑动。**不做真正的反弹**（弹性、多次
       回弹、水平弹跳都不模拟），"停留"是反弹被压到 0 次弹性之后唯一确定的
       终态，因此拿它当第一版落地行为。
    2. **触发一次 Action**：落地那一帧，若 `ieIndex` 有效，触发它指向的 ACTION
       一次。

字段
----
    ieIndex   ACTION 段下标（同 PTLIFE.relationIndex 的用法，见 PROGRESS.md
              「eof_ints」条：ieIndex→action(int32,offset 96)）；-1 = 不触发
              Action（但落地冻结仍然发生——两者是独立的：冻结是物理表现，
              触发是附加效果）。

触发判据：**必须是「越过」**，不是「当前 ≤0」——记一份上一帧的 Y，只有「上一帧
Y>0 且这一帧 Y<=0」才算撞地。粒子一出生就在地面（含地面以下）永远满足不了
「上一帧 Y>0」，因此天然不触发（用户要求的边缘情况）。整个生命只落地一次。

落地后要覆写 `p.pos`/`p.vel`，因此本 behavior 放在 CONSTRAIN 阶段（INTEGRATE
算完这一帧的位置之后、XFORM/SHADE 之前覆写回落地点）；ACTION 触发只是产出
`SpawnRequest`，哪个阶段都能做，跟着挪过来一起写更简单。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import PTCOLLISION
from ..registry import Behavior, register
from ..stages import CONSTRAIN
from ..state import SpawnRequest, Vec3


@register(PTCOLLISION)
class PtCollision(Behavior):
    """CONSTRAIN 阶段：粒子越过地面（Y=0）时冻结在落地点，可选触发一次 ACTION。"""

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
            # 冻结：不管这一帧 VELOCITY3D/重力算出了什么，都按落地点钉死。
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
