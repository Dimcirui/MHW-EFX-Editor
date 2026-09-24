# -*- coding: utf-8 -*-
"""渲染主体之间共用的函数。

BILLBOARD3D / PLANE / RIBBON / MESH 具有同一组语义相同的颜色字段（color / colorRange /
useColorRange / brightness / blendMode（启用自发光）），统一在此实现，避免四处重复及由此产生的不一致。

染色模型：`color` 与 `colorRange` 是 RGBA 四元组的两端，所有通道（含 alpha）共用一个随机
系数在两者之间插值，颜色落在两端连线上：

    通道值 = color[i] + (colorRange[i] − color[i]) × t，t 每个粒子抽一次

仅在 `useColorRange=1` 时抽取，否则直接使用 color；MESH 另有总开关 `disableAllColorRange`。

发射器动态旋转：`rot_dynamic` 为发射器自身的旋转量，`host_rotation` 为从 PTLIFE 父实例继承的
旋转量。父发射器旋转时，其派生的子发射器（包括生成位置与初速度）须随之旋转，否则子特效始终朝
同一方向发射。两者使用同一 `rot_order`，按同一欧拉顺序相加，与先后无关。静态旋转由宿主负责。

条带轨迹来源：RIBBON 的字段说明为「沿**发射器**实际经过的轨迹」，而带 VELOCITY3D 的条带粒子
各自有独立轨迹，两种用法均存在。因此 `pick_trail` 默认 `'auto'`：粒子自身有位移时使用粒子
轨迹，否则（完全依靠骨骼绑定运动的情形）使用发射器轨迹；`SimConfig.ribbon_trail_source` 可
强制指定。

两层颜色的合成：渲染链中每个粒子只有一个颜色，而 RGBFIRE / RGBWATER 有两层，按贴图通道分层
需在 fragment shader 中完成。`blend_two_colors` 按权重合成代表色，两层颜色仍保存在
`p.rolled` 中供 shader 使用。

维护约束：
- 抽取的系数必须保存在 `p.rolled`：带 TIML 的属性逐帧重新求值静态色后，须按同一组系数重新
  计算，否则随机结果会因曲线的存在而每帧变化。
- RGB 不做截断（加法混合下超出范围即更亮，brightness 可达 50），alpha 截断到 [0,1]（大于 1
  对混合无意义，且会抵消 LIFE 的淡入淡出）。
"""

import math

from ..rng import jitter, jitter_int
from ..state import Vec3
from ..vecmath import ROT_ORDER_TRANSFORM, rot_order_name, rotate_euler

def rgba(seq, missing=1.0):
    """将 XYZ type 2 的四个字节（`<4B`）转换为 0-1 浮点四元组。

    第四字节在 codec 中名为 pad，此处用作 alpha。`missing` 为字节数不足时的补充值：颜色取
    1.0（不透明白色），随机量取 0。
    """
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return (missing, missing, missing, missing)
    a = float(seq[3]) / 255.0 if len(seq) > 3 else missing
    return (float(seq[0]) / 255.0, float(seq[1]) / 255.0, float(seq[2]) / 255.0, a)


#: 不启用随机时的抽取结果：四通道系数均为 0，即直接使用 color
NO_ROLL = ("lerp", (0.0, 0.0, 0.0, 0.0))


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _mix(base, other, roll):
    """将出生时抽取的系数应用于静态色（可能已由 TIML 更新）。"""
    _kind, k = roll
    out = [base[i] + (other[i] - base[i]) * k[i] for i in range(4)]
    return (out[0], out[1], out[2], _clamp01(out[3]))


def roll_rgba(f, rng, cfg, color_field="color", range_field="colorRange",
              gate="useColorRange", disable=None):
    """返回本粒子的 RGBA 与抽取结果 `(rgba4, roll)`。

    `roll` 须原样保存在 `p.rolled`，供 `pick_color(f, roll)` 在 TIML 更新静态色后按同一组
    系数重新计算。
    """
    base = rgba(f.raw(color_field))
    on = not (disable and f.i(disable)) and (not gate or f.i(gate))
    if not on:
        return base, NO_ROLL

    t = rng.random()
    roll = ("lerp", (t, t, t, t))
    return _mix(base, rgba(f.raw(range_field)), roll), roll


def jitter_offsets(f, rolled):
    """出生时记下各字段抽到的值与当时静态值之差，`rolled` 为 {字段名: 抽到的值}。

    带 TIML 时字段每帧按曲线重新求值，再加回这份偏移（见 `with_offset`），否则随机部分会丢失。
    """
    return {k: v - f.get(k, 1.0) for k, v in rolled.items()}


def with_offset(f, field, offs, default=1.0):
    """返回字段的当前曲线值加上出生时的随机偏移。"""
    return f.get(field, default) + (offs.get(field, 0.0) if offs else 0.0)


def pick_color(f, roll=NO_ROLL, color_field="color", range_field="colorRange"):
    """以当前静态色与出生时抽取的系数计算颜色，供 TIML 逐帧重新求值使用。"""
    if roll is None:
        roll = NO_ROLL
    return _mix(rgba(f.raw(color_field)), rgba(f.raw(range_field)), roll)


