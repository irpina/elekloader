/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* hello-marker: the smallest mod that runs code on a Digitakt mk1 (OS 1.53
 * and 1.54) or, built from examples/hello-marker-dt2, a Digitakt II (1.17).
 *
 * It subscribes to core's ev_draw event (mod.json "subscribe"): after the
 * firmware has drawn each frame, core calls hello_draw(bmp, ctrl) with the
 * frame's Bitmap, and this puts a 3x3 white square in its top-right corner.
 *
 * Firmware routines are called at their fixed addresses, through function
 * pointers. Those addresses are absolute: they need no relocation, but each
 * OS version has its own, so mod.json gives them (FILLRECT_AT in "cflags",
 * and again in each of its "ports").
 *
 * Handlers use the C calling convention (docs/FORMAT.md, "The Digitakt mk1
 * hook bus"), so plain C functions work. There is no C library: no printf,
 * no malloc. The firmware's own routines are what you have.
 */
typedef void (*fillrect_t)(void *bmp, int x0, int y0, int x1, int y1, int colour);

/* Bitmap::fillRect(bmp, x0, y0, x1, y1, colour): colour 0 clears, 1 sets,
 * a negative colour inverts. The screen is 128 x 64 and y = 0 is its
 * bottom row. Its address is OS 1.53's 0x400c19a6, 1.54's 0x400c1bce, and
 * the Digitakt II 1.17's 0x401131ae. */
#ifndef FILLRECT_AT
#error "FILLRECT_AT: Bitmap::fillRect's address in the target OS (mod.json cflags)"
#endif
#define FILLRECT ((fillrect_t)FILLRECT_AT)

/* The square's colour: white, or -1 to invert where the corner is already
 * white (the Digitakt II's tempo box). */
#ifndef MARKER_COLOUR
#define MARKER_COLOUR 1
#endif

void hello_draw(void *bmp, void *ctrl)
{
    (void)ctrl;
    FILLRECT(bmp, 125, 61, 127, 63, MARKER_COLOUR);
}
