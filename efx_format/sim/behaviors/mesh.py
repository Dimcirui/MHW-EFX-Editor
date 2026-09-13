# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/mesh.py  —  MESH（宿主绑定的 mod3 网格）

分工
----
核心层**拿不到几何**——mod3 的顶点在宿主里（Blender 侧 `mod3_link.py` 已经把
mod3 导入并绑在 MESH 属性的 `efx_mesh_target` 上）。所以本 behavior 只产出
「在这个位置、按这个变换、用这个颜色，画那个绑定的网格」，具体怎么画交给 glue：

    item.kind = 'MESH'
    item.pos / item.size(=逐轴缩放) / item.extra['rot'](欧拉角，度；含发射器旋转)
    item.extra['viscon'] = visconIndex   —— 选 mod3 里哪一组网格
    item.extra['emissive'] = (r,g,b,a)   —— 自发光色，glue 可叠加

这条分界和 BILLBOARD3D 一样干净：核心只说「画什么、在哪」，glue 知道「怎么画」。

字段
----
    rotation(XYZ0)            逐轴旋转（固定/抖动成对）。⚠ 曾经这一块的字节边界划错了
                              8 个字节，于是「X」拿到一个非角度字段、「Y」拿到真 X、
                              「Z」拿到真 Y，而真正的 Z 被单独叫成 rotation2。
                              现在 rotation 就是完整的三轴，没有额外的标量旋转。
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
from ._common import epv_note, pick_color, roll_rgba


@register(MESH)
class Mesh(Behavior):
    """RENDER_BODY：产出 kind='MESH'，几何由 glue 从绑定对象取。"""

    STAGE = RENDER_BODY
    ORDER = 100

    #: 本块有没有 TIML 曲线。挂了才在 build_render 逐帧重解 scale/color——同
    #: BILLBOARD3D/PLANE 的模式。常见的「淡入淡出」用 scale 的 A1 曲线做（age=0
    #: 起多半是 0），只在出生时采一次样会把网格冻结在 0 缩放上、永久不可见。
    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(MESH)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        epv_note(f, em, "MESH", "epv_color_slot1", "epv_color_slot2")
        em.note("MESH 的几何来自绑定的 mod3；未绑定时预览只画一个占位框")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(MESH, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        # 逐轴旋转（X/Y/Z 各自的固定+随机）
        rb, ra = f.xyz_lo("rotation"), f.xyz_hi("rotation")
        p.rolled["me_rot"] = Vec3(jitter(rb.x, ra.x, rng, mode),
                                  jitter(rb.y, ra.y, rng, mode),
                                  jitter(rb.z, ra.z, rng, mode))
        p.rolled["me_order"] = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)

        # 逐轴缩放 × 整体缩放
        sb, sa = f.xyz_lo("scale"), f.xyz_hi("scale")
        g = jitter(f.get("global_scale", 1.0), f.get("global_scale_jitter"), rng, mode)
        p.rolled["me_scale"] = Vec3(jitter(sb.x, sa.x, rng, mode) * g,
                                    jitter(sb.y, sa.y, rng, mode) * g,
                                    jitter(sb.z, sa.z, rng, mode) * g)

        p.rolled["me_viscon"] = jitter_int(f.get("visconIndex"),
                                           f.get("visconIndexJitter"), rng, mode)

        p.rolled["me_rgba"], p.rolled["me_coff"] = roll_rgba(
            f, rng, em.config, disable="disableAllColorRange")
        p.rolled["me_rate"] = jitter(f.get("colorRate", 1.0), f.get("colorRateJitter"),
                                     rng, mode)

        if f.i("useEmissiveColor"):
            (er, eg, eb, ea), eoff = roll_rgba(
                f, rng, em.config, "emissiveColor", "emissiveColorRange",
                gate="useEmissiveColorRange", disable="disableAllColorRange")
            rate = jitter(f.get("emissiveColorRate", 1.0),
                          f.get("emissiveColorRateJitter"), rng, mode)
            p.rolled["me_emissive"] = (er * rate, eg * rate, eb * rate, ea)
            p.rolled["me_ecoff"] = eoff
        else:
            p.rolled["me_emissive"] = (0.0, 0.0, 0.0, 0.0)
            p.rolled["me_ecoff"] = None

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "me_rgba" not in rolled:
            return item

        if self._has_tracks:        # 挂了 TIML → rotation/scale/color 可能逐帧变，重解
            f = em.f(MESH, p)
            rot = f.xyz_lo("rotation")
            sb = f.xyz_lo("scale")
            g = f.get("global_scale", 1.0)
            s = Vec3(sb.x * g, sb.y * g, sb.z * g)
            r0, g0, b0, a0 = pick_color(f, rolled.get("me_coff"))
            rate = f.get("colorRate", 1.0)
            if f.i("useEmissiveColor"):
                er, eg, eb, ea = pick_color(f, rolled.get("me_ecoff"),
                                            "emissiveColor", "emissiveColorRange")
                erate = f.get("emissiveColorRate", 1.0)
                emissive = (er * erate, eg * erate, eb * erate, ea)
            else:
                emissive = (0.0, 0.0, 0.0, 0.0)
        else:
            rot = rolled["me_rot"]
            r0, g0, b0, a0 = rolled["me_rgba"]
            rate = rolled["me_rate"]
            s = rolled["me_scale"]
            emissive = rolled["me_emissive"]

        item = RenderItem(kind="MESH", pos=p.pos.copy())
        item.size = Vec3(s.x * p.scale.x, s.y * p.scale.y, s.z * p.scale.z)
        item.color = [r0 * rate * p.color[0],
                      g0 * rate * p.color[1],
                      b0 * rate * p.color[2],
                      a0 * p.alpha]
        item.blend = "ALPHA"           # MESH 没有 blendMode 字段；网格按实心处理
        # 属性旋转 + ROTATEANIM 累积 + **发射器自己的旋转** + **从 PTLIFE 父实例
        # 继承的旋转**。`em.rot_dynamic` 是「宿主没有替我们套的那部分」：根 entry
        # 上它只含 TRANSFORM3D 的 rotation_velocity 累积（静态部分由宿主摆位），
        # 子实例上它还含静态 rotate（子实例没有宿主，见 scene.py 的 `_child_config`）。
        # `em.host_rotation` 是父实例转起来时逐帧传下来的那份（见
        # scene.py::SimScene._follow）——父发射器转，召唤出的子发射器也要跟着转。
        # 两种情形加上去都是对的，所以不设门。
        # 实例：wp11_017 的 aura32a/b/c 只差发射器静态 rotate Z 的 0 / ±120°，
        # 不加这一项三份就完全重叠。
        item.extra["rot"] = rot + p.rot + em.rot_dynamic + em.host_rotation
        item.extra["rot_order"] = rolled["me_order"]
        item.extra["viscon"] = rolled["me_viscon"]
        item.extra["emissive"] = emissive
        item.extra["age"] = p.age
        return item
