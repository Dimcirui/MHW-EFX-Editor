# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/_common.py  —  渲染主体之间共享的小件

BILLBOARD3D / PLANE / RIBBON / MESH 都有同一组颜色字段（color / colorRange /
useColorRange / brightness / blendMode），语义也一致，抽出来免得四份各写一遍、
各错一处。

染色模型：color / colorRange 是 RGBA 四元组的 static / random 对
--------------------------------------------------------------
每个通道**各自独立**在 color 与 colorRange 之间抽一个值，**alpha（第 4 字节）
同样参与**：

    通道值 = color[i] + (colorRange[i] - color[i]) × t[i]，t[i] 逐通道独立抽

（`useColorRange=1` 时才抽；关着就用 color 原样。MESH 另有 disableAllColorRange 总闸。）

为什么不是「color + 随机[0, colorRange]」的加法量读法：那要求作者把
color+colorRange 控制在 255 以内，而官方语料里 BILLBOARD3D 只有 6.1% 满足、
RIBBON 0.9%；且 colorRange 的第 4 字节绝大多数是 255——当「第二个颜色的 alpha」
讲得通，当「alpha 的随机量」讲不通。故按「范围的另一端」读。
`SimConfig.color_range_mode` 可切：
    'channel'（默认）逐通道各抽一个 t
    'shared'        整条通道共用一个 t（改动前的行为）
    'add'           加法量读法 color + 随机[0, colorRange]

抽到的系数存进 `p.rolled`，挂了 TIML 的块逐帧重解静态色之后按同一组系数重算，
这样「曲线改色」和「逐粒子随机」能共存。RGB 不夹取（加法混合下越界就是更亮，
brightness/ColorRate 本来就能到 50），alpha 夹到 [0,1]（>1 对混合无意义，
还会把 LIFE 的淡入淡出顶掉）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ..rng import jitter, jitter_int
from ..state import Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler

BLEND_ALPHA = 0
BLEND_ADDITIVE = 1


def rgba(seq, missing=1.0):
    """XYZ type 2 的四个字节（`<4B`）→ 0-1 浮点四元组。

    第四字节在 codec 里叫 pad、在 annotations 里叫 RGBA 的 A，这里当 alpha 用。
    `missing` 是字节数不足时的补值：颜色补 1.0（不透明白），随机量那一侧补 0。
    """
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return (missing, missing, missing, missing)
    a = float(seq[3]) / 255.0 if len(seq) > 3 else missing
    return (float(seq[0]) / 255.0, float(seq[1]) / 255.0, float(seq[2]) / 255.0, a)


#: 不随机时的抽签结果（四通道系数全 0 → 就用 color 原样）
NO_ROLL = ("lerp", (0.0, 0.0, 0.0, 0.0))


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _mix(base, other, roll):
    """把出生时抽好的系数套到（可能刚被 TIML 改过的）静态色上。"""
    kind, k = roll
    if kind == "add":
        out = [base[i] + k[i] for i in range(4)]
    else:
        out = [base[i] + (other[i] - base[i]) * k[i] for i in range(4)]
    return (out[0], out[1], out[2], _clamp01(out[3]))


def roll_rgba(f, rng, cfg, color_field="color", range_field="colorRange",
              gate="useColorRange", disable=None):
    """本粒子的 RGBA + 抽签结果。返回 `(rgba4, roll)`。

    `roll` 原样存进 `p.rolled`，之后 `pick_color(f, roll)` 可在 TIML 改过静态色
    之后用同一组系数重算——随机形态不会因为挂了曲线就每帧重抽。
    """
    base = rgba(f.raw(color_field))
    on = not (disable and f.i(disable)) and (not gate or f.i(gate))
    if not on:
        return base, NO_ROLL

    mode = getattr(cfg, "color_range_mode", "channel")
    if mode == "add":
        amt = rgba(f.raw(range_field), missing=0.0)
        roll = ("add", tuple(jitter(0.0, a, rng, cfg.jitter_mode) for a in amt))
    elif mode == "shared":
        t = rng.random()
        roll = ("lerp", (t, t, t, t))
    else:                                    # 'channel'（默认）：逐通道独立
        roll = ("lerp", tuple(rng.random() for _ in range(4)))
    return _mix(base, rgba(f.raw(range_field)), roll), roll


