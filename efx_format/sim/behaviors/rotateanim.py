# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/rotateanim.py  —  ROTATEANIM（逐帧旋转动画）

两套互斥的旋转，由 `rotationModeMask` 选（ENUM_ROTATION_MODE，用户实机确认的四态）：

    0 = 平面旋转系          billboardRotation + billboardRotationCoef
    1 = 平面旋转 + 随机正反
    2 = 自旋速度系          spin_velocity(XYZ) + spinSpeedCoef{X,Y,Z}
    3 = 自旋速度 + 随机正反（**每轴独立**随机）

两套都是「速度 + 逐帧乘法衰减」，和 VELOCITY3D/SCALEANIM 同一形状：
`billboardRotationCoef` / `spinSpeedCoef*` 的 tooltip 都是那句标准的
「逐帧速度倍率……1=匀速，>1 越来越快，<1 越来越慢」。

    rotateDelayStart(+Jitter)  开始旋转前的延迟帧数

角度单位是度，写进 `p.rot`。平面旋转写 **Z**（屏幕空间自转，渲染体拿它当
billboard 的 rotation）；自旋写三轴。

哪些轴参与自旋：看 spin_velocity，**不看 spinAxisMask**
-----------------------------------------------------
`spinAxisMask` 的原注解说是 bit0=X/bit1=Y/bit2=Z 的轴掩码，**全语料对不上**：
取值到 16/19/20/25 都有（超出 3 位），而且 mask 与 spin_velocity 哪几轴非零毫无
对应关系（mask=1 配 XYZ 全非零 872 块、mask=3 配只有 X 非零 887 块…）。真实作用未知。
所以本 behavior 只按 spin_velocity 的逐轴取值决定转不转——0 就是不转。
（现实证据：菱形那条 mask=16、spin_velocity.z=5，游戏里确实在转；按旧的掩码读法
 16 一位都命中不了，Z 轴被整个挡掉，于是「看起来没接入」。）

自旋方向
--------
用户实机：spin_velocity.z=+5 时，该轴与 Blender 全局 Y 重合，从 -Y 看向 +Y 是
**顺时针**。我们这边 `oriented_basis` 用的是绕法线的**右手**旋转，而 game +Z 映到
Blender -Y（法线朝着观察者），右手正角在那个视角下是逆时针——所以写进 p.rot 的
自旋角要取负号。只校准过「绕 Z 自旋 + PLANE」这一种组合，另两轴同号处理。

单位：度 / 帧，Coef 每帧乘一次
----------------------------
用户实机（BILLBOARD3D 正方形）：平面旋转速度恒 2 时转过 90° 用 0.733 秒
（= 44 帧，2.05°/帧）；速度 10 配 Coef 0.95 时约 1.27 秒（76 帧）几乎停住
（0.95⁷⁶ ≈ 2%）。两条都对上「速度是度/帧、Coef 是逐帧乘一次的倍率」。

billboard 只认**朝向相机那根轴**的自旋
--------------------------------------
同一组实机：正方形 billboard 上「平面旋转」与「自旋速度的 X」效果**完全等同**，
而自旋的 Y/Z 一点反应都没有——因为 billboard 每帧都被摆正朝向相机，绕画面内的两根
轴转它看不出来，只有绕法线（= 视线方向）转才是屏幕上的自转。那次配置里 game X 恰好
指向相机。所以自旋角除了写进 `p.rot`（PLANE/MESH 这些真 3D 渲染体要用），还另存一份
`p.rolled["spin_ang"]`，由 BILLBOARD3D 在 `build_render` 里按相机朝向取分量
（`SimConfig.rotateanim_billboard_axis`）。

