/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Machines for the Digitone mk1, in C: what a machine mod gives the machines companion
 * (mods/machines-dn1) and what the companion gives it (docs/ADAPTING.md, "Machines on the Digitone").
 * The SDK puts this folder on the include path:
 *
 *     #include "digitone-mk1/machines.h"
 *
 * A machine replaces the FM voice of every note its sounds play. Each audio block the companion calls its
 * render for each voice playing one of its sounds; what it writes is that voice's sound, which the
 * Digitone's multimode filter, mixer and effects then take as they take FM. The companion applies the
 * AMP page's envelope and the note's velocity after it. A machine's parameters are the SYN1 and SYN2
 * knobs of its sounds, relabelled: their values keep their sound slots and their stock ranges, so p-locks,
 * MIDI CC, the LFOs and sound presets work on them as on FM, and FM stays valid if the sound goes back.
 * The machine a sound plays is in its sound slot 0 (the id << 8); 0 is FM. */
#ifndef ELEKLOADER_DIGITONE_MK1_MACHINES_H
#define ELEKLOADER_DIGITONE_MK1_MACHINES_H

#include "digitone-mk1/core3.h"

#define DNM_KNOBS 16                /* SYN1 A-H, then SYN2 A-H */

/* One knob. Its value is the stock parameter's: an 8.8 number within that parameter's range
 * (dnm_knob_range): SYN1 A ALGO 0-7, B-D the ratios (indices), E HARM -26..26, F DTUN 0-127, G FDBK 0-127,
 * H MIX -63..63; SYN2 A-H 0-127. */
struct dnm_knob {
    const char *name;               /* +0  its label (5 characters); 0: unused (blank) on this machine */
    void (*fmt)(int32_t value, char *buf);  /* +4 its value's text from the 8.8 value; 0: the number */
    int32_t look;                   /* +8  the stock id whose knob graphic it borrows; 0 a plain knob (PTIM) */
};

struct dnm_voice {                  /* the companion's account of a voice, for the machine's render */
    int32_t pitch;                  /* +0  its pitch word now: the note << 16, with portamento and the rest */
    int32_t velocity;               /* +4  its note's velocity, 1-127 */
    int32_t fresh;                  /* +8  1 on the first block of a note: start its phases */
    int32_t track;                  /* +12 0-3 */
    int32_t gate;                   /* +16 1 until the note is released */
};

#define DNM_OWN_ENV 1               /* flags: the machine applies its own envelope (no AMP envelope) */

/* How loud to write: a voice that peaks about here is as loud as an FM voice at the stock defaults (a sine
 * peaking at DNM_PEAK is a Q15 sine << 12). The track's level, the AMP page and the mixer follow as for FM. */
#define DNM_PEAK    0x08000000

struct dnm_machine {                /* what a mod contributes to the table dn_machines points to */
    int32_t id;                     /* +0  1-127, claimed as the resource dnmachine:<id> */
    const char *name;               /* +4  its name in the MACHINES menu (14 characters fit) */
    const uint16_t *icon;           /* +8  16 rows of 16 pixels for its tile (bit 15 the left), or 0 */
    const struct dnm_knob *knobs;   /* +12 DNM_KNOBS of them */
    /* +16 32 samples, Q1.31, for one block of a voice playing one of its sounds; block holds the FM voice's
     * on entry. Interrupt level, every block: keep it short (the main CPU also runs the filters and
     * effects). */
    void (*render)(int32_t voice, int32_t *block, const struct dnm_voice *v);
    uint32_t flags;                 /* +20 DNM_OWN_ENV */
    /* +24 what its knobs are set to when a track switches to it (8.8, within each knob's stock range; -1
     * leaves a knob as it is), or 0 for none. A switch back to FM sets the SYN knobs to FM's defaults. */
    const int16_t *defaults;
} __attribute__((aligned(4)));

/* From the companion. */
extern int32_t dnm_knob(int32_t voice, int32_t knob);           /* the voice's knob value, 8.8 */
extern void dnm_knob_range(int32_t knob, int32_t *min, int32_t *max);   /* its stock range, 8.8 */
extern uint32_t dnm_phase_inc(int32_t pitch);                   /* a phase step a sample at 48 kHz */
extern int32_t dnm_sin(uint32_t phase);                         /* sin(2 pi phase / 2^32), Q15 */

#endif
