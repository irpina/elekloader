| SPDX-License-Identifier: GPL-2.0-or-later
| perform-direct: the PERSONALIZE row's label callback. It returns a
| std::string through a0, which C cannot say: std::string(a0, label, alloc&)
| at 0x401e7e7a, the mk1's 0x4017af20 (as the firmware's own label
| callbacks do, 0x4009c5cc on).
        .equ STR_CTOR, 0x401e7e7a
        .section .run, "ax"
        .globl  pd_label
pd_label:
        link    %a6, #-4
        move.l  %d2, -(%sp)
        pea     -1(%a6)                 | the allocator: one byte
        pea     label
        move.l  %a0, %d2
        move.l  %a0, -(%sp)             | the string to construct
        jsr     STR_CTOR
        lea     12(%sp), %sp
        move.l  %d2, %d0
        move.l  -8(%a6), %d2
        unlk    %a6
        rts

label:  .asciz  "DIRECT PERFORM"
        .balign 2
