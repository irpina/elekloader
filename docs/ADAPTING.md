# How to adapt your mod to elekloader

This guide is for people and for coding agents. Every step has a command
and the output that means it worked; the last sections map every refusal to
its fix and give a definition of done. The format itself is
[FORMAT.md](FORMAT.md); the Digitakt mk1 addresses below are OS 1.53's, the
Digitone mk1's 1.43's. Building for another OS version (1.54, 1.44) is 3.10.

## 0. Pick a path

| you have | do | result |
|---|---|---|
| code that should run next to other mods | **Path B**: a linkable mod (format 2), built with the SDK | combines with any other mod that does not conflict |
| a byte or two to change (a constant, a limit) | **Path B** with `bytes` sites and no sources | the same; no compiler needed |
| a custom firmware you already build as one piece (one `.syx`) | **Path A**: a whole-build mod (format 1), made with `mkmod` | quick, but it cannot be combined with anything |
| an octabam module (Octatrack) | `elekloader.sdk.octabam` converts it to Path B (section 4b) | a linkable mod, checked against octabam's own account of its bytes |

Path B is the one to aim for. Path A is a stopgap for an existing
monolithic build; section 4 says how to go from A to B.

## 1. What you need

- Python 3.9 or newer, and this repository (no dependencies).
- The stock OS file for the device and release you target, exactly as the
  manufacturer publishes it. elekloader knows it by hash: the README lists
  the supported releases, and `devices/` holds their profiles.
- For code (Path B with sources): the device's cross toolchain, from its
  profile's `toolchain`. For the Digitakt mk1 that is m68k binutils and
  gcc: on Debian or Ubuntu, `apt install binutils-m68k-linux-gnu
  gcc-m68k-linux-gnu`; on Windows, inside WSL. Set `ELEKLOADER_CROSS` if
  your tools have another prefix.
- For linkable mods: the **core** mod for your device (`core-*.elemod`).
  It owns the shared hook sites, copies every mod's code into RAM at boot,
  and turns the shared sites into events your mod subscribes to. Every
  format-2 mod set needs exactly one core. `mods/core/core.s` is its one
  source; `mods/core` builds it for the Digitakt mk1
  (`python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.53.syx`)
  and `mods/core-dn1` for the Digitone mk1. The Octatrack's core,
  `mods/core-ot`, is only the boot copier: its mods patch their own sites,
  since it has no events yet.

## 2. The rules

The loader checks all of these before it builds anything; each rule says
what you see when it is broken (section 5 has the fixes).

1. **Only the main OS changes.** A mod has no way to touch the bootloader
   or any other section, so the stock OS file always recovers the device.
2. **Ship no firmware bytes.** Call firmware routines by address; do not
   copy stock code into your sources. When your bytes do repeat stock bytes
   (the instruction a hook displaced, say), runs of 8 bytes or more are
   stored as references and filled in from the user's own file.
3. **Patch whole instructions.** A code site covers whole stock
   instructions, and so do its new bytes: typically a 6-byte `jsr`/`jmp`
   over one or more instructions, and the routine it calls does their work
   itself. *"ends mid-instruction"*, *"sweeps land on the start"*.
4. **Do not patch the shared sites: subscribe.** On the Digitakt mk1 the
   core mod owns the sites in the table below. Subscribe to their events
   instead of hooking them. *"... overlap"*.
5. **One owner per byte.** No two mods may patch overlapping bytes, or bytes
   another mod's table entries claim. *"... overlap"*.
6. **Let the linker place you.** Your code and data go in sections; never
   hard-code the address of your own code or data. Budgets are shared by
   every mod: on the Digitakt mk1, 128 KB of RAM (`.run` + `.bss`) and
   2304 bytes of fast SRAM (`.fast`). *"the mods need RAM to ..."*.
