"""The linker, format-2 mods (pytest, or run with python).

Needs files that never go in the repo, named by environment variables; a
test whose inputs are missing is skipped, not passed:
  ELEKLOADER_STOCK   the stock Digitakt_OS1.53.syx
  ELEKLOADER_MODS    a folder of built format-2 mods (core, sysinfo,
                     fast-audio, opts, slicer)
"""
import copy
import glob
import itertools
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, link, patch, syx     # noqa: E402
from elekloader.codec import transport                      # noqa: E402
from elekloader.elemod import sha                            # noqa: E402
from elekloader.mkmod import stock_parts                    # noqa: E402

STOCK = os.environ.get('ELEKLOADER_STOCK', '')
DEV = devices.devices()[0]                                  # Digitakt mk1
LOAD = DEV.main_load
MODS = os.environ.get('ELEKLOADER_MODS', '')

IDS = ('core', 'sysinfo', 'fast-audio', 'opts', 'slicer')


class Skip(Exception):
    pass


_c = {}


def image():
    if 'img' not in _c:
        if not STOCK or not os.path.exists(STOCK):
            raise Skip('missing ELEKLOADER_STOCK')
        _c['img'] = syx.Syx.load(STOCK).section(3)
    return _c['img']


def doc_path(mid):
    paths = sorted(glob.glob(os.path.join(MODS, '%s-*.elemod' % mid))
                   + glob.glob(os.path.join(MODS, '%s-*.dtmod' % mid))) if MODS else []
    if not paths:
        raise Skip('no %s mod in %s' % (mid, MODS))
    return paths[-1]


def doc(mid):
    paths = sorted(glob.glob(os.path.join(MODS, '%s-*.elemod' % mid))
                   + glob.glob(os.path.join(MODS, '%s-*.dtmod' % mid))) if MODS else []
    if not paths:
        raise Skip('no %s mod in %s' % (mid, MODS))
    with open(paths[-1]) as fh:
        return json.load(fh)


def mods(*ids):
    return [link.Mod2(doc(i), i) for i in ids]


def expect(fn, *words):
    try:
        fn()
    except elemod.ModError as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return str(e)
    raise AssertionError('not refused')


def test_all_five_link():
    out = link.link(mods(*IDS), image())
    L = out.layout
    assert L['ddr_spare'] > 0 and L['fast_spare'] >= 0
    assert out.map['__run_words'] * 4 == L['ddr'][1] - L['ddr'][0]
    assert out.tables['fa_copies'][1] == 2 and out.tables['fa_fixups'][1] == 31
    assert out.tables['ev_tick'][1] == 3 and out.tables['ev_draw'][1] == 2


def test_order_does_not_matter():
    base = sha(link.link(mods(*IDS), image()).image)
    ids = list(IDS)
    for p in (ids[::-1], ids[2:] + ids[:2], ['slicer', 'core', 'opts', 'sysinfo', 'fast-audio']):
        assert sha(link.link(mods(*p), image()).image) == base


def test_subsets_link():
    for r in range(0, 4):
        for sub in itertools.combinations(('sysinfo', 'fast-audio', 'slicer'), r):
            link.link(mods('core', *sub), image())
    link.link(mods('core', 'fast-audio', 'opts'), image())


def test_core_alone_changes_only_its_sites():
    out = link.link(mods('core'), image())
    img0 = image()
    diff = [i for i in range(len(img0)) if out.image[i] != img0[i]]
    sites = [int(s['addr'], 16) - LOAD for s in doc('core')['sites']]
    assert all(any(s <= d < s + 6 for s in sites) for d in diff)


def test_weak_import_without_fast_audio():
    out = link.link(mods('core', 'sysinfo'), image())
    assert 'r_on' not in out.map or out.map['r_on'] == out.map['core_zero']
    with_fa = link.link(mods('core', 'sysinfo', 'fast-audio'), image())
    assert with_fa.map['r_on'] != with_fa.map['core_zero']


def test_refuses_without_core_or_with_two():
    expect(lambda: link.link(mods('sysinfo'), image()), 'core is not enabled', 'requires core')
    raw = '\n'.join(link.check(mods('sysinfo'), image()))
    assert '.boot' in raw and 'core_additem' in raw and 'ev_tick' in raw
    c2 = doc('core')
    c2['id'] = 'core2'
    expect(lambda: link.link(mods('core') + [link.Mod2(c2, 'core2')], image()),
           'exactly one', 'overlap')


