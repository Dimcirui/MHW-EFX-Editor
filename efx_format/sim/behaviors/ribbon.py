# -*- coding: utf-8 -*-
"""RIBBON —— 条带。

`ribbonMode` 的三种取值：

    0 轨迹跟随  沿**发射器**实际经过的轨迹绘制；粒子自身有位移时改用粒子轨迹（见
                `_common.pick_trail`）。需要逐帧位置历史，因此 `NEEDS_TRAIL = True`
    1 定长面片  刚性矩形，仅绕单个轴旋转以朝向相机。相机经过侧面时整条翻转 180°，是该构造的
                固有表现。伸展方向见下文「朝向」
    2 柔体链    自发射器向外延伸，带有弹性

几何与外观字段：

    length / width               游戏单位；`scale`(+jitter) 为两者共同的倍率
    subdivisionCount             沿长度方向的**分段边**数，N 条边构成 N-1 段
    base_/tip_width_multiplier   两端的宽度乘数，沿全长插值。base 为粒子所在一端（轨迹跟随即
                                 条带头部），tip 为远端。base=1 / tip=0 时为三角形
    base_/tip_opacity            两端**端点**的不透明度，中间部分始终不透明
    base_/tip_fade_length        各自在该长度（占全长比例）内过渡到端点值；
    enableFadeLength             两个渐隐长度的开关，关闭时两者均按 1 计
    spawnAnchorOffset            生成点在条带长度方向上的位置，以条带自身跨度为单位
    enableFlap +                 柔体链专用：旗帜式摆动，两组叠加
    flap1/flap2(Frequency,Amount)
    restoreStrength /            柔体链专用：恢复平直形态的强度 / 弹簧刚度 / 分段惯性
    springiness / inertia
    enableGravity + gravityX/Y/Z 柔体链专用：重力，每帧加到链节点速度上。gravityLocalSpace
                                 开启时按发射器的动态旋转转动方向
    useTrailTimeScale +          轨迹跟随专用：每段覆盖的轨迹时长按 trailTimeScale 缩放
    trailTimeScale
    uvScaleMode + uvScaleLength  长度方向的贴图重复次数，见 `ribbon_uv.repeat_count`
    uvScaleWidth                 宽度方向以中线缩放贴图，超出部分取边缘像素

轨迹跟随的长度按**帧**计算：条带取粒子最近 subdivisionCount 个逐帧位置，即 subdiv − 1 帧的
轨迹，与 length 无关；运动越快条带越长。开启 useTrailTimeScale 后改取最近
(subdiv − 1) × trailTimeScale × `SimConfig.ribbon_trail_time_frames` 帧，不足一帧的部分在最旧
一段上插值；trailTimeScale 不大于 0 时条带为生成点到当前位置的直线。`SimConfig.ribbon_length_mode` 另保留 'per_segment'
（总长 = length × (subdiv − 1)）与 'total'（length 即总长）作对照。

两端渐隐：`base_/tip_opacity` 为**端点值**，而非整条带的不透明度——两端均取 0 时中间仍不透明，
仅两端渐隐。每一端在 base_/tip_fade_length 的跨度内由端点值过渡到 1；两端取 `min` 而非相乘，
跨度不重叠时两者等价，重叠时相乘会使中间部分变暗。跨度不大于 0 时为硬边，端点值不起作用。
宽度乘数一对才是沿全长插值。

朝向（定长面片与柔体链）：出生时由 baseAxis 与 rotationX/Y/Z 确定静止形状，此后随发射器一起
转动——PARENTOPTIONS 跟随旋转时，施加到粒子位置上的旋转同样施加到条带朝向上。粒子位于旋转
半径上时，反转自转方向会使领先的一端互换。`SimConfig.ribbon_rigid_dir` 另保留 'velocity'
（静止时朝上的一侧指向运动方向）与 'static'（始终不变）作对照。

贴图方向：各模式一律以粒子所在一端为 base（贴图底边）。轨迹跟随的头部即粒子当前位置，
因此贴图底边在条带头部。

柔体链的弹簧模型为推断：每个节点的静止目标在「完全平直」与「保持当前朝向」之间按
restoreStrength 插值，以 springiness 为劲度系数拉向目标，以 inertia 为速度保留率。
重力方向与开关已确认，量纲未实测（`SimConfig.ribbon_gravity_scale`）。世界轴重力取模拟坐标系
的轴向，与 VELOCITY3D.gravity 的约定相同。

贴图缩放只输出参数 `item.extra["uv_scale"] = (重复次数, 宽度缩放)`，几何切分见 `ribbon_uv`。

维护约束：
- 轨迹跟随模式下发射器静止时条带**完全消失**，必须返回显式的 `kind='NONE'`。返回 None 时
  Simulator 会补绘调试点，出现「静止时反而多一个点」，与实机相反。
- `spawnAnchorOffset` 对轨迹跟随模式**不生效**：头部始终等于粒子当前位置，沿首尾方向平移会使
  条带超前于发射器，或在轨迹历史不足时将头部固定在出生点，直至达到理论长度。两种结果都与
  「自出生起始终贴合运动」不符。该字段只对刚性矩形与柔体链生效，二者没有轨迹历史，仅沿自身
  长度方向平移。
- 长度须乘 `p.scale.y`，宽度乘 `p.scale.x`：RIBBON 的约定为 X=width / Y=length。长度未乘时，
  SCALEANIM 的 scaleSpeedY（沿长度方向拉伸）完全不生效。
- RIBBON 的 rotationX/Y/Z 为三个**标量**字段，各配一个 Jitter，不是 PLANE / TRANSFORM3D 使用的
  XYZ type 0 六元组。
- 伸展方向直接取 `axis_normal` 的结果，不取负：baseAxis 为下时条带自发射器向下伸展，
  贴图底边在发射器一端。
"""

