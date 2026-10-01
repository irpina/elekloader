# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a mod's sources into a format-2 .elemod (docs/ADAPTING.md).

    python -m elekloader.sdk.build MODDIR --stock Digitakt_OS1.53.syx [--out DIR]

MODDIR holds mod.json and the sources it names. Needs the device's cross
toolchain (for the Digitakt mk1: m68k-linux-gnu-as, -gcc and -ld; set
ELEKLOADER_CROSS to use another prefix). The stock .syx is needed to check
every site against the stock bytes, and to store the runs your code repeats
from the firmware as copies from the user's image.

mod.json:

    {"id": "my-mod", "version": "1.0", "title": "...", "description": "...",
     "category": "...", "author": "...",
     "device": "digitakt-mk1", "os": "1.53",          must match the stock file
     "sources": ["my.c", "glue.s"],                  assembled or compiled, then ld -r
     "fixed": [{"source", "addr", "symbol"}],         optional: code at a fixed address
     "defsym": {"NAME": 1},                           assembler --defsym, optional
     "cflags": [...],                                 extra compiler flags, optional
     "name_string": "my-mod",                         optional: str_name = "<it> <version>"
     "sites": [{"addr", "stock", "op", "target" | "new", "addend"}],
     "subscribe": [{"event": "ev_draw", "fn": "my_draw", "order": 60}],
     "collections": {"my_table": 8},                  tables you declare (entry size)
     "contribute": [{"to", "order", "data", "relocs", "claims"}],
     "weak": ["name"], "copied": [...],
     "resources": {"regions": [...], "names": [...]},
     "requires": ["core"], "conflicts": [...],
     "ports": {"1.54": {"defsym": {...}, "sites": [...]}}}   optional: other OS versions

A port builds the same mod for another release of the device: for that OS,
its keys replace the top level's (typically defsym, sites, cflags), and the
.elemod is named <id>-<version>-os<os>.elemod. The stock file says which
one is built.

A site's "op" says how its new bytes are made:

| op | new bytes |
|---|---|
| `jsr`, `jmp` | `4eb9` or `4ef9` + target's address, nop-padded to the stock length (6 bytes or more) |
| `keep2` | the stock opcode word + target's address (a `jsr.l` or `lea.l` whose operand you redirect) |
| `ptr` | target's address (4 bytes of data, e.g. a vtable entry) |
| `bytes` | `new`, given in hex; `"kind": "code"` if they are instructions |

With a target, `"addend": N` (optional) adds N bytes to its address.

A `fixed` source is placed at `addr` inside the stock image. It must be
inside one of the device's free image areas (`image_free`, zero in stock).
It may only have `.text`. `symbol` (optional) names its first byte. It
becomes an ordinary site over those zeros, and its labels become absolute
symbols, so nothing new is needed to load it.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

from .. import devices, elemod, formats, link
from ..mkmod import stock_parts
from . import elf

OPS = {'jsr': b'\x4e\xb9', 'jmp': b'\x4e\xf9'}
KEEP = ('.boot', '.run', '.fast', '.bss')
STOCK_MIN = 8
LD_SCRIPT = """/* One mod's objects -> one relocatable object (ld -r), in the four sections
   elekloader places: .boot (the core mod only), .run, .fast, .bss. */
SECTIONS
{
    .boot 0 : { *(.boot) }
    .run  0 : { *(.run) *(.text) *(.text.*) *(.data) *(.data.*) *(.rodata) *(.rodata.*) *(.sdata) *(.sdata.*) }
    .fast 0 : { *(.fast) }
    .bss  0 : { *(.bss) *(.bss.*) *(.sbss) *(.sbss.*) *(COMMON) }
    /DISCARD/ : { *(.comment) *(.note*) *(.gnu.attributes) }
}
"""


