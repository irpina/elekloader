# SPDX-License-Identifier: GPL-2.0-or-later
"""elekloader.sdk.octabam: octabam modules -> Octatrack mods (pytest, or run with python).

Needs files named by environment variables; a test whose inputs are missing
is skipped, not passed:
  ELEKLOADER_OT_SYX    OCTATRACK_OS1.40C.syx
  ELEKLOADER_OCTABAM   optional: a sambanks/octabam checkout; without one, only
                       the synthetic module below is converted
Building and checking also needs the cross binutils (m68k-linux-gnu-as, -ld,
-objcopy).
"""
import os
import shutil
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, elemod, formats, link   # noqa: E402
from elekloader.sdk import build, octabam               # noqa: E402

SYX = os.environ.get('ELEKLOADER_OT_SYX', '')
OCTABAM = os.environ.get('ELEKLOADER_OCTABAM', '')
DEV = [d for d in devices.devices() if d.key == 'octatrack'][0]


class Skip(Exception):
    pass


_c = {}


def stock():
    if not SYX or not os.path.exists(SYX):
        raise Skip('missing ELEKLOADER_OT_SYX')
    if 'img' not in _c:
        st, dev, _rel = formats.load(SYX)
        _c['img'] = formats.main_image(st, dev)
    return _c['img']


def tools():
    for t in ('as', 'ld', 'objcopy'):
        if not shutil.which(os.environ.get('ELEKLOADER_CROSS', DEV.toolchain['prefix']) + t):
            raise Skip('no m68k cross binutils')


def core(out):
    if 'core' not in _c:
        _c['core'], _m = build.build(os.path.join(ROOT, 'mods', 'core-ot'), SYX,
                                     tempfile.mkdtemp())
    return _c['core']


# ---- a synthetic checkout: every mapping, no octabam needed ---------------------------------
# The sites are real 1.40C ones (octabam's FLEX SEEK BIND, FLEX SEEK BIND CTR and RLEN
# PLEN hook these), so their stock bytes check against the user's image.

MANIFEST = '''
from types import SimpleNamespace as NS

def emit(addr):
    return b"", ((0x4002fb10, bytes.fromhex("2f04487af710"),
                  bytes.fromhex("4eb9") + (addr + 8).to_bytes(4, "big")),
                 (0x400d3d4e, (65).to_bytes(4, "big"), (66).to_bytes(4, "big")))

CAVE = NS(label="a cave", cave_addr=None, pinned=b"", source="modules/fake/cave.s",
          hook_addr=0x4000f8cc, hook_stock=bytes.fromhex("4a2f00376718"),
          registers_formatter=None, emit=emit, defsyms=(("STOCK_RTS", 0x40027e1a),),
          cpu="5475", reference=None, pool_base_literals=1)
UNIT = NS(label="unit", source="modules/fake/unit.s", cave_addr=None, cpu="54455",
          reference=None, dram=True, include=None)
DETOUR = NS(site=0x4000f834, expect=bytes.fromhex("52aa009025480098"), unit="unit",
            symbol="fake_entry", note="", kind="jmp", target=None, pad_to=None,
            subst_return=False)
MODULE = NS(name="fake", key="FAKE", doc="a test module", dsp=None, menu=None, params=(),
            runtime=None, arena=None, overrides=(), cf_patches=(CAVE,), linked=(UNIT,),
            detours=(DETOUR,), symbol_refs=(), tables=(), pokes=(), requires=(),
            claims=NS(part_window=((0x90492, 20, "x"),), sram=()), category=None,
            author="test")
'''

CAVE_S = '''
        .text
        cmpi.l  #0x40a955e0,%d0         | the arena's stock base: follows the core's
        beq.s   1f
        rts
1:      jmp     STOCK_RTS
        nop
screen: rts
'''

UNIT_S = '''
        .text
        .globl  fake_entry
fake_entry:
        addq.l  #1,(144,%a2)
        move.l  %a0,(152,%a2)
        jmp     0x4000f83c
'''


# A bridge: it stands in for FAKE's detour at 0x4000f834, so it carries FAKE.
BRIDGE = '''
from types import SimpleNamespace as NS
UNIT = NS(label="bunit", source="modules/bridge/bunit.s", cave_addr=None, cpu="54455",
          reference=None, dram=True, include=None)
MODULE = NS(name="bridge", key="BRIDGE", doc="a bridge", dsp=None, menu=None, params=(),
            runtime=None, arena=None, cf_patches=(), linked=(UNIT,),
            overrides=(NS(site=0x4000f834, module="FAKE", write=None, defsym=None),),
            detours=(NS(site=0x4000f834, expect=bytes.fromhex("52aa009025480098"),
                        unit="bunit", symbol="bridge_entry", note="", kind="jmp", target=None,
                        pad_to=8, subst_return=False),),
            symbol_refs=(), tables=(), pokes=(), requires=(), claims=None, category=None,
            author="test")
'''

