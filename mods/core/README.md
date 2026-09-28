# core

The boot copier and the hook bus for Digitakt mk1 OS 1.53. Every set of
linkable (format 2) mods needs exactly one core. On its own it changes
nothing the unit does.

`core.s` has no addresses: `mod.json` gives them (`defsym`), with the
sites. [../core-dn1](../core-dn1) builds the same `core.s` for the Digitone
mk1.

- **At boot** (the OS entry's call at 0x40000538), `boot` copies the RAM
  image the linker built to 0x47BE0000, zeroes `.bss`, starts the DTIM0
  counter if nothing has, and goes on to the call it replaced.
- **The shared sites** become events that mods subscribe to, in `order`:
  `ev_tick`, `ev_draw`, `ev_key`, `ev_enc`, `ev_settings`, `ev_render_in`
  and `ev_render_out`. `core_additem(menu, row)` adds a SETTINGS row. The
  table of events, their C prototypes and the sites core owns is in
  [docs/ADAPTING.md](../../docs/ADAPTING.md), "The Digitakt mk1 hook bus".

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.53.syx
python -m elekloader.lint mods/core/out/core-2.0a.elemod --stock Digitakt_OS1.53.syx
```

Checked by cold-booting it in digikit's emulator: alone, every screen and
the audio are identical to stock; with other mods, as those mods' own
checks describe.
