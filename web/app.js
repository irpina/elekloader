// SPDX-License-Identifier: GPL-2.0-or-later
// elekloader in the browser: the page. Your files go only to the worker in
// this tab (worker.js, which runs elekloader in Pyodide), and the downloads are
// made here from what it returns. Nothing is sent anywhere.
//
// The logic is the desktop window's (gui.py): the same check, the same
// statuses and wording, ticking a mod ticks what it requires, profiles are
// named sets of ticked mods (here, one set of profiles per device).

const $ = id => document.getElementById(id);

// Elements are built with text only: a mod's title and description come from
// its file, so nothing from a file is ever parsed as HTML.
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (typeof v === 'boolean') e[k] = v;
    else e.setAttribute(k, String(v));
  }
  for (const k of kids.flat(Infinity)) {
    if (k != null && k !== false) e.append(k instanceof Node ? k : String(k));
  }
  return e;
}

const kb = n => (n / 1024).toFixed(1) + ' KB';
const mb = n => (n / 1048576).toFixed(2) + ' MB';
const secs = ms => (ms / 1000).toFixed(1) + ' s';
const hex = n => '0x' + n.toString(16).padStart(8, '0');
const base = p => p.slice(p.lastIndexOf('/') + 1);

// ---- the engine (worker.js) ---------------------------------------------------------

class Engine {
  constructor() {
    this.worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
    this.next = 1;
    this.waiting = new Map();
    this.worker.onmessage = e => {
      const m = e.data;
      const w = this.waiting.get(m.id);
      if (!w) return;
      if ('log' in m) { if (w.onlog) w.onlog(m.log, m.t); return; }
      this.waiting.delete(m.id);
      if (m.ok) w.resolve(m.result); else w.reject(new Error(m.error));
    };
    this.worker.onerror = e => {
      e.preventDefault();
      for (const w of this.waiting.values()) w.reject(new Error(e.message || 'the engine stopped'));
      this.waiting.clear();
    };
  }

  // data: an ArrayBuffer, copied (the page keeps its own for IndexedDB)
  call(cmd, args = {}, data = null, onlog = null) {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject, onlog });
      const buf = data ? data.slice(0) : null;
      this.worker.postMessage({ id, cmd, args, data: buf }, buf ? [buf] : []);
    });
  }
}

// ---- what is kept in this browser ------------------------------------------------------

const KEY = 'elekloader.settings';
// profiles: [{id, name, device, os, sha, file, mods}], each with one stock OS (its device key,
// OS version, sha256 and file name; null until it has one) and the mod files ticked for it;
// current: the id of the one in use; versions: {device key: the last version field}
const S = Object.assign({ profiles: [], current: null, versions: {}, remember: false, showOther: false },
  (() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } })());
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
if (!Array.isArray(S.profiles)) {      // before: {device key: {name: [file names]}}, none with a stock OS
  S.profiles = Object.entries(S.profiles || {}).flatMap(([device, sets]) => Object.entries(sets)
    .map(([name, mods]) => ({ id: newId(), name, device, os: null, sha: null, file: null, mods })));
  const was = Object.entries(S.profile || {}).map(([d, n]) => S.profiles.find(p => p.device === d && p.name === n))
    .find(Boolean);
  S.current = (was || S.profiles[0] || {}).id || null;
  delete S.profile;
}

function saveSettings() {
  try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* storage off: fine */ }
}

// The stock file and the mods, only when the user ticks "Keep my stock file
// and mods in this browser". IndexedDB keeps them on this computer.
const Files = {
  db: null,
  open() {
    if (this.db) return this.db;
    this.db = new Promise((resolve, reject) => {
      const r = indexedDB.open('elekloader', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('files');
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
    return this.db;
  },
  async run(mode, fn) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const t = db.transaction('files', mode);
      const r = fn(t.objectStore('files'));
      t.oncomplete = () => resolve(r && r.result);
      t.onerror = () => reject(t.error);
    });
  },
  put(key, value) { return this.run('readwrite', s => s.put(value, key)); },
  get(key) { return this.run('readonly', s => s.get(key)); },
  del(key) { return this.run('readwrite', s => s.delete(key)); },
  clear() { return this.run('readwrite', s => s.clear()); },
  async all() {
    const keys = await this.run('readonly', s => s.getAllKeys());
    const vals = await this.run('readonly', s => s.getAll());
    return keys.map((k, i) => [k, vals[i]]);
  },
};

// ---- the state --------------------------------------------------------------------------

const engine = new Engine();
const st = {
  ready: false, info: null, build: null,
  stock: null,            // set_stock's answer
  stockFiles: new Map(),  // sha256 -> {name, data}: the stock files given this visit (a profile each)
  modFiles: new Map(),    // file name -> data: the mods the user added, for IndexedDB
  mods: [],               // describe() of every listed mod
  enabled: new Set(),     // paths in the worker
  check: null, checking: null, checkedFor: null,
  selected: null, busy: false, nameEdited: false, versionOk: false,
  urls: [],
};

const dev = () => (st.stock && st.stock.ok ? st.stock.dev : null);
const desc = p => st.mods.find(d => d.path === p);

// ---- the library -------------------------------------------------------------------------
// The shop's mods (shop/index.json: packaging/build_web.py, from web/catalog.json;
// their files are on this site, next to it) and the mods you added yourself,
// as one collection of cards, one per mod.

const shop = { items: [] };
const lib = { device: S.libDevice || (S.profiles.find(p => p.id === S.current) || {}).device || null,
  type: S.libType || null, sort: S.libSort || 'collection', query: '' };
const OWN = '\u0000own';                         // the "Your files" kind
const cmpVer = (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true });
const shopItem = d => shop.items.find(e => e.available && e.sha256 === d.sha256);
const owned = e => st.mods.find(d => !d.builtin && d.sha256 === e.sha256);

// One card per mod: its files for each OS version of a device (a mod's ports)
// are one card, oldest OS first.
function shopGroups(items) {
  const m = new Map();
  for (const e of items) {
    const k = [e.repo, e.id || e.title, e.version, e.device].join('|');
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(e);
  }
  return [...m.values()].map(g => g.sort((a, b) => cmpVer(a.os || '', b.os || '')));
}

// The file a card offers: the one for the stock file's OS, else its newest OS's.
function shopPick(g) {
  const sd = dev();
  return (sd && g.find(e => e.device === sd.key && e.os === st.stock.os)) || g[g.length - 1];
}

// Every card: {shop: group} for the shop's, {own: [descs]} for your own files
// (a mod not from the shop and not built in), with what the cards show.
function libEntries() {
  const out = [];
  for (const g of shopGroups(shop.items)) {
    const e = g[g.length - 1];
    out.push({ shop: g, title: e.title || e.id, id: e.id || e.title, version: e.version || '',
      device: e.device, category: e.category || '', author: e.author || '', license: e.license || '',
      summary: e.summary || e.description || '', oses: g.map(x => x.os).filter(Boolean),
      available: g.some(x => x.available), onUnit: e.on_unit || '' });
  }
  const own = new Map();
  for (const d of st.mods) {
    if (d.builtin || d.error || shopItem(d)) continue;
    const k = [d.id, d.version, d.for_device].join('|');
    if (!own.has(k)) own.set(k, []);
    own.get(k).push(d);
  }
  for (const ds of own.values()) {
    ds.sort((a, b) => cmpVer(a.os || '', b.os || ''));
    const d = ds[0];
    out.push({ own: ds, title: d.title || d.id, id: d.id, version: d.version || '', device: d.for_device,
      category: d.category || (d.format === 1 ? 'Whole build' : ''), author: d.author || '',
      license: d.license || '', summary: d.description || '', oses: ds.map(x => x.os).filter(Boolean),
      available: true });
  }
  return out;
}

// What a card stands for now: the installed files that are its, the one that
// fits the stock file, whether it is in the build, and what Add would add.
function entryState(en) {
  const sd = dev();
  const mine = en.shop ? en.shop.map(owned).filter(Boolean) : en.own;
  const fitting = mine.find(d => d.fits);
  const inBuild = mine.some(d => st.enabled.has(d.path));
  let toAdd = [];
  if (en.shop) {
    const pick = shopPick(en.shop);
    // with a stock file, the file for its OS; before one, every OS's (the list hides the others)
    const files = sd ? [pick] : en.shop.filter(x => x.available);
    toAdd = files.filter(x => x.available && !owned(x));
  }
  const pick = en.shop ? shopPick(en.shop) : (fitting || mine[0]);
  const otherOs = sd && sd.key === en.device && !fitting && pick && pick.os !== st.stock.os;
  return { mine, fitting, inBuild, toAdd, pick, otherOs };
}

async function loadShop() {
  try {
    const r = await fetch(new URL('shop/index.json', import.meta.url));
    shop.items = r.ok ? await r.json() : [];
  } catch {
    shop.items = [];
  }
  renderMods();
}

// the devices to pick from: the engine's, or (before it loads) the shop's
function pickable() {
  if (st.info) {
    return st.info.devices.map(d => ({ key: d.key, name: d.name, os: d.releases.join(' or '),
      latest: d.releases[d.releases.length - 1] }));
  }
  const seen = new Map();                         // before the engine: the shop's devices and OS versions
  for (const e of shop.items) {
    if (!seen.has(e.device)) seen.set(e.device, { key: e.device, name: e.device_name || e.device, oses: new Set() });
    if (e.os) seen.get(e.device).oses.add(e.os);
  }
  return [...seen.values()].map(({ oses, ...d }) => {
    const v = [...oses].sort(cmpVer);
    return { ...d, os: v.join(' or '), latest: v[v.length - 1] || '' };
  });
}
const deviceName = key => (pickable().find(d => d.key === key) || {}).name || key;

function setFilter(k, v) {
  lib[k] = v;
  S['lib' + k[0].toUpperCase() + k.slice(1)] = v;
  saveSettings();
  if (location.hash !== '#library' && location.hash !== '') location.hash = '#library';
  renderLibrary();
}

function filtered(entries) {
  const q = lib.query.trim().toLowerCase();
  return entries.filter(en => (!lib.device || en.device === lib.device)
    && (!lib.type || (lib.type === OWN ? !!en.own : !en.own && en.category === lib.type))
    && (!q || [en.title, en.id, en.summary, en.category, en.author].join(' ').toLowerCase().includes(q)));
}

