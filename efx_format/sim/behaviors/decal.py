# -*- coding: utf-8 -*-
"""PTBEHAVIOR —— 按 b_type 分派的行为；目前只模拟贴花 `MhEffectDecalBehavior`。

PTBEHAVIOR 不是扁平字段表，而是「b_type + 稀疏参数列表」。`_PtbResolver` 把参数列表按参数名
展开成扁平 dict，之后照常用 `em.f(PTBEHAVIOR, p)` 取值：

    range(0x36) / rangef(0x37)   值 + 抖动 → `mFoo` 与 `mFooJitter`
    vector3/4(0x14/0x15)         → `mFooX` / `mFooY` / `mFooZ`(/`mFooW`)
    color(0x0F)                  → `<4B>` 列表，与渲染体的 color 同一格式

TIML 轨道按 `nEffect::nTimelineParam::<短类名>` 与去掉 m 前缀的参数名查找，
`mEmissiveMapFactor` 的通道名是 EmissiveMapFactorColor，单独登记在 `_DT_ALIAS`。

贴花是渲染主体：一张按 `mAxis` 方向投射的面片，面片法线与投射方向相反，`mUpVector` 为贴图
上方。`mAxis` 与 `mUpVector` 使用 AxisDirection6 枚举，官方样本以 4（−Y，向下投射）为主，
glue 据 `extra["decal_ground"]` 把向下投射的贴花贴到地面。`mRange` 的 X/Y 为贴花宽高
（游戏单位），Z 为投射深度，预览不使用深度。`mRangeScaleMode` 的 bit0/bit1 决定宽/高是否随
SCALEANIM 缩放，缺省视为全部缩放。

贴图有两种来源，由 `mMappingMode` 选择：

    1  序列帧：mpUVSequence 的 .uvs，mSequenceNo 选 group，其余播放字段与 UVSEQUENCE 同义
    0  贴图组：mpAlbedoMap（BaseMap）× mBlendFactor，叠加 mpEmissiveMap ×
       mEmissiveMapFactor × mEmissiveMapFactorIntensity 的自发光

序列帧模式下 `mShadingMode` 选择着色：1 为火焰/烟雾两层（字段与 RGBFIRE 同构），2 为水膜/
高光两层（字段与 RGBWATER 同构），0 直接用贴图乘 mBlendFactor。两层模式与 RGBFIRE /
RGBWATER 共用 glue 的通道遮罩 shader。`mpFlowMap` 在 `mFlowEnable=1` 时接入共用 flowmap。

`mPlayType` 取 0=停在起始帧、1=循环、2=播放一次后停在末帧；`mPlayOrder` 取 0=正放、
1=倒放、2=随机。`mNormalMap`、`mpAlphaTestMap`、`mAlphaCorrectionMin/Max`、金属度/粗糙度、
`mLimitAngle`、`mEdgeFade` 不参与计算。

维护约束：
- 非贴花的 b_type 必须记入 `em.unsupported`：注册 PTBEHAVIOR 后，registry 不再替它们记账。
- 本 behavior 位于 RENDER_BODY 阶段，step 中只写 `p.user`，两层颜色也存在 `p.user` 而非
  `p.color`，strict 模式据此检查。
"""

import math

from ...hashes import PTBEHAVIOR
from ..registry import Behavior, register
from ..resolve import FieldResolver
from ..rng import jitter, jitter_int
from ..stages import RENDER_BODY
from ..state import BASE_AXES, RenderItem, Vec3
from . import _flowmap
from ._common import color_param_weight, quad_size, rgba
from .uvsequence import (DIR_RANDOM, DIR_REVERSE, PB_LOOP, PB_ONCE_HOLD, PB_START_ONLY,
                         UVSequence, _roll_flip)

DECAL_CLASS = "MhEffectDecalBehavior"

#: 参数值类型 t（custom_codecs.unpack_ptbehavior）
_T_BOOL = 0x03
_T_SHORT = 0x05
_T_INT = 0x06
_T_FLOAT = 0x0C
_T_COLOR = 0x0F
_T_VEC3 = 0x14
_T_VEC4 = 0x15
_T_RANGE = 0x36
_T_RANGEF = 0x37
_T_INT64 = 0x40
_T_PATH = 0x80

