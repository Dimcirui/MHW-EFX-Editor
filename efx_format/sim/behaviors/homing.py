# -*- coding: utf-8 -*-
"""HOMING —— 归航：粒子追踪目标，先直线接近，越过目标后绕其做圆周运动。

HOMING 的运动模型为纯追踪（实现见 `Homing._pursue`）：

    速度方向每帧向「指向目标」的方向旋转 turnRate/fps 度；速度大小由 acceleration 与
    maxSpeed 单独决定。

`turnRate` 为角速度，单位度/秒（360 即每秒一圈）。已确认的单粒子行为均可由该模型导出，
不构成独立机制：

    · 直线接近      V3D 初速度为 0 时，初始方向即指向目标，轨迹为直线。
    · 切圆轨道      粒子越过目标时，「指向目标」的方向翻转 180°，而速度方向每帧至多旋转
                    turnRate，故方向连续变化，轨迹为半径 r = v/ω 的圆。目标点是该圆的切点，
                    圆心位于侧向，而非目标点。
    · 轨道稳定      圆经过目标点时，由弦切角定理，「指向目标」的方向以 ω/2 旋转；粒子以 ω
                    追随，每一整圈恰好回到目标点一次。因此该切圆是追踪方程的不变集。
    · 速度为设定值  轨道直径与出生距离无关，速度大小只由初速度、acceleration 与 maxSpeed
                    决定，与转向无关。

其它速度来源自然参与合成：V3D 初速度决定初始方向，重力逐帧改变方向，speedCoef 缩放当帧输出。
本 behavior 在 FORCE 阶段只写 `p.vel`，位移由 VELOCITY3D 在 INTEGRATE 阶段积分，故 HOMING 依赖
同一 entry 中的 VELOCITY3D（其字段可全为 0）。

模型唯一的奇异点是速度方向与「指向目标」反向平行，即粒子越过目标的瞬间：此时旋转轴无定义，
转向由 `_lateral_dir` 的约定决定。该约定是本模块中尚未确认的部分。奇异点邻域的条件数很差，
旋转轴对横向分量极为敏感，因此速度含有 Y 分量时会出现进动。

`_lateral_dir` 取侧向平面的两个基 `e = normalize(U × d)`（对来向 d 为奇函数，水平）与 `b`
（偶函数），令

    n = cos(φ)·e + sin(φ)·b        φ = tilt·(d·U)

φ 取奇标量 `d·U`，保证 `n` 整体为奇函数，出生球壳上各粒子的侧向方向相互抵消，粒子群没有净
漂移。`tilt`（`SimConfig.homing_orbit_lateral_tilt`）只影响竖直方向的压缩程度。

速度大小：

    起始速度 = min(VELOCITY3D 给出的初速度, maxSpeed)
    每帧速度 += acceleration / fps，至 maxSpeed 为止；自出生起即开始加速

    acceleration 为每秒增加的速度，0 表示保持初速度；maxSpeed 为 0 时粒子静止。半径
    r = v/ω 随速度线性增长，未到上限时轨迹为等距螺旋。

归航目标 `homingTarget`（取模 4）在核心层的对应量：

    0 生成点      em.origin，即发射器的实时位置；逐帧读取，不在 spawn 时固定
    1 模型原点    em.host_origin，即宿主上报的发射器位置，不含本地 TRANSFORM3D 漂移
    2/3 世界原点  本模拟坐标系原点 (0,0,0)，而非 Blender 场景的世界原点

仅取值 0 为精确对应；1 与 2/3 为近似，`on_emitter_init` 会为此记录 note。

力场与消失判定均以目标为球心，半径分别为 `forceFieldRadius` 与 `vanishRadius`：

    forceFieldMode 1     在球内生成的粒子直接剔除
    forceFieldMode 3     球内冻结转向；球内生成的粒子不剔除
    forceFieldMode 2/4   在球内（2）或球外（4）按 forceFieldSpeedScale=k 减速：每帧先乘 k，
                         再加固定增量 c = 1/homing_ff_recover_frames 回升，平衡在
                         min(1, c/(1-k)) 倍速度
    vanishMode 1         进入消失球时触发一次，取消无限寿命。LIFE 的寿命计时自出生起持续，
                         故效果并非立即消失
    vanishMode 2         进入消失球时触发一次，粒子立即消失

维护约束：
- 起始速度必须在第一帧读取：出生时 VELOCITY3D 尚未写入初速度。
- 力场减速必须记录在独立的阻尼因子 `ff_damp` 上，不得写入 `speed`。`speed` 承载
  acceleration 的慢速增长；若约 48 帧的快速回升作用于 `speed`，将完全覆盖增长过程。
- 必须排在 EMITTERSHAPE3D 之后：出生剔除须基于 ES3D 确定后的实际生成位置。
"""

