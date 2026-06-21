"""
blender_efx/timl_preview.py  —  TIML transform 视口浏览 + FreeKinetics 快捷编辑（添头功能）

定位（与用户确认的边界）
------------------------
- **FK 是「添头」而非依赖**：FreeKinetics（MHW-Free-HyperKinetics，算子前缀 `freehk.`）
  不在场时，本模块的功能全部隐藏/禁用，timl_io 的文件互导（方案 C）照常工作，零退化。
  检测到 FK 才解锁下面两项额外功能。

- **浏览（提案 ②）**：进入浏览 = 借 FK 把当前 body（或本 EFX 下所有已绑定 body）的 TIML
  导入成标准 Blender Action（`location/rotation_euler/scale` 曲线，FK 已做游戏→Blender 轴变换），
  挂到该 body 在 MESH 块上绑定的网格（`Object.efx_mesh_target`，与 UVC 预览共用绑定）。
  动作靠 Blender 原生 action 播放，**无需 frame handler**，拖时间轴即可看 transform 动画。
  没绑定网格的 body 直接跳过（不动）。**当前只做 transform 通道**（color/flag 跳过）。
  退出浏览 = 还原各网格原 action、删除本次导入的临时 Action 与 FK 节点树（timl controller）、
  删临时文件、还原帧范围 —— 回到进入前状态。

- **快捷编辑（提案 ①）**：与浏览同一套「导入成 action 挂到网格」机制，区别是退出时不丢弃，
  而是把（用户在摄影表上改过的）action 经 FK 序列化回 TIML 字节写回 body。FK 的导出绑定
  节点编辑器上下文，自动回写最 fragile：本模块用上下文覆盖尽力触发，失败则提示走 timl_io 的
  「替换 TIML」手动回填，绝不静默丢改动。

约束（CLAUDE.md）
-----------------
- 纯胶水层；浏览全程只读 TIML（不重序列化）→ 完全不碰 byte-perfect 底线。
- Python 3.10 兼容；bpy 只用长期稳定子集；FK 全部调用经 `_fk_*` 封装，缺席即降级。
"""

import os
import base64
import tempfile

import bpy
from bpy.types import Operator, Panel
from bpy.app.handlers import persistent

from .i18n import T
from . import uvc_preview as _uvc   # 复用：_body_mesh_target / _resolve_root / _all_efx_roots / _is_efx_object
from . import timl_io as _tio       # 复用：_body_is_timl_capable / _body_timl_bytes


# transform 通道的 data_path（FK 把 TIML transform 映到这三个标准属性）
_TRANSFORM_PATHS = {"location", "rotation_euler", "scale"}
_FK_TREE_IDNAME = "FreeHKNodeTree"


# ─────────────────────────────────────────────────────────────────────────────
# FreeKinetics 在场检测（添头开关）
# ─────────────────────────────────────────────────────────────────────────────

def _fk_available() -> bool:
    """FreeKinetics 是否已安装并注册了 TIML 导入算子。

    用算子注册情况判断（比查 addon 名更稳，名字随打包变化）：`freehk.import_timl`
    存在即认为 FK 可用。bpy.ops.freehk 是惰性命名空间，dir() 列出已注册算子。
    """
    try:
        return "import_timl" in dir(bpy.ops.freehk)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# body → 可浏览判定 / 临时 .timl 落盘
# ─────────────────────────────────────────────────────────────────────────────

def _body_has_timl_and_mesh(body):
    """该 EFX_BODY 是否「含非空 TIML」且「MESH 块已绑定网格」。返回 (timl_bytes, mesh) 或 None。"""
    if body is None or body.get("~TYPE") != "EFX_BODY":
        return None
    if not _tio._body_is_timl_capable(body):
        return None
    try:
        tb = _tio._body_timl_bytes(body)
    except Exception:
        return None
    if not tb:
        return None
    mesh = _uvc._body_mesh_target(body)
    if mesh is None:
        return None
    return tb, mesh


