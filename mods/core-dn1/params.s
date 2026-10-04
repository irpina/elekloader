| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: parameter slots (Digitone mk1, OS 1.43). ColdFire V4; assemble
| with -mcpu=54455. Beside core.s; the Digitakt's core does not have them.
|
|   PARAMS      the stock parameter records, 60 bytes each, ids 0-181: page
|               group, sound slot, min, max, default (8.8), flags, MIDI CC,
|               two words, a word, name, group name, short name, formatter
|   PARAM_FREE  right after them, where ids 182-184 go: two small tables live
|               there in the stock image, and boot moves them to
|               core_ptab_save (three instructions read them, and core
|               points them there)
|   UIRECS      the UI records, 84 bytes each, built by the OS's static
|               constructors for ids 0-181; core builds its slots' own
|
| The firmware clamps every parameter id it is given to 0-181 (44 places:
| cmpi.l #182). From 2.1 core raises each clamp to 185, so ids 182-184 reach
| PARAM_FREE through the stock code: the knob, its pop-up, its value and its
| p-locks work as for any parameter. A mod adds one by contributing to the
| table core_params a pointer to its descriptor:
|   +0  id      182, 183 or 184, claimed as the resource param:<id>
|   +4  the 60-byte record, in the stock layout (docs/ADAPTING.md)
|   +64 look    the stock parameter whose knob it borrows: its UI record
|               (graphic, how a turn moves the value, the knob's scale), with
|               the mod's own formatter. 0 is PTIM (24), a plain knob that
|               steps by whole values within the record's range
| and puts the id on a page knob with a data site on the page's layout. A
| slot no mod fills gets record 0, the firmware's 'none', as the clamp did.
        .equ    SLOT0,    182
        .equ    SLOTS,    3
        .equ    PREC,     60            | a parameter record
        .equ    UREC,     84            | a UI record
        .equ    PTAB_LEN, 228           | the two tables at PARAM_FREE
        .equ    LOOK_DEF, 24            | PTIM: a plain knob, whole steps

| ============================ .boot =======================================
| core_dn_boot: the OS entry's call at 0x40000538 comes here first. It runs
| from the load image, before boot copies .run to its run address, so what
| it writes into .run it writes at the load address (run2load).
        .section .boot, "ax"
        .globl  core_dn_boot
core_dn_boot:
        move.l  %a2, -(%sp)
        | 1. The two tables at PARAM_FREE move to core_ptab_save.
        lea     core_ptab_save, %a1
        bsr.w   run2load
        lea     PARAM_FREE, %a0
        moveq   #PTAB_LEN / 4, %d0
1:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   1b
        | 2. Every slot gets record 0, then each contributed record its id's.
        lea     PARAM_FREE, %a1
        moveq   #SLOTS, %d1
2:      lea     PARAMS, %a0
        moveq   #PREC / 4, %d0
3:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   3b
        subq.l  #1, %d1
        bne.s   2b
        lea     core_params, %a1
        bsr.w   run2load
        movea.l %a1, %a2
4:      move.l  (%a2)+, %d0             | a descriptor (its run address), or 0
        beq.s   6f
        movea.l %d0, %a1
        bsr.w   run2load
        move.l  (%a1)+, %d0             | its id
        subi.l  #SLOT0, %d0
        cmpi.l  #SLOTS, %d0
        bcc.s   4b                      | not a slot: left out
        move.l  PREC(%a1), %d1          | its look, or 0
        bne.s   7f
        moveq   #LOOK_DEF, %d1
7:      move.l  %a1, -(%sp)
        move.l  %d0, -(%sp)
        lea     core_param_look, %a1
        bsr.w   run2load
        move.l  (%sp)+, %d0
        move.l  %d1, (%a1,%d0.l*4)
        movea.l (%sp)+, %a1
        moveq   #PREC, %d1
        muls.l  %d1, %d0
        lea     PARAM_FREE, %a0
        adda.l  %d0, %a0
        moveq   #PREC / 4, %d0
5:      move.l  (%a1)+, (%a0)+
        subq.l  #1, %d0
        bne.s   5b
        bra.s   4b
6:      movea.l (%sp)+, %a2
        jmp     boot                    | core.s: the copy, then the OS

| run2load: a1 = an address in .run -> a1 = that address in the load image.
| Changes d0.
run2load:
        move.l  %a1, %d0
        subi.l  #__run_start, %d0
        addi.l  #__run_load, %d0
        movea.l %d0, %a1
        rts

| ============================ .run ========================================
        .section .run, "ax"

| core_param_ui: d1 = a parameter id -> d0 = its UI record. By jsr from the
| UI record accessors 0x400899c4 and 0x400899e2, in place of their clamp and
| index (at 0x400899c8 and 0x400899e6). Keeps every register but d0 and d1,
| as the code it replaces did. A slot's record is built on first use: id 0's
| record (the stock default knob) with the slot's own formatter, which the
| static constructors take from the parameter record for stock ids. Its
| record is a copy of the stock one it borrows (the descriptor's look).
        .globl  core_param_ui
core_param_ui:
        cmpi.l  #SLOT0, %d1
        bcc.s   1f
        moveq   #UREC, %d0
        muls.l  %d1, %d0
        addi.l  #UIRECS, %d0
        rts
1:      subi.l  #SLOT0, %d1
        cmpi.l  #SLOTS, %d1
        bcs.s   2f
        move.l  #UIRECS, %d0            | past the slots: id 0's, as the clamp
        rts
2:      lea     -12(%sp), %sp
        movem.l %d2/%a0-%a1, (%sp)
        moveq   #UREC, %d0
        muls.l  %d1, %d0
        addi.l  #core_param_uirec, %d0
        movea.l %d0, %a1
        tst.l   0x1c(%a1)               | built: its formatter's manager is set
        bne.s   4f
        lea     core_param_look, %a0    | the stock record it borrows
        move.l  (%a0,%d1.l*4), %d2
        moveq   #UREC, %d0
        muls.l  %d0, %d2
        addi.l  #UIRECS, %d2
        movea.l %d2, %a0
        moveq   #UREC / 4, %d2
3:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d2
        bne.s   3b
        lea     -UREC(%a1), %a1
        moveq   #PREC, %d2
        muls.l  %d1, %d2
        lea     PARAM_FREE, %a0
        move.l  0x34(%a0,%d2.l), %d2    | the formatter
        move.l  %d2, 0x14(%a1)
4:      move.l  %a1, %d0
        movem.l (%sp), %d2/%a0-%a1
        lea     12(%sp), %sp
        rts

| The two tables from PARAM_FREE, filled at boot.
        .balign 4
        .globl  core_ptab_save
core_ptab_save:
        .skip   PTAB_LEN
| Each slot's look (a stock parameter id), filled at boot; 0 for an empty
| slot, whose UI record is then id 0's.
core_param_look:
        .skip   4 * SLOTS

| ============================ .bss ========================================
        .section .bss
        .balign 4
core_param_uirec:
        .skip   UREC * SLOTS
