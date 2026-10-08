/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 irpina and contributors */
/* machines: machines for the Digitone mk1, on core-dn1 3.1 (docs/ADAPTING.md, "Machines on the Digitone").
 *
 * A machine (digitone-mk1/machines.h) replaces the FM voice of every note its sounds play. A sound's
 * machine is its sound slot 0, which no stock parameter uses: the machine's id << 8, 0 for FM. The voice
 * loads it with the rest of the sound at each note, so a sound lock switches machines per trig.
 *
 * - The sound: each block, core's ev_render_voices hands over the DSP's eight voices before the render
 *   filters them. For a voice whose sound has a machine, the machine renders its block in place of the FM
 *   voice's, and this applies the AMP page's envelope (ATK, DEC, SUS, REL: the voice's slots 66-69) and
 *   the note's velocity: the DSP applies the AMP envelope to FM before its output, so a block written here
 *   has none. ev_voice_on starts a voice's envelope; core's fw_gate_off releases it.
 * - The knobs: a machine track's SYN1 and SYN2 pages show the machine's parameters. Through core's
 *   core_param_override this answers for the SYN parameters while the active track's sound has a machine:
 *   their labels, and UI records (core_param_ui_make) with the machine's value text and a plain knob that
 *   turns as the stock one does. The values stay the stock parameters', in their slots and ranges.
 * - The menu: MACHINES in core-dn1's Mod Menu (hold a track key) opens a grid of FM and the machines in
 *   the build; picking one sets the held track's sound (core_sound_set, so its voices follow). */
#include "digitone-mk1/core3.h"
#include "digitone-mk1/machines.h"
#include "tables.h"

#define VOICES      8
#define SYNTHS      4
#define MACH_SLOT   0               /* the sound slot that holds the machine (id << 8) */
#define S_ATK       66              /* AMP: the voice's slots */
#define S_DEC       67
#define S_SUS       68
#define S_REL       69
#define UREC        84
#define PREC        60

extern const struct dnm_machine *const dn_machines[];      /* this mod's table, ending in 0 */

/* The SYN knobs, A-H of SYN1's first page and of SYN2's: their parameter ids. */
static const uint8_t knob_id[DNM_KNOBS] = {
    107, 108, 109, 110, 111, 112, 113, 114,
    119, 120, 121, 122, 123, 124, 125, 126,
};

static int32_t knob_of(int32_t id)
{
    if (id >= 107 && id <= 114)
        return id - 107;
    if (id >= 119 && id <= 126)
        return id - 119 + 8;
    return -1;
}

static const int32_t *param_rec(int32_t id)
{
    return (const int32_t *)(fw_params + PREC * id);
}

static const struct dnm_machine *find(int32_t id)
{
    const struct dnm_machine *const *p;
    for (p = dn_machines; *p; p++)
        if ((*p)->id == id)
            return *p;
    return 0;
}

int32_t dnm_knob(int32_t voice, int32_t knob)
{
    return FW_VOICE_PARAM(voice, param_rec(knob_id[knob & 15])[1]);
}

void dnm_knob_range(int32_t knob, int32_t *min, int32_t *max)
{
    const int32_t *r = param_rec(knob_id[knob & 15]);
    *min = r[2];
    *max = r[3];
}

uint32_t dnm_phase_inc(int32_t pitch)
{
    int32_t n = pitch >> 16;
    uint32_t f = (uint32_t)pitch & 0xffff, a, b;
    if (n < 0)
        return dnm_inc[0];
    if (n > 127)
        return dnm_inc[128];
    a = dnm_inc[n];
    b = dnm_inc[n + 1];
    return a + ((b - a) >> 8) * (f >> 8);
}

int32_t dnm_sin(uint32_t phase)
{
    uint32_t i = phase >> 24;
    int32_t fr = (phase >> 8) & 0xffff, a = dnm_sin_t[i], b = dnm_sin_t[i + 1];
    return a + (((b - a) * fr) >> 16);
}

/* ---- The voices ------------------------------------------------------------------------------- */
enum { OFF, ATK, DEC, SUS, REL };

static struct {
    struct dnm_voice v;
    int32_t stage;
    int32_t level;                  /* the envelope, Q15 */
} vs[VOICES];