def quad_size(p, cfg, scale, width, height):
    """面片本帧的宽高（`Vec3`，z 恒为 1），结果限定为非负。

    SizeScalarAdd 的增量加在 `scale` 上，SizeXAdd / SizeYAdd 的增量加在从 1 起的逐轴倍率上。
    """
    ax = p.rolled.get("sa_axis")
    s = max(0.0, scale + p.rolled.get("sa_scalar", 0.0))
    if ax is None:
        return Vec3(width * s, height * s, 1.0)
    return Vec3(width * max(0.0, 1.0 + ax[0]) * s, height * max(0.0, 1.0 + ax[1]) * s, 1.0)


def emissive_on(f):
    """「启用自发光」（ori_name 为 blendMode）：开启时 brightness 生效，关闭时亮度按 1 计。

    它不决定混合方式，混合方式由 SHADERSETTINGS.blendStateType 决定。
    """
    return bool(f.i("blendMode"))


def epv_note(f, em, block, *slots):
    """任一 EPV 颜色槽位非 0 时记录 note：游戏内颜色取自 .epv，本地 color 不生效。

    预览无法读取 .epv，仍使用本地值；修改颜色无效是游戏内的实际行为，而非预览缺陷。
    """
    if any(f.i(s) for s in slots if f.has(s)):
        em.note("%s 绑了 EPV 颜色槽位：游戏内颜色来自 .epv，本地 color 不生效"
                "（预览仍按本地值画）" % block)


# ─────────────────────────────────────────────────────────────────────────────
# 固定朝向面片的基（PLANE 与 RIBBON 的定长面片模式共用）
# ─────────────────────────────────────────────────────────────────────────────

def oriented_basis(normal, spin_deg=0.0):
    """由法线构造一对正交的横纵轴 `(u, v)`，`spin_deg` 为绕法线的自转角。

    法线退化时回退为世界 X/Y，不抛出异常。
    """
    n = normal.normalized(fallback=Vec3(0.0, 0.0, 1.0))
    # 选取与 n 不平行的参考轴进行叉乘
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
    """返回 baseAxis（AxisDirection6）经 rotationX/Y/Z 旋转后的朝向向量。

    给出 `rolled` 时使用其中逐粒子抽取的三个角，否则读取静态字段。旋转顺序使用
    `_TRANSFORM_ROT_ORDER`，与 PLANE、MESH 一致。
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
    """按发射器的动态旋转（自身与继承之和）旋转方向向量 `v`；无旋转时原样返回。"""
    hr = em.host_rotation
    rx = em.rot_dynamic.x + hr.x
    ry = em.rot_dynamic.y + hr.y
    rz = em.rot_dynamic.z + hr.z
    if not (rx or ry or rz):
        return v
    return rotate_euler(v, rx, ry, rz, order=em.rot_order,
                        applied=em.config.rot_order_applied)


def emitter_place(em, local):
    """将发射器局部偏移转换为相对发射器原点的偏移：先施加动态缩放，再施加动态旋转。"""
    s = em.scale_dynamic
    if s.x != 1.0 or s.y != 1.0 or s.z != 1.0:
        local = Vec3(local.x * s.x, local.y * s.y, local.z * s.z)
    return emitter_rotate(em, local)


def pick_trail(p, em):
    """返回条带类渲染体使用的轨迹：粒子轨迹或发射器轨迹。"""
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
# ColorParam —— RGBFIRE / RGBWATER 共用的单色生命期时序块
#
# 每段 10 个 int，各段结构相同（RGBWATER 的第三段只有 9 个，没有 correctColorNo）：
#     useLife │ appearFrame(+J) │ keepFrame(+J) │ vanishFrame(+J) │ lighting │ lifeType
# useLife=0 时整段不生效，段内 keep/vanish 保持默认值，不具参考意义。
# `lighting`（是否受光照）与 `lifeType` 作用未知，不参与计算。
# ─────────────────────────────────────────────────────────────────────────────

def roll_color_param(f, rng, cfg, prefix):
    """出生时抽取一段 ColorParam，返回供 `color_param_weight` 使用的 dict。"""
    if not f.i(prefix + "useLife"):
        return None                 # 整段不生效，权重恒为 1
    appear = max(0, jitter_int(f.get(prefix + "appearFrame"),
                               f.get(prefix + "appearFrameJitter"), rng))
    keep = max(0, jitter_int(f.get(prefix + "keepFrame"),
                             f.get(prefix + "keepFrameJitter"), rng))
    vanish = max(0, jitter_int(f.get(prefix + "vanishFrame"),
                               f.get(prefix + "vanishFrameJitter"), rng))
    return {"appear": appear, "keep": keep, "vanish": vanish}


def color_param_weight(st, age):
    """返回该段颜色在 `age` 帧时的权重（0~1），依次为淡入 appear、保持 keep、淡出 vanish。"""
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


# ─────────────────────────────────────────────────────────────────────────────
# 双重正弦振荡器 —— NOISE / BLINK 共用的频率换算
# ─────────────────────────────────────────────────────────────────────────────

def oscillator_omega(cfg, freq):
    """将 LowFrequency / HighFrequency（每秒周期数）换算为每帧弧度。"""
    fps = float(getattr(cfg, "fps", 60) or 60)
    return 2.0 * math.pi * float(freq) / fps


def blend_two_colors(cfg, c0, w0, c1, w1):
    """按两层各自的权重将两种颜色加权平均为一个 tint。"""
    t = w0 + w1
    if t <= 1e-9:
        return [0.5 * (c0[i] + c1[i]) for i in range(3)]
    return [(c0[i] * w0 + c1[i] * w1) / t for i in range(3)]
