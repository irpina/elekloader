| SPDX-License-Identifier: GPL-2.0-or-later
| core for the Octatrack, OS 1.40C: the draw site's gate (core 0.2).
| ColdFire V4 (MCF5445x); assemble with -mcpu=54455.
|
| The OS composes the screen twice before the boot site (from 0x4006331a and
| 0x400633b0, inside the OS entry's call at 0x400004ba), so before .boot has
| copied core's .run into the reserve. The compositor's site therefore calls
| this, which is in the image from power-on: mod.json places it ("fixed") in
| the last 24 bytes of the 338-byte zero run at 0x400c45b0-0x400c4702 that
| octabam measured as unused (its SPECTRUM pins code at the run's start).
| .boot sets core_up once .run is in place; until then the gate only does
| what the site replaced. The image is loaded from flash at every boot, so
| core_up starts at 0 each time, whatever the reserve still holds.

        .text
        .globl  core_draw_gate, core_up
core_draw_gate:
        tst.b   core_up
        beq.s   1f
        jmp     core_draw
1:      movea.l FRAME_PTR, %a5          | the instruction the site replaced
        rts
core_up:
        .byte   0
        .balign 2
