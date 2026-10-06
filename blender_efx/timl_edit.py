"""将 Entry TIML 字节与 Blender 持久 F 曲线同步，并提供网格预览绑定。

维护约束：``timl_bytes`` 保留 F 曲线无法表达的结构数据；所有字节变更必须经
``set_entry_timl`` 重建句柄和 F 曲线。结构编辑先提交当前 F 曲线值。导出时再将
F 曲线值合并回字节。TIML 解析和编码规则归 ``efx_format.timl``。
"""

import base64

import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import FloatProperty, FloatVectorProperty, CollectionProperty

from .i18n import T
from . import timl_io as _tio          # resolve_timl_entry / _entry_timl_bytes / _entry_has_timl
from . import uvc_preview as _uvc       # _entry_mesh_target / _resolve_root
from . import session_core as _sc       # 标记式 reconcile（bind/unbind 用）
from . import root_collection as _rc
from ..efx_format import timl as _timl
from ..efx_format.timl import names as _tn


# ─────────────────────────────────────────────────────────────────────────────
# Action F 曲线兼容层。
# ─────────────────────────────────────────────────────────────────────────────
# Blender 4.4+ 使用 layer/strip/slot/channelbag；调用方统一经 ``_act_fcurves``。
# 版本判定使用 ``bpy.app.version``，不能依赖 RNA 类属性探测。
_LEGACY_ACTION_FCURVES = bpy.app.version < (4, 4, 0)


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


class _EmptyFCurves:
    """只读上下文没有 channelbag 时使用的空 F 曲线集合。

    写入操作必须报错，避免在本不应创建数据的路径静默改变状态。
    """

    def find(self, data_path, index=0):
        return None

    def new(self, *a, **kw):
        raise RuntimeError("_act_fcurves(create=False) 下不能新建 fcurve")

    def remove(self, fc):
        raise RuntimeError("_act_fcurves(create=False) 下不能删除 fcurve")

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __getitem__(self, i):
        raise IndexError(i)

    def __bool__(self):
        return False


def _ensure_channelbag(act, timl_obj, create=True):
    """返回 4.4+ ActionChannelbag；``create`` 会写入 Blender ID 数据。

    从 ``poll`` 或 ``draw`` 可达的路径必须传 ``create=False``。
    """
    ad = timl_obj.animation_data
    slot = ad.action_slot if (ad is not None and ad.action_slot is not None) else None
    if slot is None:
        for s in act.slots:
            if s.target_id_type in ("OBJECT", "UNSPECIFIED"):
                slot = s
                break
    if slot is None:
        if not create:
            return None
        slot = act.slots.new(id_type="OBJECT", name=timl_obj.name)
    if create and ad is not None and ad.action_slot is not slot:
        ad.action_slot = slot
    if act.layers:
        layer = act.layers[0]
    elif create:
        layer = act.layers.new(name="Layer")
    else:
        return None
    if layer.strips:
        strip = layer.strips[0]
    elif create:
        strip = layer.strips.new(type="KEYFRAME")
    else:
        return None
    return strip.channelbag(slot, ensure=create)


def _act_fcurves(act, timl_obj, create=False):
    """取得版本无关的 F 曲线集合；创建仅允许在可写上下文。"""
    if _LEGACY_ACTION_FCURVES:
        return act.fcurves
    bag = _ensure_channelbag(act, timl_obj, create=create)
    if bag is None:
        return _EmptyFCurves()
    return _ChannelbagFCurvesProxy(bag)


class EFXTimlChannel(PropertyGroup):
    value: FloatProperty(name="Value")   # synthetic 通道的 F 曲线驱动目标


# ─────────────────────────────────────────────────────────────────────────────
# 通道映射辅助
# ─────────────────────────────────────────────────────────────────────────────

def _anim_role(slot):
    # 通道组名前缀（发射轴 / 寿命轴 的短名，随 UI 语言）
    return T("timlm.short0") if slot == 0 else T("timlm.short1")


def _channel_group_name(slot, tlp_hash, dt_hash, dtype, sub_label):
    base = "A%d %s · %s" % (slot, _anim_role(slot), _tn.channel_label(tlp_hash, dt_hash))
    if sub_label:
        base += " [%s]" % sub_label
    return base


