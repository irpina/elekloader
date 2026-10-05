// SPDX-License-Identifier: GPL-3.0-or-later
// The kit's tools for a website and for elekloader's releases (docs/INTEGRATING.md):
//
//   node js/tools/kit.ts feed --list web/catalog.json --files <downloaded> --revision <commit>
//        [--core <core.elemod>... --core-source owner/repo@tag] --out catalog.json
//     elekloader's curated catalog, from its list and the files it names: each file read by the engine for what it
//     says about itself (id, version, device, OS, licence, requires), with the list's summary and checks on a unit.
//   node js/tools/kit.ts sync <catalog.json> <out dir> [--device <key>]...
//     a site's copy: every pinned file downloaded from its source and checked against its sha256, and the catalog
//     (only those devices', if given) written beside them.
//   node js/tools/kit.ts verify <dir> [--lock <lock.json> --kit <kit dir>]
//     the site's copy as served: the catalog whole, every pin's file there and the same, nothing else; with a lock,
//     the catalog and the kit's files are the ones it pins.
//   node js/tools/kit.ts lock --kit <kit dir> --catalog <dir>
//     prints a lock file for the site's repository: the kit's files and the catalog, by sha256.
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { basename, join, relative, sep } from 'node:path'
import { sha } from '../src/bytes.ts'
import { loadAny } from '../src/patch.ts'
import { VERSION } from '../src/version.ts'
import { parseCatalog, sourceUrl, type Catalog, type CatalogMod, type Pin, type Source } from '../src/kit/catalog.ts'
import { PROTOCOL } from '../src/kit/protocol.ts'

const [, , cmd, ...rest] = process.argv
const flags = new Map<string, string[]>(), args: string[] = []
for (let i = 0; i < rest.length; i++) {
  if (rest[i].startsWith('--')) {
    const k = rest[i].slice(2), vs: string[] = []
    while (i + 1 < rest.length && !rest[i + 1].startsWith('--')) vs.push(rest[++i])
    flags.set(k, [...(flags.get(k) ?? []), ...vs])
  } else args.push(rest[i])
}
const flag = (k: string) => flags.get(k)?.[0]
const die = (msg: string): never => { console.error(msg); process.exit(1) }
const json = (p: string) => JSON.parse(readFileSync(p, 'utf8'))

function walk(dir: string): string[] {
  return readdirSync(dir).sort().flatMap(n => (statSync(join(dir, n)).isDirectory() ? walk(join(dir, n)) : [join(dir, n)]))
}

/** What a file says about itself, as a pin. */
function facts(path: string, source: Source, license?: string): Pin & { doc: Record<string, any>; requires: string[]; conflicts: string[] } {
  const data = new Uint8Array(readFileSync(path))
  const m = loadAny({ path, data })
  const lic = (m.doc.license as string) || license || ''
  return { file: basename(path), sha256: sha(data), id: m.id, version: m.version, device: m.dev.key, os: m.rel.version, license: lic, source, doc: m.doc, requires: [...m.requires], conflicts: [...m.conflicts] }
}

function feed() {
  const list = json(flag('list') ?? die('feed: --list <web/catalog.json>')).items as Record<string, any>[]
  const files = flag('files') ?? die('feed: --files <the folder the listed files were downloaded to>')
  const revision = flag('revision') ?? die('feed: --revision <the commit of the list>')
  const out = flag('out') ?? die('feed: --out <catalog.json>')
  const cores: Pin[] = [], mods: CatalogMod[] = []
  const coreSource = flag('core-source')
  for (const p of flags.get('core') ?? []) {
    if (!coreSource || !/^[\w.-]+\/[\w.-]+@.+$/.test(coreSource)) die('feed: --core-source owner/repo@tag, where the --core files are released')
    const [repo, tag] = coreSource!.split('@')
    const { doc: _doc, requires: _r, conflicts: _c, ...pin } = facts(p, { repo, tag })
    cores.push(pin)
  }
  for (const it of list) {
    const file = it.file ?? String(it.path).split('/').pop()
    const path = join(files, file)
    if (!existsSync(path)) { console.error(`warning: ${file} is not in ${files}; the catalog leaves it out`); continue }
    const source: Source = it.commit ? { repo: it.repo, commit: it.commit, path: it.path } : { repo: it.repo, tag: it.tag }
    const f = facts(path, source, it.license)
    if (f.sha256 !== it.sha256) die(`${file}: sha256 ${f.sha256}, not the ${it.sha256} the list pins`)
    if (f.device !== it.device) die(`${file} is made for ${f.device}, not the list's ${it.device}`)
    const { doc, requires, conflicts, ...pin } = f
    if (it.kind === 'core') { cores.push(pin); continue }
    const mod: CatalogMod = { ...pin, title: it.title ?? doc.title ?? f.id, requires, conflicts }
    for (const [k, v] of [['summary', it.summary], ['description', doc.description], ['category', doc.category], ['author', doc.author], ['needs_core', it.needs_core], ['on_unit', it.on_unit]] as const)
      if (v) (mod as Record<string, unknown>)[k] = v
    mods.push(mod)
  }
  const byFile = (a: Pin, b: Pin) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0)
  const seen = new Map<string, Pin>()
  for (const c of cores) {
    const was = seen.get(c.file)
    if (was && was.sha256 !== c.sha256) die(`two different ${c.file}`)
    seen.set(c.file, c)
  }
  const catalog: Catalog = {
    schema: 1, kind: 'elekloader-catalog', revision,
    about: 'elekloader\'s curated catalog: the cores and mods a site may offer, each pinned by sha256 to its author\'s release or commit. docs/INTEGRATING.md.',
    cores: [...seen.values()].sort(byFile), mods,
  }
  parseCatalog(catalog)
  writeFileSync(out, JSON.stringify(catalog, null, 1) + '\n')
  console.log(`${out}: ${catalog.cores.length} cores, ${mods.length} mods, revision ${revision.slice(0, 7)}`)
}

