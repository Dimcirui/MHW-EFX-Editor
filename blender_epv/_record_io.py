"""EPV 记录 dict 与记录属性对象之间的无 bpy 映射。

维护约束：
- 仅通过属性协议读写，支持 Blender PropertyGroup 与离线测试替身。
- 导入时重建 8 个颜色槽；文件颜色使用 0-255 通道，UI 使用 0-1 浮点，
  导出时必须取整还原为字节值。
- position 与 rotation 由对象 transform 承载，io_tree.py 负责其读写。
"""
from __future__ import annotations

SCALAR_KEYS = [
    "padding", "unknownID", "recordID",
    "pb1_paramU1", "boneID",
    "pb2_f1", "pb2_b1", "pb2_b2", "pb2_b3", "pb2_b4",
    "pb2_i1", "pb2_f2", "pb2_i2", "pb2_i3",
]
STRING_KEYS = ["path0", "path1", "path2", "path3"]
VECTOR_KEYS = [
    "pb1_paramU0", "pb1_paramU2",
    "pb1_EFXSubIndex", "pb1_paramU3", "pb1_EFXSubIndex2", "pb1_paramU4",
    "positionJitter", "rotationJitter",
    "paramW3", "paramW4", "paramW5", "paramV",
]


def dict_to_props(rp, d):
    """将记录 dict 写入属性对象，并重建颜色槽。"""
    for k in STRING_KEYS:
        setattr(rp, k, d[k])
    for k in SCALAR_KEYS:
        setattr(rp, k, d[k])
    for k in VECTOR_KEYS:
        setattr(rp, k, tuple(d[k]))

    rp.epv_colors.clear()
    for i in range(8):
        it = rp.epv_colors.add()
        it.efxslot = d["col%d_efxslot" % i]
        rgba = d["col%d_rgba" % i]                  # 文件字节通道
        it.color = tuple(c / 255.0 for c in rgba)   # Blender 归一化颜色
        it.saturation = d["col%d_saturation" % i]
        it.size = d["col%d_size" % i]
        it.frequency = d["col%d_frequency" % i]


def props_to_dict(rp):
    """从属性对象生成记录 dict；不含对象 transform。"""
    d = {}
    for k in STRING_KEYS:
        d[k] = getattr(rp, k)
    for k in SCALAR_KEYS:
        d[k] = getattr(rp, k)
    for k in VECTOR_KEYS:
        d[k] = list(getattr(rp, k))

    for i, it in enumerate(rp.epv_colors):
        d["col%d_efxslot" % i] = it.efxslot
        d["col%d_rgba" % i] = [int(round(c * 255.0)) for c in it.color]
        d["col%d_saturation" % i] = it.saturation
        d["col%d_size" % i] = it.size
        d["col%d_frequency" % i] = it.frequency
    return d
