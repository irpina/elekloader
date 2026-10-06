# CC who (Octatrack)

Which mod took that CC? Send the Octatrack a MIDI CC, and for a moment the
screen's top-right corner says what it was and who got it:

```
CC68=32          CC40=64
> CC MAP         > OT
```

- `> CC MAP`: a mod took it. CC MAP (octabam's, octabam2elemod v1.1) keeps
  CC 62-73 for the FX page-2 knobs. For another number it says `> A MOD`.
- `> OT`: no mod took it, so the Octatrack's own CC handler got it.

It is a demo of what the Octatrack core's hook bus (core-ot 0.2) makes
possible, and the smallest example of two mods sharing one input.

## How it works

Every MIDI message goes through core's `ev_midi` event: to each subscriber in
turn, in `order`, until one takes it, then to the firmware's handler if none
did. This mod subscribes twice, and takes nothing:

| handler | order | runs |
|---|---|---|
| `ccwho_first` | 10, before the shipped mods | for every CC: it notes it |
| `ccwho_last` | 90, after them | only for a CC no mod took |

So when `ccwho_last` doesn't run for a CC, a mod in between kept it. `ev_draw`
shows the result over whatever is on screen, and `ev_tick` hides it after
1.5 s.

## Why the bus

Without the bus, CC MAP repoints the firmware's one CC handler (the MIDI
dispatch entry at 0x400d64a0) at its own code. This mod's twin, written the
same way, patches the same four bytes, and elekloader refuses the pair:

```
octabam-cc-map 363861e site 0x400d64a0 and cc-who-patch 1.0 site 0x400d64a0 overlap
```

Even placed elsewhere, a patch can't see what CC MAP decided without
wrapping CC MAP's own code. octabam does that with a hand-written bridge for
each pair of modules. On the bus both mods subscribe and run in order, and
neither knows about the other.

## Build

```bash
python -m elekloader.sdk.build examples/cc-who-ot --stock OCTATRACK_OS1.40C.syx
```

Add it with the core (0.2 or newer), and with CC MAP's `-bus` file to see
`> CC MAP`.
