# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/parentoptions.py  —  PARENTOPTIONS（发射器与粒子的绑定关系）

本模块做的事
------------
    particleUseLocal  「跟随发射器」：开 → 已经发出去的粒子跟着发射器一起走；
                      关 → 粒子只认**出生那一刻**的原点，之后发射器怎么动都与它无关。
    constRelease(+Jitter)「停止追踪帧数」：跟随开启后，数到这个帧数就停止跟随、
                      就地锁定。0 = 一直跟。
    relationPos / relationRot / relationScl   逐轴的平移/角度/缩放跟踪模式，
                      每轴一个枚举。⚠ 曾经按字面读成「与玩家/地图的关系」而搁置——
                      用户订正：这三组跟的其实是**父级（发出这个粒子的发射器自己）**，
                      不是玩家/地图。"三轴几乎总是同值"（语料 99%+），故按「三轴是否
                      全部等于默认值 1（追踪）」判定，不拆分到逐轴——真出现混轴或
                      2/3 这类罕见取值时，保守按「不追踪」处理并如实 note。
                      `particleUseLocal` 只管**位置**（本来就有独立实现，见下）；
                      relationRot/relationScl 各自新增对应的角度/缩放跟随。
    jointNo           绑定骨骼：Blender 侧已由 transform_sync.py 按骨骼摆好 entry，
                      模拟层不再重复处理。

跟随怎么实现
------------
逐帧把「发射器这一帧的位移/旋转增量/缩放比例」施加到粒子上（写 p.pos/p.vel →
CONSTRAIN 阶段）。都是**增量式**（这一帧比上一帧多变了多少）而不是「每帧重算
出生时的偏移」——后者会把粒子自己的运动（VELOCITY3D 积出来的位移）一并抹掉。
增量式则两者共存：粒子照自己的速度飞，同时被发射器整体拖着走/转/缩。

角度跟随是「粒子被自转的发射器带着转」的机制：粒子位置相对发射器原点的偏移量，
按发射器这一帧比上一帧多转的角度旋转；连粒子自己的速度矢量 `p.vel` 也一并转，
不然下一帧的直线飞行方向就和已经转过的位置对不上。发射器持续旋转 + 粒子径向
飘移 = 世界空间里的螺旋轨迹，这正是某些效果（转起来的发射器带着一串粒子甩出去）
需要的形状。缩放跟随同理，只是换成按比例缩放偏移量与速度。

「数到帧数就停」数的是哪个时钟（粒子自己的 age，还是发射器时间轴）未确认，
`SimConfig.parent_release_clock` 是开关。默认逐粒子 age——这个字段自带 Jitter，
只有逐粒子抽才用得上抖动。停止追踪之后位置/旋转/缩放三种跟随一起停，与
`particleUseLocal` 共用同一个 release 判定。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import PARENTOPTIONS
from ..registry import Behavior, register
from ..rng import jitter_int
from ..stages import CONSTRAIN
from ..state import Vec3
from ..vecmath import rotate_euler

#: relationPos/Rot/Scl 的两个已理解取值：0=不追踪父级这个通道，1=追踪（默认）。
#: 2/3 語义未定，遇到时按「不追踪」处理并 note，不当 0/1 那样静默生效。
_TRACK_STOP = 0
_TRACK_FOLLOW = 1


def _uniform_axis(raw):
    """三个分量是否全相等；相等则返回该值，混轴或数据不全返回 None。"""
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    a, b, c = int(raw[0]), int(raw[1]), int(raw[2])
    return a if a == b == c else None


def _total_rotation(em):
    """发射器此刻的总旋转：自己转的 + 从 PTLIFE 父实例继承的（见 scene.py::_follow）。"""
    r, h = em.rot_dynamic, em.host_rotation
    return Vec3(r.x + h.x, r.y + h.y, r.z + h.z)


