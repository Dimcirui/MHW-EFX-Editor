"""按文件名匹配 EPV 记录路径与已导入的 EFX，提供跳转与路径填写。

EFX 导入后只保留文件名，不保留原始游戏路径，因此匹配只能按路径末段进行。
路径槽始终是可编辑字符串，填写时只替换其文件名部分并保留目录前缀。
"""
import bpy
from bpy.props import IntProperty, EnumProperty

from ..blender_efx import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 匹配工具
# ─────────────────────────────────────────────────────────────────────────────

def _efx_roots():
    """返回场景中全部 EFX 根集合及其去扩展名的名称。"""
    out = []
    for col in _rc.all_root_collections():
        name = col.name
        stem = name[:-4] if name.lower().endswith(".efx") else name
        out.append((stem, col))
    return out


def _path_stem(path):
    """取路径的最后一段；EPV 路径使用反斜杠分隔。"""
    p = str(path).replace("/", "\\")
    return p.rsplit("\\", 1)[-1]


def find_efx_for_path(path):
    """按文件名匹配 EFX 根集合；无匹配返回 None。"""
    if not path:
        return None
    stem = _path_stem(path)
    for s, root in _efx_roots():
        if s == stem:
            return root
    return None


def _find_layer_collection(view_layer, target_col):
    """在 view_layer 的集合树中查找 target_col 对应的 LayerCollection。"""
    def _walk(lc):
        if lc.collection is target_col:
            return lc
        for child in lc.children:
            found = _walk(child)
            if found is not None:
                return found
        return None
    return _walk(view_layer.layer_collection)


# ─────────────────────────────────────────────────────────────────────────────
# L1：跳转到 EFX
# ─────────────────────────────────────────────────────────────────────────────

class EPV_OT_jump_to_efx(bpy.types.Operator):
    """选中并激活当前 record 路径所指向的、已导入的 EFX 根对象"""

    bl_idname = "epv.jump_to_efx"
    bl_label = "Jump to EFX"
    bl_description = "Select the imported EFX that this record's path points to (matched by file name)"
    bl_options = {"REGISTER"}

    slot: IntProperty(default=0)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EPV_RECORD":
            return {"CANCELLED"}
        path = getattr(obj.epv_record, "path%d" % self.slot, "")
        root = find_efx_for_path(path)
        if root is None:
            self.report({"WARNING"}, f"No imported EFX matches '{path}'")
            return {"CANCELLED"}

        # EFX 根是集合而非对象，只能设为活动集合；另选中其下首个 Entry 作为视口落点。
        lc = _find_layer_collection(context.view_layer, root)
        if lc is not None:
            context.view_layer.active_layer_collection = lc

        for o in context.selected_objects:
            o.select_set(False)
        entries = _rc.collect_top_level(root, "EFX_ENTRY")
        if entries:
            entries[0].select_set(True)
            context.view_layer.objects.active = entries[0]

        self.report({"INFO"}, f"Jumped to EFX: {root.name}")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# L2：从已导入 EFX 拾取路径
# ─────────────────────────────────────────────────────────────────────────────

# 动态 items 必须由常驻引用持有，否则枚举条目会在回调返回后失效。
_EFX_ENUM_CACHE = []


def _efx_enum_items(self, context):
    global _EFX_ENUM_CACHE
    roots = _efx_roots()
    if roots:
        _EFX_ENUM_CACHE = [(s, s, "") for s, _c in roots]
    else:
        _EFX_ENUM_CACHE = [("", "(no imported EFX)", "")]
    return _EFX_ENUM_CACHE


class EPV_OT_pick_efx_path(bpy.types.Operator):
    """从已导入的 EFX 中选一个，替换当前路径槽的文件名（保留目录前缀）"""

    bl_idname = "epv.pick_efx_path"
    bl_label = "Pick Imported EFX"
    bl_description = "Replace this path slot's file name with an imported EFX (directory prefix kept)"
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty(default=0)
    choice: EnumProperty(name="EFX", items=_efx_enum_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "choice")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("~TYPE") != "EPV_RECORD":
            return {"CANCELLED"}
        stem = self.choice
        if not stem:
            self.report({"WARNING"}, "No imported EFX to pick")
            return {"CANCELLED"}

        key = "path%d" % self.slot
        cur = str(getattr(obj.epv_record, key, "")).replace("/", "\\")
        if "\\" in cur:
            new_path = cur.rsplit("\\", 1)[0] + "\\" + stem
        else:
            new_path = stem
        setattr(obj.epv_record, key, new_path)
        self.report({"INFO"}, f"Path {self.slot} set: {new_path}")
        return {"FINISHED"}


_CLASSES = (EPV_OT_jump_to_efx, EPV_OT_pick_efx_path)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
