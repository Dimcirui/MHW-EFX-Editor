"""将 TRANSFORM3D 与 PARENTOPTIONS 映射为 Entry 的视口变换。

维护约束：这是单向视口代理，Object 变换不得反写或参与 EFX 导出。TRANSFORM3D
FLOAT6 的基础值使用索引 0/2/4。骨骼只通过 Copy Location 叠加当前位置，旋转和缩放
始终由 TRANSFORM3D 的游戏到 Blender 基变换决定；无效绑定必须移除约束。
"""

from math import radians

import bpy
from mathutils import Matrix, Euler, Vector

from . import root_collection as _rc


def _t3d_hash() -> int:
    from ..efx_format.hashes import TRANSFORM3D
    return TRANSFORM3D


def _parentopts_hash() -> int:
    from ..efx_format.hashes import PARENTOPTIONS
    return PARENTOPTIONS


# ── 坐标映射（game fixed 三元组 → blender 三元组）─────────────────────────────

def game_loc_to_blender(gx, gy, gz):
    """平移：/100 + 轴 (X,Y,Z)→(X,-Z,Y)。"""
    return (gx / 100.0, -gz / 100.0, gy / 100.0)


def game_rot_to_blender(gx, gy, gz):
    """将旋转分量换算为 Blender 弧度坐标。"""
    return (radians(gx), radians(-gz), radians(gy))


def game_scale_to_blender(gx, gy, gz):
    """缩放：Y/Z 互换、不除 100。"""
    return (gx, gz, gy)


# 旋转必须做完整基变换，不能像向量一样仅交换 Euler 分量。

def _game_rot_matrix(gx, gy, gz):
    """按游戏组合顺序 ``Ry @ Rx @ Rz`` 构建旋转矩阵。"""
    Rx = Matrix.Rotation(radians(gx), 3, 'X')
    Ry = Matrix.Rotation(radians(gy), 3, 'Y')
    Rz = Matrix.Rotation(radians(gz), 3, 'Z')
    return Ry @ Rx @ Rz


def _g2b_basis():
    """游戏→Blender 的基变换矩阵 M = Rx(+90°)（游戏 Y-up → Blender Z-up）。"""
    return Matrix.Rotation(radians(90), 3, 'X')


def game_rot_matrix_blender(gx, gy, gz):
    """无骨骼基准时：游戏旋转换到 Blender 世界 = M · R_game · M⁻¹，返回 4x4。"""
    M = _g2b_basis()
    R = _game_rot_matrix(gx, gy, gz)
    return (M @ R @ M.inverted()).to_4x4()


def _fixed3(float6_value):
    """从 FLOAT6 取基础三元组（idx 0/2/4）。"""
    v = list(float6_value)
    return (v[0], v[2], v[4])


# ── 取属性/字段 ─────────────────────────────────────────────────────────────────

def _iter_entry_attributes(entry_obj, children_map=None):
    """枚举 Entry 属性；批量调用应传入预建映射。"""
    if children_map is not None:
        yield from children_map.get(entry_obj, [])
        return
    for blk in bpy.data.objects:
        if blk.parent is entry_obj and blk.get("~TYPE") == "EFX_ATTRIBUTE":
            yield blk


def build_entry_attr_map(root_obj):
    """按父对象建立属性映射，供批量变换同步与锚定解析复用。"""
    out = {}
    for blk in bpy.data.objects:
        if blk.get("~TYPE") == "EFX_ATTRIBUTE":
            p = blk.parent
            if p is not None:
                out.setdefault(p, []).append(blk)
    return out


def _attribute_of_type(entry_obj, type_hash, children_map=None):
    """返回 entry 下第一个指定 type_hash 的 EFX_ATTRIBUTE（无则 None）。"""
    for blk in _iter_entry_attributes(entry_obj, children_map):
        try:
            if int(blk.efx_block.type_hash_str) == type_hash:
                return blk
        except Exception:
            continue
    return None


