"""导出前检查 EFX 对象树，并将问题分为 ERROR 与 WARN。

维护约束：
- 校验只报告，不修改对象树；属性 PropertyGroup 可能缺失，读取须可安全跳过。
- 悬空引用与 EOF 归属异常为 WARN，因为导出端已有确定的跳过或回退语义。
- 会产生无效结构的属性组合为 ERROR；证据不足的组合仅提示为 WARN。
"""

import bpy

from .operators import _find_efx_root
from .i18n import T
from . import root_collection as _rc


# 对象收集与图分析。

def _children_by_type(parent_obj, type_tag: str) -> list:
    """按容器类型收集直属段对象或 Entry 的直属属性。"""
    if isinstance(parent_obj, bpy.types.Collection):
        return _rc.collect_top_level(parent_obj, type_tag)
    return [
        o for o in bpy.data.objects
        if o.parent == parent_obj and o.get("~TYPE") == type_tag
    ]


def _build_trigger_graph(bodies, plays):
    """构建 Entry 与 Action 的文件内触发有向图。"""
    node_set = set(bodies) | set(plays)
    adj = {n: set() for n in node_set}

    # Action → Entry。
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

    # Entry → Action。
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
    """返回去重的有向环；每个环按最小名称规范化。"""
    cycles = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack = []

    def _norm(path):
        # 旋转到字典序最小的节点，保证同一环只报告一次。
        names = [o.name for o in path]
        k = names.index(min(names))
        return tuple(names[k:] + names[:k])

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, ()):
            if color[v] == GRAY:
                # 回边与当前递归栈构成有向环。
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


def detect_dimension_entries(root_obj) -> tuple:
    """返回含 TRANSFORM2D 与 TRANSFORM3D 的 Entry 名称，供校验和导出共用。"""
    try:
        from ..efx_format.hashes import TRANSFORM2D as _T2D, TRANSFORM3D as _T3D
    except ImportError:
        return [], []
    dim_2d, dim_3d = [], []
    for body in _children_by_type(root_obj, "EFX_ENTRY"):
        try:
            hash_set = set()
            for blk in _children_by_type(body, "EFX_ATTRIBUTE"):
                raw = blk.get("type_hash")
                if raw is not None:
                    try:
                        hash_set.add(int(str(raw)))
                    except (ValueError, TypeError):
                        pass
            if _T2D in hash_set:
                dim_2d.append(body.name)
            if _T3D in hash_set:
                dim_3d.append(body.name)
        except Exception:
            pass
    return dim_2d, dim_3d


# 核心校验。

def _extern_ref_state_indices(blk_obj) -> list:
    """读取 EXTERNREFERENCE 的 index0 与 index1；数据不足时返回空列表。"""
    import base64
    import struct as _struct

    raw = blk_obj.get("data_bytes")
    if not raw:
        return []
    try:
        data = base64.b64decode(str(raw))
    except Exception:
        return []
    if len(data) < 20:
        return []
    i0, i1 = _struct.unpack_from("<ii", data, 12)
    return [("index0", i0), ("index1", i1)]


