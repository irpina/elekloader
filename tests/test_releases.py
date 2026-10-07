# SPDX-License-Identifier: GPL-2.0-or-later
"""Every stock release the device profiles know, and the cores built for it
(pytest, or run with python).

Needs a folder of stock OS files (Elektron's .syx, .bin or .zip, any names),
which never go in the repo:
  ELEKLOADER_RELEASES   e.g. a folder with Digitakt_OS1.53.syx, Digitakt_OS1.54.syx,
                        Digitone_and_Digitone_Keys_OS1.43.syx and ...OS1.44.syx
Each file is known by its hash. A release with no file there is skipped,
not passed, and named. Building the cores also needs the device's cross
toolchain.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, formats, lint, syx      # noqa: E402
from elekloader.elemod import sha                       # noqa: E402
from elekloader.sdk import build                        # noqa: E402

DIR = os.environ.get('ELEKLOADER_RELEASES', '')


class Skip(Exception):
    pass


_files = {}


def files():
    """-> {(device key, version): (path, raw bytes)} for the files in DIR."""
    if not DIR or not os.path.isdir(DIR):
        raise Skip('missing ELEKLOADER_RELEASES')
    if not _files:
        for n in sorted(os.listdir(DIR)):
            p = os.path.join(DIR, n)
            if not os.path.isfile(p) or not n.lower().endswith(('.syx', '.bin', '.zip')):
                continue
            try:
                st, dev, rel = formats.load(p)
            except (devices.UnknownFirmware, formats.FormatError):
                continue
            _files.setdefault((dev.key, rel.version), (p, st.raw))
    return _files


def each_release():
    """-> [(dev, rel, path, raw)] for the known releases with a file; names the rest."""
    have = files()
    out, missing = [], []
    for d in devices.devices():
        for v, r in d.releases.items():
            if (d.key, v) in have:
                out.append((d, r) + have[(d.key, v)])
            else:
                missing.append('%s %s' % (d.name, v))
    if missing:
        print('        (no file for %s)' % ', '.join(missing))
    if not out:
        raise Skip('no known release in %s' % DIR)
    return out


def test_each_release_parses_and_rebuilds_byte_for_byte():
    for dev, rel, path, raw in each_release():
        st = formats.parse(raw, dev)
        img = formats.main_image(st, dev)
        assert len(img) == rel.main_len and sha(img) == rel.main_sha256, (dev.key, rel.version)
        outputs = formats.write(st, st.stored[dev.main_section], dev)
        assert raw in outputs.values(), '%s %s: the writer does not reproduce %s' % (
            dev.key, rel.version, os.path.basename(path))
        formats.verify(outputs, st, img, dev)
        if dev.container == 'ele3' and dev.stage is not None:
            out, gap = syx.inplace_depack(st.stored[dev.main_section], dev)
            assert out == img and gap > 0, (dev.key, rel.version, gap)


def test_releases_of_a_device_differ_only_in_the_main_os():
    """What lets one profile serve every release: the rest of the file is the
    same bytes (the version string's section aside)."""
    by_dev = {}
    for dev, rel, path, raw in each_release():
        if dev.container == 'ele3':
            by_dev.setdefault(dev.key, []).append((dev, formats.parse(raw, dev)))
    pairs = [(v[0], v[i]) for v in by_dev.values() for i in range(1, len(v))]
    if not pairs:
        raise Skip('no device with two releases in %s' % DIR)
    for (dev, a), (_d, b) in pairs:
        assert [t[0] for t in a.table] == [t[0] for t in b.table]
        for sid in a.stored:
            if sid not in (dev.main_section, 5):            # 5: the version string
                assert a.stored[sid] == b.stored[sid], (dev.key, sid)


def mod_dirs(dev, rel):
    """The mods/ folders whose mod.json builds for this release (its os, or a
    port): (the cores, the others: companions such as machine-pages)."""
    cores, others = [], []
    for n in sorted(os.listdir(os.path.join(ROOT, 'mods'))):
        p = os.path.join(ROOT, 'mods', n, 'mod.json')
        if os.path.exists(p):
            with open(p) as fh:
                j = json.load(fh)
            if j.get('device') == dev.key and rel.version in [j.get('os')] + list(j.get('ports', {})):
                (cores if j.get('id') == 'core' else others).append(os.path.join(ROOT, 'mods', n))
    return cores, others


def test_each_core_builds_and_lints_for_each_release_it_names():
    """Each core alone, and each companion in mods/ with the core built for
    its release."""
    built = 0
    for dev, rel, path, raw in each_release():
        cores, others = mod_dirs(dev, rel)
        if not cores:
            continue
        tc = dev.toolchain
        if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc.get('prefix', '')) + 'as'):
            raise Skip('no cross assembler for the %s' % dev.name)
        with tempfile.TemporaryDirectory() as tmp:
            core = None
            for d in cores + others:
                out, m = build.build(d, path, tmp)
                with open(out) as fh:
                    doc = json.load(fh)
                assert doc['target'] == devices.target_of(dev, rel)
                with open(os.path.join(d, 'mod.json')) as fh:
                    primary = json.load(fh).get('os') == rel.version
                assert os.path.basename(out) == '%s-%s%s.elemod' % (
                    m.id, m.version, '' if primary else '-os' + rel.version)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = lint.main([out, '--stock', path, '--json']
                                   + (['--with', core] if m.id != 'core' else []))
                r = json.loads(buf.getvalue())
                assert rc == 0, (d, rel.version, r['problems'])
                if m.id == 'core':
                    core = out
                built += 1
    if not built:
        raise Skip('no core names a release in %s' % DIR)


if __name__ == '__main__':
    import traceback
    ok = skipped = failed = 0
    for n in sorted(k for k in globals() if k.startswith('test_')):
        try:
            globals()[n]()
            print('ok      %s' % n)
            ok += 1
        except Skip as e:
            print('SKIP    %s (%s)' % (n, e))
            skipped += 1
        except Exception:
            print('FAIL    %s' % n)
            traceback.print_exc()
            failed += 1
    print('%d passed, %d failed, %d skipped' % (ok, failed, skipped))
    sys.exit(1 if failed else 0)
