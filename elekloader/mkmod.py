"""A built custom firmware .syx -> a format-1 .dtmod (one mod = one whole build).

    python -m elekloader.mkmod --stock Digitakt_OS1.53.syx --build CUSTOM.syx \
        [--manifest CUSTOM.syx.json] [--elf CUSTOM.syx.elf] --meta META.json --out CUSTOM.dtmod

For builds made the monolithic way: one patch list and one blob appended at
the stock main OS's end.

The sites come from the build's manifest: a JSON with
"patches": [{"addr", "old", "new"}], as digikit's build_cfw.py writes it,
with every site's whole stock instruction or data word. Each site is:
- checked against the stock image and the build;
- classified "code" when the stock bytes decode as whole instructions (the
  full boundary check must then pass), else "data", or "data" when the meta
  file lists it under "data_sites".
Every byte the build changes must be covered by a site.

The blob is everything after the stock image's end. Runs of at least
--stock-min bytes that also occur in the stock main OS (2-aligned in both)
are stored as copies from the user's image, not as bytes.

The regions come from the ELF's layout symbols (__run_start..__bss_end,
__fast_start + __fast_len), plus the meta file's "regions". The result is
checked by applying it to stock: it must give the build's main OS exactly.
"""
import argparse
import json
import os
import struct
import sys

from . import devices, dtmod, syx
from .dtmod import sha


def die(msg):
    print('FAIL: ' + msg)
    sys.exit(1)


def elf_symbols(path):
    """ELF32 big-endian -> {name: value} from its .symtab."""
    with open(path, 'rb') as fh:
        d = fh.read()
    if d[:4] != b'\x7fELF' or d[4] != 1 or d[5] != 2:
        raise ValueError('%s: not a 32-bit big-endian ELF' % path)
    shoff, = struct.unpack_from('>I', d, 0x20)
    shentsize, shnum = struct.unpack_from('>HH', d, 0x2E)
    shs = [struct.unpack_from('>IIIIIIIIII', d, shoff + i * shentsize) for i in range(shnum)]
    out = {}
    for sh in shs:
        if sh[1] != 2:                               # SHT_SYMTAB
            continue
        stoff = shs[sh[6]][4]
        for o in range(sh[4], sh[4] + sh[5], 16):
            name, value = struct.unpack_from('>II', d, o)
            end = d.index(b'\0', stoff + name)
            nm = d[stoff + name:end].decode('ascii', 'replace')
            if nm:
                out[nm] = value
    return out


