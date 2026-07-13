"""
blender_efx/__init__.py  —  MHW EFX 编辑器 Blender 扩展子包入口

导入策略（打包扩展）
--------------------
项目根目录作为扩展包 efx_editor（与 blender_manifest.toml 同级的根 __init__.py
是扩展入口）。Blender 加载时包名为 bl_ext.user_default.efx_editor。

blender_efx/ 与 efx_format/ 是 efx_editor 包下的兄弟子包，因此：
  - blender_efx 内对 efx_format 的引用用 ..efx_format（包内相对导入）。
  - blender_efx 内部子模块互相引用用 . 前缀（同包相对导入）。
  - 不需要也不应有任何 sys.path 操作。

开发期 importlib 加载片段（供 MCP / Blender Python 解释器使用）：
  import importlib, importlib.util, sys
  ROOT = r"E:\\Data\\Github\\Python\\EFX-Editor"
  spec = importlib.util.spec_from_file_location(
      "efx_editor",
      ROOT + r"\\__init__.py",
      submodule_search_locations=[ROOT],
  )
  mod = importlib.util.module_from_spec(spec)
  sys.modules["efx_editor"] = mod
  spec.loader.exec_module(mod)
  # 之后 efx_editor.blender_efx、efx_editor.efx_format 均可用，相对导入正常解析。
"""

import bpy
from bpy.props import PointerProperty

# ── 子模块（同包相对导入）────────────────────────────────────────────────────
from . import i18n          # 中英双语化基础设施（语言状态 + T() + 切换算子）
from . import root_collection  # ROOT 集合化：文件归属改由 Collection 承载（无依赖，最先注册）
from . import operators
from . import panels
from . import io_tree       # 供外部直接访问，如 MCP 调用
from . import fields        # L1.1a：字段模型
from . import presets       # L1.2：块字段值预设
from . import subselect     # L2 #1a：Subselect 结构化存储
from . import action_emitter  # L2 #1b：PlayEmitter targets 指针化
from . import extern_ref    # L2 #1c：ExternReference referenceIndex 指针化
from . import extern_props  # L2 #1c+：Extern 段字段展开（EFXExternProps）
from . import entry_action_ref # L2 #1d：PtLife/PtCollision/eof_ints 指针化
from . import backref       # L2 反向引用视图（只读）
from . import reorder       # L2 #3a：body / 块重排（上移/下移）
from . import delete_ops    # L2 #3b：删除条目（body/块/play/extern/subselect）
from . import add_ops       # L2 #3c：从整 body 预设新增 body + Active EFX 选择器
from . import add_section_ops  # 从无到有新建 Play / Extern / Subselect 段条目
from . import attribute_ops     # 块级组装：单块复制/粘贴/预设保存/新增
from . import part_mask_ops # PLEMISSIVE body_p/wp_p 位掩码勾选编辑器
from . import validate      # L2 #4：导出前校验
from . import hexview       # 只读 hex 视图（opaque/路径-only 块原始字节查看）
from . import session_core  # 会话/预览类公共基础设施：标记式孤儿清理 + 生命周期缓存复位
from . import timl_io       # TIML ↔ .timl 文件互导 + EFX_TIML 句柄解析
from . import timl_meta_ui  # TIML 头部元字段编辑（Dope Sheet 侧栏 EFX TIML：长度/循环控制）
from . import timl_edit      # 阶段2b：自建 TIML 通道编辑会话（原生 F 曲线，零 FK）
from . import timl_tracks    # T1/T2/T2b：TIML 轨道增删复制（删除/复制/调色板/字段+TIML 按钮）
from . import transform_sync # TRANSFORM3D → body empty 视口变换（单向）
from . import uvs_io        # UVS Edition：UVSEQUENCE 块下 .uvs 文件导入/导出/编辑
from . import uvc_preview    # UVCONTROL 视口 UV 滚动动画预览（根级单会话，全播）
from . import mod3_link        # EFX MESH 块引用的 mod3 自动导入+绑定（联动 MHW Model Editor，可勾选）
from . import mesh_align        # 绑定网格随 TRANSFORM3D+MESH 旋转/缩放实时对齐（预览式+可编辑+实例化）
from . import es3d_preview      # EmitterShape3D 形状预览（透明几何体：立方体/球/环/点，预览式会话）
from . import efx_preview       # 统一预览面板 EFX Preview（点5：总开关+勾选，编排 uvc/timl/mesh_align/es3d）

# 对外公开的核心函数
from .io_tree import import_efx_tree, export_efx_tree, roundtrip_corpus
from .fields import verify_items_lossless  # 验证钩子

