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
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import FloatProperty, FloatVectorProperty, CollectionProperty

from .i18n import T
from . import timl_io as _tio          # resolve_timl_body / _body_timl_bytes / _body_has_timl
from . import uvc_preview as _uvc       # _body_mesh_target / _resolve_root
from ..efx_format import timl as _timl
from ..efx_format import timl_names as _tn


# ─────────────────────────────────────────────────────────────────────────────
# Action fcurves 兼容层
# ─────────────────────────────────────────────────────────────────────────────
# Blender 4.4+ 把 Action 改成 layers/strips/slots/channelbag 的分层结构，
# Action.fcurves 被彻底移除（不是 deprecated，是 AttributeError）。旧版(<4.4，
# 含 3.6/4.3 目标运行版本)Action.fcurves 仍是直接的 F 曲线集合。这层薄代理把
# 两套 API 收敛成旧版接口(new/find/remove/迭代)，业务代码统一走 _act_fcurves()，
# 不分裂成 if 版本 分支。
_LEGACY_ACTION_FCURVES = hasattr(bpy.types.Action, "fcurves")


class _ChannelbagFCurvesProxy:
    """代理新版 ActionChannelbag.fcurves，接口对齐旧版 act.fcurves。"""
    __slots__ = ("_fcs",)

    def __init__(self, channelbag):
        self._fcs = channelbag.fcurves

    def new(self, data_path, index=0, action_group=""):
        return self._fcs.new(data_path, index=index, group_name=action_group)

    def find(self, data_path, index=0):
        return self._fcs.find(data_path, index=index)

    def remove(self, fc):
        self._fcs.remove(fc)

    def __iter__(self):
        return iter(self._fcs)

    def __len__(self):
        return len(self._fcs)

    def __getitem__(self, i):
        return self._fcs[i]

    def __bool__(self):
        return len(self._fcs) > 0


def _ensure_channelbag(act, timl_obj):
    """新版 API 专用：按需建 slot/layer/strip，返回 timl_obj 对应的 ActionChannelbag。
    要求 act 已经是 timl_obj.animation_data.action（否则 action_slot 赋值语义不对）。"""
    ad = timl_obj.animation_data
    slot = ad.action_slot if (ad is not None and ad.action_slot is not None) else None
    if slot is None:
        for s in act.slots:
            if s.target_id_type in ("OBJECT", "UNSPECIFIED"):
                slot = s
                break
    if slot is None:
        slot = act.slots.new(id_type="OBJECT", name=timl_obj.name)
    if ad is not None and ad.action_slot is not slot:
        ad.action_slot = slot
    layer = act.layers[0] if act.layers else act.layers.new(name="Layer")
    strip = layer.strips[0] if layer.strips else layer.strips.new(type="KEYFRAME")
    return strip.channelbag(slot, ensure=True)


def _act_fcurves(act, timl_obj):
    """统一入口：旧版直接 act.fcurves；新版(4.4+)走 layers/strips/channelbag 代理。"""
    if _LEGACY_ACTION_FCURVES:
        return act.fcurves
    return _ChannelbagFCurvesProxy(_ensure_channelbag(act, timl_obj))


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


def _ch_fcurve(act, timl_obj, ch):
    return _act_fcurves(act, timl_obj).find(ch["path"], index=ch["index"])


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
                    fc = _act_fcurves(act, timl_obj).new(data_path=bl_prop, index=bl_index)
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
                        fc = _act_fcurves(act, timl_obj).new(data_path=path, index=0, action_group=gname)
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
    # ⚠ 会话 Action 必须靠自己的引用清理，不能指望退出时重新读 animation_data.action
    # 再删——用户在 Dope Sheet/Action Editor 原生控件上点 New/Browse/Unlink 都会改掉
    # ad.action，届时 teardown 读到的就不是这个真正的会话 Action 了，导致真正该删的
    # Action 找不到、永久残留在 bpy.data.actions 里（哪怕显示 0 用户也不会被清）。
    # fake_user=True 顺便防止会话期间被意外当孤儿数据回收。
    act.use_fake_user = True
    created = False
    if timl_obj.animation_data is None:
        timl_obj.animation_data_create()
        created = True
    prior = timl_obj.animation_data.action
    timl_obj.animation_data.action = act

    channels, fmin, fmax = _populate_action(timl_obj, t, act)

    mesh, con_name = _bind_mesh(timl_obj, body)
    entry = {"timl_obj": timl_obj, "body": body, "timl": t, "channels": channels,
             "action": act, "prior_action": prior, "created_anim": created, "mesh": mesh,
             "con_name": con_name, "basis_snap": basis_snap, "edited": False,
             "snapshot": _snapshot(act, timl_obj, channels)}
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


