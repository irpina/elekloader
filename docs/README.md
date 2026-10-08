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
  [mods/core-dt2](../mods/core-dt2) (Digitakt II), and
  [mods/core-ot](../mods/core-ot) with [mods/dspbus-ot](../mods/dspbus-ot)
  (Octatrack).
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
