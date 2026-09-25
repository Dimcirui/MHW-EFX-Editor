# -*- coding: utf-8 -*-
"""
tests/test_sim_core.py  —  efx_format/sim 的单元测试（零 bpy，脱离 Blender 跑）

    python3 -m unittest discover -s tests -v
    python3 tests/test_sim_core.py

这些测试存在的理由不只是防回归：模拟核心里每一条「实测得来的语义」都应该在这里
有一条对应的断言，这样等以后标定出新结论、改了 SimConfig 的默认值，能立刻看出
哪些结论被推翻了。
"""

import json
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from efx_format.hashes import (ALPHACORRECTION, BILLBOARD2D, BILLBOARD3D, DUMMY,  # noqa: E402
                               EMITTERSHAPE3D, FADEBYANGLE, FADEBYDEPTH, HOMING, LIGHTNING,
                               LIFE, MESH, NOISE, BLINK, PLANE, RIBBON, RIBBONBLADE,
                               PARENTOPTIONS, PTBEHAVIOR, PTCOLLISION, PTLIFE, REFRACTION,
                               RGBFIRE,
                               RGBWATER, ROTATEANIM, SCALEANIM, SHADERSETTINGS,
                               SPAWN, TRANSFORM3D, TURBULENCE, UVSEQUENCE, VELOCITY3D)
from efx_format.sim import (ActionTarget, EntryTemplate, FORCE,  # noqa: E402
                            Behavior, SimConfig, SimResources, SimScene,
                            Simulator, Vec3, from_attr_blocks, grid_table,
                            register)
from efx_format.sim import uvs_table as simuvs  # noqa: E402
from efx_format.sim.behaviors.homing import (Homing,  # noqa: E402
                                             _rotate_axis)
from efx_format.sim.behaviors.ptcollision import PtCollision  # noqa: E402
from efx_format.sim.behaviors.uvsequence import frame_info  # noqa: E402
from efx_format.sim import rng as simrng  # noqa: E402
from efx_format.sim import trail as _trail  # noqa: E402
from efx_format.sim.vecmath import (ROT_ORDER_TRANSFORM,  # noqa: E402
                                    rot_order_name, rotate_euler)

ARCHETYPE_DIR = os.path.join(_ROOT, "presets", "__archetypes__")


# ─────────────────────────────────────────────────────────────────────────────
# 构造辅助
# ─────────────────────────────────────────────────────────────────────────────

def spawn_fields(**kw):
    f = {
        "maxParticles": 0, "spawnNum": 1, "spawnNumJitter": 0,
        "intervalFrame": 10, "intervalFrameJitter": 0,
        "loopNum": 0, "loopNumJitter": 0,
        "emitterDelayFrame": 0, "emitterDelayFrameJitter": 0,
        "particleDelayFrame": 0, "particleDelayFrameJitter": 0,
        "revivalLoop": 0,
        "revivalInterval": 0, "revivalIntervalJitter": 0,
    }
    f.update(kw)
    return f


def life_fields(**kw):
    f = {
        "appearFrame": 0, "appearFrameJitter": 0,
        "keepFrame": 10, "keepFrameJitter": 0,
        "vanishFrame": 0, "vanishFrameJitter": 0,
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
        "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0,
        "sizeX": 1.0, "sizeY": 1.0, "sizeZ": 1.0,
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
         "sizeScalarAdd": 0.0, "sizeScalarAddJitter": 0.0,
         "sizeScalarAddCoef": 1.0, "sizeScalarAddCoefJitter": 0.0,
         "animUpdateStart": 0, "animUpdateStartJitter": 0}
    for ax in ("X", "Y", "Z"):
        f["size" + ax + "Add"] = 0.0
        f["size" + ax + "AddJitter"] = 0.0
        f["size" + ax + "AddCoef"] = 1.0
        f["size" + ax + "AddCoefJitter"] = 0.0
    f.update(kw)
    return f


def rgbfire_fields(**kw):
    f = {"typeFlag": 1,
         "fireColor": [255, 0, 0, 255], "smokeColor": [0, 0, 255, 255],
         "fireFactor": 1.0, "redChFactor": 1.0,
         "lerpAlphaToBlue": 0.0, "alphaFactor": 1.0, "colorRate": 1.0}
    for pre in ("fireColorParam_", "smokeColorParam_"):
        f[pre + "useLife"] = 0
        for k in ("appearFrame", "keepFrame", "vanishFrame"):
            f[pre + k] = 0
            f[pre + k + "Jitter"] = 0
        f[pre + "lighting"] = 0
        f[pre + "lifeType"] = 0
        f[pre + "correctColorNo"] = 0
    f.update(kw)
    return f


def rgbwater_fields(**kw):
    f = {"typeFlag": 1,
         "colorSpecular": [255, 0, 0, 255], "colorSheet": [0, 0, 255, 255],
         "colorRate": 1.0, "waterLerpGtoB": 0.0, "intensityCubeMap": 0.0,
         "intensitySpecular": 1.0, "intensitySheet": 1.0, "intensityAlpha": 1.0,
         "normalSharpness": 0.3, "path_len": 0, "path": b""}
    for pre in ("specularColorParam_", "sheetColorParam_", "waterLerpParam_"):
        f[pre + "useLife"] = 0
        for k in ("appearFrame", "keepFrame", "vanishFrame"):
            f[pre + k] = 0
            f[pre + k + "Jitter"] = 0
        f[pre + "lighting"] = 0
        f[pre + "lifeType"] = 0
    for pre in ("specularColorParam_", "sheetColorParam_"):
        f[pre + "correctColorNo"] = 0
    f.update(kw)
    return f


def alphacorrection_fields(**kw):
    f = {"unkn0": 1, "lowPass": 0.0, "contrast_gamma": 1.0,
         "unkn3": 0.0, "unknFlag2": 0}
    f.update(kw)
    return f


def rotateanim_fields(**kw):
    f = {"typeFlag": 0x7, "rotationModeMask": 0,
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
         "correctColorNo": 0, "colorRangeCorrectColorNo": 0,
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
         "correctColorNo": 0, "colorRangeCorrectColorNo": 0,
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
         "spawnAnchorOffset": 1.0,
         "restoreStrength": 1.0, "restoreStrengthJitter": 0.0,
         "inertia": 0.9, "inertiaJitter": 0.0,
         "springiness": 0.1, "springiness_jitter": 0.0,
         "epvcolor_0": 0, "epvcolor_1": 0,
         "base_width_multiplier": 1.0, "tip_width_multiplier": 1.0,
         "base_opacity": 1.0, "tip_opacity": 1.0,
         "base_fade_length": 0.3, "tip_fade_length": 0.4,
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
         "playSpeed": 0.0, "playSpeedJitter": 0.0,
         "rotation": [0.0] * 6, "rotationOrder": 4,
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
         "particleUseLocal": 0, "invalidParticleScale": 0,
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


def ptcollision_fields(**kw):
    f = {
        "typeFlag": 0, "physicsEnum": 3, "unkn02": 0, "unkn03": 0,
        "unknEnum04": 0, "unknFixed05": 0,
        "projectionOffset": 0.0, "projectionDist": 0.0,
        "unkn1_0": 0.0, "unkn1_1": 0.0, "unkn1_2": 0.0,
        "bounceCount": 0, "bounceCountJitter": 0,
        "bounceElasticity": 0.0, "bounceElasticityJitter": 0.0,
        "bounceElasticityMultiplier": 0.0, "horizontalBounce": 0.0,
        "unkn34": 0.0, "unkn35": 0.0, "unkn36": 0.0, "unkn37": 0.0,
        "impactPlayTriggerMode": 0, "impactPlayTriggerCount": 0,
        "impactPlayTriggerCountJitter": 0, "ieIndex": 0,
        "unknEnum6_0": 0, "unknEnum6_1": 0, "unknFixed6_2": 0,
    }
    f.update(kw)
    return f


#: 一帧内加速到 maxSpeed：只关心轨道几何的用例用它得到「从第二帧起恒速」
INSTANT_ACCEL = 1e6


def homing_fields(**kw):
    f = {
        "turnRate": 360.0, "acceleration": INSTANT_ACCEL, "maxSpeed": 2.0,
        "forceFieldSpeedScale": 1.0, "vanishRadius": 0.0, "forceFieldRadius": 0.0,
        "homingTarget": 0, "vanishMode": 0, "forceFieldMode": 0, "unknownEnum1": 0,
    }
    f.update(kw)
    return f


def noise_fields(**kw):
    f = {
        "typeFlag": 0, "section_length": 36, "spacer": 0,
        "lowFrequency": 0.0, "lowFrequencyJitter": 0.0,
        "lowFrequencyWidth": 0.0, "lowFrequencyWidthJitter": 0.0,
        "highFrequency": 0.0, "highFrequencyJitter": 0.0,
        "highFrequencyWidth": 0.0, "highFrequencyWidthJitter": 0.0,
    }
    f.update(kw)
    return f


def blink_fields(**kw):
    f = {
        "typeFlag": 0, "section_length": 44, "unkn1_0": 0.0,
        "minAlphaRate": 0.0, "maxAlphaRate": 1.0,
        "lowFrequency": 0.0, "lowFrequencyJitter": 0.0,
        "lowFrequencyWidth": 0.0, "lowFrequencyWidthJitter": 0.0,
        "highFrequency": 0.0, "highFrequencyJitter": 0.0,
        "highFrequencyWidth": 0.0, "highFrequencyWidthJitter": 0.0,
    }
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
    kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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
    kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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
        """intervalFrame=10 → 第 0/10/20… 帧各发一批，不是 11 帧一次。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=10, spawnNum=1),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 31), [0, 10, 20, 30])

    def test_interval_zero_emits_every_frame(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=0, spawnNum=1),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 5), [0, 1, 2, 3, 4])

    def test_interval_jitter_is_rolled_per_burst(self):
        """intervalFrameJitter 每批重抽 → 批间距参差不齐，落在 [v, v+jitter] 里。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=4, intervalFrameJitter=4),
                       life=life_fields(indefiniteLifespan=1))
        frames = self._birth_frames(sim, 200)
        gaps = {b - a for a, b in zip(frames, frames[1:])}
        self.assertGreater(len(gaps), 1)                    # 不是整轮等距
        self.assertGreaterEqual(min(gaps), 4)
        self.assertLessEqual(max(gaps), 8)

    def test_interval_jitter_per_cycle_is_uniform(self):
        """'per_cycle'（改动前的行为）：一轮只抽一次，整轮等距。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=4, intervalFrameJitter=4),
                       life=life_fields(indefiniteLifespan=1),
                       config=SimConfig(spawn_interval_jitter="per_cycle"))
        frames = self._birth_frames(sim, 200)
        gaps = {b - a for a, b in zip(frames, frames[1:])}
        self.assertEqual(len(gaps), 1)

    def test_emitter_start_delay(self):
        sim = make_sim(spawn=spawn_fields(emitterDelayFrame=7, intervalFrame=100),
                       life=life_fields(indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 20), [7])

    def test_particles_per_burst(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=4, intervalFrame=100),
                       life=life_fields(indefiniteLifespan=1))
        sim.step()
        self.assertEqual(len(sim.particles), 4)

    def test_max_particles_is_a_concurrent_cap(self):
        """maxParticles 是同时存活上限，不是终身总量：死一个补一个。

        ⚠ 不断言「每帧都满编」：step() 是先生成后收割，本帧要死的粒子在做生成决策
        时还占着名额，所以满编+同龄时会有一帧空窗（见 simulator.py 的取舍说明）。
        """
        sim = make_sim(
            spawn=spawn_fields(spawnNum=5, intervalFrame=0, maxParticles=3),
            life=life_fields(keepFrame=4))
        counts = []
        for _ in range(40):
            sim.step()
            counts.append(len(sim.particles))
            self.assertLessEqual(counts[-1], 3)
        self.assertEqual(max(counts), 3)
        self.assertGreater(sim.em.spawned_total, 3)   # 确实一直在补

    def test_revival_starts_next_round_after_interval(self):
        """每轮 loopNum 批，最后一批发出后等 revivalInterval 帧开始下一轮，共 revivalLoop 轮。"""
        sim = make_sim(
            spawn=spawn_fields(loopNum=3, intervalFrame=10, revivalLoop=2,
                               revivalInterval=60),
            life=life_fields(keepFrame=20))
        self.assertEqual(self._birth_frames(sim, 300), [0, 10, 20, 80, 90, 100])
        self.assertEqual(sim.em.cycle, 1)

    def test_revival_interval_ignores_particle_life(self):
        """复活间隔从最后一批发出时算起，不等粒子消失。"""
        for duration in (5, 40):
            sim = make_sim(
                spawn=spawn_fields(loopNum=1, intervalFrame=0, revivalLoop=3,
                                   revivalInterval=60),
                life=life_fields(keepFrame=duration))
            self.assertEqual(self._birth_frames(sim, 300), [0, 60, 120])

    def test_revival_interval_zero_revives_next_frame(self):
        sim = make_sim(
            spawn=spawn_fields(loopNum=1, intervalFrame=0, revivalLoop=30,
                               revivalInterval=0),
            life=life_fields(keepFrame=20))
        self.assertEqual(self._birth_frames(sim, 100), list(range(30)))

    def test_revival_loop_one_does_not_revive(self):
        """revivalLoop=1 只跑一轮：3 批、间隔 2 帧 → 0/2/4，之后不再发。"""
        sim = make_sim(
            spawn=spawn_fields(loopNum=3, revivalLoop=1, intervalFrame=2,
                               revivalInterval=5),
            life=life_fields(keepFrame=10, indefiniteLifespan=1))
        self.assertEqual(self._birth_frames(sim, 200), [0, 2, 4])

    def test_revival_loop_zero_revives_forever(self):
        sim = make_sim(
            spawn=spawn_fields(loopNum=1, intervalFrame=0, revivalLoop=0,
                               revivalInterval=60),
            life=life_fields(keepFrame=20))
        self.assertEqual(self._birth_frames(sim, 400), [0, 60, 120, 180, 240, 300, 360])

    def test_loop_num_zero_never_ends_round(self):
        """loopNum=0 时这一轮不结束，按 intervalFrame 一直发。"""
        sim = make_sim(
            spawn=spawn_fields(loopNum=0, revivalLoop=1, intervalFrame=3),
            life=life_fields(keepFrame=5))
        sim.run(500)
        self.assertGreater(sim.em.spawned_total, 50)
        self.assertGreater(sim.suggested_duration(), 0)

    def test_particle_spawn_delay_holds_the_particle(self):
        sim = make_sim(
            spawn=spawn_fields(particleDelayFrame=5, intervalFrame=100),
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
        """keepFrame=10 → 恰好被渲染 10 帧。

        没有渲染体的 entry 现在不产出任何渲染项（同 DUMMY，见 TestDummy），
        这里挂一个未实现的 LIGHTNING 当渲染体，只借它的退化点探测粒子存在，
        与本测试要验的 duration 逻辑无关。
        """
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000), life=life_fields(keepFrame=10),
                       extra=[(LIGHTNING, {})])
        rendered = 0
        for _ in range(30):
            sim.step()
            rendered += len(sim.build_render())
        self.assertEqual(rendered, 10)

    def test_indefinite_never_dies(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(keepFrame=3, indefiniteLifespan=1))
        for _ in range(200):
            sim.step()
        self.assertEqual(len(sim.particles), 1)

    def test_fade_in_ramps_alpha(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(appearFrame=4, keepFrame=10))
        alphas = []
        for _ in range(6):
            sim.step()
            if sim.particles:
                alphas.append(round(sim.particles[0].alpha, 3))
        self.assertEqual(alphas[:5], [0.0, 0.25, 0.5, 0.75, 1.0])

    def test_fade_out_ramps_down(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(keepFrame=4, vanishFrame=4))
        alphas = []
        for _ in range(9):
            sim.step()
            if sim.particles:
                alphas.append(round(sim.particles[0].alpha, 3))
        self.assertEqual(alphas[-4:], [1.0, 0.75, 0.5, 0.25])

    def test_total_life_is_sum_of_three_segments(self):
        """总寿命 = 淡入 + 持续 + 淡出。"""
        f = life_fields(appearFrame=5, keepFrame=10, vanishFrame=5)
        a = make_sim(spawn=spawn_fields(intervalFrame=1000), life=f)
        a.step()
        self.assertEqual(a.particles[0].life, 20)


# ─────────────────────────────────────────────────────────────────────────────
# EMITTERSHAPE3D
# ─────────────────────────────────────────────────────────────────────────────

class TestEmitterShape3D(unittest.TestCase):
    """按作者教程《生成方式》：rangeXYZ = 偏移(内边界) / 尺寸(向外的厚度)。"""

    def _spawn_many(self, es3d, n=300, config=None):
        sim = make_sim(spawn=spawn_fields(spawnNum=n, intervalFrame=1000),
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
        low = [math.hypot(p.x, p.z) for p in pts if p.y < 2.0]
        high = [math.hypot(p.x, p.z) for p in pts if p.y > 7.0]
        self.assertTrue(low and high)
        self.assertLess(max(low), min(high) + 1e-6)     # 两端半径不重叠
        self.assertLess(max(low), 4.0)                  # 底部约 0.2 倍
        self.assertGreater(max(high), 8.0)              # 顶部约 1.0 倍

    def test_cylinder_height_grows_one_way(self):
        """圆柱高度是**单向**的：偏移 Y=底面、尺寸 Y=往 +Y 长的高度，不是 ±尺寸。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[0.0, 10.0, 0.0, 20.0, 0.0, 10.0]), n=400)
        ys = [p.y for p in pts]
        self.assertGreaterEqual(min(ys), -1e-6)          # 底面在偏移处，不往 -Y 走
        self.assertLessEqual(max(ys), 20.0 + 1e-6)
        self.assertGreater(max(ys), 18.0)                # 确实长到了 20

    def test_cylinder_height_offset_moves_the_base(self):
        """偏移 Y 抬高的是底面，高度仍是尺寸 Y。"""
        pts = self._spawn_many(es3d_fields(
            shapeType=2, rangeXYZ=[0.0, 10.0, 5.0, 20.0, 0.0, 10.0]), n=400)
        ys = [p.y for p in pts]
        self.assertGreaterEqual(min(ys), 5.0 - 1e-6)
        self.assertLessEqual(max(ys), 25.0 + 1e-6)

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
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
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
        sim = make_sim(spawn=spawn_fields(spawnNum=50, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1), es3d=es3d,
                       velocity=velocity_fields(velocityType=2, speed=1.0))
        sim.step()
        for p in sim.particles:
            self.assertGreater(p.pos.length(), p.spawn_pos.length())

    def test_directional_spread_uses_the_documented_formula(self):
        """Vi = (size - 1) * 生成坐标 + offset，归一化。"""
        es3d = es3d_fields(shapeType=3, rangeXYZ=[3.0, 3.0, 0.0, 0.0, 4.0, 4.0])
        p = self._one(velocity_fields(velocityType=1, speed=5.0,
                                      sizeX=2.0, sizeY=1.0, sizeZ=2.0),
                      es3d=es3d)
        expect = Vec3(3.0, 0.0, 4.0).normalized() * 5.0
        self.assertAlmostEqual(p.vel.x, expect.x, places=6)
        self.assertAlmostEqual(p.vel.z, expect.z, places=6)

    def test_directional_spread_offset_counts_double(self):
        """offset 按 2 倍计入：Vi = (size - 1) * 生成坐标 + 2 * offset。"""
        es3d = es3d_fields(shapeType=3, rangeXYZ=[3.0, 3.0, 0.0, 0.0, 4.0, 4.0])
        p = self._one(velocity_fields(velocityType=1, speed=5.0,
                                      sizeX=2.0, sizeY=1.0, sizeZ=2.0, offsetY=1.0),
                      es3d=es3d)
        expect = Vec3(3.0, 2.0, 4.0).normalized() * 5.0
        self.assertAlmostEqual(p.vel.x, expect.x, places=6)
        self.assertAlmostEqual(p.vel.y, expect.y, places=6)
        self.assertAlmostEqual(p.vel.z, expect.z, places=6)

    def test_unknown_velocity_type_is_reported(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(velocityType=5))
        sim.step()
        self.assertTrue(any("velocityType=5" in n for n in sim.notes))

    def test_rotation_jitter_spreads_directions(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=100, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0, rotationX=30.0,
                                                rotationXJitter=10.0))
        sim.step()
        ys = [p.vel.y for p in sim.particles]
        self.assertGreater(max(ys) - min(ys), 1e-3)