⚠ 其余仍无实测样本
------------------
仓库自带的 16 个 archetype **没有一个带 ROTATEANIM**，下面这些仍是按
schema 注释 + annotations 推的：
  - 「随机正反」按 50% 概率整体取负（模式 1）／每轴独立取负（模式 3）。
  - 自旋三轴各自独立衰减（spinSpeedCoefX/Y/Z 分开给，说明是逐轴的）。
  - 平面旋转（模式 0/1）的方向没有实机数据，暂与自旋同号处理。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import ROTATEANIM
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import XFORM

MODE_PLANE = 0
MODE_PLANE_RANDOM_DIR = 1
MODE_SPIN = 2
MODE_SPIN_RANDOM_DIR = 3

#: 游戏给的角速度 → 我们的右手旋转要取负（见模块 docstring「自旋方向」）
_SPIN_SIGN = -1.0


@register(ROTATEANIM)
class RotateAnim(Behavior):
    """XFORM 阶段：写 p.rot。排在 SCALEANIM 之后（两者写不同槽位，互不影响）。"""

    STAGE = XFORM
    ORDER = 110

    def on_particle_spawn(self, p, em, rng):
        f = em.f(ROTATEANIM, p)
        if f is None:
            return
        cfg = em.config
        mode_v = f.i("rotationModeMask")
        st = {
            "mode": mode_v,
            "delay": max(0, jitter_int(f.get("rotateDelayStart"),
                                       f.get("rotateDelayStartJitter"), rng,
                                       cfg.jitter_mode)),
        }

        if mode_v in (MODE_PLANE, MODE_PLANE_RANDOM_DIR):
            speed = jitter(f.get("billboardRotation"), f.get("billboardRotationJitter"),
                           rng, cfg.jitter_mode)
            if mode_v == MODE_PLANE_RANDOM_DIR and rng.random() < 0.5:
                speed = -speed
            st["plane_v"] = speed * _SPIN_SIGN
            st["plane_a"] = jitter(f.get("billboardRotationCoef", 1.0),
                                   f.get("billboardRotationCoefJitter"), rng,
                                   cfg.jitter_mode)
        else:
            # spin_velocity 是 XYZ type 0：固定/随机逐轴成对
            base = f.xyz_lo("spin_velocity")
            amount = f.xyz_hi("spin_velocity")
            vel = []
            acc = []
            for i, ax in enumerate(("X", "Y", "Z")):
                if not base[i] and not amount[i]:
                    # 这一轴没给角速度 = 不转（不看 spinAxisMask，见模块 docstring）
                    vel.append(0.0)
                    acc.append(1.0)
                    continue
                v = jitter(base[i], amount[i], rng, cfg.jitter_mode) * _SPIN_SIGN
                if mode_v == MODE_SPIN_RANDOM_DIR and rng.random() < 0.5:
                    v = -v      # 每轴独立随机正反
                vel.append(v)
                acc.append(jitter(f.get("spinSpeedCoef" + ax, 1.0),
                                  f.get("spinSpeedCoef" + ax + "Jitter"), rng,
                                  cfg.jitter_mode))
            st["spin_v"] = vel
            st["spin_a"] = acc
            #: 累积的自旋角，供 BILLBOARD3D 按视轴取分量（见模块 docstring）
            p.rolled["spin_ang"] = [0.0, 0.0, 0.0]

        p.user[RotateAnim] = st

    def on_particle_step(self, p, em):
        st = p.user.get(RotateAnim)
        if st is None or p.age < st["delay"]:
            return

        if "plane_v" in st:
            p.rot.z += st["plane_v"]          # 平面旋转 = 屏幕空间自转，走 Z
            st["plane_v"] *= st["plane_a"]
            return

        vel = st["spin_v"]
        acc = st["spin_a"]
        p.rot.x += vel[0]
        p.rot.y += vel[1]
        p.rot.z += vel[2]
        ang = p.rolled.get("spin_ang")
        if ang is not None:
            ang[0] += vel[0]
            ang[1] += vel[1]
            ang[2] += vel[2]
        vel[0] *= acc[0]
        vel[1] *= acc[1]
        vel[2] *= acc[2]
