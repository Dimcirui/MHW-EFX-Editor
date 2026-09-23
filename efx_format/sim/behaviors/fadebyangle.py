# -*- coding: utf-8 -*-
"""FADEBYANGLE —— 按观察方向与指定轴的夹角淡出。

字段职能：

    baseAxis / rotation / rotOrder  触发渐隐的朝向：AxisDirection6 经欧拉旋转，旋转顺序表与
                                    VELOCITY3D 相同（默认 4=ZXY，即 Ry·Rx·Rz·baseAxis）
    cutoffConeAngle                 锥角（半角），夹角在此以内完全不可见
    fadeConeAngle                   渐隐过渡区的边界，读法由 `SimConfig.fade_cone_mode` 选择：
                                    'outer' 为外边界的绝对角，'width' 为从 cutoff 起算的过渡宽度
    minAlpha                        渐隐能达到的最低 alpha
    coneVisibilityFlags             bit0 双锥：同一规则镜像到 -baseAxis
                                    bit1 排除锥体：锥内外可见性互换
                                    bit2 单独置位也互换可见性，但 bit0 置位时无效

整体反转 = bit1 OR (bit2 AND NOT bit0)。夹角取朝向与「粒子指向相机」向量之间的角度，
结果乘入 `item.color[3]`。

维护约束：
- 依赖相机，只能在渲染 pass 中计算；`view.cam_pos` 须由宿主换算到本发射器的局部游戏坐标。
"""

import math

from ...hashes import FADEBYANGLE
from ..registry import Behavior, register
from ..stages import RENDER_MOD
from ..state import BASE_AXES, Vec3
from ..vecmath import ROT_ORDER_VELOCITY, rot_order_name, rotate_euler
from ._common import emitter_rotate
from .fadebydepth import ramp

BIT_DOUBLE_CONE = 1
BIT_EXCLUDE_CONE = 2
BIT_UNKNOWN_INVERT = 4


def cone_visibility(theta, cutoff, fade, flags, mode="outer"):
    """夹角 theta（度）处的可见度 0~1，已含双锥与反转。"""
    if flags & BIT_DOUBLE_CONE:
        theta = min(theta, 180.0 - theta)
    hi = cutoff + fade if mode == "width" else fade
    v = ramp(theta, cutoff, hi)
    if (flags & BIT_EXCLUDE_CONE) or ((flags & BIT_UNKNOWN_INVERT)
                                       and not (flags & BIT_DOUBLE_CONE)):
        v = 1.0 - v
    return v


@register(FADEBYANGLE)
class FadeByAngle(Behavior):
    """RENDER_MOD 阶段按观察角度修改渲染项的 alpha。"""

    STAGE = RENDER_MOD
    ORDER = 81

    _axis = None

    def on_emitter_init(self, em, rng):
        f = em.f(FADEBYANGLE)
        if f is None:
            return
        idx = f.i("baseAxis")
        axis = BASE_AXES[idx] if 0 <= idx < len(BASE_AXES) else BASE_AXES[1]
        rot = f.raw("rotation") or (0.0, 0.0, 0.0)
        order = rot_order_name(f.i("rotOrder"), ROT_ORDER_VELOCITY)
        self._axis = rotate_euler(axis, float(rot[0]), float(rot[1]), float(rot[2]),
                                  order=order, applied=em.config.rot_order_applied)

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE" or self._axis is None:
            return item
        f = em.f(FADEBYANGLE, p)
        if f is None:
            return item
        to_cam = Vec3(view.cam_pos.x - item.pos.x, view.cam_pos.y - item.pos.y,
                      view.cam_pos.z - item.pos.z)
        n = to_cam.length()
        if n < 1e-9:
            return item
        axis = emitter_rotate(em, self._axis)
        c = (axis.x * to_cam.x + axis.y * to_cam.y + axis.z * to_cam.z) / n
        theta = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        v = cone_visibility(theta, f.get("cutoffConeAngle"), f.get("fadeConeAngle"),
                            f.i("coneVisibilityFlags"), em.config.fade_cone_mode)
        lo = max(0.0, min(1.0, f.get("minAlpha")))
        k = lo + (1.0 - lo) * v
        if k < 1.0:
            item.color[3] *= k
        return item