__all__ = [
    "import_efx_tree",
    "export_efx_tree",
    "roundtrip_corpus",
    "verify_items_lossless",
    "i18n",
    "operators",
    "panels",
    "fields",
    "presets",
    "subselect",
    "action_emitter",
    "extern_ref",
    "extern_props",
    "entry_action_ref",
    "backref",
    "reorder",
    "delete_ops",
    "add_ops",
    "add_section_ops",
    "attribute_ops",
    "validate",
    "hexview",
    "timl_io",
    "timl_meta_ui",
    "timl_tracks",
    "transform_sync",
    "uvs_io",
    "uvc_preview",
    "mod3_link",
]


# ─────────────────────────────────────────────────────────────────────────────
# register / unregister
# ─────────────────────────────────────────────────────────────────────────────

def register():
    """注册扩展的全部 PropertyGroup、Operator 和 Panel 类。"""
    # ── 双语化基础设施：最先注册（语言切换算子 + 读回语言偏好；panels 绘制时要用 T()）─
    i18n.register()

    # ── ROOT 集合化：Collection.efx_root_ptr 反向指针，全仓库找 root 的唯一依赖，最先注册 ──
    root_collection.register()

    # ── L1.1a：先注册 PropertyGroup（顺序重要：子类先于容器类）────────────────
    # EFXFieldItem 必须在 EFXAttributeProps 之前注册，因为后者用 CollectionProperty(type=EFXFieldItem)
    bpy.utils.register_class(fields.EFXFieldItem)
    bpy.utils.register_class(fields.EFXAttributeProps)

    # 把 EFXAttributeProps 挂到 Object 上
    bpy.types.Object.efx_block = PointerProperty(
        name="EFX Block Properties",
        description="AttrBlock field model (EFX_ATTRIBUTE objects only)",
        type=fields.EFXAttributeProps,
    )

    # ── L2 #1a：Subselect 结构化存储（PropertyGroup + UIList + Operators）──────
    # subselect.register() 注册核心类（不含 Panel）并把 EFXSubselectProps 挂到 Object。
    # EFX_PT_subselect 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'
    # 要求父面板先注册，而 EFX_PT_entry 在 panels._CLASSES 首位，顺序正确）。
    subselect.register()

    # ── L2 #1b：Play 结构化存储（PropertyGroup + UIList + Operators）──────────
    # action_emitter.register() 注册核心类（不含 Panel）并把 EFXActionProps 挂到 Object。
    # EFX_PT_action 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'）。
    action_emitter.register()

    # ── L2 #1c：ExternReference 指针化（PropertyGroup）────────────────────────
    # extern_ref.register() 注册核心类（不含 Panel）并把 EFXExternRefProps 挂到 Object。
    # EFX_PT_extern_ref 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'）。
    extern_ref.register()

    # ── L2 #1c+：Extern 段字段展开（EFXExternInstanceProps/EFXExternItemProps/EFXExternProps）─
    # EFXFieldItem 必须已注册（在本函数开头完成）。
    # EFX_PT_extern_props 面板由 panels.register() 注册。
    extern_props.register()

    # ── L2 #1d：PtLife/PtCollision/eof_ints 指针化（PropertyGroup）─────────────
    # entry_action_ref.register() 注册核心类（不含 Panel）。
    # 三个面板 EFX_PT_ptlife_ref/EFX_PT_ptcollision_ref/EFX_PT_eof_list 由 panels.register() 注册。
    entry_action_ref.register()

    # ── L2 反向引用视图（只读）：算子无依赖，先注册；面板由 panels.register() 注册 ─
    backref.register()

    # ── L2 #3a：body / 块重排算子（EFX_OT_move_entry / EFX_OT_move_attribute）──────
    reorder.register()

    # ── L2 #3b：删除条目算子（EFX_OT_delete_*）────────────────────────────────
    delete_ops.register()

    # ── L2 #3c：新增 body 算子 + Scene.efx_active_efx（必须在 panels.register() 前）─
    add_ops.register()

    # ── 从无到有新建 Play/Extern/Subselect 段条目（算子，须在 panels.register() 前）──
    add_section_ops.register()

    # ── 块级组装：单块复制/粘贴/预设保存/新增（必须在 panels.register() 前）────────
    attribute_ops.register()

    # ── PLEMISSIVE 位掩码勾选编辑器（算子，须在 panels.register() 前）─────────────
    part_mask_ops.register()

    # ── L2 #4：导出前校验算子（EFX_OT_validate）──────────────────────────────
    validate.register()

    # ── Operator / Panel ────────────────────────────────────────────────────
    operators.register()
    panels.register()  # 包含 EFX_PT_entry（父）和所有 L2 子面板

    # ── 只读 hex 视图：面板 bl_parent_id='EFX_PT_entry'，必须在 panels.register() 之后 ─
    hexview.register()

    # ── TIML 互导：面板 bl_parent_id='EFX_PT_entry'，同样在 panels.register() 之后 ─
    timl_io.register()

    # ── TIML 头部元字段编辑：Dope Sheet 独立侧栏 N 面板，独立注册 ────────────────
    timl_meta_ui.register()

    # ── 阶段2b：自建 TIML 通道编辑会话（原生 F 曲线，零 FK）──────────────────────
    timl_edit.register()

    # ── T1/T2/T2b：TIML 轨道增删复制（Dope Sheet 面板 + 字段 +TIML 按钮）────────
    timl_tracks.register()

    # ── TRANSFORM3D → 视口同步算子（无面板依赖）─────────────────────────────
    transform_sync.register()

    # ── UVS Edition：顶层 N 面板（bl_order=0），独立注册 ──────────────────────
    uvs_io.register()

    # ── UVCONTROL UV 预览：顶层 N 面板 + frame handler，独立注册 ───────────────
    uvc_preview.register()

    # ── mod3 自动导入联动：注册 Scene.efx_chunk_root（导入算子 draw/execute 用）────
    mod3_link.register()

    # ── 会话/预览类公共基础设施（标记式孤儿清理 + load_post 缓存复位）先于消费者注册 ──
    session_core.register()

    # ── 绑定网格实时对齐预览（预览式+可编辑+实例化）：顶层 N 面板，独立注册 ────────
    mesh_align.register()

    # ── EmitterShape3D 形状预览（透明几何体，预览式会话）：顶层入口，独立注册 ─────────
    es3d_preview.register()

    # ── 统一预览面板 EFX Preview（编排 uvc/timl/mesh_align/es3d）──────────────────
    efx_preview.register()


