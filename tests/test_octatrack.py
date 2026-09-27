"""The Octatrack: its file family (elek.py), its profile, whole builds (pytest,
or run with python).

Needs the stock files, which never go in the repo, named by environment
variables; a test whose inputs are missing is skipped, not passed:
  ELEKLOADER_OT_SYX   OCTATRACK_OS1.40C.syx
  ELEKLOADER_OT_BIN   OCTATRACK_OS1.40C.bin
"""
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

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


def test_no_linkable_mods_yet():
    doc = {'elemod': 2, 'id': 'x', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sections': {}}
    m = link.Mod2(doc, 'x')
    st, img = stock()
    expect(lambda: link.link([m], img), 'no linkable')


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
