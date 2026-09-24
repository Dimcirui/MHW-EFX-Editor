# -*- coding: utf-8 -*-
"""RGBWATER —— 高光层与水膜层两层染色。

结构与 RGBFIRE 相同，区别在于两层各自的强度均为已确认的具名字段，代表色的 'weighted' 合成
直接依据这两个字段。

字段职能：

    colorSpecular / intensitySpecular         高光层的颜色与强度
    colorSheet / intensitySheet               水膜层的颜色与强度
    colorRate                                 整体亮度倍率
    intensityAlpha                            透明度强度，乘入 p.alpha 并限定不超过 1
    waterLerpGtoB                             水膜遮罩中 Green 到 Blue 的插值系数
    specularColorParam_* /                    两层各自的生命期时序块
    sheetColorParam_*

有贴图时两层遮罩为：

    水膜(Sheet)遮罩     = Alpha × mix(Green, Blue, waterLerpGtoB)
    高光(Specular)遮罩  = R × Alpha

两层遮罩都已含 Alpha，贴图 shader 的不透明度取两层遮罩的较大者，不再单独使用 Alpha。

`intensityCubeMap`（水面反射，依赖环境贴图）、`waterLerpParam_*`（插值系数自身的生命期块，
作用未知）、`normalSharpness`（法线锐度，依赖真实法线贴图）三项不参与计算。

维护约束：
- `p.rolled["layers"]` 的顺序为 (水膜色, 高光色)，glue 侧两条遮罩公式按位置对应，调换顺序会使
  两层遮罩互换。该顺序与 RGBFIRE 的 (火焰色, 烟雾色) 不是同一种排列。
"""

from ...hashes import RGBWATER
from ..registry import Behavior, register
from ..stages import SHADE
from ._common import blend_two_colors, color_param_weight, roll_color_param
from .rgbfire import _rgb


@register(RGBWATER)
class RgbWater(Behavior):
    """SHADE 阶段写入 p.color，并将 intensityAlpha 乘入 p.alpha。"""

    STAGE = SHADE
    ORDER = 61

    #: 颜色、强度与 colorRate 可由 TIML 驱动，存在轨道时逐帧重新求值；
    #: 仅在出生时采样会使颜色停留在 age=0 的取值。
    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(RGBWATER)
        if f is None:
            return
        self._has_tracks = f.has_tracks

    def on_particle_spawn(self, p, em, rng):
        f = em.f(RGBWATER, p)
        if f is None:
            return
        cfg = em.config
        p.rolled["rgbwater"] = {
            "spec": _rgb(f.raw("colorSpecular")),
            "sheet": _rgb(f.raw("colorSheet")),
            "spec_i": max(0.0, float(f.get("intensitySpecular", 1.0) or 0.0)),
            "sheet_i": max(0.0, float(f.get("intensitySheet", 1.0) or 0.0)),
            "rate": float(f.get("colorRate", 1.0) or 0.0),
            "alpha": float(f.get("intensityAlpha", 1.0) or 0.0),
            "lerp": max(0.0, min(1.0, float(f.get("waterLerpGtoB", 0.0) or 0.0))),
            "sp": roll_color_param(f, rng, cfg, "specularColorParam_"),
            "hp": roll_color_param(f, rng, cfg, "sheetColorParam_"),
        }

    def on_particle_step(self, p, em):
        st = p.rolled.get("rgbwater")
        if st is None:
            return
        spec, sheet = st["spec"], st["sheet"]
        spec_i, sheet_i, rate, alpha = st["spec_i"], st["sheet_i"], st["rate"], st["alpha"]
        lerp = st["lerp"]
        if self._has_tracks:
            f = em.f(RGBWATER, p)
            if f is not None:
                spec = _rgb(f.raw("colorSpecular"))
                sheet = _rgb(f.raw("colorSheet"))
                spec_i = max(0.0, float(f.get("intensitySpecular", 1.0) or 0.0))
                sheet_i = max(0.0, float(f.get("intensitySheet", 1.0) or 0.0))
                rate = float(f.get("colorRate", 1.0) or 0.0)
                alpha = float(f.get("intensityAlpha", 1.0) or 0.0)
                lerp = max(0.0, min(1.0, float(f.get("waterLerpGtoB", 0.0) or 0.0)))

        w0 = spec_i * color_param_weight(st["sp"], p.age)
        w1 = sheet_i * color_param_weight(st["hp"], p.age)
        tint = blend_two_colors(em.config, spec, w0, sheet, w1)
        p.color = [tint[0] * rate, tint[1] * rate, tint[2] * rate]
        # (水膜色, 高光色)，由贴图 shader 按两个遮罩分别使用
        p.rolled["layers"] = ([c * w1 * rate for c in sheet],
                              [c * w0 * rate for c in spec])
        p.rolled["rgbwater_lerp"] = lerp
        p.alpha = min(1.0, p.alpha * alpha)
