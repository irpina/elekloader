// SPDX-License-Identifier: GPL-3.0-or-later
// The Python behaviours the engine copies, against what Python itself gave (test/vectors.json, tools/vectors.py):
// json.loads and its messages, UTF-8 errors, int(x, 0), repr(), json.dumps, zipfile, and the ELEK transport.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fromHex, sha } from '../src/bytes.ts'
import { encodeBin, encodeSyx } from '../src/elek.ts'
import { PyFloat, dumps, floatRepr, pyInt, repr } from '../src/py.ts'
import { decodeUtf8, loads } from '../src/pyjson.ts'
import { members, read } from '../src/zip.ts'
import { lcg } from './helpers.ts'

const P = JSON.parse(readFileSync(new URL('./vectors.json', import.meta.url), 'utf8'))

test('json.loads: values, floats and every message', () => {
  for (const c of P.python.json) {
    if (c.error) {
      assert.throws(() => loads(c.text), (e: Error) => e.message === c.error, `${JSON.stringify(c.text)} -> ${c.error}`)
    } else {
      const v = loads(c.text)
      assert.equal(dumps(v), c.value, JSON.stringify(c.text))
      const floats: [string, string][] = []
      const walk = (x: unknown, path: string) => {
        if (x instanceof PyFloat) floats.push([path, floatRepr(x.value)])
        else if (Array.isArray(x)) x.forEach((y, i) => walk(y, `${path}/${i}`))
        else if (x && typeof x === 'object') for (const [k, y] of Object.entries(x)) walk(y, `${path}/${k}`)
      }
      walk(v, '')
      assert.deepEqual(floats, c.floats, JSON.stringify(c.text))
    }
  }
})

test('UTF-8 decoding, with Python\'s messages', () => {
  for (const c of P.python.utf8) {
    if (c.error) assert.throws(() => decodeUtf8(fromHex(c.hex)!), (e: Error) => e.message === c.error, c.hex)
    else assert.equal(decodeUtf8(fromHex(c.hex)!), c.text)
  }
})

test('int(x, 0)', () => {
  for (const c of P.python.int) assert.equal(pyInt(c.s), c.value, JSON.stringify(c.s))
  assert.equal(pyInt(true), 1)
  assert.equal(pyInt(new PyFloat(4)), null)
})

test('repr() of values and floats', () => {
  for (const c of P.python.repr) assert.equal(repr(c.value), c.repr)
  for (const c of P.python.float_repr) assert.equal(floatRepr(c.value), c.repr, String(c.value))
})

test('json.dumps, flat and indented', () => {
  const d = P.python.dumps
  // the Python dict's order, numeric key included, kept by a Map
  const v = new Map(Object.entries(d.value).sort(([a], [b]) => Object.keys(d.value).indexOf(a) - Object.keys(d.value).indexOf(b)))
  const ordered = new Map([['b', 1], ['a', [1, 'xé\u0001"', null, true, new PyFloat(2.5), {}]], ['z', {}], ['3', { k: [] }], ['e', []]])
  assert.equal(dumps(ordered, 1), d.indent1)
  assert.equal(dumps(ordered, 0), d.indent0)
  assert.equal(dumps(ordered), d.flat)
  assert.ok(v.size === 5)
})

test('zip members and their bytes, as zipfile reads them', async () => {
  const raw = fromHex(P.python.zip.hex)!
  const ms = members(raw)
  assert.deepEqual(ms.map(m => m.filename), P.python.zip.members.map((m: any) => m.filename))
  for (const [i, m] of ms.entries()) {
    const want = P.python.zip.members[i]
    assert.equal(m.fileSize, want.size)
    if (!want.dir) assert.equal(sha(await read(raw, m)), want.sha256)
  }
  const bad = raw.slice()
  const at = ms[2].offset + 30 + ms[2].filename.length + 10    // a byte of the deflated member's data
  bad[at] ^= 0xff
  await assert.rejects(() => read(bad, members(bad)[2]))
  assert.throws(() => members(new Uint8Array(40)), /File is not a zip file/)
})

test('the ELEK transport and card file encode as the Python', () => {
  const e = P.elek
  const oc = new Uint8Array([...new TextEncoder().encode('ELEK0178     1.40C'), ...lcg(e.container_seed, 1000)])
  assert.equal(sha(encodeSyx(oc, 0x05)), e.syx_sha256)
  assert.equal(sha(encodeBin(oc, 0x2f1349d2)), e.bin_sha256)
  assert.equal(sha(encodeBin(new Uint8Array([...oc, 1]), 0x00800001)), e.bin_odd_sha256)
})
