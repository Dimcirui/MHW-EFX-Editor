"""
blender_efx/transform_sync.py  —  TRANSFORM3D + PARENTOPTIONS → body empty 视口定位

把每个 body 的基础变换摆到视口做**可视化代理**（单向，不反写、不参与导出）：
  - 基准 = 该 body 绑定骨骼（PARENTOPTIONS.bone_lim）的世界位置；
    bone_lim = -1 / 255 / 找不到对应骨骼 → 以世界原点为基准（=旧行为）。
  - 在基准之上叠加 TRANSFORM3D 的 translate/rotate/resize（基础值）。
  - 一次性烘焙到 body empty 的 matrix_world（不建父子约束，不跟随骨架 pose）。

⚠ object transform **不参与导出**（导出只读字段/data_bytes），纯可视、零字节风险。

骨骼映射（用户确认）：
  - MHW_Model_Editor 把骨骼命名为 MhBone_<boneFunction 补零3位>；255 是"无"哨兵。
  - EFX 的 bone_lim 即 boneFunction → 目标骨骼名 = f"MhBone_{bone_lim:03d}"。
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


def _fixed3(float6_value):
    """从 FLOAT6 取基础三元组（idx 0/2/4）。"""
    v = list(float6_value)
    return (v[0], v[2], v[4])


# ── 取块/字段 ─────────────────────────────────────────────────────────────────

def _iter_body_blocks(body_obj):
    """枚举 body 下的 EFX_BLOCK 子对象。"""
    for blk in bpy.data.objects:
        if blk.parent is body_obj and blk.get("~TYPE") == "EFX_BLOCK":
            yield blk


def _block_of_type(body_obj, type_hash):
    """返回 body 下第一个指定 type_hash 的 EFX_BLOCK（无则 None）。"""
    for blk in _iter_body_blocks(body_obj):
        try:
            if int(blk.efx_block.type_hash_str) == type_hash:
                return blk
        except Exception:
            continue
    return None


def _body_bone_lim(body_obj):
    """读 body 的 PARENTOPTIONS.bone_lim（int）；无 PARENTOPTIONS/字段 → None。"""
    po = _block_of_type(body_obj, _parentopts_hash())
    if po is None:
        return None
    try:
        for it in po.efx_block.field_items:
            if it.ori_name == "bone_lim":
                return int(it.int_value)
    except Exception:
        pass
    return None


def _t3d_local_matrix(t3d_block):
    """把 TRANSFORM3D 块的 translate/rotate/resize 组装成 Blender 世界空间变换矩阵。
    使用 game→Blender 轴交换（M_G2B），适用于无骨骼基准的情形。"""
    vals = {}
    try:
        for it in t3d_block.efx_block.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)
    except Exception:
        return None

    loc = Vector(game_loc_to_blender(*vals["translate"])) if "translate" in vals else Vector((0, 0, 0))
    if "rotate" in vals:
        rot = Euler(game_rot_to_blender(*vals["rotate"]), "XYZ").to_matrix().to_4x4()
    else:
        rot = Matrix.Identity(4)
    if "resize" in vals:
        sx, sy, sz = game_scale_to_blender(*vals["resize"])
    else:
        sx = sy = sz = 1.0
    scl = Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))
    return Matrix.Translation(loc) @ rot @ scl


def _t3d_local_matrix_game(t3d_block):
    """把 TRANSFORM3D 块的 translate/rotate/resize 组装成游戏空间变换矩阵。
    不做 Y/Z 轴交换——骨骼的 matrix_local 已内嵌 M_G2B，有骨骼时用此函数避免双重转换。"""
    vals = {}
    try:
        for it in t3d_block.efx_block.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)
    except Exception:
        return None

    if "translate" in vals:
        gx, gy, gz = vals["translate"]
        loc = Vector((gx / 100.0, gy / 100.0, gz / 100.0))
    else:
        loc = Vector((0, 0, 0))
    if "rotate" in vals:
        gx, gy, gz = vals["rotate"]
        rot = Euler((radians(gx), radians(gy), radians(gz)), "XYZ").to_matrix().to_4x4()
    else:
        rot = Matrix.Identity(4)
    if "resize" in vals:
        sx, sy, sz = vals["resize"]
    else:
        sx = sy = sz = 1.0
    scl = Matrix.Diagonal(Vector((sx, sy, sz, 1.0)))
    return Matrix.Translation(loc) @ rot @ scl


# ── 骨骼基准矩阵 ─────────────────────────────────────────────────────────────

# 视为"无绑定骨骼 / 原点基准"的 bone_lim 哨兵值。
_BONE_NONE_SENTINELS = (-1, 255)


def bone_base_matrix(armature_obj, bone_lim):
    """
    返回绑定骨骼的世界 rest 矩阵；以下情形返回 None（→ 以世界原点为基准）：
      - armature_obj 为空 / 非骨架
      - bone_lim 为 None / -1 / 255
      - 骨架中无名为 MhBone_<bone_lim:03d> 的骨骼
    """
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return None
    if bone_lim is None or bone_lim in _BONE_NONE_SENTINELS or bone_lim < 0:
        return None
    bone_name = f"MhBone_{bone_lim:03d}"
    bone = armature_obj.data.bones.get(bone_name)
    if bone is None:
        return None
    # rest 位姿下骨骼 head 的世界矩阵（matrix_local 是骨架空间的 rest 矩阵）
    return armature_obj.matrix_world @ bone.matrix_local


# ── 应用到单个 body ──────────────────────────────────────────────────────────

def apply_body_transform(body_obj, armature_obj=None) -> bool:
    """
    按 body 的 TRANSFORM3D（基础变换）+ PARENTOPTIONS（bone_lim 绑定骨骼）
    计算 body empty 的 matrix_world 并写入。返回是否成功。

    有骨骼时 TRANSFORM3D 使用游戏坐标原样（不做 Y/Z 交换），因为骨骼的
    matrix_local 已内嵌 M_G2B 旋转，直接叠加可正确还原朝向。
    无骨骼时使用 M_G2B 轴交换后的 Blender 坐标（原有行为）。
    """
    try:
        t3d = _block_of_type(body_obj, _t3d_hash())
        if t3d is None:
            return False
        base = bone_base_matrix(armature_obj, _body_bone_lim(body_obj))
        if base is not None:
            local = _t3d_local_matrix_game(t3d)
        else:
            local = _t3d_local_matrix(t3d)
        if local is None:
            return False
        body_obj.matrix_world = (base @ local) if base is not None else local
        return True
    except Exception:
        return False


def sync_all_transform3d(root_obj, armature_obj=None) -> int:
    """
    对 root_obj 下所有 EFX_BODY，按 TRANSFORM3D + bone_lim 摆位。返回处理数量。
    供导入后一次性摆位、以及"刷新特效体位置"算子调用。
    """
    n = 0
    for body in bpy.data.objects:
        if body.get("~TYPE") != "EFX_BODY" or body.parent is not root_obj:
            continue
        if apply_body_transform(body, armature_obj):
            n += 1
    return n


# ── 算子：刷新特效体位置 ──────────────────────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """按 TRANSFORM3D + 绑定骨骼(bone_lim) 重新计算并摆放所有特效体（视口可视化，不影响导出）"""

    bl_idname      = "efx.sync_transform_to_view"
    bl_label       = "Refresh Body Positions"
    bl_description = ("Recompute every body's position from its TRANSFORM3D and bound bone "
                      "(PARENTOPTIONS.bone_lim) using the selected armature (visual only, not written to file)")
    bl_options     = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from .add_ops import get_active_efx_root
            root = get_active_efx_root(context)
        except Exception:
            root = None
        if root is None:
            cur = context.active_object
            while cur is not None and cur.get("~TYPE") != "EFX_ROOT":
                cur = cur.parent
            root = cur
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found (select an Active EFX or an EFX object)")
            return {"CANCELLED"}
        armature = getattr(context.scene, "efx_armature", None)
        n = sync_all_transform3d(root, armature)
        self.report({"INFO"}, f"Refreshed {n} body position(s)")
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
        description="Skeleton used to position effect bodies by their bound bone (PARENTOPTIONS.bone_lim → MhBone_NNN)",
        type=bpy.types.Object,
        poll=_armature_poll,
    )


def unregister():
    try:
        del bpy.types.Scene.efx_armature
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
