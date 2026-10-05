// SPDX-License-Identifier: GPL-3.0-or-later
// One interface over the OS file families a device profile names (Device.container): 'ele3' (syx.ts) and 'elek'
// (elek.ts). Ported from elekloader's formats.py (GPL-2.0-or-later).
//
//     const [stock, dev, rel] = await load(bytes)     // a stock file (or Elektron's zip of it), known by its hash
//     const image = mainImage(stock, dev)
//     const outputs = write(stock, storedMain, dev, version)   // {syx} or {syx, bin}
//     const facts = verify(outputs, stock, wantMain, dev, version)
import { encodeAsciiReplace, equal, sha } from './bytes.ts'
import { packSection } from './codec/aplib.ts'
import { type Device, type Release, UnknownFirmware, identify, supported } from './devices.ts'
import * as elek from './elek.ts'
import { hexw } from './py.ts'
import * as syx from './syx.ts'
import { BadZipFile, members, read } from './zip.ts'

export class FormatError extends Error {}

export type Parsed = syx.Syx | elek.ElekFile

/** A file of `dev`'s family -> its parsed form. */
export function parse(raw: Uint8Array, dev: Device): Parsed {
  try {
    if (dev.container === 'ele3') return new syx.Syx(raw)
    if (dev.container === 'elek') return new elek.ElekFile(raw)
  } catch (e) {
    if (e instanceof syx.SyxError || e instanceof elek.ElekError) throw new FormatError(e.message)
    throw e
  }
  throw new FormatError(`${dev.name}: no reader for the ${dev.container} family`)
}

/** The known stock OS file inside a zip, as Elektron publishes them (a .syx first, then a .bin). -> its bytes. */
async function fromZip(raw: Uint8Array): Promise<Uint8Array> {
  let names: ReturnType<typeof members> = []
  try {
    names = members(raw).filter(i => !i.filename.endsWith('/') && i.fileSize <= 64 << 20
      && /\.(syx|bin)$/i.test(i.filename))
    const key = (i: { filename: string }) => (i.filename.toLowerCase().endsWith('.syx') ? 0 : 1)
    names.sort((a, b) => key(a) - key(b) || (a.filename < b.filename ? -1 : a.filename > b.filename ? 1 : 0))
    for (const i of names) {
      const data = await read(raw, i)
      try {
        identify(sha(data))
      } catch (e) {
        if (e instanceof UnknownFirmware) continue
        throw e
      }
      return data
    }
  } catch (e) {
    if (e instanceof BadZipFile) throw new FormatError('the zip cannot be read: ' + e.message)
    throw e
  }
  throw new UnknownFirmware(`the zip holds no stock firmware elekloader knows (${names.map(i => i.filename).join(', ')
    || 'no .syx or .bin file'}). Supported: ${supported()}`)
}

/** A stock OS file -> [parsed, Device, Release], known by its sha256. A zip stands for the known OS file inside it. */
export async function load(raw: Uint8Array): Promise<[Parsed, Device, Release]> {
  if (raw[0] === 0x50 && raw[1] === 0x4b && raw[2] === 0x03 && raw[3] === 0x04) raw = await fromZip(raw)
  const [dev, rel] = identify(sha(raw))
  return [parse(raw, dev), dev, rel]
}

export const mainImage = (parsed: Parsed, dev: Device): Uint8Array => parsed.section(dev.mainSection)

/** Refuse a version the device's field cannot show. */
export function checkVersion(dev: Device, version: string | null): void {
  if (version === null) return
  const n = encodeAsciiReplace(version).length
  if (dev.container === 'ele3' && n !== dev.versionLen) throw new FormatError(`the version is exactly ${dev.versionLen} ASCII characters`)
  if (!(n > 0 && n <= dev.versionLen)) throw new FormatError(`the version is 1 to ${dev.versionLen} ASCII characters`)
}

export const packMain = (image: Uint8Array): Uint8Array => packSection(image)

export type Outputs = { syx: Uint8Array; bin?: Uint8Array }

/** -> {syx} or, for a family with a card file too, {syx, bin}. */
export function write(stock: Parsed, storedMain: Uint8Array, dev: Device, version: string | null = null): Outputs {
  checkVersion(dev, version)
  try {
    if (dev.container === 'ele3') return { syx: syx.write(stock as syx.Syx, storedMain, dev, version) }
    return elek.write(stock as elek.ElekFile, storedMain, dev, version)
  } catch (e) {
    if (e instanceof syx.SyxError || e instanceof elek.ElekError) throw new FormatError(e.message)
    throw e
  }
}

/** Re-read every output with the decoder and refuse it unless only the main OS (and the version field) changed,
 * and the protected ranges are stock's. -> facts. */
export function verify(outputs: Outputs, stock: Parsed, wantMain: Uint8Array, dev: Device, version: string | null = null) {
  const stockMain = mainImage(stock, dev)
  let facts: Record<string, any>
  try {
    if (dev.container === 'ele3') {
      facts = syx.verify(outputs.syx, stock as syx.Syx, wantMain, dev, version)
      const same = [...(facts.sections as Map<string, syx.Section>)].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .filter(([, v]) => v.stock).map(([s]) => s)
      facts.untouched = [`sections ${same.join(', ')}, byte for byte`]
    } else {
      facts = elek.verify(outputs as Record<string, Uint8Array>, stock as elek.ElekFile, wantMain, dev, stockMain, version)
    }
  } catch (e) {
    if (e instanceof syx.SyxError || e instanceof elek.ElekError) throw new FormatError(e.message)
    throw e
  }
  for (const [lo, hi, why] of dev.protected) {
    const a = lo - dev.mainLoad, b = hi - dev.mainLoad
    if (!equal(wantMain.subarray(a, b), stockMain.subarray(a, b)))
      throw new FormatError(`0x${hexw(lo)}-0x${hexw(hi)} (${why}) is not stock`)
  }
  return facts
}
