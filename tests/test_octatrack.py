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

from elekloader import devices, dsp, elek, elemod, formats, link, mkmod, patch   # noqa: E402
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


def test_relocatable_data_is_reached_only_through_its_references():
    """The profile's `relocatable` facts, against the stock image: the data lies in a
    protected range, each reference holds its address, and no other four bytes outside
    the protected ranges point into it, at any alignment."""
    st, img = stock()
    base = DEV.main_load
    assert DEV.relocatable
    for lo, n, refs, what in DEV.relocatable:
        assert any(plo <= lo and lo + n <= phi for plo, phi, _w in DEV.protected), what
        found = []
        for o in range(len(img) - 3):
            a = base + o
            if lo <= int.from_bytes(img[o:o + 4], 'big') < lo + n \
                    and not any(plo <= a < phi for plo, phi, _w in DEV.protected):
                found.append(a)
        assert found == list(refs), (what, [hex(a) for a in found])


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
    shrink by it. From 0.3 the linker computes them (the profile's `reserve`):
    each site names the value it carries, the profile's formula gives the
    stock value at 0 pages, and at 1,707 pages the bytes core 0.2 wrote. Each
    stock value is checked against the stock image."""
    with open(os.path.join(ROOT, 'mods', 'core-ot', 'mod.json')) as fh:
        j = json.load(fh)
    lo, hi = DEV.ddr
    moved = {lo: hi, lo + PAGE: hi + PAGE,                  # core 0.2's 1,707 pages
             STOCK_PAGES: STOCK_PAGES - PAGES, STOCK_PAGES + 1: STOCK_PAGES + 1 - PAGES,
             (STOCK_PAGES + 1) * PAGE: (STOCK_PAGES + 1 - PAGES) * PAGE}
    named = {lo: ('arena_base', 0), lo + PAGE: ('arena_base', PAGE),
             STOCK_PAGES: ('__arena_pages', 0), STOCK_PAGES + 1: ('__arena_fill', 0),
             (STOCK_PAGES + 1) * PAGE: ('__arena_clear', 0)}
    unit, names = DEV.reserve
    assert unit == PAGE and set(names) == {t for t, _a in named.values()}
    st, img = stock()
    seen = {}
    for s in j['sites']:
        o = int(s['addr'], 16) - DEV.main_load
        old = bytes.fromhex(s['stock'])
        assert img[o:o + len(old)] == old, s['addr']
        if s['op'] == 'ptr':
            v = int(s['stock'], 16)
            t, add = named[v]
            assert (s['target'], s.get('addend', 0)) == (t, add), s['addr']
            a, b = names[t]
            assert (a + add) & 0xFFFFFFFF == v                        # 0 pages: stock
            assert (a + b * PAGES + add) & 0xFFFFFFFF == moved[v]     # 1,707: core 0.2's
            seen[v] = seen.get(v, 0) + 1
    assert seen == {lo: 23, lo + PAGE: 1, STOCK_PAGES: 2, STOCK_PAGES + 1: 1,
                    (STOCK_PAGES + 1) * PAGE: 1}
    calls = {s['target']: int(s['addr'], 16) for s in j['sites'] if s['op'] == 'jsr'}
    assert calls.pop('boot') == 0x4000050c
    assert set(calls) == set(BUS_SITES), calls             # the rest are the hook bus's


def reserve_docs(img, bss, fixed=False):
    """A core that sizes its reserve (two of core-ot's arena writes, against the linker's
    reserve symbols) or, `fixed`, one that exports arena_base as core 0.2 does; and a mod
    with `bss` bytes of RAM."""
    tgt = devices.target_of(DEV, REL)

    def site(addr, sym):
        o = addr - DEV.main_load
        return {'addr': '0x%08x' % addr, 'len': 4, 'kind': 'data', 'new': '00000000',
                'stock_sha256': sha(img[o:o + 4]), 'relocs': [[0, 'abs32', 'sym:' + sym, 0]]}
    core = {'elemod': 2, 'id': 'core', 'version': '0', 'target': tgt,
            'sections': {'.boot': {'len': 2, 'parts': [['hex', '4e75']]}},
            'sites': [site(0x4000045e, 'arena_base'), site(0x40096f82, '__arena_pages')],
            'imports': ['arena_base', '__arena_pages']}
    if fixed:
        core['symbols'] = {'arena_base': ['abs', DEV.ddr[1]]}
        core['exports'] = ['arena_base']
        core['imports'] = ['__arena_pages']
    mod = {'elemod': 2, 'id': 'ram', 'version': '0', 'target': tgt, 'requires': ['core'],
           'sections': {'.bss': {'size': bss}}}
    return core, mod


def test_the_reserve_fits_the_mods():
    """The linker sizes the reserve to the mods' RAM, in pages, for a core that imports the
    profile's reserve symbols: at least one page, and the arena's values follow. A core
    that exports arena_base (a fixed reserve, core 0.2) gets none of them, and a link
    without a sized core is as before."""
    st, img = stock()
    lo = DEV.ddr[0]
    for bss, pages in ((0, 1), (PAGE - 200, 1), (PAGE * 3, 3), (PAGE * 3 + 4, 4),
                      (PAGE * PAGES - 300, PAGES)):
        core, mod = reserve_docs(img, bss)
        ln = link.link([link.Mod2(core, 'core'), link.Mod2(mod, 'ram')], img)
        assert ln.layout['reserve'] == {'units': pages, 'end': lo + pages * PAGE}, (bss, ln.layout)
        assert ln.map['arena_base'] == lo + pages * PAGE
        assert ln.map['__arena_pages'] == STOCK_PAGES - pages
        o = 0x40096f82 - DEV.main_load
        assert struct.unpack('>I', ln.image[o:o + 4])[0] == STOCK_PAGES - pages
        o = 0x4000045e - DEV.main_load
        assert struct.unpack('>I', ln.image[o:o + 4])[0] == lo + pages * PAGE
    core, mod = reserve_docs(img, PAGE * PAGES + 4)        # past the most it may take
    expect(lambda: link.link([link.Mod2(core, 'core'), link.Mod2(mod, 'ram')], img),
           'the mods need RAM to 0x%08x, past 0x%08x' % (DEV.ddr[1] + 4, DEV.ddr[1]))
    core, mod = reserve_docs(img, 64, fixed=True)
    mods = [link.Mod2(core, 'core'), link.Mod2(mod, 'ram')]
    expect(lambda: link.link(mods, img), 'core 0 imports __arena_pages, which no given mod '
           'exports')
    core['imports'], core['sites'] = [], core['sites'][:1]
    core['sites'][0]['relocs'][0][2] = 'sym:arena_base'
    ln = link.link([link.Mod2(core, 'core'), link.Mod2(mod, 'ram')], img)
    assert 'reserve' not in ln.layout and '__arena_pages' not in ln.map
    assert ln.map['arena_base'] == DEV.ddr[1]               # the fixed core's own


# The hook bus (core-ot 0.2): each site, the instruction it replaces, and its event.
BUS_SITES = {
    'core_tick': (0x40061e94, '4eb940031970', 'ev_tick'),        # jsr 0x40031970, sys loop kind 5
    'core_draw_gate': (0x40013cae, '2a79400b9710', 'ev_draw'),   # movea.l 0x400b9710,a5, compositor
    'core_key': (0x40061dc8, '4eb940031734', 'ev_key'),          # jsr key(code, pressed), kind 1
    'core_enc': (0x40061e00, '4eb940031944', 'ev_enc'),          # jsr enc(encoder, delta), kind 2
    'core_midi': (0x40005572, '20720c004e90', 'ev_midi'),        # the MIDI thread's handler call
    'core_frame': (0x4000d94e, '4ab946104d08', 'ev_frame'),      # tst.l 0x46104d08, frame interrupt
}
# Instructions the converted octabam mods of irpina/octabam2elemod v1.0 hook in the same
# routines (TUNER, CC FEEDBACK, CC MAP, the USB audio mods, USB MIDI): the bus keeps clear
# of every one, so those files link with core 0.2 as they did with 0.1.
V10_NEIGHBOURS = ((0x40056c72, 6), (0x4000d99a, 6), (0x4000d9a0, 6), (0x4005595c, 6),
                  (0x400d64a0, 4), (0x4001e606, 6), (0x40059ef0, 6))


def test_the_core_bus_sites():
    """core-ot 0.2's hook bus: each site replaces whole stock instructions, has the
    collection for its event, keeps clear of the v1.0 conversions' sites, and the
    draw site goes through the gate placed in a free image area (the OS composes
    the screen twice before the boot site, before .run is in the reserve)."""
    with open(os.path.join(ROOT, 'mods', 'core-ot', 'mod.json')) as fh:
        j = json.load(fh)
    st, img = stock()
    sites = {s['target']: s for s in j['sites'] if s['op'] == 'jsr' and s['target'] != 'boot'}
    for target, (addr, stock_hex, event) in BUS_SITES.items():
        s = sites[target]
        assert (int(s['addr'], 16), s['stock']) == (addr, stock_hex), target
        o = addr - DEV.main_load
        assert img[o:o + 6].hex() == stock_hex, target
        assert j['collections'][event] == 4, event
        for a, n in V10_NEIGHBOURS:
            assert not (a < addr + 6 and addr < a + n), (target, hex(a))
    assert sorted(j['collections']) == sorted(e for _a, _s, e in BUS_SITES.values())
    (fx,) = j['fixed']
    at = int(fx['addr'], 16)
    assert any(a <= at and at + 24 <= b for a, b in DEV.image_free)
    assert at + 24 == DEV.image_free[0][1]          # the run's end: its start is octabam's SPECTRUM's


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

    # A destination operand stays absolute with every assembler (a bare-metal one turns
    # a source operand naming its own label into a PC-relative one), so the relocations
    # are the same whichever builds it.
    code = ('        .text\n        .globl  fx_loop, fx_word\nfx_loop: move.l  %d0,fx_word\n'
            '        jsr     arena_base\n        rts\nfx_word: .long   0\n')
    with tempfile.TemporaryDirectory() as tmp:
        path, m = attempt(tmp, '0x400d64e0', code)
        s = m.sites[0]
        assert (s['addr'], s['len'], s['kind']) == (0x400d64e0, 18, 'data')
        assert s['stock_sha256'] == sha(bytes(18))
        assert m.symbols['fx_start'] == ('abs', 0x400d64e0) == m.symbols['fx_loop']
        assert m.symbols['fx_word'] == ('abs', 0x400d64ee)
        assert (2, 'abs32', 'abs', 0x400d64ee) in s['relocs'], s['relocs']   # move.l d0,fx_word
        assert (8, 'abs32', 'sym:arena_base', 0) in s['relocs']            # jsr arena_base
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
    o = 0x4000045e - DEV.main_load              # the arena's base, past the pages the mods fill
    assert new[o:o + 4] == struct.pack('>I', DEV.ddr[0] + PAGE)
    assert man['link']['layout']['reserve'] == {'units': 1, 'end': DEV.ddr[0] + PAGE}
    # the draw site calls the gate in the image (tst.b core_up), whose flag starts clear
    gate = 0x400c46ea
    o = 0x40013cae - DEV.main_load
    assert new[o:o + 6] == b'\x4e\xb9' + struct.pack('>I', gate)
    o = gate - DEV.main_load
    assert new[o:o + 6] == b'\x4a\x39' + struct.pack('>I', gate + 22)
    assert new[o + 22] == 0


def test_the_example_subscribes_to_the_bus():
    """examples/hello-marker-ot with core-ot: its handler is the one entry of the ev_draw
    table, in the run image .boot copies to the reserve; the other events have none."""
    import shutil
    from elekloader.sdk import build
    need(SYX)
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', DEV.toolchain['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    st, img = stock()
    with tempfile.TemporaryDirectory() as tmp:
        core, _m = build.build(os.path.join(ROOT, 'mods', 'core-ot'), SYX, tmp)
        ex, m = build.build(os.path.join(ROOT, 'examples', 'hello-marker-ot'), SYX, tmp)
        assert 'hello_draw' in m.exports and not m.imports, m.imports
        ln = link.link([elemod.load_any(core), elemod.load_any(ex)], img)
    counts = {t: ln.tables[t][1] for t in ln.tables}
    assert counts == {'ev_draw': 1, 'ev_enc': 0, 'ev_frame': 0, 'ev_key': 0, 'ev_midi': 0,
                      'ev_tick': 0}, counts
    at = ln.tables['ev_draw'][0]
    o = ln.layout['run_load'] + (at - DEV.ddr[0]) - DEV.main_load
    assert struct.unpack('>II', ln.image[o:o + 8]) == (ln.map['hello_draw'], 0)


# ---- DSP code ---------------------------------------------------------------------------

HOOK = 0x400ef758               # payload A's P:0x88, move r2,x:>$204 (627000 000204)
AREA = 0x400f1771               # payload A's P:0xaa8, SPATIALIZER's first word


def le24(*ws):
    return b''.join(bytes((w & 0xFF, (w >> 8) & 0xFF, w >> 16)) for w in ws)


def words(b, at, n):
    o = at - DEV.main_load
    return [dsp.w24(b, o + 3 * i) for i in range(n)]


def dsp_docs(img):
    """(a bare core, a DSP bus, a mod with DSP code) as documents. The bus frees SPATIALIZER's
    words, declares ev_dsp_rx (the instruction it displaces, the entries, rts) and makes P:0x88
    `jsr >ev_dsp_rx`. The other mod has four words, the third the address of the fourth, and
    adds `jsr >its second word` to the table."""
    tgt = devices.target_of(DEV, REL)
    core = {'elemod': 2, 'id': 'core', 'version': '0', 'target': tgt,
            'sections': {'.boot': {'len': 2, 'parts': [['hex', '4e75']]}},
            'symbols': {'core_x': ['.boot', 0]}, 'exports': ['core_x']}
    o = HOOK - DEV.main_load
    hook = img[o:o + 6]
    bus = {'elemod': 2, 'id': 'dspbus', 'version': '0', 'target': tgt, 'sections': {},
           'requires': ['core'], 'resources': {'names': ['dsp:harvest:SPATIALIZER']},
           'collections': {'ev_dsp_rx': {'entry': 6, 'space': 'dsp.A', 'head': hook.hex(),
                                         'end': le24(0x00000c).hex()}},
           'imports': ['ev_dsp_rx'],
           'sites': [{'addr': '0x%08x' % HOOK, 'len': 6, 'kind': 'data', 'stock_sha256': sha(hook),
                      'new': (le24(0x0bf080) + bytes(3)).hex(),
                      'relocs': [[3, 'dsp24', 'sym:ev_dsp_rx', 0]]}]}
    sub = {'elemod': 2, 'id': 'dsptest', 'version': '0', 'target': tgt, 'requires': ['core'],
           'sections': {'.dsp.A': {'len': 12, 'parts': [['hex', le24(0, 0x60f400, 0, 0x0c).hex()]]}},
           'symbols': {'tst': ['.dsp.A', 0]},
           'relocs': [['.dsp.A', 6, 'dsp24', 'sec:.dsp.A', 3]],
           'contribute': [{'to': 'ev_dsp_rx', 'order': 50, 'data': (le24(0x0bf080) + bytes(3)).hex(),
                           'relocs': [[3, 'dsp24', 'sym:tst', 1]]}]}
    return core, bus, sub


def test_dsp_payloads_parse():
    """Both payloads walk to their end; P:0x88 and SPATIALIZER's words are where the profile
    and the bus expect them."""
    st, img = stock()
    for tag, (at, n) in DEV.dsp_payloads.items():
        recs = dsp.records(img, DEV, tag)
        assert recs and all(sp in (0, 1, 2) for sp, _a, _c, _w in recs), tag
    assert dsp.p_span(img, DEV, 'A', 0x88, 0x8a) == HOOK
    assert img[HOOK - DEV.main_load:HOOK - DEV.main_load + 6] == le24(0x627000, 0x000204)
    for tag, lo, hi, _nm, _w in DEV.dsp_areas:
        assert dsp.p_span(img, DEV, tag, lo, hi) == AREA
    expect(lambda: dsp.p_span(img, DEV, 'A', 0x0, 0x100000), 'does not load P:0x00000-0xfffff')
    expect(lambda: dsp.records(img, DEV, 'C'), 'has no DSP payload C')


def test_dsp_code_links_into_the_area_a_mod_frees():
    st, img = stock()
    core, bus, sub = dsp_docs(img)
    mods = [link.Mod2(d, d['id']) for d in (core, bus, sub)]
    ln = link.link(mods, img)
    assert ln.layout['dsp'] == {'A': {'area': [0xaa8, 0xbad], 'used': [0xaa8, 0xab1],
                                      'name': 'dsp:harvest:SPATIALIZER',
                                      'sections': {'dsptest .dsp.A': 0xaa8},
                                      'tables': {'ev_dsp_rx': 0xaac}}}, ln.layout['dsp']
    assert 'dsptest .dsp.A' not in ln.layout['sections']
    assert ln.map['dsptest:tst'] == 0xaa8 and ln.map['ev_dsp_rx'] == 0xaac
    assert ln.tables['ev_dsp_rx'] == (0xaac, 1, 6) and ln.map['ev_dsp_rx_n'] == 1
    assert words(ln.image, HOOK, 2) == [0x0bf080, 0xaac]
    assert words(ln.image, AREA, 10) == [0, 0x60f400, 0xaab, 0x0c,          # the code, relocated
                                         0x627000, 0x000204, 0x0bf080, 0xaa9, 0x0c,  # the table
                                         words(img, AREA + 27, 1)[0]]       # then stock
    changed = [i for i in range(len(img)) if ln.image[i] != img[i]]
    assert all(HOOK <= DEV.main_load + i < HOOK + 6 or AREA <= DEV.main_load + i < AREA + 27
               for i in changed), hex(DEV.main_load + changed[0])
    # the bus alone: P:0x88 runs the displaced instruction and returns, as stock does
    ln = link.link(mods[:2], img)
    assert words(ln.image, AREA, 3) == [0x627000, 0x000204, 0x0c]
    assert ln.tables['ev_dsp_rx'] == (0xaa8, 0, 6)


def test_dsp_code_is_refused_where_it_cannot_go():
    st, img = stock()

    def refused(docs, *msgs):
        mods = [link.Mod2(d, d['id']) for d in docs]
        return expect(lambda: link.link(mods, img), *msgs)
    core, bus, sub = dsp_docs(img)
    refused([core, sub], 'dsptest 0 adds to table ev_dsp_rx, which no given mod declares',
            'dsptest 0 has DSP code for payload A, which needs a mod that frees DSP memory '
            'there (one that claims dsp:harvest:SPATIALIZER)')
    big = json.loads(json.dumps(sub))
    big['sections']['.dsp.A'] = {'len': 3 * 300, 'parts': [['hex', '00' * 900]]}
    refused([core, bus, big], 'the DSP code for payload A needs P words to 0x00bd9, past the '
            '261 words dsp:harvest:SPATIALIZER frees (44 over)')
    cf = json.loads(json.dumps(sub))
    cf['contribute'][0]['relocs'][0][2] = 'sym:core_x'
    refused([core, bus, cf], 'dsptest 0: an entry of ev_dsp_rx is a DSP reference to a '
            'ColdFire address')
    back = json.loads(json.dumps(sub))
    back['sections']['.run'] = {'len': 4, 'parts': [['hex', '00000000']]}
    back['relocs'].append(['.run', 0, 'abs32', 'sym:tst', 0])
    refused([core, bus, back], 'dsptest 0: .run+0x0 is a ColdFire reference to a DSP address')
    ent = json.loads(json.dumps(sub))
    ent['contribute'][0]['relocs'] = [[0, 'abs32', 'sym:tst', 0], [1, 'dsp24', 'sym:tst', 0]]
    refused([core, bus, ent], 'an entry for ev_dsp_rx has a abs32 relocation at +0; a DSP '
            "table's entries take dsp24, at whole words",
            'an entry for ev_dsp_rx has a dsp24 relocation at +1')
    cft = json.loads(json.dumps(core))
    cft['collections'] = {'ev_cf': {'entry': 4}}
    ent = json.loads(json.dumps(sub))
    ent['contribute'].append({'to': 'ev_cf', 'data': '00000000',
                              'relocs': [[0, 'dsp24', 'sym:tst', 0]]})
    refused([cft, bus, ent], 'an entry for ev_cf has a dsp24 relocation at +0; dsp24 is for '
            'DSP tables')
    site = json.loads(json.dumps(sub))
    o = AREA + 3 - DEV.main_load
    site['sites'] = [{'addr': '0x%08x' % (AREA + 3), 'len': 3, 'kind': 'data', 'new': '000000',
                      'stock_sha256': sha(img[o:o + 3])}]
    refused([core, bus, site], 'dspbus 0 DSP area dsp:harvest:SPATIALIZER (payload A '
            'P:0x0aa8-0x0bac) and dsptest 0 site 0x400f1774 overlap')
    # what each mod alone may hold
    for change, msg in [
            (lambda d: d['sections']['.dsp.A'].update(len=10, parts=[['hex', '00' * 10]]),
             'not whole 24-bit DSP words'),
            (lambda d: d['symbols'].update(tst=['.dsp.A', 1]), 'DSP symbol tst is not at a whole word'),
            (lambda d: d['relocs'][0].__setitem__(2, 'abs32'), 'a abs32 relocation in .dsp.A'),
            (lambda d: d['relocs'][0].__setitem__(1, 7), 'a dsp24 relocation in .dsp.A'),
            (lambda d: d.update(collections={'t': {'entry': 6, 'space': 'dsp.Q'}}),
             "table t in space 'dsp.Q', which the Octatrack lacks"),
            (lambda d: d.update(collections={'t': {'entry': 6, 'space': 'dsp.A', 'head': '00'}}),
             'DSP table t is not whole 24-bit words'),
            (lambda d: d['sections'].update({'.dsp.B2': d['sections']['.dsp.A']}),
             'unknown section .dsp.B2')]:
        d = json.loads(json.dumps(sub))
        change(d)
        expect(lambda: link.Mod2(d, 'm'), msg)
    dt = [x for x in devices.devices() if x.key == 'digitakt-mk1'][0]
    d = json.loads(json.dumps(sub))
    d['target'] = devices.target_of(dt, dt.releases['1.53'])
    expect(lambda: link.Mod2(d, 'm'), 'unknown section .dsp.A')       # no DSP code in its OS


def dsp_mod_dirs(tmp, img, source):
    """mod.json folders for dsp_docs' bus and a mod with the DSP source `source`."""
    o = HOOK - DEV.main_load
    hook = img[o:o + 6].hex()
    bus, sub = os.path.join(tmp, 'bus'), os.path.join(tmp, 'sub')
    for d in (bus, sub):
        os.makedirs(d)
    with open(os.path.join(bus, 'mod.json'), 'w') as fh:
        json.dump({'id': 'dspbus', 'version': '0', 'device': 'octatrack', 'os': '1.40C',
                   'resources': {'names': ['dsp:harvest:SPATIALIZER']},
                   'collections': {'ev_dsp_rx': {'entry': 6, 'space': 'dsp.A', 'head': hook,
                                                 'end': le24(0x0c).hex()}},
                   'sites': [{'addr': '0x%08x' % HOOK, 'stock': hook, 'op': 'dsp_jsr',
                              'target': 'ev_dsp_rx'}],
                   'requires': ['core']}, fh)
    with open(os.path.join(sub, 'test.asm'), 'w') as fh:
        fh.write(source)
    with open(os.path.join(sub, 'mod.json'), 'w') as fh:
        json.dump({'id': 'dsptest', 'version': '0', 'device': 'octatrack', 'os': '1.40C',
                   'dsp': [{'source': 'test.asm', 'payload': 'A'}],
                   'subscribe_dsp': [{'event': 'ev_dsp_rx', 'fn': 'tst', 'addend': 1}],
                   'requires': ['core']}, fh)
    return bus, sub


def test_sdk_builds_dsp_code():
    """sdk.build's "dsp", dsp_jsr sites, DSP tables and subscribe_dsp: built from mod.json, the
    bus and the mod link as dsp_docs' do. The assembler is a stand-in that evaluates each line
    at the origin, so the two-origin rule is tested without octabam's dsp_asm."""
    from elekloader.sdk import build
    st, img = stock()
    real_run, old = build.run, os.environ.get('ELEKLOADER_DSP_ASM')

    def fake_run(cmd):
        if cmd[0] != os.environ['ELEKLOADER_DSP_ASM']:
            return real_run(cmd)
        a = dict(zip(cmd[1::2], cmd[2::2]))
        org, ws, labels = int(a['-org'], 16), [], {}
        with open(a['-in']) as fh:
            for line in fh:
                t = line.split(';')[0].strip()
                if t.endswith(':'):
                    labels[t[:-1]] = org + len(ws)
                elif t:
                    ws.append(eval(t, {'org': org}))
        with open(a['-out'], 'wb') as fh:
            fh.write(le24(*ws))
        with open(a['-sym'], 'w') as fh:
            fh.write(''.join('%s %x\n' % kv for kv in labels.items()))
        return ''
    with tempfile.TemporaryDirectory() as tmp:
        fake = os.path.join(tmp, 'dsp_asm')
        open(fake, 'w').close()
        os.environ['ELEKLOADER_DSP_ASM'] = fake
        build.run = fake_run
        try:
            bus, sub = dsp_mod_dirs(tmp, img, 'tst:\n0\n0x60f400\norg + 3   ; an address\n0x0c\n')
            bp, bm = build.build(bus, SYX, tmp)
            sp, sm = build.build(sub, SYX, tmp)
            assert sm.symbols == {'tst': ('.dsp.A', 0)}, sm.symbols
            assert sm.relocs == [('.dsp.A', 6, 'dsp24', 'sec:.dsp.A', 3)], sm.relocs
            core = link.Mod2(dsp_docs(img)[0], 'core')
            ln = link.link([core, bm, sm], img)
            want = link.link([link.Mod2(d, d['id']) for d in dsp_docs(img)], img)
            assert ln.image == want.image and ln.layout == want.layout
            # an address the linker cannot place, a payload the device lacks, a short hook
            with open(os.path.join(sub, 'test.asm'), 'w') as fh:
                fh.write('tst:\n0\n(org + 3) >> 4\n')
            expect_build = lambda d, *w: _expect_build(build, d, tmp, *w)
            expect_build(sub, 'word 1 (+0x1) holds an address the linker cannot place')
            with open(os.path.join(sub, 'mod.json')) as fh:
                doc = json.load(fh)
            doc['dsp'][0]['payload'] = 'Q'
            with open(os.path.join(sub, 'mod.json'), 'w') as fh:
                json.dump(doc, fh)
            expect_build(sub, "payload 'Q'; the Octatrack has A, B")
            with open(os.path.join(bus, 'mod.json')) as fh:
                doc = json.load(fh)
            doc['sites'][0]['stock'] = doc['sites'][0]['stock'][:8]
            with open(os.path.join(bus, 'mod.json'), 'w') as fh:
                json.dump(doc, fh)
            expect_build(bus, 'a dsp_jsr replaces one two-word DSP instruction (6 bytes)')
            doc['sites'][0].update(addr='0x4000050c', stock=img[0x10c:0x112].hex())
            with open(os.path.join(bus, 'mod.json'), 'w') as fh:
                json.dump(doc, fh)
            expect_build(bus, "site 0x4000050c: a dsp_jsr goes in the DSP code the Octatrack's "
                         'OS uploads (0x400e2324 +0x136cb, 0x400f59ef +0x12d05)')
            os.environ['ELEKLOADER_DSP_ASM'] = os.path.join(tmp, 'absent')
            doc['dsp'] = [{'source': 'x.asm', 'payload': 'A'}]
            doc['sites'] = []
            with open(os.path.join(bus, 'mod.json'), 'w') as fh:
                json.dump(doc, fh)
            expect_build(bus, 'is not installed: DSP code is assembled with octabam\'s dsp_asm')
        finally:
            build.run = real_run
            if old is None:
                os.environ.pop('ELEKLOADER_DSP_ASM', None)
            else:
                os.environ['ELEKLOADER_DSP_ASM'] = old


def _expect_build(build, d, out, *words):
    try:
        build.build(d, SYX, out)
    except build.BuildError as e:
        for w in words:
            assert w in str(e), 'expected %r in: %s' % (w, e)
        return
    raise AssertionError('built')


def test_sdk_dsp_with_octabams_assembler():
    """With octabam's dsp_asm (ELEKLOADER_DSP_ASM): a loop's end address becomes the one
    relocation, and the linked words are what dsp_asm writes for that origin itself."""
    import subprocess
    from elekloader.sdk import build
    asm = os.environ.get('ELEKLOADER_DSP_ASM', '')
    if not os.path.isfile(asm):
        raise Skip('ELEKLOADER_DSP_ASM (octabam\'s dsp_asm) not given')
    st, img = stock()
    src = ('tst:\n        move    r2,x:>$204\n        move    x:>$202,r1\n'
           '        do      #4,loop_end\n        nop\n        nop\nloop_end:\n        rts\n')
    with tempfile.TemporaryDirectory() as tmp:
        bus, sub = dsp_mod_dirs(tmp, img, src)
        bp, bm = build.build(bus, SYX, tmp)
        sp, sm = build.build(sub, SYX, tmp)
        n = sm.size('.dsp.A') // 3
        end = sm.symbols['loop_end'][1] // 3
        assert [(o, t, g) for _s, o, t, g, _a in sm.relocs] == [(15, 'dsp24', 'sec:.dsp.A')]
        assert sm.relocs[0][4] == end - 1                       # do's operand: the last word
        ln = link.link([link.Mod2(dsp_docs(img)[0], 'core'), bm, sm], img)
        blob = os.path.join(tmp, 'at.bin')
        subprocess.run([asm, '-in', os.path.join(sub, 'test.asm'), '-org', 'aa8', '-out', blob],
                       check=True, capture_output=True)
        with open(blob, 'rb') as fh:
            want = fh.read()
    o = AREA - DEV.main_load
    assert len(want) == 3 * n and ln.image[o:o + 3 * n] == want


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
