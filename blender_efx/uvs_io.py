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


def _is_uvsequence_block(obj) -> bool:
    """该对象是否为 UVSEQUENCE 类型的 EFX_BLOCK。"""
    if obj is None or obj.get("~TYPE") != "EFX_BLOCK":
        return False
    try:
        from ..efx_format.hashes import UVSEQUENCE
        return int(obj.efx_block.type_hash_str) == UVSEQUENCE
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup：单个 Group 的可编辑字段
# ─────────────────────────────────────────────────────────────────────────────

class EFXUVSGroupProp(PropertyGroup):
    """UVS Group 的可编辑元数据（路径槽 + 类型 + dynamic + 帧生成参数）。"""

    display_name: StringProperty(
        name="Name",
        description="显示名称（第一条路径的末段文件名）",
    )
    frame_count: IntProperty(name="Frames", min=0)
    dynamic: IntProperty(name="Dynamic", min=0)
    map_count: IntProperty(name="Path Count", min=0, max=4)

    path0: StringProperty(name="Path 0")
    path1: StringProperty(name="Path 1")
    path2: StringProperty(name="Path 2")
    path3: StringProperty(name="Path 3")

    type0: IntProperty(name="Type 0", min=0, default=1)
    type1: IntProperty(name="Type 1", min=0, default=1)
    type2: IntProperty(name="Type 2", min=0, default=1)
    type3: IntProperty(name="Type 3", min=0, default=1)

    # Phase 3：帧生成参数
    grid_h: IntProperty(name="H", min=1, default=1,
                        description="精灵表水平格数")
    grid_v: IntProperty(name="V", min=1, default=1,
                        description="精灵表垂直格数")
    grid_scan: bpy.props.EnumProperty(
        name="Scan",
        items=[
            ('LR_TB', "LR↓", "左→右 上→下（最常用）"),
            ('LR_BT', "LR↑", "左→右 下→上（UV 标准序）"),
            ('TB_LR', "TB→", "上→下 左→右"),
            ('BT_LR', "BT→", "下→上 左→右"),
        ],
        default='LR_TB',
    )
    # 当前选中帧（用于预览高亮）
    frame_index: IntProperty(name="Frame", min=0, default=0)


# ─────────────────────────────────────────────────────────────────────────────
# PropertyGroup：整个 UVS 文件
# ─────────────────────────────────────────────────────────────────────────────

