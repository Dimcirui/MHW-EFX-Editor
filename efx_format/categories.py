"""
efx_format/categories.py  —  属性类型的功能分类表（纯 Python，零 bpy 依赖）

用途：把属性类型按功能分组，供
  - 属性预设的两级下拉（先选分类，再选类内属性；部分分类内部再按子组分堆）
  - 属性预设按分类存盘（presets/__attributes__/<slug>/[<subgroup>/]<NAME>.json）
两处共用同一份分类事实，避免重复。

2026-07 分类重构（v1）：用位置统计（stats/block_ordering.json）+ 共现矩阵
（stats/cooccurrence.json）交叉验证旧分类（"基础属性+渲染主体+主体修饰"三段式 13 类），
发现多处归属跟实测数据矛盾后重排，详见规划记录。核心变化：
  - FAKEPLANE 从"渲染主体互斥选一"移出（99.8% 跟某个真渲染主体共存，不互斥），归渲染修饰的
    通用/跨宿主子组
  - Renderer 拆成 Body（互斥选一）/ Modifier（依附 Body，可叠加）两个独立顶层类，各自按
    宿主系统（UVS系/Mesh系/Dummy系）再分子组
  - EMITTERBOUNDARY、REPEATAREA、SHADERSETTINGS 按共现数据改判归属
  - Action Trigger 收紧为仅 PTCOLLISION/PTLIFE（有确认的 Action 段引用字段）；PTTRIGGER/SHOVEL
    因证据不足移入 misc
  - TIML 不再登记（它是 entry 子对象 EFX_TIML，不是 EFX_ATTRIBUTE，不走这套分类）

键为 type_hash（来自 hashes.py）。ATTRIBUTE_CATEGORY_OF 未登记的类型一律归入 "misc"；
ATTRIBUTE_SUBGROUP_OF 只有"分类内部再分子组"的类型才有条目，没有条目代表该分类不分子组。

分类逻辑摘要：
  skeleton          — Entry 骨架，每个 entry 必有 + TRANSFORM2D（2D 骨架，同源并入）
  extern_reference  — 外部资源声明，entry 最前（EXTERNREFERENCE）
  renderer_body     — 渲染主体，互斥选一；子组 uvs/mesh/dummy/special（按宿主系统）
  renderer_modifier — 渲染修饰，依附 body、可叠加；子组 uvs/mesh/dummy/generic
  spawn_method      — 生成方式：生成时一次性设定（EMITTERSHAPE3D/RAYCAST…）
  motion_visibility — 运动与可见性：逐帧行为；子组 motion/visibility
  action_trigger    — 触发其他 Action 段（仅 PTCOLLISION/PTLIFE，有确认引用字段）
  pt_behavior       — 独立行为系统，与常规渲染/物理流程互斥（PTBEHAVIOR）
  misc              — 兜底；子组 post_process（屏幕后处理滤镜）/ others（证据不足/待归类）
  custom            — 用户自定义预设专属（无预置类型，运行时由 save_attribute_preset 填充）
"""

