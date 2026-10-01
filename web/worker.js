// SPDX-License-Identifier: GPL-2.0-or-later
// elekloader's engine for the page: Pyodide (CPython compiled to WebAssembly)
// running elekloader, in a worker so the page never blocks.
//
// Same origin only. The <meta> CSP in index.html does not reach a worker, and
// GitHub Pages cannot send CSP headers, so this worker keeps itself to the
// site: before anything loads, fetch and XMLHttpRequest refuse any URL that is
// not this site's, and the other ways out (WebSocket, EventSource, ...) are
// removed. Pyodide is told to take everything from ./pyodide/, packageBaseUrl
// included, so it has no CDN to fall back on, and nothing here asks it for a
// package.
//
// The files the page sends are written into Pyodide's in-memory file system
// (/work, see bridge.py). They never leave this tab.

const SITE = self.location.origin;

function sameSite(url) {
  return new URL(url, self.location.href).origin === SITE;
}

const siteFetch = self.fetch.bind(self);
self.fetch = (input, init) => {
  const url = input instanceof Request ? input.url : String(input);
  if (!sameSite(url)) {
    return Promise.reject(new TypeError(`refused: ${url} is not on this site`));
  }
  return siteFetch(input, init);
};
if (self.XMLHttpRequest) {
  const open = self.XMLHttpRequest.prototype.open;
  self.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    if (!sameSite(url)) throw new TypeError(`refused: ${url} is not on this site`);
    return open.call(this, method, url, ...rest);
  };
}
for (const k of ['WebSocket', 'WebSocketStream', 'EventSource', 'WebTransport', 'RTCPeerConnection']) {
  if (k in self) self[k] = undefined;
}

let py = null;
let bridge = null;

async function bytes(path) {
  const r = await fetch(new URL(path, import.meta.url));
  if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
  return new Uint8Array(await r.arrayBuffer());
}

// What the browser fetched for the engine: each file, and what crossed the
// network (0 when it came from the cache).
function fetched() {
  return performance.getEntriesByType('resource').map(e => ({
    url: e.name, transferred: e.transferSize, size: e.decodedBodySize,
    ms: Math.round(e.duration),
  }));
}

async function init() {
  const t0 = performance.now();
  const indexURL = new URL('./pyodide/', import.meta.url).href;
  const { loadPyodide } = await import('./pyodide/pyodide.mjs');
  py = await loadPyodide({ indexURL, packageBaseUrl: indexURL, env: { HOME: '/work' } });
  const t1 = performance.now();
  const [zip, src, cores, build] = await Promise.all([
    bytes('elekloader.zip'), bytes('bridge.py'),
    fetch(new URL('core/index.json', import.meta.url)).then(r => r.json()),
    fetch(new URL('build.json', import.meta.url)).then(r => r.json()),
  ]);
  py.unpackArchive(zip, 'zip', { extractDir: '/elek' });
  py.FS.mkdirTree('/work');
  py.FS.writeFile('/elek/bridge.py', src);
  py.runPython("import sys; sys.path.insert(0, '/elek')");
  bridge = py.pyimport('bridge');
  for (const c of cores) {
    const raw = await bytes('core/' + c.file);
    call('add_core', { name: c.file, sha256: c.sha256 }, raw);
  }
  const t2 = performance.now();
  return {
    info: call('info', {}), build, python: py.runPython('import sys; sys.version.split()[0]'),
    pyodide: py.version, ms: { pyodide: Math.round(t1 - t0), elekloader: Math.round(t2 - t1) },
    fetched: fetched(),
  };
}

// (undefined arrives in Python as None; null would arrive as JsNull)
function call(name, args, data = undefined, progress = undefined) {
  return JSON.parse(bridge.call(name, JSON.stringify(args), data, progress));
}

async function handle(id, cmd, args, data) {
  if (cmd === 'init') return init();
  if (!bridge) throw new Error('the engine is not loaded');
  if (cmd !== 'build') return call(cmd, args, data);
  const t0 = performance.now();
  const say = line => self.postMessage({ id, log: line, t: Math.round(performance.now() - t0) });
  const r = call('build', args, undefined, say);
  if (r.ok) {
    for (const f of r.files) f.data = py.FS.readFile(f.path).buffer;
  }
  r.ms = Math.round(performance.now() - t0);
  return r;
}

self.onmessage = async e => {
  const { id, cmd, args, data } = e.data;
  try {
    const result = await handle(id, cmd, args || {}, data ? new Uint8Array(data) : undefined);
    const moved = result && result.files ? result.files.map(f => f.data).filter(Boolean) : [];
    self.postMessage({ id, ok: true, result }, moved);
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message || err) });
  }
};
