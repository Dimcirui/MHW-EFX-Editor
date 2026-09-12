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

from efx_format.hashes import (ALPHACORRECTION, BILLBOARD3D, DUMMY,  # noqa: E402
                               EMITTERSHAPE3D,
                               LIFE, MESH, NOISE, PLANE, RIBBON, RIBBONBLADE,
                               PARENTOPTIONS, PTLIFE, RGBFIRE, RGBWATER,
                               ROTATEANIM, SCALEANIM,
                               SPAWN, TRANSFORM3D, UVSEQUENCE, VELOCITY3D)
from efx_format.sim import (ActionTarget, EntryTemplate, FORCE,  # noqa: E402
                            Behavior, SimConfig, SimResources, SimScene,
                            Simulator, Vec3, from_attr_blocks, grid_table,
                            register)
from efx_format.sim import uvs_table as simuvs  # noqa: E402
from efx_format.sim.behaviors.uvsequence import frame_info  # noqa: E402
from efx_format.sim import rng as simrng  # noqa: E402
from efx_format.sim.vecmath import (ROT_ORDER_TRANSFORM,  # noqa: E402
                                    rot_order_name, rotate_euler)

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


def rgbfire_fields(**kw):
    f = {"typeFlag": 1,
         "fireColor": [255, 0, 0, 255], "smokeColor": [0, 0, 255, 255],
         "brightness1": 1.0, "brightness2": 1.0,
         "unkn4": 0.0, "brightness3": 1.0, "brightness4": 1.0}
    for pre in ("fireColorParam_", "smokeColorParam_"):
        f[pre + "useLife"] = 0
        for k in ("appearFrame", "keepFrame", "vanishFrame"):
            f[pre + k] = 0
            f[pre + k + "Jitter"] = 0
        f[pre + "lighting"] = 0
        f[pre + "lifeType"] = 0
        f[pre + "unkn9"] = 0
    f.update(kw)
    return f


def rgbwater_fields(**kw):
    f = {"typeFlag": 1,
         "colorSpecular": [255, 0, 0, 255], "colorSheet": [0, 0, 255, 255],
         "colorRate": 1.0, "waterLerpGtoB": 0.0, "intensityCubeMap": 0.0,
         "intensitySpecular": 1.0, "intensitySheet": 1.0, "intensityAlpha": 1.0,
         "unknownFloat": 0.3, "path_len": 0, "path": b""}
    for pre in ("specularColorParam_", "sheetColorParam_", "waterLerpParam_"):
        f[pre + "useLife"] = 0
        for k in ("appearFrame", "keepFrame", "vanishFrame"):
            f[pre + k] = 0
            f[pre + k + "Jitter"] = 0
        f[pre + "lighting"] = 0
        f[pre + "lifeType"] = 0
    for pre in ("specularColorParam_", "sheetColorParam_"):
        f[pre + "unkn9"] = 0
    f.update(kw)
    return f


def alphacorrection_fields(**kw):
    f = {"unkn0": 1, "lowPass": 0.0, "contrast_gamma": 1.0,
         "unkn3": 0.0, "unknFlag2": 0}
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


def plane_fields(**kw):
    f = {"typeFlag": 0, "applicationRule": 0,
         "color": [255, 255, 255, 255], "colorRange": [255, 255, 255, 255],
         "useColorRange": 0, "blendMode": 0,
         "brightness": 1.0, "brightnessJitter": 0.0,
         "EPVColorSlot1": 0, "EPVColorSlot2": 0,
         "rotation2": 0.0, "rotation2Jitter": 0.0,
         "scale": 1.0, "scaleJitter": 0.0,
         "width": 100.0, "widthJitter": 0.0,
         "height": 100.0, "heightJitter": 0.0,
         "baseAxis": 1, "rotationOrder": 4,
         "rotation": [0.0] * 6}
    f.update(kw)
    return f


def ribbon_fields(**kw):
    f = {"typeFlag": 0, "color": [255, 255, 255, 255],
         "colorRange": [255, 255, 255, 255], "useColorRange": 0, "blendMode": 0,
         "brightness": 1.0, "brightnessJitter": 0.0,
         "ribbonMode": 0, "scale": 1.0, "scale_jitter": 0.0,
         "width": 20.0, "width_jitter": 0.0,
         "length": 100.0, "length_jitter": 0.0,
         "subdivisionCount": 5, "baseAxis": 1, "rotationOrder": 4,
         "rotationX": 0.0, "rotationXJitter": 0.0,
         "rotationY": 0.0, "rotationYJitter": 0.0,
         "rotationZ": 0.0, "rotationZJitter": 0.0,
         "spawnAnchorOffset": 0.0,
         "restoreStrength": 1.0, "restoreStrengthJitter": 0.0,
         "inertia": 0.9, "inertiaJitter": 0.0,
         "springiness": 0.1, "springiness_jitter": 0.0,
         "epvcolor_0": 0, "epvcolor_1": 0,
         "base_width_multiplier": 1.0, "tip_width_multiplier": 1.0,
         "base_opacity": 1.0, "tip_opacity": 1.0,
         "enableFlap": 0,
         "flap1Frequency": 0.0, "flap1FrequencyJitter": 0.0,
         "flap1Amount": 0.0, "flap1AmountJitter": 0.0,
         "flap2Frequency": 0.0, "flap2FrequencyJitter": 0.0,
         "flap2Amount": 0.0, "flap2AmountJitter": 0.0}
    f.update(kw)
    return f


def blade_fields(**kw):
    white = {"epvColorSlot": 0, "color1": [255, 255, 255, 255]}
    f = {"typeFlag": 1, "widthDirection": 1, "width": 100.0,
         "length": 500.0, "lengthMode": 0,
         "maxLengthLimit": 1500.0, "contractionSpeed": 600.0,
         "colourTransitionPoint": 0.0, "emissiveStrength": 1.0,
         "uvRepetition": 1.0, "head": dict(white), "tailEnd": dict(white)}
    f.update(kw)
    return f


def mesh_fields(**kw):
    f = {"typeFlag": 1, "colorRate": 1.0, "colorRateJitter": 0.0,
         "emissiveColorRate": 1.0, "emissiveColorRateJitter": 0.0,
         "rotation": [0.0] * 6, "rotation2": 0.0, "rotation2Jitter": 0.0,
         "rotationOrder": 4,
         "scale": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
         "global_scale": 1.0, "global_scale_jitter": 0.0,
         "visconIndex": 0, "visconIndexJitter": 0,
         "color": [255, 255, 255, 255], "colorRange": [255, 255, 255, 255],
         "emissiveColor": [0, 0, 0, 255], "emissiveColorRange": [0, 0, 0, 255],
         "useColorRange": 0, "useEmissiveColor": 0, "useEmissiveColorRange": 0,
         "disableAllColorRange": 0,
         "epv_color_slot1": 0, "epv_color_slot2": 0}
    f.update(kw)
    return f


def parentoptions_fields(**kw):
    f = {"typeFlag": 0,
         "relationPos": [0, 0, 0], "relationRot": [0, 0, 0], "relationScl": [0, 0, 0],
         "particleUseLocal": 0, "unknFlag1": 0,
         "constRelease": 0, "constReleaseJitter": 0, "jointNo": -1}
    f.update(kw)
    return f


#: TRANSFORM3D 的速度字段是**每秒**（见 behaviors/transform3d.py），而下面这两个 helper
#: 的参数写的是「每帧多少」——测试断言按帧数算更直观，所以这里乘上 fps 换过去。
_FPS = 60.0


def drifting_emitter(vx=0.0, vy=0.0, vz=0.0):
    """一个**每帧**位移 (vx,vy,vz) 的发射器（TRANSFORM3D 的 translation_velocity）。"""
    return transform3d_fields(
        enableVelocityBitflag=1,
        translation_velocity=[vx * _FPS, 0.0, vy * _FPS, 0.0, vz * _FPS, 0.0])


def spinning_emitter(ry_per_frame=0.0):
    """一个**每帧**绕 Y 转 `ry_per_frame` 度的发射器。"""
    return transform3d_fields(
        enableVelocityBitflag=1,
        rotation_velocity=[0.0, 0.0, ry_per_frame * _FPS, 0.0, 0.0, 0.0])


def ptlife_fields(**kw):
    f = {"typeFlag": 0, "unknFixed1": 0, "status": 0, "unknEnum3": 0,
         "relationIndex": 0, "unknEnum5": 0,
         "unknFrame0": 0, "unknFrame0Jitter": 0,
         "unknFrame1": 0, "unknFrame1Jitter": 0}
    f.update(kw)
    return f


def make_sim(spawn=None, life=None, velocity=None, es3d=None, config=None, extra=(),
             transform=None, scaleanim=None, rotateanim=None, billboard=None,
             resources=None):
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
    return Simulator(blocks, b"", config or SimConfig(), resources)


def uvseq_fields(**kw):
    f = {"typeFlag": 1, "sequenceNo": 0, "sequenceNoJitter": 0,
         "patternNo": 0, "patternNoJitter": 0,
         "playSpeed": 1.0, "playSpeedJitter": 0.0,
         "playSpeedCoef": 1.0, "playSpeedCoefJitter": 0.0,
         "loopingMode": 1, "loopingOrientation": 0, "loopingPad": 0,
         "path_len": 0, "path": b""}
    f.update(kw)
    return f


def looping_mode(playback=1, flip_h=0, flip_v=0, direction=0):
    """打包 loopingMode 字节（与 schema/enums.py::BITS_LOOPING_MODE 同一套位段）。"""
    return ((playback & 3) | ((flip_h & 3) << 2) | ((flip_v & 3) << 4)
            | ((direction & 3) << 6))


def uvs_bytes(frame_rects, extra_groups=0):
    """造一个最小 .uvs 字节流（走真正的序列化器，不手搓字节）。"""
    from efx_format.uvs import UVSFile, UVSFrame, UVSGroup, UVSString

    def _grp(rects):
        frames = [UVSFrame(uv0=(r[0], r[1]), uv1=(r[2], r[3])) for r in rects]
        return UVSGroup(frames=frames, path_indices=[0], map_count=1, dynamic=4)

    groups = [_grp(frame_rects)]
    for i in range(extra_groups):
        groups.append(_grp([(0.0, 0.0, 0.5, 0.5)] * (2 + i)))
    return UVSFile(groups=groups,
                   strings=[UVSString(path="sheet.tex", type=1)]).serialize()


