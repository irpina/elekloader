# SPDX-License-Identifier: GPL-2.0-or-later
"""Build elekloader's Windows app: one elekloader.exe with the core mods built in.

    python packaging/build_windows.py --core core-2.0a.elemod [core-dn1-2.0a.elemod ...] [--out dist]

Needs Windows and PyInstaller (packaging/requirements-build.txt). The core
.elemod files (one per device with linkable mods) are given, not built
here: building one needs the device's stock OS file (python -m
elekloader.sdk.build mods/core --stock ...), which no build machine may
hold. The release workflow takes them from the release it builds for.

Writes OUT/elekloader-<version>-windows.exe, the file a release offers, and
OUT/SHA256SUMS.txt. First it runs the exe's --selftest and checks that the
exe carries exactly the cores it was given and knows every device this
source tree does.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import __version__, devices, elemod     # noqa: E402


def sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', required=True, nargs='+',
                    help='the core .elemod files to build in, one per device')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'), help='where the exe goes')
    a = ap.parse_args(argv)
    if sys.platform != 'win32':
        sys.exit('build_windows.py builds a Windows exe: run it on Windows')
    cores = {}
    for path in a.core:
        core = elemod.load_any(path)
        if core.id != 'core':
            sys.exit('%s is %s, not the core mod' % (path, core.id))
        name = os.path.basename(path)
        if name in cores:
            sys.exit('two cores named %s: give each device\'s its own file name' % name)
        if any(c.dev.key == core.dev.key for c in cores.values()):
            sys.exit('%s: a second core for the %s' % (path, core.dev.name))
        cores[name] = core

    build = os.path.join(ROOT, 'build', 'windows')
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(os.path.join(build, 'bundled'))
    data = []
    for path, name in zip(a.core, cores):
        shutil.copyfile(path, os.path.join(build, 'bundled', name))
        data += ['--add-data', os.path.join(build, 'bundled', name) + os.pathsep
                 + 'elekloader/bundled']
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--windowed', '--name', 'elekloader',
                    '--distpath', os.path.join(build, 'dist'),
                    '--workpath', os.path.join(build, 'work'),
                    '--specpath', build, '--paths', ROOT,
                    '--collect-submodules', 'elekloader'] + data
                   + [os.path.join(HERE, 'elekloader_main.py')], check=True)
    exe = os.path.join(build, 'dist', 'elekloader.exe')

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
        sys.exit('the exe\'s self-test does not match: %s' % json.dumps(st))
    print('self-test: elekloader %s, frozen, Tk %s, supports %s; built in and listed: %s'
          % (st['version'], st['tk'], st['supported'],
             ', '.join('%s %s' % (n, c.sha256[:16]) for n, c in sorted(cores.items()))))

    os.makedirs(a.out, exist_ok=True)
    name = 'elekloader-%s-windows.exe' % __version__
    out = os.path.join(a.out, name)
    shutil.copyfile(exe, out)
    with open(os.path.join(a.out, 'SHA256SUMS.txt'), 'w', newline='\n') as fh:
        fh.write('%s  %s\n' % (sha(out), name))
    print('wrote %s (%d bytes)' % (out, os.path.getsize(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
