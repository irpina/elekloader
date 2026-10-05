// SPDX-License-Identifier: GPL-3.0-or-later
// Elektron OS .syx files of the ELE3 family (the Digitakt mk1 and II, the Digitone mk1): read, rebuild with a new
// main OS, verify. Ported from elekloader's syx.py (GPL-2.0-or-later), which has the layout and its evidence.
//
// The writer changes one thing: the stored bytes of the device's main OS section. Every other section's stored
// bytes, the ELE3 header (but its 4-character version field) and the framing messages (but their message count)
// are copied from the stock file. A sealed device (trailer 'hmac': the Digitakt II) gets a 32-byte HMAC-SHA256
// of the container after its last section, keyed from the stock file's own bootstrap (sealKey). verify() re-reads
// an output with the decoder, not the writer, and refuses it unless every other section is stock and the main OS
// depacks, in place as the bootloader does it, to the expected image.
import { ascii, be32, byteSum, concat, decodeAscii, equal, find, hmacSha256, putU32, sha, sha256, u32 } from './bytes.ts'
import { packSection } from './codec/aplib.ts'
import { BIAS, Bits, FAR, Out, REUSE, depackSection } from './codec/elz.ts'
import { CHUNK_SIZE, FIRST_COUNTER, MFR, contentChecksum, encodeSyx, packetChecksum } from './codec/transport.ts'
import type { Device } from './devices.ts'
import { hexw, repr } from './py.ts'

export const COUNT_OFF = 0x1c, TABLE_OFF = 0x20, ENTRY_SZ = 16
export const DIGEST = 32                 // the HMAC-SHA256 trailer of a sealed device
const CHUNK = CHUNK_SIZE

export class SyxError extends Error {}

/** One table entry: [section id, offset, stored length, dest]. */
export type Entry = [number, number, number, number]

function messages(raw: Uint8Array): Uint8Array[] {
  const out: Uint8Array[] = []
  let i = 0
  while (i < raw.length) {
    if (raw[i] !== 0xf0) throw new SyxError(`byte ${i} is not F0`)
    const j = raw.indexOf(0xf7, i)
    if (j < 0) throw new SyxError(`message at ${i} has no F7`)
    out.push(raw.subarray(i, j + 1))
    i = j + 1
  }
  return out
}

/** Data messages -> the decoded stream (8-in-7). */
function decode(msgs: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(msgs.length * 116)
  let n = 0
  for (const m of msgs) {
    const p = m.subarray(10, 126)
    let k = 0
    while (k < p.length) {
      const ms = p[k++]
      for (let b = 0; b < 7; b++) {
        if (k >= p.length) break
        out[n++] = p[k++] | ((ms >> (6 - b)) & 1 ? 0x80 : 0)
      }
    }
  }
  return out.subarray(0, n)
}

/** Stored section bytes -> 'packed' | 'raw-header' | 'raw'. */
export function classify(raw: Uint8Array): 'packed' | 'raw-header' | 'raw' {
  const [ln, sm] = raw.length >= 8 ? [u32(raw, 0), u32(raw, 4)] : [0, 1]
  if (ln + 8 <= raw.length && byteSum(raw, 8, 8 + ln) === sm) return 'packed'
  if (raw.length >= 8 && sm === 0) return 'raw-header'
  return 'raw'
}

export function unstore(raw: Uint8Array): Uint8Array {
  const kind = classify(raw)
  if (kind === 'packed') return depackSection(raw)
  if (kind === 'raw-header') return raw.slice(8)
  return raw.slice()
}

const MFR_OK = (m: Uint8Array) => m[1] === MFR[0] && m[2] === MFR[1] && m[3] === MFR[2]

/** A parsed Elektron OS .syx. */
export class Syx {
  readonly raw: Uint8Array
  readonly sha256: string
  readonly framing: [Uint8Array, Uint8Array]
  readonly data: Uint8Array[]
  readonly deviceId: number
  readonly k: number
  readonly total: number
  readonly checksum: number
  readonly container: Uint8Array
  readonly tail: Uint8Array
  readonly header: Uint8Array
  readonly table: Entry[]
  readonly dataStart: number
  readonly stored: Map<number, Uint8Array>
  readonly kind = 'syx'
  readonly seed = null

