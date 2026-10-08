/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Core 3.0 for the Digitakt mk1, in C: the firmware locations core exports, and the page a machine
 * describes for the machine-pages mod (docs/ADAPTING.md, "Firmware locations" and "Machine pages").
 * The SDK puts this folder on the include path:
 *
 *     #include "digitakt-mk1/core3.h"
 *
 * Every name here is resolved by the linker against the core (and machine-pages) in the build, so a mod
 * that uses only these rebuilds for another OS version without a change. digitakt-mk1/core3.inc has the
 * same for assembly. Functions that return a pointer are declared to return uint32_t: the firmware and
 * core return it in d0, where gcc for m68k looks in a0. */
#ifndef ELEKLOADER_DIGITAKT_MK1_CORE3_H
#define ELEKLOADER_DIGITAKT_MK1_CORE3_H

#include <stdint.h>

/* ---- the render: interrupt level, 1500 blocks a second; keep it short, call nothing ---------------- */
extern int32_t fw_track_blocks[];               /* [32 * t + i]: track t's block, 32 Q31 samples */
extern volatile uint8_t fw_render_machine[];    /* [t]: the machine the track renders as */
extern volatile int16_t fw_voice_params[];      /* [53 * t + k]: the machine's parameters A-H (k 0-7), 8.8 */
extern volatile int32_t fw_voice_note[];        /* [t]: the trig's note, 16.16 (60 << 16 with none) */
extern volatile int16_t fw_voice_vel[];         /* [t]: its velocity, 8.8 */
extern volatile uint32_t fw_voice_start;        /* bit t: track t starts a voice this block */
extern volatile int32_t fw_amp_env[];           /* [3 * t]: the AMP envelope's phase, [3 * t + 1] its level */
extern const uint32_t fw_pitch_tab[];           /* 2^((i - 10752) / 2048), Q29, i = 0-14848 */

/* ---- the UI task --------------------------------------------------------------------------------- */
extern volatile uint32_t fw_active_track;       /* 0-7 */
extern uint8_t *volatile fw_kit;                /* the UI kit: track t's sound at + 0x20 + 0xa2 t */
#define FW_SOUND(kit, t)    ((kit) + 0x20 + 0xa2 * (t))
#define FW_SOUND_MACHINE    0x7e                /* a sound's byte: its machine */
#define FW_SOUND_PARAM(k)   (0x36 + 2 * (k))    /* its word: machine parameter A-H (slot 17 + k), 8.8 */
extern uint32_t fw_slice_layout[];              /* SLICE's SRC page layout: 11 longs, the ids at [2 + k] */
extern void fw_set_param(int32_t value, int32_t track, int32_t slot);   /* a knob's path into the engine */
extern const char fw_bitmap_vt[];               /* a Bitmap's vtable: an icon's first long */
extern void fw_fillrect(void *bmp, int32_t x0, int32_t y0, int32_t x1, int32_t y1, int32_t colour);
extern void fw_framerect(void *bmp, int32_t x0, int32_t y0, int32_t x1, int32_t y1, int32_t colour);
extern int32_t fw_textf(void *bmp, const void *font, int32_t x, int32_t y, int32_t maxlen, const char *fmt, ...);
extern const char fw_font5[];
extern void fw_blit(void *dst, const void *src, int32_t x, int32_t y, int32_t centre);
extern uint32_t fw_op_new(uint32_t size);       /* the firmware's heap; 0 when it is full */

/* ---- SRC machines (core 2.1), and the page a machine describes (core 3.0 + machine-pages) -------- */
#define CM_UI_TAG   0x55493330u                 /* "UI30": a descriptor's tail */

enum {
    CM_HIDDEN     = 1,      /* the knob is blank on the SRC page: it shows and turns nothing */
    CM_RANGE      = 2,      /* min and max replace the stock range */
    CM_DEFAULT    = 4,      /* def replaces the stock default (a switch to the machine, a new sound) */
    CM_NOT_SAMPLE = 8,      /* knob D: turning it changes it, and does not open the sample list */
    CM_DRAW       = 16,     /* draw, not gfx: the machine draws the knob's graphic (a page naming cm_ui_v31) */
};

