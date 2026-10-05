// SPDX-License-Identifier: GPL-3.0-or-later
// The kit, for a website's pages: the client for the builder worker (worker.ts, started separately), the catalog
// format, and the build page's helpers. docs/INTEGRATING.md has how a site uses it.
export { createBuilder, type Builder, type BuilderOptions } from './client.ts'
export { CATALOG_SCHEMA, CatalogError, cmpVersion, parseCatalog, planBuild, releases, sourceUrl, type Catalog, type CatalogMod, type Pin, type Plan, type Source } from './catalog.ts'
export { buildLogText, buildStep, describeBuilder, prepare, type Prepared, type Step } from './build.ts'
export { PROTOCOL } from './protocol.ts'
export type * from './protocol.ts'