async function sync() {
  const [from, out] = args
  if (!from || !out) die('sync <catalog.json> <out dir> [--device <key>]...')
  const all = parseCatalog(json(from)), devices = flags.get('device')
  const keep = (p: Pin) => !devices || devices.includes(p.device)
  const catalog: Catalog = { ...all, cores: all.cores.filter(keep), mods: all.mods.filter(keep) }
  mkdirSync(out, { recursive: true })
  for (const p of [...catalog.cores, ...catalog.mods]) {
    const dest = join(out, p.file)
    if (existsSync(dest) && sha(new Uint8Array(readFileSync(dest))) === p.sha256) continue
    const r = await fetch(sourceUrl(p), { redirect: 'follow' })
    if (!r.ok) die(`${p.file}: ${sourceUrl(p)} answered ${r.status}`)
    const data = new Uint8Array(await r.arrayBuffer())
    if (sha(data) !== p.sha256) die(`${p.file}: sha256 ${sha(data)}, not the ${p.sha256} the catalog pins`)
    writeFileSync(dest, data)
    console.log(`  ${p.file}`)
  }
  writeFileSync(join(out, 'catalog.json'), JSON.stringify(catalog, null, 1) + '\n')
  console.log(`${out}: ${catalog.cores.length} cores and ${catalog.mods.length} mods, checked`)
}

function verify() {
  const [dir] = args
  if (!dir) die('verify <dir> [--lock <lock.json> --kit <kit dir>]')
  const raw = readFileSync(join(dir, 'catalog.json'))
  const catalog = parseCatalog(JSON.parse(raw.toString('utf8')))
  const bad: string[] = []
  const pins = [...catalog.cores, ...catalog.mods]
  for (const p of pins) {
    const f = join(dir, p.file)
    if (!existsSync(f)) bad.push(`missing: ${p.file}`)
    else if (sha(new Uint8Array(readFileSync(f))) !== p.sha256) bad.push(`not the pinned file: ${p.file}`)
  }
  const named = new Set(pins.map(p => p.file))
  for (const n of readdirSync(dir)) if (/\.(elemod|dtmod)$/.test(n) && !named.has(n)) bad.push(`not in the catalog: ${n}`)
  const lockPath = flag('lock')
  if (lockPath) {
    const lock = json(lockPath)
    if (lock.kind !== 'elekloader-kit-lock' || lock.schema !== 1) bad.push(`${lockPath} is not a kit lock file`)
    if (lock.catalog?.sha256 !== sha(new Uint8Array(raw))) bad.push(`catalog.json is not the one ${lockPath} pins (revision ${lock.catalog?.revision})`)
    const kit = flag('kit') ?? die('verify --lock needs --kit <the kit\'s folder>')
    const files = kitFiles(kit)
    for (const [p, h] of Object.entries(lock.kit?.files ?? {})) if (files[p] !== h) bad.push(files[p] ? `kit file changed: ${p}` : `kit file missing: ${p}`)
    for (const p of Object.keys(files)) if (!(p in (lock.kit?.files ?? {}))) bad.push(`kit file not in the lock: ${p}`)
  }
  if (bad.length) die(bad.join('\n'))
  console.log(`${dir}: catalog ${catalog.revision.slice(0, 7)}, ${catalog.cores.length} cores and ${catalog.mods.length} mods${lockPath ? ', and the kit,' : ''} as pinned`)
}

function kitFiles(dir: string) {
  return Object.fromEntries(walk(dir).map(f => [relative(dir, f).split(sep).join('/'), sha(new Uint8Array(readFileSync(f)))]))
}

function lock() {
  const kit = flag('kit') ?? die('lock --kit <kit dir> --catalog <dir>'), dir = flag('catalog') ?? die('lock --catalog <dir>')
  const raw = readFileSync(join(dir, 'catalog.json')), catalog = parseCatalog(JSON.parse(raw.toString('utf8')))
  console.log(JSON.stringify({
    schema: 1, kind: 'elekloader-kit-lock',
    kit: { version: VERSION, protocol: PROTOCOL, files: kitFiles(kit) },
    catalog: { revision: catalog.revision, sha256: sha(new Uint8Array(raw)), cores: catalog.cores.length, mods: catalog.mods.length },
  }, null, 1))
}

if (cmd === 'feed') feed()
else if (cmd === 'sync') await sync()
else if (cmd === 'verify') verify()
else if (cmd === 'lock') lock()
else die('node js/tools/kit.ts feed | sync | verify | lock (see the top of this file)')
