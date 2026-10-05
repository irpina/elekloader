# SPDX-License-Identifier: GPL-2.0-or-later
"""The Python half of tools/parity.ts: runs every case with elekloader's Python and writes what it gives.

    python3 js/tools/parity.py cases.json results.json

Each case is a stock file and a set of mods, copied under ROOT/<n>/ to the paths the TypeScript engine is given
(stock/<name>, mods/<name>), so the manifests name the same paths. For each case: what patch.build and patch.save
give (each file's sha256, or the refusal), what the window's live check says (gui.LoaderModel.check), and what it
says about each mod (describe). Needs a POSIX system (the paths), and the stock files, which never go in the repo.
"""
import hashlib
import json
import os
import shutil
import sys
import traceback

ROOT_PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_PKG)

from elekloader import gui, patch     # noqa: E402


def sha(b):
    return hashlib.sha256(b).hexdigest()


def run(case, root):
    work = os.path.join(root, str(case['n']))
    shutil.rmtree(work, ignore_errors=True)
    for d in ('stock', 'mods', 'out'):
        os.makedirs(os.path.join(work, d))
    stock = os.path.join(work, 'stock', case['stock_name'])
    shutil.copyfile(case['stock'], stock)
    mods = []
    for p in case['mods']:
        q = os.path.join(work, 'mods', os.path.basename(p))
        shutil.copyfile(p, q)
        mods.append(q)
    out = {'n': case['n']}
    log = []
    try:
        outputs, man = patch.build(stock, mods, case.get('version'), check_only=case.get('check_only', False),
                                   log=lambda line: log.append(line))
        if outputs is None:
            out['checked'] = json.loads(json.dumps(man))
        else:
            patch.save(outputs, man, os.path.join(work, 'out', case['out_name']))
            out['files'] = {n: sha(open(os.path.join(work, 'out', n), 'rb').read())
                            for n in sorted(os.listdir(os.path.join(work, 'out')))}
    except patch.PatchError as e:
        out['refused'] = str(e)
    except Exception as e:                      # a crash is a result too: the TS must crash alike
        out['crash'] = type(e).__name__
        out['trace'] = traceback.format_exc()[-400:]
    out['log'] = [x for x in log if not x.startswith('packed the main OS')]
    model = gui.LoaderModel(stock=stock, library=os.path.join(work, 'mods'),
                            settings=os.path.join(work, 'settings.json'))
    try:
        r = model.check(sorted(mods))
        r.pop('ms', None)
        out['check'] = json.loads(json.dumps(r))
    except Exception as e:
        out['check'] = {'crash': type(e).__name__}
    out['describe'] = {}
    for p in mods:
        try:
            out['describe'][os.path.basename(p)] = json.loads(json.dumps(model.describe(p)))
        except Exception as e:
            out['describe'][os.path.basename(p)] = {'crash': type(e).__name__}
    out['stock'] = {k: v for k, v in model.stock.items()}
    return out


def main():
    cases_path, results_path = sys.argv[1:3]
    with open(cases_path) as fh:
        spec = json.load(fh)
    results = []
    for i, case in enumerate(spec['cases']):
        r = run(case, spec['root'])
        results.append(r)
        state = 'built' if 'files' in r else 'checked' if 'checked' in r else 'REFUSED' if 'refused' in r else 'CRASH'
        print('%3d/%d %-8s %s' % (i + 1, len(spec['cases']), state, case['label']), flush=True)
    with open(results_path, 'w') as fh:
        json.dump(results, fh, indent=1)


if __name__ == '__main__':
    main()
