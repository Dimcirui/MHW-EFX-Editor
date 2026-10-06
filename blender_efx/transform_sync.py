"""将 TRANSFORM3D 与 PARENTOPTIONS 映射为 Entry 的视口变换。

维护约束：
- TRANSFORM3D FLOAT6 的基础值使用索引 0/2/4，按分量写入 Entry 的 location /
  rotation_euler / scale，rotation_mode 由 rotationOrder 决定。导出只读字段。
- 用户确认的 Entry 变换经 ``reconcile_entry`` 反写进字段；判断哪一边变了靠 Entry 上的
  同步基准，基准随撤销快照一起恢复，所以撤销 / 重做后对账即可恢复一致。
- 骨骼只通过 Copy Location 叠加当前位置；无效绑定必须移除约束。TIML 句柄与 Entry 用
  同一套通道换算，摆位时一并同步。
"""

from math import degrees, radians

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Euler, Vector

from . import root_collection as _rc


def _t3d_hash() -> int:
    from ..efx_format.hashes import TRANSFORM3D
    return TRANSFORM3D


def _parentopts_hash() -> int:
    from ..efx_format.hashes import PARENTOPTIONS
    return PARENTOPTIONS


# ── 坐标映射（game fixed 三元组 → blender 三元组）─────────────────────────────

def game_loc_to_blender(gx, gy, gz):
    """平移：/100 + 轴 (X,Y,Z)→(X,-Z,Y)。"""
    return (gx / 100.0, -gz / 100.0, gy / 100.0)


def game_rot_to_blender(gx, gy, gz):
    """将旋转分量换算为 Blender 弧度坐标。"""
    return (radians(gx), radians(-gz), radians(gy))


def game_scale_to_blender(gx, gy, gz):
    """缩放：Y/Z 互换、不除 100。"""
    return (gx, gz, gy)


# 旋转除交换分量外还要换算组合顺序，见 blender_rotation_mode。

#: rotationOrder 缺省值 4（ZXY）。
DEFAULT_ROT_ORDER = "ZXY"


def rot_order_of(attribute):
    """读属性的 rotationOrder 并换成顺序串；缺字段时返回默认顺序。

    取值表与模拟层共用，TRANSFORM3D、MESH 等同一套；VELOCITY3D 的 rotOrder 不适用。
    """
    from ..efx_format.sim.vecmath import ROT_ORDER_TRANSFORM, rot_order_name
    try:
        for it in attribute.efx_block.field_items:
            if it.ori_name == "rotationOrder":
                return rot_order_name(it.int_value, ROT_ORDER_TRANSFORM)
    except Exception:
        pass
    return DEFAULT_ROT_ORDER


def _game_rot_matrix(gx, gy, gz, order=DEFAULT_ROT_ORDER):
    """按顺序串构建游戏空间旋转矩阵；先写的轴先作用，ZXY 即 ``Ry @ Rx @ Rz``。"""
    ang = {"X": gx, "Y": gy, "Z": gz}
    m = Matrix.Identity(3)
    for axis in order:
        m = Matrix.Rotation(radians(ang[axis]), 3, axis) @ m
    return m


def _g2b_basis():
    """游戏→Blender 的基变换矩阵 M = Rx(+90°)（游戏 Y-up → Blender Z-up）。"""
    return Matrix.Rotation(radians(90), 3, 'X')


def game_rot_matrix_blender(gx, gy, gz, order=DEFAULT_ROT_ORDER):
    """无骨骼基准时：游戏旋转换到 Blender 世界 = M · R_game · M⁻¹，返回 4x4。"""
    M = _g2b_basis()
    R = _game_rot_matrix(gx, gy, gz, order)
    return (M @ R @ M.inverted()).to_4x4()


def _fixed3(float6_value):
    """从 FLOAT6 取基础三元组（idx 0/2/4）。"""
    v = list(float6_value)
    return (v[0], v[2], v[4])


# ── 取属性/字段 ─────────────────────────────────────────────────────────────────

