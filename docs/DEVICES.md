# Adding a device

Everything elekloader knows about a product is in one profile,
`elekloader/devices/<device>.py`, registered in `devices/__init__.py`
(`_all()`). The Digitakt mk1 profile is the example.

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
