/* SPDX-License-Identifier: GPL-2.0-or-later */
/* machine-pages (Digitakt mk1): answers pages.s's sites from the page each added machine describes (core
 * 3.0: its descriptor's tail, struct cm_ui in elekloader/sdk/include/digitakt-mk1/core3.h). A machine with
 * no page, and every stock one, gets the stock code.
 *
 * Whose machine a site asks about, by site:
 * - the SRC page's (layout, labels, values, graphics, UI records, the pop-up, knob D): the machine whose
 *   layout the page asked for last, as the page asks for it with its track's machine before it draws or
 *   turns a knob;
 * - a range: the machine of the sound the parameter object belongs to;
 * - the LFO page's names: the active track's machine.
 * A parameter id is a knob of a machine's page by the stock machine it copies (page_from: its eight ids,
 * 0x6c + 8 page_from on, A-H), or else by its params machine (the ids MIDI, the LFOs and Randomize use). */
#include "src.h"

#define KNOBS       8
#define ID_BASE(p)  (0x6cu + 8u * (uint32_t)(p))
#define PAGES       32                         /* added machines with a page; more get the stock page */
#define LAY_LONGS   11

/* The markers a page's abi names: a machine whose page reads this layout links only beside this mod. 3.1
 * is 3 with knobs that draw their own graphic (CM_DRAW), which machine-pages 1.0 does not read. */
const char cm_ui_v3[] = "machine-pages 3";
const char cm_ui_v31[] = "machine-pages 3.1";

struct page {
    int32_t id;
    const struct cm_ui *ui;
    const struct cm_ui5 *extended;
    uint32_t params;                           /* its params machine */
    uint32_t ready;                            /* lay is copied */
    uint32_t lay[2][LAY_LONGS];
};

static struct page pages[PAGES];
static int npages, found;
static struct page *page_now;                  /* the SRC page's machine, if it has a page */
static char pop[16];                           /* the pop-up's text */
static uint8_t selected[8];

extern const struct cm_machine *const core_machines[];   /* core 2.1's table, 0 at its end */
extern uint32_t mp_stock_layout(int32_t machine);        /* pages.s: the stock layout of machine 0-3 */
extern uint32_t mp_view_knob(void *view, int32_t knob);
extern uint32_t mp_view_track(void *view);
extern void mp_page_changed(void *view, void *event);

/* The machines with a page, read from their descriptors once (the table is the linker's: it never
 * changes), the first time a site or the tick asks. */
static void find(void)
{
    int i;
    found = 1;
    for (i = 0; core_machines[i] && npages < PAGES; i++) {
        const struct cm_machine *d = core_machines[i];
        const struct cm_ui *ui = (const struct cm_ui *)core_machine_ui(d->id);
        if (!ui || (ui->abi != cm_ui_v3 && ui->abi != cm_ui_v31 &&
                    ui->abi != cm_ui_v5) ||
            ui->page_from > 3 || d->id <= 3)
            continue;                          /* no page, or not one this mod reads */
        const struct cm_ui5 *extended = mp_src_for(d->id);
        if (ui->abi == cm_ui_v5 && !extended)
            continue;
        pages[npages].id = d->id;
        pages[npages].ui = ui;
        pages[npages].extended = extended;
        pages[npages].params = (uint32_t)d->params;
        npages++;
    }
}

/* A machine's page; 0 for a stock machine or one without a page. */
static struct page *page_of(uint32_t m)
{
    int i;
    if (m <= 3)
        return 0;
    if (!found)
        find();
    for (i = 0; i < npages; i++)
        if (pages[i].id == (int32_t)m)
            return &pages[i];
    return 0;
}

/* The knob (0-7) a parameter id is on a page, or -1. */
static int knob_of(const struct page *p, uint32_t id)
{
    if (p->extended && id >= 164 && id < 172)
        return 8 + id - 164;
    uint32_t k = id - ID_BASE(p->ui->page_from);
    if (k < KNOBS)
        return (int)k;
    k = id - ID_BASE(p->params);
    return k < KNOBS ? (int)k : -1;
}

static const struct cm_knob *knob(const struct page *p, int k)
{
    return k < 8 ? &p->ui->knob[k] : &p->extended->extra[k - 8];
}