def validate_efx_tree(root_obj) -> list:
    """扫描对象树，返回 ``level``、``msg`` 与 ``obj`` 组成的问题列表。"""
    problems = []
    if root_obj is None:
        problems.append({
            "level": "ERROR",
            "msg": "EFX_ROOT object not found",
            "obj": "",
        })
        return problems

    # 段对象集合。
    bodies     = _children_by_type(root_obj, "EFX_ENTRY")
    plays      = _children_by_type(root_obj, "EFX_ACTION")
    externs    = _children_by_type(root_obj, "EFX_EXTERN")
    subselects = _children_by_type(root_obj, "EFX_SUBSELECT")
    count_extern = len(externs)

    # Extern 结构：空项、指向会被剔除的项及状态下标越界。
    _empty_externs = set()
    for ext in externs:
        ep = getattr(ext, "efx_extern", None)
        if ep is None:
            continue
        hdr = ext.get("hdr_item_count")
        if hdr is not None:
            try:
                if int(str(hdr)) == 0:
                    continue  # 导入时为空的段按导出端语义原样保留。
            except (ValueError, TypeError):
                pass
        if len(ep.items) == 0:
            _empty_externs.add(ext.name)
            problems.append({
                "level": "WARN",
                "msg": (f"Extern '{ext.name}' has no items and will be left out of the exported "
                        "file; add an item to it, or delete it"),
                "obj": ext.name,
            })

    for body in bodies:
        for blk in _children_by_type(body, "EFX_ATTRIBUTE"):
            er = getattr(blk, "efx_extern_ref", None)
            if er is None:
                continue
            try:
                ptr = er.extern_ref_ptr
                if (er.extern_ref_pointerized and not er.extern_ref_none
                        and ptr is not None and ptr.name in _empty_externs):
                    problems.append({
                        "level": "WARN",
                        "msg": (f"ExternReference attribute '{blk.name}' points at Extern "
                                f"'{ptr.name}', which has no items and will be left out of the "
                                "exported file; this reference will be written as 'no target'"),
                        "obj": blk.name,
                    })
                # 删除状态列后，引用中保留的 index0/index1 可能越界。
                if (er.extern_ref_pointerized and not er.extern_ref_none
                        and ptr is not None):
                    pep = getattr(ptr, "efx_extern", None)
                    n_state = max((len(it.instances) for it in pep.items), default=0) if pep else 0
                    if n_state:
                        raw = _extern_ref_state_indices(blk)
                        for label, v in raw:
                            if v >= n_state:
                                problems.append({
                                    "level": "WARN",
                                    "msg": (f"ExternReference attribute '{blk.name}' selects "
                                            f"{label}={v}, but Extern '{ptr.name}' only has "
                                            f"{n_state} state(s); the game will fall back to an "
                                            "existing state"),
                                    "obj": blk.name,
                                })
            except AttributeError:
                pass

    # 悬空引用：导出端可安全跳过或回退，故仅警告。

    # Subselect 成员。
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

    # Action 目标。
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

    # 属性引用。
    for body in bodies:
        for blk in _children_by_type(body, "EFX_ATTRIBUTE"):
            # ExternReference 悬空。
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
                    # 无 Extern 段时保留的指针化引用仅提示。
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

            # PtLife 与 PtCollision 的空 Action 目标表示无目标，导出时写 -1。

    # per_entry EOF 模型中，Entry 应恰好归属一个触发子集合。
    # 导入时修复 EOF 索引或顺序会改变原始字节，必须提示用户。
    _eof_dropped = str(root_obj.get("eof_dropped", ""))
    if _eof_dropped:
        problems.append({
            "level": "WARN",
            "category": "eof_repaired",
            "msg": (
                f"EOF section had invalid entry indices {_eof_dropped} "
                "(out of range or duplicated) — dropped on import; export writes the "
                "repaired list, so the file will not be byte-identical to the original"
            ),
            "obj": "",
        })
    # 放在错误 Entry 类型下的属性会在导出时剔除。
    _root_attr_dropped = str(root_obj.get("root_attr_dropped", ""))
    if _root_attr_dropped:
        problems.append({
            "level": "WARN",
            "category": "root_attr_dropped",
            "msg": (
                f"Attribute(s) dropped on export (wrong entry type for their kind): "
                f"{_root_attr_dropped}"
            ),
            "obj": "",
        })
    if root_obj.get("eof_reordered", 0):
        problems.append({
            "level": "WARN",
            "category": "eof_reordered",
            "msg": (
                "EOF section was not in ascending order — normalized on import "
                "(order carries no meaning; official files are always ascending). "
                "Export writes ascending order, so the file will not be byte-identical "
                "to the original"
            ),
            "obj": "",
        })

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

    # Entry 与 Action 的触发环可能递归生成粒子；保留为 WARN 以允许受控循环。
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
        # 图分析失败不阻断其他校验。
        pass

    # 属性结构规则；哈希不可用时跳过本节。
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
            TRANSFORM2D as _T2D,       TRANSFORM3D as _T3D,
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
        # FAKEPLANE 是渲染修饰，不作为 2D/3D 主体匹配依据。
        _RENDERER_BODY_3D = frozenset({
            _BB3D, _RIBBON, _MESH, _PLANE,
            _LIGHTNING, _DUMMY, _RIBBONBLADE, _SRBN, _TUBE,
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

                # 重复属性类型。
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

                # 互斥颜色效果。
                if _RGBFIRE in hash_set and _RGBWATER in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Entry '{body.name}' has both RGBFIRE and RGBWATER "
                            "(mutually exclusive global color effects)"
                        ),
                        "obj": body.name,
                    })

                # 互斥渲染器。
                if _PLANE in hash_set and _FAKEPLANE in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Entry '{body.name}' has both PLANE and FAKEPLANE "
                            "(mutually exclusive renderer types)"
                        ),
                        "obj": body.name,
                    })

                # PTBEHAVIOR 通常独立使用，但共存仅提示。
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

                # 多个渲染主体仅提示。
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

                # 骨架与渲染主体必须使用相同维度的管线。
                if _T2D in hash_set:
                    bad = hash_set & _RENDERER_BODY_3D
                    if bad:
                        names = "/".join(_H2N.get(h, f"0x{h:08X}") for h in bad)
                        problems.append({
                            "level": "ERROR",
                            "msg": (
                                f"Entry '{body.name}' has TRANSFORM2D (2D skeleton) together "
                                f"with 3D renderer body ({names}) — confirmed to crash the game "
                                "in-machine. 2D entries must use BILLBOARD2D as the renderer body."
                            ),
                            "obj": body.name,
                        })
                if _T3D in hash_set and _BB2D in hash_set:
                    problems.append({
                        "level": "ERROR",
                        "msg": (
                            f"Entry '{body.name}' has TRANSFORM3D (3D skeleton) together "
                            "with BILLBOARD2D (2D renderer body) — the mirror of a "
                            "confirmed in-machine crash case, blocked as a precaution."
                        ),
                        "obj": body.name,
                    })

                # HOMING 缺少速度属性时仅提示。
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

                # UVCONTROL 依赖 MESH。
                if _UVCTL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has UVCONTROL without MESH "
                            "(UVCONTROL is a MESH-exclusive UV scroller)"
                        ),
                        "obj": body.name,
                    })

                # MATERIAL 覆盖 MESH 的材质属性。
                if _MATERIAL in hash_set and _MESH not in hash_set:
                    problems.append({
                        "level": "WARN",
                        "msg": (
                            f"Entry '{body.name}' has MATERIAL without MESH "
                            "(MATERIAL overrides mrl3 material properties on a MESH entry)"
                        ),
                        "obj": body.name,
                    })

                # ALPHACORRECTION 需要 SHADERSETTINGS 的着色器上下文。
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

                # 零属性 standard Entry 会在导出时剔除，故仅提示清理。
                if str(body.get("entry_kind", "")) == "standard" and not blk_objs:
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

                # 仅检查必须依赖 SHADERSETTINGS 的渲染主体。
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
                pass  # 单个 Entry 检查失败不影响整体。

        # header.is_3d 必须与文件内的维度类型保持一致。
        _dim_2d_entries, _dim_3d_entries = detect_dimension_entries(root_obj)
        if _dim_2d_entries or _dim_3d_entries:
            is_3d_raw = root_obj.get("hdr_is_3d")
            is_3d = None
            if is_3d_raw is not None:
                try:
                    is_3d = int(str(is_3d_raw))
                except (ValueError, TypeError):
                    is_3d = None

            if _dim_2d_entries and _dim_3d_entries:
                problems.append({
                    "level": "WARN",
                    "msg": (
                        f"File mixes 2D-type ({len(_dim_2d_entries)} entries, TRANSFORM2D) "
                        f"and 3D-type ({len(_dim_3d_entries)} entries, TRANSFORM3D) content — "
                        "the game appears to use a separate rendering pipeline per file "
                        "(gated by header.is_3d), so mixing both in one file is likely to "
                        "crash. Keep only one type per file (2D → is_3d=0, 3D → is_3d=1)."
                    ),
                    "obj": (_dim_2d_entries + _dim_3d_entries)[0],
                })
            elif is_3d == 0 and _dim_3d_entries:
                problems.append({
                    "level": "WARN",
                    "msg": (
                        "header.is_3d=0 (2D file) but "
                        f"{len(_dim_3d_entries)} entry(ies) use TRANSFORM3D "
                        f"({', '.join(_dim_3d_entries)}) — a mismatched 2D/3D pipeline "
                        "flag is likely to crash the game. Set is_3d=1."
                    ),
                    "obj": _dim_3d_entries[0],
                })
            elif is_3d == 1 and _dim_2d_entries:
                problems.append({
                    "level": "WARN",
                    "msg": (
                        "header.is_3d=1 (3D file) but "
                        f"{len(_dim_2d_entries)} entry(ies) use TRANSFORM2D "
                        f"({', '.join(_dim_2d_entries)}) — a mismatched 2D/3D pipeline "
                        "flag is likely to crash the game. Set is_3d=0."
                    ),
                    "obj": _dim_2d_entries[0],
                })

    # TIML 仅支持固定插值；BEZIER 有明确近似，其余不支持插值阻止导出。
    try:
        from . import timl_edit as _te
        from . import io_tree as _iot
    except ImportError:
        _te = None
    if _te is not None:
        for body in bodies:
            try:
                h = _iot.find_timl_handle(body)
                if h is None:
                    continue
                for iss in _te.check_timl_interpolations(h):
                    if iss["severity"] == "ERROR":
                        problems.append({
                            "level": "ERROR",
                            "category": "timl_interp",
                            "msg": (
                                f"Entry '{body.name}' TIML keyframe uses unsupported "
                                f"interpolation '{iss['interp']}' — only "
                                f"{_te._SUPPORTED_INTERP_DESC} are supported by the game"
                            ),
                            "obj": body.name,
                        })
                    else:  # BEZIER → WARN（近似为 Cubic）
                        problems.append({
                            "level": "WARN",
                            "category": "timl_interp",
                            "msg": (
                                f"Entry '{body.name}' TIML keyframe uses BEZIER — the game "
                                "has no free bezier, so it is approximated as Cubic on export"
                            ),
                            "obj": body.name,
                        })
            except Exception:
                pass  # 单个 Entry 检查失败不影响整体。

    return problems


# 校验算子。

class EFX_OT_validate(bpy.types.Operator):
    """执行导出前校验并在弹窗中显示结果。"""

    bl_idname      = "efx.validate"
    bl_label       = "Pre-export Validation"
    bl_description = "Scan the EFX object tree for invalid references, duplicate indices, and invalid attributes, and report the results in a popup"
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


# 注册。

_CLASSES = (
    EFX_OT_validate,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
