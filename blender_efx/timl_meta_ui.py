"""
blender_efx/timl_meta_ui.py  —  TIML 头部元字段编辑（Dope Sheet 侧栏「EFX TIML」）

直接编辑选中 EFX_BODY 的 TIML 头部元字段（无需任何外部工具）：

  - Animation Length（每条动画）—— 可内联编辑 + 「贴合最后关键帧」按钮（grow-only）。
  - Loop Control —— 四值英文下拉（No Loop / Loop / Unkn / Unkn Loop）。
  - 「编辑时自动增长长度」开关（per-body，默认开）—— TIML 回写/导入时把长度增长到末关键帧。

实现要点
--------
- 源数据始终是 `body["timl_bytes"]`（base64）。编辑字段用 bpy 属性的 **get/set 回调**直接
  读写 timl_bytes，无需镜像状态、无 draw 期同步问题。
- 三个元字段都是**定长 4 字节原地 patch**（见 efx_format/timl_meta），改它们不改 timl 长度
  → 不碰 byte-perfect。`timl_length` 仍同步重写（导出端也会重算，双保险）。
- 语料实测一条 timl 多为 2 条 animation（max 2），故面板逐条平铺，算子带 anim_index。
- 面板放 DOPESHEET_EDITOR 的 N 面板独立侧栏，随选中特效体/动作切换显示。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；包内相对导入；纯胶水层。
"""

import base64

import bpy
from bpy.types import Operator, Panel

from .i18n import T
from ..efx_format import timl_meta as tm
from ..efx_format import timl as _timl   # 完整解析/序列化（animation 增删用）


