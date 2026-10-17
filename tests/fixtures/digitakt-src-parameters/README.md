# Silent two-page SRC test

PARAM exposes P1–P8 and P9–P15 on two SRC pages (page 2's eighth knob is
blank: sound slot 0 is kept for a machine's id). All controls range from
0 to 127 and default to zero. It has no audio-render callback, oscillator,
tick handler or custom graphics; only the shared parameter paths run.

It uses experimental machine ID 120 on Digitakt mk1 OS 1.53/1.54. Build
with this branch's core and machine-pages. For OS 1.53:

```sh
export ELEKLOADER_STOCK=/absolute/path/to/Digitakt_OS1.53.syx
# Set ELEKLOADER_CROSS if your installed toolchain has another prefix.
mise exec python@3.12.13 -- python -m elekloader.sdk.build mods/core --out build/src-poc
mise exec python@3.12.13 -- python -m elekloader.sdk.build mods/machine-pages --out build/src-poc
mise exec python@3.12.13 -- python -m elekloader.sdk.build tests/fixtures/digitakt-src-parameters --out build/src-poc
mise exec python@3.12.13 -- python -m elekloader.lint build/src-poc/src-parameters-test-0.1.elemod \
  --stock "$ELEKLOADER_STOCK" --with build/src-poc/core-4.0.elemod \
  --with build/src-poc/machine-pages-1.2.elemod --json
mise exec python@3.12.13 -- python -m elekloader.patch --stock "$ELEKLOADER_STOCK" \
  --mod build/src-poc/core-4.0.elemod --mod build/src-poc/machine-pages-1.2.elemod \
  --mod build/src-poc/src-parameters-test-0.1.elemod --out build/src-poc/test.syx --version PRAM
```

For 1.54, rebuild against its stock file; ported mod filenames add `-os1.54`.
The [plan](https://github.com/simonjohansson/elekloader/blob/codex/digitakt-src-notes/docs/DIGITAKT-SRC-PLAN.md)
and [findings](https://github.com/simonjohansson/elekloader/blob/codex/digitakt-src-notes/docs/DIGITAKT-SRC-FINDINGS.md)
live on the separate notes branch.

Press SRC to switch pages. Test independent edits, page copy/clear/paste,
parameter locks, both LFO destinations and sound/project save/load.
Processed lock/LFO values can be read with the USB diagnostics channel;
the controls intentionally have no audible effect. Normal parameter
processing still has a cost, so this is not a zero-load firmware.
