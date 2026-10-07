# SPDX-License-Identifier: GPL-2.0-or-later
"""The catalog against a new core (pytest, or run with python): every Digitakt
mk1 mod of a catalog, alone and with every other, linked against the
catalog's core 2.1 and against mods/core built from this tree. Core 3.0 is
core 2.1 and more, so every selection must link or be refused as it is
with 2.1, with the same messages; and the core a builder takes for each
selection (elemod.pick_core) must stay 2.1, so today's builds keep their
bytes.

Needs files named by environment variables; without them it skips:
  ELEKLOADER_CATALOG_DIR  a folder with the catalog's .elemod files, cores
                          included (js/tools/kit.ts sync, or the site's shop/
                          and core/ folders together)
  ELEKLOADER_STOCK        Digitakt_OS1.53.syx
  ELEKLOADER_STOCK_154    optional: Digitakt_OS1.54.syx
and the m68k cross toolchain, to build mods/core and mods/machine-pages.
"""
import glob
import itertools
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, elemod, formats, link     # noqa: E402
from elekloader.sdk import build                          # noqa: E402

CATALOG = os.environ.get('ELEKLOADER_CATALOG_DIR', '')
STOCKS = {'1.53': os.environ.get('ELEKLOADER_STOCK', ''),
          '1.54': os.environ.get('ELEKLOADER_STOCK_154', '')}


class Skip(Exception):
    pass


def outcome(mods, image):
    try:
        link.link(mods, image)
        return 'links'
    except elemod.ModError as e:
        return str(e)


def matrix(os_version, tmp):
    """-> [(selection, 2.1's outcome, 3.0's outcome)] for one OS, and the cores."""
    st = STOCKS[os_version]
    if not st or not os.path.exists(st):
        raise Skip('missing the stock file for %s' % os_version)
    stock, dev, rel = formats.load(st)
    image = formats.main_image(stock, dev)
    files = [elemod.load_any(p) for p in sorted(glob.glob(os.path.join(CATALOG, '*.elemod')))]
    files = [m for m in files if m.dev.key == 'digitakt-mk1' and m.rel.version == os_version]
    old = [m for m in files if m.id == 'core' and m.version == '2.1']
    if not old:
        raise Skip('no core 2.1 for %s in ELEKLOADER_CATALOG_DIR' % os_version)
    new = link.Mod2(*_load(build.build(os.path.join(ROOT, 'mods', 'core'), st, tmp)[0]))
    mods = [m for m in files if m.id != 'core']
    byid = {m.id: m for m in mods}

    def with_requirements(sel):
        out = list(sel)
        for m in sel:
            out += [byid[r] for r in m.requires if r in byid and byid[r] not in out]
        return out

    rows = []
    for sel in [(m,) for m in mods] + list(itertools.combinations(mods, 2)):
        ms = with_requirements(sel)
        a = outcome([old[0]] + ms, image).replace(old[0].label(), 'core')
        b = outcome([new] + ms, image).replace(new.label(), 'core')
        rows.append(([m.label() for m in sel], a, b, ms))
    return rows, old[0], new, image


def _load(path):
    doc, raw = elemod.read_json(path)
    return doc, os.path.basename(path), raw


def check_os(os_version):
    if not CATALOG or not os.path.isdir(CATALOG):
        raise Skip('missing ELEKLOADER_CATALOG_DIR')
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'as'):
        raise Skip('no m68k cross assembler to build mods/core')
    with tempfile.TemporaryDirectory() as tmp:
        rows, old, new, _image = matrix(os_version, tmp)
        assert new.version == '3.0' and rows
        diff = [(sel, a, b) for sel, a, b, _ in rows if a != b]
        assert not diff, diff[:3]
        # the core a builder takes for each selection: 2.1, as before 3.0 was listed
        for _sel, _a, _b, ms in rows:
            needs = [m.needs_core for m in ms if m.needs_core]
            need = max(needs, key=elemod.version_key) if needs else None
            assert elemod.pick_core([old.version, new.version], need) == 0
        linked = sum(a == 'links' for _s, a, _b, _m in rows)
        print('  %s: %d selections, %d link and %d are refused, the same with core 3.0'
              % (os_version, len(rows), linked, len(rows) - linked))


def test_the_catalog_links_with_core_3_as_with_core_2_1():
    check_os('1.53')


def test_the_catalog_links_with_core_3_as_with_core_2_1_on_1_54():
    check_os('1.54')


if __name__ == '__main__':
    import traceback
    ok = skipped = failed = 0
    for n in sorted(k for k in globals() if k.startswith('test_')):
        try:
            globals()[n]()
            print('ok      %s' % n)
            ok += 1
        except Skip as e:
            print('SKIP    %s (%s)' % (n, e))
            skipped += 1
        except Exception:
            print('FAIL    %s' % n)
            traceback.print_exc()
            failed += 1
    print('%d passed, %d failed, %d skipped' % (ok, failed, skipped))
    sys.exit(1 if failed else 0)