static const struct cm_knob *page_knob(uint32_t id)
{
    int k;
    if (!page_now || (k = knob_of(page_now, id)) < 0)
        return 0;
    return knob(page_now, k);
}

/* ---- the SRC page -------------------------------------------------------------------------------- */

uint32_t mp_layout_track(int32_t m, uint32_t track)
{
    struct page *p = page_of((uint32_t)m);
    int i;
    page_now = p;
    if (!p)
        return 0;
    if (!p->ready) {
        const uint32_t *s = (const uint32_t *)mp_stock_layout(p->ui->page_from);
        int count = p->extended ? p->extended->page_count : 1;
        for (int page = 0; page < count; ++page) {
            for (i = 0; i < LAY_LONGS; i++)
                p->lay[page][i] = s[i];
            for (i = 0; i < KNOBS; i++) {
                int k = p->extended ? p->extended->pages[page].parameter[i] : i;
                if (k == CM_SRC_BLANK || (knob(p, k)->flags & CM_HIDDEN))
                    p->lay[page][2 + i] = 0;
                else if (p->extended)
                    p->lay[page][2 + i] = k < 8 ? ID_BASE(p->params) + k : 164 + k - 8;
            }
        }
        p->ready = 1;
    }
    if (track < 8 && p->extended) {
        if (selected[track] >= p->extended->page_count)
            selected[track] = 0;
        return (uint32_t)p->lay[selected[track]];
    }
    return (uint32_t)p->lay[0];
}

uint32_t mp_layout(int32_t m)
{
    return mp_layout_track(m, fw_active_track);
}

/* Native SRC copy, clear and randomize collect the visible eight controls. */
uint32_t mp_action_layout(uint32_t page, int32_t machine)
{
    uint32_t track = fw_active_track;
    if ((page != 4 && page != 5) || track >= 8)
        return 0;
    if (machine == -2) {                     /* The ID collector has no source object. */
        const uint8_t *kit = fw_kit;
        if (!kit)
            return 0;
        machine = FW_SOUND(kit, track)[FW_SOUND_MACHINE];
    }
    return mp_src_for(machine) ? mp_layout_track(machine, track) : 0;
}

int32_t mp_src_key(void *view, const uint32_t *event)
{
    if (event[3] != 20 || (event[4] & ~4u) != 16)
        return 0;
    uint32_t track = mp_view_track(view);
    if (track >= 8)
        return 0;
    mp_view_knob(view, 0);                 /* Resolve the view's sound, including sound locks. */
    if (!page_now || !page_now->extended)
        return 0;
    selected[track] = (selected[track] + 1) % page_now->extended->page_count;
    mp_page_changed(view, (void *)event);
    return 1;
}

uint32_t mp_src_title(void *view)
{
    uint32_t track = mp_view_track(view);
    mp_view_knob(view, 0);
    if (track >= 8 || !page_now || !page_now->extended)
        return 0;
    return (uint32_t)page_now->extended->pages[selected[track]].title;
}

uint32_t mp_label(uint32_t id, int32_t long_name)
{
    const struct cm_knob *k = page_knob(id);
    if (!k)
        return 0;
    return (uint32_t)(long_name ? k->lname : k->name);
}

int32_t mp_value_text(uint32_t id, int32_t value, char *buf)
{
    const struct cm_knob *k = page_knob(id);
    return k && k->fmt && k->fmt(buf, value, 0, page_now->id);
}

uint32_t mp_pop_text(uint32_t id, int32_t value)
{
    const struct cm_knob *k = page_knob(id);
    if (!k || !k->fmt)
        return 0;
    pop[0] = 0;
    if (!k->fmt(pop, value, 1, page_now->id))
        return 0;
    pop[sizeof pop - 1] = 0;
    return (uint32_t)pop;
}

/* The knob's graphic: a = its arguments from the id on, [id, value, flag, -, bmp, x, y]. -> nonzero when
 * the machine drew it (CM_DRAW); else a holds the borrowed look's id and the graphic's value. With CM_DRAW
 * the slot at +36 is draw, never gfx: on a cm_ui_v3 page (which should name cm_ui_v31) it is not called. */