# ── 插值类型映射 ────────────────────────────────────────────────────────────
# 游戏插值：0 / 1 阶跃（两者相同）、2 线性、3 三次 Hermite（段起始关键帧的两个值是本段起点 /
# 终点切线，以本段平均斜率为 1）、4 smoothstep（= 3 不带切线）。5 以上不是正常插值。
# 3 / 4 导入为 FREE 手柄的贝塞尔：手柄横向落在段长 1/3 处时，贝塞尔与 Hermite 完全等价，
# 手柄高度 = 切线 × 落差 / 3。导出时由手柄斜率反算切线，一律写 3。
_GAME_TO_BLENDER_INTERP = {
    0: "CONSTANT",
    1: "CONSTANT",
    2: "LINEAR",
    3: "BEZIER",
    4: "BEZIER",
}
_EXACT_INTERP = {"CONSTANT": 1, "LINEAR": 2, "BEZIER": 3}
_HERMITE = 3
_EPS = 1e-6
#: 手柄横向偏离段长 1/3 超过这个比例时，导出形状与编辑器里看到的有可见差别
_HANDLE_X_TOL = 0.08
#: 拟合 Blender 缓动时每段的采样点（不含两端）
_FIT_SAMPLES = [i / 16.0 for i in range(1, 16)]


def _interp_to_blender(transition):
    """游戏 transition → Blender 插值名（导入用）；5 以上按线性。"""
    return _GAME_TO_BLENDER_INTERP.get(transition, "LINEAR")


def _hermite_basis(u):
    u2 = u * u
    u3 = u2 * u
    return (3.0 * u2 - 2.0 * u3, u3 - 2.0 * u2 + u, u3 - u2)


