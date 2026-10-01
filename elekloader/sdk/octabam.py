# SPDX-License-Identifier: GPL-2.0-or-later
"""sambanks/octabam's ColdFire modules -> linkable Octatrack mods (format 2).

    python -m elekloader.sdk.octabam --octabam PATH --stock OCTATRACK_OS1.40C.syx
                                     [--module NAME ...] [--out DIR] [--core CORE.elemod]

octabam (MIT) declares each module in modules/<name>/manifest.py, in the
vocabulary of its tools/remix/schema.py. This reads the manifests of a
checkout and, for each module, writes an SDK mod folder: mod.json, the
module's sources, and generated glue. It builds each folder with sdk.build,
links the result with the Octatrack's core (mods/core-ot), and checks it
against octabam's own account of the bytes (below).

Placement differs from octabam's, on purpose. Everything goes in the core's
RAM reserve (`.run`), which is the reserve octabam's own DRAM units use.
That includes the caves octabam puts in the zero runs inside the OS image,
so a cave is the same code at another address. A module converts when it
uses only these:

| octabam (schema.py) | here |
|---|---|
| CavePatch, floating, with a source | the source in .run, under a glue label; its hook a `jsr` site |
| CavePatch.emit's pokes | sites; a poke that holds the cave's address is a jsr/jmp/ptr site against it |
| CavePatch.defsyms | the assembler's --defsym, with the manifest's values |
| CavePatch.pool_base_literals | the literal becomes the core's `arena_base` (the moved base) |
| Linked, dram or floating | .run; an `include` is generated for a remix of this module alone |
| Detour jmp/jsr (pad_to), lea, a stock target | jmp/jsr sites, keep2, a code `bytes` site |
| SymbolRef | a ptr site, with its addend |
| TableGrow | the grown table in .run, a ptr site at each ref |
| Poke | a bytes site |
| requires | requires, by the converted ids |
| Claims (part window, SRAM) | named resources, one per 16-byte block, so mods whose claims overlap are refused together |

Anything else refuses the module, with the reason:
- DSP code or an FX menu entry (only ColdFire-only modules convert);
- a cave or unit pinned to an address in the OS image;
- a formatter registered on another module's knob (a DSP module's);
- a loader-appended Runtime (Octakit), an ArenaReserve, an Override (a
  bridge between two modules' hooks);
- requiring a module that does not convert.

Where octabam links one module's symbol into another at build time (a
CavePatch.defsym another unit exports, e.g. CC MAP's CC_MODEDEF1 from MODE
DEFAULTS), the converted mod keeps the manifest's own value.

**The check.** With every module linked alone with the core:
- each cave's bytes in RAM must equal its source assembled and linked by
  GNU ld at that address, as octabam's build does. The arena-base literals
  are counted and moved as octabam does.
- Those bytes must equal the manifest's ratified ones (`reference(addr)`,
  or `pinned`), as octabam requires.
- Every site must hold what octabam would write, computed from the final
  addresses (hooks, emit's pokes, detours, symbol refs, pokes, tables).
- The whole of the mod's RAM must equal GNU ld's link of the same object
  at the same addresses.
- A unit with a `reference` (address, sha256) must still link to it.
"""
import argparse
import contextlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys

from .. import elemod, formats, link
from . import build as sdkbuild

DEVICE = 'octatrack'
ARENA_STOCK_BASE = 0x40A955E0
EMIT_AT = (0x10000000, 0x20000000)      # two trial addresses for a cave's emit()
NOP = b'\x4e\x71'
OPS = {'jmp': b'\x4e\xf9', 'jsr': b'\x4e\xb9'}
ASM = ('.s', '.S', '.inc', '.i', '.h')
HERE = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'mods', 'core-ot')


class Refused(Exception):
    """The module does not convert; the message says why."""


class CheckError(Exception):
    pass


