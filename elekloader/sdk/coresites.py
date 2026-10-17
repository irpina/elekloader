# SPDX-License-Identifier: GPL-2.0-or-later
"""Which stock code more than one mod hooks for itself (docs/CORE-CONTRIBUTING.md).

    python -m elekloader.sdk.coresites MODS... [--stock STOCK.syx ...] [--json]

MODS are .elemod files or folders of them: the shop's mods, say. Of each
mod (by id, for each device and OS) only the newest version counts, and
the core's own sites do not. Each linkable mod's code sites (the ones
`lint` notes as core candidates) are compared with every other mod's:

- **same bytes**: the sites overlap; the two mods cannot be built together;
- **same routine**: with that OS's stock file given, the stock code runs
  from the lower site to the higher one with no `rts`, `rte` or new
  `link` between them, within --reach bytes;
- **near**: without the stock file, the sites are at most --window bytes
  apart.

Each group of sites that are linked so is one place where the core could
offer an event in their place. A group's kind is its loosest link (a
group in one routine where some sites also overlap says "overlapping").
Nothing is changed or refused.
"""
import argparse
import json
import os
import sys

from .. import devices, elemod, formats, link
from ..lint import core_candidates

KINDS = ('same bytes', 'same routine', 'near')     # strongest first


def code_sites(paths):
    """-> {(device name, OS): [(mod id, version, addr, len), ...]}, the newest
    version of each linkable mod (other than the core) in `paths`."""
    files = []
    for p in paths:
        files += elemod.mod_files(p) if os.path.isdir(p) else [p]
    newest = {}
    for f in files:
        m = elemod.load_any(f)
        if not isinstance(m, link.Mod2) or m.id == 'core':
            continue
        k = (m.dev.key, m.rel.version, m.id)
        if k not in newest or elemod.version_key(m.version) > elemod.version_key(newest[k].version):
            newest[k] = m
    out = {}
    for (_key, _os, _id), m in sorted(newest.items()):
        out.setdefault((m.dev.name, m.rel.version), []).extend(
            (m.id, m.version, int(c['site'], 16), c['len']) for c in core_candidates(m))
    return out


def routine_test(image, dev, reach=1024):
    """-> same(lo, hi): whether stock code runs from site lo to site hi
    (each (addr, len), lo first) inside one routine."""
    isa = dev.decoder()
    read = isa.reader(image, dev.main_load)
    bad = isa.ILLEGAL | isa.LINEF | isa.FPU

    def same(lo, hi):
        pc = lo[0]
        while pc < hi[0]:
            if pc - lo[0] > reach:
                return False
            ins = isa.decode(read(pc), pc)
            if ins.flags & bad or (ins.op == 'link' and pc != lo[0]):
                return False
            if ins.flow in (isa.F_RTS, isa.F_RTE) and pc + ins.length <= hi[0]:
                return False
            pc += ins.length
        return True
    return same


def shared_sites(sites, same_routine=None, window=64, reach=1024):
    """`sites`: [(mod, version, addr, len), ...] for one device and OS.
    -> [{'kind', 'lo', 'hi', 'sites': [...]}, ...], each group of other
    mods' sites linked by overlapping, one routine (with `same_routine`) or
    nearness (without it), by address; 'kind' is the loosest link in the
    group, and 'overlap' whether any two of its sites overlap. Sites more than `reach` (with
    `same_routine`) or `window` bytes apart are never compared."""
    s = sorted(sites, key=lambda x: (x[2], x[0]))
    up = list(range(len(s)))

    def root(i):
        while up[i] != i:
            up[i] = up[up[i]]
            i = up[i]
        return i
    kind, overlap = {}, set()
    for i, a in enumerate(s):
        for j in range(i + 1, len(s)):
            b = s[j]
            if b[2] - (a[2] + a[3]) > (window if same_routine is None else reach):
                break
            if a[0] == b[0]:
                continue
            if b[2] < a[2] + a[3]:
                k = 0
            elif same_routine is not None:
                if not same_routine((a[2], a[3]), (b[2], b[3])):
                    continue
                k = 1
            elif b[2] - (a[2] + a[3]) <= window:
                k = 2
            else:
                continue
            ra, rb = root(i), root(j)
            if ra != rb:
                up[rb] = ra
                k = max(k, kind.pop(rb, k))
                if rb in overlap:
                    overlap.remove(rb)
                    overlap.add(ra)
            kind[ra] = max(k, kind.get(ra, k))
            if b[2] < a[2] + a[3]:
                overlap.add(ra)
    groups = {}
    for i in range(len(s)):
        groups.setdefault(root(i), []).append(s[i])
    out = []
    for r, g in groups.items():
        if r not in kind or len({x[0] for x in g}) < 2:
            continue
        out.append({'kind': KINDS[kind[r]], 'overlap': r in overlap, 'lo': g[0][2], 'hi': max(x[2] + x[3] for x in g),
                    'sites': [{'mod': x[0], 'version': x[1], 'site': '0x%08x' % x[2], 'len': x[3]}
                              for x in g]})
    return sorted(out, key=lambda o: o['lo'])


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.sdk.coresites', description=__doc__.split('\n')[0])
    ap.add_argument('mods', nargs='+', help='.elemod files, or folders of them')
    ap.add_argument('--stock', action='append', default=[],
                    help='a stock file (repeatable): its OS is checked routine by routine')
    ap.add_argument('--window', type=int, default=64,
                    help='without a stock file: the most bytes between two sites called near')
    ap.add_argument('--reach', type=int, default=1024,
                    help='with one: the most bytes one routine is followed for')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    a = ap.parse_args(argv)
    tests = {}
    for p in a.stock:
        st, dev, rel = formats.load(p)
        tests[(dev.name, rel.version)] = routine_test(formats.main_image(st, dev), dev, a.reach)
    report = []
    for (name, os_), sites in sorted(code_sites(a.mods).items()):
        if not sites:
            continue
        report.append({'target': '%s %s' % (name, os_), 'mods': len({x[0] for x in sites}),
                       'code_sites': len(sites), 'by_routine': (name, os_) in tests,
                       'shared': shared_sites(sites, tests.get((name, os_)), a.window, a.reach)})
    if a.json:
        print(json.dumps(report, indent=1))
        return 0
    for t in report:
        print('%s: %d shared, from %d mods with %d code sites of their own (%s)'
              % (t['target'], len(t['shared']), t['mods'], t['code_sites'],
                 'by routine' if t['by_routine'] else 'within %d bytes; give --stock to '
                 'check routines' % a.window))
        for g in t['shared']:
            kind = g['kind'] + (', overlapping' if g['overlap'] and g['kind'] != KINDS[0] else '')
            print('  0x%08x-0x%08x  %-25s  %s' % (g['lo'], g['hi'], kind, ', '.join(
                '%s %s (%s +%d)' % (x['mod'], x['version'], x['site'], x['len'])
                for x in g['sites'])))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, elemod.ModError, formats.FormatError, devices.UnknownFirmware) as e:
        sys.exit('coresites: %s' % e)