def uvseq_sim(uv=None, frames=0, config=None, resources=None, **kw):
    """一个粒子 + UVSEQUENCE（默认配 BILLBOARD3D，这样 build_render 有东西可改）。"""
    kw.setdefault("spawn", spawn_fields(burstInterval=1000))
    kw.setdefault("life", life_fields(indefiniteLifespan=1))
    kw.setdefault("billboard", billboard_fields())
    extra = list(kw.pop("extra", ()))
    extra.append((UVSEQUENCE, uvseq_fields(**(uv or {}))))
    sim = make_sim(config=config, resources=resources, extra=extra, **kw)
    for _ in range(frames):
        sim.step()
    return sim


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

    def test_interval_jitter_is_rolled_per_burst(self):
        """burstIntervalJitter 每批重抽 → 批间距参差不齐，落在 [v, v+jitter] 里。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=4, burstIntervalJitter=4),
                       life=life_fields(indefiniteLifespan=1))
        frames = self._birth_frames(sim, 200)
        gaps = {b - a for a, b in zip(frames, frames[1:])}
        self.assertGreater(len(gaps), 1)                    # 不是整轮等距
        self.assertGreaterEqual(min(gaps), 4)
        self.assertLessEqual(max(gaps), 8)

    def test_interval_jitter_per_cycle_is_uniform(self):
        """'per_cycle'（改动前的行为）：一轮只抽一次，整轮等距。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=4, burstIntervalJitter=4),
                       life=life_fields(indefiniteLifespan=1),
                       config=SimConfig(spawn_interval_jitter="per_cycle"))
        frames = self._birth_frames(sim, 200)
        gaps = {b - a for a, b in zip(frames, frames[1:])}
        self.assertEqual(len(gaps), 1)

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

    def test_finite_cycle_stops_emitting(self):
        """批次数 = burstsPerCycle + emitterRepeatCount - 1，发完就**不再发**。

        3 + 1 - 1 = 3 批、间隔 2 帧 → 只有 0/2/4 三个出生帧，后面一直空着。
        """
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=3, emitterRepeatCount=1, burstInterval=2),
            life=life_fields(duration=10, indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 200), [0, 2, 4])

    def test_recycle_mode_keeps_going(self):
        """'recycle'（改动前的行为）：最后一批之后按粒子寿命等一段，换位置再开一轮。"""
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=3, emitterRepeatCount=1, burstInterval=2),
            life=life_fields(duration=10, indefiniteLifespan=1),
            config=SimConfig(spawn_after_cycle="recycle"))
        frames = self._birth_frames(sim, 30)
        self.assertEqual(frames[:6], [0, 2, 4, 14, 16, 18])
        self.assertGreaterEqual(sim.em.cycle, 2)

    def test_zero_repeat_count_never_stops(self):
        """emitterRepeatCount=0 是「无限」那一态，不受收工逻辑影响。"""
        sim = make_sim(
            spawn=spawn_fields(burstsPerCycle=2, emitterRepeatCount=0, burstInterval=3),
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
    """按作者教程《生成方式》：rangeXYZ = 偏移(内边界) / 尺寸(向外的厚度)。"""

    def _spawn_many(self, es3d, n=300, config=None):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=n, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       es3d=es3d, config=config)
        sim.step()
        return [p.spawn_pos for p in sim.particles]

    # ── 偏移 / 尺寸 ──────────────────────────────────────────────────────────
    def test_box_offset_zero_fills_the_volume(self):
        """偏移=0、尺寸=S → 实心盒子，逐轴 ±S。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[0.0, 100.0, 0.0, 0.0, 0.0, 20.0]))
        self.assertLessEqual(max(abs(p.x) for p in pts), 100.0 + 1e-9)
        self.assertGreater(max(abs(p.x) for p in pts), 80.0)
        self.assertEqual(max(abs(p.y) for p in pts), 0.0)      # 这一轴厚度 0
        self.assertLessEqual(max(abs(p.z) for p in pts), 20.0 + 1e-9)

    def test_box_offset_hollows_the_middle(self):
        """偏移=10、尺寸=10 → 厚度 10、内部掏空：没有点落在内盒里面。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[10.0, 10.0, 10.0, 10.0, 10.0, 10.0]), n=400)
        for p in pts:
            self.assertLessEqual(max(abs(p.x), abs(p.y), abs(p.z)), 20.0 + 1e-9)
            # 至少一个轴越过内边界 → 不在空腔里
            self.assertGreaterEqual(max(abs(p.x), abs(p.y), abs(p.z)), 10.0 - 1e-9)

    def test_sphere_shell_between_offset_and_offset_plus_size(self):
        """球：半径落在 [偏移, 偏移+尺寸] 之间。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=1, rangeXYZ=[10.0, 10.0, 10.0, 10.0, 10.0, 10.0]))
        radii = [p.length() for p in pts]
        self.assertGreaterEqual(min(radii), 10.0 - 1e-6)
        self.assertLessEqual(max(radii), 20.0 + 1e-6)
        self.assertGreater(max(radii) - min(radii), 3.0)        # 壳层是有厚度的

    def test_sphere_size_zero_is_a_surface(self):
        """尺寸=0 → 内外边界重合，退化成球面。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=1, rangeXYZ=[10.0, 0.0, 10.0, 0.0, 10.0, 0.0]))
        for p in pts:
            self.assertAlmostEqual(p.length(), 10.0, places=5)

    def test_minmax_mode_is_still_available(self):
        """'minmax' 是留作对照的旧读法（RE DTI 官方名那一套）。"""
        fields = es3d_fields(shapeType=0, rangeXYZ=[4.0, 10.0, 0.0, 0.0, 0.0, 0.0])
        mm = self._spawn_many(fields, config=SimConfig(es3d_range_mode="minmax"))
        self.assertGreaterEqual(min(p.x for p in mm), 4.0 - 1e-9)
        self.assertLessEqual(max(p.x for p in mm), 10.0 + 1e-9)

    # ── 扫描角度 ─────────────────────────────────────────────────────────────
    def test_horizontal_scan_angle_restricts_the_sweep(self):
        """横向扫描角度 90 → 只覆盖四分之一圈（球/圆柱用）。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[0.0, 10.0, 0.0, 0.0, 0.0, 10.0],
            scanAngleHorizontal=90.0))
        for p in pts:
            ang = math.degrees(math.atan2(p.z, p.x)) % 360.0
            self.assertLessEqual(ang, 91.0)

    def test_vertical_scan_angle_shrinks_toward_none(self):
        """纵向扫描角度只有球用：0=全向、180=一半、360=不生成（越大越窄）。"""
        def band(v):
            pts = self._spawn_many(es3d_fields(
                shapeType=1, rangeXYZ=[0.0, 10.0, 0.0, 10.0, 0.0, 10.0],
                scanAngleVertical=v), n=200)
            return max(abs(p.y) for p in pts)

        full, half, none = band(0.0), band(180.0), band(360.0)
        self.assertGreater(full, 8.0)              # 全向：能到两极附近
        self.assertLess(half, full * 0.75)         # 一半：明显收窄
        self.assertLess(none, 1e-6)               # 360：只剩赤道一圈
        self.assertGreater(half, 1.0)

    # ── 等分数量（纵向=扇形切片，横向=纬度/高度切片）──────────────────────────
    def test_vertical_divide_cuts_fan_slices(self):
        """纵向等分数量：绕竖轴切扇形 —— 立方体/球/圆柱都用。4 → 只有 4 个方位。"""
        for shape in (0, 1, 2):
            with self.subTest(shape=shape):
                pts = self._spawn_many(es3d_fields(
                    shapeType=shape, rangeXYZ=[0.0, 10.0, 0.0, 10.0, 0.0, 10.0],
                    rangeDivideVerticalNum=4), n=200)
                angles = {round(math.degrees(math.atan2(p.z, p.x)) % 360.0, 2)
                          for p in pts if math.hypot(p.x, p.z) > 1e-6}
                self.assertLessEqual(len(angles), 4)
                self.assertGreater(len(angles), 1)

    def test_horizontal_divide_slices_the_cylinder_by_height(self):
        """横向等分数量：圆柱是沿高度的水平切片。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[0.0, 10.0, 0.0, 10.0, 0.0, 10.0],
            rangeDivideHorizontalNum=3), n=200)
        ys = {round(p.y, 4) for p in pts}
        self.assertLessEqual(len(ys), 3)

    def test_horizontal_divide_makes_cones_on_the_sphere(self):
        """横向等分数量：球是 n 个圆锥面 → 极角只剩 n 个离散值。"""
        # 用「偏移=10 尺寸=0」的薄壳（球面）：半径固定，纬度才看得出离散
        pts = self._spawn_many(es3d_fields(
            shapeType=1, rangeXYZ=[10.0, 0.0, 10.0, 0.0, 10.0, 0.0],
            rangeDivideHorizontalNum=6), n=300)
        ys = {round(p.y, 3) for p in pts}
        self.assertLessEqual(len(ys), 6)
        self.assertGreater(len(ys), 1)

    # ── 起始/结束半径 = 锥度（只有圆柱用）────────────────────────────────────
    def test_radius_taper_makes_a_cone(self):
        """起始半径 0.2 / 结束 1.0 → 沿高度收窄成圆台：底细顶粗。"""
        # 同样用薄壳（管壁）：实心圆柱里半径本来就从 0 铺到 R，看不出锥度
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[10.0, 0.0, 0.0, 10.0, 10.0, 0.0],
            radiusOrigin=0.2, radiusEnd=1.0), n=400)
        low = [math.hypot(p.x, p.z) for p in pts if p.y < -5.0]
        high = [math.hypot(p.x, p.z) for p in pts if p.y > 5.0]
        self.assertTrue(low and high)
        self.assertLess(max(low), min(high) + 1e-6)     # 两端半径不重叠
        self.assertLess(max(low), 4.0)                  # 底部约 0.2 倍
        self.assertGreater(max(high), 8.0)              # 顶部约 1.0 倍

    def test_radius_default_is_a_plain_cylinder(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[0.0, 10.0, 0.0, 0.0, 0.0, 10.0]))
        radii = [math.hypot(p.x, p.z) for p in pts]
        self.assertGreater(min(radii), 0.0)
        self.assertLessEqual(max(radii), 10.0 + 1e-6)

    # ── 其余 ─────────────────────────────────────────────────────────────────
    def test_point_shape_is_a_single_spot(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=3, rangeXYZ=[0.0, 2.0, 1.0, 3.0, 2.0, 4.0]))
        for p in pts:
            self.assertEqual(p, Vec3(0, 1, 2))   # 点：恒在偏移处

    def test_local_rotation_is_applied(self):
        pts = self._spawn_many(es3d_fields(
            shapeType=0, rangeXYZ=[0.0, 10.0, 0.0, 0.0, 0.0, 0.0],
            localRotationZ=90.0), n=50)
        self.assertLess(max(abs(p.x) for p in pts), 1e-6)   # X 轴的盒子被转到 Y 上
        self.assertGreater(max(abs(p.y) for p in pts), 1.0)


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
        es3d = es3d_fields(shapeType=1, rangeXYZ=[0, 10, 0, 10, 0, 10])
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
            es3d=es3d_fields(shapeType=1, rangeXYZ=[0, 5, 0, 5, 0, 5]),
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
            es3d=es3d_fields(shapeType=1, rangeXYZ=[0, 5, 0, 5, 0, 5]),
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

