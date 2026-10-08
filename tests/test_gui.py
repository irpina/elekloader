# SPDX-License-Identifier: GPL-2.0-or-later
"""The window's first run, with its file dialogs scripted (pytest, or run with
python). A hidden Tk window: it needs Tk, and the files, named by environment
variables; a test whose inputs are missing is skipped, not passed:
  ELEKLOADER_STOCK      Digitakt_OS1.53.syx
  ELEKLOADER_STOCK_154  Digitakt_OS1.54.syx
  ELEKLOADER_OT_SYX     OCTATRACK_OS1.40C.syx
  ELEKLOADER_MODS       a folder with core-*.elemod (the cores the Windows app builds
                        in): core-2.1.elemod (1.53), core-2.1-os1.54.elemod (1.54)
  ELEKLOADER_DN_SYX, ELEKLOADER_DN_MODS   the Digitone's stock file, and its cores
"""
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from elekloader import gui           # noqa: E402

STOCK = os.environ.get('ELEKLOADER_STOCK', '')
OT_SYX = os.environ.get('ELEKLOADER_OT_SYX', '')
MODS = os.environ.get('ELEKLOADER_MODS', '')


class Skip(Exception):
    pass


def need(p, what):
    if not p or not os.path.exists(p):
        raise Skip('missing %s' % what)
    return p


def first_run(stock_answers, tmp):
    """A first run (no settings) with core built in; the file dialog returns
    `stock_answers` in turn, then cancels. -> the window, still open."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        root = tk.Tk()
    except Exception as e:                       # no display, no Tk
        raise Skip('no Tk: %s' % e)
    cores = sorted(glob.glob(os.path.join(need(MODS, 'ELEKLOADER_MODS'), 'core-*.*mod')))
    if not cores:
        raise Skip('no core-*.elemod in ELEKLOADER_MODS')
    bundled = os.path.join(tmp, 'bundled')
    os.makedirs(bundled)
    shutil.copy(cores[-1], bundled)
    answers = list(stock_answers)
    asked = []
    saved = filedialog.askopenfilename, messagebox.askretrycancel
    filedialog.askopenfilename = lambda **kw: asked.append(kw) or (answers.pop(0) if answers else '')
    messagebox.askretrycancel = lambda *a, **kw: True
    try:
        root.withdraw()
        w = gui.LoaderWindow(root, gui.LoaderModel(None, os.path.join(tmp, 'lib'), [bundled],
                                                   os.path.join(tmp, 'settings.json')))
        t = time.time()
        while time.time() - t < 2.0:
            root.update()
            time.sleep(0.02)
    finally:
        filedialog.askopenfilename, messagebox.askretrycancel = saved
    w.asked = asked
    return w


def rows(w):
    return [(w.descs[i]['id'], w.tree.item(i, 'values')[0] == gui.BOX_ON)
            for i in w.tree.get_children()]


def test_the_first_run_asks_for_the_stock_file_and_filters_by_it():
    need(OT_SYX, 'ELEKLOADER_OT_SYX')
    with tempfile.TemporaryDirectory() as tmp:
        junk = os.path.join(tmp, 'notes.txt')
        with open(junk, 'w') as fh:
            fh.write('not firmware')
        w = first_run([junk, OT_SYX], tmp)
        try:
            assert len(w.asked) == 2                     # asked, refused, asked again
            assert w.model.stock['ok'] and w.model.dev.key == 'octatrack'
            assert rows(w) == [] and w.hidden == 1        # the Digitakt core: hidden, not ticked
            assert not w.enabled
            with open(os.path.join(tmp, 'settings.json')) as fh:
                assert json.load(fh)['stock'] == OT_SYX
        finally:
            w.win.destroy()


def test_the_first_run_on_a_digitakt_lists_core_unticked():
    need(STOCK, 'ELEKLOADER_STOCK')
    with tempfile.TemporaryDirectory() as tmp:
        buf = io.BytesIO()                               # the stock file in a zip, as downloaded
        with zipfile.ZipFile(buf, 'w') as z:
            z.write(STOCK, 'Digitakt_OS1.53/' + os.path.basename(STOCK))
        zp = os.path.join(tmp, 'Digitakt_OS1.53.zip')
        with open(zp, 'wb') as fh:
            fh.write(buf.getvalue())
        w = first_run([zp], tmp)
        try:
            assert w.model.stock['ok'] and w.model.dev.key == 'digitakt-mk1'
            assert rows(w) == [('core', False)] and w.hidden == 0
        finally:
            w.win.destroy()


STOCK_154 = os.environ.get('ELEKLOADER_STOCK_154', '')


def test_a_newer_os_gets_its_own_core():
    """With both Digitakt cores built in (1.53's core-2.1.elemod and 1.54's
    core-2.1-os1.54.elemod) and a 1.54 stock file, the first run lists and
    ticks 1.54's core, hides 1.53's, and the set checks."""
    need(STOCK_154, 'ELEKLOADER_STOCK_154')
    mods = need(MODS, 'ELEKLOADER_MODS')
    cores = [os.path.join(mods, n) for n in ('core-2.1.elemod', 'core-2.1-os1.54.elemod')]
    if not all(os.path.exists(c) for c in cores):
        raise Skip('ELEKLOADER_MODS lacks core-2.1.elemod or core-2.1-os1.54.elemod')
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        raise Skip('no Tk: %s' % e)
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, 'bundled')
        os.makedirs(bundled)
        for c in cores:
            shutil.copy(c, bundled)
        root.withdraw()
        w = gui.LoaderWindow(root, gui.LoaderModel(STOCK_154, os.path.join(tmp, 'lib'), [bundled],
                                                   os.path.join(tmp, 'settings.json')))
        try:
            assert w.model.rel.version == '1.54'
            assert rows(w) == [('core', True)] and w.hidden == 1
            assert [os.path.basename(p) for p in w.enabled] == ['core-2.1-os1.54.elemod']
            assert 'firmware' in w.count_var.get()
            r = w.model.check(sorted(w.enabled))
            assert r['ok'], r
        finally:
            root.destroy()


def test_two_core_lines_a_first_run_takes_2_1_and_a_mod_that_needs_3_0_takes_3_0():
    """With core 2.1 and core 3.0 built in, a first run ticks 2.1 (the core
    every build took before 3.0); ticking a mod whose resources.core asks for
    3.0 (machine-pages) swaps the build's core for 3.0, and the set checks."""
    need(STOCK, 'ELEKLOADER_STOCK')
    mods = need(MODS, 'ELEKLOADER_MODS')
    # the newest machine-pages for 1.53 there (machine-pages-<version>.elemod)
    mps = sorted((p for p in glob.glob(os.path.join(mods, 'machine-pages-*.elemod'))
                  if '-os' not in os.path.basename(p)),
                 key=lambda p: [int(x) for x in os.path.basename(p)[14:-7].split('.') if x.isdigit()])
    files = [os.path.join(mods, n) for n in ('core-2.1.elemod', 'core-3.0.elemod')] + mps[-1:]
    if len(files) < 3 or not all(os.path.exists(f) for f in files):
        raise Skip('ELEKLOADER_MODS lacks core-2.1, core-3.0 or a machine-pages')
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        raise Skip('no Tk: %s' % e)
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, 'bundled')
        os.makedirs(bundled)
        for c in files[:2]:
            shutil.copy(c, bundled)
        root.withdraw()
        w = gui.LoaderWindow(root, gui.LoaderModel(STOCK, os.path.join(tmp, 'lib'), [bundled],
                                                   os.path.join(tmp, 'settings.json')))
        try:
            assert [os.path.basename(p) for p in w.enabled] == ['core-2.1.elemod']
            w.model.install(files[2])
            w.refresh()
            mp = [p for p, d in w.descs.items() if d.get('id') == 'machine-pages'][0]
            w.toggle(mp)
            assert sorted(os.path.basename(p) for p in w.enabled) == [
                'core-3.0.elemod', os.path.basename(files[2])]
            r = w.model.check(sorted(w.enabled))
            assert r['ok'], r
            w.toggle(mp)                            # off again: the core stays as chosen
            assert [os.path.basename(p) for p in w.enabled] == ['core-3.0.elemod']
        finally:
            root.destroy()


