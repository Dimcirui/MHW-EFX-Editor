# -*- coding: utf-8 -*-
"""RIBBON —— 条带。

`ribbonMode` 的三种取值：

    0 轨迹跟随  沿**发射器**实际经过的轨迹绘制；粒子自身有位移时改用粒子轨迹（见
                `_common.pick_trail`）。需要逐帧位置历史，因此 `NEEDS_TRAIL = True`
    1 定长面片  刚性矩形，仅绕单个轴旋转以朝向相机。相机经过侧面时整条翻转 180°，是该构造的
                固有表现。伸展方向默认在出生时由 baseAxis 与 rotationX/Y/Z 确定；
                `SimConfig.ribbon_rigid_dir='velocity'` 时改为逐帧跟随当前运动方向
    2 柔体链    自发射器向外延伸，带有弹性

几何与外观字段：

    length / width               游戏单位；`scale`(+jitter) 为两者共同的倍率
    subdivisionCount             沿长度方向的**分段边**数，N 条边构成 N-1 段
    base_/tip_width_multiplier   后端／前端的宽度乘数（tip 为前进方向一端），沿全长插值。
                                 base=1 / tip=0 时为三角形
    base_/tip_opacity            两端**端点**的不透明度，中间部分始终不透明
    base_/tip_fade_length        各自在该长度（占全长比例）内过渡到端点值
    spawnAnchorOffset            生成点在条带长度方向上的位置，以条带自身跨度为单位
    enableFlap +                 旗帜式摆动，两组叠加
    flap1/flap2(Frequency,Amount)
    restoreStrength /            柔体链专用：恢复平直形态的强度 / 弹簧刚度 / 分段惯性
    springiness / inertia

轨迹跟随的总长默认按**每段定长**计算：总长 = length × (subdiv − 1)，每段一个 length
（`SimConfig.ribbon_length_mode='total'` 时 length 即总长）。

两端渐隐：`base_/tip_opacity` 为**端点值**，而非整条带的不透明度——两端均取 0 时中间仍不透明，
仅两端渐隐。每一端在 base_/tip_fade_length 的跨度内由端点值过渡到 1；两端取 `min` 而非相乘，
跨度不重叠时两者等价，重叠时相乘会使中间部分变暗。跨度不大于 0 时为硬边，端点值不起作用。
宽度乘数一对才是沿全长插值。

柔体链的弹簧模型为推断：每个节点的静止目标在「完全平直」与「保持当前朝向」之间按
restoreStrength 插值，以 springiness 为劲度系数拉向目标，以 inertia 为速度保留率。

维护约束：
- 轨迹跟随模式下发射器静止时条带**完全消失**，必须返回显式的 `kind='NONE'`。返回 None 时
  Simulator 会补绘调试点，出现「静止时反而多一个点」，与实机相反。
- `spawnAnchorOffset` 对轨迹跟随模式**不生效**：tip 始终等于粒子当前位置，沿首尾方向平移会使
  条带超前于发射器，或在轨迹历史不足时将 tip 固定在出生点，直至达到理论长度。两种结果都与
  「自出生起始终贴合运动」不符。该字段只对刚性矩形与柔体链生效，二者没有轨迹历史，仅沿自身
  长度方向平移。
- 长度须乘 `p.scale.y`，宽度乘 `p.scale.x`：RIBBON 的约定为 X=width / Y=length。长度未乘时，
  SCALEANIM 的 scaleSpeedY（沿长度方向拉伸）完全不生效。
- RIBBON 的 rotationX/Y/Z 为三个**标量**字段，各配一个 Jitter，不是 PLANE / TRANSFORM3D 使用的
  XYZ type 0 六元组。
- 伸展方向须对 `axis_normal` 的结果取负：该函数按 PLANE 的面法线设计，RIBBON 以同一组
  baseAxis 与 rotation 表示伸展方向，实机对比结果恰好相反。
"""

import math

from ...hashes import RIBBON
from .. import trail as _trail
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, RibbonStrip, Vec3
from ._common import (axis_normal, blend_name, emitter_rotate, epv_note,
                      pick_color, pick_trail, roll_rgba)

MODE_TRAIL = 0
MODE_RIGID = 1
MODE_CHAIN = 2

