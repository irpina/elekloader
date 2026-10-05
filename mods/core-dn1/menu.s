| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: the Mod Menu (Digitone mk1). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s; the Digitakt's core does not have it.
|
| Hold a track key (T1-T4) on its own, about half a second: core first asks
| the handlers of ev_hold, f(brain, event, track) -> nonzero to take it (a
| mod whose own page is on screen, say), and if none does, it opens the Mod
| Menu, the entries mods contribute to the table core_menu. A descriptor:
|   +0  name    its label in the menu (14 characters fit)
|   +4  open    void open(void *brain, void *event, int track): picked; the
|               event is the key's that picked it, track the one held (0-3)
|   +8  tag     from 2.3, optional: 0x49434F4E ("ICON") when an icon follows
|   +12 icon    16 rows of 16 pixels, 16 bits each, the top row first and
|               bit 15 the left; without the tag (a 2.2 descriptor) or with
|               0 here, the menu draws its own (a chip)
| The menu is a grid of tiles, two across and two down, each the entry's
| icon over its label and the trig key that picks it in the corner, with a
| scroll bar on the right; the selected tile is drawn inverted.
| In the menu: the arrows or any knob move, YES or trig key N picks, NO or
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
        .equ    KEY_LEFT,  17
        .equ    KEY_RIGHT, 18
        .equ    KEY_TRIG,  20           | the page keys, TRIG ... LFO: 20-25
        .equ    KEY_LFO,   25
        .equ    KEY_STEP1, 26           | trig keys 1-16: 26-41
        .equ    KEY_T1,    42           | track keys T1-T4: 42-45
        .equ    COUNTS,    4            | encoder counts a detent
        .equ    ICON_TAG,  0x49434F4E   | "ICON": descriptor +8, an icon at +12
| The grid, in the Bitmap's coordinates (y = 0 the bottom row): tiles 59 x
| 30 with their left edge at x 1 and 62 and their top at y 62 and 30, two
| pixels apart; the scroll bar at x 123-126, y 1-62.
        .equ    TILE_W,    59
        .equ    TILE_H,    30
        .equ    RIGHT,     TILE_W - 1   | from a tile's left edge and top
        .equ    IN_RIGHT,  TILE_W - 2
        .equ    BOTTOM,    1 - TILE_H
        .equ    IN_BOTTOM, 2 - TILE_H
        .equ    COL2_X,    62
        .equ    ROW2_Y,    30
        .equ    LABEL_MAX, 14           | characters: 14 x 4 - 1 = 55 of 57 pixels

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
2:      moveq   #KEY_UP, %d0            | UP: the tile above
        cmp.l   %d0, %d2
        bne.s   3f
        moveq   #-2, %d0
        bsr.w   menu_move
        bra.w   mk_take
3:      moveq   #KEY_DOWN, %d0
        cmp.l   %d0, %d2
        bne.s   31f
        bsr.w   menu_down
        bra.w   mk_take
31:     moveq   #KEY_LEFT, %d0          | LEFT and RIGHT: the one before, after
        cmp.l   %d0, %d2
        bne.s   32f
        moveq   #-1, %d0
        bsr.w   menu_move
        bra.w   mk_take
32:     moveq   #KEY_RIGHT, %d0
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

| menu_down: the tile below; from the row above the last, when there is
| none below, the last tile.
menu_down:
        move.l  %d2, -(%sp)
        bsr.w   menu_count              | d0 = the entries
        moveq   #0, %d1
        move.b  menu_sel, %d1
        move.l  %d1, %d2
        addq.l  #2, %d2
        cmp.l   %d0, %d2
        bcs.s   1f                      | the one below
        move.l  %d0, %d2
        subq.l  #1, %d2                 | else the last, if on a lower row
        lsr.l   #1, %d1
        move.l  %d2, %d0
        lsr.l   #1, %d0
        cmp.l   %d1, %d0
        bls.s   2f
1:      move.b  %d2, menu_sel
2:      move.l  (%sp)+, %d2
        rts

