/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiCosm's UI: its Mod Menu entry, its screen, its keys and knobs, its project data. While it is open it
 * owns the output (dcosm_owner.on) and the screen; NO gives both back.
 *
 *   knobs A-H        ACT REP SHP FLT / MIX TIME SPC LOOP;  FUNC + a knob: GAIN MDEP MRAT RESO / FXVL LSPD
 *                    VERB FADE;  pushing a knob: its default
 *   trig keys 1-11   the engines; 12 HOLD; 13-16 the variation, A-D
 *   T1 the looper: record, play, overdub (held: undo);  T2 stop (held: erase);  T3 reverse;  T4 bypass
 *   YES SETUP, NO back (from the main page: close);  PLAY, STOP, RECORD, TEMPO and LEVEL/DATA stay stock
 *   presets: in SETUP a trig key saves the page as that preset (1-16); FUNC + a trig key recalls one
 *   MIDI: the Microcosm's CCs, on the auto channel (or any, in SETUP), while the page is open */
#pragma GCC optimize ("no-tree-loop-distribute-patterns")
#include "dcosm.h"

#define KEY_FUNC    1
#define KEY_TEMPO   9
#define KEY_RECORD  10
#define KEY_PLAY    11
#define KEY_STOP    12
#define KEY_YES     13
#define KEY_NO      14
#define KEY_UP      15
#define KEY_DOWN    16
#define KEY_LEFT    17
#define KEY_RIGHT   18
#define KEY_STEP1   26
#define KEY_T1      42
#define KEY_PUSH_A  46
#define EV_KEY(ev)   (*(u32 *)((char *)(ev) + 12))
#define EV_FLAGS(ev) (*(u32 *)((char *)(ev) + 16))
#define EV_DELTA(ev) (*(s32 *)((char *)(ev) + 16))
#define COUNTS      4                       /* encoder counts a detent */

typedef void (*rect_fn)(void *bmp, int x0, int y0, int x1, int y1, int colour);
typedef void (*text_fn)(void *bmp, const void *font, int x, int y, int maxlen, const char *fmt, ...);
#define FILLRECT  ((rect_fn)fw_fillrect)
#define FRAMERECT ((rect_fn)fw_framerect)
#define TEXTF     ((text_fn)fw_textf)
#define FONT5     ((const void *)fw_font5)

static const u8 knob_def[8] = { 64, 64, 0, 127, 64, 48, 32, 100 };
static const u8 shift_def[8] = { 64, 0, 40, 0, 100, 64, 0, 30 };
static const char *const knob_lbl[8] = { "ACT", "REP", "SHP", "FLT", "MIX", "TIME", "SPC", "LOOP" };
static const char *const shift_lbl[8] = { "GAIN", "MDEP", "MRAT", "RESO", "FXVL", "LSPD", "VERB", "FADE" };
static const char *const shapes[4] = { "FLAT", "SWEL", "PERC", "ARCH" };
static const char *const times[6] = { "BAR", "1/2", "1/4", "1/8", "1/16", "1/32" };
static const char *const speeds[5] = { "1/4X", "1/2X", "1X", "2X", "4X" };
static const char *const rooms[4] = { "ROOM", "DARK", "HALL", "AMBI" };
static const char *const cfg_lbl[G_COUNT] = { "INPUT", "LOOP ROUTE", "LOOPER ONLY", "QUANTIZE", "BURST",
                                              "HOLD", "LOOP ORDER", "MIDI CC" };
static const char *const cfg_val[G_COUNT][2] = { { "STEREO", "MONO" }, { "POST-FX", "PRE-FX" }, { "OFF", "ON" },
                                                 { "OFF", "ON" }, { "OFF", "ON" }, { "LATCH", "MOMENT" },
                                                 { "REC-PLAY", "REC-DUB" }, { "AUTO CH", "ANY CH" } };

static u8 ui_open, ui_page, ui_func, ui_ready, ui_inited, ui_row;
static u8 ui_msg_ticks, ui_msg_preset, ui_msg_kind;   /* a message for a second: 1 saved, 2 recalled, 3 empty */
static u32 clear_at;                        /* the next address to clear, 0 when nothing is */
static u32 bclear_at;                       /* the overdub layer's clearing, in frames */
static s32 enc_acc[8];

