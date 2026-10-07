| SPDX-License-Identifier: GPL-2.0-or-later
| machine-pages (Digitakt mk1): the sites of the SRC page, the LFO page, the
| machine menu's icons and the render's voice blocks, owned once for every
| added machine. Each site's wrapper asks pages.c, which answers from the
| page the machine describes (core 3.0: its descriptor's tail, struct cm_ui
| in elekloader/sdk/include/digitakt-mk1/core3.h), and otherwise goes on to
| the stock code as it was. ColdFire V4 (MCF54418). The addresses in the
| comments are OS 1.53's; mod.json's defsym gives each OS's:
|   LAYOUT_ON     0x400657d2  the page layout, past its site
|   LAB_SHORT_ON  0x4000fe94  a knob's label, past its site
|   LAB_LONG_ON   0x4000feb6  its long name, past its site
|   VAL_TEXT_ON   0x4000f32c  the value under a turning knob, past its site
|   KNOB_GFX_ON   0x4000f2c4  a knob's graphic, past its site
|   UI_REC_ON     0x4006579e  a parameter's UI record, past its site
|   POP_TEXT_ON   0x400657f8  the value pop-up's text, past its site
|   PRANGE_FN     0x40078f0c  a parameter's range: (id), a0 the result
|   PARAM_VT      0x4017eb58  the SRC page's parameter object's vtable
|   SNDREF_VT     0x40181330  the vtable of the object at its +16
|   INJECT_LEA    0x4199e444  what the render site's lea loads into a4
|   DESC_TAB      0x401a9d9c  the parameter descriptors, 52 bytes an id
|   LFO_LABEL_ON  0x40060b94  the LFO destination label, past its site
|   LFO_LABEL_PUT 0x40060baa  ... once its name is on the stack
|   FMT_S         0x401d09ca  "%s"
|   M_TYPE_FN     0x40029e80  the machine menu's icon type of a row

        .section .run, "ax"

