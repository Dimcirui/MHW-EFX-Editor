"""
blender_efx/transform_sync.py  —  TRANSFORM3D + PARENTOPTIONS → body empty 视口定位

把每个 body 的基础变换摆到视口做**可视化代理**（单向，不反写、不参与导出）：
  - 基准 = 该 body 绑定骨骼（PARENTOPTIONS.jointNo）的世界位置；
    jointNo = -1 / 255 / 找不到对应骨骼 → 以世界原点为基准（=旧行为）。
  - 在基准之上叠加 TRANSFORM3D 的 translate/rotate/resize（基础值）。
  - 一次性烘焙到 body empty 的 matrix_world（不建父子约束，不跟随骨架 pose）。

⚠ object transform **不参与导出**（导出只读字段/data_bytes），纯可视、零字节风险。

骨骼映射（用户确认）：
  - MHW_Model_Editor 把骨骼命名为 MhBone_<boneFunction 补零3位>；255 是"无"哨兵。
  - EFX 的 jointNo 即 boneFunction → 目标骨骼名 = f"MhBone_{jointNo:03d}"。
  - 骨架由 N 面板的 Scene.efx_armature 选择器指定。

坐标约定（用户实测确认）：
  - 平移：game 值 /100；轴 game(X,Y,Z) → blender(X, -Z, Y)。
  - 旋转：角度→弧度；blender(X,-Z,Y)=game(X,Y,Z) 同款轴交换。
  - 缩放：Y/Z 互换、不除 100。
TRANSFORM3D 的 translate/rotate/resize 是 FLOAT6（XYZ type 0），基础值在 idx 0/2/4（1/3/5 是 jitter）。
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
    """旋转：度→弧度 + 轴交换（bZ=gY 已确认；bX=gX、bY=-gZ 待验）。"""
    return (radians(gx), radians(-gz), radians(gy))


def game_scale_to_blender(gx, gy, gz):
    """缩放：Y/Z 互换、不除 100。"""
    return (gx, gz, gy)


# ── 旋转：基变换（共轭），而非朴素交换 Euler 分量 ──────────────────────────────
#
# ⚠ 关键：旋转不是向量，不能像平移那样交换分量。游戏 Euler 必须作为「同一旋转换基」处理：
#   R_blender = M · R_game · M⁻¹    （M = Rx(+90°)，游戏 Y-up → Blender Z-up）
# 且游戏内 Euler 组合顺序实测为 Z 先转（R = Rx·Ry·Rz，向量先受 Rz 作用）。
# 实测六组单/组合旋转（含 (90,0,90)→-X、(45,0,90)→-X）全部吻合本式；朴素交换法仅单轴碰巧对。

def _game_rot_matrix(gx, gy, gz):
    """游戏 Euler(度) → 3x3 旋转矩阵，按游戏组合顺序 **Ry·Rx·Rz**（Rz 先作用于向量，X 在 Y 之后）。

    ⚠ 确定性验证（unsheath.efx，几何真值，非目测）：zhu 是连线 mesh，每根指向下一颗星(xing)。
    用星星真实坐标算"星→星"方向，对照各 zhu 原始 rotate 在两种顺序下的 mesh 朝向：
      YXZ 全部命中（夹角 1.6~5.8°，纯取整误差）；Rx·Ry·Rz 偏 16~56°（把 gz=0 的剑全挤向一处）。
    故 Ry·Rx·Rz 为准。注意：本函数**只影响视口显示，不碰导出字节**——改它绝不会影响游戏文件。
    用显式 Matrix.Rotation 逐轴相乘，避开 Blender Euler order 字符串语义的歧义。
    """
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
    """枚举 entry 下的 EFX_ATTRIBUTE 子对象。

    children_map（可选）：build_entry_attr_map() 的结果——批量场景（如
    sync_all_transform3d/build_anchor_map 遍历全部 entry）应传，否则每次调用都
    全场景扫 bpy.data.objects，是 O(entry 数 × 场景对象数) 的性能陷阱（2026-07
    曾在此把"导入即摆位"拖得很慢，场景里已加载的其它 EFX 文件越多越明显，已修）。
    """
    if children_map is not None:
        yield from children_map.get(entry_obj, [])
        return
    for blk in bpy.data.objects:
        if blk.parent is entry_obj and blk.get("~TYPE") == "EFX_ATTRIBUTE":
            yield blk


def build_entry_attr_map(root_obj):
    """一次性扫 bpy.data.objects，按 .parent 分组 EFX_ATTRIBUTE 子对象，返回
    {entry: [attrs]}。供批量摆位（sync_all_transform3d/build_anchor_map）替代
    逐 entry 各扫一遍全场景的写法。"""
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


# ── 骨骼基准矩阵 ─────────────────────────────────────────────────────────────

# 视为"无绑定骨骼 / 原点基准"的 jointNo 哨兵值。
_BONE_NONE_SENTINELS = (-1, 255)


def bone_base_matrix(armature_obj, jointNo):
    """
    返回绑定骨骼的世界 rest 矩阵；以下情形返回 None（→ 以世界原点为基准）：
      - armature_obj 为空 / 非骨架
      - jointNo 为 None / -1 / 255
      - 骨架中无名为 MhBone_<jointNo:03d> 的骨骼
    """
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return None
    if jointNo is None or jointNo in _BONE_NONE_SENTINELS or jointNo < 0:
        return None
    bone_name = f"MhBone_{jointNo:03d}"
    bone = armature_obj.data.bones.get(bone_name)
    if bone is None:
        return None
    # rest 位姿下骨骼 head 的世界矩阵（matrix_local 是骨架空间的 rest 矩阵）
    return armature_obj.matrix_world @ bone.matrix_local


# ── 应用到单个 entry ──────────────────────────────────────────────────────────

def apply_entry_transform(entry_obj, armature_obj=None, base_override=None, children_map=None) -> bool:
    """
    按 entry 的 TRANSFORM3D（基础变换）+ PARENTOPTIONS（jointNo 绑定骨骼）
    计算 entry empty 的 matrix_world 并写入。返回是否成功。

    base_override：锚定机制传入「基点 entry 的 matrix_world」。提供时它**优先于**骨骼
    （锚定 entry 间接继承基点 entry 的位置）。

    ⚠ 三类基准都用 **M 共轭的 blender 局部** `_t3d_local_matrix`，局部朝向统一交给
    M_G2B 轴交换，与无骨骼路径一致 —— 关键是基准只贡献**位置**，不贡献朝向：
      - 骨骼基准：只取骨骼世界位置(head)，**不继承骨骼 rest 朝向**（与 uvc_preview 同款）。
        Blender 骨骼默认沿 +Y，指向 +Z 的 MhBone 其 matrix_local 内嵌 +90°X 伪旋转，
        整体继承会让 entry 平白绕 X 多转 90°（绑定竖直骨骼时尤其明显）。故只取 translation。
      - 锚定基准：基点是另一个 EFX entry 的 Blender 空间矩阵，同样用 blender 局部叠加。
      - 无基准：直接 blender 局部（原有行为）。
    """
    try:
        t3d = _attribute_of_type(entry_obj, _t3d_hash(), children_map)
        if t3d is None:
            return False
        local = _t3d_local_matrix(t3d)              # 统一：blender 空间（M 共轭）
        if local is None:
            return False
        if base_override is not None:
            base = base_override                    # 锚定：继承基点 entry 的完整矩阵
        else:
            bone = bone_base_matrix(armature_obj, _entry_joint_no(entry_obj, children_map))
            if bone is not None:
                base = Matrix.Translation(bone.to_translation())  # 只取骨骼 head 位置，不继承朝向
            else:
                base = None
        entry_obj.matrix_world = (base @ local) if base is not None else local
        return True
    except Exception:
        return False


# ── 锚定机制：A 只被一个 action 调用、该 action 只被一个 entry B 触发 → A 以 B 为基点 ──

def _iter_root_bodies(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ENTRY")


def _iter_root_actions(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ACTION")


def build_anchor_map(root_obj, children_map=None):
    """构建 entry→anchor_entry 映射（实现用户规则）。

    规则：entryA 仅被一个 action 调用（出现在恰好一个 action 的 PlayEmitter targets 里），
    且该 action 仅被一个 entryB 触发（恰好一个 entry 的 PTLIFE.relation_play_ptr 指向它），
    则 anchor[A] = B。

    children_map（可选）：build_entry_attr_map() 的结果；不传则内部现建一次
    （仍比"逐 entry 各扫一遍全场景"快得多——批量调用方应自建一次并传入复用）。
    """
    from ..efx_format.hashes import PTLIFE

    if children_map is None:
        children_map = build_entry_attr_map(root_obj)

    # action → 它调用的 entry 集合；entry → 调用它的 action 集合
    callers = {}   # body → set(play)
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

    # action → 触发它的 entry 集合（entry 的 PTLIFE.relation_play_ptr）
    triggers = {}  # play → set(body)
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
    """对 entries 做拓扑序：anchor 基点排在被锚 entry 之前；环检测兜底（环内按原序、不锚）。"""
    ordered = []
    placed = set()

    def visit(b, stack):
        if b in placed:
            return
        if b in stack:           # 成环 → 不再深入（环里的锚关系会被忽略）
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
    """摆放单个 entry（锚定感知）。供字段实时编辑回调用：编辑 TRANSFORM3D 时若该 entry
    满足锚定规则，仍以基点 entry 为基准，而非掉回自身骨骼/原点。

    基点 entry 的位置取其当前 matrix_world（编辑的是被锚 entry，自身基点未动 → 有效）。
    """
    base_override = None
    if use_anchor:
        root = _rc.find_root_collection(entry_obj)
        if root is not None:
            try:
                a = build_anchor_map(root).get(entry_obj)
                if a is not None:
                    base_override = a.matrix_world.copy()
            except Exception:
                base_override = None
    return apply_entry_transform(entry_obj, armature_obj, base_override=base_override)


def sync_all_transform3d(root_obj, armature_obj=None, use_anchor=True) -> int:
    """
    对 root_obj 下所有 EFX_ENTRY，按 TRANSFORM3D + jointNo 摆位。返回处理数量。
    供导入后一次性摆位、以及"刷新特效体位置"算子调用。

    use_anchor=True 时启用锚定机制：满足规则的 entry 以基点 entry 的最终位置为基准
    （优先于自身骨骼），并按依赖顺序摆位确保基点先就位。
    """
    # 批量：一次性建 {entry: [attribute 子对象]} 映射，下面对每个 entry 的
    # TRANSFORM3D/PARENTOPTIONS/PTLIFE 查找全部复用它，不再各自现场扫全场景
    # bpy.data.objects（每次导入都跑这个函数，曾是明显的性能陷阱，已修）。
    children_map = build_entry_attr_map(root_obj)
    bodies = list(_iter_root_bodies(root_obj))
    anchor = build_anchor_map(root_obj, children_map) if use_anchor else {}
    order = _resolve_order(bodies, anchor) if anchor else bodies

    n = 0
    # 环检测后真正可用的锚集合：基点必须排在自己之前（已就位）
    seen = set()
    for body in order:
        base_override = None
        a = anchor.get(body)
        if a is not None and a in seen:
            base_override = a.matrix_world.copy()
        if apply_entry_transform(body, armature_obj, base_override=base_override, children_map=children_map):
            n += 1
        seen.add(body)
    return n


# ── 算子：刷新特效体位置 ──────────────────────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """按 TRANSFORM3D + 绑定骨骼(jointNo) 重新计算并摆放所有特效体（视口可视化，不影响导出）"""

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
