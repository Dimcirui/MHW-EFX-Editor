"""
blender_efx/fields.py  —  L1.1b+c + L1.3：通用块字段模型 + 脏标记 + 逐字段无损性 + 路径编辑 + 颜色色轮

设计原则（参照 CLAUDE.md）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集：PropertyGroup / CollectionProperty / PointerProperty /
    FloatVectorProperty / IntVectorProperty / BoolProperty / StringProperty /
    EnumProperty / IntProperty
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层
  - byte-perfect：拿不准的结构全部 is_editable=False + base64

无损性策略（L1.1b 新增）：
  每个 EFXFieldItem 存储：
    orig_b64  : StringProperty — 该字段原始字节切片的 base64（导入时填入）
    edited    : BoolProperty  — 用户实际编辑过该字段时置 True
    read_only : BoolProperty  — 原始字节不能被值槽精确往返的字段（NaN/inf 等）

  导出重建 data_bytes 时（rebuild_data_bytes）：
    - edited=False 或 read_only=True → 直接用 b64decode(orig_b64)（bit 精确）
    - edited=True 且 read_only=False → 用字段 spec 重新 pack 新值

  健壮性闸门（roundtrip gate）：
    dict_to_items 完成后，立即用"全未编辑"路径重建 data_bytes，
    与原始 data_bytes 断言相等；不等则该块退回 is_editable=False。

数据类型映射（EFXFieldItem.data_type → 值槽）：
  FLOAT    → float_value   (单精度浮点)
  INT      → int_value     (int32 / int16 / int8)
  UINT     → uint_str      (uint32/uint64 十进制字符串，避免 Blender C int 溢出)
  BOOL     → bool_value
  FLOAT2   → float2_value  (FloatVectorProperty size=2)
  FLOAT3   → float3_value  (FloatVectorProperty size=3)
  FLOAT4   → float4_value  (FloatVectorProperty size=4)
  FLOAT6   → float6_value  (FloatVectorProperty size=6)
  COLOUR   → colour_value  (4 × ubyte，存为 IntVectorProperty size=4 [0,255])
  COLOR_RGBA → color_rgba_value  (L1.3：4 × ubyte r,g,b,a → FloatVectorProperty size=4 subtype='COLOR' [0,1])
               用于 spec='colour' 和 spec=('XYZ',2)（第4字节为 alpha，实测：255 主导、偶 16/50、从不为 0）
  COLOR_RGB  → color_rgb_value   (保留值槽，当前无 spec 映射到此类型；旧数据兼容)
  INT2     → int2_value    (IntVectorProperty size=2)
  INT3     → int3_value    (IntVectorProperty size=3)
  INT4     → int4_value    (IntVectorProperty size=4)
  INT10    → int10_str     (StringProperty，逗号分隔十进制)
  INT16    → int16_str     (StringProperty，逗号分隔十进制，for ('f',16) or ('i',16))
  FLOAT2_STR  → float2_str    (StringProperty，逗号分隔，用于 size=2 float array)
  FLOAT3_STR  → float3_str    (用于 ('f',3) float 数组)
  FLOAT5_STR  → float5_str    (用于 ('f',5) float 数组)
  FLOAT8_STR  → float8_str    (用于 ('f',8) float 数组)
  FLOAT16_STR → float16_str   (用于 ('f',16) float 数组)
  INT_PAIR    → int_pair_str  (2个int，逗号分隔，用于 ('i',2) 等)
  BYTE1    → byte1_value   (单个 uint8，用 IntProperty [0,255])
  SHORT1   → short1_value  (单个 int16)
  OPAQUE   → opaque_str    (base64，用于不可表示的复杂结构)
  STRING   → string_value (路径字符串，用于 custom-codec 含路径类型的路径字段)

L1.3 颜色色轮策略（byte-perfect）：
  COLOR_RGBA（spec='colour' 或 spec=('XYZ',2)）：
    导入：[r, g, b, a] (0-255) → [r/255, g/255, b/255, a/255] (0-1)
    重建：clamp(round(c*255), 0, 255) × 4（全4通道均从 picker 取值）
    往返检测：ubyte → float → ubyte 精确（ubyte 不存在 NaN/精度问题，100% 通过）
    注：('XYZ',2) 第4字节是 alpha（实测：1030 个字段中 255×1017、50×10、16×3、0×0），
        BT 模板标注的 "NULL" 是误名，实为透明度，用户可在色块中编辑。
        未编辑时 orig_b64 恒等还原（bit 精确），不受影响。
"""

import base64
import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    IntProperty,
    FloatProperty,
    FloatVectorProperty,
    IntVectorProperty,
    EnumProperty,
    CollectionProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup

# ─────────────────────────────────────────────────────────────────────────────
# 加载守卫：导入时防止 update 回调置脏
# ─────────────────────────────────────────────────────────────────────────────

_LOADING: bool = False
"""
全局加载守卫。
在 io_tree.import_efx_tree 的块字段填充阶段置 True，
填充完成后（导入末尾）重置为 False。
所有 update 回调检查此标志，加载期间直接返回不置脏。
"""


def _mark_block_dirty(self, context):
    """
    通用脏标记回调：编辑任何字段值 → 把所属 EFXBlockProps 的 efx_dirty 置 True，
    同时把该字段项的 edited 置 True（逐字段无损性：仅编辑过的字段走重新 pack 路径）。
    加载期间（_LOADING=True）跳过，避免填充字段时误置脏。
    """
    if _LOADING:
        return
    # self 是 EFXFieldItem 实例；id_data 是挂该 CollectionProperty 的 Object
    try:
        # 标记该字段已被编辑（rebuild_data_bytes 会用新值 pack 此字段）
        self.edited = True
        obj = self.id_data
        if obj is not None and hasattr(obj, "efx_block"):
            obj.efx_block.efx_dirty = True
            # TRANSFORM3D 的 translate/rotate/resize 编辑 → 实时同步到 body empty（单向、纯可视）
            if self.ori_name in ("translate", "rotate", "resize"):
                try:
                    from ..efx_format.hashes import TRANSFORM3D
                    if int(obj.efx_block.type_hash_str) == TRANSFORM3D:
                        from . import transform_sync
                        # 0.2.15 重构后入口是 apply_body_transform(body, armature)：
                        # 取该块的父 body + 当前骨架（含 bone_lim 骨骼基准），而非旧的 block 签名。
                        body = obj.parent
                        if body is not None and body.get("~TYPE") == "EFX_BODY":
                            scene = getattr(context, "scene", None) or bpy.context.scene
                            armature = getattr(scene, "efx_armature", None) if scene else None
                            transform_sync.apply_body_transform(body, armature)
                except Exception:
                    pass
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 数据类型枚举条目
# ─────────────────────────────────────────────────────────────────────────────

_DATA_TYPE_ITEMS = [
    # 标量
    ("FLOAT",       "Float",        "单精度浮点（float32）"),
    ("INT",         "Int",          "有符号整数（int32/int16/int8）"),
    ("UINT",        "Uint",         "无符号整数（uint32/uint64，字符串存储）"),
    ("BOOL",        "Bool",         "布尔值"),
    ("BYTE1",       "Byte",         "单个 uint8 [0,255]"),
    ("SHORT1",      "Short",        "单个 int16"),
    # 定长向量（直接用 FloatVectorProperty / IntVectorProperty）
    ("FLOAT2",      "Float[2]",     "2 个浮点"),
    ("FLOAT3",      "Float[3]",     "3 个浮点"),
    ("FLOAT4",      "Float[4]",     "4 个浮点"),
    ("FLOAT6",      "Float[6]",     "6 个浮点（XYZ type 0）"),
    ("COLOUR",      "Colour",       "4 个 ubyte [0,255]（colour）"),
    ("COLOR_RGBA",  "Color RGBA",   "L1.3 色轮 RGBA：4 ubyte r,g,b,a → FloatVectorProperty subtype=COLOR size=4（用于 colour 和 XYZ type 2；XYZ2 第4字节为 alpha）"),
    ("COLOR_RGB",   "Color RGB",    "保留值槽（当前无 spec 映射到此；旧数据兼容）"),
    ("INT2",        "Int[2]",       "2 个整数"),
    ("INT3",        "Int[3]",       "3 个整数（XYZ type 1）"),
    ("INT4",        "Int[4]",       "4 个整数"),
    # 较大数组：用逗号分隔字符串存储（避免 Blender PropertyGroup 大向量限制）
    ("FLOAT2_STR",  "Float[2]str",  "2 个浮点（字符串形式）"),
    ("FLOAT3_STR",  "Float[3]str",  "3 个浮点（字符串形式）"),
    ("FLOAT5_STR",  "Float[5]str",  "5 个浮点（字符串形式）"),
    ("FLOAT8_STR",  "Float[8]str",  "8 个浮点（字符串形式）"),
    ("FLOAT16_STR", "Float[16]str", "16 个浮点（字符串形式）"),
    ("INT_PAIR",    "Int[2]str",    "2 个整数（字符串形式）"),
    ("INT10_STR",   "Int[10]str",   "10 个整数（字符串形式）"),
    ("INT16_STR",   "Int[16]str",   "16 个整数（字符串形式）"),
    # 通用数组（任意 count）
    ("ARRAY_STR",   "Array str",    "任意 count 的 float/int 数组（逗号分隔字符串）"),
    # 不可表示
    ("OPAQUE",      "Opaque",       "不支持的复杂结构（base64 原始）"),
    # 路径字符串（custom-codec 含路径类型专用）
    ("STRING",      "Path/String",  "路径字符串（custom-codec 含路径块的路径字段）"),
]


# ─────────────────────────────────────────────────────────────────────────────
# EFXFieldItem  —  通用字段项 PropertyGroup
# ─────────────────────────────────────────────────────────────────────────────

