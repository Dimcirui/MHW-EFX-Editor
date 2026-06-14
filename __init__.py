"""
efx_editor/__init__.py  —  MHW EFX 编辑器 Blender 扩展根入口

此文件与 blender_manifest.toml 同级，是 Blender 扩展系统识别的入口。
Blender 加载时此目录被视为包 bl_ext.user_default.efx_editor。

结构：
  efx_editor/             ← 扩展包根（本文件所在目录）
  ├── __init__.py         ← 本文件（扩展入口，委托给 blender_efx）
  ├── blender_manifest.toml
  ├── blender_efx/        ← Blender 胶水层（operators / panels / io_tree / fields）
  │   └── __init__.py
  └── efx_format/         ← 纯 Python 解析层（零 bpy 依赖）
      └── __init__.py

开发期 importlib 加载片段（供 MCP / Blender Python 解释器使用）：
  import importlib.util, sys
  ROOT = r"E:\\Data\\Github\\Python\\EFX-Editor"
  spec = importlib.util.spec_from_file_location(
      "efx_editor",
      ROOT + r"\\__init__.py",
      submodule_search_locations=[ROOT],
  )
  mod = importlib.util.module_from_spec(spec)
  sys.modules["efx_editor"] = mod
  spec.loader.exec_module(mod)
  # 加载完毕后：
  #   efx_editor.register()   →  注册全部算子/面板
  #   efx_editor.unregister() →  注销
  #   efx_editor.blender_efx.import_efx_tree(path)  →  导入
  #   efx_editor.blender_efx.export_efx_tree(root)  →  导出
"""

# bl_info：仅供 Blender 老式 addon 系统（<4.2，如 3.6）识别。
# 4.2+ 扩展系统忽略它、改用 blender_manifest.toml。两者并存无冲突。
# 老式 addon 打包变体（tools/build_extension.py --legacy）会把本包套进 efx_editor/ 文件夹。
bl_info = {
    "name": "MHW EFX Editor",
    "author": "Dimcirui",
    "version": (0, 2, 36),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > EFX",
    "description": "Import and export Monster Hunter World EFX effect files",
    "category": "Import-Export",
}

from . import blender_efx


def register():
    """注册扩展（Blender 扩展系统入口）。"""
    blender_efx.register()


def unregister():
    """注销扩展（Blender 扩展系统入口）。"""
    blender_efx.unregister()
