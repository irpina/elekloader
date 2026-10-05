// SPDX-License-Identifier: GPL-3.0-or-later
// The codecs and hashes against elekloader's Python (test/vectors.json, from tools/vectors.py) and Node's crypto.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash, createHmac } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { pack, packSection } from '../src/codec/aplib.ts'
import { depackSection } from '../src/codec/elz.ts'
import { contentChecksum, encodeSyx } from '../src/codec/transport.ts'
import { fromHex, hmacSha256, sha, toHex } from '../src/bytes.ts'
import { lcg } from './helpers.ts'

const V = JSON.parse(readFileSync(new URL('./vectors.json', import.meta.url), 'utf8'))

type Spec = { kind: string; n: number; seed?: number; value?: number; text?: string }
function make(spec: Spec): Uint8Array {
  const { kind, n } = spec
  if (kind === 'random') return lcg(spec.seed!, n)
  if (kind === 'repeat') return new Uint8Array(n).fill(spec.value!)
  if (kind === 'phrase') {
    const p = new TextEncoder().encode(spec.text!)
    return Uint8Array.from({ length: n }, (_, i) => p[i % p.length])
  }
  if (kind === 'blocks') {
    const out = lcg(spec.seed!, n)
    for (let k = 0, at = 512; at < n - 300; k++, at += 997) {
      const src = at - (37 + (k * 811) % 6000)
      if (src >= 0) {
        const ln = 3 + (k * 13) % 260
        out.set(out.slice(src, src + ln), at)       // Python's slice assignment copies first
      }
    }
    return out
  }
  if (kind === 'words') {
    const m = Math.floor(n / 4), out = new Uint8Array(4 * m), v = new DataView(out.buffer)
    for (let i = 0; i < m; i++) v.setUint32(4 * i, i % 5 ? i * 6 : 0)
    return out
  }
  throw new Error(kind)
}

test('SHA-256 and HMAC-SHA256 match Node crypto', () => {
  for (const n of [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 100003]) {
    const d = lcg(n, n)
    assert.equal(sha(d), createHash('sha256').update(d).digest('hex'), `sha256 of ${n} bytes`)
    for (const kn of [0, 16, 32, 64, 65, 200]) {
      const key = lcg(kn + 7, kn)
      assert.equal(toHex(hmacSha256(key, d)), createHmac('sha256', key).update(d).digest('hex'), `hmac ${kn}/${n}`)
    }
  }
})

test('fromHex is Python bytes.fromhex', () => {
  assert.deepEqual(fromHex('00ff 1a'), Uint8Array.of(0, 255, 0x1a))
  assert.equal(fromHex('0'), null)
  assert.equal(fromHex('0 0'), null)
  assert.equal(fromHex('zz'), null)
})

for (const c of V.aplib) {
  test(`aplib packs as the Python: ${c.spec.kind} ${c.spec.n}`, () => {
    const data = make(c.spec)
    assert.equal(sha(data), c.input_sha256, 'the input is the Python\'s')
    const packed = packSection(data)
    if (c.packed) assert.equal(toHex(packed), c.packed)
    assert.equal(packed.length, c.packed_len)
    assert.equal(sha(packed), c.packed_sha256)
    assert.equal(sha(packSection(data, false)), c.store_sha256)
    assert.deepEqual(depackSection(packed), data)
    assert.equal(pack(data).length, packed.length - 8)
  })
}

test('the transport encodes as the Python', () => {
  const t = V.transport
  const syx = encodeSyx(lcg(t.stream_seed, t.stream_len), 0x0a, fromHex(t.framing[0])!, fromHex(t.framing[1])!)
  assert.equal(syx.length, t.syx_len)
  assert.equal(sha(syx), t.syx_sha256)
  assert.equal(contentChecksum(lcg(t.content_checksum.seed, t.content_checksum.len)), t.content_checksum.value)
})
