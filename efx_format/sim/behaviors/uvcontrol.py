# -*- coding: utf-8 -*-
"""UVCONTROL —— UV 的滚动、缩放与流动贴图。

`blender_efx/uvc_preview.py` 直接调用本模块的 `roll_channels` / `uv_xform`，两处预览共用同一套
公式。

四元组字段（`('f', 4)`）的布局为 **[U static, U random, V static, V random]**：出生时各分量在
`[static, static + random]` 内取值。若以 index 1 作为 V，V 方向会退化为条纹。偏移的单位是整张
贴图的 U/V 比例。

每个轴的运动（n 为帧数，speed 与 scaleAdd 为每秒的量，两个 Coef 为每帧作用一次的倍率）：

    偏移   offset + Σ (offsetAdd / fps)·offsetCoef^k    （k = 0..n−1）
    缩放   scale  + Σ (scaleAdd  / fps)·scaleCoef^k

Coef 不大于 0 时按 1 计。缩放以 U=0 / V=0 为锚点，不绕贴图中心。

uv1 与 uv2 两套通道共用同一批贴图，布局相同。uv1 恒生效，uv2 由 `uv2_enable` 开启；两套同时
生效时叠加：**偏移相加，缩放相乘**。
时间基准由 `SimConfig.uvc_clock` 决定，默认取粒子自身的年龄。

输出 `item.extra["uv_xform"] = (su, sv, ou, ov)`，由 glue 变换顶点 UV：
`uv' = uv × (su, sv) + (ou, ov)`。这组值在游戏 UV 空间（v 向下）；V 翻转过的 UV 要先经
`flip_v_xform` 换算。没有贴图的渲染路径不含 UV，本属性在这些路径上不生效。

flowmap 字段组与渲染体上的同名字段同义，相位与强度沿用 `_flowmap` 的算法，开关是
`enableFlowmap`，没有「播放一次后停止」位。流动贴图本身不在本属性里，由 glue 从同一 Entry 的
MATERIAL 贴图槽取。渲染体自己也启用了 flowmap 时以渲染体的为准。
"""

from ...hashes import UVCONTROL
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_MOD
from . import _flowmap

#: 存进 p.rolled 的 flowmap 参数键，与渲染体自己的 `_flowmap.KEY` 分开
FLOW_KEY = "uvc_flowmap"

#: 每个轴依次取的六个字段后缀及其缺省值
_AXIS_FIELDS = (("_offset", 0.0), ("_offsetAdd", 0.0), ("_offsetCoef", 1.0),
                ("_scale", 1.0), ("_scaleAdd", 0.0), ("_scaleCoef", 1.0))


def _comp(vec, i, default=0.0):
    try:
        return float(vec[i])
    except (TypeError, IndexError, ValueError):
        return default


def channel_names(uv2_enable):
    """返回参与计算的通道前缀。"""
    return ["uv1", "uv2"] if uv2_enable else ["uv1"]


def roll_channels(raw, names, rng=None, mode=None):
    """按通道取出 U、V 两轴各六个参数：`[((U 六元组), (V 六元组)), …]`。

    `raw(field)` 返回字段原始值。`rng` 为 None 时只取 static 分量。
    """
    chans = []
    for pre in names:
        axes = []
        for i in (0, 2):
            vals = []
            for suffix, dflt in _AXIS_FIELDS:
                v = raw(pre + suffix)
                base = _comp(v, i, dflt)
                if rng is not None:
                    base = jitter(base, _comp(v, i + 1), rng, mode)
                vals.append(base)
            axes.append(tuple(vals))
        chans.append(tuple(axes))
    return chans


def _coef(c):
    return 1.0 if c <= 0.0 else c


def _axis_state(ax, frames, fps):
    offset, speed, o_coef, scale, s_add, s_coef = ax
    pos = offset + _flowmap._geometric(speed / fps, _coef(o_coef), frames)
    size = scale + _flowmap._geometric(s_add / fps, _coef(s_coef), frames)
    return pos, size


def uv_xform(chans, frames, fps):
    """返回第 `frames` 帧的 `(su, sv, ou, ov)`。"""
    fps = float(fps or 60)
    frames = max(0.0, float(frames))
    ou = ov = 0.0
    su = sv = 1.0
    for u_ax, v_ax in chans:
        pu, s_u = _axis_state(u_ax, frames, fps)
        pv, s_v = _axis_state(v_ax, frames, fps)
        ou += pu
        ov += pv
        su *= s_u
        sv *= s_v
    return su, sv, ou, ov


def flip_v_xform(xf):
    """把游戏 UV 空间的 `(su, sv, ou, ov)` 换到 V 翻转（v' = 1 − v）的 UV 空间。

    翻转空间里 V 的偏移、速度方向和缩放锚点都随之反向：
    `1 − ((1 − v)·sv + ov) = v·sv + (1 − sv − ov)`。
    """
    su, sv, ou, ov = xf
    return su, sv, ou, 1.0 - sv - ov


@register(UVCONTROL)
class UVControl(Behavior):
    """RENDER_MOD 阶段计算 UV 的缩放、偏移与流动贴图位移并写入渲染项，实际变换由 glue 完成。"""

    STAGE = RENDER_MOD
    ORDER = 55          # 必须排在 UVSEQUENCE 之后：先确定使用哪一格，再在该格内滚动

    def on_particle_spawn(self, p, em, rng):
        f = em.f(UVCONTROL, p)
        if f is None:
            return
        mode = em.config.jitter_mode
        names = channel_names(f.i("uv2_enable"))
        p.rolled["uvc"] = roll_channels(f.raw, names, rng, mode)

        if not f.i("enableFlowmap"):
            return
        strength = jitter(f.get("flowmapStrength"), f.get("flowmapStrengthJitter"), rng, mode)
        if not strength:
            return              # 强度为 0 时无位移
        p.rolled[FLOW_KEY] = (
            jitter(f.get("flowmapSpeed"), f.get("flowmapSpeedJitter"), rng, mode),
            strength,
            jitter(f.get("flowmapSpeedCoef", 1.0), f.get("flowmapSpeedCoefJitter"), rng, mode)
            or 1.0,
            jitter(f.get("flowmapStrengthCoef", 1.0), f.get("flowmapStrengthCoefJitter"),
                   rng, mode) or 1.0,
            False, False)

    def build_render(self, p, em, view, item):
        if item is None or item.kind == "NONE":
            return item
        if _flowmap.KEY not in item.extra:
            _flowmap.apply(p, em, item, key=FLOW_KEY)

        chans = p.rolled.get("uvc")
        if not chans:
            return item
        cfg = em.config
        frames = (em.frame if getattr(cfg, "uvc_clock", "particle_age") == "emitter_frame"
                  else p.age)
        xf = uv_xform(chans, frames, getattr(cfg, "fps", 60))
        if xf == (1.0, 1.0, 0.0, 0.0):
            return item                 # 中性值不写入，glue 无需逐顶点计算
        item.extra["uv_xform"] = xf
        return item
