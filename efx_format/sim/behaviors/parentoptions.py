# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/parentoptions.py  —  PARENTOPTIONS（发射器与粒子的绑定关系）

本模块只做两件事（用户划的范围）
--------------------------------
    particleUseLocal  「跟随发射器」：开 → 已经发出去的粒子跟着发射器一起走；
                      关 → 粒子只认**出生那一刻**的原点，之后发射器怎么动都与它无关。
    constRelease(+Jitter)「停止追踪帧数」：跟随开启后，数到这个帧数就停止跟随、
                      就地锁定。0 = 一直跟。

**刻意没做**（如实 note 出来，预览不假装支持）：
    relationPos / relationRot / relationScl   逐轴的平移/角度/缩放跟踪模式
                      （0=绝对追踪地图中心 / 1=追踪玩家移动 / 2=不再追踪后续移动 …）
                      ——这些讲的是特效与**玩家/地图**的关系，预览里没有玩家也没有
                      地图，做出来只能是猜的。
    jointNo           绑定骨骼：Blender 侧已由 transform_sync.py 按骨骼摆好 entry，
                      模拟层重复处理会双份。

跟随怎么实现
------------
逐帧把「发射器这一帧的位移」加到粒子位置上（写 p.pos → CONSTRAIN 阶段）。
不是「每帧重算 出生偏移 + 当前原点」——那样会把粒子自己的运动（VELOCITY3D 积出来的
位移）一并抹掉。加增量则两者共存：粒子照自己的速度飞，同时被发射器整体拖着走。

「数到帧数就停」数的是哪个时钟（粒子自己的 age，还是发射器时间轴）未确认，
`SimConfig.parent_release_clock` 是开关。默认逐粒子 age——这个字段自带 Jitter，
只有逐粒子抽才用得上抖动。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import PARENTOPTIONS
from ..registry import Behavior, register
from ..rng import jitter_int
from ..stages import CONSTRAIN

#: relationPos/Rot/Scl 的「什么都不做」取值。语料里 0 是绝大多数，
#: 非 0 说明作者挑了别的跟踪模式，而我们没实现——那时才 note，免得逢块就刷屏。
_TRACK_DEFAULT = 0


@register(PARENTOPTIONS)
class ParentOptions(Behavior):
    """CONSTRAIN 阶段：只在「跟随发射器」开着时把发射器位移加到粒子上。"""

    STAGE = CONSTRAIN
    #: 排在其它 CONSTRAIN 之前：先跟着发射器走，再让真正的约束类（PATHCHAIN /
    #: REPEATAREA / 碰撞）去覆写位置。
    ORDER = 10

    _follow = False
    _release = 0
    _release_jitter = 0

    def on_emitter_init(self, em, rng):
        f = em.f(PARENTOPTIONS)
        if f is None:
            return
        self._follow = bool(f.i("particleUseLocal"))
        self._release = max(0, f.i("constRelease"))
        self._release_jitter = max(0, f.i("constReleaseJitter"))

        # 未实现的部分如实报一次
        unhandled = []
        for name in ("relationPos", "relationRot", "relationScl"):
            raw = f.raw(name)
            if isinstance(raw, (list, tuple)) and any(
                    int(x) != _TRACK_DEFAULT for x in raw):
                unhandled.append(name)
        if unhandled:
            em.note("PARENTOPTIONS 的 %s 跟踪模式未模拟（预览没有玩家/地图可追）"
                    % "/".join(unhandled))
        if f.i("jointNo", -1) >= 0:
            em.note("PARENTOPTIONS 绑定了骨骼（jointNo=%d）：摆位由宿主负责，"
                    "模拟层不再重复处理" % f.i("jointNo", -1))
        if not self._follow:
            em.note("PARENTOPTIONS 未开「跟随发射器」：粒子只认出生那一刻的原点")

    def on_particle_spawn(self, p, em, rng):
        if not self._follow:
            return
        release = self._release
        if release and self._release_jitter:
            release = max(0, jitter_int(release, self._release_jitter, rng,
                                        em.config.jitter_mode))
        p.user[ParentOptions] = {
            "last": em.origin.copy(),     # 上一帧的发射器原点（算增量用）
            "release": release,           # 0 = 永远跟随
            "birth": em.frame,
        }

    def on_particle_step(self, p, em):
        st = p.user.get(ParentOptions)
        if st is None:
            return

        release = st["release"]
        if release:
            if em.config.parent_release_clock == "emitter_frame":
                elapsed = em.frame - st["birth"]
            else:
                elapsed = p.age
            if elapsed >= release:
                return                    # 停止追踪 → 就地锁定，不再跟

        origin = em.origin
        last = st["last"]
        dx = origin.x - last.x
        dy = origin.y - last.y
        dz = origin.z - last.z
        if dx or dy or dz:
            p.pos.x += dx
            p.pos.y += dy
            p.pos.z += dz
        st["last"] = origin.copy()
