"""多 Entry 批量属性编辑：把同类型属性按页并排对比，并把参考属性的值写入本页其余属性。

维护约束：
- 字段控件全部交给 panels._draw_plain_field_list 绘制，本模块只在行左侧加勾选 / 不一致标记，
  不复制官方控件分支。
- 只写字段值，不改属性结构；写入走 presets._json_value_to_item。
- 路径字符串只允许等长写入：块尺寸随路径长度变化，批量改长度会让后续块整体偏移。
- 页表 _STATE 是选择的派生缓存，读取路径不得写场景数据；切换文件时由 session_core 复位。
"""

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import fields as _fields
from . import field_labels as _field_labels
from . import field_visibility as _field_visibility
from . import panels as _panels
from . import presets as _presets
from . import session_core
from .i18n import T
from .layout_model import build_units, resolve_axis_groups
from ..efx_format.hashes import HASH_TO_NAME, pretty_type_name

DASH = "—"

# 路径字符串：只允许等长写入。
_LEN_SENSITIVE = ("STRING",)

# 由专用控件接管、通用字段上的修改会被导出覆写的字段。
_UPSTREAM_MANAGED = {
    ("PTLIFE", "relationIndex"),
    ("PTCOLLISION", "ieIndex"),
    ("EXTERNREFERENCE", "referenceIndex"),
}


