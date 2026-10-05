# elekloader in the browser

<https://irpina.github.io/elekloader/> builds custom firmware in your browser:
- **your stock OS file:** the one Elektron publishes for your device;
- **your mods:** the `.elemod` files you have;
- **out:** the patched `.syx` (and, for the Octatrack, the `.bin`), with the build manifest.

The build runs in the page. Nothing is uploaded, and the site hosts no firmware and no mods: the mods are on [Modwerk](https://modwerk.app/), and you bring the files.

## The page

One view, in steps:
- **Before a stock file is in**, the page opens with what it does. It also says where the files come from: mods from Modwerk, and the stock OS from Elektron's download page for each device.
- **01 Your stock OS file:** a drop zone that also opens a file chooser. It takes a `.syx`, the Octatrack's `.bin`, or Elektron's `.zip` as you downloaded it. A file that is not a stock OS gets a message naming the files the page knows.
- **02 Your mods:**
  - **The list:** every `.elemod` you added, and the site's cores, built in. The cores come from elekloader's latest release, one per device and OS.
  - **Adding:** a drop zone for your `.elemod` files. A `.elemod` dropped anywhere on the page is added too.
  - **Ticking** a mod ticks what it requires (the core). Of several files with one id, the last by name is taken: a newer core you add is preferred to the site's.
  - **The details:** each mod's description, what it needs, its memory and its patch sites.
  - **Profiles:** the profile menu.
- **03 Check:** the live check, as you tick: conflicts, the load order, the RAM and fast SRAM the mods take.
- **04 Build:** the OS version the unit will show, the file name, and Build firmware, with its log.
- **05 Your firmware:** what was built and verified, the device's recovery text, and the downloads once you confirm you know how to get back to stock.

Around them:
- **The sidebar:** your profiles.
  - A profile is one stock OS (its device, OS version and file) and the mods you tick for it. Each shows its stock OS under its name and how many mods it has ticked.
  - Picking one switches both. Its stock file comes back from this visit or from this browser (if you keep files here), or the page asks for it by name.
  - **+** makes a new profile: a name, then either the stock OS that is in now (empty, or with the mods ticked now) or another file you drop in next.
  - Your first stock file makes the first profile, "Default". A stock file for another OS goes to the profile that has it, or makes a new one: each profile keeps its own.
  - Delete, in step 02, deletes the profile in use (its mods stay added).
- **The top bar** shows the profile and stock OS in use, and links to Modwerk.
- **The sidebar's foot** shows the engine, and opens About (licences, how to recover).
- **On a phone** the page is one column, with the profiles at its end.

## How it works

```
index.html + app.js  (the page: your stock file, your mods, the check, the build, the downloads)
      |  postMessage: your files' bytes, ticks; results back
worker.js            (a module worker, so the page never blocks)
      |
engine/              (elekloader's TypeScript engine, js/, as plain JavaScript)
```

The engine is elekloader's own, ported from the Python and matching it byte for byte: the same `.syx`, `.bin`, manifest and map, refusals and messages. `js/tools/parity.ts` and `bridge_parity.ts` check that with your own files; js/README.md has how.

The logic is the desktop window's:
- **The stock file** goes to `LoaderModel.setStock`. It is recognised by its hash, or refused with the same words.
- **The mod list, the details and each mod's status** come from `describe`.
- **The live check**, as you tick, is `check`: the linker's checks on the stock image the engine has already loaded.
- **Ticking a mod** ticks what it requires (`with_requirements`).
- **The build** is `build` then `save`, as the command line does. Every output is verified before anything is offered for download.

The worker talks to the engine through `js/src/bridge.ts`, whose calls are `web/bridge.py`'s. That file is no longer on the site: it is the reference the TypeScript bridge is compared with.

Your files stay in the worker's memory, under `/work`, and disappear with the tab. The downloads are made in the page from the bytes the worker returns (`blob:` URLs).

The page shows the device's recovery text before it lets you download. Flash the file yourself, as with any OS update ([README](../README.md#flash-it)). The page never talks to a device: it has no Web MIDI and no USB access.

## What stays private, and how

- **Nothing is sent anywhere.** No request ever carries your files. The page fetches only its own files (the page, the worker, the engine, the cores), all from this site. There are no analytics, no fonts or scripts from elsewhere, and no server side.
- **The page** carries a Content Security Policy in a `<meta>` tag: `default-src 'self'`, scripts from this site only. GitHub Pages cannot send CSP headers, so the tag is all there is.
- **The worker** is not covered by a `<meta>` CSP, and that is by the standard: a worker takes its policy from its own response's headers, and Pages sends none. So `worker.js` keeps itself to the site:
  - before anything loads, it replaces `fetch` and `XMLHttpRequest.open` with versions that refuse any URL off this site;
  - it removes `WebSocket`, `EventSource`, `WebTransport` and `RTCPeerConnection`.
- **Kept in this browser:**
  - Always, in `localStorage`: your profiles (each one's name, its stock OS by sha256, and its mod file names), the last version field per device, and your display choices.
  - Only if you tick "Keep my stock file and mods in this browser": the stock files (one per profile's OS) and the mods you added, in IndexedDB. "Forget them" deletes them.
  - Neither leaves the browser.

## What is on the site

`packaging/build_web.py` assembles it, about 380 KB in 33 files:

| path | what |
|---|---|
| `index.html`, `style.css`, `app.js`, `worker.js` | `web/`, as committed |
| `engine/*.js`, `engine/LICENSE.txt` | the engine: `js/` exactly as the commit has it (`git archive HEAD js`), made plain JavaScript by `js/tools/build.ts` (Node's own type stripping), and its licence (GPL-3.0-or-later) |
| `core/*.elemod`, `core/index.json` | the cores of the latest release, with their sha256 (the worker checks each) |
| `build.json` | the commit, the engine's sha256 and git tree, the Node that built it, the release the cores come from and whether the engine is that release's, every file's sha256 |
| `LICENSE.txt`, `NOTICE.txt` | elekloader's |

## The workflow

`.github/workflows/pages.yml` runs on every push to main, and by hand. It:
1. runs `tests/test_units.py` and the engine's tests (`node --test "js/test/*.test.ts"`);
2. takes the `core-*.elemod` files of the latest release (`gh release download`), and fetches that release's tag;
3. assembles the site;
4. runs `tests/test_web.mjs` on the assembled site:
   - the engine loaded as the worker loads it, with every core;
   - the refusals;
   - that the site carries no shop and no Pyodide;
5. deploys it with `actions/upload-pages-artifact` and `actions/deploy-pages`.

No firmware reaches the workflow. Pages has to be on, with **GitHub Actions** as its source (Settings > Pages). When a new release carries its cores, run the workflow by hand to put them on the site.

## Build and try it locally

```bash
python packaging/build_web.py --core core-*.elemod --out build/site   # the release's: one per device and OS
node tests/test_web.mjs build/site
python -m http.server --directory build/site 8000      # then open http://localhost:8000
```

Building needs Node 22.18 or newer. The page needs module workers, which current Chrome, Edge, Firefox and Safari all have; it has been tested in Chromium. It also needs a secure context (https, or localhost).

## How long it takes

Measured on one Windows 11 desktop PC, Node 24 (the page's engine; Chromium gives the same within a few per cent). A build is `build` plus `save`, the median of three runs. The page as it was, with Python in Pyodide, is shown for comparison:

| | now | in Pyodide |
|---|---|---|
| loading the engine | 30 to 40 ms | 2.7 to 3.9 s |
| Digitakt mk1: core 2.1 + digislicer 2.0 | 0.43 s | 11.9 s |
| Digitone mk1: core-dn1 2.0a | 0.44 s | 13.3 s |
| Octatrack: core 0.1 + tuner | 0.23 s | 5.0 s |

The page downloads about 380 KB the first time, where it downloaded 13.2 MB with Pyodide. Packing the main OS, which was half of every build, now takes a tenth of a second or two.
