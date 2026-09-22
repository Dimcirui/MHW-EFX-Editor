# -*- coding: utf-8 -*-
"""ALPHACORRECTION —— 贴图 alpha 通道的阈值与伽马修正。

本属性只改变 alpha 的分布，不影响 RGB。修正按纹素而非按粒子进行，因此本 behavior 不修改
`p.alpha`，只将参数写入渲染项的 `extra["alpha_fix"]`，由 fragment shader 逐像素执行：

    a = texture.a
    a = (a < lowPass) ? 0 : pow(a, contrast_gamma)

字段职能：

    lowPass         硬阈值：alpha 低于此值时置 0；取 0 表示不裁切
    contrast_gamma  对比度／伽马，无上限。小于 1 时边缘更不透明，大于 1 时边缘更透明

`unkn0`、`unkn3`、`unknFlag2` 语义未知，不参与计算。

维护约束：
- `contrast_gamma <= 0` 必须视为中性值：`pow(a, 0)` 会使整张贴图完全不透明。
- 没有贴图的渲染路径（纯色片、POINT、MESH）无法取得逐纹素 alpha，本属性在这些路径上不生效，
  不得以整体乘 alpha 近似。
"""

from ...hashes import ALPHACORRECTION
from ..registry import Behavior, register
from ..stages import RENDER_MOD


@register(ALPHACORRECTION)
class AlphaCorrection(Behavior):
    """RENDER_MOD 阶段只向渲染项写入参数，逐像素处理由 shader 完成。"""

    STAGE = RENDER_MOD
    ORDER = 60          # 必须排在 UVSEQUENCE 之后：先确定帧，再修正该帧

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        f = em.f(ALPHACORRECTION, p)
        if f is None:
            return item
        low = float(f.get("lowPass", 0.0) or 0.0)
        gamma = float(f.get("contrast_gamma", 1.0) or 0.0)
        if low <= 0.0 and (gamma == 1.0 or gamma <= 0.0):
            return item                      # 两项均为中性值，无需交给 glue 处理
        item.extra["alpha_fix"] = (max(0.0, min(1.0, low)),
                                   gamma if gamma > 0.0 else 1.0)
        return item
