| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: the Mod Menu (Digitone mk1). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s; the Digitakt's core does not have it.
|
| Hold a track key (T1-T4) on its own, about half a second: core first asks
| the handlers of ev_hold, f(brain, event, track) -> nonzero to take it (a
| mod whose own page is on screen, say), and if none does, it opens the Mod
| Menu, the entries mods contribute to the table core_menu. A descriptor:
|   +0  name    its line in the menu (about 20 characters fit)
|   +4  open    void open(void *brain, void *event, int track): picked; the
|               event is the key's that picked it, track the one held (0-3)
| In the menu: UP/DOWN or any knob moves, YES or trig key N picks, NO or
| holding a track key again closes, a page key (TRIG ... LFO) closes and
| goes on to its page; PLAY, STOP, FUNC and the track keys still work.
|
| The hold is the stock key event's flags 0x9: down (1) and held (8),
| about 0.4 s in. Another key pressed meanwhile stops it, but one pressed
| before does not (MIDI held, then a track key, selects a MIDI track), and
| neither does a knob: so a hold counts only when the track key went down
| with no other key down and no knob turned since. The stock OS does
| nothing with 0x9 on a track key held alone.
|
| core-dn1's tick, draw, key and encoder sites go to core_dn_tick ...
| core_dn_enc below, which do this and go on to core.s's core_tick ...
| core_enc: core.s stays the Digitakt's.
        .equ    KEY_FUNC,  1
        .equ    KEY_PLAY,  11
        .equ    KEY_STOP,  12
        .equ    KEY_YES,   13
        .equ    KEY_NO,    14
        .equ    KEY_UP,    15
        .equ    KEY_DOWN,  16
        .equ    KEY_TRIG,  20           | the page keys, TRIG ... LFO: 20-25
        .equ    KEY_LFO,   25
        .equ    KEY_STEP1, 26           | trig keys 1-16: 26-41
        .equ    KEY_T1,    42           | track keys T1-T4: 42-45
        .equ    ROWS,      5            | menu lines on screen
        .equ    COUNTS,    4            | encoder counts a detent

        .section .run, "ax"

| ---- keys: core_dn_key(brain, event), in place of core_key ----------------
        .globl  core_dn_key
core_dn_key:
        lea     -12(%sp), %sp
        movem.l %d2-%d3/%a2, (%sp)      | args from 16: brain, event
        movea.l 20(%sp), %a0
        move.l  12(%a0), %d2            | the key
        move.l  16(%a0), %d3            | its flags
        moveq   #64, %d0
        cmp.l   %d0, %d2
        bcc.s   1f
        bsr.w   note_key
1:      tst.b   menu_open
        beq.s   2f
        bsr.w   menu_key                | -> d0 1: the menu took it
        tst.l   %d0
        bne.w   taken
2:      move.l  %d2, %d0                | a track key?
        subi.l  #KEY_T1, %d0
        moveq   #3, %d1
        cmp.l   %d1, %d0
        bls.s   3f
        btst    #0, %d3                 | another key went down: no hold
        beq.w   pass
        clr.b   held
        bra.w   pass
3:      moveq   #1, %d1
        cmp.l   %d1, %d3
        bne.s   4f
        bsr.w   others_down             | pressed (no FUNC): alone?
        clr.b   turned
        clr.b   held
        tst.l   %d0
        bne.w   pass
        move.b  %d2, held
        bra.w   pass
4:      moveq   #9, %d1
        cmp.l   %d1, %d3
        beq.s   5f
        clr.b   held
        bra.w   pass
5:      moveq   #0, %d0                 | held: went down alone, no knob since?
        move.b  held, %d0
        cmp.l   %d2, %d0
        bne.w   pass
        tst.b   turned
        bne.w   pass
        clr.b   held
        tst.b   menu_open               | the menu open: holding closes it
        beq.s   6f
        clr.b   menu_open
        bra.w   taken
6:      move.l  %d2, %d3
        subi.l  #KEY_T1, %d3            | the track, 0-3
        lea     ev_hold, %a2            | a mod's first
7:      move.l  (%a2)+, %d0
        beq.s   8f
        move.l  %d3, -(%sp)             | track
        move.l  24(%sp), -(%sp)         | event
        move.l  24(%sp), -(%sp)         | brain
        movea.l %d0, %a0
        jsr     (%a0)
        lea     12(%sp), %sp
        tst.l   %d0
        beq.s   7b
        bra.s   taken
8:      bsr.w   menu_count              | then the menu, if there is one
        tst.l   %d0
        beq.s   pass
        moveq   #0, %d1
        move.b  menu_sel, %d1
        cmp.l   %d0, %d1
        bcs.s   9f
        clr.b   menu_sel
9:      move.b  %d3, menu_track
        clr.l   enc_acc
        moveq   #1, %d0
        move.b  %d0, menu_open
taken:  movem.l (%sp), %d2-%d3/%a2
        lea     12(%sp), %sp
        moveq   #1, %d0
        rts
