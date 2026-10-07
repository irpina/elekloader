[elekloader docs](README.md) › Build, flash and recover

# Build, flash and recover

## In the app

1. **Your stock OS file**: the first time, elekloader asks for it (a `.syx`,
   a `.bin` or Elektron's `.zip`); **Change stock firmware...** (top right)
   picks another. The header then shows the device and OS version with a
   tick. Mods made for another device or OS version are hidden unless you
   tick **Show mods for other firmware**.
2. **+ Install from file...**: add the `.elemod` files of the mods you want.
   They are copied into your library.
3. **Tick the mods** (or double-click them). Each mod's status shows as you
   go: Enabled, Conflict, Needs another mod, or made for other firmware.
   The check below the list says when the set combines: "No conflicts ...
   Ready to build".
4. **OS version shown**: what the unit will show as its OS version: 4
   characters on the Digitakt mk1 and the Digitone mk1, 1 to 10 on the
   Octatrack.
5. **BUILD FIRMWARE**: choose where to save the `.syx`. elekloader builds it,
   verifies it ([below](#what-a-build-guarantees)), and shows its sha256. For the Octatrack it also
   writes the card file, the `.bin` beside it.

The details pane shows each mod's description, every change it makes
(patch sites, the events it handles, its memory) and what it requires.
Profiles save a set of ticked mods. Your library, profiles and the stock
file you chose last are kept in `%APPDATA%\elekloader` (Windows) or
`~/.elekloader`.

The web page works the same way: [WEB.md](WEB.md).

## On the command line

From source ([INSTALL.md](INSTALL.md#from-source-on-any-system)), name the
stock file, the core and the mods:

```bash
python -m elekloader.patch --stock Digitakt_OS1.53.syx --mod core-2.1.elemod --mod a.elemod --out custom.syx --version 2.0a
python -m elekloader.patch --stock Digitakt_OS1.53.syx --mod core-2.1.elemod --mod a.elemod --check
```

`--check` only checks that the mods combine; with `--out` it builds and
verifies the file. With `pip install .` the command is `elekpatch`.

## Flash it

Send the `.syx` to the unit the way Elektron describes for OS updates
([How to update your device](https://support.elektron.se/support/solutions/articles/43000662890-how-to-update-your-device)).
For the Digitakt mk1, the Digitakt II and the Digitone mk1:
1. Connect it over USB and open Elektron Transfer.
2. Select the unit and **Connect**.
3. Drag the `.syx` onto **Drop files here**.
4. Press **YES** on the unit.

Don't turn the unit off until the upgrade is done.

For the Octatrack, from the card (back it up first):
1. **PROJECT > SYSTEM > USB DISK MODE**, and copy the `.bin` to the root of
   the card.
2. Eject the card on the computer, then leave USB DISK MODE on the unit.
3. **PROJECT > SYSTEM > OS UPGRADE**, and confirm.
4. When it restarts, power-cycle it once more before judging anything.

## Recovery

The bootloader is never changed, so the stock OS file always
restores the unit. If a custom OS will not start on a Digitakt mk1, a
Digitakt II or a Digitone mk1, hold **FUNC** while powering on for the
startup menu, and press **TRIG 4** for OS UPGRADE.
Then send the stock `.syx` with Transfer's legacy OS upgrade mode (on the
Digitakt II, over its MIDI ports: not USB). On the
Octatrack: hold **FUNC** while powering on, press **TRIG 3** for MIDI
UPGRADE, and send the stock `.syx` over 5-pin DIN MIDI (USB MIDI does not
work for this).

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
elektron-firmware-tool when given the same main OS stream. For the Digitone
mk1 (the same file family, with seven sections), it reproduces the stock
file from its own main OS stream.

The Digitakt II's files are sealed: the container ends in an HMAC-SHA256 of
the rest, which its bootstrap checks before it flashes anything. elekloader
derives the key from your stock file's bootstrap, as the unit does, seals
the output, and checks the seal again. From its own main OS stream, the
writer reproduces the stock file byte for byte.

The Octatrack's files are checked the same way: the container header
differs only in its 10-character version field, every SysEx message's
checksum and the card file's checksum are right, and the `.syx` and `.bin`
carry the same container. The copy of the bootloader that the OS can
re-flash (0x400de1e0-0x400e21e0) must stay stock. The in-place unpack is
not simulated there: where its bootloader stages the image is not known
yet. From their own main OS stream, the writer reproduces Elektron's
`.syx` and `.bin` byte for byte.
