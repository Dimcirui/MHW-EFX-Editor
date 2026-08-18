# -*- coding: utf-8 -*-
"""
blender_efx/layout_model.py — 字段行布局的**纯逻辑**：配对、轴组、顺序订正、常用/高级分档。

⚠ **本模块零 import**（连 bpy 都不碰），这样 `tools/ui_layout_sim.py` 才能在命令行里
按文件路径加载它、拿全语料跑自检——`panels.py` 里 `import bpy`，CLI 进不去。
同样的手法已经用在 `field_labels.py` / `field_visibility.py` 上。

**为什么非要能在 CLI 里跑**：这一层完全不经过 `roundtrip.py` / `field_roundtrip.py`
两套测试的路径（见 CLAUDE.md §3 的告诫）。2026-08-18 那张错的属性顺序表把 52% 的官方
文件排成错误顺序，两套 CLI 测试全绿——就是因为没人能在 Blender 外面跑这一层。

数据表（`FIELD_ORDER_ANCHORS` / `ADVANCED_FIELDS`）不在这里 import，一律**由调用方注入**，
以保持零依赖。`panels.py` 那两个同名包装函数负责查表并转调。

这里只认 item 的两个属性：`.ori_name` 和 `.data_type`（鸭子类型）——自检脚本因此可以
拿最简单的假对象喂进来。
"""


# 可配对的标量 dtype → 其值控件属性名（value+jitter 同行显示用）
SCALAR_PROP_ATTR = {
    "FLOAT":  "float_value",
    "INT":    "int_value",
    "UINT":   "uint_str",
    "BYTE1":  "byte1_value",
    "SHORT1": "short1_value",
}


# 不符合 Jitter 后缀约定、但语义上是抖动字段的名称（MESH 的 _j 后缀字段）
# SPAWN 原 randomizedSpawnsPerFrame/randomizedDelay/randomizedLifespan/occur2 已改名为标准
# XJitter 后缀（2026-07-26 实机测试后重命名），不再需要在此特例登记。
NONSTANDARD_JITTER_NAMES = frozenset({
    "emissive_saturation_j",
    "emissive_brightness_j",
})


def is_jitter_name(name: str) -> bool:
    """字段名是否为 jitter（camelCase 'XJitter' / snake 'x_jitter' / 非标准后缀特例）。"""
    return name.endswith("Jitter") or name.endswith("_jitter") or name in NONSTANDARD_JITTER_NAMES


def is_matching_jitter(base_name: str, candidate_name: str) -> bool:
    """candidate_name 是否确实是 base_name 的 jitter 搭档（按名字派生关系判断，而非仅仅
    "长得像 jitter"）。原来的相邻位置配对只检查下一个字段是否为任意 jitter 名，未核对是否
    真的由 base_name 派生——当 value/jitter 在字节布局里不相邻（如 RIBBON 的
    rotationYJitter 排在 rotationY 前面，见 ribbon-family 相关 schema 注释）时，会错误地把
    下一个无关的 jitter 字段（如 rotationZJitter）配对给当前字段（rotationY），2026-07-30 修复。"""
    return candidate_name in (base_name + "Jitter", base_name + "_jitter", base_name + "_j")


