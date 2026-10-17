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
    # the newest, whatever the mods need: each core keeps all of the one before it
    assert elemod.pick_core(['2.1', '3.0', '2.0a']) == 1
    assert elemod.pick_core(['2.1', '3.0', '2.0a'], '2.1') == 1
    assert elemod.pick_core(['2.1', '3.0', '3.1'], '3.0') == 2
    assert elemod.pick_core(['2.1', '2.1']) == 1                 # the last of equals
    assert elemod.pick_core(['2.1', '3.0'], '3.1') is None
    assert elemod.pick_core(['2.0a', '2.2', '2.3', '3.0']) == 3
    assert elemod.pick_core(['2.0a', '2.2', '2.10', '2.3']) == 2   # versions as numbers
    assert elemod.pick_core([]) is None
    # fits: whether each core's RAM holds the mods (the Digitone's 4.0 has 1.25 MB, 2.3 and 3.2 128 KB)
    dn = ['2.3', '3.2', '4.0', '4.1']
    assert elemod.pick_core(dn, None, [True] * 4) == 3
    assert elemod.pick_core(dn, '3.2', [True] * 4) == 3
    assert elemod.pick_core(dn, None, [True, True, False, False]) == 1     # the newest that holds them
    assert elemod.pick_core(dn, '3.2', [True, False, False, False]) == 3  # none new enough holds: the newest
    assert elemod.pick_core(dn, '4.1', [True, True, False, True]) == 3
    assert elemod.pick_core(dn, '5.0', [True] * 4) is None


def test_a_selection_too_big_for_its_core_takes_one_with_more_ram():
    from elekloader.gui import one_core, with_requirements
    kb = 1024
    d = {
        'app/core-dn1-2.3.elemod': {'id': 'core', 'version': '2.3', 'fits': True, 'requires': [],
                                    'ram_bound': 4 * kb, 'ram_area': 128 * kb},
        'app/core-dn1-3.2.elemod': {'id': 'core', 'version': '3.2', 'fits': True, 'requires': [],
                                    'ram_bound': 6 * kb, 'ram_area': 128 * kb},
        'app/core-dn1-4.0.elemod': {'id': 'core', 'version': '4.0', 'fits': True, 'requires': [],
                                    'ram_bound': 6 * kb, 'ram_area': 1280 * kb},
        'lib/tiny.elemod': {'id': 'tiny', 'fits': True, 'requires': ['core'], 'ram_bound': kb},
        'lib/whole.elemod': {'id': 'whole', 'fits': True, 'format': 1},
        'lib/huge.elemod': {'id': 'huge', 'fits': True, 'requires': ['core'], 'needs_core': '3.2',
                            'ram_bound': 2000 * kb},
    }
    for i in range(1, 6):                          # five pedals of 30 KB that need core 3.2
        d['lib/pedal%d.elemod' % i] = {'id': 'pedal%d' % i, 'fits': True, 'requires': ['core'],
                                       'needs_core': '3.2', 'ram_bound': 30 * kb}
    c23, c32, c40 = 'app/core-dn1-2.3.elemod', 'app/core-dn1-3.2.elemod', 'app/core-dn1-4.0.elemod'
    pedals = ['lib/pedal%d.elemod' % i for i in range(1, 6)]
    # a build takes the newest core, 4.0, for a small selection too
    on = set()
    for k, p in enumerate(pedals):
        on = with_requirements(d, on, p)
        assert on == set(pedals[:k + 1]) | {c40}, on
    assert with_requirements(d, set(), 'lib/tiny.elemod') == {'lib/tiny.elemod', c40}
    # a core chosen by hand that will do is kept
    assert with_requirements(d, {c32}, pedals[0]) == {c32, pedals[0]}
    assert with_requirements(d, {c23}, 'lib/tiny.elemod') == {c23, 'lib/tiny.elemod'}
    # with 3.2 chosen by hand: up to 120 KB + 3.2's 6 KB, 3.2 holds them; 150 KB, 4.0 in its place
    on = {c32}
    for k, p in enumerate(pedals[:4]):
        on = with_requirements(d, on, p)
        assert on == set(pedals[:k + 1]) | {c32}, on
    assert with_requirements(d, on, pedals[4]) == set(pedals) | {c40}
    # exactly 3.2's area: 3.2 is kept; a byte more: 4.0
    d['lib/edge.elemod'] = {'id': 'edge', 'fits': True, 'requires': ['core'], 'needs_core': '3.2',
                            'ram_bound': 122 * kb}
    assert with_requirements(d, {c32}, 'lib/edge.elemod') == {'lib/edge.elemod', c32}
    d['lib/edge.elemod']['ram_bound'] += 1
    assert with_requirements(d, {c32}, 'lib/edge.elemod') == {'lib/edge.elemod', c40}
    # held by no core: the newest, or the one chosen by hand, for the check to say how much RAM is over
    assert with_requirements(d, set(), 'lib/huge.elemod') == {'lib/huge.elemod', c40}
    assert with_requirements(d, {c32}, 'lib/huge.elemod') == {'lib/huge.elemod', c32}
    # a file with no ram_bound (a whole build, an unreadable file) counts as nothing
    assert with_requirements(d, {'lib/whole.elemod', c23}, 'lib/tiny.elemod') == {
        'lib/whole.elemod', 'lib/tiny.elemod', c23}
    # the first run's ticks: one core, the newest
    assert one_core(d, {c23, c32, c40} | set(pedals)) == set(pedals) | {c40}
    assert one_core(d, {c23, c32, c40, 'lib/tiny.elemod'}) == {c40, 'lib/tiny.elemod'}


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
    # what needs nothing from 3.0 builds on 3.0 too: the newest core
    assert with_requirements(d, set(), 'lib/health.elemod') == {'lib/health.elemod', c30}
    # a core chosen by hand that will do is kept
    assert with_requirements(d, {c21}, 'lib/health.elemod') == {c21, 'lib/health.elemod'}
    assert with_requirements(d, {c30}, 'lib/health.elemod') == {c30, 'lib/health.elemod'}
    # what needs 3.0 brings it, through its requirements too, in place of 2.1 chosen by hand
    assert with_requirements(d, {'lib/health.elemod', c21}, 'lib/nb.elemod') == {
        'lib/health.elemod', 'lib/nb.elemod', 'lib/pages.elemod', c30}
    # none new enough: the newest, for the check to say why
    assert with_requirements(d, set(), 'lib/later.elemod') == {'lib/later.elemod', c30}
    assert with_requirements(d, {c21}, 'lib/later.elemod') == {'lib/later.elemod', c21}
    # the first run's ticks: one core, the newest
    assert one_core(d, {c21, c30, 'lib/health.elemod'}) == {c30, 'lib/health.elemod'}
    assert one_core(d, {c21, c30, 'lib/pages.elemod'}) == {c30, 'lib/pages.elemod'}