class TestScaleAnimTimings(unittest.TestCase):
    """用户在 test.efx（BILLBOARD3D scale=30 / width=height=1）上的三条计时。

    结论：两组速度都是**每帧加在同名尺寸字段上**——逐轴那组加 width/height，
    整体那组加 scale。同为 -0.1 差 30 倍，就是 1 与 30 的差距。
    """

    def _frames_to_vanish(self, scaleanim, limit=600):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=1, burstInterval=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(scale=30.0, width=1.0, height=1.0),
                       scaleanim=scaleanim)
        for n in range(1, limit + 1):
            sim.step()
            items = sim.build_render()
            if items and items[0].size.x <= 1e-9:   # 0.1 累加十次会剩个 1e-16
                return n
        return None

    def test_axis_speed_adds_to_width(self):
        """scaleSpeedX=-0.1 → width 1→0，10 帧；-0.01 → 100 帧。"""
        self.assertEqual(self._frames_to_vanish(
            scaleanim_fields(scaleSpeedX=-0.1)), 10)
        self.assertEqual(self._frames_to_vanish(
            scaleanim_fields(scaleSpeedX=-0.01)), 100)

    def test_initial_speed_adds_to_scale(self):
        """initialScaleSpeed=-0.1 → scale 30→0，300 帧（= 5 秒 @60fps）。"""
        self.assertEqual(self._frames_to_vanish(
            scaleanim_fields(initialScaleSpeed=-0.1)), 300)

    def test_multiplier_mode_is_still_available(self):
        """'multiplier'（改动前的行为）：两组都按归一化倍率，30 倍的差距就没了。"""
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=1, burstInterval=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(scale=30.0, width=1.0, height=1.0),
                       scaleanim=scaleanim_fields(initialScaleSpeed=-0.1),
                       config=SimConfig(scaleanim_add_target="multiplier"))
        for _ in range(10):
            sim.step()
        self.assertAlmostEqual(sim.build_render()[0].size.x, 0.0, places=5)


class TestRgbColoring(unittest.TestCase):
    """RGBFIRE / RGBWATER：两层颜色 + 各自的生命期时序块。"""

    def _color(self, block_hash, fields, frames=1, config=None):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=1, burstInterval=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(block_hash, fields)], config=config)
        sim.run(frames)
        return sim.particles[0]

    # ── RGBFIRE ──────────────────────────────────────────────────────────────
    def test_two_layers_are_weighted_together(self):
        """两层强度相等 → 取中间色（红 + 蓝 → 半红半蓝）。"""
        p = self._color(RGBFIRE, rgbfire_fields())
        self.assertAlmostEqual(p.color[0], 0.5, places=5)
        self.assertAlmostEqual(p.color[1], 0.0, places=5)
        self.assertAlmostEqual(p.color[2], 0.5, places=5)

    def test_brightness1_zero_turns_the_fire_layer_off(self):
        """brightness1=0 → 只剩 smokeColor（语料证据见 behaviors/rgbfire.py）。"""
        p = self._color(RGBFIRE, rgbfire_fields(brightness1=0.0))
        self.assertAlmostEqual(p.color[0], 0.0, places=5)
        self.assertAlmostEqual(p.color[2], 1.0, places=5)

    def test_color_rate_scales_the_tint(self):
        p = self._color(RGBFIRE, rgbfire_fields(brightness2=2.0))
        self.assertAlmostEqual(p.color[0], 1.0, places=5)
        self.assertAlmostEqual(p.color[2], 1.0, places=5)

    def test_tint_mode_can_force_one_layer(self):
        for mode, want in (("first", (1.0, 0.0)), ("second", (0.0, 1.0))):
            with self.subTest(mode=mode):
                p = self._color(RGBFIRE, rgbfire_fields(),
                                config=SimConfig(rgb_tint_mode=mode))
                self.assertAlmostEqual(p.color[0], want[0], places=5)
                self.assertAlmostEqual(p.color[2], want[1], places=5)

    def test_color_param_life_fades_a_layer_out(self):
        """fire 段 useLife=1、持续 10 帧后 10 帧淡出 → 火焰权重 1 → 0.5 → 0。"""
        f = rgbfire_fields(fireColorParam_useLife=1, fireColorParam_keepFrame=10,
                           fireColorParam_vanishFrame=10)
        red = lambda n: self._color(RGBFIRE, f, frames=n).color[0]
        self.assertAlmostEqual(red(6), 0.5, places=5)       # age 5：两层等权
        self.assertAlmostEqual(red(16), 0.5 / 1.5, places=5)  # age 15：火焰权重 0.5
        self.assertAlmostEqual(red(26), 0.0, places=5)      # age 25：火焰已淡尽

    def test_life_off_means_the_timings_are_inert(self):
        """useLife=0 时那几个帧数字段不生效（语料里它们常停在 20/40 的默认值上）。"""
        f = rgbfire_fields(fireColorParam_keepFrame=1, fireColorParam_vanishFrame=1)
        self.assertAlmostEqual(self._color(RGBFIRE, f, frames=60).color[0], 0.5,
                               places=5)

    # ── RGBWATER ─────────────────────────────────────────────────────────────
    def test_water_weights_come_from_named_intensities(self):
        """intensitySpecular=3 / intensitySheet=1 → 高光色占 3/4。"""
        p = self._color(RGBWATER, rgbwater_fields(intensitySpecular=3.0))
        self.assertAlmostEqual(p.color[0], 0.75, places=5)
        self.assertAlmostEqual(p.color[2], 0.25, places=5)

    def test_intensity_alpha_multiplies_and_clamps(self):
        p = self._color(RGBWATER, rgbwater_fields(intensityAlpha=2.0))
        self.assertAlmostEqual(p.alpha, 1.0, places=5)
        q = self._color(RGBWATER, rgbwater_fields(intensityAlpha=0.25))
        self.assertAlmostEqual(q.alpha, 0.25, places=5)


class TestAlphaCorrection(unittest.TestCase):
    """只往渲染项上挂参数——逐纹素的处理在 glue 的 fragment shader 里。"""

    def _item(self, **kw):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=1, burstInterval=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(ALPHACORRECTION, alphacorrection_fields(**kw))])
        sim.run(2)
        return sim.build_render()[0]

    def test_params_ride_on_the_render_item(self):
        it = self._item(lowPass=0.25, contrast_gamma=2.0)
        self.assertEqual(it.extra["alpha_fix"], (0.25, 2.0))

    def test_neutral_values_attach_nothing(self):
        """两项都中性 → 不挂，免得 glue 白白多分一个 draw 桶。"""
        self.assertNotIn("alpha_fix", self._item().extra)

    def test_zero_gamma_is_treated_as_neutral(self):
        """pow(a, 0) 会把整片贴成全不透明；语料 7488 个块里只有 12 个是 0。"""
        self.assertNotIn("alpha_fix", self._item(contrast_gamma=0.0).extra)
        self.assertEqual(self._item(lowPass=0.3, contrast_gamma=0.0).extra["alpha_fix"],
                         (0.3, 1.0))

    def test_particle_alpha_is_untouched(self):
        """这是逐纹素的操作，不该整体乘个 alpha。"""
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=1, burstInterval=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(ALPHACORRECTION,
                               alphacorrection_fields(lowPass=0.9, contrast_gamma=9.0))])
        sim.run(2)
        self.assertAlmostEqual(sim.particles[0].alpha, 1.0, places=5)


