# SPDX-License-Identifier: GPL-2.0-or-later
"""Build elekloader's Windows app: one elekloader.exe with the core mod built in.

    python packaging/build_windows.py --core core-2.0a.elemod [--out dist]

Needs Windows and PyInstaller (packaging/requirements-build.txt). The core
.elemod is given, not built here: building it needs the stock OS file
(python -m elekloader.sdk.build mods/core --stock ...), which no build
machine may hold. The release workflow takes it from the release it builds
for.

Writes OUT/elekloader-<version>-windows.exe, the file a release offers, and
OUT/SHA256SUMS.txt. First it runs the exe's --selftest and checks that the
exe carries exactly the core it was given and knows every device this
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
    ap.add_argument('--core', required=True, help='the core .elemod to build in')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'), help='where the exe goes')
    a = ap.parse_args(argv)
    if sys.platform != 'win32':
        sys.exit('build_windows.py builds a Windows exe: run it on Windows')
    core = elemod.load_any(a.core)
    if core.id != 'core':
        sys.exit('%s is %s, not the core mod' % (a.core, core.id))
    core_file = os.path.basename(a.core)

    build = os.path.join(ROOT, 'build', 'windows')
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(os.path.join(build, 'bundled'))
    shutil.copyfile(a.core, os.path.join(build, 'bundled', core_file))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--windowed', '--name', 'elekloader',
                    '--distpath', os.path.join(build, 'dist'),
                    '--workpath', os.path.join(build, 'work'),
                    '--specpath', build, '--paths', ROOT,
                    '--collect-submodules', 'elekloader',
                    '--add-data', os.path.join(build, 'bundled', core_file) + os.pathsep
                    + 'elekloader/bundled',
                    os.path.join(HERE, 'elekloader_main.py')], check=True)
    exe = os.path.join(build, 'dist', 'elekloader.exe')

    report = os.path.join(build, 'selftest.json')
    subprocess.run([exe, '--selftest', report], check=True, timeout=120)
    with open(report) as fh:
        st = json.load(fh)
    want = [{'file': core_file, 'id': 'core', 'version': core.version, 'sha256': core.sha256}]
    if (st.get('version') != __version__ or not st.get('frozen') or st.get('bundled') != want
            or st.get('listed') != [core_file] or not st.get('tk')
            or st.get('supported') != devices.supported()):
        sys.exit('the exe\'s self-test does not match: %s' % json.dumps(st))
    print('self-test: elekloader %s, frozen, Tk %s, built in and listed: %s %s; supports %s'
          % (st['version'], st['tk'], core_file, core.sha256[:16], st['supported']))

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
