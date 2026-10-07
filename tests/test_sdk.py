# SPDX-License-Identifier: GPL-2.0-or-later
"""The mod author's tools: sdk.build and lint (pytest, or run with python).

Needs files named by environment variables; a test whose inputs are
missing is skipped, not passed:
  ELEKLOADER_STOCK      the stock Digitakt_OS1.53.syx
  ELEKLOADER_STOCK_154  optional: Digitakt_OS1.54.syx, for the ports to 1.54
  ELEKLOADER_MODS       optional: a folder with the core mod (core-*.elemod or
                        .dtmod); without one, mods/core is built
  ELEKLOADER_CORE_21    optional: the released core-2.1.elemod (v0.4.0), with
                        core-2.1-os1.54.elemod beside it: core 3.0 must keep
                        all of it
  ELEKLOADER_DN_SYX, ELEKLOADER_DN_SYX_144  optional: the Digitone's 1.43
                        and 1.44 files, for mods/core-dn1 and its port
  ELEKLOADER_CORE_DN1_23  optional: the released core-dn1-2.3.elemod (the
                        core-dn1-v2.3 pre-release), with
                        core-dn1-2.3-os1.44.elemod beside it: core-dn1 3.0
                        must keep all of it
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

from elekloader import devices, elemod, formats, lint, link        # noqa: E402
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


FW = ['fw_active_track', 'fw_amp_env', 'fw_bitmap_vt', 'fw_blit', 'fw_fillrect', 'fw_font5',
      'fw_framerect', 'fw_kit', 'fw_op_new', 'fw_pitch_tab', 'fw_render_machine', 'fw_set_param',
      'fw_slice_layout', 'fw_textf', 'fw_track_blocks', 'fw_voice_note', 'fw_voice_params',
      'fw_voice_start', 'fw_voice_vel']


def test_core_builds_and_lints():
    """core 3.0: the hook bus (core.s, 8 sites), the SRC machine slots
    (machines.s, Digitakt mk1 only: 31 sites and the table core_machines),
    the machine page reader (core_machine_ui) and the firmware locations
    (fw.s: absolute exports, no site)."""
    path = built_core()
    with open(path) as fh:
        doc = json.load(fh)
    assert doc['id'] == 'core' and doc['version'] == '3.0'
    assert '.boot' in doc['sections'] and len(doc['sites']) == 39
    assert sorted(doc['collections']) == sorted(HOOK_BUS + ['core_machines'])
    assert set(FW + ['core_machine', 'core_machine_ui']) <= set(doc['exports'])
    assert all(doc['symbols'][x][0] == 'abs' for x in FW)
    rc, r = lint_json(path, '--stock', stock())
    assert rc == 0 and r['link']['order'][0].startswith('core')


CORE_21 = os.environ.get('ELEKLOADER_CORE_21', '')


def check_superset(old_path, new_path, st):
    """Core 3.0 is core 2.1 and more: the same sites with the same bytes, the
    same tables, every 2.1 symbol where 2.1 has it, 2.1's .run at the start of
    3.0's and the same .bss."""
    with open(old_path) as fh:
        old = json.load(fh)
    with open(new_path) as fh:
        new = json.load(fh)
    assert old['version'] == '2.1' and new['version'] == '3.0'
    assert old['target'] == new['target']
    assert new['sites'] == old['sites'] and new['collections'] == old['collections']
    assert new['contribute'] == old['contribute'] and new['resources'] == old['resources']
    assert set(old['exports']) <= set(new['exports'])
    assert all(new['symbols'][k] == v for k, v in old['symbols'].items())
    assert old['sections']['.bss'] == new['sections']['.bss']
    stock_, dev, _rel = formats.load(st)
    image = formats.main_image(stock_, dev)
    m_old, m_new = link.Mod2(old, 'old'), link.Mod2(new, 'new')
    run_old = elemod.parts_bytes(m_old.sections['.run']['parts'], image, dev)
    run_new = elemod.parts_bytes(m_new.sections['.run']['parts'], image, dev)
    assert run_new[:len(run_old)] == run_old and len(run_new) > len(run_old)
    assert [r for r in new['relocs'] if r[1] < len(run_old) or r[0] != '.run'] == old['relocs']


def test_core_3_is_core_2_1_and_more():
    if not CORE_21 or not os.path.exists(CORE_21):
        raise Skip('missing ELEKLOADER_CORE_21 (the released core-2.1.elemod)')
    check_superset(CORE_21, built_core(), stock())
    other = CORE_21.replace('core-2.1.elemod', 'core-2.1-os1.54.elemod')
    if STOCK_154 and os.path.exists(STOCK_154) and os.path.exists(other):
        with tempfile.TemporaryDirectory() as tmp:
            path, _m = build.build(os.path.join(ROOT, 'mods', 'core'), STOCK_154, tmp)
            check_superset(other, path, STOCK_154)


