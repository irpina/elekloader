/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "src.h"

extern uint32_t mp_descriptor_table[];
uint32_t mp_legacy_tables[150];
static int initialized;

/* Preserve the following tables before extending the descriptor array. */
void mp_params_init(void)
{
    if (initialized)
        return;
    initialized = 1;
    mp_src_init();
    uint32_t *extra = mp_descriptor_table + 164 * 13;
    for (int i = 0; i < 150; ++i)
        mp_legacy_tables[i] = extra[i];
    static const char *const names[] = {
        "Extra 1", "Extra 2", "Extra 3", "Extra 4", "Extra 5", "Extra 6", "Extra 7", "Extra 8",
    };
    static const char *const labels[] = {"XTR1", "XTR2", "XTR3", "XTR4", "XTR5", "XTR6", "XTR7", "XTR8"};
    for (int k = 0; k < 8; ++k) {
        uint32_t *p = extra + 13 * k;
        for (int i = 0; i < 13; ++i)
            p[i] = mp_descriptor_table[134 * 13 + i];
        p[1] = k == 7 ? 0 : 46 + k;
        p[4] = 0;
        p[6] = p[7] = 0xffffffffu;       /* no borrowed MIDI assignments */
        p[8] = 0;
        p[10] = (uint32_t)names[k];
        p[11] = (uint32_t)"SRC";
        p[12] = (uint32_t)labels[k];
    }
}

int32_t mp_slot_id(int32_t slot, int32_t machine)
{
    const struct cm_ui5 *u = mp_src_for(machine);
    if (slot == 0)
        return u ? 171 : -1;
    if (slot < 46 || slot > 52)
        return -1;
    return u ? 164 + slot - 46 : 0;
}

int32_t mp_randomize_owner(int32_t id, int32_t machine)
{
    return mp_src_for(machine) && (uint32_t)(id - 164) < 8 ? 3 : -1;
}

void mp_sound_defaults(uint8_t *sound)
{
    if (!sound)
        return;
    const struct cm_ui5 *u = mp_src_for(sound[126]);
    if (!u)
        return;
    for (int k = 0; k < 16; ++k) {
        const struct cm_knob *p = k < 8 ? &u->base.knob[k] : &u->extra[k - 8];
        if (p->flags & CM_DEFAULT) {
            int slot = k < 8 ? 17 + k : k == 15 ? 0 : 46 + k - 8;
            sound[20 + 2 * slot] = (uint32_t)p->def >> 8;
            sound[21 + 2 * slot] = p->def;
        }
    }
}

void mp_machine_defaults(void *object)
{
    const uint32_t *vtable = *(const uint32_t **)object;
    uint8_t *sound = (uint8_t *)((uint32_t (*)(void *))vtable[10])(object);
    if (!sound || !mp_src_for(sound[126]))
        return;
    mp_sound_defaults(sound);
    /* A null event is the native sound reference's full-sound update. */
    ((void (*)(void *, void *))vtable[4])(object, 0);
}