| ---- the SRC page ----------------------------------------------------------
| 0x400657cc(machine) -> the page's layout, 44 bytes: the knobs' ids at +8
| (A-H), 0 a blank knob. The page asks for it with its track's machine
| before it draws or turns a knob, so the hooks after this one answer for
| that machine. At its entry (was: moveq #3,d1 ; move.l 4(sp),d0), by jmp.
        .globl  mp_layout_s
mp_layout_s:
        move.l  4(%sp), -(%sp)
        jsr     mp_layout               | -> the machine's own layout, or 0
        addq.l  #4, %sp
        tst.l   %d0
        bne.s   9f
        moveq   #3, %d1
        move.l  4(%sp), %d0
        jmp     LAYOUT_ON
9:      rts

| mp_stock_layout(machine): the stock layout of machine 0-3, for pages.c.
        .globl  mp_stock_layout
mp_stock_layout:
        moveq   #3, %d1
        move.l  4(%sp), %d0
        jmp     LAYOUT_ON

| 0x4000fe8a(obj, id), a knob's label, and 0x4000feac(obj, id), its long
| name (was: move.l 8(sp),d1 ; cmpi.l #164,d1), by jmp.
        .globl  mp_lab_short_s, mp_lab_long_s
mp_lab_short_s:
        clr.l   -(%sp)                  | the short one
        move.l  12(%sp), -(%sp)         | the id
        jsr     mp_label
        addq.l  #8, %sp
        tst.l   %d0
        bne.s   9f
        move.l  8(%sp), %d1
        cmpi.l  #164, %d1
        jmp     LAB_SHORT_ON
9:      rts

mp_lab_long_s:
        pea     1.w                     | the long one
        move.l  12(%sp), -(%sp)
        jsr     mp_label
        addq.l  #8, %sp
        tst.l   %d0
        bne.s   9f
        move.l  8(%sp), %d1
        cmpi.l  #164, %d1
        jmp     LAB_LONG_ON
9:      rts

| 0x4000f324(obj, id, value, buf) -> buf: the value under a turning knob
| (was: lea -20(sp),sp ; movem.l d2-d4/a2-a3,(sp)), by jmp.
        .globl  mp_val_text_s
mp_val_text_s:
        move.l  16(%sp), -(%sp)         | buf
        move.l  16(%sp), -(%sp)         | the value
        move.l  16(%sp), -(%sp)         | the id
        jsr     mp_value_text           | -> nonzero when it wrote buf
        lea     12(%sp), %sp
        tst.l   %d0
        beq.s   1f
        move.l  16(%sp), %d0            | buf, as the stock function returns it
        rts
1:      lea     -20(%sp), %sp
        movem.l %d2-%d4/%a2-%a3, (%sp)
        jmp     VAL_TEXT_ON

| 0x4000f2bc(obj, id, value, ...): a knob's graphic (was: lea -20(sp),sp ;
| movem.l d2-d6,(sp)), by jmp. pages.c may give it another parameter's
| graphic, and another value, in its arguments.
        .globl  mp_knob_gfx_s
mp_knob_gfx_s:
        pea     8(%sp)                  | -> [id, value]
        jsr     mp_knob
        addq.l  #4, %sp
        lea     -20(%sp), %sp
        movem.l %d2-%d6, (%sp)
        jmp     KNOB_GFX_ON

| 0x40065794(id): a parameter's UI record, 84 bytes (how a turn moves it,
| its text and graphic drawers) (was: move.l 4(sp),d1 ; cmpi.l #164,d1), by
| jmp: the record of the parameter the knob borrows its look from.
        .globl  mp_ui_rec_s
mp_ui_rec_s:
        move.l  4(%sp), -(%sp)
        jsr     mp_look                 | -> the id whose record it takes
        addq.l  #4, %sp
        move.l  %d0, %d1
        cmpi.l  #164, %d1
        jmp     UI_REC_ON

| 0x400657ee(id, value) -> the value pop-up's text, in a static buffer (was:
| move.l 4(sp),d1 ; cmpi.l #164,d1), by jmp.
        .globl  mp_pop_text_s
mp_pop_text_s:
        move.l  8(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     mp_pop_text             | -> its own buffer, or 0
        addq.l  #8, %sp
        tst.l   %d0
        bne.s   9f
        move.l  4(%sp), %d1
        cmpi.l  #164, %d1
        jmp     POP_TEXT_ON
9:      rts

| ---- parameter ranges --------------------------------------------------------
| The range lookup 0x40078f0c(id), a0 the result {min, max, default}, has
| four callers: 0x4000ff20 (the setter's clamp), 0x400100c4 (a turn's
| scaling) and 0x4000f534 (a list's stepper), by jsr with the parameter
| object in a2; and 0x4000f5fc (the validator), by lea into a2, called
| later with the object as its caller's first argument (36(sp) here). Each
| goes here instead (keep2): the stock range, then the one the sound's
| machine describes. d0 = a0 = the result, as the stock lookup leaves them.
        .globl  mp_prange_s, mp_prange_f_s
mp_prange_s:
        movea.l %a2, %a1
        bra.s   1f
mp_prange_f_s:
        movea.l 36(%sp), %a1
1:      move.l  %a1, -(%sp)             | the object
        move.l  %a0, -(%sp)             | the result's place
        move.l  12(%sp), -(%sp)         | the id
        jsr     PRANGE_FN
        addq.l  #4, %sp
        movea.l (%sp), %a0
        movea.l 4(%sp), %a1
        bsr.s   mp_rmach                | d0 = the sound's machine, or -1
        move.l  %d0, 4(%sp)             | [out][machine]
        move.l  12(%sp), -(%sp)         | [id][out][machine]
        jsr     mp_range
        addq.l  #4, %sp
        movea.l (%sp), %a0
        addq.l  #8, %sp
        move.l  %a0, %d0
        rts

| a1 = a parameter object -> d0 = its sound's machine, or -1 when it is not
| a sound's parameter. Changes d0 and a1.
mp_rmach:
        move.l  (%a1), %d0
        cmpi.l  #PARAM_VT, %d0
        bne.s   8f
        movea.l 16(%a1), %a1
        move.l  (%a1), %d0
        cmpi.l  #SNDREF_VT, %d0
        bne.s   8f
        movea.l 16(%a1), %a1            | the sound
        moveq   #0, %d0
        move.b  126(%a1), %d0           | its machine
        rts
8:      moveq   #-1, %d0
        rts

| ---- the render ---------------------------------------------------------------
| ev_render_voices(blocks): at 0x40077fba in the render handler, after
| playback has written every track's block (32 Q31 samples, 128 bytes a
| track at fw_track_blocks) and before the overdrive stage (was: lea
| 0x4199e444,a4), by jsr. Handlers in order: 10-49 make a track's sound,
| 50-89 take or change sound already made. Every register is kept, then the
| replaced instruction.
        .globl  mp_render_s
mp_render_s:
        lea     -60(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        lea     ev_render_voices, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        pea     fw_track_blocks
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movem.l (%sp), %d0-%d7/%a0-%a6
        lea     60(%sp), %sp
        lea     INJECT_LEA, %a4
        rts

| ---- the LFO page's DEST names -------------------------------------------------
| A destination is a parameter id, named from its descriptor (DESC_TAB + 52
| id: the long name +40, the group +44, the short name +48). pages.c answers
| for the active track's machine (mp_lfo, mp_lfo52), else with the stock
| name it is given.
|
| 0x40060b8e, the destination's label (was: lea DESC_TAB,a0), by jmp; d0 =
| the id. The stock code after it puts the short name at (sp) and goes on
| at 0x40060baa; when the machine names it, it is put there here.
        .globl  mp_lfo_label_s
mp_lfo_label_s:
        move.l  %d0, -(%sp)
        clr.l   -(%sp)                  | no stock name: 0 when not ours
        pea     2.w                     | the short name
        move.l  %d0, -(%sp)
        jsr     mp_lfo
        lea     12(%sp), %sp
        tst.l   %d0
        beq.s   1f
        addq.l  #4, %sp
        move.l  %d0, (%sp)              | the name, where the stock code puts it
        lea     DESC_TAB, %a0
        jmp     LFO_LABEL_PUT
1:      move.l  (%sp)+, %d0
        lea     DESC_TAB, %a0
        jmp     LFO_LABEL_ON

| The other four push their names as arguments. Each wrapper leaves the
| pushes the stock instructions make (a slot under the return address for
| each), with mp_lfo52's answer in place of the field; every register is
| kept. d7 is kept by the C code, so it holds 52 id across the calls.
|
| 0x400a4374, a row of the DEST list (was: move.l 0x28(a3,d0.l),-(sp) ;
| move.l d6,-(sp)): d0 = 52 id, a3 = DESC_TAB, d6 the group's text. Leaves
| [group][long name].
        .globl  mp_lfo_list_s
mp_lfo_list_s:
        move.l  (%sp), -(%sp)
        move.l  (%sp), -(%sp)           | [ret][ret][ret]
        lea     -60(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        move.l  %d0, %d7
        move.l  0x28(%a3,%d0.l), -(%sp)
        pea     1.w
        move.l  %d7, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 68(%sp)            | the long name
        move.l  %d6, -(%sp)
        clr.l   -(%sp)
        move.l  %d7, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 64(%sp)            | the group
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     60(%sp), %sp
        rts

| 0x400a43f0, the same row when "group:long name" is too wide for it (was:
| move.l 0x30(a3,d2.l),-(sp) ; move.l d6,-(sp)): d2 = 52 id. Leaves
| [group][short name].
        .globl  mp_lfo_lshort_s
mp_lfo_lshort_s:
        move.l  (%sp), -(%sp)
        move.l  (%sp), -(%sp)
        lea     -60(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        move.l  0x30(%a3,%d2.l), -(%sp)
        pea     2.w
        move.l  %d2, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 68(%sp)            | the short name
        move.l  %d6, -(%sp)
        clr.l   -(%sp)
        move.l  %d2, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 64(%sp)            | the group
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     60(%sp), %sp
        rts

| 0x40065de6, the DEST box's top line (was: move.l 0x2c(a0,d0.l),-(sp) ;
| move.l d2,-(sp)): d0 = 52 id, a0 = DESC_TAB, d2 the line's string.
| Leaves [d2][group].
        .globl  mp_lfo_bgrp_s
mp_lfo_bgrp_s:
        move.l  (%sp), -(%sp)
        move.l  (%sp), -(%sp)
        lea     -60(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        move.l  %d2, 64(%sp)
        move.l  0x2c(%a0,%d0.l), -(%sp)
        clr.l   -(%sp)
        move.l  %d0, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 68(%sp)            | the group
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     60(%sp), %sp
        rts

| 0x40065e68, the DEST box's bottom line (was: pea "%s", after move.l
| 0x30(a0,d3.l),-(sp)): d3 = 52 id. Leaves ["%s"][short name].
        .globl  mp_lfo_bname_s
mp_lfo_bname_s:
        move.l  (%sp), -(%sp)           | [ret][ret][short name]
        lea     -60(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        lea     FMT_S, %a0
        move.l  %a0, 64(%sp)
        move.l  68(%sp), -(%sp)         | the stock short name
        pea     2.w
        move.l  %d3, -(%sp)
        jsr     mp_lfo52
        lea     12(%sp), %sp
        move.l  %d0, 68(%sp)
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     60(%sp), %sp
        rts

| ---- knob D, when it is not a sample -----------------------------------------
| The SRC page's knob handlers compare the turned knob's id with SAMP's
| (0x87) and open the sample list instead of changing it: at 0x4003b314
| (was: cmpi.l #135,d0) and 0x4003b5b2 (was: cmpi.l #135,d2), by jsr. When
| the page's machine marks knob D CM_NOT_SAMPLE, the compare says "not
| SAMP" (Z clear); otherwise it is the stock compare. Every register is
| kept; only the condition codes are read after it.
        .globl  mp_samp_d0_s, mp_samp_d2_s
mp_samp_d0_s:
        cmpi.l  #0x87, %d0
        bne.s   9f                      | not SAMP: Z clear
        bsr.s   mp_samp_ours
        beq.s   1f
        tst.l   %d0                     | 0x87: Z clear, no sample list
        rts
1:      cmpi.l  #0x87, %d0              | SAMP's own: Z set
9:      rts

mp_samp_d2_s:
        cmpi.l  #0x87, %d2
        bne.s   9f
        bsr.s   mp_samp_ours
        beq.s   1f
        tst.l   %d2
        rts
1:      cmpi.l  #0x87, %d2
9:      rts

| -> Z clear when knob D on the page is not a sample. Every register kept.
mp_samp_ours:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        jsr     mp_not_sample
        tst.l   %d0
        movem.l (%sp), %d0-%d1/%a0-%a1  | the flags stay
        lea     16(%sp), %sp
        rts

| ---- the machine menu's icons ------------------------------------------------
| The menu's row loop asks 0x40029e80(machine) for a row's icon type (1-4
| for the stock four, 0 past them) and draws a row's icon only when its
| type differs from the row above's, so core 2.1 drew an icon for the first
| added machine only. At 0x4002a382 (was: jsr 0x40029e80), by keep2: an
| added machine's type is its own, 5 + its number, so every row draws its
| icon (core's icon callback draws the machine's own, or none).
        .globl  mp_mtype
mp_mtype:
        move.l  4(%sp), %d0
        moveq   #3, %d1
        cmp.l   %d0, %d1
        bcs.s   1f
        jmp     M_TYPE_FN               | 0-3: the stock types
1:      addq.l  #5, %d0
        rts
