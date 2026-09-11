# -*- coding: utf-8 -*-
"""
efx_format/sim/  —  EFX 粒子系统模拟核心（零 bpy）

定位
----
把一个 EFX Entry 的属性块喂进来，逐帧算出粒子状态。**不碰 Blender，不碰渲染**——
glue 层负责时钟（modal + timer）、绘制（gpu 模块 draw handler）和坐标换算。
这样核心能在 CI 里单测，将来换前端也只要移植这一层。

用法
----
    from efx_format.sim import Simulator, SimConfig

    blocks = [(type_hash, fields_dict), ...]      # entry 里属性的原始顺序
    sim = Simulator(blocks, timl_bytes, SimConfig(seed=1))
    for _ in range(120):
        sim.step()
        items = sim.build_render(view)            # 与 step 解耦，可单独重跑

`blocks` 刻意不是 EntryData 也不是 Blender 属性树：glue 层从**当前正在编辑的**
属性树构造它，预览才能反映未保存的改动。`from_attr_blocks()` 是从已解析文件构造
的便捷入口。

设计要点（详见各模块 docstring）
--------------------------------
- stages.py   阶段按「写什么」命名（FORCE/INTEGRATE/CONSTRAIN/XFORM/SHADE），
              不按「什么时候跑」；顺序是数据不是代码。
- rng.py      抖动只在 spawn 抽（step 钩子签名里没有 rng）；逐帧随机用确定性噪声。
- resolve.py  字段只能通过 `em.f(HASH, p)` 读，TIML 双轴与 EXTERN 在这里统一叠加。
- config.py   所有未确认的语义收成开关（UNKNOWNS），标定 = 拖滑块而不是改代码。
- simulator.py step() 与 build_render(view) 分离：逐帧模拟与视角无关。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10；零第三方依赖。
"""

from . import behaviors  # noqa: F401  —— import 即注册，必须在 registry 之后
from .config import UNKNOWNS, SimConfig
from .registry import Behavior, BoundBehavior, register, registered_hashes
from .resolve import Curve, FieldResolver, FieldView, TimlTracks
from .rng import (JITTER_GAUSSIAN, JITTER_ONESIDED, JITTER_SYMMETRIC, jitter,
                  jitter_int, jitter_vec, noise1, noise3)
from .simulator import EmitterState, Simulator
from .stages import (CONSTRAIN, FORCE, INTEGRATE, RENDER_BODY, RENDER_MOD, SHADE,
                     STAGE_LABELS, STAGE_NAMES, XFORM, stage_name)
from .state import Particle, RenderItem, SpawnRequest, Vec3, ViewContext

__all__ = [
    # 顶层
    "Simulator", "SimConfig", "EmitterState", "UNKNOWNS",
    # 扩展点
    "Behavior", "register", "registered_hashes", "BoundBehavior",
    # 阶段
    "FORCE", "INTEGRATE", "CONSTRAIN", "XFORM", "SHADE",
    "RENDER_BODY", "RENDER_MOD", "STAGE_NAMES", "STAGE_LABELS", "stage_name",
    # 数据
    "Particle", "RenderItem", "SpawnRequest", "Vec3", "ViewContext",
    # 字段解析
    "FieldResolver", "FieldView", "TimlTracks", "Curve",
    # 随机
    "jitter", "jitter_int", "jitter_vec", "noise1", "noise3",
    "JITTER_ONESIDED", "JITTER_SYMMETRIC", "JITTER_GAUSSIAN",
    # 便捷入口
    "from_attr_blocks",
]


def from_attr_blocks(attr_blocks, timl_bytes=b"", config=None):
    """从 `efxfile.AttrBlock` 列表构造 Simulator（解析好的文件走这条）。

    Blender 里的实时预览**不要**走这条——那边应该从正在编辑的属性树直接拼
    `[(type_hash, fields_dict), ...]`，否则预览看到的是上次保存的状态。
    """
    blocks = []
    for blk in attr_blocks or []:
        try:
            fields = blk.decode()
        except Exception:
            fields = None
        if fields is None:
            fields = {}
        blocks.append((blk.type_hash, fields))
    return Simulator(blocks, timl_bytes, config)