import math

from ...hashes import RIBBON
from .. import ribbon_uv as _ruv
from .. import trail as _trail
from ..registry import Behavior, register
from ..rng import jitter
from ..stages import RENDER_BODY
from ..state import RenderItem, RibbonStrip, Vec3
from ..vecmath import rotate_euler
from ._common import (axis_normal, blend_name, emitter_rotate, epv_note,
                      pick_color, pick_trail, roll_rgba)
from .parentoptions import ParentOptions

MODE_TRAIL = 0
MODE_RIGID = 1
MODE_CHAIN = 2

#: 轨迹弧长低于该值（游戏单位）时视为发射器静止。不取 0，因为绑定骨骼的发射器存在微小的
#: 数值抖动，取 0 会使应当消失的条带残留一条细线。
_STATIC_ARC_EPS = 1e-4

#: 定长面片与柔体链走批量路径的最少点数。点数更少时逐条计算更快；带旗帜摆动的也逐条计算，
#: 摆动只有标量实现。
_BODY_BATCH_MIN_N = 6

#: 两端渐隐长度的缺省值（占全长比例），字段缺失时使用。
_DEF_BASE_FADE = 0.3
_DEF_TIP_FADE = 0.4


def _fade_spans(f):
    """两端渐隐长度；enableFadeLength 关闭时两者均按 1 计。"""
    if f is None:
        return _DEF_BASE_FADE, _DEF_TIP_FADE
    if f.has("enableFadeLength") and not f.i("enableFadeLength"):
        return 1.0, 1.0
    return (f.get("base_fade_length", _DEF_BASE_FADE),
            f.get("tip_fade_length", _DEF_TIP_FADE))


def _fade_alpha(u, base_a, tip_a, base_span, tip_span):
    """返回沿长度参数 `u` 处的 alpha 系数：端点取 base_/tip_opacity，中间为 1。"""
    rb = 1.0 if base_span <= 0.0 else min(1.0, u / base_span)
    rt = 1.0 if tip_span <= 0.0 else min(1.0, (1.0 - u) / tip_span)
    return min(base_a + (1.0 - base_a) * rb, tip_a + (1.0 - tip_a) * rt)