class TestHoming(unittest.TestCase):
    """运动学模型见 memory homing-orbit-kinematics-model：径直飞向目标→到达转 90°→
    以 r=v/turnRate 匀速转圈。圆心一般不是目标本身（离散逐帧积分下，圆经过「到达」
    那一刻的位置，target 只保证落在一帧步长之内——见 behaviors/homing.py 模块
    docstring），所以断言只查「有界、周期性」而不是「半径恰好等于 target」。"""

    def _sim(self, homing, es3d=None, velocity=None, life=None, config=None):
        return make_sim(spawn=spawn_fields(intervalFrame=1000),
                        life=life or life_fields(indefiniteLifespan=1),
                        es3d=es3d, velocity=velocity or velocity_fields(speed=0.0),
                        config=config, extra=[(HOMING, homing)])

    def test_approach_flies_straight_and_monotonically_closes_in(self):
        es3d = es3d_fields(shapeType=0, rangeXYZ=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(maxSpeed=2.0), es3d=es3d)
        sim.step()
        p = sim.particles[0]
        for _ in range(5):
            prev = p.pos.length()
            sim.step()
            self.assertLess(p.pos.length(), prev)
        self.assertAlmostEqual(p.vel.length(), 2.0, places=6)

    def test_scattered_particles_keep_distinct_orbit_directions(self):
        """回归：生成距离恰好是 speed 的整数倍时（如默认预设 30 距离 / 1 速度），
        到达那一帧 (p.pos-target) 精确归零，落进退化回退——曾经导致**全体**粒子
        （不管球面上哪个方向生成的）摔进同一个回退常量、转向完全一致，实机表现是
        全部粒子到达后一起往同一个方向甩出去。2026-09-12 用户实机截图坐实。"""
        es3d = es3d_fields(shapeType=1, rangeXYZ=[30.0, 0.0, 30.0, 0.0, 30.0, 0.0])
        sim = self._sim(homing_fields(turnRate=90.0, maxSpeed=1.0),
                        es3d=es3d,
                        velocity=velocity_fields(speed=0.0, velocityType=1))
        sim.em.request_spawn(200)
        sim.step()
        particles = list(sim.particles)
        for _ in range(60):
            sim.step()
        directions = {(round(p.vel.x, 3), round(p.vel.y, 3), round(p.vel.z, 3))
                     for p in particles}
        # 球面各方向生成，到达后的转向理应五花八门；退化回退时会全部塌缩成 1 个。
        self.assertGreater(len(directions), len(particles) // 2)

    def test_axial_offset_does_not_drift_away_unbounded(self):
        """回归：绕固定轴转结构上只碰垂直于轴的两维——到达瞬间那份沿轴分量若留在
        续转的方向向量里，会被逐帧重复叠加进 p.vel，永远回不了头（2026-09-12 用户
        实机反馈"某根轴上完全看不到收缩"，正是这个缺口：600 帧内沿轴偏移量从十几
        涨到一百多，单调发散）。切向状态改成只留垂直于轴的部分 + 独立轴向回拉后，
        沿轴偏移应该在有界范围内起伏，不再单调发散。"""
        es3d = es3d_fields(shapeType=1, rangeXYZ=[30.0, 0.0, 30.0, 0.0, 30.0, 0.0])
        sim = self._sim(homing_fields(turnRate=90.0, maxSpeed=1.0),
                        es3d=es3d,
                        velocity=velocity_fields(speed=0.0, velocityType=1))
        sim.em.request_spawn(200)
        sim.step()
        particles = list(sim.particles)
        early_axial = []
        late_axial = []
        for i in range(1200):
            sim.step()
            if i == 100:
                early_axial = [abs(p.pos.y) for p in particles]
            if i == 1100:
                late_axial = [abs(p.pos.y) for p in particles]
        self.assertTrue(early_axial and late_axial)
        # 发散的话晚期均值会比早期大出一个数量级；有界起伏的话量级相近。
        early_mean = sum(early_axial) / len(early_axial)
        late_mean = sum(late_axial) / len(late_axial)
        self.assertLess(late_mean, early_mean * 5.0 + 5.0)

    def test_orbit_stays_bounded_after_arrival(self):
        """到达后既不会飞出去也不会定住——半径量级围着 r=v/turnRate 打转，有界。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(turnRate=360.0, maxSpeed=2.0),
                        es3d=es3d)
        sim.step()
        p = sim.particles[0]
        dists = []
        for _ in range(300):
            sim.step()
            dists.append(p.pos.length())
        turn_step = math.radians(360.0) / 60
        expected_r = 2.0 / (2.0 * math.sin(turn_step / 2.0))
        tail = dists[-120:]
        self.assertLess(max(tail), 2.5 * expected_r)
        self.assertGreater(max(tail), 0.5 * expected_r)

    def _probe_sim(self, acceleration, max_speed, v3d, turn_rate=360.0):
        """实机探针同款：出生在 (±15, 0, 0)，V3D 竖直向上的初速度把轨道锁在 X-Y 平面。"""
        es3d = es3d_fields(shapeType=2, rangeXYZ=[15.0, 0.0, 0.0, 0.0, 15.0, 0.0],
                           rangeDivideVerticalNum=2)
        return self._sim(homing_fields(turnRate=turn_rate, acceleration=acceleration,
                                       maxSpeed=max_speed),
                         es3d=es3d, velocity=velocity_fields(speed=v3d))

    def test_speed_holds_once_max_speed_is_reached(self):
        """到达 maxSpeed 后速度不再变化，轨道是闭合的圆。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(maxSpeed=3.0), es3d=es3d)
        sim.step()
        p = sim.particles[0]
        for _ in range(20):
            sim.step()
            self.assertAlmostEqual(p.user[Homing]["speed"], 3.0, places=9)

    def test_start_speed_comes_from_velocity3d(self):
        """探针 C1（2026-09-24 实机）：acceleration=0 时粒子保持 V3D 初速度绕圈，轨道
        直径与 V3D 速度成正比。旧读法「初速度为 0 则不动」只在 V3D 也为 0 时成立。"""
        for v in (1.0, 2.0, 4.0):
            sim = self._probe_sim(0.0, 1000.0, v)
            sim.step()
            p = sim.particles[0]
            start = p.pos.copy()
            for _ in range(30):
                sim.step()
            self.assertAlmostEqual(p.user[Homing]["speed"], v, places=9)
            self.assertNotEqual(p.pos, start)
            self.assertAlmostEqual(p.pos.z, 0.0, places=9)   # 留在正对镜头的平面内

    def test_start_speed_is_capped_by_max_speed(self):
        sim = self._probe_sim(0.0, 1.0, 4.0)
        sim.step()
        self.assertAlmostEqual(sim.particles[0].user[Homing]["speed"], 1.0, places=9)

    def test_zero_max_speed_is_stationary(self):
        """maxSpeed=0 时粒子不动，V3D 初速度也被覆盖。"""
        sim = self._probe_sim(5.0, 0.0, 3.0)
        sim.step()
        p = sim.particles[0]
        start = p.pos.copy()
        for _ in range(30):
            sim.step()
        self.assertEqual(p.pos, start)

    def test_acceleration_is_speed_added_per_second(self):
        """探针 B2/C2（2026-09-24 实机）：每秒加 acceleration，至 maxSpeed 为止，自出生起
        即开始加速。"""
        sim = self._probe_sim(2.0, 1000.0, 1.0)
        sim.step()
        p = sim.particles[0]
        for _ in range(60):
            sim.step()
        self.assertAlmostEqual(p.user[Homing]["speed"], 3.0, places=6)

        sim = self._probe_sim(2.0, 1.5, 1.0)
        sim.step()
        p = sim.particles[0]
        for _ in range(60):
            sim.step()
        self.assertAlmostEqual(p.user[Homing]["speed"], 1.5, places=9)

    def test_time_to_max_speed_scales_inversely_with_acceleration(self):
        """探针 C3（2026-09-24 实机）：0.2→3 与 1→3（V3D=1）入轨时间差 5 倍。
        旧标定「0.1→1 与 0.5→1 都是 4 圈」是 V3D=0 下的误读，已作废。"""
        def frames_to_max(acc, top=3.0):
            sim = self._probe_sim(acc, top, 1.0)
            sim.step()
            p = sim.particles[0]
            n = 0
            while p.user[Homing]["speed"] < top - 1e-9 and n < 5000:
                sim.step()
                n += 1
            return n

        slow, fast = frames_to_max(0.2), frames_to_max(1.0)
        self.assertAlmostEqual(slow, 600, delta=2)      # (3 − 1) / (0.2 / 60)
        self.assertAlmostEqual(fast, 120, delta=2)
    def _swarm_flatness(self, frames, n=300):
        """球壳生成一批粒子，跑 `frames` 帧后返回 extY/max(extX,extZ)。
        1.0=各向同性的球，<1=竖直方向被压扁。"""
        es3d = es3d_fields(shapeType=1, rangeXYZ=[30.0, 0.0, 30.0, 0.0, 30.0, 0.0])
        sim = self._sim(homing_fields(turnRate=90.0, maxSpeed=1.0),
                        es3d=es3d,
                        velocity=velocity_fields(speed=0.0, velocityType=1))
        sim.em.request_spawn(n)
        sim.step()
        particles = list(sim.particles)
        for _ in range(frames):
            sim.step()
        xs = [p.pos.x for p in particles]
        ys = [p.pos.y for p in particles]
        zs = [p.pos.z for p in particles]
        ext_y = max(ys) - min(ys)
        ext_xz = max(max(xs) - min(xs), max(zs) - min(zs))
        return ext_y / ext_xz if ext_xz else 0.0

    def test_lateral_force_alone_flattens_swarm_at_full_expansion(self):
        """竖直压扁**不需要任何额外机制**，它是「侧向力」这条正确读法的自然结果。

        到达目标时速度获得的是一个与来向**垂直的分量**（侧向/向心力），方向在原点
        连续、原点是圆的切点。于是轨道相的闭式解变成（`d`=来向，`n`=指向圆心的侧向
        单位向量，与 `d` 正交）

            p(θ) = r·sinθ·d + r·(1-cosθ)·n      ⇒  θ=180° 时 p = 2r·n

        半周期的形状因此是 **`{n_i}` 的分布**，而不是出生方向 `{s_i}` 的分布——后者
        是球壳、恒各向同性（这正是旧的「就地转 90°」读法怎么调都压不扁的原因）。
        `{n_i}` 则可以各向异性。

        实测最大扩张处 flat≈0.47，往收缩两端回到≈0.95，与用户实拍差分序列的签名一致
        （中间几格压成横条、两端是圆环）。"""
        # 帧数含 approach 段（球壳半径 30 / 速度 1 ⇒ 约 30 帧才到达），所以半周期
        # 落在第 150 帧附近而不是 120。
        at_peak = self._swarm_flatness(frames=150)       # ≈ θ=180°，最大扩张
        near_contract = self._swarm_flatness(frames=45)  # ≈ 接近收缩点
        self.assertLess(at_peak, 0.6)
        self.assertGreater(near_contract, 0.85)
        self.assertGreater(near_contract, at_peak)

    def test_spiral_gap_scales_with_acceleration(self):
        """未到上限时轨道是等距螺旋，每圈半径增量与 acceleration 成正比（探针 C2）。"""
        def lap_gaps(acc, laps=4):
            sim = self._probe_sim(acc, 1000.0, 1.0)
            sim.step()
            p = sim.particles[0]
            origin = sim.em.origin
            radii = []
            for _ in range(laps):
                far = 0.0
                for _ in range(60):           # turnRate=360 @60fps ⇒ 一圈 60 帧
                    sim.step()
                    far = max(far, (p.pos - origin).length())
                radii.append(far)
            return [b - a for a, b in zip(radii, radii[1:])]

        gaps = {acc: lap_gaps(acc) for acc in (0.5, 1.0, 2.0)}
        for acc, g in gaps.items():
            self.assertTrue(all(x > 0 for x in g), (acc, g))
            self.assertLess(max(g), 1.5 * min(g), "应近似等距 %r" % (g,))
        mean = {acc: sum(g) / len(g) for acc, g in gaps.items()}
        self.assertAlmostEqual(mean[1.0] / mean[0.5], 2.0, delta=0.3)
        self.assertAlmostEqual(mean[2.0] / mean[1.0], 2.0, delta=0.3)

    def test_arrival_is_a_lateral_force_not_a_ninety_degree_corner(self):
        """回归（2026-09-12 用户看 Blender 预览当场指出）：到达目标处的轨迹必须是
        **光滑**的——速度方向逐帧只转 turnRate/fps，不存在就地转 90° 的锐角拐点；
        而且圆心落在**侧向**（与来向垂直），原点是圆的切点，整个圆挂在侧向那一边。

        曾经实现成 `_rotate_axis(incoming, axis, 90.0)`（把方向整个转 90°），导致
        ① 原点是锐角拐点；② 圆心在 `-r·d`，圆挂在来向的反侧（"在上面"而不是
        "在左侧"）；③ 转完再投影还丢速度，各段圆半径不一致。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(turnRate=90.0, maxSpeed=1.0), es3d=es3d)
        sim.step()
        p = sim.particles[0]
        dirs, poss = [], []
        for _ in range(400):
            sim.step()
            dirs.append(p.vel.normalized(fallback=Vec3(0.0, 0.0, 1.0)))
            poss.append(p.pos.copy())

        # ① 方向连续：相邻帧夹角处处 ≤ 每帧转角，绝不出现 90° 跳变
        per_frame = 90.0 / 60.0
        for a, b in zip(dirs, dirs[1:]):
            cosang = max(-1.0, min(1.0, a.dot(b)))
            self.assertLessEqual(math.degrees(math.acos(cosang)), per_frame + 0.1)

        # ② 原点是切点：圆心到原点的距离 ≈ 半径 ≈ v/ω
        orbit = poss[40:]
        cx = (max(q.x for q in orbit) + min(q.x for q in orbit)) / 2.0
        cy = (max(q.y for q in orbit) + min(q.y for q in orbit)) / 2.0
        cz = (max(q.z for q in orbit) + min(q.z for q in orbit)) / 2.0
        center = Vec3(cx, cy, cz)
        expected_r = 1.0 * 60.0 / (math.pi / 2.0)
        self.assertAlmostEqual(center.length(), expected_r, delta=0.15 * expected_r)

        # ③ 圆心在侧向：来向与「原点→圆心」方向近乎垂直（旧的错误行为是 180°）
        d_in = dirs[10]
        cosang = max(-1.0, min(1.0, d_in.dot(center.normalized(fallback=Vec3(0.0, 1.0, 0.0)))))
        self.assertAlmostEqual(math.degrees(math.acos(cosang)), 90.0, delta=5.0)

    def test_outward_initial_velocity_expands_the_swarm_before_homing_wins(self):
        """2026-09-12 定案判据（用户实机，用他场景里的真实参数复现）：
        V3D 向外 1（Radial，speedCoef 0.95）+ HOMING init=target=1、turnRate 90。

        实机：整团**先向外扩张**并旋转，之后回归周期运动，最大直径不缩水。

        纯追踪给得出扩张：初速度方向朝外，HOMING 只能按 turnRate 把方向慢慢扭回来，
        扭到对准目标为止。"""
        def radii():
            sim = make_sim(
                spawn=spawn_fields(spawnNum=60, intervalFrame=1000),
                life=life_fields(indefiniteLifespan=1),
                es3d=es3d_fields(shapeType=1,
                                 rangeXYZ=[30.0, 0.0, 30.0, 0.0, 30.0, 0.0]),
                velocity=velocity_fields(speed=1.0, velocityType=2, speedCoef=0.95),
                extra=[(HOMING, homing_fields(turnRate=90.0, maxSpeed=1.0))])
            sim.step()
            out = []
            for _ in range(600):
                sim.step()
                act = [q for q in sim.particles if q.active]
                out.append(sum(q.pos.length() for q in act) / len(act))
            return out

        pur = radii()
        self.assertGreater(pur[0], 30.0)                 # 第一帧就在向外
        for a, b in zip(pur[:60], pur[1:61]):
            self.assertGreater(b, a)                     # 头一秒持续扩张
        self.assertGreater(max(pur[:150]), 2.0 * 30.0)   # 涨到出生半径两倍以上
        # 之后回归周期运动，且**最大直径不缩水**（系统无耗散）——注意最小值仍会
        # 回到 ~0：切圆过目标点，每圈必然穿过一次，这是轨道几何不是衰减。
        self.assertGreater(max(pur[300:450]), 40.0)
        self.assertAlmostEqual(max(pur[450:600]), max(pur[300:450]), delta=2.0)

    def test_pursuit_reproduces_the_tangent_circle_without_a_state_machine(self):
        """纯追踪把「到达处的侧向力」从硬编码变成推论：圆过目标点、与来向相切、
        半径 r=v/ω、方向处处连续——这些**都没有**在 _pursue 里写出来，是「每帧朝
        目标转 turnRate」自己长出来的。（弦切角定理：圆过目标点时「指向目标」的
        方向以 ω/2 旋转，粒子以 ω 追它，每整圈正好回到目标点一次 ⇒ 切圆是不变集。）"""
        sim = self._sim(homing_fields(turnRate=90.0, maxSpeed=1.0),
                        es3d=es3d_fields(shapeType=0,
                                         rangeXYZ=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        sim.step()
        p = sim.particles[0]
        dirs, poss = [], []
        for _ in range(400):
            sim.step()
            dirs.append(p.vel.normalized(fallback=Vec3(0.0, 0.0, 1.0)))
            poss.append(p.pos.copy())

        per_frame = 90.0 / 60.0
        for a, b in zip(dirs, dirs[1:]):                 # 方向处处连续，无锐角
            cosang = max(-1.0, min(1.0, a.dot(b)))
            self.assertLessEqual(math.degrees(math.acos(cosang)), per_frame + 0.1)

        orbit = poss[120:]
        center = Vec3(*[(max(q[k] for q in orbit) + min(q[k] for q in orbit)) / 2.0
                        for k in range(3)])
        expected_r = 1.0 * 60.0 / (math.pi / 2.0)        # v/ω
        radii = [(q - center).length() for q in orbit]
        self.assertAlmostEqual(sum(radii) / len(radii), expected_r,
                               delta=0.1 * expected_r)   # 半径 = v/ω
        self.assertAlmostEqual(center.length(), expected_r,
                               delta=0.15 * expected_r)  # 目标在圆上 ⇒ 原点是切点

    def test_force_field_mode_1_culls_particles_spawned_inside(self):
        es3d = es3d_fields(shapeType=0, rangeXYZ=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(forceFieldMode=1, forceFieldRadius=50.0), es3d=es3d)
        sim.step()
        self.assertEqual(len(sim.particles), 0)

    def test_force_field_mode_3_keeps_particles_spawned_inside(self):
        """内部不转向只冻结球内转向，球内出生的粒子保留。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(forceFieldMode=3, forceFieldRadius=50.0), es3d=es3d)
        sim.step()
        self.assertEqual(len(sim.particles), 1)

    def test_force_field_mode_2_slows_particles_inside(self):
        """球内每帧阻尼因子先乘 k、再加 1/48 回升，速度 = speed × 阻尼因子。"""
        def run(frames):
            es3d = es3d_fields(shapeType=0, rangeXYZ=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            # V3D 给满速，第一帧起速度即为 maxSpeed
            sim = self._sim(homing_fields(forceFieldMode=2, forceFieldRadius=50.0,
                                          forceFieldSpeedScale=0.1,
                                          maxSpeed=2.0),
                            es3d=es3d, velocity=velocity_fields(speed=2.0))
            sim.step()
            p = sim.particles[0]
            for _ in range(frames):
                sim.step()
            return p.vel.length()

        c = 1.0 / 48.0
        damp = 1.0
        for n in range(3):
            damp = min(1.0, damp * 0.1 + c)       # 出生那一帧已经算过一次
            self.assertAlmostEqual(run(n), 2.0 * damp, places=9)

    def test_balanced_force_field_settles_at_c_over_one_minus_k(self):
        """力场减速的定量标定（2026-09-12 用户扫 k 量轨道直径）。

        实拍 k=0.99/0.95/0.9/0.8/0.5 的直径比 **24:8:4:2:1**。

        每帧先乘 k、再加固定绝对增量 c=1/recover_frames，阻尼因子平衡在
            f* = min(1, c/(1-k))
        给出 24:10:5:2.5:1 —— **两个端点精确命中**，且 k=0.99 的 24 正是撞到上限
        （纯 1/(1-k) 外推会给 50）。中段高约 25%，在目测比例的误差内。

        ⚠ 阻尼必须记在**独立的** ff_damp 上，不能写进 speed 状态：后者是
        acceleration 那条**慢**加速的载体，被这条**快**回拉（48 帧）碰到就会被整个接管。"""
        def settled_damp(k, recover=48.0, frames=3000):
            cfg = SimConfig()
            cfg.homing_ff_recover_frames = recover
            es3d = es3d_fields(shapeType=0, rangeXYZ=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            sim = self._sim(homing_fields(forceFieldMode=2, forceFieldRadius=1e9,
                                          forceFieldSpeedScale=k,
                                          maxSpeed=1.0),
                            es3d=es3d, config=cfg)
            sim.step()
            p = sim.particles[0]
            for _ in range(frames):
                sim.step()
            return p.user[Homing]["ff_damp"]

        c = 1.0 / 48.0
        for k in (0.5, 0.8, 0.9, 0.95):
            self.assertAlmostEqual(settled_damp(k), min(1.0, c / (1.0 - k)),
                                   places=6)
        # k 足够接近 1 时撞上限，不再随 k 增长
        self.assertAlmostEqual(settled_damp(0.999), 1.0, places=6)

        # 加速状态不受影响：speed 仍停在 maxSpeed
        sim = self._sim(homing_fields(forceFieldMode=2, forceFieldRadius=1e9,
                                      forceFieldSpeedScale=0.5,
                                      maxSpeed=1.0),
                        es3d=es3d_fields(shapeType=0,
                                         rangeXYZ=[5.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        sim.step()
        for _ in range(300):
            sim.step()
        self.assertAlmostEqual(sim.particles[0].user[Homing]["speed"], 1.0, places=9)

    def test_vanish_mode_immediate_kills_particle_near_target(self):
        """spawn 距离(30) > vanishRadius(5)，先确认活着，逼近到球内才应该死。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[30.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim = self._sim(homing_fields(maxSpeed=2.0,
                                     vanishMode=2, vanishRadius=5.0),
                        es3d=es3d)
        sim.step()
        p = sim.particles[0]
        self.assertTrue(p.alive)
        for _ in range(30):
            sim.step()
            if not p.alive:
                break
        self.assertFalse(p.alive)

    def test_vanish_mode_cancels_infinite_life_without_resetting_age(self):
        """memory：寿命计时器从出生就在跑、没有被重置——只是把 indefinite 摘掉。"""
        es3d = es3d_fields(shapeType=0, rangeXYZ=[30.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        life = life_fields(indefiniteLifespan=1, keepFrame=3)
        sim = self._sim(homing_fields(maxSpeed=2.0,
                                     vanishMode=1, vanishRadius=5.0),
                        es3d=es3d, life=life)
        sim.step()
        p = sim.particles[0]
        self.assertTrue(p.rolled.get("life_indefinite"))
        for _ in range(30):
            sim.step()
            if not p.alive:
                break
        self.assertFalse(p.rolled.get("life_indefinite"))
        self.assertFalse(p.alive)      # age 早就过了 keepFrame=3，摘掉 indefinite 即刀落

    def test_homing_target_wraps_every_4(self):
        sim0 = self._sim(homing_fields(homingTarget=0))
        sim4 = self._sim(homing_fields(homingTarget=4))
        sim0.step()
        sim4.step()
        self.assertEqual(sim0.particles[0].user[Homing]["target_mode"],
                         sim4.particles[0].user[Homing]["target_mode"])

    def test_target_resolution_modes(self):
        """0=spawn point(em.origin) 1=model origin(em.host_origin) 2/3=世界原点(0,0,0)。"""
        class _FakeEm(object):
            origin = Vec3(1.0, 2.0, 3.0)
            host_origin = Vec3(4.0, 5.0, 6.0)

        em = _FakeEm()
        self.assertEqual(Homing._target(0, em), em.origin)
        self.assertEqual(Homing._target(1, em), em.host_origin)
        self.assertEqual(Homing._target(2, em), Vec3())
        self.assertEqual(Homing._target(3, em), Vec3())

    def test_notes_approximation_for_non_spawn_point_targets(self):
        sim1 = self._sim(homing_fields(homingTarget=1))
        sim1.step()
        self.assertTrue(any("Model Origin" in n for n in sim1.notes))

        sim2 = self._sim(homing_fields(homingTarget=2))
        sim2.step()
        self.assertTrue(any("World Origin" in n for n in sim2.notes))

        sim0 = self._sim(homing_fields(homingTarget=0))
        sim0.step()
        self.assertFalse(any("Model Origin" in n or "World Origin" in n
                            for n in sim0.notes))


class TestNoise(unittest.TestCase):
    """NOISE：两重随机取向的圆周振荡，以增量叠加到其它运动之上。"""

    @staticmethod
    def _sim(fields, config=None, velocity=None):
        return make_sim(spawn=spawn_fields(intervalFrame=1000),
                        life=life_fields(indefiniteLifespan=1),
                        velocity=velocity,
                        extra=[(NOISE, fields)], config=config)

    def test_sway_rides_on_velocity_instead_of_replacing_it(self):
        """有 VELOCITY3D 时，粒子相对直线轨迹的偏移恒等于振幅，直线运动本身不被抹去。"""
        sim = self._sim(noise_fields(lowFrequency=0.5, lowFrequencyWidth=10.0),
                        velocity=velocity_fields(baseAxis=1, speed=2.0))
        for n in range(1, 30):
            sim.step()
            straight = Vec3(0.0, 2.0 * n, 0.0)
            self.assertAlmostEqual((sim.particles[0].pos - straight).length(), 10.0,
                                   places=6)

    def test_hz_frequency_returns_after_one_second(self):
        """默认单位为每秒周期数：frequency=1 时，60 帧后回到同一位置。"""
        sim = self._sim(noise_fields(lowFrequency=1.0, lowFrequencyWidth=10.0))
        sim.step()
        start = sim.particles[0].pos.copy()
        for _ in range(60):
            sim.step()
        self.assertAlmostEqual((sim.particles[0].pos - start).length(), 0.0, places=6)
        sim.step()
        self.assertGreater((sim.particles[0].pos - start).length(), 0.1)

    def test_frequency_is_cycles_per_second(self):
        """frequency=15 即每秒 15 圈，60fps 下每 4 帧一圈。"""
        sim = self._sim(noise_fields(lowFrequency=15.0, lowFrequencyWidth=10.0))
        sim.step()
        start = sim.particles[0].pos.copy()
        for _ in range(4):
            sim.step()
        self.assertAlmostEqual((sim.particles[0].pos - start).length(), 0.0, places=6)

    def test_single_group_orbits_spawn_point_at_constant_radius(self):
        """闭式解：只开一组时，每一帧到生成点的距离都精确等于 lowFrequencyWidth。"""
        sim = self._sim(noise_fields(lowFrequency=90.0, lowFrequencyWidth=10.0))
        for _ in range(8):
            sim.step()
            self.assertAlmostEqual(sim.particles[0].pos.length(), 10.0, places=6)

    def test_zero_radius_group_is_a_true_no_op(self):
        """第二组半径为 0 时，不管它的转速多大，都不应该扰动第一组的轨迹
        （两边消耗的随机数序列长度必须一致，否则会连带打乱第一组抽到的轴/相位）。"""
        sim1 = self._sim(noise_fields(lowFrequency=45.0, lowFrequencyWidth=5.0))
        sim2 = self._sim(noise_fields(lowFrequency=45.0, lowFrequencyWidth=5.0,
                                      highFrequency=999.0, highFrequencyWidth=0.0))
        for _ in range(5):
            sim1.step()
            sim2.step()
        drift = (sim1.particles[0].pos - sim2.particles[0].pos).length()
        self.assertAlmostEqual(drift, 0.0, places=6)

    def test_two_groups_stay_within_triangle_inequality(self):
        """两组叠加：到生成点的距离必须落在 |r1-r2| ~ r1+r2 之间（三角不等式），
        且不会精确等于单组半径——否则说明第二组没真正参与叠加。"""
        sim = self._sim(noise_fields(lowFrequency=37.0, lowFrequencyWidth=6.0,
                                     highFrequency=101.0, highFrequencyWidth=3.0))
        saw_non_trivial = False
        for _ in range(20):
            sim.step()
            dist = sim.particles[0].pos.length()
            self.assertLessEqual(dist, 6.0 + 3.0 + 1e-6)
            self.assertGreaterEqual(dist, abs(6.0 - 3.0) - 1e-6)
            if abs(dist - 6.0) > 1e-3:
                saw_non_trivial = True
        self.assertTrue(saw_non_trivial)


class TestBlink(unittest.TestCase):
    """BLINK：双重正弦钳制到 MinRate ~ MaxRate 后乘入 alpha。"""

    @staticmethod
    def _sim(fields, config=None, with_life=True):
        return make_sim(spawn=spawn_fields(intervalFrame=1000),
                        life=life_fields(indefiniteLifespan=1) if with_life else None,
                        extra=[(BLINK, fields)], config=config)

    def test_is_simulated(self):
        sim = self._sim(blink_fields(lowFrequency=1.0, lowFrequencyWidth=1.0))
        sim.step()
        self.assertNotIn(BLINK, sim.em.unsupported)

    def test_alpha_follows_clamped_sine(self):
        """默认 0 ~ 1 钳制：alpha = clamp(sin(2·2π·age/60))，实机速度为 Hz 换算的 2 倍。"""
        sim = self._sim(blink_fields(lowFrequency=1.0, lowFrequencyWidth=1.0))
        for k in range(1, 70):
            sim.step()
            age = k - 1
            want = min(1.0, max(0.0, math.sin(2.0 * 2.0 * math.pi * age / 60.0)))
            self.assertAlmostEqual(sim.particles[0].alpha, want, places=6)

    def test_min_rate_is_a_floor(self):
        sim = self._sim(blink_fields(minAlphaRate=0.5, lowFrequency=1.0, lowFrequencyWidth=1.0))
        for _ in range(90):
            sim.step()
            self.assertGreaterEqual(sim.particles[0].alpha, 0.5 - 1e-9)

    def test_does_not_compound_without_life(self):
        """没有 LIFE 重写 alpha 时，恒定系数 0.5 不能逐帧累乘成 0.5^n。"""
        sim = self._sim(blink_fields(minAlphaRate=0.5, maxAlphaRate=0.5), with_life=False)
        for _ in range(20):
            sim.step()
        self.assertAlmostEqual(sim.particles[0].alpha, 0.5, places=9)

    def test_high_group_adds_to_low_group(self):
        sim = self._sim(blink_fields(minAlphaRate=-10.0, maxAlphaRate=10.0,
                                     lowFrequency=1.0, lowFrequencyWidth=0.3,
                                     highFrequency=7.0, highFrequencyWidth=0.2))
        w = 2.0 * 2.0 * math.pi / 60.0        # BLINK 频率按 Hz 换算后再乘 2
        for k in range(1, 30):
            sim.step()
            age = k - 1
            want = 0.3 * math.sin(w * age) + 0.2 * math.sin(7.0 * w * age)
            self.assertAlmostEqual(sim.particles[0].alpha, want, places=6)


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
        register(TURBULENCE)(_StageViolator)

    def test_unknown_attribute_is_reported_not_crashed(self):
        fake_hash = 0x7FFFFFF1
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(fake_hash, {})])
        sim.step()
        self.assertEqual(len(sim.particles), 1)
        self.assertIn(fake_hash, [h for h, _ in sim.unsupported])
        self.assertTrue(any("未模拟属性" in n for n in sim.notes))

    def test_disabled_attribute_is_skipped(self):
        cfg = SimConfig(disabled={VELOCITY3D})
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=99.0), config=cfg)
        sim.step()
        self.assertEqual(sim.particles[0].pos, Vec3())

    def test_stage_order_is_data(self):
        """VELOCITY3D 默认在 INTEGRATE，可被 order_override 挪走。"""
        cfg = SimConfig(order_override={VELOCITY3D: (FORCE, 5)})
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0), config=cfg)
        bound = [b for b in sim.bound if b.type_hash == VELOCITY3D][0]
        self.assertEqual((bound.stage, bound.order), (FORCE, 5))

    def test_strict_mode_catches_stage_violation(self):
        cfg = SimConfig(strict=True)
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(TURBULENCE, {})], config=cfg)
        with self.assertRaises(AssertionError) as ctx:
            for _ in range(3):
                sim.step()
        self.assertIn("FORCE", str(ctx.exception))

    def test_non_strict_mode_lets_it_through(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(TURBULENCE, {})], config=SimConfig(strict=False))
        for _ in range(3):
            sim.step()
        self.assertGreater(sim.particles[0].pos.x, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 确定性 / 渲染 pass
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminismAndRender(unittest.TestCase):

    def _trace(self, seed):
        sim = make_sim(
            spawn=spawn_fields(spawnNum=3, intervalFrame=2,
                               spawnNumJitter=2),
            life=life_fields(keepFrame=8, keepFrameJitter=4),
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
            spawn=spawn_fields(spawnNum=2, intervalFrame=3),
            life=life_fields(keepFrame=6),
            es3d=es3d_fields(shapeType=1, rangeXYZ=[0, 5, 0, 5, 0, 5]),
            velocity=velocity_fields(speed=1.0, speedJitter=1.0))
        first = [p.pos.as_tuple() for p in sim.run(20).particles]
        sim.reset()
        second = [p.pos.as_tuple() for p in sim.run(20).particles]
        self.assertEqual(first, second)

    def test_run_to_rewinds(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0))
        sim.run_to(10)
        forward = sim.particles[0].pos.as_tuple()
        sim.run_to(30)
        sim.run_to(10)                       # 倒退 → 自动 reset 重放
        self.assertEqual(sim.particles[0].pos.as_tuple(), forward)

    def test_build_render_is_side_effect_free(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=5, intervalFrame=1000),
                       life=life_fields(keepFrame=20),
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
        # 借 LIGHTNING（未实现的渲染体）撑出退化点，见 test_duration_is_exact_frame_count。
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(appearFrame=4, keepFrame=10),
                       velocity=velocity_fields(speed=0.0),
                       extra=[(LIGHTNING, {})])
        sim.run(3)
        self.assertAlmostEqual(sim.build_render()[0].color[3], 0.5, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 端到端：仓库自带的 archetype
# ─────────────────────────────────────────────────────────────────────────────

def _load_archetype(name):
    path = os.path.join(ARCHETYPE_DIR, name)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    from efx_format.assembly.preset import build_preset
    body = build_preset(data)
    return body.attr_blocks, body.timl_bytes


class TestArchetypeEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(ARCHETYPE_DIR):
            raise unittest.SkipTest("没有 presets/__archetypes__")

    def test_floating_particle_fire(self):
        """SPAWN: maxParticles=2 / perBurst=1 / interval=50，LIFE: keepFrame=60。

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
        """draw_chain 的 STRAINRIBBON 不模拟 → 应该被如实列出。"""
        blocks, timl = _load_archetype("draw_chain.json")
        sim = from_attr_blocks(blocks, timl)
        self.assertIn("STRAINRIBBON", [n for _h, n in sim.unsupported])
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

    def test_color_track_replaces_color_bytes(self):
        """Color 通道按 RGBA 四分量插值，经 raw() 作用于颜色字段。"""
        from efx_format.sim.resolve import FieldView
        tracks = self._tracks_with("BILLBOARD3D", "color", 1,
                                   [(0.0, (0.0, 0.0, 0.0, 255.0), 2),
                                    (10.0, (200.0, 100.0, 50.0, 255.0), 2)])
        r = self._resolver("BILLBOARD3D", billboard_fields(), tracks)
        self.assertEqual(FieldView(r, 0, 5).raw("color"), [100, 50, 25, 255])
        self.assertEqual(FieldView(r, 0, 5).raw("colorRange"),
                         billboard_fields()["colorRange"])      # 没有轨道的字段原样返回

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

    def test_timl_value_replaces_static_field(self):
        from efx_format.sim.resolve import FieldView
        tracks = self._tracks_with("VELOCITY3D", "speed", 1, [(0.0, 3.0, 2)])
        rep = self._resolver(raw=velocity_fields(speed=2.0), tracks=tracks)
        self.assertAlmostEqual(FieldView(rep, 0, 0).speed, 3.0)

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
        sim = make_sim(spawn=spawn_fields(emitterDelayFrame=30, intervalFrame=10),
                       life=life_fields(keepFrame=45))
        self.assertGreaterEqual(sim.suggested_duration(), 75)

    def test_fire_archetype(self):
        blocks, timl = _load_archetype("floating_particle_fire.json")
        sim = from_attr_blocks(blocks, timl)
        d = sim.suggested_duration()
        self.assertGreaterEqual(d, 60)        # 至少盖住一个粒子的寿命
        self.assertLess(d, 10000)

    def test_never_exceeds_max_frames(self):
        cfg = SimConfig(max_frames=50)
        sim = make_sim(spawn=spawn_fields(emitterDelayFrame=99999),
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
        p, _ = one_particle(frames=3, scaleanim=scaleanim_fields(sizeScalarAdd=0.1))
        for v in (p.scale.x, p.scale.y, p.scale.z):
            self.assertAlmostEqual(v, 1.0 + 0.3, places=6)

    def test_uniform_accel_decays_the_increment(self):
        """iv=0.02 / ia=0.99 / 60 帧 ≈ +0.91（floating_particle_fire 的实测组合）。"""
        p, _ = one_particle(frames=60, scaleanim=scaleanim_fields(
            sizeScalarAdd=0.02, sizeScalarAddCoef=0.99))
        expect = 1.0 + sum(0.02 * (0.99 ** n) for n in range(60))
        self.assertAlmostEqual(p.scale.x, expect, places=6)
        self.assertAlmostEqual(p.scale.x, 1.91, places=2)

    def test_per_axis_is_independent(self):
        p, _ = one_particle(frames=4, scaleanim=scaleanim_fields(
            sizeXAdd=0.5, sizeYAdd=0.25, sizeZAdd=0.0))
        self.assertAlmostEqual(p.scale.x, 1.0 + 2.0, places=6)
        self.assertAlmostEqual(p.scale.y, 1.0 + 1.0, places=6)
        self.assertAlmostEqual(p.scale.z, 1.0, places=6)

    def test_anim_update_start_delays_both_parts(self):
        """animUpdateStart 同时延迟整体与逐轴两组。"""
        p, _ = one_particle(frames=5, scaleanim=scaleanim_fields(
            sizeScalarAdd=0.1, sizeXAdd=1.0, animUpdateStart=3))
        self.assertAlmostEqual(p.scale.y, 1.0 + 0.2, places=6)        # 整体：只有 2 帧
        self.assertAlmostEqual(p.scale.x, 1.0 + 0.2 + 2.0, places=6)  # 逐轴：同样 2 帧

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
    """BILLBOARD3D 上 SCALEANIM 的收缩计时。

    整体那组每帧加在 scale 字段上；逐轴那组加在从 1 起的倍率上，与宽高无关。
    """

    def _frames_to_vanish(self, scaleanim, limit=600, width=1.0):
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(scale=30.0, width=width, height=1.0),
                       scaleanim=scaleanim)
        for n in range(1, limit + 1):
            sim.step()
            items = sim.build_render()
            if items and items[0].size.x <= 1e-9:   # 0.1 累加十次会剩个 1e-16
                return n
        return None

    def test_axis_speed_is_independent_of_width(self):
        """sizeXAdd=-1/60 → 不论宽度多少都在 60 帧缩到 0。"""
        for width in (1.0, 100.0, 500.0):
            n = self._frames_to_vanish(scaleanim_fields(sizeXAdd=-1.0 / 60.0), width=width)
            self.assertIn(n, (60, 61))
        self.assertEqual(self._frames_to_vanish(
            scaleanim_fields(sizeXAdd=-0.1), width=100.0), 10)

    def test_initial_speed_adds_to_scale(self):
        """sizeScalarAdd=-0.1 → scale 30→0，300 帧（= 5 秒 @60fps）。"""
        self.assertEqual(self._frames_to_vanish(
            scaleanim_fields(sizeScalarAdd=-0.1)), 300)


class TestRgbColoring(unittest.TestCase):
    """RGBFIRE / RGBWATER：两层颜色 + 各自的生命期时序块。"""

    def _color(self, block_hash, fields, frames=1, config=None):
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(block_hash, fields)], config=config)
        sim.run(frames)
        return sim.particles[0]

    def _item(self, block_hash, fields, frames=1):
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(block_hash, fields)])
        sim.run(frames)
        return sim.build_render()[0]

    # ── RGBFIRE ──────────────────────────────────────────────────────────────
    def test_two_layers_are_weighted_together(self):
        """两层强度相等 → 取中间色（红 + 蓝 → 半红半蓝）。"""
        p = self._color(RGBFIRE, rgbfire_fields())
        self.assertAlmostEqual(p.color[0], 0.5, places=5)
        self.assertAlmostEqual(p.color[1], 0.0, places=5)
        self.assertAlmostEqual(p.color[2], 0.5, places=5)

    def test_fire_factor_zero_turns_the_fire_layer_off(self):
        """fireFactor=0 → 只剩 smokeColor（语料证据见 behaviors/rgbfire.py）。"""
        p = self._color(RGBFIRE, rgbfire_fields(fireFactor=0.0))
        self.assertAlmostEqual(p.color[0], 0.0, places=5)
        self.assertAlmostEqual(p.color[2], 1.0, places=5)

    def test_smoke_factor_zero_turns_the_smoke_layer_off(self):
        """redChFactor=0 → 只剩 fireColor，跟 fireFactor 镜像对称。"""
        p = self._color(RGBFIRE, rgbfire_fields(redChFactor=0.0))
        self.assertAlmostEqual(p.color[0], 1.0, places=5)
        self.assertAlmostEqual(p.color[2], 0.0, places=5)

    def test_lerp_alpha_to_blue_rides_on_the_render_item(self):
        """贴图通道遮罩混合系数挂在渲染项上，供 glue 的 fragment shader 使用。"""
        it = self._item(RGBFIRE, rgbfire_fields(lerpAlphaToBlue=0.75))
        self.assertAlmostEqual(it.extra["rgbfire_lerp"], 0.75, places=5)
        self.assertIn("layers", it.extra)

    def test_color_rate_scales_the_tint(self):
        p = self._color(RGBFIRE, rgbfire_fields(colorRate=2.0))
        self.assertAlmostEqual(p.color[0], 1.0, places=5)
        self.assertAlmostEqual(p.color[2], 1.0, places=5)

    def test_alpha_factor_scales_alpha(self):
        p = self._color(RGBFIRE, rgbfire_fields(alphaFactor=0.25))
        self.assertAlmostEqual(p.alpha, 0.25, places=5)

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

    def test_water_lerp_gtob_rides_on_the_render_item(self):
        """贴图通道遮罩混合系数挂在渲染项上，供 glue 的 fragment shader 使用。"""
        it = self._item(RGBWATER, rgbwater_fields(waterLerpGtoB=0.6))
        self.assertAlmostEqual(it.extra["rgbwater_lerp"], 0.6, places=5)
        self.assertIn("layers", it.extra)
        self.assertNotIn("rgbfire_lerp", it.extra)


class TestAlphaCorrection(unittest.TestCase):
    """只往渲染项上挂参数——逐纹素的处理在 glue 的 fragment shader 里。"""

    def _item(self, **kw):
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
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
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
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
        """转不转只看 spin_velocity 的逐轴取值——**不看 typeFlag**
        （那个字段的位布局与全语料对不上，作用未知，见 behaviors/rotateanim.py）。"""
        p, _ = one_particle(frames=3, rotateanim=rotateanim_fields(
            rotationModeMask=2, spin_velocity=[0.0, 0.0, 2.0, 0.0, 0.0, 0.0]))
        self.assertEqual(p.rot.x, 0.0)
        self.assertAlmostEqual(p.rot.y, self.SIGN * 6.0, places=6)
        self.assertEqual(p.rot.z, 0.0)

    def test_spin_ignores_the_axis_mask(self):
        """菱形那条的实况：mask=16（旧读法一位都不命中）但 Z 轴确实在转。"""
        p, _ = one_particle(frames=4, rotateanim=rotateanim_fields(
            rotationModeMask=2, typeFlag=16,
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
        sim = make_sim(spawn=spawn_fields(spawnNum=60, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(rotationModeMask=1,
                                                    billboardRotation=10.0))
        sim.step()
        signs = {1 if p.rot.z > 0 else -1 for p in sim.particles}
        self.assertEqual(signs, {1, -1})

    def test_fixed_direction_mode_is_single_signed(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=60, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(rotationModeMask=0,
                                                    billboardRotation=10.0))
        sim.step()
        signs = {1 if p.rot.z > 0 else -1 for p in sim.particles}
        self.assertEqual(len(signs), 1)

    def test_plane_spin_reaches_the_plane_body(self):
        """PLANE 的横/纵轴要真的跟着转——渲染体不消费 p.rot 的话，改了也看不见。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       rotateanim=rotateanim_fields(
                           rotationModeMask=2, typeFlag=16,
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
                       spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.step()
        self.assertEqual(sim.em.origin, Vec3())
        self.assertEqual(sim.particles[0].pos, Vec3())
        self.assertTrue(any("静态变换未套用" in n for n in sim.notes))

    def test_apply_base_switch_moves_the_emitter(self):
        sim = make_sim(transform=transform3d_fields(
                           translate=[10.0, 0.0, 20.0, 0.0, 30.0, 0.0]),
                       spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       config=SimConfig(t3d_apply_base=True))
        sim.step()
        self.assertEqual(sim.em.origin, Vec3(10, 20, 30))
        self.assertEqual(sim.particles[0].pos, Vec3(10, 20, 30))

    def test_velocity_bitflag_gates_drift(self):
        # 60/秒 = 1/帧
        base = dict(translation_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        off = make_sim(transform=transform3d_fields(enableVelocityBitflag=0, **base),
                       spawn=spawn_fields(intervalFrame=1000), life=life_fields())
        on = make_sim(transform=transform3d_fields(enableVelocityBitflag=1, **base),
                      spawn=spawn_fields(intervalFrame=1000), life=life_fields())
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
            spawn=spawn_fields(intervalFrame=1000),
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
            spawn=spawn_fields(intervalFrame=1000),
            life=life_fields(indefiniteLifespan=1),
            velocity=velocity_fields(velocityType=3, speed=1.0,
                                     minMovementThreshold=10.0))
        sim.run(3)
        self.assertEqual(sim.particles[0].vel, Vec3())

    def test_velocities_are_per_second(self):
        """三组速度都是每秒：每秒 60 → 每帧 1。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               translation_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                               rotation_velocity=[0.0, 0.0, 600.0, 0.0, 0.0, 0.0],
                               scale_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        kw = dict(spawn=spawn_fields(intervalFrame=1000),
                  life=life_fields(indefiniteLifespan=1))
        sec = make_sim(transform=t, **kw)
        sec.run(10)
        self.assertAlmostEqual(sec.em.origin.x, 10.0, places=5)       # 1/帧 × 10
        # 10°/帧 × 10，照字面符号
        self.assertAlmostEqual(sec.em.rot_dynamic.y, 100.0, places=4)
        self.assertAlmostEqual(sec.em.scale_dynamic.x, 11.0, places=4)  # 1 + 1/帧 × 10

    def test_negative_scale_velocity_stops_at_zero(self):
        """缩放倍率不能穿过 0 变负——负倍率等于把生成形状镜像翻过去，
        表现上粒子会从收缩变成朝外飞（05 spell 那条就是这么暴露的）。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               scale_velocity=[-60.0, 0.0, -60.0, 0.0, -60.0, 0.0])
        sim = make_sim(transform=t, spawn=spawn_fields(intervalFrame=1000),
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
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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
                           scaleanim=scaleanim_fields(sizeScalarAdd=0.1))
        self.assertAlmostEqual(it.size.x, 100.0 * 2.0, places=4)

    def test_color_is_ubyte_scaled(self):
        it, _ = self._item(billboard=billboard_fields(color=[128, 0, 255, 255]))
        self.assertAlmostEqual(it.color[0], 128 / 255.0, places=6)
        self.assertAlmostEqual(it.color[1], 0.0, places=6)
        self.assertAlmostEqual(it.color[2], 1.0, places=6)

    def test_brightness_multiplies_rgb(self):
        it, _ = self._item(billboard=billboard_fields(color=[100, 100, 100, 255],
                                                      brightness=2.0, blendMode=1))
        self.assertAlmostEqual(it.color[0], 200 / 255.0, places=6)

    def test_brightness_needs_emissive(self):
        """「启用自发光」关着时亮度不生效。"""
        it, _ = self._item(billboard=billboard_fields(color=[100, 100, 100, 255],
                                                      brightness=2.0, blendMode=0))
        self.assertAlmostEqual(it.color[0], 100 / 255.0, places=6)

    def test_base_tint_is_own_color_times_brightness(self):
        """`base_tint` 是渲染体自己的颜色（供 glue 当两层染色的逐通道滤镜用），
        跟 item.color 分开存，见 sim_preview.py 的 `_layers_of`。"""
        it, _ = self._item(billboard=billboard_fields(color=[128, 0, 255, 255],
                                                      brightness=2.0, blendMode=1))
        r, g, b = it.extra["base_tint"]
        self.assertAlmostEqual(r, 128 / 255.0 * 2.0, places=6)
        self.assertAlmostEqual(g, 0.0, places=6)
        self.assertAlmostEqual(b, 1.0 * 2.0, places=6)

    def test_base_tint_is_independent_of_rgbfire_tint(self):
        """挂了 RGBFIRE 时 item.color 会把两层的代表色乘进去，但 `base_tint`
        只反映渲染体自己的颜色，不含 RGBFIRE 的贡献——两者在 glue 里分开使用。"""
        it, sim = self._item(billboard=billboard_fields(color=[255, 0, 0, 255]),
                             extra=[(RGBFIRE, rgbfire_fields())])
        r, g, b = it.extra["base_tint"]
        self.assertAlmostEqual(r, 1.0, places=5)
        self.assertAlmostEqual(g, 0.0, places=5)
        self.assertAlmostEqual(b, 0.0, places=5)
        self.assertIn("layers", it.extra)

    def test_color_range_lerps_per_particle(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=60, intervalFrame=1000),
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
        sim = make_sim(spawn=spawn_fields(spawnNum=20, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(color=[0, 0, 0, 255],
                                                  colorRange=[255, 255, 255, 255],
                                                  useColorRange=0))
        sim.step()
        self.assertEqual({i.color[0] for i in sim.build_render()}, {0.0})

    def test_emissive_toggle_does_not_pick_the_blend(self):
        """「启用自发光」（blendMode）只管亮度；没有 SHADERSETTINGS 时一律 Alpha。"""
        for flag in (0, 1):
            it, _ = self._item(billboard=billboard_fields(blendMode=flag))
            self.assertEqual(it.blend, "ALPHA")

    def test_blend_state_picks_the_blend(self):
        """SHADERSETTINGS.blendStateType 覆盖渲染体（实机四象限贴图对拍的映射）。"""
        expect = {0: "OPAQUE", 1: "ALPHA", 2: "ADDITIVE", 3: "INV_MULTIPLY",
                  4: "OPAQUE", 5: "ALPHA", 7: "ADDITIVE", 8: "MULTIPLY", 9: "ALPHA",
                  10: "OPAQUE"}
        for state, mode in expect.items():
            it, _ = self._item(billboard=billboard_fields(blendMode=1),
                               extra=[(SHADERSETTINGS, {"blendStateType": state})])
            self.assertEqual(it.blend, mode, state)

    def test_blend_state_6_draws_nothing(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(),
                       extra=[(SHADERSETTINGS, {"blendStateType": 6})])
        sim.step()
        self.assertEqual(sim.build_render(), [])

    def test_alpha_comes_from_life(self):
        it, _ = self._item(frames=3, billboard=billboard_fields(),
                           life=life_fields(appearFrame=4, keepFrame=20))
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
        _it, sim = self._item(billboard=billboard_fields(correctColorNo=3))
        self.assertTrue(any("EPV" in n for n in sim.notes))

    def test_render_body_writes_no_particle_state(self):
        """RENDER_BODY 阶段不许改粒子状态——strict 模式会查。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
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
        self.assertEqual(sim.build_render()[0].blend, "ADDITIVE")   # blendStateType=2

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
    """color / colorRange 是 RGBA 四元组的两端，所有通道共用一个系数插值，
    第 4 通道当 alpha 用并乘上 LIFE 的淡入淡出。"""

    BLACK = [0, 0, 0, 0]
    WHITE = [255, 255, 255, 255]

    def _sim(self, n=40, config=None, life=None, **bb):
        f = billboard_fields(**bb)
        return make_sim(spawn=spawn_fields(spawnNum=n, intervalFrame=1000),
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

    def test_channels_share_one_factor(self):
        items = self._items(color=list(self.BLACK), colorRange=list(self.WHITE),
                            useColorRange=1)
        self.assertGreater(len({tuple(it.color) for it in items}), 1)   # 粒子之间不同
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

    def test_life_fade_multiplies_the_colour_alpha(self):
        """LIFE 的淡入 × 颜色自带的 alpha —— 两者相乘，不是二选一。"""
        life = life_fields(appearFrame=10, keepFrame=50, vanishFrame=0)
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000), life=life,
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
        sim = make_sim(spawn=spawn_fields(spawnNum=8, intervalFrame=1000),
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
                    spawn=spawn_fields(spawnNum=30, intervalFrame=1000),
                    life=life_fields(indefiniteLifespan=1),
                    extra=[(hash_, fields(**kw))])
                sim.step()
                cols = {tuple(it.color) for it in sim.build_render()}
                self.assertGreater(len(cols), 1)


class TestPtLifeActionScene(unittest.TestCase):
    """PTLIFE 在某个生命阶段触发 ACTION → SimScene 建子实例；
    子实例跟着父粒子走，父粒子消亡后失去 parent 就地留下（用户实机）。"""

    def _scene(self, ptlife=None, parent_life=None, child_life=None,
               parent_velocity=None, targets=None, config=None, actions=None,
               child_spawn=None):
        """两个 entry：0 = 父（带 PTLIFE），1 = 子（一个静止的 billboard）。"""
        parent_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, parent_life or life_fields(keepFrame=10)),
            (PTLIFE, ptlife or ptlife_fields()),
            (BILLBOARD3D, billboard_fields()),
        ]
        if parent_velocity is not None:
            parent_blocks.append((VELOCITY3D, parent_velocity))
        child_blocks = [
            (SPAWN, child_spawn or spawn_fields(intervalFrame=1000)),
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
                         parent_life=life_fields(keepFrame=5))
        sc.run(4)
        self.assertEqual(sc.instance_count, 1)        # 还活着，没触发
        sc.run(4)
        self.assertEqual(sc.instance_count, 2)        # 死了 → 触发

    def test_sustain_fires_after_fade_in(self):
        sc = self._scene(ptlife=ptlife_fields(status=2),
                         parent_life=life_fields(appearFrame=6, keepFrame=40))
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
                         parent_life=life_fields(keepFrame=8),
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

    # ── 父旋转带着子实例一起转（螺旋类特效的基础）─────────────────────────────
    def test_rotating_parent_spins_up_the_children_it_spawns(self):
        """父实例的 TRANSFORM3D.rotation_velocity 转起来 → 之后陆续触发的每个
        子实例都该带上父此刻的旋转角（`em.host_rotation`，见 scene.py::_follow），
        子实例 VELOCITY3D 的方向字段因此跟着偏转。不同时刻出生的子实例应该拿到
        不同方向——这正是「父转、多个子特效各自偏转」画出螺旋的机制。"""
        parent_blocks = [
            (SPAWN, spawn_fields(spawnNum=1, intervalFrame=5, loopNum=0)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (TRANSFORM3D, transform3d_fields(
                enableVelocityBitflag=1,
                rotation_velocity=[0.0, 0.0, 90.0, 0.0, 0.0, 0.0])),
            (PTLIFE, ptlife_fields(status=0)),
        ]
        child_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (VELOCITY3D, velocity_fields(baseAxis=2, speed=1.0)),
        ]
        templates = {0: EntryTemplate(0, parent_blocks), 1: EntryTemplate(1, child_blocks)}
        sc = SimScene(templates, {0: [ActionTarget(1)]}, root_key=0,
                      config=SimConfig(seed=1))

        sc.run(4)      # 父转了 4 帧 → 第一个子实例带着一个不为零的旋转角出生
        first_child = [i for i in sc.instances if i.key == 1][-1]
        first_vel = first_child.sim.em.particles[0].vel.copy()

        sc.run(20)     # 父继续转，第二批粒子触发第二个子实例
        later = [i for i in sc.instances if i.key == 1]
        self.assertGreaterEqual(len(later), 2)
        second_vel = later[-1].sim.em.particles[0].vel.copy()

        # baseAxis=2（游戏 +Z，与 Y 轴旋转正交）：父转了多少度，方向就该偏多少，
        # 两个出生时刻不同 → 旋转角不同 → 初速度方向不该相同。
        self.assertGreater(abs(first_vel.x - second_vel.x) + abs(first_vel.z - second_vel.z),
                           1e-3)

    def test_child_instances_roll_their_own_jitter(self):
        """同一 entry 的多个子实例各自抽取 TRANSFORM3D 的随机量，而不是全部相同。"""
        parent_blocks = [
            (SPAWN, spawn_fields(spawnNum=4, intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (PTLIFE, ptlife_fields(status=0)),
        ]
        child_blocks = [
            (TRANSFORM3D, transform3d_fields(rotate=[0.0, 0.0, 0.0, 360.0, 0.0, 0.0])),
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
        ]
        templates = {0: EntryTemplate(0, parent_blocks), 1: EntryTemplate(1, child_blocks)}
        sc = SimScene(templates, {0: [ActionTarget(1)]}, root_key=0,
                      config=SimConfig(seed=1))
        sc.run(3)
        rots = {round(i.em.rot_dynamic.y, 6) for i in sc.instances if i.key == 1}
        self.assertGreaterEqual(len(rots), 3)

    # ── Action 的 Size / Position ────────────────────────────────────────────
    def test_action_position_offsets_the_child(self):
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         targets=[ActionTarget(1, position=Vec3(0.0, 50.0, 0.0))])
        sc.run(4)
        child = sc.instances[1]
        parent_p = sc.root.sim.em.particles[0]
        self.assertAlmostEqual(child.em.host_origin.y, parent_p.pos.y + 50.0, places=4)

    def test_action_size_scales_the_whole_child_effect(self):
        """PLAYEMITTER 的 Size 是**整体缩放**：位置和尺寸都跟着缩，绕锚点。

        用户原话：Size 0.5 时「和距离相关的都会缩到 0.5 倍」——t3d 平移 +200 在
        Size 0.5 的 action 下实际就是 +100。
        ⚠ 旧实现是把 Size 乘进 `em.scale_dynamic`，那只影响 EMITTERSHAPE3D 的生成点，
        对没有 ES3D 的 entry（wp11_017 里那些 aura 网格）完全不起作用。
        """
        def run(size):
            sc = self._scene(ptlife=ptlife_fields(status=0),
                             parent_life=life_fields(indefiniteLifespan=1),
                             child_life=life_fields(indefiniteLifespan=1),
                             targets=[ActionTarget(1, position=Vec3(0.0, 40.0, 0.0),
                                                   size=Vec3(size, size, size))])
            sc.run(3)
            child = sc.instances[1]
            it = [i for i in sc.build_render()
                  if i.extra.get("instance") == child.iid][0]
            anchor = child.em.host_origin
            return (it.pos - anchor).length(), it.size.x

        d1, s1 = run(1.0)
        d2, s2 = run(0.5)
        self.assertAlmostEqual(s2, s1 * 0.5, places=5)      # 尺寸缩一半
        self.assertAlmostEqual(d2, d1 * 0.5, places=5)      # 离锚点的距离也缩一半

    def test_emitter_outline_matches_where_particles_land(self):
        """生成区域线框必须罩得住真正的落点——两边共用 `_region`，不该走样。

        用球形 + 横向扫描 90°（四分之一扇区）：线框的包围盒既要覆盖所有粒子，
        也要跟着扫描角度只占一个象限（整圈的话 x/z 两侧都会有点）。
        """
        blocks = [
            (SPAWN, {"maxParticles": 200, "spawnNum": 40,
                     "intervalFrame": 1, "loopNum": 0,
                     "revivalLoop": 1}),
            (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
            (EMITTERSHAPE3D, {"shapeType": 1,          # 球
                              "rangeXYZ": [15.0, 200.0, 15.0, 200.0, 15.0, 200.0],
                              "scanAngleHorizontal": 90.0,
                              "scanAngleVertical": 0.0}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 10, "height": 10, "scale": 1}),
        ]
        sim = Simulator(blocks, b"", SimConfig())
        sim.run(6)
        pts = sim.emitter_outline()
        self.assertTrue(pts, "球形应当有线框")
        self.assertEqual(len(pts) % 2, 0, "线框是成对的点")

        def bounds(vs):
            return (min(v.x for v in vs), max(v.x for v in vs),
                    min(v.y for v in vs), max(v.y for v in vs),
                    min(v.z for v in vs), max(v.z for v in vs))

        ox0, ox1, oy0, oy1, oz0, oz1 = bounds(pts)
        # 外边界 = 偏移 15 + 尺寸 200
        self.assertAlmostEqual(max(abs(ox0), abs(ox1)), 215.0, delta=1.0)
        # 扫描 90° → 只占一个象限：横向两轴各只跨「半径」而不是「直径」
        self.assertLessEqual(ox1 - ox0, 215.0 * 1.1)
        self.assertLessEqual(oz1 - oz0, 215.0 * 1.1)
        # 纵向没限制 → 上下都到 ±215
        self.assertGreaterEqual(oy1 - oy0, 215.0 * 1.5)

        live = [p.pos for p in sim.em.particles]
        self.assertTrue(live)
        px0, px1, py0, py1, pz0, pz1 = bounds(live)
        eps = 1.0
        self.assertGreaterEqual(px0, ox0 - eps)
        self.assertLessEqual(px1, ox1 + eps)
        self.assertGreaterEqual(py0, oy0 - eps)
        self.assertLessEqual(py1, oy1 + eps)
        self.assertGreaterEqual(pz0, oz0 - eps)
        self.assertLessEqual(pz1, oz1 + eps)

    def test_flowmap_loop_outputs_strength_and_phase(self):
        """循环：强度照字段值输出，相位按每秒 speed 轮推进，标记为两层循环。"""
        def items(frames):
            blocks = [
                (SPAWN, {"maxParticles": 1, "spawnNum": 1,
                         "intervalFrame": 0, "loopNum": 1,
                         "revivalLoop": 1}),
                (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
                (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                               "blendMode": 0, "width": 100, "height": 100,
                               "scale": 1, "applicationRule": 0x04,
                               "flowSpeed": 1.0, "flowStrength": 0.2,
                               "flowSpeedCoef": 1.0, "flowStrengthCoef": 1.0}),
            ]
            sim = Simulator(blocks, b"", SimConfig())
            out = []
            for t in frames:
                while sim.frame < t:
                    sim.step()
                out.append(sim.build_render()[0].extra)
            return out

        a, b = items((5, 20))
        self.assertAlmostEqual(a["flowmap"], 0.2)
        self.assertAlmostEqual(b["flowmap_phase"] - a["flowmap_phase"], 15 / 60.0, places=6)
        self.assertTrue(a["flowmap_loop"])

    def test_flowmap_zero_speed_is_a_static_distortion(self):
        """速度为 0 时相位停在 0，循环两层中只剩 p = 0.5 的一层，扭曲幅度由强度决定。"""
        blocks = [
            (SPAWN, {"maxParticles": 1, "spawnNum": 1, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 100, "height": 100,
                           "scale": 1, "applicationRule": 0x04,
                           "flowSpeed": 0.0, "flowStrength": 1.0,
                           "flowSpeedCoef": 1.0, "flowStrengthCoef": 1.0}),
        ]
        sim = Simulator(blocks, b"", SimConfig())
        sim.run(10)
        extra = sim.build_render()[0].extra
        self.assertAlmostEqual(extra["flowmap"], 1.0)
        self.assertEqual(extra["flowmap_phase"], 0.0)
        self.assertTrue(extra["flowmap_loop"])

    def test_flowmap_play_once_holds_at_the_end(self):
        """播放一次后停止：单层，相位 0 → 1 后停住，不跳回起点；逆向模式 1 → 0。"""
        blocks = [
            (SPAWN, {"maxParticles": 1, "spawnNum": 1, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 100, "height": 100,
                           "scale": 1, "applicationRule": 0x04 | 0x08,
                           "flowSpeed": 1.0, "flowStrength": 1.0,
                           "flowSpeedCoef": 1.0, "flowStrengthCoef": 1.0}),
        ]
        def phases(rule):
            blocks[2][1]["applicationRule"] = rule
            sim = Simulator(blocks, b"", SimConfig())
            sim.run(30)             # 一轮 60 帧，第 30 帧在半程
            mid = sim.build_render()[0].extra
            sim.run(60)
            return mid, sim.build_render()[0].extra

        mid, end = phases(0x04 | 0x08)
        self.assertFalse(mid["flowmap_loop"])
        self.assertAlmostEqual(mid["flowmap_phase"], 0.5, places=1)
        self.assertEqual(end["flowmap_phase"], 1.0)
        self.assertAlmostEqual(end["flowmap"], 1.0)
        _mid, end = phases(0x04 | 0x08 | 0x10)
        self.assertEqual(end["flowmap_phase"], 0.0)
        # 逆向模式只在播放一次时生效
        _mid, end = phases(0x04 | 0x10)
        self.assertAlmostEqual(end["flowmap_phase"], 1.5, places=1)

    def test_flowmap_off_leaves_nothing_on_the_item(self):
        """没开 bit 0x04 就完全不挂——glue 据此决定要不要分流动桶。"""
        blocks = [
            (SPAWN, {"maxParticles": 1, "spawnNum": 1, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 100, "height": 100, "scale": 1,
                           "applicationRule": 0,           # 位没开
                           "flowSpeed": 1.0, "flowStrength": 0.2}),
        ]
        sim = Simulator(blocks, b"", SimConfig())
        sim.run(5)
        self.assertNotIn("flowmap", sim.build_render()[0].extra)

    def test_refraction_turns_the_body_into_a_multiply_pass(self):
        """REFRACTION：源色换成背后画面 × 颜色 × brightness；Alpha 混合下即背景 × 颜色。"""
        blocks = [
            (SPAWN, {"maxParticles": 1, "spawnNum": 1, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 60, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 0, 0, 255], "brightness": 10,
                           "blendMode": 1, "width": 100, "height": 100, "scale": 1}),
            (REFRACTION, {"typeFlag": 2, "distortionType": 0,
                          "alphaBlend": 0.0}),
        ]
        sim = Simulator(blocks, b"", SimConfig())
        sim.run(3)
        it = sim.build_render()[0]
        self.assertEqual(it.blend, "REFRACT")       # 无 SHADERSETTINGS = Alpha 混合
        self.assertAlmostEqual(it.color[0], 10.0, places=5)   # 红 × brightness
        self.assertAlmostEqual(it.color[1], 0.0, places=5)
        self.assertEqual(it.extra["refraction"], (0, 0.0))
        self.assertFalse([n for n in sim.notes if "REFRACTION" in n])

    def test_refraction_with_additive_blend_brightens(self):
        """加法混合下折射为 背景 × (1 + 颜色)。"""
        blocks = [
            (SPAWN, {"maxParticles": 1, "spawnNum": 1, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 60, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 100, "height": 100, "scale": 1}),
            (SHADERSETTINGS, {"blendStateType": 2}),
            (REFRACTION, {"typeFlag": 2, "distortionType": 0, "alphaBlend": 0.0}),
        ]
        sim = Simulator(blocks, b"", SimConfig())
        sim.run(3)
        self.assertEqual(sim.build_render()[0].blend, "REFRACT_ADD")

    def test_refraction_hands_flowmap_and_params_to_the_preview(self):
        """面片上的畸变位移与 alphaBlend 已由预览画出：不报 note，流动贴图参数照常带出。"""
        def run(flow, blend):
            blocks = [
                (SPAWN, {"maxParticles": 1, "spawnNum": 1,
                         "intervalFrame": 0, "loopNum": 1,
                         "revivalLoop": 1}),
                (LIFE, {"keepFrame": 60, "indefiniteLifespan": 1}),
                (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                               "blendMode": 1, "width": 100, "height": 100,
                               "scale": 1, "applicationRule": 0x04 if flow else 0,
                               "flowStrength": 1.0}),
                (REFRACTION, {"typeFlag": 2, "distortionType": 1,
                              "alphaBlend": blend}),
            ]
            sim = Simulator(blocks, b"", SimConfig())
            sim.run(2)
            return sim, sim.build_render()[0]

        for flow, blend in ((False, 0.0), (True, 0.0), (True, 0.35)):
            sim, it = run(flow, blend)
            self.assertEqual([n for n in sim.notes if "REFRACTION" in n], [])
            self.assertEqual(it.extra["refraction"], (1, blend))
            self.assertEqual(bool(it.extra.get("flowmap")), flow)

    def test_scale_item_array_path_matches_per_point(self):
        """条带的数组形态（RibbonStrip）走 `_scale_item` 要和逐点路完全一致。

        ⚠ 这条不靠场景跑出来——语料里 PLAYEMITTER 的 Size 94% 是 1.0，缩放分支
        平时根本不执行，真错了也要等某个特定文件才暴露。
        """
        from efx_format.sim.scene import _scale_item
        from efx_format.sim.state import RenderItem, RibbonStrip
        numpy = _trail.numpy_backend()
        if numpy is None:
            self.skipTest("环境里没有 numpy，数组形态不会被创建")

        n = 7
        pos = numpy.array([[i * 1.5, i * -2.0, 3.0 + i] for i in range(n)],
                          dtype="f8")
        half = numpy.array([1.0 + 0.1 * i for i in range(n)], dtype="f8")
        alpha = numpy.array([0.2 + 0.05 * i for i in range(n)], dtype="f8")
        anchor = Vec3(2.0, -1.0, 0.5)
        s = Vec3(0.4, 1.7, -0.3)

        arr = RenderItem(kind="RIBBON", pos=Vec3())
        arr.points = RibbonStrip(pos.copy(), half.copy(), alpha.copy())
        _scale_item(arr, anchor, s)

        lst = RenderItem(kind="RIBBON", pos=Vec3())
        lst.points = [(Vec3(pos[i][0], pos[i][1], pos[i][2]),
                       float(half[i]), float(alpha[i])) for i in range(n)]
        _scale_item(lst, anchor, s)

        self.assertEqual(len(arr.points), n)
        for (qa, ha, aa), (qb, hb, ab) in zip(arr.points, lst.points):
            self.assertAlmostEqual(qa.x, qb.x, places=9)
            self.assertAlmostEqual(qa.y, qb.y, places=9)
            self.assertAlmostEqual(qa.z, qb.z, places=9)
            self.assertAlmostEqual(ha, hb, places=9)
            self.assertAlmostEqual(aa, ab, places=9)

    def test_child_applies_its_own_static_transform(self):
        """子实例没有宿主替它摆位 → 它得自己套 TRANSFORM3D 的静态变换。

        根实例照旧不套（Blender 里 transform_sync 已经摆好，再套就是双份位移）。
        """
        t = transform3d_fields(translate=[0.0, 0.0, 70.0, 0.0, 0.0, 0.0])
        blocks = [
            (TRANSFORM3D, t),
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (BILLBOARD3D, billboard_fields()),
        ]
        parent = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (PTLIFE, ptlife_fields(status=0)),
            (BILLBOARD3D, billboard_fields()),
        ]
        sc = SimScene({0: EntryTemplate(0, parent), 1: EntryTemplate(1, blocks)},
                      {0: [ActionTarget(1)]}, root_key=0, config=SimConfig(seed=1))
        sc.run(3)
        child = sc.instances[1]
        self.assertTrue(child.sim.config.t3d_apply_base)
        self.assertFalse(sc.root.sim.config.t3d_apply_base)
        self.assertAlmostEqual(child.em.drift.y, 70.0, places=4)

    # ── 安全阀 ───────────────────────────────────────────────────────────────
    def test_depth_limit_stops_recursion(self):
        """自指的 action（entry 0 触发指向自己的 action）→ 靠深度上限收住。"""
        blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
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
                         child_life=life_fields(keepFrame=3),
                         config=SimConfig(seed=1, child_cull_grace=5))
        sc.run(6)
        self.assertEqual(sc.instance_count, 2)
        sc.run(40)
        self.assertEqual(sc.instance_count, 1)       # 只剩根

    def test_a_child_that_has_not_fired_yet_is_not_culled(self):
        """SPAWN.emitterDelayFrame 比空转宽限还长 → 不能在它开火前就把实例回收了。

        用户的 `wp11_017` 里 `explpt` 就是这样：延迟 60 帧，而空转宽限 30 帧，
        表现成「这个子特效完全不触发」。判据是**有没有吐过粒子**：一个都没吐过的
        实例是在等，不是空转。
        """
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         child_spawn=spawn_fields(emitterDelayFrame=60,
                                                  intervalFrame=1000),
                         child_life=life_fields(indefiniteLifespan=1),
                         config=SimConfig(seed=1, child_cull_grace=5))
        sc.run(40)
        self.assertEqual(sc.instance_count, 2)      # 还在等，别收
        sc.run(30)
        child = [i for i in sc.instances if i.depth > 0][0]
        self.assertGreater(child.em.spawned_total, 0)   # 第 60 帧确实开火了

    def test_pending_children_do_eventually_time_out(self):
        """但也不能无限等——一个永远不发的子实例最后还是要收掉。"""
        sc = self._scene(ptlife=ptlife_fields(status=0),
                         parent_life=life_fields(indefiniteLifespan=1),
                         child_spawn=spawn_fields(emitterDelayFrame=100000,
                                                  intervalFrame=1000),
                         config=SimConfig(seed=1, child_cull_grace=5,
                                          child_pending_grace=20))
        sc.run(15)
        self.assertEqual(sc.instance_count, 2)
        sc.run(20)
        self.assertEqual(sc.instance_count, 1)

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


