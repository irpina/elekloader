/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* cc-who: which mod took that CC? A demo of the Octatrack core's hook bus
 * (core-ot 0.2).
 *
 * Every MIDI message the Octatrack receives goes through core's ev_midi
 * event: to each subscriber in turn, in "order", until one takes it, then to
 * the firmware's own handler if none did. This mod subscribes twice:
 *   ccwho_first (order 10), before the shipped mods: it notes each CC;
 *   ccwho_last  (order 90), after them: it runs only for a CC no mod took.
 * So for each CC it knows whether a mod in between kept it (CC MAP keeps
 * CC 62-73, for the FX page-2 knobs) or the Octatrack got it, and shows
 * that for a moment in the screen's top-right corner (ev_draw, timed by
 * ev_tick). It takes nothing itself.
 *
 * Without the bus, CC MAP repoints the firmware's one CC handler (the
 * dispatch entry at 0x400d64a0) at its own code. A mod that wanted to see
 * CCs the same way would patch the same four bytes, and the loader refuses
 * the pair; seeing what CC MAP decided would mean wrapping CC MAP itself.
 *
 * The frame is 1024 bytes: 128 rows of 8 bytes, one per screen column x (0
 * at the left), line y (0 at the top) at bit 63 - y of the row, counting from
 * its first byte's most significant bit. 1 is a lit pixel.
 */
typedef unsigned char u8;

#define SHOW_TICKS 90                   /* ev_tick is 60 Hz: 1.5 s */

static volatile unsigned int ticks, shown_at, serial, passed;
static volatile u8 cc_num, cc_val;

static int is_cc(const u8 *msg)
{
    return (msg[0] & 0xf0) == 0xb0;
}

int ccwho_first(const u8 *msg)
{
    if (is_cc(msg)) {
        cc_num = msg[1];
        cc_val = msg[2];
        serial++;
        shown_at = ticks;
    }
    return 0;                           /* pass it on */
}

int ccwho_last(const u8 *msg)
{
    if (is_cc(msg) && msg[1] == cc_num)
        passed = serial;                /* no mod took it: the Octatrack gets it */
    return 0;
}

void ccwho_tick(void)
{
    ticks++;
}

/* 3 x 5 glyphs, a row a nibble's top three bits, top row first */
static const struct { char c; unsigned short rows; } font[] = {
    {'0', 075557}, {'1', 026227}, {'2', 071747}, {'3', 071717}, {'4', 055711},
    {'5', 074717}, {'6', 074757}, {'7', 071122}, {'8', 075757}, {'9', 075717},
    {'A', 025755}, {'C', 074447}, {'D', 065556}, {'M', 057755}, {'O', 075557},
    {'P', 065644}, {'T', 072222}, {'=', 007070}, {'>', 042124},
};

static void pixel(u8 *f, int x, int y, int on)
{
    int bit = 63 - y;
    u8 m = (u8)(0x80 >> (bit & 7));
    if (on)
        f[x * 8 + (bit >> 3)] |= m;
    else
        f[x * 8 + (bit >> 3)] &= (u8)~m;
}

static int text(u8 *f, int x, int y, const char *s)    /* dark on the lit box */
{
    for (; *s; s++, x += 4) {
        unsigned int i, r, c;
        for (i = 0; i < sizeof font / sizeof font[0]; i++)
            if (font[i].c == *s)
                break;
        if (i == sizeof font / sizeof font[0])
            continue;                   /* a space */
        for (r = 0; r < 5; r++)
            for (c = 0; c < 3; c++)
                if ((font[i].rows >> (3 * (4 - r) + (2 - c))) & 1)
                    pixel(f, x + (int)c, y + (int)r, 0);
    }
    return x;
}

static char *number(char *p, unsigned int v)
{
    char d[4];
    int n = 0;
    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 3);
    while (n)
        *p++ = d[--n];
    return p;
}

void ccwho_draw(u8 *frame)
{
    char top[12], *p = top;
    const char *who;
    int x, y;
    if (!serial || ticks - shown_at >= SHOW_TICKS)
        return;
    *p++ = 'C';
    *p++ = 'C';
    p = number(p, cc_num);
    *p++ = '=';
    p = number(p, cc_val);
    *p = 0;
    if (passed == serial)
        who = "> OT";
    else if (cc_num >= 62 && cc_num <= 73)
        who = "> CC MAP";
    else
        who = "> A MOD";
    for (x = 86; x < 128; x++)          /* a lit box, 42 x 14, top right: */
        for (y = 0; y < 14; y++)        /* room for CC127=127 */
            pixel(frame, x, y, 1);
    text(frame, 88, 2, top);
    text(frame, 88, 8, who);
}
