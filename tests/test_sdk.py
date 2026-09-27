# SPDX-License-Identifier: GPL-2.0-or-later
"""The mod author's tools: sdk.build and lint (pytest, or run with python).

Needs files named by environment variables; a test whose inputs are
missing is skipped, not passed:
  ELEKLOADER_STOCK   the stock Digitakt_OS1.53.syx
  ELEKLOADER_MODS    optional: a folder with the core mod (core-*.elemod or
                     .dtmod); without one, mods/core is built
Building mods/core or the example also needs the cross toolchain
(m68k-linux-gnu-as, -gcc and -ld).
"""
import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from elekloader import devices, elemod, lint, link        # noqa: E402
from elekloader.sdk import build                           # noqa: E402

STOCK = os.environ.get('ELEKLOADER_STOCK', '')
MODS = os.environ.get('ELEKLOADER_MODS', '')


class Skip(Exception):
    pass


def stock():
    if not STOCK or not os.path.exists(STOCK):
        raise Skip('missing ELEKLOADER_STOCK')
    return STOCK


_BUILT_CORE = []


def built_core():
    """mods/core, built once with the SDK into a temporary folder."""
    if not _BUILT_CORE:
        tc = devices.devices()[0].toolchain
        if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'as'):
            raise Skip('no m68k cross assembler to build mods/core')
        path, _m = build.build(os.path.join(ROOT, 'mods', 'core'), stock(), tempfile.mkdtemp())
        _BUILT_CORE.append(path)
    return _BUILT_CORE[0]


def core():
    paths = elemod.mod_files(MODS) if MODS else []
    paths = [p for p in paths if os.path.basename(p).startswith('core-')]
    return paths[-1] if paths else built_core()


def lint_json(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = lint.main(list(args) + ['--json'])
    return rc, json.loads(out.getvalue())


def data_only_mod(tmp):
    d = os.path.join(tmp, 'grid-max')
    os.makedirs(d)
    with open(os.path.join(d, 'mod.json'), 'w') as fh:
        json.dump({'id': 'grid-max', 'version': '0.1', 'device': 'digitakt-mk1', 'os': '1.53',
                   'sites': [{'addr': '0x401ab9b0', 'stock': '00000400', 'op': 'bytes',
                              'new': '00000500'}],
                   'requires': ['core']}, fh)
    return d


def test_data_only_mod_builds_without_a_toolchain():
    with tempfile.TemporaryDirectory() as tmp:
        path, m = build.build(data_only_mod(tmp), stock())
        assert path.endswith('grid-max-0.1.elemod')
        with open(path) as fh:
            assert json.load(fh)['elemod'] == 2
        assert isinstance(m, link.Mod2) and len(m.sites) == 1 and not m.sections


def test_build_refuses_wrong_stock_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        d = data_only_mod(tmp)
        with open(os.path.join(d, 'mod.json')) as fh:
            j = json.load(fh)
        j['sites'][0]['stock'] = '00000401'
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump(j, fh)
        try:
            build.build(d, stock())
        except build.BuildError as e:
            assert 'stock bytes' in str(e)
        else:
            raise AssertionError('built with the wrong stock bytes')


def test_lint():
    with tempfile.TemporaryDirectory() as tmp:
        path, _m = build.build(data_only_mod(tmp), stock())
        rc, r = lint_json(path)
        assert rc == 0 and r['mods'][0]['id'] == 'grid-max'
        rc, r = lint_json(path, '--stock', stock())
        assert rc == 1 and any('requires core' in x for x in r['problems'])
        rc, r = lint_json(path, '--stock', stock(), '--with', core())
        assert rc == 0 and r['link']['order'][0].startswith('core')
        slicer = [p for p in elemod.mod_files(MODS) if os.path.basename(p).startswith('slicer-')]
        if slicer:
            rc, r = lint_json(path, '--stock', stock(), '--with', core(), '--with', slicer[-1])
            assert rc == 1 and any('overlap' in x for x in r['problems'])


def test_core_builds_and_lints():
    path = built_core()
    with open(path) as fh:
        doc = json.load(fh)
    assert doc['id'] == 'core' and '.boot' in doc['sections'] and len(doc['sites']) == 8
    assert sorted(doc['collections']) == ['ev_draw', 'ev_enc', 'ev_key', 'ev_render_in',
                                          'ev_render_out', 'ev_settings', 'ev_tick']
    rc, r = lint_json(path, '--stock', stock())
    assert rc == 0 and r['link']['order'][0].startswith('core')


def test_example_builds_and_links():
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    with tempfile.TemporaryDirectory() as tmp:
        path, m = build.build(os.path.join(ROOT, 'examples', 'hello-marker'), stock(), tmp)
        assert m.size('.run') > 0 and 'hello_draw' in m.exports
        rc, r = lint_json(path, '--stock', stock(), '--with', core())
        assert rc == 0 and 'hello_draw' in r['link']['addresses']


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
