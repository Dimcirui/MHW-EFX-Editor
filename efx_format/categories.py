"""
efx_format/categories.py  —  属性类型的功能分类表（纯 Python，零 bpy 依赖）

用途：把几十种属性类型按功能分组，供
  - 属性预设的两级下拉（先选分类，再选类内属性）
  - 属性预设按分类存盘（presets/__attributes__/<slug>/<NAME>.json）
两处共用同一份分类事实，避免重复。

分组依据见 docs/ATTRIBUTE_TYPES.md（2026-06 重分类，基于 738 文件 / 16758 entry 统计）。
键为 type_hash（来自 hashes.py），未登记的类型一律归入 "misc"。

分类逻辑摘要：
  skeleton    — Entry 骨架，每个 entry 必有（TRANSFORM3D / PARENTOPTIONS / SPAWN / LIFE）
  renderer    — 渲染主体，互斥选一（BILLBOARD3D / RIBBON / MESH / PLANE /
                FAKEPLANE / LIGHTNING / DUMMY / RIBBONBLADE / STRAINRIBBON / TUBELIGHT…）
  sprite_mod  — 面片渲染专属修饰（billboard/ribbon/plane 专用；与 MESH 完全不共存）
                SHADERSETTINGS（可视渲染体必须，88.3% 共现，缺失则贴图/透明不生效）
                UVSEQUENCE / RGBFIRE / RGBWATER / ALPHACORRECTION / REFRACTION / BLINK / LUMINANCEBLEED
  mesh_over   — MESH 专属覆盖（MATERIAL / UVCONTROL；100% 与 MESH 绑定）
  emitter     — 发射器 / 空间约束（EMITTERSHAPE3D / EMITTERBOUNDARY…）
  motion      — 运动 / 速度 / 动画（VELOCITY3D / SCALEANIM / ROTATEANIM / NOISE…）
  visibility  — 可见性 / 渐隐（FADE* / RAYCAST…）
  lifecycle   — 生命周期触发，entry 最后（PTCOLLISION / PTLIFE / PTTRIGGER / SHOVEL——
                地面接触触发地面特效，非角色专属，故不归 char_effect）
  extern_decl — 外部资源声明，entry 最前（EXTERNREFERENCE）
  char_effect — 角色附着效果（PLEMISSIVE / PARENTEMISSIVE / PLSNOW…）
  behavior    — 独立行为系统，与常规流程互斥（PTBEHAVIOR）
  ui_2d       — 2D / UI 变体（TRANSFORM2D / EMITTERSHAPE2D / VELOCITY2D / BILLBOARD2D；
                2D 特效专用，存在时多数 3D 属性不可用）
  misc        — 特殊 / 控制（RANDOMFIX / TIML / CHECKPUREATTRIBUTE / LAYOUT…）
"""

from .hashes import (
    # 骨架
    TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE,
    # 渲染主体
    BILLBOARD3D, RIBBON, MESH, PLANE, FAKEPLANE,
    LIGHTNING, DUMMY, RIBBONBLADE, STRAINRIBBON, TUBELIGHT,
    BILLBOARD2D,
    # 面片修饰（含 SHADERSETTINGS：可视渲染体必须）
    SHADERSETTINGS,
    UVSEQUENCE, RGBFIRE, RGBWATER, ALPHACORRECTION, REFRACTION, BLINK, LUMINANCEBLEED,
    # MESH 专属覆盖
    MATERIAL, UVCONTROL,
    # 发射器
    EMITTERSHAPE3D, EMITTERSHAPE2D, EMITTERSHAPEMESH, EMITTERBOUNDARY,
    SPAWNBYANGLE, SPAWNBYOCCLUSION,
    # 运动/速度
    VELOCITY3D, VELOCITY2D, SCALEANIM, ROTATEANIM,
    NOISE, TURBULENCE, HOMING, GUIDE, PATHCHAIN, SCREENSPACECOLLISION,
    # 可见性
    FADEBYDEPTH, FADEBYANGLE, FADEBYEMITTERANGLE, FADEBYOCCLUSION,
    MASTERONLY, RAYCAST, LINKPARTSVISIBLE,
    # 生命周期触发
    PTCOLLISION, PTLIFE, PTTRIGGER,
    # 外部声明
    EXTERNREFERENCE,
    # 角色附着
    PLEMISSIVE, PARENTEMISSIVE, PLSNOW, PARENTSNOW, OTOMOSNOW, PARENTMATERIAL, SHOVEL,
    # 独立行为系统
    PTBEHAVIOR,
    # 特殊/控制
    RANDOMFIX, TIML, CHECKPUREATTRIBUTE, REPEATAREA, LAYOUT, TRANSFORM2D,
    FAKEDOF, TONEMAPFILTER, COLORCORRECTFILTER,
)

