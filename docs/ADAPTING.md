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
  source (with `settings.s`, `render.s` and `fast.s` where the device
  uses them); `mods/core` builds it for the Digitakt mk1
  (`python -m elekloader.sdk.build mods/core --stock Digitakt_OS1.53.syx`),
  `mods/core-dn1` for the Digitone mk1 and `mods/core-dt2` for the
  Digitakt II. The Octatrack's core, `mods/core-ot`, has a hook bus of
  its own from 0.2, with the Octatrack's events ("The hook bus on the
  Octatrack" below).

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

### The hook bus (core's events): the Digitakt mk1, the Digitone mk1 and the Digitakt II

Handlers are C functions (arguments on the stack; d0-d1/a0-a1 free,
everything else kept; the result in d0). `order` sorts handlers of one
event (lower first; the shipped mods use 10-90).

| event | when | C prototype | notes |
|---|---|---|---|
| `ev_tick` | 30 times a second, UI task | `void f(void *ctrl)` | set `*((unsigned char *)ctrl + 0x20) = 1` to redraw |
| `ev_draw` | after each frame is drawn | `void f(void *bmp, void *ctrl)` | draw over the frame; y = 0 is the bottom row |
| `ev_key` | each key event | `int f(void *brain, void *ev)` | return nonzero to take it: nothing later sees it. `ev+12` key id, `ev+16` flags (1 pressed, 8 repeat, 2 FUNC held; measured on the Digitone mk1: 8 comes once, about 0.4 s into a key held on its own, 4 marks a double press, 0x10 a release) |
| `ev_enc` | each encoder turn | `int f(void *brain, void *ev)` | `ev+12` encoder 1-8 (A-H), `ev+16` delta |
| `ev_settings` | the SETTINGS menu is built | `void f(void *menu)` | add a row with `core_additem(menu, row)`; `row` is four callbacks (label, select, draw, change) in the firmware's MenuItem conventions, which this guide does not document yet |
| `ev_render_in` | audio render entry, 1500 times a second | `void f(void)` | interrupt level: keep it short |
| `ev_render_out` | audio render exit | `void f(void)` | the same |
| `ev_hold` | Digitone mk1 only (core-dn1 2.2): a track key held on its own, UI task | `int f(void *brain, void *event, int track)` | return nonzero to take it; when none does, core opens the Mod Menu ("The Mod Menu" below) |
| `ev_personalize` | Digitakt II only (core-dt2): SETTINGS > PERSONALIZE is built | `void f(void *menu)` | add a row with `core_additem(menu, row)`, after TRK SELECT; a row redraws the menu with `View::invalidate(menu + 0x38)`, as from SETTINGS; a checkbox is drawn as mods/core-dt2/README.md describes |
| `ev_voice_on` | Digitone mk1 only (core-dn1 2.1): a voice starts a note, in the render | `void f(int voice, int track, void *event)` | interrupt level. The voice's pitch word (`0x41391f80` + 4 x voice, the note << 16) is already written and may be changed: the render reads it every block. The voice's sound and the step's locks load after this, so read the voice's parameters from `ev_render_out` |

The events, their prototypes and their conventions are the same on every
device; only the sites differ, and `ev_voice_on` exists on the Digitone
only. The Digitakt II's core (mods/core-dt2 1.0) has `ev_tick`, `ev_draw`,
`ev_key`, `ev_enc`, `ev_settings` and its own `ev_personalize`, and no
render events: its audio
renders on the DSP. It copies `.fast` code into SRAM itself, on the first
`ev_tick` (`core_fast`): subscribe only `.run` code to `ev_key` and
`ev_enc` there, since a key can come before that tick (`ev_draw` cannot:
the tick site runs first). The sites core owns (do not patch them):
- Digitakt mk1 1.53 and 1.54: 0x40000538, 0x4000a770, 0x4000a7d6,
  0x4000b770, 0x4000b7ba, 0x40058800, 0x40077428, 0x400784c8;
- Digitone mk1 1.43: 0x40000538, 0x4001900c, 0x40019072, 0x40019d9c,
  0x40019de4, 0x40072a34, 0x4009d108, 0x4009e51c, and from core-dn1 2.1
  0x4009e928;
- Digitone mk1 1.44: the same, but 0x40072a54, 0x4009d128 and 0x4009e53c
  for the last three of the eight, and 0x4009e948;
