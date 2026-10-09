# DigiChroma

An effects pedal for the Digitone mk1's audio inputs, after the
[Hologram Chroma Console](https://www.hologramelectronics.com/pages/chroma-console):
four modules in a chain you can reorder, each with five effects, Character
(DRIVE, SWEETEN, FUZZ, HOWL, SWELL), Movement (DOUBLER, VIBRATO, PHASER,
TREMOLO, PITCH), Diffusion (CASCADE, REELS, SPACE, COLLAGE, REVERSE) and
Texture (FILTER, SQUASH, CASSETTE, BROKEN, INTERFERENCE), with GESTURE (knob
recordings), CAPTURE (a 30-second looper and sustainer), presets and the
Chroma Console's MIDI CCs. DigiChroma is an elekloader mod for core-dn1 3.2.
It is not affiliated with Hologram Electronics and uses none of its code; the
effects are rebuilt from the Chroma Console's public manual (firmware 1.04).

DIGICHROMA is an entry in core-dn1's Mod Menu (hold a track key). While its
page is open, DigiChroma owns the audio engine, as DigiCosm does (core-dn1
3.2's `core_audio`): the synths are silent, the Digitone's own effects are
off, and what you hear is the inputs through the pedal. NO gives the audio
and the screen back. The sequencer keeps running, so PLAY, STOP and TEMPO
still work and the clock can follow the Digitone's tempo. BYPASS (trig 16)
passes the inputs through dry, with the delays' and the reverb's tails.

**Sources.** That is SETUP's SOURCE: INPUTS, the default. With core-dn1 3.3
(its insert audio) SOURCE can also be DIGITONE: the pedal then sits after
the Digitone's master stage, so the synths, the inputs as the mixer has
them and the Digitone's own chorus, delay and reverb all go through it, and
it **stays on** after NO, while you play the Digitone as usual, until
BYPASS. A project saved without DigiChroma starts with it off. With an older
core SOURCE reads INPUTS ONLY.

## The page

DigiChroma's page is drawn like the Digitone's own parameter pages, in their
fonts: the tempo in the box at the top left, the page in the title bar,
CAPTURE's state (with G while a gesture plays, B while bypassed) and the
output's meter on the left, and eight controls, one per knob, laid out as
the Chroma Console's: the top row TILT, RATE, TIME and MIX, the bottom row
the four modules' AMOUNT, each named by its module's effect. A bypassed
module's knobs are dotted. While you turn a knob the title bar shows its
value; LEFT and RIGHT, or PAGE, move between the three pages, and holding
FUNC shows page 2.

| Page | Knobs A-D | Knobs E-H |
|---|---|---|
| 1 Chroma (the primary controls) | TILT (Character's tone), RATE (Movement), TIME (Diffusion), MIX | AMOUNT of Character, Movement, Diffusion, Texture |
| 2 Secondary (the gray labels) | SENS (Character's sensitivity), DRFT (Movement's DRIFT), DRFT (Diffusion's), OUT (output level) | VOL: each module's EFFECT VOL (Diffusion's: its wet only) |
| 3 Modules | the four modules' effects: turn to pick, push for on/off | ORDR (the order, as letters: CMDT), FLTR (FILTER's style: TILT, LPF, HPF), CAPT (CAPTURE: POST or PRE the effects), LEVL (the input level: LOW, MED, HIGH, VHI) |

Pushing a knob on pages 1 and 2 sets it back to its default; on page 2 the
knobs whose middle is neutral (SENS, OUT, the VOLs) show - and +. The `C` at
the top right is how much of each audio block the whole render takes, the
Digitone's and DigiChroma's (see CPU below).

| Chroma Console | DigiChroma |
|---|---|
| The four module buttons: tap for the next effect, hold to bypass the module | T1-T4, the Digitone's track keys: tap for the module's next effect, hold to bypass it |
| TAP footswitch: tap tempo; hold to CAPTURE, release to play; tap to stop | trig 15, the same |
| BYPASS footswitch (with DUAL BYPASS the chosen modules; double tap, everything) | trig 16, the same (DUAL BYPASS in SETUP) |
| GESTURE (C + D): record knob movements; again to play them; hold to erase | trig 13: record; again to play. FUNC + trig 13 erases every gesture |
| Secondary controls (A + B) | page 2, or FUNC held |
| FX SETUP (A + D): routing, filter style, capture routing | page 3 (DUAL BYPASS in SETUP) |
| Calibration (both footswitches) | LEVL on page 3, and SENS on page 2 |
| 80 user presets (B + C, the preset browser) | 8: in SETUP a trig key 1-8 saves the pedal there; FUNC + a trig key 1-8 recalls it |
| Global settings (all four buttons) | YES opens SETUP: SOURCE (INPUTS, or DIGITONE with core-dn1 3.3), INPUT (STEREO, or MONO from input L), CLOCK, BYPASS (trails or cut), DUAL BYPASS, MIDI CC (auto channel or any), CC CLOSED |
| Expression pedal | not yet |

## Modules and effects

The chain runs in the order on page 3 (C(haracter), M(ovement),
D(iffusion), T(exture) by default), and MIX blends the chain against the
dry signal. Each module's EFFECT VOL sets its output, and OUT the pedal's,
with a soft clip before the output.

| Module | Effect | Its controls |
|---|---|---|
| Character: TILT, AMOUNT, SENS | DRIVE | a tube-like drive. AMOUNT: the drive; TILT the tone before it and after it |
| | SWEETEN | a preamp: EQ, compression and gentle saturation, all growing with AMOUNT |
| | FUZZ | a fuzz. AMOUNT: its intensity; TILT changes its tightness, bias and tone together |
| | HOWL | a fuzz into a resonant filter, opened by the playing. TILT: from smooth low tones to bright stabs; AMOUNT: drive and resonance |
| | SWELL | each note fades in. AMOUNT: the attack and decay; SENS: when it triggers |
| Movement: RATE, AMOUNT, DRIFT | DOUBLER | two short voices, as overdubs. RATE: tight to slapback; AMOUNT: how much; DRIFT: random pitch jumps |
| | VIBRATO | RATE, AMOUNT (depth); DRIFT: a random wave and a wider stereo |
| | PHASER | RATE; AMOUNT: depth, feedback and 2 to 12 stages; DRIFT: a random sweep |
| | TREMOLO | RATE; AMOUNT: depth, and from a sine to a square; DRIFT: an unsteady rate and depth |
| | PITCH | RATE: -1 to +1 octave, gliding (the middle is none); AMOUNT: the mix, all pitched at full; DRIFT: lo-fi and unsteady |
| Diffusion: TIME, AMOUNT, DRIFT | CASCADE | a dark bucket-brigade delay. TIME: 30-700 ms, and turning it bends the repeats; AMOUNT: repeats, self-oscillating at the top; DRIFT: modulation and wear |
| | REELS | a tape echo: brighter, with wow and flutter. DRIFT: worn tape, dropouts |
| | SPACE | a reverb from a small chamber (TIME left) to a cloud (right). AMOUNT: its mix; DRIFT: pitch modulation inside |
| | COLLAGE | a looping delay, 40 ms to 2.5 s: moving TIME bends and folds the loop. AMOUNT: repeats; DRIFT: random double-speed loops |
| | REVERSE | backwards windows of what just played. TIME: half speed (left) to double (right); AMOUNT: its mix; DRIFT: pitch modulation |
| Texture: AMOUNT | FILTER | the cutoff: TILT style cuts highs left of the middle and lows right of it; LPF and HPF styles are open at one end |
| | SQUASH | a heavy compressor that overdrives near the top |
| | CASSETTE | tape: saturation, a narrowing band, wow, flutter, hiss and dropouts, in turn as AMOUNT grows |
| | BROKEN | a motor in need of service: pitch drops, wobbling level and speed |
| | INTERFERENCE | static and crackle that follow the music, radio fading, bursts of a phone's buzz, then stutters, crushed bits and dropouts |

With CLOCK on DIGITONE (or TAP, after you tap trig 15) the delays' TIME
picks subdivisions of the tempo (1/32 to 1/4; COLLAGE 1/16 to two bars),
VIBRATO's, PHASER's and TREMOLO's RATE picks a cycle from two bars to 1/32,
REVERSE's windows are a quarter note long, and gestures play at the tempo
against the one they were recorded at. On FREE the knobs are continuous.

With SOURCE INPUTS Diffusion is stereo. SPACE takes each side through its
own allpasses into four of its eight lines, and the delays and REVERSE keep
a line a side, so a stereo source keeps its sides in the repeats. On a mono
source the two sides' modulation (the delays' wow, REVERSE's windows) runs
apart, for width. As an insert (DIGITONE) Diffusion is lean: SPACE has four
lines at half the rate, and the delays and REVERSE repeat the sum of both
sides (see CPU below).

## GESTURE and CAPTURE

- **GESTURE**: trig 13 starts recording. Each primary knob you then turn
  (page 1, or by MIDI) records its own loop of values, from your first
  move until trig 13 again, which plays them all, each knob looping on its
  own. A dot over a knob shows its gesture playing. Turning that knob
  later deletes its gesture; FUNC + trig 13 deletes all of them. Gestures
  are not saved.
- **CAPTURE**: hold trig 15 to record (from the press), release to play.
  A recording under a second plays as a sustained pad (two overlapping
  windows); a longer one as a loop, up to 30 seconds. A tap stops it.
  POST (page 3's CAPT) records what you hear and plays it beside the
  pedal's output; PRE records what comes in and plays it into the effects.
  Captures are not saved.

## MIDI

DigiChroma takes the Chroma Console's CCs (its manual's chart) that come on
the Digitone's auto channel (MIDI CONFIG > CHANNELS > AUTO CHANNEL), through
core-dn1's `ev_midi_cc`, while its page is open; with SETUP's CC CLOSED on,
also while it is closed, and with MIDI CC on ANY CH on a track's channel too.
The Digitone does not apply a CC DigiChroma takes; every other CC goes on to
the Digitone. MIDI CONFIG > PORT CONFIG > INPUT FROM has to let them in.

| CC | | CC | |
|---|---|---|---|
| 64 | TILT | 72 | SENSITIVITY |
| 65 | AMOUNT (Character) | 73 | EFFECT VOL (Character) |
| 66 | RATE | 74 | DRIFT (Movement) |
| 67 | AMOUNT (Movement) | 75 | EFFECT VOL (Movement) |
| 68 | TIME | 76 | DRIFT (Diffusion) |
| 69 | AMOUNT (Diffusion) | 77 | EFFECT VOL (Diffusion) |
| 70 | MIX | 78 | OUTPUT LEVEL |
| 71 | AMOUNT (Texture) | 79 | EFFECT VOL (Texture) |
| 16-19 | a module's effect: 0-21, 22-43, 44-65, 66-87, 88-109 the five, 110-127 off | 91 | bypass below 64, on from 64 |
| 92 | total bypass (0-31), dual bypass (32-63), all on (64-127) | 103-106 | a module's bypass, below 64 |
| 80 | GESTURE: record from 64, play below | 81 | GESTURE: erase |
| 82 | CAPTURE: stop (0-43), play (44-87), record (88-127) | 83 | CAPTURE: post below 64, pre from 64 |
| 84 | FILTER: LPF (0-43), TILT (44-87), HPF (88-127) | 93 | TAP |
| 94 | the input level: LOW, MED, HIGH, VERY HIGH by quarters | 95 | taken, does nothing |

Program changes (the Chroma Console's presets) are not mapped: core-dn1
passes mods the CCs only.

## How it works

The render (`dsp.c`) runs at interrupt level in core-dn1's render, on each
block of 32 frames (the inputs, or with DIGITONE what the master stage
made): the modules in their order, MIX against the dry, CAPTURE, OUTPUT
LEVEL and a soft clip. Everything is fixed
point in C: samples are 16-bit with 6 dB of headroom between the modules,
and the delay lines hold them at half scale. The UI (`ui.c`) runs in the
Digitone's UI task.

- **Memory:** the buffers (7 MB: Diffusion's 2.7-second line, SPACE's
  eight lines, Movement's and Texture's short lines, the gestures and
  CAPTURE's 30 seconds) are a region in the Digitone profile's `bulk` area
  after DigiCosm's, cleared at the first ticks after power-up. The code and
  its state take 59 KB of the 128 KB mods share; with DigiCosm, digitables
  and digihealth too, 114 KB.
- **CPU:** in digikit's emulator, with the factory pattern playing. With
  the source INPUTS the Digitone's own render shrinks to about 18% (no
  master stage, no voices' filters), and DigiChroma uses the time: the full
  SPACE takes 17% of each block, the stereo delays and REVERSE 8%, the other
  effects 3-7%; the default chain 24%, and the heaviest chain tried (FUZZ,
  PHASER, SPACE, INTERFERENCE) 27%, so the whole render stays under 45%.
  With DIGITONE DigiChroma runs on top of all of the Digitone's render,
  about 57%, and is lean: one module takes 3-8% (SPACE the most), the
  default chain 14%, the heaviest chain 17%, and the whole render stays
  under 80%. In both PHASER's wet chain runs at half the rate and slow
  modulation is worked out a block at a time. The emulator's timing tables assume memory without wait states,
  so a unit runs slower: a guard times the whole render on DMA timer 0
  every block, and if the unit stays over 93% for 0.2 s it bypasses the
  pedal at once (no trails) and says so in the title ("CPU full:
  bypassed"); BYPASS turns it back on.
- **Project data:** the pedal (the effects, which run, their order, the
  knobs, the secondary controls, the styles and SETUP) and the eight presets
  are saved with the project (tag `DCHR`, 136 bytes). A preset keeps the
  effects, which run, their order, FILTER's style, CAPTURE's route and the
  primary knobs; the secondary controls are the project's. Mods share 480
  bytes there: DigiChroma fits beside digitables' tables, or beside
  DigiCosm, but not beside both, and then the later one in the build's
  order is left out of the save.
- **With DigiCosm:** both may be in one build, and each owns the audio
  while its own page is open. DigiCosm comes first in core's table: with
  DigiChroma's source on DIGITONE, DigiCosm has the output while its page
  is open, and DigiChroma carries on when DigiCosm closes.

## Build

With the SDK and a stock OS file:

```bash
python -m elekloader.sdk.build mods/digichroma-dn1 --stock Digitone_and_Digitone_Keys_OS1.43.syx   # out/digichroma-0.1.elemod
python -m elekloader.sdk.build mods/digichroma-dn1 --stock Digitone_and_Digitone_Keys_OS1.44.syx   # out/digichroma-0.1-os1.44.elemod
```

It names no firmware address, so its 1.44 port is empty. It needs core-dn1
3.2 (`"resources": {"core": "3.2"}`) and an elekloader with the profile's
`bulk` area. The source DIGITONE needs core-dn1 3.3's insert audio:
DigiChroma weak-imports 3.3's `core_audio_caps` (`"weak"` in mod.json),
which reads 0 with 3.2, and then offers the inputs only. `gentables.py`
makes `tables.h`.

## Checked

In digikit's emulator, OS 1.43 and 1.44, and with the render's own code
compiled for a computer and fed test signals:

- **The firmware.** A build with the released core-dn1 3.2 and DigiChroma
  passes every stage of the emulator's check against stock on 1.43 and
  1.44, with every screen identical (and so did one with core-dn1 3.3).
- **INPUTS.** With plucked notes on the inputs and the factory pattern
  playing: closed, the synths; open, the plucks through the pedal and the
  synths silent (with the inputs silent too, an rms of 6 against the
  synths' 1856), the whole render 40% of a block with the default chain and
  its full SPACE; after NO the synths again, and the stock render. With
  core-dn1 3.2 SOURCE stays INPUTS.
- **DIGITONE** (core-dn1 3.3): SETUP's SOURCE turns to DIGITONE, the synths
  go through the pedal, and it stays on after NO.
- **The page and the keys.** Its three pages, a knob turn and its value in
  the title, T2's next effect (VIBRATO, by name), T3 held (Diffusion
  bypassed, its knobs dotted), page 3's order, SETUP, GESTURE (RATE turned
  while recording, then playing on its own) and CAPTURE (held 1.5 s:
  1.5 s playing), as screenshots and as the state DigiChroma keeps; on 1.43
  and 1.44.
- **Presets.** Saved as P5 from SETUP and recalled with FUNC + trig 5
  exactly (the knobs, the effects, which run, the order); an empty one
  changes nothing.
- **MIDI.** CCs sent into the emulator's MIDI input on 1.43. Before the page was
  ever opened a mapped CC went on to the Digitone. With it open, each kind
  in the chart on the auto channel (the primary and secondary knobs, the
  modules' effects and bypasses, FILTER's style, CAPTURE's route and its
  record, play and stop, GESTURE's record and stop, bypass, the input
  level, TAP) set DigiChroma and stopped at core's site, and a CC outside
  the chart went on. The runs were split: in the timed emulator, MIDI input
  stops a few seconds after a track key has been held, on stock 1.43 too.
- **The effects** (the render on a computer): every effect at AMOUNT 0, 64
  and 127 on plucked notes, within a few dB of the dry (louder where a
  delay self-oscillates, FUZZ and HOWL near the top) and with no DC;
  PITCH's and REVERSE's octaves; the delays' first repeat at the knob's time
  (30-700 ms, COLLAGE 40 ms-2.5 s), and on the tempo when synced; their
  feedback at the top bounded; SPACE's decay from 0.3 s (TIME left) to 9.4 s
  (right), the lean one's to 10.6 s; with INPUTS an input on L alone
  reaching R through SPACE and staying on L through the delays, at the lean
  versions' level within 1 dB; TREMOLO's rate, also synced; FILTER's three
  styles open where the manual says; SQUASH's curve; CAPTURE's pad and loop;
  GESTURE's loop;
  BYPASS's trails, and without them a clean cut; the CPU guard's trip
  (sustained 94% bypasses, 92% and a short burst do not).
- **CPU** on the cycle clock: above.

## Not yet

- Program changes, and an expression pedal (the Digitone Keys has an input
  for one).
- The source DIGITONE on a unit with a released core: it needs core-dn1
  3.3, which is not released yet.
- More presets, and gestures and captures saved: the project has room for
  eight presets, and the Digitone's +Drive no files for mods.
- Automatic calibration: LEVL and SENS set the input level by hand.

## Licence

GPL-2.0-or-later, as the rest of elekloader ([LICENSE](../../LICENSE)).
