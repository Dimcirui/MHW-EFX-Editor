"""绑定网格的 UV、TIML 与静态摆放驱动编排层。

驱动只作用于绑定网格，退出时由各自模块解除，不修改 EFX 数据。TIML 曲线本身始终可编辑；
此处的 TIML 开关仅让网格跟随对应句柄。各驱动仍由其所属模块的 enter/exit 算子实现。
"""

import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty

from .i18n import T

# 驱动项：(标识、enter、exit、启用属性、作用域属性)。
_DRIVERS = [
    ("uv",    "efx.uvc_preview_enter", "efx.uvc_preview_exit", "efx_drive_uv",    "efx_uvc_preview_all"),
    ("timl",  "efx.timl_edit_enter",   "efx.timl_edit_exit",   "efx_drive_timl",  "efx_timle_all_bodies"),
    ("place", "efx.mesh_align_enter",  "efx.mesh_align_exit",  "efx_drive_place", "efx_align_all_efx"),
]

# 旧 Scene 属性仅在注销时清理。
_LEGACY_PROPS = ("efx_prev_scope_all", "efx_prev_t_uvc", "efx_prev_t_timl",
                 "efx_prev_t_mesh", "efx_prev_t_es3d", "efx_es3d_preview_all")


def _op(idname):
    """'efx.foo_bar' → bpy.ops.efx.foo_bar。"""
    ns, name = idname.split(".", 1)
    return getattr(getattr(bpy.ops, ns), name)


def _try_poll(idname):
    try:
        return _op(idname).poll()
    except Exception:
        return False


def _any_active():
    """任一驱动挂着（用各自 exit 算子 poll == True 判定）。"""
    for _k, _en, ex, _t, _s in _DRIVERS:
        if _try_poll(ex):
            return True
    return False


class EFX_OT_mesh_drive_start(Operator):
    """按勾选给绑定网格挂上驱动（统一作用域）"""
    bl_idname = "efx.mesh_drive_start"
    bl_label = "Start Mesh Drive"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return not _any_active()

    def execute(self, context):
        scene = context.scene
        scope_all = getattr(scene, "efx_drive_scope_all", False)
        started = []
        for key, enter, _ex, tprop, sprop in _DRIVERS:
            if not getattr(scene, tprop, False):
                continue
            if sprop and hasattr(scene, sprop):
                try:
                    setattr(scene, sprop, scope_all)
                except Exception:
                    pass
            if _try_poll(enter):
                try:
                    _op(enter)()
                    started.append(key)
                except Exception as exc:
                    self.report({"WARNING"}, "%s: %s" % (key, exc))
        if not started:
            self.report({"WARNING"}, T("meshdrive.none_started"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("meshdrive.started").format(", ".join(started)))
        return {"FINISHED"}


class EFX_OT_mesh_drive_stop(Operator):
    """摘掉全部驱动，绑定网格回到不受 EFX 影响的状态"""
    bl_idname = "efx.mesh_drive_stop"
    bl_label = "Stop Mesh Drive"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _any_active()

    def execute(self, context):
        for key, _en, ex, _t, _s in _DRIVERS:
            if not _try_poll(ex):
                continue
            try:
                _op(ex)()
            except Exception as exc:
                self.report({"WARNING"}, "%s: %s" % (key, exc))
        self.report({"INFO"}, T("meshdrive.stopped"))
        return {"FINISHED"}


class EFX_PT_mesh_drive(Panel):
    """绑定网格驱动的父面板；其注册必须先于子面板。"""

    bl_idname = "EFX_PT_mesh_drive"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Mesh Drive"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active = _any_active()

        layout.label(text=T("meshdrive.hint"), icon="INFO")

        box = layout.box()
        box.label(text=T("meshdrive.scope"), icon="RESTRICT_SELECT_OFF")
        row = box.row()
        row.enabled = not active
        row.prop(scene, "efx_drive_scope_all", text=T("meshdrive.scope_all"))

        box = layout.box()
        box.label(text=T("meshdrive.drivers"), icon="OPTIONS")
        col = box.column(align=True)
        col.enabled = not active
        col.prop(scene, "efx_drive_uv",    text=T("meshdrive.d_uv"))
        col.prop(scene, "efx_drive_timl",  text=T("meshdrive.d_timl"))
        col.prop(scene, "efx_drive_place", text=T("meshdrive.d_place"))

        r = layout.row()
        r.scale_y = 1.4
        if active:
            r.operator("efx.mesh_drive_stop", text=T("meshdrive.stop"), icon="X")
            layout.label(text=T("meshdrive.stop_note"), icon="INFO")
        else:
            r.operator("efx.mesh_drive_start", text=T("meshdrive.start"), icon="PLAY")


_CLASSES = (EFX_OT_mesh_drive_start, EFX_OT_mesh_drive_stop, EFX_PT_mesh_drive)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    S = bpy.types.Scene
    S.efx_drive_scope_all = BoolProperty(
        name="All bodies in this EFX",
        description="Drive the bound mesh of every entry in this EFX (else the active entry only)",
        default=False)
    S.efx_drive_uv = BoolProperty(
        name="UV scroll", default=True,
        description="Scrolls the bound mesh's UVs from its UVCONTROL attributes (drives the material's Mapping node during timeline playback)")
    S.efx_drive_timl = BoolProperty(
        name="TIML animation", default=True,
        description="Makes the bound mesh follow the entry's TIML animation. The TIML curves themselves are always live in the Dope Sheet - this only attaches the mesh to them")
    S.efx_drive_place = BoolProperty(
        name="Static placement", default=False,
        description="Places the bound mesh by TRANSFORM3D + MESH rotation/scale, and re-places it live while those fields are edited")


def unregister():
    for attr in ("efx_drive_scope_all", "efx_drive_uv", "efx_drive_timl",
                 "efx_drive_place") + _LEGACY_PROPS:
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
