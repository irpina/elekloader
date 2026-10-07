// SPDX-License-Identifier: GPL-3.0-or-later
// The Octatrack family's OS files: the ELEK container, the legacy SysEx transport (.syx) and the ELUP card file
// (.bin). Read, rebuild with a new main OS, verify. Ported from elekloader's elek.py (GPL-2.0-or-later), which
// documents the layout; the checksum and the cipher are as elektron-firmware-tool (MIT) and sambanks/octabam (MIT)
// describe them. Rebuilding the stock Octatrack 1.40C files from their own section reproduces both byte for byte.
import { ascii, byteSum, concat, decodeAscii, equal, putU32, sha, u32 } from './bytes.ts'
import { packSection } from './codec/aplib.ts'
import { depackSection } from './codec/elz.ts'
import type { Device } from './devices.ts'
import { hexw, repr } from './py.ts'

const MAGIC = ascii('ELEK'), BIN_MAGIC = ascii('ELUP')
export const SECT = 0x12                       // the section's [length][sum] header
export const VERSION: [number, number] = [0x08, 0x12]    // the 10-character version field
const CHUNK = 63
const FIRST = 0x4000
const XOR_A = 0x9e3b16a2, XOR_B = 0x764e28ca, MIX_A = 0x360fa955, MIX_B = 0xef4a9ab6
const MFR = [0x00, 0x20, 0x3c]

export class ElekError extends Error {}

// ---- the legacy SysEx transport ----

const nibbles = (v: number) => [20, 16, 12, 8, 4, 0].map(s => (v >>> s) & 0xf)
const value = (nib: ArrayLike<number>) => Array.from(nib).reduce((v, x) => (v << 4) | x, 0)

export function packetChecksum(data: Uint8Array, nib: ArrayLike<number>): number {
  return (byteSum(data) + (nib[1] & 7) + nib[3] + nib[5] + ((nib[2] + nib[4]) << 4)) & 0xff
}

/** 8-in-7. `stale` is what the encoder's 63-byte buffer held before `data` was written over it: the marker of a
 * short final group also carries the high bits of the bytes left there, as Elektron's encoder does (elek.py). */
function enc87(data: Uint8Array, stale: Uint8Array): number[] {
  const buf = new Uint8Array(CHUNK)
  buf.set(stale.subarray(0, CHUNK))
  buf.set(data)
  const out: number[] = []
  for (let i = 0; i < data.length; i += 7) {
    let marker = 0
    for (let n = 0; n < 7 && i + n < CHUNK; n++) if (buf[i + n] & 0x80) marker += 0x40 >> n
    out.push(marker)
    for (let n = i; n < Math.min(i + 7, data.length); n++) out.push(data[n] & 0x7f)
  }
  return out
}

function dec87(p: Uint8Array): Uint8Array {
  const out: number[] = []
  let k = 0
  while (k < p.length) {
    const ms = p[k++]
    for (let n = 0; n < 7; n++) {
      if (k >= p.length) break
      out.push(p[k++] | ((ms >> (6 - n)) & 1 ? 0x80 : 0))
    }
  }
  return Uint8Array.from(out)
}

export function encodeSyx(container: Uint8Array, devId: number): Uint8Array {
  const head = [0xf0, ...MFR, devId, 0x00]
  const out: number[] = []
  let prev: Uint8Array = new Uint8Array(0)
  for (let off = 0; off < container.length; off += CHUNK) {
    const data = container.subarray(off, off + CHUNK)
    const nib = nibbles(FIRST + off)
    const c = packetChecksum(data, nib)
    out.push(...head, 0x7e, c >> 4, c & 0xf, ...nib, ...enc87(data, prev), 0xf7)
    prev = data
  }
  out.push(...head, 0x7e, 0xf7)
  out.push(...head, 0x7f, ...nibbles(container.length), 0xf7)
  return Uint8Array.from(out)
}

