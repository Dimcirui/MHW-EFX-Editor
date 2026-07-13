"""
blender_efx/validate.py  —  L2 #4：导出前校验（仿 mrl3 checkMrl3Error）

提供：
  validate_efx_tree(root_obj) -> list[dict]  纯函数，扫描对象树返回问题列表
  EFX_OT_validate                            校验算子（efx.validate），弹窗显示问题

问题项结构：{"level": "ERROR"|"WARN", "msg": str, "obj": str}

检查项
------
(1) 悬空指针（删除被引用对象后产生）—— **WARN**（category="dangling"），导出端安全跳过、不挡导出：
    - Subselect 成员 member.body_ptr is None
    - Action targets target.body_ptr is None
    - ExternReference extern_ref_ptr is None（pointerized && !none）
    悬空指针不再 ERROR：导出端各 export_* 早已对 None 指针安全跳过/回退（subselect/action
    直接 skip，extern 原样保留旧字节）。降级为 WARN + 导出时报告即可，不应仅因引用悬空
    就阻断导出。
    PtLife.relation_play_ptr / PtCollision.ie_play_ptr **不**在此列——2026-07 简化后 None
    是这两个字段的正常合法状态（无目标），导出时自动写 -1，不再是需要提醒的"悬空"。
(1b) EOF 异常归属（per_entry 模型，Entry 下 Direct Trigger / Not Direct Trigger 两个
    对称子集合）—— WARN，两种情况：
    - 双重挂载（category="eof_dual_membership"）：同一 entry 同时 link 在两个子集合里。
      只有手动 Ctrl+drag 追加链接才会出现，正常切换/拖拽是互斥移动。导出以 Direct
      Trigger 为准（entry 仍算作直接触发）。
    - 孤儿（category="eof_orphan_entry"）：entry 不在任何一个子集合里，误留在 Entry
      叶子集合直接子级（拖拽失误）。导出 fail-safe 视为直接触发（宁可多触发不漏触发）。
    两者都只是提醒用户清理，不挡导出。
(3) 死属性 EXTERNREFERENCE（count_extern==0 却仍 pointerized）—— WARN（合法历史模式）
(5k) standard/extended entry 零属性 —— WARN（提示性；io_tree.py §4a0 已自动从导出剔除这类
     残留空壳，这里只是提醒用户手动清理场景里的对象；见该检查项内联注释）

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集
  - 不改 efx_format/，不改 io_tree.py
  - 所有属性访问 getattr + try/except 防御（对象可能未初始化对应 PropertyGroup）
"""

import bpy

from .operators import _find_efx_root
from .i18n import T
from . import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 工具：收集子对象
# ─────────────────────────────────────────────────────────────────────────────

def _children_by_type(parent_obj, type_tag: str) -> list:
    """
    收集 parent_obj 下 ~TYPE == type_tag 的对象。
    parent_obj 是顶层文件集合（Collection，entry/action/extern/subselect 场景）时走
    集合归属收集；是 EFX_ENTRY 对象（attribute 场景）时走原 parent 收集（不受
    ROOT 集合化影响）。
    """
    if isinstance(parent_obj, bpy.types.Collection):
        return _rc.collect_top_level(parent_obj, type_tag)
    return [
        o for o in bpy.data.objects
        if o.parent == parent_obj and o.get("~TYPE") == type_tag
    ]


def _build_trigger_graph(bodies, plays):
    """构建召唤触发有向图，返回 {obj: set(obj)} 邻接表。

    边方向 = 召唤/触发方向：
      Action → entry ：play.efx_play.entries[].targets[].body_ptr （action 生成 entry）
      entry  → Action ：PTLIFE.relation_play_ptr / PTCOLLISION.ie_play_ptr （entry 触发 action）

    只保留终点也在本 root 节点集内的边（指针经 poll 已限定同文件，外指针忽略）。
    """
    node_set = set(bodies) | set(plays)
    adj = {n: set() for n in node_set}

    # Action → entry
    for play in plays:
        pp = getattr(play, "efx_play", None)
        if pp is None:
            continue
        try:
            entries = pp.entries
        except AttributeError:
            continue
        for entry in entries:
            try:
                targets = entry.targets
            except AttributeError:
                continue
            for t in targets:
                try:
                    tgt = t.body_ptr
                except AttributeError:
                    continue
                if tgt in node_set:
                    adj[play].add(tgt)

    # entry → Action
    for body in bodies:
        for blk in _children_by_type(body, "EFX_ATTRIBUTE"):
            pl = getattr(blk, "efx_ptlife_ref", None)
            if pl is not None:
                try:
                    if pl.relation_play_ptr in node_set:
                        adj[body].add(pl.relation_play_ptr)
                except AttributeError:
                    pass
            pc = getattr(blk, "efx_ptcollision_ref", None)
            if pc is not None:
                try:
                    if pc.ie_play_ptr in node_set:
                        adj[body].add(pc.ie_play_ptr)
                except AttributeError:
                    pass

    return adj