BUNIT_S = '''
        .text
        .globl  bridge_entry
bridge_entry:
        jmp     fake_entry
'''

# A unit whose generated include changes with FAKE (which converts) and with DSPMOD
# (which does not).
INCMOD = '''
from types import SimpleNamespace as NS

def inc(mods):
    return ".set HAS_FAKE, %d\\n.set HAS_DSP, %d\\n" % ("FAKE" in mods, "DSPMOD" in mods)

UNIT = NS(label="iunit", source="modules/incmod/iunit.s", cave_addr=None, cpu="54455",
          reference=None, dram=True, include=inc)
MODULE = NS(name="incmod", key="INCMOD", doc="an include", dsp=None, menu=None, params=(),
            runtime=None, arena=None, overrides=(), cf_patches=(), linked=(UNIT,), detours=(),
            symbol_refs=(), tables=(), pokes=(), requires=(), claims=None, category=None,
            author="test")
'''

IUNIT_S = '''
        .include "remix.inc"
        .text
        .globl  incmod_flags
incmod_flags:
        .byte   HAS_FAKE, HAS_DSP
'''

DSPMOD = '''
from types import SimpleNamespace as NS
MODULE = NS(name="dspmod", key="DSPMOD", doc="DSP", dsp=object(), menu=None, params=(),
            overrides=(), linked=(), cf_patches=(), requires=())
'''

# Pinned code: a cave and a unit at fixed addresses in the image's free run.
PINNED = '''
from types import SimpleNamespace as NS
CAVE = NS(label="pcave", cave_addr=0x400d64e0, pinned=b"", source="modules/pinned/pcave.s",
          hook_addr=0x4000f8cc, hook_stock=bytes.fromhex("4a2f00376718"),
          registers_formatter=None, emit=None, defsyms=(), cpu="5475", reference=None,
          pool_base_literals=0)
UNIT = NS(label="punit", source="modules/pinned/punit.s", cave_addr=0x400d6500, cpu="5407",
          reference=None, dram=False, include=None)
MODULE = NS(name="pinned", key="PINNED", doc="pinned code", dsp=None, menu=None, params=(),
            runtime=None, arena=None, overrides=(), cf_patches=(CAVE,), linked=(UNIT,),
            detours=(), symbol_refs=(), tables=(), pokes=(), requires=(), claims=None,
            category=None, author="test")
'''

PCAVE_S = '''
        .text
        tst.b   (55,%sp)
        jmp     punit_entry
'''

PUNIT_S = '''
        .text
        .globl  punit_entry
punit_entry:
        lea     punit_entry,%a0
        rts
'''


def fake_checkout(tmp):
    root = os.path.join(tmp, 'octabam')
    for rel, text in (('tools/remix/schema.py', ''), ('modules/fake/manifest.py', MANIFEST),
                      ('modules/fake/cave.s', CAVE_S), ('modules/fake/unit.s', UNIT_S),
                      ('modules/bridge/manifest.py', BRIDGE), ('modules/bridge/bunit.s', BUNIT_S),
                      ('modules/incmod/manifest.py', INCMOD), ('modules/incmod/iunit.s', IUNIT_S),
                      ('modules/dspmod/manifest.py', DSPMOD),
                      ('modules/pinned/manifest.py', PINNED), ('modules/pinned/pcave.s', PCAVE_S),
                      ('modules/pinned/punit.s', PUNIT_S),
                      ('LICENSE', 'MIT, for the test\n')):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as fh:
            fh.write(textwrap.dedent(text))
    return octabam.Octabam(root)


def test_the_mappings():
    img = stock()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        plan = octabam.convert(ob, 'fake', img, DEV)
    j = plan['json']
    by = {s['addr']: s for s in j['sites']}
    sym = 'ob_fake_a_cave'
    assert by['0x4000f8cc'] == {'addr': '0x4000f8cc', 'stock': '4a2f00376718', 'op': 'jsr',
                                'target': sym}
    # emit's poke that holds the cave's address + 8: a jsr against the cave, addend 8
    assert by['0x4002fb10']['op'] == 'jsr' and by['0x4002fb10']['addend'] == 8
    assert by['0x400d3d4e'] == {'addr': '0x400d3d4e', 'stock': '00000041', 'op': 'bytes',
                                'new': '00000042'}
    # a six-byte jmp would cut `move.l a0,(152,a2)`: padded to the instruction's end
    assert by['0x4000f834']['op'] == 'jmp' and len(by['0x4000f834']['stock']) == 16
    assert j['defsym'] == {'STOCK_RTS': '0x40027e1a'}
    assert j['requires'] == ['core'] and j['license'] == 'MIT'
    assert j['resources']['names'] == ['octabam:part-window@0x90490', 'octabam:part-window@0x904a0']
    assert b'cmpi.l  #arena_base' in plan['files']['modules/fake/cave.s']
    assert b'.include "modules/fake/cave.s"' in plan['files']['glue/%s.s' % sym]


