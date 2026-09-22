# -*- coding: utf-8 -*-
"""REFRACTION —— 将渲染体从叠加光照改为与背景相乘。

    输出 = 背景 × (渲染体颜色 × brightness)

该乘法**覆盖渲染体自身的 blendMode**：即使渲染体设为加法混合，附加 REFRACTION 后仍按乘法
输出。`brightness` 乘入源色，因此白色且 brightness=1 的渲染体不改变背景，视觉上完全消失。

`pixelNormalOffset` 取 0 时不产生像素位移，无需读回帧缓冲，glue 层以乘法混合即可实现。取 1 / 2
时为屏幕空间位移，未实现，按取 0 处理并记录 note。`seeThroughBlend` 语义未确认，不参与计算。

维护约束：
- 必须显式设置 `item.blend = "MULTIPLY"`，不得沿用渲染体自身的混合模式。
- 折射替换整条输出通道，flowmap 仅偏移 UV。同一渲染体同时启用两者时，预览保留折射。
"""

from ...hashes import REFRACTION
from ..registry import Behavior, register
from ..stages import RENDER_MOD


@register(REFRACTION)
class Refraction(Behavior):
    """RENDER_MOD 阶段将渲染项改为乘法混合，逐像素处理由 glue 层完成。"""

    STAGE = RENDER_MOD
    ORDER = 90          # 必须排在颜色与序列帧之后：前者确定颜色，此处只更换混合方式

    def on_emitter_init(self, em, rng):
        f = em.f(REFRACTION)
        if f is None:
            return
        if f.i("pixelNormalOffset"):
            em.note("REFRACTION.pixelNormalOffset 非 0（像素位移）未模拟，"
                    "预览只画不位移的那一档")
        if f.get("seeThroughBlend", 0.0):
            em.note("REFRACTION.seeThroughBlend 语义未确认，未参与预览")
        from ._flowmap import BIT_ENABLE as _FLOW_BIT
        from ...hashes import BILLBOARD3D, BILLBOARD2D, PLANE
        for h in (BILLBOARD3D, BILLBOARD2D, PLANE):
            rf = em.f(h)
            if rf is not None and (int(rf.i("applicationRule") or 0) & _FLOW_BIT):
                em.note("同一个渲染体上折射与流动贴图同时启用，预览保折射、"
                        "不做流动位移")
                break

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        f = em.f(REFRACTION, p)
        if f is None:
            return item
        item.blend = "MULTIPLY"
        # glue 仅支持 offset==0，两个字段仍原样传递
        item.extra["refraction"] = (int(f.i("pixelNormalOffset") or 0),
                                    float(f.get("seeThroughBlend", 0.0) or 0.0))
        return item
