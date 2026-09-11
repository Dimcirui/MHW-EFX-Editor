# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/plane.py  —  PLANE（**固定朝向**的片）

和 BILLBOARD3D 的唯一本质区别：**不朝相机**。对应 Unity ParticleSystemRenderMode
的 Mesh/Stretched 之外那档「按自身 transform 定向的 quad」，或 UE Niagara 里
Sprite Renderer 把 Alignment 设成 Custom Direction 的用法。

    baseAxis        AxisDirection6，片的基准法线（实机确认，与 VELOCITY3D 同一套枚举）
    rotation(XYZ0)  在基准法线上叠的欧拉旋转
    rotationOrder   实机确认与 MESH 同款枚举（_TRANSFORM_ROT_ORDER）
    rotation2(+Jitter)  沿自身垂线的自旋（annotations：「与上面的 XYZ 朝向字段独立」）

其余字段（color / colorRange / useColorRange / brightness / blendMode /
scale / width / height / flowmap*）与 BILLBOARD3D 同名同义，走 _common.py 共享实现。

尺寸约定同 BILLBOARD3D：`scale`(SizeScalar) 是倍率，`width`/`height` 是游戏单位。

未处理：EPVColorSlot1/2（记 note）、flowmap 一族（属 T3 纹理部分）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import PLANE
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ._common import (axis_normal, blend_name, color_lerp_t, epv_note,
                      oriented_basis, pick_color)


@register(PLANE)
class Plane(Behavior):
    """RENDER_BODY：产出固定朝向的片（RenderItem.axis_u/axis_v 非空 → glue 不朝相机）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(PLANE)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        epv_note(f, em, "PLANE", "EPVColorSlot1", "EPVColorSlot2")

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

        # 朝向：baseAxis 经 rotation(XYZ0) 旋转。XYZ0 的后一半是逐轴抖动幅度。
        base = f.xyz_lo("rotation")
        amt = f.xyz_hi("rotation")
        rolled_rot = (jitter(base.x, amt.x, rng, mode),
                      jitter(base.y, amt.y, rng, mode),
                      jitter(base.z, amt.z, rng, mode))
        normal = axis_normal(f, em.config, rolled=rolled_rot)
        p.user[Plane] = {"normal": normal}

        t = color_lerp_t(f, rng)
        p.rolled["pl_color_t"] = t
        p.rolled["pl_rgba"] = pick_color(f, t)
        p.rolled["pl_blend"] = blend_name(f)

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
            w, h = f.get("width", 1.0) * s, f.get("height", 1.0) * s
            r0, g0, b0, a0 = pick_color(f, rolled.get("pl_color_t", 0.0))
            bright = f.get("brightness", 1.0)
        else:
            s = rolled["pl_scale"]
            w, h = rolled["pl_width"] * s, rolled["pl_height"] * s
            r0, g0, b0, a0 = rolled["pl_rgba"]
            bright = rolled["pl_bright"]

        item.size = Vec3(w * p.scale.x, h * p.scale.y, 1.0)
        # 自旋 = 属性自带的 rotation2 + ROTATEANIM 在 p.rot.z 上累积的平面旋转
        item.axis_u, item.axis_v = oriented_basis(
            normal, rolled.get("pl_spin", 0.0) + p.rot.z)
        item.rot = 0.0                     # 朝向已经烘进 axis_u/axis_v，不再给 glue 转
        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.blend = rolled["pl_blend"]
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        return item