def _is_sentinel(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _is_attribute(obj) -> bool:
    return obj is not None and obj.get("~TYPE") == "EFX_ATTRIBUTE" and hasattr(obj, "efx_block")


def _is_material_block(obj) -> bool:
    """结构化材质槽块整块由材质编辑器管理，批量写会连带重编码。"""
    try:
        return any(it.ori_name == "__material__" for it in obj.efx_block.field_items)
    except Exception:
        return False


def _str_same_len(a, b) -> bool:
    try:
        return len(str(a).encode("utf-8", "surrogateescape")) == len(
            str(b).encode("utf-8", "surrogateescape"))
    except Exception:
        return False


def _type_name(hash_str) -> str:
    try:
        h = int(hash_str)
    except (TypeError, ValueError):
        return str(hash_str or "").upper()
    return HASH_TO_NAME.get(h, f"0x{h:08X}").upper()


def _type_hash(obj) -> str:
    try:
        return str(obj.efx_block.type_hash_str or obj.get("type_hash", "") or "")
    except Exception:
        return ""


def _efx_index(obj) -> int:
    try:
        return int(obj.get("efx_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _vkey(v):
    """值的可哈希规范键；只归一 -0.0，不做容差。"""
    if isinstance(v, (list, tuple)):
        return tuple(_vkey(x) for x in v)
    if isinstance(v, float):
        return round(v, 9) + 0.0
    return v


def _current_value(item):
    """字段当前值的 JSON 表示；无法表示的字段返回 None。"""
    try:
        return _presets._item_to_json_value(item)
    except Exception:
        return None


def _field_map(obj):
    return {it.ori_name: it for it in obj.efx_block.field_items}


# ─────────────────────────────────────────────────────────────────────────────
# 选择解析：Entry → 属性 → 分页
# ─────────────────────────────────────────────────────────────────────────────

_STATE = {
    "sig": None,
    "err": "",
    "n_sel": 0,
    "n_block": 0,
    "pages": [],      # [{key, title, type_name, ref, targets, rows, use, skip, order, err}]
    "page": 0,
    "ref_of": {},     # key -> 上一轮的参考属性名
    "ref_pin": {},    # key -> 用户显式指定的参考属性名
}


def reset_state():
    _STATE.update(sig=None, err="", n_sel=0, n_block=0, pages=[], page=0,
                  ref_of={}, ref_pin={})


def _selected(context):
    return [o for o in (context.selected_objects or ())
            if o is not None and o.get("~TYPE") in ("EFX_ENTRY", "EFX_ATTRIBUTE")]


def _children_blocks(entry):
    """Entry 下的属性，按 efx_index 排序（即文件里的属性顺序）。"""
    blocks = [o for o in entry.children if _is_attribute(o)]
    blocks.sort(key=_efx_index)
    return blocks


def _build_columns(objs, active):
    """选中对象展开成列：每个 Entry 一列；直接选中的属性合成一列。

    活动对象所在列排最前，使每页的参考属性落在活动对象一侧。
    每列元素为 (属性, 同类型出现序号)；页键 = (类型哈希, 出现序号)。
    """
    direct = [o for o in objs if _is_attribute(o)]
    entries = [o for o in objs if not _is_attribute(o)]
    if active is not None:
        direct.sort(key=lambda o: 0 if o is active else 1)
        entries.sort(key=lambda o: 0 if o is active else 1)

    columns = []
    if direct:
        direct.sort(key=lambda o: (0 if o is active else 1,
                                   o.parent.name if o.parent else "",
                                   _efx_index(o), o.name))
        columns.append([(o, 0) for o in direct])
    for entry in entries:
        seen = {}
        col = []
        for b in _children_blocks(entry):
            h = _type_hash(b)
            occ = seen.get(h, 0)
            seen[h] = occ + 1
            col.append((b, occ))
        if col:
            columns.append(col)
    return columns


def _rows_for(targets):
    """以 targets[0]（参考属性）为基准建立字段对比表；只收录所有目标都有的可表示字段。"""
    ref = targets[0]
    if not ref.efx_block.is_editable:
        return [], "read_only"

    type_name = _type_name(_type_hash(ref))
    items = [it for it in ref.efx_block.field_items
             if it.ori_name and not _is_sentinel(it.ori_name)]
    items = list(_panels.reorder_items_for_display(type_name, items))

    maps = [_field_map(t) for t in targets]
    rows = []
    for it in items:
        name = it.ori_name
        if it.read_only:
            continue
        vals = []
        for m in maps:
            ti = m.get(name)
            v = _current_value(ti) if ti is not None else None
            if v is None:
                break
            vals.append(v)
        else:
            snap = vals[0]
            rows.append({
                "field": name,
                "dtype": it.data_type,
                "mixed": len({_vkey(v) for v in vals}) > 1,
                "snap": snap,      # 扫描时参考属性的值，用于判定「被改过」和还原
                "_cur": snap,      # 上次比较过的参考值，避免每次重绘全量比较
            })
    return rows, ""


def _rescan(context, force=False, rebase=False):
    """按当前选择重建页表；签名未变直接复用。

    rebase=True 表示重新取基线，仅用于「应用」「还原」落地之后。
    平时重扫必须保住基线与待应用列表，否则拖选扩选会把已改的值当成没改过。
    """
    st = _STATE
    objs = _selected(context)
    active = context.active_object
    sig = (active.name if active is not None else "") + "\n" + "|".join(sorted(o.name for o in objs))
    if not force and sig == st["sig"]:
        return st

    prev_pages = st["pages"]
    prev_idx = st["page"]
    prev_key = prev_pages[prev_idx]["key"] if 0 <= prev_idx < len(prev_pages) else None
    prev = {p["key"]: (set(p["use"]), set(p["skip"]), p["ref"],
                       {r["field"]: r["snap"] for r in p["rows"]})
            for p in prev_pages}

    st.update(sig=sig, pages=[], page=0, err="", n_sel=len(objs), n_block=0)
    if not objs:
        st["err"] = "no_selection"
        return st

    by_key = {}
    order = []
    for col in _build_columns(objs, active):
        for blk, occ in col:
            key = (_type_hash(blk), occ)
            if key not in by_key:
                by_key[key] = []
                order.append(key)
            by_key[key].append(blk)
            st["n_block"] += 1
    if not order:
        st["err"] = "no_blocks"
        return st

    pages = []
    new_ref_of = {}
    for key in order:
        targets = by_key[key]
        # 参考属性一旦定下就黏住，避免大纲里扩选时跟着「最后点中的」漂移。
        for want in (st["ref_pin"].get(key), st["ref_of"].get(key)):
            if want and any(o.name == want for o in targets):
                targets.sort(key=lambda o: 0 if o.name == want else 1)
                break
        ref = targets[0]
        type_name = _type_name(key[0])
        rows, err = _rows_for(targets)
        page = {
            "key": key,
            "targets": [o.name for o in targets],
            "ref": ref.name,
            "type_name": type_name,
            "title": f"{_efx_index(ref):02d} {pretty_type_name(type_name)}",
            "rows": rows,
            "order": [r["field"] for r in rows],
            "err": err,
            "use": set(),
            "skip": set(),
        }
        old = None if rebase else prev.get(key)
        if old is not None and old[2] == ref.name:
            names = set(page["order"])
            page["use"] = {n for n in old[0] if n in names}
            page["skip"] = {n for n in old[1] if n in names}
            # 基线随待应用项一起沿用：否则重扫后 snap 取到的就是已改过的值。
            for r in rows:
                if (r["field"] in page["use"] or r["field"] in page["skip"]) \
                        and old[3].get(r["field"]) is not None:
                    r["snap"] = r["_cur"] = old[3][r["field"]]
        new_ref_of[key] = ref.name
        pages.append(page)

    st["pages"] = pages
    st["ref_of"] = new_ref_of
    if prev_key is not None:
        for i, p in enumerate(pages):
            if p["key"] == prev_key:
                st["page"] = i
                break
        else:
            st["page"] = min(max(0, prev_idx), len(pages) - 1)
    return st


def _page(st):
    pages = st["pages"]
    if not pages:
        return None
    st["page"] = min(max(0, st["page"]), len(pages) - 1)
    return pages[st["page"]]


def _refresh_page(page, ref_obj):
    """重绘前刷新当前页：参考值变过的字段更新不一致标记，并同步待应用列表。

    只有参考值变过的字段才读取其它属性。返回参考属性的 {字段名: item}。
    """
    ref_map = _field_map(ref_obj)
    live = None
    for r in page["rows"]:
        item = ref_map.get(r["field"])
        if item is None or item.read_only:
            continue
        cur = _current_value(item)
        if cur is None:
            continue
        if r["_cur"] != cur:
            r["_cur"] = cur
            if live is None:
                live = [_field_map(o) for o in map(bpy.data.objects.get, page["targets"])
                        if o is not None and _is_attribute(o)]
            r["mixed"] = any(m.get(r["field"]) is None or _current_value(m[r["field"]]) != cur
                             for m in live)
        if cur == r["snap"]:
            page["use"].discard(r["field"])
            page["skip"].discard(r["field"])
        elif r["field"] in page["skip"]:
            page["use"].discard(r["field"])
        else:
            page["use"].add(r["field"])
    return ref_map


def _hidden_test(context, type_name, ref_map):
    """返回 name -> 是否隐藏；规则与属性面板一致，并跟随「显示全部字段」。"""
    show_all = bool(getattr(context.scene, "efx_show_all_fields", False))
    has_vis = type_name in _field_visibility.FIELD_VISIBILITY

    def _mode_getter(name):
        it = ref_map.get(name)
        return _fields._enum_backing_read(it) if it is not None else None

    def hidden(name):
        if _is_sentinel(name):
            return True
        if show_all:
            return False
        if has_vis and _field_visibility.field_hidden(type_name, name, _mode_getter):
            return True
        return _field_labels.is_reserved_fill(type_name, name)

    return hidden


# ─────────────────────────────────────────────────────────────────────────────
# 设置
# ─────────────────────────────────────────────────────────────────────────────

class EFXBatchSettings(PropertyGroup):
    show_checkboxes: BoolProperty(
        name="Checkboxes",
        description="Show a checkbox on each field to pick which fields to apply. "
                    "Off: only fields changed on the reference are applied",
        default=False,
    )
    filter: StringProperty(
        name="Filter",
        description="Only list fields whose name contains this text",
        default="",
    )
    report: StringProperty(name="Report", default="")


def _settings(context):
    return getattr(context.scene, "efx_batch", None)


def _set_report(context, text):
    s = _settings(context)
    if s is not None:
        s.report = text


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_batch_page(Operator):
    bl_idname = "efx.batch_page"
    bl_label = "Batch Edit Page"
    bl_description = "Go to another page"
    bl_options = {"REGISTER", "INTERNAL"}

    mode: StringProperty(default="NEXT")

    def execute(self, context):
        st = _rescan(context)
        pages = st["pages"]
        if not pages:
            return {"CANCELLED"}
        cur = st["page"]
        if self.mode == "PREV":
            st["page"] = max(0, cur - 1)
        elif self.mode == "NEXT":
            st["page"] = min(len(pages) - 1, cur + 1)
        else:
            step = 1 if self.mode == "DIFF_NEXT" else -1
            i = cur
            for _ in range(len(pages)):
                i = (i + step) % len(pages)
                if any(r["mixed"] for r in pages[i]["rows"]):
                    st["page"] = i
                    break
        return {"FINISHED"}


class EFX_OT_batch_ref(Operator):
    bl_idname = "efx.batch_ref"
    bl_label = "Switch Reference"
    bl_description = "Use another attribute on this page as the reference for values"
    bl_options = {"REGISTER", "INTERNAL"}

    mode: StringProperty(default="NEXT")

    def execute(self, context):
        page = _page(_rescan(context))
        if page is None:
            return {"CANCELLED"}
        names = page["targets"]
        if len(names) < 2:
            return {"CANCELLED"}
        i = names.index(page["ref"]) if page["ref"] in names else 0
        step = 1 if self.mode == "NEXT" else -1
        key = page["key"]
        _STATE["ref_pin"][key] = names[(i + step) % len(names)]
        _rescan(context, force=True)
        for j, p in enumerate(_STATE["pages"]):
            if p["key"] == key:
                _STATE["page"] = j
                break
        return {"FINISHED"}


class EFX_OT_batch_toggle(Operator):
    bl_idname = "efx.batch_toggle"
    bl_label = "Toggle Field"
    bl_description = "Include or exclude this field when applying"
    bl_options = {"REGISTER", "INTERNAL"}

    field: StringProperty()

    def execute(self, context):
        page = _page(_rescan(context))
        names = [n for n in self.field.split("|") if n]
        if page is None or not names:
            return {"CANCELLED"}
        turn_off = all(n in page["use"] for n in names)
        for n in names:
            if turn_off:
                page["use"].discard(n)
                page["skip"].add(n)      # 黑名单：重绘时不再自动勾回
            else:
                page["use"].add(n)
                page["skip"].discard(n)
        return {"FINISHED"}


class EFX_OT_batch_check(Operator):
    bl_idname = "efx.batch_check"
    bl_label = "Batch Check"
    bl_description = "Check all fields, uncheck all, or return to automatic selection"
    bl_options = {"REGISTER", "INTERNAL"}

    mode: StringProperty(default="ALL")

    def execute(self, context):
        page = _page(_rescan(context))
        if page is None:
            return {"CANCELLED"}
        names = set(page["order"])
        page["use"] = set(names) if self.mode == "ALL" else set()
        page["skip"] = set(names) if self.mode == "NONE" else set()
        return {"FINISHED"}


class EFX_OT_batch_restore(Operator):
    bl_idname = "efx.batch_restore"
    bl_label = "Revert Reference"
    bl_description = "Restore the reference attribute's fields on this page to the values from when the page was scanned"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        page = _page(_STATE)
        ref = bpy.data.objects.get(page["ref"]) if page is not None else None
        if ref is None or not _is_attribute(ref):
            return False
        ref_map = _field_map(ref)
        for r in page["rows"]:
            it = ref_map.get(r["field"])
            if it is not None and not it.read_only and _current_value(it) != r["snap"]:
                return True
        return False

    def execute(self, context):
        page = _page(_rescan(context))
        ref = bpy.data.objects.get(page["ref"]) if page is not None else None
        if ref is None or not _is_attribute(ref):
            return {"CANCELLED"}
        ref_map = _field_map(ref)
        changed = 0
        for r in page["rows"]:
            item = ref_map.get(r["field"])
            if item is None or item.read_only or _current_value(item) == r["snap"]:
                continue
            if _presets._json_value_to_item(item, r["dtype"], r["snap"]):
                changed += 1
        page["use"] = set()
        page["skip"] = set()
        _rescan(context, force=True, rebase=True)
        text = T("batch.reverted").format(n=changed)
        _set_report(context, text)
        self.report({"INFO"}, text)
        return {"FINISHED"}


class EFX_OT_batch_apply(Operator):
    bl_idname = "efx.batch_apply"
    bl_label = "Apply to Page"
    bl_description = "Write the checked fields' values from the reference attribute to every attribute on this page"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = _rescan(context)
        page = _page(st)
        if page is None:
            self.report({"WARNING"}, T("batch.no_page"))
            return {"CANCELLED"}
        wanted = [r for r in page["rows"] if r["field"] in page["use"]]
        if not wanted:
            self.report({"WARNING"}, T("batch.nothing_checked"))
            return {"CANCELLED"}

        ref = bpy.data.objects.get(page["ref"])
        if ref is None or not _is_attribute(ref):
            self.report({"ERROR"}, T("batch.ref_invalid"))
            return {"CANCELLED"}
        if _is_material_block(ref):
            text = T("batch.material_refused").format(title=page["title"])
            _set_report(context, text)
            self.report({"WARNING"}, text)
            return {"CANCELLED"}

        targets = []
        for name in page["targets"]:
            o = bpy.data.objects.get(name)
            if o is not None and _is_attribute(o) and o.efx_block.is_editable:
                targets.append(o)
        if len(targets) < 2:
            self.report({"WARNING"}, T("batch.need_two"))
            return {"CANCELLED"}

        ref_map = _field_map(ref)
        maps = {o.name: _field_map(o) for o in targets}

        # 提交前自检：参考属性上的路径若被改成不同长度，先退回基线。
        reverted = 0
        for r in page["rows"]:
            if r["dtype"] not in _LEN_SENSITIVE:
                continue
            it = ref_map.get(r["field"])
            cur = _current_value(it) if it is not None and not it.read_only else None
            if cur is not None and not _str_same_len(cur, r["snap"]):
                if _presets._json_value_to_item(it, r["dtype"], r["snap"]):
                    reverted += 1

        touched_blocks = set()
        touched_fields = 0
        skipped = 0
        for r in wanted:
            name, dtype = r["field"], r["dtype"]
            src = ref_map.get(name)
            val = _current_value(src) if src is not None else None
            if val is None or (page["type_name"], name) in _UPSTREAM_MANAGED:
                skipped += 1
                continue
            if dtype in _LEN_SENSITIVE and not _str_same_len(val, r["snap"]):
                skipped += 1
                continue

            wrote = False
            for o in targets:
                if o is ref:
                    continue
                ti = maps[o.name].get(name)
                if ti is None or ti.read_only or ti.data_type != dtype:
                    skipped += 1
                    continue
                cur = _current_value(ti)
                if cur == val:
                    continue         # 值已相同不写，保持未编辑状态
                if dtype in _LEN_SENSITIVE and not _str_same_len(val, cur):
                    skipped += 1     # 长度以各属性自己的当前路径为准
                    continue
                if _presets._json_value_to_item(ti, dtype, val):
                    wrote = True
                    touched_blocks.add(o.name)
            touched_fields += wrote

        text = T("batch.applied").format(title=page["title"], blocks=len(touched_blocks),
                                         fields=touched_fields)
        if skipped:
            text += T("batch.skipped").format(n=skipped)
        if reverted:
            text += T("batch.path_reverted").format(n=reverted)

        keep = st["page"]
        _rescan(context, force=True, rebase=True)
        st["page"] = keep
        _set_report(context, text)
        self.report({"INFO"} if touched_blocks else {"WARNING"}, text)
        return {"FINISHED"}


class EFX_OT_batch_rescan(Operator):
    bl_idname = "efx.batch_rescan"
    bl_label = "Rescan"
    bl_description = "Rebuild the pages from the current selection"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        _rescan(context, force=True, rebase=True)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板
# ─────────────────────────────────────────────────────────────────────────────

def _draw_locked_row(col, item, type_name, note):
    """只读字段行：字段名 + 锁标说明，与单字段行同一 45% 分栏。"""
    row = col.row(align=True)
    row.scale_y = 1.1
    row.use_property_split = False
    split = row.split(factor=0.45)
    split.label(text=_panels._friendly_name(item.ori_name, type_name))
    split.label(text=note, icon="LOCKED")
    _panels._draw_field_row_buttons(row, type_name, item.ori_name, item=item, timl=False)


def _units(type_name, items):
    """把字段切成绘制单元：轴向组合整组一个单元，value+jitter 配对一个单元，其余单字段。"""
    by_name = {it.ori_name: it for it in items}
    axis_at, consumed = resolve_axis_groups(type_name, by_name)
    out = []
    for unit in build_units(items):
        lead = unit[0].ori_name
        if lead in axis_at:
            names = []
            for _label, base in axis_at[lead][1]:
                names.append(base)
                if base + "Jitter" in by_name:
                    names.append(base + "Jitter")
            out.append([by_name[n] for n in names])
        elif lead not in consumed:
            out.append(unit)
    return out


def _draw_unit(col, unit, type_name, mixed, use, boxes, locked):
    names = [it.ori_name for it in unit]
    row = col.row(align=True)
    gutter = row.row(align=True)
    gutter.ui_units_x = 2.0 if boxes else 1.0
    if boxes:
        checked = all(n in use for n in names)
        op = gutter.operator("efx.batch_toggle", text="", emboss=False,
                             icon="CHECKBOX_HLT" if checked else "CHECKBOX_DEHLT")
        op.field = "|".join(names)
    gutter.label(text=DASH if any(n in mixed for n in names) else "")
    body = row.column(align=True)
    if names[0] in locked:
        _draw_locked_row(body, unit[0], type_name, locked[names[0]])
    else:
        _panels._draw_plain_field_list(body, unit, type_name)


def _draw_content(layout, context):
    st = _rescan(context)
    settings = _settings(context)
    if settings is None:
        return

    if st["err"]:
        box = layout.box().column(align=True)
        if st["err"] == "no_selection":
            box.label(text=T("batch.select_hint"), icon="INFO")
            box.label(text=T("batch.select_hint2"))
        else:
            box.label(text=T("batch.no_blocks"), icon="INFO")
        box.operator("efx.batch_rescan", text=T("batch.rescan"), icon="FILE_REFRESH")
        return

    pages = st["pages"]
    page = _page(st)
    ref_obj = bpy.data.objects.get(page["ref"])
    if ref_obj is None or not _is_attribute(ref_obj):
        layout.label(text=T("batch.ref_invalid"), icon="ERROR")
        return
    if page["err"]:
        box = layout.box().column(align=True)
        box.label(text=T("batch.page_read_only").format(title=page["title"]), icon="ERROR")
        box.operator("efx.batch_page", text="", icon="TRIA_RIGHT").mode = "NEXT"
        return

    ref_map = _refresh_page(page, ref_obj)
    n_mixed = sum(1 for r in page["rows"] if r["mixed"])
    n_same = len(page["rows"]) - n_mixed
    n_tgt = len(page["targets"])

    # 头部行数保持恒定，编辑时面板高度不跳动。
    head = layout.box().column(align=True)
    head.label(text=T("batch.summary").format(sel=st["n_sel"], blocks=st["n_block"],
                                              pages=len(pages)),
               icon="OBJECT_DATAMODE")
    nav_row = head.row(align=True)
    nav = nav_row.row(align=True)
    nav.operator("efx.batch_page", text="", icon="TRIA_LEFT").mode = "PREV"
    nav.operator("efx.batch_page", text="", icon="TRIA_RIGHT").mode = "NEXT"
    nav_row.label(text=f"{st['page'] + 1} / {len(pages)}")
    nav = nav_row.row(align=True)
    nav.operator("efx.batch_page", text="", icon="FRAME_PREV").mode = "DIFF_PREV"
    nav.operator("efx.batch_page", text="", icon="FRAME_NEXT").mode = "DIFF_NEXT"
    nav_row.label(text=page["title"], icon="NODETREE")

    counts = T("batch.counts").format(blocks=n_tgt, same=n_same, mixed=n_mixed,
                                      pending=len(page["use"]))
    if n_tgt < 2:
        counts += T("batch.single_block")
    head.label(text=counts, icon="INFO")

    ref_row = head.row(align=True)
    if n_tgt > 1:
        ref_row.operator("efx.batch_ref", text="", icon="TRIA_LEFT").mode = "PREV"
        ref_row.operator("efx.batch_ref", text="", icon="TRIA_RIGHT").mode = "NEXT"
    pos = page["targets"].index(page["ref"]) + 1 if page["ref"] in page["targets"] else 1
    ref_row.label(text=T("batch.reference").format(name=page["ref"], i=pos, n=n_tgt))
    head.label(text=T("batch.dash_legend").format(dash=DASH))

    opt = layout.row(align=True)
    opt.prop(settings, "show_checkboxes", text=T("batch.checkboxes"), toggle=True)
    layout.prop(settings, "filter", text="", icon="VIEWZOOM")

    type_name = page["type_name"]
    hidden = _hidden_test(context, type_name, ref_map)
    rows = {r["field"]: r for r in page["rows"]}
    flt = (settings.filter or "").strip().lower()
    mat_block = _is_material_block(ref_obj)

    items = []
    mixed = set()
    locked = {}
    for name in page["order"]:
        item = ref_map.get(name)
        if item is None or item.read_only or hidden(name):
            continue
        if flt and flt not in name.lower():
            continue
        if mat_block:
            locked[name] = T("batch.locked_material")
        elif (type_name, name) in _UPSTREAM_MANAGED:
            locked[name] = T("batch.locked_managed")
        elif item.data_type in _LEN_SENSITIVE:
            locked[name] = T("batch.locked_path")
        items.append(item)
        if rows[name]["mixed"]:
            mixed.add(name)

    col = layout.column(align=True)
    col.use_property_split = False
    for unit in _units(type_name, items):
        _draw_unit(col, unit, type_name, mixed, page["use"],
                   bool(settings.show_checkboxes), locked)

    if locked:
        tip = layout.box().column(align=True)
        tip.label(text=T("batch.locked_count").format(n=len(locked)), icon="LOCKED")
        tip.label(text=T("batch.locked_tip"))

    if settings.show_checkboxes:
        row = layout.row(align=True)
        row.operator("efx.batch_check", text=T("batch.check_all")).mode = "ALL"
        row.operator("efx.batch_check", text=T("batch.check_none")).mode = "NONE"
        row.operator("efx.batch_check", text=T("batch.check_auto")).mode = "RESET"

    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator("efx.batch_apply",
                 text=T("batch.apply").format(n=len(page["use"])), icon="CHECKMARK")
    row.operator("efx.batch_restore", text=T("batch.revert"), icon="LOOP_BACK")

    if settings.report:
        layout.box().label(text=settings.report, icon="TEXT")


class EFX_PT_batch_edit(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Batch Edit"
    bl_order = -2

    @classmethod
    def poll(cls, context):
        from . import root_collection as _rc
        return bool(_selected(context)) and not _rc.context_in_color_editor(context)

    def draw(self, context):
        _draw_content(self.layout, context)


_CLASSES = (
    EFXBatchSettings,
    EFX_OT_batch_page,
    EFX_OT_batch_ref,
    EFX_OT_batch_toggle,
    EFX_OT_batch_check,
    EFX_OT_batch_restore,
    EFX_OT_batch_apply,
    EFX_OT_batch_rescan,
    EFX_PT_batch_edit,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_batch = PointerProperty(type=EFXBatchSettings)
    if reset_state not in session_core._cache_resets:
        session_core._cache_resets.append(reset_state)


def unregister():
    try:
        del bpy.types.Scene.efx_batch
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    reset_state()