/* ---- project data: the page and sixteen presets, saved with the project ------------------------------
 * 132 bytes: the gap mods share in a project holds 480, and digitables' tables take 328 of it with its
 * header. A preset is the engine, the variation and the eight knobs, 6 bits each (FUNC's knobs and
 * SETUP stay the project's). */
#define NPRESET 16
struct dc_save {
    u8 ver, engine, var, cfg;           /* cfg: a bit a SETUP row (eight rows) */
    u8 knob[8], shift[8];
    u8 preset[NPRESET][7];              /* [0]: engine | var << 4 | 0x80 once saved; [1-6]: the knobs */
} __attribute__((aligned(4)));
static struct dc_save save;
#define SAVE_VER 2

static void defaults(void)
{
    int i;
    for (i = 0; i < 8; i++) {
        dcosm.knob[i] = knob_def[i];
        dcosm.shift[i] = shift_def[i];
    }
    for (i = 0; i < G_COUNT; i++)
        dcosm.cfg[i] = 0;
    dcosm.engine = E_MOSAIC;
    dcosm.var = 0;
}

static void dcosm_loaded(int found)
{
    int i, j;
    if (!found || save.ver != SAVE_VER || save.engine >= E_COUNT || save.var > 3) {
        defaults();
        for (i = 0; i < NPRESET; i++)
            for (j = 0; j < 7; j++)
                save.preset[i][j] = 0;
    } else {
        for (i = 0; i < 8; i++) {
            dcosm.knob[i] = save.knob[i] & 127;
            dcosm.shift[i] = save.shift[i] & 127;
        }
        for (i = 0; i < G_COUNT; i++)
            dcosm.cfg[i] = (save.cfg >> i) & 1;
        dcosm.engine = save.engine;
        dcosm.var = save.var;
    }
    ui_inited = 1;
}

const struct core_projdata dcosm_projdata = { 0x4443534Du /* "DCSM" */, sizeof(struct dc_save), &save,
                                              dcosm_loaded };

static void keep_save(void)                 /* the page into the project's copy (the presets are there) */
{
    int i;
    u8 cfg = 0;
    save.ver = SAVE_VER;
    save.engine = dcosm.engine;
    save.var = dcosm.var;
    for (i = 0; i < 8; i++) {
        save.knob[i] = dcosm.knob[i];
        save.shift[i] = dcosm.shift[i];
    }
    for (i = 0; i < G_COUNT; i++)
        cfg |= (u8)((dcosm.cfg[i] & 1) << i);
    save.cfg = cfg;
}

static void preset_save(int n)
{
    u8 *p = save.preset[n];
    u32 hi = 0, lo = 0;
    int i;
    for (i = 0; i < 4; i++)
        hi = (hi << 6) | (u32)(dcosm.knob[i] >> 1);
    for (i = 4; i < 8; i++)
        lo = (lo << 6) | (u32)(dcosm.knob[i] >> 1);
    p[0] = (u8)(dcosm.engine | dcosm.var << 4 | 0x80);
    p[1] = (u8)(hi >> 16), p[2] = (u8)(hi >> 8), p[3] = (u8)hi;
    p[4] = (u8)(lo >> 16), p[5] = (u8)(lo >> 8), p[6] = (u8)lo;
}

static int preset_recall(int n)             /* -> 0 when the slot is empty */
{
    const u8 *p = save.preset[n];
    u32 hi, lo, v;
    int i;
    if (!(p[0] & 0x80) || (p[0] & 15) >= E_COUNT)
        return 0;
    hi = (u32)p[1] << 16 | (u32)p[2] << 8 | p[3];
    lo = (u32)p[4] << 16 | (u32)p[5] << 8 | p[6];
    for (i = 3; i >= 0; i--, hi >>= 6) {
        v = hi & 63;
        dcosm.knob[i] = (u8)(v == 63 ? 127 : v << 1);    /* 64 stays 64, 127 stays 127 */
    }
    for (i = 7; i >= 4; i--, lo >>= 6) {
        v = lo & 63;
        dcosm.knob[i] = (u8)(v == 63 ? 127 : v << 1);    /* 64 stays 64, 127 stays 127 */
    }
    dcosm.engine = (u8)(p[0] & 15);
    dcosm.var = (u8)((p[0] >> 4) & 3);
    return 1;
}

static void message(int kind, int n)
{
    ui_msg_kind = (u8)kind;
    ui_msg_preset = (u8)(n + 1);
    ui_msg_ticks = 30;
}

