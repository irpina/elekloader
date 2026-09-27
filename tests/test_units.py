"""Unit tests that need no firmware (pytest, or run with python)."""
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import devices, elemod, syx               # noqa: E402
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
