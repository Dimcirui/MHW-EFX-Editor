"""
efx_format/categories.py  —  table of attribute type categories

Purpose: Group attribute types by function, for
  - two-level dropdown of attribute presets (first select category, then select attribute within category; some categories are further subdivided into subgroups)
  - saving attribute presets by category (presets/__attributes__/<slug>/[<subgroup>/]<NAME>.json)

key: type_hash. Non-registered types default to "misc" in ATTRIBUTE_CATEGORY_OF; 
only types that are further subdivided within their category have entries in ATTRIBUTE_SUBGROUP_OF.

Abstract of the category/subgroup structure (for reference):
  skeleton          — every entry must have
  extern_reference  — always first in entry
  renderer_body     — mutually exclusive; subgroups uvs/mesh/dummy/special (by host system)
  renderer_modifier — attached to body, stackable; subgroups uvs/mesh/dummy/generic
  spawn_method      — set at spawn time (EMITTERSHAPE3D/RAYCAST…)
  motion_visibility — frame-by-frame behavior; subgroups motion/visibility
  action_trigger    — trigger Action segments
  pt_behavior       — independent behavior system, mutually exclusive with regular rendering/physics workflows (PTBEHAVIOR)
  misc              — fallback category; subgroups post_process (screen post-processing filters) / others (insufficient evidence/pending classification)
  custom            — for user-defined preset
"""

