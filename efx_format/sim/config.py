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
    "t3d_velocity_unit": (
        "TRANSFORM3D 三组速度（translation/rotation/scale_velocity）的单位。"
        "'per_second'=每秒这么多、逐帧推进 v/fps（默认）；'per_frame'=每帧这么多"
        "（改动前的行为）。语料里启用了速度位的 8158 个块：旋转 |值| 中位 90/90% 500/"
        "最大 5000 度，平移中位 150/90% 1500/最大 12000 游戏单位，缩放中位 1.0/最大 40"
        "——按每帧读分别是每秒 83 圈、900 m/s、一秒放大 60 倍，全都荒谬。"
        "⚠ `_modifier`（加速度）不受此开关影响，它是逐帧乘一次的衰减率。",
        ("per_second", "per_frame"), "per_second",
    ),
    "spawn_interval_jitter": (
        "SPAWN.burstIntervalJitter 的重抽粒度。'per_burst'=每一批都重新抽一次间隔"
        "（默认，与同为发射器层的 particlesPerBurstJitter 一致），一串粒子的间距参差不齐；"
        "'per_cycle'=一轮只抽一次，整轮等距（改动前的行为）。",
        ("per_burst", "per_cycle"), "per_burst",
    ),
    "spawn_after_cycle": (
        "有限轮次（burstsPerCycle 与 emitterRepeatCount 都非 0）的那些批次发完之后。"
        "'stop'=不再发（默认）；'recycle'=等一个粒子寿命后换位置、重抽、再开一轮"
        "（改动前的行为）。两个「无限」态（任一为 0）不受此开关影响。",
        ("stop", "recycle"), "stop",
    ),
    "rotateanim_billboard_axis": (
        "ROTATEANIM 的自旋速度怎么作用在 BILLBOARD3D 上。'view'=只取朝向相机那根轴的"
        "分量当屏幕自转（默认；正方形 billboard 上自旋 X 与平面旋转等同、Y/Z 无反应，"
        "因为 billboard 每帧都被摆正朝向相机）；'z'=只认 Z 轴（改动前的行为）。"
        "PLANE/MESH 这些真 3D 渲染体不受影响，照旧吃完整的三轴自旋。",
        ("view", "z"), "view",
    ),
    "scaleanim_add_target": (
        "SCALEANIM 的速度加在哪。'size'=加在同名的尺寸字段上——SizeScalarAdd(整体那组)"
        "加 BILLBOARD3D.scale、SizeXAdd/YAdd(逐轴那组)加 width/height（默认；官方通道名"
        "就叫 …Add，且能解释两组速度为什么量级差很远：同为 -0.1，加在 width=1 上 10 帧"
        "缩没、加在 scale=30 上要 300 帧）；'multiplier'=都加进一个从 1 起的归一化倍率"
        "（改动前的行为）。⚠ 只有 BILLBOARD3D 走 'size'，其余渲染体仍读归一化倍率。",
        ("size", "multiplier"), "size",
    ),
    "t3d_rotation_sign": (
        "TRANSFORM3D 的 rotation_velocity 往哪边转。'flip'=与字面符号相反（默认；"
        "用户实机：`05 spell` 那圈符文是逆时针生成的，照字面符号转出来是顺时针）；"
        "'raw'=照字面符号。",
        ("flip", "raw"), "flip",
    ),
    "rgb_tint_mode": (
        "RGBFIRE / RGBWATER 的两层颜色怎么压成粒子的单一颜色。'weighted'=各按自己的"
        "强度×生命期权重加权平均（默认；火焰用 brightness1、高光/水膜用 "
        "intensitySpecular/intensitySheet）；'mix'=等权平均；'first'=只取 fireColor/"
        "colorSpecular；'second'=只取 smokeColor/colorSheet。"
        "⚠ 实机是外缘/内部两层按贴图分布的，压成一个颜色是当前渲染链的限制，"
        "两个颜色本身都留在 p.rolled 里。",
        ("weighted", "mix", "first", "second"), "weighted",
    ),
    "uvc_clock": (
        "UVCONTROL 的 UV 动画按哪个时钟走。'particle_age'=每个粒子从自己出生起算"
        "（默认，与 UVSEQUENCE 一致）；'emitter_frame'=发射器时间轴，全体同步。",
        ("particle_age", "emitter_frame"), "particle_age",
    ),
    "es3d_range_mode": (
        "EMITTERSHAPE3D.rangeXYZ 这一对的含义。'shell'=前一半是**偏移（内边界）**、"
        "后一半是**尺寸（向外延伸的厚度）**，外边界=偏移+尺寸，三种形状通用（默认，"
        "与作者教程《生成方式》一致）；'minmax'=前一半 Min、后一半 Max（RE DTI dump 的"
        "官方名 RangeMinX/RangeMaxX 是这个读法，但与实机行为对不上，留作对照）。"
        "⚠ blender_efx/es3d_preview.py 是第三种读法（前一半当尺寸），用户已决定搁置不改。",
        ("shell", "minmax"), "shell",
    ),
    "ribbon_trail_source": (
        "条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE）沿谁的轨迹画。"
        "annotations 原话是「沿**发射器**实际划过的轨迹」，但带 VELOCITY3D 的条带"
        "粒子显然各画各的。'auto'=粒子动过就用粒子的、否则退回发射器的，"
        "两种用法都能覆盖；另两个值可强制。",
        ("auto", "particle", "emitter"), "auto",
    ),
    "color_range_mode": (
        "color 与 colorRange 怎么组成一个颜色。'channel'=逐通道（含 alpha）各自独立在"
        "两者之间抽（默认）；'shared'=整条通道共用一个系数插值（改动前的行为）；"
        "'add'=把 colorRange 当加法随机量 color+随机[0,range]——语料里 BILLBOARD3D 只有"
        "6.1%、RIBBON 0.9% 的块满足 color+range≤255，故不作默认。",
        ("channel", "shared", "add"), "channel",
    ),
    "parent_release_clock": (
        "PARENTOPTIONS.constRelease（停止追踪帧数）数的是哪个时钟："
        "'particle_age'=每个粒子出生后各自数（默认——这个字段自带 Jitter，逐粒子抽"
        "才用得上抖动）；'emitter_frame'=发射器时间轴，到点全体一起锁定。",
        ("particle_age", "emitter_frame"), "particle_age",
    ),
    "ribbon_length_mode": (
        "RIBBON 轨迹跟随的总长怎么来。'per_segment'=length × (细分数-1)，一段一个 "
        "length（默认；用户实测长度跟着细分数走，且语料里 mode 0 的 length 59% 留在"
        "默认 100 不动、变化的是 subdiv）；'total'=length 就是总长（改动前的行为）。"
        "还有第三种可能没实现：每段存一帧历史，那样长度会随运动速度变——要改 "
        "p.trail 的记录长度才能做，等实测分清了再说。",
        ("per_segment", "total"), "per_segment",
    ),
    "uvs_speed_unit": (
        "UVSEQUENCE.playSpeed 的单位：'per_frame'=每帧推进这么多格，"
        "'per_second'=每秒推进这么多格。默认 per_frame——语料取值 0~10、众数 1.0，"
        "而 playSpeed==0 与 playbackMode==0（只显示起始帧）完全对齐"
        "（pm=0 的 17888 个块无一例外是 0），说明它就是推进速率。",
        ("per_frame", "per_second"), "per_frame",
    ),
    "uvs_once_span": (
        "「播放一次」（playbackMode 2 消亡 / 3 定格）算几格："
        "'to_end'=从起始帧走到序列末尾，'full_cycle'=不论起点都走满整序列。",
        ("to_end", "full_cycle"), "to_end",
    ),
    "uvs_start_wrap": (
        "起始帧（patternNo + 抖动）超出帧数时回绕还是夹取。语料里 "
        "patternNoJitter=63 极常见，真实帧数未知，两种都说得通。",
        ("wrap", "clamp"), "wrap",
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
        "ribbon_length_mode", "parent_release_clock", "color_range_mode",
        "t3d_velocity_unit", "spawn_interval_jitter", "spawn_after_cycle",
        "rotateanim_billboard_axis", "scaleanim_add_target",
        "t3d_rotation_sign", "rgb_tint_mode", "uvc_clock",
        "uvs_speed_unit", "uvs_once_span", "uvs_start_wrap",
        "uvs_grid_h", "uvs_grid_v", "uvs_grid_scan",
        "rot_order_applied", "ribbon_trail_source", "t3d_apply_base",
        "stage_order", "render_stage_order", "order_override", "disabled",
        "max_particles_hard", "max_frames", "max_spawn_depth", "trail_max",
        "max_instances", "max_particles_total", "child_cull_grace",
        "child_pending_grace",
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
        self.ribbon_trail_source = "auto"
        self.ribbon_length_mode = "per_segment"
        self.parent_release_clock = "particle_age"
        self.color_range_mode = "channel"
        self.t3d_velocity_unit = "per_second"
        self.spawn_interval_jitter = "per_burst"
        self.spawn_after_cycle = "stop"
        self.rotateanim_billboard_axis = "view"
        self.scaleanim_add_target = "size"
        self.t3d_rotation_sign = "flip"
        self.rgb_tint_mode = "weighted"
        self.uvc_clock = "particle_age"
        self.uvs_speed_unit = "per_frame"
        self.uvs_once_span = "to_end"
        self.uvs_start_wrap = "wrap"

        # 没有载入 .uvs 时的网格兜底（不是待标定语义，是「猜一张图」的参数）。
        # 8×8=64 依据全语料 patternNoJitter==63 占 33.6%，见 uvs_table.grid_table。
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

        # ── 安全阀 ───────────────────────────────────────────────────────────
        self.max_particles_hard = 20000     # 硬上限，防未知语义导致的爆炸
        self.max_frames = 100000            # indefiniteLifespan 的兜底
        self.max_spawn_depth = 4            # Action 递归上限（validate.py 查过 Action loop）
        # PTLIFE → ACTION 的实例树闸门（见 sim/scene.py）。「每个粒子生一棵子树」
        # 不设上限必然挂死，所以这三个是安全阀不是调优项。
        self.max_instances = 256            # 同时存在的实例数
        self.max_particles_total = 20000    # 全树粒子总数
        self.child_cull_grace = 30          # 生成过粒子的子实例，空转多少帧就回收
        #: 还一个粒子都没吐过的子实例能等多久。SPAWN.emitterStartDelay 可以很长，
        #: 用 child_cull_grace 那 30 帧去卡它会让子特效「完全不触发」。
        self.child_pending_grace = 600
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
