# -*- coding: utf-8 -*-
"""逐属性的模拟行为。

新增一个属性只需新建一个文件、以 `@register(HASH)` 注册，并在下方增加一行 import，无需修改
registry / simulator / stages。

未实现的属性不会被静默跳过：registry 将其记入 `em.unsupported`，由 UI 列出该 entry 中未模拟的
属性数量。

维护约束：
- STRAINRIBBON 与 LIGHTNING 不予实现，按未模拟属性处理。其字段语义几乎全部未知，实现结果只能
  是猜测。
- `_flowmap.py` 是共用函数模块，不是 behavior，没有 `@register`。flowmap 字段属于
  BILLBOARD3D / PLANE / BILLBOARD2D，由各渲染体分别调用。
"""

from . import alphacorrection  # noqa: F401
from . import billboard3d     # noqa: F401
from . import dummy            # noqa: F401
from . import emittershape3d   # noqa: F401
from . import homing           # noqa: F401
from . import life             # noqa: F401
from . import mesh             # noqa: F401
from . import noise            # noqa: F401
from . import parentoptions    # noqa: F401
from . import plane            # noqa: F401
from . import ptcollision      # noqa: F401
from . import ptlife           # noqa: F401
from . import refraction       # noqa: F401
from . import rgbfire          # noqa: F401
from . import rgbwater         # noqa: F401
from . import ribbon           # noqa: F401
from . import ribbonblade      # noqa: F401
from . import rotateanim       # noqa: F401
from . import scaleanim        # noqa: F401
from . import spawn            # noqa: F401
from . import transform3d      # noqa: F401
from . import uvcontrol        # noqa: F401
from . import uvsequence       # noqa: F401
from . import velocity3d       # noqa: F401

__all__ = ["spawn", "life", "emittershape3d", "velocity3d", "homing",
           "transform3d", "scaleanim", "rotateanim", "billboard3d",
           "dummy", "plane", "ribbon", "ribbonblade", "mesh", "uvsequence",
           "parentoptions", "ptlife", "ptcollision", "noise", "rgbfire", "rgbwater",
           "alphacorrection", "uvcontrol", "refraction"]
