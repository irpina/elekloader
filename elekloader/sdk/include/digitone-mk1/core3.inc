| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.0 for the Digitone mk1, in assembly: the layouts that go with
| the firmware locations core exports (core3.h has the same in C). Assembly
| names the locations directly: fw_voice_pitch, fw_kit, fw_fillrect, ...
| A mod that uses them needs core-dn1 3.0: "resources": {"core": "3.0"}.
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
