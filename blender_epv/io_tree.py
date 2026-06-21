"""
blender_epv/io_tree.py — EPV3 文件 ↔ Blender 对象树 互转。

对象树结构（COLOR_04 绿色集合，~TYPE 标记类型）：
  EPV 集合 (文件名, color_tag='COLOR_04')
    ├── EPV_ROOT  Empty   (~TYPE='EPV_ROOT')      存 signature + trail 段全部数据
    └── <groupID 集合>    (~TYPE='EPV_GROUP', ~GID=groupID, ~GIDX=组序)   每 group 一个子集合
          └── Record Empty (~TYPE='EPV_RECORD', ~RIDX=组内序)            每条 record 一个对象

byte-perfect 关键
-----------------
- group 顺序由集合自定义属性 ~GIDX 决定；record 顺序由对象 ~RIDX 决定（导出时排序还原）。
- position / rotation 驱动对象 transform（location / rotation_euler，无单位换算），导出时
  从 transform 读回；float32→double→float32 往返精确，未改动的 record 保持 byte-perfect。
- 其余全部字段（含 jitter / 各 param / epvColor / trail）存自定义属性，原值无损。

⚠ 本模块依赖 bpy，是版本敏感胶水层；纯拆拼逻辑在 epv_format/flatten.py（已脱离 bpy 验证）。
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
    """读取 .epv3 → 构建对象树，返回 EPV_ROOT Empty。"""
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
    root_col.color_tag = "COLOR_04"   # 绿，区别于 EFX(紫 06)、mrl3(蓝 05)

    # ── EPV_ROOT Empty：signature + trail 段 ─────────────────────────────────
    root_obj = _new_empty(file_stem + " [EPV_ROOT]", root_col)
    root_obj["~TYPE"] = "EPV_ROOT"
    # signature(uint64) 超 32 位、trail 段整型可能 ≥2^31 → Blender 32 位 int 属性会溢出，
    # 故 signature 存 hex 字符串、trail 段整体存 JSON 字符串（精确无损）。
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
            # transform 承载 position / rotation（无单位换算）
            robj.location = tuple(rd["position"])
            robj.rotation_euler = tuple(rd["rotation"])
            # 其余字段写入 EPVRecordProps（含 8 槽颜色）
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

    # root_props（trail 段 + signature）：从 ~SIG(hex) + ~TRAIL(JSON) 还原
    root_props = {"signature": int(str(root_obj["~SIG"]), 16)}
    root_props.update(json.loads(str(root_obj["~TRAIL"])))

    # group 集合：按 ~GIDX 排序
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
