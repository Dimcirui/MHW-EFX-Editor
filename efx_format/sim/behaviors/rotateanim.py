# -*- coding: utf-8 -*-
"""ROTATEANIM —— 逐帧旋转动画。

两套互斥的旋转，由 `rotationModeMask` 的四个取值选择：

    0 = 平面旋转            billboardRotation + billboardRotationCoef
    1 = 平面旋转 + 随机方向
    2 = 自旋速度            spin_velocity(XYZ) + spinSpeedCoef{X,Y,Z}
    3 = 自旋速度 + 随机方向（各轴独立随机）

两套均为「速度 + 逐帧乘法衰减」，与 VELOCITY3D / SCALEANIM 形式相同：速度单位为度/帧，Coef
每帧作用一次（1 为匀速，大于 1 逐渐加快，小于 1 逐渐减慢）。`rotateDelayStart(+Jitter)` 为
开始旋转前的延迟帧数。角度写入 `p.rot`：平面旋转写入 **Z**（屏幕空间自转，渲染体将其作为
billboard 的 rotation），自旋写入三个轴。

维护约束：
- 参与自旋的轴只由 `spin_velocity` 的逐轴取值决定，**不读取 `spinAxisMask`**。后者的取值超出
  三位，与 spin_velocity 的非零轴也没有对应关系，实际作用未知；按轴掩码过滤会屏蔽有角速度的轴。
- 写入 `p.rot` 的自旋角必须取负：游戏给出的角速度方向，与 `oriented_basis` 绕法线的右手旋转在
  游戏到 Blender 的坐标映射下相反。目前只校准了「绕 Z 自旋 + PLANE」一种组合，另两轴按相同
  符号处理。
- 自旋角除写入 `p.rot`（供 PLANE / MESH 等三维渲染体使用）外，必须另存于
  `p.rolled["spin_ang"]`：billboard 每帧都朝向相机，只有绕法线（即视线方向）的自旋在屏幕上
  可见，由 BILLBOARD3D 在 `build_render` 中按相机朝向取分量（`SimConfig.rotateanim_billboard_axis`）。
- 「随机方向」按 50% 概率取负、自旋三轴独立衰减、平面旋转的方向，三项均无实机样本验证。
- TIML（A1）：billboardRotation / spin_velocity 每帧取「曲线值 + 出生时抽取的抖动偏移」为基准，
  乘以出生时定下的方向符号与 Coef 自延迟结束起的累积衰减；没有轨道时与逐帧递推完全一致。
  静态值为 0 的自旋轴同样跟随曲线。
"""

from ...hashes import ROTATEANIM
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import XFORM

MODE_PLANE = 0
MODE_PLANE_RANDOM_DIR = 1
MODE_SPIN = 2
MODE_SPIN_RANDOM_DIR = 3

#: 游戏给出的角速度写入 p.rot 时取负，原因见模块 docstring
_SPIN_SIGN = -1.0


@register(ROTATEANIM)
class RotateAnim(Behavior):
    """XFORM 阶段写入 p.rot；与 SCALEANIM 写入不同的状态，互不影响。"""

    STAGE = XFORM
    ORDER = 110

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(ROTATEANIM)
        if f is not None:
            self._has_tracks = f.has_tracks

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
            static = f.get("billboardRotation")
            speed = jitter(static, f.get("billboardRotationJitter"), rng, cfg.jitter_mode)
            sign = _SPIN_SIGN
            if mode_v == MODE_PLANE_RANDOM_DIR and rng.random() < 0.5:
                sign = -sign
            st["plane_v"] = speed * sign
            if self._has_tracks:
                st["tl"] = {"sign": sign, "off": speed - static, "decay": 1.0}
            st["plane_a"] = jitter(f.get("billboardRotationCoef", 1.0),
                                   f.get("billboardRotationCoefJitter"), rng,
                                   cfg.jitter_mode)
        else:
            # spin_velocity 为 XYZ type 0：各轴由固定值与随机幅度成对组成
            base = f.xyz_lo("spin_velocity")
            amount = f.xyz_hi("spin_velocity")
            vel = []
            acc = []
            signs = []
            offs = []
            for i, ax in enumerate(("X", "Y", "Z")):
                if not base[i] and not amount[i] and not self._has_tracks:
                    # 该轴没有角速度即不旋转，不读取 spinAxisMask
                    vel.append(0.0)
                    acc.append(1.0)
                    continue
                raw = jitter(base[i], amount[i], rng, cfg.jitter_mode)
                sign = _SPIN_SIGN
                if mode_v == MODE_SPIN_RANDOM_DIR and rng.random() < 0.5:
                    sign = -sign    # 各轴独立随机方向
                vel.append(raw * sign)
                signs.append(sign)
                offs.append(raw - base[i])
                acc.append(jitter(f.get("spinSpeedCoef" + ax, 1.0),
                                  f.get("spinSpeedCoef" + ax + "Jitter"), rng,
                                  cfg.jitter_mode))
            st["spin_v"] = vel
            st["spin_a"] = acc
            if self._has_tracks:
                st["tl"] = {"sign": signs, "off": offs, "decay": [1.0, 1.0, 1.0]}
            #: 累积的自旋角，供 BILLBOARD3D 按视线方向取分量
            p.rolled["spin_ang"] = [0.0, 0.0, 0.0]

        p.user[RotateAnim] = st

    def on_particle_step(self, p, em):
        st = p.user.get(RotateAnim)
        if st is None or p.age < st["delay"]:
            return

        tl = st.get("tl")
        f = em.f(ROTATEANIM, p) if tl is not None else None

        if "plane_v" in st:
            if f is not None:
                st["plane_v"] = ((f.get("billboardRotation") + tl["off"])
                                 * tl["sign"] * tl["decay"])
                tl["decay"] *= st["plane_a"]
            p.rot.z += st["plane_v"]          # 平面旋转即屏幕空间自转，写入 Z
            st["plane_v"] *= st["plane_a"]
            return

        vel = st["spin_v"]
        acc = st["spin_a"]
        if f is not None:
            cur = f.xyz_lo("spin_velocity")
            dec = tl["decay"]
            for i in range(3):
                vel[i] = (cur[i] + tl["off"][i]) * tl["sign"][i] * dec[i]
                dec[i] *= acc[i]
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
