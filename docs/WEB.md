# elekloader in the browser

<https://irpina.github.io/elekloader/> is elekloader's patcher as a static
web page. You pick mods from its shop or add your own `.elemod` files, drop
in your stock OS file, tick mods, and download the patched `.syx` (and, for
the Octatrack, the `.bin`), with the build manifest. The build runs in the
page. Nothing is uploaded, and the site hosts no firmware.

## How it works

```
index.html + app.js  (the page: the shop, the list, the check, the build, the downloads)
      |  postMessage: your files' bytes, ticks; results back
worker.js            (a module worker, so the page never blocks)
      |
Pyodide              (CPython 3.14 compiled to WebAssembly, served by this site)
      |
bridge.py            (a thin layer over elekloader, on Pyodide's in-memory file system)
      |
elekloader           (the package, unchanged: elekloader.zip)
```

The page runs elekloader's own code, and the logic is the desktop window's:
- the stock file goes to `gui.LoaderModel.set_stock`: it is recognised by its
  hash, or refused with the same words;
- the mod list, the details and each mod's status come from
  `LoaderModel.describe`;
- the live check, as you tick, is `LoaderModel.check`, which runs the
  linker's checks on the stock image it has already loaded;
- ticking a mod ticks what it requires (`gui.with_requirements`);
- the build is `patch.build` then `patch.save`, the same calls as the
  command line and the window. They verify every output before anything is
  offered for download.

Your files are written under `/work` in Pyodide's in-memory file system. It
disappears with the tab. The downloads are made in the page from the bytes
the worker returns (`blob:` URLs).

