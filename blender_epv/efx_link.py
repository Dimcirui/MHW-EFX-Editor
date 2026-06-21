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


# ─────────────────────────────────────────────────────────────────────────────
# 匹配工具
# ─────────────────────────────────────────────────────────────────────────────

def _efx_roots():
    """返回场景中所有 EFX：[(stem, collection, root_obj), ...]。"""
    out = []
    for col in bpy.data.collections:
        root = None
        for o in col.objects:
            if o.get("~TYPE") == "EFX_ROOT":
                root = o
                break
        if root is None:
            continue
        name = col.name
        stem = name[:-4] if name.lower().endswith(".efx") else name
        out.append((stem, col, root))
    return out


def _path_stem(path):
    """取 epv 路径的文件名干（无扩展名；epv 用反斜杠）。"""
    p = str(path).replace("/", "\\")
    return p.rsplit("\\", 1)[-1]


def find_efx_for_path(path):
    """按 stem 找匹配的 efx 根对象；找不到返回 None。"""
    if not path:
        return None
    stem = _path_stem(path)
    for s, _col, root in _efx_roots():
        if s == stem:
            return root
    return None


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

        for o in context.selected_objects:
            o.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root
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
        _EFX_ENUM_CACHE = [(s, s, "") for s, _c, _r in roots]
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