| menu_move: d0 = -2 ... +2: the selection moves, within the entries.
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
1:      lea     -40(%sp), %sp
        movem.l %d2-%d7/%a2-%a5, (%sp)  | args from 44: ctrl, bmp
        movea.l 48(%sp), %a2            | the Bitmap; y = 0 is the bottom row
        clr.l   -(%sp)                  | the screen cleared
        pea     63
        pea     127
        clr.l   -(%sp)
        clr.l   -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        bsr.w   menu_count
        move.l  %d0, %d6                | d6 the entries
        moveq   #0, %d2
        move.b  menu_sel, %d2           | d2 the selection
        move.l  %d6, %d7                | d7 the rows, at least the two shown
        addq.l  #1, %d7
        lsr.l   #1, %d7
        moveq   #2, %d0
        cmp.l   %d0, %d7
        bcc.s   2f
        move.l  %d0, %d7
2:      moveq   #0, %d3                 | d3 the top row, moved only as far
        move.b  menu_top, %d3           | as keeps the selection's on screen
        move.l  %d2, %d0
        lsr.l   #1, %d0                 | the selection's row
        cmp.l   %d3, %d0
        bcc.s   3f
        move.l  %d0, %d3
3:      move.l  %d3, %d1
        addq.l  #1, %d1
        cmp.l   %d1, %d0
        bls.s   4f
        move.l  %d0, %d3
        subq.l  #1, %d3
4:      move.l  %d7, %d0
        subq.l  #2, %d0                 | and no further than the last two rows
        cmp.l   %d0, %d3
        bls.s   5f
        move.l  %d0, %d3
5:      move.b  %d3, menu_top
        pea     1                       | the scroll bar, rounded
        pea     62
        pea     126
        pea     1
        pea     123
        move.l  %a2, -(%sp)
        jsr     FRAMERECT
        lea     24(%sp), %sp
        movea.w #123, %a4
        movea.w #62, %a5
        moveq   #126, %d0
        moveq   #1, %d1
        bsr.w   corners
        moveq   #60, %d0                | its thumb: rows top and top + 1 of
        move.l  %d3, %d4                | d7, in the 60 pixels inside
        muls.l  %d0, %d4
        divu.l  %d7, %d4                | d4 its first pixel from the top
        move.l  %d3, %d5
        addq.l  #2, %d5
        muls.l  %d0, %d5
        divu.l  %d7, %d5
        subq.l  #1, %d5                 | d5 its last
        pea     1
        moveq   #61, %d0
        sub.l   %d4, %d0
        move.l  %d0, -(%sp)
        pea     125
        moveq   #61, %d0
        sub.l   %d5, %d0
        move.l  %d0, -(%sp)
        pea     124
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        moveq   #0, %d4                 | d4 the tile on screen, 0-3
6:      move.l  %d3, %d5
        add.l   %d5, %d5
        add.l   %d4, %d5                | d5 its entry
        moveq   #1, %d0
        btst    #0, %d4
        beq.s   7f
        moveq   #COL2_X, %d0
7:      movea.l %d0, %a4                | a4 its left edge
        moveq   #62, %d0
        btst    #1, %d4
        beq.s   8f
        moveq   #ROW2_Y, %d0
8:      movea.l %d0, %a5                | a5 its top
        cmp.l   %d6, %d5
        bcs.s   9f
        bsr.w   draw_slot               | past the last entry: an empty slot
        bra.s   10f
