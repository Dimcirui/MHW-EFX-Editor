# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/rgbfire.py  —  RGBFIRE（火/烟两层染色）

字段语义来自实机（见 schema 注释）：

    fireColor            外缘的荧光色，同时会把 smoke 也染上一层
    smokeColor           内部的颜色；对常驻主体是持久焊死的
    brightness2          ColorRate（整体亮度倍率，TIML DT 0x9F1E012E 已确认）
    fireColorParam_*     fireColor 的生命期时序块（见 _common.roll_color_param）
    smokeColorParam_*    smokeColor 的生命期时序块

brightness1 当作**火焰层的强度**
--------------------------------
它紧跟在 fireColor 后面，位置上对应 RGBWATER 的 intensitySpecular/intensitySheet。
语料侧的证据是一道有方向的门（53532 个块）：

    brightness1 != 0  →  fire 段开生命期 13.6%，smoke 段 21.9%
    brightness1 == 0  →  fire 段开生命期  2.9%，smoke 段 23.4%

fire 侧掉到 1/4.7，smoke 侧纹丝不动——这个不对称是**针对 fire 段**的，说明
brightness1 管的就是火焰那一层（0 = 这层关掉）。对照组 unkn4 同样有一半是 0，
但两侧都没有差别（11.0% vs 10.4%），不是这种门。brightness3/4 几乎从不为 0，
不是「层开关」那一类，作用未知，不参与计算。

两层怎么给下游
--------------
两条路同时走：

  - `p.color` = 压成一个的代表色（`SimConfig.rgb_tint_mode` 决定怎么合，默认
    'weighted'）。纯色片 / POINT / MESH 这些拿不到逐纹素亮度的路径用它。
  - `p.rolled["layers"] = (外缘色, 核心色)`，两层各自乘好自己的权重与 ColorRate。
    有贴图时 glue 的 fragment shader 按**贴图亮度**在两者之间插值：亮处（笔画核心）
    取核心色、暗处（边缘）取外缘色——这才是实机那两层的样子。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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
    """SHADE 阶段：写 p.color。排在 LIFE(10) 之后——LIFE 管 alpha，这里管颜色。"""

    STAGE = SHADE
    ORDER = 60

    #: fireColor/smokeColor/brightness2 有 FIELD_TO_DT 映射——挂了 TIML 就每帧
    #: 重解，同 MESH 的模式（见该文件注释：只在出生时采样会把颜色冻结在 age=0）。
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
            "fire_i": max(0.0, float(f.get("brightness1", 1.0) or 0.0)),
            "rate": float(f.get("brightness2", 1.0) or 0.0),
            "fp": roll_color_param(f, rng, cfg, "fireColorParam_"),
            "sp": roll_color_param(f, rng, cfg, "smokeColorParam_"),
        }

    def on_particle_step(self, p, em):
        st = p.rolled.get("rgbfire")
        if st is None:
            return
        fire, smoke, fire_i, rate = st["fire"], st["smoke"], st["fire_i"], st["rate"]
        if self._has_tracks:
            f = em.f(RGBFIRE, p)
            if f is not None:
                fire = _rgb(f.raw("fireColor"))
                smoke = _rgb(f.raw("smokeColor"))
                fire_i = max(0.0, float(f.get("brightness1", 1.0) or 0.0))
                rate = float(f.get("brightness2", 1.0) or 0.0)

        wf = fire_i * color_param_weight(st["fp"], p.age)
        ws = color_param_weight(st["sp"], p.age)
        tint = blend_two_colors(em.config, fire, wf, smoke, ws)
        p.color = [tint[0] * rate, tint[1] * rate, tint[2] * rate]
        # fireColor 是外缘的荧光、smokeColor 是内部色 → (外缘, 核心)
        p.rolled["layers"] = ([c * wf * rate for c in fire],
                              [c * ws * rate for c in smoke])