function sorted(list) {
  const by = lib.sort;
  if (by === 'name') return [...list].sort((a, b) => a.title.localeCompare(b.title));
  if (by === 'device') {
    return [...list].sort((a, b) => deviceName(a.device).localeCompare(deviceName(b.device))
      || a.title.localeCompare(b.title));
  }
  return list;                                     // the catalog's order, then your files
}

// ---- small drawings: the icons, a card's cover ----

const SVG = 'http://www.w3.org/2000/svg';
const PLUS = 'M12 5v14M5 12h14';
const BOLT = 'M13.5 3.5 6.5 13h5l-1 7.5 7-9.5h-5z';
function icon(d, cls = 'ico') {
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('class', cls);
  s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(SVG, 'path');
  p.setAttribute('d', d);
  s.append(p);
  return s;
}

function seeded(s) {                               // a small deterministic generator
  let h = 2166136261;
  for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296;
}

// A cover's motif, from keywords in the mod's id and title: what the mod is
// about (a tuner draws a needle, USB audio its channels). First match wins;
// a mod with none is drawn from its kind. `hue` nudges the kind's colour, so a
// shelf of one kind still varies.
const MOTIFS = [
  { re: /tuner/, motif: 'needle', hue: -20 },
  { re: /sophie|percussion|metal/, motif: 'metal', hue: 0 },
  { re: /synth|\bfm\b/, motif: 'fm', hue: 10 },
  { re: /quantiz|scale/, motif: 'steps', hue: 28 },
  { re: /repitch|turntable/, motif: 'record', hue: -36 },
  { re: /jump|chain/, motif: 'jump', hue: 40 },
  { re: /recorder|rlen|loop/, motif: 'loop', hue: -8 },
  { re: /seek/, motif: 'seek', hue: 18 },
  { re: /lofi|lo-fi|crush/, motif: 'crush', hue: -24 },
  { re: /scene|crossfade/, motif: 'fader', hue: 0 },
  { re: /(^|[-\s])cc[-\s]/, motif: 'knobs', hue: 22 },
  { re: /usb-audio|usb-io|usb audio|usb io/, motif: 'meters', hue: -16 },
  { re: /crossbar/, motif: 'grid', hue: 34 },
  { re: /usb/, motif: 'usb', hue: -34 },
  { re: /midi/, motif: 'din', hue: 12 },
];

function motifOf(en) {
  const words = `${en.id || ''} ${en.title || ''}`.toLowerCase();
  return MOTIFS.find(m => m.re.test(words)) || null;
}

// a USB audio mod's channel counts, from its id: [out, in]
function channelsOf(id) {
  const out = /tracks-main-cue/.test(id) ? 20 : /tracks/.test(id) ? 16 : /main-cue/.test(id) ? 4 : 2;
  const inn = !/usb-io/.test(id) ? 0 : /abcd/.test(id) ? 4 : 2;
  return [out, inn];
}

// a cover's line: drawn from the mod's motif or kind, varied by its name
function trace(en) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 200 100');
  svg.setAttribute('aria-hidden', 'true');
  const add = (tag, a) => {
    const e = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(a)) e.setAttribute(k, String(v));
    svg.append(e);
    return e;
  };
  const rnd = seeded(en.id + en.device);
  const line = { fill: 'none', stroke: 'currentColor', 'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' };
  const faint = { stroke: 'currentColor', 'stroke-opacity': 0.4, 'stroke-width': 1.5, 'stroke-dasharray': '3 5' };
  const dot = (cx, cy, r) => add('circle', { cx, cy, r, fill: 'currentColor' });
  const pt = (cx, cy, r, deg) => [cx + r * Math.cos(deg * Math.PI / 180), cy + r * Math.sin(deg * Math.PI / 180)];
  const pts = [];
  const m = motifOf(en);
  if (m && drawMotif(m.motif, en, { add, rnd, line, faint, dot, pt })) return svg;
  if (en.category === 'Sampling') {                // a hit that decays, cut into slices
    for (let x = 0; x <= 200; x += 2) {
      const t = x / 200, env = Math.min(1, t * 14) * Math.exp(-3.2 * t);
      pts.push(`${x},${64 - 30 * env * Math.sin(x * 0.8 + 6 * rnd()) * (0.75 + 0.25 * rnd())}`);
    }
    for (const t of [0.2, 0.4, 0.62, 0.82]) add('line', { ...faint, x1: t * 200, y1: 34, x2: t * 200, y2: 94 });
    add('polyline', { ...line, points: pts.join(' ') });
  } else if (en.category === 'Performance') {      // a load that settles under a ceiling
    let y = 88;
    for (let x = 0; x <= 200; x += 8) {
      y = Math.max(42, Math.min(90, y + (rnd() - 0.62) * 13));
      pts.push(`${x},${y}`);
    }
    add('line', { ...faint, x1: 0, y1: 36, x2: 200, y2: 36 });
    add('polyline', { ...line, points: pts.join(' ') });
  } else if (en.category === 'Framework') {        // a bus with taps
    add('line', { ...line, x1: 0, y1: 70, x2: 200, y2: 70 });
    for (let i = 0; i < 5; i++) {
      const x = 16 + i * 38 + 8 * rnd(), up = i % 2 ? -1 : 1;
      add('polyline', { ...line, points: `${x},70 ${x},${70 - up * 20} ${x + 14},${70 - up * 20}` });
      add('circle', { cx: x + 14, cy: 70 - up * 20, r: 3.5, fill: 'currentColor' });
    }
  } else {                                         // a pulse train
    let x = 0, hi = false;
    pts.push('0,88');
    while (x < 200) {
      x += 10 + 24 * rnd();
      pts.push(`${x},${hi ? 50 : 88}`, `${x},${hi ? 88 : 50}`);
      hi = !hi;
    }
    add('polyline', { ...line, points: pts.join(' ') });
  }
  return svg;
}