- Digitakt II 1.17: 0x40000538, 0x40032ad4, 0x40032b3a, 0x40033d94,
  0x40033dde, 0x400a5eac, 0x4009e2a2.

A firmware routine your mod calls has its own address on each device and
each OS version: look it up for the release you target, and build one
`.elemod` per device and OS (a mod's `device` and `os`, or one of its
`ports`, pick the stock file: 3.10).

### The hook bus on the Octatrack (core-ot 0.2)

The Octatrack's firmware is not the Digitakt's, so its events carry what
its own routines have. The conventions are the same: C handlers, `order`,
and `subscribe` in mod.json. A mod that subscribes to one of these is
refused with core-ot 0.1 (*"adds to table ev_tick, which no given mod
declares"*).

| event | when | C prototype | notes |
|---|---|---|---|
| `ev_tick` | 60 times a second, sys task | `void f(void)` | the task `ev_key`, `ev_enc` and (nearly always) `ev_draw` run in, so their handlers never interrupt one another |
| `ev_draw` | each composed frame, before the bytes that changed go to the LCD | `void f(unsigned char *frame)` | 1024 bytes: 128 rows of 8 bytes, one per screen column x (0 at the left); line y (0 at the top) is bit 63 - y of the row, counting from its first byte's most significant bit. The frame is cleared and composed again each time: what you draw stays one frame. `examples/hello-marker-ot` |
| `ev_key` | each key press and release | `int f(int code, int pressed)` | the firmware's key code (PLAY 0x28, YES 0x31, NO 0x32, UP 0x33: octabam's docs/firmware/PANEL.md); `pressed` nonzero on a press, 0 on a release. Return nonzero to take it: the firmware never sees it. Auto-repeat does not come here |
| `ev_enc` | each encoder turn | `int f(int encoder, int delta)` | the firmware's encoder index, 0-7; return nonzero to take it |
| `ev_midi` | each MIDI message in, MIDI thread | `int f(const unsigned char *msg)` | `msg[0]` the status, then its data bytes; return nonzero to take it: the firmware's handler for it is not called |
| `ev_frame` | the frame interrupt, every 16 samples (2,756 a second) | `void f(void)` | interrupt level: keep it short. It runs before the interrupted task's EMAC state is put back, so it may use the EMAC |

The sites core-ot owns (Octatrack 1.40C): the boot site 0x4000050c, the 28
arena writes listed in its `mod.json`, 0x40061e94, 0x40013cae, 0x40061dc8,
0x40061e00, 0x40005572 and 0x4000d94e, and its draw gate at
0x400c46ea-0x400c4702. They keep clear of every byte that the converted
octabam modules (4b) patch.

### SRC machines (core 2.1, Digitakt mk1)

The Digitakt mk1 has four SRC machines: 0 ONESHOT, 1 WERP, 2 REPITCH and
3 SLICE, kept in a sound's byte +0x7E. From core 2.1 a mod can add one: it
contributes to the table `core_machines` a pointer to a descriptor of six
longs:

| offset | field | |
|---|---|---|
| +0 | id | its number, 4-127. Kits store it, so it is fixed for good: claim it as the resource `machine:<id>`. Taken so far: 4 NEIGHBOR, 5 DIGISLICER, 6 Digi Poly's POLY, 7 SOPHIE, 20-29 Digi Mono's (20-26 in use); pick another, and say which in your mod's README |
| +4 | name | its name in the machine menu and the SRC page's title (10 characters fit) |
| +8 | short | its 4-character name (the SRC page's `NAME: sample` title) |
| +12 | icon | an 11 x 7 Bitmap for the menu, in the stock icons' format, or 0 |
| +16 | params | the stock machine (0-3) whose 8 parameters it takes: their defaults on a switch, MIDI CC 16-23 and NRPN 0x80-0x87, the Randomize and Reload pages, the SAMP lookup of the sample browser |
| +20 | render | the machine it plays as: a stock one (0-3) in the audio render and in that machine's features elsewhere (SLICE's slice locks, its keyboard slice pages, its SRC page state); or its own id, for an empty voice window a mod fills |

```json
"contribute": [{"to": "core_machines", "order": 50, "data": "00000000",
                "relocs": [[0, "abs32", "sym:my_machine", 0]]}],
"resources": {"names": ["machine:30"]}
```

