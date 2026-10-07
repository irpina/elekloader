| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1: project data (Digitone mk1, OS 1.43). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s, params.s and pages.s.
|
| A project is saved as one block, projectStorage_v14_t (2782212 bytes): the
| firmware serializes the project in RAM into a storage buffer, and writes
| that buffer to the project's slot on the card (or to the temp area); a load
| reads a slot into a buffer and deserializes it. The block starts with a
| 32-byte header (0xBEEFBACE, version 14, the name, ...) and its first data
| record is at +0x200: the 480 bytes between are written and read with the
| rest, and the firmware neither fills nor reads them.
|
| From 2.1 mods keep data there, saved and loaded with the project. A mod
| contributes to the table core_projdata a pointer to a descriptor:
|   +0  tag      four characters, claimed as the resource projdata:<tag>
|   +4  size     bytes, a multiple of 4
|   +8  data     the mod's copy in RAM, which it reads and writes
|   +12 loaded   void loaded(int found), or 0: after a project's data is
|               loaded into RAM; found 0 when the project has none for this
|               tag (a project saved without the mod, or a new one), when
|               data holds zeros and the mod sets its defaults
| Core puts each block in the gap after the project is serialized for a save
| (core_proj_save), and takes them out after a project is deserialized
| (core_proj_load) or a new one is made (core_proj_new). The gap holds
| 'ELKP', then per block its tag, its size and its bytes, then a zero tag.
        .equ    GAP,      0x20          | the gap in the storage block
        .equ    GAP_END,  0x200
        .equ    MAGIC,    0x454c4b50    | 'ELKP'

        .section .run, "ax"

| core_proj_save: SERIALIZE(data, project, a, b, cb), by jmp at its entry
| (0x4000eb10; its first two instructions are run at 1: below), then the
| blocks into data's gap. Every save goes through it: to a slot, to the
| temp area, and the working copy the OS keeps for power-up (written
| compressed at sectors 0x7a000/0x7c000, read back at boot). Keeps the
| result.
        .globl  core_proj_save
core_proj_save:
        move.l  20(%sp), -(%sp)
        move.l  20(%sp), -(%sp)
        move.l  20(%sp), -(%sp)
        move.l  20(%sp), -(%sp)
        move.l  20(%sp), -(%sp)
        bsr.s   1f
        lea     20(%sp), %sp
        move.l  %d0, -(%sp)
        move.l  8(%sp), -(%sp)          | data
        bsr.w   stamp
        addq.l  #4, %sp
        move.l  (%sp)+, %d0
        rts
1:      lea     -44(%sp), %sp
        movem.l %d2-%d7/%a2-%a6, (%sp)
        jmp     SERIALIZE + 8

| core_proj_load: DESERIALIZE(project, data, cb) by jsr from the load of a
| slot (0x400acc40), then, if it loaded, the blocks out of data's gap.
        .globl  core_proj_load
core_proj_load:
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        jsr     DESERIALIZE
        lea     12(%sp), %sp
        move.l  %d0, -(%sp)
        tst.b   %d0
        beq.s   1f
        move.l  12(%sp), -(%sp)         | data
        bsr.w   extract
        addq.l  #4, %sp
1:      move.l  (%sp)+, %d0
        rts

| core_proj_import: the other load, of a storage block already in RAM
| (0x40010ca6: at boot and from SysEx), by jsr at 0x40010cfa in place of
| 'move.l d4,-(sp); jsr DESERIALIZE' (d4 the project, then on the stack the
| data and cb). Leaves the stack as those two did: d4 where its return
| address was, which waits in core_import_ret meanwhile.
        .globl  core_proj_import
core_proj_import:
        move.l  (%sp), core_import_ret
        move.l  %d4, (%sp)              | the move.l d4,-(sp) this replaced
        jsr     DESERIALIZE             | (project, data, cb)
        move.l  %d0, -(%sp)
        tst.b   %d0
        beq.s   1f
        move.l  8(%sp), -(%sp)          | data
        bsr.w   extract
        addq.l  #4, %sp
1:      move.l  (%sp)+, %d0
        move.l  core_import_ret, -(%sp)
        rts

| core_proj_new: the new project's copy (MEMCPY(dst, src, n), by jsr at
| 0x400acbf4 in the load of slot -1), then every block's defaults.
        .globl  core_proj_new
core_proj_new:
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        jsr     MEMCPY
        lea     12(%sp), %sp
        move.l  %d0, -(%sp)
        clr.l   -(%sp)                  | no data: defaults
        bsr.w   extract
        addq.l  #4, %sp
        move.l  (%sp)+, %d0
        rts

