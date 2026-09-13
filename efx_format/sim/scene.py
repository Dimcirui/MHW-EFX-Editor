# -*- coding: utf-8 -*-
"""
efx_format/sim/scene.py  —  实例树：PTLIFE → ACTION → 目标 entry 的联动

一个 `Simulator` 是**一个 entry 的一次实例**。PTLIFE 让粒子在某个生命阶段触发一个
ACTION，而 ACTION 里的 PLAYEMITTER 点名一组目标 entry —— 于是同一个文件里会同时
跑好多个实例，构成一棵树。`SimScene` 就是这棵树的驱动。

父子关系（用户实机确认）
------------------------
子实例**跟着父粒子走**：每帧把父粒子的位置报成子实例的 host_origin。
父粒子消亡后，子实例**继续存在，但失去 parent** —— 不再跟随，就地留在最后那个位置，
自己的粒子照常演下去。所以这里不是「父死子亡」，而是「父死则断链」。

API 与 Simulator 鸭子兼容
-------------------------
`frame / particles / step() / run_to() / run() / build_render() / reset() /
unsupported / notes / config / em / suggested_duration()` 都在，所以
`blender_efx/sim_preview.py` 的播放器可以把 SimScene 当 Simulator 用，
一行都不用改判断。

安全阀（这块不是可选的）
------------------------
`validate.py` 已经在查 ACTION 成环，说明循环引用在真实文件里存在；加上「每个粒子
都生一棵子树」，不设上限必然挂死。三道闸：

    config.max_spawn_depth     递归深度（默认 4；语料里目标 entry 自己还带 PTLIFE 的
                               只占 3.9%，深度 2 就够覆盖绝大多数）
    config.max_instances       同时存在的实例数
    config.max_particles_total 全树粒子总数

任何一道闸拦下来都 `em.note` 一条 —— 预览不静默撒谎。

未做：PLAYEFX（调用外部 .efx 文件，占 action 条目的 11.7%）。遇到就 note。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from .config import SimConfig
from .resolve import TimlTracks
from .simulator import Simulator
from .state import ONE, RibbonStrip, Vec3, ViewContext


# ─────────────────────────────────────────────────────────────────────────────
# 输入数据
# ─────────────────────────────────────────────────────────────────────────────

class EntryTemplate(object):
    """一个 entry 的「模板」：属性块 + TIML 字节。TIML 只解析一次，多实例复用。"""

    __slots__ = ("key", "blocks", "timl_bytes", "_tracks")

    def __init__(self, key, blocks, timl_bytes=b""):
        self.key = key
        self.blocks = list(blocks or [])
        self.timl_bytes = bytes(timl_bytes or b"")
        self._tracks = None

    def tracks(self):
        if self._tracks is None:
            self._tracks = TimlTracks.parse(self.timl_bytes)
        return self._tracks

    def __repr__(self):
        return "<EntryTemplate %r blocks=%d>" % (self.key, len(self.blocks))


class ActionTarget(object):
    """ACTION 里一个 PLAYEMITTER 点到的一个目标 entry（带它的 Size / Position）。

    Size(@28) 与 Position(@40) 都是实机确认生效的字段。语料里 Size 94% 是 (1,1,1)、
    Position 99% 是 0，所以它们对观感影响很小，但接进来几乎不要钱。
    """

    __slots__ = ("entry_key", "size", "position")

    def __init__(self, entry_key, size=None, position=None):
        self.entry_key = entry_key
        self.size = size or Vec3(1.0, 1.0, 1.0)
        self.position = position or Vec3()

    def __repr__(self):
        return "<ActionTarget %r>" % (self.entry_key,)


# ─────────────────────────────────────────────────────────────────────────────
# 从已解析的 EFXFile 直接搭场景（CLI / 测试用；Blender 侧走对象指针，见 sim_preview）
# ─────────────────────────────────────────────────────────────────────────────

#: PLAYEMITTER raw（type_hash 之后）的偏移。与 blender_efx/action_emitter.py 同一份
#: 结构知识：@28 Size(float3)、@40 Position(float3)、@52 target_count、@56 targets[N]。
_PE_SIZE_OFF = 28
_PE_POS_OFF = 40
_PE_COUNT_OFF = 52
_PE_TARGETS_OFF = 56


def action_targets(action_data, entry_count=None):
    """一个 ActionData → [ActionTarget]（只认 PLAYEMITTER；PLAYEFX 交给调用方 note）。"""
    import struct

    from ..hashes import PLAYEMITTER

    out = []
    for ae in getattr(action_data, "entries", None) or []:
        if int(ae.type_hash) != PLAYEMITTER:
            continue
        raw = ae.raw or b""
        if len(raw) < _PE_TARGETS_OFF:
            continue
        try:
            size = Vec3(*struct.unpack_from("<3f", raw, _PE_SIZE_OFF))
            pos = Vec3(*struct.unpack_from("<3f", raw, _PE_POS_OFF))
            (n,) = struct.unpack_from("<i", raw, _PE_COUNT_OFF)
        except Exception:
            continue
        n = max(0, min(int(n), (len(raw) - _PE_TARGETS_OFF) // 4))
        for k in range(n):
            (ti,) = struct.unpack_from("<i", raw, _PE_TARGETS_OFF + 4 * k)
            if entry_count is not None and not (0 <= ti < entry_count):
                continue
            out.append(ActionTarget(int(ti), size.copy(), pos.copy()))
    return out


def has_playefx(action_data):
    from ..hashes import PLAYEFX

    return any(int(ae.type_hash) == PLAYEFX
               for ae in (getattr(action_data, "entries", None) or []))


def from_efx_file(efx, root_index=0, config=None, resources=None):
    """已解析的 `EFXFile` → SimScene（entry 以 main 段下标做 key）。

    Blender 里**不要**走这条：那边应该从正在编辑的属性树建模板、用对象指针解目标，
    否则预览看到的是上次保存的状态（同 Simulator 的那条注意事项）。
    """
    main = list(getattr(efx, "main", None) or [])
    templates = {}
    for i, e in enumerate(main):
        blocks = []
        for b in (getattr(e, "attr_blocks", None) or []):
            try:
                fields = b.decode()
            except Exception:
                fields = None
            blocks.append((b.type_hash, fields if fields is not None else {}))
        templates[i] = EntryTemplate(i, blocks,
                                     getattr(e, "timl_bytes", b"") or b"")

    actions = {}
    playefx_seen = False
    for ai, a in enumerate(getattr(efx, "play", None) or []):
        actions[ai] = action_targets(a, entry_count=len(main))
        playefx_seen = playefx_seen or has_playefx(a)

    scene = SimScene(templates, actions, root_key=root_index, config=config,
                     resources=resources)
    if playefx_seen:
        scene.note("Action 里有 PLAYEFX（调用外部 .efx）未模拟")
    return scene


# ─────────────────────────────────────────────────────────────────────────────
# 实例
# ─────────────────────────────────────────────────────────────────────────────

def _scale_item(it, anchor, s):
    """PLAYEMITTER 的 Size = 这一整个子特效的**整体缩放**，绕它的锚点缩。

    位置和尺寸都要缩：只缩生成区域（原来那种把 Size 乘进 `em.scale_dynamic` 的做法）
    对**没有 EMITTERSHAPE3D 的 entry 完全不起作用**——`scale_dynamic` 的唯一消费者是
    ES3D 的生成点，而 wp11_017 里那几个 aura 网格根本没有 ES3D，Size=0.4 等于白写。
    绕锚点缩位置则连带把生成区域、速度轨迹一起缩了，才是「整体」。
    """
    p = it.pos
    p.x = anchor.x + (p.x - anchor.x) * s.x
    p.y = anchor.y + (p.y - anchor.y) * s.y
    p.z = anchor.z + (p.z - anchor.z) * s.z
    sz = it.size
    sz.x *= s.x
    sz.y *= s.y
    sz.z *= s.z
    if it.points:
        # 条带：逐顶点位置 + 半宽。半宽是标量，取 x 那一路——Size 在语料里 94% 是
        # 等比的，非等比时条带的宽度本来也没有唯一正确的答案。
        pos = getattr(it.points, "pos", None)
        if pos is not None:
            # 数组形态（RibbonStrip）：整条一次缩完，别为了缩个尺寸把它物化成
            # 上百个 Vec3——那正是这个形态要省掉的东西。切片各自独占 Q 的行，
            # 原地改不会影响别的条带。
            off = (anchor.x, anchor.y, anchor.z)
            pos -= off
            pos *= (s.x, s.y, s.z)
            pos += off
            it.points = RibbonStrip(pos, it.points.half * s.x, it.points.alpha)
            return
        pts = []
        for q, hw, a in it.points:
            pts.append((Vec3(anchor.x + (q.x - anchor.x) * s.x,
                             anchor.y + (q.y - anchor.y) * s.y,
                             anchor.z + (q.z - anchor.z) * s.z),
                        hw * s.x, a))
        it.points = pts


class Instance(object):
    """树上的一个节点 = 一个 entry 的一次运行。"""

    __slots__ = ("iid", "key", "sim", "depth", "parent_particle", "parent_em",
                 "offset", "birth_frame", "idle_frames", "detached", "scale")

    def __init__(self, iid, key, sim, depth, parent_particle=None, offset=None,
                 birth_frame=0, scale=None, parent_em=None):
        self.iid = iid
        self.key = key
        self.sim = sim
        self.depth = depth
        #: 发起它的那个粒子（根实例为 None）。粒子死了就断链，见 detached。
        self.parent_particle = parent_particle
        #: 发起它的那个**实例**的 EmitterState（根实例为 None）。跟 parent_particle
        #: 分开存是因为旋转是发射器级的量，不挂在某个粒子上——`_follow` 用它逐帧
        #: 刷新 `self.em.host_rotation`（见模块 docstring「父子关系」）。
        self.parent_em = parent_em
        self.offset = offset or Vec3()
        #: PLAYEMITTER 的 Size —— 这一整个子特效的整体缩放（见 SimScene.build_render）
        self.scale = scale or Vec3(1.0, 1.0, 1.0)
        self.birth_frame = birth_frame
        self.idle_frames = 0
        #: True = 已经失去 parent（父粒子消亡），不再跟随，就地留下
        self.detached = parent_particle is None

    @property
    def em(self):
        return self.sim.em

    def __repr__(self):
        return ("<Instance #%d %r depth=%d particles=%d%s>"
                % (self.iid, self.key, self.depth, len(self.sim.em.particles),
                   " detached" if self.detached else ""))


# ─────────────────────────────────────────────────────────────────────────────
# SimScene
# ─────────────────────────────────────────────────────────────────────────────

class SimScene(object):
    """一棵实例树。`templates` / `actions` 由宿主准备好（Blender 侧是对象指针，
    CLI 侧是段内下标），本类只按 key 查表，不关心 key 是什么类型。"""

    def __init__(self, templates, actions=None, root_key=None, config=None,
                 resources=None, resources_for=None):
        self.templates = {t.key: t for t in templates} if not isinstance(
            templates, dict) else dict(templates)
        #: action key → [ActionTarget]
        self.actions = dict(actions or {})
        self.root_key = root_key if root_key is not None else next(
            iter(self.templates), None)
        self.config = config or SimConfig()
        self.resources = resources
        #: key → SimResources 的解析函数（每个 entry 有自己的 .uvs 帧表）。
        #: 没给就所有实例共用 `resources`。
        self.resources_for = resources_for
        self.instances = []
        self.root = None
        self._next_iid = 0
        self._notes = []
        self._child_cfg = None
        self.reset()

    # ── 生命周期 ─────────────────────────────────────────────────────────────
    def reset(self):
        self.frame = -1
        self.instances = []
        self._next_iid = 0
        self._notes = []
        self.root = None
        if self.root_key in self.templates:
            self.root = self._make_instance(self.root_key, depth=0)
        return self.em

    def _child_config(self):
        """子实例用的 config：与根共用一切，只把 `t3d_apply_base` 打开。

        SimConfig 是 __slots__ 类，逐槽位拷；列表那几项（stage_order 之类）共享引用
        没问题——它们只读。
        """
        if self._child_cfg is None:
            c = SimConfig()
            for name in SimConfig.__slots__:
                try:
                    setattr(c, name, getattr(self.config, name))
                except Exception:
                    pass
            c.t3d_apply_base = True
            self._child_cfg = c
        return self._child_cfg

    def _make_instance(self, key, depth, parent_particle=None, target=None, parent_em=None):
        tmpl = self.templates.get(key)
        if tmpl is None:
            self.note("Action 指向的 entry %r 不在本次模拟里，已跳过" % (key,))
            return None
        res = self.resources
        if self.resources_for is not None:
            try:
                res = self.resources_for(key) or res
            except Exception:
                pass
        # ⚠ 子实例要**自己套用** TRANSFORM3D 的静态变换。`t3d_apply_base` 默认关着，
        # 理由是「Blender 里 entry 的 empty 已经被 transform_sync 摆好了」——那只对
        # **根** entry 成立。子实例是锚在父粒子上的，没有任何宿主替它摆位，静态
        # translate/rotate/resize 就这么被整个丢掉了。
        # 实例：wp11_017 的 aura32a/b/c 只差一个静态 rotate Z（0 / ±120°），丢了之后
        # 三份完全重叠画在同一处。
        cfg = self.config if depth == 0 else self._child_config()
        sim = Simulator(tmpl.blocks, tmpl.timl_bytes, cfg, res,
                        tracks=tmpl.tracks())
        offset = target.position.copy() if target is not None else Vec3()
        scale = target.size.copy() if target is not None else None
        inst = Instance(self._next_iid, key, sim, depth, parent_particle, offset,
                        max(0, self.frame), scale, parent_em=parent_em)
        self._next_iid += 1
        if parent_particle is not None:
            self._follow(inst)
        self.instances.append(inst)
        return inst

    # ── 推进 ─────────────────────────────────────────────────────────────────
    def step(self):
        self.frame += 1

        # 1+2. 逐实例：先跟随父粒子、再推进。
        #
        # 跟随与推进**交错**而不是分两遍：实例列表里父一定排在子之前（子是父存在
        # 之后才建的），所以轮到子的时候父这一帧已经走完了，子拿到的是**当前帧**的
        # 父粒子位置，不是上一帧的（分两遍会整体慢一帧，条带/子特效会拖尾）。
        #
        # 遍历快照：本帧新建的子实例下一帧才开始跑（它是发射器不是粒子，从自己的
        # 第 0 帧干净起步更好推理）。
        live = list(self.instances)
        for inst in live:
            if not inst.detached:
                p = inst.parent_particle
                if p is None or not p.alive:
                    # 父粒子消亡 → 失去 parent，不再跟随，就地留在最后那个位置
                    inst.detached = True
                else:
                    self._follow(inst)
            inst.sim.step()

        # 3. 消化触发请求
        for inst in live:
            reqs = inst.em.spawn_requests
            if reqs:
                inst.em.spawn_requests = []
                self._consume(inst, reqs)

        # 4. 回收：只回收子实例（根实例永远留着，播放器的帧号靠它）
        #
        # ⚠ 「一个粒子都还没吐过」和「吐完了没了」是两回事，不能用同一个宽限期：
        # SPAWN.emitterStartDelay 可以很长（用户的 `explpt` 是 60 帧），而空转宽限只有
        # 30 帧——按老逻辑它在开火前 30 帧就被回收了，表现成「这个子特效完全不触发」。
        # 所以还没生成过粒子的实例用一个**宽得多**的等待上限，生成过之后才按 grace 收。
        grace = int(getattr(self.config, "child_cull_grace", 30))
        pending = int(getattr(self.config, "child_pending_grace", 600))
        keep = []
        for inst in self.instances:
            if inst.depth == 0:
                keep.append(inst)
                continue
            if inst.em.particles:
                inst.idle_frames = 0
                keep.append(inst)
                continue
            inst.idle_frames += 1
            limit = grace if getattr(inst.em, "spawned_total", 0) else pending
            if inst.idle_frames < limit:
                keep.append(inst)
        self.instances = keep
        return self.em

    def _follow(self, inst):
        ho = inst.em.host_origin
        p = inst.parent_particle
        ho.x = p.pos.x + inst.offset.x
        ho.y = p.pos.y + inst.offset.y
        ho.z = p.pos.z + inst.offset.z

        # 父实例转起来，它召唤出的子实例（生成方式/初速度的朝向）要跟着一起转，
        # 不然子特效永远只往同一个方向发，看不出父的旋转（见 _common.emitter_rotate）。
        # 逐帧覆盖而非累加：host_rotation 恒等于「父此刻的总旋转」，父继续转下一帧
        # 这里跟着更新，父不转就一直是父那份常量，不会自己越滚越大。
        pem = inst.parent_em
        if pem is not None:
            hr = inst.em.host_rotation
            hr.x = pem.rot_dynamic.x + pem.host_rotation.x
            hr.y = pem.rot_dynamic.y + pem.host_rotation.y
            hr.z = pem.rot_dynamic.z + pem.host_rotation.z

    def _consume(self, inst, reqs):
        cfg = self.config
        for req in reqs:
            if req.kind == "efx":
                self.note("Action 里的 PLAYEFX（调用外部 .efx）未模拟")
                continue
            if req.kind != "action":
                self.note("未知的子发射请求 kind=%r，已跳过" % (req.kind,))
                continue
            if inst.depth + 1 > cfg.max_spawn_depth:
                self.note("触发深度超过 max_spawn_depth=%d，更深的子特效未模拟"
                          % cfg.max_spawn_depth)
                continue
            targets = self.actions.get(req.target)
            if not targets:
                self.note("Action %r 没有可用的 PLAYEMITTER 目标" % (req.target,))
                continue
            for target in targets:
                if len(self.instances) >= cfg.max_instances:
                    self.note("同时存在的子特效达到上限 max_instances=%d，后续未生成"
                              % cfg.max_instances)
                    return
                if self.particle_count >= cfg.max_particles_total:
                    self.note("全树粒子数达到上限 max_particles_total=%d，后续未生成"
                              % cfg.max_particles_total)
                    return
                self._make_instance(target.entry_key, inst.depth + 1,
                                    parent_particle=req.particle, target=target,
                                    parent_em=inst.em)

    def run_to(self, frame):
        if frame < self.frame:
            self.reset()
        while self.frame < frame:
            self.step()
        return self.em

    def run(self, frames):
        for _ in range(int(frames)):
            self.step()
        return self.em

    # ── 渲染 ─────────────────────────────────────────────────────────────────
    def emitter_outline(self, segments=28):
        """**根发射器**的生成区域线框。

        只画根的：PtLife 子实例各有各的形状，一棵几十个实例的树全画出来就成了
        一团线，而作者正在编辑的是根那个。
        """
        try:
            return self.root.sim.emitter_outline(segments)
        except Exception:
            return []

    def build_render(self, view=None):
        view = view or ViewContext()
        out = []
        for inst in self.instances:
            items = inst.sim.build_render(view)
            s = inst.scale
            scaled = (s.x != 1.0 or s.y != 1.0 or s.z != 1.0)
            anchor = inst.em.host_origin if scaled else None
            for it in items:
                # 宿主要按 entry 取各自的序列帧大图（一棵树里每个 entry 一张），
                # 所以每个渲染项都标出自己出自哪个 entry。
                it.extra["entry_key"] = inst.key
                it.extra["instance"] = inst.iid
                if scaled:
                    _scale_item(it, anchor, s)
            out.extend(items)
        return out

    # ── Simulator 鸭子兼容的那几个口 ─────────────────────────────────────────
    @property
    def em(self):
        return self.root.em if self.root is not None else None

    @property
    def particles(self):
        out = []
        for inst in self.instances:
            out.extend(inst.sim.em.particles)
        return out

    @property
    def particle_count(self):
        return sum(len(inst.sim.em.particles) for inst in self.instances)

    @property
    def unsupported(self):
        seen = {}
        for inst in self.instances:
            for h, name in inst.sim.unsupported:
                seen[int(h)] = name
        return [(h, n) for h, n in seen.items()]

    @property
    def notes(self):
        out = list(self._notes)
        for inst in self.instances:
            for n in inst.sim.notes:
                if n not in out:
                    out.append(n)
        return out

    def note(self, msg):
        if msg not in self._notes:
            self._notes.append(msg)

    def suggested_duration(self, default=180):
        if self.root is None:
            return default
        return self.root.sim.suggested_duration(default)

    @property
    def instance_count(self):
        return len(self.instances)

    def __repr__(self):
        return ("<SimScene root=%r frame=%d instances=%d particles=%d>"
                % (self.root_key, self.frame, len(self.instances),
                   self.particle_count))
