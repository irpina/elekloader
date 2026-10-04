# core (Digitakt II)

The boot copier and the hook bus for Digitakt II OS 1.17. Every set of
linkable (format 2) mods for the Digitakt II needs it. On its own it changes
nothing the unit does.

It builds the shared [../core/core.s](../core/core.s) with the Digitakt II's
addresses (`mod.json`). The SETTINGS and audio-render hooks
(`settings.s`, `render.s`) are not in it: the Digitakt II renders its audio
on the DSP, and its SETTINGS site has not been found yet.

- **At boot** (the OS entry's call at 0x40000538, which called 0x400019b0,
  as on the mk1), `boot` copies the RAM image the linker built to the
  device's DDR area (0x47F00000), zeroes `.bss`, and goes on to the call it
  replaced. Unlike the mk1's core it does not start the DTIM0 counter
  (`NO_DTIM0`): the OS reads it at ten sites (0xfc07000c) and nothing on the
  unit starts it, so stock reads it as stopped, and this core keeps that.
  A mod that wants a time base cannot use DTIM0 here.
- **The shared sites** become the events `ev_tick`, `ev_draw`, `ev_key`
  and `ev_enc`, with the same prototypes as on the mk1
  ([docs/ADAPTING.md](../../docs/ADAPTING.md), "The hook bus"):

  | site | was | event |
  |---|---|---|
  | 0x40032ad4 | `jsr 0x4011bc60`: returns the view controller's byte +0x20 | `ev_tick` |
  | 0x40032b3a | `jsr 0x4011bc96`: `drawAll(ctrl, bmp)`, the 128x64 frame | `ev_draw` |
  | 0x40033d94 | `jsr 0x40030bd0`: `Brain::key(brain, event)` | `ev_key` |
  | 0x40033dde | `jsr 0x40030b64`: `Brain::enc(brain, event)` | `ev_enc` |

  Each was found by the mk1's code around its site, with the addresses
  masked: the UI loop's dirty check and frame composition, and the key and
  encoder events built from the UI queue's message. 0x4011bc60 is the mk1's
  0x400ca574 instruction for instruction, and `Brain::key` reads the same
  fields (+0x94, +0x98).

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
`ev_key` and `ev_enc` are wired to the dispatchers above but no mod has
used them yet. Not run on a unit.
