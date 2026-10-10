/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* track-meters: eight live track meters over every screen, on the Octatrack
 * core's hook bus (core-ot 0.2).
 *
 *   ev_frame (the audio interrupt, every 16 samples): the peak of each
 *     track's block, from the read-back the DSP leaves for the ColdFire:
 *     RB_BASE + bank * 1024 + track * 128 + frame * 8, two 32-bit words (L, R,
 *     24 bits left-justified) a frame, 16 frames, 8 tracks, post-FX and
 *     pre-fader; RB_PREV holds the bank the DSP has finished. TUNER and the
 *     USB audio mods read the same memory in the same interrupt.
 *   ev_tick (60 Hz): each peak becomes a bar that rises at once and falls
 *     one pixel a tick.
 *   ev_draw: the bars, in a dark box in the screen's bottom-right corner.
 *
 * Every mod that draws over the screen subscribes to ev_draw; each draws
 * over the last. Without the bus, drawing over the screen meant patching the
 * compositor's one compose point, which only one mod can own.
 */
typedef unsigned char u8;

#define RB_BASE 0x80003190u
#define RB_PREV 0x800000e4u
#define BAR_MAX 24

static volatile unsigned int peak[8];
static u8 shown[8];

void meters_frame(void)
{
    const unsigned int bank = *(volatile const unsigned int *)RB_PREV & 1;
    const volatile int *rb = (const volatile int *)(RB_BASE + bank * 1024);
    int t, w;
    for (t = 0; t < 8; t++) {
        const volatile int *p = rb + t * 32;   /* 16 frames of (L, R) */
        unsigned int m = peak[t];
        for (w = 0; w < 32; w += 4) {           /* every other frame: L, R */
            unsigned int l = (unsigned int)p[w], r = (unsigned int)p[w + 1];
            if ((int)l < 0)
                l = 0u - l;
            if ((int)r < 0)
                r = 0u - r;
            if (l > m)
                m = l;
            if (r > m)
                m = r;
        }
        peak[t] = m;
    }
}

/* 2 pixels for each 6 dB below full scale, 72 dB on 24 pixels */
static int height(unsigned int p)
{
    int msb = 31, h;
    if (!p)
        return 0;
    while (!(p & 0x80000000u)) {
        p <<= 1;
        msb--;
    }
    h = (msb - 19) * 2 + (int)((p >> 30) & 1);
    return h < 0 ? 0 : h > BAR_MAX ? BAR_MAX : h;
}

void meters_tick(void)
{
    int t;
    for (t = 0; t < 8; t++) {
        unsigned int p = peak[t];
        int h;
        peak[t] = 0;
        h = height(p);
        if (h >= shown[t])
            shown[t] = (u8)h;
        else
            shown[t]--;
    }
}

static void pixel(u8 *f, int x, int y, int on)
{
    int bit = 63 - y;
    u8 m = (u8)(0x80 >> (bit & 7));
    if (on)
        f[x * 8 + (bit >> 3)] |= m;
    else
        f[x * 8 + (bit >> 3)] &= (u8)~m;
}

void meters_draw(u8 *frame)
{
    int t, x, y;
    for (x = 103; x < 128; x++)                 /* a dark box, 25 x 27 */
        for (y = 37; y < 64; y++)
            pixel(frame, x, y, 0);
    for (t = 0; t < 8; t++)
        for (x = 104 + 3 * t; x < 106 + 3 * t; x++)
            for (y = 63; y >= 63 - shown[t]; y--)   /* the bottom row always: the slot */
                pixel(frame, x, y, 1);
}
