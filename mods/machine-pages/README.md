# machine-pages

The SRC and LFO pages of the SRC machines mods add to the Digitakt mk1,
drawn from what each machine describes (core 3.0), for OS 1.53 and 1.54.
Without it every machine mod hooks the same firmware functions itself (the
page's layout, its knob labels, values, graphics and ranges, the LFO
page's names, the render point after playback), so no two of them can be
in one build. With it, those places have one owner, and each machine only
describes its page: SOPHIE, NEIGHBOR and DIGISLICER, built for it, combine.

On its own, and for machines that describe no page (every core 2.1
machine mod), it changes nothing the unit does.

| | |
|---|---|
| needs | core 3.0 (`resources.core`), and refuses beside digichain, which owns the same places |
| sites | 20, listed in `mod.json`: 7 on the SRC page, 4 range lookups, 5 on the LFO page, 2 SAMP compares, the machine menu's icon row and the render point 0x40077fba |
| exports | `cm_ui_v3` and, from 1.1, `cm_ui_v31`: the markers a machine's page names |
| declares | `ev_render_voices`, the render event |
| RAM | 2.4 KB code, 2 KB for up to 32 machines' pages |

## What a machine describes

A machine adds its descriptor to core's `core_machines` (core 2.1). From
core 3.0 the descriptor goes on with a tagged tail: `"UI30"` at +24 and
its page at +28. The page copies a stock machine's SRC page (`page_from`)
and changes each of the eight knobs, A-H, as it needs: its label and long
name, its names on the LFO page, a blank knob, the stock parameter whose
knob it looks like, its range and default, and its value's text. In C,
with `elekloader/sdk/include/digitakt-mk1/core3.h`:

```c
static int32_t gain_text(char *buf, int32_t v, int32_t ctx, int32_t machine);  /* writes buf, returns 1 */
static int32_t gain_gfx(int32_t v) { return v + v; }

static const struct cm_ui my_page = {
    .abi = cm_ui_v3, .page_from = 3,                         /* SLICE's page */
    .knob = {
        [1] = { .flags = CM_HIDDEN },                        /* B blank */
        [4] = { .name = "SLOT", .lname = "Source Slot",
                .flags = CM_RANGE, .min = 0, .max = 8 << 8 }, /* E */
        [5] = { .name = "GAIN", .lname = "Gain", .look = 0x86,  /* F, drawn as BR's knob */
                .fmt = gain_text, .gfx = gain_gfx },
    },
};
const struct cm_machine my_machine = { 30, "MINE", "MINE", 0, 3, 3, CM_UI_TAG, &my_page };
```

and in `mod.json`:

```json
"machines": [{"id": 30, "descriptor": "my_machine"}],
"requires": ["core", "machine-pages"],
"resources": {"core": "3.0"}
```

`digitakt-mk1/core3.inc` has the same in assembly (`CM_MACHINE`, `CM_UI`,
`CM_KNOB`), as digineighbor 0.7 and digislicer 2.3 use it. The fields are
in [docs/ADAPTING.md](../../docs/ADAPTING.md), "Machine pages".

Because the page names `cm_ui_v3`, a machine with a page links only beside
this mod: against core 2.1, or without it, the loader says which is
missing instead of building a stock-looking page.

**A knob that draws itself (1.1).** A knob with `CM_DRAW` in its flags has
`draw` in gfx's place, `int draw(void *bmp, int x, int y, int value, int
flag)`: machine-pages calls it at the knob-graphic site with the page's
Bitmap, and the stock graphic is not drawn when it returns nonzero. Such a
page names `cm_ui_v31` instead of `cm_ui_v3`, so it links only beside
machine-pages 1.1 and newer (1.0 would read `draw` as a `gfx`). 1.1 still
reads every `cm_ui_v3` page as 1.0 did; there, flag 16 means nothing.
DT-FM's ALGO diagram and OP number are drawn this way.

## Whose machine a site answers for

- **The SRC page** (layout, labels, values, graphics, UI records, the
  pop-up, knob D): the machine whose layout the page asked for last. The
  page asks for it with its own track's machine before it draws or turns
  a knob, and the layout is copied once per machine.
- **Ranges** (the setter's clamp, a turn's scaling, a list's stepper and
  the validator): the machine of the sound the parameter belongs to.
- **The LFO page** (the DEST list, its narrow rows, the DEST box's two
  lines and the destination's label): the active track's machine.

A parameter id is a knob of a page by the stock machine the page copies
(its ids are `0x6c + 8 page_from` onwards, A-H), or else by the machine's
params machine (the ids MIDI, the LFOs and Randomize name it by).

## The render event

`ev_render_voices(int32_t *blocks)` runs at 0x40077fba, after playback has
written every track's block (32 Q31 samples, `fw_track_blocks`) and before
the overdrive. A machine that makes its own sound subscribes with order
10-49; one that takes or changes sound already made, 50-89. SOPHIE renders
at 20 and NEIGHBOR copies at 60, so a NEIGHBOR track can take a SOPHIE
track's sound, as digichain arranged it.

## Beside the shop's mods

It links beside every Digitakt mod of the shop that adds no machine (Digi
EQ, Digi Matrix, Digi utilities, digihealth, digistring), on OS 1.53 and
1.54. The machine mods built for core 2.1 (SOPHIE 1.1.13, DT-FM 1.1.0,
NEIGHBOR 0.6, DIGISLICER 2.2, digichain 1.6 and the Digi Mono and Digi Poly
builds that need it) hook the same places themselves, so the loader refuses
them beside it; they still link with core 3.0 without it, as they did with
2.1. Their builds for machine-pages (NEIGHBOR 0.7, DIGISLICER 2.3, and
SOPHIE's, Digi Mono's and Digi Poly's, which are their authors' to publish)
all link together: with digihealth, 100,012 of the 131,072 bytes of RAM.
DT-FM 1.2.0, built for 1.1, links beside it with each shop mod that does,
on OS 1.53 and 1.54.

| mod | sites with core 2.1 | built for machine-pages |
|---|---|---|
| SOPHIE | 17 | 0 |
| NEIGHBOR | 9 | 1 (its pre-mix tap) |
| DIGISLICER | 23 | 19 (playback, PLAY's reads, the editor, the keyboard) |
| Digi Mono | 12, and digichain's 18 | 0 |
| Digi Poly | 10, and digichain's 18 | 10 (voice routing, level, previews) |
| machine-pages | | 20, owned once |

## Checked

On a unit: the owner's Digitakt on OS 1.54 ran a build of core 3.0 and
machine-pages with NEIGHBOR 0.7, DIGISLICER 2.3, SOPHIE, Digi Mono, Digi
Poly and digihealth, and everything worked.

In digikit's emulator (`emu.fwcheck`: cold boots through the real
bootloader, a script of key presses, the screens and the audio compared),
each port against the core 2.1 build it replaces, built from the same
sources with the same compiler:

- **machine-pages alone** (core 3.0), against stock 1.53: the nine screens
  and the audio identical.
- **NEIGHBOR 0.7** against 0.6, through the machine menu, its page, SLOT,
  GAIN (under the knob, in the pop-up, at its maximum) and TUNE turned,
  and the LFO page: every screen identical, but the LFO page's DEST list,
  which now names NEIGHBOR's knobs (Source Slot, Gain; Unused for PLAY and
  SAMP) where 0.6 showed SLICE's names. The audio identical.
- **DIGISLICER 2.3** against 2.2, with NEIGHBOR in both: its menu, page,
  GRID turned to AUTO and PLAY to PIPO (the ranges it describes), the
  editor, the keyboard's trig slice mode, the pattern playing: every
  screen identical but the menu, where DIGISLICER now has its icon (core
  2.1 drew only the first added machine's). The audio identical, apart
  from the silent end.
- **SOPHIE** against its 1.1.13, on 1.53 and 1.54: the menu, its page,
  MODEL (its four-position knob), FOLD, SWEEP, METAL, FEEDBACK and COLOR
  turned, a trig, the pattern playing, the LFO page and its DEST list: all
  20 screens identical. The audio, aligned (the build takes the key presses
  0.4 ms later, so the pattern starts 128 samples later), is identical
  sample for sample but around PLAY and STOP, the two moments a key press
  times: the hits the sequencer times in between are bit-exact.
- **Digi Mono** built for machine-pages (its author's to publish) against
  0.13b with digichain 1.6: MONO PULSE's menu and page, knob D (an engine
  knob, not the sample list), PW in %, a trig, the pattern playing, the
  LFO page and its DEST list: all 13 screens identical. Its oscillators
  run free from the machine switch, which the build takes a fraction of a
  millisecond later, so the samples differ in phase; the sound does not:
  within each note the two recordings' spectra are the same to 0.1 %
  (correlation 1.0000), with the same pitch.
- **Each machine inside a build of all three** (NEIGHBOR, DIGISLICER,
  SOPHIE, with digihealth) against the same machine alone: every page and
  LFO screen identical; only the machine menu, which lists more machines,
  differs.
- **NEIGHBOR, DIGISLICER and SOPHIE together**, with digihealth, against
  stock 1.53 and 1.54: the nine screens identical, and the audio too, apart
  from the recording's silent end being 1-2 ms longer (core 2.1 alone does
  the same). With Digi Mono and Digi Poly too (all six machine mods, 100 KB
  of RAM), the same, on 1.53 and 1.54.
- **examples/sine-machine** on 1.53 and on 1.54 (the same code, its 1.54
  port empty): every
  settled screen identical, and the audio, aligned, identical but around
  PLAY and STOP.
