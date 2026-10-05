// SPDX-License-Identifier: GPL-2.0-or-later
// elekloader's engine for the page, in a worker so the page never blocks: the
// TypeScript engine (js/, built into engine/ by packaging/build_web.py), the
// same code and results as elekloader's Python, as plain JavaScript.
//
// Same origin only. The <meta> CSP in index.html does not reach a worker, and
// GitHub Pages cannot send CSP headers, so this worker keeps itself to the
// site: before anything loads, fetch and XMLHttpRequest refuse any URL that is
// not this site's, and the other ways out (WebSocket, EventSource, ...) are
// removed.
//
// The files the page sends stay in this worker's memory (the engine's Store,
// under /work). They never leave this tab.

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

let bridge = null;

async function bytes(path) {
  const r = await fetch(new URL(path, import.meta.url));
  if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function init() {
  const t0 = performance.now();
  const { Bridge } = await import('./engine/index.js');
  bridge = new Bridge();
  const t1 = performance.now();
  const [cores, build] = await Promise.all([
    fetch(new URL('core/index.json', import.meta.url)).then(r => r.json()),
    fetch(new URL('build.json', import.meta.url)).then(r => r.json()),
  ]);
  // the site's cores, each checked against the sha256 core/index.json gives
  for (const c of cores) bridge.addCore({ name: c.file, sha256: c.sha256 }, await bytes('core/' + c.file));
  const t2 = performance.now();
  return {
    info: bridge.info(), build,
    ms: { engine: Math.round(t1 - t0), cores: Math.round(t2 - t1) },
  };
}

async function handle(id, cmd, args, data) {
  if (cmd === 'init') return init();
  if (!bridge) throw new Error('the engine is not loaded');
  if (cmd !== 'build') return bridge.call(cmd, args, data);
  const t0 = performance.now();
  const say = line => self.postMessage({ id, log: line, t: Math.round(performance.now() - t0) });
  const r = await bridge.call('build', args, undefined, say);
  if (r.ok) {
    for (const f of r.files) f.data = f.data.buffer.slice(f.data.byteOffset, f.data.byteOffset + f.data.byteLength);
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
