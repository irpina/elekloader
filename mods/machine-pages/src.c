/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "src.h"
#include <stddef.h>

_Static_assert(sizeof(struct cm_ui) == 336, "legacy UI layout");
_Static_assert(sizeof(struct cm_src_page) == 12, "SRC page layout");
_Static_assert(sizeof(struct cm_ui32) == 624, "extra-value UI layout");
_Static_assert(offsetof(struct cm_ui32, extra) == 336, "extra parameters");
_Static_assert(offsetof(struct cm_ui32, page_count) == 616, "page count");
_Static_assert(offsetof(struct cm_ui32, pages) == 620, "pages pointer");

const char cm_ui_v32[] = "machine-pages 3.2";
extern const struct cm_machine *const core_machines[];
extern const uint32_t SAVE_MAP[];
extern uint32_t mp_native_save(uint8_t *, const uint8_t *, int32_t);
extern uint32_t mp_native_load(uint8_t *, const uint8_t *);
extern uint32_t mp_native_upgrade(uint8_t *, uint8_t *, int32_t);
static const struct cm_ui32 *extended[128];
static int ready;

static int valid(const struct cm_machine *m, const struct cm_ui32 *u)
{
    /* shortcut: the POC uses SLICE's bank; add other banks when a consumer needs them. */
    if (m->id < 4 || m->id > 127 || m->params != 3 ||
        u->base.page_from > 3 || u->base.flags || u->base.reserved ||
        u->page_count < 1 || u->page_count > 2 || !u->pages ||
        u->reserved[0] || u->reserved[1] || u->reserved[2])
        return 0;
    for (int k = 0; k < CM_EXTRAS; ++k) {
        const struct cm_knob *p = &u->extra[k];
        if (!p->look || p->look >= 164 || p->reserved || (p->flags & ~31) ||
            (p->flags & (CM_RANGE | CM_DEFAULT)) != (CM_RANGE | CM_DEFAULT) ||
            p->min != 0 || p->max != 0x7f00 || p->def < 0 || p->def > 0x7f00)
            return 0;
    }
    for (int page = 0; page < u->page_count; ++page) {
        if (!u->pages[page].title)
            return 0;
        for (int k = 0; k < 8; ++k)
            if (u->pages[page].parameter[k] != CM_SRC_BLANK &&
                u->pages[page].parameter[k] >= 8 + CM_EXTRAS)
                return 0;
    }
    return 1;
}

void mp_src_init(void)
{
    if (ready)
        return;
    ready = 1;
    int count = 0;
    for (int i = 0; core_machines[i]; ++i) {
        const struct cm_machine *m = core_machines[i];
        if (m->tag != CM_UI_TAG || !m->ui)
            continue;
        if (m->id > 3 && m->ui->page_from <= 3 &&
            (m->ui->abi == cm_ui_v3 || m->ui->abi == cm_ui_v31)) {
            ++count;
            continue;
        }
        const struct cm_ui32 *u = (const struct cm_ui32 *)m->ui;
        if (m->ui->abi == cm_ui_v32 && count < 32 && valid(m, u)) {
            extended[m->id] = u;
            ++count;
        }
    }
}

const struct cm_ui32 *mp_src_for(int32_t machine)
{
    if (!ready)
        mp_src_init();
    return machine >= 4 && machine < 128 ? extended[machine] : 0;
}

uint32_t mp_ui32(int32_t machine)
{
    return (uint32_t)mp_src_for(machine);
}

int32_t cm_src_value(int32_t track, int32_t parameter)
{
    if ((uint32_t)track >= 8 || (uint32_t)parameter >= 8 + CM_EXTRAS)
        return 0;
    if (parameter < 8)
        return fw_voice_params[53 * track + parameter];
    if (!mp_src_for(core_track_machine[track]))
        return 0;
    return fw_voice_params[53 * track + MP_EXTRA_SLOT(parameter - 8) - 17];  /* fw_voice_params is slot 17 */
}

static uint16_t word(const uint8_t *p)
{
    return ((uint16_t)p[0] << 8) | p[1];
}

static uint32_t longword(const uint8_t *p)
{
    return ((uint32_t)word(p) << 16) | word(p + 2);
}

static void put(uint8_t *p, uint16_t value)
{
    p[0] = value >> 8;
    p[1] = value;
}

static int32_t extra_value(const struct cm_ui32 *u, const uint8_t *sound, int k)
{
    int32_t value = (int16_t)word(sound + 20 + 2 * MP_EXTRA_SLOT(k));
    return value < 0 || value > 0x7f00 ? u->extra[k].def : value;
}

/* Version 4 keeps the native 160-byte record. Its payload, bytes 28-123 and 127-131 (124-126 stay
 * the native machine bytes), is a bit stream: slots 1-45 (the SRC slots 17-24 16 bits, the rest 15),
 * the extras (15 bits) and slot 0 raw (16 bits: the machine's id) = 804 bits; the last byte's low four
 * bits stay zero. */
