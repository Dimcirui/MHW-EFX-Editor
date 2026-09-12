# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/transform3d.py  —  TRANSFORM3D（发射器自身的变换与漂移）

字段（EXTERN_TRANSFORM3D_SCHEMA，228 B）：

    translate / rotate / resize          XYZ type 0，固定/随机逐轴成对
    rotationOrder                        _TRANSFORM_ROT_ORDER（**不是** VELOCITY3D 那套）
    translation_velocity(+_modifier)     发射器自身的漂移速度 / 逐帧倍率
    rotation_velocity(+_modifier)
    scale_velocity(+_modifier)
    enableVelocityBitflag                bit0=启用速度，bit1=启用加速度（annotations 确认）

三组速度的单位是**每秒**
------------------------
`SimConfig.t3d_velocity_unit`（默认 'per_second'）。语料里启用了速度位的 8158 个块：

    rotation_velocity     非零分量 7219，|值| 中位 90 / 90% 500 / 最大 5000
    translation_velocity  非零 2257，中位 150 / 90% 1500 / 最大 12000（游戏单位）
    scale_velocity        非零 2073，中位 1.0 / 90% 4.0 / 最大 40

按「每帧」读的话：500°/帧 = 每秒 83 圈、1500 单位/帧 = 900 m/s、缩放每帧 +1 = 一秒
放大 60 倍——三组都荒谬。按「每秒」读（逐帧推进 v/fps）全部落在合理区间。
`_modifier`（加速度）仍是**逐帧**乘一次的衰减率，那一族 tooltip 原话就是「每帧乘一次」。

⚠ 动态缩放夹在 0 以上：`scale_velocity` 为负时无限累减会让倍率穿过 0 变负，
生成形状会被镜像翻过去（表现是粒子从收缩变成朝外飞）。

旋转/缩放怎么作用到粒子上
------------------------
`rotation_velocity` / `scale_velocity` 累积进 `em.rot_dynamic` / `em.scale_dynamic`，
生成方式和初速度在出生时按它们变换（见 `_common.emitter_place/emitter_rotate`
的调用处：EMITTERSHAPE3D 的生成点、VELOCITY3D 的初速度方向）。这样「发射器一边转
一边喷」才会真的转起来——在这之前这两个量只是累积着没人用。

⚠ 默认**不套用静态变换**（cfg.t3d_apply_base = False）
-----------------------------------------------------
在 Blender 里，entry 的 empty 已经被 transform_sync.py 按 translate/rotate/resize
摆好了（还额外处理了 PARENTOPTIONS 的骨骼绑定与锚定）。模拟层要是再把 translate
加进 `em.origin`，预览里就会**双份位移**。

所以默认只贡献**动态部分**（漂移），静态部分留给宿主：

    em.origin 从 (0,0,0) 起，只被 translation_velocity 推动
    → 粒子坐标是「相对发射器」的，宿主再叠上 entry 的世界矩阵

脱离 Blender 单独用（或者宿主没有摆位能力）时，把 `t3d_apply_base` 打开，
静态 translate/rotate/resize 就会由本 behavior 自己套上。

副产品：`em.velocity`（每帧位移）由核心从 origin 的变化算出，正好喂给
VELOCITY3D 的 velocityType=3（EmitterMotion）。语料里 enableVelocityBitflag
几乎恒为 0，所以这条路平时是静默的——但它在，一旦遇到会漂移的发射器就生效。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import TRANSFORM3D
from ..registry import Behavior, register
from ..rng import jitter_vec
from ..stages import FORCE
from ..state import Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name

BIT_ENABLE_VELOCITY = 0x1
BIT_ENABLE_ACCEL = 0x2