void dnm_voice_on(int32_t voice, int32_t track, void *event)
{
    int32_t vel = ((const int32_t *)event)[4] >> 8;     /* the note event's +0x10: velocity << 8 */
    voice &= VOICES - 1;
    if (vel < 1 || vel > 127)
        vel = 100;
    vs[voice].v.velocity = vel;
    vs[voice].v.track = track;
    vs[voice].v.fresh = 1;
    vs[voice].v.gate = 1;
    vs[voice].stage = ATK;          /* from the level it has: a retrigger does not click */
}

static int32_t amp(int32_t voice, int32_t slot)
{
    int32_t v = FW_VOICE_PARAM(voice, slot) >> 8;
    return v < 0 ? 0 : v > 127 ? 127 : v;
}

/* The block times the envelope (ramped from the last block's level) and the velocity. */
static void envelope(int32_t voice, int32_t *block)
{
    int32_t l0 = vs[voice].level, l1 = l0, sus = amp(voice, S_SUS) * 258, g0, step, i;
    switch (vs[voice].stage) {
    case ATK:
        l1 += dnm_rate[amp(voice, S_ATK)];
        if (l1 >= 32767) {
            l1 = 32767;
            vs[voice].stage = DEC;
        }
        break;
    case DEC:
        l1 -= dnm_rate[amp(voice, S_DEC)];
        if (l1 <= sus) {
            l1 = sus;
            vs[voice].stage = SUS;
        }
        break;
    case SUS:
        l1 = sus;
        break;
    case REL:
        l1 -= dnm_rate[amp(voice, S_REL)];
        if (l1 <= 0) {
            l1 = 0;
            vs[voice].stage = OFF;
        }
        break;
    default:
        l1 = 0;
    }
    if (l1 > 32767)
        l1 = 32767;
    vs[voice].level = l1;
    g0 = l0 * vs[voice].v.velocity / 127;
    step = (l1 * vs[voice].v.velocity / 127 - g0) / 32;
    for (i = 0; i < 32; i++) {
        block[i] = ((block[i] >> 16) * g0) << 1;
        g0 += step;
    }
}

void dnm_render(int32_t *voices)
{
    uint32_t released = fw_gate_off;
    int32_t v, i;
    for (v = 0; v < VOICES; v++) {
        int32_t id = FW_VOICE_PARAM(v, MACH_SLOT) >> 8, *block = voices + 32 * v;
        const struct dnm_machine *m;
        if (id <= 0 || !(m = find(id)))
            continue;                       /* FM, or a machine not in this build: the FM voice */
        if (released & (1u << v)) {
            vs[v].v.gate = 0;
            if (vs[v].stage != OFF)
                vs[v].stage = REL;
        }
        if (vs[v].stage == OFF && vs[v].level == 0 && !(m->flags & DNM_OWN_ENV)) {
            for (i = 0; i < 32; i++)
                block[i] = 0;               /* silent: no FM either */
            continue;
        }
        vs[v].v.pitch = fw_voice_pitch[v];
        m->render(v, block, &vs[v].v);
        vs[v].v.fresh = 0;
        if (!(m->flags & DNM_OWN_ENV))
            envelope(v, block);
    }
}

/* ---- The SYN pages, for the active track's machine --------------------------------------------- */
static int32_t active_machine(void)
{
    int32_t t = fw_active_track;
    uint8_t *kit = fw_kit;
    if (t < 0 || t >= SYNTHS || !kit)
        return 0;
    return FW_SOUND_SLOT(kit, t, MACH_SLOT) >> 8;
}

static uint32_t ui_rec[DNM_KNOBS][UREC / 4];
static int32_t ui_for = -1;                 /* the machine ui_rec was made for */

static void no_value(int32_t value, char *buf)
{
    (void)value;
    buf[0] = 0;
}

/* A knob's record: the stock parameter's turn (its steps suit its range), the machine's graphic and text;
 * a knob the machine leaves unused looks unused. */
static void make_ui(const struct dnm_machine *m)
{
    int32_t k;
    for (k = 0; k < DNM_KNOBS; k++) {
        const struct dnm_knob *kn = &m->knobs[k];
        if (kn->name)
            core_param_ui_make(ui_rec[k], knob_id[k], kn->look, kn->fmt);
        else
            core_param_ui_make(ui_rec[k], knob_id[k], CORE_LOOK_NONE, no_value);
    }
    ui_for = m->id;
}

/* SYN1's and SYN2's second pages (the ratio offsets, the operators' delays, trigs and resets) are FM's
 * alone: on a machine track they look unused. */
static int32_t fm_only(int32_t id)
{
    return (id >= 115 && id <= 118) || (id >= 127 && id <= 133);
}

