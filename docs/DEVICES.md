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
| `hmac_key_from` | for `'hmac'`: the section and seed string the key is derived from (never the key itself) | none on the mk1 |
| `isa` | the main CPU's instruction decoder, for the boundary checks | ColdFire (`isa/coldfire.py`) |
| `areas` | memory that is free at run time: where a mod's regions may lie | the research on what the OS never touches |
| `ddr`, `sram_code`, `fast_table` | where the linker puts mods' code and data, fast code, and the table that copies it | the areas above |
| `recovery` | how to get back to stock, shown to the user | FUNC at power-on |
| `container`, `version_len` | the file family (`'ele3'`, `'elek'`) and the version field's length | the container header |
| `protected` | main OS ranges no mod may change, with the reason | none on the mk1 |
| `relocatable` | data inside a protected range that the OS reaches only through the listed 4-byte operands and never writes, so a mod may serve its own copy through them (sdk.octabam does, for a poke there) | none on the mk1 |
| `blob_max` | a cap on the appended blob, if the DDR areas do not give one | none on the mk1 |
| `image_free` | zero runs inside the main OS that `fixed` code may take (sdk.build) | none on the mk1 |
| `toolchain` | the compiler, assembler and flags the SDK uses | the CFW's build |

## The Digitakt II (1.17)

Experimental. Whole builds and the core (mods/core-dt2) boot in digikit's
emulator, and a build of core with examples/perform-direct works on a unit
(4 Oct 2026): flashed, it booted, and the key swap and
a PERSONALIZE row (in an earlier version of the mod) worked. digikit (https://github.com/m-dwyer/digikit,
docs/findings/01-container-and-patching.md) mapped 1.15C and 1.16. Each fact
below was found again in 1.17.

- **Files.** The Digitakt mk1's family (ELE3, the same SysEx transport),
  device byte `0x14`. It has six sections: 5, 2 (the bootstrap, run at
  `0x80000400`; its `dest` is a version, `0x0201`), 3 (MAIN OS), 4 (the
  updater), 7 (the SHARC DSP's program) and 8.
- **Sealed.** After the last section's 16-byte padding comes a 32-byte
  HMAC-SHA256 of everything before it, inside the preamble's length.
  - The bootstrap checks it, and the content checksum, before it flashes;
    the OS checks it on an upgrade. A file that fails is refused with
    `Checksum failed` or `UPGRADE ABORTED`, and nothing is written.
  - The key: in section 2, the seed `"Master Overdrive"`, a NUL and a
    32-byte constant C; the key is C ^ sha256(seed) ^ sha256(reversed seed).
    `syx.seal_key` reads it from the user's stock file, so it is never
    stored here.
  - From its own main OS stream, the writer reproduces the stock file byte
    for byte, seal included.
- **Staging.** The bootstrap's loader (`0x80000596`) reads section 3 from
  flash, at its container offset + `0x80000`, to `0x40400000`, and unpacks
  it from there to `0x40000400` with its depacker (`0x80000432`). The mk1
  stages at `0x40200000`; this image, 3.27 MB depacked, runs past that.
  Stock's in-place gap is 2,065,240 bytes.
- **The unit's own depacker takes elekloader's stream.** Run in Unicorn
  through digikit's harness (`emu/oracle.py`, with the 1.17 entry), the
  bootstrap's depacker yields the stock main OS from both Elektron's
  stream and elekloader's repack of it (1,385,586 bytes against
  1,147,584).
- **Flash.** The container starts at `0x80000`: the bootstrap's read above,
  and digikit's map of the OS's own reads. The OS keeps a store at
  `0x380000`-`0x400000`, with the mk1's code at its own addresses: it reads
  a 0x14-byte header at `0x380000`, and erases the sectors at `0x380000` and
  `0x3c0000` (26 and 12 call sites, from `0x400ca504`). So `flash_limit` is
  `0x380000`: 3 MB for the container, of which stock takes 1.48 MB. The
  bootstrap's receive path has no size check of its own, so this limit is
  elekloader's alone.
