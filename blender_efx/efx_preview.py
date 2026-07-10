"""
blender_efx/efx_preview.py  —  统一预览面板「EFX Preview」（点5：整合分散的预览入口）

把原本分散的三类预览/会话收进一个面板，用「总开关 + 两块勾选」驱动：
  - 作用域块：是否扩大到本 EFX 全部特效体（默认仅当前）。
  - 目标块（勾选要启用哪些）：
      · Effect (UV) —— UVCONTROL 视口 UV 滚动预览（efx.uvc_preview_*）
      · TIML       —— 原生 TIML 通道编辑（含 transform3d 视口播放，efx.timl_edit_*）
      · Mesh Align —— 绑定网格随 TRANSFORM3D+MESH 实时对齐（efx.mesh_align_*）

实现为**编排层**：总开关按勾选调用各模块既有的 enter/exit 算子（复用已验证逻辑，不重写各自
会话引擎）。各模块原有面板暂保留（本面板是加法）；后续可据实测决定是否隐藏个别旧面板。

⚠ TIML 项启用 = 进入**通道编辑会话**（不是只读浏览）——视口会播放，但 Apply 才回写、Cancel 丢弃。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层。
"""

import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty

from .i18n import T

# 目标 → (enter 算子, exit 算子, 勾选 Scene 属性名, 该模块作用域 Scene 属性名|None)
_TARGETS = [
    ("uvc",  "efx.uvc_preview_enter", "efx.uvc_preview_exit", "efx_prev_t_uvc",  "efx_uvc_preview_all"),
    ("timl", "efx.timl_edit_enter",   "efx.timl_edit_exit",   "efx_prev_t_timl", "efx_timle_all_bodies"),
    ("mesh", "efx.mesh_align_enter",  "efx.mesh_align_exit",   "efx_prev_t_mesh", "efx_align_all_efx"),
    ("es3d", "efx.es3d_preview_enter", "efx.es3d_preview_exit", "efx_prev_t_es3d", "efx_es3d_preview_all"),
]


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
    """任一目标会话进行中（用各自 exit 算子 poll == True 判定）。"""
    for _, _en, ex, _t, _s in _TARGETS:
        if _try_poll(ex):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Operators：总开关 进入 / 退出
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_preview_enter(Operator):
    """按勾选启用所选预览（统一作用域 + 目标）"""
    bl_idname = "efx.preview_enter"
    bl_label = "Enter EFX Preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return not _any_active()

    def execute(self, context):
        scene = context.scene
        scope_all = getattr(scene, "efx_prev_scope_all", False)
        started = []
        for key, enter, _ex, tprop, sprop in _TARGETS:
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
            self.report({"WARNING"}, T("efxprev.none_started"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("efxprev.started").format(", ".join(started)))
        return {"FINISHED"}


class EFX_OT_preview_exit(Operator):
    """退出所有进行中的预览/会话（纯预览：一律丢弃，不回写）"""
    bl_idname = "efx.preview_exit"
    bl_label = "Exit EFX Preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _any_active()

    def execute(self, context):
        # 预览定位为只读：TIML 编辑会话以 discard 退出（不回写）；其余直接退出。
        for key, _en, ex, _t, _s in _TARGETS:
            if not _try_poll(ex):
                continue
            try:
                if key == "timl":
                    _op(ex)(apply=False)
                else:
                    _op(ex)()
            except Exception as exc:
                self.report({"WARNING"}, "%s: %s" % (key, exc))
        self.report({"INFO"}, T("efxprev.exited"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_efx_preview(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "EFX Preview"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        active = _any_active()

        # ── 作用域块 ───────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("efxprev.scope"), icon="RESTRICT_SELECT_OFF")
        row = box.row()
        row.enabled = not active
        row.prop(scene, "efx_prev_scope_all", text=T("efxprev.scope_all"))

        # ── 目标块 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("efxprev.targets"), icon="OPTIONS")
        col = box.column(align=True)
        col.enabled = not active
        col.prop(scene, "efx_prev_t_uvc",  text=T("efxprev.t_uvc"))
        col.prop(scene, "efx_prev_t_timl", text=T("efxprev.t_timl"))
        col.prop(scene, "efx_prev_t_mesh", text=T("efxprev.t_mesh"))
        col.prop(scene, "efx_prev_t_es3d", text=T("efxprev.t_es3d"))

        # ── 总开关 ─────────────────────────────────────────────────────────────
        if active:
            r = layout.row(); r.scale_y = 1.4
            r.operator("efx.preview_exit", text=T("efxprev.exit"), icon="X")
            layout.label(text=T("efxprev.discard_note"), icon="INFO")
        else:
            r = layout.row(); r.scale_y = 1.4
            r.operator("efx.preview_enter", text=T("efxprev.enter"), icon="PLAY")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (EFX_OT_preview_enter, EFX_OT_preview_exit, EFX_PT_efx_preview)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    S = bpy.types.Scene
    S.efx_prev_scope_all = BoolProperty(
        name="All entries in this EFX",
        description="Apply preview to every entry in the current EFX (else active only)",
        default=False)
    S.efx_prev_t_uvc = BoolProperty(name="UVCONTROL UV scroll", default=True,
                                    description="Previews ONLY UVCONTROL attributes' UV scroll (drives the bound mesh's Mapping node during playback)")
    S.efx_prev_t_timl = BoolProperty(name="TIML transform playback", default=True,
                                     description="Plays the TIML transform3d animation in the viewport (read-only here; edits are discarded on exit)")
    S.efx_prev_t_mesh = BoolProperty(name="Mesh placement", default=False,
                                     description="Places bound mesh instances by TRANSFORM3D + MESH rotation/scale (static placement, re-aligns live when those fields are edited)")
    S.efx_prev_t_es3d = BoolProperty(name="EmitterShape3D shape", default=False,
                                     description="Shows a transparent shape (cube/sphere/ring/spot) for each EmitterShape3D attribute, sized by its fields (live update when edited)")


def unregister():
    for attr in ("efx_prev_scope_all", "efx_prev_t_uvc", "efx_prev_t_timl", "efx_prev_t_mesh", "efx_prev_t_es3d"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
