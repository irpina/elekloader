// SPDX-License-Identifier: GPL-3.0-or-later
// Your stock OS file + .elemod files -> a custom firmware. Ported from elekloader's patch.py (GPL-2.0-or-later):
// build() takes the same steps in the same order, stopping at the first failure, and save() writes the same files,
// byte for byte, the manifest and the symbol map included. Files here are bytes with a path, not a file system.
//   1. the stock file must be a release elekloader knows (by its sha256), and its main OS the known image;
//   2. every mod must be made for that release, and every site's stock bytes must hash to what the mod expects;
//   3. the static conflict check, including the device's protected ranges;
//   4. apply the sites, or link the mods;
//   5. repack the main OS and rebuild the OS file: only the main OS and the version field change;
//   6. verify every output with independent code (formats.verify);
//   7. the .syx and, for a device with a card file (the Octatrack), the .bin; OUT.json (a manifest with every hash);
//      and, for linked mods, OUT.map.json (every symbol's address).
import { sha } from './bytes.ts'
import { UnknownFirmware } from './devices.ts'
import { type AnyMod, Mod, ModError, apply, formatOf, get, pyEq, readJson } from './elemod.ts'
import * as formats from './formats.ts'
import { Mod2, link, type Linked } from './link.ts'
import { dumps, hex8, hexw, repr, str, truthy } from './py.ts'

export class PatchError extends Error {}

export type File = { path: string; data: Uint8Array }

export const basename = (p: string): string => p.slice(p.lastIndexOf('/') + 1)
const dirname = (p: string): string => (p.lastIndexOf('/') > 0 ? p.slice(0, p.lastIndexOf('/')) : p.startsWith('/') ? '/' : '')

/** os.path.abspath on the in-memory paths (they are already absolute): '..', '.' and doubled slashes resolved. */
export function abspath(p: string): string {
  const out: string[] = []
  for (const part of p.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') out.pop()
    else out.push(part)
  }
  return '/' + out.join('/')
}

/** A format-1 Mod or a format-2 Mod2, by the file's "elemod" (elemod.load_any). */
export function loadAny(file: File): AnyMod {
  const doc = readJson(file.data, file.path)
  const name = basename(file.path)
  if (pyEq(formatOf(doc), 2)) return new Mod2(doc as Record<string, any>, name, file.data)
  return new Mod(doc as Record<string, any>, name, file.data)
}

const pad = (s: string, n: number) => s + ' '.repeat(Math.max(0, n - s.length))
const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())

