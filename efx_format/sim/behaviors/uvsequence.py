# -*- coding: utf-8 -*-
"""UVSEQUENCE —— 序列帧：为渲染主体选择贴图中的一格。

UVSEQUENCE 不是渲染主体，而是在渲染体产出 `RenderItem` 之后修改其 UV，因此位于 `RENDER_MOD`
阶段。一个 entry 至多带一个 UVSEQUENCE，无需处理多个实例的覆盖顺序。

帧表不由核心层读取文件：属性中只有 `uvsPath`（游戏相对路径），帧矩形位于 `.uvs` 文件中，由
宿主将字节写入 `SimResources`，此处按 `sequenceNo`（即 group 下标）取对应 group。无法取得时
按 H×V 网格生成并记录 note。

时间模型：

    每帧： phase += speed ；随后 speed *= playSpeedCoef

先推进后衰减，第一帧按原速度推进。该模型为逐帧乘法递推，而非 dt 积分。`playSpeed` 常由 TIML
驱动（UVSEQUENCE 的原生时间轴是 A1 寿命轴），因此闭式解 `phase = Σ speed·coef^k` 不适用，只能
逐帧递推；由 TIML 驱动时，本帧速度取「曲线值 + 出生时抽取的抖动偏移」，使替换语义与抖动并存。

`playbackMode`（`loopingMode` 的 bit0-1）：

    0 仅显示起始帧      不推进
    1 循环              (start + ⌊phase⌋) mod n
    2 播放一次后消失    完成一轮后粒子死亡
    3 播放一次后停止    停留在末帧

「一轮」指从起始帧到序列末尾还是完整序列，尚未确认，由 `SimConfig.uvs_once_span` 选择。

翻转与朝向均在出生时抽取，循环期间不重新抽取：`flipHorizontal` / `flipVertical` 各取 0=不翻转、
1=固定翻转、2=随机翻转；`loopingOrientation` 取 0=正常、1=顺时针 90°、2=逆时针 90°、3=随机。
语料中以随机取值为主，若不实现，预览会明显比游戏内规整。

维护约束：
- `phase` 必须在 `on_particle_step` 中推进，`build_render` 只读。`build_render` 可能被重复调用
  （例如暂停时旋转视角），必须没有副作用。RENDER_MOD 阶段 behavior 的 step 排在 SHADE 之后、
  每帧最后执行；`p.user` 在任何阶段都允许写入。
- `playbackMode=2` 是 UVSEQUENCE 唯一影响寿命的情形，粒子死亡必须在 step 中处理，不得放在渲染
  过程中。
"""

import math

from ...hashes import UVSEQUENCE
from ..registry import Behavior, register
from ..rng import jitter, jitter_int
from ..stages import RENDER_MOD

# playbackMode（loopingMode bit0-1）
PB_START_ONLY = 0
PB_LOOP = 1
PB_ONCE_VANISH = 2
PB_ONCE_HOLD = 3

# flipHorizontal / flipVertical 每轴的取值（bit2-3 / bit4-5）
FLIP_NONE = 0
FLIP_ALWAYS = 1
FLIP_RANDOM = 2

# direction（bit6-7）
DIR_FORWARD = 0
DIR_REVERSE = 1
DIR_RANDOM = 2

#: loopingOrientation：3 表示在前三种之中随机选取
ORIENT_RANDOM = 3

#: loopingOrientation 取值到 90° 旋转次数（`corners()` 的 turns）的映射。
#: 旋转方向的正负未经实机验证；若方向相反，对调表中的 1 与 3。
_ORIENT_TURNS = {0: 0, 1: 1, 2: 3}


def _roll_flip(code, rng):
    """按 flipHorizontal/flipVertical 的单轴取值，返回本粒子是否翻转。"""
    if code == FLIP_ALWAYS:
        return True
    if code == FLIP_RANDOM:
        return rng.random() < 0.5
    return False          # FLIP_NONE 以及非法值 3


def frame_info(p):
    """返回 `(帧号, 总帧数, 帧表来源)`，供 UI 调试显示；粒子没有序列帧信息时返回 None。"""
    st = p.user.get(UVSequence)
    if not st:
        return None
    return (st["frame"], st["n"], st["source"])


