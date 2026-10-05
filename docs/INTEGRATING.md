# Building firmware on your website: elekloader's kit

The kit lets any website build custom firmware in its visitors' browsers with elekloader's engine. The engine is the TypeScript port in `js/`, which writes the same bytes as the Python. The kit belongs to no website: elekloader's own page and a forum use the same files.

What the kit provides:
- **the engine,** in a worker started from your site;
- **a client** your pages call with promises;
- **a catalog format:** the cores and mods your site offers, each pinned by sha256;
- **elekloader's curated catalog** in that format, with every release;
- **tools** to copy a catalog's files, check them, and pin everything in a lock file;
- **the build page's helpers:** prepare a selection, follow a build in three steps, keep its log as text for bug reports.

What stays yours: your pages, their design, your accounts and your community. The kit has no UI and talks to no server.

## The pieces

| file | what |
|---|---|
| `kit/worker.ts` (`dist/kit/worker.js`) | the builder worker: one bridge (web/bridge.py's calls), the catalog and its cores loaded from your site, every file checked against its pin. It keeps to your site's origin. |
| `kit/client.ts` | `createBuilder({ base, worker })`: the worker, called with promises. |
| `kit/catalog.ts` | the catalog format, `parseCatalog`, `planBuild` (a selection's files, with what each mod requires, and the core it needs), `sourceUrl`. |
| `kit/build.ts` | `prepare` (load and check a selection), `buildStep` (the three steps from the log), `buildLogText`, `describeBuilder`. |
| `kit/protocol.ts` | the messages and replies, and `PROTOCOL`. |
| `tools/kit.ts` | `feed`, `sync`, `verify`, `lock`. |
| `examples/minimal/` | the smallest site: stock file, mods, build, log, downloads. |

## Put it on your site

1. **Take the kit:** `elekloader-kit-<version>.zip` from an [elekloader release](https://github.com/irpina/elekloader/releases). Check it against the sha256 in the release notes.
   - **No bundler:** serve `dist/` as it is, for example at `/elekloader/`.
   - **With a bundler** (Vite, esbuild): import `src/kit/index.ts`. Start the worker with `new Worker(new URL('…/src/kit/worker.ts', import.meta.url), { type: 'module' })`.
2. **Take the catalog:** `elekloader-catalog.json` from the same release. Copy its files to your site:
   ```bash
   node tools/kit.ts sync elekloader-catalog.json public/elekloader-catalog --device digitakt-mk1 --device digitone-mk1
   ```
   `sync` downloads each file from its author's release or commit and checks its sha256. It writes the catalog beside the files, keeping only the devices you name. Keep the catalog in its own folder, apart from the kit's files, so each is pinned on its own. To offer only some mods, or add your own, edit the catalog (format below) and run `sync` again.
3. **Pin it:**
   ```bash
   node tools/kit.ts lock --kit public/elekloader --catalog public/elekloader-catalog > elekloader.lock.json
   ```
   Commit the lock file. In your CI, check that what you deploy is what you pinned:
   ```bash
   node tools/kit.ts verify public/elekloader-catalog --lock elekloader.lock.json --kit public/elekloader
   ```
   The check fails on a changed, missing or extra file, in the kit or in the catalog.
4. **Call it from your page:**
   ```js
   import { createBuilder, parseCatalog, prepare, buildStep, buildLogText, describeBuilder } from '/elekloader/kit/index.js'

   const builder = createBuilder({
     base: '/elekloader-catalog/',                       // where catalog.json and its files are served
     worker: () => new Worker('/elekloader/kit/worker.js', { type: 'module' }),
   })
   const catalog = parseCatalog(await (await fetch('/elekloader-catalog/catalog.json')).json())
   const ready = await builder.load()                      // the catalog and its cores, checked

   // the owner's stock file (a File from an <input type="file">) and the mod ids they chose
   const prepared = await prepare(builder, { catalog, device: 'digitakt-mk1', os: '1.53', stock: file, ids: ['digimono'] })
   if (!prepared.ok) throw new Error(prepared.error)       // elekloader's words: conflicts, a wrong OS file, …

   let step = 'composing'                                  // then 'packing', 'verifying'
   const built = await builder.build(prepared.enabled, '2.0a', 'custom.syx', line => { step = buildStep(line, step) })
   // built.files: each output's name, sha256 and bytes (an ArrayBuffer) to offer as a download
   const log = buildLogText({ title: 'Your site build log', builder: describeBuilder(ready), device: 'Digitakt mk1', os: '1.53', version: '2.0a', enabled: prepared.enabled, result: built })
   ```
   `examples/minimal/` does all of this in about a hundred lines.
5. **Serve it right:**
   - **A secure context:** https, or localhost.
   - **The page's CSP** needs `worker-src 'self'` and `script-src 'self'`. No `'wasm-unsafe-eval'`: nothing runs WebAssembly.
   - **The worker** keeps to your origin by itself. It needs no CSP header.

## What a site must do

- **Keep the owner's files in their browser.** Never upload a stock OS file or a build. The kit never sends them anywhere: the worker refuses every request off your site. Don't add a path that does.
- **Show how to get back to stock** before offering a download. `built.recovery` is the device's own text. The owner flashes the file themselves; the kit never talks to a device.
- **Keep the notices.** Ship the kit's `LICENSE` (GPL-3.0-or-later) and `NOTICE`, and link to the kit's source: the release you took. The catalog gives each mod's licence; show it, and keep each mod's notices with it.
- **Leave the engine's files as they are.** The lock file and `verify` are there so you can show your users that the builder is elekloader's. If you change the engine, it is no longer the pinned one.

## The messages

A call is `{ id, call, args, data }`. The worker answers `{ id, log }` for each line while a build runs, then `{ id, ok: true, result }` or `{ id, ok: false, error }`. The client wraps all of this.

| call | args | result |
|---|---|---|
| `init` | `base`, `catalog` (default `catalog.json`) | the protocol, the engine's version, the catalog's revision and counts, the bridge's `info` |
| `add_catalog_mod` | `file` | the catalog's mod, fetched from your site and checked |
| `set_stock` | `name`, with the file's bytes | known by its hash (device, OS), or refused |
| `add_mod` | `name`, with the file's bytes | the owner's own `.elemod`, or why it is refused |
| `remove_mod`, `mods`, `tick`, `check`, `version`, `build`, `info` | as web/bridge.py | as web/bridge.py; `build`'s files carry their bytes |

Cores come only from the catalog, at `init`. A page cannot add a core of its own, but the owner can add a newer core as a mod (`add_mod`).

## The catalog

```json
{
  "schema": 1, "kind": "elekloader-catalog", "revision": "<the commit of elekloader's list, or your own>",
  "cores": [{ "file": "core-2.1.elemod", "sha256": "…", "id": "core", "version": "2.1", "device": "digitakt-mk1",
              "os": "1.53", "license": "GPL-2.0-or-later", "source": { "repo": "irpina/digislicer", "tag": "v2.1" } }],
  "mods": [{ "file": "digimono-0.13b.elemod", "sha256": "…", "id": "digimono", "version": "0.13b", "device": "digitakt-mk1",
             "os": "1.53", "license": "MIT", "title": "Digi Mono", "requires": ["core", "digichain"], "conflicts": [],
             "summary": "…", "on_unit": "…",
             "source": { "repo": "gdeo607/digi1_mods", "commit": "35bacb3…", "path": "elemods/digimono-0.13b.elemod" } }]
}
```

- **What each file says about itself:** `file`, `sha256`, `id`, `version`, `device`, `os`, `license`, `requires` and `conflicts`. `kit.ts feed` reads them from the file with the engine.
- **What a page shows:** `title`, `summary`, `description`, `category`, `author`, `needs_core` (the oldest core the mod links with) and `on_unit` (what has been checked on real hardware).
- **Where the file comes from:** `source` is a GitHub release (`repo`, `tag`) or a commit (`repo`, the whole `commit`, `path`).
- **File names are unique.** A site serves every file beside `catalog.json` under that name.

**Your own entries:**
- Add a mod your forum hosts, in the same shape, pinned to its release or commit.
- Run `sync` and `lock` again.
- Give it a `revision` of your own (your repository's commit, say), so you can tell your catalog from elekloader's.

## Versions

- **The kit's version is elekloader's** (`js/package.json`, `kit.json`).
- **`PROTOCOL`,** in `init`'s reply, changes when a call or a reply changes shape. A site written for protocol 1 should refuse another.
- **The catalog's `schema`** changes when the format does. `parseCatalog` refuses a schema it does not read.
- **A catalog's `revision`** names its list. Keep it apart from the engine's version: a site can update the kit without changing its catalog, and the other way round. Saved selections that name the revision stay valid across engine updates.

## For elekloader's releases

Each release attaches the kit and the catalog. Both are reproducible from the commit:

```bash
python packaging/build_kit.py --out build/kit                   # elekloader-kit-<version>.zip, and its sha256
python packaging/build_web.py --catalog-list web/catalog.json   # the list's files: download each (as pages.yml does)
node js/tools/kit.ts feed --list web/catalog.json --files build/shop --core build/core/core-*.elemod \
     --core-source irpina/elekloader@<tag> --revision $(git rev-parse HEAD) --out build/elekloader-catalog.json
```

- **The curated list** is `web/catalog.json`, the one elekloader's shop used.
- **`feed`** reads every listed file with the engine and refuses one whose sha256 or device is not the list's.
