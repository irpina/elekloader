# elekloader

A mod loader for Elektron firmware. You pick mods and supply the stock OS
file Elektron publishes for your device. elekloader builds a custom OS
file on your own machine, and you flash it the way you flash any OS update.

- **Nothing from Elektron is distributed.** A mod (`.elemod`) carries only
  its author's bytes, the short instruction fragments needed to hook the OS,
  and hashes of the stock bytes it expects. Every build starts from your own
  stock file, recognised by its hash.
- **The bootloader is never touched.** Mods can only change the main OS:
  the file format has no way to say anything else. Each output file is
  re-read and verified before it is written. So the stock OS file always
  recovers the device.
- **Mods are checked against each other before anything is built.** Two
  mods may not touch the same bytes, claim the same memory or the same
  named resource, or leave a requirement unmet.

| Device | OS | Status |
|---|---|---|
| Digitakt (mk1) | 1.53, 1.54 | supported |
| Digitakt II | 1.17 | experimental: whole builds (format-1 mods) and linkable mods with its own core (the hook bus's tick, draw, key and encoder events), sealed as the unit checks them; boots in digikit's emulator; core with a key-swap mod works on a unit (Transfer over USB) |
| Digitone (mk1) and Digitone Keys | 1.43, 1.44 | supported |
| Octatrack (MKI and MKII) | 1.40C | supported: whole builds (format-1 mods); linkable mods with its own core: boots on an MKII, not yet run on an MKI |
| other Elektron devices | | planned: see [docs/DEVICES.md](docs/DEVICES.md) |

## Get started

- **In your browser, nothing to install:** <https://irpina.github.io/elekloader/>.
  Drop in your stock OS file, add mods from its shop or your own, build, and
  download the result. Your files are never uploaded.
- **Windows or macOS:** the apps on
  [Releases](https://github.com/irpina/elekloader/releases/latest), with the
  core mods built in.
- **From source, on any system:** Python 3.9 or newer and nothing else:
  `python -m elekloader`.

Each way needs the **stock OS file** for your device, exactly as Elektron
publishes it; the `.zip` from Elektron's site works as it is.
[docs/INSTALL.md](docs/INSTALL.md) says which file each device needs and
how each way starts.

Then tick your mods and build. Send the `.syx` to the unit with Elektron
Transfer, as for any OS update; the Octatrack takes its `.bin` from the
card. See [docs/BUILDING.md](docs/BUILDING.md).

**If a custom OS will not start:** the bootloader is never changed, so the
stock OS file always restores the unit. On a Digitakt mk1, a Digitakt II or
a Digitone mk1, hold **FUNC** while powering on for the startup menu, press
**TRIG 4** for OS UPGRADE, and send the stock `.syx` with Transfer's legacy
OS upgrade mode (on the Digitakt II, over its MIDI ports: not USB). On the
Octatrack, hold **FUNC** while powering on, press **TRIG 3** for MIDI
UPGRADE, and send the stock `.syx` over 5-pin DIN MIDI (USB MIDI does not
work for this).

## Mods

Mods are `.elemod` files: a whole build in one file, or linkable mods that
combine, on top of the **core** mod for your device. Cores add things of
their own. On the Digitone, for example, holding a track key opens the Mod
Menu, where you pick what your mods add ([docs/CORES.md](docs/CORES.md)):

![The Digitone's Mod Menu: four tiles, each an icon over a label with its trig key's number, TABLES selected, and a scroll bar](docs/img/dn-modmenu-grid.png)

Find mods in the web page's shop, or write your own:
[docs/ADAPTING.md](docs/ADAPTING.md) takes you from the first build to done.

## Documentation

The [docs](docs/README.md) are elekloader's wiki:

| for | pages |
|---|---|
| **Using it** | [Install](docs/INSTALL.md) · [Build, flash and recover](docs/BUILDING.md) · [Cores](docs/CORES.md) · [The web page](docs/WEB.md) |
| **Writing mods** | [Adapting your mod](docs/ADAPTING.md) · [The file format](docs/FORMAT.md) · [Adding a device](docs/DEVICES.md) · coding agents: [AGENTS.md](AGENTS.md) |
| **On your own site** | [The kit](docs/INTEGRATING.md) · [The engine in TypeScript](js/README.md) |
| **Maintaining it** | [Releasing](docs/RELEASING.md) · [The apps](docs/APPS.md) · [Tests](docs/TESTS.md) |

## Licence

GPL-2.0-or-later. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for the code that
comes from digikit and for the credits. elekloader is not affiliated with
Elektron. Flashing custom firmware is at your own risk.
