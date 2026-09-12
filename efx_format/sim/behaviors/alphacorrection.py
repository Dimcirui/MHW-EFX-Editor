# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/alphacorrection.py  —  ALPHACORRECTION（贴图 alpha 的修正）

这一块**只改贴图 alpha 通道的形状，不碰 RGB**（实机确认，见 schema 注释）：

    lowPass         硬阈值裁切（类 PS 的 Threshold）：alpha 低于此值直接归 0，0=不裁
    contrast_gamma  对比度/伽马修正，无上限：越大边缘（低/中 alpha）越快变透明、核心保留

这是**逐纹素**的操作，不是逐粒子的——把它做成「整体乘个 alpha」是错的，所以这里
不动 `p.alpha`，只把两个参数挂到渲染项上（`item.extra["alpha_fix"]`），由 glue 的
fragment shader 逐像素执行：

    a = texture.a
    a = (a < lowPass) ? 0 : pow(a, contrast_gamma)

没贴图的渲染路径（纯色片 / POINT / MESH）拿不到逐纹素的 alpha，那里这一块不生效——
如实不做，而不是找个近似糊上去。

`contrast_gamma <= 0` 当成中性（不做修正）：`pow(a, 0)` 会把整片贴成全不透明，
显然不是本意，而且语料里 7488 个块中只有 **12 个**（0.16%）是 0。
取值分布：1.0 占 42%，其余多在 0.3~0.9 之间——**小于 1 是让边缘更实、大于 1 才是更透**。
`lowPass` 有 60% 是 0（不裁）。

未参与：`unkn0`（取值 1~7+，不是开关）/ `unkn3`（BT 误标成 int、实为 float，语义未知，
98% 为 0）/ `unknFlag2`（0/1 各占一半，与 gamma 取值无关联）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import ALPHACORRECTION
from ..registry import Behavior, register
from ..stages import RENDER_MOD


@register(ALPHACORRECTION)
class AlphaCorrection(Behavior):
    """RENDER_MOD：只往渲染项上挂参数，真正的逐像素处理在 shader 里。"""

    STAGE = RENDER_MOD
    ORDER = 60          # 排在 UVSEQUENCE(50) 之后：先定用哪一帧，再说这一帧怎么修

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        f = em.f(ALPHACORRECTION, p)
        if f is None:
            return item
        low = float(f.get("lowPass", 0.0) or 0.0)
        gamma = float(f.get("contrast_gamma", 1.0) or 0.0)
        if low <= 0.0 and (gamma == 1.0 or gamma <= 0.0):
            return item                      # 两项都是中性值 → 不必给 glue 加桶
        item.extra["alpha_fix"] = (max(0.0, min(1.0, low)),
                                   gamma if gamma > 0.0 else 1.0)
        return item
