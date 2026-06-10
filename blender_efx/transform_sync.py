"""
blender_efx/transform_sync.py  —  TRANSFORM3D 字段 → body empty 视口变换（单向）

把 TRANSFORM3D 块的 translate/rotate/resize（基础变换）映射到其所属 body empty
对象的 Blender transform，做**可视化代理**。单向：编辑字段 → empty 动；
**不反写**（移动 empty 不改字段）。

⚠ object transform **不参与导出**（导出只读字段/data_bytes），故纯可视、零字节风险。

坐标约定（用户实测确认）：
  - 平移：game 值 /100；轴 game(X,Y,Z) → blender(X, -Z, Y)。
      例 gX=30,gY=0,gZ=156 → b(0.30, -1.56, 0)（+X 0.3m、-Y 1.56m）
  - 旋转：角度→弧度；blender Z 旋转 = game Y（已确认）；X/-Z 轴按平移同款交换推得，符号待验。
  - 缩放：Y/Z 互换、不除 100。
TRANSFORM3D 的 translate/rotate/resize 是 FLOAT6（XYZ type 0），基础值在 idx 0/2/4（1/3/5 是 jitter）。
"""

from math import radians

import bpy


def _t3d_hash() -> int:
    from ..efx_format.hashes import TRANSFORM3D
    return TRANSFORM3D


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


def apply_transform3d_to_body(block_obj) -> bool:
    """
    读 block_obj（TRANSFORM3D 块）的 translate/rotate/resize 字段，
    换算后写到其父 body empty 的 location/rotation_euler/scale。
    返回是否成功。失败安全返回 False。
    """
    try:
        body = block_obj.parent
        if body is None or body.get("~TYPE") != "EFX_BODY":
            return False
        bp = getattr(block_obj, "efx_block", None)
        if bp is None:
            return False

        vals = {}
        for it in bp.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)

        if "translate" in vals:
            body.location = game_loc_to_blender(*vals["translate"])
        if "rotate" in vals:
            body.rotation_mode = "XYZ"
            body.rotation_euler = game_rot_to_blender(*vals["rotate"])
        if "resize" in vals:
            body.scale = game_scale_to_blender(*vals["resize"])
        return True
    except Exception:
        return False


def sync_all_transform3d(root_obj) -> int:
    """
    对 root_obj 下所有 TRANSFORM3D 块，应用到各自 body empty。返回处理数量。
    供导入后一次性摆位、以及"刷新到视口"算子调用。
    """
    th = _t3d_hash()
    n = 0
    for blk in bpy.data.objects:
        if blk.get("~TYPE") != "EFX_BLOCK":
            continue
        # 仅 root_obj 旗下（blk.parent=body, body.parent=root）
        body = blk.parent
        if body is None or body.parent is not root_obj:
            continue
        try:
            bp = blk.efx_block
            if int(bp.type_hash_str) != th:
                continue
        except Exception:
            continue
        if apply_transform3d_to_body(blk):
            n += 1
    return n


# ── 算子：手动刷新（兜底 / 一键全部应用）─────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """把所有 TRANSFORM3D 的基础变换应用到对应 body empty（视口可视化，不影响导出）"""

    bl_idname      = "efx.sync_transform_to_view"
    bl_label       = "TRANSFORM3D → 视口"
    bl_description = "按 TRANSFORM3D 的平移/旋转/缩放摆放各 body empty（纯可视，不写入文件）"
    bl_options     = {"REGISTER", "UNDO"}

    def execute(self, context):
        # 解析 active EFX root（复用 add_ops 的逻辑）
        try:
            from .add_ops import get_active_efx_root
            root = get_active_efx_root(context)
        except Exception:
            root = None
        if root is None:
            # 兜底：从 active_object 沿 parent 找 root
            cur = context.active_object
            while cur is not None and cur.get("~TYPE") != "EFX_ROOT":
                cur = cur.parent
            root = cur
        if root is None:
            self.report({"ERROR"}, "未找到 EFX_ROOT（请选 Active EFX 或选中 EFX 对象）")
            return {"CANCELLED"}
        n = sync_all_transform3d(root)
        self.report({"INFO"}, f"已应用 {n} 个 TRANSFORM3D 变换到视口")
        return {"FINISHED"}


_CLASSES = (EFX_OT_sync_transform,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
