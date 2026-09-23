# -*- coding: utf-8 -*-
"""flowmap（流动贴图）字段组的共用实现。

BILLBOARD3D / PLANE / BILLBOARD2D 各自带有同一组八个字段，flowmap 不是独立的属性类型，因此
本模块提供**共用函数**而非 `@register` 的 behavior——一个 type_hash 只能绑定一个 behavior。
各渲染体在自身的 `on_particle_spawn` / `build_render` 中分别调用。

字段职能：

    applicationRule                位域。bit 0x04 = 启用，bit 0x08 = 播放一次后停止
    path                           流动贴图的游戏路径
    flowmapSpeed(+Jitter)          相位推进速度
    flowmapSpeedCoef(+Jitter)      逐帧速度倍率
    flowmapStrength(+Jitter)       扭曲幅度
    flowmapStrengthCoef(+Jitter)   逐帧强度倍率

两个 Coef 是每帧作用一次的衰减率，与 TRANSFORM3D 的 `_modifier` 属于同一类。相位与强度均有
闭式解，无需逐帧递推：

    相位   step·t                 （Coef == 1）
           step·(c^t − 1)/(c − 1) （等比数列求和）
    强度   strength · c^t

输出 `item.extra["flowmap"]` 为标量位移量 = 相位映射 × 当前强度。逐纹素位移由 glue 的 shader
完成：按流动贴图的 RG 通道（切线空间法线，`rg×2−1` 即二维方向）偏移 UV，位移量再乘以当前
序列帧单格的尺寸。

两项未确定的读法以 `SimConfig.UNKNOWNS` 开关保留：`flowmap_speed_unit`（speed 的单位为每秒
或每帧，默认每秒）与 `flowmap_phase`（相位到位移的映射：`cycle` 取小数部分映射到 −1..1，
结果有界；`linear` 持续累积）。`applicationRule` 中三选一的应用模式完全未知，不参与计算。

维护约束：
- 位移量必须按序列帧单格的尺寸缩放，而非整张贴图。`strength` 的常见取值 0.2 若按整张贴图计算，
  一次即跨过一格半。
"""

import math

from ..rng import jitter

#: applicationRule 的位，与 schema/enums.py::BITS_APPLICATION_RULE 同一套
BIT_ENABLE = 0x04
BIT_FREEZE = 0x08

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
    p.rolled[KEY] = (float(speed), float(strength),
                     float(f.get("flowmapSpeedCoef", 1.0) or 1.0),
                     float(f.get("flowmapStrengthCoef", 1.0) or 1.0),
                     bool(rule & BIT_FREEZE))


def _geometric(step, coef, t):
    """返回 Σ step·coef^k（k=0..t-1）；coef==1 时为 step·t。"""
    if abs(coef - 1.0) < 1e-9:
        return step * t
    try:
        return step * (coef ** t - 1.0) / (coef - 1.0)
    except (OverflowError, ValueError):
        return step * t


def apply(p, em, item, key=KEY):
    """将本帧位移量写入 `item.extra[KEY]` 并返回 item；未启用时原样返回。

    `key` 为参数在 p.rolled 里的键，UVCONTROL 的 flowmap 组另存一份。
    """
    got = p.rolled.get(key)
    if item is None or item.kind == "NONE" or not got:
        return item
    speed, strength, s_coef, t_coef, freeze = got
    cfg = em.config
    t = float(p.age)

    fps = float(getattr(cfg, "fps", 60) or 60)
    step = (speed / fps
            if getattr(cfg, "flowmap_speed_unit", "per_second") == "per_second"
            else speed)
    phase = _geometric(step, s_coef, t)
    if freeze and phase > 1.0:
        phase = 1.0             # 播放一次后停止：相位保持在一轮末尾
    if abs(t_coef - 1.0) > 1e-9:
        try:
            strength = strength * (t_coef ** t)
        except (OverflowError, ValueError):
            pass

    if getattr(cfg, "flowmap_phase", "cycle") == "cycle":
        # 取小数部分映射到 −1..1，位移有界，不随寿命无限增长
        phase = (phase - math.floor(phase) - 0.5) * 2.0
    amount = phase * strength
    if amount:
        item.extra[KEY] = amount
    return item
