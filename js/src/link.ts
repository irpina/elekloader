// SPDX-License-Identifier: GPL-3.0-or-later
// The linker: format-2 mods -> one patched main OS (docs/FORMAT.md). Ported from elekloader's link.py
// (GPL-2.0-or-later): the same checks in the same order, the same layout, and the same bytes.
//
// A format-2 mod is a relocatable object in JSON: its sections (.boot for core only, .run, .fast, .bss), the symbols
// it defines and exports, what it imports (some weakly), relocations, sites with relocations of their own, the tables
// it declares and the entries it adds to other mods' tables, and its resources. A relocation target is "sym:NAME"
// (its own symbol, else another mod's export, else, if the import is weak, core_zero), "sec:NAME" or "abs".
import { concat, sha } from './bytes.ts'
import { type Device, type Release, imageEnd, linkable } from './devices.ts'
import {
  type AnyMod, type Part, type Region, type Site, type Span, COMMON, ModError, commonChecks, formatOf, get, hexBytes, insnCheck,
  int, isDict, iter, overlaps, parseParts, parseResources, parseSites, partsBytes, partsLen, pyEq, resolveTarget, summarize, unpack,
} from './elemod.ts'
import { PCREL, decodeColdFire, readerAt } from './isa/coldfire.ts'
import { AttributeError, KeyError, PyException, ValueError, hex8, pyType, repr, str } from './py.ts'

/** Python's struct.error. */
export class StructError extends PyException {}

export const FORMAT2 = 2
const SECTIONS = ['.boot', '.run', '.fast', '.bss']
const RTYPES = ['abs32', 'pc32', 'pc16']
const FAST_ENTRY = 16                       // a .fast copy entry: src, dst, len, 0
const MAX_ALIGN = 4096                      // a section's alignment: a power of two up to this
const LINKER_SYMS = new Set(['__run_load', '__run_start', '__run_words', '__bss_start', '__bss_end', '__bss_words'])

const align = (v: number, a: number) => Math.ceil(v / a) * a

/** d.items() of a JSON dict, or Python's AttributeError. */
function items(d: unknown): [string, any][] {
  if (!isDict(d)) throw new AttributeError(`'${pyType(d)}' object has no attribute 'items'`)
  return Object.entries(d)
}

type Sec = { align: number; parts?: Part[]; len?: number; size?: number }
export type Contribution = { to: string; order: number; data: Uint8Array; relocs: [number, string, string, number][]; claims: [number, number][]; i: number }

/** A loaded, validated format-2 mod. */
export class Mod2 implements AnyMod {
  readonly format = 2
  doc: Record<string, any>
  name: string
  sha256: string | null
  id: string
  version: string
  dev: Device
  rel: Release
  sections: Map<string, Sec>
  symbols: Map<string, [string, number]>
  exports: string[]
  imports: string[]
  weak: Set<string>
  relocs: [string, number, string, string, number][]
  sites: Site[]
  collections: Map<string, number>
  contribute: Contribution[]
  copied: [number, number, number][]
  regions: Region[]
  names: string[]
  requires: string[]
  conflicts: string[]
  blob = null

