# SPDX-License-Identifier: GPL-2.0-or-later
"""The web page's way into elekloader. It runs in Pyodide, in the page's
worker (worker.js), on Pyodide's in-memory file system: the files the page
hands over are written under /work, and nothing here reads anything else or
talks to a network.

The logic is elekloader's own, unchanged: gui.LoaderModel (the desktop
window's logic without Tk) for the stock file, the mod list and the live
check; gui.with_requirements for ticking; patch.build and patch.save for the
build, as the command line and the window do.

The worker calls call(name, args_json, data, progress) and gets JSON back.
"""
import hashlib
import json
import os
import shutil
import time

import elekloader
from elekloader import devices, elemod, formats, gui, patch

WORK = '/work'
STOCK, MODS, CORE, OUT = (os.path.join(WORK, d) for d in ('stock', 'mods', 'core', 'out'))
for d in (STOCK, MODS, CORE, OUT):
    os.makedirs(d, exist_ok=True)

# the user's mods are the library; the site's cores are listed beside them,
# as the apps list their built-in cores
model = gui.LoaderModel(library=MODS, also=[CORE], settings=os.path.join(WORK, 'settings.json'))


def _name(name):
    """A file name from the page: its last part only."""
    n = os.path.basename(str(name).replace('\\', '/')).strip()
    if n in ('', '.', '..'):
        raise ValueError('no file name')
    return n


def _device(d, rel=None):
    return {'key': d.key, 'name': d.name, 'releases': sorted(d.releases),
            'container': d.container, 'version_len': d.version_len,
            'exact_len': d.container == 'ele3', 'recovery': d.recovery,
            'card_file': d.container == 'elek', 'linkable': d.linkable(),
            # the window's default (gui.LoaderWindow.refresh_stock)
            'default_version': ('2.0a' if d.container == 'ele3'
                                else '%s ELEK' % rel.version if rel else '')}


def describe(path):
    d = model.describe(path)
    d['builtin'] = os.path.dirname(path) == CORE
    return d


def info(args, data):
    return {'version': elekloader.__version__, 'supported': devices.supported(),
            'devices': [_device(d) for d in devices.devices()],
            'exts': list(elemod.EXTS)}


def add_core(args, data):
    """A core the site carries (core/index.json names it, with its sha256)."""
    path = os.path.join(CORE, _name(args['name']))
    raw = data.to_bytes()
    if hashlib.sha256(raw).hexdigest() != args['sha256']:
        raise ValueError('%s is not the file the site lists' % args['name'])
    with open(path, 'wb') as fh:
        fh.write(raw)
    return describe(path)


def set_stock(args, data):
    """The stock OS file: known by its hash, or refused (and not kept)."""
    name = _name(args['name'])
    for n in os.listdir(STOCK):                    # one stock file at a time
        os.remove(os.path.join(STOCK, n))
    path = os.path.join(STOCK, name)
    with open(path, 'wb') as fh:
        fh.write(data.to_bytes())
    t = time.time()
    st = dict(model.set_stock(path), file=name, ms=round(1000 * (time.time() - t)))
    if st['ok']:
        st['dev'] = _device(model.dev, model.rel)
    else:
        os.remove(path)
        if 'Supported:' not in st.get('error', ''):
            st['supported'] = devices.supported()
    return st


def add_mod(args, data):
    """Add a mod to the library, as Install from file does: it must load."""
    name = _name(args['name'])
    if not name.lower().endswith(elemod.EXTS):
        return {'ok': False, 'file': name, 'error': '%s is not a mod: the file name must end '
                '%s' % (name, ' or '.join(elemod.EXTS))}
    path = os.path.join(MODS, name)
    with open(path, 'wb') as fh:
        fh.write(data.to_bytes())
    # a file replaced under the same name is read again, not taken from the cache
    model._mods = {k: v for k, v in model._mods.items() if k[0] != path}
    try:
        elemod.load_any(path)
    except (OSError, elemod.ModError) as e:
        os.remove(path)
        return {'ok': False, 'file': name, 'error': str(e)}
    return {'ok': True, 'mod': describe(path)}


