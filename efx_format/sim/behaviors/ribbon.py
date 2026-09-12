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

轨迹跟随的总长（`SimConfig.ribbon_length_mode`）
-----------------------------------------------
用户实测：跟随条带的长短**跟着细分数走**（宽=长=1、细分=2 是一个矩形）。定长面片
那边则相反——语料里 mode 1 的 subdiv 90.6% 恒为 2 而 length 被逐个细调，mode 0 的
length 59% 留在默认 100 不动、变化的是 subdiv。所以两个模式对 length 的用法不同。

默认按「每段定长」：**总长 = length × (subdiv - 1)**，一段一个 length。另一种读法是
「每段一帧历史」（长度随运动速度变），要改 p.trail 的记录长度才能做，先不实现；
`ribbon_length_mode='total'` 保留改动前的行为（length 即总长）。
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
from ..state import RenderItem, RibbonStrip, Vec3
from ._common import (axis_normal, blend_name, epv_note, pick_color,
                      pick_trail, roll_rgba)

MODE_TRAIL = 0
MODE_RIGID = 1
MODE_CHAIN = 2

#: 轨迹弧长低于这个值（游戏单位）就当发射器没动 —— 静止时条带彻底消失（实机确认）。
#: 不取 0 是因为绑骨的发射器总有一点数值抖动，取 0 会让本该消失的条带留一条丝。
_STATIC_ARC_EPS = 1e-4


