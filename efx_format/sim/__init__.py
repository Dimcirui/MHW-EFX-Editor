# -*- coding: utf-8 -*-
"""EFX 粒子系统的模拟核心：吃属性块，逐帧算出粒子状态。

维护约束：
- 本包不涉及 Blender 与渲染。时钟、绘制与坐标换算由宿主负责，核心因此可单测。
- 输入是 `[(type_hash, fields_dict), ...]`，不是 EntryData 也不是 Blender 属性树；
  宿主须从当前正在编辑的属性树构造，否则预览反映的是上次保存的状态。
"""

from . import behaviors  # noqa: F401  —— import 即注册，必须在 registry 之后
from .config import UNKNOWNS, SimConfig
from .registry import Behavior, BoundBehavior, register, registered_hashes
from .resolve import Curve, FieldResolver, FieldView, TimlTracks
from .rng import jitter, jitter_int, jitter_vec, noise1, noise3
from .scene import (ActionTarget, EntryTemplate, SimScene, action_targets,
                    from_efx_file)
from .simulator import EmitterState, Simulator
from .stages import (CONSTRAIN, FORCE, INTEGRATE, RENDER_BODY, RENDER_MOD, SHADE,
                     STAGE_LABELS, STAGE_NAMES, XFORM, stage_name)
from .state import Particle, RenderItem, SpawnRequest, Vec3, ViewContext
from .uvs_table import FrameTable, SimResources, grid_table

__all__ = [
    # 顶层
    "Simulator", "SimConfig", "EmitterState", "UNKNOWNS",
    # 实例树（PTLIFE → ACTION 联动）
    "SimScene", "EntryTemplate", "ActionTarget", "from_efx_file", "action_targets",
    # 扩展点
    "Behavior", "register", "registered_hashes", "BoundBehavior",
    # 阶段
    "FORCE", "INTEGRATE", "CONSTRAIN", "XFORM", "SHADE",
    "RENDER_BODY", "RENDER_MOD", "STAGE_NAMES", "STAGE_LABELS", "stage_name",
    # 数据
    "Particle", "RenderItem", "SpawnRequest", "Vec3", "ViewContext",
    # 外部资源（序列帧表）
    "SimResources", "FrameTable", "grid_table",
    # 字段解析
    "FieldResolver", "FieldView", "TimlTracks", "Curve",
    # 随机
    "jitter", "jitter_int", "jitter_vec", "noise1", "noise3",
    # 便捷入口
    "from_attr_blocks",
]


def from_attr_blocks(attr_blocks, timl_bytes=b"", config=None, resources=None):
    """从已解析的 AttrBlock 列表构造 Simulator；实时预览不要走这条。"""
    blocks = []
    for blk in attr_blocks or []:
        try:
            fields = blk.decode()
        except Exception:
            fields = None
        if fields is None:
            fields = {}
        blocks.append((blk.type_hash, fields))
    return Simulator(blocks, timl_bytes, config, resources)
