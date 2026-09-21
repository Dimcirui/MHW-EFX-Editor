"""
blender_efx/builtin_entries.py  —  写死在代码里的基础 entry 模板

「基础 3D Entry」「基础 2D Entry」「Root」是每次从零搭 entry 都要用的起手配方，属于插件
功能的一部分，不该跟用户自己攒的预设一样躺在 presets/ 目录里任人删改——放文件里
还会出现「用户删了就再也建不出基础 entry」的坑。所以这些内置在代码中，出现在
entry 预设下拉的最前面，标识符用 `builtin:` 前缀（预设文件的标识符是 urlsafe
base64，不含冒号，不会撞）。

其余 curated 模板（丝带、闪电、MESH 碎片……）仍走 presets/__archetypes__/ 的 JSON：
它们是「配方」，多一个少一个不影响插件能用，而且需要能被用户照着改。
"""

import json
import os


BUILTIN_3D = "builtin:basic_3d"
BUILTIN_2D = "builtin:basic_2d"
BUILTIN_ROOT = "builtin:root"

# 这两个模板此前是文件预设，历次版本在用户预设目录里留下了几份副本：
#   __archetypes__/  随扩展下发的原始位置（播种时"已存在就跳过"，升级不会清掉旧的）
#   __entries__/     用户保存目录（早期版本把它当普通预设存过）
#   __bodies__/      3.0 改名前的旧目录，schema 也是旧的（属性存在 blocks 键下）
# 不清掉的话，下拉里会并排出现三四个内容完全相同的「基础 Entry」。
# 键是相对预设根的路径，值是取代它的内置模板。
_SUPERSEDED = (
    ("__archetypes__/基础Entry.json",   BUILTIN_3D),
    ("__archetypes__/2d_entry_basic.json", BUILTIN_2D),
    ("__entries__/基础Entry.json",      BUILTIN_3D),
    ("__bodies__/基础Body.json",        BUILTIN_3D),
)


