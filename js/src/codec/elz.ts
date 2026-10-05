// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from elekloader's codec/elz.py (GPL-2.0-or-later; vendored there from digikit, dt2/elz.py, by Em D):
// the decoder for the LZ codec of Elektron's ELE3 and ELEK firmware sections. It matches the device's own depacker
// byte for byte. The format reference is mischa85/elektron-firmware-tool (MIT), aplib.c `ap_depack`:
//   * a section is [u32 BE stream length][u32 BE byte sum] + stream (+ zero padding);
//   * control bits are read MSB first from tag bytes fetched on demand; 1 = literal byte, 0 = match;
//   * a match begins with an interlaced Elias-gamma g (data bit, then a stop bit: 1 stops). g == 2 reuses the
//     last offset; otherwise raw = (g << 8) + byte, raw == 767 ends the stream, offset = raw - 767 (32-bit);
//   * two bits give a short length 1..3; 00 means gamma + 2 follows. Past offset 3328 the length gains 1. The
//     copy count is length + 1.

export const BIAS = 767
export const REUSE = 2
export const FAR = 3328

/** Python's EOFError: the stream ended inside a symbol. */
export class EOFError extends Error {}

export class Bits {
  tag = 0
  readonly d: Uint8Array
  p: number
  readonly end: number
  constructor(d: Uint8Array, p: number, end: number) {
    this.d = d
    this.p = p
    this.end = end
  }

  byte(): number {
    if (this.p >= this.end) throw new EOFError()
    return this.d[this.p++]
  }

  bit(): number {
    this.tag = (this.tag << 1) & 0x1ff
    if ((this.tag & 0xff) === 0) {
      const b = this.byte()
      this.tag = (b << 1) | 1
      return b >> 7
    }
    return this.tag >> 8
  }

  gamma(): number {
    let v = 1
    for (;;) {
      v = (v << 1) | this.bit()
      if (this.bit()) return v
      if (v > 0x02000000) throw new Error('gamma overflow')
    }
  }
}

/** A growable output buffer that copies matches byte by byte (they may overlap). */
export class Out {
  d: Uint8Array
  n = 0
  constructor(size = 1 << 16) { this.d = new Uint8Array(size) }
  private grow(need: number) {
    let size = this.d.length
    while (size < need) size *= 2
    const more = new Uint8Array(size)
    more.set(this.d.subarray(0, this.n))
    this.d = more
  }
  push(b: number) {
    if (this.n === this.d.length) this.grow(this.n + 1)
    this.d[this.n++] = b
  }
  copy(off: number, count: number) {
    if (this.n + count > this.d.length) this.grow(this.n + count)
    const d = this.d
    for (let k = 0; k < count; k++, this.n++) d[this.n] = d[this.n - off]
  }
  bytes(): Uint8Array { return this.d.slice(0, this.n) }
}

/** -> [output bytes, input position after the end marker]. */
export function depack(data: Uint8Array, pos: number, end: number): [Uint8Array, number] {
  const s = new Bits(data, pos, end)
  const out = new Out(Math.max(1 << 16, (end - pos) * 2))
  let last = 1
  for (;;) {
    if (s.bit()) { out.push(s.byte()); continue }
    const g = s.gamma()
    let off: number
    if (g === REUSE) {
      off = last
    } else {
      const raw = (g * 256 + s.byte()) >>> 0
      if (raw === BIAS) return [out.bytes(), s.p]
      off = (raw - BIAS) >>> 0
      last = off
    }
    const short = 2 * s.bit() + s.bit()
    let length = short ? short : s.gamma() + 2
    if (off > FAR) length += 1
    if (off === 0 || off > out.n) throw new Error(`offset ${off} outside ${out.n} bytes of output`)
    out.copy(off, length + 1)
  }
}

/** Depack a section that starts with its [u32 length][u32 sum] header. Throws when the end marker does not land
 * exactly on the declared stream length. */
export function depackSection(stream: Uint8Array): Uint8Array {
  const length = ((stream[0] << 24) | (stream[1] << 16) | (stream[2] << 8) | stream[3]) >>> 0
  const [out, end] = depack(stream, 8, 8 + length)
  if (end !== 8 + length) throw new Error(`end marker at ${end - 8} of ${length} stream bytes`)
  return out
}
