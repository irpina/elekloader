/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* hello-marker for the Octatrack: the smallest mod that runs code on an
 * Octatrack (MKI or MKII, OS 1.40C).
 *
 * It subscribes to the Octatrack core's ev_draw event (core-ot 0.2, mod.json
 * "subscribe"): after the firmware has composed each frame, and before the
 * bytes that changed go to the LCD, core calls hello_draw(frame), and this
 * sets a 3x3 square in the frame's top-right corner.
 *
 * The frame is 1024 bytes: 128 rows of 8 bytes, one row per screen column x
 * (0 at the left), and in each row the 64 lines y (0 at the top) from its
 * last bit to its first: line y is bit 63 - y, counting from the most
 * significant bit of the row's first byte. The firmware clears and composes
 * the frame again each time, so what a handler draws stays for one frame.
 *
 * Handlers use the C calling convention (docs/ADAPTING.md, "The hook bus"),
 * so plain C functions work. There is no C library.
 */
static void pixel(unsigned char *frame, int x, int y)
{
    int bit = 63 - y;
    frame[x * 8 + (bit >> 3)] |= (unsigned char)(0x80 >> (bit & 7));
}

void hello_draw(unsigned char *frame)
{
    int x, y;
    for (x = 125; x < 128; x++)
        for (y = 0; y < 3; y++)
            pixel(frame, x, y);
}
