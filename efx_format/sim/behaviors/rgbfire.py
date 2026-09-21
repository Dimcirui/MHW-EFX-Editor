# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/rgbfire.py  —  RGBFIRE（火/烟两层染色）

字段语义来自实机（见 schema 注释）：

    fireColor            火焰（GreenCh）层的颜色
    smokeColor           烟雾（RedCh）层的颜色
    fireFactor/redChFactor  两层各自独立的强度旋钮（已实机确认门控效果，见下）
    colorRate            ColorRate（整体亮度倍率，TIML DT 0x9F1E012E 已确认；2026-09-20
                          改值实机测试订正，原挂在 brightness2 上是错的）
    alphaFactor          全局透明度强度，效果暂未接入模拟
    fireColorParam_*     fireColor 的生命期时序块（见 _common.roll_color_param）
    smokeColorParam_*    smokeColor 的生命期时序块

fireFactor/redChFactor 是每层各自的强度旋钮
------------------------------------------
devlecture P26 确认 GreenCh=Fire、RedCh=Smoke。语料侧证据是一道有方向的门
（53532 个块）：

    fireFactor != 0  →  fire 段开生命期 13.6%，smoke 段 21.9%
    fireFactor == 0  →  fire 段开生命期  2.9%，smoke 段 23.4%

fire 侧掉到 1/4.7，smoke 侧纹丝不动——这个不对称是**针对 fire 段**的，说明
fireFactor 管的就是火焰那一层（0 = 这层关掉）。redChFactor 跟 fireFactor 同一识别度、
同一实机测试批次，按镜像关系认作烟雾层的同款旋钮，两者都已接入权重（`fire_i`/
`smoke_i`）。alphaFactor/colorRate 几乎从不为 0，不是「层开关」那一类，跟
fireFactor/redChFactor 不是同一种字段；colorRate 是整体亮度倍率（已接入 `rate`），
alphaFactor 效果暂未接入模拟。

贴图通道语义与两层怎么给下游
--------------------------
devlecture 面板标题是 RGB Common，字段全用 Fire/Smoke 术语，且官方强调纹理通道
按 R=烟密度、G=火焰强度、B=辅助弥散层（无独立调色入口）、A=轮廓遮罩 分工，
`lerpAlphaToBlue` 就是把 A 按比例混入 B。两条路同时走：

  - `p.color` = 压成一个的代表色（`SimConfig.rgb_tint_mode` 决定怎么合，默认
    'weighted'）。纯色片 / POINT / MESH 这些拿不到逐纹素通道的路径用它。
  - `p.rolled["layers"] = (火焰色, 烟雾色)`，各自乘好自己的权重、ColorRate；
    `p.rolled["rgbfire_lerp"] = lerpAlphaToBlue`。有贴图时 glue 的 fragment
    shader 按通道语义分别取火焰/烟雾的遮罩再各自上色（见 sim_preview.py
    `_FRAG_SRC`）：

        fire_mask  = G                                      ← 独立，不掺 B/A
        smoke_mask = R × mix(Alpha, Blue, lerpAlphaToBlue)   ← 多插一个 Alpha↔Blue 系数

    GreenCh（火焰）恒不受 B/Alpha 影响；lerpAlphaToBlue=0 时烟雾以 Alpha 为底、
    R 在其中刻出实际显示的部分，=1 时 Alpha 项被 Blue 完全顶替。

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

    #: fireColor/smokeColor/colorRate 有 FIELD_TO_DT 映射——挂了 TIML 就每帧
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
            "fire_i": max(0.0, float(f.get("fireFactor", 1.0) or 0.0)),
            "smoke_i": max(0.0, float(f.get("redChFactor", 1.0) or 0.0)),
            "rate": float(f.get("colorRate", 1.0) or 0.0),
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
        if self._has_tracks:
            f = em.f(RGBFIRE, p)
            if f is not None:
                fire = _rgb(f.raw("fireColor"))
                smoke = _rgb(f.raw("smokeColor"))
                fire_i = max(0.0, float(f.get("fireFactor", 1.0) or 0.0))
                smoke_i = max(0.0, float(f.get("redChFactor", 1.0) or 0.0))
                rate = float(f.get("colorRate", 1.0) or 0.0)
                lerp = max(0.0, min(1.0, float(f.get("lerpAlphaToBlue", 0.0) or 0.0)))

        wf = fire_i * color_param_weight(st["fp"], p.age)
        ws = smoke_i * color_param_weight(st["sp"], p.age)
        tint = blend_two_colors(em.config, fire, wf, smoke, ws)
        p.color = [tint[0] * rate, tint[1] * rate, tint[2] * rate]
        # (火焰色, 烟雾色)；贴图 shader 按 G/R×mix(A,B,lerp) 两个遮罩分别取用，
        # 见文件顶部说明与 sim_preview.py 的 `_FRAG_SRC`。
        p.rolled["layers"] = ([c * wf * rate for c in fire],
                              [c * ws * rate for c in smoke])
        p.rolled["rgbfire_lerp"] = lerp