def _per_segment(em):
    """轨迹跟随的 length 是「每段」还是「总长」（见模块 docstring）。"""
    return getattr(em.config, "ribbon_length_mode", "per_segment") != "total"


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

        p.rolled["rb_rgba"], p.rolled["rb_coff"] = roll_rgba(f, rng, cfg)
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
        cap = int(getattr(cfg, "ribbon_subdiv_max", 0) or 0)
        if cap and n > cap:
            n = max(2, cap)             # 预览降载，见 SimConfig.ribbon_subdiv_max
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
    def _dims(self, p, em, st, f):
        """(尺寸 f, 长度, 宽度, 采样点数)。

        挂了 TIML 就逐帧重解尺寸：语料里 RIBBON 的 Length/Width 确实有曲线
        （场景里 15 line 那条的 length 静态值 10、曲线给 1），只在出生时取一次
        会把「条带随寿命伸缩」整个丢掉。同 BILLBOARD3D 的 has_tracks 分支
        ——那边也是重解时不再叠抖动偏移。
        """
        if self._has_tracks and f is not None:
            scale = f.get("scale", 1.0)
            length = f.get("length", 1.0) * scale
            width = f.get("width", 1.0) * scale
        else:
            rolled = p.rolled
            scale = rolled["rb_scale"]
            length = rolled["rb_length"] * scale
            width = rolled["rb_width"] * scale
        return f, length, width, st["n"]

    def pre_render(self, em, view):
        """整批做轨迹裁剪 + 重采样 + 粗细/透明度剖面（见 `trail.clip_resample_batch`）。

        逐粒子走一趟 clip+resample 是渲染 pass 里最贵的一段，而每条带的算式一模
        一样、只是数据不同——正好整批拉成数组算。结果**留在数组里**交给
        `RibbonStrip`：条带顶点串在核心层造出来、到 glue 层又被逐个拆回 float，
        一条 50 细分的条带就是上百个短命对象，上千条时这两趟纯搬运比算术还贵。

        顺手把尺寸也解出来存着，`build_render` 直接取，`em.f()` 一个粒子一帧只过一次。
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
                # 柔体链/刚性矩形不看轨迹，照旧逐粒子算（strip=None, pts=None）
                st["_pre"] = (f, length, width, n, None, None)
                continue
            pend.append((p, st, f, length, width, n))
            trails.append(pick_trail(p, em))
            max_lens.append(length * (n - 1) if per_seg else length)
            counts.append(n)
        if not pend:
            return

        # 弧长不到阈值 → 空 = 发射器没动过 → 没有条带（不是画一条直线）
        got = None if numpy is None else _trail.clip_resample_batch(
            trails, max_lens, counts, min_arc=_STATIC_ARC_EPS, reverse=True)
        if got is None:                 # 没有 numpy：退回逐条标量路
            pts_all = _trail.clip_resample_many(trails, max_lens, counts,
                                                min_arc=_STATIC_ARC_EPS)
            for rec, pts in zip(pend, pts_all):
                rec[1]["_pre"] = (rec[2], rec[3], rec[4], rec[5], None,
                                  pts[::-1])          # 新→旧 翻成 base→tip
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
        """给批量重采样的结果补上锚点平移和粗细/透明度剖面，包成 `RibbonStrip`。

        整批一次算完：Q 的行本来就按 `pend` 的顺序首尾相接，所以逐粒子的标量
        （半宽基数、两端倍率）用 `repeat` 摊到行上即可。逐条带过 numpy 是不划算的
        ——每条要二十来次数组调用，调度开销比算术还大。
        """
        out = [None] * len(pend)
        keep = [k for k in range(len(pend)) if starts[k] >= 0]
        if not keep:
            return out
        ns = numpy.array([sizes[k] for k in keep], dtype=numpy.intp)
        row0 = numpy.array([starts[k] for k in keep], dtype=numpy.intp)

        anchors = []
        wbases = []
        base_ws = []
        dws = []
        base_as = []
        das = []
        flaps = []
        for k in keep:
            p, st, f, length, width, n = pend[k]
            a = (f.get("spawnAnchorOffset") if f is not None else 0.0) or 0.0
            anchors.append(float(a) * length)
            wbases.append(0.5 * width * p.scale.x)
            bw = f.get("base_width_multiplier", 1.0) if f is not None else 1.0
            tw = f.get("tip_width_multiplier", 1.0) if f is not None else 1.0
            ba = f.get("base_opacity", 1.0) if f is not None else 1.0
            ta = f.get("tip_opacity", 1.0) if f is not None else 1.0
            base_ws.append(bw)
            dws.append(tw - bw)
            base_as.append(ba)
            das.append(ta - ba)
            flaps.append(bool(st["flap"]))

        arr = lambda seq: numpy.array(seq, dtype="f8")
        rep = lambda seq: numpy.repeat(arr(seq), ns)

        # 锚点：生成点在条带长度方向上的位置（0=前端贴住生成点，1=后端贴住）
        amt = arr(anchors)
        if numpy.any(amt):
            d = Q[row0 + ns - 1] - Q[row0]
            nrm = numpy.sqrt((d * d).sum(axis=1))
            numpy.divide(d, nrm[:, None], out=d, where=(nrm > 1e-12)[:, None])
            Q += numpy.repeat(d * amt[:, None], ns, axis=0)

        # 沿长度的归一化参数 u（0=base，1=tip），逐行算
        total = int(ns.sum())
        run = numpy.zeros(len(ns), dtype=numpy.intp)
        numpy.cumsum(ns[:-1], out=run[1:])
        u = ((numpy.arange(total, dtype="f8") - numpy.repeat(run, ns))
             / numpy.repeat((ns - 1).astype("f8"), ns))
        half = rep(wbases) * (rep(base_ws) + rep(dws) * u)
        alpha = rep(base_as) + rep(das) * u

        for j, k in enumerate(keep):
            s = starts[k]
            e = s + sizes[k]
            strip = RibbonStrip(Q[s:e], half[s:e], alpha[s:e])
            if flaps[j]:
                # 旗帜摆动是逐点的正弦位移，没有数组写法（而且极少见）：物化成
                # Vec3 交给纯 Python 路，摆完再逐点拼 points
                pend[k][1]["_flap_pts"] = strip.vecs()
            else:
                out[k] = strip
        return out

    def build_render(self, p, em, view, item):
        rolled = p.rolled
        st = p.user.get(Ribbon)
        if st is None or "rb_rgba" not in rolled:
            return item

        # pre_render 算过就取走（pop：别让这一帧的结果留到下一帧）；没算过就
        # 就地补一趟——behavior 必须能脱离 Simulator 单独调用
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
            # 快路：锚点与剖面都已在 pre_render 里整批算完
            points = strip
            tip = strip.vec(-1)
        else:
            if pts is None:
                pts = self._sample_points(p, em, st, length, n)   # base→tip
            if len(pts) < 2:
                # 轨迹跟随 + 发射器静止 → **彻底消失**（实机确认）。返回显式的
                # kind='NONE' 而不是 None：后者会让 Simulator 退化成调试点，那就
                # 变成「静止时反而多出一个点」，与实机相反。
                return RenderItem(kind="NONE", pos=p.pos.copy())
            # 锚点在 _build_strips 里已经批量加过了，物化出来的那条别再加一次
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
        """纯 Python 的条带成形（没有 numpy、柔体链/刚性矩形、或旗帜摆动时走）。

        返回 `([(Vec3, 半宽, alpha), …], 末点)`。
        """
        anchor = 0.0 if skip_anchor else (
            (f.get("spawnAnchorOffset") if f is not None else 0.0) or 0.0)
        if anchor:
            # 生成点在条带长度方向上的位置：0=前端贴住生成点，1=后端贴住。
            # 原地平移——pts 是这一趟新造的，可以随便改；写成
            # `[q + shift for q in pts]` 会再造一整串 Vec3，上千条带就是每帧几万
            # 个临时对象。
            shift = (pts[-1] - pts[0]).normalized() * (length * anchor)
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

        # pts 是 base→tip（index 0 = 后端 = 远离前进方向的一端）
        wbase = 0.5 * width * p.scale.x
        dw = tip_w - base_w
        da = tip_a - base_a
        if dw == 0.0 and da == 0.0:
            # 宽度与不透明度沿长度不变（语料里的常态）：整条一组数，不必逐点算 u
            hw = wbase * base_w
            points = [(q, hw, base_a) for q in pts]
        else:
            inv = 1.0 / (len(pts) - 1)
            points = [(q, wbase * (base_w + dw * (i * inv)),
                       base_a + da * (i * inv))
                      for i, q in enumerate(pts)]
        return points, pts[-1].copy()

    # ── 三种取点方式 ─────────────────────────────────────────────────────────
    def _sample_points(self, p, em, st, length, n):
        """返回 base→tip 顺序的顶点串（index 0 = 后端）；**空列表 = 不该画**。"""
        mode = st["mode"]

        if mode == MODE_CHAIN:
            # 复制一份：节点是模拟状态（`on_particle_step` 每帧就地改），而调用方
            # 会把返回的点当自己的（锚点平移是原地改的）
            return [q.copy() for q in st["nodes"]]   # 首节点在粒子身上 = base

        if mode == MODE_TRAIL:
            total = length * (n - 1) if _per_segment(em) else length
            # 裁剪+重采样合并成一趟（见 trail.clip_resample）：弧长不到阈值就
            # 提前返回空 = 发射器没动过 → 没有条带（不是画一条直线）
            pts, _arc = _trail.clip_resample(pick_trail(p, em), total, n,
                                             min_arc=_STATIC_ARC_EPS)  # 新→旧
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