class TestPtCollisionActionScene(unittest.TestCase):
    """PTCOLLISION 反弹后停留（physicsEnum=3、bounceCount=0）：粒子越过 Y=0（游戏坐标系，
    对应 Blender Z=0）→ 位置/速度冻结在落地点，且触发一次 ACTION。"""

    def _scene(self, ptcollision=None, velocity=None, life=None, config=None):
        parent_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life or life_fields(indefiniteLifespan=1)),
            (VELOCITY3D, velocity or velocity_fields(baseAxis=4, speed=1.0)),
            (PTCOLLISION, ptcollision or ptcollision_fields()),
            (BILLBOARD3D, billboard_fields()),
        ]
        child_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (BILLBOARD3D, billboard_fields()),
        ]
        templates = {0: EntryTemplate(0, parent_blocks), 1: EntryTemplate(1, child_blocks)}
        actions = {0: [ActionTarget(1)]}
        return SimScene(templates, actions, root_key=0, config=config or SimConfig(seed=1))

    def test_ptcollision_is_simulated(self):
        sc = self._scene()
        sc.step()
        self.assertNotIn("PTCOLLISION", [n for _h, n in sc.unsupported])

    def test_ie_index_minus_one_does_nothing(self):
        sc = self._scene(ptcollision=ptcollision_fields(ieIndex=-1))
        sc.run(10)
        self.assertEqual(sc.instance_count, 1)

    def test_landing_freeze_happens_even_without_action(self):
        """ieIndex=-1 只关掉「触发 ACTION」，落地冻结是独立的物理表现，照常生效。"""
        sc = self._scene(ptcollision=ptcollision_fields(ieIndex=-1),
                         velocity=velocity_fields(baseAxis=4, speed=1.0))
        sc.run(1)
        parent_p = sc.root.sim.em.particles[0]
        parent_p.pos.y = 5.0
        parent_p.user[PtCollision]["prev_y"] = 5.0
        while parent_p.pos.y > 0.0 and sc.frame < 200:
            sc.run(1)
        self.assertEqual(parent_p.pos.y, 0.0)
        pos_at_landing = parent_p.pos.copy()
        sc.run(20)
        self.assertEqual(parent_p.pos, pos_at_landing)    # 没有 ACTION，但照样冻结
        self.assertEqual(sc.instance_count, 1)            # 且确实没有触发子实例

    def test_crossing_ground_fires_once(self):
        """默认出生点 Y=0，本 behavior 只关心「越过」——手动把粒子摆到地面上方，
        再让 baseAxis=4（游戏 -Y，下）的匀速下落把它带过 Y=0，验证那一帧触发。"""
        sc = self._scene(velocity=velocity_fields(baseAxis=4, speed=1.0))
        sc.run(1)
        parent_p = sc.root.sim.em.particles[0]
        parent_p.pos.y = 5.0
        parent_p.user[PtCollision]["prev_y"] = 5.0

        while parent_p.pos.y > 0.0 and sc.frame < 200:
            sc.run(1)
        sc.run(1)                                        # 让触发请求被 scene 消化
        self.assertEqual(parent_p.pos.y, 0.0)             # 落地即钉死在 Y=0（不是任意负值）
        self.assertEqual(sc.instance_count, 2)            # 触发了一次

        frame_at_trigger = sc.frame
        pos_at_landing = parent_p.pos.copy()
        sc.run(20)                                        # 继续跑，不应再触发第二次
        self.assertEqual(sc.instance_count, 2)
        self.assertGreater(sc.frame, frame_at_trigger)
        self.assertEqual(parent_p.pos, pos_at_landing)     # 冻结：位置完全不再变化

    def test_landed_particle_freezes_velocity_too(self):
        """落地后 p.vel 清零——不只是位置被钉住，后续帧也不再有速度可言
        （避免下游读 vel 的逻辑，如条带/速度线，显示一个仍在下落的假象）。"""
        sc = self._scene(velocity=velocity_fields(baseAxis=4, speed=1.0))
        sc.run(1)
        parent_p = sc.root.sim.em.particles[0]
        parent_p.pos.y = 5.0
        parent_p.user[PtCollision]["prev_y"] = 5.0
        while parent_p.pos.y > 0.0 and sc.frame < 200:
            sc.run(1)
        self.assertEqual(parent_p.vel.x, 0.0)
        self.assertEqual(parent_p.vel.y, 0.0)
        self.assertEqual(parent_p.vel.z, 0.0)

    def test_spawning_at_ground_never_triggers(self):
        """边缘情况：粒子一开始就在 Y<=0（这里出生点即 Y=0），不算「越过」，
        即便之后继续往下（负 Y）走也不该触发——`prev_y` 从没经历过 >0。"""
        sc = self._scene(velocity=velocity_fields(baseAxis=4, speed=1.0))
        sc.run(20)
        parent_p = sc.root.sim.em.particles[0]
        self.assertLess(parent_p.pos.y, 0.0)              # 确实一路往下走了
        self.assertEqual(sc.instance_count, 1)            # 但从未触发