// The motifs, in the cover's 200 x 100 box below its name (y 34..96). Each is
// varied by the mod's own generator, so two mods with one motif differ.
function drawMotif(motif, en, { add, rnd, line, faint, dot, pt }) {
  const poly = (pts, extra = {}) => add('polyline', { ...line, ...extra, points: pts.map(p => p.join(',')).join(' ') });
  const arc = (cx, cy, r, a0, a1, extra = {}) => {
    const [x0, y0] = pt(cx, cy, r, a0), [x1, y1] = pt(cx, cy, r, a1);
    add('path', { ...line, ...extra, d: `M${x0},${y0} A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1},${y1}` });
  };
  const arrowHead = (x, y, deg, s = 7) => poly([pt(x, y, s, deg + 150), [x, y], pt(x, y, s, deg - 150)]);
  switch (motif) {
  case 'needle': {                                 // a tuner: a scale, its ticks, the needle
    const cx = 100, cy = 98, r = 58;
    arc(cx, cy, r, 205, 335);
    for (let a = 210; a <= 330; a += 10) {
      const [x0, y0] = pt(cx, cy, r - (a % 30 === 0 ? 10 : 6), a), [x1, y1] = pt(cx, cy, r, a);
      add('line', { ...line, 'stroke-width': a === 270 ? 2.4 : 1.4, x1: x0, y1: y0, x2: x1, y2: y1 });
    }
    const [nx, ny] = pt(cx, cy, r - 4, 270 + (rnd() - 0.5) * 40);
    add('line', { ...line, x1: cx, y1: cy, x2: nx, y2: ny });
    dot(cx, cy - 2, 4);
    return true;
  }
  case 'metal': {                                  // a struck metal's spectrum: its partials miss the harmonics (ticks)
    const u = 17 + 3 * rnd(), x0 = 10 + 4 * rnd(), pts = [];
    const peaks = [1, 2.76, 5.4, 8.93].map((r, i) => [x0 + r * u, (54 - 11 * i) * (0.8 + 0.2 * rnd())]);
    for (let k = 1; x0 + k * u <= 196; k++) add('line', { ...faint, 'stroke-dasharray': 'none', x1: x0 + k * u, y1: 94, x2: x0 + k * u, y2: 99 });
    for (let x = 4; x <= 196; x += 0.5) {
      pts.push([x, 92 - peaks.reduce((s, [px, h]) => s + h / (1 + ((x - px) / 1.8) ** 2), 0)]);
    }
    poly(pts);
    return true;
  }
  case 'fm': {                                     // a carrier bent by its modulator
    const f = 3 + 2 * rnd(), mod = 1 + rnd(), idx = 1.5 + 2 * rnd(), pts = [];
    for (let x = 0; x <= 200; x += 2) {
      const t = x / 200;
      pts.push([x, 66 - 24 * Math.sin(2 * Math.PI * f * t + idx * Math.sin(2 * Math.PI * mod * f * t))]);
    }
    poly(pts);
    return true;
  }
  case 'steps': {                                  // a pitch line snapped to a scale's degrees
    const ph = 6 * rnd(), smooth = [], snapped = [];
    for (let x = 0; x <= 200; x += 2) smooth.push([x, 65 - 26 * Math.sin(x / 32 + ph)]);
    add('polyline', { ...faint, fill: 'none', points: smooth.map(p => p.join(',')).join(' ') });
    for (let x = 0; x <= 200; x += 14) {
      const y = 65 + 9 * Math.round(-26 * Math.sin((x + 7) / 32 + ph) / 9);
      snapped.push([x, y], [Math.min(200, x + 14), y]);
    }
    poly(snapped);
    return true;
  }
  case 'record': {                                 // a turntable: the record, its grooves, the arm
    const cx = 74 + 10 * rnd(), cy = 66;
    add('circle', { ...line, cx, cy, r: 30 });
    for (const r of [24, 18]) add('circle', { ...faint, fill: 'none', cx, cy, r });
    dot(cx, cy, 3.5);
    const px = 160, py = 36;
    dot(px, py, 4);
    poly([[px, py], [px - 6, py + 34], [cx + 16, cy + 6]]);
    arc(cx, cy, 38, 300 + 20 * rnd(), 350 + 20 * rnd());
    return true;
  }
  case 'jump': {                                   // steps, and a jump from one to a later one
    const n = 8, w = 16, gap = 6, x0 = 100 - (n * w + (n - 1) * gap) / 2, y = 74;
    const from = 1 + Math.floor(rnd() * 3), to = from + 3 + Math.floor(rnd() * 2);
    for (let i = 0; i < n; i++) {
      add('rect', { ...line, 'stroke-width': 1.6, x: x0 + i * (w + gap), y, width: w, height: 14, rx: 2,
        fill: i === from || i === to ? 'currentColor' : 'none', 'fill-opacity': 0.35 });
    }
    const xa = x0 + from * (w + gap) + w / 2, xb = x0 + to * (w + gap) + w / 2;
    add('path', { ...line, d: `M${xa},${y - 4} Q${(xa + xb) / 2},${y - 50} ${xb},${y - 6}` });
    arrowHead(xb, y - 6, 70);
    return true;
  }
  case 'loop': {                                   // a recording that comes round again
    const cx = 100, cy = 64, r = 26, a0 = 20 + 60 * rnd();
    arc(cx, cy, r, a0, a0 + 300);
    const [hx, hy] = pt(cx, cy, r, a0 + 300);
    arrowHead(hx, hy, a0 + 300 + 90);
    dot(cx, cy, 7);
    const pts = [];
    for (let x = 0; x <= 200; x += 4) if (x < 62 || x > 138) pts.push([x, 64 - 10 * Math.sin(x / 6 + 5 * rnd())]);
    poly(pts.filter(p => p[0] < 62), { 'stroke-width': 1.6 });
    poly(pts.filter(p => p[0] > 138), { 'stroke-width': 1.6 });
    return true;
  }
  case 'seek': {                                   // a playhead that seeks back instead of restarting
    const pts = [];
    for (let x = 0; x <= 200; x += 2) pts.push([x, 68 - 18 * Math.sin(x / 9) * (0.6 + 0.4 * Math.sin(x / 41 + 3 * rnd()))]);
    poly(pts, { 'stroke-width': 1.8 });
    const xh = 110 + 50 * rnd();
    add('line', { ...line, x1: xh, y1: 36, x2: xh, y2: 96 });
    add('path', { ...line, d: `M${xh - 4},40 Q${xh - 30},30 ${xh - 52},40` });
    arrowHead(xh - 52, 40, 200);
    return true;
  }
  case 'crush': {                                  // a wave, sampled and held
    const hold = 8 + Math.floor(6 * rnd()), pts = [];
    for (let x = 0; x <= 200; x += hold) {
      const y = 66 + 10 * Math.round(-2.6 * Math.sin(x / 18));
      pts.push([x, y], [x + hold, y]);
    }
    poly(pts);
    return true;
  }
  case 'fader': {                                  // the crossfader, and its two scenes
    add('line', { ...line, 'stroke-width': 3, x1: 36, y1: 74, x2: 164, y2: 74 });
    for (const [x, s] of [[24, 'A'], [176, 'B']]) {
      add('circle', { ...line, 'stroke-width': 1.8, cx: x, cy: 74, r: 9 });
      add('text', { x, y: 78, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: 'currentColor' }).textContent = s;
    }
    const fx = 60 + 80 * rnd();
    add('rect', { x: fx - 7, y: 62, width: 14, height: 24, rx: 3, fill: 'currentColor' });
    if (/midi/.test(en.id || '')) {                // driven over MIDI: a small socket above
      add('circle', { ...line, 'stroke-width': 1.8, cx: 100, cy: 44, r: 10 });
      for (const a of [180, 225, 270, 315, 0]) { const [x, y] = pt(100, 44, 5.5, a); dot(x, y, 1.4); }
    } else if (/p2/.test(en.id || '')) {           // page 2: a second row of the same
      add('line', { ...line, 'stroke-width': 2, 'stroke-opacity': 0.6, x1: 36, y1: 44, x2: 164, y2: 44 });
      add('rect', { x: 200 - fx - 6, y: 36, width: 12, height: 16, rx: 3, fill: 'currentColor', 'fill-opacity': 0.6 });
    } else {
      add('path', { ...faint, fill: 'none', d: `M36,50 C${fx},${36} ${fx},${60} 164,44` });
    }
    return true;
  }
  case 'knobs': {                                  // a row of knobs, each at its value
    for (let i = 0; i < 4; i++) {
      const cx = 34 + i * 44, cy = 66, a = 135 + 270 * rnd();
      arc(cx, cy, 15, 135, 405, { 'stroke-width': 1.4, 'stroke-opacity': 0.5 });
      add('circle', { ...line, cx, cy, r: 10 });
      const [x, y] = pt(cx, cy, 10, a);
      add('line', { ...line, x1: cx, y1: cy, x2: x, y2: y });
    }
    if (/feedback/.test(en.id || '')) {            // the values going back out
      add('path', { ...line, 'stroke-width': 1.8, d: 'M166,44 Q100,22 36,42' });
      arrowHead(36, 42, 170, 6);
    }
    return true;
  }
  case 'meters': {                                 // its channels as meters; with an input, both ways
    const [out, inn] = channelsOf(en.id || '');
    const right = inn ? 140 : 196, w = Math.min(22, (right - 8) / out), bw = Math.max(2, Math.min(14, w * 0.64));
    const x0 = 8 + ((right - 8) - out * w) / 2;     // a few channels sit centred, at a meter's width
    for (let i = 0; i < out; i++) {
      const h = 12 + 38 * rnd(), x = x0 + i * w + (w - bw) / 2;
      add('rect', { x, y: 94 - h, width: bw, height: h, rx: 1, fill: 'currentColor', 'fill-opacity': 0.85 });
    }
    if (inn) {
      poly([[146, 50], [160, 50]]); arrowHead(146, 50, 180, 6);
      poly([[146, 70], [160, 70]]); arrowHead(160, 70, 0, 6);
      const wi = 30 / inn;
      for (let i = 0; i < inn; i++) {
        const h = 14 + 30 * rnd();
        add('rect', { ...line, 'stroke-width': 1.4, x: 166 + i * wi + 1, y: 94 - h, width: wi - 3, height: h, rx: 1 });
      }
    }
    return true;
  }
  case 'grid': {                                   // a crossbar: lines, and the points that connect
    for (let i = 0; i < 4; i++) {
      add('line', { ...line, 'stroke-width': 1.4, x1: 40, y1: 44 + i * 15, x2: 160, y2: 44 + i * 15 });
      add('line', { ...line, 'stroke-width': 1.4, x1: 55 + i * 30, y1: 36, x2: 55 + i * 30, y2: 96 });
    }
    for (let i = 0; i < 4; i++) dot(55 + Math.floor(rnd() * 4) * 30, 44 + i * 15, 4.5);
    return true;
  }
  case 'usb': {                                    // the USB trident
    const y = 66;
    dot(40, y, 7);
    poly([[40, y], [158, y]]);
    poly([[150, y - 8], [164, y], [150, y + 8], [150, y - 8]], { fill: 'currentColor' });
    poly([[70, y], [86, y - 22], [110, y - 22]]);
    add('circle', { ...line, cx: 116, cy: y - 22, r: 6 });
    poly([[88, y], [104, y + 20], [124, y + 20]]);
    add('rect', { x: 124, y: y + 15, width: 11, height: 11, fill: 'currentColor' });
    return true;
  }
  case 'din': {                                    // a MIDI DIN socket
    const cx = 100, cy = 66;
    add('circle', { ...line, cx, cy, r: 27 });
    for (const a of [180, 225, 270, 315, 0]) { const [x, y] = pt(cx, cy, 15, a); dot(x, y, 3.2); }
    add('rect', { x: cx - 5, y: cy + 21, width: 10, height: 7, fill: 'currentColor' });
    return true;
  }
  }
  return false;
}

// ---- the first visit: the three steps; then, with a stock file in, what's next ----

// where Elektron publishes each device's stock OS (README, "You also need")
const DOWNLOADS = {
  'digitakt-mk1': { label: 'Digitakt', url: 'https://www.elektron.se/support-downloads/digitakt' },
  'digitakt-mk2': { label: 'Digitakt II', url: 'https://www.elektron.se/support-downloads/digitakt-ii' },
  'digitone-mk1': { label: 'Digitone and Digitone Keys', url: 'https://www.elektron.se/support-downloads/digitone' },
  octatrack: { label: 'Octatrack (MKI and MKII use the same file)', url: 'https://www.elektron.se/support-downloads/octatrack-mkii' },
};

function renderStart(all) {
  const s = st.stock, sd = dev();
  $('welcome').hidden = !!sd;
  $('lib-head').hidden = !sd;
  $('list-title').hidden = !!sd;
  if (sd) { renderNext(); return; }
  const devs = pickable();
  $('dev-tiles').replaceChildren(...devs.map(d => {
    const n = all.filter(en => en.device === d.key).length;
    const on = lib.device === d.key;
    return el('button', { type: 'button', class: 'dev-tile' + (on ? ' on' : ''), 'aria-pressed': String(on),
      onclick: () => setFilter('device', on ? null : d.key) },
    el('strong', {}, d.name), el('span', { class: 'os' }, 'OS ' + d.os),
    el('span', { class: 'n' }, n ? `${n} mod${n === 1 ? '' : 's'}` : 'your own mods'));
  }));
  const d = devs.find(x => x.key === lib.device);
  const dl = d && DOWNLOADS[d.key];
  const want = cur() && cur().sha ? cur() : null;  // a profile waiting for its stock file
  $('g-device').classList.toggle('done', !!d);
  $('g-stock-text').replaceChildren(...(want
    ? [`Your profile "${want.name}" uses `, el('strong', {}, osLabel(want)), ': drop ', el('code', {}, want.file),
      ' here', ...(dl ? [' (it is on ', el('a', { href: dl.url, rel: 'noreferrer', target: '_blank' }, 'Elektron\'s site'), ')'] : []), '.']
    : d
    ? ['Download ', el('strong', {}, `OS ${d.latest}`), ` for the ${dl ? dl.label : d.name} from `,
      dl ? el('a', { href: dl.url, rel: 'noreferrer', target: '_blank' }, 'Elektron\'s site') : 'Elektron\'s site',
      '. Then drop the .syx here, or the .zip just as you downloaded it.']
    : ['Elektron publishes it for each device. Pick yours first and its download link shows here.']));
  $('start-drop').classList.toggle('waiting', !st.ready);
  $('start-drop-text').replaceChildren(...(st.ready
    ? ['Drop the file here, or ', el('span', { class: 'like-link' }, 'choose it')]
    : ['Starting the build engine: a few seconds, the first time only…']));
  $('start-error').hidden = !(s && !s.ok);
  if (s && !s.ok) {
    $('start-error').textContent = `${s.file} is not one of Elektron's stock OS files. It needs the file just as `
      + `Elektron publishes it` + (st.info ? `: ${st.info.supported}.` : '.');
  }
}