  constructor(raw: Uint8Array) {
    this.raw = raw
    this.sha256 = sha(raw)
    const msgs = messages(raw)
    if (msgs.length < 3 || msgs[0].length !== 16 || msgs[msgs.length - 1].length !== 16)
      throw new SyxError('no 16-byte framing messages at both ends')
    this.framing = [msgs[0], msgs[msgs.length - 1]]
    this.data = msgs.slice(1, -1)
    if (this.data.some(m => m.length !== 128)) throw new SyxError('a data message is not 128 bytes')
    if (!msgs.every(MFR_OK)) throw new SyxError('manufacturer id is not Elektron')
    this.deviceId = msgs[0][4]
    this.k = msgs[0][8]
    const dec = decode(this.data)
    if (dec.length < 8) throw new SyxError('no ELE3 container')
    this.total = u32(dec, 0)
    this.checksum = u32(dec, 4)
    if (!equal(dec.subarray(8, 12), ascii('ELE3')) || 8 + this.total > dec.length) throw new SyxError('no ELE3 container')
    this.container = dec.slice(8, 8 + this.total)
    this.tail = dec.slice(8 + this.total)
    this.header = this.container.slice(0, COUNT_OFF)
    const n = u32(this.container, COUNT_OFF)
    if (!(n > 0 && n <= 16) || TABLE_OFF + n * ENTRY_SZ > this.total)
      throw new SyxError(`${n} sections: not a table this container can hold`)
    this.table = []
    for (let i = 0; i < n; i++) {
      const at = TABLE_OFF + ENTRY_SZ * i
      this.table.push([u32(this.container, at), u32(this.container, at + 4), u32(this.container, at + 8), u32(this.container, at + 12)])
    }
    this.dataStart = Math.min(...this.table.map(t => t[1]))
    if (TABLE_OFF + n * ENTRY_SZ > this.dataStart) throw new SyxError(`${n} sections do not fit the table`)
    this.stored = new Map()
    for (const [sid, off, clen] of this.table) {
      if (this.stored.has(sid) || off + clen > this.total) throw new SyxError(`section ${sid}: duplicate or outside the container`)
      this.stored.set(sid, this.container.subarray(off, off + clen))
    }
  }

  get version(): string { return decodeAscii(this.header.subarray(0x14, 0x18)) }

  /** -> the section's decoded bytes. */
  section(sid: number): Uint8Array {
    const s = this.stored.get(sid)
    if (!s) throw new Error(`KeyError: ${sid}`)
    return unstore(s)
  }
}

/** Main OS image -> its stored section (the aPLib-shaped packer). */
export const packMain = (image: Uint8Array): Uint8Array => packSection(image)

/** -> the HMAC key of a sealed device's files, derived from `stock` as its bootstrap derives it: in the section
 * dev.hmacKeyFrom names, the seed string, a NUL and a 32-byte constant C; the key is
 * C ^ sha256(seed) ^ sha256(reversed seed). */
export function sealKey(stock: Syx, dev: Device): Uint8Array {
  const [sid, seedText] = dev.hmacKeyFrom!
  const seed = ascii(seedText)
  const sec = stock.section(sid)
  const marker = concat([seed, Uint8Array.of(0)])
  const i = find(sec, marker)
  if (i < 0 || find(sec, marker, i + 1) >= 0) throw new SyxError(`section ${sid} does not hold the seal seed once`)
  const c = sec.subarray(i + seed.length + 1, i + seed.length + 1 + DIGEST)
  if (c.length !== DIGEST) throw new SyxError(`section ${sid} ends inside the seal constant`)
  const a = sha256(seed), b = sha256(seed.slice().reverse())
  return c.map((x, k) => x ^ a[k] ^ b[k])
}

/** -> .syx bytes: `stock` with the main OS section's stored bytes replaced by `storedMain` and, if given, the
 * ELE3 version field set. */
