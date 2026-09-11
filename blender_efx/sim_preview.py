# -*- coding: utf-8 -*-
"""
blender_efx/sim_preview.py  —  粒子模拟播放器（modal 时钟 + gpu 绘制，零场景对象）

定位
----
`efx_format/sim`（零 bpy）负责算，本模块只负责三件事：

  1. **喂数据**：从**正在编辑的属性树**拼 `[(type_hash, fields_dict)]`——不是从
     上次保存的文件读，否则预览看到的不是你刚改的值。
  2. **时钟**：modal + `wm.event_timer_add`，自带播放/循环/倍速，**不碰
     `scene.frame_current`**，与时间轴完全解耦。
  3. **绘制**：`SpaceView3D.draw_handler_add(POST_VIEW)` 直接画，**不建任何场景对象**
     ——没有标记、没有孤儿、不污染 undo 栈（session_core 那一整套在这里用不上）。

为什么不走 mesh + 几何节点
--------------------------
用户明确「不要求在 3D View、不要求拖时间轴」之后，场景对象那条路的代价（生命周期
管理 + GN 建图 + frame_change 耦合 + EEVEE 没有加法混合）就全都没必要付了。直接
gpu 绘制还顺带把加法混合白拿了：`gpu.state.blend_set('ADDITIVE')` 一行，比 EEVEE
（4.2+ 只剩 Dithered/Blended 两种 Render Method）能做到的更准。

骨架照搬 `uvs_io.py`（`wm.window_new` + `draw_handler_add` + modal 管生命周期），
那套在本仓库已经跑通过。

⚠ 本文件尚未在 Blender 里跑过
-----------------------------
写它的环境没有 Blender。逻辑层（efx_format/sim）有 74 条单测护着，但下面这些
bpy 侧的东西必须实机验一遍：

  - `gpu.shader.from_builtin` 的名字：4.0+ 是 'FLAT_COLOR'，3.x 是 '3D_FLAT_COLOR'。
    `_builtin()` 两个都试。（顺带一提 uvs_io.py:766 直接写死了 4.0+ 的名字，
    如果那边 3.6 确实报错，把 `_builtin` 提出去共用即可。）
  - `gpu.state.blend_set('ADDITIVE')` 是否如预期。
  - **不要**用 `gpu.types.GPUShader(vert_src, frag_src)` 字符串构造器：3.4 起废弃、
    5.0 移除，且 Vulkan 后端（5.x 默认）下不工作。本模块只用 builtin shader，
    真要自定义 shader 走 `gpu.shader.create_from_info`。

约束（CLAUDE.md）：bpy 稳定子集；Python 3.10；纯胶水层，不改 efx_format/。
"""

import base64
import math
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator, Panel

from .i18n import T

_DRAW_TAG = "~EFX_SIM_PREVIEW"      # draw handler 识别用（跨热重载按名移除）


# ─────────────────────────────────────────────────────────────────────────────
# 播放器状态
#
# 这里用模块级 dict 是**合理的**（对比 session_core 的教条）：本模块不产生任何
# 场景数据，没有「场景里的残留物要清理」的问题。真相源就是 draw handler 在不在、
# modal 在不在——两者都由本 dict 持有并由算子成对管理。
# ─────────────────────────────────────────────────────────────────────────────

_P = {
    "sim": None,          # efx_format.sim.Simulator
    "entry_name": "",     # 正在预览的 EFX_ENTRY 对象名
    "playing": False,
    "acc": 0.0,           # 帧累加器（浮点，只走整数帧）
    "last_t": 0.0,        # 上次 tick 的墙钟
    "duration": 0,        # 本次「播放一次」的长度（帧）
    "items": [],          # 最近一次 build_render 的结果（draw handler 读它）
    "handler": None,
    "timer": None,
    "dirty": False,       # 属性被编辑过 → 下个 tick 重建
    "error": "",
    "ref_rows": None,     # 播放起点的 entry 世界矩阵（三行），绘制与位移都以它为基准
    "mesh_cache": {},     # 绑定网格 → 游戏坐标系下的三角顶点（避免逐帧重算）
}


def is_active():
    return _P["handler"] is not None


def is_playing():
    return _P["playing"] and is_active()


