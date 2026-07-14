"""
blender_efx/timl_io.py  —  TIML 段 ↔ 独立 .timl 文件互导 + 句柄解析

实测：EFX 内嵌 entry.timl_bytes 与独立 .timl 文件 byte-identical（同 'timl' magic）。
本模块把 .timl 文件的导入/导出/增删自动化（供与外部工具交换，或归档）：

  - efx.export_entry_timl：把当前 TIML 的 timl_bytes 写成独立 .timl 文件。
  - efx.import_entry_timl：读 .timl 文件写回 timl_bytes（重算 timl_length，支持变长）。
  - efx.delete_entry_timl：清空 TIML 段。

timl 在 EFX 里由 timl_length 字段界定，故允许变长——导出端 io_tree 按 len(timl_bytes) 重算。
另提供 resolve_timl_entry()：把 EFX_TIML 句柄 / EFX_ENTRY 解析回所属 entry（TIML 统一入口）。
通道级编辑见 timl_edit.py（原生 F 曲线，自建）。

约束（CLAUDE.md）：Python 3.11、bpy 稳定子集、包内相对导入。
"""

import base64
import os

import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import StringProperty

from .i18n import T


_TIML_MAGIC = b"timl"


def resolve_timl_entry(obj):
    """把活动对象解析成所属 EFX_ENTRY：

    - EFX_TIML 句柄  → 其父 entry（TIML 统一入口）
    - EFX_ENTRY      → 自身（兼容直接选 entry，如给无 TIML 的 entry 添加）
    - 其他          → None
    """
    if obj is None:
        return None
    t = obj.get("~TYPE")
    if t == "EFX_TIML":
        return obj.parent
    if t == "EFX_ENTRY":
        return obj
    return None


def _entry_is_timl_capable(obj) -> bool:
    """该对象是否为「能携带 TIML 段」的 EFX_ENTRY（standard/extended）。

    注意：与 _entry_has_timl 不同，这里不要求 timl 非空——standard/extended entry
    的头部本来就有 timl_length 字段（0 = 无 TIML，是合法常态，官方 78 文件里
    750/982 个 standard entry 即 timl_length==0）。故"添加 TIML"对这些 entry 都成立。
    """
    if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
        return False
    return str(obj.get("entry_kind", "")) in ("standard", "extended")


def _entry_has_timl(obj) -> bool:
    """该对象是否为含**非空** timl 段的 EFX_ENTRY（用于 Replace/Delete/Export 门控）。"""
    if not _entry_is_timl_capable(obj):
        return False
    try:
        tb = base64.b64decode(str(obj.get("timl_bytes", "")))
    except Exception:
        return False
    return len(tb) > 0


def _entry_timl_bytes(obj) -> bytes:
    return base64.b64decode(str(obj.get("timl_bytes", "")))


def _default_timl_name(obj) -> str:
    """从 entry 的标签/名字生成默认 .timl 文件名（不含扩展名）。"""
    raw = str(obj.get("efx_raw_label", "")) or obj.name
    # 去非法文件名字符
    safe = "".join(c for c in raw if c not in '\\/:*?"<>|').strip()
    return safe or "timl_attribute"