def _find_cycles(adj):
    """在邻接表上找有向环，返回去重后的环列表（每环是 obj 名字列表）。

    DFS + 递归栈回边检测；环按"最小名字旋转到首位"规范化去重。
    """
    cycles = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack = []

    def _norm(path):
        # path 是构成环的节点序列；旋转使字典序最小的节点在首位
        names = [o.name for o in path]
        k = names.index(min(names))
        return tuple(names[k:] + names[:k])

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, ()):  # 邻接确定性可不排序；环集去重
            if color[v] == GRAY:
                # 回边：栈中从 v 到栈顶构成一个环
                idx = stack.index(v)
                cycles.add(_norm(stack[idx:]))
            elif color[v] == WHITE:
                dfs(v)
        stack.pop()
        color[u] = BLACK

    for n in adj:
        if color[n] == WHITE:
            dfs(n)
    return [list(c) for c in cycles]


def _is_extern_ref_attribute(obj) -> bool:
    """判断属性对象是否是已指针化的 EXTERNREFERENCE（有 efx_extern_ref 且 pointerized）。"""
    props = getattr(obj, "efx_extern_ref", None)
    if props is None:
        return False
    try:
        return bool(props.extern_ref_pointerized)
    except AttributeError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 核心校验函数
# ─────────────────────────────────────────────────────────────────────────────

