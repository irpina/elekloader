| SPDX-License-Identifier: GPL-2.0-or-later
| core: the SETTINGS menu's hook (ev_settings) and core_additem. Built with
| core.s by the cores whose device has the site: the Digitakt mk1 (mods/core)
| and the Digitone mk1 (mods/core-dn1). Its addresses come from mod.json:
|
|   OP_NEW       operator new(size) -> d0
|   ITEM_CTOR    MenuItem(this, label, select, draw, change, id, step)
|   MENU_ADD     Menu::addItem(menu, item)
|   FN_MGR       a std::function manager for a 4-byte function pointer
|   SETTINGS_RET where the SETTINGS item builder goes on after its site

        .section .run, "ax"

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
        jmp     SETTINGS_RET

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
