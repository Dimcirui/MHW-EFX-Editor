# -*- coding: utf-8 -*-
"""
efx_format/sim/state.py  —  模拟器的数据结构（Vec3 / Particle / EmitterState / RenderItem）

坐标系
------
本层**全程使用游戏坐标系**（+X=左，+Y=上，+Z=前，见 annotations.py 的
VELOCITY3D.baseAxis 条目）。到 Blender 坐标的换算是 glue 层的事，核心层不碰——
这样核心可以脱离 Blender 单测，也能被别的前端原样复用。

时间单位
--------
全程用**整数帧**（EFX 的所有 duration/interval/delay 都是 int）。一帧 = 1/`SimConfig.fps`
秒，默认 60。逐帧乘法递推（speedCoef 每帧乘一次）不是 dt 积分，不要引入 dt。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
"""

import math


# ─────────────────────────────────────────────────────────────────────────────
# Vec3 —— 极简三维向量（零依赖；几百粒子规模下比 tuple + 函数更可读，且够快）
# ─────────────────────────────────────────────────────────────────────────────

class Vec3(object):
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    # ── 构造 / 转换 ──────────────────────────────────────────────────────────
    @classmethod
    def from_seq(cls, seq):
        return cls(seq[0], seq[1], seq[2])

    def copy(self):
        return Vec3(self.x, self.y, self.z)

    def as_tuple(self):
        return (self.x, self.y, self.z)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __len__(self):
        return 3

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __repr__(self):
        return "Vec3(%.4f, %.4f, %.4f)" % (self.x, self.y, self.z)

    def __eq__(self, other):
        if not isinstance(other, Vec3):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __hash__(self):
        return hash((self.x, self.y, self.z))

    # ── 运算 ─────────────────────────────────────────────────────────────────
    def __add__(self, o):
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __neg__(self):
        return Vec3(-self.x, -self.y, -self.z)

    def __mul__(self, s):
        if isinstance(s, Vec3):   # 逐分量乘（缩放向量用）
            return Vec3(self.x * s.x, self.y * s.y, self.z * s.z)
        return Vec3(self.x * s, self.y * s, self.z * s)

    __rmul__ = __mul__

    def __iadd__(self, o):
        self.x += o.x
        self.y += o.y
        self.z += o.z
        return self

    def __isub__(self, o):
        self.x -= o.x
        self.y -= o.y
        self.z -= o.z
        return self

    def __imul__(self, s):
        if isinstance(s, Vec3):
            self.x *= s.x
            self.y *= s.y
            self.z *= s.z
        else:
            self.x *= s
            self.y *= s
            self.z *= s
        return self

    # ── 度量 ─────────────────────────────────────────────────────────────────
    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def length_sq(self):
        return self.x * self.x + self.y * self.y + self.z * self.z

    def normalized(self, fallback=None):
        """长度为 0 时返回 `fallback`（默认零向量），不抛。"""
        n = self.length()
        if n <= 1e-12:
            return fallback.copy() if fallback is not None else Vec3()
        return Vec3(self.x / n, self.y / n, self.z / n)

    def dot(self, o):
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o):
        return Vec3(self.y * o.z - self.z * o.y,
                    self.z * o.x - self.x * o.z,
                    self.x * o.y - self.y * o.x)


ZERO = Vec3()
ONE = Vec3(1.0, 1.0, 1.0)

#: VELOCITY3D.baseAxis 的六个基准轴（游戏坐标系：+X=左 +Y=上 +Z=前）
#: 0=左 1=上 2=前 3=右 4=下 5=后（annotations.py ("VELOCITY3D","baseAxis")）
BASE_AXES = (
    Vec3(1.0, 0.0, 0.0),
    Vec3(0.0, 1.0, 0.0),
    Vec3(0.0, 0.0, 1.0),
    Vec3(-1.0, 0.0, 0.0),
    Vec3(0.0, -1.0, 0.0),
    Vec3(0.0, 0.0, -1.0),
)


# ─────────────────────────────────────────────────────────────────────────────
# Particle
# ─────────────────────────────────────────────────────────────────────────────

class Particle(object):
    """一个粒子的全部状态。

    `rolled`：出生时抽定的抖动值（speedJitter 之类每粒子定死一次的常量）。
    `user`  ：behavior 私有的逐粒子状态，按 behavior 类做 key——新属性存自己的
              东西不必改这里的 __slots__，这是「可扩展」的落点之一。
    """

    __slots__ = (
        # 身份
        "index", "seed", "birth_frame",
        # 时间
        "age", "life", "delay_left", "alive",
        # 运动
        "pos", "vel", "spawn_pos",
        # 外观
        "scale", "rot", "color", "alpha",
        # 轨迹历史（只有需要的 behavior 声明 NEEDS_TRAIL 时才记录，见 simulator）
        "trail",
        # 扩展
        "rolled", "user",
    )

    def __init__(self, index, seed, birth_frame):
        self.index = index
        self.seed = seed
        self.birth_frame = birth_frame

        self.age = 0
        self.life = 0           # 由 LIFE behavior 在 spawn 时写；0 = 尚未设定
        self.delay_left = 0     # SPAWN.particleSpawnDelay
        self.alive = True

        self.pos = Vec3()
        self.vel = Vec3()
        self.spawn_pos = Vec3()  # 出生位置（相对发射器原点）；velocityType 1/2 要用

        self.scale = Vec3(1.0, 1.0, 1.0)
        self.rot = Vec3()        # 角度制，游戏坐标系
        self.color = [1.0, 1.0, 1.0]
        self.alpha = 1.0

        #: 最近若干帧的位置（旧→新，末尾是当前帧）。条带类渲染体要用；
        #: 不需要的时候恒为空列表，不占成本。
        self.trail = []

        self.rolled = {}
        self.user = {}

    @property
    def active(self):
        """已出生且过了 particleSpawnDelay —— 只有 active 的粒子参与 step / 渲染。"""
        return self.alive and self.delay_left <= 0

    def __repr__(self):
        return ("<Particle #%d age=%d/%d pos=%s alive=%s>"
                % (self.index, self.age, self.life, self.pos, self.alive))