  constructor(doc: Record<string, any>, name = '<mod>', raw: Uint8Array | null = null) {
    this.doc = doc
    this.name = name
    this.sha256 = raw ? sha(raw) : null
    if (!pyEq(formatOf(doc), FORMAT2)) throw new ModError(`${name}: not a format-2 .elemod file`)
    const more = new Set(['sections', 'symbols', 'exports', 'imports', 'weak', 'relocs', 'collections', 'contribute', 'copied'])
    const extra = Object.keys(doc).filter(k => !COMMON.has(k) && !more.has(k)).sort()
    if (extra.length) throw new ModError(`${name}: unknown fields ${repr(extra)}`)
    for (const k of ['id', 'version', 'target', 'sections']) if (!(k in doc)) throw new ModError(`${name}: no "${k}"`)
    this.id = str(doc.id)
    this.version = str(doc.version)
    ;[this.dev, this.rel] = resolveTarget(doc, name)
    this.sections = new Map()
    for (const [sec, d] of items(doc.sections)) {
      if (!SECTIONS.includes(sec)) throw new ModError(`${name}: unknown section ${sec}`)
      const al = int(get(d, 'align', 4), name)
      if (al < 1 || al & (al - 1) || al > MAX_ALIGN) throw new ModError(`${name} ${sec}: alignment ${al} (a power of two up to ${MAX_ALIGN})`)
      if (sec === '.bss') {
        if (!('size' in d)) throw new KeyError(repr('size'))
        this.sections.set(sec, { align: al, size: int(d.size, name) })
        continue
      }
      const parts = parseParts(get(d, 'parts', []), name + ' ' + sec, this.dev, this.rel)
      const n = partsLen(parts)
      if (n !== int(get(d, 'len', n), name)) throw new ModError(`${name} ${sec}: parts make ${n} bytes, not ${str(get(d, 'len'))}`)
      this.sections.set(sec, { align: al, parts, len: n })
    }
    this.symbols = new Map()
    for (const [nm, v] of items(get(doc, 'symbols', {}))) {
      if (!Array.isArray(v) || v.length !== 2) throw new ModError(`${name}: symbol ${nm}`)
      if (v[0] !== 'abs' && !this.sections.has(v[0])) throw new ModError(`${name}: symbol ${nm} in a section it lacks (${str(v[0])})`)
      this.symbols.set(nm, [v[0], int(v[1], name)])
    }
    this.exports = iter(get(doc, 'exports', [])).map(x => str(x))
    for (const x of this.exports) if (!this.symbols.has(x)) throw new ModError(`${name}: exports ${x}, which it does not define`)
    this.imports = iter(get(doc, 'imports', [])).map(x => str(x))
    this.weak = new Set(iter(get(doc, 'weak', [])).map(x => str(x)))
    if (![...this.weak].every(w => this.imports.includes(w))) throw new ModError(`${name}: a weak name it does not import`)
    this.relocs = []
    for (const r of iter(get(doc, 'relocs', []))) {
      const [sec, off0, typ, tgt, add] = unpack(r, 5)
      const off = int(off0, name)
      this.relocOk(sec, off, typ, tgt)
      this.relocs.push([sec as string, off, typ as string, tgt as string, int(add, name)])
    }
    this.sites = parseSites(doc, name, this.dev, this.rel, true)
    this.collections = new Map()
    for (const [c, d] of items(get(doc, 'collections', {}))) {
      const e = int(get(d, 'entry'), name)
      if (e <= 0 || e % 4) throw new ModError(`${name}: table ${c} entry size ${e}`)
      this.collections.set(c, e)
    }
    this.contribute = []
    iter(get(doc, 'contribute', [])).forEach((c, i) => {
      const what = `${name} contribution ${i}`
      const data = hexBytes(get(c, 'data'), what)
      const rel: [number, string, string, number][] = []
      for (const r of iter(get(c, 'relocs', []))) {
        const [off0, typ, tgt, add] = unpack(r, 4)
        const off = int(off0, what)
        if (!RTYPES.includes(typ as string) || off < 0 || off + 4 > data.length) throw new ModError(`${what}: bad relocation ${repr(r)}`)
        rel.push([off, typ as string, tgt as string, int(add, what)])
      }
      const claims = iter(get(c, 'claims', [])).map(ab => {
        const [a, b] = unpack(ab, 2)
        return [int(a, what), int(b, what)] as [number, number]
      })
      if (!isDict(c) || !('to' in c)) throw new KeyError(repr('to'))
      this.contribute.push({ to: str(c.to), order: int(get(c, 'order', 50), what), data, relocs: rel, claims, i })
    })
    this.copied = iter(get(doc, 'copied', [])).map(c => {
      for (const k of ['lo', 'hi', 'to']) if (!isDict(c) || !(k in c)) throw new KeyError(repr(k))
      return [int((c as any).lo, name), int((c as any).hi, name), int((c as any).to, name)] as [number, number, number]
    })
    ;[this.regions, this.names] = parseResources(doc, name, this.dev)
    this.requires = iter(get(doc, 'requires', [])).map(x => str(x))
    this.conflicts = iter(get(doc, 'conflicts', [])).map(x => str(x))
  }

