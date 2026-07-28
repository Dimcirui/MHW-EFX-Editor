# -*- coding: utf-8 -*-
"""
blender_efx/field_labels.py — 保留填充字段（0xCD 占位）只读表 + is_reserved_fill()。

⚠ 字段中文标签不在本模块：定长块标签是 `efx_format` 里 Field.label_zh，custom-codec 块
标签走 `efx_format/schema/labels.py` 的残余表，统一 accessor `field_label_zh(type_name,
field_name)`（panels._friendly_name 调用它）。本模块只剩「哪些字段是保留填充位、UI 关闭
编辑」这一职责。
"""

# ─────────────────────────────────────────────────────────────────────────────
# 保留填充字段（0xCD 未初始化占位）——UI 中关闭编辑（只读灰显）
#
# 判据：tools/scan_fill_fields.py 全语料(10163 文件)统计，字段最高字节(MSB)==0xCD
# 的比例 ≥99%（基本 100%）。这些是引擎从不写入的保留/填充位（spacer*/unkn*/CD1 等），
# 编辑无意义且易写坏；导出时未编辑字段走原始字节，byte-perfect 不受影响。
# 键 = (type_name, ori_name)。如需放行某字段，删对应行即可。
# 重新生成：python3 tools/scan_fill_fields.py --all --emit-set
# ⚠ 已手动排除 2 个名字像真实字段、可能有语义的项（--emit-set 会再次列出它们，
#   重生成后需重新删除）：PLSNOW.alpha_effect、STRAINRIBBON.color3_w。
#   （RIBBON.tailTiedToBone 曾在此列，2026-07-10 查明其 4B 恒为 0xCDCDCD00/01——只有
#   最低字节 0/1 是真实数据，已拆成 tailTiedToBone(B,真实)+spacer6(B×3,纯填充)。）
# ─────────────────────────────────────────────────────────────────────────────

