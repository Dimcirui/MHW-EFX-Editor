# -*- coding: utf-8 -*-
"""
efx_format/sim/resolve.py  —  字段解析（原始值 → EXTERN 覆盖 → TIML A0 → TIML A1）

**behavior 不许直接读原始字段 dict**，一律走 `em.f(TYPE_HASH, p).字段名`。

这条规矩是为「语义待补」准备的。举个具体的未知点：发射器第 50 帧生的粒子，它的
`speed` 取 A0@50（出生时冻结）还是每帧跟着 A0 走？不知道。现在它是
`SimConfig.a0_sample` 一个开关；如果当初让 behavior 直接读原始字段，等标定出
答案要改几十个文件。

TIML 的两条轴（见 efx_format/timl/__init__.py）
-----------------------------------------------
    animation0 = 发射轴（emitter time）   → 按 a0_sample 取「出生帧」或「当前帧」
    animation1 = 更新/寿命轴（particle age）→ 一律按粒子 age 取

这个双轴结构本来就是粒子系统的 emitter-time / particle-age 两条曲线，不用另造。

尚未覆盖
--------
- Color 通道（data_type == 3）：四个子通道挤在一个关键帧里，等 RENDER 层要用时再补。
- BIG_FLAGS 标志位通道：语义未知，跳过。
- EXTERN 覆盖：接口已经留好（`extern_overrides`），但 EXTERN 的触发条件是运行时
  状态（见 README「Extern：某些条件满足时替换参数」），预览里没有那些条件，
  故当前只支持 glue 层显式传入一张覆盖表。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from .state import Vec3

# 插值类型（efx_format/timl/__init__.py INTERP_NAMES 的下标）
_INTERP_STUCK = 0
_INTERP_CONSTANT = 1
_INTERP_LINEAR = 2
_INTERP_QUAD = 3
_INTERP_CUBIC = 4


# ─────────────────────────────────────────────────────────────────────────────
# Curve —— 一条 TIML 子通道
# ─────────────────────────────────────────────────────────────────────────────

class Curve(object):
    """按 frameTiming 排序的关键帧序列。超出两端一律夹取端点值。"""

    __slots__ = ("keys", "length")

    def __init__(self, keys, length=0.0):
        # keys: [(frame, value, transition), ...]
        self.keys = sorted(keys, key=lambda k: k[0])
        self.length = float(length)

    def __len__(self):
        return len(self.keys)

    def eval(self, t, interp_mode="native"):
        keys = self.keys
        n = len(keys)
        if n == 0:
            return None
        if n == 1 or t <= keys[0][0]:
            return keys[0][1]
        if t >= keys[-1][0]:
            return keys[-1][1]

        # 二分找区间
        lo, hi = 0, n - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if keys[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        f0, v0, tr0 = keys[lo]
        f1, v1, _ = keys[hi]

        if interp_mode == "constant":
            return v0
        if interp_mode == "native":
            # QUAD/CUBIC 的实际曲线形状未验证，先退化成线性——形状会偏，
            # 但不会错到量级上；标定之后在这里补。
            if tr0 in (_INTERP_STUCK, _INTERP_CONSTANT):
                return v0
        span = f1 - f0
        if span <= 1e-9:
            return v1
        return v0 + (v1 - v0) * ((t - f0) / span)


# ─────────────────────────────────────────────────────────────────────────────
# TimlTracks —— 从 timl 字节抽出所有可用曲线
# ─────────────────────────────────────────────────────────────────────────────

class TimlTracks(object):
    """(axis, tlp_hash, dt_hash) → Curve。解析失败一律退化成「没有曲线」。"""

    __slots__ = ("_curves", "_lengths", "ok")

    def __init__(self):
        self._curves = {}
        self._lengths = {}     # axis -> animation_length
        self.ok = False

    @classmethod
    def parse(cls, timl_bytes):
        out = cls()
        if not timl_bytes:
            return out
        try:
            from ..timl import parse_timl, decode_keyframe
        except Exception:
            return out
        try:
            timl = parse_timl(bytes(timl_bytes))
        except Exception:
            timl = None
        if timl is None:
            return out

        for axis, anim in enumerate(timl.animations or []):
            if anim is None:
                continue
            out._lengths[axis] = float(getattr(anim, "animation_length", 0.0) or 0.0)
            for tp in anim.types or []:
                for tf in tp.transforms or []:
                    if tf.data_type == 3:
                        continue          # Color 通道，暂不支持（见模块 docstring）
                    keys = []
                    for kf in tf.keyframes or []:
                        try:
                            d = decode_keyframe(kf.raw, tf.data_type, tf.datatype_hash)
                        except Exception:
                            continue
                        subs = d.get("subs") or []
                        if not subs:
                            continue
                        keys.append((float(d["frame"]),
                                     float(subs[0]["value"]),
                                     int(d["transition"])))
                    if keys:
                        key = (axis, tp.timeline_param_hash, tf.datatype_hash)
                        out._curves[key] = Curve(keys, out._lengths.get(axis, 0.0))
        out.ok = bool(out._curves)
        return out

    def curve(self, axis, tlp_hash, dt_hash):
        return self._curves.get((axis, tlp_hash, dt_hash))

    def channel_count(self):
        return len(self._curves)


# ─────────────────────────────────────────────────────────────────────────────
# FieldResolver —— 一块属性的解析器
# ─────────────────────────────────────────────────────────────────────────────

def _field_dt(block_name, field_name):
    """(块名, 字段名) → [(dt_hash, data_type), ...]（向量按 X/Y/Z 序）。"""
    try:
        from ..timl.names import FIELD_TO_DT
    except Exception:
        return None
    return FIELD_TO_DT.get((block_name.upper(), field_name))


def _block_tlp(block_name):
    try:
        from ..timl.names import BLOCK_TO_TLP
    except Exception:
        return None
    return BLOCK_TO_TLP.get(block_name.upper())


class FieldResolver(object):
    """一个属性块的字段解析：原始 dict + TIML 轨道 + 覆盖表。"""

    __slots__ = ("block_name", "raw", "tlp_hash", "tracks", "config",
                 "extern_overrides", "_dt_cache")

    def __init__(self, block_name, raw_fields, tracks, config, extern_overrides=None):
        self.block_name = block_name or ""
        self.raw = raw_fields or {}
        self.tlp_hash = _block_tlp(self.block_name)
        self.tracks = tracks
        self.config = config
        self.extern_overrides = extern_overrides or {}
        self._dt_cache = {}

    # ── 原始值 ───────────────────────────────────────────────────────────────
    def raw_value(self, field, default=0.0):
        if field in self.extern_overrides:
            return self.extern_overrides[field]
        return self.raw.get(field, default)

    # ── TIML 调制 ────────────────────────────────────────────────────────────
    def _dt_for(self, field, comp):
        key = (field, comp)
        if key in self._dt_cache:
            return self._dt_cache[key]
        entries = _field_dt(self.block_name, field)
        dt = None
        if entries and 0 <= comp < len(entries):
            dt = entries[comp][0]
        self._dt_cache[key] = dt
        return dt

    def _axis_comp(self, field, axis, high):
        """FLOAT6 字段某个轴、某一半对应的 FIELD_TO_DT 下标。

        FLOAT6 的字节布局恒为 `a_x b_x a_y b_y a_z b_z`（codec._XYZ_FMT[0]），
        但挂在上面的 TIML 通道数量分两种：

          6 条 —— 两半各有官方通道名，逐轴交错。例：
                  EMITTERSHAPE3D.rangeXYZ = RangeMinX/RangeMaxX/RangeMinY/…
                  → 下标 = axis*2 + (0|1)
          3 条 —— 只有前一半有通道。例：TRANSFORM3D.translate = pos:X/Y/Z
                  → 下标 = axis，后一半无通道

        （通道名也是判断「这一对到底是什么」的最好证据：rangeXYZ 是 Min/Max，
        translate 是 值/抖动。别按单一惯例硬套。）
        """
        entries = _field_dt(self.block_name, field)
        if not entries:
            return None
        if len(entries) >= 6:
            return axis * 2 + (1 if high else 0)
        if len(entries) >= 3:
            return None if high else axis
        return None

    def _timl_value(self, field, comp, a0_frame, age):
        """返回 TIML 给出的值；没有轨道则 None。

        ⚠ 同一字段两条轴都有轨道时，**A1（寿命轴）整条胜出**，不与 A0 叠加。
        理由是寿命轴更具体；但「两条轴同时存在时游戏怎么合成」没有实测，如果
        以后测出是相乘/相加，改这一处即可（behavior 全都走这条路径）。
        """
        if self.tracks is None or self.tlp_hash is None:
            return None
        dt = self._dt_for(field, comp)
        if dt is None:
            return None
        mode = self.config.timl_interp if self.config else "native"
        c1 = self.tracks.curve(1, self.tlp_hash, dt)
        if c1 is not None and age is not None:
            v = c1.eval(float(age), mode)
            if v is not None:
                return v
        c0 = self.tracks.curve(0, self.tlp_hash, dt)
        if c0 is not None and a0_frame is not None:
            return c0.eval(float(a0_frame), mode)
        return None

    def _apply(self, base, timl_v):
        if timl_v is None:
            return base
        if self.config is not None and self.config.timl_mode == "multiply":
            return base * timl_v
        return timl_v      # 'replace'（默认，见 config.UNKNOWNS['timl_mode']）

    # ── 对外 ─────────────────────────────────────────────────────────────────
    def scalar(self, field, a0_frame, age, comp=0, default=0.0):
        base = self.raw_value(field, default)
        if isinstance(base, (list, tuple)):
            base = base[comp] if comp < len(base) else default
        return self._apply(float(base), self._timl_value(field, comp, a0_frame, age))

    def xyz_half(self, field, a0_frame, age, high=False, default=(0.0, 0.0, 0.0)):
        """FLOAT6（XYZ type 0）的一半 → Vec3，已套 TIML。

        `high=False` 取 idx 0/2/4，`high=True` 取 idx 1/3/5。这一对**是什么**取决于
        字段（rangeXYZ=Min/Max，translate=值/抖动），本函数只负责取值，不作解释。
        """
        v = self.raw_value(field, None)
        if not isinstance(v, (list, tuple)) or len(v) < 6:
            return Vec3(*default)
        base = 1 if high else 0
        out = []
        for axis in range(3):
            raw = float(v[axis * 2 + base])
            comp = self._axis_comp(field, axis, high)
            tv = None if comp is None else self._timl_value(field, comp, a0_frame, age)
            out.append(self._apply(raw, tv))
        return Vec3(*out)


# ─────────────────────────────────────────────────────────────────────────────
# FieldView —— 绑定到具体 (a0_frame, age) 的只读视图
# ─────────────────────────────────────────────────────────────────────────────

class FieldView(object):
    """behavior 实际拿到的东西。`view.speed` = 已套好 EXTERN + TIML 的标量。"""

    __slots__ = ("_r", "_a0", "_age")

    def __init__(self, resolver, a0_frame, age):
        self._r = resolver
        self._a0 = a0_frame
        self._age = age

    def __getattr__(self, name):
        """`view.speed` 式取值。**字段不存在就抛**——拼错字段名必须炸，
        不能静默返回 0 让 behavior 带着错误值跑下去。要默认值用 `get()`。"""
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._r.raw and name not in self._r.extern_overrides:
            raise AttributeError(
                "%s 没有字段 %r（拼错了？要默认值请用 .get(%r, default)）"
                % (self._r.block_name or "该属性", name, name))
        return self._r.scalar(name, self._a0, self._age)

    # 显式方法（不走 __getattr__，避免和字段名撞车）
    def get(self, field, default=0.0):
        """标量取值，字段不存在时给 default。"""
        if field not in self._r.raw and field not in self._r.extern_overrides:
            return default
        return self._r.scalar(field, self._a0, self._age, default=default)

    def raw(self, field, default=None):
        """未经 TIML 调制的原始值（list 字段、枚举、位掩码用）。"""
        return self._r.raw_value(field, default)

    def i(self, field, default=0):
        """整数字段（帧数、枚举、位掩码）。TIML 调制后取整。"""
        return int(round(self.get(field, default)))

    def xyz_lo(self, field, default=(0.0, 0.0, 0.0)):
        """FLOAT6 的前一半（idx 0/2/4）→ Vec3。"""
        return self._r.xyz_half(field, self._a0, self._age, False, default)

    def xyz_hi(self, field, default=(0.0, 0.0, 0.0)):
        """FLOAT6 的后一半（idx 1/3/5）→ Vec3。"""
        return self._r.xyz_half(field, self._a0, self._age, True, default)

    #: 多数字段前一半是主值，故留个短别名
    xyz = xyz_lo

    def has(self, field):
        return field in self._r.raw

    def __repr__(self):
        return "<FieldView %s a0=%s age=%s>" % (self._r.block_name, self._a0, self._age)
