[elekloader docs](README.md) › Cores

# Cores

Users install mods from their `.elemod` files.
[FORMAT.md](FORMAT.md) describes both kinds:

- **format 1**: a whole custom build as one file;
- **format 2**: separate, linkable mods. A `core` mod provides a hook
  bus; other mods subscribe to its events and add entries to each other's
  tables. The loader's linker places them, resolves their symbols and
  checks them.

Every set of format-2 mods needs the **core** mod for its device, and
exactly one. The Windows and macOS apps have them built in, the web page
lists them, and each release carries them. Files from before version 0.2
used the `.dtmod` extension; they still load.

## Which file

There is one core file per device and OS:

| device | OS | core | where |
|---|---|---|---|
| Digitakt mk1 | 1.53 | `core-2.1.elemod` | the latest release (v0.4.0) |
| Digitakt mk1 | 1.54 | `core-2.1-os1.54.elemod` | the latest release (v0.4.0) |
| Digitakt mk1 | 1.53 | `core-3.0.elemod` | the [core-v3.0](https://github.com/irpina/elekloader/releases/tag/core-v3.0) pre-release, for mods that need the 3.x line |
| Digitakt mk1 | 1.54 | `core-3.0-os1.54.elemod` | the same pre-release |
| Digitone mk1, Digitone Keys | 1.43 | `core-dn1-2.3.elemod` | the [core-dn1-v2.3](https://github.com/irpina/elekloader/releases/tag/core-dn1-v2.3) pre-release (v0.4.0 has 2.0a) |
| Digitone mk1, Digitone Keys | 1.44 | `core-dn1-2.3-os1.44.elemod` | the same pre-release (v0.4.0 has 2.0a) |
| Digitone mk1, Digitone Keys | 1.43 | `core-dn1-3.2.elemod` | the [core-dn1-v3.2](https://github.com/irpina/elekloader/releases/tag/core-dn1-v3.2) pre-release, for mods that need the 3.x line |
| Digitone mk1, Digitone Keys | 1.44 | `core-dn1-3.2-os1.44.elemod` | the same pre-release |
| Digitakt II | 1.17 | `core-dt2-1.0.elemod` | not released yet: build it ([below](#building-a-core)) |
| Octatrack MKI, MKII | 1.40C | `core-ot-0.1.elemod` | the latest release (v0.4.0) |
| Octatrack MKI, MKII | 1.40C | `core-ot-0.3.elemod` | on main, not released yet (0.2, with the hook bus, is too) |

From 3.0 the Digitakt mk1's core and the Digitone mk1's each have two
lines, 2.x and 3.x, and a build takes the 3.x line only for a mod that
needs it. The Digitakt's 3.0 is on the core-v3.0 pre-release and the
Digitone's 3.2 on the core-dn1-v3.2 pre-release, and both are in the shop.

## How a build picks one

A mod says which core it needs at least (`resources.core` in the file,
`needs_core` in the shop's list). A build takes the newest core of the
oldest major line that is new enough ([ADAPTING.md](ADAPTING.md), "Core
3.0"). So a Digitakt mk1 selection stays on 2.1 unless a mod needs 3.0, and
a Digitone selection takes 2.3, the newest of the 2.x line, unless a mod
needs core-dn1 3.0, 3.1 or 3.2, and then it takes 3.2. The web page,
the kit and the window (from source, and the apps after 0.4.0) tick that
core for you and keep one. The 0.4.0 apps refuse a build with two cores
ticked: there, untick the built-in one when you add a newer core.

## What each core adds

- **Digitakt mk1** ([mods/core](../mods/core)): the hook bus, the shared
  events (tick, draw, key, encoder, SETTINGS, the render), and the
  machines list, where mods add SRC machines. From 3.0, with
  [machine-pages](../mods/machine-pages), a machine describes its own SRC
  page, so machine mods combine ([ADAPTING.md](ADAPTING.md), "Machine
  pages").
- **Digitone mk1** ([mods/core-dn1](../mods/core-dn1)): the same hook bus,
  plus a voice note-on event, parameter slots, mod pages and project data
  (2.1), and the Mod Menu (2.2, a grid of icons from 2.3):
  [below](#the-digitones-mod-menu). From 3.0 it also exports the firmware
  locations Digitone mods use, so a mod that names only those builds for
  1.43 and 1.44 unchanged ([ADAPTING.md](ADAPTING.md), "Firmware locations
  (core-dn1 3.0)"). From 3.1 it has what machines need: the voices' sound
  before the filter, stock parameters a mod relabels for its tracks, sound
  edits the voices hear and submenus in the Mod Menu. With
  [machines](../mods/machines-dn1), a sound plays a machine mod's voice in
  place of FM ([ADAPTING.md](ADAPTING.md), "Machines on the Digitone").
  From 3.2 a mod may take the whole output, with the synths silent, and
  keep large buffers in the profile's `bulk` area ([ADAPTING.md](ADAPTING.md),
  "Exclusive audio"), and take MIDI CCs before the stock applies them
  (`ev_midi_cc`).
- **Digitakt II** ([mods/core-dt2](../mods/core-dt2)): the hook bus's tick,
  draw, key and encoder events, and rows in SETTINGS > PERSONALIZE.
- **Octatrack** ([mods/core-ot](../mods/core-ot)): a source of its own. It
  reserves RAM for mods, copies their code there, and from 0.2 has a hook
  bus with the Octatrack's events; from 0.3 it reserves only the RAM the mods
  use, at most 10 MB. Beside it,
  [mods/dspbus-ot](../mods/dspbus-ot) is an optional bus for mods' DSP code.

### The Digitone's Mod Menu

Hold a track key (T1, say) on its own for about half a second, and core
lists what your mods add to it, as a grid of icons from core-dn1 2.3. Move
with the arrows or a knob and pick with YES, or pick with the entry's trig
key; NO closes it. With no mod that adds an entry, holding a track key does
nothing, as on the stock OS. Here digitables 1.3 and a test mod with seven
entries are linked, in digikit's emulator; [mods/core-dn1](../mods/core-dn1)
has more screens and how a mod adds an entry.

![The Digitone's Mod Menu: four tiles, each an icon over a label with its trig key's number, TABLES selected, and a scroll bar](img/dn-modmenu-grid.png)

## Building a core

One source, [mods/core/core.s](../mods/core/core.s), is built with each
device's addresses ([mods/core](../mods/core) for the Digitakt mk1,
[mods/core-dn1](../mods/core-dn1) for the Digitone mk1,
[mods/core-dt2](../mods/core-dt2) for the Digitakt II). Each `mod.json`
gives the addresses of every OS it supports (its `os`, and its `ports`):
the stock file you build with picks them. The Octatrack's has its own
source. Build any of them with the SDK, which needs the device's cross
toolchain ([ADAPTING.md](ADAPTING.md), "What you need"):

```bash
python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.54.syx                          # the Digitakt mk1's (or 1.53)
python -m elekloader.sdk.build mods/core-dn1 --stock Digitone_and_Digitone_Keys_OS1.44.syx   # the Digitone mk1's (or 1.43)
python -m elekloader.sdk.build mods/core-dt2 --stock Digitakt_II_OS1.17.syx                      # the Digitakt II's
python -m elekloader.sdk.build mods/core-ot --stock OCTATRACK_OS1.40C.syx                    # the Octatrack's
python -m elekloader.sdk.build mods/dspbus-ot --stock OCTATRACK_OS1.40C.syx                  # its DSP bus (optional)
```

The SDK writes `out/core-<version>.elemod`; a release renames each as the
table above does ([RELEASING.md](RELEASING.md)).
