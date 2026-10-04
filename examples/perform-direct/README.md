# Direct perform (Digitakt II)

A mod for Digitakt II OS 1.17, and an example of a real one: a key handler
and a PERSONALIZE option.

- **Stock:** [PRESET] opens the PRESET/KIT menu; [FUNC] + [PRESET] toggles
  PERFORM (Perform Kit).
- **With DIRECT PERFORM ticked:** [PRESET] alone toggles PERFORM, quicker
  to reach while playing live; [FUNC] + [PRESET] opens the PRESET/KIT menu.

The option is a checkbox row at the end of SETTINGS > PERSONALIZE, drawn and
changed like the firmware's own (select toggles it, LEFT and RIGHT set it).
It is on after every power-on: the firmware's settings store has no place
for it.

How it works (`perform.c`): core's `ev_key` hands it every key event first.
For [PRESET]'s events (key 7) it flips the flag the firmware reads as
"[FUNC] held" (bit 2 of the event's flags) and lets the firmware go on, so
each combination does what the other one did. The row comes from core-dt2's
`ev_personalize` and `core_additem`; `perform_label.s` is its label
callback, which returns a `std::string` through a0.

```bash
python -m elekloader.sdk.build mods/core-dt2 --stock Digitakt_II_OS1.17.syx
python -m elekloader.sdk.build examples/perform-direct --stock Digitakt_II_OS1.17.syx
python -m elekloader.patch --stock Digitakt_II_OS1.17.syx \
    --mod mods/core-dt2/out/core-1.0.elemod \
    --mod examples/perform-direct/out/perform-direct-1.0.elemod --out perform.syx --version PD10
```

Checked in digikit's emulator, on a cold boot of core-dt2 with this mod:
the boot passes as stock does; [PRESET] alone toggles Perform Kit and
[FUNC] + [PRESET] opens the PRESET/KIT menu; the row is at the end of
PERSONALIZE, ticked; YES unticks it, RIGHT ticks it, LEFT unticks it; and
with it off, [PRESET] opens the PRESET/KIT menu as stock. Not run on a unit.
