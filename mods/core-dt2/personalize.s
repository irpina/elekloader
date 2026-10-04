| SPDX-License-Identifier: GPL-2.0-or-later
| core-dt2: ev_personalize, the Digitakt II's SETTINGS > PERSONALIZE menu.
| ColdFire V4 (MCF5441x); assemble with -mcpu=54455. OS 1.17.
|
| The PERSONALIZE builder (0x4009daec) adds its rows with the same generic
| MenuItem as SETTINGS (0x40115a44, then Menu::addItem 0x4011527a), the
| menu in a4, and ends: movem.l $18(a7),d2-d6/a2-a6 ; lea $80(a7),a7 ; rts.
| The site 0x4009e2a2 jumps here in place of the movem, after its last row
| (TRK SELECT). Handlers: f(menu), which add rows with
| core_additem(menu, row), as from ev_settings. The movem restores every
| register the handlers could have changed, so they need only follow the C
| convention.
|
| A row redraws the menu with View::invalidate(menu + 0x38), as from
| SETTINGS. (The firmware's own PERSONALIZE rows keep the menu in a heap
| cell, so their code reads it through one more pointer.)

        .section .run, "ax"
        .globl  core_personalize
core_personalize:
        lea     ev_personalize, %a3
1:      move.l  (%a3)+, %d0
        beq.s   2f
        move.l  %a4, -(%sp)             | the menu
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movem.l 0x18(%sp), %d2-%d6/%a2-%a6   | the instructions this replaced
        lea     0x80(%sp), %sp
        rts
