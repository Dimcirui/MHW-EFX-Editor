"""
blender_efx/timl_edit.py  —  持久化 TIML 通道编辑（Phase 3：导入即建 fcurve，字节=结构权威）

模型（见 memory timl-fcurve-persistence-refactor-plan / timl-phase3-persistent-fcurve-detail）
------------------------------------------------------------------------------------------
- **EFX 导入时**即把 entry 的 TIML 解析成句柄(EFX_TIML)Action 上的**持久原生 fcurve**
  （`build_persistent_fcurves`）。fcurve 是「值编辑面」，用户随时在 Dope/Graph 里改值/帧/插值。
- **导出时**把 fcurve 值合并回 `timl_bytes` 结构再序列化（`sync_fcurves_to_bytes`，io_tree 调）。
- **timl_bytes = 结构权威**（labelHash/dataIx/loop/轴/hash/顺序/opaque，fcurve 装不下）。
- **弃 Apply/Cancel**：编辑即时持久（像普通 Blender 动画），丢弃靠原生 Ctrl+Z——由构造闭合
  "Apply后撤销不回态 / 会话内撤销失效"两个旧 bug。进入/退出编辑退化为**绑定/解绑网格预览**。
- **单一咽喉点 `set_entry_timl`**：所有 timl_bytes 变更（新建/替换/删除）必经它，写字节+建/删句柄+
  从新字节重建 fcurve——否则 fcurve 陈旧，导出会拿旧 fcurve 反向覆盖新字节丢数据。结构编辑先
  `commit_fcurves_to_bytes` 提交进行中的关键帧编辑，再改字节、再 set_entry_timl 重建。
- byte-perfect：build→sync 全语料逐字节还原（仅变换值 loc/rot 亚-ULP 用户已接受，见
  timl-loc-fcurve-precision-finding）；不再靠脏门控/未编辑短路。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层；硬逻辑在 efx_format/timl*.py。
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
from ..efx_format import timl_names as _tn


# ─────────────────────────────────────────────────────────────────────────────
# Action fcurves 兼容层（Blender 4.4+ 把 Action 改成 layers/strips/slots/channelbag）
# ─────────────────────────────────────────────────────────────────────────────
# 4.4+ Action.fcurves 被移除（AttributeError，非 deprecated）；旧版(<4.4，含 3.6/4.3 目标运行
# 版本)仍是直接 F 曲线集合。这层薄代理把两套 API 收敛成旧版接口，业务代码统一走 _act_fcurves()。
# ⚠ 判据必须用 bpy.app.version（类级 RNA 数据属性 hasattr 不可靠，4.3 上误返回 False）。
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


def _ensure_channelbag(act, timl_obj):
    """新版(4.4+) API 专用：按需建 slot/layer/strip，返回 timl_obj 对应的 ActionChannelbag。"""
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


# ── 插值类型映射（游戏 transition/easingMethod ↔ Blender fcurve interpolation）──────
# 游戏枚举权威见 efx_format/timl.py::INTERP_NAMES（refs/EFX_Crimson.bt + EFX_TIML.bt）。
# 游戏没有自由贝塞尔，只有一张固定多项式缓动枚举；且 Stuck(0)/Constant(1) 都得塌缩到
# Blender 唯一的 CONSTANT（Blender 无法区分二者）。因映射非双射，正查/反查分两张表。
_GAME_TO_BLENDER_INTERP = {
    0: "CONSTANT",   # Stuck（步进，Blender 无独立档，并入 CONSTANT）
    1: "CONSTANT",   # Constant（常量）
    2: "LINEAR",     # Linear（线性）
    3: "QUAD",       # Quadratic（二次）
    4: "CUBIC",      # Cubic（三次）
}
# 导出：Blender interpolation → 游戏 transition。忽略 Stuck(0)，常量统一写 1。
_BLENDER_TO_GAME_INTERP = {
    "CONSTANT": 1,
    "LINEAR":   2,
    "QUAD":     3,
    "CUBIC":    4,
}
# BEZIER = Blender 新建关键帧的默认插值，游戏无对应 → 导出近似为 Cubic + WARNING（不阻拦）。
# 其余（SINE/EXPO/QUART/QUINT/CIRC/BACK/BOUNCE/ELASTIC）无游戏对应 → ERROR，validate 阻止导出。
_SUPPORTED_INTERP_DESC = "Constant / Linear / Quadratic / Cubic (Bezier is approximated as Cubic)"


def _interp_to_blender(transition):
    """游戏 transition 整数 → Blender fcurve interpolation 枚举名（导入用）。
    未知值（如 Int/Flag 才用的 5/6）安全退 LINEAR。"""
    return _GAME_TO_BLENDER_INTERP.get(transition, "LINEAR")


def _blender_to_transition(interp):
    """Blender fcurve interpolation 枚举 → 游戏 transition 整数（导出用）。
    BEZIER 近似为 Cubic；其余未知类型安全退 Linear（这类应已被 validate 拦成 ERROR，
    不该走到这里，退 Linear 只是兜底不崩）。"""
    m = _BLENDER_TO_GAME_INTERP.get(interp)
    if m is not None:
        return m
    if interp == "BEZIER":
        return _BLENDER_TO_GAME_INTERP["CUBIC"]
    return _BLENDER_TO_GAME_INTERP["LINEAR"]


def check_timl_interpolations(handle):
    """扫描 handle 持久 Action 的所有 fcurve 关键帧插值，返回问题列表：
        [{"severity": "ERROR"|"WARNING", "interp": <Blender枚举名>}, ...]（按类型去重）
    - CONSTANT/LINEAR/QUAD/CUBIC → 无问题
    - BEZIER → WARNING（导出会近似为 Cubic）
    - 其余 → ERROR（游戏无对应，应阻止导出，避免静默降级）
    供 validate_efx_tree 与独立 .timl 导出复用。"""
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
            kps = fc.keyframe_points
        except Exception:
            continue
        for kp in kps:
            it = kp.interpolation
            if it in seen or it in _BLENDER_TO_GAME_INTERP:
                seen.add(it)
                continue
            seen.add(it)
            out.append({"severity": "WARNING" if it == "BEZIER" else "ERROR",
                        "interp": it})
    return out


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
# 通道走法（纯遍历，build 与 sync 共用 → synthetic ci 编号 / xform 碰撞判定一致）
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
    """导入用：从 body 的 timl_bytes 在 handle 的 Action 上建**持久** fcurve（幂等：先清后建）。
    空 TIML / 死数据（无非空动画）/ 非-timl → 不建 fcurve，返回 0（导出时走 verbatim）。返回通道数。"""
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
        fcs = _act_fcurves(act, handle)
        while len(fcs):
            fcs.remove(fcs[0])

    channels = _walk_channels(t)
    for ch in channels:
        f = ch["tf"]
        decoded = [_timl.decode_keyframe(kf.raw, f.data_type, f.datatype_hash)
                   for kf in f.keyframes]
        if ch["mode"] == "xform":
            fc = _act_fcurves(act, handle).new(data_path=ch["path"], index=ch["index"])
            for dec in decoded:
                s = dec["subs"][0]
                val = _tn.game_to_blender(ch["kind"], ch["bl_index"], s["value"])
                kp = fc.keyframe_points.insert(dec["frame"], float(val))
                _set_kp(kp, dec["transition"], s["back"], s["period"])
            fc.update()
        else:
            handle.efx_timl_channels.add()   # 顺序 add → 集合索引 == ch["ci"]
            fc = _act_fcurves(act, handle).new(data_path=ch["path"], index=0,
                                               action_group=ch["gname"])
            for dec in decoded:
                s = dec["subs"][ch["sub"]]
                kp = fc.keyframe_points.insert(dec["frame"], float(s["value"]))
                _set_kp(kp, dec["transition"], s["back"], s["period"])
            fc.update()
    return len(channels)


def sync_fcurves_to_bytes(handle, body):
    """导出用：把 handle 的 fcurve 值合并回 body 的 timl_bytes 结构并序列化，返回新字节。
    无 fcurve / 非-timl → 原 timl_bytes verbatim（空/死数据/未建 fcurve 都走这条，保 byte-perfect）。"""
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
    """清空 handle 上的持久 TIML fcurve + synthetic 通道集合（结构重建/删除用）。"""
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


def rebuild_fcurves(handle, body):
    """结构编辑后：从当前 timl_bytes 重建 fcurve（= 清空 + build）。build 已幂等，直接转发。"""
    return build_persistent_fcurves(handle, body)


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
        transition = 2   # 默认 Linear（无子通道命中该帧时的兜底；新表 2=Linear）
        for i, fc in enumerate(sub_fcurves):
            kp = kp_maps[i].get(fr)
            if kp is not None:
                transition = _blender_to_transition(kp.interpolation); break
        raw = _timl.encode_keyframe(tf.data_type, tf.datatype_hash, fr,
                                    transition, tf.data_type, subs)
        out.append(_timl.TimlKeyframe(raw=raw, frame_timing=fr,
                                      transition=transition, data_type=tf.data_type))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 单一咽喉点 API（供 io/tracks/meta_ui 变更 TIML；见文件头"单一咽喉点"）
# ─────────────────────────────────────────────────────────────────────────────

def read_model(body):
    """解析 body 当前 timl_bytes 为 Timl 模型（展示/结构编辑用）；无/非-timl → None。"""
    return _timl.parse_timl(_tio._entry_timl_bytes(body))


def _store_bytes(body, data):
    body["timl_bytes"] = base64.b64encode(bytes(data)).decode("ascii")
    body["timl_length"] = str(len(data))   # 导出端也会再重算，双保险


def commit_fcurves_to_bytes(body):
    """把 body 句柄上 fcurve 的当前值同步进 timl_bytes（提交进行中的关键帧编辑）。
    结构编辑【前】调用，避免随后 rebuild 用旧字节冲掉正在改的关键帧。无句柄/无 fcurve → 无操作。"""
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
    """**所有 timl_bytes 变更（新建/替换/删除）的唯一咽喉点**：写字节+长度、按需建/删 EFX_TIML
    句柄、从新字节重建持久 fcurve。空 bytes → 删句柄+Action。不做 commit-first（新字节为准，
    旧 fcurve 编辑按替换语义丢弃）；结构编辑请在调用前先 commit_fcurves_to_bytes。"""
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
    build_persistent_fcurves(h, body)   # 幂等清+建；无动画则清空不建


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


def has_timl_fcurves(body):
    """body 句柄上是否有持久 TIML fcurve（供消费者判断 live 编辑面是否存在）。"""
    from . import io_tree as _iot
    h = _iot.find_timl_handle(body)
    if h is None:
        return False
    act = _get_timl_action(h)
    return act is not None and len(_act_fcurves(act, h)) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 网格预览绑定（进入/退出编辑退化为绑定/解绑）
# ─────────────────────────────────────────────────────────────────────────────

_PREVIEW_FLAG = "efx_timl_preview_on"    # Scene 上的预览开关
_FR_BACKUP = ("efx_timl_fr0", "efx_timl_fr1")   # 帧范围备份（Scene 自定义属性）
_BOUND_MARKER = "~EFX_TIML_BOUND"        # 被绑定跟随的 mesh 标记（session_core reconcile）
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
        con.inverse_matrix = handle.matrix_world.inverted()
        mesh[_BOUND_MARKER] = 1
        return True
    except Exception:
        return False


def unbind_all():
    """解绑所有被 TIML 预览绑定的 mesh（按标记 reconcile，脱节也不残留）。"""
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
    """浏览 TIML transform 效果：绑定网格跟随句柄的 TIML 动画 + 设帧范围（编辑随时在 Dope Sheet 进行）"""
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
        unbind_all()   # 先清场（历史遗留绑定）
        scene = context.scene
        scene[_FR_BACKUP[0]] = scene.frame_start
        scene[_FR_BACKUP[1]] = scene.frame_end
        # ⚠ 先设帧范围 + 跳到起始帧 + 刷新 depsgraph，让句柄按 t=0 求值，**再**绑定 mesh：
        # Child-Of 的 inverse_matrix 须在起始帧（参考系=t=0）捕获，否则在任意当前帧捕获会让
        # 网格运动错乱、且随捕获帧不同而不同（用户实测的"错乱"根因）。
        fmin, fmax = _frame_range(bodies)
        scene.frame_start = int(fmin)
        scene.frame_end = max(int(round(fmax)), int(fmin) + 1)
        try:
            scene.frame_set(scene.frame_start)
            context.view_layer.update()   # 强制 depsgraph 重算 handle.matrix_world 到 t=0
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
    """退出 TIML 预览：解绑网格、还原帧范围（编辑已持久，无需回写/丢弃）"""
    bl_idname = "efx.timl_edit_exit"
    bl_label = "Exit TIML Preview"
    bl_options = {"REGISTER"}

    # 兼容旧调用签名（efx_preview 曾传 apply=False）；现忽略——编辑始终持久。
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
# 色轮（Color Wheel）—— 把 RGB(A) 4 条 synthetic 标量通道聚合成一个色轮控件
# 持久化模型下 fcurve 始终存在，色轮随时可用；读写这 4 条真实 fcurve 在当前帧的关键帧
# （与直接在 Dope Sheet 逐条调值等价，导出走同一条 sync_fcurves_to_bytes 路径）。
# ─────────────────────────────────────────────────────────────────────────────

def _current_ctx(context):
    """当前活动 entry 的 {handle, body, act, channels}；无 TIML fcurve → None。"""
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
    """确定色轮当前操作哪一组：唯一一组直接用；多组按 fcurve.select 判定；都没选中则二义（None）。"""
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
            self.layout.label(text="TIML Color Wheel panel error (see console):", icon="ERROR")
            for line in traceback.format_exc().splitlines()[-4:]:
                self.layout.label(text=line[:80])
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
