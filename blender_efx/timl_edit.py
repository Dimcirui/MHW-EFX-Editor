"""
blender_efx/timl_edit.py  —  阶段2b：自建 TIML 通道编辑会话（完全自包含，无外部工具依赖）

把 body 的 TIML 解析成**原生 Blender F 曲线**，用户在 Dope Sheet / Graph Editor 里改值/帧/
插值/缓动，Apply 时读回曲线、用 efx_format.timl 重建 TIML 字节写回 body。整条链路只用我们
自己的 `efx_format/timl.py` + `timl_names.py`。

机制
----
- 每个 body 一个 EFX_TIML 句柄；句柄上挂 `efx_timl_channels` CollectionProperty + 一个 Action。
- transform3d 九条通道(data_type2 且命中 timl_names.transform_mapping) → 真实
  location/rotation_euler/scale 曲线(轴变换 game↔Blender) → 句柄自身 transform 动 = **视口可播**；
  撞车(同 prop+index)回退 synthetic。其余通道 → synthetic `efx_timl_channels[i].value`。
- 关键帧映射(镜像 FK，编解码 28188/28188 验证)：co=(frame,value)、interpolation=transition、
  back=controlL、period=controlR。Color 拆 RGBA、Flag(hash∈BIG_FLAGS)拆 lo/hi、其余单条。
- 绑定 MESH(_uvc._body_mesh_target)时加 Child Of 约束让网格跟随句柄动画(退出移除)；
  无绑定则仅句柄自身动 + 曲线/Action 在(用户可自行绑到网格)。
- 回写：每 transform 收集子曲线 → 帧并集/逆轴变换 → encode_keyframe 重建 → Timl.dirty → serialize。
- byte-perfect：**会话级无改动检测**(进入快照曲线签名，Apply 一致则不回写 → verbatim)。

作用域(点③)：可勾选「同时编辑当前 EFX 集合内所有特效体」→ 每个含 TIML 的 body 各建一条编辑
条目(各自句柄+Action)，统一进入/应用/退出。

约束(CLAUDE.md)：bpy 稳定子集；Python 3.10；纯胶水层；硬逻辑在 efx_format/timl*.py。
"""

import base64

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import FloatProperty, CollectionProperty

from .i18n import T
from . import timl_io as _tio          # resolve_timl_body / _body_timl_bytes / _body_has_timl
from . import uvc_preview as _uvc       # _body_mesh_target / _resolve_root
from ..efx_format import timl as _timl
from ..efx_format import timl_names as _tn


class EFXTimlChannel(PropertyGroup):
    value: FloatProperty(name="Value")   # synthetic 通道的 F 曲线驱动目标


# ─────────────────────────────────────────────────────────────────────────────
# 会话状态（多条目：每个 body 一条）
# ─────────────────────────────────────────────────────────────────────────────
# entry = {timl_obj, body, timl, channels, prior_action, created_anim, mesh, con_name, snapshot}
# channel = {"mode":"xform", tf, kind, bl_index, path, index}
#         | {"mode":"syn",   tf, sub, path, index}

_state = {"active": False, "entries": [], "frame_start": 0, "frame_end": 1, "focus": "A0"}


def _anim_role(slot):
    # 通道组名前缀（发射轴 / 寿命轴 的短名，随 UI 语言）
    return T("timlm.short0") if slot == 0 else T("timlm.short1")


def _channel_group_name(slot, tlp_hash, dt_hash, dtype, sub_label):
    base = "A%d %s · %s" % (slot, _anim_role(slot), _tn.channel_label(tlp_hash, dt_hash))
    if sub_label:
        base += " [%s]" % sub_label
    return base


def _interp_to_blender(transition):
    return _timl.INTERP_NAMES[transition] if 0 <= transition < len(_timl.INTERP_NAMES) else "LINEAR"


def _blender_to_transition(interp):
    try:
        return _timl.INTERP_NAMES.index(interp)
    except ValueError:
        return 1   # 非这 7 种（如 BEZIER）→ 退 LINEAR