_PRESETS = {
    BUILTIN_3D: {
        'efx_preset_kind': 'entry',
        'entry_kind': 'standard',
        'props': {'body_type': '526957114', 'unkn0': '0', 'attr_count': '4', 'null': '0', 'timl_length': '0'},
        'timl_bytes': '',
        'raw': '',
        'source_label': 'basic',
        'source_counts': {'extern': 0, 'entry': 0, 'action': 0},
        'in_eof': False,
        'attributes': [
            {'type_hash': '10286765',
             'data_bytes': 'AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAAAACAPwAAAAAAAIA/AAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIA/AAAAAAAAgD8AAAAAAACAPwAAAAAAAAAA'},
            {'type_hash': '368199626',
             'data_bytes': 'AwAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAD/////'},
            {'type_hash': '1921765292',
             'data_bytes': 'AgAAAAEAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAA'},
            {'type_hash': '1320868484',
             'data_bytes': 'DAAAAAUAAAAAAAAAPAAAAAAAAAAAAAAAAAAAABQAAAAUAAAAAAAAAAAAAAAAAAAA'},
        ],
    },
    BUILTIN_2D: {
        'efx_preset_kind': 'entry',
        'entry_kind': 'standard',
        'props': {'body_type': '1013701303', 'unkn0': '0', 'attr_count': '7', 'null': '0', 'timl_length': '0'},
        'timl_bytes': '',
        'raw': '',
        'source_label': '2D_Entry',
        'source_counts': {'extern': 0, 'entry': 0, 'action': 0},
        'in_eof': False,
        # ScaleAnim（480396424）2026-09-20 移除：不是 2D Entry 的基础组成，不该在起手
        # 配方里默认带上。
        'attributes': [
            {'type_hash': '428328940',
             'data_bytes': 'AQAAAAAAAAAAAAAAAAAAAAAAgD8AAIA/'},
            {'type_hash': '368199626',
             'data_bytes': 'AwAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAAAAAAAAAAAAAAAAAD/////'},
            {'type_hash': '1921765292',
             'data_bytes': 'AgAAAAEAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAA'},
            {'type_hash': '1320868484',
             'data_bytes': 'DAAAAAAAAAAAAAAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'},
            {'type_hash': '1524169119',
             'data_bytes': 'BQAAAAAAAABXa8hk/////wAAIEEAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAgD8AAIBDAAAAAAAAgEMAAAAAAAAAAAAAAAAAAIA/AAAAAAAAAAAAAAAAAACAPwAAAAABAAAAAAAAAAAAAAAA'},
            {'type_hash': '1698970185',
             'data_bytes': 'BQAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgD8AAAAACAAAABgAAAB2ZnhcdXZzXGNtXGNtX2xpZ2h0XzAwMAA='},
            {'type_hash': '1978267738',
             'data_bytes': 'BAAAAGgAAAAAzc3NAQAAAAAAAADNzMw9AAAAAAAAAAABAAAAAACAP83MzD1mZmY/AACAPwAAgD8AAIA/AACAPwAAyEL/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP////8AAQAAAAAAAAAAAAA='},
        ],
    },
    # Root：整段按原样存 raw（entry_kind='root'，add_entry_from_preset_dict 的 root
    # 分支只认 raw，见该函数注释），不走可编辑的 UnitBoundary 结构化路径——
    # RenderTarget/LayoutBank 本身仍未逆向到能拆成字段（见 efx_format/efxfile.py 的
    # RootOpaqueEntry）。
    # ⚠ 这不是单个真实文件里的 Root：全语料 10084 个官方样本扫描过，UnitBoundary/
    # RenderTarget/LayoutBank 三种子条目从未在同一个 Root 里凑齐过（RT 只跟 UB/LB
    # 互斥出现，含 RT 的 18 个样本一个 UB/LB 都没有）。这是拼出来的"全都有"版本：
    # UnitBoundary+LayoutBank 取自 evc1020_014.efx（语料里 UB+LB 组合仅 2 例，这个
    # 的 LayoutBank 最大/最完整），RenderTarget 取自 2d_gm001_900_04.efx（18 个纯
    # RT 样本里字节数最大、贴图路径最完整的一个）。三段各自都是从真实文件里逐字节
    # 摘出来的，拼接后用 EFXFile._parse_root_body 反向验证过能精确解析回同样三个
    # 子条目、再序列化逐字节不变——结构自洽，但这个组合本身没有真机验证过，游戏
    # 是否认这份 Root 未知。
    BUILTIN_ROOT: {
        'efx_preset_kind': 'entry',
        'entry_kind': 'root',
        'props': {},
        'timl_bytes': '',
        'raw': 'mqk5SQEAAAADAAAAAAAAACxxQFQBAAAAAQAAAACAu0UAAEjEAADIwgAAr8MAAEhEAAAWRAAAr0MAAAAANh0yfAwAAAArAAAAdmZ4XGRkc1xnbVxnbTAwMVxnbTAwMV85MDBcZ20wMDFfOTAwXzA0X0JNACsAAAB2ZnhcZGRzXGdtXGdtMDAxXGdtMDAxXzkwMFxnbTAwMV85MDBfMDRfTk0AAQAAAAABAAAAAAEAAAAAAQAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAPwAAAAAAAAAAAAAAAAAAAAAAJHRKAACAQQAAgD8AACBC9vQ3egIAAAACAAAAEAAAAAAAAADANBFDABq2wjBxScSAAXzDCOaZwmjxSsSANFPDgOrGQTQkgcSgxkzDQAdRwgDSTEJACHbDQNAkwZBXq0MA9mXDkDFXwiCT0sMBoDdB8L9cwgDm2sLwN4lDAPGvwYjxTMSA2ChDMB11wiDiwMMg705DQDedwkAfi0LA9RbDMCijwgAL1MMAZWlD0HZQQmASNcSAiO3CgFmWQnD0IkQgl2xD/5NDQABTmUIAIi3CAFMlQSDvG8QA3fRCwJZBQtB8SEQBAAAAODRHsSzDAABit4CwIMMAAEe26ikowwAAKrZOrifDAACAtwalIMMAABW3oq4kwwAAxyXzrjDDAABVOJGpHcMAAG81468owwAAvjYcsSTDAAD/tGOxKMMAAMc39S4gwwAAB7QcMSzDAAAOOLYeIMMAABOuyyUwwwAAVTTcLi3DAAAEAAAAQFZAVgAA7khAVkBWAADfSEBWQFYAACdJQFZAVgAA6khAVkBWAACvSEBWQFYAAMlIQFZAVgAAiEhAVkBWAAChSEBWQFYAAGdIQFZAVgAAN0hAVkBWAABhSEBWQFYAAANIQFZAVgAAIUhAVkBWAAAJSEBWQFYAAIRHQFZAVgAA40cFAAAAAAAAAAAAZiYAAAAAAABmJgAAAAAAAGYmAAAAAAAAZiYAAAAAAABmJgAAAAAAAGYmAAAAAAAAZiYAAAAAAABmJgAAAAAAAGYmAAAAAAAAZiYAAAAAAABmJgAAAAAAAGYmAAAAAAAAZiYAAAAAAABmJgAAAAAAAGYmAAAAAAAAZib/////EQAAAAAAAAAA8EtCgPCPQYimUMSAZMpCAFZWweCcmcSgNwnD4NoPQgC6/EOgK3rDMChowsDqQMNAr0hDcNArQgDNMMMg9CTDWM2GwnDR58MAG33CwPm7QaCHmENAy4fDAF57wrAT/EPAsPJCgJchwRixasTADpjCoBOZQqCjgsQg0RpDoLV5wgA/zUOgyyfD6H2IQoBN2MNAczNDIJJPwsCIJMRgqi3D0AGXwkDXD8OgKEVDAWwDQEAzkUIA/GtBwAVBQlDlmsOABi3DIAKJQmCnP8MBAAAA9y00KDDDAAD7MVOmMMMAABm0TCwuwwAAhbf7riDDAAAcNjgtKMMAABm1KrAowwAA46/mKTDDAABGuOOvHcMAAMczMaUuwwAA8bD8MC/DAAAVNRywKMMAAJW1jDAowwAADjYAryjDAADxtSqxJ8MAANU2ihwmwwAALCjHLjDDAAAotuAwJsMAAAQAAABAVkBWAACySEBWQFYAAKpIQFZAVgAAm0hAVkBWAABhSEBWQFYAAFRIQFZAVgAATkhAVkBWAAB5SEBWQFYAABxIQFZAVgAAiUhAVkBWAABKSEBWQFYAAF9IQFZAVgAAJUhAVkBWAAAhSEBWQFYAAAtIQFZAVgAArkdAVkBWAAAJSEBWQFYAAABIBQAAAAAAAAAAAJEgAAAAAAAA3SAAAAAAAAAuIQAAAAAAAIYhAAAAAAAA4iEAAAAAAABDIgAAAAAAAKciAAAAAAAAGCMAAAAAAACPIwAAAAAAAAckAAAAAAAATSQAAAAAAACWJAAAAAAAAOckAAAAAAAAOCUAAAAAAACOJQAAAAAAAOolAAAAAAAAQyb/////',
        'source_label': 'Root',
        'source_counts': {'extern': 0, 'entry': 0, 'action': 0},
        'in_eof': True,
        'attributes': [],
    },
}