class EFXUVSProps(PropertyGroup):
    """UVS Edition 数据存储（挂到 Object）。"""

    filepath: StringProperty(
        name="UVS File",
        description="磁盘上的 .uvs 文件路径",
        subtype="FILE_PATH",
    )
    is_loaded: BoolProperty(name="Loaded", default=False)

    # 完整序列化字节 base64，用于 frame data 等不可编辑字段的往返
    raw_b64: StringProperty(name="Raw Bytes (base64)", default="")

    groups: CollectionProperty(type=EFXUVSGroupProp)
    group_index: IntProperty(name="Group Index", default=0)

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
        return _is_uvsequence_block(context.active_object)

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_uvs
        path = self.filepath
        try:
            with open(path, "rb") as f:
                data = f.read()
            _populate_props(props, data)
            props.filepath = path
            self.report({"INFO"}, f"已导入：{os.path.basename(path)}（{len(props.groups)} groups）")
        except Exception as e:
            self.report({"ERROR"}, f"导入失败：{e}")
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
        return _is_uvsequence_block(obj) and getattr(
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
            self.report({"INFO"}, f"已导出：{os.path.basename(self.filepath)}")
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
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
        return (_is_uvsequence_block(obj) and props is not None
                and bool(props.filepath) and os.path.isfile(props.filepath))

    def execute(self, context):
        obj = context.active_object
        props = obj.efx_uvs
        try:
            with open(props.filepath, "rb") as f:
                data = f.read()
            _populate_props(props, data)
            self.report({"INFO"}, "已重新加载")
        except Exception as e:
            self.report({"ERROR"}, f"重载失败：{e}")
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
        row.label(text=item.display_name)
        row.label(text=f"{item.frame_count}f")


# ─────────────────────────────────────────────────────────────────────────────
# Panel：UVS Edition（挂在 EFX_PT_block_fields 下）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_uvs_edition(Panel):
    """UVS Edition — 仅在选中 UVSEQUENCE 块时显示"""

    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "EFX"
    bl_label       = "UVS Edition"
    bl_parent_id   = "EFX_PT_block_fields"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _is_uvsequence_block(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object
        props  = obj.efx_uvs

        # ── UVS 游戏路径（只读显示，来自块字段）──────────────────────────────
        game_path = _get_uvsequence_path(obj)
        if game_path:
            box = layout.box()
            row = box.row()
            row.label(text="Game path:", icon="FILE")
            row.label(text=game_path)

        # ── Import / Export / Reload ──────────────────────────────────────────
        row = layout.row(align=True)
        row.operator("efx.uvs_import", icon="IMPORT", text="Import")
        if props.is_loaded:
            row.operator("efx.uvs_export", icon="EXPORT", text="Export")
            row.operator("efx.uvs_reload", icon="FILE_REFRESH", text="")

        # ── GIF → PNG 精灵表（Phase 4，独立于 UVS 是否已加载）──────────────────
        box = layout.box()
        box.label(text="GIF → PNG 精灵表", icon="IMAGE_DATA")
        if _check_pillow():
            box.operator("efx.uvs_gif_to_png", icon="RENDER_ANIMATION")
        else:
            box.label(text="需要 Pillow 库", icon="ERROR")
            box.label(text="（Blender Python 里执行 pip install Pillow）")

        if not props.is_loaded:
            layout.label(text="未加载 UVS 文件", icon="INFO")
            return

        # ── Group 列表 ────────────────────────────────────────────────────────
        layout.label(text=f"Groups: {len(props.groups)}", icon="SEQUENCE")
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
            box.label(text=f"Group {idx} — {g.display_name}", icon="LAYER_ACTIVE")

            row = box.row()
            row.prop(g, "dynamic")
            row.label(text=f"{g.frame_count} frames")

            box.separator(factor=0.5)
            box.label(text="Path slots:", icon="IMAGE_DATA")

            _TYPE_NAMES = {1: "Diffuse", 2: "Normal", 3: "Specular"}
            for i in range(4):
                path_attr = f"path{i}"
                type_attr = f"type{i}"
                path_val  = getattr(g, path_attr)
                type_val  = getattr(g, type_attr)
                type_name = _TYPE_NAMES.get(type_val, str(type_val))

                row = box.row(align=True)
                row.label(text=f"{i+1}", icon="BLANK1")
                if i < g.map_count:
                    sub = row.row(align=True)
                    sub.prop(g, path_attr, text="")
                    sub.label(text=type_name)
                    sub.prop(g, type_attr, text="")
                else:
                    row.label(text="（空槽）", icon="BLANK1")

        layout.separator(factor=0.5)

        # ── Edit UVS 弹窗 ─────────────────────────────────────────────────────
        if _edit_state["window"] is not None:
            layout.operator("efx.uvs_close_editor", text="关闭编辑器", icon="X")
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

def _gen_frames_grid(H: int, V: int, scan: str):
    """按 H×V 网格和扫描方向生成 UVSFrame 列表。"""
    from ..efx_format.uvs import UVSFrame
    w, h = 1.0 / H, 1.0 / V

    if scan == 'LR_TB':    # 左→右 上→下（视觉顺序，v 从 V-1 降到 0）
        pairs = [(i, V - 1 - j) for j in range(V) for i in range(H)]
    elif scan == 'LR_BT':  # 左→右 下→上（UV 标准序）
        pairs = [(i, j) for j in range(V) for i in range(H)]
    elif scan == 'TB_LR':  # 上→下 左→右
        pairs = [(i, V - 1 - j) for i in range(H) for j in range(V)]
    else:                  # BT_LR：下→上 左→右
        pairs = [(i, j) for i in range(H) for j in range(V)]

    frames = []
    for ci, ri in pairs:
        u0, v0 = ci * w, ri * h
        u1, v1 = (ci + 1) * w, (ri + 1) * h
        frames.append(UVSFrame(uv0=(u0, v0), uv1=(u1, v1)))
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
        return _is_uvsequence_block(obj) and getattr(
            getattr(obj, "efx_uvs", None), "is_loaded", False
        )

    def invoke(self, context, event):
        # 已有编辑器在跑 → 检测窗口是否仍存在
        if _edit_state["window"] is not None:
            if _edit_state["window"] in context.window_manager.windows[:]:
                self.report({"INFO"}, "UVS 编辑器已打开")
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
            self.report({"ERROR"}, "无效的 Group 序号")
            return {"CANCELLED"}

        g_prop = props.groups[idx]
        H, V, scan = g_prop.grid_h, g_prop.grid_v, g_prop.grid_scan
        new_frames = _gen_frames_grid(H, V, scan)

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
            self.report({"INFO"}, f"已生成 {len(new_frames)} 帧（{H}×{V}，{scan}）")
        except Exception as e:
            self.report({"ERROR"}, f"生成失败：{e}")
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
    bl_label       = "UVS 编辑器"

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
            layout.label(text="找不到编辑目标", icon="ERROR")
            layout.operator("efx.uvs_close_editor", icon="X")
            return
        props = obj.efx_uvs

        # ── 标题 + 关闭 ──────────────────────────────────────────────────────
        row = layout.row()
        row.label(text=obj_name, icon="OBJECT_DATA")
        row.operator("efx.uvs_close_editor", text="", icon="X")

        # ── 参考图 ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="参考图", icon="IMAGE_DATA")
        box.prop_search(props, "ref_image_name", bpy.data, "images", text="")
        row = box.row(align=True)
        row.operator("image.open", text="加载图片", icon="FILE_FOLDER")
        # 把选中图片设到当前 Image Editor
        if props.ref_image_name:
            img = bpy.data.images.get(props.ref_image_name)
            if img and context.space_data:
                if context.space_data.image != img:
                    context.space_data.image = img

        layout.separator(factor=0.3)

        # ── Group 列表 ────────────────────────────────────────────────────────
        layout.label(text=f"Groups  ({len(props.groups)})", icon="SEQUENCE")
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
        box.label(text=f"Group {idx} — {g.display_name}", icon="LAYER_ACTIVE")
        row = box.row()
        row.prop(g, "dynamic")
        row.label(text=f"{g.frame_count} frames")

        box.separator(factor=0.3)
        box.label(text="路径槽", icon="RENDERLAYERS")
        _TYPE_NAMES = {1: "Diffuse", 2: "Normal", 3: "Specular"}
        for i in range(4):
            path_attr = f"path{i}"
            type_attr = f"type{i}"
            row = box.row(align=True)
            row.label(text=f"{i+1}")
            if i < g.map_count:
                row.prop(g, path_attr, text="")
                row.prop(g, type_attr, text="")
            else:
                row.label(text="（空槽）")

        layout.separator(factor=0.3)

        # ── 帧生成 ────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text="帧生成", icon="RENDER_ANIMATION")
        row = box.row(align=True)
        row.prop(g, "grid_h", text="H")
        row.prop(g, "grid_v", text="V")
        box.prop(g, "grid_scan", text="扫描")
        sub = box.row()
        sub.scale_y = 1.2
        sub.operator("efx.uvs_gen_frames", icon="PLAY")

        layout.separator(factor=0.3)

        # ── 帧导航（高亮选中帧） ──────────────────────────────────────────────
        box = layout.box()
        box.label(text="帧预览", icon="KEYFRAME")
        row = box.row(align=True)
        row.prop(g, "frame_index", text="帧")
        row.label(text=f"/ {g.frame_count}")

        # 显示选中帧的 UV 坐标
        frames = _get_frames_for_group(props.raw_b64, idx)
        fi = max(0, min(g.frame_index, len(frames) - 1)) if frames else 0
        if frames:
            f = frames[fi]
            col = box.column(align=True)
            col.label(text=f"UV0: ({f.uv0[0]:.3f}, {f.uv0[1]:.3f})")
            col.label(text=f"UV1: ({f.uv1[0]:.3f}, {f.uv1[1]:.3f})")

        layout.separator(factor=0.3)

        # ── 保存 ─────────────────────────────────────────────────────────────
        row = layout.row()
        row.scale_y = 1.3
        row.operator("efx.uvs_export", text="保存 UVS", icon="FILE_TICK")


# ─────────────────────────────────────────────────────────────────────────────
# 填充 _CLASSES_P3（在类定义完成后）
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES_P3.extend([
    EFX_OT_uvs_edit,
    EFX_OT_uvs_close_editor,
    EFX_OT_uvs_gen_frames,
    EFX_PT_uvs_editor,
])


# =============================================================================
# Phase 4 — GIF → PNG 精灵表生成
# =============================================================================

def _check_pillow() -> bool:
    """检测 Pillow 是否可用（import 失败 = 未安装）。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


class EFX_OT_uvs_gif_to_png(Operator, ImportHelper):
    """将 GIF 动图拆帧并拼合为 PNG 精灵表，可选自动更新当前 Group 帧数据"""

    bl_idname  = "efx.uvs_gif_to_png"
    bl_label   = "GIF → PNG 精灵表"
    bl_options = {"REGISTER"}

    filter_glob: StringProperty(default="*.gif", options={"HIDDEN"})

    auto_layout: bpy.props.BoolProperty(
        name="自动布局",
        description="根据帧数自动计算行列数（√N 向上取整）",
        default=True,
    )
    cols: IntProperty(name="列数 (H)", min=1, default=1,
                      description="精灵表水平格数（auto_layout=False 时生效）")
    rows: IntProperty(name="行数 (V)", min=1, default=1,
                      description="精灵表垂直格数（auto_layout=False 时生效）")
    apply_to_group: bpy.props.BoolProperty(
        name="应用到当前 Group",
        description="生成后自动更新 UV 帧序列，并将 PNG 路径写入 path0",
        default=False,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        if not _check_pillow():
            try:
                cls.poll_message_set("需要安装 Pillow：在 Blender Python 里执行 pip install Pillow")
            except Exception:
                pass
            return False
        obj = context.active_object
        return (
            _is_uvsequence_block(obj)
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

    def execute(self, context):
        import math
        try:
            from PIL import Image
        except ImportError:
            self.report({"ERROR"}, "Pillow 未安装，无法处理 GIF")
            return {"CANCELLED"}

        gif_path = self.filepath
        if not os.path.isfile(gif_path):
            self.report({"ERROR"}, f"文件不存在：{gif_path}")
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
            self.report({"ERROR"}, f"读取 GIF 失败：{e}")
            return {"CANCELLED"}

        if not raw_frames:
            self.report({"ERROR"}, "GIF 中没有找到帧")
            return {"CANCELLED"}

        n = len(raw_frames)

        # ── 计算行列数 ───────────────────────────────────────────────────────
        if self.auto_layout:
            cols = math.ceil(math.sqrt(n))
            rows = math.ceil(n / cols)
        else:
            cols, rows = max(1, self.cols), max(1, self.rows)

        # ── 拼接精灵表 ───────────────────────────────────────────────────────
        fw, fh = raw_frames[0].size
        sprite = Image.new("RGBA", (fw * cols, fh * rows), (0, 0, 0, 0))
        for i, frame in enumerate(raw_frames):
            if i >= cols * rows:
                break
            sprite.paste(frame, ((i % cols) * fw, (i // cols) * fh))

        # ── 保存 PNG ─────────────────────────────────────────────────────────
        out_path = os.path.splitext(gif_path)[0] + ".png"
        try:
            sprite.save(out_path)
        except Exception as e:
            self.report({"ERROR"}, f"保存 PNG 失败：{e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已保存：{out_path}（{n} 帧，{cols}×{rows}）")

        # ── 应用到当前 Group ─────────────────────────────────────────────────
        if self.apply_to_group:
            obj = context.active_object
            props = obj.efx_uvs
            idx = props.group_index
            if 0 <= idx < len(props.groups):
                g = props.groups[idx]
                g.grid_h   = cols
                g.grid_v   = rows
                g.grid_scan = 'LR_TB'
                # path0：填入文件系统路径供参考，用户需改为游戏相对路径
                if g.map_count == 0:
                    g.map_count = 1
                g.path0 = out_path
                # 直接重用生成逻辑（不走 operator，避免 wm.efx_uvs_edit_obj 依赖）
                new_frames = _gen_frames_grid(cols, rows, 'LR_TB')
                try:
                    from ..efx_format.uvs import UVSFile
                    data = base64.b64decode(props.raw_b64)
                    uvs  = UVSFile.parse(data)
                    ug   = uvs.groups[idx]
                    ug.frames         = new_frames
                    ug._frame_indices = list(range(len(new_frames)))
                    props.raw_b64     = base64.b64encode(uvs.serialize()).decode("ascii")
                    g.frame_count     = len(new_frames)
                    g.frame_index     = 0
                    _frame_cache.clear()
                except Exception as e:
                    self.report({"WARNING"}, f"帧数据更新失败：{e}")

        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 注册列表
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES_P4.extend([EFX_OT_uvs_gif_to_png])
