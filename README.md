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
4. Use the sidebar buttons to add, remove, reorder, and reuse parts.
5. Click `Pre-export Validation` to check potential errors & warnings before export.
6. **Export** when you're finished.

## Basic structure

For reference only. This interpretation does not reflect the actual structure of .efx file and may not be accurate.

- **EFX Collection**
  - **EFX Sections**
    1. **Body/Main**: The core EFX unit.
       
       Composed of typed Components (**Blocks**) that together define particle behaviors (transforms, emission, rendering, color and more).
    2. **Play**: An action trigger.
       
       Called by a Body's PTLIFE or PTCOLLISION block; activates one or more target Bodies (**PLAYEREMIITER**) or external EFX files (PLAYER.
    3. **Extern**: EFX Body replacer(?)
       
       There are two types, replacement parameters and external EFX references.
       The former replaces the corresponding parameter in the block within the body when some conditions are met;
       the specific mechanism of the latter is not yet clear.
  - **EFX Subselect Table**: A subset of Bodies. Determines which EFX blocks from which subsets to call under some conditions.

## Supported Operations & Features

> **Note:** All add, remove, reorder, and paste operations must be done through the **EFX sidebar panel**
> (`N` key). Do not rename, move, or delete the generated objects directly in the outliner — the add-on
> manages the structure internally.

### 1. Sections

Universal section operations: **Add** (from preset) / **Delete** / **Reorder** (move up/down within body) / **Copy whole Body** / **Paste whole Body** / **Rename** / **Save** (to preset).

| Section | Add | Delete | Edit | Note |
|---|---|---|---|---|
| **Play** | ✓ | ✓ | ✓ | |
| **Extern** | **Partial** | ✓ | **Partial** | EXTERN-SPAWN/RGBFIRE/VELOCITY3D/SCALEANIM/TRANSFORM3D add&edit |
| **Body / Main** | ✓ | ✓ | ✓ | TIML editable via .timl file import/export |

### 2. Subselection Table

Fully Supported

### 3. Body Block

Universal block operations: **Add** (from preset) / **Delete** / **Reorder** (move up/down within body) / **Copy whole block** / **Paste whole block** / **Copy field values** / **Paste field values** / **Save** (to preset).

#### I. Body Skeleton (required in every EFX Body)

| Block Type | Field Editing |
|---|---|
| TRANSFORM3D | ✓ |
| PARENTOPTIONS | ✓ |
| SPAWN | ✓ |
| LIFE | ✓ |

#### II. Renderer (can be mutually exclusive)

| Block Type | Field Editing |
|---|---|
| BILLBOARD3D | ✓ |
| PLANE | ✓ |
| RIBBON | ✓ |
| RIBBONBLADE | ✓ |
| STRAINRIBBON | ✓ |
| MESH | ✓ |
| LIGHTNING | ✓ |
| DUMMY | ✓ |

#### III. Sprite Modifiers (face-rendered only, can be conflict with MESH)

| Block Type | Field Editing |
|---|---|
| UVSEQUENCE | ✓ |
| RGBFIRE | ✓ |
| RGBWATER | ✓ |
| ALPHACORRECTION | ✓ |
| REFRACTION | ✓ |
| BLINK | ✓ |
| LUMINANCEBLEED | ✓ |

#### IV. Mesh Overrides (probably require MESH)

| Block Type | Field Editing |
|---|---|
| UVCONTROL | ✓ |
| MATERIAL | **Partial** — texture path slots (tAlbedoMap, etc.) editable only |

#### V. Emitter / Space

| Block Type | Field Editing |
|---|---|
| EMITTERSHAPE3D | ✓ |
| EMITTERSHAPE2D | ✓ |
| EMITTERBOUNDARY | ✓ |

#### VI. Motion / Velocity

| Block Type | Field Editing |
|---|---|
| VELOCITY3D | ✓ |
| SCALEANIM | ✓ |
| ROTATEANIM | ✓ |
| NOISE | ✓ |
| TURBULENCE | ✓ |
| HOMING | ✓ |
| GUIDE | ✓ |
| SCREENSPACECOLLISION | ✓ |

#### VII. Visibility / Fade

| Block Type | Field Editing |
|---|---|
| FADEBYDEPTH | ✓ |
| FADEBYANGLE | ✓ |
| FADEBYEMITTERANGLE | ✓ |
| SHADERSETTINGS | ✓ |
| MASTERONLY | ✓ |
| RAYCAST | ✓ |

#### VIII. Lifecycle Triggers (almost certainly last in body)

| Block Type | Field Editing |
|---|---|
| PTCOLLISION | ✓ |
| PTLIFE | ✓ |
| PTBEHAVIOR | **Partial** — existing parameters editable only |

#### IX. Extern Declaration (almost certainly first in body)

| Block Type | Field Editing |
|---|---|
| EXTERNREFERENCE | ✓ |

#### X. Char Effects

| Block Type | Field Editing |
|---|---|
| PLEMISSIVE | ✓ |
| PARENTEMISSIVE | ✓ |
| PLSNOW | ✓ |
| SHOVEL | ✓ |

#### XI. Misc / Control

| Block Type | Field Editing |
|---|---|
| RANDOMFIX | ✓ |

### 3. Other Features
- **TRANSFORM3D Visualization** — Reflects the actual trigger position of the EFX Body.
  This feature uses the same coordinate system as the MHW Model Editor.
- **Place Effects on an Armature** — effects snap to the bone (decided in PARENTOPTIONS) they belong to when you load a matching
  skeleton, so you can see them where they actually appear in-game.
  This feature relies on armatures imported via the MHW Model Editor.
- **Pre-export Validation** — Check for errors & warnings that could cause the game to crash, such as null pointers, Play loop, block order, etc.
  This feature does not guarantee that errors will never occur.
- **Activation & Reference Status Check** — Display the calls to and from the selected Body, as well as its activation status.
- **Hex View** — You can copy the entire hex value of a specific block, edit it, and then paste it back (ensuring that the bytes remain exactly the same).

## Credits

This add-on builds on community documentation and format research. In particular:

- [UNOWEN-OwO/MHW-EFX-Template](https://github.com/UNOWEN-OwO/MHW-EFX-Template) — the source of most of
  the 010 Editor format templates this add-on is built on.
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki) — the
  community knowledge base.

Bone placement is designed to pair with the
[MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor).

Released under the GPL-3.0-or-later license.
