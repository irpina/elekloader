/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* perform-direct: PERFORM mode without [FUNC] on a Digitakt II (OS 1.17).
 *
 * Stock, [PRESET] opens the PRESET/KIT menu and [FUNC] + [PRESET] toggles
 * PERFORM (Perform Kit). With this mod they swap: [PRESET] alone toggles
 * PERFORM, which is quicker to reach live, and [FUNC] + [PRESET] opens the
 * PRESET/KIT menu.
 *
 * How: core's ev_key gives every key event before the firmware sees it.
 * A key event holds the key at +12 ([PRESET] is 7) and flags at +16: 1
 * pressed, 8 repeat, 0x10 released, and 2 while [FUNC] is held. For
 * [PRESET]'s events this mod flips the FUNC bit and lets the firmware go on,
 * so each combination does what the other one did. The firmware decides by
 * that bit, not by a [FUNC] state of its own.
 */

#define KEY_PRESET 7
#define FLAG_FUNC  2

int pd_key(void *brain, void *ev)
{
    (void)brain;
    if (*(int *)((char *)ev + 12) == KEY_PRESET)
        *(int *)((char *)ev + 16) ^= FLAG_FUNC;
    return 0;                          /* the firmware handles it, as swapped */
}