import math

from ...hashes import HOMING
from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3

# ENUM_HOMING_FORCEFIELD
FF_NONE = 0
FF_CULL_INSIDE = 1
FF_SLOW_INSIDE = 2
FF_NO_TURN_INSIDE = 3
FF_SLOW_OUTSIDE = 4

# ENUM_HOMING_VANISH
VANISH_NONE = 0
VANISH_CANCEL_INFINITE = 1
VANISH_IMMEDIATE = 2

_UP = Vec3(0.0, 1.0, 0.0)
_FRONT = Vec3(0.0, 0.0, 1.0)


def _rotate_axis(v, axis, deg):
    """罗德里格斯公式：`v` 绕单位轴 `axis` 转 `deg` 度。"""
    if not deg:
        return v.copy()
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    cross = axis.cross(v)
    dot = axis.dot(v)
    return v * c + cross * s + axis * (dot * (1.0 - c))


def _lateral_dir(d, tilt):
    """返回来向 `d` 对应的侧向单位方向 `n`，`tilt` 控制随纬度的倾斜量。

    `d` 与竖直轴平行时侧向平面退化，返回 `_FRONT`。
    """
    e = _UP.cross(d)
    e_len = e.length()
    if e_len < 1e-6:          # d 与竖直轴平行：两个基均退化，侧向平面为整个水平面
        return _FRONT.copy()
    e = e * (1.0 / e_len)
    b = (d * d.dot(_UP) - _UP).normalized(fallback=_FRONT)
    phi = tilt * d.dot(_UP)
    return (e * math.cos(phi) + b * math.sin(phi)).normalized(fallback=e)


def _rotate_toward(cur, goal, max_rad, tilt):
    """将单位方向 `cur` 向 `goal` 旋转，每帧至多 `max_rad` 弧度，返回新的单位方向。

    夹角不超过 `max_rad` 时直接对准。两者反向平行时旋转轴由 `_lateral_dir(cur, tilt)` 确定。
    """
    if max_rad <= 0.0:
        return cur.copy()
    c = cur.dot(goal)
    if c > 1.0:
        c = 1.0
    elif c < -1.0:
        c = -1.0
    ang = math.acos(c)
    if ang <= max_rad:
        return goal.copy()
    axis = cur.cross(goal)
    if axis.length() < 1e-9:                  # 反向平行：本帧正越过目标
        axis = cur.cross(_lateral_dir(cur, tilt))
    axis = axis.normalized(fallback=_FRONT)
    return _rotate_axis(cur, axis, math.degrees(max_rad)).normalized(fallback=cur)