/* ---- opening and closing -------------------------------------------------------------------------- */
static void dcosm_open(void *brain, void *ev, int track)
{
    (void)brain, (void)ev, (void)track;
    ui_open = 1;
    ui_page = 0;
    ui_func = 0;
    if (!ui_ready && !clear_at)
        clear_at = DC_BULK;                 /* the first time: clear what the render reads */
}

static void dcosm_close(void)
{
    ui_open = 0;
    dcosm_owner.on = 0;                     /* the stock audio, from the next block */
    dcosm.hold = 0;
}

/* The Mod Menu's DIGICOSM, with its icon: an orb. */
static const u16 dcosm_icon[16] = {
    0x07e0, 0x1818, 0x2004, 0x43c2, 0x4c32, 0x9009, 0x93c9, 0xa5a5,
    0xa5a5, 0x93c9, 0x9009, 0x4c32, 0x43c2, 0x2004, 0x1818, 0x07e0
};
const struct core_menu_item dcosm_menu = { "DIGICOSM", dcosm_open, CORE_MENU_ICON, dcosm_icon };

/* ---- keys ------------------------------------------------------------------------------------------- */
static void set_knob(int i, int func, s32 v)
{
    if (v < 0) v = 0;
    if (v > 127) v = 127;
    if (func)
        dcosm.shift[i] = (u8)v;
    else
        dcosm.knob[i] = (u8)v;
}

int dcosm_key(void *brain, void *ev)
{
    u32 key = EV_KEY(ev), fl = EV_FLAGS(ev);
    int press = (fl & 1) && !(fl & 8), released = (fl & 0x10) != 0;
    (void)brain;
    if (!ui_open)
        return 0;
    if (key == KEY_FUNC) {                  /* down: flags 1 (5 for a double press); up: 0x10, or 0 after
                                               another key went down meanwhile */
        ui_func = (u8)(fl & 1);
        return 1;
    }
    if (fl & 2)                             /* another key's event: FUNC is held */
        ui_func = 1;
    if (key == KEY_PLAY || key == KEY_STOP || key == KEY_TEMPO || key == KEY_RECORD)
        return 0;                           /* the sequencer and its tempo stay the Digitone's */
    if (released) {
        if (key == KEY_STEP1 + 11 && dcosm.cfg[G_HOLDMOM])
            dcosm.hold = 0;
        if (key == KEY_T1 && dcosm.cfg[G_BURST])
            dcosm.lcmd = C_BURST_UP;
        return 1;
    }
    if (!press)
        return 1;                           /* repeats; ev_hold sees the track keys held */
    if (key >= KEY_STEP1 && key < KEY_STEP1 + NPRESET && (ui_page || ui_func)) {
        int n = (int)(key - KEY_STEP1);
        if (ui_page) {                      /* SETUP: save the page as preset n */
            preset_save(n);
            message(1, n);
        } else {                            /* FUNC: recall it */
            message(preset_recall(n) ? 2 : 3, n);
        }
    } else if (key >= KEY_STEP1 && key < KEY_STEP1 + E_COUNT) {
        dcosm.engine = (u8)(key - KEY_STEP1);
    } else if (key == KEY_STEP1 + 11) {
        dcosm.hold = dcosm.cfg[G_HOLDMOM] ? 1 : !dcosm.hold;
    } else if (key >= KEY_STEP1 + 12 && key <= KEY_STEP1 + 15) {
        dcosm.var = (u8)(key - KEY_STEP1 - 12);
    } else if (key == KEY_T1) {
        dcosm.lcmd = dcosm.cfg[G_BURST] ? C_BURST_DOWN : C_T1;
    } else if (key == KEY_T1 + 1) {
        dcosm.lcmd = C_STOP;
    } else if (key == KEY_T1 + 2) {
        dcosm.reverse = !dcosm.reverse;
    } else if (key == KEY_T1 + 3) {
        dcosm.bypass = !dcosm.bypass;
    } else if (key == KEY_YES) {
        ui_page = !ui_page;
    } else if (key == KEY_NO) {
        if (ui_page)
            ui_page = 0;
        else
            dcosm_close();
    } else if (ui_page && (key == KEY_UP || key == KEY_DOWN)) {
        ui_row = (u8)((ui_row + (key == KEY_UP ? G_COUNT - 1 : 1)) % G_COUNT);
    } else if (ui_page && (key == KEY_LEFT || key == KEY_RIGHT)) {
        dcosm.cfg[ui_row] = !dcosm.cfg[ui_row];
        if (ui_row == G_HOLDMOM)
            dcosm.hold = 0;
    } else if (key >= KEY_PUSH_A && key < KEY_PUSH_A + 8) {
        int i = (int)(key - KEY_PUSH_A);
        set_knob(i, ui_func, ui_func ? shift_def[i] : knob_def[i]);
    }
    return 1;
}