def test_the_synthetic_module_builds_and_checks():
    img = stock()
    tools()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        plan = octabam.convert(ob, 'fake', img, DEV)
        d = octabam.write(ob, plan, tmp)
        assert os.path.exists(os.path.join(d, 'LICENSE.octabam'))
        path, mod = build.build(d, SYX, tmp)
        lines = octabam.check(ob, plan, path, core(tmp), SYX, os.path.join(tmp, 'check'))
    assert any('1 arena-base literal(s) moved' in x for x in lines), lines
    assert any('as GNU ld links them' in x for x in lines), lines
    assert 'arena_base' in mod.imports


def build_and_check(ob, name, tmp):
    plan = octabam.convert(ob, name, stock(), DEV)
    d = octabam.write(ob, plan, tmp)
    path, mod = build.build(d, SYX, tmp)
    lines = octabam.check(ob, plan, path, core(tmp), SYX, os.path.join(tmp, name + '.check'))
    return plan, mod, lines


def test_a_bridge_carries_what_it_bridges():
    """BRIDGE stands in for FAKE's detour: one mod with both, the bridge's detour at
    the shared site, and a conflict with FAKE alone."""
    stock()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        plan = octabam.convert(ob, 'bridge', stock(), DEV)
        j = plan['json']
        assert plan['members'] == ['bridge', 'fake'] and j['conflicts'] == ['octabam-fake']
        assert j['title'] == 'BRIDGE (with FAKE)'
        at = [x for x in j['sites'] if x['addr'] == '0x4000f834']
        assert at == [{'addr': '0x4000f834', 'stock': '52aa009025480098', 'op': 'jmp',
                       'target': 'bridge_entry'}], at
        tools()
        plan, mod, lines = build_and_check(ob, 'bridge', tmp)
    assert any('(1 stood in for)' in x for x in lines), lines
    assert 'bridge_entry' in mod.exports and 'fake_entry' in mod.exports


def test_a_generated_include_that_changes_with_another_module():
    stock()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        plan = octabam.convert(ob, 'incmod', stock(), DEV)
    j = plan['json']
    assert j['conflicts'] == ['octabam-fake'], j.get('conflicts')
    assert plan['files']['glue/incmod_iunit.inc'] == b'.set HAS_FAKE, 0\n.set HAS_DSP, 0\n'
    assert b'.include "glue/incmod_iunit.inc"' in plan['files']['modules/incmod/iunit.s']
    assert any('dspmod' in n and 'do not convert' in n for n in plan['notes']), plan['notes']


def test_pinned_code_stays_where_it_is_pinned():
    stock()
    tools()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        plan, mod, lines = build_and_check(ob, 'pinned', tmp)
    assert plan['json']['fixed'] == [
        {'source': 'modules/pinned/pcave.s', 'addr': '0x400d64e0', 'symbol': 'ob_pinned_pcave'},
        {'source': 'modules/pinned/punit.s', 'addr': '0x400d6500'}]
    assert mod.symbols['ob_pinned_pcave'] == ('abs', 0x400d64e0)
    assert mod.symbols['punit_entry'] == ('abs', 0x400d6500)
    assert not mod.size('.run')
    assert sum('fixed code' in x for x in lines) == 2, lines
    assert any('the same bytes for 5407 as for the chip' in x for x in lines), lines


def test_converted_mods_stay_out_of_the_checkout():
    assert octabam.inside_checkout(os.path.join(ROOT, 'octabam-mods')) == \
        os.path.exists(os.path.join(ROOT, '.git'))
    assert not octabam.inside_checkout(tempfile.gettempdir())


