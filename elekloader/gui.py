#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""elekloader's window: a mod manager for Elektron firmware, in the style of
a game's (Vortex, Nexus Mod Manager). Tkinter, no other dependency.

    python -m elekloader [--stock OS.syx] [--mods DIR ...]

- The mod list: tick mods to enable them. The conflict check runs as you
  tick, and each mod's status says whether it combines, conflicts, needs
  another, or is made for other firmware.
- The details pane: what a mod is, every change it makes, and what it
  needs.
- Install from file copies a .elemod into your library; Uninstall removes it
  from there. Mods built into the app (the bundled/ folder next to this
  file: the Windows build carries core there) are listed too, and can't be
  uninstalled.
- Ticking a mod also ticks the mods it requires, when they are listed.
- Profiles are named sets of enabled mods.
- Build firmware links the enabled mods onto your stock .syx, verifies the
  result, and saves it.

Your library, profiles and the stock file you chose are kept in a per-user
folder (settings_dir()). Nothing here talks to a device: you flash the .syx
yourself, and the stock .syx recovers the unit, because the bootloader is
never changed.

LoaderModel is the logic without the window (for another front end, or a
test); LoaderWindow takes any Tk parent.
"""
import argparse
import glob
import json
import os
import queue
import shutil
import sys
import threading
import time

from . import devices, elemod, formats, link, patch

APP = 'elekloader'


def settings_dir():
    """The per-user folder: %APPDATA%\\elekloader, else ~/.elekloader."""
    base = os.environ.get('APPDATA')
    return os.path.join(base, APP) if base else os.path.join(os.path.expanduser('~'), '.' + APP)


LIBRARY = os.path.join(settings_dir(), 'mods')
SETTINGS = os.path.join(settings_dir(), 'settings.json')
# Mods built into the app: the Windows build puts core here. A source checkout
# has none (built .elemod files are never committed).
BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bundled')


def with_requirements(descs, enabled, path):
    """-> `enabled` plus `path`, plus the mods it requires (and theirs) that are
    listed and made for the stock firmware, when none enabled already provides
    them. descs: {path: describe(path)}. Of several files with the id, the last
    (by file name) is taken; a requirement nothing provides is left for the
    check to report."""
    out = set(enabled) | {path}
    todo = [path]
    while todo:
        d = descs.get(todo.pop(), {})
        for rid in d.get('requires', []):
            if any(descs.get(p, {}).get('id') == rid for p in out):
                continue
            cands = sorted((p for p, x in descs.items()
                            if x.get('id') == rid and x.get('fits') and 'error' not in x),
                           key=os.path.basename)
            if cands:
                out.add(cands[-1])
                todo.append(cands[-1])
    return out


# ---- the logic ----------------------------------------------------------------------

class LoaderModel:
    def __init__(self, stock=None, library=LIBRARY, also=(), settings=SETTINGS):
        self.lock = threading.Lock()
        self.library = library
        self.also = list(also)
        self.settings_path = settings
        self._mods = {}
        self.settings = self._load_settings()
        self.profiles = self.settings.get('profiles') or {}
        self.profile = self.settings.get('profile')
        self.set_stock(stock or self.settings.get('stock'))

    # the stock firmware
    def set_stock(self, path):
        """Choose the stock firmware: known by its hash, or refused."""
        info = {'path': path, 'ok': False}
        self.img = self.dev = self.rel = None
        if not path:
            info['error'] = 'no stock firmware chosen'
        else:
            try:
                s, dev, rel = formats.load(path)
                info['sha256'] = s.sha256
                img = formats.main_image(s, dev)
                if elemod.sha(img) == rel.main_sha256:
                    self.img, self.dev, self.rel = img, dev, rel
                    info.update(ok=True, device=dev.name, os=rel.version)
                else:
                    info['error'] = 'its main OS is not the known image'
            except Exception as e:       # a missing, foreign or unknown file: say so
                info['error'] = str(e)
        self.stock = info
        if info['ok']:
            self.settings['stock'] = path
            self.save_settings()
        return info

    # the library
    def files(self):
        out = elemod.mod_files(self.library)
        seen = {os.path.basename(p) for p in out}
        for d in self.also:
            for p in elemod.mod_files(d):
                if os.path.basename(p) not in seen:
                    out.append(p)
                    seen.add(os.path.basename(p))
        return out

    def installed_by_hand(self, path):
        return os.path.dirname(os.path.abspath(path)) == os.path.abspath(self.library)

    def install(self, src):
        """Copy a .elemod into the library (it must load). -> its new path."""
        elemod.load_any(src)
        os.makedirs(self.library, exist_ok=True)
        dst = os.path.join(self.library, os.path.basename(src))
        shutil.copyfile(src, dst)
        return dst

    def uninstall(self, path):
        if not self.installed_by_hand(path):
            raise elemod.ModError('only mods installed from a file can be uninstalled here')
        os.remove(path)

    def mod(self, path):
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
        if key not in self._mods:
            self._mods[key] = elemod.load_any(path)
        return self._mods[key]

    def describe(self, path):
        base = {'path': path, 'file': os.path.basename(path)}
        try:
            m = self.mod(path)
        except (OSError, elemod.ModError) as e:
            return dict(base, error=str(e), id=os.path.basename(path), label=base['file'])
        d = dict(base, id=m.id, version=m.version, label=m.label(),
                 for_device=m.dev.key, for_label='%s %s' % (m.dev.name, m.rel.version),
                 fits=self.dev is not None and m.dev.key == self.dev.key and m.rel == self.rel,
                 title=m.doc.get('title', m.id), description=m.doc.get('description', ''),
                 category=m.doc.get('category') or ('Whole build'
                                                    if not isinstance(m, link.Mod2) else ''),
                 author=m.doc.get('author', ''), license=m.doc.get('license', ''),
                 sha256=m.sha256,
                 requires=list(m.requires), conflicts=list(m.conflicts), names=list(m.names))
        sites = []
        for s in m.sites:
            tgt = ''
            for r in s.get('relocs', []):
                tgt = r[2][4:] if r[2].startswith('sym:') else r[2]
            sites.append((s['addr'], s['len'], s['kind'], tgt))
        d['sites'] = sites
        if isinstance(m, link.Mod2):
            d['format'] = 2
            d['ram'] = m.size('.run') + m.size('.bss')
            d['fast'] = m.size('.fast')
            d['events'] = sorted((c['to'], c['order'], c['relocs'][0][2][4:])
                                 for c in m.contribute if c['to'].startswith('ev_'))
            adds = {}
            for c in m.contribute:
                if not c['to'].startswith('ev_'):
                    adds[c['to']] = adds.get(c['to'], 0) + len(c['data']) // max(1, 8)
            d['adds_to'] = sorted({c['to'] for c in m.contribute if not c['to'].startswith('ev_')})
            d['tables'] = sorted(m.collections)
            d['regions'] = [(g['name'], g['lo'], g['hi']) for g in m.regions]
        else:
            d['format'] = 1
            d['ram'] = m.blob['len'] if m.blob else 0
            d['fast'] = 0
            d['events'], d['adds_to'], d['tables'], d['regions'] = [], [], [], []
        return d

    # the check
    def check(self, paths):
        """-> {'ok', 'headline', 'problems', 'status': {path: (state, text)}, ...}."""
        descs = {p: self.describe(p) for p in paths}
        status = {}
        if not self.stock['ok']:
            return {'ok': False, 'headline': 'Choose your stock firmware first',
                    'problems': [self.stock.get('error', 'no stock firmware')],
                    'status': status}
        other = [p for p in paths if not descs[p].get('fits')]
        if other:
            for p in other:
                status[p] = ('warn', 'For ' + descs[p].get('for_label', '?'))
            return {'ok': False, 'headline': 'Made for other firmware',
                    'problems': ['%s is made for %s; your stock firmware is %s %s'
                                 % (descs[p]['label'], descs[p].get('for_label', '?'),
                                    self.dev.name, self.rel.version) for p in other],
                    'status': status}
        if not paths:
            return {'ok': False, 'headline': 'No mods enabled', 'problems': [], 'status': status,
                    'empty': True}
        t = time.time()
        with self.lock:
            try:
                mods = [self.mod(p) for p in paths]
                v2 = [m for m in mods if isinstance(m, link.Mod2)]
                if v2 and len(v2) != len(mods):
                    whole = [descs[p]['label'] for p in paths
                             if not isinstance(self.mod(p), link.Mod2)]
                    raise elemod.ModError('x:\n  %s is a whole build: it cannot be combined '
                                         'with separate mods' % ', '.join(whole))
                if not v2:
                    img = elemod.apply(mods, self.img)
                    for p in paths:
                        status[p] = ('ok', 'Enabled')
                    return {'ok': True, 'format': 1, 'ms': round(1000 * (time.time() - t)),
                            'order': [m.label() for m in mods], 'status': status,
                            'blob': len(img) - len(self.img),
                            'sites': sum(len(m.sites) for m in mods)}
                L = link.link(mods, self.img)
            except (OSError, elemod.ModError) as e:
                lines = [x.strip() for x in str(e).split('\n')[1:]] or [str(e)]
                for p in paths:
                    d = descs[p]
                    lab = d['label']
                    mine = [x for x in lines if lab in x or x.startswith(d['id'] + ' ')]
                    needs = [r for r in d.get('requires', [])
                             if not any(descs[q].get('id') == r for q in paths)]
                    if needs:
                        status[p] = ('warn', 'Needs ' + ', '.join(needs))
                    elif mine:
                        status[p] = ('bad', 'Conflict')
                    else:
                        status[p] = ('ok', 'Enabled')
                return {'ok': False, 'headline': 'Conflicts: the firmware cannot be built',
                        'problems': lines,
                        'status': status, 'ms': round(1000 * (time.time() - t))}
        order = {lab: i + 1 for i, lab in enumerate(L.order)}
        for p in paths:
            status[p] = ('ok', 'Enabled')
        lay = L.layout
        return {'ok': True, 'format': 2, 'ms': round(1000 * (time.time() - t)), 'status': status,
                'order': L.order, 'load_order': {p: order.get(descs[p]['label']) for p in paths},
                'ram': (lay['bss'][1] - lay['ddr'][0], lay['ddr_size']),
                'fast': (lay['fast'][1] - lay['fast'][0], lay['fast_size']),
                'blob': lay['blob_len'], 'sites': sum(len(m.sites) for m in mods)}

    def build(self, paths, version, out_path):
        """Build, verify and write out_path (+ .json, + .map.json). -> facts."""
        with self.lock:
            outputs, man = patch.build(self.stock['path'], paths, version or None,
                                       log=lambda *a: None)
        written = patch.save(outputs, man, out_path)
        f = man['output']
        return {'path': out_path, 'written': written, 'sha256': f['sha256'], 'bytes': f['bytes'],
                'version': man['version'], 'flash_end': f['flash_end'],
                'headroom': f['flash_headroom'], 'gap': f['main'].get('inplace_min_gap'),
                'inplace': f['main'].get('inplace', ''),
                'mods': [m['id'] + ' ' + m['version'] for m in man['mods']],
                'untouched': f['untouched']}

    # settings: the stock file, and profiles (named sets of enabled mod files)
    def _load_settings(self):
        try:
            with open(self.settings_path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        self.settings['profiles'] = self.profiles
        self.settings['profile'] = self.profile
        try:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, 'w') as fh:
                json.dump(self.settings, fh, indent=1)
        except OSError:
            pass

    save_profiles = save_settings


def suggested_name(descs, version):
    ids = sorted(d['id'] for d in descs if d.get('id') not in (None, 'core'))
    return 'custom-%s%s.syx' % (version or 'x', ('-' + '+'.join(ids)) if ids else '')


# ---- the window -----------------------------------------------------------------------

EVENT_NAMES = {'ev_tick': 'UI tick, 30 Hz', 'ev_draw': 'Screen draw', 'ev_key': 'Keys',
               'ev_enc': 'Encoders', 'ev_settings': 'SETTINGS menu rows',
               'ev_render_in': 'Audio render start', 'ev_render_out': 'Audio render end'}
C = {                                     # a dark theme, like a game's mod manager
    'bg': '#16181d', 'panel': '#1e2128', 'raised': '#262a33', 'line': '#323743',
    'text': '#e6e8ec', 'muted': '#9197a3', 'accent': '#e8903a', 'accent2': '#f0a55c',
    'ok': '#46c46d', 'warn': '#e2b340', 'bad': '#f0564a', 'sel': '#35405a',
}
FONT = 'Segoe UI'
BOX_ON, BOX_OFF = '\u2611', '\u2610'


class LoaderWindow:
    def __init__(self, parent, model):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.model = tk, ttk, model
        self.win = parent
        self.q = queue.Queue()
        self.enabled = set()
        self.descs = {}
        self.result = None
        self.pending = None
        parent.title('elekloader')
        parent.geometry('1180x720')
        parent.minsize(980, 600)
        parent.configure(background=C['bg'])
        self._style()

        # the header: the "game" being modded
        head = tk.Frame(parent, background=C['panel'], height=64)
        head.pack(fill='x')
        tk.Label(head, text='ELEK', font=(FONT, 18, 'bold'), fg=C['accent'],
                 bg=C['panel']).pack(side='left', padx=(18, 0), pady=12)
        tk.Label(head, text='LOADER', font=(FONT, 18), fg=C['text'],
                 bg=C['panel']).pack(side='left', pady=12)
        tk.Label(head, text='mods for Elektron firmware', font=(FONT, 9), fg=C['muted'],
                 bg=C['panel']).pack(side='left', padx=12, pady=(18, 12))
        right = tk.Frame(head, background=C['panel'])
        right.pack(side='right', padx=16)
        self.stock_title = tk.Label(right, font=(FONT, 10, 'bold'), bg=C['panel'], anchor='e')
        self.stock_title.pack(anchor='e')
        self.stock_sub = tk.Label(right, font=(FONT, 8), fg=C['muted'], bg=C['panel'], anchor='e')
        self.stock_sub.pack(anchor='e')
        ttk.Button(head, text='Change stock firmware...', style='Flat.TButton',
                   command=self.choose_stock).pack(side='right', padx=6)

        # the toolbar
        bar = ttk.Frame(parent, style='Bar.TFrame', padding=(12, 8))
        bar.pack(fill='x')
        for text, cmd in (('+  Install from file...', self.install),
                          ('Uninstall', self.uninstall), ('Enable all', self.enable_all),
                          ('Disable all', self.disable_all), ('Refresh', self.refresh)):
            ttk.Button(bar, text=text, style='Tool.TButton', command=cmd).pack(side='left', padx=(0, 6))
        self.show_other = tk.BooleanVar(value=False)       # mods for other firmware: hidden
        self.hidden = 0
        ttk.Checkbutton(bar, text='Show mods for other devices', variable=self.show_other,
                        style='Bar.TCheckbutton', command=self._toggle_other
                        ).pack(side='left', padx=(10, 0))
        ttk.Button(bar, text='Save as...', style='Tool.TButton',
                   command=self.save_profile).pack(side='right')
        self.profile_var = tk.StringVar()
        self.profile_box = ttk.Combobox(bar, textvariable=self.profile_var, width=18,
                                        state='readonly', style='Dark.TCombobox')
        self.profile_box.pack(side='right', padx=6)
        self.profile_box.bind('<<ComboboxSelected>>', lambda e: self.load_profile())
        ttk.Label(bar, text='Profile', style='Bar.TLabel').pack(side='right')

        # the list and the details
        panes = ttk.Panedwindow(parent, orient='horizontal')
        panes.pack(fill='both', expand=True, padx=12, pady=(8, 0))
        left = ttk.Frame(panes, style='Panel.TFrame')
        panes.add(left, weight=3)
        cols = ('on', 'name', 'category', 'version', 'status', 'size', 'order')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', selectmode='browse',
                                 style='Mods.Treeview')
        for c, text, w, anchor in (('on', '', 34, 'center'), ('name', 'Mod', 250, 'w'),
                                   ('category', 'Category', 110, 'w'),
                                   ('version', 'Version', 70, 'w'), ('status', 'Status', 150, 'w'),
                                   ('size', 'RAM', 80, 'e'), ('order', 'Load order', 80, 'center')):
            self.tree.heading(c, text=text, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=w, anchor=anchor, stretch=c == 'name')
        for tag, colour in (('ok', C['text']), ('off', C['muted']), ('bad', C['bad']),
                            ('warn', C['warn']), ('err', C['bad'])):
            self.tree.tag_configure(tag, foreground=colour)
        sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview,
                           style='Dark.Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree.bind('<Button-1>', self._click)
        self.tree.bind('<Double-1>', self._double)
        self.tree.bind('<space>', lambda e: self.toggle(self.tree.focus()))
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.show_details())
        self.tree.bind('<Button-3>', self._menu)
        self.sort_col, self.sort_rev = 'order', False

        det = ttk.Frame(panes, style='Panel.TFrame', padding=(16, 12))
        panes.add(det, weight=2)
        self.d_title = tk.Label(det, font=(FONT, 16, 'bold'), fg=C['text'], bg=C['panel'],
                                anchor='w', justify='left')
        self.d_title.pack(fill='x')
        self.d_sub = tk.Label(det, font=(FONT, 9), fg=C['muted'], bg=C['panel'], anchor='w')
        self.d_sub.pack(fill='x')
        self.d_badge = tk.Label(det, font=(FONT, 9, 'bold'), bg=C['raised'], padx=8, pady=2)
        self.d_badge.pack(anchor='w', pady=(8, 8))
        nb = ttk.Notebook(det, style='Dark.TNotebook')
        nb.pack(fill='both', expand=True)
        self.d_text = {}
        for tab in ('Description', 'Changes', 'Requirements'):
            f = ttk.Frame(nb, style='Panel.TFrame', padding=(0, 8))
            t = tk.Text(f, wrap='word', relief='flat', bg=C['panel'], fg=C['text'],
                        font=(FONT, 9), insertbackground=C['text'], highlightthickness=0,
                        padx=4, pady=4, cursor='arrow')
            t.tag_configure('h', font=(FONT, 9, 'bold'), foreground=C['accent2'], spacing1=6)
            t.tag_configure('m', foreground=C['muted'])
            t.tag_configure('code', font=('Consolas', 9))
            t.tag_configure('ok', foreground=C['ok'])
            t.tag_configure('bad', foreground=C['bad'])
            t.tag_configure('warn', foreground=C['warn'])
            t.pack(fill='both', expand=True)
            t.configure(state='disabled')
            nb.add(f, text=tab)
            self.d_text[tab] = t

        # the check
        chk = tk.Frame(parent, background=C['panel'])
        chk.pack(fill='x', padx=12, pady=(8, 0))
        self.c_head = tk.Label(chk, font=(FONT, 10, 'bold'), bg=C['panel'], anchor='w')
        self.c_head.pack(fill='x', padx=12, pady=(8, 0))
        self.c_body = tk.Text(chk, height=3, wrap='word', relief='flat', bg=C['panel'],
                              fg=C['text'], font=(FONT, 9), highlightthickness=0, padx=12,
                              pady=4, cursor='arrow')
        self.c_body.tag_configure('bad', foreground=C['bad'])
        self.c_body.tag_configure('m', foreground=C['muted'])
        self.c_body.pack(fill='x')
        self.c_body.configure(state='disabled')

        # the footer: budgets, version, build
        foot = tk.Frame(parent, background=C['bg'])
        foot.pack(fill='x', padx=12, pady=10)
        self.bars = {}
        for k, label in (('ram', 'RAM'), ('fast', 'Fast SRAM')):
            f = tk.Frame(foot, background=C['bg'])
            f.pack(side='left', padx=(0, 18))
            tk.Label(f, text=label, font=(FONT, 8, 'bold'), fg=C['muted'], bg=C['bg']).pack(anchor='w')
            pb = ttk.Progressbar(f, length=170, maximum=100, style='Budget.Horizontal.TProgressbar')
            pb.pack(anchor='w')
            v = tk.StringVar(value='-')
            tk.Label(f, textvariable=v, font=(FONT, 8), fg=C['muted'], bg=C['bg']).pack(anchor='w')
            self.bars[k] = (pb, v)
        self.count_var = tk.StringVar()
        tk.Label(foot, textvariable=self.count_var, font=(FONT, 9), fg=C['muted'],
                 bg=C['bg']).pack(side='left')
        self.build_btn = ttk.Button(foot, text='BUILD FIRMWARE', style='Accent.TButton',
                                    command=self.build)
        self.build_btn.pack(side='right')
        self.version_var = tk.StringVar(value='2.0a')
        ttk.Entry(foot, textvariable=self.version_var, width=11, style='Dark.TEntry',
                  font=(FONT, 11)).pack(side='right', padx=8)
        tk.Label(foot, text='OS version shown', font=(FONT, 9), fg=C['muted'],
                 bg=C['bg']).pack(side='right')
        self.progress = ttk.Progressbar(foot, mode='indeterminate', length=120,
                                        style='Budget.Horizontal.TProgressbar')
        self.note = tk.Label(parent, font=(FONT, 8), fg=C['muted'], bg=C['bg'], anchor='w',
                             justify='left')
        self.note.pack(fill='x', padx=14, pady=(0, 8))

        self.refresh_stock()
        self._init_profiles()
        self.refresh()
        parent.after(80, self._poll)
        if not model.stock['ok']:
            # the first run, or the remembered file moved: ask for it straight away
            parent.after(300, lambda: self.choose_stock(first=True))

    # -- theme ------------------------------------------------------------------------------
    def _style(self):
        ttk = self.ttk
        s = ttk.Style(self.win)
        s.theme_use('clam')
        s.configure('.', background=C['bg'], foreground=C['text'], font=(FONT, 9),
                    fieldbackground=C['raised'], bordercolor=C['line'], lightcolor=C['line'],
                    darkcolor=C['line'], troughcolor=C['raised'])
        s.configure('TFrame', background=C['bg'])
        s.configure('Bar.TFrame', background=C['bg'])
        s.configure('Panel.TFrame', background=C['panel'])
        s.configure('Bar.TLabel', background=C['bg'], foreground=C['muted'])
        s.configure('Bar.TCheckbutton', background=C['bg'], foreground=C['muted'],
                    indicatorbackground=C['raised'], indicatorforeground=C['text'])
        s.map('Bar.TCheckbutton', background=[('active', C['bg'])],
              foreground=[('active', C['text'])],
              indicatorbackground=[('selected', C['accent'])])
        s.configure('Tool.TButton', background=C['raised'], foreground=C['text'], padding=(10, 5),
                    borderwidth=0, focusthickness=0)
        s.map('Tool.TButton', background=[('active', C['line']), ('disabled', C['panel'])],
              foreground=[('disabled', C['muted'])])
        s.configure('Flat.TButton', background=C['panel'], foreground=C['muted'], borderwidth=0,
                    padding=(8, 4))
        s.map('Flat.TButton', background=[('active', C['raised'])], foreground=[('active', C['text'])])
        s.configure('Accent.TButton', background=C['accent'], foreground='#1b1206',
                    font=(FONT, 11, 'bold'), padding=(22, 8), borderwidth=0)
        s.map('Accent.TButton', background=[('active', C['accent2']), ('disabled', C['raised'])],
              foreground=[('disabled', C['muted'])])
        s.configure('Mods.Treeview', background=C['panel'], fieldbackground=C['panel'],
                    foreground=C['text'], rowheight=30, borderwidth=0, font=(FONT, 10))
        s.map('Mods.Treeview', background=[('selected', C['sel'])],
              foreground=[('selected', C['text'])])
        s.configure('Mods.Treeview.Heading', background=C['raised'], foreground=C['muted'],
                    font=(FONT, 9, 'bold'), borderwidth=0, padding=(6, 6))
        s.map('Mods.Treeview.Heading', background=[('active', C['line'])])
        s.configure('Dark.TNotebook', background=C['panel'], borderwidth=0)
        s.configure('Dark.TNotebook.Tab', background=C['panel'], foreground=C['muted'],
                    padding=(12, 5), borderwidth=0)
        s.map('Dark.TNotebook.Tab', background=[('selected', C['raised'])],
              foreground=[('selected', C['text'])])
        s.configure('Budget.Horizontal.TProgressbar', background=C['accent'],
                    troughcolor=C['raised'], borderwidth=0, thickness=8)
        s.configure('Dark.TEntry', fieldbackground=C['raised'], foreground=C['text'],
                    insertcolor=C['text'])
        s.configure('Dark.TCombobox', fieldbackground=C['raised'], background=C['raised'],
                    foreground=C['text'], arrowcolor=C['text'])
        s.map('Dark.TCombobox', fieldbackground=[('readonly', C['raised'])],
              foreground=[('readonly', C['text'])])
        s.configure('Dark.Vertical.TScrollbar', background=C['raised'], troughcolor=C['panel'],
                    arrowcolor=C['muted'], borderwidth=0)
        s.configure('TPanedwindow', background=C['bg'])
        self.win.option_add('*TCombobox*Listbox.background', C['raised'])
        self.win.option_add('*TCombobox*Listbox.foreground', C['text'])

    # -- the list ---------------------------------------------------------------------------
    def refresh_stock(self):
        st = self.model.stock
        dev = self.model.dev
        if dev is not None:
            cur = self.version_var.get().strip()
            default = '2.0a' if dev.container == 'ele3' else '%s ELEK' % self.model.rel.version
            try:
                formats.check_version(dev, cur)
                if cur in ('2.0a',) or cur.endswith(' ELEK'):
                    self.version_var.set(default)         # another device's default
            except formats.FormatError:
                self.version_var.set(default)
        self.note.configure(text=(
            'Nothing here talks to your device: flash the built .syx yourself, as with any OS '
            'update. Only the main OS changes, so the stock .syx always recovers the unit'
            + (' (%s: %s).' % (dev.name, dev.recovery) if dev and dev.recovery else '.')))
        if st['ok']:
            self.stock_title.configure(text='%s  \u00b7  OS %s  \u2713' % (st['device'], st['os']),
                                       fg=C['ok'])
            self.stock_sub.configure(text='%s  \u00b7  sha256 %s...' % (
                os.path.basename(st['path']), st['sha256'][:16]))
        else:
            self.stock_title.configure(text='Choose your stock firmware', fg=C['warn'])
            self.stock_sub.configure(text=('%s: %s' % (os.path.basename(st['path']), st['error']))
                                     if st.get('path') else 'Supported: ' + devices.supported())

    def refresh(self):
        files = self.model.files()
        self.descs = {p: self.model.describe(p) for p in files}
        self.enabled &= set(files)
        self._fill()
        self.changed()

    def _fill(self, status=None, order=None):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        rows = []
        self.hidden = 0
        for p, d in self.descs.items():
            on = p in self.enabled
            if self._other(d) and not on and not self.show_other.get():
                self.hidden += 1                       # made for other firmware
                continue
            if 'error' in d:
                st, text = 'err', 'Invalid file'
            elif not d.get('fits') and self.model.dev is not None:
                st, text = 'off', 'For ' + d.get('for_label', '?')
            elif not on:
                st, text = 'off', 'Disabled'
            else:
                st, text = (status or {}).get(p, ('off', 'Checking...'))
            o = (order or {}).get(p)
            rows.append((p, (BOX_ON if on else BOX_OFF, d.get('title', d['file']),
                             d.get('category', ''), d.get('version', ''), text,
                             '%.1f KB' % (d.get('ram', 0) / 1024.0) if 'error' not in d else '',
                             o if o else ''), st))
        key = {'name': 1, 'category': 2, 'version': 3, 'status': 4, 'size': 5}.get(self.sort_col)
        if key is None:
            rows.sort(key=lambda r: (r[1][6] == '', r[1][6] if r[1][6] != '' else 0,
                                     self.descs[r[0]].get('id', '') != 'core',
                                     self.descs[r[0]].get('id', '')))
        else:
            rows.sort(key=lambda r: str(r[1][key]).lower(), reverse=self.sort_rev)
        for p, vals, tag in rows:
            self.tree.insert('', 'end', iid=p, values=vals, tags=(tag,))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        elif rows:
            self.tree.selection_set(rows[0][0])
        else:
            self._no_mods()
        self._update_count()

    def _other(self, d):
        """A mod made for other firmware than the stock file loaded."""
        return 'error' not in d and not d.get('fits') and self.model.dev is not None

    def _toggle_other(self):
        self._fill(*self._last_status())

    def _update_count(self):
        shown = [p for p in self.descs if self.tree.exists(p)]
        n = len([p for p in self.enabled if p in shown])
        text = '%d of %d mods enabled' % (n, len(shown))
        if self.hidden:
            text += '  ·  %d for other devices hidden' % self.hidden
        self.count_var.set(text)

    def _no_mods(self):
        """The details pane when the list is empty."""
        dev, rel = self.model.dev, self.model.rel
        self.d_title.configure(text='No mods for this firmware yet' if dev else 'No mods')
        self.d_sub.configure(text='%s OS %s' % (dev.name, rel.version) if dev else '')
        self.d_badge.configure(text='')
        hint = [('Install a mod made for this firmware with "Install from file...".', '')]
        if self.hidden:
            hint += [('\n\n%d mod%s for other devices %s hidden; "Show mods for other devices" '
                      'lists them.' % (self.hidden, '' if self.hidden == 1 else 's',
                                       'is' if self.hidden == 1 else 'are'), 'm')]
        for tab in self.d_text:
            self._write(tab, hint if tab == 'Description' else [])

    def sort_by(self, col):
        if col == 'on':
            return
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else False
        self.sort_col = col
        self._fill(*self._last_status())

    def _last_status(self):
        r = self.result or {}
        return r.get('status'), r.get('load_order')

    def _click(self, e):
        if self.tree.identify_region(e.x, e.y) == 'cell' and self.tree.identify_column(e.x) == '#1':
            self.toggle(self.tree.identify_row(e.y))
            return 'break'

    def _double(self, e):
        if self.tree.identify_region(e.x, e.y) == 'cell':
            self.toggle(self.tree.identify_row(e.y))

    def _menu(self, e):
        tk = self.tk
        row = self.tree.identify_row(e.y)
        if not row:
            return
        self.tree.selection_set(row)
        m = tk.Menu(self.win, tearoff=0, bg=C['raised'], fg=C['text'],
                    activebackground=C['sel'], activeforeground=C['text'])
        on = row in self.enabled
        m.add_command(label='Disable' if on else 'Enable', command=lambda: self.toggle(row))
        m.add_command(label='Open file location', command=lambda: self._reveal(row))
        if self.model.installed_by_hand(row):
            m.add_separator()
            m.add_command(label='Uninstall', command=self.uninstall)
        m.tk_popup(e.x_root, e.y_root)

    def toggle(self, p):
        d = self.descs.get(p, {'error': 1})
        if not p or 'error' in d:
            return
        if not d.get('fits') and self.model.dev is not None and p not in self.enabled:
            return                                   # made for other firmware
        if p in self.enabled:
            self.enabled.discard(p)
        else:
            self.enabled = with_requirements(self.descs, self.enabled, p)
        self._remember()
        self._fill(*self._last_status())
        self.changed()

    def enable_all(self):
        self.enabled = {p for p, d in self.descs.items() if d.get('format') == 2 and d.get('fits')}
        self._remember()
        self.refresh()

    def disable_all(self):
        self.enabled = set()
        self._remember()
        self.refresh()

    # -- details ------------------------------------------------------------------------------
    def show_details(self):
        sel = self.tree.selection()
        if not sel:
            return
        p = sel[0]
        d = self.descs.get(p, {})
        self.d_title.configure(text=d.get('title', d.get('file', '')))
        bits = [d.get('id', ''), 'version ' + d.get('version', '?') if d.get('version') else '',
                d.get('category', ''), d.get('file', '')]
        self.d_sub.configure(text='  \u00b7  '.join(b for b in bits if b))
        st, text = ('err', 'Invalid file') if 'error' in d else \
            ((self.result or {}).get('status', {}).get(p, ('ok', 'Enabled'))
             if p in self.enabled else ('off', 'Disabled'))
        colour = {'ok': C['ok'], 'off': C['muted'], 'bad': C['bad'], 'warn': C['warn'],
                  'err': C['bad']}[st]
        self.d_badge.configure(text=text.upper(), fg=colour)
        self._write('Description', self._desc_text(d))
        self._write('Changes', self._changes_text(d))
        self._write('Requirements', self._req_text(d))

    def _write(self, tab, parts):
        t = self.d_text[tab]
        t.configure(state='normal')
        t.delete('1.0', 'end')
        for text, tag in parts:
            t.insert('end', text, tag)
        t.configure(state='disabled')

    def _desc_text(self, d):
        if 'error' in d:
            return [(d['error'], 'bad')]
        out = [(d.get('description') or 'No description.', ''), ('\n', '')]
        if d.get('format') == 1:
            out += [('\nWhole build', 'h'), ('\nThis file is one complete CFW build (patcher '
                                             'phase 1). It cannot be combined with separate '
                                             'mods.\n', 'm')]
        out += [('\nFor', 'h'), ('\n%s\n' % d.get('for_label', '?'), '' if d.get('fits') else 'warn')]
        out += [('\nLicence', 'h'), ('\n%s\n' % (d.get('license') or 'not stated'),
                                      '' if d.get('license') else 'm')]
        out += [('\nFile', 'h'), ('\n%s\nsha256 %s\n' % (d['path'], d.get('sha256', '')), 'm')]
        return out

    def _changes_text(self, d):
        if 'error' in d:
            return []
        out = [('Patch sites in the main OS (%d)' % len(d['sites']), 'h'), ('\n', '')]
        for addr, n, kind, tgt in d['sites']:
            out += [('0x%08x' % addr, 'code'),
                    ('  %d bytes, %s%s\n' % (n, kind, ('  \u2192 ' + tgt) if tgt else ''), 'm')]
        if d.get('events'):
            out += [('\nHandles (through core)', 'h'), ('\n', '')]
            for ev, order, fn in d['events']:
                out += [(EVENT_NAMES.get(ev, ev), ''), ('  \u2192 %s  (order %d)\n' % (fn, order), 'm')]
        if d.get('adds_to'):
            out += [('\nAdds entries to', 'h'), ('\n' + ', '.join(d['adds_to']) + '\n', 'm')]
        if d.get('tables'):
            out += [('\nProvides tables', 'h'), ('\n' + ', '.join(d['tables']) + '\n', 'm')]
        mem = []
        if d.get('ram'):
            mem.append('%.1f KB of RAM' % (d['ram'] / 1024.0))
        if d.get('fast'):
            mem.append('%d bytes of fast SRAM' % d['fast'])
        for name, lo, hi in d.get('regions', []):
            mem.append('%s: 0x%08x-0x%08x' % (name, lo, hi))
        if mem:
            out += [('\nMemory', 'h'), ('\n' + '\n'.join(mem) + '\n', 'm')]
        if d.get('names'):
            out += [('\nClaims', 'h'), ('\n' + '\n'.join(d['names']) + '\n', 'm')]
        return out

    def _req_text(self, d):
        if 'error' in d:
            return []
        ids = {self.descs[p].get('id'): p for p in self.enabled}
        out = [('Requires', 'h'), ('\n', '')]
        if not d.get('requires'):
            out.append(('Nothing.\n', 'm'))
        for r in d.get('requires', []):
            ok = r in ids
            out += [('\u2713 ' if ok else '\u2717 ', 'ok' if ok else 'bad'),
                    ('%s  %s\n' % (r, 'enabled' if ok else 'not enabled'), '' if ok else 'bad')]
        needed_by = sorted(self.descs[p].get('title', '') for p in self.enabled
                           if d.get('id') in self.descs[p].get('requires', []))
        out += [('\nRequired by (enabled)', 'h'), ('\n' + ('\n'.join(needed_by) or 'None.') + '\n', 'm')]
        if d.get('conflicts'):
            out += [('\nIncompatible with', 'h'), ('\n' + '\n'.join(d['conflicts']) + '\n', 'm')]
        return out

    # -- the check ---------------------------------------------------------------------------------
    def changed(self):
        if self.pending:
            self.win.after_cancel(self.pending)
        self.pending = self.win.after(120, self._start_check)

    def _start_check(self):
        self.pending = None
        paths = sorted(self.enabled)
        self.c_head.configure(text='Checking...', fg=C['muted'])
        threading.Thread(target=lambda: self.q.put(('check', paths, self.model.check(paths))),
                         daemon=True).start()

    def _show_check(self, paths, r):
        if paths != sorted(self.enabled):
            return                                  # stale: a newer check is coming
        self.result = r
        self._fill(r.get('status'), r.get('load_order'))
        self.show_details()
        self._update_count()
        for k, (pb, v) in self.bars.items():
            pb['value'] = 0
            v.set('-')
        body = []
        if r['ok']:
            self.c_head.configure(text='\u2713  No conflicts: %d mods, %d patch sites. Ready to build.'
                                  % (len(r['order']), r['sites']), fg=C['ok'])
            if r.get('format') == 2:
                body.append(('Load order (fixed by the linker, the same result in any order): '
                             + '  \u203a  '.join(r['order']), 'm'))
                for k in ('ram', 'fast'):
                    used, size = r[k]
                    pb, v = self.bars[k]
                    pb['value'] = 100.0 * used / size if size else 0
                    if not size:
                        v.set('none on this device')        # e.g. no .fast area (Digitone)
                    else:
                        v.set('%.1f / %.0f KB' % (used / 1024.0, size / 1024.0) if k == 'ram'
                              else '%d / %d bytes' % (used, size))
            else:
                body.append(('A whole build: %s.' % ', '.join(r['order']), 'm'))
            self.build_btn.state(['!disabled'])
        else:
            self.c_head.configure(text=('\u26a0  ' if not r.get('empty') else '') + r['headline'],
                                  fg=C['muted'] if r.get('empty') else C['bad'])
            for x in r.get('problems', []):
                body.append(('\u2022 ' + x + '\n', 'bad'))
            if r.get('empty'):
                body.append(('Tick mods in the list to enable them.', 'm'))
            self.build_btn.state(['disabled'])
        t = self.c_body
        t.configure(state='normal')
        t.delete('1.0', 'end')
        for text, tag in body:
            t.insert('end', text, tag)
        lines = sum(max(1, len(x[0]) // 150 + x[0].count('\n')) for x in body) or 1
        t.configure(state='disabled', height=max(1, min(6, lines)))

    # -- the build ------------------------------------------------------------------------------
    def build(self):
        from tkinter import filedialog, messagebox
        paths = sorted(self.enabled)
        version = self.version_var.get().strip()
        try:
            formats.check_version(self.model.dev, version)
        except formats.FormatError as e:
            messagebox.showerror('elekloader', 'The OS version: %s.' % e, parent=self.win)
            return
        out = filedialog.asksaveasfilename(
            parent=self.win, title='Save the custom firmware as', defaultextension='.syx',
            initialfile=suggested_name([self.descs[p] for p in paths], version),
            initialdir=os.path.expanduser('~'), filetypes=[('SysEx firmware', '*.syx')])
        # a device with a card file gets the .bin beside the .syx (patch.save)
        if not out:
            return
        if os.path.exists(out) and os.path.samefile(out, self.model.stock['path']):
            messagebox.showerror('elekloader', 'That is your stock file.', parent=self.win)
            return
        self.start_build(paths, version, out)

    def start_build(self, paths, version, out):
        self.build_btn.state(['disabled'])
        self.build_btn.configure(text='BUILDING...')
        self.progress.pack(side='right', padx=8)
        self.progress.start(12)

        def work():
            try:
                self.q.put(('built', self.model.build(paths, version, out), None))
            except Exception as e:
                self.q.put(('built', None, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _show_build(self, r, err):
        from tkinter import messagebox
        self.progress.stop()
        self.progress.pack_forget()
        self.build_btn.configure(text='BUILD FIRMWARE')
        self.build_btn.state(['!disabled'])
        self.built = r
        if err:
            messagebox.showerror('elekloader', 'The firmware was not built:\n\n' + err,
                                 parent=self.win)
            return
        self._done_dialog(r)

    def _done_dialog(self, r):
        tk, ttk = self.tk, self.ttk
        w = self.done = tk.Toplevel(self.win, background=C['panel'])
        w.title('Firmware built')
        w.transient(self.win)
        tk.Label(w, text='\u2713  Firmware built and verified', font=(FONT, 14, 'bold'),
                 fg=C['ok'], bg=C['panel']).pack(anchor='w', padx=18, pady=(16, 4))
        tk.Label(w, text='  +  '.join(os.path.basename(p) for p in r['written']),
                 font=(FONT, 10, 'bold'), fg=C['text'], bg=C['panel']).pack(anchor='w', padx=18)
        lines = [
            ('Mods', ', '.join(r['mods'])),
            ('OS version shown', r['version']),
            ('sha256', r['sha256']),
            ('Size', '%.2f MB' % (r['bytes'] / 1048576.0)),
            ('Untouched', '; '.join(r['untouched'])),
            ('Main OS', 'unpacks in place with %.0f KB to spare' % (r['gap'] / 1024.0)
             if r['gap'] is not None else 'depacks to the patched image (%s)' % r['inplace']),
            ('Flash', 'ends %s, %.1f MB to spare' % (r['flash_end'], r['headroom'] / 1048576.0)),
        ]
        g = tk.Frame(w, background=C['panel'])
        g.pack(fill='x', padx=18, pady=10)
        for i, (k, v) in enumerate(lines):
            tk.Label(g, text=k, font=(FONT, 9), fg=C['muted'], bg=C['panel']).grid(
                row=i, column=0, sticky='nw', padx=(0, 12), pady=1)
            tk.Label(g, text=v, font=('Consolas', 9) if k == 'sha256' else (FONT, 9),
                     fg=C['text'], bg=C['panel'], wraplength=460, justify='left').grid(
                row=i, column=1, sticky='w', pady=1)
        dev = self.model.dev
        tk.Label(w, text='Flash it like any OS update. The stock .syx recovers the unit'
                 + (' (%s).' % dev.recovery if dev and dev.recovery else '.'), font=(FONT, 8),
                 fg=C['muted'], bg=C['panel'], wraplength=560, justify='left'
                 ).pack(anchor='w', padx=18)
        b = tk.Frame(w, background=C['panel'])
        b.pack(fill='x', padx=18, pady=14)
        ttk.Button(b, text='Close', style='Tool.TButton', command=w.destroy).pack(side='right')
        ttk.Button(b, text='Show in folder', style='Tool.TButton',
                   command=lambda: self._reveal(r['path'])).pack(side='right', padx=6)

    def _reveal(self, path):
        if sys.platform == 'win32':
            import subprocess
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])

    # -- files, profiles ------------------------------------------------------------------------
    def choose_stock(self, first=False):
        """Ask for the stock OS file until one is known or the user cancels."""
        from tkinter import filedialog, messagebox
        last = self.model.stock.get('path')
        start = os.path.dirname(last) if last else os.path.join(os.path.expanduser('~'),
                                                                'Downloads')
        title = ('elekloader: choose the stock OS file Elektron publishes for your device'
                 if first else 'Your stock OS file (as Elektron publishes it)')
        while True:
            p = filedialog.askopenfilename(
                parent=self.win, title=title,
                initialdir=start if os.path.isdir(start) else None,
                filetypes=[('Elektron OS files', '*.syx *.bin *.zip'), ('All files', '*.*')])
            if not p:
                return
            info = self.model.set_stock(p)
            self.refresh_stock()
            self.refresh()          # which mods fit depends on the stock: describe them again
            if info['ok']:
                return
            start = os.path.dirname(p)
            why = info.get('error', '')
            if 'Supported:' not in why:
                why += '\n\nSupported: %s.' % devices.supported()
            if not messagebox.askretrycancel(
                    'elekloader', '%s is not a stock OS file elekloader knows.\n\n%s\n\n'
                    'Choose another file?' % (os.path.basename(p), why), parent=self.win):
                return

    def install(self):
        from tkinter import filedialog, messagebox
        ps = filedialog.askopenfilenames(parent=self.win, title='Install mods',
                                         filetypes=[('elekloader mods', '*.elemod *.dtmod')])
        for p in ps:
            try:
                dst = self.model.install(p)
                self.enabled.add(dst)
            except (OSError, elemod.ModError) as e:
                messagebox.showerror('elekloader', 'Not installed:\n\n%s' % e,
                                     parent=self.win)
        if ps:
            self._remember()
            self.refresh()

    def uninstall(self):
        from tkinter import messagebox
        sel = self.tree.selection()
        if not sel:
            return
        p = sel[0]
        if not self.model.installed_by_hand(p):
            messagebox.showinfo('elekloader', 'This mod comes from the build folder '
                                '(%s), not from Install; disable it instead.'
                                % os.path.dirname(p), parent=self.win)
            return
        if messagebox.askyesno('elekloader', 'Uninstall %s?\n\nThe file is removed from '
                               'the library.' % self.descs[p].get('title'), parent=self.win):
            self.model.uninstall(p)
            self.enabled.discard(p)
            self._remember()
            self.refresh()

    def _init_profiles(self):
        m = self.model
        files = {os.path.basename(p): p for p in m.files()}
        if not m.profiles:                  # the first run: every separate mod for this stock on
            on = []
            for n, p in files.items():
                try:
                    x = m.mod(p)
                    # no stock file yet: nothing is known to fit, so nothing is ticked
                    if isinstance(x, link.Mod2) and m.dev is not None \
                            and x.dev.key == m.dev.key and x.rel == m.rel:
                        on.append(n)
                except (OSError, elemod.ModError):
                    pass
            m.profiles = {'Default': sorted(on)}
            m.profile = 'Default'
        if m.profile not in m.profiles:
            m.profile = sorted(m.profiles)[0]
        self.profile_box['values'] = sorted(m.profiles)
        self.profile_var.set(m.profile)
        self.enabled = {files[n] for n in m.profiles.get(m.profile) or [] if n in files}

    def load_profile(self):
        self.model.profile = self.profile_var.get()
        files = {os.path.basename(p): p for p in self.model.files()}
        self.enabled = {files[n] for n in self.model.profiles.get(self.model.profile, [])
                        if n in files}
        self.model.save_profiles()
        self._fill()
        self.changed()

    def save_profile(self):
        from tkinter import simpledialog
        name = simpledialog.askstring('elekloader', 'Profile name:', parent=self.win)
        if name:
            self.model.profile = name.strip()
            self._remember()
            self.profile_box['values'] = sorted(self.model.profiles)
            self.profile_var.set(self.model.profile)

    def _remember(self):
        m = self.model
        m.profiles[m.profile or 'Default'] = sorted(os.path.basename(p) for p in self.enabled)
        try:
            m.save_profiles()
        except OSError:
            pass

    def _poll(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == 'check':
                    self._show_check(a, b)
                else:
                    self._show_build(a, b)
        except queue.Empty:
            pass
        self.win.after(80, self._poll)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader', description=__doc__.split('\n')[0])
    ap.add_argument('--stock', help='your stock OS .syx (default: the one chosen last time)')
    ap.add_argument('--mods', action='append', default=[],
                    help='also list the .elemod files in this folder (repeatable)')
    ap.add_argument('--library', default=LIBRARY, help='where Install puts mods')
    ap.add_argument('--selftest', metavar='OUT.json',
                    help='write the version and the built-in mods to OUT.json and exit '
                         '(for checking a build; opens no window)')
    a = ap.parse_args(argv)
    also = ([BUNDLED] if os.path.isdir(BUNDLED) else []) + a.mods
    if a.selftest:
        from . import __version__
        mods = []
        for p in elemod.mod_files(BUNDLED):
            m = elemod.load_any(p)
            mods.append({'file': os.path.basename(p), 'id': m.id, 'version': m.version,
                         'sha256': m.sha256})
        import tempfile
        import tkinter as tk
        root = tk.Tk()                       # the window's toolkit works (hidden, destroyed)
        root.withdraw()
        root.update()
        root.destroy()
        with tempfile.TemporaryDirectory() as tmp:
            listed = LoaderModel(None, os.path.join(tmp, 'mods'), also,
                                 os.path.join(tmp, 'settings.json')).files()
        with open(a.selftest, 'w') as fh:
            json.dump({'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                       'tk': str(tk.TkVersion), 'supported': devices.supported(),
                       'bundled': mods,
                       'listed': [os.path.basename(p) for p in listed]}, fh, indent=1)
        return
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    import tkinter as tk
    root = tk.Tk()
    LoaderWindow(root, LoaderModel(a.stock, a.library, also))
    root.mainloop()


if __name__ == '__main__':
    main()
