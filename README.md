# MHW EFX Editor

A Blender add-on for opening, editing, and saving **Monster Hunter World: Iceborne** visual
effect files (`.efx`).

It loads an effect into Blender as a tidy, browsable tree so you can tweak its values, rearrange or
remove parts, and save it back into the game — no hex editor required. Anything you don't touch is
saved back exactly as it was.

---

## What you can do

- **Open and save `.efx` files** — import from a file or just drag one into the viewport, then export
  when you're done.
- **Edit effect values** — colors (with a full color wheel and transparency), sizes, timing, randomness,
  and more, all with readable names and ⓘ hover tips explaining what each one does.
- **Rearrange and remove parts** — reorder, delete, copy, and paste pieces of an effect. Links between
  parts fix themselves automatically, so nothing breaks when you move things around.
- **Reuse pieces with presets** — save a block or a whole body and drop it into another effect later.
- **Place effects on a character** — effects snap to the bone they belong to when you load a matching
  skeleton, so you can see them where they actually appear in-game.

> **Note:** All add, remove, reorder, and paste operations must be done through the **EFX sidebar panel**
> (`N` key). Do not rename, move, or delete the generated objects directly in the outliner — the add-on
> manages the structure internally.

---

## Requirements

- Blender 3.x or newer. Tested on 3.6, 4.3 and 5.1

---

## Installation

1. Click Code > Download Zip.
2. (For blender 3.x to 4.1) In Blender, go to Edit > Preferences > Addons, click the arrow in the top right of the addon menu and choose "Install From Disk".
3. (For blender 4.2+) Drag in and confirm install.

---

## Getting started

1. Press `N` in the 3D Viewport and open the **EFX** tab in the sidebar.
2. **Import** an `.efx` file (or drag it into the viewport). It appears as a collection you can expand to
   browse its parts.
3. Click a part to see and edit its values in the **EFX** sidebar and the **Object Data** properties tab.
4. Use the sidebar buttons to add, remove, reorder, and reuse parts.
5. **Export** when you're finished. The add-on checks for problems first and warns you before saving if
   something would break.

---

## Notes & credits

A couple of more complex block types (materials and particle behavior) can't be fully broken out into
editable fields yet — you can still edit their texture/file paths or view them as raw data, and they're
always saved back safely.

This add-on builds on community documentation and format research. In particular:

- [UNOWEN-OwO/MHW-EFX-Template](https://github.com/UNOWEN-OwO/MHW-EFX-Template) — the source of most of
  the 010 Editor format templates this add-on is built on.
- [Monster Hunter World Modding Wiki](https://github.com/Ezekial711/MonsterHunterWorldModding/wiki) — the
  community knowledge base.

Bone placement is designed to pair with the
[MHW Model Editor](https://github.com/chikichikibangbang/MHW_Model_Editor).

Released under the GPL-3.0-or-later license.
