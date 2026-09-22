# -*- coding: utf-8 -*-
"""PARENTOPTIONS —— 发射器与粒子的绑定关系。

字段职能：

    particleUseLocal        跟随发射器。开启时，已发射的粒子随发射器移动；关闭时，粒子只以
                            **出生时刻**的原点为准，与此后发射器的运动无关
    constRelease(+Jitter)   停止跟随的帧数，到达后固定在当前位置。0 表示始终跟随
    relationPos /           逐轴的平移／旋转／缩放跟随模式。跟随对象是**父级（发射该粒子的
    relationRot /           发射器）**，而非玩家或地图。0=不跟随、1=跟随（默认），2 / 3 语义
    relationScl             未确定
    jointNo                 绑定骨骼。Blender 侧已按骨骼放置 entry，模拟层不重复处理

三组 relation 按「三轴是否均为 1」整体判定，不区分逐轴；三轴不一致或出现 2 / 3 时按不跟随
处理并记录 note。`particleUseLocal` 只控制位置，旋转与缩放跟随分别由 relationRot /
relationScl 决定。

跟随以**增量**方式实现：每帧施加发射器相对上一帧的位移、旋转增量与缩放比例，而非每帧重新计算
出生时的偏移——后者会抹去粒子自身的运动（VELOCITY3D 积分的位移）。增量方式下两者叠加：粒子按
自身速度运动，同时随发射器整体平移、旋转与缩放。旋转跟随除旋转位置偏移外，还同时旋转
`p.vel` 与 `p.vel_free`，否则下一帧的运动方向与已旋转的位置不一致；缩放跟随同理，按比例缩放
偏移与速度。发射器持续旋转且粒子径向运动时，世界空间轨迹为螺旋线。

维护约束：
- 必须排在其它 CONSTRAIN 之前：先随发射器移动，再由约束类属性覆写位置。
- 停止跟随的计时时钟未确认，由 `SimConfig.parent_release_clock` 选择，默认取逐粒子 age：该
  字段带 Jitter，只有按粒子计时抖动才有意义。停止跟随后，位置、旋转、缩放三种跟随同时停止，
  与 `particleUseLocal` 共用同一判定。
"""

from ...hashes import PARENTOPTIONS
from ..registry import Behavior, register
from ..rng import jitter_int
from ..stages import CONSTRAIN
from ..state import Vec3
from ..vecmath import rotate_euler

#: relationPos/Rot/Scl 的两个已确认取值：0=不跟随该通道，1=跟随（默认）。
_TRACK_STOP = 0
_TRACK_FOLLOW = 1


def _uniform_axis(raw):
    """三个分量相等时返回该值；不一致或数据不完整时返回 None。"""
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    a, b, c = int(raw[0]), int(raw[1]), int(raw[2])
    return a if a == b == c else None


def _total_rotation(em):
    """返回发射器当前的总旋转，即自身旋转与从 PTLIFE 父实例继承的旋转之和。"""
    r, h = em.rot_dynamic, em.host_rotation
    return Vec3(r.x + h.x, r.y + h.y, r.z + h.z)


@register(PARENTOPTIONS)
class ParentOptions(Behavior):
    """CONSTRAIN 阶段按开关将发射器的位移、旋转增量与缩放比例施加到粒子上。"""

    STAGE = CONSTRAIN
    #: 必须排在其它 CONSTRAIN 之前，原因见模块 docstring。
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

        # 仅在取值不属于 {0, 1} 时记录 note：0/1 为已实现的语义，无需逐块提示
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
            "last": em.origin.copy(),           # 上一帧的发射器原点，用于计算位移增量
            "last_rot": _total_rotation(em),    # 上一帧的发射器总旋转，用于计算旋转增量
            "last_scale": em.scale_dynamic.copy(),  # 上一帧的发射器动态缩放
            "release": release,                 # 0 表示始终跟随
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
                return                    # 停止跟随，固定在当前位置

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
                # 自由速度通道同步旋转；HOMING 的部分在下一帧按新方向重新计算
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
