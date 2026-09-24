# -*- coding: utf-8 -*-
"""模拟参数。

这个文件的作用不是「配置」，是把所有未确认的语义收成可调开关：标定它们的方式是在
Blender 里对拍，不是改代码重装插件。

维护约束：
- `UNKNOWNS` 是未确认语义的登记表，每条对应一处必须实测才能定的行为。
- 实机标定完的开关直接退役：删掉开关与其余候选值的分支，行为写死在 behavior 里。
  标定依据与推翻过的读法写进 `docs/notes/sim_notes.md`，不留在本文件。
- 一个开关的默认值出现在三处：`UNKNOWNS`、`SimConfig.__init__`、以及
  `blender_efx/sim_preview.py` 读 Scene 属性时的兜底值。改默认值必须三处同改。
"""

from . import stages as _stages


#: 未确认语义的登记表：key → (说明, 候选值, 默认值)
UNKNOWNS = {
    "a0_sample": (
        "TIML A0（发射轴）对粒子级字段的采样点：'spawn' 在粒子出生那一帧冻结，"
        "'current' 每帧跟着发射器时间走。",
        ("spawn", "current"), "spawn",
    ),
    "timl_interp": (
        "关键帧插值。'native' 按 keyframe.transition（0=STUCK 1=CONSTANT 2=LINEAR "
        "3=QUAD 4=CUBIC），其中 QUAD/CUBIC 未验证、退化成线性；'linear'/'constant' 强制。",
        ("native", "linear", "constant"), "native",
    ),
    "age_during_delay": (
        "SPAWN.spawnWaitFrame 期间粒子的 age 是否推进（影响 TIML A1 与 LIFE）。",
        (False, True), False,
    ),
    "spawn_interval_jitter": (
        "SPAWN.intervalFrameJitter 的重抽粒度。'per_burst' 每批重抽一次间隔，"
        "一串粒子的间距参差不齐；'per_cycle' 一轮只抽一次，整轮等距。",
        ("per_burst", "per_cycle"), "per_burst",
    ),
    "spawn_after_cycle": (
        "有限轮次（loopNum 与 emitterRepeatCount 都非 0）的批次发完之后。"
        "'stop' 不再发；'recycle' 等一个粒子寿命后换位置、重抽、再开一轮。"
        "两个无限态（任一为 0）不受此开关影响。",
        ("stop", "recycle"), "stop",
    ),
    "rotateanim_billboard_axis": (
        "ROTATEANIM 的自旋速度怎么作用在 BILLBOARD3D 上。'view' 只取朝向相机那根轴的"
        "分量当屏幕自转；'z' 只认 Z 轴。PLANE/MESH 等真 3D 渲染体不受影响，"
        "照旧吃完整的三轴自旋。",
        ("view", "z"), "view",
    ),
    "blink_phase": (
        "BLINK 两重正弦的初相位。'zero' 以粒子出生为相位 0，同一时刻出生的粒子同步闪烁；"
        "'random' 每个粒子在出生时各自抽取初相位。",
        ("zero", "random"), "zero",
    ),
    "uvc_clock": (
        "UVCONTROL 的 UV 动画按哪个时钟走。'particle_age' 每个粒子从自己出生起算"
        "（与 UVSEQUENCE 一致）；'emitter_frame' 发射器时间轴，全体同步。",
        ("particle_age", "emitter_frame"), "particle_age",
    ),
    "ribbon_trail_source": (
        "条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE）沿谁的轨迹画。"
        "'auto' 粒子动过就用粒子的、否则退回发射器的；另两个值强制指定。",
        ("auto", "particle", "emitter"), "auto",
    ),
    "ribbon_gravity_scale": (
        "RIBBON 柔体链的重力（gravityX/Y/Z）换算成每帧加到链节点速度上的量时乘的倍率。"
        "方向与开关已确认，量纲未实测。",
        (0.0, 4.0), 1.0,
    ),
    "ribbon_trail_time_frames": (
        "RIBBON 轨迹跟随开启 useTrailTimeScale 后，trailTimeScale = 1 时每段覆盖的帧数；"
        "总时长 = (细分数 − 1) × 该值 × trailTimeScale。已确认按时间计、与细分数相乘，"
        "比例常数按「值为 1 时约相当于细分数 60」估算，未精测。",
        (0.1, 2.0), 0.42,
    ),
    "parent_release_clock": (
        "PARENTOPTIONS.constRelease（停止追踪帧数）数的是哪个时钟。"
        "'particle_age' 每个粒子出生后各自数——这个字段自带 Jitter，逐粒子抽才用得上；"
        "'emitter_frame' 发射器时间轴，到点全体一起锁定。",
        ("particle_age", "emitter_frame"), "particle_age",
    ),
    "uvs_speed_unit": (
        "UVSEQUENCE.playSpeed 的单位：'per_frame' 每帧推进这么多格，"
        "'per_second' 每秒推进这么多格。",
        ("per_frame", "per_second"), "per_frame",
    ),
    "uvs_once_span": (
        "「播放一次」（playbackMode 2 消亡 / 3 定格）算几格："
        "'to_end' 从起始帧走到序列末尾，'full_cycle' 不论起点都走满整序列。",
        ("to_end", "full_cycle"), "to_end",
    ),
    "uvs_start_wrap": (
        "起始帧（patternNo 加抖动）超出帧数时回绕还是夹取。",
        ("wrap", "clamp"), "wrap",
    ),
    "rot_order_applied": (
        "欧拉角按 rotationOrder 依次旋转时，是顺序串里先写的先作用于向量"
        "（'forward'）还是相反（'reverse'）。VELOCITY3D 与 EMITTERSHAPE3D 共用此开关："
        "两者的取值→顺序映射表不同，但「先写的先作用」这个约定应当一致。",
        ("forward", "reverse"), "forward",
    ),
    "homing_orbit_lateral_tilt": (
        "侧向方向 n 随纬度倾斜多少：n = cos(φ)·e + sin(φ)·b，φ = tilt·(d·世界Y)。"
        "φ 取 d·Y 这个奇标量，使 n 对 d→-d 为奇，整团因此没有净漂移。"
        "tilt 只控制竖直压扁程度：0 时半周期压成纯平面，越大越立体。"
        "⚠ 具体倾斜量未实测。",
        (0.0, 2.0), 0.0,
    ),
    "fade_depth_metric": (
        "FADEBYDEPTH 的距离怎么量。'view_depth' 为视线方向上的深度；"
        "'distance' 为粒子到相机的直线距离。",
        ("view_depth", "distance"), "view_depth",
    ),
    "fade_cone_mode": (
        "FADEBYANGLE.fadeConeAngle 的读法。'outer' 为过渡区外边界的绝对锥角；"
        "'width' 为从 cutoffConeAngle 起算的过渡宽度。"
        "语料中约三分之一的块 fadeConeAngle 小于 cutoffConeAngle，'outer' 下这些块没有过渡区。",
        ("outer", "width"), "outer",
    ),
}


