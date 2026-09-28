# SPDX-License-Identifier: GPL-2.0-or-later
"""The Analog Rytm mk1: its file family (ELE2, in syx.py), its profile, patch
sets (pytest, or run with python).

Needs the stock file, which never goes in the repo, named by an environment
variable; a test whose input is missing is skipped, not passed:
  ELEKLOADER_RYTM_SYX   Analog-Rytm_OS1.73.syx
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, formats, link, mkmod, patch, syx   # noqa: E402
from elekloader.elemod import sha                                         # noqa: E402

SYX = os.environ.get('ELEKLOADER_RYTM_SYX', '')
DEV = [d for d in devices.devices() if d.key == 'rytm-mk1'][0]
REL = DEV.releases['1.73']
CAVE2 = DEV.areas['cave2']


class Skip(Exception):
    pass


def need(p):
    if not p or not os.path.exists(p):
        raise Skip('missing %s' % (p or 'ELEKLOADER_RYTM_SYX'))
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
    except (syx.SyxError, formats.FormatError, elemod.ModError, patch.PatchError) as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return str(e)
    raise AssertionError('not refused')


def patchset(mid, sites, regions=(), names=(), version=None, conflicts=()):
    """A format-1 mod without a blob: `sites` [(addr, new, kind)], `regions` [(lo, hi)]."""
    st, img = stock()
    doc = {'elemod': 1, 'id': mid, 'version': '1', 'target': devices.target_of(DEV, REL),
           'sites': [], 'resources': {'regions': [], 'names': list(names)},
           'conflicts': list(conflicts)}
    for addr, new, kind in sites:
        o = addr - DEV.main_load
        doc['sites'].append({'addr': '0x%08x' % addr, 'len': len(new), 'kind': kind,
                             'stock_sha256': sha(img[o:o + len(new)]), 'new': new.hex()})
    for lo, hi in regions:
        doc['resources']['regions'].append({'name': 'code', 'lo': '0x%08x' % lo,
                                            'hi': '0x%08x' % hi})
    if version:
        doc['ele3_version'] = version
    return doc


def write_mod(tmp, doc):
    p = os.path.join(tmp, doc['id'] + '.elemod')
    with open(p, 'w') as fh:
        json.dump(doc, fh)
    return p


# ---- the file family ------------------------------------------------------------------

def test_stock_file_parses():
    st, img = stock()
    assert st.family == 'ELE2' and st.device_id == 0x07 and st.version == '1.73'
    assert [t[0] for t in st.table] == [3] and st.table[0][3] == DEV.main_load
    assert len(img) == REL.main_len and sha(img) == REL.main_sha256


def test_writer_no_change_is_stock():
    st, _img = stock()
    raw = need(SYX)
    assert formats.write(st, st.stored[3], DEV)['syx'] == raw
    assert formats.write(st, st.stored[3], DEV, '1.73')['syx'] == raw


def test_inplace_depack_from_the_stage():
    st, img = stock()
    out, gap = syx.inplace_depack(st.stored[3], DEV)
    assert out == img and gap > 0


def test_repacked_stock_verifies():
    st, img = stock()
    out = formats.write(st, formats.pack_main(img), DEV)
    facts = formats.verify(out, st, img, DEV)
    assert facts['main']['sha256'] == REL.main_sha256 and facts['flash_headroom'] > 0


def test_the_zip_elektron_publishes():
    import io
    import zipfile
    raw = need(SYX)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Analog-Rytm_OS1.73_readme.html', b'<html></html>')
        z.writestr('Analog-Rytm_OS1.73.syx', raw)
    f, dev, rel = formats.load(buf.getvalue())
    assert dev is DEV and rel == REL and formats.main_image(f, DEV) == stock()[1]


def test_verify_refuses_a_changed_header():
    st, img = stock()
    out = formats.write(st, st.stored[3], DEV)
    f = formats.parse(out['syx'], DEV)
    import struct
    from elekloader.codec import transport
    cont = bytearray(f.container)
    cont[5] ^= 1                                       # the build code
    stream = struct.pack('>II', len(cont), transport.content_checksum(bytes(cont))) + bytes(cont)
    bad = transport.encode_syx(stream, f.device_id, f.framing[0], f.framing[1])
    expect(lambda: formats.verify({'syx': bad}, st, img, DEV), 'header')


# ---- patch sets -----------------------------------------------------------------------------

def test_patch_set_builds_and_verifies_keeping_the_version():
    st, img = stock()
    code = bytes.fromhex('4e71' * 8 + '4e75')
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, patchset('rt-a', [(CAVE2[0], code, 'data')],
                                    [(CAVE2[0], CAVE2[0] + 0x40)]))
        outputs, man = patch.build(SYX, [p], log=lambda *a: None)
    o = formats.parse(outputs['syx'], DEV)
    new = formats.main_image(o, DEV)
    assert o.version == '1.73' and man['version'] == '1.73'
    assert new[CAVE2[0] - DEV.main_load:][:len(code)] == code and len(new) == len(img)
    assert man['output']['main']['inplace_min_gap'] > 0


def test_patch_sets_that_share_a_region_or_a_name_are_refused():
    with tempfile.TemporaryDirectory() as tmp:
        a = write_mod(tmp, patchset('rt-a', [(CAVE2[0], b'\x4e\x75', 'data')],
                                    [(CAVE2[0], CAVE2[0] + 0x40)], ['sound-word:0']))
        b = write_mod(tmp, patchset('rt-b', [(CAVE2[0] + 0x80, b'\x4e\x75', 'data')],
                                    [(CAVE2[0] + 0x20, CAVE2[0] + 0x100)], ['sound-word:0']))
        need(SYX)
        msg = expect(lambda: patch.build(SYX, [a, b], check_only=True, log=lambda *x: None),
                     'overlap')
        assert 'sound-word:0' in msg


def test_refuses_the_protected_bootstrap_copy():
    lo, hi, _why = DEV.protected[0]
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, patchset('rt-bad', [(lo + 0x100, b'\x4e\x71', 'data')]))
        need(SYX)
        expect(lambda: patch.build(SYX, [p], log=lambda *a: None), 'protected')
    st, img = stock()
    bad = bytearray(img)
    bad[lo - DEV.main_load + 0x100] ^= 1
    outputs = formats.write(st, formats.pack_main(bytes(bad)), DEV)
    expect(lambda: formats.verify(outputs, st, bytes(bad), DEV), 'not stock')


def test_version_is_four_characters():
    st, img = stock()
    out = formats.write(st, st.stored[3], DEV, '1.7X')
    assert formats.parse(out['syx'], DEV).version == '1.7X'
    formats.verify(out, st, img, DEV, '1.7X')
    expect(lambda: formats.write(st, st.stored[3], DEV, '1.73a'), '4')


def test_no_linkable_mods_yet():
    doc = {'elemod': 2, 'id': 'x', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sections': {}}
    m = link.Mod2(doc, 'x')
    _st, img = stock()
    expect(lambda: link.link([m], img), 'no linkable')


def test_a_digitakt_file_is_not_this_family():
    st, _img = stock()
    dt = [d for d in devices.devices() if d.key == 'digitakt-mk1'][0]
    expect(lambda: formats.parse(st.raw, dt), 'ELE2')


def test_mkmod_diff_round_trip():
    st, img = stock()
    changed = bytearray(img)
    o = CAVE2[0] - DEV.main_load
    changed[o:o + 4] = b'\x4e\x71\x4e\x75'
    built = formats.write(st, formats.pack_main(bytes(changed)), DEV)
    with tempfile.TemporaryDirectory() as tmp:
        bp = os.path.join(tmp, 'built.syx')
        with open(bp, 'wb') as fh:
            fh.write(built['syx'])
        meta = os.path.join(tmp, 'meta.json')
        with open(meta, 'w') as fh:
            json.dump({'id': 'diffed', 'title': 'a diffed build'}, fh)
        out = os.path.join(tmp, 'diffed.elemod')
        rc = mkmod.main(['--stock', SYX, '--build', bp, '--diff', '--meta', meta, '--out', out])
        assert rc == 0
        m = elemod.load_any(out)
        assert m.blob is None and len(m.sites) == 1
        assert elemod.apply([m], img) == bytes(changed)


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
