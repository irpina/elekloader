# Adding a device

Everything elekloader knows about a product is in one profile,
`elekloader/devices/<device>.py`, registered in `devices/__init__.py`
(`_all()`). The Digitakt mk1 profile is the example. The Digitone mk1's
(`digitone_mk1.py`) is a second device of the same file family, with its own
core. The Octatrack's (`octatrack.py`) is a second file family, with a core
of its own that is only a boot copier.

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
| `container`, `version_len` | the file family (`'ele3'`, `'elek'`) and the version field's length | the container header |
| `protected` | main OS ranges no mod may change, with the reason | none on the mk1 |
| `blob_max` | a cap on the appended blob, if the DDR areas do not give one | none on the mk1 |
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
  `None`), so the in-place unpack is not simulated.
- **Linkable mods.** There is no free RAM in stock: the OS gives the whole
  audio page arena (`0x40a955e0-0x46025de0`, 14,602 pages of 6,144 B) to
  samples and the recorders. The core, `mods/core-ot`, takes the arena's
  bottom 1,707 pages (10 MB), as sambanks/octabam's platform does, and
  that is the device's `ddr`: `0x40a955e0-0x41495de0`.
  - It moves the arena's base past them with octabam's 28 arena writes
    (the base, base + one page, the page count, the fill limit and the
    clear length). tests/test_octatrack.py derives each from the page count.
  - Its `.boot` is appended at the image's end (`0x4010fdf0`) and called
    from the boot site `0x4000050c`, in place of `0x40001e50`, which it
    calls first. It copies the run image to the reserve through the
    uncached alias (`+0x08000000`) and zeroes `.bss`.
  - There is no hook bus: each mod patches its own sites.
  - `elekloader.sdk.octabam` converts octabam's ColdFire-only modules to
    such mods (docs/ADAPTING.md, 4b).
- **Checked in an emulator** (octabam's `ot_emu`): with core and a mod that
  puts a marker in `.run`, the boot reaches the RTOS handoff as stock does,
  `.boot` runs once, and the marker is in the reserve after boot. Not yet
  run on a unit.

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
