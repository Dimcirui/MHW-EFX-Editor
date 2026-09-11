# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/  —  逐属性的模拟行为

**加一个属性 = 新建一个文件 + `@register(HASH)` + 在下面加一行 import。**
不需要改 registry / simulator / stages 里的任何东西。

已实现
------
T1（生成与运动）  SPAWN / LIFE / EMITTERSHAPE3D / VELOCITY3D
T2（外观与发射器）TRANSFORM3D / SCALEANIM / ROTATEANIM / BILLBOARD3D
T3（其余渲染主体）DUMMY / PLANE / RIBBON / RIBBONBLADE / MESH

刻意不做：STRAINRIBBON / LIGHTNING —— 用户确认极少用到，且字段语义几乎全未知，
做出来也只是好看的猜测。它们照常走「未模拟」兜底，如实列在面板上。

未实现的属性不是「不支持」：registry 会把它们记进 `em.unsupported`，UI 上列出
「本 entry 有 N 个未模拟属性」，预览不静默撒谎。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from . import billboard3d     # noqa: F401
from . import dummy            # noqa: F401
from . import emittershape3d   # noqa: F401
from . import life             # noqa: F401
from . import mesh             # noqa: F401
from . import plane            # noqa: F401
from . import ribbon           # noqa: F401
from . import ribbonblade      # noqa: F401
from . import rotateanim       # noqa: F401
from . import scaleanim        # noqa: F401
from . import spawn            # noqa: F401
from . import transform3d      # noqa: F401
from . import velocity3d       # noqa: F401

__all__ = ["spawn", "life", "emittershape3d", "velocity3d",
           "transform3d", "scaleanim", "rotateanim", "billboard3d",
           "dummy", "plane", "ribbon", "ribbonblade", "mesh"]
