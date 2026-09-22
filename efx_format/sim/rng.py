# -*- coding: utf-8 -*-
"""抖动抽取与确定性噪声。

维护约束：
- 抖动只在 spawn / init 抽，抽完存进 `p.rolled`；`on_particle_step` 的签名里没有
  rng，逐帧重抽在这套 API 下写不出来。
- 逐帧变化的量用 `noise1` / `noise3`，它们是 (seed, frame, channel) 的纯函数，
  重启必然复现。不要在 step 里抽随机数。
- 所有抖动必须经 `jitter()`，分布由 `SimConfig.jitter_mode` 统一切换。
- ⚠ `amount == 0` 时仍然抽一次。这是刻意的：把某个 jitter 从 0 改成非 0 时不会
  连带打乱其他字段已抽到的值。省掉这次抽取会让编辑期的随机流不稳定。
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
    """在 base 上叠加 amount 规模的抖动；rng 由 particle_rng 逐粒子播种。"""
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
    """发射器级种子；randomfix_seeds 来自 RANDOMFIX 的 randomSeedTable0~7。

    ⚠ 只是把这些值混进种子，使「改种子表 → 形态变化」可观察，不复现游戏的取用规则。
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
    """发射器级随机流，供每批重抽的量（批次数量、间隔）使用。

    与逐粒子的流分开，使改粒子数不扰动发射节奏、改节奏不扰动粒子形态。
    """
    return random.Random(_mix64((int(em_seed) ^ 0x5EED_E177_5EED_E177) & _MASK64))


# ─────────────────────────────────────────────────────────────────────────────
# 确定性噪声（给 on_particle_step 用；不是随机数抽取）
# ─────────────────────────────────────────────────────────────────────────────

def noise1(seed, frame, channel=0):
    """(seed, frame, channel) → [-1, 1] 的白噪声。纯函数，逐帧独立。"""
    h = _mix64((int(seed) & _MASK64) ^ _mix64((int(frame) << 16) ^ int(channel)))
    # 取高 53 位得 [0, 1)，再映到 [-1, 1)
    return (h >> 11) / float(1 << 53) * 2.0 - 1.0


def noise3(seed, frame, channel=0):
    """三分量白噪声向量，各分量独立。"""
    return Vec3(noise1(seed, frame, channel * 3 + 0),
                noise1(seed, frame, channel * 3 + 1),
                noise1(seed, frame, channel * 3 + 2))


def noise_smooth1(seed, t, channel=0, period=8.0):
    """时间上连续的值噪声：整数节点间插值，period 帧一个节点。

    需要「飘」而不是「抖」的效果用这个；白噪声逐帧跳变看起来像噪点。
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
