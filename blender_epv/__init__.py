"""
blender_epv/ — MHW EPV3 编辑器 Blender 胶水层子包。

与 blender_efx/ 平级、独立注册。纯格式逻辑在 epv_format/（零 bpy）。
本包是唯一对 Blender 版本敏感的部分，刻意保持薄。

导入策略同 blender_efx：包内相对导入（. / ..），不依赖 sys.path。
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
    # fields 先注册：EPVRecordProps 挂到 Object，io_tree 导入与 panels 绘制都依赖它
    fields.register()
    operators.register()
    efx_link.register()    # L1/L2 联动算子（panels 绘制时引用）
    panels.register()


def unregister():
    panels.unregister()
    efx_link.unregister()
    operators.unregister()
    fields.unregister()
