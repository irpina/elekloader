// SPDX-License-Identifier: GPL-3.0-or-later
// The kit without firmware: the catalog and its checks, the plan, the worker's logic and its refusals, the client
// talking to it through a stand-in worker, and the build page's helpers.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sha } from '../src/bytes.ts'
import { VERSION } from '../src/version.ts'
import { CatalogError, parseCatalog, planBuild, releases, sourceUrl, type Catalog } from '../src/kit/catalog.ts'
import { createBuilder } from '../src/kit/client.ts'
import { buildLogText, buildStep, describeBuilder, prepare } from '../src/kit/build.ts'
import { createService } from '../src/kit/serve.ts'
import { PROTOCOL, type BuildResult, type Ready } from '../src/kit/protocol.ts'

const H = (c: string) => c.repeat(64)
const core = (file: string, os: string, version = '2.1', device = 'digitakt-mk1') =>
  ({ file, sha256: H('a'), id: 'core', version, device, os, license: 'GPL-2.0-or-later', source: { repo: 'irpina/elekloader', tag: 'v0.4.0' } })
const mod = (id: string, os: string, extra: Record<string, unknown> = {}) =>
  ({ file: `${id}-${os}.elemod`, sha256: H('b'), id, version: '1.0', device: 'digitakt-mk1', os, license: 'MIT', title: id, requires: ['core'], conflicts: [],
    source: { repo: 'someone/mods', commit: 'c'.repeat(40), path: `elemods/${id}-${os}.elemod` }, ...extra })
const CATALOG = {
  schema: 1, kind: 'elekloader-catalog', revision: 'e'.repeat(40),
  cores: [core('core-2.1.elemod', '1.53'), core('core-2.1-os1.54.elemod', '1.54'), core('core-2.2.elemod', '1.53', '2.2')],
  mods: [
    mod('digichain', '1.53'), mod('digimono', '1.53', { requires: ['core', 'digichain'] }), mod('fancy', '1.53', { needs_core: '2.2' }),
    mod('digichain', '1.54'), mod('digimono', '1.54', { requires: ['core', 'digichain'] }),
  ],
}

test('a catalog is read whole, and refused when any part is wrong', () => {
  const c = parseCatalog(structuredClone(CATALOG))
  assert.equal(c.mods.length, 5)
  const broken = (change: (c: any) => void) => { const c = structuredClone(CATALOG) as any; change(c); return () => parseCatalog(c) }
  assert.throws(broken(c => { c.kind = 'x' }), /not an elekloader catalog/)
  assert.throws(broken(c => { c.schema = 2 }), /catalog schema 2: this kit reads schema 1/)
  assert.throws(broken(c => { c.mods[0].sha256 = 'ab' }), /"sha256" is 64 lowercase hex digits/)
  assert.throws(broken(c => { c.mods[0].file = '../x.elemod' }), /plain \.elemod or \.dtmod file name/)
  assert.throws(broken(c => { c.mods[1].file = c.mods[0].file }), /two entries named digichain-1\.53\.elemod/)
  assert.throws(broken(c => { c.cores[0].id = 'digimono' }), /is digimono, not a core/)
  assert.throws(broken(c => { c.mods[0].source = { repo: 'someone/mods', commit: 'c'.repeat(7), path: 'x.elemod' } }), /whole commit id/)
  assert.throws(broken(c => { c.mods[0].source = { repo: 'someone/mods', commit: 'c'.repeat(40), path: '../x.elemod' } }), /whole commit id and a plain path/)
  assert.throws(broken(c => { c.mods[0].source = { repo: 'nowhere' } }), /owner\/name/)
  assert.throws(broken(c => { c.mods[0].requires = 'core' }), /"requires" is a list of mod ids/)
  assert.throws(broken(c => { delete c.mods[0].title }), CatalogError)
})

test('a file is downloaded from its release or its commit', () => {
  const c = parseCatalog(structuredClone(CATALOG))
  assert.equal(sourceUrl(c.cores[0]), 'https://github.com/irpina/elekloader/releases/download/v0.4.0/core-2.1.elemod')
  assert.equal(sourceUrl(c.mods[0]), `https://raw.githubusercontent.com/someone/mods/${'c'.repeat(40)}/elemods/digichain-1.53.elemod`)
})

test('a plan brings what each mod requires, and the newest core it needs', () => {
  const c = parseCatalog(structuredClone(CATALOG))
  const p = planBuild(c, 'digitakt-mk1', '1.53', ['digimono'])
  assert.deepEqual(p.mods.map(m => m.id), ['digichain', 'digimono'])
  assert.equal(p.core!.file, 'core-2.2.elemod')
  assert.equal(planBuild(c, 'digitakt-mk1', '1.54', ['digimono']).core!.file, 'core-2.1-os1.54.elemod')
  assert.deepEqual(planBuild(c, 'digitakt-mk1', '1.54', ['fancy', 'digichain']).missing, ['fancy'])
  assert.equal(planBuild(c, 'digitone-mk1', '1.43', []).core, undefined)
  assert.deepEqual(releases(c, 'digitakt-mk1', 'digimono'), ['1.53', '1.54'])
})

