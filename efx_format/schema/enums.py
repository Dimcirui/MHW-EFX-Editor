# -*- coding: utf-8 -*-
"""
efx_format/schema/enums.py — 共享枚举 / 位定义
"""
from .fields_model import EnumDef, BitDef

# ─────────────────────────────────────────────────────────────────────────────
# 共享枚举 / 位定义——选项据 annotations.py / 实机记忆 / 行内考据。
# 供各块字段引用；enum/bitmask 只改 UI widget 元数据，底层 spec（int/short）不变→byte 不变。
# ⚠ 越界值（如 shapeType≥3、homingTarget 的 cycle 值）由 Blender 层回退显示原整数。
# ─────────────────────────────────────────────────────────────────────────────

ENUM_SHAPE_TYPE3D = EnumDef("ShapeType3D", [
    (0, "Box", "立方体"), 
    (1, "Sphere", "球面"), 
    (2, "Cylinder", "圆环面"), 
    (3, "Point", "点"),
])
ENUM_SHAPE_TYPE2D = EnumDef("ShapeType2D", [
    (0, "Square", "方形"), 
    (1, "Circle", "圆形"), 
    (2, "Point", "点"),
])
ENUM_COLLISION_PHYSICS = EnumDef("CollisionPhysics", [
    (0, "Fall Through", "穿透坠落"), 
    (1, "Bounce and Fade", "反弹并渐隐"),
    (2, "Bounce and Fall Through", "反弹后穿透坠落"), 
    (3, "Remaining after Bouncing", "反弹后残留"),
])
ENUM_PTLIFE_STATUS = EnumDef("PtLifeStatus", [
    (0, "On Spawn", "生成时"), 
    (1, "Appear", "出现"), 
    (2, "Keep", "保持"),
    (3, "Vanish", "消失"), 
    (4, "On End", "结束时"), 
    (-1, "Unknown", "未知"),
])
# needs further investigation, this should be same as AxisDirection6
ENUM_RAYCAST_DIR = EnumDef("RaycastDirection", [
    (0, "Left", "左"), 
    (1, "Down", "下"), 
    (2, "Forward", "前"),
    (3, "Right", "右"), 
    (4, "Up", "上"), 
    (5, "Backward", "后"),
])
ENUM_HOMING_TARGET = EnumDef("HomingTarget", [
    (0, "Spawn Point", "生成点"), 
    (1, "Model Origin", "模型原点"),
    (2, "World Origin", "世界原点"), 
    (3, "World Origin", "世界原点"),
])
ENUM_HOMING_FORCEFIELD = EnumDef("HomingForceFieldMode", [
    (0, "Normal", "普通"), 
    (1, "Exclusion", "排除场"), 
    (2, "Deceleration", "减速场"),
    (3, "Escape-Catch", "逃逸抓取场"), 
    (4, "Acceleration", "加速场"),
])
ENUM_HOMING_VANISH = EnumDef("HomingVanishMode", [
    (0, "None", "不触发"), 
    (1, "Cancel Infinite Life", "取消无限寿命"),
    (2, "Vanish Immediately", "立即消失"),
])
ENUM_RENDER_LAYER = EnumDef("RenderLayerMode", [
    (0, "3D Billboard", "3D Billboard"), 
    (2, "Plane", "Plane"),
    (3, "Bypass Tonemap", "无视色调滤镜"),
    (6, "3D Billboard v6", "3D Billboard 变体6"), 
    (7, "3D Billboard v7", "3D Billboard 变体7"),
    (8, "3D Billboard v8", "3D Billboard 变体8"), 
    (9, "3D Billboard v9", "3D Billboard 变体9"),
])
ENUM_SHADER_CONTROL = EnumDef("ShaderControlFlag", [
    (0, "No Alpha", "无 alpha"), 
    (1, "Alpha Enabled", "启用 alpha"),
    (2, "Emissive", "自发光"), 
    (3, "Inverted Color + Alpha", "反色 + alpha"), 
    (6, "Greyscale", "灰度"),
])
ENUM_ROTATION_MODE = EnumDef("RotationMode", [
    (0, "Plane Rotation", "平面旋转系"), 
    (1, "Plane + Random Dir", "平面旋转 + 随机正反"),
    (2, "Spin Velocity", "自旋速度系"), 
    (3, "Spin + Random Dir", "自旋速度 + 随机正反"),
])

# PARENTOPTIONS 逐轴跟随模式：0/1/2 三字段共享，值 3 各字段不同（见下）
_TRACKING_BASE = [
    (0, "Track Map Center Absolutely", "绝对追踪地图中心"),
    (1, "Track Player Movement", "追踪玩家移动"),
    (2, "Do not track further", "不再追踪后续移动"),
]
ENUM_TRACKING_POS = EnumDef("TrackingModePos",
    _TRACKING_BASE + [(3, "Ignore Basic Transform", "忽略基础变换")])   # translation / scale
ENUM_TRACKING_ANGLE = EnumDef("TrackingModeAngle",
    _TRACKING_BASE + [(3, "Snap to Angle And Track", "对齐到角度并追踪")])  # angle

BITS_ENABLE_VELOCITY = [(0x1, "Enable Velocity", "启用速度"), (0x2, "Enable Acceleration", "启用加速度")]
BITS_SPIN_AXIS = [(0x1, "X", "X"), (0x2, "Y", "Y"), (0x4, "Z", "Z")]
BITS_RANDOMFIX_TABLE = [(1 << _i, "Table %d" % _i, "表 %d" % _i) for _i in range(8)]

_AXIS_DIRECTION6 = EnumDef("AxisDirection6", [
    (0, "Left", "左"),  # +X
    (1, "Up", "上"),    # +Y
    (2, "Front", "前"), # +Z
    (3, "Right", "右"), # -X
    (4, "Down", "下"),  # -Y
    (5, "Back", "后"),  # -Z
])
_ROT_ORDER6 = EnumDef("RotOrder", [
    (0, "XYZ", "XYZ"), (1, "XZY", "XZY"), (2, "YXZ", "YXZ"),
    (3, "YZX", "YZX"), (4, "ZXY", "ZXY"), (5, "ZYX", "ZYX"),
])
_VELOCITY_TYPE = EnumDef("VelocityType", [
    (0, "Directional", "定向"),
    (1, "DirectionalSpread", "定向扩散"),
    (2, "Radial", "径向"),
    (3, "EmitterMotion", "发射器运动"),
])
