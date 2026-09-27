| SPDX-License-Identifier: GPL-2.0-or-later
| core: the boot copier and the hook bus every other mod builds on.
| ColdFire V4 (MCF54418), Digitakt mk1 OS 1.53; assemble with -mcpu=54455.
|
| .boot runs where the bootstrap unpacks it (appended to MAIN OS at
| 0x4025CA40), once, from the OS entry's call at 0x40000538: before the OS
| zeroes 0x40252000-0x439D0000 and turns the caches on. It copies the DDR
| image the patcher's linker built to 0x47BE0000, zeroes .bss, starts DTIM0
| if nothing has, and goes on to the call it replaced. The linker defines
| the __run_*/__bss_* symbols.
|
| Each shared site calls the handlers mods subscribe to its event, from a
| table the linker builds (docs/ADAPTING.md, "The Digitakt mk1 hook bus"):
| a list of pointers ending in 0. Handlers use the C convention.

        .equ DRAWALL,     0x400ca382    | ViewController::drawAll(ctrl, Bitmap&)
        .equ KEYDISP,     0x400084fe    | Brain::key(brain, KeyEvent*)
        .equ ENCDISP,     0x40008550    | Brain::enc(brain, EncoderEvent*)
        .equ OP_NEW,      0x400d4180    | operator new(size) -> d0
        .equ ITEM_CTOR,   0x400c423c    | MenuItem(this, label, select, draw, change, id, step)
        .equ MENU_ADD,    0x400c3a72    | Menu::addItem(menu, item)
        .equ FN_MGR,      0x40137478    | std::function manager, 4-byte payload
        .equ DTMR0,       0xFC070000    | DMA timer 0 mode
        .equ PPMSR0,      0xFC04002D    | peripheral clock set register
        .equ VBR_FN,      0x40001c94    | the call 0x40000538 made

| ============================ .boot =======================================
        .section .boot, "ax"
        .globl  boot
boot:
        lea     __run_load, %a0         | where the DDR image was unpacked
        lea     __run_start, %a1        | where it runs
        move.l  #__run_words, %d0
1:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   1b
        lea     __bss_start, %a1        | DDR holds noise at power-on
        move.l  #__bss_words, %d0
        beq.s   3f
2:      clr.l   (%a1)+
        subq.l  #1, %d0
        bne.s   2b
3:      | DTIM0: the OS reads its counter as a 132 MHz time base and never
        | starts it, so something before the OS does. Start it only if it is
        | held in reset: rewriting DTMR0 while it runs would stop it.
        move.w  DTMR0, %d0
        btst    #0, %d0
        bne.s   4f
        move.b  #0x1C, %d0
        move.b  %d0, PPMSR0             | its clock on
        clr.l   %d0
        move.w  %d0, DTMR0
        moveq   #3, %d0
        move.w  %d0, DTMR0              | bus clock, free running
4:      jmp     VBR_FN                  | its rts returns to 0x4000053e

| ============================ .run ========================================
        .section .run, "ax"

| ---- ev_tick: the 30 Hz compose check -------------------------------------
| At 0x4000a770 (was: jsr 0x400ca34c, which returns ctrl->dirty, byte +0x20,
| in d0). (sp) = return, 4(sp) = the view controller. UI task. Handlers:
| f(ctrl); one that wants the frame recomposed sets ctrl+0x20.
        .globl  core_tick
core_tick:
        move.l  %a2, -(%sp)
        lea     ev_tick, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  8(%sp), -(%sp)          | ctrl
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a2
        movea.l 4(%sp), %a0             | what 0x400ca34c returns
        move.b  0x20(%a0), %d0
        rts

| ---- ev_draw: on top of every composed frame ------------------------------
| At 0x4000a7d6 (was: jsr 0x400ca382, drawAll(ctrl, bmp)). (sp) = return,
| 4(sp) = ctrl, 8(sp) = the frame's Bitmap. d2-d7/a2-a6 must survive.
| Handlers: f(bmp, ctrl), in order, each over the last.
        .globl  core_draw
