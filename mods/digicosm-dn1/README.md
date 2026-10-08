# DigiCosm

An effects engine for the Digitone mk1's two audio inputs, after the
[Hologram Microcosm](https://www.hologramelectronics.com/pages/microcosm):
eleven engines with four variations each, a 60-second looper, Hold, Reverse,
a resonant filter, pitch modulation and a reverb with four rooms, all in time
with the Digitone's tempo. DigiCosm is an elekloader mod for core-dn1 3.2. It
is not affiliated with Hologram Electronics and uses none of its code; the
engines are rebuilt from the Microcosm's public manual.

DIGICOSM is an entry in core-dn1's Mod Menu (hold a track key). While its
page is open, DigiCosm owns the audio engine (core-dn1 3.2's `core_audio`):
the synths are silent, the Digitone's own effects are off, and everything
you hear is the inputs through DigiCosm. NO gives the audio and the screen
back. The sequencer keeps running, so DigiCosm follows its tempo and PLAY,
STOP and TEMPO still work.

## Controls

| Microcosm | DigiCosm |
|---|---|
| Activity, Repeats, Shape, Filter | knobs A, B, C, D |
| Mix, Time, Space, Loop Level | knobs E, F, G, H |
| Shift + a knob | FUNC + the same knob: GAIN (input, 64 is 0 dB), MDEP and MRAT (pitch modulation), RESO, FXVL (effect volume), LSPD (loop speed), VERB (room), FADE (loop fade) |
| The preset selector | trig keys 1-11 pick the engine, 13-16 the variation (A-D) |
| Hold | trig key 12 (latching, or momentary in SETUP) |
| Looper: Rec / Play / Dub, hold for undo | T1; hold T1 to undo the overdub |
| Looper: Stop, hold to erase | T2; hold T2 to erase |
| Reverse | T3 |
| Bypass (with trails) | T4 |
| 16 user presets | FUNC + trig key 1-16 recalls one; in SETUP a trig key saves the page as that preset (the engine, the variation and knobs A-H). They are saved with the project |
| Global configuration | YES opens SETUP (input mono/stereo, loop route, looper only, quantize, burst, hold mode, loop order); UP and DOWN pick a row, LEFT or RIGHT changes it |
| Tap tempo | the Digitone's own tempo (TEMPO) |

Pushing a knob sets it back to its default. Time picks a bar, 1/2, 1/4,
1/8, 1/16 or 1/32 of the Digitone's tempo, and when the sequencer plays the
engines' grid is its timeline.

## Engines

| | Engine | A | B | C | D |
|---|---|---|---|---|---|
| 1 | MOSAIC: loops at several speeds | 1x and 2x | 1x and 0.5x | all 2x | 0.5x, 1x, 2x, 4x |
| 2 | SEQ: slices shuffled into rhythms | filtered | 1x and 0.5x (a pad at full Activity) | layers with filter sweeps | layers, crushed |
| 3 | GLIDE: loops whose speed glides | 0.5x-1x | 2x-0.5x | 1x-2x | up and down at once |
| 4 | HAZE: grain clouds | stretched | random | 1x and 2x | 1x and 0.5x |
| 5 | TUNNEL: micro-loop drones | the loop breathes | an octave down, swept | resonant band-passes | the input moves the loop |
| 6 | STRUM: repeats of note onsets | the last onset | copies phasing | a cascade of onsets | a cascade and 2x grains |
| 7 | BLOCKS: rearranged blocks | with bursts | pitched | filtered, soft | pitched and crushed |
| 8 | INTERRUPT: bursts in place of the dry | rearranged | pitched | filter sweeps | crushed |
| 9 | ARP: onsets as arpeggios | 1x | thirds, fifths, octaves | a filter a step | crushed |
| 10 | PATTERN: taps of a delay | straight | syncopated | clusters | triplets |
| 11 | WARP: taps, processed | envelope filters | resonant band-passes | pitched | 2x grains |

Activity is density (loopers, grains, taps, steps), Repeats how long or
how often (a loop's life, a drone's decay, a delay's feedback), and Shape
the contour of each loop or grain: FLAT, SWEL(l), PERC, ARCH. The
Microcosm does not publish what its macros move in each variation, so these
are DigiCosm's own.

## How it works

Every engine is a scheduler that starts *heads*: readers of a 10.9-second
history of the input, interpolated and windowed, as one-shot grains or as
loops. PATTERN reads taps off a delay line of its own. After the engine come
the looper (60 s stereo, with one overdub layer for undo), pitch modulation,
the filter, Space (an eight-line feedback delay network) and Mix against the
dry input. Everything is fixed point in C (`dsp.c`), at interrupt level in
core-dn1's render; the UI (`ui.c`) runs in the Digitone's UI task.

- **Memory:** the buffers (26 MB) are a region in the Digitone profile's
  `bulk` area (`resources.regions` in `mod.json`), cleared when DigiCosm
  first opens. The code and its state take 30 KB of the 128 KB mods share.
- **CPU:** DigiCosm times its own render with DMA timer 0 and shows its share
  of a block in the corner (`C`). Over 45% it starts fewer new grains; under
  30% it allows more again, up to sixteen heads.
- **Project data:** the page (engine, variation, knobs, FUNC's knobs, SETUP)
  and the sixteen presets are saved with the project (tag `DCSM`, 132 bytes:
  a preset keeps the knobs at 6 bits). Mods share 480 bytes there;
  digitables' tables take 328 of them, and DigiCosm fits beside them. Loops
  are not saved.

## Build

With the SDK and a stock OS file:

```bash
python -m elekloader.sdk.build mods/digicosm-dn1 --stock Digitone_and_Digitone_Keys_OS1.43.syx   # out/digicosm-0.1.elemod
python -m elekloader.sdk.build mods/digicosm-dn1 --stock Digitone_and_Digitone_Keys_OS1.44.syx   # out/digicosm-0.1-os1.44.elemod
```

It names no firmware address, so its 1.44 port is empty. It needs core-dn1
3.2 (`"resources": {"core": "3.2"}`) and an elekloader with the profile's
`bulk` area. `gentables.py` makes `tables.h`.

## Checked

In digikit's emulator, OS 1.43 and 1.44, with core-dn1 3.2. Not run on a
unit yet.

- **Owning the audio.** With the factory pattern playing, its FM is silent
  while DigiCosm is open and back at once after NO, also when PLAY was
  pressed while DigiCosm was open. After DigiCosm has used its buffers, the
  FM plays as before.
- **The page.** Knob turns, FUNC's page, the engine and variation keys,
  SETUP (UP, DOWN, LEFT, RIGHT) and NO, as screenshots and as the state
  DigiCosm keeps.
- **The engines.** Every engine at every variation, with plucked notes on
  the inputs, on the emulator's cycle clock (MCF5441x tables at 250 MHz):
  each makes sound, at the octaves its variation names (MOSAIC C an octave
  up, MOSAIC D down, at and up; HAZE C and D; GLIDE's ranges; WARP C's
  pitched taps), and the whole render, the stock part included, takes
  30-55% of a block, never more than stock's 56.6%. DigiCosm's own reading
  agrees with the cycle clock (HAZE at full Activity: 39%, sixteen heads).
- **The looper.** Record, play, overdub (a fifth over the loop), undo (the
  fifth gone), reverse, stop with its fade, and erase.
- **Hold.** MOSAIC and HAZE keep sounding with the input silent while Hold
  is on, and fall silent once it is off.
- **Presets.** A page saved as preset 5 from SETUP comes back exactly with
  FUNC + trig 5 after the engine, variation and knobs have changed; an
  empty preset changes nothing. The page and its presets fit in the
  project beside digitables' tables.
- **The Digitone Keys.** With the Keys bit set in the emulator, core-dn1 3.2
  hands the inputs left first as on a Keys and keeps the Keys' own output
  buffer silent. Nothing has run on a Keys.

## Not yet

- Saving loops: they need +Drive files from a mod. The Digitakt's +Drive
  calls (which digislicer uses) are not the same code in the Digitone, so
  core-dn1 cannot offer them yet.
- The Microcosm's MIDI CC and program-change map: core-dn1 has no MIDI CC
  event yet. Tone+FX patches the CC router's entry (0x400ed94e) itself; a
  core site a few instructions in would sit beside it, but MIDI input does
  not reach the Digitone's parser in digikit's emulator yet, so it could not
  be checked.
- An expression pedal (the Digitone Keys has an input for one).
- A run on a Digitone Keys: only the code path was checked, in the
  emulator.

## Licence

GPL-2.0-or-later, as the rest of elekloader ([LICENSE](../../LICENSE)).