7. **Only relocatable references.** The linker relocates 32-bit absolute and
   32/16-bit PC-relative references. Use the device's compiler flags (the
   SDK does) and 32-bit addressing for your own symbols. Firmware addresses
   are plain numbers and need no relocation. *"relocation type N"*.
8. **One namespace.** Every global symbol is visible to every mod: prefix
   yours with your mod's id (`hello_draw`), and make internals `static`.
   *"both export ..."*.
9. **Claim what you use.** List named resources in `resources.names`: SysEx
   device ids (`sysex:0x7d`), SETTINGS rows (`settings:MY ROW`), +Drive
   paths (`drive:/cfw/mine.bin`), key combinations (`ui:SRC page:hold YES`).
   Memory you use outside the linker's areas goes in `resources.regions`.
   *"both claim ..."*.
10. **Inside another mod's copied block, be absolute.** FAST AUDIO copies the
    render block 0x400716c0-0x4007629a to SRAM at run time. A site of yours
    in that block runs from the copy too, so it may not be PC-relative and
    may not touch the bytes the copy's fix-ups rewrite. *"PC-relative,
    inside ... copied block"*.
11. **Say what you need.** `requires` names the mods yours depends on (always
    `core` for format 2); `conflicts` names the ones it cannot live with.
    *"X requires Y"*.
12. **One file, one release.** A mod targets one stock release by hash.
    Porting to another OS version means finding every address again.

### The hook bus (core's events): the Digitakt mk1 and the Digitone mk1

Handlers are C functions (arguments on the stack; d0-d1/a0-a1 free,
everything else kept; the result in d0). `order` sorts handlers of one
event (lower first; the shipped mods use 10-90).

| event | when | C prototype | notes |
|---|---|---|---|
| `ev_tick` | 30 times a second, UI task | `void f(void *ctrl)` | set `*((unsigned char *)ctrl + 0x20) = 1` to redraw |
| `ev_draw` | after each frame is drawn | `void f(void *bmp, void *ctrl)` | draw over the frame; y = 0 is the bottom row |
| `ev_key` | each key event | `int f(void *brain, void *ev)` | return nonzero to take it: nothing later sees it. `ev+12` key id, `ev+16` flags (1 pressed, 8 repeat, 2 FUNC held) |
| `ev_enc` | each encoder turn | `int f(void *brain, void *ev)` | `ev+12` encoder 1-8 (A-H), `ev+16` delta |
| `ev_settings` | the SETTINGS menu is built | `void f(void *menu)` | add a row with `core_additem(menu, row)`; `row` is four callbacks (label, select, draw, change) in the firmware's MenuItem conventions, which this guide does not document yet |
| `ev_render_in` | audio render entry, 1500 times a second | `void f(void)` | interrupt level: keep it short |
| `ev_render_out` | audio render exit | `void f(void)` | the same |

The events, their prototypes and their conventions are the same on both
devices; only the sites differ. The sites core owns (do not patch them):
- Digitakt mk1 1.53 and 1.54: 0x40000538, 0x4000a770, 0x4000a7d6,
  0x4000b770, 0x4000b7ba, 0x40058800, 0x40077428, 0x400784c8;
- Digitone mk1 1.43: 0x40000538, 0x4001900c, 0x40019072, 0x40019d9c,
  0x40019de4, 0x40072a34, 0x4009d108, 0x4009e51c;
- Digitone mk1 1.44: the same, but 0x40072a54, 0x4009d128 and 0x4009e53c
  for the last three.

A firmware routine your mod calls has its own address on each device and
each OS version: look it up for the release you target, and build one
`.elemod` per device and OS (a mod's `device` and `os`, or one of its
`ports`, pick the stock file: 3.10).

### SRC machines (core 2.1, Digitakt mk1)

The Digitakt mk1 has four SRC machines: 0 ONESHOT, 1 WERP, 2 REPITCH and
3 SLICE, kept in a sound's byte +0x7E. From core 2.1 a mod can add one: it
contributes to the table `core_machines` a pointer to a descriptor of six
longs:

