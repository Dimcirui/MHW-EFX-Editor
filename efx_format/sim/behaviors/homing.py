# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/homing.py  —  HOMING（归航：径直飞向目标→绕目标转圈）

运动学模型来自 memory `homing-orbit-kinematics-model`（八角探针 2026-07-30 实测坐实），
FORCE 阶段：本 behavior 只写 `p.vel`（方向 + 大小），真正的位移仍由 VELOCITY3D 在
INTEGRATE 阶段用 `p.pos += p.vel` 完成——这也是为什么 HOMING 硬依赖同 entry 的
VELOCITY3D（哪怕字段全 0）：没有它就没有谁把这份速度积成位移。

单粒子行为（已实测坐实，不是本文件的猜测）
------------------------------------------
    ① approach：从生成位置**径直飞向**目标，这一段是直线，不转弯。
    ② 到达目标的瞬间（本帧位移会追上/越过目标），速度获得一个与来向**垂直（90°）**
       的分量，转入 orbit。⚠ 这是一记**侧向（向心）力**，**方向在这里是连续的**——
       不是「把速度方向就地旋转 90°」。曾经实现成后者，2026-09-12 用户看 Blender
       预览当场指出两处硬伤：轨迹在原点成了锐角拐点（实机是光滑的），且圆心被放在
       `-r·d` 上、整个圆挂在来向那一侧（实机是**原点为圆的切点、圆在侧向那一边**）。
       详见 `_turn` 的 docstring。
    ③ orbit：之后 `p.vel` 的方向每帧固定绕同一根轴转 turnRate 度/秒
       （`turnRate` 是**角速度**，360 实测正好每秒一圈），大小仍是当前速度——
       匀速圆周运动下这就等价于半径 r = v / ω 的圆，圆**与来向相切于目标点**
       （圆心在侧向 r 处，不是以目标为圆心）。
    ④ 起手速度 = **min(initialSpeed, targetSpeed)**，然后**线性**爬向 targetSpeed，
       半径 r=v/ω 跟着变，于是画出螺旋。任一为 0 → 全程不动（`locked` 单独锁死）。
       2026-09-12 用户用 initialSpeed 0.1/0.5/0.9/1.0 四组游戏实拍逐项标定：
         · 形状 = **等距螺旋**（每圈径向增量恒定）⇒ 速度**线性**爬升，每帧加固定
           增量，按**原始**差值算。按剩余差值算会退化成指数逼近，那给出的是
           "起手半径大、间距逐圈变小"，与实拍正好相反。
         · **固定圈数，不是固定加速度**：0.1→1.0 与 0.5→1.0 **都是 4 圈**，差值
           减半而圈数不变（固定加速度的话应当只要 2 圈）。
           见 `SimConfig.homing_speed_ramp_turns`（默认 4）。
         · **initialSpeed > targetSpeed 时 initialSpeed 完全不起作用**：1.0→0.5 与
           0.9→0.1 都是「第一圈就已经是终态半径」，且圈的大小只随 targetSpeed 走。
           所以是**上限被钳住**，不是"降得快"。
       ⚠ 本会话曾一度把这条钳制当 bug 删掉，理由是用户说「扩张后还会再收缩」——
       **那是归因错了**：扩张再收缩是**轨道几何本身**（圆过目标点，
       `|p| = 2r·sin(θ/2)` 的呼吸，见 `_lateral_dir` 的闭式解），跟速度收敛无关。
       最早那份文档写的「上限被 targetSpeed 钳住」一直是对的。

仍是猜的部分（standalone 的 SimConfig 开关，别当成结论）
--------------------------------------------------------
侧向力往哪边推（等价地：绕哪根轴转）——2026-09-12 一天内改判了四版，**当前 default
是第四版 `'lateral_tilt'`**，见 `_lateral_dir`。前三版的坑都别重踩：

- **第一版**（逐粒子定轴，无手性修正）：数学上可证明 `cross(offset, UP)` 这个公式
  对任意来向算出来的转向 Y 分量恒为 `-h`（h=来向水平分量长度，恒≥0）——不是「看似
  有偏，实测微弱」，是结构性、不会均值抵消的系统偏置。Blender 预览里全体粒子一起
  偏向 -Y，用户截图实锤。
