// SPDX-License-Identifier: GPL-3.0-or-later
// The web page's way into the engine: the calls of elekloader's web/bridge.py (GPL-2.0-or-later), with the same
// names, arguments and results, so a page that ran the Python in Pyodide runs this instead unchanged. Files live in
// a Store under the same paths (/work/stock, /work/mods, /work/core, /work/out); nothing here reads anything else or
// talks to a network.
import { isAscii, sha } from './bytes.ts'
import { type Device, type Release, devices, linkable, supported } from './devices.ts'
import { EXTS, ModError } from './elemod.ts'
import * as formats from './formats.ts'
import { LoaderModel, OSError_, Store, suggestedName, withRequirements } from './model.ts'
import { PatchError, basename, dirname } from './patch.ts'
import { KeyError, PyFloat, ValueError, repr } from './py.ts'
import { VERSION } from './version.ts'

const WORK = '/work'
export const STOCK = WORK + '/stock', MODS = WORK + '/mods', CORE = WORK + '/core', OUT = WORK + '/out'

/** A file name from the page: its last part only. */
function fileName(name: unknown): string {
  const n = basename(String(name).replace(/\\/g, '/')).trim()
  if (n === '' || n === '.' || n === '..') throw new ValueError('no file name')
  return n
}

/** A result as the JSON the Python bridge returns: floats as numbers, Maps as objects. */
function plain(v: unknown): any {
  if (v instanceof PyFloat) return v.value
  if (v instanceof Uint8Array) return v
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [k, plain(x)]))
  if (Array.isArray(v)) return v.map(plain)
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, plain(x)]))
  return v
}

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())

export function device(d: Device, rel: Release | null = null) {
  return {
    key: d.key, name: d.name, releases: d.releases.map(r => r.version).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)),
    container: d.container, version_len: d.versionLen, exact_len: d.container === 'ele3', recovery: d.recovery,
    card_file: d.container === 'elek', linkable: linkable(d),
    // the window's default (gui.LoaderWindow.refresh_stock)
    default_version: d.container === 'ele3' ? '2.0a' : rel ? `${rel.version} ELEK` : '',
  }
}

export class Bridge {
  readonly store = new Store()
  // the user's mods are the library; the site's cores are listed beside them, as the apps list their built-in cores
  readonly model = new LoaderModel(this.store, MODS, [CORE])

  describe(path: string) {
    const d = this.model.describe(path)
    d.builtin = dirname(path) === CORE
    if (!('error' in d)) d.os = this.model.mod(path).rel.version     // the OS version it is made for
    return plain(d)
  }

  info() {
    return { version: VERSION, supported: supported(), devices: devices().map(d => device(d)), exts: [...EXTS] }
  }

  /** A core the site carries (core/index.json names it, with its sha256). */
  addCore(args: { name: string; sha256: string }, data: Uint8Array) {
    const path = CORE + '/' + fileName(args.name)
    if (sha(data) !== args.sha256) throw new ValueError(`${args.name} is not the file the site lists`)
    this.store.write(path, data)
    return this.describe(path)
  }

  /** The stock OS file: known by its hash, or refused (and not kept). */
  async setStock(args: { name: string }, data: Uint8Array) {
    const name = fileName(args.name)
    for (const p of this.store.list(STOCK)) this.store.remove(p)     // one stock file at a time
    const path = STOCK + '/' + name
    this.store.write(path, data)
    const t = now()
    const st: Record<string, any> = { ...(await this.model.setStock(path)), file: name, ms: Math.round(now() - t) }
    if (st.ok) {
      st.dev = device(this.model.dev!, this.model.rel)
    } else {
      this.store.remove(path)
      if (!String(st.error ?? '').includes('Supported:')) st.supported = supported()
    }
    return st
  }

  /** Add a mod to the library, as Install from file does: it must load. From the shop, it must also be the file
   * the shop lists (args.sha256). */
  addMod(args: { name: string; sha256?: string }, data: Uint8Array) {
    const name = fileName(args.name)
    if (!EXTS.some(x => name.toLowerCase().endsWith(x)))
      return { ok: false, file: name, error: `${name} is not a mod: the file name must end ${EXTS.join(' or ')}` }
    if (args.sha256 && sha(data) !== args.sha256) return { ok: false, file: name, error: `${name} is not the file the shop lists` }
    const path = MODS + '/' + name
    this.store.write(path, data)
    this.model.forget(path)            // a file replaced under the same name is read again
    try {
      this.model.mod(path)
    } catch (e) {
      if (e instanceof ModError || e instanceof OSError_) {
        this.store.remove(path)
        return { ok: false, file: name, error: e.message }
      }
      throw e
    }
    return { ok: true, mod: this.describe(path) }
  }