def stock_parts(blob, stock, minimum, load):
    """-> parts of `blob`: runs of >= minimum bytes found in `stock` (loaded at
    `load`; 2-aligned in both) as ('stock', addr, n), the rest as ('hex', bytes)."""
    idx = {}
    for o in range(0, len(stock) - minimum + 1, 2):
        idx.setdefault(stock[o:o + minimum], o)
    parts, lit, i = [], bytearray(), 0
    while i < len(blob):
        o = idx.get(blob[i:i + minimum]) if i % 2 == 0 and i + minimum <= len(blob) else None
        if o is None or len(set(blob[i:i + minimum])) == 1:
            lit.append(blob[i])
            i += 1
            continue
        n = minimum
        while i + n + 2 <= len(blob) and stock[o + n:o + n + 2] == blob[i + n:i + n + 2]:
            n += 2
        if lit:
            parts.append(('hex', bytes(lit)))
            lit = bytearray()
        parts.append(('stock', load + o, n))
        i += n
    if lit:
        parts.append(('hex', bytes(lit)))
    return parts


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.mkmod', description=__doc__.split('\n')[0])
    ap.add_argument('--stock', required=True, help='the stock OS .syx')
    ap.add_argument('--build', required=True, help='the built custom firmware .syx')
    ap.add_argument('--manifest', help='its build manifest (default BUILD.json)')
    ap.add_argument('--elf', help='its ELF, for the regions (default BUILD.elf if present)')
    ap.add_argument('--meta', required=True, help='the mod\'s id, title, resources (JSON)')
    ap.add_argument('--out', required=True, help='the .dtmod to write')
    ap.add_argument('--stock-min', type=int, default=8,
                    help='store blob runs of at least this many bytes found in stock as '
                         'copies from the user\'s image (default 8; even)')
    a = ap.parse_args(argv)
    if a.stock_min < 4 or a.stock_min % 2:
        die('--stock-min is an even number >= 4')

    stock = syx.Syx.load(a.stock)
    try:
        dev, rel = devices.identify(stock.sha256)
    except devices.UnknownFirmware as e:
        die(str(e))
    load, end = dev.main_load, dev.image_end(rel)
    img0 = stock.section(dev.main_section)
    if sha(img0) != rel.main_sha256:
        die('the stock main OS sha256 is not the known one')
    built = syx.Syx.load(a.build)
    img1 = built.section(dev.main_section)
    if [(s, d) for s, _o, _l, d in built.table] != [(s, d) for s, _o, _l, d in stock.table]:
        die('the build\'s section table differs from stock')
    for sid in stock.stored:
        if sid != dev.main_section and built.section(sid) != stock.section(sid):
            die('the build changes section %d; a .dtmod can only carry the main OS' % sid)
    hd = [i for i in range(0x1C) if built.header[i] != stock.header[i]]
    if any(not 0x14 <= i < 0x18 for i in hd):
        die('the build\'s ELE3 header differs outside the version field')
    if len(img1) < len(img0):
        die('the build\'s main OS is shorter than stock')

    with open(a.meta) as fh:
        meta = json.load(fh)
    data_sites = {int(str(x), 0) for x in meta.get('data_sites', [])}
    with open(a.manifest or a.build + '.json') as fh:
        manifest = json.load(fh)

    sites, cover = [], bytearray(img0)
    for p in sorted(manifest['patches'], key=lambda p: int(p['addr'], 16)):
        addr, old, new = int(p['addr'], 16), bytes.fromhex(p['old']), bytes.fromhex(p['new'])
        o = addr - load
        if len(old) != len(new) or not 0 <= o <= len(img0) - len(old):
            die('manifest patch %s: bad length or address' % p['addr'])
        if img0[o:o + len(old)] != old:
            die('manifest patch %s: not the stock bytes' % p['addr'])
        if img1[o:o + len(new)] != new:
            die('manifest patch %s: not what the build has there' % p['addr'])
        ok_end = dtmod.insn_check(img0, addr, len(old), dev, sweeps=0)[0]
        kind = 'data' if addr in data_sites or not ok_end else 'code'
        if kind == 'code':
            for which, im in (('stock', img0),
                              ('new', bytes(cover[:o] + new + cover[o + len(new):]))):
                ok, note = dtmod.insn_check(im, addr, len(old), dev)
                if not ok:
                    die('site 0x%08x (%s bytes): %s; if it is data, list it under '
                        '"data_sites" in the meta file' % (addr, which, note))
        cover[o:o + len(new)] = new
        sites.append({'addr': '0x%08x' % addr, 'len': len(old),
                      'stock_sha256': sha(old), 'new': new.hex(), 'kind': kind})
    if bytes(cover) != img1[:len(img0)]:
        n = sum(1 for x, y in zip(cover, img1) if x != y)
        die('%d changed bytes of the build are not covered by a manifest site' % n)

    blob = img1[len(img0):]
    doc = {
        'dtmod': dtmod.FORMAT,
        'id': meta['id'],
        'version': meta.get('version') or built.version,
        'title': meta.get('title', meta['id']),
        'category': meta.get('category', 'Whole build'),
        'description': meta.get('description', ''),
        'target': devices.target_of(dev, rel),
        'ele3_version': built.version,
        'sites': sites,
    }
    regions = list(meta.get('regions', []))
    elf = a.elf or (a.build + '.elf' if os.path.exists(a.build + '.elf') else None)
    if elf:
        sym = elf_symbols(elf)
        if blob and sym.get('boot') != end:
            die('the ELF\'s boot is not at the image end: not this build\'s ELF?')
        regions.insert(0, {'name': 'run+bss', 'lo': '0x%08x' % sym['__run_start'],
                           'hi': '0x%08x' % sym['__bss_end']})
        if sym.get('__fast_len'):
            regions.insert(1, {'name': 'fast', 'lo': '0x%08x' % sym['__fast_start'],
                               'hi': '0x%08x' % (sym['__fast_start'] + sym['__fast_len'])})
    elif blob:
        print('warning: no ELF, so no run-time regions beyond the meta file\'s')
    if blob:
        parts = stock_parts(blob, img0, a.stock_min, load)
        doc['blob'] = {'load': '0x%08x' % end, 'len': len(blob), 'sha256': sha(blob),
                       'parts': [['hex', p[1].hex()] if p[0] == 'hex'
                                 else ['stock', '0x%08x' % p[1], p[2]] for p in parts]}
    doc['resources'] = {'regions': regions, 'names': list(meta.get('names', []))}
    doc['requires'] = list(meta.get('requires', []))
    doc['conflicts'] = list(meta.get('conflicts', []))
    doc['build'] = {'syx_sha256': built.sha256, 'section3_sha256': sha(img1)}
    if meta.get('notes'):
        doc['notes'] = meta['notes']
    doc['signature'] = None

    mod = dtmod.Mod(doc, os.path.basename(a.out))
    if dtmod.apply([mod], img0) != img1:
        die('the .dtmod does not reproduce the build\'s main OS')
    raw = (json.dumps(doc, indent=1) + '\n').encode('utf-8')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'wb') as fh:
        fh.write(raw)
    ncopy = [p for p in doc.get('blob', {}).get('parts', []) if p[0] == 'stock']
    print('wrote %s (%d bytes, sha256 %s)' % (a.out, len(raw), sha(raw)))
    print('  %s %s: %d sites (%d code, %d data), blob %d bytes at 0x%08x'
          % (doc['id'], doc['version'], len(sites), sum(s['kind'] == 'code' for s in sites),
             sum(s['kind'] == 'data' for s in sites), len(blob), end))
    if blob:
        print('  blob: %d bytes from the user\'s stock image in %d runs (>= %d bytes each), '
              '%d bytes carried' % (sum(p[2] for p in ncopy), len(ncopy), a.stock_min,
                                    len(blob) - sum(p[2] for p in ncopy)))
    for g in regions:
        print('  region %-18s %s-%s' % (g['name'], g['lo'], g['hi']))
    print('  reproduces the build\'s main OS (sha256 %s)' % sha(img1)[:16])
    return 0


if __name__ == '__main__':
    sys.exit(main())
