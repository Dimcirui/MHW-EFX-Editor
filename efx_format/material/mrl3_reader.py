"""
efx_format/material/mrl3_reader.py — .mrl3 材质文件只读解析

移植自 MHW_Model_Editor 的 mrl3/file_mrl3.py（Mrl3Header + MaterialInfo + Material +
Mrl3File.read()），去掉了原版对 bpy（i18n 报错文案）和 mrl3_dicts（材质名反查表，
原版仅用作可选校验过滤/显示名，不影响解析本身）的依赖——核心字节级解析本就是
纯 struct，与 bpy 无关。

用途：EFX MATERIAL 编辑器"参考 .mrl3 新建材质槽"功能——用户选一个 .mrl3 文件，
读出里面实际存在的每条材质（材质名哈希 + 材质类型 + 贴图路径默认值），供用户挑一
条直接新建一个绑定正确、贴图预填好的材质槽（见 blender_efx/operators.py 的
EFX_OT_material_add_from_mrl3）。不需要装 MHW Model Editor 插件、不需要把 mrl3
材质导入到场景、不联动任何 mesh（跟 mod3/mesh 完全解耦，纯粹读一个独立文件）。

⚠ 字段命名坑（实测 confuse.mrl3 173 条材质核对过）：MaterialInfo 里紧跟
materialNameHash 之后的字段（原版命名 mmtrHash）才是跟 EFX material/meta.py
.MATERIAL_TYPE_NAMES 同源同键的材质类型哈希；原版再往后一个字段（命名
shaderHash）实测不落在这 112 种已知类型表内，是另一个更细粒度的哈希，本模块
不收集它。

贴图路径解析（2026-09 新增，此前"有意不做"，现已用 master_material_dict.json
生成的编码表解决——见 material/resources.py 头部注释）：mrl3 材质的 resource
buffer 里每条资源用 `resHash >> 12` 匹配该材质类型的贴图资源编码表；命中的贴图
资源的 value 字段（1-based）索引进文件的贴图字符串表即为实际路径。非贴图资源
（CB 常量缓冲区 / Sampler State）不需要，不收集。
"""

import io
import struct


_MAGIC = 5001805
_TEXTURE_ENTRY_SIZE = 272
_MATERIAL_INFO_SIZE = 56


class Mrl3ParseError(Exception):
    """.mrl3 解析失败（非法文件 / 损坏 / 越界）。"""


def _read_uint(f) -> int:
    data = f.read(4)
    if len(data) != 4:
        raise Mrl3ParseError("unexpected EOF")
    return struct.unpack('<I', data)[0]


def _read_uint64(f) -> int:
    data = f.read(8)
    if len(data) != 8:
        raise Mrl3ParseError("unexpected EOF")
    return struct.unpack('<Q', data)[0]


def _read_ubyte(f) -> int:
    data = f.read(1)
    if len(data) != 1:
        raise Mrl3ParseError("unexpected EOF")
    return struct.unpack('<B', data)[0]


def _read_ushort(f) -> int:
    data = f.read(2)
    if len(data) != 2:
        raise Mrl3ParseError("unexpected EOF")
    return struct.unpack('<H', data)[0]


def _read_header(f):
    """读 Mrl3Header（40 字节），返回
    (material_count, material_offset, texture_count, texture_offset)。"""
    magic = _read_uint(f)
    if magic != _MAGIC:
        raise Mrl3ParseError("not a MHW .mrl3 file (magic mismatch)")
    _version = _read_uint(f)
    _timestamp = _read_uint64(f)
    material_count = _read_uint(f)
    texture_count = _read_uint(f)
    texture_offset = _read_uint64(f)
    material_offset = _read_uint64(f)
    return material_count, material_offset, texture_count, texture_offset


def _read_material_info(f):
    """读一条 MaterialInfo（56 字节），返回
    (material_name_hash, mmtr_hash, resource_count, block_offset)。"""
    _type_id = _read_uint(f)
    material_name_hash = _read_uint(f)
    mmtr_hash = _read_uint(f)
    _shader_hash = _read_uint(f)
    _block_size = _read_uint(f)
    for _ in range(2):
        _read_ubyte(f)
    resource_count = _read_ushort(f)
    for _ in range(4):
        _read_ubyte(f)
    f.seek(20, io.SEEK_CUR)
    block_offset = _read_uint64(f)
    return material_name_hash, mmtr_hash, resource_count, block_offset


def _read_texture_list(data: bytes, texture_count: int, texture_offset: int) -> list:
    """贴图字符串表：每条 entry 272 字节，路径字符串从 entry+16 开始、'\\0' 结尾。"""
    textures = []
    for i in range(texture_count):
        base = texture_offset + i * _TEXTURE_ENTRY_SIZE + 16
        end = data.find(b'\x00', base)
        if end < 0:
            end = base
        textures.append(data[base:end].decode('ascii', errors='replace'))
    return textures