class SimConfig(object):
    """一次模拟的全部可调项。默认值 = 当前最佳猜测。"""

    __slots__ = (
        "fps", "seed",
        "a0_sample", "timl_interp",
        "age_during_delay", "parent_release_clock",
        "spawn_interval_jitter", "spawn_after_cycle",
        "rotateanim_billboard_axis", "uvc_clock",
        "uvs_speed_unit", "uvs_once_span", "uvs_start_wrap",
        "uvs_grid_h", "uvs_grid_v", "uvs_grid_scan",
        "blink_phase",
        "rot_order_applied", "ribbon_trail_source", "t3d_apply_base",
        "homing_ff_recover_frames",
        "homing_orbit_lateral_tilt", "fade_depth_metric", "fade_cone_mode",
        "stage_order", "render_stage_order", "order_override", "disabled",
        "max_particles_hard", "max_frames", "max_spawn_depth", "trail_max",
        "max_instances", "max_particles_total", "child_cull_grace",
        "child_pending_grace",
        "ribbon_subdiv_max", "ribbon_gravity_scale", "ribbon_trail_time_frames",
        "strict",
    )

    def __init__(self, **kw):
        # ── 时基 ─────────────────────────────────────────────────────────────
        self.fps = 60                       # EFX 的帧 = 1/60 秒
        self.seed = 0                       # 基础种子；换它 = 换一次随机形态

        # ── 未确认语义的开关（见 UNKNOWNS）──────────────────────────────────
        self.a0_sample = "spawn"
        self.timl_interp = "native"
        self.age_during_delay = False
        self.rot_order_applied = "forward"
        self.homing_ff_recover_frames = 48.0
        self.homing_orbit_lateral_tilt = 0.0
        self.ribbon_trail_source = "auto"
        self.ribbon_gravity_scale = 1.0
        self.ribbon_trail_time_frames = 0.42
        self.parent_release_clock = "particle_age"
        self.spawn_interval_jitter = "per_burst"
        self.spawn_after_cycle = "stop"
        self.rotateanim_billboard_axis = "view"
        self.uvc_clock = "particle_age"
        self.blink_phase = "zero"
        self.uvs_speed_unit = "per_frame"
        self.uvs_once_span = "to_end"
        self.uvs_start_wrap = "wrap"
        self.fade_depth_metric = "view_depth"
        self.fade_cone_mode = "outer"

        # 没有载入 .uvs 时的网格兜底；不是待标定语义，是「猜一张图」的参数。
        self.uvs_grid_h = 8
        self.uvs_grid_v = 8
        self.uvs_grid_scan = "LR_TB"

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

        # ── 预览降载（LOD）──────────────────────────────────────────────────
        #: 条带沿长度方向的重采样点数上限。0 = 照文件里的 subdivisionCount 来。
        #: 一条 50 细分的条带每帧出 294 个顶点，PtLife 子树里同时活着上千条就是
        #: 三十多万顶点全在 Python 侧装配；降到十几段形状基本还在，开销少一大截。
        #: ⚠ 这是**预览**参数，不改文件、不改导出，只影响画面精细度。
        self.ribbon_subdiv_max = 0

        # ── 安全阀 ───────────────────────────────────────────────────────────
        self.max_particles_hard = 20000     # 硬上限，防未知语义导致的爆炸
        self.max_frames = 100000            # indefiniteLifespan 的兜底
        self.max_spawn_depth = 4            # Action 递归上限（validate.py 查过 Action loop）
        # PTLIFE → ACTION 的实例树闸门（见 sim/scene.py）。「每个粒子生一棵子树」
        # 不设上限必然挂死，所以这三个是安全阀不是调优项。
        self.max_instances = 256            # 同时存在的实例数
        self.max_particles_total = 20000    # 全树粒子总数
        self.child_cull_grace = 30          # 生成过粒子的子实例，空转多少帧就回收
        #: 还一个粒子都没吐过的子实例能等多久。SPAWN.emitterDelayFrame 可以很长，
        #: 用 child_cull_grace 那 30 帧去卡它会让子特效「完全不触发」。
        self.child_pending_grace = 600
        #: 逐粒子位置历史的最大帧数（条带类渲染体用）；behavior 可按需声明更长，见 EmitterState.trail_need
        self.trail_max = 64

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
        return ("<SimConfig fps=%d seed=%d a0=%s strict=%s>"
                % (self.fps, self.seed, self.a0_sample, self.strict))