@contextlib.contextmanager
def _in(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def mod_id(name):
    return 'octabam-' + name


def _slug(s):
    return re.sub(r'\W+', '_', s).strip('_').lower()


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], 'big')


# ---- the checkout -------------------------------------------------------------------

class Octabam:
    """An octabam checkout: its modules by directory name, and its commit."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        tools = os.path.join(self.root, 'tools')
        if not os.path.isfile(os.path.join(tools, 'remix', 'schema.py')):
            raise ValueError('%s is not an octabam checkout (no tools/remix/schema.py)' % root)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        self.modules, self.broken = {}, {}
        with _in(self.root):
            for name in sorted(os.listdir('modules')):
                p = os.path.join('modules', name, 'manifest.py')
                if name.startswith('_') or not os.path.isfile(p):
                    continue
                try:
                    g = runpy.run_path(p, run_name='octabam_' + _slug(name))
                    self.modules[name] = g['MODULE']
                except Exception as e:      # the manifest's own code: report, go on
                    self.broken[name] = '%s: %s' % (type(e).__name__, e)
        self.by_key = {m.key: n for n, m in self.modules.items()}
        try:
            self.commit = subprocess.run(['git', '-C', self.root, 'rev-parse', '--short=7', 'HEAD'],
                                         capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            self.commit = 'unknown'

    def call(self, fn, *a):
        """A manifest's callable (emit, reference, include), run where octabam runs it."""
        with _in(self.root):
            return fn(*a)


# ---- what converts --------------------------------------------------------------------

def refusal(ob, name, _seen=()):
    """Why module `name` does not convert, or None."""
    m = ob.modules[name]
    if m.dsp is not None or m.menu is not None or m.params:
        return 'it has DSP code or an FX menu entry (only ColdFire-only modules convert)'
    for _dp, _dns, fns in os.walk(os.path.join(ob.root, 'modules', name)):
        if any(f.endswith('.asm') for f in fns):
            return ('it carries DSP56300 code (.asm), which its build uploads (only '
                    'ColdFire-only modules convert)')
    if m.runtime is not None:
        return 'it is a loader-appended runtime (%s)' % m.runtime.recipe
    if m.arena is not None:
        return 'it reserves arena pages of its own'
    if m.overrides:
        return ('it bridges other modules\' hooks (Override), which elekloader has no form '
                'for yet')
    for c in m.cf_patches:
        if c.cave_addr is not None:
            return ('its cave "%s" is pinned at 0x%08x in the OS image; elekloader places '
                    'code only in RAM so far' % (c.label, c.cave_addr))
        if not c.source:
            return 'its cave "%s" has no source' % c.label
        if c.registers_formatter is not None:
            return ('its cave "%s" draws a knob of %s (a formatter registration), a DSP module'
                    % (c.label, c.registers_formatter.module))
    for u in m.linked:
        if not u.dram and u.cave_addr is not None:
            return ('its unit "%s" is pinned at 0x%08x in the OS image; elekloader places '
                    'code only in RAM so far' % (u.label, u.cave_addr))
    for k in m.requires:
        n = ob.by_key.get(k)
        if n is None:
            return 'it requires %s, which this checkout does not have' % k
        if n in _seen:
            continue
        why = refusal(ob, n, _seen + (name,))
        if why:
            return 'it requires %s, which does not convert: %s' % (k, why)
    return None


def _boundary(image, addr, n, dev):
    """The first instruction boundary at or after addr + n, decoding from addr."""
    isa = dev.decoder()
    read = isa.reader(image, dev.main_load)
    a = addr
    while a < addr + n:
        a += isa.decode(read(a), a).length
    return a - addr


def _stock(image, dev, addr, n):
    o = addr - dev.main_load
    return image[o:o + n]