- **第二版**（全体共用一根固定轴，如世界 +Y）：为了解释用户甩出的游戏内实拍——过
  中点前后整片"经线"阵列**整体**产生一个方向的偏转，偏转量画面视觉中心大、边缘
  小（刚体绕单一固定轴转动配透视投影的经典签名）——改成全体共用同一根轴。但**绕
  固定轴转在数学上只能碰垂直于该轴的两维，沿轴那一维摸不到**：要么放着不管，到达
  那一刻速度沿轴的分量（等于 incoming 沿轴那份，旋转不改变它）逐帧原样叠加进
  p.vel，沿轴位置无界发散（600 帧从十几涨到一百多，用户反馈"某根轴上完全看不到
  收缩"）；补一条独立回拉硬把偏移拉回 0 又会让**全体粒子摊死在同一张平面上**，
  用户反馈"过中心点后完全只在一个平面里动"——两个方向都不对，是这个「共用一根
  固定轴」架构本身的死结，不是回拉强度没调好。
- **第三版（当前）**：退回逐粒子定轴，但加一个出生时抽好的 ±1 手性抵消第一版的
  系统偏置。不同粒子的轴方向天然不同，群体在离散帧上才会有立体感——不会像"全体
  共用一根轴"那样把每个粒子的运动摊死在同一张平面里，也不会有"沿轴分量摸不到"
  这个第二版专属的结构性问题（本粒子的 incoming 本来就与本粒子的 axis 垂直，
  90° 转向天然落在这根轴的垂直面内，不需要额外投影/回拉）。`on_particle_step`
  里那条"轴向回拉"代码保留着（对 `'world_up'`/`'world_front'` 这两个留作对照的
  legacy 模式仍然需要），对默认的 `'offset_up'` 是近似 no-op。

- **第四版（当前 default，`'lateral_tilt'`）**：第三版的随机手性被用户的连续喷射
  实拍证伪（整条轨迹是一条干净曲线，抛硬币必然劈成镜像两族），改回固定手性后
  第一版那个偏置就回来了——根因是这些公式算出来的侧向方向 `n` 对 `d → -d` 是
  **偶**的，球壳上求和不抵消（实测 θ=180° 时质心 Y=-59，而整团竖直尺寸才 70）。
  第四版直接从这个约束出发构造：`n = cos(φ)·e + sin(φ)·b`，`φ = tilt·(d·Y)`，
  φ 取奇标量 ⇒ `n` 整体为奇 ⇒ `mean(n) ≡ 0`（实测漂移 0.00000，是结构性的），
  且处处连续。详见 `_lateral_dir`。

真正的规则到底是什么——还是未确认。第四版只是「满足当前全部已知约束里最简单的
那个」：方向连续、原点是切点、半径恒为 v/ω、零净漂移、半周期竖直压扁。倾斜量
`tilt` 本身（默认 1.0）**没有实测依据**，需要拿实拍标定。另一条一直没挖的线索是
pure pursuit（连续追踪目标方向、每帧最多转 turnRate），它能让"到达时的垂直偏转"
和"稳定绕圈"都变成连续物理的自然结果而不是硬编码的两阶段状态机，值得以后再试。
用户 2026-09-12 还观察到「粒子不是直接进入切线轨道，转向时略微外偏」——那条线索
尚未解释，很可能与"转两圈"现象同源。

归航目标（homingTarget，实测 mod 4：0=生成点 1=模型原点 2/3=世界原点，见
annotations.py）在核心层的落点
--------------------------------------------------------------------
本层没有「角色模型根节点」「地图坐标」这些游戏侧概念，只能用模拟里已有的量近似：
    0 生成点   → em.origin（发射器的**实时**位置——annotations 原话「不是触发时
                捕获定住」，故逐帧重新取，不在 spawn 时冻结）
    1 模型原点 → em.host_origin（宿主上报的发射器位置，不含本地 TRANSFORM3D 漂移；
                没有角色骨架数据时能给出的最接近「所在模型」的量）
    2/3 世界原点 → 本模拟坐标系的 (0,0,0)（不是 Blender 场景世界原点——那需要宿主
                侧的参考矩阵换算，核心层拿不到）
