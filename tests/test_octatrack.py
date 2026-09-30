# SPDX-License-Identifier: GPL-2.0-or-later
"""The Octatrack: its file family (elek.py), its profile, whole builds (pytest,
or run with python).

Needs the stock files, which never go in the repo, named by environment
variables; a test whose inputs are missing is skipped, not passed:
  ELEKLOADER_OT_SYX   OCTATRACK_OS1.40C.syx
  ELEKLOADER_OT_BIN   OCTATRACK_OS1.40C.bin
Building mods/core-ot also needs the cross assembler (m68k-linux-gnu-as).
"""
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, elek, elemod, formats, link, mkmod, patch   # noqa: E402
from elekloader.elemod import sha                                           # noqa: E402

SYX = os.environ.get('ELEKLOADER_OT_SYX', '')
BIN = os.environ.get('ELEKLOADER_OT_BIN', '')
DEV = [d for d in devices.devices() if d.key == 'octatrack'][0]
REL = DEV.releases['1.40C']


class Skip(Exception):
    pass


def need(p):
    if not p or not os.path.exists(p):
        raise Skip('missing %s' % (p or 'ELEKLOADER_OT_SYX/BIN'))
    with open(p, 'rb') as fh:
        return fh.read()


_c = {}


def stock():
    if 'st' not in _c:
        raw = need(SYX)
        _c['st'], dev, rel = formats.load(raw)
        assert dev is DEV and rel == REL
        _c['img'] = formats.main_image(_c['st'], DEV)
    return _c['st'], _c['img']


def expect(fn, *words):
    try:
        fn()
    except (elek.ElekError, formats.FormatError, elemod.ModError, patch.PatchError) as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return str(e)
    raise AssertionError('not refused')


def bundle(sites=(), blob=b'', version=None, extra=None):
    """A format-1 mod for the Octatrack: data `sites` [(addr, new)], a blob."""
    st, img = stock()
    doc = {'elemod': 1, 'id': 'ot-test', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sites': []}
    for addr, new in sites:
        o = addr - DEV.main_load
        doc['sites'].append({'addr': '0x%08x' % addr, 'len': len(new), 'kind': 'data',
                             'stock_sha256': sha(img[o:o + len(new)]), 'new': new.hex()})
    if blob:
        doc['blob'] = {'load': '0x%08x' % DEV.image_end(REL), 'len': len(blob),
                       'sha256': sha(blob), 'parts': [['hex', blob.hex()]]}
    if version:
        doc['ele3_version'] = version
    doc.update(extra or {})
    return doc


def write_mod(tmp, doc, name='ot-test.elemod'):
    p = os.path.join(tmp, name)
    with open(p, 'w') as fh:
        json.dump(doc, fh)
    return p


# ---- the file family ------------------------------------------------------------------

def test_stock_files_parse_and_agree():
    st, img = stock()
    b = formats.parse(need(BIN), DEV)
    assert st.kind == 'syx' and b.kind == 'bin' and st.device_id == 0x05
    assert st.build == '0178' and st.version == '1.40C' == b.version
    assert b.stored[3] == st.stored[3]
    assert len(img) == REL.main_len and sha(img) == REL.main_sha256


def test_the_zip_elektron_publishes_loads_as_its_os_file():
    import io
    import zipfile
    syx_raw, bin_raw = need(SYX), need(BIN)
    for members in ((('OCTATRACK_OS1.40C_dist/OCTATRACK_OS1.40C.bin', bin_raw),
                     ('OCTATRACK_OS1.40C_dist/OCTATRACK_OS1.40C.syx', syx_raw),
                     ('OCTATRACK_OS1.40C_dist/readme.txt', b'notes')),
                    (('OCTATRACK_OS1.40C.bin', bin_raw),)):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in members:
                z.writestr(name, data)
        f, dev, rel = formats.load(buf.getvalue())
        assert dev is DEV and rel == REL
        assert f.kind == ('syx' if len(members) > 1 else 'bin')     # the .syx is preferred
        assert formats.main_image(f, DEV) == stock()[1]


def test_rebuilds_both_stock_files_byte_for_byte():
    syx_raw, bin_raw = need(SYX), need(BIN)
    for src in (syx_raw, bin_raw):
        f = formats.parse(src, DEV)
        out = formats.write(f, f.stored[3], DEV)
        assert out['syx'] == syx_raw and out['bin'] == bin_raw


def test_corruption_is_caught():
    raw = bytearray(need(SYX))
    raw[1000] ^= 0x01                                 # a payload bit: the checksum fails
    expect(lambda: elek.ElekFile(bytes(raw)))
    b = bytearray(need(BIN))
    b[5000] ^= 0x10                                   # a cipher bit: the card checksum fails
    expect(lambda: elek.ElekFile(bytes(b)), 'checksum')


# ---- whole builds ---------------------------------------------------------------------------

def test_data_site_and_blob_build_and_verify():
    st, img = stock()
    blob = b'\x4e\x75' + bytes(range(256)) * 4        # stands in for a loader and its payloads
    site = (0x400b5839, b'OS UPDATE!')                # the "OS UPGRADE" text, same length
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([site], blob, version='ELEK TEST'))
        need(SYX)
        outputs, man = patch.build(SYX, [p], log=lambda *a: None)
    assert set(outputs) == {'syx', 'bin'}
    o = formats.parse(outputs['syx'], DEV)
    ob = formats.parse(outputs['bin'], DEV)
    new = formats.main_image(o, DEV)
    assert new == formats.main_image(ob, DEV)
    assert new[site[0] - DEV.main_load:][:10] == site[1]
    assert new[len(img):] == blob and len(new) == len(img) + len(blob)
    assert o.version == 'ELEK TEST' and o.build == '0178'
    assert man['output']['main']['inplace_min_gap'] is None


