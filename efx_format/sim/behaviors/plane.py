# -*- coding: utf-8 -*-
"""PLANE —— 固定朝向的面片。

与 BILLBOARD3D 的唯一本质区别是**不朝向相机**，朝向由自身字段确定。

字段职能：

    baseAxis            面片的基准法线，与 VELOCITY3D 共用 AxisDirection6 枚举
    rotation(XYZ0)      整个面片的欧拉旋转，XYZ0 的后半部分为逐轴抖动幅度
    rotationOrder       欧拉旋转顺序，与 MESH 使用同一套枚举
    rotation2(+Jitter)  绕自身法线的自旋，独立于上述朝向字段

ROTATEANIM 的平面旋转绕法线转；三轴自旋绕面片自身的局部轴转，局部轴即经 rotation 旋转后的
世界三轴。基准法线为 Y 时自旋 Y 就是面内旋转，与 rotation 把面片倾斜到什么角度无关。

color / colorRange / useColorRange / brightness / blendMode / scale / width / height 与
flowmap 字段组均与 BILLBOARD3D 同名同义，使用 `_common.py` 的共享实现；尺寸约定也相同，
`scale` 为倍率，`width` / `height` 为游戏单位。`correctColorNo` 与
`colorRangeCorrectColorNo` 未接入，仅记录 note。

维护约束：
- rotation 必须转整个横纵轴，不能只转法线再重建横纵轴，否则绕法线的旋转（基准法线 Y 时的
  rotation Y）会整个丢掉。
- `item.extra["base_tint"]` 保存渲染主体自身的颜色，不含 RGBFIRE / RGBWATER 写入 `p.color`
  的分层色，供 glue 的两层染色分支作为逐通道滤镜使用。BILLBOARD3D 的同名字段含义相同。
"""

from ...hashes import PLANE
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import BASE_AXES, RenderItem, Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler
from . import _flowmap
from ._common import (emissive_on, epv_note, jitter_offsets,
                      oriented_basis, pick_color, quad_size, roll_rgba, with_offset)


@register(PLANE)
class Plane(Behavior):
    """RENDER_BODY 阶段产出固定朝向的面片；axis_u/axis_v 非空即表示 glue 不做朝向相机处理。"""

    STAGE = RENDER_BODY
    ORDER = 100

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(PLANE)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        epv_note(f, em, "PLANE", "correctColorNo", "colorRangeCorrectColorNo")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(PLANE, p)
        if f is None:
            return

        p.rolled["pl_scale"] = jitter(f.get("scale", 1.0), f.get("scaleJitter"), rng)
        p.rolled["pl_width"] = jitter(f.get("width", 1.0), f.get("widthJitter"), rng)
        p.rolled["pl_height"] = jitter(f.get("height", 1.0), f.get("heightJitter"), rng)
        p.rolled["pl_bright"] = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"),
                                       rng)
        p.rolled["pl_spin"] = jitter(f.get("rotation2"), f.get("rotation2Jitter"), rng)

        base = f.xyz_lo("rotation")
        amt = f.xyz_hi("rotation")
        rolled_rot = (jitter(base.x, amt.x, rng),
                      jitter(base.y, amt.y, rng),
                      jitter(base.z, amt.z, rng))
        idx = f.i("baseAxis")
        p.user[Plane] = {"axis": BASE_AXES[idx] if 0 <= idx < len(BASE_AXES) else BASE_AXES[1],
                         "rot": rolled_rot,
                         "order": rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)}

        p.rolled["pl_rgba"], p.rolled["pl_coff"] = roll_rgba(f, rng, em.config)
        if self._has_tracks:
            p.rolled["pl_off"] = jitter_offsets(f, {
                "scale": p.rolled["pl_scale"], "width": p.rolled["pl_width"],
                "height": p.rolled["pl_height"], "brightness": p.rolled["pl_bright"]})
        p.rolled["pl_emissive"] = emissive_on(f)

        _flowmap.roll(p, f, rng)

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "pl_rgba" not in rolled:
            return item
        st = p.user.get(Plane)

        item = RenderItem(kind="PLANE", pos=p.pos.copy())

        if self._has_tracks:
            f = em.f(PLANE, p)
            off = rolled.get("pl_off")
            s = with_offset(f, "scale", off)
            w, h = with_offset(f, "width", off), with_offset(f, "height", off)
            r0, g0, b0, a0 = pick_color(f, rolled.get("pl_coff"))
            bright = with_offset(f, "brightness", off)
        else:
            s = rolled["pl_scale"]
            w, h = rolled["pl_width"], rolled["pl_height"]
            r0, g0, b0, a0 = rolled["pl_rgba"]
            bright = rolled["pl_bright"]
        if not rolled.get("pl_emissive"):
            bright = 1.0

        item.size = quad_size(p, em.config, s, w, h)
        # 面内转角 = 自身的 rotation2 + ROTATEANIM 平面旋转；p.rot.z 里的三轴自旋分量扣掉，
        # 改由 _frame 绕局部轴施加
        spin = rolled.get("spin_ang")
        inplane = rolled.get("pl_spin", 0.0) + p.rot.z - (spin[2] if spin else 0.0)
        item.axis_u, item.axis_v = _frame(st, inplane, spin, em.config)
        item.rot = 0.0                     # 朝向已写入 axis_u/axis_v，glue 不得再次旋转
        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.extra["base_tint"] = (r0 * bright, g0 * bright, b0 * bright)
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        return _flowmap.apply(p, em, item)


def _frame(st, inplane, spin, cfg):
    """面片的横纵轴：基准法线上的局部横纵轴 → 面内转角 → 三轴自旋 → rotation。"""
    if st is None:
        return oriented_basis(Vec3(0.0, 0.0, 1.0), inplane)
    u, v = oriented_basis(st["axis"], inplane)
    order, applied = st["order"], cfg.rot_order_applied
    if spin and (spin[0] or spin[1] or spin[2]):
        u = rotate_euler(u, spin[0], spin[1], spin[2], order=order, applied=applied)
        v = rotate_euler(v, spin[0], spin[1], spin[2], order=order, applied=applied)
    rx, ry, rz = st["rot"]
    return (rotate_euler(u, rx, ry, rz, order=order, applied=applied),
            rotate_euler(v, rx, ry, rz, order=order, applied=applied))
