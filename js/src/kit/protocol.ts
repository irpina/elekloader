// SPDX-License-Identifier: GPL-3.0-or-later
// The kit's messages between a page and its builder worker, and the replies the page gets back. Nothing here names
// a website: any site serves the kit's worker and its catalog, and talks to it in these messages.
//
// A call is { id, call, args, data }. `call` is one of the bridge's calls (web/bridge.py's names: set_stock, add_mod,
// remove_mod, mods, tick, check, version, build, info) or one of the kit's own: init, which loads the site's catalog
// and its cores, and add_catalog_mod, which adds a mod the catalog lists. The worker answers { id, log } for each
// line while a build runs, then { id, ok: true, result } or { id, ok: false, error }.
//
// PROTOCOL changes when a call or a reply changes shape; init's reply carries it, so a page knows what it talks to.
export const PROTOCOL = 1

export type Call = { id: number; call: string; args?: Record<string, unknown>; data?: ArrayBuffer }
export type Answer = { id: number; log: string } | { id: number; ok: true; result: unknown } | { id: number; ok: false; error: string }

/** A device, as the bridge describes it (bridge.ts device()). */
export type Device = {
  key: string; name: string; releases: string[]; container: string; version_len: number; exact_len: boolean
  recovery: string; card_file: boolean; linkable: boolean; default_version: string
}
export type Info = { version: string; supported: string; devices: Device[]; exts: string[] }
/** init's reply: the protocol, the engine's version, the catalog loaded and its cores, and the bridge's info. */
export type Ready = { protocol: number; engine: string; catalog: { revision: string; cores: number; mods: number }; info: Info }

/** The stock file: known by its hash (device name, OS version, the device), or refused with the words why. */
export type Stock =
  | { ok: true; file: string; sha256: string; device: string; os: string; dev: Device; ms: number }
  | { ok: false; file: string; error: string; sha256?: string; supported?: string; ms: number }

/** A mod in the builder's list: the catalog's cores (builtin), the catalog mods added, and the user's own files. */
export type Mod = {
  path: string; file: string; id: string; label: string; builtin: boolean; error?: string
  version?: string; os?: string; fits?: boolean; title?: string; description?: string; category?: string; author?: string
  license?: string; sha256?: string; requires?: string[]; conflicts?: string[]; ram?: number; fast?: number
  for_device?: string; for_label?: string; status?: string
  [fact: string]: unknown
}
export type Added = { ok: true; mod: Mod } | { ok: false; file: string; error: string }
export type Check = { ok: boolean; headline?: string; problems?: string[]; empty?: boolean; order?: string[]; [fact: string]: unknown }
export type VersionField = { ok: boolean; error?: string; name: string }

/** The builder's log: each line with its time in seconds from the start of the build. */
export type Log = [number, string][]
/** A built file, with its bytes as the page's own copy. */
export type Output = { name: string; path: string; bytes: number; sha256: string; data: ArrayBuffer }
export type Built = {
  ok: true; files: Output[]; seconds: number; log: Log; device: string; os: string; sha256: string; bytes: number
  version: string; mods: string[]; recovery: string; [fact: string]: unknown
}
export type BuildFailed = { ok: false; error: string; log?: Log; seconds?: number }
export type BuildResult = Built | BuildFailed
