# SPDX-License-Identifier: GPL-2.0-or-later
"""Analog Rytm MKII: a ColdFire MCF5441x-family CPU (the Digitakt mk1's
platform, an MCF54418); the main OS runs from DDR at 0x40000400. Measured
on OS 1.73, by comparison with the Digitakt mk1 1.54 (elekloader's
digitakt-mk1 profile and mods/core, whose 1.54 port is the core this one
starts from) in Ghidra and on the stock images. Proof-of-concept profile.
1.74's file differs from 1.73's only in the main OS (and the version
string's section 5): the same bootstrap, FPGA bitstream and ARM image. Its
main OS is 1.73's with code added in two places (Outbox 8's main-output
routing), and the same OS entry, SRAM operands, cleared RAM and stack, with
no operand near the mods' area, so what follows holds for both, at 1.73's
addresses (docs/DEVICES.md says how far each moved).

- The container: ELE3, sysex id 0x0C, sections 5 (meta), 2 (bootstrap,
  with the STARTUP menu), 1 (FPGA bitstream), 3 (MAIN OS, packed) and 8
  (an ARM Cortex-M image, byte-identical to the Digitakt mk1's section 8).
  No updater section (the Digitakt mk1 has one, section 4) and no trailer:
  elektron-firmware-tool's -r null repack reproduces the stock file byte
  for byte. Only section 3 changes.
- Same platform as the Digitakt mk1: the OS entry (word[0] = 0x40000870;
  the Digitakt's 0x400004E8) is the Digitakt's instruction for instruction
  apart from addresses and one constant (it ORs 0x8E into 0xFC044000,
  the Digitakt ORs 0x06). It sets SP to 0x48000000, writes the same
  peripheral registers (0xFC04002D, 0xFC04002F, 0xEC09000E bit 11, CACR,
  ITT0, with the same values) and makes the same five setup calls in the same
  order; the third (0x400008C0, the Digitakt's 0x40000538) sets VBR to
  0x40000000.
- The bootstrap reads section 3 from flash (its container offset +
  0x80000) to 0x40200000 and depacks it to 0x40000400: the Digitakt mk1
  bootstrap's loader (Rytm 0x80000590, Digitakt 0x800005FE), call for
  call, with a decompiled-identical depacker (Rytm 0x8000042C, Digitakt
  0x8000049A).
- Flash limit: 0x300000. The Rytm's bootstrap makes no fixed-offset flash
  read (its only flash reads are relative to the container), so the limit
  comes from the main OS, as the Digitakt II's does. Like the Digitakt
  mk1's, it keeps a store at 0x380000-0x400000 (42 pushes of 0x380000 and
  16 of 0x3C0000 around 0x40139000, into the same read, write and erase
  routines, 0x40136FAA, 0x40136FAE and 0x4013702A). It also keeps a second
  store of its own at 0x300000-0x380000: the routines at 0x400FAC1A-
  0x400FB1C6 read a 0x1B072-byte block from 0x300000 or 0x340000 into
  0x4198911A, and erase and write there through the same routines. So the
  container must end below 0x300000: 2.5 MB from 0x80000, a whole number of
  256 KB units. Stock's ends at 0x1EA2F0; elekloader's repack of the stock
  main OS, which compresses less than Elektron's, at 0x20A5D0. The in-OS
  upgrade (0x4009F3A0) erases from 0x80000 only as far as the container it
  received reaches.
- No protected range: the main OS holds no copy of the bootstrap, and
  nothing in it writes its own bytes to flash (docs/DEVICES.md).
- The OS clears 0x402CE000-0x42FBB250 at start (0x4000083A, the
  Digitakt's routine at 0x400004B2, which clears 0x40253000-0x439D1000)
  and runs its stack down from 0x48000000.
- Mods' area: 0x47BE0000-0x47C00000, the Digitakt mk1's
  area, below the stack's page. Verified on hardware 2026-10-11 with the
  DDR canary (mod 0016 + 0003 diag mode 4, Iced-Cream/rytm-mods-src,
  elemod branch at fb1a0ec,
  `make ddr-canary-build`): the area was
  filled with address ^ 0xC0DEF00D at the boot site and read back with 0
  changed words after boot, through kit/sample loading, busy playback,
  FX/drive, MIDI, Overbridge, project save/reload, a long run, and again
  after a power cycle. That run also exercised the boot hook (0x400008C0).
- UI: the periodic UI routine (0x400A2AAA) advances its counter 20 per
  second (the Digitakt's at 30, 0x4000A75C), so ev_tick runs at about
  20 Hz. The tick target is the Digitakt's byte for byte (it returns the
  dirty flag at +0x20 of the view controller) and the draw target
  (drawAll) opens as the Digitakt's does. The Digitakt passes the
  controller embedded at +0x40 of the UI object; the Rytm loads a pointer
  from +0x20 and skips the frame when it is null.
- Recovery: STARTUP menu (hold FUNC at power-on), TRIG 4 (OS UPGRADE, the
  Digitakt's menu, with the Rytm's POTENTIOMETER and PAD TEST added),
  stock .syx over MIDI DIN; checked on hardware with stock 1.73.
"""
from . import Device, Release

DEVICE = Device(
    key='analog-rytm-mk2',
    name='Analog Rytm MKII',
    sysex_id=0x0C,
    releases={
        '1.73': Release(
            version='1.73',
            syx_sha256='8ad671087ec30433d5407c7380d2396e0915ab931c5d3dd18a78bf284d3d1e52',
            main_sha256='28d9ef40c895e03f17dfce096543109adaf708947392db72818fc2a412d685d6',
            main_len=3005432),
        '1.74': Release(
            version='1.74',
            syx_sha256='cb0f99d620edde994fb860c0e79cc2464e427d06882828cfdfb00fc53700e123',
            main_sha256='34cd0c4da8e4b810d1b25284475a99ea53821e2ab7d30a978bf15dc578251f3b',
            main_len=3005432),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x80000,
    flash_limit=0x300000,                         # the OS's own store starts there
    trailer=None,
    isa='coldfire',
    areas={
        'ddr': (0x47BE0000, 0x47C00000),          # verified 2026-10-11, see above
    },
    ddr=(0x47BE0000, 0x47C00000),
    recovery=('hold FUNC while powering on for the STARTUP menu, press TRIG 4 (OS UPGRADE), '
              'then send the stock .syx over MIDI DIN (not USB)'),
    toolchain={
        'prefix': 'm68k-linux-gnu-',              # or ELEKLOADER_CROSS=m68k-elf-
        'asflags': ['-mcpu=54455'],                 # ColdFire V4 (the MCF5441x's ISA), as the Digitakt mk1
        'cflags': ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                   '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall'],
    },
)
