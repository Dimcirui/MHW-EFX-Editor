# -*- coding: utf-8 -*-
"""
blender_efx/es3d_overlay.py  —  发射器生成区域线框（独立叠加层）

一个开关，画**当前选中的那些 entry** 的 EMITTERSHAPE3D 生成区域。与粒子模拟
完全解耦：不用播放、不推进任何东西，勾上就看得见，改字段立刻跟。

与另外两处的分工
----------------
* `sim_preview` 的「显示 → Emitter shape」勾选框：**播放期间**画正在播的那些
  track（整文件播放时就是那一批），跟着播放起点的矩阵走。
* 本模块：**不播放**也能看，只画选中的，用 entry 当前的世界矩阵（拖动 empty
  时线框跟着动）。**不展开 PtLife → Action 的子特效**——那是一整棵实例树，
  几十个形状叠在一起没法看，而作者正在编辑的是选中的这几个。
* `es3d_preview.py`：进入/退出式会话，用 GN 生成**真实网格子对象**，读法也与
  模拟层不同（见那个文件的说明）。那是另一套东西，本模块不碰它。

线框本身来自 `efx_format/sim/behaviors/emittershape3d.py::EmitterShape3D.outline()`
——和采样器同一份读法，所以「框在哪」与「粒子会生在哪」必然一致。形状读法的标定
开关（`es3d_range_mode` 等）同样对它生效。

约束（CLAUDE.md）：bpy 稳定子集（draw_handler_add 自 2.8、gpu.shader.from_builtin
自 2.8）；Python 3.10；纯胶水层，只读 EFX 字段。
"""

import bpy
from bpy.props import BoolProperty, FloatVectorProperty
from bpy.types import Operator

from .i18n import T

#: 一次最多画几个 entry 的线框。选中整个 EFX 时不至于把视口刷爆。
_MAX_ENTRIES = 64

_STATE = {
    "handler": None,
    "sig": None,        # 上次算线框时的「选中了谁」签名
    "dirty": False,     # 字段被改过 → 下次绘制重算
    "lines": [],        # 世界坐标的成对顶点
}


def is_active():
    return _STATE["handler"] is not None


def invalidate():
    """字段被编辑过 → 下次绘制重算（fields.py 的回调里调）。"""
    if _STATE["handler"] is not None:
        _STATE["dirty"] = True
        _redraw()


def _redraw():
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 线框计算
# ─────────────────────────────────────────────────────────────────────────────

def selected_entries(context):
    """选中对象（或它们下面的属性）各自往上找到的 entry，去重保序。

    空选时退回活动对象。**不**像 `sim_preview.collect_entries` 那样在点中根集合时
    扩展到整个文件——本叠加层就是「只看我选的这几个」。
    """
    from . import sim_preview as _sp

    out = []
    seen = set()
    for obj in list(getattr(context, "selected_objects", None) or ()):
        e = _sp._resolve_entry(obj)
        if e is not None and e.name not in seen:
            seen.add(e.name)
            out.append(e)
    if not out:
        e = _sp._resolve_entry(getattr(context, "active_object", None))
        if e is not None:
            out.append(e)
    return out[:_MAX_ENTRIES]


def _build(entries, scene):
    """每个 entry 建一个**单体** Simulator（不是 SimScene → 天然没有子特效树），
    取它的生成区域线框，过 entry 的世界矩阵变到世界坐标。"""
    from . import sim_preview as _sp

    out = []
    for obj in entries:
        try:
            sim = _sp.build_simulator(obj, scene)
        except Exception:
            continue
        if sim is None:
            continue
        try:
            pts = sim.emitter_outline()
        except Exception:
            continue
        if not pts:
            continue
        r0, r1, r2 = _sp._entry_matrix_rows(obj)
        for v in pts:
            bx, by, bz = _sp._to_blender(v)
            out.append((r0[0] * bx + r0[1] * by + r0[2] * bz + r0[3],
                        r1[0] * bx + r1[1] * by + r1[2] * bz + r1[3],
                        r2[0] * bx + r2[1] * by + r2[2] * bz + r2[3]))
    return out


def _signature(entries):
    """「选中了谁、摆在哪」——变了就重算。矩阵进签名，这样拖动 empty 线框会跟着走。"""
    sig = []
    for o in entries:
        try:
            m = o.matrix_world
            sig.append((o.name, tuple(m[i][j] for i in range(3) for j in range(4))))
        except Exception:
            sig.append((o.name, None))
    return tuple(sig)


# ─────────────────────────────────────────────────────────────────────────────
# 绘制
# ─────────────────────────────────────────────────────────────────────────────

def _draw():
    if _STATE["handler"] is None:
        return
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return
    context = bpy.context
    scene = context.scene
    entries = selected_entries(context)
    sig = _signature(entries)
    if _STATE["dirty"] or sig != _STATE["sig"]:
        _STATE["lines"] = _build(entries, scene)
        _STATE["sig"] = sig
        _STATE["dirty"] = False
    lines = _STATE["lines"]
    if not lines:
        return

    col = tuple(getattr(scene, "efx_es3d_overlay_color", (0.35, 0.75, 1.0, 0.7)))
    try:
        shader = gpu.shader.from_builtin("FLAT_COLOR")
    except Exception:
        try:
            shader = gpu.shader.from_builtin("3D_FLAT_COLOR")
        except Exception:
            return
    batch = batch_for_shader(shader, "LINES",
                             {"pos": lines, "color": [col] * len(lines)})
    depth = bool(getattr(scene, "efx_es3d_overlay_depth", True))
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL" if depth else "NONE")
    try:
        batch.draw(shader)
    except Exception:
        pass
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


_HANDLERS = []


def _remove_handler():
    while _HANDLERS:
        h = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except Exception:
            pass
    _STATE["handler"] = None
    _STATE["sig"] = None
    _STATE["lines"] = []


def _add_handler():
    _remove_handler()
    h = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _HANDLERS.append(h)
    _STATE["handler"] = h


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_es3d_overlay_toggle(Operator):
    """显示/隐藏选中特效体的生成区域线框（不需要播放；多选即多画）"""

    bl_idname = "efx.es3d_overlay_toggle"
    bl_label = "Emitter Shape Overlay"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if is_active():
            _remove_handler()
        else:
            _add_handler()
            _STATE["dirty"] = True
            n = len(selected_entries(context))
            if not n:
                self.report({"WARNING"}, T("es3do.no_entry"))
        _redraw()
        return {"FINISHED"}


def draw_button(layout, context):
    """给面板用的一行。开着时显示成按下状态。"""
    on = is_active()
    row = layout.row(align=True)
    row.operator("efx.es3d_overlay_toggle",
                 text=T("es3do.hide") if on else T("es3do.show"),
                 icon="MESH_UVSPHERE", depress=on)
    if on:
        sub = layout.row(align=True)
        sub.prop(context.scene, "efx_es3d_overlay_color", text="")
        sub.prop(context.scene, "efx_es3d_overlay_depth", toggle=True,
                 icon="XRAY")


_CLASSES = (EFX_OT_es3d_overlay_toggle,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    S = bpy.types.Scene
    S.efx_es3d_overlay_color = FloatVectorProperty(
        name="Outline colour", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=(0.35, 0.75, 1.0, 0.7))
    S.efx_es3d_overlay_depth = BoolProperty(
        name="Behind geometry", default=True,
        description="Let scene geometry hide the outline. Turn it off to keep the "
                    "whole outline visible through whatever is in front of it")


def unregister():
    _remove_handler()
    for attr in ("efx_es3d_overlay_color", "efx_es3d_overlay_depth"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