def test_a_digitone_machine_ticks_machines_and_its_core():
    """The shop's machines-dn1 (id machines, needs core-dn1 3.1) comes with a
    machine mod that requires it, and the core the shop lists that will do
    (3.2, not 2.3) with them."""
    from elekloader.gui import with_requirements
    d = {
        'app/core-dn1-2.3.elemod': {'id': 'core', 'version': '2.3', 'fits': True, 'requires': []},
        'app/core-dn1-3.2.elemod': {'id': 'core', 'version': '3.2', 'fits': True, 'requires': []},
        'lib/machines-0.1.elemod': {'id': 'machines', 'fits': True, 'requires': ['core'],
                                    'needs_core': '3.1'},
        'lib/dnsine-1.0.elemod': {'id': 'dnsine', 'fits': True, 'requires': ['core', 'machines']},
        'lib/tables.elemod': {'id': 'tables', 'fits': True, 'requires': ['core']},
    }
    c23, c32 = 'app/core-dn1-2.3.elemod', 'app/core-dn1-3.2.elemod'
    assert with_requirements(d, set(), 'lib/dnsine-1.0.elemod') == {
        'lib/dnsine-1.0.elemod', 'lib/machines-0.1.elemod', c32}
    # beside 2.3 chosen by hand, the machine brings machines and moves the build to 3.2
    assert with_requirements(d, {'lib/tables.elemod', c23}, 'lib/dnsine-1.0.elemod') == {
        'lib/tables.elemod', 'lib/dnsine-1.0.elemod', 'lib/machines-0.1.elemod', c32}


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


def test_the_main_os_is_stored_padded_to_4():
    """Elektron stores a packed section as its header and stream, then zeros
    to a multiple of 4; the table's length counts them, the header's does not
    (issue #59). pack_main pads the same way; the Octatrack's family does not
    pad, and write() keeps whatever stream it is given."""
    from elekloader import elek, formats
    body = b'main os image ' * 300
    s = syx.Syx(transport.encode_syx(
        (lambda c: struct.pack('>II', len(c), transport.content_checksum(c)) + c)(
            _container([(5, 0, b'meta'), (3, 0x40000400, aplib.pack_section(body))])),
        0x0A, FRAMING0, FRAMING1))
    dev = devices.devices()[0]
    seen = set()
    for extra in range(8):
        img = body + b'!' * extra
        packed = aplib.pack_section(img)
        seen.add(len(packed) % 4)
        stored = syx.pack_main(img)
        assert formats.pack_main(img, dev) == stored
        assert len(stored) % 4 == 0 and stored[:len(packed)] == packed
        assert stored[len(packed):] == bytes(len(stored) - len(packed))
        o = syx.Syx(syx.write(s, stored, dev))
        assert o.stored[3] == stored and o.section(3) == img
        assert elek.pack_main(img) == packed
    assert len(seen) > 1, 'the cases do not reach an unaligned stream'


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


