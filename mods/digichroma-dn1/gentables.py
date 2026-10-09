"""DigiChroma's constant tables (tables.h): waveshapers, sine, exp2, filter coefficients, knob curves.
python3 gentables.py > tables.h"""
import math

FS = 48000.0
out = []


def arr(ctype, name, vals, per=12):
    out.append('static const %s %s[%d] = {' % (ctype, name, len(vals)))
    for i in range(0, len(vals), per):
        out.append('    ' + ', '.join(str(v) for v in vals[i:i + per]) + ',')
    out.append('};')


def clip16(v):
    return max(-32768, min(32767, int(round(v))))


def knob(fn, n=129):
    """A knob's curve: 129 values, so 0-127 interpolates with its fraction (the last repeats 127's)."""
    return [fn(min(k, 127) / 127.0) for k in range(n)]


# ---- waveshapers: 1025 points over -4.0 .. +4.0 of full scale (32768), Q15 out --------------------------
def shaper(name, f):
    arr('int16_t', name, [clip16(32767 * f(-4.0 + 8.0 * i / 1024)) for i in range(1025)], 16)


B = 0.12                # the tube's bias: even harmonics
shaper('sh_tube', lambda x: (math.tanh(x + B) - math.tanh(B)) / (1 + math.tanh(B)))
shaper('sh_soft', lambda x: math.tanh(x))
shaper('sh_fuzz', lambda x: x / (1 + abs(x) ** 6) ** (1 / 6.0) * 0.92)          # a hard knee
shaper('sh_tape', lambda x: math.tanh(0.9 * x) * 0.96 + 0.04 * math.tanh(3 * x) * (1 - math.tanh(0.9 * x) ** 2))
# the output's soft clip: straight to 0.8, then a tanh into 1.0
shaper('sh_out', lambda x: x if abs(x) < 0.8 else math.copysign(0.8 + 0.2 * math.tanh((abs(x) - 0.8) / 0.2), x))

arr('int16_t', 'ch_sin', [clip16(32767 * math.sin(2 * math.pi * i / 256)) for i in range(257)], 16)

# 2^(i/256), Q12 (4096..8191): a ratio from an offset in 1/256 octaves.
arr('uint16_t', 'ch_exp2', [int(round(4096 * 2 ** (i / 256.0))) for i in range(256)], 16)


# ---- one-pole coefficients: a = 1 - exp(-2 pi f / fs), Q14, f 20 Hz .. 20 kHz over 256 log steps --------
def op_f(i):
    return 20.0 * 1000.0 ** (i / 255.0)


arr('int16_t', 'ch_op', [int(round(16384 * (1 - math.exp(-2 * math.pi * op_f(i) / FS)))) for i in range(256)], 16)

# Phaser: a first-order allpass's coefficient (tan - 1)/(tan + 1), Q15, 60 Hz .. 6 kHz over 256 log steps.
arr('int16_t', 'ch_ap', [clip16(32767 * (math.tan(math.pi * 60.0 * 100.0 ** (i / 255.0) / FS) - 1)
                                / (math.tan(math.pi * 60.0 * 100.0 ** (i / 255.0) / FS) + 1)) for i in range(256)], 16)

# Howl: the Chamberlin SVF's f = 2 sin(pi fc / fs), Q14, 60 Hz .. 7 kHz over 256 log steps.
arr('int16_t', 'ch_svf', [int(round(16384 * 2 * math.sin(math.pi * 60.0 * (7000 / 60.0) ** (i / 255.0) / FS)))
                          for i in range(256)], 16)

# ---- knob curves (129 entries) ----------------------------------------------------------------------------
# Volumes (EFFECT VOL, OUTPUT LEVEL): 64 is 0 dB; -36 dB at 1, 0 mutes; +12 dB at 127. Q12.
def vol(u):
    k = u * 127
    if k < 0.5:
        return 0
    db = (k - 64) * 12 / 63.0 if k >= 64 else (k - 64) * 36 / 63.0
    return int(round(4096 * 10 ** (db / 20)))


arr('int16_t', 'ch_vol', knob(vol), 16)
# TILT: shelf gains, +-9 dB about 64; Q12, the low side and the high side.
arr('int16_t', 'ch_tilt_lo', knob(lambda u: int(round(4096 * 10 ** (-(u - 0.5039) * 2 * 9 / 20)))), 16)
arr('int16_t', 'ch_tilt_hi', knob(lambda u: int(round(4096 * 10 ** ((u - 0.5039) * 2 * 9 / 20)))), 16)
# Mix: equal power, Q12.
arr('int16_t', 'ch_mix_dry', knob(lambda u: int(round(4096 * math.cos(math.pi / 2 * u)))), 16)
arr('int16_t', 'ch_mix_wet', knob(lambda u: int(round(4096 * math.sin(math.pi / 2 * u)))), 16)
# Rates in milli-hertz, exponential: 0.05 .. 16 Hz.
arr('int32_t', 'ch_rate', knob(lambda u: int(round(1000 * 0.05 * 320.0 ** u))), 12)
# Delay times in frames, exponential: 30 ms .. 700 ms (Cascade, Reels).
arr('int32_t', 'ch_dtime', knob(lambda u: int(round(FS * 0.030 * (0.700 / 0.030) ** u))), 12)
# Collage's loop: 40 ms .. 2.5 s.
arr('int32_t', 'ch_ctime', knob(lambda u: int(round(FS * 0.040 * (2.5 / 0.040) ** u))), 12)
# Doubler: 6 ms .. 110 ms.
arr('int32_t', 'ch_dbl', knob(lambda u: int(round(FS * 0.006 * (0.110 / 0.006) ** u))), 12)
# Drive's gain (Q8): 1x .. 40x; and its make-up (Q12): a -16 dBFS input comes out at about its own level.
arr('int32_t', 'ch_drive', knob(lambda u: int(round(256 * 40.0 ** u))), 12)
arr('int16_t', 'ch_drive_mk', knob(lambda u: int(round(4096 * 0.16 / math.tanh(0.16 * 40.0 ** u)))), 16)
# Fuzz's gain (Q8): 3x .. 300x.
arr('int32_t', 'ch_fuzz', knob(lambda u: int(round(256 * 3.0 * 100.0 ** u))), 12)

print('/* SPDX-License-Identifier: GPL-2.0-or-later */')
print('/* DigiChroma\'s constant tables, from gentables.py: do not edit. */')
print('\n'.join(out))