def _fit_tangents(fc, f0, v0, f1, v1):
    """用最小二乘把 fc 在 [f0, f1] 上的形状拟合成 Hermite 的两个切线。"""
    dv = v1 - v0
    a11 = a12 = a22 = b1 = b2 = 0.0
    for u in _FIT_SAMPLES:
        y = (fc.evaluate(f0 + (f1 - f0) * u) - v0) / dv
        h01, h10, h11 = _hermite_basis(u)
        r = y - h01
        a11 += h10 * h10
        a12 += h10 * h11
        a22 += h11 * h11
        b1 += h10 * r
        b2 += h11 * r
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return 0.0, 0.0
    return (b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det


def _close(a, b):
    return abs(a - b) <= 1e-4 * (1.0 + abs(b))


def _segment_spec(fc, kp, kp_next):
    """一个关键帧 → (transition, 起点切线, 终点切线, 问题)。

    问题：None；"approx" 用了游戏没有的缓动，按拟合近似；"handle" 贝塞尔手柄无法精确对应。
    没被改动过的切线沿用导入时存下的原值（kp.back / kp.period），保证原样写回。
    """
    stored = (kp.back, kp.period)
    it = kp.interpolation
    if it in ("CONSTANT", "LINEAR"):
        return (_EXACT_INTERP[it],) + stored + (None,)
    if kp_next is None:
        return (_HERMITE,) + stored + (None,)
    f0, v0 = kp.co[0], kp.co[1]
    f1, v1 = kp_next.co[0], kp_next.co[1]
    span, dv = f1 - f0, v1 - v0
    if span <= _EPS:
        return (_HERMITE,) + stored + (None,)
    if it != "BEZIER":
        if abs(dv) <= _EPS:
            return (_EXACT_INTERP["LINEAR"], 0.0, 0.0, "approx")
        m0, m1 = _fit_tangents(fc, f0, v0, f1, v1)
        return (_HERMITE, m0, m1, "approx")
    hr, hl = kp.handle_right, kp_next.handle_left
    if abs(dv) <= _EPS:
        # 落差为 0 时游戏里这一段只能是平的
        flat = abs(hr[1] - v0) <= _EPS and abs(hl[1] - v1) <= _EPS
        return (_HERMITE,) + stored + (None if flat else "handle",)
    avg = dv / span
    dx0, dx1 = hr[0] - f0, f1 - hl[0]
    issue = None
    if abs(dx0 / span - 1.0 / 3.0) > _HANDLE_X_TOL or abs(dx1 / span - 1.0 / 3.0) > _HANDLE_X_TOL:
        issue = "handle"
    m0 = (hr[1] - v0) / dx0 / avg if dx0 > _EPS else 0.0
    m1 = (v1 - hl[1]) / dx1 / avg if dx1 > _EPS else 0.0
    if _close(m0, stored[0]):
        m0 = stored[0]
    if _close(m1, stored[1]):
        m1 = stored[1]
    return (_HERMITE, m0, m1, issue)


def _sorted_kps(fc):
    return sorted(fc.keyframe_points, key=lambda k: k.co[0])


def check_timl_interpolations(handle):
    """返回持久 Action 中导出时要近似的地方，按问题类型去重；全部是警告，不阻止导出。

    {"severity": "WARNING", "kind": "approx", "interp": Blender 插值名} 用了游戏没有的缓动；
    {"severity": "WARNING", "kind": "handle"} 贝塞尔手柄无法被游戏曲线精确表示。
    """
    out = []
    act = _get_timl_action(handle)
    if act is None:
        return out
    try:
        fcs = _act_fcurves(act, handle)
    except Exception:
        return out
    seen = set()
    for fc in fcs:
        try:
            kps = _sorted_kps(fc)
        except Exception:
            continue
        for i, kp in enumerate(kps):
            try:
                issue = _segment_spec(fc, kp, kps[i + 1] if i + 1 < len(kps) else None)[3]
            except Exception:
                continue
            if issue is None:
                continue
            key = (issue, kp.interpolation if issue == "approx" else None)
            if key in seen:
                continue
            seen.add(key)
            item = {"severity": "WARNING", "kind": issue}
            if issue == "approx":
                item["interp"] = kp.interpolation
            out.append(item)
    return out


def _set_kp(kp, transition, start_tangent, end_tangent):
    # 两个切线原值存在 Blender 关键帧的 back / period 上：手柄没动时导出原样写回
    try:
        kp.interpolation = _interp_to_blender(transition)
        kp.back = float(start_tangent)
        kp.period = float(end_tangent)
    except Exception:
        pass


def _apply_hermite_handles(fc, decoded, values):
    """按游戏关键帧给类型 3 / 4 的段摆贝塞尔手柄（横向 1/3，高度 = 切线 × 落差 / 3）。

    decoded / values 与 fc 的关键帧一一对应且按帧排序；values 是 Blender 数值空间的值。
    """
    kps = _sorted_kps(fc)
    if len(kps) != len(decoded):
        return
    for i in range(len(kps) - 1):
        tr = decoded[i][0]
        if tr not in (3, 4):
            continue
        m0, m1 = decoded[i][1:3] if tr == 3 else (0.0, 0.0)
        f0, f1 = kps[i].co[0], kps[i + 1].co[0]
        v0, v1 = values[i], values[i + 1]
        third = (f1 - f0) / 3.0
        a, b = kps[i], kps[i + 1]
        a.handle_right_type = "FREE"
        b.handle_left_type = "FREE"
        a.handle_right = (f0 + third, v0 + m0 * (v1 - v0) / 3.0)
        b.handle_left = (f1 - third, v1 - m1 * (v1 - v0) / 3.0)


def _ch_fcurve(act, timl_obj, ch):
    return _act_fcurves(act, timl_obj).find(ch["path"], index=ch["index"])


# ─────────────────────────────────────────────────────────────────────────────
# 作用域解析
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scope_bodies(context):
    """按作用域返回要预览的 entry 列表（均含非空 TIML）。"""
    active = context.active_object
    if getattr(context.scene, "efx_timle_all_bodies", False):
        root = None
        try:
            root = _uvc._resolve_root(active)
        except Exception:
            root = None
        if root is None:
            body = _tio.resolve_timl_entry(active)
            return [body] if _tio._entry_has_timl(body) else []
        return [c for c in _rc.collect_top_level(root, "EFX_ENTRY")
                if _tio._entry_has_timl(c)]
    body = _tio.resolve_timl_entry(active)
    return [body] if _tio._entry_has_timl(body) else []


# ─────────────────────────────────────────────────────────────────────────────
# 通道遍历。构建与同步共用，必须保持 synthetic 编号和 transform 冲突判定一致。
# ─────────────────────────────────────────────────────────────────────────────

def _walk_channels(t):
    """按确定顺序产出通道描述符列表。ALL 语义（两轴全建），无 focus 过滤。"""
    channels = []
    used_slots = set()
    ci = 0
    for slot, d in enumerate(t.animations):
        if d is None:
            continue
        for ty in d.types:
            for f in ty.transforms:
                labels = _timl.channel_sublabels(f.data_type, f.datatype_hash)
                tmap = _tn.transform_mapping(f.datatype_hash) if (
                    f.data_type == 2 and len(labels) == 1) else None
                if tmap is not None and (tmap[0], tmap[1]) not in used_slots:
                    bl_prop, bl_index, kind = tmap
                    used_slots.add((bl_prop, bl_index))
                    channels.append({"mode": "xform", "tf": f, "kind": kind,
                                     "bl_index": bl_index, "path": bl_prop, "index": bl_index})
                else:
                    for sub_idx, sub_label in enumerate(labels):
                        channels.append({
                            "mode": "syn", "tf": f, "sub": sub_idx, "index": 0, "ci": ci,
                            "path": "efx_timl_channels[%d].value" % ci,
                            "gname": _channel_group_name(d.anim_index, ty.timeline_param_hash,
                                                         f.datatype_hash, f.data_type, sub_label)})
                        ci += 1
    return channels


def _get_timl_action(handle):
    ad = handle.animation_data if handle is not None else None
    return ad.action if ad is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# 导入建 fcurve / 导出同步回字节 / 结构重建
# ─────────────────────────────────────────────────────────────────────────────

_TIML_ACTION_MARKER = "~EFX_TIML_FC"   # 持久 TIML Action 标记


def build_persistent_fcurves(handle, body):
    """从 TIML 字节重建句柄上的持久 F 曲线，返回通道数。

    空、不可解析或无动画的 TIML 清空 F 曲线，导出时保留原字节。
    """
    if handle is None or body is None:
        return 0
    data = _tio._entry_timl_bytes(body)
    t = _timl.parse_timl(data)
    if t is None or not any(a is not None for a in t.animations):
        _clear_timl_fcurves(handle)
        return 0

    handle.efx_timl_channels.clear()
    act = _get_timl_action(handle)
    if act is None:
        act = bpy.data.actions.new("EFX_TIML::%s" % (body.get("efx_raw_label", "") or body.name))
        act.use_fake_user = True
        act[_TIML_ACTION_MARKER] = 1
        if handle.animation_data is None:
            handle.animation_data_create()
        handle.animation_data.action = act
    else:
        # 重建路径允许创建新版 API 所需的 channelbag。
        fcs = _act_fcurves(act, handle, create=True)
        while len(fcs):
            fcs.remove(fcs[0])

    channels = _walk_channels(t)
    for ch in channels:
        f = ch["tf"]
        decoded = [_timl.decode_keyframe(kf.raw, f.data_type, f.datatype_hash)
                   for kf in f.keyframes]
        decoded.sort(key=lambda d: d["frame"])
        if ch["mode"] == "xform":
            fc = _act_fcurves(act, handle, create=True).new(
                data_path=ch["path"], index=ch["index"])
            sub_of = lambda dec: dec["subs"][0]
            to_bl = lambda v: _tn.game_to_blender(ch["kind"], ch["bl_index"], v)
        else:
            handle.efx_timl_channels.add()   # 集合索引必须对应 ``ch["ci"]``。
            fc = _act_fcurves(act, handle, create=True).new(data_path=ch["path"], index=0,
                                               action_group=ch["gname"])
            sub_of = lambda dec, _i=ch["sub"]: dec["subs"][_i]
            to_bl = float
        segs, values = [], []
        for dec in decoded:
            s = sub_of(dec)
            val = float(to_bl(s["value"]))
            kp = fc.keyframe_points.insert(dec["frame"], val)
            tangents = _timl.sub_tangents(s)
            _set_kp(kp, dec["transition"], *tangents)
            segs.append((dec["transition"],) + tuple(float(x) for x in tangents))
            values.append(val)
        fc.update()
        _apply_hermite_handles(fc, segs, values)
    return len(channels)


def sync_fcurves_to_bytes(handle, body):
    """将持久 F 曲线值合并回 TIML 并返回序列化字节。

    不可解析或没有 F 曲线时原样返回输入字节。
    """
    data = _tio._entry_timl_bytes(body)
    t = _timl.parse_timl(data)
    if t is None:
        return data
    act = _get_timl_action(handle)
    if act is None or not len(_act_fcurves(act, handle)):
        return data

    channels = _walk_channels(t)
    by_tf = {}
    for ch in channels:
        e = by_tf.setdefault(id(ch["tf"]), {"tf": ch["tf"], "xform": None, "syn": {}})
        if ch["mode"] == "xform":
            e["xform"] = ch
        else:
            e["syn"][ch["sub"]] = ch
    for e in by_tf.values():
        tf = e["tf"]
        if e["xform"] is not None:
            tf.keyframes = _rebuild_xform(act, handle, e["xform"], tf)
        else:
            tf.keyframes = _rebuild_synthetic(act, handle, e["syn"], tf)
    t.dirty = True
    return t.serialize()


def _clear_timl_fcurves(handle):
    """清空句柄上的持久 TIML F 曲线和 synthetic 通道。"""
    act = _get_timl_action(handle)
    if act is not None:
        try:
            fcs = _act_fcurves(act, handle)
            while len(fcs):
                fcs.remove(fcs[0])
        except Exception:
            pass
    try:
        handle.efx_timl_channels.clear()
    except Exception:
        pass


def _rebuild_xform(act, timl_obj, ch, tf):
    fc = _ch_fcurve(act, timl_obj, ch)
    if fc is None:
        return []
    kind, bl_index = ch["kind"], ch["bl_index"]
    out = []
    kps = _sorted_kps(fc)
    for i, kp in enumerate(kps):
        fr = round(kp.co[0], 4)
        game_v = _tn.blender_to_game(kind, bl_index, kp.co[1])
        transition, t0, t1, _ = _segment_spec(fc, kp, kps[i + 1] if i + 1 < len(kps) else None)
        subs = [_timl.make_sub(game_v, t0, t1)]
        raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, fr,
                                    transition, tf.data_type, subs)
        out.append(_timl.TimlKeyframe(raw=raw, frame_timing=fr,
                                      transition=transition, data_type=tf.data_type))
    return out


