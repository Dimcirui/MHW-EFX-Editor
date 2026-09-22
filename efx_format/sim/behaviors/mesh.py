# -*- coding: utf-8 -*-
"""MESH —— 宿主绑定的 mod3 网格。

核心层无法取得几何数据：mod3 的顶点位于宿主中（Blender 侧由 `mod3_link.py` 导入 mod3 并绑定到
MESH 属性的 `efx_mesh_target`）。因此本 behavior 只产出绘制所需的位置、变换与颜色，具体绘制由
glue 完成：

    item.kind = 'MESH'
    item.pos / item.size            位置与逐轴缩放
    item.extra['rot']               欧拉角，单位度，已包含发射器旋转
    item.extra['rot_order']
    item.extra['viscon']            选择 mod3 中的哪一组网格
    item.extra['emissive']          自发光色，由 glue 叠加

字段职能：

    rotation(XYZ0)              完整的三轴旋转，各轴由固定值与抖动幅度成对组成；不存在额外的标量旋转字段
    rotationOrder               欧拉旋转顺序，与 TRANSFORM3D 相同
    scale(XYZ0)                 逐轴缩放
    global_scale(+Jitter)       整体缩放倍率，与逐轴缩放相乘
    visconIndex(+Jitter)        选择所链接 mod3 中 Visible Condition 与该值相同的网格
    color / colorRange /        基础色
    useColorRange
    emissiveColor /             自发光色
    emissiveColorRange
    colorRate(+Jitter) /        两者各自的倍率
    emissiveColorRate(+Jitter)

affectedByLight / shadowCastBitflag / tracking_flags / enableIntensity* 均为渲染管线开关，
预览中没有对应实现，不参与计算；`epv_color_slot1/2` 仅记录 note。

维护约束：
- 带 TIML 的属性必须在 `build_render` 中逐帧重新求值 rotation / scale / color。常见的淡入淡出
  通过 scale 的 A1 曲线实现，age=0 时多为 0；仅在出生时采样会使网格停留在 0 缩放、始终不可见。
- `item.extra['rot']` 必须是四项之和：属性自身的 rotation、ROTATEANIM 的累积、
  `em.rot_dynamic`（宿主未施加的部分：根 entry 上只含 TRANSFORM3D 的 rotation_velocity 累积，
  子实例上还包含静态 rotate）与 `em.host_rotation`（父实例旋转时逐帧传递的部分）。两种情形下
  相加均正确，因此不设条件判断。
- `item.blend` 固定为 `'ALPHA'`：MESH 没有 blendMode 字段，网格按不透明处理。
- `item.extra["base_tint"]` 保存渲染主体自身的颜色，不含 RGBFIRE / RGBWATER 写入 `p.color`
  的分层色，供 glue 的两层染色分支作为逐通道滤镜使用。
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
    """RENDER_BODY 阶段产出 kind='MESH'，几何由 glue 从绑定对象读取。"""

    STAGE = RENDER_BODY
    ORDER = 100

    #: 本属性是否带 TIML 曲线；带曲线时在 build_render 中逐帧重新求值。
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

        rb, ra = f.xyz_lo("rotation"), f.xyz_hi("rotation")
        p.rolled["me_rot"] = Vec3(jitter(rb.x, ra.x, rng, mode),
                                  jitter(rb.y, ra.y, rng, mode),
                                  jitter(rb.z, ra.z, rng, mode))
        p.rolled["me_order"] = rot_order_name(f.i("rotationOrder"), ROT_ORDER_TRANSFORM)

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

        if self._has_tracks:
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
        item.extra["base_tint"] = (r0 * rate, g0 * rate, b0 * rate)
        item.blend = "ALPHA"
        item.extra["rot"] = rot + p.rot + em.rot_dynamic + em.host_rotation
        item.extra["rot_order"] = rolled["me_order"]
        item.extra["viscon"] = rolled["me_viscon"]
        item.extra["emissive"] = emissive
        item.extra["age"] = p.age
        return item
