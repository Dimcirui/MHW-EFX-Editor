"""
blender_efx/add_section_ops.py  —  从无到有新建 Play / Extern / Subselect 段条目

设计原则（参照 CLAUDE.md / add_ops.py / delete_ops.py）：
  - Python 3.11 语法（目标 Blender 4.3.2）
  - bpy 只用稳定子集（Operator / Panel / 自定义属性）
  - efx_format/ 是纯 Python 层，本文件是胶水层（不改 efx_format/）
  - byte-perfect：新建条目用「真实样本抓取的模板字节」种子，opaque 区合法；
    header 计数/标签表/subselect_size 全部由 io_tree 导出端按实际内容重算
    （count_* = len(对象)；labels_dirty=1 → 重建标签前缀；subselect_dirty=1 → 重算 size）。

为什么是"容器式"创建（参照与用户的讨论）：
  Play/Extern/Subselect 更像关系容器而非参数块——真正可调的视觉参数在 body 块里。
  所以"新建"= 建一个带合法空白模板的容器对象 + 设段局部 index + 置脏标志，
  导出端自动把它纳入 header / 标签表。引用（targets / 成员）由用户后续在面板里接线。

标签前缀规则（与 reorder.can_label_body 同源）：
  EFX_Type 标签表是 [Play|Extern|Main] 全局顺序的**连续前缀**。新建的 play/extern
  追加在本组末尾，其 has_label = "它前面的所有条目（全局序）当前是否都有标签"：
    - 全标签文件（语料 29/34）：前面 play/extern 都有标签 → 新条目也给标签；
    - 无标签文件（语料 5/34，nlabels=0）：前面无标签 → 新条目 has_label=0。
  这条规则可证明保持合法前缀（旧状态合法前缀 + 末尾追加）。subselect 不在标签表内，无此顾虑。

模板字节来源（efx_samples 语料抓取）：
  - PLAYEMITTER unkn[7]：corpus 中最常见的 28 字节模式（int[2]==4 标记），xyz 缺省 (1,1,1) 缩放，0 targets。
  - ExternAttribute：最小的真实 extern（wp08_061.efx 的 EXTERNSPAWN，172 字节），整体作为起始模板。
    ⚠ extern 内容当前 opaque 不可编辑，新建出来是个合法的"起始模板"，需配合 EXTERNREFERENCE 块使用。
"""

import base64
import struct

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .i18n import T
from .add_ops import get_active_efx_root


# ─────────────────────────────────────────────────────────────────────────────
# 模板常量（真实样本抓取）
# ─────────────────────────────────────────────────────────────────────────────

# PLAYEMITTER unkn[7]（28B）：corpus 最常见模式（int[2]=4 标记），其余 0。
_BLANK_EMITTER_UNKN7 = bytes.fromhex(
    "02000000000000000000000004000000000000000000000000000000"
)
# 新建 Play 的 play_type 缺省值（corpus 最常见 hash；语义未知，面板可改）。
_BLANK_PLAY_TYPE = 0xBF9F765B

# ── Extern 子类型模板（ExternAttribute.serialize()，byte-perfect 往返验证）────────
# EXTERNSPAWN   172B  来源：wp08_061.efx（单类型 ExternAttribute）
_BLANK_EXTERN_B64 = (
    "pgdIxQAAAAABAAAAAAAAAGHIswEBAAAAAgAAAAAAAAABAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAABAAAAEAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABQAAAAAAAAAAQAAAAAAAAAAAAAAAAAA"
    "AA=="
)
# EXTERNRGBFIRE  252B  来源：wp08_001.efx（单类型 ExternAttribute）
_BLANK_EXTERN_RGBFIRE_B64 = "cqQ1NwAAAAABAAAAAAAAAHJVVHsHAAAAAgAAAAAAAAD/////AACAP/////8AAKBAAAAAAAAAAAAAAEhCAAAAAAAAAAAAAAAAFAAAAAAAAAAoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABQAAAAAAAAAKAAAAAAAAAABAAAAAAAAAAAAAAAAAAAA/////wAAgD//////AACgQAAAAAAAAIA/AABIQgAAAAAAAAAAAAAAABQAAAAAAAAAKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAUAAAAAAAAACgAAAAAAAAAAQAAAAAAAAAAAAAA"  # noqa: E501
# EXTERNVELOCITY3D  244B  attr_type=0xBBDA4B3A，unkn=5，attr_count=2，data=zeros×216B
_BLANK_EXTERN_VELOCITY3D_B64 = "OkvauwAAAAABAAAAAAAAAFFg+RQFAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="  # noqa: E501
# EXTERNSCALEANIM  180B  attr_type=0xBBDA4B3A，unkn=3，attr_count=2，data=zeros×152B
_BLANK_EXTERN_SCALEANIM_B64 = "OkvauwAAAAABAAAAAAAAAIt74S4DAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # noqa: E501
# EXTERNTRANSFORM3D  484B  attr_type=0xBF688367，unkn=24，attr_count=2，data=zeros×456B
_BLANK_EXTERN_TRANSFORM3D_B64 = "Z4NovwAAAAABAAAAAAAAABA61x0YAAAAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="  # noqa: E501