@register(TRANSFORM3D)
class Transform3D(Behavior):
    """发射器级：只跑 init / emitter_step，不碰单个粒子。"""

    STAGE = FORCE
    ORDER = 0        # 排在所有 spawn_method 之前：它定的是发射器原点

    def on_emitter_init(self, em, rng):
        f = em.f(TRANSFORM3D)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode

        translate = jitter_vec(f.xyz_lo("translate"), f.xyz_hi("translate"), rng, mode)
        rotate = jitter_vec(f.xyz_lo("rotate"), f.xyz_hi("rotate"), rng, mode)
        resize = jitter_vec(f.xyz_lo("resize"), f.xyz_hi("resize"), rng, mode)

        flags = f.i("enableVelocityBitflag")
        vel_on = bool(flags & BIT_ENABLE_VELOCITY)
        acc_on = bool(flags & BIT_ENABLE_ACCEL)

        st = {
            "translate": translate,
            "rotate": rotate,
            "resize": resize,
            "rot_order": rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM),
            "vel": jitter_vec(f.xyz_lo("translation_velocity"),
                              f.xyz_hi("translation_velocity"), rng, mode)
                   if vel_on else Vec3(),
            "vel_mod": jitter_vec(f.xyz_lo("translation_velocity_modifier"),
                                  f.xyz_hi("translation_velocity_modifier"), rng, mode)
                       if acc_on else Vec3(1.0, 1.0, 1.0),
            "rot_vel": jitter_vec(f.xyz_lo("rotation_velocity"),
                                  f.xyz_hi("rotation_velocity"), rng, mode)
                       if vel_on else Vec3(),
            "rot_vel_mod": jitter_vec(f.xyz_lo("rotation_velocity_modifier"),
                                      f.xyz_hi("rotation_velocity_modifier"), rng, mode)
                           if acc_on else Vec3(1.0, 1.0, 1.0),
            "scale_vel": jitter_vec(f.xyz_lo("scale_velocity"),
                                    f.xyz_hi("scale_velocity"), rng, mode)
                         if vel_on else Vec3(),
            "scale_vel_mod": jitter_vec(f.xyz_lo("scale_velocity_modifier"),
                                        f.xyz_hi("scale_velocity_modifier"), rng, mode)
                             if acc_on else Vec3(1.0, 1.0, 1.0),
            "accel_on": acc_on,
        }
        em.user[Transform3D] = st

        # 供渲染/宿主取用；静态部分是否落进 origin 由开关决定（见模块 docstring）
        em.rotation = rotate.copy()
        em.scale = resize.copy()
        em.rot_order = st["rot_order"]
        if cfg.t3d_apply_base:
            em.drift = translate.copy()
            em.rot_dynamic = rotate.copy()
            em.scale_dynamic = resize.copy()
        else:
            em.note("TRANSFORM3D 静态变换未套用（宿主已摆位；开 t3d_apply_base 可改）")

    def on_emitter_step(self, em):
        st = em.user.get(Transform3D)
        if st is None:
            return

        # 每秒 → 每帧（见模块 docstring「三组速度的单位是每秒」）
        dt = self._per_frame(em.config)

        v = st["vel"]
        if v.x or v.y or v.z:
            em.drift += v * dt   # 写 drift 不写 origin：origin 由核心每帧合成
            if st["accel_on"]:
                m = st["vel_mod"]
                v.x *= m.x
                v.y *= m.y
                v.z *= m.z

        rv = st["rot_vel"]
        if rv.x or rv.y or rv.z:
            step = rv * (dt * self._rot_sign(em.config))
            em.rotation += step
            em.rot_dynamic += step      # 发射器转了 → 它发出去的东西跟着转
            if st["accel_on"]:
                m = st["rot_vel_mod"]
                rv.x *= m.x
                rv.y *= m.y
                rv.z *= m.z

        sv = st["scale_vel"]
        if sv.x or sv.y or sv.z:
            em.scale += sv * dt
            # scale_velocity 是**加**在缩放上的，所以动态倍率同样按加法累积：
            # base 恒为 1 的常见情形下 1+Σ(sv·dt) 就是真实倍率。**夹在 0 以上**——
            # 负倍率等于把生成形状镜像翻过去，表现上粒子会从收缩变成朝外飞。
            sd = em.scale_dynamic
            sd.x = max(0.0, sd.x + sv.x * dt)
            sd.y = max(0.0, sd.y + sv.y * dt)
            sd.z = max(0.0, sd.z + sv.z * dt)
            if st["accel_on"]:
                m = st["scale_vel_mod"]
                sv.x *= m.x
                sv.y *= m.y
                sv.z *= m.z

    @staticmethod
    def _rot_sign(cfg):
        """旋转速度的转向。用户实机：`05 spell` 那圈符文是**逆时针**生成的，
        照字面符号转出来是顺时针——所以默认取反。"""
        return -1.0 if getattr(cfg, "t3d_rotation_sign", "flip") == "flip" else 1.0

    @staticmethod
    def _per_frame(cfg):
        """速度的「每帧份额」。'per_frame' 开关下退回改动前的行为（1 帧 = 1 个单位）。"""
        if getattr(cfg, "t3d_velocity_unit", "per_second") == "per_frame":
            return 1.0
        return 1.0 / float(getattr(cfg, "fps", 60) or 60)
