# -*- coding: utf-8 -*-
"""RIBBONBLADE —— 刀光拖尾。

RIBBONBLADE 是沿轨迹的条带，参数化方式与 RIBBON 不同：带有长度上限与回缩速度。

字段职能：

    widthDirection          刀光**宽度**的延伸方向，与 RIBBON.baseAxis / VELOCITY3D 共用
                            AxisDirection6；长度方向由轨迹决定，与该字段无关
    width                   纵边宽度，游戏单位
    lengthMode              关闭时，长度由 `length` 决定，回缩速度为内置值；
                            开启时，由 `maxLengthLimit` 与 `contractionSpeed` 共同决定
    contractionSpeed        停止运动后的回缩速度。0=保持、1=回缩、极大值=立即回缩
    colourTransitionPoint   0=立即开始颜色过渡、1=在末端才开始
    head / tailEnd          EPVColorSlot 结构，各含一个 color1(RGBA)，即刀光两端的颜色
    emissiveStrength        自发光强度，作为亮度乘数
    uvRepetition            UV 沿长度方向的重复次数，未接入

长度模型：

    运动中：长度 = min(长度 + 本帧移动距离, 上限)
    静止后：长度 = max(0, 长度 − contractionSpeed/fps)

`contractionSpeed` 只作用于**停止运动之后**，而非运动过程中持续缩短。若按后一种读法，上限小于
回缩速度的刀光长度始终为 0，不可见。

刀光由**发射器**的运动形成轨迹：PARENTOPTIONS 将发射器绑定到武器骨骼，粒子自身通常不运动，
因此长度取 `max(p.vel, em.velocity)` 计算。

维护约束：
- 发射器静止时没有轨迹，必须记录 note 说明原因，不得无提示地输出空结果。
- `item.color` 的 alpha 只取 `p.alpha`：两端颜色的 alpha 已逐点写入 `points` 的 alpha_mul，
  不得重复相乘。
- 没有 blendMode 字段，按加法混合处理。
"""

from ...hashes import RIBBONBLADE
from .. import trail as _trail
from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import BASE_AXES, RenderItem, Vec3
from ._common import pick_trail, rgba

#: 没有 blendMode 字段，按加法混合处理。
_BLEND = "ADDITIVE"

#: lengthMode=0 时的内置回缩速度（游戏单位/帧）。文件中不存储该值，此处取使 length 约等于
#: 可见拖尾长度的量级，未经实测。
_BUILTIN_CONTRACTION = 40.0


def _slot_color(v):
    """返回 EPVColorSlot 结构（head / tailEnd）中的 color1(RGBA)。"""
    if isinstance(v, dict):
        return rgba(v.get("color1"))
    return (1.0, 1.0, 1.0, 1.0)


@register(RIBBONBLADE)
class RibbonBlade(Behavior):
    """RENDER_BODY 阶段产出沿轨迹的条带，两端颜色不同。"""

    STAGE = RENDER_BODY
    ORDER = 100
    NEEDS_TRAIL = True

    _segments = 12          # 刀光没有 subdivisionCount 字段，取足以平滑显示的重采样点数

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

        # 刀光沿发射器轨迹绘制，粒子自身通常不运动
        moved = max(p.vel.length(), em.velocity.length())
        if f.i("lengthMode"):
            limit = f.get("maxLengthLimit", 0.0)
            shrink = f.get("contractionSpeed", 0.0)
        else:
            limit = f.get("length", 0.0)
            shrink = _BUILTIN_CONTRACTION
        shrink = shrink / float(max(1, em.config.fps))     # 每秒换算为每帧

        cur = st["length"]
        if moved > 1e-6:
            cur += moved                       # 运动中只增长
        else:
            cur -= shrink                      # 静止后按回缩速度缩短
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
            if p.vel.length() < 1e-6 and em.velocity.length() < 1e-6:
                em.note("RIBBONBLADE 靠**发射器**运动画轨迹（PARENTOPTIONS 绑骨）；"
                        "发射器静止时没有拖尾可画——拖动特效体或播放骨骼动画即可看到")
            return RenderItem(kind="NONE")

        # 轨迹按新到旧排列，裁剪与重采样一次完成
        seg_n = self._segments
        cap = int(getattr(em.config, "ribbon_subdiv_max", 0) or 0)
        if cap and seg_n > cap:
            seg_n = max(2, cap)
        pts, _arc = _trail.clip_resample(pick_trail(p, em), length, seg_n)
        if not pts:
            return RenderItem(kind="NONE")
        pts = pts[::-1]                                     # 反转为 tail→head

        half_w = 0.5 * f.get("width", 1.0) * p.scale.x
        emissive = f.get("emissiveStrength", 1.0) or 1.0

        cut = max(0.0, min(1.0, f.get("colourTransitionPoint", 0.0)))
        tr, tg, tb, ta = st["tail"]
        hr, hg, hb, ha = st["head"]

        last = len(pts) - 1
        points = []
        for i, q in enumerate(pts):
            u = i / float(last)             # 0 = 尾端，1 = 头端
            # cut 之前保持尾端颜色，之后线性过渡到头端颜色
            w = 0.0 if u <= cut else (u - cut) / max(1e-6, 1.0 - cut)
            points.append((q, half_w, (ta + (ha - ta) * w) * p.alpha))

        # 整体颜色取两端的中间值；逐点 alpha 已包含过渡
        mid = 0.5
        item = RenderItem(kind="RIBBON", pos=pts[-1].copy())
        item.points = points
        item.size = Vec3(half_w * 2.0, length, 1.0)
        item.color = [(tr + (hr - tr) * mid) * emissive * p.color[0],
                      (tg + (hg - tg) * mid) * emissive * p.color[1],
                      (tb + (hb - tb) * mid) * emissive * p.color[2],
                      p.alpha]
        item.blend = _BLEND
        # 渲染主体自身的颜色；RGBFIRE / RGBWATER 的两层颜色在 glue 侧再乘上它
        item.extra["base_tint"] = ((tr + (hr - tr) * mid) * emissive,
                                   (tg + (hg - tg) * mid) * emissive,
                                   (tb + (hb - tb) * mid) * emissive)
        item.extra["width_dir"] = st["width_dir"]
        item.extra["age"] = p.age
        return item
