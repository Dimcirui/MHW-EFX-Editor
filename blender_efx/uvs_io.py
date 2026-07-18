"""
blender_efx/uvs_io.py  —  UVS Edition（Phase 2）

UVSEQUENCE 块属性下的 UVS 编辑工具栏。

功能（Phase 2）：
  - 解析 / 序列化 .uvs 文件（Import / Export）
  - Group 列表（UIList，只读浏览）
  - 选中 Group 的路径槽（Path 0-3）+ 类型 + Dynamic 可编辑
  - "Edit UVS"按钮占位（Phase 3 实现弹窗）
  - "GIF to PNG Sequence"按钮占位（Phase 4）

数据存储策略：
  - EFXUVSProps 挂到 Object（efx_uvs），仅 UVSEQUENCE 块对象有意义
  - raw_b64：序列化后的完整 UVS 字节，保证 frame data 等不可编辑字段原样往返
  - groups CollectionProperty：可编辑字段（路径、类型、dynamic）
  - 导出时：decode raw_b64 → 用 CollectionProperty 覆写可变字段 → 重序列化

约束（CLAUDE.md）：
  - Python 3.10 兼容语法
  - bpy 只用稳定子集
  - 不使用 5.x 新增 API
"""

import base64
import os

import bpy
from bpy.props import (
    StringProperty, BoolProperty, IntProperty,
    CollectionProperty, PointerProperty,
)
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .i18n import T


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：从 UVSEQUENCE 块对象取 path 字段值（游戏相对路径）
# ─────────────────────────────────────────────────────────────────────────────

def _get_uvsequence_path(obj) -> str:
    """返回 UVSEQUENCE 块的 path 字段（game-relative）；找不到时返回空字符串。"""
    try:
        bp = obj.efx_block
        for item in bp.field_items:
            if item.ori_name == "path":
                raw = item.string_value
                if isinstance(raw, bytes):
                    return raw.decode("utf-8", errors="replace").rstrip("\x00")
                return str(raw).rstrip("\x00")
    except Exception:
        pass
    return ""


def _is_uvsequence_attribute(obj) -> bool:
    """该对象是否为 UVSEQUENCE 类型的 EFX_ATTRIBUTE。"""
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return False
    try:
        from ..efx_format.hashes import UVSEQUENCE
        return int(obj.efx_block.type_hash_str) == UVSEQUENCE
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Type 槎名称下拉（typeN 保留为真实存储的 int；typeN_ui 是绑定的展示/编辑下拉，
# 靠 update 回调单向写回 typeN——静态 items 列表，不用动态 itemsfunc，规避
# 动态 EnumProperty 的 GC 乱码坑）
# ─────────────────────────────────────────────────────────────────────────────

_TYPE_NAMES = {1: "Diffuse", 2: "Normal", 3: "RMT", 4: "Mask", 5: "Emissive"}
_TYPE_UI_ITEMS = [(str(k), v, "") for k, v in sorted(_TYPE_NAMES.items())]


def _make_type_ui_update(i: int):
    """生成第 i 槎 typeN_ui → typeN 的同步回调（闭包捕获 i，纯函数无 GC 风险）。"""
    def _update(self, context):
        try:
            setattr(self, f"type{i}", int(getattr(self, f"type{i}_ui")))
        except Exception:
            pass
    return _update


def _sync_type_ui(item, i: int) -> None:
    """按 typeN 当前值刷新 typeN_ui 下拉的显示项（未知数值兜底显示 Diffuse）。"""
    raw = getattr(item, f"type{i}")
    setattr(item, f"type{i}_ui", str(raw) if raw in _TYPE_NAMES else '1')


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup：单个 Group 的可编辑字段
# ─────────────────────────────────────────────────────────────────────────────

class EFXUVSGroupProp(PropertyGroup):
    """UVS Group 的可编辑元数据（路径槽 + 类型 + dynamic + 帧生成参数）。"""

    display_name: StringProperty(
        name="Name",
        description="Display name (last path segment of the first path slot)",
    )
    frame_count: IntProperty(name="Frames", min=0)
    dynamic: IntProperty(name="Dynamic", min=0, default=4)
    map_count: IntProperty(name="Path Count", min=0, max=4)

    path0: StringProperty(name="Path 0")
    path1: StringProperty(name="Path 1")
    path2: StringProperty(name="Path 2")
    path3: StringProperty(name="Path 3")

    type0: IntProperty(name="Type 0", min=0, default=1)
    type1: IntProperty(name="Type 1", min=0, default=1)
    type2: IntProperty(name="Type 2", min=0, default=1)
    type3: IntProperty(name="Type 3", min=0, default=1)

    # 下拉展示层（真实数值仍在 typeN，见上方 _sync_type_ui/_make_type_ui_update）
    type0_ui: bpy.props.EnumProperty(name="Type", items=_TYPE_UI_ITEMS, default='1', update=_make_type_ui_update(0))
    type1_ui: bpy.props.EnumProperty(name="Type", items=_TYPE_UI_ITEMS, default='1', update=_make_type_ui_update(1))
    type2_ui: bpy.props.EnumProperty(name="Type", items=_TYPE_UI_ITEMS, default='1', update=_make_type_ui_update(2))
    type3_ui: bpy.props.EnumProperty(name="Type", items=_TYPE_UI_ITEMS, default='1', update=_make_type_ui_update(3))

    # Phase 3：帧生成参数
    grid_h: IntProperty(name="H", min=1, default=1,
                        description="Sprite sheet horizontal cell count",
                        update=lambda self, ctx: setattr(self, "gen_frame_count", self.grid_h * self.grid_v))
    grid_v: IntProperty(name="V", min=1, default=1,
                        description="Sprite sheet vertical cell count",
                        update=lambda self, ctx: setattr(self, "gen_frame_count", self.grid_h * self.grid_v))
    gen_frame_count: IntProperty(
        name="Count", min=0, default=1,
        description="Actual frame count generated (trims trailing leftover grid cells when the frame "
                    "count doesn't divide H×V evenly; 0 or >=H×V means no trimming)",
    )
    # 标签文字按用户实机复现结果对调过（0.2.102）：内部 scan 取值/_gen_frames_grid
    # 生成逻辑没变，只是把标签+说明文字换到了实际匹配的那个取值上。RL_*/*_RL
    # 四个是 0.2.103 补的镜像方向，纵向语义直接照抄对应的 LR_*/*_LR 项（已经过
    # 实机验证），只把横向方向翻了过来——没有再重新猜纵向方向。
    grid_scan: bpy.props.EnumProperty(
        name="Scan",
        items=[
            ('LR_TB', "LR↑", "Left→Right, Bottom→Top (standard UV order)"),
            ('LR_BT', "LR↓", "Left→Right, Top→Bottom (most common)"),
            ('RL_TB', "RL↑", "Right→Left, Bottom→Top"),
            ('RL_BT', "RL↓", "Right→Left, Top→Bottom"),
            ('TB_LR', "BT→", "Bottom→Top, Left→Right"),
            ('BT_LR', "TB→", "Top→Bottom, Left→Right"),
            ('TB_RL', "BT←", "Bottom→Top, Right→Left"),
            ('BT_RL', "TB←", "Top→Bottom, Right→Left"),
        ],
        default='LR_TB',
    )
    # 当前选中帧（用于预览高亮）；导航切帧要立刻挪动高亮矩形，同样需要手动 tag_redraw
    frame_index: IntProperty(name="Frame", min=0, default=0,
                             update=lambda self, ctx: _tag_redraw_editor())


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup：整个 UVS 文件
# ─────────────────────────────────────────────────────────────────────────────

class EFXUVSProps(PropertyGroup):
    """UVS Edition 数据存储（挂到 Object）。"""

    filepath: StringProperty(
        name="UVS File",
        description="Path to the .uvs file on disk",
        subtype="FILE_PATH",
    )
    is_loaded: BoolProperty(name="Loaded", default=False)

    # 完整序列化字节 base64，用于 frame data 等不可编辑字段的往返
    raw_b64: StringProperty(name="Raw Bytes (base64)", default="")

    groups: CollectionProperty(type=EFXUVSGroupProp)
    group_index: IntProperty(name="Group Index", default=0,
                             update=lambda self, ctx: _tag_redraw_editor())

    # Phase 3：IMAGE_EDITOR 参考图名称（bpy.data.images 中的 name）
    ref_image_name: StringProperty(name="Reference Image", default="")


