"""将 TRANSFORM3D 与 PARENTOPTIONS 映射为 Entry 的视口变换。

维护约束：这是单向视口代理，Object 变换不得反写或参与 EFX 导出。TRANSFORM3D
FLOAT6 的基础值使用索引 0/2/4，按分量写入 Entry 的 location / rotation_euler / scale，
rotation_mode 由 rotationOrder 决定。骨骼只通过 Copy Location 叠加当前位置；无效绑定
必须移除约束。
"""

from math import radians

import bpy
from bpy.app.handlers import persistent
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


# 旋转除交换分量外还要换算组合顺序，见 blender_rotation_mode。

#: rotationOrder 缺省值 4（ZXY）。
DEFAULT_ROT_ORDER = "ZXY"


def rot_order_of(attribute):
    """读属性的 rotationOrder 并换成顺序串；缺字段时返回默认顺序。

    取值表与模拟层共用，TRANSFORM3D、MESH 等同一套；VELOCITY3D 的 rotOrder 不适用。
    """
    from ..efx_format.sim.vecmath import ROT_ORDER_TRANSFORM, rot_order_name
    try:
        for it in attribute.efx_block.field_items:
            if it.ori_name == "rotationOrder":
                return rot_order_name(it.int_value, ROT_ORDER_TRANSFORM)
    except Exception:
        pass
    return DEFAULT_ROT_ORDER


def _game_rot_matrix(gx, gy, gz, order=DEFAULT_ROT_ORDER):
    """按顺序串构建游戏空间旋转矩阵；先写的轴先作用，ZXY 即 ``Ry @ Rx @ Rz``。"""
    ang = {"X": gx, "Y": gy, "Z": gz}
    m = Matrix.Identity(3)
    for axis in order:
        m = Matrix.Rotation(radians(ang[axis]), 3, axis) @ m
    return m


def _g2b_basis():
    """游戏→Blender 的基变换矩阵 M = Rx(+90°)（游戏 Y-up → Blender Z-up）。"""
    return Matrix.Rotation(radians(90), 3, 'X')


def game_rot_matrix_blender(gx, gy, gz, order=DEFAULT_ROT_ORDER):
    """无骨骼基准时：游戏旋转换到 Blender 世界 = M · R_game · M⁻¹，返回 4x4。"""
    M = _g2b_basis()
    R = _game_rot_matrix(gx, gy, gz, order)
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
    """按父对象建立属性映射，供批量变换同步复用。"""
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


#: 游戏轴到 Blender 轴的置换，与平移、缩放的分量交换一致。
_G2B_AXIS = {"X": "X", "Y": "Z", "Z": "Y"}


def blender_rotation_mode(order):
    """游戏旋转顺序串 → 逐分量等价的 Blender rotation_mode。

    配合 ``game_rot_to_blender`` 的分量，Euler 与 ``M·R_game·M⁻¹`` 完全相同，
    所以 Entry 可以直接用 rotation_euler 表示游戏旋转。
    """
    return "".join(_G2B_AXIS[c] for c in order)


def t3d_channels(t3d_attribute):
    """返回 TRANSFORM3D 静态值对应的 (location, rotation_mode, rotation_euler, scale)。

    读取失败返回 None；缺少的分组取单位值。
    """
    vals = {}
    try:
        for it in t3d_attribute.efx_block.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)
    except Exception:
        return None
    loc = game_loc_to_blender(*vals.get("translate", (0.0, 0.0, 0.0)))
    rot = game_rot_to_blender(*vals.get("rotate", (0.0, 0.0, 0.0)))
    scl = game_scale_to_blender(*vals.get("resize", (1.0, 1.0, 1.0)))
    return loc, blender_rotation_mode(rot_order_of(t3d_attribute)), rot, scl


