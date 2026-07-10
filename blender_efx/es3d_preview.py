"""
blender_efx/es3d_preview.py  —  EMITTERSHAPE3D 发射器形状预览（透明几何体，预览式会话）

设计（与用户确认）
------------------
- **预览式会话**（进入/退出，同 uvc/mesh_align），场景零残留：进入时按 patternControl/
  transform/spawnAngleLimits 生成一个绑在该 ES3D 属性下的透明预览网格子对象；退出即删除。
- **形状 = patternControl**（0=Cube,1=Sphere,2=Ring,3=Spot；见 annotations.py 实测注释），
  **尺寸 = transform.xyz**（FLOAT6 取 idx 0/2/4，与 ES3D 变换共用同一批数据——"变换就是
  几何体的 XYZ"），**弧形裁剪 = spawnAngleLimits**（角度制，360=完整、调小挖去一段弧）。
- **几何生成用 Geometry Nodes 修饰器**（单个共享 node group，多实例复用）：
    Cube/UV Sphere 直接用图元节点；Ring 用 Curve Circle(major) + Curve Circle(minor)
    → Curve to Mesh 组出圆环（GN 无内置 Torus 图元），再转 90°X 摆进局部 XZ 平面
    （y=环高度、x/z=环形状，与文档一致）；Spot 用固定小球做位置标记。
    形状分支用 Switch(GEOMETRY) 三级嵌套（非 Index Switch，兼容更早版本的 GN）。
    弧形裁剪：Position→atan2(局部 X/Z，绕局部 Y 扫)→归一化[0,2π)→与 AngleLimit 比较
    →Delete Geometry（POINT 域），MCP 实机验证：Sphere/Ring 在 270° 下裁出正确的 90° 缺口。
- **对象归属**：预览网格是子对象（parent=ES3D 属性，恒等本地变换），不改 ES3D 本身的
  Empty 类型——数据权威仍在 efx_block 字段，不破坏"属性=Empty"既有类型约定（对齐 MESH
  属性绑定的既有模式，但此处网格是插件自动生成，非用户提供）。
- **实时编辑**：会话期间 fields.py 的字段编辑回调调用本模块 resync_if_active()。
  ⚠ 直接改 GN 修饰器的 ID property（mod[socket_id]=value）不会触发依赖图重算——
  MCP 实测确认，需要 mod.show_viewport 假关再开一次才能强制刷新（不能用
  scene.frame_set 这种会动时间轴、干扰其他预览会话的重手段）。

版本兼容（CLAUDE.md）
--------------------
- node group 构建用 `ng.interface.new_socket(...)`，这是 4.0+ 的 NodeTreeInterface API。
  3.6 走旧式 `ng.inputs.new(...)`，与用户约定的顺序一致：先在 5.1 用 MCP 完善本功能，
  再验证 4.3，最后才补 3.6 分支——`_ensure_node_group()` 用 hasattr 守卫，3.6 分支
  暂未实现（显式抛错而非静默错误几何体）。
- 修饰器 socket key 在 4.0 前后不同（旧版 Input_N / 新版 interface identifier），
  本模块按 socket **名字**动态查 identifier（`_socket_ids`），不硬编码字符串。
- 节点词汇全部选自 GN 早期即有的稳定节点（Mesh Cube/UV Sphere、Curve Primitive Circle、
  Curve to Mesh、Switch、Delete Geometry、Transform），刻意不用 4.1+ 才有的
  Index Switch/Menu Switch，为 3.6 移植预留空间。

约束（CLAUDE.md）
-----------------
- 纯胶水层、只读 EFX 字段，不碰 byte-perfect。Python 3.10、bpy 稳定子集
  （GeometryNodesModifier 自 2.92 稳定；FunctionNodeCompare/GeometryNodeSwitch 同期）。
"""

import math

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator
from bpy.app.handlers import persistent

from .i18n import T

_TEMP_COLLECTION = "EFX ES3D Preview"
_NODE_GROUP_NAME = "EFX ES3D Shape"
_NODE_GROUP_VER = 1  # 图结构版本标记；不匹配则重建（开发期迭代用）
_MATERIAL_NAME = "EFX ES3D Preview Material"
_MODIFIER_NAME = "EFX ES3D Shape"


# ─────────────────────────────────────────────────────────────────────────────
# 属性类型判定 / 字段读取
# ─────────────────────────────────────────────────────────────────────────────

def _attribute_type_hash(obj):
    if obj is None or obj.get("~TYPE") != "EFX_ATTRIBUTE":
        return None
    try:
        return int(obj.efx_block.type_hash_str)
    except Exception:
        return None


