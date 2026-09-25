# -*- coding: utf-8 -*-
"""实例树：PTLIFE 触发 ACTION，ACTION 的 PLAYEMITTER 点名目标 entry，构成一棵实例树。

一个 `Simulator` 是一个 entry 的一次实例，`SimScene` 驱动整棵树。

维护约束：
- 子实例跟着父粒子走，每帧把父粒子位置报成子实例的 host_origin。父粒子消亡后子实例
  继续存在但失去 parent，不再跟随、就地留在最后那个位置。是「父死则断链」而非「父死子亡」。
- 本类须与 `Simulator` 保持鸭子兼容：`blender_efx/sim_preview.py` 的播放器把两者当同一
  种东西用，新增 Simulator 的公开口时这里要跟上。
- 三道安全阀（`max_spawn_depth` / `max_instances` / `max_particles_total`）不是可选的：
  ACTION 成环在真实文件里存在，加上「每个粒子都生一棵子树」，不设上限必然挂死。
  任何一道拦下来都要 `em.note` 一条，预览不得静默忽略。
- PLAYEFX（调用外部 .efx）未实现，遇到就 note。
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
    """ACTION 里一个 PLAYEMITTER 点到的目标 entry，带它的 Size 与 Position。"""

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
    """已解析的 EFXFile → SimScene，entry 以 main 段下标做 key。

    实时预览不要走这条：宿主应从正在编辑的属性树建模板、用对象指针解目标。
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
    """PLAYEMITTER 的 Size 是整个子特效的整体缩放，绕锚点缩。

    位置与尺寸都要缩。只把 Size 乘进 `em.scale_dynamic` 是不够的：它唯一的消费者是
    EMITTERSHAPE3D 的生成点，没有该属性的 entry 就完全不受影响。绕锚点缩位置才能连带
    把生成区域与速度轨迹一起缩掉。
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
        # 条带逐顶点缩位置与半宽。半宽是标量，取 x 那一路：非等比缩放下条带宽度
        # 本来就没有唯一正确答案。
        pos = getattr(it.points, "pos", None)
        if pos is not None:
            # 数组形态整条一次缩完，不要为了缩尺寸把它物化成上百个 Vec3——那正是这个
            # 形态要省掉的开销。切片各自独占底层数组的行，原地改不影响别的条带。
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
        #: 发起它的那个实例的 EmitterState（根实例为 None）。与 parent_particle 分开存
        #: 是因为旋转是发射器级的量，不挂在某个粒子上；`_follow` 用它刷新 host_rotation。
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

        逐槽位拷贝；列表类项（stage_order 等）共享引用，它们只读。
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
        # ⚠ 子实例必须自己套用 TRANSFORM3D 的静态变换。`t3d_apply_base` 默认关着的理由
        # 是「宿主已经摆好了 entry 的位置」，而那只对根 entry 成立——子实例锚在父粒子上，
        # 没有宿主替它摆位，静态 translate/rotate/resize 会被整个丢掉。
        cfg = self.config if depth == 0 else self._child_config()
        # 子实例按实例号加盐：否则同一 entry 的所有实例抽到同一组抖动，朝向、大小完全一致
        sim = Simulator(tmpl.blocks, tmpl.timl_bytes, cfg, res,
                        tracks=tmpl.tracks(), seed_salt=self._next_iid if depth else 0)
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

        # 1+2. 逐实例先跟随父粒子、再推进。跟随与推进必须交错而不是分两遍：实例列表里
        #      父一定排在子之前，交错时子拿到的是当前帧的父粒子位置；分两遍会整体慢
        #      一帧，条带与子特效会拖尾。
        #      遍历快照，本帧新建的子实例下一帧才开始跑。
        live = list(self.instances)
        for inst in live:
            if not inst.detached:
                p = inst.parent_particle
                if p is None or not p.alive:
                    # 父粒子消亡：失去 parent，不再跟随，就地留在最后那个位置
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

        # 4. 回收：只回收子实例，根实例永远留着，播放器的帧号靠它。
        #
        # ⚠ 「一个粒子都还没吐过」与「吐完了没了」必须用两个宽限期：
        #    SPAWN.emitterDelayFrame 可以远长于空转宽限，共用一个宽限期会让子实例在开火
        #    前就被回收，表现成这个子特效完全不触发。
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

        # 父实例转起来时子实例的朝向要跟着转，否则子特效永远只往同一个方向发。
        # 逐帧覆盖而非累加：host_rotation 恒等于父此刻的总旋转，不会自己越滚越大。
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
        """根发射器的生成区域线框。只画根的：整棵树全画出来会成为一团线。"""
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
                # 宿主按 entry 取各自的序列帧大图，故每个渲染项都标出自己出自哪个 entry。
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

    def has_indefinite_life(self):
        """任一 entry 模板的 LIFE 开了无限寿命。"""
        from ..hashes import LIFE
        for t in self.templates.values():
            for h, f in t.blocks:
                if int(h) == LIFE and f and int(f.get("indefiniteLifespan", 0) or 0):
                    return True
        return False

    @property
    def instance_count(self):
        return len(self.instances)

    def __repr__(self):
        return ("<SimScene root=%r frame=%d instances=%d particles=%d>"
                % (self.root_key, self.frame, len(self.instances),
                   self.particle_count))