# ─────────────────────────────────────────────────────────────────────────────
# 解析 UVSFile → 填充 EFXUVSProps
# ─────────────────────────────────────────────────────────────────────────────

def _populate_props(props: EFXUVSProps, data: bytes) -> None:
    """从 UVS 字节填充 PropertyGroup（存 raw_b64 + groups）。"""
    from ..efx_format.uvs import UVSFile

    uvs = UVSFile.parse(data)
    props.raw_b64 = base64.b64encode(data).decode("ascii")
    props.groups.clear()

    for g in uvs.groups:
        item = props.groups.add()
        item.frame_count = len(g.frames)
        item.dynamic = int(g.dynamic)
        item.map_count = min(4, len(g.path_indices))

        paths = []
        for idx in g.path_indices[:4]:
            if 0 <= idx < len(uvs.strings):
                paths.append(uvs.strings[idx].path)
            else:
                paths.append("")
        types = []
        for idx in g.path_indices[:4]:
            if 0 <= idx < len(uvs.strings):
                types.append(uvs.strings[idx].type)
            else:
                types.append(1)

        for i, attr in enumerate(["path0", "path1", "path2", "path3"]):
            setattr(item, attr, paths[i] if i < len(paths) else "")
        for i, attr in enumerate(["type0", "type1", "type2", "type3"]):
            setattr(item, attr, types[i] if i < len(types) else 1)
            _sync_type_ui(item, i)

        # 显示名：取第一条路径最后一段（兼容正反斜杠）
        first_path = paths[0] if paths else ""
        last_seg = first_path.replace("\\", "/").split("/")[-1]
        item.display_name = last_seg or f"group_{len(props.groups) - 1}"

    props.is_loaded = True


# ─────────────────────────────────────────────────────────────────────────────
# 从 EFXUVSProps 重建 UVSFile（导出用）
# ─────────────────────────────────────────────────────────────────────────────

def _rebuild_uvs(props: EFXUVSProps) -> bytes:
    """用 PropertyGroup 中的可编辑字段覆写 raw_b64 里的 UVSFile，返回序列化字节。"""
    from ..efx_format.uvs import UVSFile, UVSString

    data = base64.b64decode(props.raw_b64)
    uvs = UVSFile.parse(data)

    # 从 PropertyGroup 收集所有 (path, type) → 去重重建字符串表
    path_type_pairs = []
    seen = {}
    for item in props.groups:
        for i in range(item.map_count):
            p = getattr(item, f"path{i}")
            t = getattr(item, f"type{i}")
            key = (p, t)
            if key not in seen:
                seen[key] = len(path_type_pairs)
                path_type_pairs.append(key)

    uvs.strings = [UVSString(path=p, type=t) for p, t in path_type_pairs]

    # 更新每个 Group 的 dynamic + path_indices（frame data 从 raw 保留）
    for g_orig, item in zip(uvs.groups, props.groups):
        g_orig.dynamic = item.dynamic
        g_orig.map_count = item.map_count
        new_indices = []
        for i in range(item.map_count):
            p = getattr(item, f"path{i}")
            t = getattr(item, f"type{i}")
            key = (p, t)
            new_indices.append(seen.get(key, 0))
        g_orig.path_indices = new_indices

    return uvs.serialize()