def _snapshot(act, timl_obj, channels):
    sig = []
    for ch in channels:
        fc = _ch_fcurve(act, timl_obj, ch)
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

def _session_action(entry):
    """取该 entry 真正的会话 Action，并把 animation_data.action 重新绑回它（自愈）。

    用户在 Dope Sheet/Graph Editor 的原生 Action Editor 控件上点 New/Browse/Unlink
    会改掉 timl_obj.animation_data.action，但 entry["action"] 这个引用本身不受影响——
    每次读写前都重新绑一次，编辑/回写/退出清理才始终对着真正的会话 Action，不会被
    用户误操作带偏。"""
    act = entry.get("action")
    timl_obj = entry.get("timl_obj")
    if act is None or timl_obj is None:
        return act
    try:
        ad = timl_obj.animation_data
        if ad is not None and ad.action is not act:
            ad.action = act
    except Exception:
        pass
    return act


def _readback_entry_to_model(entry):
    """把当前 Action（当前焦点的通道）读回内存模型 entry["timl"]（不写 body 字节）。
    无改动则跳过；有改动则重建受影响 transform 的 keyframes 并标 entry["edited"]。返回是否改动。"""
    channels = entry["channels"]
    timl_obj = entry["timl_obj"]
    act = _session_action(entry)
    if act is None:
        return False
    if _snapshot(act, timl_obj, channels) == entry["snapshot"]:
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
            tf.keyframes = _rebuild_xform(act, timl_obj, ent["xform"], tf)
        else:
            tf.keyframes = _rebuild_synthetic(act, timl_obj, ent["syn"], tf)
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


def _rebuild_xform(act, timl_obj, ch, tf):
    fc = _ch_fcurve(act, timl_obj, ch)
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


