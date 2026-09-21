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
from . import fields        # 属性字段模型：脏标记 / 逐字段无损性 / 重建字节
from . import presets       # 预设读写的公共工具（路径 / 命名 / 字段值 JSON 化）
from . import subselect     # Subselect 表的结构化存储与段局部索引映射
from . import action_emitter  # Action 的 PlayEmitter targets 指针化
from . import extern_ref    # EXTERNREFERENCE.referenceIndex → Extern 对象指针
from . import extern_props  # Extern 段的字段展开（EFXExternProps）
from . import entry_action_ref # PtLife / PtCollision / eof_ints 三类引用指针化
from . import backref       # 反向引用视图 + entry 激活状态判定（只读）
from . import reorder       # Entry / Attribute 重排（上移 / 下移）与显示名重建
from . import delete_ops    # 删除 Entry / Attribute / Action / Extern / Subselect 并重排编号
from . import add_ops       # 从整 Entry 预设新增 Entry + Active EFX 文件选择器
from . import add_section_ops  # 从无到有新建 Action / Extern / Subselect 段条目
from . import attribute_ops     # 单个 Attribute 的复制 / 粘贴 / 存预设 / 从预设新增
from . import part_mask_ops # PLEMISSIVE 部位位掩码（body_p / wp_p）勾选编辑器
from . import bitmask_ops    # 通用位掩码弹窗编辑器（typed Field bitmask 字段）
from . import shadersettings_preset_ops  # SHADERSETTINGS.presetId 已知预设名下拉
from . import color_ops      # Color Editor 全局改色工具（色系偏移 / 直接替换）
from . import validate      # 导出前校验（悬空指针 / 2D-3D 混用 / Action 成环…）
from . import session_core  # 会话/预览类公共基础设施：标记式孤儿清理 + 生命周期缓存复位
from . import standalone   # 无宿主 TIML / UVS：不依赖 .efx 树也能打开编辑
from . import timl_io       # TIML ↔ .timl 文件互导 + EFX_TIML 句柄解析
from . import timl_meta_ui  # TIML 头部元字段编辑（Dope Sheet 侧栏 EFX TIML：长度/循环控制）
from . import timl_edit      # TIML 通道编辑：导入即建原生 F 曲线并持久化
from . import timl_tracks    # TIML 轨道增删复制（调色板 / 字段行的 +TIML 按钮）
from . import transform_sync # TRANSFORM3D → Entry empty 的视口变换（单向可视化代理）
from . import uvs_io        # UVSEQUENCE 属性下的 .uvs 导入 / 导出 / 帧编辑 / GIF 转精灵表
from . import uvc_preview    # UVCONTROL 视口 UV 滚动动画预览（根级单会话，全播）
from . import mod3_link        # MESH 属性引用的 mod3 自动导入 + 绑定（联动 MHW Model Editor，可勾选）
from . import uvs_link         # UVSEQUENCE → .uvs → .tex 链式载入（同 mod3_link 那套路径解析）
from . import mesh_align        # 绑定网格随 TRANSFORM3D+MESH 旋转/缩放实时对齐（预览式+可编辑+实例化）
from . import es3d_overlay      # 生成区域线框（独立叠加层，只画选中的 entry，不依赖播放）
from . import mesh_drive        # 绑定网格驱动 Mesh Drive（总开关+勾选，编排 uvc/timl/mesh_align）
from . import sim_preview       # 粒子模拟播放器（modal 时钟 + gpu 绘制，零场景对象）
from . import workspace_preset  # 一键添加内置的 MHW VFX 工作区预设（随包 assets/*.blend）
from . import file_menu      # File > Import/Export 菜单项 + .timl/.uvs 拖入（须在各算子注册后挂）

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
    "standalone",
    "timl_io",
    "timl_meta_ui",
    "timl_tracks",
    "transform_sync",
    "uvs_io",
    "uvc_preview",
    "mod3_link",
    "uvs_link",
    "file_menu",
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

    # ── 先注册 PropertyGroup（顺序重要：子类先于容器类）────────────────
    # EFXFieldItem 必须在 EFXAttributeProps 之前注册，因为后者用 CollectionProperty(type=EFXFieldItem)
    bpy.utils.register_class(fields.EFXFieldItem)
    bpy.utils.register_class(fields.EFXAttributeProps)

    # 把 EFXAttributeProps 挂到 Object 上
    bpy.types.Object.efx_block = PointerProperty(
        name="EFX Block Properties",
        description="AttrBlock field model (EFX_ATTRIBUTE objects only)",
        type=fields.EFXAttributeProps,
    )

    # ── Subselect 结构化存储（PropertyGroup + UIList + Operators）──────
    # subselect.register() 注册核心类（不含 Panel）并把 EFXSubselectProps 挂到 Object。
    # EFX_PT_subselect 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'
    # 要求父面板先注册，而 EFX_PT_entry 在 panels._CLASSES 首位，顺序正确）。
    subselect.register()

    # ── Action 结构化存储（PropertyGroup + UIList + Operators）──────────
    # action_emitter.register() 注册核心类（不含 Panel）并把 EFXActionProps 挂到 Object。
    # EFX_PT_action 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'）。
    action_emitter.register()

    # ── EXTERNREFERENCE 指针化（PropertyGroup）────────────────────────
    # extern_ref.register() 注册核心类（不含 Panel）并把 EFXExternRefProps 挂到 Object。
    # EFX_PT_extern_ref 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_entry'）。
    extern_ref.register()

    # ── Extern 段字段展开（EFXExternInstanceProps/EFXExternItemProps/EFXExternProps）─
    # EFXFieldItem 必须已注册（在本函数开头完成）。
    # EFX_PT_extern_props 面板由 panels.register() 注册。
    extern_props.register()

    # ── PtLife / PtCollision / eof_ints 指针化（PropertyGroup）─────────────
    # entry_action_ref.register() 注册核心类（不含 Panel）。
    # EFX_PT_eof_list 面板由 panels.register() 注册（PtLife/PtCollision 已无独立面板，
    # 合并进 Attribute Properties 内联渲染）。
    entry_action_ref.register()

    # ── L2 反向引用视图（只读）：算子无依赖，先注册；面板由 panels.register() 注册 ─
    backref.register()

    # ── Entry / Attribute 重排算子（EFX_OT_move_entry / EFX_OT_move_attribute）──────
    reorder.register()

    # ── 删除条目算子（EFX_OT_delete_*）────────────────────────────────
    delete_ops.register()

    # ── 新增 Entry 算子 + Scene.efx_active_efx（必须在 panels.register() 前）─
    add_ops.register()

    # ── 从无到有新建 Play/Extern/Subselect 段条目（算子，须在 panels.register() 前）──
    add_section_ops.register()

    # ── 单 Attribute 复制/粘贴/存预设/从预设新增（必须在 panels.register() 前）────────
    attribute_ops.register()

    # ── PLEMISSIVE 位掩码勾选编辑器（算子，须在 panels.register() 前）─────────────
    part_mask_ops.register()
    bitmask_ops.register()
    shadersettings_preset_ops.register()

    # ── Color Editor 全局改色工具（算子 + 顶层面板 + Scene.efx_recolor_target）────
    color_ops.register()

    # ── 导出前校验算子（EFX_OT_validate）──────────────────────────────
    validate.register()

    # ── Operator / Panel ────────────────────────────────────────────────────
    operators.register()
    panels.register()  # 包含 EFX_PT_entry（父）和所有 L2 子面板

    # ── 无宿主 TIML / UVS：只有算子（关闭无主载体），无面板依赖，先于消费者注册 ──
    standalone.register()

    # ── TIML 互导：面板 bl_parent_id='EFX_PT_entry'，同样在 panels.register() 之后 ─
    timl_io.register()

    # ── TIML 头部元字段编辑：Dope Sheet 独立侧栏 N 面板，独立注册 ────────────────
    timl_meta_ui.register()

    # ── TIML 通道编辑会话（原生 F 曲线，零 FK）──────────────────────
    timl_edit.register()

    # ── TIML 轨道增删复制（Dope Sheet 面板 + 字段行的 +TIML 按钮）────────
    timl_tracks.register()

    # ── TRANSFORM3D → 视口同步算子（无面板依赖）─────────────────────────────
    transform_sync.register()

    # ── UVS Edition：顶层 N 面板（bl_order=0），独立注册 ──────────────────────
    uvs_io.register()

    # ── 绑定网格驱动父面板 Mesh Drive（编排 uvc/timl/mesh_align）────────────────
    # ⚠ 必须早于 uvc_preview / mesh_align：那两个模块的面板用
    # bl_parent_id='EFX_PT_mesh_drive' 挂在它下面，父面板未注册则子面板注册失败。
    mesh_drive.register()

    # ── UVCONTROL UV 预览：顶层 N 面板 + frame handler，独立注册 ───────────────
    uvc_preview.register()

    # ── mod3 自动导入联动：注册 Scene.efx_chunk_root（导入算子 draw/execute 用）────
    mod3_link.register()

    # ── UVSEQUENCE → .uvs → .tex 链式载入算子（用 mod3_link 的 Scene.efx_chunk_root，
    #    故必须排在它后面）───────────────────────────────────────────────────────
    uvs_link.register()

    # ── 会话/预览类公共基础设施（标记式孤儿清理 + load_post 缓存复位）先于消费者注册 ──
    session_core.register()

    # ── 绑定网格实时对齐预览（预览式+可编辑+实例化）：顶层 N 面板，独立注册 ────────
    mesh_align.register()

    # ── EmitterShape3D 形状预览（透明几何体，预览式会话）：顶层入口，独立注册 ─────────
    es3d_overlay.register()

    # ── 粒子模拟播放器：顶层 N 面板（bl_order=3）+ 三个子面板，独立注册 ───────────
    # 与 mesh_drive 那一族无父子关系（那边是给绑定网格挂驱动，这边是播放器
    # 模型）；不建任何场景对象，故也不依赖 session_core。
    sim_preview.register()

    # ── 一键添加 MHW VFX 工作区预设：单个算子，无依赖 ───────────────────────────
    workspace_preset.register()

    # ── File > Import/Export 菜单项 + .timl/.uvs 拖入 ───────────────────────────
    # 最后注册：菜单项按 bl_idname 引用上面各模块的算子，必须等它们全部注册完。
    file_menu.register()