core_draw:
        move.l  8(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     DRAWALL                 | every visible view, as before
        addq.l  #8, %sp
        move.l  %a2, -(%sp)
        lea     ev_draw, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  8(%sp), -(%sp)          | ctrl
        move.l  16(%sp), -(%sp)         | bmp
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a2
        rts

| ---- ev_key, ev_enc: the UI main loop's key and encoder dispatch -----------
| At 0x4000b770 (was: jsr 0x400084fe) and 0x4000b7ba (was: jsr 0x40008550).
| (sp) = return, 4 brain, 8 the event. Handlers: f(brain, event) -> d0
| nonzero when they took it; then nothing after them sees it, stock
| included.
        .globl  core_key, core_enc
core_key:
        move.l  %a2, -(%sp)
        lea     ev_key, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     KEYDISP                 | the stock path, same stack
1:      rts

core_enc:
        move.l  %a2, -(%sp)
        lea     ev_enc, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     ENCDISP
1:      rts

| dispatch: a2 = the table; 12(sp) brain, 16(sp) event (after its return
| address and the caller's saved a2). -> d0 = the first nonzero result, or 0.
dispatch:
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  16(%sp), -(%sp)         | the event
        move.l  16(%sp), -(%sp)         | brain
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        tst.l   %d0
        beq.s   1b
2:      rts

| ---- ev_settings: the SETTINGS menu's rows ---------------------------------
| At 0x40058800 in the item builder 0x400583fc (was: movea.l (a2),a0 ;
| pea 2.w), by jmp, after the last row and before the selection is
| restored; a2 = the menu. Handlers: f(menu), which add rows with
| core_additem(menu, row).
        .globl  core_settings
core_settings:
        move.l  %a3, -(%sp)
        lea     ev_settings, %a3
1:      move.l  (%a3)+, %d0
        beq.s   2f
        move.l  %a2, -(%sp)             | the menu
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a3
        movea.l (%a2), %a0              | the instructions this replaced
        pea     2.w
        jmp     0x40058806

| core_additem(Menu*, row*): a 0x54-byte MenuItem with four std::function
| objects, the callbacks from row: label, select, draw, change.
        .globl  core_additem
core_additem:
        link    %a6, #-64
        lea     -12(%sp), %sp
        movem.l %d2/%a2-%a3, (%sp)
        movea.l 8(%a6), %a2
        movea.l 12(%a6), %a3
        lea     -64(%a6), %a0           | label: no payload
        clr.l   (%a0)
        clr.l   4(%a0)
        move.l  #FN_MGR, %d0
        move.l  %d0, 8(%a0)
        move.l  (%a3), %d0
        move.l  %d0, 12(%a0)
        lea     -48(%a6), %a0           | select: payload = the menu
        move.l  %a2, (%a0)
        clr.l   4(%a0)
        move.l  #FN_MGR, %d0
        move.l  %d0, 8(%a0)
        move.l  4(%a3), %d0
        move.l  %d0, 12(%a0)
        lea     -32(%a6), %a0           | draw: no payload
        clr.l   (%a0)
        clr.l   4(%a0)
        move.l  #FN_MGR, %d0
        move.l  %d0, 8(%a0)
        move.l  8(%a3), %d0
        move.l  %d0, 12(%a0)
        lea     -16(%a6), %a0           | change: payload = the menu
        move.l  %a2, (%a0)
        clr.l   4(%a0)
        move.l  #FN_MGR, %d0
        move.l  %d0, 8(%a0)
        move.l  12(%a3), %d0
        move.l  %d0, 12(%a0)
        pea     0x54.w
        jsr     OP_NEW
        addq.l  #4, %sp
        move.l  %d0, %d2
        pea     8.w
        pea     -1.w
        pea     -16(%a6)
        pea     -32(%a6)
        pea     -48(%a6)
        pea     -64(%a6)
        move.l  %d2, -(%sp)
        jsr     ITEM_CTOR
        lea     28(%sp), %sp
        move.l  %d2, -(%sp)
        move.l  %a2, -(%sp)
        jsr     MENU_ADD
        addq.l  #8, %sp
        movem.l -76(%a6), %d2/%a2-%a3
        unlk    %a6
        rts

| ---- ev_render_in, ev_render_out: the audio render (vector 191) ------------
| Entry, at 0x40077428 (was: move.l #$7fffffff,d0). The handler has saved
| d0-d7/a0-a5; a6 is its frame. d1/a0/a1 are kept around the handlers.
        .globl  core_render_in
core_render_in:
        lea     -16(%sp), %sp
        movem.l %d1/%a0-%a2, (%sp)
        lea     ev_render_in, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      movem.l (%sp), %d1/%a0-%a2
        lea     16(%sp), %sp
        move.l  #0x7fffffff, %d0        | the instruction this replaced
        rts

| Exit, at 0x400784c8 (was: movem.l -$a8(a6),d0-d7/a0-a5), the handler's
| only way out: every register but a6 is restored after the handlers.
        .globl  core_render_out
core_render_out:
        lea     ev_render_out, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      movem.l -0xa8(%a6), %d0-%d7/%a0-%a5
        rts

| ============================ .bss ========================================
        .section .bss
        .balign 4
| What a weak import resolves to when no mod provides it: reads as zero.
        .globl  core_zero
core_zero:  .skip 16
