#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the kit for websites (docs/INTEGRATING.md) as a release asset: elekloader-kit-<version>.zip.

    python packaging/build_kit.py --out build/kit      # needs Node 22.18 or newer

The zip holds, from HEAD (git archive HEAD js: committed files only):
  - src/: the engine and the kit in TypeScript, for a site with a bundler;
  - dist/: the same as plain JavaScript (js/tools/build.ts), for a site
    without one. dist/kit/worker.js is the worker, dist/kit/index.js the
    page's side;
  - tools/kit.ts and tools/build.ts: feed, sync, verify and lock, and the
    build of dist/;
  - examples/minimal/: the smallest site;
  - LICENSE (GPL-3.0-or-later, the kit's), NOTICE (elekloader's), README.md
    (docs/INTEGRATING.md);
  - kit.json: the version, the protocol, the commit and every file's sha256.

It is zipped reproducibly, as build_web.py zips the package: sorted, one
fixed date, stored. The same commit and Node give the same zip.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_MIN = (22, 18)
TAKE = ('js/src/', 'js/tools/kit.ts', 'js/tools/build.ts', 'js/examples/minimal/', 'js/LICENSE')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', ROOT] + list(args), check=True, stdout=subprocess.PIPE).stdout


def node():
    out = subprocess.run(['node', '--version'], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    v = tuple(int(x) for x in out.lstrip('v').split('.')[:2])
    if v < NODE_MIN:
        sys.exit('node %s: the kit is built with Node %d.%d or newer' % (out, *NODE_MIN))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True, help='the folder to write the zip to')
    a = ap.parse_args(argv)
    version = node()
    commit = git('rev-parse', 'HEAD').decode().strip()
    tar = tarfile.open(fileobj=io.BytesIO(git('-c', 'core.autocrlf=false', 'archive', '--format=tar', 'HEAD', 'js')))
    files = {}
    for m in tar.getmembers():
        if m.isfile() and m.name.startswith(TAKE):
            files[m.name[len('js/'):]] = tar.extractfile(m).read()
    files['README.md'] = git('-c', 'core.autocrlf=false', 'show', 'HEAD:docs/INTEGRATING.md')
    files['NOTICE'] = git('-c', 'core.autocrlf=false', 'show', 'HEAD:NOTICE')
    with tempfile.TemporaryDirectory() as tmp:          # dist/: the commit's sources, built by its build.ts
        for name, data in files.items():
            if name.startswith(('src/', 'tools/')):
                p = os.path.join(tmp, *name.split('/'))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as fh:
                    fh.write(data)
        subprocess.run(['node', os.path.join(tmp, 'tools', 'build.ts'), os.path.join(tmp, 'dist')], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for dirpath, _, names in os.walk(os.path.join(tmp, 'dist')):
            for n in names:
                p = os.path.join(dirpath, n)
                with open(p, 'rb') as fh:
                    files[os.path.relpath(p, tmp).replace(os.sep, '/')] = fh.read()
    pkg = json.loads(git('show', 'HEAD:js/package.json'))
    protocol = int(re.search(rb'export const PROTOCOL = (\d+)', files['src/kit/protocol.ts']).group(1))
    files['kit.json'] = (json.dumps({
        'name': 'elekloader-kit', 'version': pkg['version'], 'protocol': protocol, 'commit': commit,
        'node': version, 'license': 'GPL-3.0-or-later',
        'files': {n: sha(b) for n, b in sorted(files.items())},
    }, indent=1) + '\n').encode()
    top = 'elekloader-kit-%s/' % pkg['version']
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(top + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.create_system = 3          # zipfile writes the running OS's (0 on Windows)
            z.writestr(info, data)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, 'elekloader-kit-%s.zip' % pkg['version'])
    with open(path, 'wb') as fh:
        fh.write(out.getvalue())
    print('%s: %d files, %d KB, sha256 %s (commit %s, protocol %d, %s)'
          % (path, len(files), len(out.getvalue()) // 1024, sha(out.getvalue()), commit[:12], protocol, version))
    return 0


if __name__ == '__main__':
    sys.exit(main())
