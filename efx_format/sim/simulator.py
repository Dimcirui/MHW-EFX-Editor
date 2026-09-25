# -*- coding: utf-8 -*-
"""顶层驱动：EmitterState 与 Simulator。

维护约束：
- `step()` 与 `build_render(view)` 是两个独立调用。逐帧模拟必须与视角无关，依赖相机的
  属性只能进渲染 pass；暂停时转视角因此只需重跑 build_render。
- 不做子步。EFX 全程整数帧，逐帧乘法递推没有 dt 的位置，不要引入。
- 出生当帧就参与 step（frame N 生成的粒子在 frame N 以 age=0 跑一次），故 life=1 的
  粒子正好活 1 帧。这是未经验证的取舍。
- 先生成、后收割：本帧要死的粒子在本帧的生成决策里仍占着 maxParticles 名额。同为未经
  验证的取舍；换顺序只需调整 step() 里两段的位置。
"""

from . import registry as _reg
from . import rng as _rng
from . import stages as _stages
from ..categories import ATTRIBUTE_CATEGORY_OF
from ..hashes import TUBELIGHT
from .config import SimConfig
from .resolve import FieldView, TimlTracks
from .state import Particle, RenderItem, RibbonStrip, Vec3, ViewContext
from .uvs_table import SimResources

#: 没有可用渲染体时，退化点的显示尺寸（游戏单位；100 游戏单位 = 1 Blender 单位）。
#: 纯显示默认值，不来自文件——真实尺寸只有渲染体属性（BILLBOARD3D 等）知道。
FALLBACK_SIZE = 10.0

#: 不属于 "renderer_body" 分类但自带完整渲染的类型，判断 entry 有无主体时要算作有
_SELF_RENDERING_EXTRA = frozenset({int(TUBELIGHT)})


def _has_renderer_body(blocks):
    """这个 entry 有没有渲染主体；决定 build_render 给退化点还是干脆不画。

    只有 PTBEHAVIOR、或只有 SPAWN/LIFE/PTLIFE 这类骨架属性（纯当 Action 召唤枢纽）的
    entry 本来就没有视觉主体，给它画退化点是凭空捏造。TUBELIGHT 自带完整渲染，
    虽同归 pt_behavior 分类但要算作有主体。
    """
    for h, _fields in blocks:
        h = int(h)
        if h in _SELF_RENDERING_EXTRA or ATTRIBUTE_CATEGORY_OF.get(h) == "renderer_body":
            return True
    return False


def _apply_emitter_size(item, size, host):
    """按发射器尺寸缩放渲染项的大小（跟随发射器时），位置不动。

    MESH 的顶点经过 entry 的世界矩阵，宿主摆位时已含静态 resize，只补剩下的倍率；
    其余渲染项的大小不经过该矩阵，乘全量。
    """
    s = size
    if item.kind == "MESH":
        s = Vec3(*[c / b if abs(b) > 1e-9 else c
                   for c, b in ((size.x, host.x), (size.y, host.y), (size.z, host.z))])
    if s.x == 1.0 and s.y == 1.0 and s.z == 1.0:
        return
    sz = item.size
    item.size = Vec3(sz.x * s.x, sz.y * s.y, sz.z * s.z)
    pts = item.points
    if not pts:
        return
    if getattr(pts, "pos", None) is not None:
        item.points = RibbonStrip(pts.pos, pts.half * s.x, pts.alpha)
    else:
        # 条带半宽是标量，取 x 那一路，与 scene._scale_item 一致
        item.points = [(q, hw * s.x, a) for q, hw, a in pts]


# ─────────────────────────────────────────────────────────────────────────────
# EmitterState
# ─────────────────────────────────────────────────────────────────────────────

