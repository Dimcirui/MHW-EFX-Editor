"""在 Entry TIML 字节与独立 .timl 文件之间导入、导出。

维护约束：TIML 可变长，写回时必须同步 ``timl_length``；TIML 句柄、Entry 与属性
入口均须解析到同一字节载体。导出前先同步持久 F-Curve，失败时回退已存字节。
独立打开的 TIML 不隶属任何 EFX 根集合。
"""

import base64
import os

import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import BoolProperty, CollectionProperty, StringProperty

from .i18n import T


_TIML_MAGIC = b"timl"


def _poll_msg(cls, msg) -> None:
    """在支持时为禁用的菜单或按钮提供原因。"""
    setter = getattr(cls, "poll_message_set", None)
    if setter is not None:
        setter(msg)


def is_standalone_timl(obj) -> bool:
    """判断对象是否为自身承载字节、无 parent 的独立 TIML 句柄。"""
    return (
        obj is not None
        and obj.get("~TYPE") == "EFX_TIML"
        and obj.parent is None
    )


def resolve_timl_entry(obj):
    """将 TIML 句柄、Entry 或属性解析为 TIML 字节载体。"""
    if obj is None:
        return None
    t = obj.get("~TYPE")
    if t == "EFX_TIML":
        return obj.parent if obj.parent is not None else obj
    if t == "EFX_ENTRY":
        return obj
    if t == "EFX_ATTRIBUTE":
        # 父链深度限制避免异常层级阻塞 UI。
        cur, depth = obj.parent, 0
        while cur is not None and depth < 8:
            if cur.get("~TYPE") == "EFX_ENTRY":
                return cur
            cur, depth = cur.parent, depth + 1
    return None


def _entry_is_timl_capable(obj) -> bool:
    """判断对象能否承载 TIML；空 TIML 的标准和扩展 Entry 仍可写入。"""
    if obj is None:
        return False
    if is_standalone_timl(obj):
        return True
    if obj.get("~TYPE") != "EFX_ENTRY":
        return False
    return str(obj.get("entry_kind", "")) == "standard"


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
    safe = "".join(c for c in raw if c not in '\\/:*?"<>|').strip()
    return safe or "timl_attribute"