/** -> [device id, container]. Checks every message. */
export function decodeSyx(raw: Uint8Array): [number, Uint8Array] {
  const msgs: Uint8Array[] = []
  let i = 0
  while (i < raw.length) {
    if (raw[i] !== 0xf0) throw new ElekError(`byte ${i} is not F0`)
    const j = raw.indexOf(0xf7, i)
    if (j < 0) throw new ElekError(`the message at ${i} has no F7`)
    msgs.push(raw.subarray(i, j + 1))
    i = j + 1
  }
  if (msgs.length < 3) throw new ElekError('too few messages for an OS file')
  const dev = msgs[0].length > 4 ? msgs[0][4] : -1
  msgs.forEach((m, n) => {
    if (m[1] !== MFR[0] || m[2] !== MFR[1] || m[3] !== MFR[2] || m[4] !== dev || m[5] !== 0)
      throw new ElekError(`message ${n}: not an Elektron message for device 0x${hexw(dev, 2)}`)
  })
  const data = msgs.slice(0, -2), empty = msgs[msgs.length - 2], end = msgs[msgs.length - 1]
  if (!equal(empty, Uint8Array.of(0xf0, ...MFR, dev, 0, 0x7e, 0xf7))) throw new ElekError('no empty data message before the end marker')
  if (end.length !== 14 || end[6] !== 0x7f) throw new ElekError('no end marker')
  const parts: Uint8Array[] = []
  let len = 0
  data.forEach((m, n) => {
    if (m[6] !== 0x7e || m.length < 17) throw new ElekError(`message ${n} is not a data message`)
    const nib = m.subarray(9, 15)
    if (m.subarray(7, 15).some(x => x > 0xf)) throw new ElekError(`message ${n}: a nibble field over 0xF`)
    if (value(nib) !== FIRST + len)
      throw new ElekError(`message ${n} carries offset 0x${value(nib).toString(16)}, not 0x${(FIRST + len).toString(16)}`)
    const d = dec87(m.subarray(15, -1))
    if (!(d.length > 0 && d.length <= CHUNK) || (d.length < CHUNK && n !== data.length - 1))
      throw new ElekError(`message ${n} carries ${d.length} bytes`)
    if (packetChecksum(d, nib) !== ((m[7] << 4) | m[8])) throw new ElekError(`message ${n} fails its checksum`)
    parts.push(d)
    len += d.length
  })
  if (value(end.subarray(7, 13)) !== len)
    throw new ElekError(`the end marker says ${value(end.subarray(7, 13))} bytes, the messages carry ${len}`)
  return [dev, concat(parts)]
}

// ---- the ELUP card file ----

const rot16 = (v: number) => ((v << 16) | (v >>> 16)) >>> 0
const bswap = (v: number) => (((v & 0xff) << 24) | ((v & 0xff00) << 8) | ((v >>> 8) & 0xff00) | (v >>> 24)) >>> 0

function cipher(k: number, p: number): number {
  if (!(k & 0x800000)) return (rot16((p ^ k ^ MIX_A) >>> 0) ^ XOR_A) >>> 0
  return (bswap((p ^ k ^ MIX_B) >>> 0) ^ XOR_B) >>> 0
}

function plain(k: number, c: number): number {
  if (!(k & 0x800000)) return (k ^ MIX_A ^ rot16((c ^ XOR_A) >>> 0)) >>> 0
  return (k ^ MIX_B ^ bswap((c ^ XOR_B) >>> 0)) >>> 0
}

export function encodeBin(container: Uint8Array, seed: number): Uint8Array {
  const body = concat([container, new Uint8Array((4 - (container.length % 4)) % 4)])
  const words = 1 + body.length / 4
  const out = new Uint8Array(8 + 4 * (words + 1))
  out.set(BIN_MAGIC, 0)
  putU32(out, 4, seed)
  let k = seed >>> 0, acc = 0
  for (let w = 0; w < words; w++) {
    const p = w === 0 ? body.length : u32(body, 4 * (w - 1))
    const c = cipher(k, p)
    putU32(out, 8 + 4 * w, c)
    acc = (acc + p) >>> 0
    k = c
  }
  putU32(out, 8 + 4 * words, cipher(k, acc))
  return out
}