def _iter_entry_attributes(entry_obj, children_map=None):
    """枚举 Entry 属性；批量调用应传入预建映射。"""
    if children_map is not None:
        yield from children_map.get(entry_obj, [])
        return
    for blk in bpy.data.objects:
        if blk.parent is entry_obj and blk.get("~TYPE") == "EFX_ATTRIBUTE":
            yield blk


def build_entry_attr_map(root_obj):
    """按父对象建立属性映射，供批量变换同步复用。"""
    out = {}
    for blk in bpy.data.objects:
        if blk.get("~TYPE") == "EFX_ATTRIBUTE":
            p = blk.parent
            if p is not None:
                out.setdefault(p, []).append(blk)
    return out


def _attribute_of_type(entry_obj, type_hash, children_map=None):
    """返回 entry 下第一个指定 type_hash 的 EFX_ATTRIBUTE（无则 None）。"""
    for blk in _iter_entry_attributes(entry_obj, children_map):
        try:
            if int(blk.efx_block.type_hash_str) == type_hash:
                return blk
        except Exception:
            continue
    return None


def _entry_joint_no(entry_obj, children_map=None):
    """读 entry 的 PARENTOPTIONS.jointNo（int）；无 PARENTOPTIONS/字段 → None。"""
    po = _attribute_of_type(entry_obj, _parentopts_hash(), children_map)
    if po is None:
        return None
    try:
        for it in po.efx_block.field_items:
            if it.ori_name == "jointNo":
                return int(it.int_value)
    except Exception:
        pass
    return None


#: 游戏轴到 Blender 轴的置换，与平移、缩放的分量交换一致。
_G2B_AXIS = {"X": "X", "Y": "Z", "Z": "Y"}


def blender_rotation_mode(order):
    """游戏旋转顺序串 → 逐分量等价的 Blender rotation_mode。

    配合 ``game_rot_to_blender`` 的分量，Euler 与 ``M·R_game·M⁻¹`` 完全相同，
    所以 Entry 和 TIML 句柄可以直接用 rotation_euler 表示游戏旋转。
    """
    return "".join(_G2B_AXIS[c] for c in order)


def t3d_channels(t3d_attribute):
    """返回 TRANSFORM3D 静态值对应的 (location, rotation_mode, rotation_euler, scale)。

    读取失败返回 None；缺少的分组取单位值。
    """
    vals = {}
    try:
        for it in t3d_attribute.efx_block.field_items:
            if it.ori_name in ("translate", "rotate", "resize") and it.data_type == "FLOAT6":
                vals[it.ori_name] = _fixed3(it.float6_value)
    except Exception:
        return None
    loc = game_loc_to_blender(*vals.get("translate", (0.0, 0.0, 0.0)))
    rot = game_rot_to_blender(*vals.get("rotate", (0.0, 0.0, 0.0)))
    scl = game_scale_to_blender(*vals.get("resize", (1.0, 1.0, 1.0)))
    return loc, blender_rotation_mode(rot_order_of(t3d_attribute)), rot, scl


def channels_matrix(ch):
    """把 ``t3d_channels`` 的结果组成 4x4 矩阵。"""
    loc, mode, rot, scl = ch
    return (Matrix.Translation(Vector(loc)) @ Euler(rot, mode).to_matrix().to_4x4()
            @ Matrix.Diagonal(Vector((scl[0], scl[1], scl[2], 1.0))))


_CHANNEL_PROPS = ("location", "rotation_euler", "scale")


def _write_channels(obj, ch, skip=frozenset()):
    """写入 Object 的变换通道；``skip`` 中的 (data_path, index) 不写。"""
    loc, mode, rot, scl = ch
    # 先切换模式再写值：切换 rotation_mode 时 Blender 会换算旧值。
    if obj.rotation_mode != mode:
        obj.rotation_mode = mode
    for prop, val in zip(_CHANNEL_PROPS, (loc, rot, scl)):
        target = getattr(obj, prop)
        for i in range(3):
            # 相同的值也不重写：任何写入都会触发 depsgraph 更新，进而重新对账。
            if (prop, i) not in skip and not _close(target[i], val[i]):
                target[i] = val[i]