static uint32_t blank_rec[11][UREC / 4];

static void *dnm_ui(int32_t id)
{
    int32_t k = knob_of(id), mid;
    const struct dnm_machine *m;
    if ((k < 0 && !fm_only(id)) || (mid = active_machine()) <= 0 || !(m = find(mid)))
        return 0;
    if (k < 0) {
        uint32_t *r = blank_rec[id <= 118 ? id - 115 : id - 127 + 4];
        if (!r[0x14 / 4])
            core_param_ui_make(r, id, CORE_LOOK_NONE, no_value);
        return r;
    }
    if (ui_for != mid)
        make_ui(m);
    return ui_rec[k];
}

static const char *dnm_name(int32_t id, int32_t field)
{
    int32_t k = knob_of(id), mid;
    const struct dnm_machine *m;
    if (field != 0x30 || (k < 0 && !fm_only(id)) || (mid = active_machine()) <= 0 || !(m = find(mid)))
        return 0;
    if (k < 0)
        return "";
    return m->knobs[k].name ? m->knobs[k].name : "";
}

const struct core_param_override dnm_override = { dnm_ui, dnm_name };

/* ---- MACHINES in the Mod Menu ------------------------------------------------------------------ */
#define MAX_MACHINES 15

static const uint16_t machines_icon[16] = {     /* a little synth: keys under a wave */
    0x0000, 0x0000, 0x0C30, 0x1248, 0x2184, 0x4002, 0x0000, 0x7FFE,
    0x4922, 0x4922, 0x4922, 0x4922, 0x7FFE, 0x0000, 0x0000, 0x0000,
};
static const uint16_t fm_icon[16] = {           /* two operators, one into the other */
    0x0000, 0x07E0, 0x0420, 0x0420, 0x07E0, 0x0180, 0x0180, 0x0180,
    0x07E0, 0x0420, 0x0420, 0x07E0, 0x0000, 0x0000, 0x0000, 0x0000,
};

static struct core_menu_item items[1 + MAX_MACHINES];
static const struct core_menu_item *list[1 + MAX_MACHINES + 1];

/* A switch sets the track's SYN knobs: the machine's defaults, or FM's (the stock records') for FM. */
static void set_knobs(int32_t track, const struct dnm_machine *m)
{
    int32_t k;
    for (k = 0; k < DNM_KNOBS; k++) {
        const int32_t *r = param_rec(knob_id[k]);
        int32_t v;
        if (m) {
            if (!m->defaults || m->defaults[k] == -1)
                continue;
            v = m->defaults[k];
        } else {
            v = r[4];
        }
        core_sound_set(track, r[1], v);
    }
}

static void machines_pick(void *brain, void *event, int32_t track, int32_t index)
{
    uint8_t *kit = fw_kit;
    const struct dnm_machine *m = index > 0 ? dn_machines[index - 1] : 0;
    int32_t id = m ? m->id : 0;
    (void)brain;
    (void)event;
    if (!kit || track < 0 || track >= SYNTHS)
        return;
    if ((FW_SOUND_SLOT(kit, track, MACH_SLOT) >> 8) != id)
        set_knobs(track, m);
    core_sound_set(track, MACH_SLOT, id << 8);
    ui_for = -1;
}

static void machines_open(void *brain, void *event, int32_t track)
{
    int32_t n = 0, sel = 0, cur = 0;
    const struct dnm_machine *const *p;
    uint8_t *kit = fw_kit;
    (void)brain;
    (void)event;
    if (kit && track >= 0 && track < SYNTHS)
        cur = FW_SOUND_SLOT(kit, track, MACH_SLOT) >> 8;
    items[0].name = "FM";
    items[0].open = 0;
    items[0].tag = CORE_MENU_ICON;
    items[0].icon = fm_icon;
    list[n] = &items[n];
    n++;
    for (p = dn_machines; *p && n <= MAX_MACHINES; p++) {
        items[n].name = (*p)->name;
        items[n].open = 0;
        items[n].tag = (*p)->icon ? CORE_MENU_ICON : 0;
        items[n].icon = (*p)->icon;
        if ((*p)->id == cur)
            sel = n;
        list[n] = &items[n];
        n++;
    }
    list[n] = 0;
    core_menu_open((const void *const *)list, sel, machines_pick);
}

const struct core_menu_item dnm_menu = { "MACHINES", machines_open, CORE_MENU_ICON, machines_icon };
