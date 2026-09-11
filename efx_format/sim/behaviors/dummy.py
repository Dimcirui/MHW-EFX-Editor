# -*- coding: utf-8 -*-
"""
efx_format/sim/behaviors/dummy.py  —  DUMMY（**显式**无视觉输出的渲染主体）

categories.py 对它的定性：「无视觉输出的功能性宿主（PTLIFE/SHOVEL/PLEMISSIVE
宿主）」。也就是说它占着「渲染主体」这个互斥位，但它的作用是**当别的属性的载体**，
自己不画任何东西——对应 Unity 里给粒子挂逻辑却关掉 Renderer 的用法。

所以它需要一个显式的 behavior，而不是「没实现所以退化成点」：

  - 不实现 → 预览把它画成点（凭空多出视觉），并列进「未模拟属性」（凭空多出待办）。
    两条都在骗用户。
  - 实现成返回 `kind='NONE'` → 预览什么都不画，列表里也干净。

字段只有 typeFlag（官方语料恒为 1）和 section_length，都不是可调参数，所以本
behavior 除了「明说不画」之外不做任何事。

约束（CLAUDE.md）：纯 Python，禁 import bpy；语法兼容 3.10。
"""

from ...hashes import DUMMY
from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem


@register(DUMMY)
class Dummy(Behavior):
    """占着渲染主体位，但明说自己没有视觉输出。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def build_render(self, p, em, view, item):
        # kind='NONE' 与 `return None` 不是一回事：返回 None 会让 Simulator 以为
        # 「这个 entry 没有渲染体」，进而补一个退化点。这里要的是「明确不画」。
        return RenderItem(kind="NONE")
