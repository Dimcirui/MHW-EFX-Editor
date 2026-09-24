# -*- coding: utf-8 -*-
"""PTCOLLISION —— 粒子与地面碰撞：反弹、结束方式与触地触发。

字段职能：

    physicsEnum                     0=穿透坠落 1=反弹后强制消亡 2=反弹后渐隐消亡
                                    3=反弹后停留地面 4=反弹后穿透坠落
    projectionOffset                地面高度偏移，游戏单位（cm）；地面为 Y=projectionOffset
    bounceCount(+Jitter)            允许的反弹次数；第 bounceCount+1 次触地进入结束方式
    bounceElasticity(+Jitter) /     两者之和为触地后垂直地面方向的反向速度乘数
    bounceElasticityMultiplier
    impactPlayTriggerMode           0=每次触地 1=前 N 次触地 2=仅最后一次触地
    impactPlayTriggerCount(+Jitter) 模式 1 的 N
    ieIndex                         触地时触发的 ACTION 段下标，-1 表示不触发

触地序号从 1 起。1~4 号模式在反弹次数用完后的那次触地为「最后一次触地」：1 立即消亡，
2 停在地面并从当帧起走完 LIFE 的淡出段，3 停在地面，4 此后不再碰撞。0 号模式不反弹，
第一次触地即为最后一次，此后穿过地面继续下落。

`horizontalBounce`、`projectionDist` 及其余未命名字段不参与计算。

维护约束：
- 触地判据必须是「越过地面」而非「当前 Y <= 地面」：仅当上一帧在地面以上、本帧在地面或以下
  时判定触地。在地面或地面以下出生的粒子不会触地。
- 反弹须同时改写 `p.vel` 与 `p.vel_free`，否则 VELOCITY3D 下一帧用自由速度覆盖反弹结果。
- 必须位于 CONSTRAIN 阶段：须在 INTEGRATE 计算本帧位置之后、XFORM 之前覆写 `p.pos` /
  `p.vel`；渐隐改写的 LIFE 边界由同帧稍后的 SHADE 阶段读取。
"""

from ...hashes import PTCOLLISION
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import CONSTRAIN
from ..state import SpawnRequest, Vec3

PHYS_FALL_THROUGH = 0
PHYS_KILL = 1
PHYS_FADE = 2
PHYS_STAY = 3
PHYS_BOUNCE_FALL_THROUGH = 4

TRIGGER_EVERY = 0
TRIGGER_FIRST_N = 1
TRIGGER_FINAL = 2

# 粒子碰撞状态
_FLYING = 0
_RESTING = 1      # 停在地面（停留或渐隐）
_PASSED = 2       # 不再碰撞（穿透）


@register(PTCOLLISION)
class PtCollision(Behavior):
    """CONSTRAIN 阶段处理触地：反弹、按 physicsEnum 结束，并按触发模式派发 ACTION。"""

    STAGE = CONSTRAIN
    ORDER = 200

    _action = -1
    _phys = PHYS_STAY
    _ground = 0.0
    _mode = TRIGGER_EVERY

    def on_emitter_init(self, em, rng):
        f = em.f(PTCOLLISION)
        if f is None:
            return
        self._action = f.i("ieIndex", -1)
        self._phys = f.i("physicsEnum", PHYS_STAY)
        if not PHYS_FALL_THROUGH <= self._phys <= PHYS_BOUNCE_FALL_THROUGH:
            em.note("PTCOLLISION.physicsEnum=%d 含义未知，按反弹后停留处理" % self._phys)
            self._phys = PHYS_STAY
        self._ground = float(f.get("projectionOffset", 0.0))
        self._mode = f.i("impactPlayTriggerMode")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(PTCOLLISION, p)
        if f is None:
            return
        if self._phys == PHYS_FALL_THROUGH:
            bounces = 0
        else:
            bounces = max(0, jitter_int(f.get("bounceCount"), f.get("bounceCountJitter"),
                                        rng))
        elasticity = (jitter(f.get("bounceElasticity"), f.get("bounceElasticityJitter"),
                             rng)
                      + float(f.get("bounceElasticityMultiplier", 0.0)))
        p.user[PtCollision] = {
            "prev_y": p.pos.y,
            "state": _FLYING,
            "impacts": 0,
            "bounces": bounces,
            "elasticity": max(0.0, elasticity),
            "trigger_n": max(0, jitter_int(f.get("impactPlayTriggerCount"),
                                           f.get("impactPlayTriggerCountJitter"),
                                           rng)),
            "rest_pos": None,
        }

    def on_particle_step(self, p, em):
        st = p.user.get(PtCollision)
        if st is None:
            return
        state = st["state"]
        if state == _RESTING:
            # 无论本帧积分结果如何，均固定在落地点
            p.pos = st["rest_pos"].copy()
            p.vel = Vec3(0.0, 0.0, 0.0)
            p.vel_free = Vec3(0.0, 0.0, 0.0)
            return
        if state == _PASSED:
            return
        g = self._ground
        if not (st["prev_y"] > g >= p.pos.y):
            st["prev_y"] = p.pos.y
            return

        st["impacts"] += 1
        k = st["impacts"]
        final = k > st["bounces"]
        if self._should_trigger(k, final, st):
            em.spawn_requests.append(
                SpawnRequest("action", self._action,
                             pos=Vec3(p.pos.x, g, p.pos.z), particle=p,
                             source_hash=PTCOLLISION))

        if not final:
            e = st["elasticity"]
            p.pos.y = g
            p.vel.y = -p.vel.y * e
            p.vel_free.y = -p.vel_free.y * e
        elif self._phys in (PHYS_FALL_THROUGH, PHYS_BOUNCE_FALL_THROUGH):
            st["state"] = _PASSED
        elif self._phys == PHYS_KILL:
            p.alive = False
        else:
            p.pos.y = g
            st["state"] = _RESTING
            st["rest_pos"] = p.pos.copy()
            p.vel = Vec3(0.0, 0.0, 0.0)
            p.vel_free = Vec3(0.0, 0.0, 0.0)
            if self._phys == PHYS_FADE:
                self._begin_fade(p)
        st["prev_y"] = p.pos.y

    def _should_trigger(self, k, final, st):
        if self._action < 0:
            return False
        if self._mode == TRIGGER_FIRST_N:
            return k <= st["trigger_n"]
        if self._mode == TRIGGER_FINAL:
            return final
        return True

    @staticmethod
    def _begin_fade(p):
        """从当帧起走完 LIFE 的淡出段；没有淡出段时下一帧消亡，没有 LIFE 时立即消亡。"""
        if "life_total" not in p.rolled:
            p.alive = False
            return
        fade_out = int(p.rolled.get("life_fade_out", 0) or 0)
        total = p.age + max(1, fade_out)
        p.rolled["life_indefinite"] = False
        p.rolled["life_total"] = total
        p.rolled["life_fade_out"] = max(1, fade_out)
        p.life = total
