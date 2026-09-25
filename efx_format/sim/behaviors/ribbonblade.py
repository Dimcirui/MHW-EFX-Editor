# -*- coding: utf-8 -*-
"""RIBBONBLADE —— 刀光拖尾。

刀光 = 刀身沿粒子轨迹扫过的面。刀身是从轨迹点沿 `widthDirection` **单侧**伸出的线段，方向在
粒子局部系内固定：出生时取发射器当时的旋转，之后只在 PARENTOPTIONS 跟随旋转时随发射器（含宿主）
转动；不随运动方向转，也不受 ROTATEANIM 自转影响。轨迹取粒子在世界空间的实际位移（自身速度或
跟随宿主），只有旋转、没有位移时不画。

字段职能：

    widthDirection          刀身伸出方向，AxisDirection6
    width                   刀身长度，游戏单位；负值向反方向伸出
    length                  lengthMode=0：保留最近 length+1 帧的轨迹
    lengthMode              切换长度模型，见下
    maxLengthLimit          lengthMode=1：刀光长度上限，游戏单位
    contractionSpeed        lengthMode=1：每秒持续回缩的长度，游戏单位
    interpolationCount      沿长度方向的插值细分数：相邻两帧之间按过点曲线（Catmull-Rom）补的点数，
                            0 时为逐帧折线
    head / tailEnd          EPVColorSlot 结构：color1 为端点颜色，size 为端点处的刀身长度倍率
    colourTransitionPoint   从头端起保持头端颜色的长度比例，其余部分线性过渡到尾端颜色
    emissiveStrength        自发光强度。挂 REFRACTION 时为线性乘数；否则按饱和曲线
                            `emissive_gain` 换算：1 时白色只显示为中灰，5 接近原色，10 以上饱和为白
    enableFlowmap / flow*   流动贴图组，与 BILLBOARD3D 同义，见 `_flowmap`
    uvRepetition            UV 沿长度方向的重复次数，未接入

长度模型：

    lengthMode=0  取最近 length+1 帧的轨迹（比字段值多 1 帧）；形状按满长度计算，出生不足时
                  出生点之前的部分截掉不画。maxLengthLimit、contractionSpeed 不参与
    lengthMode=1  长度从 0 起算：每帧 长度 = clamp(长度 + 本帧位移 − contractionSpeed/fps,
                  0, maxLengthLimit)，形状按当前长度计算；length 不参与。回缩持续生效，
                  回缩速度大于移动速度时刀光始终不可见；为 0 时停下后刀光一直保留

维护约束：
- 轨迹静止时不画，记录 note 说明原因，不得无提示地输出空结果。
- `item.color` 的 alpha 只取 `p.alpha`：两端颜色的 alpha 已逐点写入 `points` 的 alpha_mul，
  不得重复相乘。
- 没有 blendMode 字段，按加法混合处理。
"""

from ...hashes import REFRACTION, RIBBONBLADE
from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import BASE_AXES, RenderItem, Vec3
from . import _flowmap
from ..vecmath import rotate_euler
from ._common import emitter_rotate, rgba
from .parentoptions import ParentOptions

#: 没有 blendMode 字段，按加法混合处理。
_BLEND = "ADDITIVE"

#: emissiveStrength → 颜色倍率的饱和曲线 A·e/(e+c)，由纯白刀光的强度梯度拟合
_EMISSIVE_A = 1.41
_EMISSIVE_C = 2.9

#: 轨迹弧长不超过该值视为静止（游戏单位）。
_STATIC_ARC_EPS = 1e-4

#: lengthMode=1 下自行保留的路径点数上限；静止帧不记点。
_MAX_PATH = 512

#: 插值细分后的总点数上限，历史很长时按比例降低每段细分数
_MAX_DENSE = 512


def _trail_frames(f):
    """lengthMode=0 的拖尾帧数：比 length 多 1 帧。"""
    return max(1, f.i("length")) + 1


def emissive_gain(e, refraction=False):
    """emissiveStrength 换算为颜色倍率：折射为线性，其余按饱和曲线。"""
    e = float(e)
    if refraction:
        return e
    if e <= 0.0:
        return 0.0
    return _EMISSIVE_A * e / (e + _EMISSIVE_C)


def _slot_color(v):
    """返回 EPVColorSlot 结构（head / tailEnd）中的 color1(RGBA)。"""
    if isinstance(v, dict):
        return rgba(v.get("color1"))
    return (1.0, 1.0, 1.0, 1.0)


def _slot_size(v):
    """返回 EPVColorSlot 结构中的端点刀身长度倍率 size。"""
    if isinstance(v, dict):
        return float(v.get("size", 1.0))
    return 1.0