_COMPS = ("X", "Y", "Z", "W")

#: 参数名与其 TIML 通道名不一致的项
_DT_ALIAS = {"mEmissiveMapFactor": "mEmissiveMapFactorColor"}

#: mMappingMode
MAP_TEXTURES = 0
MAP_UVSEQUENCE = 1

#: mShadingMode
SHADE_PLAIN = 0
SHADE_FIRE = 1
SHADE_WATER = 2

#: mPlayType → UVSEQUENCE 的 playbackMode
_PLAY_TYPE = {0: PB_START_ONLY, 1: PB_LOOP, 2: PB_ONCE_HOLD}

#: AxisDirection6 中的 −Y：向下投射
AXIS_DOWN = 4


def short_class(b_type):
    """b_type → 去掉命名空间与尾部 NUL 的短类名。"""
    if isinstance(b_type, bytes):
        b_type = b_type.decode("latin-1")
    return str(b_type or "").split("\x00")[0].strip().split("::")[-1]


def _path_str(v):
    if isinstance(v, bytes):
        v = v.split(b"\x00")[0].decode("ascii", "replace")
    return str(v or "").rstrip("\x00").strip()


def flatten(values):
    """PTBEHAVIOR 的解码结果 → 扁平字段 dict，含 `b_type`（短类名）。

    glue 取贴图路径时也用它，保证与模拟读到的是同一份数据。
    """
    from ...ptbehavior.names import PTBEHAVIOR_NAMES

    values = values or {}
    out = {"b_type": short_class(values.get("b_type", b""))}
    for pr in values.get("params") or ():
        try:
            name = PTBEHAVIOR_NAMES.get(int(pr["unkn"]) & 0xFFFFFFFF)
            t = int(pr["t"])
        except Exception:
            continue
        if not name:
            continue
        if t in (_T_RANGE, _T_RANGEF):
            v = pr.get("unkn1") or (0, 0)
            out[name], out[name + "Jitter"] = v[0], v[1]
        elif t == _T_VEC3:
            for c, x in zip(_COMPS, pr.get("unkn1") or ()):
                out[name + c] = x
        elif t == _T_VEC4:
            for i, c in enumerate(_COMPS):
                out[name + c] = pr.get("unkn%d" % i, 0.0)
        elif t == _T_COLOR:
            out[name] = list(pr.get("color") or (255, 255, 255, 255))
        elif t == _T_PATH:
            out[name] = _path_str(pr.get("path"))
        elif t == _T_INT:
            out[name] = pr.get("decal_epv_color_slot", 0)
        elif t == _T_BOOL:
            out[name] = pr.get("NULL", 0)
        elif t in (_T_FLOAT, _T_SHORT, _T_INT64):
            out[name] = pr.get("unkn0", 0)
    return out


class _PtbResolver(FieldResolver):
    """展开后的 PTBEHAVIOR 参数 + 按 b_type 推出的 TIML 通道。"""

    __slots__ = ("b_type",)

    def __init__(self, block_name, raw_fields, tracks, config, extern_overrides=None):
        flat = flatten(raw_fields)
        self.b_type = flat["b_type"]
        FieldResolver.__init__(self, block_name, flat, tracks, config, extern_overrides)
        self.tlp_hash = None
        self.has_tracks = False
        if tracks is None:
            return
        from ...timl.names import ptbehavior_tlp_candidates
        for tlp in ptbehavior_tlp_candidates(self.b_type):
            if tracks.has_param(tlp):
                self.tlp_hash = tlp
                self.has_tracks = True
                break

    def _entries(self, field):
        from ...timl.names import ptbehavior_param_channels
        got = ptbehavior_param_channels(self.b_type, _DT_ALIAS.get(field, field), 1)
        if got is None or got[0] != self.tlp_hash:
            return None
        return got[1]


