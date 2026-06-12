"""
efx_format/categories.py  —  块类型的功能分类表（纯 Python，零 bpy 依赖）

用途：把几十种块类型按功能分组，供
  - 块预设的两级下拉（先选分类，再选类内块）
  - 块预设按分类存盘（presets/__blocks__/<slug>/<NAME>.json）
两处共用同一份分类事实，避免重复。

分组依据见 docs/BLOCK_TYPES.md。键为 type_hash（来自 hashes.py），
未登记的类型一律归入 "misc"。
"""

from .hashes import (
    TRANSFORM3D, PARENTOPTIONS, SCALEANIM, ROTATEANIM,
    SPAWN, EMITTERSHAPE3D, EMITTERSHAPE2D, LIFE, EMITTERBOUNDARY,
    VELOCITY3D, TURBULENCE, NOISE, HOMING, GUIDE, RAYCAST, SCREENSPACECOLLISION,
    BILLBOARD3D, PLANE, RIBBON, RIBBONBLADE, STRAINRIBBON, MESH, LIGHTNING, MATERIAL,
    UVSEQUENCE, UVCONTROL, ALPHACORRECTION, SHADERSETTINGS, RGBFIRE, RGBWATER,
    BLINK, LUMINANCEBLEED, REFRACTION,
    FADEBYDEPTH, FADEBYANGLE, FADEBYEMITTERANGLE,
    PLEMISSIVE, PARENTEMISSIVE, PLSNOW,
    PTCOLLISION, PTLIFE, PTBEHAVIOR,
    EXTERNREFERENCE,
    MASTERONLY, DUMMY, RANDOMFIX, SHOVEL,
)

# ── slug → 双语显示名（下拉顺序按本 dict 的插入顺序）────────────────────────────
# 纯数据：EN + ZH 都存这里，UI 层（blender_efx/i18n.py）按当前语言取用。
BLOCK_CATEGORY_LABELS = {
    "transform": {"EN": "Transform/Anim",   "ZH": "变换/动画"},
    "emitter":   {"EN": "Emitter/Spawn",    "ZH": "发射器/生成"},
    "motion":    {"EN": "Motion/Velocity",  "ZH": "运动/速度"},
    "render":    {"EN": "Render/Sprite",    "ZH": "渲染/面片"},
    "color":     {"EN": "Color/Shading",    "ZH": "颜色/着色"},
    "fade":      {"EN": "Fade/Cull",        "ZH": "渐隐/剔除"},
    "player":    {"EN": "Player/Char Glow", "ZH": "玩家/角色光效"},
    "physics":   {"EN": "Physics/Collision","ZH": "物理/碰撞"},
    "reference": {"EN": "Reference/Extern", "ZH": "引用/外部"},
    "misc":      {"EN": "Global/Misc",      "ZH": "全局/特殊"},
}

# ── type_hash → slug ──────────────────────────────────────────────────────────
BLOCK_CATEGORY_OF = {
    # 变换/动画
    TRANSFORM3D: "transform", PARENTOPTIONS: "transform",
    SCALEANIM: "transform", ROTATEANIM: "transform",
    # 发射器/生成
    SPAWN: "emitter", EMITTERSHAPE3D: "emitter", EMITTERSHAPE2D: "emitter",
    LIFE: "emitter", EMITTERBOUNDARY: "emitter",
    # 运动/速度
    VELOCITY3D: "motion", TURBULENCE: "motion", NOISE: "motion", HOMING: "motion",
    GUIDE: "motion", RAYCAST: "motion", SCREENSPACECOLLISION: "motion",
    # 渲染/面片
    BILLBOARD3D: "render", PLANE: "render", RIBBON: "render", RIBBONBLADE: "render",
    STRAINRIBBON: "render", MESH: "render", LIGHTNING: "render", MATERIAL: "render",
    # 颜色/着色
    UVSEQUENCE: "color", UVCONTROL: "color", ALPHACORRECTION: "color",
    SHADERSETTINGS: "color", RGBFIRE: "color", RGBWATER: "color",
    BLINK: "color", LUMINANCEBLEED: "color", REFRACTION: "color",
    # 渐隐/剔除
    FADEBYDEPTH: "fade", FADEBYANGLE: "fade", FADEBYEMITTERANGLE: "fade",
    # 玩家/角色光效
    PLEMISSIVE: "player", PARENTEMISSIVE: "player", PLSNOW: "player",
    # 物理/碰撞
    PTCOLLISION: "physics", PTLIFE: "physics", PTBEHAVIOR: "physics",
    # 引用/外部
    EXTERNREFERENCE: "reference",
    # 全局/特殊
    MASTERONLY: "misc", DUMMY: "misc", RANDOMFIX: "misc", SHOVEL: "misc",
}


def category_of(type_hash: int) -> str:
    """返回块类型的分类 slug；未登记类型归 'misc'。"""
    return BLOCK_CATEGORY_OF.get(type_hash, "misc")


def category_label(slug: str, lang: str = "ZH") -> str:
    """slug → 显示名（lang: 'EN'/'ZH'）；未知 slug 原样返回。"""
    entry = BLOCK_CATEGORY_LABELS.get(slug)
    if entry is None:
        return slug
    return entry.get(lang) or entry.get("EN") or slug
