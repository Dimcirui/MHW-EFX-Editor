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
    # "t3d_velocity_unit" 已标定，降级成注释（保留开关，不再是待办）：TRANSFORM3D
    # 三组速度（translation/rotation/scale_velocity）的单位是 per_second——每秒
    # 这么多、逐帧推进 v/fps。语料里启用了速度位的 8158 个块：旋转 |值| 中位
    # 90/90% 500/最大 5000 度，平移中位 150/90% 1500/最大 12000 游戏单位，缩放
    # 中位 1.0/最大 40——按 per_frame 读分别是每秒 83 圈、900 m/s、一秒放大 60
    # 倍，全都荒谬，故排除。`_modifier`（加速度）不受此影响，恒是逐帧乘一次的
    # 衰减率。UI 已从 Calibration 面板移除，Scene 属性 efx_sim_t3d_vel_unit 仍
    # 保留（默认 per_second）。
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
    "flowmap_speed_unit": (
        "flowmapSpeed 的单位。'per_second'=每秒推进这么多相位、逐帧走 speed/fps"
        "（默认，与 t3d_velocity_unit / uvs_speed_unit 同一结论）；'per_frame'=每帧"
        "这么多。众数 1.0：按每秒读是一秒走完一轮，按每帧读是一秒走 60 轮。"
        "⚠ 两个 Coef 不受此开关影响，它们恒是**逐帧**乘一次的衰减率。",
        ("per_second", "per_frame"), "per_second",
    ),
    "flowmap_phase": (
        "flowmap 的相位怎么映射成 UV 位移。'cycle'=取相位的小数部分映到 −1..1"
        "（默认；位移有界，粒子活多久都不会越拉越烂）；'linear'=一路累积"
        "（相位就是位移倍数，短寿命粒子上更像「被吹走」）。",
        ("cycle", "linear"), "cycle",
    ),
    "uvc_clock": (
        "UVCONTROL 的 UV 动画按哪个时钟走。'particle_age'=每个粒子从自己出生起算"
        "（默认，与 UVSEQUENCE 一致）；'emitter_frame'=发射器时间轴，全体同步。",
        ("particle_age", "emitter_frame"), "particle_age",
    ),
    # "es3d_range_mode" 已标定，降级成注释（保留开关，不再是待办）：
    # EMITTERSHAPE3D.rangeXYZ 这一对读作 shell——前一半是偏移（内边界）、后一半是
    # 尺寸（向外延伸的厚度），外边界=偏移+尺寸，三种形状通用，与作者教程《生成
    # 方式》一致。候选的 minmax 读法（前一半 Min、后一半 Max，RE DTI dump 的官方名
    # RangeMinX/RangeMaxX 像这个读法）与实机行为对不上，已排除，只留作对照。
    # 曾经还有第三种读法：Blender 侧那个 GN「形状预览」会话把前一半当尺寸。该会话
    # 0.7.1 已退休，生成区域统一由 blender_efx/es3d_overlay.py 画，与采样器同源，
    # 三种读法并存的局面到此结束。UI 已从 Calibration 面板移除，Scene 属性
    # efx_sim_es3d_range 仍保留（默认 shell）。
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
    # "homing_speed_converge" 已标定/已废，降级成注释（开关保留，不再是待办）：已标定：等距螺旋 ⇒ 线性爬升（每帧加固定增量，按原始差值算）。指数逼近给出「起手半径大、间距逐圈递减」，与实拍正好相反，已排除。
    # "homing_speed_converge": (
    #     "HOMING 的速度从 initialSpeed 逼近 targetSpeed 的曲线。轨道半径 r=v/ω，"
    #     "所以这条曲线直接决定螺旋的形状。"
    #     "'linear'（默认）=每帧加固定增量（原始差值 / 爬升圈数），半径随时间线性增长"
    #     "⇒ **等距螺旋**，每圈径向增量恒定、起手半径很小；"
    #     "'per_revolution'=每圈收掉当前**剩余**差值的 (1-e⁻¹)，即指数逼近 ⇒ 间距逐圈"
    #     "变小、起手半径很大；'instant'=下一帧直接跳到 targetSpeed（螺旋消失，仅对照）。"
    #     "2026-09-12 用户拿 initialSpeed=0.1 的游戏实拍标定：实机是**等距螺旋、起手"
    #     "半径很小**，指数逼近给出的形状正好相反，故改默认为 'linear'。两者的总圈数"
    #     "都是 ~4 圈，所以当时错的是曲线形状而不是时长。",
    #     ("linear", "per_revolution", "instant"), "linear",
    # ),
    # "homing_speed_ramp_turns" 已标定/已废，降级成注释（开关保留，不再是待办）：已标定：4 圈。0.1→1.0 与 0.5→1.0 都是 4 圈，差值减半而圈数不变 ⇒ 固定圈数而非固定加速度。
    # "homing_speed_ramp_turns": (
    #     "'linear' 收敛用：速度**升高**（initialSpeed < targetSpeed）时爬完全程要转"
    #     "几圈。2026-09-12 用户实拍标定：0.1→1.0 与 0.5→1.0 **都是 4 圈**，差值减半"
    #     "圈数不变 ⇒ 是「固定圈数」而不是「固定加速度」（后者差值减半应当只要 2 圈）。"
    #     "故默认 4.0。",
    #     (0.5, 16.0), 4.0,
    # ),
    # "homing_ff_scale_mode" 已标定/已废，降级成注释（开关保留，不再是待办）：已标定：'balanced'（每帧先乘 k、再加固定绝对增量回拉）。扫 k=0.99/0.95/0.9/0.8/0.5 量直径得 24:8:4:2:1；'output' 给出正比于 k 的1.98:1.9:1.8:1.6:1，'per_frame' 让粒子冻死，两者均已排除。
    # "homing_ff_scale_mode": (
    #     "HOMING.forceFieldSpeedScale 怎么作用。'output'（默认）=只缩放**当帧输出**"
    #     "速度、不动内部状态 ⇒ 场内匀速行进、速度不累积衰减；'per_frame'=逐帧乘进"
    #     "内部速度状态 ⇒ 几何累积。"
    #     "2026-09-12 用户实机判定：**场内粒子一直在动，而且是匀速**；k=0.1 时也不是"
    #     "停住，而是以极慢的**恒定**速度继续运动 ⇒ 就是固定倍率，**'per_frame' 被"
    #     "证伪**（累积读法下速度按 k^n 衰减，实测会让粒子彻底停死、连 approach 都飞"
    #     "不到目标）。'per_frame' 仅留作对照。"
    #     "⚠ 由此派生一条尚未对上的预言：转速 ω 不受影响，所以场内转弯半径是 k·v/ω，"
    #     "当 **2·k·r ≤ 场半径** 时整圈塞得进场里、粒子被永久困住绕小圈（实测 k=0.8/"
    #     "场20/r=11 时半径正好 17.60=2·0.8·11）。临界 k* = R场/(2r)。但用户实拍的"
    #     "转折点在 k≈0.9~0.95，同时又报告「大环 vs 小点」的巨大反差——这两件事在本"
    #     "模型里不能同时成立（临界点在 0.9 需要 2r≈22，那样三者只差 8%）。待用户在"
    #     "固定机位下量出自由轨道直径与场直径之比后再定。",
    #     ("balanced", "output", "per_frame"), "balanced",
    # ),
    # "homing_ff_recover_frames" 已标定/已废，降级成注释（开关保留，不再是待办）：已标定：48 帧。平衡点 min(1, c/(1-k))，c=1/48；k=0.99 的 24 正是撞到 targetSpeed 上限（纯 1/(1-k) 外推会给 50）。
    # "homing_ff_recover_frames": (
    #     "'balanced' 模式的恢复速率：多少帧能把速度从 0 拉回 targetSpeed（每帧加"
    #     "固定增量 targetSpeed/该值）。场内平衡点 v* = min(targetSpeed, c/(1-k))。"
    #     "2026-09-12 由用户扫 k=0.99/0.95/0.9/0.8/0.5 的轨道直径 24:8:4:2:1 反推"
    #     "得 ≈48 帧（0.8 秒）。⚠ 这与 initialSpeed→targetSpeed 的一次性线性爬升"
    #     "（约 4 圈/960 帧）是两套独立机制，快约 20 倍。",
    #     (4.0, 600.0), 48.0,
    # ),
    "homing_compose": (
        "HOMING 到底是怎么驱动粒子的，也决定它与 VELOCITY3D 等其它速度来源怎么共存。"
        "'pursuit'（默认）=**纯追踪**：速度**方向**每帧朝「指向目标」转 turnRate/fps、"
        "大小由自己的 initialSpeed→targetSpeed 决定。approach/orbit 两段状态机与"
        "「到达那一刻硬塞一记侧向力」都是它的特例展开（详见 homing.py 的 _pursue）。"
        "'add'=HOMING 把自己的指令速度加在自由速度之上（速度分量读法）；"
        "'override'=直接覆盖总速度，其它来源零帧存活（最早的行为）。后两个留作对照。"
        "2026-09-12 定案：用户给 V3D 一个**向外**的初速度，实机是整团粒子**先向外飞"
        "并旋转**、旋转到某个角度停住，之后回归周期运动。'override' 立刻被排除"
        "（会直奔目标）；'add' 也被**定量**排除——用户那组参数 V3D 向外 1 与 HOMING "
        "向内 1 恰好抵消，相加预言原地不动，实机却在扩张。'pursuit' 三条全中："
        "初速度方向朝外 ⇒ 先向外飞；HOMING 按 turnRate 把方向扭回来 ⇒ 旋转；"
        "扭到对准目标就没得扭 ⇒ 停在一个角度。"
        "⚠ 切到 'add'/'override' 会退回那套两段状态机，"
        "homing_orbit_axis_update / homing_orbit_retarget / homing_orbit_axial_falloff "
        "只对它们有意义——纯追踪每帧都按当前几何重算转向，那几个结构性缺口本来就不存在。",
        ("pursuit", "add", "override"), "pursuit",
    ),
    "homing_orbit_axis": (
        "HOMING 到达目标后转圈用哪根轴——2026-09-12 一天内改判了两次，见 homing.py"
        "模块 docstring「转向轴」一节的完整过程，别只看这条摘要就下结论。"
        "'offset_up'（默认，第三版）=每个粒子按自己的来向单独定轴（cross(来向,世界Y)"
        "，出生时抽一个 ±1 手性抵消这条公式本身的系统偏置）——同享一根固定轴的"
        "'world_up'/'world_front' 结构上只能触及垂直于该轴的两维，沿轴那一维要么"
        "冻结在到达那一刻的值只随速度整体缩放、永不回头变成"
        "无界发散（第一版），要么额外加独立回拉又会把整批粒子拉扁到同一张平面上"
        "（第二版，2026-09-12 用户反馈\"过中心点后完全只在一个平面里动\"）——per-"
        "粒子各自定轴从根上避开这个结构性缺口：不同粒子的轴方向不同，群体在离散帧"
        "上看起来才有立体感，不会被摊死在同一张平面里。'world_up'/'world_front' 保留"
        "作对照，但都带着上面这条已知缺陷，不建议启用。真正的轴到底是什么，仍未确认。"
        "⚠2026-09-12 再次改判，默认已改为 'lateral_tilt'：'offset_up' 算出来的侧向"
        "方向 n 对 d→-d 是**偶**的，球壳上求和不抵消，整团一起往下滑（θ=180° 时质心"
        "Y=-59，而整团竖直尺寸才 70）——正是用户最早反馈的「全都往 -Z 走，+Z 一个都"
        "没有」。'lateral_tilt' 用 n = cos(φ)e + sin(φ)b、φ = tilt·(d·Y) 构造，φ 取"
        "奇标量使 n 整体为奇 ⇒ mean(n)≡0（实测漂移 0.00000，结构性的），同时保留"
        "竖直压扁。'offset_up' 降级为对照。",
        ("lateral_tilt", "offset_up", "world_up", "world_front"), "lateral_tilt",
    ),
    # "homing_orbit_retarget" 已标定/已废，降级成注释（开关保留，不再是待办）：已定：'once'。曾以为轨道会换一次朝向，后查明那是 d∥世界Y 的退化点附近的数值行为，不是缺机制。
    # "homing_orbit_retarget": (
    #     "HOMING 到达目标转弯之后，转轴还会不会再变。"
    #     "'once_more'（默认）=转满第一圈后再重新定轴一次，然后锁死；"
    #     "'once'=第一次到达定轴后永不改变（旧行为）；"
    #     "'every_pass'=每次转满一圈都重新定轴。"
    #     "2026-09-12 用户拿**连续喷射**探针实拍：粒子在一个圆上转满一圈后换到另一个"
    #     "**同半径、不同朝向、同样过目标点**的圆，**之后就再也不变了**。同半径 ⇒ 不是"
    #     "速度收敛（那会改 r=v/ω）。'once' 根本不会换，排除；'every_pass' 实测这个"
    #     "重定轴映射**环长恒为 2**（对竖直/水平/任意斜向来向都是），会两个圆无限来回"
    #     "倒，也被用户当场否掉。故默认取 'once_more'。"
    #     "⚠ 「恰好两次」是照实拍描出来的现象，不是推出来的机制——真正的成因未知"
    #     "（某个量在第一圈里收敛完？approach 进来的那一下本就该算特例？），"
    #     "轴公式本身也仍未确认。",
    #     ("once", "once_more", "every_pass"), "once",
    # ),
    "homing_orbit_axis_update": (
        "orbit 段的转轴是**冻结**还是**每帧重算**。'frozen'（默认，改动前的行为）="
        "绕到达那一刻定下的轴转到底；'live'=每帧按当前速度方向重新算侧向方向与转轴，"
        "即把侧向力当成一个**场**而不是一根冻结的轴。"
        "两者在纯水平运动下**完全一致**（v·Y≡0 ⇒ 转轴恒为世界 Y ⇒ 严格闭合的水平"
        "圆）；速度一旦有 Y 分量，'live' 会让轨道平面**进动**。"
        "2026-09-12 用户实机四条签名：进动只在有 Y 分量时出现、随 Y 分量减小而减小、"
        "每次完全可复现（非随机）、约 2 圈后稳定——'live' 全中，'frozen' 一条都给"
        "不出（恒零进动）。默认暂留 'frozen' 等用户对拍确认。"
        "⚠ 进动幅度是 homing_orbit_lateral_tilt 的**陡峭**函数，见那一条。",
        ("frozen", "live"), "frozen",
    ),
    "homing_orbit_lateral_tilt": (
        "侧向方向 n 随纬度倾斜多少：n = cos(φ)·e + sin(φ)·b，φ = tilt·(d·世界Y)。"
        "φ 取 d·Y 这个奇标量，保证 n 对 d→-d 为奇 ⇒ mean(n)≡0，**整团不会有净漂移**"
        "（实测各 tilt 下漂移都是 0.00000，结构性的）。tilt 只控制竖直压扁程度："
        "0=半周期压成纯平面，0.8→0.38，1.0→0.46（默认，与上一版 offset_up 的压扁量"
        "相当但没有它那个下滑偏置），1.57→0.65，2.0→0.75。"
        "⚠ 压扁本身是新运动学（侧向力、方向连续）的自然结果，闭式解 θ=180° 时 "
        "p=2r·n，所以半周期形状就是 {n} 的分布；但**具体倾斜量未实测**，1.0 只是"
        "「与改动前观感相当」的选择，需要拿实拍标定。",
        (0.0, 2.0), 1.0,
    ),
    # "homing_orbit_handed" 已标定/已废，降级成注释（开关保留，不再是待办）：已定：'fixed'。连续喷射探针实拍是一条干净曲线，抛硬币必然劈成镜像两族，'random' 已证伪。
    # "homing_orbit_handed": (
    #     "HOMING 到达转弯的左右手性。'fixed'=全体同一个转向（默认）；'random'=每个"
    #     "粒子出生时抛一次硬币。2026-09-12 用户用**连续喷射**探针实拍：整条轨迹是"
    #     "一条干净曲线，而抛硬币必然把同一生成点出来的粒子劈成镜像两族，所以随机"
    #     "手性被证伪；用户另外单独描述过竖直轴上的粒子是「沿平面的**左**向」转，"
    #     "同样指向固定手性。⚠ 'random' 当初是为了压掉球壳生成下「全体往 -Z 甩」"
    #     "那个偏置才加的，改回 'fixed' 之后那个偏置会重新出现——但它本来就是"
    #     "`cross(来向,世界Y)` 这条轴公式自身的结构性缺陷（对任意来向 Y 分量恒为负），"
    #     "该修的是轴公式不是拿随机去盖掉。留 'random' 仅供对照。",
    #     ("fixed", "random"), "fixed",
    # ),
    # "homing_orbit_axial_falloff" 已标定/已废，降级成注释（开关保留，不再是待办）：已废：默认 0。竖直压扁是「侧向力」正确读法下闭式解的自然结果（半周期形状 = 侧向向量 n 的分布），不需要这个旋钮；且 strength=1 会让两极出生的粒子系数为 0、到达后停住，与实拍矛盾。
    # "homing_orbit_axial_falloff": (
    #     "HOMING 到达目标转弯时，沿世界 Y 的那份速度分量被吃掉多少（0=完全保留，"
    #     "轨道半径全体相同；1=只保留垂直于 Y 的分量，v'=v·|来向×Y|）。轨道半径"
    #     "r=v/ω，所以它等价于逐粒子缩放轨道半径。为什么需要这一项：轨道相有闭式解"
    #     "p(θ)=r(1-cosθ)s+r·sinθ·t，|p|=2r|sin(θ/2)| 与转轴无关且逐粒子恒等，"
    #     "所以只要半径全体相同，整团在任何时刻都严格落在同一个球面上，换任何转轴"
    #     "规则都压不出各向异性；而 θ=180° 时 p=2r·s，半周期形状恒等于出生形状的等比"
    #     "放大。实拍差分序列里出生是球壳、半周期那一格却明显压成横条，只剩「半径逐"
    #     "粒子不同」这一个出口。取 1 时两极出生的粒子系数为 0（到达后停在中心不再"
    #     "转圈），是规则的直接推论。具体强度未实测，1 是规则本身、其余是折中。",
    #     "⚠ 2026-09-12 用户实机反证：生在竖直轴上的粒子照常以 turnRate 绕圈（"
    #     "到达中心那一刻转 90°，之后一直在同一个平面里转），而这条规则给它们的系数"
    #     "恰好是 0＝原地不动。**规则形式被证伪，默认已关到 0。** 旋钮留着是因为"
    #     "「逐粒子半径」目前仍是唯一能压出各向异性的机制（见上），但正确的调制形式"
    #     "未知——正确形式必须让两极与赤道都拿满半径。",
    #     (0.0, 1.0), 0.0,
    # ),
    "ribbon_rigid_dir": (
        "RIBBON 定长面片（ribbonMode=1）的伸展方向。'velocity'=跟随当前运动方向"
        "（粒子自己的速度优先，粒子不动则看发射器的位移，都为零时保留上一个有效"
        "方向；≈ Unity Stretched Billboard 的定义）；'static'=出生时用 baseAxis + "
        "rotationX/Y/Z 定死、终生不变（默认，改动前的行为——这几个字段的物理轴"
        "映射本就因为强制朝相机而难以观察，先保守）。",
        ("static", "velocity"), "static",
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
        "rot_order_applied", "ribbon_trail_source", "t3d_apply_base",
        "homing_speed_converge", "homing_speed_ramp_turns", "homing_ff_scale_mode",
        "homing_ff_recover_frames",
        "homing_compose", "homing_orbit_axis",
        "homing_orbit_axial_falloff", "homing_orbit_handed",
        "homing_orbit_lateral_tilt", "homing_orbit_axis_update",
        "homing_orbit_retarget", "ribbon_rigid_dir",
        "stage_order", "render_stage_order", "order_override", "disabled",
        "max_particles_hard", "max_frames", "max_spawn_depth", "trail_max",
        "max_instances", "max_particles_total", "child_cull_grace",
        "child_pending_grace",
        "ribbon_subdiv_max",
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
        self.ribbon_length_mode = "per_segment"
        self.ribbon_rigid_dir = "static"
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
        self.flowmap_speed_unit = "per_second"
        self.flowmap_phase = "cycle"
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
