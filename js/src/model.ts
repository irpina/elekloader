// SPDX-License-Identifier: GPL-3.0-or-later
// The mod manager's logic without a window: elekloader's gui.LoaderModel (GPL-2.0-or-later), ported, on an
// in-memory file store instead of folders. The stock file, the library (the user's mods, and folders listed beside
// it, such as the site's cores), describe(), the live check, build(), with_requirements and suggested_name.
import { sha } from './bytes.ts'
import type { Device, Release } from './devices.ts'
import { type AnyMod, EXTS, ModError, get } from './elemod.ts'
import * as formats from './formats.ts'
import { type Mod2, link } from './link.ts'
import { apply, type Mod } from './elemod.ts'
import { basename, build as patchBuild, dirname, loadAny, save } from './patch.ts'
import { PyException, truthy } from './py.ts'

/** Python's OSError: a file that is not there. */
export class OSError_ extends PyException {}

/** Files by absolute path: the folders the Python version reads, in memory. */
export class Store {
  private files = new Map<string, Uint8Array>()
  private versions = new Map<string, number>()
  private counter = 0
  write(path: string, data: Uint8Array) {
    this.files.set(path, data)
    this.versions.set(path, ++this.counter)
  }
  read(path: string): Uint8Array {
    const d = this.files.get(path)
    if (!d) throw new OSError_(`[Errno 2] No such file or directory: '${path}'`)
    return d
  }
  exists(path: string): boolean { return this.files.has(path) }
  remove(path: string) { this.files.delete(path); this.versions.delete(path) }
  /** The paths directly in `dir`, sorted. */
  list(dir: string): string[] { return [...this.files.keys()].filter(p => dirname(p) === dir).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)) }
  /** What gui.LoaderModel.mod keys its cache by (path, mtime, size): a write counter here. */
  version(path: string): number { return this.versions.get(path) ?? 0 }
}

/** elemod.mod_files: the mod files in a folder, sorted (.elemod, and legacy .dtmod). */
export function modFiles(store: Store, folder: string): string[] {
  const out: string[] = []
  for (const ext of EXTS) out.push(...store.list(folder).filter(p => basename(p).endsWith(ext)))
  return out.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}

export type Desc = Record<string, any>
export type Stock = Record<string, any>

/** `enabled` plus `path`, plus the mods it requires (and theirs) that are listed and made for the stock firmware,
 * when none enabled already provides them. Of several files with the id, the last (by file name) is taken. */
export function withRequirements(descs: Map<string, Desc>, enabled: Iterable<string>, path: string): Set<string> {
  const out = new Set([...enabled, path])
  const todo = [path]
  while (todo.length) {
    const d = descs.get(todo.pop()!) ?? {}
    for (const rid of d.requires ?? []) {
      if ([...out].some(p => descs.get(p)?.id === rid)) continue
      const cands = [...descs].filter(([, x]) => x.id === rid && x.fits && !('error' in x)).map(([p]) => p)
        .map((p, i) => [p, i] as const).sort((a, b) => (basename(a[0]) < basename(b[0]) ? -1 : basename(a[0]) > basename(b[0]) ? 1 : a[1] - b[1]))
        .map(([p]) => p)
      if (cands.length) {
        out.add(cands[cands.length - 1])
        todo.push(cands[cands.length - 1])
      }
    }
  }
  return out
}

export function suggestedName(descs: Desc[], version: string | null): string {
  const ids = descs.map(d => d.id).filter(i => i !== null && i !== undefined && i !== 'core').sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  return `custom-${version || 'x'}${ids.length ? '-' + ids.join('+') : ''}.syx`
}

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())

export class LoaderModel {
  store: Store
  library: string
  also: string[]
  stock: Stock = { path: null, ok: false, error: 'no stock firmware chosen' }   // set_stock(None), as LoaderModel starts
  img: Uint8Array | null = null
  dev: Device | null = null
  rel: Release | null = null
  private mods = new Map<string, [number, AnyMod]>()

  constructor(store: Store, library: string, also: string[] = []) {
    this.store = store
    this.library = library
    this.also = also
  }

