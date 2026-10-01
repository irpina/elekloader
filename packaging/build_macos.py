# SPDX-License-Identifier: GPL-2.0-or-later
"""Build elekloader's macOS app: elekloader.app with the core mods built in, in a .dmg.

    python packaging/build_macos.py --core core-2.1.elemod [core-dn1-2.0a.elemod ...]
        [--identity "Developer ID Application: ..."] [--notarize] [--out dist]

Needs macOS, Xcode's command line tools and PyInstaller
(packaging/requirements-build.txt). The core .elemod files are given, not
built here, as for build_windows.py.

The app is universal2 (Apple silicon and Intel), which needs a universal2
Python such as python.org's; --arch arm64 or x86_64 builds for one. With
--identity (a Developer ID Application certificate in the keychain, by name
or SHA-1) every binary in the app is signed with the hardened runtime.
Without it the app is signed ad hoc: for trying on this Mac, not for a
release. --notarize has Apple notarize the app and the .dmg and staples
both, with an App Store Connect API key: NOTARY_KEY (the .p8 file),
NOTARY_KEY_ID and NOTARY_ISSUER.

Writes OUT/elekloader-<version>-macos.dmg, the file a release offers, and
OUT/SHA256SUMS.txt. First it runs the app's --selftest, signed as it ships,
and checks that the app carries exactly the cores it was given and knows
every device this source tree does.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import __version__, devices, elemod     # noqa: E402

BUNDLE_ID = 'io.github.irpina.elekloader'


def sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def run(*cmd, **kw):
    print('+ ' + ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def codesign(path, identity, runtime=True):
    """Sign `path` itself (what it contains keeps its own signatures)."""
    extra = ['--timestamp'] + (['--options', 'runtime'] if runtime else [])
    run('codesign', '--force', '--sign', identity, *(extra if identity != '-' else []), path)


def notarize(path, auth):
    """Have Apple notarize `path` (a .zip or .dmg) and wait; exit with Apple's log if refused."""
    print('notarizing %s' % os.path.basename(path), flush=True)
    p = subprocess.run(['xcrun', 'notarytool', 'submit', path, '--wait', '--timeout', '1h',
                        '--output-format', 'json'] + auth, capture_output=True, text=True)
    try:
        r = json.loads(p.stdout)
    except ValueError:
        r = {}
    print('notarytool: %s %s' % (r.get('id'), r.get('status')), flush=True)
    if r.get('status') != 'Accepted':
        if r.get('id'):
            subprocess.run(['xcrun', 'notarytool', 'log', r['id']] + auth)
        sys.exit('notarizing %s failed: %s%s' % (path, p.stdout, p.stderr))


def staple(path):
    run('xcrun', 'stapler', 'staple', path)
    run('xcrun', 'stapler', 'validate', path)