def _close(a, b):
    """按 float32 精度判等。"""
    return abs(a - b) <= 1e-5 * max(1.0, abs(a), abs(b))


def _read_channels(obj):
    return (tuple(obj.location), obj.rotation_mode, tuple(obj.rotation_euler), tuple(obj.scale))


def _channels_close(a, b):
    return a[1] == b[1] and all(_close(x, y) for i in (0, 2, 3) for x, y in zip(a[i], b[i]))


# ── 反向换算（Blender 通道 → 游戏三元组），与正向互为精确逆 ─────────────────────

def blender_loc_to_game(b):
    return (b[0] * 100.0, b[2] * 100.0, -b[1] * 100.0)


def blender_rot_to_game(e):
    return (degrees(e[0]), degrees(e[2]), -degrees(e[1]))


def blender_scale_to_game(s):
    return (s[0], s[2], s[1])


#: 游戏分量 x/y/z 对应的 Blender 通道下标；平移、旋转、缩放相同。
_G2B_INDEX = (0, 2, 1)

# ── 同步基准 ──────────────────────────────────────────────────────────────────
# 最近一次摆位或反写后的通道值。它是对象自定义属性，会进入撤销快照。

_SYNC_KEY = "~t3d_sync"
_SYNC_MODE_KEY = "~t3d_sync_mode"


def _store_snapshot(obj):
    loc, mode, rot, scl = _read_channels(obj)
    obj[_SYNC_KEY] = [*loc, *rot, *scl]
    obj[_SYNC_MODE_KEY] = mode


def _snapshot(obj):
    v = obj.get(_SYNC_KEY)
    mode = obj.get(_SYNC_MODE_KEY)
    if v is None or mode is None or len(v) != 9:
        return None
    v = list(v)
    return (tuple(v[0:3]), str(mode), tuple(v[3:6]), tuple(v[6:9]))


# ── 骨骼基准 ─────────────────────────────────────────────────────────────────

# 视为"无绑定骨骼 / 原点基准"的 jointNo 哨兵值。
_BONE_NONE_SENTINELS = (-1, 255)

#: entry 上骨骼跟随约束的固定名字（增/改/删都按这个名字找，避免重复叠加）。
_BONE_FOLLOW_CONSTRAINT_NAME = "EFX_BoneFollow"


def _resolve_bone_name(armature_obj, jointNo):
    """校验 jointNo 对应的骨骼是否存在，返回骨骼名；否则 None（→ 以世界原点为基准）。

    None 情形：armature_obj 为空/非骨架、jointNo 为 None/-1/255、骨架中无对应骨骼。
    """
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return None
    if jointNo is None or jointNo in _BONE_NONE_SENTINELS or jointNo < 0:
        return None
    bone_name = f"MhBone_{jointNo:03d}"
    if armature_obj.data.bones.get(bone_name) is None:
        return None
    return bone_name


def _sync_bone_follow_constraint(entry_obj, armature_obj, jointNo) -> bool:
    """同步当前 pose 的 Copy Location 约束。

    约束仅叠加位置，保留 Entry 自身的旋转和缩放；无效绑定必须清除已有约束。
    """
    bone_name = _resolve_bone_name(armature_obj, jointNo)
    con = entry_obj.constraints.get(_BONE_FOLLOW_CONSTRAINT_NAME)
    if bone_name is None:
        if con is not None:
            entry_obj.constraints.remove(con)
        return False
    if con is None:
        con = entry_obj.constraints.new(type="COPY_LOCATION")
        con.name = _BONE_FOLLOW_CONSTRAINT_NAME
    con.target = armature_obj
    con.subtarget = bone_name
    con.head_tail = 0.0
    con.use_offset = True
    con.use_x = con.use_y = con.use_z = True
    con.target_space = "WORLD"
    con.owner_space = "WORLD"
    con.influence = 1.0
    return True


