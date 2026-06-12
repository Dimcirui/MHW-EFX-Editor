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
from . import operators
from . import panels
from . import io_tree       # 供外部直接访问，如 MCP 调用
from . import fields        # L1.1a：字段模型
from . import presets       # L1.2：块字段值预设
from . import subselect     # L2 #1a：Subselect 结构化存储
from . import play_emitter  # L2 #1b：PlayEmitter targets 指针化
from . import extern_ref    # L2 #1c：ExternReference referenceIndex 指针化
from . import body_play_ref # L2 #1d：PtLife/PtCollision/eof_ints 指针化
from . import backref       # L2 反向引用视图（只读）
from . import reorder       # L2 #3a：body / 块重排（上移/下移）
from . import delete_ops    # L2 #3b：删除条目（body/块/play/extern/subselect）
from . import add_ops       # L2 #3c：从整 body 预设新增 body + Active EFX 选择器
from . import add_section_ops  # 从无到有新建 Play / Extern / Subselect 段条目
from . import block_ops     # 块级组装：单块复制/粘贴/预设保存/新增
from . import validate      # L2 #4：导出前校验
from . import hexview       # 只读 hex 视图（opaque/路径-only 块原始字节查看）
from . import timl_io       # TIML ↔ .timl 文件互导（方案 C：FreeKinetics 桥）
from . import transform_sync # TRANSFORM3D → body empty 视口变换（单向）

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
    "play_emitter",
    "extern_ref",
    "body_play_ref",
    "backref",
    "reorder",
    "delete_ops",
    "add_ops",
    "add_section_ops",
    "block_ops",
    "validate",
    "hexview",
    "timl_io",
    "transform_sync",
]


# ─────────────────────────────────────────────────────────────────────────────
# register / unregister
# ─────────────────────────────────────────────────────────────────────────────

def register():
    """注册扩展的全部 PropertyGroup、Operator 和 Panel 类。"""
    # ── 双语化基础设施：最先注册（语言切换算子 + 读回语言偏好；panels 绘制时要用 T()）─
    i18n.register()

    # ── L1.1a：先注册 PropertyGroup（顺序重要：子类先于容器类）────────────────
    # EFXFieldItem 必须在 EFXBlockProps 之前注册，因为后者用 CollectionProperty(type=EFXFieldItem)
    bpy.utils.register_class(fields.EFXFieldItem)
    bpy.utils.register_class(fields.EFXBlockProps)

    # 把 EFXBlockProps 挂到 Object 上
    bpy.types.Object.efx_block = PointerProperty(
        name="EFX Block Properties",
        description="AttrBlock field model (EFX_BLOCK objects only)",
        type=fields.EFXBlockProps,
    )

    # ── L2 #1a：Subselect 结构化存储（PropertyGroup + UIList + Operators）──────
    # subselect.register() 注册核心类（不含 Panel）并把 EFXSubselectProps 挂到 Object。
    # EFX_PT_subselect 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_main'
    # 要求父面板先注册，而 EFX_PT_main 在 panels._CLASSES 首位，顺序正确）。
    subselect.register()

    # ── L2 #1b：Play 结构化存储（PropertyGroup + UIList + Operators）──────────
    # play_emitter.register() 注册核心类（不含 Panel）并把 EFXPlayProps 挂到 Object。
    # EFX_PT_play 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_main'）。
    play_emitter.register()

    # ── L2 #1c：ExternReference 指针化（PropertyGroup）────────────────────────
    # extern_ref.register() 注册核心类（不含 Panel）并把 EFXExternRefProps 挂到 Object。
    # EFX_PT_extern_ref 面板由下面的 panels.register() 注册（bl_parent_id='EFX_PT_main'）。
    extern_ref.register()

    # ── L2 #1d：PtLife/PtCollision/eof_ints 指针化（PropertyGroup）─────────────
    # body_play_ref.register() 注册核心类（不含 Panel）。
    # 三个面板 EFX_PT_ptlife_ref/EFX_PT_ptcollision_ref/EFX_PT_eof_list 由 panels.register() 注册。
    body_play_ref.register()

    # ── L2 反向引用视图（只读）：算子无依赖，先注册；面板由 panels.register() 注册 ─
    backref.register()

    # ── L2 #3a：body / 块重排算子（EFX_OT_move_body / EFX_OT_move_block）──────
    reorder.register()

    # ── L2 #3b：删除条目算子（EFX_OT_delete_*）────────────────────────────────
    delete_ops.register()

    # ── L2 #3c：新增 body 算子 + Scene.efx_active_efx（必须在 panels.register() 前）─
    add_ops.register()

    # ── 从无到有新建 Play/Extern/Subselect 段条目（算子，须在 panels.register() 前）──
    add_section_ops.register()

    # ── 块级组装：单块复制/粘贴/预设保存/新增（必须在 panels.register() 前）────────
    block_ops.register()

    # ── L2 #4：导出前校验算子（EFX_OT_validate）──────────────────────────────
    validate.register()

    # ── Operator / Panel ────────────────────────────────────────────────────
    operators.register()
    panels.register()  # 包含 EFX_PT_main（父）和所有 L2 子面板

    # ── 只读 hex 视图：面板 bl_parent_id='EFX_PT_main'，必须在 panels.register() 之后 ─
    hexview.register()

    # ── TIML 互导：面板 bl_parent_id='EFX_PT_main'，同样在 panels.register() 之后 ─
    timl_io.register()

    # ── TRANSFORM3D → 视口同步算子（无面板依赖）─────────────────────────────
    transform_sync.register()


def unregister():
    """注销扩展的全部 PropertyGroup、Operator 和 Panel 类。"""
    # ── Operator / Panel（先注销 UI 层）────────────────────────────────────
    transform_sync.unregister()
    timl_io.unregister()
    hexview.unregister()
    panels.unregister()
    operators.unregister()

    # ── L2 #4：导出前校验算子 ───────────────────────────────────────────────
    validate.unregister()

    # ── 块级组装算子 ──────────────────────────────────────────────────────────
    block_ops.unregister()

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
    body_play_ref.unregister()

    # ── L2 #1c：ExternReference 核心类（PropertyGroup）──────────────────────
    # EFX_PT_extern_ref 已由上面的 panels.unregister() 注销。
    extern_ref.unregister()

    # ── L2 #1b：Play 核心类（PropertyGroup + UIList + Operators）────────────
    # EFX_PT_play 已由上面的 panels.unregister() 注销。
    play_emitter.unregister()

    # ── L2 #1a：Subselect 核心类（PropertyGroup + UIList + Operators）──────
    # EFX_PT_subselect 已由上面的 panels.unregister() 注销。
    subselect.unregister()

    # ── 清理 PointerProperty ─────────────────────────────────────────────────
    try:
        del bpy.types.Object.efx_block
    except AttributeError:
        pass

    # ── PropertyGroup（反序注销：先容器，再子类）────────────────────────────
    bpy.utils.unregister_class(fields.EFXBlockProps)
    bpy.utils.unregister_class(fields.EFXFieldItem)

    # ── 双语化基础设施：最后注销 ──────────────────────────────────────────────
    i18n.unregister()
