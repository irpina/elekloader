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
// profiles: {device key: {name: [file names]}}; profile: {device key: name};
// versions: {device key: the last version field}
const S = Object.assign({ profiles: {}, profile: {}, versions: {}, remember: false, showOther: false },
  (() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } })());

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
  stockFile: null,        // {name, data}: the page's copy, for IndexedDB
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
const lib = { device: S.libDevice || null, type: S.libType || null, sort: S.libSort || 'collection', query: '' };
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
      available: g.some(x => x.available) });
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
  if (st.info) return st.info.devices.map(d => ({ key: d.key, name: d.name, os: d.releases.join(' or ') }));
  const seen = new Map();
  for (const e of shop.items) {
    if (!seen.has(e.device)) seen.set(e.device, { key: e.device, name: e.device_name || e.device, os: e.os || '' });
  }
  return [...seen.values()];
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

// a cover's line: drawn from the mod's kind, varied by its name
function trace(en) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 200 100');
  svg.setAttribute('aria-hidden', 'true');
  const add = (tag, a) => {
    const e = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(a)) e.setAttribute(k, String(v));
    svg.append(e);
  };
  const rnd = seeded(en.id + en.device);
  const line = { fill: 'none', stroke: 'currentColor', 'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' };
  const faint = { stroke: 'currentColor', 'stroke-opacity': 0.4, 'stroke-width': 1.5, 'stroke-dasharray': '3 5' };
  const pts = [];
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

// ---- the library: the kinds in the sidebar, device chips, a shelf per kind ----

const KIND_HUE = { Sampling: 196, Performance: 268, Framework: 24, 'Whole build': 140 };

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
  const forDev = lib.device ? all.filter(en => en.device === lib.device) : all;
  const kinds = [...new Set(all.filter(en => !en.own).map(en => en.category).filter(Boolean))];
  const ownN = forDev.filter(en => en.own).length;
  $('nav-types').replaceChildren(
    kindItem('All mods', forDev.length, inLib && !lib.type, () => setFilter('type', null), el('span', { class: 'swatch all' })),
    ...kinds.map(k => kindItem(k, forDev.filter(en => !en.own && en.category === k).length, inLib && lib.type === k,
      () => setFilter('type', k), swatchFor(k))),
    ownN || lib.type === OWN ? kindItem('Your files', ownN, inLib && lib.type === OWN, () => setFilter('type', OWN),
      el('span', { class: 'swatch own' })) : '');
  $('device-buttons').replaceChildren(...[{ key: null, name: 'All' }, ...devs].map(d => {
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
      : `No mods ${chosen ? 'for the ' + chosen.name + ' ' : ''}here yet. Add your own with + Your .elemod.`));
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
  cover.style.setProperty('--h', String(Math.round((KIND_HUE[en.category] ?? 330) + 36 * seeded(en.id)() - 18)));
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
  const d = !dev() && pickable().find(x => x.key === lib.device);
  $('stock-need').hidden = !d;
  if (d) $('stock-need').textContent = `For the ${d.name}: Elektron's OS ${d.os} file.`;
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
function setupRow({ thumb, title, sub, on, current, href, onclick }) {
  return el('li', {}, el(href ? 'a' : 'button', { class: ['row', on ? 'on' : '', current ? 'current' : ''].join(' '),
    ...(href ? { href } : { type: 'button', onclick }) },
  thumb, el('span', { class: 'row-text' }, el('strong', {}, title), el('span', {}, sub))));
}

function renderChrome() {
  const s = st.stock, sd = dev();
  const n = st.enabled.size;
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
  const prof = sd && S.profile[sd.key];
  $('build-eyebrow').textContent = prof ? 'Profile' : 'Build';
  $('build-title').textContent = prof || 'Your firmware';
  $('build-sub').textContent = sd
    ? `${sd.name} · OS ${s.os} · ${n} mod${n === 1 ? '' : 's'} ticked · changes save in this browser`
    : 'Drop in your stock OS file, check the mods you ticked, and build.';
  // your setup: the stock file, then this device's profiles
  const rows = [sd
    ? setupRow({ thumb: el('span', { class: 'thumb stock-ok' }, icon(BOLT, '')), title: `${sd.name} · OS ${s.os}`,
      sub: 'Stock OS · ' + s.file, href: '#build' })
    : s && !s.ok
      ? setupRow({ thumb: el('span', { class: 'thumb stock-bad' }, '!'), title: 'Not a stock OS elekloader knows',
        sub: s.file, href: '#build' })
      : setupRow({ thumb: el('span', { class: 'thumb' }, icon(PLUS, 'ico')), title: 'Your stock OS file',
        sub: 'Drop it in on Build', href: '#build' })];
  if (sd) {
    const k = sd.key;
    for (const name of Object.keys(profiles()).sort()) {
      const th = el('span', { class: 'thumb profile' }, name.slice(0, 1).toUpperCase());
      th.style.setProperty('--h', String(Math.round(360 * seeded(name)())));
      const m = (profiles()[name] || []).length;
      rows.push(setupRow({ thumb: th, title: name, sub: `Profile · ${m} mod${m === 1 ? '' : 's'}`,
        on: build && S.profile[k] === name, current: S.profile[k] === name,
        onclick: () => { loadProfile(name); location.hash = '#build'; } }));
    }
  } else {
    rows.push(el('li', { class: 'side-empty' }, 'Your profiles show here once your stock file is in.'));
  }
  $('side-rows').replaceChildren(...rows);
  $('save-profile').disabled = !sd || st.busy;
}

function profiles() {
  const k = dev().key;
  S.profiles[k] = S.profiles[k] || {};
  return S.profiles[k];
}

// the window's _remember: the ticked mods are the current profile
function remember() {
  if (!dev()) return;
  const k = dev().key;
  S.profile[k] = S.profile[k] || 'Default';
  profiles()[S.profile[k]] = [...st.enabled].map(base).sort();
  saveSettings();
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
      const s = kept.find(([k]) => k === 'stock');
      if (s) await setStock(s[1].name, s[1].data);
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
  st.stockFile = r.ok ? { name, data } : st.stockFile;
  if (r.ok && S.remember) Files.put('stock', { name, data }).catch(() => {});
  await refresh();
  if (r.ok) {
    const k = r.dev.key;
    const fits = st.mods.filter(d => d.fits);
    const prof = S.profile[k] && profiles()[S.profile[k]];
    if (prof) {
      st.enabled = new Set(fits.filter(d => prof.includes(d.file)).map(d => d.path));
    } else {
      // the first time for this device: its core ticked, and the separate mods
      // you added for it (as the window's first run ticks them)
      const cores = fits.filter(d => d.id === 'core').sort((a, b) => a.file.localeCompare(b.file));
      let on = cores.length ? [cores[cores.length - 1].path] : [];
      for (const d of fits.filter(x => !x.builtin && x.format === 2 && x.id !== 'core')) {
        on = await engine.call('tick', { enabled: on, path: d.path });
      }
      st.enabled = new Set(on);
      remember();
    }
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
      dev() ? 'No mods for this firmware yet. Add one from the library, or drop an .elemod file anywhere on this page.'
        : 'Add mods from the library, or drop .elemod files anywhere on this page.')));
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
  for (const id of ['version', 'out-name', 'add-mods', 'save-profile', 'delete-profile', 'profile']) {
    $(id).disabled = st.busy || (id !== 'add-mods' && !d);
  }
}

