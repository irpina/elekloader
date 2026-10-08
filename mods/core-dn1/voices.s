| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.1: the voices event (Digitone mk1). ColdFire V4; assemble with
| -mcpu=54455. Beside core.s; the Digitakt's core does not have it.
|
|   VOICE_PREP  the render's call this site makes first
|   FW_VOICES   the render's copy of the DSP's eight voices (fw_voices)
|
| ---- ev_render_voices: each voice's sound, before the render's filters ----
| At 0x4009e078 in the audio render (vector 191): its call to VOICE_PREP
| (0x40098fa4), just before its loop over the eight voices (0x4009e08c). By
| then the DSP's eight voices for this block are in SRAM at 0x80004110: 32
| samples a voice, signed Q1.31, 128 bytes apart (eDMA 47 copied them from
| the shared RAM, started at 0x4009d18c). The loop runs each through its
| voice's multimode filter in place (0x400984b6), and the mixer (0x40096a6c)
| then takes them with the track's level, pan and effect sends. A handler
| may write any voice's block: what it writes is that voice's sound from
| here on, through the filter and the mix. The DSP applies the amp envelope
| before its output: a block written here has none of its own.
|
| Handlers: f(int32_t *voices), voices = fw_voices. Interrupt level, every
| block, inside the render, which has the EMAC set up for its own use: a
| handler that uses the EMAC keeps MACSR as it found it. Every register is
| as the render left it when this returns, as after the call it replaces.
        .section .run, "ax"
        .globl  core_render_voices
core_render_voices:
        move.l  12(%sp), -(%sp)         | the call's three arguments, again
        move.l  12(%sp), -(%sp)
        move.l  12(%sp), -(%sp)
        jsr     VOICE_PREP
        lea     12(%sp), %sp
        lea     -20(%sp), %sp
        movem.l %d0-%d1/%a0-%a2, (%sp)  | its result too, as the call left it
        lea     ev_render_voices, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        pea     FW_VOICES
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movem.l (%sp), %d0-%d1/%a0-%a2
        lea     20(%sp), %sp
        rts
