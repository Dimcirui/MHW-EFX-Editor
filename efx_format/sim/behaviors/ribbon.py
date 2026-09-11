# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/ribbon.py  —  RIBBON（条带）

`ribbonMode` 三态，annotations 里有用户实机写下的描述，对应关系也很直白：

    0 轨迹跟随  沿**发射器**实际划过的轨迹绘制     ≈ Unity Trail Renderer / UE Ribbon
                （粒子自己动过就改用粒子的轨迹，见 _common.pick_trail）
    1 定长面片  刚性矩形，只靠单个轴转动朝相机   ≈ Unity Stretched Billboard
                （所以相机经过侧边时会整体翻 180°，是该构造的固有表现）
    2 柔体链    从发射器向外延伸并带弹性         ≈ UE Niagara 的 spring/chain

模式 0 需要逐帧位置历史 → `NEEDS_TRAIL = True`，Simulator 据此开始记 `p.trail`。

几何与外观
----------
    length / width          游戏单位；`scale`(+jitter) 是两者共同的倍率（同 BILLBOARD3D
                            的 SizeScalar 约定）
    subdivisionCount        沿长度方向的**切边**数：N 条边分 N-1 段（annotations 原话）
    base_/tip_width_multiplier   后端/前端的宽度乘数（tip = 前进方向那一端）
    base_/tip_opacity            后端/前端的不透明度
    spawnAnchorOffset       生成点落在条带长度方向上的位置，以条带长度为单位
                            （0=前端贴住生成点，1=后端贴住生成点）
    enableFlap + flap1/flap2(Frequency, Amount)   旗帜式来回摆动，两组叠加

柔体链的模型（推断，无实测）
----------------------------
三个参数的 annotations 描述刚好对应一个阻尼弹簧链：

    restoreStrength  回归平直形态的力度（0 = 无回复力，表现接近轨迹跟随）
    springiness      弹簧刚度（高 → 果冻般弹跳）
    inertia          分段惯性（高 → 撑住伸展形状、振荡持续久）

故实现为：每个节点的**静止目标**在「完全平直」与「维持当前朝向」之间按
restoreStrength 混合，用 springiness 当劲度系数拉向目标，用 inertia 当速度保留率。
三条描述都能从这个模型里读出来，但没有拿真实数值对过账。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

import math

from ...hashes import RIBBON
from .. import trail as _trail
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ._common import (axis_normal, blend_name, color_lerp_t, epv_note,
                      pick_color, pick_trail)

MODE_TRAIL = 0
MODE_RIGID = 1
MODE_CHAIN = 2