def test_refuses_the_protected_bootloader_copy():
    lo, hi, _why = DEV.protected[0]
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([(0x400e18f1, b'X')]))   # the bootloader's strings
        need(SYX)
        expect(lambda: patch.build(SYX, [p], version='x', log=lambda *a: None),
               'protected')
    st, img = stock()
    bad = bytearray(img)
    bad[lo - DEV.main_load] ^= 1
    stored = formats.pack_main(bytes(bad))
    outputs = formats.write(st, stored, DEV, 'x')
    expect(lambda: formats.verify(outputs, st, bytes(bad), DEV, 'x'), 'not stock')


def test_version_field():
    st, img = stock()
    stored = st.stored[3]
    for v in ('1', '1.40C-ELEK'):
        out = formats.write(st, stored, DEV, v)
        assert formats.parse(out['syx'], DEV).version == v
        formats.verify(out, st, img, DEV, v)
    expect(lambda: formats.write(st, stored, DEV, '1.40C-ELEKX'), '1 to 10')


def test_verify_refuses_a_changed_header():
    st, img = stock()
    out = formats.write(st, st.stored[3], DEV)
    f = formats.parse(out['syx'], DEV)
    cont = bytearray(f.container)
    cont[5] ^= 1                                       # the build code
    bad = {'syx': elek.encode_syx(bytes(cont), 5), 'bin': out['bin']}
    expect(lambda: formats.verify(bad, st, img, DEV), 'header')


# ---- linkable mods and the core -------------------------------------------------------------

PAGE, PAGES, STOCK_PAGES = 6144, 1707, 14602


def test_linkable_mods_need_the_octatrack_core():
    """The Octatrack links format-2 mods in the arena's bottom pages, with its
    own core (mods/core-ot)."""
    assert DEV.linkable() and DEV.ddr == (0x40A955E0, 0x40A955E0 + PAGE * PAGES)
    site = (0x400b5839, b'OS UPDATE!')
    st, img = stock()
    o = site[0] - DEV.main_load
    doc = {'elemod': 2, 'id': 'x', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sections': {}, 'requires': ['core'],
           'sites': [{'addr': '0x%08x' % site[0], 'len': len(site[1]), 'kind': 'data',
                      'stock_sha256': sha(img[o:o + len(site[1])]), 'new': site[1].hex()}]}
    problems = link.check([link.Mod2(doc, 'x')], img)
    assert any('requires core' in p for p in problems), problems


