# MHW EFX Editor

A Blender add-on for opening, editing, and saving **Monster Hunter World: Iceborne** visual
effect files (`.efx`).

## Requirements

- Blender 3.x or newer. Tested on 4.3, 5.1 and 3.6

## Installation

1. Click Code > Download Zip.
2. In Blender, go to Edit > Preferences > Addons, click the arrow in the top right of the addon menu and choose "Install From Disk".

## Getting started

1. Press `N` in the 3D Viewport and open the **EFX** tab in the sidebar.
2. **Import** an `.efx` file (or drag it into the viewport). It appears as a collection you can expand to
   browse its parts.
3. Click a part to see and edit its values in the **EFX** sidebar and the **Object Data** properties tab.
4. Add, remove, reorder, or reuse parts.
5. Click `Pre-export Validation` to check potential errors & warnings before export.
6. **Export** when you're finished.

## Basic structure

For reference only. This interpretation does not reflect the actual structure of .efx file and may not be accurate.

- **EFX Collection**
  - **EFX Sections**
    1. **Entry**: The core EFX unit.
       
       Composed of typed Components (**Attributes**) that together define particle behaviors.
       There are two sub-collections `Direct Trigger` and `Not Direct Trigger`. Entries that are in `Direct Trigger` will be triggered directly once calling.
    3. **Action**: Efx trigger.
       
       Called by an Entry's PTLIFE or PTCOLLISION attribute; activates one or more target Entries (**PLAYEMITTER**) or external EFX files (**PLAYEFX**).
    4. **Extern**: Attribute fields' replacer.
       
       An Extern replaces the corresponding parameter in the attribute within the entry when some conditions are met.
  - **EFX Subselect Table**: A subset of Entries. Determines which EFX attributes from which subsets to call under some conditions.
 

## Features
- **Entry/Attribute Presets** — Save any Entries or Attributes as preset for future use.
- **EPV Edit** — Basic .epv edition.
- **UVS Edit** — Import/export and edit .uvs file at any UVSEQUENCE attribute. Gif to sequence png is also supported.
- **File Validation** — Check for errors & warnings that could cause the game to crash, such as Action loop, 2d/3d type mismatching, etc.
  This feature does not guarantee that errors will never occur.
- **Activation & Reference Status Check** — Display the calls to and from the selected Entry, as well as its activation status.
- **TRANSFORM3D Visualization** — Reflects the actual trigger position of the EFX Entry.
  After you snap it to any armature, efx entries can also snap to the bone binded (decided by PARENTOPTIONS).
  This feature uses the same coordinate system as the MHW Model Editor.

## Supported Operations

### 1. Sections

Universal section operations: **Add** / **Delete** / **Reorder** / **Copy & Paste** / **Rename**.

| Section | Add | Delete | Edit | Note |
|---|---|---|---|---|
| **Action** | ✓ | ✓ | ✓ | |
| **Extern** | **Partial** | ✓ | **Partial** | all editable except `EXTERNVELOCITY3D2`/`5`/`7` |
| **Entry** | ✓ | ✓ | ✓ | TIML fully editable through blender's animation tools |

### 2. Subselection Table

Fully Supported

### 3. Entry Attributes

Universal attribute operations: **Add** (from preset) / **Delete** / **Reorder** / **Copy & Paste** / **Save as preset**.

#### I. Entry Skeleton (required in every EFX Entry)

| Attribute Type | Field Editing |
|---|---|
| TRANSFORM3D | ✓ |
| PARENTOPTIONS | ✓ |
| SPAWN | ✓ |
| LIFE | ✓ |

#### II. Renderer (can be mutually exclusive)

| Attribute Type | Field Editing |
|---|---|
| BILLBOARD3D | ✓ |
| PLANE | ✓ |
| RIBBON | ✓ |
| RIBBONBLADE | ✓ |
| STRAINRIBBON | ✓ |
| MESH | ✓ |
| LIGHTNING | ✓ |
| TUBELIGHT | ✓ |
| FAKEPLANE | ✓ |
| DUMMY | ✓ |

#### III. Sprite Modifiers (face-rendered only, can conflict with MESH)

| Attribute Type | Field Editing |
|---|---|
| SHADERSETTINGS | ✓ |
| UVSEQUENCE | ✓ |
| RGBFIRE | ✓ |
| RGBWATER | ✓ |
| ALPHACORRECTION | ✓ |
| REFRACTION | ✓ |
| BLINK | ✓ |
| LUMINANCEBLEED | ✓ |

