# core for the Digitone mk1

The boot copier and the hook bus for the Digitone mk1 and Digitone Keys,
OS 1.43 and 1.44. It is [../core/core.s](../core/core.s), built with the
Digitone's addresses and sites (`mod.json`: 1.43's, and 1.44's under
`ports`). Every set of linkable (format 2) mods for
the Digitone needs it. On its own it changes nothing the unit does.

- **At boot** (the OS entry's call at 0x40000538, as on the Digitakt),
  `boot` copies the RAM image the linker built to 0x47BE0000, zeroes
  `.bss`, starts the DTIM0 counter if nothing has, and goes on to the call
  it replaced.
- **The events** are the Digitakt mk1's (docs/ADAPTING.md, "The hook
  bus"), from the Digitone's sites: 0x4001900c (tick), 0x40019072 (draw),
  0x40019d9c (key), 0x40019de4 (encoder), 0x40072a34 (SETTINGS),
  0x4009d108 and 0x4009e51c (the render's entry and exit). In 1.44 the
  last three are 0x40072a54, 0x4009d128 and 0x4009e53c; the rest are where
  they were.

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core-dn1 --stock Digitone_and_Digitone_Keys_OS1.43.syx   # out/core-2.0a.elemod
python -m elekloader.sdk.build mods/core-dn1 --stock Digitone_and_Digitone_Keys_OS1.44.syx   # out/core-2.0a-os1.44.elemod
python -m elekloader.lint mods/core-dn1/out/core-2.0a-os1.44.elemod --stock Digitone_and_Digitone_Keys_OS1.44.syx
```

A release names them `core-dn1-2.0a.elemod` and `core-dn1-2.0a-os1.44.elemod`.

Checked by cold-booting it in digikit's emulator against stock (docs/DEVICES.md):
- every stage passes, and every screen is identical;
- the audio is identical up to PLAY, then the same sound slightly shifted in
  time, as stock's own is when PLAY lands 0.3 ms later.

The 1.44 port has not been run in an emulator: digikit's Digitone support
does not yet boot stock 1.44 to a settled screen. It is the same code with
1.44's addresses. Its eight sites hold the same stock bytes as 1.43's, and
each routine it calls was found again by its own code, with the addresses
in it masked, and checked against the code that calls it. It lints and
links, and a build with it verifies, depacking in place.