# ── slug → 双语显示名（下拉顺序按本 dict 的插入顺序）────────────────────────────
# 纯数据：EN + ZH 都存这里，UI 层（blender_efx/i18n.py）按当前语言取用。
ATTRIBUTE_CATEGORY_LABELS = {
    "skeleton":    {"EN": "Entry Skeleton",     "ZH": "Entry 骨架"},
    "renderer":    {"EN": "Renderer",           "ZH": "渲染主体"},
    "sprite_mod":  {"EN": "Sprite Modifiers",   "ZH": "面片修饰"},
    "mesh_over":   {"EN": "Mesh Overrides",     "ZH": "MESH 覆盖"},
    "emitter":     {"EN": "Emitter/Space",      "ZH": "发射器/空间"},
    "motion":      {"EN": "Motion/Velocity",    "ZH": "运动/速度"},
    "visibility":  {"EN": "Visibility/Fade",    "ZH": "可见性/渐隐"},
    "lifecycle":   {"EN": "Lifecycle Triggers", "ZH": "生命周期触发"},
    "extern_decl": {"EN": "Extern Declaration", "ZH": "外部声明"},
    "char_effect": {"EN": "Char Effects",       "ZH": "角色附着效果"},
    "behavior":    {"EN": "Behavior System",    "ZH": "独立行为系统"},
    "ui_2d":       {"EN": "2D / UI Variants",   "ZH": "2D / UI 变体"},
    "misc":        {"EN": "Misc/Control",       "ZH": "特殊/控制"},
}

# ── type_hash → slug ──────────────────────────────────────────────────────────
ATTRIBUTE_CATEGORY_OF = {
    # ── Entry 骨架（每个 entry 必有） ───────────────────────────────────────────
    TRANSFORM3D:       "skeleton",
    PARENTOPTIONS:     "skeleton",
    SPAWN:             "skeleton",
    LIFE:              "skeleton",

    # ── 渲染主体（互斥选一） ──────────────────────────────────────────────────
    BILLBOARD3D:       "renderer",
    RIBBON:            "renderer",
    MESH:              "renderer",
    PLANE:             "renderer",
    FAKEPLANE:         "renderer",   # 地面投影面片，需 RAYCAST
    LIGHTNING:         "renderer",
    DUMMY:             "renderer",   # 无视觉输出的功能性宿主（PTLIFE/SHOVEL/PLEMISSIVE 宿主）
    RIBBONBLADE:       "renderer",
    STRAINRIBBON:      "renderer",
    TUBELIGHT:         "renderer",

    # ── 面片渲染专属修饰（billboard/ribbon/plane 专用，与 MESH 完全不共存） ───
    SHADERSETTINGS:    "sprite_mod",  # 可视渲染体必须（88.3% 共现）；缺失则贴图/透明不生效
    UVSEQUENCE:        "sprite_mod",  # BILLBOARD3D/RIBBON 强制伴随
    RGBFIRE:           "sprite_mod",  # 与 RGBWATER 互斥
    RGBWATER:          "sprite_mod",  # 与 RGBFIRE 互斥
    ALPHACORRECTION:   "sprite_mod",  # 与 MESH/UVCONTROL 完全不共存
    REFRACTION:        "sprite_mod",
    BLINK:             "sprite_mod",
    LUMINANCEBLEED:    "sprite_mod",

    # ── MESH 专属覆盖（100% 绑定 MESH，与 UVSEQUENCE 体系完全独立） ────────────
    MATERIAL:          "mesh_over",   # 99.6% 与 MESH 共存；覆盖 mrl3 材质属性
    UVCONTROL:         "mesh_over",   # 100% 与 MESH 共存；UV 滚动（与 UVSEQUENCE 互斥）

    # ── 发射器 / 空间约束 ─────────────────────────────────────────────────────
    EMITTERSHAPE3D:    "emitter",
    EMITTERSHAPEMESH:  "emitter",
    EMITTERBOUNDARY:   "emitter",
    SPAWNBYANGLE:      "emitter",
    SPAWNBYOCCLUSION:  "emitter",

    # ── 运动 / 速度 / 动画 ────────────────────────────────────────────────────
    VELOCITY3D:        "motion",
    SCALEANIM:         "motion",
    ROTATEANIM:        "motion",
    NOISE:             "motion",
    TURBULENCE:        "motion",
    HOMING:            "motion",
    GUIDE:             "motion",
    PATHCHAIN:         "motion",
    SCREENSPACECOLLISION: "motion",

    # ── 可见性 / 渐隐 / 着色器 ───────────────────────────────────────────────
    FADEBYDEPTH:       "visibility",
    FADEBYANGLE:       "visibility",
    FADEBYEMITTERANGLE:"visibility",
    FADEBYOCCLUSION:   "visibility",
    MASTERONLY:        "visibility",
    RAYCAST:           "visibility",
    LINKPARTSVISIBLE:  "visibility",

    # ── 生命周期触发（entry 最后，基于 action 段的事件触发器） ────────────────────
    PTCOLLISION:       "lifecycle",
    PTLIFE:            "lifecycle",
    PTTRIGGER:         "lifecycle",
    # SHOVEL：接近地面时在接触点生成地面特效（非玩家专属，如引擎喷火烤焦地面）；
    # 位置统计上与 PTLIFE/PTCOLLISION/PTTRIGGER 同属尾部触发层，语义也是接触触发，
    # 归 char_effect 不准确（2026-07 由 char_effect 改归 lifecycle）
    SHOVEL:            "lifecycle",

    # ── 外部资源声明（entry 最前，声明引用 extern 段） ─────────────────────────
    EXTERNREFERENCE:   "extern_decl",

    # ── 角色附着效果 ──────────────────────────────────────────────────────────
    PLEMISSIVE:        "char_effect",   # 宿主 100% 为 DUMMY
    PARENTEMISSIVE:    "char_effect",   # 宿主 100% 为 DUMMY
    PLSNOW:            "char_effect",
    PARENTSNOW:        "char_effect",
    OTOMOSNOW:         "char_effect",
    PARENTMATERIAL:    "char_effect",

    # ── 独立行为系统（与常规渲染/物理流程完全不兼容） ────────────────────────
    PTBEHAVIOR:        "behavior",

    # ── 特殊 / 控制 ───────────────────────────────────────────────────────────
    RANDOMFIX:         "misc",
    TIML:              "misc",
    CHECKPUREATTRIBUTE:"misc",
    REPEATAREA:        "misc",
    LAYOUT:            "misc",
    FAKEDOF:           "misc",
    TONEMAPFILTER:     "misc",
    COLORCORRECTFILTER:"misc",

    # ── 2D / UI 变体（2D 特效专用，存在时多数 3D 属性不可用；见 2d-ui-dialect）──
    TRANSFORM2D:       "ui_2d",
    EMITTERSHAPE2D:    "ui_2d",
    VELOCITY2D:        "ui_2d",
    BILLBOARD2D:       "ui_2d",
}