class TestRotateAnim(unittest.TestCase):

    #: 游戏给的角速度写进 p.rot 时取负（实机：z=+5 在 Blender 里是从 -Y 看的顺时针）
    SIGN = -1.0

    def test_plane_mode_accumulates_on_z(self):
        """平面旋转 = 屏幕空间自转，写 Z。"""
        p, _ = one_particle(frames=4, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=15.0))
        self.assertAlmostEqual(p.rot.z, self.SIGN * 60.0, places=6)
        self.assertEqual((p.rot.x, p.rot.y), (0.0, 0.0))

    def test_plane_coef_decays_the_speed(self):
        p, _ = one_particle(frames=5, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, billboardRotationCoef=0.5))
        self.assertAlmostEqual(p.rot.z,
                               self.SIGN * sum(10.0 * 0.5 ** n for n in range(5)),
                               places=6)

    def test_spin_mode_uses_all_three_axes(self):
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=2, spin_velocity=[1.0, 0.0, 2.0, 0.0, 3.0, 0.0]))
        self.assertAlmostEqual(p.rot.x, self.SIGN * 3.0, places=6)
        self.assertAlmostEqual(p.rot.y, self.SIGN * 6.0, places=6)
        self.assertAlmostEqual(p.rot.z, self.SIGN * 9.0, places=6)

    def test_axes_without_speed_do_not_spin(self):
        """转不转只看 spin_velocity 的逐轴取值——**不看 spinAxisMask**
        （那个字段的位布局与全语料对不上，作用未知，见 behaviors/rotateanim.py）。"""
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=2, spin_velocity=[0.0, 0.0, 2.0, 0.0, 0.0, 0.0]))
        self.assertEqual(p.rot.x, 0.0)
        self.assertAlmostEqual(p.rot.y, self.SIGN * 6.0, places=6)
        self.assertEqual(p.rot.z, 0.0)

    def test_spin_ignores_the_axis_mask(self):
        """菱形那条的实况：mask=16（旧读法一位都不命中）但 Z 轴确实在转。"""
        p, _ = one_particle(frames=4, rotateanim=rotateanim_fields(
            rotationModeMask=2, spinAxisMask=16,
            spin_velocity=[0.0, 0.0, 0.0, 0.0, 5.0, 0.0]))
        self.assertAlmostEqual(p.rot.z, self.SIGN * 20.0, places=6)

    def test_delay_holds_rotation(self):
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, rotateDelayStart=5))
        self.assertEqual(p.rot.z, 0.0)
        p, _ = one_particle(frames=8, rotateanim=rotateanim_fields(
            rotationModeMask=0, billboardRotation=10.0, rotateDelayStart=5))
        self.assertAlmostEqual(p.rot.z, self.SIGN * 30.0, places=6)  # 第 5..7 帧共 3 次

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
        signs = {1 if p.rot.z > 0 else -1 for p in sim.particles}
        self.assertEqual(len(signs), 1)

    def test_plane_spin_reaches_the_plane_body(self):
        """PLANE 的横/纵轴要真的跟着转——渲染体不消费 p.rot 的话，改了也看不见。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(
                           rotationModeMask=2, spinAxisMask=16,
                           spin_velocity=[0.0, 0.0, 0.0, 0.0, 5.0, 0.0]),
                       extra=[(PLANE, plane_fields(baseAxis=2))])
        sim.step()
        u0 = sim.build_render()[0].axis_u.copy()
        for _ in range(9):
            sim.step()
        u1 = sim.build_render()[0].axis_u
        self.assertGreater((u1 - u0).length(), 0.1)      # 转过去了
        self.assertAlmostEqual(u1.length(), 1.0, places=5)


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
        # 60/秒 = 1/帧
        base = dict(translation_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])
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
                translation_velocity=[120.0, 0.0, 0.0, 0.0, 0.0, 0.0]),   # 2/帧
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
                translation_velocity=[30.0, 0.0, 0.0, 0.0, 0.0, 0.0]),    # 0.5/帧
            spawn=spawn_fields(burstInterval=1000),
            life=life_fields(indefiniteLifespan=1),
            velocity=velocity_fields(velocityType=3, speed=1.0,
                                     minMovementThreshold=10.0))
        sim.run(3)
        self.assertEqual(sim.particles[0].vel, Vec3())

    def test_rotation_sign_can_be_taken_raw(self):
        """'raw' = 照字面符号（改动前的行为）。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               rotation_velocity=[0.0, 0.0, 600.0, 0.0, 0.0, 0.0])
        sim = make_sim(transform=t, spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       config=SimConfig(t3d_rotation_sign="raw"))
        sim.run(10)
        self.assertAlmostEqual(sim.em.rot_dynamic.y, 100.0, places=4)

    def test_velocities_are_per_second(self):
        """三组速度都是每秒（语料证据见 behaviors/transform3d.py）：
        每秒 60 → 每帧 1；`per_frame` 开关下退回改动前的读法。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               translation_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                               rotation_velocity=[0.0, 0.0, 600.0, 0.0, 0.0, 0.0],
                               scale_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        kw = dict(spawn=spawn_fields(burstInterval=1000),
                  life=life_fields(indefiniteLifespan=1))
        sec = make_sim(transform=t, **kw)
        sec.run(10)
        self.assertAlmostEqual(sec.em.origin.x, 10.0, places=5)       # 1/帧 × 10
        # 10°/帧 × 10；符号取反（见 t3d_rotation_sign，默认 'flip'）
        self.assertAlmostEqual(sec.em.rot_dynamic.y, -100.0, places=4)
        self.assertAlmostEqual(sec.em.scale_dynamic.x, 11.0, places=4)  # 1 + 1/帧 × 10

        frm = make_sim(transform=t, config=SimConfig(t3d_velocity_unit="per_frame"),
                       **kw)
        frm.run(10)
        self.assertAlmostEqual(frm.em.origin.x, 600.0, places=3)      # 旧读法快 60 倍

    def test_negative_scale_velocity_stops_at_zero(self):
        """缩放倍率不能穿过 0 变负——负倍率等于把生成形状镜像翻过去，
        表现上粒子会从收缩变成朝外飞（05 spell 那条就是这么暴露的）。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               scale_velocity=[-60.0, 0.0, -60.0, 0.0, -60.0, 0.0])
        sim = make_sim(transform=t, spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.run(30)                                   # 每帧 -1，30 帧远远穿过 0
        for v in sim.em.scale_dynamic:
            self.assertGreaterEqual(v, 0.0)
        self.assertAlmostEqual(sim.em.scale_dynamic.x, 0.0, places=6)

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
        # 初始角来自 BILLBOARD3D.rotation（原样），ROTATEANIM 的角速度取负叠加
        self.assertAlmostEqual(it.rot, 45.0 - 30.0, places=6)

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


# ─────────────────────────────────────────────────────────────────────────────
# 轨迹工具
# ─────────────────────────────────────────────────────────────────────────────

class TestColorAndAlpha(unittest.TestCase):
    """color / colorRange 是 RGBA 四元组的 static/random 对（逐通道独立），
    第 4 通道当 alpha 用并乘上 LIFE 的淡入淡出。"""

    BLACK = [0, 0, 0, 0]
    WHITE = [255, 255, 255, 255]

    def _sim(self, n=40, config=None, life=None, **bb):
        f = billboard_fields(**bb)
        return make_sim(spawn=spawn_fields(particlesPerBurst=n, burstInterval=1000),
                        life=life or life_fields(indefiniteLifespan=1),
                        billboard=f, config=config)

    def _items(self, **kw):
        sim = self._sim(**kw)
        sim.step()
        return sim.build_render()

    def test_range_off_uses_the_static_color(self):
        items = self._items(color=[128, 64, 32, 255], colorRange=self.WHITE,
                            useColorRange=0)
        for it in items:
            self.assertAlmostEqual(it.color[0], 128 / 255.0, places=5)
            self.assertAlmostEqual(it.color[1], 64 / 255.0, places=5)
            self.assertAlmostEqual(it.color[2], 32 / 255.0, places=5)

    def test_each_channel_draws_independently(self):
        """默认 'channel'：四个通道各自抽，所以同一个粒子的 R/G/B 会不一样。"""
        items = self._items(color=list(self.BLACK), colorRange=list(self.WHITE),
                            useColorRange=1)
        self.assertGreater(len({tuple(it.color) for it in items}), 1)   # 粒子之间不同
        self.assertTrue(any(abs(it.color[0] - it.color[1]) > 1e-6 for it in items))

    def test_shared_mode_keeps_channels_locked(self):
        cfg = SimConfig(color_range_mode="shared")
        items = self._items(color=list(self.BLACK), colorRange=list(self.WHITE),
                            useColorRange=1, config=cfg)
        for it in items:                       # 端点三通道相同 + 共用系数 → R=G=B
            self.assertAlmostEqual(it.color[0], it.color[1], places=6)
            self.assertAlmostEqual(it.color[1], it.color[2], places=6)

    def test_values_stay_between_the_two_endpoints(self):
        items = self._items(color=[100, 100, 100, 255], colorRange=[200, 200, 200, 255],
                            useColorRange=1)
        for it in items:
            for c in it.color[:3]:
                self.assertGreaterEqual(c, 100 / 255.0 - 1e-6)
                self.assertLessEqual(c, 200 / 255.0 + 1e-6)

    def test_alpha_participates_in_the_draw(self):
        items = self._items(color=[255, 255, 255, 0],
                            colorRange=[255, 255, 255, 255], useColorRange=1)
        alphas = {round(it.color[3], 6) for it in items}
        self.assertGreater(len(alphas), 1)                     # alpha 真的在随机
        self.assertTrue(all(0.0 <= a <= 1.0 for a in alphas))

    def test_alpha_is_clamped_to_one(self):
        cfg = SimConfig(color_range_mode="add")
        items = self._items(color=list(self.WHITE), colorRange=list(self.WHITE),
                            useColorRange=1, config=cfg)
        self.assertTrue(all(it.color[3] <= 1.0 + 1e-9 for it in items))

    def test_add_mode_is_additive(self):
        cfg = SimConfig(color_range_mode="add")
        items = self._items(color=[100, 100, 100, 255], colorRange=[100, 100, 100, 0],
                            useColorRange=1, config=cfg)
        for it in items:                       # 100/255 起，最多再加 100/255
            self.assertGreaterEqual(it.color[0], 100 / 255.0 - 1e-6)
            self.assertLessEqual(it.color[0], 200 / 255.0 + 1e-6)

    def test_life_fade_multiplies_the_colour_alpha(self):
        """LIFE 的淡入 × 颜色自带的 alpha —— 两者相乘，不是二选一。"""
        life = life_fields(fadeInDuration=10, duration=50, fadeOutDuration=0)
        sim = make_sim(spawn=spawn_fields(burstInterval=1000), life=life,
                       billboard=billboard_fields(color=[255, 255, 255, 128],
                                                  useColorRange=0))
        for _ in range(6):
            sim.step()
        it = sim.build_render()[0]
        p = sim.particles[0]
        self.assertLess(p.alpha, 1.0)                          # 还在淡入
        self.assertAlmostEqual(it.color[3], (128 / 255.0) * p.alpha, places=5)

    def test_same_seed_same_colours(self):
        a = [tuple(it.color) for it in self._items(
            color=list(self.BLACK), colorRange=list(self.WHITE), useColorRange=1,
            config=SimConfig(seed=3))]
        b = [tuple(it.color) for it in self._items(
            color=list(self.BLACK), colorRange=list(self.WHITE), useColorRange=1,
            config=SimConfig(seed=3))]
        c = [tuple(it.color) for it in self._items(
            color=list(self.BLACK), colorRange=list(self.WHITE), useColorRange=1,
            config=SimConfig(seed=4))]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_timl_reread_keeps_the_same_draw(self):
        """挂了 TIML 的块逐帧重解静态色，但要用出生时那组系数——不能每帧重抽。"""
        from efx_format.sim.behaviors._common import pick_color

        sim = self._sim(n=4, config=SimConfig(seed=9),
                        color=list(self.BLACK), colorRange=list(self.WHITE),
                        useColorRange=1)
        sim.step()
        for p, it in zip(sim.particles, sim.build_render()):
            f = sim.em.f(BILLBOARD3D, p)
            again = pick_color(f, p.rolled["bb_coff"])
            bright = p.rolled["bb_bright"]
            for i in range(3):
                self.assertAlmostEqual(again[i] * bright, it.color[i], places=6)

    def test_mesh_disable_all_colour_range(self):
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=8, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(MESH, mesh_fields(color=list(self.BLACK),
                                                 colorRange=list(self.WHITE),
                                                 useColorRange=1,
                                                 disableAllColorRange=1))])
        sim.step()
        for it in sim.build_render():
            for c in it.color[:3]:
                self.assertAlmostEqual(c, 0.0, places=6)

    def test_plane_and_ribbon_share_the_model(self):
        for tag, hash_, fields in (("plane", PLANE, plane_fields),
                                   ("ribbon", RIBBON, ribbon_fields)):
            with self.subTest(body=tag):
                kw = dict(color=list(self.BLACK), colorRange=list(self.WHITE),
                          useColorRange=1)
                if tag == "ribbon":
                    kw["ribbonMode"] = 1        # 定长面片：静止也画得出来
                sim = make_sim(
                    spawn=spawn_fields(particlesPerBurst=30, burstInterval=1000),
                    life=life_fields(indefiniteLifespan=1),
                    extra=[(hash_, fields(**kw))])
                sim.step()
                cols = {tuple(it.color) for it in sim.build_render()}
                self.assertGreater(len(cols), 1)


