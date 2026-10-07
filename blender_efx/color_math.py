"""Color Tool 的色彩运算与按 Entry 的改色规划，不依赖 bpy。

Entry 内颜色按角色分组：
- ``render``：渲染体颜色；
- ``layer``：RGBFIRE / RGBWATER 颜色，与渲染体颜色相乘；
- ``other``：其余颜色，各自独立。

颜色可以来自静态字段，也可以来自 TIML 关键帧；TIML 值取代静态值，两者按同样规则处理。

规则：
- 同时有渲染体和染色层：按乘积（有效颜色）运算，渲染体改为中性灰，结果写进染色层。
- 挂 REFRACTION：染色层不生效，保持不动；渲染体全为中性色时整 Entry 跳过，
  否则渲染体按独立颜色处理。
"""

import colorsys
import math

RENDER, LAYER, OTHER = "render", "layer", "other"
SHIFT, ALIGN, REPLACE, REPLACE_KEEP_V = "shift", "align", "replace", "replace_keep_v"

# HSV 饱和度低于此值视为中性色（白-灰-黑）。
NEUTRAL_SAT = 0.05


def is_neutral(rgb):
    _h, s, _v = colorsys.rgb_to_hsv(*rgb)
    return s < NEUTRAL_SAT


def dominant_hue(colors):
    """返回按 S×V 加权的圆周平均色相；全中性时返回 None。"""
    sx = sy = 0.0
    for r, g, b in colors:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        w = s * v
        if w <= 0.0:
            continue
        ang = h * 2.0 * math.pi
        sx += w * math.cos(ang)
        sy += w * math.sin(ang)
    if sx == 0.0 and sy == 0.0:
        return None
    return (math.atan2(sy, sx) / (2.0 * math.pi)) % 1.0


def rotate_hue(rgb, delta):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb((h + delta) % 1.0, s, v)


def set_hue(rgb, hue):
    _h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb(hue, s, v)


def _mul(a, b):
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


def _clamp01(rgb):
    return tuple(min(1.0, max(0.0, c)) for c in rgb)


def _classify(entry):
    """返回 (方式, 主渲染色序号)；方式为 'skip' / 'layered' / 'plain'。"""
    refraction, items = entry
    render = [i for i, (role, _rgb) in enumerate(items) if role == RENDER]
    layers = [i for i, (role, _rgb) in enumerate(items) if role == LAYER]
    if refraction:
        if render and all(is_neutral(items[i][1]) for i in render):
            return "skip", None
        return "plain", None
    if render and layers:
        # 渲染体颜色有关键帧时乘积随时间变化，取最亮的一个作代表。
        main = max(render, key=lambda i: max(items[i][1]))
        if max(items[main][1]) > 0.0:
            return "layered", main
    return "plain", None


def is_skipped(entry):
    """Entry 是否整体不参与改色（中性扭曲）。"""
    return _classify(entry)[0] == "skip"


def effective_colors(entries):
    """收集决定主色相的可见颜色。"""
    out = []
    for entry in entries:
        refraction, items = entry
        mode, main = _classify(entry)
        if mode == "skip":
            continue
        if mode == "layered":
            m = items[main][1]
            out.extend(_mul(m, rgb) for role, rgb in items if role == LAYER)
            out.extend(rgb for role, rgb in items if role == OTHER)
            continue
        for role, rgb in items:
            if role == LAYER and refraction:
                continue
            out.append(rgb)
    return out


def entry_lightness(entry):
    """Entry 可见颜色的平均明度；没有可见颜色时返回 None。"""
    colors = effective_colors([entry])
    if not colors:
        return None
    return sum(max(c) for c in colors) / len(colors)


def pick_white(entries, ratio, by_lightness, rng):
    """按比例挑出改白的 Entry 序号。

    by_lightness 为真时取原来最亮的那部分，否则随机挑；没有可见颜色的 Entry 不参与。
    """
    idx = [i for i, e in enumerate(entries) if entry_lightness(e) is not None]
    k = int(round(len(idx) * min(1.0, max(0.0, ratio))))
    if by_lightness:
        idx.sort(key=lambda i: entry_lightness(entries[i]), reverse=True)
    else:
        rng.shuffle(idx)
    return set(idx[:k])


def plan_recolor(entries, op, target_rgb, delta=0.0):
    """为每个颜色返回新 RGB，不改的为 None。

    entries：[(是否挂 REFRACTION, [(角色, (r, g, b)), ...]), ...]
    op：SHIFT 时按 delta 旋转色相；ALIGN 对齐到目标色相；REPLACE 直接替换；
    REPLACE_KEEP_V 换成目标色的色相和饱和度，保留各自明暗。
    """
    target_hue, target_sat, _tv = colorsys.rgb_to_hsv(*target_rgb)

    def apply(rgb):
        if op == SHIFT:
            return rotate_hue(rgb, delta)
        if op == ALIGN:
            return set_hue(rgb, target_hue)
        if op == REPLACE_KEEP_V:
            return colorsys.hsv_to_rgb(target_hue, target_sat, max(rgb))
        return tuple(target_rgb)

    plan = []
    for entry in entries:
        refraction, items = entry
        mode, main = _classify(entry)
        out = [None] * len(items)
        if mode == "layered":
            m = items[main][1]
            gm = max(m)
            for i, (role, rgb) in enumerate(items):
                if role == RENDER:
                    if op == REPLACE:
                        out[i] = (1.0, 1.0, 1.0)
                    else:
                        g = max(rgb)
                        out[i] = (g, g, g)
                elif role == LAYER:
                    if op == REPLACE:
                        out[i] = tuple(target_rgb)
                    else:
                        e = apply(_mul(m, rgb))
                        out[i] = _clamp01(tuple(c / gm for c in e))
                else:
                    out[i] = apply(rgb)
        elif mode == "plain":
            for i, (role, rgb) in enumerate(items):
                if role == LAYER and refraction:
                    continue
                out[i] = apply(rgb)
        plan.append(out)
    return plan
