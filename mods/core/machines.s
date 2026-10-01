| SPDX-License-Identifier: GPL-2.0-or-later
| core (Digitakt mk1): SRC machine slots. Mods add SRC machines past the
| stock four through the table core_machines, and the sites below make the
| firmware list, name, set, load, render and edit them (docs/ADAPTING.md,
| "SRC machines"). Found in FINDINGS "How SRC machines are wired, and a
| fifth one" and the survey after it. Digitakt mk1 only. The addresses in
| the comments are OS 1.53's; the code takes them from mod.json's defsym
| (M_* and the routines), one set per OS:
|   M_LIST_PUSH     the machine list's push       M_SET_REFUSE  the setter's refusal
|   M_STEP_ON/SKIP  after a step: on, or skipped  M_OPEN_ON/SKIP  the same, on opening
|   M_NAME_DEF      the long name past 3          M_SHORT_DEF   the short one
|   M_ICON_ON       the icon callback, on         M_PARAMS_NONE the descriptor's "none"
|   M_OWNER_SKIP    Randomize/Reload: not it      M_CC_GENERIC, M_NRPN_GENERIC
|   M_TRACK_GET     the track machine getter      M_PAGE_GET    the SRC page's getter
|   ITEM_ID         a menu item's id              BLIT          blit(dst, src, x, y, centre)
|   RENDER_MACHINE  the render's machine bytes (SRAM)

        .section .run, "ax"

