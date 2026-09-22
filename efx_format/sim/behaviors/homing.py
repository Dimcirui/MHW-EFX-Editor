# -*- coding: utf-8 -*-
"""HOMING —— 归航：粒子追踪目标，先直线接近，越过目标后绕其做圆周运动。

HOMING 的运动模型为纯追踪（`SimConfig.homing_compose='pursuit'`，实现见 `Homing._pursue`）：

    速度方向每帧向「指向目标」的方向旋转 turnRate/fps 度；速度大小由 initialSpeed 与
    targetSpeed 单独决定。

`turnRate` 为角速度，单位度/秒（360 即每秒一圈）。已确认的单粒子行为均可由该模型导出，
不构成独立机制：

    · 直线接近      V3D 初速度为 0 时，初始方向即指向目标，轨迹为直线。
    · 切圆轨道      粒子越过目标时，「指向目标」的方向翻转 180°，而速度方向每帧至多旋转
                    turnRate，故方向连续变化，轨迹为半径 r = v/ω 的圆。目标点是该圆的切点，
                    圆心位于侧向，而非目标点。
    · 轨道稳定      圆经过目标点时，由弦切角定理，「指向目标」的方向以 ω/2 旋转；粒子以 ω
                    追随，每一整圈恰好回到目标点一次。因此该切圆是追踪方程的不变集。
    · 速度为设定值  轨道直径与出生距离无关，说明速度大小由参数设定，而非累积所得。

在纯追踪模型下，其它速度来源自然参与合成：V3D 初速度决定初始方向，重力逐帧改变方向，
speedCoef 缩放当帧输出。本 behavior 在 FORCE 阶段只写 `p.vel`，位移由 VELOCITY3D 在
INTEGRATE 阶段积分，故 HOMING 依赖同一 entry 中的 VELOCITY3D（其字段可全为 0）。
`'add'` 与 `'override'` 是已排除的两种合成方式，启用时退回 approach / orbit 两段状态机，
仅供对照。

模型唯一的奇异点是速度方向与「指向目标」反向平行，即粒子越过目标的瞬间：此时旋转轴无定义，
转向由 `_lateral_dir` 的约定决定。该约定是本模块中尚未确认的部分，
`SimConfig.homing_orbit_lateral_tilt` 的取值亦无实测依据。奇异点邻域的条件数很差，旋转轴对
横向分量极为敏感，因此速度含有 Y 分量时会出现进动。

转向约定的构造：轨道段的闭式解为

    p(θ) = r·sinθ·d + r·(1-cosθ)·n        θ=180° 时 p = 2r·n

其中 `d` 为来向、`n` 为侧向单位方向、圆心位于 `p + r·n`。因此半周期时粒子群的形状与质心完全
由 `n` 在出生球壳上的分布决定，质心为 2r·mean(n)。`n` 必须是 `d` 的奇函数，否则在球壳上求和
不相抵消，粒子群整体向一侧偏移。`_lateral_dir` 取侧向平面的两个基 `e = normalize(U × d)`
（奇函数，水平）与 `b`（偶函数），令

    n = cos(φ)·e + sin(φ)·b        φ = tilt·(d·U)

φ 取奇标量 `d·U`，保证 `n` 整体为奇函数，从而 `mean(n) ≡ 0`；这一性质由构造保证，与参数取值
无关。赤道处 φ=0（纯水平），越靠近两极越向 `b` 倾斜，且处处连续。`tilt` 只影响竖直方向的
压缩程度：取 0 时半周期压缩为平面，取 1.0 时竖直与水平尺寸之比约为 0.46，取 2.0 时约为 0.75。

逐粒子轨道半径：闭式解 `|p(θ)| = 2r·|sin(θ/2)|` 与旋转轴无关，故若 r 对所有粒子相同，粒子群
在任意时刻都位于同一球面上，任何转轴规则都无法产生各向异性。要使半周期时的粒子群在竖直方向
压缩，r 必须因粒子而异。`_orbit_speed_scale` 在进入轨道时仅保留垂直于世界 Y 的速度分量，
`v' = v·|incoming × Y|`，由 `SimConfig.homing_orbit_axial_falloff` 控制插值强度。强度为 1 时，
恰好生成于竖直轴两极的粒子系数为 0，到达中心后静止、不再绕行。

两段状态机（`'add'` / `'override'`）进入轨道时，方向同样连续：速度获得一个与来向垂直的侧向
（向心）分量，使直线轨迹弯曲为圆，而非将速度方向原地旋转 90°。后者会使轨迹在目标点形成尖角，
且圆位于来向一侧。方向连续时，圆在目标点与来向相切，圆心位于侧向 `r·n` 处，速度大小不变。

速度大小：

    初始速度 = min(initialSpeed, targetSpeed)；任一为 0 时粒子保持静止（`locked`）。
    initialSpeed 大于 targetSpeed 时不起作用，即速度上限由 targetSpeed 限定。
    进入轨道后速度线性增至 targetSpeed：每帧增量固定，按初始差值计算，历经
    `SimConfig.homing_speed_ramp_turns` 圈（默认 4）完成。半径 r = v/ω 随之线性增长，
    轨迹为等距螺旋。增长过程的圈数固定，而非加速度固定：差值减半时圈数不变。

归航目标 `homingTarget`（取模 4）在核心层的对应量：

    0 生成点      em.origin，即发射器的实时位置；逐帧读取，不在 spawn 时固定
    1 模型原点    em.host_origin，即宿主上报的发射器位置，不含本地 TRANSFORM3D 漂移
    2/3 世界原点  本模拟坐标系原点 (0,0,0)，而非 Blender 场景的世界原点

仅取值 0 为精确对应；1 与 2/3 为近似，`on_emitter_init` 会为此记录 note。

力场与消失判定均以目标为球心，半径分别为 `forceFieldRadius` 与 `vanishRadius`：

    forceFieldMode 1/3   在球内生成的粒子直接剔除；取 3 时，球内另外冻结转向
    forceFieldMode 2/4   在球内（2）或球外（4）按 forceFieldSpeedScale=k 减速。默认采用
                         'balanced' 模型：每帧先乘 k，再加固定增量 c = targetSpeed/48 回升，
                         平衡速度为 v* = min(targetSpeed, c/(1-k))
    vanishMode 1         进入消失球时触发一次，取消无限寿命。LIFE 的寿命计时自出生起持续，
                         故效果并非立即消失
    vanishMode 2         进入消失球时触发一次，粒子立即消失

维护约束：
- approach 段必须以初始速度匀速直线运动，不参与线性增速，也不乘 `orbit_scale`。该段速度决定
  等距生成的粒子能否同时到达中心；一旦缩放，各粒子的到达时刻错开，收缩点随之发散。
- 'balanced' 模型的减速必须记录在独立的阻尼因子 `ff_damp` 上，不得写入 `speed`。`speed` 承载
  initialSpeed→targetSpeed 的慢速增长（约 4 圈）；若约 48 帧的快速回升作用于 `speed`，将完全
  覆盖增长过程，螺旋在数十帧内即告结束。
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

#: 每圈收敛的比例（1 - e⁻¹），供 'per_revolution' 使用；为经验取值，无实测依据。
_CONVERGE_PER_TURN = 1.0 - math.exp(-1.0)


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


def _rotate_toward(cur, goal, max_rad, tilt, handed):
    """将单位方向 `cur` 向 `goal` 旋转，每帧至多 `max_rad` 弧度，返回新的单位方向。

    夹角不超过 `max_rad` 时直接对准。两者反向平行时旋转轴由 `_lateral_dir(cur, tilt)` 确定，
    `handed` 为手性符号。
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
        n = _lateral_dir(cur, tilt)
        axis = cur.cross(n) * handed
    axis = axis.normalized(fallback=_FRONT)
    return _rotate_axis(cur, axis, math.degrees(max_rad)).normalized(fallback=cur)