or, with the SDK, the same in one line: `"machines": [{"id": 30,
"descriptor": "my_machine"}]`.

With it, the menu lists the machine after the stock four (added ones by
id), with its name and icon; the setter takes it, and a loaded kit keeps
it (stock loads any machine past 3 as ONESHOT, and so does core for an id
no installed mod adds). The firmware gives any machine past 3 SLICE's SRC
page; from core 3.0 a machine describes its own instead ("Machine pages",
below). `core_track_machine[t]` (8 bytes) is each track's own machine as the
render last took it, for a mod whose machine renders as a stock one:
`core_machine(id)` returns an added machine's descriptor, or 0.

### Core 3.0 (Digitakt mk1)

Core 3.0 is core 2.1 and more: the same 39 sites with the same bytes, the
same events and tables, and every 2.1 symbol where 2.1 has it (2.1's code
is the start of 3.0's). A mod built for 2.1 links with 3.0 too, and builds
the same bytes it did with 2.1 apart from where the mods are placed.
`tests/test_sdk.py` checks this against the released core 2.1. What 3.0
adds patches nothing:
- **firmware locations as exports**, so a mod can name them instead of
  their addresses (below);
- **`core_machine_ui(id)`**, the page a machine describes (the
  machine-pages mod draws it: "Machine pages").

A mod that needs 3.0 says so in `resources`, which elekloader 0.4.0 and older
ignore:

```json
"resources": {"core": "3.0"}
```

The loader then refuses it beside an older core with *"needs core 3.0 or
newer"*, and an older loader with the imports it cannot resolve.

**Which core a build takes.** A builder (the app, the web page, the kit)
takes, of the cores it has for the stock OS, the newest of the oldest major
line that every selected mod's `resources.core` (the catalog's
`needs_core`) allows. A selection that needs nothing from 3.0 builds with
2.x, as it did before 3.0 existed; one that needs 3.0 builds with the
newest 3.x. A core chosen by hand that is new enough is kept.

### Firmware locations (core 3.0, Digitakt mk1)

Core 3.0 exports the firmware data and routines machine mods use as
absolute symbols, with each OS's value in its port. A mod that names them,
and patches no site of its own, builds for another OS version with no
change but a port entry with nothing in it. In C, `#include
"digitakt-mk1/core3.h"` (the SDK has it on the include path); in assembly
use the names as they are.

| name | 1.53 | |
|---|---|---|
| `fw_track_blocks` | 0x80001a18 | the render's block of each track: 32 Q31 samples, 128 bytes a track |
| `fw_render_machine` | 0x800018bc | the machine each track renders as, a byte a track |
| `fw_voice_params` | 0x80002794 | the machine's 8 parameters A-H, 8.8, 106 bytes a track |
| `fw_voice_note`, `fw_voice_vel` | 0x80001f28, 0x80001f18 | the trig's note (16.16) and velocity (8.8) |
| `fw_voice_start` | 0x80001228 | bit t: track t starts a voice this block |
| `fw_amp_env` | 0x4199df54 | the AMP envelope: phase +0, level +4, 12 bytes a track |
| `fw_pitch_tab` | 0x4019b1c0 | 2^((i - 10752) / 2048) in Q29 |
| `fw_active_track` | 0x4197b6b4 | the active track, 0-7 |
| `fw_kit` | 0x4199dc44 | -> the UI kit: track t's sound at +0x20 + 0xa2 t, its machine at +0x7e |
| `fw_slice_layout` | 0x4197cf5c | SLICE's SRC page layout |
| `fw_set_param` | 0x400771e8 | `set_param(value, track, slot)`: a knob's path into the engine |
| `fw_bitmap_vt` | 0x401b73b4 | a Bitmap's vtable (an icon's first long) |
| `fw_fillrect`, `fw_framerect`, `fw_textf`, `fw_font5`, `fw_blit` | | drawing, as `mods/core/fw.s` lists them |
| `fw_op_new` | 0x400d4180 | the firmware's heap |

Each 1.54 value was found by the code that uses it (the render's
locations are the same in both; the rest moved), and is in
`mods/core/mod.json`'s port.

### Machine pages (core 3.0 and machine-pages, Digitakt mk1)

