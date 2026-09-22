"""不可删除的基础 Entry 模板。

内置标识使用 builtin: 前缀，与文件预设标识区分；可选的扩展模板仍由预设目录提供。
"""

import json
import os


BUILTIN_3D = "builtin:basic_3d"
BUILTIN_2D = "builtin:basic_2d"
BUILTIN_ROOT = "builtin:root"

# 可能存有被内置模板替代副本的位置。键为相对预设根路径，值为对应内置模板。
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
    # Root 模板保留 raw 负载；add_ops 在支持时将其解析为可编辑子项，否则原样保留。
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
    """返回内置模板的深拷贝，防止调用方污染源模板。"""
    import copy
    preset = _PRESETS.get(ident)
    return copy.deepcopy(preset) if preset is not None else None


def items():
    """返回下拉顺序的 (标识, i18n 键, 属性数)；属性数由模板实时计算。"""
    return [
        (BUILTIN_3D, "preset.builtin_3d", len(_PRESETS[BUILTIN_3D]["attributes"])),
        (BUILTIN_2D, "preset.builtin_2d", len(_PRESETS[BUILTIN_2D]["attributes"])),
        (BUILTIN_ROOT, "preset.builtin_root", len(_PRESETS[BUILTIN_ROOT]["attributes"])),
    ]


def _payload_signature(preset: dict):
    """返回属性负载指纹，用于识别与内置模板相同的副本。

    显示名和元数据不参与比较；兼容使用 blocks 键的旧预设。
    """
    attrs = preset.get("attributes")
    if attrs is None:
        attrs = preset.get("blocks") or []
    return [(str(a.get("type_hash")), a.get("data_bytes")) for a in attrs]


def purge_superseded_copies(presets_root: str):
    """移除与内置模板负载完全相同的旧副本，并保留用户修改。

    清理失败不影响插件启用。
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
            continue
        try:
            os.remove(path)
            removed.append(rel)
        except OSError:
            pass
    return removed
