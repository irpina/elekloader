// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from elekloader's codec/transport.py (GPL-2.0-or-later; vendored there from digikit, dt2/build.py, by
// Em D, with changes by irpina): the SysEx transport of an Elektron OS file. 8-in-7, the 128-byte messages with
// their counters and checksums, the framing messages' count, and the container's content checksum.

export const MFR = Uint8Array.of(0x00, 0x20, 0x3c)   // Elektron's SysEx manufacturer id
export const FIRST_COUNTER = 242
export const CHUNK_SIZE = 101                         // decoded bytes carried by one 128-byte message

/** 8-in-7: one marker byte per up-to-7 data bytes, holding their high bits MSB first, then those bytes with the
 * high bit stripped. A short final group is handled the same way as a full one. */
export function encode8in7(data: Uint8Array): Uint8Array {
  const out = new Uint8Array(data.length + Math.ceil(data.length / 7))
  let n = 0
  for (let start = 0; start < data.length; start += 7) {
    const end = Math.min(start + 7, data.length)
    let marker = 0
    for (let k = start; k < end; k++) if (data[k] & 0x80) marker |= 1 << (6 - (k - start))
    out[n++] = marker
    for (let k = start; k < end; k++) out[n++] = data[k] & 0x7f
  }
  return out
}

/** The preamble's 32-bit checksum: the sum of (1-based word index XOR big-endian u32 word) over the whole
 * container, trailer included, mod 2**32. */
export function contentChecksum(container: Uint8Array): number {
  let acc = 0
  const words = container.length >> 2
  for (let idx = 1; idx <= words; idx++) {
    const j = 4 * (idx - 1)
    const word = ((container[j] << 24) | (container[j + 1] << 16) | (container[j + 2] << 8) | container[j + 3]) >>> 0
    acc = (acc + ((idx ^ word) >>> 0)) >>> 0
  }
  return acc
}

/** Message byte 125, from the 125 bytes of header and payload before it. `body` is the message between F0 and
 * F7; `k` the transfer-type constant the framing message carries. */
export function packetChecksum(body: Uint8Array, k: number): number {
  let total = k
  for (let i = 0; i < 119; i++) total += body[6 + i] ^ (i + k)
  return total & 0x7f
}

/** A 16-byte framing message with its data-message count (body bytes 11..13, 21-bit base-128) set to `n`. */
function patchFramingCount(msg: Uint8Array, n: number): Uint8Array {
  const out = msg.slice()
  out[12] = (n >> 14) & 0x7f
  out[13] = (n >> 7) & 0x7f
  out[14] = n & 0x7f
  return out
}

/** The decoded byte stream -> .syx bytes: CHUNK_SIZE-byte pieces, each 8-in-7 encoded into a 128-byte message
 * with a counter from FIRST_COUNTER and a checksum, between the stock file's two framing messages (their count
 * set to the number of data messages). The last piece is padded with zeros. */
export function encodeSyx(stream: Uint8Array, deviceId: number, framingStart: Uint8Array, framingEnd: Uint8Array): Uint8Array {
  const k = framingStart[8]                           // the transfer-type constant
  const nMsgs = Math.ceil(stream.length / CHUNK_SIZE)
  const start = patchFramingCount(framingStart, nMsgs), end = patchFramingCount(framingEnd, nMsgs)
  const out = new Uint8Array(start.length + 128 * nMsgs + end.length)
  out.set(start, 0)
  let at = start.length
  const chunk = new Uint8Array(CHUNK_SIZE)
  for (let m = 0; m < nMsgs; m++) {
    chunk.fill(0)
    chunk.set(stream.subarray(m * CHUNK_SIZE, (m + 1) * CHUNK_SIZE))
    const counter = FIRST_COUNTER + m
    const body = new Uint8Array(126)
    body.set(MFR, 0)
    body.set([deviceId, 0x00, 0x7e, (counter >> 14) & 0x7f, (counter >> 7) & 0x7f, counter & 0x7f], 3)
    body.set(encode8in7(chunk), 9)
    body[125] = packetChecksum(body, k) & 0x7f
    out[at++] = 0xf0
    out.set(body, at)
    at += 126
    out[at++] = 0xf7
  }
  out.set(end, at)
  return out
}
