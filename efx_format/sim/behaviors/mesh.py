# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/mesh.py  —  MESH（宿主绑定的 mod3 网格）

分工
----
核心层**拿不到几何**——mod3 的顶点在宿主里（Blender 侧 `mod3_link.py` 已经把
mod3 导入并绑在 MESH 属性的 `efx_mesh_target` 上）。所以本 behavior 只产出
「在这个位置、按这个变换、用这个颜色，画那个绑定的网格」，具体怎么画交给 glue：

    item.kind = 'MESH'
    item.pos / item.size(=逐轴缩放) / item.extra['rot'](欧拉角，度)
    item.extra['viscon'] = visconIndex   —— 选 mod3 里哪一组网格
    item.extra['emissive'] = (r,g,b,a)   —— 自发光色，glue 可叠加

这条分界和 BILLBOARD3D 一样干净：核心只说「画什么、在哪」，glue 知道「怎么画」。

字段
----
    rotation(XYZ0)            逐轴旋转（固定/抖动成对）
    rotation2(+Jitter)        额外自旋
    rotationOrder             _TRANSFORM_ROT_ORDER
    scale(XYZ0)               逐轴缩放
    global_scale(+Jitter)     整体缩放倍率
    visconIndex(+Jitter)      「指定调用所链接 mod3 内 Visible Condition 与此值相同
                              的网格」（annotations 原话）
    color / colorRange / useColorRange        基础色
    emissiveColor / emissiveColorRange        自发光色
    colorRate(+Jitter)        颜色倍率（≈ BILLBOARD3D 的 brightness/ColorRate）
    emissiveColorRate(+Jitter) 自发光倍率

未处理：affectedByLight / shadowCastBitflag / tracking_flags / enableIntensity*
（都是渲染管线开关，预览里没有对应概念）、epv_color_slot1/2（记 note）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import MESH
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name
from ._common import epv_note, pick_color


@register(MESH)
class Mesh(Behavior):
    """RENDER_BODY：产出 kind='MESH'，几何由 glue 从绑定对象取。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(MESH)
        if f is None:
            return
        epv_note(f, em, "MESH", "epv_color_slot1", "epv_color_slot2")
        em.note("MESH 的几何来自绑定的 mod3；未绑定时预览只画一个占位框")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(MESH, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        # 逐轴旋转 + 额外自旋
        rb, ra = f.xyz_lo("rotation"), f.xyz_hi("rotation")
        rot = Vec3(jitter(rb.x, ra.x, rng, mode),
                   jitter(rb.y, ra.y, rng, mode),
                   jitter(rb.z, ra.z, rng, mode))
        rot.z += jitter(f.get("rotation2"), f.get("rotation2Jitter"), rng, mode)
        p.rolled["me_rot"] = rot
        p.rolled["me_order"] = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)

        # 逐轴缩放 × 整体缩放
        sb, sa = f.xyz_lo("scale"), f.xyz_hi("scale")
        g = jitter(f.get("global_scale", 1.0), f.get("global_scale_jitter"), rng, mode)
        p.rolled["me_scale"] = Vec3(jitter(sb.x, sa.x, rng, mode) * g,
                                    jitter(sb.y, sa.y, rng, mode) * g,
                                    jitter(sb.z, sa.z, rng, mode) * g)

        p.rolled["me_viscon"] = jitter_int(f.get("visconIndex"),
                                           f.get("visconIndexJitter"), rng, mode)

        t = 0.0 if f.i("disableAllColorRange") else (
            rng.random() if f.i("useColorRange") else 0.0)
        p.rolled["me_rgba"] = pick_color(f, t)
        p.rolled["me_rate"] = jitter(f.get("colorRate", 1.0), f.get("colorRateJitter"),
                                     rng, mode)

        et = rng.random() if (f.i("useEmissiveColorRange")
                              and not f.i("disableAllColorRange")) else 0.0
        if f.i("useEmissiveColor"):
            er, eg, eb, ea = pick_color(f, et, "emissiveColor", "emissiveColorRange")
            rate = jitter(f.get("emissiveColorRate", 1.0),
                          f.get("emissiveColorRateJitter"), rng, mode)
            p.rolled["me_emissive"] = (er * rate, eg * rate, eb * rate, ea)
        else:
            p.rolled["me_emissive"] = (0.0, 0.0, 0.0, 0.0)

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "me_rgba" not in rolled:
            return item

        r0, g0, b0, a0 = rolled["me_rgba"]
        rate = rolled["me_rate"]
        s = rolled["me_scale"]

        item = RenderItem(kind="MESH", pos=p.pos.copy())
        item.size = Vec3(s.x * p.scale.x, s.y * p.scale.y, s.z * p.scale.z)
        item.color = [r0 * rate * p.color[0],
                      g0 * rate * p.color[1],
                      b0 * rate * p.color[2],
                      a0 * p.alpha]
        item.blend = "ALPHA"           # MESH 没有 blendMode 字段；网格按实心处理
        item.extra["rot"] = rolled["me_rot"] + p.rot     # 属性旋转 + ROTATEANIM 累积
        item.extra["rot_order"] = rolled["me_order"]
        item.extra["viscon"] = rolled["me_viscon"]
        item.extra["emissive"] = rolled["me_emissive"]
        item.extra["age"] = p.age
        return item