# ── TIML 句柄 ────────────────────────────────────────────────────────────────

def _animated_channels(handle):
    """句柄上被 F 曲线驱动的 (data_path, index)。"""
    out = set()
    ad = handle.animation_data
    act = ad.action if ad is not None else None
    if act is None:
        return out
    try:
        from .timl_edit import _act_fcurves
        for fc in _act_fcurves(act, handle):
            if fc.data_path in _CHANNEL_PROPS:
                out.add((fc.data_path, fc.array_index))
    except Exception:
        pass
    return out


def _sync_timl_handle(handle, ch):
    """让句柄世界变换 = Entry 基准 × TIML 绝对值。

    TIML 的变换轨道存绝对值，句柄却是 Entry 子对象；父逆矩阵抵消 Entry 的静态部分，
    没有轨道的通道填静态值，否则只动一个轴时其余轴会回到原点。
    """
    _write_channels(handle, ch, skip=_animated_channels(handle))
    handle.matrix_parent_inverse = channels_matrix(ch).inverted_safe()


def sync_entry_timl_handle(entry_obj, handle) -> bool:
    """只按 Entry 的 TRANSFORM3D 同步句柄，不改 Entry 本身和骨骼约束。"""
    t3d = _attribute_of_type(entry_obj, _t3d_hash())
    ch = t3d_channels(t3d) if t3d is not None else None
    if ch is None:
        return False
    _sync_timl_handle(handle, ch)
    return True


def _timl_handle_map():
    """按父 Entry 建立 TIML 句柄映射，批量同步时只扫一次全场景。"""
    out = {}
    for o in bpy.data.objects:
        if o.get("~TYPE") == "EFX_TIML" and o.parent is not None:
            out.setdefault(o.parent, o)
    return out


# ── 应用到单个 entry ──────────────────────────────────────────────────────────

_NO_HANDLE = object()


def apply_entry_transform(entry_obj, armature_obj=None, children_map=None,
                          timl_handle=_NO_HANDLE) -> bool:
    """按 TRANSFORM3D 写入 Entry 的变换通道，并同步骨骼约束和 TIML 句柄。

    批量调用应传入 ``children_map`` 和 ``timl_handle``（无句柄时传 None），避免逐个扫场景。
    """
    try:
        t3d = _attribute_of_type(entry_obj, _t3d_hash(), children_map)
        if t3d is None:
            return False
        ch = t3d_channels(t3d)
        if ch is None:
            return False
        _sync_bone_follow_constraint(
            entry_obj, armature_obj, _entry_joint_no(entry_obj, children_map))
        _write_channels(entry_obj, ch)
        _store_snapshot(entry_obj)
        if timl_handle is _NO_HANDLE:
            from .io_tree import find_timl_handle
            timl_handle = find_timl_handle(entry_obj)
        animated = set()
        if timl_handle is not None:
            animated = _animated_channels(timl_handle)
            _sync_timl_handle(timl_handle, ch)
        _sync_locks(entry_obj, animated)
        return True
    except Exception:
        return False


def _sync_locks(entry_obj, animated):
    """锁住由 TIML 轨道驱动的分量：游戏里这些分量取曲线值，静态值不生效。"""
    for prop, lock in (("location", "lock_location"), ("rotation_euler", "lock_rotation"),
                       ("scale", "lock_scale")):
        arr = getattr(entry_obj, lock)
        for i in range(3):
            want = (prop, i) in animated
            if arr[i] != want:
                arr[i] = want


def _iter_root_bodies(root_obj):
    yield from _rc.collect_top_level(root_obj, "EFX_ENTRY")


def place_single_entry(entry_obj, armature_obj=None) -> bool:
    """同步单个 Entry，并使结果立即可被后续读取。对账写字段期间由对账统一摆位。"""
    if _RECONCILING:
        return False
    ok = apply_entry_transform(entry_obj, armature_obj)
    bpy.context.view_layer.update()
    return ok


