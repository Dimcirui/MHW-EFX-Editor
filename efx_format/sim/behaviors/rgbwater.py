# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/rgbwater.py  —  RGBWATER（高光/水膜两层染色）

与 RGBFIRE 同构，字段名全部是实机对齐官方 TimelineParam 的（见 custom_codecs.py）：

    colorSpecular / intensitySpecular   高光层的颜色与强度
    colorSheet    / intensitySheet      水膜层的颜色与强度
    colorRate                           整体亮度倍率（= RGBFIRE 的 brightness2）
    intensityAlpha                      透明度强度，乘在 p.alpha 上（夹到 1）
    specularColorParam_* / sheetColorParam_*   两层各自的生命期时序块

比 RGBFIRE 好的一点：两层各自的强度都是**具名确认过的字段**，不用像那边一样靠
统计去认 brightness1，所以 'weighted' 合成在这里是直接照字段来的。

未参与计算（作用与我们的渲染无关或未知）：
    waterLerpGtoB / intensityCubeMap    水面反射相关，需要环境贴图才谈得上
    waterLerpParam_*                    上面那个标量的生命期块
    unknownFloat                        无对应 TimelineParam，众数 0.3

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import RGBWATER
from ..registry import Behavior, register
from ..stages import SHADE
from ._common import blend_two_colors, color_param_weight, roll_color_param
from .rgbfire import _rgb


@register(RGBWATER)
class RgbWater(Behavior):
    """SHADE 阶段：写 p.color，并把 intensityAlpha 乘进 p.alpha。"""

    STAGE = SHADE
    ORDER = 61

    #: colorSpecular/colorSheet/intensity*/colorRate 有 FIELD_TO_DT 映射——挂了
    #: TIML 就每帧重解，同 RGBFIRE/MESH 的模式。
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
            "sp": roll_color_param(f, rng, cfg, "specularColorParam_"),
            "hp": roll_color_param(f, rng, cfg, "sheetColorParam_"),
        }

    def on_particle_step(self, p, em):
        st = p.rolled.get("rgbwater")
        if st is None:
            return
        spec, sheet = st["spec"], st["sheet"]
        spec_i, sheet_i, rate, alpha = st["spec_i"], st["sheet_i"], st["rate"], st["alpha"]
        if self._has_tracks:
            f = em.f(RGBWATER, p)
            if f is not None:
                spec = _rgb(f.raw("colorSpecular"))
                sheet = _rgb(f.raw("colorSheet"))
                spec_i = max(0.0, float(f.get("intensitySpecular", 1.0) or 0.0))
                sheet_i = max(0.0, float(f.get("intensitySheet", 1.0) or 0.0))
                rate = float(f.get("colorRate", 1.0) or 0.0)
                alpha = float(f.get("intensityAlpha", 1.0) or 0.0)

        w0 = spec_i * color_param_weight(st["sp"], p.age)
        w1 = sheet_i * color_param_weight(st["hp"], p.age)
        tint = blend_two_colors(em.config, spec, w0, sheet, w1)
        p.color = [tint[0] * rate, tint[1] * rate, tint[2] * rate]
        # (外缘, 核心)，与 RGBFIRE 同一约定。⚠ 水这边哪一层在核心没有实机数据，
        # 暂按「高光在核心」处理（高光本来就是亮处那一层）。
        p.rolled["layers"] = ([c * w1 * rate for c in sheet],
                              [c * w0 * rate for c in spec])
        p.alpha = min(1.0, p.alpha * alpha)