def _rebuild_synthetic(act, timl_obj, syn, tf):
    labels = _timl.channel_sublabels(tf.data_type, tf.datatype_hash)
    sub_fcurves = [_ch_fcurve(act, timl_obj, syn[i]) if i in syn else None for i in range(len(labels))]
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
    act = _session_action(entry)
    if act is None:
        return 0.0, 1.0
    fcs = _act_fcurves(act, timl_obj)
    while fcs:
        fcs.remove(fcs[0])
    timl_obj.efx_timl_channels.clear()
    # 重铺前把句柄归位（上个焦点播放可能已驱动它偏移）
    snap = entry.get("basis_snap")
    if snap is not None:
        timl_obj.matrix_basis = snap
    channels, fmin, fmax = _populate_action(timl_obj, entry["timl"], act)
    entry["channels"] = channels
    entry["snapshot"] = _snapshot(act, timl_obj, channels)
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
    # ⚠ 每一步独立 try：早先一步抛异常不得阻断后续的 Action 删除（否则会话 Action 残留）。
    for entry in _state["entries"]:
        # 1) 解除 mesh 预览约束
        mesh = entry.get("mesh"); con_name = entry.get("con_name")
        if mesh is not None and con_name:
            try:
                con = mesh.constraints.get(con_name)
                if con is not None:
                    mesh.constraints.remove(con)
            except Exception:
                pass
        timl_obj = entry.get("timl_obj")
        if timl_obj is None:
            continue
        # 2) 取回会话 Action 引用——直接用 entry["action"]，不要重新读
        #    animation_data.action：用户在 Dope Sheet/Action Editor 原生控件上点过
        #    New/Browse/Unlink 的话 ad.action 早就不是这个会话 Action 了，届时读出来
        #    删掉的是错的（或 None），真正的会话 Action 找不到主人、永久残留在
        #    bpy.data.actions 里（哪怕显示 0 用户也不会被自动清掉）。
        cur = entry.get("action")
        # 3) 还原进入前的 Action（独立 try，失败也不挡删除）
        try:
            ad = timl_obj.animation_data
            if ad is not None:
                ad.action = entry.get("prior_action")
        except Exception:
            pass
        # 4) 删除会话 Action 数据块——清 fake_user 防止残留在 .blend 的 Action 列表里
        if cur is not None:
            try:
                cur.use_fake_user = False
                bpy.data.actions.remove(cur, do_unlink=True)
            except Exception:
                pass
        # 5) 进会话时若新建过 animation_data，整体清除（恢复"无动画"状态）
        try:
            if entry.get("created_anim") and timl_obj.animation_data is not None:
                timl_obj.animation_data_clear()
        except Exception:
            pass
        # 6) 清 synthetic 通道集合
        try:
            timl_obj.efx_timl_channels.clear()
        except Exception:
            pass
        # 7) 还原句柄进入前的 transform（清 Action 后值会停在末帧，须显式还原）
        try:
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
# 会话内结构性编辑对接 API
# （供 timl_tracks / timl_meta_ui 在会话进行中直接改内存模型 entry["timl"]，
#  而非改 body 字节——会话期间字节是陈旧的，编辑都在模型里，Apply 才落字节）
# ─────────────────────────────────────────────────────────────────────────────

def session_active() -> bool:
    return bool(_state["active"])


def session_entry(body):
    """该 body 在当前会话中的 entry；不在会话 / 无会话 → None。"""
    if not _state["active"] or body is None:
        return None
    for e in _state["entries"]:
        b = e.get("body")
        if b is body or (b is not None and getattr(b, "name", None) == body.name):
            return e
    return None


def session_model(body):
    """该 body 在会话中的内存 Timl 模型（只读展示用）；无 → None。"""
    e = session_entry(body)
    return e["timl"] if e is not None else None


def session_capture(entry):
    """结构性改动【前】调用：把当前焦点的曲线编辑读回内存模型，避免进行中的编辑被重建覆盖。"""
    try:
        _readback_entry_to_model(entry)
    except Exception:
        pass


def session_mark_edited(entry):
    """仅标脏（元字段如长度/循环改动用，不触碰曲线）。"""
    entry["edited"] = True


def session_refresh(entry):
    """结构性改动【后】调用：标脏 + 按当前焦点重建 Action（含新轨道）+ 重设帧范围。"""
    entry["edited"] = True
    try:
        lo, hi = _rebuild_entry_action(entry)
        _apply_frame_range(lo, hi)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

def _select_session_handles(context):
    """选中所有会话条目的 TIML 句柄并把第一个设为 active。

    Dope Sheet / Graph Editor 默认「只显示选中物体」，进入编辑会话后如果不主动选中
    句柄，新建好的 Action 曲线不会自动出现在编辑器里——之前 enter 完全没做这一步，
    表现为"新建/进入编辑后不会跳转到指定的动作"，得用户自己去大纲视图手动点句柄。"""
    try:
        for obj in context.view_layer.objects:
            obj.select_set(False)
    except Exception:
        pass
    first = None
    for entry in _state["entries"]:
        obj = entry.get("timl_obj")
        if obj is None:
            continue
        try:
            obj.select_set(True)
            if first is None:
                first = obj
        except Exception:
            pass
    if first is not None:
        try:
            context.view_layer.objects.active = first
        except Exception:
            pass


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
        _select_session_handles(context)
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
# 色轮（Color Wheel）—— 把 RGB(A) 4 条 synthetic 标量通道聚合成一个色轮控件
# 只在会话中存在（synthetic fcurve 只在编辑会话期间挂在句柄 Action 上）；
# 色轮不改数据模型，只是读写这 4 条真实 fcurve 在当前帧的关键帧——与直接在
# Dope Sheet 里逐条调值等价，Apply 时走同一条 _readback_entry_to_model 路径。
# ─────────────────────────────────────────────────────────────────────────────