| core_proj_init: INIT_PROJECT(project), the new project built in RAM (CREATE
| NEW and two more), by jmp at its entry (0x4001570e; its first two
| instructions are run at 1: below), then every block's defaults.
        .globl  core_proj_init
core_proj_init:
        move.l  4(%sp), -(%sp)
        bsr.s   1f
        addq.l  #4, %sp
        move.l  %d0, -(%sp)
        clr.l   -(%sp)                  | no data: defaults
        bsr.w   extract
        addq.l  #4, %sp
        move.l  (%sp)+, %d0
        rts
1:      lea     -20(%sp), %sp
        movem.l %d2-%d4/%a2-%a3, (%sp)
        jmp     INIT_PROJECT + 8

| stamp(data): 'ELKP', each block that fits, a zero tag. C conventions.
stamp:
        lea     -12(%sp), %sp
        movem.l %d2/%a2-%a3, (%sp)
        movea.l 16(%sp), %a1            | data
        lea     GAP_END(%a1), %a3       | the end of the gap
        lea     GAP(%a1), %a1
        move.l  #MAGIC, (%a1)+
        lea     core_projdata, %a2
1:      move.l  (%a2)+, %d0             | a descriptor, or 0
        beq.s   4f
        movea.l %d0, %a0
        move.l  4(%a0), %d1             | its size
        move.l  %a3, %d2                | room: tag, size, data, a zero tag
        sub.l   %a1, %d2
        subi.l  #12, %d2
        cmp.l   %d1, %d2
        bcs.s   1b                      | does not fit: left out
        move.l  (%a0), (%a1)+
        move.l  %d1, (%a1)+
        movea.l 8(%a0), %a0
        lsr.l   #2, %d1
        beq.s   1b
2:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d1
        bne.s   2b
        bra.s   1b
4:      clr.l   (%a1)
        movem.l (%sp), %d2/%a2-%a3
        lea     12(%sp), %sp
        rts

| extract(data): each block's bytes from data's gap into its RAM, or zeros,
| then its loaded(found). data 0: none found. C conventions.
extract:
        lea     -20(%sp), %sp
        movem.l %d2-%d4/%a2-%a3, (%sp)
        lea     core_projdata, %a2
1:      move.l  (%a2)+, %d0
        beq.w   9f
        movea.l %d0, %a3                | the descriptor
        moveq   #0, %d4                 | found
        move.l  24(%sp), %d0            | data
        beq.s   5f
        movea.l %d0, %a0
        lea     GAP_END(%a0), %a1       | the end of the gap
        lea     GAP(%a0), %a0
        move.l  (%a0)+, %d0
        cmpi.l  #MAGIC, %d0
        bne.s   5f
2:      move.l  (%a0)+, %d0             | a block's tag
        beq.s   5f
        move.l  (%a0)+, %d1             | its size
        move.l  %a1, %d2
        sub.l   %a0, %d2
        cmp.l   %d1, %d2
        bcs.s   5f                      | runs past the gap: corrupt, stop
        cmp.l   (%a3), %d0
        beq.s   3f
        adda.l  %d1, %a0
        bra.s   2b
3:      move.l  4(%a3), %d2             | ours: copy what both sizes hold
        cmp.l   %d1, %d2
        bls.s   4f
        move.l  %d1, %d2
4:      movea.l 8(%a3), %a1
        bsr.s   zero                    | the whole RAM copy, then the bytes
        lsr.l   #2, %d2
        beq.s   8f
41:     move.l  (%a0)+, (%a1)+
        subq.l  #1, %d2
        bne.s   41b
8:      moveq   #1, %d4
        bra.s   6f
5:      movea.l 8(%a3), %a1             | none: zeros
        bsr.s   zero
6:      move.l  12(%a3), %d0            | loaded(found)
        beq.s   1b
        move.l  %d4, -(%sp)
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
9:      movem.l (%sp), %d2-%d4/%a2-%a3
        lea     20(%sp), %sp
        rts

| zero: a3 = a descriptor -> its RAM copy cleared. a1 = the copy's start
| on return; changes d0/d3.
zero:
        movea.l 8(%a3), %a1
        move.l  4(%a3), %d3
        lsr.l   #2, %d3
        beq.s   2f
1:      clr.l   (%a1)+
        subq.l  #1, %d3
        bne.s   1b
2:      movea.l 8(%a3), %a1
        rts

        .balign 4
core_import_ret:
        .long   0
