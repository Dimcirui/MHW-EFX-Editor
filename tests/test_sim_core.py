# -*- coding: utf-8 -*-
"""
tests/test_sim_core.py  —  efx_format/sim 的单元测试（零 bpy，脱离 Blender 跑）

    python3 -m unittest discover -s tests -v
    python3 tests/test_sim_core.py

这些测试存在的理由不只是防回归：模拟核心里每一条「实测得来的语义」都应该在这里
有一条对应的断言，这样等以后标定出新结论、改了 SimConfig 的默认值，能立刻看出
哪些结论被推翻了。
"""

import base64
import json
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from efx_format.hashes import (BILLBOARD3D, EMITTERSHAPE3D, LIFE,  # noqa: E402
                               NOISE, ROTATEANIM, SCALEANIM, SPAWN,
                               TRANSFORM3D, VELOCITY3D)
from efx_format.sim import (FORCE, Behavior, SimConfig, Simulator,  # noqa: E402
                            Vec3, from_attr_blocks, register)
from efx_format.sim import rng as simrng  # noqa: E402
from efx_format.sim.vecmath import rotate_euler  # noqa: E402

ARCHETYPE_DIR = os.path.join(_ROOT, "presets", "__archetypes__")


# ─────────────────────────────────────────────────────────────────────────────
# 构造辅助
# ─────────────────────────────────────────────────────────────────────────────

def spawn_fields(**kw):
    f = {
        "maxParticles": 0, "particlesPerBurst": 1, "particlesPerBurstJitter": 0,
        "burstInterval": 10, "burstIntervalJitter": 0,
        "burstsPerCycle": 0, "burstsPerCycleJitter": 0,
        "emitterStartDelay": 0, "emitterStartDelayJitter": 0,
        "particleSpawnDelay": 0, "particleSpawnDelayJitter": 0,
        "emitterRepeatCount": 0,
        "altBurstInterval": 0, "altBurstIntervalJitter": 0,
    }
    f.update(kw)
    return f


def life_fields(**kw):
    f = {
        "fadeInDuration": 0, "fadeInDurationJitter": 0,
        "duration": 10, "durationJitter": 0,
        "fadeOutDuration": 0, "fadeOutDurationJitter": 0,
        "timeToDeath": 0, "timeToDeathJitter": 0,
        "indefiniteLifespan": 0,
    }
    f.update(kw)
    return f


def velocity_fields(**kw):
    f = {
        "baseAxis": 1, "rotOrder": 4,
        "rotationX": 0.0, "rotationXJitter": 0.0,
        "rotationY": 0.0, "rotationYJitter": 0.0,
        "rotationZ": 0.0, "rotationZJitter": 0.0,
        "speed": 1.0, "speedJitter": 0.0,
        "speedCoef": 1.0, "speedCoefJitter": 0.0,
        "velocityX": 0.0, "velocityY": 0.0, "velocityZ": 0.0,
        "divergenceX": 1.0, "divergenceY": 1.0, "divergenceZ": 1.0,
        "velocityType": 0,
        "gravity": 0.0, "gravity_jitter": 0.0,
        "movementDelay": 0, "movementDelayJitter": 0,
        "gravityDelay": 0, "gravityDelayJitter": 0,
        "minMovementThreshold": 0.0,
    }
    f.update(kw)
    return f


def es3d_fields(**kw):
    f = {
        "rangeXYZ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "shapeType": 0, "rangeDivideAxis": 0, "rotationCorrect": 0,
        "localRotationX": 0.0, "localRotationY": 0.0, "localRotationZ": 0.0,
        "rotationOrder": 4,
        "scanAngleHorizontal": 360.0, "scanAngleVertical": 0.0,
        "rangeDivideHorizontalNum": 0, "rangeDivideVerticalNum": 0,
        "radiusEnd": 1.0, "radiusOrigin": 1.0,
    }
    f.update(kw)
    return f


def scaleanim_fields(**kw):
    f = {"typeFlag": 8,
         "initialScaleSpeed": 0.0, "initialScaleSpeedJitter": 0.0,
         "initialScaleAccel": 1.0, "initialScaleAccelJitter": 0.0,
         "animUpdateStart": 0, "animUpdateStartJitter": 0}
    for ax in ("X", "Y", "Z"):
        f["scaleSpeed" + ax] = 0.0
        f["scaleSpeed" + ax + "Jitter"] = 0.0
        f["scaleAccel" + ax] = 1.0
        f["scaleAccel" + ax + "Jitter"] = 0.0
    f.update(kw)
    return f


def rotateanim_fields(**kw):
    f = {"spinAxisMask": 0x7, "rotationModeMask": 0,
         "billboardRotation": 0.0, "billboardRotationJitter": 0.0,
         "billboardRotationCoef": 1.0, "billboardRotationCoefJitter": 0.0,
         "spin_velocity": [0.0] * 6,
         "rotateDelayStart": 0, "rotateDelayStartJitter": 0}
    for ax in ("X", "Y", "Z"):
        f["spinSpeedCoef" + ax] = 1.0
        f["spinSpeedCoef" + ax + "Jitter"] = 0.0
    f.update(kw)
    return f


def transform3d_fields(**kw):
    z6 = [0.0] * 6
    one6 = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    f = {"typeFlag": 0, "rotationOrder": 4, "enableVelocityBitflag": 0,
         "translate": list(z6), "rotate": list(z6), "resize": list(one6),
         "translation_velocity": list(z6), "translation_velocity_modifier": list(one6),
         "rotation_velocity": list(z6), "rotation_velocity_modifier": list(one6),
         "scale_velocity": list(z6), "scale_velocity_modifier": list(one6)}
    f.update(kw)
    return f


def billboard_fields(**kw):
    f = {"typeFlag": 0, "applicationRule": 0,
         "color": [255, 255, 255, 255], "colorRange": [255, 255, 255, 255],
         "useColorRange": 0, "blendMode": 0,
         "brightness": 1.0, "brightnessJitter": 0.0,
         "EPVColorSlot1": 0, "SlotOverride1": 0,
         "rotation": 0.0, "rotationJitter": 0.0,
         "scale": 1.0, "scaleJitter": 0.0,
         "width": 100.0, "widthJitter": 0.0,
         "height": 100.0, "heightJitter": 0.0}
    f.update(kw)
    return f


def make_sim(spawn=None, life=None, velocity=None, es3d=None, config=None, extra=(),
             transform=None, scaleanim=None, rotateanim=None, billboard=None):
    blocks = []
    if transform is not None:
        blocks.append((TRANSFORM3D, transform))
    if spawn is not None:
        blocks.append((SPAWN, spawn))
    if life is not None:
        blocks.append((LIFE, life))
    if es3d is not None:
        blocks.append((EMITTERSHAPE3D, es3d))
    if velocity is not None:
        blocks.append((VELOCITY3D, velocity))
    if scaleanim is not None:
        blocks.append((SCALEANIM, scaleanim))
    if rotateanim is not None:
        blocks.append((ROTATEANIM, rotateanim))
    if billboard is not None:
        blocks.append((BILLBOARD3D, billboard))
    blocks.extend(extra)
    return Simulator(blocks, b"", config or SimConfig())


