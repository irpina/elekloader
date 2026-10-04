# SPDX-License-Identifier: GPL-2.0-or-later
"""The Digitakt II: its profile, its sealed file, whole builds
(pytest, or run with python).

Needs the stock file, which never goes in the repo, named by an environment
variable; a test whose input is missing is skipped, not passed:
  ELEKLOADER_DT2_SYX   Digitakt_II_OS1.17.syx
"""
import dataclasses
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, formats, link, patch, syx   # noqa: E402
from elekloader.codec import transport                              # noqa: E402
from elekloader.elemod import sha                                   # noqa: E402

SYX = os.environ.get('ELEKLOADER_DT2_SYX', '')
DEV = [d for d in devices.devices() if d.key == 'digitakt-mk2'][0]
REL = DEV.releases['1.17']


class Skip(Exception):
    pass


def need(p):
    if not p or not os.path.exists(p):
        raise Skip('missing %s' % (p or 'ELEKLOADER_DT2_SYX'))
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
    except (formats.FormatError, elemod.ModError, patch.PatchError, syx.SyxError) as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return str(e)
    raise AssertionError('not refused')


def bundle(sites=(), blob=b'', version=None):
    """A format-1 mod for the Digitakt II: data `sites` [(addr, new)], a blob."""
    st, img = stock()
    doc = {'elemod': 1, 'id': 'dt2-test', 'version': '1', 'target': devices.target_of(DEV, REL),
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


def write_mod(tmp, doc, name='dt2-test.elemod'):
    p = os.path.join(tmp, name)
    with open(p, 'w') as fh:
        json.dump(doc, fh)
    return p


def reseal(st, container):
    """-> .syx bytes for `container` (an ELE3 container, trailer included)."""
    stream = (len(container).to_bytes(4, 'big')
              + transport.content_checksum(container).to_bytes(4, 'big') + container)
    return transport.encode_syx(stream, st.device_id, st.framing[0], st.framing[1])


# ---- the file ------------------------------------------------------------------------------

def test_stock_file_parses():
    st, img = stock()
    assert st.device_id == 0x14 and st.version == '1.17' and st.data_start == 0x90
    assert [t[0] for t in st.table] == [5, 2, 3, 4, 7, 8]
    assert len(img) == REL.main_len and sha(img) == REL.main_sha256


def test_the_seal_is_the_last_32_bytes_and_verifies():
    st, img = stock()
    end = max(off + n for _s, off, n, _d in st.table)
    assert st.total == end + (-end % 16) + syx.DIGEST
    import hashlib, hmac
    key = syx.seal_key(st, DEV)
    assert hmac.new(key, st.container[:-32], hashlib.sha256).digest() == st.container[-32:]


def test_writer_no_change_is_stock():
    st, img = stock()
    assert formats.write(st, st.stored[3], DEV)['syx'] == _c['raw']


def test_inplace_depack_from_the_stage():
    st, img = stock()
    out, gap = syx.inplace_depack(st.stored[3], DEV)
    assert out == img and gap > 0


def test_verify_refuses_a_broken_seal():
    """The check's other side: one trailer bit flipped, every checksum redone."""
    st, img = stock()
    bad = bytearray(st.container)
    bad[-1] ^= 1
    expect(lambda: syx.verify(reseal(st, bytes(bad)), st, img, DEV), 'HMAC')
    syx.verify(reseal(st, st.container), st, img, DEV)        # the unbroken one passes


def test_writer_refuses_a_stock_file_whose_seal_fails():
    st, img = stock()
    bad = bytearray(st.container)
    bad[-1] ^= 1
    broken = syx.Syx(reseal(st, bytes(bad)))
    expect(lambda: syx.write(broken, st.stored[3], DEV), 'seal')


def test_writer_refuses_a_device_whose_seed_is_not_in_the_bootstrap():
    st, img = stock()
    other = dataclasses.replace(DEV, hmac_key_from=(2, b'Multiplier'))    # the Digitone II's
    expect(lambda: syx.write(st, st.stored[3], other), 'seed')


# ---- whole builds ----------------------------------------------------------------------------

def test_whole_build_data_site_and_blob():
    st, img = stock()
    site = a_string_site()
    blob = bytes(range(256)) * 8
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([site], blob, version='DT01'))
        outputs, man = patch.build(SYX, [p], log=lambda *a: None)
    assert set(outputs) == {'syx'}
    o = formats.parse(outputs['syx'], DEV)
    new = formats.main_image(o, DEV)
    assert new[site[0] - DEV.main_load:][:len(site[1])] == site[1]
    assert new[len(img):] == blob and len(new) == len(img) + len(blob)
    assert o.version == 'DT01'
    assert all(o.stored[k] == st.stored[k] for k in (5, 2, 4, 7, 8))   # the rest stays stock
    import hashlib, hmac
    assert hmac.new(syx.seal_key(st, DEV), o.container[:-32],
                    hashlib.sha256).digest() == o.container[-32:]
    assert man['output']['main']['inplace_min_gap'] > 0


