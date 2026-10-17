/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "digitakt-mk1/core3.h"

static const struct cm_src_page pages[] = {{"TEST", {8, 9, 255, 255, 255, 255, 255, 255}}};
static const struct cm_src_page bad_pages[] = {{"BAD", {16, 255, 255, 255, 255, 255, 255, 255}}};
#define EXTRA(v) {.look=134, .flags=CM_RANGE|CM_DEFAULT, .min=0, .max=0x7f00, .def=(v)}
#define REST EXTRA(0), EXTRA(0), EXTRA(0), EXTRA(0), EXTRA(0), EXTRA(0), EXTRA(0)
#define BASE .base={.abi=cm_ui_v5, .page_from=3}
const struct cm_ui5 probe_ui = {BASE,
    .extra={EXTRA(13), EXTRA(29), EXTRA(3), EXTRA(4), EXTRA(5), EXTRA(6), EXTRA(7), EXTRA(8)},
    .page_count=1, .pages=pages};
static const struct cm_ui5 bad_count = {BASE, .extra={EXTRA(0), REST}, .page_count=3, .pages=pages};
static const struct cm_ui5 bad_range = {BASE, .extra={{.look=134, .flags=6, .max=65535}, REST},
                                      .page_count=1, .pages=pages};
static const struct cm_ui5 bad_look = {BASE, .extra={{.look=164, .flags=6, .max=0x7f00}, REST},
                                     .page_count=1, .pages=pages};
static const struct cm_ui5 bad_mapping = {BASE, .extra={EXTRA(0), REST}, .page_count=1, .pages=bad_pages};
static const struct cm_ui5 bad_reserved = {BASE, .extra={EXTRA(0), REST}, .page_count=1,
                                         .reserved={1}, .pages=pages};
#define MACHINE(n, ui) const struct cm_machine probe_machine##n = \
    {n, "Storage probe", "TEST", 0, 3, n, CM_UI_TAG, ui}
MACHINE(121, &probe_ui.base);
const struct cm_machine probe_machine119 = {119, "Other bank", "BANK", 0, 0, 119, CM_UI_TAG, &probe_ui.base};
static const struct cm_ui legacy_ui = {
    .abi=cm_ui_v3, .page_from=3,
    .knob={[0]={.name="OLD", .lname="Old Tune", .lfo_long="Old LFO", .look=134,
                .flags=CM_RANGE|CM_DEFAULT, .max=0x7f00, .def=13}},
};
MACHINE(122, &legacy_ui);
MACHINE(123, &bad_count.base);
MACHINE(124, &bad_range.base);
MACHINE(125, &bad_look.base);
MACHINE(126, &bad_mapping.base);
MACHINE(127, &bad_reserved.base);