/* A value's text: write it into buf and return nonzero, or return 0 for the stock text. ctx is 0 for the
 * value under a turning knob (about 5 characters) and 1 for the pop-up (up to 15); value is 8.8. */
typedef int32_t (*cm_fmt)(char *buf, int32_t value, int32_t ctx, int32_t machine);
/* The value the knob's graphic shows, from the one the firmware gives it (whole steps). */
typedef int32_t (*cm_gfx)(int32_t value);
/* With CM_DRAW: draw the knob's graphic into bmp, the page's Bitmap, and return nonzero, or return 0 for the
 * stock graphic. It spans x + 1 to x + 17 and y to y + 16 (y = 0 is the screen's bottom row); value is 8.8,
 * and flag is the firmware's, for a stock drawer it calls. */
typedef int32_t (*cm_draw)(void *bmp, int32_t x, int32_t y, int32_t value, int32_t flag);

struct cm_knob {                    /* 40 bytes; knobs A-H by their place on the page */
    const char *name;               /* +0  its label on the SRC page; 0 for the stock one */
    const char *lname;              /* +4  its long name (the pop-up); 0 for the stock one */
    const char *lfo;                /* +8  its name in the LFO page's DEST box; 0 for name */
    const char *lfo_long;           /* +12 in its DEST list; 0 for lname */
    uint8_t look;                   /* +16 the parameter id whose UI record and graphic it borrows; 0 its own */
    uint8_t flags;                  /* +17 CM_HIDDEN, CM_RANGE, CM_DEFAULT, CM_NOT_SAMPLE */
    uint16_t reserved;              /* +18 0 */
    int32_t min, max, def;          /* +20 8.8, with CM_RANGE and CM_DEFAULT */
    cm_fmt fmt;                     /* +32 its value's text; 0 for the stock one */
    union {
        cm_gfx gfx;                 /* +36 its graphic's value; 0 for the value itself */
        cm_draw draw;               /* +36 with CM_DRAW: its graphic, drawn by the machine */
    };
} __attribute__((aligned(4)));

struct cm_ui {                      /* 336 bytes */
    const void *abi;                /* +0  cm_ui_v3, or cm_ui_v31 for CM_DRAW: links only beside a machine-pages that reads it */
    uint8_t page_from;              /* +4  the stock machine whose SRC page it copies: 0 ONESHOT ... 3 SLICE */
    uint8_t flags;                  /* +5  0 */
    uint16_t reserved;              /* +6  0 */
    const char *group;              /* +8  the LFO page's group for its parameters; 0 for the stock one */
    void (*on_switch)(int32_t track, int32_t from, uint8_t *sound);  /* +12 a track turns to it; 0 none */
    struct cm_knob knob[8];         /* +16 */
} __attribute__((aligned(4)));

struct cm_machine {                 /* what a mod contributes to core_machines points to */
    int32_t id;                     /* +0  4-127, claimed as machine:<id> */
    const char *name, *sname;       /* +4, +8 */
    const void *icon;               /* +12 an 11 x 7 Bitmap, or 0 */
    int32_t params, render;         /* +16, +20 */
    uint32_t tag;                   /* +24 CM_UI_TAG (core 3.0; core 2.1 reads to +20 only) */
    const struct cm_ui *ui;         /* +28 */
} __attribute__((aligned(4)));

extern const char cm_ui_v3[];                       /* machine-pages' marker (cm_ui.abi) */
extern const char cm_ui_v31[];                      /* machine-pages 1.1's: a page with CM_DRAW names it */
extern volatile uint8_t core_track_machine[8];      /* each track's own machine, as the render last took it */
extern uint32_t core_machine(int32_t id);           /* -> its struct cm_machine, or 0 */
extern uint32_t core_machine_ui(int32_t id);        /* core 3.0: -> its struct cm_ui, or 0 */

/* machine-pages' render event: after playback has written every track's block, before the overdrive.
 * Subscribe with order 10-49 to make a track's sound, 50-89 to take or change one already made. */
typedef void (*ev_render_voices_fn)(int32_t *blocks);   /* blocks = fw_track_blocks */

#endif
