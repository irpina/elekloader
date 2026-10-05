// SPDX-License-Identifier: GPL-3.0-or-later
// The catalog a site offers: the cores and mods its builder may fetch, each pinned by sha256 to a file the site
// serves beside catalog.json, with where that file comes from (an author's GitHub release, or their repository at a
// commit). elekloader publishes its curated catalog in this format with each release; a site takes it whole, takes
// part of it, or adds its own entries. docs/INTEGRATING.md describes it.
export const CATALOG_SCHEMA = 1

export type Source = { repo: string; tag: string } | { repo: string; commit: string; path: string }
/** A file the builder may fetch: what the file says about itself (id, version, device, OS, licence), its sha256 and
 * its source. `file` is its name on the site, beside catalog.json, and is unique in the catalog. */
export type Pin = { file: string; sha256: string; id: string; version: string; device: string; os: string; license: string; source: Source }
/** A mod, with what a page shows: its title and summary, what it requires, and what has been checked on a unit. */
export type CatalogMod = Pin & {
  title: string; requires: string[]; conflicts: string[]; summary?: string; description?: string; category?: string
  author?: string; needs_core?: string; on_unit?: string
}
export type Catalog = { schema: 1; kind: 'elekloader-catalog'; revision: string; about?: string; cores: Pin[]; mods: CatalogMod[] }

export class CatalogError extends Error {}

const HEX64 = /^[0-9a-f]{64}$/, COMMIT = /^[0-9a-f]{40}$/
const FILE = /^[\w.-]+\.(elemod|dtmod)$/, REPO = /^[\w.-]+\/[\w.-]+$/, PATH = /^[\w.-]+(\/[\w.-]+)*$/
const text = (v: unknown) => typeof v === 'string' && v !== ''

/** Versions in order, numbers as numbers (2.10 after 2.9): the order the page and the engine use. */
export function cmpVersion(a: string, b: string) {
  return a.localeCompare(b, 'en', { numeric: true })
}

function pin(v: unknown, at: string): Pin {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new CatalogError(`${at}: not an object`)
  const p = v as Record<string, unknown>
  if (!text(p.file) || !FILE.test(p.file as string)) throw new CatalogError(`${at}: "file" is a plain .elemod or .dtmod file name`)
  const where = `${at} (${p.file})`
  if (!text(p.sha256) || !HEX64.test(p.sha256 as string)) throw new CatalogError(`${where}: "sha256" is 64 lowercase hex digits`)
  for (const k of ['id', 'version', 'device', 'os']) if (!text(p[k])) throw new CatalogError(`${where}: no "${k}"`)
  if (typeof p.license !== 'string') throw new CatalogError(`${where}: no "license"`)
  const s = p.source as Record<string, unknown> | undefined
  if (!s || !text(s.repo) || !REPO.test(s.repo as string)) throw new CatalogError(`${where}: "source" names a GitHub repository (owner/name)`)
  if ('commit' in s) {
    if (!text(s.commit) || !COMMIT.test(s.commit as string) || !text(s.path) || !PATH.test(s.path as string) || (s.path as string).split('/').includes('..'))
      throw new CatalogError(`${where}: a commit source has the whole commit id and a plain path in the repository`)
  } else if (!text(s.tag)) {
    throw new CatalogError(`${where}: "source" has a release "tag", or a "commit" and "path"`)
  }
  return p as Pin
}

/** A catalog, checked: the shape above, every pin whole, file names unique, the cores cores. Throws CatalogError. */
export function parseCatalog(value: unknown): Catalog {
  const c = value as Record<string, unknown>
  if (!c || typeof c !== 'object' || c.kind !== 'elekloader-catalog') throw new CatalogError('not an elekloader catalog')
  if (c.schema !== CATALOG_SCHEMA) throw new CatalogError(`catalog schema ${String(c.schema)}: this kit reads schema ${CATALOG_SCHEMA}`)
  if (!text(c.revision)) throw new CatalogError('the catalog has no "revision"')
  if (!Array.isArray(c.cores) || !Array.isArray(c.mods)) throw new CatalogError('the catalog has no "cores" and "mods" lists')
  const names = new Set<string>()
  const seen = (p: Pin) => {
    if (names.has(p.file)) throw new CatalogError(`two entries named ${p.file}`)
    names.add(p.file)
    return p
  }
  c.cores.forEach((v, i) => {
    const p = seen(pin(v, `cores[${i}]`))
    if (p.id !== 'core') throw new CatalogError(`cores[${i}] (${p.file}) is ${p.id}, not a core`)
  })
  c.mods.forEach((v, i) => {
    const p = seen(pin(v, `mods[${i}]`)) as CatalogMod
    if (!text(p.title)) throw new CatalogError(`mods[${i}] (${p.file}): no "title"`)
    for (const k of ['requires', 'conflicts'] as const)
      if (!Array.isArray(p[k]) || !p[k].every(text)) throw new CatalogError(`mods[${i}] (${p.file}): "${k}" is a list of mod ids`)
  })
  return c as Catalog
}

/** Where a pinned file can be downloaded from its source (for a site's own copy; the builder only fetches the site's). */
export function sourceUrl(p: Pin): string {
  const s = p.source
  return 'commit' in s
    ? `https://raw.githubusercontent.com/${s.repo}/${s.commit}/${s.path}`
    : `https://github.com/${s.repo}/releases/download/${encodeURIComponent(s.tag)}/${encodeURIComponent(p.file)}`
}

export type Plan = { core?: Pin; mods: CatalogMod[]; missing: string[] }

/** The catalog files for a selection of mod ids on one device and OS version. Each mod brings the catalog mods it
 * requires (digichain for Digi Mono), required ones first; ids with no file for that OS are `missing`. The core is
 * the newest for that OS, and at least as new as every chosen mod's needs_core. */
export function planBuild(catalog: Catalog, device: string, os: string, ids: readonly string[]): Plan {
  const forOs = (p: Pin) => p.device === device && p.os === os
  const newest = (ps: CatalogMod[]) => ps.sort((a, b) => cmpVersion(b.version, a.version))[0] as CatalogMod | undefined
  const mods: CatalogMod[] = [], missing: string[] = []
  const add = (id: string, path: string[]) => {
    if (mods.some(m => m.id === id) || missing.includes(id)) return
    const m = newest(catalog.mods.filter(x => x.id === id && forOs(x)))
    if (!m) { missing.push(id); return }
    for (const r of m.requires) if (r !== 'core' && !path.includes(r)) add(r, [...path, id])
    mods.push(m)
  }
  for (const id of ids) add(id, [])
  const need = mods.map(m => m.needs_core).filter((v): v is string => !!v).sort(cmpVersion).pop()
  const core = catalog.cores.filter(c => forOs(c) && (!need || cmpVersion(c.version, need) >= 0))
    .sort((a, b) => cmpVersion(b.version, a.version))[0]
  return { core, mods, missing }
}

/** The OS versions a mod has a file for, on a device. */
export function releases(catalog: Catalog, device: string, id: string): string[] {
  return [...new Set(catalog.mods.filter(m => m.device === device && m.id === id).map(m => m.os))].sort(cmpVersion)
}
