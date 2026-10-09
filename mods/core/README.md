# core

The boot copier and the hook bus for Digitakt mk1 OS 1.53 and 1.54. Every
set of linkable (format 2) mods needs exactly one core. On its own it
changes nothing the unit does.

`core.s`, `settings.s`, `render.s`, `machines.s` and `fw.s` have no addresses:
`mod.json` gives them (`defsym`), with the sites, for 1.53, and again for
1.54 under `ports`. The stock file you build with picks them.
[../core-dn1](../core-dn1) builds the same `core.s`, `settings.s` and
`render.s` for the Digitone mk1, and [../core-dt2](../core-dt2) `core.s`,
`settings.s` and `fast.s` (with its own `personalize.s`) for the
Digitakt II. The addresses in this README and in the sources' comments
are 1.53's.

- **At boot** (the OS entry's call at 0x40000538), `boot` copies the RAM
  image the linker built to 0x47BE0000, zeroes `.bss`, starts the DTIM0
  counter if nothing has, and goes on to the call it replaced.
- **The shared sites** become events that mods subscribe to, in `order`:
  `ev_tick`, `ev_draw`, `ev_key`, `ev_enc`, `ev_settings`, `ev_render_in`
  and `ev_render_out`. `core_additem(menu, row)` adds a SETTINGS row. The
  table of events, their C prototypes and the sites core owns is in
  [docs/ADAPTING.md](../../docs/ADAPTING.md), "The hook bus".
- **SRC machine slots** (2.1, `machines.s`, Digitakt mk1 only): mods add
  SRC machines past the stock four through the table `core_machines`, and
  core makes the firmware list, name, set, load and render them, and treat
  them as the stock machine they stand for where the firmware tests for
  one. Several mods can add machines at once (NEIGHBOR is 4, DIGISLICER
  5). [docs/ADAPTING.md](../../docs/ADAPTING.md), "SRC machines".
- **3.0: core 2.1 and more** (Digitakt mk1). The same 39 sites with the
  same bytes, the same events and tables, every 2.1 symbol in its place
  (2.1's code is the start of 3.0's), and no new site. It adds:
  - the firmware locations machine mods use, as named exports (`fw.s`:
    `fw_track_blocks`, `fw_kit`, ...), so a mod that names them builds for
    another OS unchanged;
  - `core_machine_ui(id)`: the page a machine describes in its
    descriptor's tail, which [../machine-pages](../machine-pages) draws.

  A builder takes 3.0 only for a selection with a mod whose
  `resources.core` asks for it, and 2.1 for every other, so adding 3.0 to
  a catalog or the app changes no build that does not need it.
  [docs/ADAPTING.md](../../docs/ADAPTING.md), "Core 3.0".

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.53.syx      # out/core-3.0.elemod
python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.54.syx      # out/core-3.0-os1.54.elemod
python -m elekloader.lint mods/core/out/core-3.0-os1.54.elemod --stock Digitakt_OS1.54.syx
```

Core 3.0's files are on the
[core-v3.0](https://github.com/irpina/elekloader/releases/tag/core-v3.0)
pre-release and in the mod shop; 2.1's are in the latest release (v0.4.0).

The 1.54 port is the same core: the same code, sites and sections, built
with 1.54's addresses. Of its 39 sites, 38 are where 1.53 has them, and
0x400a1706 is 0x400a1862. Of the routines and data it names, DRAWALL,
OP_NEW, ITEM_CTOR, MENU_ADD, FN_MGR, ITEM_ID and BLIT moved by 0x228, and the
machine menu's default names by 0x380. Each was found again by its own code
with the addresses in it masked, and checked against the code that calls
it.

Checked by cold-booting it in digikit's emulator: alone, every screen and
the audio are identical to stock; with other mods, as those mods' own
checks describe. 2.1 alone: the check's nine screens are identical to
stock's, and the audio too, apart from the recording's silent end being
1 ms longer (2.0a does the same). The machine slots were checked with
digislicer 2.0 and digineighbor 0.6, as their READMEs describe.

2.1 on 1.54, alone, the same check against stock 1.54: every stage passes,
the nine screens are identical, and the audio too, apart from the silent
end being 1 ms off, as on 1.53. With [hello-marker](../../examples/hello-marker)
added, every screen differs from stock only at its corner square. The
machine slots have not been checked on 1.54 with a mod that adds a machine:
digislicer and digineighbor are not built for 1.54 yet.

3.0, on 1.53 and on 1.54: `tests/test_sdk.py` checks it against the
released 2.1 (the same sites, tables and symbols, 2.1's code at the start
of 3.0's), and `tests/test_catalog_link.py` links every Digitakt mod of the
shop alone and in pairs against both: 144 selections, each linking or
refused as it is with 2.1, with the same messages. In digikit's emulator,
3.0 alone against stock: the nine screens identical, the audio too apart
from the silent end; NEIGHBOR 0.6 on 3.0 against 0.6 on 2.1, through its
menu, page and LFO page: every screen and the audio identical. On a unit
(OS 1.54), with machine-pages and every machine mod built for it, as
[../machine-pages](../machine-pages) describes: everything worked.