export function write(stock: Syx, storedMain: Uint8Array, dev: Device, version: string | null = null): Uint8Array {
  if (dev.trailer !== null && dev.trailer !== 'hmac')
    throw new SyxError(`${dev.name} files are sealed (${dev.trailer}); elekloader cannot write them`)
  const key = dev.trailer === 'hmac' ? sealKey(stock, dev) : null
  if (key && !equal(hmacSha256(key, stock.container.subarray(0, -DIGEST)), stock.container.subarray(-DIGEST)))
    throw new SyxError('the stock file\'s seal does not verify with the key its bootstrap gives')
  const header = stock.header.slice()
  if (version !== null) {
    const v = ascii(version)
    if (v.length !== 4) throw new SyxError('the version field is exactly 4 characters')
    header.set(v, 0x14)
  }
  const parts: Uint8Array[] = []
  const head = stock.container.slice(0, stock.dataStart)  // the table area as stock has it
  head.set(header, 0)
  parts.push(head)
  let len = head.length
  stock.table.forEach(([sid, , , dest], i) => {
    const data = sid === dev.mainSection ? storedMain : stock.stored.get(sid)!
    const at = TABLE_OFF + ENTRY_SZ * i
    putU32(head, at, sid)
    putU32(head, at + 4, len)
    putU32(head, at + 8, data.length)
    putU32(head, at + 12, dest)
    parts.push(data)
    len += data.length
    const padN = (16 - (len % 16)) % 16
    parts.push(new Uint8Array(padN))
    len += padN
  })
  let cont = concat(parts)
  if (key) cont = concat([cont, hmacSha256(key, cont)])
  const stream = concat([be32(cont.length, contentChecksum(cont)), cont])
  return encodeSyx(stream, stock.deviceId, stock.framing[0], stock.framing[1])
}

/** Depack the main OS the way the bootloader does it in place: the stored section staged at dev.stage, the output
 * written from dev.mainLoad over it. -> [image, the smallest distance in bytes between the writer and the next
 * unread stream byte]. A distance > 0 throughout means the in-place result is the same as depacking elsewhere. */
export function inplaceDepack(stored: Uint8Array, dev: Device): [Uint8Array, number | null] {
  const length = u32(stored, 0)
  const s = new Bits(stored, 8, 8 + length)
  const out = new Out(Math.max(1 << 16, length * 3))
  const base = dev.stage! - dev.mainLoad      // the stream's offset from the load address
  let gap: number | null = null
  let last = 1
  for (;;) {
    if (s.bit()) {
      const g = base + s.p - out.n
      if (gap === null || g < gap) gap = g
      out.push(s.byte())
      continue
    }
    const g = s.gamma()
    let off: number
    if (g === REUSE) {
      off = last
    } else {
      const raw = (g * 256 + s.byte()) >>> 0
      if (raw === BIAS) break
      off = (raw - BIAS) >>> 0
      last = off
    }
    const short = 2 * s.bit() + s.bit()
    let n = short ? short : s.gamma() + 2
    if (off > FAR) n += 1
    if (off === 0 || off > out.n) throw new SyxError('the main OS: a match reaches before the output')
    const w = base + s.p - (out.n + n)          // the last byte this match writes
    if (gap === null || w < gap) gap = w
    out.copy(off, n + 1)
  }
  if (s.p !== 8 + length) throw new SyxError('the main OS: the end marker is not at the declared length')
  return [out.bytes(), gap]
}

const hx = (n: number, w = 8) => '0x' + hexw(n, w)

/** Refuse (SyxError) unless `out` is `stock` with only the main OS changed, and it depacks in place to `wantMain`.
 * -> facts (the manifest's "output"). */
