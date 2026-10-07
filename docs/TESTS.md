[elekloader docs](README.md) › Tests

# Tests

Each suite runs with plain Python (or Node for the TypeScript engine and the
page) and takes its input files from environment variables. A test whose
input files are not given is skipped, not passed: say which ran. Firmware
files never go in this repository.

```bash
python tests/test_units.py        # needs nothing
ELEKLOADER_STOCK=Digitakt_OS1.53.syx ELEKLOADER_MODS=path/to/mods python tests/test_link.py
ELEKLOADER_STOCK=... ELEKLOADER_STOCK_154=Digitakt_OS1.54.syx ELEKLOADER_MODS=... python tests/test_sdk.py   # the example needs the cross compiler
ELEKLOADER_RELEASES=folder/of/stock/files python tests/test_releases.py   # every known release, and its cores
ELEKLOADER_STOCK=... ELEKLOADER_BUNDLE=bundle.elemod ELEKLOADER_CTOOL_SYX=its-build.syx python tests/test_patcher.py
ELEKLOADER_OT_SYX=OCTATRACK_OS1.40C.syx ELEKLOADER_OT_BIN=OCTATRACK_OS1.40C.bin python tests/test_octatrack.py
ELEKLOADER_OT_SYX=... ELEKLOADER_OCTABAM=path/to/octabam python tests/test_octabam.py   # octabam optional
ELEKLOADER_DN_SYX=Digitone_and_Digitone_Keys_OS1.43.syx python tests/test_digitone.py
ELEKLOADER_DT2_SYX=Digitakt_II_OS1.17.syx python tests/test_digitakt2.py
ELEKLOADER_CATALOG_DIR=folder/of/catalog/files ELEKLOADER_STOCK=... python tests/test_catalog_link.py   # the catalog against core 3.0
ELEKLOADER_STOCK=... ELEKLOADER_STOCK_154=... ELEKLOADER_OT_SYX=... ELEKLOADER_MODS=... python tests/test_gui.py   # the window, hidden (Tk)
node tests/test_web.mjs build/site   # the web page's engine, in Pyodide (packaging/build_web.py first)
```

More inputs some suites take:
- `ELEKLOADER_CROSS`: the cross toolchain's prefix, when it is not
  `m68k-linux-gnu-` (Homebrew's is `m68k-elf-`). The suites that build code
  need it on the path: test_sdk, test_releases, test_catalog_link,
  test_octatrack, test_octabam and test_digitakt2.
- `ELEKLOADER_DN_SYX` and `ELEKLOADER_DN_SYX_144` (the Digitone's 1.43 and
  1.44 files) for test_sdk's Digitone core and its 1.44 port;
  `ELEKLOADER_CORE_21` (a released `core-2.1.elemod`) for its core 3.0
  checks.
- `ELEKLOADER_DSP_ASM` (octabam's `dsp_asm`) for test_octatrack's and
  test_octabam's DSP code.
- `ELEKLOADER_DN_MODS`, a folder of Digitone mods, for test_gui.

The TypeScript engine has its own tests, which need no firmware, and a
parity run that compares it with the Python on your own files
([js/README.md](../js/README.md)):

```bash
cd js && node --test "test/*.test.ts"
```
