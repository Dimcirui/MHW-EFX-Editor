"""在 Dope Sheet 与曲线编辑器侧栏编辑 TIML 元字段。

维护约束：TIML 字节归 Entry（或独立 TIML 载体）所有；属性回调直接读写该字节。
长度、循环和循环起点使用定长 patch。结构改动前必须提交 F-Curve，随后经
timl_edit 的入口写回以重建持久曲线。A0、A1 是固定槽位而非可任意增删的列表。
"""

import base64

import bpy
from bpy.types import Operator, Panel

from .i18n import T
from ..efx_format.timl import meta as tm
from ..efx_format import timl as _timl


# ─────────────────────────────────────────────────────────────────────────────
# entry 解析 / timl_bytes 读写
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_active_entry(obj):
    """解析活动对象的 TIML 字节载体；独立 TIML 句柄本身也是载体。"""
    from .timl_io import is_standalone_timl
    if is_standalone_timl(obj):
        return obj
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ENTRY":
            return cur
        cur = cur.parent
    return None


def _entry_timl_bytes(body) -> bytes:
    try:
        return base64.b64decode(str(body.get("timl_bytes", "")))
    except Exception:
        return b""


def _active_entry():
    """返回活动对象解析出的有效 TIML 载体。"""
    body = _resolve_active_entry(bpy.context.active_object)
    if body is None:
        return None
    tb = _entry_timl_bytes(body)
    if not tm.is_timl(tb):
        return None
    return body


def _store_timl(body, data: bytes):
    body["timl_bytes"] = base64.b64encode(data).decode("ascii")
    body["timl_length"] = str(len(data))


# ─────────────────────────────────────────────────────────────────────────────
# get/set 回调工厂（按 anim_index 绑定，挂在 WindowManager 上，瞬态不保存）
# ─────────────────────────────────────────────────────────────────────────────

# WindowManager 回调属性是瞬态 UI 入口；元字段不进入 F-Curve。
def _make_length_get(idx):
    def _get(self):
        body = _active_entry()
        if body is None:
            return 0.0
        anims = tm.parse_animations(_entry_timl_bytes(body))
        return float(anims[idx].animation_length) if idx < len(anims) else 0.0
    return _get


def _make_length_set(idx):
    def _set(self, value):
        body = _active_entry()
        if body is None:
            return
        data = _entry_timl_bytes(body)
        new = tm.set_animation_length(data, idx, value)
        if new != data:
            _store_timl(body, new)
    return _set


def _make_loop_get(idx):
    def _get(self):
        body = _active_entry()
        if body is None:
            return 0
        anims = tm.parse_animations(_entry_timl_bytes(body))
        if idx < len(anims):
            v = int(anims[idx].loop_control)
            return v if v in tm.LOOP_CONTROL_VALUES else 0
        return 0
    return _get


def _make_loop_set(idx):
    def _set(self, value):
        body = _active_entry()
        if body is None:
            return
        data = _entry_timl_bytes(body)
        new = tm.set_loop_control(data, idx, int(value))
        if new != data:
            _store_timl(body, new)
    return _set


def _make_loopstart_get(idx):
    def _get(self):
        body = _active_entry()
        if body is None:
            return 0.0
        anims = tm.parse_animations(_entry_timl_bytes(body))
        return float(anims[idx].loop_start_point) if idx < len(anims) else 0.0
    return _get


def _make_loopstart_set(idx):
    def _set(self, value):
        body = _active_entry()
        if body is None:
            return
        data = _entry_timl_bytes(body)
        new = tm.set_loop_start_point(data, idx, value)
        if new != data:
            _store_timl(body, new)
    return _set


# loopControl 枚举项：identifier / 名称（英文，无 0123）/ 描述 / 图标 / 数值(=loopControl 原值)
_LOOP_ENUM_ITEMS = [
    ("V0", "No Loop",   "Play once",                "", 0),
    ("V1", "Loop",      "Loop playback",            "", 1),
    ("V2", "Unkn",      "Play once (commonly used)", "", 2),
    ("V3", "Unkn Loop", "Loop playback (variant)",  "", 3),
]

# UI 为固定轴槽预留的最大回调属性数。
_MAX_ANIMS = 4