@register(HOMING)
class Homing(Behavior):
    """FORCE 阶段写入 p.vel，位移由 VELOCITY3D 积分。"""

    STAGE = FORCE
    #: 必须排在 EMITTERSHAPE3D 之后，原因见模块 docstring。
    ORDER = 60

    def on_emitter_init(self, em, rng):
        f = em.f(HOMING)
        if f is None:
            return
        mode = f.i("homingTarget") % 4
        if mode == 1:
            em.note("HOMING.homingTarget=Model Origin：预览没有角色模型根节点数据，"
                    "近似取宿主上报的发射器位置（host_origin，不含本地漂移）")
        elif mode in (2, 3):
            em.note("HOMING.homingTarget=World Origin：预览没有地图坐标数据，"
                    "近似取本次模拟坐标系的原点")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(HOMING, p)
        if f is None:
            return

        target_mode = f.i("homingTarget") % 4
        ff_mode = f.i("forceFieldMode")
        ff_radius = f.get("forceFieldRadius")

        target = self._target(target_mode, em)
        if ff_mode == FF_CULL_INSIDE:
            if (p.pos - target).length() < ff_radius:
                p.alive = False       # 球内出生剔除
                return

        fps = max(1, em.config.fps)
        p.user[Homing] = {
            "target_mode": target_mode,
            # 第一帧取 VELOCITY3D 的初速度
            "speed": None,
            "accel": f.get("acceleration") / fps,
            "max_speed": max(0.0, f.get("maxSpeed")),
            "turn_step": math.radians(f.get("turnRate")) / fps,
            "vanished": False,
            "vanish_mode": f.i("vanishMode"),
            "vanish_radius": f.get("vanishRadius"),
            "ff_mode": ff_mode,
            "ff_radius": ff_radius,
            "ff_scale": f.get("forceFieldSpeedScale", 1.0),
            "ff_recover_frames": max(1.0, em.config.homing_ff_recover_frames),
            "ff_damp": 1.0,
            "lateral_tilt": em.config.homing_orbit_lateral_tilt,
        }

    def on_particle_step(self, p, em):
        st = p.user.get(Homing)
        if st is None:
            return

        target = self._target(st["target_mode"], em)
        to_target = target - p.pos
        dist = to_target.length()

        if (not st["vanished"] and st["vanish_mode"] != VANISH_NONE
                and dist <= st["vanish_radius"]):
            st["vanished"] = True
            if st["vanish_mode"] == VANISH_CANCEL_INFINITE:
                p.rolled["life_indefinite"] = False
            elif st["vanish_mode"] == VANISH_IMMEDIATE:
                p.alive = False
                return

        inside_ff = dist <= st["ff_radius"]
        freeze_turn = inside_ff and st["ff_mode"] == FF_NO_TURN_INSIDE
        #: 本帧是否按 forceFieldSpeedScale 减速（球内减速或球外减速）
        ff_slow = ((inside_ff and st["ff_mode"] == FF_SLOW_INSIDE)
                   or (not inside_ff and st["ff_mode"] == FF_SLOW_OUTSIDE))

        turn_step = st["turn_step"]
        speed = st["speed"]
        if speed is None:
            speed = min(p.vel.length(), st["max_speed"])
        else:
            speed = max(0.0, min(st["max_speed"], speed + st["accel"]))
        st["speed"] = speed

        # 场内 ff_damp *= k；每帧（含场外）ff_damp += 1/recover_frames
        damp = st["ff_damp"]
        if ff_slow:
            damp *= st["ff_scale"]
        damp = min(1.0, damp + 1.0 / st["ff_recover_frames"])
        st["ff_damp"] = damp

        direction = self._pursue(st, p, to_target, dist,
                                 0.0 if freeze_turn else turn_step)
        # 方向由上一帧总速度旋转而来，已包含其它速度来源，直接赋值即完成合成
        p.vel = direction * (speed * damp)

    # ── 内部 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _pursue(st, p, to_target, dist, turn_step):
        """执行一帧纯追踪，返回新的速度方向。"""
        goal = to_target * (1.0 / dist) if dist > 1e-9 else None
        cur = p.vel.normalized(fallback=(goal if goal is not None else _FRONT))
        if goal is None:
            goal = -cur          # 恰位于目标点：视为刚越过目标，由退化分支确定转向
        return _rotate_toward(cur, goal, turn_step, st["lateral_tilt"])

    @staticmethod
    def _target(mode, em):
        """归航目标的**实时**位置，而非触发时固定的位置。"""
        if mode == 1:
            return em.host_origin.copy()
        if mode in (2, 3):
            return Vec3()
        return em.origin.copy()
