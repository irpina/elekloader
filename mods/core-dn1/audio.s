| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.2: exclusive audio (Digitone mk1). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s; the Digitakt's core does not have it.
|
|   VOICES_LOOP  the render's loop over the eight voices' filters
|   VOICES_DONE  just past that loop
|   VMIX         the render's voice mix (the voices' levels, pans and sends)
|   MASTER       the render's master stage: the inputs, chorus, delay,
|                reverb, the master drive, the output and the USB block
|   MODEL_FLAGS  the boot flags: bit 19 set on a Digitone Keys
|   USB_BLOCK    the 12-channel block the render hands on to USB
|
| ---- core_audio: one mod owns the output while it wants to ----------------
| The render (vector 191) runs the voices through their filters, mixes them
| and then calls its master stage (0x40096e14 in 1.43) with the output's
| half of the SSI double buffer, a buffer of the Keys', the half of the input
| ring the codec last filled, and the mixer. Core takes three places: the
| instructions just before the voices' filter loop (0x4009e07e), the call to
| the voice mix (0x4009e0f6) and the call to the master stage (0x4009e146).
|
| A mod contributes a pointer to its owner record to the table core_audio.
| A build may have several; the first one whose on is set has the output:
|   +0 on      nonzero: the mod has the output, from the next block on
|   +4 render  render(int32_t *out, const int32_t *in): in is the block's
|              input, 32 frames L,R, Q1.31 (left first on a Keys too); out
|              is 32 frames L,R, Q1.31, all of which render writes
|   +8 flags   bit 0, CORE_AUDIO_MUTE_VOICES: skip the voices' filters and
|              the voice mix as well
| Each block, before the voices' filters, core takes the first record whose
| on is set. While there is one, the master stage does not run: core hands
| the owner the input and writes what it returns to the output and to the
| USB block's main pair (the effect buses silent, the inputs where the master
| stage puts them), and on a Keys clears the Keys' buffer. With no owner
| every block is stock. render runs at interrupt level, inside the render,
| whose EMAC settings it keeps if it uses the EMAC.

        .equ    MUTE_VOICES, 1
        .equ    KEYS_BIT, 0x00080000

        .section .run, "ax"

| The block's owner: core_audio_cur (0 for none), core_audio_mute.
core_audio_pick:
        lea     core_audio, %a0
1:      move.l  (%a0)+, %d0
        beq.s   2f
        movea.l %d0, %a1
        tst.l   (%a1)                   | on
        beq.s   1b
2:      move.l  %d0, core_audio_cur
        beq.s   3f
        moveq   #MUTE_VOICES, %d0
        and.l   8(%a1), %d0
3:      move.l  %d0, core_audio_mute
        rts

| 0x4009e07e, by jmp: the instructions it replaced, then the voices' filter
| loop, or past it when the owner mutes the voices.
        .globl  core_voices_gate
core_voices_gate:
        move.l  %a2, %d6
        movea.l %a2, %a4
        addi.l  #48, %d6
        lea     12(%sp), %sp
        lea     -12(%sp), %sp
        movem.l %d0/%a0-%a1, (%sp)
        bsr.s   core_audio_pick
        movem.l (%sp), %d0/%a0-%a1
        lea     12(%sp), %sp
        tst.l   core_audio_mute
        bne.s   1f
        jmp     VOICES_LOOP
1:      jmp     VOICES_DONE

| 0x4009e0f6, the voice mix's call: the voice mix, unless the voices are muted.
        .globl  core_render_vmix
core_render_vmix:
        tst.l   core_audio_mute
        bne.s   1f
        jmp     VMIX
1:      rts

| 0x4009e146, the master stage's call: the stock stage, or the owner's.
|   4(sp) the output's half (32 frames L,R, 24-bit), 8(sp) the Keys' buffer's
|   half, 12(sp) the input's half (32 frames, 24-bit), 16(sp) the mixer.
        .globl  core_render_master
core_render_master:
        tst.l   core_audio_cur
        bne.s   1f
        jmp     MASTER
1:      lea     -24(%sp), %sp
        movem.l %d2-%d4/%a2-%a4, (%sp)
        movea.l 36(%sp), %a0            | the input, as the codec wrote it
        lea     core_audio_in, %a1
        move.l  MODEL_FLAGS, %d3
        andi.l  #KEYS_BIT, %d3          | a Keys: its words come right first
        moveq   #32, %d2
2:      move.l  (%a0)+, %d0
        move.l  (%a0)+, %d1
        asl.l   #8, %d0
        asl.l   #8, %d1
        tst.l   %d3
        beq.s   3f
        move.l  %d0, %d4
        move.l  %d1, %d0
        move.l  %d4, %d1
3:      move.l  %d0, (%a1)+
        move.l  %d1, (%a1)+
        subq.l  #1, %d2
        bne.s   2b
        movea.l core_audio_cur, %a2
        pea     core_audio_in
        pea     core_audio_out
        movea.l 4(%a2), %a0
        jsr     (%a0)
        addq.l  #8, %sp
        movea.l 28(%sp), %a0            | the output's half
        lea     core_audio_out, %a1
        lea     USB_BLOCK, %a2
        lea     core_audio_in, %a3
        moveq   #32, %d2
4:      move.l  (%a1)+, %d0
        move.l  (%a1)+, %d1
        move.l  %d0, (%a2)              | USB: the main pair, the four effect
        move.l  %d1, 4(%a2)             | buses silent, the inputs right, left
        clr.l   8(%a2)
        clr.l   12(%a2)
        clr.l   16(%a2)
        clr.l   20(%a2)
        clr.l   24(%a2)
        clr.l   28(%a2)
        clr.l   32(%a2)
        clr.l   36(%a2)
        move.l  4(%a3), 40(%a2)
        move.l  (%a3), 44(%a2)
        addq.l  #8, %a3
        lea     48(%a2), %a2
        asr.l   #8, %d0
        asr.l   #8, %d1
        move.l  %d0, (%a0)+
        move.l  %d1, (%a0)+
        subq.l  #1, %d2
        bne.s   4b
        tst.l   %d3
        beq.s   6f
        movea.l 32(%sp), %a0            | a Keys: its own buffer, silent
        move.l  #256, %d2
5:      clr.l   (%a0)+
        subq.l  #1, %d2
        bne.s   5b
6:      movem.l (%sp), %d2-%d4/%a2-%a4
        lea     24(%sp), %sp
        rts

        .balign 4
core_audio_cur:
        .long   0
core_audio_mute:
        .long   0

        .section .bss
        .balign 4
core_audio_in:
        .skip   256
core_audio_out:
        .skip   256