def _set_kp(kp, transition, back, period):
    try:
        kp.interpolation = _interp_to_blender(transition)
        kp.back = float(back)
        kp.period = float(period)
    except Exception:
        pass


def _ch_fcurve(act, ch):
    return act.fcurves.find(ch["path"], index=ch["index"])


# ─────────────────────────────────────────────────────────────────────────────
# 作用域解析
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scope_bodies(context):
    """按作用域返回要编辑的 body 列表（均含非空 TIML）。"""
    active = context.active_object
    if getattr(context.scene, "efx_timle_all_bodies", False):
        root = None
        try:
            root = _uvc._resolve_root(active)
        except Exception:
            root = None
        if root is None:
            body = _tio.resolve_timl_body(active)
            return [body] if _tio._body_has_timl(body) else []
        out = []
        for c in bpy.data.objects:
            if c.parent == root and c.get("~TYPE") == "EFX_BODY" and _tio._body_has_timl(c):
                out.append(c)
        return out
    body = _tio.resolve_timl_body(active)
    return [body] if _tio._body_has_timl(body) else []


# ─────────────────────────────────────────────────────────────────────────────
# 把模型的（焦点）通道铺进 Action —— 初次构建与切焦点重建共用
# ─────────────────────────────────────────────────────────────────────────────

def _focus_includes(slot: int) -> bool:
    f = _state.get("focus", "A0")
    if f == "A0":
        return slot == 0
    if f == "A1":
        return slot == 1
    return True   # ALL


def _populate_action(timl_obj, t, act):
    """按当前焦点把 t 的通道铺进 act（建 fcurve + 关键帧）。返回 (channels, fmin, fmax)。"""
    channels = []
    used_slots = set()
    fmin, fmax = 0.0, 1.0
    for slot, d in enumerate(t.animations):
        if d is None or not _focus_includes(slot):
            continue
        for ty in d.types:
            for f in ty.transforms:
                labels = _timl.channel_sublabels(f.data_type, f.datatype_hash)
                decoded = [_timl.decode_keyframe(kf.raw, f.data_type, f.datatype_hash)
                           for kf in f.keyframes]
                tmap = _tn.transform_mapping(f.datatype_hash) if (
                    f.data_type == 2 and len(labels) == 1) else None

                if tmap is not None and (tmap[0], tmap[1]) not in used_slots:
                    bl_prop, bl_index, kind = tmap
                    used_slots.add((bl_prop, bl_index))
                    fc = act.fcurves.new(data_path=bl_prop, index=bl_index)
                    for dec in decoded:
                        s = dec["subs"][0]
                        val = _tn.game_to_blender(kind, bl_index, s["value"])
                        kp = fc.keyframe_points.insert(dec["frame"], float(val))
                        _set_kp(kp, dec["transition"], s["back"], s["period"])
                        fmin = min(fmin, dec["frame"]); fmax = max(fmax, dec["frame"])
                    fc.update()
                    channels.append({"mode": "xform", "tf": f, "kind": kind,
                                     "bl_index": bl_index, "path": bl_prop, "index": bl_index})
                else:
                    for sub_idx, sub_label in enumerate(labels):
                        ci = len(timl_obj.efx_timl_channels)
                        timl_obj.efx_timl_channels.add()
                        gname = _channel_group_name(d.anim_index, ty.timeline_param_hash,
                                                    f.datatype_hash, f.data_type, sub_label)
                        path = "efx_timl_channels[%d].value" % ci
                        fc = act.fcurves.new(data_path=path, index=0, action_group=gname)
                        for dec in decoded:
                            s = dec["subs"][sub_idx]
                            kp = fc.keyframe_points.insert(dec["frame"], float(s["value"]))
                            _set_kp(kp, dec["transition"], s["back"], s["period"])
                            fmin = min(fmin, dec["frame"]); fmax = max(fmax, dec["frame"])
                        fc.update()
                        channels.append({"mode": "syn", "tf": f, "sub": sub_idx,
                                         "path": path, "index": 0})
    return channels, fmin, fmax


