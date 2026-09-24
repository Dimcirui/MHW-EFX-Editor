# -*- coding: utf-8 -*-
"""REFRACTION（官方名 Distortion）—— 渲染体的源色换成背后画面。

    源色 = 背后画面的采样 × 渲染体颜色 × brightness

贴图 RGB 不参与，贴图 alpha 仍决定覆盖范围。源色之后照常走 SHADERSETTINGS 的混合方式：

    Alpha 等    输出 = 背景 × 颜色              'REFRACT'      白色即透明
    加法        输出 = 背景 × (1 + 颜色)        'REFRACT_ADD'

开启流动贴图时，背后画面的采样点沿流动方向位移，`distortionType` 决定方式：0 = 轻度折射
（小幅位移）、1 = 折射（约为 0 的 6 倍）、2 = 方向模糊（沿流向多次采样）。位移需要读回
帧缓冲，预览未实现，只按不位移的采样画，并记录 note。`alphaBlend` 把未畸变的背景按比例混回，
同样未实现。

维护约束：
- 必须排在 SHADERSETTINGS 之后：折射的输出取决于其混合方式。
- 乘法必须作用于已画出的内容（含背后的粒子），glue 层按绘制顺序画在后面。
"""

from ...hashes import REFRACTION
from ..registry import Behavior, register
from ..stages import RENDER_MOD


@register(REFRACTION)
class Refraction(Behavior):
    """RENDER_MOD 阶段按混合方式改为折射通道，逐像素处理由 glue 层完成。"""

    STAGE = RENDER_MOD
    ORDER = 90          # 必须排在颜色、序列帧与 SHADERSETTINGS(85) 之后

    def on_emitter_init(self, em, rng):
        f = em.f(REFRACTION)
        if f is None:
            return
        from ._flowmap import BIT_ENABLE as _FLOW_BIT
        from ...hashes import (BILLBOARD3D, BILLBOARD2D, PLANE, RIBBON, STRAINRIBBON,
                               LIGHTNING)
        for h in (BILLBOARD3D, BILLBOARD2D, PLANE, RIBBON, STRAINRIBBON, LIGHTNING):
            rf = em.f(h)
            if rf is None:
                continue
            if (int(rf.i("applicationRule") or 0) & _FLOW_BIT
                    or int(rf.i("enableFlowmap") or 0)):
                em.note("REFRACTION 的畸变位移（distortionType）未模拟，"
                        "预览按不位移的背景画")
                break
        if f.get("alphaBlend", 0.0):
            em.note("REFRACTION.alphaBlend（按比例混回原背景）未模拟")

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        f = em.f(REFRACTION, p)
        if f is None:
            return item
        item.blend = "REFRACT_ADD" if item.blend == "ADDITIVE" else "REFRACT"
        item.extra["refraction"] = (int(f.i("distortionType") or 0),
                                    float(f.get("alphaBlend", 0.0) or 0.0))
        return item
