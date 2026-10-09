/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiChroma: a Chroma Console-style effects pedal for the Digitone mk1, on core-dn1's core_audio: on the audio
 * inputs with the synths silent while its page is open (exclusive, core-dn1 3.2), or on everything the Digitone
 * plays, staying on (an insert, CORE_AUDIO_INSERT, core-dn1 3.3). Shared by dsp.c (the render, interrupt level)
 * and ui.c (the UI task). */
#ifndef DCHROMA_H
#define DCHROMA_H

#include <stdint.h>
#include "digitone-mk1/core3.h"
#ifndef CORE_AUDIO_INSERT
#define CORE_AUDIO_INSERT       2u      /* core-dn1 3.3's insert */
#endif
extern const uint32_t core_audio_caps;       /* 3.3: CORE_AUDIO_INSERT where the core takes inserts; weak (mod.json), so
                                           0 with core-dn1 3.2, where the source is always the inputs */

typedef int32_t s32;
typedef uint32_t u32;
typedef int16_t s16;
typedef uint16_t u16;
typedef uint8_t u8;

/* The buffers: the region mod.json claims in the profile's bulk area, after DigiCosm's. The OS never clears
 * it, so the UI clears what the render reads before it has written it (the first DH_CLEAR_END bytes). */
#ifndef DH_BULK                                         /* a host build of the DSP for tests sets its own */
#define DH_BULK         0x45B00000u
#endif
#define DH_BULK_END     0x46200000u
#define DH_DIFF_FR      (1u << 17)                      /* Diffusion's line: 2.7 s, stereo s16 */
#define DH_DIFF         ((s16 *)DH_BULK)
#define DH_REV          ((s16 *)(DH_BULK + 0x00080000u)) /* Space: 8 lines, then 8 allpasses */
#define DH_REV_LINE     8192
#define DH_MOVE_FR      8192                            /* Movement's line: 171 ms */
#define DH_MOVE         ((s16 *)(DH_BULK + 0x000A8000u))
#define DH_TEX_FR       16384                           /* Texture's line: 341 ms */
#define DH_TEX          ((s16 *)(DH_BULK + 0x000B0000u))
#define DH_CLEAR_END    (DH_BULK + 0x000C0000u)
#define DH_GEST_N       8192                            /* a gesture: 87 s of a knob at 94 values a second */
#define DH_GEST         ((u8 *)(DH_BULK + 0x000C0000u))
#define DH_CAP_FR       (30u * 48000u)                  /* CAPTURE: 30 s, stereo s16 */
#define DH_CAP          ((s16 *)(DH_BULK + 0x00100000u))

enum { M_CHAR, M_MOVE, M_DIFF, M_TEX, M_COUNT };                   /* the modules */
enum { K_TILT, K_RATE, K_TIME, K_MIX, K_CAMT, K_MAMT, K_DAMT, K_TAMT };      /* the knobs, A-H */
enum { S_SENS, S_MDRIFT, S_DDRIFT, S_OUT, S_CVOL, S_MVOL, S_DVOL, S_TVOL }; /* their secondaries */
enum { FX_DRIVE, FX_SWEETEN, FX_FUZZ, FX_HOWL, FX_SWELL };                   /* Character */
enum { FX_DOUBLER, FX_VIBRATO, FX_PHASER, FX_TREMOLO, FX_PITCH };            /* Movement */
enum { FX_CASCADE, FX_REELS, FX_SPACE, FX_COLLAGE, FX_REVERSE };             /* Diffusion */
enum { FX_FILTER, FX_SQUASH, FX_CASSETTE, FX_BROKEN, FX_INTERFERENCE };      /* Texture */
enum { ST_TILT, ST_LPF, ST_HPF };                                            /* FILTER's styles */
enum { CL_FREE, CL_TEMPO, CL_TAP };                                          /* the clock */
enum { C_EMPTY, C_REC, C_PLAY };                                             /* CAPTURE */
enum { CC_NONE, CC_REC, CC_PLAY, CC_STOP };                                  /* its commands */
enum { G_NONE, G_REC, G_PLAY };                                              /* a knob's gesture */
enum { SRC_INPUTS, SRC_DIGITONE };                                           /* what it processes */

/* What the UI sets and the render reads, and what the render reports. Bytes, so either side writes one
 * without a read-modify-write the other could cut in on. */
struct dh_state {
    volatile u8 knob[8], sec[8];        /* the primary and secondary controls, 0-127 */
    volatile u8 fx[4];                  /* each module's effect, 0-4 */
    volatile u8 on[4];                  /* 1: the module runs; 0: bypassed */
    volatile u8 order;                  /* the modules' order, 0-23 (ch_order) */
    volatile u8 style;                  /* FILTER's style, ST_* */
    volatile u8 croute;                 /* CAPTURE: 0 post-FX, 1 pre-FX */
    volatile u8 level;                  /* the input level (calibration): 0 low .. 3 very high */
    volatile u8 bypass;                 /* 1: the pedal is off */
    volatile u8 trails;                 /* 1: after a bypass the tails ring out */
    volatile u8 clock;                  /* CL_* */
    volatile u8 ccmd;                   /* a CAPTURE command, taken at the next block */
    volatile u8 cstate;                 /* C_*, the render's */
    volatile u8 grec;                   /* 1: GESTURE records the knobs that turn */
    volatile u8 gtouch[8];              /* the UI: 1, the knob turned while recording; the render clears it */
    volatile u8 gkill[8];               /* the UI: 1, delete the knob's gesture; the render clears it */
    volatile u8 gstate[8];              /* G_*, the render's */
    volatile u8 eff[8];                 /* the knobs as the render plays them, gestures and all */
    volatile u8 active;                 /* the render's: 1 while it has sound to make */
    volatile u8 lite;                   /* the render's CPU guard: 1, Space runs lighter */
    volatile u32 tap;                   /* the tapped tempo, BPM x 120 */
    volatile u32 clen;                  /* CAPTURE: its length, frames */
    volatile u32 crec;                  /* frames recorded so far */
    volatile u32 blocks;                /* blocks rendered: the UI's clock, 1500 a second */
    volatile u16 meter[2];              /* the output's peak, 0-32767, decayed by the UI */
    volatile u16 cpu;                   /* DigiChroma's render's share of a block, per mille */
    volatile u16 load;                  /* the whole render's (the Digitone's and DigiChroma's), per mille */
    volatile u8 overload;               /* 1: the guard bypassed the pedal (the UI clears it) */
    volatile u8 source;                 /* SRC_*: the inputs (exclusive) or the Digitone (insert) */
    volatile u8 mono;                   /* 1: input L to both sides (a mono source on one jack) */
};
extern struct dh_state dchroma;
extern struct core_audio_owner dchroma_owner;
extern const u8 ch_order[24][4];

void dchroma_render(int32_t *out, const int32_t *in);
void dchroma_rin(void);                 /* ev_render_in, ev_render_out: the guard's clock */
void dchroma_rout(void);
void dchroma_dsp_reset(void);
u32 dchroma_tempo(void);                /* the clock's tempo, BPM x 120 (0 when free) */

#endif
