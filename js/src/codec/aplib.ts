// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from elekloader's codec/aplib.py (GPL-2.0-or-later; vendored there from digikit, dt2/aplib.py, by Em D,
// with the match-finder and the compressed output by irpina). It writes the same bytes as the Python for any
// input: the same greedy match-finder, ties broken the same way, the same terminator. See aplib.py for the
// format and how each rule was confirmed against the device's own depacker.

const BIAS = 767            // offset = ((g << 8) + byte) - 767
const FAR = 3328            // past this, the decoder adds 1 to the length
const REUSE = 2             // a gamma of 2 reuses the last offset
const MIN_MATCH = 3         // below this a match costs more bits than literals
const MAX_OFFSET = 1 << 16
const MAX_COUNT = 1 << 12
const CANDIDATES = 24
const TERMINATOR_GAMMA = (1 << 24) + 2     // with a trailing 0xFF byte: (2**24+2)*256 + 255 == 0x2FF mod 2**32
const TERMINATOR_TRAILER = 0xff

/** The (tag bit, payload) event stream, written as the depacker reads it: a tag byte per 8 events, MSB first,
 * that group's payload bytes right after it (aplib.py _assemble). */
class Events {
  out: Uint8Array
  n = 0
  private tagAt = 0
  private count = 0
  constructor(size: number) { this.out = new Uint8Array(Math.max(64, size)) }
  private push(b: number) {
    if (this.n === this.out.length) {
      const more = new Uint8Array(this.out.length * 2)
      more.set(this.out)
      this.out = more
    }
    this.out[this.n++] = b
  }
  event(bit: number, payload = -1) {
    const slot = this.count & 7
    if (slot === 0) { this.tagAt = this.n; this.push(0) }
    if (bit & 1) this.out[this.tagAt] |= 0x80 >> slot
    this.count++
    if (payload >= 0) this.push(payload)
  }
  /** The depacker's gamma2 code for `value` (>= 2): each bit after the leading 1, then a stop bit, 1 on the
   * last. `trailer` rides on that last stop bit (a match's offset byte, the terminator's 0xFF). */
  gamma(value: number, trailer = -1) {
    if (value < 2) throw new Error('gamma2 cannot encode values below 2, got ' + value)
    for (let b = 30 - Math.clz32(value); b >= 0; b--) {
      this.event((value >>> b) & 1)
      this.event(b === 0 ? 1 : 0, b === 0 ? trailer : -1)
    }
  }
  bytes(): Uint8Array { return this.out.slice(0, this.n) }
}

function match(ev: Events, offset: number, count: number) {
  if (!(offset >= 1 && offset <= MAX_OFFSET)) throw new Error(`offset ${offset} out of range`)
  let length = count - 1
  if (offset > FAR) length -= 1           // the decoder will add it back
  if (length < 1) throw new Error(`count ${count} too small for offset ${offset}`)
  const raw = offset + BIAS
  const g = raw >>> 8
  if (g === REUSE) throw new Error(`offset ${offset} would encode as the reuse code`)
  ev.event(0)                             // a match
  ev.gamma(g, raw & 0xff)                 // the offset's gamma, its raw byte riding the last bit
  if (length >= 1 && length <= 3) {
    ev.event((length >> 1) & 1)
    ev.event(length & 1)
  } else {
    ev.event(0)                           // 00: a gamma follows
    ev.event(0)
    ev.gamma(length - 2)
  }
}

/** aplib.py _find_matches: greedy, non-overlapping [pos, offset, count] triples, in order. The three bytes at
 * each position index the positions they last appeared at (the newest 24); the newest candidate is tried first. */
function findMatches(data: Uint8Array): [number, number, number][] {
  const n = data.length
  const out: [number, number, number][] = []
  if (n < MIN_MATCH) return out
  const table = new Map<number, number[]>()
  const key = (p: number) => (data[p] << 16) | (data[p + 1] << 8) | data[p + 2]
  const remember = (k: number, p: number) => {
    let chain = table.get(k)
    if (!chain) { chain = []; table.set(k, chain) }
    chain.push(p)
    if (chain.length > CANDIDATES) chain.splice(0, chain.length - CANDIDATES)
  }
  let i = 0
  while (i < n - MIN_MATCH) {
    const k = key(i)
    let bestOff = 0, bestLen = 0
    const chain = table.get(k)
    if (chain) {
      for (let c = chain.length - 1; c >= 0; c--) {
        const j = chain[c], off = i - j
        if (off <= 0 || off > MAX_OFFSET) continue
        const limit = Math.min(MAX_COUNT, n - i)
        let len = 0
        while (len < limit && data[j + len] === data[i + len]) len++
        const need = MIN_MATCH + (off > FAR ? 1 : 0)
        if (len >= need && len > bestLen) {
          bestOff = off
          bestLen = len
          if (len >= 64) break
        }
      }
    }
    remember(k, i)
    if (bestLen) {
      out.push([i, bestOff, bestLen])
      for (let s = 1; s < bestLen; s++) {       // index the covered positions so later matches can reach in
        const p = i + s
        if (p < n - MIN_MATCH) remember(key(p), p)
      }
      i += bestLen
    } else {
      i += 1
    }
  }
  return out
}

function terminate(ev: Events) {
  ev.event(0)
  ev.gamma(TERMINATOR_GAMMA, TERMINATOR_TRAILER)
}

/** A valid stream for the device's depacker, without the section header. `compress` false stores every byte as
 * a literal (always a little larger than the input), as aplib.py's pack(compress=False). */
export function pack(data: Uint8Array, compress = true): Uint8Array {
  const ev = new Events(Math.ceil(data.length * 1.15) + 64)
  if (compress) {
    const matches = findMatches(data)
    let m = 0, i = 0
    while (i < data.length) {
      if (m < matches.length && matches[m][0] === i) {
        const [, off, count] = matches[m++]
        match(ev, off, count)
        i += count
      } else {
        ev.event(1, data[i])
        i += 1
      }
    }
  } else {
    for (let i = 0; i < data.length; i++) ev.event(1, data[i])
  }
  terminate(ev)
  return ev.bytes()
}

/** pack(data) with the section's 8-byte header: big-endian [u32 stream length][u32 byte sum of the stream]. */
export function packSection(data: Uint8Array, compress = true): Uint8Array {
  const body = pack(data, compress)
  const out = new Uint8Array(8 + body.length)
  let sum = 0
  for (let i = 0; i < body.length; i++) sum += body[i]
  const v = new DataView(out.buffer)
  v.setUint32(0, body.length)
  v.setUint32(4, sum >>> 0)
  out.set(body, 8)
  return out
}
