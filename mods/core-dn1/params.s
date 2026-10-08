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
|   STR_CTOR    std::string(dest, const char *, alloc) (from 3.1)
|   FW_KIT      -> the active kit (fw_kit) (from 3.1)
|   SOUND_LIVE  live(value, track, slot): a sound slot into the voices
|               playing the track, the stock setter's last step (from 3.1)
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
|
| From 3.1 a mod may also answer for a stock parameter, as long as it
| wants (a machine relabelling the SYN pages for its tracks, say), through
| the table core_param_override: a pointer to a descriptor
|   +0  ui      void *ui(int id): a UI record (84 bytes, in the stock
|               layout) to use for the id, or 0 for the stock one
|   +4  name    const char *name(int id, int field): the name to show
|               for field 0x30 (the short name, a knob's label), or 0
| either of which may be 0. The first mod that answers wins. The UI
| record carries the value text (its formatter), the knob's graphic and
| how a turn moves the value; the value itself, its sound slot and its
| range stay the stock parameter's. core_param_ui_make builds one from
| the stock id's (its turn), another id's graphic and the mod's formatter.
| The short name is read by one routine (0x400207b8), which core
| replaces: the label on the page. Other screens (the LFO destination
| list, the pop-up) read names on their own.
|
| From 3.1 too: a mod that changes a sound slot calls core_sound_set,
| which does what a stock edit does: the kit, then the track's voices.
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
        tst.l   core_param_override     | a stock id: a mod's override first
        bne.s   5f
        moveq   #UREC, %d0
        muls.l  %d1, %d0
        addi.l  #UIRECS, %d0
        rts
5:      lea     -16(%sp), %sp
        movem.l %d1-%d2/%a0-%a1, (%sp)  | 0 the id
        move.l  #core_param_override, %d2
6:      movea.l %d2, %a0
        move.l  (%a0), %d0              | a descriptor, or 0: none answered
        beq.s   8f
        addq.l  #4, %d2
        movea.l %d0, %a0
        move.l  (%a0), %d0              | its ui(), or 0
        beq.s   6b
        move.l  (%sp), -(%sp)
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        tst.l   %d0
        beq.s   6b
        bra.s   9f
8:      move.l  (%sp), %d1              | the stock record
        moveq   #UREC, %d0
        muls.l  %d1, %d0
        addi.l  #UIRECS, %d0
9:      movem.l (%sp), %d1-%d2/%a0-%a1
        lea     16(%sp), %sp
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

| core_param_short: the routine at 0x400207b8, std::string short_name(set,
| int id), by jmp at its entry. a0 = the string to make (the caller's), 8(sp)
| the id once the frame is up. As the stock one, with core_param_override
| asked first: the id clamped to the slots (185, as core's raised clamps),
| its record's +0x30, and std::string(dest, name, alloc). Returns dest in d0.
        .globl  core_param_short
core_param_short:
        link.w  %fp, #-4
        move.l  %d2, -(%sp)
        move.l  %a0, %d2                | the string to make
        move.l  #core_param_override, %a1
1:      move.l  (%a1)+, %d0             | a descriptor, or 0
        beq.s   3f
        movea.l %d0, %a0
        move.l  4(%a0), %d0             | its name(), or 0
        beq.s   1b
        move.l  %a1, -(%sp)
        pea     0x30.w
        move.l  12(%fp), -(%sp)         | the id
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        movea.l (%sp)+, %a1
        tst.l   %d0
        beq.s   1b
        bra.s   4f
3:      move.l  12(%fp), %d1            | the stock name
        cmpi.l  #SLOT0 + SLOTS, %d1
        bcs.s   2f
        moveq   #0, %d1
2:      moveq   #PREC, %d0
        muls.l  %d0, %d1
        lea     PARAMS, %a0
        move.l  0x30(%a0,%d1.l), %d0
4:      pea     -1(%fp)                 | the allocator
        move.l  %d0, -(%sp)
        move.l  %d2, -(%sp)
        jsr     STR_CTOR
        lea     12(%sp), %sp
        move.l  %d2, %d0
        move.l  -8(%fp), %d2
        unlk    %fp
        rts

| core_param_ui_make(void *ui, int id, int look, fmt): a UI record for an
| override (core_param_override's ui()): stock id's +4 to +0x10, which say
| how a turn moves the value (its steps, the stepper at +0x10), with the
| look's +0 (the knob's kind) and +0x18 on (the three draw delegates: the
| graphic, the value, the pop-up), and fmt at +0x14, or id's formatter for
| fmt 0. Look 0 is PTIM (a plain knob), -1 id 0 (an unused knob's).
        .globl  core_param_ui_make
core_param_ui_make:
        move.l  8(%sp), %d0             | id: the stock ids only
        cmpi.l  #SLOT0, %d0
        bcs.s   1f
        moveq   #0, %d0
1:      mulu.w  #UREC, %d0
        lea     UIRECS, %a0
        adda.l  %d0, %a0                | id's record
        move.l  12(%sp), %d1            | the look
        bmi.s   2f
        bne.s   3f
        moveq   #LOOK_DEF, %d1
        bra.s   3f
2:      moveq   #0, %d1
3:      cmpi.l  #SLOT0, %d1
        bcs.s   4f
        moveq   #0, %d1
4:      mulu.w  #UREC, %d1
        addi.l  #UIRECS, %d1
        move.l  %a0, -(%sp)
        movea.l %d1, %a0
        movea.l 8(%sp), %a1             | ui
        moveq   #UREC / 4, %d0
5:      move.l  (%a0)+, (%a1)+          | the look's record
        subq.l  #1, %d0
        bne.s   5b
        lea     -UREC(%a1), %a1
        movea.l (%sp)+, %a0
        move.l  4(%a0), 4(%a1)          | id's turn
        move.l  8(%a0), 8(%a1)
        move.l  12(%a0), 12(%a1)
        move.l  16(%a0), 16(%a1)
        move.l  20(%a0), %d0            | id's formatter
        move.l  16(%sp), %d1            | fmt, or 0
        beq.s   6f
        move.l  %d1, %d0
6:      move.l  %d0, 20(%a1)
        rts

| core_sound_set(int track, int slot, int value): slot (0-78) of synth track
| track's (0-3) sound in the active kit, as a stock edit leaves it (the
| setter 0x40020fc0): the kit's word, then SOUND_LIVE (0x4009c972), which
| writes the value into the voices playing the track. A voice keeps the
| sound it loaded last (it points at it from 0x80003f5c + 4 v) and loads it
| again only for another sound: a write to the kit alone is not heard on a
| voice that played the track before.
        .globl  core_sound_set
core_sound_set:
        move.l  4(%sp), %d0             | the track
        moveq   #4, %d1
        cmp.l   %d1, %d0
        bcc.s   9f
        moveq   #79, %d1
        cmp.l   8(%sp), %d1             | the slot
        bls.s   9f
        move.l  FW_KIT, %d1             | -> the active kit
        beq.s   9f
        movea.l %d1, %a0
        mulu.w  #326, %d0
        adda.l  %d0, %a0
        move.l  8(%sp), %d0
        add.l   %d0, %d0
        move.l  12(%sp), %d1
        move.w  %d1, 0x2c(%a0,%d0.l)
        move.l  8(%sp), -(%sp)          | SOUND_LIVE(value, track, slot)
        move.l  8(%sp), -(%sp)
        move.l  20(%sp), -(%sp)
        jsr     SOUND_LIVE
        lea     12(%sp), %sp
9:      rts

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
