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
    - Play targets target.body_ptr is None
    - ExternReference extern_ref_ptr is None（pointerized && !none）
    - PtLife relation_play_ptr is None（pointerized；relationIndex=actionID，无 -1 哨兵字段）
    - PtCollision ie_play_ptr is None（pointerized && !ie_none）
    悬空指针不再 ERROR：导出端各 export_* 早已对 None 指针安全跳过/回退（subselect/play/eof
    直接 skip，extern/ptlife/ptcollision 原样保留旧字节）。降级为 WARN + 导出时报告即可，
    不应仅因引用悬空就阻断导出。
(1b) EOF 越界 raw 值（category="eof_raw"）—— WARN，仅当 eof 列表被编辑过（root["eof_dirty"]）时报告：
    eof 条目整数落在 [0, body 数) 之外即存为 raw（is_ptr=False）。这些是原始文件里的
    "空槽哨兵"（常见 33/99/==count_body），不指向真实 body。编辑激活集/增删 body 后它们成为
    指向错误或不存在 body 的陈旧索引 → 破坏直接触发集 → 特效不生效。导出端在 eof_dirty 时丢弃。
(2) efx_index 重复（同级组内）—— ERROR
(3) 死块 EXTERNREFERENCE（count_extern==0 却仍 pointerized）—— WARN（合法历史模式）

约束（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集
  - 不改 efx_format/，不改 io_tree.py
  - 所有属性访问 getattr + try/except 防御（对象可能未初始化对应 PropertyGroup）