  /** Choose the stock firmware: known by its hash, or refused. */
  async setStock(path: string | null): Promise<Stock> {
    const info: Stock = { path, ok: false }
    this.img = this.dev = this.rel = null
    if (!path) {
      info.error = 'no stock firmware chosen'
    } else {
      try {
        const [s, dev, rel] = await formats.load(this.store.read(path))
        info.sha256 = s.sha256
        const img = formats.mainImage(s, dev)
        if (sha(img) === rel.mainSha256) {
          this.img = img
          this.dev = dev
          this.rel = rel
          Object.assign(info, { ok: true, device: dev.name, os: rel.version })
        } else {
          info.error = 'its main OS is not the known image'
        }
      } catch (e) {                          // a missing, foreign or unknown file: say so
        info.error = (e as Error).message
      }
    }
    this.stock = info
    return info
  }

  files(): string[] {
    const out = modFiles(this.store, this.library)
    const seen = new Set(out.map(basename))
    for (const d of this.also) {
      for (const p of modFiles(this.store, d)) {
        if (!seen.has(basename(p))) {
          out.push(p)
          seen.add(basename(p))
        }
      }
    }
    return out
  }

  mod(path: string): AnyMod {
    const v = this.store.version(path)
    const hit = this.mods.get(path)
    if (hit && hit[0] === v) return hit[1]
    const m = loadAny({ path, data: this.store.read(path) })
    this.mods.set(path, [v, m])
    return m
  }

  forget(path: string) { this.mods.delete(path) }

  describe(path: string): Desc {
    const base = { path, file: basename(path) }
    let m: AnyMod
    try {
      m = this.mod(path)
    } catch (e) {
      if (e instanceof ModError || e instanceof OSError_) return { ...base, error: e.message, id: basename(path), label: base.file }
      throw e
    }
    const cat = get(m.doc, 'category')
    const d: Desc = {
      ...base, id: m.id, version: m.version, label: m.label(), for_device: m.dev.key,
      for_label: `${m.dev.name} ${m.rel.version}`,
      fits: this.dev !== null && m.dev.key === this.dev.key && m.rel === this.rel,
      title: get(m.doc, 'title', m.id), description: get(m.doc, 'description', ''),
      category: truthy(cat) ? cat : (m.format !== 2 ? 'Whole build' : ''),
      author: get(m.doc, 'author', ''), license: get(m.doc, 'license', ''), sha256: m.sha256,
      requires: [...m.requires], conflicts: [...m.conflicts], names: [...m.names],
    }
    d.sites = m.sites.map(s => {
      let tgt = ''
      for (const r of s.relocs) tgt = r[2].startsWith('sym:') ? r[2].slice(4) : r[2]
      return [s.addr, s.len, s.kind, tgt]
    })
    if (m.format === 2) {
      const m2 = m as Mod2
      d.format = 2
      d.ram = m2.size('.run') + m2.size('.bss')
      d.fast = m2.size('.fast')
      d.events = m2.contribute.filter(c => c.to.startsWith('ev_')).map(c => {
        if (!c.relocs.length) throw new Error('IndexError: list index out of range')
        return [c.to, c.order, c.relocs[0][2].slice(4)]
      }).sort((a, b) => cmpTuple(a, b))
      d.adds_to = [...new Set(m2.contribute.filter(c => !c.to.startsWith('ev_')).map(c => c.to))].sort(cmpStr)
      d.tables = [...m2.collections.keys()].sort(cmpStr)
      d.regions = m2.regions.map(g => [g.name, g.lo, g.hi])
    } else {
      d.format = 1
      d.ram = m.blob ? m.blob.len : 0
      d.fast = 0
      d.events = []
      d.adds_to = []
      d.tables = []
      d.regions = []
    }
    return d
  }

