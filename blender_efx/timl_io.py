"""
blender_efx/timl_io.py  —  TIML 块 ↔ 独立 .timl 文件互导（方案 C：松耦合 FreeKinetics 桥）

实测：EFX 内嵌 body.timl_bytes 与独立 .timl 文件 byte-identical（同 'timl' magic）。
故无需引入 FreeKinetics API，只把"手动 hex 复制 + 改长度"自动化：

  - efx.export_body_timl：把当前 EFX_BODY 的 timl_bytes 写成独立 .timl 文件。
  - efx.import_body_timl：读 .timl 文件写回当前 body 的 timl_bytes（重算 timl_length，支持变长）。

中间用户用 FreeKinetics 正常的 import_timl / export 编辑那个 .timl 文件。
零 FK 版本耦合。timl 在 EFX 里由 timl_length 字段界定，故允许变长（FK 加关键帧后变长 OK）——
导出端 io_tree 已改为 timl_length = len(timl_bytes) 重算。

约束（CLAUDE.md）：Python 3.11、bpy 稳定子集、包内相对导入。
"""

import base64
import os

import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import StringProperty

from .i18n import T


_TIML_MAGIC = b"timl"


def _body_is_timl_capable(obj) -> bool:
    """该对象是否为「能携带 TIML 段」的 EFX_BODY（standard/extended）。

    注意：与 _body_has_timl 不同，这里不要求 timl 非空——standard/extended body
    的头部本来就有 timl_length 字段（0 = 无 TIML，是合法常态，官方 78 文件里
    750/982 个 standard body 即 timl_length==0）。故"添加 TIML"对这些 body 都成立。
    """
    if obj is None or obj.get("~TYPE") != "EFX_BODY":
        return False
    return str(obj.get("body_kind", "")) in ("standard", "extended")


def _body_has_timl(obj) -> bool:
    """该对象是否为含**非空** timl 段的 EFX_BODY（用于 Replace/Delete/Export 门控）。"""
    if not _body_is_timl_capable(obj):
        return False
    try:
        tb = base64.b64decode(str(obj.get("timl_bytes", "")))
    except Exception:
        return False
    return len(tb) > 0


def _body_timl_bytes(obj) -> bytes:
    return base64.b64decode(str(obj.get("timl_bytes", "")))


def _default_timl_name(obj) -> str:
    """从 body 的标签/名字生成默认 .timl 文件名（不含扩展名）。"""
    raw = str(obj.get("efx_raw_label", "")) or obj.name
    # 去非法文件名字符
    safe = "".join(c for c in raw if c not in '\\/:*?"<>|').strip()
    return safe or "timl_block"


