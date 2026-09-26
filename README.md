# elekloader

A mod loader for Elektron firmware. You pick mods and supply the stock OS
file Elektron publishes for your device. elekloader builds a custom OS
file on your own machine, and you flash it the way you flash any OS update.

- **Nothing from Elektron is distributed.** A mod (`.dtmod`) carries only
  its author's bytes plus hashes of the stock bytes it expects. Every build
  starts from your own stock file, recognised by its hash.
- **The bootloader is never touched.** Mods can only change the main OS:
  the file format has no way to say anything else. Each output file is
  re-read and verified before it is written. So the stock OS file always
  recovers the device.
- **Mods are checked against each other before anything is built.** Two
  mods may not touch the same bytes, claim the same memory or the same
  named resource, or leave a requirement unmet.

| Device | OS | Status |
|---|---|---|
| Digitakt (mk1) | 1.53 | supported |
| other Elektron devices | | planned: see [docs/DEVICES.md](docs/DEVICES.md) |

## Running it

Python 3.9 or newer, nothing else to install.

```bash
python -m elekloader                        # the window
python -m elekloader.patch --stock Digitakt_OS1.53.syx --mod a.dtmod --mod b.dtmod --out custom.syx --version 2.0a
python -m elekloader.patch --stock Digitakt_OS1.53.syx --mod a.dtmod --check
```

With `pip install .` the same commands are `elekloader` and `elekpatch`.

The window works like a game's mod manager:
- **The mod list.** Tick mods to enable them. Each shows its status as you
  go: Enabled, Conflict, Needs another mod, or made for other firmware.
- **The details pane.** Each mod's description, every change it makes
  (patch sites, the events it handles, its memory) and what it requires.
- **Install from file**, **profiles**, and the memory budgets.
- **Build firmware.** It builds, verifies and saves the `.syx`, and shows
  its sha256 and the verification results.

Your mod library, profiles and the stock file you chose last are kept in
`%APPDATA%\elekloader` (Windows) or `~/.elekloader`.

## What a build guarantees

The output is refused unless every one of these holds:

- It is your stock file with only the main OS section changed. The other
  sections, bootloader included, are byte for byte stock. The header
  differs only in its 4-character version field; the framing only in its
  message count.
- Every message checksum, counter and the content checksum are right, and
  the container fits the device's flash budget.
- The main OS unpacks to exactly the patched image, simulated the way the
  bootloader does it: in place, over its own staged copy.

For the Digitakt mk1, the writer produces the same bytes as
elektron-firmware-tool when given the same main OS stream.

## Mods

This repository is the loader. Mods are built elsewhere and installed from
their `.dtmod` files. [docs/FORMAT.md](docs/FORMAT.md) describes both kinds:

- **format 1**: a whole custom build as one file;
- **format 2**: separate, linkable mods. A `core` mod provides a hook
  bus; other mods subscribe to its events and add entries to each other's
  tables. The loader's linker places them, resolves their symbols and
  checks them.

## Tests

```bash
python tests/test_units.py        # needs nothing
ELEKLOADER_STOCK=Digitakt_OS1.53.syx ELEKLOADER_MODS=path/to/mods python tests/test_link.py
ELEKLOADER_STOCK=... ELEKLOADER_BUNDLE=bundle.dtmod ELEKLOADER_CTOOL_SYX=its-build.syx python tests/test_patcher.py
```

A test whose input files are not given is skipped, not passed. Firmware
files never go in this repository.

## Licence

GPL-2.0. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for the code that
comes from digikit and for the credits. elekloader is not affiliated with
Elektron. Flashing custom firmware is at your own risk.