# ─────────────────────────────────────────────────────────────────────────────
# Operator：Import UVS
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_import(Operator, ImportHelper):
    """导入 .uvs 文件到当前 UVSEQUENCE 块"""

    bl_idname = "efx.uvs_import"
    bl_label = "Import UVS"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".uvs"
    filter_glob: StringProperty(default="*.uvs", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _is_uvsequence_attribute(context.active_object)

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_uvs
        path = self.filepath
        try:
            with open(path, "rb") as f:
                data = f.read()
            _populate_props(props, data)
            props.filepath = path
            self.report({"INFO"}, T("uvs.imported").format(os.path.basename(path), len(props.groups)))
        except Exception as e:
            self.report({"ERROR"}, T("uvs.import_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator：Export UVS
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_export(Operator, ExportHelper):
    """将当前编辑结果导出为 .uvs 文件"""

    bl_idname = "efx.uvs_export"
    bl_label = "Export UVS"
    bl_options = {"REGISTER"}

    filename_ext = ".uvs"
    filter_glob: StringProperty(default="*.uvs", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return _is_uvsequence_attribute(obj) and getattr(
            getattr(obj, "efx_uvs", None), "is_loaded", False
        )

    def invoke(self, context, event):
        # 用已知路径预填对话框
        props = context.active_object.efx_uvs
        if props.filepath:
            self.filepath = props.filepath
        return super().invoke(context, event)

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_uvs
        try:
            data = _rebuild_uvs(props)
            with open(self.filepath, "wb") as f:
                f.write(data)
            props.filepath = self.filepath
            self.report({"INFO"}, T("uvs.exported").format(os.path.basename(self.filepath)))
        except Exception as e:
            self.report({"ERROR"}, T("uvs.export_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator：Reload UVS from disk
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_reload(Operator):
    """从磁盘重新读取 .uvs 文件（丢弃当前未保存的修改）"""

    bl_idname = "efx.uvs_reload"
    bl_label = "Reload from Disk"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        props = getattr(obj, "efx_uvs", None)
        return (_is_uvsequence_attribute(obj) and props is not None
                and bool(props.filepath) and os.path.isfile(props.filepath))

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_uvs
        try:
            with open(props.filepath, "rb") as f:
                data = f.read()
            _populate_props(props, data)
            self.report({"INFO"}, T("uvs.reloaded"))
        except Exception as e:
            self.report({"ERROR"}, T("uvs.reload_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# UIList：Group 列表
# ─────────────────────────────────────────────────────────────────────────────

class EFX_UL_uvs_groups(UIList):
    """UIList：UVS Group 列表，每行显示序号 + 名称 + 帧数。"""

    bl_idname = "EFX_UL_uvs_groups"

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index}:", icon="BLANK1")
        row.prop(item, "display_name", text="", emboss=False)
        row.label(text=f"{item.frame_count}f")


# ─────────────────────────────────────────────────────────────────────────────
# Panel：UVS Edition（挂在 EFX_PT_attribute_fields 下）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_uvs_edition(Panel):
    """UVS Edition — 顶层面板，仅在选中 UVSEQUENCE 属性时显示

    工具类特性 → 只放 N 面板（不放属性编辑器）；bl_order=0 压在 Attribute Properties 之上。
    """

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "UVS Edition"
    bl_order       = 0
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _is_uvsequence_attribute(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object
        props  = obj.efx_uvs

        # ── UVS 游戏路径（只读显示，来自块字段）──────────────────────────────
        game_path = _get_uvsequence_path(obj)
        if game_path:
            box = layout.box()
            row = box.row()
            row.label(text=T("uvs.game_path"), icon="FILE")
            row.label(text=game_path)

        # ── Import / Export / Reload ──────────────────────────────────────────
        row = layout.row(align=True)
        row.operator("efx.uvs_import", icon="IMPORT", text="Import")
        if props.is_loaded:
            row.operator("efx.uvs_export", icon="EXPORT", text="Export")
            row.operator("efx.uvs_reload", icon="FILE_REFRESH", text="")

        # ── GIF → PNG 精灵表（Phase 4，独立于 UVS 是否已加载）──────────────────
        box = layout.box()
        box.label(text=T("uvs.gif_to_png_box"), icon="IMAGE_DATA")
        if _check_pillow():
            box.operator("efx.uvs_gif_to_png", icon="RENDER_ANIMATION")
        else:
            box.label(text=T("uvs.need_pillow"), icon="ERROR")
            box.label(text=T("uvs.pip_install_hint"))

        if not props.is_loaded:
            layout.label(text=T("uvs.not_loaded"), icon="INFO")
            return

        # ── Group 列表 ────────────────────────────────────────────────────────
        row = layout.row()
        row.label(text=T("uvs.groups_count").format(n=len(props.groups)), icon="SEQUENCE")
        sub = row.row(align=True)
        sub.operator("efx.uvs_group_add",    text="", icon="ADD")
        sub.operator("efx.uvs_group_remove", text="", icon="REMOVE")
        sub.separator()
        sub.operator("efx.uvs_group_move", text="", icon="TRIA_UP").direction = 'UP'
        sub.operator("efx.uvs_group_move", text="", icon="TRIA_DOWN").direction = 'DOWN'
        layout.template_list(
            "EFX_UL_uvs_groups", "",
            props, "groups",
            props, "group_index",
            rows=4,
        )

        # ── 选中 Group 详情 ───────────────────────────────────────────────────
        idx = props.group_index
        if 0 <= idx < len(props.groups):
            g = props.groups[idx]
            box = layout.box()
            row = box.row(align=True)
            row.label(text=T("uvs.group_header").format(idx), icon="LAYER_ACTIVE")
            row.prop(g, "display_name", text="")

            row = box.row()
            row.prop(g, "dynamic")
            row.label(text=T("uvs.frame_count_suffix").format(g.frame_count))

            box.separator(factor=0.5)
            box.label(text=T("uvs.path_slots"), icon="IMAGE_DATA")

            for i in range(4):
                path_attr = f"path{i}"
                type_ui_attr = f"type{i}_ui"

                row = box.row(align=True)
                row.label(text=f"{i+1}", icon="BLANK1")
                if i < g.map_count:
                    sub = row.row(align=True)
                    sub.prop(g, path_attr, text="")
                    sub.prop(g, type_ui_attr, text="")
                    if i == g.map_count - 1:
                        row.operator("efx.uvs_slot_remove", text="", icon="REMOVE")
                elif i == g.map_count:
                    row.label(text=T("uvs.empty_slot"), icon="BLANK1")
                    row.operator("efx.uvs_slot_add", text="", icon="ADD")
                else:
                    row.label(text=T("uvs.empty_slot"), icon="BLANK1")

        layout.separator(factor=0.5)

        # ── Edit UVS 弹窗 ─────────────────────────────────────────────────────
        if _edit_state["window"] is not None:
            layout.operator("efx.uvs_close_editor", text=T("uvs.close_editor_btn"), icon="X")
        else:
            layout.operator("efx.uvs_edit", text="Edit UVS", icon="WINDOW")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES_P2 = [
    EFXUVSGroupProp,
    EFXUVSProps,
    EFX_UL_uvs_groups,
    EFX_OT_uvs_import,
    EFX_OT_uvs_export,
    EFX_OT_uvs_reload,
    EFX_PT_uvs_edition,
]

# Phase 3 & 4 classes appended after their definitions below
_CLASSES_P3 = []  # filled after class definitions
_CLASSES_P4 = []  # filled after class definitions


def register():
    for cls in _CLASSES_P2 + _CLASSES_P3 + _CLASSES_P4:
        bpy.utils.register_class(cls)
    bpy.types.Object.efx_uvs = PointerProperty(
        name="EFX UVS Edition",
        description="UVS 文件编辑数据（仅 UVSEQUENCE 块对象有意义）",
        type=EFXUVSProps,
    )
    bpy.types.WindowManager.efx_uvs_edit_obj = StringProperty(
        name="UVS Edit Object",
        description="当前 UVS 编辑器正在编辑的对象名称",
        default="",
    )


def unregister():
    _cleanup_edit_state()
    if hasattr(bpy.types.WindowManager, "efx_uvs_edit_obj"):
        del bpy.types.WindowManager.efx_uvs_edit_obj
    if hasattr(bpy.types.Object, "efx_uvs"):
        del bpy.types.Object.efx_uvs
    for cls in reversed(_CLASSES_P2 + _CLASSES_P3 + _CLASSES_P4):
        bpy.utils.unregister_class(cls)


# =============================================================================
# Phase 3 — UVS 编辑弹窗（新窗口 + Image Editor + GPU overlay）
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 编辑器状态（模块级，保证生命周期与 draw handler 绑定）
# ─────────────────────────────────────────────────────────────────────────────

_edit_state = {
    "draw_handler": None,  # SpaceImageEditor draw handler 引用
    "window": None,        # 编辑器窗口对象引用
}

_frame_cache = {}          # raw_b64 cache key → list[UVSFrame]


def _tag_redraw_editor():
    """标脏编辑器窗口里的 IMAGE_EDITOR 区域，强制重跑 GPU draw handler。

    POST_VIEW draw handler 不会在底层数据（raw_b64）变化后自动重绘——
    必须显式 tag_redraw()，否则叠加层矩形停留在旧状态，直到用户做出
    其他触发重绘的操作（移动鼠标/缩放窗口等）才会刷新。
    """
    win = _edit_state.get("window")
    if win is None:
        return
    try:
        for area in win.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()
    except Exception:
        pass


def _cleanup_edit_state():
    """移除 draw handler，清空编辑状态。调用方负责时序正确。"""
    _frame_cache.clear()
    if _edit_state["draw_handler"] is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(
                _edit_state["draw_handler"], 'WINDOW'
            )
        except Exception:
            pass
        _edit_state["draw_handler"] = None
    _edit_state["window"] = None
    try:
        bpy.context.window_manager.efx_uvs_edit_obj = ""
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 帧缓存（避免每帧 decode + parse）
# ─────────────────────────────────────────────────────────────────────────────

def _get_frames_for_group(raw_b64: str, group_idx: int):
    """返回指定 Group 的 UVSFrame 列表，带简单 LRU-like 缓存。"""
    cache_key = (len(raw_b64), raw_b64[-32:], group_idx)
    if cache_key in _frame_cache:
        return _frame_cache[cache_key]
    try:
        from ..efx_format.uvs import UVSFile
        data = base64.b64decode(raw_b64)
        uvs = UVSFile.parse(data)
        frames = uvs.groups[group_idx].frames if 0 <= group_idx < len(uvs.groups) else []
    except Exception:
        frames = []
    if len(_frame_cache) > 30:
        _frame_cache.clear()
    _frame_cache[cache_key] = frames
    return frames


# ─────────────────────────────────────────────────────────────────────────────
# GPU draw handler：在 IMAGE_EDITOR 上画 UV 矩形覆盖层
# ─────────────────────────────────────────────────────────────────────────────

def _uvs_draw_handler():
    """POST_VIEW draw handler：在当前编辑 Group 的帧 UV 范围上画彩色矩形。"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return

    context = bpy.context

    # 仅在我们打开的窗口里画
    if _edit_state["window"] is None or context.window != _edit_state["window"]:
        return

    wm = context.window_manager
    obj_name = getattr(wm, "efx_uvs_edit_obj", "")
    if not obj_name:
        return
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return
    props = getattr(obj, "efx_uvs", None)
    if props is None or not props.is_loaded:
        return

    idx = props.group_index
    if not (0 <= idx < len(props.groups)):
        return

    frames = _get_frames_for_group(props.raw_b64, idx)
    if not frames:
        return

    selected = max(0, min(props.groups[idx].frame_index, len(frames) - 1))

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)

    for i, frame in enumerate(frames):
        u0, v0 = frame.uv0
        u1, v1 = frame.uv1
        # ⚠ 这个翻转是照"v 越大越靠近贴图顶部"的旧假设调的；0.4.3 实机测试已
        # 证实那个假设是反的（真实 v 越大越靠近贴图底部，见 EFX_OT_uvs_frame_edit
        # 的订正）。但这里翻转后配合 _gen_frames_pixel_grid（未做 1-v 翻转）已
        # 实机截图确认选中帧正确显示在左上角——两个"错"抵消出了当前预览效果
        # 正确的结果，暂不改动；如果之后改 _gen_frames_grid/这里任何一处，要
        # 连带重新验证预览方向，不要只改一处。
        v0, v1 = 1.0 - v0, 1.0 - v1
        if i == selected:
            color = (1.0, 0.85, 0.0, 1.0)   # 黄色：选中帧
        else:
            color = (0.25, 0.65, 1.0, 0.55)  # 蓝色：其他帧

        verts = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        batch = batch_for_shader(shader, 'LINE_LOOP', {"pos": verts})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# 帧生成辅助
# ─────────────────────────────────────────────────────────────────────────────

def _gen_frames_grid(H: int, V: int, scan: str, count: int = None):
    """按 H×V 网格和扫描方向生成 UVSFrame 列表，count 非 0 且小于 H×V 时裁剪掉末尾多余帧。"""
    from ..efx_format.uvs import UVSFrame
    w, h = 1.0 / H, 1.0 / V

    # ⚠ 0.4.3：实机测试确认 EFX_OT_uvs_frame_edit 原先"v 越大越靠近贴图顶部"的
    # 假设是反的（真实是 v 越大越靠近贴图底部），已订正该处 Top/Bottom 标签；
    # 但这里的 ri↔"上/下"映射、以及下面 GPU 叠加层的翻转是否也要跟着改，尚未
    # 用同样方式实机验证——LR_TB 等 scan 选项的实际游戏内播放方向可能因此和
    # 标签描述不符，改动前先找具体数值复现，不要凭这条注释直接反转。
    # j 是"播放顺序批次"（0 起），下面把 j 映到 ri，让实际（游戏内）播放方向和 scan 标签一致。
    # RL_*/*_RL 四个是 LR_*/*_LR 的镜像：纵向 ri 公式原样照抄，只把横向 ci 换成 H-1-i。
    if scan == 'LR_TB':    # 左→右 上→下：先播最上面一行（ri=V-1，v 最大），逐行往下
        pairs = [(i, V - 1 - j) for j in range(V) for i in range(H)]
    elif scan == 'LR_BT':  # 左→右 下→上：先播最下面一行（ri=0，v 最小），逐行往上
        pairs = [(i, j) for j in range(V) for i in range(H)]
    elif scan == 'RL_TB':  # 右→左 上→下（LR_TB 的横向镜像）
        pairs = [(H - 1 - i, V - 1 - j) for j in range(V) for i in range(H)]
    elif scan == 'RL_BT':  # 右→左 下→上（LR_BT 的横向镜像）
        pairs = [(H - 1 - i, j) for j in range(V) for i in range(H)]
    elif scan == 'TB_LR':  # 上→下 左→右
        pairs = [(i, V - 1 - j) for i in range(H) for j in range(V)]
    elif scan == 'BT_LR':  # 下→上 左→右
        pairs = [(i, j) for i in range(H) for j in range(V)]
    elif scan == 'TB_RL':  # 上→下 右→左（TB_LR 的横向镜像）
        pairs = [(H - 1 - i, V - 1 - j) for i in range(H) for j in range(V)]
    else:                  # BT_RL：下→上 右→左（BT_LR 的横向镜像）
        pairs = [(H - 1 - i, j) for i in range(H) for j in range(V)]

    frames = []
    for ci, ri in pairs:
        u0, v0 = ci * w, ri * h
        u1, v1 = (ci + 1) * w, (ri + 1) * h
        frames.append(UVSFrame(uv0=(u0, v0), uv1=(u1, v1)))

    if count and 0 < count < len(frames):
        frames = frames[:count]
    return frames


# ─────────────────────────────────────────────────────────────────────────────
# Operator：打开 UVS 编辑器（modal，管理窗口生命周期）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_edit(Operator):
    """打开 UVS 编辑器窗口（Image Editor + UV 叠加层）"""

    bl_idname = "efx.uvs_edit"
    bl_label  = "Edit UVS"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return _is_uvsequence_attribute(obj) and getattr(
            getattr(obj, "efx_uvs", None), "is_loaded", False
        )

    def invoke(self, context, event):
        # 已有编辑器在跑 → 检测窗口是否仍存在
        if _edit_state["window"] is not None:
            if _edit_state["window"] in context.window_manager.windows[:]:
                self.report({"INFO"}, T("uvs.editor_open_already"))
                return {"CANCELLED"}
            _cleanup_edit_state()

        # 记录编辑目标
        context.window_manager.efx_uvs_edit_obj = context.active_object.name

        # 开新窗口并切换到 Image Editor
        bpy.ops.wm.window_new()
        new_win = context.window_manager.windows[-1]
        _edit_state["window"] = new_win
        new_win.screen.areas[0].type = "IMAGE_EDITOR"

        # 注册 GPU draw handler
        handler = bpy.types.SpaceImageEditor.draw_handler_add(
            _uvs_draw_handler, (), 'WINDOW', 'POST_VIEW'
        )
        _edit_state["draw_handler"] = handler

        # 启动 modal 监控窗口关闭
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _edit_state["window"] is None:
            return {"FINISHED"}
        if _edit_state["window"] not in context.window_manager.windows[:]:
            _cleanup_edit_state()
            return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        _cleanup_edit_state()


# ─────────────────────────────────────────────────────────────────────────────
# Operator：关闭编辑器（从 Image Editor 内部触发）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_close_editor(Operator):
    """关闭 UVS 编辑器窗口并清理 draw handler"""

    bl_idname  = "efx.uvs_close_editor"
    bl_label   = "Close UVS Editor"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _edit_state["window"] is not None

    def execute(self, context):
        _cleanup_edit_state()
        # 若当前窗口就是编辑器窗口，直接关闭
        try:
            bpy.ops.wm.window_close()
        except Exception:
            pass
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator：按 H×V 网格生成帧序列
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_gen_frames(Operator):
    """按当前 H×V 网格参数重新生成选中 Group 的 UV 帧序列"""

    bl_idname  = "efx.uvs_gen_frames"
    bl_label   = "Generate Frames"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        obj = bpy.data.objects.get(getattr(wm, "efx_uvs_edit_obj", ""))
        if obj is None:
            return False
        props = getattr(obj, "efx_uvs", None)
        return props is not None and props.is_loaded and len(props.groups) > 0

    def execute(self, context):
        wm = context.window_manager
        obj = bpy.data.objects.get(getattr(wm, "efx_uvs_edit_obj", ""))
        props = obj.efx_uvs
        idx = props.group_index
        if not (0 <= idx < len(props.groups)):
            self.report({"ERROR"}, T("uvs.invalid_group_index"))
            return {"CANCELLED"}

        g_prop = props.groups[idx]
        H, V, scan = g_prop.grid_h, g_prop.grid_v, g_prop.grid_scan
        new_frames = _gen_frames_grid(H, V, scan, g_prop.gen_frame_count)

        try:
            from ..efx_format.uvs import UVSFile
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
            g    = uvs.groups[idx]
            g.frames         = new_frames
            g._frame_indices = list(range(len(new_frames)))
            props.raw_b64    = base64.b64encode(uvs.serialize()).decode("ascii")
            g_prop.frame_count = len(new_frames)
            g_prop.frame_index = 0
            _frame_cache.clear()
            _tag_redraw_editor()
            self.report({"INFO"}, T("uvs.frames_generated").format(len(new_frames), H, V, scan))
        except Exception as e:
            self.report({"ERROR"}, T("uvs.generate_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Operator：自定义帧编辑（增删/重排/改矩形，不依赖 CSV）
# 均沿用 EFX_OT_uvs_gen_frames 的约定：只在编辑器窗口内可用，走 wm.efx_uvs_edit_obj。
# ─────────────────────────────────────────────────────────────────────────────

def _get_edit_group(context):
    """返回编辑器窗口当前正在编辑的 (props, group_index)，取不到时返回 (None, -1)。"""
    wm = context.window_manager
    obj = bpy.data.objects.get(getattr(wm, "efx_uvs_edit_obj", ""))
    if obj is None:
        return None, -1
    props = getattr(obj, "efx_uvs", None)
    if props is None or not props.is_loaded:
        return None, -1
    idx = props.group_index
    if not (0 <= idx < len(props.groups)):
        return None, -1
    return props, idx


class EFX_OT_uvs_frame_edit(Operator):
    """编辑当前选中帧的 UV 矩形（弹窗输入左/右/上/下四条边）"""

    bl_idname  = "efx.uvs_frame_edit"
    bl_label   = "Edit Frame"
    bl_options = {"REGISTER", "UNDO"}

    # uv0=(Left,Top)、uv1=(Right,Bottom)：0.4.3 实机测试订正——之前假设"v 越大
    # 越靠近贴图顶部"（uv1.v 是上边）是反的，实机验证 flip=0 时按旧假设显示会
    # 上下翻转；真实约定是 v 越大越靠近贴图底部，故 uv0.v 才是上边、uv1.v 是
    # 下边。这里只改哪个字段叫"Top"/"Bottom"，数值不动——网格生成的帧恒有
    # uv0.v < uv1.v，直接一一对应改名，不做 min/max 重排，避免把游戏里本来就
    # 镜像/翻转过的自定义帧的边序改坏。
    left:   bpy.props.FloatProperty(name="Left")
    top:    bpy.props.FloatProperty(name="Top")
    right:  bpy.props.FloatProperty(name="Right")
    bottom: bpy.props.FloatProperty(name="Bottom")

    @classmethod
    def poll(cls, context):
        props, idx = _get_edit_group(context)
        return props is not None and props.groups[idx].frame_count > 0

    def invoke(self, context, event):
        props, idx = _get_edit_group(context)
        g_prop = props.groups[idx]
        frames = _get_frames_for_group(props.raw_b64, idx)
        fi = max(0, min(g_prop.frame_index, len(frames) - 1)) if frames else 0
        if frames:
            f = frames[fi]
            self.left, self.top = f.uv0
            self.right, self.bottom = f.uv1
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "top")
        row = layout.row(align=True)
        row.prop(self, "left")
        row.prop(self, "right")
        layout.prop(self, "bottom")

    def execute(self, context):
        from ..efx_format.uvs import UVSFile

        props, idx = _get_edit_group(context)
        g_prop = props.groups[idx]
        fi = max(0, min(g_prop.frame_index, g_prop.frame_count - 1))
        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
            frame = uvs.groups[idx].frames[fi]
            frame.uv0 = (self.left, self.top)
            frame.uv1 = (self.right, self.bottom)
            props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
            _frame_cache.clear()
            _tag_redraw_editor()
        except Exception as e:
            self.report({"ERROR"}, T("uvs.edit_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class EFX_OT_uvs_frame_insert(Operator):
    """在当前帧之后插入一帧（复制当前帧的 UV 矩形；组内无帧时插入全图 UV）"""

    bl_idname  = "efx.uvs_frame_insert"
    bl_label   = "Insert Frame"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props, idx = _get_edit_group(context)
        return props is not None

    def execute(self, context):
        from ..efx_format.uvs import UVSFile, UVSFrame

        props, idx = _get_edit_group(context)
        g_prop = props.groups[idx]
        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
            g    = uvs.groups[idx]
            n    = len(g.frames)
            insert_at = min(g_prop.frame_index + 1, n) if n else 0
            if n:
                src = g.frames[max(0, min(g_prop.frame_index, n - 1))]
                new_frame = UVSFrame(uv0=src.uv0, uv1=src.uv1)
            else:
                new_frame = UVSFrame(uv0=(0.0, 0.0), uv1=(1.0, 1.0))
            g.frames.insert(insert_at, new_frame)
            g._frame_indices = list(range(len(g.frames)))
            props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
            g_prop.frame_count = len(g.frames)
            g_prop.frame_index = insert_at
            _frame_cache.clear()
            _tag_redraw_editor()
        except Exception as e:
            self.report({"ERROR"}, T("uvs.insert_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class EFX_OT_uvs_frame_delete(Operator):
    """删除当前选中帧"""

    bl_idname  = "efx.uvs_frame_delete"
    bl_label   = "Delete Frame"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props, idx = _get_edit_group(context)
        return props is not None and props.groups[idx].frame_count > 0

    def execute(self, context):
        from ..efx_format.uvs import UVSFile

        props, idx = _get_edit_group(context)
        g_prop = props.groups[idx]
        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
            g    = uvs.groups[idx]
            n    = len(g.frames)
            fi   = max(0, min(g_prop.frame_index, n - 1))
            g.frames.pop(fi)
            g._frame_indices = list(range(len(g.frames)))
            props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
            g_prop.frame_count = len(g.frames)
            g_prop.frame_index = max(0, min(fi, len(g.frames) - 1))
            _frame_cache.clear()
            _tag_redraw_editor()
        except Exception as e:
            self.report({"ERROR"}, T("uvs.delete_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class EFX_OT_uvs_frame_move(Operator):
    """交换当前帧与相邻帧的播放顺序（自定义播放顺序，无需 CSV）"""

    bl_idname  = "efx.uvs_frame_move"
    bl_label   = "Move Frame"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
        default='UP',
    )

    @classmethod
    def poll(cls, context):
        props, idx = _get_edit_group(context)
        return props is not None and props.groups[idx].frame_count > 1

    def execute(self, context):
        from ..efx_format.uvs import UVSFile

        props, idx = _get_edit_group(context)
        g_prop = props.groups[idx]
        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
            g    = uvs.groups[idx]
            n    = len(g.frames)
            fi   = max(0, min(g_prop.frame_index, n - 1))
            target = fi - 1 if self.direction == 'UP' else fi + 1
            if not (0 <= target < n):
                self.report({"INFO"}, T("uvs.at_boundary"))
                return {"CANCELLED"}
            g.frames[fi], g.frames[target] = g.frames[target], g.frames[fi]
            props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
            g_prop.frame_index = target
            _frame_cache.clear()
            _tag_redraw_editor()
        except Exception as e:
            self.report({"ERROR"}, T("uvs.move_failed").format(e))
            return {"CANCELLED"}
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel：IMAGE_EDITOR 侧边栏（"UVS" 标签页）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_uvs_editor(Panel):
    """UVS 编辑器主面板（仅显示在 efx.uvs_edit 打开的 Image Editor 窗口里）"""

    bl_space_type  = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category    = "UVS"
    bl_label       = "UVS Editor"

    @classmethod
    def poll(cls, context):
        if _edit_state["window"] is None:
            return False
        return context.window == _edit_state["window"]

    def draw(self, context):
        layout = self.layout
        wm     = context.window_manager

        obj_name = getattr(wm, "efx_uvs_edit_obj", "")
        obj      = bpy.data.objects.get(obj_name)
        if obj is None:
            layout.label(text=T("uvs.editor_target_missing"), icon="ERROR")
            layout.operator("efx.uvs_close_editor", icon="X")
            return
        props = obj.efx_uvs

        # ── 标题 + 关闭 ──────────────────────────────────────────────────────
        row = layout.row()
        row.label(text=obj_name, icon="OBJECT_DATA")
        row.operator("efx.uvs_close_editor", text="", icon="X")

        # ── 参考图 ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("uvs.reference_image"), icon="IMAGE_DATA")
        box.prop_search(props, "ref_image_name", bpy.data, "images", text="")
        row = box.row(align=True)
        row.operator("image.open", text=T("uvs.load_image_btn"), icon="FILE_FOLDER")
        # 把选中图片设到当前 Image Editor
        if props.ref_image_name:
            img = bpy.data.images.get(props.ref_image_name)
            if img and context.space_data:
                if context.space_data.image != img:
                    context.space_data.image = img

        layout.separator(factor=0.3)

        # ── Group 列表 ────────────────────────────────────────────────────────
        row = layout.row()
        row.label(text=T("uvs.groups_count").format(n=len(props.groups)), icon="SEQUENCE")
        sub = row.row(align=True)
        sub.operator("efx.uvs_group_add",    text="", icon="ADD")
        sub.operator("efx.uvs_group_remove", text="", icon="REMOVE")
        sub.separator()
        sub.operator("efx.uvs_group_move", text="", icon="TRIA_UP").direction = 'UP'
        sub.operator("efx.uvs_group_move", text="", icon="TRIA_DOWN").direction = 'DOWN'
        layout.template_list(
            "EFX_UL_uvs_groups", "editor",
            props, "groups",
            props, "group_index",
            rows=4,
        )

        idx = props.group_index
        if not (0 <= idx < len(props.groups)):
            return
        g = props.groups[idx]

        # ── 路径槽 + Dynamic ─────────────────────────────────────────────────
        box = layout.box()
        row = box.row(align=True)
        row.label(text=T("uvs.group_header").format(idx), icon="LAYER_ACTIVE")
        row.prop(g, "display_name", text="")
        row = box.row()
        row.prop(g, "dynamic")
        row.label(text=T("uvs.frame_count_suffix").format(g.frame_count))

        box.separator(factor=0.3)
        box.label(text=T("uvs.path_slots"), icon="RENDERLAYERS")
        for i in range(4):
            path_attr = f"path{i}"
            type_ui_attr = f"type{i}_ui"
            row = box.row(align=True)
            row.label(text=f"{i+1}")
            if i < g.map_count:
                row.prop(g, path_attr, text="")
                row.prop(g, type_ui_attr, text="")
                if i == g.map_count - 1:
                    row.operator("efx.uvs_slot_remove", text="", icon="REMOVE")
            elif i == g.map_count:
                row.label(text=T("uvs.empty_slot"))
                row.operator("efx.uvs_slot_add", text="", icon="ADD")
            else:
                row.label(text=T("uvs.empty_slot"))

        layout.separator(factor=0.3)

        # ── 帧生成 ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("uvs.frame_gen_box"), icon="RENDER_ANIMATION")
        row = box.row(align=True)
        row.prop(g, "grid_h", text="H")
        row.prop(g, "grid_v", text="V")
        box.prop(g, "grid_scan", text=T("uvs.scan_label"))
        box.prop(g, "gen_frame_count", text=T("uvs.frame_count_trim_label"))
        sub = box.row()
        sub.scale_y = 1.2
        sub.operator("efx.uvs_gen_frames", icon="PLAY")

        layout.separator(factor=0.3)

        # ── 帧导航（高亮选中帧）+ 自定义帧编辑（增删/重排/改矩形）────────────────
        box = layout.box()
        box.label(text=T("uvs.frame_preview_box"), icon="KEYFRAME")
        row = box.row(align=True)
        row.prop(g, "frame_index", text=T("uvs.frame_label"))
        row.label(text=f"/ {g.frame_count}")

        row = box.row(align=True)
        row.operator("efx.uvs_frame_move", text="", icon="TRIA_UP").direction = 'UP'
        row.operator("efx.uvs_frame_move", text="", icon="TRIA_DOWN").direction = 'DOWN'
        row.operator("efx.uvs_frame_insert", text="", icon="ADD")
        row.operator("efx.uvs_frame_delete", text="", icon="REMOVE")

        # 显示选中帧的边框位置（Left/Top/Right/Bottom）
        frames = _get_frames_for_group(props.raw_b64, idx)
        fi = max(0, min(g.frame_index, len(frames) - 1)) if frames else 0
        if frames:
            f = frames[fi]
            col = box.column(align=True)
            col.label(text=f"Top={f.uv0[1]:.3f}   Left={f.uv0[0]:.3f}  Right={f.uv1[0]:.3f}")
            col.label(text=f"Bottom={f.uv1[1]:.3f}")
            box.operator("efx.uvs_frame_edit", text=T("uvs.edit_frame_border_btn"), icon="GREASEPENCIL")
        else:
            box.label(text=T("uvs.no_frame_data"), icon="INFO")

        layout.separator(factor=0.3)

        # ── 保存 ─────────────────────────────────────────────────────────────
        row = layout.row()
        row.scale_y = 1.3
        row.operator("efx.uvs_export", text=T("uvs.save_uvs_btn"), icon="FILE_TICK")


# =============================================================================
# Group 增删操作符
# =============================================================================

class EFX_OT_uvs_group_add(Operator):
    """在当前选中位置之后新增一个空 UVS Group"""

    bl_idname  = "efx.uvs_group_add"
    bl_label   = "Add UVS Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            _is_uvsequence_attribute(obj)
            and getattr(getattr(obj, "efx_uvs", None), "is_loaded", False)
        )

    def execute(self, context):
        from ..efx_format.uvs import UVSFile, UVSGroup, UVSFrame

        props = context.active_object.efx_uvs
        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
        except Exception as e:
            self.report({"ERROR"}, T("uvs.parse_failed").format(e))
            return {"CANCELLED"}

        insert_at = props.group_index + 1
        # 默认 1 帧覆盖整张图（(0,0)-(1,1)），dynamic 默认 4——实测绝大多数游戏
        # 文件里这个值就是 4，参考工具 UI 的 spinbox 默认值也是 4。
        new_g = UVSGroup(
            frames=[UVSFrame(uv0=(0.0, 0.0), uv1=(1.0, 1.0))],
            path_indices=[],
            map_count=0,
            dynamic=4,
        )
        uvs.groups.insert(insert_at, new_g)

        props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
        _frame_cache.clear()
        _tag_redraw_editor()

        # 在 CollectionProperty 同位置插入
        props.groups.add()                              # 追加一个空槽
        for i in range(len(props.groups) - 1, insert_at, -1):
            # CollectionProperty 无 insert，只能从末尾向前逐步移动
            props.groups.move(i - 1, i)
        item = props.groups[insert_at]
        item.frame_count  = 1
        item.dynamic      = 4
        item.map_count    = 0
        item.display_name = f"group_{insert_at}"
        for attr in ("path0", "path1", "path2", "path3"):
            setattr(item, attr, "")
        for i, attr in enumerate(("type0", "type1", "type2", "type3")):
            setattr(item, attr, 1)
            _sync_type_ui(item, i)

        props.group_index = insert_at
        self.report({"INFO"}, T("uvs.group_added").format(insert_at))
        return {"FINISHED"}


class EFX_OT_uvs_group_remove(Operator):
    """删除当前选中的 UVS Group"""

    bl_idname  = "efx.uvs_group_remove"
    bl_label   = "Remove UVS Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not _is_uvsequence_attribute(obj):
            return False
        props = getattr(obj, "efx_uvs", None)
        return (
            props is not None
            and props.is_loaded
            and len(props.groups) > 0
        )

    def execute(self, context):
        from ..efx_format.uvs import UVSFile

        props = context.active_object.efx_uvs
        idx   = props.group_index
        if not (0 <= idx < len(props.groups)):
            self.report({"ERROR"}, T("uvs.invalid_group_index"))
            return {"CANCELLED"}

        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
        except Exception as e:
            self.report({"ERROR"}, T("uvs.parse_failed").format(e))
            return {"CANCELLED"}

        uvs.groups.pop(idx)
        props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
        _frame_cache.clear()
        _tag_redraw_editor()

        props.groups.remove(idx)
        props.group_index = max(0, idx - 1)
        self.report({"INFO"}, T("uvs.group_removed").format(idx))
        return {"FINISHED"}


class EFX_OT_uvs_group_move(Operator):
    """将当前选中 Group 上移/下移一位（调整 Group 在文件中的顺序）"""

    bl_idname  = "efx.uvs_group_move"
    bl_label   = "Move UVS Group"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
        default='UP',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not _is_uvsequence_attribute(obj):
            return False
        props = getattr(obj, "efx_uvs", None)
        return props is not None and props.is_loaded and len(props.groups) > 1

    def execute(self, context):
        from ..efx_format.uvs import UVSFile

        props = context.active_object.efx_uvs
        idx = props.group_index
        target = idx - 1 if self.direction == 'UP' else idx + 1
        if not (0 <= target < len(props.groups)):
            self.report({"INFO"}, T("uvs.at_boundary"))
            return {"CANCELLED"}

        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
        except Exception as e:
            self.report({"ERROR"}, T("uvs.parse_failed").format(e))
            return {"CANCELLED"}

        uvs.groups[idx], uvs.groups[target] = uvs.groups[target], uvs.groups[idx]
        props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")
        _frame_cache.clear()
        _tag_redraw_editor()

        props.groups.move(idx, target)
        props.group_index = target
        self.report({"INFO"}, T("uvs.group_moved").format(target))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Path slot 增删操作符（Group 内 path0-3 的有效槽数 map_count）
#
# 格式约束（efx_format/uvs.py _serialize）：map indices 数组只在该 Group
# frameCount != 0 时才实际写出字节；frameCount==0 却 map_count>0 会导致
# dataOffset 指向没有数据的位置，产生结构性损坏。因此新增槽位要求该 Group
# 已有帧数据（先用"帧生成"或导入带帧的 Group）。
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_uvs_slot_add(Operator):
    """在当前选中 Group 末尾追加一个 path slot（最多 4 个）"""

    bl_idname  = "efx.uvs_slot_add"
    bl_label   = "Add Path Slot"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not _is_uvsequence_attribute(obj):
            return False
        props = getattr(obj, "efx_uvs", None)
        if props is None or not props.is_loaded:
            return False
        idx = props.group_index
        if not (0 <= idx < len(props.groups)):
            return False
        g = props.groups[idx]
        if g.map_count >= 4:
            return False
        if g.frame_count <= 0:
            try:
                cls.poll_message_set(T("uvs.slot_needs_frames"))
            except Exception:
                pass
            return False
        return True

    def execute(self, context):
        props = context.active_object.efx_uvs
        g = props.groups[props.group_index]
        i = g.map_count
        setattr(g, f"path{i}", "")
        setattr(g, f"type{i}", 1)
        _sync_type_ui(g, i)
        g.map_count = i + 1
        self.report({"INFO"}, T("uvs.slot_added").format(i))
        return {"FINISHED"}


class EFX_OT_uvs_slot_remove(Operator):
    """删除当前选中 Group 的最后一个 path slot"""

    bl_idname  = "efx.uvs_slot_remove"
    bl_label   = "Remove Path Slot"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not _is_uvsequence_attribute(obj):
            return False
        props = getattr(obj, "efx_uvs", None)
        if props is None or not props.is_loaded:
            return False
        idx = props.group_index
        if not (0 <= idx < len(props.groups)):
            return False
        return props.groups[idx].map_count > 0

    def execute(self, context):
        props = context.active_object.efx_uvs
        g = props.groups[props.group_index]
        i = g.map_count - 1
        setattr(g, f"path{i}", "")
        setattr(g, f"type{i}", 1)
        _sync_type_ui(g, i)
        g.map_count = i
        self.report({"INFO"}, T("uvs.slot_removed").format(i))
        return {"FINISHED"}


# =============================================================================
# Phase 4 — GIF → PNG 精灵表生成
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 填充 _CLASSES_P3（在所有 P3 类定义完成后）
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES_P3.extend([
    EFX_OT_uvs_group_add,
    EFX_OT_uvs_group_remove,
    EFX_OT_uvs_group_move,
    EFX_OT_uvs_slot_add,
    EFX_OT_uvs_slot_remove,
    EFX_OT_uvs_edit,
    EFX_OT_uvs_close_editor,
    EFX_OT_uvs_gen_frames,
    EFX_OT_uvs_frame_edit,
    EFX_OT_uvs_frame_insert,
    EFX_OT_uvs_frame_delete,
    EFX_OT_uvs_frame_move,
    EFX_PT_uvs_editor,
])


def _check_pillow() -> bool:
    """检测 Pillow 是否可用（import 失败 = 未安装）。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def _next_pow2(v: int) -> int:
    """向上取整到 2 的幂（MHW 贴图要求边长为 2^n）。"""
    p = 1
    while p < v:
        p *= 2
    return p


def _pick_pot_layout(n: int, fw: int, fh: int, cols: int = None, rows: int = None):
    """计算精灵表行列数 + POT 画布尺寸。

    帧不缩放，按原始像素尺寸 fw×fh 紧密左上对齐贴入格子（步长就是 fw/fh，
    不强制 cols/rows 是 2 的幂）；网格末尾多余格子和画布补齐到 2 的幂产生的
    边缘留白均为透明。

    注意：这里算出的 cols/rows 不是"整张画布被均匀切成 cols×rows 份"的意思
    （画布通常比 fw*cols/fh*rows 略大，多出来的留白只在最右/最下）。因此每帧
    的 UV 矩形不能用 _gen_frames_grid 那种 w=1/cols 的均匀网格公式反推
    ——必须用 _gen_frames_pixel_grid 按每帧真实像素位置直接换算，否则从第
    二列/行起就会跟实际贴的像素错位（byte-perfect 这类问题测不出，只在游戏
    里贴图错位才会发现）。

    cols/rows 均给定时：沿用用户指定的行列，只把画布取整到 POT。
    否则：遍历 cols=1..n（rows=ceil(n/cols)），取 POT 画布面积最小的一组；
    面积打平时优先更接近正方形的（|log2(w)-log2(h)| 更小）。
    """
    import math

    if cols and rows:
        cols, rows = max(1, cols), max(1, rows)
        canvas_w, canvas_h = _next_pow2(fw * cols), _next_pow2(fh * rows)
        return cols, rows, canvas_w, canvas_h

    best = None
    for c in range(1, n + 1):
        r = math.ceil(n / c)
        w, h = _next_pow2(fw * c), _next_pow2(fh * r)
        area = w * h
        squareness = abs(math.log2(w) - math.log2(h))
        key = (area, squareness)
        if best is None or key < best[0]:
            best = (key, c, r, w, h)

    _, cols, rows, canvas_w, canvas_h = best
    return cols, rows, canvas_w, canvas_h


def _gen_frames_pixel_grid(n: int, cols: int, fw: int, fh: int, canvas_w: int, canvas_h: int):
    """按每帧真实像素位置直接生成 UVSFrame 列表（左→右、上→下播放顺序）。

    跟 _gen_frames_grid 的区别：那个假设整张画布被 cols×rows 均匀切分
    （w=1/cols），只在"画布≈fw*cols 无需补齐"时才准；这里改成直接拿
    帧在画布里的真实像素矩形换算 UV 分数，哪怕画布因取整到 2 的幂而带了
    尾部留白也不会累积错位——因为 GIF→PNG 生成的精灵表本来就不是均匀
    网格（每帧固定 fw×fh，只有画布最右/最下有一圈留白）。

    v 轴方向：实机截图确认过——按"第 j 行（0 起，从顶往下数）对应 v 从
    1-(j+1)*fh/canvas_h 到 1-j*fh/canvas_h"（沿用 _gen_frames_grid"v 越大越
    靠近贴图顶部"的约定）算出来，UVS 编辑器预览里第 0 帧却显示在左下角，
    和 PNG 里实际贴在左上角的内容对不上，所以这里改成反过来的直接映射
    （j 越大 v 越大）。⚠ 这只是照编辑器预览校准的，游戏里贴图 v 轴到底是
    以左上还是左下为原点还没有实机验证过；如果之后验证结果相反，把这里
    的 v0/v1 换回上面那版即可。
    """
    from ..efx_format.uvs import UVSFrame
    frames = []
    for k in range(n):
        ci, j = k % cols, k // cols
        u0, u1 = ci * fw / canvas_w, (ci + 1) * fw / canvas_w
        v0, v1 = j * fh / canvas_h, (j + 1) * fh / canvas_h
        frames.append(UVSFrame(uv0=(u0, v0), uv1=(u1, v1)))
    return frames


class EFX_OT_uvs_gif_to_png(Operator, ImportHelper):
    """将 GIF 动图拆帧并拼合为 PNG 精灵表，可选自动更新当前 Group 帧数据"""

    bl_idname  = "efx.uvs_gif_to_png"
    bl_label   = "GIF to PNG Sprite Sheet"
    bl_options = {"REGISTER"}

    filter_glob: StringProperty(default="*.gif", options={"HIDDEN"})

    auto_layout: bpy.props.BoolProperty(
        name="Auto Layout",
        description="Automatically search for a row/column layout that minimizes the power-of-2 padded canvas area",
        default=True,
    )
    cols: IntProperty(name="Columns (H)", min=1, default=1,
                      description="Sprite sheet column count (used when Auto Layout is off; "
                                  "final canvas is rounded up to a power of 2)")
    rows: IntProperty(name="Rows (V)", min=1, default=1,
                      description="Sprite sheet row count (used when Auto Layout is off; "
                                  "final canvas is rounded up to a power of 2)")
    create_new_group: bpy.props.BoolProperty(
        name="Create Matching Group",
        description="After generating, insert a new group into the current UVS whose grid/frame count/path "
                    "exactly match the generated PNG (the PNG has power-of-2 padding; a dedicated grid avoids "
                    "mismatching the UVS editor's own Generate Frames parameters)",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        if not _check_pillow():
            try:
                cls.poll_message_set(T("uvs.need_pillow_msg"))
            except Exception:
                pass
            return False
        obj = context.active_object
        return (
            _is_uvsequence_attribute(obj)
            and getattr(getattr(obj, "efx_uvs", None), "is_loaded", False)
        )

    def invoke(self, context, event):
        # 预填行列数：从当前 group 的 grid_h/grid_v
        obj = context.active_object
        props = obj.efx_uvs
        idx = props.group_index
        if 0 <= idx < len(props.groups):
            g = props.groups[idx]
            self.cols = g.grid_h
            self.rows = g.grid_v
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_layout")
        row = layout.row(align=True)
        row.enabled = not self.auto_layout
        row.prop(self, "cols")
        row.prop(self, "rows")

        info = self._preview_layout()
        if info:
            cols, rows, n, canvas_w, canvas_h = info
            layout.label(text=T("uvs.gif_preview_line").format(n, cols, rows, canvas_w, canvas_h), icon="INFO")

        layout.separator()
        layout.prop(self, "create_new_group")

    def _preview_layout(self):
        """在文件浏览侧栏里预览最终行列/画布尺寸；文件未选定或读取失败时返回 None。"""
        path = self.filepath
        if not path or not os.path.isfile(path) or not path.lower().endswith(".gif"):
            return None
        try:
            from PIL import Image
            gif = Image.open(path)
            fw, fh = gif.size
            n = getattr(gif, "n_frames", 1)
        except Exception:
            return None

        if self.auto_layout:
            cols, rows, canvas_w, canvas_h = _pick_pot_layout(n, fw, fh)
        else:
            cols, rows, canvas_w, canvas_h = _pick_pot_layout(n, fw, fh, self.cols, self.rows)
        return cols, rows, n, canvas_w, canvas_h

    def execute(self, context):
        try:
            from PIL import Image
        except ImportError:
            self.report({"ERROR"}, T("uvs.pillow_not_installed"))
            return {"CANCELLED"}

        gif_path = self.filepath
        if not os.path.isfile(gif_path):
            self.report({"ERROR"}, T("uvs.file_not_found").format(gif_path))
            return {"CANCELLED"}

        # ── 读取所有 GIF 帧 ──────────────────────────────────────────────────
        try:
            gif = Image.open(gif_path)
            raw_frames = []
            while True:
                raw_frames.append(gif.copy().convert("RGBA"))
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass
        except Exception as e:
            self.report({"ERROR"}, T("uvs.gif_read_failed").format(e))
            return {"CANCELLED"}

        if not raw_frames:
            self.report({"ERROR"}, T("uvs.gif_no_frames"))
            return {"CANCELLED"}

        n = len(raw_frames)
        fw, fh = raw_frames[0].size

        # ── 计算行列数 + POT 画布尺寸 ───────────────────────────────────────
        if self.auto_layout:
            cols, rows, canvas_w, canvas_h = _pick_pot_layout(n, fw, fh)
        else:
            cols, rows, canvas_w, canvas_h = _pick_pot_layout(n, fw, fh, self.cols, self.rows)

        # ── 拼接精灵表（帧不缩放，按原始尺寸左上对齐；网格末尾与 POT 补齐的
        #    留白透明）。帧的 UV 矩形不在这里算，见下面 _insert_group 用
        #    _gen_frames_pixel_grid 按真实像素位置直接生成 ───────────────────
        sprite = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        for i, frame in enumerate(raw_frames):
            if i >= cols * rows:
                break
            sprite.paste(frame, ((i % cols) * fw, (i // cols) * fh))

        # ── 保存 PNG ─────────────────────────────────────────────────────────
        out_path = os.path.splitext(gif_path)[0] + ".png"
        try:
            sprite.save(out_path)
        except Exception as e:
            self.report({"ERROR"}, T("uvs.png_save_failed").format(e))
            return {"CANCELLED"}

        msg = T("uvs.gif_saved").format(out_path, n, cols, rows, canvas_w, canvas_h)

        # ── 新增对应 Group ───────────────────────────────────────────────────
        if self.create_new_group:
            obj = context.active_object
            props = obj.efx_uvs
            insert_at, err = self._insert_group(props, out_path, cols, rows, n, fw, fh, canvas_w, canvas_h)
            if err:
                self.report({"WARNING"}, msg + T("uvs.new_group_failed").format(err))
                return {"FINISHED"}
            msg += T("uvs.new_group_created").format(insert_at)

        self.report({"INFO"}, msg)
        return {"FINISHED"}

    def _insert_group(self, props, out_path: str, cols: int, rows: int, n: int,
                       fw: int, fh: int, canvas_w: int, canvas_h: int):
        """在当前 Group 之后插入一个新 Group，网格/帧数/路径与生成的精灵表完全对应。

        插入手法同 EFX_OT_uvs_group_add：raw UVSFile 和 CollectionProperty 必须
        同步插入到相同位置——导出时 _rebuild_uvs 按下标 zip 两者，位置对不上会错位/丢组。
        返回 (insert_at, error_message)，成功时 error_message 为 None。
        """
        from ..efx_format.uvs import UVSFile, UVSGroup

        try:
            data = base64.b64decode(props.raw_b64)
            uvs  = UVSFile.parse(data)
        except Exception as e:
            return None, str(e)

        insert_at = props.group_index + 1
        # 按真实像素位置生成 UV 矩形（不能用 _gen_frames_grid 的均匀网格公式，
        # 见 _gen_frames_pixel_grid 文档串——画布右/下常带 POT 补齐留白，不是
        # 均匀 cols×rows 切分）。
        new_frames = _gen_frames_pixel_grid(n, cols, fw, fh, canvas_w, canvas_h)
        # map_count=0：真正的路径槽（path_indices）要到 Export 时才由 _rebuild_uvs
        # 依据 props.groups 的 path0/type0 重建字符串表并回填，这里先留空同
        # EFX_OT_uvs_group_add 的约定，避免 raw 里出现指向不存在字符串的假索引。
        new_g = UVSGroup(
            frames=new_frames,
            path_indices=[],
            map_count=0,
            dynamic=4,
        )
        new_g._frame_indices = list(range(len(new_frames)))
        uvs.groups.insert(insert_at, new_g)
        props.raw_b64 = base64.b64encode(uvs.serialize()).decode("ascii")

        # CollectionProperty 同位置插入（同 EFX_OT_uvs_group_add：无 insert，只能追加后逐格前移）
        props.groups.add()
        for i in range(len(props.groups) - 1, insert_at, -1):
            props.groups.move(i - 1, i)
        item = props.groups[insert_at]
        item.display_name = os.path.splitext(os.path.basename(out_path))[0]
        item.dynamic       = 4
        item.map_count     = 1
        item.path0         = out_path  # 文件系统路径供参考，用户需改为游戏相对路径
        for attr in ("path1", "path2", "path3"):
            setattr(item, attr, "")
        for i, attr in enumerate(("type0", "type1", "type2", "type3")):
            setattr(item, attr, 1)
            _sync_type_ui(item, i)
        item.grid_h          = cols
        item.grid_v          = rows
        item.grid_scan       = 'LR_TB'
        item.gen_frame_count = n
        item.frame_count     = len(new_frames)
        item.frame_index     = 0

        props.group_index = insert_at
        _frame_cache.clear()
        _tag_redraw_editor()
        return insert_at, None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 注册列表
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES_P4.extend([EFX_OT_uvs_gif_to_png])
