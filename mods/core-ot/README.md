# core for the Octatrack

The boot copier for the Octatrack (MKI and MKII), OS 1.40C. Every set of
linkable (format 2) mods for the Octatrack needs it. On its own it takes
10 MB of sample and recorder memory and changes nothing else the unit does.

The Octatrack has no hook bus yet. Its mods patch their own sites, and what
each of them needs is RAM plus a way to get its code there. The core provides both:

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
  - It returns with every register as that call left it.

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core-ot --stock OCTATRACK_OS1.40C.syx
python -m elekloader.lint mods/core-ot/out/core-0.1.elemod --stock OCTATRACK_OS1.40C.syx
```

Checked in octabam's emulator (`ot_emu`) with a test mod that has a marker
string in `.run`:
- stock and the core build both reach the RTOS handoff;
- `boot` runs once, called from the boot site;
- after boot, the marker is at 0x40a955e0, where stock has zeros.

Not yet run on a unit.