9:      lea     core_menu, %a0
        movea.l (%a0,%d5.l*4), %a3      | a3 its descriptor
        bsr.w   draw_tile
        cmp.l   %d2, %d5
        bne.s   10f
        pea     -1                      | the selection: inverted inside its
        pea     -1(%a5)                 | frame (FILLRECT's colour -1 is XOR)
        pea     IN_RIGHT(%a4)
        pea     IN_BOTTOM(%a5)
        pea     1(%a4)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
10:     addq.l  #1, %d4
        moveq   #4, %d0
        cmp.l   %d0, %d4
        bcs.w   6b
        movem.l (%sp), %d2-%d7/%a2-%a5
        lea     40(%sp), %sp
        rts

| draw_tile: a2 the Bitmap, a3 a descriptor, a4 the tile's left edge, a5
| its top, d5 its entry: the frame, rounded, the icon, the label under it
| and, in the corner, the trig key that picks it.
draw_tile:
        pea     1
        move.l  %a5, -(%sp)
        pea     RIGHT(%a4)
        pea     BOTTOM(%a5)
        move.l  %a4, -(%sp)
        move.l  %a2, -(%sp)
        jsr     FRAMERECT
        lea     24(%sp), %sp
        lea     RIGHT(%a4), %a0
        move.l  %a0, %d0
        lea     BOTTOM(%a5), %a0
        move.l  %a0, %d1
        bsr.w   corners
        lea     chip_icon, %a0          | the icon: the descriptor's, if it
        move.l  8(%a3), %d0             | has one
        cmpi.l  #ICON_TAG, %d0
        bne.s   1f
        move.l  12(%a3), %d0
        beq.s   1f
        movea.l %d0, %a0
1:      moveq   #21, %d0                | centred, 3 pixels down
        add.l   %a4, %d0
        moveq   #-3, %d1
        add.l   %a5, %d1
        bsr.w   draw_icon
        movea.l (%a3), %a0              | the label, centred under it
        bsr.w   label_fit
        moveq   #IN_RIGHT, %d1
        sub.l   %d0, %d1
        asr.l   #1, %d1
        addq.l  #1, %d1
        add.l   %a4, %d1
        pea     lbuf
        pea     str_s
        pea     -1
        pea     -26(%a5)
        move.l  %d1, -(%sp)
        pea     FONT5
        move.l  %a2, -(%sp)
        jsr     TEXTF
        lea     28(%sp), %sp
        moveq   #16, %d0                | the trig key that picks it, 1-16
        cmp.l   %d0, %d5
        bcc.s   2f
        move.l  %d5, %d0
        addq.l  #1, %d0
        move.l  %d0, -(%sp)
        pea     str_d
        pea     -1
        pea     -6(%a5)
        pea     2(%a4)
        pea     FONT5
        move.l  %a2, -(%sp)
        jsr     TEXTF
        lea     28(%sp), %sp
2:      rts

| draw_slot: a tile with no entry, a4 its left edge, a5 its top: only its
| corners.
draw_slot:
        lea     -8(%sp), %sp
        movem.l %d7/%a3, (%sp)
        lea     slot_marks, %a3
        moveq   #8, %d7
1:      pea     1
        mvs.w   6(%a3), %d0
        add.l   %a5, %d0
        move.l  %d0, -(%sp)
        mvs.w   4(%a3), %d0
        add.l   %a4, %d0
        move.l  %d0, -(%sp)
        mvs.w   2(%a3), %d0
        add.l   %a5, %d0
        move.l  %d0, -(%sp)
        mvs.w   (%a3), %d0
        add.l   %a4, %d0
        move.l  %d0, -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        addq.l  #8, %a3
        subq.l  #1, %d7
        bne.s   1b
        movem.l (%sp), %d7/%a3
        addq.l  #8, %sp
        rts

| corners: a2 the Bitmap; the box a4 (left) to d0 (right), a5 (top) to d1
| (bottom) loses its four corner pixels: a rounded frame.
corners:
        move.l  %d0, -(%sp)             | 4(sp) the right
        move.l  %d1, -(%sp)             | (sp) the bottom
        move.l  %a4, %d0
        move.l  %a5, %d1
        bsr.s   dot
        move.l  4(%sp), %d0
        move.l  %a5, %d1
        bsr.s   dot
        move.l  %a4, %d0
        move.l  (%sp), %d1
        bsr.s   dot
        move.l  4(%sp), %d0
        move.l  (%sp), %d1
        bsr.s   dot
        addq.l  #8, %sp
        rts

| dot: d0 = x, d1 = y: that pixel cleared.
dot:
        clr.l   -(%sp)
        move.l  %d1, -(%sp)
        move.l  %d0, -(%sp)
        move.l  %d1, -(%sp)
        move.l  %d0, -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        rts

| draw_icon: a2 the Bitmap, a0 16 rows of 16 bits (bit 15 the left), d0
| the x of its left column, d1 the y of its top row: each row's runs of
| set bits, one FILLRECT a run.
draw_icon:
        lea     -28(%sp), %sp
        movem.l %d2-%d7/%a3, (%sp)
        movea.l %a0, %a3
        move.l  %d0, %d4                | d4 the left column's x
        move.l  %d1, %d5                | d5 the row's y
        moveq   #16, %d7                | d7 the rows left
1:      moveq   #0, %d6
        move.w  (%a3)+, %d6
        swap    %d6                     | d6 the row, its left pixel bit 31
        moveq   #0, %d2                 | d2 the column
2:      tst.l   %d6
        beq.s   5f                      | no more set: the next row
        bmi.s   3f
        lsl.l   #1, %d6
        addq.l  #1, %d2
        bra.s   2b
3:      move.l  %d2, %d3                | d3 a run's first column
4:      lsl.l   #1, %d6
        addq.l  #1, %d2
        tst.l   %d6
        bmi.s   4b
        pea     1                       | the run, d3 to d2 - 1
        move.l  %d5, -(%sp)
        move.l  %d2, %d0
        add.l   %d4, %d0
        subq.l  #1, %d0
        move.l  %d0, -(%sp)
        move.l  %d5, -(%sp)
        move.l  %d3, %d0
        add.l   %d4, %d0
        move.l  %d0, -(%sp)
        move.l  %a2, -(%sp)
        jsr     FILLRECT
        lea     24(%sp), %sp
        bra.s   2b
5:      subq.l  #1, %d5
        subq.l  #1, %d7
        bne.s   1b
        movem.l (%sp), %d2-%d7/%a3
        lea     28(%sp), %sp
        rts

| label_fit: a0 a name -> lbuf, its first LABEL_MAX characters, and d0
| their width in pixels (FONT5: 4 a character, 3 a space, less the gap
| after the last).
label_fit:
        move.l  %d2, -(%sp)
        lea     lbuf, %a1
        moveq   #0, %d0
        moveq   #LABEL_MAX, %d1
1:      moveq   #0, %d2
        move.b  (%a0)+, %d2
        beq.s   3f
        move.b  %d2, (%a1)+
        addq.l  #4, %d0
        cmpi.l  #32, %d2
        bne.s   2f
        subq.l  #1, %d0
2:      subq.l  #1, %d1
        bne.s   1b
3:      clr.b   (%a1)
        tst.l   %d0
        beq.s   4f
        subq.l  #1, %d0
4:      move.l  (%sp)+, %d2
        rts

str_s:
        .asciz  "%s"
str_d:
        .asciz  "%d"

        .balign 2
| The default icon, for an entry without its own: a chip.
chip_icon:
        .word   0x0000, 0x0DB0, 0x0DB0, 0x1FF8, 0x700E, 0x740E, 0x1008, 0x700E
        .word   0x700E, 0x1008, 0x700E, 0x700E, 0x1FF8, 0x0DB0, 0x0DB0, 0x0000
| An empty slot's corners: x0, y0, x1, y1 from the tile's left and top.
slot_marks:
        .word   0, 0, 3, 0
        .word   0, -3, 0, 0
        .word   TILE_W - 4, 0, TILE_W - 1, 0
        .word   TILE_W - 1, -3, TILE_W - 1, 0
        .word   0, 1 - TILE_H, 3, 1 - TILE_H
        .word   0, 1 - TILE_H, 0, 4 - TILE_H
        .word   TILE_W - 4, 1 - TILE_H, TILE_W - 1, 1 - TILE_H
        .word   TILE_W - 1, 1 - TILE_H, TILE_W - 1, 4 - TILE_H

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
menu_top:
        .byte   0                       | the grid's top row on screen
lbuf:
        .space  LABEL_MAX + 1           | a label, cut to fit
        .balign 4
