"""Your stock OS .syx + .dtmod files -> a custom firmware .syx (the command line).

    python -m elekloader.patch --stock Digitakt_OS1.53.syx \
        --mod core-2.0a.dtmod --mod sysinfo-2.0a.dtmod ... --out CUSTOM.syx \
        [--version 2.0a] [--check]

In this order, stopping at the first failure:
  1. the .syx must be a stock release elekloader knows (by its sha256), and
     its main OS the known image;
  2. every mod must be made for that release, and every site's stock bytes
     must hash to what the mod expects;
  3. the static conflict check (dtmod.check, link.check);
  4. apply the sites, or link the mods;
  5. repack the main OS and rebuild the .syx: only the main OS section and
     the 4-character version field change;
  6. verify the output with independent code (syx.verify): every other
     section is stock byte for byte, the main OS depacks in place to the
     patched image, every checksum, the flash budget;
  7. write the .syx, OUT.json (a manifest with every hash) and, for linked
     mods, OUT.map.json (every symbol's address).

--check stops after step 4 and writes nothing. Nothing here talks to a
device: you flash the .syx yourself, as with any OS update, and the stock
.syx recovers the unit because the bootloader is never changed.
"""
import argparse
import json
import os
import sys
import time

from . import devices, dtmod, link, syx
from .dtmod import sha


class PatchError(Exception):
    pass


def build(stock_path, mod_paths, version=None, check_only=False, log=print):
    """-> (out .syx bytes or None, manifest dict). Raises PatchError."""
    try:
        stock = syx.Syx.load(stock_path)
    except (OSError, syx.SyxError) as e:
        raise PatchError('cannot read %s: %s' % (stock_path, e))
    try:
        dev, rel = devices.identify(stock.sha256)
    except devices.UnknownFirmware as e:
        raise PatchError('%s: %s' % (stock_path, e))
    img0 = stock.section(dev.main_section)
    if sha(img0) != rel.main_sha256:
        raise PatchError('its main OS is not the known %s %s image' % (dev.name, rel.version))
    log('stock: %s OS %s (%s)' % (dev.name, rel.version, stock.sha256))
    mods = []
    for p in mod_paths:
        try:
            m = dtmod.load_any(p)
        except (OSError, dtmod.ModError) as e:
            raise PatchError(str(e))
        if m.dev.key != dev.key or m.rel != rel:
            raise PatchError('%s is made for %s %s; your stock firmware is %s %s'
                             % (m.label(), m.dev.name, m.rel.version, dev.name, rel.version))
        log('mod %-24s %d sites%s  (file sha256 %s)'
            % (m.label(), len(m.sites), ', blob %d bytes' % m.blob['len'] if m.blob else '',
               m.sha256[:16]))
        mods.append(m)
    if not mods:
        raise PatchError('no mods given')
    v2 = [m for m in mods if isinstance(m, link.Mod2)]
    linked = None
    try:
        if v2:
            if len(v2) != len(mods):
                raise dtmod.ModError('a whole-build bundle (format 1) cannot be combined '
                                     'with separate mods (format 2)')
            linked = link.link(mods, img0)
            img = linked.image
        else:
            img = dtmod.apply(mods, img0)
    except dtmod.ModError as e:
        raise PatchError(str(e))
    log('the mods combine: no overlaps, stock bytes as expected, code sites whole instructions')
    if linked:
        L = linked.layout
        log('linked %s: RAM 0x%08x-0x%08x (%d bytes spare), .fast to 0x%08x (%d spare), '
            'blob %d bytes' % (', '.join(linked.order), L['ddr'][0], L['bss'][1],
                               L['ddr_spare'], L['fast'][1], L['fast_spare'], L['blob_len']))
    man = {
        'patcher': 'elekloader', 'device': dev.key,
        'stock': {'path': os.path.abspath(stock_path), 'sha256': stock.sha256,
                  'os': rel.version, 'main_sha256': sha(img0)},
        'mods': [{'id': m.id, 'version': m.version, 'file': m.name, 'sha256': m.sha256,
                  'format': 2 if isinstance(m, link.Mod2) else 1, 'sites': len(m.sites),
                  'regions': [{'name': g['name'], 'lo': '0x%08x' % g['lo'],
                               'hi': '0x%08x' % g['hi'], 'area': g['area']} for g in m.regions],
                  'names': m.names} for m in mods],
        'main_sha256': sha(img),
        'main_len': len(img),
    }
    if linked:
        man['link'] = {'order': linked.order, 'layout': linked.layout,
                       'tables': {c: {'at': '0x%08x' % a, 'entries': n, 'entry': e}
                                  for c, (a, n, e) in sorted(linked.tables.items())}}
        man['_map'] = linked.map
    if len(mods) == 1 and not v2 and (mods[0].doc.get('build') or {}).get('section3_sha256'):
        want = mods[0].doc['build'].get('section3_sha256')
        man['bundle_matches_build'] = want == sha(img)
        if want != sha(img):
            raise PatchError('the bundle does not reproduce its build\'s main OS')
        log('the main OS matches the build the bundle came from (sha256 %s)' % sha(img)[:16])
    if check_only:
        return None, man
    if version is None:
        vs = {m.doc.get('ele3_version') for m in mods} - {None}
        if len(vs) != 1:
            raise PatchError('give --version (4 characters): the mods name %s'
                             % (sorted(vs) or 'no version'))
        version = vs.pop()
    if len(version.encode('ascii', 'replace')) != 4:
        raise PatchError('the version is exactly 4 ASCII characters')
    t = time.time()
    stored = syx.pack_main(img)
    log('packed the main OS: %d -> %d bytes (%.1f s)' % (len(img), len(stored), time.time() - t))
    try:
        out = syx.write(stock, stored, dev, version)
        facts = syx.verify(out, stock, img, dev, version)
    except syx.SyxError as e:
        raise PatchError('the output failed verification: %s' % e)
    log('verified: every other section stock byte for byte; the main OS depacks in place '
        '(min gap %d bytes); flash ends %s (%d bytes spare)'
        % (facts['main']['inplace_min_gap'], facts['flash_end'], facts['flash_headroom']))
    man['version'] = version
    man['output'] = facts
    return out, man


