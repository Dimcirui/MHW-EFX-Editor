# MHW EFX Editor

A Blender add-on for opening, editing and saving **Monster Hunter World: Iceborne** visual
effect files (`.efx`).

It parses an `.efx` into a collection tree you can browse, edits fields with real widgets
(colour wheels, enum dropdowns, bitmask checkboxes) instead of raw hex, and writes the file
back byte-for-byte except where you actually changed something.

> 中文说明见页面底部的 **[中文](#中文)** 折叠块。

---

## Requirements

| Blender | Package to install |
|---|---|
| **4.3 and newer** | `efx_editor-<version>.zip` — the extension package |
| **3.6 – 4.2** | `efx_editor-<version>-legacy.zip` — the legacy add-on package |

Tested on 3.6, 4.3 and 5.1.

## Installation

Download the matching zip from the [Releases](../../releases) page, then:

- **Blender 4.3+** — `Edit > Preferences > Get Extensions`, click the dropdown at the top
  right, choose *Install from Disk*, pick the extension zip.
- **Blender 3.6 – 4.2** — `Edit > Preferences > Add-ons`, click the dropdown at the top
  right, choose *Install from Disk*, pick the `-legacy` zip.

## Getting started

1. Press `N` in the 3D Viewport and open the **EFX** tab in the sidebar.
2. **Import** an `.efx` file, or drag one into the viewport (4.1+). It becomes a collection
   you can expand to browse.
3. Click any part to edit its values in the **EFX** sidebar and the **Object Data** properties tab.
4. Add, remove, reorder or reuse parts. New attributes are inserted at the position the game's
   own files use.
5. Run **Pre-export Validation** to catch problems before they reach the game.
6. **Export** when you are done.

## What you can do

| Feature | | |
|---|---|---|
| **Import / Export** | Read and write `.efx`, including drag-and-drop import | Full |
| **New from scratch** | Create an empty EFX without starting from a file | Full |
| **Structure editing** | Add / delete / reorder / rename / copy-paste Entries, Actions, Externs and Subselect tables — indices and header counts are recalculated for you | Full |
| **Field editing** | Every field gets a widget matched to its type: XYZ vectors, colour wheels with alpha, enum dropdowns, bitmask checkboxes, value+random pairs | Full |
| **Presets** | Save any Entry or Attribute as a reusable preset; 16 ready-made Entry templates ship with the add-on | Full |
| **Reference tracking** | Jump between an Extern and everything pointing at it; see whether an Entry is actually reachable, and through which path | Full |
| **Validation** | Scans for dangling pointers, duplicate indices, 2D/3D mixing and Action call loops before export | Full |
| **TIML animation** | Keyframe tracks become real Blender F-curves — edit them in the Dope Sheet and Graph Editor | Full |
| **UVS editing** | Import, export and visually edit `.uvs` sprite sheets; convert a GIF into a sprite sheet | Full |
| **Material editing** | Add and remove material slots, pick shader types, fill texture slots, clone settings from a reference `.mrl3` | Full |
| **Colour tools** | Shift hue, retint or replace every colour in an effect at once | Full |
| **Bilingual UI** | Switch the whole interface between English and 中文 | Full |
| **Workspace preset** | One click to add a ready-made MHW VFX workspace layout | Full |
| **TRANSFORM3D placement** | Entries sit where the effect actually triggers; snap to an armature and they follow the bound bone | Full |
| **Particle preview** | Play the particle simulation in the viewport | Approximate — see *Known limits* |
| **Mesh binding preview** | Drive a bound mesh from MESH / UVCONTROL / TIML values | Approximate |
| **mod3 auto-link** | Import the mod3 mesh an effect references, together with its materials and textures | Needs the companion MHW Model Editor / Tex add-ons |
| **`.epv` editing** | A lightweight editor for `.epv3` files, with jump-to-EFX linking | Full |

## How an `.efx` file is organised

Simplified — enough to work with, not a format specification.

- **EFX Collection** — one file
  - **Entry** — the core unit. A list of typed components (**Attributes**) that together
    define one particle behaviour. Entries live in two sub-collections: those under
    **Direct Trigger** fire as soon as the effect is played; the rest wait to be called.
  - **Action** — a trigger. Called by an Entry's `PTLIFE` or `PTCOLLISION` attribute, it
    activates one or more target Entries (`PLAYEMITTER`) or other `.efx` files (`PLAYEFX`).
  - **Extern** — a field replacer. When its condition is met, an Extern swaps in different
    values for the fields of an Attribute inside an Entry.
  - **Subselect Table** — a named subset of Entries, used to decide which parts of the
    effect play under which conditions.

## Attribute coverage

All **68 attribute types** parse and round-trip byte-perfectly, and all of them are
field-editable. What differs is **how many of their fields have a known meaning** — an
unnamed field still shows up and is still safe to edit, it just carries an `unkn…` label
instead of a real name.

Each group below shows two numbers: what share of **its own fields** have real names, and what
share of **the attributes you actually meet** it accounts for — the latter measured across the
game's own effect files.

### Fully labelled — 30 types · 97% of their fields named

These account for **84%** of the attributes you will actually meet.

| Group | Types |
|---|---|
| Entry Skeleton | `TRANSFORM3D` `TRANSFORM2D` `PARENTOPTIONS` `SPAWN` `LIFE` |
| ExternReference | `EXTERNREFERENCE` |
| Renderer Body | `BILLBOARD3D` `BILLBOARD2D` `PLANE` |
| Renderer Modifier | `UVSEQUENCE` `RGBFIRE` `RGBWATER` `BLINK` `REFRACTION` `UVCONTROL` |
| Generation Method | `EMITTERSHAPE3D` `EMITTERSHAPE2D` `RAYCAST` |
| Motion & Visibility | `VELOCITY3D` `VELOCITY2D` `SCALEANIM` `ROTATEANIM` `NOISE` `HOMING` `FADEBYDEPTH` `FADEBYANGLE` `FADEBYOCCLUSION` `SCREENSPACECOLLISION` `MASTERONLY` |
| Misc | `RANDOMFIX` |

### Mostly labelled — 19 types · 67% of their fields named

Main behaviour is known; some fields' purpose is not. **6%** of what you will meet.

| Group | Types |
|---|---|
| Renderer Body | `MESH` `RIBBON` `RIBBONBLADE` `STRAINRIBBON` `DUMMY` |
| Renderer Modifier | `ALPHACORRECTION` `LUMINANCEBLEED` `PLEMISSIVE` `PARENTEMISSIVE` `PLSNOW` |
| Motion & Visibility | `FADEBYEMITTERANGLE` `GUIDE` `TURBULENCE` |
| Action Trigger | `PTLIFE` `PTCOLLISION` |
| PtBehavior | `TUBELIGHT` |
| Misc | `SHOVEL` `PTTRIGGER` `TONEMAPFILTER` |

### Partly labelled — 17 types · 27% of their fields named

Editable, but most fields still carry `unkn…` names. **9%** of what you will meet.

| Group | Types |
|---|---|
| Renderer Body | `LIGHTNING` |
| Renderer Modifier | `SHADERSETTINGS` `FAKEPLANE` `PARENTSNOW` `OTOMOSNOW` `PARENTMATERIAL` |
| Generation Method | `EMITTERSHAPEMESH` `SPAWNBYANGLE` `SPAWNBYOCCLUSION` |
| Motion & Visibility | `EMITTERBOUNDARY` `PATHCHAIN` `REPEATAREA` `LINKPARTSVISIBLE` |
| Misc | `LAYOUT` `FAKEDOF` `COLORCORRECTFILTER` `CHECKPUREATTRIBUTE` |

Nearly all of this group's 9% is `SHADERSETTINGS` alone, which appears in most effect files.
Its common fields (render layer, depth bias, soft-particle distance, preset) are labelled;
the rest are not.

### Dynamic structure — 2 types

`MATERIAL` and `PTBEHAVIOR` do not have a fixed field list — their contents depend on the
shader or behaviour type in use. Both have their own dedicated editors rather than a flat
field list.

## Extern coverage

**26 of the 27** Extern data types can be edited field by field. `EXTERNITEM` is passed
through read-only.

Eight types — `EXTERNFADEBYANGLE`, `EXTERNFADEBYDEPTH`, `EXTERNUVCONTROL`, `EXTERNGUIDE`,
`EXTERNPARENTSNOW`, `EXTERNOTOMOSNOW`, `EXTERNSTRAINRIBBON`, `EXTERNTURBULENCE` — never occur
in the game's own files, so their field layout is inferred rather than observed. The add-on
marks them **(fabricated)** in the UI. If you meet one in a real file, check the bytes before
trusting the layout.

## Known limits

- **Unlabelled fields.** About a third of all fields still carry `unkn…` names — though weighted
  by how often you actually meet them, closer to one in six. They are editable and round-trip
  safely, but you are on your own as to what they do.
- **Validation is not a guarantee.** It catches the failure modes that are known to crash the
  game. It cannot catch everything.
- **Particle preview is an approximation.** It is a reimplementation of the effect system for
  authoring feedback, not the game's renderer. Some attribute types are not simulated at all,
  and the panel lists which ones. Treat it as a sketch, not a preview render.
- **Some values are deliberately left alone.** A few header values have no known formula and
  are written back exactly as they came in. Changing them by hand can crash the game.

## Credits

Built on community documentation and format research, with help from many people:

- [UNOWEN-OwO/MHW-EFX-Template](https://github.com/UNOWEN-OwO/MHW-EFX-Template) — the parsing
  approach and the initial parameter names come from these templates.
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki)
  — the basic explanation of how `.efx` works.
- [RE Engine Lib](https://github.com/kagenocookie/RE-Engine-Lib) — a wealth of material for
  cross-checking attribute definitions.
- **Crimson** — attribute categorisation, and the insight behind many attributes.
- **冰室菖蒲** — guides on Entry attributes and on the structure of EFX TIML.
- **003** — detailed guides on Lightning, StrainRibbon and Homing.
- **Fexty** — detailed guides on Blink, Velocity3D/2D and FadeByEmitterAngle.

Bone placement is designed to pair with the
[MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor).

Released under the GPL-3.0-or-later license.

---

<h2 id="中文">中文</h2>

<details>
<summary><b>点击展开中文说明</b></summary>

### MHW EFX 编辑器

编辑《怪物猎人：世界／冰原》特效文件（`.efx`）的 Blender 插件。

它把 `.efx` 解析成可以展开浏览的集合树，用真正的控件（色轮、枚举下拉、位掩码勾选）编辑字段，
而不是让你对着十六进制改；导出时除了你实际改过的地方，其余字节原样写回。

### 环境要求

| Blender | 装哪个包 |
|---|---|
| **4.3 及以上** | `efx_editor-<版本>.zip` —— 扩展包 |
| **3.6 – 4.2** | `efx_editor-<版本>-legacy.zip` —— 旧式 addon 包 |

已在 3.6、4.3、5.1 上测试。

### 安装

从 [Releases](../../releases) 页下载对应的 zip，然后：

- **Blender 4.3+** —— `编辑 > 偏好设置 > 获取扩展`，点右上角下拉箭头，选 *从磁盘安装*，选扩展 zip。
- **Blender 3.6 – 4.2** —— `编辑 > 偏好设置 > 插件`，点右上角下拉箭头，选 *从磁盘安装*，选 `-legacy` zip。

### 上手

1. 在 3D 视图里按 `N`，打开侧栏的 **EFX** 标签页。
2. **导入**一个 `.efx`，或者直接把文件拖进视图（4.1+）。它会变成一个可以展开浏览的集合。
3. 点任意部件，在 **EFX** 侧栏和**物体数据**属性页里改它的值。
4. 增删、重排、复用部件。新加的属性会自动插到游戏自己的文件所用的位置。
5. 点**导出前校验**，在问题进游戏之前把它抓出来。
6. 改完**导出**。

### 能做什么

| 功能 | | |
|---|---|---|
| **导入 / 导出** | 读写 `.efx`，支持拖入导入 | 完整 |
| **从零新建** | 不用先有文件就能搭特效 | 完整 |
| **结构编辑** | Entry / Action / Extern / Subselect 表的增删、重排、改名、复制粘贴——索引和头部计数自动重算 | 完整 |
| **字段编辑** | 每个字段按真实类型给控件：XYZ 向量、带 alpha 的色轮、枚举下拉、位掩码勾选、固定值+随机值配对 | 完整 |
| **预设** | 任意 Entry 或属性存成可复用预设；随插件附带 16 个开箱即用的 Entry 模板 | 完整 |
| **引用追踪** | 在 Extern 和指向它的东西之间跳转；查看某个 Entry 到底会不会被激活、经由哪条路径 | 完整 |
| **导出前校验** | 扫描悬空指针、索引重复、2D/3D 混用、Action 调用成环 | 完整 |
| **TIML 动画** | 关键帧轨道变成真正的 Blender F 曲线，在摄影表和曲线编辑器里直接编辑 | 完整 |
| **UVS 编辑** | 导入导出并可视化编辑 `.uvs` 序列帧；GIF 可转精灵表 | 完整 |
| **材质编辑** | 增删材质槽、选着色器类型、填贴图槽、从参考 `.mrl3` 克隆设置 | 完整 |
| **调色工具** | 一次性对整个特效做色相偏移、统一换色、直接替换 | 完整 |
| **双语界面** | 整个界面一键切换中英文 | 完整 |
| **工作区预设** | 一键添加内置的 MHW VFX 工作区布局 | 完整 |
| **TRANSFORM3D 摆位** | Entry 摆在特效实际触发的位置；吸附到骨架后会跟随绑定的骨骼 | 完整 |
| **粒子预览** | 在视口里播放粒子模拟 | 近似——见「已知限制」 |
| **绑定网格预览** | 用 MESH / UVCONTROL / TIML 的值驱动绑定的网格 | 近似 |
| **mod3 联动导入** | 自动导入特效引用的 mod3 网格及其材质、贴图 | 需要配套的 MHW Model Editor / Tex 插件 |
| **`.epv` 编辑** | `.epv3` 的轻量编辑器，可与 EFX 互相跳转 | 完整 |

### `.efx` 是怎么组织的

简化说明，够用即可，不是格式规范。

- **EFX 集合** —— 一个文件
  - **Entry** —— 核心单元。由若干有类型的部件（**属性**）组成，共同定义一种粒子行为。
    Entry 分在两个子集合里：**Direct Trigger** 下的会在特效播放时立即触发，其余的等人来叫。
  - **Action** —— 触发器。由某个 Entry 的 `PTLIFE` 或 `PTCOLLISION` 属性调用，激活一个或多个
    目标 Entry（`PLAYEMITTER`）或别的 `.efx` 文件（`PLAYEFX`）。
  - **Extern** —— 字段替换器。条件满足时，把 Entry 内某个属性的字段换成另一组值。
  - **Subselect 表** —— Entry 的具名子集，用来决定什么条件下播特效的哪些部分。

### 属性覆盖情况

**68 种属性类型**全部能解析、能位精确往返，且全部可以逐字段编辑。区别在于**有多少字段已经知道
是干什么的**——没命名的字段照样显示、照样能安全编辑，只是挂着 `unkn…` 而不是真名字。

下面每一档给两个数：这一档**自身字段**的命名率，以及它占**你实际会遇到的属性**的比重
（后者按游戏自己的特效文件统计）。

#### 命名齐全 —— 30 种 · 字段命名率 97%

占你**实际会遇到**的属性的 **84%**。

| 分组 | 类型 |
|---|---|
| Entry 骨架 | `TRANSFORM3D` `TRANSFORM2D` `PARENTOPTIONS` `SPAWN` `LIFE` |
| ExternReference | `EXTERNREFERENCE` |
| 渲染主体 | `BILLBOARD3D` `BILLBOARD2D` `PLANE` |
| 渲染修饰 | `UVSEQUENCE` `RGBFIRE` `RGBWATER` `BLINK` `REFRACTION` `UVCONTROL` |
| 生成方式 | `EMITTERSHAPE3D` `EMITTERSHAPE2D` `RAYCAST` |
| 运动与可见性 | `VELOCITY3D` `VELOCITY2D` `SCALEANIM` `ROTATEANIM` `NOISE` `HOMING` `FADEBYDEPTH` `FADEBYANGLE` `FADEBYOCCLUSION` `SCREENSPACECOLLISION` `MASTERONLY` |
| Misc | `RANDOMFIX` |

#### 主干清楚 —— 19 种 · 字段命名率 67%

主要行为已知，部分字段作用未知。占你会遇到的 **6%**。

| 分组 | 类型 |
|---|---|
| 渲染主体 | `MESH` `RIBBON` `RIBBONBLADE` `STRAINRIBBON` `DUMMY` |
| 渲染修饰 | `ALPHACORRECTION` `LUMINANCEBLEED` `PLEMISSIVE` `PARENTEMISSIVE` `PLSNOW` |
| 运动与可见性 | `FADEBYEMITTERANGLE` `GUIDE` `TURBULENCE` |
| Action 触发 | `PTLIFE` `PTCOLLISION` |
| PtBehavior | `TUBELIGHT` |
| Misc | `SHOVEL` `PTTRIGGER` `TONEMAPFILTER` |

#### 命名不全 —— 17 种 · 字段命名率 27%

可以编辑，但多数字段仍挂着 `unkn…`。占你会遇到的 **9%**。

| 分组 | 类型 |
|---|---|
| 渲染主体 | `LIGHTNING` |
| 渲染修饰 | `SHADERSETTINGS` `FAKEPLANE` `PARENTSNOW` `OTOMOSNOW` `PARENTMATERIAL` |
| 生成方式 | `EMITTERSHAPEMESH` `SPAWNBYANGLE` `SPAWNBYOCCLUSION` |
| 运动与可见性 | `EMITTERBOUNDARY` `PATHCHAIN` `REPEATAREA` `LINKPARTSVISIBLE` |
| Misc | `LAYOUT` `FAKEDOF` `COLORCORRECTFILTER` `CHECKPUREATTRIBUTE` |

这 9% 里几乎全是 `SHADERSETTINGS` 一家，它出现在绝大多数特效文件里。它的常用字段
（渲染层、深度偏移、软粒子距离、预设）已命名，其余未命名。

#### 动态结构 —— 2 种

`MATERIAL` 和 `PTBEHAVIOR` 没有固定字段表，内容取决于当前用的着色器或行为类型。
两者都有各自的专用编辑器，不走平铺字段列表。

### Extern 覆盖情况

**27 种 Extern 数据类型里有 26 种**可以逐字段编辑，只有 `EXTERNITEM` 是只读直通。

其中 8 种——`EXTERNFADEBYANGLE`、`EXTERNFADEBYDEPTH`、`EXTERNUVCONTROL`、`EXTERNGUIDE`、
`EXTERNPARENTSNOW`、`EXTERNOTOMOSNOW`、`EXTERNSTRAINRIBBON`、`EXTERNTURBULENCE`——在游戏自己的
文件里从未出现过，它们的字段布局是推断的而非观测到的。插件在界面上给这些类型标了
**(fabricated)**。如果你在真实文件里碰到其中一种，先核对字节再信这套布局。

### 已知限制

- **未命名字段。** 全部字段里约三分之一仍挂着 `unkn…`；但按实际遇到的频率加权，大约六分之一。
  它们可以编辑、往返安全，但具体作用得你自己摸。
- **校验不是保证。** 它能抓到已知会让游戏崩溃的那些写法，抓不全。
- **粒子预览是近似的。** 它是为了给作者反馈而重新实现的一套特效系统，不是游戏的渲染器。
  有些属性类型完全没模拟，面板里列出了是哪些。当草稿看，别当预览渲染看。
- **有些值刻意不动。** 少数头部数值没有已知公式，导出时原样写回。手改可能让游戏崩溃。

### 致谢

基于社区文档和格式研究，并得到许多人的帮助：

- [UNOWEN-OwO/MHW-EFX-Template](https://github.com/UNOWEN-OwO/MHW-EFX-Template) —— 本插件的解析
  方法和最初的参数命名源自这些模板。
- [怪物猎人世界 Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki)
  —— 提供了 efx 的基础说明。
- [RE Engine Lib](https://github.com/kagenocookie/RE-Engine-Lib) —— 为属性定义的交叉印证提供了
  大量有价值的材料。
- **Crimson** —— 属性分类思路，以及许多属性的启发。
- **冰室菖蒲** —— 大量 Entry 属性的用法说明，以及 efx TIML 的结构。
- **003** —— Lightning、StrainRibbon、Homing 的详细用法说明。
- **Fexty** —— Blink、Velocity3D/2D、FadeByEmitterAngle 的详细用法说明。

骨骼摆位设计为与 [MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor) 配合使用。

以 GPL-3.0-or-later 许可发布。

</details>
