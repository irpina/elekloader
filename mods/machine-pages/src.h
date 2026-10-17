/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "digitakt-mk1/core3.h"

/* Extra value k (0-6) is sound slot 46 + k, parameter id 164 + k. */
#define MP_EXTRA_SLOT(k) (46 + (k))
#define MP_EXTRA_ID      164
#define MP_EXTRA_END     (MP_EXTRA_ID + CM_EXTRAS)   /* 171: the first id past them */

const struct cm_ui32 *mp_src_for(int32_t machine);
uint32_t mp_ui32(int32_t machine);
void mp_src_init(void);
