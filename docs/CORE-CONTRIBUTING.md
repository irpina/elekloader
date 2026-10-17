[elekloader docs](README.md) › Growing the core

# Growing the core

Every event, table and firmware export a core has came from a mod that
needed it: `ev_midi_cc` from DigiCosm's MIDI, machine pages from the SRC
machines, step-fire events from mods that change what the sequencer
plays. This page is for mod authors, and for the coding agents
they work with, whose mod needs something the core does not offer yet. It
says how to tell whether that need belongs in the core, how to build it so
that it can move there, and how to propose it.

A mod that hooks a site itself owns those bytes, and no other mod can hook
them (rule 5 in [ADAPTING.md](ADAPTING.md#2-the-rules)). The same site as a
core event serves every mod, and the mod's next OS port is the core's work
rather than its own.

## 1. Look first

Before you hook a stock site, look for what the core already has for
your device:

- the events and tables: `collections` in the core's `mod.json`
  ([mods/core](../mods/core/mod.json), [mods/core-dn1](../mods/core-dn1/mod.json),
  [mods/core-dt2](../mods/core-dt2/mod.json), [mods/core-ot](../mods/core-ot/mod.json));
- each event's handler, its arguments and what its return means: the
  comment over the code that calls it, in the core's `.s` files;
- the firmware exports and the C names for all of it: the SDK's headers,
  `elekloader/sdk/include/<device>/core3.h` (and `core3.inc` for assembly);
- the companions, which own a group of sites once: machine-pages,
  machines-dn1 and seq-events ([CORES.md](CORES.md#what-each-core-adds));
- the sections of [ADAPTING.md](ADAPTING.md) whose heading names a core
  version.

If one of them fits, subscribe to it, or import it. You are done here.

## 2. Is it a core thing?

When nothing fits, ask of each site, address or table your mod needs:
**would a different mod plausibly want the same thing?**

| your mod needs | it belongs | as |
|---|---|---|
| to see or change what the UI, the keys, the knobs, the LEDs, the menus or the screens do | in the core | an event |
| to see or change the audio, the voices, the sound parameters or the MIDI the unit gets | in the core | an event |
| to see or change what the sequencer fires, or the project the unit loads and saves | in the core, or a companion beside it | an event or a table |
| a firmware routine or variable, by its address | in the core | a firmware export (`fw_*`): mods that name it need no OS port |
| a list that other mods add entries to (machines, menu entries, pages) | in the core, or a companion | a table |
| a group of sites that only one kind of mod uses (the SRC page's machines, say) | a companion beside the core | its own events and tables |
| your feature itself: its sound, its pages, its state | in your mod | |
| a constant only your feature changes | in your mod | a `bytes` site |

An event's handler returns nonzero to take what it saw (a key, a CC), so a
mod that replaces stock behaviour works as an event too.

When the answer is "in the core", go on to section 3. When it is unclear,
treat it as a core thing: it costs a few lines more now, and nothing
later.

## 3. Build it in core's shape

Build your mod in two parts, so that one of them can later move into the
core as it is:

- **the core part**: the site, the call to each handler, and the table
  (or the firmware address), in a source file of its own
  (`core_candidate.s` or `.c`) with the site and the table in your
  `mod.json`;
- **your mod**: everything else. It subscribes to the core part's event as
  it will to the core's, and imports what it will import from the core.

The core part follows the core's conventions:

| | |
|---|---|
| names | the event's table `ev_<what>` (`ev_midi_pc`); the code the site calls `core_<what>` (`core_midi_pc`); a firmware export `fw_<what>`; flags and constants `CORE_<WHAT>_...`. While it lives in your mod, prefix none of these with your id: they are the names it will have in the core |
| the handler | written down over the code, as in [mods/core-dn1/midi.s](../mods/core-dn1/midi.s): its C signature, the context it runs in (a task, or interrupt level for the render), what each argument and flag means, and what a nonzero return does |
| no subscriber | the unit behaves exactly as stock: with the table empty, the code does what the bytes it replaced did |
| every OS | the site's address and stock bytes for every OS the core supports: `os`, and each of `ports` (Digitakt mk1 1.53 and 1.54, Digitone mk1 1.43 and 1.44). When you could find only one, say so in your proposal |
| the cost | a hot site (the render, the voices) walks its table on every block: keep the empty path a few instructions, and say what you measured |
| registers | the core part saves what it uses and gives the stock code back the registers it expects, as the existing calls do |

Ship your mod like this, with the core part in it, while the proposal is
open. A second mod that wants the same site then meets your mod's site
(*"... overlap"*): that is the signal to propose it, if you have not.

## 4. Propose it

Open a pull request on elekloader that moves the core part into the core:

1. Put its code in a new file in the core's folder (`mods/core-dn1/`,
   say), last in `sources`, so the code before it does not move.
2. Move its site into the core's `sites`, its address for each other OS
   into `ports`, its table into `collections` and its exports into the
   SDK header (`core3.h` and `core3.inc`).
3. Raise the core's minor version (4.0 to 4.1). The maintainers decide
   when a core is released, and whether a change needs a new major line
   (one that moves the mods' RAM, say).
4. Keep everything the core had: the same sites with the same bytes, the
   same tables and exports, every symbol where it was. `tests/test_sdk.py`
   checks it against the released cores (`check_superset`,
   `check_dn_superset`): add your site, table and exports to what those
   checks expect a new core to add.
5. Add a section to [ADAPTING.md](ADAPTING.md) headed with the core
   version ("Program changes (core-dn1 4.0, Digitone mk1)" is one), a line
   to "What each core adds" in [CORES.md](CORES.md), and the smallest mod
   that uses it in `examples/` (`examples/dn-progchange` is the one for
   `ev_midi_pc`).
6. Say in the pull request what it ran on: built for every OS, linked
   with the mods that share its area, the stock behaviour unchanged with no
   subscriber, and the emulator or the unit you ran it on.

Then your mod drops its core part, sets `resources.core` to the new
version, and needs no other change: it subscribes to the same table by the
same name. Release that version when the core is released: the old one and
the new core both declare the table, and a build refuses the pair
(*"... both declare the table ev_..."*).

## Which sites mods share

`elekloader.sdk.coresites` reads a set of mods (the shop's, say) and lists
the stock code more than one of them hooks for itself: sites that overlap,
which those mods cannot be built together over, and, given that OS's stock
file, sites in one stock routine. Each group it lists is a place where one
core event could serve those mods. Of each mod only the newest version
counts, and the core's own sites do not.

```bash
python -m elekloader.sdk.coresites <folder of .elemod files> --stock Digitakt_OS1.53.syx [--json]
```

Without `--stock` it groups sites at most `--window` bytes apart (64)
instead of by routine.

## Checklist

- [ ] Nothing in the core already does it (section 1).
- [ ] The core part is in a file of its own, under the core's names, with
      its handler written down.
- [ ] With no subscriber, the unit behaves as stock.
- [ ] Every OS the core supports has the site's address, or the proposal
      says which is missing.
- [ ] The core keeps everything it had, and the superset tests say what
      the new version adds.
- [ ] ADAPTING.md, CORES.md and an example are in the pull request.