class BuildError(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise BuildError('%s is not installed (the device\'s cross toolchain; see '
                         'docs/ADAPTING.md)' % cmd[0])
    if r.returncode:
        raise BuildError('%s\n%s%s' % (' '.join(cmd), r.stdout, r.stderr))
    return r.stdout


PORT_FIXED = ('id', 'version', 'device', 'os', 'ports')   # which mod it is: no port changes them


def for_release(mod, dev, rel):
    """mod.json -> (the mod as built for this device and release, whether that is
    one of its ports). A port's keys replace the top level's for its OS."""
    ports = mod.get('ports', {})
    if not isinstance(ports, dict) or not all(isinstance(p, dict) for p in ports.values()):
        raise BuildError('mod.json: "ports" maps an OS version to the keys that differ there')
    if mod.get('device', dev.key) == dev.key:
        if mod.get('os', rel.version) == rel.version:
            return mod, False
        if rel.version in ports:
            port = ports[rel.version]
            fixed = sorted(k for k in port if k in PORT_FIXED)
            if fixed:
                raise BuildError('mod.json: the %s port changes %s; a port gives only what '
                                 'differs on that OS' % (rel.version, ', '.join(fixed)))
            out = dict(mod, **port)
            out['os'] = rel.version
            return out, True
    raise BuildError('mod.json is for %s %s%s; the stock file is %s %s'
                     % (mod.get('device'), mod.get('os'),
                        ' (ports: %s)' % ', '.join(sorted(ports)) if ports else '',
                        dev.key, rel.version))


def build(mdir, stock_path, out_dir=None, extra=None):
    """-> (the path of the .elemod written, its Mod2). `extra` ({'sites', 'contribute',
    'sources'}) lets a generator add parts it computed."""
    with open(os.path.join(mdir, 'mod.json')) as fh:
        mod = json.load(fh)
    extra = extra or {}
    try:
        stock, dev, rel = formats.load(stock_path)
    except (devices.UnknownFirmware, formats.FormatError) as e:
        raise BuildError(str(e))
    mod, ported = for_release(mod, dev, rel)
    image = formats.main_image(stock, dev)
    if sha(image) != rel.main_sha256:
        raise BuildError('the stock main OS is not the known image')
    tc = dev.toolchain
    if not tc:
        raise BuildError('no toolchain in the %s profile' % dev.key)
    prefix = os.environ.get('ELEKLOADER_CROSS', tc['prefix'])
    mid, version = mod['id'], str(mod['version'])
    out_dir = out_dir or os.path.join(mdir, 'out')
    work = os.path.join(out_dir, mid + '.work')
    os.makedirs(work, exist_ok=True)

    srcs = [os.path.join(mdir, s) for s in mod.get('sources', [])] + list(extra.get('sources', []))
    if mod.get('name_string'):
        p = os.path.join(work, 'name.s')
        with open(p, 'w') as fh:
            fh.write('        .section .run, "ax"\n        .globl  str_name\n'
                     'str_name: .asciz "%s %s"\n        .balign 2\n' % (mod['name_string'], version))
        srcs.append(p)
    if not srcs and not mod.get('sites') and not extra.get('sites') and not mod.get('fixed'):
        raise BuildError('mod.json names no sources and no sites: nothing to build')
    defs = []
    for k, v in mod.get('defsym', {}).items():
        defs += ['--defsym', '%s=%s' % (k, v)]
    objs = []
    for s in srcs:
        o = os.path.join(work, os.path.basename(s) + '.o')
        if s.endswith('.c'):
            run([prefix + 'gcc'] + tc['cflags'] + mod.get('cflags', []) + ['-I', mdir, '-c', s,
                                                                            '-o', o])
        else:
            run([prefix + 'as'] + tc['asflags'] + ['-I', mdir] + defs + ['-o', o, s])
        objs.append(o)
    fixed = {}                              # section name -> (address, source)
    for k, fx in enumerate(mod.get('fixed', [])):
        src = os.path.join(mdir, fx['source'])
        at = int(fx['addr'], 16) if isinstance(fx['addr'], str) else fx['addr']
        o = os.path.join(work, 'fixed%d.o' % k)
        run([prefix + 'as'] + tc['asflags'] + ['-I', mdir] + defs + ['-o', o, src])
        for sec in elf.Elf.load(o).sections:
            if sec.size and sec.flags & 2 and sec.name != '.text':
                raise BuildError('%s: fixed code may only have .text, not %s'
                                 % (fx['source'], sec.name))
        name = '.fixed.%d' % k
        run([prefix + 'objcopy', '--rename-section', '.text=' + name, o])
        if fx.get('symbol'):
            run([prefix + 'objcopy', '--add-symbol', '%s=%s:0,global' % (fx['symbol'], name), o])
        fixed[name] = (at, fx['source'])
        objs.append(o)
    secs, sec_of, fsec = {}, {}, {}
    if objs:
        ld = os.path.join(work, 'mod.ld')
        with open(ld, 'w') as fh:
            fh.write(LD_SCRIPT.replace('    /DISCARD/', ''.join(
                '    %s 0 : { *(%s) }\n' % (n, n) for n in fixed) + '    /DISCARD/'))
        obj = os.path.join(work, mid + '.o')
        run([prefix + 'ld', '-r', '-d', '-T', ld, '-o', obj] + objs)
        e = elf.Elf.load(obj)
    else:                                   # a mod of data sites only: no code to link
        e = elf.Elf.__new__(elf.Elf)
        e.sections, e.symbols, e.relocs = [], [], {}
    for s in e.sections:
        if s.name in fixed:
            fsec[s.idx] = s
            continue
        if s.name in KEEP and s.size:
            sec_of[s.idx] = s.name
            if s.name == '.bss':
                secs['.bss'] = {'align': max(4, s.align), 'size': s.size}
            else:
                parts = stock_parts(s.data, image, STOCK_MIN, dev.main_load)
                secs[s.name] = {'align': max(4, s.align), 'len': s.size,
                                'parts': [['hex', p[1].hex()] if p[0] == 'hex'
                                          else ['stock', '0x%08x' % p[1], p[2]] for p in parts]}
        elif s.size and s.flags & 2 and s.name not in KEEP:          # SHF_ALLOC
            raise BuildError('section %s is not one elekloader places (.run, .fast, .bss, '
                             '.boot)' % s.name)
    if '.boot' in secs and mid != 'core':
        raise BuildError('only the core mod may have a .boot section')
    symbols, exports, imports = {}, [], set()
    for y in e.symbols:
        if not y.name or y.type in (elf.STT_SECTION, elf.STT_FILE) or y.name.startswith('.L'):
            continue
        if y.shndx == elf.SHN_UNDEF:
            continue
        if y.shndx == elf.SHN_ABS:
            where = ['abs', y.value]
        elif y.shndx in fsec:
            where = ['abs', fixed[fsec[y.shndx].name][0] + y.value]
        elif y.shndx in sec_of:
            where = [sec_of[y.shndx], y.value]
        else:
            continue
        if y.bind == elf.STB_LOCAL and y.name in symbols:
            continue
        symbols[y.name] = where
        if y.bind in (elf.STB_GLOBAL, elf.STB_WEAK):
            exports.append(y.name)
    def target(y, add):
        v = 0 if y.type == elf.STT_SECTION else y.value
        if y.shndx == elf.SHN_UNDEF:
            imports.add(y.name)
            return 'sym:' + y.name, add
        if y.shndx == elf.SHN_ABS:
            return 'abs', y.value + add
        if y.shndx in fsec:                 # fixed code: its address is known
            return 'abs', fixed[fsec[y.shndx].name][0] + v + add
        if y.shndx in sec_of:
            return 'sec:' + sec_of[y.shndx], v + add
        raise BuildError('a relocation against %s in section %d' % (y.name, y.shndx))

    relocs, frel = [], {}
    for tidx, rl in sorted(e.relocs.items()):
        if tidx not in sec_of and tidx not in fsec:
            if e.sections[tidx].flags & 2:
                raise BuildError('relocations in %s' % e.sections[tidx].name)
            continue
        sec = sec_of.get(tidx) or e.sections[tidx].name
        for off, typ, y, add in rl:
            if typ == elf.R_68K_NONE:
                continue
            if typ not in (elf.R_68K_32, elf.R_68K_PC32, elf.R_68K_PC16):
                raise BuildError('relocation type %d at %s+0x%x (%s): only 32-bit absolute and '
                                 '32/16-bit PC-relative references can be relocated'
                                 % (typ, sec, off, y.name))
            tgt, a = target(y, add)
            if tidx in fsec:
                frel.setdefault(tidx, []).append([off, elf.RNAMES[typ], tgt, a])
            else:
                relocs.append([sec, off, elf.RNAMES[typ], tgt, a])

    sites = []
    for idx, s in sorted(fsec.items()):
        at, src = fixed[s.name]
        if not s.size:
            raise BuildError('%s: no code to place' % src)
        if not any(a <= at and at + s.size <= b for a, b in dev.image_free):
            raise BuildError('%s: 0x%08x-0x%08x is not inside a free area of the %s image (%s)'
                             % (src, at, at + s.size, dev.name,
                                ', '.join('0x%08x-0x%08x' % ab for ab in dev.image_free)
                                or 'it declares none'))
        stockb = image[at - dev.main_load:at - dev.main_load + s.size]
        if any(stockb):
            raise BuildError('%s: the stock bytes at 0x%08x are not all zero' % (src, at))
        sites.append({'addr': '0x%08x' % at, 'len': s.size, 'stock_sha256': sha(stockb),
                      'new': s.data.hex(), 'kind': 'data', 'relocs': frel.get(idx, [])})
    for s in mod.get('sites', []) + list(extra.get('sites', [])):
        addr = int(s['addr'], 16) if isinstance(s['addr'], str) else s['addr']
        stockb = bytes.fromhex(s['stock'])
        o = addr - dev.main_load
        if image[o:o + len(stockb)] != stockb:
            raise BuildError('site 0x%08x: the stock bytes are %s, not %s'
                             % (addr, image[o:o + len(stockb)].hex(), s['stock']))
        op, rel_ = s['op'], []
        add = int(s.get('addend', 0))
        if add and op not in OPS and op not in ('keep2', 'ptr'):
            raise BuildError('site 0x%08x: an addend needs a target (jsr, jmp, keep2 or ptr)' % addr)
        if op in OPS:
            if len(stockb) < 6 or len(stockb) % 2:
                raise BuildError('site 0x%08x: a jsr/jmp needs 6 or more (even) bytes' % addr)
            new = OPS[op] + bytes(4) + b'\x4e\x71' * ((len(stockb) - 6) // 2)
            rel_ = [[2, 'abs32', 'sym:' + s['target'], add]]
            kind = 'code'
        elif op == 'keep2':
            new = stockb[:2] + bytes(4)
            rel_ = [[2, 'abs32', 'sym:' + s['target'], add]]
            kind = 'code'
        elif op == 'ptr':
            new = bytes(4)
            rel_ = [[0, 'abs32', 'sym:' + s['target'], add]]
            kind = 'data'
        elif op == 'bytes':
            new = bytes.fromhex(s['new'])
            kind = s.get('kind', 'data')
        else:
            raise BuildError('site 0x%08x: op %r (jsr, jmp, keep2, ptr or bytes)' % (addr, op))
        if len(new) != len(stockb):
            raise BuildError('site 0x%08x: the new bytes are not as long as the stock ones' % addr)
        if kind == 'code':
            ok, note = elemod.insn_check(image, addr, len(stockb), dev)
            if not ok:
                raise BuildError('site 0x%08x: %s. A code site must cover whole stock '
                                 'instructions' % (addr, note))
        for _o, _t, tgt, _a in rel_:
            if tgt[4:] not in symbols:
                imports.add(tgt[4:])
        sites.append({'addr': '0x%08x' % addr, 'len': len(stockb), 'stock_sha256': sha(stockb),
                      'new': new.hex(), 'kind': kind, 'relocs': rel_})

    contrib = []
    for sub in mod.get('subscribe', []):
        contrib.append({'to': sub['event'], 'order': sub.get('order', 50), 'data': '00000000',
                        'relocs': [[0, 'abs32', 'sym:' + sub['fn'], 0]], 'claims': []})
    for c in mod.get('contribute', []) + list(extra.get('contribute', [])):
        contrib.append({'to': c['to'], 'order': c.get('order', 50), 'data': c['data'],
                        'relocs': c.get('relocs', []), 'claims': c.get('claims', [])})
    for c in contrib:
        for _o, _t, tgt, _a in c['relocs']:
            if tgt.startswith('sym:') and tgt[4:] not in symbols:
                imports.add(tgt[4:])
    weak = list(mod.get('weak', []))
    imports |= set(weak)

    doc = {
        'elemod': 2, 'id': mid, 'version': version,
        'title': mod.get('title', mid), 'description': mod.get('description', ''),
        'category': mod.get('category', ''), 'author': mod.get('author', ''),
        'license': mod.get('license', ''),
        'target': devices.target_of(dev, rel),
        'sections': secs, 'symbols': symbols, 'exports': sorted(exports),
        'imports': sorted(imports - set(symbols)), 'weak': sorted(weak),
        'relocs': relocs, 'sites': sites,
        'collections': {k: {'entry': v} for k, v in mod.get('collections', {}).items()},
        'contribute': contrib, 'copied': mod.get('copied', []),
        'resources': mod.get('resources', {}),
        'requires': mod.get('requires', []), 'conflicts': mod.get('conflicts', []),
        'build': {'sources': {os.path.basename(s): sha(open(s, 'rb').read()) for s in srcs}},
        'signature': None,
    }
    raw = (json.dumps(doc, indent=1) + '\n').encode()
    try:
        m = link.Mod2(json.loads(raw), mid)                # the loader's own validation
    except elemod.ModError as e:
        raise BuildError('the result does not validate: %s' % e)
    path = os.path.join(out_dir, '%s-%s%s.elemod' % (mid, version,
                                                     '-os' + rel.version if ported else ''))
    with open(path, 'wb') as fh:
        fh.write(raw)
    return path, m


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.sdk.build', description=__doc__.split('\n')[0])
    ap.add_argument('moddir', help='the folder with mod.json')
    ap.add_argument('--stock', default=os.environ.get('ELEKLOADER_STOCK'),
                    help='the stock .syx (default: $ELEKLOADER_STOCK)')
    ap.add_argument('--out', help='where to write the .elemod (default MODDIR/out)')
    a = ap.parse_args(argv)
    if not a.stock:
        ap.error('--stock is required (or set ELEKLOADER_STOCK)')
    try:
        path, m = build(a.moddir, a.stock, a.out)
    except (BuildError, OSError, KeyError, ValueError) as e:
        print('BUILD FAILED: %s' % e)
        return 1
    print('BUILT %s' % path)
    print('  %s: .run %d, .fast %d, .bss %d bytes; %d sites, %d relocations; imports %s'
          % (m.label(), m.size('.run'), m.size('.fast'), m.size('.bss'), len(m.sites),
             len(m.relocs), ', '.join(m.imports) or 'nothing'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
