# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/billboard3d.py  —  BILLBOARD3D（渲染主体：面朝相机的方片）

第一个 RENDER_BODY 阶段的 behavior：产出 RenderItem，让预览从「一堆点」变成
「有尺寸、有颜色、有朝向的片」。

尺寸
----
    width(SizeX) × scale(SizeScalar)  →  游戏单位的宽
    height(SizeY) × scale             →  游戏单位的高
再乘 `p.scale`（SCALEANIM 累积的倍率，出生时 1）。

`scale` 是**倍率**不是独立尺寸，依据是官方通道名 SizeScalar 与 SizeX/SizeY 的分工，
以及数量级：floating_particle_fire 的 width=height=100、scale=0.4 → 40 游戏单位
= 0.4 Blender 单位，对一团火花是合理的；当成独立值则是 100 单位 = 1 米见方，过大。

颜色
----
    color / colorRange 是 XYZ type 2（`<4B`：r g b + 第四字节）的 0-255 无符号字节。
    useColorRange=1 → 在 color 与 colorRange 之间**按粒子**随机取（出生时抽一个
    插值系数 t，整条通道共用一个 t——比逐通道独立随机更像「颜色范围」这个说法，
    但没有实测，见下）。
    brightness（通道名 ColorRate）当**乘数**用：实测 floating_particle_fire 的值是
    1.0，不是 annotations 里按全语料统计说的 0~255 量级——两者不矛盾（HDR 亮度可以
    很大），但 1.0 = 中性这个读法能同时解释两者，故取之。

    第四字节在 codec 里叫 pad、在 annotations 里叫 RGBA 的 A。实测样本里恒为 255，
    两种读法给出相同结果，故一并当 alpha 乘进去——是 pad 的话也是乘 1.0，无害。

混合模式
--------
    blendMode: 0=Alpha 混合，1=Add 叠加（ENUM_BLEND_MODE）→ 直接给 RenderItem.blend，
    glue 层翻成 gpu.state.blend_set。

未处理
------
    EPVColorSlot1 / SlotOverride1 非 0 时，颜色实际来自调用方 .epv 的槽位，本地
    color 不生效（annotations 明确写了）。预览拿不到 .epv，故照常用本地值并记一条
    note，免得用户以为「改了颜色没反应」是预览的 bug——那恰恰是游戏内的真实行为。
    flowmap* 一族（扰动贴图）也未处理，属于 T3 的纹理部分。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import BILLBOARD3D
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

BLEND_ALPHA = 0
BLEND_ADDITIVE = 1


def _rgba(seq):
    """XYZ type 2 的四个字节 → 0-1 浮点四元组。"""
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return (1.0, 1.0, 1.0, 1.0)
    a = float(seq[3]) / 255.0 if len(seq) > 3 else 1.0
    return (float(seq[0]) / 255.0, float(seq[1]) / 255.0, float(seq[2]) / 255.0, a)


@register(BILLBOARD3D)
class Billboard3D(Behavior):
    """RENDER_BODY 阶段：产出 RenderItem。不写任何粒子状态（strict 会查）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    #: 本块有没有 TIML 曲线。init 时问一次，build_render 就能在常见情形（没有 TIML）
    #: 下连 em.f() 都不必调——那是逐粒子逐帧的热路径。
    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(BILLBOARD3D)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        if f.i("EPVColorSlot1") or f.i("SlotOverride1"):
            em.note("BILLBOARD3D 绑了 EPV 颜色槽位：游戏内颜色来自 .epv，"
                    "本地 color 不生效（预览仍按本地值画）")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(BILLBOARD3D, p)
        if f is None:
            return
        mode = em.config.jitter_mode

        p.rolled["bb_scale"] = jitter(f.get("scale", 1.0), f.get("scaleJitter"), rng, mode)
        p.rolled["bb_width"] = jitter(f.get("width", 1.0), f.get("widthJitter"), rng, mode)
        p.rolled["bb_height"] = jitter(f.get("height", 1.0), f.get("heightJitter"), rng, mode)
        p.rolled["bb_bright"] = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"),
                                       rng, mode)
        # 颜色范围的插值系数：整条通道共用一个 t
        p.rolled["bb_color_t"] = rng.random() if f.i("useColorRange") else 0.0

        # 初始平面角（ROTATEANIM 的平面旋转在这之上累积）
        p.rot.z += jitter(f.get("rotation"), f.get("rotationJitter"), rng, mode)

        # 外观的静态部分**在出生时解一次就缓存**。build_render 是逐粒子逐帧调用的
        # 热路径（profile 里占了一半时间），而 color/colorRange/blendMode 只有挂了
        # TIML 才会逐帧变——没挂就直接用缓存，挂了才重解。
        p.rolled["bb_rgba"] = self._resolve_rgba(f, p)
        p.rolled["bb_blend"] = ("ADDITIVE" if f.i("blendMode") == BLEND_ADDITIVE
                                else "ALPHA")

    @staticmethod
    def _resolve_rgba(f, p):
        r, g, b, a = _rgba(f.raw("color"))
        t = p.rolled.get("bb_color_t", 0.0)
        if t:
            r1, g1, b1, a1 = _rgba(f.raw("colorRange"))
            r += (r1 - r) * t
            g += (g1 - g) * t
            b += (b1 - b) * t
            a += (a1 - a) * t
        return (r, g, b, a)

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "bb_rgba" not in rolled:      # 没跑过 spawn（属性是后加的？）→ 交给下游
            return item

        item = RenderItem(kind="BILLBOARD", pos=p.pos.copy())
        item.rot = p.rot.z

        if self._has_tracks:        # 挂了 TIML → 尺寸/颜色可能逐帧变，重解
            f = em.f(BILLBOARD3D, p)
            s = f.get("scale", 1.0)
            item.size = Vec3(f.get("width", 1.0) * s * p.scale.x,
                             f.get("height", 1.0) * s * p.scale.y, 1.0)
            r0, g0, b0, a0 = self._resolve_rgba(f, p)
            bright = f.get("brightness", 1.0)
        else:
            s = rolled["bb_scale"]
            item.size = Vec3(rolled["bb_width"] * s * p.scale.x,
                             rolled["bb_height"] * s * p.scale.y, 1.0)
            r0, g0, b0, a0 = rolled["bb_rgba"]
            bright = rolled["bb_bright"]

        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.blend = rolled.get("bb_blend", "ALPHA")
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        return item
