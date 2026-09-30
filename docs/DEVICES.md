# Adding a device

Everything elekloader knows about a product is in one profile,
`elekloader/devices/<device>.py`, registered in `devices/__init__.py`
(`_all()`). The Digitakt mk1 profile is the example. The Digitone mk1's
(`digitone_mk1.py`) is a second device of the same file family, with its own
core. The Octatrack's (`octatrack.py`) is a second file family, which has no
linkable mods yet. The Analog Rytm mk1's (`rytm_mk1.py`) is a third, ELE2,
read and written by `syx.py`; its mods are patch sets.

| field | what it is | how it was found for the Digitakt mk1 |
|---|---|---|
| `releases` | each supported stock OS: its `.syx` sha256, and its main OS section's sha256 and length | hash the file, and the section depacked |
| `sysex_id` | the device byte of its OS messages | the framing messages (`0x0A`) |
| `main_section`, `main_load` | which container section is the main OS, and where it runs | the section table (id 3, `0x40000400`) |
| `stage` | where the bootloader stages the main OS before unpacking it in place | the bootstrap's loader (`0x800005fe`: read to `0x40200000`, unpack to `0x40000400`) |
| `flash_at`, `flash_limit` | where the container sits in flash and must end | the bootstrap (`0x80000` .. `0x380000`) |
| `trailer` | how the file is sealed: `None`, or `'hmac'` | mk1 has none |
| `isa` | the main CPU's instruction decoder, for the boundary checks | ColdFire (`isa/coldfire.py`) |
| `areas` | memory that is free at run time: where a mod's regions may lie | the research on what the OS never touches |
| `ddr`, `sram_code`, `fast_table` | where the linker puts mods' code and data, fast code, and the table that copies it | the areas above |
| `recovery` | how to get back to stock, shown to the user | FUNC at power-on |
| `container`, `version_len` | the file family (`'ele3'`, `'ele2'`, `'elek'`) and the version field's length | the container header |
| `protected` | main OS ranges no mod may change, with the reason | none on the mk1 |
| `blob_max` | a cap on the appended blob, if the DDR areas do not give one | none on the mk1 |
| `default_version` | the version a build keeps unless given one | none on the mk1 (the window offers 2.0a) |
| `toolchain` | the compiler, assembler and flags the SDK uses | the CFW's build |

## The Digitone mk1 and Digitone Keys (1.43)