def test_a_build_past_the_flash_store_is_refused():
    """The OS keeps a store at flash 0x380000: the container must end below
    it. A main OS grown with incompressible bytes past the room (a blob that
    big is refused before this, at the DDR area's size)."""
    st, img = stock()
    room = DEV.flash_limit - DEV.flash_at - st.total
    big = img + os.urandom(room + 0x1000)
    out = syx.write(st, syx.pack_main(big), DEV)
    expect(lambda: syx.verify(out, st, big, DEV), '0x380000')
    with tempfile.TemporaryDirectory() as tmp:
        p = write_mod(tmp, bundle([], os.urandom(DEV.ddr[1] - DEV.ddr[0] + 1), version='DT02'))
        expect(lambda: patch.build(SYX, [p], log=lambda *a: None), 'blob', 'allows')


def test_linkable_mods_need_the_digitakt_ii_core():
    """The Digitakt II links format-2 mods in its own DDR area, with its own
    core (mods/core-dt2)."""
    assert DEV.linkable() and DEV.ddr == (0x47F00000, 0x47F40000)
    assert not DEV.fast_table                      # no .fast copy table yet
    addr, new = a_string_site()
    st, img = stock()
    o = addr - DEV.main_load
    doc = {'elemod': 2, 'id': 'x', 'version': '1', 'target': devices.target_of(DEV, REL),
           'sections': {}, 'requires': ['core'],
           'sites': [{'addr': '0x%08x' % addr, 'len': len(new), 'kind': 'data',
                      'stock_sha256': sha(img[o:o + len(new)]), 'new': new.hex()}]}
    problems = link.check([link.Mod2(doc, 'x')], img)
    assert any('requires core' in p for p in problems), problems


def test_the_areas_are_outside_what_the_os_clears_and_copies():
    """The boot copier runs before the OS clears 0x40312000-0x47E28470 and
    fills SRAM, so .run must lie above the clear, and SRAM is only free from
    the end of each half's copied data. Read from the reset code itself."""
    st, img = stock()
    def word(a):
        return int.from_bytes(img[a - DEV.main_load:a - DEV.main_load + 4], 'big')
    assert word(0x400004bc) == 0x40312000 and word(0x400004c2) == 0x47E28470   # the clear
    assert word(0x40000472) == 0x40318e80 and word(0x4000049a) == 0x4031ff60   # the copies' ends
    clear_end = word(0x400004c2)
    lo, hi = DEV.ddr
    assert clear_end <= lo and hi <= 0x48000000
    first = 0x80000000 + (0x40318e80 - 0x40312000)
    second = 0x80008000 + (0x4031ff60 - 0x40318e80)
    assert DEV.areas['sram-block'][0] >= first and DEV.areas['sram-block'][1] == 0x80008000
    assert DEV.areas['sram-tail'][0] >= second and DEV.areas['sram-tail'][1] == 0x80010000


def test_core_builds_links_and_verifies():
    """mods/core-dt2 built with the SDK, then a build with it alone."""
    import shutil
    from elekloader.sdk import build
    need(SYX)
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', DEV.toolchain['prefix']) + 'as'):
        raise Skip('no cross assembler (ELEKLOADER_CROSS)')
    root = os.path.dirname(HERE)
    with tempfile.TemporaryDirectory() as tmp:
        core, m = build.build(os.path.join(root, 'mods', 'core-dt2'), SYX, tmp)
        outputs, man = patch.build(SYX, [core], version='DT03', log=lambda *a: None)
    st, img = stock()
    o = formats.parse(outputs['syx'], DEV)
    new = formats.main_image(o, DEV)
    for site, stock_bytes in ((0x40000538, '4eb9400019b0'), (0x40032ad4, '4eb94011bc60'),
                              (0x40032b3a, '4eb94011bc96'), (0x40033d94, '4eb940030bd0'),
                              (0x40033dde, '4eb940030b64')):
        a = site - DEV.main_load
        assert img[a:a + 6].hex() == stock_bytes
        assert new[a:a + 2] == b'\x4e\xb9' and new[a + 2:a + 6] != img[a + 2:a + 6], hex(site)
    assert new[:len(img)][:0x138] == img[:0x138]
    assert man['output']['main']['inplace_min_gap'] > 0


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
