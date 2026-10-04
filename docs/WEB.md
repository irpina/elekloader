# elekloader in the browser

<https://irpina.github.io/elekloader/> is elekloader's patcher as a static
web page. You pick mods from its library or add your own `.elemod` files,
drop in your stock OS file, tick mods, and download the patched `.syx` (and,
for the Octatrack, the `.bin`), with the build manifest. The build runs in
the page. Nothing is uploaded, and the site hosts no firmware.

The page is an app with two views:
- **Mods** (`#library`), where the page opens. Until a stock file is in, it
  starts with **Get started**: what the page does, and three steps.
  1. **Pick your device**: a tile per device, with its OS versions and how
     many mods it has. It also filters the cards.
  2. **Add its stock OS file**: a link to the device's page on Elektron's
     site, for its newest OS, and a drop zone. A file that is not a stock OS
     gets a message naming the files the page knows.
  3. **Add mods, then build**, with a link to how to flash and how to go
     back.

  Once a stock file is in, the head shows the device and OS, and a strip of
  what is done and what is next: **✓ Stock OS**, then **+ Add** a mod (or
  **✓ n mods in your build**), then **Build your firmware**. Below are the
  mods, every mod as a card on a shelf per kind (Sampling, Performance, ...;
  your own files last). The sidebar's Categories, the device chips and the search
  filter them, and Sort orders them.
- **Build** (`#build`): your stock OS file, your mods (the list, the profile,
  the details), the check, and Build firmware, then the downloads. Under the
  list are the two ways to add a mod: **Add from the library**, and **Add
  your own `.elemod`**, a drop zone that also opens a file chooser. (A
  `.elemod` dropped anywhere on the page is added too.)

Around them:
- **The sidebar**: the two views, the categories of mod with their counts,
  and your profiles.
- **Profiles**: a profile is one stock OS (its device, OS version and file)
  and the mods you tick for it. Each shows its stock OS under its name and
  how many mods it has ticked. Picking one switches both: its stock file
  comes back from this visit or from this browser (if you keep files here),
  or the page asks for it by name. **+** makes a new profile: a name, then
  the stock OS that is in now (empty, or with the mods ticked now) or
  another file you drop in next. Your first stock file makes the first
  profile, "Default". A stock file for another OS goes to the profile that
  has it, or makes a new one: each profile keeps its own. The Build view's
  Profile menu switches too, and Delete deletes the profile in use (its mods
  stay added).
- **Its foot** shows the build engine, and opens About (licences, how to
  recover).
- **On a phone** the page is one column (the profiles at its end), and a tab
  bar switches between Mods, Build and About.

## How it works

```
index.html + app.js  (the page: the library, your mods, the check, the build, the downloads)
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

## The mod shop: the library's cards

The library shows the shop's curated mods, and the `.elemod` files you added
yourself (the "Your files" shelf). Once you have dropped in a stock file, it
opens on that file's device. A device you pick before that says which stock
OS file it needs.

Each card's cover is the mod's name over line art, in its kind's colour.
- **Keywords pick the art.** `MOTIFS` in `app.js` matches the mod's id and title,
  and the first match wins:
  - a tuner draws a needle; metallic percussion, a struck metal's spectrum;
    a synth, an FM wave; a quantizer, a line snapped to steps; pitch tables,
    their steps around a zero line, with a strum's ADD steps hollow; REPITCH,
    a record;
  - a jump, steps and an arc; a recorder, a loop; scenes, a crossfader; CCs,
    knobs;
  - USB audio, one meter per channel (and the inputs, for USB IO); USB, the
    trident; MIDI, a DIN socket.
- **The motif also nudges the hue**, so one shelf still varies.
- **No keyword:** the art is drawn for the mod's kind (a sliced waveform for
  Sampling, a level under a ceiling for Performance).
- **Variation:** each drawing is varied by the mod's id, so two mods with one
  motif differ. Below it are the mod's title, version, device and OS
versions, the summary from the catalog, and its patch sites. The cover and
**Details** open a sheet with its author, kind and licence, what it changes,
and the files with their sha256.

- **+ Add** puts the mod in your mods and ticks it with what it requires.
- **✓ In build** marks a mod in your build; a click takes it out of the
  build, and it stays in your mods.
- **Remove** takes it out of your mods.

A mod built for several OS versions of a device (its files for 1.53 and
1.54, say) is one card, which lists the OS versions it has. With a stock
file dropped in, the card adds the file for that OS; before one, it adds
every OS's file, and the list shows the one that fits once you drop in your
stock file.

- **The list** is `web/catalog.json`, committed and edited by hand. Each
  item names a file of a GitHub release (`repo`, `tag`, `file`), its
  `sha256`, its `device`, and optionally:
  - `needs_core`: the oldest core version it links with;
  - a `summary`;
  - `on_unit`: what has been checked on real hardware. The details sheet shows
    it under "On a unit"; the card does not.
  - a `license`, when the file names none. `"kind": "core"` marks a core the listed mods need: it joins the
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
it. A mod with a file for each OS version gets an item per file; the page
shows them as one card (the same repository, mod, version and device).

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
- **Kept in this browser:** your profiles (each one's name, stock OS by
  sha256, and mod file names), the last version field per device, and your
  display choices are kept in `localStorage`. Only if you tick "Keep my stock
  file and mods in this browser" are the stock files (one per profile's OS)
  and the mods you added kept, in IndexedDB. "Forget them" deletes them.
  Neither leaves the browser. Profiles from before (sets of mods per device,
  with no stock OS) become profiles that take the next stock file for their
  device.

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
python packaging/build_web.py --pyodide pyodide-core-314.0.7.tar.bz2 --core core-*.elemod --out build/site   # the release's: one per device and OS
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
