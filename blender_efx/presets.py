"""
blender_efx/presets.py  —  L1.2 块字段值预设

功能：
  - save_block_preset(block_obj, preset_name)：把可编辑块的字段值存为 JSON
  - load_block_preset(block_obj, json_path)：把 JSON 字段值写回已有块
  - reload_presets(type_name)：扫目录生成 EnumProperty 用列表

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法
  - 仅改已有块的字段值（不创建新块/body），复用现有"改值→脏→导出"路径
  - 预设 JSON 里浮点用 repr 保证精度；uint 用字符串
  - 只存可编辑块（is_editable=True）
  - 类型校验：type_hash 不一致拒绝 load
  - read_only 字段加载时跳过（永远保持 orig_b64 路径）

JSON 结构（保存一个块）：
{
  "type_hash": "1003792849",        # 十进制字符串
  "type_name": "EMITTERSHAPE3D",    # 显示名，仅供人读，load 不依赖此字段
  "fields": {
    "ori_name": {
      "data_type": "FLOAT",
      "value": <repr精度字符串或数值>
    },
    ...
  }
}

浮点精度：FLOAT/FLOAT*_STR/FLOAT* 等字段一律用 repr(float) 转成字符串存储，
load 时用 float(s) 还原。uint 用十进制字符串。整数/bool 直接用 JSON 原生类型。
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
    """把 _encode_path_ident 产生的 identifier 解码回原始文件路径。
    若解码失败（旧格式直接路径）则原样返回，保持向后兼容。
    """
    try:
        return base64.urlsafe_b64decode(ident.encode("ascii")).decode("utf-8")
    except Exception:
        return ident


# ─────────────────────────────────────────────────────────────────────────────
# 文件名 ASCII 化 + 内置显示名（彻底绕开中文文件名乱码）
# ─────────────────────────────────────────────────────────────────────────────
# 设计：磁盘文件名一律纯 ASCII（os.scandir/identifier 永不碰非 ASCII 字节），
# 中文友好名存进 JSON 的 "display_name" 字段，下拉菜单从 JSON 内容里用 utf-8
# 读出来显示。这样从源头消除文件名编码 + enum identifier 两类乱码诱因。

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


# 显示名缓存：json_path -> (mtime, display_name)，避免每次重绘都解析大 JSON
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
# 路径工具：找到 presets/ 目录（位于 blender_efx/ 同级的扩展包根下）
# ─────────────────────────────────────────────────────────────────────────────

def _presets_root() -> str:
    """
    返回 presets/ 目录的绝对路径。
    位置：本文件（blender_efx/presets.py）所在目录的父级（扩展包根）下的 presets/。
    即：<efx_editor_root>/presets/
    """
    here = os.path.dirname(os.path.abspath(__file__))
    package_root = os.path.dirname(here)
    return os.path.join(package_root, "presets")


def _preset_dir(type_name: str) -> str:
    """返回 presets/<TYPENAME>/ 目录路径（type_name 已是大写）。"""
    return os.path.join(_presets_root(), type_name)


def _type_name_from_hash(type_hash_str: str) -> str:
    """
    从 type_hash_str（十进制字符串）查 HASH_TO_NAME，返回大写类型名。
    找不到时返回 "UNKNOWN_<hash>" 作为回退目录名。
    """
    try:
        from ..efx_format.hashes import HASH_TO_NAME
        h = int(type_hash_str)
        name = HASH_TO_NAME.get(h, "")
        if name:
            return name.upper()
    except (ImportError, ValueError):
        pass
    return f"UNKNOWN_{type_hash_str}"


# ─────────────────────────────────────────────────────────────────────────────
# _item_to_json_value：把 EFXFieldItem 的当前值序列化为 JSON 可存类型
# ─────────────────────────────────────────────────────────────────────────────

def _item_to_json_value(item):
    """
    把 EFXFieldItem 的当前值转为 JSON 兼容的 Python 对象。

    浮点精度策略：
      - 单个 float (FLOAT) → repr(float_value) 字符串
      - 含浮点的向量/数组 (FLOAT2/FLOAT3/…/FLOAT*_STR) → 逗号分隔 repr 字符串
      - UINT → 十进制字符串（已在 uint_str 中）
      - 整数/bool → 直接 int/bool
      - 字符串（STRING/OPAQUE/uint_str/array_str 等） → 直接字符串
    """
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
        # 存储为 repr 精度浮点字符串列表（0-1 范围）
        return ",".join(repr(float(v)) for v in item.color_rgba_value)

    # COLOR_RGB: 保留分支（当前无 spec 映射到此 dtype，不会执行）
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
        # 重新解析后用 repr 写回，保证精度一致
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
        # opaque 字段不存入预设（只读且不可有意义编辑）
        return None

    elif dtype == "STRING":
        return str(item.string_value)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# _json_value_to_item：把 JSON 值写回 EFXFieldItem 的对应值槽
# ─────────────────────────────────────────────────────────────────────────────

def _json_value_to_item(item, data_type: str, value) -> bool:
    """
    把 JSON 解析出的 value 写入 item 对应值槽。
    返回 True 表示写入成功，False 表示写入失败（调用者跳过该字段）。
    不触发 update 回调（由调用者统一置 edited=True + efx_dirty）。
    """
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

        # COLOR_RGB: 保留分支（当前无 spec 映射到此 dtype，不会执行）
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
            # OPAQUE 及未知类型：跳过
            return False

        return True

    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# save_block_preset
# ─────────────────────────────────────────────────────────────────────────────

def save_block_preset(block_obj: bpy.types.Object, preset_name: str) -> str:
    """
    把 block_obj 的 efx_block 字段值存为 JSON 预设文件。

    参数
    ----
    block_obj   : Object — ~TYPE == 'EFX_BLOCK' 的 Blender 对象
    preset_name : str    — 预设名称（不含 .json 扩展名）

    返回
    ----
    str — 保存的 JSON 文件路径

    异常
    ----
    ValueError — 对象不是可编辑 EFX_BLOCK，或 preset_name 非法
    """
    # ── 校验 ──────────────────────────────────────────────────────────────────
    if block_obj is None or block_obj.get("~TYPE") != "EFX_BLOCK":
        raise ValueError("save_block_preset：目标对象不是 EFX_BLOCK")

    bp = block_obj.efx_block
    if not bp.is_editable:
        raise ValueError("save_block_preset：此块不可编辑（is_editable=False），无法保存预设")

    if not preset_name or "/" in preset_name or "\\" in preset_name or ".." in preset_name:
        raise ValueError(f"save_block_preset：非法预设名称 {preset_name!r}")

    # ── 确定类型名 ────────────────────────────────────────────────────────────
    type_name = _type_name_from_hash(bp.type_hash_str)

    # ── 构建 JSON dict ────────────────────────────────────────────────────────
    # display_name 存用户原始名（可含中文，下拉从这里 utf-8 读出来显示）
    preset_dict = {
        "type_hash": bp.type_hash_str,
        "type_name": type_name,
        "display_name": preset_name,
        "fields": {},
    }

    for item in bp.field_items:
        # 跳过 opaque hint 项（ori_name 以 '__' 开头）和 read_only 字段
        if item.ori_name.startswith("__"):
            continue

        json_val = _item_to_json_value(item)
        if json_val is None:
            # OPAQUE 等不序列化
            continue

        preset_dict["fields"][item.ori_name] = {
            "data_type": item.data_type,
            "value": json_val,
        }

    # ── 确保目录存在 ──────────────────────────────────────────────────────────
    save_dir = _preset_dir(type_name)
    os.makedirs(save_dir, exist_ok=True)

    # 文件名一律 ASCII：净化用户名 → 空则退回类型名 → 仍空用 "preset"；重名加 _0/_1…
    fname = _unique_ascii_filename(save_dir, preset_name, type_name)
    json_path = os.path.join(save_dir, fname + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(preset_dict, f, ensure_ascii=False, indent=4)

    return json_path


# ─────────────────────────────────────────────────────────────────────────────
# load_block_preset
# ─────────────────────────────────────────────────────────────────────────────

def load_block_preset(block_obj: bpy.types.Object, json_path: str) -> int:
    """
    把 JSON 预设文件的字段值写回 block_obj.efx_block 的对应字段。

    校验：type_hash 必须与目标块一致（不一致立即拒绝，保证类型安全）。
    只写 schema 里存在且非 read_only 的字段（read_only 字段永远跳过）。
    写入后置 item.edited=True 和 block.efx_dirty=True（走现有编辑→导出路径）。

    参数
    ----
    block_obj : Object — ~TYPE == 'EFX_BLOCK' 的 Blender 对象
    json_path : str    — 预设 JSON 文件路径

    返回
    ----
    int — 成功写入的字段数

    异常
    ----
    ValueError — 类型不匹配、对象不可编辑、文件读取失败
    """
    # ── 校验对象 ──────────────────────────────────────────────────────────────
    if block_obj is None or block_obj.get("~TYPE") != "EFX_BLOCK":
        raise ValueError("load_block_preset：目标对象不是 EFX_BLOCK")

    bp = block_obj.efx_block
    if not bp.is_editable:
        raise ValueError("load_block_preset：此块不可编辑（is_editable=False），无法应用预设")

    # ── 读取 JSON ─────────────────────────────────────────────────────────────
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            preset_dict = json.load(f)
    except Exception as exc:
        raise ValueError(f"load_block_preset：读取预设文件失败：{exc}")

    # ── 类型 hash 校验（核心安全检查）────────────────────────────────────────
    preset_hash = str(preset_dict.get("type_hash", ""))
    if preset_hash != bp.type_hash_str:
        raise ValueError(
            f"load_block_preset：类型不匹配！"
            f"预设 type_hash={preset_hash!r}，"
            f"目标块 type_hash={bp.type_hash_str!r}。"
            f"预设只能应用于相同类型的块。"
        )

    # ── 建 name→item 映射（快速查找）─────────────────────────────────────────
    item_by_name = {}
    for item in bp.field_items:
        if not item.ori_name.startswith("__"):
            item_by_name[item.ori_name] = item

    # ── 逐字段写入 ────────────────────────────────────────────────────────────
    fields_dict = preset_dict.get("fields", {})
    written = 0

    # 使用 fields._LOADING 守卫：写入期间临时关闭 update 回调自动置脏，
    # 写完后统一手动置 edited=True 和 efx_dirty=True，更清晰可控。
    from . import fields as _fields
    old_loading = _fields._LOADING
    _fields._LOADING = True

    try:
        for ori_name, field_entry in fields_dict.items():
            item = item_by_name.get(ori_name)
            if item is None:
                # schema 里没有此字段（版本差异），跳过
                continue

            if item.read_only:
                # read_only 字段永远跳过（orig_b64 路径）
                continue

            data_type = field_entry.get("data_type", "")
            if data_type != item.data_type:
                # data_type 不匹配（预设与当前 schema 有差异），跳过
                continue

            value = field_entry.get("value")
            if value is None:
                continue

            ok = _json_value_to_item(item, data_type, value)
            if ok:
                item.edited = True
                written += 1

    finally:
        _fields._LOADING = old_loading

    # ── 统一置块脏标记 ────────────────────────────────────────────────────────
    if written > 0:
        bp.efx_dirty = True

    return written


# ─────────────────────────────────────────────────────────────────────────────
# reload_presets：扫目录生成 EnumProperty 用列表
# ─────────────────────────────────────────────────────────────────────────────

def reload_presets(type_name: str):
    """
    扫 presets/<TYPE_NAME>/ 目录，返回 EnumProperty items 列表：
      [(json_相对路径, 显示名, ""), ...]

    type_name 应是大写类型名（如 "EMITTERSHAPE3D"）。
    若目录不存在或无 .json 文件则返回空列表。

    返回值可直接传给 EnumProperty(items=...) 或作为动态 items 回调的返回值。
    """
    preset_dir = _preset_dir(type_name)
    result = []

    if not os.path.isdir(preset_dir):
        return result

    for entry in sorted(os.scandir(preset_dir), key=lambda e: e.name):
        if entry.is_file() and entry.name.lower().endswith(".json"):
            # 显示名从 JSON 内的 display_name 读（utf-8，免疫文件名编码）；
            # identifier 用 base64(纯 ASCII 文件名路径)。
            display_name = _read_display_name(entry.path)
            result.append((_encode_path_ident(entry.path), display_name, ""))

    return result