def _current_entry(context):
    if not _state["active"]:
        return None
    try:
        body = _tio.resolve_timl_body(context.active_object)
    except Exception:
        return None
    return session_entry(body)


def _find_color_groups(entry):
    """按 tf 聚合该 entry 里所有 dataType==Color(3) 的 synthetic 通道组。"""
    groups = {}
    order = []
    for ch in entry["channels"]:
        if ch["mode"] != "syn" or ch["tf"].data_type != 3:
            continue
        key = id(ch["tf"])
        if key not in groups:
            groups[key] = {"tf": ch["tf"], "subs": {}}
            order.append(key)
        groups[key]["subs"][ch["sub"]] = ch
    return [groups[k] for k in order if len(groups[k]["subs"]) >= 3]


def _active_color_group(context, entry):
    """确定色轮当前操作哪一组：唯一一组直接用；多组按 Dope Sheet/Graph 里选中的
    通道行（fcurve.select）判定；都没选中则二义，不猜（返回 None）。"""
    act = _session_action(entry)
    if act is None:
        return None, None
    groups = _find_color_groups(entry)
    if not groups:
        return None, act
    if len(groups) == 1:
        return groups[0], act
    for g in groups:
        for ch in g["subs"].values():
            fc = _ch_fcurve(act, entry["timl_obj"], ch)
            if fc is not None and fc.select:
                return g, act
    return None, act


def _write_scalar_keyframe(fc, frame, value):
    for kp in fc.keyframe_points:
        if abs(kp.co[0] - frame) < 1e-4:
            kp.co[1] = value
            fc.update()
            return
    kp = fc.keyframe_points.insert(frame, value)
    kp.interpolation = "LINEAR"
    fc.update()


def _color_wheel_get(self):
    try:
        entry = _current_entry(bpy.context)
        if entry is None:
            return (0.0, 0.0, 0.0)
        group, act = _active_color_group(bpy.context, entry)
        if group is None:
            return (0.0, 0.0, 0.0)
        frame = bpy.context.scene.frame_current
        out = [0.0, 0.0, 0.0]
        for i in range(3):
            fc = _ch_fcurve(act, entry["timl_obj"], group["subs"][i])
            if fc is not None:
                out[i] = max(0.0, min(255.0, fc.evaluate(frame))) / 255.0
        return tuple(out)
    except Exception:
        return (0.0, 0.0, 0.0)


def _color_wheel_set(self, value):
    try:
        entry = _current_entry(bpy.context)
        if entry is None:
            return
        group, act = _active_color_group(bpy.context, entry)
        if group is None:
            return
        frame = bpy.context.scene.frame_current
        for i in range(3):
            fc = _ch_fcurve(act, entry["timl_obj"], group["subs"].get(i)) if i in group["subs"] else None
            if fc is not None:
                _write_scalar_keyframe(fc, frame, max(0.0, min(1.0, value[i])) * 255.0)
    except Exception:
        pass


def _color_alpha_get(self):
    try:
        entry = _current_entry(bpy.context)
        if entry is None:
            return 1.0
        group, act = _active_color_group(bpy.context, entry)
        if group is None or 3 not in group["subs"]:
            return 1.0
        fc = _ch_fcurve(act, entry["timl_obj"], group["subs"][3])
        if fc is None:
            return 1.0
        return max(0.0, min(255.0, fc.evaluate(bpy.context.scene.frame_current))) / 255.0
    except Exception:
        return 1.0