def _rebuild_synthetic(act, timl_obj, syn, tf):
    labels = _timl.channel_sublabels(tf.data_type, tf.datatype_hash)
    sub_fcurves = [_ch_fcurve(act, timl_obj, syn[i]) if i in syn else None for i in range(len(labels))]
    frames = set(); kp_maps = []; kp_next = []
    for fc in sub_fcurves:
        m = {}; nx = {}
        if fc is not None:
            kps = _sorted_kps(fc)
            for i, kp in enumerate(kps):
                fr = round(kp.co[0], 4); m[fr] = kp; frames.add(fr)
                nx[fr] = kps[i + 1] if i + 1 < len(kps) else None
        kp_maps.append(m); kp_next.append(nx)
    if not frames:
        return []
    out = []
    for fr in sorted(frames):
        # 游戏里多个子通道（如 RGBA）共用一个插值和一对切线：取落差最大的那条子通道来算
        spec, best = (2, 0.0, 0.0, None), -1.0   # 没有子通道关键帧时回退 Linear
        for i, fc in enumerate(sub_fcurves):
            kp = kp_maps[i].get(fr)
            if kp is None:
                continue
            nxt = kp_next[i].get(fr)
            drop = abs(nxt.co[1] - kp.co[1]) if nxt is not None else 0.0
            if drop > best:
                spec, best = _segment_spec(fc, kp, nxt), drop
        transition, t0, t1 = spec[0], spec[1], spec[2]
        shared = tf.data_type == 3      # Color 的两个控制值由 RGBA 共用；BIG_FLAGS 的高低两半各存一份
        subs = []
        for i, fc in enumerate(sub_fcurves):
            kp = kp_maps[i].get(fr)
            fill = (t0, t1) if shared else (0.0, 0.0)
            if fc is None:
                subs.append(_timl.make_sub(0.0, *fill))
            elif kp is not None:
                subs.append(_timl.make_sub(kp.co[1], *((t0, t1) if shared else (kp.back, kp.period))))
            else:
                subs.append(_timl.make_sub(fc.evaluate(fr), *fill))
        raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, fr,
                                    transition, tf.data_type, subs)
        out.append(_timl.TimlKeyframe(raw=raw, frame_timing=fr,
                                      transition=transition, data_type=tf.data_type))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TIML 字节写入入口。