| offset | field | |
|---|---|---|
| +0 | id | its number, 4-127. Kits store it, so it is fixed for good: claim it as the resource `machine:<id>` (NEIGHBOR is 4, DIGISLICER 5) |
| +4 | name | its name in the machine menu and the SRC page's title (10 characters fit) |
| +8 | short | its 4-character name (the SRC page's `NAME: sample` title) |
| +12 | icon | an 11 x 7 Bitmap for the menu, in the stock icons' format, or 0 |
| +16 | params | the stock machine (0-3) whose 8 parameters it takes: their defaults on a switch, MIDI CC 16-23 and NRPN 0x80-0x87, the Randomize and Reload pages, the SAMP lookup of the sample browser |
| +20 | render | the machine it plays as: a stock one (0-3) in the audio render and in that machine's features elsewhere (SLICE's slice locks, its keyboard slice pages, its SRC page state); or its own id, for an empty voice window a mod fills |

```json
"contribute": [{"to": "core_machines", "order": 50, "data": "00000000",
                "relocs": [[0, "abs32", "sym:my_machine", 0]]}],
"resources": {"names": ["machine:6"]}
```

With it, the menu lists the machine after the stock four (added ones by
id), with its name and icon; the setter takes it, and a loaded kit keeps
it (stock loads any machine past 3 as ONESHOT, and so does core for an id
no installed mod adds). The firmware gives any machine past 3 SLICE's SRC
page; to change it, hook the page layout `0x400657cc` as digineighbor
does. `core_track_machine[t]` (8 bytes) is each track's own machine as the
render last took it, for a mod whose machine renders as a stock one:
`core_machine(id)` returns an added machine's descriptor, or 0.

Core 2.1 owns these sites too (`mods/core/mod.json` says what each is;
in 1.54 they are at the same addresses, but 0x400a1706 is 0x400a1862):
0x40011322, 0x400225f0, 0x40022fe6, 0x40028f7e, 0x40029e9c, 0x4002a4e0,
0x4002a76e, 0x4002a9e8, 0x4002aee0, 0x4002ba7e, 0x40039dac, 0x40039dcc,
0x40039e80, 0x40039e86, 0x4003a43e, 0x4003afe4, 0x4003afee, 0x4003b448,
0x4003b452, 0x4003b49e, 0x4003b4ac, 0x4003b6d4, 0x4003b6de, 0x40077272,
0x40078f72, 0x40079124, 0x40079144, 0x400791d6, 0x40079240, 0x4007a2ea,
0x400a1706.

## 3. Path B: a linkable mod

**3.1 Start from the template.** Copy `examples/hello-marker/` to a folder
of your own. It is a complete mod: a C handler on `ev_draw` that draws a
small square in the top-right corner of every screen.

**3.2 Fill in `mod.json`.**

```json
{
 "id": "my-mod", "version": "1.0",
 "title": "My mod", "category": "Utilities", "author": "you",
 "license": "GPL-2.0-or-later",
 "description": "One or two sentences a user reads in the loader.",
 "device": "digitakt-mk1", "os": "1.53",
 "sources": ["my.c"],
 "subscribe": [{"event": "ev_draw", "fn": "my_draw", "order": 60}],
 "requires": ["core"],
 "resources": {"names": ["settings:MY ROW"]}
}
```

| field | |
|---|---|
| `id` | lowercase, unique; also the prefix of your global symbols |
| `license` | an SPDX identifier. The example uses `GPL-2.0-or-later`, the loader's own licence. Put the same `SPDX-License-Identifier` line at the top of each source |
| `sources` | `.c` and `.s` files, compiled/assembled with the device's flags |
| `subscribe` | `{"event", "fn", "order"}`: `fn` is one of your global functions |
| `sites` | patches to the stock image: `{"addr", "stock", "op", "target" or "new"}` (below) |
| `collections`, `contribute` | tables you declare, and entries you add to others' ([FORMAT.md](FORMAT.md)) |
| `weak` | names you import that may be missing; they then read as zero |
| `resources`, `requires`, `conflicts` | rules 9 and 11 |
| `ports` | the same mod for other OS versions of the device: per OS, the keys that differ there (3.10) |

