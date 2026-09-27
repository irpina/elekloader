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
| `sections` | `.run` (RAM), `.fast` (fast SRAM, copied in at run time), `.bss` (`{"size"}`), and `.boot` (the core mod only: it runs where the bootloader unpacks it) |
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
3. **Builds the tables.** Each table's entries are sorted by (`order`, mod
   id), followed by one zero entry. A table defines two symbols: `NAME` (its
   address) and `NAME_n` (its count). Each `.fast` section is added to the
   device's copy table (`fa_copies` on the Digitakt mk1) automatically.
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

## The Digitakt mk1 hook bus

This is a convention between Digitakt mk1 mods, not a rule of the loader.

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
