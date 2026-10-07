# SPDX-License-Identifier: GPL-2.0-or-later
"""The DSP code inside a main OS: the payloads its ColdFire uploads to the DSP cores at boot.

A device that has them names them in its profile (`dsp_payloads`: tag -> (address, length)).
A payload is 24-bit little-endian words: records [space, address, count, count words], space
0 = P, 1 = X, 2 = Y, and two-word directives led by 3 or 4 (the Octatrack's payloads start
with [3, the shared window's start] [4, 0] and end with the [3, ...] again). A word above 4
also ends it. (The Octatrack's: sambanks/octabam's docs/firmware/DSP.md and
tools/build/dsp_modmap.py, which read the same layout.)

The linker places DSP code (`.dsp.<tag>` sections, DSP tables) in the P words of a payload
that a mod frees (the profile's `dsp_areas`); those words are bytes of the main OS at the
addresses `p_span` gives.
"""
from .elemod import ModError

SPACES = 'PXY'


def w24(b, i):
    """A 24-bit little-endian word, as the ColdFire's loader assembles it."""
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16)


def records(image, dev, tag):
    """-> [(space, address, count, main OS address of its first word)] of payload `tag`."""
    if tag not in dev.dsp_payloads:
        raise ModError('the %s has no DSP payload %s' % (dev.name, tag))
    at, n = dev.dsp_payloads[tag]
    b = image[at - dev.main_load:at - dev.main_load + n]
    if len(b) != n:
        raise ModError('DSP payload %s runs past the main OS' % tag)
    off, out = 0, []
    while off + 3 <= n:
        sp = w24(b, off)
        if sp > 4:
            return out
        if sp >= 3:                             # a two-word directive
            off += 6
            continue
        if off + 9 > n:
            break
        addr, cnt = w24(b, off + 3), w24(b, off + 6)
        if not cnt or off + 9 + 3 * cnt > n:
            break
        out.append((sp, addr, cnt, at + off + 9))
        off += 9 + 3 * cnt
    if off == n:
        return out
    raise ModError('DSP payload %s does not parse at +0x%x' % (tag, off))


def p_span(image, dev, tag, lo, hi):
    """The main OS address of payload `tag`'s P words lo..hi-1, which must lie in one record."""
    for sp, addr, cnt, at in records(image, dev, tag):
        if sp == 0 and addr <= lo and hi <= addr + cnt:
            return at + 3 * (lo - addr)
    raise ModError('payload %s does not load P:0x%05x-0x%05x in one record' % (tag, lo, hi - 1))