function renderProfiles() {
  const sel = $('profile');
  if (!dev()) { sel.replaceChildren(); renderChrome(); return; }
  const k = dev().key;
  const names = Object.keys(profiles()).sort();
  sel.replaceChildren(...names.map(n => el('option', { value: n }, n)));
  sel.value = S.profile[k] || names[0] || '';
  renderChrome();
}

// a configuration (the window's profile): its mods ticked, those that are here
function loadProfile(name) {
  S.profile[dev().key] = name;
  const names = profiles()[name] || [];
  st.enabled = new Set(st.mods.filter(d => d.fits && names.includes(d.file)).map(d => d.path));
  const missing = names.filter(n => !st.mods.some(d => d.file === n));
  saveSettings();
  renderProfiles();
  changed();
  if (missing.length) note('This configuration also names mods that are not added here: ' + missing.join(', '));
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
  const drop = $('stock-drop');
  drop.addEventListener('click', () => $('stock-file').click());
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('stock-file').click(); } });
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
  $('profile').addEventListener('change', e => loadProfile(e.target.value));
  $('save-profile').addEventListener('click', () => {
    const name = (prompt('Name the configuration (the mods ticked now):') || '').trim();
    if (!name) return;
    S.profile[dev().key] = name;
    remember();
    renderProfiles();
  });
  $('delete-profile').addEventListener('click', () => {
    const k = dev().key;
    const name = S.profile[k];
    if (!name || !confirm(`Delete the configuration "${name}"? (The mods stay.)`)) return;
    delete profiles()[name];
    const next = Object.keys(profiles()).sort()[0];
    if (next) {
      loadProfile(next);
    } else {                                 // none left: the ticked mods become Default
      S.profile[k] = 'Default';
      remember();
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
        if (st.stockFile) await Files.put('stock', st.stockFile);
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
  for (const [sheet, close] of [['mod-sheet', 'sheet-close'], ['about-sheet', 'about-close']]) {
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