pass:   movem.l (%sp), %d2-%d3/%a2
        lea     12(%sp), %sp
        jmp     core_key                | core.s: the mods, then the stock

| note_key: d2 = a key (0-63), d3 = its flags: keys_down follows it.
note_key:
        lea     keys_down, %a1
        move.l  %d2, %d0
        lsr.l   #5, %d0
        lsl.l   #2, %d0
        adda.l  %d0, %a1
        move.l  %d2, %d1
        moveq   #31, %d0
        and.l   %d0, %d1
        moveq   #1, %d0
        lsl.l   %d1, %d0
        btst    #0, %d3
        beq.s   1f
        or.l    %d0, (%a1)
        rts
1:      not.l   %d0
        and.l   %d0, (%a1)
        rts

| others_down: d2 = a track key (32-63) -> d0 nonzero if another key is down.
others_down:
        move.l  %d2, %d1
        subi.l  #32, %d1
        moveq   #1, %d0
        lsl.l   %d1, %d0
        not.l   %d0
        and.l   keys_down + 4, %d0
        or.l    keys_down, %d0
        rts

| menu_count -> d0 = the entries in core_menu.
menu_count:
        lea     core_menu, %a0
        moveq   #0, %d0
1:      tst.l   (%a0)+
        beq.s   2f
        addq.l  #1, %d0
        bra.s   1b
2:      rts

| menu_key: the menu is open; d2 = the key, d3 = its flags, 20(sp) brain,
| 24(sp) event -> d0 1 when it took the key, 0 to let it go on.
menu_key:
        moveq   #KEY_PLAY, %d0
        cmp.l   %d0, %d2
        beq.w   mk_pass
        moveq   #KEY_STOP, %d0
        cmp.l   %d0, %d2
        beq.w   mk_pass
        moveq   #KEY_FUNC, %d0
        cmp.l   %d0, %d2
        beq.w   mk_pass
        move.l  %d2, %d0                | track keys: core_dn_key sees to them
        subi.l  #KEY_T1, %d0
        moveq   #3, %d1
        cmp.l   %d1, %d0
        bls.w   mk_pass
        move.l  %d2, %d0                | a page key: closes, and on to it
        subi.l  #KEY_TRIG, %d0
        moveq   #KEY_LFO - KEY_TRIG, %d1
        cmp.l   %d1, %d0
        bhi.s   1f
        btst    #0, %d3
        beq.w   mk_pass
        clr.b   menu_open
        bra.w   mk_pass
1:      btst    #0, %d3                 | the rest: taken, and acted on down
        beq.w   mk_take
        moveq   #KEY_NO, %d0
        cmp.l   %d0, %d2
        bne.s   2f
        clr.b   menu_open
        bra.w   mk_take
2:      moveq   #KEY_UP, %d0
        cmp.l   %d0, %d2
        bne.s   3f
        moveq   #-1, %d0
        bsr.w   menu_move
        bra.w   mk_take
3:      moveq   #KEY_DOWN, %d0
        cmp.l   %d0, %d2
        bne.s   4f
        moveq   #1, %d0
        bsr.w   menu_move
        bra.w   mk_take
4:      moveq   #KEY_YES, %d0
        cmp.l   %d0, %d2
        bne.s   5f
        moveq   #0, %d0
        move.b  menu_sel, %d0
        bra.s   pick
5:      move.l  %d2, %d0                | trig key N: the Nth entry
        subi.l  #KEY_STEP1, %d0
        moveq   #15, %d1
        cmp.l   %d1, %d0
        bhi.w   mk_take
        move.l  %d0, -(%sp)
        bsr.w   menu_count
        move.l  %d0, %d1
        move.l  (%sp)+, %d0
        cmp.l   %d1, %d0
        bcc.w   mk_take
        move.b  %d0, menu_sel
pick:   clr.b   menu_open               | d0 = the entry: closed, then open()
        lea     core_menu, %a0
        movea.l (%a0,%d0.l*4), %a0
        movea.l 4(%a0), %a0
        moveq   #0, %d1
        move.b  menu_track, %d1
        move.l  %d1, -(%sp)             | track
        move.l  28(%sp), -(%sp)         | event
        move.l  28(%sp), -(%sp)         | brain
        jsr     (%a0)
        lea     12(%sp), %sp
mk_take:
        moveq   #1, %d0
        rts
mk_pass:
        moveq   #0, %d0
        rts

| menu_move: d0 = -1 or +1: the selection moves, within the entries.
menu_move:
        move.l  %d2, -(%sp)
        move.l  %d0, %d2
        bsr.w   menu_count
        moveq   #0, %d1
        move.b  menu_sel, %d1
        add.l   %d2, %d1
        bmi.s   1f                      | above the first: stays
        cmp.l   %d0, %d1
        bcc.s   1f                      | past the last: stays
        move.b  %d1, menu_sel
1:      move.l  (%sp)+, %d2
        rts