function renderNext() {
  const sd = dev();
  const n = [...st.enabled].map(desc).filter(d => d && !d.builtin).length;
  const p = cur();
  $('lib-eyebrow').textContent = `${p ? p.name + ' · ' : ''}${sd.name} · OS ${st.stock.os}`;
  const sep = () => el('span', { class: 'next-sep', 'aria-hidden': 'true' }, '→');
  $('next').replaceChildren(
    el('span', { class: 'next-step done' }, `✓ Stock OS ${st.stock.os}`), sep(),
    n ? el('span', { class: 'next-step done' }, `✓ ${n} mod${n === 1 ? '' : 's'} in your build`)
      : el('span', { class: 'next-step now' }, 'Now: + Add the mods you want, below'), sep(),
    n ? el('a', { class: 'btn primary', href: '#build' }, 'Build your firmware →')
      : el('span', { class: 'next-step' }, 'Then: build'));
}

// ---- the library: the kinds in the sidebar, device chips, a shelf per kind ----

const KIND_HUE = { Sampling: 196, Performance: 268, Framework: 24, 'Whole build': 140, Synthesis: 232,
  // octabam's kinds (elekloader.sdk.octabam takes its CATEGORY_TITLE)
  'Machines and the sequencer': 68, 'Parts, Kits and scenes': 104, 'MIDI and USB': 312, Fixes: 350 };

// a kind in the sidebar: its colour, its name, how many
function kindItem(label, n, on, onclick, swatch) {
  return el('li', {}, el('button', { type: 'button', class: 'side-item' + (on ? ' on' : ''), 'aria-pressed': String(on), onclick },
    swatch, label, el('span', { class: 'n' }, String(n))));
}

function swatchFor(kind) {
  const sw = el('span', { class: 'swatch' });
  sw.style.setProperty('--h', String(KIND_HUE[kind] ?? 330));
  return sw;
}

function renderLibrary() {
  const all = libEntries();
  const sd = dev();
  const devs = pickable();
  const inLib = location.hash !== '#build';
  renderStart(all);
  const forDev = lib.device ? all.filter(en => en.device === lib.device) : all;
  const kinds = [...new Set(all.filter(en => !en.own).map(en => en.category).filter(Boolean))];
  const ownN = forDev.filter(en => en.own).length;
  $('nav-types').replaceChildren(
    kindItem('All mods', forDev.length, inLib && !lib.type, () => setFilter('type', null), el('span', { class: 'swatch all' })),
    ...kinds.map(k => kindItem(k, forDev.filter(en => !en.own && en.category === k).length, inLib && lib.type === k,
      () => setFilter('type', k), swatchFor(k))),
    ownN || lib.type === OWN ? kindItem('Your files', ownN, inLib && lib.type === OWN, () => setFilter('type', OWN),
      el('span', { class: 'swatch own' })) : '');
  // the devices with mods (or the one picked): a device without any would only be an empty list
  const withMods = devs.filter(d => d.key === lib.device || all.some(en => en.device === d.key));
  $('device-buttons').replaceChildren(...[{ key: null, name: 'All' }, ...withMods].map(d => {
    const on = lib.device === d.key;
    return el('button', { type: 'button', class: 'chip' + (on ? ' on' : ''), 'aria-pressed': String(on),
      onclick: () => setFilter('device', d.key) },
    sd && sd.key === d.key ? el('span', { class: 'yours', title: 'Your stock file is for this device' }) : '',
    d.name, el('span', { class: 'n' }, String(all.filter(en => !d.key || en.device === d.key).length)));
  }));
  $('f-sort').value = lib.sort;
  const chosen = devs.find(d => d.key === lib.device);
  $('device-note').textContent = !chosen
    ? (sd ? `Every device's mods. Your stock file is for the ${sd.name}.`
      : 'Every device\'s mods. Pick your device to see the ones that fit it.')
    : sd && sd.key === chosen.key ? `For your ${sd.name}, OS ${st.stock.os}: what you add for that OS is ticked for your build.`
      : sd ? `Your stock file is for the ${sd.name}, so mods for the ${chosen.name} can't go into this build.`
        : `Mods for the ${chosen.name}. To build, you need its stock OS ${chosen.os} file.`;
  $('device-note').className = 'device-note' + (chosen && sd && sd.key !== chosen.key ? ' warn' : '');
  const list = sorted(filtered(all));
  const shelves = new Map();                       // in the order the kinds first appear; your files last
  for (const en of list) {
    const k = en.own ? 'Your files' : en.category || 'Other';
    if (!shelves.has(k)) shelves.set(k, []);
    shelves.get(k).push(en);
  }
  const own = shelves.get('Your files');
  if (own) { shelves.delete('Your files'); shelves.set('Your files', own); }
  $('lib-cards').replaceChildren(...[...shelves].map(([name, ens]) => el('section', { class: 'shelf' },
    el('h2', {}, name, el('span', { class: 'n' }, String(ens.length))), el('div', { class: 'cards' }, ...ens.map(card)))));
  if (!list.length) {
    $('lib-cards').append(el('p', { class: 'empty' }, lib.query.trim() ? 'No mod matches that.'
      : `No mods ${chosen ? 'for the ' + chosen.name + ' ' : ''}here yet. Add your own with + Add your own .elemod.`));
  }
  renderNeed();
}

// what a card's button does now, if anything
function action(en, s) {
  const sd = dev();
  if (!en.available) return null;
  if (s.inBuild) {
    return { kind: 'in', label: `Take ${en.title} out of your build (it stays in your mods)`, disabled: st.busy || !sd,
      run: () => untick(s.mine.map(d => d.path)) };
  }
  if (s.fitting && sd) {
    return { kind: 'add', label: `Add ${en.title} to your build`, disabled: st.busy,
      run: async () => { await tickWithCore(s.fitting.path); remember(); changed(); } };
  }
  if (s.toAdd.length) {
    return { kind: 'add', label: `Add ${en.title}`, disabled: !st.ready || st.busy, run: ev => shopAdd(s.toAdd, ev.currentTarget) };
  }
  return null;                                     // in your mods already, for another device or OS
}

function card(en) {
  const s = entryState(en);
  const act = action(en, s);
  const pick = s.pick || {};
  const open = () => openSheet(en);
  const cover = el('button', { type: 'button', class: 'cover', onclick: open, 'aria-label': `About ${en.title}` },
    trace(en), el('span', { class: 'name' }, en.title));
  const m = motifOf(en);
  cover.style.setProperty('--h', String(Math.round((KIND_HUE[en.category] ?? 330) + (m ? m.hue : 0)
    + (m ? 16 : 36) * seeded(en.id)() - (m ? 8 : 18))));
  const button = act
    ? el('button', { type: 'button', class: 'add' + (act.kind === 'in' ? ' in' : ''), disabled: act.disabled,
      title: act.label, onclick: act.run }, act.kind === 'in' ? '✓ In build' : '+ Add')
    : el('button', { type: 'button', class: 'add have', disabled: true }, en.available ? '✓ Added' : 'Soon');
  const sites = en.shop ? pick.sites : (pick.sites || []).length;
  return el('article', { class: 'card' + (s.inBuild ? ' live' : '') + (en.available ? '' : ' unavailable') },
    cover,
    el('div', { class: 'card-body' },
      el('div', { class: 'card-main' },
        el('div', { class: 'card-title' },
          el('div', {},
            el('h3', {}, en.title, en.version ? el('span', { class: 'ver' }, 'v' + en.version) : ''),
            el('p', { class: 'meta' }, [deviceName(en.device), en.oses.length ? 'OS ' + en.oses.join(', ') : '']
              .filter(Boolean).join(' · '))),
          button),
        el('p', { class: 'summary' }, en.summary),
        s.otherOs ? el('p', { class: 'note' }, `Made for OS ${pick.os}; your stock file is OS ${st.stock.os}.`) : '',
        !en.available && en.shop ? el('p', { class: 'note' }, `Its release (${en.shop[0].tag}) is not published yet.`) : ''),
      el('div', { class: 'card-foot' },
        el('span', {}, en.available && sites != null ? `${sites} patch sites` : ''),
        el('span', { class: 'links' },
          el('button', { type: 'button', class: 'linkish', onclick: open }, 'Details'),
          s.mine.length && !st.busy ? el('button', { type: 'button', class: 'linkish',
            onclick: () => removeMods(s.mine.map(d => d.path)) }, 'Remove') : '',
          en.shop ? el('a', { href: en.available ? en.shop[0].homepage : en.shop[0].release_url, rel: 'noreferrer' }, 'Source') : ''))));
}

// a card's details: what an installed file says about itself, or the catalog's
function openSheet(en) {
  const s = entryState(en);
  const d = s.fitting || s.mine[0];
  $('sheet-title').textContent = `${en.title} ${en.version ? 'v' + en.version : ''}`;
  let parts;
  if (d) {
    parts = detailParts(d);
  } else {
    const e = s.pick;
    const needs = (e.requires || []).map(r => (r === 'core' && e.needs_core ? `core ${e.needs_core} or newer` : r));
    parts = [
      el('p', { class: 'muted' }, [deviceName(en.device), en.oses.length && 'OS ' + en.oses.join(', '),
        en.category, en.author && 'by ' + en.author, en.license].filter(Boolean).join(' · ')),
      el('p', { class: 'desc' }, e.description || en.summary || ''),
      e.available ? el('h4', {}, 'What it changes') : '',
      e.available ? el('p', { class: 'muted' }, [`${e.sites} patch sites`, e.ram ? `${kb(e.ram)} of RAM` : '',
        needs.length ? 'needs ' + needs.join(', ') : '', e.conflicts && e.conflicts.length
          ? 'not with ' + e.conflicts.join(', ') : ''].filter(Boolean).join(' · ')) : '',
      el('h4', {}, en.shop.length > 1 ? 'Files' : 'File'),
      el('p', { class: 'muted mono' }, en.shop.filter(x => x.available)
        .map(x => `${x.file}${en.shop.length > 1 ? ` (OS ${x.os})` : ''}\nsha256 ${x.sha256}`).join('\n')
        || `Its release (${e.tag}) is not published yet.`),
    ];
  }
  // what has been checked on real hardware (the catalog's on_unit), under the description
  if (en.onUnit) {
    const i = parts.findIndex(p => p && p.classList && p.classList.contains('desc'));
    parts.splice(i < 0 ? parts.length : i + 1, 0, el('h4', {}, 'On a unit'), el('p', { class: 'muted' }, en.onUnit));
  }
  // what you can do with it: the card's action, Remove, its source
  const act = action(en, s);
  const close = () => $('mod-sheet').close();
  const acts = el('div', { class: 'sheet-acts' },
    act ? el('button', { type: 'button', class: 'btn ' + (act.kind === 'in' ? 'outline' : 'primary'), disabled: act.disabled,
      onclick: ev => { close(); act.run(ev); } }, act.kind === 'in' ? 'Take it out of the build' : 'Add') : '',
    s.mine.length && !st.busy ? el('button', { type: 'button', class: 'btn outline',
      onclick: () => { close(); removeMods(s.mine.map(x => x.path)); } }, 'Remove') : '',
    en.shop ? el('a', { class: 'btn outline', rel: 'noreferrer',
      href: en.shop[0].available ? en.shop[0].homepage : en.shop[0].release_url }, 'Source') : '');
  $('sheet-body').replaceChildren(acts, ...parts);
  $('mod-sheet').showModal();
}