def one_particle(frames=1, **kw):
    """生一个粒子、跑 `frames` 帧，返回它。"""
    kw.setdefault("spawn", spawn_fields(burstInterval=1000))
    kw.setdefault("life", life_fields(indefiniteLifespan=1))
    sim = make_sim(**kw)
    for _ in range(frames):
        sim.step()
    return sim.particles[0], sim


# ─────────────────────────────────────────────────────────────────────────────
# Vec3 / 数学
# ─────────────────────────────────────────────────────────────────────────────

class TestVec3(unittest.TestCase):

    def test_arithmetic(self):
        a = Vec3(1, 2, 3)
        b = Vec3(4, 5, 6)
        self.assertEqual(a + b, Vec3(5, 7, 9))
        self.assertEqual(b - a, Vec3(3, 3, 3))
        self.assertEqual(a * 2, Vec3(2, 4, 6))
        self.assertEqual(a * Vec3(2, 0, 1), Vec3(2, 0, 3))
        self.assertAlmostEqual(Vec3(3, 4, 0).length(), 5.0)

    def test_inplace_does_not_alias(self):
        a = Vec3(1, 1, 1)
        b = a.copy()
        a += Vec3(1, 0, 0)
        self.assertEqual(b, Vec3(1, 1, 1))

    def test_normalize_zero_is_safe(self):
        self.assertEqual(Vec3().normalized(), Vec3())
        self.assertEqual(Vec3().normalized(fallback=Vec3(0, 1, 0)), Vec3(0, 1, 0))

    def test_rotate_euler_90_about_z(self):
        v = rotate_euler(Vec3(1, 0, 0), 0, 0, 90, order="XYZ")
        self.assertAlmostEqual(v.x, 0.0, places=6)
        self.assertAlmostEqual(v.y, 1.0, places=6)

    def test_rotate_order_matters(self):
        a = rotate_euler(Vec3(1, 0, 0), 90, 90, 0, order="XYZ")
        b = rotate_euler(Vec3(1, 0, 0), 90, 90, 0, order="YXZ")
        self.assertNotAlmostEqual((a - b).length(), 0.0, places=3)


# ─────────────────────────────────────────────────────────────────────────────
# 抖动与噪声
# ─────────────────────────────────────────────────────────────────────────────

class TestRng(unittest.TestCase):

    def test_onesided_is_the_documented_default(self):
        """用户 2026-09 确认：在 static 基础上**追加** [0, amount]，单边不是 ±。"""
        r = simrng.particle_rng(123, 0)
        vals = [simrng.jitter(5.0, 2.0, r) for _ in range(500)]
        self.assertGreaterEqual(min(vals), 5.0)
        self.assertLessEqual(max(vals), 7.0)

    def test_symmetric_mode(self):
        r = simrng.particle_rng(123, 0)
        vals = [simrng.jitter(5.0, 2.0, r, simrng.JITTER_SYMMETRIC) for _ in range(500)]
        self.assertLess(min(vals), 5.0)
        self.assertGreater(max(vals), 5.0)
        self.assertGreaterEqual(min(vals), 3.0)
        self.assertLessEqual(max(vals), 7.0)

    def test_zero_amount_still_draws(self):
        """amount=0 仍然消耗一次抽取——这样改某个 jitter 字段不会打乱其他字段。"""
        r1 = simrng.particle_rng(7, 0)
        simrng.jitter(1.0, 0.0, r1)
        after_draw = simrng.jitter(0.0, 1.0, r1)

        r2 = simrng.particle_rng(7, 0)
        r2.uniform(0.0, 0.0)
        self.assertAlmostEqual(after_draw, simrng.jitter(0.0, 1.0, r2))

    def test_particle_rng_is_reproducible(self):
        a = [simrng.particle_rng(99, i).random() for i in range(20)]
        b = [simrng.particle_rng(99, i).random() for i in range(20)]
        self.assertEqual(a, b)
        self.assertEqual(len(set(a)), 20)     # 不同粒子拿到不同的流

    def test_noise_is_pure_and_bounded(self):
        for frame in range(50):
            v = simrng.noise1(42, frame, 0)
            self.assertGreaterEqual(v, -1.0)
            self.assertLessEqual(v, 1.0)
            self.assertEqual(v, simrng.noise1(42, frame, 0))

    def test_smooth_noise_is_continuous(self):
        prev = simrng.noise_smooth1(5, 0.0, 0, period=8.0)
        for i in range(1, 200):
            cur = simrng.noise_smooth1(5, i * 0.25, 0, period=8.0)
            self.assertLess(abs(cur - prev), 0.75)   # 相邻采样不会跳变
            prev = cur


# ─────────────────────────────────────────────────────────────────────────────
# SPAWN
# ─────────────────────────────────────────────────────────────────────────────

