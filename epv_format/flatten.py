"""EPVFile 与扁平 dict 树之间的互转。

dict 的值只使用 Blender 自定义属性支持的类型：int、float、str 及其列表，嵌套结构
一律展平。本模块不依赖 bpy，拆拼与顺序还原可脱离 Blender 单独验证。
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Any

from .epv import (
    EPVFile, EPVGroup, EPVRecord, EPVColor,
    ParameterBlock1, ParameterBlock2,
)


# ─────────────────────────────────────────────────────────────────────────────
# record ↔ dict
# ─────────────────────────────────────────────────────────────────────────────

def record_to_dict(rec: EPVRecord) -> Dict[str, Any]:
    pb1 = rec.parameterBlock1
    pb2 = rec.parameterBlock2
    d: Dict[str, Any] = {}

    # 拆成 4 个独立键：自定义属性不支持字符串数组
    pp = list(rec.packed_path) + ["", "", "", ""]
    for i in range(4):
        d["path%d" % i] = pp[i]

    d["padding"] = rec.padding
    d["unknownID"] = rec.unknownID
    d["recordID"] = rec.recordID

    d["pb1_paramU0"] = list(pb1.paramU0)
    d["pb1_paramU1"] = pb1.paramU1
    d["pb1_paramU2"] = list(pb1.paramU2)
    d["pb1_EFXSubIndex"] = list(pb1.EFXSubIndex)
    d["pb1_paramU3"] = list(pb1.paramU3)
    d["pb1_EFXSubIndex2"] = list(pb1.EFXSubIndex2)
    d["pb1_paramU4"] = list(pb1.paramU4)

    d["position"] = list(rec.position)
    d["positionJitter"] = list(rec.positionJitter)
    d["rotation"] = list(rec.rotation)
    d["rotationJitter"] = list(rec.rotationJitter)

    d["paramW3"] = list(rec.paramW3)
    d["boneID"] = rec.boneID
    d["paramW4"] = list(rec.paramW4)

    cols = list(rec.epvColor) + [EPVColor() for _ in range(8)]
    for i in range(8):
        c = cols[i]
        d["col%d_efxslot" % i] = c.efxslot
        d["col%d_rgba" % i] = list(c.hexcolor)
        d["col%d_saturation" % i] = c.saturation
        d["col%d_size" % i] = c.size
        d["col%d_frequency" % i] = c.frequency

    d["paramW5"] = list(rec.paramW5)

    d["pb2_f1"] = pb2.f1
    d["pb2_b1"] = pb2.b1
    d["pb2_b2"] = pb2.b2
    d["pb2_b3"] = pb2.b3
    d["pb2_b4"] = pb2.b4
    d["pb2_i1"] = pb2.i1
    d["pb2_f2"] = pb2.f2
    d["pb2_i2"] = pb2.i2
    d["pb2_i3"] = pb2.i3

    d["paramV"] = list(rec.paramV)
    return d


def dict_to_record(d: Dict[str, Any]) -> EPVRecord:
    pb1 = ParameterBlock1(
        paramU0=tuple(d["pb1_paramU0"]),
        paramU1=d["pb1_paramU1"],
        paramU2=tuple(d["pb1_paramU2"]),
        EFXSubIndex=tuple(d["pb1_EFXSubIndex"]),
        paramU3=tuple(d["pb1_paramU3"]),
        EFXSubIndex2=tuple(d["pb1_EFXSubIndex2"]),
        paramU4=tuple(d["pb1_paramU4"]),
    )
    pb2 = ParameterBlock2(
        f1=d["pb2_f1"], b1=d["pb2_b1"], b2=d["pb2_b2"], b3=d["pb2_b3"],
        b4=d["pb2_b4"], i1=d["pb2_i1"], f2=d["pb2_f2"], i2=d["pb2_i2"], i3=d["pb2_i3"],
    )
    epvColor = []
    for i in range(8):
        epvColor.append(EPVColor(
            efxslot=d["col%d_efxslot" % i],
            hexcolor=tuple(d["col%d_rgba" % i]),
            saturation=d["col%d_saturation" % i],
            size=d["col%d_size" % i],
            frequency=d["col%d_frequency" % i],
        ))
    return EPVRecord(
        packed_path=[d["path0"], d["path1"], d["path2"], d["path3"]],
        padding=d["padding"],
        unknownID=d["unknownID"],
        recordID=d["recordID"],
        parameterBlock1=pb1,
        position=tuple(d["position"]),
        positionJitter=tuple(d["positionJitter"]),
        rotation=tuple(d["rotation"]),
        rotationJitter=tuple(d["rotationJitter"]),
        paramW3=tuple(d["paramW3"]),
        boneID=d["boneID"],
        paramW4=tuple(d["paramW4"]),
        epvColor=epvColor,
        paramW5=tuple(d["paramW5"]),
        parameterBlock2=pb2,
        paramV=tuple(d["paramV"]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# file ↔ tree
# ─────────────────────────────────────────────────────────────────────────────

def file_to_tree(epv: EPVFile) -> Tuple[Dict[str, Any], List[Tuple[int, List[Dict[str, Any]]]]]:
    """拆成 (root_props, groups)。root_props 含 signature + trail 段全部数据。"""
    root_props: Dict[str, Any] = {
        "signature": epv.signature,
        "epvPath": epv.epvPath,
        "trail_padding": epv.trail_padding,
        "trail_one": epv.trail_one,
        "trail_null": epv.trail_null,
        # 展平为三个等长数组，按下标对应同一条 trail
        "trail_ids": [t.trailID for t in epv.trails],
        "trail_blockIDs": [t.blockID for t in epv.trails],
        "trail_recordIDs": [t.recordID for t in epv.trails],
    }
    groups: List[Tuple[int, List[Dict[str, Any]]]] = []
    for g in epv.groups:
        groups.append((g.groupID, [record_to_dict(r) for r in g.records]))
    return root_props, groups


def tree_to_file(root_props: Dict[str, Any],
                 groups: List[Tuple[int, List[Dict[str, Any]]]]) -> EPVFile:
    """file_to_tree 的逆向；三个 trail 数组必须等长，否则多出的条目被丢弃。"""
    from .epv import EPVTrail
    trails = [
        EPVTrail(trailID=tid, blockID=bid, recordID=rid)
        for tid, bid, rid in zip(
            root_props["trail_ids"],
            root_props["trail_blockIDs"],
            root_props["trail_recordIDs"],
        )
    ]
    epv_groups = [
        EPVGroup(groupID=gid, records=[dict_to_record(rd) for rd in recs])
        for gid, recs in groups
    ]
    return EPVFile(
        signature=root_props["signature"],
        groups=epv_groups,
        trails=trails,
        epvPath=root_props["epvPath"],
        trail_padding=root_props["trail_padding"],
        trail_one=root_props["trail_one"],
        trail_null=root_props["trail_null"],
    )