def _write_temp_timl(data: bytes) -> str:
    """把 TIML 字节写到一个临时 .timl 文件，返回路径（用户不可见）。"""
    fd, path = tempfile.mkstemp(suffix=".timl", prefix="efx_timl_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return path


def _action_transform_score(act) -> int:
    """action 里 transform 曲线条数（location/rotation_euler/scale）；用于挑「最像变换」的 action。"""
    n = 0
    try:
        for fc in act.fcurves:
            if fc.data_path in _TRANSFORM_PATHS:
                n += 1
    except Exception:
        pass
    return n


# ─────────────────────────────────────────────────────────────────────────────
# FK 桥：导入一个 .timl → (新建 Action 列表, 新建节点树列表)
# ─────────────────────────────────────────────────────────────────────────────

def _fk_import_timl(path):
    """调 FK 的 freehk.import_timl 导入一个 .timl，返回 (new_actions, new_trees)。

    用导入前后 bpy.data 快照差集找出本次新建的对象，便于精确清理 / 归属。
    advanced_remap=True 让 FK 自动估算 remap；reuse_tree=False 每次新建独立树（timl controller）。
    """
    before_actions = {a.name for a in bpy.data.actions}
    before_trees = {g.name for g in bpy.data.node_groups}

    bpy.ops.freehk.import_timl(
        filepath=path, advanced_remap=True, reuse_tree=False, hide=True
    )

    new_actions = [a for a in bpy.data.actions if a.name not in before_actions]
    new_trees = [
        g for g in bpy.data.node_groups
        if g.name not in before_trees and g.bl_idname == _FK_TREE_IDNAME
    ]
    return new_actions, new_trees


def _assign_action(mesh, act):
    """把 action 挂到网格的 animation_data，返回 (prior_action, created_anim) 供还原。"""
    created = False
    if mesh.animation_data is None:
        mesh.animation_data_create()
        created = True
    prior = mesh.animation_data.action
    mesh.animation_data.action = act
    return prior, created


# ─────────────────────────────────────────────────────────────────────────────
# 浏览会话状态（模块级，单会话）
# ─────────────────────────────────────────────────────────────────────────────

_state = {
    "active": False,
    "editable": False,          # True = 快捷编辑模式（退出时回写）；False = 只读浏览
    "entries": [],              # [dict(body, mesh, action, prior_action, created_anim, temp_path, all_actions, trees)]
    "frame_start": 0,
    "frame_end": 1,
}


def _collect_browse_targets(bodies):
    """从给定 body 列表收集浏览目标：含非空 TIML 且已绑定网格。同一网格只收一次（去重）。"""
    targets = []
    seen = set()
    for body in bodies:
        res = _body_has_timl_and_mesh(body)
        if res is None:
            continue
        tb, mesh = res
        if mesh.name in seen:
            continue
        seen.add(mesh.name)
        targets.append((body, mesh, tb))
    return targets


def _start_session(bodies, editable, report):
    """进入浏览/编辑会话。返回 (n_ok, n_skipped_no_transform)。失败抛异常由调用方兜底清理。"""
    targets = _collect_browse_targets(bodies)
    if not targets:
        return 0, 0

    entries = []
    no_transform = 0
    fmin, fmax = 0.0, 1.0

    for body, mesh, tb in targets:
        temp_path = _write_temp_timl(tb)
        new_actions, new_trees = _fk_import_timl(temp_path)
        if not new_actions:
            # 没建出 action（空 TIML / FK 解析无果）→ 清掉树和临时文件，跳过
            for g in new_trees:
                try:
                    bpy.data.node_groups.remove(g)
                except Exception:
                    pass
            _remove_temp(temp_path)
            continue

        # 挑 transform 曲线最多的 action 挂到网格
        best = max(new_actions, key=_action_transform_score)
        if _action_transform_score(best) == 0:
            # 本 TIML 无 transform 通道（可能纯 color/flag）→ 不挂，但仍清理
            no_transform += 1
            for a in new_actions:
                try:
                    bpy.data.actions.remove(a)
                except Exception:
                    pass
            for g in new_trees:
                try:
                    bpy.data.node_groups.remove(g)
                except Exception:
                    pass
            _remove_temp(temp_path)
            continue

        # 动作改名成特效体名，便于摄影表识别
        try:
            best.name = "EFX_TIML::%s" % (body.get("efx_raw_label", "") or body.name)
        except Exception:
            pass

        # ⚠ 进入前快照网格本地变换：action 会写 location/rotation/scale 通道，移除 action 后
        # Blender 不会自动还原，值停在最后评估帧 → 退出时据此 matrix_basis 还原回原位。
        basis_snap = mesh.matrix_basis.copy()
        prior, created = _assign_action(mesh, best)
        try:
            fr = best.frame_range
            fmin = min(fmin, fr[0])
            fmax = max(fmax, fr[1])
        except Exception:
            pass

        entries.append({
            "body": body,
            "mesh": mesh,
            "action": best,
            "prior_action": prior,
            "created_anim": created,
            "basis_snap": basis_snap,
            "temp_path": temp_path,
            "all_actions": new_actions,
            "trees": new_trees,
        })

    if not entries:
        return 0, no_transform

    scene = bpy.context.scene
    _state["frame_start"] = scene.frame_start
    _state["frame_end"] = scene.frame_end
    scene.frame_start = int(fmin)
    scene.frame_end = max(int(round(fmax)), int(fmin) + 1)

    _state["entries"] = entries
    _state["editable"] = editable
    _state["active"] = True
    return len(entries), no_transform


def _remove_temp(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _teardown_session(keep_meshes=False):
    """退出会话：还原网格 action、删除临时 Action / FK 节点树 / 临时文件、还原帧范围。

    keep_meshes=True 时（如换文件后引用已失效）跳过对网格/数据块的访问，只清状态。
    """
    if not keep_meshes:
        for ent in _state["entries"]:
            # 还原网格原 action + 本地变换（matrix_basis）。先清 action 再写 basis，
            # 否则残留 action 会在下次帧变化时又覆盖回去。
            try:
                mesh = ent["mesh"]
                if mesh.animation_data is not None:
                    mesh.animation_data.action = ent["prior_action"]
                snap = ent.get("basis_snap")
                if snap is not None:
                    mesh.matrix_basis = snap
            except Exception:
                pass
            # 删除本次导入的全部临时 Action
            for a in ent.get("all_actions", []):
                try:
                    bpy.data.actions.remove(a)
                except Exception:
                    pass
            # 删除 FK 节点树（timl controller）
            for g in ent.get("trees", []):
                try:
                    bpy.data.node_groups.remove(g)
                except Exception:
                    pass
            _remove_temp(ent.get("temp_path"))

        # 还原帧范围
        try:
            scene = bpy.context.scene
            scene.frame_start = _state["frame_start"]
            scene.frame_end = _state["frame_end"]
        except Exception:
            pass

    _state["active"] = False
    _state["editable"] = False
    _state["entries"] = []
    _state["frame_start"] = 0
    _state["frame_end"] = 1


# ─────────────────────────────────────────────────────────────────────────────
# 快捷编辑回写：经 FK 把（改过的）action 序列化回 TIML 字节 → 写回 body
# ─────────────────────────────────────────────────────────────────────────────

_TIML_FILE_NODE_IDNAME = "TIMLFileNode"


def _find_timl_file_node(trees):
    """在本 entry 导入建出的 FK 树里找 TIML 输出节点（FileNode）。"""
    for tree in trees:
        try:
            for node in tree.nodes:
                if node.bl_idname == _TIML_FILE_NODE_IDNAME:
                    return node
        except Exception:
            continue
    return None


def _clear_fk_cache():
    """清 FK 节点导出的全局缓存（globalCacheClear），确保读到摄影表上改过的最新曲线。

    FK 导出有结点缓存；不清的话重复导出可能拿到旧结构。经 sys.modules 定位 FK 模块，best-effort。
    """
    import sys
    for name, mod in list(sys.modules.items()):
        if name.endswith("freeHKNodes") and hasattr(mod, "globalCacheClear"):
            try:
                mod.globalCacheClear()
            except Exception:
                pass
            return


def _writeback_entry(ent, report):
    """把一个 entry 的 FK 树序列化回 TIML，写回 body.timl_bytes。返回 True/False。

    **不依赖节点编辑器上下文**：直接调 TIML 输出节点的 `export()`（内部自取 FK 偏好、遍历
    连接的 action 节点重建 TIML 结构）→ `serialize()` 得字节。这样用户只在摄影表上改曲线、
    无需打开 FK 节点编辑器，回写也成立。回写复用变长写回（timl_length 导出端重算）。
    """
    node = _find_timl_file_node(ent.get("trees", []))
    if node is None:
        report({"WARNING"}, "未找到 TIML 输出节点，无法回写")
        return False
    _clear_fk_cache()
    try:
        structure = node.export()
        data = structure.serialize()
    except Exception as exc:
        report({"WARNING"}, "FK 导出失败：%s" % exc)
        return False
    if not data or data[:4] != b"timl":
        report({"WARNING"}, "FK 导出结果非法（非 timl 数据）")
        return False
    body = ent["body"]
    body["timl_bytes"] = base64.b64encode(data).decode("ascii")
    body["timl_length"] = str(len(data))
    return True


# ─────────────────────────────────────────────────────────────────────────────
# load_post：换文件/重载时清状态（引用失效，不碰数据块）
# ─────────────────────────────────────────────────────────────────────────────

@persistent
def _on_load(*_args):
    _teardown_session(keep_meshes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Operators：进入浏览 / 退出 / 退出并回写
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_active_body(obj):
    """从活动对象解析出所属 EFX_BODY：自身是 body 即取，是块则取 parent；否则 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == "EFX_BODY":
            return cur
        cur = cur.parent
    return None


def _bodies_under_root(root):
    return [b for b in root.children if b.get("~TYPE") == "EFX_BODY"]


def _resolve_scope_bodies(context):
    """按作用域开关决定要浏览的 body 列表（返回列表或 None）。

    三档（两个开关互斥，都关 = 单体）：
      - all_efx  : 场景内所有 EFX 的全部 body
      - all_bodies: 当前 EFX（活动对象所属 root）的全部 body
      - 默认      : 仅活动 EFX_BODY 单个
    """
    scene = context.scene
    if getattr(scene, "efx_timlp_all_efx", False):
        bodies = []
        for root in _uvc._all_efx_roots():
            bodies.extend(_bodies_under_root(root))
        return bodies or None
    if getattr(scene, "efx_timlp_all_bodies", False):
        root = _uvc._resolve_root(context.active_object)
        return _bodies_under_root(root) if root is not None else None
    body = _resolve_active_body(context.active_object)
    return [body] if body is not None else None


class EFX_OT_timl_preview_enter(Operator):
    """进入 TIML 浏览（借 FreeKinetics 把 TIML 挂成网格动作，拖时间轴查看 transform）"""

    bl_idname = "efx.timl_preview_enter"
    bl_label = "Enter TIML Browse"
    bl_options = {"REGISTER"}

    editable: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        if _state["active"] or not _fk_available():
            return False
        if getattr(context.scene, "efx_timlp_all_efx", False):
            return True
        return _uvc._is_efx_object(context.active_object)

    def execute(self, context):
        if not _fk_available():
            self.report({"ERROR"}, T("timlp.no_fk"))
            return {"CANCELLED"}
        bodies = _resolve_scope_bodies(context)
        if not bodies:
            self.report({"ERROR"}, T("timlp.no_root"))
            return {"CANCELLED"}
        try:
            n_ok, n_skip = _start_session(bodies, self.editable, self.report)
        except Exception as exc:
            _teardown_session()
            self.report({"ERROR"}, T("timlp.import_failed").format(exc))
            return {"CANCELLED"}
        if n_ok == 0:
            self.report({"WARNING"}, T("timlp.no_content"))
            return {"CANCELLED"}
        # 立即跳到首帧让用户看到效果
        try:
            context.scene.frame_set(context.scene.frame_start)
        except Exception:
            pass
        msg = T("timlp.entered").format(n_ok)
        if n_skip:
            msg += " " + T("timlp.skipped_no_transform").format(n_skip)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class EFX_OT_timl_preview_exit(Operator):
    """退出 TIML 浏览并还原（丢弃临时动作；编辑模式下先回写再清理）"""

    bl_idname = "efx.timl_preview_exit"
    bl_label = "Exit TIML Browse"
    bl_options = {"REGISTER"}

    writeback: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _state["active"]

    def execute(self, context):
        wrote = 0
        failed = 0
        if self.writeback:
            for ent in _state["entries"]:
                if _writeback_entry(ent, self.report):
                    wrote += 1
                else:
                    failed += 1
        _teardown_session()
        if self.writeback:
            if failed:
                self.report({"WARNING"}, T("timlp.writeback_partial").format(wrote, failed))
            else:
                self.report({"INFO"}, T("timlp.writeback_ok").format(wrote))
        else:
            self.report({"INFO"}, T("timlp.exited"))
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# Panel：TIML 浏览 / 快捷编辑（选中 EFX_BODY 时显示；FK 在场才显示功能）
# ─────────────────────────────────────────────────────────────────────────────

class EFX_PT_timl_preview(Panel):
    """TIML 视口浏览 + FreeKinetics 快捷编辑（FK 在场解锁）"""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"
    bl_label = "TIML Browse (FreeKinetics)"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "EFX_BODY"

    def draw(self, context):
        layout = self.layout
        if not _fk_available():
            box = layout.box()
            box.label(text=T("timlp.no_fk"), icon="INFO")
            return

        layout.label(text=T("timlp.timeline_hint"), icon="TIME")

        if _state["active"]:
            box = layout.box()
            box.label(text=T("timlp.previewing").format(len(_state["entries"])), icon="PLAY")
            if _state["editable"]:
                row = box.row()
                row.scale_y = 1.3
                op = row.operator("efx.timl_preview_exit",
                                  text=T("timlp.apply_exit"), icon="CHECKMARK")
                op.writeback = True
            row = box.row()
            row.scale_y = 1.2
            op = row.operator("efx.timl_preview_exit", text=T("timlp.exit"), icon="X")
            op.writeback = False
        else:
            # 作用域：默认单特效体；两个互斥开关（本 EFX 全部 / 所有 EFX）
            box = layout.box()
            box.label(text=T("timlp.scope_label"), icon="RESTRICT_SELECT_OFF")
            box.prop(context.scene, "efx_timlp_all_bodies", text=T("timlp.all_bodies"))
            box.prop(context.scene, "efx_timlp_all_efx", text=T("timlp.all_efx"))
            row = layout.row()
            row.scale_y = 1.3
            op = row.operator("efx.timl_preview_enter", text=T("timlp.enter"), icon="PLAY")
            op.editable = False
            row = layout.row()
            op = row.operator("efx.timl_preview_enter",
                              text=T("timlp.enter_edit"), icon="GREASEPENCIL")
            op.editable = True
            layout.label(text=T("timlp.bind_hint"), icon="MESH_DATA")


# ─────────────────────────────────────────────────────────────────────────────
# 注册 / 注销
# ─────────────────────────────────────────────────────────────────────────────

_CLASSES = [
    EFX_OT_timl_preview_enter,
    EFX_OT_timl_preview_exit,
    EFX_PT_timl_preview,
]


def _on_all_bodies_set(self, context):
    # 互斥：勾「本 EFX 全部」时取消「所有 EFX」
    if self.efx_timlp_all_bodies and self.efx_timlp_all_efx:
        self.efx_timlp_all_efx = False


def _on_all_efx_set(self, context):
    # 互斥：勾「所有 EFX」时取消「本 EFX 全部」
    if self.efx_timlp_all_efx and self.efx_timlp_all_bodies:
        self.efx_timlp_all_bodies = False


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_timlp_all_bodies = bpy.props.BoolProperty(
        name="本 EFX 所有特效体",
        description="进入浏览时处理当前 EFX 下所有已绑定特效体（不勾则仅当前单个）",
        default=False,
        update=_on_all_bodies_set,
    )
    bpy.types.Scene.efx_timlp_all_efx = bpy.props.BoolProperty(
        name="所有 EFX",
        description="进入浏览时处理场景内所有 EFX 的全部已绑定特效体（与「本 EFX 所有特效体」互斥）",
        default=False,
        update=_on_all_efx_set,
    )
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    _teardown_session()
    if _on_load in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_on_load)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "efx_timlp_all_bodies"):
        del bpy.types.Scene.efx_timlp_all_bodies
    if hasattr(bpy.types.Scene, "efx_timlp_all_efx"):
        del bpy.types.Scene.efx_timlp_all_efx
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
