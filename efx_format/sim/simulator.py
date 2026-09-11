# -*- coding: utf-8 -*-
"""
efx_format/sim/simulator.py  —  顶层驱动（EmitterState + Simulator）

逐帧流程
--------
    frame += 1
    1. on_emitter_step      —— SPAWN 在这里决定这一帧生几个
    2. 消化生成队列          —— 新粒子逐个跑 on_particle_spawn（唯一能抽 rng 的地方）
    3. on_particle_step      —— 按 stage 顺序，逐个活着的粒子
    4. age++ / delay--
    5. 收割死亡              —— on_particle_death 收集 SpawnRequest

**step() 与 build_render(view) 是两个独立调用。** 逐帧模拟与视角无关（FADEBY* 这类
依赖相机的只能进渲染 pass），所以暂停时转视角只要重跑 build_render，不用步进；
核心也因此能没有相机就单测。

已定的取舍（会影响观感，标定时优先复核）
----------------------------------------
- **出生当帧就参与 step**：frame N 生成的粒子，在 frame N 以 age=0 跑一次 step。
  故 life=1 的粒子正好活 1 帧。另一种可能是「出生帧不动、下一帧才开始」，未验证。
- **先生成、后收割**：本帧要死的粒子，在本帧做生成决策时仍然占着 maxParticles 的
  名额。可见后果是「满编 + 集体同龄」时会出现一帧空窗（老的还占着位所以没补新的，
  紧接着老的全死）。反过来先收割则要求提前知道谁会死，而死是 LIFE 在 step 里判的。
  两种都说得通，未验证；换顺序只需调整 step() 里这两段的位置。
- **不做子步**：EFX 全程整数帧，逐帧乘法递推没有 dt 的位置，不要引入。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from . import registry as _reg
from . import rng as _rng
from . import stages as _stages
from .config import SimConfig
from .resolve import FieldResolver, FieldView, TimlTracks
from .state import Particle, RenderItem, Vec3, ViewContext

#: 没有可用渲染体时，退化点的显示尺寸（游戏单位；100 游戏单位 = 1 Blender 单位）。
#: 纯显示默认值，不来自文件——真实尺寸只有渲染体属性（BILLBOARD3D 等）知道。
FALLBACK_SIZE = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# EmitterState
# ─────────────────────────────────────────────────────────────────────────────

class EmitterState(object):
    """一个发射器实例的运行期状态。behavior 通过它拿字段、拿噪声、排队生成。"""

    __slots__ = (
        "frame", "config", "seed",
        "origin", "velocity", "prev_origin", "rotation", "scale",
        "particles", "spawned_total", "spawn_requests",
        "unsupported", "user", "cycle", "finished",
        "_resolvers", "_pending_spawn", "_notes",
    )

    def __init__(self, config, seed):
        self.frame = -1
        self.config = config
        self.seed = seed

        # 发射器自身的变换。⚠ 默认只含**动态**部分（漂移）——静态 translate 由宿主
        # 摆位承担，见 behaviors/transform3d.py 的说明；cfg.t3d_apply_base 可改。
        self.origin = Vec3()
        self.rotation = Vec3()
        self.scale = Vec3(1.0, 1.0, 1.0)
        self.velocity = Vec3()        # 每帧位移（velocityType=3 EmitterMotion 要用）
        self.prev_origin = Vec3()

        self.particles = []
        self.spawned_total = 0        # 累计生成数（逐粒子播种的序号）
        self.spawn_requests = []      # 子发射请求（PTLIFE/PTCOLLISION，T4）

        self.unsupported = []         # [(type_hash, name)]，未模拟的属性
        self.user = {}                # 发射器级的 behavior 私有状态
        self.cycle = 0                # 当前轮次（SPAWN 的「换位置」计数）
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
        """排队生成 n 个粒子（本帧结算）。上限由调用方（SPAWN）按 maxParticles 把关，
        这里只挡硬上限。"""
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

    def __init__(self, blocks, timl_bytes=b"", config=None):
        self.blocks = list(blocks or [])
        self.timl_bytes = bytes(timl_bytes or b"")
        self.config = config or SimConfig()
        self.tracks = TimlTracks.parse(self.timl_bytes)

        self.bound = []
        self.em = None
        self._h_emitter_step = []
        self._h_spawn = []
        self._h_step = []
        self._h_death = []
        self._h_render = []
        self.reset()

    # ── 生命周期 ─────────────────────────────────────────────────────────────
    def reset(self):
        """回到未开始状态（frame = -1），重新跑 on_emitter_init。"""
        cfg = self.config
        self.bound, unsupported = _reg.build_behaviors(self.blocks, cfg)

        em_seed = _rng.emitter_seed(cfg.seed, self._randomfix_seeds())
        em = EmitterState(cfg, em_seed)
        em.unsupported = list(unsupported)

        for b in self.bound:
            em._resolvers[b.type_hash] = FieldResolver(
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

        init_rng = _rng.particle_rng(em_seed, 0)
        for b in self.bound:
            b.behavior.on_emitter_init(em, init_rng)

        for h, name in unsupported:
            em.note("未模拟属性：%s" % (name or ("0x%08X" % h)))

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

        # 1. 发射器时间轴
        for b in self._h_emitter_step:
            b.behavior.on_emitter_step(em)

        # 2. 发射器这一帧的位移。**必须在生成之前算**——本帧出生的粒子要用它
        #    （velocityType=3 EmitterMotion 继承发射器移动），放到生成之后就变成
        #    读到上一帧的值，出生那一帧永远拿到 0。
        em.velocity = em.origin - em.prev_origin

        # 3. 消化生成队列
        self._consume_spawn(em)

        # 3. 逐粒子 step
        strict = cfg.strict
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

    def run(self, frames):
        """从当前状态再推进 `frames` 帧。"""
        for _ in range(int(frames)):
            self.step()
        return self.em

    # ── 渲染 pass（与 step 解耦；可重复调用，不改状态）────────────────────────
    def build_render(self, view=None):
        em = self.em
        view = view or ViewContext()
        out = []
        for p in em.particles:
            if not p.active:
                continue
            item = None
            for b in self._h_render:
                item = b.behavior.build_render(p, em, view, item)
            if item is None:
                # 这个 entry 没有已实现的 RENDER_BODY（比如渲染体是 RIBBON/MESH）
                # → 退化成一个点，至少能看见「有多少、在哪、多大、多亮」。
                # 尺寸用一个**显示用**的默认值（游戏单位）乘 p.scale：真实尺寸只有
                # 渲染体属性知道，这里没有，所以不假装知道。
                item = RenderItem(kind="POINT", pos=p.pos.copy(),
                                  size=p.scale * FALLBACK_SIZE)
                item.color = [p.color[0], p.color[1], p.color[2], p.alpha]
                # 调试量：没有真渲染体的时候，速度矢量是判断运动对不对的主要抓手
                item.extra["vel"] = p.vel.copy()
                item.extra["age"] = p.age
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
            # 默认出生在发射器原点。EMITTERSHAPE3D 会覆写成「原点 + 形状内采样点」，
            # 但没有生成方式属性的 entry 也得站在发射器上，不能留在世界原点。
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

        start = g(sp, "emitterStartDelay") + g(sp, "emitterStartDelayJitter")
        per_cycle = g(sp, "burstsPerCycle") + g(sp, "burstsPerCycleJitter")
        repeat = g(sp, "emitterRepeatCount")
        interval = (g(sp, "altBurstInterval") if per_cycle == 1
                    else g(sp, "burstInterval"))
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