# ─────────────────────────────────────────────────────────────────────────────
# 导出：entry.timl_bytes → 独立 .timl 文件
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_export_entry_timl(bpy.types.Operator, ExportHelper):
    """把当前 EFX_ENTRY 的 TIML 段导出为独立 .timl 文件"""

    bl_idname      = "efx.export_entry_timl"
    bl_label       = "Export as .timl File"
    bl_description = "Write the current EFX_ENTRY's embedded TIML segment to a standalone .timl file"
    bl_options     = {"REGISTER"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    @classmethod
    def poll(cls, context):
        return _entry_has_timl(resolve_timl_entry(context.active_object))

    def invoke(self, context, event):
        # 用 entry 标签预填默认文件名
        if not self.filepath:
            self.filepath = _default_timl_name(resolve_timl_entry(context.active_object)) + ".timl"
        return super().invoke(context, event)

    def execute(self, context):
        obj = resolve_timl_entry(context.active_object)
        if not _entry_has_timl(obj):
            self.report({"ERROR"}, "Current object is not an EFX_ENTRY containing TIML")
            return {"CANCELLED"}
        # 与主 .efx 导出同款新鲜度保证：若句柄有持久 fcurve，先把当前关键帧值同步回
        # 字节再导出——否则会导出 timl_bytes 的旧快照（导入时/上次结构编辑提交时），
        # 漏掉尚未触发 commit_fcurves_to_bytes 的实时关键帧编辑。
        try:
            from . import io_tree as _iot
            from . import timl_edit as _te
            h = _iot.find_timl_handle(obj)
            # 插值类型校验：不支持的缓动（Sine/Expo/Back…）阻止导出，BEZIER 仅提醒。
            if h is not None:
                issues = _te.check_timl_interpolations(h)
                errs = sorted({i["interp"] for i in issues if i["severity"] == "ERROR"})
                if errs:
                    self.report(
                        {"ERROR"},
                        f"TIML export blocked: unsupported interpolation ({', '.join(errs)}) — "
                        f"only {_te._SUPPORTED_INTERP_DESC} are supported by the game",
                    )
                    return {"CANCELLED"}
                if any(i["severity"] == "WARNING" for i in issues):
                    self.report({"WARNING"}, "BEZIER keyframes are approximated as Cubic on export")
            data = bytes(_te.sync_fcurves_to_bytes(h, obj)) if h is not None else _entry_timl_bytes(obj)
        except Exception:
            data = _entry_timl_bytes(obj)
        try:
            with open(self.filepath, "wb") as f:
                f.write(data)
        except OSError as exc:
            self.report({"ERROR"}, f"Failed to write file: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"TIML exported: {self.filepath} ({len(data)} bytes)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 导入：独立 .timl 文件 → entry.timl_bytes（重算 timl_length，支持变长）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_import_entry_timl(bpy.types.Operator, ImportHelper):
    """读 .timl 文件写入当前 EFX_ENTRY 的 TIML 段（添加新 TIML 或替换现有 TIML）"""

    bl_idname      = "efx.import_entry_timl"
    bl_label       = "Add / Replace TIML"
    bl_description = (
        "Read a .timl file and write it into the current EFX_ENTRY's TIML segment "
        "(adds one if the entry has none, or replaces the existing TIML). "
        "timl_length is recomputed automatically (variable length supported)."
    )
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    @classmethod
    def poll(cls, context):
        # 放宽到「能携带 TIML 的 entry」：无 TIML 时此算子用于"添加"
        return _entry_is_timl_capable(resolve_timl_entry(context.active_object))

    def execute(self, context):
        obj = resolve_timl_entry(context.active_object)
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            self.report({"ERROR"}, "Select an EFX_ENTRY containing TIML first")
            return {"CANCELLED"}
        if str(obj.get("entry_kind", "")) not in ("standard", "extended"):
            self.report({"ERROR"}, "This entry type does not contain a TIML segment")
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

        old_len = len(_entry_timl_bytes(obj))
        # grow-only 自动长度：导入 .timl 时把每条动画长度增长到末关键帧（per-entry 开关，默认开）。
        # 原地等长 patch，不改 timl 长度、不碰 byte-perfect。
        if obj.get("efx_timl_auto_grow", True):
            try:
                from ..efx_format import timl_meta as _tm
                data = _tm.auto_grow_lengths(data)
            except Exception:
                pass
        # 咽喉点：写字节 + 建句柄 + 从新字节重建持久 fcurve（替换整段 TIML → 新字节为准）
        from . import timl_edit as _te
        _te.set_entry_timl(obj, data)
        self.report(
            {"INFO"},
            f"TIML reimported: {len(data)} bytes (was {old_len}). timl_length is auto-recomputed on export.",
        )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 新建：从零生成空白 TIML（count=0，32 字节），用于不需要导入外部文件的情况
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_create_entry_timl(bpy.types.Operator):
    """为当前 EFX_ENTRY 新建一个空白 TIML 段（count=0，不含任何轨道）"""

    bl_idname      = "efx.create_entry_timl"
    bl_label       = "Create Blank TIML"
    bl_description = (
        "Create a minimal empty TIML segment (count=0) for this EFX_ENTRY. "
        "Use 'Enable Axis' in the EFX TIML panel to add A0/A1, then add tracks."
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _entry_is_timl_capable(resolve_timl_entry(context.active_object))

    def execute(self, context):
        obj = resolve_timl_entry(context.active_object)
        if obj is None or obj.get("~TYPE") != "EFX_ENTRY":
            self.report({"ERROR"}, "Select an EFX_ENTRY first")
            return {"CANCELLED"}
        if str(obj.get("entry_kind", "")) not in ("standard", "extended"):
            self.report({"ERROR"}, "This entry type does not support a TIML segment")
            return {"CANCELLED"}
        if _entry_has_timl(obj):
            self.report({"WARNING"}, "Entry already has a TIML segment — use Replace to overwrite")
            return {"CANCELLED"}

        from ..efx_format.timl import make_blank_timl
        data = make_blank_timl()
        # 咽喉点：新建 → 写字节 + 建句柄（空 TIML 无动画，不建 fcurve，符合预期）
        from . import timl_edit as _te
        _te.set_entry_timl(obj, data)
        self.report({"INFO"}, f"Blank TIML created ({len(data)} bytes). Use EFX TIML panel to enable axes.")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 删除：清空 entry 的 TIML 段（timl_bytes="" → 导出端 timl_length 重算为 0）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_delete_entry_timl(bpy.types.Operator):
    """删除当前 EFX_ENTRY 的 TIML 段（清空字节，导出时 timl_length 归 0）"""

    bl_idname      = "efx.delete_entry_timl"
    bl_label       = "Delete TIML"
    bl_description = (
        "Remove this EFX_ENTRY's TIML segment entirely (clears the bytes; "
        "timl_length is recomputed to 0 on export). timl_length=0 is a valid, common state"
    )
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _entry_has_timl(resolve_timl_entry(context.active_object))

    def execute(self, context):
        obj = resolve_timl_entry(context.active_object)
        if not _entry_has_timl(obj):
            self.report({"ERROR"}, "Current object is not an EFX_ENTRY containing TIML")
            return {"CANCELLED"}
        old_len = len(_entry_timl_bytes(obj))
        # 咽喉点：删除 → 清空字节 + 删句柄+持久 Action
        from . import timl_edit as _te
        _te.set_entry_timl(obj, b"")
        self.report({"INFO"}, f"TIML deleted ({old_len} bytes removed). timl_length=0.")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板：EFX_PT_entry_timl（Entry 面板下的子栏，与激活/References 同级）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_entry_timl(bpy.types.Panel):
    """EFX 的 TIML 段管理（添加/替换/删除/导出 .timl + 进入通道编辑）"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "TIML"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        # TIML 统一入口：选中 EFX_TIML 句柄或能携带 TIML 的 entry 都显示（无 TIML 时提供"添加"）
        return _entry_is_timl_capable(resolve_timl_entry(context.active_object))

    def draw(self, context):
        layout = self.layout
        obj = resolve_timl_entry(context.active_object)
        has = _entry_has_timl(obj)

        # 段状态行
        if has:
            n = len(_entry_timl_bytes(obj))
            layout.label(text=T("timl.segment_bytes").format(n=n), icon="ANIM")
        else:
            layout.label(text=T("timl.none"), icon="DOT")

        col = layout.column(align=True)

        if not has:
            # 无 TIML：两种添加方式并列
            row = col.row(align=True)
            row.operator("efx.import_entry_timl", text=T("timl.import_file_btn"), icon="FILEBROWSER")
            row.operator("efx.create_entry_timl", text=T("timl.create_blank_btn"), icon="ADD")
        else:
            # 有 TIML：替换（从文件）+ 删除
            row = col.row(align=True)
            row.operator("efx.import_entry_timl", text=T("timl.replace_file_btn"), icon="FILE_REFRESH")
            row.operator("efx.delete_entry_timl", text=T("timl.delete_btn"), icon="TRASH")
            # 导出
            col.operator("efx.export_entry_timl", text=T("timl.export_btn"), icon="EXPORT")

        layout.label(text=T("timl.hint"), icon="INFO")

        # ── 通道编辑（点1：编辑入口归入 TIML 栏目）──────────────────────────────
        if has:
            layout.separator()
            try:
                from . import timl_edit as _te
                _te.draw_edit_controls(layout, context)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_export_entry_timl,
    EFX_OT_import_entry_timl,
    EFX_OT_create_entry_timl,
    EFX_OT_delete_entry_timl,
    EFX_PT_entry_timl,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
