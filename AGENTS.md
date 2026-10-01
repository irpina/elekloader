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
| `elekloader/syx.py` | the Digitakt mk1's and Digitone mk1's family (ELE3, SysEx): parse, write (only the main OS changes), verify |
| `elekloader/elek.py` | the Octatrack's family (ELEK, legacy SysEx, the ELUP card file): the same |
| `elekloader/elemod.py` | the mod format: shared validation, format 1, the instruction check, `summarize` |
| `elekloader/link.py` | format 2: the linker and its checks |
| `elekloader/patch.py` | the command line; `build()` is what the window calls too |
| `elekloader/gui.py` | the window (Tkinter); `LoaderModel` is its logic without Tk |
| `elekloader/lint.py`, `elekloader/mkmod.py`, `elekloader/sdk/` | tools for mod authors; `sdk/octabam.py` converts octabam's modules |
| `elekloader/codec/`, `elekloader/isa/` | code from digikit (GPL-2.0-or-later): change it only with a round-trip test |
| `mods/core/`, `mods/core-dn1/` | the core mod (the hook bus every format-2 mod needs): one `core.s`, each device's addresses and sites in its `mod.json` |
| `mods/core-ot/` | the Octatrack's core: a boot copier only (its RAM reserve and `.boot`), no hook bus |
| `packaging/`, `.github/workflows/windows-build.yml`, `macos-build.yml` | the apps: `elekloader-<version>-windows.exe`, and `elekloader-<version>-macos.dmg` (signed and notarized), with core built in (`elekloader/bundled`, never committed) |

Tests:

```bash
python tests/test_units.py                                   # always
ELEKLOADER_STOCK=... ELEKLOADER_MODS=... python tests/test_link.py
ELEKLOADER_STOCK=... ELEKLOADER_MODS=... python tests/test_sdk.py    # the example needs the cross compiler
ELEKLOADER_STOCK=... ELEKLOADER_BUNDLE=... ELEKLOADER_CTOOL_SYX=... python tests/test_patcher.py
ELEKLOADER_OT_SYX=... ELEKLOADER_OT_BIN=... python tests/test_octatrack.py
ELEKLOADER_OT_SYX=... ELEKLOADER_OCTABAM=... python tests/test_octabam.py
ELEKLOADER_DN_SYX=... python tests/test_digitone.py
ELEKLOADER_STOCK=... ELEKLOADER_OT_SYX=... ELEKLOADER_MODS=... python tests/test_gui.py   # the window, hidden (Tk)
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
- **A change to the file format** needs docs/FORMAT.md, docs/ADAPTING.md and
  tests updated with it. Keep reading older files: the legacy `.dtmod`
  extension and `"dtmod"` key are still accepted.
- **The writer must stay byte-exact.** With the maintainers' test files,
  `test_writer_matches_c_tool` and `test_writer_no_change_is_stock` must
  pass.

Done means all of these:
- the tests that could run pass;
- the docs match the code;
- `git status` shows no firmware.
