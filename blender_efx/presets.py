"""预设路径、显示名和字段值 JSON 序列化公共工具。

维护约束：浮点以 ``repr`` 保存、uint 以十进制字符串保存；read_only 字段不能从
预设覆盖原始字节路径。文件名保持 ASCII，用户可见名称存于 JSON。官方预设可同步，
``custom`` 中的用户文件不可覆盖或删除。
"""

import base64
import json
import os
import re

import bpy


def _encode_path_ident(path: str) -> str:
    """把文件路径 base64 编码为纯 ASCII identifier，供 EnumProperty 使用。"""
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")


def _decode_path_ident(ident: str) -> str:
    """解码路径 identifier；不能解码时按旧格式原样返回。"""
    try:
        return base64.urlsafe_b64decode(ident.encode("ascii")).decode("utf-8")
    except Exception:
        return ident


# ─────────────────────────────────────────────────────────────────────────────
# 磁盘文件名保持 ASCII，显示名从 UTF-8 JSON 读取。

def _sanitize_ascii(s: str) -> str:
    """保留 ASCII 字母/数字/下划线/连字符，其余字符丢弃。"""
    return re.sub(r"[^A-Za-z0-9_-]", "", s or "")


def _unique_ascii_filename(directory: str, base_hint: str, fallback: str) -> str:
    """
    在 directory 内生成唯一的纯 ASCII 文件名（不含 .json）。
    base_hint 净化后为空 → 用 fallback（同样净化）；仍为空 → 用 "preset"。
    重名时末尾依次加 _0 / _1 / _2 …（用户约定）。
    """
    base = _sanitize_ascii(base_hint) or _sanitize_ascii(fallback) or "preset"
    candidate = base
    n = 0
    while os.path.exists(os.path.join(directory, candidate + ".json")):
        candidate = "{}_{}".format(base, n)
        n += 1
    return candidate


# json_path -> (mtime, display_name)，避免重绘时重复解析。
_display_name_cache = {}