static int payload_offset(int bit)
{
    int byte = bit >> 3;
    return byte < 96 ? 28 + byte : 31 + byte;
}

static void pack(uint8_t *saved, int *bit, uint16_t value, int width)
{
    while (width--) {
        saved[payload_offset(*bit)] |= ((value >> width) & 1) << (7 - (*bit & 7));
        ++*bit;
    }
}

static uint16_t unpack(const uint8_t *saved, int *bit, int width)
{
    uint16_t value = 0;
    while (width--) {
        value = (value << 1) | ((saved[payload_offset(*bit)] >> (7 - (*bit & 7))) & 1);
        ++*bit;
    }
    return value;
}

static int packed_sound(const uint8_t *saved)
{
    return saved && longword(saved) == 0xbeefbace && longword(saved + 4) == 4 &&
        longword(saved + 156) == 0xbacef00c && !(saved[131] & 15) && mp_ui32(saved[124]);
}

uint32_t mp_sound_save(uint8_t *saved, const uint8_t *sound, int32_t mode)
{
    uint32_t result = mp_native_save(saved, sound, mode);
    if (!(result & 255))
        return result;
    const struct cm_ui32 *u = mp_src_for(sound[126]);
    if (!u)
        return result;
    for (int k = 28; k < 124; ++k)
        saved[k] = 0;
    for (int k = 127; k < 132; ++k)
        saved[k] = 0;
    int bit = 0;
    for (int slot = 1; slot < 46; ++slot) {
        uint16_t value = word(sound + 20 + 2 * slot);
        int src = slot >= 17 && slot <= 24;
        if (!src && (int16_t)value < 0)
            value = 0;
        pack(saved, &bit, value, src ? 16 : 15);
    }
    for (int k = 0; k < CM_EXTRAS; ++k)
        pack(saved, &bit, extra_value(u, sound, k), 15);
    pack(saved, &bit, word(sound + 20), 16);
    put(saved + 4, 0);
    put(saved + 6, 4);
    return result;
}

uint32_t mp_sound_load(uint8_t *sound, const uint8_t *saved)
{
    if (!sound || !saved || longword(saved + 4) != 4) {
        uint32_t result = mp_native_load(sound, saved);
        if (!(result & 255))
            return result;
        const struct cm_ui32 *u = mp_src_for(sound[126]);
        if (u) {
            for (int k = 0; k < CM_EXTRAS; ++k) {
                put(sound + 20 + 2 * MP_EXTRA_SLOT(k), u->extra[k].def);
            }
        }
        return result;
    }
    if (!packed_sound(saved))
        return 0;
    const struct cm_ui32 *u = mp_src_for(saved[124]);
    uint8_t native_saved[160], native_sound[162];
    uint16_t values[45 + CM_EXTRAS], id;
    for (int k = 0; k < 160; ++k)
        native_saved[k] = saved[k];
    for (int k = 0; k < 162; ++k)
        native_sound[k] = sound[k];
    for (int k = 28; k < 124; ++k)
        native_saved[k] = 0;
    put(native_saved + 4, 0);
    put(native_saved + 6, 3);
    int bit = 0;
    for (int slot = 1; slot < 46; ++slot) {
        uint16_t value = unpack(saved, &bit, slot >= 17 && slot <= 24 ? 16 : 15);
        values[slot - 1] = value;
        put(native_saved + 28 + 2 * SAVE_MAP[slot], slot == 4 || slot == 12 ? 0 : value);
    }
    for (int k = 0; k < CM_EXTRAS; ++k) {
        uint16_t value = unpack(saved, &bit, 15);
        values[45 + k] = value <= 0x7f00 ? value : u->extra[k].def;
    }
    id = unpack(saved, &bit, 16);
    put(native_saved + 28 + 2 * SAVE_MAP[0], id);
    uint32_t result = mp_native_load(native_sound, native_saved);
    if (result & 255) {
        put(native_sound + 20, id);
        for (int slot = 1; slot < 46; ++slot)
            put(native_sound + 20 + 2 * slot, values[slot - 1]);
        for (int k = 0; k < CM_EXTRAS; ++k)
            put(native_sound + 20 + 2 * MP_EXTRA_SLOT(k), values[45 + k]);
        for (int k = 0; k < 162; ++k)
            sound[k] = native_sound[k];
    }
    return result;
}

uint32_t mp_sound_upgrade(uint8_t *saved, uint8_t *changed, int32_t target)
{
    if (target == 3 && packed_sound(saved)) {
        if (changed)
            *changed = 0;
        return 1;
    }
    return mp_native_upgrade(saved, changed, target);
}

/* Return -1 to replay the native permutation for ordinary destinations. */
int32_t mp_lfo_save(int32_t machine)
{
    return mp_src_for(machine) ? 0 : -1;
}
