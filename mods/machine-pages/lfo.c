/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "src.h"

int32_t mp_lfo_target(int32_t track, int32_t destination)
{
    if (!mp_ui5(core_track_machine[track]))
        return destination;
    if (!destination)
        return -1;
    return destination == 53 ? 0 : destination;
}