# ─────────────────────────────────────────────────────────────────────────────
# 虚拟轴向组合控件（用户 2026-07-26 提议）：部分类型的 X/Y/(Z) 分量因各轴实测语义不完全
# 对称（如 ROTATEANIM.spinSpeedCoef 系列错位重构后拆成独立标量），无法用真正的 XYZ
# 复合类型（FLOAT6/FLOAT3/INT3）表示，只能各轴各自建标量字段。这里在 UI 层把它们重新
# 拼成跟 FLOAT6 同款的标题行 + 逐轴行显示——纯展示层分组，不改 schema/字节布局。
#
# 结构：type_name -> [ (title_key, [(axis_label, base_field_name), ...]), ... ]
#   title_key      友好名来源（过 _friendly_name 转换/中文标签表）
#   axis_label     行首标签（"X"/"Y"/"Z"）
#   base_field_name 该轴的 value 字段名；若存在 "<name>Jitter" 字段则自动配对成 Static/Random，
#                   否则单值显示（跟 FLOAT3/INT3 一样只有 X/Y/Z 无静态随机之分）。
# ─────────────────────────────────────────────────────────────────────────────
AXIS_GROUPS: dict = {
    "ROTATEANIM": [
        ("spinSpeedCoef", [("X", "spinSpeedCoefX"), ("Y", "spinSpeedCoefY"), ("Z", "spinSpeedCoefZ")]),
    ],
    "TRANSFORM2D": [
        ("offset", [("X", "offsetX"), ("Y", "offsetY")]),
        ("scale",  [("X", "scaleX"),  ("Y", "scaleY")]),
    ],
    "VELOCITY2D": [
        ("velocity",   [("X", "velocityX"),   ("Y", "velocityY")]),
        ("divergence", [("X", "divergenceX"), ("Y", "divergenceY")]),
    ],
    "VELOCITY3D": [
        ("rotation",   [("X", "rotationX"),   ("Y", "rotationY"),   ("Z", "rotationZ")]),
        ("velocity",   [("X", "velocityX"),   ("Y", "velocityY"),   ("Z", "velocityZ")]),
        ("divergence", [("X", "divergenceX"), ("Y", "divergenceY"), ("Z", "divergenceZ")]),
    ],
    "EMITTERSHAPE3D": [
        ("localRotation", [("X", "localRotationX"), ("Y", "localRotationY"), ("Z", "localRotationZ")]),
    ],
    "EMITTERSHAPE2D": [
        ("range", [("X", "rangeX"), ("Y", "rangeY")]),
    ],
    "SCALEANIM": [
        ("scaleSpeed", [("X", "scaleSpeedX"), ("Y", "scaleSpeedY"), ("Z", "scaleSpeedZ")]),
        ("scaleAccel", [("X", "scaleAccelX"), ("Y", "scaleAccelY"), ("Z", "scaleAccelZ")]),
    ],
    # RIBBON 的 rotationX/Y/Z：字节布局里 Y/Z 两组的 value/jitter 顺序是反的（rotationYJitter
    # 排在 rotationY 前面，rotationZJitter 排在 rotationZ 前面），相邻位置配对逻辑找不到，
    # 靠这里按名字查找而非位置的分组机制正确显示，2026-07-30。
    "RIBBON": [
        ("rotation", [("X", "rotationX"), ("Y", "rotationY"), ("Z", "rotationZ")]),
    ],
}


def resolve_axis_groups(type_name: str, item_by_name: dict):
    """把 AXIS_GROUPS 里该类型的分组规格解析成可绘制的形式；缺字段（如 custom 变体裁剪过）
    的分组整体跳过。返回 (group_first_name -> group_spec 字典, 全部被消费的字段名 set)。"""
    group_render_at = {}
    consumed = set()
    for title_key, axes in AXIS_GROUPS.get(type_name, []):
        names = []
        ok = True
        for _axis_label, base in axes:
            if base not in item_by_name:
                ok = False
                break
            names.append(base)
            jn = base + "Jitter"
            if jn in item_by_name:
                names.append(jn)
        if not ok:
            continue
        group_render_at[names[0]] = (title_key, axes)
        consumed.update(names)
    return group_render_at, consumed


def reorder_units(items, anchors: dict):
    """按锚点表订正字段显示顺序，返回重排后的列表；`anchors` = {字段: 画到哪个字段之后}。

    **默认原样返回**——字节序本来就是语义序（见 `efx_format/field_order.py` 的说明），
    这里只搬少数确实错位的行，典型是 `useColorRange` 被甩在它管的 `colorRange` 十几行之后。

    搬动以「行」为单位：value+jitter 先合成一个单元再整体移动，锚点带 jitter 时也落在
    它那一对之后，不会把配对拆散。表写错导致落不了位（比如锚点成环）时**整体退回原顺序**，
    宁可不排也不半排。⚠ 只影响显示：`field_items` 本身没动，导出仍按字节序重建。
    """
    if not anchors:
        return list(items)

    units = build_units(items)
    lead_at = dict((u[0].ori_name, k) for k, u in enumerate(units))
    # 字段或锚点在这个变体里不存在（custom 变体会裁字段）就跳过该条，不是错误
    moves = dict((f, a) for f, a in anchors.items()
                 if f in lead_at and a in lead_at and f != a)
    if not moves:
        return list(items)

    rest = [u for u in units if u[0].ori_name not in moves]
    pending = dict((f, units[lead_at[f]]) for f in moves)
    # 反复插入以支持链式锚点（A 挂 B、B 挂 C）
    changed = True
    while pending and changed:
        changed = False
        for f in list(pending):
            target = moves[f]
            pos = next((k for k, u in enumerate(rest)
                        if u[0].ori_name == target), None)
            if pos is None:
                continue
            rest.insert(pos + 1, pending.pop(f))
            changed = True
    if pending:
        return list(items)   # 有落不了位的（成环）→ 整体退回，不半排
    return [it for u in rest for it in u]