/** A site: its files by URL. */
function site(files: Record<string, Uint8Array | string>) {
  const got: string[] = []
  const get = async (url: string) => {
    got.push(url)
    const f = files[url]
    if (f === undefined) throw new Error(url.split('/').pop() + ': 404')
    return typeof f === 'string' ? new TextEncoder().encode(f) : f
  }
  return { get, got }
}
const BASE = 'https://example.test/kit/'
const empty = { schema: 1, kind: 'elekloader-catalog', revision: 'r1', cores: [], mods: [] }

test('init loads the catalog and its cores from the site, once, and refuses what does not match', async () => {
  const s = site({ [BASE + 'catalog.json']: JSON.stringify(empty) })
  const handle = createService(s.get)
  await assert.rejects(handle({ call: 'mods' }), /not loaded: call init first/)
  await assert.rejects(handle({ call: 'init', args: { base: '/kit/' } }), /absolute URL/)
  await assert.rejects(handle({ call: 'init', args: { base: BASE, catalog: '../x.json' } }), /plain \.json file name/)
  const ready = await handle({ call: 'init', args: { base: BASE } }) as Ready
  assert.deepEqual([ready.protocol, ready.engine, ready.catalog], [PROTOCOL, VERSION, { revision: 'r1', cores: 0, mods: 0 }])
  assert.equal(ready.info.devices[0].key, 'digitakt-mk1')
  await handle({ call: 'init', args: { base: BASE } })
  assert.equal(s.got.length, 1)                                 // loaded once
  await assert.rejects(handle({ call: 'init', args: { base: 'https://other.test/' } }), /already loaded https:\/\/example\.test\/kit\//)
  await assert.rejects(handle({ call: 'add_core', args: { name: 'x.elemod', sha256: H('a') } }), /no call add_core/)
  await assert.rejects(handle({ call: 'add_catalog_mod', args: { file: 'digimono-1.53.elemod' } }), /not in the site's catalog/)
  const st = await handle({ call: 'set_stock', args: { name: 'junk.syx' }, data: new Uint8Array(64).buffer }) as { ok: boolean; error: string }
  assert.equal(st.ok, false)
  assert.match(st.error, /^not a stock firmware elekloader knows/)
})

test('a core or a catalog mod that is not the pinned file is refused', async () => {
  const wrong = new TextEncoder().encode('not the core')
  const c = { ...empty, cores: [core('core-2.1.elemod', '1.53')] }
  const s = site({ [BASE + 'catalog.json']: JSON.stringify(c), [BASE + 'core-2.1.elemod']: wrong })
  await assert.rejects(createService(s.get)({ call: 'init', args: { base: BASE } }), /core-2\.1\.elemod is not the file the catalog pins/)
  const m = { ...empty, mods: [mod('digichain', '1.53')] }
  const s2 = site({ [BASE + 'catalog.json']: JSON.stringify(m), [BASE + 'digichain-1.53.elemod']: wrong })
  const handle = createService(s2.get)
  await handle({ call: 'init', args: { base: BASE } })
  await assert.rejects(handle({ call: 'add_catalog_mod', args: { file: 'digichain-1.53.elemod' } }), /is not the file the catalog pins/)
  // the pin's own hash: a file that is the pinned one but does not load is the engine's refusal, not the kit's
  const junk = new TextEncoder().encode('{"elemod": 2}')
  const m3 = { ...empty, mods: [{ ...mod('digichain', '1.53'), sha256: sha(junk) }] }
  const h3 = createService(site({ [BASE + 'catalog.json']: JSON.stringify(m3), [BASE + 'digichain-1.53.elemod']: junk }).get)
  await h3({ call: 'init', args: { base: BASE } })
  assert.deepEqual(await h3({ call: 'add_catalog_mod', args: { file: 'digichain-1.53.elemod' } }), { ok: false, file: 'digichain-1.53.elemod', error: 'digichain-1.53.elemod: no "id"' })
})

/** The kit's worker in this process: messages in, answers out, as the real one. */
class StandInWorker {
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  terminated = false
  handle: ReturnType<typeof createService>
  constructor(handle: ReturnType<typeof createService>) { this.handle = handle }
  postMessage(msg: any) {
    void (async () => {
      const send = (data: unknown) => this.onmessage?.({ data } as MessageEvent)
      try { send({ id: msg.id, ok: true, result: await this.handle(msg, line => send({ id: msg.id, log: line })) }) } catch (e) { send({ id: msg.id, ok: false, error: (e as Error).message }) }
    })()
  }
  terminate() { this.terminated = true }
}

test('the client: one worker, promises, the catalog loaded once, closed for good', async () => {
  const s = site({ [BASE + 'catalog.json']: JSON.stringify(empty) })
  let started = 0, w: StandInWorker | undefined
  const b = createBuilder({ base: BASE, worker: () => { started++; return (w = new StandInWorker(createService(s.get))) as unknown as Worker } })
  const ready = await b.load()
  assert.equal(ready.catalog.revision, 'r1')
  assert.equal(await b.load(), ready)
  assert.deepEqual(await b.mods(), [])
  const st = await b.setStock(new File([new Uint8Array(8)], 'x.syx'))
  assert.equal(st.ok, false)
  await assert.rejects(b.call('nope'), /no call nope/)
  assert.equal(started, 1)
  b.dispose()
  assert.equal(w!.terminated, true)
  await assert.rejects(b.mods(), /The builder was closed/)
})

test('prepare: the stock file must be the one chosen, the plan\'s files come from the catalog, the plan\'s core is ticked', async () => {
  const c = parseCatalog(structuredClone(CATALOG))
  const added: string[] = []
  const fake = (os: string) => ({
    load: async () => ({}),
    setStock: async () => ({ ok: true, file: 'x.syx', device: 'Digitakt mk1', os, dev: { key: 'digitakt-mk1' } }),
    addCatalogMod: async (file: string) => { added.push(file); return { ok: true, mod: { path: '/work/mods/' + file } } },
    tick: async (enabled: string[], path: string) => [...new Set([...enabled, path, '/work/core/core-2.1.elemod'])].sort(),
    mods: async () => [
      { path: '/work/core/core-2.1.elemod', file: 'core-2.1.elemod', id: 'core', builtin: true, fits: true },
      { path: '/work/core/core-2.2.elemod', file: 'core-2.2.elemod', id: 'core', builtin: true, fits: true },
    ],
    check: async (enabled: string[]) => ({ ok: true, order: enabled }),
  }) as any
  const stock = new File([new Uint8Array(4)], 'x.syx')
  const p = await prepare(fake('1.53'), { catalog: c, device: 'digitakt-mk1', os: '1.53', stock, ids: ['digimono', 'fancy'] })
  assert.deepEqual(added, ['digichain-1.53.elemod', 'digimono-1.53.elemod', 'fancy-1.53.elemod'])
  assert.deepEqual(p.ok && p.enabled, ['/work/core/core-2.2.elemod', '/work/mods/digichain-1.53.elemod', '/work/mods/digimono-1.53.elemod', '/work/mods/fancy-1.53.elemod'])
  const other = await prepare(fake('1.54'), { catalog: c, device: 'digitakt-mk1', os: '1.53', stock, ids: [] })
  assert.deepEqual(other, { ok: false, error: 'This OS file is Digitakt mk1 1.54, not the digitakt-mk1 OS 1.53 chosen.', device: { key: 'digitakt-mk1' } })
  assert.deepEqual(await prepare(fake('1.54'), { catalog: c, device: 'digitakt-mk1', os: '1.54', stock, ids: ['fancy'] }),
    { ok: false, error: 'Not available for OS 1.54: fancy.' })
})

test('the build steps and the build log', () => {
  const lines = ['stock: Digitakt mk1 OS 1.53 (…)', 'mod core 2.1  39 sites', 'the mods combine: …', 'linked core 2.1: RAM …', 'packed the main OS: 1 -> 1 bytes (0.2 s)', 'verified: …']
  let step = buildStep(lines[0])
  assert.deepEqual(lines.map(l => (step = buildStep(l, step))), ['composing', 'composing', 'composing', 'packing', 'verifying', 'verifying'])
  const ready = { protocol: 1, engine: '0.4.0', catalog: { revision: 'e4d8ba8', cores: 4, mods: 8 } } as Ready
  assert.equal(describeBuilder(ready), 'elekloader 0.4.0 (kit protocol 1), catalog e4d8ba8')
  const built: BuildResult = { ok: true, files: [{ name: 'custom.syx', path: '/work/out/custom.syx', bytes: 10, sha256: H('d'), data: new ArrayBuffer(0) }], seconds: 0.4,
    log: [[0.04, 'stock: …'], [0.28, 'packed the main OS: 1 -> 1 bytes (0.2 s)']], device: 'Digitakt mk1', os: '1.53', sha256: H('d'), bytes: 10, version: '2.0a', mods: ['core 2.1'], recovery: '' }
  const text = buildLogText({ title: 'Some forum build log', builder: describeBuilder(ready), device: 'Digitakt mk1', os: '1.53', version: '2.0a', enabled: [], result: built })
  assert.equal(text, [
    'Some forum build log: Digitakt mk1, OS 1.53', 'Builder: elekloader 0.4.0 (kit protocol 1), catalog e4d8ba8', 'Mods: core 2.1', 'OS version shown: 2.0a',
    'Result: built and verified in 0.40 s', `  custom.syx  10 bytes  sha256 ${H('d')}`, '', '   0.04 s  stock: …', '   0.28 s  packed the main OS: 1 -> 1 bytes (0.2 s)', ''].join('\n'))
  const failed = buildLogText({ builder: 'b', device: 'Digitone mk1', os: '1.43', version: '2.0a', enabled: ['/work/mods/x.elemod'], result: { ok: false, error: 'no' } })
  assert.match(failed, /^elekloader build log: Digitone mk1, OS 1\.43\nBuilder: b\nMods: x\.elemod\nOS version shown: 2\.0a\nResult: failed: no\n\n$/)
})
