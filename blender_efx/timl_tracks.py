"""添加、删除和复制 TIML 轨道，并提供字段与轨道面板入口。

维护约束：结构编辑先提交持久 F 曲线，随后经 ``set_entry_timl`` 重建。新增轨道
应以字段当前静态值作为首帧种子，避免改变当前外观；无 TIML 的可支持 Entry 可在
添加时创建空段。
"""

import base64

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty
from bpy.types import Operator, Panel

from .i18n import T
from .timl_meta_ui import _active_entry, _entry_timl_bytes, _store_timl
from ..efx_format import timl as _timl
from ..efx_format.timl.names import (
    BLOCK_TO_TLP, FIELD_TO_DT, DT_PALETTE,
    TLP_NAMES, DT_NAMES, DT_TRANSFORM,
    timeline_param_name, timeline_param_fullname, timeline_param_category,
    TLP_CATEGORIES,
    datatype_name, channel_label, block_native_axis,
)


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────

_SLOT_LABEL = {0: "A0", 1: "A1"}


def _is_zh() -> bool:
    try:
        from .i18n import get_lang
        return get_lang() == "ZH"
    except Exception:
        return False


# 新轨道首帧种子来自静态字段值；无法读取时由 DT_NEUTRAL 回退。
_SEED_SCALAR = {
    "FLOAT":  lambda it: [float(it.float_value)],
    "INT":    lambda it: [float(it.int_value)],
    "BYTE1":  lambda it: [float(it.byte1_value)],
    "SHORT1": lambda it: [float(it.short1_value)],
    "FLOAT2": lambda it: [float(v) for v in it.float2_value],
    "FLOAT3": lambda it: [float(v) for v in it.float3_value],
    "FLOAT4": lambda it: [float(v) for v in it.float4_value],
    "FLOAT6": lambda it: [float(v) for v in it.float6_value],
    "INT2":   lambda it: [float(v) for v in it.int2_value],
    "INT3":   lambda it: [float(v) for v in it.int3_value],
    "INT4":   lambda it: [float(v) for v in it.int4_value],
    "COLOUR":     lambda it: [float(v) for v in it.colour_value],
    "COLOR_RGBA": lambda it: [float(v) * 255.0 for v in it.color_rgba_value],
}


def _field_seed_values(block_type: str, field_name: str, n_dt: int):
    """读取字段当前值作为新增轨道种子；不可读时返回 ``None``。"""
    import bpy
    obj = bpy.context.active_object
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return None
    try:
        items = obj.efx_block.field_items
    except AttributeError:
        return None
    item = None
    for it in items:
        if it.ori_name == field_name:
            item = it
            break
    if item is None:
        return None
    reader = _SEED_SCALAR.get(item.data_type)
    if reader is None:
        return None
    try:
        vals = reader(item)
    except (AttributeError, TypeError, ValueError):
        return None
    if not vals:
        return None
    if n_dt == 1:
        return [vals if len(vals) > 1 else vals[0]]
    if n_dt == 3 and len(vals) == 6:
        # 三条 DT 取 FLOAT6 成对值中的 0/2/4，而非抖动分量。
        return [vals[0], vals[2], vals[4]]
    # 其余按位置对齐，缺少分量时重复最后一项。
    return [vals[i] if i < len(vals) else vals[-1] for i in range(n_dt)]


def _resolve_for_edit():
    """提交当前 F 曲线后解析待编辑 TIML，返回 ``(body, timl)``。"""
    body = _active_entry()
    if body is None:
        return None, None
    from . import timl_edit as _te
    _te.commit_fcurves_to_bytes(body)
    timl = _te.read_model(body)
    return (body, timl) if timl is not None else (None, None)


