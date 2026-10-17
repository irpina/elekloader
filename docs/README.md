# elekloader docs

This folder is elekloader's wiki: everything past the
[front page](../README.md), sorted by who it is for. The pages are plain
Markdown and change through pull requests with the code, so a release's
docs match its code.

## Using elekloader

- **[Install](INSTALL.md)**: the web page, the Windows and macOS apps, or
  Python from source, and the stock OS file each device needs.
- **[Build, flash and recover](BUILDING.md)**: building a custom OS in the
  app or on the command line, sending it to the unit, getting back to stock,
  and what every build is checked for.
- **[Cores](CORES.md)**: the core mod each device needs, which file serves
  which OS, how a build picks one, and what each core adds (the Digitone's
  Mod Menu, say).
- **[The web page](WEB.md)**: elekloader in your browser, its mod shop, and
  how the shop's list is kept.

## Writing mods

- **[Adapting your mod](ADAPTING.md)**: the path to take, the rules, every
  command with the output it should print, every refusal with its fix, and a
  definition of done. Coding agents: start with [AGENTS.md](../AGENTS.md).
- **[Growing the core](CORE-CONTRIBUTING.md)**: when what your mod needs
  belongs in the core, how to build it so it can move there, and how to
  propose it.
- **[The file format](FORMAT.md)**: `.elemod`, whole builds (format 1) and
  linkable mods (format 2).
- **[Adding a device](DEVICES.md)**: a device profile, and what was found
  for each device elekloader supports.
- **octabam's modules (Octatrack):** `elekloader.sdk.octabam` converts
  [sambanks/octabam](https://github.com/sambanks/octabam)'s ColdFire modules
  into linkable mods, each checked against octabam's own account of its
  bytes ([ADAPTING.md](ADAPTING.md), section 4b).
- **The cores' own pages:** [mods/core](../mods/core) (Digitakt mk1),
  [mods/machine-pages](../mods/machine-pages) (its SRC machines' pages, core
  3.0), [mods/core-dn1](../mods/core-dn1) (Digitone mk1) with
  [mods/machines-dn1](../mods/machines-dn1) (its machines, core-dn1 3.1),
  [mods/seq-events-dn1](../mods/seq-events-dn1) (its step fire as events;
  the Digitakt mk1's in [mods/seq-events-dt1](../mods/seq-events-dt1)),
  [mods/core-dt2](../mods/core-dt2) (Digitakt II), and
  [mods/core-ot](../mods/core-ot) with [mods/dspbus-ot](../mods/dspbus-ot)
  (Octatrack).
- **A whole mod on core-dn1 3.2's exclusive audio:**
  [mods/digicosm-dn1](../mods/digicosm-dn1), DigiCosm, a Microcosm-style
  effects engine for the Digitone mk1's audio inputs, with its own page in
  the Mod Menu and the Microcosm's MIDI CCs (`ev_midi_cc`).
- **Another on the same:** [mods/digichroma-dn1](../mods/digichroma-dn1),
  DigiChroma, a Chroma Console-style pedal for the inputs, with its own
  page and the Chroma Console's MIDI CCs.
- **Five more pedals** on a shared pedal shell, each with its pedal's MIDI
  CCs: [DigiMood](../mods/digimood-dn1) (after the MOOD MkII: a wet channel
  and a micro-looper), [DigiHedra](../mods/digihedra-dn1) (the Hedra: three
  pitch voices in a key, with delays), [DigiTensor](../mods/digitensor-dn1)
  (the Tensor: tape speed, reverse, hold and stutter in time),
  [DigiHabit](../mods/digihabit-dn1) (the Habit: echoes from a 3-minute
  memory) and [DigiSky](../mods/digisky-dn1) (the BigSky: twelve reverbs).
- **Examples to start from** ([examples/](../examples)):
  - `hello-marker`, one C function on the draw event that puts a small square
    in the corner of every screen; `hello-marker-dt2` and `hello-marker-ot`
    do the same on the Digitakt II and the Octatrack;
  - `perform-direct`, a real Digitakt II mod: [PRESET] toggles PERFORM
    without [FUNC];
  - `sine-machine`, an SRC machine for core 3.0 that names no firmware
    address, so its OS 1.54 port is empty;
  - `dn-sine-machine`, the same for the Digitone mk1: a machine for the
    machines mod and core-dn1 3.1, with an empty OS 1.44 port;
  - `dn-thru`, the smallest Digitone mk1 mod that takes the whole output
    (core-dn1 3.2): the audio inputs straight through, the synths silent;
  - `dn-tremolo`, the smallest one that takes it as an insert (core-dn1
    4.0): a tremolo on everything the Digitone plays;
  - `dn-progchange`, the smallest one that takes program changes
    (core-dn1 4.0): each shown for two seconds, channel 16's taken;
  - `dn-euclid`, the smallest Digitone mk1 mod on seq-events: track 1 fires 5
    steps of every 16, with an empty OS 1.44 port; `euclid` the same on the
    Digitakt mk1, with an empty OS 1.54 port;
  - `dsp-tone-ot`, the smallest mod with code on the Octatrack's DSP: a quiet
    sawtooth in place of input A, through the DSP bus.

## Building firmware on your own site

- **[The kit](INTEGRATING.md)**: the builder worker, a client for your
  pages, and elekloader's curated catalog of cores and mods, each pinned by
  sha256.
- **[The engine in TypeScript](../js/README.md)**: the OS files, the mod
  checks, the linker and the build, with no dependencies and no Python. For
  the same stock file and mods it writes the same files as the Python, byte
  for byte. It is GPL-3.0-or-later.

## Maintaining elekloader

- **[Releasing](RELEASING.md)**: the version, the core files a release
  carries, the workflows that build the apps, the kit and the site, and
  pre-releases.
- **[The apps](APPS.md)**: building the Windows and macOS apps, by hand or
  in the workflows, and the signing secrets.
- **[Tests](TESTS.md)**: each suite and the files it needs.