class EmitterState(object):
    """一个发射器实例的运行期状态。behavior 通过它拿字段、拿噪声、排队生成。"""

    __slots__ = (
        "frame", "config", "seed",
        "origin", "host_origin", "drift", "velocity", "prev_origin",
        "rotation", "scale", "rot_dynamic", "scale_dynamic", "rot_order",
        "host_rotation",
        "particles", "spawned_total", "spawn_requests",
        "unsupported", "user", "cycle", "finished", "trail", "trail_need", "resources",
        "_resolvers", "_pending_spawn", "_notes",
    )

    def __init__(self, config, seed, resources=None):
        self.frame = -1
        self.config = config
        self.seed = seed
        #: 宿主塞进来的外部资源（.uvs 字节等，见 uvs_table.SimResources）。
        #: 恒非 None——behavior 不必到处判空。
        self.resources = resources if resources is not None else SimResources()

        # origin = host_origin + drift，每帧合成。两者都会动，必须分开存：合成一个
        # 的话，宿主每帧写一次就会冲掉 TRANSFORM3D 累积的 drift。
        self.host_origin = Vec3()
        self.drift = Vec3()
        self.origin = Vec3()
        self.rotation = Vec3()
        self.scale = Vec3(1.0, 1.0, 1.0)

        #: PTLIFE 子实例从父实例继承来的旋转，逐帧由 SimScene._follow 刷新；根实例恒零。
        #: 与 rot_dynamic 分开存的理由同 origin：两者要能相加，不能互相覆盖。
        self.host_rotation = Vec3()

        # rotation / scale 是全量（给宿主与调试看），rot_dynamic / scale_dynamic 只含
        # 模拟层该自己套的那部分。宿主已按静态 rotate/resize 摆好位，模拟层再套一次就是
        # 双份，故动态部分从无旋转 / 1 倍起步，只被 *_velocity 推动。
        self.rot_dynamic = Vec3()
        self.scale_dynamic = Vec3(1.0, 1.0, 1.0)
        #: TRANSFORM3D.rotationOrder 解析出的顺序串（发射器旋转按它作用）
        self.rot_order = "XYZ"
        self.velocity = Vec3()        # 每帧位移（velocityType=3 EmitterMotion 要用）
        self.prev_origin = Vec3()

        self.particles = []
        self.spawned_total = 0        # 累计生成数（逐粒子播种的序号）
        self.spawn_requests = []      # 子发射请求（PTLIFE / PTCOLLISION）

        self.unsupported = []         # [(type_hash, name)]，未模拟的属性
        self.user = {}                # 发射器级的 behavior 私有状态
        self.cycle = 0                # 当前轮次（SPAWN 的「换位置」计数）
        #: 发射器自己的位置历史（旧→新），供条带沿发射器路径绘制时使用。
        #: 与 p.trail 同样受 NEEDS_TRAIL 门控。
        self.trail = []
        #: behavior 在 on_emitter_init 中声明所需的历史帧数；与 config.trail_max 取大者
        self.trail_need = 0
        self.finished = False         # 发射器不再生成且粒子清空

        self._resolvers = {}
        self._pending_spawn = 0
        self._notes = []

    # ── 字段访问（唯一入口）──────────────────────────────────────────────────
    def f(self, type_hash, p=None):
        """取某个属性块的字段视图。

        `p` 为 None → 发射器视角（A0 取当前帧，无 A1）；
        `p` 非 None → 粒子视角（A0 按 config.a0_sample 取出生帧或当前帧，A1 取 age）。
        """
        r = self._resolvers.get(int(type_hash))
        if r is None:
            return None
        if p is None:
            return FieldView(r, self.frame, None)
        a0 = p.birth_frame if self.config.a0_sample == "spawn" else self.frame
        return FieldView(r, a0, p.age)

    def has(self, type_hash):
        return int(type_hash) in self._resolvers

    # ── 生成队列 ─────────────────────────────────────────────────────────────
    def request_spawn(self, n):
        """排队生成 n 个粒子，本帧结算。maxParticles 由调用方把关，这里只挡硬上限。"""
        if n > 0:
            self._pending_spawn += int(n)

    @property
    def alive_count(self):
        return len(self.particles)

    # ── 噪声（step 里唯一的「随机」来源）──────────────────────────────────────
    def noise1(self, seed, channel=0):
        return _rng.noise1(seed, self.frame, channel)

    def noise3(self, seed, channel=0):
        return _rng.noise3(seed, self.frame, channel)

    def noise_smooth3(self, seed, channel=0, period=8.0):
        return _rng.noise_smooth3(seed, self.frame, channel, period)

    # ── 记事（给 UI 用：本次模拟里跳过/猜测了什么）────────────────────────────
    def note(self, msg):
        if msg not in self._notes:
            self._notes.append(msg)

    @property
    def notes(self):
        return list(self._notes)

    def __repr__(self):
        return ("<EmitterState frame=%d particles=%d spawned=%d>"
                % (self.frame, len(self.particles), self.spawned_total))


# ─────────────────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────────────────