class TestPtLifeActionScene(unittest.TestCase):
    """PTLIFE 在某个生命阶段触发 ACTION → SimScene 建子实例；
    子实例跟着父粒子走，父粒子消亡后失去 parent 就地留下（用户实机）。"""

    def _scene(self, ptlife=None, parent_life=None, child_life=None,
               parent_velocity=None, targets=None, config=None, actions=None):
        """两个 entry：0 = 父（带 PTLIFE），1 = 子（一个静止的 billboard）。"""
        parent_blocks = [
            (SPAWN, spawn_fields(burstInterval=1000)),
            (LIFE, parent_life or life_fields(duration=10)),
            (PTLIFE, ptlife or ptlife_fields()),
            (BILLBOARD3D, billboard_fields()),
        ]
        if parent_velocity is not None:
            parent_blocks.append((VELOCITY3D, parent_velocity))
        child_blocks = [
            (SPAWN, spawn_fields(burstInterval=1000)),
            (LIFE, child_life or life_fields(indefiniteLifespan=1)),
            (BILLBOARD3D, billboard_fields()),
        ]
        templates = {0: EntryTemplate(0, parent_blocks),
                     1: EntryTemplate(1, child_blocks)}
        if actions is None:
            actions = {0: list(targets or [ActionTarget(1)])}
        return SimScene(templates, actions, root_key=0,
                        config=config or SimConfig(seed=1))

    # ── 基本联动 ─────────────────────────────────────────────────────────────
    def test_ptlife_is_simulated(self):
        sc = self._scene()
        sc.step()
        self.assertNotIn("PTLIFE", [n for _h, n in sc.unsupported])

    def test_on_spawn_creates_a_child_instance(self):
        sc = self._scene(ptlife=ptlife_fields(status=0))
        self.assertEqual(sc.instance_count, 1)       # 只有根
        sc.step()                                     # 第 0 帧生粒子 → 请求
        sc.step()                                     # 子实例开始跑
        self.assertEqual(sc.instance_count, 2)
        self.assertEqual(sc.instances[1].key, 1)

    def test_relation_index_minus_one_does_nothing(self):
        sc = self._scene(ptlife=ptlife_fields(relationIndex=-1))
        sc.run(5)
        self.assertEqual(sc.instance_count, 1)
        self.assertTrue(any("-1" in n for n in sc.notes))

    def test_each_particle_triggers_once(self):
        sc = self._scene(ptlife=ptlife_fields(status=0))
        sc.run(20)
        # 一个粒子 → 一个子实例，不会每帧刷一个
        self.assertEqual(sc.instance_count, 2)

    def test_on_death_fires_at_the_end_of_life(self):
        sc = self._scene(ptlife=ptlife_fields(status=4),
                         parent_life=life_fields(duration=5))
        sc.run(4)
        self.assertEqual(sc.instance_count, 1)        # 还活着，没触发
        sc.run(4)
        self.assertEqual(sc.instance_count, 2)        # 死了 → 触发

    def test_sustain_fires_after_fade_in(self):
        sc = self._scene(ptlife=ptlife_fields(status=2),
                         parent_life=life_fields(fadeInDuration=6, duration=40))
        sc.run(4)
        self.assertEqual(sc.instance_count, 1)
        sc.run(6)
        self.assertEqual(sc.instance_count, 2)

    # ── 跟随 / 断链（用户实机确认的那条）──────────────────────────────────────
    def test_child_follows_the_parent_particle(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         parent_velocity=velocity_fields(baseAxis=1, speed=4.0))
        sc.run(12)
        child = sc.instances[1]
        parent_p = sc.root.sim.em.particles[0]
        self.assertFalse(child.detached)
        self.assertAlmostEqual(child.em.host_origin.y, parent_p.pos.y, places=4)
        self.assertGreater(parent_p.pos.y, 10.0)      # 父粒子确实在动

    def test_child_detaches_when_the_parent_dies(self):
        """父粒子消亡 → 子实例继续存在，但不再跟随，就地留下。"""
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(duration=8),
                         parent_velocity=velocity_fields(baseAxis=1, speed=4.0),
                         child_life=life_fields(indefiniteLifespan=1))
        sc.run(6)
        child = sc.instances[1]
        self.assertFalse(child.detached)               # 父粒子还活着 → 还在跟
        self.assertGreater(child.em.host_origin.y, 0.0)

        while not child.detached and sc.frame < 60:     # 跑到父粒子消亡
            sc.run(1)
        self.assertTrue(child.detached)
        frozen_at = child.em.host_origin.copy()

        sc.run(20)                                     # 断链之后再跑一段
        self.assertIn(child, sc.instances)             # 子实例还在
        self.assertAlmostEqual(child.em.host_origin.y, frozen_at.y, places=4)
        self.assertTrue(child.em.particles)            # 自己的粒子照常演

    def test_child_particles_show_up_in_render(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         child_life=life_fields(indefiniteLifespan=1))
        sc.run(10)
        self.assertGreaterEqual(len(sc.build_render()), 2)   # 父 1 + 子 1
        self.assertGreaterEqual(len(sc.particles), 2)

    # ── Action 的 Size / Position ────────────────────────────────────────────
    def test_action_position_offsets_the_child(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         targets=[ActionTarget(1, position=Vec3(0.0, 50.0, 0.0))])
        sc.run(4)
        child = sc.instances[1]
        parent_p = sc.root.sim.em.particles[0]
        self.assertAlmostEqual(child.em.host_origin.y, parent_p.pos.y + 50.0, places=4)

    def test_action_size_scales_the_child_emitter(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         targets=[ActionTarget(1, size=Vec3(2.0, 2.0, 2.0))])
        sc.run(3)
        self.assertAlmostEqual(sc.instances[1].em.scale_dynamic.x, 2.0, places=5)

    # ── 安全阀 ───────────────────────────────────────────────────────────────
    def test_depth_limit_stops_recursion(self):
        """自指的 action（entry 0 触发指向自己的 action）→ 靠深度上限收住。"""
        blocks = [
            (SPAWN, spawn_fields(burstInterval=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (PTLIFE, ptlife_fields(status=0)),
            (BILLBOARD3D, billboard_fields()),
        ]
        sc = SimScene({0: EntryTemplate(0, blocks)}, {0: [ActionTarget(0)]},
                      root_key=0, config=SimConfig(seed=1, max_spawn_depth=2))
        sc.run(30)
        self.assertLessEqual(max(i.depth for i in sc.instances), 2)
        self.assertTrue(any("max_spawn_depth" in n for n in sc.notes))

    def test_instance_budget(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         child_life=life_fields(indefiniteLifespan=1),
                         config=SimConfig(seed=1, max_instances=3),
                         actions={0: [ActionTarget(1), ActionTarget(1),
                                      ActionTarget(1), ActionTarget(1)]})
        sc.run(6)
        self.assertLessEqual(sc.instance_count, 3)
        self.assertTrue(any("max_instances" in n for n in sc.notes))

    def test_missing_target_entry_is_reported(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         targets=[ActionTarget(99)])
        sc.run(4)
        self.assertEqual(sc.instance_count, 1)
        self.assertTrue(any("99" in n for n in sc.notes))

    def test_idle_children_get_culled(self):
        """子实例的粒子演完 → 空转一段时间后回收，别无限堆着。"""
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         child_life=life_fields(duration=3),
                         config=SimConfig(seed=1, child_cull_grace=5))
        sc.run(6)
        self.assertEqual(sc.instance_count, 2)
        sc.run(40)
        self.assertEqual(sc.instance_count, 1)       # 只剩根

    # ── 确定性 ───────────────────────────────────────────────────────────────
    def test_same_seed_same_tree(self):
        def run(seed):
            sc = self._scene(ptlife=ptlife_fields(status=0),
                             parent_life=life_fields(indefiniteLifespan=1),
                             child_life=life_fields(indefiniteLifespan=1),
                             config=SimConfig(seed=seed))
            sc.run(15)
            return [(i.key, i.depth, round(i.em.host_origin.y, 5))
                    for i in sc.instances]

        self.assertEqual(run(5), run(5))

    def test_reset_rebuilds_from_scratch(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1))
        sc.run(10)
        self.assertEqual(sc.instance_count, 2)
        sc.reset()
        self.assertEqual(sc.instance_count, 1)
        self.assertEqual(sc.frame, -1)


class TestParentOptions(unittest.TestCase):
    """跟随发射器 + 停止追踪帧数（其余字段刻意未实现，只 note）。"""

    def _sim(self, parent=None, frames=10, drift=(0.0, 0.0, 0.0), **kw):
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        kw.setdefault("transform", drifting_emitter(*drift))
        extra = list(kw.pop("extra", ()))
        extra.append((PARENTOPTIONS, parent or parentoptions_fields()))
        sim = make_sim(extra=extra, **kw)
        for _ in range(frames):
            sim.step()
        return sim

    def test_parentoptions_is_simulated(self):
        sim = self._sim()
        self.assertNotIn("PARENTOPTIONS", [n for _h, n in sim.unsupported])

    def test_without_follow_particles_keep_their_birth_origin(self):
        """关着「跟随发射器」→ 粒子只认出生那一刻的原点。"""
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=0),
                        drift=(5.0, 0.0, 0.0), frames=10)
        p = sim.particles[0]
        # 第 0 帧发射器已经走了一步（5），粒子就生在那儿，之后再也不动
        self.assertAlmostEqual(p.pos.x, 5.0, places=5)
        self.assertGreater(sim.em.origin.x, 40.0)           # 发射器确实走了

    def test_follow_carries_existing_particles(self):
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1),
                        drift=(5.0, 0.0, 0.0), frames=10)
        p = sim.particles[0]
        self.assertAlmostEqual(p.pos.x, sim.em.origin.x, places=4)

    def test_follow_adds_on_top_of_the_particles_own_motion(self):
        """跟随是**加增量**，不是每帧重置到发射器身上——粒子自己的速度要保住。"""
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1),
                        drift=(5.0, 0.0, 0.0), frames=10,
                        velocity=velocity_fields(baseAxis=1, speed=3.0))  # 自己朝 +Y 飞
        p = sim.particles[0]
        self.assertAlmostEqual(p.pos.x, sim.em.origin.x, places=4)   # 跟着发射器横移
        self.assertGreater(p.pos.y, 20.0)                            # 自己的运动没丢

    def test_const_release_stops_the_tracking(self):
        """停止追踪帧数 = 5 → 只跟 5 帧，之后就地锁定。"""
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    constRelease=5),
                        drift=(5.0, 0.0, 0.0), frames=20)
        p = sim.particles[0]
        self.assertAlmostEqual(p.pos.x, 25.0, delta=5.1)     # 5 帧 × 5/帧
        self.assertLess(p.pos.x, sim.em.origin.x - 40.0)     # 发射器早就跑远了

    def test_const_release_zero_means_always(self):
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    constRelease=0),
                        drift=(5.0, 0.0, 0.0), frames=20)
        self.assertAlmostEqual(sim.particles[0].pos.x, sim.em.origin.x, places=4)

    def test_release_clock_can_follow_the_emitter_timeline(self):
        cfg = SimConfig(parent_release_clock="emitter_frame")
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    constRelease=5),
                        drift=(5.0, 0.0, 0.0), frames=20, config=cfg)
        self.assertAlmostEqual(sim.particles[0].pos.x, 25.0, delta=5.1)

    def test_unhandled_tracking_modes_are_reported(self):
        sim = self._sim(parent=parentoptions_fields(relationPos=[1, 0, 0]))
        self.assertTrue(any("relationPos" in n for n in sim.notes))