def _length_mode(em):
    return getattr(em.config, "ribbon_length_mode", "frames")


def _trail_time_frames(f, cfg):
    """开启 useTrailTimeScale 时轨迹覆盖的帧数；未开启返回 None，不大于 0 返回 0。"""
    if not f.i("useTrailTimeScale"):
        return None
    scale = f.get("trailTimeScale")
    if scale <= 0.0:
        return 0.0
    segs = max(2, f.i("subdivisionCount") or 2) - 1
    return segs * scale * float(getattr(cfg, "ribbon_trail_time_frames", 0.42))


def _last_frames(trail, frames):
    """截取轨迹最近 `frames` 帧（可为小数），最旧一端插值到恰好的位置；历史不足时全取。"""
    whole = int(math.ceil(frames - 1e-9))
    if len(trail) < whole + 1:
        return list(trail)
    sub = list(trail[-(whole + 1):])
    cut = whole - frames                    # 最旧一段要裁掉的比例
    if cut > 1e-9:
        sub[0] = sub[0] + (sub[1] - sub[0]) * cut
    return sub


def _trail_span(p, em, st, length):
    """返回轨迹跟随要用的 `(轨迹, 最大弧长)`；按帧计算时只截取最近若干帧、不限弧长。"""
    trail = pick_trail(p, em)
    mode = _length_mode(em)
    if mode == "frames":
        tf = st.get("time_frames")
        if tf is None:
            return trail[-st["frames"]:], float("inf")
        if tf <= 0.0:
            # 设计外取值：生成点直连当前位置
            if not trail:
                return [], float("inf")
            start = st["spawn_p"] if trail is p.trail else st["spawn_em"]
            return [start, trail[-1]], float("inf")
        return _last_frames(trail, tf), float("inf")
    return trail, (length * (st["frames"] - 1) if mode == "per_segment" else length)


def _arc_length(points):
    """条带顶点串的折线长度；兼容 `RibbonStrip` 与 `[(Vec3, 半宽, alpha), …]`。"""
    pos = getattr(points, "pos", None)
    if pos is not None:
        d = pos[1:] - pos[:-1]
        return float(((d * d).sum(axis=1) ** 0.5).sum())
    total = 0.0
    prev = None
    for q, _hw, _a in points:
        if prev is not None:
            total += (q - prev).length()
        prev = q
    return total


def _align_up(rest, fwd):
    """把静止朝向 `rest` 施加「+Y 转到 `fwd`」的最小旋转；`fwd` 须为单位向量。"""
    c = fwd.y
    if c < -1.0 + 1e-9:
        return Vec3(rest.x, -rest.y, -rest.z)     # 正好朝下：绕 X 转 180°
    k = Vec3(fwd.z, 0.0, -fwd.x)                  # +Y × fwd，长度为 sinθ
    return rest * c + k.cross(rest) + k * (k.dot(rest) / (1.0 + c))


