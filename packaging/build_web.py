#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Assemble the web page (web/) into a static site, for GitHub Pages.

    python packaging/build_web.py --core core-2.1.elemod [core-dn1-2.0a.elemod ...] \\
        [--release v0.4.0] --out build/site

The page builds custom firmware from the user's own stock OS file and their
own .elemod files. The mods themselves are on Modwerk, not here.

The site holds:
  - web/'s page: index.html, style.css, app.js and worker.js;
  - engine/: elekloader's TypeScript engine (js/), exactly as the commit
    has it (`git archive HEAD js`: committed files only), made plain
    JavaScript by js/tools/build.ts with Node's own type stripping (Node
    22.18 or newer), and its licence (engine/LICENSE.txt, GPL-3.0-or-later);
  - core/: the core mods given (the release's), with core/index.json;
  - LICENSE.txt, NOTICE.txt, and build.json (what went in).

Everything the page loads is in the site: it fetches nothing from anywhere
else. No firmware goes in. The stock OS file is only ever read in the
user's browser, and each core is checked to be a core mod.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from elekloader import elemod, link  # noqa: E402

WEB_FILES = ('index.html', 'style.css', 'app.js', 'worker.js')
NODE_MIN = (22, 18)                  # type stripping by default, and module.stripTypeScriptTypes
PAGES_FILE_MAX = 100 << 20           # GitHub Pages: 100 MB a file, 1 GB a site
PAGES_SITE_MAX = 1 << 30


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', ROOT] + list(args), check=True,
                          stdout=subprocess.PIPE).stdout


def node():
    """The node to build the engine with, checked to be new enough."""
    exe = shutil.which('node')
    if not exe:
        sys.exit('node is needed to build the engine (Node %d.%d or newer)' % NODE_MIN)
    v = subprocess.run([exe, '--version'], check=True, stdout=subprocess.PIPE).stdout.decode().strip()
    got = tuple(int(x) for x in re.findall(r'\d+', v)[:2])
    if got < NODE_MIN:
        sys.exit('node %s is too old to build the engine: %d.%d or newer' % ((v,) + NODE_MIN))
    return exe, v


def engine():
    """js/ as HEAD has it (the blobs as committed), built into plain JavaScript. -> ({name: bytes}, node version)."""
    exe, version = node()
    tar = tarfile.open(fileobj=io.BytesIO(
        git('-c', 'core.autocrlf=false', 'archive', '--format=tar', 'HEAD', 'js')))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        tar.extractall(tmp, filter='data') if hasattr(tarfile, 'data_filter') else tar.extractall(tmp)
        dist = os.path.join(tmp, 'dist')
        subprocess.run([exe, os.path.join(tmp, 'js', 'tools', 'build.ts'), dist], check=True,
                       stdout=subprocess.DEVNULL)
        for folder, _dirs, files in os.walk(dist):
            for f in files:
                p = os.path.join(folder, f)
                with open(p, 'rb') as fh:
                    out[os.path.relpath(p, dist).replace(os.sep, '/')] = fh.read()
        with open(os.path.join(tmp, 'js', 'LICENSE'), 'rb') as fh:
            out['LICENSE.txt'] = fh.read()
    if 'index.js' not in out:
        sys.exit('the engine build made no index.js')
    return out, version


def cores(paths):
    out = []
    for p in sorted(paths, key=os.path.basename):
        m = elemod.load_any(p)
        if m.id != 'core' or not isinstance(m, link.Mod2):
            sys.exit('%s is not a core mod (id %r)' % (p, m.id))
        with open(p, 'rb') as fh:
            raw = fh.read()
        out.append(({'file': os.path.basename(p), 'sha256': sha(raw), 'id': m.id,
                     'version': m.version, 'device': m.dev.key, 'os': m.rel.version}, raw))
    return out


def tree(rev, path):
    """The git tree of `path` at `rev`, or None when it has none there."""
    r = subprocess.run(['git', '-C', ROOT, 'rev-parse', '%s:%s' % (rev, path)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', nargs='*', default=[], help='the core mods to list (the release\'s)')
    ap.add_argument('--release', help='the release the cores come from (its tag, fetched): the '
                                      'page says whether its engine is that release\'s')
    ap.add_argument('--out', required=True, help='the site folder to write (emptied first)')
    a = ap.parse_args(argv)
    eng, node_version = engine()
    cs = cores(a.core)
    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    site = {}
    for n in WEB_FILES:
        with open(os.path.join(ROOT, 'web', n), 'rb') as fh:
            site[n] = fh.read()
    for n in ('LICENSE', 'NOTICE'):
        with open(os.path.join(ROOT, n), 'rb') as fh:
            site[n + '.txt'] = fh.read()
    for n, b in eng.items():
        site['engine/' + n] = b
    for c, raw in cs:
        site['core/' + c['file']] = raw
    site['core/index.json'] = json.dumps([c for c, _ in cs], indent=1).encode()
    commit = git('rev-parse', 'HEAD').decode().strip()
    dirty = bool(git('status', '--porcelain', '--', 'js').strip())
    js_tree = tree('HEAD', 'js')
    # the same tree is the same engine, file for file
    same = bool(a.release and tree('%s^{commit}' % a.release, 'js') == js_tree)
    engine_sha = sha(''.join('%s %s\n' % (n, sha(b)) for n, b in sorted(eng.items())).encode())
    from elekloader import __version__
    site['build.json'] = json.dumps({
        'elekloader': __version__, 'commit': commit,
        'commit_date': git('log', '-1', '--format=%cI').decode().strip(),
        # the engine is HEAD's js/; a working tree with changes there is not in it
        'engine_changes_not_in_site': dirty,
        'engine_tree': js_tree, 'engine_sha256': engine_sha, 'engine_files': len(eng),
        'node': node_version, 'release': a.release or None, 'same_as_release': same,
        'cores': [c for c, _ in cs],
        'files': {n: sha(b) for n, b in sorted(site.items())},
    }, indent=1).encode()
    for n, b in site.items():
        p = os.path.join(a.out, *n.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(b)
    big = [n for n, b in site.items() if len(b) > PAGES_FILE_MAX]
    total = sum(len(b) for b in site.values())
    if big or total > PAGES_SITE_MAX:
        sys.exit('too large for GitHub Pages: %s' % (', '.join(big) or '%d bytes' % total))
    for n in sorted(site, key=lambda n: -len(site[n])):
        print('%10d  %s' % (len(site[n]), n))
    print('%10d  in %d files -> %s' % (total, len(site), a.out))
    print('elekloader %s (%s%s%s); engine sha256 %s (%d files, node %s); cores: %s'
          % (__version__, commit[:12], ', with engine changes NOT in the site' if dirty else '',
             (', the same engine as %s' if same else ', not the engine of %s') % a.release
             if a.release else '', engine_sha, len(eng), node_version,
             ', '.join(c['file'] for c, _ in cs) or 'none'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