from .hashes import (
    # 骨架
    TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE, TRANSFORM2D,
    # 外部声明
    EXTERNREFERENCE,
    # 渲染主体
    BILLBOARD3D, RIBBON, PLANE, LIGHTNING, RIBBONBLADE, STRAINRIBBON, BILLBOARD2D,
    MESH, DUMMY, TUBELIGHT,
    # 渲染修饰
    UVSEQUENCE, RGBFIRE, RGBWATER, ALPHACORRECTION, REFRACTION, BLINK, LUMINANCEBLEED,
    MATERIAL, UVCONTROL,
    PLEMISSIVE, PARENTEMISSIVE, PLSNOW, PARENTSNOW, OTOMOSNOW, PARENTMATERIAL,
    FAKEPLANE, SHADERSETTINGS,
    # 生成方式
    EMITTERSHAPE3D, EMITTERSHAPEMESH, SPAWNBYANGLE, SPAWNBYOCCLUSION, RAYCAST, EMITTERSHAPE2D,
    # 运动与可见性
    VELOCITY3D, SCALEANIM, ROTATEANIM, NOISE, TURBULENCE, HOMING, GUIDE, PATHCHAIN,
    VELOCITY2D, REPEATAREA,
    FADEBYDEPTH, FADEBYANGLE, FADEBYEMITTERANGLE, FADEBYOCCLUSION, MASTERONLY,
    EMITTERBOUNDARY, SCREENSPACECOLLISION, LINKPARTSVISIBLE,
    # Action Trigger
    PTCOLLISION, PTLIFE,
    # PtBehavior
    PTBEHAVIOR,
    # Misc
    FAKEDOF, TONEMAPFILTER, COLORCORRECTFILTER,
    RANDOMFIX, CHECKPUREATTRIBUTE, LAYOUT, PTTRIGGER, SHOVEL,
)

# ── 顶层分类 slug → 双语显示名（下拉顺序按本 dict 的插入顺序）──────────────────
ATTRIBUTE_CATEGORY_LABELS = {
    "skeleton":          {"EN": "Entry Skeleton",       "ZH": "Entry 骨架"},
    "extern_reference":  {"EN": "ExternReference",      "ZH": "ExternReference"},
    "renderer_body":     {"EN": "Renderer Body",        "ZH": "渲染主体"},
    "renderer_modifier": {"EN": "Renderer Modifier",    "ZH": "渲染修饰"},
    "spawn_method":      {"EN": "Generation Method",    "ZH": "生成方式"},
    "motion_visibility": {"EN": "Motion & Visibility",  "ZH": "运动与可见性"},
    "action_trigger":    {"EN": "Action Trigger",       "ZH": "Action Trigger"},
    "pt_behavior":        {"EN": "PtBehavior",          "ZH": "PtBehavior"},
    "misc":              {"EN": "Misc",                 "ZH": "Misc"},
    "custom":            {"EN": "Custom",                "ZH": "Custom"},
}

# ── 子组 slug → 双语显示名（同一 slug 在不同顶层分类下语义一致，共用一份标签）────
ATTRIBUTE_SUBGROUP_LABELS = {
    "uvs":          {"EN": "UVS System",          "ZH": "UVS系"},
    "mesh":         {"EN": "Mesh System",         "ZH": "Mesh系"},
    "dummy":        {"EN": "Dummy System",        "ZH": "Dummy系"},
    "special":      {"EN": "Special",             "ZH": "其他"},
    "generic":      {"EN": "Generic",             "ZH": "通用/跨宿主"},
    "motion":       {"EN": "Motion",              "ZH": "运动"},
    "visibility":   {"EN": "Visibility",          "ZH": "可见性判定"},
    "post_process": {"EN": "Post-process Filters","ZH": "后处理滤镜"},
    "others":       {"EN": "Others",              "ZH": "其他"},
}