#: 轨迹弧长低于该值（游戏单位）时视为发射器静止。不取 0，因为绑定骨骼的发射器存在微小的
#: 数值抖动，取 0 会使应当消失的条带残留一条细线。
_STATIC_ARC_EPS = 1e-4

#: 两端渐隐长度的缺省值（占全长比例），字段缺失时使用。
_DEF_BASE_FADE = 0.3
_DEF_TIP_FADE = 0.4


def _fade_alpha(u, base_a, tip_a, base_span, tip_span):
    """返回沿长度参数 `u` 处的 alpha 系数：端点取 base_/tip_opacity，中间为 1。"""
    rb = 1.0 if base_span <= 0.0 else min(1.0, u / base_span)
    rt = 1.0 if tip_span <= 0.0 else min(1.0, (1.0 - u) / tip_span)
    return min(base_a + (1.0 - base_a) * rb, tip_a + (1.0 - tip_a) * rt)


def _per_segment(em):
    """轨迹跟随的 length 是否按每段计算。"""
    return getattr(em.config, "ribbon_length_mode", "per_segment") != "total"


@register(RIBBON)
class Ribbon(Behavior):
    """RENDER_BODY 阶段产出 kind='RIBBON' 的顶点序列，由 glue 层展开为三角带。"""

    STAGE = RENDER_BODY
    ORDER = 100
    NEEDS_TRAIL = True          # 模式 0 需要；开启不影响另两种模式

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
        elif mode == MODE_TRAIL and f.get("spawnAnchorOffset"):
            em.note("RIBBON 轨迹跟随模式下 spawnAnchorOffset 不生效（本地值仍保留，"
                    "只是预览不套用）：条带的头恒贴着发射器当前位置")

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

        p.rolled["rb_rgba"], p.rolled["rb_coff"] = roll_rgba(f, rng, cfg)
        p.rolled["rb_blend"] = blend_name(f)

        # 条带的基准伸展方向，即定长面片与柔体链的平直形态
        rolled_rot = (jitter(f.get("rotationX"), f.get("rotationXJitter"), rng, mode),
                      jitter(f.get("rotationY"), f.get("rotationYJitter"), rng, mode),
                      jitter(f.get("rotationZ"), f.get("rotationZJitter"), rng, mode))
        # 取负的原因见模块 docstring
        direction = -axis_normal(f, cfg, rolled=rolled_rot)
        # 父实例旋转时，子 entry 的伸展方向随之旋转；只叠加这一项整体旋转，
        # 由 baseAxis 与 rotationX/Y/Z 确定的本地朝向不变
        direction = emitter_rotate(em, direction)

        ribbon_mode = f.i("ribbonMode")
        n = max(2, f.i("subdivisionCount") or 2)
        cap = int(getattr(cfg, "ribbon_subdiv_max", 0) or 0)
        if cap and n > cap:
            n = max(2, cap)             # 降低预览负载
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

    # ── 逐帧 ─────────────────────────────────────────────────────────────────
    def on_particle_step(self, p, em):
        st = p.user.get(Ribbon)
        if st is None:
            return

        if st["mode"] == MODE_RIGID:
            # velocity 档下伸展方向跟随当前运动方向（优先取粒子速度，粒子静止时取发射器位移）；
            # 两者均为零时保留上一个有效方向，不因短暂静止恢复为出生时的朝向
            if getattr(em.config, "ribbon_rigid_dir", "static") == "velocity":
                v = p.vel if p.vel.length() > 1e-6 else em.velocity
                if v.length() > 1e-6:
                    st["dir"] = v.normalized()
            return

        if st["mode"] != MODE_CHAIN:
            return

        nodes = st["nodes"]
        vels = st["vels"]
        seg = st["seg"]
        restore = st["restore"]
        spring = st["spring"]
        inertia = st["inertia"]
        straight_dir = st["dir"]

        nodes[0] = p.pos.copy()             # 首节点跟随粒子位置
        for i in range(1, len(nodes)):
            prev = nodes[i - 1]
            cur_dir = (nodes[i] - prev).normalized(fallback=straight_dir)
            # 静止朝向：在完全平直与保持当前朝向之间按 restoreStrength 插值
            rest_dir = (straight_dir * restore + cur_dir * (1.0 - restore))
            rest_dir = rest_dir.normalized(fallback=straight_dir)
            target = prev + rest_dir * seg

            v = vels[i]
            v *= inertia
            v += (target - nodes[i]) * spring
            nodes[i] += v

    # ── 渲染 ─────────────────────────────────────────────────────────────────
    def _dims(self, p, em, st, f):
        """返回 `(属性字段 f, 长度, 宽度, 采样点数)`；带 TIML 时逐帧重新求值尺寸。"""
        if self._has_tracks and f is not None:
            scale = f.get("scale", 1.0)
            length = f.get("length", 1.0) * scale * p.scale.y
            width = f.get("width", 1.0) * scale
        else:
            rolled = p.rolled
            scale = rolled["rb_scale"]
            length = rolled["rb_length"] * scale * p.scale.y
            width = rolled["rb_width"] * scale
        return f, length, width, st["n"]

    def pre_render(self, em, view):
        """批量完成轨迹裁剪、重采样与粗细／透明度剖面计算，并缓存各粒子的尺寸。

        逐粒子执行 clip+resample 是渲染过程中开销最大的部分，而各条带的算式相同、仅数据不同，
        因此整批以数组计算。结果以数组形式交给 `RibbonStrip`：一条 50 分段的条带若转换为 Vec3，
        将产生上百个临时对象，条带数量上千时，这一转换的开销超过计算本身。
        """
        numpy = _trail.numpy_backend()
        pend = []
        trails = []
        max_lens = []
        counts = []
        per_seg = _per_segment(em)
        for p in em.particles:
            if not p.active:
                continue
            st = p.user.get(Ribbon)
            if st is None or "rb_rgba" not in p.rolled:
                continue
            f, length, width, n = self._dims(p, em, st, em.f(RIBBON, p))
            st.pop("_pre", None)
            st.pop("_flap_pts", None)
            if st["mode"] != MODE_TRAIL:
                # 柔体链与刚性矩形不使用轨迹，仍逐粒子计算
                st["_pre"] = (f, length, width, n, None, None)
                continue
            pend.append((p, st, f, length, width, n))
            trails.append(pick_trail(p, em))
            max_lens.append(length * (n - 1) if per_seg else length)
            counts.append(n)
        if not pend:
            return

        # 弧长低于阈值时返回空：发射器未运动即没有条带，而非绘制一条直线
        got = None if numpy is None else _trail.clip_resample_batch(
            trails, max_lens, counts, min_arc=_STATIC_ARC_EPS, reverse=True)
        if got is None:                 # 没有 numpy 时退回逐条标量计算
            pts_all = _trail.clip_resample_many(trails, max_lens, counts,
                                                min_arc=_STATIC_ARC_EPS)
            for rec, pts in zip(pend, pts_all):
                rec[1]["_pre"] = (rec[2], rec[3], rec[4], rec[5], None,
                                  pts[::-1])          # 由新到旧反转为 base→tip
            return

        Q, starts, sizes = got
        strips = ([None] * len(pend) if Q is None
                  else self._build_strips(numpy, Q, starts, sizes, pend))
        for k, rec in enumerate(pend):
            strip = strips[k]
            rec[1]["_pre"] = (rec[2], rec[3], rec[4], rec[5], strip,
                              None if strip is not None else [])

    @staticmethod
    def _build_strips(numpy, Q, starts, sizes, pend):
        """为批量重采样的结果补充粗细／透明度剖面，封装为 `RibbonStrip`。

        Q 的行已按 `pend` 的顺序首尾相接，逐粒子的标量（半宽基数、两端倍率）以 `repeat` 展开到
        各行即可。逐条带调用 numpy 并不划算：每条约需二十次数组调用，调度开销超过计算本身。
        """
        out = [None] * len(pend)
        keep = [k for k in range(len(pend)) if starts[k] >= 0]
        if not keep:
            return out
        ns = numpy.array([sizes[k] for k in keep], dtype=numpy.intp)
        row0 = numpy.array([starts[k] for k in keep], dtype=numpy.intp)

        wbases = []
        base_ws = []
        dws = []
        base_as = []
        tip_as = []
        base_spans = []
        tip_spans = []
        flaps = []
        for k in keep:
            p, st, f, length, width, n = pend[k]
            wbases.append(0.5 * width * p.scale.x)
            bw = f.get("base_width_multiplier", 1.0) if f is not None else 1.0
            tw = f.get("tip_width_multiplier", 1.0) if f is not None else 1.0
            ba = f.get("base_opacity", 1.0) if f is not None else 1.0
            ta = f.get("tip_opacity", 1.0) if f is not None else 1.0
            base_ws.append(bw)
            dws.append(tw - bw)
            base_as.append(ba)
            tip_as.append(ta)
            base_spans.append(f.get("base_fade_length", _DEF_BASE_FADE)
                              if f is not None else _DEF_BASE_FADE)
            tip_spans.append(f.get("tip_fade_length", _DEF_TIP_FADE)
                             if f is not None else _DEF_TIP_FADE)
            flaps.append(bool(st["flap"]))

        arr = lambda seq: numpy.array(seq, dtype="f8")
        rep = lambda seq: numpy.repeat(arr(seq), ns)

        # 仅轨迹跟随使用此路径，因此不处理 spawnAnchorOffset，见模块 docstring

        # 沿长度的归一化参数 u（0=base，1=tip），逐行计算
        total = int(ns.sum())
        run = numpy.zeros(len(ns), dtype=numpy.intp)
        numpy.cumsum(ns[:-1], out=run[1:])
        u = ((numpy.arange(total, dtype="f8") - numpy.repeat(run, ns))
             / numpy.repeat((ns - 1).astype("f8"), ns))
        half = rep(wbases) * (rep(base_ws) + rep(dws) * u)

        # 两端渐隐，逐点计算，与 `_fade_alpha` 的算式相同
        sb = rep(base_spans)
        stp = rep(tip_spans)
        rb = numpy.clip(u / numpy.where(sb > 1e-6, sb, 1.0), 0.0, 1.0)
        rt = numpy.clip((1.0 - u) / numpy.where(stp > 1e-6, stp, 1.0), 0.0, 1.0)
        rb[sb <= 1e-6] = 1.0            # 跨度为 0 即硬边
        rt[stp <= 1e-6] = 1.0
        ba_ = rep(base_as)
        ta_ = rep(tip_as)
        alpha = numpy.minimum(ba_ + (1.0 - ba_) * rb, ta_ + (1.0 - ta_) * rt)

        for j, k in enumerate(keep):
            s = starts[k]
            e = s + sizes[k]
            strip = RibbonStrip(Q[s:e], half[s:e], alpha[s:e])
            if flaps[j]:
                # 旗帜摆动为逐点正弦位移，无数组实现：转换为 Vec3 后交由纯 Python 路径处理
                pend[k][1]["_flap_pts"] = strip.vecs()
            else:
                out[k] = strip
        return out

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        st = p.user.get(Ribbon)
        if st is None or "rb_rgba" not in rolled:
            return item

        # pre_render 已计算时取出并移除，避免本帧结果残留到下一帧；未计算时就地补算，
        # behavior 必须能脱离 Simulator 单独调用
        pre = st.pop("_pre", None)
        flap_pts = st.pop("_flap_pts", None)
        if pre is None:
            f, length, width, n = self._dims(p, em, st, em.f(RIBBON, p))
            strip, pts = None, None
        else:
            f, length, width, n, strip, pts = pre
        if flap_pts is not None:
            strip, pts = None, flap_pts

        if strip is not None:
            points = strip
            tip = strip.vec(-1)
        else:
            if pts is None:
                pts = self._sample_points(p, em, st, length, n)   # base→tip
            if len(pts) < 2:
                # 轨迹跟随且发射器静止时完全消失，见模块 docstring
                return RenderItem(kind="NONE", pos=p.pos.copy())
            points, tip = self._strip_py(p, em, st, f, pts, length, width,
                                         skip_anchor=flap_pts is not None)

        if self._has_tracks and f is not None:
            r0, g0, b0, a0 = pick_color(f, rolled.get("rb_coff"))
            bright = f.get("brightness", 1.0)
        else:
            r0, g0, b0, a0 = rolled["rb_rgba"]
            bright = rolled["rb_bright"]

        item = RenderItem(kind="RIBBON", pos=tip)
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

    def _strip_py(self, p, em, st, f, pts, length, width, skip_anchor=False):
        """以纯 Python 构造条带，返回 `([(Vec3, 半宽, alpha), …], 末点)`。

        用于没有 numpy、柔体链／刚性矩形或带旗帜摆动的情形。
        """
        # spawnAnchorOffset 只对刚性矩形与柔体链生效，见模块 docstring
        anchor = 0.0 if (skip_anchor or st["mode"] == MODE_TRAIL) else (
            (f.get("spawnAnchorOffset") if f is not None else 0.0) or 0.0)
        if anchor:
            # 0=前端对齐生成点，1=后端对齐。位移量按该条带实际的首尾跨度计算，刚性矩形与
            # 柔体链的实际跨度即等于配置长度
            span = pts[-1] - pts[0]
            shift = span * anchor
            sx, sy, sz = shift.x, shift.y, shift.z
            for q in pts:
                q.x += sx
                q.y += sy
                q.z += sz

        if st["flap"]:
            self._apply_flap(pts, st, p, em)

        base_w = f.get("base_width_multiplier", 1.0) if f is not None else 1.0
        tip_w = f.get("tip_width_multiplier", 1.0) if f is not None else 1.0
        base_a = f.get("base_opacity", 1.0) if f is not None else 1.0
        tip_a = f.get("tip_opacity", 1.0) if f is not None else 1.0
        base_span = (f.get("base_fade_length", _DEF_BASE_FADE)
                     if f is not None else _DEF_BASE_FADE)
        tip_span = (f.get("tip_fade_length", _DEF_TIP_FADE)
                    if f is not None else _DEF_TIP_FADE)

        # pts 按 base→tip 排列（index 0 为后端，即远离前进方向的一端）
        wbase = 0.5 * width * p.scale.x
        dw = tip_w - base_w
        if dw == 0.0 and base_a == 1.0 and tip_a == 1.0:
            # 宽度不变且两端不渐隐：整条使用同一组值，无需逐点计算 u
            hw = wbase * base_w
            points = [(q, hw, 1.0) for q in pts]
        else:
            inv = 1.0 / (len(pts) - 1)
            points = [(q, wbase * (base_w + dw * (i * inv)),
                       _fade_alpha(i * inv, base_a, tip_a, base_span, tip_span))
                      for i, q in enumerate(pts)]
        return points, pts[-1].copy()

    # ── 三种取点方式 ─────────────────────────────────────────────────────────
    def _sample_points(self, p, em, st, length, n):
        """返回按 base→tip 排列的顶点序列（index 0 为后端）；空列表表示不绘制。"""
        mode = st["mode"]

        if mode == MODE_CHAIN:
            # 必须复制：节点属于模拟状态（`on_particle_step` 每帧原地修改），调用方会原地
            # 修改返回的点（锚点平移）
            return [q.copy() for q in st["nodes"]]   # 首节点位于粒子处，即 base

        if mode == MODE_TRAIL:
            total = length * (n - 1) if _per_segment(em) else length
            # 弧长低于阈值时提前返回空：发射器未运动即没有条带
            pts, _arc = _trail.clip_resample(pick_trail(p, em), total, n,
                                             min_arc=_STATIC_ARC_EPS)  # 由新到旧
            return pts[::-1]                                # 反转为 base→tip

        # MODE_RIGID：刚性矩形，沿基准方向延伸
        return _trail.straight(p.pos, st["dir"], length, n)

    @staticmethod
    def _apply_flap(pts, st, p, em):
        """原地施加旗帜式摆动：沿条带长度做正弦横向位移，两组参数叠加。

        相位必须取自 `em.frame` 而非随机数：step 与 render 均须是确定性的。
        """
        if len(pts) < 3:
            return
        axis = (pts[-1] - pts[0]).normalized(fallback=Vec3(0.0, 1.0, 0.0))
        side = axis.cross(Vec3(0.0, 1.0, 0.0))
        if side.length() < 1e-6:
            side = axis.cross(Vec3(1.0, 0.0, 0.0))
        side = side.normalized(fallback=Vec3(1.0, 0.0, 0.0))

        last = len(pts) - 1
        phase0 = p.seed % 628 / 100.0        # 各粒子相位错开，避免同步摆动
        for freq, amount in st["flap"]:
            if not freq or not amount:
                continue
            w = em.frame * freq * 0.1 + phase0
            for i in range(1, last + 1):     # base 端固定，摆幅向 tip 端递增
                u = i / float(last)
                pts[i] = pts[i] + side * (math.sin(w + u * math.pi) * amount * u)