export function verify(out: Uint8Array, stock: Syx, wantMain: Uint8Array, dev: Device, version: string | null = null) {
  const o = new Syx(out)                 // every message's shape and the ELE3 magic
  const main = dev.mainSection
  for (const m of o.data) if (m[4] !== stock.deviceId) throw new SyxError(`a data message has device id 0x${hexw(m[4], 2)}`)
  const bad = o.data.filter(m => packetChecksum(m.subarray(1, -1), o.k) !== m[m.length - 2]).length
  if (bad) throw new SyxError(`${bad} data messages fail their checksum`)
  o.data.forEach((m, i) => {
    const c = (m[7] << 14) | (m[8] << 7) | m[9]
    if (c !== FIRST_COUNTER + i) throw new SyxError(`data message ${i} carries counter ${c}`)
  })
  for (let f = 0; f < 2; f++) {
    const fo = o.framing[f], fs = stock.framing[f]
    const n = (fo[12] << 14) | (fo[13] << 7) | fo[14]
    if (n !== o.data.length) throw new SyxError(`framing count ${n} != ${o.data.length} data messages`)
    if (!equal(concat([fo.subarray(0, 12), fo.subarray(15)]), concat([fs.subarray(0, 12), fs.subarray(15)])))
      throw new SyxError('a framing message differs from stock beyond its count')
  }
  const got = contentChecksum(o.container)
  if (got !== o.checksum) throw new SyxError(`content checksum 0x${hexw(got)} != preamble 0x${hexw(o.checksum)}`)
  if (o.tail.length >= CHUNK || o.tail.some(x => x !== 0)) throw new SyxError(`${o.tail.length} bytes after the container, or not zero`)
  const order = (t: Entry[]) => t.map(([s, , , d]) => s + ':' + d).join(',')
  if (order(o.table) !== order(stock.table)) throw new SyxError('section order or destinations differ from stock')
  let at = stock.dataStart
  for (const [sid, off, clen] of o.table) {
    if (off !== at) throw new SyxError(`section ${sid} at 0x${off.toString(16)}, not 0x${at.toString(16)}`)
    at = off + clen + ((16 - ((off + clen) % 16)) % 16)
  }
  if (dev.trailer === 'hmac') {
    if (o.total !== at + DIGEST) throw new SyxError(`container length ${o.total} is not the 16-aligned end ${at} and the seal`)
    if (!equal(hmacSha256(sealKey(stock, dev), o.container.subarray(0, -DIGEST)), o.container.subarray(-DIGEST)))
      throw new SyxError('the HMAC trailer does not verify')
  } else if (o.total !== at) {
    throw new SyxError(`container length ${o.total} is not the 16-aligned end ${at}`)
  }
  if (dev.flashAt + o.total > dev.flashLimit)
    throw new SyxError(`the container ends at flash 0x${(dev.flashAt + o.total).toString(16)} > 0x${dev.flashLimit.toString(16)}`)
  const hd: number[] = []
  for (let i = 0; i < COUNT_OFF; i++) if (o.header[i] !== stock.header[i]) hd.push(i)
  if (hd.some(i => !(i >= 0x14 && i < 0x18))) throw new SyxError(`ELE3 header differs outside the version field: ${repr(hd)}`)
  if (version !== null && o.version !== version) throw new SyxError(`version field ${repr(o.version)}, not ${repr(version)}`)
  if (!equal(o.container.subarray(TABLE_OFF + ENTRY_SZ * o.table.length, stock.dataStart),
    stock.container.subarray(TABLE_OFF + ENTRY_SZ * stock.table.length, stock.dataStart)))
    throw new SyxError('the table area after the entries differs from stock')
  for (const sid of stock.stored.keys()) {
    if (sid === main) continue
    if (!o.stored.has(sid) || !equal(o.stored.get(sid)!, stock.stored.get(sid)!)) throw new SyxError(`section ${sid} is not stock`)
    if (!equal(o.section(sid), stock.section(sid))) throw new SyxError(`section ${sid} does not depack as stock`)
  }
  const s3 = o.stored.get(main)!
  if (classify(s3) !== 'packed') throw new SyxError('the main OS is not a packed stream with a valid byte sum')
  const [img, gap] = inplaceDepack(s3, dev)
  if (!equal(img, wantMain)) throw new SyxError('the main OS does not depack to the patched image')
  if (!equal(depackSection(s3), img)) throw new SyxError('the main OS: the depacker disagrees with the in-place depack')
  if (gap! <= 0) throw new SyxError(`the main OS: the in-place depack overwrites unread input (gap ${gap})`)
  // 'sections' is keyed by section id in table order, which a plain object would sort: a Map keeps it
  const sections = new Map<string, Section>()
  for (const [s, , l] of o.table) sections.set(String(s), { stored: l, stored_sha256: sha(o.stored.get(s)!), stock: s !== main })
  const facts: Facts = {
    sha256: sha(out), bytes: out.length, messages: o.data.length + 2,
    content_checksum: hx(o.checksum), container_len: o.total,
    flash_end: hx(dev.flashAt + o.total, 6),
    flash_headroom: dev.flashLimit - dev.flashAt - o.total,
    ele3_version: o.version,
    main: { section: main, stored: s3.length, image: img.length, sha256: sha(img), staged_to: hx(dev.stage! + s3.length),
      inplace_min_gap: gap },
    sections,
  }
  return facts
}

export type Section = { stored: number; stored_sha256: string; stock: boolean }
/** The facts a verify returns, in the manifest's key order. */
export type Facts = Record<string, any> & { sections: Map<string, Section> }