class TestFadeBy(unittest.TestCase):
    """FADEBYDEPTH / FADEBYANGLE：按相机修改渲染项 alpha。粒子固定在原点。"""

    def _alpha(self, block, fields, cam, config=None):
        from efx_format.sim.state import ViewContext
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
                       life=life_fields(indefiniteLifespan=1),
                       billboard=billboard_fields(), extra=[(block, fields)],
                       config=config)
        sim.run(1)
        fwd = Vec3(-cam[0], -cam[1], -cam[2]).normalized()
        view = ViewContext(cam_pos=Vec3(*cam), cam_forward=fwd)
        return sim.build_render(view)[0].color[3]

    def _depth(self, d, config=None):
        f = {"typeFlag": 0, "nearFadeInStart": 100.0, "nearFadeInEnd": 200.0,
             "farFadeOutStart": 1000.0, "farFadeOutEnd": 2000.0}
        return self._alpha(FADEBYDEPTH, f, (0.0, 0.0, -d), config)

    def test_depth_fade_ramps(self):
        self.assertAlmostEqual(self._depth(50.0), 0.0)
        self.assertAlmostEqual(self._depth(150.0), 0.5)
        self.assertAlmostEqual(self._depth(500.0), 1.0)
        self.assertAlmostEqual(self._depth(1500.0), 0.5)
        self.assertAlmostEqual(self._depth(3000.0), 0.0)

    def _angle(self, deg, flags=0, cutoff=10.0, fade=30.0, min_alpha=0.0, mode="outer"):
        f = {"typeFlag": 0, "coneVisibilityFlags": flags, "cutoffConeAngle": cutoff,
             "fadeConeAngle": fade, "minAlpha": min_alpha, "rotation": [0.0, 0.0, 0.0],
             "baseAxis": 1, "rotOrder": 4}
        a = math.radians(deg)
        cam = (500.0 * math.sin(a), 500.0 * math.cos(a), 0.0)   # 与 +Y 夹角为 deg
        return self._alpha(FADEBYANGLE, f, cam, SimConfig(fade_cone_mode=mode))

    def test_angle_cone(self):
        self.assertAlmostEqual(self._angle(5.0), 0.0)
        self.assertAlmostEqual(self._angle(20.0), 0.5)
        self.assertAlmostEqual(self._angle(60.0), 1.0)
        self.assertAlmostEqual(self._angle(170.0), 1.0)
        self.assertAlmostEqual(self._angle(20.0, min_alpha=0.5), 0.75)

    def test_angle_flags(self):
        self.assertAlmostEqual(self._angle(175.0, flags=1), 0.0)       # 双锥
        self.assertAlmostEqual(self._angle(5.0, flags=2), 1.0)         # 排除锥体
        self.assertAlmostEqual(self._angle(5.0, flags=4), 1.0)         # bit2 单独也反转
        self.assertAlmostEqual(self._angle(5.0, flags=5), 0.0)         # bit0 置位时 bit2 无效

    def test_angle_width_mode(self):
        self.assertAlmostEqual(self._angle(25.0, cutoff=10.0, fade=30.0, mode="width"), 0.5)