def channels_matrix(ch):
    """把 ``t3d_channels`` 的结果组成 4x4 矩阵。"""
    loc, mode, rot, scl = ch
    return (Matrix.Translation(Vector(loc)) @ Euler(rot, mode).to_matrix().to_4x4()
            @ Matrix.Diagonal(Vector((scl[0], scl[1], scl[2], 1.0))))


_CHANNEL_PROPS = ("location", "rotation_euler", "scale")


def _write_channels(obj, ch, skip=frozenset()):
    """写入 Object 的变换通道；``skip`` 中的 (data_path, index) 不写。"""
    loc, mode, rot, scl = ch
    # 先切换模式再写值：切换 rotation_mode 时 Blender 会换算旧值。
    if obj.rotation_mode != mode:
        obj.rotation_mode = mode
    for prop, val in zip(_CHANNEL_PROPS, (loc, rot, scl)):
        target = getattr(obj, prop)
        for i in range(3):
            if (prop, i) not in skip:
                target[i] = val[i]


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

def apply_entry_transform(entry_obj, armature_obj=None, children_map=None) -> bool:
    """按 TRANSFORM3D 写入 Entry 的变换通道，并同步骨骼约束。

    批量调用应传入 ``children_map``，避免逐个扫场景。
    """
    try:
        t3d = _attribute_of_type(entry_obj, _t3d_hash(), children_map)
        if t3d is None:
            return False
        ch = t3d_channels(t3d)
        if ch is None:
            return False
        _sync_bone_follow_constraint(
            entry_obj, armature_obj, _entry_joint_no(entry_obj, children_map))
        _write_channels(entry_obj, ch)
        return True
    except Exception:
        return False


def _iter_root_bodies(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ENTRY")


def place_single_entry(entry_obj, armature_obj=None) -> bool:
    """同步单个 Entry，并使结果立即可被后续读取。"""
    ok = apply_entry_transform(entry_obj, armature_obj)
    bpy.context.view_layer.update()
    return ok


def sync_all_transform3d(root_obj, armature_obj=None) -> int:
    """同步根下全部 Entry，返回成功处理数。"""
    children_map = build_entry_attr_map(root_obj)
    n = 0
    for body in _iter_root_bodies(root_obj):
        if apply_entry_transform(body, armature_obj, children_map=children_map):
            n += 1
    bpy.context.view_layer.update()
    return n


# ── 算子：刷新特效体位置 ──────────────────────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """按 TRANSFORM3D 和骨骼刷新 Entry 视口位置。"""

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
        n = sync_all_transform3d(root, armature)
        self.report({"INFO"}, f"Refreshed {n} entry position(s)")
        return {"FINISHED"}


# ── 视口点选：只有 Entry 可点 ────────────────────────────────────────────────

# 与 Entry 重叠的辅助 empty 尺寸为 0，视口点击只命中 Entry。不能改用 hide_select 或隐藏：
# 那样对象进不了 selected_objects，大纲多选后的删除、复制等操作会失效。
_HELPER_TYPES = frozenset(("EFX_ATTRIBUTE", "EFX_TIML", "EFX_ACTION", "EFX_EXTERN",
                           "EFX_SUBSELECT", "EFX_UVS_LINK_ITEM"))
#: 旧版本创建时的默认尺寸；其他尺寸是用户自设的，保留。
_LEGACY_HELPER_SIZES = (0.1, 0.12)


def shrink_legacy_helper_empties() -> int:
    """把旧文件中辅助 empty 的默认尺寸改为 0，返回修改数。"""
    n = 0
    for o in bpy.data.objects:
        if o.type != "EMPTY" or o.library is not None or o.get("~TYPE") not in _HELPER_TYPES:
            continue
        if any(abs(o.empty_display_size - s) < 1e-6 for s in _LEGACY_HELPER_SIZES):
            o.empty_display_size = 0.0
            n += 1
    return n


@persistent
def _on_load(*_args):
    try:
        shrink_legacy_helper_empties()
    except Exception:
        pass


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
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    try:
        del bpy.types.Scene.efx_armature
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