def test_the_core_moves_the_arena_past_its_reserve():
    """Every arena write in mods/core-ot follows from one number, the pages it
    takes: the base and base + one page move up by the reserve; the page
    count, the fill limit and the clear length (one page more than the count)
    shrink by it. Each stock value is checked against the stock image."""
    with open(os.path.join(ROOT, 'mods', 'core-ot', 'mod.json')) as fh:
        j = json.load(fh)
    lo, hi = DEV.ddr
    moved = {lo: hi, lo + PAGE: hi + PAGE,
             STOCK_PAGES: STOCK_PAGES - PAGES, STOCK_PAGES + 1: STOCK_PAGES + 1 - PAGES,
             (STOCK_PAGES + 1) * PAGE: (STOCK_PAGES + 1 - PAGES) * PAGE}
    st, img = stock()
    seen = {}
    for s in j['sites']:
        o = int(s['addr'], 16) - DEV.main_load
        old = bytes.fromhex(s['stock'])
        assert img[o:o + len(old)] == old, s['addr']
        if s['op'] == 'bytes':
            assert moved[int(s['stock'], 16)] == int(s['new'], 16), s['addr']
            seen[int(s['stock'], 16)] = seen.get(int(s['stock'], 16), 0) + 1
    assert seen == {lo: 23, lo + PAGE: 1, STOCK_PAGES: 2, STOCK_PAGES + 1: 1,
                    (STOCK_PAGES + 1) * PAGE: 1}
    assert [s['op'] for s in j['sites']].count('jsr') == 1


def test_a_site_can_add_to_its_target():
    """sdk.build's `addend`: a site's relocation carries it (no toolchain needed:
    a mod of sites only). Only a site with a target takes one."""
    from elekloader.sdk import build
    need(SYX)
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'm')
        os.makedirs(d)
        site = {'addr': '0x400d64a0', 'stock': '4000e79c', 'op': 'ptr', 'target': 'arena_base',
                'addend': 8}
        doc = {'id': 'addend', 'version': '1', 'device': 'octatrack', 'os': '1.40C',
               'sites': [site], 'requires': ['core']}
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump(doc, fh)
        path, m = build.build(d, SYX, tmp)
        assert m.sites[0]['relocs'] == [(0, 'abs32', 'sym:arena_base', 8)], m.sites[0]['relocs']
        assert m.imports == ['arena_base']
        doc['sites'] = [{'addr': '0x400d64a0', 'stock': '4000e79c', 'op': 'bytes',
                         'new': '00000000', 'addend': 8}]
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump(doc, fh)
        try:
            build.build(d, SYX, tmp)
        except build.BuildError as e:
            assert 'addend needs a target' in str(e)
        else:
            raise AssertionError('an addend without a target was built')


def test_fixed_code_is_a_site_with_absolute_symbols():
    """sdk.build's `fixed`: code at an address in a free image area becomes a site
    over the zeros there, its labels absolute symbols; the linker needs nothing new.
    Refused outside a free area, over bytes that are not zero, or with anything but
    .text."""
    import shutil
    from elekloader.sdk import build
    need(SYX)
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', DEV.toolchain['prefix']) + 'objcopy'):
        raise Skip('no m68k cross binutils')
    st, img = stock()

    def attempt(tmp, addr, text, sym='fx_start'):
        d = os.path.join(tmp, 'fx')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'fx.s'), 'w') as fh:
            fh.write(text)
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump({'id': 'fx', 'version': '1', 'device': 'octatrack', 'os': '1.40C',
                       'fixed': [{'source': 'fx.s', 'addr': addr, 'symbol': sym}],
                       'requires': ['core']}, fh)
        return build.build(d, SYX, tmp)

    code = ('        .text\n        .globl  fx_loop\nfx_loop: lea     fx_loop,%a0\n'
            '        jsr     arena_base\n        rts\n')
    with tempfile.TemporaryDirectory() as tmp:
        path, m = attempt(tmp, '0x400d64e0', code)
        s = m.sites[0]
        assert (s['addr'], s['len'], s['kind']) == (0x400d64e0, 14, 'data')
        assert s['stock_sha256'] == sha(bytes(14))
        assert m.symbols['fx_start'] == ('abs', 0x400d64e0) == m.symbols['fx_loop']
        assert (2, 'abs32', 'abs', 0x400d64e0) in s['relocs']            # lea fx_loop
        assert (8, 'abs32', 'sym:arena_base', 0) in s['relocs']        # jsr arena_base
        assert not m.size('.run') and m.imports == ['arena_base']
        for addr, text, words in (('0x400d2000', code, 'not inside a free area'),
                                  ('0x400d7c30', code, 'not inside a free area'),
                                  ('0x40000400', code, 'not inside a free area'),
                                  ('0x400d64e0', code + '        .data\n        .long 1\n',
                                   'only have .text')):
            try:
                attempt(tmp, addr, text)
            except build.BuildError as e:
                assert words in str(e), (words, str(e))
            else:
                raise AssertionError('built: %s' % words)
    dev0 = [d for d in devices.devices() if d.key == 'digitakt-mk1'][0]
    assert dev0.image_free == ()                    # other devices declare none: unchanged


