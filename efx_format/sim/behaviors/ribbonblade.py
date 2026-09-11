# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/ribbonblade.py  —  RIBBONBLADE（刀光拖尾）

本质是「沿轨迹的条带」，但参数化方式和 RIBBON 不同——它是照武器挥舞的刀光设计的，
对应 Unity/UE 里那种带长度上限 + 回缩速度的 Trail：

    widthDirection   AxisDirection6（实机确认，与 RIBBON.baseAxis / VELOCITY3D 同一套）
                     刀光**宽度**延伸的朝向——注意是宽度方向，不是长度方向；
                     长度方向由轨迹决定。
    width            纵边宽度（游戏单位）
    lengthMode       关：长度由 `length` 决定（收缩速度固定内置）
                     开：由 `maxLengthLimit` + `contractionSpeed` 共同决定
    contractionSpeed 0=驻留，1=回缩，∞=瞬间回缩（annotations 原话）
    colourTransitionPoint  0=立即开始过渡，1=在末端开始
    head / tailEnd   EPVColorSlot 结构，各带一个 color1(RGBA)——刀光两端的颜色
    emissiveStrength 自发光强度，当亮度乘数用
    uvRepetition     UV 沿长度的重复次数（属 T3 纹理部分，未处理）

长度模型（推断）
----------------
`lengthMode=1` 时「长度上限 maxLengthLimit + 回缩速度 contractionSpeed」被实现为：
当前长度 = min(已走过的轨迹弧长, maxLengthLimit)，再每帧从尾端回缩
contractionSpeed（游戏单位/帧）。contractionSpeed=0 → 不主动回缩（只受上限约束），
与 annotations 的「0=驻留」一致。

blade_trail 原型的实测值：width=100、lengthMode=1、maxLengthLimit=1500、
contractionSpeed=1600、widthDirection=5(后)。1600/帧的回缩速度配 1500 的上限，
意味着刀光基本是「挥到哪亮到哪、立刻收」——符合刀光的观感。

`contractionSpeed` 控制的是**停下之后**的回缩，不是挥动过程中的持续削减：

    挥动中：长度 = min(长度 + 这一帧走过的距离, maxLengthLimit)
    停下后：长度 = max(0, 长度 − contractionSpeed/fps)

这么读才和 annotations 的「0=驻留，1=回缩，∞=瞬间回缩」对得上——0 就是停下也不
收（拖尾驻留），值越大停下后收得越快，极大值就是「一停就没」。
反过来把它当挥动过程中也持续削减的速度，blade_trail 的 1600 配 1500 上限会让
拖尾永远长不出来（实测过，画出来是空的），那个读法可以排除。⚠ 仍未实测。

⚠ 刀光依赖**发射器**运动
------------------------
blade_trail 原型的属性表是 TRANSFORM3D + PARENTOPTIONS + SPAWN + LIFE +
RIBBONBLADE——**没有 VELOCITY3D**。也就是说粒子自己不动，整个效果靠
PARENTOPTIONS 把发射器绑在挥动的武器骨骼上。所以发射器静止时它本来就没有轨迹
可画，这时 behavior 记一条 note 说明原因，而不是默默画空。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import RIBBONBLADE
from .. import trail as _trail
from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import BASE_AXES, RenderItem, Vec3
from ._common import pick_trail, rgba

#: 没有 blendMode 字段——刀光在语料里一律是自发光叠加的观感，按 Add 处理。
_BLEND = "ADDITIVE"

#: lengthMode=0 时内置的回缩速度（游戏单位/帧）。annotations 说「收缩速度固定内置」
#: 但没给数值，取一个能让 length 大致等于可见拖尾长度的量级。未实测。
_BUILTIN_CONTRACTION = 40.0


def _slot_color(v):
    """head / tailEnd 是 EPVColorSlot 结构，取其中的 color1(RGBA)。"""
    if isinstance(v, dict):
        return rgba(v.get("color1"))
    return (1.0, 1.0, 1.0, 1.0)


