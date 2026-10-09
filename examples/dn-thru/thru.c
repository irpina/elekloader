/* SPDX-License-Identifier: GPL-2.0-or-later */
/* THRU: the smallest exclusive-audio mod for the Digitone mk1 and Digitone Keys (core-dn1 3.2). THRU in
 * the Mod Menu takes the output: the audio inputs go straight to it at knob A's level, and the synths are
 * silent. NO gives the output back. Every other key and knob stays the Digitone's. A template for a mod
 * that wants the whole audio engine (docs/ADAPTING.md, "Exclusive audio"). */
#include "digitone-mk1/core3.h"

#define KEY_NO      14
#define EV_KEY(ev)   (*(uint32_t *)((char *)(ev) + 12))
#define EV_FLAGS(ev) (*(uint32_t *)((char *)(ev) + 16))
#define EV_DELTA(ev) (*(int32_t *)((char *)(ev) + 16))

typedef void (*rect_fn)(void *bmp, int x0, int y0, int x1, int y1, int colour);
typedef void (*text_fn)(void *bmp, const void *font, int x, int y, int maxlen, const char *fmt, ...);

static volatile int32_t thru_level = 100;   /* knob A: 0-127, 100 unity */
static int32_t thru_counts;

/* Interrupt level, every block THRU has the output: 32 frames L,R in, 32 out, Q1.31. */
static void thru_render(int32_t *out, const int32_t *in)
{
    int32_t g = thru_level * 16384 / 100;   /* Q14, up to 1.27 */
    int i;
    for (i = 0; i < 64; i++) {
        int32_t v = (in[i] >> 16) * g;      /* Q15 x Q14: Q29 */
        if (v > 0x1fffffff)
            v = 0x1fffffff;
        else if (v < -0x20000000)
            v = -0x20000000;
        out[i] = v << 2;
    }
}

struct core_audio_owner thru_owner = { 0, thru_render, CORE_AUDIO_MUTE_VOICES };

static void thru_open(void *brain, void *event, int32_t track)
{
    (void)brain, (void)event, (void)track;
    thru_owner.on = 1;                      /* the output is THRU's from the next block */
}

const struct core_menu_item thru_menu = { "THRU", thru_open, 0, 0 };

int thru_key(void *brain, void *ev)
{
    (void)brain;
    if (!thru_owner.on || EV_KEY(ev) != KEY_NO || !(EV_FLAGS(ev) & 1))
        return 0;
    thru_owner.on = 0;                      /* the stock audio, from the next block */
    return 1;
}

int thru_enc(void *brain, void *ev)
{
    int32_t v;
    (void)brain;
    if (!thru_owner.on || EV_KEY(ev) != 1)
        return 0;
    thru_counts += EV_DELTA(ev);            /* 4 counts a detent */
    v = thru_level + thru_counts / 4;
    thru_counts %= 4;
    thru_level = v < 0 ? 0 : v > 127 ? 127 : v;
    return 1;
}

void thru_draw(void *bmp, void *ctrl)
{
    (void)ctrl;
    if (!thru_owner.on)
        return;
    ((rect_fn)fw_fillrect)(bmp, 84, 54, 127, 63, 0);
    ((text_fn)fw_textf)(bmp, (const void *)fw_font5, 87, 57, -1, "THRU %d", (int)thru_level);
    ((rect_fn)fw_fillrect)(bmp, 84, 54, 127, 63, -1);
}