def make_dmg(app, dmg, volname, work):
    """A compressed disk image with the app and a link to /Applications to drag it to."""
    stage = os.path.join(work, 'dmg')
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run('ditto', app, os.path.join(stage, os.path.basename(app)))
    os.symlink('/Applications', os.path.join(stage, 'Applications'))
    for attempt in range(3):                # hdiutil is sometimes "busy" on CI machines
        try:
            run('hdiutil', 'create', '-volname', volname, '-srcfolder', stage, '-fs', 'HFS+',
                '-format', 'UDZO', '-ov', dmg)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(10)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', required=True, nargs='+',
                    help='the core .elemod files to build in, one per device and OS')
    ap.add_argument('--identity', help='the Developer ID Application identity to sign with '
                    '(default: ad hoc, not for a release)')
    ap.add_argument('--notarize', action='store_true',
                    help='notarize and staple (needs --identity, and NOTARY_KEY, NOTARY_KEY_ID '
                         'and NOTARY_ISSUER)')
    ap.add_argument('--arch', default='universal2', choices=['universal2', 'arm64', 'x86_64'],
                    help='what the app runs on (default: universal2, both)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'), help='where the .dmg goes')
    a = ap.parse_args(argv)
    if sys.platform != 'darwin':
        sys.exit('build_macos.py builds a macOS app: run it on macOS')
    auth = []
    if a.notarize:
        env = {k: os.environ.get(k) for k in ('NOTARY_KEY', 'NOTARY_KEY_ID', 'NOTARY_ISSUER')}
        if not a.identity or not all(env.values()):
            sys.exit('--notarize needs --identity, and NOTARY_KEY, NOTARY_KEY_ID and '
                     'NOTARY_ISSUER set')
        auth = ['--key', env['NOTARY_KEY'], '--key-id', env['NOTARY_KEY_ID'],
                '--issuer', env['NOTARY_ISSUER']]
    identity = a.identity or '-'
    cores = {}
    for path in a.core:
        core = elemod.load_any(path)
        if core.id != 'core':
            sys.exit('%s is %s, not the core mod' % (path, core.id))
        name = os.path.basename(path)
        if name in cores:
            sys.exit('two cores named %s: give each device and OS its own file name' % name)
        if any(c.dev.key == core.dev.key and c.rel == core.rel for c in cores.values()):
            sys.exit('%s: a second core for the %s %s' % (path, core.dev.name, core.rel.version))
        cores[name] = core

    build = os.path.join(ROOT, 'build', 'macos')
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(os.path.join(build, 'bundled'))
    data = []
    for path, name in zip(a.core, cores):
        shutil.copyfile(path, os.path.join(build, 'bundled', name))
        data += ['--add-data', os.path.join(build, 'bundled', name) + os.pathsep
                 + 'elekloader/bundled']
    # PyInstaller signs every binary it collects, then the bundle (ad hoc without an identity)
    sign = ['--codesign-identity', a.identity] if a.identity else []
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                    '--windowed', '--name', 'elekloader', '--target-arch', a.arch,
                    '--osx-bundle-identifier', BUNDLE_ID] + sign
                   + ['--distpath', os.path.join(build, 'dist'),
                      '--workpath', os.path.join(build, 'work'),
                      '--specpath', build, '--paths', ROOT,
                      '--collect-submodules', 'elekloader'] + data
                   + [os.path.join(HERE, 'elekloader_main.py')], check=True)
    app = os.path.join(build, 'dist', 'elekloader.app')
    exe = os.path.join(app, 'Contents', 'MacOS', 'elekloader')

    # The version Finder shows. The bundle's signature covers Info.plist: sign it again
    plist = os.path.join(app, 'Contents', 'Info.plist')
    with open(plist, 'rb') as fh:
        info = plistlib.load(fh)
    info.update(CFBundleShortVersionString=__version__, CFBundleVersion=__version__)
    with open(plist, 'wb') as fh:
        plistlib.dump(info, fh)
    codesign(app, identity)
    run('codesign', '--verify', '--deep', '--strict', '--verbose=2', app)
    archs = subprocess.run(['lipo', '-archs', exe], capture_output=True, text=True,
                           check=True).stdout.split()
    if sorted(archs) != sorted({'universal2': ['arm64', 'x86_64']}.get(a.arch, [a.arch])):
        sys.exit('the app is built for %s, not %s' % (' and '.join(archs), a.arch))

    report = os.path.join(build, 'selftest.json')
    subprocess.run([exe, '--selftest', report], check=True, timeout=120)
    with open(report) as fh:
        st = json.load(fh)
    want = sorted(({'file': n, 'id': 'core', 'version': c.version, 'sha256': c.sha256}
                   for n, c in cores.items()), key=lambda x: x['file'])
    if (st.get('version') != __version__ or not st.get('frozen')
            or sorted(st.get('bundled') or [], key=lambda x: x['file']) != want
            or sorted(st.get('listed') or []) != sorted(cores) or not st.get('tk')
            or st.get('supported') != devices.supported()):
        sys.exit('the app\'s self-test does not match: %s' % json.dumps(st))
    print('self-test: elekloader %s, frozen, %s, Tk %s, supports %s; built in and listed: %s'
          % (st['version'], ' and '.join(archs), st['tk'], st['supported'],
             ', '.join('%s %s' % (n, c.sha256[:16]) for n, c in sorted(cores.items()))))

    name = 'elekloader-%s-macos.dmg' % __version__
    dmg = os.path.join(build, name)
    if a.notarize:
        # The app's own ticket, stapled, so it opens offline once copied out of the .dmg
        zipped = os.path.join(build, 'elekloader.zip')
        run('ditto', '-c', '-k', '--keepParent', app, zipped)
        notarize(zipped, auth)
        staple(app)
    make_dmg(app, dmg, 'elekloader %s' % __version__, build)
    if a.identity:
        codesign(dmg, identity, runtime=False)
    if a.notarize:
        notarize(dmg, auth)
        staple(dmg)
        run('spctl', '--assess', '--type', 'execute', '--verbose=2', app)
        run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature',
            '--verbose=2', dmg)
    elif not a.identity:
        print('signed ad hoc: for trying on this Mac, not for a release')

    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, name)
    shutil.copyfile(dmg, out)
    with open(os.path.join(a.out, 'SHA256SUMS.txt'), 'w', newline='\n') as fh:
        fh.write('%s  %s\n' % (sha(out), name))
    print('wrote %s (%d bytes)' % (out, os.path.getsize(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
