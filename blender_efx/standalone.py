"""
blender_efx/standalone.py  —  无宿主的 TIML / UVS：不依赖任何 .efx 树也能打开编辑

背景
----
TIML 与 UVS 两个编辑器原本只能作为「EFX 属性的附体」进入：TIML 要先选中带 TIML 段的
entry，UVS 要先选中 UVSEQUENCE 属性。但这两种文件本身是独立格式，编辑器也早就只认
「一个承载数据的对象」而不关心它挂在哪：

  - TIML：timl_edit 的 build_persistent_fcurves(handle, body) / sync_fcurves_to_bytes
    里，body 只被当成 timl_bytes 的读写目标（外加取个名字），handle 只被当成 fcurve
    的挂载点——两者是同一个对象也完全成立。
  - UVS：数据全在 obj.efx_uvs 这个挂在 Object 上的 PropertyGroup，宿主是谁无所谓。

于是无主形态就是：**一个带类型标记的空 Empty，自己承载数据**。

  ~TYPE = "EFX_TIML"，parent is None   → 无主 TIML（句柄即载体，timl_bytes 存自己身上）
  ~TYPE = "EFX_UVS"                    → 无主 UVS（数据在自己的 efx_uvs 上）

放哪 / 归谁管
-------------
统一放进场景里一个名为 "EFX Standalone" 的普通集合（惰性创建）。它**不是** EFX_ROOT
文件集合——不带 ~TYPE="EFX_ROOT"，也不带 efx_root_ptr 反向指针。

因此它对 .efx 的导出/校验完全隐形，且是两道独立保险：

  1. 导出与校验的收集入口是 root_collection.collect_top_level(root_col, type_tag)，
     只遍历某个 EFX_ROOT 文件集合下的叶子集合——EFX Standalone 不在任何 root 下。
  2. 全仓库对 bpy.data.objects 的全局扫描一律带 `o.parent == 某个具体对象` 的过滤
     （io_tree / reorder / normalize / validate / delete_ops / entry_action_ref），
     无主对象 parent 是 None，一条都不会命中。

另外 ~TYPE 为 EFX_TIML / EFX_UVS 的对象本来就既非 EFX_ENTRY 也非 EFX_ATTRIBUTE，
按类型过滤的路径本就忽略它们。

约束（CLAUDE.md）：Python 3.10 语法、bpy 稳定子集、包内相对导入。
"""

import bpy

from .i18n import T


SCRATCH_NAME = "EFX Standalone"

# 无主载体的类型标记（EFX_TIML 复用 TIML 句柄的既有标记，靠 parent is None 区分有主/无主）
TYPE_TIML = "EFX_TIML"
TYPE_UVS = "EFX_UVS"


# ─────────────────────────────────────────────────────────────────────────────
# 存放集合
# ─────────────────────────────────────────────────────────────────────────────

def scratch_collection(context=None):
    """取得（必要时创建）存放无主 TIML / UVS 的集合，并确保它挂在场景里。

    ⚠ 刻意不写 ~TYPE / efx_root_ptr：它必须**不是** EFX_ROOT 文件集合，
    否则会被导出目标选择器（operators.py::_export_target_poll）和
    root_collection.all_root_collections() 当成一个 .efx 文件。
    """
    ctx = context or bpy.context
    col = bpy.data.collections.get(SCRATCH_NAME)
    if col is None:
        col = bpy.data.collections.new(SCRATCH_NAME)
        # EFX 文件集合用紫（COLOR_06），这里用绿区分"不是一个 efx 文件"
        try:
            col.color_tag = "COLOR_04"
        except Exception:
            pass
    scene_col = ctx.scene.collection
    if col.name not in {c.name for c in scene_col.children}:
        already_linked = any(col.name in {c.name for c in p.children}
                             for p in bpy.data.collections)
        if not already_linked:
            scene_col.children.link(col)
    return col


def _make_host(name: str, type_tag: str, display: str, context=None):
    """建一个无主载体 Empty，放进 EFX Standalone 集合，选中并设为活动对象。"""
    ctx = context or bpy.context
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = display
    obj.empty_display_size = 0.12
    scratch_collection(ctx).objects.link(obj)
    obj["~TYPE"] = type_tag
    try:
        for o in ctx.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        ctx.view_layer.objects.active = obj
    except Exception:
        pass
    return obj


def new_timl_host(name: str, context=None):
    """新建一个无主 TIML 句柄（自身即数据载体）。调用方随后用
    timl_edit.set_entry_timl(host, data) 写字节——那是所有 timl_bytes 变更的唯一咽喉点。"""
    return _make_host("%s [timl]" % name, TYPE_TIML, "SPHERE", context)


def new_uvs_host(name: str, context=None):
    """新建一个无主 UVS 载体（数据写进它的 obj.efx_uvs）。"""
    return _make_host("%s [uvs]" % name, TYPE_UVS, "PLAIN_AXES", context)


def is_standalone(obj) -> bool:
    """obj 是否为无主 TIML / UVS 载体。"""
    if obj is None:
        return False
    t = obj.get("~TYPE")
    if t == TYPE_UVS:
        return True
    return t == TYPE_TIML and obj.parent is None


# ─────────────────────────────────────────────────────────────────────────────
# 关闭（删除载体对象）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_close_standalone(bpy.types.Operator):
    """关闭当前的无主 TIML / UVS（丢弃未导出的修改）"""

    bl_idname      = "efx.close_standalone"
    bl_label       = "Close Standalone"
    bl_description = "Remove this standalone TIML/UVS from the scene. Unexported edits are discarded"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ok = is_standalone(context.active_object)
        setter = getattr(cls, "poll_message_set", None)
        if not ok and setter is not None:
            setter("Select a standalone TIML/UVS first")
        return ok

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        if not is_standalone(obj):
            return {"CANCELLED"}
        name = obj.name
        if obj.get("~TYPE") == TYPE_TIML:
            # 走 timl_edit 的删除路径：连持久 Action 一起清（fake_user 会挡住自动回收）
            try:
                from . import timl_edit as _te
                _te._delete_timl_handle(obj)
                obj = None
            except Exception:
                obj = context.active_object
        if obj is not None:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                self.report({"ERROR"}, "Failed to remove %s" % name)
                return {"CANCELLED"}
        # 集合空了就一并收掉，别在 Outliner 里留个空壳
        col = bpy.data.collections.get(SCRATCH_NAME)
        if col is not None and not col.objects and not col.children:
            try:
                bpy.data.collections.remove(col)
            except Exception:
                pass
        self.report({"INFO"}, "Closed %s" % name)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板里复用的一行：无主载体的状态 + 关闭按钮
# ─────────────────────────────────────────────────────────────────────────────

def draw_standalone_header(layout, obj) -> bool:
    """无主载体时画一行「独立文件 + 关闭」，返回是否画了。有宿主返回 False 不画。"""
    if not is_standalone(obj):
        return False
    box = layout.box()
    row = box.row(align=True)
    row.label(text=T("standalone.badge"), icon="UNLINKED")
    row.operator("efx.close_standalone", text="", icon="X")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (EFX_OT_close_standalone,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
