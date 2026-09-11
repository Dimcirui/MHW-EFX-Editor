# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/_common.py  —  渲染主体之间共享的小件

BILLBOARD3D / PLANE / RIBBON / MESH 都有同一组颜色字段（color / colorRange /
useColorRange / brightness / blendMode），语义也一致，抽出来免得四份各写一遍、
各错一处。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ..state import Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler

BLEND_ALPHA = 0
BLEND_ADDITIVE = 1


def rgba(seq):
    """XYZ type 2 的四个字节（`<4B`）→ 0-1 浮点四元组。

    第四字节在 codec 里叫 pad、在 annotations 里叫 RGBA 的 A。实测样本恒为 255，
    两种读法结果相同，故一并当 alpha 用——是 pad 的话也只是乘 1.0。
    """
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return (1.0, 1.0, 1.0, 1.0)
    a = float(seq[3]) / 255.0 if len(seq) > 3 else 1.0
    return (float(seq[0]) / 255.0, float(seq[1]) / 255.0, float(seq[2]) / 255.0, a)


def pick_color(f, t, color_field="color", range_field="colorRange"):
    """在 color 与 colorRange 之间按 `t` 插值。`t` 由 useColorRange 决定（0=不插值）。

    整条通道共用一个 t（而不是逐通道独立随机）——「颜色范围」这个说法更像是在
    两个颜色之间取值，而不是把三个通道各自打散。未实测。
    """
    r, g, b, a = rgba(f.raw(color_field))
    if not t:
        return (r, g, b, a)
    r1, g1, b1, a1 = rgba(f.raw(range_field))
    return (r + (r1 - r) * t, g + (g1 - g) * t,
            b + (b1 - b) * t, a + (a1 - a) * t)


def color_lerp_t(f, rng, field="useColorRange"):
    """useColorRange 开着就抽一个插值系数，否则 0。"""
    return rng.random() if f.i(field) else 0.0


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
