"""
blender_efx/timl_meta_ui.py  —  TIML 头部元字段编辑（Dope Sheet 侧栏「EFX TIML」）

在不进 FreeKinetics node tree 的前提下，直接编辑选中 EFX_BODY 的 TIML 头部元字段：

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

def _make_length_get(idx):
    def _get(self):
        body = _active_body()
        if body is None:
            return 0.0
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
        data = _body_timl_bytes(body)
        new = tm.set_loop_control(data, idx, int(value))
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
        data = _body_timl_bytes(body)
        lk = tm.last_keyframe_time(data, self.anim_index)
        if lk is None:
            self.report({"WARNING"}, T("timlm.no_kf"))
            return {"CANCELLED"}
        anims = tm.parse_animations(data)
        cur = anims[self.anim_index].animation_length if self.anim_index < len(anims) else 0.0
        if lk <= cur:
            self.report({"INFO"}, T("timlm.grow_only"))
            return {"CANCELLED"}
        _store_timl(body, tm.set_animation_length(data, self.anim_index, lk))
        self.report({"INFO"}, T("timlm.last_kf").format(f=lk))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel：DOPESHEET_EDITOR N 面板「EFX TIML」
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_timl_meta(Panel):
    """Dope Sheet 侧栏：编辑选中 EFX 特效体 TIML 的长度 / 循环控制"""

    bl_space_type = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_category = "EFX TIML"
    bl_label = "EFX TIML"

    def draw(self, context):
        layout = self.layout
        body = _active_body()
        if body is None:
            # 区分"没选 body"和"选了但没 TIML"
            raw = _resolve_active_body(context.active_object)
            if raw is not None:
                layout.label(text=T("timlm.no_timl"), icon="DOT")
            else:
                layout.label(text=T("timlm.no_body"), icon="INFO")
            return

        data = _body_timl_bytes(body)
        anims = tm.parse_animations(data)
        wm = context.window_manager

        # per-body 自动增长开关
        layout.prop(body, "efx_timl_auto_grow", text=T("timlm.auto_grow"))

        for a in anims:
            box = layout.box()
            box.label(text=T("timlm.anim").format(i=a.index), icon="ANIM")
            if a.data_offset == 0:
                box.label(text=T("timlm.empty_anim"), icon="DOT")
                continue
            if a.index >= _MAX_ANIMS:
                # 超出预注册属性范围（不可能发生于实测语料），只读显示
                box.label(text="length=%g  loop=%d" % (a.animation_length, a.loop_control))
                continue

            # 动画长度：内联可编辑 + 贴合最后关键帧
            row = box.row(align=True)
            row.prop(wm, "efx_timlm_length_%d" % a.index, text=T("timlm.length"))
            op = row.operator("efx.timlm_fit_last_keyframe",
                              text="", icon="KEYFRAME_HLT")
            op.anim_index = a.index
            lk = tm.last_keyframe_time(data, a.index)
            if lk is not None:
                box.label(text=T("timlm.last_kf").format(f=lk), icon="KEYFRAME")
            else:
                box.label(text=T("timlm.no_kf"), icon="BLANK1")

            # 循环控制下拉
            box.prop(wm, "efx_timlm_loop_%d" % a.index, text=T("timlm.loop"))


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_timlm_fit_last_keyframe,
    EFX_PT_timl_meta,
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


def unregister():
    for i in range(_MAX_ANIMS):
        for stem in ("efx_timlm_length_%d", "efx_timlm_loop_%d"):
            attr = stem % i
            if hasattr(bpy.types.WindowManager, attr):
                delattr(bpy.types.WindowManager, attr)
    if hasattr(bpy.types.Object, "efx_timl_auto_grow"):
        del bpy.types.Object.efx_timl_auto_grow
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
