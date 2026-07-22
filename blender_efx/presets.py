"""
blender_efx/presets.py  —  预设公共工具 + 字段值序列化助手

现存内容（旧「字段值预设」存/取盘函数 save/load_attribute_preset/reload_presets 已移除，
属性预设改为 attribute_ops 的整属性增删机制）：
  - 路径/命名助手：_presets_root / _preset_dir 无、_unique_ascii_filename /
    _read_display_name / _encode_path_ident / _decode_path_ident
    （供 attribute_ops.py、add_ops.py 复用）
  - 字段值序列化：_item_to_json_value / _json_value_to_item
    （供 operators.py 的字段即时复制/粘贴复用）

设计约束（参照 CLAUDE.md）：
  - Python 3.11 语法
  - 预设 JSON 里浮点用 repr 保证精度；uint 用字符串
  - read_only 字段加载时跳过（永远保持 orig_b64 路径）

JSON 结构（保存一个属性）：
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


def _is_stock_duplicate(old_path: str, new_path: str) -> bool:
    """
    old_path（__blocks__ 里的旧文件）是否与 new_path（__attributes__ 里同分类/同文件名的
    现行文件）内容完全一致（type_hash + data_bytes 均相同）。

    只比这两个字段——efx_preset_kind/display_name 允许因重命名而不同（如 SHOVEL 改了译名），
    不影响"是否为随插件下发的同一份内置预设"的判定。任一读取失败、或字段不一致，
    都视为不是重复（保守：宁可留着，不误删用户内容）。
    """
    if not os.path.isfile(new_path):
        return False
    try:
        with open(old_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        with open(new_path, "r", encoding="utf-8") as f:
            new = json.load(f)
    except Exception:
        return False
    return (isinstance(old, dict) and isinstance(new, dict)
            and old.get("type_hash") == new.get("type_hash")
            and old.get("data_bytes") == new.get("data_bytes"))


# 2026-07 分类重构：这些 slug 在新分类树里彻底不存在（改名/拆分/合并/取消，见
# efx_format/categories.py 顶部注释）。用户目录里只要还有任意一个，就说明还没跑过
# 新版迁移（_migrate_to_new_category_tree）。不含 skeleton/misc——这两个新旧同名，
# 光看文件夹名判断不了迁移状态，但一旦触发迁移，仍会连它们一起处理（可能有旧扁平
# 残留，如老版本的 misc/RANDOMFIX.json 需要挪到 misc/others/RANDOMFIX.json）。
_OLD_ONLY_ATTRIBUTE_CATEGORY_SLUGS = frozenset({
    "renderer", "sprite_mod", "mesh_over", "emitter", "motion",
    "visibility", "lifecycle", "extern_decl", "char_effect", "behavior", "ui_2d",
})


def _is_autogen_preset_name(display_name: str, type_name: str) -> bool:
    """display_name 是否为自动生成式（空 / 等于 type_name / 「TYPE（中文）」），而非用户自定义。
    跟 attribute_ops.py::_is_autogen_name 同一判据，这里独立复制一份小函数，避免
    presets.py（被 attribute_ops.py 依赖）反向 import attribute_ops.py 造成循环依赖。"""
    if display_name in ("", type_name):
        return True
    return display_name.startswith(type_name + "（") and display_name.endswith("）")


def _build_official_preset_fingerprints(package_attrs_dir: str) -> tuple:
    """扫描包内 presets/__attributes__/ 全部文件，返回 (exact_fingerprints, known_type_names)：
    - exact_fingerprints：(type_hash, data_bytes) -> display_name，内容做 key（不管文件在哪个
      文件夹——这次分类重构几乎所有类型的文件夹路径都变了，按路径比对会完全失效，只能按内容）
    - known_type_names：type_hash -> type_name，只要该类型当前有官方预设就登记，不要求内容
      精确匹配（配合 _is_autogen_preset_name 识别"用户没改名、只是内容比当前官方版本旧"的情况——
      插件这段时间对默认值做了大量修订，老用户装的版本内容早就跟最新官方版本不一致，但那不是
      用户自定义，只是版本旧，不该被误判成自定义内容塞进 custom/）
    """
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
                exact_fingerprints[(d.get("type_hash"), d.get("data_bytes"))] = d.get("display_name", "")
                if d.get("type_hash") is not None:
                    known_type_names[d.get("type_hash")] = d.get("type_name", "")
            except Exception:
                continue
    return exact_fingerprints, known_type_names


def _migrate_to_new_category_tree(new_root: str, package_attrs_dir: str):
    """
    2026-07 属性预设分类重构的一次性迁移：旧 13 类扁平/浅层目录 → 新 10 类
    （部分再分子组）目录结构，同时把用户已有的自定义预设隔离进 custom/。

    触发条件：用户 __attributes__/ 下存在任意一个 _OLD_ONLY_ATTRIBUTE_CATEGORY_SLUGS
    里的文件夹。全新安装或已迁移过（旧文件夹已清空/不存在）则什么都不做——天然一次性，
    不需要额外持久化"是否已迁移"标记。

    步骤：
    1. 备份整个用户 __attributes__/ 到 __attributes__.backup_<时间戳>/（唯一安全网，
       不做用户可见报告/二次确认弹窗——本函数任何异常都静默吞掉、不中断注册流程，
       出问题时用户自己有备份可以手动核对/恢复）
    2. 建官方内容指纹表（见 _build_official_preset_fingerprints）
    3. 遍历用户 __attributes__/ 下现有全部 .json（custom/ 本身不碰，其内容已经是用户
       数据），逐条判定：
       a. 内容 + display_name 都跟某条官方指纹完全一致 → 官方预设原样拷贝 → 删除
       b. 内容不完全匹配，但 type_hash 是已知官方类型 **且** display_name 是自动生成式
          （用户没有改名）→ 判定"内容是旧版本官方默认值，不是用户自定义"（插件近期对
          大量类型的默认值做过修订，装过旧版本的用户手上的内容早就跟当前官方版本不一致，
          这不代表用户编辑过）→ 同样删除
       c. 其余（全新类型 / 改过字段值又改过名字 / 未知类型）→ 判定用户内容 → 挪进
          custom/（保守：宁可 custom 里多一份无害重复，不冒险丢真正的自定义内容）
       a/b 两种"删除"情况都由下面的强制同步阶段在正确新路径放回当前最新的等价文件。
    4. 清理迁移后搬空的旧目录（自底向上，非空则 rmdir 失败静默跳过，不递归强删）
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
                    type_hash = d.get("type_hash")
                    type_name = d.get("type_name", "")
                    key = (type_hash, d.get("data_bytes"))
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
        pass  # 备份已经在最前面做了；任何异常都不中断注册流程


