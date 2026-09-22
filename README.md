# MHW EFX Editor

A Blender add-on for opening, editing, and exporting **Monster Hunter World: Iceborne** visual-effect files (`.efx`).

It presents an EFX file as a browsable Blender collection and object tree. Fields use controls such as colour pickers, enum menus, and bitmask checkboxes; unchanged data is preserved when the file is exported.

> 中文说明见页面底部的 **[中文](#中文)** 折叠块。

## Requirements and installation

| Blender version | Package |
|---|---|
| 4.3 or newer | `efx_editor-<version>.zip` (extension) |
| 3.6–4.2 | `efx_editor-<version>-legacy.zip` (legacy add-on) |

Download the matching zip from [Releases](../../releases); do not extract it. In Blender, open **Edit → Preferences**. For 4.3+, go to **Get Extensions**; for 3.6–4.2, go to **Add-ons**. Use the menu in the upper-right corner to **Install from Disk**, select the zip, and enable the add-on. Open the **EFX** tab in the 3D Viewport sidebar with `N`.

The add-on has been tested on Blender 3.6, 4.3, and 5.1.

### First steps

1. In **EFX → MHW EFX**, import an `.efx` or create a new one. An imported file appears as an expandable collection.
2. Select an Entry, Attribute, Action, or another part in the Outliner. The relevant controls appear in the **EFX** sidebar; some Entry and Attribute controls are also available in Object Data Properties.
3. Edit fields or use **Add** and **Edit** to change the structure. If several EFX files are open, check **Active EFX** before adding an item. When it is unset, the selected object's EFX collection is used.
4. Run **Validation** before exporting to check known reference and structural problems. Validation cannot guarantee that an effect will work in-game.

## Main features

- Import, create, and export `.efx`; browse and change its parts as Blender collections and objects.
- Edit fields with controls suited to their data types, and save or reuse Entry and Attribute presets.
- Inspect references among Entries, Actions, and Externs; check for common problems before export.
- Edit TIML animation, materials, and UVS data; use colour tools across an effect.
- Preview particle and bound-mesh motion, and work with models and armatures. The particle simulation is an observation-based approximation, not an accurate rendering of the game effect.
- Switch between English and Chinese UI; use the separate lightweight `.epv3` editor.

### Working with EFX in Blender

The **MHW EFX** panel contains New, Import, Export, the language toggle, Active EFX and armature selectors, placement synchronisation, and validation. After importing, select an object in the Outliner to reveal context-specific controls:

| UI area | What it does |
|---|---|
| **Add** | Create an Action, Extern, or Subselect; switch between Entry and Attribute tabs. Add an Entry from a built-in starting template or saved preset. Find Attributes by search or category. |
| **Edit** | Rename, move, delete, copy, or paste the selected kind of item. Available actions depend on the selection. |
| **Entry Status / Activation / Entry References** | Inspect direct activation, Action calls, and references; toggle an Entry's direct-trigger state. The displayed effective activation is an editor-derived aid. |
| **Entry / Attribute / Extern Properties** | Inspect and edit the selected object's data. Attribute fields use numeric, vector, colour, enum, bitmask, and other appropriate controls; some types have dedicated editors. |
| **Subselect States / Extern Referenced By** | Inspect Subselect membership or jump from an Extern to objects that reference it. |

Whole Entries and Attributes can be copied, pasted, and saved as presets. To add an Attribute, select an Entry or an Attribute beneath it. The UI may suggest commonly used missing Attributes, but these are suggestions, not format requirements. The add-on maintains relevant indices after structural edits; run validation again before exporting when references are involved.

### Animation, assets, and previews

- **TIML:** Edit Entry timelines as Blender F-curves in the Dope Sheet and Graph Editor. Add, remove, and edit tracks; adjust timeline settings in the **EFX TIML** sidebar. Standalone `.timl` import and editing are also available.
- **UVS:** Import or export `.uvs` from a `UVSEQUENCE` Attribute. Edit groups, path slots, and frames in the Image Editor's **UVS** sidebar, with an optional reference image. A GIF-to-PNG-sprite-sheet tool and standalone `.uvs` editing are available.
- **Materials and models:** `MATERIAL` has controls for material blocks and texture slots and can use a reference `.mrl3`. `MESH` can be paired with mesh binding and Mesh Drive previews. Automatic linking of mod3 meshes, materials, and textures requires the companion add-ons and configured resource paths.
- **Viewport aids:** `TRANSFORM3D` can show an Entry's trigger position and work with an armature and `PARENTOPTIONS`. Emission regions, UV scrolling, bound-mesh motion, and particles have preview tools. These are authoring aids, not guarantees of in-game rendering.
- **Colour Editor:** Use the Color Tool to shift hues or replace colours across an effect.
- **VFX workspace:** Add the bundled MHW VFX editing workspace to the current Blender file.

### EPV editing

The 3D Viewport also has an **EPV** sidebar tab for importing, editing, and exporting `.epv3`. Select a Record in its object tree to edit its Group ID, four EFX path slots, colour slots, transform, and raw fields. A path slot can select an already imported EFX and jump to it when matched. This auxiliary editor is separate from EFX Attribute coverage.

## Basic `.efx` structure

This is the editor's working view, not a specification of the file's byte layout.

| Part | Role |
|---|---|
| EFX | One effect file, represented by a Blender collection after import. |
| Entry | A main effect unit containing an ordered list of Attributes and, optionally, TIML animation. Some Entries trigger directly; others can be called by Actions. |
| TIML | Timeline data within an Entry, editable as tracks and keyframes in Blender. |
| Attribute | A typed data block within an Entry, describing generation, rendering, motion, lifetime, and other behaviour. |
| Action | Called through references such as an Entry's `PTLIFE` or `PTCOLLISION`. `PLAYEMITTER` calls an Entry; `PLAYEFX` calls an external `.efx`. |
| Extern | Supplies replacement data referenced by an Entry and applied with interpolation under the relevant conditions. |
| Subselect | Records a selection of Entries used to control which parts participate in playback. |

## Attribute categories and editability

The add-on covers all **68 main Attribute types found so far**. They are organised into nine editor categories for browsing, creation, and presets; these are not nine native sections in the file format.

**All main Attribute types have parsing and editing support**, including dedicated modular controls for variable-length `MATERIAL` and `PTBEHAVIOR`. “Editable” means that the add-on can read and write fields; it does **not** mean every field's purpose is known. Many still have `unkn…` names. Before enabling field editing for a particular data instance, the add-on checks that it can reconstruct the original bytes exactly. If that check fails or the instance is unsupported, it keeps the original data and disables field editing for that instance.

For Extern data, **26 of 27 types** support field editing. `EXTERNITEM` is read-only and preserved unchanged. Some supported Extern types have not been observed in use, so their layouts have not been validated against real instances.

### Category overview

The categories describe typical editing roles. They do not imply that every Entry needs every category or that any combination within a category is valid.

| Category | Types | Typical role and examples |
|---|---:|---|
| Entry Skeleton | 5 | Basic transform, parent relationship, spawning, and lifetime; e.g. `TRANSFORM3D`, `LIFE`. |
| Extern Reference | 1 | Connects an Entry to Extern data through `EXTERNREFERENCE`. |
| Renderer Body | 9 | Visual carriers such as Billboard, Mesh, and Ribbon; e.g. `BILLBOARD3D`, `MESH`. |
| Renderer Modifier | 17 | Texture, colour, material, and other rendering changes; e.g. `UVSEQUENCE`, `MATERIAL`. |
| Generation Method | 6 | Initial distribution of particles or effects; e.g. `EMITTERSHAPE3D`. |
| Motion & Visibility | 18 | Motion, scale, rotation, fading, and visibility; e.g. `VELOCITY3D`, `FADEBYDEPTH`. |
| Action Trigger | 2 | `PTLIFE` and `PTCOLLISION` connect lifetime or collision events to Actions. |
| PtBehavior | 2 | `PTBEHAVIOR`, `TUBELIGHT`, and their distinct behaviour systems. |
| Miscellaneous | 8 | Types outside the preceding groups, such as `LAYOUT` and `RANDOMFIX`. |

Attribute-type coverage, knowledge of field meanings, and preview-simulation coverage are different measures. An unnamed field can still be edited; an editable field is not necessarily understood. Keep a backup and test unusual changes in-game.

## Credits

Thanks to the community members and projects whose research and documentation informed this add-on:

- The many contributors to **MHW-EFX-Template**: early EFX parsing approaches and some field names in this add-on were informed by this collaborative 010 Editor template. The link points to [the repository maintained by UNOWEN-OwO](https://github.com/UNOWEN-OwO/MHW-EFX-Template).
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki): foundational EFX format and editing documentation.
- [RE Engine Lib](https://github.com/kagenocookie/RE-Engine-Lib): a reference for cross-checking Attribute structures and field definitions.
- **Crimson:** contributions to the template and EFX Attribute research, and help with this add-on's Attribute categorisation and field understanding.
- **冰室菖蒲:** explanations of many Entry Attributes and research into TIML and Extern subtype structures.
- **003:** detailed analyses of Lightning, StrainRibbon, and Homing.
- **Fexty:** detailed analyses of Blink, Velocity3D/2D, and FadeByEmitterAngle.

Placement, Mesh Drive, and particle-simulation workflows can be used alongside [MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor).

Released under the GPL-3.0-or-later license.

---

<h2 id="中文">中文</h2>

<details>
<summary><b>点击展开中文说明</b></summary>

### MHW EFX Editor

一款在 Blender 中查看、编辑和导出《怪物猎人：世界／冰原》特效文件（`.efx`）的插件。

它将 `.efx` 显示为可展开的 Blender 集合与对象树，以颜色、枚举、位掩码等控件编辑字段；导出时保留未修改的数据。

#### 环境要求与安装

| Blender 版本 | 安装包 |
|---|---|
| 4.3 及以上 | `efx_editor-<版本号>.zip`（扩展包） |
| 3.6–4.2 | `efx_editor-<版本号>-legacy.zip`（传统插件包） |

从 [Releases](../../releases) 下载对应压缩包，不需要解压。在 Blender 的「编辑 → 偏好设置」中，4.3 及以上版本进入「获取扩展」，3.6–4.2 版本进入「插件」，通过右上角菜单选择「从磁盘安装」并选中压缩包。安装并启用后，在 3D 视图按 `N`，打开侧栏中的 **EFX** 标签页。

插件已在 Blender 3.6、4.3 和 5.1 上测试。

##### 第一次使用

1. 在 3D 视图的 **EFX → MHW EFX** 面板中导入 `.efx`，或新建一个 EFX。导入的文件会成为一个可展开的集合。
2. 在大纲视图中选择 Entry、Attribute、Action 等对象；与所选对象相关的面板会出现在 **EFX** 侧栏，Entry 和 Attribute 的部分内容也可在属性编辑器的「对象数据」页查看。
3. 编辑字段或使用 **Add**、**Edit** 面板调整结构。场景里有多个 EFX 时，先检查顶部的 **Active EFX**，避免把新条目加到别的文件。Active EFX 置空时，会使用当前选中对象所在的 EFX 集合。
4. 导出前建议运行 **Validation**，检查引用和结构问题，再导出 `.efx`。校验能发现已知风险，但不能保证游戏中一定正常运行。

#### 主要功能

- 导入、创建和导出 `.efx`；在 Blender 集合与对象树中查看文件结构，增删、重排和复制主要条目。
- 通过数值、枚举、颜色、位掩码等控件编辑属性字段；保存和复用 Entry、属性预设。
- 跟踪 Entry、Action、Extern 之间的引用，并在导出前检查悬空引用、索引等常见问题。
- 编辑 Entry 中的 TIML 动画、材质及 UVS；提供批量颜色工具。
- 在视图中预览粒子和网格运动，并支持与模型、骨骼相关的工作流。粒子模拟是基于观察的近似实现，不能视为游戏内效果的准确预览。
- 提供中英文界面，以及独立的 `.epv3` 轻量编辑功能。

##### 在 Blender 中操作 EFX

**EFX 主面板**提供新建、导入、导出、语言切换、Active EFX 选择、骨架选择、位置同步和导出前校验。导入后，通常先在大纲视图中选中目标，再看随选中对象变化的面板：

| 位置 | 主要用途 |
|---|---|
| **Add** | 新建 Action、Extern、Subselect；在 Entry 与 Attribute 两个标签页间切换。Entry 可从内置基础模板或已保存预设新增；Attribute 可搜索类型，或按分类与子组选择预设。 |
| **Edit** | 对当前条目执行重命名、移动、删除、复制与粘贴等结构操作；可用操作随所选对象变化。 |
| **Entry Status / Activation / Entry References** | 查看 Entry 是否直接触发、是否被 Action 调用，以及与其他条目的引用关系；可切换直接触发状态。这里显示的有效激活状态是插件推导的辅助信息。 |
| **Entry / Attribute / Extern Properties** | 查看并编辑所选对象的数据。Attribute 字段按类型显示为数值、向量、颜色、枚举或位掩码等控件；特殊类型有单独的编辑区。 |
| **Subselect States / Extern Referenced By** | 查看 Subselect 的条目选择状态，或从 Extern 跳转到引用它的位置。 |

Entry 和 Attribute 均可整项复制、粘贴或保存为预设。新增属性时，选中 Entry 或它下面的 Attribute 都可以指定目标；界面还会给出常见缺失属性的建议，但这些建议不是格式合法性规则。删除和重排之后，插件会维护相关索引；复杂引用仍建议在导出前再运行一次校验。

##### 动画、素材与预览

- **TIML**：Entry 内的时间轴可转换为 Blender 的 F 曲线，在 Dope Sheet / Graph Editor 中编辑。轨道可增删、编辑，另有 **EFX TIML** 侧栏编辑相关时间轴设置；也支持独立 `.timl` 文件的导入和编辑。
- **UVS**：在 `UVSEQUENCE` 属性处导入或导出 `.uvs`，并在 Image Editor 的 **UVS** 面板中编辑组、路径槽与帧；可用参考图辅助编辑，也提供 GIF 转 PNG 精灵表工具。独立 `.uvs` 文件也可打开。
- **材质与模型**：`MATERIAL` 有材质块和贴图槽编辑界面，可参考 `.mrl3` 建立材质；`MESH` 可配合模型绑定与 Mesh Drive 预览。自动关联 mod3、材质和贴图的工作流依赖配套插件及资源路径设置。
- **视图辅助**：`TRANSFORM3D` 可用于显示 Entry 的触发位置，并可结合骨架与 `PARENTOPTIONS` 定位；生成区域、UV 滚动、绑定网格运动和粒子模拟均有相应预览工具。它们服务于制作反馈，不保证与游戏渲染一致。
- **色彩编辑器**：Color Tool 可对特效颜色做色相偏移、替换等操作。
- **VFX 工作区**：内置 MHW VFX 工作区（便于 VFX 编辑的界面），可一键添加到当前 Blender 文件。

##### EPV 编辑

插件另提供 3D 视图侧栏的 **EPV** 标签页，用于导入、编辑和导出 `.epv3`。导入后可在对象树中选中 Record，编辑其所属 Group ID、四个 EFX 路径槽、颜色槽、位置与若干原始字段。路径槽可从已导入的 EFX 中选择目标，并在匹配时跳转到对应 EFX。EPV 编辑是辅助功能，不应与 EFX 属性编辑覆盖率混为一谈。

#### `.efx` 的基本结构

下面描述的是插件中的编辑视角，不是文件的字节布局。

| 结构 | 作用 |
|---|---|
| EFX | 一个特效文件；导入后在 Blender 中对应一个集合。 |
| Entry | 特效的主要组成单元，内部按顺序包含多个 Attribute，也可能包含 TIML 动画。部分 Entry 在特效播放时直接触发，其余可被 Action 调用。 |
| TIML | Entry 所含的时间轴数据；在 Blender 中可以按轨道和关键帧编辑。 |
| Attribute | Entry 中带类型的数据块，描述生成、渲染、运动、生命周期等行为。 |
| Action | 由 Entry 中的 `PTLIFE`、`PTCOLLISION` 等引用触发，通过 `PLAYEMITTER` 调用 Entry，或通过 `PLAYEFX` 调用其他外部 `.efx`。 |
| Extern | 提供可供 Entry 引用的替换数据，在特定条件下使用插值过渡替换对应 Entry 的数据。 |
| Subselect | 记录一组 Entry 的选择关系，用于控制参与播放的部分。 |

#### 属性分类与可编辑覆盖

插件目前登记了出现过的全部 **68 种主属性类型**，分为 Entry 骨架、Extern 引用、渲染主体、渲染修饰、生成方式、运动与可见性、Action 扳机、PtBehavior 和其他，共九类。分类主要服务于浏览、创建与预设管理，不代表游戏格式中的真实分类。

**所有主属性均支持完整的解析和编辑**，其中变长类型 `MATERIAL`、`PTBEHAVIOR` 支持专门的模块化增减。“编辑”仅指可以通过插件正常读写，**不代表每个字段的用途都已确认**，大部分字段仍以 `unkn…` 等名称显示。插件在展开字段后会检查能否无损重建原始字节；遇到不匹配或不支持的具体数据实例时，会保留原始数据并关闭该实例的字段编辑，避免误写。

此外，Extern 类型除了 `EXTERNITEM` 不支持编辑，其他 26 种类型均支持字段编辑（包括从未调用过的类型，但未经实际验证可用）。

##### 分类概览

以下是插件用于选择和整理主属性的类别。分类表达的是编辑时的用途，不是所有 Entry 都必须包含各类属性，也不意味着同一类别中的属性一定能任意组合。

| 类别 | 类型数 | 大致用途与例子 |
|---|---:|---|
| Entry 骨架 | 5 | 基础变换、父级关系、生成和生命周期，例如 `TRANSFORM3D`、`LIFE`。 |
| Extern 引用 | 1 | 通过 `EXTERNREFERENCE` 连接 Extern 数据。 |
| 渲染主体 | 9 | 选择 Billboard、Mesh、Ribbon 等表现载体，例如 `BILLBOARD3D`、`MESH`。 |
| 渲染修饰 | 17 | 修改主体的贴图、颜色、材质或渲染表现，例如 `UVSEQUENCE`、`MATERIAL`。 |
| 生成方式 | 6 | 控制粒子或效果的初始分布，例如 `EMITTERSHAPE3D`。 |
| 运动与可见性 | 18 | 控制运动、缩放、旋转以及淡入淡出、隐藏等行为，例如 `VELOCITY3D`、`FADEBYDEPTH`。 |
| Action 扳机 | 2 | `PTLIFE`、`PTCOLLISION`，将生命周期时间或碰撞事件关联到 Action 并触发其引用的其他特效。 |
| PtBehavior | 2 | `PTBEHAVIOR`、`TUBELIGHT` 等特殊独立行为系统。 |
| 其他 | 8 | 不适合归入以上类别的属性，例如 `LAYOUT`、`RANDOMFIX`。 |

属性类型覆盖、字段语义覆盖和预览模拟覆盖是三件不同的事。字段尚未命名并不阻止编辑；相反，某个字段可以编辑，也不表示插件已经确认它在游戏中的效果。对特殊或未见过的数据，建议保留原文件备份并在游戏内验证。

#### 致谢

感谢以下社区成员和项目分享的研究成果与资料：

- MHW-EFX-Template 的历代贡献者：本插件早期的 EFX 解析思路和部分字段命名参考了这一多人协作的 010 Editor 模板。这里链接的是 [UNOWEN-OwO 维护的仓库版本](https://github.com/UNOWEN-OwO/MHW-EFX-Template)。
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki)：提供了 EFX 格式与编辑的基础资料。
- [RE Engine Lib](https://github.com/kagenocookie/RE-Engine-Lib)：为交叉核对属性结构和字段定义提供了参考。
- Crimson：对上述模板及 EFX 属性研究作出了贡献，也帮助改进了本插件的属性分类与字段理解。
- 冰室菖蒲：分享了许多 Entry 属性的作用说明，以及对 TIML 和 Extern 子类结构的研究。
- 003：分享了对 Lightning、StrainRibbon 和 Homing 的详细分析。
- Fexty：分享了对 Blink、Velocity3D/2D 和 FadeByEmitterAngle 的详细分析。

位置定位、Mesh Drive 和粒子模拟等工作流可与 [MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor) 配合使用。

本项目采用 GPL-3.0-or-later 许可证。

</details>
