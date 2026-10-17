# core-ar2

The boot copier and the hook bus for the Analog Rytm MKII, OS 1.73 and 1.74. A proof
of concept: no new code. It builds the Digitakt mk1's `core.s`, `settings.s`
and `render.s` with the Rytm's addresses, which `mod.json` gives (`defsym`,
`sites`). On its own it changes nothing the unit does.

The Rytm runs on the Digitakt mk1's platform (a ColdFire MCF5441x), and its OS
entry, bootstrap loader and UI loop are the Digitakt's, so each site below is
the counterpart of one the Digitakt mk1 core hooks, found by matching the two
images and checked by the code around it
(`elekloader/devices/analog_rytm_mk2.py` has the platform evidence).

| event | Rytm 1.73 | Rytm 1.74 | Digitakt 1.54 | note |
|---|---|---|---|---|
| boot | 0x400008c0 | 0x400008c0 | 0x40000538 | the OS entry's third call, VBR := 0x40000000 |
| `ev_tick` | 0x400a2bee | 0x400a2c5a | 0x4000a770 | about 20 Hz (the Digitakt's 30) |
| `ev_draw` | 0x400a2c56 | 0x400a2cc2 | 0x4000a7d6 | drawAll(ctrl, bmp), 128 x 64 |
| `ev_key` | 0x400a47cc | 0x400a4838 | 0x4000b770 | |
| `ev_enc` | 0x400a4816 | 0x400a4882 | 0x4000b7ba | |
| `ev_settings` | 0x400db87e | 0x400db8ea | 0x40058800 | the SETTINGS menu's builder, 0x400db174 (1.73); rejoins 6 bytes on |
| `ev_render_in` | 0x4011fb02 | 0x4011fb6e | 0x40077428 | the audio interrupt (vector 191), 32 frames a block |
| `ev_render_out` | 0x40121656 | 0x401216c2 | 0x400784c8 | its only exit; the frame is 0xb4 (the Digitakt's 0xa8) |

1.74's main OS is 1.73's with code added for Outbox 8's main-output
routing, so its sites and routines are 1.73's moved (+0x6c, `FN_MGR`
+0x1cc), each found again by its own bytes; `mod.json`'s `ports` gives
them. A core built for one release is refused with the other's stock file.

The routines `core_additem` calls are the Digitakt's, the same code with the
addresses in it masked: `OP_NEW` 0x400829d4, `ITEM_CTOR` 0x40072f50,
`MENU_ADD` 0x40072786 and `FN_MGR` 0x40193f4e (the manager for the same
function-pointer type, by its typeinfo's name).

What differs from the Digitakt mk1 at these sites:

- **The tick.** The UI routine passes the view controller from a pointer at
  +0x20 of its object and skips the frame when it is null; the Digitakt passes
  the controller embedded at +0x40. `core_tick` sees the same argument either
  way, and its target (the dirty flag at +0x20) is the Digitakt's byte for byte.
- **The render.** The Rytm's drum voices are analog. Its audio interrupt is
  the digital path: the sample voices, the delay and the reverb. In order:
  `ev_render_in`; the analog voice controls; the PRE and POST effect returns
  mixed from the previous block's delay output (0x80007c44) and reverb buffer
  (0x80007b44); the voices received from the ADC; then 0x4010e650 builds the
  sends and runs the delay (0x4010d9b8) and the reverb (0x4010d3c8); then
  `ev_render_out`. Two other handlers (0x4013cc08, 0x4013e9b8) can take vector
  191, as on the Digitakt, whose core hooks only the main one too.
- **No machines.** The Digitakt's SRC machine slots (`machines.s`) and its
  firmware exports (`fw.s`) are not ported.

## Checked so far

On a unit (OS 1.73). With test images built by rytm-mods-src (its `elemod`
branch):

- **The boot site**, and the DDR area the linker uses: mod 0016 filled
  0x47BE0000-0x47C00000 from 0x400008c0 at boot, and a readout showed no word
  of it changed after a long, hard session and a power cycle.
- **Both render sites**: mod 0017 armed a flag at `ev_render_in` and cleared
  the effect returns from `ev_render_out` on alternate 0.7 s stretches. The
  delay and the reverb pulsed, each on its own setting, with the reverb return
  PRE or POST.

- **This core**, with [hello-marker-ar2](../../examples/hello-marker-ar2), built
  and patched by elekloader (11 Oct 2026): the unit booted the build, reported
  its version (HM01), and drew the 3x3 square on every screen. So the boot
  copier, the linked image in DDR and `ev_draw` work.

- **Every event**, with [hooks-check-ar2](../../examples/hooks-check-ar2)
  (11 Oct 2026, build HC01): `ev_tick` blinked its square and requested
  redraws, `ev_render_in` advanced its bar steadily and never disagreed with
  `ev_render_out`, `ev_key` and `ev_enc` counted every key and encoder event
  while the unit acted on each as stock does, and `ev_settings` listed the
  HOOK TEST row through `core_additem`, which counted each selection while
  the other rows worked as stock. The same through a short session with a
  pattern playing into the delay and reverb.

Statically, against the stock image (python, no toolchain): every site's
stock bytes, and that each covers whole instructions.

## Building

```bash
# needs m68k-linux-gnu binutils and gcc (or set ELEKLOADER_CROSS to another prefix)
python -m elekloader.sdk.build mods/core-ar2 --stock Analog-Rytm_MKII_OS1.73.syx
python -m elekloader.sdk.build examples/hello-marker-ar2 --stock Analog-Rytm_MKII_OS1.73.syx
python -m elekloader.lint examples/hello-marker-ar2/out/hello-marker-1.0.elemod \
    --stock Analog-Rytm_MKII_OS1.73.syx --with mods/core-ar2/out/core-0.1.elemod
python -m elekloader.patch --stock Analog-Rytm_MKII_OS1.73.syx \
    --mod mods/core-ar2/out/core-0.1.elemod --mod examples/hello-marker-ar2/out/hello-marker-1.0.elemod \
    --out rytm-hello.syx --version HM01
```
