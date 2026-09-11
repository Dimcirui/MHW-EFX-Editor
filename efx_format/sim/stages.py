# -*- coding: utf-8 -*-
"""
efx_format/sim/stages.py  —  behavior 的阶段划分

设计要点：**阶段按「写什么」命名，不按「什么时候跑」命名。**

`pre/motion/post` 这类相对时机命名的问题是：叠加顺序本来就未确认，以后每加一个
属性都可能要插队，而「pre」里挤满互不相干的东西之后，没人说得清一个新 behavior
该放哪。改成按写入目标命名之后：

  - NOISE/TURBULENCE/HOMING/GUIDE 都写速度 → 全在 FORCE，彼此用 ORDER 排；
  - PATHCHAIN/REPEATAREA 不是「在运动之后」，而是「写 pos 不写 vel」→ CONSTRAIN
    这个名字自己解释了它为什么必须排在 INTEGRATE 后面；
  - 将来真出现「积分前改位置」的属性，那是个新阶段（加一个常量），不必重构。

副产品：`STAGE_WRITES` 给出每个阶段允许写的 Particle 槽位，`SimConfig.strict`
打开时逐调用比对，越界即抛（FORCE 的 behavior 碰了 p.pos = bug）。30 个 behavior
共存之后，这是唯一能自动检查的契约。

阶段顺序是**数据不是代码**：`DEFAULT_STAGE_ORDER` 只是默认值，SimConfig 可整体
替换，UI 上可拖动重排——把「顺序未知」变成可调参数，而不是待定的代码分支。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

# ── 阶段常量 ─────────────────────────────────────────────────────────────────
# 数值留空隙，方便以后往中间插（例如 WARP = 15：积分前改位置）。
FORCE       = 10   # 写 p.vel      —— NOISE / TURBULENCE / HOMING / GUIDE / 重力
INTEGRATE   = 20   # p.pos ← p.vel —— VELOCITY3D 独占
CONSTRAIN   = 30   # 覆写 p.pos    —— PATHCHAIN / REPEATAREA / EMITTERBOUNDARY / 碰撞
XFORM       = 40   # 写 p.scale / p.rot —— SCALEANIM / ROTATEANIM
SHADE       = 50   # 写 p.color / p.alpha —— LIFE 淡入淡出 / BLINK / RGBFIRE
RENDER_BODY = 60   # 产出 RenderItem —— BILLBOARD3D / MESH / RIBBON / DUMMY
RENDER_MOD  = 70   # 改 RenderItem   —— UVSEQUENCE / SHADERSETTINGS / FADEBY*

#: 逐粒子 step 用到的阶段（顺序即执行顺序）
DEFAULT_STAGE_ORDER = (FORCE, INTEGRATE, CONSTRAIN, XFORM, SHADE)

#: 渲染 pass 用到的阶段（与 step 分开，见 simulator.build_render）
DEFAULT_RENDER_STAGE_ORDER = (RENDER_BODY, RENDER_MOD)

STAGE_NAMES = {
    FORCE:       "FORCE",
    INTEGRATE:   "INTEGRATE",
    CONSTRAIN:   "CONSTRAIN",
    XFORM:       "XFORM",
    SHADE:       "SHADE",
    RENDER_BODY: "RENDER_BODY",
    RENDER_MOD:  "RENDER_MOD",
}

STAGE_LABELS = {
    FORCE:       {"EN": "Force (writes velocity)",     "ZH": "受力（写速度）"},
    INTEGRATE:   {"EN": "Integrate (vel → pos)",       "ZH": "积分（速度→位置）"},
    CONSTRAIN:   {"EN": "Constrain (overwrites pos)",  "ZH": "约束（覆写位置）"},
    XFORM:       {"EN": "Transform (scale/rotation)",  "ZH": "变换（缩放/旋转）"},
    SHADE:       {"EN": "Shade (color/alpha)",         "ZH": "着色（颜色/透明度）"},
    RENDER_BODY: {"EN": "Render body",                 "ZH": "渲染主体"},
    RENDER_MOD:  {"EN": "Render modifier",             "ZH": "渲染修饰"},
}

# ── 契约：每个阶段允许写哪些 Particle 槽位（strict 模式据此断言）──────────────
# `rolled` / `user` / `alive` 任何阶段都可写，不列入检查（见 _EXEMPT）。
STAGE_WRITES = {
    FORCE:       frozenset({"vel"}),
    INTEGRATE:   frozenset({"pos", "vel"}),
    CONSTRAIN:   frozenset({"pos", "vel"}),
    XFORM:       frozenset({"scale", "rot"}),
    SHADE:       frozenset({"color", "alpha"}),
    RENDER_BODY: frozenset(),   # 渲染阶段完全不许碰粒子状态
    RENDER_MOD:  frozenset(),
}

#: 任何阶段都可写的槽位（behavior 私有状态 + 存活标志）
EXEMPT_SLOTS = frozenset({"rolled", "user", "alive"})

#: strict 模式检查的槽位全集
CHECKED_SLOTS = frozenset({"pos", "vel", "scale", "rot", "color", "alpha", "age"})


# ── 按 categories.py 的分类推默认阶段 ────────────────────────────────────────
# 复用仓库既有的分类体系，新属性的 STAGE 有个合理默认，作者只在默认不对时才覆盖。
DEFAULT_STAGE_BY_CATEGORY = {
    "renderer_body":     RENDER_BODY,
    "renderer_modifier": RENDER_MOD,
    "motion_visibility": FORCE,
    "skeleton":          FORCE,
    "spawn_method":      FORCE,   # 这类通常只实现 on_particle_spawn，阶段无所谓
}


def default_stage_for(type_hash):
    """按 categories.py 的分类给出默认阶段；分类不可用时退回 FORCE。"""
    try:
        from ..categories import ATTRIBUTE_CATEGORY_OF
    except Exception:
        return FORCE
    cat = ATTRIBUTE_CATEGORY_OF.get(type_hash, "misc")
    return DEFAULT_STAGE_BY_CATEGORY.get(cat, FORCE)


def stage_name(stage):
    return STAGE_NAMES.get(stage, "STAGE_%s" % stage)
