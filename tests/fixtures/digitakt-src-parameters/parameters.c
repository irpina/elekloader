/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "digitakt-mk1/core3.h"

#define PARAMETER(n, extra_flags) { .name = "P" #n, .lname = "Parameter " #n, \
    .look = 134, .flags = CM_RANGE | CM_DEFAULT | (extra_flags), .max = 0x7f00 }

static const struct cm_src_page pages[] = {
    { "PARAM 1/2", {0, 1, 2, 3, 4, 5, 6, 7} },
    { "PARAM 2/2", {8, 9, 10, 11, 12, 13, 14, 15} },
};

static const struct cm_ui5 ui = {
    .base = {
        .abi = cm_ui_v5, .page_from = 3, .group = "PARAM",
        .knob = {
            PARAMETER(1, 0), PARAMETER(2, 0), PARAMETER(3, 0),
            PARAMETER(4, CM_NOT_SAMPLE),
            PARAMETER(5, 0), PARAMETER(6, 0), PARAMETER(7, 0), PARAMETER(8, 0),
        },
    },
    .extra = {
        PARAMETER(9, 0), PARAMETER(10, 0), PARAMETER(11, 0), PARAMETER(12, 0),
        PARAMETER(13, 0), PARAMETER(14, 0), PARAMETER(15, 0), PARAMETER(16, 0),
    },
    .page_count = 2, .pages = pages,
};

/* Experimental render ID 120 has no native sound generator. */
const struct cm_machine parameter_machine = {
    120, "PARAM", "PARM", 0, 3, 120, CM_UI_TAG, &ui.base,
};