def _apply_frame_range(fmin, fmax):
    scene = bpy.context.scene
    scene.frame_start = int(fmin)
    scene.frame_end = max(int(round(fmax)), int(fmin) + 1)


# ─────────────────────────────────────────────────────────────────────────────
# 进入：为单个 body 建条目
# ─────────────────────────────────────────────────────────────────────────────

def _build_entry(timl_obj, body):
    """为一个 body 建 Action+通道（按当前焦点），返回 (entry, fmin, fmax) 或 None。"""
    data = _tio._body_timl_bytes(body)
    t = _timl.parse_timl(data)
    if t is None:
        return None

    # ⚠ 快照句柄进入前的 transform：transform3d 曲线会驱动句柄 location/rot/scale，
    # 移除 Action 后值停在最后评估帧 → 退出时据此还原回原位（否则句柄停在末帧位置）。
    basis_snap = timl_obj.matrix_basis.copy()
    timl_obj.efx_timl_channels.clear()
    act = bpy.data.actions.new("EFX_TIML::%s" % (body.get("efx_raw_label", "") or body.name))
    created = False
    if timl_obj.animation_data is None:
        timl_obj.animation_data_create()
        created = True
    prior = timl_obj.animation_data.action
    timl_obj.animation_data.action = act

    channels, fmin, fmax = _populate_action(timl_obj, t, act)

    mesh, con_name = _bind_mesh(timl_obj, body)
    entry = {"timl_obj": timl_obj, "body": body, "timl": t, "channels": channels,
             "prior_action": prior, "created_anim": created, "mesh": mesh,
             "con_name": con_name, "basis_snap": basis_snap, "edited": False,
             "snapshot": _snapshot(act, channels)}
    return entry, fmin, fmax


def _bind_mesh(timl_obj, body):
    """绑定 MESH 时加 Child Of 约束让网格跟随句柄。返回 (mesh, con_name) 或 (None, None)。"""
    try:
        mesh = _uvc._body_mesh_target(body)
    except Exception:
        mesh = None
    if mesh is None:
        return None, None
    try:
        con = mesh.constraints.new("CHILD_OF")
        con.name = "EFX_TIML_PREVIEW"
        con.target = timl_obj
        con.inverse_matrix = timl_obj.matrix_world.inverted()
        return mesh, con.name
    except Exception:
        return None, None


def _snapshot(act, channels):
    sig = []
    for ch in channels:
        fc = _ch_fcurve(act, ch)
        if fc is None:
            sig.append(()); continue
        sig.append(tuple(sorted(
            (round(kp.co[0], 4), round(kp.co[1], 5), kp.interpolation,
             round(kp.back, 5), round(kp.period, 5))
            for kp in fc.keyframe_points)))
    return tuple(sig)


# ─────────────────────────────────────────────────────────────────────────────
# 会话级进入 / 退出
# ─────────────────────────────────────────────────────────────────────────────

def _start_session(bodies):
    """为多个 body 建条目。返回建成的条目数。"""
    # 焦点取自 Scene 枚举（默认 A0）；_build_entry 按 _state["focus"] 过滤
    _state["focus"] = getattr(bpy.context.scene, "efx_timle_focus", "A0")
    entries = []
    fmin, fmax = 0.0, 1.0
    from . import io_tree as _iot
    seen = set()
    for body in bodies:
        if body is None or body.name in seen:
            continue
        seen.add(body.name)
        h = _iot.find_timl_handle(body)
        if h is None:
            h = _iot.make_timl_handle(body)
        built = _build_entry(h, body)
        if built is None:
            continue
        entry, lo, hi = built
        entries.append(entry)
        fmin = min(fmin, lo); fmax = max(fmax, hi)
    if not entries:
        return 0
    scene = bpy.context.scene
    _state.update(active=True, entries=entries,
                  frame_start=scene.frame_start, frame_end=scene.frame_end)
    scene.frame_start = int(fmin)
    scene.frame_end = max(int(round(fmax)), int(fmin) + 1)
    return len(entries)


