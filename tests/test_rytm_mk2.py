# SPDX-License-Identifier: GPL-2.0-or-later
"""The Analog Rytm MKII: its profile, its file, and core-ar2's sites (pytest,
or run with python).

Needs a stock file, which never goes in the repo, named by an environment
variable; a test whose input is missing is skipped, not passed:
  ELEKLOADER_AR2_SYX   Analog-Rytm_MKII_OS1.73.syx or ...OS1.74.syx

The addresses below are 1.73's. 1.74's main OS is 1.73's with code added in
two places (Outbox 8's main-output routing), so what follows each moved:
see moved().
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, elemod, formats, syx   # noqa: E402
from elekloader.sdk import build                        # noqa: E402

SYX = os.environ.get('ELEKLOADER_AR2_SYX', '')
DEV = [d for d in devices.devices() if d.key == 'analog-rytm-mk2'][0]
REL = None                                              # the stock file's


def moved(addr):
    """1.73's address -> the same code's in the stock file's release."""
    if REL.version == '1.73' or addr < 0x40057000:
        return addr
    if 0x40057080 <= addr < 0x40123e00:
        return addr + 0x6c
    if 0x40123e80 <= addr < 0x401b4f00:
        return addr + 0x1cc
    raise ValueError('no 1.74 address for %#x' % addr)


class Skip(Exception):
    pass


_c = {}


def stock():
    if 'st' not in _c:
        if not SYX or not os.path.exists(SYX):
            raise Skip('missing %s' % (SYX or 'ELEKLOADER_AR2_SYX'))
        with open(SYX, 'rb') as fh:
            _c['raw'] = fh.read()
        _c['st'], dev, rel = formats.load(_c['raw'])
        assert dev is DEV
        global REL
        REL = rel
        _c['img'] = formats.main_image(_c['st'], DEV)
    return _c['raw'], _c['st'], _c['img']


def at(img, addr, n):
    a = moved(addr)
    return img[a - DEV.main_load:a - DEV.main_load + n]


def test_profile():
    assert DEV.linkable() and DEV.flash_limit == 0x300000 and DEV.trailer is None
    assert (DEV.flash_limit - DEV.flash_at) % 0x40000 == 0      # whole 256 KB units
    assert DEV.ddr == DEV.areas['ddr'] == (0x47BE0000, 0x47C00000)


def test_the_file_and_the_writer():
    """Five sections (5, 2, 1, 3, 8), no trailer; from its own main OS
    stream the writer gives the stock file back byte for byte."""
    raw, st, img = stock()
    assert [s for s, _o, _l, _d in st.table] == [5, 2, 1, 3, 8]
    assert syx.sha(img) == REL.main_sha256 and len(img) == REL.main_len
    assert formats.write(st, st.stored[DEV.main_section], DEV)['syx'] == raw
    _im, gap = syx.inplace_depack(st.stored[DEV.main_section], DEV)
    assert gap > 0


def test_a_repack_verifies_inside_the_flash_limit():
    raw, st, img = stock()
    out = formats.write(st, formats.pack_main(img, DEV), DEV, version='AR01')
    facts = formats.verify(out, st, img, DEV, version='AR01')
    assert facts['flash_headroom'] > 0 and facts['main']['inplace_min_gap'] > 0


def test_the_os_entry_is_the_digitakts():
    """SP := 0x48000000, the same peripheral writes, and the third setup
    call (the boot site) sets VBR to 0x40000000."""
    _r, _s, img = stock()
    assert struct.unpack('>I', img[:4])[0] == 0x40000870
    assert at(img, 0x4000087a, 6) == bytes.fromhex('2e7c48000000')
    assert at(img, 0x40000882, 6) == bytes.fromhex('41f9fc04002d')
    assert at(img, 0x400008c0, 6) == bytes.fromhex('4eb9400014cc')
    assert at(img, 0x400014cc, 12) == bytes.fromhex('203c400000004e7b08014e75')


def test_the_os_stores_from_0x300000():
    """The settings store at 0x380000-0x400000, as on the Digitakt mk1, and a
    second at 0x300000-0x380000: flash_limit is 0x300000."""
    _r, _s, img = stock()
    push = lambda v: bytes.fromhex('2f3c') + v.to_bytes(4, 'big')
    assert img.count(push(0x380000)) == 42 and img.count(push(0x3c0000)) == 16
    assert img.count(push(0x300000)) == 7 and img.count(push(0x340000)) == 7
    # read(0x300000, 0x1b072, 0x4198911a) at 0x400fad5a
    assert at(img, 0x400fad5a, 20) == bytes.fromhex('48794198911a2f3c0001b0722f3c003000004eb9')
    assert at(img, 0x400fad5a + 20, 4) == moved(0x40136faa).to_bytes(4, 'big')


