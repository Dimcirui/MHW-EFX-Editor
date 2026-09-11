# -*- coding: utf-8 -*-
"""
efx_format/sim/registry.py  —  Behavior 协议 + 注册表

加一个属性 = 新建一个文件 + `@register(HASH)`，不改任何现有代码。这是「后续补充
语义」这条需求的落点。

六个钩子（作用域/时机，与 stage 正交）
--------------------------------------
    on_emitter_init (em, rng)                 一次
    on_emitter_step (em)                      每帧 ×1
    on_particle_spawn(p, em, rng)             每粒子一次
    on_particle_step (p, em)                  每帧 ×N   ← 签名里没有 rng，故意的
    on_particle_death(p, em) -> [SpawnRequest]
    build_render    (p, em, view, item) -> item

三条结构性保证（见各自出处的详细说明）
--------------------------------------
    (a) step 拿不到 rng                 —— rng.py
    (b) 字段只能通过 p.f(HASH) 读        —— resolve.py
    (c) step 必须与视角无关              —— simulator.py

未注册的属性类型不进逐帧流程，但会被记进 `em.unsupported`，UI 上列出「本 entry 有
N 个未模拟属性」。预览不静默撒谎——跟 validate.py 报 WARN 不阻断是同一套做法。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from . import stages as _stages


# ─────────────────────────────────────────────────────────────────────────────
# Behavior 基类
# ─────────────────────────────────────────────────────────────────────────────

class Behavior(object):
    """一个 EFX 属性类型的模拟行为。子类只实现自己关心的钩子。"""

    #: 本 behavior 写哪一类字段，决定它在逐帧流程里的位置。
    #: None = 按 categories.py 的分类取默认（见 stages.default_stage_for）。
    STAGE = None

    #: 同 stage 内的先后；小的先跑。可被 SimConfig.order_override 覆盖。
    ORDER = 100

    #: 本 behavior 负责的属性类型 hash（由 @register 填）
    TYPE_HASH = 0

    #: schema 块名（给 resolve.py 查 TIML 映射用；由 @register 填）
    BLOCK_NAME = ""

    #: 声明「我要逐帧的位置历史」。任一 behavior 打开它，Simulator 就开始给每个
    #: 粒子记 `p.trail`。条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE）要用。
    #: 默认关，因为绝大多数属性不需要，记录是白白的拷贝开销。
    NEEDS_TRAIL = False

    def __init__(self, type_hash, block_name):
        self.type_hash = type_hash
        self.block_name = block_name

    # ── 钩子（默认全是 no-op）─────────────────────────────────────────────────
    def on_emitter_init(self, em, rng):
        """发射器开始播放时一次。预计算、播种、常量表都放这里。"""

    def on_emitter_step(self, em):
        """每帧一次，发射器时间轴。SPAWN 在这里决定这一帧生几个。"""

    def on_particle_spawn(self, p, em, rng):
        """每个粒子出生一次。**所有抖动必须在这里抽**，抽完存 `p.rolled`。"""

    def on_particle_step(self, p, em):
        """每帧、每个活着的粒子。注意签名里没有 rng：逐帧随机用 `em.noise*`。"""

    def on_particle_death(self, p, em):
        """粒子死亡。返回 `[SpawnRequest]` 或 None（PTLIFE 将来住这儿）。"""
        return None

    def build_render(self, p, em, view, item):
        """渲染 pass。RENDER_BODY 阶段 `item` 为 None、负责产出；
        RENDER_MOD 阶段 `item` 是上游产物、就地改。返回 item（或 None 表示不渲染）。"""
        return item

    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self.block_name or hex(self.type_hash))


# ─────────────────────────────────────────────────────────────────────────────
# 注册表
# ─────────────────────────────────────────────────────────────────────────────

_REGISTRY = {}     # type_hash -> Behavior 子类


def register(*type_hashes):
    """把一个 Behavior 子类绑到一个或多个属性类型 hash 上。

        @register(VELOCITY3D)
        class Velocity3D(Behavior):
            STAGE = INTEGRATE
    """
    def deco(cls):
        if not issubclass(cls, Behavior):
            raise TypeError("%r 不是 Behavior 子类" % cls)
        for h in type_hashes:
            h = int(h)
            if h in _REGISTRY and _REGISTRY[h] is not cls:
                raise ValueError(
                    "type_hash 0x%08X 已被 %s 注册，不能再绑 %s"
                    % (h, _REGISTRY[h].__name__, cls.__name__))
            _REGISTRY[h] = cls
        cls.TYPE_HASH = int(type_hashes[0]) if type_hashes else 0
        return cls
    return deco


def registered_hashes():
    return frozenset(_REGISTRY)


def behavior_class_for(type_hash):
    return _REGISTRY.get(int(type_hash))


def _block_name(type_hash):
    try:
        from ..hashes import HASH_TO_NAME
        return HASH_TO_NAME.get(int(type_hash), "")
    except Exception:
        return ""


def resolve_stage(cls, type_hash, config):
    """算出一个 behavior 的最终 (stage, order)：
    SimConfig.order_override > 类上的 STAGE/ORDER > categories.py 的分类默认。"""
    ov = config.order_override.get(int(type_hash)) if config else None
    if ov:
        return int(ov[0]), int(ov[1])
    stage = cls.STAGE if cls.STAGE is not None else _stages.default_stage_for(type_hash)
    return int(stage), int(cls.ORDER)


class BoundBehavior(object):
    """behavior 实例 + 它在这个 entry 里对应的那一块属性数据。"""

    __slots__ = ("behavior", "type_hash", "block_name", "stage", "order",
                 "raw_fields", "attr_index")

    def __init__(self, behavior, type_hash, block_name, stage, order,
                 raw_fields, attr_index):
        self.behavior = behavior
        self.type_hash = type_hash
        self.block_name = block_name
        self.stage = stage
        self.order = order
        self.raw_fields = raw_fields
        self.attr_index = attr_index

    @property
    def sort_key(self):
        return (self.stage, self.order, self.attr_index)

    def __repr__(self):
        return ("<Bound %s stage=%s order=%d>"
                % (self.block_name or hex(self.type_hash),
                   _stages.stage_name(self.stage), self.order))


def build_behaviors(blocks, config):
    """`blocks` 是 [(type_hash, fields_dict), ...]（entry 里属性的原始顺序）。

    返回 (bound_list, unsupported)：
      bound_list  —— 已按 (stage, order, 属性在 entry 里的位置) 排序
      unsupported —— [(type_hash, block_name), ...]，未注册或被 disable 的
    """
    bound = []
    unsupported = []
    for idx, (type_hash, fields) in enumerate(blocks):
        type_hash = int(type_hash)
        name = _block_name(type_hash)
        if config is not None and type_hash in config.disabled:
            unsupported.append((type_hash, name))
            continue
        cls = _REGISTRY.get(type_hash)
        if cls is None:
            unsupported.append((type_hash, name))
            continue
        stage, order = resolve_stage(cls, type_hash, config)
        inst = cls(type_hash, name)
        inst.BLOCK_NAME = name
        bound.append(BoundBehavior(inst, type_hash, name, stage, order, fields, idx))
    bound.sort(key=lambda b: b.sort_key)
    return bound, unsupported


def implements(bound, hook_name):
    """这个 behavior 是否真的覆写了某个钩子（没覆写就不进逐帧循环，省调用开销）。"""
    cls = type(bound.behavior)
    return getattr(cls, hook_name) is not getattr(Behavior, hook_name)