def remove_mod(args, data):
    path = args['path']
    if os.path.dirname(path) != MODS:
        raise ValueError('only mods you added can be removed')
    if os.path.exists(path):
        os.remove(path)
    return {'ok': True}


def mods(args, data):
    return [describe(p) for p in model.files()]


def tick(args, data):
    """Tick a mod, with the mods it requires (as the window does)."""
    descs = {p: describe(p) for p in model.files()}
    return sorted(gui.with_requirements(descs, set(args['enabled']), args['path']))


def check(args, data):
    return model.check(sorted(args['enabled']))


def _version_problem(v):
    """What is wrong with the version field, or None. formats.check_version
    counts a non-ASCII character as one; the writers then refuse to encode it
    (they raise UnicodeEncodeError, not a refusal), so it is refused here,
    in check_version's words."""
    try:
        formats.check_version(model.dev, v)
    except formats.FormatError as e:
        return 'The OS version: %s.' % e
    if v and not v.isascii():
        return 'The OS version: the version is %s ASCII characters.' % (
            'exactly %d' % model.dev.version_len if model.dev.container == 'ele3'
            else '1 to %d' % model.dev.version_len)
    return None


def version(args, data):
    """The version field and a file name for the build."""
    v = args['version']
    bad = _version_problem(v) if model.dev is not None else None
    out = {'ok': False, 'error': bad} if bad else {'ok': True}
    out['name'] = gui.suggested_name([describe(p) for p in args['enabled']], v)
    return out


def build(args, data, progress=None):
    """Build, verify and save into OUT, as the window does. -> the facts the
    window shows, every file written, the log with its times."""
    if not model.stock['ok']:
        return {'ok': False, 'error': 'Choose your stock firmware first'}
    v = args['version']
    if v and not v.isascii():               # the one case patch.build crashes on (above)
        return {'ok': False, 'error': _version_problem(v)}
    shutil.rmtree(OUT)
    os.makedirs(OUT)
    name = _name(args['name'])
    if not name.lower().endswith('.syx'):
        name += '.syx'
    log = []
    t0 = time.time()

    def say(*a):
        line = ' '.join(str(x) for x in a)
        log.append([round(time.time() - t0, 2), line])
        if callable(progress):              # (JavaScript's null arrives as JsNull, not None)
            progress(line)

    try:
        outputs, man = patch.build(model.stock['path'], sorted(args['enabled']),
                                   args['version'] or None, log=say)
        patch.save(outputs, man, os.path.join(OUT, name))
    except patch.PatchError as e:
        return {'ok': False, 'error': str(e), 'log': log,
                'seconds': round(time.time() - t0, 2)}
    order = {'syx': 0, 'bin': 1, 'json': 2}
    files = []
    for n in sorted(os.listdir(OUT), key=lambda n: (order.get(n.rsplit('.', 1)[-1], 3), n)):
        p = os.path.join(OUT, n)
        with open(p, 'rb') as fh:
            raw = fh.read()
        files.append({'name': n, 'path': p, 'bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest()})
    f = man['output']
    return {'ok': True, 'files': files, 'seconds': round(time.time() - t0, 2), 'log': log,
            'device': model.dev.name, 'os': model.rel.version,
            # what the window's "Firmware built" dialog shows (gui.LoaderModel.build)
            'sha256': f['sha256'], 'bytes': f['bytes'], 'version': man['version'],
            'flash_end': f['flash_end'], 'headroom': f['flash_headroom'],
            'gap': f['main'].get('inplace_min_gap'), 'inplace': f['main'].get('inplace', ''),
            'mods': [m['id'] + ' ' + m['version'] for m in man['mods']],
            'untouched': f['untouched'], 'recovery': model.dev.recovery}


CALLS = {f.__name__: f for f in (info, add_core, set_stock, add_mod, remove_mod, mods, tick,
                                  check, version)}


def call(name, args_json, data=None, progress=None):
    args = json.loads(args_json) if args_json else {}
    if name == 'build':
        return json.dumps(build(args, data, progress))
    return json.dumps(CALLS[name](args, data))
