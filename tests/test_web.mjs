// SPDX-License-Identifier: GPL-2.0-or-later
// The web patcher's engine under Node, from an assembled site (packaging/build_web.py),
// needing no firmware:
//   1. tests/test_units.py, in the site's Pyodide, against the site's elekloader.zip;
//   2. the page's bridge (bridge.py), loaded as worker.js loads it, with the site's
//      cores: every core is listed and checked against core/index.json, a file that is
//      no stock firmware and a file that is no mod are refused, and the check and the
//      build refuse to start without a stock file.
//
//   node tests/test_web.mjs build/site
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const read = p => new Uint8Array(readFileSync(p));   // Pyodide takes typed arrays, not Buffers
const SITE = resolve(process.argv[2] || 'build/site');
const { loadPyodide } = await import(pathToFileURL(join(SITE, 'pyodide', 'pyodide.mjs')).href);

let failed = 0;
function check(what, ok, detail = '') {
  console.log(`${ok ? 'ok    ' : 'FAIL  '} ${what}${detail ? ': ' + detail : ''}`);
  if (!ok) failed++;
}

const t0 = performance.now();
const py = await loadPyodide({ indexURL: join(SITE, 'pyodide') + '/', env: { HOME: '/work' } });
py.setStdout({ batched: s => console.log('   ' + s) });
py.setStderr({ batched: s => console.error('   ' + s) });
py.unpackArchive(read(join(SITE, 'elekloader.zip')), 'zip', { extractDir: '/elek' });
py.runPython("import sys; sys.path.insert(0, '/elek')");
const where = py.runPython('import elekloader, sys; elekloader.__file__ + " " + elekloader.__version__ + ", Python " + sys.version.split()[0]');
check('elekloader from the site\'s zip', where.startsWith('/elek/elekloader/'), where);
console.log(`   Pyodide ${py.version} loaded in ${Math.round(performance.now() - t0)} ms`);

// 1. the unit tests
py.FS.mkdirTree('/work/tests');
py.FS.writeFile('/work/tests/test_units.py', read(join(HERE, 'test_units.py')));
const code = py.runPython(`
import runpy
try:
    runpy.run_path('/work/tests/test_units.py', run_name='__main__')
    code = 0
except SystemExit as e:
    code = e.code or 0
code`);
check('tests/test_units.py under Pyodide', code === 0, `exit ${code}`);

// 2. the bridge, as worker.js loads it
py.FS.writeFile('/elek/bridge.py', read(join(SITE, 'bridge.py')));
const bridge = py.pyimport('bridge');
const call = (name, args = {}, data = undefined) => JSON.parse(bridge.call(name, JSON.stringify(args), data));
const info = call('info');
check('info', info.version && info.devices.length >= 3, `elekloader ${info.version}; ${info.supported}`);
const cores = JSON.parse(readFileSync(join(SITE, 'core', 'index.json'), 'utf8'));
for (const c of cores) {
  const d = call('add_core', { name: c.file, sha256: c.sha256 }, read(join(SITE, 'core', c.file)));
  check(`core ${c.file}`, d.id === 'core' && d.builtin && d.sha256 === c.sha256 && !d.error,
    `${d.for_label}, ${d.sites.length} sites`);
}
let tampered = false;
try {
  if (cores.length) call('add_core', { name: cores[0].file, sha256: '0'.repeat(64) }, read(join(SITE, 'core', cores[0].file)));
} catch (e) {
  tampered = /not the file the site lists/.test(String(e));
}
check('a core that is not the listed file is refused', tampered || !cores.length);
const listed = call('mods');
check('the cores are listed, made for no stock yet', listed.length === cores.length && listed.every(d => !d.fits));
const st = call('set_stock', { name: 'not-firmware.syx' }, new TextEncoder().encode('\xf0 nope \xf7'));
check('an unknown file is refused as the stock', !st.ok && /not a stock firmware/.test(st.error), st.error.slice(0, 90));
const junk = call('add_mod', { name: 'junk.elemod' }, new TextEncoder().encode('{"elemod": 2}'));
check('a broken mod is refused, not kept', !junk.ok && call('mods').length === cores.length, junk.error);
const notmod = call('add_mod', { name: 'readme.txt' }, new TextEncoder().encode('hi'));
check('a file that is no mod is refused by its name', !notmod.ok, notmod.error);
const chk = call('check', { enabled: listed.map(d => d.path) });
check('the check asks for the stock file first', !chk.ok && /stock firmware first/.test(chk.headline), chk.headline);
const b = JSON.parse(bridge.call('build', JSON.stringify({ enabled: [], version: '2.0a', name: 'x.syx' }), undefined, null));
check('the build asks for the stock file first', !b.ok && /stock firmware first/.test(b.error), b.error);

console.log(failed ? `${failed} failed` : 'all passed');
process.exit(failed ? 1 : 0);
