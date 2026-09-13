# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/  —  逐属性的模拟行为

**加一个属性 = 新建一个文件 + `@register(HASH)` + 在下面加一行 import。**
不需要改 registry / simulator / stages 里的任何东西。

已实现
------
T1（生成与运动）  SPAWN / LIFE / EMITTERSHAPE3D / VELOCITY3D / HOMING（径直飞向目标→
                  绕目标转圈，FORCE 阶段只写速度，位移仍由 VELOCITY3D 积分）
T2（外观与发射器）TRANSFORM3D / SCALEANIM / ROTATEANIM / BILLBOARD3D
T3（其余渲染主体）DUMMY / PLANE / RIBBON / RIBBONBLADE / MESH
T3（渲染修饰）    UVSEQUENCE（序列帧；帧表由宿主经 SimResources 提供）
T4（绑定关系）    PARENTOPTIONS（只做「跟随发射器」+「停止追踪帧数」，其余如实 note）
T4（联动）        PTLIFE（粒子在某个生命阶段触发 ACTION → 子实例，见 sim/scene.py）
T5（染色）        RGBFIRE / RGBWATER（两层颜色 + 各自的生命期时序块）
T5（渲染修饰）    ALPHACORRECTION（逐纹素的 alpha 阈值/伽马，真正的处理在 shader）
T5（渲染修饰）    REFRACTION（折射层 = 对背后画面做乘法；只做 pixelNormalOffset=0 那一档）
T5（渲染修饰）    flowmap 流动贴图（`_flowmap.py`，**共用函数不是 behavior**——八件套挂在
                  BILLBOARD3D / PLANE / BILLBOARD2D 自己身上，渲染体各调一次）
T5（渲染修饰）    UVCONTROL（UV 滚动/缩放，公式与 uvc_preview.py 同一套）

刻意不做：STRAINRIBBON / LIGHTNING —— 用户确认极少用到，且字段语义几乎全未知，
做出来也只是好看的猜测。它们照常走「未模拟」兜底，如实列在面板上。

未实现的属性不是「不支持」：registry 会把它们记进 `em.unsupported`，UI 上列出
「本 entry 有 N 个未模拟属性」，预览不静默撒谎。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from . import alphacorrection  # noqa: F401
from . import billboard3d     # noqa: F401
from . import dummy            # noqa: F401
from . import emittershape3d   # noqa: F401
from . import homing           # noqa: F401
from . import life             # noqa: F401
from . import mesh             # noqa: F401
from . import parentoptions    # noqa: F401
from . import plane            # noqa: F401
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
           "parentoptions", "ptlife", "rgbfire", "rgbwater", "alphacorrection", "uvcontrol",
           "refraction"]
