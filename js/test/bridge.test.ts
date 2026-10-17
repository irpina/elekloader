// SPDX-License-Identifier: GPL-3.0-or-later
// The bridge without firmware: what it says about files that are not stock or not mods, its device list, and the core
// its tick takes.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Bridge } from '../src/bridge.ts'
import { sha } from '../src/bytes.ts'
import { type Desc, oneCore, withRequirements } from '../src/model.ts'
import { VERSION } from '../src/version.ts'
import { lcg } from './helpers.ts'

test('tick: the newest core, and one with more RAM in place of a core chosen by hand that is too small (test_units.py\'s cases)', () => {
  const kb = 1024
  const d = new Map<string, Desc>([
    ['app/core-dn1-2.3.elemod', { id: 'core', version: '2.3', fits: true, requires: [], ram_bound: 4 * kb, ram_area: 128 * kb }],
    ['app/core-dn1-3.2.elemod', { id: 'core', version: '3.2', fits: true, requires: [], ram_bound: 6 * kb, ram_area: 128 * kb }],
    ['app/core-dn1-4.0.elemod', { id: 'core', version: '4.0', fits: true, requires: [], ram_bound: 6 * kb, ram_area: 1280 * kb }],
    ['lib/tiny.elemod', { id: 'tiny', fits: true, requires: ['core'], ram_bound: kb }],
    ['lib/whole.elemod', { id: 'whole', fits: true, format: 1 }],
    ['lib/huge.elemod', { id: 'huge', fits: true, requires: ['core'], needs_core: '3.2', ram_bound: 2000 * kb }],
  ])
  const pedals = [1, 2, 3, 4, 5].map(i => `lib/pedal${i}.elemod`)
  pedals.forEach((p, i) => d.set(p, { id: `pedal${i + 1}`, fits: true, requires: ['core'], needs_core: '3.2', ram_bound: 30 * kb }))
  const [c23, c32, c40] = ['app/core-dn1-2.3.elemod', 'app/core-dn1-3.2.elemod', 'app/core-dn1-4.0.elemod']
  const tick = (on: Iterable<string>, p: string) => withRequirements(d, on, p)
  const is = (got: Set<string>, want: string[]) => assert.deepEqual([...got].sort(), [...want].sort())
  let on = new Set<string>()
  pedals.forEach((p, k) => {                                      // the newest core, 4.0, for a small selection too
    on = tick(on, p)
    is(on, [...pedals.slice(0, k + 1), c40])
  })
  is(tick([], 'lib/tiny.elemod'), ['lib/tiny.elemod', c40])
  is(tick([c32], pedals[0]), [c32, pedals[0]])                    // a core chosen by hand that will do is kept
  is(tick([c23], 'lib/tiny.elemod'), [c23, 'lib/tiny.elemod'])
  on = new Set([c32])
  pedals.slice(0, 4).forEach((p, k) => {                         // 3.2 by hand: up to 120 KB + its 6 KB, it holds them
    on = tick(on, p)
    is(on, [...pedals.slice(0, k + 1), c32])
  })
  is(tick(on, pedals[4]), [...pedals, c40])                       // 150 KB: 4.0 in 3.2's place
  d.set('lib/edge.elemod', { id: 'edge', fits: true, requires: ['core'], needs_core: '3.2', ram_bound: 122 * kb })
  is(tick([c32], 'lib/edge.elemod'), ['lib/edge.elemod', c32])
  d.get('lib/edge.elemod')!.ram_bound += 1
  is(tick([c32], 'lib/edge.elemod'), ['lib/edge.elemod', c40])
  is(tick([], 'lib/huge.elemod'), ['lib/huge.elemod', c40])     // held by no core: the newest
  is(tick([c32], 'lib/huge.elemod'), ['lib/huge.elemod', c32])  // or the one chosen by hand
  is(tick(['lib/whole.elemod', c23], 'lib/tiny.elemod'), ['lib/whole.elemod', 'lib/tiny.elemod', c23])
  is(oneCore(d, [c23, c32, c40, ...pedals]), [...pedals, c40])
  is(oneCore(d, [c23, c32, c40, 'lib/tiny.elemod']), [c40, 'lib/tiny.elemod'])
})