- **Files.** One `.syx` serves both. It is the Digitakt mk1's family (ELE3,
  the same SysEx transport and layout) with seven sections: 5, 2 (the
  bootstrap, with the startup menu), 3 (MAIN OS), 4 (the updater), 6, 7 (the
  second CPU's image, which renders the FM voices) and 8. The longer table
  moves the first section to `0xA0`; the reader and writer take that from
  the stock file. From its own main OS stream, the writer reproduces the
  stock file byte for byte.
- **Unpacking.** The bootstrap loads the updater, which reads section 3
  from flash (offset + `0x80000`) to `0x40200000` and depacks it in place to
  `0x40000400`: the Digitakt mk1's loader, instruction for instruction
  (`0x80003518` in the updater). Stock's in-place gap is 403,540 bytes.
- **Recovery.** The startup menu (FUNC at power-on) has 4 ... OS UPGRADE.
- **Checked in an emulator.** digikit's firmware check runs the file's own
  bootstrap and updater, then a cold boot and a scripted session. Stock 1.43,
  repacked by elekloader, passes it against stock: the updater accepts the
  stream, and the screens and the audio are identical.
- **Linkable mods.** Its core is `mods/core-dn1`: `core.s` with the
  Digitone's addresses. Its eight sites and every routine it calls are the
  Digitakt mk1's found again in 1.43. They are the same code instruction
  for instruction, bar the addresses in it. The render handler's frame is
  0xB8 bytes (0xA8 on the Digitakt), hence `RENDER_FRAME`.
- **The DDR area** is the Digitakt's, `0x47BE0000-0x47C00000`:
  - The OS clears `0x4028E000-0x43229E60` at start, and its stack runs down
    from `0x48000000`.
  - No instruction operand in its code points between `0x43EB0000` and the
    stack.
  - In a settled emulator run, no DDR page from `0x43400000` to
    `0x47C00000` is ever mapped.
- **Checked in the emulator:** with core alone, the build passes every
  stage, with every screen identical to stock.
  - The audio is identical to stock up to PLAY.
  - After PLAY it is the same sound, sample-shifted, because core's few
    cycles move when the scripted key presses land. Stock against itself
    with PLAY 0.3 ms later diverges in the same way.

## The Octatrack (1.40C)

- **Files.** One stock image serves the MKI and MKII. It comes as a `.syx`
  (the legacy SysEx transport) and as a `.bin` card file (ELUP: a
  word-feedback cipher with a checksum). Both carry one ELEK container,
  whose only section is the main OS, at `0x40000400`. `elek.py` rebuilds
  both stock files byte for byte from their own main OS stream.
- **Protected.** `0x400de1e0-0x400e21e0` holds the copy of the bootloader
  that the OS can re-flash. No site, blob or verified output may change it.
- **Flash.** The container sits at `0x4000` and must end below `0x200000`.
- **Not known yet.** Where the bootloader stages the image (`stage` is
  `None`), so the in-place unpack is not simulated; and the free run-time
  areas, so there is no linker layout and only format-1 mods load.

## What a new device needs besides its profile

- **Sealed files.** The Digitakt II and Digitone II seal the container with
  an HMAC-SHA256 trailer. digikit computes it (`dt2/authcode.py`).
  - `syx.write` refuses any device whose `trailer` is not `None` until that
    is ported and verified against the stock files.
  - The trailer's layout, and the preamble's length rule, must be checked
    against real files first, as the mk1's were against
    elektron-firmware-tool's output.
- **The packing format.** The loader repacks with the same codec
  (`codec/`). Check that the device's own depacker accepts it: every
  section must round-trip through `codec/elz.py`, and the in-place
  simulation must hold for the device's `stage`.
- **Another CPU.** A decoder in `isa/` with `reader()`, `decode()` and the
  flags `ILLEGAL`, `LINEF`, `FPU`, `PCREL` and the flow constants.
- **Tests.** Before anything is flashed:
  - the writer must reproduce a stock file from its own main OS stream
    (`test_writer_no_change_is_stock`);
  - a verified build must pass the device's cold boot in an emulator, if
    one exists.

Mods are made per release: a mod's target names one stock file by hash, so
supporting a new OS version means adding its release to the profile and
rebuilding the mods for it.

## The Analog Rytm mk1 (1.73)

- **Files.** `Analog-Rytm_OS1.73.syx`: the Digitakt mk1's SysEx transport
  (device id `0x07`; the same counters, checksums and framing) around an
  **ELE2** container. That is a `0x14`-byte header (`ELE2`, build `0173`,
  eight spaces, version `1.73` at `0x10`), the load address `0x40000400`,
  and the one packed section (the main OS) at `0x18`, with no table. The
  container is padded to 4 bytes. From its own section stream, the writer
  reproduces the stock file byte for byte.
- **Unpacking.** The bootstrap lives in flash below `0x20000` and the
  container starts at `0x20000`. At boot the bootstrap depacks from flash
  (`0x20018` to the address at `0x20014`). After an upgrade it depacks the
  section staged at `0x40200000` to `0x40000400` in place. Both use one
  routine, at flash `0x2a` (356 bytes). It is **byte-identical** to the
  Digitakt mk1 bootstrap's depacker (`0x8000009e`), so this packer's streams
  are valid on the Rytm too. Stock's in-place gap is 558,719 bytes.
- **Flash budget.** The bootstrap's MIDI upgrade stages the received file in
  RAM below the part of itself it runs from `0x40400000`, then erases only
  the 64 KB sectors the length needs, from `0x20000`. The pad calibration
  goes to the pad controller, not to this flash. A flash that holds the
  stock container (ending at `0x15a2c4`) is at least 2 MB, hence
  `flash_limit` `0x200000`. This packer's stream is about 9% larger than
  stock's (1.41 MB against 1.29 MB). Whether the in-OS (USB) upgrade takes a
  file of that size has not been tried; the bootstrap's does.
- **Protected.** The main OS carries a copy of the bootstrap
  (`0x4028c708-0x402a1b24`). At boot it writes that copy into the
  bootstrap's flash when the copy's version word is newer than flash's
  (`0x1fff8`; `0x400005aa`, then `0x4011a738`, BOOTSTRAP UPGRADE). No mod may
  change a byte of it, so the startup menu stays stock.
- **Mods are patch sets**: format 1 without a blob. Their code sits in three
  runs of zeros the OS never uses: `cave2` below the SRAM load images,
  `cave` right after the bootstrap copy, and `cave3` in the read-only data.
  Their `regions` claim those runs, and the checks keep two mods apart by
  bytes, regions and names. A working set (euclid accents, velocity
  humanise, LFO random modifiers, a sample low/high cut) is
  [rytm1_mods](https://github.com/gdeo607/rytm1_mods). For every
  combination of its mods, elekloader builds the same main OS as that
  project's own pipeline (its `tools/elemod_check.py`).
- **The version field** keeps `1.73` (`default_version`): how the bootstrap
  treats another value has not been tried on a unit.
- **Not yet:** a core and a DDR area for linkable mods, and a run on a unit
  of an elekloader-built file.