@register(UVSEQUENCE)
class UVSequence(Behavior):
    """RENDER_MOD 阶段将当前帧的 UV 写入上游渲染体产出的 RenderItem。"""

    STAGE = RENDER_MOD
    #: 排在其它渲染修饰之前：先确定使用哪一格，再修改该格的显示。
    ORDER = 50

    _table = None
    _fell_back = False
    _has_tracks = False
    _group = 0

    # ── 发射器级：帧表只解析一次 ──────────────────────────────────────────────
    def on_emitter_init(self, em, rng):
        f = em.f(UVSEQUENCE)
        if f is None:
            return
        self._has_tracks = f.has_tracks
        seq = f.i("sequenceNo")
        self._group = seq
        self._table, self._fell_back = em.resources.uvs_table(seq, em.config)
        if self._fell_back:
            grid = self._table.grid or (0, 0)
            em.note("没有载入 .uvs（sequenceNo=%d）：序列帧按 %d×%d 网格假设"
                    % (seq, grid[0], grid[1]))

    # ── 出生：抽取翻转、朝向、起始帧与速度 ─────────────────────────────────────
    def on_particle_spawn(self, p, em, rng):
        f = em.f(UVSEQUENCE, p)
        if f is None or self._table is None:
            return
        cfg = em.config
        mode = cfg.jitter_mode
        n = len(self._table)
        if n <= 0:
            return

        packed = f.i("loopingMode")
        playback = packed & 0x03
        flip_u = _roll_flip((packed >> 2) & 0x03, rng)
        flip_v = _roll_flip((packed >> 4) & 0x03, rng)
        direction = (packed >> 6) & 0x03

        orient = f.i("loopingOrientation")
        if orient == ORIENT_RANDOM:
            orient = rng.randint(0, 2)
        turns = _ORIENT_TURNS.get(orient, 0)

        # 随机播放方向在出生时确定；负的 playSpeed 同样表示倒放，两者相乘即可
        sign = -1.0 if direction == DIR_REVERSE else 1.0
        if direction == DIR_RANDOM:
            sign = -1.0 if rng.random() < 0.5 else 1.0

        static_speed = f.get("playSpeed", 0.0)
        speed = jitter(static_speed, f.get("playSpeedJitter"), rng, mode)
        coef = jitter(f.get("playSpeedCoef", 1.0), f.get("playSpeedCoefJitter"),
                      rng, mode)

        start = jitter_int(f.get("patternNo", 0), f.get("patternNoJitter"), rng, mode)
        wrap = cfg.uvs_start_wrap == "wrap"
        start = self._table.index(start, wrap)

        # 「播放一次」推进的格数
        if cfg.uvs_once_span == "full_cycle":
            span = n - 1
        elif sign < 0:
            span = start                 # 倒放至第 0 格
        else:
            span = n - 1 - start         # 正放至末格

        p.user[UVSequence] = {
            "phase": 0.0,
            "speed": speed,
            # TIML 驱动 playSpeed 时，以「曲线值 + 该偏移」保留出生时抽取的抖动
            "speed_offset": speed - static_speed,
            "coef": coef,
            "start": start,
            "frame": start,
            "n": n,
            "source": self._table.source,
            "playback": playback,
            "sign": sign,
            "span": max(0, span),
            "flip_u": flip_u,
            "flip_v": flip_v,
            "turns": turns,
            "wrap": wrap,
        }

    # ── 逐帧：推进 phase（build_render 只读，不得在其中累积）─────────────────
    def on_particle_step(self, p, em):
        st = p.user.get(UVSequence)
        if st is None:
            return
        playback = st["playback"]
        if playback == PB_START_ONLY:
            return                        # 仅显示起始帧，phase 无需推进

        speed = st["speed"]
        if self._has_tracks:
            f = em.f(UVSEQUENCE, p)
            if f is not None:
                speed = f.get("playSpeed", 0.0) + st["speed_offset"]
                st["coef"] = f.get("playSpeedCoef", st["coef"])

        step = speed * st["sign"]
        if em.config.uvs_speed_unit == "per_second":
            step /= float(em.config.fps or 60)

        st["phase"] += step
        st["speed"] = speed * st["coef"]   # 先推进再衰减
        st["frame"] = self._frame_of(st)

        if playback == PB_ONCE_VANISH and abs(st["phase"]) >= st["span"] + 1:
            p.alive = False

    @staticmethod
    def _frame_of(st):
        """返回当前帧号，已按 playbackMode 处理循环与截断。"""
        adv = int(math.floor(abs(st["phase"])))
        playback = st["playback"]
        if playback == PB_START_ONLY:
            return st["start"]
        if playback == PB_LOOP:
            n = st["n"]
            return (st["start"] + int(st["sign"]) * adv) % n if n > 0 else 0
        # 播放一次（消失或停止）：截断在本轮终点。full_cycle 下起点非 0 时终点超出帧数，
        # 取模回到 [0, n)
        adv = min(adv, st["span"])
        n = st["n"]
        idx = st["start"] + int(st["sign"]) * adv
        return idx % n if n > 0 else 0

    # ── 渲染：只读 ───────────────────────────────────────────────────────────
    def build_render(self, p, em, view, item):
        if item is None:
            return None                   # 没有可修改的渲染体，交由上层生成退化点
        st = p.user.get(UVSequence)
        if st is None or self._table is None:
            return item

        idx = st["frame"]
        wrap = st["wrap"]
        item.uv_rect = self._table.rect(idx, wrap)
        item.uv_corners = self._table.corners(
            idx, st["flip_u"], st["flip_v"], st["turns"], wrap)
        # 调试量：面板与叠加层据此显示当前帧
        item.extra["uvs_frame"] = idx
        item.extra["uvs_n"] = st["n"]
        item.extra["uvs_source"] = st["source"]
        item.extra["uvs_group"] = self._group
        return item