def sync_all_transform3d(root_obj, armature_obj=None) -> int:
    """同步根下全部 Entry，返回成功处理数。"""
    children_map = build_entry_attr_map(root_obj)
    handles = _timl_handle_map()
    n = 0
    for body in _iter_root_bodies(root_obj):
        if apply_entry_transform(body, armature_obj, children_map=children_map,
                                 timl_handle=handles.get(body)):
            n += 1
    bpy.context.view_layer.update()
    return n


# ── 反写对账 ──────────────────────────────────────────────────────────────────

_RECONCILING = False
_WRITE_DECIMALS = 4
_EULER_MODES = frozenset(("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"))
_T3D_FIELD_OF = (("translate", "location", 0, blender_loc_to_game),
                 ("rotate", "rotation_euler", 2, blender_rot_to_game),
                 ("resize", "scale", 3, blender_scale_to_game))


def _write_back(t3d, cur, base, animated):
    """把用户改动过的分量写进 TRANSFORM3D；只写与基准不同的分量，避免浮点漂移。"""
    items = {it.ori_name: it for it in t3d.efx_block.field_items}
    for field, prop, ci, to_game in _T3D_FIELD_OF:
        item = items.get(field)
        if item is None or item.data_type != "FLOAT6":
            continue
        game = to_game(cur[ci])
        v = list(item.float6_value)
        changed = False
        for k in range(3):
            bi = _G2B_INDEX[k]
            if (prop, bi) in animated or _close(cur[ci][bi], base[ci][bi]):
                continue
            # Blender 以 float32 存米和弧度，换算回厘米和度会带出 444.99997 这类尾数。
            v[2 * k] = round(game[k], _WRITE_DECIMALS)
            changed = True
        if changed:
            item.float6_value = v
    if cur[1] != base[1]:
        from ..efx_format.sim.vecmath import ROT_ORDER_TRANSFORM
        order = blender_rotation_mode(cur[1])   # 轴置换是对合，反向用同一个函数
        item = items.get("rotationOrder")
        if item is not None and order in ROT_ORDER_TRANSFORM:
            item.int_value = ROT_ORDER_TRANSFORM.index(order)


def reconcile_entry(entry_obj, armature_obj=None, writeback=True, children_map=None,
                    timl_handle=_NO_HANDLE) -> bool:
    """按「当前通道 / 同步基准 / 字段」三方对账，返回是否改动了字段或摆位。

    通道偏离基准说明用户动过 Entry，写回字段；否则以字段为准重新摆位。没有
    TRANSFORM3D 的 Entry 不处理。四元数等非 Euler 模式不写回，按字段恢复。
    rotation_mode 换成另一种 Euler 顺序时写进 rotationOrder。
    """
    global _RECONCILING
    t3d = _attribute_of_type(entry_obj, _t3d_hash(), children_map)
    if t3d is None:
        return False
    exp = t3d_channels(t3d)
    if exp is None:
        return False
    cur = _read_channels(entry_obj)
    base = _snapshot(entry_obj)
    wrote = False
    # 没有基准（旧文件或刚建的对象）时无法判断哪边变了，以字段为准。
    if (writeback and base is not None and cur[1] in _EULER_MODES
            and not _channels_close(cur, base)):
        if timl_handle is _NO_HANDLE:
            from .io_tree import find_timl_handle
            timl_handle = find_timl_handle(entry_obj)
        animated = _animated_channels(timl_handle) if timl_handle is not None else set()
        _RECONCILING = True
        try:
            _write_back(t3d, cur, base, animated)
        finally:
            _RECONCILING = False
        wrote = True
        exp = t3d_channels(t3d)
    if not wrote and base is not None and _channels_close(cur, exp):
        return False
    apply_entry_transform(entry_obj, armature_obj, children_map, timl_handle)
    if wrote:
        try:
            from . import mesh_align
            mesh_align.realign_entry_if_active(entry_obj)
        except Exception:
            pass
    return True


def _writeback_enabled(scene=None):
    scene = scene or bpy.context.scene
    return bool(getattr(scene, "efx_t3d_writeback", True)) if scene else False