from .hashes import (
    # Skeleton
    TRANSFORM3D, PARENTOPTIONS, SPAWN, LIFE, TRANSFORM2D,
    # ExternReference
    EXTERNREFERENCE,
    # Renderer Body
    BILLBOARD3D, RIBBON, PLANE, LIGHTNING, RIBBONBLADE, STRAINRIBBON, BILLBOARD2D,
    MESH, DUMMY, TUBELIGHT,
    # Renderer Modifier
    UVSEQUENCE, RGBFIRE, RGBWATER, ALPHACORRECTION, REFRACTION, BLINK, LUMINANCEBLEED,
    MATERIAL, UVCONTROL,
    PLEMISSIVE, PARENTEMISSIVE, PLSNOW, PARENTSNOW, OTOMOSNOW, PARENTMATERIAL,
    FAKEPLANE, SHADERSETTINGS,
    # Spawn Method
    EMITTERSHAPE3D, EMITTERSHAPEMESH, SPAWNBYANGLE, SPAWNBYOCCLUSION, RAYCAST, EMITTERSHAPE2D,
    # Motion & Visibility
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

# ── Top-level Categories (EN/ZH, ordered) ────────────────────
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

# ── Subgroup slugs → bilingual labels (same slug has same meaning across different top-level categories) ─
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

# ── type_hash → top-level category slug (unregistered types default to "misc") ─────────────
ATTRIBUTE_CATEGORY_OF = {
    # ── Entry Skeleton (every entry must have + 2D skeleton is merged) ─────────────────────────
    TRANSFORM3D:       "skeleton",
    PARENTOPTIONS:     "skeleton",
    SPAWN:             "skeleton",
    LIFE:              "skeleton",
    TRANSFORM2D:       "skeleton",   # 2D version of TRANSFORM3D

    # ── ExternReference ─────────────────────────
    EXTERNREFERENCE:   "extern_reference",

    # ── Renderer Body (mutually exclusive; subgroups see ATTRIBUTE_SUBGROUP_OF) ─────────────────────
    BILLBOARD3D:       "renderer_body",
    RIBBON:            "renderer_body",
    PLANE:             "renderer_body",
    LIGHTNING:         "renderer_body",
    RIBBONBLADE:       "renderer_body",
    STRAINRIBBON:      "renderer_body",
    BILLBOARD2D:       "renderer_body",   # 2D version of BILLBOARD3D
    MESH:              "renderer_body",
    DUMMY:             "renderer_body",   # 无视觉输出的功能性宿主（PTLIFE/SHOVEL/PLEMISSIVE 宿主）
    TUBELIGHT:         "renderer_body",

    # ── Renderer Modifier (attached to Body, stackable; subgroups see ATTRIBUTE_SUBGROUP_OF) ────────────
    UVSEQUENCE:        "renderer_modifier",
    RGBFIRE:           "renderer_modifier",   # 与 RGBWATER 互斥
    RGBWATER:          "renderer_modifier",   # 与 RGBFIRE 互斥
    ALPHACORRECTION:   "renderer_modifier",   # 与 MESH/UVCONTROL 完全不共存
    REFRACTION:        "renderer_modifier",
    BLINK:             "renderer_modifier",
    LUMINANCEBLEED:    "renderer_modifier",
    MATERIAL:          "renderer_modifier",   # 99.6% 与 MESH 共存；覆盖 mrl3 材质属性
    UVCONTROL:         "renderer_modifier",   # 100% 与 MESH 共存
    PLEMISSIVE:        "renderer_modifier",   # 宿主 100% 为 DUMMY
    PARENTEMISSIVE:    "renderer_modifier",   # 宿主 100% 为 DUMMY
    PLSNOW:            "renderer_modifier",
    PARENTSNOW:        "renderer_modifier",
    OTOMOSNOW:         "renderer_modifier",
    PARENTMATERIAL:    "renderer_modifier",
    FAKEPLANE:         "renderer_modifier",   # 跨宿主叠加渲染，99.8% 跟某个真渲染体共存，不互斥
    SHADERSETTINGS:    "renderer_modifier",   # 跨宿主：UVS系 100%/MESH 78.6%/DUMMY 43.8% 共现

    # ── Spawn Method (spawn at runtime) ────────────────────────────────────────────
    EMITTERSHAPE3D:    "spawn_method",
    EMITTERSHAPEMESH:  "spawn_method",
    SPAWNBYANGLE:      "spawn_method",
    SPAWNBYOCCLUSION:  "spawn_method",
    RAYCAST:           "spawn_method",
    EMITTERSHAPE2D:    "spawn_method",   # 2D version of EMITTERSHAPE3D

    # ── Motion & Visibility (per-frame behaviors; subgroups see ATTRIBUTE_SUBGROUP_OF) ─────────────────
    VELOCITY3D:        "motion_visibility",
    SCALEANIM:         "motion_visibility",
    ROTATEANIM:        "motion_visibility",
    NOISE:             "motion_visibility",
    TURBULENCE:        "motion_visibility",
    HOMING:            "motion_visibility",
    GUIDE:             "motion_visibility",
    PATHCHAIN:         "motion_visibility",
    VELOCITY2D:        "motion_visibility",   # 2D version of VELOCITY3D
    REPEATAREA:        "motion_visibility",   # 跟 VELOCITY3D 共现 91.9%，本质是运动/空间重复行为
    FADEBYDEPTH:       "motion_visibility",
    FADEBYANGLE:       "motion_visibility",
    FADEBYEMITTERANGLE:"motion_visibility",
    FADEBYOCCLUSION:   "motion_visibility",
    MASTERONLY:        "motion_visibility",
    EMITTERBOUNDARY:   "motion_visibility",   # 位置数据落尾部，逐帧边界判定而非生成时形状定义
    SCREENSPACECOLLISION: "motion_visibility",
    LINKPARTSVISIBLE:  "motion_visibility",

    # ── Action Trigger ──────────────────
    PTCOLLISION:       "action_trigger",
    PTLIFE:            "action_trigger",

    # ── PtBehavior（independent behavior system） ────────────────
    PTBEHAVIOR:        "pt_behavior",

    # ── Misc ──────────────────────────────
    FAKEDOF:           "misc",
    TONEMAPFILTER:     "misc",
    COLORCORRECTFILTER:"misc",
    RANDOMFIX:         "misc",
    CHECKPUREATTRIBUTE:"misc",
    LAYOUT:            "misc",
    PTTRIGGER:         "misc",   # looks like Action Trigger, but it doesn't call any Action segment
    SHOVEL:            "misc",
}

# ── type_hash → subgroup slug (only types that are further subdivided within their category have entries) ─
ATTRIBUTE_SUBGROUP_OF = {
    # ── Renderer Body Subgroups ────────────────────────────────────────────────────
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

    # ── Renderer Modifier Subgroups ────────────────────────────────────────────────
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

    # ── Motion and Visibility Subgroups ─────────────────────────────────────────────────────────
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

    # ── Misc Subgroups ────────────────────────────────────────────────────────────────
    FAKEDOF:            "post_process",
    TONEMAPFILTER:      "post_process",
    COLORCORRECTFILTER: "post_process",
    RANDOMFIX:          "others",
    CHECKPUREATTRIBUTE: "others",
    LAYOUT:             "others",
    PTTRIGGER:          "others",
    SHOVEL:             "others",
}

# ── Entry suffix display: UI/UX, for quickly seeing the key features of this entry ──
SUFFIX_DISPLAY_TYPES = frozenset({
    # Renderer Body
    BILLBOARD3D, RIBBON, PLANE, LIGHTNING, RIBBONBLADE, STRAINRIBBON, BILLBOARD2D,
    MESH, DUMMY, TUBELIGHT,
    # PtBehavior
    PTBEHAVIOR,
    # Action Trigger
    PTCOLLISION, PTLIFE,
    # ExternReference
    EXTERNREFERENCE,
})


def category_of(type_hash: int) -> str:
    """
    return the top-level category slug of the attribute type; unregistered types default to 'misc'.
    """
    return ATTRIBUTE_CATEGORY_OF.get(type_hash, "misc")


def subgroup_of(type_hash: int) -> str:
    """
    return the subgroup slug of the attribute type; returns an empty string if the category has no subgroups or the type is not registered.
    """
    return ATTRIBUTE_SUBGROUP_OF.get(type_hash, "")


def attribute_preset_relpath(type_hash: int) -> tuple:
    """
    return the relative path segments for the attribute preset (relative to __attributes__/), e.g.,
    ("skeleton",) or ("renderer_body", "uvs"); for use in attribute_ops.py to construct save/scan paths.
    """
    cat = category_of(type_hash)
    sub = subgroup_of(type_hash)
    return (cat, sub) if sub else (cat,)


def category_label(slug: str, lang: str = "ZH") -> str:
    """
    slug → display name (lang: 'EN'/'ZH'); unknown slug returns as-is.
    """
    entry = ATTRIBUTE_CATEGORY_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug


def subgroup_label(slug: str, lang: str = "ZH") -> str:
    """
    subgroup slug → display name (lang: 'EN'/'ZH'); unknown slug returns as-is.
    """
    entry = ATTRIBUTE_SUBGROUP_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug

# for quickly seeing the key features of this entry
def renderer_suffix(type_hashes) -> str:
    """
    Given a sequence of type_hashes within an entry (in original order), return a display name suffix,
    e.g., " (Mesh)" / " (Ribbon, Dummy)" / " (ExternReference, Billboard3D, PtLife)";
    returns an empty string if none of the types are in SUFFIX_DISPLAY_TYPES.
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