| ---- core_machines: SRC machines past the stock four ---------------------
| A mod adds a machine by contributing to the table core_machines a pointer
| to its descriptor (docs/ADAPTING.md, "SRC machines"):
|   +0  id      its number in a sound (byte +0x7E), 4-127. Kits store it, so
|               it is fixed for good, and claimed as the resource machine:<id>
|   +4  name    its name in the machine menu
|   +8  short   its 4-character name
|   +12 icon    an 11 x 7 Bitmap for the menu (the stock icons' format), or 0
|   +16 params  the stock machine (0-3) whose eight parameters it takes
|   +20 render  the machine the audio render sees: a stock one (0-3) plays as
|               that machine; its own id gets an empty voice window
| Stock machines are 0 ONESHOT, 1 WERP, 2 REPITCH, 3 SLICE. The firmware
| gives any machine past 3 SLICE's SRC page. The menu lists the stock four,
| then the added ones by id. core_track_machine[t] is track t's own machine
| as the render last took it: a machine that renders as a stock one reads
| there as itself.
        .equ    M_ID,     0
        .equ    M_NAME,   4
        .equ    M_SHORT,  8
        .equ    M_ICON,   12
        .equ    M_PARAMS, 16
        .equ    M_RENDER, 20

| core_machine(id) -> its descriptor, or 0. C: changes d0, d1, a1.
        .globl  core_machine
core_machine:
        move.l  4(%sp), %d1
| cm_find: d1 = a machine -> d0 = its descriptor, or 0, with the flags of
| d0. Changes d0 and a1.
cm_find:
        lea     core_machines, %a1
1:      move.l  (%a1)+, %d0
        beq.s   9f                      | the table's end
        move.l  %a1, -(%sp)
        movea.l %d0, %a1
        cmp.l   (%a1), %d1
        movea.l (%sp)+, %a1
        bne.s   1b
        tst.l   %d0
9:      rts

| cm_row: d1 = a machine -> d0 = its row in the machine menu (0-3 as they
| are, the added ones after them by id), or -1 when the menu does not list
| it. Changes d0, a0, a1; d1 is kept.
cm_row:
        moveq   #3, %d0
        cmp.l   %d1, %d0
        bcs.s   1f
        move.l  %d1, %d0
        rts
1:      bsr.w   cm_find
        bne.s   2f
        moveq   #-1, %d0
        rts
2:      moveq   #4, %d0
        lea     core_machines, %a1
3:      tst.l   (%a1)
        beq.s   5f
        movea.l (%a1)+, %a0
        cmp.l   (%a0), %d1
        bls.s   3b                      | not below it
        addq.l  #1, %d0
        bra.s   3b
5:      rts

| The menu's list: 0x40022f6a builds a vector of the machines it offers,
| pushing 0-3 (was: moveq #4,d0 ; cmp.l d2,d0 ; bne.s <push d2>, at
| 0x40022fe6, d2 the next machine). By jsr: after 3, each added machine,
| smallest id first. Back to the push (0x40022fc0) with d2, or on (rts)
| when there are no more.
        .globl  core_mlist
core_mlist:
        moveq   #3, %d0
        cmp.l   %d2, %d0
        bcc.s   8f                      | 0-3
        moveq   #-1, %d1                | the smallest id >= d2 so far
        lea     core_machines, %a1
1:      move.l  (%a1)+, %d0
        beq.s   3f
        movea.l %d0, %a0
        move.l  (%a0), %d0
        cmp.l   %d2, %d0
        bcs.s   1b                      | below d2
        cmp.l   %d1, %d0
        bcc.s   1b                      | not below the best
        move.l  %d0, %d1
        bra.s   1b
3:      moveq   #-1, %d0
        cmp.l   %d0, %d1
        beq.s   9f                      | none: the list is done
        move.l  %d1, %d2
8:      move.l  #M_LIST_PUSH, (%sp)
9:      rts

| The machine setter 0x400225ca refuses a machine past 3 (was: moveq #3,d0 ;
| cmp.l d2,d0 ; bcs.w <refuse>, at 0x400225f0, d2 the machine). By jsr and
| a nop: an added machine is taken too.
        .globl  core_mset
core_mset:
        moveq   #3, %d0
        cmp.l   %d2, %d0
        bcc.s   8f
        move.l  %d2, %d1
        bsr.w   cm_find
        bne.s   8f
        move.l  #M_SET_REFUSE, (%sp)    | refused
8:      rts

| The menu's cursor follows the machine only while machine + 1 <= 4. The
| list widget puts its cursor on the item whose id (the machine) it is given,
| so the bound only kept out machines it does not list. After a step, at
| 0x4002a4e0 in 0x4002a4c6 (was: cmp.l d0,d1 ; bcs.s <skip> ; movea.l
| 76(a2),a0 ; clr.l -(sp) ; move.l d2,-(sp), d2 the machine, a2 the view),
| by jsr and three nops: any listed machine, added ones included.
        .globl  core_mstep
core_mstep:
        move.l  %d2, %d1
        bsr.w   cm_row
        tst.l   %d0
        bmi.s   9f                      | not listed: no move
        movea.l 76(%a2), %a0
        move.l  (%sp)+, %d1             | our return address
        clr.l   -(%sp)
        move.l  %d2, -(%sp)
        jmp     M_STEP_ON
9:      move.l  #M_STEP_SKIP, (%sp)
        rts

| ... and on opening, at 0x4002a9e8 in 0x4002a736 (was: moveq #4,d4 ;
| move.l d0,d1 ; addq.l #1,d1 ; cmp.l d1,d4 ; bcs.s <skip> ; clr.l -(sp) ;
| move.l d0,-(sp) ; move.l d2,-(sp), d0 the machine, d2 the list), by jsr
| and five nops.
        .globl  core_mopen
core_mopen:
        moveq   #4, %d4                 | as the stock code leaves it
        move.l  %d0, %d1
        bsr.w   cm_row                  | (d1 kept)
        tst.l   %d0
        bmi.s   9f                      | not listed: no move
        move.l  %d1, %d0                | the machine
        move.l  (%sp)+, %d1             | our return address
        clr.l   -(%sp)
        move.l  %d0, -(%sp)
        move.l  %d2, -(%sp)
        jmp     M_OPEN_ON
9:      move.l  #M_OPEN_SKIP, (%sp)
        rts

| The names: 0x4007910c (long) and 0x4007912c (short) return a default
| string past 3 (was: move.l #default,d0 at 0x40079124 and 0x40079144, then
| rts), by jmp, d0 the machine: an added machine's own.
        .globl  core_mname, core_mshort
core_mname:
        move.l  %d0, %d1
        bsr.w   cm_find
        beq.s   1f
        movea.l %d0, %a0
        move.l  M_NAME(%a0), %d0
        rts
1:      move.l  #M_NAME_DEF, %d0
        rts

core_mshort:
        move.l  %d0, %d1
        bsr.w   cm_find
        beq.s   1f
        movea.l %d0, %a0
        move.l  M_SHORT(%a0), %d0
        rts
1:      move.l  #M_SHORT_DEF, %d0
        rts

| The menu's icons: the item's icon callback 0x40029e9c picks one of four
| Bitmaps for 0-3 and draws none past 3. At its entry (was: lea -12(sp),sp ;
| movem.l d2-d4,(sp)), by jmp: (sp) return, 8 the item, 12 the screen, 16
| x, 20 y. An added machine with an icon gets it drawn as the stock ones
| are, blit(screen, icon, x + 2, y - 1, 0), a tail call.
        .globl  core_micon
core_micon:
        move.l  8(%sp), -(%sp)
        jsr     ITEM_ID
        addq.l  #4, %sp
        moveq   #3, %d1
        cmp.l   %d0, %d1
        bcc.s   8f                      | 0-3
        move.l  %d0, %d1
        bsr.w   cm_find
        beq.s   8f
        movea.l %d0, %a0
        move.l  M_ICON(%a0), %d0
        beq.s   8f
        move.l  %d0, 8(%sp)             | blit(screen, icon, x + 2, y - 1, 0)
        move.l  12(%sp), %d0
        move.l  %d0, 4(%sp)
        move.l  16(%sp), %d0
        addq.l  #2, %d0
        move.l  %d0, 12(%sp)
        move.l  20(%sp), %d0
        subq.l  #1, %d0
        move.l  %d0, 16(%sp)
        clr.l   20(%sp)
        jmp     BLIT
8:      lea     -12(%sp), %sp           | the replaced instructions
        movem.l %d2-%d4, (%sp)
        jmp     M_ICON_ON

| A sound parameter's descriptor for a machine: 0x40078f44(index, machine)
| has eight machine parameters (indices 0x11-0x18) for each of 0-3, and none
| past 3 (was: moveq #3,d2 ; cmp.l d0,d2 ; bcs.s <none>, at 0x40078f72, d0
| the machine, a0 the index). Without them a switch to a new machine resets
| and announces nothing, and the render never takes it. By jsr: an added
| machine takes its params machine's. Back to 0x40078f78 with d0, or to the
| "none" exit 0x40078f54. d2 is scratch there; a0 is kept.
        .globl  core_mparams
core_mparams:
        moveq   #3, %d2
        cmp.l   %d0, %d2
        bcc.s   8f                      | 0-3
        move.l  %d0, %d1
        bsr.w   cm_find
        beq.s   7f
        movea.l %d0, %a1
        move.l  M_PARAMS(%a1), %d0
8:      rts
7:      move.l  #M_PARAMS_NONE, (%sp)
        rts

| The render's machine byte: 0x4007725a(sound, t) copies the sound's
| machine (+0x7E) to 0x800018bc[t], which the voices branch on (was: lea
| 126(a0),a0 ; move.b (a0),(0,a1,d0.l), at 0x40077272, a1 = 0x800018bc,
| d0 = t <= 7). By jsr and a nop: the machine goes to core_track_machine[t],
| and the render gets an added machine's render machine instead.
        .globl  core_mrender
core_mrender:
        move.l  %d2, -(%sp)
        move.l  %d0, %d2                | t
        moveq   #0, %d1
        move.b  126(%a0), %d1           | the sound's machine
        lea     core_track_machine, %a1
        move.b  %d1, 0(%a1,%d2.l)
        moveq   #3, %d0
        cmp.l   %d1, %d0
        bcc.s   1f                      | 0-3: itself
        bsr.w   cm_find
        beq.s   1f                      | unknown: itself (an empty window)
        movea.l %d0, %a1
        move.l  M_RENDER(%a1), %d1
1:      lea     RENDER_MACHINE, %a1
        move.b  %d1, 0(%a1,%d2.l)
        move.l  (%sp)+, %d2
        rts


| ---- the firmware's other machine tests ------------------------------------
| An added machine keeps its own number in the sound; the tests below see
| it as the stock machine it stands for: the parameter-level ones as its
| params machine, the ones for a machine's features (SLICE's slice locks
| and keyboard slice pages) as its render machine.