def _entry_joint_no(entry_obj, children_map=None):
    """读 entry 的 PARENTOPTIONS.jointNo（int）；无 PARENTOPTIONS/字段 → None。"""
    po = _attribute_of_type(entry_obj, _parentopts_hash(), children_map)
    if po is None:
        return None
    try:
        for it in po.efx_block.field_items:
            if it.ori_name == "jointNo":
                return int(it.int_value)
    except Exception:
        pass
    return None


def _t3d_local_matrix(t3d_attribute):
    """把 TRANSFORM3D 块的 translate/rotate/resize 组装成 Blender 世界空间变换矩阵。
    使用 game→Blender 轴交换（M_G2B），适用于无骨骼基准的情形。"""
    vals = {}
    try:
        for it in t3d_attribute.efx_block.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)
    except Exception:
        return None

    loc = Vector(game_loc_to_blender(*vals["translate"])) if "translate" in vals else Vector((0, 0, 0))
    if "rotate" in vals:
        # 基变换共轭 M·R_game·M⁻¹（非朴素分量交换）；与 loc/scl 的 M 变换一致组合。
        rot = game_rot_matrix_blender(*vals["rotate"])
    else:
        rot = Matrix.Identity(4)
    if "resize" in vals:
        sx, sy, sz = game_scale_to_blender(*vals["resize"])
    else:
        sx = sy = sz = 1.0
    scl = Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))
    return Matrix.Translation(loc) @ rot @ scl


# ── 骨骼基准 ─────────────────────────────────────────────────────────────────

# 视为"无绑定骨骼 / 原点基准"的 jointNo 哨兵值。
_BONE_NONE_SENTINELS = (-1, 255)

#: entry 上骨骼跟随约束的固定名字（增/改/删都按这个名字找，避免重复叠加）。
_BONE_FOLLOW_CONSTRAINT_NAME = "EFX_BoneFollow"


def _resolve_bone_name(armature_obj, jointNo):
    """校验 jointNo 对应的骨骼是否存在，返回骨骼名；否则 None（→ 以世界原点为基准）。

    None 情形：armature_obj 为空/非骨架、jointNo 为 None/-1/255、骨架中无对应骨骼。
    """
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return None
    if jointNo is None or jointNo in _BONE_NONE_SENTINELS or jointNo < 0:
        return None
    bone_name = f"MhBone_{jointNo:03d}"
    if armature_obj.data.bones.get(bone_name) is None:
        return None
    return bone_name


def bone_base_matrix(armature_obj, jointNo):
    """返回骨骼世界 rest 矩阵，供一次性定位；实时摆位使用约束。"""
    bone_name = _resolve_bone_name(armature_obj, jointNo)
    if bone_name is None:
        return None
    bone = armature_obj.data.bones[bone_name]
    # rest 位姿下骨骼 head 的世界矩阵（matrix_local 是骨架空间的 rest 矩阵）
    return armature_obj.matrix_world @ bone.matrix_local


def _sync_bone_follow_constraint(entry_obj, armature_obj, jointNo) -> bool:
    """同步当前 pose 的 Copy Location 约束。

    约束仅叠加位置，保留 Entry 自身的旋转和缩放；无效绑定必须清除已有约束。
    """
    bone_name = _resolve_bone_name(armature_obj, jointNo)
    con = entry_obj.constraints.get(_BONE_FOLLOW_CONSTRAINT_NAME)
    if bone_name is None:
        if con is not None:
            entry_obj.constraints.remove(con)
        return False
    if con is None:
        con = entry_obj.constraints.new(type="COPY_LOCATION")
        con.name = _BONE_FOLLOW_CONSTRAINT_NAME
    con.target = armature_obj
    con.subtarget = bone_name
    con.head_tail = 0.0
    con.use_offset = True
    con.use_x = con.use_y = con.use_z = True
    con.target_space = "WORLD"
    con.owner_space = "WORLD"
    con.influence = 1.0
    return True