class Simulator(object):
    """一个 EFX Entry 的粒子模拟。

    输入是 `[(type_hash, fields_dict), ...]`——**不是** EntryData，也不是 Blender
    属性树。glue 层从当前正在编辑的属性树构造它，这样预览反映的是未保存的改动。
    """

    def __init__(self, blocks, timl_bytes=b"", config=None, resources=None,
                 tracks=None):
        self.blocks = list(blocks or [])
        self._has_body = _has_renderer_body(self.blocks)
        self.timl_bytes = bytes(timl_bytes or b"")
        self.config = config or SimConfig()
        #: 属性块里没有、必须由宿主提供的外部数据。帧表在 on_emitter_init 解一次即缓存，
        #: 换资源必须 reset。
        self.resources = resources if resources is not None else SimResources()
        # tracks 给了就复用，避免同一个 entry 被 PTLIFE 实例化多次时反复解析 TIML。
        self.tracks = tracks if tracks is not None else TimlTracks.parse(self.timl_bytes)

        self.bound = []
        self.em = None
        self._h_emitter_step = []
        self._h_spawn = []
        self._h_step = []
        self._h_death = []
        self._h_render = []
        self._record_trail = False
        self._trail_max = self.config.trail_max
        self.reset()

    # ── 生命周期 ─────────────────────────────────────────────────────────────
    def reset(self):
        """回到未开始状态（frame = -1），重新跑 on_emitter_init。"""
        cfg = self.config
        self.bound, unsupported = _reg.build_behaviors(self.blocks, cfg)

        em_seed = _rng.emitter_seed(cfg.seed, self._randomfix_seeds())
        em = EmitterState(cfg, em_seed, self.resources)
        em.unsupported = list(unsupported)

        for b in self.bound:
            em._resolvers[b.type_hash] = type(b.behavior).make_resolver(
                b.block_name, b.raw_fields, self.tracks, cfg)

        self._h_emitter_step = [b for b in self.bound if _reg.implements(b, "on_emitter_step")]
        self._h_spawn = [b for b in self.bound if _reg.implements(b, "on_particle_spawn")]
        self._h_step = [b for b in self.bound if _reg.implements(b, "on_particle_step")]
        self._h_death = [b for b in self.bound if _reg.implements(b, "on_particle_death")]
        self._h_render = [b for b in self.bound
                          if _reg.implements(b, "build_render")
                          and b.stage in cfg.render_stage_order]
        self._h_render.sort(key=lambda b: (cfg.render_stage_order.index(b.stage), b.order,
                                           b.attr_index))

        # 任一 behavior 声明 NEEDS_TRAIL 即全局开启位置历史；开销是每粒子每帧一次拷贝。
        self._record_trail = any(type(b.behavior).NEEDS_TRAIL for b in self.bound)

        init_rng = _rng.particle_rng(em_seed, 0)
        for b in self.bound:
            b.behavior.on_emitter_init(em, init_rng)

        for h, name in unsupported:
            em.note("未模拟属性：%s" % (name or ("0x%08X" % h)))

        self._trail_max = max(cfg.trail_max, em.trail_need)

        self.em = em
        return em

    # ── 推进 ─────────────────────────────────────────────────────────────────
    def step(self):
        """推进一帧。返回本帧结束后的 EmitterState。"""
        em = self.em
        cfg = self.config
        em.frame += 1
        if em.frame > cfg.max_frames:
            em.finished = True
            return em

        em.prev_origin = em.origin.copy()

        # 1. 发射器时间轴（TRANSFORM3D 在这里更新 em.drift）
        for b in self._h_emitter_step:
            b.behavior.on_emitter_step(em)

        # 2. 合成发射器位置并算出本帧位移。必须在生成之前：本帧出生的粒子要读它，
        #    放到生成之后就成了上一帧的值。
        em.origin = em.host_origin + em.drift
        em.velocity = em.origin - em.prev_origin
        if self._record_trail:
            em.trail.append(em.origin.copy())
            if len(em.trail) > self._trail_max:
                del em.trail[0]

        # 3. 消化生成队列
        self._consume_spawn(em)

        # 4. 逐粒子 step
        strict = cfg.strict
        record_trail = self._record_trail
        trail_max = self._trail_max
        for p in em.particles:
            if not p.alive:
                continue
            if p.delay_left > 0:
                p.delay_left -= 1
                if cfg.age_during_delay:
                    p.age += 1
                continue
            for b in self._h_step:
                if strict:
                    self._strict_call(b, p, em)
                else:
                    b.behavior.on_particle_step(p, em)
            p.age += 1
            if record_trail:
                t = p.trail
                t.append(p.pos.copy())
                if len(t) > trail_max:
                    del t[0]

        # 4. 收割
        dead = [p for p in em.particles if not p.alive]
        if dead:
            for p in dead:
                for b in self._h_death:
                    req = b.behavior.on_particle_death(p, em)
                    if req:
                        em.spawn_requests.extend(req)
            em.particles = [p for p in em.particles if p.alive]

        return em

    def run_to(self, frame):
        """推进到指定帧（frame 从 0 起）。已经越过则先 reset。"""
        if frame < self.em.frame:
            self.reset()
        while self.em.frame < frame:
            self.step()
        return self.em

    def emitter_outline(self, segments=28):
        """生成区域的线框（成对的点，与粒子同一坐标空间）。没有形状属性就返回 []。

        按「behavior 有没有 outline()」找，不写死 EMITTERSHAPE3D——以后别的形状类
        属性加上同名方法就自动被画出来。
        """
        out = []
        for b in self.bound:
            fn = getattr(b.behavior, "outline", None)
            if fn is None:
                continue
            try:
                out.extend(fn(self.em, segments))
            except Exception:
                pass
        return out

    def run(self, frames):
        """从当前状态再推进 `frames` 帧。"""
        for _ in range(int(frames)):
            self.step()
        return self.em

    # ── 渲染 pass（与 step 解耦；可重复调用，不改状态）────────────────────────
    def build_render(self, view=None):
        em = self.em
        view = view or ViewContext()
        # 整批预计算（条带的轨迹重采样一类）。放在逐粒子循环之外，见
        # Behavior.pre_render。
        for b in self._h_render:
            b.behavior.pre_render(em, view)
        out = []
        for p in em.particles:
            if not p.active:
                continue
            item = None
            for b in self._h_render:
                item = b.behavior.build_render(p, em, view, item)
            if item is not None and item.kind == "NONE":
                continue      # 渲染体明说「我不该有视觉输出」（DUMMY），不走退化点
            if item is not None and "layers" in p.rolled:
                # 双层染色（RGBFIRE/RGBWATER）在 SHADE 阶段算好两层留在 p.rolled 里，
                # 这里统一转交给贴图 glue 的 fragment shader，靠 `*_lerp` 键选 shader
                # 分支；两个键都没有时退回按贴图亮度插值。没贴图的用 item.color。
                # 渲染主体须写 `extra["base_tint"]`，否则两层颜色会顶掉它自身的颜色。
                item.extra.setdefault("layers", p.rolled["layers"])
                if "rgbfire_lerp" in p.rolled:
                    item.extra.setdefault("rgbfire_lerp", p.rolled["rgbfire_lerp"])
                elif "rgbwater_lerp" in p.rolled:
                    item.extra.setdefault("rgbwater_lerp", p.rolled["rgbwater_lerp"])
            if item is None:
                if not self._has_body:
                    # 没有渲染主体类属性：不是「有主体但没实现」，而是本来就不该有画面，
                    # 同 DUMMY 一样明确不画（见 _has_renderer_body）。
                    continue
                # 有渲染主体类属性但尚未实现，退化成一个点。尺寸用显示默认值乘 p.scale：
                # 真实尺寸只有渲染体属性知道，此处没有，不假装知道。
                item = RenderItem(kind="POINT", pos=p.pos.copy(),
                                  size=p.scale * FALLBACK_SIZE)
                item.color = [p.color[0], p.color[1], p.color[2], p.alpha]
                # 调试量：没有真渲染体的时候，速度矢量是判断运动对不对的主要抓手
                item.extra["vel"] = p.vel.copy()
                item.extra["age"] = p.age
            es = p.rolled.get("emitter_size")
            if es is not None:
                _apply_emitter_size(item, es[0], es[1])
            out.append(item)
        return out

    # ── 内部 ─────────────────────────────────────────────────────────────────
    def _randomfix_seeds(self):
        """从 RANDOMFIX 块里取 8 个种子；没有该属性则空。"""
        try:
            from ..hashes import RANDOMFIX
        except Exception:
            return ()
        for h, fields in self.blocks:
            if int(h) == RANDOMFIX:
                return tuple(int(fields.get("randomSeedTable%d" % i, 0) or 0)
                             for i in range(8))
        return ()

    def _consume_spawn(self, em):
        n = em._pending_spawn
        em._pending_spawn = 0
        if n <= 0:
            return
        room = self.config.max_particles_hard - len(em.particles)
        if room <= 0:
            em.note("触发硬上限 max_particles_hard=%d" % self.config.max_particles_hard)
            return
        n = min(n, room)
        for _ in range(n):
            idx = em.spawned_total
            em.spawned_total += 1
            p = Particle(idx, _rng.particle_seed(em.seed, idx), em.frame)
            # 默认出生在发射器原点；有生成方式属性时由它覆写。
            p.pos = em.origin.copy()
            prng = _rng.particle_rng(em.seed, idx)
            for b in self._h_spawn:
                b.behavior.on_particle_spawn(p, em, prng)
            em.particles.append(p)

    def _strict_call(self, b, p, em):
        """strict 模式：逐调用校验 behavior 没有越出它声明的阶段去写字段。

        这是「阶段按写什么命名」换来的唯一能自动检查的契约——30 个 behavior
        共存之后，没有它谁也说不清是谁把 pos 改坏的。
        """
        allowed = _stages.STAGE_WRITES.get(b.stage, frozenset())
        before = self._snapshot(p)
        b.behavior.on_particle_step(p, em)
        after = self._snapshot(p)
        for slot in _stages.CHECKED_SLOTS:
            if before[slot] != after[slot] and slot not in allowed:
                raise AssertionError(
                    "%s 在 %s 阶段写了 p.%s（该阶段只允许写 %s）"
                    % (b.block_name or hex(b.type_hash),
                       _stages.stage_name(b.stage), slot,
                       ", ".join(sorted(allowed)) or "（无）"))

    @staticmethod
    def _snapshot(p):
        return {
            "pos": p.pos.as_tuple(),
            "vel": p.vel.as_tuple(),
            "scale": p.scale.as_tuple(),
            "rot": p.rot.as_tuple(),
            "color": tuple(p.color),
            "alpha": p.alpha,
            "age": p.age,
        }

    # ── 播放长度建议 ─────────────────────────────────────────────────────────
    def suggested_duration(self, default=180):
        """「播放一次」该放多长（帧）。

        EFX 的 SPAWN 三态里**没有一态会停**（见 behaviors/spawn.py 的说明），所以
        循环长度必须由播放器自己定。这里按静态字段（不含抖动）估一个合理值：

            启动延迟 + 一整轮批次 + 一个粒子的完整寿命

        glue 层拿它当「播放一次」的默认长度和循环点，用户可以在 UI 上改。
        """
        try:
            from ..hashes import LIFE, SPAWN
        except Exception:
            return default
        raw = {int(h): f for h, f in self.blocks}

        sp = raw.get(SPAWN) or {}
        lf = raw.get(LIFE) or {}

        def g(d, k, dv=0):
            try:
                return int(d.get(k, dv) or 0)
            except Exception:
                return dv

        start = g(sp, "emitterDelayFrame") + g(sp, "emitterDelayFrameJitter")
        per_cycle = g(sp, "loopNum") + g(sp, "loopNumJitter")
        repeat = g(sp, "revivalLoop")
        interval = (g(sp, "revivalInterval") if per_cycle == 1
                    else g(sp, "intervalFrame"))
        bursts = max(1, per_cycle + repeat - 1) if (per_cycle and repeat) else 1

        life = g(lf, "fadeInDuration") + g(lf, "duration") + g(lf, "fadeOutDuration")
        life += g(lf, "durationJitter") + g(lf, "fadeOutDurationJitter")
        if g(lf, "indefiniteLifespan"):
            life = max(life, default)

        total = start + bursts * max(interval, 1) + max(life, 1)
        return max(1, min(int(total), self.config.max_frames))

    # ── 只读视图 ─────────────────────────────────────────────────────────────
    @property
    def frame(self):
        return self.em.frame

    @property
    def particles(self):
        return self.em.particles

    @property
    def unsupported(self):
        return self.em.unsupported

    @property
    def notes(self):
        return self.em.notes

    def __repr__(self):
        return ("<Simulator blocks=%d behaviors=%d frame=%d particles=%d>"
                % (len(self.blocks), len(self.bound), self.em.frame,
                   len(self.em.particles)))
