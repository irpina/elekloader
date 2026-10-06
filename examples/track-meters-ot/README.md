# Track meters (Octatrack)

Eight live track meters in the screen's bottom-right corner, over every
page. Each one is a track's audio after its effects and before its fader,
rising at once and falling over about 0.4 s. A demo of the Octatrack core's
hook bus (core-ot 0.2).

## How it works

| event | what it does |
|---|---|
| `ev_frame` (the audio interrupt, every 16 samples) | the peak of each track's block, from the read-back the DSP leaves for the ColdFire. TUNER and the USB audio mods read the same memory in the same interrupt |
| `ev_tick` (60 Hz) | each peak becomes a bar height, 2 pixels for each 6 dB |
| `ev_draw` | the bars, in a dark box 25 × 27 pixels |

## Why the bus

The screen has one point where a mod can draw over it: the moment the
compositor has built a frame and before it goes to the LCD. With patches,
the first mod to take that point owns it, and a second one that draws is
refused:

```
meters-patch 1.0 site 0x40013cae and cc-who-patch 1.0 site 0x40013cae overlap
```

On the bus, every mod that draws subscribes to `ev_draw`, each over the
last. With [cc-who-ot](../cc-who-ot) beside it, CC WHO's box is in the top
right and the meters are in the bottom right, in the same frame. The audio
interrupt is shared the same way: the meters, TUNER and the USB audio mods
all subscribe to `ev_frame`.

## Build

```bash
python -m elekloader.sdk.build examples/track-meters-ot --stock OCTATRACK_OS1.40C.syx
```

It needs the core 0.2 or newer.
