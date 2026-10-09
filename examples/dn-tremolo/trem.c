/* SPDX-License-Identifier: GPL-2.0-or-later */
/* TREMOLO: the smallest insert-audio mod for the Digitone mk1 and Digitone Keys (core-dn1 3.3). TREMOLO in
 * the Mod Menu turns it on, and again off: a 4 Hz tremolo on everything the Digitone plays (the synths, the
 * inputs as the mixer has them, chorus, delay and reverb), while every key, knob and screen stays the
 * Digitone's. A template for an effect on the Digitone's output (docs/ADAPTING.md, "Insert audio"). */
#include "digitone-mk1/core3.h"

static uint32_t trem_phase;                 /* the LFO, 2^32 a cycle */

/* Interrupt level, every block while it is on: in is what the master stage wrote, 32 frames L,R, Q1.31. */
static void trem_render(int32_t *out, const int32_t *in)
{
    int i;
    for (i = 0; i < 32; i++) {
        int32_t tri = (int32_t)((trem_phase += 357914u) >> 16);   /* 4 Hz at 48 kHz */
        int32_t g;
        tri = tri < 32768 ? tri : 65535 - tri;                      /* a triangle, 0-32767 */
        g = 32767 - (tri >> 1);                                     /* Q15: 1 down to 0.5 */
        out[2 * i] = ((in[2 * i] >> 16) * g) << 1;
        out[2 * i + 1] = ((in[2 * i + 1] >> 16) * g) << 1;
    }
}

struct core_audio_owner trem_owner = { 0, trem_render, CORE_AUDIO_INSERT };

static void trem_open(void *brain, void *event, int32_t track)
{
    (void)brain, (void)event, (void)track;
    trem_owner.on = !trem_owner.on;         /* from the next block */
}

const struct core_menu_item trem_menu = { "TREMOLO", trem_open, 0, 0 };
