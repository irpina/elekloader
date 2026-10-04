# SPDX-License-Identifier: GPL-2.0-or-later
"""The mod author's tools: sdk.build and lint (pytest, or run with python).

Needs files named by environment variables; a test whose inputs are
missing is skipped, not passed:
  ELEKLOADER_STOCK      the stock Digitakt_OS1.53.syx
  ELEKLOADER_STOCK_154  optional: Digitakt_OS1.54.syx, for the ports to 1.54
  ELEKLOADER_MODS       optional: a folder with the core mod (core-*.elemod or
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


# The hook bus's events (core.s), which every device's core provides.
HOOK_BUS = ['ev_draw', 'ev_enc', 'ev_key', 'ev_render_in', 'ev_render_out', 'ev_settings',
            'ev_tick']


def test_core_builds_and_lints():
    """core 2.1: the hook bus (core.s, 8 sites) and the SRC machine slots
    (machines.s, Digitakt mk1 only: 31 sites and the table core_machines)."""
    path = built_core()
    with open(path) as fh:
        doc = json.load(fh)
    assert doc['id'] == 'core' and '.boot' in doc['sections'] and len(doc['sites']) == 39
    assert sorted(doc['collections']) == sorted(HOOK_BUS + ['core_machines'])
    rc, r = lint_json(path, '--stock', stock())
    assert rc == 0 and r['link']['order'][0].startswith('core')


DN_STOCK = os.environ.get('ELEKLOADER_DN_SYX', '')


def dn_core(tmp, drop=None):
    """mods/core-dn1 built with the SDK (one defsym left out if `drop`)."""
    if not DN_STOCK or not os.path.exists(DN_STOCK):
        raise Skip('missing ELEKLOADER_DN_SYX')
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'as'):
        raise Skip('no m68k cross assembler to build mods/core-dn1')
    src = os.path.join(ROOT, 'mods', 'core-dn1')
    if drop:
        with open(os.path.join(src, 'mod.json')) as fh:
            j = json.load(fh)
        del j['defsym'][drop]
        j['sources'] = [os.path.join(ROOT, 'mods', 'core', 'core.s')]
        src = os.path.join(tmp, 'core-dn1')
        os.makedirs(src)
        with open(os.path.join(src, 'mod.json'), 'w') as fh:
            json.dump(j, fh)
    path, _m = build.build(src, DN_STOCK, tmp)
    return path


def test_digitone_core_builds_and_links():
    """core-dn1 2.2: core 2.1's core.s (the hook bus, without the Digitakt's
    machine slots), voice.s (ev_voice_on), params.s (parameter slots, ids
    182-184), pages.s (mod pages, 27-30), projdata.s (mods' data saved with
    the project) and menu.s (the Mod Menu), the last five Digitone only."""
    with tempfile.TemporaryDirectory() as tmp:
        path = dn_core(tmp)
        with open(path) as fh:
            dn = json.load(fh)
        with open(built_core()) as fh:
            dt = json.load(fh)
        # 8 hook bus sites, the voice note-on, the parameter slots' 63 (3
        # table moves, 2 UI record lookups and 58 raised id bounds), the mod
        # pages' 2 (the page record lookup and the views' builder) and the
        # project data's 5 (the serializer, two loads, two new projects).
        assert dn['target']['device'] == 'digitone-mk1' and len(dn['sites']) == 79
        assert sorted(dn['collections']) == sorted(
            HOOK_BUS + ['core_menu', 'core_pages', 'core_params', 'core_projdata',
                        'ev_hold', 'ev_voice_on'])
        # The same core.s as core 2.1's, with the Digitone's addresses, and
        # each of its labels where core 2.1 has it.
        assert sorted(dn['build']['sources']) == ['core.s', 'menu.s', 'pages.s', 'params.s',
                                                  'projdata.s', 'voice.s']
        assert dn['build']['sources']['core.s'] == dt['build']['sources']['core.s']
        placed = {k: v for k, v in dn['symbols'].items() if v[0] != 'abs'}
        shared = {k: v for k, v in placed.items() if k in dt['symbols']}
        assert shared == {k: dt['symbols'][k] for k in shared}
        assert {'core_voice_on', 'core_dn_boot', 'core_param_ui', 'core_page_rec',
                'core_view_init', 'core_page_open', 'core_page_shown', 'core_proj_save',
                'core_proj_load', 'core_proj_import', 'core_proj_new',
                'core_proj_init', 'core_dn_key', 'core_dn_enc', 'core_dn_tick',
                'core_dn_draw'} <= set(placed) - set(shared)
        # voice.s follows core.s's code in .run.
        last = max(off for sec, off in shared.values() if sec == '.run')
        assert placed['core_voice_on'][0] == '.run' and placed['core_voice_on'][1] > last
        rc, r = lint_json(path, '--stock', DN_STOCK)
        assert rc == 0 and r['link']['order'] == ['core 2.2']


def test_digitone_core_needs_every_constant():
    """A device constant left out of mod.json is an import nothing provides,
    so the link refuses it, rather than falling back to another device's."""
    with tempfile.TemporaryDirectory() as tmp:
        path = dn_core(tmp, drop='FN_MGR')
        rc, r = lint_json(path, '--stock', DN_STOCK)
        assert rc == 1 and any('FN_MGR' in x for x in r['problems']), r['problems']