def test_core_builds_and_links():
    """mods/core-ot with a mod that puts a marker in .run: the boot site calls
    .boot at the end of the image, and the run image the linker placed after
    .boot is what .boot copies to the reserve."""
    import shutil
    from elekloader.sdk import build
    need(SYX)
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', DEV.toolchain['prefix']) + 'as'):
        raise Skip('no m68k cross assembler to build mods/core-ot')
    st, img = stock()
    with tempfile.TemporaryDirectory() as tmp:
        core, _m = build.build(os.path.join(ROOT, 'mods', 'core-ot'), SYX, tmp)
        d = os.path.join(tmp, 'marker')
        os.makedirs(d)
        with open(os.path.join(d, 'marker.s'), 'w') as fh:
            fh.write('        .section .run, "ax"\n        .globl  otmarker\n'
                     'otmarker: .ascii "ELEKLOADER MARKER"\n        .balign 4\n'
                     '        .section .bss\n        .balign 4\notbss:  .skip   64\n')
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump({'id': 'ot-marker', 'version': '1', 'device': 'octatrack', 'os': '1.40C',
                       'sources': ['marker.s'], 'requires': ['core']}, fh)
        marker, _m = build.build(d, SYX, tmp)
        outputs, man = patch.build(SYX, [core, marker], version='CORE TEST',
                                   log=lambda *a: None)
    new = formats.main_image(formats.parse(outputs['syx'], DEV), DEV)
    end = DEV.image_end(REL)
    boot = DEV.main_load + len(img)
    assert end == boot
    o = 0x4000050c - DEV.main_load
    assert new[o:o + 6] == b'\x4e\xb9' + struct.pack('>I', boot)
    assert new[len(img):].find(b'ELEKLOADER MARKER') > 0
    o = 0x4000045e - DEV.main_load
    assert new[o:o + 4] == struct.pack('>I', DEV.ddr[1])


def test_mkmod_diff_round_trip():
    st, img = stock()
    blob = bytes(range(200))
    changed = bytearray(img)
    o = 0x400b5839 - DEV.main_load
    changed[o:o + 10] = b'OS UPDATE!'
    changed[0x40050000 - DEV.main_load] ^= 0xFF
    changed += blob
    built = formats.write(st, formats.pack_main(bytes(changed)), DEV, 'BUILD 1')
    with tempfile.TemporaryDirectory() as tmp:
        bp = os.path.join(tmp, 'built.syx')
        with open(bp, 'wb') as fh:
            fh.write(built['syx'])
        meta = os.path.join(tmp, 'meta.json')
        with open(meta, 'w') as fh:
            json.dump({'id': 'diffed', 'title': 'a diffed build'}, fh)
        out = os.path.join(tmp, 'diffed.elemod')
        sp = os.path.join(tmp, 'stock.syx')
        with open(sp, 'wb') as fh:
            fh.write(need(SYX))
        rc = mkmod.main(['--stock', sp, '--build', bp, '--diff', '--meta', meta, '--out', out])
        assert rc == 0
        m = elemod.load_any(out)
        assert m.blob['len'] == len(blob) and len(m.sites) == 2
        assert elemod.apply([m], img) == bytes(changed)
        outputs, man = patch.build(sp, [out], log=lambda *a: None)
        assert man['bundle_matches_build'] and formats.parse(outputs['syx'], DEV).version == 'BUILD 1'


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
