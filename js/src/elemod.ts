// SPDX-License-Identifier: GPL-3.0-or-later
// The .elemod file: shared validation, format 1 (whole-build bundles), the instruction-boundary check, and apply for
// bundles. Format 2 (separate, linkable mods) is link.ts. Ported from elekloader's elemod.py (GPL-2.0-or-later);
// the format is docs/FORMAT.md. Every refusal says what the Python says.
//
// A .elemod is JSON. It carries only its author's bytes plus hashes of the stock bytes it expects, and it can only
// describe changes to the device's main OS: the bootloader and the other sections stay stock by construction.
import { concat, encodeAsciiReplace, fromHex, sha } from './bytes.ts'
import { type Device, type Release, UnknownFirmware, forTarget, imageEnd, linkable } from './devices.ts'
import { ILLEGAL, LINEF, FPU, decodeColdFire, readerAt } from './isa/coldfire.ts'
import { AttributeError, PyFloat, TypeError_, ValueError, hex8, pyInt, pyType, repr, str, truthy } from './py.ts'
import { decodeUtf8, loads } from './pyjson.ts'

export const FORMAT = 1
export const EXTS = ['.elemod', '.dtmod']   // what the loader lists; the SDK writes .elemod

export class ModError extends Error {}

/** Python's ==, for a JSON value and an int: True == 1 and 1.0 == 1 there. */
export const pyEq = (v: unknown, n: number): boolean =>
  v === n || (typeof v === 'boolean' && Number(v) === n) || (v instanceof PyFloat && v.value === n)

/** The file's format number, from "elemod" or the legacy "dtmod". */
export function formatOf(doc: unknown): unknown {
  if (!isDict(doc)) return null
  return 'elemod' in doc ? doc.elemod : ('dtmod' in doc ? doc.dtmod : null)
}

export const isDict = (v: unknown): v is Record<string, any> =>
  typeof v === 'object' && v !== null && !Array.isArray(v) && !(v instanceof PyFloat)

/** d.get(k, default), and Python's AttributeError when d is not a dict. */
export function get(d: unknown, k: string, dflt: unknown = null): any {
  if (!isDict(d)) throw new AttributeError(`'${pyType(d)}' object has no attribute 'get'`)
  return k in d ? d[k] : dflt
}

/** elemod._int: an int, or a string Python's int(v, 0) reads. */
export function int(v: unknown, what: string): number {
  const n = pyInt(v)
  if (n === null) throw new ModError(`${what}: ${repr(v)} is not a number`)
  return n
}

export function hexBytes(v: unknown, what: string): Uint8Array {
  const b = typeof v === 'string' ? fromHex(v) : null
  if (!b) throw new ModError(`${what}: not hex`)
  return b
}

/** -> [Device, Release] for a mod's "target", or ModError. */
export function resolveTarget(doc: Record<string, any>, name: string): [Device, Release] {
  try {
    return forTarget(get(doc, 'target'))
  } catch (e) {
    if (e instanceof UnknownFirmware) throw new ModError(`${name}: ${e.message}`)
    throw e
  }
}

export type Part = ['hex', Uint8Array] | ['stock', number, number]

/** [["hex", "..."] | ["stock", addr, n], ...] -> parts. A stock part is n bytes the patcher copies from the user's
 * own (hash-checked) stock image: what a mod repeats from the firmware is never shipped. */
export function parseParts(parts: unknown, what: string, dev: Device, rel: Release): Part[] {
  const lo = dev.mainLoad, hi = imageEnd(dev, rel)
  const out: Part[] = []
  for (const p of iter(parts)) {
    const list = Array.isArray(p) ? p : null
    if (list && list.length && list[0] === 'hex' && list.length === 2) {
      out.push(['hex', hexBytes(list[1], what + ' part')])
    } else if (list && list.length && list[0] === 'stock' && list.length === 3) {
      const a = int(list[1], what + ' part'), k = int(list[2], what + ' part')
      if (a < lo || a + k > hi || k <= 0) throw new ModError(`${what}: a part copies ${hex8(a)} +${k}, outside the image`)
      out.push(['stock', a, k])
    } else {
      throw new ModError(`${what}: bad part ${repr(p)}`)
    }
  }
  return out
}