def _migrate_presets_once(new_root: str):
    """
    把包内 presets/ 目录的 JSON 文件同步到用户目录：
    - __attributes__/ 下除 custom/ 外，一律以包内版本为准强制覆盖（官方内容，随插件
      更新随时可能改默认值，2026-07 起不再"已存在就跳过"——那样会导致老用户永远收不到
      内置预设的后续更新）；custom/ 完全跳过不碰，那是用户专属数据
    - __attributes__/ 之外的其它预设种类（__entries__ 等，非本次重构范围）维持旧策略：
      跳过已存在的同名文件
    - 精准清理 3.0 重命名前遗留的 __blocks__ 旧目录：只删除与 __attributes__ 里
      同分类/同文件名的现行文件内容完全一致的条目（即确认是随插件下发、现已有
      __attributes__ 等价替代的内置预设），不区分就整个目录删掉的做法删过一次
      用户数据，故改为逐文件比对，用户自定义/编辑过的文件不受影响地保留。
      （类别本身发生变化的条目，如 SHOVEL 从 char_effect 挪到了 lifecycle，因两侧
      路径不对应会被判定为"不是重复"而保留，属于无害的孤儿文件，可自行清理。）
    - __bodies__ 不做删除/清理：这批基本是用户自己攒的自定义 entry 预设，已接
      只读兼容读取（list_entry_presets() 一并扫描 + add_entry_from_preset_dict()
      自动转换旧 schema key），无需清理。
    """
    import shutil

    here = os.path.dirname(os.path.abspath(__file__))
    old_root = os.path.join(os.path.dirname(here), "presets")
    if not os.path.isdir(old_root):
        return

    user_attrs_dir = os.path.join(new_root, "__attributes__")
    package_attrs_dir = os.path.join(old_root, "__attributes__")
    custom_root = os.path.join(user_attrs_dir, "custom")

    # 分类重构迁移必须先于下面的同步执行——同步的"非 custom 强制覆盖"策略依赖迁移已经
    # 把用户自定义内容清出非 custom 目录这个前提，否则会直接覆盖掉用户数据。
    _migrate_to_new_category_tree(new_root, package_attrs_dir)

    # 从包内预设目录复制文件：__attributes__/ 下除 custom/ 外强制覆盖，其余维持
    # "已存在就跳过"
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

    # 精准清理旧 __blocks__：仅删掉确认与 __attributes__ 里现行文件内容一致的条目
    # （3.0 改名遗留的历史迁移，跟本次分类重构无关，路径比对法在这里仍然适用——
    # __blocks__ 的相对路径结构从没变过）
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
        # 清掉迁移后变空的分类子目录/根目录（非空则 rmdir 失败，静默跳过——安全，不递归强删）
        for dirpath, dirs, files in os.walk(blocks_dir, topdown=False):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


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
