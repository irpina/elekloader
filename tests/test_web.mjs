// SPDX-License-Identifier: GPL-2.0-or-later
// The web page's engine under Node, from an assembled site (packaging/build_web.py),
// needing no firmware: the site's engine/ (elekloader's TypeScript engine as plain
// JavaScript), loaded as worker.js loads it, with the site's cores. Every core is
// listed and checked against core/index.json; a core that is not the listed file, a
// file that is no stock firmware, a broken mod and a file that is no mod are
// refused; the check and the build wait for a stock file. The site carries the
// engine, the cores and the page, and no shop and no Pyodide.
//
//   node tests/test_web.mjs build/site
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const SITE = resolve(process.argv[2] || 'build/site');
const read = p => new Uint8Array(readFileSync(p));

let failed = 0;
function check(what, ok, detail = '') {
  console.log(`${ok ? 'ok    ' : 'FAIL  '} ${what}${detail ? ': ' + detail : ''}`);
  if (!ok) failed++;
}

const build = JSON.parse(readFileSync(join(SITE, 'build.json'), 'utf8'));
const t0 = performance.now();
const { Bridge, VERSION } = await import(pathToFileURL(join(SITE, 'engine', 'index.js')).href);
check('the engine from the site', VERSION === build.elekloader,
  `elekloader ${VERSION}, ${build.engine_files} files, loaded in ${Math.round(performance.now() - t0)} ms`);
check('the worker loads that engine', /import\('\.\/engine\/index\.js'\)/.test(readFileSync(join(SITE, 'worker.js'), 'utf8')));
check('no shop and no Pyodide on the site', !Object.keys(build.files).some(n => /^(shop|pyodide)\//.test(n) || n.endsWith('.py'))
  && !existsSync(join(SITE, 'shop')) && !existsSync(join(SITE, 'pyodide')));
check('the engine\'s licence is on the site', /GNU GENERAL PUBLIC LICENSE\s+Version 3/.test(readFileSync(join(SITE, 'engine', 'LICENSE.txt'), 'utf8')));

// the bridge, as worker.js uses it
const bridge = new Bridge();
const call = (name, args = {}, data = undefined) => bridge.call(name, args, data);
const info = await call('info');
check('info', info.version && info.devices.length >= 4, `elekloader ${info.version}; ${info.supported}`);
const cores = JSON.parse(readFileSync(join(SITE, 'core', 'index.json'), 'utf8'));
for (const c of cores) {
  const d = await call('add_core', { name: c.file, sha256: c.sha256 }, read(join(SITE, 'core', c.file)));
  check(`core ${c.file}`, d.id === 'core' && d.builtin && d.sha256 === c.sha256 && !d.error,
    `${d.for_label}, ${d.sites.length} sites`);
}
let tampered = false;
try {
  if (cores.length) await call('add_core', { name: cores[0].file, sha256: '0'.repeat(64) }, read(join(SITE, 'core', cores[0].file)));
} catch (e) {
  tampered = /not the file the site lists/.test(String(e));
}
check('a core that is not the listed file is refused', tampered || !cores.length);
const listed = await call('mods');
check('the cores are listed, made for no stock yet', listed.length === cores.length && listed.every(d => !d.fits));
const st = await call('set_stock', { name: 'not-firmware.syx' }, new TextEncoder().encode('\xf0 nope \xf7'));
check('an unknown file is refused as the stock', !st.ok && /not a stock firmware/.test(st.error), st.error.slice(0, 90));
const junk = await call('add_mod', { name: 'junk.elemod' }, new TextEncoder().encode('{"elemod": 2}'));
check('a broken mod is refused, not kept', !junk.ok && (await call('mods')).length === cores.length, junk.error);
const notmod = await call('add_mod', { name: 'readme.txt' }, new TextEncoder().encode('hi'));
check('a file that is no mod is refused by its name', !notmod.ok, notmod.error);
const chk = await call('check', { enabled: listed.map(d => d.path) });
check('the check asks for the stock file first', !chk.ok && /stock firmware first/.test(chk.headline), chk.headline);
const b = await call('build', { enabled: [], version: '2.0a', name: 'x.syx' });
check('the build asks for the stock file first', !b.ok && /stock firmware first/.test(b.error), b.error);

console.log(failed ? `${failed} failed` : 'all passed');
process.exit(failed ? 1 : 0);
