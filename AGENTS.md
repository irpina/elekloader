# Notes for coding agents

elekloader builds custom firmware for Elektron devices from mods, on the
user's machine, from the stock OS file they supply. Read README.md first.

## If you are adapting or writing a mod

Follow [docs/ADAPTING.md](docs/ADAPTING.md). It has:
- the rules;
- the build, lint and patch commands, with the output each should print;
- a table from each refusal message to its fix;
- a definition of done.

Start from `examples/hello-marker/`. Your loop is:

```bash
python -m elekloader.sdk.build <moddir> --stock <stock.syx>
python -m elekloader.lint <mod.elemod> --stock <stock.syx> --with <core.elemod> --json
python -m elekloader.patch --stock <stock.syx> --mod <core.elemod> --mod <mod.elemod> --out test.syx --version XXXX
```

## If you are changing elekloader itself

| path | what |
|---|---|
| `elekloader/devices/` | everything device-specific: one profile per product, releases by hash |
| `elekloader/formats.py` | one interface over the OS file families (`Device.container`); `load` also takes Elektron's zip |
| `elekloader/syx.py` | the Digitakt mk1's, Digitone mk1's and Digitakt II's family (ELE3, SysEx; the II's sealed with an HMAC): parse, write (only the main OS changes), verify |
| `elekloader/elek.py` | the Octatrack's family (ELEK, legacy SysEx, the ELUP card file): the same |
| `elekloader/elemod.py` | the mod format: shared validation, format 1, the instruction check, `summarize` |
| `elekloader/link.py` | format 2: the linker and its checks |
| `elekloader/patch.py` | the command line; `build()` is what the window calls too |
| `elekloader/gui.py` | the window (Tkinter); `LoaderModel` is its logic without Tk |
| `elekloader/lint.py`, `elekloader/mkmod.py`, `elekloader/sdk/` | tools for mod authors; `sdk/octabam.py` converts octabam's modules |
| `elekloader/codec/`, `elekloader/isa/` | code from digikit (GPL-2.0-or-later): change it only with a round-trip test |
| `mods/core/`, `mods/core-dn1/`, `mods/core-dt2/` | the core mod (the hook bus every format-2 mod needs): one `core.s` (with `settings.s`, `render.s` and `fast.s` where the device uses them), each device's addresses and sites in its `mod.json`, each further OS version's in its `ports` |
| `mods/core-ot/` | the Octatrack's core: its RAM reserve and `.boot`, and from 0.2 its own hook bus (`bus.s`, with the draw site's gate in `gate.s`) |
| `packaging/`, `.github/workflows/windows-build.yml`, `macos-build.yml` | the apps: `elekloader-<version>-windows.exe`, and `elekloader-<version>-macos.dmg` (signed and notarized), with core built in (`elekloader/bundled`, never committed) |
| `js/` | the engine in TypeScript (GPL-3.0-or-later; js/README.md): the formats, the checks, the linker, the build and the web bridge, ported from the Python and matching it byte for byte, messages included (`js/tools/parity.ts` checks with your stock files) |
| `js/src/kit/`, `js/tools/kit.ts`, `js/examples/minimal/`, `packaging/build_kit.py`, `.github/workflows/kit-build.yml` | the kit for websites (docs/INTEGRATING.md): the builder worker, the page's client, the catalog format and elekloader's curated catalog, the lock and its checks. It names no website |
| `web/`, `packaging/build_web.py`, `.github/workflows/pages.yml` | the web page (GitHub Pages): elekloader in Pyodide, in a worker; `bridge.py` is its only Python, a thin layer over `gui.LoaderModel` and `patch`; `catalog.json` is its mod shop's curated list (docs/WEB.md). Everything it loads comes from the site itself |

Tests:

```bash
python tests/test_units.py                                   # always
ELEKLOADER_STOCK=... ELEKLOADER_MODS=... python tests/test_link.py
ELEKLOADER_STOCK=... ELEKLOADER_MODS=... python tests/test_sdk.py    # the example needs the cross compiler
ELEKLOADER_STOCK=... ELEKLOADER_BUNDLE=... ELEKLOADER_CTOOL_SYX=... python tests/test_patcher.py
ELEKLOADER_OT_SYX=... ELEKLOADER_OT_BIN=... python tests/test_octatrack.py
ELEKLOADER_OT_SYX=... ELEKLOADER_OCTABAM=... python tests/test_octabam.py
ELEKLOADER_DN_SYX=... python tests/test_digitone.py
ELEKLOADER_DT2_SYX=... python tests/test_digitakt2.py
ELEKLOADER_RELEASES=<folder of stock files> python tests/test_releases.py   # every known release, and the cores for it
ELEKLOADER_STOCK=... ELEKLOADER_OT_SYX=... ELEKLOADER_MODS=... python tests/test_gui.py   # the window, hidden (Tk)
python packaging/build_web.py --pyodide pyodide-core-<v>.tar.bz2 --core core-*.elemod --out build/site
node tests/test_web.mjs build/site                           # the web page's engine, in Pyodide
```

A test whose files are not given is skipped, not passed. Say which ran.

Rules:
- **Never commit firmware.** That means `.syx` files, extracted sections,
  `.bin` images, built `.elemod` files, or anything derived from a stock
  OS. `.gitignore` covers the usual names; check `git status` anyway.
- **Never weaken a check to make something pass.** `syx.verify` and the
  checks in `elemod`/`link` are the user's protection: the bootloader must
  stay stock, and mods must not collide. If a check refuses something
  legitimate, fix the check narrowly and add a test for both sides.
- **Device-specific facts belong in `devices/`**, not in the code paths.
  A new device needs its profile, a writer that reproduces its stock files
  byte for byte, and tests (docs/DEVICES.md).
- **The TypeScript engine (js/) changes with the Python.** A change to what
  the Python accepts, writes or says needs the same change in its js/ port,
  and `node --test "js/test/*.test.ts"` and the parity run (js/README.md) to
  pass.
- **The kit stays site-agnostic.** Nothing in js/src/kit names a website,
  its pages or its accounts. A change to a call or a reply raises `PROTOCOL`
  (js/src/kit/protocol.ts); a change to the catalog format raises
  `CATALOG_SCHEMA`. docs/INTEGRATING.md changes with them.
- **A change to the file format** needs docs/FORMAT.md, docs/ADAPTING.md and
  tests updated with it. Keep reading older files: the legacy `.dtmod`
  extension and `"dtmod"` key are still accepted.
- **The writer must stay byte-exact.** With the maintainers' test files,
  `test_writer_matches_c_tool` and `test_writer_no_change_is_stock` must
  pass.
- **The web page stays on its own site.** It loads nothing from anywhere
  else (no CDN, fonts, analytics or package downloads), sends the user's
  files nowhere, and only offers downloads: no Web MIDI or USB. Its Python
  goes through `elekloader` unchanged. The site never holds firmware or a
  build; the only mods on it are the cores and the shop's
  (`web/catalog.json`), each from its author's release, pinned by sha256,
  under a licence that allows passing it on.

Done means all of these:
- the tests that could run pass;
- the docs match the code;
- `git status` shows no firmware.
