| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: mod pages (Digitone mk1, OS 1.43). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s and params.s; the Digitakt's core does not have
| them.
|
| A parameter page (SYN1's two, AMP's two, ...) is a 44-byte record: a short
| and a long title (char pointers; the long one heads the screen), the eight
| knobs' parameter ids (0 is an empty box) and a kind (9 for a sound's page).
| The firmware has 26, indexed 1-26, and finds one by its index through one
| routine, PAGE_REC. Each page key's view keeps the indices of its pages in a
| std::vector<int> at +124 (+128 its end, +132 its capacity) and the one it
| shows at +144; pressing the key again steps through them, and the title
| counts them ("Amplitude (2/3)"). The views are built at boot, each by
| VIEW_INIT(view, list, ...), which copies the list it is given.
|
| From 2.2 a mod adds a page by contributing to the table core_pages a
| pointer to its descriptor (in .data: core writes its last two words):
|   +0  idx     27-30, claimed as the resource page:<idx>
|   +4  after   the stock page it follows in its key's list: 9 (AMP's second
|               page) makes it AMP's third
|   +8  the 44-byte record
|   +52 view    0; core writes the view that shows it when that is built
|   +56 pos     core writes its place in that view's list
| PAGE_REC then returns the record for idx, VIEW_INIT puts idx after the
| page it follows, and the stock UI shows the page and turns its knobs like
| its own. core_page_open opens it from a key handler.
        .equ    PAGE0,    27            | the first index for mods
        .equ    PAGES,    4
        .equ    LISTMAX,  32            | the longest list core rebuilds
        .equ    EVLEN,    32            | a key event, with room to spare
        .equ    VIEW_CUR, 144           | a view's page: its place in its list
        .equ    PRESSES,  8             | the most core_page_open sends

        .section .run, "ax"

| core_page_rec: PAGE_REC(idx) -> d0 = the page record. By jmp at its entry
| (0x40089a2c, the three instructions there are run at 3: below): a mod's
| index gets its descriptor's record, anything else the stock routine.
        .globl  core_page_rec
core_page_rec:
        move.l  4(%sp), %d0
        cmpi.l  #PAGE0, %d0
        bcs.s   3f
        lea     core_pages, %a0
1:      move.l  (%a0)+, %d1             | a descriptor, or 0: the table's end
        beq.s   3f
        movea.l %d1, %a1
        cmp.l   (%a1), %d0
        bne.s   1b
        lea     8(%a1), %a1
        move.l  %a1, %d0
        rts
3:      move.l  %d3, -(%sp)
        moveq   #26, %d0
        move.l  %d2, -(%sp)
        jmp     PAGE_REC + 6

| core_view_init: VIEW_INIT(view, list, a, b). By jmp at its entry
| (0x40044490). Copies the list to core_view_buf, putting each mod page right
| after the page it follows and noting the view and its place in the
| descriptor, and gives the stock routine that copy instead. A list too long
| for the buffer goes through unchanged.
        .globl  core_view_init
core_view_init:
        lea     -24(%sp), %sp           | 0: the copy's std::vector, 12: saves
        movem.l %d2/%a2-%a3, 12(%sp)
        movea.l 32(%sp), %a0            | the list (args from 28: view, list)
        movea.l (%a0), %a1              | its first index
        move.l  4(%a0), %d2             | its end
        sub.l   %a1, %d2
        cmpi.l  #4 * (LISTMAX - PAGES), %d2
        bhi.s   5f
        add.l   %a1, %d2
        lea     core_view_buf, %a2
1:      cmp.l   %a1, %d2                | each stock index ...
        beq.s   4f
        move.l  (%a1)+, %d0
        move.l  %d0, (%a2)+
        lea     core_pages, %a3
2:      move.l  (%a3)+, %d1             | ... and each mod page after it
        beq.s   1b
        movea.l %d1, %a0
        cmp.l   4(%a0), %d0
        bne.s   2b
        move.l  (%a0), (%a2)+
        move.l  28(%sp), 52(%a0)        | the view
        move.l  %a2, %d1
        subi.l  #core_view_buf + 4, %d1
        asr.l   #2, %d1
        move.l  %d1, 56(%a0)            | the place in its list
        bra.s   2b
