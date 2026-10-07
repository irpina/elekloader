/* SPDX-License-Identifier: GPL-2.0-or-later */
/* core-dn1 3.0 for the Digitone mk1, in C: the firmware locations core exports, and core-dn1's own
 * tables and calls (docs/ADAPTING.md, "Firmware locations", "Parameter slots", "Mod pages", "Project
 * data" and "The Mod Menu"). The SDK puts this folder on the include path:
 *
 *     #include "digitone-mk1/core3.h"
 *
 * Every fw_ name here is resolved by the linker against the core in the build, so a mod that uses only
 * these rebuilds for another OS version without a change (its port in mod.json is empty). Declaring one
 * makes the mod need core-dn1 3.0: say so with "resources": {"core": "3.0"}. digitone-mk1/core3.inc has
 * the same for assembly. Functions that return a pointer are declared to return uint32_t: the firmware
 * returns it in d0, where gcc for m68k looks in a0. */
#ifndef ELEKLOADER_DIGITONE_MK1_CORE3_H
#define ELEKLOADER_DIGITONE_MK1_CORE3_H

#include <stdint.h>

/* ---- the render: interrupt level, 1500 blocks a second; keep it short --------------------------- */
extern volatile uint32_t fw_voice_pitch[];      /* [v]: voice v's pitch word, the note << 16 (ev_voice_on) */
extern volatile int16_t fw_voice_params[];      /* the render's copy of each voice's sound: */
#define FW_VOICE_PARAM(v, k)  (fw_voice_params[9 + 79 * (v) + (k)])   /* slot k (0-78) of voice v, 8.8 */
extern volatile int32_t fw_voice_len[];         /* [v]: its length left in timeline units, 0 none; the
                                                   render releases the voice when it runs out */
extern volatile uint32_t fw_gate_off;           /* bit v: voice v was released in the last block */
extern volatile uint32_t fw_timeline;           /* 5,400,000 units a 16th (900,000 a 24 PPQN tick) */
extern volatile int32_t fw_transpose[];         /* [0] the transposition, [1 + t] track t's */
extern volatile int32_t fw_lfo_state[];         /* each voice's LFOs, 0x50 bytes a voice: */
#define FW_LFO(v, i)          (fw_lfo_state + 20 * (v) + 10 * (i))    /* LFO i (0, 1) of voice v */
#define FW_LFO_DEST           16                /* [16] its destination slot */
#define FW_LFO_MOD            17                /* [17] its modulation, 8.8 parameter units, signed */

/* ---- the note queue: mask interrupts around these --------------------------------------------- */
extern uint32_t fw_ev_alloc(void);              /* a note event (0x48 bytes), or 0 when the pool is empty */
extern void fw_ev_free(uint32_t *event);        /* and its p-lock list's reference */
extern void fw_ev_queue(uint32_t *event, uint32_t time);    /* at a time on the timeline */
extern uint32_t fw_lock_alloc(void);            /* a p-lock list; no check: test fw_locks_free first */
extern volatile uint32_t fw_locks_free;         /* the free p-lock lists, 0 for none */
extern volatile uint32_t fw_nodes_free;         /* the queue's free times: with none, queueing at a new
                                                   time never returns */

/* ---- the UI task ------------------------------------------------------------------------------ */
extern uint8_t *volatile fw_kit;                /* the active kit: */
#define FW_SOUND_SLOT(kit, t, k)  (*(volatile int16_t *)((kit) + 0x2c + 326 * (t) + 2 * (k)))
extern volatile uint32_t fw_slot_ids[];         /* [k]: sound slot k's parameter id */
extern const char fw_str_amp[];                 /* "Amp", a parameter group's name */
extern const char fw_str_empty[];               /* "", a parameter record's +60 */
extern void fw_fillrect(void *bmp, int32_t x0, int32_t y0, int32_t x1, int32_t y1, int32_t colour);
extern void fw_framerect(void *bmp, int32_t x0, int32_t y0, int32_t x1, int32_t y1, int32_t colour);
extern int32_t fw_textf(void *bmp, const void *font, int32_t x, int32_t y, int32_t maxlen, const char *fmt, ...);
extern const char fw_font5[];
extern void fw_blit(void *dst, const void *src, int32_t x, int32_t y, int32_t centre);
extern uint32_t fw_op_new(uint32_t size);       /* the firmware's heap; 0 when it is full */

/* ---- core-dn1's tables (core 2.1-2.3): what a mod contributes points to one of these ------------ */
struct core_param {                 /* core_params: parameter slots 182-184 */
    int32_t id;                     /* +0  182-184, claimed as param:<id> */
    int32_t group;                  /* +4  the page group: 1 Amp, 2 Filter, ... */
    int32_t slot;                   /* +8  the sound parameter it edits, 0-78 */
    int32_t min, max, def;          /* +12 8.8 */
    int32_t flags;                  /* +24 0 */
    int32_t cc;                     /* +28 MIDI CC (MSB << 16 | LSB), or -1 */
    int32_t r32, r36, r40;          /* +32 -1, -1, 0 */
    const char *name, *group_name, *short_name;     /* +44 */
    void (*format)(int32_t value, char *buf);       /* +56 the value's text */
    const char *empty;              /* +60 fw_str_empty */
    int32_t look;                   /* +64 the stock parameter whose knob it borrows, 0 for a plain one */
} __attribute__((aligned(4)));

struct core_page {                  /* core_pages: pages 27-30 */
    int32_t idx;                    /* +0  27-30, claimed as page:<idx> */
    int32_t after;                  /* +4  the stock page it follows: 9 makes it AMP's third */
    const char *short_title, *title;    /* +8 */
    int32_t ids[8];                 /* +16 the knobs' parameter ids, A-H; 0 an empty box */
    int32_t kind;                   /* +48 9 */
    void *view;                     /* +52 0: core writes it */
    int32_t pos;                    /* +56 core writes it */
} __attribute__((aligned(4)));

struct core_projdata {              /* core_projdata: saved and loaded with the project */
    uint32_t tag;                   /* +0  four characters, claimed as projdata:<tag> */
    uint32_t size;                  /* +4  bytes, a multiple of 4 */
    void *data;                     /* +8  the mod's copy */
    void (*loaded)(int32_t found);  /* +12 after a load; found 0: none, data holds zeros */
} __attribute__((aligned(4)));

#define CORE_MENU_ICON  0x49434F4Eu /* "ICON" (core-dn1 2.3) */
struct core_menu_item {             /* core_menu: the Mod Menu's entries */
    const char *name;               /* +0  its label, 14 characters */
    void (*open)(void *brain, void *event, int32_t track);  /* +4 picked */
    uint32_t tag;                   /* +8  CORE_MENU_ICON when an icon follows (2.3) */
    const uint16_t *icon;           /* +12 -> its icon, 16 rows of 16 pixels, the top row first and
                                       bit 15 the left pixel; 0 for core's own */
} __attribute__((aligned(4)));

/* Open a mod page from a key handler (its key's code: AMP 24, say); 0 when the view was never built. */
extern int32_t core_page_open(void *brain, void *event, int32_t key, void *page);
/* 1 when the page is on screen, with no overlay over it. */
extern int32_t core_page_shown(void *brain, void *page);

/* Core-dn1's own events, beside the hook bus's (docs/ADAPTING.md, "The hook bus"). */
typedef void (*ev_voice_on_fn)(int32_t voice, int32_t track, void *event);  /* in the render */
typedef int32_t (*ev_hold_fn)(void *brain, void *event, int32_t track);     /* nonzero: taken */

#endif
