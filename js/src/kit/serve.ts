// SPDX-License-Identifier: GPL-3.0-or-later
// The builder worker's logic, apart from the worker so it can be tested: one bridge, the site's catalog, and the
// files fetched from the site, each checked against its pin before the engine sees it. `get` fetches a URL from the
// site (the worker's own, which refuses anything off the site).
import { Bridge } from '../bridge.ts'
import { sha } from '../bytes.ts'
import { VERSION } from '../version.ts'
import { parseCatalog, type Catalog } from './catalog.ts'
import { PROTOCOL, type Built, type Call, type Ready } from './protocol.ts'

export type Fetcher = (url: string) => Promise<Uint8Array>

/** The calls a page may make through to the bridge. Cores come from the catalog only, at init. */
const BRIDGE_CALLS = new Set(['info', 'set_stock', 'add_mod', 'remove_mod', 'mods', 'tick', 'check', 'version', 'build'])

export function createService(get: Fetcher) {
  let bridge: Bridge | undefined, catalog: Catalog | undefined, base = ''
  let loading: Promise<Ready> | undefined

  const ready = (): Ready => ({
    protocol: PROTOCOL, engine: VERSION,
    catalog: { revision: catalog!.revision, cores: catalog!.cores.length, mods: catalog!.mods.length }, info: bridge!.info(),
  })

  async function load(siteBase: string, name: string): Promise<Ready> {
    const json = JSON.parse(new TextDecoder().decode(await get(new URL(name, siteBase).href)))
    const c = parseCatalog(json), b = new Bridge()
    for (const core of c.cores) {
      const raw = await get(new URL(core.file, siteBase).href)
      if (sha(raw) !== core.sha256) throw new Error(`${core.file} is not the file the catalog pins`)
      b.addCore({ name: core.file, sha256: core.sha256 }, raw)
    }
    bridge = b; catalog = c; base = siteBase
    return ready()
  }

  /** init { base, catalog = 'catalog.json' }: the site's catalog and its cores, once; again with the same base is a
   * no-op, and another base is refused (one builder, one site). */
  function init(args: Record<string, unknown>): Promise<Ready> {
    const siteBase = String(args.base ?? ''), name = String(args.catalog ?? 'catalog.json')
    if (!/^[\w.-]+\.json$/.test(name)) throw new Error('the catalog is a plain .json file name beside the kit\'s files')
    if (!/^https?:\/\//.test(siteBase)) throw new Error('init needs the absolute URL the site serves the catalog from')
    if (base && siteBase !== base) throw new Error('this builder already loaded ' + base)
    if (!loading) loading = load(siteBase, name).catch(error => { loading = undefined; throw error })
    return loading
  }

  /** add_catalog_mod { file }: a mod the catalog lists, fetched from the site and checked against its pin. */
  async function addCatalogMod(args: Record<string, unknown>) {
    const pin = catalog!.mods.find(m => m.file === args.file)
    if (!pin) throw new Error(`${String(args.file)} is not in the site's catalog`)
    const raw = await get(new URL(pin.file, base).href)
    if (sha(raw) !== pin.sha256) throw new Error(`${pin.file} is not the file the catalog pins`)
    return bridge!.addMod({ name: pin.file, sha256: pin.sha256 }, raw)
  }

  return async function handle(call: Pick<Call, 'call' | 'args' | 'data'>, progress?: (line: string) => void): Promise<unknown> {
    const args = call.args ?? {}
    if (call.call === 'init') return init(args)
    if (!bridge) throw new Error('the builder is not loaded: call init first')
    if (call.call === 'add_catalog_mod') return addCatalogMod(args)
    if (!BRIDGE_CALLS.has(call.call)) throw new Error(`no call ${call.call}`)
    const result = await bridge.call(call.call, args, call.data ? new Uint8Array(call.data) : undefined, progress)
    if (call.call !== 'build' || !(result as { ok: boolean }).ok) return result
    // the page gets its own copy of each file: the engine keeps its in /work/out until the next build
    const built = result as Omit<Built, 'files'> & { files: (Omit<Built['files'][number], 'data'> & { data: Uint8Array })[] }
    return { ...built, files: built.files.map(f => ({ ...f, data: f.data.slice().buffer })) } as Built
  }
}
