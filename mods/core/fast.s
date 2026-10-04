| SPDX-License-Identifier: GPL-2.0-or-later
| core: the .fast copy table, for a device whose core provides it (the
| Digitakt II's, mods/core-dt2; on the Digitakt mk1 a mod declares
| fa_copies instead). The linker adds an entry to core_fast for each mod
| with .fast code: its source in RAM, its SRAM address, its length (a
| multiple of 4) and a zero word; a zero entry ends the table.
|
| The OS fills and zeroes SRAM at reset, after core's boot copier, so the
| copy waits for the UI: core_fastcopy is an ev_tick handler (order 0) that
| copies every entry on its first call. .fast code is there from the first
| ev_tick on; nothing may call it before. The SRAM has never held code that
| ran, so no instruction cache line can be stale.

        .section .run, "ax"
        .globl  core_fastcopy
core_fastcopy:
        tst.l   fast_done
        bne.s   3f
        move.l  %a2, -(%sp)
        lea     core_fast, %a2
1:      move.l  (%a2)+, %d0             | source
        beq.s   2f
        movea.l %d0, %a0
        movea.l (%a2)+, %a1             | destination
        move.l  (%a2)+, %d0             | length
        addq.l  #4, %a2                 | the zero word
        lsr.l   #2, %d0
        beq.s   1b
4:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   4b
        bra.s   1b
2:      moveq   #1, %d0
        move.l  %d0, fast_done
        movea.l (%sp)+, %a2
3:      rts

        .section .bss
        .balign 4
fast_done:  .skip 4
