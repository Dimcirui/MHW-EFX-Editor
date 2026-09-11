# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/velocity3d.py  —  VELOCITY3D（初速度 + 逐帧积分）

语义来源：blender_efx/annotations.py 的 ("VELOCITY3D", ...) 条目（已实测）。

    baseAxis      六个基准轴之一，不是自由方向向量。游戏坐标系 +X=左 +Y=上 +Z=前，
                  0=左 1=上 2=前 3=右 4=下 5=后。仅 velocityType=Directional 有意义。
    rotOrder      **另一套**取值→顺序映射（_ROT_ORDER6），跟 TRANSFORM3D 的不是一套。
    speedCoef     「逐帧速度倍率：对应的速度每帧乘一次这个值」
                  → 1=匀速、>1 加速、<1 减速。这是整个模型是**逐帧乘法递推**而非
                    dt 积分的直接证据，别改成 dt。
    velocityType  0=Directional（baseAxis+rotation 定方向）
                  1=DirectionalSpread（Vi=(divergence-1)*生成坐标+velocity，归一化）
                  2=Radial（始终向外，rotation/velocity/divergence 均无效）
                  3=EmitterMotion（继承发射器自身移动，受 minMovementThreshold 门控）
                  ⚠ 4/5 也出现过，含义未知 → 按 0 处理并记 note
    gravity       「不论 Velocity Type 如何，始终生效」

    movementDelay / gravityDelay（+Jitter）：起效前的帧数延迟。

待标定
------
- 旋转顺序串里「先写的先作用」还是相反：SimConfig.rot_order_applied。
- 重力方向按 +Y=上 取 -Y；`minMovementThreshold` 的比较对象（速度还是位移）未确认，
  当前按发射器**每帧位移**长度比较。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

import math

from ...hashes import VELOCITY3D
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import INTEGRATE
from ..state import BASE_AXES, Vec3
from ..vecmath import ROT_ORDER_VELOCITY, rot_order_name, rotate_euler

VT_DIRECTIONAL = 0
VT_DIRECTIONAL_SPREAD = 1
VT_RADIAL = 2
VT_EMITTER_MOTION = 3


@register(VELOCITY3D)
class Velocity3D(Behavior):
    """INTEGRATE 阶段：把速度积到位置上。改速度的（NOISE/TURBULENCE/HOMING）排在
    FORCE 阶段，自动跑在本阶段之前。"""

    STAGE = INTEGRATE
    ORDER = 100

    def on_particle_spawn(self, p, em, rng):
        f = em.f(VELOCITY3D, p)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode

        p.rolled["v_speed"] = jitter(f.get("speed"), f.get("speedJitter"), rng, mode)
        p.rolled["v_coef"] = jitter(f.get("speedCoef", 1.0), f.get("speedCoefJitter"),
                                    rng, mode)
        p.rolled["v_gravity"] = jitter(f.get("gravity"), f.get("gravity_jitter"),
                                       rng, mode)
        p.rolled["v_move_delay"] = max(0, jitter_int(
            f.get("movementDelay"), f.get("movementDelayJitter"), rng, mode))
        p.rolled["v_grav_delay"] = max(0, jitter_int(
            f.get("gravityDelay"), f.get("gravityDelayJitter"), rng, mode))

        vtype = f.i("velocityType")
        if vtype > VT_EMITTER_MOTION:
            em.note("VELOCITY3D.velocityType=%d 含义未知，按 Directional 处理" % vtype)
            vtype = VT_DIRECTIONAL
        p.rolled["v_type"] = vtype

        direction = self._initial_direction(vtype, f, p, em, rng, cfg)
        p.vel = direction * p.rolled["v_speed"]

    def _initial_direction(self, vtype, f, p, em, rng, cfg):
        if vtype == VT_DIRECTIONAL_SPREAD:
            # Vi = (divergence - 1) * 生成坐标 + velocity，再归一化
            div = Vec3(f.get("divergenceX", 1.0), f.get("divergenceY", 1.0),
                       f.get("divergenceZ", 1.0))
            base = Vec3(f.get("velocityX"), f.get("velocityY"), f.get("velocityZ"))
            v = Vec3((div.x - 1.0) * p.spawn_pos.x + base.x,
                     (div.y - 1.0) * p.spawn_pos.y + base.y,
                     (div.z - 1.0) * p.spawn_pos.z + base.z)
            return v.normalized(fallback=BASE_AXES[1])

        if vtype == VT_RADIAL:
            # 始终向外；rotation/velocity/divergence 均无效
            return p.spawn_pos.normalized(fallback=self._random_unit(rng))

        if vtype == VT_EMITTER_MOTION:
            thr = f.get("minMovementThreshold")
            mv = em.velocity
            if mv.length() <= thr:
                return Vec3()
            return mv.normalized()

        # VT_DIRECTIONAL：baseAxis 经 rotationX/Y/Z（带抖动）旋转
        axis_idx = f.i("baseAxis")
        axis = BASE_AXES[axis_idx] if 0 <= axis_idx < len(BASE_AXES) else BASE_AXES[1]
        mode = cfg.jitter_mode
        rx = jitter(f.get("rotationX"), f.get("rotationXJitter"), rng, mode)
        ry = jitter(f.get("rotationY"), f.get("rotationYJitter"), rng, mode)
        rz = jitter(f.get("rotationZ"), f.get("rotationZJitter"), rng, mode)
        order = rot_order_name(f.i("rotOrder"), ROT_ORDER_VELOCITY)
        return rotate_euler(axis, rx, ry, rz, order=order,
                            applied=cfg.rot_order_applied)

    @staticmethod
    def _random_unit(rng):
        """spawn_pos 恰好在原点时 Radial 没有方向可用，退回一个随机方向。"""
        z = rng.uniform(-1.0, 1.0)
        a = rng.uniform(0.0, 2.0 * math.pi)
        r = math.sqrt(max(0.0, 1.0 - z * z))
        return Vec3(math.cos(a) * r, z, math.sin(a) * r)

    # ── 逐帧 ─────────────────────────────────────────────────────────────────
    def on_particle_step(self, p, em):
        # 逐帧乘法递推：speedCoef 每帧乘一次（不是 dt 积分）
        coef = p.rolled.get("v_coef", 1.0)
        if coef != 1.0:
            p.vel *= coef

        if p.age >= p.rolled.get("v_grav_delay", 0):
            g = p.rolled.get("v_gravity", 0.0)
            if g:
                p.vel.y -= g          # 游戏坐标系 +Y = 上

        if p.age >= p.rolled.get("v_move_delay", 0):
            p.pos += p.vel