# ── type_hash → 顶层分类 slug ──────────────────────────────────────────────────
ATTRIBUTE_CATEGORY_OF = {
    # ── Entry 骨架（每个 entry 必有 + 2D 骨架同源并入） ─────────────────────────
    TRANSFORM3D:       "skeleton",
    PARENTOPTIONS:     "skeleton",
    SPAWN:             "skeleton",
    LIFE:              "skeleton",
    TRANSFORM2D:       "skeleton",   # TRANSFORM3D 的 2D 版本

    # ── 外部资源声明（entry 最前，声明引用 extern 段） ─────────────────────────
    EXTERNREFERENCE:   "extern_reference",

    # ── 渲染主体（互斥选一；子组见 ATTRIBUTE_SUBGROUP_OF） ─────────────────────
    BILLBOARD3D:       "renderer_body",
    RIBBON:            "renderer_body",
    PLANE:             "renderer_body",
    LIGHTNING:         "renderer_body",
    RIBBONBLADE:       "renderer_body",
    STRAINRIBBON:      "renderer_body",
    BILLBOARD2D:       "renderer_body",   # BILLBOARD3D 的 2D 版本
    MESH:              "renderer_body",
    DUMMY:             "renderer_body",   # 无视觉输出的功能性宿主（PTLIFE/SHOVEL/PLEMISSIVE 宿主）
    TUBELIGHT:         "renderer_body",

    # ── 渲染修饰（依附 Body、可叠加；子组见 ATTRIBUTE_SUBGROUP_OF） ────────────
    UVSEQUENCE:        "renderer_modifier",
    RGBFIRE:           "renderer_modifier",   # 与 RGBWATER 互斥
    RGBWATER:          "renderer_modifier",   # 与 RGBFIRE 互斥
    ALPHACORRECTION:   "renderer_modifier",   # 与 MESH/UVCONTROL 完全不共存
    REFRACTION:        "renderer_modifier",
    BLINK:             "renderer_modifier",
    LUMINANCEBLEED:    "renderer_modifier",
    MATERIAL:          "renderer_modifier",   # 99.6% 与 MESH 共存；覆盖 mrl3 材质属性
    UVCONTROL:         "renderer_modifier",   # 100% 与 MESH 共存；UV 滚动（与 UVSEQUENCE 互斥）
    PLEMISSIVE:        "renderer_modifier",   # 宿主 100% 为 DUMMY
    PARENTEMISSIVE:    "renderer_modifier",   # 宿主 100% 为 DUMMY
    PLSNOW:            "renderer_modifier",
    PARENTSNOW:        "renderer_modifier",
    OTOMOSNOW:         "renderer_modifier",
    PARENTMATERIAL:    "renderer_modifier",
    FAKEPLANE:         "renderer_modifier",   # 跨宿主叠加渲染，99.8% 跟某个真渲染体共存，不互斥
    SHADERSETTINGS:    "renderer_modifier",   # 跨宿主：UVS系 100%/MESH 78.6%/DUMMY 43.8% 共现

    # ── 生成方式（生成时一次性设定） ────────────────────────────────────────────
    EMITTERSHAPE3D:    "spawn_method",
    EMITTERSHAPEMESH:  "spawn_method",
    SPAWNBYANGLE:      "spawn_method",
    SPAWNBYOCCLUSION:  "spawn_method",
    RAYCAST:           "spawn_method",
    EMITTERSHAPE2D:    "spawn_method",   # EMITTERSHAPE3D 的 2D 版本

    # ── 运动与可见性（逐帧行为；子组见 ATTRIBUTE_SUBGROUP_OF） ─────────────────
    VELOCITY3D:        "motion_visibility",
    SCALEANIM:         "motion_visibility",
    ROTATEANIM:        "motion_visibility",
    NOISE:             "motion_visibility",
    TURBULENCE:        "motion_visibility",
    HOMING:            "motion_visibility",
    GUIDE:             "motion_visibility",
    PATHCHAIN:         "motion_visibility",
    VELOCITY2D:        "motion_visibility",   # VELOCITY3D 的 2D 版本
    REPEATAREA:        "motion_visibility",   # 跟 VELOCITY3D 共现 91.9%，本质是运动/空间重复行为
    FADEBYDEPTH:       "motion_visibility",
    FADEBYANGLE:       "motion_visibility",
    FADEBYEMITTERANGLE:"motion_visibility",
    FADEBYOCCLUSION:   "motion_visibility",
    MASTERONLY:        "motion_visibility",
    EMITTERBOUNDARY:   "motion_visibility",   # 位置数据落尾部，逐帧边界判定而非生成时形状定义
    SCREENSPACECOLLISION: "motion_visibility",
    LINKPARTSVISIBLE:  "motion_visibility",

    # ── Action Trigger（仅保留有确认 Action 段引用字段的两个） ──────────────────
    PTCOLLISION:       "action_trigger",
    PTLIFE:            "action_trigger",   # relationIndex 已实机验证指向 Action 段

    # ── PtBehavior（独立行为系统，与常规渲染/物理流程完全不兼容） ────────────────
    PTBEHAVIOR:        "pt_behavior",

    # ── Misc（兜底；子组见 ATTRIBUTE_SUBGROUP_OF） ──────────────────────────────
    FAKEDOF:           "misc",
    TONEMAPFILTER:     "misc",
    COLORCORRECTFILTER:"misc",
    RANDOMFIX:         "misc",
    CHECKPUREATTRIBUTE:"misc",
    LAYOUT:            "misc",
    PTTRIGGER:         "misc",   # 原归 Action Trigger，缺确认的 Action 段引用字段，证据不足移出
    SHOVEL:            "misc",   # 同上
}

