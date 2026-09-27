"""Check .elemod files and say what is wrong (docs/ADAPTING.md).

    python -m elekloader.lint MY.elemod [MORE.elemod ...]
    python -m elekloader.lint MY.elemod --stock Digitakt_OS1.53.syx --with core.elemod [--json]

Without --stock, it checks each file on its own:
- the format and every field;
- a target it knows;
- sites and sections inside the image.

With --stock it also runs the full conflict check on the files together
with any --with mods (e.g. the core your mod requires). Format-2 mods are
then linked, so every import resolves and the budgets are checked.

It prints one "OK" or "PROBLEM:" line per finding, or JSON with --json.
Exit status 0 means every check passed.
"""
import argparse
import json
import sys

from . import devices, elemod, formats, link


def describe(m):
    d = {'file': m.name, 'id': m.id, 'version': m.version,
         'format': 2 if isinstance(m, link.Mod2) else 1,
         'target': '%s %s' % (m.dev.name, m.rel.version),
         'sites': ['0x%08x +%d %s' % (s['addr'], s['len'], s['kind']) for s in m.sites],
         'requires': m.requires, 'conflicts': m.conflicts, 'names': m.names,
         'license': m.doc.get('license', ''),
         'regions': ['%s 0x%08x-0x%08x' % (g['name'], g['lo'], g['hi']) for g in m.regions]}
    if isinstance(m, link.Mod2):
        d.update(sections={s: m.size(s) for s in ('.boot', '.run', '.fast', '.bss') if m.size(s)},
                 exports=len(m.exports), imports=m.imports, weak=sorted(m.weak),
                 tables=m.collections,
                 adds_to=sorted({c['to'] for c in m.contribute}))
    else:
        d['blob'] = m.blob['len'] if m.blob else 0
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.lint', description=__doc__.split('\n')[0])
    ap.add_argument('mods', nargs='+', help='the .elemod files to check')
    ap.add_argument('--stock', help='the stock .syx: also run the full check and link')
    ap.add_argument('--with', dest='others', action='append', default=[],
                    help='another mod to check together with (repeatable), e.g. core')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    a = ap.parse_args(argv)
    report = {'ok': True, 'mods': [], 'problems': []}

    def problem(text):
        report['ok'] = False
        report['problems'].append(text)

    loaded = []
    for p in a.mods + a.others:
        try:
            m = elemod.load_any(p)
        except (OSError, elemod.ModError) as e:
            problem('%s: %s' % (p, e))
            continue
        loaded.append(m)
        if p in a.mods:
            report['mods'].append(describe(m))
    if a.stock and loaded and report['ok']:
        try:
            st, dev, rel = formats.load(a.stock)
            img = formats.main_image(st, dev)
        except (OSError, formats.FormatError, devices.UnknownFirmware) as e:
            problem('the stock file: %s' % e)
        else:
            for m in loaded:
                if m.dev.key != dev.key or m.rel != rel:
                    problem('%s is made for %s %s; the stock file is %s %s'
                            % (m.label(), m.dev.name, m.rel.version, dev.name, rel.version))
            if report['ok']:
                v2 = [m for m in loaded if isinstance(m, link.Mod2)]
                try:
                    if v2 and len(v2) != len(loaded):
                        raise elemod.ModError('x:\n  a whole build (format 1) cannot be '
                                             'combined with format-2 mods')
                    if v2:
                        L = link.link(loaded, img)
                        lay = L.layout
                        report['link'] = {
                            'order': L.order,
                            'ram_used': lay['bss'][1] - lay['ddr'][0], 'ram_size': lay['ddr_size'],
                            'fast_used': lay['fast'][1] - lay['fast'][0],
                            'fast_size': lay['fast_size'],
                            'addresses': {k: '0x%08x' % L.map[k]
                                          for m in loaded[:len(a.mods)]
                                          for k in sorted(m.exports) if k in L.map}}
                    else:
                        elemod.apply(loaded, img)
                except elemod.ModError as e:
                    for line in str(e).split('\n')[1:] or [str(e)]:
                        problem(line.strip())
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        for d in report['mods']:
            print('OK: %s %s (format %d) for %s: %d sites%s; licence %s' % (
                d['id'], d['version'], d['format'], d['target'], len(d['sites']),
                (', sections %s, imports %s' % (d['sections'], ', '.join(d['imports']) or 'none'))
                if d['format'] == 2 else '', d['license'] or 'not stated'))
        if 'link' in report:
            L = report['link']
            print('OK: links as %s; RAM %d of %d bytes, fast SRAM %d of %d'
                  % (' > '.join(L['order']), L['ram_used'], L['ram_size'], L['fast_used'],
                     L['fast_size']))
        for x in report['problems']:
            print('PROBLEM: %s' % x)
        if report['ok'] and not a.stock:
            print('(add --stock and --with to check it against the firmware and other mods)')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