@register(PARENTOPTIONS)
class ParentOptions(Behavior):
    """CONSTRAIN 阶段：按开关把发射器的位移/旋转增量/缩放比例施加到粒子上。"""

    STAGE = CONSTRAIN
    #: 排在其它 CONSTRAIN 之前：先跟着发射器走，再让真正的约束类（PATHCHAIN /
    #: REPEATAREA / 碰撞）去覆写位置。
    ORDER = 10

    _follow = False
    _release = 0
    _release_jitter = 0
    _follow_rot = False
    _follow_scale = False

    def on_emitter_init(self, em, rng):
        f = em.f(PARENTOPTIONS)
        if f is None:
            return
        self._follow = bool(f.i("particleUseLocal"))
        self._release = max(0, f.i("constRelease"))
        self._release_jitter = max(0, f.i("constReleaseJitter"))

        pos_v = _uniform_axis(f.raw("relationPos"))
        rot_v = _uniform_axis(f.raw("relationRot"))
        scl_v = _uniform_axis(f.raw("relationScl"))
        self._follow_rot = (rot_v == _TRACK_FOLLOW)
        self._follow_scale = (scl_v == _TRACK_FOLLOW)

        # 三个取值都不在 {0, 1}（混轴，或用了未理解的 2/3）才 note——0/1 两态
        # 已经是理解、消费过的语义，不该逢块就刷屏。
        unhandled = [name for name, v in
                    (("relationPos", pos_v), ("relationRot", rot_v),
                     ("relationScl", scl_v))
                    if v not in (_TRACK_STOP, _TRACK_FOLLOW)]
        if unhandled:
            em.note("PARENTOPTIONS 的 %s 用了未理解的追踪档位（三轴不一致，或取值"
                    "不是 0/1），按不追踪处理" % "/".join(unhandled))
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
            "last": em.origin.copy(),           # 上一帧的发射器原点（算位移增量用）
            "last_rot": _total_rotation(em),    # 上一帧的发射器总旋转（算角度增量用）
            "last_scale": em.scale_dynamic.copy(),  # 上一帧的发射器动态缩放
            "release": release,                 # 0 = 永远跟随
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

        if self._follow_rot:
            total_rot = _total_rotation(em)
            last_rot = st["last_rot"]
            drx = total_rot.x - last_rot.x
            dry = total_rot.y - last_rot.y
            drz = total_rot.z - last_rot.z
            if drx or dry or drz:
                order, applied = em.rot_order, em.config.rot_order_applied
                offset = rotate_euler(p.pos - origin, drx, dry, drz,
                                      order=order, applied=applied)
                p.pos.x, p.pos.y, p.pos.z = (origin.x + offset.x,
                                             origin.y + offset.y,
                                             origin.z + offset.z)
                p.vel = rotate_euler(p.vel, drx, dry, drz, order=order,
                                     applied=applied)
                # 自由通道同步转（HOMING 那份下一帧会按新方向重算，不用管）
                p.vel_free = rotate_euler(p.vel_free, drx, dry, drz, order=order,
                                          applied=applied)
            st["last_rot"] = total_rot

        if self._follow_scale:
            s = em.scale_dynamic
            ls = st["last_scale"]
            if s.x != ls.x or s.y != ls.y or s.z != ls.z:
                rx = (s.x / ls.x) if ls.x else 1.0
                ry = (s.y / ls.y) if ls.y else 1.0
                rz = (s.z / ls.z) if ls.z else 1.0
                offset = p.pos - origin
                p.pos.x, p.pos.y, p.pos.z = (origin.x + offset.x * rx,
                                             origin.y + offset.y * ry,
                                             origin.z + offset.z * rz)
                p.vel = Vec3(p.vel.x * rx, p.vel.y * ry, p.vel.z * rz)
                p.vel_free = Vec3(p.vel_free.x * rx, p.vel_free.y * ry,
                                  p.vel_free.z * rz)
            st["last_scale"] = s.copy()
