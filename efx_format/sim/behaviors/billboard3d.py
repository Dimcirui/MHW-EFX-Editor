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
    color / colorRange 是 XYZ type 2（`<4B`：r g b + 第四字节）的 0-255 无符号字节，
    两者是 **RGBA 四元组的 static/random 对**：useColorRange=1 时逐通道（含 alpha）
    各抽一个 [0, colorRange] 的随机量加到 color 上。详见 `_common` 的染色模型说明。
    brightness（通道名 ColorRate）当**乘数**用：实测 floating_particle_fire 的值是
    1.0，不是 annotations 里按全语料统计说的 0~255 量级——两者不矛盾（HDR 亮度可以
    很大），但 1.0 = 中性这个读法能同时解释两者，故取之。

    第四字节在 codec 里叫 pad、在 annotations 里叫 RGBA 的 A，这里当 alpha 用：
    乘进 item.color[3]，再乘上 LIFE 淡入淡出算出来的 `p.alpha`。

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

import math

from ...hashes import BILLBOARD3D
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ._common import pick_color, roll_rgba

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
        # 染色：color 是静态 RGBA，colorRange 是**逐通道随机量**（含 alpha）
        p.rolled["bb_rgba"], p.rolled["bb_coff"] = roll_rgba(f, rng, em.config)

        # 初始平面角（ROTATEANIM 的平面旋转在这之上累积）
        p.rot.z += jitter(f.get("rotation"), f.get("rotationJitter"), rng, mode)

        # 外观的静态部分**在出生时解一次就缓存**。build_render 是逐粒子逐帧调用的
        # 热路径（profile 里占了一半时间），而 color/colorRange/blendMode 只有挂了
        # TIML 才会逐帧变——没挂就直接用缓存，挂了才重解。
        p.rolled["bb_blend"] = ("ADDITIVE" if f.i("blendMode") == BLEND_ADDITIVE
                                else "ALPHA")

    @staticmethod
    def _size(p, em, scale, width, height):
        """SCALEANIM 是**加**在尺寸字段上的（SizeScalarAdd 加 scale、SizeXAdd 加 width）。

        用户在 test.efx（scale=30 / width=height=1）上计时：同为 -0.1，逐轴那组 10 帧
        缩没、整体那组 300 帧——正是 1 与 30 的差距。夹在 0 以上：负尺寸等于把面片翻过来，
        游戏里是「消失」不是「翻面」。
        """
        if getattr(em.config, "scaleanim_add_target", "size") != "size":
            return Vec3(width * scale * p.scale.x, height * scale * p.scale.y, 1.0)
        ax = p.rolled.get("sa_axis")
        s = max(0.0, scale + p.rolled.get("sa_scalar", 0.0))
        if ax is None:
            return Vec3(width * s, height * s, 1.0)
        return Vec3(max(0.0, width + ax[0]) * s, max(0.0, height + ax[1]) * s, 1.0)

    @staticmethod
    def _spin_on_view(p, em, view):
        """ROTATEANIM 的自旋里，只有**朝向相机那根轴**的分量会变成屏幕自转。

        用户实机：正方形 billboard 上自旋 X 与平面旋转完全等同、Y/Z 毫无反应——
        billboard 每帧被摆正朝向相机，绕画面内的轴转看不出来。`p.rot.z` 里已经含了
        自旋的 Z 分量（那是 PLANE/MESH 用的），所以这里要把它减掉再按视轴加回来。
        """
        ang = p.rolled.get("spin_ang")
        if ang is None:
            return 0.0
        if getattr(em.config, "rotateanim_billboard_axis", "view") != "view":
            return 0.0                      # 'z' = 改动前的行为，只认 p.rot.z
        n = view.cam_forward
        d = math.sqrt(n.x * n.x + n.y * n.y + n.z * n.z)
        if d < 1e-9:
            return 0.0
        return (ang[0] * n.x + ang[1] * n.y + ang[2] * n.z) / d - ang[2]

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        if "bb_rgba" not in rolled:      # 没跑过 spawn（属性是后加的？）→ 交给下游
            return item

        item = RenderItem(kind="BILLBOARD", pos=p.pos.copy())
        item.rot = p.rot.z + self._spin_on_view(p, em, view)

        if self._has_tracks:        # 挂了 TIML → 尺寸/颜色可能逐帧变，重解
            f = em.f(BILLBOARD3D, p)
            s = f.get("scale", 1.0)
            item.size = self._size(p, em, s, f.get("width", 1.0), f.get("height", 1.0))
            r0, g0, b0, a0 = pick_color(f, rolled.get("bb_coff"))
            bright = f.get("brightness", 1.0)
        else:
            s = rolled["bb_scale"]
            item.size = self._size(p, em, s, rolled["bb_width"], rolled["bb_height"])
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