# ─────────────────────────────────────────────────────────────────────────────
# SpawnRequest —— 粒子死亡/碰撞触发的子发射（PTLIFE / PTCOLLISION，T4 用）
# ─────────────────────────────────────────────────────────────────────────────

class SpawnRequest(object):
    """一次子发射请求。现在只占位——顶层 Simulator 收集但不消化。

    ⚠ 消化它的时候记得设递归深度上限：validate.py 已经在查 Action loop，说明
    循环引用在真实文件里是存在的，模拟器撞上会直接挂死。
    """

    __slots__ = ("kind", "target", "pos", "scale", "delay", "source_hash")

    def __init__(self, kind, target, pos=None, scale=None, delay=0, source_hash=0):
        self.kind = kind            # 'entry'（PLAYEMITTER）| 'efx'（PLAYEFX）
        self.target = target
        self.pos = pos or Vec3()
        self.scale = scale or Vec3(1.0, 1.0, 1.0)
        self.delay = int(delay)
        self.source_hash = source_hash

    def __repr__(self):
        return "<SpawnRequest %s %r @%s>" % (self.kind, self.target, self.pos)


# ─────────────────────────────────────────────────────────────────────────────
# RenderItem —— 渲染 pass 的产物（纯数据，glue 层翻译成 GPU batch）
# ─────────────────────────────────────────────────────────────────────────────

class RenderItem(object):
    """一个待绘制单元。RENDER_BODY 阶段产出，RENDER_MOD 阶段就地修改。"""

    __slots__ = ("kind", "pos", "size", "rot", "color", "uv_rect",
                 "blend", "tex_key", "extra", "points", "axis_u", "axis_v")

    def __init__(self, kind="BILLBOARD", pos=None, size=None, rot=0.0):
        #: 'BILLBOARD'（面朝相机的片）| 'PLANE'（固定朝向的片）| 'RIBBON'（条带）
        #: | 'MESH'（宿主绑定的网格）| 'POINT'（无渲染体时的退化显示）
        #: | 'NONE'（**显式**不渲染，例如 DUMMY——与「没有渲染体」不是一回事）
        self.kind = kind
        self.pos = pos or Vec3()
        self.size = size or Vec3(1.0, 1.0, 1.0)
        self.rot = rot                       # 屏幕空间自转（角度制）
        self.color = [1.0, 1.0, 1.0, 1.0]    # RGBA
        self.uv_rect = (0.0, 0.0, 1.0, 1.0)  # (u0, v0, u1, v1)
        self.blend = "ALPHA"                 # 'ALPHA' | 'ADDITIVE' | 'MULTIPLY'
        self.tex_key = None                  # 贴图标识，由 glue 层解释

        #: 条带类（kind='RIBBON'）的顶点串：[(pos, half_width, alpha_mul), ...]，
        #: 从尾到头。glue 层按相机方向把它撑成三角带。
        self.points = None

        #: 面片的朝向。为 None 时 glue 层按**面朝相机**画（BILLBOARD3D）；
        #: 给了就用这一对作为面片的横/纵轴（PLANE 这类固定朝向的渲染体）。
        self.axis_u = None
        self.axis_v = None

        self.extra = {}

    def __repr__(self):
        return "<RenderItem %s @%s %s>" % (self.kind, self.pos, self.blend)


# ─────────────────────────────────────────────────────────────────────────────
# ViewContext —— 渲染 pass 的视角输入（FADEBY* 之类要用）
# ─────────────────────────────────────────────────────────────────────────────

class ViewContext(object):
    """相机信息，由 glue 层填。**step() 拿不到它**——逐帧模拟必须与视角无关，
    这样暂停时转视角只需重跑 build_render，核心也能没有相机就单测。"""

    __slots__ = ("cam_pos", "cam_forward", "cam_up", "cam_right", "viewport")

    def __init__(self, cam_pos=None, cam_forward=None, cam_up=None,
                 cam_right=None, viewport=(1920, 1080)):
        self.cam_pos = cam_pos or Vec3(0.0, 0.0, -1000.0)
        self.cam_forward = cam_forward or Vec3(0.0, 0.0, 1.0)
        self.cam_up = cam_up or Vec3(0.0, 1.0, 0.0)
        self.cam_right = cam_right or Vec3(1.0, 0.0, 0.0)
        self.viewport = viewport