def is_builtin(ident: str) -> bool:
    return ident in _PRESETS


def get(ident: str):
    """取内置模板的预设 dict（深拷贝，调用方改坏了不影响下一次新增）。"""
    import copy
    preset = _PRESETS.get(ident)
    return copy.deepcopy(preset) if preset is not None else None


def items():
    """[(identifier, i18n key, 属性数), ...]，按下拉里该出现的顺序。

    属性数现算不写死——写死的话改了模板忘记同步，下拉里就会显示一个假数字。
    """
    return [
        (BUILTIN_3D, "preset.builtin_3d", len(_PRESETS[BUILTIN_3D]["attributes"])),
        (BUILTIN_2D, "preset.builtin_2d", len(_PRESETS[BUILTIN_2D]["attributes"])),
        (BUILTIN_ROOT, "preset.builtin_root", len(_PRESETS[BUILTIN_ROOT]["attributes"])),
    ]


def _payload_signature(preset: dict):
    """预设的属性负载指纹 [(type_hash, data_bytes), ...]，用于判定"是不是同一份东西"。

    只看属性负载，不比 display_name / props / source_label——那些字段在历次改名和
    schema 调整里变过，拿它们比会让明明相同的内容判成不同。3.0 改名前的旧 schema
    把属性存在 blocks 键下，一并认。
    """
    attrs = preset.get("attributes")
    if attrs is None:
        attrs = preset.get("blocks") or []
    return [(str(a.get("type_hash")), a.get("data_bytes")) for a in attrs]


def purge_superseded_copies(presets_root: str):
    """删掉用户预设目录里已被内置模板取代的旧副本，返回删掉的相对路径。

    **只在属性负载与内置模板逐字节一致时才删。** 用户照着改过一个字节的就留着——
    下拉里多一项只是碍眼，误删用户自己攒的预设是不可逆的数据损失。判定方式与
    presets.py::_is_stock_duplicate 同源（只比内容、不比名字和元数据）。

    读不出、删不掉（只读安装、权限不足）时静默跳过：清理本身不是必需功能，
    不该让它拦住插件启用。
    """
    removed = []
    for rel, ident in _SUPERSEDED:
        path = os.path.join(presets_root, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
        except (OSError, ValueError):
            continue
        if _payload_signature(on_disk) != _payload_signature(_PRESETS[ident]):
            continue  # 用户改过，留着
        try:
            os.remove(path)
            removed.append(rel)
        except OSError:
            pass
    return removed