class TestSpawn(unittest.TestCase):

    def _birth_frames(self, sim, frames):
        seen = {}
        for _ in range(frames):
            sim.step()
            for p in sim.particles:
                seen.setdefault(p.index, p.birth_frame)
        return sorted(seen.values())

    def test_interval_is_exact(self):
        """burstInterval=10 → 第 0/10/20… 帧各发一批，不是 11 帧一次。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=10, particlesPerBurst=1),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 31), [0, 10, 20, 30])

    def test_interval_zero_emits_every_frame(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=0, particlesPerBurst=1),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 5), [0, 1, 2, 3, 4])

    def test_emitter_start_delay(self):
        sim = make_sim(spawn=spawn_fields(emitterStartDelay=7, burstInterval=100),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 20), [7])

    def test_particles_per_burst(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=4, burstInterval=100),
                       life=life_fields(indefiniteLifespan=1))
        sim.step()
        self.assertEqual(len(sim.particles), 4)

    def test_max_particles_is_a_concurrent_cap(self):
        """maxParticles 是同时存活上限，不是终身总量：死一个补一个。

        ⚠ 不断言「每帧都满编」：step() 是先生成后收割，本帧要死的粒子在做生成决策
        时还占着名额，所以满编+同龄时会有一帧空窗（见 simulator.py 的取舍说明）。
        """
        sim = make_sim(
            spawn=spawn_fields(particlesPerBurst=5, burstInterval=0, maxParticles=3),
            life=life_fields(duration=4))
        counts = []
        for _ in range(40):
            sim.step()
            counts.append(len(sim.particles))
            self.assertLessEqual(counts[-1], 3)
        self.assertEqual(max(counts), 3)
        self.assertGreater(sim.em.spawned_total, 3)   # 确实一直在补

    def test_bursts_per_cycle_one_uses_alt_interval(self):
        """三态之二：burstsPerCycle 抽到 1 时改用 altBurstInterval 作节奏。"""
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=1, emitterRepeatCount=3,
                               burstInterval=100, altBurstInterval=5),
            life=life_fields(indefiniteLifespan=1))
        frames = self._birth_frames(sim, 12)
        self.assertEqual(frames[:3], [0, 5, 10])

    def test_repeat_count_zero_never_stops(self):
        """emitterRepeatCount=0 → 永不换位置、无限生成（三态之一）。"""
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=2, emitterRepeatCount=0, burstInterval=3),
            life=life_fields(indefiniteLifespan=1))
        frames = self._birth_frames(sim, 30)
        self.assertGreaterEqual(len(frames), 9)

    def test_bursts_per_cycle_then_life_paced_gap(self):
        """非 0 时每轮批次数 = burstsPerCycle + emitterRepeatCount - 1，
        最后一批之后按粒子寿命等一段再换位置开下一轮。

        3 + 1 - 1 = 3 批、间隔 2 帧 → 0/2/4；寿命 10 → 下一轮从 14 起。
        发射器不会停（三态里没有停止条件），所以这里断言的是**节奏**不是总数。
        """
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=3, emitterRepeatCount=1, burstInterval=2),
            life=life_fields(duration=10, indefiniteLifespan=1))
        frames = self._birth_frames(sim, 30)
        self.assertEqual(frames[:6], [0, 2, 4, 14, 16, 18])
        self.assertGreaterEqual(sim.em.cycle, 2)

    def test_emitter_never_stops_so_duration_is_the_players_job(self):
        """没有任何一态会停 → 「播放一次」的长度得播放器自己定。"""
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=2, emitterRepeatCount=2, burstInterval=3),
            life=life_fields(duration=5))
        sim.run(500)
        self.assertGreater(sim.em.spawned_total, 50)
        self.assertGreater(sim.suggested_duration(), 0)

    def test_particle_spawn_delay_holds_the_particle(self):
        sim = make_sim(
            spawn=spawn_fields(particleSpawnDelay=5, burstInterval=100),
            life=life_fields(indefiniteLifespan=1),
            velocity=velocity_fields(speed=10.0))
        sim.step()
        p = sim.particles[0]
        self.assertFalse(p.active)
        self.assertEqual(sim.build_render(), [])   # 延迟期间不渲染
        for _ in range(5):
            sim.step()
        self.assertTrue(sim.particles[0].active)


# ─────────────────────────────────────────────────────────────────────────────
# LIFE
# ─────────────────────────────────────────────────────────────────────────────

class TestLife(unittest.TestCase):

    def test_duration_is_exact_frame_count(self):
        """duration=10 → 恰好被渲染 10 帧。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=1000), life=life_fields(duration=10))
        rendered = 0
        for _ in range(30):
            sim.step()
            rendered += len(sim.build_render())
        self.assertEqual(rendered, 10)

    def test_indefinite_never_dies(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(duration=3, indefiniteLifespan=1))
        for _ in range(200):
            sim.step()
        self.assertEqual(len(sim.particles), 1)

    def test_fade_in_ramps_alpha(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(fadeInDuration=4, duration=10))
        alphas = []
        for _ in range(6):
            sim.step()
            if sim.particles:
                alphas.append(round(sim.particles[0].alpha, 3))
        self.assertEqual(alphas[:5], [0.0, 0.25, 0.5, 0.75, 1.0])

    def test_fade_out_ramps_down(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(duration=4, fadeOutDuration=4))
        alphas = []
        for _ in range(9):
            sim.step()
            if sim.particles:
                alphas.append(round(sim.particles[0].alpha, 3))
        self.assertEqual(alphas[-4:], [1.0, 0.75, 0.5, 0.25])

    def test_life_model_switch_changes_total(self):
        """SimConfig.life_model 是待标定开关，两种算法给出不同总长。"""
        f = life_fields(fadeInDuration=5, duration=10, fadeOutDuration=5)
        a = make_sim(spawn=spawn_fields(burstInterval=1000), life=f,
                     config=SimConfig(life_model="sum"))
        b = make_sim(spawn=spawn_fields(burstInterval=1000), life=f,
                     config=SimConfig(life_model="duration"))
        a.step()
        b.step()
        self.assertEqual(a.particles[0].life, 20)
        self.assertEqual(b.particles[0].life, 10)


# ─────────────────────────────────────────────────────────────────────────────
# EMITTERSHAPE3D
# ─────────────────────────────────────────────────────────────────────────────

