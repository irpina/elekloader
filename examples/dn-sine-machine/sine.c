/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* SINE: the smallest machine for the Digitone mk1 (the machines companion, digitone-mk1/machines.h). A
 * sine at the note, folded brighter by FOLD, with a sub-oscillator an octave down. It names no firmware
 * address, so its OS 1.44 port is empty. Its knobs, on its sounds' SYN1 page:
 *   A  OCT   the octave, from ALGO (0-7): -3 to +4
 *   F  FOLD  0-100%, from DTUN (0-127)
 *   G  SUB   0-100%, from FDBK (0-127) */
#include "digitone-mk1/machines.h"

static uint32_t phase[8], sub_phase[8];

static void put_int(char *buf, int32_t v)
{
    char t[8];
    int32_t n = 0;
    if (v < 0) {
        *buf++ = '-';
        v = -v;
    }
    do {
        t[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 7);
    while (n)
        *buf++ = t[--n];
    *buf = 0;
}

static void oct_text(int32_t value, char *buf)
{
    int32_t o = (value >> 8) - 3;
    if (o > 0) {
        *buf++ = '+';
    }
    put_int(buf, o);
}

static void pct_text(int32_t value, char *buf)
{
    int32_t p = (value >> 8) * 100 / 127, n;
    put_int(buf, p);
    for (n = 0; buf[n]; n++)
        ;
    buf[n] = '%';
    buf[n + 1] = 0;
}

static const struct dnm_knob knobs[DNM_KNOBS] = {
    [0] = { "OCT", oct_text, 0 },
    [5] = { "FOLD", pct_text, 0 },
    [6] = { "SUB", pct_text, 0 },
};

static void sine_render(int32_t voice, int32_t *block, const struct dnm_voice *v)
{
    int32_t oct = (dnm_knob(voice, 0) >> 8) - 3, fold = dnm_knob(voice, 5) >> 8;
    int32_t sub = dnm_knob(voice, 6) >> 8, gain = 128 + fold * 3, i;
    uint32_t inc = dnm_phase_inc(v->pitch), p, q;
    inc = oct >= 0 ? inc << oct : inc >> -oct;
    if (v->fresh)
        phase[voice] = sub_phase[voice] = 0;
    p = phase[voice];
    q = sub_phase[voice];
    for (i = 0; i < 32; i++) {
        int32_t s = (dnm_sin(p) * gain) >> 7;          /* Q15, up to ~4x before the fold */
        while (s > 32767 || s < -32767)                 /* fold back at full scale */
            s = s > 0 ? 65534 - s : -65534 - s;
        s = (s * (127 - (sub >> 1)) + dnm_sin(q) * (sub >> 1)) >> 7;
        block[i] = s << 12;                             /* peak DNM_PEAK: as loud as FM at its defaults */
        p += inc;
        q += inc >> 1;
    }
    phase[voice] = p;
    sub_phase[voice] = q;
}

static const uint16_t sine_icon[16] = {
    0x0000, 0x0000, 0x0000, 0x0E00, 0x1100, 0x2080, 0x2080, 0x4041,
    0x4041, 0x0022, 0x0022, 0x0014, 0x0008, 0x0000, 0x0000, 0x0000,
};

const struct dnm_machine sine_machine = { 2, "SINE", sine_icon, knobs, sine_render, 0 };