def build_units(items):
    """把字段列表切成「行」：value+jitter 合成一个单元，其余各自成单元。

    配对判据以**名字派生关系**为主（`is_matching_jitter`），dtype 相等只是次要门槛。
    """
    units = []
    i, n = 0, len(items)
    while i < n:
        it = items[i]
        nxt = items[i + 1] if i + 1 < n else None
        if is_pair(it, nxt):
            units.append([it, nxt])
            i += 2
        else:
            units.append([it])
            i += 1
    return units


def is_pair(it, nxt) -> bool:
    """`it` 与紧随其后的 `nxt` 是否是同一行的 value + jitter。"""
    return (nxt is not None
            and it.data_type in SCALAR_PROP_ATTR
            and not is_jitter_name(it.ori_name)
            and not it.ori_name.startswith("__")
            and nxt.data_type == it.data_type
            and is_matching_jitter(it.ori_name, nxt.ori_name))


def classify_tiers(items, tier_set, axis_group_at: dict, axis_group_consumed):
    """把字段分成「常用」/「高级」两档，返回 (高级组首名 set, 高级跟随成员名 set)。

    `tier_set` = 该类型归入高级的字段名集合（`efx_format/field_tiers.py` 语料生成）。
    **只影响显示不影响导出**——高级区里的字段照常可编辑，导出走的还是同一套
    `rebuild_data_bytes`。

    定档以「一行」为单位而非单个字段：value+jitter 配对由 value 定档（jitter 从不单独
    成行），轴组要全部基字段都是高级才整组下沉。否则会出现半行在常用区、半行在折叠区的
    割裂感——`objectInteractionFlag0..3` 这种编号兄弟组的拉齐则在生成脚本里做掉了。
    """
    if not tier_set:
        return set(), set()

    lead, follow = set(), set()
    n = len(items)
    i = 0
    while i < n:
        name = items[i].ori_name
        if name in axis_group_consumed and name not in axis_group_at:
            i += 1
            continue
        if name in axis_group_at:
            bases = [b for _label, b in axis_group_at[name][1]]
            if bases and all(b in tier_set for b in bases):
                lead.add(name)
                follow.update(x for x in axis_group_consumed if x != name)
            i += 1
            continue
        nxt = items[i + 1] if i + 1 < n else None
        paired = is_pair(items[i], nxt)
        if name in tier_set:
            lead.add(name)
            if paired:
                follow.add(nxt.ori_name)
        i += 2 if paired else 1
    return lead, follow


def all_rows_advanced(items, lead, follow, is_hidden) -> bool:
    """常用区会不会一行都没有——即所有没被隐藏的字段都归了「高级」。

    `is_hidden(name)` 由调用方注入：哨兵 / 保留填充位 / 模式门控 / Color Editor 过滤。

    这种类型（`DUMMY` / `MASTERONLY` / `PATHCHAIN` / `FAKEPLANE` … 字段全是占位名的那些，
    全语料 12 种）折叠没有意义：藏起来面板上就只剩一个孤零零的「高级 (N)」，看着像坏了。
    调用方据此**放弃折叠、直接内联画**——反正也没有常用字段需要跟它们区分。
    """
    if not lead:
        return False
    for it in items:
        name = it.ori_name
        if name in lead or name in follow:
            continue
        if is_hidden(name):
            continue
        return False
    return True
