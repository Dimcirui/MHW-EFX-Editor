# -*- coding: utf-8 -*-
"""
efx_format/sim/rng.py  —  抖动抽取 + 确定性噪声

两条规矩，都是结构性的（靠签名而不是靠注释保证）：

1. **抖动只在 spawn/init 抽，抽完存进 `p.rolled`。**
   `speedJitter = 2.0` 是每个粒子出生时定死的常量，不是每帧重抽。
   `Behavior.on_particle_step(self, p, em)` 的签名里**没有 rng**，所以「每帧重抽」
   在这套 API 下写不出来。

2. **逐帧随机用确定性噪声，不用随机数抽取。**
   NOISE/TURBULENCE 之类确实需要逐帧变化的，用 `noise1/noise3`——它们是
   (seed, frame, channel) 的纯函数。这样重启必然复现，核心也能脱离 Blender 单测。
   游戏本身要做到帧可复现，多半也是这个路子。

抖动分布（2026-09 用户确认）
---------------------------
确认的是「在 static 基础上**追加** [0, amount]」，即**单边**，不是 ±。
具体怎么取值（均匀/高斯）未确认，先按均匀。故默认 `JITTER_ONESIDED`，另两种
分布留在 `SimConfig.jitter_mode` 里当开关——标定出真实分布之后改一个默认值，
不动任何 behavior。

⚠ `amount == 0` 时**仍然抽一次**（结果当然等于 base）。故意的：这样把某个 jitter
字段从 0 改成非 0 时，不会连带打乱其他所有字段抽到的值，编辑体验稳定。代价是
随机数流跟游戏对不上——但逐帧对齐游戏本来就不可达（见评估 T5），不值得为它
牺牲编辑期的稳定性。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
"""

import random

from .state import Vec3

# ── 抖动分布 ─────────────────────────────────────────────────────────────────
JITTER_ONESIDED  = "onesided"    # base + U[0, amount]      ← 默认
JITTER_SYMMETRIC = "symmetric"   # base + U[-amount, amount]
JITTER_GAUSSIAN  = "gaussian"    # base + N(0, amount / 2)

JITTER_MODES = (JITTER_ONESIDED, JITTER_SYMMETRIC, JITTER_GAUSSIAN)

JITTER_LABELS = {
    JITTER_ONESIDED:  {"EN": "base + U[0, a]",  "ZH": "基值 + 均匀[0, a]"},
    JITTER_SYMMETRIC: {"EN": "base + U[-a, a]", "ZH": "基值 + 均匀[-a, a]"},
    JITTER_GAUSSIAN:  {"EN": "base + N(0, a/2)", "ZH": "基值 + 高斯(0, a/2)"},
}


def jitter(base, amount, rng, mode=JITTER_ONESIDED):
    """`base` 上叠加 `amount` 规模的抖动。**所有抖动都必须走这里。**

    `rng` 是 `random.Random` 实例（逐粒子播种，见 `particle_rng`）。
    """
    base = float(base)
    amount = float(amount)
    if mode == JITTER_SYMMETRIC:
        return base + rng.uniform(-amount, amount)
    if mode == JITTER_GAUSSIAN:
        return base + rng.gauss(0.0, amount * 0.5)
    # JITTER_ONESIDED（默认）
    return base + rng.uniform(0.0, amount)


def jitter_int(base, amount, rng, mode=JITTER_ONESIDED):
    """整数字段（帧数一类）的抖动：按浮点抽完取整。"""
    return int(round(jitter(base, amount, rng, mode)))


def jitter_vec(base, amount, rng, mode=JITTER_ONESIDED):
    """逐分量抖动。`base`/`amount` 是三元序列。"""
    return Vec3(
        jitter(base[0], amount[0], rng, mode),
        jitter(base[1], amount[1], rng, mode),
        jitter(base[2], amount[2], rng, mode),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 播种
# ─────────────────────────────────────────────────────────────────────────────

_MASK64 = (1 << 64) - 1


def _mix64(x):
    """splitmix64 的 finalizer：整数 → 雪崩良好的 64 位整数。"""
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def emitter_seed(base_seed, randomfix_seeds=()):
    """发射器级种子。`randomfix_seeds` 来自 RANDOMFIX 的 randomSeedTable0~7。

    ⚠ RANDOMFIX 的表怎么被游戏取用（`useRandomSeedTableCount` /
    `tableSelectionGroup` 的确切语义）只有统计推断，没有实测。这里只是把它们
    混进种子保证「改种子表 → 形态变化」这个可观察行为，不假装复现游戏的取用规则。
    """
    h = _mix64(int(base_seed) & _MASK64)
    for s in randomfix_seeds:
        h = _mix64(h ^ (int(s) & 0xFFFFFFFF))
    return h


def particle_seed(em_seed, particle_index):
    """逐粒子种子：同一发射器内按序号派生，重启后必然复现。"""
    return _mix64((int(em_seed) ^ (int(particle_index) * 0x2545F4914F6CDD1D)) & _MASK64)


def particle_rng(em_seed, particle_index):
    """给 `on_particle_spawn` 用的 rng。"""
    return random.Random(particle_seed(em_seed, particle_index))


def emitter_stream_rng(em_seed):
    """发射器级的随机流（批次数量/间隔这类**每批**重抽的量）。

    刻意和逐粒子的流分开：改粒子数不会扰动发射节奏，改节奏也不会扰动粒子形态，
    调参时观感稳定。reset 后从同一种子重建，所以照样确定性。
    """
    return random.Random(_mix64((int(em_seed) ^ 0x5EED_E177_5EED_E177) & _MASK64))


# ─────────────────────────────────────────────────────────────────────────────
# 确定性噪声（给 on_particle_step 用；不是随机数抽取）
# ─────────────────────────────────────────────────────────────────────────────

def noise1(seed, frame, channel=0):
    """(seed, frame, channel) → [-1, 1] 的白噪声。纯函数，逐帧独立。"""
    h = _mix64((int(seed) & _MASK64) ^ _mix64((int(frame) << 16) ^ int(channel)))
    # h >> 11 取高 53 位 → [0, 2^53)，除以 2^53 得 [0, 1)，再映到 [-1, 1)
    return (h >> 11) / float(1 << 53) * 2.0 - 1.0


def noise3(seed, frame, channel=0):
    """三分量白噪声向量，各分量独立。"""
    return Vec3(noise1(seed, frame, channel * 3 + 0),
                noise1(seed, frame, channel * 3 + 1),
                noise1(seed, frame, channel * 3 + 2))


def noise_smooth1(seed, t, channel=0, period=8.0):
    """时间上连续的值噪声：整数节点间线性插值，`period` 帧一个节点。

    TURBULENCE 这类需要「飘」而不是「抖」的效果用这个；白噪声逐帧跳变会像噪点。
    """
    if period <= 0.0:
        return noise1(seed, int(t), channel)
    u = float(t) / float(period)
    i = int(u // 1.0)
    f = u - i
    a = noise1(seed, i, channel)
    b = noise1(seed, i + 1, channel)
    f = f * f * (3.0 - 2.0 * f)     # smoothstep，避免线性插值的折角
    return a + (b - a) * f


def noise_smooth3(seed, t, channel=0, period=8.0):
    return Vec3(noise_smooth1(seed, t, channel * 3 + 0, period),
                noise_smooth1(seed, t, channel * 3 + 1, period),
                noise_smooth1(seed, t, channel * 3 + 2, period))
