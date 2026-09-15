# -*- coding: utf-8 -*-
"""
efx_format/material/mod3_names.py — .mod3 材质名表只读解析（纯 Python，零 bpy）

只做一件事：读 .mod3 的 materialNameList（每条材质槽的真实名字字符串，如
"VFX_EmissiveFog_Mt__3"）。.mrl3 本身不存名字字符串，只存 jamcrc 后的
materialNameHash（见 material/mrl3_reader.py 头部注释）；本模块配合它，在同目录
同名的 .mod3 存在时，把 mrl3 材质的 materialNameHash 反查回真名——不需要嵌入
社区维护的 266665 条 hash→名字反查表（16MB，见 blender_efx/material_name_cache.py
的取舍说明），只用这条 mrl3 自己配套的 .mod3 就能精确复原（前提是这份 .mod3
真的和这份 .mrl3 是同一个资源导出的一对，用同目录同名判定）。

字节布局移植自 MHW_Model_Editor 的 mod3/file_mod3.py（FileHeader 的
materialCount/materialOffset 字段 + 每条材质名字符串固定 128 字节步进）。
"""

import struct


_MAGIC = 4476749
_MATERIAL_NAME_STRIDE = 128


class Mod3ParseError(Exception):
    """.mod3 解析失败（非法文件 / 损坏 / 越界）。"""


def read_material_names(data: bytes) -> list:
    """解析 .mod3 文件字节，返回其 materialNameList（按材质槽下标顺序的字符串列表）。

    只读到 FileHeader 里 materialCount/materialOffset 这一步——mesh/骨骼/顶点等
    其余内容跟本功能无关，不解析。
    """
    if len(data) < 72 or struct.unpack_from('<I', data, 0)[0] != _MAGIC:
        raise Mod3ParseError("not a MHW .mod3 file (magic mismatch)")

    # FileHeader（见 MHW_Model_Editor 的 mod3/file_mod3.py）：
    # magic(4)+version(2)+boneCount(2)+meshCount(2)+materialCount(2)+vertexCount(4)+
    # faceCount(4)+unkn1(4)+vertexBufferSize(8)+groupCount(4)+pad(4)+timestamp(8)+
    # boneOffset(8)+groupOffset(8)+materialOffset(8) ...
    material_count = struct.unpack_from('<H', data, 10)[0]
    material_offset = struct.unpack_from('<Q', data, 64)[0]

    names = []
    for i in range(material_count):
        base = material_offset + i * _MATERIAL_NAME_STRIDE
        end = data.find(b'\x00', base)
        if end < 0:
            break
        names.append(data[base:end].decode('ascii', errors='replace'))
    return names