def test_example_builds_and_links():
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    with tempfile.TemporaryDirectory() as tmp:
        path, m = build.build(os.path.join(ROOT, 'examples', 'hello-marker'), stock(), tmp)
        assert m.size('.run') > 0 and 'hello_draw' in m.exports
        rc, r = lint_json(path, '--stock', stock(), '--with', core())
        assert rc == 0 and 'hello_draw' in r['link']['addresses']


STOCK_154 = os.environ.get('ELEKLOADER_STOCK_154', '')


def stock_154():
    if not STOCK_154 or not os.path.exists(STOCK_154):
        raise Skip('missing ELEKLOADER_STOCK_154')
    return STOCK_154


def test_core_port_to_154_is_the_same_core():
    """mods/core's 1.54 port: the same code and the same sites, at 1.54's
    addresses; a 1.53 core is refused on 1.54."""
    st154 = stock_154()
    with tempfile.TemporaryDirectory() as tmp:
        path, _m = build.build(os.path.join(ROOT, 'mods', 'core'), st154, tmp)
        assert os.path.basename(path) == 'core-2.1-os1.54.elemod'
        with open(path) as fh:
            new = json.load(fh)
        with open(built_core()) as fh:
            old = json.load(fh)
        assert new['target']['os'] == '1.54' and old['target']['os'] == '1.53'
        for k in ('exports', 'collections', 'contribute', 'resources', 'build'):
            assert new[k] == old[k], k
        def sizes(d):
            return {s: v.get('len', v.get('size')) for s, v in d['sections'].items()}
        assert sizes(new) == sizes(old)

        def what(d):                # each site's new bytes and targets, not where it is
            return [(s['len'], s['kind'], s['new'], s.get('relocs')) for s in d['sites']]
        assert what(new) == what(old)
        rc, r = lint_json(path, '--stock', st154)
        assert rc == 0, r['problems']
        rc, r = lint_json(built_core(), '--stock', st154)
        assert rc == 1 and any('1.53' in x and '1.54' in x for x in r['problems']), r['problems']


def test_example_port_to_154_builds_and_links():
    st154 = stock_154()
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    with tempfile.TemporaryDirectory() as tmp:
        c, _m = build.build(os.path.join(ROOT, 'mods', 'core'), st154, tmp)
        path, m = build.build(os.path.join(ROOT, 'examples', 'hello-marker'), st154, tmp)
        assert path.endswith('hello-marker-1.0-os1.54.elemod') and 'hello_draw' in m.exports
        rc, r = lint_json(path, '--stock', st154, '--with', c)
        assert rc == 0 and 'hello_draw' in r['link']['addresses']


DN_STOCK_144 = os.environ.get('ELEKLOADER_DN_SYX_144', '')


def test_digitone_core_port_to_144_is_the_same_core():
    """mods/core-dn1's 1.44 port: the same code and the same sites, at 1.44's
    addresses; a 1.43 core-dn1 is refused on 1.44."""
    if not DN_STOCK_144 or not os.path.exists(DN_STOCK_144):
        raise Skip('missing ELEKLOADER_DN_SYX_144')
    with tempfile.TemporaryDirectory() as tmp:
        old_path = dn_core(tmp)
        path, _m = build.build(os.path.join(ROOT, 'mods', 'core-dn1'), DN_STOCK_144, tmp)
        assert os.path.basename(path) == 'core-2.2-os1.44.elemod'
        with open(path) as fh:
            new = json.load(fh)
        with open(old_path) as fh:
            old = json.load(fh)
        assert new['target']['os'] == '1.44' and old['target']['os'] == '1.43'
        for k in ('exports', 'collections', 'contribute', 'resources', 'build'):
            assert new[k] == old[k], k
        def sizes(d):
            return {s: v.get('len', v.get('size')) for s, v in d['sections'].items()}
        assert sizes(new) == sizes(old)

        def what(d):                # each site's new bytes and targets, not where it is
            return [(s['len'], s['kind'], s['new'], s.get('relocs')) for s in d['sites']]
        assert len(new['sites']) == 79 and what(new) == what(old)
        rc, r = lint_json(path, '--stock', DN_STOCK_144)
        assert rc == 0, r['problems']
        rc, r = lint_json(old_path, '--stock', DN_STOCK_144)
        assert rc == 1 and any('1.43' in x and '1.44' in x for x in r['problems']), r['problems']


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