class TestTransform3DTiml(unittest.TestCase):
    """TRANSFORM3D 的 A0 轨道逐帧改发射器的动态平移 / 旋转 / 缩放（只施加相对静态值的增量）。"""

    def _sim(self, field, comp, keys, config=None, **t3d):
        from efx_format.sim.resolve import Curve, TimlTracks
        from efx_format.timl.names import BLOCK_TO_TLP, FIELD_TO_DT
        tracks = TimlTracks()
        dt = FIELD_TO_DT[("TRANSFORM3D", field)][comp][0]
        tracks._curves[(0, BLOCK_TO_TLP["TRANSFORM3D"], dt)] = Curve(keys)
        tracks.ok = True
        return Simulator([(TRANSFORM3D, transform3d_fields(**t3d))], b"",
                         config or SimConfig(), tracks=tracks)

    def test_translate_curve_moves_by_delta_only(self):
        sim = self._sim("translate", 0, [(0.0, 50.0, 2), (10.0, 150.0, 2)],
                        translate=[50.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        sim.run(11)                                  # 帧 0..10
        self.assertAlmostEqual(sim.em.drift.x, 100.0)
        sim.run(5)                                   # 曲线夹取在末端，不再累加
        self.assertAlmostEqual(sim.em.drift.x, 100.0)

    def test_translate_delta_undoes_static_rotation(self):
        """entry 静态绕 Y 转 90° 时，父空间 +X 的位移在局部坐标里不能再是 +X。"""
        sim = self._sim("translate", 0, [(0.0, 0.0, 2), (10.0, 100.0, 2)],
                        rotate=[0.0, 0.0, 90.0, 0.0, 0.0, 0.0])
        sim.run(11)
        d = sim.em.drift
        self.assertAlmostEqual(abs(d.x), 0.0, places=4)
        self.assertAlmostEqual(abs(d.z), 100.0, places=4)

    def test_rotate_curve_adds_to_rot_dynamic(self):
        sim = self._sim("rotate", 1, [(0.0, 0.0, 2), (10.0, 90.0, 2)])
        sim.run(11)
        self.assertAlmostEqual(sim.em.rot_dynamic.y, 90.0)

    def test_resize_curve_scales_relative_to_static(self):
        sim = self._sim("resize", 0, [(0.0, 0.0, 2), (10.0, 4.0, 2)],
                        resize=[2.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        sim.run(1)
        self.assertAlmostEqual(sim.em.scale_dynamic.x, 0.0)      # 从 0 长起
        sim.run(10)
        self.assertAlmostEqual(sim.em.scale_dynamic.x, 2.0)      # 4 / 静态 2
        self.assertAlmostEqual(sim.em.scale_dynamic.y, 1.0)


class TestRendererTimlKeepsJitter(unittest.TestCase):
    """渲染体带 TIML 时，尺寸 = 曲线值 + 出生时抽到的随机偏移，随机部分不丢。"""

    def test_billboard_scale_jitter_survives_timl(self):
        from efx_format.sim.resolve import Curve, TimlTracks
        from efx_format.timl.names import BLOCK_TO_TLP, FIELD_TO_DT
        tracks = TimlTracks()
        dt = FIELD_TO_DT[("BILLBOARD3D", "scale")][0][0]
        tracks._curves[(1, BLOCK_TO_TLP["BILLBOARD3D"], dt)] = Curve([(0.0, 1.0, 2), (10.0, 1.0, 2)])
        tracks.ok = True
        blocks = [(SPAWN, spawn_fields(intervalFrame=1000)),
                  (LIFE, life_fields(indefiniteLifespan=1)),
                  (BILLBOARD3D, billboard_fields(scale=1.0, scaleJitter=2.0, width=10.0, height=10.0))]
        sim = Simulator(blocks, b"", SimConfig(), tracks=tracks)
        sim.run(2)
        p = sim.particles[0]
        offset = p.rolled["bb_scale"] - 1.0
        self.assertGreater(offset, 0.0)
        self.assertAlmostEqual(sim.build_render()[0].size.x, 10.0 * (1.0 + offset), places=5)


class TestA1TrackWithDecay(unittest.TestCase):
    """VELOCITY3D / SCALEANIM / ROTATEANIM 的 A1 轨道：每帧基准 = 曲线值 + 抖动偏移，
    再乘以衰减系数按帧的累积乘积。"""

    def _particle(self, block, fields, curves, frames):
        from efx_format.sim.resolve import Curve, TimlTracks
        from efx_format.timl.names import BLOCK_TO_TLP, FIELD_TO_DT
        name = {VELOCITY3D: "VELOCITY3D", SCALEANIM: "SCALEANIM",
                ROTATEANIM: "ROTATEANIM"}[block]
        tracks = TimlTracks()
        for (field, comp), keys in curves.items():
            dt = FIELD_TO_DT[(name, field)][comp][0]
            tracks._curves[(1, BLOCK_TO_TLP[name], dt)] = Curve(keys)
        tracks.ok = True
        blocks = [(SPAWN, spawn_fields(intervalFrame=1000)),
                  (LIFE, life_fields(indefiniteLifespan=1)), (block, fields)]
        sim = Simulator(blocks, b"", SimConfig(), tracks=tracks)
        sim.run(frames)
        return sim.particles[0]

    def test_speed_curve_times_accumulated_coef(self):
        p = self._particle(VELOCITY3D, velocity_fields(speed=10.0, speedCoef=0.5),
                           {("speed", 0): [(0.0, 10.0, 2), (1.0, 20.0, 2)]}, 2)
        self.assertAlmostEqual(p.vel.y, 20.0 * 0.25)         # 曲线 20 × 0.5²

    def test_gravity_curve_is_per_frame_gravity(self):
        p = self._particle(VELOCITY3D, velocity_fields(speed=0.0),
                           {("gravity", 0): [(0.0, 2.0, 2), (10.0, 2.0, 2)]}, 3)
        self.assertAlmostEqual(p.vel.y, -6.0)

    def test_scale_speed_curve_times_accel(self):
        p = self._particle(SCALEANIM, scaleanim_fields(sizeScalarAdd=1.0,
                                                       sizeScalarAddCoef=0.5),
                           {("sizeScalarAdd", 0): [(0.0, 1.0, 2), (1.0, 3.0, 2)]}, 2)
        self.assertAlmostEqual(p.scale.x, 1.0 + 1.0 + 3.0 * 0.5)

    def test_billboard_rotation_curve(self):
        p = self._particle(ROTATEANIM, rotateanim_fields(),
                           {("billboardRotation", 0): [(0.0, 0.0, 2), (2.0, 4.0, 2)]}, 3)
        self.assertAlmostEqual(p.rot.z, -(0.0 + 2.0 + 4.0))  # 自旋角取负

    def test_spin_curve_drives_axis_with_zero_static(self):
        p = self._particle(ROTATEANIM, rotateanim_fields(rotationModeMask=2),
                           {("spin_velocity", 1): [(0.0, 3.0, 2), (10.0, 3.0, 2)]}, 2)
        self.assertAlmostEqual(p.rot.y, -6.0)


class TestPlaneScaleAnim(unittest.TestCase):

    def test_scaleanim_adds_to_plane_size_fields(self):
        sim = make_sim(spawn=spawn_fields(spawnNum=1, intervalFrame=10000),
                       life=life_fields(indefiniteLifespan=1),
                       scaleanim=scaleanim_fields(sizeXAdd=0.1),
                       extra=[(PLANE, plane_fields())])
        sim.run(3)
        item = sim.build_render()[0]
        self.assertAlmostEqual(item.size.x, 130.0)
        self.assertAlmostEqual(item.size.y, 100.0)


class TestPtCollisionPhysics(unittest.TestCase):
    """PTCOLLISION 的物理类型、反弹、地面偏移与触地触发模式。"""

    def _drop(self, frames=40, height=5.0, gravity=0.3, **kw):
        """让一颗粒子从 height 高处以每帧 1 的初速下落（带重力），返回 (scene, 粒子)。"""
        parent_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, kw.pop("life", None) or life_fields(indefiniteLifespan=1)),
            (VELOCITY3D, velocity_fields(baseAxis=4, speed=1.0, gravity=gravity)),
            (PTCOLLISION, ptcollision_fields(**kw)),
            (BILLBOARD3D, billboard_fields()),
        ]
        child_blocks = [
            (SPAWN, spawn_fields(intervalFrame=1000)),
            (LIFE, life_fields(indefiniteLifespan=1)),
            (BILLBOARD3D, billboard_fields()),
        ]
        templates = {0: EntryTemplate(0, parent_blocks),
                     1: EntryTemplate(1, child_blocks)}
        sc = SimScene(templates, {0: [ActionTarget(1)]}, root_key=0,
                      config=SimConfig(seed=1))
        sc.run(1)
        p = sc.root.sim.em.particles[0]
        p.pos.y = height
        p.user[PtCollision]["prev_y"] = height
        sc.run(frames)
        return sc, p

    def test_fall_through_passes_ground(self):
        sc, p = self._drop(physicsEnum=0, bounceCount=3)
        self.assertLess(p.pos.y, -20.0)
        self.assertEqual(sc.instance_count, 2)        # 穿过地面那一次仍算触地

    def test_bounce_reverses_vertical_velocity_by_summed_elasticity(self):
        sc, p = self._drop(frames=6, gravity=0.0, physicsEnum=3, bounceCount=2,
                           bounceElasticity=0.5, bounceElasticityMultiplier=0.3,
                           ieIndex=-1)
        self.assertAlmostEqual(p.vel.y, 0.8)
        self.assertAlmostEqual(p.vel_free.y, 0.8)
        self.assertGreater(p.pos.y, 0.0)

    def test_stay_after_bounces_used_up(self):
        sc, p = self._drop(frames=60, physicsEnum=3, bounceCount=1,
                           bounceElasticity=0.5, ieIndex=-1)
        self.assertEqual(p.user[PtCollision]["impacts"], 2)
        self.assertEqual(p.pos.y, 0.0)
        self.assertEqual(p.vel.y, 0.0)

    def test_kill_after_bounces(self):
        sc, p = self._drop(frames=60, physicsEnum=1, bounceCount=1,
                           bounceElasticity=0.5, ieIndex=-1)
        self.assertFalse(p.alive)

    def test_fade_runs_life_fade_out_on_ground(self):
        sc, p = self._drop(frames=7, physicsEnum=2, bounceCount=0, ieIndex=-1,
                           life=life_fields(indefiniteLifespan=1, vanishFrame=10))
        self.assertTrue(p.alive)
        self.assertEqual(p.pos.y, 0.0)
        self.assertLess(p.alpha, 1.0)
        sc.run(15)
        self.assertFalse(p.alive)

    def test_bounce_then_fall_through(self):
        sc, p = self._drop(frames=60, physicsEnum=4, bounceCount=1,
                           bounceElasticity=0.5, ieIndex=-1)
        self.assertEqual(p.user[PtCollision]["impacts"], 2)
        self.assertLess(p.pos.y, -10.0)

    def test_projection_offset_raises_ground(self):
        sc, p = self._drop(frames=10, height=20.0, physicsEnum=3, projectionOffset=12.0,
                           ieIndex=-1)
        self.assertEqual(p.pos.y, 12.0)

    def test_trigger_modes(self):
        common = dict(frames=80, physicsEnum=3, bounceCount=2, bounceElasticity=0.7)
        self.assertEqual(self._drop(impactPlayTriggerMode=0, **common)[0].instance_count, 4)
        self.assertEqual(self._drop(impactPlayTriggerMode=1, impactPlayTriggerCount=1,
                                    **common)[0].instance_count, 2)
        sc, p = self._drop(impactPlayTriggerMode=2, **common)
        self.assertEqual(p.user[PtCollision]["impacts"], 3)
        self.assertEqual(sc.instance_count, 2)


class TestParentOptions(unittest.TestCase):
    """跟随发射器 + 停止追踪帧数（其余字段刻意未实现，只 note）。"""

    def _sim(self, parent=None, frames=10, drift=(0.0, 0.0, 0.0), **kw):
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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

    # ── relationRot/relationScl：跟父级的旋转/缩放，不是跟玩家/地图 ─────────────
    def test_relation_rot_off_by_default_leaves_the_path_straight(self):
        """relationRot 全 0（fixture 默认）→ 不跟发射器自转，直线飞行不变。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               rotation_velocity=[0.0, 0.0, 0.0, 0.0, 90.0, 0.0])
        vel = velocity_fields(baseAxis=0, speed=2.0, velocityType=0)
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1),
                        transform=t, velocity=vel, frames=1)
        p = sim.particles[0]
        vel0 = p.vel.copy()
        for _ in range(20):
            sim.step()
        self.assertAlmostEqual((p.vel.normalized() - vel0.normalized()).length(), 0.0,
                               places=4)

    def test_relation_rot_on_curves_the_path_into_a_spiral(self):
        """relationRot=(1,1,1) + 发射器持续自转 → 已经飞出去的粒子被带着一起转，
        飞行方向逐帧偏转（速度大小不变），直线因此弯成螺旋——同用户反馈的
        「自转的发射器应该带着它扔出去的东西一起转」。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               rotation_velocity=[0.0, 0.0, 0.0, 0.0, 90.0, 0.0])
        vel = velocity_fields(baseAxis=0, speed=2.0, velocityType=0)
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    relationRot=[1, 1, 1]),
                        transform=t, velocity=vel, frames=1)
        p = sim.particles[0]
        vel0 = p.vel.copy()
        for _ in range(20):
            sim.step()
        # 速率不变，只转方向
        self.assertAlmostEqual(p.vel.length(), vel0.length(), places=3)
        self.assertGreater((p.vel.normalized() - vel0.normalized()).length(), 0.3)

    def test_relation_scl_on_scales_offset_and_velocity_with_the_emitter(self):
        """relationScl=(1,1,1) + 发射器动态缩放 → 粒子相对发射器原点的偏移与自身
        速度都按同一比例缩放（同 relationRot 的「跟父级」模型，换成缩放）。"""
        t = transform3d_fields(enableVelocityBitflag=1,
                               scale_velocity=[2.0, 0.0, 2.0, 0.0, 2.0, 0.0])
        vel = velocity_fields(baseAxis=0, speed=1.0, velocityType=0)
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    relationScl=[1, 1, 1]),
                        transform=t, velocity=vel, frames=3)
        p = sim.particles[0]
        before = p.pos.x
        speed_before = p.vel.length()
        for _ in range(10):
            sim.step()
        self.assertGreater(p.pos.x, before)          # 偏移被放大跟着涨
        self.assertGreater(p.vel.length(), speed_before)   # 速度也按比例放大

    # ── 跟随发射器时粒子大小取 TRANSFORM3D 尺寸，与 relationScl 无关 ──────────
    def _size_x(self, parent, transform, frames=1):
        sim = self._sim(parent=parent, transform=transform, frames=frames,
                        billboard=billboard_fields())
        return sim.build_render()[0].size.x

    def test_follow_scales_particle_size_by_base_resize(self):
        """尺寸全 2 → 粒子大小 2 倍，relationScl 为 0 也一样。"""
        t1 = transform3d_fields()
        t2 = transform3d_fields(resize=[2.0, 0.0, 2.0, 0.0, 2.0, 0.0])
        for scl in ([0, 0, 0], [1, 1, 1]):
            par = parentoptions_fields(particleUseLocal=1, relationScl=scl)
            self.assertAlmostEqual(self._size_x(par, t2),
                                   2.0 * self._size_x(par, t1), places=5)

    def test_follow_scales_particle_size_by_scale_velocity(self):
        t = transform3d_fields(enableVelocityBitflag=1,
                               scale_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # +1/帧
        par = parentoptions_fields(particleUseLocal=1)
        base = self._size_x(par, transform3d_fields(), frames=5)
        self.assertAlmostEqual(self._size_x(par, t, frames=5), 6.0 * base, places=4)

    def test_without_follow_particle_takes_birth_size(self):
        """不跟随：出生时取发射器尺寸，之后缩放速度不再影响已发出的粒子。"""
        par = parentoptions_fields(particleUseLocal=0)
        t2 = transform3d_fields(resize=[2.0, 0.0, 2.0, 0.0, 2.0, 0.0])
        self.assertAlmostEqual(self._size_x(par, t2),
                               2.0 * self._size_x(par, transform3d_fields()), places=5)
        grow = transform3d_fields(enableVelocityBitflag=1,
                                  scale_velocity=[60.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(self._size_x(par, grow, frames=5),
                               self._size_x(par, grow, frames=1), places=5)

    def test_invalid_particle_scale_ignores_emitter_size(self):
        """invalidParticleScale 开启：大小不跟发射器尺寸，位置照常跟随。"""
        t2 = transform3d_fields(resize=[2.0, 0.0, 2.0, 0.0, 2.0, 0.0])
        for follow in (0, 1):
            par = parentoptions_fields(particleUseLocal=follow, invalidParticleScale=1)
            self.assertAlmostEqual(self._size_x(par, t2),
                                   self._size_x(par, transform3d_fields()), places=5)
        sim = self._sim(parent=parentoptions_fields(particleUseLocal=1,
                                                    invalidParticleScale=1),
                        drift=(5.0, 0.0, 0.0), frames=10)
        self.assertAlmostEqual(sim.particles[0].pos.x, sim.em.origin.x, places=4)


class TestEmitterRotationReachesParticles(unittest.TestCase):
    """TRANSFORM3D 的 rotation_velocity / scale_velocity 要真的作用到发出去的东西上
    （在这之前 em.rotation/em.scale 只是累积着没人用）。"""

    def _spawn_at(self, transform, frames=4, es3d=None, velocity=None):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000, emitterDelayFrame=3),
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
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0))
        sim.run(10)
        self.assertEqual(sim.particles[0].trail, [])
        self.assertEqual(sim.em.trail, [])

    def test_recorded_when_a_body_needs_it(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       velocity=velocity_fields(speed=1.0),
                       extra=[(RIBBON, ribbon_fields())])
        sim.run(10)
        # 两条轨迹都是每帧一个点：跑 10 帧 → 10 个点（粒子在第 0 帧出生）
        self.assertEqual(len(sim.particles[0].trail), 10)
        self.assertEqual(len(sim.em.trail), 10)

    def test_trail_is_capped(self):
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
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
        sim = make_sim(spawn=spawn_fields(spawnNum=5, intervalFrame=1000),
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
        """对照组：渲染体存在但没实现时（同 LIGHTNING）才该出现退化点。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       extra=[(LIGHTNING, {})])
        sim.run(3)
        self.assertEqual([i.kind for i in sim.build_render()], ["POINT"])

    def test_truly_bodyless_renders_nothing(self):
        """PTBEHAVIOR、或压根没挂任何渲染体分类属性的 entry（纯 Action 召唤枢纽等）——
        跟显式的 DUMMY 一样明确不画，不该凭空冒出退化点。"""
        sim = make_sim(spawn=spawn_fields(spawnNum=5, intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.run(5)
        self.assertEqual(len(sim.particles), 5)      # 粒子照常存在
        self.assertEqual(sim.build_render(), [])     # 但什么都不画


# ─────────────────────────────────────────────────────────────────────────────
# PLANE
# ─────────────────────────────────────────────────────────────────────────────

class TestPlane(unittest.TestCase):

    def _item(self, frames=1, **kw):
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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
        self.assertEqual(it.blend, "ALPHA")
        self.assertAlmostEqual(it.color[2], 1.0, places=6)
        self.assertAlmostEqual(it.color[0], 0.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# RIBBON
# ─────────────────────────────────────────────────────────────────────────────

class TestRibbon(unittest.TestCase):

    def _sim(self, ribbon=None, frames=20, **kw):
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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
        """默认按帧：条带覆盖最近 细分数-1 帧的轨迹，length 不参与（取个大值验证）。"""
        spans = {}
        for n in (2, 5):
            sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=999.0,
                                                 subdivisionCount=n),
                            velocity=velocity_fields(speed=10.0), frames=40)
            pts = [q for q, _w, _a in sim.build_render()[0].points]
            spans[n] = (pts[-1] - pts[0]).length()
        self.assertAlmostEqual(spans[2], 10.0, delta=0.5)      # 1 帧 × 10/帧
        self.assertAlmostEqual(spans[5], 40.0, delta=0.5)      # 4 帧 × 10/帧

    def test_trail_frames_mode_exceeds_default_history_cap(self):
        """细分数超过 config.trail_max（64）时，位置历史按需加长，条带不被截短。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, subdivisionCount=140),
                        velocity=velocity_fields(speed=1.0), frames=200)
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 139.0, delta=1.0)

    def test_trail_mode_ignores_spawn_anchor_offset(self):
        """轨迹跟随模式下 spawnAnchorOffset 不生效：头部（base）恒等于粒子当前位置。

        试过按"往前甩"（原样照抄 RIGID 的读法）和"往后拖"（在粒子当前位置之外
        再往身后偏一截）两种解读，都会导致粒子刚出生、历史还没积累够时条带的头
        被钉死在出生点、追上理论长度才开始动——用户实机核对：从出生起就应该
        一直贴着发射器走，没有这段"先冻结再追上"的过渡（真实案例：
        wp11_011.efx 的 08 trail）。故对轨迹跟随模式直接不套用这个字段，
        跟 anchor=0 时完全一样，不管 anchor 取什么值。"""
        base = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=10.0,
                                              subdivisionCount=8, spawnAnchorOffset=0.0),
                         velocity=velocity_fields(speed=10.0, baseAxis=0))
        anchored = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=10.0,
                                                  subdivisionCount=8, spawnAnchorOffset=1.0),
                             velocity=velocity_fields(speed=10.0, baseAxis=0))
        pts_base = [q for q, _w, _a in base.build_render()[0].points]
        pts_anchored = [q for q, _w, _a in anchored.build_render()[0].points]
        p = anchored.particles[0]
        self.assertAlmostEqual(pts_anchored[0].x, p.pos.x, places=3)    # 头部 = 当前位置
        for qa, qb in zip(pts_anchored, pts_base):
            self.assertAlmostEqual(qa.x, qb.x, places=4)                # 跟 anchor=0 一样

    def test_trail_mode_follows_particle_motion(self):
        """粒子自己动 → 沿粒子轨迹（pick_trail 的 auto 分支）。

        默认 subdiv=5 → 最近 4 帧 × 10/帧 = 40。
        """
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=0, length=50.0),
                        velocity=velocity_fields(speed=10.0))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        span = (pts[-1] - pts[0]).length()
        self.assertAlmostEqual(span, 40.0, delta=1.0)

    def test_trail_falls_back_to_emitter_when_particle_is_static(self):
        """blade_trail 那种粒子不动的情形，轨迹得取发射器的。"""
        sim = self._sim(
            ribbon=ribbon_fields(ribbonMode=0, length=40.0),
            transform=transform3d_fields(
                enableVelocityBitflag=1,
                translation_velocity=[300.0, 0.0, 0.0, 0.0, 0.0, 0.0]))   # 5/帧
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        # 默认 subdiv=5 → 发射器最近 4 帧 × 5/帧 = 20
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 20.0, delta=1.0)

    def test_rigid_mode_is_a_straight_fixed_length_strip(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=60.0, baseAxis=1))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 60.0, places=4)
        for q in pts:                                  # baseAxis=1 → 沿 +Y
            self.assertAlmostEqual(q.x, 0.0, places=6)

    def test_rigid_mode_extends_along_base_axis(self):
        """伸展方向直接取 baseAxis，不取负：baseAxis=4（下）→ 自发射器向下伸展。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=60.0, baseAxis=4))
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        self.assertAlmostEqual(pts[-1].y - pts[0].y, -60.0, places=4)

    def test_rigid_mode_turns_with_emitter_spin(self):
        """默认 parent 档：条带随发射器一起转。粒子在 +X 半径上、静止朝 +Y，转动后仍与
        逆时针切向同向——反转自转方向时领先的一端随之互换。"""
        for spin in (1200.0, -1200.0):                     # ±20°/帧
            for axis, sign in ((1, 1.0), (4, -1.0)):
                sim = make_sim(
                    extra=[(PARENTOPTIONS, parentoptions_fields(
                               particleUseLocal=1, relationRot=[1, 1, 1])),
                           (RIBBON, ribbon_fields(ribbonMode=1, length=60.0,
                                                  baseAxis=axis))],
                    transform=transform3d_fields(
                        enableVelocityBitflag=1,
                        rotation_velocity=[0.0, 0.0, 0.0, 0.0, spin, 0.0]),
                    spawn=spawn_fields(intervalFrame=1000),
                    life=life_fields(indefiniteLifespan=1))
                sim.step()
                pt = sim.particles[0]
                # 放到绕圈半径上，并与出生时已计入朝向的发射器旋转对齐
                from efx_format.sim.behaviors._common import emitter_rotate
                pt.pos = emitter_rotate(sim.em, Vec3(10.0, 0.0, 0.0))
                for _ in range(5):
                    sim.step()
                r = pt.pos
                ccw = Vec3(-r.y, r.x, 0.0).normalized()    # 绕 +Z 逆时针的切向
                pts = [q for q, _w, _a in sim.build_render()[0].points]
                d = (pts[-1] - pts[0]).normalized()
                self.assertGreater(d.dot(ccw) * sign, 0.99, (spin, axis))

    def test_fade_length_switch_off_counts_both_spans_as_one(self):
        """enableFadeLength=0：两个渐隐长度按 1 计，本地填的值不起作用。"""
        kw = dict(ribbonMode=1, subdivisionCount=5, base_opacity=0.0, tip_opacity=1.0,
                  base_fade_length=0.2, tip_fade_length=0.0)
        off = self._sim(ribbon=ribbon_fields(enableFadeLength=0, **kw))
        on = self._sim(ribbon=ribbon_fields(enableFadeLength=1, **kw))
        a_off = [a for _q, _w, a in off.build_render()[0].points]
        a_on = [a for _q, _w, a in on.build_render()[0].points]
        for i, a in enumerate(a_off):                  # 跨度 1：由 0 线性升到 1
            self.assertAlmostEqual(a, i / 4.0, places=6)
        self.assertAlmostEqual(a_on[1], 1.0, places=6)  # 跨度 0.2：u=0.25 处已回到不透明

    def test_rigid_mode_length_grows_with_scaleanim_y(self):
        """SCALEANIM 的 Y 轴增量要拉伸 RIBBON 的长度（p.scale.y），不能只对宽度生效
        （X=width/Y=length，同 BILLBOARD3D/PLANE 的 X=width/Y=height 约定）。"""
        base = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=100.0), frames=1)
        it0 = base.build_render()[0]
        grown = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=100.0),
                          scaleanim=scaleanim_fields(sizeYAdd=1.0, sizeYAddCoef=1.0),
                          frames=10)
        it1 = grown.build_render()[0]
        self.assertAlmostEqual(it0.size.y, 100.0, places=3)
        self.assertGreater(it1.size.y, it0.size.y + 5.0)
        self.assertAlmostEqual(it1.size.x, it0.size.x, places=3)   # 宽度不受影响

    def test_direction_follows_host_rotation_when_triggered(self):
        """作为斩击扳机这类 PtLife 父实例触发的子 entry，父实例此刻的旋转
        （`em.host_rotation`）要整体转动 RIBBON 的伸展方向——否则不管触发者转到
        哪个角度，子 entry 永远只朝本地固定方向伸，看起来就像"朝向被重置"。
        """
        sim = make_sim(extra=[(RIBBON, ribbon_fields(ribbonMode=1, length=60.0,
                                                     baseAxis=0))],
                       spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1))
        sim.em.host_rotation.z = 90.0        # 模拟被旋转过的触发者
        sim.step()
        pts = [q for q, _w, _a in sim.build_render()[0].points]
        span = pts[-1] - pts[0]
        # baseAxis=0 的本地方向在 X 轴上；绕 Z 转 90° 之后应当基本转到 Y 轴上
        self.assertLess(abs(span.x), 1.0)
        self.assertGreater(abs(span.y), 50.0)

    def test_rgbfire_on_ribbon_keeps_the_ribbon_color(self):
        """RGBFIRE 的两层颜色交给 shader 按通道遮罩解码，RIBBON 自身颜色记在 base_tint
        里一起乘上，不会被两层颜色顶掉。"""
        sim = make_sim(
            extra=[(RIBBON, ribbon_fields(ribbonMode=1, color=[0, 0, 255, 255])),
                  (RGBFIRE, rgbfire_fields())],   # 默认 fireColor=红 smokeColor=蓝，跟上面不是同一回事
            spawn=spawn_fields(intervalFrame=1000),
            life=life_fields(indefiniteLifespan=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertIn("layers", it.extra)
        self.assertIn("rgbfire_lerp", it.extra)
        tint = it.extra["base_tint"]
        self.assertGreater(tint[2], tint[0])          # 蓝仍然是主导通道
        self.assertGreater(it.color[2], it.color[0])

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

    def test_opacity_is_an_endpoint_fade_not_a_lengthwise_lerp(self):
        """base_/tip_opacity 是**端点值**，中间恒为实心。

        用户实机：两端都填 0 的条带在游戏里看得见，只是两边渐隐——所以这两个字段
        不能当成「沿全长从 base 插到 tip」，那会把整条带子算成 alpha=0（0.7.0 之前
        就是这么算的，suidao1 的三条 trail 在预览里整条消失）。
        """
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, subdivisionCount=21,
                                             base_opacity=0.0, tip_opacity=0.0,
                                             base_fade_length=0.3,
                                             tip_fade_length=0.4))
        alphas = [a for _q, _w, a in sim.build_render()[0].points]
        self.assertAlmostEqual(alphas[0], 0.0, places=6)       # 两个端点透明
        self.assertAlmostEqual(alphas[-1], 0.0, places=6)
        self.assertAlmostEqual(max(alphas), 1.0, places=6)     # 中间实心
        # 渐隐区之外（u ∈ [0.3, 0.6]）整段都是 1
        for i in range(7, 13):                                 # u = 0.35 ~ 0.60
            self.assertAlmostEqual(alphas[i], 1.0, places=6)
        self.assertAlmostEqual(alphas[3], 0.5, places=6)        # u=0.15，后端渐隐过半

    def test_opacity_taper_one_end_only(self):
        """经典拖尾写法：后端硬边、前端渐隐。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, subdivisionCount=11,
                                             base_opacity=1.0, tip_opacity=0.0,
                                             tip_fade_length=0.4))
        alphas = [a for _q, _w, a in sim.build_render()[0].points]
        self.assertAlmostEqual(alphas[0], 1.0, places=6)
        self.assertAlmostEqual(alphas[-1], 0.0, places=6)
        self.assertAlmostEqual(alphas[5], 1.0, places=6)       # u=0.5 还在渐隐区外

    def test_zero_fade_length_means_a_hard_edge(self):
        """渐隐长度 0 = 硬边：端点值不起作用，整条恒 1。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, base_opacity=0.0,
                                             tip_opacity=0.0,
                                             base_fade_length=0.0,
                                             tip_fade_length=0.0))
        alphas = [a for _q, _w, a in sim.build_render()[0].points]
        self.assertTrue(all(abs(a - 1.0) < 1e-6 for a in alphas), alphas)

    def test_rigid_ribbon_follows_the_velocity(self):
        """开启朝向运动方向的定长面片沿速度伸展（base→tip 指向速度），baseAxis 不起作用。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, baseAxis=1, length=50.0,
                                             faceVelocity=1),
                        velocity=velocity_fields(velocityType=0, baseAxis=0, speed=5.0,
                                                 speedCoef=1.0))
        pts = [q for q, _w, _x in sim.build_render()[0].points]
        d = (pts[-1] - pts[0]).normalized()
        self.assertAlmostEqual(d.x, 1.0, places=5)

    def test_rigid_ribbon_without_face_velocity_keeps_base_axis(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, baseAxis=1, length=50.0,
                                             fixedDirection=1),
                        velocity=velocity_fields(velocityType=0, baseAxis=0, speed=5.0,
                                                 speedCoef=1.0))
        pts = [q for q, _w, _x in sim.build_render()[0].points]
        d = (pts[-1] - pts[0]).normalized()
        self.assertAlmostEqual(d.y, 1.0, places=5)

    def test_lock_initial_velocity_ignores_gravity(self):
        """朝向运动方向 + 锁定初速度：重力压弯速度后条带仍指向出生时的方向。"""
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=50.0, faceVelocity=1,
                                             lockInitialVelocity=1),
                        velocity=velocity_fields(velocityType=0, baseAxis=0, speed=5.0,
                                                 speedCoef=1.0, gravity=1.0))
        self.assertLess(sim.particles[0].vel.y, -1.0)       # 速度已被重力压弯
        pts = [q for q, _w, _x in sim.build_render()[0].points]
        d = (pts[-1] - pts[0]).normalized()
        self.assertAlmostEqual(d.x, 1.0, places=5)

    def test_still_rigid_ribbon_facing_velocity_draws_nothing(self):
        sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, faceVelocity=1),
                        velocity=velocity_fields(speed=0.0))
        self.assertFalse([it for it in sim.build_render() if it.kind != "NONE"])

    def _stretch(self, frames, **rb):
        rb.setdefault("ribbonMode", 1)
        rb.setdefault("faceVelocity", 1)
        rb.setdefault("stretchFromSpawn", 1)
        rb.setdefault("length", 50.0)
        rb.setdefault("spawnAnchorOffset", 0.7)
        sim = self._sim(ribbon=ribbon_fields(**rb), frames=frames,
                        velocity=velocity_fields(velocityType=0, baseAxis=1, speed=1.0,
                                                 speedCoef=1.0))
        pts = [q for q, _w, _x in sim.build_render()[0].points]
        return sim, pts

    def test_stretch_keeps_the_base_at_the_spawn_point(self):
        """base 固定在生成点，tip 在粒子前方锚点 × 长度处。"""
        sim, pts = self._stretch(20)
        p = sim.particles[0]
        self.assertAlmostEqual((pts[0] - p.spawn_pos).length(), 0.0, places=4)
        self.assertAlmostEqual((pts[-1] - p.pos).length(), 35.0, places=4)

    def test_stretch_max_length_drags_the_base(self):
        sim, pts = self._stretch(40, stretchMaxLength=40.0)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 40.0, places=3)
        self.assertGreater((pts[0] - sim.particles[0].spawn_pos).length(), 1.0)

    def test_stretch_reset_restarts_from_the_tip(self):
        """超出重置距离后 base 跳到 tip，条带从零重新拉伸，长度回落到阈值以下。"""
        _sim, pts = self._stretch(40, stretchResetDistance=40.0)
        self.assertLess((pts[-1] - pts[0]).length(), 40.0)

    def test_stretch_smaller_threshold_wins(self):
        _sim, pts = self._stretch(40, stretchMaxLength=45.0, stretchResetDistance=40.0)
        self.assertLess((pts[-1] - pts[0]).length(), 40.0)          # 重置先到
        _sim, pts = self._stretch(40, stretchMaxLength=38.0, stretchResetDistance=40.0)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 38.0, places=3)   # 上限先到

    def test_spawn_anchor_offset_places_the_spawn_point(self):
        """1 = 条带自生成点伸出，0.5 = 生成点居中，0 = 整条落在另一侧。"""
        def ends(anchor):
            sim = self._sim(ribbon=ribbon_fields(ribbonMode=1, length=50.0,
                                                 spawnAnchorOffset=anchor))
            pts = [q for q, _w, _x in sim.build_render()[0].points]
            return pts[0] - sim.particles[0].pos, pts[-1] - sim.particles[0].pos

        base, tip = ends(1.0)
        self.assertAlmostEqual(base.length(), 0.0, places=4)
        self.assertAlmostEqual(tip.length(), 50.0, places=4)
        base, tip = ends(0.5)
        self.assertAlmostEqual(base.length(), 25.0, places=4)
        self.assertAlmostEqual(tip.length(), 25.0, places=4)
        base, tip = ends(0.0)
        self.assertAlmostEqual(base.length(), 50.0, places=4)
        self.assertAlmostEqual(tip.length(), 0.0, places=4)

    def test_flap_displaces_the_strip(self):
        flat = self._sim(ribbon=ribbon_fields(ribbonMode=2, enableFlap=0))
        wavy = self._sim(ribbon=ribbon_fields(ribbonMode=2, enableFlap=1,
                                              flap1Frequency=2.0, flap1Amount=10.0))
        pf = [q for q, _w, _a in flat.build_render()[0].points]
        pw = [q for q, _w, _a in wavy.build_render()[0].points]
        moved = sum((a - b).length() for a, b in zip(pf, pw))
        self.assertGreater(moved, 1.0)

    def test_flap_is_deterministic(self):
        r = ribbon_fields(ribbonMode=2, enableFlap=1, flap1Frequency=2.0,
                          flap1Amount=10.0)
        a = [q.as_tuple() for q, _w, _x in self._sim(ribbon=r).build_render()[0].points]
        b = [q.as_tuple() for q, _w, _x in self._sim(ribbon=r).build_render()[0].points]
        self.assertEqual(a, b)

    def test_flap_only_applies_to_chain_mode(self):
        """旗帜摆动是柔体链专属：定长面片开了 enableFlap 也保持平直。"""
        flat = self._sim(ribbon=ribbon_fields(ribbonMode=1, enableFlap=0))
        wavy = self._sim(ribbon=ribbon_fields(ribbonMode=1, enableFlap=1,
                                              flap1Frequency=2.0, flap1Amount=10.0))
        pf = [q.as_tuple() for q, _w, _a in flat.build_render()[0].points]
        pw = [q.as_tuple() for q, _w, _a in wavy.build_render()[0].points]
        self.assertEqual(pf, pw)

    # ── 柔体链重力 ─────────────────────────────────────────────────────────
    def _chain_tip(self, **kw):
        base = dict(ribbonMode=2, length=60.0, baseAxis=4, restoreStrength=1.0,
                    springiness=0.3, inertia=0.5)
        base.update(kw)
        sim = self._sim(ribbon=ribbon_fields(**base), frames=120)
        return [q for q, _w, _a in sim.build_render()[0].points][-1]

    def test_chain_gravity_pulls_tip_down(self):
        still = self._chain_tip()
        heavy = self._chain_tip(enableGravity=1, gravityY=-1.0)
        self.assertLess(heavy.y, still.y - 1.0)

    def test_chain_gravity_needs_enable_switch(self):
        """只填了分量、没开 enableGravity 时不生效（实机：只开本地坐标系也不生效）。"""
        still = self._chain_tip()
        off = self._chain_tip(enableGravity=0, gravityLocalSpace=1, gravityY=-1.0)
        self.assertAlmostEqual((off - still).length(), 0.0, places=6)

    def test_chain_gravity_local_space_follows_emitter_rotation(self):
        """gravityLocalSpace 开启时重力方向随发射器的动态旋转转动。"""
        from efx_format.sim.behaviors.ribbon import Ribbon as _R
        for local in (0, 1):
            sim = make_sim(extra=[(RIBBON, ribbon_fields(
                ribbonMode=2, enableGravity=1, gravityLocalSpace=local, gravityY=-1.0,
                springiness=0.0, inertia=0.0))],
                spawn=spawn_fields(intervalFrame=1000),
                life=life_fields(indefiniteLifespan=1))
            sim.step()
            em = sim.em
            em.rot_dynamic = Vec3(0.0, 0.0, 90.0)     # 绕 Z 转 90°，-Y 转到水平
            sim.step()
            dv = sim.particles[0].user[_R]["vels"][-1]   # 惯性与弹簧为 0，速度只剩重力
            if local:
                self.assertLess(abs(dv.y), 1e-6)
                self.assertAlmostEqual(abs(dv.x), 1.0, places=6)
            else:
                self.assertAlmostEqual(dv.y, -1.0, places=6)

    # ── 条带时间缩放 ───────────────────────────────────────────────────────
    def _trail_pts(self, frames=60, **kw):
        base = dict(ribbonMode=0, subdivisionCount=11)
        base.update(kw)
        sim = self._sim(ribbon=ribbon_fields(**base),
                        velocity=velocity_fields(speed=1.0), frames=frames,
                        config=SimConfig(ribbon_trail_time_frames=0.5))
        return [q for q, _w, _a in sim.build_render()[0].points]

    def test_trail_time_scale_multiplies_with_subdivision(self):
        """开启后长度 = (细分数 − 1) × 每段帧数 × trailTimeScale。"""
        pts = self._trail_pts(useTrailTimeScale=1, trailTimeScale=1.0)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 5.0, delta=0.05)
        pts = self._trail_pts(useTrailTimeScale=1, trailTimeScale=2.0)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 10.0, delta=0.05)
        pts = self._trail_pts(useTrailTimeScale=1, trailTimeScale=2.0,
                              subdivisionCount=21)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 20.0, delta=0.05)
        self.assertEqual(len(pts), 21)

    def test_trail_time_scale_interpolates_fractional_frames(self):
        pts = self._trail_pts(useTrailTimeScale=1, trailTimeScale=0.3)   # 1.5 帧
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 1.5, delta=0.05)

    def test_trail_time_scale_off_keeps_frame_model(self):
        pts = self._trail_pts(useTrailTimeScale=0, trailTimeScale=3.0)
        self.assertAlmostEqual((pts[-1] - pts[0]).length(), 10.0, delta=0.05)

    def test_trail_time_scale_zero_connects_spawn_to_current(self):
        """0 及负值：条带从当前位置直线连到生成点。"""
        for v in (0.0, -2.0):
            pts = self._trail_pts(frames=30, useTrailTimeScale=1, trailTimeScale=v)
            head, tip = pts[0], pts[-1]
            self.assertAlmostEqual(tip.length(), 0.0, delta=1e-6)      # 生成点在原点
            self.assertGreater(head.length(), 20.0)
            mid = pts[len(pts) // 2]
            cross = (mid - tip).cross(head - tip).length()
            self.assertAlmostEqual(cross, 0.0, delta=1e-6)             # 共线

    # ── 贴图缩放参数 ───────────────────────────────────────────────────────
    def _uv(self, **kw):
        base = dict(ribbonMode=1, length=60.0, width=20.0)
        base.update(kw)
        return self._sim(ribbon=ribbon_fields(**base)).build_render()[0].extra.get("uv_scale")

    def test_uv_scale_absent_by_default(self):
        self.assertIsNone(self._uv())
        self.assertIsNone(self._uv(uvScaleMode=0, uvScaleLength=3.0))   # 不缩放时无效

    def test_uv_scale_fixed_count(self):
        self.assertEqual(self._uv(uvScaleMode=1, uvScaleLength=2.0), (2.0, 1.0))

    def test_uv_scale_by_aspect_ratio(self):
        rep, _w = self._uv(uvScaleMode=2, uvScaleLength=1.5)
        self.assertAlmostEqual(rep, 1.5 * 60.0 / 20.0, places=4)
        # 长宽相等时与固定次数相同：重复 1 次即不缩放，不附加参数
        self.assertIsNone(self._uv(uvScaleMode=2, uvScaleLength=1.0, length=20.0))

    def test_uv_scale_width_only(self):
        self.assertEqual(self._uv(uvScaleWidth=2.0), (1.0, 2.0))


class TestRibbonUV(unittest.TestCase):
    """贴图缩放的几何切分（ribbon_uv）。"""

    def test_width_columns_identity(self):
        from efx_format.sim.ribbon_uv import width_columns
        self.assertEqual(width_columns(1.0), [(0.0, 1.0, 0.0, 1.0)])

    def test_width_columns_scale_two_clamps_edges(self):
        """2：整张贴图压到中间一半，两侧恒取边缘像素。"""
        from efx_format.sim.ribbon_uv import width_columns
        cols = width_columns(2.0)
        self.assertEqual(len(cols), 3)
        (_a0, a1, au0, au1), (b0, b1, bu0, bu1), (_c0, _c1, cu0, cu1) = cols
        self.assertAlmostEqual(a1, 0.25)
        self.assertEqual((au0, au1), (0.0, 0.0))
        self.assertAlmostEqual(b0, 0.25)
        self.assertAlmostEqual(b1, 0.75)
        self.assertEqual((bu0, bu1), (0.0, 1.0))
        self.assertEqual((cu0, cu1), (1.0, 1.0))

    def test_width_columns_half_shows_middle(self):
        from efx_format.sim.ribbon_uv import width_columns
        [(s0, s1, u0, u1)] = width_columns(0.5)
        self.assertEqual((s0, s1), (0.0, 1.0))
        self.assertAlmostEqual(u0, 0.25)
        self.assertAlmostEqual(u1, 0.75)

    def test_length_pieces_split_at_repeat_boundaries(self):
        from efx_format.sim.ribbon_uv import length_pieces
        pieces = length_pieces(2, 2.0)
        self.assertEqual(pieces, [(0, 0.0, 0.5, 0.0, 1.0), (0, 0.5, 1.0, 0.0, 1.0)])

    def test_length_pieces_identity_matches_row_param(self):
        from efx_format.sim.ribbon_uv import length_pieces
        pieces = length_pieces(5, 1.0)
        self.assertEqual(len(pieces), 4)
        for i, (seg, fa, fb, va, vb) in enumerate(pieces):
            self.assertEqual((seg, fa, fb), (i, 0.0, 1.0))
            self.assertAlmostEqual(va, i / 4.0)
            self.assertAlmostEqual(vb, (i + 1) / 4.0)

    def test_length_pieces_half(self):
        from efx_format.sim.ribbon_uv import length_pieces
        self.assertAlmostEqual(length_pieces(3, 0.5)[-1][4], 0.5)       # 只显示一半

    def test_repeat_count(self):
        from efx_format.sim.ribbon_uv import repeat_count
        self.assertEqual(repeat_count(0, 3.0, 100.0, 10.0), 1.0)
        self.assertEqual(repeat_count(1, 3.0, 100.0, 10.0), 3.0)
        self.assertAlmostEqual(repeat_count(2, 1.5, 40.0, 20.0), 3.0)   # 两倍长、1.5 → 三张


# ─────────────────────────────────────────────────────────────────────────────
# RIBBONBLADE
# ─────────────────────────────────────────────────────────────────────────────

class TestRibbonBlade(unittest.TestCase):

    def _sim(self, blade=None, frames=20, **kw):
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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

    def test_rgbfire_keeps_the_blade_color(self):
        """挂 RGBFIRE 时两层颜色交给 shader，刀光自身颜色记在 base_tint 里。"""
        sim = make_sim(extra=[(RIBBONBLADE, blade_fields()), (RGBFIRE, rgbfire_fields())],
                       spawn=spawn_fields(intervalFrame=1000),
                       life=life_fields(indefiniteLifespan=1),
                       transform=transform3d_fields(
                           enableVelocityBitflag=1,
                           translation_velocity=[20.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        for _ in range(20):
            sim.step()
        it = sim.build_render()[0]
        self.assertIn("layers", it.extra)
        self.assertIn("base_tint", it.extra)

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
                spawn=spawn_fields(intervalFrame=1000),
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
        kw.setdefault("spawn", spawn_fields(intervalFrame=1000))
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

    def test_rotation_jitter_is_the_second_of_each_pair(self):
        """rotation 是完整的三轴（固定/随机成对）——没有额外的标量旋转。

        曾经这块字节边界偏了 8 个字节，真正的 Z 被单独当成 `rotation2`；
        现在 6 个 float 就是 (X, XJitter, Y, YJitter, Z, ZJitter)。
        """
        it, _ = self._item(mesh=mesh_fields(
            rotation=[10.0, 0.0, 20.0, 0.0, 45.0, 0.0]))
        self.assertAlmostEqual(it.extra["rot"].z, 45.0, places=6)
        self.assertNotIn("rotation2", mesh_fields())

    def test_emitter_rotation_reaches_the_mesh(self):
        """发射器自己的旋转要转动网格——`em.rot_dynamic` 是宿主没替我们套的那部分。

        wp11_017 的 aura32a/b/c 只差发射器静态 rotate Z 的 0 / ±120°；不算这一项
        三份会完全重叠画在同一处。
        """
        it, sim = self._item(mesh=mesh_fields(rotation=[0.0] * 6))
        base = it.extra["rot"].z
        sim.em.rot_dynamic.z += 120.0
        it2 = sim.build_render()[0]
        self.assertAlmostEqual(it2.extra["rot"].z, base + 120.0, places=5)

    def test_viscon_index_is_passed_through(self):
        it, _ = self._item(mesh=mesh_fields(visconIndex=3))
        self.assertEqual(it.extra["viscon"], 3)

    def test_draw_model_bit_off_hides_the_mesh(self):
        """shadowCastBitflag 位 0 关闭（只画阴影 / 全关）时不绘制网格。"""
        for flag in (0, 2, 14):
            sim = make_sim(spawn=spawn_fields(intervalFrame=1000),
                           life=life_fields(indefiniteLifespan=1),
                           extra=[(MESH, mesh_fields(shadowCastBitflag=flag))])
            sim.step()
            self.assertEqual(sim.build_render(), [], flag)

    def test_draw_model_bit_on_draws_the_mesh(self):
        for flag in (1, 3, 9):
            it, _ = self._item(mesh=mesh_fields(shadowCastBitflag=flag))
            self.assertEqual(it.kind, "MESH", flag)

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
                # 10 帧：ribbon_particle 只发一批（loopNum=1/repeat=1）、
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
        """STRAINRIBBON / LIGHTNING 刻意不做 → 退化点 + 如实列出。"""
        for stem, missing in (("draw_chain", "STRAINRIBBON"),
                              ("lightning", "LIGHTNING")):
            with self.subTest(archetype=stem):
                blocks, timl = _load_archetype(stem + ".json")
                sim = from_attr_blocks(blocks, timl, SimConfig(seed=2))
                sim.run(20)
                self.assertIn(missing, [n for _h, n in sim.unsupported])
                for it in sim.build_render():
                    self.assertEqual(it.kind, "POINT")

    def test_billboard2d_falls_back_honestly(self):
        """BILLBOARD2D 同上。唯一带它的 archetype 预设已移除，改用合成 entry
        保住这条覆盖——未模拟的渲染主体照样得退化成点、并出现在 unsupported 里。"""
        sim = make_sim(spawn=spawn_fields(intervalFrame=0, spawnNum=1),
                       life=life_fields(),
                       extra=[(BILLBOARD2D, {})],
                       config=SimConfig(seed=2))
        sim.run(20)
        self.assertIn("BILLBOARD2D", [n for _h, n in sim.unsupported])
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
        spawn = spawn_fields(spawnNum=24, intervalFrame=1000)

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

    def test_no_render_body_renders_nothing(self):
        """UVSEQUENCE 没有可修饰的宿主渲染体（这里没挂 billboard）→ 这个 entry
        压根没有渲染主体类属性，按新规则（同 DUMMY/纯 PtBehavior）不产出任何
        渲染项，而不是凭空退化成点。"""
        sim = uvseq_sim(billboard=None, resources=self._res(4), frames=2)
        self.assertEqual(sim.build_render(), [])



# ─────────────────────────────────────────────────────────────────────────────
# PTBEHAVIOR：贴花
# ─────────────────────────────────────────────────────────────────────────────

def ptb_fields(b_type, **params):
    """造一个 PTBEHAVIOR 解码结果；参数按名字给，值类型按名字后缀推断的 t 由调用方给。

    params 的值为 (t, payload_dict)。
    """
    from efx_format.ptbehavior.names import PTBEHAVIOR_NAMES
    by_name = {v: k for k, v in PTBEHAVIOR_NAMES.items()}
    out = []
    for name, (t, payload) in params.items():
        pr = {"unkn": by_name[name], "const0": 0, "t": t}
        pr.update(payload)
        out.append(pr)
    bt = b_type.encode("latin-1") + b"\x00"
    return {"typeFlag": 0, "behav_type_len": len(bt), "para_count": len(out),
            "b_type": bt, "params": out}


def decal_fields(**params):
    base = {
        "mRange": (0x14, {"unkn1": [40.0, 20.0, 50.0]}),
        "mAxis": (0x06, {"decal_epv_color_slot": 4}),
        "mUpVector": (0x06, {"decal_epv_color_slot": 2}),
        "mBlendFactor": (0x0F, {"color": [255, 255, 255, 255]}),
    }
    base.update(params)
    return ptb_fields("nEffect::MhEffectDecalBehavior", **base)


def decal_sim(frames=1, resources=None, config=None, **params):
    blocks = [(SPAWN, spawn_fields(intervalFrame=1000)),
              (LIFE, life_fields(indefiniteLifespan=1)),
              (PTBEHAVIOR, decal_fields(**params))]
    sim = Simulator(blocks, b"", config or SimConfig(strict=True), resources)
    for _ in range(frames):
        sim.step()
    return sim


class TestDecal(unittest.TestCase):

    def _res(self, n):
        return SimResources(uvs_bytes([(i / float(n), 0.0, (i + 1) / float(n), 1.0)
                                       for i in range(n)]))

    def test_lies_flat_facing_up(self):
        item = decal_sim().build_render()[0]
        self.assertEqual(item.kind, "PLANE")
        self.assertAlmostEqual(item.size.x, 40.0)
        self.assertAlmostEqual(item.size.y, 20.0)
        # 向下投射 → 面片两轴都在水平面内，并标记贴地
        self.assertAlmostEqual(item.axis_u.y, 0.0)
        self.assertAlmostEqual(item.axis_v.y, 0.0)
        self.assertTrue(item.extra["decal_ground"])

    def _rotated(self, transform, extra=(), frames=1):
        blocks = [(TRANSFORM3D, transform), (SPAWN, spawn_fields(intervalFrame=1000)),
                  (LIFE, life_fields(indefiniteLifespan=1))] + list(extra)
        blocks.append((PTBEHAVIOR, decal_fields()))
        sim = Simulator(blocks, b"", SimConfig(strict=True, t3d_apply_base=True))
        for _ in range(frames):
            sim.step()
        return sim.build_render()[0]

    def test_emitter_rotation_turns_the_decal(self):
        flat = decal_sim().build_render()[0]
        item = self._rotated(transform3d_fields(rotate=[0.0, 0.0, 90.0, 0.0, 0.0, 0.0]))
        # 绕 Y 转 90°：仍贴地，但横轴换了方向
        self.assertAlmostEqual(item.axis_u.y, 0.0)
        self.assertAlmostEqual(abs(item.axis_u.dot(flat.axis_u)), 0.0, places=5)
        self.assertTrue(item.extra["decal_ground"])

    def test_tilted_emitter_is_not_grounded(self):
        item = self._rotated(transform3d_fields(rotate=[90.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
        self.assertFalse(item.extra["decal_ground"])

    def test_follows_spinning_emitter_with_parentoptions(self):
        po = (PARENTOPTIONS, parentoptions_fields(particleUseLocal=1,
                                                  relationRot=[1, 1, 1]))
        fixed = self._rotated(spinning_emitter(3.0), frames=10)
        follow = self._rotated(spinning_emitter(3.0), extra=[po], frames=10)
        # 不跟随时停在出生朝向，跟随时多转了 9 帧 × 3°
        self.assertAlmostEqual(fixed.axis_u.dot(follow.axis_u),
                               math.cos(math.radians(27.0)), places=4)

    def test_uvsequence_mapping_uses_sequence_frames(self):
        sim = decal_sim(resources=self._res(4), frames=3,
                        mMappingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mShadingMode=(0x06, {"decal_epv_color_slot": 0}),
                        mPlayType=(0x06, {"decal_epv_color_slot": 1}),
                        mPlaySpeed=(0x37, {"unkn1": [1.0, 0.0]}))
        item = sim.build_render()[0]
        self.assertEqual(item.extra["uvs_n"], 4)
        self.assertEqual(item.extra["uvs_source"], "uvs")
        self.assertEqual(item.extra["uvs_frame"], 3)
        self.assertNotIn("layers", item.extra)

    def test_start_only_by_default(self):
        sim = decal_sim(resources=self._res(4), frames=5,
                        mMappingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mPatternNo=(0x36, {"unkn1": [2, 0]}))
        self.assertEqual(sim.build_render()[0].extra["uvs_frame"], 2)

    def test_fire_shading_gives_two_layers(self):
        sim = decal_sim(resources=self._res(4),
                        mMappingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mShadingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mFireColor=(0x14, {"unkn1": [1.0, 0.5, 0.0]}),
                        mFireColorRate=(0x0C, {"unkn0": 2.0}),
                        mSmokeLerpAlphaToB=(0x0C, {"unkn0": 0.25}))
        item = sim.build_render()[0]
        fire, _smoke = item.extra["layers"]
        self.assertEqual([round(c, 6) for c in fire], [2.0, 1.0, 0.0])
        self.assertAlmostEqual(item.extra["rgbfire_lerp"], 0.25)

    def test_blend_mode_one_multiplies(self):
        on = decal_sim(mBlendMode=(0x06, {"decal_epv_color_slot": 1})).build_render()[0]
        off = decal_sim(mBlendMode=(0x06, {"decal_epv_color_slot": 0})).build_render()[0]
        self.assertEqual(on.blend, "MULTIPLY")
        self.assertEqual(off.blend, "ALPHA")

    def test_uvsequence_mapping_adds_emissive(self):
        sim = decal_sim(resources=self._res(4),
                        mMappingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mShadingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mEmissiveMapFactor=(0x0F, {"color": [0, 0, 255, 255]}),
                        mEmissiveMapFactorIntensity=(0x0C, {"unkn0": 100.0}))
        item = sim.build_render()[0]
        r, _g, b, _a = item.extra["decal_emissive"]
        self.assertAlmostEqual(r, 0.0)
        self.assertAlmostEqual(b, 100.0)
        # 火焰模式但没写火焰/烟雾颜色：不画两层
        self.assertNotIn("layers", item.extra)

    def test_fire_layer_without_color_is_black(self):
        sim = decal_sim(resources=self._res(4),
                        mMappingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mShadingMode=(0x06, {"decal_epv_color_slot": 1}),
                        mFireColor=(0x14, {"unkn1": [1.0, 0.5, 0.0]}))
        _fire, smoke = sim.build_render()[0].extra["layers"]
        self.assertEqual(list(smoke), [0.0, 0.0, 0.0])

    def test_texture_mapping_adds_emissive(self):
        sim = decal_sim(mMappingMode=(0x06, {"decal_epv_color_slot": 0}),
                        mpAlbedoMap=(0x80, {"file_type": 0, "path_len": 2, "path": b"a\x00"}),
                        mpEmissiveMap=(0x80, {"file_type": 0, "path_len": 2, "path": b"e\x00"}),
                        mEmissiveMapFactor=(0x0F, {"color": [255, 0, 0, 255]}),
                        mEmissiveMapFactorIntensity=(0x0C, {"unkn0": 20.0}))
        item = sim.build_render()[0]
        r, g, b, _a = item.extra["decal_emissive"]
        self.assertAlmostEqual(r, 20.0)
        self.assertAlmostEqual(g, 0.0)
        self.assertIsNone(item.uv_corners)

    def test_other_btype_is_listed_unsupported(self):
        blocks = [(SPAWN, spawn_fields(intervalFrame=1000)),
                  (LIFE, life_fields(indefiniteLifespan=1)),
                  (PTBEHAVIOR, ptb_fields("MhPointLightBehavior"))]
        sim = Simulator(blocks, b"", SimConfig())
        sim.step()
        self.assertIn(PTBEHAVIOR, [h for h, _ in sim.unsupported])
        self.assertEqual(sim.build_render(), [])


class TestUVControl(unittest.TestCase):
    """UVCONTROL：static+random 取值、逐帧 Coef、缩放加速度与 flowmap 组。"""

    @staticmethod
    def _sim(uvc, n=1):
        from efx_format.hashes import UVCONTROL
        blocks = [
            (SPAWN, {"maxParticles": n, "spawnNum": n, "intervalFrame": 0,
                     "loopNum": 1, "revivalLoop": 1}),
            (LIFE, {"keepFrame": 600, "indefiniteLifespan": 1}),
            (BILLBOARD3D, {"color": [255, 255, 255, 255], "brightness": 1,
                           "blendMode": 0, "width": 100, "height": 100, "scale": 1}),
            (UVCONTROL, dict(uvc)),
        ]
        return Simulator(blocks, b"", SimConfig())

    def test_offset_rolls_between_static_and_static_plus_random(self):
        sim = self._sim({"uv1_offset": [0.0, 0.5, 0.1, 0.2]}, n=40)
        sim.run(1)
        xs = [it.extra["uv_xform"] for it in sim.build_render()]
        self.assertEqual(len(xs), 40)
        for su, sv, ou, ov in xs:
            self.assertTrue(0.0 <= ou <= 0.5)
            self.assertTrue(0.1 <= ov <= 0.3 + 1e-9)
        self.assertGreater(len(set(round(x[2], 6) for x in xs)), 1)

    def test_offset_coef_is_per_frame(self):
        # 每秒 60 = 每帧 1，逐帧乘 0.5：位移收敛到 1 / (1 − 0.5) = 2
        sim = self._sim({"uv1_offsetAdd": [60.0, 0.0, 0.0, 0.0],
                         "uv1_offsetCoef": [0.5, 0.0, 1.0, 0.0]})
        sim.run(40)
        su, sv, ou, ov = sim.build_render()[0].extra["uv_xform"]
        self.assertAlmostEqual(ou, 2.0, places=4)
        self.assertEqual(ov, 0.0)

    def test_scale_coef_decays_scale_speed(self):
        sim = self._sim({"uv1_scale": [1.0, 0.0, 1.0, 0.0],
                         "uv1_scaleAdd": [60.0, 0.0, 0.0, 0.0],
                         "uv1_scaleCoef": [0.5, 0.0, 1.0, 0.0]})
        sim.run(40)
        su, sv, ou, ov = sim.build_render()[0].extra["uv_xform"]
        self.assertAlmostEqual(su, 3.0, places=4)
        self.assertAlmostEqual(sv, 1.0)

    def test_flowmap_group_follows_enable_flag(self):
        on = self._sim({"enableFlowmap": 1, "flowSpeed": 1.0, "flowStrength": 0.2,
                        "flowSpeedCoef": 1.0, "flowStrengthCoef": 1.0})
        on.run(10)
        amt = on.build_render()[0].extra.get("flowmap")
        self.assertAlmostEqual(amt, 0.2, places=6)
        off = self._sim({"enableFlowmap": 0, "flowSpeed": 1.0, "flowStrength": 0.2})
        off.run(15)
        self.assertNotIn("flowmap", off.build_render()[0].extra)


if __name__ == "__main__":
    unittest.main(verbosity=2)