@register(RIBBON)
class Ribbon(Behavior):
    """RENDER_BODY：产出 kind='RIBBON' 的顶点串，glue 层撑成三角带。"""

    STAGE = RENDER_BODY
    ORDER = 100
    NEEDS_TRAIL = True          # 模式 0 要用；开着不影响另两个模式

    _has_tracks = False

    def on_emitter_init(self, em, rng):
        f = em.f(RIBBON)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        epv_note(f, em, "RIBBON", "epvcolor_0", "epvcolor_1")
        mode = f.i("ribbonMode")
        if mode == MODE_CHAIN:
            em.note("RIBBON 柔体链的弹簧模型是推断的（无实测），形态仅供参考")

    # ── 出生 ─────────────────────────────────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        f = em.f(RIBBON, p)
        if f is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode

        scale = jitter(f.get("scale", 1.0), f.get("scale_jitter"), rng, mode)
        p.rolled["rb_scale"] = scale
        p.rolled["rb_width"] = jitter(f.get("width", 1.0), f.get("width_jitter"), rng, mode)
        p.rolled["rb_length"] = jitter(f.get("length", 1.0), f.get("length_jitter"),
                                       rng, mode)
        p.rolled["rb_bright"] = jitter(f.get("brightness", 1.0), f.get("brightnessJitter"),
                                       rng, mode)

        t = color_lerp_t(f, rng)
        p.rolled["rb_color_t"] = t
        p.rolled["rb_rgba"] = pick_color(f, t)
        p.rolled["rb_blend"] = blend_name(f)

        # 条带的基准伸展方向（定长面片/柔体链的「平直形态」）。
        # ⚠ RIBBON 的 rotationX/Y/Z 是三个**标量**字段各配一个 Jitter，
        #   不是 PLANE/TRANSFORM3D 那种 XYZ type 0 的六元组，别套错。
        rolled_rot = (jitter(f.get("rotationX"), f.get("rotationXJitter"), rng, mode),
                      jitter(f.get("rotationY"), f.get("rotationYJitter"), rng, mode),
                      jitter(f.get("rotationZ"), f.get("rotationZJitter"), rng, mode))
        direction = axis_normal(f, cfg, rolled=rolled_rot)

        ribbon_mode = f.i("ribbonMode")
        n = max(2, f.i("subdivisionCount") or 2)
        st = {"mode": ribbon_mode, "n": n, "dir": direction,
              "restore": jitter(f.get("restoreStrength"), f.get("restoreStrengthJitter"),
                                rng, mode),
              "inertia": jitter(f.get("inertia"), f.get("inertiaJitter"), rng, mode),
              "spring": jitter(f.get("springiness"), f.get("springiness_jitter"),
                               rng, mode),
              "flap": [], }

        if f.i("enableFlap"):
            for k in ("flap1", "flap2"):
                st["flap"].append((
                    jitter(f.get(k + "Frequency"), f.get(k + "FrequencyJitter"), rng, mode),
                    jitter(f.get(k + "Amount"), f.get(k + "AmountJitter"), rng, mode)))

        if ribbon_mode == MODE_CHAIN:
            seg = (p.rolled["rb_length"] * scale) / (n - 1)
            st["nodes"] = [p.pos + direction * (seg * i) for i in range(n)]
            st["vels"] = [Vec3() for _ in range(n)]
            st["seg"] = seg
        p.user[Ribbon] = st

    # ── 逐帧（只有柔体链要算）─────────────────────────────────────────────────
    def on_particle_step(self, p, em):
        st = p.user.get(Ribbon)
        if st is None or st["mode"] != MODE_CHAIN:
            return

        nodes = st["nodes"]
        vels = st["vels"]
        seg = st["seg"]
        restore = st["restore"]
        spring = st["spring"]
        inertia = st["inertia"]
        straight_dir = st["dir"]

        nodes[0] = p.pos.copy()             # 首节点被粒子拖着走
        for i in range(1, len(nodes)):
            prev = nodes[i - 1]
            cur_dir = (nodes[i] - prev).normalized(fallback=straight_dir)
            # 静止朝向：在「完全平直」和「保持现状」之间按 restoreStrength 混合
            rest_dir = (straight_dir * restore + cur_dir * (1.0 - restore))
            rest_dir = rest_dir.normalized(fallback=straight_dir)
            target = prev + rest_dir * seg

            v = vels[i]
            v *= inertia
            v += (target - nodes[i]) * spring
            nodes[i] += v

    # ── 渲染 ─────────────────────────────────────────────────────────────────
    def build_render(self, p, em, view, item):
        rolled = p.rolled
        st = p.user.get(Ribbon)
        if st is None or "rb_rgba" not in rolled:
            return item
        f = em.f(RIBBON, p)

        scale = rolled["rb_scale"]
        length = rolled["rb_length"] * scale
        width = rolled["rb_width"] * scale
        n = st["n"]

        pts = self._sample_points(p, em, st, length, n)
        if len(pts) < 2:
            return item

        anchor = f.get("spawnAnchorOffset") if f is not None else 0.0
        if anchor:
            # 生成点在条带长度方向上的位置：0=前端贴住生成点，1=后端贴住
            shift = (pts[-1] - pts[0]).normalized() * (length * anchor)
            pts = [q + shift for q in pts]

        if st["flap"]:
            self._apply_flap(pts, st, p, em)

        if self._has_tracks and f is not None:
            r0, g0, b0, a0 = pick_color(f, rolled.get("rb_color_t", 0.0))
            bright = f.get("brightness", 1.0)
        else:
            r0, g0, b0, a0 = rolled["rb_rgba"]
            bright = rolled["rb_bright"]

        base_w = f.get("base_width_multiplier", 1.0) if f is not None else 1.0
        tip_w = f.get("tip_width_multiplier", 1.0) if f is not None else 1.0
        base_a = f.get("base_opacity", 1.0) if f is not None else 1.0
        tip_a = f.get("tip_opacity", 1.0) if f is not None else 1.0

        # pts 是 base→tip（index 0 = 后端 = 远离前进方向的一端）
        last = len(pts) - 1
        points = []
        for i, q in enumerate(pts):
            u = i / float(last)
            hw = 0.5 * width * (base_w + (tip_w - base_w) * u) * p.scale.x
            am = base_a + (tip_a - base_a) * u
            points.append((q, hw, am))

        item = RenderItem(kind="RIBBON", pos=pts[-1].copy())
        item.points = points
        item.size = Vec3(width, length, 1.0)
        item.color = [r0 * bright * p.color[0],
                      g0 * bright * p.color[1],
                      b0 * bright * p.color[2],
                      a0 * p.alpha]
        item.blend = rolled["rb_blend"]
        item.extra["mode"] = st["mode"]
        item.extra["age"] = p.age
        return item

    # ── 三种取点方式 ─────────────────────────────────────────────────────────
    def _sample_points(self, p, em, st, length, n):
        """返回 base→tip 顺序的顶点串（index 0 = 后端）。"""
        mode = st["mode"]

        if mode == MODE_CHAIN:
            return list(st["nodes"])        # 首节点在粒子身上 = base

        if mode == MODE_TRAIL:
            poly = _trail.clip_by_length(pick_trail(p, em), length)   # 新→旧
            if len(poly) < 2:
                # 还没走出轨迹（刚出生/静止）→ 退化成沿基准方向的直线，
                # 免得第一帧闪一下空条带
                return _trail.straight(p.pos, -st["dir"], length, n)[::-1]
            pts = _trail.resample(poly, n)                  # 仍是 新→旧
            return pts[::-1]                                # 翻成 base→tip

        # MODE_RIGID：刚性矩形，沿基准方向伸出去
        return _trail.straight(p.pos, st["dir"], length, n)

    @staticmethod
    def _apply_flap(pts, st, p, em):
        """旗帜式摆动：沿条带长度做正弦横向位移，两组参数叠加。

        相位用 `em.frame`（不是随机数）——step/render 都必须是确定性的。
        """
        if len(pts) < 3:
            return
        axis = (pts[-1] - pts[0]).normalized(fallback=Vec3(0.0, 1.0, 0.0))
        side = axis.cross(Vec3(0.0, 1.0, 0.0))
        if side.length() < 1e-6:
            side = axis.cross(Vec3(1.0, 0.0, 0.0))
        side = side.normalized(fallback=Vec3(1.0, 0.0, 0.0))

        last = len(pts) - 1
        phase0 = p.seed % 628 / 100.0        # 每个粒子错开相位，免得整齐划一
        for freq, amount in st["flap"]:
            if not freq or not amount:
                continue
            w = em.frame * freq * 0.1 + phase0
            for i in range(1, last + 1):     # base 端固定，越往 tip 摆幅越大
                u = i / float(last)
                pts[i] = pts[i] + side * (math.sin(w + u * math.pi) * amount * u)
