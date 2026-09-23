# -*- coding: utf-8 -*-
"""模拟参数。

这个文件的作用不是「配置」，是把所有未确认的语义收成可调开关：标定它们的方式是在
Blender 里对拍，不是改代码重装插件。

维护约束：
- `UNKNOWNS` 是未确认语义的登记表，每条对应一处必须实测才能定的行为。
- 标定完一条就改掉默认值，并把该条从 `UNKNOWNS` 移走；开关本身保留作对照。
  标定依据与推翻过的读法写进 `docs/notes/sim_notes.md`，不留在本文件。
- 一个开关的默认值出现在三处：`UNKNOWNS`、`SimConfig.__init__`、以及
  `blender_efx/sim_preview.py` 读 Scene 属性时的兜底值。改默认值必须三处同改。
"""

from . import stages as _stages
from .rng import JITTER_ONESIDED


#: 未确认语义的登记表：key → (说明, 候选值, 默认值)
UNKNOWNS = {
    "jitter_mode": (
        "抖动分布。已确认是在 static 基础上追加 [0, amount] 的单边加法，"
        "具体取值分布未确认。",
        ("onesided", "symmetric", "gaussian"), "onesided",
    ),
    "a0_sample": (
        "TIML A0（发射轴）对粒子级字段的采样点：'spawn' 在粒子出生那一帧冻结，"
        "'current' 每帧跟着发射器时间走。",
        ("spawn", "current"), "spawn",
    ),
    "timl_mode": (
        "TIML 关键帧值是替换静态字段还是乘上去。"
        "timl_tracks.py 新增轨道时用静态字段值做首帧 seed，"
        "只有 replace 语义下「加一条轨道不改变外观」才成立。",
        ("replace", "multiply"), "replace",
    ),
    "timl_interp": (
        "关键帧插值。'native' 按 keyframe.transition（0=STUCK 1=CONSTANT 2=LINEAR "
        "3=QUAD 4=CUBIC），其中 QUAD/CUBIC 未验证、退化成线性；'linear'/'constant' 强制。",
        ("native", "linear", "constant"), "native",
    ),
    "life_model": (
        "LIFE 的总寿命怎么算。'sum' 为 fadeIn+duration+fadeOut；"
        "'duration' 为 duration 即总长、淡入淡出包含在内。",
        ("sum", "duration"), "sum",
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
    "scaleanim_add_target": (
        "SCALEANIM 的速度加在哪。'size' 加在同名的尺寸字段上——SizeScalarAdd 加"
        "scale，SizeXAdd/YAdd 加 width/height；'multiplier' 加进一个从 1 "
        "起的归一化倍率。⚠ 只有 BILLBOARD3D / PLANE 走 'size'，MESH / RIBBON 仍读归一化倍率。",
        ("size", "multiplier"), "size",
    ),
    "rgb_tint_mode": (
        "RGBFIRE / RGBWATER 的两层颜色怎么压成粒子的单一颜色。'weighted' 各按自己的"
        "强度与生命期权重加权平均；'mix' 等权平均；'first' 只取 fireColor/colorSpecular；"
        "'second' 只取 smokeColor/colorSheet。"
        "⚠ 压成一个颜色是当前渲染链的限制，两个颜色本身都留在 p.rolled 里。",
        ("weighted", "mix", "first", "second"), "weighted",
    ),
    "flowmap_speed_unit": (
        "flowmapSpeed 的单位。'per_second' 每秒推进这么多相位、逐帧走 speed/fps；"
        "'per_frame' 每帧这么多。"
        "⚠ 两个 Coef 不受此开关影响，它们恒是逐帧乘一次的衰减率。",
        ("per_second", "per_frame"), "per_second",
    ),
    "flowmap_phase": (
        "flowmap 的相位怎么映射成 UV 位移。'cycle' 取相位的小数部分映到 −1..1，"
        "位移有界；'linear' 一路累积，相位即位移倍数。",
        ("cycle", "linear"), "cycle",
    ),
    "oscillator_freq_unit": (
        "NOISE 与 BLINK 共用的双重正弦振荡器中，LowFrequency / HighFrequency 的单位。"
        "'hz' 为每秒周期数；'rad_per_second' 为每秒弧度；'rad_per_frame' 为每帧弧度。"
        "可用 BLINK（lowFrequency=1、lowFrequencyWidth=1、minRate=0、maxRate=1）实机计数"
        "10 秒内的闪烁次数判定：约 10 次为 'hz'，约 1.6 次为 'rad_per_second'，"
        "逐帧频闪为 'rad_per_frame'。",
        ("hz", "rad_per_second", "rad_per_frame"), "hz",
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
    "color_range_mode": (
        "color 与 colorRange 怎么组成一个颜色。'channel' 逐通道（含 alpha）各自独立在"
        "两者之间抽；'shared' 整条通道共用一个系数插值；"
        "'add' 把 colorRange 当加法随机量 color+随机[0,range]。",
        ("channel", "shared", "add"), "channel",
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
    "homing_compose": (
        "HOMING 怎么驱动粒子，也决定它与 VELOCITY3D 等其它速度来源怎么共存。"
        "'pursuit' 是纯追踪：速度方向每帧朝「指向目标」转 turnRate/fps、"
        "大小由自己的 initialSpeed→targetSpeed 决定。"
        "'add' 把 HOMING 的指令速度加在自由速度之上；'override' 直接覆盖总速度。"
        "⚠ 切到 'add'/'override' 会退回两段状态机，"
        "homing_orbit_axis_update 与 homing_orbit_lateral_tilt 只对它们有意义——"
        "纯追踪每帧按当前几何重算转向，不存在「冻结的轴」这回事。",
        ("pursuit", "add", "override"), "pursuit",
    ),
    "homing_orbit_axis": (
        "orbit 段（仅 'add'/'override' 下存在）的转轴怎么构造。"
        "'lateral_tilt' 逐粒子按来向定侧向方向，使整团无净漂移；"
        "'offset_up' / 'world_up' / 'world_front' 保留作对照，均带已知缺陷"
        "（固定轴只能触及两维，per-粒子偶函数轴会让整团往一侧漂）。"
        "真正的轴是什么仍未确认。",
        ("lateral_tilt", "offset_up", "world_up", "world_front"), "lateral_tilt",
    ),
    "homing_orbit_axis_update": (
        "orbit 段的转轴是冻结还是每帧重算。'frozen' 绕到达那一刻定下的轴转到底；"
        "'live' 每帧按当前速度方向重算，即把侧向力当成一个场而不是一根冻结的轴。"
        "两者在纯水平运动下完全一致；速度一旦有 Y 分量，'live' 会让轨道平面进动。"
        "⚠ 进动幅度是 homing_orbit_lateral_tilt 的陡峭函数。",
        ("frozen", "live"), "frozen",
    ),
    "homing_orbit_lateral_tilt": (
        "侧向方向 n 随纬度倾斜多少：n = cos(φ)·e + sin(φ)·b，φ = tilt·(d·世界Y)。"
        "φ 取 d·Y 这个奇标量，使 n 对 d→-d 为奇，整团因此没有净漂移。"
        "tilt 只控制竖直压扁程度：0 时半周期压成纯平面，越大越立体。"
        "⚠ 具体倾斜量未实测。",
        (0.0, 2.0), 1.0,
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
        "jitter_mode", "a0_sample", "timl_mode", "timl_interp",
        "life_model", "age_during_delay", "es3d_range_mode",
        "ribbon_length_mode", "parent_release_clock", "color_range_mode",
        "t3d_velocity_unit", "spawn_interval_jitter", "spawn_after_cycle",
        "rotateanim_billboard_axis", "scaleanim_add_target",
        "t3d_rotation_sign", "rgb_tint_mode", "uvc_clock",
        "uvs_speed_unit", "uvs_once_span", "uvs_start_wrap",
        "uvs_grid_h", "uvs_grid_v", "uvs_grid_scan",
        "flowmap_speed_unit", "flowmap_phase",
        "oscillator_freq_unit", "blink_phase",
        "rot_order_applied", "ribbon_trail_source", "t3d_apply_base",
        "homing_speed_converge", "homing_speed_ramp_turns", "homing_ff_scale_mode",
        "homing_ff_recover_frames",
        "homing_compose", "homing_orbit_axis",
        "homing_orbit_axial_falloff", "homing_orbit_handed",
        "homing_orbit_lateral_tilt", "homing_orbit_axis_update",
        "homing_orbit_retarget", "ribbon_rigid_dir",
        "fade_depth_metric", "fade_cone_mode",
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
        self.jitter_mode = JITTER_ONESIDED
        self.a0_sample = "spawn"
        self.timl_mode = "replace"
        self.timl_interp = "native"
        self.life_model = "sum"
        self.age_during_delay = False
        self.es3d_range_mode = "shell"
        self.rot_order_applied = "forward"
        self.homing_speed_converge = "linear"
        self.homing_speed_ramp_turns = 4.0
        self.homing_ff_scale_mode = "balanced"
        self.homing_ff_recover_frames = 48.0
        self.homing_compose = "pursuit"
        self.homing_orbit_axis = "lateral_tilt"
        self.homing_orbit_lateral_tilt = 0.0
        self.homing_orbit_axis_update = "frozen"
        self.homing_orbit_axial_falloff = 0.0
        self.homing_orbit_handed = "fixed"
        self.homing_orbit_retarget = "once"
        self.ribbon_trail_source = "auto"
        self.ribbon_length_mode = "frames"
        self.ribbon_rigid_dir = "parent"
        self.ribbon_gravity_scale = 1.0
        self.ribbon_trail_time_frames = 0.42
        self.parent_release_clock = "particle_age"
        self.color_range_mode = "channel"
        self.t3d_velocity_unit = "per_second"
        self.spawn_interval_jitter = "per_burst"
        self.spawn_after_cycle = "stop"
        self.rotateanim_billboard_axis = "view"
        self.scaleanim_add_target = "size"
        self.t3d_rotation_sign = "raw"
        self.rgb_tint_mode = "weighted"
        self.uvc_clock = "particle_age"
        self.flowmap_speed_unit = "per_second"
        self.flowmap_phase = "cycle"
        self.oscillator_freq_unit = "hz"
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
        return ("<SimConfig fps=%d seed=%d jitter=%s a0=%s timl=%s strict=%s>"
                % (self.fps, self.seed, self.jitter_mode, self.a0_sample,
                   self.timl_mode, self.strict))
