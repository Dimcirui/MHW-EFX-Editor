# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/uvsequence.py  —  UVSEQUENCE（序列帧：贴哪张图的第几格）

定位
----
UVSEQUENCE 不是渲染主体，是**给主体挑一格贴图** → `RENDER_MOD`，在渲染体产出
`RenderItem` 之后改它的 UV。全语料 10084 个官方文件里，一个 entry 最多一个
UVSEQUENCE（84106 个有的 entry 全是 1 个），所以不必处理「多块叠加谁覆盖谁」。

帧表从哪来
----------
属性里只有 `uvsPath`（游戏相对路径），帧矩形在 `.uvs` 文件里。核心不读文件——
宿主把字节塞进 `SimResources`（见 uvs_table.py），这里按 `sequenceNo` 取对应
group（用户确认：**sequenceNo 就是 group 下标**）。拿不到就按 H×V 网格假设一张，
并 `em.note` 一条——预览不静默撒谎。

时间模型
--------
    每帧： phase += speed ；然后 speed *= playSpeedCoef

先推进再衰减，与 rotateanim.py 的写法一致（第一帧按原速度走）。逐帧乘法递推而
不是 dt 积分——`playSpeedCoef` 的 tooltip 原话就是「每帧乘一次」。

**不能在 build_render 里累积**：它可以被重复调用（暂停时转视角就会重跑），必须
无副作用。所以 phase 在 `on_particle_step` 里推，`build_render` 只读。这不需要
改 simulator：`_h_step` 不按 stage 过滤，而 `bound` 已按 (stage, order) 排序，
于是一个 RENDER_MOD 的 behavior 的 step 自然排在 SHADE 之后、每帧最后跑；写
`p.user` 在任何阶段都是允许的（stages.EXEMPT_SLOTS）。

`playSpeed` 挂 TIML 的很常见（UVSEQUENCE 的原生轴是 A1 寿命轴，语料 99%），所以
闭式解 `phase = Σ speed·coef^k` 不可用——只能逐帧递推。TIML 驱动时，本帧速度取
「曲线值 + 出生时抽到的抖动偏移」，这样 replace 语义与抖动能共存。

playbackMode（loopingMode bit0-1）
----------------------------------
    0 只显示起始帧    —— 不推进（语料里它与 playSpeed==0 完全对齐：17888/17888）
    1 循环            —— (start + ⌊phase⌋) mod n
    2 播一次后消亡    —— 走完一轮把粒子杀掉。**这是 UVSEQUENCE 唯一会影响寿命的
                          地方**，所以它必须在 step 里做，不能在渲染 pass 里。
    3 播一次后定格    —— 夹在末帧

「一轮」是从起始帧到序列末尾还是走满整序列，未确认 → `SimConfig.uvs_once_span`。

翻转与朝向（都在出生时抽定，循环期间不重抽）
--------------------------------------------
flipHorizontal / flipVertical（各 0=不翻 1=固定翻 2=随机翻）和 loopingOrientation
（0=正常 1=顺时针90° 2=逆时针90° 3=随机）在语料里**随机档是主流**（水平随机
66938、垂直随机 47025、朝向随机 29734，共 84106 块），不实现的话预览会明显比
游戏「整齐」。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
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

#: loopingOrientation：3 = 在前三种里随机取一种
ORIENT_RANDOM = 3

#: loopingOrientation 取值 → 90° 圈数（corners() 的 turns）。
#: 1=顺时针 → +1 圈，2=逆时针 → -1 圈（= 3）。旋转方向的正负未实机验证，
#: 看着转反了就把这张表的 1 和 3 对调（见 uvs_table.FrameTable.corners）。
_ORIENT_TURNS = {0: 0, 1: 1, 2: 3}


def _roll_flip(code, rng):
    """flipHorizontal/flipVertical 的一轴 → 本粒子翻不翻。"""
    if code == FLIP_ALWAYS:
        return True
    if code == FLIP_RANDOM:
        return rng.random() < 0.5
    return False          # FLIP_NONE，以及非法的 3