def test_refusals():
    from types import SimpleNamespace as NS
    img = stock()
    with tempfile.TemporaryDirectory() as tmp:
        ob = fake_checkout(tmp)
        m = ob.modules['fake']
        cases = (
            ({'dsp': object()}, 'DSP code'),
            ({'runtime': type('R', (), {'recipe': 'r.json'})()}, 'runtime'),
            ({'overrides': (NS(site=0x4000f834, module='NOTHING', write=None, defsym=None),)},
             'needs NOTHING'),
            ({'overrides': (NS(site=0x4000f834, module='BRIDGE', write='w', defsym=None),)},
             'runtime write w'),
            ({'pokes': (NS(addr=0x400e2004, expect=bytes(3), write=bytes.fromhex('ef0201'),
                           note=''),)}, 'protects'),
            ({'cf_patches': (m.cf_patches[0].__class__(**dict(vars(m.cf_patches[0]),
                                                                cave_addr=0x400d2000)),)},
             'pinned'),
            ({'requires': ('NOTHING',)}, 'needs NOTHING'),
        )
        for change, words in cases:
            ob.modules['fake'] = m.__class__(**dict(vars(m), **change))
            try:
                octabam.convert(ob, 'fake', img, DEV)
            except octabam.Refused as e:
                assert words in str(e), (words, str(e))
            else:
                raise AssertionError('not refused: %s' % words)
        ob.modules['fake'] = m
        with open(os.path.join(ob.root, 'modules', 'fake', 'x.asm'), 'w') as fh:
            fh.write('; DSP56300\n')
        assert 'DSP56300' in octabam.refusal(ob, 'fake')


# ---- a real checkout ------------------------------------------------------------------------

def real():
    if not OCTABAM or not os.path.isdir(OCTABAM):
        raise Skip('missing ELEKLOADER_OCTABAM')
    if 'ob' not in _c:
        _c['ob'] = octabam.Octabam(OCTABAM)
    return _c['ob']


def convert_all(names):
    ob, img = real(), stock()
    tools()
    out = tempfile.mkdtemp()
    done = {}
    for n in names:
        plan = octabam.convert(ob, n, img, DEV)
        d = octabam.write(ob, plan, out)
        path, mod = build.build(d, SYX, out)
        octabam.check(ob, plan, path, core(out), SYX, os.path.join(out, n + '.check'))
        done[n] = mod
    return done


def test_real_modules_convert_and_check():
    """One of each shape: a pool-literal cave, emit's pokes (a nop-padded jsr among
    them), defsyms with a ratified reference(), DRAM units with detours, a
    floating unit with symbol refs and pokes."""
    done = convert_all(['recorder-hold', 'rlen-plen', 'direct-jump', 'cc-map', 'tuner',
                        'repitch', 'quantizer', 'synth', 'lofi-amf-fix'])
    assert len(done['recorder-hold'].sites) == 3 and 'arena_base' in done['recorder-hold'].imports
    # pinned code, at octabam's addresses: SYNTH's page, QUANTIZER's two units
    assert done['synth'].symbols['ob_synth_synth_page'] == ('abs', 0x400d24d0)
    assert {s['addr'] for s in done['quantizer'].sites} >= {0x400d2ca8, 0x400d2cb0}
    assert not done['lofi-amf-fix'].size('.run') and len(done['lofi-amf-fix'].sites) == 2


def test_real_usb_midi_with_a_bare_metal_assembler():
    """USB MIDI's unit reproduces its author's bytes only with an assembler that resolves
    references to its own global labels, as octabam's m68k-elf does."""
    real()
    if not octabam.bare_metal(DEV):
        raise Skip('the configured assembler is not bare metal (ELEKLOADER_CROSS=m68k-elf-)')
    done = convert_all(['usb-midi'])
    assert done['usb-midi'].size('.run') > 0


def test_real_refusals():
    ob = real()
    for n, words in (('busverb', 'DSP code'), ('analog-bassdrum', 'DSP56300'),
                     ('octakit', 'runtime'), ('tempo-sync', 'formatter'),
                     ('kits-reload', 'runtime write'), ('cfmeter-idle', 'needs CF METER'),
                     ('rig-hosts', 'serves DSP'), ('tempo-bus', 'serves DSP'),
                     ('mode-defaults', 'serves DSP')):
        if n in ob.modules:
            assert words in (octabam.refusal(ob, n) or ''), (n, octabam.refusal(ob, n))
    # USB AUDIO OUT sets the class of the USB device descriptor at 0x400e2004, inside the
    # bootloader copy elekloader protects
    if 'usb-audio-out-main' in ob.modules:
        try:
            octabam.convert(ob, 'usb-audio-out-main', stock(), DEV)
        except octabam.Refused as e:
            assert 'protects' in str(e) and '0x400e2004' in str(e), str(e)
        else:
            raise AssertionError('usb-audio-out-main converted')


def test_real_overlapping_claims_do_not_combine():
    """octabam's ledger refuses MIDI SCENES with SCENES P2 (their Part-window
    claims overlap); so does the linker, by the claims' block names."""
    done = convert_all(['midi-scenes', 'scenes-p2'])
    img = stock()
    probs = link.check([elemod.load_any(_c['core'])] + list(done.values()), img)
    assert any('octabam:part-window@' in p for p in probs), probs


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