/** -> [seed, the container padded to 4]. Checks the checksum. */
export function decodeBin(raw: Uint8Array): [number, Uint8Array] {
  if (!equal(raw.subarray(0, 4), BIN_MAGIC) || raw.length % 4 || raw.length < 16) throw new ElekError('not an ELUP card file')
  const n = raw.length / 4
  const seed = u32(raw, 4)
  let k = seed, acc = 0
  const pb = new Uint8Array(4 * (n - 3))
  for (let w = 2; w < n - 1; w++) {
    const c = u32(raw, 4 * w)
    const p = plain(k, c)
    putU32(pb, 4 * (w - 2), p)
    acc = (acc + p) >>> 0
    k = c
  }
  if (plain(k, u32(raw, 4 * (n - 1))) !== acc) throw new ElekError('the card file fails its checksum')
  const declared = u32(pb, 0)
  if (declared !== pb.length - 4) throw new ElekError(`the card file declares ${declared} bytes and carries ${pb.length - 4}`)
  return [seed, pb.slice(4)]
}

// ---- the container ----

/** Python's str.strip() on ASCII text. */
const pyStrip = (s: string) => s.replace(/^[ \t\n\r\x0b\x0c\x1c-\x1f]+|[ \t\n\r\x0b\x0c\x1c-\x1f]+$/g, '')

/** A parsed Octatrack-family OS file, from its .syx or its .bin. */
export class ElekFile {
  readonly raw: Uint8Array
  readonly sha256: string
  readonly kind: 'syx' | 'bin'
  readonly seed: number | null
  readonly deviceId: number | null
  readonly container: Uint8Array
  readonly header: Uint8Array
  readonly stored: Map<number, Uint8Array>
  readonly tail: Uint8Array
  readonly table: [number, number, number, number][]

  constructor(raw: Uint8Array) {
    this.raw = raw
    this.sha256 = sha(raw)
    let cont: Uint8Array
    if (equal(raw.subarray(0, 4), BIN_MAGIC)) {
      this.kind = 'bin'
      ;[this.seed, cont] = decodeBin(raw)
      this.deviceId = null
    } else {
      this.kind = 'syx'
      ;[this.deviceId, cont] = decodeSyx(raw)
      this.seed = null
    }
    if (!equal(cont.subarray(0, 4), MAGIC) || cont.length < SECT + 8) throw new ElekError('no ELEK container')
    const n = u32(cont, SECT), s = u32(cont, SECT + 4)
    if (SECT + 8 + n > cont.length) throw new ElekError('the section runs past the container')
    if (byteSum(cont, SECT + 8, SECT + 8 + n) !== s) throw new ElekError('the section fails its byte sum')
    this.container = cont
    this.header = cont.slice(0, SECT)
    this.stored = new Map([[3, cont.subarray(SECT, SECT + 8 + n)]])
    this.tail = cont.slice(SECT + 8 + n)
    this.table = [[3, SECT, 8 + n, 0]]
  }

  get build(): string { return decodeAscii(this.header.subarray(4, 8)) }
  get version(): string { return pyStrip(decodeAscii(this.header.subarray(VERSION[0], VERSION[1]))) }

  section(sid: number): Uint8Array {
    if (sid !== 3) throw new ElekError('an ELEK container has one section, the main OS')
    return depackSection(this.stored.get(3)!)
  }
}

/** -> the header's 10 version bytes: right-justified, padded with spaces. */
export function versionField(dev: Device, version: string): Uint8Array {
  const v = ascii(version)
  if (!(v.length > 0 && v.length <= dev.versionLen)) throw new ElekError(`the version is 1 to ${dev.versionLen} ASCII characters`)
  const out = new Uint8Array(dev.versionLen).fill(0x20)
  out.set(v, dev.versionLen - v.length)
  return out
}

/** -> the ELEK container: `stock`'s header (its version field set to `version`, if given), the new section,
 * padding to an even length. */
