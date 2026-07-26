"""
efx_format/ptbehavior_edit.py  —  PTBEHAVIOR 稀疏覆盖的增删编辑核心（纯 Python，零 bpy）

PTBEHAVIOR 是类型化稀疏覆盖（见 categories/catalog 与 memory ptbehavior-is-sparse-override）：
每个 b_type 一张固定有序的属性表，实例只存被覆盖的属性子集（保持子序列）。本模块在
unpack_ptbehavior 产出的 values dict 上做增删覆盖项，再交给 pack_ptbehavior 还原字节。

不变量：params 始终是 PTBEHAVIOR_CATALOG[b_type] 规范顺序的子序列；每个 key 至多一项。
新增覆盖项按规范顺序插入；const0 取同块现有项（= jamcrc(b_type)），空块时用 jamcrc 算。
"""

import zlib

from .ptbehavior_catalog import PTBEHAVIOR_CATALOG


def jamcrc(s: str) -> int:
    """MHW/RE Engine 字段哈希：标准 CRC-32 但 xorout=0（即取反）。"""
    return (zlib.crc32(s.encode('ascii')) ^ 0xFFFFFFFF) & 0xFFFFFFFF


def _to_signed32(v: int) -> int:
    """无符号 → 有符号 int32（pack_ptbehavior 用 '<i'，与 unpack 一致存有符号值）。"""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _btype_str(values: dict) -> str:
    """从 values['b_type']（bytes，含末尾 null）取规范字符串（去 null）。"""
    return values['b_type'].decode('latin-1').rstrip('\x00')


def catalog_for(values: dict):
    """返回该实例 b_type 的属性目录 [(key, t, freq), ...]；未知 b_type 返回 []。"""
    return PTBEHAVIOR_CATALOG.get(_btype_str(values), [])


def _canonical_index(values: dict):
    """key_hash → 规范顺序下标；不在目录内的 key 给一个超大下标（排末尾，稳定）。"""
    cat = catalog_for(values)
    idx = {k: i for i, (k, _t, _f) in enumerate(cat)}
    return idx


def present_keys(values: dict) -> set:
    """当前已覆盖的 key 集合。"""
    return {p['unkn'] & 0xFFFFFFFF for p in values['params']}


def addable_catalog(values: dict):
    """可新增的属性（目录中尚未覆盖的项），保持规范顺序。"""
    have = present_keys(values)
    return [(k, t, f) for (k, t, f) in catalog_for(values)
            if (k & 0xFFFFFFFF) not in have]


# ── 各 value_type t 的默认值（新增覆盖项时填零/空，用户再编辑）─────────────────
def _default_param_fields(t: int) -> dict:
    if t == 0x03:
        return {'NULL': 0}
    if t == 0x05:
        return {'unkn0': 0}
    if t == 0x06:
        return {'decal_epv_color_slot': 0}
    if t == 0x0C:
        return {'unkn0': 0.0}
    if t == 0x0F:
        return {'color': [0, 0, 0, 0]}
    if t == 0x14:
        return {'unkn1': [0.0, 0.0, 0.0]}
    if t == 0x15:
        return {'unkn0': 0.0, 'unkn1': 0.0, 'unkn2': 0.0, 'unkn3': 0.0}
    if t == 0x36:
        return {'unkn1': [0, 0]}
    if t == 0x37:
        return {'unkn1': [0.0, 0.0]}
    if t == 0x40:
        return {'unkn0': 0}
    if t == 0x80:
        return {'file_type': 0, 'path_len': 0, 'path': b''}
    return {'unkn_type': 0}


def _const0_for(values: dict) -> int:
    """新增项的 const0 = jamcrc(b_type)；优先复用同块现有项的 const0。"""
    for p in values['params']:
        return p['const0']
    return jamcrc(_btype_str(values))


def add_override(values: dict, key: int) -> bool:
    """
    新增一条覆盖项（key 取自 catalog）。按规范顺序插入以保持子序列不变量。
    返回 True 成功；False 表示 key 已存在或不在目录内。
    """
    key &= 0xFFFFFFFF
    if key in present_keys(values):
        return False
    cat = {k & 0xFFFFFFFF: t for (k, t, _f) in catalog_for(values)}
    if key not in cat:
        return False
    t = cat[key]
    # unkn/const0 存有符号 int32（与 unpack_ptbehavior 输出、pack 的 '<i' 一致）
    param = {'unkn': _to_signed32(key), 'const0': _to_signed32(_const0_for(values)), 't': t}
    param.update(_default_param_fields(t))

    # 按规范顺序找插入位置：第一个 canonical_index > key 的现有项之前
    idx = _canonical_index(values)
    key_ci = idx.get(key, 1 << 30)
    params = values['params']
    pos = len(params)
    for i, p in enumerate(params):
        if idx.get(p['unkn'] & 0xFFFFFFFF, 1 << 30) > key_ci:
            pos = i
            break
    params.insert(pos, param)
    values['para_count'] = len(params)
    return True


def remove_override(values: dict, key: int) -> bool:
    """删除指定 key 的覆盖项。返回 True 成功；False 表示未找到。"""
    key &= 0xFFFFFFFF
    params = values['params']
    for i, p in enumerate(params):
        if (p['unkn'] & 0xFFFFFFFF) == key:
            del params[i]
            values['para_count'] = len(params)
            return True
    return False
