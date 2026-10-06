# The .elemod format

A `.elemod` is a JSON file. How to make one is [ADAPTING.md](ADAPTING.md).
Every mod names its **target**: the stock release it was made for, by hash.

```json
"target": {"device": "digitakt-mk1", "product": "Digitakt mk1", "os": "1.53",
           "syx_sha256": "...", "section3_sha256": "...", "section3_len": 2475584}
```

`section3_*` describe the device's main OS section, whatever its id.
elekloader refuses a mod whose target it does not know, or a set of mods
made for different releases.

## Shared fields

| field | |
|---|---|
| `elemod` | 1 or 2: the format (files from before 0.2 say `"dtmod"` and end in `.dtmod`; both still load) |
| `id`, `version` | the mod's name and version; `requires`/`conflicts` name other ids |
| `title`, `description`, `category`, `author` | for people |
| `license` | an SPDX identifier for the mod's own bytes, e.g. `GPL-2.0-or-later`; shown in the loader and by `lint` |
| `sites` | changes to the stock image (below) |
| `resources` | `regions`: run-time memory it claims, each inside one of the device's free areas; `names`: named resources such as `sysex:0x7d`, `settings:FAST AUDIO`, `drive:/cfw/slices.a` |
| `requires`, `conflicts` | lists of mod ids |
| `signature` | reserved; `null` |

A **site** is a change to the stock main OS:

```json
{"addr": "0x4000a770", "len": 6, "stock_sha256": "...", "new": "4eb900000000",
 "kind": "code", "relocs": [[2, "abs32", "sym:core_tick", 0]]}
```

- The mod ships the new bytes and a hash of the stock bytes, never the
  stock bytes themselves.
- A `code` site must be whole instructions: the end exactly, and the start
  by linear sweeps that must all land on it.
- `relocs` exist in format 2 only.

Wherever a mod's bytes repeat the firmware, it can say
`["stock", "0x40071998", 58]` in place of the bytes. The loader then copies
them from the user's own, hash-checked image, so they are never shipped.

## Format 1: a whole build

A format-1 mod is one monolithic custom build:
- `sites`;
- one `blob`, appended at the stock main OS's end:
  `{"load", "len", "sha256", "parts": [["hex", "..."], ["stock", addr, n]]}`;
- `ele3_version`, optional: the version the unit shows. The name is
  historical; it applies to every device: 4 characters on the Digitakt mk1
  and the Digitone mk1, 1 to 10 on the Octatrack.

At most one format-1 mod can be used, and never with format-2 mods.

## Format 2: linkable mods

A format-2 mod is a relocatable object:

| field | |
|---|---|
| `sections` | `.run` (RAM), `.fast` (fast SRAM, copied in at run time), `.bss` (`{"size"}`), and `.boot` (the core mod only: it runs where the bootloader unpacks it); each with an `align`, a power of two up to 4,096 (default 4) |
| `symbols` | `{"name": [".run", offset]}` or `["abs", value]` |
| `exports` | the symbols other mods may use |
| `imports`, `weak` | the names it uses from others; a weak one resolves to `core_zero` (zeros) if no mod provides it |
| `relocs` | `[section, offset, "abs32"/"pc32"/"pc16", target, addend]`; target `"sym:NAME"`, `"sec:NAME"` or `"abs"` |
| `collections` | tables this mod declares: `{"ev_tick": {"entry": 4}}` |
| `contribute` | entries for tables: `{"to", "order", "data", "relocs", "claims"}` |
| `copied` | `[{"lo", "hi", "to"}]`: a block of the image this mod copies elsewhere at run time |

### The linker

1. **Checks.** Everything in "Checks" below. Nothing is linked unless all
   of it passes.
2. **Lays out.** The core mod comes first, then the others by id, so the
   result is the same whatever order the mods were given in.
   - The core's `.boot` goes at the image end.
   - Then the RAM image: every `.run`, the tables, and the load images of
     every `.fast`.
   - Then every `.bss`.
   - The `.fast` sections go in the device's fast-SRAM area.
   - The core's `boot` copies the RAM image and zeroes `.bss`, using the
     symbols the linker defines: `__run_load`, `__run_start`,
     `__run_words`, `__bss_start`, `__bss_end`, `__bss_words`.
   - On a device whose RAM for mods is taken from the OS (the profile's
     `reserve`: the Octatrack's sample memory), a core may take only what
     the mods use. When a mod imports one of the profile's reserve
     symbols, and none exports one, the linker counts n, the units the
     mods' RAM fills (at least one), and defines each symbol as a + b·n;
     the layout then says `reserve: {units, end}`. The Octatrack's are
     `arena_base`, `__arena_pages`, `__arena_fill` and `__arena_clear`
     (core-ot 0.3). The RAM budget is still the device's `ddr`.
3. **Builds the tables.** Each table's entries are sorted by (`order`, mod
   id), followed by one zero entry. A table defines two symbols: `NAME` (its
   address) and `NAME_n` (its count). Each `.fast` section is added to the
   device's copy table (`fa_copies` on the Digitakt mk1, `core_fast` on the
   Digitakt II) automatically.
