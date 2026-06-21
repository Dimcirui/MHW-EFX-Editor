"""
epv_format/ — MHW EPV3 (Effect Provider) 纯 Python 解析 / 序列化。

与 efx_format/ 同样的分层铁律：本包零 bpy 依赖、版本无关，可在 Blender 外测试。
EPV 指引 .efx 文件的触发/挂点/外观覆盖（epvColor slot）。

权威结构来源：AsteriskAmpersand/MHW-EPV-Editor structs/epv.py（construct 定义），
本实现用手写 struct 重写，避免引入 construct 外部依赖、保持 Python 3.10 兼容。
"""
from .epv import (
    EPVFile,
    EPVGroup,
    EPVRecord,
    EPVColor,
    EPVTrail,
    ParameterBlock1,
    ParameterBlock2,
)

__all__ = [
    "EPVFile",
    "EPVGroup",
    "EPVRecord",
    "EPVColor",
    "EPVTrail",
    "ParameterBlock1",
    "ParameterBlock2",
]