def _color_alpha_set(self, value):
    try:
        entry = _current_entry(bpy.context)
        if entry is None:
            return
        group, act = _active_color_group(bpy.context, entry)
        if group is None or 3 not in group["subs"]:
            return
        fc = _ch_fcurve(act, entry["timl_obj"], group["subs"][3])
        if fc is not None:
            _write_scalar_keyframe(fc, bpy.context.scene.frame_current, max(0.0, min(1.0, value)) * 255.0)
    except Exception:
        pass


def draw_color_wheel(layout, context):
    """TIML 色轮控件：聚合当前选中颜色通道组的 R/G/B(/A) 为一个色轮 + Alpha 滑条。"""
    entry = _current_entry(context)
    if entry is None:
        layout.label(text=T("timle.color_need_session"), icon="INFO")
        return
    groups = _find_color_groups(entry)
    if not groups:
        layout.label(text=T("timle.color_none"), icon="INFO")
        return
    group, act = _active_color_group(context, entry)
    if group is None or act is None:
        layout.label(text=T("timle.color_ambiguous"), icon="INFO")
        return
    col = layout.column(align=True)
    col.template_color_picker(context.scene, "efx_timle_color_rgb", value_slider=True)
    col.prop(context.scene, "efx_timle_color_rgb", text="")
    if 3 in group["subs"]:
        col.prop(context.scene, "efx_timle_color_a", text=T("timle.color_alpha"), slider=True)


class EFX_PT_timl_color_wheel(Panel):
    """Dope Sheet 侧栏：把当前颜色通道组的 RGBA 聚合成色轮编辑。"""

    bl_space_type  = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_category    = "EFX TIML"
    bl_label       = "TIML Color Wheel"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _state["active"]

    def draw(self, context):
        # ⚠ 同 EFX_PT_timl_tracks：异常直接显示在面板里而不是让内容静默消失。
        try:
            draw_color_wheel(self.layout, context)
        except Exception:
            import traceback
            self.layout.label(text="TIML Color Wheel panel error (see console):", icon="ERROR")
            for line in traceback.format_exc().splitlines()[-4:]:
                self.layout.label(text=line[:80])
            traceback.print_exc()


class EFX_PT_timl_color_wheel_graph(EFX_PT_timl_color_wheel):
    """曲线编辑器侧栏：与 Dope Sheet 完全相同的色轮面板。"""

    bl_space_type = "GRAPH_EDITOR"


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
    EFX_PT_timl_color_wheel,
    EFX_PT_timl_color_wheel_graph,
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
    bpy.types.Scene.efx_timle_color_rgb = FloatVectorProperty(
        name="Color", subtype="COLOR", size=3, min=0.0, max=1.0,
        get=_color_wheel_get, set=_color_wheel_set,
        description="Aggregated RGB color wheel for the active TIML color channel group "
                    "(reads/writes the R/G/B synthetic channels' keyframe at the current frame)",
    )
    bpy.types.Scene.efx_timle_color_a = FloatProperty(
        name="Alpha", min=0.0, max=1.0, default=1.0,
        get=_color_alpha_get, set=_color_alpha_set,
        description="Alpha channel of the active TIML color channel group at the current frame",
    )


def unregister():
    _teardown()
    if hasattr(bpy.types.Scene, "efx_timle_color_a"):
        del bpy.types.Scene.efx_timle_color_a
    if hasattr(bpy.types.Scene, "efx_timle_color_rgb"):
        del bpy.types.Scene.efx_timle_color_rgb
    if hasattr(bpy.types.Scene, "efx_timle_focus"):
        del bpy.types.Scene.efx_timle_focus
    if hasattr(bpy.types.Scene, "efx_timle_all_bodies"):
        del bpy.types.Scene.efx_timle_all_bodies
    if hasattr(bpy.types.Object, "efx_timl_channels"):
        del bpy.types.Object.efx_timl_channels
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
