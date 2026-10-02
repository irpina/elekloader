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

// ---- the mod shop ------------------------------------------------------------------------
// shop/index.json lists the curated mods (packaging/build_web.py, from
// web/catalog.json); their files are on this site, next to it.

const shop = { items: [], device: S.shopDevice || null, query: '' };
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

async function loadShop() {
  try {
    const r = await fetch(new URL('shop/index.json', import.meta.url));
    shop.items = r.ok ? await r.json() : [];
  } catch {
    shop.items = [];
  }
  $('open-shop').hidden = !shop.items.length;
  renderShop();
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

function pickDevice(key) {
  shop.device = key;
  S.shopDevice = key;
  saveSettings();
  renderShop();
}

function openShop() {
  if (dev() && !$('shop').open) shop.device = dev().key;
  renderShop();
  $('shop').showModal();
}

function renderShop() {
  if (!shop.items.length) return;
  const devs = pickable();
  const sd = dev();
  $('device-buttons').replaceChildren(...[{ key: null, name: 'All' }, ...devs].map(d => {
    const n = shopGroups(shop.items.filter(e => !d.key || e.device === d.key)).length;
    const on = shop.device === d.key;
    return el('button', { type: 'button', class: 'pick' + (on ? ' on' : ''), 'aria-pressed': String(on),
      onclick: () => pickDevice(d.key) },
    d.name, el('span', { class: 'count' }, String(n)),
    sd && sd.key === d.key ? el('span', { class: 'yours', title: 'Your stock file' }, '⚡') : '');
  }));
  const chosen = devs.find(d => d.key === shop.device);
  $('device-note').textContent = !chosen
    ? (sd ? `Every device's mods. Your stock file is for the ${sd.name}.`
      : 'Every device\'s mods. Select your device to see the ones that fit it.')
    : sd && sd.key === chosen.key ? `For your ${sd.name}, OS ${st.stock.os}: what you add for that OS is ticked for your build.`
      : sd ? `Your stock file is for the ${sd.name}, so mods for the ${chosen.name} can't go into this build.`
        : `Mods for the ${chosen.name}. To build, you need its stock OS ${chosen.os} file (step 1).`;
  $('device-note').className = 'device-note' + (chosen && sd && sd.key !== chosen.key ? ' warn' : '');
  const n = st.enabled.size;
  $('cart').textContent = n ? `⚡ ${n} in your build: done` : 'Done';
  const q = shop.query.trim().toLowerCase();
  const list = shopGroups(shop.items.filter(e => (!shop.device || e.device === shop.device)
    && (!q || [e.title, e.id, e.summary, e.description, e.category, e.author].join(' ').toLowerCase().includes(q))));
  $('shop-cards').replaceChildren(...list.map(card));
  if (!list.length) {
    $('shop-cards').append(el('p', { class: 'empty muted' }, q ? 'Nothing in the shop matches that.'
      : `Nothing in the shop for the ${chosen ? chosen.name : 'device'} yet. You can still add your own .elemod files with + Add mods.`));
  }
  renderNeed();
}

function card(g) {
  const e = shopPick(g);
  // with a stock file, the file for its OS; before one, every OS's (the window hides the others)
  const files = dev() ? [e] : g.filter(x => x.available);
  const haves = files.map(owned).filter(Boolean);
  const have = files.length && haves.length === files.length ? haves : null;
  const otherOs = dev() && dev().key === e.device && e.os && e.os !== st.stock.os;
  const fitsStock = dev() && dev().key === e.device && !otherOs;
  const oses = g.map(x => x.os).filter(Boolean);
  let action;
  if (!e.available) {
    action = el('button', { type: 'button', class: 'buy', disabled: true }, 'Not released yet');
  } else if (have) {
    action = el('span', { class: 'have' }, have.some(d => st.enabled.has(d.path)) ? '✓ In your build' : '✓ In your mods',
      el('button', { type: 'button', class: 'linkish', disabled: st.busy,
        onclick: () => removeMods(have.map(d => d.path)) }, 'Remove'));
  } else {
    action = el('button', { type: 'button', class: 'buy', disabled: !st.ready || st.busy,
      onclick: ev => shopAdd(files.filter(x => !owned(x)), ev.currentTarget) },
    fitsStock || !dev() ? 'Add to build' : 'Add to my mods');
  }
  const needs = (e.requires || []).map(r => (r === 'core' && e.needs_core ? `core ${e.needs_core} or newer` : r));
  const facts = e.available ? [`${e.sites} patch sites`, e.ram ? `${kb(e.ram)} of RAM` : '',
    needs.length ? 'needs ' + needs.join(', ') : '', e.conflicts.length ? 'not with ' + e.conflicts.join(', ') : '']
    .filter(Boolean).join(' · ') : '';
  const device = e.device_name || (pickable().find(d => d.key === e.device) || {}).name || e.device;
  return el('article', { class: 'card' + (e.available ? '' : ' unavailable') + (have ? ' owned' : '') },
    el('div', { class: 'card-top' }, e.category ? el('span', { class: 'chip' }, e.category) : '',
      el('span', { class: 'chip dev' }, device + (oses.length ? ' · OS ' + oses.join(', ') : ''))),
    el('h3', {}, e.title, ' ', el('span', { class: 'ver' }, e.version || '')),
    el('p', { class: 'by' }, [e.author && 'by ' + e.author, e.license].filter(Boolean).join(' · ')),
    el('p', { class: 'summary' }, e.summary || e.description || ''),
    otherOs ? el('p', { class: 'muted small' }, `Made for OS ${e.os}; your stock file is OS ${st.stock.os}.`) : '',
    e.available ? el('details', { class: 'more' }, el('summary', {}, 'More'),
      el('p', { class: 'desc' }, e.description), el('p', { class: 'muted small' }, facts),
      el('p', { class: 'muted small mono' }, g.filter(x => x.available)
        .map(x => `${x.file}${g.length > 1 ? ` (OS ${x.os})` : ''}\nsha256 ${x.sha256}`).join('\n')))
      : el('p', { class: 'muted small' }, `Its release (${e.tag}) is not published yet.`),
    el('div', { class: 'card-foot' }, action,
      el('a', { href: e.available ? e.homepage : e.release_url, rel: 'noreferrer', class: 'src' }, 'Source')));
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
    renderShop();
  }
}