def _reconcile_all(writeback):
    """对账全部 EFX 根下的 Entry。"""
    scene = bpy.context.scene
    armature = getattr(scene, "efx_armature", None) if scene else None
    handles = _timl_handle_map()
    for root in _rc.all_root_collections():
        children_map = build_entry_attr_map(root)
        for body in _iter_root_bodies(root):
            try:
                reconcile_entry(body, armature, writeback, children_map, handles.get(body))
            except Exception:
                pass


# ── 触发：变换确认后、N 面板输入后、撤销 / 重做后 ───────────────────────────────

_pending = set()
#: 无 ``Window.modal_operators`` 的版本里，通道连续稳定多少次轮询后视为已确认。
_LEGACY_STABLE_POLLS = 5
_POLL_INTERVAL = 0.1
_legacy_seen = {}


def _transform_running():
    """是否有变换操作仍在进行；版本不支持判断时返回 None。"""
    try:
        windows = bpy.context.window_manager.windows
    except Exception:
        return None
    for w in windows:
        ops = getattr(w, "modal_operators", None)
        if ops is None:
            return None
        if any(op.bl_idname.startswith("TRANSFORM_OT") for op in ops):
            return True
    return False


def _flush_pending():
    """计时器回调：变换结束后对账待处理的 Entry；仍在拖动时继续等待。"""
    if not _pending:
        return None
    running = _transform_running()
    names = list(_pending)
    if running is None:
        # 旧版本：通道连续数次轮询不变即视为确认；取消时由对账按基准自动还原。
        ready = []
        for n in names:
            o = bpy.data.objects.get(n)
            ch = _read_channels(o) if o is not None else None
            prev, count = _legacy_seen.get(n, (None, 0))
            stable = ch is not None and prev is not None and _channels_close(ch, prev)
            count = count + 1 if stable else 0
            _legacy_seen[n] = (ch, count)
            if ch is None or count >= _LEGACY_STABLE_POLLS:
                ready.append(n)
        names = ready
    elif running:
        return _POLL_INTERVAL
    scene = bpy.context.scene
    armature = getattr(scene, "efx_armature", None) if scene else None
    for n in names:
        _pending.discard(n)
        _legacy_seen.pop(n, None)
        o = bpy.data.objects.get(n)
        if o is not None:
            try:
                reconcile_entry(o, armature, _writeback_enabled(scene))
            except Exception:
                pass
    return _POLL_INTERVAL if _pending else None


def _animation_playing():
    try:
        return any(s.is_animation_playing for s in bpy.data.screens)
    except Exception:
        return False


@persistent
def _on_depsgraph(scene, depsgraph):
    if _RECONCILING or not _writeback_enabled(scene) or _animation_playing():
        return
    added = False
    for u in depsgraph.updates:
        if not u.is_updated_transform or not isinstance(u.id, bpy.types.Object):
            continue
        o = u.id.original
        if o.get("~TYPE") == "EFX_ENTRY" and o.name not in _pending:
            _pending.add(o.name)
            added = True
    if added and not bpy.app.timers.is_registered(_flush_pending):
        bpy.app.timers.register(_flush_pending, first_interval=_POLL_INTERVAL)


@persistent
def _on_undo_redo(*_args):
    # 撤销快照里通道、基准和字段各自恢复；对账让三者重新一致。
    _pending.clear()
    try:
        _reconcile_all(_writeback_enabled())
    except Exception:
        pass


# ── 算子：刷新特效体位置 ──────────────────────────────────────────────────────