def validate_efx_tree(root_obj) -> list:
    """
    扫描 root_obj 对象树，返回问题列表。

    返回
    ----
    list[dict]：每项 {"level": "ERROR"|"WARN", "msg": str, "obj": str}。
                空列表表示无问题。
    """
    problems = []
    if root_obj is None:
        problems.append({
            "level": "ERROR",
            "msg": "EFX_ROOT object not found",
            "obj": "",
        })
        return problems

    # 段对象集合
    bodies     = _children_by_type(root_obj, "EFX_ENTRY")
    plays      = _children_by_type(root_obj, "EFX_ACTION")
    externs    = _children_by_type(root_obj, "EFX_EXTERN")
    subselects = _children_by_type(root_obj, "EFX_SUBSELECT")
    count_extern = len(externs)

    # ── (1) 悬空指针 ─────────────────────────────────────────────────────────

    # Subselect 成员
    for ss in subselects:
        ss_props = getattr(ss, "efx_subselect", None)
        if ss_props is None:
            continue
        try:
            members = ss_props.members
        except AttributeError:
            continue
        for i, member in enumerate(members):
            try:
                if member.body_ptr is None:
                    problems.append({
                        "level": "WARN",
                        "category": "dangling",
                        "msg": f"Subselect '{ss.name}' member {i} has a dangling pointer (skipped on export)",
                        "obj": ss.name,
                    })
            except AttributeError:
                continue

    # Action targets（结构：efx_play.entries[].targets[].body_ptr）
    for play in plays:
        play_props = getattr(play, "efx_play", None)
        if play_props is None:
            continue
        try:
            entries = play_props.entries
        except AttributeError:
            continue
        for ei, entry in enumerate(entries):
            try:
                targets = entry.targets
            except AttributeError:
                continue
            for ti, target in enumerate(targets):
                try:
                    if target.body_ptr is None:
                        problems.append({
                            "level": "WARN",
                            "category": "dangling",
                            "msg": (
                                f"Action '{play.name}' entry {ei} target {ti} "
                                f"has a dangling pointer (skipped on export)"
                            ),
                            "obj": play.name,
                        })
                except AttributeError:
                    continue

    # 遍历全部属性（EFX_ATTRIBUTE）做引用检查
    for body in bodies:
        for blk in _children_by_type(body, "EFX_ATTRIBUTE"):
            # ExternReference 悬空
            er = getattr(blk, "efx_extern_ref", None)
            if er is not None:
                try:
                    if (er.extern_ref_pointerized
                            and not er.extern_ref_none
                            and er.extern_ref_ptr is None):
                        problems.append({
                            "level": "WARN",
                            "category": "dangling",
                            "msg": (
                                f"ExternReference attribute '{blk.name}' has a dangling pointer"
                                " (the referenced Extern was deleted; original index bytes kept on export)"
                            ),
                            "obj": blk.name,
                        })
                    # (3) 死属性 WARN：count_extern==0 却仍 pointerized
                    if er.extern_ref_pointerized and count_extern == 0:
                        problems.append({
                            "level": "WARN",
                            "msg": (
                                f"ExternReference attribute '{blk.name}' is still pointerized, "
                                "but the file has no Extern segment (count_extern=0, legal legacy dead attribute)"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

            # PtLife.relation_play_ptr / PtCollision.ie_play_ptr：None 是正常的"无目标"
            # 状态（2026-07 简化，见文件头说明），导出时自动写 -1，不再检查/报告悬空。

    # EOF 异常归属：per_entry 模型下 entry 应恰好属于 Direct Trigger / Not Direct
    # Trigger 两个子集合之一。正常切换/拖拽是互斥移动，不会产生异常；只有手动
    # Ctrl+drag 追加链接（双重挂载）或误把 entry 落在 Entry 叶子集合直接子级
    # （孤儿）才会出现 —— 见 (1b) 说明。
    if str(root_obj.get("eof_model", "")) == "per_entry":
        dt_col = _rc.get_direct_trigger_collection(root_obj)
        ndt_col = _rc.get_not_direct_trigger_collection(root_obj)
        for b in bodies:
            in_dt = dt_col is not None and dt_col in b.users_collection
            in_ndt = ndt_col is not None and ndt_col in b.users_collection
            if in_dt and in_ndt:
                problems.append({
                    "level": "WARN",
                    "category": "eof_dual_membership",
                    "msg": (
                        f"Entry '{b.name}' is linked into both Direct Trigger and "
                        "Not Direct Trigger — treated as triggered (Direct Trigger wins) on export"
                    ),
                    "obj": b.name,
                })
            elif not in_dt and not in_ndt:
                problems.append({
                    "level": "WARN",
                    "category": "eof_orphan_entry",
                    "msg": (
                        f"Entry '{b.name}' is not in either Direct Trigger or Not Direct "
                        "Trigger (left directly under the Entry collection) — treated as "
                        "triggered (fail-safe) on export"
                    ),
                    "obj": b.name,
                })

    # efx_index 重复（如原生 Shift+D 复制后新旧对象撞号）不检查——已确认无害：
    # 导出端从不直接按存储的 efx_index 写字节位置，而是先按 efx_index 排序
    # （Python 稳定排序，撞号只影响并列时的相对顺序）再用 enumerate() 位置重算
    # 真正的段局部 index（entry/action/extern/subselect 均如此，见 io_tree.py
    # 的 collect_top_level → enumerate 模式）；attribute 更进一步——字节格式里
    # 根本没有 index 字段，序列化顺序就是列表顺序。曾经在此报 ERROR 挡导出，
    # 但这恰恰是原生复制的正常产物，不该拦——已移除。

    # ── (4) 召唤回绕（entry↔action 触发图成环）—— WARN ────────────────────────────
    # entry 的 PTLIFE/PTCOLLISION 触发 Action，Action 的 targets 又指回（祖先）entry，
    # 形成递归召唤 → 每轮按扇出倍增（如 12→144→1728…）直接卡死游戏。
    # 仅警告、不挡导出：保留刻意 loop 的自由，由用户判断该环是否有界。
    try:
        adj = _build_trigger_graph(bodies, plays)
        for cyc in _find_cycles(adj):
            problems.append({
                "level": "WARN",
                "msg": (
                    "Spawn cycle detected (entry↔action recursive summoning, may cause "
                    "exponential particle explosion / game freeze): "
                    + " → ".join(cyc + [cyc[0]])
                ),
                "obj": cyc[0] if cyc else "",
            })
    except Exception:
        # 环检测失败不应阻断其它校验/导出
        pass

    # ── (5) Attribute-level structural rules ──────────────────────────────────────
    # 依赖 efx_format.hashes；导入失败则跳过整节（不影响其他检查）。
    try:
        from ..efx_format.hashes import (
            HASH_TO_NAME as _H2N,
            RGBFIRE as _RGBFIRE,       RGBWATER as _RGBWATER,
            PLANE as _PLANE,           FAKEPLANE as _FAKEPLANE,
            PTBEHAVIOR as _PTBEHAVIOR,
            BILLBOARD3D as _BB3D,      RIBBON as _RIBBON,
            MESH as _MESH,             LIGHTNING as _LIGHTNING,
            DUMMY as _DUMMY,           RIBBONBLADE as _RIBBONBLADE,
            STRAINRIBBON as _SRBN,     TUBELIGHT as _TUBE,
            BILLBOARD2D as _BB2D,
            UVCONTROL as _UVCTL,
            MATERIAL as _MATERIAL,
            ALPHACORRECTION as _ALPHACORR,
            SHADERSETTINGS as _SHADERSET,
            HOMING as _HOMING,         VELOCITY3D as _VEL3D,
        )
        _RENDERERS = frozenset({
            _BB3D, _RIBBON, _MESH, _PLANE, _FAKEPLANE,
            _LIGHTNING, _DUMMY, _RIBBONBLADE, _SRBN, _TUBE, _BB2D,
        })
        _attribute_rules_ok = True
    except ImportError:
        _attribute_rules_ok = False

    if _attribute_rules_ok:
        for body in bodies:
            try:
                blk_objs = _children_by_type(body, "EFX_ATTRIBUTE")
                hashes = []
                for blk in blk_objs:
                    raw = blk.get("type_hash")
                    if raw is not None:
                        try:
                            hashes.append(int(str(raw)))
                        except (ValueError, TypeError):
                            pass
                hash_count = {}
                for h in hashes:
                    hash_count[h] = hash_count.get(h, 0) + 1
                hash_set = set(hashes)

                # (5a) 重复属性类型 — ERROR
                for h, cnt in hash_count.items():
                    if cnt > 1:
                        name = _H2N.get(h, f"0x{h:08X}")
                        problems.append({
                            "level": "ERROR",
                            "msg": (
                                f"Entry '{body.name}' has {cnt}× {name} attributes "
                                "(duplicate attribute types are not allowed)"
                            ),
                            "obj": body.name,
                        })

                # (5b) RGBFIRE ✗ RGBWATER — ERROR
                if _RGBFIRE in hash_set and _RGBWATER in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Entry '{body.name}' has both RGBFIRE and RGBWATER "
                            "(mutually exclusive global color effects)"
                        ),
                        "obj": body.name,
                    })

                # (5c) PLANE ✗ FAKEPLANE — ERROR
                if _PLANE in hash_set and _FAKEPLANE in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Entry '{body.name}' has both PLANE and FAKEPLANE "
                            "(mutually exclusive renderer types)"
                        ),
                        "obj": body.name,
                    })

                # (5d) PTBEHAVIOR 与其他属性共存 — 全部 WARN
                # 实测大量第三方特效让 PTBEHAVIOR 与任意属性（含渲染体）共存且不崩溃，
                # 故不再区分 hard/soft，统一降级为 WARN（仅提示，不挡导出）。
                if _PTBEHAVIOR in hash_set and len(hash_set) > 1:
                    conflicts = hash_set - {_PTBEHAVIOR}
                    names = "/".join(
                        _H2N.get(h, f"0x{h:08X}") for h in conflicts
                    )
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has PTBEHAVIOR alongside "
                            f"other attributes ({names}) — PTBEHAVIOR is usually an "
                            "isolated system, but coexistence is observed not to crash; "
                            "verify in-game behavior"
                        ),
                        "obj": body.name,
                    })

                # (5e) 多个渲染体 — WARN
                renderers_in_entry = hash_set & _RENDERERS
                if len(renderers_in_entry) > 1:
                    names = "/".join(
                        _H2N.get(h, f"0x{h:08X}") for h in renderers_in_entry
                    )
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has multiple renderers ({names}) — "
                            "only one renderer per entry is expected"
                        ),
                        "obj": body.name,
                    })

                # (5m) HOMING without VELOCITY3D — WARN
                # 全语料 212 个 HOMING 条目统计：95.3% 伴随 VELOCITY3D（另 95.8% 伴随
                # EMITTERSHAPE3D）；归航行为强依赖粒子速度矢量才能计算转向。
                if _HOMING in hash_set and _VEL3D not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has HOMING without VELOCITY3D — "
                            "homing steers particle velocity, so it strongly depends on "
                            "VELOCITY3D being present (95.3% of official HOMING entries "
                            "have it)"
                        ),
                        "obj": body.name,
                    })

                # (5g) UVCONTROL without MESH — WARN
                if _UVCTL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has UVCONTROL without MESH "
                            "(UVCONTROL is a MESH-exclusive UV scroller)"
                        ),
                        "obj": body.name,
                    })

                # (5h) MATERIAL without MESH — WARN
                if _MATERIAL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has MATERIAL without MESH "
                            "(MATERIAL overrides mrl3 material properties on a MESH entry)"
                        ),
                        "obj": body.name,
                    })

                # (5i) ALPHACORRECTION without SHADERSETTINGS — WARN
                # 738 文件统计：ALPHACORRECTION 100% 依附 SHADERSETTINGS，从不单独出现
                if _ALPHACORR in hash_set and _SHADERSET not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has ALPHACORRECTION without SHADERSETTINGS "
                            "(ALPHACORRECTION requires SHADERSETTINGS as its shader context; "
                            "all 738 sample files follow this rule)"
                        ),
                        "obj": body.name,
                    })

                # (5k) standard/extended entry 一个属性都没有 — WARN（提示性，不挡导出）
                # 正常特效体至少有 1 个属性；0 属性的 standard/extended entry 几乎总是原生
                # 「Delete Hierarchy」的残留空壳——2026-07-01 实测坐实：entry 这个 Empty
                # 对象本身没被真正删除（残留在 bpy.data.objects，默认 Outliner「View
                # Layer」视图不可见、Purge Unused Data 也清不掉，因为它仍链接在集合里、
                # 不算孤儿），只有它的 EFX_ATTRIBUTE 子对象被删掉了。io_tree.py §4a0 已经会
                # 在导出时自动把这类零属性 entry 当不存在（不写进文件），这里只是提示用户
                # 场景里还留着这个空壳对象，建议手动清理（对导出结果无影响）。root 类型
                # entry 本来就没有属性，不算在内。
                if str(body.get("entry_kind", "")) in ("standard", "extended") and not blk_objs:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has zero attributes (leftover from Blender's "
                            "native \"Delete Hierarchy\" not fully removing it — check the "
                            "Outliner's \"Blender File\" view to confirm). It will be "
                            "automatically excluded from the export, but you may want to "
                            "manually delete this leftover object from the scene"
                        ),
                        "obj": body.name,
                    })

                # (5j) 有渲染器但缺 SHADERSETTINGS — WARN
                # 官方样本：BILLBOARD3D/RIBBON/PLANE/LIGHTNING 与 SHADERSETTINGS 100% 共现；
                # MESH 78.7%（有合法的不可见 MESH，故豁免）；DUMMY 功能性体也豁免。
                _SHADERSET_REQUIRED = frozenset({_BB3D, _RIBBON, _PLANE, _LIGHTNING, _RIBBONBLADE, _SRBN})
                has_required_renderer = bool(hash_set & _SHADERSET_REQUIRED)
                if has_required_renderer and _SHADERSET not in hash_set:
                    renderer_names = ", ".join(
                        _H2N.get(h, f"0x{h:08X}") for h in (hash_set & _SHADERSET_REQUIRED)
                    )
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has {renderer_names} but no SHADERSETTINGS — "
                            "textures and transparency will not work in-game "
                            "(88.3% of official rendering entries include SHADERSETTINGS)"
                        ),
                        "obj": body.name,
                    })

            except Exception:
                pass  # 单个 entry 检查失败不影响整体

    return problems