def _channel_total():
    return sum(len(e["channels"]) for e in _state["entries"])


# ─────────────────────────────────────────────────────────────────────────────
# 回写（逐条目）
# ─────────────────────────────────────────────────────────────────────────────

def _readback_entry_to_model(entry):
    """把当前 Action（当前焦点的通道）读回内存模型 entry["timl"]（不写 body 字节）。
    无改动则跳过；有改动则重建受影响 transform 的 keyframes 并标 entry["edited"]。返回是否改动。"""
    timl_obj = entry["timl_obj"]; channels = entry["channels"]
    act = timl_obj.animation_data.action if timl_obj.animation_data else None
    if act is None:
        return False
    if _snapshot(act, channels) == entry["snapshot"]:
        return False   # 当前焦点无改动 → 不动模型（byte-perfect 友好）

    by_transform = {}
    for ch in channels:
        ent = by_transform.setdefault(id(ch["tf"]), {"tf": ch["tf"], "xform": None, "syn": {}})
        if ch["mode"] == "xform":
            ent["xform"] = ch
        else:
            ent["syn"][ch["sub"]] = ch
    for ent in by_transform.values():
        tf = ent["tf"]
        if ent["xform"] is not None:
            tf.keyframes = _rebuild_xform(act, ent["xform"], tf)
        else:
            tf.keyframes = _rebuild_synthetic(act, ent["syn"], tf)
    entry["edited"] = True
    return True


def _writeback_entry(entry):
    """Apply：先读回当前焦点，再（若该 body 累计有改动）序列化整模型写回 body。"""
    _readback_entry_to_model(entry)
    if not entry.get("edited"):
        return False
    t = entry["timl"]; body = entry["body"]
    t.dirty = True
    out = t.serialize()
    body["timl_bytes"] = base64.b64encode(out).decode("ascii")
    body["timl_length"] = str(len(out))
    return True


def _rebuild_xform(act, ch, tf):
    fc = _ch_fcurve(act, ch)
    if fc is None:
        return []
    kind, bl_index = ch["kind"], ch["bl_index"]
    out = []
    for kp in sorted(fc.keyframe_points, key=lambda k: k.co[0]):
        fr = round(kp.co[0], 4)
        game_v = _tn.blender_to_game(kind, bl_index, kp.co[1])
        subs = [{"value": game_v, "back": kp.back, "period": kp.period}]
        transition = _blender_to_transition(kp.interpolation)
        raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, fr,
                                    transition, tf.data_type, subs)
        out.append(_timl.TimlKeyframe(raw=raw, frame_timing=fr,
                                      transition=transition, data_type=tf.data_type))
    return out


def _rebuild_synthetic(act, syn, tf):
    labels = _timl.channel_sublabels(tf.data_type, tf.datatype_hash)
    sub_fcurves = [_ch_fcurve(act, syn[i]) if i in syn else None for i in range(len(labels))]
    frames = set(); kp_maps = []
    for fc in sub_fcurves:
        m = {}
        if fc is not None:
            for kp in fc.keyframe_points:
                fr = round(kp.co[0], 4); m[fr] = kp; frames.add(fr)
        kp_maps.append(m)
    if not frames:
        return []
    out = []
    for fr in sorted(frames):
        subs = []
        for i, fc in enumerate(sub_fcurves):
            kp = kp_maps[i].get(fr)
            if fc is None:
                subs.append({"value": 0.0, "back": 0.0, "period": 0.0})
            elif kp is not None:
                subs.append({"value": kp.co[1], "back": kp.back, "period": kp.period})
            else:
                subs.append({"value": fc.evaluate(fr), "back": 0.0, "period": 0.0})
        transition = 1
        for i, fc in enumerate(sub_fcurves):
            kp = kp_maps[i].get(fr)
            if kp is not None:
                transition = _blender_to_transition(kp.interpolation); break
        raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, fr,
                                    transition, tf.data_type, subs)
        out.append(_timl.TimlKeyframe(raw=raw, frame_timing=fr,
                                      transition=transition, data_type=tf.data_type))
    return out