class TestEmitterRotationReachesParticles(unittest.TestCase):
    """TRANSFORM3D 的 rotation_velocity / scale_velocity 要真的作用到发出去的东西上
    （在这之前 em.rotation/em.scale 只是累积着没人用）。"""

    def _spawn_at(self, transform, frames=4, es3d=None, velocity=None):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000, emitterStartDelay=3),
                       life=life_fields(indefiniteLifespan=1),
                       transform=transform,
                       es3d=es3d, velocity=velocity)
        for _ in range(frames):
            sim.step()
        return sim

    #: 一个定点生成方式：rangeXYZ 的 min==max → 采样点恒为 (10,0,0)
    #: 一个定点生成方式：偏移 X=10、尺寸全 0 → 采样点恒在 (±10, 0, 0) 的球壳退化点上
    FIXED_POINT = dict(shapeType=1, rangeXYZ=[10.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_spawn_offset_follows_emitter_rotation(self):
        """发射器的动态旋转要作用到「它发出去的东西」上。

        直接驱动 `_common.emitter_place`（生成方式的采样点就是过它落地的），
        而不是借某个形状的随机采样——那样断言会被形状的随机性糊掉。
        """
        from efx_format.sim.behaviors._common import emitter_place

        still = self._spawn_at(spinning_emitter(0.0))
        spun = self._spawn_at(spinning_emitter(30.0))
        v = Vec3(10.0, 0.0, 0.0)
        a = emitter_place(still.em, v)
        b = emitter_place(spun.em, v)
        self.assertAlmostEqual(a.x, 10.0, places=4)
        self.assertAlmostEqual(a.length(), b.length(), places=4)   # 只转不缩
        self.assertGreater((a - b).length(), 1.0)                  # 真的转了

        order = rot_order_name(4, ROT_ORDER_TRANSFORM)
        expect = rotate_euler(v, 0.0, spun.em.rot_dynamic.y, 0.0, order=order)
        self.assertAlmostEqual(b.x, expect.x, places=3)
        self.assertAlmostEqual(b.z, expect.z, places=3)

    def test_initial_velocity_follows_emitter_rotation(self):
        vel = velocity_fields(baseAxis=1, speed=5.0)               # 自身朝 +Y
        still = self._spawn_at(spinning_emitter(0.0), velocity=vel)
        spun = self._spawn_at(spinning_emitter(30.0), velocity=vel)
        a = still.particles[0].vel
        b = spun.particles[0].vel
        self.assertAlmostEqual(a.length(), b.length(), places=4)
        # 绕 Y 转不动 +Y 本身 —— 换成朝 +X 的初速度才看得出差别
        vel_x = velocity_fields(baseAxis=0, speed=5.0)
        a2 = self._spawn_at(spinning_emitter(0.0), velocity=vel_x).particles[0].vel
        b2 = self._spawn_at(spinning_emitter(30.0), velocity=vel_x).particles[0].vel
        self.assertGreater((a2 - b2).length(), 1.0)

    def test_static_rotation_is_left_to_the_host(self):
        """t3d_apply_base 关着（默认）→ 静态 rotate 不进 rot_dynamic，
        否则 Blender 里会和 entry 矩阵双份旋转。"""
        from efx_format.sim.behaviors._common import emitter_place

        t = transform3d_fields(rotate=[90.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._spawn_at(t)
        self.assertAlmostEqual(sim.em.rot_dynamic.x, 0.0, places=6)
        # 动态部分为零 → 生成点原样不动（静态旋转由宿主的 entry 矩阵负责）
        placed = emitter_place(sim.em, Vec3(10.0, 0.0, 0.0))
        self.assertAlmostEqual(placed.x, 10.0, places=4)
        self.assertAlmostEqual(placed.length(), 10.0, places=4)

    def test_scale_velocity_scales_the_spawn_offset(self):
        from efx_format.sim.behaviors._common import emitter_place

        t = transform3d_fields(enableVelocityBitflag=1,
                               scale_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # +1/帧
        sim = self._spawn_at(t)
        # 每帧 +1 → x 方向倍率 1+N
        expect = 10.0 * sim.em.scale_dynamic.x
        self.assertGreater(sim.em.scale_dynamic.x, 1.0)
        self.assertAlmostEqual(emitter_place(sim.em, Vec3(10.0, 0.0, 0.0)).x,
                               expect, places=4)


class TestTrailHelpers(unittest.TestCase):

    def setUp(self):
        from efx_format.sim import trail
        self.t = trail
        # 沿 X 每帧走 10：0,10,20,...,100
        self.line = [Vec3(i * 10.0, 0, 0) for i in range(11)]

    def test_clip_keeps_newest_end(self):
        out = self.t.clip_by_length(self.line, 25.0)
        self.assertEqual(out[0], Vec3(100, 0, 0))          # 新→旧
        self.assertAlmostEqual(out[-1].x, 75.0, places=6)  # 恰好截断 25

    def test_clip_interpolates_the_cut(self):
        """截断点落在段中间时插值，条带长度才是连续变化的。"""
        out = self.t.clip_by_length(self.line, 15.0)
        self.assertAlmostEqual(out[-1].x, 85.0, places=6)

    def test_clip_longer_than_trail_returns_all(self):
        out = self.t.clip_by_length(self.line, 9999.0)
        self.assertEqual(len(out), 11)

    def test_resample_is_arc_length_uniform(self):
        pts = self.t.resample(self.line, 6)
        self.assertEqual(len(pts), 6)
        gaps = [(pts[i + 1] - pts[i]).length() for i in range(5)]
        for g in gaps:
            self.assertAlmostEqual(g, 20.0, places=4)

    def test_resample_degenerate_does_not_crash(self):
        self.assertEqual(self.t.resample([], 5), [])
        same = [Vec3(1, 1, 1)] * 4
        self.assertEqual(len(self.t.resample(same, 5)), 5)

    def test_straight(self):
        pts = self.t.straight(Vec3(), Vec3(0, 1, 0), 100.0, 5)
        self.assertEqual(len(pts), 5)
        self.assertAlmostEqual(pts[-1].y, 100.0, places=6)


class TestTrailRecording(unittest.TestCase):

    def test_not_recorded_unless_requested(self):
        """没有条带类渲染体就不记轨迹——那是白白的逐帧拷贝。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0))
        sim.run(10)
        self.assertEqual(sim.particles[0].trail, [])
        self.assertEqual(sim.em.trail, [])

    def test_recorded_when_a_body_needs_it(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0),
                       extra=[(RIBBON, ribbon_fields())])
        sim.run(10)
        # 两条轨迹都是每帧一个点：跑 10 帧 → 10 个点（粒子在第 0 帧出生）
        self.assertEqual(len(sim.particles[0].trail), 10)
        self.assertEqual(len(sim.em.trail), 10)

    def test_trail_is_capped(self):
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0),
                       extra=[(RIBBON, ribbon_fields())],
                       config=SimConfig(trail_max=8))
        sim.run(40)
        self.assertEqual(len(sim.particles[0].trail), 8)


# ─────────────────────────────────────────────────────────────────────────────
# DUMMY
# ─────────────────────────────────────────────────────────────────────────────

class TestDummy(unittest.TestCase):

    def test_draws_nothing_at_all(self):
        """DUMMY 是「无视觉输出的功能性宿主」——既不该画，也不该退化成点。"""
        sim = make_sim(spawn=spawn_fields(particlesPerBurst=5, burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(DUMMY, {"typeFlag": 1, "section_length": 1})])
        sim.run(5)
        self.assertEqual(len(sim.particles), 5)      # 粒子照常存在
        self.assertEqual(sim.build_render(), [])     # 但什么都不画

    def test_is_not_listed_as_unsupported(self):
        sim = make_sim(spawn=spawn_fields(), life=life_fields(),
                       extra=[(DUMMY, {"typeFlag": 1, "section_length": 1})])
        self.assertNotIn("DUMMY", [n for _h, n in sim.unsupported])

    def test_without_dummy_the_fallback_point_appears(self):
        """对照组：没有渲染体时才该出现退化点。"""
        sim = make_sim(spawn=spawn_fields(burstInterval=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.run(3)
        self.assertEqual([i.kind for i in sim.build_render()], ["POINT"])


# ─────────────────────────────────────────────────────────────────────────────
# PLANE
# ─────────────────────────────────────────────────────────────────────────────

class TestPlane(unittest.TestCase):

    def _item(self, frames=1, **kw):
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        sim = make_sim(extra=[(PLANE, kw.pop("plane"))], **kw)
        for _ in range(frames):
            sim.step()
        return sim.build_render()[0], sim

    def test_kind_and_fixed_orientation(self):
        """PLANE 给出自己的横/纵轴 → glue 不按相机朝向画。"""
        it, _ = self._item(plane=plane_fields())
        self.assertEqual(it.kind, "PLANE")
        self.assertIsNotNone(it.axis_u)
        self.assertIsNotNone(it.axis_v)

    def test_axes_are_orthonormal(self):
        it, _ = self._item(plane=plane_fields(baseAxis=2, rotation=[30, 0, 20, 0, 45, 0]))
        self.assertAlmostEqual(it.axis_u.length(), 1.0, places=6)
        self.assertAlmostEqual(it.axis_v.length(), 1.0, places=6)
        self.assertAlmostEqual(it.axis_u.dot(it.axis_v), 0.0, places=6)

    def test_base_axis_changes_the_plane(self):
        a, _ = self._item(plane=plane_fields(baseAxis=1))    # 上
        b, _ = self._item(plane=plane_fields(baseAxis=2))    # 前
        self.assertGreater((a.axis_u - b.axis_u).length()
                           + (a.axis_v - b.axis_v).length(), 1e-3)

    def test_rotation2_spins_within_the_plane(self):
        a, _ = self._item(plane=plane_fields(rotation2=0.0))
        b, _ = self._item(plane=plane_fields(rotation2=90.0))
        self.assertGreater((a.axis_u - b.axis_u).length(), 1.0)
        # 自旋不改变法线：u×v 应当一致
        na, nb = a.axis_u.cross(a.axis_v), b.axis_u.cross(b.axis_v)
        self.assertAlmostEqual((na - nb).length(), 0.0, places=5)

    def test_size_follows_billboard_convention(self):
        it, _ = self._item(plane=plane_fields(width=80.0, height=40.0, scale=0.5))
        self.assertAlmostEqual(it.size.x, 40.0, places=5)
        self.assertAlmostEqual(it.size.y, 20.0, places=5)

    def test_blend_and_color(self):
        it, _ = self._item(plane=plane_fields(blendMode=1, color=[0, 128, 255, 255]))
        self.assertEqual(it.blend, "ADDITIVE")
        self.assertAlmostEqual(it.color[2], 1.0, places=6)
        self.assertAlmostEqual(it.color[0], 0.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# RIBBON
# ─────────────────────────────────────────────────────────────────────────────

class TestRibbon(unittest.TestCase):

    def _sim(self, ribbon=None, frames=20, **kw):
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        sim = make_sim(extra=[(RIBBON, ribbon or ribbon_fields())], **kw)
        for _ in range(frames):
            sim.step()
        return sim

    def test_kind_and_vertex_count(self):
        # 轨迹跟随要有轨迹才画得出来（静止 → 彻底消失，见下面那条）
        sim = self._sim(ribbon=ribbon_fields(subdivisionCount=5),
                        velocity=velocity_fields(speed=10.0))
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        self.assertEqual(len(it.points), 5)

    def test_static_trail_ribbon_draws_nothing(self):
        """静止时条带**彻底消失**（用户实机确认）——不是退化成一条直线，
        也不能退化成 Simulator 的调试点（那会变成「静止时反而多一个点」）。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=50.0))
        self.assertEqual(sim.build_render(), [])

    def test_trail_length_scales_with_subdivision(self):
        """长度跟着细分数走：总长 = length × (细分数-1)。"""
        spans = {}
        for n in (2, 5):
            sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=10.0,
                                                 subdivisionCount=n),
                            velocity=velocity_fields(speed=10.0), frames=40)
            pts = [q for q, _w, _a in sim.build_render()[0].points]
            spans[n] = (pts[-1] - pts[0]).length()
        self.assertAlmostEqual(spans[2], 10.0, delta=0.5)      # 1 段
        self.assertAlmostEqual(spans[5], 40.0, delta=0.5)      # 4 段

    def test_trail_mode_follows_particle_motion(self):
        """粒子自己动 → 沿粒子轨迹（pick_trail 的 auto 分支）。

        默认 subdiv=5 → 总长上限 = 50 × 4 = 200；20 帧 × 10/帧只走了 190，
        还没到上限，所以条带就是这 190。
        """
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=50.0),
                        velocity=velocity_fields(speed=10.0))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        span = (pts[-1] - pts[0]).length()
        self.assertAlmostEqual(span, 190.0, delta=1.0)

    def test_trail_length_mode_total_caps_at_length(self):
        """`ribbon_length_mode='total'` = 改动前的读法：length 就是总长。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=50.0),
                        velocity=velocity_fields(speed=10.0),
                        config=SimConfig(ribbon_length_mode="total"))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 50.0, delta=1.0)

    def test_trail_falls_back_to_emitter_when_particle_is_static(self):
        """blade_trail 那种粒子不动的情形，轨迹得取发射器的。"""
        sim = self._sim(
            ribbon=ribbon_fields(ribbonMode=0, length=40.0),
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[300.0, 0.0, 0.0, 0.0, 0.0, 0.0]))   # 5/帧
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        # 发射器 20 帧 × 5/帧 = 95（默认 subdiv=5 → 上限 40×4=160，没到）
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 95.0, delta=1.0)

    def test_rigid_mode_is_a_straight_fixed_length_strip(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=60.0, baseAxis=1))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 60.0, places=4)
        for q in pts:                                  # baseAxis=1 → 沿 +Y
            self.assertAlmostEqual(q.x, 0.0, places=6)

    def test_chain_mode_settles_toward_straight(self):
        """restoreStrength=1 → 柔体链最终归位成平直。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=2, length=60.0,
                                             restoreStrength=1.0, springiness=0.3,
                                             inertia=0.5),
                        frames=120)
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 60.0, delta=3.0)

    def test_chain_mode_needs_per_frame_state(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=2), frames=5)
        from efx_format.sim.behaviors.ribbon import Ribbon as _R
        self.assertIn("nodes", sim.particles[0].user[_R])

    def test_width_taper(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, width=20.0,
                                             base_width_multiplier=0.0,
                                             tip_width_multiplier=1.0))
        widths = [w for _q, w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual(widths[0], 0.0, places=6)
        self.assertAlmostEqual(widths[-1], 10.0, places=6)     # 半宽 = 20/2
        self.assertLess(widths[0], widths[-1])

    def test_opacity_taper(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, base_opacity=0.0,
                                             tip_opacity=1.0))
        alphas = [a for _q, _w, a in sim.build_render()[0].points]
        self.assertAlmostEqual(alphas[0], 0.0, places=6)
        self.assertAlmostEqual(alphas[-1], 1.0, places=6)

    def test_spawn_anchor_offset_shifts_the_strip(self):
        a = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=50.0,
                                           spawnAnchorOffset=0.0))
        b = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=50.0,
                                           spawnAnchorOffset=1.0))
        pa = [q for q, _w, _x in a.build_render()[0].points]
        pb = [q for q, _w, _x in b.build_render()[0].points]
        self.assertAlmostEqual((pb[0] - pa[0]).length(), 50.0, places=4)

    def test_flap_displaces_the_strip(self):
        flat = self._sim(ribbon=ribbon_fields(ribbonMode=1, enableFlap=0))
        wavy = self._sim(ribbon=ribbon_fields(ribbonMode=1, enableFlap=1,
                                              flap1Frequency=2.0, flap1Amount=10.0))
        pf = [q for q, _w, _a in flat.build_render()[0].points]
        pw = [q for q, _w, _a in wavy.build_render()[0].points]
        moved = sum((a - b).length() for a, b in zip(pf, pw))
        self.assertGreater(moved, 1.0)

    def test_flap_is_deterministic(self):
        r = ribbon_fields(ribbonMode=1, enableFlap=1, flap1Frequency=2.0,
                          flap1Amount=10.0)
        a = [q.as_tuple() for q, _w, _x in self._sim(ribbon=r).build_render()[0].points]
        b = [q.as_tuple() for q, _w, _x in self._sim(ribbon=r).build_render()[0].points]
        self.assertEqual(a, b)