def _decode_property(data: bytes, off: int, type_str: str):
    """按声明类型从绝对偏移 off 解出原始值：bbool→bool，uint→int，float→float，
    float[N]→4 个 float 的 list（不管声明 N 是多少，统一按 4 读——匹配
    material/edit.py::get_param_value 的"负载末端固定 4 槽"约定，多出的槽位
    读 0，供 EFX Tex_Set 的 float[N] 负载直接使用）。"""
    if type_str == 'bbool':
        return bool(struct.unpack_from('<I', data, off)[0])
    if type_str == 'uint':
        return struct.unpack_from('<I', data, off)[0]
    if type_str == 'float':
        return struct.unpack_from('<f', data, off)[0]
    if type_str and type_str.startswith('float['):
        n = int(type_str[6:-1])
        vals = list(struct.unpack_from(f'<{n}f', data, off))
        vals += [0.0] * (4 - n)
        return vals
    return None


def _read_material_resources(data: bytes, mmtr_hash: int, resource_count: int,
                              block_offset: int, texture_list: list):
    """解析一条材质的 resource buffer，返回 (textures, params)：
        textures: {贴图裸名: 路径字符串}
        params:   {字段名: 值}（bool/int/float/4-float-list，见 _decode_property）
    未收录 shader 类型的两者均为空 dict。

    复刻 MHW_Model_Editor 的 ReadResourceBuffers/ReadPropertyBuffers 算法：
    每条 resource 用 resHash>>12 匹配（贴图/CB 编码表分别见 resources.py 的
    texture_resource_codes/cb_resource_codes），贴图的 resValue 是 1-based 贴图
    索引，CB 的 resValue 是该 CB 在这条材质自己 resource buffer 里的字节偏移
    （逐材质从文件读，不用 JSON 声明的默认值）；CB 内部字段偏移用
    cb_field_layout 的预算表（对齐字段已在生成时计入偏移，见 resources.py
    头部注释）。
    """
    from .resources import texture_resource_codes, cb_resource_codes, cb_field_layout

    tex_lut = texture_resource_codes(mmtr_hash)
    cb_lut = cb_resource_codes(mmtr_hash)
    textures = {}
    params = {}
    if not tex_lut and not cb_lut:
        return textures, params

    n = resource_count // 2
    for k in range(n):
        off = block_offset + k * 16
        try:
            _res_code, res_hash, res_value, _unkn = struct.unpack_from('<4I', data, off)
        except struct.error:
            break
        key = res_hash >> 12

        tex_name = tex_lut.get(key) if tex_lut else None
        if tex_name is not None:
            if 0 < res_value <= len(texture_list):
                textures[tex_name] = texture_list[res_value - 1]
            continue

        cb_name = cb_lut.get(key) if cb_lut else None
        if cb_name is not None:
            layout = cb_field_layout(mmtr_hash, cb_name)
            if not layout:
                continue
            for _t_hash, field_name, type_str, field_offset in layout:
                abs_off = block_offset + res_value + field_offset
                try:
                    params[field_name] = _decode_property(data, abs_off, type_str)
                except struct.error:
                    continue
    return textures, params


def read_materials(data: bytes) -> list:
    """解析 .mrl3 文件字节，返回文件里每条合法材质：

        [{'material_name_hash': int, 'mmtr_hash': int,
          'textures': {name: path}, 'params': {field_name: value}}, ...]

    `material_name_hash` 直接可用作 EFX MATERIAL 的 mat_name_hash（见
    material/edit.py::set_block_material_name 的绑定原理——两者本就同一个值，
    不需要再算 jamcrc）；`mmtr_hash` 即 mat_shader。`textures`/`params` 只包含
    按 material/resources.py 编码表能解出名字的资源，未收录材质类型时均为空
    dict（仍返回该材质本身，因为 name_hash/shader 已经足够新建一个绑定正确的
    材质槽，只是没有贴图/参数默认值可填）。

    仅做基本合法性过滤（resourceCount 为偶数，参照原版 Mrl3File.read() 的判据）。
    解析失败（非法 .mrl3 / 损坏文件）抛 Mrl3ParseError；调用方（UI）应捕获后提示
    用户，不静默失败退化成空列表。
    """
    f = io.BytesIO(data)
    material_count, material_offset, texture_count, texture_offset = _read_header(f)

    if not material_count or not material_offset:
        return []

    texture_list = _read_texture_list(data, texture_count, texture_offset) if texture_count and texture_offset else []

    f.seek(material_offset)
    results = []
    for _ in range(material_count):
        material_name_hash, mmtr_hash, resource_count, block_offset = _read_material_info(f)
        if resource_count % 2 != 0:
            continue
        textures, params = _read_material_resources(data, mmtr_hash, resource_count, block_offset, texture_list)
        results.append({
            'material_name_hash': material_name_hash,
            'mmtr_hash': mmtr_hash,
            'textures': textures,
            'params': params,
        })
    return results