export function container(stock: ElekFile, storedMain: Uint8Array, dev: Device, version: string | null = null): Uint8Array {
  const head = stock.header.slice()
  if (version !== null) head.set(versionField(dev, version), VERSION[0])
  const cont = concat([head, storedMain])
  return concat([cont, new Uint8Array(cont.length % 2)])
}

/** -> {syx, bin}: `stock` with the main OS replaced. */
export function write(stock: ElekFile, storedMain: Uint8Array, dev: Device, version: string | null = null, seed: number | null = null) {
  const cont = container(stock, storedMain, dev, version)
  const devId = stock.deviceId !== null ? stock.deviceId : dev.sysexId
  if (seed === null) seed = stock.seed !== null ? stock.seed : 0x2f1349d2
  return { syx: encodeSyx(cont, devId), bin: encodeBin(cont, seed) }
}

const hx = (n: number, w = 8) => '0x' + hexw(n, w)

/** Refuse (ElekError) unless every output is `stock` with only the main OS (and the version field) changed, the
 * main OS depacks to `wantMain`, and the protected ranges are stock's. -> facts. */
export function verify(outputs: Record<string, Uint8Array>, stock: ElekFile, wantMain: Uint8Array, dev: Device,
  stockMain: Uint8Array, version: string | null = null) {
  const o = new ElekFile(outputs.syx)     // every message, checksum, offset
  if (o.deviceId !== dev.sysexId) throw new ElekError(`device id 0x${hexw(o.deviceId!, 2)}, not 0x${hexw(dev.sysexId, 2)}`)
  const hd: number[] = []
  for (let i = 0; i < SECT; i++) if (o.header[i] !== stock.header[i]) hd.push(i)
  if (hd.some(i => !(i >= VERSION[0] && i < VERSION[1]))) throw new ElekError(`the ELEK header differs outside the version field: ${repr(hd)}`)
  if (version !== null && !equal(o.header.subarray(VERSION[0], VERSION[1]), versionField(dev, version)))
    throw new ElekError(`the version field is ${repr(o.version)}, not ${repr(version)}`)
  if (o.tail.some(x => x !== 0) || o.container.length % 2) throw new ElekError('the container\'s padding is not zeros to an even length')
  const img = o.section(3)
  if (!equal(img, wantMain)) throw new ElekError('the main OS does not depack to the patched image')
  for (const [lo, hi, why] of dev.protected) {
    const a = lo - dev.mainLoad, b = hi - dev.mainLoad
    if (!equal(img.subarray(a, b), stockMain.subarray(a, b))) throw new ElekError(`${hx(lo)}-${hx(hi)} (${why}) is not stock`)
  }
  const budget = dev.flashLimit - dev.flashAt
  if (o.container.length > budget)
    throw new ElekError(`the container is ${o.container.length} bytes; the OS region in flash holds ${budget}`)
  const s3 = o.stored.get(3)!
  const facts: Record<string, any> = {
    sha256: sha(outputs.syx), bytes: outputs.syx.length, messages: outputs.syx.filter(x => x === 0xf7).length,
    container_len: o.container.length, flash_end: hx(dev.flashAt + o.container.length, 6),
    flash_headroom: budget - o.container.length, version: o.version,
    main: { section: 3, stored: s3.length, image: img.length, sha256: sha(img), inplace_min_gap: null,
      inplace: 'not simulated: where the bootloader unpacks from is unknown' },
    untouched: ['the container header but for the version', ...dev.protected.map(([lo, hi, why]) => `${why} (${hx(lo)}-${hx(hi)})`)],
    sections: new Map([['3', { stored: s3.length, stored_sha256: sha(s3), stock: false }]]),
  }
  if ('bin' in outputs) {
    const [seed, cont] = decodeBin(outputs.bin)
    if (!equal(cont, concat([o.container, new Uint8Array((4 - (o.container.length % 4)) % 4)])))
      throw new ElekError('the card file does not carry the same container as the .syx')
    facts.bin = { sha256: sha(outputs.bin), bytes: outputs.bin.length, seed: hx(seed) }
  }
  return facts
}

export const packMain = (image: Uint8Array): Uint8Array => packSection(image)
