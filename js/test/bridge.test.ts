// SPDX-License-Identifier: GPL-3.0-or-later
// The bridge without firmware: what it says about files that are not stock or not mods, and its device list.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Bridge } from '../src/bridge.ts'
import { sha } from '../src/bytes.ts'
import { VERSION } from '../src/version.ts'
import { lcg } from './helpers.ts'

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
