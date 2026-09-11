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
        if cfg.t3d_apply_base:
            em.drift = translate.copy()
        else:
            em.note("TRANSFORM3D 静态变换未套用（宿主已摆位；开 t3d_apply_base 可改）")

    def on_emitter_step(self, em):
        st = em.user.get(Transform3D)
        if st is None:
            return

        v = st["vel"]
        if v.x or v.y or v.z:
            em.drift += v      # 写 drift 不写 origin：origin 由核心每帧合成
            if st["accel_on"]:
                m = st["vel_mod"]
                v.x *= m.x
                v.y *= m.y
                v.z *= m.z

        rv = st["rot_vel"]
        if rv.x or rv.y or rv.z:
            em.rotation += rv
            if st["accel_on"]:
                m = st["rot_vel_mod"]
                rv.x *= m.x
                rv.y *= m.y
                rv.z *= m.z

        sv = st["scale_vel"]
        if sv.x or sv.y or sv.z:
            em.scale += sv
            if st["accel_on"]:
                m = st["scale_vel_mod"]
                sv.x *= m.x
                sv.y *= m.y
                sv.z *= m.z