- **Checked in an emulator** (digikit's, `emu.checkpoint` from a cold
  boot, then `tools/emucheck.py` to 600M instructions; 4 Oct 2026):
  - Two elekloader builds, a repack of stock 1.17 (version `DT01`) and a
    whole build with one data site (`DT02`), pass every stage as stock does:
    the main screen, six tasks, the +Drive formatted, the same instruction
    count. The repack's screen at 650M is identical to stock's.
  - digikit's extractor reads both, and its checker passes their content
    checksum, seal, framing count and every packet checksum.
  - Not checked in the emulator: the bootstrap's own flash path (it serves
    the container to the OS's flash reads and boots the main OS directly).
    The unit above accepted a sealed build.
- **Recovery.** The startup menu (FUNC at power-on), TRIG 4 for OS UPGRADE,
  over MIDI only (Elektron's readme). It is in the bootstrap, which no build
  changes, and checks only the content checksum and the seal.
- **At reset** (`0x400004e8`), the OS:
  - copies `0x40312000-0x40318e80` to SRAM at `0x80000000` and
    `0x40318e80-0x4031ff60` to `0x80008000`, and zeroes the rest of each
    32 KB half;
  - clears DDR `0x40312000-0x47E28470`;
  - runs its stack down from `0x48000000`.
  The mk1's reset code, with the II's addresses.
- **Free memory, and the core** (mods/core-dt2):
  - There is no sample pool in its DDR to take from: samples go to the DSP
    over FlexBus (0x8C000000, digikit). The reset clears 0x40312000-
    0x47E28470 for the OS's static `.bss`, almost all of the 128 MB.
  - Above the clear, the OS reaches its DSP buffers only through the
    uncached alias (+0x08000000): 0x4FE30000-0x4FE7AE80, so 0x47E30000-
    0x47E7AE80. The boot stack runs down from 0x48000000.
  - Between them, 0x47E7B000-0x48000000: no decoded instruction (digikit's
    `tools/refscan.py`, 96.75% coverage) names it or its alias (the only
    hit, 0x47efffff, is the high word of the double FLT_MAX); it is zero in
    every rung of a cold boot; and a write watch over all of it, cached and
    uncached, saw no write from 400M to 808M instructions of a session
    with 37 key events. The core takes 0x47F00000-0x47F40000 (256 KB) from
    the middle, 520 KB clear of the buffers and 768 KB of the stack.
  - SRAM: the reset copies the image's tail into each 32 KB half and zeroes
    the rest. Past the copies, 0x80006E80-0x80008000 and 0x8000F100-
    0x80010000 are named by no decoded instruction. They are zeroed after
    the boot copier runs, so they are free at run time only, as on the mk1.
    A write watch over both saw no write from 400M to 781M instructions of
    a session with 24 key presses. `.fast` code goes to the tail: core-dt2
    declares `core_fast` and copies it on the first `ev_tick`.
  - The core does not start DTIM0, unlike the mk1's (`NO_DTIM0` in
    core.s). Nothing before the OS starts it on the II either, and ten OS
    sites read its counter: with it running, a cold boot with core alone
    jumped to 0 at 553M instructions in digikit's emucheck.
  - The core's events: `ev_tick`, `ev_draw`, `ev_key`, `ev_enc`,
    `ev_settings`, and the II's own `ev_personalize` (SETTINGS >
    PERSONALIZE, whose builder makes its rows with the same generic
    `MenuItem`). mods/core-dt2/README.md lists the sites and routines.
  - Checked in the emulator (cold boot, then emucheck to 600M): core 1.0
    alone passes every stage, with its screen at 650M identical to stock's;
    with a mod that inverts an 8x8 block on `ev_draw`, the screen differs
    from stock in exactly those 64 pixels. Each event was driven with a
    test mod: key and encoder counts, a SETTINGS row, and
    a PERSONALIZE checkbox row. examples/perform-direct (a key swap) works
    on a unit, with core's other events registered but not used there.
  - Not covered: anything a session in the emulator does not reach (no
    DSP, no samples, an empty +Drive) and the unit run did not use.

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
  0xB8 bytes (0xA8 on the Digitakt), hence `RENDER_FRAME`. From 2.1
  (`voice.s`) it has a ninth site, the render's voice note-on at
  0x4009e928, for the Digitone-only `ev_voice_on`, and parameter slots
  (`params.s`): ids 182-184 for mods, through 63 more sites; mod pages
  (`pages.s`): pages 27-30, through two more; and project data
  (`projdata.s`): mods' blocks saved with the project, through five more.
  From 2.2 the Mod Menu (`menu.s`): holding a track key opens a menu of
  the mods' entries; the four UI sites go to its wrappers first.
  1.44 has all of them, at its own addresses (`ports`).
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
  - The OS's USB descriptor tables are its top 480 bytes, from
    `0x400e2000`. The device descriptor (18 bytes) is `relocatable`: the
    only pointer to it is the operand of `pea 0x400e2000` at `0x4001d82c`
    (GET_DESCRIPTOR), and nothing writes it. A mod may point that operand
    at its own copy. tests/test_octatrack.py checks, against the stock
    file, that no other four bytes outside the range point into it.
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
    such mods, and whole remixes, which is how USB AUDIO IN converts
    (docs/ADAPTING.md, 4b).
