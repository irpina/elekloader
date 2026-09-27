"""The window's first run, with its file dialogs scripted (pytest, or run with
python). A hidden Tk window: it needs Tk, and the files, named by environment
variables; a test whose inputs are missing is skipped, not passed:
  ELEKLOADER_STOCK    Digitakt_OS1.53.syx
  ELEKLOADER_OT_SYX   OCTATRACK_OS1.40C.syx
  ELEKLOADER_MODS     a folder with core-*.elemod (the core the Windows app builds in)
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