# ─────────────────────────────────────────────────────────────────────────────

def read_model(body):
    """解析 body 当前 timl_bytes 为 Timl 模型（展示/结构编辑用）；无/非-timl → None。"""
    return _timl.parse_timl(_tio._entry_timl_bytes(body))


def _store_bytes(body, data):
    body["timl_bytes"] = base64.b64encode(bytes(data)).decode("ascii")
    body["timl_length"] = str(len(data))


def commit_fcurves_to_bytes(body):
    """将当前 F 曲线值提交到 ``timl_bytes``。

    结构编辑前必须调用，避免重建时覆盖尚未提交的关键帧修改。
    """
    if body is None:
        return
    from . import io_tree as _iot
    h = _iot.find_timl_handle(body)
    if h is None:
        return
    try:
        _store_bytes(body, sync_fcurves_to_bytes(h, body))
    except Exception:
        pass


def set_entry_timl(body, new_bytes):
    """写入 TIML 字节并同步创建、删除或重建关联句柄和 F 曲线。

    调用者在结构编辑前负责提交 F 曲线；传入的新字节始终为准。
    """
    # 字段动画状态缓存随 TIML 字节失效。
    try:
        from . import timl_tracks as _tt
        _tt.invalidate_anim_cache()
    except Exception:
        pass
    from . import io_tree as _iot
    new_bytes = bytes(new_bytes)
    _store_bytes(body, new_bytes)
    h = _iot.find_timl_handle(body)
    if not new_bytes:
        if h is not None:
            _delete_timl_handle(h)
        return
    if h is None:
        h = _iot.make_timl_handle(body)
    build_persistent_fcurves(h, body)


