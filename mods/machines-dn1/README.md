# machines (Digitone mk1)

Machines for the Digitone mk1 and Digitone Keys, OS 1.43 and 1.44: sounds
that play a machine mod's voice in place of FM, through the Digitone's own
multimode filter, mixer and effects, with the AMP page's envelope. It is
built on core-dn1 3.1 ([../core-dn1](../core-dn1)). On its own it adds
MACHINES to the Mod Menu and nothing else: machines come in mods of their
own, and [examples/dn-sine-machine](../../examples/dn-sine-machine) is one
to start from.

| | |
|---|---|
| needs | core-dn1 3.1 (`resources.core`) |
| sites | none: it uses core's `ev_voice_on`, `ev_render_voices`, `core_param_override`, `core_sound_set` and `core_menu_open` |
| table | `dn_machines`: a machine mod contributes a pointer to its `struct dnm_machine` |
| exports | `dnm_knob`, `dnm_knob_range`, `dnm_phase_inc`, `dnm_sin` (`digitone-mk1/machines.h`) |
| claims | `soundslot:0` |
| RAM | 3.8 KB code, 2.8 KB data |

## How it works

- **A sound's machine** is its slot 0, which no stock parameter uses: the
  machine's id << 8, 0 for FM. A voice loads it with the rest of the sound
  at each note.
- **MACHINES** in the Mod Menu (hold a track key) opens a submenu: FM and
  each machine in the build, as tiles. Picking one sets the held track's
  slot 0 and its SYN knobs to the machine's defaults (to FM's when it goes
  back to FM), with `core_sound_set`, so the track's voices play it from the
  next note.
- **The knobs.** While the active track's sound plays a machine, SYN1's first
  page and SYN2's first page are the machine's sixteen knobs: its labels, its
  value texts, on plain knobs that turn as the stock ones do
  (`core_param_override`, `core_param_ui_make`). The values stay the stock
  parameters', in their slots and ranges. The second pages are FM's alone,
  and show no labels or values.
- **The sound.** Each block (`ev_render_voices`) every voice playing a
  machine gets the machine's 32 samples in place of the FM voice's. The DSP
  applies the AMP envelope to FM before its output, so this applies it to
  the machine: ATK, DEC, SUS and REL from the voice's slots 66-69, started
  by `ev_voice_on` and released by `fw_gate_off`, and the note's velocity.
  A voice whose envelope has ended is silent.

The fields of `struct dnm_machine` and `struct dnm_knob` are in
[docs/ADAPTING.md](../../docs/ADAPTING.md), "Machines on the Digitone".

## Checked

In digikit's emulator, OS 1.43 and 1.44, with SINE and digitables 1.4:
MACHINES opens its submenu; SINE picked for track 1 plays a pure sine at the
note (G4, 392 Hz, no harmonics), FOLD adds odd harmonics, OCT +1 moves it an
octave up, the AMP page's release fades it; track 2 stays FM; back to FM sets
FM's defaults. Turning a knob on a machine track moves its value as on FM
(ALGO, under OCT, about four detents a step). A machine voice that peaks at
`DNM_PEAK` plays about as loud as FM at the stock defaults. Not yet on a
unit.

## Not yet

- The SYN pages still draw FM's pictures: SYN1's algorithm diagram (which
  follows ALGO, a machine's knob A), the group headings ("RATIO", "RATIO
  OFFSET"), and SYN2's envelope graphs over its first page, whose labels
  show three characters. Core-dn1 3.1 cannot change a stock page's drawing
  per track.
- A knob a machine leaves unused still turns, and changes the FM parameter
  under it (unseen, and unheard while the machine plays).
- The pop-up's long name and the LFO destination lists keep FM's names.
- The DSP still renders FM for a machine's voices, and its AMP envelope is
  repeated here.
- SYN1's knobs keep their stock ranges (ALGO 0-7, the ratios as indices, HARM
  -26..26, MIX -63..63); SYN2's are 0-127.
- A machine's render costs the main CPU per voice: in the emulator SINE
  takes about 3,000 instructions a voice a block (a block is 667 us). There
  is no voice limit yet.