int32_t mp_knob(int32_t *a)
{
    const struct cm_knob *k = page_knob((uint32_t)a[0]);
    if (!k)
        return 0;
    if (k->flags & CM_DRAW) {
        if (page_now->ui->abi != cm_ui_v3 && k->draw && k->draw((void *)a[4], a[5], a[6], a[1], a[2]))
            return 1;
    } else if (k->gfx)
        a[1] = k->gfx(a[1]);
    if (k->look)
        a[0] = k->look;
    return 0;
}

uint32_t mp_look(uint32_t id)
{
    const struct cm_knob *k = page_knob(id);
    return k && k->look ? k->look : id;
}

int32_t mp_not_sample(void)
{
    return page_now && (page_now->ui->knob[3].flags & CM_NOT_SAMPLE) != 0;
}

/* ---- ranges -------------------------------------------------------------------------------------- */

/* out = {min, max, default}, the stock range; machine: the sound's, or -1. */
void mp_range(uint32_t id, int32_t *out, int32_t machine)
{
    const struct page *p;
    const struct cm_knob *k;
    int i;
    if ((id == 55 || id == 64) && mp_ui5(machine)) {
        out[0] = out[2] = 0;
        out[1] = 53 << 8;
        return;
    }
    if (machine < 0 || !(p = page_of((uint32_t)machine)) || (i = knob_of(p, id)) < 0)
        return;
    k = knob(p, i);
    if (k->flags & CM_RANGE) {
        out[0] = k->min;
        out[1] = k->max;
    }
    if (k->flags & CM_DEFAULT)
        out[2] = k->def;
}

void mp_reset_range(uint32_t id, int32_t *out, int32_t machine)
{
    if (mp_ui5(machine))
        mp_range(id, out, machine);
}

/* ---- the LFO page ---------------------------------------------------------------------------------- */

static const struct page *active_page(void)
{
    uint32_t t = fw_active_track;
    const uint8_t *kit = fw_kit;
    if (t > 7 || !kit)
        return 0;
    return page_of(FW_SOUND(kit, t)[FW_SOUND_MACHINE]);
}

/* A destination's name, for the active track's machine: what 0 the group, 1 the long name, 2 the short
 * one; stock, what the firmware has (0 when it has not read it yet). */
uint32_t mp_lfo(uint32_t id, int32_t what, uint32_t stock)
{
    const struct page *p = active_page();
    const struct cm_knob *k;
    const char *s;
    uint32_t i;
    if (!p)
        return stock;
    i = id - ID_BASE(p->params);
    if (i >= KNOBS) {
        if (!p->extended || id < 164 || id >= 172)
            return stock;
        i = 8 + id - 164;
    }
    if (what == 0)
        return p->ui->group ? (uint32_t)p->ui->group : stock;
    k = knob(p, i);
    s = what == 1 ? (k->lfo_long ? k->lfo_long : k->lname) : (k->lfo ? k->lfo : k->name);
    if (!s && (k->flags & CM_HIDDEN))
        s = what == 1 ? "Unused" : "-";
    return s ? (uint32_t)s : stock;
}

uint32_t mp_lfo52(uint32_t off, int32_t what, uint32_t stock)
{
    return off % 52 ? stock : mp_lfo(off / 52, what, stock);
}

/* ---- a track that turns to a machine with a page (ev_tick, 30 Hz) --------------------------------- */

static const uint8_t *seen_kit;
static uint8_t seen[8];

void mp_tick(void *ctrl)
{
    uint8_t *kit = fw_kit;
    int t;
    (void)ctrl;
    if (!kit)
        return;
    if (kit != seen_kit) {                     /* another kit: taken as it is */
        for (t = 0; t < 8; t++)
            seen[t] = FW_SOUND(kit, t)[FW_SOUND_MACHINE];
        for (t = 0; t < 8; t++)
            selected[t] = 0;
        seen_kit = kit;
        return;
    }
    for (t = 0; t < 8; t++) {
        uint8_t *snd = FW_SOUND(kit, t);
        uint8_t m = snd[FW_SOUND_MACHINE], from = seen[t];
        const struct page *p;
        if (m == from)
            continue;
        seen[t] = m;
        selected[t] = 0;
        p = page_of(m);
        if (p && p->ui->on_switch)
            p->ui->on_switch(t, from, snd);
    }
}
