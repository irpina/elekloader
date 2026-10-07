# SPDX-License-Identifier: GPL-2.0-or-later
"""Unit tests that need no firmware (pytest, or run with python)."""
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, link, syx         # noqa: E402
from elekloader.codec import aplib, elz, transport       # noqa: E402

FRAMING0 = bytes.fromhex('f000203c0a007f010500017200000000f7')[:15] + b'\xf7'
FRAMING1 = bytes.fromhex('f000203c0a007f020500017200000000f7')[:15] + b'\xf7'


def test_requirements_are_ticked_with_a_mod():
    from elekloader.gui import with_requirements
    d = {
        'lib/slicer.elemod': {'id': 'slicer', 'fits': True, 'requires': ['core']},
        'lib/health.elemod': {'id': 'health', 'fits': True, 'requires': ['core']},
        'app/core-2.0a.elemod': {'id': 'core', 'fits': True, 'requires': []},
        'lib/core-1.0.elemod': {'id': 'core', 'fits': False, 'requires': []},
        'lib/opts.elemod': {'id': 'opts', 'fits': True, 'requires': ['core', 'fast']},
    }
    # core comes with the first mod that needs it: the one made for this firmware
    assert with_requirements(d, set(), 'lib/slicer.elemod') == {
        'lib/slicer.elemod', 'app/core-2.0a.elemod'}
    # an enabled core is not doubled
    on = {'lib/slicer.elemod', 'app/core-2.0a.elemod'}
    assert with_requirements(d, on, 'lib/health.elemod') == on | {'lib/health.elemod'}
    # a requirement nothing provides is left for the check to report
    assert with_requirements(d, set(), 'lib/opts.elemod') == {
        'lib/opts.elemod', 'app/core-2.0a.elemod'}
    # a mod that requires nothing adds only itself
    assert with_requirements(d, set(), 'app/core-2.0a.elemod') == {'app/core-2.0a.elemod'}


def test_versions_sort_and_the_core_a_build_takes():
    order = ['', '0.13a', '0.13b', '2', '2.0', '2.0a', '2.1', '2.9', '2.10', '3.0', '10.0']
    assert sorted(reversed(order), key=elemod.version_key) == order
    assert elemod.pick_core(['2.1', '3.0', '2.0a']) == 0
    assert elemod.pick_core(['2.1', '3.0', '2.0a'], '2.1') == 0
    assert elemod.pick_core(['2.1', '3.0', '2.0a'], '2.2') == 1
    assert elemod.pick_core(['2.1', '3.0', '3.1'], '3.0') == 2
    assert elemod.pick_core(['2.1', '2.1']) == 1                 # the last of equals
    assert elemod.pick_core(['2.1', '3.0'], '3.1') is None
    assert elemod.pick_core([]) is None


def test_a_mod_that_needs_core_3_ticks_core_3():
    from elekloader.gui import one_core, with_requirements
    d = {
        'app/core-2.1.elemod': {'id': 'core', 'version': '2.1', 'fits': True, 'requires': []},
        'app/core-3.0.elemod': {'id': 'core', 'version': '3.0', 'fits': True, 'requires': []},
        'lib/health.elemod': {'id': 'health', 'fits': True, 'requires': ['core']},
        'lib/pages.elemod': {'id': 'pages', 'fits': True, 'requires': ['core'],
                             'needs_core': '3.0'},
        'lib/nb.elemod': {'id': 'nb', 'fits': True, 'requires': ['core', 'pages'],
                          'needs_core': '3.0'},
        'lib/later.elemod': {'id': 'later', 'fits': True, 'requires': ['core'],
                             'needs_core': '4.0'},
    }
    c21, c30 = 'app/core-2.1.elemod', 'app/core-3.0.elemod'
    # what needs nothing from 3.0 builds on 2.1, as before 3.0 was there
    assert with_requirements(d, set(), 'lib/health.elemod') == {'lib/health.elemod', c21}
    # what needs it brings 3.0, through its requirements too, in 2.1's place
    assert with_requirements(d, {'lib/health.elemod', c21}, 'lib/nb.elemod') == {
        'lib/health.elemod', 'lib/nb.elemod', 'lib/pages.elemod', c30}
    # a core chosen by hand that will do is kept
    assert with_requirements(d, {c30}, 'lib/health.elemod') == {c30, 'lib/health.elemod'}
    # none new enough: the newest, for the check to say why
    assert with_requirements(d, set(), 'lib/later.elemod') == {'lib/later.elemod', c30}
    assert with_requirements(d, {c21}, 'lib/later.elemod') == {'lib/later.elemod', c21}
    # the first run's ticks: one core
    assert one_core(d, {c21, c30, 'lib/health.elemod'}) == {c21, 'lib/health.elemod'}
    assert one_core(d, {c21, c30, 'lib/pages.elemod'}) == {c30, 'lib/pages.elemod'}


