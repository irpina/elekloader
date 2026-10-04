| SPDX-License-Identifier: GPL-2.0-or-later
| core: the audio render's hooks (ev_render_in, ev_render_out). Built with
| core.s by the cores whose device renders on the ColdFire: the Digitakt mk1
| (mods/core) and the Digitone mk1 (mods/core-dn1). From mod.json:
|
|   RENDER_FRAME the render handler's frame: its registers are saved at
|                -RENDER_FRAME(a6)

        .section .run, "ax"

| ---- ev_render_in, ev_render_out: the audio render (vector 191) ------------
| Entry, at 0x40077428 (was: move.l #$7fffffff,d0). The handler has saved
| d0-d7/a0-a5; a6 is its frame. d1/a0/a1 are kept around the handlers.
        .globl  core_render_in
core_render_in:
        lea     -16(%sp), %sp
        movem.l %d1/%a0-%a2, (%sp)
        lea     ev_render_in, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      movem.l (%sp), %d1/%a0-%a2
        lea     16(%sp), %sp
        move.l  #0x7fffffff, %d0        | the instruction this replaced
        rts

| Exit, at 0x400784c8 (was: movem.l -$a8(a6),d0-d7/a0-a5), the handler's
| only way out: every register but a6 is restored after the handlers.
        .globl  core_render_out
core_render_out:
        lea     ev_render_out, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      movem.l -RENDER_FRAME(%a6), %d0-%d7/%a0-%a5
        rts