# ─────────────────────────────────────────────────────────────────────────────
# Operator：贴合最后关键帧（grow-only，单条动画）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timlm_fit_last_keyframe(Operator):
    """将轴长度增长到最后关键帧，绝不缩短已有长度。"""

    bl_idname = "efx.timlm_fit_last_keyframe"
    bl_label = "Fit to Last Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    anim_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_entry() is not None

    def execute(self, context):
        body = _active_entry()
        if body is None:
            self.report({"ERROR"}, T("timlm.no_entry"))
            return {"CANCELLED"}
        # 末帧计算前必须提交尚未写回的曲线编辑。
        from . import timl_edit as _te
        _te.commit_fcurves_to_bytes(body)
        lk = _live_last_kf(body, self.anim_index)
        if lk is None:
            self.report({"WARNING"}, T("timlm.no_kf"))
            return {"CANCELLED"}
        data = _entry_timl_bytes(body)
        anims = tm.parse_animations(data)
        cur = anims[self.anim_index].animation_length if self.anim_index < len(anims) else 0.0
        if lk <= cur:
            self.report({"INFO"}, T("timlm.grow_only"))
            return {"CANCELLED"}
        # 长度是结构字段，直接 patch 字节。
        _store_timl(body, tm.set_animation_length(data, self.anim_index, lk))
        self.report({"INFO"}, T("timlm.last_kf").format(f=lk))
        return {"FINISHED"}


# A0/A1 是两个固定的独立时间轴槽。
_AXIS_LABEL = {0: "timlm.axis0", 1: "timlm.axis1"}


def _axis_present(anims, slot) -> bool:
    return slot < len(anims) and anims[slot].data_offset != 0


def _set_anim_indices(t):
    for i, a in enumerate(t.animations):
        if a is not None:
            a.anim_index = i


class EFX_OT_timlm_enable_axis(Operator):
    """启用固定轴槽，以另一有效轴或空动画初始化。"""

    bl_idname = "efx.timlm_enable_axis"
    bl_label = "Enable Axis"
    bl_options = {"REGISTER", "UNDO"}

    slot: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_entry() is not None   # 会话内/外均可

    def execute(self, context):
        body = _active_entry()
        if body is None:
            return {"CANCELLED"}
        import copy
        # 结构改动前提交曲线，写回后由统一入口重建曲线。
        from . import timl_edit as _te
        _te.commit_fcurves_to_bytes(body)
        t = _te.read_model(body)
        if t is None:
            return {"CANCELLED"}
        slot = max(0, min(self.slot, 1))
        while len(t.animations) <= slot:
            t.animations.append(None)
        other = next((a for i, a in enumerate(t.animations) if a is not None and i != slot), None)
        t.animations[slot] = copy.deepcopy(other) if other is not None else _timl.make_blank_animdata(slot)
        t.count = len(t.animations)
        _set_anim_indices(t)
        t.dirty = True
        _te.set_entry_timl(body, t.serialize())
        self.report({"INFO"}, T("timlm.enabled_axis").format(T(_AXIS_LABEL.get(slot, ""))))
        return {"FINISHED"}


class EFX_OT_timlm_clear_axis(Operator):
    """清空固定轴槽；仅移除末端连续空槽。"""

    bl_idname = "efx.timlm_clear_axis"
    bl_label = "Clear Axis"
    bl_options = {"REGISTER", "UNDO"}

    slot: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_entry() is not None

    def execute(self, context):
        body = _active_entry()
        if body is None:
            return {"CANCELLED"}
        from . import timl_edit as _te
        _te.commit_fcurves_to_bytes(body)
        t = _te.read_model(body)
        if t is None:
            return {"CANCELLED"}
        slot = self.slot
        if 0 <= slot < len(t.animations):
            t.animations[slot] = None
        while t.animations and t.animations[-1] is None:
            t.animations.pop()
        t.count = len(t.animations)
        _set_anim_indices(t)
        t.dirty = True
        _te.set_entry_timl(body, t.serialize())
        self.report({"INFO"}, T("timlm.cleared_axis").format(T(_AXIS_LABEL.get(slot, ""))))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel：「EFX TIML」（Dope Sheet + 曲线编辑器 共用内容）
# ─────────────────────────────────────────────────────────────────────────────

def _live_axis_present(body):
    """返回两个固定轴槽是否在 TIML 字节中存在。"""
    anims = tm.parse_animations(_entry_timl_bytes(body))
    return [_axis_present(anims, s) for s in (0, 1)]


def _live_last_kf(body, slot):
    """返回字节中的最后关键帧；精确读取前调用方须先提交曲线。"""
    return tm.last_keyframe_time(_entry_timl_bytes(body), slot)


