# Direct perform (Digitakt II)

A mod for Digitakt II OS 1.17, and an example of a real one: one key
handler.

- **Stock:** [PRESET] opens the PRESET/KIT menu; [FUNC] + [PRESET] toggles
  PERFORM (Perform Kit).
- **With this mod:** [PRESET] alone toggles PERFORM, quicker to reach while
  playing live; [FUNC] + [PRESET] opens the PRESET/KIT menu.

How it works (`perform.c`): core's `ev_key` hands it every key event first.
For [PRESET]'s events (key 7) it flips the flag the firmware reads as
"[FUNC] held" (0x2 in the event's flags) and lets the firmware go on, so
each combination does what the other one did.

```bash
python -m elekloader.sdk.build mods/core-dt2 --stock Digitakt_II_OS1.17.syx
python -m elekloader.sdk.build examples/perform-direct --stock Digitakt_II_OS1.17.syx
python -m elekloader.patch --stock Digitakt_II_OS1.17.syx \
    --mod mods/core-dt2/out/core-1.0.elemod \
    --mod examples/perform-direct/out/perform-direct-1.0.elemod --out perform.syx --version PD10
```

Checked in digikit's emulator, on a cold boot of core-dt2 with this mod:
the boot passes as stock does, [PRESET] alone toggles Perform Kit and
[FUNC] + [PRESET] opens the PRESET/KIT menu. Confirmed on a unit (an
earlier version, which also had an on/off row in PERSONALIZE).