  removeMod(args: { path: string }) {
    if (dirname(args.path) !== MODS) throw new ValueError('only mods you added can be removed')
    this.store.remove(args.path)
    return { ok: true }
  }

  mods() { return this.model.files().map(p => this.describe(p)) }

  /** Tick a mod, with the mods it requires (as the window does). */
  tick(args: { enabled: string[]; path: string }) {
    const descs = new Map(this.model.files().map(p => [p, this.describe(p)]))
    return [...withRequirements(descs, args.enabled, args.path)].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  }

  check(args: { enabled: string[] }) {
    return plain(this.model.check([...args.enabled].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))))
  }

  /** What is wrong with the version field, or null (bridge.py _version_problem). */
  private versionProblem(v: string): string | null {
    const dev = this.model.dev!
    try {
      formats.checkVersion(dev, v)
    } catch (e) {
      if (e instanceof formats.FormatError) return `The OS version: ${e.message}.`
      throw e
    }
    if (v && !isAscii(v))
      return `The OS version: the version is ${dev.container === 'ele3' ? `exactly ${dev.versionLen}` : `1 to ${dev.versionLen}`} ASCII characters.`
    return null
  }

  /** The version field and a file name for the build. */
  version(args: { version: string; enabled: string[] }) {
    const bad = this.model.dev !== null ? this.versionProblem(args.version) : null
    const out: Record<string, any> = bad ? { ok: false, error: bad } : { ok: true }
    out.name = suggestedName(args.enabled.map(p => this.describe(p)), args.version)
    return out
  }

  /** Build, verify and save into /work/out, as the window does. -> the facts the window shows, every file written
   * (with its bytes), the log with its times. */
  async build(args: { enabled: string[]; version: string; name: string }, progress?: (line: string) => void) {
    if (!this.model.stock.ok) return { ok: false, error: 'Choose your stock firmware first' }
    const v = args.version
    if (v && !isAscii(v)) return { ok: false, error: this.versionProblem(v) }
    for (const p of this.store.list(OUT)) this.store.remove(p)
    let name = fileName(args.name)
    if (!name.toLowerCase().endsWith('.syx')) name += '.syx'
    const log: [number, string][] = []
    const t0 = now()
    const say = (line: string) => {
      log.push([Math.round((now() - t0) / 10) / 100, line])
      if (typeof progress === 'function') progress(line)
    }
    let r
    try {
      r = await this.model.build([...args.enabled].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)), args.version || null, OUT + '/' + name, say)
    } catch (e) {
      if (e instanceof PatchError) return { ok: false, error: e.message, log, seconds: Math.round((now() - t0) / 10) / 100 }
      throw e
    }
    const rank: Record<string, number> = { syx: 0, bin: 1, json: 2 }
    const files = this.store.list(OUT).map(p => {
      const n = basename(p), data = this.store.read(p)
      return { name: n, path: p, bytes: data.length, sha256: sha(data), data }
    }).sort((a, b) => (rank[a.name.split('.').pop()!] ?? 3) - (rank[b.name.split('.').pop()!] ?? 3) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    return {
      ok: true, files, seconds: Math.round((now() - t0) / 10) / 100, log,
      device: this.model.dev!.name, os: this.model.rel!.version,
      // what the window's "Firmware built" dialog shows (gui.LoaderModel.build)
      sha256: r.sha256, bytes: r.bytes, version: r.version, flash_end: r.flash_end, headroom: r.headroom,
      gap: r.gap, inplace: r.inplace, mods: r.mods, untouched: r.untouched, recovery: this.model.dev!.recovery,
    }
  }

  /** bridge.py's call(name, args, data, progress), for a worker that sends the Python bridge's messages. */
  async call(name: string, args: any = {}, data?: Uint8Array, progress?: (line: string) => void): Promise<unknown> {
    switch (name) {
      case 'info': return this.info()
      case 'add_core': return this.addCore(args, data!)
      case 'set_stock': return this.setStock(args, data!)
      case 'add_mod': return this.addMod(args, data!)
      case 'remove_mod': return this.removeMod(args)
      case 'mods': return this.mods()
      case 'tick': return this.tick(args)
      case 'check': return this.check(args)
      case 'version': return this.version(args)
      case 'build': return this.build(args, progress)
    }
    throw new KeyError(repr(name))
  }
}
