# core (Digitakt II)

The boot copier and the hook bus for Digitakt II OS 1.17. Every set of
linkable (format 2) mods for the Digitakt II needs it. On its own it changes
nothing the unit does.

It builds the shared [../core/core.s](../core/core.s),
[settings.s](../core/settings.s) and [fast.s](../core/fast.s) with the
Digitakt II's addresses (`mod.json`), and its own
[personalize.s](personalize.s). The render hooks (`render.s`) are not
in it: the Digitakt II renders its audio on the DSP.

- **At boot** (the OS entry's call at 0x40000538, which called 0x400019b0,
  as on the mk1), `boot` copies the RAM image the linker built to the
  device's DDR area (0x47F00000), zeroes `.bss`, and goes on to the call it
  replaced. Unlike the mk1's core it does not start the DTIM0 counter
  (`NO_DTIM0`): the OS reads it at ten sites (0xfc07000c) and nothing on the
  unit starts it, so stock reads it as stopped, and this core keeps that.
  A mod that wants a time base cannot use DTIM0 here.
- **The shared sites** become the events `ev_tick`, `ev_draw`, `ev_key`,
  `ev_enc`, `ev_settings` and, the Digitakt II's own, `ev_personalize`, with the same prototypes as on the mk1
  ([docs/ADAPTING.md](../../docs/ADAPTING.md), "The hook bus"):

  | site | was | event |
  |---|---|---|
  | 0x40032ad4 | `jsr 0x4011bc60`: returns the view controller's byte +0x20 | `ev_tick` |
  | 0x40032b3a | `jsr 0x4011bc96`: `drawAll(ctrl, bmp)`, the 128x64 frame | `ev_draw` |
  | 0x40033d94 | `jsr 0x40030bd0`: `Brain::key(brain, event)` | `ev_key` |
  | 0x40033dde | `jsr 0x40030b64`: `Brain::enc(brain, event)` | `ev_enc` |
  | 0x400a5eac | `movea.l (a2),a0; pea 2.w`, the SETTINGS builder 0x400a5b04 going on at 0x400a5eb2 | `ev_settings` |
  | 0x4009e2a2 | `movem.l $18(a7),d2-d6/a2-a6`, the end of the PERSONALIZE builder 0x4009daec, after TRK SELECT | `ev_personalize` |

  `core_additem(menu, row)` adds a SETTINGS row, after SYSTEM, with the
  firmware's routines: `operator new` 0x4011ebd0, `MenuItem`'s constructor
  0x40115a44, `Menu::addItem` 0x4011527a and the `std::function` manager
  0x4019d8a8 (for `PFSs15FileStorageInfoE`, as on the mk1). A row's label
  callback builds a `std::string` with 0x401e7e7a. PERSONALIZE's rows are
  the same generic `MenuItem`, so `core_additem` adds them there too, from
  `ev_personalize`; such a row redraws with `View::invalidate(menu + 0x38)`
  (0x4011b126), and draws a checkbox as the firmware's do: `blit` 0x40114168
  of one of the two Bitmaps (0x1c bytes each, empty then ticked) at
  `*(char **)0x44f34554`.
- **`.fast` code** (`fast.s`): core declares the copy table `core_fast`,
  and its `ev_tick` handler copies every mod's `.fast` section into the SRAM
  tail (0x8000F100-0x80010000) on the first tick, once: the OS zeroes SRAM
  after the boot copier runs.

Each site and routine was found by the mk1's code, with the addresses
masked: the UI loop's dirty check and frame composition, the key and
encoder events built from the UI queue's message, and the SETTINGS
builder's last row (its rows are the mk1's, less SAMPLES and GLOBAL FX/MIX,
plus PERSONALIZE). 0x4011bc60 is the mk1's 0x400ca574 instruction for
instruction, `Brain::key` reads the same fields (+0x94, +0x98), and each
routine `core_additem` calls matches the mk1's whole.

Build it with the SDK (it needs m68k binutils; with Homebrew's
`m68k-elf-binutils`, set `ELEKLOADER_CROSS=m68k-elf-`):

```bash
python -m elekloader.sdk.build mods/core-dt2 --stock Digitakt_II_OS1.17.syx      # out/core-1.0.elemod
python -m elekloader.lint mods/core-dt2/out/core-1.0.elemod --stock Digitakt_II_OS1.17.syx
```

Checked by cold-booting it in digikit's emulator (`emu.checkpoint`, then
`tools/emucheck.py` to 600M instructions): alone, every stage passes and the
screen at 650M is identical to stock 1.17's. With a mod that inverts an 8x8
block from `ev_draw` (hello-marker, with 1.17's `Bitmap::fillRect` at
0x401131ae), the screen differs from stock in exactly those 64 pixels.
A test mod that counts `ev_key` events and `ev_enc` detents, takes none,
and draws the counts as bars: after three trig presses and two encoder
turns (+3, -4), the screen differs from stock's under the same input only
in a 9-pixel bar (press, repeat and release of each key) and a 7-pixel one,
and the OS acted on every input as stock does. A mod with one
`ev_settings` row: the SETTINGS menu lists it after SYSTEM. Not run on a
unit.
