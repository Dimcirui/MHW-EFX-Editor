"""材质名与 jamcrc 的会话级缓存。

缓存不持久化，也不内置静态反查表。解析时优先使用已记录名称、绑定网格和场景材质，
最后可选地查询已安装的 MHW Model Editor；该插件不是依赖。
"""

_CACHE = {}  # hash(int) -> name(str)


def record(name: str) -> int:
    """记录一对 (jamcrc(name), name)，返回算出的 hash。"""
    from ..efx_format.hashes import jamcrc
    h = jamcrc(name) & 0xFFFFFFFF
    _CACHE[h] = name
    return h


def lookup(h: int):
    """仅查询会话缓存。"""
    return _CACHE.get(h & 0xFFFFFFFF)


def scan_scene_materials() -> int:
    """记录当前场景的所有材质名，并返回扫描数量。"""
    import bpy
    n = 0
    for mat in bpy.data.materials:
        h = record(mat.name)
        n += 1
    return n


def _mhwme_available() -> bool:
    """判断 MHW Model Editor 的导入算子是否可用。"""
    try:
        import bpy
        return "import_mhw_mod3" in dir(bpy.ops.mhw_mod3)
    except Exception:
        return False


def _mhwme_reverse_lookup(h: int):
    """可选地查询已安装 MHW Model Editor 的反查表。"""
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
    """按缓存、绑定网格、场景和可选插件的顺序解析名称。"""
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
