# DSP bus for the Octatrack

The DSP hook bus for the Octatrack (MKI and MKII), OS 1.40C. Mods can run
code on the DSP with it. It needs the Octatrack's core (`mods/core-ot`, 0.1
or 0.2), and every Octatrack mod with DSP code needs it.

The main OS uploads its DSP code to the DSP56721's two cores at boot:
- payload A to core 0, which runs tracks 5-8, the inputs, the mix and the
  master;
- payload B to core 1, which runs tracks 1-4.

Payload A's P memory is full, so mods' DSP code can only take the words of
a stock effect. This mod gives up SPATIALIZER's, as sambanks/octabam's USB
IO remixes do (MIT).

## What it does

- **It frees SPATIALIZER's words.** That is payload A's P:0xaa8-0xbac, 261
  words. It claims `dsp:harvest:SPATIALIZER`, so the linker places mods' DSP
  code and DSP tables there (docs/FORMAT.md, "DSP code"), and no other mod
  may change those bytes.
- **It takes SPATIALIZER off both FX menus**, so nothing selects the code
  that is gone:
  - FX1's and FX2's chooser lists are rebuilt without it, at 0x400d6b20 and
    0x400d7bbc (free runs of the image). The six `lea` instructions that
    load them are pointed there.
  - In both id-to-row tables, the rows below SPATIALIZER's move up one.
  - Its two dispatch words on payload A, X:0x21a (init) and X:0x23a
    (process), point at the null stubs (P:0x7c8, P:0x7c9). Stock points
    every unused effect id at those stubs.
- **The bus.** Payload A's P:0x88, `move r2,x:>$204` at the head of every
  audio frame, becomes `jsr >ev_dsp_rx`. That is a table the linker builds:
  - the displaced instruction;
  - `jsr >handler` for each subscriber, in `order`;
  - `rts`.

  With no subscribers, the frame runs as stock.

All of these bytes are the ones octabam's build writes for its USB IO
remixes (irpina/octabam2elemod's `usb-io-*` mods carry them). Those builds
ran on a unit: USB IO TRACKS MAIN CUE AB on an MKII, 3 Oct 2026.
tests/test_octatrack.py derives the harvest from the stock image.

What changes for a user:
- SPATIALIZER is off both menus.
- A project that already has SPATIALIZER on track 5-8 runs the null stub
  there instead. The SPATIALIZER code for tracks 1-4 is on core 1, and stays.

## The event

| event | when | handler | notes |
|---|---|---|---|
| `ev_dsp_rx` | DSP core 0, the head of every audio frame (16 samples, 2,756 a second), before anything reads the current RX block | DSP code, called with `jsr`; it ends with `rts` | the RX block is at `x:>$202`: 16 samples x 4 slots, slot 2 input A, 3 input B, 0 and 1 C and D. Every stock reader of the block runs after it, including the core 0 to core 1 handoff and the recorder's read-back |

- A handler may change `a`, `x1`, `r0`, `r1` and the condition codes. It
  must keep every other register: `r2`, `r4`-`r7` and `b` are live there.
- Subscribe with `subscribe_dsp` in mod.json (docs/ADAPTING.md, "DSP code").
- Keep handlers short: they run inside the audio frame on core 0.

## Conflicts

The USB IO mods made from octabam's remixes (`octabam-usb-io-*`, v1.0)
harvest SPATIALIZER themselves, with these same bytes. The linker therefore
refuses to combine them with this mod.

The examples, `examples/dsp-tone-ot` and USB AUDIO IN's inject, ran in
octabam's emulator (`ot_emu --dsp`): the tone on input A, and
`verify_usb_in` with the inject as an `ev_dsp_rx` handler. Not yet on a
unit.
