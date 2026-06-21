"""
blender_epv/_record_io.py — 扁平 dict ↔ EPVRecordProps 的鸭子类型映射（零 bpy）。

故意不 import bpy：dict_to_props / props_to_dict 只按属性名读写传入对象，
对象可以是真正的 EPVRecordProps，也可以是测试用的 SimpleNamespace，从而让
io_tree 的「文件→属性→文件」往返能用假 bpy 离线验 byte-perfect。

颜色：文件里是 0-255 整数(ubyte[4])，UI 色板用 0-1 float。两者往返逐值精确
（已验证 256 值无误差），故色板编辑不破坏 byte-perfect。

position / rotation 不在此处理：它们由对象 transform 承载，io_tree 单独读写。
"""
from __future__ import annotations

# 标量字段（int / float）
SCALAR_KEYS = [
    "padding", "unknownID", "recordID",
    "pb1_paramU1", "boneID",
    "pb2_f1", "pb2_b1", "pb2_b2", "pb2_b3", "pb2_b4",
    "pb2_i1", "pb2_f2", "pb2_i2", "pb2_i3",
]
STRING_KEYS = ["path0", "path1", "path2", "path3"]
# 定长向量字段（IntVector / FloatVector）
VECTOR_KEYS = [
    "pb1_paramU0", "pb1_paramU2",
    "pb1_EFXSubIndex", "pb1_paramU3", "pb1_EFXSubIndex2", "pb1_paramU4",
    "positionJitter", "rotationJitter",
    "paramW3", "paramW4", "paramW5", "paramV",
]


def dict_to_props(rp, d):
    """把扁平 dict 写入 record-props 对象（含 8 槽 epvColor）。"""
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
        rgba = d["col%d_rgba" % i]                       # 0-255 整数
        it.color = tuple(c / 255.0 for c in rgba)        # → 0-1 色板
        it.saturation = d["col%d_saturation" % i]
        it.size = d["col%d_size" % i]
        it.frequency = d["col%d_frequency" % i]


def props_to_dict(rp):
    """从 record-props 对象读回扁平 dict（不含 position / rotation）。"""
    d = {}
    for k in STRING_KEYS:
        d[k] = getattr(rp, k)
    for k in SCALAR_KEYS:
        d[k] = getattr(rp, k)
    for k in VECTOR_KEYS:
        d[k] = list(getattr(rp, k))

    for i, it in enumerate(rp.epv_colors):
        d["col%d_efxslot" % i] = it.efxslot
        d["col%d_rgba" % i] = [int(round(c * 255.0)) for c in it.color]  # 0-1 → 0-255
        d["col%d_saturation" % i] = it.saturation
        d["col%d_size" % i] = it.size
        d["col%d_frequency" % i] = it.frequency
    return d