Every machine mod used to hook the SRC page itself (its layout, labels,
value texts, knob graphics and ranges), the LFO page's names and the
render point after playback, so no two could be in one build. The
`machine-pages` mod (`mods/machine-pages`) owns those places once and
answers each from what a machine describes. A descriptor goes on past
its six longs with a tagged tail, which core 2.1 does not read:

| offset | field | |
|---|---|---|
| +24 | tag | 0x55493330, `"UI30"` |
| +28 | ui | its page, a `struct cm_ui` |

The page (`struct cm_ui`, 336 bytes; `digitakt-mk1/core3.h`):

| offset | field | |
|---|---|---|
| +0 | abi | `cm_ui_v3`, which machine-pages exports: the machine links only beside it |
| +4 | page_from | the stock machine whose SRC page it copies (byte): 3 SLICE, 0 ONESHOT |
| +5, +6 | | 0 |
| +8 | group | the LFO page's group for its parameters, or 0 for the stock one |
| +12 | on_switch | `void f(int track, int from, unsigned char *sound)`, called on the UI task when a track of the kit turns to the machine (the machine menu switches as its cursor moves), or 0 |
| +16 | knob[8] | A-H, 40 bytes each |

A knob (`struct cm_knob`); a 0 field is the stock one:

| offset | field | |
|---|---|---|
| +0, +4 | name, lname | its label on the SRC page, and its long name (the pop-up) |
| +8, +12 | lfo, lfo_long | its names on the LFO page: the DEST box's, and the DEST list's (0: name and lname; a blank knob reads "Unused") |
| +16 | look | the parameter id whose UI record and graphic it borrows (byte): how a turn moves it, its knob |
| +17 | flags | 1 blank (it shows and turns nothing), 2 the range min-max, 4 the default def, 8 knob D is not a sample (turning it does not open the sample list) |
| +20, +24, +28 | min, max, def | 8.8 |
| +32 | fmt | `int f(char *buf, int value, int ctx, int machine)`: its value's text into buf, returning nonzero (0: the stock text). ctx 0 is the value under a turning knob, about 5 characters; 1 the pop-up, up to 15 |
| +36 | gfx | `int f(int value)`: the value its graphic shows (whole steps) |

In assembly `digitakt-mk1/core3.inc` has `CM_MACHINE`, `CM_UI` and
`CM_KNOB`; digineighbor 0.7, digislicer 2.3 and SOPHIE's core 3.0 build use
them. `examples/sine-machine` is a whole machine in C to start from: a sine
the trig's note plays and a SHAPE knob folds, its page, its icon, and no
firmware address, so its 1.54 port is empty. A machine with a page needs
core 3.0 and machine-pages:

```json
"machines": [{"id": 30, "descriptor": "my_machine"}],
"requires": ["core", "machine-pages"],
"resources": {"core": "3.0"}
```

Which machine a site answers for: the SRC page's sites, the machine whose
layout the page asked for last (it asks with its track's machine before it
draws or turns a knob); a range, the machine of the sound the parameter
belongs to; the LFO page, the active track's machine. A parameter id is a
knob by the ids of the stock machine the page copies (`0x6c + 8 page_from`
onwards, A-H), or else of its params machine (the ids MIDI, the LFOs and
Randomize use).

**The render event.** machine-pages declares `ev_render_voices`,
`void f(int *blocks)` with `blocks` = `fw_track_blocks`, called after
playback has written every track's block and before the overdrive
(0x40077fba): order 10-49 for a machine that makes a track's sound
(SOPHIE: 20), 50-89 for one that takes or changes sound already made
(NEIGHBOR: 60).