def test_8in7_round_trip():
    rnd = random.Random(1)
    for n in (0, 1, 6, 7, 8, 13, 14, 101, 250):
        data = bytes(rnd.getrandbits(8) for _ in range(n))
        enc = transport.encode_8in7(data)
        out, k = bytearray(), 0
        while k < len(enc):
            ms = enc[k]
            k += 1
            for m in range(7):
                if k >= len(enc):
                    break
                out.append(enc[k] | (0x80 if (ms >> (6 - m)) & 1 else 0))
                k += 1
        assert bytes(out) == data and all(b < 0x80 for b in enc)


def test_packer_round_trip():
    rnd = random.Random(2)
    cases = [b'', b'A', bytes(range(256)) * 3, b'\x00' * 5000,
             bytes(rnd.getrandbits(8) for _ in range(3000)),
             (b'ColdFire' * 400 + bytes(rnd.getrandbits(8) for _ in range(700))) * 3]
    for data in cases:
        packed = aplib.pack_section(data)
        assert syx.classify(packed) == 'packed'
        assert elz.depack_section(packed) == data


def _container(sections):
    """[(id, dest, stored)] -> a container laid out like the mk1 files."""
    cont = bytearray(0x80)
    cont[:4] = b'ELE3'
    cont[0x14:0x18] = b'1.00'
    struct.pack_into('>I', cont, 0x1C, len(sections))
    for i, (sid, dest, data) in enumerate(sections):
        struct.pack_into('>IIII', cont, 0x20 + 16 * i, sid, len(cont), len(data), dest)
        cont += data
        cont += bytes(-len(cont) % 16)
    return bytes(cont)


def test_transport_and_parser_round_trip():
    body = b'main os image ' * 300
    cont = _container([(5, 0, b'meta'), (3, 0x40000400, aplib.pack_section(body)),
                       (4, 0x80000400, struct.pack('>II', 16, 0) + bytes(range(1, 17)))])
    stream = struct.pack('>II', len(cont), transport.content_checksum(cont)) + cont
    raw = transport.encode_syx(stream, 0x0A, FRAMING0, FRAMING1)
    s = syx.Syx(raw)
    assert s.container == cont and not any(s.tail)
    assert [t[0] for t in s.table] == [5, 3, 4]
    assert s.section(3) == body and s.section(4) == bytes(range(1, 17)) and s.version == '1.00'
    for m in s.data:
        assert transport.packet_checksum(m[1:-1], s.k) == m[-2]
    n = (s.framing[0][12] << 14) | (s.framing[0][13] << 7) | s.framing[0][14]
    assert n == len(s.data)


def test_a_longer_section_table_moves_the_data_start():
    """Seven sections (the Digitone mk1's) end the table at 0x90, and the data
    starts at 0xA0: the reader finds it there and the writer keeps it."""
    body = b'another main os ' * 300
    secs = [(5, 0, b'meta'), (2, 0x02000802, b'boot' * 10), (3, 0x40000400, aplib.pack_section(body)),
            (4, 0x80000400, b'upd' * 7), (6, 0, b'six'), (7, 0, b'dsp' * 40), (8, 0, b'eight')]
    cont = bytearray(0xA0)
    cont[:4] = b'ELE3'
    cont[0x14:0x18] = b'1.43'
    struct.pack_into('>I', cont, 0x1C, len(secs))
    for i, (sid, dest, data) in enumerate(secs):
        struct.pack_into('>IIII', cont, 0x20 + 16 * i, sid, len(cont), len(data), dest)
        cont += data
        cont += bytes(-len(cont) % 16)
    cont = bytes(cont)
    stream = struct.pack('>II', len(cont), transport.content_checksum(cont)) + cont
    raw = transport.encode_syx(stream, 0x0A, FRAMING0, FRAMING1)     # the framing's device byte
    s = syx.Syx(raw)
    assert s.data_start == 0xA0 and s.section(3) == body and [t[0] for t in s.table] == [5, 2, 3, 4, 6, 7, 8]
    dev = devices.devices()[0]
    assert syx.write(s, s.stored[3], dev) == raw
    out = syx.write(s, aplib.pack_section(body + b'!'), dev, 'ABCD')
    o = syx.Syx(out)
    assert o.data_start == 0xA0 and o.section(3) == body + b'!' and o.version == 'ABCD'
    assert all(o.stored[k] == s.stored[k] for k in (5, 2, 4, 6, 7, 8))


