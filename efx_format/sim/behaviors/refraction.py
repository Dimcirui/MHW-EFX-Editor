# -*- coding: utf-8 -*-
"""REFRACTION（官方名 Distortion）—— 渲染体的源色换成背后画面。

    源色 = 背后画面的采样 × 渲染体颜色 × brightness

贴图 RGB 不参与，贴图 alpha 仍决定覆盖范围。源色之后照常走 SHADERSETTINGS 的混合方式：

    Alpha 等    输出 = 背景 × 颜色              'REFRACT'      白色即透明
    加法        输出 = 背景 × (1 + 颜色)        'REFRACT_ADD'

开启流动贴图时，背后画面的采样点沿流动方向位移，位移量随流动贴图的相位推进，与镜头位置无关。
`distortionType` 决定方式：0 = 轻度折射（小幅位移）、1 = 折射（约为 0 的 6 倍）、2 = 方向模糊
（沿流向多次采样）。`alphaBlend` 按线性把未畸变的背景混回，1 时两者各半。读回帧缓冲与位移
由 glue 层完成；条带类渲染体不带流动贴图数据，按不位移的背景画并记录 note。

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
        from ...hashes import RIBBON, STRAINRIBBON, LIGHTNING
        for h in (RIBBON, STRAINRIBBON, LIGHTNING):
            rf = em.f(h)
            if rf is None:
                continue
            if (int(rf.i("applicationRule") or 0) & _FLOW_BIT
                    or int(rf.i("enableFlowmap") or 0)):
                em.note("条带上的 REFRACTION 畸变位移未模拟，预览按不位移的背景画")
                break

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
