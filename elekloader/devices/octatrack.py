# SPDX-License-Identifier: GPL-2.0-or-later
"""Octatrack (MKI and MKII): a ColdFire MCF5445x (V4e, EMAC) and a DSP56721.
The main OS runs from SDRAM at 0x40000400. MKI and MKII get the same 1.40C
file.

The file family is `elek` (elek.py), older than the Digitakt's ELE3:
- one ELEK container with a single packed section, and no section table,
  content checksum or trailer;
- the legacy SysEx transport, with per-message nibble checksums and an end
  marker;
- a second transport for the CompactFlash card, the ELUP `.bin`.
Every rule was checked here against the stock 1.40C files: rebuilding them
from their own section reproduces both files byte for byte
(tests/test_octatrack.py).

Facts taken from sambanks/octabam (MIT) and not re-derived here are marked
"octabam". Where they matter, they are used cautiously:

- **The bootloader.** It lives in NOR flash at 0..0x3fff and never comes in
  an OS file. The OS carries a copy of it and can re-flash the bootloader
  from that copy ("the unit may update its bootstrap", octabam).
  - The copy sits below the DSP code at 0x400e21e0. The bootloader's own
    strings ("READY TO RECEIVE MIDI UPGRADE...", "CHKSUM ERROR",
    "DOWNGRADE NOT POSSIBLE") are at 0x400e18f1-0x400e19c9.
  - Its exact start is not known, so the whole 16 KB below 0x400e21e0 (the
    most a 0x4000-byte bootloader can be) is protected: no mod may change a
    byte of it.
- **The OS in flash.** It is programmed from 0x4000, and the OS's sector
  table spans 0x4000-0x1fffff (octabam, marked inferred there). That is the
  container budget used here.
- **Staging.** Where the bootloader unpacks from is unknown (the bootloader
  is not in the file), so the in-place unpack is not simulated. A container
  that depacks from flash into SDRAM needs no such check. If that turns out
  wrong, set `stage`.
- **No free RAM by default.** A whole build (e.g. an octabam remix) brings
  its own loader, which runs at boot from right after the OS image
  (0x4010fdf0) and carves memory for itself. elekloader has no linkable mods
  for the Octatrack yet.
"""
from . import Device, Release

DEVICE = Device(
    key='octatrack',
    name='Octatrack',
    sysex_id=0x05,
    releases={
        '1.40C': Release(
            version='1.40C',
            syx_sha256='0a8d2d2b35c2cc78fa338576adc1af0cbc094cef973255103165c73edd87f2b6',
            main_sha256='164f31224bf61181e3f50e7dec40df9afcae5b16dbf6e4c0d0cc5e986af0a84e',
            main_len=1112560,
            bin_sha256='34695b606eb00e1b4dded5fd0c4b66f3a460522a632e47d7416dbd220599e1ad'),
    },
    main_section=3,
    main_load=0x40000400,
    stage=None,
    flash_at=0x4000,
    flash_limit=0x200000,
    trailer=None,
    isa='coldfire',
    container='elek',
    version_len=10,
    protected=((0x400de1e0, 0x400e21e0,
                'the copy of the bootloader the OS can re-flash it from'),),
    blob_max=None,
    recovery=('hold FUNC while powering on for the startup menu, press TRIG 3 (MIDI '
              'UPGRADE) and send the stock .syx over 5-pin MIDI (not USB)'),
    toolchain={
        'prefix': 'm68k-linux-gnu-',
        'asflags': ['-mcpu=54455'],
        'cflags': ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                   '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall'],
    },
)