class _FlowFields(object):
    """把贴花的 flow 参数映射成 `_flowmap.roll` 读取的渲染体字段名。"""

    __slots__ = ("_f",)

    _NAMES = {"flowmapSpeed": "mFlowSpeed", "flowmapSpeedCoef": "mFlowSpeedCoef",
              "flowmapStrength": "mFlowStrength",
              "flowmapStrengthCoef": "mFlowStrengthCoef"}

    def __init__(self, f):
        self._f = f

    def get(self, field, default=0.0):
        name = self._NAMES.get(field)
        return self._f.get(name, default) if name else default

    def i(self, field, default=0):
        if field == "applicationRule":
            return _flowmap.BIT_ENABLE if self._f.i("mFlowEnable") else 0
        return int(round(self.get(field, default)))


def _rgb3(f, prefix, default=1.0):
    return (float(f.get(prefix + "X", default)), float(f.get(prefix + "Y", default)),
            float(f.get(prefix + "Z", default)))


def _roll_life(f, rng, mode, use, appear, keep, vanish):
    """两层着色的生命期时序，与 `_common.roll_color_param` 同义。"""
    if not f.i(use):
        return None
    return {"appear": max(0, jitter_int(f.get(appear), f.get(appear + "Jitter"), rng, mode)),
            "keep": max(0, jitter_int(f.get(keep), f.get(keep + "Jitter"), rng, mode)),
            "vanish": max(0, jitter_int(f.get(vanish), f.get(vanish + "Jitter"), rng, mode))}


def _axis(idx, fallback):
    return BASE_AXES[idx] if 0 <= idx < len(BASE_AXES) else BASE_AXES[fallback]