def _rebuild_entry_action(entry):
    """切焦点：清空该条目的 Action/通道，按当前焦点重铺。"""
    timl_obj = entry["timl_obj"]
    ad = timl_obj.animation_data
    act = ad.action if ad else None
    if act is None:
        return 0.0, 1.0
    while act.fcurves:
        act.fcurves.remove(act.fcurves[0])
    timl_obj.efx_timl_channels.clear()
    # 重铺前把句柄归位（上个焦点播放可能已驱动它偏移）
    snap = entry.get("basis_snap")
    if snap is not None:
        timl_obj.matrix_basis = snap
    channels, fmin, fmax = _populate_action(timl_obj, entry["timl"], act)
    entry["channels"] = channels
    entry["snapshot"] = _snapshot(act, channels)
    return fmin, fmax


def _switch_focus(new_focus):
    """会话内切换焦点（A0/A1/All）：读回当前焦点编辑 → 改焦点 → 各条目重建视图。
    编辑保留在内存模型，跨切换不丢；body 字节仅在 Apply 时写。"""
    if not _state["active"]:
        _state["focus"] = new_focus
        return
    for entry in _state["entries"]:
        _readback_entry_to_model(entry)
    _state["focus"] = new_focus
    fmin, fmax = 0.0, 1.0
    for entry in _state["entries"]:
        lo, hi = _rebuild_entry_action(entry)
        fmin = min(fmin, lo); fmax = max(fmax, hi)
    _apply_frame_range(fmin, fmax)
    try:
        bpy.context.scene.frame_set(bpy.context.scene.frame_start)
    except Exception:
        pass


def _teardown():
    for entry in _state["entries"]:
        mesh = entry.get("mesh"); con_name = entry.get("con_name")
        if mesh is not None and con_name:
            try:
                con = mesh.constraints.get(con_name)
                if con is not None:
                    mesh.constraints.remove(con)
            except Exception:
                pass
        timl_obj = entry.get("timl_obj")
        if timl_obj is not None:
            try:
                ad = timl_obj.animation_data
                cur = ad.action if ad else None
                if ad is not None:
                    ad.action = entry["prior_action"]
                if cur is not None:
                    bpy.data.actions.remove(cur)
                if entry["created_anim"] and timl_obj.animation_data is not None:
                    timl_obj.animation_data_clear()
                timl_obj.efx_timl_channels.clear()
                # 还原句柄进入前的 transform（清 Action 后值会停在末帧，须显式还原）
                snap = entry.get("basis_snap")
                if snap is not None:
                    timl_obj.matrix_basis = snap
            except Exception:
                pass
    try:
        scene = bpy.context.scene
        scene.frame_start = _state["frame_start"]
        scene.frame_end = _state["frame_end"]
    except Exception:
        pass
    _state.update(active=False, entries=[], frame_start=0, frame_end=1)


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_edit_enter(Operator):
    """进入 TIML 通道编辑（解析成原生 F 曲线，在 Dope/Graph 编辑）"""
    bl_idname = "efx.timl_edit_enter"
    bl_label = "Edit TIML"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if _state["active"]:
            return False
        return bool(_resolve_scope_bodies(context))

    def execute(self, context):
        bodies = _resolve_scope_bodies(context)
        if not bodies:
            self.report({"ERROR"}, T("timle.no_timl"))
            return {"CANCELLED"}
        try:
            n = _start_session(bodies)
        except Exception as exc:
            _teardown()
            self.report({"ERROR"}, T("timle.build_failed").format(exc))
            return {"CANCELLED"}
        if n == 0:
            self.report({"WARNING"}, T("timle.no_content"))
            return {"CANCELLED"}
        try:
            context.scene.frame_set(context.scene.frame_start)
        except Exception:
            pass
        self.report({"INFO"}, T("timle.entered").format(_channel_total()))
        return {"FINISHED"}