class EFXFieldItem(PropertyGroup):
    """
    通用字段项，代表 AttrBlock decode() 字典中的一个字段。

    ori_name  ：schema 中的字段名（权威，用于重建 dict）。
    data_type ：字段数据类型枚举，决定读取哪个值槽。
    各值槽   ：按 data_type 只有一个槽有效数据。
    每个值槽均挂 update=_mark_block_dirty 以在编辑时置脏。
    """

    ori_name: StringProperty(
        name="Field Name",
        description="Original schema field name (read-only)",
    )

    hint_name: StringProperty(
        name="Hint Name",
        description="Optional semantic hint for display (used by PTBEHAVIOR params)",
        default="",
    )

    data_type: EnumProperty(
        name="Data Type",
        items=_DATA_TYPE_ITEMS,
    )

    # ── L1.1b：逐字段无损性元数据 ────────────────────────────────────────────

    orig_b64: StringProperty(
        name="Original Bytes (base64)",
        description=(
            "base64 of the byte slice for this field in the original data_bytes. "
            "When unedited, export uses these bytes directly (bit-exact, avoids float NaN/precision issues)."
        ),
        default="",
    )

    edited: BoolProperty(
        name="Edited",
        description=(
            "True = user modified this field value, export re-packs with the new value; "
            "False = export uses the orig_b64 original bytes (identity restore)."
        ),
        default=False,
    )

    read_only: BoolProperty(
        name="Read-only",
        description=(
            "True = this field's original bytes cannot round-trip exactly through the value slot (e.g. floats with NaN/inf/sentinel bits); "
            "export always uses orig_b64, UI disables editing."
        ),
        default=False,
    )

    # ── 标量值槽 ─────────────────────────────────────────────────────────────

    float_value: FloatProperty(
        name="",
        description="float32 value",
        precision=6,
        update=_mark_block_dirty,
    )

    int_value: IntProperty(
        name="",
        description="int32/int16/int8 value",
        update=_mark_block_dirty,
    )

    # uint32/uint64 存字符串，避免 Blender C int 32 位溢出
    uint_str: StringProperty(
        name="",
        description="uint value (decimal string, avoids overflow)",
        update=_mark_block_dirty,
    )

    bool_value: BoolProperty(
        name="",
        description="Boolean value",
        default=False,
        update=_mark_block_dirty,
    )

    byte1_value: IntProperty(
        name="",
        description="uint8 value [0, 255]",
        min=0, max=255,
        update=_mark_block_dirty,
    )

    short1_value: IntProperty(
        name="",
        description="int16 value",
        min=-32768, max=32767,
        update=_mark_block_dirty,
    )

    # ── 向量值槽（FloatVectorProperty）───────────────────────────────────────

    float2_value: FloatVectorProperty(
        name="",
        size=2,
        precision=6,
        update=_mark_block_dirty,
    )

    float3_value: FloatVectorProperty(
        name="",
        size=3,
        precision=6,
        update=_mark_block_dirty,
    )

    float4_value: FloatVectorProperty(
        name="",
        size=4,
        precision=6,
        update=_mark_block_dirty,
    )

    float6_value: FloatVectorProperty(
        name="",
        size=6,
        precision=6,
        update=_mark_block_dirty,
    )

    # ── 整数向量值槽 ─────────────────────────────────────────────────────────

    # colour：4 个 ubyte [0,255]（r,g,b,a）
    colour_value: IntVectorProperty(
        name="",
        size=4,
        min=0, max=255,
        update=_mark_block_dirty,
    )

    # ── L1.3 颜色色轮值槽 ─────────────────────────────────────────────────────

    # COLOR_RGBA：spec='colour' 或 spec=('XYZ',2)，4 ubyte r,g,b,a → 0-1 浮点（含 alpha）
    # ('XYZ',2) 第4字节实为 alpha（实测：255×1017、50×10、16×3、0×0，绝非 pad）
    # subtype='COLOR' → Blender 自动显示色块，点击打开色轮/滑块（含 Alpha 面板）
    color_rgba_value: FloatVectorProperty(
        name="",
        description="Colour RGBA (ubyte 0-255 ↔ float 0-1, subtype=COLOR; used for colour and XYZ type 2)",
        subtype='COLOR',
        size=4,
        min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        update=_mark_block_dirty,
    )

    # COLOR_RGB：保留值槽（当前无 spec 映射到此 dtype；旧数据兼容）
    # ('XYZ',2) 已改为映射到 COLOR_RGBA（第4字节为 alpha，非 pad）
    color_rgb_value: FloatVectorProperty(
        name="",
        description="Colour RGB (reserved value slot, currently no spec maps to this dtype)",
        subtype='COLOR',
        size=3,
        min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0),
        update=_mark_block_dirty,
    )

    int2_value: IntVectorProperty(
        name="",
        size=2,
        update=_mark_block_dirty,
    )

    int3_value: IntVectorProperty(
        name="",
        size=3,
        update=_mark_block_dirty,
    )

    int4_value: IntVectorProperty(
        name="",
        size=4,
        update=_mark_block_dirty,
    )

    # ── 较大数组：逗号分隔字符串 ──────────────────────────────────────────────
    # 这些用于 ('f', N) / ('i', N) 等较大定长数组。
    # 对 N>6 的 float 数组和 N>4 的 int 数组统一用逗号字符串存储，
    # 以避免 FloatVectorProperty/IntVectorProperty size 参数的兼容性问题。
    # 同样用于任意不规则 count（如 11、7 等）的一般情况。

    float2_str: StringProperty(
        name="",
        description="2 floats, comma-separated",
        update=_mark_block_dirty,
    )

    float3_str: StringProperty(
        name="",
        description="3 floats, comma-separated",
        update=_mark_block_dirty,
    )

    float5_str: StringProperty(
        name="",
        description="5 floats, comma-separated",
        update=_mark_block_dirty,
    )

    float8_str: StringProperty(
        name="",
        description="8 floats, comma-separated",
        update=_mark_block_dirty,
    )

    float16_str: StringProperty(
        name="",
        description="16 floats, comma-separated",
        update=_mark_block_dirty,
    )

    int_pair_str: StringProperty(
        name="",
        description="2 ints, comma-separated",
        update=_mark_block_dirty,
    )

    int10_str: StringProperty(
        name="",
        description="10 ints, comma-separated",
        update=_mark_block_dirty,
    )

    int16_str: StringProperty(
        name="",
        description="16 ints, comma-separated",
        update=_mark_block_dirty,
    )

    # ── 通用数组字符串（ARRAY_STR）────────────────────────────────────────────
    # 用于任意 count 的浮点/整数数组（不在上面专用槽范围内的情况）。
    # 格式：逗号分隔十进制/repr字符串，不带空格。
    array_str: StringProperty(
        name="",
        description="Generic array (comma-separated), for float/int arrays of any count",
        update=_mark_block_dirty,
    )

    # ── 不可表示字段（base64 opaque）─────────────────────────────────────────

    opaque_str: StringProperty(
        name="",
        description="Unsupported complex structure (base64 raw bytes)",
        update=_mark_block_dirty,
    )

    # ── 路径字符串槽（custom-codec 含路径类型，L1.1b）──────────────────────────
    # 用于 UVSEQUENCE / BILLBOARD3D / MESH / RIBBON / PLANE / RIBBONBLADE /
    #        TURBULENCE / LIGHTNING / RGBWATER 的路径字段项。
    # data_type == STRING 时，读/写此槽。
    string_value: StringProperty(
        name="",
        description="Path string (in-game resource path, e.g. .dds/.efx/.mod3 paths)",
        update=_mark_block_dirty,
    )


# ─────────────────────────────────────────────────────────────────────────────
# EFXBlockProps  —  挂到 Object 上的块属性 PropertyGroup
# ─────────────────────────────────────────────────────────────────────────────