def _orbit_axis(incoming, mode, handed=1.0, tilt=1.0):
    """两段状态机中 orbit 阶段使用的旋转轴。

    默认 `'lateral_tilt'` 取 `d × n`，逐帧绕其旋转即使轨迹向 `n` 一侧弯曲；其余三档仅供对照，
    均有已知缺陷。
    """
    if mode == "lateral_tilt":
        d = incoming
        n = _lateral_dir(d, tilt)
        axis = d.cross(n).normalized(fallback=_FRONT)
        return axis * handed
    if mode == "world_up":
        # 全体共用一根固定轴：旋转只作用于垂直于该轴的两个维度，沿轴分量须由
        # on_particle_step 中的独立回拉项处理
        if abs(incoming.dot(_UP)) > 0.999:
            return _FRONT.copy()
        return _UP.copy()
    if mode == "world_front":
        return _FRONT.copy()
    # 'offset_up'：来向与世界 Y 平行时退化。回退轴不得取 _UP，否则 axis 与 incoming 平行，
    # 旋转退化为恒等变换，粒子将直线穿过目标
    axis = (-incoming).cross(_UP)
    axis = axis.normalized(fallback=_FRONT)
    return axis * handed


def _orbit_speed_scale(incoming, strength):
    """返回进入轨道时的速度系数 `1 - strength·(1 - |incoming × Y|)`，即逐粒子轨道半径系数。

    `strength` 不大于 0 时恒返回 1。
    """
    if strength <= 0.0:
        return 1.0
    perp = incoming.cross(_UP).length()
    if perp > 1.0:
        perp = 1.0
    return 1.0 - strength * (1.0 - perp)


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
        if ff_mode in (FF_CULL_INSIDE, FF_NO_TURN_INSIDE):
            if (p.pos - target).length() < ff_radius:
                p.alive = False       # 球内出生剔除
                return

        fps = max(1, em.config.fps)
        turn_rate = f.get("turnRate")
        initial_speed = f.get("initialSpeed")
        target_speed = f.get("targetSpeed")

        # 初始速度以 targetSpeed 为上限。轨迹先扩张后收缩是轨道几何本身的周期变化
        # （|p|=2r·sin(θ/2)），与速度收敛无关，不构成否定上限的依据
        locked = initial_speed <= 0.0 or target_speed <= 0.0
        start_speed = min(initial_speed, target_speed)
        turn_step_rad = math.radians(turn_rate) / fps
        p.user[Homing] = {
            "target_mode": target_mode,
            "speed": 0.0 if locked else start_speed,
            "target_speed": target_speed,
            "locked": locked,
            "turn_step": turn_step_rad,
            "phase": "approach",
            "dir": None,
            "axis": None,
            # 转轴手性。实机中手性固定：连续发射的轨迹是一条连续曲线，随机手性会使同一
            # 生成点的粒子分成互为镜像的两组
            "handed": 1.0 if em.config.homing_orbit_handed == "fixed"
                      else (1.0 if rng.random() < 0.5 else -1.0),
            # 逐粒子轨道半径系数，在到达目标的那一帧确定；approach 段不得使用
            "orbit_scale": 1.0,
            "axial_falloff": em.config.homing_orbit_axial_falloff,
            "turn_mode": em.config.homing_orbit_retarget,
            "since_turn": 0,
            "turns_done": 0,
            # 绕行一整圈所需的帧数，作为重新定轴的触发阈值
            "turn_min_frames": max(2, int(round(2.0 * math.pi / abs(turn_step_rad))))
                               if turn_step_rad else 2,
            "vanished": False,
            "vanish_mode": f.i("vanishMode"),
            "vanish_radius": f.get("vanishRadius"),
            "ff_mode": ff_mode,
            "ff_radius": ff_radius,
            "ff_scale": f.get("forceFieldSpeedScale", 1.0),
            "ff_scale_mode": em.config.homing_ff_scale_mode,
            "ff_recover_frames": max(1.0, em.config.homing_ff_recover_frames),
            "ff_damp": 1.0,
            "converge": em.config.homing_speed_converge,
            # 供 'linear' 使用：增量按初始差值计算；若按剩余差值计算，则退化为指数逼近
            "initial_speed": 0.0 if locked else start_speed,
            "ramp_turns": max(1e-6, em.config.homing_speed_ramp_turns),
            "axis_mode": em.config.homing_orbit_axis,
            "lateral_tilt": em.config.homing_orbit_lateral_tilt,
            "axis_update": em.config.homing_orbit_axis_update,
            "compose": em.config.homing_compose,
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

        # 自由速度（V3D 初速度、重力累积与 speedCoef 衰减）仅在 'add' 下显式相加
        free = p.vel_free if st["compose"] == "add" else Vec3()

        turn_step = st["turn_step"]
        frac = min(1.0, (abs(turn_step) / (2.0 * math.pi)) * _CONVERGE_PER_TURN) \
            if turn_step else 0.0

        speed = st["speed"]
        tgt_speed = st["target_speed"]
        if not st["locked"] and speed != tgt_speed:
            if st["converge"] == "instant":
                speed = tgt_speed
            elif st["converge"] == "linear":
              # 阶段判据必须位于此层：若写作 `elif linear and phase=="orbit"`，approach 段
              # 将落入下方 else 分支，执行指数收敛
              if st["phase"] == "orbit":
                  # 仅在 orbit 段增速，增速圈数按轨道圈数计。每帧增量 = 初始差值 /
                  # (增速圈数 × 每圈帧数)。初始速度已限定为 min(initialSpeed, targetSpeed)，
                  # 故 span 恒 ≥ 0，只增不减
                  span = tgt_speed - st["initial_speed"]
                  step = span * (abs(turn_step) / (2.0 * math.pi)) / st["ramp_turns"]
                  speed += step
                  if speed > tgt_speed:
                      speed = tgt_speed
            else:                      # 'per_revolution'：可双向收敛
                speed += (tgt_speed - speed) * frac
        # 'per_frame'：forceFieldSpeedScale 逐帧乘入内部速度状态，按几何级数累积
        if ff_slow and st["ff_scale_mode"] == "per_frame":
            speed *= st["ff_scale"]
        st["speed"] = speed

        # 'balanced'：减速记录在独立的 ff_damp 上，不得写入 speed（见模块 docstring）。
        #   场内 ff_damp *= k；每帧（含场外）ff_damp += 1/recover_frames
        #   平衡点 f* = min(1, c/(1-k))，c = 1/recover_frames
        if st["ff_scale_mode"] == "balanced":
            damp = st["ff_damp"]
            if ff_slow:
                damp *= st["ff_scale"]
            damp = min(1.0, damp + 1.0 / st["ff_recover_frames"])
            st["ff_damp"] = damp

        if st["compose"] == "pursuit":
            direction = self._pursue(st, p, to_target, dist,
                                     0.0 if freeze_turn else turn_step)
        elif st["phase"] == "approach":
            # 以合速度在目标方向上的分量判断本帧是否到达或越过目标。自由速度指向外侧时
            # closing 减小甚至为负，粒子应始终无法到达目标
            closing = speed + free.dot(to_target * (1.0 / dist)) if dist else speed
            if dist <= max(closing, 1e-6):
                # 到达时转入 orbit。来向必须取上一帧记录的 st["dir"]，不得取本帧的 to_target：
                # 生成距离恰为 speed 的整数倍时残差为 0，所有粒子将落入同一退化回退值，
                # 统一偏向同一方向
                incoming = st["dir"] if st["dir"] is not None \
                    else to_target.normalized(fallback=_FRONT)
                direction = self._turn(st, incoming)
                st["phase"] = "orbit"
            else:
                direction = to_target.normalized(fallback=_FRONT)
                if not freeze_turn:
                    st["dir"] = direction
                else:
                    direction = st["dir"] if st["dir"] is not None else direction
        else:                          # orbit
            st["since_turn"] += 1
            # 'once_more'：绕行第一圈后，以当前速度方向为新的来向重新定轴一次，此后固定。
            # 「恰好两次」为观测现象，成因未知
            may_return = (st["turn_mode"] == "every_pass"
                          or (st["turn_mode"] == "once_more"
                              and st["turns_done"] < 2))
            if (may_return and not freeze_turn and st["turn_step"]
                    and st["since_turn"] >= st["turn_min_frames"]):
                # 以累计转角满一圈为触发条件，而非「距目标一帧以内」：离散采样不能保证每圈
                # 都落入该范围
                direction = self._turn(st, st["dir"])
            else:
                direction = st["dir"]
                if not freeze_turn and st["turn_step"]:
                    # 'frozen' 始终绕到达时确定的轴旋转；'live' 每帧按当前速度方向重新计算
                    # 转轴，速度含 Y 分量时轨道平面发生进动
                    axis_now = (_orbit_axis(direction, st["axis_mode"],
                                            st["handed"], st["lateral_tilt"])
                                if st["axis_update"] == "live" else st["axis"])
                    direction = _rotate_axis(direction, axis_now,
                                            math.degrees(st["turn_step"]))
                st["dir"] = direction

        # 仅 orbit 段按逐粒子系数缩放；approach 段保持原速，以保证粒子同时到达中心
        vel = direction * (speed * st["orbit_scale"]
                           if st["phase"] == "orbit" else speed)

        if st["compose"] != "pursuit" and st["phase"] == "orbit" and not freeze_turn:
            # 绕固定轴旋转不改变沿轴分量，沿轴偏移将保持不变；此处按 frac 的速率将其回拉至 0。
            # 回拉强度未经实测，仅为最小修补
            axis = st["axis"]
            axial_offset = (p.pos - target).dot(axis)
            if axial_offset:
                vel = vel - axis * (axial_offset * frac)

        # 'output' 仅缩放当帧输出；'per_frame' 已在上方累积至 st["speed"]
        if st["ff_scale_mode"] == "output" and ff_slow:
            vel = vel * st["ff_scale"]
        elif st["ff_scale_mode"] == "balanced":
            vel = vel * st["ff_damp"]
        # 'pursuit' 的方向由上一帧总速度旋转而来，已包含其它速度来源，直接赋值即完成合成；
        # 仅 'add' 需要显式相加
        p.vel = free + vel if st["compose"] == "add" else vel

    # ── 内部 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _pursue(st, p, to_target, dist, turn_step):
        """执行一帧纯追踪，返回新的速度方向，并更新 `st` 的 phase、axis、orbit_scale 与 dir。

        `phase` 仅用于控制速度增长与 `orbit_scale`，以**转向饱和**为切换判据：可对准目标时转角
        不超过 turn_step（直线接近段恒为 0），无法对准即表明已越过目标。
        """
        goal = to_target * (1.0 / dist) if dist > 1e-9 else None
        cur = p.vel.normalized(fallback=(goal if goal is not None else _FRONT))
        if goal is None:
            goal = -cur          # 恰位于目标点：视为刚越过目标，由退化分支确定转向
        if st["phase"] == "approach":
            c = cur.dot(goal)
            if c > 1.0:
                c = 1.0
            elif c < -1.0:
                c = -1.0
            if math.acos(c) > max(turn_step, 1e-9):
                st["phase"] = "orbit"
                st["turns_done"] += 1
                st["axis"] = cur.cross(goal).normalized(fallback=_FRONT)
                st["orbit_scale"] = _orbit_speed_scale(cur, st["axial_falloff"])
        direction = _rotate_toward(cur, goal, turn_step, st["lateral_tilt"],
                                   st["handed"])
        st["dir"] = direction
        return direction

    @staticmethod
    def _turn(st, incoming):
        """两段状态机中进入轨道：按 `incoming` 确定转轴，返回进入 orbit 当帧的方向。

        同时重置 `st` 的转轴、计数与轨道半径系数。首次到达与此后的重新定轴均调用本函数。
        """
        axis = _orbit_axis(incoming, st["axis_mode"], st["handed"],
                           st["lateral_tilt"])
        # 仅去除沿轴分量，不做 90° 旋转。逐粒子定轴时 axis 已与 incoming 垂直，此步为恒等
        # 变换；仅对固定轴的对照档起作用
        tangential = incoming - axis * incoming.dot(axis)
        direction = tangential.normalized(fallback=incoming)
        st["dir"] = direction
        st["axis"] = axis
        st["since_turn"] = 0
        st["turns_done"] = st.get("turns_done", 0) + 1
        st["orbit_scale"] = _orbit_speed_scale(incoming, st["axial_falloff"])
        return direction

    @staticmethod
    def _target(mode, em):
        """归航目标的**实时**位置，而非触发时固定的位置。"""
        if mode == 1:
            return em.host_origin.copy()
        if mode in (2, 3):
            return Vec3()
        return em.origin.copy()