def unregister():
    """注销扩展的全部 PropertyGroup、Operator 和 Panel 类。"""
    # ── Operator / Panel（先注销 UI 层）────────────────────────────────────
    efx_preview.unregister()
    es3d_preview.unregister()
    mesh_align.unregister()
    session_core.unregister()
    mod3_link.unregister()
    uvc_preview.unregister()
    uvs_io.unregister()
    transform_sync.unregister()
    timl_tracks.unregister()
    timl_edit.unregister()
    timl_meta_ui.unregister()
    timl_io.unregister()
    hexview.unregister()
    panels.unregister()
    operators.unregister()

    # ── L2 #4：导出前校验算子 ───────────────────────────────────────────────
    validate.unregister()

    # ── 块级组装算子 ──────────────────────────────────────────────────────────
    part_mask_ops.unregister()
    attribute_ops.unregister()

    # ── 从无到有新建 Play/Extern/Subselect 段条目 ────────────────────────────
    add_section_ops.unregister()

    # ── L2 #3c：新增 body 算子 + Scene.efx_active_efx ────────────────────────
    add_ops.unregister()

    # ── L2 #3b：删除条目算子 ────────────────────────────────────────────────
    delete_ops.unregister()

    # ── L2 #3a：body / 块重排算子 ───────────────────────────────────────────
    reorder.unregister()

    # ── L2 反向引用视图（只读）：面板已由 panels.unregister() 注销 ────────────
    backref.unregister()

    # ── L2 #1d：PtLife/PtCollision/eof_ints 指针化核心类（PropertyGroup）──────
    # EFX_PT_ptlife_ref/EFX_PT_ptcollision_ref/EFX_PT_eof_list 已由 panels.unregister() 注销。
    entry_action_ref.unregister()

    # ── L2 #1c+：Extern 段字段展开核心类（PropertyGroup + Operators）────────
    extern_props.unregister()

    # ── L2 #1c：ExternReference 核心类（PropertyGroup）──────────────────────
    # EFX_PT_extern_ref 已由上面的 panels.unregister() 注销。
    extern_ref.unregister()

    # ── L2 #1b：Play 核心类（PropertyGroup + UIList + Operators）────────────
    # EFX_PT_action 已由上面的 panels.unregister() 注销。
    action_emitter.unregister()

    # ── L2 #1a：Subselect 核心类（PropertyGroup + UIList + Operators）──────
    # EFX_PT_subselect 已由上面的 panels.unregister() 注销。
    subselect.unregister()

    # ── 清理 PointerProperty ─────────────────────────────────────────────────
    try:
        del bpy.types.Object.efx_block
    except AttributeError:
        pass

    # ── PropertyGroup（反序注销：先容器，再子类）────────────────────────────
    bpy.utils.unregister_class(fields.EFXAttributeProps)
    bpy.utils.unregister_class(fields.EFXFieldItem)

    # ── ROOT 集合化反向指针：最后注销（其余模块可能在自身 unregister 里间接用到）──────
    root_collection.unregister()

    # ── 双语化基础设施：最后注销 ──────────────────────────────────────────────
    i18n.unregister()