def _sync_parent_rot(p, em, st):
    """把 PARENTOPTIONS 新施加到粒子上的旋转同步到条带朝向；按累计量求差，可重复调用。"""
    po = p.user.get(ParentOptions)
    if po is None:
        return
    acc = po["rot_applied"]
    last = st.get("po_rot") or Vec3()
    dx, dy, dz = acc.x - last.x, acc.y - last.y, acc.z - last.z
    if dx or dy or dz:
        st["dir"] = rotate_euler(st["dir"], dx, dy, dz, order=em.rot_order,
                                 applied=em.config.rot_order_applied)
        st["po_rot"] = acc.copy()


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
        if mode == MODE_TRAIL and _length_mode(em) == "frames":
            # 按帧取轨迹时，位置历史须覆盖所取的帧数
            need = f.i("subdivisionCount") or 2
            tf = _trail_time_frames(f, em.config)
            if tf is not None:
                need = int(math.ceil(tf)) + 2
            em.trail_need = max(em.trail_need, need)
        if mode == MODE_CHAIN and f.i("enableGravity"):
            em.note("RIBBON 柔体链重力的量纲未实测，下垂程度仅供参考")

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
        p.rolled["rb_uvlen"] = jitter(f.get("uvScaleLength", 1.0),
                                      f.get("uvScaleLengthJitter"), rng, mode)
        p.rolled["rb_blend"] = blend_name(f)

        # 条带的基准伸展方向，即定长面片与柔体链的平直形态
        rolled_rot = (jitter(f.get("rotationX"), f.get("rotationXJitter"), rng, mode),
                      jitter(f.get("rotationY"), f.get("rotationYJitter"), rng, mode),
                      jitter(f.get("rotationZ"), f.get("rotationZJitter"), rng, mode))
        direction = axis_normal(f, cfg, rolled=rolled_rot)
        # 父实例旋转时，子 entry 的伸展方向随之旋转；只叠加这一项整体旋转，
        # 由 baseAxis 与 rotationX/Y/Z 确定的本地朝向不变
        direction = emitter_rotate(em, direction)

        ribbon_mode = f.i("ribbonMode")
        frames = n = max(2, f.i("subdivisionCount") or 2)
        cap = int(getattr(cfg, "ribbon_subdiv_max", 0) or 0)
        if cap and n > cap:
            n = max(2, cap)             # 降低预览负载：只减点数，不改长度
        st = {"mode": ribbon_mode, "n": n, "frames": frames,
              "dir": direction, "rest": direction.copy(),
              "restore": jitter(f.get("restoreStrength"), f.get("restoreStrengthJitter"),
                                rng, mode),
              "inertia": jitter(f.get("inertia"), f.get("inertiaJitter"), rng, mode),
              "spring": jitter(f.get("springiness"), f.get("springiness_jitter"),
                               rng, mode),
              "flap": [], "gravity": None,
              "time_frames": (_trail_time_frames(f, cfg) if ribbon_mode == MODE_TRAIL
                              else None),
              "spawn_p": p.pos.copy(), "spawn_em": em.origin.copy(), }

        if ribbon_mode == MODE_CHAIN and f.i("enableGravity"):
            k = float(getattr(cfg, "ribbon_gravity_scale", 1.0))
            st["gravity"] = Vec3(f.get("gravityX") * k, f.get("gravityY") * k,
                                 f.get("gravityZ") * k)
            st["gravity_local"] = bool(f.i("gravityLocalSpace"))

        if ribbon_mode == MODE_CHAIN and f.i("enableFlap"):
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

        if st["mode"] == MODE_TRAIL:
            return

        dir_mode = getattr(em.config, "ribbon_rigid_dir", "parent")
        if dir_mode == "parent":
            _sync_parent_rot(p, em, st)
        elif dir_mode == "velocity":
            # 优先取粒子相对上一帧的位移（PARENTOPTIONS 带着粒子绕圈时只改位置，速度仍为零），
            # 粒子静止时取发射器位移；两者均为零时保留上一个有效方向
            v = p.pos - p.trail[-1] if p.trail else p.vel
            if v.length() <= 1e-6:
                v = em.velocity
            if v.length() > 1e-6:
                st["dir"] = _align_up(st["rest"], v.normalized())

        if st["mode"] != MODE_CHAIN:
            return

        nodes = st["nodes"]
        vels = st["vels"]
        seg = st["seg"]
        restore = st["restore"]
        spring = st["spring"]
        inertia = st["inertia"]
        straight_dir = st["dir"]
        grav = st["gravity"]
        if grav is not None and st["gravity_local"]:
            grav = emitter_rotate(em, grav)

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
            if grav is not None:
                v += grav
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
        """批量完成各条带的取点与粗细／透明度剖面计算，并缓存各粒子的尺寸。

        逐粒子取点是渲染过程中开销最大的部分，而各条带的算式相同、仅数据不同，因此整批以数组
        计算：轨迹跟随走 clip+resample，点数足够的定长面片与柔体链走 `_body_batch`。结果以数组形式交给
        `RibbonStrip`：一条 50 分段的条带若转换为 Vec3，将产生上百个临时对象，条带数量上千时，
        这一转换的开销超过计算本身。
        """
        numpy = _trail.numpy_backend()
        sync_rot = getattr(em.config, "ribbon_rigid_dir", "parent") == "parent"
        pend = []
        body = []
        trails = []
        max_lens = []
        counts = []
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
                if numpy is None or n < _BODY_BATCH_MIN_N or st["flap"]:
                    st["_pre"] = (f, length, width, n, None, None)
                    continue
                if st["mode"] != MODE_CHAIN and sync_rot:
                    # 逐帧 step 可能先于 PARENTOPTIONS 执行，渲染前再同步一次，否则朝向落后一帧
                    _sync_parent_rot(p, em, st)
                body.append((p, st, f, length, width, n))
                continue
            pend.append((p, st, f, length, width, n))
            trail, max_len = _trail_span(p, em, st, length)
            trails.append(trail)
            max_lens.append(max_len)
            counts.append(n)

        if body:
            Q, starts, sizes = self._body_batch(numpy, body)
            self._store_pre(body, self._build_strips(numpy, Q, starts, sizes, body))
        if not pend:
            return

        # 弧长低于阈值时返回空：发射器未运动即没有条带，而非绘制一条直线
        got = None if numpy is None else _trail.clip_resample_batch(
            trails, max_lens, counts, min_arc=_STATIC_ARC_EPS)   # 新→旧即 base→tip
        if got is None:                 # 没有 numpy 时退回逐条标量计算
            pts_all = _trail.clip_resample_many(trails, max_lens, counts,
                                                min_arc=_STATIC_ARC_EPS)
            for rec, pts in zip(pend, pts_all):
                rec[1]["_pre"] = (rec[2], rec[3], rec[4], rec[5], None,
                                  pts)                # 新→旧即 base→tip
            return

        Q, starts, sizes = got
        strips = ([None] * len(pend) if Q is None
                  else self._build_strips(numpy, Q, starts, sizes, pend))
        self._store_pre(pend, strips)

    @staticmethod
    def _store_pre(recs, strips):
        for rec, strip in zip(recs, strips):
            rec[1]["_pre"] = (rec[2], rec[3], rec[4], rec[5], strip,
                              None if strip is not None else [])

    @staticmethod
    def _body_batch(numpy, recs):
        """定长面片与柔体链的顶点（base→tip），返回与 `clip_resample_batch` 相同的
        `(Q, starts, sizes)`，已套 spawnAnchorOffset。

        算式与 `_sample_points` + `_strip_py` 的锚点平移相同：定长面片为 `trail.straight`，
        柔体链为节点的拷贝。
        """
        rig, rig_o, rig_d = [], [], []
        chain, chain_xyz = [], []
        for k, (p, st, f, length, width, n) in enumerate(recs):
            if st["mode"] == MODE_CHAIN:
                chain.append(k)
                chain_xyz.extend((q.x, q.y, q.z) for q in st["nodes"])
            else:
                d = st["dir"].normalized(fallback=Vec3(0.0, 1.0, 0.0))
                step = float(length) / (n - 1)
                rig.append(k)
                rig_o.append((p.pos.x, p.pos.y, p.pos.z))
                rig_d.append((d.x * step, d.y * step, d.z * step))

        # 行按 rig 在前、chain 在后首尾相接
        order = rig + chain
        cnt = numpy.array([recs[k][5] for k in rig]
                          + [len(recs[k][1]["nodes"]) for k in chain], dtype=numpy.intp)
        first = numpy.zeros(len(order), dtype=numpy.intp)
        numpy.cumsum(cnt[:-1], out=first[1:])
        blocks = []
        if rig:
            ns = cnt[:len(rig)]
            total = int(ns.sum())
            i = (numpy.arange(total, dtype="f8")
                 - numpy.repeat(first[:len(rig)], ns).astype("f8"))
            blocks.append(numpy.repeat(numpy.array(rig_o, dtype="f8"), ns, axis=0)
                          + numpy.repeat(numpy.array(rig_d, dtype="f8"), ns, axis=0)
                          * i[:, None])
        if chain:
            blocks.append(numpy.array(chain_xyz, dtype="f8").reshape(-1, 3))
        Q = blocks[0] if len(blocks) == 1 else numpy.concatenate(blocks)

        # spawnAnchorOffset：沿各条带自身的首尾跨度平移
        anc = [((recs[k][2].get("spawnAnchorOffset") if recs[k][2] is not None else 0.0)
                or 0.0) for k in order]
        if any(anc):
            span = Q[first + cnt - 1] - Q[first]
            Q += numpy.repeat(span * numpy.array(anc, dtype="f8")[:, None], cnt, axis=0)

        starts = [-1] * len(recs)
        sizes = [0] * len(recs)
        for j, k in enumerate(order):
            starts[k] = int(first[j])
            sizes[k] = int(cnt[j])
        return Q, starts, sizes

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
            bs, ts = _fade_spans(f)
            base_spans.append(bs)
            tip_spans.append(ts)
            flaps.append(bool(st["flap"]))

        arr = lambda seq: numpy.array(seq, dtype="f8")
        rep = lambda seq: numpy.repeat(arr(seq), ns)

        # spawnAnchorOffset 已由调用方套在 Q 上（轨迹跟随不套，见模块 docstring）

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
        uv = self._uv_scale(p, f, points, width)
        if uv is not None:
            item.extra["uv_scale"] = uv
        return item

    @staticmethod
    def _uv_scale(p, f, points, width):
        """返回 `(长度方向重复次数, 宽度缩放)`；两者均为 1 时返回 None。"""
        if f is None:
            return None
        mode = f.i("uvScaleMode")
        w = f.get("uvScaleWidth", 1.0)
        if mode == _ruv.UV_SCALE_ASPECT:
            rep = _ruv.repeat_count(mode, p.rolled.get("rb_uvlen", 1.0),
                                    _arc_length(points), width * p.scale.x)
        else:
            rep = _ruv.repeat_count(mode, p.rolled.get("rb_uvlen", 1.0), 0.0, 0.0)
        if rep == 1.0 and w == 1.0:
            return None
        return (rep, w)

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
        base_span, tip_span = _fade_spans(f)

        # pts 按 base→tip 排列（index 0 为粒子所在一端）
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
        """返回按 base→tip 排列的顶点序列（index 0 为粒子所在一端）；空列表表示不绘制。"""
        mode = st["mode"]

        if mode == MODE_CHAIN:
            # 必须复制：节点属于模拟状态（`on_particle_step` 每帧原地修改），调用方会原地
            # 修改返回的点（锚点平移）
            return [q.copy() for q in st["nodes"]]   # 首节点位于粒子处，即 base

        if mode == MODE_TRAIL:
            trail, max_len = _trail_span(p, em, st, length)
            # 弧长低于阈值时提前返回空：发射器未运动即没有条带
            pts, _arc = _trail.clip_resample(trail, max_len, n, min_arc=_STATIC_ARC_EPS)
            return pts                                      # 新→旧即 base→tip

        # MODE_RIGID：刚性矩形，沿基准方向延伸。逐帧 step 可能先于 PARENTOPTIONS 执行，
        # 渲染前再同步一次，否则朝向落后一帧
        if getattr(em.config, "ribbon_rigid_dir", "parent") == "parent":
            _sync_parent_rot(p, em, st)
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
