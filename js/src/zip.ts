// SPDX-License-Identifier: GPL-3.0-or-later
// Just enough of the zip format to take a stock OS file out of the .zip Elektron publishes it in, as elekloader's
// formats._from_zip does with Python's zipfile: the central directory, stored and deflated members (deflate through
// the platform's DecompressionStream), and the CRC-32 check. Its messages are zipfile's.

export class BadZipFile extends Error {}

export type ZipMember = { filename: string; method: number; flags: number; crc: number; compressedSize: number; fileSize: number; offset: number }

const u16 = (d: Uint8Array, at: number) => d[at] | (d[at + 1] << 8)
const u32le = (d: Uint8Array, at: number) => (d[at] | (d[at + 1] << 8) | (d[at + 2] << 16) | (d[at + 3] << 24)) >>> 0

// cp437, the zip format's default name encoding, for bytes 0x80-0xff (zipfile decodes a name so unless flag 11 says UTF-8)
const CP437 = 'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ '

function name(d: Uint8Array, utf8: boolean): string {
  if (utf8) return new TextDecoder('utf-8').decode(d)
  return Array.from(d, b => (b < 0x80 ? String.fromCharCode(b) : CP437[b - 0x80])).join('')
}

/** The members of a zip, from its central directory (zipfile.ZipFile(...).infolist()). */
export function members(raw: Uint8Array): ZipMember[] {
  let end = -1
  for (let i = raw.length - 22; i >= Math.max(0, raw.length - 22 - 0xffff); i--) {
    if (u32le(raw, i) === 0x06054b50) { end = i; break }
  }
  if (end < 0) throw new BadZipFile('File is not a zip file')
  const count = u16(raw, end + 10), size = u32le(raw, end + 12), start = u32le(raw, end + 16)
  if (start + size > end) throw new BadZipFile('Bad magic number for central directory')
  const out: ZipMember[] = []
  let at = start
  for (let k = 0; k < count; k++) {
    if (u32le(raw, at) !== 0x02014b50) throw new BadZipFile('Bad magic number for central directory')
    const flags = u16(raw, at + 8), n = u16(raw, at + 28), e = u16(raw, at + 30), c = u16(raw, at + 32)
    out.push({
      filename: name(raw.subarray(at + 46, at + 46 + n), !!(flags & 0x800)), method: u16(raw, at + 10), flags,
      crc: u32le(raw, at + 16), compressedSize: u32le(raw, at + 20), fileSize: u32le(raw, at + 24), offset: u32le(raw, at + 42),
    })
    at += 46 + n + e + c
  }
  return out
}

let CRC_TABLE: Uint32Array | null = null
function crc32(d: Uint8Array): number {
  if (!CRC_TABLE) {
    CRC_TABLE = new Uint32Array(256)
    for (let n = 0; n < 256; n++) {
      let c = n
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
      CRC_TABLE[n] = c >>> 0
    }
  }
  let c = 0xffffffff
  for (let i = 0; i < d.length; i++) c = CRC_TABLE[(c ^ d[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

async function inflateRaw(d: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([d as Uint8Array<ArrayBuffer>]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}

/** One member's bytes (zipfile's ZipFile.read). */
export async function read(raw: Uint8Array, m: ZipMember): Promise<Uint8Array> {
  if (m.flags & 1) throw new BadZipFile(`File '${m.filename}' is encrypted, password required for extraction`)
  if (u32le(raw, m.offset) !== 0x04034b50) throw new BadZipFile('Bad magic number for file header')
  const start = m.offset + 30 + u16(raw, m.offset + 26) + u16(raw, m.offset + 28)
  const body = raw.subarray(start, start + m.compressedSize)
  let data: Uint8Array
  if (m.method === 0) data = body.slice()
  else if (m.method === 8) {
    try { data = await inflateRaw(body) } catch (e) { throw new BadZipFile('Error -3 while decompressing data: ' + (e as Error).message) }
  } else throw new BadZipFile('That compression method is not supported')
  if (crc32(data) !== m.crc) throw new BadZipFile(`Bad CRC-32 for file '${m.filename}'`)
  return data
}