def test_core_ar2_sites():
    """Every site's stock bytes, and that each covers whole instructions."""
    _r, _s, img = stock()
    with open(os.path.join(ROOT, 'mods', 'core-ar2', 'mod.json')) as fh:
        mod, _port = build.for_release(json.load(fh), DEV, REL)
    assert mod['device'] == DEV.key and mod['os'] == REL.version
    for s in mod['sites']:
        a, want = int(s['addr'], 16), bytes.fromhex(s['stock'])
        assert img[a - DEV.main_load:a - DEV.main_load + len(want)] == want, s
        ok, note = elemod.insn_check(img, a, len(want), DEV)
        assert ok, (s, note)
    d = mod['defsym']
    # the render handler's frame, which core_render_out restores from
    assert at(img, 0x4011fafa, 4) == bytes.fromhex('4e56') + (-int(d['RENDER_FRAME'], 16) & 0xffff).to_bytes(2, 'big')
    # SETTINGS: the jmp's 6 bytes, then where core_settings rejoins
    assert int(d['SETTINGS_RET'], 16) == moved(0x400db87e) + 6
    # and the rest are where 1.73's are, moved
    with open(os.path.join(ROOT, 'mods', 'core-ar2', 'mod.json')) as fh:
        d73 = json.load(fh)['defsym']
    for k, v in d73.items():
        if v.lower().startswith('0x4'):
            assert int(d[k], 16) == moved(int(v, 16)), k


def test_no_copy_of_the_bootstrap_in_the_main_os():
    """The main OS holds no copy of the bootstrap (section 2). No 512 bytes of
    its first 0x7d94 (zero-padded tables and data follow them) are in
    the main OS, no 2 KB anywhere in it with more than 32 distinct byte
    values is, and its stored (packed) bytes share nothing. What the two do
    share is pieces of tables and data."""
    _r, st, img = stock()
    boot, packed = st.section(2), st.stored[2]
    for o in range(0, 0x7d94 - 512, 64):
        assert boot[o:o + 512] not in img, hex(o)
    for o in range(0, len(boot) - 2048, 64):
        w = boot[o:o + 2048]
        assert len(set(w)) <= 32 or w not in img, hex(o)
    for o in range(0, len(packed) - 32, 32):
        assert packed[o:o + 32] not in img, hex(o)


def test_every_flash_write_and_erase_in_the_os_is_known():
    """The SPI NOR routines (program 0x40136fae; erase 0x4013702a, 0x40136bae,
    0x40136cd0, 0x40136aaa, 0x40136e88, 0x401366d6) are reached only from:
    the store at 0x300000 (0x400fac00-0x400fb200), the settings store at
    0x380000 (0x40139100-0x40139b10), the factory console (0x4013a068-
    0x4013bf98: "READY FOR BOOTSTRAP" writes a received bootstrap at
    0x40000, "READY FOR OS" a received container from 0x80000), the in-OS
    upgrade (0x4009f3a0-0x4009f460: erase and write from 0x80000), and an
    erase of 0x400000, 0x800000 and 0xc00000 (0x401229f0-0x40122a30). Each
    writes what it received or a store, never bytes of the main OS image:
    nothing in it is a bootstrap the OS could re-flash, so no protected range."""
    _r, _s, img = stock()
    known = [(0x400fac00, 0x400fb200), (0x40139100, 0x40139b10), (0x4013a068, 0x4013bf98),
             (0x4009f3a0, 0x4009f460), (0x401229f0, 0x40122a30)]
    known = [(moved(lo), moved(hi)) for lo, hi in known]
    for routine in (0x40136fae, 0x4013702a, 0x40136bae, 0x40136cd0, 0x40136aaa, 0x40136e88, 0x401366d6):
        word, i, refs = moved(routine).to_bytes(4, 'big'), 0, []
        while True:
            i = img.find(word, i)
            if i < 0:
                break
            refs.append(DEV.main_load + i - 2)
            i += 2
        assert refs, hex(routine)
        for r in refs:
            assert any(lo <= r < hi for lo, hi in known), (hex(routine), hex(r))
    assert at(img, 0x4009f3c2, 6) == bytes.fromhex('267c00080000')        # a3 = 0x80000
    assert at(img, 0x4013bea0, 6) == bytes.fromhex('2f3c00040000')        # the bootstrap at 0x40000


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
