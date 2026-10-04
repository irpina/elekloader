/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* perform-direct: PERFORM mode without [FUNC] on a Digitakt II (OS 1.17).
 *
 * Stock, [PRESET] opens the PRESET/KIT menu and [FUNC] + [PRESET] toggles
 * PERFORM (Perform Kit). With DIRECT PERFORM ticked (SETTINGS >
 * PERSONALIZE), they swap: [PRESET] alone toggles PERFORM, which is quicker
 * to reach live, and [FUNC] + [PRESET] opens the PRESET/KIT menu.
 *
 * How: core's ev_key gives every key event before the firmware sees it.
 * A key event holds the key at +12 ([PRESET] is 7) and flags at +16: 1
 * pressed, 8 repeat, 0x10 released, and 2 while [FUNC] is held. For
 * [PRESET]'s events this mod flips the FUNC bit and lets the firmware go on,
 * so each combination does what the other one did. The firmware decides by
 * that bit, not by a [FUNC] state of its own (checked in the emulator).
 *
 * The option is a PERSONALIZE row, added from core's ev_personalize, drawn
 * and changed the way the firmware's own checkbox rows are (LED BACKLIGHT):
 * select toggles it, LEFT and RIGHT set it off and on. It is on after every
 * power-on: the firmware's settings store has no place for it.
 */

/* Firmware routines and data, OS 1.17 (mod.json gives no defsym: they are
 * here, next to how each was found). */
typedef void (*blit_t)(void *dst, const void *src, int x, int y, int centre);
typedef void (*invalidate_t)(void *view);
#define BLIT       ((blit_t)0x40114168)        /* the mk1's 0x400c2b88, matched whole */
#define INVALIDATE ((invalidate_t)0x4011b126)  /* View::invalidate, the mk1's 0x400c9a3a */
/* -> two checkbox Bitmaps, 0x1c bytes each: empty, ticked. LED BACKLIGHT's
 * draw callback (0x4009d65c) reads this pointer. */
#define CHECKBOXES (*(char **)0x44f34554)

#define KEY_PRESET 7
#define FLAG_FUNC  2

extern void core_additem(void *menu, const void *row);
extern void pd_label(void);            /* perform_label.s */

static int direct = 1;

int pd_key(void *brain, void *ev)
{
    (void)brain;
    if (direct && *(int *)((char *)ev + 12) == KEY_PRESET)
        *(int *)((char *)ev + 16) ^= FLAG_FUNC;
    return 0;                          /* the firmware handles it, as swapped */
}

/* The row's callbacks get the std::function's storage first: its payload
 * is the menu (core_additem). The menu redraws through its view at
 * menu + 0x38, as from SETTINGS. */
static void redraw(void **fn)
{
    INVALIDATE((char *)*fn + 0x38);
}

static void pd_select(void **fn)
{
    direct = !direct;
    redraw(fn);
}

static void pd_change(void **fn, void *item, int delta)
{
    (void)item;
    if (delta > 0)
        direct = 1;
    else if (delta < 0)
        direct = 0;
    redraw(fn);
}

static void pd_draw(void **fn, void *item, void *dst, int x, int y)
{
    (void)fn; (void)item;
    BLIT(dst, CHECKBOXES + (direct ? 0x1c : 0), x + 11, y, 0);
}

static const void *const row[4] = {
    (const void *)pd_label, (const void *)pd_select,
    (const void *)pd_draw, (const void *)pd_change,
};

void pd_personalize(void *menu)
{
    core_additem(menu, row);
}
