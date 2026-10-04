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
- **From 2.1, `ev_voice_on`** ([voice.s](voice.s)), which the Digitakt's
  core does not have: at 0x4009e928 (0x4009e948 in 1.44), where the
  render's note-on loop stores a voice's pitch word (the note << 16, at
  `0x41391f80` + 4 x voice; `0x41392f80` in 1.44), it
  makes that store itself and calls `f(voice, track, event)`. A handler
  may change the pitch word: the render reads it every block, so a change
  is heard within about three blocks. The voice's sound and the step's
  locks are loaded after this point; read the voice's parameters from
  `ev_render_out`.
- **From 2.1, parameter slots** ([params.s](params.s)): ids 182-184 for
  mods' own parameters, handled by the stock UI as its own (knob, pop-up,
  value, p-locks). At boot `core_dn_boot` moves the two small tables after
  the stock parameter records to `core_ptab_save` and installs the records
  contributed to `core_params` in their place; the firmware's 58 id
  bounds are raised by three, and the UI record lookups build each slot's
  record from the stock one it borrows (docs/ADAPTING.md, "Parameter
  slots").
- **From 2.1, mod pages** ([pages.s](pages.s)): pages 27-30 for mods,
  each put after a stock page in its key's list (AMP's third page, say)
  and shown, turned and p-locked by the stock UI. The page record lookup
  serves them, the views' builder puts them in their key's list, and
  `core_page_open` opens one from a key handler, `core_page_shown` says
  whether it is on screen (docs/ADAPTING.md, "Mod pages").
- **From 2.1, project data** ([projdata.s](projdata.s)): mods' blocks
  saved and loaded with the project, in the 480 bytes of its storage
  header the OS leaves alone. The serializer's entry puts them there for
  every save; the loads and the new project's builder take them out, or
  tell the mod there are none (docs/ADAPTING.md, "Project data").
- **OS 1.44:** every 2.1 site has its port (`ports` in mod.json): the same
  code, moved, and RAM 0x1000 further on.

Build it with the SDK (it needs m68k binutils):

```bash
python -m elekloader.sdk.build mods/core-dn1 --stock Digitone_and_Digitone_Keys_OS1.43.syx   # out/core-2.1.elemod
python -m elekloader.sdk.build mods/core-dn1 --stock Digitone_and_Digitone_Keys_OS1.44.syx   # out/core-2.1-os1.44.elemod
python -m elekloader.lint mods/core-dn1/out/core-2.1-os1.44.elemod --stock Digitone_and_Digitone_Keys_OS1.44.syx
```

A release names them `core-dn1-2.1.elemod` and `core-dn1-2.1-os1.44.elemod`.

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