/* core-dn1's ev_hold, a track key held on its own: while open, T1 undoes the overdub, T2 erases. */
int dcosm_hold(void *brain, void *ev, int track)
{
    (void)brain, (void)ev;
    if (!ui_open)
        return 0;
    if (track == 0 && !dcosm.cfg[G_BURST])
        dcosm.lcmd = C_UNDO;
    else if (track == 1)
        dcosm.lcmd = C_ERASE;
    return 1;
}

int dcosm_enc(void *brain, void *ev)
{
    u32 e = EV_KEY(ev);
    s32 d;
    (void)brain;
    if (!ui_open || e < 1 || e > 8)
        return 0;                           /* LEVEL/DATA stays the Digitone's */
    enc_acc[e - 1] += EV_DELTA(ev);
    d = enc_acc[e - 1] / COUNTS;
    enc_acc[e - 1] -= d * COUNTS;
    if (d)
        set_knob((int)e - 1, ui_func, (ui_func ? dcosm.shift[e - 1] : dcosm.knob[e - 1]) + d);
    return 1;
}

/* ---- MIDI: the Microcosm's CC map (core-dn1 3.2's ev_midi_cc, the MIDI task) -------------------------------
 * While the page is open, the CCs below are DigiCosm's when they come on the auto channel (SETUP's MIDI CC:
 * ANY CH, on a track's channel too): the Digitone does not apply them. Every other CC, and every CC while
 * the page is closed, goes on to the Digitone. A switch is on from 64; a looper CC acts from 64. CC 5 and
 * CC 18 take the Microcosm's steps, 0-5: 1/4, 1/2, TAP, 2x, 4x, 8x (and anything above as 8x). Its six
 * subdivisions are DigiCosm's six TIME steps, a bar down to 1/32; its loop speeds are DigiCosm's five, 8x
 * as 4x. */
static const u8 cc_knob[8] = { K_ACT, K_SHP, K_FLT, K_MIX, K_TIME, K_REP, K_SPC, K_LOOP };          /* CC 6-13 */
static const u8 cc_shift[8] = { S_MRATE, S_RESO, S_FXVOL, S_LSPEED, S_LSPEED, S_MDEP, S_VERB, S_FADE }; /* 14-21 */
static const u8 cc_cfg[4] = { G_PRE, G_ONLY, G_BURST, G_QUANT };                                    /* 24-27 */
static const u8 cc_time[6] = { 10, 32, 53, 74, 96, 117 };       /* CC 5: the middle of each TIME step */
static const u8 cc_lspeed[6] = { 12, 38, 64, 89, 115, 115 };    /* CC 18: of each LSPD step */