_EXTERN_TYPE_B64 = {
    'EXTERNSPAWN':       _BLANK_EXTERN_B64,
    'EXTERNRGBFIRE':     _BLANK_EXTERN_RGBFIRE_B64,
    'EXTERNVELOCITY3D':  _BLANK_EXTERN_VELOCITY3D_B64,
    'EXTERNSCALEANIM':   _BLANK_EXTERN_SCALEANIM_B64,
    'EXTERNTRANSFORM3D': _BLANK_EXTERN_TRANSFORM3D_B64,
}

# PlayEFX 空白模板（type_hash 之后，65B）：unkn0/type/unkn[7]/NULL[3] 全零，xyz=(0,0,0)，path="\0"
_BLANK_PLAYEFX_RAW = (
    b'\x00' * 4                          # unkn0
    + struct.pack('<i', 1)               # path_len = 1（仅 null 终止符）
    + b'\x00' * 4                        # type
    + b'\x00' * 28                       # unkn[7]
    + struct.pack('<3f', 0.0, 0.0, 0.0)  # xyz
    + b'\x00' * 12                       # NULL[3]
    + b'\x00'                            # path[1] = null terminator
)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _nn(idx: int) -> str:
    """零填充 2 位序号（>99 不填充），与 io_tree.py / delete_ops.py 命名规则一致。"""
    return str(idx).zfill(2) if idx < 100 else str(idx)


def _sorted_children(root_obj, type_tag):
    """收集 root_obj 直属、~TYPE==type_tag 的对象，按 efx_index 升序。"""
    objs = [o for o in bpy.data.objects
            if o.parent == root_obj and o.get("~TYPE") == type_tag]
    objs.sort(key=lambda o: int(o.get("efx_index", 0)))
    return objs


def _next_index(root_obj, type_tag) -> int:
    """该段现有最大 efx_index + 1（空段 → 0）。"""
    mx = -1
    for o in _sorted_children(root_obj, type_tag):
        try:
            mx = max(mx, int(o.get("efx_index", 0)))
        except (ValueError, TypeError):
            pass
    return mx + 1


def _section_collection(root_obj, suffix: str):
    """
    找 root_obj 所在根集合下、名字以 suffix 结尾的段集合（如 '_0 Play'）；
    找不到则按 <stem><suffix> 新建并挂到根集合下。返回 Collection 或 None。
    """
    root_cols = list(root_obj.users_collection)
    root_col = root_cols[0] if root_cols else None
    if root_col is None:
        return None

    for child in root_col.children:
        if child.name.endswith(suffix):
            return child

    # 从 Main 集合名推导 stem（'<stem>_2 Main'）；失败则用根集合名。
    stem = root_col.name
    try:
        from .subselect import find_main_collection
        mc = find_main_collection(root_obj)
        if mc is not None and mc.name.endswith("_2 Main"):
            stem = mc.name[: -len("_2 Main")]
    except Exception:
        pass

    newc = bpy.data.collections.new(stem + suffix)
    root_col.children.link(newc)
    return newc


def _new_empty(name: str, collection) -> bpy.types.Object:
    """建 Empty 对象（与 io_tree._new_empty 一致）。"""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.1
    collection.objects.link(obj)
    return obj


def _all_labeled(objs) -> bool:
    """objs 是否全部 efx_has_label==1（缺省 1，与导出标签重建默认一致）。"""
    return all(int(o.get("efx_has_label", 1)) == 1 for o in objs)


def _select_only(context, obj) -> None:
    """取消其它选择，选中并激活 obj。"""
    try:
        for o in context.selected_objects:
            o.select_set(False)
    except Exception:
        pass
    obj.select_set(True)
    context.view_layer.objects.active = obj


