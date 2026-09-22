"""MHW EPV3（Effect Provider）文件的解析与序列化，零 bpy 依赖。

EPV 指定 .efx 的触发点、挂点与外观覆盖槽。实现不引入外部依赖。
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
