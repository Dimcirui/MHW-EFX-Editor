# -*- coding: utf-8 -*-
"""flowmap（流动贴图）字段组的共用实现。

BILLBOARD3D / PLANE / BILLBOARD2D 各自带有同一组八个字段，flowmap 不是独立的属性类型，因此
本模块提供**共用函数**而非 `@register` 的 behavior——一个 type_hash 只能绑定一个 behavior。
各渲染体在自身的 `on_particle_spawn` / `build_render` 中分别调用。

字段职能：

    applicationRule                位域。0x04 = 启用，0x08 = 播放一次后停止，
                                   0x10 = 逆向播放（仅播放一次时生效）
    path                           流动贴图的游戏路径
    flowmapSpeed(+Jitter)             相位推进速度，每秒轮数
    flowmapSpeedCoef(+Jitter)         逐帧速度倍率
    flowmapStrength(+Jitter)          扭曲幅度
    flowmapStrengthCoef(+Jitter)      逐帧强度倍率

两个 Coef 是每帧作用一次的衰减率，与 TRANSFORM3D 的 `_modifier` 属于同一类。相位与强度均有
闭式解，无需逐帧递推：

    相位   step·t                 （Coef == 1）
           step·(c^t − 1)/(c − 1) （等比数列求和）
    强度   strength · c^t

一层的采样位置 = UV − strength × p × f，f 为流动方向（`rg×2−1`，y 以贴图像素向下为正），
p 为一轮内的位置，从 0 走到 1；越界取边缘像素。

- 循环：两层相位错开半轮叠加，权重为三角波 1 − |2p − 1|，两层之和为 1。一层回绕时权重正好
  为 0，因此没有跳变。速度为 0 时只剩 p = 0.5 的一层，即 UV − 0.5 × strength × f。
- 播放一次后停止：只有一层，p 从 0 走到 1 后停住；逆向模式下从 1 走到 0。

输出 `item.extra`：`flowmap` = 当前强度，`flowmap_phase` = 相位，`flowmap_loop` = 是否按
两层循环。逐纹素位移由预览 shader 计算，位移量再乘以当前序列帧单格的尺寸。

维护约束：
- 位移量必须按序列帧单格的尺寸缩放，而非整张贴图。`strength` 的常见取值 0.2 若按整张贴图计算，
  一次即跨过一格半。
"""

from ..rng import jitter

#: applicationRule 的位，与 schema/enums.py::BITS_APPLICATION_RULE 同一套
BIT_ENABLE = 0x04
BIT_FREEZE = 0x08
BIT_REVERSE = 0x10

#: 存进 p.rolled 的键
KEY = "flowmap"


def roll(p, f, rng, mode):
    """出生时抽取四个 Jitter 并写入 p.rolled；未启用或未配置时不写入。"""
    if f is None:
        return
    rule = int(f.i("applicationRule") or 0)
    if not (rule & BIT_ENABLE):
        return
    speed = jitter(f.get("flowmapSpeed", 0.0), f.get("flowmapSpeedJitter"), rng, mode)
    strength = jitter(f.get("flowmapStrength", 0.0), f.get("flowmapStrengthJitter"),
                      rng, mode)
    if not strength:
        return              # 强度为 0 时无位移，速度取值不影响画面
    freeze = bool(rule & BIT_FREEZE)
    p.rolled[KEY] = (float(speed), float(strength),
                     float(f.get("flowmapSpeedCoef", 1.0) or 1.0),
                     float(f.get("flowmapStrengthCoef", 1.0) or 1.0),
                     freeze,
                     freeze and bool(rule & BIT_REVERSE))


def _geometric(step, coef, t):
    """返回 Σ step·coef^k（k=0..t-1）；coef==1 时为 step·t。"""
    if abs(coef - 1.0) < 1e-9:
        return step * t
    try:
        return step * (coef ** t - 1.0) / (coef - 1.0)
    except (OverflowError, ValueError):
        return step * t


def apply(p, em, item, key=KEY):
    """将本帧强度与相位写入 `item.extra` 并返回 item；未启用时原样返回。

    `key` 为参数在 p.rolled 里的键，UVCONTROL 的 flowmap 组另存一份。
    """
    got = p.rolled.get(key)
    if item is None or item.kind == "NONE" or not got:
        return item
    speed, strength, s_coef, t_coef, freeze, reverse = got
    t = float(p.age)

    fps = float(getattr(em.config, "fps", 60) or 60)
    phase = _geometric(speed / fps, s_coef, t)
    if freeze:
        # 播放一次后停止：相位停在一轮末尾，负速度对称
        phase = max(-1.0, min(1.0, phase))
        if reverse:
            phase = (1.0 if phase >= 0.0 else -1.0) - phase
    if abs(t_coef - 1.0) > 1e-9:
        try:
            strength = strength * (t_coef ** t)
        except (OverflowError, ValueError):
            pass

    if strength:
        item.extra[KEY] = strength
        item.extra[KEY + "_phase"] = phase
        item.extra[KEY + "_loop"] = not freeze
    return item
