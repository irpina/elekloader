| SPDX-License-Identifier: GPL-2.0-or-later
        .section .run, "ax"

| Native entries replay their complete stolen prologues, avoiding the entry hooks.
        .globl mp_native_save, mp_native_load, mp_native_upgrade
mp_native_save:
        lea     -20(%sp), %sp
        movem.l %d2-%d3/%a2-%a4, (%sp)
        jmp     SOUND_SAVE_ON
mp_native_load:
        lea     -16(%sp), %sp
        movem.l %d2/%a2-%a4, (%sp)
        jmp     SOUND_LOAD_ON
mp_native_upgrade:
        lea     -48(%sp), %sp
        movem.l %d2-%d5/%a2-%a5, (%sp)
        jmp     SOUND_UPGRADE_ON

| Saved LFO destinations, before their native permutation lookup. A3 is
| the source sound; A1 is the stock table.
        .macro lfo_save name, onward
        .globl \name
\name:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        moveq   #0, %d0
        move.b  126(%a3), %d0
        move.l  %d0, -(%sp)
        jsr     mp_lfo_save
        addq.l  #4, %sp
        tst.l   %d0
        bmi.s   1f
        move.l  %d0, (%sp)
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        jmp     \onward
1:      movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        move.l  0(%a1,%d0.l*4), %d0
        lsl.l   #8, %d0
        jmp     \onward
        .endm

        lfo_save mp_lfo_save1_s, LFO_SAVE1_ON
        lfo_save mp_lfo_save2_s, LFO_SAVE2_ON

| Pattern locks use the same fixed slots; the stock permutation ends at
| 45. Keep its mapping for MIDI tracks and all ordinary parameters.
        .globl mp_lock_load_s
mp_lock_load_s:
        move.l  4(%sp), %d1
        cmpi.l  #8, %d1
        bcc.s   1f
        move.l  8(%sp), %d0
        cmpi.l  #46, %d0
        bcs.s   1f
        cmpi.l  #52, %d0
        bls.s   2f
1:      move.l  %d2, -(%sp)
        moveq   #16, %d2
        move.l  8(%sp), %d1
        jmp     LOCK_LOAD_ON
2:      rts

        .globl mp_lock_save_s
mp_lock_save_s:
        move.l  %d0, -(%sp)
        cmpi.l  #8, %d3
        bcc.s   1f
        cmpi.l  #184, %d6
        bcs.s   1f
        cmpi.l  #208, %d6
        bhi.s   1f
        move.l  %d6, %d0
        lsr.l   #2, %d0
        move.b  %d0, (%a3)
        bra.s   2f
1:      move.b  3(%a5,%d6.l), (%a3)
2:      move.b  %d3, 1(%a3)
        move.l  (%sp)+, %d0
        rts