4:      lea     core_view_buf, %a0      | the copy as a vector
        move.l  %a0, (%sp)
        move.l  %a2, 4(%sp)
        move.l  %a2, 8(%sp)
        move.l  40(%sp), -(%sp)         | b
        move.l  40(%sp), -(%sp)         | a
        pea     8(%sp)                  | the copy
        move.l  40(%sp), -(%sp)         | view
        bsr.s   6f
        lea     16(%sp), %sp
        movem.l 12(%sp), %d2/%a2-%a3
        lea     24(%sp), %sp
        rts
5:      movem.l 12(%sp), %d2/%a2-%a3    | too long: the stock routine as called
        lea     24(%sp), %sp
6:      lea     -28(%sp), %sp           | the two instructions the jmp replaced
        movem.l %d2-%d5/%a2-%a4, (%sp)
        jmp     VIEW_INIT + 8

| int core_page_open(void *brain, void *event, int key, descriptor *page):
| from an ev_key handler (its brain and event), shows the mod page. It
| presses and releases the page key that owns the page's view through the
| stock key dispatcher, as often as it takes: the first brings that view
| up, each next one steps it to its next page, title and all, as the key
| does. -> 1, or 0 when the page's view was never built.
        .globl  core_page_open
core_page_open:
        movea.l 16(%sp), %a1            | the descriptor
        tst.l   52(%a1)
        bne.s   1f
        moveq   #0, %d0
        rts
1:      lea     -8(%sp), %sp
        movem.l %d2/%a2, (%sp)          | args from 12: brain, event, key, page
        movea.l 16(%sp), %a0            | the event, copied
        lea     core_page_ev, %a2
        moveq   #EVLEN / 4, %d0
2:      move.l  (%a0)+, (%a2)+
        subq.l  #1, %d0
        bne.s   2b
        lea     core_page_ev, %a2
        move.l  20(%sp), 12(%a2)        | the key
        moveq   #PRESSES, %d2
3:      moveq   #1, %d0                 | pressed
        bsr.s   9f
        moveq   #0x10, %d0              | released
        bsr.s   9f
        movea.l 24(%sp), %a1
        movea.l 52(%a1), %a0
        move.l  VIEW_CUR(%a0), %d0      | the view's page: the mod's yet?
        cmp.l   56(%a1), %d0
        beq.s   4f
        subq.l  #1, %d2
        bne.s   3b
4:      movem.l (%sp), %d2/%a2
        lea     8(%sp), %sp
        moveq   #1, %d0
        rts
9:      move.l  %d0, 16(%a2)            | d0 = the flags -> KEYDISP(brain, ev)
        move.l  %a2, -(%sp)
        move.l  20(%sp), -(%sp)         | brain (past this call's return, d2, a2)
        jsr     KEYDISP
        addq.l  #8, %sp
        rts

| int core_page_shown(void *brain, descriptor *page): 1 when the page is on
| screen with nothing over it. The key dispatcher's brain keeps the screens
| shown: +0x54 the bottom one, the page views' (its +8 the page manager,
| whose +0xc0 is the view shown), +0x5c the top one, another when a menu or
| a browser is open over the pages.
        .globl  core_page_shown
core_page_shown:
        movea.l 4(%sp), %a0             | the brain
        move.l  0x54(%a0), %d0
        beq.s   0f
        cmp.l   0x5c(%a0), %d0          | something over the pages?
        bne.s   0f
        movea.l %d0, %a0
        move.l  8(%a0), %d0             | the page manager
        beq.s   0f
        movea.l %d0, %a0
        move.l  0xc0(%a0), %d0          | its view shown
        movea.l 8(%sp), %a1
        cmp.l   52(%a1), %d0
        bne.s   0f
        movea.l %d0, %a0
        move.l  VIEW_CUR(%a0), %d0
        cmp.l   56(%a1), %d0
        bne.s   0f
        moveq   #1, %d0
        rts
0:      moveq   #0, %d0
        rts

| ============================ .bss ========================================
        .section .bss
        .balign 4
core_view_buf:
        .skip   4 * LISTMAX
core_page_ev:
        .skip   EVLEN