- **Free space inside the image** (`image_free`, octabam's measured zero
  runs): `0x400c45b0-0x400c4702`, `0x400d24d0-0x400d2ce0` and
  `0x400d64e0-0x400d7c3c`. octabam pins code in these runs, and `fixed`
  code may use them.
  - The third run starts at `0x400d64da` in stock. Its first six bytes are
    left out: they follow the table at `0x400d64a0`.
  - Left out entirely: `0x400d2ee6-0x400d3020` (a live descriptor), and
    everything above `0x400d8000` (the PROJECT subsystem's RAM).
- **Checked in an emulator** (octabam's `ot_emu`): with core and a mod that
  puts a marker in `.run`, the boot reaches the RTOS handoff as stock does,
  `.boot` runs once, and the marker is in the reserve after boot.
- **On a unit** (an MKII, 3 Oct 2026): eight builds flashed from the card
  booted, each showing its own version.
  - The builds were core alone, then core with 19 of the converted octabam
    mods (irpina/octabam2elemod v1.0) in seven groups, the last with all 19.
  - In the last build, the 15 mods it carried were tested in use, and all
    worked: the 14 non-USB mods but SCENES P2, and USB IO TRACKS MAIN CUE AB.
    The shop's details sheet says, mod by mod, what has been checked
    (`on_unit` in web/catalog.json).
  - Not yet run on an MKI.

## What a new device needs besides its profile

- **Sealed files.** `trailer='hmac'` with `hmac_key_from` (the Digitakt
  II, above). Another sealed device needs its seed found in its bootstrap
  (the Digitone II's is `"Multiplier"`, digikit), and the writer checked to
  reproduce its stock file, seal included.
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
rebuilding the mods for it (below).

## A new OS version of a supported device

How Digitakt mk1 1.54 and Digitone mk1 1.44 were added (2026-10-01):

1. **Compare the file with the last release's.** Every section but the main
   OS (and section 5, the version string) must be the same bytes: the same
   bootstrap and updater, so the same staging and flash layout. For both
   releases that held. If the bootstrap changes, check `stage`,
   `flash_limit` and the recovery path again.
2. **Add the release** to the profile: the file's sha256, and the main OS's
   sha256 and length, depacked. The writer must reproduce the file from its
   own main OS stream, and its main OS must depack in place from `stage`
   (`tests/test_releases.py` checks both for every release given).
3. **Check the memory facts** the profile states: here, the same SRAM
   operands in the code, and no operand near the DDR area mods run from.
   Both releases moved their RAM past the image by 0x1000 and changed
   nothing else there.
4. **Port the cores**, under `ports` in their `mod.json` (ADAPTING.md 3.10):
   every `defsym` and site found again in the new image, and each site's
   stock bytes read from it. `tests/test_releases.py` builds and lints every
   core for every release it names.
5. **Run a build with the core in the emulator** against the new stock
   file. Digitakt mk1 1.54: core 2.1 passes, with every screen identical
   and the audio identical apart from the recording's silent end, 1 ms
   off, exactly as core 2.1 does on 1.53. Digitone mk1 1.44: not yet,
   since the emulator does not boot stock 1.44 to a settled screen.
6. **Tell mod authors** to build their mods for the new OS. A mod for the
   old one is refused with the new stock file.