# ─────────────────────────────────────────────────────────────────────────────
# 导出：body.timl_bytes → 独立 .timl 文件
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_export_body_timl(bpy.types.Operator, ExportHelper):
    """把当前 EFX_BODY 的 TIML 段导出为独立 .timl 文件（供 FreeKinetics 编辑）"""

    bl_idname      = "efx.export_body_timl"
    bl_label       = "Export as .timl File"
    bl_description = "Write the current EFX_BODY's embedded TIML segment to a standalone .timl file, openable in FreeKinetics for editing"
    bl_options     = {"REGISTER"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    @classmethod
    def poll(cls, context):
        return _body_has_timl(context.active_object)

    def invoke(self, context, event):
        # 用 body 标签预填默认文件名
        if not self.filepath:
            self.filepath = _default_timl_name(context.active_object) + ".timl"
        return super().invoke(context, event)

    def execute(self, context):
        obj = context.active_object
        if not _body_has_timl(obj):
            self.report({"ERROR"}, "Current object is not an EFX_BODY containing TIML")
            return {"CANCELLED"}
        data = _body_timl_bytes(obj)
        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to write file: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"TIML exported: {self.filepath} ({len(data)} bytes)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 导入：独立 .timl 文件 → body.timl_bytes（重算 timl_length，支持变长）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_import_body_timl(bpy.types.Operator, ImportHelper):
    """读 .timl 文件写入当前 EFX_BODY 的 TIML 段（添加新 TIML 或替换现有 TIML）"""

    bl_idname      = "efx.import_body_timl"
    bl_label       = "Add / Replace TIML"
    bl_description = (
        "Read a .timl file and write it into the current EFX_BODY's TIML segment "
        "(adds one if the body has none, or replaces the existing TIML). "
        "timl_length is recomputed automatically (variable length supported). "
        "Edit the .timl externally in FreeKinetics"
    )
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    @classmethod
    def poll(cls, context):
        # 放宽到「能携带 TIML 的 body」：无 TIML 时此算子用于"添加"
        return _body_is_timl_capable(context.active_object)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EFX_BODY":
            self.report({"ERROR"}, "Select an EFX_BODY containing TIML first")
            return {"CANCELLED"}
        if str(obj.get("body_kind", "")) not in ("standard", "extended"):
            self.report({"ERROR"}, "This body type does not contain a TIML segment")
            return {"CANCELLED"}
        try:
            with open(self.filepath, "rb") as f:
                data = f.read()
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to read file: {exc}")
            return {"CANCELLED"}

        if data[:4] != _TIML_MAGIC:
            self.report(
                {"ERROR"},
                f"Not a valid .timl file (magic should be 'timl', got {data[:4]!r})",
            )
            return {"CANCELLED"}

        old_len = len(_body_timl_bytes(obj))
        obj["timl_bytes"]  = base64.b64encode(data).decode("ascii")
        obj["timl_length"] = str(len(data))  # 重算长度（导出端也会再重算，双保险）
        self.report(
            {"INFO"},
            f"TIML reimported: {len(data)} bytes (was {old_len}). timl_length is auto-recomputed on export.",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 删除：清空 body 的 TIML 段（timl_bytes="" → 导出端 timl_length 重算为 0）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_body_timl(bpy.types.Operator):
    """删除当前 EFX_BODY 的 TIML 段（清空字节，导出时 timl_length 归 0）"""

    bl_idname      = "efx.delete_body_timl"
    bl_label       = "Delete TIML"
    bl_description = (
        "Remove this EFX_BODY's TIML segment entirely (clears the bytes; "
        "timl_length is recomputed to 0 on export). timl_length=0 is a valid, common state"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _body_has_timl(context.active_object)

    def execute(self, context):
        obj = context.active_object
        if not _body_has_timl(obj):
            self.report({"ERROR"}, "Current object is not an EFX_BODY containing TIML")
            return {"CANCELLED"}
        old_len = len(_body_timl_bytes(obj))
        obj["timl_bytes"]  = ""    # base64 of empty = b""
        obj["timl_length"] = "0"   # 导出端也会再重算，双保险
        self.report({"INFO"}, f"TIML deleted ({old_len} bytes removed). timl_length=0.")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板：EFX_PT_body_timl（Body 面板下的子栏，与激活/References 同级）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_body_timl(bpy.types.Panel):
    """EFX Body 的 TIML 段管理（添加/替换/删除/导出 .timl，配合 FreeKinetics）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "TIML"
    bl_parent_id    = "EFX_PT_body_properties"  # Body Properties 子栏（与 Unkn Attributes 同级）
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        # 能携带 TIML 的 body 都显示（无 TIML 时提供"添加"）
        return _body_is_timl_capable(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        has = _body_has_timl(obj)

        # 段状态行
        if has:
            n = len(_body_timl_bytes(obj))
            layout.label(text=T("timl.segment_bytes").format(n=n), icon="ANIM")
        else:
            layout.label(text=T("timl.none"), icon="DOT")

        col = layout.column(align=True)

        # 第一排：Add/Replace（按是否有 TIML 切换文案）+ Delete（无 TIML 时禁用）
        row = col.row(align=True)
        add_replace_text = T("timl.replace_btn") if has else T("timl.add_btn")
        row.operator("efx.import_body_timl", text=add_replace_text,
                     icon="FILE_REFRESH" if has else "ADD")
        del_sub = row.row(align=True)
        del_sub.enabled = has
        del_sub.operator("efx.delete_body_timl", text=T("timl.delete_btn"), icon="TRASH")

        # 第二排：导出（无 TIML 时禁用）
        exp_row = col.row(align=True)
        exp_row.enabled = has
        exp_row.operator("efx.export_body_timl", text=T("timl.export_btn"), icon="EXPORT")

        layout.label(text=T("timl.hint"), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_export_body_timl,
    EFX_OT_import_body_timl,
    EFX_OT_delete_body_timl,
    EFX_PT_body_timl,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