class TestEmitterShape3D(unittest.TestCase):

    def _spawn_many(self, es3d, n=300, config=None):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=n, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       es3d=es3d, config=config)
        sim.step()
        return [p.spawn_pos for p in sim.particles]

    def test_box_spans_min_to_max(self):
        """rangeXYZ = Min/Max 交错（官方通道名 RangeMinX/RangeMaxX/…）：
        [0,100, 0,0, 0,20] → X∈[0,100]、Y∈[0,0]、Z∈[0,20]。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[0.0, 100.0, 0.0, 0.0, 0.0, 20.0]))
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        zs = [p.z for p in pts]
        self.assertGreaterEqual(min(xs), -1e-9)
        self.assertLessEqual(max(xs), 100.0 + 1e-9)
        self.assertGreater(max(xs), 80.0)               # 确实铺满
        self.assertLess(min(xs), 20.0)
        self.assertEqual(max(abs(v) for v in ys), 0.0)  # Min=Max=0 → 扁平
        self.assertLessEqual(max(zs), 20.0 + 1e-9)

    def test_box_negative_min_spans_both_sides(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[-10.0, 10.0, 0.0, 0.0, 0.0, 0.0]))
        self.assertLess(min(p.x for p in pts), -5.0)
        self.assertGreater(max(p.x for p in pts), 5.0)
        for p in pts:
            self.assertGreaterEqual(p.x, -10.0 - 1e-9)
            self.assertLessEqual(p.x, 10.0 + 1e-9)

    def test_range_mode_switch_changes_reading(self):
        """es3d_range_mode 是待标定开关：同一组字节，两种读法给出不同区间。"""
        fields = es3d_fields(shapeType=0, rangeXYZ=[4.0, 10.0, 0.0, 0.0, 0.0, 0.0])
        mm = self._spawn_many(fields, config=SimConfig(es3d_range_mode="minmax"))
        os_ = self._spawn_many(fields, config=SimConfig(es3d_range_mode="offset_size"))
        self.assertGreaterEqual(min(p.x for p in mm), 4.0 - 1e-9)    # [4, 10]
        self.assertLessEqual(max(p.x for p in mm), 10.0 + 1e-9)
        self.assertLess(min(p.x for p in os_), 4.0)                  # 4 ± 5
        self.assertGreater(max(p.x for p in os_), 6.0)

    def test_sphere_lands_on_the_shell(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=1, rangeXYZ=[-10.0, 10.0, -10.0, 10.0, -10.0, 10.0],
            radiusOrigin=1.0, radiusEnd=1.0))
        for p in pts:
            self.assertAlmostEqual(p.length(), 10.0, places=4)

    def test_sphere_radius_range_fills_a_shell(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=1, rangeXYZ=[-10.0, 10.0, -10.0, 10.0, -10.0, 10.0],
            radiusOrigin=0.5, radiusEnd=1.0))
        radii = [p.length() for p in pts]
        self.assertGreaterEqual(min(radii), 4.99)
        self.assertLessEqual(max(radii), 10.01)
        self.assertGreater(max(radii) - min(radii), 2.0)

    def test_scan_angle_restricts_the_sweep(self):
        """scanAngleHorizontal=90 → 只覆盖四分之一圈。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[-10.0, 10.0, 0.0, 0.0, -10.0, 10.0],
            scanAngleHorizontal=90.0))
        for p in pts:
            ang = math.degrees(math.atan2(p.z, p.x)) % 360.0
            self.assertLessEqual(ang, 91.0)

    def test_range_divide_quantizes(self):
        """rangeDivideHorizontalNum 是**等分数量**：4 → 只出现 4 个离散方位。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[-10.0, 10.0, 0.0, 0.0, -10.0, 10.0],
            rangeDivideHorizontalNum=4))
        angles = {round(math.degrees(math.atan2(p.z, p.x)) % 360.0, 3) for p in pts}
        self.assertEqual(len(angles), 4)

    def test_point_shape_is_a_single_spot(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=3, rangeXYZ=[0.0, 2.0, 1.0, 3.0, 2.0, 4.0]))
        for p in pts:
            self.assertEqual(p, Vec3(1, 2, 3))

    def test_local_rotation_is_applied(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[-10.0, 10.0, 0.0, 0.0, 0.0, 0.0],
            localRotationZ=90.0), n=50)
        self.assertLess(max(abs(p.x) for p in pts), 1e-6)   # X 轴的盒子被转到 Y 上
        self.assertGreater(max(abs(p.y) for p in pts), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# VELOCITY3D
# ─────────────────────────────────────────────────────────────────────────────

class TestVelocity3D(unittest.TestCase):

    def _one(self, velocity, frames=1, config=None, es3d=None):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       es3d=es3d, velocity=velocity, config=config)
        for _ in range(frames):
            sim.step()
        return sim.particles[0]

    def test_base_axis_up(self):
        p = self._one(velocity_fields(baseAxis=1, speed=3.0))
        self.assertEqual(p.pos, Vec3(0, 3, 0))

    def test_base_axis_down(self):
        p = self._one(velocity_fields(baseAxis=4, speed=3.0))
        self.assertEqual(p.pos, Vec3(0, -3, 0))

    def test_speed_coef_is_per_frame_multiplier(self):
        """annotations：「对应的速度每帧乘一次这个值」。10 帧后速度 = 1 * 0.95^10。"""
        p = self._one(velocity_fields(speed=1.0, speedCoef=0.95), frames=10)
        self.assertAlmostEqual(p.vel.y, 0.95 ** 10, places=9)

    def test_speed_coef_one_is_constant_speed(self):
        p = self._one(velocity_fields(speed=2.0, speedCoef=1.0), frames=7)
        self.assertAlmostEqual(p.pos.y, 14.0, places=6)

    def test_gravity_pulls_down_regardless_of_type(self):
        """annotations：「不论 Velocity Type 如何，始终生效」。"""
        for vt in (0, 1, 2, 3):
            p = self._one(velocity_fields(speed=0.0, gravity=1.0, velocityType=vt),
                          frames=3)
            self.assertLess(p.pos.y, 0.0, "velocityType=%d 时重力失效" % vt)

    def test_gravity_delay(self):
        p = self._one(velocity_fields(speed=0.0, gravity=1.0, gravityDelay=5), frames=5)
        self.assertEqual(p.pos.y, 0.0)
        p = self._one(velocity_fields(speed=0.0, gravity=1.0, gravityDelay=5), frames=7)
        self.assertLess(p.pos.y, 0.0)

    def test_movement_delay_freezes_position_not_velocity(self):
        p = self._one(velocity_fields(speed=1.0, speedCoef=0.5, movementDelay=3),
                      frames=3)
        self.assertEqual(p.pos, Vec3())
        self.assertAlmostEqual(p.vel.y, 0.5 ** 3, places=9)

    def test_radial_moves_outward(self):
        es3d = es3d_fields(shapeType=1, rangeXYZ=[-10, 10, -10, 10, -10, 10])
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=50, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1), es3d=es3d,
                       velocity=velocity_fields(velocityType=2, speed=1.0))
        sim.step()
        for p in sim.particles:
            self.assertGreater(p.pos.length(), p.spawn_pos.length())

    def test_directional_spread_uses_the_documented_formula(self):
        """Vi = (divergence - 1) * 生成坐标 + velocity，归一化。"""
        es3d = es3d_fields(shapeType=3, rangeXYZ=[3.0, 3.0, 0.0, 0.0, 4.0, 4.0])
        p = self._one(velocity_fields(velocityType=1, speed=5.0,
                                      divergenceX=2.0, divergenceY=1.0, divergenceZ=2.0),
                      es3d=es3d)
        expect = Vec3(3.0, 0.0, 4.0).normalized() * 5.0
        self.assertAlmostEqual(p.vel.x, expect.x, places=6)
        self.assertAlmostEqual(p.vel.z, expect.z, places=6)

    def test_unknown_velocity_type_is_reported(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(velocityType=5))
        sim.step()
        self.assertTrue(any("velocityType=5" in n for n in sim.notes))

    def test_rotation_jitter_spreads_directions(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=100, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0, rotationX=30.0,
                                                rotationXJitter=10.0))
        sim.step()
        ys = [p.vel.y for p in sim.particles]
        self.assertGreater(max(ys) - min(ys), 1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# 注册表 / 阶段契约
# ─────────────────────────────────────────────────────────────────────────────

class _StageViolator(Behavior):
    """故意越界：声明在 FORCE（只许写 vel），却去写 pos。"""
    STAGE = FORCE

    def on_particle_step(self, p, em):
        p.pos.x += 1.0


class TestRegistryAndStages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        register(NOISE)(_StageViolator)

    def test_unknown_attribute_is_reported_not_crashed(self):
        fake_hash = 0x7FFFFFF1
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(fake_hash, {})])
        sim.step()
        self.assertEqual(len(sim.particles), 1)
        self.assertIn(fake_hash, [h for h, _ in sim.unsupported])
        self.assertTrue(any("未模拟属性" in n for n in sim.notes))

    def test_disabled_attribute_is_skipped(self):
        cfg = SimConfig(disabled={VELOCITY3D})
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=99.0), config=cfg)
        sim.step()
        self.assertEqual(sim.particles[0].pos, Vec3())

    def test_stage_order_is_data(self):
        """VELOCITY3D 默认在 INTEGRATE，可被 order_override 挪走。"""
        cfg = SimConfig(order_override={VELOCITY3D: (FORCE, 5)})
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0), config=cfg)
        bound = [b for b in sim.bound if b.type_hash == VELOCITY3D][0]
        self.assertEqual((bound.stage, bound.order), (FORCE, 5))

    def test_strict_mode_catches_stage_violation(self):
        cfg = SimConfig(strict=True)
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(NOISE, {})], config=cfg)
        with self.assertRaises(AssertionError) as ctx:
            for _ in range(3):
                sim.step()
        self.assertIn("FORCE", str(ctx.exception))

    def test_non_strict_mode_lets_it_through(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(NOISE, {})], config=SimConfig(strict=False))
        for _ in range(3):
            sim.step()
        self.assertGreater(sim.particles[0].pos.x, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 确定性 / 渲染 pass
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminismAndRender(unittest.TestCase):

    def _trace(self, seed):
        sim = make_sim(
            spawn=spawn_fields(particlesPerBurst=3, burstInterval=2,
                               particlesPerBurstJitter=2),
            life=life_fields(duration=8, durationJitter=4),
            es3d=es3d_fields(shapeType=1, rangeXYZ=[-5, 5, -5, 5, -5, 5]),
            velocity=velocity_fields(speed=1.0, speedJitter=2.0, speedCoef=0.9),
            config=SimConfig(seed=seed))
        out = []
        for _ in range(40):
            sim.step()
            out.append([(p.index, p.pos.as_tuple()) for p in sim.particles])
        return out

    def test_same_seed_same_result(self):
        self.assertEqual(self._trace(7), self._trace(7))

    def test_different_seed_different_result(self):
        self.assertNotEqual(self._trace(7), self._trace(8))

    def test_reset_replays_identically(self):
        sim = make_sim(
            spawn=spawn_fields(particlesPerBurst=2, burstInterval=3),
            life=life_fields(duration=6),
            es3d=es3d_fields(shapeType=1, rangeXYZ=[-5, 5, -5, 5, -5, 5]),
            velocity=velocity_fields(speed=1.0, speedJitter=1.0))
        first = [p.pos.as_tuple() for p in sim.run(20).particles]
        sim.reset()
        second = [p.pos.as_tuple() for p in sim.run(20).particles]
        self.assertEqual(first, second)

    def test_run_to_rewinds(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0))
        sim.run_to(10)
        forward = sim.particles[0].pos.as_tuple()
        sim.run_to(30)
        sim.run_to(10)                       # 倒退 → 自动 reset 重放
        self.assertEqual(sim.particles[0].pos.as_tuple(), forward)

    def test_build_render_is_side_effect_free(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=5, burstInterval=1000),
                       life=life_fields(duration=20),
                       velocity=velocity_fields(speed=1.0))
        sim.run(3)
        before = [p.pos.as_tuple() for p in sim.particles]
        a = sim.build_render()
        b = sim.build_render()
        after = [p.pos.as_tuple() for p in sim.particles]
        self.assertEqual(before, after)
        self.assertEqual(len(a), len(b), 5)
        self.assertEqual([i.pos.as_tuple() for i in a], [i.pos.as_tuple() for i in b])

    def test_render_carries_alpha_from_life(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(fadeInDuration=4, duration=10),
                       velocity=velocity_fields(speed=0.0))
        sim.run(3)
        self.assertAlmostEqual(sim.build_render()[0].color[3], 0.5, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 端到端：仓库自带的 archetype
# ─────────────────────────────────────────────────────────────────────────────

def _load_archetype(name):
    path = os.path.join(ARCHETYPE_DIR, name)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    from efx_format.efxfile import AttrBlock
    blocks = [AttrBlock(int(a["type_hash"]), base64.b64decode(a["data_bytes"]))
              for a in data.get("attributes", [])]
    timl = data.get("timl_bytes") or b""
    if isinstance(timl, str):
        timl = base64.b64decode(timl)
    return blocks, timl


class TestArchetypeEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(ARCHETYPE_DIR):
            raise unittest.SkipTest("没有 presets/__archetypes__")

    def test_floating_particle_fire(self):
        """SPAWN: maxParticles=2 / perBurst=1 / interval=50，LIFE: duration=60。

        存活上限 2、每 50 帧生 1 个、活 60 帧 —— 稳态同时存活应该在 1~2 之间
        （Little's Law：生成速率 1/50 × 寿命 60 = 1.2）。
        """
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl, SimConfig(seed=3))

        counts = []
        for _ in range(300):
            sim.step()
            counts.append(len(sim.particles))

        self.assertGreater(max(counts), 0)
        self.assertLessEqual(max(counts), 2)          # maxParticles=2
        self.assertGreaterEqual(sim.em.spawned_total, 5)

    def test_fire_speed_decays(self):
        """VELOCITY3D.speedCoef=0.95 → 速度单调衰减。"""
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl, SimConfig(seed=3))
        sim.step()
        p = sim.particles[0]
        speeds = [p.vel.length()]
        for _ in range(20):
            sim.step()
            if p not in sim.particles:
                break
            speeds.append(p.vel.length())
        self.assertGreater(len(speeds), 5)
        for a, b in zip(speeds, speeds[1:]):
            self.assertLessEqual(b, a + 1e-9)

    def test_every_archetype_runs_without_crashing(self):
        """所有 archetype 都能跑 120 帧不炸——未实现的属性走兜底，不是异常。"""
        for name in sorted(os.listdir(ARCHETYPE_DIR)):
            if not name.endswith(".json"):
                continue
            with self.subTest(archetype=name):
                blocks, timl = _load_archetype(name)
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=1))
                for _ in range(120):
                    sim.step()
                sim.build_render()

    def test_unsupported_list_is_populated(self):
        """ribbon_particle 有 RIBBON 之类还没实现的属性 → 应该被如实列出。"""
        blocks, timl = _load_archetype("ribbon_particle.json")
        sim = from_attr_blocks(blocks, timl)
        self.assertTrue(sim.unsupported)
        for h, name in sim.unsupported:
            self.assertIsInstance(h, int)


# ─────────────────────────────────────────────────────────────────────────────
# 字段解析 / TIML
# ─────────────────────────────────────────────────────────────────────────────

class TestFieldResolution(unittest.TestCase):

    def _resolver(self, block="VELOCITY3D", raw=None, tracks=None, config=None):
        from efx_format.sim.resolve import FieldResolver
        return FieldResolver(block, raw if raw is not None else velocity_fields(),
                             tracks, config or SimConfig())

    def _tracks_with(self, block, field, axis, keys, comp=0):
        from efx_format.sim.resolve import Curve, TimlTracks
        from efx_format.timl.names import BLOCK_TO_TLP, FIELD_TO_DT
        tracks = TimlTracks()
        tlp = BLOCK_TO_TLP[block]
        dt = FIELD_TO_DT[(block, field)][comp][0]
        tracks._curves[(axis, tlp, dt)] = Curve(keys)
        tracks.ok = True
        return tracks

    def test_missing_field_raises_not_returns_zero(self):
        """拼错字段名必须炸，不能静默给 0。"""
        from efx_format.sim.resolve import FieldView
        view = FieldView(self._resolver(), 0, 0)
        self.assertAlmostEqual(view.speed, 1.0)
        with self.assertRaises(AttributeError):
            _ = view.speeed
        self.assertAlmostEqual(view.get("speeed", 42.0), 42.0)   # 要默认值走 get

    def test_curve_linear_interpolation(self):
        from efx_format.sim.resolve import Curve
        c = Curve([(0.0, 0.0, 2), (10.0, 100.0, 2)])
        self.assertAlmostEqual(c.eval(-5.0), 0.0)      # 左端夹取
        self.assertAlmostEqual(c.eval(0.0), 0.0)
        self.assertAlmostEqual(c.eval(5.0), 50.0)
        self.assertAlmostEqual(c.eval(10.0), 100.0)
        self.assertAlmostEqual(c.eval(99.0), 100.0)    # 右端夹取

    def test_curve_constant_transition_holds(self):
        from efx_format.sim.resolve import Curve
        c = Curve([(0.0, 0.0, 1), (10.0, 100.0, 2)])   # 1 = CONSTANT
        self.assertAlmostEqual(c.eval(5.0, "native"), 0.0)
        self.assertAlmostEqual(c.eval(5.0, "linear"), 50.0)

    def test_a1_curve_drives_by_particle_age(self):
        from efx_format.sim.resolve import FieldView
        tracks = self._tracks_with("VELOCITY3D", "speed", 1,
                                   [(0.0, 10.0, 2), (10.0, 20.0, 2)])
        r = self._resolver(tracks=tracks)
        self.assertAlmostEqual(FieldView(r, 0, 0).speed, 10.0)
        self.assertAlmostEqual(FieldView(r, 0, 5).speed, 15.0)
        self.assertAlmostEqual(FieldView(r, 0, 10).speed, 20.0)

    def test_a0_curve_drives_by_emitter_frame(self):
        from efx_format.sim.resolve import FieldView
        tracks = self._tracks_with("VELOCITY3D", "speed", 0,
                                   [(0.0, 1.0, 2), (100.0, 101.0, 2)])
        r = self._resolver(tracks=tracks)
        self.assertAlmostEqual(FieldView(r, 0, 0).speed, 1.0)
        self.assertAlmostEqual(FieldView(r, 50, 0).speed, 51.0)

    def test_timl_mode_replace_vs_multiply(self):
        from efx_format.sim.resolve import FieldView
        tracks = self._tracks_with("VELOCITY3D", "speed", 1, [(0.0, 3.0, 2)])
        raw = velocity_fields(speed=2.0)
        rep = self._resolver(raw=raw, tracks=tracks, config=SimConfig(timl_mode="replace"))
        mul = self._resolver(raw=raw, tracks=tracks, config=SimConfig(timl_mode="multiply"))
        self.assertAlmostEqual(FieldView(rep, 0, 0).speed, 3.0)
        self.assertAlmostEqual(FieldView(mul, 0, 0).speed, 6.0)

    def test_float6_six_channel_field_maps_per_half(self):
        """rangeXYZ 有 6 条通道（RangeMinX/RangeMaxX/…），逐轴交错对应字节布局。"""
        from efx_format.sim.resolve import FieldView
        raw = es3d_fields(rangeXYZ=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        # comp 1 = RangeMaxX → 只该影响 hi 的 X
        tracks = self._tracks_with("EMITTERSHAPE3D", "rangeXYZ", 1,
                                   [(0.0, 99.0, 2)], comp=1)
        r = self._resolver("EMITTERSHAPE3D", raw, tracks)
        view = FieldView(r, 0, 0)
        self.assertEqual(view.xyz_lo("rangeXYZ"), Vec3(1.0, 3.0, 5.0))
        self.assertEqual(view.xyz_hi("rangeXYZ"), Vec3(99.0, 4.0, 6.0))

    def test_a0_sample_switch_changes_which_frame_is_read(self):
        """待标定开关：粒子级字段的 A0 取出生帧还是当前帧。"""
        from efx_format.sim.resolve import FieldResolver, FieldView
        tracks = self._tracks_with("VELOCITY3D", "speed", 0,
                                   [(0.0, 0.0, 2), (100.0, 100.0, 2)])

        class FakeP(object):
            birth_frame = 10
            age = 0

        for mode, expect in (("spawn", 10.0), ("current", 80.0)):
            cfg = SimConfig(a0_sample=mode)
            r = FieldResolver("VELOCITY3D", velocity_fields(), tracks, cfg)
            a0 = FakeP.birth_frame if mode == "spawn" else 80
            self.assertAlmostEqual(FieldView(r, a0, FakeP.age).speed, expect)

    def test_real_archetype_timl_parses(self):
        """回归护栏：真实 TIML 字节能解出预期通道（draw_chain 是 A1 两条）。"""
        from efx_format.sim.resolve import TimlTracks
        _blocks, timl = _load_archetype("draw_chain.json")
        tracks = TimlTracks.parse(timl)
        self.assertTrue(tracks.ok)
        self.assertEqual(tracks.channel_count(), 2)
        self.assertTrue(all(axis == 1 for axis, _tlp, _dt in tracks._curves))

    def test_empty_timl_is_harmless(self):
        from efx_format.sim.resolve import TimlTracks
        self.assertFalse(TimlTracks.parse(b"").ok)
        self.assertFalse(TimlTracks.parse(b"not a timl at all").ok)


# ─────────────────────────────────────────────────────────────────────────────
# 播放长度
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestedDuration(unittest.TestCase):

    def test_covers_start_delay_and_life(self):
        sim = make_sim(spawn=spawn_fields(emitterStartDelay=30, burstInterval=10),
                       life=life_fields(duration=45))
        self.assertGreaterEqual(sim.suggested_duration(), 75)

    def test_fire_archetype(self):
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl)
        d = sim.suggested_duration()
        self.assertGreaterEqual(d, 60)        # 至少盖住一个粒子的寿命
        self.assertLess(d, 10000)

    def test_never_exceeds_max_frames(self):
        cfg = SimConfig(max_frames=50)
        sim = make_sim(spawn=spawn_fields(emitterStartDelay=99999),
                       life=life_fields(indefiniteLifespan=1), config=cfg)
        self.assertLessEqual(sim.suggested_duration(), 50)


# ─────────────────────────────────────────────────────────────────────────────
# SCALEANIM
# ─────────────────────────────────────────────────────────────────────────────

class TestScaleAnim(unittest.TestCase):

    def test_scale_starts_at_one(self):
        p, _ = one_particle(scaleanim=scaleanim_fields())
        self.assertEqual(p.scale, Vec3(1, 1, 1))

    def test_uniform_growth_is_additive_on_all_axes(self):
        """通道名是 SizeScalarAdd —— 加法，不是乘法。"""
        p, _ = one_particle(frames=3, scaleanim=scaleanim_fields(initialScaleSpeed=0.1))
        for v in (p.scale.x, p.scale.y, p.scale.z):
            self.assertAlmostEqual(v, 1.0 + 0.3, places=6)

    def test_uniform_accel_decays_the_increment(self):
        """iv=0.02 / ia=0.99 / 60 帧 ≈ +0.91（floating_particle_fire 的实测组合）。"""
        p, _ = one_particle(frames=60, scaleanim=scaleanim_fields(
            initialScaleSpeed=0.02, initialScaleAccel=0.99))
        expect = 1.0 + sum(0.02 * (0.99 ** n) for n in range(60))
        self.assertAlmostEqual(p.scale.x, expect, places=6)
        self.assertAlmostEqual(p.scale.x, 1.91, places=2)

    def test_per_axis_is_independent(self):
        p, _ = one_particle(frames=4, scaleanim=scaleanim_fields(
            scaleSpeedX=0.5, scaleSpeedY=0.25, scaleSpeedZ=0.0))
        self.assertAlmostEqual(p.scale.x, 1.0 + 2.0, places=6)
        self.assertAlmostEqual(p.scale.y, 1.0 + 1.0, places=6)
        self.assertAlmostEqual(p.scale.z, 1.0, places=6)

    def test_anim_update_start_delays_only_the_per_axis_part(self):
        """animUpdateStart 门控逐轴那组；整体那组不受影响。"""
        p, _ = one_particle(frames=5, scaleanim=scaleanim_fields(
            initialScaleSpeed=0.1, scaleSpeedX=1.0, animUpdateStart=3))
        self.assertAlmostEqual(p.scale.y, 1.0 + 0.5, places=6)   # 整体：5 帧都算
        self.assertAlmostEqual(p.scale.x, 1.0 + 0.5 + 2.0, places=6)  # 逐轴：只有 2 帧

    def test_stage_is_xform(self):
        from efx_format.sim import XFORM
        sim = make_sim(spawn=spawn_fields(), life=life_fields(),
                       scaleanim=scaleanim_fields())
        b = [x for x in sim.bound if x.type_hash == SCALEANIM][0]
        self.assertEqual(b.stage, XFORM)


# ─────────────────────────────────────────────────────────────────────────────
# ROTATEANIM
# ─────────────────────────────────────────────────────────────────────────────

class TestRotateAnim(unittest.TestCase):

    def test_plane_mode_accumulates_on_z(self):
        """平面旋转 = 屏幕空间自转，写 Z。"""
        p, _ = one_particle(frames=4, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=15.0))
        self.assertAlmostEqual(p.rot.z, 60.0, places=6)
        self.assertEqual((p.rot.x, p.rot.y), (0.0, 0.0))

    def test_plane_coef_decays_the_speed(self):
        p, _ = one_particle(frames=5, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, billboardRotationCoef=0.5))
        self.assertAlmostEqual(p.rot.z, sum(10.0 * 0.5 ** n for n in range(5)), places=6)

    def test_spin_mode_uses_all_three_axes(self):
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=2, spinAxisMask=0x7,
            spin_velocity=[1.0, 0.0, 2.0, 0.0, 3.0, 0.0]))
        self.assertAlmostEqual(p.rot.x, 3.0, places=6)
        self.assertAlmostEqual(p.rot.y, 6.0, places=6)
        self.assertAlmostEqual(p.rot.z, 9.0, places=6)

    def test_spin_axis_mask_gates_axes(self):
        """spinAxisMask bit0=X bit1=Y bit2=Z。只开 Y。"""
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=2, spinAxisMask=0x2,
            spin_velocity=[1.0, 0.0, 2.0, 0.0, 3.0, 0.0]))
        self.assertEqual(p.rot.x, 0.0)
        self.assertAlmostEqual(p.rot.y, 6.0, places=6)
        self.assertEqual(p.rot.z, 0.0)

    def test_delay_holds_rotation(self):
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, rotateDelayStart=5))
        self.assertEqual(p.rot.z, 0.0)
        p, _ = one_particle(frames=8, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, rotateDelayStart=5))
        self.assertAlmostEqual(p.rot.z, 30.0, places=6)   # 第 5..7 帧共 3 次

    def test_random_direction_mode_produces_both_signs(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=60, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(rotationModeMask=1,
                                                    billboardRotation=10.0))
        sim.step()
        signs = {1 if p.rot.z > 0 else -1 for p in sim.particles}
        self.assertEqual(signs, {1, -1})

    def test_fixed_direction_mode_is_single_signed(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=60, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(rotationModeMask=0,
                                                    billboardRotation=10.0))
        sim.step()
        self.assertTrue(all(p.rot.z > 0 for p in sim.particles))


# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORM3D
# ─────────────────────────────────────────────────────────────────────────────

class TestTransform3D(unittest.TestCase):

    def test_static_translate_is_skipped_by_default(self):
        """默认宿主负责摆位——模拟层再加一次就会双份位移。"""
        sim = make_sim(transform=transform3d_fields(
                           translate=[10.0, 0.0, 20.0, 0.0, 30.0, 0.0]),
                       spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.step()
        self.assertEqual(sim.em.origin, Vec3())
        self.assertEqual(sim.particles[0].pos, Vec3())
        self.assertTrue(any("静态变换未套用" in n for n in sim.notes))

    def test_apply_base_switch_moves_the_emitter(self):
        sim = make_sim(transform=transform3d_fields(
                           translate=[10.0, 0.0, 20.0, 0.0, 30.0, 0.0]),
                       spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       config=SimConfig(t3d_apply_base=True))
        sim.step()
        self.assertEqual(sim.em.origin, Vec3(10, 20, 30))
        self.assertEqual(sim.particles[0].pos, Vec3(10, 20, 30))

    def test_velocity_bitflag_gates_drift(self):
        base = dict(translation_velocity=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        off = make_sim(transform=transform3d_fields(enableVelocityBitflag=0, **base),
                       spawn=spawn_fields(burstInterval=1000), life=life_fields())
        on = make_sim(transform=transform3d_fields(enableVelocityBitflag=1, **base),
                      spawn=spawn_fields(burstInterval=1000), life=life_fields())
        off.run(5)
        on.run(5)
        self.assertEqual(off.em.origin, Vec3())
        self.assertAlmostEqual(on.em.origin.x, 5.0, places=6)

    def test_emitter_velocity_feeds_velocity_type_3(self):
        """velocityType=3 EmitterMotion 继承发射器移动——这是它唯一的来源。"""
        sim = make_sim(
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[2.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            spawn=spawn_fields(burstInterval=1000),
            life=life_fields(indefiniteLifespan=1),
            velocity=velocity_fields(velocityType=3, speed=1.0))
        sim.run(3)
        self.assertAlmostEqual(sim.em.velocity.x, 2.0, places=6)
        self.assertGreater(sim.particles[0].vel.x, 0.0)

    def test_emitter_motion_below_threshold_is_gated(self):
        sim = make_sim(
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[0.5, 0.0, 0.0, 0.0, 0.0, 0.0]),
            spawn=spawn_fields(burstInterval=1000),
            life=life_fields(indefiniteLifespan=1),
            velocity=velocity_fields(velocityType=3, speed=1.0,
                                     minMovementThreshold=10.0))
        sim.run(3)
        self.assertEqual(sim.particles[0].vel, Vec3())

    def test_transform3d_runs_before_emittershape(self):
        """发射器原点必须先定下来，ES3D 才能在它周围采样。"""
        sim = make_sim(transform=transform3d_fields(), spawn=spawn_fields(),
                       life=life_fields(), es3d=es3d_fields())
        order = [b.type_hash for b in sim.bound]
        self.assertLess(order.index(TRANSFORM3D), order.index(EMITTERSHAPE3D))


# ─────────────────────────────────────────────────────────────────────────────
# BILLBOARD3D
# ─────────────────────────────────────────────────────────────────────────────

class TestBillboard3D(unittest.TestCase):

    def _item(self, frames=1, **kw):
        kw.setdefault("billboard", billboard_fields())
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        sim = make_sim(**kw)
        for _ in range(frames):
            sim.step()
        items = sim.build_render()
        return items[0], sim

    def test_kind_is_billboard_not_fallback_point(self):
        it, _ = self._item()
        self.assertEqual(it.kind, "BILLBOARD")

    def test_size_is_width_times_scale_in_game_units(self):
        """SizeScalar 是倍率：width=100, scale=0.4 → 40 游戏单位（0.4 Blender 单位）。"""
        it, _ = self._item(billboard=billboard_fields(width=100.0, height=50.0, scale=0.4))
        self.assertAlmostEqual(it.size.x, 40.0, places=5)
        self.assertAlmostEqual(it.size.y, 20.0, places=5)

    def test_scaleanim_multiplies_the_size(self):
        it, _ = self._item(frames=10,
                           billboard=billboard_fields(width=100.0, height=100.0, scale=1.0),
                           scaleanim=scaleanim_fields(initialScaleSpeed=0.1))
        self.assertAlmostEqual(it.size.x, 100.0 * 2.0, places=4)

    def test_color_is_ubyte_scaled(self):
        it, _ = self._item(billboard=billboard_fields(color=[128, 0, 255, 255]))
        self.assertAlmostEqual(it.color[0], 128 / 255.0, places=6)
        self.assertAlmostEqual(it.color[1], 0.0, places=6)
        self.assertAlmostEqual(it.color[2], 1.0, places=6)

    def test_brightness_multiplies_rgb(self):
        it, _ = self._item(billboard=billboard_fields(color=[100, 100, 100, 255],
                                                      brightness=2.0))
        self.assertAlmostEqual(it.color[0], 200 / 255.0, places=6)

    def test_color_range_lerps_per_particle(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=60, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(color=[0, 0, 0, 255],
                                                  colorRange=[255, 255, 255, 255],
                                                  useColorRange=1))
        sim.step()
        reds = [i.color[0] for i in sim.build_render()]
        self.assertGreater(max(reds) - min(reds), 0.5)   # 确实在两端之间铺开
        self.assertGreaterEqual(min(reds), 0.0)
        self.assertLessEqual(max(reds), 1.0)

    def test_color_range_off_is_uniform(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=20, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(color=[0, 0, 0, 255],
                                                  colorRange=[255, 255, 255, 255],
                                                  useColorRange=0))
        sim.step()
        self.assertEqual({i.color[0] for i in sim.build_render()}, {0.0})

    def test_blend_mode_maps(self):
        it, _ = self._item(billboard=billboard_fields(blendMode=0))
        self.assertEqual(it.blend, "ALPHA")
        it, _ = self._item(billboard=billboard_fields(blendMode=1))
        self.assertEqual(it.blend, "ADDITIVE")

    def test_alpha_comes_from_life(self):
        it, _ = self._item(frames=3, billboard=billboard_fields(),
                           life=life_fields(fadeInDuration=4, duration=20))
        self.assertAlmostEqual(it.color[3], 0.5, places=6)

    def test_initial_rotation_seeds_rot_z(self):
        p, _ = one_particle(billboard=billboard_fields(rotation=45.0))
        self.assertAlmostEqual(p.rot.z, 45.0, places=6)

    def test_rotateanim_accumulates_on_top_of_initial_rotation(self):
        it, _ = self._item(frames=3,
                           billboard=billboard_fields(rotation=45.0),
                           rotateanim=rotateanim_fields(rotationModeMask=0,
                                                        billboardRotation=10.0))
        self.assertAlmostEqual(it.rot, 45.0 + 30.0, places=6)

    def test_epv_slot_is_reported(self):
        _it, sim = self._item(billboard=billboard_fields(EPVColorSlot1=3))
        self.assertTrue(any("EPV" in n for n in sim.notes))

    def test_render_body_writes_no_particle_state(self):
        """RENDER_BODY 阶段不许改粒子状态——strict 模式会查。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(), scaleanim=scaleanim_fields(),
                       rotateanim=rotateanim_fields(),
                       config=SimConfig(strict=True))
        for _ in range(10):
            sim.step()
            sim.build_render()