# ─────────────────────────────────────────────────────────────────────────────
# 核心：新建各段条目
# ─────────────────────────────────────────────────────────────────────────────

def add_subselect(root_obj) -> bpy.types.Object:
    """
    新建一个空白 Subselect 表（0 成员）。成员由用户在面板里增删。

    subselect 不在标签表内，故只需：建对象 + raw_b64 + init props + 置 subselect_dirty。
    导出端：count_subselect=len(对象) 自动重算；subselect_dirty=1 → subselect_size 重算。
    """
    from ..efx_format.efxfile import SubselectTable
    from . import subselect as _subselect

    col = _section_collection(root_obj, "_3 Subselect")
    if col is None:
        raise RuntimeError("找不到/无法新建 Subselect 集合")

    idx = _next_index(root_obj, "EFX_SUBSELECT")
    tbl = SubselectTable(table_type=1, unkn0=(0xFFFFFFFF, 0, 0), entries=[])

    obj = _new_empty(f"{_nn(idx)} subselect_{idx}", col)
    obj["~TYPE"]     = "EFX_SUBSELECT"
    obj["efx_index"] = idx
    obj["raw_b64"]   = _b64enc(tbl.serialize())
    obj.parent       = root_obj

    try:
        _subselect.init_subselect_props(obj, tbl, {})
    except Exception:
        pass

    root_obj["subselect_dirty"] = 1
    return obj


def add_play(root_obj, entry_type='PLAYEMITTER') -> bpy.types.Object:
    """
    新建一个 Play（action）：含 1 个初始 entry，类型由 entry_type 决定。
      'PLAYEMITTER'：空白 PlayEmitter（0 targets，xyz=1,1,1）
      'PLAYEFX'    ：空白 PlayEFX（path=""，xyz=0,0,0）
    targets / 路径由用户在 Play 面板里接线。
    """
    from ..efx_format.efxfile import PlayData, PlayEntry
    from ..efx_format.hashes import PLAYEMITTER, PLAYEFX
    from . import play_emitter as _play_emitter

    col = _section_collection(root_obj, "_0 Play")
    if col is None:
        raise RuntimeError("找不到/无法新建 Play 集合")

    idx = _next_index(root_obj, "EFX_PLAY")

    if entry_type == 'PLAYEFX':
        first_entry = PlayEntry(type_hash=PLAYEFX, raw=_BLANK_PLAYEFX_RAW)
    else:
        emitter_raw = (_BLANK_EMITTER_UNKN7
                       + struct.pack("<3f", 1.0, 1.0, 1.0)
                       + b"\x00" * 12
                       + struct.pack("<i", 0))
        first_entry = PlayEntry(type_hash=PLAYEMITTER, raw=emitter_raw)

    pd = PlayData(play_type=_BLANK_PLAY_TYPE, entries=[first_entry])

    # 标签前缀规则：新 play 追加在 play 组末尾，前面=现有所有 play。
    has_label = _all_labeled(_sorted_children(root_obj, "EFX_PLAY"))
    raw_label = f"play_{idx}"

    obj = _new_empty(f"{_nn(idx)} {raw_label}", col)
    obj["~TYPE"]         = "EFX_PLAY"
    obj["efx_index"]     = idx
    obj["efx_raw_label"] = raw_label
    obj["efx_has_label"] = int(has_label)
    obj["raw_b64"]       = _b64enc(pd.serialize())
    obj.parent           = root_obj

    try:
        _play_emitter.init_play_props(obj, pd, {})
    except Exception:
        pass

    root_obj["labels_dirty"] = 1
    return obj


