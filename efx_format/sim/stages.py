# -*- coding: utf-8 -*-
"""behavior 的阶段划分。

维护约束：
- 阶段按「写什么」命名，不按「什么时候跑」命名。新 behavior 归哪个阶段，看它写
  Particle 的哪个槽位；出现新的写入目标时加一个阶段常量，不要重构现有阶段。
- `STAGE_WRITES` 是各阶段允许写的槽位清单，`SimConfig.strict` 打开时逐调用比对，
  越界即抛。新增阶段必须同时登记。
- 阶段顺序是数据：`DEFAULT_STAGE_ORDER` 只是默认值，SimConfig 可整体替换，UI 可
  重排。叠加顺序尚未确认，故做成可调参数而非固定代码分支。
"""

# ── 阶段常量 ─────────────────────────────────────────────────────────────────
# 数值留空隙，便于在两个阶段之间插入新阶段。
FORCE       = 10   # 写 p.vel      —— TURBULENCE / HOMING / GUIDE / 重力
INTEGRATE   = 20   # p.pos ← p.vel —— VELOCITY3D 独占
CONSTRAIN   = 30   # 覆写 p.pos    —— PATHCHAIN / REPEATAREA / EMITTERBOUNDARY / NOISE / 碰撞
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
