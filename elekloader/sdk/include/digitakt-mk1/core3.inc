| SPDX-License-Identifier: GPL-2.0-or-later
| Core 3.0 for the Digitakt mk1, in assembly: the page a machine describes
| for the machine-pages mod (core3.h has the same in C, and the firmware
| locations, which assembly names directly: fw_kit, fw_track_blocks, ...).
| The SDK puts this folder on the include path:
|
|       .include "digitakt-mk1/core3.inc"
|
| A machine with a page: its descriptor with the tail, then the page, a
| head and eight knobs (A-H), each CM_KNOB naming only what it changes:
|
|       CM_MACHINE 4, str_long, str_short, my_icon, 3, 4, my_page
|   my_page:
|       CM_UI   3                               | SLICE's page
|       CM_KNOB                                 | A as it is
|       CM_KNOB flags=CM_HIDDEN                 | B blank
|       CM_KNOB name=str_slot, lname=str_slot_long, flags=CM_RANGE, max=0x800
|       ...                                     | eight in all

        .equ    CM_UI_TAG,      0x55493330      | "UI30"
        .equ    CM_HIDDEN,      1
        .equ    CM_RANGE,       2
        .equ    CM_DEFAULT,     4
        .equ    CM_NOT_SAMPLE,  8
        .equ    CM_KNOB_SIZE,   40              | struct cm_knob
        .equ    CM_UI_SIZE,     336             | struct cm_ui: 16 + 8 knobs

| A descriptor for core_machines, with core 3.0's tail (+24 tag, +28 page).
        .macro  CM_MACHINE id, name, sname, icon, params, render, ui
        .balign 4
        .long   \id, \name, \sname, \icon, \params, \render, CM_UI_TAG, \ui
        .endm

| A page's head: the stock machine whose SRC page it copies (0-3), the LFO
| page's group for its parameters (0: stock) and on_switch (0: none).
        .macro  CM_UI page_from, group=0, on_switch=0
        .balign 4
        .long   cm_ui_v3
        .byte   \page_from, 0
        .short  0
        .long   \group, \on_switch
        .endm

| One knob, A-H in order. Everything left out is 0: stock.
        .macro  CM_KNOB name=0, lname=0, lfo=0, lfo_long=0, look=0, flags=0, min=0, max=0, def=0, fmt=0, gfx=0
        .long   \name, \lname, \lfo, \lfo_long
        .byte   \look, \flags
        .short  0
        .long   \min, \max, \def, \fmt, \gfx
        .endm
