# SPDX-License-Identifier: GPL-2.0-or-later
"""The Digitone mk1 (and Digitone Keys): its profile, its file, whole builds
(pytest, or run with python).

Needs the stock file, which never goes in the repo, named by an environment
variable; a test whose input is missing is skipped, not passed:
  ELEKLOADER_DN_SYX   Digitone_and_Digitone_Keys_OS1.43.syx
"""
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, formats, link, mkmod, patch, syx   # noqa: E402
from elekloader.elemod import sha                                         # noqa: E402

SYX = os.environ.get('ELEKLOADER_DN_SYX', '')
DEV = [d for d in devices.devices() if d.key == 'digitone-mk1'][0]
REL = DEV.releases['1.43']


class Skip(Exception):
    pass


def need(p):
    if not p or not os.path.exists(p):
        raise Skip('missing %s' % (p or 'ELEKLOADER_DN_SYX'))
    with open(p, 'rb') as fh:
        return fh.read()


_c = {}


def stock():
    if 'st' not in _c:
        _c['raw'] = need(SYX)
        _c['st'], dev, rel = formats.load(_c['raw'])
        assert dev is DEV and rel == REL
        _c['img'] = formats.main_image(_c['st'], DEV)
    return _c['st'], _c['img']


def expect(fn, *words):
    try:
        fn()
    except (formats.FormatError, elemod.ModError, patch.PatchError) as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return str(e)
    raise AssertionError('not refused')


def bundle(sites=(), blob=b'', version=None):
    """A format-1 mod for the Digitone: data `sites` [(addr, new)], a blob."""
    st, img = stock()
    doc = {'elemod': 1, 'id': 'dn-test', 'version': '1', 'target': devices.target_of(DEV, REL),
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
    return doc


def a_string_site(text=b'FACTORY RESET'):
    """(address, same-length replacement) for a string of the main OS."""
    st, img = stock()
    o = img.find(text)
    assert o > 0, text
    return DEV.main_load + o, text.lower()


def write_mod(tmp, doc, name='dn-test.elemod'):
    p = os.path.join(tmp, name)
    with open(p, 'w') as fh:
        json.dump(doc, fh)
    return p


# ---- the file ------------------------------------------------------------------------------

def test_stock_file_parses():
    st, img = stock()
    assert st.device_id == 0x0D and st.version == '1.43' and st.data_start == 0xA0
    assert [t[0] for t in st.table] == [5, 2, 3, 4, 6, 7, 8]
    assert len(img) == REL.main_len and sha(img) == REL.main_sha256


def test_writer_no_change_is_stock():
    st, img = stock()
    assert formats.write(st, st.stored[3], DEV)['syx'] == _c['raw']


def test_inplace_depack_from_the_stage():
    st, img = stock()
    out, gap = syx.inplace_depack(st.stored[3], DEV)
    assert out == img and gap > 0


def test_the_zip_elektron_publishes():
    raw = need(SYX)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Digitone_and_Digitone_Keys_OS1.43_dist/Digitone_and_Digitone_Keys_OS1.43.syx', raw)
        z.writestr('Digitone_and_Digitone_Keys_OS1.43_dist/readme.html', b'<html></html>')
    f, dev, rel = formats.load(buf.getvalue())
    assert dev is DEV and rel == REL and f.raw == raw


# ---- whole builds ----------------------------------------------------------------------------

def test_whole_build_data_site_and_blob():
    st, img = stock()
    site = a_string_site()
    blob = bytes(range(256)) * 8
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([site], blob, version='DN01'))
        outputs, man = patch.build(SYX, [p], log=lambda *a: None)
    assert set(outputs) == {'syx'}
    o = formats.parse(outputs['syx'], DEV)
    new = formats.main_image(o, DEV)
    assert new[site[0] - DEV.main_load:][:len(site[1])] == site[1]
    assert new[len(img):] == blob and len(new) == len(img) + len(blob)
    assert o.version == 'DN01'
    assert all(o.stored[k] == st.stored[k] for k in (5, 2, 4, 6, 7, 8))   # the rest stays stock
    assert man['output']['main']['inplace_min_gap'] > 0


def test_version_is_four_characters():
    st, img = stock()
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([a_string_site()]))
        expect(lambda: patch.build(SYX, [p], version='DN1', log=lambda *a: None), '4')


def test_no_linkable_mods_yet():
    doc = {'elemod': 2, 'id': 'x', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sections': {}}
    st, img = stock()
    expect(lambda: link.link([link.Mod2(doc, 'x')], img), 'no linkable')


def test_a_digitakt_mod_is_refused():
    dt = devices.devices()[0]
    doc = {'elemod': 1, 'id': 'dt', 'version': '1',
           'target': devices.target_of(dt, dt.releases['1.53']), 'sites': []}
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, doc, 'dt.elemod')
        need(SYX)
        expect(lambda: patch.build(SYX, [p], version='DN01', log=lambda *a: None), 'Digitakt')


def test_mkmod_diff_round_trip():
    st, img = stock()
    changed = bytearray(img)
    addr, new = a_string_site()
    o = addr - DEV.main_load
    changed[o:o + len(new)] = new
    changed += bytes(range(100))
    built = formats.write(st, formats.pack_main(bytes(changed)), DEV, 'DN02')
    with tempfile.TemporaryDirectory() as tmp:
        bp = os.path.join(tmp, 'built.syx')
        with open(bp, 'wb') as fh:
            fh.write(built['syx'])
        meta = os.path.join(tmp, 'meta.json')
        with open(meta, 'w') as fh:
            json.dump({'id': 'diffed', 'title': 'a diffed build'}, fh)
        out = os.path.join(tmp, 'diffed.elemod')
        assert mkmod.main(['--stock', SYX, '--build', bp, '--diff', '--meta', meta, '--out', out]) == 0
        m = elemod.load_any(out)
        assert elemod.apply([m], img) == bytes(changed)
        outputs, man = patch.build(SYX, [out], log=lambda *a: None)
        assert man['bundle_matches_build'] and formats.parse(outputs['syx'], DEV).version == 'DN02'


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