def test_core_too_old_is_said_plainly():
    """A mod whose resources.core asks for 3.0 is refused beside an older core
    with that, and not with the imports that follow from it."""
    if not CORE_21 or not os.path.exists(CORE_21):
        raise Skip('missing ELEKLOADER_CORE_21 (the released core-2.1.elemod)')
    with tempfile.TemporaryDirectory() as tmp:
        d = data_only_mod(tmp)
        with open(os.path.join(d, 'mod.json')) as fh:
            j = json.load(fh)
        j['resources'] = {'core': '3.0'}
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump(j, fh)
        path, m = build.build(d, stock())
        assert m.needs_core == '3.0'
        rc, r = lint_json(path, '--stock', stock(), '--with', CORE_21)
        assert rc == 1 and r['problems'] == [
            'grid-max 0.1 needs core 3.0 or newer, and this build has core 2.1'], r['problems']
        rc, r = lint_json(path, '--stock', stock(), '--with', built_core())
        assert rc == 0, r['problems']


C_MACHINE = r'''
#include "digitakt-mk1/core3.h"
static int32_t pg_text(char *buf, int32_t v, int32_t ctx, int32_t machine)
{
    buf[0] = (char)('0' + ((v >> 8) & 7)); buf[1] = ctx ? '!' : 0; buf[2] = 0;
    (void)machine;
    return 1;
}
static const struct cm_ui pg_page = {
    .abi = cm_ui_v3, .page_from = 3,
    .knob = { [1] = { .flags = CM_HIDDEN },
              [4] = { .name = "SEVN", .lname = "Seven", .flags = CM_RANGE, .max = 7 << 8, .fmt = pg_text },
              [5] = { .look = 0x86 } },
};
const struct cm_machine pg_machine = { 30, "PAGETEST", "PGT", 0, 3, 3, CM_UI_TAG, &pg_page };
void pg_render(int32_t *blocks) { blocks[32 * fw_active_track] = fw_voice_params[0]; }
'''


def machine_pages(st, tmp):
    return build.build(os.path.join(ROOT, 'mods', 'machine-pages'), st, tmp)[0]


def test_a_machine_in_c_describes_its_page():
    """A machine written against digitakt-mk1/core3.h, with mod.json's
    "machines": it links with core 3.0 and machine-pages, and names only
    core's and machine-pages' symbols, so its 1.54 port is empty."""
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'pagetest')
        os.makedirs(d)
        with open(os.path.join(d, 'pagetest.c'), 'w') as fh:
            fh.write(C_MACHINE)
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump({'id': 'pagetest', 'version': '1.0', 'device': 'digitakt-mk1', 'os': '1.53',
                       'sources': ['pagetest.c'], 'ports': {'1.54': {}},
                       'machines': [{'id': 30, 'descriptor': 'pg_machine'}],
                       'subscribe': [{'event': 'ev_render_voices', 'fn': 'pg_render', 'order': 30}],
                       'requires': ['core', 'machine-pages'], 'resources': {'core': '3.0'}}, fh)
        path, m = build.build(d, stock(), tmp)
        assert m.needs_core == '3.0' and m.names == ['machine:30'] and not m.sites
        assert sorted(c['to'] for c in m.contribute) == ['core_machines', 'ev_render_voices']
        assert set(m.imports) == {'cm_ui_v3', 'fw_active_track', 'fw_voice_params'}
        mp = machine_pages(stock(), tmp)
        rc, r = lint_json(path, '--stock', stock(), '--with', built_core(), '--with', mp)
        assert rc == 0, r['problems']
        rc, r = lint_json(path, '--stock', stock(), '--with', built_core())
        assert rc == 1 and r['problems'] == ['pagetest 1.0 requires machine-pages'], r['problems']
        if CORE_21 and os.path.exists(CORE_21):
            rc, r = lint_json(path, '--stock', stock(), '--with', CORE_21, '--with', mp)
            assert rc == 1 and set(r['problems']) == {
                'pagetest 1.0 needs core 3.0 or newer, and this build has core 2.1',
                'machine-pages 1.0 needs core 3.0 or newer, and this build has core 2.1'}, r['problems']
        if STOCK_154 and os.path.exists(STOCK_154):
            path4, m4 = build.build(d, STOCK_154, tmp)
            assert path4.endswith('pagetest-1.0-os1.54.elemod')
            with open(path) as fh:
                a = json.load(fh)
            with open(path4) as fh:
                b = json.load(fh)
            def sizes(x):
                return {s: v.get('len', v.get('size')) for s, v in x['sections'].items()}
            assert sizes(a) == sizes(b) and a['relocs'] == b['relocs'] and a['symbols'] == b['symbols']


