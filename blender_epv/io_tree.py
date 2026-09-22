"""在 .epv3 文件与 Blender 对象树之间导入、导出。

对象树为根集合下的一个 EPV_ROOT Empty 与若干 EPV_GROUP 子集合，每条 record 是组内
一个 EPV_RECORD 对象。

维护约束：
- group 顺序由集合的 ~GIDX 决定，record 顺序由对象的 ~RIDX 决定，导出时据此排序还原。
- position 与 rotation 由对象 transform 承载，不做单位换算；float32 经 Python float
  往返取值不变，未编辑的 record 导出后与原字节一致。
- 字节拆拼归 epv_format/flatten.py，本模块只负责 Blender 映射。
"""
from __future__ import annotations
import os
import json

import bpy

from ..epv_format import EPVFile
from ..epv_format.flatten import file_to_tree, tree_to_file
from . import _record_io


# ─────────────────────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────────────────────

def _new_collection(name: str, parent_col) -> bpy.types.Collection:
    col = bpy.data.collections.new(name)
    parent_col.children.link(col)
    return col


def _new_empty(name: str, col) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    col.objects.link(obj)
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# 导入
# ─────────────────────────────────────────────────────────────────────────────

def import_epv_tree(filepath: str, context=None) -> bpy.types.Object:
    """读取 .epv3 并建立对象树；返回 EPV_ROOT Empty。"""
    if context is None:
        context = bpy.context

    with open(filepath, "rb") as f:
        raw = f.read()
    epv = EPVFile.parse(raw)
    root_props, groups = file_to_tree(epv)

    file_name = os.path.basename(filepath)
    file_stem = os.path.splitext(file_name)[0]

    scene_col = context.scene.collection
    root_col = _new_collection(file_name, scene_col)
    root_col.color_tag = "COLOR_04"   # 绿；EFX 用紫 06，mrl3 用蓝 05

    # ── EPV_ROOT Empty：signature + trail 段 ─────────────────────────────────
    root_obj = _new_empty(file_stem + " [EPV_ROOT]", root_col)
    root_obj["~TYPE"] = "EPV_ROOT"
    # signature 是 uint64、trail 段整型可超 32 位，写入 Blender 整型属性会溢出，
    # 因此分别以十六进制字符串和 JSON 字符串保存。
    root_obj["~SIG"] = "0x%X" % root_props["signature"]
    trail_props = {k: v for k, v in root_props.items() if k != "signature"}
    root_obj["~TRAIL"] = json.dumps(trail_props)

    # ── 每个 group 一个子集合 ────────────────────────────────────────────────
    for gi, (group_id, records) in enumerate(groups):
        gcol = _new_collection("%s G%03d id%d" % (file_stem, gi, group_id), root_col)
        gcol["~TYPE"] = "EPV_GROUP"
        gcol["~GID"] = group_id
        gcol["~GIDX"] = gi

        for ri, rd in enumerate(records):
            robj = _new_empty("%s G%03d R%03d" % (file_stem, gi, ri), gcol)
            robj["~TYPE"] = "EPV_RECORD"
            robj["~RIDX"] = ri
            robj.location = tuple(rd["position"])
            robj.rotation_euler = tuple(rd["rotation"])
            _record_io.dict_to_props(robj.epv_record, rd)

    return root_obj


# ─────────────────────────────────────────────────────────────────────────────
# 导出
# ─────────────────────────────────────────────────────────────────────────────

def _root_collection_of(root_obj) -> bpy.types.Collection:
    """EPV_ROOT 所在集合即根集合。"""
    for col in root_obj.users_collection:
        return col
    raise ValueError("EPV_ROOT 不在任何集合中")


def export_epv_tree(root_obj: bpy.types.Object) -> bytes:
    """从 EPV_ROOT 对象树还原 .epv3 字节。"""
    if root_obj.get("~TYPE") != "EPV_ROOT":
        raise ValueError("传入对象不是 EPV_ROOT")

    root_col = _root_collection_of(root_obj)

    root_props = {"signature": int(str(root_obj["~SIG"]), 16)}
    root_props.update(json.loads(str(root_obj["~TRAIL"])))

    gcols = [c for c in root_col.children if c.get("~TYPE") == "EPV_GROUP"]
    gcols.sort(key=lambda c: c.get("~GIDX", 0))

    groups = []
    for gcol in gcols:
        group_id = int(gcol.get("~GID", 0))
        robjs = [o for o in gcol.objects if o.get("~TYPE") == "EPV_RECORD"]
        robjs.sort(key=lambda o: o.get("~RIDX", 0))
        recs = [_record_dict_from_obj(o) for o in robjs]
        groups.append((group_id, recs))

    epv = tree_to_file(root_props, groups)
    return epv.serialize()


def _record_dict_from_obj(obj) -> dict:
    """从 record 对象还原扁平 dict（EPVRecordProps + transform）。"""
    d = _record_io.props_to_dict(obj.epv_record)
    d["position"] = list(obj.location)
    d["rotation"] = list(obj.rotation_euler)
    return d
