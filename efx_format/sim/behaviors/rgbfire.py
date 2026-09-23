# -*- coding: utf-8 -*-
"""RGBFIRE —— 火焰层与烟雾层两层染色。

RGBFIRE 只提供颜色，其作用是从一张多通道贴图中分别取出两层颜色。官方面板名为 RGB Common，
字段使用 Fire / Smoke 术语，其中 GreenCh 即 Fire，RedCh 即 Smoke。

字段职能：

    fireColor / smokeColor      两层各自的颜色
    fireFactor / redChFactor    两层各自独立的强度，取 0 即关闭该层
    colorRate                   整体亮度倍率
    alphaFactor                 整体透明度强度，乘入 p.alpha 并限定不超过 1
    lerpAlphaToBlue             烟雾遮罩中 Alpha 与 Blue 的混合比例
    fireColorParam_* /          两层各自的生命期时序块（出现、保持、消失），
    smokeColorParam_*           见 `_common.roll_color_param`

贴图通道分工为 R=烟雾密度、G=火焰强度、B=辅助弥散层（无独立调色参数）、A=轮廓遮罩。
两层颜色以两种形式同时提供给下游：

  - `p.color` 为合成后的代表色（合成方式由 `SimConfig.rgb_tint_mode` 决定），供纯色片、
    POINT、MESH 等无法取得逐纹素通道的路径使用。
  - `p.rolled["layers"]` 为 (火焰色, 烟雾色)，各自已乘权重与 colorRate；
    `p.rolled["rgbfire_lerp"]` 为 lerpAlphaToBlue。有贴图时由 fragment shader 分别计算两层
    遮罩并着色：

        fire_mask  = G                                      火焰层不受 B / Alpha 影响
        smoke_mask = R × mix(Alpha, Blue, lerpAlphaToBlue)

    lerpAlphaToBlue 取 0 时烟雾以 Alpha 为范围，R 决定其中的显示部分；取 1 时 Alpha 项完全由
    Blue 替代。

维护约束：
- 必须同时提供代表色与分层色。只提供代表色时，有贴图的路径失去通道语义；只提供分层色时，
  无贴图的路径没有颜色。
- `lighting`、`lifeType`、`correctColorNo` 三项作用未知或未接入，不参与计算。
"""

from ...hashes import RGBFIRE
from ..registry import Behavior, register
from ..stages import SHADE
from ._common import blend_two_colors, color_param_weight, roll_color_param


def _rgb(v):
    """XYZ type 2（ubyte×3 + pad）→ 0~1 的三元组。"""
    v = v or (255, 255, 255, 255)
    return (v[0] / 255.0, v[1] / 255.0, v[2] / 255.0)


@register(RGBFIRE)
class RgbFire(Behavior):
    """SHADE 阶段写入 p.color，并将 alphaFactor 乘入 p.alpha；排在 LIFE 之后。"""

    STAGE = SHADE
    ORDER = 60

    #: fireColor / smokeColor / colorRate / alphaFactor 可由 TIML 驱动，存在轨道时逐帧重新求值；
    #: 仅在出生时采样会使颜色停留在 age=0 的取值。
    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(RGBFIRE)
        if f is None:
            return
        self._has_tracks = f.has_tracks

    def on_particle_spawn(self, p, em, rng):
        f = em.f(RGBFIRE, p)
        if f is None:
            return
        cfg = em.config
        if f.i("fireColorParam_lifeType") or f.i("smokeColorParam_lifeType"):
            em.note("RGBFIRE 的 lifeType 非 0（作用未知，按 0 处理）")
        p.rolled["rgbfire"] = {
            "fire": _rgb(f.raw("fireColor")),
            "smoke": _rgb(f.raw("smokeColor")),
            "fire_i": max(0.0, float(f.get("fireFactor", 1.0) or 0.0)),
            "smoke_i": max(0.0, float(f.get("redChFactor", 1.0) or 0.0)),
            "rate": float(f.get("colorRate", 1.0) or 0.0),
            "alpha": float(f.get("alphaFactor", 1.0) or 0.0),
            "lerp": max(0.0, min(1.0, float(f.get("lerpAlphaToBlue", 0.0) or 0.0))),
            "fp": roll_color_param(f, rng, cfg, "fireColorParam_"),
            "sp": roll_color_param(f, rng, cfg, "smokeColorParam_"),
        }

    def on_particle_step(self, p, em):
        st = p.rolled.get("rgbfire")
        if st is None:
            return
        fire, smoke = st["fire"], st["smoke"]
        fire_i, smoke_i, rate, lerp = st["fire_i"], st["smoke_i"], st["rate"], st["lerp"]
        alpha = st["alpha"]
        if self._has_tracks:
            f = em.f(RGBFIRE, p)
            if f is not None:
                fire = _rgb(f.raw("fireColor"))
                smoke = _rgb(f.raw("smokeColor"))
                fire_i = max(0.0, float(f.get("fireFactor", 1.0) or 0.0))
                smoke_i = max(0.0, float(f.get("redChFactor", 1.0) or 0.0))
                rate = float(f.get("colorRate", 1.0) or 0.0)
                alpha = float(f.get("alphaFactor", 1.0) or 0.0)
                lerp = max(0.0, min(1.0, float(f.get("lerpAlphaToBlue", 0.0) or 0.0)))

        wf = fire_i * color_param_weight(st["fp"], p.age)
        ws = smoke_i * color_param_weight(st["sp"], p.age)
        tint = blend_two_colors(em.config, fire, wf, smoke, ws)
        p.color = [tint[0] * rate, tint[1] * rate, tint[2] * rate]
        p.alpha = min(1.0, p.alpha * max(0.0, alpha))
        # (火焰色, 烟雾色)，由贴图 shader 按两个遮罩分别使用
        p.rolled["layers"] = ([c * wf * rate for c in fire],
                              [c * ws * rate for c in smoke])
        p.rolled["rgbfire_lerp"] = lerp