def _draw_meta_panel(layout, context):
    body = _active_entry()
    if body is None:
        # 区分"没选 entry"和"选了但没 TIML"
        raw = _resolve_active_entry(context.active_object)
        if raw is not None:
            layout.label(text=T("timlm.no_timl"), icon="DOT")
        else:
            layout.label(text=T("timlm.no_entry"), icon="INFO")
        return

    wm = context.window_manager
    present = _live_axis_present(body)

    # per-entry 自动增长开关
    layout.prop(body, "efx_timl_auto_grow", text=T("timlm.auto_grow"))

    # A0 / A1 两个固定独立的轴槽（不是可增删的列表）
    for slot in (0, 1):
        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text=T(_AXIS_LABEL[slot]),
                  icon="ANIM" if slot == 0 else "PARTICLES")

        if present[slot]:
            clr = hdr.row(align=True)
            op = clr.operator("efx.timlm_clear_axis", text="", icon="X")
            op.slot = slot
            box.label(text=T(_AXIS_LABEL[slot] + "_tip"), icon="BLANK1")

            # 动画长度：内联可编辑 + 贴合最后关键帧
            row = box.row(align=True)
            row.prop(wm, "efx_timlm_length_%d" % slot, text=T("timlm.length"))
            op = row.operator("efx.timlm_fit_last_keyframe", text="", icon="KEYFRAME_HLT")
            op.anim_index = slot
            lk = _live_last_kf(body, slot)
            if lk is not None:
                box.label(text=T("timlm.last_kf").format(f=lk), icon="KEYFRAME")
            else:
                box.label(text=T("timlm.no_kf"), icon="BLANK1")

            box.prop(wm, "efx_timlm_loop_%d" % slot, text=T("timlm.loop"))
            box.prop(wm, "efx_timlm_loopstart_%d" % slot, text=T("timlm.loopstart"))
        else:
            box.label(text=T(_AXIS_LABEL[slot] + "_tip"), icon="BLANK1")
            row = box.row(align=True)
            row.label(text=T("timlm.axis_empty"), icon="DOT")
            op = row.operator("efx.timlm_enable_axis", text=T("timlm.enable_axis"), icon="ADD")
            op.slot = slot


class EFX_PT_timl_meta(Panel):
    """Dope Sheet 侧栏中的 TIML 长度和循环控制。"""

    bl_space_type = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_category = "EFX TIML"
    bl_label = "EFX TIML"

    def draw(self, context):
        self.layout.label(text="· EFX TIML v0.2.77", icon="ANIM")
        try:
            _draw_meta_panel(self.layout, context)
        except Exception:
            import traceback
            self.layout.label(text=T("ui.error_console"), icon="ERROR")
            traceback.print_exc()


class EFX_PT_timl_meta_graph(EFX_PT_timl_meta):
    """曲线编辑器侧栏中的同一 TIML 元字段面板。"""
    bl_space_type = "GRAPH_EDITOR"


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_timlm_fit_last_keyframe,
    EFX_OT_timlm_enable_axis,
    EFX_OT_timlm_clear_axis,
    EFX_PT_timl_meta,
    EFX_PT_timl_meta_graph,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Object.efx_timl_auto_grow = bpy.props.BoolProperty(
        name="Auto-grow length on edit",
        description=T("timlm.auto_grow_desc"),
        default=True,
    )

    for i in range(_MAX_ANIMS):
        setattr(bpy.types.WindowManager, "efx_timlm_length_%d" % i,
                bpy.props.FloatProperty(
                    name="Animation Length", min=0.0,
                    get=_make_length_get(i), set=_make_length_set(i)))
        setattr(bpy.types.WindowManager, "efx_timlm_loop_%d" % i,
                bpy.props.EnumProperty(
                    name="Loop Control", items=_LOOP_ENUM_ITEMS,
                    get=_make_loop_get(i), set=_make_loop_set(i)))
        setattr(bpy.types.WindowManager, "efx_timlm_loopstart_%d" % i,
                bpy.props.FloatProperty(
                    name="Loop Start", get=_make_loopstart_get(i), set=_make_loopstart_set(i)))


def unregister():
    for i in range(_MAX_ANIMS):
        for stem in ("efx_timlm_length_%d", "efx_timlm_loop_%d", "efx_timlm_loopstart_%d"):
            attr = stem % i
            if hasattr(bpy.types.WindowManager, attr):
                delattr(bpy.types.WindowManager, attr)
    if hasattr(bpy.types.Object, "efx_timl_auto_grow"):
        del bpy.types.Object.efx_timl_auto_grow
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
