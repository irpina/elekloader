| SPDX-License-Identifier: GPL-2.0-or-later
| Native descriptor extension; the map constructor still visits only the
| original 164 records. Its machine-specific map has only eight entries.
        .section .run, "ax"
        .globl mp_descriptor_table
        .set mp_descriptor_table, DESC_TAB

        .globl mp_params_ctor_s
mp_params_ctor_s:
        jsr     mp_params_init
        lea     -44(%sp), %sp
        movem.l %d2-%d7/%a2-%a6, (%sp)
        jmp     PARAM_CTOR_ON

        .globl mp_slot_id_s
mp_slot_id_s:
        move.l  8(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     mp_slot_id
        addq.l  #8, %sp
        tst.l   %d0
        bmi.s   1f
        rts
1:      move.l  %d2, -(%sp)
        moveq   #52, %d1
        movea.l 8(%sp), %a0
        jmp     SLOT_ID_ON

        .globl mp_sound_init_s
mp_sound_init_s:
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        bsr.s   mp_stock_sound_init
        lea     12(%sp), %sp
        move.l  %d0, -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     mp_sound_defaults
        addq.l  #4, %sp
        move.l  (%sp)+, %d0
        rts

mp_stock_sound_init:
        lea     -36(%sp), %sp
        movem.l %d2-%d3/%a2-%a5, (%sp)
        jmp     SOUND_INIT_ON

| The machine setter resets the eight stock SRC values, then our declared
| defaults. Replay its argument cleanup; sound loading never comes here.
        .globl mp_machine_reset_s
mp_machine_reset_s:
        move.l  16(%sp), -(%sp)
        move.l  16(%sp), -(%sp)
        move.l  16(%sp), -(%sp)
        move.l  16(%sp), -(%sp)
        jsr     MACHINE_RESET_FN
        lea     16(%sp), %sp
        tst.b   %d0
        beq.s   1f
        move.l  %d0, -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     mp_machine_defaults
        addq.l  #4, %sp
        move.l  (%sp)+, %d0
1:      movea.l (%sp)+, %a0
        lea     16(%sp), %sp
        jmp     (%a0)

| Randomize/Reload enumerate extra descriptors only for a machine
| that uses them. Their native caller keeps its machine at 32(SP).
        .globl mp_randomize_owner_s
mp_randomize_owner_s:
        move.l  4(%sp), %d0
        cmpi.l  #164, %d0
        bcs.s   1f
        cmpi.l  #171, %d0
        bcc.s   1f
        move.l  32(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     mp_randomize_owner
        addq.l  #8, %sp
        rts
1:      jmp     OWNER_FN
