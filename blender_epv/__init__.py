"""EPV3 的 Blender 编辑适配层。

负责将 .epv 数据映射为可编辑对象树，并维护与已导入 .efx 的引用关系。
字节解析与序列化由 epv_format/ 负责；对象结构信息由 io_tree.py 管理。
"""
from . import fields
from . import operators
from . import efx_link
from . import panels
from . import io_tree

from .io_tree import import_epv_tree, export_epv_tree

__all__ = [
    "fields",
    "operators",
    "efx_link",
    "panels",
    "io_tree",
    "import_epv_tree",
    "export_epv_tree",
]


def register():
    fields.register()
    operators.register()
    efx_link.register()
    panels.register()


def unregister():
    panels.unregister()
    efx_link.unregister()
    operators.unregister()
    fields.unregister()