# ─────────────────────────────────────────────────────────────────────────────
# T2 之后的端到端
# ─────────────────────────────────────────────────────────────────────────────

class TestT2EndToEnd(unittest.TestCase):

    def test_fire_archetype_now_renders_billboards(self):
        """floating_particle_fire 带 BILLBOARD3D，不该再退化成点。"""
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl, SimConfig(seed=3))
        sim.run(20)
        items = sim.build_render()
        self.assertTrue(items)
        for it in items:
            self.assertEqual(it.kind, "BILLBOARD")

    def test_fire_size_is_physically_sensible(self):
        """width=height=100、scale=0.4(+0.2 抖动) → 40~60 游戏单位 = 0.4~0.6 Blender 单位。
        再乘 SCALEANIM 一生最多约 1.9 倍。"""
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl, SimConfig(seed=3))
        sim.step()
        it = sim.build_render()[0]
        self.assertGreaterEqual(it.size.x, 40.0)
        self.assertLessEqual(it.size.x, 60.0)
        sim.run(59)
        if sim.build_render():
            self.assertLess(sim.build_render()[0].size.x, 60.0 * 2.0)

    def test_fire_uses_alpha_blend(self):
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl)
        sim.step()
        self.assertEqual(sim.build_render()[0].blend, "ALPHA")   # blendMode=0

    def test_more_attributes_are_simulated_now(self):
        """T2 之后，fire 原型的未模拟属性应该比 T1 时少。"""
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl)
        names = {n for _h, n in sim.unsupported}
        for done in ("SPAWN", "LIFE", "EMITTERSHAPE3D", "VELOCITY3D",
                     "TRANSFORM3D", "SCALEANIM", "BILLBOARD3D"):
            self.assertNotIn(done, names)

    def test_every_archetype_still_runs_and_renders(self):
        for name in sorted(os.listdir(ARCHETYPE_DIR)):
            if not name.endswith(".json"):
                continue
            with self.subTest(archetype=name):
                blocks, timl = _load_archetype(name)
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=1, strict=True))
                for _ in range(120):
                    sim.step()
                sim.build_render()


if __name__ == "__main__":
    unittest.main(verbosity=2)