# ── type_hash → 子组 slug（仅"分类内部再分子组"的类型才有条目）──────────────────
ATTRIBUTE_SUBGROUP_OF = {
    # ── Renderer Body 子组（按宿主系统，共现数据验证：Mesh/Dummy 干净 1:1，
    #    UVS 系 7 个共享同一修饰池互相无细分证据；TUBELIGHT 样本太小+自成一套 schema）──
    BILLBOARD3D:  "uvs",
    RIBBON:       "uvs",
    PLANE:        "uvs",
    LIGHTNING:    "uvs",
    RIBBONBLADE:  "uvs",
    STRAINRIBBON: "uvs",
    BILLBOARD2D:  "uvs",
    MESH:         "mesh",
    DUMMY:        "dummy",
    TUBELIGHT:    "special",

    # ── Renderer Modifier 子组（同上按宿主系统；FAKEPLANE/SHADERSETTINGS 跨宿主归通用组）──
    UVSEQUENCE:      "uvs",
    RGBFIRE:         "uvs",
    RGBWATER:        "uvs",
    ALPHACORRECTION: "uvs",
    REFRACTION:      "uvs",
    BLINK:           "uvs",
    LUMINANCEBLEED:  "uvs",
    MATERIAL:        "mesh",
    UVCONTROL:       "mesh",
    PLEMISSIVE:      "dummy",
    PARENTEMISSIVE:  "dummy",
    PLSNOW:          "dummy",
    PARENTSNOW:      "dummy",
    OTOMOSNOW:       "dummy",
    PARENTMATERIAL:  "dummy",
    FAKEPLANE:       "generic",
    SHADERSETTINGS:  "generic",

    # ── 运动与可见性子组 ─────────────────────────────────────────────────────────
    VELOCITY3D:            "motion",
    SCALEANIM:             "motion",
    ROTATEANIM:            "motion",
    NOISE:                 "motion",
    TURBULENCE:            "motion",
    HOMING:                "motion",
    GUIDE:                 "motion",
    PATHCHAIN:             "motion",
    VELOCITY2D:            "motion",
    REPEATAREA:            "motion",
    FADEBYDEPTH:           "visibility",
    FADEBYANGLE:           "visibility",
    FADEBYEMITTERANGLE:    "visibility",
    FADEBYOCCLUSION:       "visibility",
    MASTERONLY:            "visibility",
    EMITTERBOUNDARY:       "visibility",
    SCREENSPACECOLLISION:  "visibility",
    LINKPARTSVISIBLE:      "visibility",

    # ── Misc 子组 ────────────────────────────────────────────────────────────────
    FAKEDOF:            "post_process",
    TONEMAPFILTER:      "post_process",
    COLORCORRECTFILTER: "post_process",
    RANDOMFIX:          "others",
    CHECKPUREATTRIBUTE: "others",
    LAYOUT:             "others",
    PTTRIGGER:          "others",
    SHOVEL:             "others",
}

