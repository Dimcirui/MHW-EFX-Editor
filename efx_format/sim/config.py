# -*- coding: utf-8 -*-
"""
efx_format/sim/config.py  —  模拟参数

这个文件的作用不是「配置」，是**把所有未确认的语义收成可调开关**。

项目里每个 `UNKNOWNS` 条目都对应一处「实测才能定」的行为。做成开关而不是写死，
是因为标定它们的方式是在 Blender 里点几下对拍，不是改代码重装插件——把未知
变成参数，标定周期从「一次编辑-重装-重试」压到「拖一下滑块」。

标定完一条，就把默认值改掉、并在 `UNKNOWNS` 里降级成注释（保留开关，但不再
是待办）。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from . import stages as _stages
from .rng import JITTER_ONESIDED


#: 待标定项清单：key → (中文说明, 候选值, 当前默认)
#: UI 可以直接拿它生成一排下拉框；标定完把 default 改掉即可。
UNKNOWNS = {
    "jitter_mode": (
        "抖动分布。已确认是「static 基础上追加 [0, amount]」的单边加法，"
        "具体取值分布未确认，先按均匀。",
        ("onesided", "symmetric", "gaussian"), "onesided",
    ),
    "a0_sample": (
        "TIML A0（发射轴）对粒子级字段的采样点：'spawn'=粒子出生那一帧冻结，"
        "'current'=每帧跟着发射器时间走。"
        "默认 spawn——VELOCITY3D 的 schema 标了 native_timl_axis=0，说明它的轨道"
        "本来就挂在发射轴上，而它的字段又都是出生时定死的初速/方向。",
        ("spawn", "current"), "spawn",
    ),
    "timl_mode": (
        "TIML 关键帧值是**替换**静态字段还是**乘**上去。"
        "默认 replace——timl_tracks.py 新增轨道时用静态字段值做首帧 seed，"
        "目的是「加一条轨道不改变外观」，只有 replace 语义下这才成立。",
        ("replace", "multiply"), "replace",
    ),
    "timl_interp": (
        "关键帧插值。'native'=按 keyframe.transition（0=STUCK 1=CONSTANT 2=LINEAR "
        "3=QUAD 4=CUBIC），QUAD/CUBIC 未验证先退化成线性；'linear'/'constant'=强制。",
        ("native", "linear", "constant"), "native",
    ),
    "life_model": (
        "LIFE 的总寿命怎么算。'sum'=fadeIn+duration+fadeOut；"
        "'duration'=duration 即总长、淡入淡出包含在内。archetype 语料里 fadeIn/"
        "fadeOut 多为 0，两种算法给出相同结果，区分不开。",
        ("sum", "duration"), "sum",
    ),
    "age_during_delay": (
        "SPAWN.particleSpawnDelay 期间粒子的 age 是否推进（影响 TIML A1 与 LIFE）。",
        (False, True), False,
    ),
    "es3d_range_mode": (
        "EMITTERSHAPE3D.rangeXYZ 这一对的含义。'minmax'=前一半是 Min、后一半是 Max"
        "（默认，依据是官方 TimelineParam 通道名 RangeMinX/RangeMaxX/…）；"
        "'offset_size'=前一半是中心偏移、后一半是尺寸（timl_tracks.py 注释里的说法，"
        "只有 Min 恒为 0 时才与 minmax 等价）。"
        "⚠ blender_efx/es3d_preview.py 目前是第三种读法（前一半当尺寸），三处待统一。",
        ("minmax", "offset_size"), "minmax",
    ),
    "ribbon_trail_source": (
        "条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE）沿谁的轨迹画。"
        "annotations 原话是「沿**发射器**实际划过的轨迹」，但带 VELOCITY3D 的条带"
        "粒子显然各画各的。'auto'=粒子动过就用粒子的、否则退回发射器的，"
        "两种用法都能覆盖；另两个值可强制。",
        ("auto", "particle", "emitter"), "auto",
    ),
    "rot_order_applied": (
        "欧拉角按 rotationOrder 依次旋转时，是「顺序串里先写的先作用于向量」"
        "（'forward'）还是相反（'reverse'）。VELOCITY3D 和 EMITTERSHAPE3D 共用此开关"
        "（两者的**取值→顺序映射表**不同，但「先写的先作用」这个约定应当一致）。",
        ("forward", "reverse"), "forward",
    ),
}


class SimConfig(object):
    """一次模拟的全部可调项。默认值 = 当前最佳猜测。"""

    __slots__ = (
        "fps", "seed",
        "jitter_mode", "a0_sample", "timl_mode", "timl_interp",
        "life_model", "age_during_delay", "es3d_range_mode",
        "rot_order_applied", "ribbon_trail_source", "t3d_apply_base",
        "stage_order", "render_stage_order", "order_override", "disabled",
        "max_particles_hard", "max_frames", "max_spawn_depth", "trail_max",
        "strict",
    )

    def __init__(self, **kw):
        # ── 时基 ─────────────────────────────────────────────────────────────
        self.fps = 60                       # EFX 的帧 = 1/60 秒
        self.seed = 0                       # 基础种子；换它 = 换一次随机形态

        # ── 未确认语义的开关（见 UNKNOWNS）──────────────────────────────────
        self.jitter_mode = JITTER_ONESIDED
        self.a0_sample = "spawn"
        self.timl_mode = "replace"
        self.timl_interp = "native"
        self.life_model = "sum"
        self.age_during_delay = False
        self.es3d_range_mode = "minmax"
        self.rot_order_applied = "forward"
        self.ribbon_trail_source = "auto"

        # ── 宿主分工（不是待标定项，是集成选择）────────────────────────────
        # False = TRANSFORM3D 的静态 translate/rotate/resize 由**宿主**负责摆位
        #         （Blender 里 transform_sync.py 已经摆了，再套一次会双份位移）；
        #         模拟层只贡献漂移（translation_velocity 那组）。
        # True  = 脱离宿主单独跑时，让模拟层自己套上静态变换。
        self.t3d_apply_base = False

        # ── 阶段顺序（数据不是代码；UI 可拖动重排）──────────────────────────
        self.stage_order = list(_stages.DEFAULT_STAGE_ORDER)
        self.render_stage_order = list(_stages.DEFAULT_RENDER_STAGE_ORDER)
        #: type_hash → (stage, order)，逐属性覆盖默认排位
        self.order_override = {}
        #: 要跳过的 type_hash 集合（UI 上的逐项开关，用来「关掉这条看看差别」）
        self.disabled = set()

        # ── 安全阀 ───────────────────────────────────────────────────────────
        self.max_particles_hard = 20000     # 硬上限，防未知语义导致的爆炸
        self.max_frames = 100000            # indefiniteLifespan 的兜底
        self.max_spawn_depth = 4            # Action 递归上限（validate.py 查过 Action loop）
        self.trail_max = 64                 # 逐粒子位置历史的最大帧数（条带类渲染体用）

        # ── 开发期 ───────────────────────────────────────────────────────────
        self.strict = False                 # 逐调用校验 behavior 没越阶段写字段

        for k, v in kw.items():
            if k not in self.__slots__:
                raise TypeError("SimConfig 没有 %r 这个选项" % k)
            setattr(self, k, v)

    def copy(self):
        out = SimConfig()
        for k in self.__slots__:
            v = getattr(self, k)
            if isinstance(v, list):
                v = list(v)
            elif isinstance(v, dict):
                v = dict(v)
            elif isinstance(v, set):
                v = set(v)
            setattr(out, k, v)
        return out

    def __repr__(self):
        return ("<SimConfig fps=%d seed=%d jitter=%s a0=%s timl=%s strict=%s>"
                % (self.fps, self.seed, self.jitter_mode, self.a0_sample,
                   self.timl_mode, self.strict))
