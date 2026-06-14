"""
blender_efx/extern_ref.py  —  L2 #1c：ExternReference.referenceIndex → extern 指针化

设计原则（参照 CLAUDE.md / subselect.py / play_emitter.py 模式）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集（PropertyGroup / PointerProperty / BoolProperty / Panel）
  - 不使用 5.x 新增 API
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：死块/越界/count_extern=0 → pointerized=False → orig_b64 路径

EXTERNREFERENCE 块的 data_bytes 布局（EXTERNREFERENCE_SCHEMA，共 36 字节）：
  offset  0:  int  unkn0          (4 B)
  offset  4:  int  referenceIndex (4 B, 有符号 int32)  ← 指针化目标字段
  offset  8:  int  unkn1[7]       (28 B)

referenceIndex 语义（实测，BLUEPRINT §9）：
  -1                → 哨兵，无 extern 目标（22 个）
  0 <= v < count_extern → 有效 extern 局部 index（指向 EFX_EXTERN 对象）
  其他              → 死块/越界（count_extern=0 的文件中 15 个异常值）

指针化路径：
  导入（init_extern_ref_props）：
    有效范围 → extern_ref_ptr 指向对应 EFX_EXTERN；pointerized=True
    -1       → none=True；pointerized=True
    越界/死块 → pointerized=False（保持 orig_b64 路径，byte-perfect）

  导出（overlay_extern_ref_index）：
    pointerized=True  → 用 extern_ref_ptr 经 build_local_index_map 解析 extern 局部 index，
                         struct.pack_into('<i', ..., 4) 覆盖 data_bytes 偏移 4 的 4 字节
    pointerized=False → 不覆盖（原样，byte-perfect）

多对一天然支持：多个 EXTERNREFERENCE 块可指向同一 EFX_EXTERN 对象，
PointerProperty 天然允许，build_local_index_map 解析得到相同 index，完全正确。

byte-perfect 保证：
  - 死块（pointerized=False）：orig_b64 路径整体保留，完全不动。
  - 哨兵（none=True）：导出写 -1（0xFFFFFFFF 的有符号补码），与原始文件完全一致。
  - 有效指针（未变 extern）：extern 对象的 efx_index == 导出局部 index == 原值，byte-perfect。
"""