def frame_info(p):
    """`(帧号, 总帧数, 帧表来源)`；这个粒子没有序列帧信息时返回 None。

    给 UI 做调试读数用（P0 阶段还没有贴图，面板显示「当前第几格」是唯一的反馈）。
    """
    st = p.user.get(UVSequence)
    if not st:
        return None
    return (st["frame"], st["n"], st["source"])


@register(UVSEQUENCE)
class UVSequence(Behavior):
    """RENDER_MOD：把当前帧的 UV 写进上游渲染体产出的 RenderItem。"""

    STAGE = RENDER_MOD
    #: 排在其它渲染修饰之前——UV 是「贴哪一格」，与 FADEBY* 那类改颜色的互不相干，
    #: 但先确定贴图内容再谈淡出，读代码时顺序更自然。
    ORDER = 50

    _table = None
    _fell_back = False
    _has_tracks = False
    _group = 0

    # ── 发射器级：帧表只解一次 ───────────────────────────────────────────────
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

    # ── 出生：抽定翻转/朝向/起始帧/速度 ──────────────────────────────────────
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

        # 播放方向：随机档在出生时定一次。负的 playSpeed 也能倒放（语料里只有 7 例），
        # 两者相乘即可，不必特殊处理。
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

        # 「播放一次」走几格
        if cfg.uvs_once_span == "full_cycle":
            span = n - 1
        elif sign < 0:
            span = start                 # 倒着走到第 0 格
        else:
            span = n - 1 - start         # 正着走到末格

        p.user[UVSequence] = {
            "phase": 0.0,
            "speed": speed,
            # TIML 驱动 playSpeed 时，用「曲线值 + 这个偏移」保住出生时抽到的抖动
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

    # ── 逐帧：推进 phase（build_render 只读，不能在那儿累积）──────────────────
    def on_particle_step(self, p, em):
        st = p.user.get(UVSequence)
        if st is None:
            return
        playback = st["playback"]
        if playback == PB_START_ONLY:
            return                        # 只显示起始帧，连 phase 都不用动

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
        st["speed"] = speed * st["coef"]   # 先推进再衰减（同 rotateanim）
        st["frame"] = self._frame_of(st)

        # 播一次后消亡：走完一轮就杀掉。**唯一一处 UVSEQUENCE 影响寿命的地方。**
        if playback == PB_ONCE_VANISH and abs(st["phase"]) >= st["span"] + 1:
            p.alive = False

    @staticmethod
    def _frame_of(st):
        """当前帧号（已按 playbackMode 处理回绕/夹取）。"""
        adv = int(math.floor(abs(st["phase"])))
        playback = st["playback"]
        if playback == PB_START_ONLY:
            return st["start"]
        if playback == PB_LOOP:
            n = st["n"]
            return (st["start"] + int(st["sign"]) * adv) % n if n > 0 else 0
        # 播一次（消亡 / 定格）：夹在这一轮的终点。
        # full_cycle 下终点可能越出帧数（起点非 0 时），回绕收进 [0, n)。
        adv = min(adv, st["span"])
        n = st["n"]
        idx = st["start"] + int(st["sign"]) * adv
        return idx % n if n > 0 else 0

    # ── 渲染：只读 ───────────────────────────────────────────────────────────
    def build_render(self, p, em, view, item):
        if item is None:
            return None                   # 没有渲染体可改（交给上层的退化点）
        st = p.user.get(UVSequence)
        if st is None or self._table is None:
            return item

        idx = st["frame"]
        wrap = st["wrap"]
        item.uv_rect = self._table.rect(idx, wrap)
        item.uv_corners = self._table.corners(
            idx, st["flip_u"], st["flip_v"], st["turns"], wrap)
        # 调试量：P0 还没有贴图，面板/叠加层靠这两个值显示「现在放到第几格」
        item.extra["uvs_frame"] = idx
        item.extra["uvs_n"] = st["n"]
        item.extra["uvs_source"] = st["source"]
        item.extra["uvs_group"] = self._group
        return item
