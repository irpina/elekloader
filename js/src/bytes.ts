// SPDX-License-Identifier: GPL-3.0-or-later
// Bytes and hashes: SHA-256 and HMAC-SHA256 in plain TypeScript, synchronous, so the engine runs the same way in
// a page, a worker and Node (Web Crypto's digest is asynchronous); hex; big-endian words.

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

/** Incremental SHA-256 (FIPS 180-4). */
export class Sha256 {
  private h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19])
  private w = new Uint32Array(64)
  private buf = new Uint8Array(64)
  private used = 0
  private total = 0

  update(data: Uint8Array): this {
    let i = 0
    this.total += data.length
    if (this.used) {
      const take = Math.min(64 - this.used, data.length)
      this.buf.set(data.subarray(0, take), this.used)
      this.used += take
      i = take
      if (this.used < 64) return this
      this.block(this.buf, 0)
      this.used = 0
    }
    for (; i + 64 <= data.length; i += 64) this.block(data, i)
    if (i < data.length) {
      this.buf.set(data.subarray(i))
      this.used = data.length - i
    }
    return this
  }

  digest(): Uint8Array {
    const bits = this.total * 8
    const pad = new Uint8Array((this.used < 56 ? 64 : 128) - this.used)
    pad[0] = 0x80
    const n = pad.length
    pad[n - 8] = Math.floor(bits / 2 ** 56) & 0xff
    pad[n - 7] = Math.floor(bits / 2 ** 48) & 0xff
    pad[n - 6] = Math.floor(bits / 2 ** 40) & 0xff
    pad[n - 5] = Math.floor(bits / 2 ** 32) & 0xff
    pad[n - 4] = (bits >>> 24) & 0xff
    pad[n - 3] = (bits >>> 16) & 0xff
    pad[n - 2] = (bits >>> 8) & 0xff
    pad[n - 1] = bits & 0xff
    const total = this.total
    this.update(pad)
    this.total = total
    const out = new Uint8Array(32)
    for (let k = 0; k < 8; k++) {
      out[4 * k] = this.h[k] >>> 24
      out[4 * k + 1] = (this.h[k] >>> 16) & 0xff
      out[4 * k + 2] = (this.h[k] >>> 8) & 0xff
      out[4 * k + 3] = this.h[k] & 0xff
    }
    return out
  }

  private block(d: Uint8Array, at: number) {
    const w = this.w, h = this.h
    for (let t = 0; t < 16; t++) {
      const j = at + 4 * t
      w[t] = (d[j] << 24) | (d[j + 1] << 16) | (d[j + 2] << 8) | d[j + 3]
    }
    for (let t = 16; t < 64; t++) {
      const a = w[t - 15], b = w[t - 2]
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3)
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10)
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0
    }
    let a = h[0], b = h[1], c = h[2], e = h[4], f = h[5], g = h[6], hh = h[7], dd = h[3]
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
      const ch = (e & f) ^ (~e & g)
      const t1 = (hh + S1 + ch + K[t] + w[t]) | 0
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) | 0
      hh = g; g = f; f = e; e = (dd + t1) | 0; dd = c; c = b; b = a; a = (t1 + t2) | 0
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += dd; h[4] += e; h[5] += f; h[6] += g; h[7] += hh
  }
}

export const sha256 = (data: Uint8Array): Uint8Array => new Sha256().update(data).digest()

/** sha256 as lowercase hex, as Python's hashlib.sha256(b).hexdigest(). */
export const sha = (data: Uint8Array): string => toHex(sha256(data))

/** HMAC-SHA256 (RFC 2104), as Python's hmac.new(key, data, hashlib.sha256).digest(). */
export function hmacSha256(key: Uint8Array, data: Uint8Array): Uint8Array {
  const k = new Uint8Array(64)
  k.set(key.length > 64 ? sha256(key) : key)
  const ipad = k.map(x => x ^ 0x36), opad = k.map(x => x ^ 0x5c)
  const inner = new Sha256().update(ipad).update(data).digest()
  return new Sha256().update(opad).update(inner).digest()
}

const HEX = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, '0'))

export function toHex(data: Uint8Array): string {
  let s = ''
  for (let i = 0; i < data.length; i++) s += HEX[data[i]]
  return s
}

/** Python's bytes.fromhex: pairs of hex digits, spaces between pairs allowed; null on anything else. */
export function fromHex(s: string): Uint8Array | null {
  const out: number[] = []
  let i = 0
  while (i < s.length) {
    if (s[i] === ' ' || s[i] === '\t' || s[i] === '\n' || s[i] === '\r' || s[i] === '\f' || s[i] === '\v') { i++; continue }
    const pair = s.slice(i, i + 2)
    if (!/^[0-9a-fA-F]{2}$/.test(pair)) return null
    out.push(parseInt(pair, 16))
    i += 2
  }
  return Uint8Array.from(out)
}

export function concat(parts: readonly Uint8Array[]): Uint8Array {
  let n = 0
  for (const p of parts) n += p.length
  const out = new Uint8Array(n)
  let at = 0
  for (const p of parts) { out.set(p, at); at += p.length }
  return out
}

export function equal(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

export const u32 = (d: Uint8Array, at: number): number =>
  ((d[at] << 24) | (d[at + 1] << 16) | (d[at + 2] << 8) | d[at + 3]) >>> 0

export function putU32(d: Uint8Array, at: number, v: number) {
  d[at] = (v >>> 24) & 0xff
  d[at + 1] = (v >>> 16) & 0xff
  d[at + 2] = (v >>> 8) & 0xff
  d[at + 3] = v & 0xff
}

export const be32 = (...values: number[]): Uint8Array => {
  const out = new Uint8Array(4 * values.length)
  values.forEach((v, i) => putU32(out, 4 * i, v >>> 0))
  return out
}

/** The plain byte sum, mod 2**32. */
export function byteSum(d: Uint8Array, from = 0, to = d.length): number {
  let s = 0
  for (let i = from; i < to; i++) s += d[i]
  return s >>> 0
}

/** Python's bytes.find: the first index of `needle` in `hay` at or after `from`, or -1. */
export function find(hay: Uint8Array, needle: Uint8Array, from = 0): number {
  if (!needle.length) return from <= hay.length ? from : -1
  const first = needle[0]
  outer: for (let i = hay.indexOf(first, from); i >= 0 && i + needle.length <= hay.length; i = hay.indexOf(first, i + 1)) {
    for (let k = 1; k < needle.length; k++) if (hay[i + k] !== needle[k]) continue outer
    return i
  }
  return -1
}

export const ascii = (s: string): Uint8Array => Uint8Array.from(s, c => c.charCodeAt(0) & 0xff)

/** Python's bytes.decode('ascii', 'replace'). */
export const decodeAscii = (d: Uint8Array): string => Array.from(d, x => (x < 0x80 ? String.fromCharCode(x) : '�')).join('')

/** Python's str.encode('ascii', 'replace'): one byte per code point, '?' for a non-ASCII one. */
export const encodeAsciiReplace = (s: string): Uint8Array => Uint8Array.from(Array.from(s), c => {
  const x = c.codePointAt(0)!
  return x < 0x80 ? x : 0x3f
})

export const isAscii = (s: string): boolean => /^[\x00-\x7f]*$/.test(s)
