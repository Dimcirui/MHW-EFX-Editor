"""
blender_efx/timl_tracks.py  —  T1/T2/T2b：TIML 轨道增删复制

UI 入口
-------
  T1  — Dope Sheet 侧栏「EFX TIML」→「Tracks」子面板：当前 entry 的轨道列表 + 删除/复制按钮
  T2  — panels.py 字段标题行旁的 +A0/+A1 小按钮（仅六类"确认"字段显示）
  T2b — 同上 Dope Sheet 面板下方：语料调色板 + 「开放所有组合」开关

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；包内相对导入；纯胶水层。
"""

import base64

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty
from bpy.types import Operator, Panel

from .i18n import T
from .timl_meta_ui import _active_entry, _entry_timl_bytes, _store_timl
from ..efx_format import timl as _timl
from ..efx_format.timl.names import (
    BLOCK_TO_TLP, FIELD_TO_DT, CORPUS_PAIRS,
    TLP_NAMES, DT_NAMES, DT_TRANSFORM,
    timeline_param_name, datatype_name, channel_label, block_native_axis,
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


# 新增轨道首帧的 seed：从属性当前静态字段值读取，使"加一条轨道"不改变外观。
# 只有标量/向量/颜色几种值槽有意义；其余（字符串数组、枚举、路径等）返回 None
# 交给 DT_NEUTRAL 兜底。
_SEED_SCALAR = {
    "FLOAT":  lambda it: [float(it.float_value)],
    "INT":    lambda it: [float(it.int_value)],
    "BYTE1":  lambda it: [float(it.byte1_value)],
    "SHORT1": lambda it: [float(it.short1_value)],
    "FLOAT2": lambda it: [float(v) for v in it.float2_value],
    # FLOAT3 = XYZ type 3，背板按游戏序 [gx, gy, gz]
    "FLOAT3": lambda it: [float(v) for v in it.float3_value],
    "FLOAT4": lambda it: [float(v) for v in it.float4_value],
    # FLOAT6 = XYZ type 0，背板按游戏序逐轴成对交错 [x_a, x_b, y_a, y_b, z_a, z_b]。
    # 这一对是什么取决于字段：多数是"值/抖动"（translate/rotate/resize），
    # EMITTERSHAPE3D.rangeXYZ 则是"offset/size"。返回全部 6 个，由
    # _field_seed_values 按该字段挂了几条 DT 决定怎么对齐。
    "FLOAT6": lambda it: [float(v) for v in it.float6_value],
    "INT3":   lambda it: [float(v) for v in it.int3_value],
    # 颜色两种值槽：COLOUR 已是 0-255 ubyte；COLOR_RGBA 是 picker 的 0-1 float
    "COLOUR":     lambda it: [float(v) for v in it.colour_value],
    "COLOR_RGBA": lambda it: [float(v) * 255.0 for v in it.color_rgba_value],
}


def _field_seed_values(block_type: str, field_name: str, n_dt: int):
    """读活动 EFX_ATTRIBUTE 上 field_name 字段的当前值，返回长度 n_dt 的 seed 列表
    （每个元素喂给一条 DT 轨道）；拿不到则返回 None（由 DT_NEUTRAL 兜底）。

    向量字段按分量对齐 DT：FIELD_TO_DT 里向量条目就是游戏分量顺序（X,Y,Z），
    如 TRANSFORM3D.translate → pos:X/pos:Y/pos:Z，故 seed[i] 直接给 entries[i]。
    Color 字段只有一条 DT，整个 4 通道序列作为该条的 seed。
    """
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
        # 单条 DT：标量给标量，颜色给整个通道序列
        return [vals if len(vals) > 1 else vals[0]]
    if n_dt == 3 and len(vals) == 6:
        # FLOAT6 挂 3 条 DT：成对交错里只有前一个是"值"，后一个是抖动
        # （translate → pos:X/Y/Z）。取 0/2/4，否则会把 X 的抖动当成 Y 的值。
        return [vals[0], vals[2], vals[4]]
    # 其余按位置直接对齐（含 FLOAT6 挂 6 条 DT 的 rangeXYZ → offset/size 交错）；
    # 分量不够则用最后一个值补齐
    return [vals[i] if i < len(vals) else vals[-1] for i in range(n_dt)]


def _resolve_for_edit():
    """持久化模型：解析"要编辑哪个 Timl 模型"。**先提交进行中的关键帧编辑**（commit
    fcurves→字节），再从字节解析——否则随后 set_entry_timl 重建会用旧字节冲掉正在改的关键帧。
    返回 (body, timl)；无 entry / 解析失败 (None, None)。"""
    body = _active_entry()
    if body is None:
        return None, None
    from . import timl_edit as _te
    _te.commit_fcurves_to_bytes(body)
    timl = _te.read_model(body)
    return (body, timl) if timl is not None else (None, None)


def _commit_edit(body, timl):
    """落实结构性改动：经咽喉点存字节 + 从新字节重建持久 fcurve（含新增/删除的轨道）。"""
    from . import timl_edit as _te
    _te.set_entry_timl(body, timl.serialize())


def _read_for_display():
    """面板展示用：从 timl_bytes 解析（持久化模型下字节即结构权威）。返回 (body, timl)。"""
    body = _active_entry()
    if body is None:
        return None, None
    return body, _timl.parse_timl(_entry_timl_bytes(body))


# 「该字段已经在做动画吗」——字段行上 ♫ 按钮的按下态。逐行去解 TIML 字节太贵
# （Inspector 一次重绘要画几十行），所以按 (entry 名, 字节长度) 缓存一份 (tlp,dt) 集合，
# 并在 set_entry_timl 这个咽喉点显式失效。没有 TIML 的 entry（全语料 94.8%）直接空集返回，
# 连解析都不做。
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
    """当前活动对象解析出的 EFX_ENTRY，**不要求它已经有 TIML**（`_active_entry` 要求）。
    ♫ 按钮据此决定是否可点：还没有 TIML 的 entry 也该能点开，弹窗里给"先建 TIML"。"""
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


def _ptbehavior_channel(attr_obj, item):
    """PTBEHAVIOR 参数行 → (tlp_hash, dt_hash, data_type)；不可动画则 None。

    PTBEHAVIOR 不是普通块：TLP 由它自己的 b_type（DTI 类名字符串）算出，DT 由参数名
    去掉前导 m 后取 jamcrc —— 两条规则都在语料上验证过，故这一整类无需静态映射表
    （详见 efx_format/timl/names.py 的 ptbehavior_* 说明）。

    参数名取 item.hint_name（ori_name 是 'p3' 这样的序号占位）。名字未知（显示成
    0x%08X）→ 算不出 DT，不给按钮。只放行 FLOAT / COLOR_RGBA 两种值槽：语料里的
    behavior 轨道全是 data_type 2/3，整型参数（槽位号、枚举等）做动画没有意义。
    """
    from ..efx_format.timl.names import ptbehavior_tlp_candidates, ptbehavior_param_dt

    # t==0x15 的参数展开成 p{i}_v0..v3 四个子项，共用同一个参数名 —— 若照常给按钮
    # 会出现 4 个指向同一条轨道的入口；且 4 浮点参数怎么映射到 TIML 通道未知，
    # 整类跳过。
    if "_v" in (getattr(item, "ori_name", "") or ""):
        return None

    dt = ptbehavior_param_dt(getattr(item, "hint_name", "") if item else "")
    if dt is None:
        return None
    if item.data_type == "COLOR_RGBA":
        data_type = 3
    elif item.data_type == "FLOAT":
        data_type = 2
    else:
        return None

    b_type = ""
    for it in attr_obj.efx_block.field_items:
        if it.ori_name == "b_type":
            b_type = it.string_value
            break
    cands = ptbehavior_tlp_candidates(b_type)
    if not cands:
        return None

    # Mh* 子类可能把轨道挂在自身 TLP 或基类 TLP 下（从不并存）——优先复用该 TIML 里
    # 已经存在的那个，避免把同一属性的轨道拆到两个 TLP。
    tlp = cands[0]
    if len(cands) > 1:
        body = _active_entry()
        if body is not None:
            try:
                t = _timl.parse_timl(_entry_timl_bytes(body))
                present = {ty.timeline_param_hash & 0xFFFFFFFF
                           for a in t.animations if a is not None for ty in a.types}
                for c in cands:
                    if c in present:
                        tlp = c
                        break
            except Exception:
                pass
    return tlp, dt, data_type


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
        # 属性对象取 item.id_data 而非 active_object——Entry Inspector 里画的是
        # 非活动的属性对象，用 active_object 会拿到 entry 本身而白白跳过按钮。
        obj = item.id_data
        if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
            return
        ch = _ptbehavior_channel(obj, item)
        if ch is None:
            return
        tlp_hex, dt_hex, data_type = "%08X" % ch[0], "%08X" % ch[1], ch[2]
        animated = bool(present) and (ch[0] & 0xFFFFFFFF, ch[1] & 0xFFFFFFFF) in present
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
    # 还没有 TIML 的 entry 也放行——弹窗里第一步就是"先建 TIML 段"。
    # （全语料只有 5.2% 的 entry 自带 TIML，卡在这里等于按钮基本永远是灰的。）
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
    """点击后弹出小菜单，选择将该字段的 TIML 轨道加到 A0（发射轴）还是 A1（寿命轴）"""

    bl_idname = "efx.timl_field_add_menu"
    bl_label  = "+TIML"
    bl_options = {"INTERNAL"}

    block_type: StringProperty(default="")
    field_name: StringProperty(default="")
    # PTBEHAVIOR 专用：TLP/DT 在绘制时已按 b_type + 参数名算好，直接透传给添加算子
    # （该块没有静态 FIELD_TO_DT 条目）。普通块留空。
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
        # 这个 entry 还没有 TIML 段：先给创建入口，不在这里替用户默默建
        # （空白 TIML 的头部常量有过写错的历史，建段保持为显式动作）。
        if _active_entry() is None:
            layout.label(text=T("timl.no_segment_yet"), icon="INFO")
            layout.operator("efx.create_entry_timl",
                            text=T("timl.create_blank_btn"), icon="ADD")
            return
        native = block_native_axis(self.block_type)   # 0=A0 母轴 / 1=A1 母轴 / None=两轴都行

        specs = {0: ("+A0  (Emission)", "ANIM"), 1: ("+A1  (Lifetime)", "PARTICLES")}
        # 母轴排第一并标推荐；非母轴排后面并加"该属性在此轴通常不生效"提示。两轴都行→原序。
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
            if _is_zh():
                layout.label(text="该属性的动画在游戏里通常只在 %s 轴生效；" % axis_name, icon="INFO")
                layout.label(text="加到另一条轴很可能静默无效。", icon="BLANK1")
            else:
                layout.label(text="This attribute usually only works on %s in-game;" % axis_name, icon="INFO")
                layout.label(text="the other axis is likely a silent no-op.", icon="BLANK1")

    def execute(self, context):
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T2 — 按字段整组添加（translate→3条 pos:X/Y/Z）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_add_field_tracks(Operator):
    """为确认字段在指定轴添加所有 DT 通道（向量一次添3条，Color 添1条）"""

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
        return _active_entry() is not None

    def execute(self, context):
        if self.tlp_hash_hex and self.dt_hash_hex:
            # PTBEHAVIOR 路径：单条通道，TLP/DT 已由 b_type + 参数名算出
            try:
                tlp_hash = int(self.tlp_hash_hex, 16)
                entries = [(int(self.dt_hash_hex, 16), int(self.dt_data_type))]
            except ValueError:
                self.report({"ERROR"}, "Invalid hash hex value")
                return {"CANCELLED"}
        else:
            key = (self.block_type.upper(), self.field_name)
            entries = FIELD_TO_DT.get(key)
            if not entries:
                self.report({"ERROR"}, f"No confirmed DT mapping for {key}")
                return {"CANCELLED"}
            tlp_hash = BLOCK_TO_TLP.get(self.block_type.upper())
            if tlp_hash is None:
                self.report({"ERROR"}, f"No TLP mapping for attribute type '{self.block_type}'")
                return {"CANCELLED"}
        body, timl = _resolve_for_edit()   # 已 commit 进行中关键帧编辑
        if timl is None:
            self.report({"ERROR"}, "No valid TIML found on active entry")
            return {"CANCELLED"}

        # 新轨道首帧用该属性当前的静态字段值，使"加一条轨道"不改变特效当下的外观
        # （绝对量级字段如 SizeY/Radius 因此也能拿到正确量级）。读不到则由
        # DT_NEUTRAL 兜底（乘算类 → 1.0，其余 → 0.0）。
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
        self.report({"INFO"}, f"Added {added} track(s) to {slot_lbl} for {self.block_type}.{self.field_name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator: T2b — 按 TLP+DT hash 添加单条（调色板按钮用）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_timl_add_track(Operator):
    """在指定轴添加单条 TIML 轨道（TLP+DT hash 由调色板按钮提供）"""

    bl_idname = "efx.timl_add_track"
    bl_label  = "Add TIML Track"
    bl_options = {"REGISTER", "UNDO"}

    tlp_hash_hex: StringProperty(default="")  # e.g. "4D111433"
    dt_hash_hex:  StringProperty(default="")  # e.g. "8E8AFE06"
    data_type:    IntProperty(default=2)       # 2=Float, 3=Color
    slot:         IntProperty(default=0)       # 0=A0, 1=A1

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

        added = _timl.add_transform(timl, self.slot, tlp, dt, self.data_type)
        if not added:
            self.report({"WARNING"}, "Track already exists")
            return {"CANCELLED"}

        _commit_edit(body, timl)
        lbl = channel_label(tlp, dt)
        slot_lbl = _SLOT_LABEL.get(self.slot, str(self.slot))
        self.report({"INFO"}, f"Added {lbl} → {slot_lbl}")
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
# Panel: EFX TIML Tracks（Dope Sheet 侧栏，EFX TIML 分类）
# T1 轨道列表 + T2b 语料调色板
# ─────────────────────────────────────────────────────────────────────────────

def _get_entry_attribute_tlps(entry_obj) -> set:
    """返回 entry 下所有 EFX_ATTRIBUTE 子对象对应的 TLP hash 集合（经 BLOCK_TO_TLP 映射）。
    同时包含该 entry TIML 中已存在的 TLP hash（兼容手动添加或导入的已有轨道）。"""
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


# 全局缓存：防止 Blender EnumProperty 动态回调因 GC 丢引用导致下拉乱码
_tlp_enum_cache = [("NONE", "— 无匹配属性 —", "")]


def _tlp_enum_items(self, context):
    """TLP 下拉 EnumProperty 回调。
    open_all=False：只列当前 entry 有对应 EFX_ATTRIBUTE 的 TLP + TIML 已有的 TLP。
    open_all=True ：列出 CORPUS_PAIRS 中所有已知 TLP。"""
    global _tlp_enum_cache
    if context is None:
        return _tlp_enum_cache

    wm = context.window_manager
    open_all = getattr(wm, "efx_timl_tracks_open_all", False)
    body = _active_entry()

    if open_all or body is None:
        # 显示 CORPUS_PAIRS 全部 TLP，按名称字母序
        items = sorted(
            [("%08X" % h, timeline_param_name(h), "0x%08X" % h)
             for h in CORPUS_PAIRS],
            key=lambda x: x[1],
        )
    else:
        # 过滤：只列 entry 属性类型对应 TLP（+ TIML 已有 TLP）
        allowed = _get_entry_attribute_tlps(body)
        # 也补入 TIML 中已有的 TLP（避免手动添加的 TLP 从下拉消失）
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
        # 只保留 CORPUS_PAIRS 中有数据的
        items = sorted(
            [("%08X" % h, timeline_param_name(h), "0x%08X" % h)
             for h in allowed if h in CORPUS_PAIRS],
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
    # 删除按钮
    op = row.operator("efx.timl_delete_track", text="", icon="X")
    op.tlp_hash_hex = "%08X" % (tlp_hash & 0xFFFFFFFF)
    op.dt_hash_hex  = "%08X" % (dt_hash  & 0xFFFFFFFF)
    op.slot = slot
    # 跨轴复制按钮（方向箭头）
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
        layout.label(text="Select an EFX_ENTRY with TIML", icon="INFO")
        return
    if timl is None:
        layout.label(text="Failed to parse TIML", icon="ERROR")
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

    # ── T2b: 语料调色板（下拉选 TLP → 显示该 TLP 的 DT 列表）────────────────
    layout.separator()
    add_box = layout.box()

    # 过滤控制行：[开放全部 toggle] [TLP 下拉]
    sel_row = add_box.row(align=True)
    sel_row.prop(wm, "efx_timl_tracks_open_all", text="", icon="WORLD", toggle=True)
    sel_row.prop(wm, "efx_timl_tracks_tlp_filter", text="")

    # 解析当前选中 TLP
    tlp_hex = getattr(wm, "efx_timl_tracks_tlp_filter", "NONE")
    if tlp_hex == "NONE" or not tlp_hex:
        add_box.label(text="No matching attribute types in this EFX", icon="INFO")
        return

    try:
        tlp_h = int(tlp_hex, 16)
    except ValueError:
        return

    pairs = CORPUS_PAIRS.get(tlp_h, [])
    if not pairs:
        add_box.label(text="No corpus data for this TLP", icon="INFO")
        return

    col = add_box.column(align=True)
    for dt_h, data_type in pairs:
        _draw_corpus_add_row(col, 0, tlp_h, dt_h, data_type, timl)


class EFX_PT_timl_tracks(Panel):
    """Dope Sheet 侧栏：TIML 轨道增删（T1 删除/复制 + T2b 调色板）"""

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
            self.layout.label(text="TIML Tracks panel error (see console):", icon="ERROR")
            for line in traceback.format_exc().splitlines()[-4:]:
                self.layout.label(text=line[:80])
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
        description="开放全部：下拉列出所有 CORPUS_PAIRS TLP，而非只列当前 entry 有对应属性类型的",
        default=False,
    )
    bpy.types.WindowManager.efx_timl_tracks_tlp_filter = bpy.props.EnumProperty(
        name="TLP",
        description="选择要添加轨道的目标块类型（TLP）",
        items=_tlp_enum_items,
    )


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    for attr in ("efx_timl_tracks_open_all", "efx_timl_tracks_tlp_filter"):
        try:
            delattr(bpy.types.WindowManager, attr)
        except Exception:
            pass
