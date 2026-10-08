| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.0 to 3.2 for the Digitone mk1, in assembly: the layouts that go
| with the firmware locations core exports (core3.h has the same in C).
| Assembly names the locations directly: fw_voice_pitch, fw_kit, fw_fillrect,
| ... A mod that uses them needs core-dn1 3.0: "resources": {"core": "3.0"};
| one that uses a 3.1 name (fw_voices, core_sound_set, ...) needs 3.1, and a
| 3.2 one (fw_tempo, core_audio) 3.2.
| The SDK puts this folder on the include path:
|
|       .include "digitone-mk1/core3.inc"

        .equ    FW_VOICE_PARAMS_SKIP, 18        | fw_voice_params + 18 + 158 v + 2 k: slot k of voice v
        .equ    FW_VOICE_STRIDE,  158
        .equ    FW_LFO_STRIDE,    0x50          | fw_lfo_state + 0x50 v: LFO1 of voice v; LFO2 0x28 on
        .equ    FW_LFO2,          0x28
        .equ    FW_LFO_DEST,      0x40          | an LFO's destination slot
        .equ    FW_LFO_MOD,       0x44          | its modulation, 8.8, signed
        .equ    FW_SOUND_SLOTS,   0x2c          | (fw_kit) + 0x2c + 326 t + 2 k: track t's sound slot k
        .equ    FW_SOUND_STRIDE,  326
        .equ    CORE_MENU_ICON,   0x49434F4E    | "ICON": a core_menu entry's +8, then +12 -> its icon
| 3.1
        .equ    FW_VOICE_BLOCK,   128           | fw_voices + 128 v: voice v's 32 samples, Q1.31
        .equ    FW_PARAM_REC,     60            | fw_params + 60 id: a parameter record
        .equ    FW_UI_REC,        84            | fw_uirecs + 84 id: its UI record
        .equ    CORE_LOOK_NONE,   -1            | core_param_ui_make's look: id 0's ('none')
| 3.2: a core_audio record (core3.h, struct core_audio_owner)
        .equ    CORE_AUDIO_ON,     0             | nonzero: this mod has the output
        .equ    CORE_AUDIO_RENDER, 4             | render(out, in), each block
        .equ    CORE_AUDIO_FLAGS,  8
        .equ    CORE_AUDIO_MUTE_VOICES, 1        | skip the voices' filters too
