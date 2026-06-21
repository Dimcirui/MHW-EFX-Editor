"""
blender_epv/panels.py — EPV 工具 / 字段 N 面板（阶段 2 + 3）。

3D 视口 N 面板「EPV」标签页：
  EPV_PT_main      — 导入 / 导出 + 当前选中信息
  EPV_PT_group     — 选中 record 所属 group 的 groupID（可编辑）
  EPV_PT_record    — record 字段：EFX 路径、EFX Slots 8 槽颜色表、空间、raw 字段
"""
import bpy


def _record_group_collection(obj):
    """返回 record 对象所在的 EPV_GROUP 集合（找不到返回 None）。"""
    if obj is None:
        return None
    for col in obj.users_collection:
        if col.get("~TYPE") == "EPV_GROUP":
            return col
    return None


class EPV_PT_main(bpy.types.Panel):
    bl_label = "EPV Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EPV"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("epv.import_epv", icon="IMPORT")
        col.operator("epv.export_epv", icon="EXPORT")

        obj = context.active_object
        if obj is not None and str(obj.get("~TYPE", "")).startswith("EPV_"):
            box = layout.box()
            box.label(text="Active: " + obj.name, icon="DOT")
            box.label(text="Type: " + str(obj.get("~TYPE")))


class EPV_PT_group(bpy.types.Panel):
    bl_label = "EPV Group"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EPV"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EPV_RECORD"

    def draw(self, context):
        layout = self.layout
        gcol = _record_group_collection(context.active_object)
        if gcol is None:
            layout.label(text="(group collection not found)", icon="ERROR")
            return
        layout.label(text=gcol.name, icon="OUTLINER_COLLECTION")
        # 集合自定义属性 ~GID 直接编辑（id-property 路径）
        layout.prop(gcol, '["~GID"]', text="Group ID")


class EPV_PT_record(bpy.types.Panel):
    bl_label = "EPV Record"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EPV"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EPV_RECORD"

    def draw(self, context):
        layout = self.layout
        rp = context.active_object.epv_record

        # ── EFX 路径槽（+ L1/L2 联动）────────────────────────────────────────
        from . import efx_link
        box = layout.box()
        box.label(text="EFX Paths", icon="FILE")
        for i in range(4):
            p = getattr(rp, "path%d" % i)
            matched = efx_link.find_efx_for_path(p) is not None if p else False
            row = box.row(align=True)
            row.label(text="", icon="CHECKMARK" if matched else "BLANK1")
            row.prop(rp, "path%d" % i, text="")
            op = row.operator("epv.pick_efx_path", text="", icon="DOWNARROW_HLT")
            op.slot = i
            sub = row.row(align=True)
            sub.enabled = matched
            op = sub.operator("epv.jump_to_efx", text="", icon="RESTRICT_SELECT_OFF")
            op.slot = i

        # ── EFX Slots 8 槽颜色表 ─────────────────────────────────────────────
        box = layout.box()
        box.label(text="EFX Slots", icon="COLOR")
        header = box.row(align=True)
        header.label(text="Slot")
        header.label(text="Color")
        header.label(text="Sat")
        header.label(text="Size")
        header.label(text="Freq")
        for it in rp.epv_colors:
            row = box.row(align=True)
            row.prop(it, "efxslot", text="")
            row.prop(it, "color", text="")
            row.prop(it, "saturation", text="")
            row.prop(it, "size", text="")
            row.prop(it, "frequency", text="")

        # ── 空间（transform 驱动 + jitter）─────────────────────────────────────
        box = layout.box()
        box.label(text="Transform", icon="ORIENTATION_GLOBAL")
        obj = context.active_object
        box.prop(obj, "location", text="Position")
        box.prop(obj, "rotation_euler", text="Rotation")
        box.prop(rp, "positionJitter")
        box.prop(rp, "rotationJitter")
        box.prop(obj, '["~RIDX"]', text="Record Order")

        # ── raw 字段（语义后补）─────────────────────────────────────────────
        box = layout.box()
        box.label(text="Raw Fields", icon="SCRIPT")
        box.prop(rp, "boneID")
        box.prop(rp, "recordID")
        box.prop(rp, "unknownID")
        box.prop(rp, "padding")
        col = box.column(align=True)
        col.prop(rp, "pb1_EFXSubIndex")
        col.prop(rp, "pb1_EFXSubIndex2")
        col.prop(rp, "pb1_paramU0")
        col.prop(rp, "pb1_paramU1")
        col.prop(rp, "pb1_paramU2")
        col.prop(rp, "pb1_paramU3")
        col.prop(rp, "pb1_paramU4")
        col.prop(rp, "paramW3")
        col.prop(rp, "paramW4")
        col.prop(rp, "paramV")

        # ── Effect Scale（特效大小总控：fixed + random）──────────────────────
        sub = box.column(align=True)
        sub.label(text="Effect Scale (1=unchanged, 0.5=half)")
        sub.prop(rp, "paramW5", index=0, text="Fixed")
        sub.prop(rp, "paramW5", index=1, text="Random")
        col.prop(rp, "pb2_f1")
        row = col.row(align=True)
        row.prop(rp, "pb2_b1")
        row.prop(rp, "pb2_b2")
        row.prop(rp, "pb2_b3")
        row.prop(rp, "pb2_b4")
        col.prop(rp, "pb2_i1")
        col.prop(rp, "pb2_f2")
        col.prop(rp, "pb2_i2")
        col.prop(rp, "pb2_i3")


_CLASSES = (EPV_PT_main, EPV_PT_group, EPV_PT_record)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
