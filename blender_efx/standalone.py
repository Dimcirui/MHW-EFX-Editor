"""管理不隶属 EFX 文件树的独立 TIML 与 UVS 编辑载体。

维护约束：独立对象放在普通集合，绝不能拥有 EFX_ROOT 标记或根指针；它们不属于
任何 EFX 段，因此导出和校验收集路径必须忽略。
"""

import bpy

from .i18n import T


SCRATCH_NAME = "EFX Standalone"

# EFX_TIML 通过无 parent 与附属 TIML 句柄区分。
TYPE_TIML = "EFX_TIML"
TYPE_UVS = "EFX_UVS"


# ─────────────────────────────────────────────────────────────────────────────
# 存放集合
# ─────────────────────────────────────────────────────────────────────────────

def scratch_collection(context=None):
    """取得独立载体集合并挂入场景；该集合不得成为 EFX_ROOT。"""
    ctx = context or bpy.context
    col = bpy.data.collections.get(SCRATCH_NAME)
    if col is None:
        col = bpy.data.collections.new(SCRATCH_NAME)
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
    """新建自身承载 TIML 字节的无主句柄。"""
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
            # TIML 句柄须由其专用路径删除，以同时回收持久 Action。
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
        col = bpy.data.collections.get(SCRATCH_NAME)
        if col is not None and not col.objects and not col.children:
            try:
                bpy.data.collections.remove(col)
            except Exception:
                pass
        self.report({"INFO"}, "Closed %s" % name)
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
def draw_standalone_header(layout, obj) -> bool:
    """为无主载体绘制状态和关闭按钮；有宿主时返回 False。"""
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