def test_the_sine_machine_example_builds_for_each_os_unchanged():
    """examples/sine-machine names no firmware address: its 1.54 port is
    empty, and both builds carry the same code."""
    tc = devices.devices()[0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    src = os.path.join(ROOT, 'examples', 'sine-machine')
    with tempfile.TemporaryDirectory() as tmp:
        path, m = build.build(src, stock(), tmp)
        assert not m.sites and m.needs_core == '3.0' and m.names == ['machine:120']
        rc, r = lint_json(path, '--stock', stock(), '--with', built_core(),
                          '--with', machine_pages(stock(), tmp))
        assert rc == 0, r['problems']
        if STOCK_154 and os.path.exists(STOCK_154):
            path4, m4 = build.build(src, STOCK_154, tmp)
            images = []
            for st, mod in ((stock(), m), (STOCK_154, m4)):
                s, dev, _rel = formats.load(st)
                images.append(bytes(elemod.parts_bytes(mod.sections['.run']['parts'],
                                                       formats.main_image(s, dev), dev)))
            assert images[0] == images[1] and m.relocs == m4.relocs


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
        j['sources'] = [os.path.join(src, s) for s in j['sources']]
        src = os.path.join(tmp, 'core-dn1')
        os.makedirs(src)
        with open(os.path.join(src, 'mod.json'), 'w') as fh:
            json.dump(j, fh)
    path, _m = build.build(src, DN_STOCK, tmp)
    return path


def test_digitone_core_builds_and_links():
    """core-dn1 3.0: core 2.1's core.s (the hook bus, without the Digitakt's
    machine slots), voice.s (ev_voice_on), params.s (parameter slots, ids
    182-184), pages.s (mod pages, 27-30), projdata.s (mods' data saved with
    the project), menu.s (the Mod Menu, a grid of icons from 2.3) and fw.s
    (firmware locations as exports, from 3.0), the last six Digitone only."""
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
        assert sorted(dn['build']['sources']) == ['core.s', 'fw.s', 'menu.s', 'pages.s',
                                                  'params.s', 'projdata.s', 'render.s',
                                                  'settings.s', 'voice.s']
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
        assert rc == 0 and r['link']['order'] == ['core 3.0']
        # the firmware locations: absolute symbols, exported
        assert all(dn['symbols'][k][0] == 'abs' and k in dn['exports'] for k in FW_DN)


def test_digitone_core_needs_every_constant():
    """A device constant left out of mod.json is an import nothing provides,
    so the link refuses it, rather than falling back to another device's."""
    with tempfile.TemporaryDirectory() as tmp:
        path = dn_core(tmp, drop='FN_MGR')
        rc, r = lint_json(path, '--stock', DN_STOCK)
        assert rc == 1 and any('FN_MGR' in x for x in r['problems']), r['problems']


CORE_DN23 = os.environ.get('ELEKLOADER_CORE_DN1_23', '')
FW_DN = ['fw_blit', 'fw_ev_alloc', 'fw_ev_free', 'fw_ev_queue', 'fw_fillrect', 'fw_font5',
         'fw_framerect', 'fw_gate_off', 'fw_kit', 'fw_lfo_state', 'fw_lock_alloc', 'fw_locks_free',
         'fw_nodes_free', 'fw_op_new', 'fw_slot_ids', 'fw_str_amp', 'fw_str_empty', 'fw_textf',
         'fw_timeline', 'fw_transpose', 'fw_voice_len', 'fw_voice_params', 'fw_voice_pitch']


def check_dn_superset(old_path, new_path):
    """core-dn1 3.0 is 2.3 and the firmware exports: the same code, sites,
    tables and symbols, and nothing else but exports added."""
    with open(old_path) as fh:
        old = json.load(fh)
    with open(new_path) as fh:
        new = json.load(fh)
    assert old['version'] == '2.3' and new['version'] == '3.0'
    for k in ('target', 'sites', 'collections', 'contribute', 'resources', 'sections', 'relocs'):
        assert new[k] == old[k], k
    assert sorted(set(new['exports']) - set(old['exports'])) == FW_DN
    assert set(old['exports']) <= set(new['exports'])
    assert all(new['symbols'][k] == v for k, v in old['symbols'].items())


def test_digitone_core_3_is_2_3_and_more():
    if not CORE_DN23 or not os.path.exists(CORE_DN23):
        raise Skip('missing ELEKLOADER_CORE_DN1_23 (the released core-dn1-2.3.elemod)')
    with tempfile.TemporaryDirectory() as tmp:
        check_dn_superset(CORE_DN23, dn_core(tmp))
        other = CORE_DN23.replace('core-dn1-2.3.elemod', 'core-dn1-2.3-os1.44.elemod')
        if DN_STOCK_144 and os.path.exists(DN_STOCK_144) and os.path.exists(other):
            path, _m = build.build(os.path.join(ROOT, 'mods', 'core-dn1'), DN_STOCK_144, tmp)
            check_dn_superset(other, path)


C_DN = """
#include "digitone-mk1/core3.h"
static uint32_t dn_when;
void dn_voice_on(int32_t voice, int32_t track, void *event)
{
    fw_voice_pitch[voice] += (uint32_t)FW_VOICE_PARAM(voice, 26) << 8;
    dn_when = fw_timeline;
    (void)track; (void)event;
}
static void dn_open(void *brain, void *event, int32_t track)
{
    (void)brain; (void)event; (void)track;
}
static const uint16_t dn_icon[16] = { 0x8001, 0x4002 };
const struct core_menu_item dn_menu = { "DN TEST", dn_open, CORE_MENU_ICON, dn_icon };
"""


def test_a_digitone_mod_in_c_names_only_core_exports():
    """A Digitone mod written against digitone-mk1/core3.h: it needs core-dn1
    3.0 and names only core's symbols, so its 1.44 port is empty and both
    builds carry the same code; beside core-dn1 2.3 it is refused plainly."""
    if not DN_STOCK or not os.path.exists(DN_STOCK):
        raise Skip('missing ELEKLOADER_DN_SYX')
    tc = [x for x in devices.devices() if x.key == 'digitone-mk1'][0].toolchain
    if not shutil.which(os.environ.get('ELEKLOADER_CROSS', tc['prefix']) + 'gcc'):
        raise Skip('no m68k cross compiler')
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'dntest')
        os.makedirs(d)
        with open(os.path.join(d, 'dntest.c'), 'w') as fh:
            fh.write(C_DN)
        with open(os.path.join(d, 'mod.json'), 'w') as fh:
            json.dump({'id': 'dntest', 'version': '1.0', 'device': 'digitone-mk1', 'os': '1.43',
                       'sources': ['dntest.c'], 'ports': {'1.44': {}},
                       'subscribe': [{'event': 'ev_voice_on', 'fn': 'dn_voice_on', 'order': 50}],
                       'contribute': [{'to': 'core_menu', 'order': 50, 'data': '00000000',
                                       'relocs': [[0, 'abs32', 'sym:dn_menu', 0]]}],
                       'requires': ['core'], 'resources': {'core': '3.0'}}, fh)
        path, m = build.build(d, DN_STOCK, tmp)
        assert m.needs_core == '3.0' and not m.sites
        assert set(m.imports) == {'fw_voice_pitch', 'fw_voice_params', 'fw_timeline'}
        rc, r = lint_json(path, '--stock', DN_STOCK, '--with', dn_core(tmp))
        assert rc == 0, r['problems']
        if CORE_DN23 and os.path.exists(CORE_DN23):
            rc, r = lint_json(path, '--stock', DN_STOCK, '--with', CORE_DN23)
            assert rc == 1 and r['problems'] == [
                'dntest 1.0 needs core 3.0 or newer, and this build has core 2.3'], r['problems']
        if DN_STOCK_144 and os.path.exists(DN_STOCK_144):
            path4, m4 = build.build(d, DN_STOCK_144, tmp)
            assert path4.endswith('dntest-1.0-os1.44.elemod')
            images = []
            for st, mod in ((DN_STOCK, m), (DN_STOCK_144, m4)):
                s, dev, _rel = formats.load(st)
                images.append(bytes(elemod.parts_bytes(mod.sections['.run']['parts'],
                                                       formats.main_image(s, dev), dev)))
            assert images[0] == images[1] and m.relocs == m4.relocs
            core4, _m = build.build(os.path.join(ROOT, 'mods', 'core-dn1'), DN_STOCK_144, tmp)
            rc, r = lint_json(path4, '--stock', DN_STOCK_144, '--with', core4)
            assert rc == 0, r['problems']


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
        assert os.path.basename(path) == 'core-3.0-os1.54.elemod'
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
        assert os.path.basename(path) == 'core-3.0-os1.44.elemod'
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
