# -*- coding: utf-8 -*-
"""LIGHTNING —— 闪电，只模拟主干。

闪电从出生点沿粒子初速度方向生长，每帧长出本帧速度的长度，到 `branch0_length` 为止，之后停住
直到寿命结束。没有初速度时不画。起点随宿主平移（取粒子位置减去自身速度累计的位移），
不随宿主旋转。

形状在出生时按粒子种子生成一次，此后只随生长露出更多：

    大轮廓    waveAmplitude × sin(π × waveFrequency × s)，s 为沿全长的比例（出生端 0）
    粗折/细折 中点位移分形：先粗折 lowDetailNum 层、再细折 highDetailNum 层，每层把每段从中点
              向横向随机偏开，首层偏移 = *DetailWidth，此后每层乘 *DetailWidthCoef
    smoothLine=1 时对折线做平滑

横向偏移（波幅、两层折线）都乘 thickness / `_THICK_REF`：粗细同时放大线宽和摆幅。

外观：

    线宽      thickness × lineWidthScale（大于 1 按 1），再乘出生端→末端线性插值的
              headScale→tailScale
    不透明度  headAlpha→tailAlpha，同样沿全长线性插值
    颜色      color / colorRange，blendMode 开启时乘 brightness；再乘 branch0_intensity
    贴图 V    沿闪电从出生端 0 线性增长到末端 = waveFrequency（出生端在贴图顶边），与长度无关

不模拟：分支（branch1/2）、末端骨骼 terminalJointNo、末端形状、消失模式、flowmap。
lightningType 为 1 / 5 或 highDetailNum 为 -1 时整道不画。
"""

import math

from ...hashes import LIGHTNING
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ._common import emissive_on, oriented_basis, roll_rgba

#: 横向偏移按 thickness / _THICK_REF 缩放；取官方语料 thickness 的中位数
_THICK_REF = 70.0

#: 分形最多细分的层数（2^8 = 256 段），更细的层在预览尺度上看不出
_MAX_LAYERS = 8

#: 折线层数不足时补直线段到这个段数，保证大轮廓的正弦画得圆
_MIN_SEGMENTS = 32

#: 平滑的轮数（[1, 2, 1] / 4 滑动平均）
_SMOOTH_PASSES = 3

#: 游戏里整道不显示的 lightningType
_HIDDEN_TYPES = (1, 5)


def _layers(f, rng, scale):
    """粗折、细折两层分形逐层的偏移幅度（游戏单位），总层数不超过 _MAX_LAYERS。"""
    out = []
    for tier in ("low", "high"):
        n = f.i("branch0_%sDetailNum" % tier)
        w = jitter(f.get("branch0_%sDetailWidth" % tier), f.get("branch0_%sDetailWidthJitter" % tier), rng)
        k = jitter(f.get("branch0_%sDetailWidthCoef" % tier),
                   f.get("branch0_%sDetailWidthCoefJitter" % tier), rng)
        for i in range(max(0, n)):
            out.append(w * (k ** i) * scale)
    return out[:_MAX_LAYERS]


def _fractal(amps, rng):
    """中点位移折线：返回沿全长均匀分布的横向偏移 [(a, b)]，首尾为 0。"""
    offs = [(0.0, 0.0), (0.0, 0.0)]
    for amp in amps:
        nxt = []
        for (a0, b0), (a1, b1) in zip(offs, offs[1:]):
            nxt.append((a0, b0))
            nxt.append((0.5 * (a0 + a1) + amp * rng.uniform(-1.0, 1.0),
                        0.5 * (b0 + b1) + amp * rng.uniform(-1.0, 1.0)))
        nxt.append(offs[-1])
        offs = nxt
    # 段数不足时在每段内均匀补点，不改变形状
    seg = len(offs) - 1
    k = max(1, int(math.ceil(_MIN_SEGMENTS / float(seg))))
    if k > 1:
        dense = []
        for (a0, b0), (a1, b1) in zip(offs, offs[1:]):
            for j in range(k):
                t = j / float(k)
                dense.append((a0 + (a1 - a0) * t, b0 + (b1 - b0) * t))
        dense.append(offs[-1])
        offs = dense
    return offs


def _smooth(offs):
    """首尾固定的 [1, 2, 1] / 4 滑动平均。"""
    for _ in range(_SMOOTH_PASSES):
        offs = ([offs[0]]
                + [(0.25 * (a0 + 2.0 * a1 + a2), 0.25 * (b0 + 2.0 * b1 + b2))
                   for (a0, b0), (a1, b1), (a2, b2) in zip(offs, offs[1:], offs[2:])]
                + [offs[-1]])
    return offs