def _ensure_timl_segment():
    """确保活动 Entry 有 TIML 段，必要时通过统一入口创建空段。"""
    if _active_entry() is not None:
        return True, False
    body = _timl_capable_entry()
    if body is None:
        return False, False
    if body.get("~TYPE") == "EFX_ENTRY" and \
            str(body.get("entry_kind", "")) != "standard":
        return False, False
    from ..efx_format.timl import make_blank_timl
    from . import timl_edit as _te
    _te.set_entry_timl(body, make_blank_timl())
    return _active_entry() is not None, True


def _commit_edit(body, timl):
    """通过 TIML 统一入口提交结构编辑并重建持久 F 曲线。"""
    from . import timl_edit as _te
    _te.set_entry_timl(body, timl.serialize())


def _read_for_display():
    """从当前 Entry 字节读取供面板展示的 TIML。"""
    body = _active_entry()
    if body is None:
        return None, None
    return body, _timl.parse_timl(_entry_timl_bytes(body))


# 字段动画状态缓存按 Entry 名和字节长度失效，由 ``set_entry_timl`` 显式清理。
_ANIM_CACHE = {"key": None, "set": frozenset()}


def invalidate_anim_cache():
    """TIML 字节被改写后清缓存（由 timl_edit.set_entry_timl 调用）。"""
    _ANIM_CACHE["key"] = None


def entry_animated_channels():
    """当前 entry 的 TIML 里已存在的 (tlp_hash, dt_hash) 集合；无 TIML 返回空集。"""
    body = _active_entry()
    if body is None:
        return frozenset()
    try:
        raw = _entry_timl_bytes(body)
    except Exception:
        return frozenset()
    if not raw:
        return frozenset()
    key = (body.name, len(raw))
    if _ANIM_CACHE["key"] == key:
        return _ANIM_CACHE["set"]
    out = set()
    try:
        timl_obj = _timl.parse_timl(raw)
        for anim in (getattr(timl_obj, "animations", None) or []):
            if anim is None:
                continue
            for t in anim.types:
                tlp = t.timeline_param_hash & 0xFFFFFFFF
                for tf in t.transforms:
                    out.add((tlp, tf.datatype_hash & 0xFFFFFFFF))
    except Exception:
        out = set()
    _ANIM_CACHE["key"] = key
    _ANIM_CACHE["set"] = frozenset(out)
    return _ANIM_CACHE["set"]


def _timl_capable_entry():
    """返回可承载 TIML 的活动 Entry，不要求其已存在 TIML 段。"""
    try:
        from .timl_io import resolve_timl_entry, _entry_is_timl_capable
        obj = resolve_timl_entry(bpy.context.active_object)
        return obj if _entry_is_timl_capable(obj) else None
    except Exception:
        return None


def _track_exists(timl_obj, slot: int, tlp_hash: int, dt_hash: int) -> bool:
    """检查 (slot, tlp_hash, dt_hash) 通道是否已存在。"""
    if slot >= len(timl_obj.animations) or timl_obj.animations[slot] is None:
        return False
    for t in timl_obj.animations[slot].types:
        if (t.timeline_param_hash & 0xFFFFFFFF) == (tlp_hash & 0xFFFFFFFF):
            for tf in t.transforms:
                if (tf.datatype_hash & 0xFFFFFFFF) == (dt_hash & 0xFFFFFFFF):
                    return True
    return False


# 值槽 dtype → 该参数在 TIML 侧拆成几条分量轨道（向量参数逐分量各一条：
# mUVRange → UVRangeX/Y/Z/W）。颜色是单条，所以 FLOAT4 走 4 分量之前会先试整名，
# 由 ptbehavior_param_channels 内部处理。
_PTB_COMPONENTS = {"FLOAT4": 4, "FLOAT3": 3, "FLOAT2": 2,
                   "INT4": 4, "INT3": 3, "INT2": 2}