"""

import bpy

from .operators import _find_efx_root
from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 工具：收集子对象
# ─────────────────────────────────────────────────────────────────────────────

def _children_by_type(parent_obj, type_tag: str) -> list:
    """收集 parent_obj 的直接子对象中 ~TYPE == type_tag 的全部对象。"""
    return [
        o for o in bpy.data.objects
        if o.parent == parent_obj and o.get("~TYPE") == type_tag
    ]


def _build_trigger_graph(bodies, plays):
    """构建召唤触发有向图，返回 {obj: set(obj)} 邻接表。

    边方向 = 召唤/触发方向：
      Play  → body ：play.efx_play.entries[].targets[].body_ptr （play 生成 body）
      body  → Play ：PTLIFE.relation_play_ptr / PTCOLLISION.ie_play_ptr （body 触发 play）

    只保留终点也在本 root 节点集内的边（指针经 poll 已限定同文件，外指针忽略）。
    """
    node_set = set(bodies) | set(plays)
    adj = {n: set() for n in node_set}

    # Play → body
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

    # body → Play
    for body in bodies:
        for blk in _children_by_type(body, "EFX_BLOCK"):
            pl = getattr(blk, "efx_ptlife_ref", None)
            if pl is not None:
                try:
                    if pl.relation_pointerized and pl.relation_play_ptr in node_set:
                        adj[body].add(pl.relation_play_ptr)
                except AttributeError:
                    pass
            pc = getattr(blk, "efx_ptcollision_ref", None)
            if pc is not None:
                try:
                    if (pc.ie_pointerized and not pc.ie_none
                            and pc.ie_play_ptr in node_set):
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


def _is_extern_ref_block(obj) -> bool:
    """判断块对象是否是已指针化的 EXTERNREFERENCE（有 efx_extern_ref 且 pointerized）。"""
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
    bodies     = _children_by_type(root_obj, "EFX_BODY")
    plays      = _children_by_type(root_obj, "EFX_PLAY")
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

    # Play targets（结构：efx_play.entries[].targets[].body_ptr）
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
                                f"Play '{play.name}' entry {ei} target {ti} "
                                f"has a dangling pointer (skipped on export)"
                            ),
                            "obj": play.name,
                        })
                except AttributeError:
                    continue

    # 遍历全部块（EFX_BLOCK）做引用检查
    for body in bodies:
        for blk in _children_by_type(body, "EFX_BLOCK"):
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
                                f"ExternReference block '{blk.name}' has a dangling pointer"
                                " (the referenced Extern was deleted; original index bytes kept on export)"
                            ),
                            "obj": blk.name,
                        })
                    # (3) 死块 WARN：count_extern==0 却仍 pointerized
                    if er.extern_ref_pointerized and count_extern == 0:
                        problems.append({
                            "level": "WARN",
                            "msg": (
                                f"ExternReference block '{blk.name}' is still pointerized, "
                                "but the file has no Extern segment (count_extern=0, legal legacy dead block)"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

            # PtLife relation 悬空（relationIndex 无 -1 哨兵字段）
            pl = getattr(blk, "efx_ptlife_ref", None)
            if pl is not None:
                try:
                    if pl.relation_pointerized and pl.relation_play_ptr is None:
                        problems.append({
                            "level": "WARN",
                            "category": "dangling",
                            "msg": (
                                f"PtLife block '{blk.name}' relation has a dangling pointer"
                                " (the referenced Action/Play was deleted; original index bytes kept on export)"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

            # PtCollision ie 悬空
            pc = getattr(blk, "efx_ptcollision_ref", None)
            if pc is not None:
                try:
                    if (pc.ie_pointerized
                            and not pc.ie_none
                            and pc.ie_play_ptr is None):
                        problems.append({
                            "level": "WARN",
                            "category": "dangling",
                            "msg": (
                                f"PtCollision block '{blk.name}' ie has a dangling pointer"
                                " (the referenced Play was deleted; original index bytes kept on export)"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

    # eof_ints 列表：悬空 body 指针不报（导出端跳过、count_eof 重算）。
    # 但若 eof 列表被编辑过（eof_dirty），报告将被丢弃的越界 raw 值（空槽哨兵），
    # 让用户知道哪些陈旧索引被清理 —— 见 (1b) 说明。
    try:
        eof_dirty = bool(int(root_obj.get("eof_dirty", 0)))
    except (ValueError, TypeError):
        eof_dirty = False
    if eof_dirty:
        n_bodies = len(bodies)
        eof_props = getattr(root_obj, "efx_eof_list", None)
        if eof_props is not None:
            for i, item in enumerate(getattr(eof_props, "items", [])):
                try:
                    if not item.is_ptr:
                        rv = int(item.raw_value)
                        if rv < 0 or rv >= n_bodies:
                            problems.append({
                                "level": "WARN",
                                "category": "eof_raw",
                                "msg": (
                                    f"EOF entry {i} raw={rv} is out of range "
                                    f"[0,{n_bodies}) — inactive-slot sentinel, "
                                    "dropped on export (the active set was edited)"
                                ),
                                "obj": root_obj.name,
                            })
                except (AttributeError, ValueError, TypeError):
                    continue

    # ── (2) efx_index 重复 ──────────────────────────────────────────────────

    def _check_dup(objs, group_name):
        seen = {}
        for o in objs:
            idx = o.get("efx_index")
            if idx is None:
                continue
            idx = int(idx)
            seen.setdefault(idx, []).append(o.name)
        dups = {k: v for k, v in seen.items() if len(v) > 1}
        if dups:
            dup_str = ", ".join(str(k) for k in sorted(dups))
            problems.append({
                "level": "ERROR",
                "msg": f"{group_name} segment has duplicate efx_index: {dup_str}",
                "obj": "",
            })

    _check_dup(bodies, "Body")
    _check_dup(plays, "Play")
    _check_dup(externs, "Extern")
    _check_dup(subselects, "Subselect")
    # 每个 body 内的块各自一组
    for body in bodies:
        blocks = _children_by_type(body, "EFX_BLOCK")
        _check_dup(blocks, f"Body '{body.name}' blocks")

    # ── (4) 召唤回绕（body↔play 触发图成环）—— WARN ────────────────────────────
    # body 的 PTLIFE/PTCOLLISION 触发 Play，Play 的 targets 又指回（祖先）body，
    # 形成递归召唤 → 每轮按扇出倍增（如 12→144→1728…）直接卡死游戏。
    # 仅警告、不挡导出：保留刻意 loop 的自由，由用户判断该环是否有界。
    try:
        adj = _build_trigger_graph(bodies, plays)
        for cyc in _find_cycles(adj):
            problems.append({
                "level": "WARN",
                "msg": (
                    "Spawn cycle detected (body↔Play recursive summoning, may cause "
                    "exponential particle explosion / game freeze): "
                    + " → ".join(cyc + [cyc[0]])
                ),
                "obj": cyc[0] if cyc else "",
            })
    except Exception:
        # 环检测失败不应阻断其它校验/导出
        pass

    # ── (5) Block-level structural rules ──────────────────────────────────────
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
            UVSEQUENCE as _UVSEQ,      UVCONTROL as _UVCTL,
            MATERIAL as _MATERIAL,
            ALPHACORRECTION as _ALPHACORR,
            SHADERSETTINGS as _SHADERSET,
        )
        _RENDERERS = frozenset({
            _BB3D, _RIBBON, _MESH, _PLANE, _FAKEPLANE,
            _LIGHTNING, _DUMMY, _RIBBONBLADE, _SRBN, _TUBE, _BB2D,
        })
        _SPRITE_RENDERERS = frozenset({_BB3D, _RIBBON, _PLANE})
        _block_rules_ok = True
    except ImportError:
        _block_rules_ok = False

    if _block_rules_ok:
        for body in bodies:
            try:
                blk_objs = _children_by_type(body, "EFX_BLOCK")
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

                # (5a) 重复块类型 — ERROR
                for h, cnt in hash_count.items():
                    if cnt > 1:
                        name = _H2N.get(h, f"0x{h:08X}")
                        problems.append({
                            "level": "ERROR",
                            "msg": (
                                f"Body '{body.name}' has {cnt}× {name} blocks "
                                "(duplicate block types are not allowed)"
                            ),
                            "obj": body.name,
                        })

                # (5b) RGBFIRE ✗ RGBWATER — ERROR
                if _RGBFIRE in hash_set and _RGBWATER in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Body '{body.name}' has both RGBFIRE and RGBWATER "
                            "(mutually exclusive global color effects)"
                        ),
                        "obj": body.name,
                    })

                # (5c) PLANE ✗ FAKEPLANE — ERROR
                if _PLANE in hash_set and _FAKEPLANE in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Body '{body.name}' has both PLANE and FAKEPLANE "
                            "(mutually exclusive renderer types)"
                        ),
                        "obj": body.name,
                    })

                # (5d) PTBEHAVIOR 与其他块共存 — 全部 WARN
                # 实测大量第三方特效让 PTBEHAVIOR 与任意块（含渲染体）共存且不崩溃，
                # 故不再区分 hard/soft，统一降级为 WARN（仅提示，不挡导出）。
                if _PTBEHAVIOR in hash_set and len(hash_set) > 1:
                    conflicts = hash_set - {_PTBEHAVIOR}
                    names = "/".join(
                        _H2N.get(h, f"0x{h:08X}") for h in conflicts
                    )
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has PTBEHAVIOR alongside "
                            f"other blocks ({names}) — PTBEHAVIOR is usually an "
                            "isolated system, but coexistence is observed not to crash; "
                            "verify in-game behavior"
                        ),
                        "obj": body.name,
                    })

                # (5e) 多个渲染体 — WARN
                renderers_in_body = hash_set & _RENDERERS
                if len(renderers_in_body) > 1:
                    names = "/".join(
                        _H2N.get(h, f"0x{h:08X}") for h in renderers_in_body
                    )
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has multiple renderers ({names}) — "
                            "only one renderer per body is expected"
                        ),
                        "obj": body.name,
                    })

                # (5f) UVSEQUENCE without BILLBOARD3D/RIBBON/PLANE — WARN
                if _UVSEQ in hash_set and not (hash_set & _SPRITE_RENDERERS):
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has UVSEQUENCE without BILLBOARD3D/RIBBON/PLANE "
                            "(UVSEQUENCE is a sprite face UV animation system)"
                        ),
                        "obj": body.name,
                    })

                # (5g) UVCONTROL without MESH — WARN
                if _UVCTL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has UVCONTROL without MESH "
                            "(UVCONTROL is a MESH-exclusive UV scroller)"
                        ),
                        "obj": body.name,
                    })

                # (5h) MATERIAL without MESH — WARN
                if _MATERIAL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has MATERIAL without MESH "
                            "(MATERIAL overrides mrl3 material properties on a MESH body)"
                        ),
                        "obj": body.name,
                    })

                # (5i) ALPHACORRECTION without SHADERSETTINGS — WARN
                # 738 文件统计：ALPHACORRECTION 100% 依附 SHADERSETTINGS，从不单独出现
                if _ALPHACORR in hash_set and _SHADERSET not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Body '{body.name}' has ALPHACORRECTION without SHADERSETTINGS "
                            "(ALPHACORRECTION requires SHADERSETTINGS as its shader context; "
                            "all 738 sample files follow this rule)"
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
                            f"Body '{body.name}' has {renderer_names} but no SHADERSETTINGS — "
                            "textures and transparency will not work in-game "
                            "(88.3% of official rendering bodies include SHADERSETTINGS)"
                        ),
                        "obj": body.name,
                    })

            except Exception:
                pass  # 单个 body 检查失败不影响整体

    return problems


# ─────────────────────────────────────────────────────────────────────────────
# 校验算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_validate(bpy.types.Operator):
    """导出前校验：扫描悬空指针、重复索引、死块，弹窗报告"""

    bl_idname      = "efx.validate"
    bl_label       = "Pre-export Validation"
    bl_description = "Scan the EFX object tree for dangling pointers / duplicate index / dead blocks and report issues in a popup"
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
