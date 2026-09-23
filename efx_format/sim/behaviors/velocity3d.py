# -*- coding: utf-8 -*-
"""VELOCITY3D —— 初速度与逐帧积分。

字段职能：

    baseAxis                六个基准轴之一，而非任意方向向量。游戏坐标系 +X=左 +Y=上 +Z=前，
                            取值 0=左 1=上 2=前 3=右 4=下 5=后。
                            仅在 velocityType=Directional 时有效
    rotOrder                取值到旋转顺序的映射为 `_ROT_ORDER6`，与 TRANSFORM3D 不同
    speed(+Jitter)          初速度大小
    speedCoef(+Jitter)      逐帧速度倍率，速度每帧乘以此值。1 为匀速，大于 1 加速，小于 1 减速
    velocityType            0=Directional：由 baseAxis 与 rotation 确定方向
                            1=DirectionalSpread：Vi=(size-1)·生成坐标+offset，再归一化
                            2=Radial：始终向外，rotation / velocity / divergence 均无效
                            3=EmitterMotion：继承发射器自身的运动，受 minMovementThreshold 限制
                            4 / 5 在语料中出现，含义未知，按 0 处理并记录 note
    gravity(+Jitter)        与 velocityType 无关，始终生效，方向为 -Y
    movementDelay /         各自生效前的延迟帧数
    gravityDelay(+Jitter)

维护约束：
- `speedCoef` 为**逐帧乘法递推**，而非 dt 积分；改为按 dt 缩放会改变整条速度曲线。
- `speedCoef` 与 `gravity` 必须同时作用于两条速度通道：`p.vel` 为总速度（自由速度与 HOMING
  本帧的指令速度之和），`p.vel_free` 仅为自由速度。作用于 `p.vel` 意味着 speedCoef 对粒子
  总速度生效，HOMING 驱动的部分同样受影响；HOMING 每帧重写 `p.vel`，因此对该部分而言是单帧
  倍率，而非几何累积。没有 HOMING 时两条通道逐帧一致。
- TIML（A1）：speed 与 gravity 每帧取「曲线值 + 出生时抽取的抖动偏移」为基准。speed 的基准再
  乘以 speedCoef 按年龄的累积衰减，按与上一帧的差量沿初速度方向加到两条速度通道上，不打乱
  gravity 的累积与 HOMING 的指令速度；没有轨道时与逐帧递推完全一致。gravity 没有自己的衰减
  系数，基准即本帧重力。
- 两项未确定的读法以 `SimConfig` 保留：`rot_order_applied`（旋转顺序串中先写的轴先作用还是
  后作用）与 `minMovementThreshold` 的比较对象（当前按发射器每帧位移的长度比较）。
"""

import math

from ...hashes import VELOCITY3D
from ..registry import Behavior, register
from ._common import emitter_rotate
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
    """INTEGRATE 阶段将速度积分到位置；修改速度的属性均位于更早的 FORCE 阶段。"""

    STAGE = INTEGRATE
    ORDER = 100

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(VELOCITY3D)
        if f is not None:
            self._has_tracks = f.has_tracks

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
        if self._has_tracks:
            # TIML 基准 = 曲线值 + 这两个偏移；v_base 为上一帧用过的 speed 基准
            p.rolled["v_speed_off"] = p.rolled["v_speed"] - f.get("speed")
            p.rolled["v_grav_off"] = p.rolled["v_gravity"] - f.get("gravity")
            p.rolled["v_base"] = p.rolled["v_speed"]
            p.rolled["v_decay"] = 1.0
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
        # 发射器自身旋转时，初速度方向随之旋转；静态朝向由宿主的 entry 矩阵负责
        direction = emitter_rotate(em, direction)
        p.vel = direction * p.rolled["v_speed"]
        p.rolled["v_dir"] = direction
        # 自由速度通道，HOMING 的指令速度叠加在其上
        p.vel_free = p.vel.copy()

    def _initial_direction(self, vtype, f, p, em, rng, cfg):
        if vtype == VT_DIRECTIONAL_SPREAD:
            div = Vec3(f.get("sizeX", 1.0), f.get("sizeY", 1.0),
                       f.get("sizeZ", 1.0))
            base = Vec3(f.get("offsetX"), f.get("offsetY"), f.get("offsetZ"))
            v = Vec3((div.x - 1.0) * p.spawn_pos.x + base.x,
                     (div.y - 1.0) * p.spawn_pos.y + base.y,
                     (div.z - 1.0) * p.spawn_pos.z + base.z)
            return v.normalized(fallback=BASE_AXES[1])

        if vtype == VT_RADIAL:
            return p.spawn_pos.normalized(fallback=self._random_unit(rng))

        if vtype == VT_EMITTER_MOTION:
            thr = f.get("minMovementThreshold")
            mv = em.velocity
            if mv.length() <= thr:
                return Vec3()
            return mv.normalized()

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
    def _apply_speed_track(p, f, coef):
        """speed 曲线的基准变化乘以累积衰减，沿初速度方向补到两条速度通道上。"""
        r = p.rolled
        r["v_decay"] *= coef
        base = f.get("speed") + r["v_speed_off"]
        delta = (base - r["v_base"]) * r["v_decay"]
        r["v_base"] = base
        if delta:
            d = r.get("v_dir")
            if d is not None:
                p.vel += d * delta
                p.vel_free += d * delta

    @staticmethod
    def _random_unit(rng):
        """返回随机单位向量，用于 spawn_pos 恰为原点、Radial 无方向可取的情形。"""
        z = rng.uniform(-1.0, 1.0)
        a = rng.uniform(0.0, 2.0 * math.pi)
        r = math.sqrt(max(0.0, 1.0 - z * z))
        return Vec3(math.cos(a) * r, z, math.sin(a) * r)

    # ── 逐帧 ─────────────────────────────────────────────────────────────────
    def on_particle_step(self, p, em):
        coef = p.rolled.get("v_coef", 1.0)
        if coef != 1.0:
            p.vel *= coef
            p.vel_free *= coef

        f = em.f(VELOCITY3D, p) if self._has_tracks else None
        if f is not None and "v_base" in p.rolled:
            self._apply_speed_track(p, f, coef)

        if p.age >= p.rolled.get("v_grav_delay", 0):
            g = p.rolled.get("v_gravity", 0.0)
            if f is not None and "v_grav_off" in p.rolled:
                g = f.get("gravity") + p.rolled["v_grav_off"]
            if g:
                p.vel.y -= g          # 游戏坐标系 +Y = 上
                p.vel_free.y -= g

        if p.age >= p.rolled.get("v_move_delay", 0):
            p.pos += p.vel