def _clip(hist, limit):
    """从最新点往回截取弧长不超过 `limit` 的一段，位置与刀身方向一并按弧长插值。

    `hist` 为 [(位置, 方向)]（旧→新），原地不动的帧不占段。返回 ([(位置, 方向, 距头端弧长)]
    新→旧, 弧长)。
    """
    if not hist:
        return [], 0.0
    q, d = hist[-1]
    out = [(q, d, 0.0)]
    acc = 0.0
    for bq, bd in reversed(hist[:-1]):
        seg = (bq - q).length()
        if seg <= 1e-9:
            continue
        if acc + seg >= limit:
            t = (limit - acc) / seg
            out.append((q + (bq - q) * t, d + (bd - d) * t, limit))
            return out, limit
        acc += seg
        out.append((bq, bd, acc))
        q, d = bq, bd
    return out, acc


def _densify(hist, n):
    """相邻两点之间按 Catmull-Rom 补 n 个点（位置与刀身方向同插），首尾端点重复作切线。"""
    m = len(hist)
    if n <= 0 or m < 2:
        return hist
    n = min(int(n), max(0, _MAX_DENSE // (m - 1) - 1))
    if n <= 0:
        return hist
    out = []
    for i in range(m - 1):
        p0 = hist[i - 1] if i > 0 else hist[i]
        p1, p2 = hist[i], hist[i + 1]
        p3 = hist[i + 2] if i + 2 < m else hist[i + 1]
        out.append(p1)
        for k in range(1, n + 1):
            t = k / float(n + 1)
            t2, t3 = t * t, t * t * t
            a = -0.5 * t3 + t2 - 0.5 * t
            b = 1.5 * t3 - 2.5 * t2 + 1.0
            c = -1.5 * t3 + 2.0 * t2 + 0.5 * t
            d = 0.5 * t3 - 0.5 * t2
            out.append((p0[0] * a + p1[0] * b + p2[0] * c + p3[0] * d,
                        p0[1] * a + p1[1] * b + p2[1] * c + p3[1] * d))
    out.append(hist[-1])
    return out


def _pad_history(hist, need, vel):
    """历史不足 `need` 帧时，按最早一段的位移往前外推补齐，用于求满长度刀光的弧长。"""
    missing = need - len(hist)
    if missing <= 0 or not hist:
        return hist
    if len(hist) >= 2:
        d = hist[1] - hist[0]
    else:
        d = vel
    if d.length() <= 1e-9:
        return hist
    first = hist[0]
    return [first - d * k for k in range(missing, 0, -1)] + list(hist)


def _sync_parent_rot(p, em, st):
    """把 PARENTOPTIONS 新施加到粒子上的旋转同步到刀身方向（同 RIBBON），按累计量求差。"""
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


@register(RIBBONBLADE)
class RibbonBlade(Behavior):
    """RENDER_BODY 阶段产出沿轨迹的条带，两端颜色不同。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_particle_spawn(self, p, em, rng):
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return
        idx = f.i("widthDirection")
        axis = BASE_AXES[idx] if 0 <= idx < len(BASE_AXES) else BASE_AXES[1]
        cur = self._source(p, em, None)[0]
        p.user[RibbonBlade] = {
            "axis": axis.copy(),
            "head": _slot_color(f.raw("head")),
            "tail": _slot_color(f.raw("tailEnd")),
            "head_size": _slot_size(f.raw("head")),
            "tail_size": _slot_size(f.raw("tailEnd")),
            # 刀身方向：出生时取发射器当前旋转，此后只随 PARENTOPTIONS 施加的旋转转动
            "dir": emitter_rotate(em, axis.copy()),
            # 逐帧 (位置, 刀身方向) 历史（旧→新）；lengthMode=1 只在移动的帧记点
            "hist": [],
            "len": 0.0,
            "last_p": p.pos.copy(),
            "last_e": em.origin.copy(),
        }
        st = p.user[RibbonBlade]
        st["hist"].append((cur.copy(), st["dir"].copy()))
        _flowmap.roll(p, _flowmap.FlagFields(f), rng)

    @staticmethod
    def _source(p, em, st):
        """本帧轨迹点与本帧位移：同 pick_trail，粒子自身有位移用粒子，否则用发射器。"""
        if st is None:
            return (em.origin if em.config.ribbon_trail_source == "emitter" else p.pos), 0.0
        mode = em.config.ribbon_trail_source
        dp = (p.pos - st["last_p"]).length()
        de = (em.origin - st["last_e"]).length()
        st["last_p"] = p.pos.copy()
        st["last_e"] = em.origin.copy()
        if mode == "emitter" or (mode != "particle" and dp <= 1e-9):
            return em.origin, de
        return p.pos, dp

    def on_particle_step(self, p, em):
        st = p.user.get(RibbonBlade)
        if st is None:
            return
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return
        cur, moved = self._source(p, em, st)
        _sync_parent_rot(p, em, st)
        rec = (cur.copy(), st["dir"].copy())
        hist = st["hist"]
        if len(hist) == 1 and (hist[0][0] - cur).length() <= 1e-9 and not st.get("stepped"):
            # 出生帧与首次步进是同一位置，不重复计一帧
            hist[0] = rec
            st["stepped"] = True
            return
        st["stepped"] = True
        if not f.i("lengthMode"):
            hist.append(rec)
            keep = _trail_frames(f) + 1
            if len(hist) > keep:
                del hist[:len(hist) - keep]
            return
        if moved > 1e-9:
            hist.append(rec)
            if len(hist) > _MAX_PATH:
                del hist[0]
        else:
            hist[-1] = (hist[-1][0], rec[1])
        cap = f.get("maxLengthLimit", 0.0)
        shrink = f.get("contractionSpeed", 0.0) / float(max(1, em.config.fps))
        length = st["len"] + moved - shrink
        if cap > 0.0:
            length = min(length, cap)
        st["len"] = max(0.0, length)

    def build_render(self, p, em, view, item):
        st = p.user.get(RibbonBlade)
        if st is None:
            return item
        f = em.f(RIBBONBLADE, p)
        if f is None:
            return item

        raw = st["hist"]
        hist = _densify(raw, f.i("interpolationCount"))
        if f.i("lengthMode"):
            # 按当前长度截取自身路径，形状按当前长度计算
            pts, arc = _clip(hist, st["len"])
            full = arc
        else:
            # 最近 length 帧：形状按满 length 帧计算，出生不足 length 帧时出生点之前截掉不画
            frames = _trail_frames(f)
            pts, arc = _clip(hist, float("inf"))
            full = arc
            if len(raw) < frames + 1:
                # 缺的帧按出生速度外推，只补这段外推长度（逐帧折线）
                pos = [q for q, _d in raw]
                _o, padded = _clip([(q, q) for q in _pad_history(pos, frames + 1, p.vel)],
                                   float("inf"))
                _o, chord = _clip([(q, q) for q in pos], float("inf"))
                full = arc + max(0.0, padded - chord)
        if len(pts) < 2 or arc <= _STATIC_ARC_EPS:
            em.note("RIBBONBLADE 只由粒子的实际位移画出轨迹；粒子和宿主都静止时没有刀光")
            return RenderItem(kind="NONE")
        pts = pts[::-1]                                     # 反转为 tail→head

        width = f.get("width", 1.0) * p.scale.x
        emissive = emissive_gain(f.get("emissiveStrength", 1.0) or 1.0,
                                 em.f(REFRACTION, p) is not None)

        cut = max(0.0, min(1.0, f.get("colourTransitionPoint", 0.0)))
        tr, tg, tb, ta = st["tail"]
        hr, hg, hb, ha = st["head"]
        ts, hs = st["tail_size"], st["head_size"]

        points = []
        prgb = []
        pt = []
        sides = []
        cr, cg, cb = emissive * p.color[0], emissive * p.color[1], emissive * p.color[2]
        for q, d, dist in pts:
            # 在满长度刀光中的位置：0 = 尾端，1 = 头端
            u = 1.0 - dist / full if full > 0.0 else 1.0
            # 头端 cut 比例内保持头端颜色，其余线性过渡到尾端颜色
            w = 1.0 if u >= 1.0 - cut else u / max(1e-6, 1.0 - cut)
            wd = d.normalized(fallback=st["axis"])
            # 刀身从轨迹点单侧伸出：条带中线放在刀身中点，半宽为刀身一半
            half = 0.5 * width * (ts + (hs - ts) * u)
            mid = Vec3(q.x + wd.x * half, q.y + wd.y * half, q.z + wd.z * half)
            points.append((mid, half, (ta + (ha - ta) * w) * p.alpha))
            pt.append(u)
            sides.append(wd)
            prgb.append(((tr + (hr - tr) * w) * cr, (tg + (hg - tg) * w) * cg,
                         (tb + (hb - tb) * w) * cb))

        # 整体颜色取两端的中间值；逐点 alpha 已包含过渡
        mid = 0.5
        item = RenderItem(kind="RIBBON", pos=pts[-1][0].copy())
        item.points = points
        item.size = Vec3(abs(width), arc, 1.0)
        item.color = [(tr + (hr - tr) * mid) * emissive * p.color[0],
                      (tg + (hg - tg) * mid) * emissive * p.color[1],
                      (tb + (hb - tb) * mid) * emissive * p.color[2],
                      p.alpha]
        item.blend = _BLEND
        # 渲染主体自身的颜色；RGBFIRE / RGBWATER 的两层颜色在 glue 侧再乘上它
        item.extra["base_tint"] = ((tr + (hr - tr) * mid) * emissive,
                                   (tg + (hg - tg) * mid) * emissive,
                                   (tb + (hb - tb) * mid) * emissive)
        # 逐点刀身方向（尾→头），条带横向取它而不面向镜头
        item.extra["side"] = sides
        # 逐点 RGB（尾→头），两端颜色沿刀光过渡；整条颜色只作兜底
        item.extra["point_rgb"] = prgb
        # 逐点在满长度刀光中的位置（尾→头），贴图 V 按它铺：头端 V=0、满长度尾端 V=1
        item.extra["point_t"] = pt
        item.extra["width_dir"] = sides[-1]
        item.extra["age"] = p.age
        return _flowmap.apply(p, em, item)
