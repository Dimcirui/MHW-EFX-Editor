# -*- coding: utf-8 -*-
"""PLANE —— 固定朝向的面片。

与 BILLBOARD3D 的唯一本质区别是**不朝向相机**，朝向由自身字段确定。

字段职能：

    baseAxis            面片的基准法线，与 VELOCITY3D 共用 AxisDirection6 枚举
    rotation(XYZ0)      作用于基准法线的欧拉旋转，XYZ0 的后半部分为逐轴抖动幅度
    rotationOrder       欧拉旋转顺序，与 MESH 使用同一套枚举
    rotation2(+Jitter)  绕自身法线的自旋，独立于上述朝向字段

color / colorRange / useColorRange / brightness / blendMode / scale / width / height 与
flowmap 字段组均与 BILLBOARD3D 同名同义，使用 `_common.py` 的共享实现；尺寸约定也相同，
`scale` 为倍率，`width` / `height` 为游戏单位。`correctColorNo` 与
`colorRangeCorrectColorNo` 未接入，仅记录 note。

维护约束：
- `item.extra["base_tint"]` 保存渲染主体自身的颜色，不含 RGBFIRE / RGBWATER 写入 `p.color`
  的分层色，供 glue 的两层染色分支作为逐通道滤镜使用。BILLBOARD3D 的同名字段含义相同。
"""

from ...hashes import PLANE
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from . import _flowmap
from ._common import (axis_normal, blend_name, epv_note, oriented_basis,
                      pick_color, quad_size, roll_rgba)


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
        mode = em.config.jitter_mode

        p.rolled["pl_scale"] = jitter(f.get("scale", 1.0), f.get("scaleJitter"), rng, mode)
        p.rolled["pl_width"] = jitter(f.get("width", 1.0), f.get("widthJitter"), rng, mode)
        p.rolled["pl_height"] = jitter(f.get("height", 1.0), f.get("heightJitter"), rng, mode)
        p.rolled["pl_bright"] = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"),
                                       rng, mode)
        p.rolled["pl_spin"] = jitter(f.get("rotation2"), f.get("rotation2Jitter"), rng, mode)

        base = f.xyz_lo("rotation")
        amt = f.xyz_hi("rotation")
        rolled_rot = (jitter(base.x, amt.x, rng, mode),
                      jitter(base.y, amt.y, rng, mode),
                      jitter(base.z, amt.z, rng, mode))
        normal = axis_normal(f, em.config, rolled=rolled_rot)
        p.user[Plane] = {"normal": normal}

        p.rolled["pl_rgba"], p.rolled["pl_coff"] = roll_rgba(f, rng, em.config)
        p.rolled["pl_blend"] = blend_name(f)

        _flowmap.roll(p, f, rng, mode)

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "pl_rgba" not in rolled:
            return item
        st = p.user.get(Plane)
        normal = st["normal"] if st else Vec3(0.0, 0.0, 1.0)

        item = RenderItem(kind="PLANE", pos=p.pos.copy())

        if self._has_tracks:
            f = em.f(PLANE, p)
            s = f.get("scale", 1.0)
            w, h = f.get("width", 1.0), f.get("height", 1.0)
            r0, g0, b0, a0 = pick_color(f, rolled.get("pl_coff"))
            bright = f.get("brightness", 1.0)
        else:
            s = rolled["pl_scale"]
            w, h = rolled["pl_width"], rolled["pl_height"]
            r0, g0, b0, a0 = rolled["pl_rgba"]
            bright = rolled["pl_bright"]

        item.size = quad_size(p, em.config, s, w, h)
        # 自旋 = 自身的 rotation2 与 ROTATEANIM 在 p.rot.z 上累积的平面旋转之和
        item.axis_u, item.axis_v = oriented_basis(
            normal, rolled.get("pl_spin", 0.0) + p.rot.z)
        item.rot = 0.0                     # 朝向已写入 axis_u/axis_v，glue 不得再次旋转
        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.extra["base_tint"] = (r0 * bright, g0 * bright, b0 * bright)
        item.blend = rolled["pl_blend"]
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        return _flowmap.apply(p, em, item)