1/2/3 都是近似，`on_emitter_init` 记一条 note 说明，0（83% 官方用值）是精确的。

力场（forceFieldMode）与消失（vanishMode）
-------------------------------------------
以目标为球心、`forceFieldRadius`/`vanishRadius` 为半径的两个独立球体：
    forceFieldMode 1/3   球内**出生**的粒子直接剔除（3 额外在球内冻结转向，即
                        orbit 阶段停止绕轴旋转、approach 阶段停止重新瞄准）
    forceFieldMode 2/4   球内/外用 forceFieldSpeedScale=k 减速。
                        **'balanced'（默认，已按实拍标定）**：每帧先乘 k、再加一个
                        **固定绝对增量** c=targetSpeed/48 把速度往回拉，平衡点
                            v* = min(targetSpeed, c/(1-k))
                        2026-09-12 用户扫 k=0.99/0.95/0.9/0.8/0.5 量轨道直径得
                        24:8:4:2:1，本式给出 24:10:5:2.5:1——两个端点精确命中，
                        k=0.99 的 24 正是**撞到 targetSpeed 上限**（纯 1/(1-k) 外推
                        会给 50）。另两档已被同一组数据证伪，仅留作对照：
                        'output'（只缩放当帧输出）给出直径**正比于 k**，
                        即 1.98:1.9:1.8:1.6:1，差一个数量级；
                        'per_frame'（纯累积、无回拉）让粒子**冻死**，图案尺寸恒为 0，
                        且停在 20-v/(1-k) 处（实测与理论差 <2%）。
    vanishMode 1        进入 vanish 球触发一次：`p.rolled['life_indefinite']=False`
                        —— LIFE 的寿命计时器从出生就在跑、没有被重置，效果是
                        「取消无限寿命」而不是立即刀口式砍死（见 memory
                        velocity3d-speedcoef-is-global-damping 的死结分析同源）
    vanishMode 2        进入 vanish 球触发一次：`p.alive = False`（立即消失）

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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

#: 一圈收敛掉的比例（1 - e⁻¹），'per_revolution' 用；纯经验选择，无实测依据。
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
    """侧向（向心）单位方向 `n`：粒子到达目标后被这记侧向力弯成圆，圆心在 `p + r·n`。

    为什么需要专门构造：新运动学（方向连续、原点是圆的切点）的闭式解是

        p(θ) = r·sinθ·d + r·(1-cosθ)·n      ⇒  θ=180° 时 p = 2r·n

    所以**半周期的整团形状与质心，完全由 `n` 在出生球壳上的分布决定**：
    质心 = 2r·mean(n)，竖直压扁 = {n} 的竖直/水平尺寸比。

    旧公式 `n = cross(cross(来向,Y), 来向)` 一类的问题是它对 `d → -d` 是**偶**的，
    球壳上求和不抵消：展开成 `n = cosψ·m - sinψ·U`（`d = cosψ·U + sinψ·m`），
    `n·U = -sinψ ≤ 0` 恒成立 —— 整团一起往下滑（实测 θ=180° 时质心 Y=-59，
    而整团竖直尺寸才 70），正是用户最早反馈的「全都往 -Z 走，+Y 一个都没有」。

    这里改成**构造上就是奇的**：取侧向平面的两个基 `e = normalize(U × d)`（奇、水平）
    与 `b`（偶），令 `n = cos(φ)·e + sin(φ)·b`，其中 `φ = tilt·(d·U)` —— φ 取 `d·U`
    这个**奇标量**保证整体为奇 ⇒ `mean(n) ≡ 0`（实测各 tilt 下漂移都是 0.00000，
    是结构性的不是调出来的）。赤道处 φ=0（纯水平），越靠两极越往 `b` 倾斜，
    **处处连续**——不像按半球翻手性那种做法会在赤道留一道缝。

    `tilt` 只控制压扁程度，不影响零漂移：0→半周期压成纯平面，1.0→竖直/水平≈0.46，
    2.0→≈0.75。默认 1.0（`SimConfig.homing_orbit_lateral_tilt`），量本身未实测。
    """
    e = _UP.cross(d)
    e_len = e.length()
    if e_len < 1e-6:          # d 与竖直轴平行：两个基都退化，侧向平面是整个水平面
        return _FRONT.copy()
    e = e * (1.0 / e_len)
    b = (d * d.dot(_UP) - _UP).normalized(fallback=_FRONT)
    phi = tilt * d.dot(_UP)
    return (e * math.cos(phi) + b * math.sin(phi)).normalized(fallback=e)