  private relocOk(sec: unknown, off: number, typ: unknown, tgt: unknown) {
    if (typeof sec !== 'string' || !this.sections.has(sec) || sec === '.bss') throw new ModError(`${this.name}: relocation in ${str(sec)}`)
    if (!RTYPES.includes(typ as string)) throw new ModError(`${this.name}: relocation type ${str(typ)}`)
    if (off < 0 || off + (typ === 'pc16' ? 2 : 4) > this.sections.get(sec)!.len!) throw new ModError(`${this.name}: relocation at ${sec}+${off} is outside it`)
    if (tgt !== 'abs' && typeof tgt !== 'string') throw new AttributeError(`'${pyType(tgt)}' object has no attribute 'startswith'`)
    if (!(tgt === 'abs' || tgt.startsWith('sym:') || tgt.startsWith('sec:'))) throw new ModError(`${this.name}: relocation target ${repr(tgt)}`)
  }

  label(): string { return `${this.id} ${this.version}` }

  size(sec: string): number {
    const d = this.sections.get(sec)
    if (!d) return 0
    return sec === '.bss' ? d.size! : d.len!
  }
}

// ---- checks ----

/** Static checks that need no layout. -> problems. */
export function check(mods: Mod2[], image: Uint8Array): string[] {
  const spans: Span<AnyMod>[] = []
  for (const m of mods) {
    for (const s of m.sites) spans.push([s.addr, s.addr + s.len, m, `site ${hex8(s.addr)}`])
    for (const c of m.contribute) for (const [a, b] of c.claims) spans.push([a, b, m, `${c.to} entry (claims ${hex8(a)}-${hex8(b)})`])
  }
  const bad = commonChecks(mods, image, spans)
  if (bad.length && bad[0].startsWith('the mods are for different firmware')) return bad
  const dev = mods[0].dev
  if (!linkable(dev)) return [`the ${dev.name} has no linkable (format-2) mods yet: only whole builds (format 1) can be used on it`]
  const cores = mods.filter(m => m.sections.has('.boot'))
  if (cores.length !== 1) bad.unshift(`exactly one mod must carry .boot (core); got ${cores.length ? repr(cores.map(m => m.label())) : 'none'}`)
  const owner = new Map<string, Mod2>()
  for (const m of mods) {
    for (const x of m.exports) {
      if (owner.has(x)) bad.push(`${owner.get(x)!.label()} and ${m.label()} both export ${x}`)
      owner.set(x, m)
    }
  }
  const tables = new Map<string, [Mod2, number]>()
  for (const m of mods) {
    for (const [c, e] of m.collections) {
      if (tables.has(c)) bad.push(`${tables.get(c)![0].label()} and ${m.label()} both declare the table ${c}`)
      if (owner.has(c)) bad.push(`table ${c} has the name of a symbol ${owner.get(c)!.label()} exports`)
      tables.set(c, [m, e])
    }
  }
  for (const m of mods) {
    for (const x of m.imports) {
      if (owner.has(x) || tables.has(x) || LINKER_SYMS.has(x) || m.weak.has(x) || (x.endsWith('_n') && tables.has(x.slice(0, -2)))) continue
      bad.push(`${m.label()} imports ${x}, which no given mod exports`)
    }
    for (const c of m.contribute) {
      if (!tables.has(c.to)) bad.push(`${m.label()} adds to table ${c.to}, which no given mod declares`)
      else if (c.data.length % tables.get(c.to)![1]) bad.push(`${m.label()}: an entry for ${c.to} is not ${tables.get(c.to)![1]} bytes`)
    }
    if (m.size('.fast') && (!dev.fastTable || !tables.has(dev.fastTable)))
      bad.push(`${m.label()} has .fast code, which needs the mod that declares ${dev.fastTable || 'a .fast copy table'}`)
  }
  const regs: Span<AnyMod>[] = mods.flatMap(m => m.regions.map(g => [g.lo, g.hi, m, 'region ' + g.name] as Span<AnyMod>))
  if (dev.sramCode[1] > dev.sramCode[0]) regs.push([dev.sramCode[0], dev.sramCode[1], null, 'the .fast area'])
  for (const [a, b] of overlaps(regs)) {
    const la = a[2] ? a[2].label() : 'the linker', lb = b[2] ? b[2].label() : 'the linker'
    bad.push(`${la} ${a[3]} and ${lb} ${b[3]} overlap`)
  }
  return bad
}

/** Sites of other mods inside a copied block: no PC-relative operand, no relative branch, whole instructions in the
 * patched image. */