class EFXBlockProps(PropertyGroup):
    """
    挂到 bpy.types.Object.efx_block 上（EFX_BLOCK Empty）。
    存储 AttrBlock 的字段模型、脏标记和原始字节安全网。
    """

    type_hash_str: StringProperty(
        name="Type Hash",
        description="AttrBlock type hash (decimal string, avoids uint32 overflow)",
    )

    efx_dirty: BoolProperty(
        name="Modified",
        description="Set True after a field is edited by the user; re-encode on export",
        default=False,
    )

    raw_b64: StringProperty(
        name="Original Bytes (base64)",
        description="base64 backup of data_bytes; used to restore on export if dirty=False or is_editable=False",
    )

    field_items: CollectionProperty(
        type=EFXFieldItem,
        name="Field List",
    )

    field_index: IntProperty(
        name="Field Index",
        default=0,
    )

    is_editable: BoolProperty(
        name="Editable",
        description=(
            "True = expanded into field_items (flat schema type); "
            "False = base64 opaque only (_custom / unknown / nested structure)"
        ),
        default=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Flattener：spec → data_type 映射
# ─────────────────────────────────────────────────────────────────────────────

def _spec_to_dtype(spec) -> str:
    """
    把 schema 中的 spec 映射到 EFXFieldItem.data_type 枚举字符串。
    返回 None 表示无法表示（触发整块 is_editable=False）。

    支持的映射：
      'f'           → FLOAT
      'i','h','b'   → INT    (有符号标量)
      'I','H','B'   → 对应槽  (I→UINT, H→INT, B→BYTE1)
      'q','Q'       → UINT   (int64/uint64 均存字符串)
      'colour'      → COLOUR (4 ubyte)
      ('XYZ', 0)    → FLOAT6  (6 floats)
      ('XYZ', 1)    → INT3    (3 ints)
      ('XYZ', 2)    → COLOR_RGBA  (4 ubytes r,g,b,a；第4字节为 alpha)
      ('XYZ', 3)    → FLOAT3  (3 floats)
      ('f', 2)      → FLOAT2
      ('f', 3)      → FLOAT3
      ('f', 4)      → FLOAT4
      ('f', 5)      → FLOAT5_STR
      ('f', 8)      → FLOAT8_STR
      ('f', 16)     → FLOAT16_STR
      ('i', 2)      → INT_PAIR
      ('i', 3)      → INT3
      ('i', 10)     → INT10_STR
      ('i', N)      → ARRAY_STR（其他 N，如 7）
      ('I', 2) etc  → INT_PAIR (无符号小数组也当 int pair 存)
      ('B', 2)      → INT_PAIR (bytes pair)
      ('h', 2)      → INT_PAIR
      其余无法表示的 spec（XYZ[]、colour[]、path…）→ None（强制 is_editable=False）
    """
    if isinstance(spec, str):
        if spec == 'f':
            return "FLOAT"
        if spec in ('i', 'h', 'b'):
            return "INT"
        if spec == 'B':
            return "BYTE1"
        if spec == 'H':
            return "INT"   # uint16 fit in int32
        if spec in ('I', 'q', 'Q'):
            return "UINT"  # 存字符串
        if spec == 'colour':
            return "COLOR_RGBA"  # L1.3：显示色轮（带 alpha）
        if spec == 'EPVColorSlot':
            return None    # 复杂 dict → opaque
        return None

    if isinstance(spec, tuple):
        tag = spec[0]

        # XYZ 变体
        if tag == 'XYZ':
            xyz_type = spec[1]
            if xyz_type == 0:
                return "FLOAT6"
            if xyz_type == 1:
                return "INT3"
            if xyz_type == 2:
                return "COLOR_RGBA"  # L1.3：4 ubyte r,g,b,a → 色轮 RGBA（第4字节是 alpha，非 pad）
            if xyz_type == 3:
                return "FLOAT3"
            return None

        # XYZ[] / colour[] / EPVColorSlot[] → 嵌套列表/dict，强制 opaque
        if tag in ('XYZ[]', 'colour[]', 'EPVColorSlot[]'):
            return None

        # path → bytes，可用 base64 opaque，但整块判断
        if tag == 'path':
            return None

        # 固定数组 ('scalar', count)
        if len(spec) == 2 and isinstance(spec[1], int):
            scalar, count = spec
            if scalar == 'f':
                if count == 2:
                    return "FLOAT2"
                if count == 3:
                    return "FLOAT3"
                if count == 4:
                    return "FLOAT4"
                if count == 5:
                    return "FLOAT5_STR"
                if count == 8:
                    return "FLOAT8_STR"
                if count == 16:
                    return "FLOAT16_STR"
                # 其他 float 数组（任意 count）→ 通用 ARRAY_STR
                return "ARRAY_STR"
            if scalar in ('i', 'I', 'h', 'H', 'b', 'B'):
                if count == 2:
                    return "INT_PAIR"
                if count == 3:
                    return "INT3"
                if count == 4:
                    return "INT4"
                if count == 10:
                    return "INT10_STR"
                if count == 16:
                    return "INT16_STR"
                # 其他 int 数组（任意 count）→ 通用 ARRAY_STR
                return "ARRAY_STR"
        return None

    return None


def _check_schema_all_flat(schema: list) -> bool:
    """
    检查 schema 中每个 spec 都能映射到支持的 data_type（非 None）。
    若有任何字段返回 None，整块应标记 is_editable=False。
    """
    for _name, spec in schema:
        if _spec_to_dtype(spec) is None:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# _spec_byte_size  —  spec → 字节数（与 structs._schema_size 逻辑一致）
# ─────────────────────────────────────────────────────────────────────────────

_SCALAR_BYTE_SIZE = {
    'i': 4, 'I': 4, 'f': 4,
    'h': 2, 'H': 2,
    'b': 1, 'B': 1,
    'q': 8, 'Q': 8,
}

_XYZ_BYTE_SIZE = {0: 24, 1: 12, 2: 4, 3: 12}


def _spec_byte_size(spec) -> int:
    """
    返回 spec 在 data_bytes 中占用的字节数。
    对不支持的 spec（动态长度 / 复杂结构）返回 None。
    与 structs._schema_size 的逻辑保持一致，但仅处理已知的 flat spec。
    """
    if isinstance(spec, str):
        if spec in _SCALAR_BYTE_SIZE:
            return _SCALAR_BYTE_SIZE[spec]
        if spec == 'colour':
            return 4
        # EPVColorSlot / 其它复杂 spec → None（调用者触发 is_editable=False）
        return None

    if isinstance(spec, tuple):
        tag = spec[0]
        if tag == 'XYZ':
            xyz_type = spec[1]
            return _XYZ_BYTE_SIZE.get(xyz_type)
        if len(spec) == 2 and isinstance(spec[1], int):
            scalar, count = spec
            if scalar in _SCALAR_BYTE_SIZE:
                return _SCALAR_BYTE_SIZE[scalar] * count
        return None

    return None


def _check_field_roundtrips(orig_slice: bytes, spec, val) -> bool:
    """
    检测该字段的原始字节能否被值槽精确往返：
      orig_slice → unpack → [UI 值槽编码] → decode → pack == orig_slice ?

    分两步检测：
      1. structs.pack(spec, val) == orig_slice（C 层往返，检测 NaN bit 模式等）
      2. 对 float 标量/数组字段，额外检测通过字符串表示的往返
         （repr(v) → float(s) → pack，因为 FLOAT/FLOAT*_STR 槽用 str 存储）

    若任一步失败返回 False（只读）。对任何异常保守返回 False。
    """
    try:
        from ..efx_format.structs import pack as structs_pack

        # ── 步骤1：C 层往返 ─────────────────────────────────────────────────
        repacked = structs_pack([("_", spec)], {"_": val})
        if repacked != orig_slice:
            return False

        # ── 步骤2：float 字段额外检测字符串往返（覆盖 NaN repr 问题）──────
        # 仅对包含 float 的 spec 做额外检测
        _needs_str_check = False
        if spec == 'f':
            _needs_str_check = True
        elif isinstance(spec, tuple) and len(spec) == 2:
            scalar, _count = spec
            if scalar == 'f':
                _needs_str_check = True
        elif isinstance(spec, tuple) and spec[0] == 'XYZ' and spec[1] in (0, 3):
            _needs_str_check = True

        if _needs_str_check:
            # 模拟 _float_to_str → float() 路径
            import struct as _struct
            if spec == 'f':
                floats_in = [val] if not isinstance(val, list) else val
            elif isinstance(spec, tuple) and len(spec) == 2 and isinstance(val, list):
                floats_in = val
            elif isinstance(spec, tuple) and spec[0] == 'XYZ':
                floats_in = val
            else:
                floats_in = []

            if floats_in:
                try:
                    floats_out = [float(repr(float(v))) for v in floats_in]
                    # 对 float 数组 pack 检测
                    count = len(floats_out)
                    repacked_str = _struct.pack(f'<{count}f', *floats_out)
                    # 提取对应原始字节（按 count × 4）
                    orig_floats_bytes = orig_slice[:count * 4]
                    if repacked_str != orig_floats_bytes:
                        return False
                except Exception:
                    return False

        return True

    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# dict_to_items  —  values dict → EFXFieldItem collection
# ─────────────────────────────────────────────────────────────────────────────

def dict_to_items(
    values: dict,
    schema: list,
    block_props,
    data_bytes: bytes = None,
) -> bool:
    """
    把 AttrBlock.decode() 返回的 values dict 填入 block_props.field_items。

    参数
    ----
    values     : dict  — AttrBlock.decode() 的返回值
    schema     : list  — 对应的 schema（用于确定 spec 类型，按顺序填充）
    block_props: EFXBlockProps  — 目标 PropertyGroup
    data_bytes : bytes | None  — 原始 data_bytes；若提供则按字节偏移填充
                                  每个 item.orig_b64 并判定 read_only。

    返回
    ----
    bool — True=成功（全部字段均可表示）；False=失败（含不可表示字段）

    注意：调用者应在调用前后管理 _LOADING 守卫，并在成功后清零 efx_dirty。
    """
    block_props.field_items.clear()

    byte_offset = 0  # 当前在 data_bytes 中的位置

    for name, spec in schema:
        dtype = _spec_to_dtype(spec)
        if dtype is None:
            # 遇到不可表示字段 → 失败，清理已加入的 item
            block_props.field_items.clear()
            return False

        if name not in values:
            block_props.field_items.clear()
            return False

        val = values[name]
        item = block_props.field_items.add()
        item.ori_name = name
        item.data_type = dtype
        item.edited = False

        # ── L1.1b：记录原始字节切片 + 判定 read_only ────────────────────────
        if data_bytes is not None:
            field_size = _spec_byte_size(spec)
            if field_size is not None:
                orig_slice = data_bytes[byte_offset: byte_offset + field_size]
                item.orig_b64 = base64.b64encode(orig_slice).decode("ascii")
                # 判定是否能往返：若不能则只读
                item.read_only = not _check_field_roundtrips(orig_slice, spec, val)
                byte_offset += field_size
            else:
                # spec 大小不确定（理论上已被 _check_schema_all_flat 过滤，防御性处理）
                item.orig_b64 = ""
                item.read_only = True
        else:
            item.orig_b64 = ""
            item.read_only = False

        # 按 dtype 写入对应值槽
        try:
            _write_item_value(item, dtype, val, spec)
        except Exception:
            block_props.field_items.clear()
            return False

    return True


def _write_item_value(item: EFXFieldItem, dtype: str, val, spec) -> None:
    """把 val 写入 item 的对应值槽（按 dtype）。"""
    if dtype == "FLOAT":
        item.float_value = float(val)

    elif dtype == "INT":
        item.int_value = int(val)

    elif dtype == "UINT":
        item.uint_str = str(int(val))

    elif dtype == "BOOL":
        item.bool_value = bool(val)

    elif dtype == "BYTE1":
        item.byte1_value = int(val) & 0xFF

    elif dtype == "SHORT1":
        item.short1_value = int(val)

    elif dtype == "FLOAT2":
        v = list(val)
        item.float2_value = (float(v[0]), float(v[1]))

    elif dtype == "FLOAT3":
        v = list(val)
        item.float3_value = (float(v[0]), float(v[1]), float(v[2]))

    elif dtype == "FLOAT4":
        v = list(val)
        item.float4_value = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))

    elif dtype == "FLOAT6":
        v = list(val)
        item.float6_value = tuple(float(x) for x in v[:6])

    elif dtype == "COLOUR":
        v = list(val)
        item.colour_value = (int(v[0]), int(v[1]), int(v[2]), int(v[3]))

    elif dtype == "COLOR_RGBA":
        # L1.3：spec='colour' 或 spec=('XYZ',2)，[r,g,b,a] ubyte → float [0,1]
        # ('XYZ',2) 第4字节是 alpha（实测：255 主导、偶 16/50、从不为 0），非 pad
        v = list(val)
        item.color_rgba_value = (
            _ubyte_to_float(int(v[0])),
            _ubyte_to_float(int(v[1])),
            _ubyte_to_float(int(v[2])),
            _ubyte_to_float(int(v[3])),
        )

    elif dtype == "INT2":
        v = list(val)
        item.int2_value = (int(v[0]), int(v[1]))

    elif dtype == "INT3":
        v = list(val)
        item.int3_value = (int(v[0]), int(v[1]), int(v[2]))

    elif dtype == "INT4":
        v = list(val)
        item.int4_value = (int(v[0]), int(v[1]), int(v[2]), int(v[3]))

    elif dtype == "INT_PAIR":
        v = list(val)
        item.int_pair_str = ",".join(str(int(x)) for x in v)

    elif dtype == "FLOAT2_STR":
        v = list(val)
        item.float2_str = ",".join(_float_to_str(x) for x in v)

    elif dtype == "FLOAT3_STR":
        v = list(val)
        item.float3_str = ",".join(_float_to_str(x) for x in v)

    elif dtype == "FLOAT5_STR":
        v = list(val)
        item.float5_str = ",".join(_float_to_str(x) for x in v)

    elif dtype == "FLOAT8_STR":
        v = list(val)
        item.float8_str = ",".join(_float_to_str(x) for x in v)

    elif dtype == "FLOAT16_STR":
        v = list(val)
        item.float16_str = ",".join(_float_to_str(x) for x in v)

    elif dtype == "INT10_STR":
        v = list(val)
        item.int10_str = ",".join(str(int(x)) for x in v)

    elif dtype == "INT16_STR":
        v = list(val)
        item.int16_str = ",".join(str(int(x)) for x in v)

    elif dtype == "ARRAY_STR":
        # 通用数组：浮点用 repr 保精度，整数用 str
        v = list(val)
        if v and isinstance(v[0], float):
            item.array_str = ",".join(_float_to_str(x) for x in v)
        else:
            item.array_str = ",".join(str(int(x)) for x in v)

    elif dtype == "OPAQUE":
        if isinstance(val, (bytes, bytearray)):
            item.opaque_str = base64.b64encode(val).decode("ascii")
        else:
            item.opaque_str = str(val)


def _float_to_str(v) -> str:
    """把浮点转为可精确还原的字符串（用 repr 保证往返精度）。"""
    # struct.pack/unpack float32 的精度限制在约 7 位有效数字。
    # Python 的 repr(float) 对 float64 给出足够精度，但我们的值来自 struct float32，
    # 所以直接用 repr 足够还原同一个 float32。
    return repr(float(v))