@register(PTBEHAVIOR)
class PtBehavior(Behavior):
    """RENDER_BODY 阶段产出贴花面片；非贴花的 b_type 记为未模拟。"""

    STAGE = RENDER_BODY
    ORDER = 100

    _decal = False
    _has_tracks = False
    _mapping = MAP_TEXTURES
    _shading = SHADE_FIRE
    _table = None
    _group = 0
    _ground = True
    _scale_mask = 0x07
    _emissive = False
    _normal = None
    _u = None
    _v = None

    @classmethod
    def make_resolver(cls, block_name, raw_fields, tracks, config):
        return _PtbResolver(block_name, raw_fields, tracks, config)

    # ── 发射器级 ─────────────────────────────────────────────────────────────
    def on_emitter_init(self, em, rng):
        f = em.f(PTBEHAVIOR)
        if f is None:
            return
        b_type = f.raw("b_type", "")
        if b_type != DECAL_CLASS:
            em.unsupported.append((self.type_hash, "PTBEHAVIOR:%s" % (b_type or "?")))
            em.note("未模拟属性：PTBEHAVIOR（%s）" % (b_type or "?"))
            return
        self._decal = True
        self._has_tracks = f.has_tracks
        self._mapping = f.i("mMappingMode", MAP_TEXTURES)
        self._shading = f.i("mShadingMode", SHADE_FIRE)
        self._scale_mask = f.i("mRangeScaleMode", 0x07)
        self._emissive = (self._mapping == MAP_TEXTURES
                          and bool(f.raw("mpEmissiveMap", "")))

        axis = f.i("mAxis", AXIS_DOWN)
        self._ground = axis == AXIS_DOWN
        n = _axis(axis, AXIS_DOWN) * -1.0
        up = _axis(f.i("mUpVector", 2), 2)
        v = up - n * up.dot(n)
        if v.length() < 1e-6:                     # 上方向与投射轴平行时另取一轴
            v = Vec3(0.0, 0.0, 1.0) if abs(n.z) < 0.99 else Vec3(1.0, 0.0, 0.0)
            v = v - n * v.dot(n)
        v = v.normalized(fallback=Vec3(0.0, 0.0, 1.0))
        self._normal, self._v = n, v
        self._u = v.cross(n).normalized(fallback=Vec3(1.0, 0.0, 0.0))

        if self._mapping == MAP_UVSEQUENCE:
            self._group = f.i("mSequenceNo")
            self._table, fell_back = em.resources.uvs_table(self._group, em.config)
            if fell_back:
                grid = self._table.grid or (0, 0)
                em.note("贴花没有载入 .uvs（mSequenceNo=%d）：序列帧按 %d×%d 网格假设"
                        % (self._group, grid[0], grid[1]))

    # ── 出生 ─────────────────────────────────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        if not self._decal:
            return
        f = em.f(PTBEHAVIOR, p)
        mode = em.config.jitter_mode
        st = {"flip_u": _roll_flip(f.i("mHorizontalFlip"), rng),
              "flip_v": _roll_flip(f.i("mVerticalFlip"), rng),
              "blend": "ADDITIVE" if f.i("mBlendMode") == 1 else "ALPHA"}

        if self._table is not None and len(self._table) > 0:
            self._spawn_sequence(st, f, rng, mode, em.config)
        if self._mapping == MAP_UVSEQUENCE and self._shading == SHADE_FIRE:
            st["fire"] = {
                "fp": _roll_life(f, rng, mode, "mUseFireLife", "mFireAppearFrame",
                                 "mFireKeepFrame", "mFireVanishFrame"),
                "sp": _roll_life(f, rng, mode, "mUseSmokeLife", "mSmokeAppearFrame",
                                 "mSmokeKeepFrame", "mSmokeVanishFrame"),
            }
        _flowmap.roll(p, _FlowFields(f), rng, mode)
        p.user[PtBehavior] = st

    def _spawn_sequence(self, st, f, rng, mode, cfg):
        """序列帧的起始格、速度与方向；状态字段与 UVSEQUENCE 相同，供 `_frame_of` 使用。"""
        n = len(self._table)
        order = f.i("mPlayOrder")
        sign = -1.0 if order == DIR_REVERSE else 1.0
        if order == DIR_RANDOM:
            sign = -1.0 if rng.random() < 0.5 else 1.0
        wrap = cfg.uvs_start_wrap == "wrap"
        start = self._table.index(
            jitter_int(f.get("mPatternNo"), f.get("mPatternNoJitter"), rng, mode), wrap)
        if cfg.uvs_once_span == "full_cycle":
            span = n - 1
        else:
            span = start if sign < 0 else n - 1 - start
        st.update({
            "phase": 0.0,
            "speed": jitter(f.get("mPlaySpeed", 1.0), f.get("mPlaySpeedJitter"), rng, mode),
            "coef": jitter(f.get("mPlaySpeedCoef", 1.0), f.get("mPlaySpeedCoefJitter"),
                           rng, mode),
            "start": start, "frame": start, "n": n, "sign": sign,
            "span": max(0, span), "wrap": wrap,
            "playback": _PLAY_TYPE.get(f.i("mPlayType"), PB_START_ONLY),
        })

    # ── 逐帧：推进序列帧（build_render 只读）─────────────────────────────────
    def on_particle_step(self, p, em):
        st = p.user.get(PtBehavior)
        if st is None or "phase" not in st or st["playback"] == PB_START_ONLY:
            return
        step = st["speed"] * st["sign"]
        if em.config.uvs_speed_unit == "per_second":
            step /= float(em.config.fps or 60)
        st["phase"] += step
        st["speed"] *= st["coef"]
        st["frame"] = UVSequence._frame_of(st)

    # ── 渲染 ─────────────────────────────────────────────────────────────────
    def build_render(self, p, em, view, item):
        st = p.user.get(PtBehavior)
        if st is None:
            return item
        f = em.f(PTBEHAVIOR, p)

        item = RenderItem(kind="PLANE", pos=p.pos.copy())
        w = float(f.get("mRangeX", 100.0))
        h = float(f.get("mRangeY", 100.0))
        size = quad_size(p, em.config, 1.0, w, h)
        if not self._scale_mask & 0x01:
            size.x = max(0.0, w)
        if not self._scale_mask & 0x02:
            size.y = max(0.0, h)
        item.size = size

        u, v = self._u, self._v
        if p.rot.z:                                # ROTATEANIM 绕法线的自旋
            a = math.radians(p.rot.z)
            c, s = math.cos(a), math.sin(a)
            u, v = (u * c + v * s), (v * c - u * s)
        item.axis_u, item.axis_v = u, v
        item.rot = 0.0

        r0, g0, b0, a0 = rgba(f.raw("mBlendFactor"))
        alpha = a0 * p.alpha
        item.color = [r0 * p.color[0], g0 * p.color[1], b0 * p.color[2], alpha]
        item.extra["base_tint"] = (r0, g0, b0)
        item.blend = st["blend"]
        item.extra["vel"] = p.vel
        item.extra["age"] = p.age
        item.extra["decal_ground"] = self._ground

        if "phase" in st:
            idx = st["frame"]
            item.uv_rect = self._table.rect(idx, st["wrap"])
            item.uv_corners = self._table.corners(idx, st["flip_u"], st["flip_v"], 0,
                                                  st["wrap"])
            item.extra["uvs_frame"] = idx
            item.extra["uvs_n"] = st["n"]
            item.extra["uvs_source"] = self._table.source
            item.extra["uvs_group"] = self._group
        elif st["flip_u"] or st["flip_v"]:
            u0, u1 = (1.0, 0.0) if st["flip_u"] else (0.0, 1.0)
            v0, v1 = (1.0, 0.0) if st["flip_v"] else (0.0, 1.0)
            item.uv_corners = ((u0, v1), (u1, v1), (u1, v0), (u0, v0))

        if self._mapping == MAP_UVSEQUENCE:
            if self._shading == SHADE_FIRE:
                self._fire_layers(p, f, st["fire"], item)
            elif self._shading == SHADE_WATER:
                self._water_layers(p, f, item)
        elif self._emissive:
            er, eg, eb, _ea = rgba(f.raw("mEmissiveMapFactor"))
            k = float(f.get("mEmissiveMapFactorIntensity", 1.0))
            item.extra["decal_emissive"] = (er * k * p.color[0], eg * k * p.color[1],
                                            eb * k * p.color[2], alpha)
        return _flowmap.apply(p, em, item)

    @staticmethod
    def _fire_layers(p, f, st, item):
        """火焰（G 通道）与烟雾（R 通道）两层，与 RGBFIRE 同一套遮罩。"""
        rate = float(f.get("mFireColorRate", 1.0))
        wf = max(0.0, float(f.get("mFireFactor", 1.0))) * color_param_weight(st["fp"], p.age)
        ws = max(0.0, float(f.get("mSmokeFactor", 1.0))) * color_param_weight(st["sp"], p.age)
        fire = _rgb3(f, "mFireColor")
        smoke = _rgb3(f, "mSmokeColor")
        item.extra["layers"] = ([c * wf * rate * p.color[i] for i, c in enumerate(fire)],
                                [c * ws * rate * p.color[i] for i, c in enumerate(smoke)])
        item.extra["rgbfire_lerp"] = max(0.0, min(1.0, float(f.get("mSmokeLerpAlphaToB", 0.0))))
        item.extra["base_tint"] = (1.0, 1.0, 1.0)
        item.color[3] = min(1.0, item.color[3] * max(0.0, float(f.get("mFireAlphaFactor", 1.0))))

    @staticmethod
    def _water_layers(p, f, item):
        """水膜与高光两层，与 RGBWATER 同一套遮罩，layers 顺序为 (水膜, 高光)。"""
        rate = float(f.get("mWaterColorRate", 1.0))
        spec = _rgb3(f, "mWaterColorSpecular")
        sheet = _rgb3(f, "mWaterColorSheet")
        ws = max(0.0, float(f.get("mWaterIntensitySpecular", 1.0)))
        wh = max(0.0, float(f.get("mWaterIntensitySheet", 1.0)))
        item.extra["layers"] = ([c * wh * rate * p.color[i] for i, c in enumerate(sheet)],
                                [c * ws * rate * p.color[i] for i, c in enumerate(spec)])
        item.extra["rgbwater_lerp"] = max(0.0, min(1.0, float(f.get("mWaterLerpGtoB", 0.0))))
        item.extra["base_tint"] = (1.0, 1.0, 1.0)
        item.color[3] = min(1.0, item.color[3] * max(0.0, float(f.get("mWaterIntensityAlpha", 1.0))))