def test_elek_transport_and_card_file_round_trip():
    from elekloader import elek
    body = b'octatrack main os ' * 400
    sec = aplib.pack_section(body)
    for extra in (0, 1, 2, 62, 63, 64):                 # every short-final-message shape
        cont = elek.MAGIC + b'0178' + b'     1.00X' + sec + bytes(extra)
        raw = elek.encode_syx(cont, 0x05)
        dev_id, back = elek.decode_syx(raw)
        assert dev_id == 5 and back == cont
        seed, padded = elek.decode_bin(elek.encode_bin(cont, 0x12345678))
        assert seed == 0x12345678 and padded == cont + bytes(-len(cont) % 4)
    f = elek.ElekFile(elek.encode_syx(elek.MAGIC + b'0178' + b'     1.00X' + sec, 5))
    assert f.section(3) == body and f.version == '1.00X' and f.build == '0178'


def test_a_zip_without_a_known_os_is_refused():
    import io
    import zipfile
    from elekloader import formats
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('dist/Some_OS.syx', b'\xf0\x00\x20\x3c\xf7')
        z.writestr('dist/readme.txt', b'hello')
    try:
        formats.load(buf.getvalue())
    except devices.UnknownFirmware as e:
        assert 'holds no stock firmware' in str(e) and 'dist/Some_OS.syx' in str(e)
    else:
        raise AssertionError('accepted a zip with no known OS file')
    try:
        formats.load(b'PK\x03\x04' + bytes(100))
    except formats.FormatError as e:
        assert 'zip' in str(e)
    else:
        raise AssertionError('accepted a broken zip')


def test_inplace_depack_gap():
    body = bytes(random.Random(3).getrandbits(8) for _ in range(20000))
    dev = devices.devices()[0]
    img, gap = syx.inplace_depack(aplib.pack_section(body), dev)
    assert img == body and gap > 0


def test_overlaps():
    spans = [(0, 100, 'a'), (10, 20, 'b'), (50, 60, 'c'), (100, 110, 'd')]
    pairs = {(a[2], b[2]) for a, b in elemod.overlaps(spans)}
    assert pairs == {('a', 'b'), ('a', 'c')}


def test_devices():
    d, r = devices.identify(devices.devices()[0].releases['1.53'].syx_sha256)
    assert d.key == 'digitakt-mk1' and r.version == '1.53'
    assert d.image_end(r) == 0x4025CA40
    assert devices.for_target(devices.target_of(d, r)) == (d, r)
    for bad in ('0' * 64, ''):
        try:
            devices.identify(bad)
        except devices.UnknownFirmware:
            pass
        else:
            raise AssertionError('accepted an unknown firmware')
    try:
        devices.for_target({'syx_sha256': '0' * 64})
    except devices.UnknownFirmware:
        pass
    else:
        raise AssertionError('accepted an unknown target')


def test_dsp_payload_walk():
    """dsp.records on a made-up payload: records, two-word directives anywhere, the end; and
    the profiles' DSP areas lie inside their payloads' tags."""
    import dataclasses
    from elekloader import dsp
    from elekloader.elemod import ModError

    def w(*ws):
        return b''.join(bytes((x & 0xFF, (x >> 8) & 0xFF, x >> 16)) for x in ws)
    ot = [d for d in devices.devices() if d.key == 'octatrack'][0]
    body = w(3, 0x3000, 4, 0, 0, 0x10, 2, 0x111111, 0x222222, 1, 0x20, 1, 0x333333, 3, 0x3000)
    lo = ot.main_load + 0x10
    image = bytes(0x10) + body + w(0x123456)
    dev = dataclasses.replace(ot, dsp_payloads={'T': (lo, len(body))})
    assert dsp.records(image, dev, 'T') == [(0, 0x10, 2, lo + 6 * 2 + 9), (1, 0x20, 1, lo + 27 + 9)]
    assert dsp.p_span(image, dev, 'T', 0x11, 0x12) == lo + 21 + 3
    for bad, what in ((w(0, 0x10, 5, 1), 'does not parse at +0x0'), (w(3, 1, 0), 'at +0x6')):
        d = dataclasses.replace(ot, dsp_payloads={'T': (lo, len(bad))})
        try:
            dsp.records(bytes(0x10) + bad, d, 'T')
        except ModError as e:
            assert what in str(e), str(e)
        else:
            raise AssertionError('parsed %s' % bad.hex())
    early = w(0, 0x10, 1, 7, 5, 0xFFFFFF)                   # a word above 4 ends it
    d = dataclasses.replace(ot, dsp_payloads={'T': (lo, len(early))})
    assert dsp.records(bytes(0x10) + early, d, 'T') == [(0, 0x10, 1, lo + 9)]
    for d in devices.devices():
        for tag, a, b, nm, _what in d.dsp_areas:
            assert tag in d.dsp_payloads and a < b and nm.startswith('dsp:'), (d.key, nm)
    assert [d.key for d in devices.devices() if d.dsp_payloads] == ['octatrack']


