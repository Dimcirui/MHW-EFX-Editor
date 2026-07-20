"""
efx_format/mrl3_reader.py — .mrl3 材质文件头部只读解析（纯 Python，零 bpy）

移植自 MHW_Model_Editor 的 mrl3/file_mrl3.py（Mrl3Header + MaterialInfo + Material +
Mrl3File.read()），去掉了原版对 bpy（i18n 报错文案）和 mrl3_dicts（材质名反查表，
原版仅用作可选校验过滤）的依赖——核心字节级解析本就是纯 struct，与 bpy 无关。

用途：EFX MATERIAL 编辑器"导入 mrl3 过滤材质类型"功能——用户单独选一个 .mrl3 文件，
本模块读出里面实际用到的材质类型哈希集合，拿去过滤材质类型下拉。不需要装 MHW Model
Editor 插件、不需要把 mrl3 材质导入到场景、不联动任何 mesh（2026-07 与用户确认：
mrl3 只当独立过滤器用，跟 mod3/mesh 完全解耦）。

⚠ 字段命名坑（实测 confuse.mrl3 173 条材质核对过）：MaterialInfo 里紧跟
materialNameHash 之后的字段（原版命名 mmtrHash）才是跟 EFX material_meta
.MATERIAL_TYPE_NAMES 同源同键的材质类型哈希；原版再往后一个字段（命名
shaderHash）实测不落在这 112 种已知类型表内，是另一个更细粒度的哈希，本模块
不收集它——见 read_material_type_hashes 内的详细说明。

有意不做：贴图路径 / resource / property 解析——原版这部分依赖
master_material_dict.json 的逐材质类型 resourceDict schema，本项目没有这份数据
（其内部对 CB*/SS* 常量缓冲区/采样器同样只给块名字+总字节数，不含参数级语义，
见与用户核实过的结论），做了也用不上，故只解析到材质类型哈希这一级。
"""

import io
import struct


_MAGIC = 5001805


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
    """读 Mrl3Header（40 字节），返回 (material_count, material_offset)。"""
    magic = _read_uint(f)
    if magic != _MAGIC:
        raise Mrl3ParseError("not a MHW .mrl3 file (magic mismatch)")
    _version = _read_uint(f)
    _timestamp = _read_uint64(f)
    material_count = _read_uint(f)
    _texture_count = _read_uint(f)
    _texture_offset = _read_uint64(f)
    material_offset = _read_uint64(f)
    return material_count, material_offset


def _read_material_info(f):
    """读一条 MaterialInfo（56 字节），返回 (mmtr_hash, shader_hash, resource_count)。"""
    _type_id = _read_uint(f)
    _material_name_hash = _read_uint(f)
    mmtr_hash = _read_uint(f)
    shader_hash = _read_uint(f)
    _block_size = _read_uint(f)
    for _ in range(2):
        _read_ubyte(f)
    resource_count = _read_ushort(f)
    for _ in range(4):
        _read_ubyte(f)
    f.seek(20, io.SEEK_CUR)
    _block_offset = _read_uint64(f)
    return mmtr_hash, shader_hash, resource_count


def read_material_type_hashes(data: bytes) -> set:
    """解析 .mrl3 文件字节，返回其中用到的材质类型哈希集合（uint32）。

    实测核对（confuse.mrl3，173 条材质）：MaterialInfo 里紧跟 materialNameHash
    之后的字段（原版命名 mmtrHash）才是与 EFX material_meta.MATERIAL_TYPE_NAMES /
    mrl3 master_material_dict.json 同源同键的"材质类型"哈希（如 3019453706 →
    Uber_Mt）；再往后一个字段（原版命名 shaderHash）实测不落在这 112 种已知类型
    表内，是另一个更细粒度的哈希，与本功能（按材质类型过滤下拉）无关，本函数
    不收集它。

    仅做基本合法性过滤（resourceCount 为偶数，参照原版 Mrl3File.read() 的判据）——
    不依赖材质名反查表。解析失败（非法 .mrl3 / 损坏文件）抛 Mrl3ParseError；
    调用方（UI）应捕获后提示用户，不静默失败退化成空集合（空集合会被误当作
    "这个 mrl3 不用任何材质类型"，比报错更容易误导用户）。
    """
    f = io.BytesIO(data)
    material_count, material_offset = _read_header(f)

    hashes = set()
    if material_count and material_offset:
        f.seek(material_offset)
        for _ in range(material_count):
            mmtr_hash, _shader_hash, resource_count = _read_material_info(f)
            if resource_count % 2 != 0:
                continue
            hashes.add(mmtr_hash)
    return hashes