The page shows the device's recovery text before it lets you download.
Flash the file yourself, as with any OS update ([README](../README.md#flash-it)).
The page never talks to a device: it has no Web MIDI and no USB access.

## The mod shop

**or browse the mod shop**, next to **+ Add mods**, opens a shop of curated
mods. **Select your device** shows the mods made for it (or every device's,
with "All"); once you have dropped in a stock file, the shop opens on its
device. A device you pick before that says which stock OS file it needs. Each card shows the mod's
title, version, author, licence and what it changes (from the mod file
itself), with a one-line summary from the catalog. **Add to build** puts
the mod in your mods and ticks it with what it requires.

- **The list** is `web/catalog.json`, committed and edited by hand. Each
  item names a file of a GitHub release (`repo`, `tag`, `file`), its
  `sha256`, its `device`, and optionally `needs_core` (the oldest core
  version it links with), a `summary`, and a `license` when the file names
  none. `"kind": "core"` marks a core the listed mods need: it joins the
  site's cores.
- **The files** are not committed. The pages workflow downloads each from
  its author's release, and `build_web.py` puts it on the site only if it
  is the file the catalog pins (by sha256), made for the device the catalog
  says, and under a licence that allows passing it on (`SHOP_LICENCES`). A
  file that cannot be downloaded (a draft release) is listed as not
  released yet.
- **In the page,** a mod from the shop comes from this site like everything
  else, and the worker checks it against the catalog's sha256 again before
  adding it. If it needs a newer core than the one ticked (`needs_core`),
  the newest core that fits is ticked in its place, and the page says so.

To add a mod to the shop, publish its `.elemod` in a GitHub release, add an
item to `web/catalog.json` with the asset's sha256 (the release page shows
it, or `gh release view --json assets`), and merge: the next deploy takes
it.

## What stays private, and how

- **Nothing is sent anywhere.** No request ever carries your files. The
  page fetches only its own files (the page, the worker, Pyodide, the
  elekloader package, the cores, the shop's list and its mods), all from
  this site. There are no
  analytics, no fonts or scripts from elsewhere, and no server side.
- **The page** carries a Content Security Policy in a `<meta>` tag:
  `default-src 'self'`, scripts from this site only, plus
  `'wasm-unsafe-eval'` (WebAssembly). GitHub Pages cannot send CSP headers,
  so the tag is all there is.
- **The worker** is not covered by a `<meta>` CSP, and that is by the
  standard: a worker takes its policy from its own response's headers, and
  Pages sends none. So `worker.js` keeps itself to the site. Before
  anything loads, it replaces `fetch` and `XMLHttpRequest.open` with
  versions that refuse any URL off this site, and it removes `WebSocket`,
  `EventSource`, `WebTransport` and `RTCPeerConnection`. Pyodide is loaded
  with `indexURL` and `packageBaseUrl` both set to `./pyodide/`, so it has no
  CDN to fall back on. Nothing asks it for a package, and only Pyodide's core
  files are on the site.
- **Kept in this browser:** your profiles, the last version field per
  device, and your display choices are kept in `localStorage`. Only if you
  tick "Keep my stock file and mods in this browser" are the stock file and
  the mods you added kept, in IndexedDB. "Forget them" deletes them. Neither
  leaves the browser.

## What is on the site

`packaging/build_web.py` assembles it, about 14 MB in 20 or so files:

| path | what |
|---|---|
| `index.html`, `style.css`, `app.js`, `worker.js`, `bridge.py` | `web/`, as committed |
| `elekloader.zip` | the elekloader package, exactly as the commit has it (`git archive HEAD elekloader`), stored, sorted, fixed dates: its sha256 follows from the commit |
| `core/*.elemod`, `core/index.json` | the cores of the latest release, and the cores the catalog lists, with their sha256 (the worker checks each) |
| `shop/*.elemod`, `shop/index.json` | the shop: the catalog's mods, from their authors' releases, with what each file says about itself |
| `pyodide/` | five files from Pyodide's core tarball (`pyodide.mjs`, `pyodide.asm.mjs`, `pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json`), and `NOTICE.txt` with their licences |
| `build.json` | the commit, the package's sha256 and git tree, the release the cores come from and whether the package is that release's, Pyodide's version, every file's sha256 |
| `LICENSE.txt`, `NOTICE.txt` | elekloader's |

The Pyodide release is pinned by version and sha256 in `build_web.py`
(`PYODIDE_VERSION`, `PYODIDE_SHA256`). To move to a newer one, change both,
then build and run the checks below.

## The workflow

`.github/workflows/pages.yml` runs on every push to main, and by hand. It:
1. runs `tests/test_units.py`;
2. takes the `core-*.elemod` files of the latest release
   (`gh release download`), and fetches that release's tag;
3. downloads the shop's files, each from its author's release (one it
   cannot get is a warning, and the shop lists it as not released yet);
4. downloads the pinned Pyodide core tarball;
5. assembles the site (`build_web.py` checks the tarball's sha256, and
   the shop's files against the catalog);
6. runs `tests/test_web.mjs` on the assembled site: the unit tests under
   Pyodide with the site's own `elekloader.zip`, the bridge loaded as the
   worker loads it, and every shop file through the bridge;
7. deploys it with `actions/upload-pages-artifact` and `actions/deploy-pages`.

No firmware reaches the workflow. Pages has to be on, with **GitHub
Actions** as its source (Settings > Pages). When a new release carries its
cores, run the workflow by hand to put them on the site.

## Build and try it locally

```bash
curl -fLO "$(python packaging/build_web.py --pyodide-url)"
python packaging/build_web.py --pyodide pyodide-core-314.0.7.tar.bz2 --core core-2.1.elemod core-dn1-2.0a.elemod --out build/site
node tests/test_web.mjs build/site
python -m http.server --directory build/site 8000      # then open http://localhost:8000
```

The page needs module workers and WebAssembly, which current Chrome, Edge,
Firefox and Safari all have; it has been tested in Chromium. It also needs
a secure context (https, or localhost).

## How long it takes

Measured on one Windows 11 desktop PC, in Chromium, from a local server.
A build is `patch.build` plus `patch.save`; each figure is the median of
three runs. CPython 3.14 is shown for comparison:

| | the page | CPython | of which packing (page / CPython) |
|---|---|---|---|
| loading the engine | 2.7 to 3.9 s | | |
| Digitakt mk1: core 2.1 + digislicer 2.0 | 11.9 s | 7.3 s | 6.2 s / 3.9 s |
| Digitone mk1: core-dn1 2.0a | 13.3 s | 7.7 s | 6.7 s / 4.1 s |
| Octatrack: core 0.1 + tuner | 5.0 s | 2.9 s | 2.7 s / 1.6 s |

The page downloads 13.2 MB the first time: Pyodide's WebAssembly runtime
(9.6 MB) and standard library (2.5 MB) are most of it, and gzip brings the
whole site to about 6.5 MB where the server compresses. The browser caches
it after that. Packing the main OS (aplib, pure Python) is about half of
every build. A build in the page takes about 1.6 to 1.7 times as long as in
CPython.
