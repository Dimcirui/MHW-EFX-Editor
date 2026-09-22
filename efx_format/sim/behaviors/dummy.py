# -*- coding: utf-8 -*-
"""DUMMY —— 占用渲染主体位、但不产生视觉输出的功能性宿主。

DUMMY 作为其它属性（PTLIFE / SHOVEL / PLEMISSIVE 等）的载体，自身不绘制任何内容。其字段
（typeFlag、section_length）均非可调参数，因此本 behavior 除声明不绘制外不执行任何操作。

维护约束：
- 必须显式实现并返回 `kind='NONE'`。若不实现，预览会补绘一个退化点，并将其列为未模拟属性，
  两者均与实际不符。
"""

from ...hashes import DUMMY
from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem


@register(DUMMY)
class Dummy(Behavior):
    """占用渲染主体位，并声明没有视觉输出。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def build_render(self, p, em, view, item):
        # kind='NONE' 与 return None 含义不同：返回 None 时 Simulator 判定该 entry 没有
        # 渲染体并补绘退化点，此处需要的是明确不绘制
        return RenderItem(kind="NONE")