def convert(ob, name, image, dev):
    """-> a plan: {'id', 'json' (mod.json), 'files' ({relpath: bytes}), 'caves', 'tables',
    'notes'}. Raises Refused."""
    why = refusal(ob, name)
    if why:
        raise Refused(why)
    m = ob.modules[name]
    mid, ms = mod_id(name), _slug(name)
    notes, sites, sources, files = [], [], [], {}
    defsym, caves, tables, names = {}, [], [], []

    # the module's assembler files, at their repo paths (sources .include them so)
    mdir = os.path.join(ob.root, 'modules', name)
    pool = any(c.pool_base_literals for c in m.cf_patches)
    for dp, dns, fns in os.walk(mdir):
        dns[:] = [d for d in dns if not d.startswith('.')]
        for fn in fns:
            if not fn.endswith(ASM):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ob.root).replace(os.sep, '/')
            with open(p, 'rb') as fh:
                data = fh.read()
            if re.search(rb'^\s*\.incbin\b', data, re.M):
                raise Refused('%s includes binary data (.incbin)' % rel)
            if pool:
                data = re.sub(rb'(?i)\b0x40a955e0\b', b'arena_base', data)
            files[rel] = data
    for src in [c.source for c in m.cf_patches] + [u.source for u in m.linked]:
        if src not in files:
            raise Refused('its source %s is outside modules/%s' % (src, name))

    def site(addr, stock, **kw):
        s = {'addr': '0x%08x' % addr, 'stock': stock.hex()}
        s.update(kw)
        sites.append(s)

    # caves: the source under a label, the hook, emit's pokes
    for c in m.cf_patches:
        sym = 'ob_%s_%s' % (ms, _slug(c.label))
        glue = 'glue/%s.s' % sym
        files[glue] = ('| generated by elekloader.sdk.octabam from octabam %s: %s, "%s"\n'
                       '        .text\n        .globl  %s\n%s:\n        .include "%s"\n'
                       % (ob.commit, m.key, c.label, sym, sym, c.source)).encode()
        sources.append(glue)
        for n, v in c.defsyms:
            if defsym.get(n, v) != v:
                raise Refused('two caves give %s different values' % n)
            defsym[n] = v
            notes.append('%s = 0x%08x, the manifest\'s value (octabam may link another '
                         'module\'s symbol there)' % (n, v))
        if c.hook_addr is not None:
            if _stock(image, dev, c.hook_addr, len(c.hook_stock)) != c.hook_stock:
                raise Refused('the hook site 0x%08x of "%s" is not stock' % (c.hook_addr, c.label))
            site(c.hook_addr, c.hook_stock, op='jsr', target=sym)
        if c.emit is not None:
            (b1, p1), (b2, p2) = [ob.call(c.emit, a) for a in EMIT_AT]
            if b1 or b2:
                raise Refused('the cave "%s" emits hand-assembled bytes (octabam\'s legacy path)'
                              % c.label)
            if len(p1) != len(p2):
                raise Refused('the cave "%s" emits different pokes at different addresses'
                              % c.label)
            for (pa, exp, w1), (pa2, exp2, w2) in zip(p1, p2):
                if (pa, exp) != (pa2, exp2) or len(w1) != len(w2):
                    raise Refused('the cave "%s" emits different pokes at different addresses'
                                  % c.label)
                if _stock(image, dev, pa, len(exp)) != exp:
                    raise Refused('the poke at 0x%08x is not stock' % pa)
                stock = _stock(image, dev, pa, len(w1))
                if w1 == w2:
                    site(pa, stock, op='bytes', new=w1.hex())
                    continue
                # the one word that moves with the cave: its offset in the poke, and in the cave
                at = [i for i in range(0, len(w1) - 3, 2)
                      if w1[:i] == w2[:i] and w1[i + 4:] == w2[i + 4:]
                      and _u32(w1, i) - EMIT_AT[0] == _u32(w2, i) - EMIT_AT[1]]
                if at:
                    i, d = at[0], _u32(w1, at[0]) - EMIT_AT[0]
                    if i == 0 and len(w1) == 4:
                        site(pa, stock, op='ptr', target=sym, addend=d)
                        continue
                    if i == 2 and w1[:2] in OPS.values() and w1[6:] == NOP * ((len(w1) - 6) // 2):
                        site(pa, stock, op='jsr' if w1[:2] == OPS['jsr'] else 'jmp', target=sym,
                             addend=d)
                        continue
                    if i == 2 and len(w1) == 6 and w1[:2] == stock[:2]:
                        site(pa, stock, op='keep2', target=sym, addend=d)
                        continue
                raise Refused('the cave "%s" emits a poke at 0x%08x that elekloader cannot '
                              'express (%s)' % (c.label, pa, w1.hex()))
        caves.append({'label': c.label, 'sym': sym})

    # linked units
    incs = {}
    for u in m.linked:
        sources.append(u.source)
        if u.include is not None:
            try:
                incs[u.label] = ob.call(u.include, {m.key: m})
            except Exception as e:           # a manifest's own code: any failure refuses
                raise Refused('the generated include of "%s" needs more than this module (%s)'
                              % (u.label, e))
            notes.append('"%s": its remix.inc is generated for a remix of this module alone'
                         % u.label)
    if len(set(incs.values())) > 1:
        raise Refused('two units need different generated includes')
    if incs:
        files['remix.inc'] = list(incs.values())[0].encode()
    labels = {u.label for u in m.linked}

    for d in m.detours:
        if d.target is None and d.unit not in labels:
            raise Refused('a detour at 0x%08x names unit %s of another module' % (d.site, d.unit))
        if _stock(image, dev, d.site, len(d.expect)) != d.expect:
            raise Refused('the detour site 0x%08x is not stock' % d.site)
        n = d.pad_to or 6
        if d.kind == 'lea':
            if n != 6 or d.target is not None:
                raise Refused('a lea detour at 0x%08x that is not six bytes' % d.site)
            site(d.site, _stock(image, dev, d.site, 6), op='keep2', target=d.symbol)
            continue
        whole = _boundary(image, d.site, n, dev)
        if whole != n:
            if d.kind != 'jmp':
                raise Refused('the jsr detour at 0x%08x ends inside an instruction' % d.site)
            notes.append('the jmp at 0x%08x is nop-padded to the next instruction (%d bytes, '
                         'not %d)' % (d.site, whole, n))
            n = whole
        stock = _stock(image, dev, d.site, n)
        if d.target is not None:
            new = OPS[d.kind] + d.target.to_bytes(4, 'big') + NOP * ((n - 6) // 2)
            site(d.site, stock, op='bytes', new=new.hex(), kind='code')
        else:
            site(d.site, stock, op=d.kind, target=d.symbol)

    for r in m.symbol_refs:
        if r.unit not in labels:
            raise Refused('a symbol ref at 0x%08x names unit %s of another module'
                          % (r.addr, r.unit))
        stock = r.expect.to_bytes(4, 'big')
        if _stock(image, dev, r.addr, 4) != stock:
            raise Refused('the symbol ref at 0x%08x is not stock' % r.addr)
        site(r.addr, stock, op='ptr', target=r.symbol, addend=r.addend)

    for t in m.tables:
        for u, _s in t.symbols:
            if u not in labels:
                raise Refused('table %s names unit %s of another module' % (t.label, u))
        sym = 'ob_%s_%s' % (ms, _slug(t.label))
        old = [_u32(_stock(image, dev, t.old, 4 * t.count), 4 * i) for i in range(t.count)]
        body = ''.join('        .long   0x%08x\n' % v for v in old)
        body += ''.join('        .long   %s\n' % s for _u, s in t.symbols)
        glue = 'glue/%s.s' % sym
        files[glue] = ('| generated by elekloader.sdk.octabam from octabam %s: %s, table "%s"\n'
                       '        .text\n        .balign 4\n        .globl  %s\n%s:\n%s'
                       % (ob.commit, m.key, t.label, sym, sym, body)).encode()
        sources.append(glue)
        for ra, v in t.refs:
            stock = v.to_bytes(4, 'big')
            if _stock(image, dev, ra, 4) != stock:
                raise Refused('the table ref at 0x%08x is not stock' % ra)
            site(ra, stock, op='ptr', target=sym)
        tables.append({'label': t.label, 'sym': sym})

    for p in m.pokes:
        if _stock(image, dev, p.addr, len(p.expect)) != p.expect:
            raise Refused('the poke at 0x%08x is not stock' % p.addr)
        site(p.addr, _stock(image, dev, p.addr, len(p.write)), op='bytes', new=p.write.hex())

    if m.claims is not None:
        # one name per 16-byte block claimed, so any two claims that overlap share a name
        for kind, spans in (('part-window', m.claims.part_window), ('sram', m.claims.sram)):
            for a, n, _what in spans:
                names += ['octabam:%s@0x%x' % (kind, b) for b in range(a & ~15, a + n, 16)]
        if names:
            notes.append('its claims are named resources, one per 16-byte block: a mod that '
                         'claims any of the same blocks is refused beside it')

    cat = getattr(m.category, 'value', '') if m.category is not None else ''
    doc = {
        'id': mid, 'version': ob.commit, 'title': m.key,
        'description': '%s (octabam module %s, converted from %s)' % (m.doc, name, ob.commit),
        'category': cat, 'author': m.author, 'license': 'MIT',
        'device': DEVICE, 'os': '1.40C',
        'sources': sources,
        'sites': sites,
        'requires': ['core'] + [mod_id(ob.by_key[k]) for k in m.requires],
    }
    if defsym:
        doc['defsym'] = {k: '0x%08x' % v for k, v in defsym.items()}
    if names:
        doc['resources'] = {'names': names}
    return {'id': mid, 'name': name, 'json': doc, 'files': files, 'caves': caves,
            'tables': tables, 'notes': notes}


def write(ob, plan, out):
    """The plan as an SDK mod folder under `out`; -> its path."""
    d = os.path.join(out, plan['id'])
    if os.path.isdir(d):
        shutil.rmtree(d)
    for rel, data in plan['files'].items():
        p = os.path.join(d, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(data)
    with open(os.path.join(d, 'mod.json'), 'w', newline='\n') as fh:
        json.dump(plan['json'], fh, indent=1)
        fh.write('\n')
    lic = os.path.join(ob.root, 'LICENSE')
    if os.path.isfile(lic):
        shutil.copyfile(lic, os.path.join(d, 'LICENSE.octabam'))
    with open(os.path.join(d, 'README.md'), 'w', newline='\n') as fh:
        m = ob.modules[plan['name']]
        fh.write('# %s\n\n%s\n\nConverted by elekloader.sdk.octabam from sambanks/octabam %s, '
                 'modules/%s (MIT, LICENSE.octabam). The sources are octabam\'s%s; glue/ is '
                 'generated.\n' % (m.key, m.doc, ob.commit, plan['name'],
                                   ', with the arena-base literal named `arena_base`'
                                   if any(c.pool_base_literals for c in m.cf_patches) else ''))
        if plan['notes']:
            fh.write('\nNotes:\n' + ''.join('- %s\n' % n for n in plan['notes']))
    return d


# ---- the check ------------------------------------------------------------------------

def _tool(dev, name):
    return os.environ.get('ELEKLOADER_CROSS', dev.toolchain['prefix']) + name


def _gnu(dev, work, cmd, cwd=None):
    r = subprocess.run([_tool(dev, cmd[0])] + [str(x) for x in cmd[1:]], cwd=cwd,
                       capture_output=True, text=True)
    if r.returncode:
        raise CheckError('%s failed\n%s%s' % (' '.join(str(x) for x in cmd), r.stdout, r.stderr))
    return r.stdout


def _gnu_link(ob, dev, src, at, cpu, defsyms, work, sections=('.text',)):
    """octabam's _link: `src` assembled and linked at `at`; `sections` kept (all if empty)."""
    os.makedirs(work, exist_ok=True)
    o, e, b = [os.path.join(work, x) for x in ('u.o', 'u.elf', 'u.bin')]
    _gnu(dev, work, ['as', '-mcpu=%s' % cpu, '-o', o, src], cwd=ob.root)
    _gnu(dev, work, ['ld', '-Ttext=0x%x' % at] + ['--defsym=%s=0x%x' % (n, v) for n, v in defsyms]
         + ['-o', e, o])
    _gnu(dev, work, ['objcopy', '-O', 'binary'] + [x for s in sections for x in ('-j', s)]
         + [e, b])
    with open(b, 'rb') as fh:
        return fh.read()


def check(ob, plan, mod_path, core_path, stock_path, work):
    """The converted mod, linked with the core, against octabam's account -> [lines]."""
    st, dev, rel = formats.load(stock_path)
    image = formats.main_image(st, dev)
    m = ob.modules[plan['name']]
    mod, core = elemod.load_any(mod_path), elemod.load_any(core_path)
    ln = link.link([core, mod], image)
    run_off = ln.layout['run_load'] - dev.main_load
    ddr0 = ln.layout['ddr'][0]

    def ram(a, n):
        o = run_off + a - ddr0
        return ln.image[o:o + n]

    def img(a, n):
        o = a - dev.main_load
        return ln.image[o:o + n]

    def sym(nm):
        k = '%s:%s' % (plan['id'], nm)
        if k not in ln.map:
            raise CheckError('%s is not in the link map' % nm)
        return ln.map[k]

    base = ln.map['arena_base']
    lines = []
    for i, c in enumerate(m.cf_patches):
        a = sym(plan['caves'][i]['sym'])
        gb = _gnu_link(ob, dev, c.source, a, c.cpu, c.defsyms, os.path.join(work, 'cave%d' % i))
        ref = (ob.call(c.reference, a) if c.reference is not None
               else c.pinned if c.emit is None else ob.call(c.emit, a)[0])
        if ref and gb != ref:
            raise CheckError('"%s": its source at 0x%08x no longer matches the bytes the '
                             'manifest ratifies' % (c.label, a))
        want = bytearray(gb)
        hits = [o for o in range(0, len(gb) - 3, 2) if _u32(gb, o) == ARENA_STOCK_BASE]
        if len(hits) != c.pool_base_literals:
            raise CheckError('"%s": %d arena-base literals, the manifest declares %d'
                             % (c.label, len(hits), c.pool_base_literals))
        for o in hits:
            want[o:o + 4] = base.to_bytes(4, 'big')
        if ram(a, len(want)) != bytes(want):
            raise CheckError('"%s" at 0x%08x differs from octabam\'s link at that address'
                             % (c.label, a))
        if c.hook_addr is not None:
            n = len(c.hook_stock)
            if img(c.hook_addr, n) != OPS['jsr'] + a.to_bytes(4, 'big') + NOP * ((n - 6) // 2):
                raise CheckError('"%s": the hook at 0x%08x' % (c.label, c.hook_addr))
        if c.emit is not None:
            for pa, _exp, w in ob.call(c.emit, a)[1]:
                if img(pa, len(w)) != w:
                    raise CheckError('"%s": the poke at 0x%08x' % (c.label, pa))
        lines.append('cave "%s": %d bytes at 0x%08x, as octabam links it%s%s'
                     % (c.label, len(gb), a, ' and as ratified' if ref else '',
                        ', %d arena-base literal(s) moved' % len(hits) if hits else ''))
    for d in m.detours:
        t = d.target if d.target is not None else sym(d.symbol)
        n = d.pad_to or 6
        op = OPS.get(d.kind) or d.expect[:2]
        if img(d.site, n) != op + t.to_bytes(4, 'big') + NOP * ((n - 6) // 2):
            raise CheckError('the detour at 0x%08x' % d.site)
        extra = _boundary(image, d.site, n, dev) - n if d.kind == 'jmp' else 0
        if img(d.site + n, extra) != NOP * (extra // 2):
            raise CheckError('the padding after the detour at 0x%08x' % d.site)
    for r in m.symbol_refs:
        if _u32(img(r.addr, 4), 0) != sym(r.symbol) + r.addend:
            raise CheckError('the symbol ref at 0x%08x' % r.addr)
    for i, t in enumerate(m.tables):
        at = sym(plan['tables'][i]['sym'])
        want = b''.join(_u32(image, t.old - dev.main_load + 4 * k).to_bytes(4, 'big')
                        for k in range(t.count))
        want += b''.join(sym(s).to_bytes(4, 'big') for _u, s in t.symbols)
        if ram(at, len(want)) != want:
            raise CheckError('table %s' % t.label)
        for ra, _v in t.refs:
            if _u32(img(ra, 4), 0) != at:
                raise CheckError('table %s: the ref at 0x%08x' % (t.label, ra))
    for p in m.pokes:
        if img(p.addr, len(p.write)) != p.write:
            raise CheckError('the poke at 0x%08x' % p.addr)
    if m.detours or m.symbol_refs or m.tables or m.pokes:
        lines.append('%d detours, %d symbol refs, %d tables, %d pokes: as octabam writes them'
                     % (len(m.detours), len(m.symbol_refs), len(m.tables), len(m.pokes)))

    # the whole of the mod's RAM against GNU ld's link of the same object
    if not mod.size('.run'):
        return lines
    obj = os.path.join(os.path.dirname(mod_path), plan['id'] + '.work', plan['id'] + '.o')
    lay = ln.layout['sections']
    run_at, bss_at = lay.get('%s .run' % plan['id']), lay.get('%s .bss' % plan['id'], 0)
    os.makedirs(work, exist_ok=True)
    lds = os.path.join(work, 'check.ld')
    with open(lds, 'w') as fh:
        fh.write('SECTIONS\n{\n    .run 0x%x : { *(.run) }\n    .bss 0x%x (NOLOAD) : '
                 '{ *(.bss) }\n}\n' % (run_at, bss_at))
    und = {n: ln.map.get(n, ln.map.get('core_zero')) for n in mod.imports}
    elf, raw = os.path.join(work, 'check.elf'), os.path.join(work, 'check.bin')
    _gnu(dev, work, ['ld', '-T', lds] + ['--defsym=%s=0x%x' % kv for kv in sorted(und.items())]
         + ['-o', elf, obj])
    _gnu(dev, work, ['objcopy', '-O', 'binary', '-j', '.run', elf, raw])
    with open(raw, 'rb') as fh:
        gl = fh.read()
    if ram(run_at, len(gl)) != gl or len(gl) != mod.size('.run'):
        raise CheckError('its RAM differs from GNU ld\'s link of the same object')
    lines.append('.run: %d bytes at 0x%08x, as GNU ld links them' % (len(gl), run_at))

    for u in m.linked:
        if not u.dram and u.cpu != '54455':
            # octabam assembles a unit placed in the OS image for u.cpu; the SDK, for the chip
            ws = os.path.join(work, 'isa_' + _slug(u.label))
            os.makedirs(ws, exist_ok=True)
            mdir = os.path.join(os.path.dirname(mod_path), plan['id'])
            got = {}
            for cpu in (u.cpu, '54455'):
                o = os.path.join(ws, cpu + '.o')
                _gnu(dev, ws, ['as', '-mcpu=%s' % cpu, '-I', mdir, '-o', o, u.source],
                     cwd=ob.root)
                for sec in ('.text', '.data'):
                    b = os.path.join(ws, cpu + sec + '.bin')
                    _gnu(dev, ws, ['objcopy', '-O', 'binary', '-j', sec, o, b])
                    with open(b, 'rb') as fh:
                        got[(cpu, sec)] = fh.read()
            if any(got[(u.cpu, s)] != got[('54455', s)] for s in ('.text', '.data')):
                raise CheckError('unit "%s" assembles differently for %s and for the chip (54455)'
                                 % (u.label, u.cpu))
            lines.append('unit "%s": the same bytes for %s as for the chip' % (u.label, u.cpu))
        if u.reference is None:
            continue
        ra, rsha = u.reference
        rb = _gnu_link(ob, dev, u.source, ra, '54455' if u.dram else u.cpu, (),
                       os.path.join(work, 'ref_' + _slug(u.label)), sections=())
        if elemod.sha(rb) != rsha:
            raise CheckError('unit "%s" linked alone at 0x%08x is sha256 %s..., not its '
                             'author\'s %s...: the source drifted, or these binutils encode it '
                             'differently (octabam\'s own build refuses it the same way)'
                             % (u.label, ra, elemod.sha(rb)[:16], rsha[:16]))
        lines.append('unit "%s": its source links to the author\'s reference' % u.label)
    return lines


# ---- the command ----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.sdk.octabam',
                                 description=__doc__.split('\n')[0])
    ap.add_argument('--octabam', required=True, help='an octabam checkout')
    ap.add_argument('--stock', default=os.environ.get('ELEKLOADER_OT_SYX'),
                    help='the stock OCTATRACK_OS1.40C.syx (default: $ELEKLOADER_OT_SYX)')
    ap.add_argument('--module', action='append', help='a module directory name (default: all)')
    ap.add_argument('--out', default='octabam-mods', help='where the folders and .elemod go')
    ap.add_argument('--core', help='the Octatrack core .elemod (default: build mods/core-ot)')
    ap.add_argument('--no-check', action='store_true', help='build, but skip the check')
    a = ap.parse_args(argv)
    if not a.stock:
        ap.error('--stock is required (or set ELEKLOADER_OT_SYX)')
    st, dev, rel = formats.load(a.stock)
    if dev.key != DEVICE:
        ap.error('the stock file is for the %s, not the Octatrack' % dev.name)
    image = formats.main_image(st, dev)
    ob = Octabam(a.octabam)
    names = a.module or sorted(set(ob.modules) | set(ob.broken))
    for n in names:
        if n not in ob.modules and n not in ob.broken:
            ap.error('no module %s in %s' % (n, ob.root))
    os.makedirs(a.out, exist_ok=True)
    core = a.core
    if not core and not a.no_check:
        if not os.path.isdir(CORE_DIR):
            ap.error('no mods/core-ot here: give --core')
        core, _m = sdkbuild.build(CORE_DIR, a.stock, os.path.join(a.out, 'core'))
    print('octabam %s: %d modules' % (ob.commit, len(ob.modules)))
    failed = 0
    for n in names:
        if n in ob.broken:
            print('REFUSED   %-30s its manifest does not load (%s)' % (n, ob.broken[n]))
            continue
        try:
            plan = convert(ob, n, image, dev)
        except Refused as e:
            print('REFUSED   %-30s %s' % (n, e))
            continue
        d = write(ob, plan, a.out)
        try:
            path, mod = sdkbuild.build(d, a.stock, a.out)
            lines = [] if a.no_check else check(ob, plan, path, core, a.stock,
                                                os.path.join(a.out, plan['id'] + '.check'))
        except (sdkbuild.BuildError, CheckError, elemod.ModError, OSError) as e:
            print('FAILED    %-30s %s' % (n, str(e).strip().replace('\n', '\n          ')))
            failed += 1
            continue
        print('CONVERTED %-30s %s: .run %d, .bss %d bytes, %d sites'
              % (n, os.path.basename(path), mod.size('.run'), mod.size('.bss'), len(mod.sites)))
        for x in lines + plan['notes']:
            print('          - %s' % x)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
