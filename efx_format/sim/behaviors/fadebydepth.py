# -*- coding: utf-8 -*-
"""FADEBYDEPTH —— 按与相机的距离淡入淡出。

字段职能：

    nearFadeInStart / nearFadeInEnd     近处淡入区间：小于起点完全不可见，大于终点完全可见
    farFadeOutStart / farFadeOutEnd     远处淡出区间：小于起点完全可见，大于终点完全不可见

两段系数相乘后乘入 `item.color[3]`。区间两端相等时在该距离处硬切换。距离单位为游戏单位
（与粒子坐标相同）。距离取视线方向上的深度还是到相机的直线距离，由
`SimConfig.fade_depth_metric` 选择。

维护约束：
- 依赖相机，只能在渲染 pass 中计算；`view.cam_pos` 须由宿主换算到本发射器的局部游戏坐标。
"""

from ...hashes import FADEBYDEPTH
from ..registry import Behavior, register
from ..stages import RENDER_MOD


def ramp(d, lo, hi):
    """d 从 lo 到 hi 线性升到 1；lo >= hi 时在 hi 处硬切换。"""
    if hi <= lo:
        return 0.0 if d < hi else 1.0
    if d <= lo:
        return 0.0
    if d >= hi:
        return 1.0
    return (d - lo) / (hi - lo)


def camera_depth(view, pos, metric):
    """粒子到相机的距离：'view_depth' 为视线方向上的深度，'distance' 为直线距离。"""
    dx = pos.x - view.cam_pos.x
    dy = pos.y - view.cam_pos.y
    dz = pos.z - view.cam_pos.z
    if metric == "distance":
        return (dx * dx + dy * dy + dz * dz) ** 0.5
    f = view.cam_forward.normalized()
    # 宿主给出的视线方向可能指向相机背后，深度按绝对值取
    return abs(dx * f.x + dy * f.y + dz * f.z)


@register(FADEBYDEPTH)
class FadeByDepth(Behavior):
    """RENDER_MOD 阶段按相机距离修改渲染项的 alpha。"""

    STAGE = RENDER_MOD
    ORDER = 80

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        f = em.f(FADEBYDEPTH, p)
        if f is None:
            return item
        d = camera_depth(view, item.pos, em.config.fade_depth_metric)
        k = (ramp(d, f.get("nearFadeInStart"), f.get("nearFadeInEnd"))
             * (1.0 - ramp(d, f.get("farFadeOutStart"), f.get("farFadeOutEnd"))))
        if k < 1.0:
            item.color[3] *= k
        return item