# ─────────────────────────────────────────────────────────────────────────────
# L1.3 颜色转换工具
# ─────────────────────────────────────────────────────────────────────────────

def _ubyte_to_float(b: int) -> float:
    """ubyte [0,255] → float [0.0, 1.0]（参照 mrl3 color_value = b/255）。"""
    return float(b) / 255.0


def _float_to_ubyte(f: float) -> int:
    """float [0.0, 1.0] → ubyte [0,255]（clamp + round，参照 mrl3 round(c*255)）。"""
    return max(0, min(255, round(float(f) * 255.0)))


# ─────────────────────────────────────────────────────────────────────────────
# items_to_dict  —  EFXFieldItem collection → values dict
# ─────────────────────────────────────────────────────────────────────────────

def items_to_dict(block_props: EFXBlockProps, schema: list) -> dict:
    """
    把 block_props.field_items 还原为 values dict，可直接喂给 AttrBlock.encode()。

    参数
    ----
    block_props : EFXBlockProps
    schema      : list — 原始 schema（用于还原正确的 Python 类型）

    返回
    ----
    dict — 与 AttrBlock.decode() 返回格式完全一致。

    注意：此函数是 dict_to_items 的精确逆，必须还原完全相同的 Python 类型，
    以保证喂给 pack(schema, values) 后得到原始字节。
    """
    # 建 name→spec 映射（schema 中字段名唯一）
    spec_map = {name: spec for name, spec in schema}

    result = {}
    for item in block_props.field_items:
        name = item.ori_name
        dtype = item.data_type
        spec = spec_map.get(name)
        if spec is None:
            raise ValueError(f"items_to_dict: 字段 {name!r} 不在 schema 中")

        result[name] = _read_item_value(item, dtype, spec)

    return result


def _read_item_value(item: EFXFieldItem, dtype: str, spec):
    """从 item 值槽读出并转换为原始 Python 类型（与 unpack 返回类型一致）。"""
    if dtype == "FLOAT":
        return float(item.float_value)

    elif dtype == "INT":
        # 根据 spec 判断原始类型宽度（无需特殊处理，pack('<i', val) 等会截断）
        return int(item.int_value)

    elif dtype == "UINT":
        return int(item.uint_str)

    elif dtype == "BOOL":
        return bool(item.bool_value)

    elif dtype == "BYTE1":
        return int(item.byte1_value) & 0xFF

    elif dtype == "SHORT1":
        return int(item.short1_value)

    elif dtype == "FLOAT2":
        return list(item.float2_value)

    elif dtype == "FLOAT3":
        # XYZ type 3 也映射到 FLOAT3，返回 list[float]
        return list(item.float3_value)

    elif dtype == "FLOAT4":
        return list(item.float4_value)

    elif dtype == "FLOAT6":
        return list(item.float6_value)

    elif dtype == "COLOUR":
        return [int(x) for x in item.colour_value]

    elif dtype == "COLOR_RGBA":
        # L1.3：float [0,1] → ubyte [0,255]，返回 list[int]
        # 用于 spec='colour' 和 spec=('XYZ',2)（第4字节为 alpha，全4通道均从 picker 取）
        return [_float_to_ubyte(c) for c in item.color_rgba_value]

    elif dtype == "INT2":
        return [int(x) for x in item.int2_value]

    elif dtype == "INT3":
        # XYZ type 1 也映射到 INT3，返回 list[int]
        return [int(x) for x in item.int3_value]

    elif dtype == "INT4":
        return [int(x) for x in item.int4_value]

    elif dtype == "INT_PAIR":
        parts = item.int_pair_str.split(",")
        return [int(x) for x in parts]

    elif dtype == "FLOAT2_STR":
        parts = item.float2_str.split(",")
        return [float(x) for x in parts]

    elif dtype == "FLOAT3_STR":
        parts = item.float3_str.split(",")
        return [float(x) for x in parts]

    elif dtype == "FLOAT5_STR":
        parts = item.float5_str.split(",")
        return [float(x) for x in parts]

    elif dtype == "FLOAT8_STR":
        parts = item.float8_str.split(",")
        return [float(x) for x in parts]

    elif dtype == "FLOAT16_STR":
        parts = item.float16_str.split(",")
        return [float(x) for x in parts]

    elif dtype == "INT10_STR":
        parts = item.int10_str.split(",")
        return [int(x) for x in parts]

    elif dtype == "INT16_STR":
        parts = item.int16_str.split(",")
        return [int(x) for x in parts]

    elif dtype == "ARRAY_STR":
        # 根据 spec 的 scalar 类型决定解析为 float 还是 int
        parts = item.array_str.split(",")
        if isinstance(spec, tuple) and len(spec) == 2:
            scalar = spec[0]
            if scalar == 'f':
                return [float(x) for x in parts]
            else:
                return [int(x) for x in parts]
        # 无法判断时尝试 int
        return [int(x) for x in parts]

    elif dtype == "OPAQUE":
        return base64.b64decode(item.opaque_str)

    else:
        raise ValueError(f"_read_item_value: 未知 dtype={dtype!r}")


# ─────────────────────────────────────────────────────────────────────────────
# rebuild_data_bytes  —  按字段重建 data_bytes（L1.1b 核心路径）
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_data_bytes(block_props, schema: list) -> bytes:
    """
    按字段顺序重建 data_bytes，实现逐字段无损性：
      - edited=False 或 read_only=True → 直接用 b64decode(item.orig_b64)（bit 精确）
      - edited=True 且 read_only=False → 用该字段 spec 重新 pack 新值

    参数
    ----
    block_props : EFXBlockProps（或 _MockBlockProps）
    schema      : list — 原始 schema

    返回
    ----
    bytes — 重建后的 data_bytes

    异常
    ----
    ValueError — 若某字段 orig_b64 缺失且未编辑（无法重建）
    """
    from ..efx_format.structs import pack as structs_pack

    spec_map = {name: spec for name, spec in schema}
    parts = []

    for item in block_props.field_items:
        name = item.ori_name
        spec = spec_map.get(name)
        if spec is None:
            raise ValueError(f"rebuild_data_bytes: 字段 {name!r} 不在 schema 中")

        # 判断是否使用 orig 字节
        use_orig = (not item.edited) or item.read_only

        if use_orig:
            if item.orig_b64:
                parts.append(base64.b64decode(item.orig_b64))
            else:
                # orig_b64 未填充（旧数据兼容）→ 退出到 pack 路径
                val = _read_item_value(item, item.data_type, spec)
                parts.append(structs_pack([("_", spec)], {"_": val}))
        else:
            # edited=True 且 read_only=False：用新值 pack
            # COLOR_RGBA（含 ('XYZ',2) 的 alpha 通道）：全4字节均从 picker 取，直接 pack
            val = _read_item_value(item, item.data_type, spec)
            parts.append(structs_pack([("_", spec)], {"_": val}))

    return b"".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# _init_custom_field_block  —  Phase A：custom 块固定标量字段展开
# ─────────────────────────────────────────────────────────────────────────────

def _decompose_custom_schema(schema):
    """
    Phase A.2：把 custom 字段 schema 展开为可平铺的 item 条目，处理复合 spec：
      - ('XYZ[]', count, t) → count 个元素（item_name=f"{name}[{i}]"，dtype 按 XYZ 元素类型）
      - 'EPVColorSlot'      → 子字段（item_name=f"{name}.{sub}"，dtype 按子 spec）
      - 其它 flat spec       → 单 item（item_name=name）

    每条目 dict：{item_name, dtype, spec, get(values), set(values, x)}。
    get/set 在 decode 出的 values dict 上读写（处理嵌套 list/dict）。
    若任一（子）spec 不可表示 → 返回 None（整块退回路径-only）。

    build（值→item）与 rebuild（item→值）共用此分解，保证一致。
    """
    from ..efx_format.structs import _EPVCSLOT_FIELDS

    entries = []
    for name, spec in schema:
        # XYZ 数组：('XYZ[]', count, xyz_type) → count 个元素 item
        if isinstance(spec, tuple) and len(spec) == 3 and spec[0] == 'XYZ[]':
            count, xyz_t = spec[1], spec[2]
            elem_spec = ('XYZ', xyz_t)
            dtype = _spec_to_dtype(elem_spec)
            if dtype is None:
                return None
            for i in range(count):
                entries.append({
                    'item_name': f"{name}[{i}]", 'dtype': dtype, 'spec': elem_spec,
                    'get': (lambda v, n=name, idx=i: v[n][idx]),
                    'set': (lambda v, x, n=name, idx=i: v[n].__setitem__(idx, x)),
                })
        # EPVColorSlot 嵌套 dict → 子字段 item
        elif spec == 'EPVColorSlot':
            for sub, subspec in _EPVCSLOT_FIELDS:
                dtype = _spec_to_dtype(subspec)
                if dtype is None:
                    return None
                entries.append({
                    'item_name': f"{name}.{sub}", 'dtype': dtype, 'spec': subspec,
                    'get': (lambda v, n=name, s=sub: v[n][s]),
                    'set': (lambda v, x, n=name, s=sub: v[n].__setitem__(s, x)),
                })
        # 普通 flat spec → 单 item
        else:
            dtype = _spec_to_dtype(spec)
            if dtype is None:
                return None
            entries.append({
                'item_name': name, 'dtype': dtype, 'spec': spec,
                'get': (lambda v, n=name: v[n]),
                'set': (lambda v, x, n=name: v.__setitem__(n, x)),
            })
    return entries


def _build_custom_field_items(values, schema, bp) -> bool:
    """
    按 _decompose_custom_schema 把 values 里的标量/颜色/嵌套字段展开为 EFXFieldItem。
    不算 orig_b64（rebuild 走 decode→pack）。含不可表示字段 → 返回 False。
    """
    entries = _decompose_custom_schema(schema)
    if entries is None:
        return False
    bp.field_items.clear()
    for e in entries:
        try:
            val = e['get'](values)
        except Exception:
            bp.field_items.clear()
            return False
        item = bp.field_items.add()
        item.ori_name = e['item_name']
        item.data_type = e['dtype']
        item.edited = False
        item.orig_b64 = ""
        item.read_only = False
        try:
            _write_item_value(item, e['dtype'], val, e['spec'])
        except Exception:
            bp.field_items.clear()
            return False
    return True