def pick_color(f, roll=NO_ROLL, color_field="color", range_field="colorRange"):
    """（TIML 逐帧重解用）当前静态色 + 出生时抽好的系数。"""
    if roll is None:
        roll = NO_ROLL
    return _mix(rgba(f.raw(color_field)), rgba(f.raw(range_field)), roll)


def blend_name(f, field="blendMode"):
    """ENUM_BLEND_MODE: 0=Alpha 混合，1=Add 叠加。"""
    return "ADDITIVE" if f.i(field) == BLEND_ADDITIVE else "ALPHA"


def epv_note(f, em, block, *slots):
    """EPV 颜色槽位非 0 时，游戏内颜色来自 .epv，本地 color 不生效。

    预览拿不到 .epv，照常用本地值，但记一条 note——免得用户以为「改了颜色没反应」
    是预览的 bug，那恰恰是游戏内的真实行为。
    """
    if any(f.i(s) for s in slots if f.has(s)):
        em.note("%s 绑了 EPV 颜色槽位：游戏内颜色来自 .epv，本地 color 不生效"
                "（预览仍按本地值画）" % block)


# ─────────────────────────────────────────────────────────────────────────────
# 固定朝向面片的基（PLANE / RIBBON 的定长面片模式都要）
# ─────────────────────────────────────────────────────────────────────────────

def oriented_basis(normal, spin_deg=0.0):
    """由法线构造一对正交的横/纵轴；`spin_deg` 是绕法线的自转。

    返回 (u, v)。法线退化时退回世界 X/Y，不抛。
    """
    import math

    n = normal.normalized(fallback=Vec3(0.0, 0.0, 1.0))
    # 选一个和 n 不平行的参考轴来叉乘
    ref = Vec3(0.0, 1.0, 0.0)
    if abs(n.dot(ref)) > 0.99:
        ref = Vec3(1.0, 0.0, 0.0)
    u = ref.cross(n).normalized(fallback=Vec3(1.0, 0.0, 0.0))
    v = n.cross(u).normalized(fallback=Vec3(0.0, 1.0, 0.0))

    if spin_deg:
        a = math.radians(spin_deg)
        c, s = math.cos(a), math.sin(a)
        u, v = (u * c + v * s), (v * c - u * s)
    return u, v


def axis_normal(f, cfg, axis_field="baseAxis", rot_prefix="rotation",
                order_field="rotationOrder", rolled=None):
    """baseAxis（AxisDirection6）经 rotationX/Y/Z 旋转后的朝向向量。

    `rolled` 给了就用里面抽好的三个角（逐粒子抖动过的），否则直接读静态字段。
    旋转顺序用 _TRANSFORM_ROT_ORDER（PLANE 的 rotationOrder 实机确认与 MESH 同款）。
    """
    from ..state import BASE_AXES

    idx = f.i(axis_field)
    axis = BASE_AXES[idx] if 0 <= idx < len(BASE_AXES) else BASE_AXES[1]
    if rolled is not None:
        rx, ry, rz = rolled
    else:
        rx = f.get(rot_prefix + "X")
        ry = f.get(rot_prefix + "Y")
        rz = f.get(rot_prefix + "Z")
    order = rot_order_name(f.i(order_field), ROT_ORDER_TRANSFORM)
    return rotate_euler(axis, rx, ry, rz, order=order, applied=cfg.rot_order_applied)


def emitter_rotate(em, v):
    """按发射器的**动态**旋转转一个方向向量（静态部分由宿主负责，见 transform3d）。

    `rot_dynamic` 是这个发射器自己转的量；`host_rotation` 是从 PTLIFE 父实例继承
    来的那份（见 scene.py::SimScene._follow）——父发射器转起来，它召唤出的子发射器
    （及其生成方式/初速度）要跟着一起转，否则子特效永远只朝同一个方向发射，'
    看不出父的旋转。两者按同一套 Euler 顺序相加，不分先后（都是同一个 rot_order）。
    """
    hr = em.host_rotation
    rx = em.rot_dynamic.x + hr.x
    ry = em.rot_dynamic.y + hr.y
    rz = em.rot_dynamic.z + hr.z
    if not (rx or ry or rz):
        return v
    return rotate_euler(v, rx, ry, rz, order=em.rot_order,
                        applied=em.config.rot_order_applied)


