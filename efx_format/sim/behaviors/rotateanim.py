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

    spinAxisMask      bit0=X bit1=Y bit2=Z，控制哪些轴参与自旋
    rotateDelayStart(+Jitter)  开始旋转前的延迟帧数

角度单位是度，写进 `p.rot`。平面旋转写 **Z**（屏幕空间自转，渲染体拿它当
billboard 的 rotation）；自旋写三轴。

⚠ 无实测样本
------------
仓库自带的 16 个 archetype **没有一个带 ROTATEANIM**，所以下面的实现全部是按
schema 注释 + annotations 推的，没有拿真实数值对过账：

  - billboardRotation 当**角速度**（度/帧）而不是初始角度。依据是它配了一个
    「逐帧速度倍率」性质的 Coef——只有速度才需要每帧乘衰减；初始角度由
    BILLBOARD3D.rotation 提供，两者不冲突。
  - 「随机正反」按 50% 概率整体取负（模式 1）／每轴独立取负（模式 3）。
  - 自旋三轴各自独立衰减（spinSpeedCoefX/Y/Z 分开给，说明是逐轴的）。

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

_AXIS_BITS = (0x1, 0x2, 0x4)      # BITS_SPIN_AXIS: bit0=X bit1=Y bit2=Z


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
            st["plane_v"] = speed
            st["plane_a"] = jitter(f.get("billboardRotationCoef", 1.0),
                                   f.get("billboardRotationCoefJitter"), rng,
                                   cfg.jitter_mode)
        else:
            # spin_velocity 是 XYZ type 0：固定/随机逐轴成对
            base = f.xyz_lo("spin_velocity")
            amount = f.xyz_hi("spin_velocity")
            axis_mask = f.i("spinAxisMask")
            vel = []
            acc = []
            for i, ax in enumerate(("X", "Y", "Z")):
                if not (axis_mask & _AXIS_BITS[i]):
                    vel.append(0.0)
                    acc.append(1.0)
                    continue
                v = jitter(base[i], amount[i], rng, cfg.jitter_mode)
                if mode_v == MODE_SPIN_RANDOM_DIR and rng.random() < 0.5:
                    v = -v      # 每轴独立随机正反
                vel.append(v)
                acc.append(jitter(f.get("spinSpeedCoef" + ax, 1.0),
                                  f.get("spinSpeedCoef" + ax + "Jitter"), rng,
                                  cfg.jitter_mode))
            st["spin_v"] = vel
            st["spin_a"] = acc

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
        vel[0] *= acc[0]
        vel[1] *= acc[1]
        vel[2] *= acc[2]