int dcosm_cc(int track, int cc, int value, int flags)
{
    int on = value >= 64, s = dcosm.lstate;
    (void)track;
    if (!ui_open || !ui_ready || (!(flags & CORE_MIDI_CC_AUTO) && !dcosm.cfg[G_MIDI]))
        return 0;
    if (value < 0 || value > 127)
        return 0;
    if (cc == 5) {                              /* Subdivision, stepped */
        dcosm.knob[K_TIME] = cc_time[value < 5 ? value : 5];
    } else if (cc == 18) {                      /* Loop Speed, stepped */
        dcosm.shift[S_LSPEED] = cc_lspeed[value < 5 ? value : 5];
    } else if (cc >= 6 && cc <= 13) {
        dcosm.knob[cc_knob[cc - 6]] = (u8)value;
    } else if (cc >= 14 && cc <= 21) {          /* 17 is Loop Speed, 0-127 */
        dcosm.shift[cc_shift[cc - 14]] = (u8)value;
    } else if (cc == 23 || cc == 47) {          /* Reverse */
        dcosm.reverse = (u8)on;
    } else if (cc >= 24 && cc <= 27) {          /* the looper's settings */
        dcosm.cfg[cc_cfg[cc - 24]] = (u8)on;
    } else if (cc >= 28 && cc <= 35 && cc != 32 && cc != 33) {
        if (!on)
            return 1;
        if (cc == 28)                           /* Record: start; close; or a new take */
            dcosm.lcmd = s == L_EMPTY || s == L_REC ? C_T1 : C_BURST_DOWN;
        else if (cc == 29)                      /* Play */
            dcosm.lcmd = s == L_REC ? C_BURST_UP : s == L_STOP || s == L_DUB ? C_T1 : C_NONE;
        else if (cc == 30)                      /* Overdub, on and off */
            dcosm.lcmd = s == L_PLAY || s == L_DUB ? C_T1 : C_NONE;
        else if (cc == 31)
            dcosm.lcmd = C_STOP;
        else if (cc == 34)
            dcosm.lcmd = C_ERASE;
        else
            dcosm.lcmd = C_UNDO;
    } else if (cc == 48) {                      /* Hold */
        dcosm.hold = (u8)on;
    } else if (cc == 102) {                     /* Bypass: below 64 bypassed */
        dcosm.bypass = (u8)!on;
    } else if (cc == 22 || cc == 45 || cc == 46 || cc == 93) {
        /* the Microcosm's looper on/off, copy preset, save preset and tap tempo: nothing to do here (the
         * looper is always on, presets are saved from SETUP, the tempo is the Digitone's), but taken, so
         * the Digitone does not apply them to the active track meanwhile */
    } else {
        return 0;
    }
    return 1;
}

/* ---- the UI task: clearing, the owner, redraws ---------------------------------------------------------- */
void dcosm_tick(void *ctrl)
{
    if (!ui_inited) {                       /* no project load reached us */
        defaults();
        ui_inited = 1;
    }
    if (clear_at) {                         /* 256 KB a tick */
        u32 *p = (u32 *)clear_at, *end = p + 65536;
        if ((u32)end > DC_CLEAR_END)
            end = (u32 *)DC_CLEAR_END;
        while (p < end)
            *p++ = 0;
        clear_at = (u32)end >= DC_CLEAR_END ? 0 : (u32)end;
        if (!clear_at) {
            dcosm_dsp_reset();
            dcosm.bvalid = 1;
            ui_ready = 1;
        }
    }
    if (dcosm.lclear_len) {                 /* undo: the overdub layer, 512 KB a tick */
        u32 *p = (u32 *)(DC_LOOPB) + bclear_at, *end = (u32 *)(DC_LOOPB) + dcosm.lclear_len;
        if (end > p + 131072)
            end = p + 131072;
        while (p < end)
            *p++ = 0;
        bclear_at = (u32)(end - (u32 *)DC_LOOPB);
        if (bclear_at >= dcosm.lclear_len) {
            bclear_at = 0;
            dcosm.lclear_len = 0;
            dcosm.bvalid = 1;
        }
    }
    dcosm_owner.on = ui_open && ui_ready;
    dcosm.meter[0] = (u16)(dcosm.meter[0] - (dcosm.meter[0] >> 3));
    dcosm.meter[1] = (u16)(dcosm.meter[1] - (dcosm.meter[1] >> 3));
    keep_save();
    if (ui_msg_ticks)
        ui_msg_ticks--;
    if (ui_open)
        *((unsigned char *)ctrl + 0x20) = 1;
}

/* ---- the screen: 128 x 64, y = 0 the bottom row ------------------------------------------------------ */
static void value_text(void *bmp, int x, int y, int i, int func)
{
    int v = func ? dcosm.shift[i] : dcosm.knob[i];
    if (!func) {
        if (i == K_SHP)
            TEXTF(bmp, FONT5, x, y, -1, "%s", shapes[v >> 5]);
        else if (i == K_FLT && v == 127)
            TEXTF(bmp, FONT5, x, y, -1, "OPEN");
        else if (i == K_TIME)
            TEXTF(bmp, FONT5, x, y, -1, "%s", times[(v * 6) >> 7]);
        else
            TEXTF(bmp, FONT5, x, y, -1, "%d", v);
        return;
    }
    if (i == S_LSPEED) {
        TEXTF(bmp, FONT5, x, y, -1, "%s", speeds[(v * 5) >> 7]);
    } else if (i == S_VERB) {
        TEXTF(bmp, FONT5, x, y, -1, "%s", rooms[(v * 4) >> 7]);
    } else if (i == S_GAIN) {
        int t = (v - 64) * 3;                   /* tenths of a dB */
        if (!v)
            TEXTF(bmp, FONT5, x, y, -1, "MUTE");
        else
            TEXTF(bmp, FONT5, x, y, -1, "%c%d.%d", t < 0 ? '-' : '+', (t < 0 ? -t : t) / 10, (t < 0 ? -t : t) % 10);
    } else if (i == S_FADE) {
        TEXTF(bmp, FONT5, x, y, -1, "%d.%dS", v / 16, (v % 16) * 10 / 16);
    } else {
        TEXTF(bmp, FONT5, x, y, -1, "%d", v);
    }
}