# ── 应用到单个 entry ──────────────────────────────────────────────────────────

def apply_entry_transform(entry_obj, armature_obj=None, base_override=None, children_map=None) -> bool:
    """应用 TRANSFORM3D 视口变换。

    锚点优先于骨骼且二者互斥；两种基准都只提供位置，旋转和缩放保持本地映射。
    """
    try:
        t3d = _attribute_of_type(entry_obj, _t3d_hash(), children_map)
        if t3d is None:
            return False
        local = _t3d_local_matrix(t3d)
        if local is None:
            return False

        if base_override is not None:
            _sync_bone_follow_constraint(entry_obj, None, None)
            entry_obj.matrix_world = base_override @ local
            return True

        jointNo = _entry_joint_no(entry_obj, children_map)
        if _sync_bone_follow_constraint(entry_obj, armature_obj, jointNo):
            entry_obj.matrix_basis = local
        else:
            entry_obj.matrix_world = local
        return True
    except Exception:
        return False


# ── 锚定机制：A 只被一个 action 调用、该 action 只被一个 entry B 触发 → A 以 B 为基点 ──

def _iter_root_bodies(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ENTRY")


def _iter_root_actions(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ACTION")


def build_anchor_map(root_obj, children_map=None):
    """构建唯一 Action 调用、唯一 PTLIFE 触发关系导出的 Entry 锚定映射。

    批量调用应传入预建属性映射；自锚定不写入结果。
    """
    from ..efx_format.hashes import PTLIFE

    if children_map is None:
        children_map = build_entry_attr_map(root_obj)

    callers = {}
    for play in _iter_root_actions(root_obj):
        pp = getattr(play, "efx_play", None)
        if pp is None:
            continue
        for entry in getattr(pp, "entries", []):
            if not getattr(entry, "is_emitter", False):
                continue
            for tgt in getattr(entry, "targets", []):
                body = getattr(tgt, "body_ptr", None)
                if body is not None:
                    callers.setdefault(body, set()).add(play)

    triggers = {}
    for body in _iter_root_bodies(root_obj):
        for blk in _iter_entry_attributes(body, children_map):
            try:
                if int(blk.efx_block.type_hash_str) != PTLIFE:
                    continue
            except Exception:
                continue
            ref = getattr(blk, "efx_ptlife_ref", None)
            if ref is None:
                continue
            play = getattr(ref, "relation_play_ptr", None)
            if play is not None:
                triggers.setdefault(play, set()).add(body)

    anchor = {}
    for body, play_set in callers.items():
        if len(play_set) != 1:
            continue
        play = next(iter(play_set))
        trig = triggers.get(play)
        if trig is None or len(trig) != 1:
            continue
        b = next(iter(trig))
        if b is not body:   # 不自锚
            anchor[body] = b
    return anchor


def _resolve_order(bodies, anchor):
    """将锚点排在依赖者之前；环关系不继续递归。"""
    ordered = []
    placed = set()

    def visit(b, stack):
        if b in placed:
            return
        if b in stack:
            return
        a = anchor.get(b)
        if a is not None and a in bodies:
            stack.add(b)
            visit(a, stack)
            stack.discard(b)
        if b not in placed:
            ordered.append(b)
            placed.add(b)

    for b in bodies:
        visit(b, set())
    return ordered


def place_single_entry(entry_obj, armature_obj=None, use_anchor=True) -> bool:
    """同步单个 Entry；锚定时先求值基点的最新世界矩阵。"""
    base_override = None
    if use_anchor:
        root = _rc.find_root_collection(entry_obj)
        if root is not None:
            try:
                a = build_anchor_map(root).get(entry_obj)
                if a is not None:
                    bpy.context.view_layer.update()
                    base_override = a.matrix_world.copy()
            except Exception:
                base_override = None
    ok = apply_entry_transform(entry_obj, armature_obj, base_override=base_override)
    # 使约束与 matrix_basis 变更立即反映到后续读取。
    bpy.context.view_layer.update()
    return ok


def sync_all_transform3d(root_obj, armature_obj=None, use_anchor=True) -> int:
    """同步根下全部 Entry，锚定时先同步基点；返回成功处理数。"""
    # 属性映射在整个批次复用，并限定为当前根。
    children_map = build_entry_attr_map(root_obj)
    bodies = list(_iter_root_bodies(root_obj))
    anchor = build_anchor_map(root_obj, children_map) if use_anchor else {}
    order = _resolve_order(bodies, anchor) if anchor else bodies

    n = 0
    seen = set()
    for body in order:
        base_override = None
        a = anchor.get(body)
        if a is not None and a in seen:
            # 读取基点前先求值其刚更新的约束和 matrix_basis。
            bpy.context.view_layer.update()
            base_override = a.matrix_world.copy()
        if apply_entry_transform(body, armature_obj, base_override=base_override, children_map=children_map):
            n += 1
        seen.add(body)
    # 使整个批次的变更可被紧随其后的调用读取。
    bpy.context.view_layer.update()
    return n


# ── 算子：刷新特效体位置 ──────────────────────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """按 TRANSFORM3D、骨骼和锚定关系刷新 Entry 视口位置。"""

    bl_idname      = "efx.sync_transform_to_view"
    bl_label       = "Refresh Entry Positions"
    bl_description = ("Recompute every entry's position from its TRANSFORM3D and bound bone "
                      "(PARENTOPTIONS.bone_lim) using the selected armature (visual only, not written to file)")
    bl_options     = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from .add_ops import get_active_efx_root
            root = get_active_efx_root(context)
        except Exception:
            root = None
        if root is None:
            root = _rc.find_root_collection(context.active_object)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found (select an Active EFX or an EFX object)")
            return {"CANCELLED"}
        armature = getattr(context.scene, "efx_armature", None)
        use_anchor = getattr(context.scene, "efx_anchor_placement", True)
        n = sync_all_transform3d(root, armature, use_anchor=use_anchor)
        self.report({"INFO"}, f"Refreshed {n} entry position(s)")
        return {"FINISHED"}


def _armature_poll(self, obj):
    """Scene.efx_armature 选择器只接受骨架对象。"""
    return obj.type == "ARMATURE"


_CLASSES = (EFX_OT_sync_transform,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_armature = bpy.props.PointerProperty(
        name="Armature",
        description="Skeleton used to position effect entries by their bound bone (PARENTOPTIONS.bone_lim → MhBone_NNN)",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    bpy.types.Scene.efx_anchor_placement = bpy.props.BoolProperty(
        name="Anchor to triggering entry",
        description="定位时：若某 entry 只被一个 action 调用、且该 action 只被一个 entry 触发，"
                    "则前者以后者为基点（优先于自身绑定骨骼）。默认开",
        default=True,
    )
    bpy.types.Scene.efx_blender_coords = bpy.props.BoolProperty(
        name="Blender coordinate display",
        description="字段里的 XYZ 坐标按 Blender 约定显示/编辑：长度 /100、Y/Z 交换并取负、"
                    "角度交换取负、缩放仅交换。仅作用于已知单位的字段；不改存储原值。默认关",
        default=False,
    )
    bpy.types.Scene.efx_show_all_fields = bpy.props.BoolProperty(
        name="Show all fields",
        description="显示全部字段（关闭按模式过滤）。默认关：由模式字段（如 velocityType）"
                    "决定只显示当前生效的字段，其余隐藏（值仍保留，纯视觉）。",
        default=False,
    )


def unregister():
    try:
        del bpy.types.Scene.efx_armature
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_anchor_placement
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_blender_coords
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_show_all_fields
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