def test_bytes_site_relocs():
    """A `bytes` site's relocs: well-formed ones pass, anything else is a
    BuildError naming the site, not a crash."""
    from elekloader.sdk import build
    new = bytes(12)
    ok = [[0, 'abs32', 'sym:a', 0], [8, 'abs32', 'abs', 0x10]]
    assert build.bytes_relocs(0x40001000, new, ok) == ok
    for bad in ([[0, 'abs32', 'sym:a']], [['0', 'abs32', 'sym:a', 0]], [[0, 'abs32', 'sym:a', '1']],
                [[True, 'abs32', 'sym:a', 0]], [[9, 'abs32', 'sym:a', 0]], [[-1, 'abs32', 'sym:a', 0]],
                [[0, 'pc32', 'sym:a', 0]], [[0, 'abs32', 'absfoo', 0]], [[0, 'abs32', 'sym:', 0]],
                [[0, 'abs32', 3, 0]], [[0, 'abs32', 'sym:a', 0], [2, 'abs32', 'sym:b', 0]],
                ['x'], {'0': 1}):
        try:
            build.bytes_relocs(0x40001000, new, bad)
        except build.BuildError as e:
            assert '0x40001000' in str(e), e
        else:
            raise AssertionError('accepted %r' % (bad,))


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



def test_lint_notes_the_code_sites_a_mod_hooks_itself():
    from elekloader.lint import core_candidates

    def mod2(mod_id, sites):
        m = link.Mod2.__new__(link.Mod2)
        m.id, m.sites = mod_id, sites
        return m
    sites = [{'addr': 0x400ea1a8, 'len': 6, 'kind': 'code'},
             {'addr': 0x401ab9b0, 'len': 4, 'kind': 'data'}]
    assert core_candidates(mod2('my-mod', sites)) == [
        {'mod': 'my-mod', 'site': '0x400ea1a8', 'len': 6}]
    # the core owns its sites; data sites are not events
    assert core_candidates(mod2('core', sites)) == []
    assert core_candidates(mod2('my-mod', sites[1:])) == []


def test_coresites_groups_the_sites_mods_share():
    from elekloader.sdk.coresites import routine_test, shared_sites
    sites = [('health', '1.0', 0x4007814a, 6), ('neighbor', '0.6', 0x40078142, 6),
             ('slicer', '2.0', 0x40074df2, 6), ('slicer', '2.0', 0x40074e00, 6),
             ('fm', '1.2', 0x40074df2, 6), ('fm', '1.2', 0x40090000, 6)]
    g = shared_sites(sites)
    assert [(x['kind'], x['overlap'], x['lo'], x['hi'], sorted(y['mod'] for y in x['sites']))
            for x in g] == [
        ('near', True, 0x40074df2, 0x40074e06, ['fm', 'slicer', 'slicer']),
        ('near', False, 0x40078142, 0x40078150, ['health', 'neighbor'])]
    assert shared_sites(sites[2:5:2])[0]['kind'] == 'same bytes'
    # one mod's own sites close together are not shared
    assert shared_sites([('a', '1', 0x100, 6), ('a', '1', 0x106, 6)]) == []
    assert [(x['lo'], x['hi']) for x in shared_sites(sites, window=0)] == [(0x40074df2, 0x40074df8)]
    # by routine: an rts between two sites parts them, however close
    code = bytes.fromhex('4e714e714e714e714e754e714e714e71')       # nop x4, rts, nop x3
    dev = type('Dev', (), {'main_load': 0x1000, 'decoder': lambda self: __import__(
        'elekloader.isa.coldfire', fromlist=['x'])})()
    same = routine_test(code, dev)
    assert same((0x1000, 2), (0x1006, 2)) and not same((0x1000, 2), (0x100a, 2))
    two = [('a', '1', 0x1000, 2), ('b', '1', 0x1006, 2), ('c', '1', 0x100c, 2)]
    assert [sorted(y['mod'] for y in x['sites']) for x in shared_sites(two, same)] == [['a', 'b']]
    assert shared_sites(two, same)[0]['kind'] == 'same routine'


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
