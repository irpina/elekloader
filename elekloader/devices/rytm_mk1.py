# SPDX-License-Identifier: GPL-2.0-or-later
"""Analog Rytm (mk1): a ColdFire V4 with EMAC; the main OS runs from DDR at
0x40000400. Measured on OS 1.73:

- **The file family is ELE2** (`syx.py`): the Digitakt mk1's SysEx transport
  (device id 0x07, the same counters and checksums) around a simpler
  container. It has a 0x14-byte header ('ELE2', build '0173', eight spaces,
  version '1.73'), the load address, then the one packed section (the main
  OS) at 0x18. There is no table, and the stock file pads the container to
  4 bytes. From its own section stream, the writer reproduces the stock file
  byte for byte.
- **The bootstrap** is in flash below 0x20000 (its vectors: SP 0x80010000, PC
  0xa6a), and the container is from 0x20000.
  - At boot it depacks straight from flash: 0x20018 to the address at 0x20014.
  - After an upgrade it depacks the section staged at 0x40200000 to
    0x40000400, in place.
  - Both use the same routine (flash 0x2a, 356 bytes), byte-identical to the
    Digitakt mk1 bootstrap's depacker (0x8000009e). So the packer's streams
    are valid here, and elz.py depacks the stock section to the known image.
    Stock's in-place gap is 558,719 bytes.
- **The flash budget.** The bootstrap's MIDI upgrade stages the received
  file in RAM below the part of itself it runs from 0x40400000. It then
  erases only the 64 KB sectors the received length needs, from 0x20000. The
  pad calibration is sent to the pad controller, not kept in this flash.
  - A flash that holds the stock container (ending at 0x15a2c4) is at least
    2 MB, so the limit is 0x200000.
  - This packer's stream is ~9% larger than stock's (1.41 MB against
    1.29 MB).
- **Protected.** The main OS carries a copy of the bootstrap
  (0x4028c708-0x402a1b24, its version words then its image). At boot it
  writes that copy into the bootstrap's flash sectors when the copy's
  version word is newer than flash's (0x1fff8; 0x400005aa, then 0x4011a738
  shows BOOTSTRAP UPGRADE). No mod may touch it, so the startup menu (FUNC at
  power-on) stays stock.
- **Mods are format 1** (whole builds without a blob, i.e. patch sets). Their
  code sits in three runs of zeros in the image that the OS never uses
  (`areas`: below the SRAM load images, after the bootstrap copy, in the
  read-only data), and their `regions` claim them. There is no core and no
  DDR area yet.
- **The version field** keeps the stock '1.73' by default: how the bootstrap
  treats another value has not been tried on a unit.
"""
from . import Device, Release

DEVICE = Device(
    key='rytm-mk1',
    name='Analog Rytm mk1',
    sysex_id=0x07,
    releases={
        '1.73': Release(
            version='1.73',
            syx_sha256='9115c3888354bb388f90410e0445cd312bf020593ed99f768a99e475d1d6157c',
            main_sha256='3db73d3a5524d10db110f6e50d722274cd0b72a01292f4a97032165e4f97e175',
            main_len=2824228),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x20000,
    flash_limit=0x200000,
    trailer=None,
    isa='coldfire',
    container='ele2',
    version_len=4,
    protected=((0x4028c708, 0x402a1b24,
                'the copy of the bootstrap the OS writes into flash at boot'),),
    areas={
        'cave2': (0x402a2780, 0x402a3000),
        'cave': (0x402a1b30, 0x402a2000),
        'cave3': (0x4024db0c, 0x4024df0c),
    },
    default_version='1.73',
    recovery=('hold FUNC while powering on for the startup menu, press TRIG 4 (OS UPGRADE) '
              'and send the stock .syx over 5-pin MIDI (not USB)'),
    toolchain={
        'prefix': 'm68k-linux-gnu-',
        'asflags': ['-mcpu=5475', '-mno-float'],
    },
)
