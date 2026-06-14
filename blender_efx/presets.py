"""
blender_efx/presets.py  —  预设公共工具 + 字段值序列化助手

现存内容（旧「字段值预设」存/取盘函数 save/load_block_preset/reload_presets 已移除，
块预设改为 block_ops 的整块增删机制）：
  - 路径/命名助手：_presets_root / _preset_dir 无、_unique_ascii_filename /
    _read_display_name / _encode_path_ident / _decode_path_ident
    （供 block_ops.py、add_ops.py 复用）
  - 字段值序列化：_item_to_json_value / _json_value_to_item
    （供 operators.py 的字段即时复制/粘贴复用）

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法
  - 预设 JSON 里浮点用 repr 保证精度；uint 用字符串
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
# 路径工具：用户持久化预设目录（重装扩展不丢失）
# ─────────────────────────────────────────────────────────────────────────────

_migrate_done = False  # 真正的 once 标志，模块级，热重载时重置


def _presets_root() -> str:
    """
    返回预设根目录的绝对路径（用户数据目录，重装扩展不丢失）。
    路径：<Blender用户数据>/scripts/presets/efx_editor/
    首次调用时自动把包内 presets/ 的预设同步到用户目录（每次 Blender 会话只跑一次）。
    """
    global _migrate_done
    new_root = bpy.utils.user_resource("SCRIPTS", path="presets/efx_editor")
    os.makedirs(new_root, exist_ok=True)
    if not _migrate_done:
        _migrate_presets_once(new_root)
        _migrate_done = True
    return new_root


def _migrate_presets_once(new_root: str):
    """
    把包内 presets/ 目录的 JSON 文件同步到用户目录：
    - 跳过已存在的同名文件（用户自定义预设不覆盖）
    - 清理用户目录中已不属于当前分类体系的旧 slug 子目录
    """
    import shutil
    from ..efx_format.categories import BLOCK_CATEGORY_LABELS

    here = os.path.dirname(os.path.abspath(__file__))
    old_root = os.path.join(os.path.dirname(here), "presets")
    if not os.path.isdir(old_root):
        return

    # 清理用户目录里不再属于当前分类体系的旧 __blocks__ 子目录
    blocks_user = os.path.join(new_root, "__blocks__")
    if os.path.isdir(blocks_user):
        for entry in os.listdir(blocks_user):
            entry_path = os.path.join(blocks_user, entry)
            if os.path.isdir(entry_path) and entry not in BLOCK_CATEGORY_LABELS:
                shutil.rmtree(entry_path, ignore_errors=True)

    # 从包内预设目录复制新文件（跳过已有同名，保留用户自定义）
    for dirpath, _dirs, files in os.walk(old_root):
        rel = os.path.relpath(dirpath, old_root)
        dest_dir = os.path.join(new_root, rel) if rel != "." else new_root
        for fname in files:
            if not fname.endswith(".json"):
                continue
            dst = os.path.join(dest_dir, fname)
            if not os.path.exists(dst):
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(os.path.join(dirpath, fname), dst)


# ─────────────────────────────────────────────────────────────────────────────
# _item_to_json_value：把 EFXFieldItem 的当前值序列化为 JSON 可存类型
#   （供 operators.py 的字段即时复制/粘贴复用；旧字段值预设的存/取盘函数已移除）
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