// a card's files (one, or before a stock file every OS's): added, and the one
// that fits the stock file ticked
async function shopAdd(files, btn) {
  btn.disabled = true;
  btn.textContent = 'Adding…';
  const e = files[0];
  try {
    let ticked = false;
    for (const x of files) {
      const r0 = await fetch(new URL('shop/' + x.file, import.meta.url));
      if (!r0.ok) throw new Error(`${x.file}: ${r0.status} ${r0.statusText}`);
      const r = await addMod(x.file, await r0.arrayBuffer(), false, x.sha256);
      if (!r.ok) throw new Error(r.error);
      await refresh();
      if (dev() && r.mod.fits) {
        await tickWithCore(r.mod.path);
        ticked = true;
      }
    }
    remember();
    changed();
    toast(`${e.title} ${e.version} added` + (ticked ? ' and ticked.' : files.length > 1
      ? ` to your mods, for OS ${files.map(x => x.os).join(' and ')}.` : ' to your mods.'));
  } catch (err) {
    note('Not added: ' + err.message);
    renderLibrary();
  }
}

async function untick(paths) {
  for (const p of paths) st.enabled.delete(p);
  remember();
  changed();
}

// the base firmware's hint: which stock file the device you picked needs
function renderNeed() {
  const p = !dev() && cur();
  const d = !dev() && pickable().find(x => x.key === lib.device);
  $('stock-need').hidden = !((p && p.sha) || d);
  if (p && p.sha) $('stock-need').textContent = `Profile "${p.name}" uses ${osLabel(p)}: ${p.file}.`;
  else if (d) $('stock-need').textContent = `For the ${d.name}: Elektron's OS ${d.os} file.`;
}

function toast(text) {
  const t = el('div', { class: 'toast', role: 'status' }, text);
  document.body.append(t);
  setTimeout(() => t.classList.add('gone'), 4000);
  setTimeout(() => t.remove(), 4600);
}

// ---- the frame: the two views, your setup, the counts ----

function route() {
  const build = location.hash === '#build';
  $('view-library').hidden = build;
  $('view-build').hidden = !build;
  document.title = build ? 'Build · elekloader' : 'Mods · elekloader';
  $('content').scrollTop = 0;
  $('topbar').classList.remove('solid');
  window.scrollTo(0, 0);
  renderLibrary();
  renderChrome();
}

// a row in Your setup: a square, a title, a line under it
function setupRow({ thumb, title, sub, n = null, on, current, need, label, href, onclick }) {
  return el('li', {}, el(href ? 'a' : 'button', {
    class: ['row', on ? 'on' : '', current ? 'current' : '', need ? 'need' : ''].join(' '), 'aria-label': label,
    title: need ? 'Drop its stock OS file in to use this profile' : null,
    ...(href ? { href } : { type: 'button', onclick }) },
  thumb, el('span', { class: 'row-text' }, el('strong', {}, title), el('span', {}, sub)),
  n != null ? el('span', { class: 'n', title: 'Mods ticked' }, String(n)) : ''));
}

function renderChrome() {
  const s = st.stock, sd = dev();
  const n = [...st.enabled].map(desc).filter(d => d && !d.builtin).length;   // your mods; the core comes with them
  const build = location.hash === '#build';
  for (const id of ['cfg-count', 'nav-count', 'tab-count']) {
    $(id).textContent = String(n);
    $(id).classList.toggle('on', n > 0);
  }
  for (const [id, on] of [['nav-library', !build], ['nav-build', build], ['tab-library', !build], ['tab-build', build]]) {
    $(id).classList.toggle('on', on);
    if (on) $(id).setAttribute('aria-current', 'page'); else $(id).removeAttribute('aria-current');
  }
  $('cfg-btn').hidden = build;
  const p = cur();
  $('build-eyebrow').textContent = p ? 'Profile' : 'Build';
  $('build-title').textContent = p ? p.name : 'Your firmware';
  $('build-sub').textContent = sd
    ? `${sd.name} · OS ${s.os} · ${n} mod${n === 1 ? '' : 's'} ticked · changes save in this browser`
    : p && p.sha ? `${osLabel(p)}: drop its stock OS file in to use this profile.`
      : 'Drop in your stock OS file, check the mods you ticked, and build.';
  // the profiles, each with its stock OS under its name
  const rows = S.profiles.map(x => {
    const here = inUse(x);
    const th = el('span', { class: 'thumb profile' }, x.name.slice(0, 1).toUpperCase());
    th.style.setProperty('--h', String(Math.round(360 * seeded(x.id)())));
    const m = userMods(x).length;
    return setupRow({ thumb: th, title: x.name, n: x.sha ? m : null,
      sub: x.sha ? osLabel(x) : 'No stock OS yet',
      on: build && x.id === S.current, current: x.id === S.current, need: x.id === S.current && !here,
      label: `${x.name}: ${x.sha ? `${osLabel(x)}, ${m} mod${m === 1 ? '' : 's'}` : 'no stock OS yet'}`
        + (x.id === S.current && x.sha && !here ? ', its stock OS file is needed' : ''),
      onclick: () => { switchProfile(x.id); location.hash = '#build'; } });
  });
  if (!rows.length) rows.push(el('li', { class: 'side-empty' }, 'Your first stock OS file makes your first profile. + makes another.'));
  $('side-rows').replaceChildren(...rows);
  $('save-profile').disabled = st.busy;
}

// ---- profiles: a name, one stock OS, and the mods ticked for it ----

const cur = () => S.profiles.find(p => p.id === S.current) || null;
const inUse = p => !!(p.sha && st.stock && st.stock.ok && st.stock.sha256 === p.sha);
const osLabel = p => (p.device ? deviceName(p.device) + (p.os ? ' · OS ' + p.os : '') : 'No stock OS yet');
const userMods = p => (p.mods || []).filter(f => !f.startsWith('core-'));   // the core comes with them

function uniqueName(base) {
  let name = base;
  for (let i = 2; S.profiles.some(p => p.name === name); i++) name = `${base} ${i}`;
  return name;
}

// a new profile, with the stock OS given (set_stock's answer) or none yet
function makeProfile(name, stock = null) {
  const p = { id: newId(), name, device: stock ? stock.dev.key : null, os: stock ? stock.os : null,
    sha: stock ? stock.sha256 : null, file: stock ? stock.file : null, mods: [] };
  S.profiles.push(p);
  return p;
}

// the window's _remember: the ticked mods are the current profile's
function remember() {
  const p = cur();
  if (!p || !inUse(p)) return;
  const away = p.mods.filter(f => !st.mods.some(d => d.file === f));   // named, not added here
  p.mods = [...new Set([...st.enabled].map(base).concat(away))].sort();
  saveSettings();
}

// a profile's mods ticked: the ones that are here and fit
function tickProfile(p, warn) {
  st.enabled = new Set(st.mods.filter(d => d.fits && p.mods.includes(d.file)).map(d => d.path));
  const missing = p.mods.filter(f => !st.mods.some(d => d.file === f));
  if (warn && missing.length) note('This profile also names mods that are not added here: ' + missing.join(', '));
}

// a profile's first ticks: the newest core, and (unless it starts empty) the mods you added that fit
async function freshTicks(withMods) {
  const fits = st.mods.filter(d => d.fits);
  const cores = fits.filter(d => d.id === 'core').sort((a, b) => a.file.localeCompare(b.file));
  let on = cores.length ? [cores[cores.length - 1].path] : [];
  if (withMods) {
    for (const d of fits.filter(x => !x.builtin && x.format === 2 && x.id !== 'core')) {
      on = await engine.call('tick', { enabled: on, path: d.path });
    }
  }
  return new Set(on);
}

// another profile: its stock OS in (from this visit or this browser), then its mods;
// without its file here, the page asks for it
async function switchProfile(id) {
  const p = S.profiles.find(x => x.id === id);
  if (!p || st.busy) return;
  S.current = p.id;
  saveSettings();
  if (inUse(p)) {
    tickProfile(p, true);
    renderProfiles();
    changed();
    return;
  }
  let f = p.sha && st.stockFiles.get(p.sha);
  if (!f && p.sha && S.remember) {
    try { f = await Files.get('stock:' + p.sha); } catch { /* not kept */ }
  }
  if (f) {
    await setStock(f.name, f.data);
    return;
  }
  st.stock = null;
  st.enabled.clear();
  if (p.device) lib.device = p.device;
  renderStock();
  renderLibrary();
  renderCheck(null);
  renderProfiles();
  changed();
}

// ---- actions ----------------------------------------------------------------------------

async function boot() {
  const t0 = performance.now();
  const tick = setInterval(() => {
    $('engine').textContent = `Starting the build engine… ${secs(performance.now() - t0)}`;
  }, 200);
  try {
    const r = await engine.call('init');
    st.info = r.info;
    st.build = r.build;
    const got = r.fetched.filter(f => /\/(pyodide\/|elekloader\.zip|bridge\.py|core\/|build\.json)/.test(f.url));
    const over = got.reduce((a, f) => a + f.transferred, 0);
    $('engine').textContent = `Engine ready: elekloader ${st.info.version}, Python ${r.python}, `
      + `loaded in ${secs(performance.now() - t0)}`
      + (over ? `, ${mb(over)} downloaded` : ', from the cache');
    $('engine').classList.add('ok');
    renderAbout(r);
    st.ready = true;
    renderLibrary();                   // its devices, and its Add buttons on
  } catch (e) {
    $('engine').textContent = 'The build engine did not load: ' + e.message;
    $('engine').classList.add('bad');
    return;
  } finally {
    clearInterval(tick);
  }
  if (S.remember) {
    $('remember').checked = true;
    $('forget').hidden = false;
    try {
      const kept = await Files.all();
      for (const [k, v] of kept) if (k.startsWith('mod:')) await addMod(v.name, v.data, false);
      const p = cur();
      const s = (p && p.sha && kept.find(([k]) => k === 'stock:' + p.sha)) || kept.find(([k]) => k === 'stock');
      if (s) {
        if (s[0] === 'stock') Files.del('stock').catch(() => {});   // kept as stock:<sha256> from now on
        await setStock(s[1].name, s[1].data);
      }
    } catch (e) {
      note('Your kept files could not be read from this browser: ' + e.message);
    }
  }
  await refresh();
}