#### IV. Mesh Overrides (require MESH)

| Attribute Type | Field Editing |
|---|---|
| UVCONTROL | ✓ |
| MATERIAL | **Partial** |

#### V. Emitter / Space

| Attribute Type | Field Editing |
|---|---|
| EMITTERSHAPE3D | ✓ |
| EMITTERSHAPEMESH | ✓ |
| EMITTERBOUNDARY | ✓ |
| SPAWNBYANGLE | ✓ |
| SPAWNBYOCCLUSION | ✓ |

#### VI. Motion / Velocity

| Attribute Type | Field Editing |
|---|---|
| VELOCITY3D | ✓ |
| SCALEANIM | ✓ |
| ROTATEANIM | ✓ |
| NOISE | ✓ |
| TURBULENCE | ✓ |
| HOMING | ✓ |
| GUIDE | ✓ |
| PATHCHAIN | ✓ |
| SCREENSPACECOLLISION | ✓ |

#### VII. Visibility / Fade

| Attribute Type | Field Editing |
|---|---|
| FADEBYDEPTH | ✓ |
| FADEBYANGLE | ✓ |
| FADEBYEMITTERANGLE | ✓ |
| FADEBYOCCLUSION | ✓ |
| MASTERONLY | ✓ |
| RAYCAST | ✓ |
| LINKPARTSVISIBLE | ✓ |

#### VIII. Lifecycle Triggers (almost certainly last in entry)

| Attribute Type | Field Editing |
|---|---|
| PTCOLLISION | ✓ |
| PTLIFE | ✓ |
| PTTRIGGER | ✓ |
| SHOVEL | ✓ |

#### IX. Extern Declaration (almost certainly first in entry)

| Attribute Type | Field Editing |
|---|---|
| EXTERNREFERENCE | ✓ |

#### X. Char Effects

| Attribute Type | Field Editing |
|---|---|
| PLEMISSIVE | ✓ |
| PARENTEMISSIVE | ✓ |
| PLSNOW | ✓ |
| PARENTSNOW | ✓ |
| OTOMOSNOW | ✓ |
| PARENTMATERIAL | ✓ |

#### XI. Behavior System (standalone, mutually exclusive with normal flow)

| Attribute Type | Field Editing |
|---|---|
| PTBEHAVIOR | ✓ |

#### XII. 2D / UI Variants (for 2D effects — functional 2D equivalents of their 3D counterparts; many 3D attributes do not apply when these are present)

| Attribute Type | Field Editing | 3D Equivalent Section |
|---|---|---|
| TRANSFORM2D | ✓ | I. Entry Skeleton |
| EMITTERSHAPE2D | ✓ | V. Emitter / Space |
| VELOCITY2D | ✓ | VI. Motion / Velocity |
| BILLBOARD2D | ✓ | II. Renderer |

#### XIII. Misc / Control

| Attribute Type | Field Editing |
|---|---|
| RANDOMFIX | ✓ |
| CHECKPUREATTRIBUTE | ✓ |
| TONEMAPFILTER | ✓ |
| COLORCORRECTFILTER | ✓ |
| FAKEDOF | ✓ |
| REPEATAREA | ✓ |
| LAYOUT | ✓ |

## Credits

This plugin was developed based on community documentation and format research, as well as with the help of many people. In particular:

- [UNOWEN-OwO/MHW-EFX-Template](https://github.com/UNOWEN-OwO/MHW-EFX-Template) — The parsing method and initial parameter names used in this plugin are based on these templates.
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki) — Provided a basic explanation of efx.
- [REE Lib](https://github.com/kagenocookie/RE-Engine-Lib) — Provides a wealth of valuable information for cross-validation of attributes.
- Crimson — Provided insights into Attribute categorization and inspiration for many attributes.
- 冰室菖蒲 — Provides guides on the Attributes for numerous Entries, as well as the structure of efx TIML.
- 003 — Provides detailed guides on the Attributes for Lightning, StrainRibbon, and Homing.
- Fexty — Provides detailed guides on the Attributes for Blink and FadeByEmitterAngle.

Bone placement is designed to pair with the
[MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor).

Released under the GPL-3.0-or-later license.
