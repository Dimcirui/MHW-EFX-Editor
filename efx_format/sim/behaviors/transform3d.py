# -*- coding: utf-8 -*-
"""TRANSFORM3D —— 发射器自身的变换与漂移。

字段职能：

    translate / rotate / resize         静态变换，XYZ type 0，各轴由固定值与随机幅度成对组成
    rotationOrder                       欧拉旋转顺序，与 VELOCITY3D **不同**
    translation_velocity(+_modifier)    发射器自身的漂移速度 / 逐帧倍率
    rotation_velocity(+_modifier)       自转角速度 / 逐帧倍率
    scale_velocity(+_modifier)          缩放速度 / 逐帧倍率
    enableVelocityBitflag               bit0=启用速度，bit1=启用加速度

三组速度的单位为**每秒**（`SimConfig.t3d_velocity_unit`），每帧推进 v/fps；三个 `_modifier`
为**每帧**作用一次的衰减率。

`rotation_velocity` / `scale_velocity` 累积到 `em.rot_dynamic` / `em.scale_dynamic`，由
EMITTERSHAPE3D 的生成点与 VELOCITY3D 的初速度方向在出生时使用，使旋转中的发射器按当前朝向
发射。`translation_velocity` 写入 `em.drift`，`em.origin` 由核心每帧合成；核心再由 origin 的
变化求得 `em.velocity`，供 VELOCITY3D 的 velocityType=3（EmitterMotion）使用。
`scale_velocity` 加在缩放上，动态倍率同样按加法累积。

TIML：translate / rotate / resize 的 A0 轨道逐帧按发射器当前帧求值，取「曲线值 − 静态值」作为
动态增量（静态部分已由宿主或出生时的基础变换施加），每帧只施加增量的变化量：平移进
`em.drift`，旋转进 `em.rot_dynamic`，缩放按「曲线值 / 静态值」的倍率乘进 `em.scale_dynamic`。

维护约束：
- 默认**不施加静态变换**（`cfg.t3d_apply_base` 为 False）。Blender 侧 entry 的 empty 已由
  `transform_sync.py` 按 translate / rotate / resize 放置（并处理了 PARENTOPTIONS 的骨骼绑定
  与锚定），若模拟层再将 translate 加入 `em.origin`，会产生**重复位移**。因此默认只计算动态
  部分，粒子坐标相对于发射器，由宿主叠加 entry 的世界矩阵；脱离 Blender 单独使用或宿主不负责
  摆放时，才启用该开关。
- `em.scale_dynamic` 必须限定为非负：`scale_velocity` 为负时持续累减会使倍率变为负数，生成
  形状被镜像，粒子由收缩变为向外运动。
- 旋转速度默认取反（`cfg.t3d_rotation_sign`）：按字面符号旋转的方向与实机相反。TIML 的
  rotate 是静态旋转的替换值，与静态 rotate 同号，不取反。
- 宿主摆位时粒子坐标会经过 entry 的旋转与缩放，TIML 平移增量须先逆变换静态旋转与缩放，
  否则 entry 带旋转时平移方向被一起转掉。基础变换由模拟层施加时（`t3d_apply_base`）不需要。
- 基础变换取**不含 TIML** 的静态值加抖动；TIML 的影响全部由逐帧增量负责，避免初始化那一帧
  的曲线值被计入两次。
"""

from ...hashes import TRANSFORM3D
from ..registry import Behavior, register
from ..rng import jitter_vec
from ..stages import FORCE
from ..state import Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler

BIT_ENABLE_VELOCITY = 0x1
BIT_ENABLE_ACCEL = 0x2