  /** -> {ok, headline, problems, status: {path: [state, text]}, ...}. */
  check(paths: string[]): Record<string, any> {
    const descs = new Map(paths.map(p => [p, this.describe(p)]))
    const status: Record<string, [string, string]> = {}
    if (!this.stock.ok) {
      return { ok: false, headline: 'Choose your stock firmware first', problems: [this.stock.error ?? 'no stock firmware'], status }
    }
    const other = paths.filter(p => !descs.get(p)!.fits)
    if (other.length) {
      for (const p of other) status[p] = ['warn', 'For ' + (descs.get(p)!.for_label ?? '?')]
      return {
        ok: false, headline: 'Made for other firmware', status,
        problems: other.map(p => `${descs.get(p)!.label} is made for ${descs.get(p)!.for_label ?? '?'}; your stock firmware is ${this.dev!.name} ${this.rel!.version}`),
      }
    }
    if (!paths.length) return { ok: false, headline: 'No mods enabled', problems: [], status, empty: true }
    const t = now()
    let mods: AnyMod[]
    let L
    try {
      mods = paths.map(p => this.mod(p))
      const v2 = mods.filter(m => m.format === 2)
      if (v2.length && v2.length !== mods.length) {
        const whole = paths.filter(p => this.mod(p).format !== 2).map(p => descs.get(p)!.label)
        throw new ModError(`x:\n  ${whole.join(', ')} is a whole build: it cannot be combined with separate mods`)
      }
      if (!v2.length) {
        const img = apply(mods as Mod[], this.img!)
        for (const p of paths) status[p] = ['ok', 'Enabled']
        return {
          ok: true, format: 1, ms: Math.round(now() - t), order: mods.map(m => m.label()), status,
          blob: img.length - this.img!.length, sites: mods.reduce((n, m) => n + m.sites.length, 0),
        }
      }
      L = link(mods as Mod2[], this.img!)
    } catch (e) {
      if (!(e instanceof ModError) && !(e instanceof OSError_)) throw e
      const lines0 = e.message.split('\n').slice(1).map(x => x.trim())
      const lines = lines0.length ? lines0 : [e.message]
      for (const p of paths) {
        const d = descs.get(p)!
        const mine = lines.filter(x => x.includes(d.label) || x.startsWith(d.id + ' '))
        const needs = (d.requires ?? []).filter((r: string) => !paths.some(q => descs.get(q)!.id === r))
        if (needs.length) status[p] = ['warn', 'Needs ' + needs.join(', ')]
        else if (mine.length) status[p] = ['bad', 'Conflict']
        else status[p] = ['ok', 'Enabled']
      }
      return { ok: false, headline: 'Conflicts: the firmware cannot be built', problems: lines, status, ms: Math.round(now() - t) }
    }
    const order = new Map(L.order.map((lab, i) => [lab, i + 1]))
    for (const p of paths) status[p] = ['ok', 'Enabled']
    const lay = L.layout
    const loadOrder: Record<string, number | null> = {}
    for (const p of paths) loadOrder[p] = order.get(descs.get(p)!.label) ?? null
    return {
      ok: true, format: 2, ms: Math.round(now() - t), status, order: L.order, load_order: loadOrder,
      ram: [lay.bss[1] - lay.ddr[0], lay.ddr_size], fast: [lay.fast[1] - lay.fast[0], lay.fast_size],
      blob: lay.blob_len, sites: mods.reduce((n, m) => n + m.sites.length, 0),
    }
  }

  /** Build, verify and write outPath (+ .json, + .map.json) into the store. -> facts and the files. */
  async build(paths: string[], version: string | null, outPath: string, log: (line: string) => void = () => {}) {
    const [outputs, man] = await patchBuild({ path: this.stock.path, data: this.store.read(this.stock.path) },
      paths.map(p => ({ path: p, data: this.store.read(p) })), version || null, false, log)
    const files = save(outputs!, man, outPath)
    for (const f of files) this.store.write(f.path, f.data)
    const f = man.output
    return {
      path: outPath, files, sha256: f.sha256, bytes: f.bytes, version: man.version, flash_end: f.flash_end,
      headroom: f.flash_headroom, gap: f.main.inplace_min_gap ?? null, inplace: f.main.inplace ?? '',
      mods: man.mods.map((m: Record<string, string>) => m.id + ' ' + m.version), untouched: f.untouched, man,
    }
  }
}

const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

/** Python's tuple order, for tuples of strings and numbers. */
function cmpTuple(a: unknown[], b: unknown[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const x = a[i] as any, y = b[i] as any
    if (x < y) return -1
    if (x > y) return 1
  }
  return a.length - b.length
}