def _delete_timl_handle(handle):
    """删除 TIML 句柄对象及其持久 Action（清 fake_user 防残留）。"""
    act = _get_timl_action(handle)
    if act is not None:
        try:
            act.use_fake_user = False
            bpy.data.actions.remove(act, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.data.objects.remove(handle, do_unlink=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 网格预览绑定。
# ─────────────────────────────────────────────────────────────────────────────

_PREVIEW_FLAG = "efx_timl_preview_on"
_FR_BACKUP = ("efx_timl_fr0", "efx_timl_fr1")
_BOUND_MARKER = "~EFX_TIML_BOUND"
_CON_NAME = "EFX_TIML_PREVIEW"


def _bind_entry_mesh(body, handle):
    """给 body 绑定的 MESH 加 Child-Of 约束跟随句柄动画。成功返回 True。"""
    try:
        mesh = _uvc._entry_mesh_target(body)
    except Exception:
        mesh = None
    if mesh is None:
        return False
    try:
        con = mesh.constraints.new("CHILD_OF")
        con.name = _CON_NAME
        con.target = handle
        # 句柄世界矩阵是 TIML 绝对变换，抵消 Entry 静态摆位后网格完全跟随句柄。
        con.inverse_matrix = body.matrix_world.inverted_safe()
        mesh[_BOUND_MARKER] = 1
        return True
    except Exception:
        return False


def unbind_all():
    """按标记解绑所有 TIML 预览网格。"""
    for mesh in _sc.iter_marked(_BOUND_MARKER):
        try:
            con = mesh.constraints.get(_CON_NAME)
            if con is not None:
                mesh.constraints.remove(con)
        except Exception:
            pass
        try:
            del mesh[_BOUND_MARKER]
        except Exception:
            pass


def _frame_range(bodies):
    """从这些 body 句柄的 fcurve 求 [fmin, fmax]。"""
    from . import io_tree as _iot
    fmin, fmax = 0.0, 1.0
    for body in bodies:
        h = _iot.find_timl_handle(body)
        if h is None:
            continue
        act = _get_timl_action(h)
        if act is None:
            continue
        for fc in _act_fcurves(act, h):
            for kp in fc.keyframe_points:
                fmin = min(fmin, kp.co[0]); fmax = max(fmax, kp.co[0])
    return fmin, fmax


def _select_handles(context, bodies):
    """选中这些 body 的 TIML 句柄并把第一个设为 active（Dope/Graph 默认只显示选中物体）。"""
    from . import io_tree as _iot
    try:
        for obj in context.view_layer.objects:
            obj.select_set(False)
    except Exception:
        pass
    first = None
    for body in bodies:
        h = _iot.find_timl_handle(body)
        if h is None:
            continue
        try:
            h.select_set(True)
            if first is None:
                first = h
        except Exception:
            pass
    if first is not None:
        try:
            context.view_layer.objects.active = first
        except Exception:
            pass


def preview_active(context) -> bool:
    return bool(context.scene.get(_PREVIEW_FLAG))


# ─────────────────────────────────────────────────────────────────────────────
# Operators：进入预览（绑定）/ 退出预览（解绑）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_edit_enter(Operator):
    """绑定网格到 TIML 句柄并设置预览帧范围。"""
    bl_idname = "efx.timl_edit_enter"
    bl_label = "Browse TIML Transform"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if preview_active(context):
            return False
        return bool(_resolve_scope_bodies(context))

    def execute(self, context):
        bodies = _resolve_scope_bodies(context)
        if not bodies:
            self.report({"ERROR"}, T("timle.no_timl"))
            return {"CANCELLED"}
        unbind_all()
        scene = context.scene
        scene[_FR_BACKUP[0]] = scene.frame_start
        scene[_FR_BACKUP[1]] = scene.frame_end
        # Child-Of 的 inverse_matrix 必须在起始帧求值后捕获，才能固定预览参考系。
        fmin, fmax = _frame_range(bodies)
        scene.frame_start = int(fmin)
        scene.frame_end = max(int(round(fmax)), int(fmin) + 1)
        try:
            scene.frame_set(scene.frame_start)
            context.view_layer.update()
        except Exception:
            pass
        nbound = 0
        for body in bodies:
            from . import io_tree as _iot
            h = _iot.find_timl_handle(body)
            if h is not None and _bind_entry_mesh(body, h):
                nbound += 1
        _select_handles(context, bodies)
        scene[_PREVIEW_FLAG] = 1
        self.report({"INFO"}, T("timle.entered").format(nbound))
        return {"FINISHED"}


class EFX_OT_timl_edit_exit(Operator):
    """解绑预览网格并恢复场景帧范围。"""
    bl_idname = "efx.timl_edit_exit"
    bl_label = "Exit TIML Preview"
    bl_options = {"REGISTER"}

    # 保留旧调用签名兼容；编辑始终持久化。
    apply: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return preview_active(context)

    def execute(self, context):
        unbind_all()
        scene = context.scene
        try:
            if _FR_BACKUP[0] in scene:
                scene.frame_start = int(scene[_FR_BACKUP[0]])
            if _FR_BACKUP[1] in scene:
                scene.frame_end = int(scene[_FR_BACKUP[1]])
        except Exception:
            pass
        for k in (_PREVIEW_FLAG,) + _FR_BACKUP:
            try:
                del scene[k]
            except Exception:
                pass
        self.report({"INFO"}, T("timle.cancelled"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 色轮：将 RGB(A) synthetic 标量通道聚合为当前帧编辑控件。
# ─────────────────────────────────────────────────────────────────────────────

def _current_ctx(context):
    """返回活动 Entry 的 TIML 句柄、Action 和通道；不可编辑时返回 ``None``。"""
    try:
        body = _tio.resolve_timl_entry(context.active_object)
    except Exception:
        return None
    if body is None:
        return None
    from . import io_tree as _iot
    h = _iot.find_timl_handle(body)
    if h is None:
        return None
    act = _get_timl_action(h)
    if act is None or not len(_act_fcurves(act, h)):
        return None
    t = read_model(body)
    if t is None:
        return None
    return {"handle": h, "body": body, "act": act, "channels": _walk_channels(t)}


def _find_color_groups(channels):
    """按 tf 聚合所有 dataType==Color(3) 的 synthetic 通道组。"""
    groups = {}
    order = []
    for ch in channels:
        if ch["mode"] != "syn" or ch["tf"].data_type != 3:
            continue
        key = id(ch["tf"])
        if key not in groups:
            groups[key] = {"tf": ch["tf"], "subs": {}}
            order.append(key)
        groups[key]["subs"][ch["sub"]] = ch
    return [groups[k] for k in order if len(groups[k]["subs"]) >= 3]


def _active_color_group(ctx):
    """确定色轮的目标组；多组时仅接受被选中 F 曲线所属的组。"""
    groups = _find_color_groups(ctx["channels"])
    if not groups:
        return None
    if len(groups) == 1:
        return groups[0]
    for g in groups:
        for ch in g["subs"].values():
            fc = _ch_fcurve(ctx["act"], ctx["handle"], ch)
            if fc is not None and fc.select:
                return g
    return None


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
        ctx = _current_ctx(bpy.context)
        if ctx is None:
            return (0.0, 0.0, 0.0)
        group = _active_color_group(ctx)
        if group is None:
            return (0.0, 0.0, 0.0)
        frame = bpy.context.scene.frame_current
        out = [0.0, 0.0, 0.0]
        for i in range(3):
            fc = _ch_fcurve(ctx["act"], ctx["handle"], group["subs"][i]) if i in group["subs"] else None
            if fc is not None:
                out[i] = max(0.0, min(255.0, fc.evaluate(frame))) / 255.0
        return tuple(out)
    except Exception:
        return (0.0, 0.0, 0.0)


def _color_wheel_set(self, value):
    try:
        ctx = _current_ctx(bpy.context)
        if ctx is None:
            return
        group = _active_color_group(ctx)
        if group is None:
            return
        frame = bpy.context.scene.frame_current
        for i in range(3):
            fc = _ch_fcurve(ctx["act"], ctx["handle"], group["subs"].get(i)) if i in group["subs"] else None
            if fc is not None:
                _write_scalar_keyframe(fc, frame, max(0.0, min(1.0, value[i])) * 255.0)
    except Exception:
        pass


def _color_alpha_get(self):
    try:
        ctx = _current_ctx(bpy.context)
        if ctx is None:
            return 1.0
        group = _active_color_group(ctx)
        if group is None or 3 not in group["subs"]:
            return 1.0
        fc = _ch_fcurve(ctx["act"], ctx["handle"], group["subs"][3])
        if fc is None:
            return 1.0
        return max(0.0, min(255.0, fc.evaluate(bpy.context.scene.frame_current))) / 255.0
    except Exception:
        return 1.0


def _color_alpha_set(self, value):
    try:
        ctx = _current_ctx(bpy.context)
        if ctx is None:
            return
        group = _active_color_group(ctx)
        if group is None or 3 not in group["subs"]:
            return
        fc = _ch_fcurve(ctx["act"], ctx["handle"], group["subs"][3])
        if fc is not None:
            _write_scalar_keyframe(fc, bpy.context.scene.frame_current, max(0.0, min(1.0, value)) * 255.0)
    except Exception:
        pass


def draw_color_wheel(layout, context):
    """TIML 色轮控件：聚合当前选中颜色通道组的 R/G/B(/A) 为一个色轮 + Alpha 滑条。"""
    ctx = _current_ctx(context)
    if ctx is None:
        layout.label(text=T("timle.color_need_session"), icon="INFO")
        return
    groups = _find_color_groups(ctx["channels"])
    if not groups:
        layout.label(text=T("timle.color_none"), icon="INFO")
        return
    group = _active_color_group(ctx)
    if group is None:
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
        return _current_ctx(context) is not None

    def draw(self, context):
        try:
            draw_color_wheel(self.layout, context)
        except Exception:
            import traceback
            self.layout.label(text=T("ui.error_console"), icon="ERROR")
            traceback.print_exc()


class EFX_PT_timl_color_wheel_graph(EFX_PT_timl_color_wheel):
    """曲线编辑器侧栏：与 Dope Sheet 完全相同的色轮面板。"""

    bl_space_type = "GRAPH_EDITOR"


# ─────────────────────────────────────────────────────────────────────────────
# 绘制控件（供 timl_io 的 TIML 面板调用）
# ─────────────────────────────────────────────────────────────────────────────

def draw_edit_controls(layout, context):
    """持久化模型：TIML 始终在 Dope Sheet 可编辑；此处提供网格预览的绑定/解绑开关。"""
    if preview_active(context):
        box = layout.box()
        box.label(text=T("timle.editor_hint"), icon="ACTION")
        row = box.row()
        row.scale_y = 1.3
        op = row.operator("efx.timl_edit_exit", text=T("timle.cancel"), icon="X")
        op.apply = False
    else:
        layout.prop(context.scene, "efx_timle_all_bodies", text=T("timle.all_bodies"))
        row = layout.row()
        row.scale_y = 1.3
        row.operator("efx.timl_edit_enter", text=T("timle.enter"), icon="FCURVE")
        layout.label(text=T("timle.enter_hint"), icon="INFO")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

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
        name="All entries in this EFX",
        description="Preview the TIML of every entry in the current EFX collection at once",
        default=False,
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
    try:
        unbind_all()
    except Exception:
        pass
    if hasattr(bpy.types.Scene, "efx_timle_color_a"):
        del bpy.types.Scene.efx_timle_color_a
    if hasattr(bpy.types.Scene, "efx_timle_color_rgb"):
        del bpy.types.Scene.efx_timle_color_rgb
    if hasattr(bpy.types.Scene, "efx_timle_all_bodies"):
        del bpy.types.Scene.efx_timle_all_bodies
    if hasattr(bpy.types.Object, "efx_timl_channels"):
        del bpy.types.Object.efx_timl_channels
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