# ─────────────────────────────────────────────────────────────────────────────
# RIBBONBLADE
# ─────────────────────────────────────────────────────────────────────────────

class TestRibbonBlade(unittest.TestCase):

    def _sim(self, blade=None, frames=20, **kw):
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        sim = make_sim(extra=[(RIBBONBLADE, blade or blade_fields())], **kw)
        for _ in range(frames):
            sim.step()
        return sim

    def test_static_emitter_draws_nothing_but_says_why(self):
        """刀光靠发射器挥动画轨迹；发射器不动就没有拖尾——要说清楚原因。"""
        sim = self._sim()
        self.assertEqual(sim.build_render(), [])
        self.assertTrue(any("发射器" in n for n in sim.notes))

    def test_moving_emitter_grows_the_trail(self):
        sim = self._sim(
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[20.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        items = sim.build_render()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "RIBBON")
        self.assertGreater(items[0].size.y, 0.0)

    def test_length_is_capped_by_the_limit(self):
        sim = self._sim(
            blade=blade_fields(lengthMode=1, maxLengthLimit=100.0),
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            frames=40)
        self.assertLessEqual(sim.build_render()[0].size.y, 100.0 + 1e-6)

    def test_contraction_only_kicks_in_after_motion_stops(self):
        """0=驻留、值越大停下后收得越快——回缩是「停下之后」的行为。"""
        from efx_format.sim.behaviors.ribbonblade import RibbonBlade as _B

        def run(shrink):
            sim = make_sim(
                spawn=spawn_fields(burstInterval=1000),
                life=life_fields(indefiniteLifespan=1),
                transform=transform3d_fields(
                    enableVelocityBitflag=1,
                    translation_velocity=[30.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                extra=[(RIBBONBLADE, blade_fields(lengthMode=1, maxLengthLimit=900.0,
                                                  contractionSpeed=shrink))])
            sim.run(20)
            grown = sim.particles[0].user[_B]["length"]
            # 让发射器停下来：清掉速度，再跑一段
            sim.em.user[list(sim.em.user)[0]]["vel"] = Vec3()
            sim.run(30)
            return grown, sim.particles[0].user[_B]["length"]

        grown_hold, after_hold = run(0.0)          # 0 = 驻留
        grown_fast, after_fast = run(1200.0)       # 大 = 停下就收
        self.assertGreater(grown_hold, 0.0)
        self.assertAlmostEqual(after_hold, grown_hold, delta=1e-6)
        self.assertLess(after_fast, grown_fast)

    def test_colour_transition_point(self):
        """0=立即开始过渡 → 尾端与头端 alpha 明显不同。"""
        sim = self._sim(
            blade=blade_fields(colourTransitionPoint=0.0,
                               head={"epvColorSlot": 0, "color1": [255, 255, 255, 255]},
                               tailEnd={"epvColorSlot": 0, "color1": [0, 0, 0, 0]}),
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[20.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        alphas = [a for _q, _w, a in sim.build_render()[0].points]
        self.assertLess(alphas[0], alphas[-1])

    def test_blade_is_additive(self):
        sim = self._sim(
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[20.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        self.assertEqual(sim.build_render()[0].blend, "ADDITIVE")


# ─────────────────────────────────────────────────────────────────────────────
# MESH
# ─────────────────────────────────────────────────────────────────────────────

class TestMesh(unittest.TestCase):

    def _item(self, mesh=None, frames=1, **kw):
        kw.setdefault("spawn", spawn_fields(burstInterval=1000))
        kw.setdefault("life", life_fields(indefiniteLifespan=1))
        sim = make_sim(extra=[(MESH, mesh or mesh_fields())], **kw)
        for _ in range(frames):
            sim.step()
        return sim.build_render()[0], sim

    def test_kind_is_mesh(self):
        it, _ = self._item()
        self.assertEqual(it.kind, "MESH")

    def test_geometry_is_left_to_the_host(self):
        """核心拿不到 mod3 顶点，只给变换 + 颜色，并说明这一点。"""
        _it, sim = self._item()
        self.assertTrue(any("mod3" in n for n in sim.notes))

    def test_per_axis_scale_times_global(self):
        it, _ = self._item(mesh=mesh_fields(
            scale=[2.0, 0.0, 3.0, 0.0, 4.0, 0.0], global_scale=0.5))
        self.assertAlmostEqual(it.size.x, 1.0, places=6)
        self.assertAlmostEqual(it.size.y, 1.5, places=6)
        self.assertAlmostEqual(it.size.z, 2.0, places=6)

    def test_rotation_is_carried_in_extra(self):
        it, _ = self._item(mesh=mesh_fields(rotation=[10.0, 0.0, 20.0, 0.0, 30.0, 0.0]))
        rot = it.extra["rot"]
        self.assertAlmostEqual(rot.x, 10.0, places=6)
        self.assertAlmostEqual(rot.y, 20.0, places=6)
        self.assertAlmostEqual(rot.z, 30.0, places=6)
        self.assertIn(it.extra["rot_order"], ("XYZ", "YZX", "YXZ", "ZYX", "ZXY", "XZY"))

    def test_rotation2_adds_to_z(self):
        it, _ = self._item(mesh=mesh_fields(rotation2=45.0))
        self.assertAlmostEqual(it.extra["rot"].z, 45.0, places=6)

    def test_viscon_index_is_passed_through(self):
        it, _ = self._item(mesh=mesh_fields(visconIndex=3))
        self.assertEqual(it.extra["viscon"], 3)

    def test_emissive_off_by_default(self):
        it, _ = self._item()
        self.assertEqual(it.extra["emissive"], (0.0, 0.0, 0.0, 0.0))

    def test_emissive_on(self):
        it, _ = self._item(mesh=mesh_fields(useEmissiveColor=1,
                                            emissiveColor=[255, 0, 0, 255],
                                            emissiveColorRate=2.0))
        self.assertAlmostEqual(it.extra["emissive"][0], 2.0, places=6)

    def test_color_rate_multiplies(self):
        it, _ = self._item(mesh=mesh_fields(color=[100, 100, 100, 255], colorRate=2.0))
        self.assertAlmostEqual(it.color[0], 200 / 255.0, places=6)

    def test_disable_all_color_range_wins(self):
        a, _ = self._item(mesh=mesh_fields(color=[0, 0, 0, 255],
                                           colorRange=[255, 255, 255, 255],
                                           useColorRange=1, disableAllColorRange=1))
        self.assertAlmostEqual(a.color[0], 0.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# T3 之后的端到端
# ─────────────────────────────────────────────────────────────────────────────

class TestT3EndToEnd(unittest.TestCase):

    EXPECT = {
        "floating_particle_fire": "BILLBOARD",
        "ribbon_particle": "RIBBON",
        "mesh_debris_collision": "MESH",
        "mesh_flowing_texture": "MESH",
    }

    def test_each_archetype_renders_its_own_body(self):
        for stem, kind in self.EXPECT.items():
            with self.subTest(archetype=stem):
                blocks, timl = _load_archetype(stem + ".json")
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=2))
                # 10 帧：ribbon_particle 只发一批（burstsPerCycle=1/repeat=1）、
                # 寿命 1+15 帧，跑到 40 帧那一批早没了
                sim.run(10)
                items = sim.build_render()
                self.assertTrue(items, "%s 没产出任何渲染项" % stem)
                self.assertEqual({i.kind for i in items}, {kind})

    def test_dummy_archetypes_render_nothing(self):
        for stem in ("ground_contact_effect", "invisible_trigger", "player_aura"):
            with self.subTest(archetype=stem):
                blocks, timl = _load_archetype(stem + ".json")
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=2))
                sim.run(40)
                self.assertEqual(sim.build_render(), [])

    def test_skipped_bodies_still_fall_back_honestly(self):
        """STRAINRIBBON / LIGHTNING / BILLBOARD2D 刻意不做 → 退化点 + 如实列出。"""
        for stem, missing in (("draw_chain", "STRAINRIBBON"),
                              ("lightning", "LIGHTNING"),
                              ("2d_entry_basic", "BILLBOARD2D")):
            with self.subTest(archetype=stem):
                blocks, timl = _load_archetype(stem + ".json")
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=2))
                sim.run(20)
                self.assertIn(missing, [n for _h, n in sim.unsupported])
                for it in sim.build_render():
                    self.assertEqual(it.kind, "POINT")

    def test_all_archetypes_survive_strict_mode(self):
        for name in sorted(os.listdir(ARCHETYPE_DIR)):
            if not name.endswith(".json"):
                continue
            with self.subTest(archetype=name):
                blocks, timl = _load_archetype(name)
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=1, strict=True))
                for _ in range(120):
                    sim.step()
                sim.build_render()


