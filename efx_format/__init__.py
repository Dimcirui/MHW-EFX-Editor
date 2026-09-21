# -*- coding: utf-8 -*-
"""
efx_format/ — MHW `.efx` 格式的纯 Python 核心（零 `bpy` 依赖）

本包只做「字节 ↔ 结构」和「结构 ↔ 语义」，不碰 Blender。Blender 侧的胶水在
`blender_efx/` 与 `blender_epv/`。这条分界是硬约束（见 CLAUDE.md §1）：本包里
出现 `import bpy` 即为破坏。

子包布局
--------
    efxfile.py      文件分段解析 / 序列化（Header / Entry / Action / Extern /
                    Subselect / End），以及属性块边界扫描
    structs.py      **对外门面**：装配 schema 子包并 re-export，外部统一从这里导入
    schema/         字段级 codec —— fields_model(类型化 Field 模型) /
                    attributes(定长块 schema) / custom_codecs(变长块手写编解码) /
                    codec(编解码基座) / enums / labels
    categories.py   属性类型的九类分类树 + 规范顺序表（68 项）
    field_order.py  字段显示顺序的人工订正锚点
    field_tiers.py  常用 / 高级字段分档（脚本生成）
    sim/            粒子模拟核心（逐帧 step + 渲染项产出），behaviors/ 下一类一档
    timl/           TIML 关键帧树解析 / 序列化 + 通道名表
    material/       MATERIAL 块（mrl3 同源内嵌材质）的解析与结构化编辑
    ptbehavior/     PTBEHAVIOR 块（类型化稀疏覆盖包）的目录与编辑
    hashes/         EFX 类型哈希常量表 + jamcrc 工具
    uvs.py          `.uvs` 序列帧文件

不变量
------
`serialize(parse(x)) == x`。解析器不得丢信息，序列化器不得臆造字节；读不懂的
结构保留原始字节（opaque）而不是猜。改动本包后跑 `tools/roundtrip.py` 与
`tools/field_roundtrip.py`。

⚠ 下面这张 re-export 清单是**历史遗留的部分子集**（70 个属性类型里只列了 15 个主
属性 schema，外加 6 个 Extern 变体），
不代表「公开 API 就这些」。真正的门面是 `efx_format.structs`——需要别的 schema
请直接 `from efx_format.structs import XXX_SCHEMA`，不必往下面补。
"""


from .efxfile import EFXFile
from .structs import (
    unpack, pack, _schema_size,
    ATTR_SCHEMA_MAP,
    TRANSFORM3D_SCHEMA,
    PARENTOPTIONS_SCHEMA,
    SPAWN_SCHEMA,
    LIFE_SCHEMA,
    SHADERSETTINGS_SCHEMA,
    VELOCITY3D_SCHEMA,
    EMITTERSHAPE3D_SCHEMA,
    SCALEANIM_SCHEMA,
    FADEBYDEPTH_SCHEMA,
    RGBFIRE_SCHEMA,
    ROTATEANIM_SCHEMA,
    ALPHACORRECTION_SCHEMA,
    LUMINANCEBLEED_SCHEMA,
    REFRACTION_SCHEMA,
    NOISE_SCHEMA,
    # Shared ExternXxx variants (same schema, reused by Main and Extern)
    EXTERN_TRANSFORM3D_SCHEMA,
    EXTERN_SPAWN_SCHEMA,
    EXTERN_VELOCITY3D_SCHEMA,
    EXTERN_EMITTERSHAPE3D_SCHEMA,
    EXTERN_SCALEANIM_SCHEMA,
    EXTERN_RGBFIRE_SCHEMA,
)

__all__ = [
    "EFXFile",
    "unpack", "pack", "_schema_size",
    "ATTR_SCHEMA_MAP",
    "TRANSFORM3D_SCHEMA",
    "PARENTOPTIONS_SCHEMA",
    "SPAWN_SCHEMA",
    "LIFE_SCHEMA",
    "SHADERSETTINGS_SCHEMA",
    "VELOCITY3D_SCHEMA",
    "EMITTERSHAPE3D_SCHEMA",
    "SCALEANIM_SCHEMA",
    "FADEBYDEPTH_SCHEMA",
    "RGBFIRE_SCHEMA",
    "ROTATEANIM_SCHEMA",
    "ALPHACORRECTION_SCHEMA",
    "LUMINANCEBLEED_SCHEMA",
    "REFRACTION_SCHEMA",
    "NOISE_SCHEMA",
    "EXTERN_TRANSFORM3D_SCHEMA",
    "EXTERN_SPAWN_SCHEMA",
    "EXTERN_VELOCITY3D_SCHEMA",
    "EXTERN_EMITTERSHAPE3D_SCHEMA",
    "EXTERN_SCALEANIM_SCHEMA",
    "EXTERN_RGBFIRE_SCHEMA",
]