def test_refuses_opts_without_fast_audio():
    msg = expect(lambda: link.link(mods('core', 'opts'), image()), 'requires fast-audio')
    assert 'fa_fixups' not in msg                  # the follow-on lines are summarised away
    raw = '\n'.join(link.check(mods('core', 'opts'), image()))
    assert 'fa_fixups' in raw and '.fast' in raw


def test_refuses_site_on_a_core_site():
    d = doc('slicer')
    d['sites'].append(copy.deepcopy(doc('core')['sites'][1]))     # core's tick site
    expect(lambda: link.link(mods('core') + [link.Mod2(d, 'x')], image()), 'overlap')


def test_refuses_duplicate_export_and_unknown_table():
    d = doc('slicer')
    d['symbols']['core_tick'] = ['.run', 0]
    d['exports'].append('core_tick')
    expect(lambda: link.link(mods('core') + [link.Mod2(d, 'x')], image()), 'both export core_tick')
    d = doc('slicer')
    d['contribute'][0]['to'] = 'ev_nothing'
    expect(lambda: link.link(mods('core') + [link.Mod2(d, 'x')], image()), 'ev_nothing')


def test_refuses_unresolved_import():
    d = doc('sysinfo')
    d['weak'] = []
    expect(lambda: link.link(mods('core') + [link.Mod2(d, 'x')], image()), 'r_on')


def test_copied_block_rules():
    img0 = image()
    # a site overlapping one of opts' fix-ups (its claims) is refused
    op = doc('opts')
    claim = [c for c in op['contribute'] if c['to'] == 'fa_fixups'][0]['claims'][0]
    a = int(claim[0], 16)
    d = doc('slicer')
    s = copy.deepcopy(d['sites'][0])
    # find whole instructions around the claimed bytes
    from elekloader.isa import coldfire as cfisa
    read = cfisa.reader(img0, LOAD)
    pc = a - 40
    while True:
        ins = cfisa.decode(read(pc), pc)
        if pc <= a < pc + ins.length:
            break
        pc += ins.length
    s.update(addr='0x%08x' % pc, len=ins.length, new=img0[pc - LOAD:pc - LOAD + ins.length].hex(),
             stock_sha256=sha(img0[pc - LOAD:pc - LOAD + ins.length]), relocs=[])
    d['sites'] = [s]
    expect(lambda: link.link(mods('core', 'fast-audio', 'opts') + [link.Mod2(d, 'x')], img0),
           'overlap')
    # a PC-relative instruction put inside the copied block is refused
    d = doc('slicer')
    s = copy.deepcopy(d['sites'][0])                     # 0x40074df2, 6 bytes
    s.update(new='6100fffe4e71', relocs=[])              # bsr.w ; nop
    d['sites'] = [s]
    expect(lambda: link.link(mods('core', 'fast-audio') + [link.Mod2(d, 'x')], img0),
           'PC-relative')
    # without fast-audio there is no copied block, so the same site is fine
    link.link(mods('core') + [link.Mod2(d, 'x')], img0)


def test_refuses_over_budget():
    d = doc('slicer')
    d['sections']['.bss']['size'] = 0x20000
    expect(lambda: link.link(mods('core') + [link.Mod2(d, 'x')], image()), 'RAM')
    d = doc('opts')
    s = d['sections']['.fast']
    s['parts'] = s['parts'] + [['hex', '00' * 800]]
    s['len'] += 800
    expect(lambda: link.link(mods('core', 'fast-audio') + [link.Mod2(d, 'x')], image()),
           'SRAM')


def test_full_build_verifies():
    image()
    for i in IDS:
        doc(i)
    paths = [doc_path(i) for i in IDS]
    out, man = patch.build(STOCK, paths, '2.0t', log=lambda *a: None)
    assert man['output']['main']['inplace_min_gap'] > 0
    o = syx.Syx(out)
    assert o.version == '2.0t'
    assert sha(o.section(3)) == man['main_sha256']


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