| Loading a sound (0x4007a236, every loader) keeps its machine only if it
| is -1 to 3, else ONESHOT (was: move.b 124(a3),d0 ; move.l d0,d1 ; addq
| #1,d1 ; mvz.b d1,d1 ; cmp.l d1,d2 ; shi d1 ; move.b #1,d2 ; and.l d1,d0,
| at 0x4007a2ea, d2 = 5, then move.b d0,126(a2)). By jsr and seven nops: an
| added machine is kept too. d2 is left 1, as there; a1 is kept.
        .globl  core_mload
core_mload:
        moveq   #0, %d0
        move.b  124(%a3), %d0           | the stored machine
        move.l  %d0, %d1
        addq.l  #1, %d1
        andi.l  #0xff, %d1
        moveq   #5, %d2
        cmp.l   %d1, %d2
        bhi.s   8f                      | -1 to 3: kept
        move.l  %a1, -(%sp)
        move.l  %d0, %d1
        bsr.w   cm_find
        movea.l (%sp)+, %a1
        bne.s   7f
        moveq   #0, %d0                 | unknown: ONESHOT
        bra.s   8f
7:      move.l  %d1, %d0                | added: kept
8:      moveq   #1, %d2
        rts

| core_mplays(obj): the track machine getter 0x4002200a(obj), with an added
| machine as its render machine. The slice-lock menu (YES on the SRC page,
| 0x4002ba7e), the slice-lock maker (0x4002aee0) and the keyboard's slice
| pages (0x40028f7e, 0x400a1706) test the machine they get for SLICE; their
| jsr 0x4002200a calls this instead.
| core_mplays_page(view): the same for the SRC page's getter 0x4002b5d4,
| where the page sets up its waveform widget for the machine
| (0x4003a430, at 0x4003a43e): an added machine gets its render machine's
| state (SLICE's: the sample, the slice count, the selection). The page
| still draws no widget for it (0x4003a8f4 asks 0x4002b5d4 itself).
        .globl  core_mplays, core_mplays_page
core_mplays_page:
        move.l  4(%sp), -(%sp)
        jsr     M_PAGE_GET
        addq.l  #4, %sp
        bra.s   cm_plays
core_mplays:
        move.l  4(%sp), -(%sp)
        jsr     M_TRACK_GET
        addq.l  #4, %sp
cm_plays:
        moveq   #3, %d1
        cmp.l   %d0, %d1
        bcc.s   9f                      | 0-3
        move.l  %d0, %d1
        bsr.w   cm_find
        bne.s   1f
        move.l  %d1, %d0                | not added: as it is
        rts
1:      movea.l %d0, %a1
        move.l  M_RENDER(%a1), %d0
9:      rts

| The SAMP parameter of each machine, for the sample browser and the SRC
| key's pop-up: six lookups in the table 0x4018470c = {0x6f, 0x77, 0x7f,
| 0x87} bound machine <= 3 (else 0, "Error"). Their bound becomes 127 and
| their table this one: an added machine's entry is its params machine's,
| filled on core's first tick (core_mtick).
        .balign 4
        .globl  core_samp_tab
