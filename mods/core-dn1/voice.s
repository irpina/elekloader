| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: the voice note-on event (Digitone mk1, OS 1.43). ColdFire V4;
| assemble with -mcpu=54455. Beside core.s, which is shared with the
| Digitakt mk1; this event exists on the Digitone only.
|
|   VOICE_PITCH  the voices' pitch words: one long per voice, the note in
|                the high word (note << 16), which the render reads again
|                every block
|
| ---- ev_voice_on: a voice starts a note ------------------------------------
| At 0x4009e928 in the audio render (vector 191), in its note-on loop (was:
| lea VOICE_PITCH,a0, followed by move.l d0,(0,a0,a1.l*4) at 0x4009e92e,
| which stores the voice's pitch word). Here a1 = the voice (0-7), d2 = the
| track, d0 = the pitch word and a3 = the note event. core_voice_on makes
| that store itself, runs the handlers and returns past it, so a handler
| sees the pitch word written and may change it.
|
| Handlers: f(int voice, int track, void *event). Interrupt level, inside the
| render: keep them short and free of firmware calls that might block. The
| voice's sound and the step's parameter locks are loaded after this point,
| in the same pass: read the voice's parameters from ev_render_out, not here.
| Every register is as the render left it when this returns, a0 included.
        .section .run, "ax"
        .globl  core_voice_on
core_voice_on:
        lea     VOICE_PITCH, %a0        | the instruction this replaced
        move.l  %d0, (0,%a0,%a1.l*4)    | and the store after it, at 0x4009e92e
        lea     -20(%sp), %sp
        movem.l %d0-%d1/%a0-%a2, (%sp)  | 0 d0, 4 d1, 8 a0, 12 a1, 16 a2
        lea     ev_voice_on, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  %a3, -(%sp)             | the note event
        move.l  %d2, -(%sp)             | the track
        move.l  20(%sp), -(%sp)         | the voice: the saved a1, 8 bytes up
        movea.l %d0, %a0
        jsr     (%a0)
        lea     12(%sp), %sp
        bra.s   1b
2:      movem.l (%sp), %d0-%d1/%a0-%a2
        lea     20(%sp), %sp
        addq.l  #4, (%sp)               | return past the store at 0x4009e92e
        rts