def _orbit_axis(incoming, mode, handed=1.0, tilt=1.0):
    """orbit 阶段逐帧沿用的那根转轴。

    默认 `'lateral_tilt'`：先按 `_lateral_dir` 定出侧向方向 `n`，再取 `a = d × n`
    （于是 `a × d = n`，逐帧绕 `a` 转正好把直线弯向 `n` 那一侧）。
    `'offset_up'` 是上一版（`cross(来向, 世界 Y)`），有已证实的整团下滑偏置，留作对照。
    """
    if mode == "lateral_tilt":
        d = incoming
        n = _lateral_dir(d, tilt)
        axis = d.cross(n).normalized(fallback=_FRONT)
        return axis * handed
    if mode == "world_up":
        # 全体共用一根固定轴。结构上只能碰垂直于该轴的两维，沿轴那一维永远只能
        # 被靠 on_particle_step 里的独立回拉项拉着走——留作对照，不建议默认用。
        if abs(incoming.dot(_UP)) > 0.999:
            return _FRONT.copy()
        return _UP.copy()
    if mode == "world_front":
        return _FRONT.copy()
    # 'offset_up'（默认）：来向与世界 Y 平行时退化——回退轴不能再用 _UP 本身，
    # 否则 axis 跟 incoming 平行，90° 转向公式又会退化成恒等变换（粒子径直穿过
    # 目标继续飞，见 on_particle_spawn 附近坑 2 的教训，同一个坑换了张脸）。
    axis = (-incoming).cross(_UP)
    axis = axis.normalized(fallback=_FRONT)
    return axis * handed


def _orbit_speed_scale(incoming, strength):
    """到达转弯时，**只有垂直于世界 Y 的那份速度分量参与转圈**的系数。

    轨道半径 `r = v / ω`，所以这个系数等价于逐粒子缩放轨道半径。由来是闭式解：
    轨道相的位置有解析式（`s` 为出生方向即 `-incoming`，`t = axis × incoming`
    与 `s` 正交，θ 为已转过的角度）

        p(θ) = r·(1-cosθ)·s + r·sinθ·t      ⇒  |p(θ)| = 2r·|sin(θ/2)|

    `|p|` 与转轴完全无关、逐粒子恒等，所以**只要 r 全体相同，整团粒子在任何时刻
    都严格落在同一个球面上，任何转轴规则都压不出各向异性**；而 θ=180° 时
    `p = 2r·s`，半周期的形状恒等于出生形状的等比放大。2026-09-12 用户给的游戏内
    差分序列里，出生是球壳、半周期那一格却明显被压成横条 —— 两条合起来只剩一个
    出口：**r 必须逐粒子不同**。取「转弯只保留垂直于竖直轴的速度分量」
    （`v' = v·|incoming × Y|`）能同时对上实拍的两头：半周期压扁、收缩两端不扁。

    `strength` 是插值强度（`SimConfig.homing_orbit_axial_falloff`）：0 完全关掉
    （退回全体同半径的旧行为），1 就是上面那条规则本身。⚠ strength=1 时正好生在
    竖直轴两极上的粒子系数为 0 —— 它们到达中心后就停在那儿不再转圈，这是规则的
    直接推论、不是 bug（实拍里中心那点亮斑与之相符）。
    """
    if strength <= 0.0:
        return 1.0
    perp = incoming.cross(_UP).length()
    if perp > 1.0:
        perp = 1.0
    return 1.0 - strength * (1.0 - perp)