4. **Relocates** the sections, the table entries and the sites.
5. **Checks again** on the result: code sites are still whole
   instructions, and the copied-block rules hold.

### Checks

Nothing is built unless all of these pass:

- **The stock image.** Every site's stock bytes hash to what the mod
  expects, and every code site is whole instructions.
- **Bytes.** No two mods touch the same bytes. That covers sites and the
  bytes that table entries `claim`: for example, the image bytes a run-time
  fix-up rewrites in a copy.
- **Memory.** No two regions overlap, and every region lies inside the
  device's free areas. The RAM and fast-SRAM budgets hold.
- **Names.** No named resource is claimed twice, and no symbol is exported
  twice.
- **Links.** Every import resolves, and every contribution goes to a
  declared table in whole entries.
- **Mods.** Exactly one core mod; `requires` and `conflicts` hold.
- **Copied blocks.** A mod's site inside another mod's `copied` block must:
  - be code;
  - avoid every byte a fix-up claims;
  - decode as whole instructions with no PC-relative operand and no relative
    branch, because it will run from the copy.

## The hook bus (Digitakt mk1, Digitone mk1, Digitakt II)

This is a convention between mods for these devices, not a rule of the
loader. The table gives the Digitakt mk1 1.53's sites, which 1.54 has at
the same addresses; the Digitone mk1 1.43's are 0x4001900c, 0x40019072,
0x40019d9c, 0x40019de4, 0x40072a34, 0x4009d108 and 0x4009e51c, in the same
order, and 1.44 has the last three at 0x40072a54, 0x4009d128 and 0x4009e53c
(`mods/core-dn1/mod.json`, its `ports`). core-dn1 2.1 adds a Digitone-only
event, `ev_voice_on` (at 0x4009e928; 0x4009e948 in 1.44), and the tables
`core_params` (parameter slots, docs/ADAPTING.md), `core_pages` (mod pages)
and `core_projdata` (project data); 2.2 the event `ev_hold` and the table
`core_menu` (the Mod Menu). The Digitakt II 1.17's core (core-dt2 1.0) has
`ev_tick`, `ev_draw`, `ev_key`, `ev_enc` and `ev_settings`, at 0x40032ad4,
0x40032b3a, 0x40033d94, 0x40033dde and 0x400a5eac, a Digitakt II-only
`ev_personalize` (0x4009e2a2, the PERSONALIZE menu, `void f(menu)`), and no
render events (its audio renders on the DSP). It declares the `.fast` copy table itself,
`core_fast`, and copies it on the first `ev_tick` (`mods/core/fast.s`).

The core mod patches each shared site once. It calls the handlers
subscribed to that event, from a table built by the linker, in order.
Handlers use the C calling convention: arguments on the stack, d0-d1/a0-a1
free, the result in d0.

| event | site | handler |
|---|---|---|
| `ev_tick` | 0x4000a770, 30 Hz compose check | `void f(ctrl)`; set `ctrl+0x20` to recompose |
| `ev_draw` | 0x4000a7d6, after drawAll | `void f(bmp, ctrl)` |
| `ev_key` | 0x4000b770, Brain::key | `int f(brain, KeyEvent*)`; nonzero: taken |
| `ev_enc` | 0x4000b7ba, Brain::enc | `int f(brain, EncoderEvent*)`; nonzero: taken |
| `ev_settings` | 0x40058800, SETTINGS builder | `void f(menu)`; `core_additem(menu, row)` |
| `ev_render_in` | 0x40077428, render entry | `void f(void)` |
| `ev_render_out` | 0x400784c8, render exit | `void f(void)` |
| `ev_hold` | Digitone only: a track key held on its own (core-dn1's key site) | `int f(brain, event, track)`; none: the Mod Menu |
| `ev_voice_on` | Digitone only: 0x4009e928 (1.44: 0x4009e948), a voice's note-on in the render | `void f(voice, track, event)`; the pitch word is written |

The Octatrack's core (core-ot 0.2, OS 1.40C) has events of its own, with the
same conventions (docs/ADAPTING.md, "The hook bus on the Octatrack"):

| event | site | handler |
|---|---|---|
| `ev_tick` | 0x40061e94, the sys task's tick (message 5), 60 Hz | `void f(void)` |
| `ev_draw` | 0x40013cae in the compositor, through the gate at 0x400c46ea | `void f(frame)`, the 1024-byte frame |
| `ev_key` | 0x40061dc8, `key(code, pressed)` | `int f(code, pressed)`; nonzero: taken |
| `ev_enc` | 0x40061e00, `enc(encoder, delta)` | `int f(encoder, delta)`; nonzero: taken |
| `ev_midi` | 0x40005572, the MIDI thread's handler call | `int f(msg)`; nonzero: taken |
| `ev_frame` | 0x4000d94e, the frame interrupt, every 16 samples | `void f(void)` |