@register(LIGHTNING)
class Lightning(Behavior):
    """RENDER_BODY 阶段产出面向镜头的条带（尾→头 = 末端→出生端）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(LIGHTNING)
        if f is None:
            return
        if f.i("terminalJointNo", -1) != -1:
            em.note("LIGHTNING 的末端骨骼未模拟：预览按初速度方向画")
        if f.i("branch1_count") > 0:
            em.note("LIGHTNING 的分支未模拟：预览只画主干")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(LIGHTNING, p)
        if f is None:
            return
        speed = p.vel.length()
        d = p.vel.normalized(fallback=Vec3(0.0, 1.0, 0.0))
        thick = jitter(f.get("branch0_thickness"), f.get("branch0_thicknessJitter"), rng)
        lateral = thick / _THICK_REF
        freq = jitter(f.get("waveFrequency"), f.get("waveFrequencyJitter"), rng)
        amp = jitter(f.get("waveAmplitude"), f.get("waveAmplitudeJitter"), rng) * lateral
        offs = _fractal(_layers(f, rng, lateral), rng)
        if f.i("smoothLine") == 1:
            offs = _smooth(offs)
        # 大轮廓沿一个随机横向方向摆动
        a, b = oriented_basis(d, rng.uniform(0.0, 360.0))
        n = len(offs) - 1
        offs = [(oa + amp * math.sin(math.pi * freq * j / n), ob) for j, (oa, ob) in enumerate(offs)]
        rgba4, _roll = roll_rgba(f, rng, em.config)
        bright = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"), rng) if emissive_on(f) else 1.0
        p.user[Lightning] = {
            "moving": speed > 1e-6,
            "dir": d, "a": a, "b": b, "offs": offs, "freq": freq,
            "length": max(0.0, jitter(f.get("branch0_length"), f.get("branch0_lengthJitter"), rng)),
            "width": thick * max(0.0, min(1.0, f.get("lineWidthScale", 1.0))),
            "rgb": (rgba4[0] * bright, rgba4[1] * bright, rgba4[2] * bright),
            "alpha": rgba4[3],
            "intensity": jitter(f.get("branch0_intensity", 1.0), f.get("branch0_intensityJitter"), rng),
            "grown": 0.0,
            "own": Vec3(),      # 自身速度累计的位移；起点 = 当前位置 − own，只跟宿主平移
        }

    def on_particle_step(self, p, em):
        st = p.user.get(Lightning)
        if st is None:
            return
        st["own"] += p.vel
        st["grown"] = min(st["length"], st["grown"] + p.vel.length())

    def build_render(self, p, em, view, item):
        st = p.user.get(Lightning)
        if st is None:
            return item
        f = em.f(LIGHTNING, p)
        if f is None:
            return item
        if f.i("lightningType") in _HIDDEN_TYPES or f.i("branch0_highDetailNum") < 0:
            return RenderItem(kind="NONE")
        if not st["moving"]:
            em.note("LIGHTNING 沿粒子初速度生长：没有初速度（VELOCITY3D）时不画")
            return RenderItem(kind="NONE")
        length = st["length"]
        if length <= 0.0 or st["grown"] <= 0.0:
            return RenderItem(kind="NONE")

        offs = st["offs"]
        n = len(offs) - 1
        s_max = st["grown"] / length
        last = int(math.floor(s_max * n + 1e-9))
        samples = [(j / float(n), offs[j]) for j in range(last + 1)]
        if last < n and s_max * n - last > 1e-6:
            # 生长前端落在两点之间：按比例插出末点
            t = s_max * n - last
            (a0, b0), (a1, b1) = offs[last], offs[last + 1]
            samples.append((s_max, (a0 + (a1 - a0) * t, b0 + (b1 - b0) * t)))
        if len(samples) < 2:
            return RenderItem(kind="NONE")

        start = p.pos - st["own"]
        d, a, b = st["dir"], st["a"], st["b"]
        hs, ha = f.get("branch0_headScale", 1.0), f.get("branch0_headAlpha", 1.0)
        ts, ta = f.get("branch0_tailScale", 1.0), f.get("branch0_tailAlpha", 1.0)
        half = 0.5 * st["width"] * p.scale.x
        freq = st["freq"]
        points = []
        rows = []
        for s, (oa, ob) in reversed(samples):              # 尾→头 = 末端→出生端
            q = start + d * (s * length) + a * oa + b * ob
            points.append((q, half * (hs + (ts - hs) * s), (ha + (ta - ha) * s)))
            # 贴图 V（顶边 0）= freq × s；条带局部 v 以底边为 0，出生端落在顶边
            rows.append(1.0 - freq * s)

        k = st["intensity"]
        r, g, bl = (c * k for c in st["rgb"])
        item = RenderItem(kind="RIBBON", pos=start)
        item.points = points
        item.size = Vec3(2.0 * half, st["grown"], 1.0)
        item.color = [r * p.color[0], g * p.color[1], bl * p.color[2], st["alpha"] * p.alpha]
        # 渲染主体自身的颜色；RGBFIRE / RGBWATER 的两层颜色在 glue 侧再乘上它
        item.extra["base_tint"] = (r, g, bl)
        item.extra["uv_scale"] = (freq * s_max, 1.0, rows)
        item.extra["age"] = p.age
        return item