DN_SYX = os.environ.get('ELEKLOADER_DN_SYX', '')
DN_MODS = os.environ.get('ELEKLOADER_DN_MODS', '')


def test_a_digitone_set_checks_with_its_core():
    """The Digitone links mods but has no .fast area: the check must show
    its budgets without dividing by that zero (a Tk callback error, which
    the window would only print)."""
    need(DN_SYX, 'ELEKLOADER_DN_SYX')
    cores = sorted(glob.glob(os.path.join(need(DN_MODS, 'ELEKLOADER_DN_MODS'), 'core*.elemod')))
    if not cores:
        raise Skip('no core*.elemod in ELEKLOADER_DN_MODS')
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        raise Skip('no Tk: %s' % e)
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc[1])
    with tempfile.TemporaryDirectory() as tmp:
        bundled = os.path.join(tmp, 'bundled')
        os.makedirs(bundled)
        for c in cores:
            shutil.copy(c, bundled)
        root.withdraw()
        w = gui.LoaderWindow(root, gui.LoaderModel(DN_SYX, os.path.join(tmp, 'lib'), [bundled],
                                                   os.path.join(tmp, 'settings.json')))
        try:
            core = [p for p, d in w.descs.items() if d.get('id') == 'core' and d.get('fits')]
            assert len(core) == 1, w.descs
            if core[0] not in w.enabled:            # a first run with the stock given ticks it
                w.toggle(core[0])
            w.changed()
            w.result = None
            t = time.time()
            while time.time() - t < 60 and not (w.result is not None and w.pending is None):
                root.update()
                time.sleep(0.02)
            assert w.result and w.result['ok'], w.result
            assert w.bars['fast'][1].get() == 'none on this device'
            assert not errors, errors
        finally:
            root.destroy()


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