class EFX_OT_sync_transform(bpy.types.Operator):
    """按 TRANSFORM3D 和骨骼刷新 Entry 视口位置。"""

    bl_idname      = "efx.sync_transform_to_view"
    bl_label       = "Refresh Entry Positions"
    bl_description = ("Recompute every entry's position from its TRANSFORM3D and bound bone "
                      "(PARENTOPTIONS.bone_lim) using the selected armature (visual only, not written to file)")
    bl_options     = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from .add_ops import get_active_efx_root
            root = get_active_efx_root(context)
        except Exception:
            root = None
        if root is None:
            root = _rc.find_root_collection(context.active_object)
        if root is None:
            self.report({"ERROR"}, "EFX_ROOT not found (select an Active EFX or an EFX object)")
            return {"CANCELLED"}
        armature = getattr(context.scene, "efx_armature", None)
        n = sync_all_transform3d(root, armature)
        self.report({"INFO"}, f"Refreshed {n} entry position(s)")
        return {"FINISHED"}


# ── 视口点选：只有 Entry 可点 ────────────────────────────────────────────────

# 与 Entry 重叠的辅助 empty 尺寸为 0，视口点击只命中 Entry。不能改用 hide_select 或隐藏：
# 那样对象进不了 selected_objects，大纲多选后的删除、复制等操作会失效。
_HELPER_TYPES = frozenset(("EFX_ATTRIBUTE", "EFX_TIML", "EFX_ACTION", "EFX_EXTERN",
                           "EFX_SUBSELECT", "EFX_UVS_LINK_ITEM"))
#: 旧版本创建时的默认尺寸；其他尺寸是用户自设的，保留。
_LEGACY_HELPER_SIZES = (0.1, 0.12)


def shrink_legacy_helper_empties() -> int:
    """把旧文件中辅助 empty 的默认尺寸改为 0，返回修改数。"""
    n = 0
    for o in bpy.data.objects:
        if o.type != "EMPTY" or o.library is not None or o.get("~TYPE") not in _HELPER_TYPES:
            continue
        if any(abs(o.empty_display_size - s) < 1e-6 for s in _LEGACY_HELPER_SIZES):
            o.empty_display_size = 0.0
            n += 1
    return n


@persistent
def _on_load(*_args):
    _pending.clear()
    try:
        shrink_legacy_helper_empties()
    except Exception:
        pass
    try:
        _reconcile_all(_writeback_enabled())
    except Exception:
        pass


def _armature_poll(self, obj):
    """Scene.efx_armature 选择器只接受骨架对象。"""
    return obj.type == "ARMATURE"


_CLASSES = (EFX_OT_sync_transform,)

_HANDLERS = (
    (bpy.app.handlers.load_post, _on_load),
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    (bpy.app.handlers.undo_post, _on_undo_redo),
    (bpy.app.handlers.redo_post, _on_undo_redo),
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_armature = bpy.props.PointerProperty(
        name="Armature",
        description="Skeleton used to position effect entries by their bound bone (PARENTOPTIONS.bone_lim → MhBone_NNN)",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    bpy.types.Scene.efx_blender_coords = bpy.props.BoolProperty(
        name="Blender coordinate display",
        description="字段里的 XYZ 坐标按 Blender 约定显示/编辑：长度 /100、Y/Z 交换并取负、"
                    "角度交换取负、缩放仅交换。仅作用于已知单位的字段；不改存储原值。默认关",
        default=False,
    )
    bpy.types.Scene.efx_show_all_fields = bpy.props.BoolProperty(
        name="Show all fields",
        description="显示全部字段（关闭按模式过滤）。默认关：由模式字段（如 velocityType）"
                    "决定只显示当前生效的字段，其余隐藏（值仍保留，纯视觉）。",
        default=False,
    )
    bpy.types.Scene.efx_t3d_writeback = bpy.props.BoolProperty(
        name="Write Back Entry Transforms",
        description="Moving, rotating or scaling an entry in the viewport writes the result "
                    "to its TRANSFORM3D once the transform is confirmed",
        default=True,
    )
    for lst, fn in _HANDLERS:
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(_flush_pending):
        bpy.app.timers.unregister(_flush_pending)
    _pending.clear()
    try:
        del bpy.types.Scene.efx_t3d_writeback
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_armature
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_blender_coords
    except AttributeError:
        pass
    try:
        del bpy.types.Scene.efx_show_all_fields
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
