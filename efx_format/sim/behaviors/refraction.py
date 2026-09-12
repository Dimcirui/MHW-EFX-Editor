# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/refraction.py  —  REFRACTION（折射层）

这一块把渲染体从「往画面上加光」改成「**对背后的画面做乘法**」：

    输出 = 背后画面 × (渲染体颜色 × brightness)

实机对拍（单个白色加法 BILLBOARD3D，width=height=100，无 UVSEQUENCE）：

* 不挂 REFRACTION：brightness=10 的白面片烧成一块不透明纯白方块。
* 挂上 REFRACTION：同一块方片变成「透得见背后场景、被整体提亮」。
* 把颜色改成纯红：方片内**绿蓝通道整个消失**，只剩红，且背景的明暗层次保留。
  ⚠ 这条是关键——渲染体自己写的是 `blendMode=1`(加法)，而**加法不可能抹掉
  背景的绿蓝通道**。所以 REFRACTION **覆盖渲染体的混合模式**。
* 颜色白、brightness 从 10 改回 1：方片**完全消失**（输出 = 背景 × 1 = 背景）。
  这一条同时坐实了「乘法」和「brightness 乘进源色」两件事。

`pixelNormalOffset = 0`（语料 61%）**不产生任何像素位移**（实机确认）——所以这一档
不需要读回帧缓冲，glue 层一个乘法混合就够了。

未做（等实测）
--------------
* `pixelNormalOffset` 1/2 —— 真正的屏幕空间位移。做它要把已渲染的画面抓成纹理
  再按偏移采样；位移的来源、方向和幅度都还没有依据，先如实不做，照旧走 0 的路。
* `seeThroughBlend` —— 恒未参与。现有说明「0=背后完全遮挡」与实拍不符（这个
  样本 blend=0 却明显透得见），语义待定。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import REFRACTION
from ..registry import Behavior, register
from ..stages import RENDER_MOD


@register(REFRACTION)
class Refraction(Behavior):
    """RENDER_MOD：把渲染项改成乘法通道，逐像素的活在 glue 层。"""

    STAGE = RENDER_MOD
    ORDER = 90          # 排在颜色/序列帧那些之后：它们先把颜色定下来，这里只换混合方式

    def on_emitter_init(self, em, rng):
        f = em.f(REFRACTION)
        if f is None:
            return
        # 非 0 那两档是真的屏幕空间位移，这里没做——如实说，别让面板显示成
        # 「REFRACTION 已模拟」就完事
        if f.i("pixelNormalOffset"):
            em.note("REFRACTION.pixelNormalOffset 非 0（像素位移）未模拟，"
                    "预览只画不位移的那一档")
        if f.get("seeThroughBlend", 0.0):
            em.note("REFRACTION.seeThroughBlend 语义未确认，未参与预览")
        # 折射换掉整条输出通道，流动贴图只推 UV；两者撞车时预览保前者
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
        # 两个字段先如实带上——glue 现在只认 offset==0 这一档，
        # 非 0 的会在面板上如实报「未做」，不假装能画
        item.extra["refraction"] = (int(f.i("pixelNormalOffset") or 0),
                                    float(f.get("seeThroughBlend", 0.0) or 0.0))
        return item