def category_of(type_hash: int) -> str:
    """返回属性类型的分类 slug；未登记类型归 'misc'。"""
    return ATTRIBUTE_CATEGORY_OF.get(type_hash, "misc")


def category_label(slug: str, lang: str = "ZH") -> str:
    """slug → 显示名（lang: 'EN'/'ZH'）；未知 slug 原样返回。"""
    entry = ATTRIBUTE_CATEGORY_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug


def renderer_suffix(type_hashes) -> str:
    """给定一个 entry 内属性的 type_hash 序列（原始顺序），返回渲染主体后缀，
    形如 " (Mesh)" / " (Ribbon, Dummy)"；不含渲染主体属性时返回空串。

    供 Entry 显示名拼接用（不落盘，导入/重排/改名/增删属性时各自现算）。
    渲染主体在全量语料里基本互斥选一（BILLBOARD3D/RIBBON/MESH/PLANE/LIGHTNING 等
    0 例外），唯一会共存的是 DUMMY 搭配真实渲染体（全量仅 9 例，见
    docs/ATTRIBUTE_TYPES.md「渲染主体（互斥选一）」一节），故多个时直接逗号拼接即可，
    不需要更复杂的展示规则。

    PTBEHAVIOR 单独并入此后缀（不改其 category_of 归类，仍是独立的 "behavior" 分类，
    预设下拉分组不受影响）：它与常规渲染/物理流程完全互斥、接管整个 entry 的表现方式，
    效果上等同于换了一种"渲染主体"，只是不在 ATTRIBUTE_CATEGORY_OF 的 renderer 组里。
    """
    from .hashes import HASH_TO_NAME, pretty_type_name, PTBEHAVIOR
    names = []
    for type_hash in type_hashes:
        if category_of(type_hash) != "renderer" and type_hash != PTBEHAVIOR:
            continue
        raw_name = HASH_TO_NAME.get(type_hash)
        if raw_name:
            names.append(pretty_type_name(raw_name))
    return " (%s)" % ", ".join(names) if names else ""