/** Iterating a JSON value as Python would: a list's items, a dict's keys, a string's characters; TypeError else. */
export function iter(v: unknown): unknown[] {
  if (Array.isArray(v)) return v
  if (typeof v === 'string') return Array.from(v)
  if (isDict(v)) return Object.keys(v)
  throw new TypeError_(`'${pyType(v)}' object is not iterable`)
}

export const partsLen = (parts: Part[]): number => parts.reduce((n, p) => n + (p[0] === 'hex' ? p[1].length : p[2]), 0)

export function partsBytes(parts: Part[], image: Uint8Array, dev: Device): Uint8Array {
  return concat(parts.map(p => (p[0] === 'hex' ? p[1] : image.subarray(p[1] - dev.mainLoad, p[1] - dev.mainLoad + p[2]))))
}

export type Reloc = [number, string, string, number]          // offset, type, target, addend
export type Site = { addr: number; len: number; new: Uint8Array; kind: string; stock_sha256: string; relocs: Reloc[] }

export function parseSites(doc: Record<string, any>, name: string, dev: Device, rel: Release, relocs = false): Site[] {
  const lo = dev.mainLoad, hi = imageEnd(dev, rel)
  const out: Site[] = []
  iter(get(doc, 'sites', [])).forEach((s, i) => {
    const what = `${name} site ${i}`
    const addr = int(get(s, 'addr'), what), n = int(get(s, 'len'), what)
    const nw = hexBytes(get(s, 'new'), what)
    if (nw.length !== n || n <= 0) throw new ModError(`${what}: "new" is not ${n} bytes`)
    if (addr < lo || addr + n > hi) throw new ModError(`${what}: ${hex8(addr)} +${n} is outside the stock image`)
    const kind = get(s, 'kind')
    if (kind !== 'code' && kind !== 'data') throw new ModError(`${what}: kind is "code" or "data"`)
    const h = get(s, 'stock_sha256')
    if (typeof h !== 'string' || h.length !== 64) throw new ModError(`${what}: no stock_sha256`)
    const site: Site = { addr, len: n, new: nw, kind, stock_sha256: h.toLowerCase(), relocs: [] }
    if (relocs) {
      for (const r of iter(get(s, 'relocs', []))) {
        const [off0, typ, tgt, add] = unpack(r, 4)
        const off = int(off0, what)
        if (!['abs32', 'pc32', 'pc16'].includes(typ as string) || off < 0 || off + (typ === 'pc16' ? 2 : 4) > n)
          throw new ModError(`${what}: bad relocation ${repr(r)}`)
        site.relocs.push([off, typ as string, tgt as string, int(add, what)])
      }
    }
    out.push(site)
  })
  return out
}

/** Python's `a, b, ... = r` for `n` names. */
export function unpack(r: unknown, n: number): unknown[] {
  const v = iter(r)
  if (v.length > n) throw new ValueError(`too many values to unpack (expected ${n})`)
  if (v.length < n) throw new ValueError(`not enough values to unpack (expected ${n}, got ${v.length})`)
  return v
}

export type Region = { name: string; lo: number; hi: number; area: string }

export function parseResources(doc: Record<string, any>, name: string, dev: Device): [Region[], string[]] {
  const r0 = get(doc, 'resources'), r = truthy(r0) ? r0 : {}
  const regions: Region[] = []
  for (const g of iter(get(r, 'regions', []))) {
    const lo = int(get(g, 'lo'), name + ' region'), hi = int(get(g, 'hi'), name + ' region')
    if (!(lo < hi)) throw new ModError(`${name}: empty region ${repr(g)}`)
    const area = Object.entries(dev.areas).filter(([, [a, z]]) => a <= lo && hi <= z).map(([k]) => k)
    if (!area.length) throw new ModError(`${name}: region ${str(get(g, 'name'))} ${hex8(lo)}-${hex8(hi)} is outside every free area`)
    regions.push({ name: str(get(g, 'name', '?')), lo, hi, area: area[0] })
  }
  return [regions, iter(get(r, 'names', [])).map(x => str(x))]
}

