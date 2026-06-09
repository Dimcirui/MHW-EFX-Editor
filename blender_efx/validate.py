"""
blender_efx/validate.py  —  L2 #4：导出前校验（仿 mrl3 checkMrl3Error）

提供：
  validate_efx_tree(root_obj) -> list[dict]  纯函数，扫描对象树返回问题列表
  EFX_OT_validate                            校验算子（efx.validate），弹窗显示问题

问题项结构：{"level": "ERROR"|"WARN", "msg": str, "obj": str}

检查项
------
(1) 悬空指针（删除被引用对象后产生）—— 核心检查，全部 ERROR：
    - Subselect 成员 member.body_ptr is None
    - Play targets target.body_ptr is None
    - ExternReference extern_ref_ptr is None（pointerized && !none）
    - PtLife relation_body_ptr is None（pointerized；relationIndex 无 -1 哨兵字段）
    - PtCollision ie_play_ptr is None（pointerized && !ie_none）
    - eof_ints item.body_ptr is None（is_ptr）
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


# ─────────────────────────────────────────────────────────────────────────────
# 工具：收集子对象
# ─────────────────────────────────────────────────────────────────────────────

def _children_by_type(parent_obj, type_tag: str) -> list:
    """收集 parent_obj 的直接子对象中 ~TYPE == type_tag 的全部对象。"""
    return [
        o for o in bpy.data.objects
        if o.parent == parent_obj and o.get("~TYPE") == type_tag
    ]


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
            "msg": "未找到 EFX_ROOT 对象",
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
                        "level": "ERROR",
                        "msg": f"Subselect '{ss.name}' 第 {i} 个成员指针悬空",
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
                            "level": "ERROR",
                            "msg": (
                                f"Play '{play.name}' entry {ei} 第 {ti} 个 "
                                f"target 指针悬空"
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
                            "level": "ERROR",
                            "msg": (
                                f"ExternReference 块 '{blk.name}' 指针悬空"
                                "（被引用的 Extern 已删除）"
                            ),
                            "obj": blk.name,
                        })
                    # (3) 死块 WARN：count_extern==0 却仍 pointerized
                    if er.extern_ref_pointerized and count_extern == 0:
                        problems.append({
                            "level": "WARN",
                            "msg": (
                                f"ExternReference 块 '{blk.name}' 仍指针化，"
                                "但文件无 Extern 段（count_extern=0，合法历史死块）"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

            # PtLife relation 悬空（relationIndex 无 -1 哨兵字段）
            pl = getattr(blk, "efx_ptlife_ref", None)
            if pl is not None:
                try:
                    if pl.relation_pointerized and pl.relation_body_ptr is None:
                        problems.append({
                            "level": "ERROR",
                            "msg": (
                                f"PtLife 块 '{blk.name}' relation 指针悬空"
                                "（被引用的 Body 已删除）"
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
                            "level": "ERROR",
                            "msg": (
                                f"PtCollision 块 '{blk.name}' ie 指针悬空"
                                "（被引用的 Play 已删除）"
                            ),
                            "obj": blk.name,
                        })
                except AttributeError:
                    pass

    # eof_ints 列表
    eof_props = getattr(root_obj, "efx_eof_list", None)
    if eof_props is not None:
        try:
            items = eof_props.items
        except AttributeError:
            items = None
        if items is not None:
            for i, item in enumerate(items):
                try:
                    if item.is_ptr and item.body_ptr is None:
                        problems.append({
                            "level": "ERROR",
                            "msg": f"EOF 列表第 {i} 项指针悬空（被引用的 Body 已删除）",
                            "obj": root_obj.name,
                        })
                except AttributeError:
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
            dup_str = "、".join(str(k) for k in sorted(dups))
            problems.append({
                "level": "ERROR",
                "msg": f"{group_name} 段存在重复 efx_index：{dup_str}",
                "obj": "",
            })

    _check_dup(bodies, "Body")
    _check_dup(plays, "Play")
    _check_dup(externs, "Extern")
    _check_dup(subselects, "Subselect")
    # 每个 body 内的块各自一组
    for body in bodies:
        blocks = _children_by_type(body, "EFX_BLOCK")
        _check_dup(blocks, f"Body '{body.name}' 的块")

    return problems


# ─────────────────────────────────────────────────────────────────────────────
# 校验算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_validate(bpy.types.Operator):
    """导出前校验：扫描悬空指针、重复索引、死块，弹窗报告"""

    bl_idname      = "efx.validate"
    bl_label       = "导出前校验"
    bl_description = "扫描 EFX 对象树的悬空指针 / 重复 index / 死块，弹窗报告问题"
    bl_options     = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _find_efx_root(context) is not None

    def execute(self, context):
        root = _find_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "未找到 EFX_ROOT 对象")
            return {"CANCELLED"}

        problems = validate_efx_tree(root)
        errors = [p for p in problems if p["level"] == "ERROR"]
        warns = [p for p in problems if p["level"] == "WARN"]

        if not problems:
            self.report({"INFO"}, "校验通过：未发现问题")
            return {"FINISHED"}

        def _draw(self_menu, ctx):
            col = self_menu.layout.column()
            if errors:
                col.label(
                    text=f"发现 {len(errors)} 个错误：", icon="ERROR",
                )
                for p in errors:
                    col.label(text="• " + p["msg"])
            if warns:
                col.separator()
                col.label(
                    text=f"发现 {len(warns)} 个警告：", icon="INFO",
                )
                for p in warns:
                    col.label(text="• " + p["msg"])

        context.window_manager.popup_menu(
            _draw, title="EFX 校验结果", icon="ERROR" if errors else "INFO",
        )

        if errors:
            self.report(
                {"WARNING"},
                f"EFX 校验：{len(errors)} 错误，{len(warns)} 警告",
            )
        else:
            self.report({"INFO"}, f"EFX 校验：{len(warns)} 警告，无错误")
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
