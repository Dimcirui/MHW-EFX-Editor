# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/rgbwater.py  —  RGBWATER（高光/水膜两层染色）

与 RGBFIRE 同构，字段名全部是实机对齐官方 TimelineParam 的（见 custom_codecs.py）：

    colorSpecular / intensitySpecular   高光层的颜色与强度
    colorSheet    / intensitySheet      水膜层的颜色与强度
    colorRate                           整体亮度倍率（= RGBFIRE 的 colorRate）
    intensityAlpha                      透明度强度，乘在 p.alpha 上（夹到 1）
    waterLerpGtoB                       贴图 Alpha↔Blue 插值系数（水膜遮罩用，见下）
    specularColorParam_* / sheetColorParam_*   两层各自的生命期时序块

比 RGBFIRE 好的一点：两层各自的强度都是**具名确认过的字段**，不用像那边一样靠
统计去认 fireFactor，所以 'weighted' 合成在这里是直接照字段来的。

贴图通道语义（2026-09-20 用户拿 ABCD 四通道测试贴图实机逐条测出，见
custom_codecs.py 的 `_RGBWATER_FIXED_SCHEMA` 注释）：

    水膜(Sheet)遮罩    = mix(Alpha, Blue, waterLerpGtoB)     ← 跟 RGBFIRE 的
                          smoke_mask 同构，0 时纯 Alpha 形状、1 时纯 Blue 形状
    高光(Specular)遮罩 = R × G × Alpha                        ← 三通道交集；
                          R/G 同时也在喂法线重建，Alpha 是共享的整体范围

跟下游对接方式与 RGBFIRE 一致：`p.rolled["layers"] = (水膜色, 高光色)`，
`p.rolled["rgbwater_lerp"] = waterLerpGtoB`；有贴图时 glue 的 fragment shader
按上面两条遮罩公式分别取用（见 sim_preview.py `_FRAG_SRC`）。

未参与计算（作用与我们的渲染无关或未知）：
    intensityCubeMap                    水面反射相关，需要环境贴图才谈得上
    waterLerpParam_*                    水膜插值系数自己的生命期块，作用未知
    normalSharpness（原 unknownFloat）   法线锐度，devlecture 确认，需要真实法线贴图才谈得上

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
        # (水膜色, 高光色)。贴图 shader 按 mix(A,B,lerp)/R×G×A 两个遮罩分别取用，
        # 见文件顶部说明与 sim_preview.py 的 `_FRAG_SRC`。
        p.rolled["layers"] = ([c * w1 * rate for c in sheet],
                              [c * w0 * rate for c in spec])
        p.rolled["rgbwater_lerp"] = lerp
        p.alpha = min(1.0, p.alpha * alpha)