test('the version is elekloader\'s', () => {
  const init = readFileSync(new URL('../../elekloader/__init__.py', import.meta.url), 'utf8')
  assert.equal(VERSION, /__version__ = '([^']+)'/.exec(init)![1])
})

test('info: every device, as bridge.py lists them', () => {
  const i = new Bridge().info()
  assert.deepEqual(i.devices.map(d => [d.key, d.releases, d.default_version, d.linkable]), [
    ['digitakt-mk1', ['1.53', '1.54'], '2.0a', true],
    ['digitakt-mk2', ['1.17'], '2.0a', true],
    ['digitone-mk1', ['1.43', '1.44'], '2.0a', true],
    ['octatrack', ['1.40C'], '', true],
    ['model-cycles', ['1.13'], '', true],
    ['model-samples', ['1.13'], '', true],
    ['analog-rytm-mk2', ['1.73', '1.74'], '2.0a', true],
  ])
  assert.deepEqual(i.exts, ['.elemod', '.dtmod'])
  assert.match(i.supported, /^Digitakt mk1 1\.53, Digitakt mk1 1\.54, Digitakt II 1\.17, /)
})

test('a file that is not a stock OS is refused, and not kept', async () => {
  const b = new Bridge()
  const junk = lcg(5, 4000)
  const st = await b.setStock({ name: '..\\dir\\junk.syx' }, junk)
  assert.equal(st.ok, false)
  assert.equal(st.file, 'junk.syx')
  assert.equal(st.error, `not a stock firmware elekloader knows (sha256 ${sha(junk)}). Supported: ${b.info().supported}`)
  assert.equal(b.store.list('/work/stock').length, 0)
  const check = b.check({ enabled: [] })
  assert.equal(check.headline, 'Choose your stock firmware first')
})

test('a zip without a known OS file names what it holds', async () => {
  const b = new Bridge()
  const P = JSON.parse(readFileSync(new URL('./vectors.json', import.meta.url), 'utf8'))
  const zip = Uint8Array.from(P.python.zip.hex.match(/../g).map((h: string) => parseInt(h, 16)))
  const st = await b.setStock({ name: 'x.zip' }, zip)
  assert.equal(st.error, `the zip holds no stock firmware elekloader knows (deflated.syx, stored.bin). Supported: ${b.info().supported}`)
})

test('mods: the name, the JSON, the format', () => {
  const b = new Bridge()
  assert.deepEqual(b.addMod({ name: 'readme.txt' }, new Uint8Array(1)),
    { ok: false, file: 'readme.txt', error: 'readme.txt is not a mod: the file name must end .elemod or .dtmod' })
  assert.deepEqual(b.addMod({ name: 'a.elemod', sha256: '00' }, new Uint8Array(1)),
    { ok: false, file: 'a.elemod', error: 'a.elemod is not the file the shop lists' })
  assert.deepEqual(b.addMod({ name: 'a.elemod' }, new TextEncoder().encode('{"elemod": 2,}')),
    { ok: false, file: 'a.elemod', error: '/work/mods/a.elemod: not JSON (Illegal trailing comma before end of object: line 1 column 13 (char 12))' })
  assert.deepEqual(b.addMod({ name: 'a.elemod' }, new TextEncoder().encode('{"elemod": 2}')),
    { ok: false, file: 'a.elemod', error: 'a.elemod: no "id"' })
  assert.deepEqual(b.mods(), [])
  assert.throws(() => b.removeMod({ path: '/work/core/x.elemod' }), /only mods you added can be removed/)
})

test('the version field and the file name', () => {
  const b = new Bridge()
  assert.deepEqual(b.version({ version: '2.0a', enabled: [] }), { ok: true, name: 'custom-2.0a.syx' })
})