@register(TRANSFORM3D)
class Transform3D(Behavior):
    """发射器级 behavior，只执行 init 与 emitter_step，不处理单个粒子。"""

    STAGE = FORCE
    ORDER = 0        # 必须排在所有 spawn_method 之前：本属性决定发射器原点

    def on_emitter_init(self, em, rng):
        f = em.f(TRANSFORM3D)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode

        static = {k: _static_half(f, k) for k in ("translate", "rotate", "resize")}
        translate = jitter_vec(static["translate"], f.xyz_hi("translate"), rng, mode)
        rotate = jitter_vec(static["rotate"], f.xyz_hi("rotate"), rng, mode)
        resize = jitter_vec(static["resize"], f.xyz_hi("resize"), rng, mode)

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
            "static": static,
            "timl": f.has_tracks,
            "tl_move": Vec3(),
            "tl_rot": Vec3(),
            "tl_scale": Vec3(1.0, 1.0, 1.0),
        }
        em.user[Transform3D] = st

        # 供渲染与宿主读取；静态部分是否计入 origin 由开关决定
        em.rotation = rotate.copy()
        em.scale = resize.copy()
        em.rot_order = st["rot_order"]
        if cfg.t3d_apply_base:
            em.drift = translate.copy()
            em.rot_dynamic = rotate.copy()
            em.scale_dynamic = resize.copy()
        else:
            em.note("TRANSFORM3D 静态变换未套用（宿主已摆位；开 t3d_apply_base 可改）")
        #: scale_velocity 的加法累积部分；em.scale_dynamic = 它 × TIML 倍率
        st["scale_add"] = em.scale_dynamic.copy()

    def on_emitter_step(self, em):
        st = em.user.get(Transform3D)
        if st is None:
            return

        dt = self._per_frame(em.config)

        v = st["vel"]
        if v.x or v.y or v.z:
            em.drift += v * dt   # 写入 drift 而非 origin，origin 由核心每帧合成
            if st["accel_on"]:
                m = st["vel_mod"]
                v.x *= m.x
                v.y *= m.y
                v.z *= m.z

        rv = st["rot_vel"]
        if rv.x or rv.y or rv.z:
            step = rv * (dt * self._rot_sign(em.config))
            em.rotation += step
            em.rot_dynamic += step      # 发射器旋转时，其发射内容随之旋转
            if st["accel_on"]:
                m = st["rot_vel_mod"]
                rv.x *= m.x
                rv.y *= m.y
                rv.z *= m.z

        if st["timl"]:
            self._apply_timl(em, st)

        sv = st["scale_vel"]
        if sv.x or sv.y or sv.z:
            em.scale += sv * dt
            # 按加法累积：base 为 1 的常见情形下，1+Σ(sv·dt) 即实际倍率
            sa = st["scale_add"]
            sa.x = max(0.0, sa.x + sv.x * dt)
            sa.y = max(0.0, sa.y + sv.y * dt)
            sa.z = max(0.0, sa.z + sv.z * dt)
            if st["accel_on"]:
                m = st["scale_vel_mod"]
                sv.x *= m.x
                sv.y *= m.y
                sv.z *= m.z
        if st["timl"] or sv.x or sv.y or sv.z:
            sa, k, sd = st["scale_add"], st["tl_scale"], em.scale_dynamic
            sd.x, sd.y, sd.z = sa.x * k.x, sa.y * k.y, sa.z * k.z

    @staticmethod
    def _apply_timl(em, st):
        """按发射器当前帧求 TIML 值，把相对上一帧的增量变化施加到动态变换上。"""
        f = em.f(TRANSFORM3D)
        base = st["static"]

        rot = f.xyz_lo("rotate") - base["rotate"]
        step = rot - st["tl_rot"]
        st["tl_rot"] = rot
        if step.x or step.y or step.z:
            em.rotation += step
            em.rot_dynamic += step

        cur = f.xyz_lo("resize")
        s0 = base["resize"]
        k = Vec3(*[max(0.0, c / b) if abs(b) > 1e-9 else 1.0
                   for c, b in ((cur.x, s0.x), (cur.y, s0.y), (cur.z, s0.z))])
        st["tl_scale"] = k

        move = f.xyz_lo("translate") - base["translate"]
        if not em.config.t3d_apply_base:
            move = _undo_static(move, base["rotate"], s0, st["rot_order"],
                                em.config.rot_order_applied)
        step = move - st["tl_move"]
        st["tl_move"] = move
        if step.x or step.y or step.z:
            em.drift += step

    @staticmethod
    def _rot_sign(cfg):
        """返回旋转速度的符号；默认取反。"""
        return -1.0 if getattr(cfg, "t3d_rotation_sign", "flip") == "flip" else 1.0

    @staticmethod
    def _per_frame(cfg):
        """返回速度的每帧系数；`per_frame` 档返回 1。"""
        if getattr(cfg, "t3d_velocity_unit", "per_second") == "per_frame":
            return 1.0
        return 1.0 / float(getattr(cfg, "fps", 60) or 60)


def _static_half(f, field):
    """FLOAT6 前一半的静态值（不含 TIML）。"""
    v = f.raw(field)
    if not isinstance(v, (list, tuple)) or len(v) < 6:
        return f.xyz_lo(field)
    return Vec3(float(v[0]), float(v[2]), float(v[4]))


def _undo_static(v, rot, scale, order, applied):
    """把父空间的位移换算到 entry 局部：逆施加静态旋转，再除以静态缩放。"""
    out = rotate_euler(v, -rot.x, -rot.y, -rot.z, order=order[::-1], applied=applied)
    return Vec3(out.x / scale.x if abs(scale.x) > 1e-9 else out.x,
                out.y / scale.y if abs(scale.y) > 1e-9 else out.y,
                out.z / scale.z if abs(scale.z) > 1e-9 else out.z)