# ─────────────────────────────────────────────────────────────────────────────
# 导出：entry.timl_bytes → 独立 .timl 文件
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_export_entry_timl(bpy.types.Operator, ExportHelper):
    """将当前 TIML 字节导出为独立 .timl 文件。"""

    bl_idname      = "efx.export_entry_timl"
    bl_label       = "Export as .timl File"
    bl_description = "Write the current EFX_ENTRY's embedded TIML segment to a standalone .timl file"
    bl_options     = {"REGISTER"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    @classmethod
    def poll(cls, context):
        ok = _entry_has_timl(resolve_timl_entry(context.active_object))
        if not ok:
            _poll_msg(cls, "Select an EFX entry (or its TIML handle) that has a TIML segment")
        return ok

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = _default_timl_name(resolve_timl_entry(context.active_object)) + ".timl"
        return super().invoke(context, event)

    def execute(self, context):
        obj = resolve_timl_entry(context.active_object)
        if not _entry_has_timl(obj):
            self.report({"ERROR"}, "Current object is not an EFX_ENTRY containing TIML")
            return {"CANCELLED"}
        # 持久曲线须先同步，避免导出过期字节。
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
        except OSError:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"Failed to write '{self.filepath}'. Check disk space and "
                                    "whether the file is open in another program.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"TIML exported: {self.filepath} ({len(data)} bytes)")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 导入：独立 .timl 文件 → entry.timl_bytes（重算 timl_length，支持变长）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_import_entry_timl(bpy.types.Operator, ImportHelper):
    """将 .timl 写入可承载的 Entry，或作为独立 TIML 打开。"""

    bl_idname      = "efx.import_entry_timl"
    bl_label       = "Add / Replace TIML"
    bl_description = (
        "Read a .timl file. With an EFX entry selected it goes into that entry's TIML "
        "segment (added if absent, replaced if present); otherwise it opens standalone, "
        "with no .efx involved. timl_length is recomputed automatically (variable length "
        "supported)."
    )
    bl_options     = {"REGISTER", "UNDO"}

    filename_ext = ".timl"
    filter_glob: StringProperty(default="*.timl", options={"HIDDEN"}, maxlen=255)

    # FileHandler 传入 directory/files，菜单入口传入 filepath。
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    # 该值由当前目标计算，不能复用上一次调用的状态。
    standalone: BoolProperty(
        name="Standalone (no .efx)",
        description="Open the .timl on its own instead of writing it into a selected entry",
        default=False,
        options={"SKIP_SAVE"},
    )

    def _target_entry(self, context):
        """本次导入要写进的 entry；无主模式或没有合适目标时返回 None。"""
        if self.standalone:
            return None
        obj = resolve_timl_entry(context.active_object)
        return obj if _entry_is_timl_capable(obj) else None

    def _resolve_path(self) -> str:
        """拖入路径优先用 directory+files，菜单/按钮路径用 ImportHelper 的 filepath。"""
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    return os.path.join(self.directory, f.name)
        return self.filepath

    def invoke(self, context, event):
        self.standalone = not _entry_is_timl_capable(resolve_timl_entry(context.active_object))
        # 拖放替换需要确认；不能再次打开文件浏览器。
        if self.directory and self.files:
            return context.window_manager.invoke_props_dialog(self)
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        entry = resolve_timl_entry(context.active_object)
        capable = _entry_is_timl_capable(entry)
        layout.label(text=os.path.basename(self._resolve_path()), icon="ANIM")
        row = layout.row()
        row.enabled = capable
        row.prop(self, "standalone")
        if self.standalone or not capable:
            layout.label(text="Opens on its own (no .efx)", icon="UNLINKED")
        else:
            verb = "Replace TIML of" if _entry_has_timl(entry) else "Add TIML to"
            layout.label(text="%s: %s" % (verb, entry.name), icon="OUTLINER_OB_EMPTY")

    def execute(self, context):
        path = self._resolve_path()
        if not path:
            self.report({"ERROR"}, "TIML import: no file path specified")
            return {"CANCELLED"}
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"Failed to read '{path}'. See the system console for details.")
            return {"CANCELLED"}

        if data[:4] != _TIML_MAGIC:
            self.report(
                {"ERROR"},
                f"Not a valid .timl file (magic should be 'timl', got {data[:4]!r})",
            )
            return {"CANCELLED"}

        obj = self._target_entry(context)
        standalone = obj is None
        if standalone:
            from . import standalone as _sa
            base = os.path.splitext(os.path.basename(path))[0] or "timl"
            obj = _sa.new_timl_host(base, context)
            obj["efx_raw_label"] = base
            obj["efx_source_path"] = path
            old_len = 0
        else:
            old_len = len(_entry_timl_bytes(obj))

        # 自动增长仅更新动画长度字段，不改变 TIML 总长度。
        if obj.get("efx_timl_auto_grow", True):
            try:
                from ..efx_format.timl import meta as _tm
                data = _tm.auto_grow_lengths(data)
            except Exception:
                pass
        # 统一写回入口负责句柄与持久曲线重建。
        from . import timl_edit as _te
        _te.set_entry_timl(obj, data)
        if standalone:
            self.report({"INFO"}, f"TIML opened standalone: {os.path.basename(path)} ({len(data)} bytes)")
        else:
            self.report(
                {"INFO"},
                f"TIML reimported: {len(data)} bytes (was {old_len}). timl_length is auto-recomputed on export.",
            )
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
class EFX_OT_create_entry_timl(bpy.types.Operator):
    """为当前 Entry 创建最小空 TIML 段。"""

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
        if str(obj.get("entry_kind", "")) != "standard":
            self.report({"ERROR"}, "This entry type does not support a TIML segment")
            return {"CANCELLED"}
        if _entry_has_timl(obj):
            self.report({"WARNING"}, "Entry already has a TIML segment — use Replace to overwrite")
            return {"CANCELLED"}

        from ..efx_format.timl import make_blank_timl
        data = make_blank_timl()
        from . import timl_edit as _te
        _te.set_entry_timl(obj, data)
        self.report({"INFO"}, f"Blank TIML created ({len(data)} bytes). Use EFX TIML panel to enable axes.")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
class EFX_OT_delete_entry_timl(bpy.types.Operator):
    """清空当前 Entry 的 TIML 字节。"""

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
        from . import timl_edit as _te
        _te.set_entry_timl(obj, b"")
        self.report({"INFO"}, f"TIML deleted ({old_len} bytes removed). timl_length=0.")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
class EFX_PT_entry_timl(bpy.types.Panel):
    """管理 Entry TIML 段及其通道编辑入口。"""

    bl_space_type   = "VIEW_3D"
    bl_region_type  = "UI"
    bl_category     = "EFX"
    bl_label        = "TIML"
    bl_options      = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        # 颜色编辑器不显示关键帧动画操作。
        obj = resolve_timl_entry(context.active_object)
        from . import root_collection as _rc
        return _entry_is_timl_capable(obj) and not _rc.is_color_editor_mode(obj)

    def draw(self, context):
        layout = self.layout
        obj = resolve_timl_entry(context.active_object)
        has = _entry_has_timl(obj)

        from . import standalone as _sa
        _sa.draw_standalone_header(layout, obj)

        if has:
            n = len(_entry_timl_bytes(obj))
            layout.label(text=T("timl.segment_bytes").format(n=n), icon="ANIM")
        else:
            layout.label(text=T("timl.none"), icon="DOT")

        col = layout.column(align=True)

        if not has:
            row = col.row(align=True)
            row.operator("efx.import_entry_timl", text=T("timl.import_file_btn"), icon="FILEBROWSER")
            row.operator("efx.create_entry_timl", text=T("timl.create_blank_btn"), icon="ADD")
        else:
            row = col.row(align=True)
            row.operator("efx.import_entry_timl", text=T("timl.replace_file_btn"), icon="FILE_REFRESH")
            row.operator("efx.delete_entry_timl", text=T("timl.delete_btn"), icon="TRASH")
            col.operator("efx.export_entry_timl", text=T("timl.export_btn"), icon="EXPORT")

        layout.label(text=T("timl.hint"), icon="INFO")

        if has:
            layout.separator()
            try:
                from . import timl_edit as _te
                _te.draw_edit_controls(layout, context)
            except Exception:
                pass


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
