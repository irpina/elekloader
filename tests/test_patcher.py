"""Format-1 bundles, the writer and the verifier (pytest, or run with python).

Needs files that never go in the repo, named by environment variables; a
test whose inputs are missing is skipped, not passed:
  ELEKLOADER_STOCK      the stock Digitakt_OS1.53.syx
  ELEKLOADER_BUNDLE     a format-1 bundle (e.g. sysinfo-bundle-1.8F.elemod)
  ELEKLOADER_CTOOL_SYX  the build that bundle came from (made by
                        elektron-firmware-tool), for the byte-for-byte checks
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
BUNDLE = os.environ.get('ELEKLOADER_BUNDLE', '')



class Skip(Exception):
    pass


def need(path):
    if not path or not os.path.exists(path):
        raise Skip('missing %s' % path)
    return path


_cache = {}


def stock():
    if 'stock' not in _cache:
        _cache['stock'] = syx.Syx.load(need(STOCK))
        _cache['img0'] = _cache['stock'].section(3)
    return _cache['stock'], _cache['img0']


def bundle_doc():
    with open(need(BUNDLE)) as fh:
        return json.load(fh)


def ctool_syx():
    doc = bundle_doc()
    p = os.environ.get('ELEKLOADER_CTOOL_SYX', '')
    s = syx.Syx.load(need(p))
    if s.sha256 != doc['build']['syx_sha256']:
        raise Skip('%s is not the build the bundle came from' % p)
    return s


def built():
    """The bundle through the whole patcher (once)."""
    if 'out' not in _cache:
        outputs, man = patch.build(STOCK, [need(BUNDLE)], log=lambda *a: None)
        out = outputs['syx']
        _cache['out'], _cache['man'] = out, man
    return _cache['out'], _cache['man']


def mod(doc, name='t'):
    return elemod.Mod(doc, name)


def small_mod(doc, mid, sites):
    """A mod with only `sites` (dicts as in the file), no blob or resources."""
    d = {k: copy.deepcopy(v) for k, v in doc.items() if k in ('elemod', 'dtmod', 'target')}
    d.update({'id': mid, 'version': '1', 'sites': sites})
    return mod(d, mid)


def expect(fn, *words):
    try:
        fn()
    except (elemod.ModError, syx.SyxError, patch.PatchError) as e:
        msg = str(e)
        for w in words:
            assert w in msg, 'expected %r in: %s' % (w, msg)
        return msg
    raise AssertionError('not refused')


def reseal(s, overrides=None, header=None):
    """Rebuild a .syx from Syx `s` with some stored sections replaced, the
    transport re-sealed (checksums right): what a careless tool would make."""
    overrides = overrides or {}
    cont = bytearray(s.container[:0x80])
    if header is not None:
        cont[:0x1C] = header
    for i, (sid, _o, _l, dest) in enumerate(s.table):
        data = overrides.get(sid, s.stored[sid])
        struct.pack_into('>IIII', cont, 0x20 + 16 * i, sid, len(cont), len(data), dest)
        cont += data
        cont += bytes(-len(cont) % 16)
    stream = struct.pack('>II', len(cont), transport.content_checksum(bytes(cont))) + bytes(cont)
    return transport.encode_syx(stream, s.device_id, s.framing[0], s.framing[1])


# ---- the container writer ------------------------------------------------------

def test_writer_matches_c_tool():
    """Given the C tool's section 3 stream, write() gives the C tool's .syx."""
    st, _ = stock()
    c = ctool_syx()
    assert syx.write(st, c.stored[3], DEV, c.version) == c.raw


def test_writer_no_change_is_stock():
    st, _ = stock()
    assert syx.write(st, st.stored[3], DEV) == st.raw


# ---- round trip ---------------------------------------------------------------

def test_bundle_round_trip():
    """The bundle applied to stock gives its build's MAIN OS, and the output
    verifies and depacks to it."""
    doc = bundle_doc()
    _, img0 = stock()
    img = elemod.apply([mod(doc)], img0)
    assert sha(img) == doc['build']['section3_sha256']
    out, man = built()
    assert man['bundle_matches_build'] is True
    assert syx.Syx(out).section(3) == img
    assert man['output']['main']['inplace_min_gap'] > 0


def test_same_main_os_as_c_tool_build():
    out, _ = built()
    assert syx.Syx(out).section(3) == ctool_syx().section(3)


def test_blob_carries_no_long_stock_run():
    doc = bundle_doc()
    _, img0 = stock()
    carried = b''.join(bytes.fromhex(p[1]) for p in doc['blob']['parts'] if p[0] == 'hex')
    idx = {img0[o:o + 8] for o in range(0, len(img0) - 8, 2)}
    for p in doc['blob']['parts']:
        if p[0] != 'hex':
            continue
        b = bytes.fromhex(p[1])
        for i in range(0, len(b) - 7, 2):
            assert b[i:i + 8] not in idx or len(set(b[i:i + 8])) == 1
    assert len(carried) + sum(p[2] for p in doc['blob']['parts'] if p[0] == 'stock') \
        == doc['blob']['len']


def test_stock_parts_round_trip():
    _, img0 = stock()
    blob = img0[0x1000:0x1400] + b'\x12\x34\x56' + img0[0x50000:0x50100] + b'\xff' * 40
    parts = stock_parts(blob, img0, 8, LOAD)
    back = b''.join(p[1] if p[0] == 'hex' else img0[p[1] - LOAD:p[1] - LOAD + p[2]]
                    for p in parts)
    assert back == blob


# ---- refused inputs ------------------------------------------------------------

def test_refuses_wrong_stock():
    c = ctool_syx()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'not-stock.syx')
        with open(p, 'wb') as fh:
            fh.write(c.raw)
        expect(lambda: patch.build(p, [need(BUNDLE)], log=lambda *a: None), 'not a stock')
        st, _ = stock()
        raw = bytearray(st.raw)
        raw[5000] ^= 0x01
        with open(p, 'wb') as fh:
            fh.write(raw)
        expect(lambda: patch.build(p, [need(BUNDLE)], log=lambda *a: None))


def test_refuses_mod_for_another_firmware():
    doc = bundle_doc()
    doc['target']['section3_sha256'] = '0' * 64
    expect(lambda: mod(doc), 'does not know')


def test_refuses_tampered_stock_hash():
    doc = bundle_doc()
    doc['sites'][3]['stock_sha256'] = sha(b'not these bytes')
    _, img0 = stock()
    expect(lambda: elemod.apply([mod(doc)], img0), 'not the ones it expects')


def test_refuses_two_mods_on_one_site():
    doc = bundle_doc()
    _, img0 = stock()
    other = small_mod(doc, 'other', [doc['sites'][0]])
    expect(lambda: elemod.apply([mod(doc), other], img0), 'overlap')


def test_refuses_overlapping_range():
    doc = bundle_doc()
    _, img0 = stock()
    s = dict(doc['sites'][0])
    a = int(s['addr'], 16) + 4                      # the last 2 bytes of that jsr, and 4 more
    o = a - LOAD
    s.update(addr='0x%08x' % a, stock_sha256=sha(img0[o:o + 6]))
    msg = expect(lambda: elemod.apply([mod(doc), small_mod(doc, 'other', [s])], img0), 'overlap')
    assert 'whole' in msg or 'mid-instruction' in msg or 'sweeps' in msg or 'decode' in msg


def test_refuses_mid_instruction_site():
    doc = bundle_doc()
    _, img0 = stock()
    a = 0x40000538 + 2                              # inside `jsr 0x40001c94`
    s = {'addr': '0x%08x' % a, 'len': 4, 'kind': 'code', 'new': '4e714e71',
         'stock_sha256': sha(img0[a - LOAD:a - LOAD + 4])}
    expect(lambda: elemod.apply([small_mod(doc, 'm', [s])], img0), '0x%08x' % a)


def test_refuses_blob_over_budget():
    doc = bundle_doc()
    n = DEV.ddr[1] - DEV.ddr[0] + 2
    doc['blob'] = {'load': doc['blob']['load'], 'len': n, 'sha256': '0' * 64,
                   'parts': [['hex', '00' * n]]}
    expect(lambda: mod(doc), 'over')


def test_refuses_region_outside_free_areas():
    doc = bundle_doc()
    doc['resources']['regions'].append({'name': 'ring', 'lo': '0x47c00000', 'hi': '0x47c00100'})
    expect(lambda: mod(doc), 'outside every free area')


def test_refuses_overlapping_regions_and_names():
    doc = bundle_doc()
    _, img0 = stock()
    other = bundle_doc()
    other.update(id='other', sites=[], blob=None)
    other['resources'] = {'regions': [{'name': 'mine', 'lo': '0x47be1000', 'hi': '0x47be2000'}],
                          'names': ['sysex:0x7d']}
    msg = expect(lambda: elemod.apply([mod(doc), mod(other)], img0), 'overlap', 'sysex:0x7d')
    assert 'region' in msg


def test_requires_and_conflicts():
    doc = bundle_doc()
    _, img0 = stock()
    a = small_mod(doc, 'a', [])
    b_doc = {k: copy.deepcopy(v) for k, v in doc.items() if k in ('elemod', 'dtmod', 'target')}
    b_doc.update(id='b', version='1', sites=[], requires=['core'], conflicts=['a'])
    expect(lambda: elemod.apply([a, mod(b_doc)], img0), 'requires core', 'conflicts with a')


def test_order_does_not_matter():
    """Mods that combine give the same image in any order (here the bundle's
    sites split into three site-only mods)."""
    import itertools
    doc = bundle_doc()
    _, img0 = stock()
    s = doc['sites']
    mods = [small_mod(doc, 'm%d' % i, s[i::3]) for i in range(3)]
    outs = {sha(elemod.apply(list(p), img0)) for p in itertools.permutations(mods)}
    assert len(outs) == 1


def test_refuses_two_blobs():
    doc = bundle_doc()
    _, img0 = stock()
    other = bundle_doc()
    other.update(id='other', sites=[])
    other['resources'] = {}
    expect(lambda: elemod.apply([mod(doc), mod(other)], img0), 'more than one whole build')


# ---- tampered outputs ----------------------------------------------------------

def test_tampered_sections_fail_verification():
    """A flipped byte in section 2, 4, 5 or 8 of the output fails, even with
    the transport re-sealed so every checksum is right."""
    out, _ = built()
    st, _ = stock()
    o = syx.Syx(out)
    want = o.section(3)
    for sid in (2, 4, 5, 8):
        b = bytearray(o.stored[sid])
        b[len(b) // 2] ^= 0x40
        bad = reseal(o, {sid: bytes(b)})
        expect(lambda: syx.verify(bad, st, want, DEV), 'section %d' % sid)


def test_tampered_header_or_transport_fails():
    out, _ = built()
    st, _ = stock()
    o = syx.Syx(out)
    want = o.section(3)
    h = bytearray(o.header)
    h[0x0A] ^= 0x01                                  # the build string, not the version
    expect(lambda: syx.verify(reseal(o, header=bytes(h)), st, want, DEV), 'header')
    raw = bytearray(out)
    raw[len(raw) // 2 + 20] ^= 0x01                  # one payload bit, not re-sealed
    expect(lambda: syx.verify(bytes(raw), st, want, DEV))
    expect(lambda: syx.verify(out, st, want[:-1] + b'\0', DEV), 'main OS')


def test_version_field():
    out, man = built()
    assert syx.Syx(out).version == bundle_doc()['ele3_version'] == man['version']


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ok = skipped = failed = 0
    for n in names:
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