def _is_es3d_attribute(obj) -> bool:
    from ..efx_format.hashes import EMITTERSHAPE3D
    return _attribute_type_hash(obj) == EMITTERSHAPE3D


def _read_int(block, name, default=0):
    try:
        for it in block.efx_block.field_items:
            if it.ori_name == name:
                return int(it.int_value)
    except Exception:
        pass
    return default


def _read_float(block, name, default=0.0):
    try:
        for it in block.efx_block.field_items:
            if it.ori_name == name:
                return float(it.float_value)
    except Exception:
        pass
    return default


def _read_transform_xyz(block, default=(1.0, 1.0, 1.0)):
    """读 transform（FLOAT6）的基础三元组（idx 0/2/4），与 mesh_align 的约定一致。"""
    try:
        for it in block.efx_block.field_items:
            if it.ori_name == "transform" and it.data_type == "FLOAT6":
                v = it.float6_value
                return (float(v[0]), float(v[2]), float(v[4]))
    except Exception:
        pass
    return default


def _read_es3d_params(es3d_obj):
    return {
        "shape": _read_int(es3d_obj, "patternControl", 0),
        "size": _read_transform_xyz(es3d_obj),
        "angle": _read_float(es3d_obj, "spawnAngleLimits", 360.0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Geometry Nodes：形状节点组（共享单例，4.0+ NodeTreeInterface）
# ─────────────────────────────────────────────────────────────────────────────

def _build_node_group_40(ng):
    """4.0+ 分支：用 NodeTreeInterface 建 Shape/Size/AngleLimit 输入 + Geometry 输出。

    图结构已在 Blender 5.1 用 MCP 逐节点实机验证（Cube/Sphere/Ring 三种形状 + 270°
    弧形裁剪均正确），细节见模块顶部文档串。
    """
    iface = ng.interface
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    s_shape = iface.new_socket("Shape", in_out="INPUT", socket_type="NodeSocketInt")
    s_shape.default_value = 0
    s_shape.min_value = 0
    s_shape.max_value = 3
    s_size = iface.new_socket("Size", in_out="INPUT", socket_type="NodeSocketVector")
    s_size.default_value = (1.0, 1.0, 1.0)
    s_angle = iface.new_socket("AngleLimit", in_out="INPUT", socket_type="NodeSocketFloat")
    s_angle.default_value = 360.0
    s_angle.min_value = 0.0
    s_angle.max_value = 360.0

    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput"); n_in.location = (-1400, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (900, 0)

    sep = nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1200, -350)
    links.new(n_in.outputs["Size"], sep.inputs[0])

    # ── Cube（shape 0）：Size 直接就是立方体三维尺寸 ──────────────────────────
    cube = nodes.new("GeometryNodeMeshCube"); cube.location = (-1000, 500)
    links.new(n_in.outputs["Size"], cube.inputs["Size"])

    # ── Sphere（shape 1）：半径取 Size.X ─────────────────────────────────────
    sphere = nodes.new("GeometryNodeMeshUVSphere"); sphere.location = (-1000, 300)
    links.new(sep.outputs["X"], sphere.inputs["Radius"])

    # ── Ring（shape 2）：GN 无内置 Torus 图元，用大圆(major)+小圆(minor)
    #    profile 走 Curve to Mesh 组环；major=(X+Z)/2，minor=Y*0.5（对应文档
    #    "x/z=环形状、y=环高度"）；默认落在局部 XY 平面，转 90°X 摆到 XZ 平面。
    add_xz = nodes.new("ShaderNodeMath"); add_xz.operation = "ADD"; add_xz.location = (-1000, -50)
    links.new(sep.outputs["X"], add_xz.inputs[0])
    links.new(sep.outputs["Z"], add_xz.inputs[1])
    major_r = nodes.new("ShaderNodeMath"); major_r.operation = "MULTIPLY"
    major_r.inputs[1].default_value = 0.5; major_r.location = (-850, -50)
    links.new(add_xz.outputs["Value"], major_r.inputs[0])

    minor_r = nodes.new("ShaderNodeMath"); minor_r.operation = "MULTIPLY"
    minor_r.inputs[1].default_value = 0.5; minor_r.location = (-1000, -200)
    links.new(sep.outputs["Y"], minor_r.inputs[0])

    major_circle = nodes.new("GeometryNodeCurvePrimitiveCircle"); major_circle.location = (-700, 0)
    major_circle.inputs["Resolution"].default_value = 48
    links.new(major_r.outputs["Value"], major_circle.inputs["Radius"])
    minor_circle = nodes.new("GeometryNodeCurvePrimitiveCircle"); minor_circle.location = (-700, -200)
    minor_circle.inputs["Resolution"].default_value = 16
    links.new(minor_r.outputs["Value"], minor_circle.inputs["Radius"])

    c2m = nodes.new("GeometryNodeCurveToMesh"); c2m.location = (-500, -50)
    links.new(major_circle.outputs["Curve"], c2m.inputs["Curve"])
    links.new(minor_circle.outputs["Curve"], c2m.inputs["Profile Curve"])

    ring_xform = nodes.new("GeometryNodeTransform"); ring_xform.location = (-300, -50)
    ring_xform.inputs["Rotation"].default_value = (math.radians(90.0), 0.0, 0.0)
    links.new(c2m.outputs["Mesh"], ring_xform.inputs["Geometry"])

    # ── Spot/Point（shape 3）：固定小球做位置标记，不随 Size 缩放 ────────────
    point = nodes.new("GeometryNodeMeshUVSphere"); point.location = (-1000, -450)
    point.inputs["Radius"].default_value = 0.05
    point.inputs["Segments"].default_value = 8
    point.inputs["Rings"].default_value = 4

    # ── 形状分支：Switch(GEOMETRY) 三级嵌套，按 Shape==0/1/2 分支，默认(含3)=Point ─
    cmp0 = nodes.new("FunctionNodeCompare"); cmp0.data_type = "INT"; cmp0.operation = "EQUAL"
    cmp0.location = (-1200, 700); cmp0.inputs[3].default_value = 0
    links.new(n_in.outputs["Shape"], cmp0.inputs[2])
    cmp1 = nodes.new("FunctionNodeCompare"); cmp1.data_type = "INT"; cmp1.operation = "EQUAL"
    cmp1.location = (-1200, 650); cmp1.inputs[3].default_value = 1
    links.new(n_in.outputs["Shape"], cmp1.inputs[2])
    cmp2 = nodes.new("FunctionNodeCompare"); cmp2.data_type = "INT"; cmp2.operation = "EQUAL"
    cmp2.location = (-1200, 600); cmp2.inputs[3].default_value = 2
    links.new(n_in.outputs["Shape"], cmp2.inputs[2])

    swC = nodes.new("GeometryNodeSwitch"); swC.input_type = "GEOMETRY"; swC.location = (200, -200)
    links.new(cmp2.outputs["Result"], swC.inputs["Switch"])
    links.new(point.outputs["Mesh"], swC.inputs["False"])
    links.new(ring_xform.outputs["Geometry"], swC.inputs["True"])

    swB = nodes.new("GeometryNodeSwitch"); swB.input_type = "GEOMETRY"; swB.location = (400, 0)
    links.new(cmp1.outputs["Result"], swB.inputs["Switch"])
    links.new(swC.outputs["Output"], swB.inputs["False"])
    links.new(sphere.outputs["Mesh"], swB.inputs["True"])

    swA = nodes.new("GeometryNodeSwitch"); swA.input_type = "GEOMETRY"; swA.location = (600, 200)
    links.new(cmp0.outputs["Result"], swA.inputs["Switch"])
    links.new(swB.outputs["Output"], swA.inputs["False"])
    links.new(cube.outputs["Mesh"], swA.inputs["True"])

    # ── 弧形裁剪：绕局部 Y 轴扫（atan2(Z,X)），归一化到 [0, 2π) 与 AngleLimit 比较 ──
    pos = nodes.new("GeometryNodeInputPosition"); pos.location = (200, -500)
    posSep = nodes.new("ShaderNodeSeparateXYZ"); posSep.location = (400, -500)
    links.new(pos.outputs["Position"], posSep.inputs[0])

    atan2 = nodes.new("ShaderNodeMath"); atan2.operation = "ARCTAN2"; atan2.location = (600, -500)
    links.new(posSep.outputs["Z"], atan2.inputs[0])
    links.new(posSep.outputs["X"], atan2.inputs[1])

    add_2pi = nodes.new("ShaderNodeMath"); add_2pi.operation = "ADD"; add_2pi.location = (800, -500)
    add_2pi.inputs[1].default_value = math.tau
    links.new(atan2.outputs["Value"], add_2pi.inputs[0])

    mod_2pi = nodes.new("ShaderNodeMath"); mod_2pi.operation = "MODULO"; mod_2pi.location = (1000, -500)
    mod_2pi.inputs[1].default_value = math.tau
    links.new(add_2pi.outputs["Value"], mod_2pi.inputs[0])

    ang_rad = nodes.new("ShaderNodeMath"); ang_rad.operation = "RADIANS"; ang_rad.location = (200, -650)
    links.new(n_in.outputs["AngleLimit"], ang_rad.inputs[0])

    cmp_ang = nodes.new("FunctionNodeCompare"); cmp_ang.data_type = "FLOAT"; cmp_ang.operation = "GREATER_THAN"
    cmp_ang.location = (1200, -500)
    links.new(mod_2pi.outputs["Value"], cmp_ang.inputs[0])
    links.new(ang_rad.outputs["Value"], cmp_ang.inputs[1])

    delete = nodes.new("GeometryNodeDeleteGeometry"); delete.domain = "POINT"; delete.location = (1400, 0)
    links.new(swA.outputs["Output"], delete.inputs["Geometry"])
    links.new(cmp_ang.outputs["Result"], delete.inputs["Selection"])

    links.new(delete.outputs["Geometry"], n_out.inputs["Geometry"])


def _ensure_node_group():
    """按名取用已存在的共享节点组；版本不符或不存在则（重）建。"""
    ng = bpy.data.node_groups.get(_NODE_GROUP_NAME)
    if ng is not None and ng.get("efx_es3d_ver") == _NODE_GROUP_VER:
        return ng
    if ng is not None:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new(_NODE_GROUP_NAME, "GeometryNodeTree")
    if hasattr(ng, "interface"):
        _build_node_group_40(ng)
    else:
        # TODO(3.6 分支)：旧式 ng.inputs.new(...) / ng.outputs.new(...) 接口。
        # 按用户约定的顺序，5.1→4.3 验证通过后再补——先显式报错，不留静默错误几何体。
        bpy.data.node_groups.remove(ng)
        raise RuntimeError("EFX ES3D preview: Blender < 4.0 node group interface not yet implemented")
    ng["efx_es3d_ver"] = _NODE_GROUP_VER
    return ng


_SOCKET_IDS_CACHE = {}


def _socket_ids(ng):
    ids = _SOCKET_IDS_CACHE.get(ng.name)
    if ids is not None:
        return ids
    ids = {
        item.name: item.identifier
        for item in ng.interface.items_tree
        if item.item_type == "SOCKET" and item.in_out == "INPUT"
    }
    _SOCKET_IDS_CACHE[ng.name] = ids
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# 透明预览材质
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_material():
    mat = bpy.data.materials.get(_MATERIAL_NAME)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(_MATERIAL_NAME)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        try:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.2, 0.85, 1.0)  # 紫色，呼应 EFX COLOR_06
            bsdf.inputs["Alpha"].default_value = 0.25
        except Exception:
            pass
    # 4.2+ EEVEE Next / 旧 EEVEE 两套渲染方式属性，版本守卫（同 uvc_preview._force_blended）
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    try:
        mat.show_transparent_back = False
    except Exception:
        pass
    return mat