RESERVED_FILL_FIELDS = frozenset({
    ('BLINK', 'unkn1_0'),
    ('CHECKPUREATTRIBUTE', 'unkn1'),
    ('EMITTERSHAPEMESH', 'unkn1_0'),
    ('EMITTERSHAPEMESH', 'unkn1_1'),
    ('EMITTERSHAPEMESH', 'unkn1_2'),
    ('FADEBYEMITTERANGLE', 'unkn'),
    ('FADEBYOCCLUSION', 'spacer0'),  # 原 unkn1，2026-07-29 复核：全语料恒 0xCDCDCDCD
    ('FAKEDOF', 'unkn2'),
    ('FAKEPLANE', 'unkn4'),
    ('HOMING', 'spacer'),
    ('LIGHTNING', 'spacer0'),
    ('LIGHTNING', 'spacer05_00'),
    ('LIGHTNING', 'spacer05_14'),
    ('LIGHTNING', 'unkn02'),
    ('LIGHTNING', 'unkn03'),
    ('LIGHTNING', 'unkn05_21'),
    ('LIGHTNING', 'unkn05_46'),
    ('LIGHTNING', 'unkn07_20'),
    ('LUMINANCEBLEED', 'unkn0'),
    ('MESH', 'CD1'),
    ('NOISE', 'spacer'),
    ('OTOMOSNOW', 'unkn1'),
    ('OTOMOSNOW', 'unkn4'),
    ('OTOMOSNOW', 'unkn6'),
    ('PARENTSNOW', 'unkn1'),
    ('PARENTSNOW', 'unkn3_1'),
    ('PARENTSNOW', 'unkn4_4'),
    ('PATHCHAIN', 'unkn1'),
    ('PLSNOW', 'spacer'),
    ('PLSNOW', 'unkn5'),
    ('PTTRIGGER', 'unkn1'),
    ('RAYCAST', 'spacer0'),
    ('RAYCAST', 'spacer1'),
    ('RAYCAST', 'spacer2'),
    ('RAYCAST', 'spacer3'),
    ('RIBBON', 'spacer0'),
    ('RIBBON', 'spacer1'),
    ('RIBBON', 'spacer2'),
    ('RIBBON', 'spacer3'),
    ('RIBBON', 'spacer4'),
    ('RIBBON', 'spacer5'),
    ('RIBBON', 'spacer6'),
    ('RIBBON', 'spacer7'),
    ('RIBBON', 'spacer8'),
    ('RIBBON', 'spacer9'),
    ('RIBBON', 'unkn24'),
    # 原 ib_junk[32] 拆分出的 13 字节纯 0xCD 填充段（2026-07-21，全语料 15015 块核对）。
    ('RIBBON', 'ribbon_flow_reserved'),
    ('RIBBONBLADE', 'spacer0'),
    ('RIBBONBLADE', 'spacer1'),
    ('RIBBONBLADE', 'spacer2'),
    ('RIBBONBLADE', 'spacer3'),
    # EPVColorSlot 嵌套字段（head.*/tailEnd.* 全语料 62/62 恒为 0xCD 填充，2026-07-10 确认）
    ('RIBBONBLADE', 'head.spacer4'),
    ('RIBBONBLADE', 'head.spacer5'),
    # head.unkn18_1 曾按恒为 0xCD 排除；tailEnd 侧同名字段是真实数据(0/1 布尔)，鉴于
    # flowmap jitter 的先例（语料恒 0 但实机确认有效），改为可编辑供实机测试（2026-07-11）。
    ('RIBBONBLADE', 'tailEnd.spacer4'),
    ('RIBBONBLADE', 'tailEnd.spacer5'),
    ('SCREENSPACECOLLISION', 'spacer'),
    ('SHADERSETTINGS', 'spacer'),
    ('SHOVEL', 'spacer'),
    ('SPAWNBYANGLE', 'unkn1'),
    ('SPAWNBYOCCLUSION', 'unkn1'),
    ('STRAINRIBBON', 'spacer00'),
    ('STRAINRIBBON', 'spacer01'),
    ('STRAINRIBBON', 'spacer02'),
    ('STRAINRIBBON', 'spacer03'),
    ('TONEMAPFILTER', 'unkn1'),
    ('TUBELIGHT', 'unkn3_2'),
    ('TUBELIGHT', 'unkn5_1'),  # 恒 0xCDCDCDCD 未初始化标记（2026-07-01 实机测试确认，schema 拆分后新增）
    ('UVSEQUENCE', 'loopingPad'),  # loopingEnum byte2-3，实测恒 0 的保留填充

    # ── "section_length" 类结构性长度标记（非 0xCD 填充，2026-07-11 全语料统计确认）───
    # 这批字段是各类型 schema 的第 2 个 4B 字段，全语料 100% 恒等于「该 attribute 总字节数
    # - 8」（即该字段自身结束位置到块尾的剩余字节数）——是引擎自描述的剩余长度标记，不是
    # 可调参数，改动会破坏解析。判据/复现见 2026-07-11 对 44 个候选类型的系统扫描。
    # ⚠ SHADERSETTINGS.unkn1（99.9% 恒 104，但按同公式应为 108，差 4）未确认属于同一机制，
    # 结构相同的 RAYCAST/HOMING/SCREENSPACECOLLISION/SHOVEL 均按标准公式吻合，故未列入。
    # 2026-07-23：本批全部 19 个类型的字段 0（原 unkn0_0/unknown/unkn00/unkn0/NULL 等）也
    # 统一核实为"类型标记"形态（小基数离散分布，见 docs/ATTRIBUTE_BEHAVIOR_NOTES.md），
    # 改名 typeFlag；字段 1（本节）改名 section_length（下面 key 已同步）。
    ('NOISE', 'section_length'),
    ('RIBBON', 'section_length'),  # 2026-07-11：变长块(custom codec)里恒 352=固定核心 360-8，只管固定部分不含尾部变长路径
    ('DUMMY', 'section_length'),
    ('BLINK', 'section_length'),
    ('FADEBYEMITTERANGLE', 'section_length'),
    ('RAYCAST', 'section_length'),
    ('HOMING', 'section_length'),
    ('SCREENSPACECOLLISION', 'section_length'),
    ('SHOVEL', 'section_length'),
    ('PATHCHAIN', 'section_length'),
    ('PTTRIGGER', 'section_length'),
    ('SPAWNBYANGLE', 'section_length'),
    ('CHECKPUREATTRIBUTE', 'section_length'),
    ('SPAWNBYOCCLUSION', 'section_length'),
    ('FADEBYOCCLUSION', 'section_length'),  # 原 unknFixed0_1，2026-07-29 复核：全语料恒 16=24B-8
    ('PARENTSNOW', 'section_length'),
    ('OTOMOSNOW', 'section_length'),
    ('FAKEPLANE', 'section_length'),
    ('REPEATAREA', 'section_length'),
    ('FAKEDOF', 'section_length'),  # 原 unkn1，跟 RepeatArea 同一机制，之前漏归类，2026-07 补上
})


def is_reserved_fill(type_name, ori_name) -> bool:
    """该字段是否为保留填充位（UI 关闭编辑）。"""
    return (type_name, ori_name) in RESERVED_FILL_FIELDS