/** -> [outputs {syx[, bin]} or null, manifest]. Throws PatchError. `stock` is the stock file (or Elektron's zip). */
export async function build(stock: File, modFiles: File[], version: string | null = null, checkOnly = false,
  log: (line: string) => void = () => {}): Promise<[formats.Outputs | null, Record<string, any>]> {
  let parsed: formats.Parsed, dev, rel
  try {
    [parsed, dev, rel] = await formats.load(stock.data)
  } catch (e) {
    if (e instanceof UnknownFirmware || e instanceof formats.FormatError) throw new PatchError(`${stock.path}: ${e.message}`)
    throw e
  }
  const img0 = formats.mainImage(parsed, dev)
  if (sha(img0) !== rel.mainSha256) throw new PatchError(`its main OS is not the known ${dev.name} ${rel.version} image`)
  log(`stock: ${dev.name} OS ${rel.version} (${parsed.sha256})`)
  const mods: AnyMod[] = []
  for (const f of modFiles) {
    let m: AnyMod
    try {
      m = loadAny(f)
    } catch (e) {
      if (e instanceof ModError) throw new PatchError(e.message)
      throw e
    }
    if (m.dev.key !== dev.key || m.rel !== rel)
      throw new PatchError(`${m.label()} is made for ${m.dev.name} ${m.rel.version}; your stock firmware is ${dev.name} ${rel.version}`)
    log(`mod ${pad(m.label(), 24)} ${m.sites.length} sites${m.blob ? `, blob ${m.blob.len} bytes` : ''}  (file sha256 ${m.sha256!.slice(0, 16)})`)
    mods.push(m)
  }
  if (!mods.length) throw new PatchError('no mods given')
  const v2 = mods.filter(m => m.format === 2) as Mod2[]
  let linked: Linked | null = null
  let img: Uint8Array
  try {
    if (v2.length) {
      if (v2.length !== mods.length) throw new ModError('a whole-build bundle (format 1) cannot be combined with separate mods (format 2)')
      linked = link(v2, img0)
      img = linked.image
    } else {
      img = apply(mods as Mod[], img0)
    }
  } catch (e) {
    if (e instanceof ModError) throw new PatchError(e.message)
    throw e
  }
  log('the mods combine: no overlaps, stock bytes as expected, code sites whole instructions')
  if (linked) {
    const L = linked.layout
    log(`linked ${linked.order.join(', ')}: RAM ${hex8(L.ddr[0])}-${hex8(L.bss[1])} (${L.ddr_spare} bytes spare), .fast to `
      + `${hex8(L.fast[1])} (${L.fast_spare} spare), blob ${L.blob_len} bytes`)
  }
  const man: Record<string, any> = {
    patcher: 'elekloader', device: dev.key,
    stock: { path: abspath(stock.path), sha256: parsed.sha256, os: rel.version, main_sha256: sha(img0) },
    mods: mods.map(m => ({
      id: m.id, version: m.version, file: m.name, sha256: m.sha256, format: m.format, sites: m.sites.length,
      regions: m.regions.map(g => ({ name: g.name, lo: hex8(g.lo), hi: hex8(g.hi), area: g.area })),
      names: m.names,
    })),
    main_sha256: sha(img),
    main_len: img.length,
  }
  if (linked) {
    const tables: Record<string, unknown> = {}
    for (const [c, [a, n, e]] of [...linked.tables].sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0)))
      tables[c] = { at: hex8(a), entries: n, entry: e }
    man.link = { order: linked.order, layout: linked.layout, tables }
    man._map = linked.map
  }
  if (mods.length === 1 && !v2.length) {
    const b = get(mods[0].doc, 'build')
    const want = get(truthy(b) ? b : {}, 'section3_sha256')
    if (truthy(want)) {
      man.bundle_matches_build = want === sha(img)
      if (want !== sha(img)) throw new PatchError('the bundle does not reproduce its build\'s main OS')
      log(`the main OS matches the build the bundle came from (sha256 ${sha(img).slice(0, 16)})`)
    }
  }
  if (checkOnly) return [null, man]
  if (version === null) {
    const vs: unknown[] = []
    for (const m of mods) {
      const v = get(m.doc, 'ele3_version')
      if (v !== null && !vs.some(x => x === v)) vs.push(v)
    }
    if (vs.length !== 1) {
      const sorted = [...vs].sort((a, b) => (String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0))
      throw new PatchError(`give --version (${dev.container === 'ele3' ? `${dev.versionLen} characters` : `up to ${dev.versionLen} characters`}): `
        + `the mods name ${sorted.length ? repr(sorted) : 'no version'}`)
    }
    version = str(vs[0])
  }
  try {
    formats.checkVersion(dev, version)
  } catch (e) {
    if (e instanceof formats.FormatError) throw new PatchError(e.message)
    throw e
  }
  const t = now()
  const stored = formats.packMain(img)
  log(`packed the main OS: ${img.length} -> ${stored.length} bytes (${((now() - t) / 1000).toFixed(1)} s)`)
  let outputs: formats.Outputs, facts: Record<string, any>
  try {
    outputs = formats.write(parsed, stored, dev, version)
    facts = formats.verify(outputs, parsed, img, dev, version)
  } catch (e) {
    if (e instanceof formats.FormatError) throw new PatchError(`the output failed verification: ${e.message}`)
    throw e
  }
  const gap = facts.main.inplace_min_gap
  log(`verified: ${facts.untouched.join('; ')}; the main OS depacks to the patched image${gap !== null && gap !== undefined
    ? ` in place (min gap ${gap} bytes)` : ''}; flash ends ${facts.flash_end} (${facts.flash_headroom} bytes spare)`)
  man.version = version
  man.output = facts
  return [outputs, man]
}

/** The path of a second output next to `path` (the .bin beside a .syx). */
export function companion(path: string, kind: string): string {
  const base = basename(path)
  const dot = base.lastIndexOf('.')
  const ext = dot > 0 ? base.slice(dot) : ''
  return (ext.toLowerCase() === '.syx' ? path.slice(0, path.length - ext.length) : path) + '.' + kind
}

const enc = new TextEncoder()

/** The .syx at `path` (and the .bin beside it), and the manifest (and symbol map) next to it, as patch.save writes
 * them. -> the files, in the order written. Changes `man` as save does. */
export function save(outputs: formats.Outputs, man: Record<string, any>, path: string): File[] {
  const written: File[] = []
  for (const [kind, data] of Object.entries(outputs) as [string, Uint8Array][])
    written.push({ path: kind === 'syx' ? path : companion(path, kind), data })
  man.output.path = abspath(path)
  if (outputs.bin) man.output.bin_path = abspath(companion(path, 'bin'))
  const smap = man._map as Map<string, number> | undefined
  delete man._map
  const extra: File[] = []
  if (smap !== undefined) {
    const sorted = [...smap].sort(([a, x], [b, y]) => (a < b ? -1 : a > b ? 1 : x - y))
    extra.push({ path: path + '.map.json', data: enc.encode(dumps(new Map(sorted.map(([k, v]) => [k, '0x' + hexw(v, 8)])), 0)) })
    man.map = basename(path) + '.map.json'
  }
  return [...written, ...extra, { path: path + '.json', data: enc.encode(dumps(man, 1)) }]
}

export { dirname }
