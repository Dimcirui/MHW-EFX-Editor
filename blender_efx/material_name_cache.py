"""
blender_efx/material_name_cache.py — 材质名↔hash 会话级缓存（纯内存，不落盘，
不内置任何静态大字典）。

背景：mat_name_hash 只存哈希，.mrl3 本身也只存 jamcrc 后的 materialNameHash，
两者都不带名字字符串——但只要用户在**这次 Blender 会话**里，从任何渠道亲眼
验证过某个 hash 对应的真名（联动导入的网格材质槽名、场景里已有的任意材质、
参考 .mrl3 旁边同名 .mod3 里读到的真名、或者用户自己手打过一次），就把这对
(hash, name) 记下来，后续别处再遇到同一个 hash 就能直接显示真名，不用每次都
现查绑定网格。

跟社区维护的 various_hash_dict.json 反查表（266665 条，16MB）比：那是"把所有
见过的都收进来"，这是"只记这次会话里亲眼验证过的"——小得多，也不会给错名字
（凡是进这张表的都能追溯到一个具体来源，不是猜出来的）。跨 Blender 会话不
持久化：新会话从空开始，重新按下面几级顺序找。

可选增强：若用户同一个 Blender 里还装了 MHW Model Editor，`resolve()` 兜底会
去问它自己内置的 various_hash_dict 要名字（那 266665 条表本来就在它的插件包
里，蹭它现成的，不用我们自己再内嵌一份）；没装就跳过，不算错误，不提示缺失
——纯粹"如果恰好有更好，没有也不影响"的锦上添花，不是功能依赖。
"""

_CACHE = {}  # hash(int) -> name(str)


def record(name: str) -> int:
    """记录一对 (jamcrc(name), name)，返回算出的 hash。"""
    from ..efx_format.hashes import jamcrc
    h = jamcrc(name) & 0xFFFFFFFF
    _CACHE[h] = name
    return h


def lookup(h: int):
    """纯缓存查——不扫描任何东西，命中就返回名字，否则 None。"""
    return _CACHE.get(h & 0xFFFFFFFF)


def scan_scene_materials() -> int:
    """把当前 .blend 里全部材质的名字都算一遍 hash 记进缓存（比只查联动导入的
    绑定网格覆盖面更广——场景里可能还有别的 mod3 导入留下的材质，或者用户
    手动建的同名材质）。返回本次新记录的条数。"""
    import bpy
    n = 0
    for mat in bpy.data.materials:
        h = record(mat.name)
        n += 1
    return n


def _mhwme_available() -> bool:
    """MHW Model Editor 是否已安装并注册了 mod3 导入算子（同 mod3_link.py 的
    model_editor_available() 判据，这里独立复制一份避免额外依赖）。"""
    try:
        import bpy
        return "import_mhw_mod3" in dir(bpy.ops.mhw_mod3)
    except Exception:
        return False


def _mhwme_reverse_lookup(h: int):
    """可选增强：如果用户装了 MHW Model Editor，问它自己内置的
    various_hash_dict（社区维护的 266665 条 hash→名字反查表）要一个名字——
    我们自己不内置这份表（16MB，见模块头部注释），只在它已经装在同一个
    Blender 里时顺手借用，没装就跳过，不算错误也不提示缺失。"""
    if not _mhwme_available():
        return None
    import sys
    for name, mod in list(sys.modules.items()):
        if not name.endswith("mrl3_dicts"):
            continue
        get_dict = getattr(mod, "get_various_hash_dict", None)
        if get_dict is None:
            continue
        try:
            hit = get_dict().get(str(h))
        except Exception:
            continue
        if hit:
            return hit
    return None


def resolve(h: int, bound_objects=()):
    """四级查找：缓存 → 绑定网格材质槽名（最贴合这个具体 EFX 属性）→ 整个场景
    材质名（更广的网，顺带把命中记进缓存）→ MHW Model Editor 的反查表（可选，
    仅当它已装在同一个 Blender 里）。全部落空返回 None（调用方回退显示
    "Hash N"）。"""
    h &= 0xFFFFFFFF
    hit = lookup(h)
    if hit:
        return hit

    from ..efx_format.hashes import jamcrc
    for obj in bound_objects:
        for slot in getattr(obj, "material_slots", ()):
            if slot.material and (jamcrc(slot.material.name) & 0xFFFFFFFF) == h:
                record(slot.material.name)
                return slot.material.name

    scan_scene_materials()
    hit = lookup(h)
    if hit:
        return hit

    hit = _mhwme_reverse_lookup(h)
    if hit:
        record(hit)
        return hit
    return None