def _read_display_name(json_path: str) -> str:
    """
    从预设 JSON 读 "display_name"（utf-8，免疫文件名编码问题）。
    缺失/读取失败 → 回退为文件名去 .json。按 mtime 缓存解析结果。
    """
    fallback = os.path.splitext(os.path.basename(json_path))[0]
    try:
        mtime = os.path.getmtime(json_path)
    except OSError:
        return fallback
    cached = _display_name_cache.get(json_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    name = fallback
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        dn = d.get("display_name")
        if isinstance(dn, str) and dn.strip():
            name = dn
    except Exception:
        pass
    _display_name_cache[json_path] = (mtime, name)
    return name


# ─────────────────────────────────────────────────────────────────────────────
_migrate_done = False


def _presets_root() -> str:
    """返回用户预设根目录，并在本次模块生命周期首次访问时同步内置预设。"""
    global _migrate_done
    new_root = bpy.utils.user_resource("SCRIPTS", path="presets/efx_editor")
    os.makedirs(new_root, exist_ok=True)
    if not _migrate_done:
        _migrate_presets_once(new_root)
        _migrate_done = True
    return new_root


def _attr_fingerprint(d) -> tuple:
    """属性预设（v1 / v2）的 ``(type_hash, type_name, 内容指纹)``；无法组装时指纹为 None。

    内容指纹是组装出的字节，因此同一内容的 v1 与 v2 预设指纹相同。
    """
    from ..efx_format.assembly import attribute_preset_type, build_preset
    if not isinstance(d, dict) or d.get("efx_preset_kind") != "attribute":
        return None, "", None
    type_hash, type_name = attribute_preset_type(d)
    try:
        key = build_preset(d)
    except Exception:
        key = None
    return type_hash, type_name, key


def _is_stock_duplicate(old_path: str, new_path: str) -> bool:
    """判断预设类型和内容是否相同；读取异常时保守保留文件。"""
    if not os.path.isfile(new_path):
        return False
    try:
        with open(old_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        with open(new_path, "r", encoding="utf-8") as f:
            new = json.load(f)
    except Exception:
        return False
    old_key = _attr_fingerprint(old)[2]
    return old_key is not None and old_key == _attr_fingerprint(new)[2]


# 旧分类目录的存在表示需要迁移属性预设树。
_OLD_ONLY_ATTRIBUTE_CATEGORY_SLUGS = frozenset({
    "renderer", "sprite_mod", "mesh_over", "emitter", "motion",
    "visibility", "lifecycle", "extern_decl", "char_effect", "behavior", "ui_2d",
})


def _is_autogen_preset_name(display_name: str, type_name: str) -> bool:
    """判断显示名是否为类型自动生成，而非用户自定义名称。"""
    if display_name in ("", type_name):
        return True
    return display_name.startswith(type_name + "（") and display_name.endswith("）")


def _build_official_preset_fingerprints(package_attrs_dir: str) -> tuple:
    """建立官方预设内容指纹和已知类型表，供迁移时识别官方内容。"""
    exact_fingerprints = {}
    known_type_names = {}
    if not os.path.isdir(package_attrs_dir):
        return exact_fingerprints, known_type_names
    for dirpath, _dirs, files in os.walk(package_attrs_dir):
        for fname in files:
            if not fname.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(dirpath, fname), "r", encoding="utf-8") as f:
                    d = json.load(f)
                type_hash, type_name, key = _attr_fingerprint(d)
                if key is not None:
                    exact_fingerprints[key] = d.get("display_name", "")
                if type_hash is not None:
                    known_type_names[type_hash] = type_name
            except Exception:
                continue
    return exact_fingerprints, known_type_names


def _migrate_to_new_category_tree(new_root: str, package_attrs_dir: str):
    """迁移旧属性分类树。

    迁移前备份属性目录；不能确定为官方内容的文件必须移入 ``custom``，清理时仅
    移除空目录。官方内容由后续同步恢复。
    """
    if not os.path.isdir(new_root):
        return
    attrs_dir = os.path.join(new_root, "__attributes__")
    if not os.path.isdir(attrs_dir):
        return
    if not any(os.path.isdir(os.path.join(attrs_dir, slug))
               for slug in _OLD_ONLY_ATTRIBUTE_CATEGORY_SLUGS):
        return  # 已迁移过或全新安装

    import shutil
    import time as _time

    try:
        custom_dir = os.path.join(attrs_dir, "custom")

        stamp = _time.strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(new_root, f"__attributes__.backup_{stamp}")
        if not os.path.isdir(backup_dir):
            shutil.copytree(attrs_dir, backup_dir)

        exact_fingerprints, known_type_names = _build_official_preset_fingerprints(package_attrs_dir)

        for dirpath, _dirs, files in os.walk(attrs_dir):
            if dirpath == custom_dir or dirpath.startswith(custom_dir + os.sep):
                continue
            for fname in files:
                if not fname.lower().endswith(".json"):
                    continue
                path = os.path.join(dirpath, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    type_hash, type_name, key = _attr_fingerprint(d)
                    display_name = d.get("display_name", "")
                except Exception:
                    type_hash, type_name, key, display_name = None, "", None, ""

                exact_match = key is not None and exact_fingerprints.get(key) == display_name
                stale_official = (
                    not exact_match
                    and type_hash is not None
                    and type_hash in known_type_names
                    and _is_autogen_preset_name(display_name, type_name)
                )
                if exact_match or stale_official:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                else:
                    os.makedirs(custom_dir, exist_ok=True)
                    base_hint = display_name or os.path.splitext(fname)[0]
                    new_name = _unique_ascii_filename(custom_dir, base_hint, os.path.splitext(fname)[0])
                    try:
                        shutil.move(path, os.path.join(custom_dir, new_name + ".json"))
                    except OSError:
                        pass

        for dirpath, _dirs, _files in os.walk(attrs_dir, topdown=False):
            if dirpath == attrs_dir or dirpath == custom_dir:
                continue
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    except Exception:
        pass


def _migrate_presets_once(new_root: str):
    """同步包内预设到用户目录。

    官方属性目录可覆盖同步，``custom``、Entry 预设和其它已有预设不得覆盖。旧
    ``__blocks__`` 仅在确认存在等价现行文件时清理。
    """
    import shutil

    here = os.path.dirname(os.path.abspath(__file__))
    old_root = os.path.join(os.path.dirname(here), "presets")
    if not os.path.isdir(old_root):
        return

    user_attrs_dir = os.path.join(new_root, "__attributes__")
    package_attrs_dir = os.path.join(old_root, "__attributes__")
    custom_root = os.path.join(user_attrs_dir, "custom")

    # 先迁移，才能安全地同步非 custom 官方目录。
    _migrate_to_new_category_tree(new_root, package_attrs_dir)

    # 官方属性目录同步，custom 和其它预设种类保留已有文件。
    for dirpath, _dirs, files in os.walk(old_root):
        rel = os.path.relpath(dirpath, old_root)
        dest_dir = os.path.join(new_root, rel) if rel != "." else new_root
        under_attrs = dest_dir == user_attrs_dir or dest_dir.startswith(user_attrs_dir + os.sep)
        under_custom = dest_dir == custom_root or dest_dir.startswith(custom_root + os.sep)
        force_sync = under_attrs and not under_custom
        for fname in files:
            if not fname.endswith(".json"):
                continue
            dst = os.path.join(dest_dir, fname)
            if force_sync or not os.path.exists(dst):
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(os.path.join(dirpath, fname), dst)

    # 仅清理已被现行属性预设等价替代的旧文件。
    blocks_dir = os.path.join(new_root, "__blocks__")
    if os.path.isdir(blocks_dir):
        for dirpath, _dirs, files in os.walk(blocks_dir):
            for fname in files:
                if not fname.endswith(".json"):
                    continue
                old_path = os.path.join(dirpath, fname)
                rel = os.path.relpath(old_path, blocks_dir)
                new_path = os.path.join(user_attrs_dir, rel)
                if _is_stock_duplicate(old_path, new_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
        # 只删除迁移后为空的目录。
        for dirpath, dirs, files in os.walk(blocks_dir, topdown=False):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def _item_to_json_value(item):
    """将字段值转换为 JSON 兼容表示；浮点使用 repr，opaque 返回 None。"""
    dtype = item.data_type

    if dtype == "FLOAT":
        return repr(float(item.float_value))

    elif dtype == "INT":
        return int(item.int_value)

    elif dtype == "UINT":
        return str(item.uint_str)

    elif dtype == "BOOL":
        return bool(item.bool_value)

    elif dtype == "BYTE1":
        return int(item.byte1_value)

    elif dtype == "SHORT1":
        return int(item.short1_value)

    elif dtype == "FLOAT2":
        return ",".join(repr(float(v)) for v in item.float2_value)

    elif dtype == "FLOAT3":
        return ",".join(repr(float(v)) for v in item.float3_value)

    elif dtype == "FLOAT4":
        return ",".join(repr(float(v)) for v in item.float4_value)

    elif dtype == "FLOAT6":
        return ",".join(repr(float(v)) for v in item.float6_value)

    elif dtype == "COLOUR":
        return list(int(x) for x in item.colour_value)

    elif dtype == "COLOR_RGBA":
        return ",".join(repr(float(v)) for v in item.color_rgba_value)

    elif dtype == "COLOR_RGB":
        return ",".join(repr(float(v)) for v in item.color_rgb_value)

    elif dtype == "INT2":
        return list(int(x) for x in item.int2_value)

    elif dtype == "INT3":
        return list(int(x) for x in item.int3_value)

    elif dtype == "INT4":
        return list(int(x) for x in item.int4_value)

    elif dtype == "INT_PAIR":
        return str(item.int_pair_str)

    elif dtype == "FLOAT2_STR":
        parts = item.float2_str.split(",")
        return ",".join(repr(float(p)) for p in parts if p.strip())

    elif dtype == "FLOAT3_STR":
        parts = item.float3_str.split(",")
        return ",".join(repr(float(p)) for p in parts if p.strip())

    elif dtype == "FLOAT5_STR":
        parts = item.float5_str.split(",")
        return ",".join(repr(float(p)) for p in parts if p.strip())

    elif dtype == "FLOAT8_STR":
        parts = item.float8_str.split(",")
        return ",".join(repr(float(p)) for p in parts if p.strip())

    elif dtype == "FLOAT16_STR":
        parts = item.float16_str.split(",")
        return ",".join(repr(float(p)) for p in parts if p.strip())

    elif dtype == "INT10_STR":
        return str(item.int10_str)

    elif dtype == "INT16_STR":
        return str(item.int16_str)

    elif dtype == "ARRAY_STR":
        return str(item.array_str)

    elif dtype == "OPAQUE":
        return None

    elif dtype == "STRING":
        return str(item.string_value)

    return None


def _json_value_to_item(item, data_type: str, value) -> bool:
    """将 JSON 值写入匹配的字段槽；调用者负责统一标记编辑状态。"""
    try:
        if data_type == "FLOAT":
            item.float_value = float(value)

        elif data_type == "INT":
            item.int_value = int(value)

        elif data_type == "UINT":
            item.uint_str = str(value)

        elif data_type == "BOOL":
            item.bool_value = bool(value)

        elif data_type == "BYTE1":
            item.byte1_value = max(0, min(255, int(value)))

        elif data_type == "SHORT1":
            item.short1_value = max(-32768, min(32767, int(value)))

        elif data_type == "FLOAT2":
            parts = str(value).split(",")
            item.float2_value = (float(parts[0]), float(parts[1]))

        elif data_type == "FLOAT3":
            parts = str(value).split(",")
            item.float3_value = (float(parts[0]), float(parts[1]), float(parts[2]))

        elif data_type == "FLOAT4":
            parts = str(value).split(",")
            item.float4_value = (float(parts[0]), float(parts[1]),
                                 float(parts[2]), float(parts[3]))

        elif data_type == "FLOAT6":
            parts = str(value).split(",")
            item.float6_value = tuple(float(p) for p in parts[:6])

        elif data_type == "COLOUR":
            v = list(value)
            item.colour_value = (int(v[0]), int(v[1]), int(v[2]), int(v[3]))

        elif data_type == "COLOR_RGBA":
            parts = str(value).split(",")
            item.color_rgba_value = (float(parts[0]), float(parts[1]),
                                     float(parts[2]), float(parts[3]))

        elif data_type == "COLOR_RGB":
            parts = str(value).split(",")
            item.color_rgb_value = (float(parts[0]), float(parts[1]), float(parts[2]))

        elif data_type == "INT2":
            v = list(value)
            item.int2_value = (int(v[0]), int(v[1]))

        elif data_type == "INT3":
            v = list(value)
            item.int3_value = (int(v[0]), int(v[1]), int(v[2]))

        elif data_type == "INT4":
            v = list(value)
            item.int4_value = (int(v[0]), int(v[1]), int(v[2]), int(v[3]))

        elif data_type == "INT_PAIR":
            item.int_pair_str = str(value)

        elif data_type == "FLOAT2_STR":
            item.float2_str = str(value)

        elif data_type == "FLOAT3_STR":
            item.float3_str = str(value)

        elif data_type == "FLOAT5_STR":
            item.float5_str = str(value)

        elif data_type == "FLOAT8_STR":
            item.float8_str = str(value)

        elif data_type == "FLOAT16_STR":
            item.float16_str = str(value)

        elif data_type == "INT10_STR":
            item.int10_str = str(value)

        elif data_type == "INT16_STR":
            item.int16_str = str(value)

        elif data_type == "ARRAY_STR":
            item.array_str = str(value)

        elif data_type == "STRING":
            item.string_value = str(value)

        else:
            return False

        return True

    except Exception:
        return False