export const COMMON = new Set(['elemod', 'dtmod', 'id', 'version', 'title', 'description', 'category', 'author',
  'license', 'target', 'sites', 'resources', 'requires', 'conflicts', 'build', 'signature', 'notes'])

/** What both formats share: the loader treats a format-1 Mod and a format-2 Mod2 alike for these. */
export type AnyMod = {
  format: 1 | 2
  doc: Record<string, any>
  name: string
  sha256: string | null
  id: string
  version: string
  dev: Device
  rel: Release
  sites: Site[]
  blob: Blob | null
  regions: Region[]
  names: string[]
  requires: string[]
  conflicts: string[]
  label(): string
}

export type Blob = { load: number; len: number; sha256: string; parts: Part[] }

/** A format-1 mod: a whole build as one file (sites + one appended blob). */
export class Mod implements AnyMod {
  readonly format = 1
  doc: Record<string, any>
  name: string
  sha256: string | null
  id: string
  version: string
  dev: Device
  rel: Release
  sites: Site[]
  blob: Blob | null
  regions: Region[]
  names: string[]
  requires: string[]
  conflicts: string[]

  constructor(doc: Record<string, any>, name = '<mod>', raw: Uint8Array | null = null) {
    this.doc = doc
    this.name = name
    this.sha256 = raw ? sha(raw) : null
    if (!pyEq(formatOf(doc), FORMAT)) throw new ModError(`${name}: not a format-${FORMAT} .elemod file`)
    for (const k of ['id', 'version', 'target', 'sites']) if (!(k in doc)) throw new ModError(`${name}: no "${k}"`)
    const extra = Object.keys(doc).filter(k => !COMMON.has(k) && k !== 'ele3_version' && k !== 'blob').sort()
    if (extra.length) throw new ModError(`${name}: unknown fields ${repr(extra)}`)
    this.id = str(doc.id)
    this.version = str(doc.version)
    ;[this.dev, this.rel] = resolveTarget(doc, name)
    const ev = get(doc, 'ele3_version')              // the version the unit shows (any device)
    if (ev !== null) {
      const n = typeof ev === 'string' ? encodeAsciiReplace(ev).length : -1
      const exact = this.dev.container === 'ele3'
      if ((exact && n !== this.dev.versionLen) || !(n > 0 && n <= this.dev.versionLen))
        throw new ModError(`${name}: ele3_version is ${exact ? 'exactly' : 'up to'} ${this.dev.versionLen} ASCII characters on the ${this.dev.name}`)
    }
    this.sites = parseSites(doc, name, this.dev, this.rel)
    this.blob = null
    const b = get(doc, 'blob')
    if (b !== null) {
      const load = int(get(b, 'load'), name + ' blob'), n = int(get(b, 'len'), name + ' blob')
      const parts = parseParts(get(b, 'parts', []), name + ' blob', this.dev, this.rel)
      const total = partsLen(parts)
      if (total !== n) throw new ModError(`${name}: blob parts make ${total} bytes, not ${n}`)
      const room = this.dev.blobMax !== null ? this.dev.blobMax : (linkable(this.dev) ? this.dev.ddr[1] - this.dev.ddr[0] : null)
      if (room !== null && n > room) throw new ModError(`${name}: blob of ${n} bytes is over the ${room} the ${this.dev.name} allows`)
      this.blob = { load, len: n, sha256: str(get(b, 'sha256', '')).toLowerCase(), parts }
    }
    ;[this.regions, this.names] = parseResources(doc, name, this.dev)
    this.requires = iter(get(doc, 'requires', [])).map(x => str(x))
    this.conflicts = iter(get(doc, 'conflicts', [])).map(x => str(x))
  }

  label(): string { return `${this.id} ${this.version}` }
}

/** The JSON of a .elemod's bytes, or ModError as read_json gives it. */
export function readJson(raw: Uint8Array, path: string): unknown {
  try {
    return loads(decodeUtf8(raw))
  } catch (e) {
    throw new ModError(`${path}: not JSON (${(e as Error).message})`)
  }
}

// ---- instruction boundaries ----

/** Does [addr, addr+n) of `image` (loaded at dev.mainLoad) hold whole instructions? -> [ok, note]. The end is
 * exact: decoding from addr must land on addr+n with no illegal word. The start cannot be proven by decoding
 * forward, so `sweeps` linear sweeps, started 32 to 94 bytes before addr, must all land on it (elemod.py). */