What it took, and what each port was checked against, is in
`mods/machine-pages/README.md`. A machine that keeps hooking the page
itself (core 2.1's way) still links with core 3.0, but not beside
machine-pages, whose sites it overlaps.

### Parameter slots (core-dn1 2.1, Digitone mk1)

A Digitone mk1 parameter is an id (0-181) with a 60-byte record; the knob
code, its pop-up, its value text, its p-locks, copy and paste all go through
the id. From core-dn1 2.1 a mod can add ids 182, 183 and 184: core raises the
firmware's id bounds (58 of them) and puts the records right after the stock
ones, so the stock UI handles them as its own. The mod contributes to the
table `core_params` a pointer to a descriptor:

| offset | field | |
|---|---|---|
| +0 | id | 182, 183 or 184: claim it as the resource `param:<id>` |
| +4 | group | the page group: 1 Amp, 2 Filter, ... (a sound page's, for a sound parameter) |
| +8 | slot | the sound parameter it edits (0-78): a slot no stock parameter of that kind uses, e.g. 26 on a synth track |
| +12, +16, +20 | min, max, default | 8.8 fixed point, as the slot holds them |
| +24 | flags | 0 |
| +28 | cc | MIDI CC (MSB << 16 \| LSB), or -1 for none |
| +32, +36, +40 | | -1, -1, 0 |
| +44, +48, +52 | name, group name, short name | the pop-up's `Name=value`, and the knob's label |
| +56 | format | `void f(int value, char *buf)`: the value's text |
| +60 | | the firmware's empty string, `0x401ddbcd` |
| +64 | look | the stock parameter whose knob it borrows (graphic, how a turn moves the value, scale), or 0 for PTIM's (24): a plain knob in whole steps |

To put it on a stock page, replace the instruction of the page's static
constructor that writes that knob's id (or give it a page of its own: "Mod
pages", below): a page's eight ids are written with
immediates, not read from a table: AMP page 1's knob F, empty, is cleared
by `clrl 0x4136b6d4` at `0x4016affe`, so a `jsr` there to a routine that
writes 182 puts id 182 on it.

Core-dn1 2.1 owns these sites too (`mods/core-dn1/mod.json`): the boot call
at 0x40000538 now goes to `core_dn_boot`, which moves two small tables from
0x4018fbac (and 0x4000820a, 0x4000821a and 0x4000b154 follow them) and
installs the records; 0x400899c8 and 0x400899e6, the UI record lookups; and
every `cmpi.l #182`, `cmpi.l #181` and `cmpa.l` id bound but the three loops
over the stock records (0x400078c2, 0x40030f10, 0x40082d6e).

### Mod pages (core-dn1 2.1, Digitone mk1)

A Digitone mk1 parameter page (SYN1's two, AMP's two, ...) is a 44-byte
record: a short and a long title (char pointers; the long one heads the
screen), its eight knobs' parameter ids (0 is an empty box) and a kind (9 for
a sound's page). The firmware has 26, indexed 1-26 and found through one
routine (0x40089a2c); each page key's view keeps the indices of its pages in
a list and steps through them when the key is pressed again. From core-dn1
2.1 a mod can add pages 27-30: it contributes to the table `core_pages` a
pointer to a descriptor, in writable data:

| offset | field | |
|---|---|---|
| +0 | idx | 27-30: claim it as the resource `page:<idx>` |
| +4 | after | the stock page it follows in its key's list: 9 (AMP's second page) makes it AMP's third |
| +8, +12 | short title, title | the title heads the screen, with the page count ("Table (3/3)") |
| +16 | ids | the eight knobs' parameter ids, A to H; 0 is an empty box. Stock ids or a mod's parameter slots |
| +48 | kind | 9 |
| +52 | view | 0: core writes the key's view here when the firmware builds it |
| +56 | pos | core writes the page's place in that view's list |

The stock UI then shows the page, with its key's other pages, and draws,
turns and p-locks its knobs as its own. `int core_page_open(void *brain,
void *event, int key, descriptor *page)`, called from an `ev_key` handler
with its brain and event, opens it: it presses and releases the page's key
(AMP is 24) through the stock key dispatcher until that key's view shows the
page, and returns 0 if the view was never built: from a Mod Menu entry,
say (below). `int core_page_shown(void *brain, descriptor *page)` is 1
while the page is on screen with nothing (a menu, a browser) over it.

Core-dn1 2.1 owns two more sites, by jmp at their entries: 0x40089a2c, the
page record lookup (`core_page_rec`), and 0x40044490, the routine each
view's constructor gives its page list to (`core_view_init`).

### Project data (core-dn1 2.1, Digitone mk1)

A Digitone mk1 project is saved as one block, `projectStorage_v14_t` (2782212
bytes): the OS serializes the project in RAM into a storage buffer and
writes that buffer to the project's slot on the card, to the temp area, or
keeps it as its working copy; a load reads a slot into a buffer and
deserializes it. The block starts with a 32-byte header (0xBEEFBACE, version
14, the name, ...) and its first record is at +0x200: the 480 bytes between
are written and read with the rest, and the OS neither fills nor reads them.
From core-dn1 2.1 mods keep data there. A mod contributes to the table
`core_projdata` a pointer to a descriptor:

| offset | field | |
|---|---|---|
| +0 | tag | four characters: claim it as the resource `projdata:<tag>` |
| +4 | size | bytes, a multiple of 4 |
| +8 | data | the mod's copy in RAM, which it reads and writes as it likes |
| +12 | loaded | `void loaded(int found)`, or 0: called after a project's data is in RAM; `found` is 0 when the project has none for this tag (saved without the mod, or a new project), and data then holds zeros for the mod to fill with its defaults |

Core puts every block in the gap each time the project is serialized, and
takes them out when one is deserialized or a new one is made: the gap holds
`ELKP`, then per block its tag, its size and its bytes, then a zero tag. A
project saved this way loads on the stock OS, which ignores the gap, and the
stock OS keeps a gap it loaded when it saves. The macro mod keeps its 16
tables there (`TBL1`, 320 bytes).

Core-dn1 2.1 owns five more sites: 0x4000eb10, the serializer's entry (by
jmp: every save, to a slot, to the temp area or the working copy);
0x400acc40, the deserialize in the load of a slot, and 0x40010cfa, the one in
the load of a block already in RAM (at boot, and from SysEx), both by jsr;
0x4001570e, the new project's builder (CREATE NEW, by jmp), and 0x400acbf4,
the template copy of slot -1's load (by jsr).