def _init_custom_field_block(blk, bp, paths) -> bool:
    """
    Phase A：对 CUSTOM_FIELD_SCHEMA_MAP 中的 custom 类型，把固定标量字段展开为
    可编辑 EFXFieldItem（路径仍建成 STRING item）。

    流程：
      1. values = blk.decode()；schema = custom_field_schema(type_hash)。
      2. 若 schema 含非 flat 字段（XYZ[] / EPVColorSlot 等）→ 返回 False（退回纯路径）。
      3. dict_to_items 建标量 item（data_bytes=None，不算 orig_b64）。
         成功后再 append 路径 STRING item（路径不在 schema，不会被 dict_to_items 建）。
         不加 __opaque_hint__（字段已全部可编辑）。
      4. 统一闸门：rebuild_custom_field_block 对"未编辑态"重建 == 原 data_bytes？
         不等 → 清理 + 返回 False（保守退回）。成功 → is_editable=True + 返回 True。

    返回 True = 成功展开（调用者直接 return）；False = 退回纯路径模式。
    成功路径会自行设置 bp.is_editable=True；失败路径会清理 field_items。
    """
    from ..efx_format.structs import custom_field_schema

    type_hash = blk.type_hash

    from ..efx_format.hashes import HASH_TO_NAME as _H2N
    _tname = _H2N.get(type_hash, f'0x{type_hash:08X}')

    try:
        values = blk.decode()
    except Exception as _e:
        print(f"[EFX Phase A] {_tname}: blk.decode() 失败 → {_e}")
        return False
    if values is None:
        print(f"[EFX Phase A] {_tname}: blk.decode() 返回 None")
        return False

    schema = custom_field_schema(type_hash)
    if schema is None:
        print(f"[EFX Phase A] {_tname}: custom_field_schema 返回 None")
        return False

    # 建字段项（含 XYZ[]→多 COLOR_RGBA、EPVColorSlot→子字段 的分解；
    # data_bytes=None：不算 orig_b64，rebuild 走 decode→覆盖→pack）。
    # 含不可表示字段 → 返回 False 退回纯路径模式。
    ok = _build_custom_field_items(values, schema, bp)
    if not ok:
        bp.field_items.clear()
        print(f"[EFX Phase A] {_tname}: _build_custom_field_items 失败（含不可表示字段）")
        return False

    # 追加路径 STRING item（路径不在 schema，需手动建）
    if type_hash == _MESH_HASH():
        _names = ['mod3_path', 'placement_path']
    else:
        _names = ['path'] * len(paths)
    for name, path_str in zip(_names, paths):
        item = bp.field_items.add()
        item.ori_name = name
        item.data_type = 'STRING'
        item.edited = False
        item.read_only = False
        item.orig_b64 = ""
        item.string_value = path_str.rstrip('\x00')

    # ── 统一闸门：未编辑态重建 == 原 data_bytes ──────────────────────────────
    try:
        rebuilt = rebuild_custom_field_block(bp, type_hash)
        if rebuilt != blk.data_bytes:
            bp.is_editable = False
            bp.field_items.clear()
            _diff = next(
                (i for i, (a, b) in enumerate(zip(rebuilt, blk.data_bytes)) if a != b),
                min(len(rebuilt), len(blk.data_bytes))
            )
            print(
                f"[EFX Phase A] {_tname}: 统一闸门失败 "
                f"rebuilt={len(rebuilt)}B orig={len(blk.data_bytes)}B "
                f"first_diff@{_diff}"
            )
            return False
    except Exception as _e:
        bp.is_editable = False
        bp.field_items.clear()
        print(f"[EFX Phase A] {_tname}: rebuild_custom_field_block 抛出异常 → {_e}")
        return False

    bp.is_editable = True
    return True


# ─────────────────────────────────────────────────────────────────────────────
# _init_path_block_props  —  L1.1b：初始化含路径 custom 类型的路径字段
# ─────────────────────────────────────────────────────────────────────────────

def _init_path_block_props(blk, bp) -> None:
    """
    对含路径的 custom-codec 类型（UVSEQUENCE / BILLBOARD3D / MESH / RIBBON /
    PLANE / RIBBONBLADE / TURBULENCE / LIGHTNING / RGBWATER），
    提取路径字段建成 STRING 类型的 EFXFieldItem，其余字节保持 opaque。

    导入闸门：建项后立即 rebuild_with_paths(原路径) 验证 == 原 data_bytes；
    不等则 is_editable=False 退回纯 base64。
    """
    from ..efx_format.structs import (
        PATH_EDITABLE_CUSTOM_HASHES,
        CUSTOM_FIELD_SCHEMA_MAP,
        extract_paths,
        rebuild_with_paths,
        custom_field_schema,
    )

    type_hash = blk.type_hash

    # 仅处理本批次支持的类型
    if type_hash not in PATH_EDITABLE_CUSTOM_HASHES:
        bp.is_editable = False
        return

    try:
        paths = extract_paths(type_hash, blk.data_bytes)
    except Exception as _e:
        from ..efx_format.hashes import HASH_TO_NAME as _H2N
        print(f"[EFX Path] {_H2N.get(type_hash, f'0x{type_hash:08X}')}: extract_paths 失败 → {_e}")
        bp.is_editable = False
        return

    # ── 路径闸门：验证 rebuild == 原始字节 ───────────────────────────────────
    try:
        rebuilt = rebuild_with_paths(type_hash, blk.data_bytes, paths)
        if rebuilt != blk.data_bytes:
            from ..efx_format.hashes import HASH_TO_NAME as _H2N
            _diff = next(
                (i for i, (a, b) in enumerate(zip(rebuilt, blk.data_bytes)) if a != b),
                min(len(rebuilt), len(blk.data_bytes))
            )
            print(
                f"[EFX Path] {_H2N.get(type_hash, f'0x{type_hash:08X}')}: "
                f"路径闸门失败 rebuilt={len(rebuilt)}B orig={len(blk.data_bytes)}B "
                f"first_diff@{_diff}"
            )
            bp.is_editable = False
            return
    except Exception as _e:
        from ..efx_format.hashes import HASH_TO_NAME as _H2N
        print(f"[EFX Path] {_H2N.get(type_hash, f'0x{type_hash:08X}')}: rebuild_with_paths 抛出异常 → {_e}")
        bp.is_editable = False
        return

    # ── Phase A：固定标量字段展开（仅 CUSTOM_FIELD_SCHEMA_MAP 中的 9 种）──────
    # 这些类型把固定标量字段也建成可编辑 item（路径仍为 STRING item），导出走
    # rebuild_custom_field_block（decode → 覆盖 → pack）。
    # 任一步退回 → 走下面的纯路径模式（仅路径 item + opaque hint，原 L1.1b 行为）。
    if type_hash in CUSTOM_FIELD_SCHEMA_MAP:
        if _init_custom_field_block(blk, bp, paths):
            return
        # _init_custom_field_block 返回 False → 已自行清理，继续纯路径回退

    # ── Phase B：PTBEHAVIOR 全参数展开 ──────────────────────────────────────
    if type_hash == _PTBEHAVIOR_HASH():
        if _init_ptbehavior_block(blk, bp):
            return
        # Phase B 失败 → 继续路径兜底

    # ── 建路径字段项（纯路径模式：MATERIAL/PTBEHAVIOR 及 Phase A 退回的块）────
    bp.field_items.clear()

    # 按类型确定路径字段命名方案：
    #   MESH：两条固定路径（mod3 + placement）
    #   MATERIAL / PTBEHAVIOR：可变数量，用 path_0/path_1/... 按序命名
    #   其余单路径类型：固定名称 'path'
    if type_hash == _MESH_HASH():
        _names = ['mod3_path', 'placement_path']
    elif type_hash in (_MATERIAL_HASH(), _PTBEHAVIOR_HASH()):
        # L1.1c：MATERIAL/PTBEHAVIOR 含 0~N 条嵌入路径，按序编号
        _names = [f'path_{i}' for i in range(len(paths))]
    else:
        _names = ['path']

    for name, path_str in zip(_names, paths):
        item = bp.field_items.add()
        item.ori_name = name
        item.data_type = 'STRING'
        item.edited = False
        item.read_only = False
        item.orig_b64 = ""   # 路径字段不需要 orig_b64（rebuild 走 rebuild_with_paths）
        # UI 存储不含尾部 \x00 的路径字符串（\x00 在 rebuild 时由 rebuild_with_paths 保留）
        item.string_value = path_str.rstrip('\x00')

    # ── 追加一个 opaque 提示项（面板提示其余字段暂 opaque）──────────────────
    hint = bp.field_items.add()
    hint.ori_name = '__opaque_hint__'
    hint.data_type = 'OPAQUE'
    hint.edited = False
    hint.read_only = True
    hint.orig_b64 = ""
    hint.opaque_str = ""

    bp.is_editable = True


def _MESH_HASH() -> int:
    """延迟返回 MESH hash（避免循环导入时提前求值）。"""
    from ..efx_format.hashes import MESH
    return MESH


def _MATERIAL_HASH() -> int:
    """延迟返回 MATERIAL hash（避免循环导入时提前求值）。"""
    from ..efx_format.hashes import MATERIAL
    return MATERIAL


def _PTBEHAVIOR_HASH() -> int:
    """延迟返回 PTBEHAVIOR hash（避免循环导入时提前求值）。"""
    from ..efx_format.hashes import PTBEHAVIOR
    return PTBEHAVIOR


def _PTBEHAVIOR_HASH_RB() -> int:
    """同 _PTBEHAVIOR_HASH，供 get_block_data_bytes 重建分发使用。"""
    from ..efx_format.hashes import PTBEHAVIOR
    return PTBEHAVIOR


# ─────────────────────────────────────────────────────────────────────────────
# PTBEHAVIOR Phase B：全参数展开编辑
#
# 结构（见 structs.unpack_ptbehavior）：
#   int unkn0(4) + int behav_type_len(4) + int para_count(4) +
#   char b_type[behav_type_len] +
#   para_count × EFX_Behav：
#     long unkn(4) + long const0(4) + int t(4) + type-dependent value
#
# Items 布局：
#   'b_type'       STRING — 行为类名（无尾 \0）
#   'p{i}'         dtype  — 第 i 个 param 的值（t != 0x15 时单 item）
#   'p{i}_v0..v3'  4 items— t==0x15 时四个子值（FLOAT,INT,FLOAT,INT）
#
# 导出重建：unpack 原字节 → 对 edited=True 的 item 覆盖值 → pack_ptbehavior
# ─────────────────────────────────────────────────────────────────────────────

def _ptb_param_dtype(t: int) -> str:
    """把 EFX_Behav.t 类型标签映射到 EFXFieldItem.data_type。"""
    return {
        0x03: 'INT',
        0x05: 'INT',
        0x06: 'INT',
        0x0C: 'FLOAT',
        0x0F: 'COLOR_RGBA',
        0x14: 'FLOAT3',
        0x36: 'INT_PAIR',
        0x37: 'INT_PAIR',
        0x40: 'UINT',
        0x80: 'STRING',
    }.get(t, 'INT')


def _ptb_param_hint(t: int) -> str:
    """把 EFX_Behav.t 映射到语义字段名（用于 UI 标注）。"""
    return {
        0x03: 'NULL',
        0x05: 'unkn0',
        0x06: 'decal_epv_color_slot',
        0x0C: 'unkn0',
        0x0F: 'color',
        0x14: 'unkn1',
        0x36: 'unkn1',
        0x37: 'unkn1',
        0x40: 'unkn0',
        0x80: 'path',
    }.get(t, 'unkn_type')