static void draw_setup(void *bmp)
{
    int i;
    TEXTF(bmp, FONT5, 1, 57, -1, "SETUP   TRIG: SAVE");
    FILLRECT(bmp, 0, 54, 127, 54, 1);
    for (i = 0; i < G_COUNT; i++) {
        int y = 47 - 6 * i;
        TEXTF(bmp, FONT5, 3, y, -1, "%s", cfg_lbl[i]);
        TEXTF(bmp, FONT5, 76, y, -1, "%s", cfg_val[i][dcosm.cfg[i] & 1]);
        if (i == ui_row)
            FILLRECT(bmp, 1, y - 1, 126, y + 4, -1);
    }
}

void dcosm_draw(void *bmp, void *ctrl)
{
    int i, t = fw_tempo, s = dcosm.lstate;
    (void)ctrl;
    if (!ui_open)
        return;
    FILLRECT(bmp, 0, 0, 127, 63, 0);
    if (!ui_ready) {
        TEXTF(bmp, FONT5, 30, 30, -1, "DIGICOSM...");
        return;
    }
    if (ui_page) {
        draw_setup(bmp);
        return;
    }
    TEXTF(bmp, FONT5, 2, 57, -1, "%s %c", dcosm_engine_names[dcosm.engine], 'A' + dcosm.var);
    FILLRECT(bmp, 0, 56, 56, 63, -1);
    TEXTF(bmp, FONT5, 60, 57, -1, "%d.%d", t / 120, (t % 120) / 12);
    if (ui_msg_ticks)
        TEXTF(bmp, FONT5, 88, 57, -1, "%s P%d", ui_msg_kind == 1 ? "SAVED" : ui_msg_kind == 2 ? "LOAD" : "EMPTY",
              ui_msg_preset);
    else if (s == L_REC)
        TEXTF(bmp, FONT5, 88, 57, -1, "REC %d.%d", dcosm.lrec / 48000, (dcosm.lrec % 48000) / 4800);
    else if (s == L_EMPTY)
        TEXTF(bmp, FONT5, 88, 57, -1, "LOOP --");
    else
        TEXTF(bmp, FONT5, 88, 57, -1, "%s %d.%d", s == L_PLAY ? "PLAY" : s == L_DUB ? "DUB" : "STOP",
              dcosm.llen / 48000, (dcosm.llen % 48000) / 4800);
    FILLRECT(bmp, 0, 54, 127, 54, 1);
    for (i = 0; i < 8; i++) {
        int x = 32 * (i & 3) + 2, yl = (i < 4) ? 46 : 26, v = ui_func ? dcosm.shift[i] : dcosm.knob[i];
        TEXTF(bmp, FONT5, x, yl, -1, "%s", ui_func ? shift_lbl[i] : knob_lbl[i]);
        value_text(bmp, x, yl - 8, i, ui_func);
        FILLRECT(bmp, x, yl - 11, x + 26, yl - 11, 1);
        FILLRECT(bmp, x, yl - 12, x + (v * 26) / 127, yl - 10, 1);
    }
    FILLRECT(bmp, 0, 9, 127, 9, 1);
    TEXTF(bmp, FONT5, 1, 1, -1, "IN");
    FILLRECT(bmp, 12, 5, 12 + (dcosm.meter[0] * 30) / 32767, 6, 1);
    FILLRECT(bmp, 12, 2, 12 + (dcosm.meter[1] * 30) / 32767, 3, 1);
    if (dcosm.hold)
        TEXTF(bmp, FONT5, 48, 1, -1, "HOLD");
    if (dcosm.reverse)
        TEXTF(bmp, FONT5, 70, 1, -1, "REV");
    if (dcosm.bypass)
        TEXTF(bmp, FONT5, 87, 1, -1, "BYP");
    TEXTF(bmp, FONT5, 104, 1, -1, "C%d", dcosm.cpu / 10);
}