**3.3 Write the code.** Call firmware routines through function pointers at
their addresses, as `hello.c` does. There is no C library. Keep interrupt-level
handlers (`ev_render_*`) short and free of firmware calls that might block.

**3.4 Hook a site nobody owns (only if no event fits).** Add a `sites`
entry. `stock` is the hex of the whole stock instruction(s) at `addr`;
`op` says what replaces them:

| op | new bytes |
|---|---|
| `jsr` / `jmp` | `jsr`/`jmp` to `target`, nop-padded to the stock length (6 bytes or more) |
| `keep2` | the stock opcode word, then `target`'s address (a `jsr.l`/`lea.l` you redirect) |
| `ptr` | `target`'s address (4 bytes of data, e.g. a vtable entry) |
| `bytes` | `new`, in hex; add `"kind": "code"` if they are instructions |

A site with a `target` may also give `"addend": N`: the address used is the
target's plus N bytes.

The routine a `jsr` site calls must do the displaced instruction's work
and keep every register the surrounding code relies on.

**Code at a fixed address.** This is only possible where the device lists
free space inside its image (`image_free`: on the Octatrack, the zero runs
octabam measured):

```json
"fixed": [{"source": "page.s", "addr": "0x400d24d0", "symbol": "page"}]
```

This assembles `page.s` for that address.
- It must fit inside one of those runs, and it may only have `.text`.
- It becomes a site over the zeros there, and its labels become absolute
  symbols, so other code and sites can name them. A mod built this way
  loads in any elekloader that loads format 2.
- Use it when other code must find the code at a known address. Otherwise
  put code in `.run`.

**3.5 Build it.**

```bash
python -m elekloader.sdk.build path/to/my-mod --stock Digitakt_OS1.53.syx
```

Expect `BUILT path/to/my-mod/out/my-mod-1.0.elemod` and a line with its
section sizes and imports. `BUILD FAILED: ...` names the problem.

**3.6 Check it, alone and with what it needs.**

```bash
python -m elekloader.lint my-mod-1.0.elemod
python -m elekloader.lint my-mod-1.0.elemod --stock Digitakt_OS1.53.syx --with core-2.1.elemod
```

Expect `OK: ... links as core ... > my-mod ...` and exit status 0.
Add `--with` for every mod users are likely to combine yours with, and
`--json` for machine-readable output.

**3.7 Build a firmware with it.**

```bash
python -m elekloader.patch --stock Digitakt_OS1.53.syx --mod core-2.1.elemod \
    --mod my-mod-1.0.elemod --out test.syx --version 2.0t
```

Expect `verified: ...` and `WROTE test.syx`. The file has passed every check
in the README's "What a build guarantees".

**3.8 Test before you flash.** A build that verifies is a well-formed
file, not a proof that your code works. Run it in an emulator if one
exists for the device (the example was checked by cold-booting it in
digikit's emulator: every screen differs from stock only in the corner
square, and the audio is identical). On hardware, know the recovery path
first: for the Digitakt mk1, hold FUNC while powering on for the startup
menu, then send the stock `.syx`.

**3.9 Ship the `.elemod`.** Users install it from the loader's window
(Install from file) or pass it to `elekloader.patch`. Bump `version` on
every change.

**3.10 Another OS version.** A mod is built for one release: its `.elemod`
names that stock file's hash, and the loader refuses it with any other
(`core 2.1 is made for Digitakt mk1 1.53; the stock file is Digitakt mk1
1.54`). When Elektron releases an OS, build your mod again for it. Every
address your mod names may have moved: its sites (re-read their stock
bytes), its `defsym`, and the firmware routines your C code calls. The rest
of `mod.json` stays as it is. Give the new OS's values under `ports`, and
the stock file you build with picks them:

```json
 "os": "1.53",
 "cflags": ["-DFILLRECT_AT=0x400c19a6"],
 "defsym": {"DRAWALL": "0x400ca382"},
 "sites": [{"addr": "0x401ab9b0", "stock": "00000400", "op": "bytes", "new": "00000500"}],
 "ports": {
  "1.54": {
   "cflags": ["-DFILLRECT_AT=0x400c1bce"],
   "defsym": {"DRAWALL": "0x400ca5aa"},
   "sites": [{"addr": "0x401abcb0", "stock": "00000400", "op": "bytes", "new": "00000500"}]
  }
 }
```

- A port's keys replace the top level's for its OS, whole: give every site
  and every `defsym`, not only the ones that moved. It may not change `id`,
  `version`, `device` or `os`.
- Built from a 1.54 stock file, the SDK writes `my-mod-1.0-os1.54.elemod`;
  from 1.53, `my-mod-1.0.elemod`, as before. Ship one file per OS, and lint
  each with that OS's core (`core-2.1-os1.54.elemod`).
- C code gets its addresses from `cflags` (`-D`), as
  [examples/hello-marker](../examples/hello-marker) does; assembly from
  `defsym`, as [mods/core](../mods/core) does.
- From Digitakt mk1 1.53 to 1.54, and Digitone mk1 1.43 to 1.44, only the
  main OS changed, and most of it only moved: by a few hundred bytes at
  most, and the RAM past the image by 0x1000. A window of the old code with
  its absolute addresses masked out usually finds a routine again in the
  new image. Check every match by its bytes, then run the build in an
  emulator (3.8).

## 4. Path A: a whole build

If you already build a patched firmware in one piece, `mkmod` turns it into
a format-1 mod without changing your build:

```bash
python -m elekloader.mkmod --stock Digitakt_OS1.53.syx --build my-cfw.syx \
    --manifest my-cfw.patches.json [--elf my-cfw.elf] --meta meta.json --out my-cfw.elemod
```

- The manifest lists your patches: `{"patches": [{"addr": "0x...", "old":
  "hex", "new": "hex"}]}`, each `old` the whole stock instruction(s) or data
  word. Every byte your build changes must be covered.
- No manifest? `--diff` (in place of `--manifest` and `--elf`) works the
  sites out by comparing your build with stock. A run of changed bytes is
  a code site only when it covers whole instructions on both sides;
  anything else is a data site. This is the path for whole builds, for
  example an octabam build for the Octatrack:
  `python -m elekloader.mkmod --stock OCTATRACK_OS1.40C.syx --build built.syx --diff --meta meta.json --out my.elemod`.
- The build may append one blob at the stock main OS's end (0x4025CA40 on
  the Digitakt mk1 1.53, 0x4025DA40 on 1.54); the ELF's `__run_start`, `__bss_end`,
  `__fast_start` and `__fast_len` describe where it runs.
- `meta.json`: `id`, `title`, `category`, `description`, `license`, `names`,
  `regions`, `requires`, and `data_sites` for data patches that happen to
  decode as instructions.

Expect `reproduces the build's main OS`. A format-1 mod cannot be combined
with anything, so plan the move to Path B:

1. List every site your build patches. The shared ones (section 2's table)
   become event handlers; the rest stay sites of your mod.
2. Split your code by feature. What one feature needs from another becomes
   an export and an import, or a weak import if the other is optional.
3. Make each feature a mod folder with a `mod.json`, build and lint them,
   and check that the combined build behaves like your old one (the same
   audio and screens in an emulator is a good bar).

## 4b. Octabam modules (Octatrack)

sambanks/octabam declares each Octatrack module in
`modules/<name>/manifest.py`. `elekloader.sdk.octabam` reads those
manifests from a checkout, and turns each ColdFire-only module into a
linkable mod for the Octatrack's core (`mods/core-ot`):

```bash
git clone --recurse-submodules https://github.com/sambanks/octabam
python -m elekloader.sdk.octabam --octabam octabam --stock OCTATRACK_OS1.40C.syx \
    [--module recorder-hold ...] --out ~/octabam-mods
```

`--out` must be outside the elekloader checkout: the converted mods carry
octabam's sources, and they stay out of this repository. Each converted
module gets:
- a mod folder: `mod.json`, octabam's sources, generated glue, and octabam's
  licence;
- a built `octabam-<name>-<commit>.elemod`.

Every line of output is one of these:
- `CONVERTED`, with what was checked;
- `REFUSED`, with the reason;
- `FAILED`, when a build or a check failed.

It needs the m68k cross binutils.

Where code goes:
- **Floating code** goes in the core's RAM reserve. That includes the caves
  octabam floats in zero runs inside the OS image, so such a cave is the
  same code at another address.
- **Pinned code** (`cave_addr` set) stays where octabam pins it, as
  `fixed` code (section 3).

The converter's docstring has the table from each octabam construct to what
it becomes. Before it writes `CONVERTED`, it links each mod with the core
and checks:
- **Caves.** Each cave's bytes equal its source, linked by GNU ld at the
  same address, as octabam's build links it. They also equal the bytes the
  manifest ratifies (`pinned`, or `reference(addr)`).
- **Sites.** Every site holds what octabam would write there, for the final
  addresses: hooks, `emit()` pokes, detours, symbol refs, pokes, tables.
- **The whole mod.** Its RAM and fixed code equal GNU ld's link of the same
  object.
- **Units.** A unit that octabam assembles for another CPU encodes the same
  for the chip. A unit with a `reference` still links to its author's bytes.

**Bridges** (`Override`): a module that stands in for another module's hook
converts as one mod that carries both.
- The other module's detour at that site is left out.
- The includes are generated for the pair.
- The bridge conflicts with the other module alone.

What does not convert, and why:
- **DSP code.** Modules with DSP code or an FX menu entry are out of scope.
- **Code pinned outside the device's free image areas.**
- **Formatter registrations.** They draw a DSP module's knob.
- **Runtimes.** This covers Octakit's runtime, arena reservations, and
  bridges over a runtime's writes (KITS RELOAD, SCENES KITS, SCENES P2 KITS).
- **Writes into the protected bootloader copy**, other than a poke wholly
  inside data the device marks `relocatable` (below). The 16 KB below
  `0x400e21e0` stay stock; octabam also places the bootstrap copy there
  (`~0x400de7dc`).
- **Modules that serve DSP modules only.** These are MODE DEFAULTS, RIG
  HOSTS and TEMPO BUS (`SERVES_DSP` in the converter, with the reasons).
  Converted alone, they would be inert, or they would point parts at
  engines the image does not have.
- **Modules that need one of the above.**

Some differences from an octabam build, by design:
- **`include` units** get the text octabam would generate for the modules
  the mod carries.
  - If that text would change with another module that converts, the mod
    conflicts with that module.
  - If it would change only with modules that do not convert, the notes say
    so.
- **`defsyms`** keep the manifest's own value, even where octabam would
  link another module's symbol (CC MAP's `CC_MODEDEF1`).
- **Claims** (Part window, SRAM) become one named resource per 16-byte
  block. Overlapping claims share a name, so the linker refuses the pair,
  as octabam's ledger does for MIDI SCENES and SCENES P2.
- **A `jmp` detour** whose six bytes end inside an instruction is
  nop-padded to that instruction's end.
