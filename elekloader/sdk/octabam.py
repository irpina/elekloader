# SPDX-License-Identifier: GPL-2.0-or-later
"""sambanks/octabam's ColdFire modules -> linkable Octatrack mods (format 2).

    python -m elekloader.sdk.octabam --octabam PATH --stock OCTATRACK_OS1.40C.syx
                                     [--module NAME ...] [--remix NAME ...] [--reference IMAGE]
                                     --out DIR [--core CORE.elemod]

octabam (MIT) declares each module in modules/<name>/manifest.py, in the
vocabulary of its tools/remix/schema.py. This reads the manifests of a
checkout and, for each module, writes an SDK mod folder: mod.json, the
module's sources, and generated glue. It builds each folder with sdk.build,
links the result with the Octatrack's core (mods/core-ot), and checks it
against octabam's own account of the bytes (below).

Placement differs from octabam's for floating code, on purpose. A floating
cave or unit goes in the core's RAM reserve (`.run`), which is the reserve
octabam's own DRAM units use. That includes the caves octabam floats in the
zero runs inside the OS image, so such a cave is the same code at another
address. Pinned code stays where octabam pins it (sdk.build's `fixed`,
inside the device's free image areas). A module converts when it uses only
these:

| octabam (schema.py) | here |
|---|---|
| CavePatch, floating, with a source | the source in .run, under a glue label; its hook a `jsr` site |
| CavePatch, pinned, with a source | `fixed` code at its address, the label its first byte |
| CavePatch, pinned, writing no bytes (no source) | its pokes only |
| CavePatch.emit's pokes | sites; a poke that holds a floating cave's address is a jsr/jmp/ptr site against it |
| CavePatch.defsyms | the assembler's --defsym, with the manifest's values |
| CavePatch.pool_base_literals | the literal becomes the core's `arena_base` (the moved base) |
| Linked, dram or floating | .run; an `include` is generated for a remix of this module alone |
| Linked, pinned | `fixed` code at its address |
| Detour jmp/jsr (pad_to), lea, a stock target | jmp/jsr sites, keep2, a code `bytes` site |
| SymbolRef | a ptr site, with its addend |
| TableGrow | the grown table in .run, a ptr site at each ref |
| Poke | a bytes site |
| Poke inside data the device marks `relocatable` (in a protected range) | a copy of that data in .run with the poke applied; a ptr site at each of the device's references to it, so the protected bytes stay stock |
| Override (a bridge) | one mod that carries the modules it bridges; their detours it stands in for are left out, and it conflicts with them alone |
| requires | requires, by the converted ids |
| category | the mod's category, as octabam titles it (CATEGORY_TITLE: "MIDI and USB", ...) |
| Claims (part window, SRAM) | named resources, one per 16-byte block, so mods whose claims overlap are refused together |

Anything else refuses the module, with the reason:
- DSP code or an FX menu entry (only ColdFire-only modules convert);
- a cave or unit pinned outside the device's free image areas;
- a write into a protected range, other than a poke wholly inside relocatable data;
- a cave with no source that writes bytes of its own;
- a formatter registered on another module's knob (a DSP module's);
- a loader-appended Runtime (Octakit), an ArenaReserve, or a bridge over a
  runtime's writes;
- needing (requires, or bridging) a module that does not convert;
- serving DSP modules only (SERVES_DSP: MODE DEFAULTS, RIG HOSTS, TEMPO BUS).

**Remixes** (`--remix`). An octabam remix converts as one mod: its modules (not the stock
effects it lists), each converted as above, with the generated includes built for all of
them. A module whose DSP code is reached only by its hooks into stock DSP code (no FX menu
entry, no knobs: USB AUDIO IN's RX inject) converts here, though not alone. Everything else
the remix's build writes in the OS image comes from octabam's own build of it
(tools/build/build_bus.py, run in the checkout, or `--reference`): every byte it changes
outside this mod's sites and the core's becomes a data site. For USB AUDIO IN that is the
inject in a stock effect's DSP code, its hook, the effect's dispatch pointed at the null
stub, and the FX1/FX2 choosers without the effect. The check then requires the linked OS
image to equal that build in every byte, but for the address operands of our placed code and
data served from a copy.

A unit's generated `include` is built for the modules this mod carries.
Where it would change with another module that converts, the mod conflicts
with that one; where it would change only with modules that do not, the
notes say so.

Where octabam links one module's symbol into another at build time (a
CavePatch.defsym another unit exports, e.g. CC MAP's CC_MODEDEF1 from MODE
DEFAULTS), the converted mod keeps the manifest's own value.

**The check.** With every module linked alone with the core:
- each cave's bytes, in RAM or in the image, must equal its source
  assembled and linked by GNU ld at that address, as octabam's build does. The arena-base literals
  are counted and moved as octabam does.
- Those bytes must equal the manifest's ratified ones (`reference(addr)`,
  or `pinned`), as octabam requires.
- Every site must hold what octabam would write, computed from the final
  addresses (hooks, emit's pokes, detours, symbol refs, pokes, tables).
- The whole of the mod's RAM and its fixed code must equal GNU ld's link of
  the same object at the same addresses.
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
        self.modules, self.broken, self._ok = {}, {}, {}
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

    def convertible(self, name):
        if name not in self._ok:
            self._ok[name] = name in self.modules and refusal(self, name) is None
        return self._ok[name]


# ---- what converts --------------------------------------------------------------------

# Modules whose only purpose is to serve DSP modules, which do not convert. Their manifests
# do not say so in a form this can read, so it is written here, from their own docs
# (octabam 363861e). Converted alone they would be inert (MODE DEFAULTS), or change the
# unit's behaviour for engines it does not have (RIG HOSTS, TEMPO BUS).
SERVES_DSP = {
    'mode-defaults': 're-defaults the knobs around a DSP engine\'s MODE select',
    'rig-hosts': 'gives every new part BusDelay, BusVerb and SEND as its FX2',
    'tempo-bus': 'turns the TEMPO window into a page of BusDelay\'s and BusVerb\'s knobs',
}


def hooked_dsp(m):
    """Is the module's DSP code reached only by its hooks into stock DSP code (USB AUDIO IN's
    RX inject), with no FX menu entry and no knobs? A remix carries such code (below)."""
    return (m.dsp is not None and m.menu is None and not m.params
            and bool(getattr(m.dsp, 'hooks', ())))


def refusal(ob, name, _seen=(), hooks=False):
    """Why module `name` does not convert, or None. With `hooks`, as part of a remix:
    DSP code reached only by its hooks converts too (the remix's build places it)."""
    m = ob.modules[name]
    if name in SERVES_DSP:
        return ('it serves DSP modules, which do not convert: it %s' % SERVES_DSP[name])
    dsp_ok = hooks and hooked_dsp(m)
    if not dsp_ok and (m.dsp is not None or m.menu is not None or m.params):
        return 'it has DSP code or an FX menu entry (only ColdFire-only modules convert)'
    for _dp, _dns, fns in os.walk(os.path.join(ob.root, 'modules', name)):
        if not dsp_ok and any(f.endswith('.asm') for f in fns):
            return ('it carries DSP56300 code (.asm), which its build uploads (only '
                    'ColdFire-only modules convert)')
    if m.runtime is not None:
        return 'it is a loader-appended runtime (%s)' % m.runtime.recipe
    if m.arena is not None:
        return 'it reserves arena pages of its own'
    for c in m.cf_patches:
        if not c.source and (c.cave_addr is None or c.pinned or c.hook_addr is not None):
            return 'its cave "%s" has no source' % c.label
        if c.registers_formatter is not None:
            return ('its cave "%s" draws a knob of %s (a formatter registration), a DSP module'
                    % (c.label, c.registers_formatter.module))
    for o in m.overrides:
        if o.write is not None:
            return ('it bridges %s\'s runtime write %s, and runtimes do not convert'
                    % (o.module, o.write))
    for k in list(m.requires) + [o.module for o in m.overrides]:
        n = ob.by_key.get(k)
        if n is None:
            return 'it needs %s, which this checkout does not have' % k
        if n in _seen or n == name:
            continue
        why = refusal(ob, n, _seen + (name,), hooks)
        if why:
            return 'it needs %s, which does not convert: %s' % (k, why)
    return None


def members(ob, name):
    """The modules one converted mod carries: `name`, and every module whose hooks it
    stands in for (schema.Override), since a bridge means nothing without them."""
    out = [name]
    for n in out:
        for o in ob.modules[n].overrides:
            k = ob.by_key[o.module]
            if k not in out:
                out.append(k)
    return out


def category(m):
    """The module's category as octabam titles it for people (schema.CATEGORY_TITLE:
    "MIDI and USB", "Fixes", ...), or its value where the checkout has no titles."""
    if m.category is None:
        return ''
    v = getattr(m.category, 'value', '')
    try:
        from remix.schema import CATEGORY_TITLE
    except ImportError:
        return v
    return {getattr(k, 'value', k): t for k, t in CATEGORY_TITLE.items()}.get(v, v)


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


def _relocatable(dev, addr, n):
    """The device's relocatable data (lo, n, refs, what) that holds addr..addr+n whole, or
    None."""
    for r in dev.relocatable:
        if r[0] <= addr and addr + n <= r[0] + r[1]:
            return r
    return None


def _changed(a, b):
    """The offsets where a and b differ, over a's length."""
    out = []
    for o in range(0, len(a), 4096):
        x, y = a[o:o + 4096], b[o:o + 4096]
        if x != y:
            out += [o + i for i in range(len(x)) if x[i] != y[i]]
    return out


_CORE = []


def _core_spans():
    """The Octatrack core's sites (mods/core-ot): [(lo, hi)]."""
    if not _CORE:
        with open(os.path.join(CORE_DIR, 'mod.json')) as fh:
            for s in json.load(fh)['sites']:
                a = int(s['addr'], 16)
                _CORE.append((a, a + len(s['stock']) // 2))
    return list(_CORE)


def _locator(ob, image, dev):
    """-> where(lo, hi): what a span of the OS image is, for the notes: a DSP payload's
    words (octabam's tools/build/dsp_modmap reads their load map), a free run, or code."""
    tb = os.path.join(ob.root, 'tools', 'build')
    if tb not in sys.path:
        sys.path.insert(0, tb)
    try:
        import dsp_modmap
        recs = [(tag, sp, addr, cnt, va + off)
                for tag, va, ln in dsp_modmap.PAYLOADS
                for sp, addr, cnt, off in dsp_modmap.modules(image, va, ln)[0]]
    except Exception:                       # the notes only: say less, not fail
        recs = []

    def where(lo, hi):
        for tag, sp, addr, cnt, d in recs:
            if d <= lo < d + cnt * 3:
                w0, w1 = (lo - d) // 3, (min(hi, d + cnt * 3) - 1 - d) // 3
                sp_ = 'PXY?'[sp] if sp < 4 else '?'
                return ('DSP payload %s %s:0x%05x' % (tag, sp_, addr + w0)
                        + ('-0x%05x' % (addr + w1) if w1 > w0 else ''))
        if any(a <= lo < b for a, b in dev.image_free):
            return 'the image\'s free run'
        return 'the OS'
    return where


def stock_raw(ob, image):
    """The checkout's out/raw/section_3_MAIN_OS.bin, the stock image octabam's tools read
    (`make recon` writes it): written from this stock OS if missing, refused if it differs."""
    raw = os.path.join(ob.root, 'out', 'raw', 'section_3_MAIN_OS.bin')
    if os.path.exists(raw):
        with open(raw, 'rb') as fh:
            if fh.read() != image:
                raise Refused('the checkout\'s out/raw/section_3_MAIN_OS.bin is not this '
                              'stock OS')
    else:
        os.makedirs(os.path.dirname(raw), exist_ok=True)
        with open(raw, 'wb') as fh:
            fh.write(image)


def load_remix(ob, name):
    """octabam's remix `name` -> {'name', 'doc', 'modules' (keys), 'stock' (the stock
    effects' keys), 'harvested' (stock effects with DSP code on neither FX menu)}. Its
    stock tables read the checkout's stock image (stock_raw)."""
    from remix import registry, stock     # octabam's tools/remix
    try:                                    # its own code: report a failure as a refusal
        r = ob.call(registry.remix, name)
    except (Exception, SystemExit) as e:
        raise Refused('no remix %s in the checkout (%s)' % (name, e))
    try:
        allm = ob.call(registry.modules)
        spans = ob.call(stock.p_spans, 'A')
    except (Exception, SystemExit) as e:
        raise Refused('octabam\'s stock tables do not load (%s)' % e)
    st = frozenset(k for k, m in allm.items() if getattr(m, 'is_stock', False))
    listed = set(r.modules) | set(getattr(r, 'fx1', None) or ())
    return {'name': r.name, 'doc': r.doc, 'modules': tuple(r.modules), 'stock': st,
            'harvested': sorted(k for k in st if k not in listed and k in spans)}


def build_reference(ob, name, image):
    """octabam's own build of remix `name` (tools/build/build_bus.py, in the checkout, which
    writes its out/mainos_bus.bin) -> that main OS image. It needs the checkout's
    out/raw/section_3_MAIN_OS.bin to be this stock OS (stock_raw), its dsp_asm (`make
    setup` builds it), and m68k-elf binutils on the PATH."""
    stock_raw(ob, image)
    if not os.path.isfile(os.path.join(ob.root, 'vendor', 'dsp56300', 'build', 'source',
                                       'dsp_host', 'dsp_asm')):
        raise Refused('octabam\'s build needs its DSP assembler (vendor/dsp56300 .../dsp_asm: '
                      '`make setup` in the checkout)')
    if not shutil.which('m68k-elf-as'):
        raise Refused('octabam\'s build needs the m68k-elf binutils on the PATH')
    out = os.path.join(ob.root, 'out', 'mainos_bus.bin')
    if os.path.exists(out):
        os.remove(out)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'SYSTEMROOT') if k in os.environ}
    env['REMIX'] = name                     # and none of build_bus's other switches
    r = subprocess.run([sys.executable, os.path.join('tools', 'build', 'build_bus.py')],
                       cwd=ob.root, env=env, capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        raise Refused('octabam\'s build of %s failed:\n%s' % (name, (r.stdout + r.stderr)[-2000:]))
    with open(out, 'rb') as fh:
        return fh.read()


INCLUDE = re.compile(rb'^\s*\.include\s+"([^"]+)"', re.M)


def _collect(ob, rel, files, pool, seen):
    """`rel` and every file it .includes, at their repo paths -> the paths, in order."""
    if rel in seen:
        return []
    seen.add(rel)
    p = os.path.join(ob.root, *rel.split('/'))
    if not os.path.isfile(p):
        raise Refused('its source %s is not in the checkout' % rel)
    with open(p, 'rb') as fh:
        data = fh.read()
    if re.search(rb'^\s*\.incbin\b', data, re.M):
        raise Refused('%s includes binary data (.incbin)' % rel)
    if pool:
        data = re.sub(rb'(?i)\b0x40a955e0\b', b'arena_base', data)
    files.setdefault(rel, data)
    out = [rel]
    for inc in INCLUDE.findall(data):
        if inc != b'remix.inc':             # generated per remix: see convert()
            out += _collect(ob, inc.decode(), files, pool, seen)
    return out


def convert(ob, name, image, dev, rx=None):
    """-> a plan: {'id', 'name', 'members', 'json' (mod.json), 'files' ({relpath: bytes}),
    'caves', 'tables', 'skip', 'notes', 'relocs', 'remix'}. Raises Refused.

    With `rx` (load_remix's dict, with 'ref', octabam's own build of the remix): one mod
    for the remix `name`, carrying its modules, and as data sites every other byte that
    build writes in the OS image (remix_sites)."""
    if rx is None:
        why = refusal(ob, name)
        if why:
            raise Refused(why)
        mid, names_ = mod_id(name), members(ob, name)
    else:
        mid, names_ = mod_id(name), []
        for k in rx['modules']:
            if k in rx['stock']:
                continue
            n = ob.by_key.get(k)
            if n is None:
                raise Refused('it needs %s, which this checkout does not have' % k)
            why = refusal(ob, n, hooks=True)
            if why:
                raise Refused('%s: %s' % (n, why))
            names_ += [x for x in members(ob, n) if x not in names_]
        if not names_:
            raise Refused('it carries no module of octabam\'s, only stock effects')
    mods = [ob.modules[n] for n in names_]
    remix = {mm.key: mm for mm in mods}
    skip = {(o.site, o.module) for mm in mods for o in mm.overrides}     # detours stood in for
    labels = {u.label for mm in mods for u in mm.linked}
    notes, sites, sources, files = [], [], [], {}
    defsym, caves, tables, names, fixed = {}, [], [], [], []
    relocs = {}                             # relocatable data's address -> its served copy
    conflicts = [mod_id(n) for n in (names_[1:] if rx is None else names_)]
    requires = ['core']
    if rx is not None:
        notes.append('it carries the remix\'s modules: %s' % ', '.join(names_))
    elif names_[1:]:
        notes.append('it carries %s, whose hooks it stands in for (octabam\'s bridge), so '
                     'it takes their place' % ', '.join(n for n in names_[1:]))

    def site(addr, stock, **kw):
        for lo, hi, what in dev.protected:
            if addr < hi and lo < addr + len(stock):
                raise Refused('it writes 0x%08x-0x%08x, inside %s (0x%08x-0x%08x), which '
                              'elekloader protects' % (addr, addr + len(stock), what, lo, hi))
        s = {'addr': '0x%08x' % addr, 'stock': stock.hex()}
        s.update(kw)
        sites.append(s)

    def place(what, at):
        if not any(a <= at < b for a, b in dev.image_free):
            raise Refused('%s is pinned at 0x%08x, outside the free areas of the %s image'
                          % (what, at, dev.name))

    included = {}                           # a file -> the generated include it now names
    for n, m in zip(names_, mods):
        ms = _slug(n)
        pool = any(c.pool_base_literals for c in m.cf_patches)
        closure = {}
        for src in [c.source for c in m.cf_patches if c.source] + [u.source for u in m.linked]:
            closure[src] = _collect(ob, src, files, pool, set())
        for k in m.requires:
            if ob.by_key[k] not in names_ and mod_id(ob.by_key[k]) not in requires:
                requires.append(mod_id(ob.by_key[k]))

        # caves: floating ones in .run under a label, pinned ones fixed; hooks; emit's pokes
        for c in m.cf_patches:
            sym = 'ob_%s_%s' % (ms, _slug(c.label))
            if not c.source:                # writes nothing of its own: only its pokes
                sym = None
            elif c.cave_addr is not None:
                place('its cave "%s"' % c.label, c.cave_addr)
                fixed.append({'source': c.source, 'addr': '0x%08x' % c.cave_addr,
                              'symbol': sym})
            else:
                glue = 'glue/%s.s' % sym
                files[glue] = ('| generated by elekloader.sdk.octabam from octabam %s: %s, "%s"\n'
                               '        .text\n        .globl  %s\n%s:\n        .include "%s"\n'
                               % (ob.commit, m.key, c.label, sym, sym, c.source)).encode()
                sources.append(glue)
            for dn, v in c.defsyms:
                if defsym.get(dn, v) != v:
                    raise Refused('two caves give %s different values' % dn)
                defsym[dn] = v
                notes.append('%s = 0x%08x, the manifest\'s value (octabam may link another '
                             'module\'s symbol there)' % (dn, v))
            if c.hook_addr is not None:
                if _stock(image, dev, c.hook_addr, len(c.hook_stock)) != c.hook_stock:
                    raise Refused('the hook site 0x%08x of "%s" is not stock'
                                  % (c.hook_addr, c.label))
                site(c.hook_addr, c.hook_stock, op='jsr', target=sym)
            if c.emit is not None and c.cave_addr is not None:
                b, pk = ob.call(c.emit, c.cave_addr)
                if b:
                    raise Refused('the cave "%s" emits hand-assembled bytes (octabam\'s legacy '
                                  'path)' % c.label)
                for pa, exp, w in pk:
                    if _stock(image, dev, pa, len(exp)) != exp:
                        raise Refused('the poke at 0x%08x is not stock' % pa)
                    site(pa, _stock(image, dev, pa, len(w)), op='bytes', new=w.hex())
            elif c.emit is not None:
                (b1, p1), (b2, p2) = [ob.call(c.emit, a) for a in EMIT_AT]
                if b1 or b2:
                    raise Refused('the cave "%s" emits hand-assembled bytes (octabam\'s legacy '
                                  'path)' % c.label)
                if len(p1) != len(p2):
                    raise Refused('the cave "%s" emits different pokes at different addresses'
                                  % c.label)
                for (pa, exp, w1), (pa2, exp2, w2) in zip(p1, p2):
                    if (pa, exp) != (pa2, exp2) or len(w1) != len(w2):
                        raise Refused('the cave "%s" emits different pokes at different '
                                      'addresses' % c.label)
                    if _stock(image, dev, pa, len(exp)) != exp:
                        raise Refused('the poke at 0x%08x is not stock' % pa)
                    stock = _stock(image, dev, pa, len(w1))
                    if w1 == w2:
                        site(pa, stock, op='bytes', new=w1.hex())
                        continue
                    # the one word that moves with the cave: its offset in the poke, and in it
                    at = [i for i in range(0, len(w1) - 3, 2)
                          if w1[:i] == w2[:i] and w1[i + 4:] == w2[i + 4:]
                          and _u32(w1, i) - EMIT_AT[0] == _u32(w2, i) - EMIT_AT[1]]
                    if at:
                        i, d = at[0], _u32(w1, at[0]) - EMIT_AT[0]
                        if i == 0 and len(w1) == 4:
                            site(pa, stock, op='ptr', target=sym, addend=d)
                            continue
                        if i == 2 and w1[:2] in OPS.values() \
                                and w1[6:] == NOP * ((len(w1) - 6) // 2):
                            site(pa, stock, op='jsr' if w1[:2] == OPS['jsr'] else 'jmp',
                                 target=sym, addend=d)
                            continue
                        if i == 2 and len(w1) == 6 and w1[:2] == stock[:2]:
                            site(pa, stock, op='keep2', target=sym, addend=d)
                            continue
                    raise Refused('the cave "%s" emits a poke at 0x%08x that elekloader cannot '
                                  'express (%s)' % (c.label, pa, w1.hex()))
            caves.append({'module': n, 'label': c.label, 'sym': sym})

        # linked units; a generated include, for this mod's modules, beside each that has one
        for u in m.linked:
            if not u.dram and u.cave_addr is not None:
                place('its unit "%s"' % u.label, u.cave_addr)
                fixed.append({'source': u.source, 'addr': '0x%08x' % u.cave_addr})
            else:
                sources.append(u.source)
            if u.include is None:
                continue
            try:
                text = ob.call(u.include, remix)
            except Exception as e:           # a manifest's own code: any failure refuses
                raise Refused('the generated include of "%s" needs more than this mod carries '
                              '(%s)' % (u.label, e))
            inc = 'glue/%s_%s.inc' % (ms, _slug(u.label))
            files[inc] = text.encode()
            for f in closure[u.source]:
                if b'"remix.inc"' in files[f]:
                    if included.get(f, inc) != inc:
                        raise Refused('%s is shared by two units with different generated '
                                      'includes' % f)
                    included[f] = inc
                    files[f] = files[f].replace(b'"remix.inc"', ('"%s"' % inc).encode())
            dsp, other = [], []
            for n2, m2 in ob.modules.items():
                if n2 in names_ or m2.key in remix:
                    continue
                try:
                    changed = ob.call(u.include, dict(remix, **{m2.key: m2})) != text
                except Exception:
                    changed = True
                if changed:
                    (other if ob.convertible(n2) else dsp).append(n2)
            if dsp:
                notes.append('"%s": its generated include would change with %s, which do not '
                             'convert; it is built as for a remix without them'
                             % (u.label, ', '.join(dsp)))
            for n2 in other:
                if mod_id(n2) not in conflicts:
                    conflicts.append(mod_id(n2))
            if other:
                notes.append('"%s": its generated include changes with %s, so it conflicts '
                             'with them' % (u.label, ', '.join(other)))

        for d in m.detours:
            if (d.site, m.key) in skip:
                continue                    # a bridge in this mod stands in for it
            if d.target is None and d.unit not in labels:
                raise Refused('a detour at 0x%08x names unit %s of another module'
                              % (d.site, d.unit))
            if _stock(image, dev, d.site, len(d.expect)) != d.expect:
                raise Refused('the detour site 0x%08x is not stock' % d.site)
            dn = d.pad_to or 6
            if d.kind == 'lea':
                if dn != 6 or d.target is not None:
                    raise Refused('a lea detour at 0x%08x that is not six bytes' % d.site)
                site(d.site, _stock(image, dev, d.site, 6), op='keep2', target=d.symbol)
                continue
            whole = _boundary(image, d.site, dn, dev)
            if whole != dn:
                if d.kind != 'jmp':
                    raise Refused('the jsr detour at 0x%08x ends inside an instruction' % d.site)
                notes.append('the jmp at 0x%08x is nop-padded to the next instruction (%d bytes, '
                             'not %d)' % (d.site, whole, dn))
                dn = whole
            stock = _stock(image, dev, d.site, dn)
            if d.target is not None:
                new = OPS[d.kind] + d.target.to_bytes(4, 'big') + NOP * ((dn - 6) // 2)
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
            files[glue] = ('| generated by elekloader.sdk.octabam from octabam %s: %s, table '
                           '"%s"\n        .text\n        .balign 4\n        .globl  %s\n%s:\n%s'
                           % (ob.commit, m.key, t.label, sym, sym, body)).encode()
            sources.append(glue)
            for ra, v in t.refs:
                stock = v.to_bytes(4, 'big')
                if _stock(image, dev, ra, 4) != stock:
                    raise Refused('the table ref at 0x%08x is not stock' % ra)
                site(ra, stock, op='ptr', target=sym)
            tables.append({'module': n, 'label': t.label, 'sym': sym})

        for p in m.pokes:
            if _stock(image, dev, p.addr, len(p.expect)) != p.expect:
                raise Refused('the poke at 0x%08x is not stock' % p.addr)
            rd = _relocatable(dev, p.addr, len(p.write))
            if rd is None:
                site(p.addr, _stock(image, dev, p.addr, len(p.write)), op='bytes',
                     new=p.write.hex())
                continue
            # the data is served from a copy with the poke applied; the image keeps its bytes
            r = relocs.setdefault(rd[0], {'data': rd, 'pokes': [],
                                          'bytes': bytearray(_stock(image, dev, rd[0], rd[1]))})
            o = p.addr - rd[0]
            for q, qw in r['pokes']:
                if q < p.addr + len(p.write) and p.addr < q + len(qw):
                    raise Refused('two pokes write %s at 0x%08x and 0x%08x' % (rd[3], q, p.addr))
            r['bytes'][o:o + len(p.write)] = p.write
            r['pokes'].append((p.addr, p.write))

        if m.claims is not None:
            # one name per 16-byte block claimed, so any two claims that overlap share a name
            for kind, spans in (('part-window', m.claims.part_window), ('sram', m.claims.sram)):
                for a, ln_, _what in spans:
                    names += ['octabam:%s@0x%x' % (kind, b) for b in range(a & ~15, a + ln_, 16)]

    for lo, r in sorted(relocs.items()):
        _lo, n, refs, what = r['data']
        sym = 'ob_%s_copy_%08x' % (_slug(name), lo)
        at = ', '.join('0x%08x' % a for a, _w in r['pokes'])
        files['glue/%s.s' % sym] = (
            '| generated by elekloader.sdk.octabam from octabam %s: %s (0x%08x, %d bytes, in a\n'
            '| range elekloader protects), served from here with the poke(s) at %s applied\n'
            '        .text\n'
            '        .balign 32                      | inside one 4 KB page, for the USB DMA\n'
            '        .globl  %s\n%s:\n        .byte   %s\n'
            % (ob.commit, what, lo, n, at, sym, sym,
               ', '.join('0x%02x' % b for b in r['bytes']))).encode()
        sources.append('glue/%s.s' % sym)
        for ref in refs:
            stock = lo.to_bytes(4, 'big')
            if _stock(image, dev, ref, 4) != stock:
                raise Refused('the reference to %s at 0x%08x is not stock' % (what, ref))
            site(ref, stock, op='ptr', target=sym)
        notes.append('the poke(s) at %s change %s, which lies inside a range elekloader '
                     'protects: the mod serves its own copy of it (%s), with them applied, '
                     'through %s, and leaves the protected bytes stock'
                     % (at, what, sym, ', '.join('0x%08x' % a for a in refs)))

    # a remix: every other byte octabam's build of it writes in the OS image, as data
    remix_sites = []
    if rx is not None:
        ref, base = rx['ref'], dev.main_load
        if len(ref) < len(image):
            raise Refused('octabam\'s build of %s is shorter than the stock OS' % name)
        taken = [(int(s['addr'], 16), int(s['addr'], 16) + len(s['stock']) // 2)
                 for s in sites] + _core_spans()
        moved = {a + i for r in relocs.values() for a, w in r['pokes'] for i in range(len(w))}

        def ours(a):
            return any(lo <= a < hi for lo, hi in taken)

        def guarded(a):
            return any(lo <= a < hi for lo, hi, _w in dev.protected)

        runs = []
        for i in _changed(image, ref):
            a = base + i
            if ours(a):
                continue                    # a site of ours or the core's: the check compares it
            if guarded(a):
                if a in moved:
                    continue                # served from a copy (above)
                raise Refused('octabam\'s build of %s writes 0x%08x, inside a range elekloader '
                              'protects' % (name, a))
            if runs and a - runs[-1][1] <= 3 and not any(
                    ours(x) or guarded(x) for x in range(runs[-1][1], a)):
                runs[-1][1] = a + 1
            else:
                runs.append([a, a + 1])
        where = _locator(ob, image, dev)
        for lo, hi in runs:
            site(lo, _stock(image, dev, lo, hi - lo), op='bytes',
                 new=ref[lo - base:hi - base].hex())
            remix_sites.append((lo, hi, where(lo, hi)))
        notes.append('octabam\'s build of %s also writes these, carried as data: %s'
                     % (name, '; '.join('%s (0x%08x, %d bytes)' % (w, lo, hi - lo)
                                        for lo, hi, w in remix_sites) or 'nothing'))
        if rx['harvested']:
            notes.append('it leaves %s off both FX menus, as the remix does: octabam\'s build '
                         'gives their DSP code space to the remix\'s DSP code'
                         % ', '.join(rx['harvested']))
        for n in names_:                    # for the reader: the build placed these words
            if hooked_dsp(ob.modules[n]):
                asm = ob.modules[n].dsp.asm
                with open(os.path.join(ob.root, *asm.split('/')), 'rb') as fh:
                    files['dsp/%s' % os.path.basename(asm)] = fh.read()
    if names:
        notes.append('its claims are named resources, one per 16-byte block: a mod that '
                     'claims any of the same blocks is refused beside it')

    m = mods[0]
    cat = category(m)
    carried = [mm.key for mm in mods[1:]]
    if rx is None:
        text = m.doc
        title = m.key + (' (with %s)' % ', '.join(carried) if carried else '')
        desc = '%s (octabam module %s%s, converted from %s)' % (
            m.doc, name, ''.join(', with ' + n for n in names_[1:]), ob.commit)
    else:
        text = rx['doc']
        title = name.replace('-', ' ').upper()      # as octabam names its modules: USB IO ...
        desc = '%s (octabam remix %s: %s; converted from %s)%s' % (
            rx['doc'], name, ', '.join(mm.key for mm in mods), ob.commit,
            ' It takes %s off both FX menus.' % ', '.join(rx['harvested'])
            if rx['harvested'] else '')
    doc = {
        'id': mid, 'version': ob.commit,
        'title': title,
        'description': desc,
        'category': cat,
        'author': ', '.join(dict.fromkeys(mm.author for mm in mods if mm.author)),
        'license': 'MIT', 'device': DEVICE, 'os': '1.40C',
        'sources': sources,
        'sites': sites,
        'requires': requires,
    }
    if fixed:
        doc['fixed'] = fixed
    if defsym:
        doc['defsym'] = {k: '0x%08x' % v for k, v in defsym.items()}
    if names:
        doc['resources'] = {'names': names}
    if conflicts:
        doc['conflicts'] = conflicts
    return {'id': mid, 'name': name, 'members': names_, 'json': doc, 'files': files,
            'caves': caves, 'tables': tables, 'skip': skip, 'notes': notes, 'doc': text,
            'relocs': [{'sym': 'ob_%s_copy_%08x' % (_slug(name), lo), 'data': r['data'],
                        'bytes': bytes(r['bytes']), 'pokes': r['pokes']}
                       for lo, r in sorted(relocs.items())],
            'remix': rx, 'remix_sites': remix_sites}


def write(ob, plan, out):
    """The plan as an SDK mod folder under `out`; -> its path."""
    d = os.path.join(out, plan['id'])
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
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
    mods = [ob.modules[n] for n in plan['members']]
    with open(os.path.join(d, 'README.md'), 'w', newline='\n') as fh:
        fh.write('# %s\n\n%s\n\nConverted by elekloader.sdk.octabam from sambanks/octabam %s, '
                 '%s (MIT, LICENSE.octabam). The sources are octabam\'s%s; glue/ is '
                 'generated.\n' % (plan['json']['title'], plan.get('doc', mods[0].doc), ob.commit,
                                   ', '.join('modules/' + n for n in plan['members']),
                                   ', with the arena-base literal named `arena_base`'
                                   if any(c.pool_base_literals for m in mods
                                          for c in m.cf_patches) else ''))
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


def _gnu_link(dev, root, src, at, cpu, defsyms, work, sections=('.text',), lookup=None):
    """octabam's _link: `src` (under `root`) assembled and linked at `at`; `sections` kept
    (all if empty). A symbol it leaves undefined is given by `lookup(name)`, as octabam
    gives a unit the symbols of those already placed."""
    os.makedirs(work, exist_ok=True)
    o, e, b = [os.path.join(work, x) for x in ('u.o', 'u.elf', 'u.bin')]
    _gnu(dev, work, ['as', '-mcpu=%s' % cpu, '-o', o, src], cwd=root)
    defs = dict(defsyms)
    if lookup is not None:
        for line in _gnu(dev, work, ['nm', '-u', o]).splitlines():
            n = line.split()[-1] if line.split() else ''
            if n and n not in defs and lookup(n) is not None:
                defs[n] = lookup(n)
    _gnu(dev, work, ['ld', '-Ttext=0x%x' % at] + ['--defsym=%s=0x%x' % kv for kv in defs.items()]
         + ['-o', e, o])
    _gnu(dev, work, ['objcopy', '-O', 'binary'] + [x for s in sections for x in ('-j', s)]
         + [e, b])
    with open(b, 'rb') as fh:
        return fh.read()


def check(ob, plan, mod_path, core_path, stock_path, work):
    """The converted mod, linked with the core, against octabam's account -> [lines]."""
    st, dev, rel = formats.load(stock_path)
    image = formats.main_image(st, dev)
    mod, core = elemod.load_any(mod_path), elemod.load_any(core_path)
    ln = link.link([core, mod], image)
    run_off = ln.layout['run_load'] - dev.main_load
    ddr0 = ln.layout['ddr'][0]
    mdir = os.path.join(os.path.dirname(mod_path), plan['id'])

    def ram(a, n):
        o = run_off + a - ddr0
        return ln.image[o:o + n]

    def img(a, n):
        o = a - dev.main_load
        return ln.image[o:o + n]

    def mem(a, n):                          # the reserve, or the image for fixed code
        return ram(a, n) if dev.ddr[0] <= a < dev.ddr[1] else img(a, n)

    def sym(nm):
        k = '%s:%s' % (plan['id'], nm)
        if k not in ln.map:
            raise CheckError('%s is not in the link map' % nm)
        return ln.map[k]

    def known(nm):                          # this mod's symbol, else another's export
        return ln.map.get('%s:%s' % (plan['id'], nm), ln.map.get(nm))

    base = ln.map['arena_base']
    lines = []
    for mn in plan['members']:
        m = ob.modules[mn]
        pc = [c for c in plan['caves'] if c['module'] == mn]
        for i, c in enumerate(m.cf_patches):
            if not c.source:
                pk = ob.call(c.emit, c.cave_addr)[1] if c.emit else ()
                for pa, _exp, w in pk:
                    if img(pa, len(w)) != w:
                        raise CheckError('"%s": the poke at 0x%08x' % (c.label, pa))
                lines.append('"%s": %d pokes, as octabam writes them' % (c.label, len(pk)))
                continue
            a = sym(pc[i]['sym'])
            if c.cave_addr is not None and a != c.cave_addr:
                raise CheckError('"%s" is at 0x%08x, not at 0x%08x' % (c.label, a, c.cave_addr))
            gb = _gnu_link(dev, ob.root, c.source, a, c.cpu, c.defsyms,
                           os.path.join(work, 'cave_%s_%d' % (_slug(mn), i)), lookup=known)
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
            if mem(a, len(want)) != bytes(want):
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
        dets = [d for d in m.detours if (d.site, m.key) not in plan['skip']]
        for d in dets:
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
        pt = [t for t in plan['tables'] if t['module'] == mn]
        for i, t in enumerate(m.tables):
            at = sym(pt[i]['sym'])
            want = b''.join(_u32(image, t.old - dev.main_load + 4 * k).to_bytes(4, 'big')
                            for k in range(t.count))
            want += b''.join(sym(s).to_bytes(4, 'big') for _u, s in t.symbols)
            if ram(at, len(want)) != want:
                raise CheckError('table %s' % t.label)
            for ra, _v in t.refs:
                if _u32(img(ra, 4), 0) != at:
                    raise CheckError('table %s: the ref at 0x%08x' % (t.label, ra))
        moved = {a for r in plan['relocs'] for a, _w in r['pokes']}
        for p in m.pokes:
            if p.addr not in moved and img(p.addr, len(p.write)) != p.write:
                raise CheckError('the poke at 0x%08x' % p.addr)
        if m.detours or m.symbol_refs or m.tables or m.pokes:
            nm = sum(p.addr in moved for p in m.pokes)
            lines.append('%s: %d detours, %d symbol refs, %d tables, %d pokes: as octabam '
                         'writes them%s%s' % (mn, len(dets), len(m.symbol_refs), len(m.tables),
                                              len(m.pokes) - nm,
                                              ' (%d stood in for)' % (len(m.detours) - len(dets))
                                              if len(dets) != len(m.detours) else '',
                                              '; %d poke(s) into a served copy (below)' % nm
                                              if nm else ''))

        for u in m.linked:
            if not u.dram and u.cpu != '54455':
                # octabam assembles a unit placed in the OS image for u.cpu; the SDK, for the chip
                ws = os.path.join(work, 'isa_' + _slug(u.label))
                os.makedirs(ws, exist_ok=True)
                got = {}
                for cpu in (u.cpu, '54455'):
                    o = os.path.join(ws, cpu + '.o')
                    _gnu(dev, ws, ['as', '-mcpu=%s' % cpu, '-o', o, u.source], cwd=mdir)
                    for sec in ('.text', '.data'):
                        b = os.path.join(ws, cpu + sec + '.bin')
                        _gnu(dev, ws, ['objcopy', '-O', 'binary', '-j', sec, o, b])
                        with open(b, 'rb') as fh:
                            got[(cpu, sec)] = fh.read()
                if any(got[(u.cpu, s)] != got[('54455', s)] for s in ('.text', '.data')):
                    raise CheckError('unit "%s" assembles differently for %s and for the chip '
                                     '(54455)' % (u.label, u.cpu))
                lines.append('unit "%s": the same bytes for %s as for the chip' % (u.label, u.cpu))
            if u.reference is None:
                continue
            ra, rsha = u.reference
            rb = _gnu_link(dev, mdir, u.source, ra, '54455' if u.dram else u.cpu, (),
                           os.path.join(work, 'ref_' + _slug(u.label)), sections=())
            if elemod.sha(rb) != rsha:
                raise CheckError('unit "%s" linked alone at 0x%08x is sha256 %s..., not its '
                                 'author\'s %s...: the source drifted, or these binutils encode '
                                 'it differently (octabam\'s own build refuses it the same way)'
                                 % (u.label, ra, elemod.sha(rb)[:16], rsha[:16]))
            lines.append('unit "%s": its source links to the author\'s reference' % u.label)

    # relocated data: the copy is the stock bytes with octabam's pokes, every reference
    # reaches it, and the protected original is untouched
    for r in plan['relocs']:
        lo, n, refs, what = r['data']
        want = bytearray(_stock(image, dev, lo, n))
        for a, w in r['pokes']:
            want[a - lo:a - lo + len(w)] = w
        a = sym(r['sym'])
        if bytes(want) != r['bytes'] or mem(a, n) != bytes(want):
            raise CheckError('the copy of %s at 0x%08x is not the stock bytes with octabam\'s '
                             'pokes' % (what, a))
        if a // 4096 != (a + n - 1) // 4096:
            raise CheckError('the copy of %s at 0x%08x crosses a 4 KB page' % (what, a))
        for ref in refs:
            if _u32(img(ref, 4), 0) != a:
                raise CheckError('the reference to %s at 0x%08x' % (what, ref))
        if img(lo, n) != _stock(image, dev, lo, n):
            raise CheckError('%s at 0x%08x is not stock in the image' % (what, lo))
        lines.append('%s: served from 0x%08x with the poke(s) at %s applied, through %s; the '
                     'protected original is stock'
                     % (what, a, ', '.join('0x%08x' % p for p, _w in r['pokes']),
                        ', '.join('0x%08x' % x for x in refs)))

    # a remix: the linked OS image is octabam's build of it, byte for byte, except where our
    # code's addresses go (the operands our relocations fill) and the descriptor it serves
    # from a copy instead of poking
    if plan.get('remix'):
        ref, base = plan['remix']['ref'], dev.main_load
        ours = set()
        for s in mod.sites:
            for o, _t, _tgt, _a in s.get('relocs', []):
                ours.update(range(s['addr'] + o, s['addr'] + o + 4))
        moved = {a + i for r in plan['relocs'] for a, w in r['pokes'] for i in range(len(w))}
        diff = [base + i for i in _changed(ln.image[:len(image)], ref)]
        bad = [a for a in diff if a not in ours and a not in moved]
        if bad:
            raise CheckError('the linked image differs from octabam\'s build of %s at %d bytes '
                             'that are not our code\'s addresses, the first at 0x%08x'
                             % (plan['name'], len(bad), bad[0]))
        wrote = _changed(image, ref)
        lines.append('the OS image equals octabam\'s build of %s: all %d bytes it changes, '
                     'but for %d address bytes of our placed code and %d of the descriptor '
                     'served from a copy' % (plan['name'], len(wrote),
                                             sum(a in ours for a in diff),
                                             sum(a in moved for a in diff)))

    # the whole of the mod's RAM and fixed code against GNU ld's link of the same object
    obj = os.path.join(os.path.dirname(mod_path), plan['id'] + '.work', plan['id'] + '.o')
    lay = ln.layout['sections']
    run_at, bss_at = lay.get('%s .run' % plan['id']), lay.get('%s .bss' % plan['id'], 0)
    blocks = [('.fixed.%d' % k, int(f['addr'], 16))
              for k, f in enumerate(plan['json'].get('fixed', []))]
    if run_at is not None:
        blocks.insert(0, ('.run', run_at))
    if blocks and os.path.exists(obj):
        os.makedirs(work, exist_ok=True)
        lds = os.path.join(work, 'check.ld')
        with open(lds, 'w') as fh:
            fh.write('SECTIONS\n{\n' + ''.join('    %s 0x%x : { *(%s) }\n' % (n, a, n)
                                                for n, a in blocks)
                     + '    .bss 0x%x (NOLOAD) : { *(.bss) }\n}\n' % bss_at)
        und = {n: ln.map.get(n, ln.map.get('core_zero')) for n in mod.imports}
        elf = os.path.join(work, 'check.elf')
        _gnu(dev, work, ['ld', '-T', lds] + ['--defsym=%s=0x%x' % kv for kv in sorted(und.items())]
             + ['-o', elf, obj])
        for n, a in blocks:
            raw = os.path.join(work, 'check%s.bin' % n)
            _gnu(dev, work, ['objcopy', '-O', 'binary', '-j', n, elf, raw])
            with open(raw, 'rb') as fh:
                gl = fh.read()
            if mem(a, len(gl)) != gl or (n == '.run' and len(gl) != mod.size('.run')):
                raise CheckError('%s differs from GNU ld\'s link of the same object' % n)
            lines.append('%s: %d bytes at 0x%08x, as GNU ld links them'
                         % ('.run' if n == '.run' else 'fixed code', len(gl), a))
    return lines


def bare_metal(dev):
    """Does the configured assembler resolve a reference to a global label of the same
    section itself, as octabam's bare-metal m68k-elf-as does? An assembler for a Linux
    target leaves it to the linker (a shared library may preempt a global), so `tst.b g`
    stays a relocated absolute operand, 2 bytes longer than the PC-relative form. None if
    it cannot be run."""
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        s, o = os.path.join(t, 'g.s'), os.path.join(t, 'g.o')
        with open(s, 'w') as fh:
            fh.write('        .text\n        .globl  g\n        tst.b   g\n        rts\n'
                     'g:      .byte   0\n')
        try:
            _gnu(dev, t, ['as', '-mcpu=54455', '-o', o, s])
            _gnu(dev, t, ['objcopy', '-O', 'binary', '-j', '.text', o, s + '.bin'])
        except (CheckError, OSError):
            return None
        with open(s + '.bin', 'rb') as fh:
            return len(fh.read()) == 7


def inside_checkout(path):
    """Is `path` inside the git checkout this elekloader runs from?"""
    repo = os.path.dirname(os.path.dirname(HERE))
    if not os.path.exists(os.path.join(repo, '.git')):     # installed, not a checkout
        return False
    path, repo = os.path.realpath(path), os.path.realpath(repo)
    return os.path.commonpath([path, repo]) == repo


# ---- the command ----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.sdk.octabam',
                                 description=__doc__.split('\n')[0])
    ap.add_argument('--octabam', required=True, help='an octabam checkout')
    ap.add_argument('--stock', default=os.environ.get('ELEKLOADER_OT_SYX'),
                    help='the stock OCTATRACK_OS1.40C.syx (default: $ELEKLOADER_OT_SYX)')
    ap.add_argument('--module', action='append', help='a module directory name (default: all, '
                    'unless --remix is given)')
    ap.add_argument('--remix', action='append',
                    help='an octabam remix to convert as one mod (e.g. usb-io-tracks-main-cue-ab): '
                         'its modules, and every other byte octabam\'s own build of it writes')
    ap.add_argument('--reference',
                    help='with one --remix: that build\'s out/mainos_bus.bin, instead of running '
                         'octabam\'s build here')
    ap.add_argument('--out', required=True,
                    help='where the folders and .elemod go: outside the elekloader checkout, '
                         'since they carry octabam\'s sources')
    ap.add_argument('--core', help='the Octatrack core .elemod (default: build mods/core-ot)')
    ap.add_argument('--no-check', action='store_true', help='build, but skip the check')
    a = ap.parse_args(argv)
    if inside_checkout(a.out):
        ap.error('%s is inside the elekloader checkout: converted mods carry octabam\'s '
                 'sources, so write them somewhere else' % a.out)
    if not a.stock:
        ap.error('--stock is required (or set ELEKLOADER_OT_SYX)')
    st, dev, rel = formats.load(a.stock)
    if dev.key != DEVICE:
        ap.error('the stock file is for the %s, not the Octatrack' % dev.name)
    if 'ELEKLOADER_CROSS' not in os.environ and shutil.which('m68k-elf-as'):
        os.environ['ELEKLOADER_CROSS'] = 'm68k-elf-'      # octabam's own toolchain
    image = formats.main_image(st, dev)
    ob = Octabam(a.octabam)
    if a.reference and len(a.remix or ()) != 1:
        ap.error('--reference goes with exactly one --remix')
    names = a.module or ([] if a.remix else sorted(set(ob.modules) | set(ob.broken)))
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
    print('assembler %sas (%s)' % (_tool(dev, ''), {True: 'bare metal, as octabam builds',
                                                      False: 'a Linux target',
                                                      None: 'not found'}[bare_metal(dev)]))
    if bare_metal(dev) is False:
        print('NOTE      this assembler leaves every reference to a global label to the linker, '
              'where octabam\'s bare-metal m68k-elf-as resolves it in a shorter PC-relative form. '
              'Such code assembles longer here: the same code, not the same bytes, and a unit '
              'whose author pinned its bytes (USB MIDI) fails its check. Install m68k-elf '
              'binutils (it is used when found), or set ELEKLOADER_CROSS=m68k-elf-.')
    failed = 0
    for n, is_remix in [(n, False) for n in names] + [(r, True) for r in a.remix or ()]:
        if n in ob.broken:
            print('REFUSED   %-30s its manifest does not load (%s)' % (n, ob.broken[n]))
            continue
        try:
            if is_remix:
                stock_raw(ob, image)
                rx = load_remix(ob, n)
                if a.reference:
                    with open(a.reference, 'rb') as fh:
                        rx['ref'] = fh.read()
                else:
                    rx['ref'] = build_reference(ob, n, image)
                plan = convert(ob, n, image, dev, rx)
            else:
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