async function setStock(name, data) {
  $('stock').hidden = false;
  $('stock').replaceChildren(el('p', { class: 'muted' }, `Reading ${name}…`));
  const r = await engine.call('set_stock', { name }, data);
  st.stock = r;
  if (r.ok) {
    st.stockFiles.set(r.sha256, { name, data });
    if (S.remember) Files.put('stock:' + r.sha256, { name, data }).catch(() => {});
  }
  await refresh();
  if (r.ok) {
    const k = r.dev.key;
    // one stock OS per profile: the current one takes this file if it has none yet; another
    // file goes to the profile that has it, or to a new one
    let p = cur();
    let fresh = false;
    if (p && !p.sha && (!p.device || p.device === k)) {
      Object.assign(p, { device: k, os: r.os, sha: r.sha256, file: r.file });
      fresh = !p.mods.length;
      if (fresh) st.enabled = await freshTicks(!p.empty); else tickProfile(p, false);
      delete p.empty;
    } else if (p && p.sha === r.sha256) {
      tickProfile(p, false);
    } else {
      const had = p;
      p = S.profiles.find(x => x.sha === r.sha256);
      if (p) {
        tickProfile(p, false);
      } else {
        p = makeProfile(uniqueName(had ? `${r.dev.name} ${r.os}` : 'Default'), r);
        st.enabled = await freshTicks(true);
        fresh = true;
      }
      if (had) toast(`Profile "${p.name}": ${osLabel(p)}. Each profile keeps its own stock OS.`);
    }
    S.current = p.id;
    if (fresh) remember(); else saveSettings();
    $('version').value = S.versions[k] || r.dev.default_version;
    st.nameEdited = false;
    lib.device = k;                    // the library follows the stock file
  } else {
    st.enabled.clear();
  }
  renderStock();
  renderLibrary();
  renderCheck(null);                   // no stale result while the check runs again
  renderProfiles();
  await versionChanged();
  changed();
}

// sha256: from the shop, the file it lists (the worker refuses any other)
async function addMod(name, data, tickIt = true, sha256 = null) {
  const r = await engine.call('add_mod', sha256 ? { name, sha256 } : { name }, data);
  if (!r.ok) return r;
  st.modFiles.set(r.mod.file, data);
  if (S.remember) Files.put('mod:' + r.mod.file, { name: r.mod.file, data }).catch(() => {});
  if (tickIt && dev() && r.mod.fits) {
    st.enabled = new Set(await engine.call('tick', { enabled: [...st.enabled], path: r.mod.path }));
  }
  return r;
}

// Tick a mod with what it requires (gui.with_requirements). A shop mod that
// needs a newer core than the one ticked gets the newest core that fits, in
// its place: a build has one core.
async function tickWithCore(p) {
  const d = desc(p);
  const want = d && (shopItem(d) || {}).needs_core;
  if (want) {
    const cores = st.mods.filter(x => x.id === 'core' && x.fits);
    const on = cores.find(x => st.enabled.has(x.path));
    if (on && cmpVer(on.version, want) < 0) {
      const best = cores.filter(x => cmpVer(x.version, want) >= 0)
        .sort((a, b) => cmpVer(a.version, b.version)).pop();
      if (best) {
        st.enabled.delete(on.path);
        st.enabled.add(best.path);
        toast(`Core ${on.version} → ${best.version}: ${d.title} needs core ${want} or newer.`);
      }
    }
  }
  st.enabled = new Set(await engine.call('tick', { enabled: [...st.enabled], path: p }));
}

async function addMods(files) {
  const bad = [];
  for (const f of files) {
    const r = await addMod(f.name, await f.arrayBuffer());
    if (!r.ok) bad.push(r.error);
  }
  await refresh();
  remember();
  changed();
  if (bad.length) note('Not added:\n' + bad.join('\n'));
}

async function removeMod(p) {
  return removeMods([p]);
}

// several files, one question (a shop card's files for each OS)
async function removeMods(paths) {
  const ds = paths.map(desc).filter(d => d && !d.builtin);
  if (!ds.length) return;
  if (!confirm(`Remove ${ds[0].title} (${ds.map(d => d.file).join(', ')})?`)) return;
  for (const d of ds) {
    await engine.call('remove_mod', { path: d.path });
    for (const p of S.profiles) p.mods = p.mods.filter(f => f !== d.file);
    st.modFiles.delete(d.file);
    Files.del('mod:' + d.file).catch(() => {});
    st.enabled.delete(d.path);
    if (st.selected === d.path) st.selected = null;
  }
  await refresh();
  remember();
  changed();
}

async function toggle(p) {
  const d = desc(p);
  if (!d || st.busy || !dev()) return;
  if (st.enabled.has(p)) st.enabled.delete(p);
  else if (d.fits) await tickWithCore(p);
  else return;                                      // made for other firmware
  remember();
  changed();
}

async function refresh() {
  if (!st.ready) return;
  st.mods = await engine.call('mods');
  const have = new Set(st.mods.map(d => d.path));
  st.enabled = new Set([...st.enabled].filter(p => have.has(p)));
  renderMods();
}

// a change to the ticked mods: check again, after a pause (the window waits 120 ms)
let pending = null;
function changed() {
  renderMods();
  renderCheck(null);                   // "Checking…" from now: the last result is stale
  clearTimeout(pending);
  pending = setTimeout(runCheck, 120);
  versionChanged();
}

async function runCheck() {
  if (!st.ready) return;
  const paths = [...st.enabled].sort();
  st.checking = paths.join('\n');
  renderCheck(null);
  const r = await engine.call('check', { enabled: paths });
  if (st.checking !== [...st.enabled].sort().join('\n')) return;   // stale: a newer one is coming
  st.check = r;
  st.checkedFor = st.checking;
  renderMods();
  renderCheck(r);
}

async function versionChanged() {
  if (!st.ready || !dev()) return renderBuildButton();
  const v = $('version').value;
  const r = await engine.call('version', { version: v, enabled: [...st.enabled].sort() });
  if (v !== $('version').value) return;
  st.versionOk = r.ok;
  $('version-error').hidden = r.ok;
  $('version-error').textContent = r.ok ? '' : r.error;
  if (!st.nameEdited) $('out-name').value = r.name;
  if (r.ok) { S.versions[dev().key] = v; saveSettings(); }
  renderBuildButton();
}

async function build() {
  const paths = [...st.enabled].sort();
  st.busy = true;
  for (const u of st.urls) URL.revokeObjectURL(u);
  st.urls = [];
  $('step-result').hidden = true;
  renderBuildButton();
  renderMods();
  const t0 = performance.now();
  const log = $('progress-log');
  log.replaceChildren();
  $('progress').hidden = false;
  $('progress').classList.add('running');
  let stage = 'Reading the stock file and the mods';
  const stages = [
    [/^stock:/, 'Loading the mods', 0.06],
    [/^the mods combine/, 'Linking', 0.14],
    [/^linked /, 'Packing the main OS (the longest step)', 0.18],
    [/^packed /, 'Writing the files and verifying them', 0.8],
    [/^verified/, 'Saving', 0.97],
  ];
  let frac = 0.02;
  let over = false;
  const show = () => {
    $('progress-stage').textContent = `${stage}${over ? ':' : '…'} ${secs(performance.now() - t0)}`;
    $('progress-fill').style.width = (100 * frac).toFixed(1) + '%';
  };
  show();
  const timer = setInterval(show, 100);
  const onlog = (line, t) => {
    log.append(el('li', {}, el('span', { class: 't' }, secs(t)), ' ', line));
    for (const [re, next, f] of stages) {
      if (re.test(line)) { stage = next; frac = f; }
    }
    if (/^the mods combine/.test(line) && !paths.some(p => (desc(p) || {}).format === 2)) {
      stage = 'Packing the main OS (the longest step)';
    }
    show();
  };
  try {
    const r = await engine.call('build', {
      enabled: paths, version: $('version').value, name: $('out-name').value,
    }, null, onlog);
    clearInterval(timer);
    frac = 1;
    over = true;
    stage = r.ok ? 'Built and verified' : 'Not built';
    show();
    renderResult(r, performance.now() - t0);
  } catch (e) {
    clearInterval(timer);
    over = true;
    stage = 'Not built';
    show();
    renderResult({ ok: false, error: e.message, log: [] }, performance.now() - t0);
  } finally {
    $('progress').classList.remove('running');
    st.busy = false;
    renderBuildButton();
    renderMods();
  }
}

// ---- rendering ----------------------------------------------------------------------------

function note(text) {
  alert(text);
}

function renderAbout(r) {
  const b = r.build || {};
  const commit = b.commit ? b.commit.slice(0, 7) : '';
  $('about').replaceChildren(...[
    `elekloader ${st.info.version}`,
    b.release ? (b.same_as_release ? ` (the package of release ${b.release})`
      : ` (newer than release ${b.release}: the package as of`) : '',
    commit ? [b.release && !b.same_as_release ? ' ' : ' · commit ',
      el('a', { href: `https://github.com/irpina/elekloader/commit/${b.commit}`, rel: 'noreferrer' }, commit),
      b.release && !b.same_as_release ? ')' : ''] : '',
    ` · Python ${r.python} in Pyodide ${r.pyodide}`,
    b.zip_sha256 ? ` · elekloader.zip sha256 ${b.zip_sha256.slice(0, 16)}…` : '',
  ].flat());
}

function renderStock() {
  const s = st.stock;
  const box = $('stock');
  if (!s) { box.hidden = true; return; }
  box.hidden = false;
  if (s.ok) {
    box.className = 'stock ok';
    box.replaceChildren(
      el('p', { class: 'big' }, `✓ ${s.device} · OS ${s.os}`),
      el('p', { class: 'muted' }, `${s.file} · sha256 ${s.sha256}`),
      el('p', { class: 'muted' }, s.dev.card_file
        ? 'You get a .syx and the card file (.bin) for this device.'
        : 'You get a .syx for this device.'),
    );
  } else {
    box.className = 'stock bad';
    box.replaceChildren(
      el('p', { class: 'big' }, `✗ ${s.file} is not a stock OS file elekloader knows`),
      el('p', {}, s.error),
      s.supported ? el('p', { class: 'muted' }, 'Supported: ' + s.supported + '.') : '',
    );
  }
}

