# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/_flowmap.py  —  flowmap（流动贴图）八件套的共用实现

BILLBOARD3D / PLANE / BILLBOARD2D 各自带着同一组八个字段，不是独立的属性类型，
所以这里是**共用函数**而不是 `@register` 的 behavior（一个 type_hash 只能绑一个
behavior）。渲染体在自己的 `on_particle_spawn` / `build_render` 里各调一次。

字段（全语料 10084 个官方文件里 3181 个用到，占 31.5%）
------------------------------------------------------
    applicationRule     位域；bit 0x04 = 启用，bit 0x08 = 播放一次后冻结
    path                流动贴图的游戏路径。启用时几乎只用 11 张共享图
                        `vfx/dds/cm/cm_flowmap/cm_flow_000..010_F_NM`
    flowmapSpeed(+Jitter)           相位推进速度
    flowmapSpeedCoef(+Jitter)       **逐帧**速度倍率（众数 1.0，其余 0.98/0.99）
    flowmapStrength(+Jitter)        扭曲幅度（众数 0.2，其余 0.1/0.3/0.5/1.0）
    flowmapStrengthCoef(+Jitter)    **逐帧**强度倍率（众数 1.0）

两个 Coef 是「每帧乘一次」的衰减率，与 TRANSFORM3D 的 `_modifier` 同一族；速度本身
的单位则是 `SimConfig.flowmap_speed_unit`（默认每秒，同 t3d/uvs 那两处的结论）。
相位与强度都有闭式解，不必逐帧递推：

    相位     step·t              （Coef == 1）
             step·(c^t − 1)/(c − 1)（等比数列求和）
    强度     strength · c^t

输出 `item.extra["flowmap"]` = 一个标量「位移量」= 相位映射 × 当前强度。真正的
逐纹素位移在 glue 的 shader 里做：按流动贴图的 RG（切线空间法线，`rg×2−1` 即二维
方向）推 UV，位移量再乘上当前序列帧格子的尺寸——`strength` 显然是相对格子而不是
相对整张大图的（0.2 若按整图算会一下跳过一格半）。

未确认（都收成开关，见 SimConfig.UNKNOWNS）
-------------------------------------------
* `flowmap_speed_unit` —— speed 是每秒还是每帧。
* `flowmap_phase` —— 相位怎么映射成位移：`cycle`（取小数部分映到 −1..1，有界，
  不会越拉越烂）还是 `linear`（一路累积）。
* `applicationRule` 的三选一「应用模式」（默认/模式1/模式2）完全未知，未参与。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

import math

from ..rng import jitter

#: applicationRule 的位（见 schema/enums.py::BITS_APPLICATION_RULE）
BIT_ENABLE = 0x04
BIT_FREEZE = 0x08

#: 存进 p.rolled 的键
KEY = "flowmap"


def roll(p, f, rng, mode):
    """出生时抽一次（四个 Jitter）。没启用/没配置就什么都不留。"""
    if f is None:
        return
    rule = int(f.i("applicationRule") or 0)
    if not (rule & BIT_ENABLE):
        return
    speed = jitter(f.get("flowmapSpeed", 0.0), f.get("flowmapSpeedJitter"), rng, mode)
    strength = jitter(f.get("flowmapStrength", 0.0), f.get("flowmapStrengthJitter"),
                      rng, mode)
    if not strength:
        return              # 强度 0 = 不位移，速度再大也没有画面差别
    p.rolled[KEY] = (float(speed), float(strength),
                     float(f.get("flowmapSpeedCoef", 1.0) or 1.0),
                     float(f.get("flowmapStrengthCoef", 1.0) or 1.0),
                     bool(rule & BIT_FREEZE))


def _geometric(step, coef, t):
    """Σ step·coef^k, k=0..t-1。coef==1 时退化成 step·t。"""
    if abs(coef - 1.0) < 1e-9:
        return step * t
    try:
        return step * (coef ** t - 1.0) / (coef - 1.0)
    except (OverflowError, ValueError):
        return step * t


def apply(p, em, item):
    """把这一帧的位移量挂到渲染项上。返回 item（没启用时原样返回）。"""
    got = p.rolled.get(KEY)
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
        phase = 1.0             # 「播放一次后冻结」：相位停在一轮末尾
    if abs(t_coef - 1.0) > 1e-9:
        try:
            strength = strength * (t_coef ** t)
        except (OverflowError, ValueError):
            pass

    if getattr(cfg, "flowmap_phase", "cycle") == "cycle":
        # 取小数部分映到 −1..1：位移有界，不会随寿命越拉越烂
        phase = (phase - math.floor(phase) - 0.5) * 2.0
    amount = phase * strength
    if amount:
        item.extra[KEY] = amount
    return item