# ─────────────────────────────────────────────────────────────────────────────
# 校验算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_validate(bpy.types.Operator):
    """导出前校验：扫描悬空指针、重复索引、死属性，弹窗报告"""

    bl_idname      = "efx.validate"
    bl_label       = "Pre-export Validation"
    bl_description = "Scan the EFX object tree for dangling pointers / duplicate index / dead attributes and report issues in a popup"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _find_efx_root(context) is not None

    def execute(self, context):
        root = _find_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT object not found")
            return {"CANCELLED"}

        problems = validate_efx_tree(root)
        errors = [p for p in problems if p["level"] == "ERROR"]
        warns = [p for p in problems if p["level"] == "WARN"]

        if not problems:
            self.report({"INFO"}, "Validation passed: no issues found")
            return {"FINISHED"}

        def _draw(self_menu, ctx):
            col = self_menu.layout.column()
            if errors:
                col.label(
                    text=T("validate.found_errors").format(n=len(errors)), icon="ERROR",
                )
                for p in errors:
                    col.label(text="• " + p["msg"])
            if warns:
                col.separator()
                col.label(
                    text=T("validate.found_warnings").format(n=len(warns)), icon="INFO",
                )
                for p in warns:
                    col.label(text="• " + p["msg"])

        context.window_manager.popup_menu(
            _draw, title=T("validate.popup_title"), icon="ERROR" if errors else "INFO",
        )

        if errors:
            self.report(
                {"WARNING"},
                f"EFX validation: {len(errors)} error(s), {len(warns)} warning(s)",
            )
        else:
            self.report({"INFO"}, f"EFX validation: {len(warns)} warning(s), no errors")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_validate,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