def emitter_place(em, local):
    """发射器局部偏移 → 相对发射器原点的偏移：先动态缩放，再动态旋转。

    生成方式（EMITTERSHAPE3D）算出来的采样点是发射器局部的，发射器自己在转/缩放时
    这个点得跟着走，否则「转着喷」看起来像「原地喷」。
    """
    s = em.scale_dynamic
    if s.x != 1.0 or s.y != 1.0 or s.z != 1.0:
        local = Vec3(local.x * s.x, local.y * s.y, local.z * s.z)
    return emitter_rotate(em, local)


def pick_trail(p, em):
    """条带类渲染体该沿谁的轨迹画。

    RIBBON 的 annotations 原话是「沿**发射器**实际划过的轨迹」，可 ribbon_particle
    那种带 VELOCITY3D 的条带粒子显然各画各的。两种用法都真实存在，故默认 'auto'：
    粒子自己动过就用粒子的轨迹，没动过（blade_trail 那种整个靠绑骨挥动的）就退回
    发射器的轨迹。`SimConfig.ribbon_trail_source` 可强制其一。
    """
    mode = em.config.ribbon_trail_source
    if mode == "particle":
        return p.trail
    if mode == "emitter":
        return em.trail
    if len(p.trail) >= 2:
        head, tail = p.trail[-1], p.trail[0]
        if (head - tail).length() > 1e-6:
            return p.trail
    return em.trail


# ─────────────────────────────────────────────────────────────────────────────
# ColorParam —— RGBFIRE / RGBWATER 共用的「一种颜色的生命期时序块」
#
# 10 个 int 一段，逐位同构（RGBWATER 的第三段只有 9 位，没有 unkn9）：
#     useLife │ appearFrame(+J) │ keepFrame(+J) │ vanishFrame(+J) │ lighting │ lifeType
# useLife=0 时整段不生效——语料里 RGBFIRE 的 fire 段只有 10.7% 开、smoke 段 22.3%，
# 关着的那些 keep/vanish 仍停在 20/40 这组默认值上，是惰性的。
# `lighting`（是否受光照）与 `lifeType`（99.6% 为 0）作用未知，不参与计算。
# ─────────────────────────────────────────────────────────────────────────────

def roll_color_param(f, rng, cfg, prefix):
    """出生时抽定一段 ColorParam。返回 dict，喂给 `color_param_weight`。"""
    if not f.i(prefix + "useLife"):
        return None                 # 整段不生效 → 权重恒 1
    mode = cfg.jitter_mode
    appear = max(0, jitter_int(f.get(prefix + "appearFrame"),
                               f.get(prefix + "appearFrameJitter"), rng, mode))
    keep = max(0, jitter_int(f.get(prefix + "keepFrame"),
                             f.get(prefix + "keepFrameJitter"), rng, mode))
    vanish = max(0, jitter_int(f.get(prefix + "vanishFrame"),
                               f.get(prefix + "vanishFrameJitter"), rng, mode))
    return {"appear": appear, "keep": keep, "vanish": vanish}


def color_param_weight(st, age):
    """这一段颜色在 `age` 帧时的权重（0~1）：淡入 appear → 持续 keep → 淡出 vanish。"""
    if st is None:
        return 1.0
    a, k, v = st["appear"], st["keep"], st["vanish"]
    if age < a:
        return float(age) / a if a else 1.0
    age -= a
    if age < k:
        return 1.0
    age -= k
    if v <= 0:
        return 0.0
    if age >= v:
        return 0.0
    return 1.0 - float(age) / v


def blend_two_colors(cfg, c0, w0, c1, w1):
    """两种颜色 → 一个 tint。`SimConfig.rgb_tint_mode` 选怎么合。

    我们的渲染链每个粒子只有一个颜色，而 RGBFIRE/RGBWATER 是两层（外缘/内部、
    高光/水膜），真照实机那样按贴图亮度分层要进 fragment shader。这里先按权重合成
    一个代表色，两种颜色本身仍原样留在 `p.rolled` 里，等 shader 那一步直接取用。
    """
    mode = getattr(cfg, "rgb_tint_mode", "weighted")
    if mode == "first":
        return list(c0)
    if mode == "second":
        return list(c1)
    if mode == "mix":
        w0 = w1 = 1.0
    t = w0 + w1
    if t <= 1e-9:
        return [0.5 * (c0[i] + c1[i]) for i in range(3)]
    return [(c0[i] * w0 + c1[i] * w1) / t for i in range(3)]