def _ptbehavior_channel(attr_obj, item):
    """解析 PTBEHAVIOR 参数对应的 TLP 与 DT 通道；不可动画时返回 ``None``。"""
    from ..efx_format.timl.names import ptbehavior_param_channels

    name = getattr(item, "hint_name", "") if item else ""
    if not name:
        return None
    b_type = ""
    for it in attr_obj.efx_block.field_items:
        if it.ori_name == "b_type":
            b_type = it.string_value
            break
    if not b_type:
        return None

    n_comp = _PTB_COMPONENTS.get(item.data_type, 1)
    res = ptbehavior_param_channels(b_type, name, n_comp)
    if res is None:
        return None
    tlp, entries = res

    # 子类/基类候选中优先复用已有 TLP，避免同一属性分裂到两处。
    from ..efx_format.timl.names import ptbehavior_tlp_candidates
    cands = ptbehavior_tlp_candidates(b_type)
    if len(cands) > 1:
        body = _active_entry()
        if body is not None:
            try:
                t = _timl.parse_timl(_entry_timl_bytes(body))
                present = {ty.timeline_param_hash & 0xFFFFFFFF
                           for a in t.animations if a is not None for ty in a.types}
                for c in cands:
                    if c in present and c != tlp:
                        alt = ptbehavior_param_channels(b_type, name, n_comp)
                        if alt is not None and alt[0] == c:
                            tlp, entries = alt
                        break
            except Exception:
                pass
    return tlp, entries


