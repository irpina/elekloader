| SPDX-License-Identifier: GPL-2.0-or-later
        .section .run, "ax"

| A1's native parameter object selects its own sound, never the visible track.
mp_lfo_sound:
        bsr.w   mp_rmach
        move.l  %d0, -(%sp)
        jsr     mp_ui5
        addq.l  #4, %sp
        rts

| LFO choices keep None at zero; the eighth extra uses virtual destination 53.
        .globl mp_lfo_slot_s
mp_lfo_slot_s:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l 20(%sp), %a1
        bsr.w   mp_lfo_sound
        tst.l   %d0
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        beq.s   1f
        move.l  8(%sp), %d0
        beq.s   2f
        cmpi.l  #53, %d0
        bne.s   1f
        move.l  #171, %d0
        rts
2:      moveq   #17, %d0
        rts
1:      move.l  %d2, -(%sp)
        movea.l 8(%sp), %a0
        jmp     LFO_SLOT_ON

| The native vector must reserve and visit 54 choices only for v5 sounds.
        .globl mp_lfo_reserve_s
mp_lfo_reserve_s:
        lea     -20(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l %a4, %a1
        bsr.w   mp_lfo_sound
        tst.l   %d0
        beq.s   1f
        moveq   #54, %d0
        bra.s   3f
1:      moveq   #53, %d0
3:      move.l  %d0, 16(%sp)
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        suba.l  %a3, %a3
        jmp     LFO_RESERVE_ON

        .globl mp_lfo_count_s
mp_lfo_count_s:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l %a4, %a1
        bsr.w   mp_lfo_sound
        tst.l   %d0
        beq.s   1f
        moveq   #54, %d0
        bra.s   3f
1:      moveq   #53, %d0
3:      move.l  %d0, (%sp)
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        cmp.l   %a3, %d0
        bne.s   2f
        jmp     LFO_LIST_DONE
2:      jmp     LFO_LIST_NEXT

| Only this chooser result turns the real slot zero into virtual 53.
        .globl mp_lfo_choice_s
mp_lfo_choice_s:
        move.l  4(%sp), %d0
        cmpi.l  #171, %d0
        bne.s   1f
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l 8(%a6), %a1
        bsr.w   mp_lfo_sound
        tst.l   %d0
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        beq.s   1f
        moveq   #53, %d0
        rts
1:      jmp     PARAM_SLOT_FN

| Native state already holds the raw destination. Keep it while remapping
| the processed index, using core ownership even when the sound pointer is null.
        .globl mp_lfo_target_s
mp_lfo_target_s:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        move.l  %d2, -(%sp)
        move.l  76(%sp), -(%sp)
        jsr     mp_lfo_target
        addq.l  #8, %sp
        move.l  %d0, 4(%sp)
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        cmp.l   %d1, %d7
        bcs.s   1f
        jmp     LFO_TARGET_ON
1:      jmp     LFO_TARGET_SKIP
