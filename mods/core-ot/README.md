# core for the Octatrack

The boot copier and the hook bus for the Octatrack (MKI and MKII), OS 1.40C.
Every set of linkable (format 2) mods for the Octatrack needs it. On its own
it takes 10 MB of sample and recorder memory and changes nothing else the
unit does.

- **The reserve.** The OS gives the whole audio page arena
  (0x40a955e0-0x46025de0, 14,602 pages of 6,144 B) to samples and the
  recorders. The core moves the arena's base past its bottom 1,707 pages,
  so 0x40a955e0-0x41495de0 is left for mods: the device's `ddr`, where the
  linker places `.run` and `.bss`. That takes 28 writes (`mod.json`):
  - 23 instructions carry the base;
  - one carries base + 6,144;
  - four literals set the geometry: the page count, the fill limit and the
    clear length each shrink by 1,707 pages.

  These are the same writes sambanks/octabam's platform makes (`arena.py`,
  MIT) for the same reservation. tests/test_octatrack.py derives each one
  from the page count. The core exports the moved base as `arena_base`,
  for mods that compare against it.
- **At boot.** The boot site 0x4000050c called 0x40001e50; it now calls
  `boot`, at the end of the OS image (0x4010fdf0), where the bootstrap
  unpacks it.
  - `boot` makes the call it replaced first, as octabam's loader does.
  - It then copies the RAM image into the reserve and zeroes `.bss`, both
    through the uncached alias (+0x08000000).
  - It sets `core_up` (below) and returns with every register as that call
    left it.
- **The hook bus** (0.2, `bus.s`). Six sites become events that mods
  subscribe to (docs/ADAPTING.md, "The hook bus on the Octatrack"):

  | event | site (was) | when |
  |---|---|---|
  | `ev_tick` | 0x40061e94 (`jsr 0x40031970`) | 60 times a second, in the sys task's loop |
  | `ev_draw` | 0x40013cae (`movea.l 0x400b9710,a5`) | each composed frame, before it goes to the LCD |
  | `ev_key` | 0x40061dc8 (`jsr 0x40031734`, `key(code, pressed)`) | each key press and release |
  | `ev_enc` | 0x40061e00 (`jsr 0x40031944`, `enc(encoder, delta)`) | each encoder turn |
  | `ev_midi` | 0x40005572 (the MIDI thread's handler call) | each MIDI message in |
  | `ev_frame` | 0x4000d94e (`tst.l 0x46104d08`) | the frame interrupt, every 16 samples |

  `ev_tick`, `ev_key`, `ev_enc` and, nearly always, `ev_draw` run in the same
  task, so their handlers never interrupt one another.
- **The draw gate** (`gate.s`). The OS composes the screen twice before the
  boot site, so before `.run` is in the reserve. The draw site therefore
  calls `core_draw_gate`, which `mod.json` places (`fixed`) in the last 24
  bytes of the 338-byte zero run at 0x400c45b0, in the image from power-on.
  The gate goes on to the bus only once `boot` has set `core_up`; until
  then it does just what the site replaced.

## Beside octabam's modules

No site of the bus is a byte that a converted octabam module patches. The
bus hooks the same routines one instruction away from them:
- the MIDI thread's dispatch call, where CC MAP repoints the CC entry of the
  table that call reads (0x400d64a0);
- the frame interrupt before the EMAC state is put back, where TUNER and
  the USB audio mods hook its tail (0x4000d99a, 0x4000d9a0);
- the sys task's tick, where TUNER and CC FEEDBACK hook the UI task's loop
  head and the key-repeat task (0x40056c72, 0x4005595c).

So the 34 mods of irpina/octabam2elemod v1.0 link with 0.2 as they did with
0.1. Their code moves up by the size of core's own (216 bytes, rounded to
their alignment), and the linker relocates it.

## Build

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core-ot --stock OCTATRACK_OS1.40C.syx
python -m elekloader.lint mods/core-ot/out/core-0.2.elemod --stock OCTATRACK_OS1.40C.syx
```

[examples/hello-marker-ot](../../examples/hello-marker-ot) is the smallest
mod that uses the bus.

## Checks

Checked in octabam's emulator (`ot_emu`) with a test mod that has a marker
string in `.run`:
- stock and the core build both reach the RTOS handoff;
- `boot` runs once, called from the boot site;
- after boot, the marker is at 0x40a955e0, where stock has zeros.

0.2, in `ot_emu` on an empty card, 9 s with keys, encoders and MIDI from a
script:
- **Core alone matches stock.** The firmware's key, encoder, CC and
  note-on handlers run as often as on stock, and the last frame the
  compositor sent to the LCD is the same, pixel for pixel.
- **A test mod subscribed to every event** saw:
  - 428 ticks and 440 frames composed;
  - the 4 key events (the last, UP released: code 0x33, 0);
  - both encoder turns (the last, encoder 3, -2);
  - the MIDI messages that reached the firmware's handlers;
  - 18,741 audio frames (2,756 a second).

  No draw ran inside a tick. Its square was in the frame sent to the LCD,
  and nothing else changed.
- **With every handler taking its event**, the firmware's key, encoder, CC
  and note handlers never ran.
- **The v1.0 files.** Every hardware-test group (T0–T7), every variant and
  every one of the 34 mods alone links with 0.2. Each image differs from
  its 0.1 build only at core's new sites, and in pointers that point at the
  same symbol plus offset as before.

On a unit (an Octatrack MKII, 3 Oct 2026): 0.1 alone, and 0.1 with 19 of the
converted octabam mods in seven groups, flashed from the card. Every build
booted with its own version. 0.2 is not yet run on a unit, and nothing is
run on an MKI.