def _ptb_write_param_item(item, t: int, param: dict) -> None:
    """把 param dict 里的值写入 EFXFieldItem 的值槽。"""
    if t == 0x03:
        item.int_value = int(param.get('NULL', 0))
    elif t == 0x05:
        item.int_value = int(param.get('unkn0', 0))
    elif t == 0x06:
        item.int_value = int(param.get('decal_epv_color_slot', 0))
    elif t == 0x0C:
        item.float_value = float(param.get('unkn0', 0.0))
    elif t == 0x0F:
        color = param.get('color', [0, 0, 0, 255])
        item.color_rgba_value = tuple(max(0.0, min(1.0, c / 255.0)) for c in color)
    elif t == 0x14:
        vals = param.get('unkn1', [0.0, 0.0, 0.0])
        item.float3_value = tuple(float(v) for v in vals[:3])
    elif t in (0x36, 0x37):
        vals = param.get('unkn1', [0, 0])
        item.int_pair_str = f"{int(vals[0])},{int(vals[1])}"
    elif t == 0x40:
        item.uint_str = str(int(param.get('unkn0', 0)))
    elif t == 0x80:
        path_b = param.get('path', b'')
        item.string_value = path_b.rstrip(b'\x00').decode('utf-8', errors='replace')
    else:
        item.int_value = int(param.get('unkn_type', 0))


def _init_ptbehavior_block(blk, bp) -> bool:
    """
    Phase B：展开 PTBEHAVIOR 为可编辑 field_items。

    建 'b_type' STRING item + 每个 param 对应 item（t==0x15 展开为 4 个子 item）。
    末尾运行 rebuild_ptbehavior_block 闸门，验证字节精度。
    返回 True=成功（bp.is_editable 由本函数设置）；False=失败（已清理 items）。
    """
    from ..efx_format.structs import unpack_ptbehavior

    try:
        d, _ = unpack_ptbehavior(blk.data_bytes)
    except Exception:
        return False

    bp.field_items.clear()

    # b_type STRING item
    bt = bp.field_items.add()
    bt.ori_name = 'b_type'
    bt.data_type = 'STRING'
    bt.edited = False
    bt.read_only = False
    bt.orig_b64 = ''
    bt.string_value = d['b_type'].rstrip(b'\x00').decode('utf-8', errors='replace')

    for i, param in enumerate(d['params']):
        t = param['t']
        if t == 0x15:
            # 四个子 item：unkn0(f), unkn1(i), unkn2(f), unkn3(i)
            for suffix, vk, dtype_str in [
                ('_v0', 'unkn0', 'FLOAT'),
                ('_v1', 'unkn1', 'INT'),
                ('_v2', 'unkn2', 'FLOAT'),
                ('_v3', 'unkn3', 'INT'),
            ]:
                it = bp.field_items.add()
                it.ori_name = f'p{i}{suffix}'
                it.data_type = dtype_str
                it.edited = False
                it.read_only = False
                it.orig_b64 = ''
                val = param.get(vk, 0)
                if dtype_str == 'FLOAT':
                    it.float_value = float(val)
                else:
                    it.int_value = int(val)
        else:
            it = bp.field_items.add()
            it.ori_name = f'p{i}'
            it.hint_name = _ptb_param_hint(t)
            it.data_type = _ptb_param_dtype(t)
            it.edited = False
            it.read_only = False
            it.orig_b64 = ''
            _ptb_write_param_item(it, t, param)

    # 闸门：rebuild 必须 == 原始字节
    try:
        rebuilt = rebuild_ptbehavior_block(bp, blk.data_bytes)
        if rebuilt == blk.data_bytes:
            bp.is_editable = True
            return True
    except Exception:
        pass

    bp.field_items.clear()
    bp.is_editable = False
    return False


def rebuild_ptbehavior_block(bp, original_data: bytes = None) -> bytes:
    """
    Phase B 重建：unpack 原始字节 → 对 edited=True 的 item 覆盖值 → pack_ptbehavior。

    参数
    ----
    bp            : EFXBlockProps
    original_data : bytes | None — 若 None 则从 bp.raw_b64 解码
    """
    from ..efx_format.structs import unpack_ptbehavior, pack_ptbehavior

    orig = original_data if original_data is not None else base64.b64decode(bp.raw_b64)
    d, _ = unpack_ptbehavior(orig)

    # item 快速查表
    imap = {}
    for item in bp.field_items:
        if not item.ori_name.startswith('__'):
            imap[item.ori_name] = item

    # b_type
    bt = imap.get('b_type')
    if bt and bt.edited and not bt.read_only:
        new_str = bt.string_value
        if d['b_type'].endswith(b'\x00') and not new_str.endswith('\x00'):
            new_str += '\x00'
        d['b_type'] = new_str.encode('utf-8')

    # params
    for i, param in enumerate(d['params']):
        t = param['t']

        if t == 0x15:
            for suffix, vk, is_float in [
                ('_v0', 'unkn0', True),
                ('_v1', 'unkn1', False),
                ('_v2', 'unkn2', True),
                ('_v3', 'unkn3', False),
            ]:
                sub = imap.get(f'p{i}{suffix}')
                if sub and sub.edited and not sub.read_only:
                    param[vk] = float(sub.float_value) if is_float else int(sub.int_value)
            continue

        item = imap.get(f'p{i}')
        if not (item and item.edited and not item.read_only):
            continue

        if t == 0x03:
            param['NULL'] = int(item.int_value)
        elif t == 0x05:
            param['unkn0'] = max(-32768, min(32767, int(item.int_value)))
        elif t == 0x06:
            param['decal_epv_color_slot'] = int(item.int_value)
        elif t == 0x0C:
            param['unkn0'] = float(item.float_value)
        elif t == 0x0F:
            param['color'] = [max(0, min(255, round(c * 255)))
                               for c in item.color_rgba_value]
        elif t == 0x14:
            param['unkn1'] = list(item.float3_value)
        elif t in (0x36, 0x37):
            parts = item.int_pair_str.split(',')
            param['unkn1'] = [int(parts[0]), int(parts[1])]
        elif t == 0x40:
            param['unkn0'] = int(item.uint_str)
        elif t == 0x80:
            new_path = item.string_value
            if param['path'].endswith(b'\x00') and not new_path.endswith('\x00'):
                new_path += '\x00'
            param['path'] = new_path.encode('utf-8')
            param['path_len'] = len(param['path'])
        else:
            param['unkn_type'] = int(item.int_value)

    return pack_ptbehavior(d)


def rebuild_path_block_data_bytes(bp, type_hash: int) -> bytes:
    """
    对含路径 custom 类型，从 block_props 的 path 字段项重建 data_bytes。

    策略：
      - 读取所有 STRING 类型的字段项的 string_value（新路径，已去掉尾 \\x00）
      - 对 length-prefixed path 类型：若原始路径（来自 raw_b64）含尾 \\x00，则
        在新路径后自动追加 \\x00，保持文件格式兼容。
      - 用 rebuild_with_paths(type_hash, original_data_bytes, new_paths) 重建
        （非路径字节 verbatim 拷贝自 raw_b64）

    参数
    ----
    bp        : EFXBlockProps — 含路径字段和 raw_b64 的块属性
    type_hash : int

    返回
    ----
    bytes — 重建后的 data_bytes
    """
    from ..efx_format.structs import rebuild_with_paths, extract_paths

    # 原始字节（非路径部分的 verbatim 源）
    original_data = base64.b64decode(bp.raw_b64)

    # 获取原始路径（用于判断 null 结尾习惯）
    try:
        original_paths = extract_paths(type_hash, original_data)
    except Exception:
        original_paths = []

    # 从字段项收集新路径字符串（跳过 opaque hint 项）
    new_path_strs = []
    for item in bp.field_items:
        if item.data_type == 'STRING' and item.ori_name != '__opaque_hint__':
            new_path_strs.append(item.string_value)

    # 还原 null 尾部（若原始路径以 \x00 结尾，则新路径也加 \x00）
    # 这确保 length-prefixed path 类型的格式一致性
    new_paths = []
    for i, new_str in enumerate(new_path_strs):
        orig_str = original_paths[i] if i < len(original_paths) else ''
        if orig_str.endswith('\x00') and not new_str.endswith('\x00'):
            new_paths.append(new_str + '\x00')
        else:
            new_paths.append(new_str)

    return rebuild_with_paths(type_hash, original_data, new_paths)


# ─────────────────────────────────────────────────────────────────────────────
# rebuild_custom_field_block  —  Phase A：custom 块固定字段 + 路径重建
#
# 策略（decode → 覆盖 → pack）：
#   1. unpack 原始字节得到精确原值 dict（含 NaN/精度/哨兵）。
#   2. 对每个被编辑的标量字段项（edited=True, 非 read_only, 非 STRING, 名在 schema）
#      用 _read_item_value 读出新值覆盖 dict。
#   3. 对每个路径 STRING 字段项，按出现顺序对应 decode dict 里 bytes 类型键的顺序
#      （与 extract_paths / unpack_* 顺序一致）覆盖；保留原 null 结尾习惯。
#   4. pack(dict) 回字节。
#
# 未编辑字段：dict 保留 decode 原值 → pack 精确还原（field_roundtrip 已证位精确）。
# 因此 path_len 内嵌 / 字段连续性等布局问题全部由 codec 负责，本函数无需处理偏移。
# 仅用于 CUSTOM_FIELD_SCHEMA_MAP 中的 9 种类型（不含 MATERIAL/PTBEHAVIOR）。
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_custom_field_block(bp, type_hash: int) -> bytes:
    """
    用字段项里的新值（标量 + 路径）重建 custom 块 data_bytes。

    参数
    ----
    bp        : EFXBlockProps — 含 field_items + raw_b64
    type_hash : int — 必须在 CUSTOM_FIELD_SCHEMA_MAP 中

    返回
    ----
    bytes — 重建后的 data_bytes
    """
    from ..efx_format.structs import ATTR_CUSTOM_CODEC, custom_field_schema

    original = base64.b64decode(bp.raw_b64)
    unpack_fn, pack_fn = ATTR_CUSTOM_CODEC[type_hash]
    values, _consumed = unpack_fn(original, 0)

    schema = custom_field_schema(type_hash)
    # 用同一分解（XYZ[]→元素、EPVColorSlot→子字段）把被编辑 item 的新值写回
    # 嵌套 values dict——与 _build_custom_field_items 完全对称。
    entries = _decompose_custom_schema(schema)
    entry_map = {e['item_name']: e for e in entries} if entries else {}

    # ── 覆盖被编辑的标量/颜色/嵌套字段 ───────────────────────────────────────
    for item in bp.field_items:
        if item.data_type == 'STRING' or item.ori_name.startswith('__'):
            continue
        if item.edited and (not item.read_only) and item.ori_name in entry_map:
            e = entry_map[item.ori_name]
            try:
                e['set'](values, _read_item_value(item, item.data_type, e['spec']))
            except Exception:
                pass

    # ── 覆盖路径（STRING 字段项 → decode dict 里 bytes 类型键，按序对齐）──────
    # extract_paths / unpack_* 对 bytes 键的顺序一致（dict 保留插入顺序），
    # 故路径 STRING item 与 values 里 bytes 键按出现顺序 zip 对应。
    path_keys = [k for k in values if isinstance(values[k], (bytes, bytearray))]
    str_items = [
        it for it in bp.field_items
        if it.data_type == 'STRING' and it.ori_name != '__opaque_hint__'
    ]
    for it, key in zip(str_items, path_keys):
        # 未编辑的路径：保留 unpack 出来的原始字节（含 null 对齐填充），不替换。
        # 替换会把原文件里多余的 null 填充字节丢失，导致 path_len 字段不一致。
        if not it.edited:
            continue
        new = it.string_value
        orig_bytes = values[key]
        # 还原 null 结尾习惯：若原 bytes 以 \x00 结尾且新串不含尾 \x00，则补 \x00。
        if isinstance(orig_bytes, (bytes, bytearray)) \
                and orig_bytes.endswith(b'\x00') and not new.endswith('\x00'):
            new = new + '\x00'
        values[key] = new.encode('utf-8')

    return pack_fn(values)