def test_each_release_is_known_by_its_own_hash():
    """Every release of every profile is identified as itself, and its .elemod
    target names it alone."""
    seen = set()
    for d in devices.devices():
        for v, r in d.releases.items():
            assert r.version == v and r.syx_sha256 not in seen
            seen.add(r.syx_sha256)
            assert devices.identify(r.syx_sha256) == (d, r)
            assert devices.for_target(devices.target_of(d, r)) == (d, r)
    dt = devices.devices()[0]
    assert sorted(dt.releases) == ['1.53', '1.54']
    assert dt.image_end(dt.releases['1.54']) == 0x4025DA40


def test_a_mod_json_port_is_built_for_its_os():
    from elekloader.sdk import build
    dt = [d for d in devices.devices() if d.key == 'digitakt-mk1'][0]
    dn = [d for d in devices.devices() if d.key == 'digitone-mk1'][0]
    mod = {'id': 'm', 'version': '1', 'device': 'digitakt-mk1', 'os': '1.53',
           'defsym': {'X': '0x1'}, 'sites': ['a'],
           'ports': {'1.54': {'defsym': {'X': '0x2'}}}}
    got, ported = build.for_release(mod, dt, dt.releases['1.53'])
    assert got is mod and not ported
    got, ported = build.for_release(mod, dt, dt.releases['1.54'])
    assert ported and got['os'] == '1.54' and got['defsym'] == {'X': '0x2'}
    assert got['sites'] == ['a'] and mod['defsym'] == {'X': '0x1'}   # the rest kept, mod unchanged

    def refused(m, d, r, *words):
        try:
            build.for_release(m, d, r)
        except build.BuildError as e:
            assert all(w in str(e) for w in words), e
        else:
            raise AssertionError('built')
    refused(mod, dn, dn.releases['1.43'], 'digitakt-mk1 1.53 (ports: 1.54)', 'digitone-mk1 1.43')
    refused(dict(mod, ports={}), dt, dt.releases['1.54'], 'is for digitakt-mk1 1.53;')
    refused(dict(mod, ports={'1.54': {'id': 'other'}}), dt, dt.releases['1.54'], 'changes id')
    refused(dict(mod, ports={'1.54': ['defsym']}), dt, dt.releases['1.54'], '"ports"')


def test_section_alignment():
    """A section's alignment is a power of two up to 4,096 (USB descriptors want 32)."""
    d, r = devices.identify(devices.devices()[0].releases['1.53'].syx_sha256)

    def mod(align):
        return {'elemod': 2, 'id': 'a', 'version': '1', 'target': devices.target_of(d, r),
                'sections': {'.run': {'align': align, 'len': 4, 'parts': [['hex', '4e714e71']]}}}
    for ok in (1, 2, 4, 8, 16, 32, 4096):
        assert link.Mod2(mod(ok), 'a').sections['.run']['align'] == ok
    for bad in (0, 3, 24, 8192):
        try:
            link.Mod2(mod(bad), 'a')
        except elemod.ModError as e:
            assert 'alignment' in str(e)
            continue
        raise AssertionError('accepted alignment %d' % bad)


def test_parts_stay_in_the_image():
    d, r = devices.identify(devices.devices()[0].releases['1.53'].syx_sha256)
    ok = elemod.parse_parts([['hex', '00ff'], ['stock', '0x40000400', 8]], 't', d, r)
    assert ok == [('hex', b'\x00\xff'), ('stock', 0x40000400, 8)]
    for bad in (['stock', '0x40000000', 8], ['stock', '0x%08x' % (d.image_end(r) - 4), 8],
                ['stock', '0x40000400', 0], ['nope']):
        try:
            elemod.parse_parts([bad], 't', d, r)
        except elemod.ModError:
            continue
        raise AssertionError('accepted %r' % bad)


if __name__ == '__main__':
    import traceback
    ok = failed = 0
    for n in sorted(k for k in globals() if k.startswith('test_')):
        try:
            globals()[n]()
            print('ok      %s' % n)
            ok += 1
        except Exception:
            print('FAIL    %s' % n)
            traceback.print_exc()
            failed += 1
    print('%d passed, %d failed' % (ok, failed))
    sys.exit(1 if failed else 0)