| ---- knobs: core_dn_enc(brain, event), in place of core_enc ---------------
| A knob turned spoils a hold; in the menu any knob moves the selection, a
| step every COUNTS counts.
        .globl  core_dn_enc
core_dn_enc:
        tst.b   held
        beq.s   1f
        moveq   #1, %d0
        move.b  %d0, turned
1:      tst.b   menu_open
        bne.s   2f
        jmp     core_enc
2:      movea.l 8(%sp), %a0
        move.l  16(%a0), %d0            | the turn, in counts
        add.l   %d0, enc_acc
        move.l  enc_acc, %d0
        moveq   #COUNTS, %d1
        cmp.l   %d1, %d0
        blt.s   3f
        sub.l   %d1, enc_acc
        moveq   #1, %d0
        bsr.s   menu_move
        bra.s   4f
3:      neg.l   %d1
        cmp.l   %d1, %d0
        bgt.s   4f
        sub.l   %d1, enc_acc
        moveq   #-1, %d0
        bsr.s   menu_move
4:      moveq   #1, %d0
        rts

| ---- tick and draw: core_dn_tick(ctrl), core_dn_draw(ctrl, bmp) ----------
        .globl  core_dn_tick, core_dn_draw
core_dn_tick:
        tst.b   menu_open
        beq.s   1f
        movea.l 4(%sp), %a0
        moveq   #1, %d0
        move.b  %d0, 0x20(%a0)          | recompose while the menu is open
1:      jmp     core_tick

core_dn_draw:
        move.l  8(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     core_draw               | the frame and the mods' drawing
        addq.l  #8, %sp
        tst.b   menu_open
        bne.s   1f
        rts
1:      lea     -20(%sp), %sp
        movem.l %d2-%d5/%a2, (%sp)      | args from 24: ctrl, bmp
        movea.l 28(%sp), %a2            | the Bitmap; y = 0 is the bottom row
        clr.l   -(%sp)                  | the screen cleared
        pea     63
        pea     127
        clr.l   -(%sp)
        clr.l   -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        pea     str_title
        pea     -1
        pea     57
        pea     1
        pea     FONT5
        move.l  %a2, -(%sp)
        jsr     TEXTF
        lea     24(%sp), %sp
        pea     1                       | a rule under the title
        pea     54
        pea     127
        pea     54
        clr.l   -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        moveq   #0, %d2
        move.b  menu_sel, %d2           | d2 the selection
        moveq   #0, %d3                 | d3 the first line's entry
        moveq   #ROWS - 1, %d0
        cmp.l   %d0, %d2
        bls.s   2f
        move.l  %d2, %d3
        subq.l  #ROWS - 1, %d3
2:      moveq   #0, %d4                 | d4 the line
3:      move.l  %d3, %d0
        add.l   %d4, %d0
        lea     core_menu, %a0
        move.l  (%a0,%d0.l*4), %d1
        beq.s   8f
        movea.l %d1, %a0
        moveq   #9, %d5                 | d5 the line's y: 46, 37, ...
        muls.l  %d4, %d5
        neg.l   %d5
        addi.l  #46, %d5
        move.l  (%a0), -(%sp)           | its name
        addq.l  #1, %d0
        move.l  %d0, -(%sp)             | its number: the trig key that picks it
        pea     str_line
        pea     -1
        move.l  %d5, -(%sp)
        pea     8
        pea     FONT5
        move.l  %a2, -(%sp)
        jsr     TEXTF
        lea     32(%sp), %sp
        move.l  %d3, %d0
        add.l   %d4, %d0
        cmp.l   %d2, %d0
        bne.s   7f
        pea     1                       | the selection: a box round it
        move.l  %d5, %d0
        addq.l  #6, %d0
        move.l  %d0, -(%sp)
        pea     123
        move.l  %d5, %d0
        subq.l  #2, %d0
        move.l  %d0, -(%sp)
        pea     4
        move.l  %a2, -(%sp)
        jsr     FRAMERECT
        lea     24(%sp), %sp
7:      addq.l  #1, %d4
        moveq   #ROWS, %d0
        cmp.l   %d0, %d4
        bcs.s   3b
8:      pea     str_hint
        pea     -1
        pea     1
        pea     1
        pea     FONT5
        move.l  %a2, -(%sp)
        jsr     TEXTF
        lea     24(%sp), %sp
        movem.l (%sp), %d2-%d5/%a2
        lea     20(%sp), %sp
        rts

str_title:
        .asciz  "MOD MENU"
str_line:
        .asciz  "%d  %s"
str_hint:
        .asciz  "YES OPEN   NO CLOSE"

        .balign 4
| The keys down, by key id (0-63), from every key event.
keys_down:
        .long   0, 0
enc_acc:
        .long   0
held:   .byte   0                       | the track key down alone, or 0
turned: .byte   0                       | a knob turned since it went down
menu_open:
        .byte   0
menu_sel:
        .byte   0
menu_track:
        .byte   0
        .balign 4