export function insnCheck(image: Uint8Array, addr: number, n: number, dev: Device, sweeps = 32): [boolean, string] {
  const read = readerAt(image, dev.mainLoad)
  const bad = ILLEGAL | LINEF | FPU
  let a = addr
  while (a < addr + n) {
    const ins = decodeColdFire(read(a), a)
    if (ins.flags & bad) return [false, `${hex8(a)} does not decode`]
    a += ins.length
  }
  if (a !== addr + n) return [false, `ends mid-instruction (${hex8(a)})`]
  let land = 0, ran = 0
  for (let k = 16; k < 16 + sweeps; k++) {
    let pc = addr - 2 * k
    if (pc < dev.mainLoad) break
    while (pc < addr) pc += decodeColdFire(read(pc), pc).length
    ran++
    if (pc === addr) land++
  }
  if (land !== ran) return [false, `only ${land} of ${ran} sweeps land on the start`]
  return [true, 'whole instructions']
}

// ---- the static check, and apply for bundles ----

export type Span<M> = [number, number, M | null, string]

/** [(lo, hi, ...)] -> every pair that shares a byte. */
export function overlaps<T extends [number, number, ...unknown[]]>(spans: T[]): [T, T][] {
  const s = spans.map((x, i) => [x, i] as const).sort((a, b) => a[0][0] - b[0][0] || a[0][1] - b[0][1] || a[1] - b[1]).map(([x]) => x)
  const out: [T, T][] = []
  for (let i = 0; i < s.length; i++) {
    for (let j = i + 1; j < s.length; j++) {
      if (s[j][0] >= s[i][1]) break
      out.push([s[i], s[j]])
    }
  }
  return out
}

/** -> problems if the mods were made for different firmware. */
export function sameTarget(mods: AnyMod[]): string[] {
  const ts = new Set(mods.map(m => m.dev.key + '\0' + m.rel.version))
  if (ts.size > 1) return ['the mods are for different firmware: ' + mods.map(m => `${m.label()} (${m.dev.name} ${m.rel.version})`).join(', ')]
  return []
}

const pyCount = <T>(xs: T[], x: T) => xs.filter(y => y === x).length
const sortedStr = (xs: Iterable<string>) => [...xs].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))

/** The checks both formats share. `spans`: [lo, hi, mod, what] of image bytes each mod changes or claims. */
export function commonChecks(mods: AnyMod[], image: Uint8Array, spans: Span<AnyMod>[]): string[] {
  const bad = sameTarget(mods)
  const ids = mods.map(m => m.id)
  for (const i of sortedStr(new Set(ids))) if (pyCount(ids, i) > 1) bad.push(`mod ${i} is given ${pyCount(ids, i)} times`)
  for (const m of mods) {
    for (const r of m.requires) if (!ids.includes(r)) bad.push(`${m.label()} requires ${r}`)
    for (const c of m.conflicts) if (ids.includes(c)) bad.push(`${m.label()} conflicts with ${c}`)
  }
  for (const [a, b] of overlaps(spans)) {
    if (a[2] === b[2] && a[3] === b[3]) continue
    bad.push(`${a[2]!.label()} ${a[3]} and ${b[2]!.label()} ${b[3]} overlap (${hex8(b[0])}-${hex8(Math.min(a[1], b[1]))})`)
  }
  const owner = new Map<string, AnyMod>()
  for (const m of mods) {
    for (const nm of m.names) {
      if (owner.has(nm) && owner.get(nm) !== m) bad.push(`${owner.get(nm)!.label()} and ${m.label()} both claim ${nm}`)
      owner.set(nm, m)
    }
  }
  if (bad.length && bad[0].startsWith('the mods are for different firmware')) return bad
  const dev = mods[0].dev
  for (const m of mods) {
    for (const s of m.sites) {
      for (const [lo, hi, why] of dev.protected) {
        if (s.addr < hi && lo < s.addr + s.len)
          bad.push(`${m.label()} site ${hex8(s.addr)} is inside ${hex8(lo)}-${hex8(hi)}, ${why}: protected on the ${dev.name}`)
      }
    }
  }
  for (const m of mods) {
    for (const s of m.sites) {
      const o = s.addr - dev.mainLoad
      if (sha(image.subarray(o, o + s.len)) !== s.stock_sha256) {
        bad.push(`${m.label()} site ${hex8(s.addr)}: the stock bytes are not the ones it expects`)
      } else if (s.kind === 'code') {
        const [ok, note] = insnCheck(image, s.addr, s.len, dev)
        if (!ok) bad.push(`${m.label()} site ${hex8(s.addr)}: ${note}`)
      }
    }
  }
  return bad
}

