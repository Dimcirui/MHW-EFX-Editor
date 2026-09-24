# -*- coding: utf-8 -*-
"""SHADERSETTINGS —— 渲染项与背景的混合方式。

`blendStateType` 决定混合方式，**覆盖渲染体自身的设置**。渲染体上的「启用自发光」（ori_name 为
`blendMode`）只决定 brightness 是否生效，不参与混合。

    0 / 4 / 10   OPAQUE        忽略 alpha，整片覆盖背景
    1 / 9        ALPHA         普通 alpha 混合（官方面板默认 BlendAlpha，语料 86%）
    5            ALPHA         只出现在贴花 PtBehavior 上，贴花不受本属性覆盖
    2 / 7        ADDITIVE      颜色 × alpha 叠加到背景上，黑色不可见
    3            INV_MULTIPLY  背景 × (1 − 颜色 × alpha)
    8            MULTIPLY      背景 × lerp(1, 颜色, alpha)，白色不改变背景
    6            不绘制         粒子本身不画，多用于承载 PTLIFE 等的 dummy Entry

没有 SHADERSETTINGS 的 entry 保持渲染体产出的 'ALPHA'。其余字段不参与计算。

维护约束：
- 必须排在 REFRACTION 之前：折射的输出取决于这里定下的混合方式。
- 贴花有自己的 mBlendMode（`extra["own_blend"]`），不受本属性覆盖。
"""

from ...hashes import SHADERSETTINGS
from ..registry import Behavior, register
from ..stages import RENDER_MOD
from ..state import RenderItem

#: blendStateType → RenderItem.blend；None 表示不绘制
BLEND_OF_STATE = {
    0: "OPAQUE", 4: "OPAQUE", 10: "OPAQUE",
    1: "ALPHA", 5: "ALPHA", 9: "ALPHA",
    2: "ADDITIVE", 7: "ADDITIVE",
    3: "INV_MULTIPLY",
    8: "MULTIPLY",
    6: None,
}


@register(SHADERSETTINGS)
class ShaderSettings(Behavior):
    """RENDER_MOD 阶段按 blendStateType 改写渲染项的混合方式。"""

    STAGE = RENDER_MOD
    ORDER = 85          # 必须排在 REFRACTION(90) 之前

    def on_emitter_init(self, em, rng):
        f = em.f(SHADERSETTINGS)
        if f is None:
            return
        v = f.i("blendStateType")
        if v not in BLEND_OF_STATE:
            em.note("SHADERSETTINGS.blendStateType=%d 未知，预览按 Alpha 混合画" % v)
        elif BLEND_OF_STATE[v] is None:
            em.note("SHADERSETTINGS.blendStateType=%d：粒子本身不绘制" % v)

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE" or item.extra.get("own_blend"):
            return item
        f = em.f(SHADERSETTINGS, p)
        if f is None:
            return item
        v = f.i("blendStateType")
        if v not in BLEND_OF_STATE:
            item.blend = "ALPHA"
            return item
        mode = BLEND_OF_STATE[v]
        if mode is None:
            # kind='NONE' 表示明确不绘制；返回 None 会被当成没有渲染体而补绘退化点
            return RenderItem(kind="NONE")
        item.blend = mode
        return item