class EFX_OT_timl_edit_exit(Operator):
    """退出 TIML 通道编辑（Apply=回写后退出；Cancel=丢弃）"""
    bl_idname = "efx.timl_edit_exit"
    bl_label = "Exit TIML Channel Edit"
    bl_options = {"REGISTER", "UNDO"}

    apply: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _state["active"]

    def execute(self, context):
        wrote = 0
        if self.apply:
            for entry in _state["entries"]:
                try:
                    if _writeback_entry(entry):
                        wrote += 1
                except Exception as exc:
                    self.report({"WARNING"}, T("timle.writeback_failed").format(exc))
        _teardown()
        if self.apply:
            self.report({"INFO"}, T("timle.applied").format(wrote) if wrote
                        else T("timle.applied_nochange"))
        else:
            self.report({"INFO"}, T("timle.cancelled"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 绘制控件（供 timl_io 的 TIML 面板调用 —— 点1：编辑入口归入 TIML 栏目）
# ─────────────────────────────────────────────────────────────────────────────

def draw_focus(layout, context):
    """焦点选择（A0/A1/All）——会话内改它即 live 切换；可在 TIML 面板与 Dope Sheet 侧栏复用。"""
    layout.prop(context.scene, "efx_timle_focus", text=T("timle.focus"), expand=True)


def draw_edit_controls(layout, context):
    if _state["active"]:
        box = layout.box()
        box.label(text=T("timle.editing").format(_channel_total(), len(_state["entries"])),
                  icon="FCURVE")
        # 焦点切换（会话内 live 重建；默认 A0 仅发射轴）
        draw_focus(box, context)
        box.label(text=T("timle.editor_hint"), icon="ACTION")
        row = box.row()
        row.scale_y = 1.3
        op = row.operator("efx.timl_edit_exit", text=T("timle.apply"), icon="CHECKMARK")
        op.apply = True
        op = box.row().operator("efx.timl_edit_exit", text=T("timle.cancel"), icon="X")
        op.apply = False
    else:
        layout.prop(context.scene, "efx_timle_all_bodies", text=T("timle.all_bodies"))
        draw_focus(layout, context)
        row = layout.row()
        row.scale_y = 1.3
        row.operator("efx.timl_edit_enter", text=T("timle.enter"), icon="FCURVE")
        layout.label(text=T("timle.enter_hint"), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_FOCUS_ITEMS = [
    ("ALL", "All", "Both axes (transform preview may mix the two axes)"),
    ("A0", "A0 Emission", "Emission axis — t=0 at effect trigger (system timeline)"),
    ("A1", "A1 Lifetime", "Lifetime axis — t=0 at each particle's birth"),
]


def _on_focus_update(self, context):
    # 会话内切焦点 → live 重建（读回当前编辑→改焦点→重铺视图）；非会话仅记默认
    _switch_focus(self.efx_timle_focus)


_CLASSES = (
    EFXTimlChannel,
    EFX_OT_timl_edit_enter,
    EFX_OT_timl_edit_exit,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.efx_timl_channels = CollectionProperty(type=EFXTimlChannel)
    bpy.types.Scene.efx_timle_all_bodies = bpy.props.BoolProperty(
        name="All bodies in this EFX",
        description="Edit the TIML of every body in the current EFX collection at once",
        default=False,
    )
    bpy.types.Scene.efx_timle_focus = bpy.props.EnumProperty(
        name="Focus", items=_FOCUS_ITEMS, default="ALL", update=_on_focus_update,
        description="Which axis to build/edit/play. Default All (most TIML use only one axis). "
                    "Pick A0/A1 to isolate when both are present.",
    )


def unregister():
    _teardown()
    if hasattr(bpy.types.Scene, "efx_timle_focus"):
        del bpy.types.Scene.efx_timle_focus
    if hasattr(bpy.types.Scene, "efx_timle_all_bodies"):
        del bpy.types.Scene.efx_timle_all_bodies
    if hasattr(bpy.types.Object, "efx_timl_channels"):
        del bpy.types.Object.efx_timl_channels
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
