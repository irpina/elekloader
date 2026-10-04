| SPDX-License-Identifier: GPL-2.0-or-later
| core for the Octatrack, OS 1.40C: the hook bus (core 0.2).
| ColdFire V4 (MCF5445x); assemble with -mcpu=54455.
|
| Each site below calls the handlers mods subscribe to its event, from a
| table the linker builds (docs/ADAPTING.md, "The hook bus"): a list of
| pointers ending in 0. Handlers use the C convention: arguments on the
| stack, d0-d1/a0-a1 free, everything else kept, the result in d0.
|
| The sites are not the ones octabam's modules hook: every byte the
| converted mods of irpina/octabam2elemod v1.0 patch stays theirs, so those
| files link with this core as they did with 0.1. The addresses come from
| mod.json (defsym):
|
|   TICK_NEXT   the sys task's tick step (0x40031970), called for message 5
|   KEYFN       key(code, pressed) (0x40031734), the panel's key dispatch
|   ENCFN       enc(encoder, delta) (0x40031944), the encoder dispatch
|   FRAME_PTR   the long holding the frame the compositor builds (0x400b9710)
|   ISR_FLAG    the long the frame interrupt's tail tests (0x46104d08)

        .section .run, "ax"

| ---- ev_tick: the sys task's tick, 60 times a second ------------------------
| At 0x40061e94 (was: jsr 0x40031970), in the sys loop's case for message
| kind 5, which the 120 Hz timer posts every second tick. The sys task also
| runs ev_key, ev_enc and (nearly always) ev_draw, so their handlers never
| interrupt one another. Handlers: void f(void).
        .globl  core_tick
core_tick:
        move.l  %a2, -(%sp)
        lea     ev_tick, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      movea.l (%sp)+, %a2
        jmp     TICK_NEXT               | the call this replaced, same stack

| ---- ev_draw: over every composed frame -------------------------------------
| At 0x40013cae in the compositor 0x40013abc (was: movea.l 0x400b9710,%a5),
| through core_draw_gate (gate.s), which comes here once .boot has run;
| after every window is drawn into the frame and before the frame is
| compared with the last one sent and the changed bytes go to the LCD. The
| frame is cleared and composed again each time, so what handlers draw shows
| until the next composition. The compositor's d2-d7/a2-a6 are live here.
| Handlers: void f(unsigned char *frame), each over the last.
        .globl  core_draw
core_draw:
        move.l  %a2, -(%sp)
        lea     ev_draw, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  FRAME_PTR, -(%sp)
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a2
        movea.l FRAME_PTR, %a5          | the instruction this replaced
        rts

| ---- ev_key, ev_enc: the panel's keys and encoders --------------------------
| At 0x40061dc8 (was: jsr 0x40031734) and 0x40061e00 (was: jsr 0x40031944),
| the sys loop's cases for message kinds 1 and 2. (sp) = return, 4 the key
| code or encoder, 8 pressed or the delta. Handlers: int f(int, int) -> d0
| nonzero when they took it; then nothing after them sees it, stock included.
        .globl  core_key, core_enc
core_key:
        move.l  %a2, -(%sp)
        lea     ev_key, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     KEYFN                   | the stock path, same stack
1:      rts

core_enc:
        move.l  %a2, -(%sp)
        lea     ev_enc, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     ENCFN
1:      rts

| dispatch: a2 = the table; 12(sp) the first argument, 16(sp) the second
| (after its return address and the caller's saved a2). -> d0 = the first
| nonzero result, or 0.
dispatch:
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  16(%sp), -(%sp)
        move.l  16(%sp), -(%sp)
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        tst.l   %d0
        beq.s   1b
2:      rts

| ---- ev_midi: each MIDI message in -------------------------------------------
| At 0x40005572 in the MIDI thread's loop (was: movea.l (%a2,%d0.l*4),%a0 ;
| jsr (%a0)): the call of the message's handler from the table at a2
| (0x400d6474), d0 = its status >> 4. (sp) = return, 4(sp) = the message
| (status, then its data bytes), 8(sp) = 0. Handlers: int f(const unsigned
| char *msg) -> d0 nonzero when they took it: the firmware's handler is not
| called. Otherwise it is, from the same table, with the same stack.
        .globl  core_midi
core_midi:
        lea     -8(%sp), %sp
        movem.l %d0/%a2, (%sp)          | the handler's index, the table
        lea     ev_midi, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  12(%sp), -(%sp)         | the message
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        tst.l   %d0
        beq.s   1b
        movem.l (%sp), %d0/%a2          | taken
        lea     8(%sp), %sp
        rts
2:      movem.l (%sp), %d0/%a2
        lea     8(%sp), %sp
        movea.l (%a2,%d0.l*4), %a0      | the instructions this replaced
        jmp     (%a0)

| ---- ev_frame: the frame interrupt, every 16 samples ------------------------
| At 0x4000d94e in the frame interrupt 0x4000aad0 (vector 0x41, level 5;
| was: tst.l 0x46104d08), on its normal path after the frame is built and
| before it puts back the interrupted task's EMAC state, so a handler may
| use the EMAC. Every register is restored from the interrupt's frame at
| its end. Handlers: void f(void), at interrupt level: keep them short.
        .globl  core_frame
core_frame:
        lea     ev_frame, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        movea.l %d0, %a0
        jsr     (%a0)
        bra.s   1b
2:      tst.l   ISR_FLAG                | the instruction this replaced: its
        rts                             | flags feed the interrupt's beq
