| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.2: ev_midi_cc, the MIDI CCs the Digitone receives (Digitone mk1).
| ColdFire V4; assemble with -mcpu=54455. Beside core.s.
|
|   ROUTER_EXIT  the CC router's exit (its registers back, rts)
|
| ---- ev_midi_cc ---------------------------------------------------------------
| The firmware's CC router (0x400ed94e; Tone+FX patches its first six bytes)
| gets each control change it receives: d2 the track (MIDI channel 1-9 is
| 0-8; the auto channel is the active track, with d5 = 1), d3 the CC number,
| d4 the value. At 0x400ed96e (0x400edbe2 in 1.44) it checks the
| track, `cmp.l d2,d0; blt.w exit` with d0 = 8. Core takes those six bytes:
| the same check, then each handler of ev_midi_cc,
|   int f(int track, int cc, int value, int flags)
| flags bit 0: it came on the auto channel. A handler that returns nonzero
| takes the CC: the router stops there and the stock does not apply it. With
| none taking it, the router goes on as stock. Not at interrupt level: the
| MIDI input's task. A mod that patches the router's entry (Tone+FX) sees a
| CC first and, if it lets it through, core sees it next.

        .section .run, "ax"
        .globl  core_midi_cc
core_midi_cc:
        cmp.l   %d2, %d0                | the router's check: a track past 8 -> out
        blt.s   9f
        lea     -20(%sp), %sp
        movem.l %d0-%d1/%a0-%a2, (%sp)
        lea     ev_midi_cc, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        moveq   #1, %d1
        and.l   %d5, %d1
        move.l  %d1, -(%sp)             | flags: the auto channel
        move.l  %d4, -(%sp)             | value
        move.l  %d3, -(%sp)             | cc
        move.l  %d2, -(%sp)             | track
        jsr     (%a0)
        lea     16(%sp), %sp
        tst.l   %d0
        beq.s   1b
        movem.l (%sp), %d0-%d1/%a0-%a2  | taken
        lea     20(%sp), %sp
9:      move.l  #ROUTER_EXIT, (%sp)     | the router's exit, in place of the return
        rts
2:      movem.l (%sp), %d0-%d1/%a0-%a2  | nobody took it: on into the router
        lea     20(%sp), %sp
        rts