const FOLLOW_ON = ['imports ', 'adds to table ', 'has .fast code']

/** The checker's lines, for a person: a mod that lacks a requirement shows that, not what follows from it; repeats
 * are merged with a count; "no .boot" says that core is not enabled. */
export function summarize(problems: string[], mods: AnyMod[]): string[] {
  const ids = new Set(mods.map(m => m.id))
  const lacking = new Set(mods.filter(m => m.requires.some(r => !ids.has(r))).map(m => m.label()))
  const out: string[] = [], count = new Map<string, number>()
  for (let x of problems) {
    if ([...lacking].some(lab => x.startsWith(lab + ' ') && FOLLOW_ON.some(f => x.includes(f)))) continue
    if (x.startsWith('exactly one mod must carry .boot') && x.endsWith('got none')) x = 'core is not enabled, and every other mod builds on it'
    if (!count.has(x)) out.push(x)
    count.set(x, (count.get(x) ?? 0) + 1)
  }
  return out.map(x => (count.get(x) === 1 ? x : `${x} (${count.get(x)} times)`))
}

/** The static conflict check for format-1 mods. -> problems. */
export function check(mods: Mod[], image: Uint8Array): string[] {
  const spans: Span<AnyMod>[] = []
  for (const m of mods) {
    for (const s of m.sites) spans.push([s.addr, s.addr + s.len, m, `site ${hex8(s.addr)}`])
    if (m.blob) spans.push([m.blob.load, m.blob.load + m.blob.len, m, 'blob'])
  }
  const bad = commonChecks(mods, image, spans)
  const regs: Span<AnyMod>[] = mods.flatMap(m => m.regions.map(g => [g.lo, g.hi, m, 'region ' + g.name] as Span<AnyMod>))
  for (const [a, b] of overlaps(regs))
    bad.push(`${a[2]!.label()} ${a[3]} and ${b[2]!.label()} ${b[3]} overlap (${hex8(b[0])}-${hex8(Math.min(a[1], b[1]))})`)
  const blobs = mods.filter(m => m.blob)
  if (blobs.length > 1) bad.push(`more than one whole build (${blobs.map(m => m.label()).join(', ')})`)
  for (const m of blobs) {
    const end = imageEnd(m.dev, m.rel)
    if (m.blob!.load !== end) bad.push(`${m.label()}: its blob loads at ${hex8(m.blob!.load)}, not the image end ${hex8(end)}`)
  }
  return bad
}

/** -> the mod's blob, its stock parts copied from `image`. */
export function blobBytes(mod: Mod, image: Uint8Array): Uint8Array {
  const out = partsBytes(mod.blob!.parts, image, mod.dev)
  if (sha(out) !== mod.blob!.sha256) throw new ModError(`${mod.label()}: the blob does not assemble to its sha256`)
  return out
}

/** Format-1 mods -> the patched main OS image. ModError with every problem the check finds. */
export function apply(mods: Mod[], image: Uint8Array): Uint8Array {
  const rel = mods[0].rel
  if (sha(image) !== rel.mainSha256) throw new ModError(`the stock main OS is not ${mods[0].dev.name} ${rel.version}`)
  const bad = summarize(check(mods, image), mods)
  if (bad.length) throw new ModError('the mods do not combine:\n  ' + bad.join('\n  '))
  const dev = mods[0].dev
  const img = image.slice()
  for (const m of mods) for (const s of m.sites) img.set(s.new, s.addr - dev.mainLoad)
  const blobs = mods.filter(m => m.blob).map(m => blobBytes(m, image))
  return blobs.length ? concat([img, ...blobs]) : img
}

export { PyFloat }