// step 2's hint: which stock file the device you picked needs
function renderNeed() {
  const d = !dev() && pickable().find(x => x.key === shop.device);
  $('stock-need').hidden = !d;
  if (d) $('stock-need').textContent = `For the ${d.name}: Elektron's OS ${d.os} file.`;
}

function toast(text) {
  const t = el('div', { class: 'toast', role: 'status' }, text);
  ($('shop').open ? $('shop') : document.body).append(t);   // above the shop when it is open
  setTimeout(() => t.classList.add('gone'), 4000);
  setTimeout(() => t.remove(), 4600);
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
    $('engine').textContent = `Powering up the build engine… ${secs(performance.now() - t0)}`;
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
    renderShop();                      // its devices, and its Add buttons on
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
    shop.device = k;                   // the shop follows the stock file
  } else {
    st.enabled.clear();
  }
  renderStock();
  renderShop();
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
      dev() ? 'No mods for this firmware yet. Add a mod made for it with "+ Add mods", or browse the mod shop.'
        : 'Add mods with "+ Add mods", browse the mod shop, or drop .elemod files anywhere on this page.')));
  }
  const n = shown.filter(d => st.enabled.has(d.path)).length;
  $('mod-count').textContent = `${n} of ${shown.length} mods enabled`
    + (hidden ? ` · ${hidden} for other firmware hidden` : '');
  $('enable-all').disabled = $('disable-all').disabled = st.busy || !dev();
  renderDetails();
  renderShop();                        // what is owned and ticked shows on its cards
}

function renderDetails() {
  const box = $('details');
  const d = st.selected && desc(st.selected);
  if (!d) { box.replaceChildren(el('p', { class: 'muted' }, 'Select a mod to see what it does and what it changes.')); return; }
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
  box.replaceChildren(...parts);
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
  $('build').textContent = st.busy ? 'BUILDING…' : 'BUILD FIRMWARE';
  for (const id of ['version', 'out-name', 'add-mods', 'save-profile', 'delete-profile', 'profile']) {
    $(id).disabled = st.busy || (id !== 'add-mods' && !d);
  }
}

function renderProfiles() {
  const sel = $('profile');
  if (!dev()) { sel.replaceChildren(); return; }
  const k = dev().key;
  const names = Object.keys(profiles()).sort();
  sel.replaceChildren(...names.map(n => el('option', { value: n }, n)));
  sel.value = S.profile[k] || names[0] || '';
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
  const loadProfile = name => {
    S.profile[dev().key] = name;
    const names = profiles()[name] || [];
    st.enabled = new Set(st.mods.filter(d => d.fits && names.includes(d.file)).map(d => d.path));
    const missing = names.filter(n => !st.mods.some(d => d.file === n));
    saveSettings();
    renderProfiles();
    changed();
    if (missing.length) note('This profile also names mods that are not added here: ' + missing.join(', '));
  };
  $('profile').addEventListener('change', e => loadProfile(e.target.value));
  $('save-profile').addEventListener('click', () => {
    const name = (prompt('Profile name:') || '').trim();
    if (!name) return;
    S.profile[dev().key] = name;
    remember();
    renderProfiles();
  });
  $('delete-profile').addEventListener('click', () => {
    const k = dev().key;
    const name = S.profile[k];
    if (!name || !confirm(`Delete the profile "${name}"? (The mods stay.)`)) return;
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
  $('shop-search').addEventListener('input', e => { shop.query = e.target.value; renderShop(); });
  $('open-shop').addEventListener('click', openShop);
  $('close-shop').addEventListener('click', () => $('shop').close());
  $('cart').addEventListener('click', () => { $('shop').close(); $('step-mods').scrollIntoView({ behavior: 'smooth' }); });
  // a click on the backdrop (the dialog itself, outside its content) closes it
  $('shop').addEventListener('click', e => { if (e.target === $('shop')) $('shop').close(); });
}

wire();
renderMods();
renderBuildButton();
loadShop();
boot();