@register(HOMING)
class Homing(Behavior):
    """FORCE 阶段：只写 p.vel，位移交给 VELOCITY3D 在 INTEGRATE 阶段积分。"""

    STAGE = FORCE
    #: 排在 EMITTERSHAPE3D（FORCE/ORDER=10）之后——出生剔除要看 ES3D 摆好之后的
    #: 真实生成位置，先跑到这里 ES3D 已经把 p.pos 从发射器原点挪到形状采样点了。
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

        # 「上限被 targetSpeed 钳住」是旧假说（八角探针只测过「相等→闭合圆」和
        # 「initialSpeed 更小→从小圈向外旋开」两种，从没测过 initialSpeed 更大的情况，
        # 「钳住」纯属过度引申）。2026-09-12 用户拿游戏实拍反证：扩张之后还会再收缩，
        # 只有 initialSpeed 不设上限、直接朝 targetSpeed 收敛（可以从大到小）才解释得
        # 通。「任一为 0→完全不动」这条是唯一保留的边界，用 locked 独立锁死，不再靠
        # min() 顺带实现。
        locked = initial_speed <= 0.0 or target_speed <= 0.0
        # ⚠ 起手速度被 targetSpeed **钳住上限**——2026-09-12 用户实拍坐实：
        # 1.0→0.5 与 0.9→0.1 都是「第一圈就已经是终态半径」，且圈的大小只跟
        # targetSpeed 走，initialSpeed 更大时完全不起作用。本会话早些时候曾把这条
        # 钳制当 bug 删掉，理由是用户说「扩张后还会再收缩」——**那是归因错了**：
        # 扩张再收缩是**轨道几何本身**（圆过目标点，|p|=2r·sin(θ/2) 的呼吸），
        # 与速度收敛无关。最早那份文档写的「上限被 targetSpeed 钳住」是对的。
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
            # 'offset_up' 模式专用：转轴手性。2026-09-12 用户拿**连续喷射**探针实拍
            # 坐实是**固定**的（整条轨迹是一条干净曲线；抛硬币必然把同一生成点出来的
            # 粒子劈成镜像两族），另外他单独描述竖直轴上的粒子「沿平面的左向」转，
            # 同样指向固定手性。'random' 是当初为了盖掉球壳生成下「全体往 -Z 甩」
            # 那个偏置加的权宜之计，现已证伪、降级成对照项（见 config.UNKNOWNS）。
            "handed": 1.0 if em.config.homing_orbit_handed == "fixed"
                      else (1.0 if rng.random() < 0.5 else -1.0),
            # 到达转弯时按来向算出来的轨道速度系数（= 逐粒子轨道半径系数）。approach
            # 段绝不能吃它：那一段的速度决定「同时到达中心」，一缩放各粒子就错开
            # 到达时刻，那个干净的收缩点会散掉。所以这里先留空，到达那一帧才定。
            "orbit_scale": 1.0,
            "axial_falloff": em.config.homing_orbit_axial_falloff,
            "turn_mode": em.config.homing_orbit_retarget,
            "since_turn": 0,
            "turns_done": 0,
            # 转满一整圈需要的帧数，当「再转一次弯」的触发门槛用。
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
            # 'linear' 用：起手速度（爬升增量按**原始差值**算，不按剩余差值——
            # 后者会退化成指数逼近），以及爬完全程要转几圈。
            "initial_speed": 0.0 if locked else start_speed,
            "ramp_turns": max(1e-6, em.config.homing_speed_ramp_turns),
            "axis_mode": em.config.homing_orbit_axis,
            "lateral_tilt": em.config.homing_orbit_lateral_tilt,
            "axis_update": em.config.homing_orbit_axis_update,
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
        #: 本帧「该被 forceFieldSpeedScale 减速」吗（球内减速 / 球外减速两种模式）
        ff_slow = ((inside_ff and st["ff_mode"] == FF_SLOW_INSIDE)
                   or (not inside_ff and st["ff_mode"] == FF_SLOW_OUTSIDE))

        turn_step = st["turn_step"]
        frac = min(1.0, (abs(turn_step) / (2.0 * math.pi)) * _CONVERGE_PER_TURN) \
            if turn_step else 0.0

        speed = st["speed"]
        tgt_speed = st["target_speed"]
        if not st["locked"] and speed != tgt_speed:
            if st["converge"] == "instant":
                speed = tgt_speed
            elif st["converge"] == "linear":
              # ⚠ 判据必须嵌在这一层里，不能写成 `elif linear and phase=="orbit"`：
              # 那样 approach 段会**掉进下面的 else 跑指数收敛**，等于没有 gate
              # （实测 0.1→1.0 只剩 3.05 圈）。
              if st["phase"] == "orbit":
                  # ⚠ 只在 orbit 段推进：用户数的「4 圈」是**轨道上的**圈数。若从出生就
                  # 开始爬，approach 段会先吃掉一截（initialSpeed 小时尤其明显，实测
                  # 0.1→1.0 只剩 3.44 圈）。approach 段保持 initialSpeed 匀速直线，
                  # 也顺带保住「等距生成的粒子同时到达中心」这条。
                  # 每帧加**固定**增量 = 原始差值 / (爬升圈数 × 每圈帧数)。
                  # 半径 r=v/ω 于是随时间线性增长 ⇒ **等距螺旋**（每圈的径向增量恒定）。
                  # 2026-09-12 用户拿 initialSpeed=0.1 的实拍标定：实机是等距螺旋、
                  # 起手半径很小，而 'per_revolution' 那条指数逼近给出的是「间距逐渐
                  # 变小、起手半径很大」，方向正好相反；两者的**总圈数**都是 ~4 圈，
                  # 所以当时错的是曲线形状不是时长。
                  # span 恒 ≥ 0：起手速度在 on_particle_spawn 就被钳成
                  # min(initialSpeed, targetSpeed)，所以只会往上爬，没有下行分支。
                  span = tgt_speed - st["initial_speed"]
                  step = span * (abs(turn_step) / (2.0 * math.pi)) / st["ramp_turns"]
                  speed += step
                  if speed > tgt_speed:
                      speed = tgt_speed
            else:                      # 'per_revolution'（可以从大朝小收敛，也可以反过来）
                speed += (tgt_speed - speed) * frac
        # forceFieldSpeedScale 的两种读法（`SimConfig.homing_ff_scale_mode`）：
        # 'per_frame'（默认）= 逐帧乘进**内部速度状态**，于是**几何累积**——scale<1
        #   时速度指数衰减、r=v/ω 跟着缩，粒子螺旋收进目标；scale>1 则发散。同格式里
        #   有同类先例：VELOCITY3D.speedCoef 就是逐帧乘粒子总速度的阻尼。
        # 'output'  = 只缩放**当帧输出**速度，不动内部状态，所以不累积（改动前的行为）。
        # ⚠ 与线性爬升的相互作用未实测：爬升每帧把 speed 往 targetSpeed 推、这里每帧
        #   往下乘，两者会在某个平衡点僵住，而不是一路衰减到 0。
        if ff_slow and st["ff_scale_mode"] == "per_frame":
            speed *= st["ff_scale"]
        st["speed"] = speed

        # 'balanced'（默认，已按实拍标定）：力场的减速记在**独立的阻尼因子**
        # `ff_damp` 上，而不是写进 speed 状态——后者是 initialSpeed→targetSpeed 那条
        # **慢**爬升（约 4 圈/960 帧）的载体，让这条**快**回拉（约 48 帧）去碰它，
        # 爬升就会被整个接管、螺旋被压成几十帧内完事（单测 test_linear_converge_
        # makes_an_equidistant_spiral / test_speed_ramp_takes_a_fixed_number_of_laps
        # 会红）。两套机制必须分开记。
        #   场内：ff_damp *= k          每帧（含场外）：ff_damp += 1/recover_frames
        # 平衡点 f* = min(1, c/(1-k))，c=1/recover_frames ⇒ 轨道直径 ∝ min(1, c/(1-k))。
        if st["ff_scale_mode"] == "balanced":
            damp = st["ff_damp"]
            if ff_slow:
                damp *= st["ff_scale"]
            damp = min(1.0, damp + 1.0 / st["ff_recover_frames"])
            st["ff_damp"] = damp

        if st["phase"] == "approach":
            if dist <= max(speed, 1e-6):
                # 本帧位移会追上/越过目标 —— 到达瞬间转入 orbit。
                #
                # ⚠ 别拿这一帧的 to_target / (p.pos-target) 算方向：一旦生成距离恰好是
                # speed 的整数倍（默认预设 30 距离 + 1 速度太常见），到达那一帧的残差
                # 会精确到 0，落进 _orbit_axis 的退化回退——**所有**粒子（不管原本从
                # 球面哪个方向生成的）会一起摔进同一个回退常量，摇身变成同一个转向，
                # 实机表现就是全体一起往同一个方向甩，跟生成方向完全脱钩（2026-09-12
                # 用户实测坐实：预设 30/1 组合下 200 个粒子里 145 个精确共享同一个
                # 到达速度向量）。改用**上一帧**记下来的 approach 方向（`st["dir"]`，
                # 逼近目标时逐帧刷新，从来不会退化，因为那时候残差还没归零）；只有
                # 「出生当帧就已在到达阈值内」这一种真正没有上一帧可用的情况才退回
                # 当帧 to_target。
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
            # 转满第一圈后**再转一次弯**（用当前速度方向当新来向重新定轴），然后锁死。
            # 2026-09-12 用户拿连续喷射探针实拍：粒子在一个圆上转满一圈后换到另一个
            # **同半径、不同朝向、同样过目标点**的圆，**之后就再也不变了**。
            # 同半径 ⇒ 不是速度收敛（那会改 r=v/ω）；只换一次 ⇒ 既不是「第一次到达
            # 就锁死一辈子」（那根本不会换），也不是「每次经过都重定轴」——后者实测
            # 出这个映射**环长恒为 2**（对竖直/水平/任意斜向来向都是），会两个圆无限
            # 来回倒，已被用户当场否掉。所以这里按实拍**只补转一次**。
            # ⚠ 「恰好两次」目前是照实拍描出来的现象，不是推出来的机制——真正的成因
            # （某个量在第一圈里收敛完？approach 进来的那一下本就该算特例？）未知。
            may_return = (st["turn_mode"] == "every_pass"
                          or (st["turn_mode"] == "once_more"
                              and st["turns_done"] < 2))
            if (may_return and not freeze_turn and st["turn_step"]
                    and st["since_turn"] >= st["turn_min_frames"]):
                # 触发判据用**累计转角满一圈**，不用「距目标一帧之内」：圆只是从目标
                # 近旁**经过**，离散采样不保证每圈都落进那个窗口——实测用距离判据时
                # 第一次要等 3 圈（719 帧）才碰巧撞上，之后才规律成 240 帧。按转角算
                # 既忠实于「转满一圈换一次」，也不看采样运气。
                direction = self._turn(st, st["dir"])
            else:
                direction = st["dir"]
                if not freeze_turn and st["turn_step"]:
                    # 'frozen'（默认）：绕到达那一刻定下的轴转到底。
                    # 'live'：**每帧按当前速度方向重新算侧向方向与转轴**，即把侧向力
                    #   当成一个**场**而不是冻结的轴。两者在**纯水平**运动下完全一致
                    #   （v·Y≡0 ⇒ φ≡0 ⇒ 转轴恒为世界 Y ⇒ 严格闭合的水平圆）；速度一旦
                    #   有 Y 分量，'live' 会让轨道平面**进动**，幅度随 |v·Y| 增大、且
                    #   第 2 圈后稳定下来。2026-09-12 用户实机：进动确实只在有 Y 分量
                    #   时出现、随 Y 分量减小而减小、每次完全可复现、约 2 圈后稳定
                    #   ——四条签名 'live' 全中，'frozen' 一条都给不出（恒零进动）。
                    # ⚠ 进动幅度是 lateral_tilt 的**陡峭**函数（v·Y≈0.71 时：tilt=0
                    #   给 56.7°、0.5 给 1.9°、1.0 给 0.10°、≥1.5 几乎为 0），所以
                    #   「量进动角」正好是标定 lateral_tilt 的手段——这是目前唯一
                    #   能给那个参数定值的观测。
                    axis_now = (_orbit_axis(direction, st["axis_mode"],
                                            st["handed"], st["lateral_tilt"])
                                if st["axis_update"] == "live" else st["axis"])
                    direction = _rotate_axis(direction, axis_now,
                                            math.degrees(st["turn_step"]))
                st["dir"] = direction

        # orbit 段的速度按逐粒子系数缩放 ⇒ 轨道半径 r = v/ω 随出生方向变化，这是
        # 整团在竖直方向被压扁的唯一来源（闭式解见 _orbit_speed_scale）。approach
        # 段恒按原速，保证全体同时到达中心。
        vel = direction * (speed * st["orbit_scale"]
                           if st["phase"] == "orbit" else speed)

        if st["phase"] == "orbit" and not freeze_turn:
            # 纯"绕固定轴转"结构上只能触及垂直于轴的两维——轴向分量在到达那一刻定死
            # 之后，绕固定轴转永远碰不到它，粒子沿轴向与 target 的偏移会被冻结、只
            # 随 speed 整体缩放，绝不会收拢回去（2026-09-12 用户实机反馈：某一根轴上
            # 完全看不到收缩，正是这个结构性缺口）。补一条独立于旋转的轴向回拉，把
            # 沿轴向的偏移量按跟 speed 收敛同一个 turnRate 节奏（`frac`）拉回 0，
            # 这样"整体转圈"与"逐渐收拢回目标所在平面"能同时成立。拉力本身未实测，
            # 只是不让轴向偏移永远冻结的最小修补。
            axis = st["axis"]
            axial_offset = (p.pos - target).dot(axis)
            if axial_offset:
                vel = vel - axis * (axial_offset * frac)

        # 'output' 模式下才在这里乘——'per_frame' 已经在上面把它累进 st["speed"] 了。
        if st["ff_scale_mode"] == "output" and ff_slow:
            vel = vel * st["ff_scale"]
        elif st["ff_scale_mode"] == "balanced":
            vel = vel * st["ff_damp"]
        p.vel = vel

    # ── 内部 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _turn(st, incoming):
        """在目标处开始转圈：按 `incoming` 定轴，返回进入 orbit 那一帧的方向。

        ⚠ **方向在这里是连续的，不拐弯**。已确认的行为是「到达目标时速度获得一个
        与来向**垂直**的分量」——那是一记**侧向（向心）力**，把直线弯成圆；不是
        「把速度方向就地旋转 90°」。这两件事完全不同，本函数曾经实现成后者
        （`_rotate_axis(incoming, axis, 90.0)`），2026-09-12 用户看 Blender 预览
        当场指出两处硬伤：① 轨迹在原点是个**锐角拐点**，而实机是光滑的；
        ② 圆心被放在 `-r·d`（来向的反方向）上，于是整个圆挂在来向那一侧（"上面"），
        而实机**原点是圆的切点、整个圆在侧向那一边（"左侧"）**。
        方向连续之后这两条自动成立：圆在原点与来向相切，圆心在侧向 `r·n` 处，
        `r = v/ω` —— 而且因为不再有"转 90° 再投影"这一步，速度大小一点不丢，
        每一段圆的半径严格相同（用户另一条实拍要求）。

        首次到达与（`turn_mode` 允许时）之后的重新定轴都走这里，规则天然一致。
        """
        axis = _orbit_axis(incoming, st["axis_mode"], st["handed"],
                           st["lateral_tilt"])
        # 只剥离沿轴分量，不做任何 90° 旋转。对默认的 'offset_up' 这是恒等变换
        # （该模式的 axis 由 cross(来向, Y) 得到，本来就与 incoming 垂直）；对
        # 'world_up'/'world_front' 这两个留作对照的 legacy 模式才真正起作用——
        # 绕固定轴转只能碰垂直于轴的两维，沿轴那份留着会被逐帧原样叠加、永不回头。
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
        """归航目标的**实时**位置（annotations 原话：不是触发时捕获定住）。"""
        if mode == 1:
            return em.host_origin.copy()
        if mode in (2, 3):
            return Vec3()
        return em.origin.copy()
