/* SPDX-License-Identifier: GPL-2.0-or-later */
/* sine-machine: an SRC machine in C on core 3.0, the template for a machine mod (docs/ADAPTING.md,
 * "Machine pages"). SINE plays a sine at the trig's note and TUNE, which SHAPE folds into brighter waves;
 * the track's filter, envelope, level, LFOs and sends work on it as on a sample.
 *
 * It names no firmware address: the locations are core 3.0's exports (fw_*), and its page is drawn by the
 * machine-pages mod from the description below. So its mod.json's 1.54 port is empty, and it builds for
 * any OS version core 3.0 and machine-pages are built for, unchanged.
 *
 * Machine 120: ids 120-127 are for examples and experiments; a mod you share takes one of its own
 * (docs/ADAPTING.md, "SRC machines"). */
#include "digitakt-mk1/core3.h"

#define SINE_ID     120
#define K_TUNE      0                   /* the SRC page's knobs, A-H: SLICE's parameters */
#define K_SHAPE     2                   /* BR's: its range, 0-127, and its knob as they are */
#define K_LEV       7

/* ---- the sound (ev_render_voices: the render, interrupt level) ----------------------------------- */

static uint32_t phase[8];

/* sin(2 pi ph / 2^32), Q15: a parabola, then its square nudged in (within 0.1 %). */
static int32_t sine(uint32_t ph)
{
    int32_t x = (int32_t)ph >> 16, a = x < 0 ? -x : x, y, z;
    y = (x * (32768 - a)) >> 13;
    z = y < 0 ? -y : y;
    y += (7373 * (((y * z) >> 15) - y)) >> 15;
    return y > 32767 ? 32767 : y < -32767 ? -32767 : y;
}

/* A sine, folded back into range after a gain of 1 + shape / 16. */
static int32_t fold(int32_t y, int32_t shape)
{
    int32_t v = y + ((y * shape) >> 4);
    while (v > 32767 || v < -32767)
        v = v > 0 ? 65534 - v : -65534 - v;
    return v;
}

void sine_render(int32_t *blocks)
{
    int t, i;
    for (t = 0; t < 8; t++) {
        const volatile int16_t *p = &fw_voice_params[53 * t];
        int32_t pitch, shape, lev, gain;
        uint32_t inc;
        if (fw_render_machine[t] != SINE_ID)
            continue;
        if (fw_voice_start & (1u << t))
            phase[t] = 0;
        /* the note and TUNE as the playback takes a sample's: the pitch table at 1 for note 60, TUNE 0 */
        pitch = ((int32_t)p[K_TUNE] - 0x4000) * 256 + fw_voice_note[t] + (3 << 16);
        pitch = pitch < 0 ? 0 : pitch > (87 << 16) ? 87 << 16 : pitch;
        inc = (23410327u >> 13) * (fw_pitch_tab[pitch / 384] >> 16);   /* 261.63 Hz at 48 kHz, times it */
        shape = (p[K_SHAPE] >> 8) & 0x7f;
        lev = (p[K_LEV] >> 8) & 0x7f;
        gain = lev * lev;                                              /* LEV's law, as a sample's: Q14 */
        for (i = 0; i < 32; i++) {
            int32_t v = fold(sine(phase[t]), shape);
            blocks[32 * t + i] = (v * gain) << 2;                       /* Q15 x Q14 -> Q31 */
            phase[t] += inc;
        }
    }
}

/* ---- the page (machine-pages draws it) --------------------------------------------------------- */

static int32_t shape_text(char *buf, int32_t value, int32_t ctx, int32_t machine)
{
    int32_t v = (value >> 8) & 0x7f, n = 0;
    char d[3];
    (void)ctx;
    (void)machine;
    if (!v) {
        buf[0] = 'S'; buf[1] = 'I'; buf[2] = 'N'; buf[3] = 0;          /* 0: a plain sine */
        return 1;
    }
    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    for (v = 0; n; v++)
        buf[v] = d[--n];
    buf[v] = 0;
    return 1;
}

static const struct cm_ui sine_page = {
    .abi = cm_ui_v3,
    .page_from = 3,                                     /* SLICE's page, as every added machine gets */
    .knob = {
        [1] = { .flags = CM_HIDDEN },                   /* PLAY, SAMP, SLICE, LEN and GRID: a sample's */
        [K_SHAPE] = { .name = "SHAP", .lname = "Shape", .fmt = shape_text },
        [3] = { .flags = CM_HIDDEN },
        [4] = { .flags = CM_HIDDEN },
        [5] = { .flags = CM_HIDDEN },
        [6] = { .flags = CM_HIDDEN },
    },
};

/* An 11 x 7 icon, as the stock ones: a word a column, the top row in bit 25, pixels then mask. */
static const uint32_t sine_px[11] = {
    0x10000000, 0x08000000, 0x04000000, 0x04000000, 0x08000000, 0x10000000,
    0x20000000, 0x40000000, 0x40000000, 0x20000000, 0x10000000,
};
static const uint32_t sine_mask[11] = {
    0xfe000000, 0xfe000000, 0xfe000000, 0xfe000000, 0xfe000000, 0xfe000000,
    0xfe000000, 0xfe000000, 0xfe000000, 0xfe000000, 0xfe000000,
};
static const struct {
    const void *vt;
    int32_t width, height, one;
    const uint32_t *px, *mask;
    int32_t zero;
} sine_icon = { fw_bitmap_vt, 11, 7, 1, sine_px, sine_mask, 0 };

/* params 3 and render its own id: SLICE's eight parameters (their defaults, MIDI, the LFOs), and an empty
 * voice window that sine_render fills. */
const struct cm_machine sine_machine = {
    SINE_ID, "SINE", "SINE", &sine_icon, 3, SINE_ID, CM_UI_TAG, &sine_page,
};
