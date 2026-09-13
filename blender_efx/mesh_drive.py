"""
blender_efx/mesh_drive.py  —  绑定网格驱动「Mesh Drive」

这个面板管的是**entry 绑定的那个 mod3 网格对象**，不是特效本身的预览。特效长什么样
去看 Particle Simulation 面板；这里三个开关只决定「那个真实的网格对象，按 EFX 里的
哪些属性动起来」：

    UV 滚动     UVCONTROL      →  驱动网格材质的 Mapping 节点     (efx.uvc_preview_*)
    TIML 动画   TIML 句柄      →  网格加 Child-Of 跟随句柄动画    (efx.timl_edit_*)
    静态摆放    TRANSFORM3D+MESH → 网格摆到该 entry 的位姿        (efx.mesh_align_*)

三项都是「往场景对象上挂驱动」，退出即解挂，本身不改任何 EFX 数据。

由来（0.7.1）
-------------
本模块前身是「EFX Preview」——四个预览会话的统一入口。其中 ES3D 那项已退休（生成区域
改由粒子模拟的线框叠加层画）；余下三项全都只作用于绑定网格，跟「预览特效」没有关系，
故整体改名并按驱动类型重述。

⚠ TIML 这项**不包含**「让 TIML 动起来」——TIML 曲线在导入时就持久化到句柄上了，拖时间轴
就播，Dope Sheet 里随时可改、改完就是最终值。这个开关加的只是「让绑定网格跟着句柄跑」。

实现为**编排层**：按勾选调用各模块既有的 enter/exit 算子，不重写各自的会话引擎。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层。
"""

import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty

from .i18n import T

# 驱动项 → (标识, enter 算子, exit 算子, 勾选 Scene 属性名, 该模块作用域 Scene 属性名|None)
_DRIVERS = [
    ("uv",    "efx.uvc_preview_enter", "efx.uvc_preview_exit", "efx_drive_uv",    "efx_uvc_preview_all"),
    ("timl",  "efx.timl_edit_enter",   "efx.timl_edit_exit",   "efx_drive_timl",  "efx_timle_all_bodies"),
    ("place", "efx.mesh_align_enter",  "efx.mesh_align_exit",  "efx_drive_place", "efx_align_all_efx"),
]

#: 0.7.1 之前的 Scene 属性名（「EFX Preview」时期）。只在 unregister 里清理，不再读写。
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


# ─────────────────────────────────────────────────────────────────────────────
# Operators：挂上 / 摘掉
# ─────────────────────────────────────────────────────────────────────────────

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
            # 把统一作用域写进各模块自己的作用域开关
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


# ─────────────────────────────────────────────────────────────────────────────
# Panel
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_mesh_drive(Panel):
    """绑定网格驱动。`EFX_PT_mesh_binding`（选谁当绑定网格）用 bl_parent_id 挂在下面。

    ⚠ 子面板要求父面板先注册——本模块的 register() 必须排在 uvc_preview / mesh_align
    之前，unregister() 则相反（见 blender_efx/__init__.py 的注册顺序注释）。
    """

    bl_idname = "EFX_PT_mesh_drive"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Mesh Drive"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active = _any_active()

        layout.label(text=T("meshdrive.hint"), icon="INFO")

        # ── 作用域 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("meshdrive.scope"), icon="RESTRICT_SELECT_OFF")
        row = box.row()
        row.enabled = not active
        row.prop(scene, "efx_drive_scope_all", text=T("meshdrive.scope_all"))

        # ── 驱动项 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("meshdrive.drivers"), icon="OPTIONS")
        col = box.column(align=True)
        col.enabled = not active
        col.prop(scene, "efx_drive_uv",    text=T("meshdrive.d_uv"))
        col.prop(scene, "efx_drive_timl",  text=T("meshdrive.d_timl"))
        col.prop(scene, "efx_drive_place", text=T("meshdrive.d_place"))

        # ── 总开关 ─────────────────────────────────────────────────────────────
        r = layout.row()
        r.scale_y = 1.4
        if active:
            r.operator("efx.mesh_drive_stop", text=T("meshdrive.stop"), icon="X")
            layout.label(text=T("meshdrive.stop_note"), icon="INFO")
        else:
            r.operator("efx.mesh_drive_start", text=T("meshdrive.start"), icon="PLAY")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

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