def add_extern(root_obj, extern_type='EXTERNSPAWN') -> bpy.types.Object:
    """
    新建一个 Extern，extern_type 决定使用哪种模板字节（默认 EXTERNSPAWN）。

    ⚠ extern 内容当前 opaque 不可逐字段编辑——新建出来是个合法占位/起始模板，
    供配合 EXTERNREFERENCE 块引用使用。
    """
    col = _section_collection(root_obj, "_1 Extern")
    if col is None:
        raise RuntimeError("找不到/无法新建 Extern 集合")

    idx = _next_index(root_obj, "EFX_EXTERN")

    # 标签前缀规则：新 extern 追加在 extern 组末尾，前面=所有 play + 现有 extern。
    before = _sorted_children(root_obj, "EFX_PLAY") + _sorted_children(root_obj, "EFX_EXTERN")
    has_label = _all_labeled(before)
    raw_label = f"extern_{idx}"

    raw_b64 = _EXTERN_TYPE_B64.get(extern_type, _BLANK_EXTERN_B64)

    obj = _new_empty(f"{_nn(idx)} {raw_label}", col)
    obj["~TYPE"]         = "EFX_EXTERN"
    obj["efx_index"]     = idx
    obj["efx_raw_label"] = raw_label
    obj["efx_has_label"] = int(has_label)
    obj["raw_b64"]       = raw_b64
    obj.parent           = root_obj

    # 解析模板字节，填充 efx_extern PropertyGroup（同 io_tree import 路径）
    try:
        import base64 as _b64
        from ..efx_format.efxfile import EFXFile as _EFXFile
        from . import extern_props as _ep
        _raw = _b64.b64decode(raw_b64)
        _ea_list, _ = _EFXFile._parse_extern(_raw, 0, 1)
        if _ea_list:
            _ep.init_extern_props(obj, _ea_list[0])
    except Exception:
        pass  # raw_b64 保底

    root_obj["labels_dirty"] = 1
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_add_play(Operator):
    """在 Active EFX 下新建一个 Play(action)，弹窗选择首条目类型"""

    bl_idname      = "efx.add_play"
    bl_label       = "Add Play (Action)"
    bl_description = ("Create a new Play/Action; a dialog lets you choose PlayEmitter or PlayEFX "
                      "as the first entry. The exporter recomputes the header and label table automatically.")
    bl_options     = {"REGISTER", "UNDO"}

    entry_type: EnumProperty(
        name="Entry Type",
        description="Type of the first entry in the new Play",
        items=[
            ('PLAYEMITTER', "PlayEmitter", "Internal body reference (targets[] pointing to Main bodies)"),
            ('PLAYEFX',     "PlayEFX",     "External .efx file call (path + XYZ offset)"),
        ],
        default='PLAYEMITTER',
    )

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "entry_type")

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_play(root, self.entry_type)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add Play: {exc}")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Play: {obj.name}")
        return {"FINISHED"}


class EFX_OT_add_extern(Operator):
    """在 Active EFX 下新建一个 Extern，弹窗选择子类型"""

    bl_idname      = "efx.add_extern"
    bl_label       = "Add Extern"
    bl_description = ("Create a new Extern; a dialog lets you choose the subtype. "
                      "Field editing is not yet supported — the new extern is a valid placeholder.")
    bl_options     = {"REGISTER", "UNDO"}

    extern_type: EnumProperty(
        name="Extern Type",
        description="Subtype of the new Extern (determines the template bytes used)",
        items=[
            ('EXTERNSPAWN',       "ExternSpawn",       "Override spawn parameters (instances, rate, delay, lifespan)"),
            ('EXTERNRGBFIRE',     "ExternRgbFire",     "Override RGB fire color parameters"),
            ('EXTERNVELOCITY3D',  "ExternVelocity3D",  "Override 3D velocity parameters"),
            ('EXTERNSCALEANIM',   "ExternScaleAnim",   "Override scale animation parameters"),
            ('EXTERNTRANSFORM3D', "ExternTransform3D", "Override 3D transform (translate/rotate/scale/velocity)"),
        ],
        default='EXTERNSPAWN',
    )

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Not fully supported — field editing not yet available.", icon="INFO")
        layout.prop(self, "extern_type")

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_extern(root, self.extern_type)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add Extern: {exc}")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Extern ({self.extern_type}): {obj.name}")
        return {"FINISHED"}


class EFX_OT_add_subselect(Operator):
    """在 Active EFX 下新建一个 Subselect 表（空成员，成员在面板里增删）"""

    bl_idname      = "efx.add_subselect"
    bl_label       = "Add Subselect"
    bl_description = ("Create a new empty Subselect table; add member bodies in its panel. "
                      "The exporter recomputes count_subselect and subselect_size automatically")
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_efx_root(context) is not None

    def execute(self, context):
        root = get_active_efx_root(context)
        if root is None:
            self.report({"ERROR"}, "Select an Active EFX collection first")
            return {"CANCELLED"}
        try:
            obj = add_subselect(root)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to add Subselect: {exc}")
            return {"CANCELLED"}
        _select_only(context, obj)
        self.report({"INFO"}, f"Added Subselect: {obj.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_add_play,
    EFX_OT_add_extern,
    EFX_OT_add_subselect,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