### The Mod Menu (core-dn1 2.2, Digitone mk1)

Holding a track key (T1-T4) on its own, about half a second, is core's: it
calls the handlers of `ev_hold` first, and when none takes it, it opens the
Mod Menu, a screen of what mods contributed to the table `core_menu`.
Each entry is a pointer to a descriptor:

| offset | field | |
|---|---|---|
| +0 | name | its label in the menu, 14 characters (core-dn1 2.2's list showed about 20) |
| +4 | open | `void open(void *brain, void *event, int track)`: picked. `event` is the key's that picked it, `track` the one held (0-3); with them a mod can open its page (`core_page_open`) or a screen of its own |
| +8 | tag | from core-dn1 2.3, optional: `0x49434F4E` ("ICON") when an icon follows |
| +12 | icon | 16 rows of 16 pixels, an `unsigned short` each: the top row first, bit 15 the left pixel. 0 for core's own |

From core-dn1 2.3 the menu is a grid of tiles like an old PDA's launcher,
two across and two down with a scroll bar beside them. A tile has the
entry's icon over its label and, in its corner, the trig key that picks it;
the selected tile is drawn inverted, and a slot past the last entry shows
only its corners. An entry without an icon (a 2.2 descriptor of eight
bytes, or 0 at +12) gets core's own, a chip. Core 2.2 reads only +0 and
+4, so a descriptor with an icon works with either core; core 2.3 reads
the four bytes after a 2.2 descriptor too, and takes an icon only when
they are the exact tag. digitables' TABLES, in C:

```c
static const unsigned short digitables_icon[16] = {    /* table 1 as bars */
    0x0000, 0x0e00, 0x0e00, 0x0e00, 0x0e00, 0x0ee0, 0x0ee0, 0x0ee0,
    0x0eee, 0x0eee, 0x0eee, 0xeeee, 0xeeee, 0x0000, 0xffff, 0x0000
};

const struct {
    const char *name;
    void (*open)(void *brain, void *ev, int track);
    unsigned long tag;                  /* 0x49434F4E, "ICON": an icon follows */
    const unsigned short *icon;
} digitables_menu = { "TABLES", digitables_menu_open, 0x49434F4EUL, digitables_icon };
```

In the menu the arrows or any knob move the selection (UP and DOWN a row,
LEFT, RIGHT and the knobs a tile), YES or trig key N picks, NO or holding a
track key again closes it, and a page key (TRIG ... LFO) closes it and goes
on to its page; PLAY, STOP, FUNC and the track keys work as ever. A mod takes the hold from `ev_hold` when it has a better use
for it where it is: the macro mod lists TABLES (its TBL page) in the menu,
and opens its table editor when the hold comes with the TBL page on screen.

The hold is the stock key event's flags 0x9 (down, held), about 0.4 s in. A
key pressed meanwhile stops it, but one pressed before does not (MIDI held,
then a track key, selects a MIDI track) and neither does a knob, so core
counts a hold only when the track key went down with no other key down and
no knob turned since. The stock OS does nothing with 0x9 on a track key held
alone; a double press (the sound browser) and FUNC + a track key (mute) are
untouched.

On the Digitone the four UI sites (0x4001900c, 0x40019072, 0x40019d9c and
0x40019de4) go to core-dn1's own `core_dn_tick`, `core_dn_draw`,
`core_dn_key` and `core_dn_enc` (`menu.s`), which see to the menu and go on
to core.s's handlers, so core.s stays the Digitakt's.

The addresses in these four sections are OS 1.43's. In 1.44 the same
routines are there, unchanged but moved, and RAM is 0x1000 further on:
`mods/core-dn1/mod.json`'s `ports` has every one of core-dn1's sites for it.

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
small square in the top-right corner of every screen. For the Digitakt II,
`examples/hello-marker-dt2/` builds the same source, and
`examples/perform-direct/` is a real mod in one key handler.

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
| `dsp`, `subscribe_dsp` | DSP code, on a device whose OS runs some (below, "DSP code") |
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
| `dsp_jsr` | `jsr >target` over one two-word DSP instruction (6 bytes) in a DSP payload |

A site with a `target` may also give `"addend": N`: the address used is the
target's plus N bytes (N words for `dsp_jsr`).

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

**DSP code (the Octatrack).** The Octatrack's main OS uploads code to its
two DSP56300 cores at boot (payload A runs on core 0, B on core 1). A mod
can carry DSP code too. It is placed in P memory that another mod frees:
the profile lists those areas (`dsp_areas`), and the mod that frees one
claims its name, for example `dsp:harvest:SPATIALIZER` (payload A's 261
words at P:0xaa8, the SPATIALIZER effect's code). Without that mod, yours is
refused.

```json
 "dsp": [{"source": "inject.asm", "payload": "A"}],
 "subscribe_dsp": [{"event": "ev_dsp_rx", "fn": "inject", "order": 20}]
```

- The SDK assembles each source with octabam's `dsp_asm` (its
  `vendor/dsp56300` build). Point `ELEKLOADER_DSP_ASM` at it, or put it on
  the `PATH`. The syntax is dsp_asm's: one instruction a line, `;`
  comments, `label:`.
- Your labels become symbols of the mod, at DSP word addresses, so
  `subscribe_dsp`, sites and other mods can name them.
- The SDK assembles each source at two origins. A word that moves with the
  origin holds an address in your code, so it becomes a relocation, and the
  linker writes the address where the code lands. A short or packed address
  (one that is not a whole word) cannot be moved, and the build refuses it.
  Branches (`bra`, `bsr`, `bcc`) are relative and need nothing.
- `subscribe_dsp` adds `jsr >fn` (plus `addend` words) to a DSP table, in
  `order`. A DSP table is declared as `{"entry": 6, "space": "dsp.A",
  "head": hex, "end": hex}` under `collections`: its words are the head,
  the entries, then the end (FORMAT.md, "DSP code").
- `dsp_jsr` hooks one two-word instruction of a payload: its `stock` is
  those 6 bytes (24-bit little-endian words, as the payload holds them).
  What it calls must do the displaced instruction's work.
- Test DSP code under a DSP emulator before any hardware: octabam's
  `ot_emu --dsp` runs both cores.

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

**Remixes** (`--remix NAME`): an octabam remix converts as one mod. Use it
for USB AUDIO IN, which only converts this way:

```bash
python -m elekloader.sdk.octabam --octabam octabam --stock OCTATRACK_OS1.40C.syx \
    --remix usb-io-tracks-main-cue-ab --out ~/octabam-mods
```

- The mod carries the remix's own modules (not the stock effects it
  lists), converted as above, with the includes generated for all of them.
