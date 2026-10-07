; SPDX-License-Identifier: GPL-2.0-or-later
; DSP TONE: input A becomes a quiet sawtooth, one ramp a frame (16 samples,
; 2,756 Hz), on DSP core 0, from the DSP bus's ev_dsp_rx (mods/dspbus-ot).
;
; ev_dsp_rx runs at the head of every frame, before anything reads the
; current RX block: 16 samples x 4 slots at x:>$202, slot 2 = input A,
; 3 = input B, 0 and 1 = C and D. A handler may use a, x1, r0 and r1 and
; must keep every other register.

tone:
        move    x:>$202,r1              ; r1 = the current RX block
        clr     a
        do      #16,ramp_done
        move    a1,x:(r1+2)             ; slot 2 = input A
        add     #>$010000,a             ; the next step: 0 .. 15/128 of full scale
        lua     (r1+4),r1               ; the next sample's four slots
ramp_done:
        rts
