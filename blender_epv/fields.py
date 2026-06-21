"""
blender_epv/fields.py — EPV record 字段的 PropertyGroup（阶段 3）。

EPVRecordProps 挂到 Object 上（仅 EPV_RECORD 对象使用），承载除 position/rotation
（由 transform 承载）外的全部 record 字段，含 8 槽 epvColor 表（CollectionProperty）。

字段宽度：bpy IntProperty/FloatProperty 均为 32 位，与 EPV record 内字段（int32/float32，
recordID 为 ushort 在范围内）一致，无溢出风险（仅 root 的 uint64/uint32 特殊处理，见 io_tree）。
"""
import bpy
from bpy.props import (
    IntProperty, FloatProperty, StringProperty,
    IntVectorProperty, FloatVectorProperty, CollectionProperty,
)


class EPVColorItem(bpy.types.PropertyGroup):
    """epvColor 一槽（EFX 外观覆盖 slot）。"""
    efxslot: IntProperty(name="EFX Slot", default=0)
    color: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0),
    )
    saturation: FloatProperty(name="Saturation", default=0.0)
    size: IntProperty(name="Size", default=0)
    frequency: FloatProperty(name="Frequency", default=1.0)


class EPVRecordProps(bpy.types.PropertyGroup):
    """一条 EPV record 的全部可编辑字段（position/rotation 见对象 transform）。"""
    # 路径槽（指向 efx）
    path0: StringProperty(name="EFX Path 0", default="")
    path1: StringProperty(name="EFX Path 1", default="")
    path2: StringProperty(name="EFX Path 2", default="")
    path3: StringProperty(name="EFX Path 3", default="")

    # 标量
    padding: IntProperty(name="padding", default=0)
    unknownID: IntProperty(name="unknownID", default=0)
    recordID: IntProperty(name="recordID", default=0)
    boneID: IntProperty(name="boneID", default=-1)
    pb1_paramU1: FloatProperty(name="paramU1", default=0.0)
    pb2_f1: FloatProperty(name="f1", default=1.0)
    pb2_b1: IntProperty(name="b1", default=-128)
    pb2_b2: IntProperty(name="b2", default=13)
    pb2_b3: IntProperty(name="b3", default=1)
    pb2_b4: IntProperty(name="b4", default=0)
    pb2_i1: IntProperty(name="i1", default=6)
    pb2_f2: FloatProperty(name="f2", default=100.0)
    pb2_i2: IntProperty(name="i2", default=512)
    pb2_i3: IntProperty(name="i3", default=-1)

    # 向量
    pb1_paramU0: IntVectorProperty(name="paramU0", size=3)
    pb1_paramU2: IntVectorProperty(name="paramU2", size=4)
    pb1_EFXSubIndex: IntVectorProperty(name="EFXSubIndex", size=2, default=(-1, -1))
    pb1_paramU3: IntVectorProperty(name="paramU3", size=2, default=(-1, -1))
    pb1_EFXSubIndex2: IntVectorProperty(name="EFXSubIndex2", size=2, default=(-1, -1))
    pb1_paramU4: IntVectorProperty(name="paramU4", size=2)
    positionJitter: FloatVectorProperty(name="positionJitter", size=3)
    rotationJitter: FloatVectorProperty(name="rotationJitter", size=3)
    paramW3: IntVectorProperty(name="paramW3", size=2)
    paramW4: IntVectorProperty(name="paramW4", size=3)
    paramW5: FloatVectorProperty(
        name="Effect Scale", size=2, default=(1.0, 0.0),
        description=(
            "Overall effect size multiplier (1.0 = unchanged, 0.5 = half size). "
            "[0] Fixed = base value, [1] Random = random jitter added on top"
        ),
    )
    paramV: IntVectorProperty(name="paramV", size=4)

    # epvColor[8]
    epv_colors: CollectionProperty(type=EPVColorItem)


_CLASSES = (EPVColorItem, EPVRecordProps)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.epv_record = bpy.props.PointerProperty(type=EPVRecordProps)


def unregister():
    try:
        del bpy.types.Object.epv_record
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