- **A poke into relocatable data** (the device profile's `relocatable`) is
  served from a copy. The USB AUDIO OUT modules set the class of the USB
  device descriptor (`0x400e2004`, inside the protected bootloader copy).
  Converted, each carries a copy of the 18-byte descriptor in `.run` with
  that poke applied, and points the descriptor's one reference
  (`0x4001d82e`, the `pea` that GET_DESCRIPTOR sends from) at it.
  - The host reads the same bytes as from octabam's build.
  - The protected range stays stock. The check proves the copy, the
    reference and the untouched original.
- **The assembler.** octabam builds with the bare-metal `m68k-elf` binutils.
  Ubuntu's `m68k-linux-gnu-as` is for a Linux target: it leaves every
  reference to a global label to the linker (a shared library may preempt a
  global), where `m68k-elf-as` resolves it in a shorter PC-relative form.
  - With `m68k-linux-gnu`, such code assembles longer: the same code, but
    not the same bytes. A unit whose author pinned its bytes (USB MIDI)
    fails its check.
  - The converter uses `m68k-elf-` when it is on the PATH (or
    `ELEKLOADER_CROSS`), and says at the start which kind it has.
  - To build it: GNU binutils, `configure --target=m68k-elf`, then
    `make all-gas all-ld all-binutils`.

## 5. When the loader refuses: message → fix

| message contains | means | fix |
|---|---|---|
| `made for a firmware elekloader does not know` | the target or stock file is not a supported release | use the exact stock file; check its hash against `devices/` |
| `is made for <device> 1.53; the stock file is <device> 1.54` / `mod.json is for ... 1.53; the stock file is ... 1.54` | the mod is for another OS version | build it for that OS: a port (3.10) |
| `the stock bytes are ..., not ...` (SDK) / `not the ones it expects` | the address is wrong, or the OS version differs | re-read the stock bytes at that address |
| `ends mid-instruction`, `sweeps land on the start`, `does not decode` | the site does not cover whole instructions | move or widen the site to instruction boundaries (disassemble the stock main OS) |
| `... overlap (0x...-0x...)` | another mod patches or claims those bytes | subscribe to an event instead, or agree with that mod's author |
| `X requires Y` / `core is not enabled` | a dependency is missing | add Y (with lint: `--with Y.elemod`) |
| `imports N, which no given mod exports` | a missing dependency, or a typo | add the mod that exports N, fix the name, or list N under `weak` |
| `adds to table T, which no given mod declares` | the table's owner is missing, or the event name is wrong | add core (or the owner); check the event name |
| `both export S` | two mods define the same global | prefix your globals with your mod id; make internals `static` |
| `relocation type N` | a reference the linker cannot relocate (e.g. 16-bit absolute) | use 32-bit addressing for your own symbols; build with the SDK's flags |
| `section X is not one elekloader places` | code or data in a section the linker does not know | C: default sections; asm: `.section .run, "ax"`, `.fast` or `.bss` |
| `the mods need RAM to ...` / `.fast code needs SRAM to ...` | over budget | shrink tables and buffers; keep `.fast` for the hottest code only |
| `has .fast code, which needs ...` | `.fast` is copied in by FAST AUDIO | require `fast-audio`, or use `.run` |
| `PC-relative, inside ... copied block` | a site in FAST AUDIO's block branches relatively | use an absolute `jmp`/`jsr` |
| `both claim N` | two mods use the same named resource | pick another SysEx id, row name or path |
| `is a whole build: it cannot be combined` | a format-1 mod was mixed with format-2 mods | use one or the other; see section 4 |

## 6. Definition of done

- [ ] `python -m elekloader.sdk.build <dir> --stock <stock.syx>` prints `BUILT`.
- [ ] `python -m elekloader.lint <mod> --stock <stock.syx> --with <core> [--with <others>]`
      exits 0, with every mod users are likely to combine yours with.
- [ ] `python -m elekloader.patch ... --out test.syx --version XXXX` prints `WROTE`.
- [ ] `mod.json` has `description`, `category`, `license`, `requires`, and every named
      resource you use under `resources.names`.
- [ ] Your sources hold no copied firmware code, and no firmware file is
      committed anywhere.
- [ ] The build ran in an emulator or on a device you can recover.