function rowStatus(d) {
  const on = st.enabled.has(d.path);
  if (d.error) return ['err', 'Invalid file'];
  if (!d.fits && dev()) return ['off', 'For ' + (d.for_label || '?')];
  if (!on) return ['off', dev() ? 'Disabled' : 'Choose your stock file'];
  const s = st.check && st.check.status && st.check.status[d.path];
  return s || ['off', 'Checking…'];
}

function renderMods() {
  const rows = $('mod-rows');
  const order = (st.check && st.check.load_order) || {};
  let hidden = 0;
  const shown = st.mods.filter(d => {
    const other = !d.error && !d.fits && dev();
    if (other && !st.enabled.has(d.path) && !S.showOther) { hidden++; return false; }
    return true;
  });
  shown.sort((a, b) => {
    const oa = order[a.path] || 0, ob = order[b.path] || 0;
    return ((oa === 0) - (ob === 0)) || (oa - ob) || ((a.id !== 'core') - (b.id !== 'core'))
      || a.id.localeCompare(b.id) || a.file.localeCompare(b.file);
  });
  rows.replaceChildren(...shown.map(d => {
    const on = st.enabled.has(d.path);
    const [cls, text] = rowStatus(d);
    const box = el('input', {
      type: 'checkbox', checked: on, disabled: st.busy || !dev() || (!d.fits && !on),
      'aria-label': (on ? 'Disable ' : 'Enable ') + d.title,
      onchange: () => toggle(d.path),
    });
    return el('tr', {
      class: ['row-' + cls, st.selected === d.path ? 'sel' : ''].join(' '),
      onclick: e => {
        if (e.target.closest('input,button')) return;
        st.selected = d.path;
        renderMods();
      },
    },
    el('td', { class: 'on' }, box),
    el('td', {}, el('span', { class: 'title' }, d.title || d.file),
      el('span', { class: 'file' }, d.builtin ? `${d.file} · built in`
        : shopItem(d) ? `${d.file} · from the shop` : d.file)),
    el('td', {}, d.version || ''),
    el('td', {}, el('span', { class: 'pill ' + cls }, text)),
    el('td', { class: 'num' }, d.error ? '' : kb(d.ram || 0)),
    el('td', { class: 'num' }, order[d.path] || ''),
    el('td', { class: 'x' }, d.builtin ? '' : el('button', {
      type: 'button', class: 'remove', title: 'Remove ' + d.file, 'aria-label': 'Remove ' + d.file,
      disabled: st.busy, onclick: () => removeMod(d.path),
    }, '×')));
  }));
  if (!shown.length) {
    rows.append(el('tr', {}, el('td', { colspan: 7, class: 'empty' },
      dev() ? 'No mods for this firmware yet: add one from the library, or your own .elemod file, below.'
        : 'Add mods from the library, or your own .elemod files, below.')));
  }
  const n = shown.filter(d => st.enabled.has(d.path)).length;
  $('mod-count').textContent = `${n} of ${shown.length} mods enabled`
    + (hidden ? ` · ${hidden} for other firmware hidden` : '');
  $('enable-all').disabled = $('disable-all').disabled = st.busy || !dev();
  renderDetails();
  renderLibrary();                     // what is owned and ticked shows on its cards
  renderChrome();
}

function renderDetails() {
  const box = $('details');
  const d = st.selected && desc(st.selected);
  if (!d) { box.replaceChildren(el('p', { class: 'muted' }, 'Select a mod to see what it does and what it changes.')); return; }
  box.replaceChildren(...detailParts(d));
}

// what a mod file says about itself (the build view's details, and a card's sheet)
function detailParts(d) {
  const [cls, text] = rowStatus(d);
  const sec = (title, ...kids) => [el('h4', {}, title), ...kids];
  const parts = [
    el('h3', {}, d.title || d.file),
    el('p', { class: 'muted' }, [d.id, d.version && 'version ' + d.version, d.category, d.file].filter(Boolean).join(' · ')),
    el('span', { class: 'pill ' + cls }, text.toUpperCase()),
  ];
  if (d.error) {
    parts.push(el('p', { class: 'bad' }, d.error));
  } else {
    parts.push(el('p', { class: 'desc' }, d.description || 'No description.'));
    if (d.format === 1) {
      parts.push(...sec('Whole build', el('p', { class: 'muted' },
        'This file is one complete CFW build. It cannot be combined with separate mods.')));
    }
    parts.push(...sec('For', el('p', { class: d.fits ? '' : 'warn' }, d.for_label || '?')));
    const ids = new Set([...st.enabled].map(p => (desc(p) || {}).id));
    parts.push(...sec('Requires', d.requires.length
      ? el('ul', {}, d.requires.map(r => el('li', { class: ids.has(r) ? 'ok' : 'bad' },
        (ids.has(r) ? '✓ ' : '✗ ') + r + (ids.has(r) ? '  enabled' : '  not enabled'))))
      : el('p', { class: 'muted' }, 'Nothing.')));
    if (d.conflicts.length) parts.push(...sec('Incompatible with', el('p', { class: 'muted' }, d.conflicts.join(', '))));
    const mem = [];
    if (d.ram) mem.push(kb(d.ram) + ' of RAM');
    if (d.fast) mem.push(d.fast + ' bytes of fast SRAM');
    for (const [name, lo, hi] of d.regions || []) mem.push(`${name}: ${hex(lo)}-${hex(hi)}`);
    if (mem.length) parts.push(...sec('Memory', el('p', { class: 'muted' }, mem.join('; '))));
    parts.push(...sec(`Patch sites in the main OS (${d.sites.length})`, el('ul', { class: 'sites' },
      d.sites.map(([addr, n, kind, tgt]) => el('li', {}, el('code', {}, hex(addr)),
        ` ${n} bytes, ${kind}${tgt ? '  → ' + tgt : ''}`)))));
    if (d.events && d.events.length) {
      parts.push(...sec('Handles (through core)', el('ul', {}, d.events.map(([ev, ord, fn]) =>
        el('li', {}, `${ev} → ${fn} (order ${ord})`)))));
    }
    if (d.adds_to && d.adds_to.length) parts.push(...sec('Adds entries to', el('p', { class: 'muted' }, d.adds_to.join(', '))));
    if (d.tables && d.tables.length) parts.push(...sec('Provides tables', el('p', { class: 'muted' }, d.tables.join(', '))));
    if (d.names && d.names.length) parts.push(...sec('Claims', el('p', { class: 'muted' }, d.names.join(', '))));
    parts.push(...sec('Licence', el('p', { class: 'muted' }, d.license || 'not stated')));
    parts.push(...sec('File', el('p', { class: 'muted mono' }, `${d.file}\nsha256 ${d.sha256}`)));
  }
  return parts;
}

function renderCheck(r) {
  const box = $('check');
  if (!dev()) {
    box.replaceChildren(el('p', { class: 'muted' }, 'Choose your stock OS file first.'));
  } else if (!r) {
    box.replaceChildren(el('p', { class: 'muted' }, 'Checking…'));
  } else if (r.ok) {
    const kids = [el('p', { class: 'head ok' },
      `✓ No conflicts: ${r.order.length} mods, ${r.sites} patch sites. Ready to build.`)];
    if (r.format === 2) {
      kids.push(el('p', { class: 'muted' }, 'Load order (fixed by the linker, the same result in any order): '
        + r.order.join('  ›  ')));
      const meter = (label, [used, size], fmt) => el('div', { class: 'meter' },
        el('span', { class: 'label' }, label),
        el('span', { class: 'track' }, el('span', { class: 'fill' })),
        el('span', { class: 'muted' }, size ? fmt(used, size) : 'none on this device'));
      const ram = meter('RAM', r.ram, (u, s) => `${(u / 1024).toFixed(1)} / ${(s / 1024).toFixed(0)} KB`);
      const fast = meter('Fast SRAM', r.fast, (u, s) => `${u} / ${s} bytes`);
      ram.querySelector('.fill').style.width = (r.ram[1] ? 100 * r.ram[0] / r.ram[1] : 0) + '%';
      fast.querySelector('.fill').style.width = (r.fast[1] ? 100 * r.fast[0] / r.fast[1] : 0) + '%';
      kids.push(ram, fast);
    } else {
      kids.push(el('p', { class: 'muted' }, `A whole build: ${r.order.join(', ')}.`));
    }
    kids.push(el('p', { class: 'muted small' }, `Checked in ${r.ms} ms.`));
    box.replaceChildren(...kids);
  } else {
    box.replaceChildren(
      el('p', { class: 'head ' + (r.empty ? 'muted' : 'bad') }, (r.empty ? '' : '⚠ ') + r.headline),
      r.problems.length ? el('ul', { class: 'problems' }, r.problems.map(x => el('li', {}, x))) : '',
      r.empty ? el('p', { class: 'muted' }, 'Tick mods in the list to enable them.') : '',
    );
  }
  renderBuildButton();
}

function renderBuildButton() {
  const d = dev();
  $('version-rule').textContent = d
    ? (d.exact_len ? `exactly ${d.version_len} characters` : `1 to ${d.version_len} characters`) : '';
  $('build').disabled = !(st.ready && d && st.check && st.check.ok && st.versionOk && !st.busy
    && st.checkedFor === [...st.enabled].sort().join('\n'));
  $('build').textContent = st.busy ? 'Building…' : 'Build firmware';
  for (const id of ['version', 'out-name']) $(id).disabled = st.busy || !d;
  for (const id of ['add-mods', 'save-profile', 'profile']) $(id).disabled = st.busy;
  $('delete-profile').disabled = st.busy || !cur();
}

function renderProfiles() {
  const sel = $('profile');
  sel.replaceChildren(...S.profiles.map(p => el('option', { value: p.id }, `${p.name} (${osLabel(p)})`)));
  sel.value = S.current || '';
  renderChrome();
}