# ─────────────────────────────────────────────────────────────────────────────
# 属性树 → 模拟器输入
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_entry(obj):
    """从当前活动对象往上找 EFX_ENTRY。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_ENTRY":
            return cur
        cur = cur.parent
    return None


def _entry_attributes(entry_obj):
    """entry 下的 EFX_ATTRIBUTE 子对象，按 efx_index 排序（= 文件里的顺序）。"""
    out = [o for o in bpy.data.objects
           if o.parent is entry_obj and o.get("~TYPE") == "EFX_ATTRIBUTE"]
    out.sort(key=lambda o: int(o.get("efx_index", 0)))
    return out


def _block_fields(blk_obj):
    """一个属性块 → (type_hash, fields_dict)，**反映未保存的编辑**。

    走导出同一条路：`fields.get_attribute_data_bytes` 按当前属性树重建字节，
    再用 `AttrBlock.decode()` 解成 dict。复用已经被往返测试盖住的路径，比另写
    一套「property → dict」的读法可靠得多（后者要重复处理十几种值槽）。
    opaque 块或重建异常 → 回退到自定义属性里的原始字节。
    """
    from ..efx_format.efxfile import AttrBlock

    try:
        type_hash = int(blk_obj.efx_block.type_hash_str)
    except Exception:
        return None

    data = None
    try:
        from . import fields as _fields
        data = _fields.get_attribute_data_bytes(blk_obj)
    except Exception:
        data = None
    if data is None:
        try:
            data = base64.b64decode(str(blk_obj["data_bytes"]))
        except Exception:
            return None

    try:
        decoded = AttrBlock(type_hash, data).decode()
    except Exception:
        decoded = None
    return (type_hash, decoded if decoded is not None else {})


def _entry_timl_bytes(entry_obj):
    try:
        return base64.b64decode(str(entry_obj.get("timl_bytes", "")))
    except Exception:
        return b""


def _config_from_scene(scene):
    """场景属性 → SimConfig。待标定项全在这儿落地成开关。"""
    from ..efx_format.sim import SimConfig

    return SimConfig(
        seed=int(getattr(scene, "efx_sim_seed", 0)),
        jitter_mode=getattr(scene, "efx_sim_jitter_mode", "onesided"),
        a0_sample=getattr(scene, "efx_sim_a0_sample", "spawn"),
        timl_mode=getattr(scene, "efx_sim_timl_mode", "replace"),
        timl_interp=getattr(scene, "efx_sim_timl_interp", "native"),
        life_model=getattr(scene, "efx_sim_life_model", "sum"),
        age_during_delay=bool(getattr(scene, "efx_sim_age_during_delay", False)),
        es3d_range_mode=getattr(scene, "efx_sim_es3d_range_mode", "minmax"),
        rot_order_applied=getattr(scene, "efx_sim_rot_order", "forward"),
    )


def build_simulator(entry_obj, scene):
    """按当前属性树建一个新的 Simulator。失败返回 None 并把原因写进 _P['error']。"""
    from ..efx_format.sim import Simulator

    blocks = []
    for blk in _entry_attributes(entry_obj):
        pair = _block_fields(blk)
        if pair is not None:
            blocks.append(pair)
    if not blocks:
        _P["error"] = T("sim.err_no_attributes")
        return None

    try:
        sim = Simulator(blocks, _entry_timl_bytes(entry_obj), _config_from_scene(scene))
    except Exception as exc:
        _P["error"] = str(exc)
        return None
    _P["error"] = ""
    return sim


def invalidate_if_active(obj=None):
    """字段被编辑 → 下个 tick 重建模拟器。fields.py 的编辑回调调用本函数。

    刻意只置一个标志：编辑回调是**每改一个字段就触发一次**的热路径，在里面重建
    整个模拟器会卡。真正的重建推迟到定时器 tick（见 `_tick`）。
    """
    if is_active():
        _P["dirty"] = True


# ─────────────────────────────────────────────────────────────────────────────
# 坐标换算（游戏 → Blender）
#
# 与 transform_sync.game_loc_to_blender 同一套：/100 + (X,Y,Z)→(X,-Z,Y)。
# 核心层全程用游戏坐标，换算只在这里发生一次。
# ─────────────────────────────────────────────────────────────────────────────

_UNIT = 1.0 / 100.0


def _to_blender(v):
    return (v.x * _UNIT, -v.z * _UNIT, v.y * _UNIT)


def _to_game(bx, by, bz):
    """_to_blender 的逆。宿主报告发射器位移时用。"""
    return (bx / _UNIT, bz / _UNIT, -by / _UNIT)


def _ref_local(rows, world_pos):
    """世界坐标点 → 参考系下的局部偏移。

    把参考系当刚体处理（`Rᵀ(p − t)`）：entry empty 上如果有非 1 的缩放，这里会
    有偏差——语料里 TRANSFORM3D.resize 恒为 1.0，先不为它引入 mathutils 依赖。
    """
    dx = world_pos[0] - rows[0][3]
    dy = world_pos[1] - rows[1][3]
    dz = world_pos[2] - rows[2][3]
    return (rows[0][0] * dx + rows[1][0] * dy + rows[2][0] * dz,
            rows[0][1] * dx + rows[1][1] * dy + rows[2][1] * dz,
            rows[0][2] * dx + rows[1][2] * dy + rows[2][2] * dz)


def _sync_host_origin(scene):
    """把 entry empty 相对**播放起点**的位移报给模拟器。

    为什么需要：条带类渲染体（RIBBON 轨迹跟随 / RIBBONBLADE 刀光）画的是发射器
    划过的轨迹。blade_trail 这类原型根本没有 VELOCITY3D——粒子自己不动，整个效果
    靠 PARENTOPTIONS 把发射器绑在挥动的武器骨骼上。宿主不把这个位移报进去，
    模拟层就永远看不到运动，刀光永远是空的。

    参考系取**播放开始那一刻**的世界矩阵并固定下来（`_P['ref_rows']`），绘制也
    用它——这样发射器移动时，已经发出去的粒子会如实留在原地，而不是跟着整体平移。
    """
    sim = _P["sim"]
    entry = bpy.data.objects.get(_P["entry_name"])
    rows = _P["ref_rows"]
    if sim is None or entry is None or rows is None:
        return
    try:
        world = entry.matrix_world.translation
    except Exception:
        return
    bx, by, bz = _ref_local(rows, (world[0], world[1], world[2]))
    gx, gy, gz = _to_game(bx, by, bz)
    ho = sim.em.host_origin
    ho.x, ho.y, ho.z = gx, gy, gz


def _entry_matrix_rows(entry_obj):
    """entry empty 的世界矩阵，拆成三行纯 float 元组。

    用**完整矩阵**而不只是位置：TRANSFORM3D 的 rotate/resize 以及 PARENTOPTIONS 的
    骨骼绑定都已经由 transform_sync.py 烘进了这个矩阵，乘上去就自动全部继承——
    模拟层因此完全不必知道骨骼、锚定这些事（见 behaviors/transform3d.py 的分工说明）。

    ⚠ 只有**位置**过这个矩阵，粒子自身的尺寸不跟着 entry 的 scale 缩放。语料里
    TRANSFORM3D.resize 恒为 1.0，区分不出来；真遇到非 1 的再定。
    """
    try:
        m = entry_obj.matrix_world
        return ((m[0][0], m[0][1], m[0][2], m[0][3]),
                (m[1][0], m[1][1], m[1][2], m[1][3]),
                (m[2][0], m[2][1], m[2][2], m[2][3]))
    except Exception:
        return ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


def _spin(right, up, deg):
    """把相机平面内的右/上向量绕视线转 `deg` 度 —— billboard 的自转。"""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return ((right[0] * c + up[0] * s, right[1] * c + up[1] * s, right[2] * c + up[2] * s),
            (-right[0] * s + up[0] * c, -right[1] * s + up[1] * c, -right[2] * s + up[2] * c))


# ─────────────────────────────────────────────────────────────────────────────
# GPU 绘制
# ─────────────────────────────────────────────────────────────────────────────

def _builtin(name):
    """builtin shader 取名的跨版本包装。

    4.0 起 2D/3D 统一成 'FLAT_COLOR' 这样的短名，3.x 是 '3D_FLAT_COLOR'。
    先试新名、失败再试旧名，这样 3.6→5.x 同一份代码都能跑。
    """
    import gpu
    try:
        return gpu.shader.from_builtin(name)
    except Exception:
        return gpu.shader.from_builtin("3D_" + name)


def _quad_verts(center, right, up, hw, hh):
    """两个三角形拼一个面朝相机的方片。"""
    rx, ry, rz = right[0] * hw, right[1] * hw, right[2] * hw
    ux, uy, uz = up[0] * hh, up[1] * hh, up[2] * hh
    cx, cy, cz = center
    a = (cx - rx - ux, cy - ry - uy, cz - rz - uz)
    b = (cx + rx - ux, cy + ry - uy, cz + rz - uz)
    c = (cx + rx + ux, cy + ry + uy, cz + rz + uz)
    d = (cx - rx + ux, cy - ry + uy, cz - rz + uz)
    return (a, b, c, a, c, d)


def _camera_axes(rv3d):
    """视图矩阵前两行 = 世界空间下的相机右/上向量（面向相机用）。"""
    vm = rv3d.view_matrix
    right = (vm[0][0], vm[0][1], vm[0][2])
    up = (vm[1][0], vm[1][1], vm[1][2])
    return right, up


def _view_direction(rv3d):
    """视图矩阵第三行 = 相机朝向（世界空间）。条带要绕它把宽度撑开。"""
    vm = rv3d.view_matrix
    return (vm[2][0], vm[2][1], vm[2][2])


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-9:
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _emit_ribbon(verts, colors, item, col, size_mul, world_fn, view_dir):
    """条带 → 三角形。

    每一段的「横向」取 `段方向 × 视线` 并归一化——这样条带永远把宽面朝向相机，
    是 Trail Renderer 的标准做法。段方向与视线平行时（正对着看）叉乘退化，
    这一段就跳过，不画烂三角。
    """
    pts = item.points
    if not pts or len(pts) < 2:
        return
    world = [world_fn(q) for q, _hw, _a in pts]
    sides = []
    n = len(world)
    for i in range(n):
        a = world[max(0, i - 1)]
        b = world[min(n - 1, i + 1)]
        seg = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        s = _norm(_cross(seg, view_dir))
        sides.append(s)

    half = [max(1e-5, size_mul * abs(hw) * _UNIT) for _q, hw, _a in pts]
    alphas = [a for _q, _hw, a in pts]

    for i in range(n - 1):
        s0, s1 = sides[i], sides[i + 1]
        if s0 is None or s1 is None:
            continue
        p0, p1 = world[i], world[i + 1]
        h0, h1 = half[i], half[i + 1]
        a0 = (col[0], col[1], col[2], col[3] * alphas[i])
        a1 = (col[0], col[1], col[2], col[3] * alphas[i + 1])

        l0 = (p0[0] - s0[0] * h0, p0[1] - s0[1] * h0, p0[2] - s0[2] * h0)
        r_0 = (p0[0] + s0[0] * h0, p0[1] + s0[1] * h0, p0[2] + s0[2] * h0)
        l1 = (p1[0] - s1[0] * h1, p1[1] - s1[1] * h1, p1[2] - s1[2] * h1)
        r_1 = (p1[0] + s1[0] * h1, p1[1] + s1[1] * h1, p1[2] + s1[2] * h1)

        verts.extend((l0, r_0, r_1, l0, r_1, l1))
        colors.extend((a0, a0, a1, a0, a1, a1))


#: MESH 没绑定网格时画的占位：单位立方体的 12 个三角（游戏坐标系，半边长 1）
_PLACEHOLDER_TRIS = None


def _placeholder_cube():
    global _PLACEHOLDER_TRIS
    if _PLACEHOLDER_TRIS is not None:
        return _PLACEHOLDER_TRIS
    c = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
             (0, 4, 5), (0, 5, 1), (2, 6, 7), (2, 7, 3),
             (1, 5, 6), (1, 6, 2), (0, 3, 7), (0, 7, 4)]
    _PLACEHOLDER_TRIS = [c[i] for f in faces for i in f]
    return _PLACEHOLDER_TRIS


def _mesh_tris_game(mesh_obj):
    """绑定网格的三角顶点，换算到**游戏坐标系**并缓存。

    换算一次、缓存下来，之后每个粒子只需要旋转/缩放/平移，不必逐帧重做坐标变换。
    """
    if mesh_obj is None:
        return _placeholder_cube()
    key = mesh_obj.name
    cached = _P["mesh_cache"].get(key)
    if cached is not None:
        return cached
    try:
        me = mesh_obj.data
        me.calc_loop_triangles()
        verts = me.vertices
        out = []
        for tri in me.loop_triangles:
            for vi in tri.vertices:
                co = verts[vi].co
                out.append(_to_game(co[0], co[1], co[2]))
    except Exception:
        out = _placeholder_cube()
    _P["mesh_cache"][key] = out
    return out


def _bound_mesh_for(entry_obj):
    """entry 下 MESH 属性绑定的网格对象（mod3_link 填的 efx_mesh_target）。"""
    for blk in _entry_attributes(entry_obj):
        try:
            tgt = getattr(blk, "efx_mesh_target", None)
        except Exception:
            tgt = None
        if tgt is not None and getattr(tgt, "type", None) == "MESH":
            return tgt
    return None


def _emit_mesh(verts, colors, item, col, size_mul, world_fn, entry_obj):
    """网格 → 三角形。

    几何来自宿主（mod3_link 已经把 mod3 导进来并绑在 MESH 属性上），模拟层只给
    位置/旋转/缩放/颜色。没绑定就画一个占位立方体——比什么都不画诚实。
    """
    from ..efx_format.sim.vecmath import rotate_euler
    from ..efx_format.sim.state import Vec3

    tris = _mesh_tris_game(_bound_mesh_for(entry_obj))
    if not tris:
        return

    rot = item.extra.get("rot")
    order = item.extra.get("rot_order", "XYZ")
    sx = size_mul * item.size.x
    sy = size_mul * item.size.y
    sz = size_mul * item.size.z
    px, py, pz = item.pos.x, item.pos.y, item.pos.z

    rx = ry = rz = 0.0
    if rot is not None:
        rx, ry, rz = rot.x, rot.y, rot.z

    for (vx, vy, vz) in tris:
        v = Vec3(vx * sx, vy * sy, vz * sz)
        if rx or ry or rz:
            v = rotate_euler(v, rx, ry, rz, order=order)
        v.x += px
        v.y += py
        v.z += pz
        verts.append(world_fn(v))
        colors.append(col)


def _draw():
    """POST_VIEW draw handler。**不改任何状态**，只画 _P['items']。"""
    if not is_active():
        return
    items = _P["items"]
    if not items:
        return

    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return

    context = bpy.context
    rv3d = getattr(context, "region_data", None)
    if rv3d is None:
        return
    scene = context.scene

    entry = bpy.data.objects.get(_P["entry_name"])
    if entry is None:
        return
    # 用**播放起点**的矩阵，不是当前矩阵：发射器移动的部分已经通过 host_origin
    # 进了模拟，这里再用当前矩阵就会把同一段位移算两遍。
    rows = _P["ref_rows"] or _entry_matrix_rows(entry)
    r0, r1, r2 = rows

    size_mul = float(getattr(scene, "efx_sim_particle_size", 1.0))
    draw_mode = getattr(scene, "efx_sim_draw_mode", "QUADS")
    blend = getattr(scene, "efx_sim_blend", "AUTO")
    show_vel = bool(getattr(scene, "efx_sim_show_velocity", False))

    right, up = _camera_axes(rv3d)

    # 按混合模式分桶：BILLBOARD3D 的 blendMode 是**逐属性**的（0=Alpha 1=Add），
    # 同一 entry 内理论上一致，但分桶几乎不要钱，还能让「AUTO」如实反映文件。
    buckets = {"ALPHA": ([], []), "ADDITIVE": ([], [])}
    points = []
    point_colors = []
    lines = []
    line_colors = []

    def _bucket_of(it):
        if blend == "AUTO":
            return buckets.get(it.blend) or buckets["ALPHA"]
        return buckets[blend]

    def _world(v):
        """游戏坐标 → 世界坐标（过参考矩阵）。"""
        bx, by, bz = _to_blender(v)
        return (r0[0] * bx + r0[1] * by + r0[2] * bz + r0[3],
                r1[0] * bx + r1[1] * by + r1[2] * bz + r1[3],
                r2[0] * bx + r2[1] * by + r2[2] * bz + r2[3])

    def _world_dir(v):
        """游戏坐标系的**方向**（不含平移）→ 世界方向。"""
        bx, by, bz = _to_blender(v)
        return (r0[0] * bx + r0[1] * by + r0[2] * bz,
                r1[0] * bx + r1[1] * by + r1[2] * bz,
                r2[0] * bx + r2[1] * by + r2[2] * bz)

    view_dir = _view_direction(rv3d)

    for it in items:
        center = _world(it.pos)
        col = (it.color[0], it.color[1], it.color[2], it.color[3])
        kind = it.kind

        if kind == "RIBBON" and it.points:
            bv, bc = _bucket_of(it)
            _emit_ribbon(bv, bc, it, col, size_mul, _world, view_dir)
        elif kind == "MESH":
            bv, bc = _bucket_of(it)
            _emit_mesh(bv, bc, it, col, size_mul, _world, entry)
        elif draw_mode in ("QUADS", "BOTH"):
            # it.size 是**游戏单位**（BILLBOARD3D 的 width×scale 一类），和位置同一
            # 套换算：÷100。size_mul 只是个人工放大镜，默认 1.0 = 照文件里的尺寸画。
            hw = max(1e-5, size_mul * abs(it.size.x) * _UNIT * 0.5)
            hh = max(1e-5, size_mul * abs(it.size.y) * _UNIT * 0.5)
            if it.axis_u is not None and it.axis_v is not None:
                # PLANE：固定朝向，用属性给的横/纵轴，不朝相机
                qr, qu = _world_dir(it.axis_u), _world_dir(it.axis_v)
            else:
                qr, qu = (_spin(right, up, it.rot) if it.rot else (right, up))
            bv, bc = _bucket_of(it)
            bv.extend(_quad_verts(center, qr, qu, hw, hh))
            bc.extend([col] * 6)

        if draw_mode in ("POINTS", "BOTH") and kind not in ("RIBBON", "MESH"):
            points.append(center)
            point_colors.append(col)
        vel = it.extra.get("vel")
        if show_vel and vel is not None:
            # 速度是「每帧位移」，直接画一帧的长度太短，乘一个可读的倍数
            vx, vy, vz = _to_blender(vel)
            k = 8.0
            lines.append(center)
            lines.append((center[0] + vx * k, center[1] + vy * k, center[2] + vz * k))
            line_colors.extend([col, (col[0], col[1], col[2], 0.0)])

    try:
        shader = _builtin("FLAT_COLOR")
    except Exception:
        return

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)      # 粒子之间不互相遮挡，但仍被场景几何遮挡
    try:
        for mode in ("ALPHA", "ADDITIVE"):
            bv, bc = buckets[mode]
            if not bv:
                continue
            gpu.state.blend_set(mode)
            batch_for_shader(shader, "TRIS", {"pos": bv, "color": bc}).draw(shader)

        overlay = "ADDITIVE" if blend == "ADDITIVE" else "ALPHA"
        if points:
            gpu.state.blend_set(overlay)
            gpu.state.point_size_set(max(1.0, float(
                getattr(scene, "efx_sim_point_px", 4))))
            batch_for_shader(shader, "POINTS",
                             {"pos": points, "color": point_colors}).draw(shader)
        if lines:
            gpu.state.blend_set("ALPHA")     # 速度线是调试叠加层，别被加法混合冲白
            batch_for_shader(shader, "LINES",
                             {"pos": lines, "color": line_colors}).draw(shader)
    except Exception:
        pass
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


#: 本模块注册过的 draw handler。模块级列表即可——不像 uvc_preview 那样需要「跨热
#: 重载按名清理」，因为本模块不往场景里放任何东西，重载后最坏只是叠加层不再刷新，
#: unregister() 会把它们摘干净。
_HANDLERS = []


def _remove_handlers():
    removed = 0
    while _HANDLERS:
        h = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
            removed += 1
        except Exception:
            pass
    _P["handler"] = None
    return removed


def _add_handler():
    _remove_handlers()
    h = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _HANDLERS.append(h)
    _P["handler"] = h
    return h


def _redraw_viewports():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ─────────────────────────────────────────────────────────────────────────────
# 时钟
# ─────────────────────────────────────────────────────────────────────────────

#: 重建后最多快进多少帧。超过就从头播——纯粹是防手滑设了个巨大的 duration
#: 之后每改一个字段都卡一下；正常值（百来帧）远在这个上限之下。
_REBUILD_CATCHUP_MAX = 600


def _rebuild_if_dirty(scene):
    """属性被编辑过 → 用新参数重建，并**快进回原来那一帧**。

    不快进的话，拖一下滑块画面就跳回第 0 帧，调参时根本没法比较前后差异。
    快进是划算的：整个模拟就是个 for 循环，几百帧 × 几百粒子是毫秒级
    （实测 600 粒子 2.1 ms/帧），而且确定性重放保证快进结果与连续播放一致。
    """
    if not _P["dirty"]:
        return
    _P["dirty"] = False
    entry = bpy.data.objects.get(_P["entry_name"])
    if entry is None:
        return
    keep_frame = _P["sim"].frame if _P["sim"] is not None else -1

    sim = build_simulator(entry, scene)
    if sim is None:
        return
    _P["sim"] = sim
    _P["duration"] = _resolve_duration(scene, sim)
    _P["acc"] = 0.0

    if 0 <= keep_frame <= _REBUILD_CATCHUP_MAX:
        try:
            sim.run_to(keep_frame)
        except Exception as exc:
            _P["error"] = str(exc)


def _resolve_duration(scene, sim):
    """「播放一次」多长。0 = 自动（SPAWN 三态里没有停止条件，见 sim/behaviors/spawn.py）。"""
    d = int(getattr(scene, "efx_sim_duration", 0))
    if d > 0:
        return d
    try:
        return sim.suggested_duration()
    except Exception:
        return 180


def _tick(scene):
    """一次定时器滴答：按墙钟推进整数帧。

    倍速不靠改定时器间隔（那会丢整数帧语义），靠浮点累加器：
    0.25 倍速 = 每 4 个 tick 走一帧，2 倍速 = 每 tick 走两帧，
    逐帧乘法递推在任何倍速下都精确。
    """
    _rebuild_if_dirty(scene)
    sim = _P["sim"]
    if sim is None:
        return
    _sync_host_origin(scene)

    now = time.perf_counter()
    dt = now - _P["last_t"]
    _P["last_t"] = now
    if dt <= 0.0 or dt > 0.5:
        dt = min(max(dt, 0.0), 1.0 / 30.0)   # 卡顿/切后台后不要一次补几百帧

    fps = float(getattr(sim.config, "fps", 60))
    speed = float(getattr(scene, "efx_sim_speed", 1.0))
    _P["acc"] += dt * fps * speed

    steps = 0
    while _P["acc"] >= 1.0 and steps < 240:   # 单 tick 步数上限，防卡死
        sim.step()
        _P["acc"] -= 1.0
        steps += 1

        if _P["duration"] > 0 and sim.frame >= _P["duration"]:
            if getattr(scene, "efx_sim_mode", "LOOP") == "LOOP":
                sim.reset()
                _P["acc"] = 0.0
                break
            _P["playing"] = False
            break

    try:
        _P["items"] = sim.build_render()
    except Exception as exc:
        _P["error"] = str(exc)
        _P["items"] = []


# ─────────────────────────────────────────────────────────────────────────────
# 算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_OT_sim_play(Operator):
    """开始播放当前 Entry 的粒子模拟（自带时钟，不动时间轴）"""

    bl_idname = "efx.sim_play"
    bl_label = "Play EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _resolve_entry(context.active_object) is not None and not is_active()

    def invoke(self, context, event):
        entry = _resolve_entry(context.active_object)
        if entry is None:
            self.report({"WARNING"}, T("sim.err_no_entry"))
            return {"CANCELLED"}

        sim = build_simulator(entry, context.scene)
        if sim is None:
            self.report({"ERROR"}, _P["error"] or T("sim.err_build"))
            return {"CANCELLED"}

        _P["sim"] = sim
        _P["entry_name"] = entry.name
        _P["duration"] = _resolve_duration(context.scene, sim)
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["items"] = []
        _P["dirty"] = False
        _P["playing"] = True
        _P["ref_rows"] = _entry_matrix_rows(entry)
        _P["mesh_cache"] = {}

        _add_handler()
        wm = context.window_manager
        # 固定高频 tick；倍速由累加器处理，不改这个间隔
        _P["timer"] = wm.event_timer_add(1.0 / 120.0, window=context.window)
        wm.modal_handler_add(self)

        if sim.unsupported:
            self.report({"INFO"}, T("sim.unsupported_n").format(len(sim.unsupported)))
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not is_active():
            return self._finish(context)
        if event.type == "TIMER":
            if _P["playing"]:
                _tick(context.scene)
                _redraw_viewports()
        return {"PASS_THROUGH"}       # 不吞事件：播放时照样能转视角、改参数

    def _finish(self, context):
        wm = context.window_manager
        if _P["timer"] is not None:
            try:
                wm.event_timer_remove(_P["timer"])
            except Exception:
                pass
            _P["timer"] = None
        _remove_handlers()
        _P["playing"] = False
        _P["items"] = []
        _P["mesh_cache"] = {}
        _redraw_viewports()
        return {"FINISHED"}

    def cancel(self, context):
        self._finish(context)


class EFX_OT_sim_stop(Operator):
    """停止播放并清除叠加层"""

    bl_idname = "efx.sim_stop"
    bl_label = "Stop EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        # 只摘 handler：modal 下一个 tick 看到 is_active()==False 就自己收尾
        _remove_handlers()
        _P["playing"] = False
        _P["items"] = []
        _P["mesh_cache"] = {}
        _redraw_viewports()
        return {"FINISHED"}


class EFX_OT_sim_pause(Operator):
    """暂停 / 继续（暂停时仍可转视角——渲染 pass 与模拟解耦）"""

    bl_idname = "efx.sim_pause"
    bl_label = "Pause EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        _P["playing"] = not _P["playing"]
        _P["last_t"] = time.perf_counter()
        return {"FINISHED"}


class EFX_OT_sim_restart(Operator):
    """从第 0 帧重放（同一种子 → 逐帧完全复现）"""

    bl_idname = "efx.sim_restart"
    bl_label = "Restart EFX Simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        # 直接重建，不走 _rebuild_if_dirty 的「快进回原帧」——重放的语义就是回到开头
        entry = bpy.data.objects.get(_P["entry_name"])
        if entry is None:
            return {"CANCELLED"}
        sim = build_simulator(entry, context.scene)
        if sim is None:
            self.report({"ERROR"}, _P["error"] or T("sim.err_build"))
            return {"CANCELLED"}
        _P["sim"] = sim
        _P["duration"] = _resolve_duration(context.scene, sim)
        _P["dirty"] = False
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["items"] = []
        _P["playing"] = True
        _P["ref_rows"] = _entry_matrix_rows(entry)
        _P["mesh_cache"] = {}
        _redraw_viewports()
        return {"FINISHED"}


class EFX_OT_sim_step(Operator):
    """单步：暂停状态下推进一帧，用来逐帧对拍"""

    bl_idname = "efx.sim_step"
    bl_label = "Step One Frame"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active() and not _P["playing"]

    def execute(self, context):
        sim = _P["sim"]
        if sim is None:
            return {"CANCELLED"}
        _rebuild_if_dirty(context.scene)
        _sync_host_origin(context.scene)
        sim.step()
        try:
            _P["items"] = sim.build_render()
        except Exception:
            _P["items"] = []
        _redraw_viewports()
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 面板
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_sim(Panel):
    """粒子模拟播放器。独立于 EFX_PT_efx_preview 那一族——那边是「进入/退出会话」
    模型，这边是「播放器」模型，混在一起只会互相干扰。"""

    bl_idname = "EFX_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Particle Simulation"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        sim = _P["sim"]
        active = is_active()

        entry = _resolve_entry(context.active_object)
        if entry is None and not active:
            layout.label(text=T("sim.pick_entry"), icon="INFO")
            return

        # ── 走带 ─────────────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.4
        if not active:
            row.operator("efx.sim_play", text=T("sim.play"), icon="PLAY")
        else:
            row.operator("efx.sim_pause",
                         text=T("sim.pause") if _P["playing"] else T("sim.resume"),
                         icon="PAUSE" if _P["playing"] else "PLAY")
            row.operator("efx.sim_restart", text="", icon="LOOP_BACK")
            sub = row.row(align=True)
            sub.enabled = not _P["playing"]
            sub.operator("efx.sim_step", text="", icon="FRAME_NEXT")
            row.operator("efx.sim_stop", text="", icon="X")

        if active and sim is not None:
            box = layout.box()
            col = box.column(align=True)
            col.label(text=T("sim.frame").format(sim.frame, _P["duration"]),
                      icon="TIME")
            col.label(text=T("sim.alive").format(len(sim.particles),
                                                 sim.em.spawned_total),
                      icon="PARTICLES")
            if _P["error"]:
                col.label(text=_P["error"], icon="ERROR")

        # ── 播放设置 ─────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("sim.playback"), icon="PLAY")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_mode", text="")
        col.prop(scene, "efx_sim_speed")
        col.prop(scene, "efx_sim_duration")
        col.prop(scene, "efx_sim_seed")

        # ── 显示 ─────────────────────────────────────────────────────────────
        box = layout.box()
        box.label(text=T("sim.display"), icon="SHADING_RENDERED")
        col = box.column(align=True)
        col.prop(scene, "efx_sim_draw_mode", text="")
        col.prop(scene, "efx_sim_blend", text="")
        col.prop(scene, "efx_sim_particle_size")
        if getattr(scene, "efx_sim_draw_mode", "QUADS") in ("POINTS", "BOTH"):
            col.prop(scene, "efx_sim_point_px")
        col.prop(scene, "efx_sim_show_velocity")

        # ── 未模拟的属性：如实列出，预览不静默撒谎 ───────────────────────────
        if sim is not None and sim.unsupported:
            box = layout.box()
            box.label(text=T("sim.unsupported"), icon="ERROR")
            col = box.column(align=True)
            col.scale_y = 0.7
            for _h, name in sim.unsupported[:8]:
                col.label(text="· " + (name or "?"))
            if len(sim.unsupported) > 8:
                col.label(text=T("sim.and_more").format(len(sim.unsupported) - 8))


class EFX_PT_sim_unknowns(Panel):
    """待标定开关。

    这些不是「偏好设置」，是**还没实测确定的语义**。每一项都对应
    efx_format/sim/config.py::UNKNOWNS 里的一条。标定方式就是切开关对拍，
    定下来之后把 sim/config.py 的默认值改掉。
    """

    bl_idname = "EFX_PT_sim_unknowns"
    bl_parent_id = "EFX_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "Calibration"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text=T("sim.calib_hint"), icon="INFO")
        col = layout.column(align=True)
        col.prop(scene, "efx_sim_jitter_mode")
        col.prop(scene, "efx_sim_es3d_range_mode")
        col.prop(scene, "efx_sim_life_model")
        col.prop(scene, "efx_sim_a0_sample")
        col.prop(scene, "efx_sim_timl_mode")
        col.prop(scene, "efx_sim_timl_interp")
        col.prop(scene, "efx_sim_rot_order")
        col.prop(scene, "efx_sim_age_during_delay")
        layout.operator("efx.sim_restart", text=T("sim.reapply"), icon="FILE_REFRESH")


# ─────────────────────────────────────────────────────────────────────────────
# 注册
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = (
    EFX_OT_sim_play,
    EFX_OT_sim_stop,
    EFX_OT_sim_pause,
    EFX_OT_sim_restart,
    EFX_OT_sim_step,
    EFX_PT_sim,
    EFX_PT_sim_unknowns,
)


def _on_knob_changed(self, context):
    """标定开关变了 → 标脏，下个 tick 用新配置重建。"""
    _P["dirty"] = True


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene

    # ── 播放 ─────────────────────────────────────────────────────────────────
    S.efx_sim_mode = EnumProperty(
        name="Mode",
        items=[("ONCE", "Play Once", "Stop at the end of one cycle"),
               ("LOOP", "Loop", "Restart from frame 0 at the end of each cycle")],
        default="LOOP")
    S.efx_sim_speed = FloatProperty(
        name="Speed", default=1.0, min=0.05, max=4.0, soft_min=0.1, soft_max=2.0,
        description="Playback speed multiplier (whole EFX frames are preserved at any speed)")
    S.efx_sim_duration = IntProperty(
        name="Duration", default=0, min=0, soft_max=600,
        description="Frames per cycle; 0 = auto (start delay + one burst cycle + one particle life). "
                    "EFX emitters have no documented stop condition, so this is the player's call")
    S.efx_sim_seed = IntProperty(
        name="Seed", default=0, update=_on_knob_changed,
        description="Base random seed; same seed replays identically")

    # ── 显示 ─────────────────────────────────────────────────────────────────
    S.efx_sim_draw_mode = EnumProperty(
        name="Draw",
        items=[("QUADS", "Billboards", "Camera-facing quads sized by particle scale"),
               ("POINTS", "Points", "One pixel-sized dot per particle (fastest)"),
               ("BOTH", "Both", "Quads plus centre dots")],
        default="QUADS")
    S.efx_sim_blend = EnumProperty(
        name="Blend",
        items=[("AUTO", "From file", "Use each renderer's own blendMode "
                                     "(BILLBOARD3D: 0=Alpha, 1=Additive)"),
               ("ADDITIVE", "Force additive", "Override everything to additive"),
               ("ALPHA", "Force alpha", "Override everything to plain alpha")],
        default="AUTO")
    S.efx_sim_particle_size = FloatProperty(
        name="Size x", default=1.0, min=0.01, max=20.0, soft_min=0.25, soft_max=4.0,
        description="Magnifier on top of the size read from the file "
                    "(BILLBOARD3D width/height x scale, in game units). 1.0 = as authored")
    S.efx_sim_point_px = IntProperty(name="Point px", default=4, min=1, max=32)
    S.efx_sim_show_velocity = BoolProperty(
        name="Velocity lines", default=False,
        description="Draw each particle's per-frame velocity as a fading line")

    # ── 待标定（见 efx_format/sim/config.py::UNKNOWNS）───────────────────────
    S.efx_sim_jitter_mode = EnumProperty(
        name="Jitter", update=_on_knob_changed,
        items=[("onesided", "base + U[0, a]", "Confirmed: jitter is added on top of the static value"),
               ("symmetric", "base + U[-a, a]", "Symmetric around the static value"),
               ("gaussian", "base + N(0, a/2)", "Gaussian instead of uniform")],
        default="onesided")
    S.efx_sim_es3d_range_mode = EnumProperty(
        name="rangeXYZ", update=_on_knob_changed,
        items=[("minmax", "Min / Max", "Per the official TimelineParam names RangeMinX/RangeMaxX/..."),
               ("offset_size", "Offset / Size", "Alternative reading (timl_tracks.py comment)")],
        default="minmax")
    S.efx_sim_life_model = EnumProperty(
        name="Lifetime", update=_on_knob_changed,
        items=[("sum", "fadeIn + duration + fadeOut", "Total life is the sum of all three"),
               ("duration", "duration is the total", "Fades are carved out of duration")],
        default="sum")
    S.efx_sim_a0_sample = EnumProperty(
        name="TIML A0", update=_on_knob_changed,
        items=[("spawn", "Frozen at spawn", "Particle-level fields read A0 at their birth frame"),
               ("current", "Follows emitter time", "Particle-level fields re-read A0 every frame")],
        default="spawn")
    S.efx_sim_timl_mode = EnumProperty(
        name="TIML value", update=_on_knob_changed,
        items=[("replace", "Replaces static", "Keyframe value replaces the static field"),
               ("multiply", "Multiplies static", "Keyframe value scales the static field")],
        default="replace")
    S.efx_sim_timl_interp = EnumProperty(
        name="Interpolation", update=_on_knob_changed,
        items=[("native", "Per keyframe", "Use each keyframe's transition (QUAD/CUBIC fall back to linear)"),
               ("linear", "Force linear", ""),
               ("constant", "Force hold", "")],
        default="native")
    S.efx_sim_rot_order = EnumProperty(
        name="Rotation order", update=_on_knob_changed,
        items=[("forward", "First listed applies first", ""),
               ("reverse", "Last listed applies first", "")],
        default="forward")
    S.efx_sim_age_during_delay = BoolProperty(
        name="Age during spawn delay", default=False, update=_on_knob_changed,
        description="Whether particleSpawnDelay still advances the particle's age")


def unregister():
    _remove_handlers()
    _P["playing"] = False
    _P["sim"] = None
    _P["items"] = []

    for attr in (
        "efx_sim_mode", "efx_sim_speed", "efx_sim_duration", "efx_sim_seed",
        "efx_sim_draw_mode", "efx_sim_blend", "efx_sim_particle_size",
        "efx_sim_point_px", "efx_sim_show_velocity",
        "efx_sim_jitter_mode", "efx_sim_es3d_range_mode", "efx_sim_life_model",
        "efx_sim_a0_sample", "efx_sim_timl_mode", "efx_sim_timl_interp",
        "efx_sim_rot_order", "efx_sim_age_during_delay",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