function copiedRules(mods: Mod2[], patched: Uint8Array, dev: Device): string[] {
  const bad: string[] = []
  const read = readerAt(patched, dev.mainLoad)
  for (const owner of mods) {
    for (const [lo, hi] of owner.copied) {
      for (const m of mods) {
        if (m === owner) continue
        for (const s of m.sites) {
          if (!((lo <= s.addr && s.addr < hi) || (lo < s.addr + s.len && s.addr + s.len <= hi))) continue
          if (s.kind !== 'code') {
            bad.push(`${m.label()} site ${hex8(s.addr)}: data inside ${owner.label()}'s copied block`)
            continue
          }
          let a = s.addr
          while (a < s.addr + s.len) {
            const ins = decodeColdFire(read(a), a)
            if (ins.flags & PCREL || ins.flow === 'bra' || ins.flow === 'bcc' || ins.flow === 'bsr')
              bad.push(`${m.label()} site ${hex8(s.addr)}: ${ins.op} at ${hex8(a)} is PC-relative, inside ${owner.label()}'s copied block`)
            a += ins.length
          }
          if (a !== s.addr + s.len) bad.push(`${m.label()} site ${hex8(s.addr)}: its new bytes are not whole instructions`)
        }
      }
    }
  }
  return bad
}

// ---- the link ----

export type Layout = {
  boot: [number, number]; run_load: number; ddr: [number, number]; bss: [number, number]; fast: [number, number]
  blob_len: number; sections: Record<string, number>; ddr_spare: number; fast_spare: number; ddr_size: number; fast_size: number
}

export type Linked = {
  image: Uint8Array
  order: string[]
  map: Map<string, number>                      // name -> address, in link.py's order
  tables: Map<string, [number, number, number]> // name -> [address, count, entry size]
  layout: Layout
}