# ─────────────────────────────────────────────────────────────────────────────
# body 解析 / timl_bytes 读写
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_active_body(obj):
    """从活动对象解析所属 EFX_BODY：自身是 body 即取，否则沿 parent 上溯。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_BODY":
            return cur
        cur = cur.parent
    return None


def _body_timl_bytes(body) -> bytes:
    try:
        return base64.b64decode(str(body.get("timl_bytes", "")))
    except Exception:
        return b""


def _active_body():
    """当前活动对象解析出的、带非空 TIML 的 EFX_BODY；否则 None。"""
    body = _resolve_active_body(bpy.context.active_object)
    if body is None:
        return None
    tb = _body_timl_bytes(body)
    if not tm.is_timl(tb):
        return None
    return body


def _store_timl(body, data: bytes):
    body["timl_bytes"] = base64.b64encode(data).decode("ascii")
    body["timl_length"] = str(len(data))   # 导出端也会再重算，双保险


# ─────────────────────────────────────────────────────────────────────────────
# get/set 回调工厂（按 anim_index 绑定，挂在 WindowManager 上，瞬态不保存）
# ─────────────────────────────────────────────────────────────────────────────

# 会话内：取活动 body 在 TIML 编辑会话中的 (entry, 内存模型 TimlData|None)；不在会话→(None, None)。
# 会话进行中元字段(长度/循环)读写直接走内存模型 entry["timl"]，Apply 才落字节（与轨道增删一致）。
def _session_anim(body, idx):
    try:
        from . import timl_edit as _te
        entry = _te.session_entry(body)
    except Exception:
        entry = None
    if entry is None:
        return None, None
    m = entry["timl"]
    if 0 <= idx < len(m.animations) and m.animations[idx] is not None:
        return entry, m.animations[idx]
    return entry, None


def _make_length_get(idx):
    def _get(self):
        body = _active_body()
        if body is None:
            return 0.0
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            return float(anim.animation_length) if anim is not None else 0.0
        anims = tm.parse_animations(_body_timl_bytes(body))
        if idx < len(anims):
            return float(anims[idx].animation_length)
        return 0.0
    return _get


def _make_length_set(idx):
    def _set(self, value):
        body = _active_body()
        if body is None:
            return
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            if anim is not None:
                anim.animation_length = float(value)
                from . import timl_edit as _te
                _te.session_mark_edited(entry)
            return
        data = _body_timl_bytes(body)
        new = tm.set_animation_length(data, idx, value)
        if new != data:
            _store_timl(body, new)
    return _set


def _make_loop_get(idx):
    def _get(self):
        body = _active_body()
        if body is None:
            return 0
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            v = int(anim.loop_control) if anim is not None else 0
            return v if v in tm.LOOP_CONTROL_VALUES else 0
        anims = tm.parse_animations(_body_timl_bytes(body))
        if idx < len(anims):
            v = int(anims[idx].loop_control)
            return v if v in tm.LOOP_CONTROL_VALUES else 0
        return 0
    return _get


def _make_loop_set(idx):
    def _set(self, value):
        body = _active_body()
        if body is None:
            return
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            if anim is not None:
                anim.loop_control = int(value)
                from . import timl_edit as _te
                _te.session_mark_edited(entry)
            return
        data = _body_timl_bytes(body)
        new = tm.set_loop_control(data, idx, int(value))
        if new != data:
            _store_timl(body, new)
    return _set


def _make_loopstart_get(idx):
    def _get(self):
        body = _active_body()
        if body is None:
            return 0.0
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            return float(anim.loop_start_point) if anim is not None else 0.0
        anims = tm.parse_animations(_body_timl_bytes(body))
        if idx < len(anims):
            return float(anims[idx].loop_start_point)
        return 0.0
    return _get


def _make_loopstart_set(idx):
    def _set(self, value):
        body = _active_body()
        if body is None:
            return
        entry, anim = _session_anim(body, idx)
        if entry is not None:
            if anim is not None:
                anim.loop_start_point = float(value)
                from . import timl_edit as _te
                _te.session_mark_edited(entry)
            return
        data = _body_timl_bytes(body)
        new = tm.set_loop_start_point(data, idx, value)
        if new != data:
            _store_timl(body, new)
    return _set


def _edit_active() -> bool:
    """通道编辑会话进行中？（进行中时禁止结构性增删，避免模型与字节脱节）"""
    try:
        from . import timl_edit as _te
        return bool(_te._state.get("active"))
    except Exception:
        return False


# loopControl 枚举项：identifier / 名称（英文，无 0123）/ 描述 / 图标 / 数值(=loopControl 原值)
_LOOP_ENUM_ITEMS = [
    ("V0", "No Loop",   "Play once",                "", 0),
    ("V1", "Loop",      "Loop playback",            "", 1),
    ("V2", "Unkn",      "Play once (commonly used)", "", 2),
    ("V3", "Unkn Loop", "Loop playback (variant)",  "", 3),
]

# 支持的最大 animation 条数（语料实测 max=2，留 4 余量）
_MAX_ANIMS = 4


# ─────────────────────────────────────────────────────────────────────────────
# Operator：贴合最后关键帧（grow-only，单条动画）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timlm_fit_last_keyframe(Operator):
    """把该动画的长度增长到其最后一个关键帧（grow-only：不缩短已有长度）"""

    bl_idname = "efx.timlm_fit_last_keyframe"
    bl_label = "Fit to Last Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    anim_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_body() is not None

    def execute(self, context):
        body = _active_body()
        if body is None:
            self.report({"ERROR"}, T("timlm.no_body"))
            return {"CANCELLED"}
        lk = _live_last_kf(body, self.anim_index)
        if lk is None:
            self.report({"WARNING"}, T("timlm.no_kf"))
            return {"CANCELLED"}
        # 会话内 → 改内存模型长度；会话外 → patch 字节
        entry, anim = _session_anim(body, self.anim_index)
        if entry is not None:
            cur = anim.animation_length if anim is not None else 0.0
            if lk <= cur:
                self.report({"INFO"}, T("timlm.grow_only"))
                return {"CANCELLED"}
            anim.animation_length = float(lk)
            from . import timl_edit as _te
            _te.session_mark_edited(entry)
            self.report({"INFO"}, T("timlm.last_kf").format(f=lk))
            return {"FINISHED"}
        data = _body_timl_bytes(body)
        anims = tm.parse_animations(data)
        cur = anims[self.anim_index].animation_length if self.anim_index < len(anims) else 0.0
        if lk <= cur:
            self.report({"INFO"}, T("timlm.grow_only"))
            return {"CANCELLED"}
        _store_timl(body, tm.set_animation_length(data, self.anim_index, lk))
        self.report({"INFO"}, T("timlm.last_kf").format(f=lk))
        return {"FINISHED"}


# A0/A1 是两个固定独立的时间轴槽（非可增删的动画列表）。实测主流形态是 [空, A1](4242 文件)。
_AXIS_LABEL = {0: "timlm.axis0", 1: "timlm.axis1"}


def _axis_present(anims, slot) -> bool:
    return slot < len(anims) and anims[slot].data_offset != 0


def _set_anim_indices(t):
    for i, a in enumerate(t.animations):
        if a is not None:
            a.anim_index = i


class EFX_OT_timlm_enable_axis(Operator):
    """启用某条轴（A0 发射 / A1 寿命）：在该槽建数据，复制另一条轴作起点（无则空）"""

    bl_idname = "efx.timlm_enable_axis"
    bl_label = "Enable Axis"
    bl_options = {"REGISTER", "UNDO"}

    slot: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_body() is not None   # 会话内/外均可

    def execute(self, context):
        body = _active_body()
        if body is None:
            return {"CANCELLED"}
        import copy
        # 会话内 → 改内存模型并重建曲线；会话外 → 解析字节并立即落字节
        entry = None
        try:
            from . import timl_edit as _te
            entry = _te.session_entry(body)
        except Exception:
            entry = None
        if entry is not None:
            _te.session_capture(entry)
            t = entry["timl"]
        else:
            t = _timl.parse_timl(_body_timl_bytes(body))
        if t is None:
            return {"CANCELLED"}
        slot = max(0, min(self.slot, 1))
        while len(t.animations) <= slot:        # 补槽（如启用 A1 时 A0 占位为空 → [None, ...]）
            t.animations.append(None)
        # 复制另一条已存在的轴作起点；没有则建空
        other = next((a for i, a in enumerate(t.animations) if a is not None and i != slot), None)
        t.animations[slot] = copy.deepcopy(other) if other is not None else _timl.make_blank_animdata(slot)
        t.count = len(t.animations)
        _set_anim_indices(t)
        t.dirty = True
        if entry is not None:
            _te.session_refresh(entry)
        else:
            _store_timl(body, t.serialize())
        self.report({"INFO"}, T("timlm.enabled_axis").format(T(_AXIS_LABEL.get(slot, ""))))
        return {"FINISHED"}


class EFX_OT_timlm_clear_axis(Operator):
    """清空某条轴（置空该槽；末端空槽自动收尾，前导空槽合法保留，如 [None, A1]）"""

    bl_idname = "efx.timlm_clear_axis"
    bl_label = "Clear Axis"
    bl_options = {"REGISTER", "UNDO"}

    slot: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_body() is not None

    def execute(self, context):
        body = _active_body()
        if body is None:
            return {"CANCELLED"}
        entry = None
        try:
            from . import timl_edit as _te
            entry = _te.session_entry(body)
        except Exception:
            entry = None
        if entry is not None:
            _te.session_capture(entry)
            t = entry["timl"]
        else:
            t = _timl.parse_timl(_body_timl_bytes(body))
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
        if entry is not None:
            _te.session_refresh(entry)
        else:
            _store_timl(body, t.serialize())
        self.report({"INFO"}, T("timlm.cleared_axis").format(T(_AXIS_LABEL.get(slot, ""))))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel：「EFX TIML」（Dope Sheet + 曲线编辑器 共用内容）
# ─────────────────────────────────────────────────────────────────────────────

def _live_axis_present(body):
    """[A0存在, A1存在]：会话内看内存模型，会话外看字节。"""
    try:
        from . import timl_edit as _te
        m = _te.session_model(body)
    except Exception:
        m = None
    if m is not None:
        return [(s < len(m.animations) and m.animations[s] is not None) for s in (0, 1)]
    anims = tm.parse_animations(_body_timl_bytes(body))
    return [_axis_present(anims, s) for s in (0, 1)]


def _live_last_kf(body, slot):
    """该轴最后关键帧时间：会话内从内存模型算，会话外从字节算。无 → None。"""
    try:
        from . import timl_edit as _te
        m = _te.session_model(body)
    except Exception:
        m = None
    if m is not None:
        if slot < len(m.animations) and m.animations[slot] is not None:
            mx = None
            for ty in m.animations[slot].types:
                for tf in ty.transforms:
                    for kf in tf.keyframes:
                        if mx is None or kf.frame_timing > mx:
                            mx = kf.frame_timing
            return mx
        return None
    return tm.last_keyframe_time(_body_timl_bytes(body), slot)


def _draw_meta_panel(layout, context):
    body = _active_body()
    if body is None:
        # 区分"没选 body"和"选了但没 TIML"
        raw = _resolve_active_body(context.active_object)
        if raw is not None:
            layout.label(text=T("timlm.no_timl"), icon="DOT")
        else:
            layout.label(text=T("timlm.no_body"), icon="INFO")
        return

    wm = context.window_manager
    edit_active = _edit_active()
    present = _live_axis_present(body)

    # per-body 自动增长开关
    layout.prop(body, "efx_timl_auto_grow", text=T("timlm.auto_grow"))
    if edit_active:
        # 通道编辑进行中：在此直接切 A0/A1/All 焦点（live 重建）
        box = layout.box()
        box.label(text=T("timlm.edit_active"), icon="FCURVE")
        try:
            from . import timl_edit as _te
            _te.draw_focus(box, context)
            box.label(text=T("timle.focus_note"), icon="BLANK1")
        except Exception:
            pass

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
    """Dope Sheet 侧栏：编辑选中 EFX 特效体 TIML 的长度 / 循环控制"""

    bl_space_type = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_category = "EFX TIML"
    bl_label = "EFX TIML"

    def draw(self, context):
        # ⚠ 无条件诊断标记：Dope Sheet 侧栏内容曾整体消失而曲线编辑器正常（2026-07-01
        # 用户报告）。这行在 draw() 一进来就画，跟内容无关——若 Dope Sheet 连这行都不显示，
        # 说明 draw() 根本没被调用（注册/空间类型问题）；若显示了但下面还是空，说明是
        # 内容绘制被吞。定位后即可删。
        self.layout.label(text="· EFX TIML v0.2.77", icon="ANIM")
        # 兜底：异常直接显示在面板里而不是静默空白。
        try:
            _draw_meta_panel(self.layout, context)
        except Exception:
            import traceback
            self.layout.label(text="EFX TIML panel error (see console):", icon="ERROR")
            for line in traceback.format_exc().splitlines()[-4:]:
                self.layout.label(text=line[:80])
            traceback.print_exc()


class EFX_PT_timl_meta_graph(EFX_PT_timl_meta):
    """曲线编辑器侧栏：与 Dope Sheet 完全相同的 EFX TIML 元字段面板。"""
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

    # per-body 自动增长开关（保存在 body 对象上，默认开）
    bpy.types.Object.efx_timl_auto_grow = bpy.props.BoolProperty(
        name="Auto-grow length on edit",
        description=T("timlm.auto_grow_desc"),
        default=True,
    )

    # 每条 animation 一组 get/set 属性（瞬态，挂 WindowManager）
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