# ─────────────────────────────────────────────────────────────────────────────
# init_block_props  —  供 io_tree 调用：初始化单个 EFX_BLOCK 的 efx_block
# ─────────────────────────────────────────────────────────────────────────────

def init_block_props(obj: bpy.types.Object, blk,
                     extern_objs_by_index: dict = None,
                     count_extern: int = 0) -> None:
    """
    初始化 obj.efx_block，尝试 decode + dict_to_items。

    参数
    ----
    obj : bpy.types.Object  — EFX_BLOCK Empty
    blk : AttrBlock         — 已解析的块对象
    extern_objs_by_index : dict[int, bpy.types.Object] | None
        {efx_index → EFX_EXTERN 对象} 映射，供 EXTERNREFERENCE 指针化使用。
        None 表示未提供（此时 EXTERNREFERENCE 块的 extern_ref_props 保持默认 pointerized=False）。
    count_extern : int
        文件头 count_extern 字段值，供 EXTERNREFERENCE 范围检查使用。

    副作用
    ------
    - 设置 obj.efx_block.type_hash_str
    - 设置 obj.efx_block.raw_b64（始终，作为安全网）
    - 若 flat schema：decode → dict_to_items → is_editable=True
    - 否则：is_editable=False
    - 最后把 efx_dirty=False（覆盖加载期 update 回调的误置）
    - L2 #1c：若 type_hash==EXTERNREFERENCE，额外初始化 obj.efx_extern_ref
    """
    global _LOADING
    _LOADING = True

    try:
        bp = obj.efx_block
        bp.type_hash_str = str(blk.type_hash)
        bp.raw_b64 = base64.b64encode(blk.data_bytes).decode("ascii")
        bp.is_editable = False
        bp.field_items.clear()

        # 检查是否有 flat schema
        from ..efx_format.structs import ATTR_SCHEMA_MAP
        entry = ATTR_SCHEMA_MAP.get(blk.type_hash)

        if entry is not None:
            schema, _expected_size = entry
            # 仅处理 flat schema（非 _custom）
            if schema != '_custom':
                # 检查 schema 所有字段均可表示
                if _check_schema_all_flat(schema):
                    try:
                        values = blk.decode()
                        if values is not None:
                            ok = dict_to_items(values, schema, bp, data_bytes=blk.data_bytes)
                            if ok:
                                # ── 健壮性闸门：验证重建结果 == 原始字节 ──────
                                # 这保证：只有能 bit 精确重建的块才开放编辑。
                                try:
                                    rebuilt = rebuild_data_bytes(bp, schema)
                                    if rebuilt == blk.data_bytes:
                                        bp.is_editable = True
                                    else:
                                        # 重建不一致 → 退回 opaque（保守安全）
                                        bp.is_editable = False
                                        bp.field_items.clear()
                                except Exception:
                                    bp.is_editable = False
                                    bp.field_items.clear()
                    except Exception:
                        bp.is_editable = False
                        bp.field_items.clear()
            else:
                # ── L1.1b：_custom 类型含路径的路径字段初始化 ──────────────────
                _init_path_block_props(blk, bp)

        # ── L2 #1c：EXTERNREFERENCE 指针化初始化 ─────────────────────────────────
        # 在 flat schema 处理之后（bp.raw_b64 已写入，无论 is_editable 与否均执行）。
        # init_extern_ref_props 使用 data_bytes（来自 blk），与 bp 的 orig_b64 路径无关，
        # 因此无论 is_editable 是否为 True 都安全调用。
        try:
            from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
            if blk.type_hash == _EXTERNREFERENCE_HASH:
                from . import extern_ref as _extern_ref
                _extern_ref.init_extern_ref_props(
                    obj,
                    blk.data_bytes,
                    extern_objs_by_index if extern_objs_by_index is not None else {},
                    count_extern,
                )
        except Exception:
            # 任何异常安全跳过（efx_extern_ref 保持默认 pointerized=False）
            pass

        # 导入末尾统一重置脏标记
        bp.efx_dirty = False

    finally:
        _LOADING = False


# ─────────────────────────────────────────────────────────────────────────────
# get_block_data_bytes  —  供 io_tree 导出时调用
# ─────────────────────────────────────────────────────────────────────────────

def get_block_data_bytes(obj: bpy.types.Object,
                         extern_index_map: dict = None,
                         body_index_map: dict = None,
                         play_index_map: dict = None) -> bytes:
    """
    从 obj.efx_block 还原 data_bytes。

    策略
    ----
    - 若 efx_dirty=True 且 is_editable=True：
        items_to_dict → AttrBlock.encode → 返回新字节（用户编辑生效）
    - 否则：
        raw_b64 → 原始字节（byte-perfect 回退）
    - L2 #1c（post-step）：若 type_hash==EXTERNREFERENCE 且 pointerized=True，
        额外调用 overlay_extern_ref_index 覆写 referenceIndex 字段（4 字节，偏移 4）。
    - L2 #1d（post-step）：若 type_hash==PTLIFE 或 PTCOLLISION 且 pointerized=True，
        额外调用 apply_block_ref_overlays 覆写 relationIndex / ieIndex 字段。
        此步骤在上述两条路径之后执行，故 dirty=False（orig_b64）和 dirty=True（重建）
        两条路径均受益。

    参数
    ----
    obj : bpy.types.Object  — EFX_BLOCK Empty
    extern_index_map : dict[bpy.types.Object, int] | None
        {EFX_EXTERN Object → extern 段局部 0-based index}。None 时跳过 #1c 覆写。
    body_index_map : dict[bpy.types.Object, int] | None
        {EFX_BODY Object → main 段局部 0-based index}。None 时跳过 #1d body 覆写。
    play_index_map : dict[bpy.types.Object, int] | None
        {EFX_PLAY Object → play 段局部 0-based index}。None 时跳过 #1d play 覆写。

    返回
    ----
    bytes — data_bytes（不含 type_hash 前缀）
    """
    bp = obj.efx_block

    if bp.efx_dirty and bp.is_editable:
        try:
            from ..efx_format.structs import (
                ATTR_SCHEMA_MAP,
                PATH_EDITABLE_CUSTOM_HASHES,
                CUSTOM_FIELD_SCHEMA_MAP,
            )

            type_hash = int(bp.type_hash_str)
            entry = ATTR_SCHEMA_MAP.get(type_hash)
            if entry is None:
                raise ValueError(f"get_block_data_bytes: 无 schema for hash {type_hash}")
            schema, _expected_size = entry

            if schema == '_custom':
                if type_hash in CUSTOM_FIELD_SCHEMA_MAP:
                    # Phase A：固定标量字段 + 路径 → decode→覆盖→pack 重建
                    data = rebuild_custom_field_block(bp, type_hash)
                elif type_hash in PATH_EDITABLE_CUSTOM_HASHES:
                    # Phase B：PTBEHAVIOR 全参数重建（b_type item 存在即为 Phase B）
                    _is_ptb = (type_hash == _PTBEHAVIOR_HASH_RB())
                    if _is_ptb and any(it.ori_name == 'b_type' for it in bp.field_items):
                        data = rebuild_ptbehavior_block(bp)
                    else:
                        # L1.1b/c：MATERIAL 等 → 仅路径感知重建
                        data = rebuild_path_block_data_bytes(bp, type_hash)
                else:
                    # 不支持编辑的 custom 类型（TIML 等）→ 退回 raw_b64
                    raise ValueError(f"get_block_data_bytes: custom 类型 0x{type_hash:08X} 不支持编辑")
            else:
                # L1.1b：用逐字段重建路径（未编辑字段用 orig_b64，编辑字段重新 pack）
                data = rebuild_data_bytes(bp, schema)

            data = _apply_extern_ref_overlay(obj, data, extern_index_map)
            data = _apply_body_play_ref_overlays(obj, data, body_index_map, play_index_map)
            return data

        except Exception:
            # 编码失败 → 安全回退到原始字节
            pass

    # 回退：使用原始 raw_b64
    data = base64.b64decode(bp.raw_b64)
    data = _apply_extern_ref_overlay(obj, data, extern_index_map)
    data = _apply_body_play_ref_overlays(obj, data, body_index_map, play_index_map)
    return data


def _apply_extern_ref_overlay(obj: bpy.types.Object,
                               data: bytes,
                               extern_index_map) -> bytes:
    """
    L2 #1c 后处理：若该块是 EXTERNREFERENCE 且 pointerized=True，
    覆写 data 中 referenceIndex 对应的 4 字节。

    extern_index_map 为 None 时直接返回（导出路径未提供 extern 映射，保守原样）。
    """
    if extern_index_map is None:
        return data
    try:
        from ..efx_format.hashes import EXTERNREFERENCE as _EXTERNREFERENCE_HASH
        bp = obj.efx_block
        if int(bp.type_hash_str) != _EXTERNREFERENCE_HASH:
            return data
        from . import extern_ref as _extern_ref
        return _extern_ref.overlay_extern_ref_index(data, obj, extern_index_map)
    except Exception:
        # 任何异常安全跳过（原样返回）
        return data


def _apply_body_play_ref_overlays(obj: bpy.types.Object,
                                   data: bytes,
                                   body_index_map,
                                   play_index_map) -> bytes:
    """
    L2 #1d 后处理：若该块是 PTLIFE 或 PTCOLLISION 且 pointerized=True，
    覆写 data 中对应的字段字节。

    body_index_map / play_index_map 为 None 时跳过（保守原样）。
    """
    if body_index_map is None and play_index_map is None:
        return data
    try:
        from . import body_play_ref as _bpr
        return _bpr.apply_block_ref_overlays(
            data, obj,
            body_index_map if body_index_map is not None else {},
            play_index_map if play_index_map is not None else {},
        )
    except Exception:
        # 任何异常安全跳过（原样返回）
        return data


# ─────────────────────────────────────────────────────────────────────────────
# verify_items_lossless  —  验证钩子（供 MCP 调用）
# ─────────────────────────────────────────────────────────────────────────────