/** The patched main OS, its map, tables and layout. Throws ModError. */
export function link(mods: Mod2[], image: Uint8Array): Linked {
  if (!mods.length) throw new ModError('no mods')
  const dev = mods[0].dev, rel = mods[0].rel
  if (sha(image) !== rel.mainSha256) throw new ModError(`the stock main OS is not ${dev.name} ${rel.version}`)
  const problems = summarize(check(mods, image), mods)
  if (problems.length) throw new ModError('the mods do not combine:\n  ' + problems.join('\n  '))
  const end = imageEnd(dev, rel)
  const [ddrBase, ddrEnd] = dev.ddr
  const [fastBase, fastEnd] = dev.sramCode
  const core = mods.filter(m => m.sections.has('.boot'))[0]
  const order = [core, ...mods.filter(m => m !== core).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))]
  const tables = new Map<string, [Mod2, number]>()
  for (const m of order) for (const [c, e] of m.collections) tables.set(c, [m, e])

  const entries = new Map<string, [number, string, number, Mod2, Contribution][]>()
  for (const c of tables.keys()) entries.set(c, [])
  for (const m of order) for (const c of m.contribute) entries.get(c.to)!.push([c.order, m.id, c.i, m, c])
  const fastMods = order.filter(m => m.size('.fast'))
  for (const list of entries.values()) {
    list.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) || a[2] - b[2])
  }
  const tableLen = (c: string) => {
    let n = entries.get(c)!.reduce((k, e) => k + e[4].data.length, 0)
    if (c === dev.fastTable) n += FAST_ENTRY * fastMods.length
    return n + tables.get(c)![1]               // the zero entry
  }

  // layout
  const base = new Map<string, number>()       // `${mod id}\0${section}` -> address
  const key = (id: string, sec: string) => id + '\0' + sec
  const bootLen = core.size('.boot')
  base.set(key(core.id, '.boot'), end)
  let at = ddrBase
  for (const m of order) {
    if (m.size('.run')) {
      at = align(at, Math.max(4, m.sections.get('.run')!.align))
      base.set(key(m.id, '.run'), at)
      at += m.size('.run')
    }
  }
  const tabAt = new Map<string, number>()
  for (const c of [...tables.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
    at = align(at, 4)
    tabAt.set(c, at)
    at += tableLen(c)
  }
  let fastAt = fastBase
  const fload = new Map<string, number>()
  for (const m of fastMods) {
    fastAt = align(fastAt, Math.max(4, m.sections.get('.fast')!.align))
    base.set(key(m.id, '.fast'), fastAt)
    at = align(at, 4)
    fload.set(m.id, at)
    const n = align(m.size('.fast'), 4)
    fastAt += n
    at += n
  }
  const runEnd = align(at, 4)
  at = runEnd
  for (const m of order) {
    if (m.size('.bss')) {
      at = align(at, Math.max(4, m.sections.get('.bss')!.align))
      base.set(key(m.id, '.bss'), at)
      at += m.size('.bss')
    }
  }
  const bssEnd = align(at, 4)
  if (bssEnd > ddrEnd) throw new ModError(`the mods need RAM to ${hex8(bssEnd)}, past ${hex8(ddrEnd)} (${bssEnd - ddrEnd} bytes over)`)
  if (fastAt > fastEnd) throw new ModError(`.fast code needs SRAM to ${hex8(fastAt)}, past ${hex8(fastEnd)}`)
  const runLoad = align(end + bootLen, 16)

  // symbols
  const addr = new Map<string, number>()       // `${mod id}\0${name}` -> address
  const glob = new Map<string, number>()
  for (const m of order) {
    for (const [nm, [sec, off]] of m.symbols) {
      let v = off
      if (sec !== 'abs') {
        const b = base.get(key(m.id, sec))
        if (b === undefined) throw new KeyError(`(${repr(m.id)}, ${repr(sec)})`)
        v = b + off
      }
      addr.set(key(m.id, nm), v)
      if (m.exports.includes(nm)) glob.set(nm, v)
    }
  }
  for (const c of tables.keys()) {
    glob.set(c, tabAt.get(c)!)
    glob.set(c + '_n', Math.floor(tableLen(c) / tables.get(c)![1]) - 1)
  }
  for (const [k, v] of [['__run_load', runLoad], ['__run_start', ddrBase], ['__run_words', Math.floor((runEnd - ddrBase) / 4)],
    ['__bss_start', runEnd], ['__bss_end', bssEnd], ['__bss_words', Math.floor((bssEnd - runEnd) / 4)]] as [string, number][]) glob.set(k, v)
  const zero = glob.get('core_zero')

  const resolve = (m: Mod2, tgt: string, where: string): number => {
    if (tgt === 'abs') return 0
    const colon = tgt.indexOf(':')
    if (colon < 0) throw new ValueError('not enough values to unpack (expected 2, got 1)')
    const kind = tgt.slice(0, colon), nm = tgt.slice(colon + 1)
    if (kind === 'sec') {
      const b = base.get(key(m.id, nm))
      if (b === undefined) throw new ModError(`${m.label()}: ${where} refers to its empty section ${nm}`)
      return b
    }
    if (addr.has(key(m.id, nm)) && m.symbols.has(nm)) return addr.get(key(m.id, nm))!
    if (glob.has(nm)) return glob.get(nm)!
    if (m.weak.has(nm) && zero !== undefined) return zero
    throw new ModError(`${m.label()}: ${where} refers to ${nm}, which nothing defines`)
  }

  const put = (buf: Uint8Array, off: number, typ: string, value: number, p: number, where: string) => {
    const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
    if (typ === 'abs32') {
      v.setUint32(off, ((value % 2 ** 32) + 2 ** 32) % 2 ** 32)
    } else if (typ === 'pc32') {
      const d = value - p
      if (d < -(2 ** 31) || d >= 2 ** 31) throw new StructError("'i' format requires -2147483648 <= number <= 2147483647")
      v.setInt32(off, d)
    } else {
      const d = value - p
      if (!(d >= -0x8000 && d < 0x8000)) throw new ModError(`${where}: a 16-bit PC-relative reference spans ${d} bytes`)
      v.setInt16(off, d)
    }
  }

  const content = new Map<string, Uint8Array>()
  for (const m of order) {
    for (const sec of ['.boot', '.run', '.fast']) {
      if (m.size(sec)) content.set(key(m.id, sec), partsBytes(m.sections.get(sec)!.parts!, image, dev).slice())
    }
    for (const [sec, off, typ, tgt, add] of m.relocs) {
      const where = `${sec}+0x${off.toString(16)}`
      put(content.get(key(m.id, sec))!, off, typ, resolve(m, tgt, where) + add, base.get(key(m.id, sec))! + off, where)
    }
  }
  const tab = new Map<string, Uint8Array>()
  for (const c of tables.keys()) {
    const parts: Uint8Array[] = []
    let len = 0
    for (const [, , , m, e] of entries.get(c)!) {
      const d = e.data.slice()
      for (const [off, typ, tgt, add] of e.relocs) {
        const where = `an entry of ${c}`
        put(d, off, typ, resolve(m, tgt, where) + add, tabAt.get(c)! + len + off, where)
      }
      parts.push(d)
      len += d.length
    }
    if (c === dev.fastTable) {
      for (const m of fastMods) {
        const e = new Uint8Array(16), v = new DataView(e.buffer)
        v.setUint32(0, fload.get(m.id)!)
        v.setUint32(4, base.get(key(m.id, '.fast'))!)
        v.setUint32(8, align(m.size('.fast'), 4))
        parts.push(e)
      }
    }
    parts.push(new Uint8Array(tables.get(c)![1]))
    tab.set(c, concat(parts))
  }
  const ddr = new Uint8Array(runEnd - ddrBase)
  for (const m of order) {
    if (m.size('.run')) ddr.set(content.get(key(m.id, '.run'))!, base.get(key(m.id, '.run'))! - ddrBase)
    if (fload.has(m.id)) ddr.set(content.get(key(m.id, '.fast'))!, fload.get(m.id)! - ddrBase)
  }
  for (const c of tables.keys()) ddr.set(tab.get(c)!, tabAt.get(c)! - ddrBase)
  const boot = content.get(key(core.id, '.boot'))
  if (!boot) throw new KeyError(`(${repr(core.id)}, '.boot')`)
  const blob = concat([boot, new Uint8Array(runLoad - end - boot.length), ddr])
  const img = new Uint8Array(image.length + blob.length)
  img.set(image)
  for (const m of order) {
    for (const s of m.sites) {
      const nw = s.new.slice()
      for (const [off, typ, tgt, add] of s.relocs) {
        const where = `site ${hex8(s.addr)}`
        put(nw, off, typ, resolve(m, tgt, where) + add, s.addr + off, where)
      }
      img.set(nw, s.addr - dev.mainLoad)
    }
  }
  img.set(blob, image.length)
  const bad = copiedRules(order, img, dev)
  for (const m of order) {
    for (const s of m.sites) {
      if (s.kind === 'code') {
        const [ok, note] = insnCheck(img, s.addr, s.len, dev, 0)
        if (!ok) bad.push(`${m.label()} site ${hex8(s.addr)} after relocation: ${note}`)
      }
    }
  }
  if (bad.length) throw new ModError('the linked mods break a rule:\n  ' + bad.join('\n  '))

  const map = new Map<string, number>()
  for (const [k, v] of addr) map.set(k.replace('\0', ':'), v)
  for (const [k, v] of glob) map.set(k, v)
  const uniq = new Map<string, Set<number>>()
  for (const [k, v] of addr) {
    const nm = k.slice(k.indexOf('\0') + 1)
    if (!uniq.has(nm)) uniq.set(nm, new Set())
    uniq.get(nm)!.add(v)
  }
  for (const [nm, vs] of uniq) if (vs.size === 1 && !map.has(nm)) map.set(nm, [...vs][0])
  const outTables = new Map<string, [number, number, number]>()
  for (const c of tables.keys()) outTables.set(c, [tabAt.get(c)!, Math.floor(tableLen(c) / tables.get(c)![1]) - 1, tables.get(c)![1]])
  const sections: Record<string, number> = {}
  for (const [k, v] of [...base].map((kv, i) => [kv, i] as const).sort((a, b) => a[0][1] - b[0][1] || a[1] - b[1]).map(([kv]) => kv))
    sections[k.replace('\0', ' ')] = v
  const layout: Layout = {
    boot: [end, end + bootLen], run_load: runLoad, ddr: [ddrBase, runEnd], bss: [runEnd, bssEnd], fast: [fastBase, fastAt],
    blob_len: blob.length, sections, ddr_spare: ddrEnd - bssEnd, fast_spare: fastEnd - fastAt, ddr_size: ddrEnd - ddrBase,
    fast_size: fastEnd - fastBase,
  }
  return { image: img, order: order.map(m => m.label()), map, tables: outTables, layout }
}