core_samp_tab:
        .byte   0x6f, 0x77, 0x7f, 0x87
        .skip   124

        .globl  core_mtick
core_mtick:
        tst.b   cm_ready
        bne.s   9f
        moveq   #1, %d0
        move.b  %d0, cm_ready
        lea     core_machines, %a1
1:      move.l  (%a1)+, %d0
        beq.s   9f
        movea.l %d0, %a0
        move.l  M_ID(%a0), %d0
        moveq   #127, %d1
        cmp.l   %d0, %d1
        bcs.s   1b                      | past the table
        move.l  M_PARAMS(%a0), %d1
        moveq   #3, %d0
        cmp.l   %d1, %d0
        bcs.s   1b                      | not a stock machine
        move.l  M_ID(%a0), %d0
        move.l  %a1, -(%sp)
        lea     core_samp_tab, %a1
        move.b  0(%a1,%d1.l), %d1
        move.b  %d1, 0(%a1,%d0.l)
        movea.l (%sp)+, %a1
        bra.s   1b
9:      rts

| The Randomize and Reload pages list the parameters whose owner is the
| track's machine (0x400112e8: was cmp.l 24(sp),d0 ; bne.s <skip> at
| 0x40011322, d0 the owner). By jsr: an added machine as its params
| machine.
        .globl  core_mowner
core_mowner:
        move.l  28(%sp), %d1            | the machine
        move.l  %d0, -(%sp)
        moveq   #3, %d0
        cmp.l   %d1, %d0
        bcc.s   1f
        bsr.w   cm_find
        beq.s   1f
        movea.l %d0, %a1
        move.l  M_PARAMS(%a1), %d1
1:      move.l  (%sp)+, %d0
        cmp.l   %d1, %d0
        beq.s   8f
        move.l  #M_OWNER_SKIP, (%sp)
8:      rts

| MIDI CC 16-23 (0x4007919e: was moveq #3,d2 ; cmp.l d1,d2 ; bcs.s
| <generic> at 0x400791d6, d1 the machine) and NRPN 0x80-0x87 (0x40079218:
| was moveq #3,d1 ; cmp.l d0,d1 ; bcs.s <generic> at 0x40079240, d0 the
| machine) reach the machine parameters of 0-3 only. By jsr: an added
| machine's params machine's.
        .globl  core_mcc, core_mnrpn
core_mcc:
        moveq   #3, %d2
        cmp.l   %d1, %d2
        bcc.s   8f
        move.l  %a1, -(%sp)
        move.l  %d0, -(%sp)
        bsr.w   cm_find
        beq.s   7f
        movea.l %d0, %a1
        move.l  M_PARAMS(%a1), %d1
        move.l  (%sp)+, %d0
        movea.l (%sp)+, %a1
        moveq   #3, %d2
8:      rts
7:      move.l  (%sp)+, %d0
        movea.l (%sp)+, %a1
        move.l  #M_CC_GENERIC, (%sp)
        rts

core_mnrpn:
        moveq   #3, %d1
        cmp.l   %d0, %d1
        bcc.s   8f
        move.l  %a1, -(%sp)
        move.l  %d0, %d1
        bsr.w   cm_find
        beq.s   7f
        movea.l %d0, %a1
        move.l  M_PARAMS(%a1), %d0
        movea.l (%sp)+, %a1
        moveq   #3, %d1
8:      rts
7:      movea.l (%sp)+, %a1
        move.l  %d1, %d0
        moveq   #3, %d1
        move.l  #M_NRPN_GENERIC, (%sp)
        rts

| ============================ .bss ========================================
        .section .bss
        .globl  core_track_machine
core_track_machine: .skip 8
cm_ready:   .skip 4