# ─────────────────────────────────────────────────────────────────────────────
# 预览对象：创建 / 应用参数 / 刷新
# ─────────────────────────────────────────────────────────────────────────────

def _get_temp_collection():
    col = bpy.data.collections.get(_TEMP_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(_TEMP_COLLECTION)
        try:
            bpy.context.scene.collection.children.link(col)
        except Exception:
            pass
    return col


def _make_preview_object(es3d_obj, col, label):
    ng = _ensure_node_group()
    mesh_data = bpy.data.meshes.new("EFX_es3d_preview_mesh")
    obj = bpy.data.objects.new("EFX_es3d::" + label, mesh_data)
    col.objects.link(obj)
    # 恒等本地变换的子对象：obj.matrix_world == es3d.matrix_world（"变换就是几何体 XYZ"）
    obj.parent = es3d_obj
    obj["~EFX_ES3D_PREVIEW"] = 1

    mod = obj.modifiers.new(_MODIFIER_NAME, "NODES")
    mod.node_group = ng

    mat = _ensure_material()
    obj.data.materials.append(mat)
    obj.display_type = "SOLID"
    return obj, mod


def _apply_params(obj, mod, params):
    ng = mod.node_group
    if ng is None:
        return
    ids = _socket_ids(ng)
    try:
        mod[ids["Shape"]] = int(params["shape"])
        mod[ids["Size"]] = params["size"]
        mod[ids["AngleLimit"]] = float(params["angle"])
    except Exception:
        return
    # ⚠ 直改 ID property 不会自动触发依赖图重算（MCP 实测）；假关再开 show_viewport
    # 强制刷新，不用 scene.frame_set（会动时间轴，干扰其他并行预览会话）。
    try:
        mod.show_viewport = False
        mod.show_viewport = True
    except Exception:
        pass
    obj.update_tag()
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 会话状态
# ─────────────────────────────────────────────────────────────────────────────

_state = {
    "active": False,
    "by_attribute": {},    # es3d_attribute.name -> preview_obj.name
    "instances": [],   # 全部预览对象名
    "collection": None,
}


def resync_if_active(es3d_obj):
    """会话进行中，重同步该 ES3D 属性的预览对象（供 fields.py 编辑回调调用）。

    ⚠ 按对象名重新解析（撤销会让 Python 持有的引用失效，名仍有效，同 mesh_align）。
    """
    if not _state["active"] or es3d_obj is None:
        return
    obj_name = _state["by_attribute"].get(es3d_obj.name)
    if not obj_name:
        return
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return
    mod = obj.modifiers.get(_MODIFIER_NAME)
    if mod is None:
        return
    _apply_params(obj, mod, _read_es3d_params(es3d_obj))


def _resolve_root(obj):
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ROOT":
            return cur
        cur = cur.parent
    return None


def _all_efx_roots():
    return [o for o in bpy.data.objects if o.get("~TYPE") == "EFX_ROOT"]


def _iter_scope_es3d_attributes(root):
    for body in root.children:
        if body.get("~TYPE") != "EFX_ENTRY":
            continue
        for blk in body.children:
            if _is_es3d_attribute(blk):
                yield blk


def _start(roots):
    col = _get_temp_collection()
    n = 0
    for root in roots:
        if root is None:
            continue
        for blk in _iter_scope_es3d_attributes(root):
            label = str(blk.get("efx_raw_label", "") or blk.name)
            obj, mod = _make_preview_object(blk, col, label)
            _apply_params(obj, mod, _read_es3d_params(blk))
            _state["by_attribute"][blk.name] = obj.name
            _state["instances"].append(obj.name)
            n += 1
    _state["collection"] = col.name
    _state["active"] = True
    return n


def _stop():
    for name in _state["instances"]:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        mesh = obj.data
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
        try:
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except Exception:
            pass
    col = bpy.data.collections.get(_state["collection"]) if _state["collection"] else None
    if col is not None:
        try:
            bpy.data.collections.remove(col)
        except Exception:
            pass
    _state["active"] = False
    _state["by_attribute"] = {}
    _state["instances"] = []
    _state["collection"] = None


@persistent
def _on_load(*_args):
    _state["active"] = False
    _state["by_attribute"] = {}
    _state["instances"] = []
    _state["collection"] = None


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_scope_roots(context):
    if getattr(context.scene, "efx_es3d_preview_all", False):
        roots = _all_efx_roots()
        return roots or None
    root = _resolve_root(context.active_object)
    return [root] if root is not None else None


class EFX_OT_es3d_preview_enter(Operator):
    """进入 EmitterShape3D 形状预览（生成透明几何体：立方体/球/环/点，随字段实时更新）"""

    bl_idname = "efx.es3d_preview_enter"
    bl_label = "Enter ES3D Shape Preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if _state["active"]:
            return False
        if getattr(context.scene, "efx_es3d_preview_all", False):
            return True
        return _resolve_root(context.active_object) is not None

    def execute(self, context):
        roots = _resolve_scope_roots(context)
        if not roots:
            self.report({"ERROR"}, T("es3d.no_root"))
            return {"CANCELLED"}
        try:
            n = _start(roots)
        except Exception as exc:
            _stop()
            self.report({"ERROR"}, T("es3d.failed").format(exc))
            return {"CANCELLED"}
        if n == 0:
            _stop()
            self.report({"WARNING"}, T("es3d.no_content"))
            return {"CANCELLED"}
        self.report({"INFO"}, T("es3d.entered").format(n))
        return {"FINISHED"}


class EFX_OT_es3d_preview_exit(Operator):
    """退出 EmitterShape3D 形状预览（删除生成的预览几何体）"""

    bl_idname = "efx.es3d_preview_exit"
    bl_label = "Exit ES3D Shape Preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _state["active"]

    def execute(self, context):
        _stop()
        self.report({"INFO"}, T("es3d.exited"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_es3d_preview_enter,
    EFX_OT_es3d_preview_exit,
]


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_es3d_preview_all = BoolProperty(
        name="Preview all EFX",
        description="Preview EmitterShape3D shapes for every EFX in the scene (else current EFX only)",
        default=False,
    )
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    _stop()
    if _on_load in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "efx_es3d_preview_all"):
        del bpy.types.Scene.efx_es3d_preview_all
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