# -----------------------------------------------------------------------------
# UVSEQUENCE（序列帧）
# -----------------------------------------------------------------------------

class TestUvsFrameTable(unittest.TestCase):
    """帧表本身：网格兜底 / 真 .uvs / 角点变换。"""

    def test_grid_default_is_8x8(self):
        t = grid_table()
        self.assertEqual(len(t), 64)
        self.assertEqual(t.source, "grid")
        self.assertEqual(t.grid, (8, 8))

    def test_grid_lr_tb_starts_at_top_row(self):
        # LR_TB = 左→右 上→下；v 向下，所以第一格在 v 最大的那行
        # （公式与 blender_efx/uvs_io.py::_gen_frames_grid 同源）
        t = grid_table(2, 2, "LR_TB")
        self.assertEqual(t.rect(0), (0.0, 0.5, 0.5, 1.0))
        self.assertEqual(t.rect(1), (0.5, 0.5, 1.0, 1.0))
        self.assertEqual(t.rect(2), (0.0, 0.0, 0.5, 0.5))

    def test_grid_lr_bt_is_the_mirror(self):
        t = grid_table(2, 2, "LR_BT")
        self.assertEqual(t.rect(0), (0.0, 0.0, 0.5, 0.5))

    def test_index_wraps_or_clamps(self):
        t = grid_table(2, 2)
        self.assertEqual(t.index(5, wrap=True), 1)
        self.assertEqual(t.index(5, wrap=False), 3)
        self.assertEqual(t.index(-1, wrap=True), 3)
        self.assertEqual(t.index(-1, wrap=False), 0)

    def test_parse_real_uvs_bytes(self):
        data = uvs_bytes([(0.0, 0.0, 0.25, 0.5), (0.25, 0.0, 0.5, 0.5)])
        t = simuvs.from_uvs_bytes(data, 0)
        self.assertIsNotNone(t)
        self.assertEqual(len(t), 2)
        self.assertEqual(t.source, "uvs")
        self.assertEqual(t.rect(0), (0.0, 0.0, 0.25, 0.5))
        self.assertEqual(t.tex_paths, ("sheet.tex",))

    def test_sequence_no_selects_the_group(self):
        # 用户确认：sequenceNo 就是 .uvs 里的 group 下标
        data = uvs_bytes([(0.0, 0.0, 1.0, 1.0)], extra_groups=2)
        self.assertEqual(len(simuvs.from_uvs_bytes(data, 0)), 1)
        self.assertEqual(len(simuvs.from_uvs_bytes(data, 1)), 2)
        self.assertEqual(len(simuvs.from_uvs_bytes(data, 2)), 3)
        self.assertIsNone(simuvs.from_uvs_bytes(data, 9))

    def test_corners_order_and_flips(self):
        t = simuvs.FrameTable([(0.1, 0.2, 0.3, 0.4)])
        bl, br, tr, tl = t.corners(0)
        self.assertEqual(bl, (0.1, 0.4))      # 左下：v 大 = 底
        self.assertEqual(br, (0.3, 0.4))
        self.assertEqual(tr, (0.3, 0.2))
        self.assertEqual(tl, (0.1, 0.2))
        # 水平翻转 = 左右两列 u 互换
        fbl, fbr = t.corners(0, flip_u=True)[:2]
        self.assertEqual((fbl[0], fbr[0]), (0.3, 0.1))
        # 垂直翻转 = 上下两行 v 互换
        vc = t.corners(0, flip_v=True)
        self.assertEqual((vc[0][1], vc[3][1]), (0.2, 0.4))

    def test_corners_turns_rotate_the_assignment(self):
        t = simuvs.FrameTable([(0.0, 0.0, 1.0, 1.0)])
        base = t.corners(0)
        self.assertEqual(t.corners(0, turns=1), base[1:] + base[:1])
        self.assertEqual(t.corners(0, turns=4), base)

    def test_resources_fall_back_to_grid(self):
        res = SimResources()
        table, fell_back = res.uvs_table(0, SimConfig())
        self.assertTrue(fell_back)
        self.assertEqual(len(table), 64)
        # 真表在就不兜底
        res2 = SimResources(uvs_bytes([(0.0, 0.0, 1.0, 1.0)] * 3))
        table2, fell_back2 = res2.uvs_table(0, SimConfig())
        self.assertFalse(fell_back2)
        self.assertEqual(len(table2), 3)


class TestUvSequence(unittest.TestCase):
    """behavior：帧推进 / 四种播放模式 / 翻转朝向 / 写进 RenderItem。"""

    def _res(self, n=4):
        w = 1.0 / n
        return SimResources(uvs_bytes([(i * w, 0.0, (i + 1) * w, 1.0)
                                       for i in range(n)]))

    def test_loop_advances_one_frame_per_frame(self):
        sim = uvseq_sim(resources=self._res(4), frames=1)
        p = sim.particles[0]
        seen = [frame_info(p)[0]]
        for _ in range(5):
            sim.step()
            seen.append(frame_info(p)[0])
        # playSpeed=1 → 每帧一格，走到末尾回绕
        self.assertEqual(seen, [1, 2, 3, 0, 1, 2])

    def test_half_speed_takes_two_frames_per_cell(self):
        sim = uvseq_sim(uv={"playSpeed": 0.5}, resources=self._res(8), frames=1)
        p = sim.particles[0]
        seen = [frame_info(p)[0]]
        for _ in range(5):
            sim.step()
            seen.append(frame_info(p)[0])
        self.assertEqual(seen, [0, 1, 1, 2, 2, 3])

    def test_per_second_unit_divides_by_fps(self):
        cfg = SimConfig(uvs_speed_unit="per_second", fps=60)
        sim = uvseq_sim(uv={"playSpeed": 60.0}, resources=self._res(8),
                        config=cfg, frames=3)
        # 60 格/秒 ÷ 60 fps = 每帧一格
        self.assertEqual(frame_info(sim.particles[0])[0], 3)

    def test_start_frame_only_never_advances(self):
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=0),
                            "patternNo": 2, "playSpeed": 0.0},
                        resources=self._res(4), frames=10)
        self.assertEqual(frame_info(sim.particles[0])[0], 2)

    def test_play_once_then_hold_clamps_at_last_frame(self):
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=3)},
                        resources=self._res(4), frames=20)
        p = sim.particles[0]
        self.assertTrue(p.alive)
        self.assertEqual(frame_info(p)[0], 3)

    def test_play_once_then_vanish_kills_the_particle(self):
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=2)},
                        resources=self._res(4), frames=3)
        self.assertEqual(len(sim.particles), 1)      # 还在放
        sim.run(4)
        self.assertEqual(len(sim.particles), 0)      # 放完就没了

    def test_vanish_span_respects_start_frame(self):
        # to_end：起始帧越靠后，这一轮越短
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=2),
                            "patternNo": 3},
                        resources=self._res(4), frames=2)
        self.assertEqual(len(sim.particles), 0)

    def test_reverse_direction_counts_down(self):
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=1, direction=1),
                            "patternNo": 3},
                        resources=self._res(4), frames=1)
        p = sim.particles[0]
        seen = [frame_info(p)[0]]
        for _ in range(3):
            sim.step()
            seen.append(frame_info(p)[0])
        self.assertEqual(seen, [2, 1, 0, 3])

    def test_always_flip_swaps_u(self):
        sim = uvseq_sim(uv={"loopingMode": looping_mode(playback=0, flip_h=1),
                            "playSpeed": 0.0},
                        resources=self._res(4), frames=1)
        item = sim.build_render()[0]
        bl, br = item.uv_corners[0], item.uv_corners[1]
        self.assertGreater(bl[0], br[0])         # 翻过来了：左角的 u 更大

    def test_random_flip_is_deterministic_per_seed(self):
        uv = {"loopingMode": looping_mode(playback=1, flip_h=2, flip_v=2),
              "loopingOrientation": 3}
        spawn = spawn_fields(particlesPerBurst=24, burstInterval=1000)

        def run(seed):
            sim = uvseq_sim(uv=uv, spawn=spawn, resources=self._res(4),
                            config=SimConfig(seed=seed), frames=2)
            return [it.uv_corners for it in sim.build_render()]

        a, b = run(7), run(7)
        self.assertEqual(a, b)
        self.assertNotEqual(a, run(8))
        # 随机档确实把粒子分成了不同形态，不是全体一致
        self.assertGreater(len(set(a)), 1)

    def test_render_item_carries_frame_debug_info(self):
        sim = uvseq_sim(resources=self._res(4), frames=2)
        item = sim.build_render()[0]
        self.assertEqual(item.extra["uvs_frame"], 2)
        self.assertEqual(item.extra["uvs_n"], 4)
        self.assertEqual(item.extra["uvs_source"], "uvs")
        self.assertEqual(item.uv_rect, (0.5, 0.0, 0.75, 1.0))

    def test_grid_fallback_notes_the_guess(self):
        sim = uvseq_sim(frames=2)      # 不给 resources
        self.assertTrue(any(".uvs" in n for n in sim.notes))
        item = sim.build_render()[0]
        self.assertEqual(item.extra["uvs_source"], "grid")
        self.assertEqual(item.extra["uvs_n"], 64)

    def test_runs_in_strict_mode(self):
        # RENDER_MOD 阶段只许写 p.user —— strict 会逐帧核对
        sim = uvseq_sim(resources=self._res(4),
                        config=SimConfig(strict=True), frames=30)
        sim.build_render()

    def test_no_render_body_stays_a_point(self):
        sim = uvseq_sim(billboard=None, resources=self._res(4), frames=2)
        item = sim.build_render()[0]
        self.assertEqual(item.kind, "POINT")
        self.assertIsNone(item.uv_corners)



if __name__ == "__main__":
    unittest.main(verbosity=2)
