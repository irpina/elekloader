| SPDX-License-Identifier: GPL-2.0-or-later
| core for the Octatrack (MKI and MKII), OS 1.40C: the boot copier.
| ColdFire V4 (MCF5445x); assemble with -mcpu=54455.
|
| The Octatrack has no hook bus yet: its mods (octabam's, converted) patch
| their own sites. What every one of them needs is RAM and a way to get
| their code into it, and that is this core:
|
| - mod.json moves the audio page arena's base past its bottom 1,707 pages
|   (0x40a955e0-0x41495de0, the device's `ddr`), so the OS never uses them.
|   Those are octabam's arena writes for the same reservation.
| - .boot runs where the bootstrap unpacks it (appended to MAIN OS at
|   0x4010fdf0), from the boot site 0x4000050c. That site called
|   BOOT_CONTINUE (0x40001e50), which is replayed first, as octabam's loader
|   does. Then .boot copies the RAM image the linker built into the reserve,
|   zeroes .bss, and returns with every register as BOOT_CONTINUE left it.
|   Both writes go through the uncached alias (+0x08000000), so no cache
|   line can hold the reserve's old contents when the code there first runs.
|
| The linker defines __run_load, __run_start, __run_words, __bss_start and
| __bss_words. BOOT_CONTINUE, UNCACHED and ARENA_BASE come from mod.json
| (defsym).

| The arena's base after the reserve, for a mod that compares against it
| (octabam's RECORDER HOLD: a fetch past a recording returns the base).
        .globl  arena_base
        .set    arena_base, ARENA_BASE

| ============================ .boot =======================================
        .section .boot, "ax"
        .globl  boot
boot:
        jsr     BOOT_CONTINUE           | the call the boot site made, first
        lea     -12(%sp), %sp
        movem.l %d0/%a0-%a1, (%sp)
        lea     __run_load, %a0         | where the RAM image was unpacked
        movea.l #__run_start + UNCACHED, %a1
        move.l  #__run_words, %d0
        beq.s   2f                      | nothing to copy (core alone)
1:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   1b
2:      movea.l #__bss_start + UNCACHED, %a1
        move.l  #__bss_words, %d0
        beq.s   4f
3:      clr.l   (%a1)+
        subq.l  #1, %d0
        bne.s   3b
4:      movem.l (%sp), %d0/%a0-%a1
        lea     12(%sp), %sp
        rts

| ============================ .bss ========================================
        .section .bss
        .balign 4
| What a weak import resolves to when no mod provides it: reads as zero.
        .globl  core_zero
core_zero:  .skip 16