def save(out, man, path):
    """Write the .syx and its manifest (and symbol map) next to it."""
    tmp = path + '.part'
    with open(tmp, 'wb') as fh:
        fh.write(out)
    os.replace(tmp, path)
    man['output']['path'] = os.path.abspath(path)
    smap = man.pop('_map', None)
    if smap is not None:
        with open(path + '.map.json', 'w') as fh:
            json.dump({k: '0x%08x' % v for k, v in sorted(smap.items())}, fh, indent=0)
        man['map'] = os.path.basename(path) + '.map.json'
    with open(path + '.json', 'w') as fh:
        json.dump(man, fh, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.patch', description=__doc__.split('\n')[0])
    ap.add_argument('--stock', required=True, help='your stock OS .syx')
    ap.add_argument('--mod', action='append', default=[], help='a .dtmod (repeat for more)')
    ap.add_argument('--out', help='the .syx to write')
    ap.add_argument('--version', help='the 4 characters the unit shows as its OS version '
                                      '(default: the mod\'s)')
    ap.add_argument('--check', action='store_true', help='check the mods combine; write nothing')
    a = ap.parse_args(argv)
    if not a.check and not a.out:
        ap.error('--out is required (or --check)')
    if a.out and os.path.exists(a.stock) and os.path.exists(a.out) \
            and os.path.samefile(a.stock, a.out):
        ap.error('--out is the stock file')
    try:
        out, man = build(a.stock, a.mod, a.version, a.check)
    except PatchError as e:
        print('REFUSED: %s' % e)
        return 1
    if a.check:
        print('OK: the mods combine (nothing written)')
        return 0
    save(out, man, a.out)
    print('WROTE %s' % a.out)
    print('  sha256 %s, version %s, %d bytes' % (man['output']['sha256'], man['version'], len(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