- A module whose DSP code is reached only by its hooks into stock DSP code
  (no FX menu entry, no knobs) converts here: USB AUDIO IN's RX inject.
- Everything else the remix writes in the OS image comes from octabam's own
  build of it. The converter runs `tools/build/build_bus.py` in the checkout
  (it needs the checkout's `dsp_asm` from `make setup`, and `m68k-elf` on the
  PATH; it rewrites the checkout's `out/mainos_bus.bin`), or takes that file
  from `--reference`. Each byte it changes outside this mod's sites and the
  core's becomes a data site. For the 12 `usb-io-*` remixes that is:
  - the RX inject in SPATIALIZER's DSP code on payload A, and its hook at
    `P:0x88`;
  - SPATIALIZER's dispatch on payload A pointed at the null stub;
  - the FX1 and FX2 choosers without SPATIALIZER, and their row tables.
  So these mods take SPATIALIZER off both FX menus, as the remixes do.
- **The check** links the mod with the core and requires the OS image to
  equal octabam's build in every byte. The only exceptions are the address
  operands of our placed code and the descriptor served from a copy. On top
  of that, each module gets the usual checks above.
- Like a bridge, a remix mod conflicts with each of its modules alone.

**On the hook bus** (`--bus`): the hooks the Octatrack core's bus serves
(core-ot 0.2) subscribe to its events instead of patching their sites.
- **Which hooks.** The converter's `BUS` table names them, each read from
  its module's own source:

  | module | its hook | the bus event |
  |---|---|---|
  | TUNER | frame_isr's tail (0x4000d99a) | `ev_frame` |
  | TUNER | the UI task's loop head (0x40056c72) | `ev_tick` |
  | CC FEEDBACK | the key-repeat task's loop (0x4005595c, 120 Hz) | `ev_tick`, two sweeps a tick, so its rate stays the same |
  | CC MAP | the CC entry of the MIDI dispatch (0x400d64a0) | `ev_midi`: it takes CC 62-73 and passes the rest on |
  | USB AUDIO OUT, every layout and every `usb-io-*` remix | the per-block producer (0x4000d9a0) | `ev_frame` |

  TUNER's TEMPO opener and the USB modules' other hooks are not bus events,
  so they stay sites, as without `--bus`.
- **What changes.** The hook's site is left stock. Generated glue
  (`glue/ob_<name>_bus.s`) subscribes to the event and keeps the C
  convention. It calls the hook's own code:
  - CC FEEDBACK's `cf_sweep` already keeps the C convention, and is called
    as it is;
  - TUNER's and USB's stubs take every register as free and end by jumping
    back to the firmware. Their one jump back is rewritten in the source to
    reach the glue;
  - CC MAP's cave passes a CC on through its `CC_NEXT`. The glue defines
    `CC_NEXT`, instead of the stock handler's address.
- **Versions.** Such a mod is versioned `<commit>-bus` and needs core-ot 0.2
  or newer. With core 0.1 the linker refuses it (*"adds to table ev_frame,
  which no given mod declares"*). Every other module converts exactly as
  without `--bus`.
- **The check also proves the bus hooks.** For each one:
  - its site is stock in the linked image, and its glue is in the event's
    table;
  - a stub entered past its replay of the displaced instruction starts with
    that instruction;
  - a rewritten source assembles to octabam's bytes but for its jumps back
    to the firmware, whose relocations name the glue;
  - CC MAP's cave equals octabam's link (and its ratified bytes) but for
    its `CC_NEXT` operand.

  In a remix, the hook's 6 bytes octabam's build writes are the only other
  bytes allowed to differ, and only while they are stock.

What does not convert, and why:
- **DSP code.** Modules with DSP code or an FX menu entry are out of scope,
  but for hook-only DSP code in a remix (above).
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
| `X needs core 3.0 or newer, and this build has core 2.1` | the mod's `resources.core` asks for a newer core | build with that core (the app and the web page take it when you tick the mod); an older loader says `imports fw_..., which no given mod exports` instead |
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
| `has DSP code for payload A, which needs a mod that frees DSP memory there` | nothing frees P memory for DSP code | add the mod that claims the name the message gives |
| `the DSP code for payload A needs P words to ...` | the DSP code and tables do not fit in the freed words | shrink your DSP code |
| `holds an address the linker cannot place` (SDK) | a label used as a short or packed operand | use a form that takes the address as a whole word (`>`); branches are relative |
| `is a DSP reference to a ColdFire address` (or the reverse) | a `dsp24` relocation names a ColdFire symbol, or a ColdFire one a DSP label | name the right symbol; DSP labels are word addresses on the DSP |
| `dsp_asm is not installed` | the SDK needs octabam's DSP assembler | build octabam's `vendor/dsp56300` and set `ELEKLOADER_DSP_ASM` |

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
