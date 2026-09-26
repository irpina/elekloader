"""Build elekloader's Windows app: one elekloader.exe with the core mod built in.

    python packaging/build_windows.py --core core-2.0a.elemod [--out dist]

Needs Windows and PyInstaller (packaging/requirements-build.txt). The core
.elemod is given, not built here: building it needs the stock OS file
(python -m elekloader.sdk.build mods/core --stock ...), which no build
machine may hold. The release workflow takes it from the release it builds
for.

Writes OUT/elekloader-<version>-windows.zip (elekloader.exe and README.txt)
and OUT/SHA256SUMS.txt. Before zipping, it runs the exe's --selftest and
checks that the exe carries exactly the core it was given.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import __version__, elemod     # noqa: E402

README = """elekloader {version} for Windows
============================

A mod loader for Elektron firmware: pick mods, give it the stock OS file
Elektron publishes for your device, and it builds a custom OS file on this
computer. Flash that the way you flash any OS update.

Run elekloader.exe. Nothing to install; your mods, profiles and the stock
file you chose are kept in %APPDATA%\\elekloader.

Built in: the core mod ({core}), which every linkable mod needs. It is
listed in the window and ticked for you with any mod that requires it.

1. Change stock firmware... : choose the stock OS file (for the Digitakt
   mk1: Digitakt_OS1.53.syx, from Elektron's Digitakt downloads).
2. + Install from file... : add the .elemod files of the mods you want.
3. Tick them. The check below the list says when they combine.
4. OS version shown: 4 characters the unit will show as its OS version.
5. BUILD FIRMWARE: save the .syx. It is verified before it is written.

Recovery: the bootloader is never changed, so the stock OS file always
restores the unit. On the Digitakt mk1, hold FUNC while powering on for the
startup menu.

The exe is not signed: Windows may say it protected your PC. Choose "More
info", then "Run anyway".

https://github.com/irpina/elekloader (GPL-2.0). Not affiliated with Elektron.
"""


def sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', required=True, help='the core .elemod to build in')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'), help='where the zip goes')
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
            or st.get('listed') != [core_file] or not st.get('tk')):
        sys.exit('the exe\'s self-test does not match: %s' % json.dumps(st))
    print('self-test: elekloader %s, frozen, Tk %s, built in and listed: %s %s'
          % (st['version'], st['tk'], core_file, core.sha256[:16]))

    os.makedirs(a.out, exist_ok=True)
    name = 'elekloader-%s-windows.zip' % __version__
    zpath = os.path.join(a.out, name)
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(exe, 'elekloader/elekloader.exe')
        z.writestr('elekloader/README.txt',
                   README.format(version=__version__, core=core_file).replace('\n', '\r\n'))
    with open(os.path.join(a.out, 'SHA256SUMS.txt'), 'w', newline='\n') as fh:
        fh.write('%s  %s\n' % (sha(zpath), name))
        fh.write('%s  elekloader.exe (inside the zip)\n' % sha(exe))
    print('wrote %s (%d bytes)' % (zpath, os.path.getsize(zpath)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