@register(RIBBONBLADE)
class RibbonBlade(Behavior):
    """RENDER_BODY：沿轨迹的条带，两端颜色不同。"""

    STAGE = RENDER_BODY
    ORDER = 100
    NEEDS_TRAIL = True

    _segments = 12          # 重采样点数；刀光没有 subdivisionCount 字段，取个够顺滑的值

    def on_emitter_init(self, em, rng):
        f = em.f(RIBBONBLADE)
        if f is None:
            return
        if f.i("lengthMode"):
            em.note("RIBBONBLADE 回缩模型（maxLengthLimit + contractionSpeed）"
                    "是推断的，未实测")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return
        idx = f.i("widthDirection")
        p.user[RibbonBlade] = {
            "width_dir": (BASE_AXES[idx] if 0 <= idx < len(BASE_AXES)
                          else BASE_AXES[1]).copy(),
            "head": _slot_color(f.raw("head")),
            "tail": _slot_color(f.raw("tailEnd")),
            "length": 0.0,          # 当前可见长度，逐帧更新
        }

    def on_particle_step(self, p, em):
        st = p.user.get(RibbonBlade)
        if st is None:
            return
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return

        # 刀光沿**发射器**的轨迹画（粒子自己通常不动），所以看发射器走了多远
        moved = max(p.vel.length(), em.velocity.length())
        if f.i("lengthMode"):
            limit = f.get("maxLengthLimit", 0.0)
            shrink = f.get("contractionSpeed", 0.0)
        else:
            limit = f.get("length", 0.0)
            shrink = _BUILTIN_CONTRACTION
        shrink = shrink / float(max(1, em.config.fps))     # 每秒 → 每帧

        cur = st["length"]
        if moved > 1e-6:
            cur += moved                       # 挥动中：只长不收
        else:
            cur -= shrink                      # 停下后才按回缩速度收
        if limit > 0.0:
            cur = min(cur, limit)
        st["length"] = max(0.0, cur)

    def build_render(self, p, em, view, item):
        st = p.user.get(RibbonBlade)
        if st is None:
            return item
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return item

        length = st["length"]
        if length <= 1e-6:
            # 没有轨迹可画。最常见的原因是发射器静止——刀光本来就是靠发射器
            # 跟着武器骨骼挥动画出来的，不是靠粒子自己飞。说清楚，别默默画空。
            if p.vel.length() < 1e-6 and em.velocity.length() < 1e-6:
                em.note("RIBBONBLADE 靠**发射器**运动画轨迹（PARENTOPTIONS 绑骨）；"
                        "发射器静止时没有拖尾可画——拖动特效体或播放骨骼动画即可看到")
            return RenderItem(kind="NONE")

        poly = _trail.clip_by_length(pick_trail(p, em), length)    # 新→旧
        if len(poly) < 2:
            return RenderItem(kind="NONE")
        pts = _trail.resample(poly, self._segments)[::-1]   # 翻成 tail→head

        half_w = 0.5 * f.get("width", 1.0) * p.scale.x
        emissive = f.get("emissiveStrength", 1.0) or 1.0

        # colourTransitionPoint：0=立即开始过渡，1=在末端才开始
        cut = max(0.0, min(1.0, f.get("colourTransitionPoint", 0.0)))
        tr, tg, tb, ta = st["tail"]
        hr, hg, hb, ha = st["head"]

        last = len(pts) - 1
        points = []
        for i, q in enumerate(pts):
            u = i / float(last)             # 0 = 尾端，1 = 头端
            # cut 之前保持尾色，之后线性过渡到头色
            w = 0.0 if u <= cut else (u - cut) / max(1e-6, 1.0 - cut)
            points.append((q, half_w, (ta + (ha - ta) * w) * p.alpha))

        # 整体色取两端混合的中值，逐点 alpha 已经带了过渡；
        # 逐点颜色等 glue 支持顶点色渐变时再细化。
        mid = 0.5
        item = RenderItem(kind="RIBBON", pos=pts[-1].copy())
        item.points = points
        item.size = Vec3(half_w * 2.0, length, 1.0)
        item.color = [(tr + (hr - tr) * mid) * emissive * p.color[0],
                      (tg + (hg - tg) * mid) * emissive * p.color[1],
                      (tb + (hb - tb) * mid) * emissive * p.color[2],
                      p.alpha]
        item.blend = _BLEND
        item.extra["width_dir"] = st["width_dir"]
        item.extra["age"] = p.age
        return item
