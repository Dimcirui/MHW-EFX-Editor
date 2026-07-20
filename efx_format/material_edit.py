"""
efx_format/material_edit.py  —  MATERIAL 结构化编辑核心（纯 Python，零 bpy）

背景（见 memory 与 material_meta.py 顶部注释）：MATERIAL 是两层嵌套
（Tex_Block「材质槽」→ Tex_Set「贴图/参数槽」），本模块在 unpack_material
产出的 values dict 上做编辑/增删，再交给 pack_material 还原字节。已证
pack_material(unpack_material(x)) == x（5792/5792 官方语料零反例，见
tools/scan_material_slots.py），故本模块的“未触碰字段 verbatim 保留”策略
在数学上等价于 PTBEHAVIOR 的逐字段 orig 兜底，不需要额外的 orig_b64 机制。

设计（2026-07 与用户核实过的范围）：
  - 材质槽（Tex_Block）数量真实可变（实测 0~7），增删走本模块的
    add_block/remove_block。
  - 每个材质槽的贴图路径槽位（Tex_Set type=0x80）数量/身份是 shader 类型的
    固定函数（见 material_meta.MATERIAL_SHADER_SLOTS，24/112 种已实测），
    **不做增删**——新建材质槽时一次性按 schema 铺满全部已知槽位（初始为空：
    head=0, path=b''），后续编辑只是「填/清」已存在的槽位（fill_slot_path /
    clear_slot_path），对应 head 字段在 0（空）↔ 606035435（非空）之间切换
    （实测 43063/43071 非空槽为 606035435，8 例为罕见离群值 2013850128，
    未触碰的槽位保留原值不受影响）。
  - 非路径 set 类型（0x06/0x03/0x0A/0x0C/0x15）当黑盒——不解语义、不做增删，
    原样保留在 dict 里，pack_material 自动带出。
  - shader_hash 的编辑是独立的标量覆盖，不联动改动已有 Tex_Set 列表（改了
    shader 类型不会引发槽位重新生成，用户如故意选一个不匹配的类型，是其
    自主选择，不强制一致性——游戏文件本身也没有强制这层一致性）。
"""

HEAD_EMPTY = 0
HEAD_FILLED = 606035435


def _to_signed32(v: int) -> int:
    """无符号 → 有符号 int32（pack_material 用 '<i'，与 unpack 一致存有符号值）。"""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def add_block(values: dict, shader_hash: int) -> dict:
    """新建一个材质槽（Tex_Block），append 到 values['blocks']，返回新 block dict。

    按 material_meta.material_slot_schema(shader_hash) 一次性铺满该材质类型的
    全部已知贴图槽位（初始为空）；无 schema 依据（未实测的 88 种材质类型）则
    新建空材质槽（sets=[]，仅有 shader_hash，用户导入贴图前无槽位可填——
    与"没有实测依据不假设完整性"的原则一致）。
    """
    from . import material_meta as mm

    shader_hash &= 0xFFFFFFFF
    schema = mm.material_slot_schema(shader_hash) or []
    sets = []
    for t in schema:
        sets.append({
            'set': mm.texture_slot_set_tag(t),
            'unkn0': 0,
            't': _to_signed32(t),
            'type': 0x80,
            'head': HEAD_EMPTY,
            'null': 0,
            'path_len': 0,
            'path': b'',
        })
    block = {
        'mat_name_hash': 0,
        'mat_shader': _to_signed32(shader_hash),
        'unkn03': 0,
        'sets': sets,
    }
    values['blocks'].append(block)
    return block


def remove_block(values: dict, index: int) -> bool:
    """删除指定下标的材质槽。返回 True 成功；False = 下标越界。"""
    blocks = values['blocks']
    if not (0 <= index < len(blocks)):
        return False
    del blocks[index]
    return True


def known_slots(block: dict):
    """该材质槽已知 schema 的贴图槽 t 列表（顺序=schema 顺序）；无依据返回 None。"""
    from . import material_meta as mm
    return mm.material_slot_schema(block['mat_shader'])


def find_path_set(block: dict, t: int):
    """在 block['sets'] 里找 type=0x80 且 t 匹配的 Tex_Set；找不到返回 None。"""
    t &= 0xFFFFFFFF
    for s in block['sets']:
        if s['type'] == 0x80 and (s['t'] & 0xFFFFFFFF) == t:
            return s
    return None


def fill_slot_path(block: dict, t: int, path_str: str) -> bool:
    """把 t 对应槽位的路径设为 path_str（非空）；head 切到 606035435。

    返回 True 成功；False = 该 block 里没有这个 t 的 Tex_Set（不做插入——
    槽位数量是 schema 固定的，新增材质槽走 add_block 一次性铺满）。
    """
    s = find_path_set(block, t)
    if s is None:
        return False
    path_b = path_str.encode('utf-8')
    if not path_b.endswith(b'\x00'):
        path_b += b'\x00'
    s['path'] = path_b
    s['path_len'] = len(path_b)
    s['head'] = HEAD_FILLED
    s['null'] = 0
    return True


def clear_slot_path(block: dict, t: int) -> bool:
    """把 t 对应槽位清空（path=b''，head=0）。返回 True 成功；False = 找不到该槽位。"""
    s = find_path_set(block, t)
    if s is None:
        return False
    s['path'] = b''
    s['path_len'] = 0
    s['head'] = HEAD_EMPTY
    s['null'] = 0
    return True


def slot_path_str(s: dict) -> str:
    """Tex_Set(type=0x80) → 当前路径字符串（去尾 \\x00）；供 UI 显示。"""
    return s['path'].split(b'\x00')[0].decode('latin1')