def verify_items_lossless(samples_dir: str) -> dict:
    """
    对 samples_dir 下所有 .efx 文件，对每个 flat 可编辑块执行：
      decode() → dict_to_items（内存模拟，带 data_bytes）→ rebuild_data_bytes（全未编辑）
    断言结果 == 原始 data_bytes。

    L1.1b 路径：未编辑字段直接用 orig_b64（bit 精确），绕开 float NaN/精度问题，
    理论上所有 is_editable 块必须 100% 通过。

    此函数不依赖 Blender PropertyGroup 的 UI 层，使用一个内存模拟的
    block_props 容器（MockBlockProps）在纯 Python 中运行，可在 Blender
    Python 解释器中被直接调用（无需任何场景对象）。

    参数
    ----
    samples_dir : str — 包含 .efx 文件的目录

    返回
    ----
    dict :
      {
        "total_blocks":   int,    # 遇到的全部 AttrBlock 数
        "editable_blocks":int,    # flat schema 可编辑块数
        "lossless_pass":  int,    # 通过往返测试的块数
        "fails": [                # 失败条目
          {"file": str, "hash": str, "reason": str}, ...
        ]
      }
    """
    import os

    from ..efx_format.efxfile import EFXFile
    from ..efx_format.structs import ATTR_SCHEMA_MAP

    efx_files = sorted(
        os.path.join(samples_dir, fn)
        for fn in os.listdir(samples_dir)
        if fn.lower().endswith(".efx")
    )

    total_blocks   = 0
    editable_blocks = 0
    lossless_pass  = 0
    fails          = []

    for filepath in efx_files:
        fname = os.path.basename(filepath)
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
            efx = EFXFile.parse(raw)
        except Exception as exc:
            fails.append({"file": fname, "hash": "N/A", "reason": f"解析失败: {exc}"})
            continue

        # 收集所有 AttrBlock
        all_blocks = []
        for body in efx.main:
            if hasattr(body, "attr_blocks"):
                all_blocks.extend(body.attr_blocks)

        for blk in all_blocks:
            total_blocks += 1
            hash_str = f"0x{blk.type_hash:08X}"

            entry = ATTR_SCHEMA_MAP.get(blk.type_hash)
            if entry is None:
                continue  # 未知类型，不计入 editable
            schema, expected_size = entry
            if schema == '_custom':
                continue  # _custom 类型，本轮不处理

            # 检查 schema 是否全 flat
            if not _check_schema_all_flat(schema):
                continue  # 含复杂字段，不计入 editable

            editable_blocks += 1

            # ── 往返测试（内存模拟，不建 Blender 对象）──────────────────────
            # L1.1b：改用 rebuild_data_bytes（全未编辑路径），
            # 未编辑字段恒等还原（orig_b64），理论上必须通过。
            try:
                # 1. decode
                values_orig = blk.decode()
                if values_orig is None:
                    fails.append({
                        "file": fname, "hash": hash_str,
                        "reason": "decode() 返回 None",
                    })
                    continue

                # 2. dict_to_items → 模拟 block_props（带 data_bytes 以填充 orig_b64）
                mock_bp = _MockBlockProps()
                ok = dict_to_items(values_orig, schema, mock_bp, data_bytes=blk.data_bytes)
                if not ok:
                    fails.append({
                        "file": fname, "hash": hash_str,
                        "reason": "dict_to_items 返回 False",
                    })
                    continue

                # 3. rebuild_data_bytes（全未编辑）→ 重建字节
                # 此路径：每个字段用 orig_b64（bit 精确），理论上必等原始字节。
                rebuilt_bytes = rebuild_data_bytes(mock_bp, schema)

                # 4. 断言
                if rebuilt_bytes == blk.data_bytes:
                    lossless_pass += 1
                else:
                    # 找出首个差异字节位置
                    diff_pos = -1
                    for i, (a, b) in enumerate(zip(blk.data_bytes, rebuilt_bytes)):
                        if a != b:
                            diff_pos = i
                            break
                    if diff_pos == -1 and len(blk.data_bytes) != len(rebuilt_bytes):
                        diff_pos = min(len(blk.data_bytes), len(rebuilt_bytes))
                    fails.append({
                        "file": fname,
                        "hash": hash_str,
                        "reason": (
                            f"字节不一致（rebuild 路径）：原始 {len(blk.data_bytes)}B，"
                            f"重建 {len(rebuilt_bytes)}B，"
                            f"首个差异偏移 {diff_pos}"
                        ),
                    })

            except Exception as exc:
                import traceback
                fails.append({
                    "file": fname,
                    "hash": hash_str,
                    "reason": f"异常: {exc}\n{traceback.format_exc()}",
                })

    return {
        "total_blocks":    total_blocks,
        "editable_blocks": editable_blocks,
        "lossless_pass":   lossless_pass,
        "fails":           fails,
    }


# ─────────────────────────────────────────────────────────────────────────────
# verify_paths_lossless  —  L1.1b 路径类型验证钩子（供 MCP 调用）
# ─────────────────────────────────────────────────────────────────────────────

def verify_paths_lossless(samples_dir: str) -> dict:
    """
    对 samples_dir 下所有 .efx 文件，对每个含路径 custom 类型块执行：
      extract_paths → rebuild_with_paths(原路径) == 原 data_bytes

    目标：100% 通过（identity 重建）。

    参数
    ----
    samples_dir : str — 包含 .efx 文件的目录

    返回
    ----
    dict :
      {
        "total_custom_blocks": int,   # 遇到的全部 _custom 块数
        "path_editable_blocks": int,  # 支持路径编辑的块数
        "lossless_pass":        int,  # 通过 identity 验证的块数
        "path_samples": [             # 前 20 个路径样例（用于确认解对）
          {"file": str, "hash_name": str, "paths": list[str]}, ...
        ],
        "fails": [
          {"file": str, "hash": str, "reason": str}, ...
        ]
      }
    """
    import os

    from ..efx_format.efxfile import EFXFile
    from ..efx_format.structs import (
        ATTR_SCHEMA_MAP,
        PATH_EDITABLE_CUSTOM_HASHES,
        extract_paths,
        rebuild_with_paths,
    )
    from ..efx_format.hashes import HASH_TO_NAME

    efx_files = sorted(
        os.path.join(samples_dir, fn)
        for fn in os.listdir(samples_dir)
        if fn.lower().endswith(".efx")
    )

    total_custom_blocks  = 0
    path_editable_blocks = 0
    lossless_pass        = 0
    path_samples         = []
    fails                = []

    for filepath in efx_files:
        fname = os.path.basename(filepath)
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
            efx = EFXFile.parse(raw)
        except Exception as exc:
            fails.append({"file": fname, "hash": "N/A", "reason": f"解析失败: {exc}"})
            continue

        all_blocks = []
        for body in efx.main:
            if hasattr(body, "attr_blocks"):
                all_blocks.extend(body.attr_blocks)

        for blk in all_blocks:
            entry = ATTR_SCHEMA_MAP.get(blk.type_hash)
            if entry is None:
                continue
            schema, _ = entry
            if schema != '_custom':
                continue

            total_custom_blocks += 1
            hash_str = f"0x{blk.type_hash:08X}"

            if blk.type_hash not in PATH_EDITABLE_CUSTOM_HASHES:
                continue  # 不支持路径编辑的 custom 类型（TIML 等）

            path_editable_blocks += 1

            try:
                paths = extract_paths(blk.type_hash, blk.data_bytes)
                rebuilt = rebuild_with_paths(blk.type_hash, blk.data_bytes, paths)

                if rebuilt == blk.data_bytes:
                    lossless_pass += 1
                    # 收集路径样例
                    if len(path_samples) < 20:
                        hash_name = HASH_TO_NAME.get(blk.type_hash, hash_str)
                        path_samples.append({
                            "file": fname,
                            "hash_name": hash_name,
                            "paths": paths,
                        })
                else:
                    diff_pos = -1
                    for i, (a, b) in enumerate(zip(blk.data_bytes, rebuilt)):
                        if a != b:
                            diff_pos = i
                            break
                    if diff_pos == -1 and len(blk.data_bytes) != len(rebuilt):
                        diff_pos = min(len(blk.data_bytes), len(rebuilt))
                    fails.append({
                        "file": fname,
                        "hash": hash_str,
                        "reason": (
                            f"identity 验证失败：原始 {len(blk.data_bytes)}B，"
                            f"重建 {len(rebuilt)}B，首个差异偏移 {diff_pos}"
                        ),
                    })

            except Exception as exc:
                import traceback
                fails.append({
                    "file": fname,
                    "hash": hash_str,
                    "reason": f"异常: {exc}\n{traceback.format_exc()}",
                })

    return {
        "total_custom_blocks":  total_custom_blocks,
        "path_editable_blocks": path_editable_blocks,
        "lossless_pass":        lossless_pass,
        "path_samples":         path_samples,
        "fails":                fails,
    }


# ─────────────────────────────────────────────────────────────────────────────
# _MockBlockProps  —  纯 Python 模拟 EFXBlockProps（用于验证钩子）
# ─────────────────────────────────────────────────────────────────────────────

class _MockFieldItem:
    """模拟 EFXFieldItem，所有值槽设为默认值。"""

    def __init__(self):
        self.ori_name      = ""
        self.data_type     = "FLOAT"
        # L1.1b：无损性元数据
        self.orig_b64      = ""
        self.edited        = False
        self.read_only     = False
        # 值槽
        self.float_value   = 0.0
        self.int_value     = 0
        self.uint_str      = "0"
        self.bool_value    = False
        self.byte1_value   = 0
        self.short1_value  = 0
        self.float2_value  = [0.0, 0.0]
        self.float3_value  = [0.0, 0.0, 0.0]
        self.float4_value  = [0.0, 0.0, 0.0, 0.0]
        self.float6_value  = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.colour_value      = [0, 0, 0, 0]
        # L1.3 颜色色轮值槽
        self.color_rgba_value  = [0.0, 0.0, 0.0, 1.0]
        self.color_rgb_value   = [0.0, 0.0, 0.0]
        self.int2_value    = [0, 0]
        self.int3_value    = [0, 0, 0]
        self.int4_value    = [0, 0, 0, 0]
        self.float2_str    = ""
        self.float3_str    = ""
        self.float5_str    = ""
        self.float8_str    = ""
        self.float16_str   = ""
        self.int_pair_str  = ""
        self.int10_str     = ""
        self.int16_str     = ""
        self.array_str     = ""
        self.opaque_str    = ""
        self.string_value  = ""


class _MockBlockProps:
    """
    模拟 EFXBlockProps，用于 verify_items_lossless 的内存往返测试。
    实现 field_items 的 add() / clear() / 迭代接口。
    """

    def __init__(self):
        self._items         = []
        self.type_hash_str  = ""
        self.efx_dirty      = False
        self.raw_b64        = ""
        self.is_editable    = False
        self.field_index    = 0

    # 模拟 CollectionProperty 接口
    @property
    def field_items(self):
        return self

    def add(self):
        item = _MockFieldItem()
        self._items.append(item)
        return item

    def clear(self):
        self._items.clear()

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)
