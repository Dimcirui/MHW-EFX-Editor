"""
blender_epv/efx_link.py — EPV ↔ EFX 联动（L1 导航 + L2 路径选择器）。

约束：EFX 导入只保留文件名（basename），不存原始游戏路径，故 epv 路径
（含 vfx\\efx\\... 前缀）与已导入 efx 只能按**文件名干(stem)**匹配。

L1：record 路径 stem → 找同名 efx 根集合 → 选中激活（跳转）。
L2：路径仍是可编辑字符串（保 byte-perfect）；提供匹配指示 + 从已导入 efx 拾取
    （替换文件名部分、保留目录前缀）。

不触及序列化，零 byte-perfect 风险。
"""
import bpy
from bpy.props import IntProperty, EnumProperty

from ..blender_efx import root_collection as _rc


# ─────────────────────────────────────────────────────────────────────────────
# 匹配工具
# ─────────────────────────────────────────────────────────────────────────────

def _efx_roots():
    """返回场景中所有 EFX：[(stem, root_col), ...]（root_col 本身即 ~TYPE==EFX_ROOT 集合）。"""
    out = []
    for col in _rc.all_root_collections():
        name = col.name
        stem = name[:-4] if name.lower().endswith(".efx") else name
        out.append((stem, col))
    return out


def _path_stem(path):
    """取 epv 路径的文件名干（无扩展名；epv 用反斜杠）。"""
    p = str(path).replace("/", "\\")
    return p.rsplit("\\", 1)[-1]


def find_efx_for_path(path):
    """按 stem 找匹配的 efx 根集合；找不到返回 None。"""
    if not path:
        return None
    stem = _path_stem(path)
    for s, root in _efx_roots():
        if s == stem:
            return root
    return None


def _find_layer_collection(view_layer, target_col):
    """在 view_layer 的图层集合树里找 target_col 对应的 LayerCollection（递归）。"""
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

        # ROOT 是集合（2026-07 起不再是 Empty 对象），没有"选中它"这个概念——
        # 改把它设为大纲的活动集合（触发 EFX Root/Direct Trigger 等 N 面板），
        # 并额外选中/激活它下面的第一个 entry（保证视口里有可见的落点）。
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

# 动态 EnumProperty 的 items 需常驻引用，防 GC 导致条目失效（见项目记忆 enum-callback-gc-trap）
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
            new_path = cur.rsplit("\\", 1)[0] + "\\" + stem   # 保留目录前缀
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