function renderResult(r, ms) {
  $('step-result').hidden = false;
  const box = $('result');
  if (!r.ok) {
    box.replaceChildren(
      el('p', { class: 'head bad' }, '✗ The firmware was not built'),
      el('pre', { class: 'error' }, r.error),
      el('p', { class: 'muted small' }, `After ${secs(ms)}.`),
    );
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  const d = dev();
  const facts = [
    ['Device', `${r.device}, OS ${r.os}`],
    ['Mods', r.mods.join(', ')],
    ['OS version shown', r.version],
    ['sha256 (.syx)', r.sha256],
    ['Size', mb(r.bytes)],
    ['Untouched', r.untouched.join('; ')],
    ['Main OS', r.gap != null ? `unpacks in place with ${(r.gap / 1024).toFixed(0)} KB to spare`
      : `depacks to the patched image (${r.inplace})`],
    ['Flash', `ends ${r.flash_end}, ${(r.headroom / 1048576).toFixed(1)} MB to spare`],
    ['Built in', `${secs(ms)}, in this browser`],
  ];
  const ack = el('input', { type: 'checkbox', id: 'ack' });
  const links = el('div', { class: 'downloads' }, r.files.map(f => {
    const url = URL.createObjectURL(new Blob([f.data], {
      type: f.name.endsWith('.json') ? 'application/json' : 'application/octet-stream' }));
    st.urls.push(url);
    const main = /\.(syx|bin)$/.test(f.name);
    return el('a', { class: 'dl ' + (main ? 'main' : ''), href: url, download: f.name,
      'aria-disabled': 'true', tabindex: '-1' },
    el('span', {}, `Download ${f.name}`),
    el('span', { class: 'muted small' }, `${main ? mb(f.bytes) : kb(f.bytes)} · sha256 ${f.sha256.slice(0, 16)}…`));
  }));
  const gate = () => {
    for (const a of links.querySelectorAll('a')) {
      a.setAttribute('aria-disabled', ack.checked ? 'false' : 'true');
      a.tabIndex = ack.checked ? 0 : -1;
    }
  };
  links.addEventListener('click', e => { if (!ack.checked) e.preventDefault(); });
  ack.addEventListener('change', gate);
  box.replaceChildren(
    el('p', { class: 'head ok' }, '✓ Firmware built and verified'),
    el('table', { class: 'facts' }, facts.map(([k, v]) => el('tr', {}, el('th', {}, k),
      el('td', { class: k.startsWith('sha') ? 'mono' : '' }, v)))),
    el('div', { class: 'recovery' },
      el('h3', {}, 'Before you flash: how to get back to stock'),
      el('p', {}, 'Only the main OS changes and the bootloader is never touched, so your stock OS '
        + 'file always recovers the unit. If the custom OS does not start: '
        + (r.recovery || (d && d.recovery) || 'see the README') + '.'),
      el('p', {}, 'Flash it like any OS update, with your own SysEx tool or, for the Octatrack, '
        + 'the card. This page never talks to your device. ',
      el('a', { href: 'https://github.com/irpina/elekloader#flash-it', rel: 'noreferrer' },
        'How to flash, and how to recover')),
      el('label', { class: 'ack' }, ack, ' I know how to get my unit back to stock')),
    links,
    el('details', {}, el('summary', {}, 'The build log'),
      el('ol', { class: 'log' }, r.log.map(([t, line]) => el('li', {}, el('span', { class: 't' }, t.toFixed(2) + ' s'), ' ', line)))),
  );
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---- New profile: a name, and the stock OS in now or another file ----

function openNewProfile() {
  const sd = dev();
  $('ps-name').value = uniqueName(S.profiles.length ? 'Profile' : 'Default');
  $('ps-same-row').hidden = !sd;
  $('ps-same-label').textContent = sd ? `${sd.name} · OS ${st.stock.os}` : '';
  $(sd ? 'ps-same' : 'ps-other').checked = true;
  $('ps-error').hidden = true;
  renderNewProfile();
  $('profile-sheet').showModal();
  $('ps-name').select();
}

function renderNewProfile() {
  $('ps-copy-row').hidden = !(dev() && $('ps-same').checked);
}

async function createProfile() {
  const name = $('ps-name').value.trim();
  const clash = S.profiles.some(p => p.name === name);
  $('ps-error').hidden = !!name && !clash;
  $('ps-error').textContent = !name ? 'Give it a name.' : 'There is a profile with that name already.';
  if (!name || clash) return;
  const same = dev() && $('ps-same').checked;
  const copy = $('ps-copy').checked;
  $('profile-sheet').close();
  if (same) {
    const p = makeProfile(name, st.stock);
    S.current = p.id;
    if (!copy) st.enabled = await freshTicks(false);
    remember();
    renderProfiles();
    changed();
    toast(`Profile "${name}": ${osLabel(p)}.`);
  } else {
    const p = makeProfile(name);
    p.empty = true;                    // its stock file ticks the core only
    await switchProfile(p.id);
    location.hash = '#build';
    toast(`Profile "${name}" made. Now drop in its stock OS file.`);
  }
}

// ---- wiring ---------------------------------------------------------------------------------

const STOCK_MAX = 64 << 20, MOD_MAX = 16 << 20;

async function takeFiles(list) {
  if (!st.ready) { note('The build engine is still loading. Try again in a moment.'); return; }
  if (st.busy) { note('Wait for the build to finish.'); return; }
  const files = [...list];
  const exts = (st.info.exts || ['.elemod', '.dtmod']);
  const mods = files.filter(f => exts.some(x => f.name.toLowerCase().endsWith(x)));
  const rest = files.filter(f => !mods.includes(f));
  const big = mods.filter(f => f.size > MOD_MAX).concat(rest.filter(f => f.size > STOCK_MAX));
  if (big.length) note('Too large to be a stock OS file or a mod: ' + big.map(f => f.name).join(', '));
  const okMods = mods.filter(f => f.size <= MOD_MAX);
  if (okMods.length) await addMods(okMods);
  const stock = rest.filter(f => f.size <= STOCK_MAX);
  if (stock.length > 1) note('Drop one stock OS file at a time.');
  else if (stock.length) await setStock(stock[0].name, await stock[0].arrayBuffer());
}

function wire() {
  // a drop zone opens its file chooser on a click or Enter (a drop anywhere is taken below)
  for (const [drop, input] of [['stock-drop', 'stock-file'], ['start-drop', 'stock-file'], ['mods-drop', 'mod-files']]) {
    $(drop).addEventListener('click', () => $(input).click());
    $(drop).addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $(input).click(); } });
  }
  $('stock-file').addEventListener('change', e => { takeFiles(e.target.files); e.target.value = ''; });
  $('add-mods').addEventListener('click', () => $('mod-files').click());
  $('mod-files').addEventListener('change', e => { takeFiles(e.target.files); e.target.value = ''; });
  // drop anywhere: mods by their extension, anything else as the stock file
  document.addEventListener('dragover', e => { e.preventDefault(); document.body.classList.add('dragging'); });
  document.addEventListener('dragleave', e => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
  document.addEventListener('drop', e => {
    e.preventDefault();
    document.body.classList.remove('dragging');
    if (e.dataTransfer && e.dataTransfer.files.length) takeFiles(e.dataTransfer.files);
  });
  $('enable-all').addEventListener('click', () => {
    st.enabled = new Set(st.mods.filter(d => d.format === 2 && d.fits).map(d => d.path));
    remember();
    changed();
  });
  $('disable-all').addEventListener('click', () => { st.enabled.clear(); remember(); changed(); });
  $('show-other').checked = S.showOther;
  $('show-other').addEventListener('change', e => { S.showOther = e.target.checked; saveSettings(); renderMods(); });
  $('profile').addEventListener('change', e => switchProfile(e.target.value));
  $('save-profile').addEventListener('click', openNewProfile);
  $('ps-create').addEventListener('click', createProfile);
  $('ps-cancel').addEventListener('click', () => $('profile-sheet').close());
  $('ps-name').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); createProfile(); } });
  for (const id of ['ps-same', 'ps-other']) $(id).addEventListener('change', renderNewProfile);
  $('delete-profile').addEventListener('click', async () => {
    const p = cur();
    if (!p || !confirm(`Delete the profile "${p.name}"? (Its mods stay added.)`)) return;
    S.profiles = S.profiles.filter(x => x !== p);
    if (p.sha && !S.profiles.some(x => x.sha === p.sha)) Files.del('stock:' + p.sha).catch(() => {});
    const next = S.profiles.find(inUse) || S.profiles[0];
    if (next) {
      await switchProfile(next.id);
    } else {                                 // none left: the stock file in makes a Default
      S.current = dev() ? makeProfile('Default', st.stock).id : null;
      remember();
      saveSettings();
      renderProfiles();
    }
  });
  $('version').addEventListener('input', () => versionChanged());
  $('out-name').addEventListener('input', () => { st.nameEdited = $('out-name').value.trim() !== ''; });
  $('build').addEventListener('click', build);
  $('remember').checked = S.remember;
  $('remember').addEventListener('change', async e => {
    S.remember = e.target.checked;
    saveSettings();
    $('forget').hidden = !S.remember;
    try {
      if (S.remember) {
        for (const [sha, f] of st.stockFiles) await Files.put('stock:' + sha, f);
        for (const [name, data] of st.modFiles) await Files.put('mod:' + name, { name, data });
      } else {
        await Files.clear();
      }
    } catch (err) {
      note('This browser would not keep the files: ' + err.message);
    }
  });
  $('forget').addEventListener('click', async () => {
    S.remember = false;
    saveSettings();
    $('remember').checked = false;
    $('forget').hidden = true;
    try { await Files.clear(); } catch { /* nothing kept */ }
  });
  $('search').addEventListener('input', e => {
    lib.query = e.target.value;
    if (location.hash === '#build') location.hash = '#library';
    renderLibrary();
  });
  $('f-sort').addEventListener('change', e => setFilter('sort', e.target.value || 'collection'));
  // the sheets: their close buttons, and a click on the backdrop
  for (const [sheet, close] of [['mod-sheet', 'sheet-close'], ['about-sheet', 'about-close'], ['profile-sheet', 'ps-close']]) {
    $(close).addEventListener('click', () => $(sheet).close());
    $(sheet).addEventListener('click', e => { if (e.target === $(sheet)) $(sheet).close(); });
  }
  for (const id of ['about-open', 'tab-about']) $(id).addEventListener('click', () => $('about-sheet').showModal());
  // the top bar goes solid once the page scrolls under it
  $('content').addEventListener('scroll', () => $('topbar').classList.toggle('solid', $('content').scrollTop > 48),
    { passive: true });
  window.addEventListener('hashchange', route);
}

wire();
route();
renderMods();
renderBuildButton();
loadShop();
boot();