def draw_field_timl_buttons(row, type_name: str, ori_name: str, item=None):
    """在字段标题行 row 上追加单个 +TIML 图标按钮（T2）。
    点击后弹出 popup 选 +A0/+A1。无 TIML 时灰显。

    两条路径：
      - 普通块：查 FIELD_TO_DT + BLOCK_TO_TLP 的静态映射，仅确认字段显示。
      - PTBEHAVIOR：TLP/DT 由 b_type 与参数名运行时算出（见 _ptbehavior_channel），
        算得出就显示。需要 item 才能拿到 hint_name（参数真名）。
    """
    tname = type_name.upper()
    tlp_hex = dt_hex = ""
    data_type = 0

    animated = False
    present = entry_animated_channels()
    if tname == "PTBEHAVIOR":
        if item is None:
            return
        # Inspector 可绘制非活动属性对象，必须使用 ``item.id_data``。
        obj = item.id_data
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return
        ch = _ptbehavior_channel(obj, item)
        if ch is None:
            return
        # 向量参数编码为多个 ``hash:dataType`` 通道。
        tlp_hex = "%08X" % ch[0]
        dt_hex = ",".join("%08X:%d" % (dt & 0xFFFFFFFF, dtp) for dt, dtp in ch[1])
        data_type = ch[1][0][1]
        animated = bool(present) and any(
            (ch[0] & 0xFFFFFFFF, dt & 0xFFFFFFFF) in present for dt, _dtp in ch[1])
    else:
        entries = FIELD_TO_DT.get((tname, ori_name))
        if not entries:
            return
        tlp = BLOCK_TO_TLP.get(tname)
        if tlp is None:
            return
        if present:
            animated = any((tlp & 0xFFFFFFFF, dt & 0xFFFFFFFF) in present
                           for dt, _dtype in entries)

    sub = row.row(align=True)
    # 可支持的 Entry 即使尚无 TIML 也可触发添加。
    sub.enabled = (_timl_capable_entry() is not None)
    op = sub.operator("efx.timl_field_add_menu", text="", icon="ANIM", depress=animated)
    op.block_type = tname
    op.field_name = ori_name
    op.tlp_hash_hex = tlp_hex
    op.dt_hash_hex = dt_hex
    op.dt_data_type = data_type


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T2 — 字段旁 +TIML 按钮弹出 popup（选 +A0 / +A1）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_field_add_menu(Operator):
    """显示字段轨道应添加到 A0 或 A1 的菜单。"""

    bl_idname = "efx.timl_field_add_menu"
    bl_label  = "+TIML"
    bl_options = {"INTERNAL"}

    block_type: StringProperty(default="")
    field_name: StringProperty(default="")
    # PTBEHAVIOR 通道在绘制时解析并直接透传。
    tlp_hash_hex: StringProperty(default="")
    dt_hash_hex:  StringProperty(default="")
    dt_data_type: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        return _timl_capable_entry() is not None   # 会话内/外均可；无 TIML 也放行

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=180)

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"{self.block_type} · {self.field_name}", icon="ANIM")
        layout.separator()
        # 添加操作会按需创建缺失的 TIML 段。
        if _active_entry() is None:
            layout.label(text=T("timl.will_create_segment"), icon="INFO")
            layout.separator()
        native = block_native_axis(self.block_type)

        specs = {0: ("+A0  (Emission)", "ANIM"), 1: ("+A1  (Lifetime)", "PARTICLES")}
        # 原生轴优先显示，另一轴仍可供用户选择。
        order = [native, 1 - native] if native in (0, 1) else [0, 1]
        for slot in order:
            txt, icon = specs[slot]
            if native in (0, 1):
                if slot == native:
                    txt += "  ★ 推荐" if _is_zh() else "  * recommended"
                else:
                    txt += "  ⚠"
            op = layout.operator("efx.timl_add_field_tracks", text=txt, icon=icon)
            op.block_type = self.block_type
            op.field_name = self.field_name
            op.slot = slot
            op.tlp_hash_hex = self.tlp_hash_hex
            op.dt_hash_hex  = self.dt_hash_hex
            op.dt_data_type = self.dt_data_type
        if native in (0, 1):
            axis_name = "A0" if native == 0 else "A1"
            layout.separator()
            layout.label(text=T("timl.other_axis").format(axis_name), icon="INFO")

    def execute(self, context):
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T2 — 按字段整组添加（translate→3条 pos:X/Y/Z）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_add_field_tracks(Operator):
    """为字段在指定轴添加其所有 DT 通道。"""

    bl_idname = "efx.timl_add_field_tracks"
    bl_label  = "Add Field TIML Tracks"
    bl_options = {"REGISTER", "UNDO"}

    block_type: StringProperty(default="")   # e.g. "TRANSFORM3D"
    field_name: StringProperty(default="")   # e.g. "translate"
    slot: IntProperty(default=0)             # 0=A0, 1=A1
    # PTBEHAVIOR 专用：绘制时算好的 TLP/DT 直传（见 draw_field_timl_buttons）
    tlp_hash_hex: StringProperty(default="")
    dt_hash_hex:  StringProperty(default="")
    dt_data_type: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        # 不要求已有 TIML，执行时会创建缺失段。
        return _timl_capable_entry() is not None

    def execute(self, context):
        if self.tlp_hash_hex and self.dt_hash_hex:
            # PTBEHAVIOR 通道允许多组 ``hash:dataType``，兼容旧式纯 hash。
            try:
                tlp_hash = int(self.tlp_hash_hex, 16)
                entries = []
                for tok in self.dt_hash_hex.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    if ":" in tok:
                        h, dtp = tok.split(":", 1)
                        entries.append((int(h, 16), int(dtp)))
                    else:
                        entries.append((int(tok, 16), int(self.dt_data_type)))
                if not entries:
                    raise ValueError
            except ValueError:
                self.report({"ERROR"}, "Invalid hash hex value")
                return {"CANCELLED"}
        else:
            key = (self.block_type.upper(), self.field_name)
            entries = FIELD_TO_DT.get(key)
            if not entries:
                self.report({"ERROR"}, f"'{self.field_name}' cannot be animated via a TIML track")
                return {"CANCELLED"}
            tlp_hash = BLOCK_TO_TLP.get(self.block_type.upper())
            if tlp_hash is None:
                self.report({"ERROR"}, f"'{self.block_type}' does not support TIML tracks")
                return {"CANCELLED"}
        ok, created = _ensure_timl_segment()
        if not ok:
            self.report({"ERROR"}, "This entry cannot carry a TIML segment")
            return {"CANCELLED"}
        body, timl = _resolve_for_edit()
        if timl is None:
            self.report({"ERROR"}, "No valid TIML found on active entry")
            return {"CANCELLED"}

        # 新轨道以静态字段值为首帧，读取失败时使用 DT_NEUTRAL。
        seeds = _field_seed_values(self.block_type.upper(), self.field_name, len(entries))

        added = 0
        for i, (dt_hash, data_type) in enumerate(entries):
            seed = seeds[i] if seeds is not None else None
            if _timl.add_transform(timl, self.slot, tlp_hash, dt_hash, data_type, seed=seed):
                added += 1
        if added == 0:
            self.report({"WARNING"}, "All tracks already exist")
            return {"CANCELLED"}

        _commit_edit(body, timl)
        slot_lbl = _SLOT_LABEL.get(self.slot, str(self.slot))
        note = " (TIML segment created)" if created else ""
        self.report({"INFO"},
                    f"Added {added} track(s) to {slot_lbl} for "
                    f"{self.block_type}.{self.field_name}{note}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: 按 TLP/DT 添加单条轨道。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_add_track(Operator):
    """在指定轴添加单条 TIML 轨道（TLP+DT hash 由调色板按钮提供）"""

    bl_idname = "efx.timl_add_track"
    bl_label  = "Add TIML Track"
    bl_options = {"REGISTER", "UNDO"}

    tlp_hash_hex: StringProperty(default="")
    dt_hash_hex:  StringProperty(default="")
    data_type:    IntProperty(default=2)
    slot:         IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        # 添加可在无 TIML 时创建空段；删除和复制则要求已有轨道。
        return _timl_capable_entry() is not None

    def execute(self, context):
        try:
            tlp = int(self.tlp_hash_hex, 16)
            dt  = int(self.dt_hash_hex,  16)
        except ValueError:
            self.report({"ERROR"}, "Invalid hash hex value")
            return {"CANCELLED"}
        ok, created = _ensure_timl_segment()
        if not ok:
            self.report({"ERROR"}, "This entry cannot carry a TIML segment")
            return {"CANCELLED"}
        body, timl = _resolve_for_edit()
        if timl is None:
            self.report({"ERROR"}, "No valid TIML found on active entry")
            return {"CANCELLED"}

        added = _timl.add_transform(timl, self.slot, tlp, dt, self.data_type)
        if not added:
            self.report({"WARNING"}, "Track already exists")
            return {"CANCELLED"}

        _commit_edit(body, timl)
        lbl = channel_label(tlp, dt)
        slot_lbl = _SLOT_LABEL.get(self.slot, str(self.slot))
        note = " (TIML segment created)" if created else ""
        self.report({"INFO"}, f"Added {lbl} → {slot_lbl}{note}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T1 — 删除单条轨道
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_delete_track(Operator):
    """删除指定轴的 TIML 轨道（空 type 一并移除）"""

    bl_idname = "efx.timl_delete_track"
    bl_label  = "Delete TIML Track"
    bl_options = {"REGISTER", "UNDO"}

    tlp_hash_hex: StringProperty(default="")
    dt_hash_hex:  StringProperty(default="")
    slot:         IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        return _active_entry() is not None

    def execute(self, context):
        try:
            tlp = int(self.tlp_hash_hex, 16)
            dt  = int(self.dt_hash_hex,  16)
        except ValueError:
            self.report({"ERROR"}, "Invalid hash hex value")
            return {"CANCELLED"}
        body, timl = _resolve_for_edit()
        if timl is None:
            self.report({"ERROR"}, "No valid TIML found on active entry")
            return {"CANCELLED"}

        ok = _timl.delete_transform(timl, self.slot, tlp, dt)
        if not ok:
            self.report({"WARNING"}, "Track not found")
            return {"CANCELLED"}

        _commit_edit(body, timl)
        lbl = channel_label(tlp, dt)
        self.report({"INFO"}, f"Deleted {lbl} from {_SLOT_LABEL.get(self.slot, str(self.slot))}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T1 — 跨轴复制（A0→A1 或 A1→A0）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_copy_track(Operator):
    """将 TIML 轨道从一条轴复制到另一条（A0↔A1；已有则覆盖）"""

    bl_idname = "efx.timl_copy_track"
    bl_label  = "Copy TIML Track"
    bl_options = {"REGISTER", "UNDO"}

    tlp_hash_hex: StringProperty(default="")
    dt_hash_hex:  StringProperty(default="")
    src_slot:     IntProperty(default=0)
    dst_slot:     IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        return _active_entry() is not None

    def execute(self, context):
        try:
            tlp = int(self.tlp_hash_hex, 16)
            dt  = int(self.dt_hash_hex,  16)
        except ValueError:
            self.report({"ERROR"}, "Invalid hash hex value")
            return {"CANCELLED"}
        body, timl = _resolve_for_edit()
        if timl is None:
            self.report({"ERROR"}, "No valid TIML found on active entry")
            return {"CANCELLED"}

        ok = _timl.copy_transform(timl, self.src_slot, self.dst_slot, tlp, dt)
        if not ok:
            self.report({"WARNING"}, "Source track not found")
            return {"CANCELLED"}

        _commit_edit(body, timl)
        lbl = channel_label(tlp, dt)
        src_lbl = _SLOT_LABEL.get(self.src_slot, str(self.src_slot))
        dst_lbl = _SLOT_LABEL.get(self.dst_slot, str(self.dst_slot))
        self.report({"INFO"}, f"Copied {lbl}: {src_lbl} → {dst_lbl}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# TIML 轨道面板。
# ─────────────────────────────────────────────────────────────────────────────

def _get_entry_attribute_tlps(entry_obj) -> set:
    """返回 Entry 属性对应的 TLP hash 集合。"""
    from ..efx_format.hashes import HASH_TO_NAME
    tlps = set()
    for child in entry_obj.children:
        if child.get("~TYPE") != "EFX_ATTRIBUTE":
            continue
        try:
            h = int(child.efx_block.type_hash_str)
            name = HASH_TO_NAME.get(h, "").upper()
            tlp = BLOCK_TO_TLP.get(name)
            if tlp is not None:
                tlps.add(tlp & 0xFFFFFFFF)
        except Exception:
            pass
    return tlps


# 动态 EnumProperty 回调必须返回持久列表。
_tlp_enum_cache = [("NONE", "— 无匹配属性 —", "")]


def _tlp_enum_items(self, context):
    """返回 TLP 下拉项；默认限制为当前 Entry，开放模式按分类列出。"""
    global _tlp_enum_cache
    if context is None:
        return _tlp_enum_cache

    wm = context.window_manager
    open_all = getattr(wm, "efx_timl_tracks_open_all", False)
    body = _active_entry()

    if open_all or body is None:
        # 开放模式仍按分类筛选。
        cat = getattr(wm, "efx_timl_tracks_category", "ALL")
        items = sorted(
            [("%08X" % h, timeline_param_name(h),
              "%s  ·  0x%08X" % (timeline_param_fullname(h), h))
             for h in DT_PALETTE
             if cat == "ALL" or timeline_param_category(h) == cat],
            key=lambda x: x[1],
        )
    else:
        # 保留 Entry 属性类型对应的 TLP。
        allowed = _get_entry_attribute_tlps(body)
        # 同时保留 TIML 中已有的 TLP。
        try:
            tb = _entry_timl_bytes(body)
            t = _timl.parse_timl(tb)
            if t:
                for anim in t.animations:
                    if anim:
                        for typ in anim.types:
                            allowed.add(typ.timeline_param_hash & 0xFFFFFFFF)
        except Exception:
            pass
        # 仅列出有调色板数据的 TLP。
        items = sorted(
            [("%08X" % h, timeline_param_name(h),
              "%s  ·  0x%08X" % (timeline_param_fullname(h), h))
             for h in allowed if h in DT_PALETTE],
            key=lambda x: x[1],
        )

    if not items:
        _tlp_enum_cache = [("NONE", "— 无匹配块类型 —", "")]
    else:
        _tlp_enum_cache = items
    return _tlp_enum_cache


def _draw_track_row(layout, slot: int, tlp_hash: int, dt_hash: int, timl_obj):
    """绘制一条轨道行：通道名 + [X删除] [→复制] 按钮。"""
    row = layout.row(align=True)
    row.label(text=datatype_name(dt_hash), icon="KEYFRAME")
    op = row.operator("efx.timl_delete_track", text="", icon="X")
    op.tlp_hash_hex = "%08X" % (tlp_hash & 0xFFFFFFFF)
    op.dt_hash_hex  = "%08X" % (dt_hash  & 0xFFFFFFFF)
    op.slot = slot
    dst = 1 - slot
    icon = "TRIA_DOWN" if dst == 1 else "TRIA_UP"
    op2 = row.operator("efx.timl_copy_track", text="", icon=icon)
    op2.tlp_hash_hex = "%08X" % (tlp_hash & 0xFFFFFFFF)
    op2.dt_hash_hex  = "%08X" % (dt_hash  & 0xFFFFFFFF)
    op2.src_slot = slot
    op2.dst_slot = dst


def _draw_corpus_add_row(layout, slot: int, tlp_hash: int, dt_hash: int,
                          data_type: int, timl_obj):
    """绘制语料 "可添加" 行：DT 名 + [+A0] [+A1]（已存在时灰）。"""
    row = layout.row(align=True)
    row.label(text=datatype_name(dt_hash), icon="ADD")
    for sl, txt in ((0, "+A0"), (1, "+A1")):
        exists = _track_exists(timl_obj, sl, tlp_hash, dt_hash)
        sub = row.row(align=True)
        sub.enabled = not exists
        op = sub.operator("efx.timl_add_track", text=txt)
        op.tlp_hash_hex = "%08X" % (tlp_hash & 0xFFFFFFFF)
        op.dt_hash_hex  = "%08X" % (dt_hash  & 0xFFFFFFFF)
        op.data_type = data_type
        op.slot = sl


def _draw_tracks_panel(layout, context):
    """轨道增删面板内容（Dope Sheet / Graph Editor 共用）。
    会话进行中 → 数据源为会话内存模型，增删实时改模型+重建曲线（不锁死）；
    会话外 → 数据源为 entry 字节，增删立即落字节。"""
    body, timl = _read_for_display()
    if body is None:
        layout.label(text=T("timl.select_entry"), icon="INFO")
        return
    if timl is None:
        layout.label(text=T("timl.parse_failed"), icon="ERROR")
        return

    wm = context.window_manager

    # ── T1: 当前轨道列表 ──────────────────────────────────────────────────
    for slot in (0, 1):
        if slot >= len(timl.animations) or timl.animations[slot] is None:
            continue
        anim = timl.animations[slot]
        if not anim.types:
            continue

        slot_box = layout.box()
        hdr = slot_box.row(align=True)
        hdr.label(text=f"{'A0 — Emission' if slot == 0 else 'A1 — Lifetime'}",
                  icon="ANIM" if slot == 0 else "PARTICLES")

        for t in anim.types:
            tlp_h = t.timeline_param_hash & 0xFFFFFFFF
            tlp_box = slot_box.box()
            tlp_box.label(text=timeline_param_name(tlp_h), icon="NODETREE")
            col = tlp_box.column(align=True)
            for tf in t.transforms:
                dt_h = tf.datatype_hash & 0xFFFFFFFF
                _draw_track_row(col, slot, tlp_h, dt_h, timl)

    # ── 语料调色板（下拉选 TLP → 显示该 TLP 的 DT 列表）────────────────
    layout.separator()
    add_box = layout.box()

    # 分类行：只在「开放全部」时生效，故关掉时灰显——避免"选了分类却没反应"的困惑
    cat_row = add_box.row(align=True)
    cat_row.enabled = bool(getattr(wm, "efx_timl_tracks_open_all", False))
    cat_row.prop(wm, "efx_timl_tracks_category", text="")

    # 过滤控制行：[开放全部 toggle] [TLP 下拉]
    sel_row = add_box.row(align=True)
    sel_row.prop(wm, "efx_timl_tracks_open_all", text="", icon="WORLD", toggle=True)
    sel_row.prop(wm, "efx_timl_tracks_tlp_filter", text="")

    # 解析当前选中 TLP
    tlp_hex = getattr(wm, "efx_timl_tracks_tlp_filter", "NONE")
    if tlp_hex == "NONE" or not tlp_hex:
        add_box.label(text=T("timl.no_matching_types"), icon="INFO")
        return

    try:
        tlp_h = int(tlp_hex, 16)
    except ValueError:
        return

    pairs = DT_PALETTE.get(tlp_h, [])
    if not pairs:
        add_box.label(text=T("timl.no_tracks_for_tlp"), icon="INFO")
        return

    col = add_box.column(align=True)
    for dt_h, data_type in pairs:
        _draw_corpus_add_row(col, 0, tlp_h, dt_h, data_type, timl)


class EFX_PT_timl_tracks(Panel):
    """Dope Sheet 侧栏：TIML 轨道增删（轨道列表删除/复制 + 语料调色板）"""

    bl_space_type  = "DOPESHEET_EDITOR"
    bl_region_type = "UI"
    bl_category    = "EFX TIML"
    bl_label       = "TIML Tracks"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, context):
        # ⚠ 与 EFX TIML 面板一样，兜底把异常直接显示在面板里而不是让内容静默消失
        # （2026-07-01 用户报告的 Dope Sheet 侧栏内容消失 bug，排查未有定论）。
        try:
            _draw_tracks_panel(self.layout, context)
        except Exception:
            import traceback
            self.layout.label(text=T("ui.error_console"), icon="ERROR")
            traceback.print_exc()


class EFX_PT_timl_tracks_graph(EFX_PT_timl_tracks):
    """曲线编辑器侧栏：与 Dope Sheet 完全相同的 TIML 轨道增删面板。"""
    bl_space_type = "GRAPH_EDITOR"


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_timl_field_add_menu,
    EFX_OT_timl_add_field_tracks,
    EFX_OT_timl_add_track,
    EFX_OT_timl_delete_track,
    EFX_OT_timl_copy_track,
    EFX_PT_timl_tracks,
    EFX_PT_timl_tracks_graph,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.efx_timl_tracks_open_all = BoolProperty(
        name="Open All TLP",
        description="开放全部：下拉列出所有 DT_PALETTE TLP，而非只列当前 entry 有对应属性类型的",
        default=False,
    )
    bpy.types.WindowManager.efx_timl_tracks_category = bpy.props.EnumProperty(
        name="Category",
        description="限定「开放全部」列出哪一类 TLP；不开放全部时本项不参与过滤",
        items=[
            ("ALL",       "All",       "所有 TLP"),
            ("EFX",       "EFX",       "特效属性块（nEffect::nTimelineParam::）"),
            ("MATERIAL",  "Material",  "材质动画（nDraw::MaterialAnimation::），TLP 即主材质类型"),
            ("ANIMATION", "Animation", "动作 / 碰撞 / 模型部件 / 事件（nTimelineParam::）"),
            ("AUDIO",     "Audio",     "音频事件（nTimelineParam::nWwiseTimeline::）"),
        ],
        default="EFX",
    )
    bpy.types.WindowManager.efx_timl_tracks_tlp_filter = bpy.props.EnumProperty(
        name="TLP",
        description="选择要添加轨道的目标块类型（TLP）",
        items=_tlp_enum_items,
    )


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    for attr in ("efx_timl_tracks_open_all", "efx_timl_tracks_category",
                 "efx_timl_tracks_tlp_filter"):
        try:
            delattr(bpy.types.WindowManager, attr)
        except Exception:
            pass