import struct
import bpy
from bpy.props import (
    BoolProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup, Operator

from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 常量：referenceIndex 在 data_bytes 中的字节偏移
# ─────────────────────────────────────────────────────────────────────────────

_REFERENCE_INDEX_OFFSET = 4   # bytes 4-7（int32 有符号，小端）
_SENTINEL_VALUE = -1          # 哨兵：无 extern 目标


# ─────────────────────────────────────────────────────────────────────────────
# §1  poll 函数
# ─────────────────────────────────────────────────────────────────────────────

def _find_root_obj(obj):
    """沿 parent 链向上找 ~TYPE == 'EFX_ROOT' 的对象，找不到返回 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _extern_object_poll(self, obj):
    """PointerProperty poll：只允许选 ~TYPE == 'EFX_EXTERN'，且限定为活动对象
    所在 EFX 文件（同一 EFX_ROOT）内的 extern——多 EFX 集合并存时防串文件。"""
    if obj.get("~TYPE") != "EFX_EXTERN":
        return False
    editing = getattr(bpy.context, "active_object", None)
    if editing is not None:
        root_self = _find_root_obj(editing)
        root_obj = _find_root_obj(obj)
        if root_self is not None and root_obj is not None and root_self is not root_obj:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# §2  PropertyGroup：ExternReference 指针存储
# ─────────────────────────────────────────────────────────────────────────────

class EFXExternRefProps(PropertyGroup):
    """
    挂在 EFX_BLOCK（EXTERNREFERENCE 类型）对象上（obj.efx_extern_ref）。

    字段
    ----
    extern_ref_ptr       : PointerProperty → EFX_EXTERN 对象（poll=EFX_EXTERN）
                           pointerized=True 且 none=False 时有效
    extern_ref_none      : BoolProperty   — True = referenceIndex == -1（哨兵/无目标）
    extern_ref_pointerized : BoolProperty — True = 已指针化（走新路径）；
                                           False = 死块（保持 orig_b64，byte-perfect 回退）
    """

    extern_ref_ptr: PointerProperty(
        name="Extern Reference",
        description="The EFX_EXTERN object this ExternReference block points to (the extern corresponding to referenceIndex)",
        type=bpy.types.Object,
        poll=_extern_object_poll,
    )

    extern_ref_none: BoolProperty(
        name="No Target (-1)",
        description="True = referenceIndex == -1 (sentinel, no extern target)",
        default=False,
    )

    extern_ref_pointerized: BoolProperty(
        name="Pointerized",
        description=(
            "True = referenceIndex has been pointerized (valid range / -1 sentinel); "
            "False = dead block / out of range, preserve original bytes (byte-perfect fallback)"
        ),
        default=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# §3  导入：从 data_bytes + extern 集合初始化 EFXExternRefProps
# ─────────────────────────────────────────────────────────────────────────────

def init_extern_ref_props(
    blk_obj: bpy.types.Object,
    data_bytes: bytes,
    extern_objs_by_index: dict,
    count_extern: int,
) -> None:
    """
    初始化 blk_obj.efx_extern_ref PropertyGroup。

    参数
    ----
    blk_obj : bpy.types.Object
        EFX_BLOCK Empty（EXTERNREFERENCE 类型）。
    data_bytes : bytes
        该块的 data_bytes（36 字节）。
    extern_objs_by_index : dict[int, bpy.types.Object]
        {efx_index → EFX_EXTERN 对象} 映射，由 import_efx_tree 构建。
    count_extern : int
        文件头的 count_extern 字段值（hdr.count_extern）。

    副作用
    ------
    填写 blk_obj.efx_extern_ref.{extern_ref_ptr, extern_ref_none, extern_ref_pointerized}。

    三种情况：
      1. 0 <= v < count_extern → ptr 指向 efx_index==v 的 EFX_EXTERN 对象；pointerized=True
      2. v == -1               → none=True；pointerized=True
      3. 越界/死块              → pointerized=False（保持 orig_b64，byte-perfect）
    """
    props = blk_obj.efx_extern_ref

    # 防御性检查：data_bytes 至少要有 8 字节（offset 4-7）
    if len(data_bytes) < 8:
        props.extern_ref_pointerized = False
        return

    # 读 referenceIndex（有符号 int32，小端）
    v = struct.unpack_from('<i', data_bytes, _REFERENCE_INDEX_OFFSET)[0]

    if v == _SENTINEL_VALUE:
        # 哨兵 -1：无目标，指针化路径标记 none
        props.extern_ref_none = True
        props.extern_ref_pointerized = True
        return

    if count_extern > 0 and 0 <= v < count_extern:
        # 有效范围：指向对应的 EFX_EXTERN 对象
        target_obj = extern_objs_by_index.get(v)
        if target_obj is not None:
            props.extern_ref_ptr = target_obj
            props.extern_ref_pointerized = True
        else:
            # 理论上不该发生（extern 对象已建但映射缺失），安全回退
            props.extern_ref_pointerized = False
        return

    # 死块/越界：count_extern=0 或 v >= count_extern 或其他异常值
    # 保持 pointerized=False → 导出走 orig_b64（byte-perfect）
    props.extern_ref_pointerized = False


# ─────────────────────────────────────────────────────────────────────────────
# §4  导出：根据 EFXExternRefProps 覆写 data_bytes 中的 referenceIndex
# ─────────────────────────────────────────────────────────────────────────────

def overlay_extern_ref_index(
    data_bytes: bytes,
    blk_obj: bpy.types.Object,
    extern_index_map: dict,
) -> bytes:
    """
    若 blk_obj.efx_extern_ref.extern_ref_pointerized==True，
    用指针解析结果覆写 data_bytes 中 referenceIndex 对应的 4 字节（偏移 4）。

    参数
    ----
    data_bytes : bytes
        已由 fields.get_block_data_bytes（或 orig_b64）得到的 EXTERNREFERENCE data_bytes。
    blk_obj : bpy.types.Object
        EFX_BLOCK Empty（EXTERNREFERENCE 类型）。
    extern_index_map : dict[bpy.types.Object, int]
        {EFX_EXTERN Object → extern 段局部 0-based index}，
        由 build_local_index_map(col_extern, 'EFX_EXTERN') 构建。

    返回
    ----
    bytes — 覆写后的 data_bytes（已替换 referenceIndex 4 字节）；
            不指针化则原样返回。

    注意
    ----
    - 使用 bytearray 做 pack_into，再转回 bytes（Python 3.11 兼容）。
    - 覆写操作：struct.pack_into('<i', buf, 4, new_index)。
    - 哨兵路径：none=True → 写 -1（struct pack '<i' 的 -1 = 0xFFFFFFFF 小端）。
    - 悬空指针（ptr=None 且 none=False）：静默返回原始字节（安全回退）。
    """
    try:
        props = blk_obj.efx_extern_ref
    except AttributeError:
        return data_bytes

    if not props.extern_ref_pointerized:
        # 死块/越界 → 不覆写，byte-perfect 原样返回
        return data_bytes

    # 计算新的 referenceIndex 值
    if props.extern_ref_none:
        new_index = _SENTINEL_VALUE  # -1
    else:
        # 从 extern_ref_ptr 经 extern_index_map 解析局部 index
        extern_obj = props.extern_ref_ptr
        if extern_obj is None:
            # 悬空指针：安全回退（不覆写）
            return data_bytes
        new_index = extern_index_map.get(extern_obj)
        if new_index is None:
            # extern_obj 不在当前文件的 Extern 段里（极端情况：跨文件等）
            return data_bytes

    # 覆写 data_bytes 中 referenceIndex 的 4 字节（偏移 4）
    if len(data_bytes) < 8:
        # 防御：字节太短，不覆写
        return data_bytes

    buf = bytearray(data_bytes)
    struct.pack_into('<i', buf, _REFERENCE_INDEX_OFFSET, new_index)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# §5  辅助：找 Extern 段集合 + 构建 extern_index_map
# ─────────────────────────────────────────────────────────────────────────────

def find_extern_collection(root_obj: bpy.types.Object):
    """
    从 EFX_ROOT 对象出发，找到 Extern 段集合（名含 '_1 Extern' 后缀）。

    返回 bpy.types.Collection 或 None（找不到时）。
    在导出时用于构建 extern_index_map。
    """
    for col in bpy.data.collections:
        if col.name.endswith("_1 Extern"):
            # 验证：root_obj 在此集合的上层集合里（宽松匹配）
            return col
    return None


def build_extern_index_map(extern_objs: list) -> dict:
    """
    构建 Extern 段局部索引映射：{EFX_EXTERN Object → 0-based local index}。

    参数
    ----
    extern_objs : list[bpy.types.Object]
        已按 efx_index 排序的 EFX_EXTERN 对象列表（与导出时 extern_raw 顺序一致）。

    返回
    ----
    dict[bpy.types.Object, int]

    注意：调用方传入的 extern_objs 应已按 efx_index 排序（int sort）。
    """
    return {obj: idx for idx, obj in enumerate(extern_objs)}


# ─────────────────────────────────────────────────────────────────────────────
# §6  算子：强制解锁死块（pointerized=False → pointerized=True + ptr=None）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_force_pointerize_extern_ref(Operator):
    """把死块/越界的 ExternReference 强制升级为悬空指针，以便手动重连 Extern 目标"""

    bl_idname  = "efx.force_pointerize_extern_ref"
    bl_label   = "Force Unlock (dangling)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
            return False
        try:
            from ..efx_format.hashes import EXTERNREFERENCE
            if int(str(obj.get("type_hash", ""))) != EXTERNREFERENCE:
                return False
            return not obj.efx_extern_ref.extern_ref_pointerized
        except (AttributeError, ValueError, ImportError):
            return False

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_extern_ref
        props.extern_ref_pointerized = True
        props.extern_ref_none        = False
        props.extern_ref_ptr         = None
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# §7  面板：ExternReference 块的 referenceIndex 指针编辑器
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_extern_ref(bpy.types.Panel):
    """
    ExternReference 块的 Extern 指针编辑面板（VIEW_3D N 面板 EFX 标签）。

    选中 EFX_BLOCK（EXTERNREFERENCE 类型）时显示：
      - pointerized=False：显示"死块/越界"警告（原始字节保留）
      - pointerized=True + none=False：EFX_EXTERN 对象选择器
      - pointerized=True + none=True：显示"无目标（-1 哨兵）"勾选
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "Extern Reference"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
            return False
        # 仅当 type_hash == EXTERNREFERENCE 时显示
        try:
            from ..efx_format.hashes import EXTERNREFERENCE
            bp = obj.efx_block
            return int(bp.type_hash_str) == EXTERNREFERENCE
        except (AttributeError, ValueError, ImportError):
            return False

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        try:
            props = obj.efx_extern_ref
        except AttributeError:
            layout.label(text=T("extern.no_data"), icon="ERROR")
            return

        if not props.extern_ref_pointerized:
            # 死块/越界：原始字节保留，只读提示 + 强制解锁按钮
            box = layout.box()
            box.label(text=T("extern.dead_title"), icon="ERROR")
            box.label(text=T("extern.dead_line1"))
            box.label(text=T("extern.dead_line2"))
            box.operator("efx.force_pointerize_extern_ref",
                         text=T("extern.force_unlock"), icon="UNLOCKED")
            return

        # 已指针化
        box = layout.box()
        box.label(text="Reference Index", icon="LINKED")

        # 无目标（-1 哨兵）勾选
        row = box.row(align=True)
        row.prop(props, "extern_ref_none", text=T("extern.no_target_sentinel"))

        if props.extern_ref_none:
            # none=True：没有 extern 目标，禁用指针选择器
            row2 = box.row(align=True)
            row2.enabled = False
            row2.prop(props, "extern_ref_ptr", text=T("extern.extern_object"))
        else:
            # 正常指针：显示 EFX_EXTERN 对象选择器
            row2 = box.row(align=True)
            row2.prop(props, "extern_ref_ptr", text=T("extern.extern_object"))

            # 悬空警告
            if props.extern_ref_ptr is None:
                warn = box.row()
                warn.alert = True
                warn.label(
                    text=T("extern.dangling"),
                    icon="ERROR",
                )
            else:
                # 显示 extern 的 efx_index（参考信息）
                ext_obj = props.extern_ref_ptr
                ext_idx = ext_obj.get("efx_index", "?")
                info = box.row()
                info.label(text=T("extern.local_index") + f" {ext_idx}", icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

# 注册顺序：PropertyGroup 先；Panel 依赖 EFX_PT_main（bl_parent_id），
# 由 panels.register() 在 EFX_PT_main 之后注册。
_CLASSES_CORE = (
    EFXExternRefProps,
    EFX_OT_force_pointerize_extern_ref,
)

# EFX_PT_extern_ref 导出给 panels.py，由 panels.register() 在 EFX_PT_main 之后注册。


def register():
    """
    注册 ExternRef 核心类（PropertyGroup）并把 EFXExternRefProps 挂到 Object 上。
    注意：EFX_PT_extern_ref 面板由 panels.py 在 EFX_PT_main 之后注册。
    """
    for cls in _CLASSES_CORE:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_extern_ref = PointerProperty(
        name="EFX Extern Reference Properties",
        description="Extern pointer data for EFX_BLOCK (EXTERNREFERENCE type)",
        type=EFXExternRefProps,
    )


def unregister():
    """
    注销 ExternRef 核心类并清理 PointerProperty。
    EFX_PT_extern_ref 由 panels.py 先注销。
    """
    try:
        del bpy.types.Object.efx_extern_ref
    except AttributeError:
        pass

    for cls in reversed(_CLASSES_CORE):
        bpy.utils.unregister_class(cls)