# ── 后缀显示：entry 显示名要拼接的类型集合，跟预设分类树彻底解耦（见 renderer_suffix）──
# 判据"没有它就无法正常表现"：只有 Renderer Body（决定"有没有东西可看"）+ PtBehavior
# （接管整个 entry 表现方式，效果等同换渲染主体）才算；FAKEPLANE 等修饰只是让 body 表现
# 出不同细节，不是独立显示单元，不列入。额外加入 Action Trigger + ExternReference——
# 这两个是"用户翻属性才知道"的信息，属于后缀该覆盖的粒度。
SUFFIX_DISPLAY_TYPES = frozenset({
    BILLBOARD3D, RIBBON, PLANE, LIGHTNING, RIBBONBLADE, STRAINRIBBON, BILLBOARD2D,
    MESH, DUMMY, TUBELIGHT,
    PTBEHAVIOR,
    PTCOLLISION, PTLIFE,
    EXTERNREFERENCE,
})


def category_of(type_hash: int) -> str:
    """返回属性类型的顶层分类 slug；未登记类型归 'misc'。"""
    return ATTRIBUTE_CATEGORY_OF.get(type_hash, "misc")


def subgroup_of(type_hash: int) -> str:
    """返回属性类型的子组 slug；该分类不分子组或未登记则返回空串。"""
    return ATTRIBUTE_SUBGROUP_OF.get(type_hash, "")


def attribute_preset_relpath(type_hash: int) -> tuple:
    """返回属性预设的存盘路径分段（相对 __attributes__/），如
    ("skeleton",) 或 ("renderer_body", "uvs")；供 attribute_ops.py 拼存盘/扫描路径用。"""
    cat = category_of(type_hash)
    sub = subgroup_of(type_hash)
    return (cat, sub) if sub else (cat,)


def category_label(slug: str, lang: str = "ZH") -> str:
    """slug → 显示名（lang: 'EN'/'ZH'）；未知 slug 原样返回。"""
    entry = ATTRIBUTE_CATEGORY_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug


def subgroup_label(slug: str, lang: str = "ZH") -> str:
    """子组 slug → 显示名（lang: 'EN'/'ZH'）；未知 slug 原样返回。"""
    entry = ATTRIBUTE_SUBGROUP_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug


def renderer_suffix(type_hashes) -> str:
    """给定一个 entry 内属性的 type_hash 序列（原始顺序），返回显示名后缀，
    形如 " (Mesh)" / " (Ribbon, Dummy)" / " (ExternReference, Billboard3D, PtLife)"；
    不含 SUFFIX_DISPLAY_TYPES 里的属性时返回空串。

    供 Entry 显示名拼接用（不落盘，导入/重排/改名/增删属性时各自现算）。这套集合跟预设分类树
    （ATTRIBUTE_CATEGORY_OF/ATTRIBUTE_SUBGROUP_OF）彻底解耦——两者服务不同需求（"entry 该显示
    什么后缀信息" vs "预设该存哪个文件夹"），语义不对齐时不用互相牵连，见 SUFFIX_DISPLAY_TYPES
    定义处的判据说明。

    Renderer Body 在全量语料里基本互斥选一（BILLBOARD3D/RIBBON/MESH/PLANE/LIGHTNING 等
    0 例外），唯一会共存的是 DUMMY 搭配真实渲染体（全量仅 9 例，见
    docs/ATTRIBUTE_TYPES.md「渲染主体（互斥选一）」一节），故多个时直接逗号拼接即可，
    不需要更复杂的展示规则。排序不用额外处理：按 entry 内属性实际出现顺序过滤拼接，
    ExternReference 天然排最前、Renderer Body 天然排中间、Action Trigger/PtBehavior
    天然排最后。
    """
    from .hashes import HASH_TO_NAME, pretty_type_name
    names = []
    for type_hash in type_hashes:
        if type_hash not in SUFFIX_DISPLAY_TYPES:
            continue
        raw_name = HASH_TO_NAME.get(type_hash)
        if raw_name:
            names.append(pretty_type_name(raw_name))
    return " (%s)" % ", ".join(names) if names else ""