def unregister():
    """注销扩展的全部 PropertyGroup、Operator 和 Panel 类。"""
    # ── Operator / Panel（先注销 UI 层）────────────────────────────────────
    file_menu.unregister()
    workspace_preset.unregister()
    sim_preview.unregister()
    es3d_overlay.unregister()
    mesh_align.unregister()
    session_core.unregister()
    uvs_link.unregister()
    mod3_link.unregister()
    uvc_preview.unregister()
    # 驱动族父面板：必须在 uvc_preview / mesh_align 这些子面板之后注销（与注册相反）
    mesh_drive.unregister()
    uvs_io.unregister()
    transform_sync.unregister()
    timl_tracks.unregister()
    timl_edit.unregister()
    timl_meta_ui.unregister()
    timl_io.unregister()
    standalone.unregister()
    panels.unregister()
    operators.unregister()

    # ── 导出前校验算子 ───────────────────────────────────────────────
    validate.unregister()

    # ── Color Editor 全局改色工具 ─────────────────────────────────────────────
    color_ops.unregister()

    # ── 单 Attribute 组装算子 ──────────────────────────────────────────────────────────
    shadersettings_preset_ops.unregister()
    bitmask_ops.unregister()
    part_mask_ops.unregister()
    attribute_ops.unregister()

    # ── 从无到有新建 Play/Extern/Subselect 段条目 ────────────────────────────
    add_section_ops.unregister()

    # ── 新增 Entry 算子 + Scene.efx_active_efx ────────────────────────
    add_ops.unregister()

    # ── 删除条目算子 ────────────────────────────────────────────────
    delete_ops.unregister()

    # ── Entry / Attribute 重排算子 ───────────────────────────────────────────
    reorder.unregister()

    # ── L2 反向引用视图（只读）：面板已由 panels.unregister() 注销 ────────────
    backref.unregister()

    # ── PtLife / PtCollision / eof_ints 指针化核心类（PropertyGroup）──────
    # EFX_PT_eof_list 已由 panels.unregister() 注销。
    entry_action_ref.unregister()

    # ── Extern 段字段展开核心类（PropertyGroup + Operators）────────
    extern_props.unregister()

    # ── EXTERNREFERENCE 核心类（PropertyGroup）──────────────────────
    # EFX_PT_extern_ref 已由上面的 panels.unregister() 注销。
    extern_ref.unregister()

    # ── Action 核心类（PropertyGroup + UIList + Operators）────────────
    # EFX_PT_action 已由上面的 panels.unregister() 注销。
    action_emitter.unregister()

    # ── Subselect 核心类（PropertyGroup + UIList + Operators）──────
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
