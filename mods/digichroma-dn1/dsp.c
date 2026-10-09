/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiChroma's render: core-dn1 calls dchroma_render at interrupt level for every block while it has the
 * output, 32 frames, 667 us. With the source INPUTS it owns the audio (the master stage does not run, the synths
 * are muted): in is the audio inputs. With DIGITONE (core-dn1 3.3) it is an insert (CORE_AUDIO_INSERT): in is
 * what the master stage made, the synths, the inputs as the mixer has them, chorus, delay and reverb. The chain:
 *   in -> CAPTURE (pre-FX) -> the four modules, in their order -> MIX with the dry -> CAPTURE (post-FX)
 *   -> OUTPUT LEVEL -> a soft clip -> out
 * Fixed point: samples are Q15 in an int32 (32768 is full scale), with 6 dB of headroom (+-65535) between
 * the modules; the delay lines hold s16 at half scale. Knobs are 0-127; the render smooths them in 8.8.
 * The Digitone's own render takes over half of every block, so this one is lean: the loops go a frame at a
 * time with their filters' state in locals, slow modulation is worked out a block at a time and ramped
 * across it, and Space's network runs at half the rate. */
#pragma GCC optimize ("no-tree-loop-distribute-patterns")
#include "dchroma.h"
#include "tables.h"

#define N       32
#ifndef DTCN0
#define DTCN0   (*(volatile u32 *)0xFC07000Cu)  /* DMA timer 0's counter: the bus clock */
#endif
#define TOP     65535                           /* a sample's bound between the modules */

struct dh_state dchroma;
struct core_audio_owner dchroma_owner = { 0, dchroma_render, CORE_AUDIO_MUTE_VOICES };   /* the UI sets flags */

/* The modules' orders: C(haracter) M(ovement) D(iffusion) T(exture); 0 is the Chroma Console's own. */
const u8 ch_order[24][4] = {
    {0, 1, 2, 3}, {0, 1, 3, 2}, {0, 2, 1, 3}, {0, 2, 3, 1}, {0, 3, 1, 2}, {0, 3, 2, 1},
    {1, 0, 2, 3}, {1, 0, 3, 2}, {1, 2, 0, 3}, {1, 2, 3, 0}, {1, 3, 0, 2}, {1, 3, 2, 0},
    {2, 0, 1, 3}, {2, 0, 3, 1}, {2, 1, 0, 3}, {2, 1, 3, 0}, {2, 3, 0, 1}, {2, 3, 1, 0},
    {3, 0, 1, 2}, {3, 0, 2, 1}, {3, 1, 0, 2}, {3, 1, 2, 0}, {3, 2, 0, 1}, {3, 2, 1, 0} };

/* ---- helpers --------------------------------------------------------------------------------------- */
static inline s32 lim(s32 v, s32 l) { return v > l ? l : v < -l ? -l : v; }
static inline s32 sat16(s32 v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : v; }
static inline s32 absv(s32 v) { return v < 0 ? -v : v; }

static u32 seed = 0x2545f491u;
static inline u32 rnd(void) { seed = seed * 1664525u + 1013904223u; return seed; }
static inline s32 rnd_s(void) { return (s32)(rnd() >> 17) - 16384; }          /* -16384 .. 16383 */
static inline u32 rnd_n(u32 n) { return ((rnd() >> 16) * n) >> 16; }        /* 0 .. n-1, n < 65536 */

/* A knob's curve (129 entries) at kq, the knob in 8.8 */
static inline s32 kt(const s16 *t, s32 kq) { s32 i = kq >> 8, f = kq & 255; return t[i] + (((t[i + 1] - t[i]) * f) >> 8); }
static inline s32 kt32(const s32 *t, s32 kq) { s32 i = kq >> 8, f = kq & 255; return t[i] + (((t[i + 1] - t[i]) * f) >> 8); }

static inline s32 sinq(u32 ph)                  /* Q15 */
{
    s32 i = (s32)(ph >> 24), f = (s32)((ph >> 16) & 255);
    return ch_sin[i] + (((ch_sin[i + 1] - ch_sin[i]) * f) >> 8);
}

static inline s32 shape(const s16 *t, s32 v)    /* a waveshaper over -4.0 .. 4.0 of full scale, Q15 out */
{
    u32 u;
    s32 i, f;
    if (v > 131071) v = 131071;
    else if (v < -131072) v = -131072;
    u = (u32)(v + 131072);
    i = (s32)(u >> 8);
    f = (s32)(u & 255);
    return t[i] + (((t[i + 1] - t[i]) * f) >> 8);
}

/* A one-pole low-pass on a local state st (the output x 256, so slow ones settle); a is Q14 (ch_op), x within
 * +-65535. The value is the new output. */
#define LP(st, x, a)    ((st) += (((x) - ((st) >> 8)) * (a)) >> 6, (st) >> 8)

static s32 exp2_q12(s32 o)                      /* 4096 x 2^(o/256) */
{
    s32 r = ch_exp2[o & 255], sh = o >> 8;
    return sh >= 0 ? r << sh : r >> -sh;
}

/* A line of s16 frames, L,R, at half scale: the sample at d12 (frames, Q12) behind frame w. */
static inline s32 rdl(const s16 *L, u32 mask, u32 w, u32 d12, int c)
{
    u32 p = (w << 12) - d12, a = (p >> 12) & mask, b = (a + 1) & mask;
    s32 f = (s32)(p & 0xfff), x0 = L[2 * a + c], x1 = L[2 * b + c];
    return (x0 + (((x1 - x0) * f) >> 12)) << 1;
}

static inline u32 lfo_inc(s32 mhz) { return (u32)((mhz * 5726) >> 6); }      /* a frame's phase step */

static inline s32 tri(u32 p)                    /* a triangle, 0 at 0, 32767 at half way */
{
    return (s32)((p < 0x80000000u ? p : ~p) >> 16);
}

static void gain(s32 *w, s32 g)                 /* a module's EFFECT VOL, Q12; 4096 is 0 dB */
{
    int i;
    if (g > 4092 && g < 4100)
        return;
    for (i = 0; i < 2 * N; i++)
        w[i] = lim((w[i] * g) >> 12, TOP);
}

/* ---- the block's knobs, clock and gain ------------------------------------------------------------ */
static s32 sk[8], ss[8];                        /* the knobs and the secondaries, 8.8, smoothed */
static s32 ek[8];                               /* the knobs this block, 8.8, gestures and all */
static s32 gin;                                 /* the input level (calibration) x SENSITIVITY, Q12 */
static u32 qfr;                                 /* frames a quarter note, 0 when the clock is free */
static int drop_x;                              /* the trails: the chain gets silence */

static const s16 cal_gain[4] = { 16345, 8173, 4096, 2053 };     /* LOW +12 dB .. VERY HIGH -6 dB */

u32 dchroma_tempo(void)
{
    u32 t;
    if (dchroma.clock == CL_TEMPO)
        t = (u32)fw_tempo;
    else if (dchroma.clock == CL_TAP)
        t = dchroma.tap;
    else
        return 0;
    return t < 2400 || t > 48000 ? 0 : t;       /* 20-400 BPM */
}

/* GESTURE: each knob's own loop of its values, 94 a second (one every 16 blocks), played at the clock's
 * tempo against the tempo it was recorded at. */
static u32 gpos[8], glen[8], gtempo[8], gtick;

static void gestures_block(u32 tempo)
{
    u8 *G = DH_GEST;
    int k;
    if (++gtick >= 16) {
        gtick = 0;
        for (k = 0; k < 8; k++) {
            u8 st = dchroma.gstate[k];
            if (dchroma.gkill[k]) {
                dchroma.gkill[k] = 0;
                st = G_NONE;
            }
            if (dchroma.grec && dchroma.gtouch[k]) {
                dchroma.gtouch[k] = 0;
                st = G_REC;
                glen[k] = 0;
                gtempo[k] = tempo;
            }
            if (st == G_REC) {
                if (!dchroma.grec || glen[k] >= DH_GEST_N) {
                    st = glen[k] >= 2 ? G_PLAY : G_NONE;
                    gpos[k] = 0;
                } else {
                    G[k * DH_GEST_N + glen[k]++] = dchroma.knob[k];
                }
            }
            dchroma.gstate[k] = st;
        }
    }
    for (k = 0; k < 8; k++) {
        if (dchroma.gstate[k] == G_PLAY) {
            const u8 *g = G + k * DH_GEST_N;
            u32 inc = 4096, L = glen[k] << 16, i, f, a, b;
            if (tempo && gtempo[k])
                inc = 4096u * tempo / gtempo[k];
            gpos[k] += inc;
            while (gpos[k] >= L)
                gpos[k] -= L;
            i = gpos[k] >> 16;
            f = (gpos[k] >> 8) & 255;
            a = g[i];
            b = g[i + 1 < glen[k] ? i + 1 : 0];
            ek[k] = (s32)(a << 8) + (((s32)b - (s32)a) * (s32)f);
        } else {
            ek[k] = dchroma.knob[k] << 8;
        }
        dchroma.eff[k] = (u8)(ek[k] >> 8);
    }
}

static void knobs_block(void)
{
    int k;
    for (k = 0; k < 8; k++) {
        sk[k] += (ek[k] - sk[k]) >> 2;
        ss[k] += ((dchroma.sec[k] << 8) - ss[k]) >> 2;
    }
    gin = (cal_gain[dchroma.level & 3] * exp2_q12((ss[S_SENS] - 16384) >> 5)) >> 12;   /* SENS: +-12 dB */
}

/* A synced time: the knob picks one of n subdivisions, in quarter notes x 24. */
static u32 sync_frames(s32 kq, const u16 *div24, int n)
{
    int i = (kq * n) >> 15;
    if (i >= n)
        i = n - 1;
    return qfr * div24[i] / 24u;
}

static const u16 dly_div[7] = { 3, 4, 6, 8, 12, 18, 24 };          /* 1/32 1/16T 1/16 1/8T 1/8 1/8D 1/4 */
static const u16 col_div[6] = { 6, 12, 24, 48, 96, 192 };          /* 1/16 1/8 1/4 1/2 1 bar, 2 bars */
static const u16 lfo_div[9] = { 192, 96, 48, 24, 12, 8, 6, 4, 3 }; /* an LFO's cycle: 2 bars .. 1/32 */

static s32 rate_mhz(s32 kq, s32 lo_kq)          /* a modulation rate: free on the knob's curve, or synced */
{
    if (qfr) {
        u32 fr = sync_frames(kq, lfo_div, 9);
        return fr ? (s32)(48000000u / fr) : 1000;
    }
    return kt32(ch_rate, lo_kq + (((32512 - lo_kq) * (kq >> 7)) >> 8));
}

struct rwalk { s32 rs, rt; u32 cnt; };          /* a smoothed random wave (DRIFT): -32768 .. 32767 */

static s32 rwalk_step(struct rwalk *r, u32 frames)  /* a new random target every so many frames, glided to */
{
    r->cnt += N;
    if (r->cnt >= frames) {
        r->cnt = 0;
        r->rt = rnd_s() * 2;
    }
    r->rs += (r->rt - r->rs) >> 4;
    return r->rs;
}

/* ---- CHARACTER ------------------------------------------------------------------------------------ */
static s32 c_t0, c_t1, c_p0, c_p1, c_h0, c_h1, c_d0, c_d1, c_l0, c_l1, c_i0, c_i1;
static s32 c_env, c_g = 4096;                   /* SWEETEN's compressor */
static s32 h_l0, h_l1, h_b0, h_b1, h_env, h_fi; /* HOWL */
static s32 sw_env, sw_g, sw_arm = 1;            /* SWELL: its follower, gain (Q23), armed */

static void tilt_eq(s32 *w, s32 kq)             /* TILT: +-9 dB shelves about 650 Hz; flat in the middle */
{
    s32 gl = kt(ch_tilt_lo, kq), gh = kt(ch_tilt_hi, kq), a = ch_op[128], t0 = c_t0, t1 = c_t1;
    int i;
    if (gl > 4088 && gl < 4104 && gh > 4088 && gh < 4104)
        return;
    for (i = 0; i < N; i++) {
        s32 x0 = w[2 * i], x1 = w[2 * i + 1], l0 = LP(t0, x0, a), l1 = LP(t1, x1, a);
        w[2 * i] = lim(((l0 * gl) >> 12) + (((x0 - l0) * gh) >> 12), TOP);
        w[2 * i + 1] = lim(((l1 * gl) >> 12) + (((x1 - l1) * gh) >> 12), TOP);
    }
    c_t0 = t0, c_t1 = t1;
}

static void m_char(s32 *w)
{
    s32 tilt = sk[K_TILT], amt = sk[K_CAMT];
    int i;
    switch (dchroma.fx[M_CHAR]) {
    case FX_DRIVE: {                            /* tube-like: TILT before the drive, and its tone after */
        s32 G = (kt32(ch_drive, amt) * gin) >> 12, cap = 33554432 / G, mk = kt(ch_drive_mk, amt);
        s32 pa = ch_op[185 + ((tilt * 51) >> 15)];                  /* 3 .. 12 kHz */
        s32 p0 = c_p0, p1 = c_p1, d0 = c_d0, d1 = c_d1, s0 = 0, s1 = 0;
        tilt_eq(w, tilt);
        for (i = 0; i < N; i++) {
            s32 y0 = shape(sh_tube, (lim(w[2 * i], cap) * G) >> 8), y1 = shape(sh_tube, (lim(w[2 * i + 1], cap) * G) >> 8);
            s0 += y0;
            s1 += y1;
            y0 = ((y0 - d0) * mk) >> 12;        /* the tube's bias: its DC, a block behind */
            y1 = ((y1 - d1) * mk) >> 12;
            w[2 * i] = LP(p0, y0, pa);
            w[2 * i + 1] = LP(p1, y1, pa);
        }
        c_p0 = p0, c_p1 = p1;
        c_d0 = d0 + (((s0 >> 5) - d0) >> 4);
        c_d1 = d1 + (((s1 >> 5) - d1) >> 4);
        break;
    }
    case FX_SWEETEN: {                          /* a preamp: a smile EQ, compression, gentle saturation */
        s32 gb = (amt * 1434) >> 15, gp = (amt * 1843) >> 15, thr = 8000 * 4096 / gin, pk = 0, g0 = c_g, g1;
        s32 drive = 256 + ((amt * 512) >> 15), mk = 4096 * 256 / drive, al = ch_op[74], ah = ch_op[185];
        s32 l0 = c_l0, l1 = c_l1, i0 = c_i0, i1 = c_i1;
        for (i = 0; i < N; i++) {
            s32 x0 = w[2 * i], x1 = w[2 * i + 1], lo0 = LP(l0, x0, al), lo1 = LP(l1, x1, al);
            s32 hi0 = x0 - LP(i0, x0, ah), hi1 = x1 - LP(i1, x1, ah);
            x0 = lim(x0 + ((lo0 * gb) >> 12) + ((hi0 * gp) >> 12), TOP);
            x1 = lim(x1 + ((lo1 * gb) >> 12) + ((hi1 * gp) >> 12), TOP);
            w[2 * i] = x0;
            w[2 * i + 1] = x1;
            x0 = absv(x0) > absv(x1) ? absv(x0) : absv(x1);
            if (x0 > pk)
                pk = x0;
        }
        c_l0 = l0, c_l1 = l1, c_i0 = i0, c_i1 = i1;
        c_env = pk > c_env ? pk : (c_env * 32623) >> 15;            /* release 150 ms */
        if (c_env > thr) {                                         /* ratio 1:1 .. 4:1 */
            s32 r = 4096 + ((amt * 12288) >> 15);
            g1 = (thr + ((c_env - thr) * 4096) / r) * 4096 / c_env;
        } else {
            g1 = 4096;
        }
        c_g = g1;
        for (i = 0; i < N; i++) {
            s32 g = (g0 + (((g1 - g0) * i) >> 5)) * drive >> 8;
            w[2 * i] = (shape(sh_soft, (w[2 * i] * g) >> 12) * mk) >> 12;
            w[2 * i + 1] = (shape(sh_soft, (w[2 * i + 1] * g) >> 12) * mk) >> 12;
        }
        break;
    }
    case FX_FUZZ: {                             /* TILT: tightness, bias and tone together */
        s32 G = (kt32(ch_fuzz, amt) * (gin >> 4)) >> 8, cap, bias = ((tilt - 16384) * 8) >> 4;
        s32 ah = ch_op[39 + ((tilt * 91) >> 15)], al = ch_op[151 + ((tilt * 75) >> 15)], a0 = ch_op[0];
        s32 h0 = c_h0, h1 = c_h1, d0 = c_d0, d1 = c_d1, p0 = c_p0, p1 = c_p1;
        if (G < 256)
            G = 256;
        cap = 33554432 / G;
        for (i = 0; i < N; i++) {
            s32 x0 = w[2 * i], x1 = w[2 * i + 1], y0, y1;
            x0 -= LP(h0, x0, ah);
            x1 -= LP(h1, x1, ah);
            y0 = shape(sh_fuzz, ((lim(x0, cap) * G) >> 8) + bias);
            y1 = shape(sh_fuzz, ((lim(x1, cap) * G) >> 8) + bias);
            y0 -= LP(d0, y0, a0);
            y1 -= LP(d1, y1, a0);
            w[2 * i] = (LP(p0, y0, al) * 5) >> 5;
            w[2 * i + 1] = (LP(p1, y1, al) * 5) >> 5;
        }
        c_h0 = h0, c_h1 = h1, c_d0 = d0, c_d1 = d1, c_p0 = p0, c_p1 = p1;
        break;
    }
    case FX_HOWL: {                             /* a fuzz into a resonant filter; the envelope opens it */
        s32 G = (((kt32(ch_drive, amt) * 3) >> 1) * (gin >> 4)) >> 8, cap = 33554432 / (G > 256 ? G : 256), pk = 0, f, q;
        s32 base = 30 + ((tilt * 140) >> 15), depth = (tilt * 110) >> 15, fi;
        s32 l0 = h_l0, l1 = h_l1, b0 = h_b0, b1 = h_b1;
        for (i = 0; i < 2 * N; i++)
            if (absv(w[i]) > pk)
                pk = absv(w[i]);
        h_env = pk > h_env ? pk : h_env - ((h_env * (8 + (tilt >> 10))) >> 10);   /* stabs decay faster */
        fi = base + ((lim(h_env, 32767) * depth) >> 15);
        h_fi += (fi - h_fi) >> 1;
        f = ch_svf[h_fi > 255 ? 255 : h_fi];
        q = 4096 - ((amt * 2900) >> 15);                            /* damping 0.25 .. 0.07 */
        for (i = 0; i < N; i++) {
            s32 x0 = (shape(sh_soft, (lim(w[2 * i], cap) * G) >> 8) * q) >> 14;     /* as loud at any resonance */
            s32 x1 = (shape(sh_soft, (lim(w[2 * i + 1], cap) * G) >> 8) * q) >> 14, hh;
            hh = lim(x0 - l0 - ((q * b0) >> 14), TOP);
            b0 = lim(b0 + ((f * hh) >> 14), TOP);
            l0 = lim(l0 + ((f * b0) >> 14), TOP);
            hh = lim(x1 - l1 - ((q * b1) >> 14), TOP);
            b1 = lim(b1 + ((f * hh) >> 14), TOP);
            l1 = lim(l1 + ((f * b1) >> 14), TOP);
            w[2 * i] = (l0 + (b0 >> 1)) >> 1;
            w[2 * i + 1] = (l1 + (b1 >> 1)) >> 1;
        }
        h_l0 = l0, h_l1 = l1, h_b0 = b0, h_b1 = b1;
        break;
    }
    default: {                                  /* SWELL: each note fades in; AMOUNT its attack and decay */
        s32 on = 1000 * 4096 / gin, off = on >> 1, A = kt32(ch_ctime, amt), up = (32767 << 8) / A, dn = up * 2;
        s32 env = sw_env, g8 = sw_g;
        int arm = sw_arm;
        tilt_eq(w, tilt);
        for (i = 0; i < N; i++) {
            s32 e0 = absv(w[2 * i]), e1 = absv(w[2 * i + 1]), e = e0 > e1 ? e0 : e1, g;
            env += e > env ? (e - env) >> 4 : -(env >> 10);
            if (arm && env > on) {
                arm = 0;
                g8 = 0;                         /* a new note: from silence */
            } else if (env < off) {
                arm = 1;
            }
            if (!arm)
                g8 = g8 + up > (32767 << 8) ? 32767 << 8 : g8 + up;
            else
                g8 = g8 > dn ? g8 - dn : 0;
            g = g8 >> 8;
            w[2 * i] = (w[2 * i] * g) >> 15;
            w[2 * i + 1] = (w[2 * i + 1] * g) >> 15;
        }
        sw_env = env, sw_g = g8, sw_arm = arm;
        break;
    }
    }
    gain(w, kt(ch_vol, ss[S_CVOL]));
}

/* ---- MOVEMENT ------------------------------------------------------------------------------------- */
static u32 mw;                                  /* Movement's line: the next frame written */
static u32 m_ph;                                /* the LFO */
static struct rwalk mrw, drw;
static u32 m_rcnt;
static s32 d_cur[2], d_wob[2];                  /* DOUBLER */
static s32 ap_x[12], ap_y[12], ap_last, ap_prev;    /* PHASER */
static s32 tr_rate = 1000, tr_depth, tr_g0 = 32767, tr_g1 = 32767;  /* TREMOLO */
static s32 vb_d0, vb_d1;                        /* VIBRATO's delays at the block's end */
static u32 ps_ph;                               /* PITCH's heads */
static s32 ps_hold0, ps_hold1, ps_hcnt;

static void m_move(s32 *w)
{
    s16 *M = DH_MOVE;
    s32 rate = sk[K_RATE], amt = sk[K_MAMT], drift = ss[S_MDRIFT];
    u32 msk = DH_MOVE_FR - 1, w0 = mw;
    int i, fx = dchroma.fx[M_MOVE];
    if (fx != FX_TREMOLO && fx != FX_PHASER) {  /* the line first: every read is at least a frame back */
        for (i = 0; i < N; i++) {
            u32 p = 2 * ((w0 + i) & msk);
            M[p] = (s16)sat16(w[2 * i] >> 1);
            M[p + 1] = (s16)sat16(w[2 * i + 1] >> 1);
        }
    }
    mw = (w0 + N) & msk;
    w0 = (w0 + 1) & msk;                        /* frame i was written at w0 + i - 1 */
    switch (fx) {
    case FX_DOUBLER: {                          /* two voices at their own short delays; DRIFT: pitch jumps */
        s32 base = kt32(ch_dbl, rate) << 12, wet = (amt * 3482) >> 15, dry = 4096 - ((amt * 1229) >> 15);
        s32 a0 = d_cur[0], a1 = d_cur[1], s0, s1, t0, t1;
        m_rcnt += N;
        if (m_rcnt > 9600u - (u32)(drift >> 2)) {
            m_rcnt = 0;
            d_wob[0] = rnd_s() * (5 + ((drift * 37) >> 15));        /* +-0.4 ms .. +-3.5 ms, Q12 frames */
            d_wob[1] = rnd_s() * (5 + ((drift * 37) >> 15));
        }
        t0 = base + d_wob[0];
        t1 = ((base >> 8) * 197) + d_wob[1];                        /* R a little shorter */
        d_cur[0] += (t0 - d_cur[0]) >> (drift > 16384 ? 2 : 5);
        d_cur[1] += (t1 - d_cur[1]) >> (drift > 16384 ? 2 : 5);
        if (d_cur[0] < (64 << 12)) d_cur[0] = 64 << 12;
        if (d_cur[1] < (64 << 12)) d_cur[1] = 64 << 12;
        s0 = (d_cur[0] - a0) >> 5;
        s1 = (d_cur[1] - a1) >> 5;
        for (i = 0; i < N; i++) {
            s32 v0 = rdl(M, msk, w0 + i, (u32)a0, 0), v1 = rdl(M, msk, w0 + i, (u32)a1, 1);
            w[2 * i] = lim(((w[2 * i] * dry) >> 12) + ((v0 * wet) >> 12), TOP);
            w[2 * i + 1] = lim(((w[2 * i + 1] * dry) >> 12) + ((v1 * wet) >> 12), TOP);
            a0 += s0;
            a1 += s1;
        }
        break;
    }
    case FX_VIBRATO: {                          /* a delay swept by the LFO; DRIFT: random and wider */
        s32 depth = amt * 24, centre = depth + (48 << 12), dr = drift >> 8, dfr = depth >> 12;
        u32 inc = lfo_inc(rate_mhz(rate, 6400)), off = (u32)dr << 23;
        s32 r = rwalk_step(&mrw, 2400), l0, l1, a0 = vb_d0, a1 = vb_d1, s0, s1;
        m_ph += inc * N;                        /* the LFO at the block's end; the delays ramp to it */
        l0 = sinq(m_ph);
        l1 = sinq(m_ph + off);
        l0 += ((r - l0) * dr) >> 7;
        l1 += ((-r - l1) * dr) >> 7;
        vb_d0 = centre + ((l0 * dfr) >> 3);
        vb_d1 = centre + ((l1 * dfr) >> 3);
        if (a0 < (8 << 12)) a0 = vb_d0;
        if (a1 < (8 << 12)) a1 = vb_d1;
        s0 = (vb_d0 - a0) >> 5;
        s1 = (vb_d1 - a1) >> 5;
        for (i = 0; i < N; i++) {
            w[2 * i] = rdl(M, msk, w0 + i, (u32)a0, 0);
            w[2 * i + 1] = rdl(M, msk, w0 + i, (u32)a1, 1);
            a0 += s0;
            a1 += s1;
        }
        break;
    }
    case FX_PHASER: {                           /* 2-12 allpass stages swept by the LFO, with feedback */
        int n = 2 + 2 * ((amt * 6) >> 15), s;
        s32 fb = (amt * 18000) >> 15, span = 70 + ((amt * 110) >> 15), dr = drift >> 8, a, l, idx, last = ap_last;
        s32 prev = ap_prev;
        u32 inc = lfo_inc(rate_mhz(rate, 0));
        if (n > 12)
            n = 12;
        l = sinq(m_ph);
        l += ((rwalk_step(&mrw, 4800) - l) * dr) >> 7;
        idx = 25 + 38 + (((l + 32768) * span) >> 16);              /* +38: twice the frequency, at half the rate */
        a = ch_ap[idx > 255 ? 255 : idx];
        m_ph += inc * N;
        for (i = 0; i < N; i += 2) {            /* one wet chain at half the rate on the sum, beside each side's dry */
            s32 v = lim(((w[2 * i] + w[2 * i + 1] + w[2 * i + 2] + w[2 * i + 3]) >> 3) + ((last * fb) >> 15), 32767), y, h;
            for (s = 0; s < n; s++) {
                y = lim(((a * (v - ap_y[s]) + 16384) >> 15) + ap_x[s], 32767);
                ap_x[s] = v;
                ap_y[s] = y;
                v = y;
            }
            last = v;
            h = (prev + v) >> 1;
            prev = v;
            w[2 * i] = lim((w[2 * i] >> 1) + h, TOP);
            w[2 * i + 1] = lim((w[2 * i + 1] >> 1) + h, TOP);
            w[2 * i + 2] = lim((w[2 * i + 2] >> 1) + v, TOP);
            w[2 * i + 3] = lim((w[2 * i + 3] >> 1) + v, TOP);
        }
        ap_last = last;
        ap_prev = prev;
        break;
    }
    case FX_TREMOLO: {                          /* AMOUNT: deeper and squarer; DRIFT: unsteady, wider */
        s32 sq = 1 + ((((amt >> 7) * (amt >> 7)) * 15) >> 16), dep = amt, dr = drift >> 8, l0, l1, g0, g1, s0, s1;
        u32 off = (u32)dr << 24, inc;
        s32 target = rate_mhz(rate, 13000);
        inc = lfo_inc(tr_rate);
        if (m_ph < inc * N) {                   /* a new cycle: its drift */
            tr_rate = target + (((target >> 2) * ((rnd_s() * dr) >> 9)) >> 12);     /* +-25% */
            tr_depth = dep - ((dep * ((((s32)rnd_n(32768) * dr) >> 7) >> 2)) >> 14);  /* -50% */
        }
        if (!dr) {
            tr_rate = target;
            tr_depth = dep;
        }
        m_ph += lfo_inc(tr_rate) * N;           /* the gains at the block's end; ramped to */
        l0 = lim(sinq(m_ph) * sq, 32767);
        l1 = lim(sinq(m_ph + off) * sq, 32767);
        g0 = tr_g0, g1 = tr_g1;
        tr_g0 = 32767 - ((tr_depth * ((l0 + 32767) >> 1)) >> 15);
        tr_g1 = 32767 - ((tr_depth * ((l1 + 32767) >> 1)) >> 15);
        s0 = (tr_g0 - g0) >> 5;
        s1 = (tr_g1 - g1) >> 5;
        for (i = 0; i < N; i++) {
            w[2 * i] = (w[2 * i] * g0) >> 15;
            w[2 * i + 1] = (w[2 * i + 1] * g1) >> 15;
            g0 += s0;
            g1 += s1;
        }
        break;
    }
    default: {                                  /* PITCH: two heads over a 43 ms window; DRIFT: lo-fi */
        s32 o = (rate - 16384) >> 6, r, dph, wet = amt, dry = 32767 - amt, crush, hold, h0 = ps_hold0, h1 = ps_hold1;
        int hc = ps_hcnt;
        u32 ph = ps_ph;
        o += (rwalk_step(&mrw, 3600) * (drift >> 8)) >> 19;
        r = exp2_q12(o);
        dph = (4096 - r) * 512;
        crush = (drift * 9) >> 15;
        hold = 1 + ((drift * 5) >> 15);
        for (i = 0; i < N; i++) {
            if (hc == 0) {
                u32 p1 = ph + 0x80000000u, d0 = (ph >> 9) + (2u << 12), d1 = (p1 >> 9) + (2u << 12);
                s32 g0 = tri(ph), g1 = 32767 - g0;                  /* a crossfade: the heads' windows */
                h0 = ((rdl(M, msk, w0 + i, d0, 0) * g0) >> 15) + ((rdl(M, msk, w0 + i, d1, 0) * g1) >> 15);
                h1 = ((rdl(M, msk, w0 + i, d0, 1) * g0) >> 15) + ((rdl(M, msk, w0 + i, d1, 1) * g1) >> 15);
                if (crush) {
                    h0 = (h0 >> crush) << crush;
                    h1 = (h1 >> crush) << crush;
                }
            }
            w[2 * i] = lim(((w[2 * i] * dry) >> 15) + ((h0 * wet) >> 15), TOP);
            w[2 * i + 1] = lim(((w[2 * i + 1] * dry) >> 15) + ((h1 * wet) >> 15), TOP);
            if (++hc >= hold)
                hc = 0;
            ph += (u32)dph;
        }
        ps_hold0 = h0, ps_hold1 = h1, ps_hcnt = hc, ps_ph = ph;
        break;
    }
    }
    gain(w, kt(ch_vol, ss[S_MVOL]));
}

/* ---- DIFFUSION ------------------------------------------------------------------------------------ */
static u32 dw;                                  /* Diffusion's line: the next frame written */
static s32 dl_cur;                              /* the delay, frames Q12, slewed to its target */
static s32 dl_l0, dl_h0, dl_drop = 32767, dl_m;
static u32 dl_ph, dl_ph2;
static u32 cl_skip, cl_t, cl_len, cl_start, cl_cnt;     /* COLLAGE's double-speed loops */
static u32 rv_age[2];                           /* REVERSE's heads: frames into their windows */
static int d_fx = -1;                           /* the effect the delay's time belongs to */

/* Space: four allpasses, then a 4-line feedback delay network with damping, at half the rate (24 kHz,
 * from the average of each two frames, ramped back up); its size, feedback, damping and pre-delay
 * blended across five rooms by TIME (a chamber .. a cloud). */
#define NL 4
static const u16 rv_base[NL] = { 1777, 2129, 2551, 3011 };          /* at 48 kHz */
static const u16 sp_mult[5] = { 90, 154, 256, 410, 620 };          /* Q8 */
static const s16 sp_fb[5] = { 22938, 26214, 28836, 30474, 31785 }; /* Q15 */
static const s16 sp_lp[5] = { 31457, 27525, 22856, 18924, 14336 }; /* Q15: the damping's low-pass at 24 kHz */
static const u16 sp_pre[5] = { 96, 480, 960, 1440, 2400 };         /* frames at 48 kHz */
static const u16 ap_len[4] = { 71, 53, 189, 138 };                 /* at 24 kHz */
static u32 rv_w, ap_w[4];
static s32 rv_lp[NL], rv_yl, rv_yr;

static s32 blend5(const void *t, int is16, s32 kq)
{
    s32 p = kq * 4, i = p >> 15, f = (p >> 7) & 255, a, b;
    if (i >= 4) {
        i = 3;
        f = 256;
    }
    a = is16 ? ((const s16 *)t)[i] : ((const u16 *)t)[i];
    b = is16 ? ((const s16 *)t)[i + 1] : ((const u16 *)t)[i + 1];
    return a + (((b - a) * f) >> 8);
}

static void space(s32 *w, s32 time, s32 amt, s32 drift, s32 wetv)
{
    s16 *R = DH_REV, *D = DH_DIFF;
    u32 len[NL], pre = (u32)blend5(sp_pre, 0, time), msk = DH_DIFF_FR - 1, rw = rv_w;
    s32 mult = blend5(sp_mult, 0, time), fb = blend5(sp_fb, 1, time), lpc = blend5(sp_lp, 1, time);
    s32 dry = kt(ch_mix_dry, amt), wet = (kt(ch_mix_wet, amt) * wetv) >> 12, md = (drift * 5) >> 15;
    s32 pl = rv_yl, pr = rv_yr;
    int i, k;
    for (k = 0; k < NL; k++)
        len[k] = ((u32)rv_base[k] * (u32)mult) >> 9;               /* half the frames at half the rate */
    for (i = 0; i < N; i += 2) {
        s32 x, y[NL], s = 0, yl, yr, m0 = 0, m1 = 0;
        D[2 * dw] = (s16)sat16((w[2 * i] + w[2 * i + 1]) >> 2);    /* the pre-delay, mono at half scale */
        D[2 * ((dw + 1) & msk)] = (s16)sat16((w[2 * i + 2] + w[2 * i + 3]) >> 2);
        x = (D[2 * ((dw - pre) & msk)] + D[2 * ((dw + 1 - pre) & msk)]) >> 1;
        dw = (dw + 2) & msk;
        for (k = 0; k < 4; k++) {               /* diffusion */
            s16 *b = R + NL * DH_REV_LINE + 1024 * k;
            u32 p = ap_w[k];
            s32 v = b[p], u = x - (v >> 1);
            b[p] = (s16)sat16(u);
            x = v + (u >> 1);
            ap_w[k] = p + 1 < ap_len[k] ? p + 1 : 0;
        }
        if (md) {                               /* DRIFT: two lines' lengths wander */
            m0 = (sinq(dl_ph) * md) >> 15;
            m1 = (sinq(dl_ph + 0x55555555u) * md) >> 15;
            dl_ph += 4474;
        }
        for (k = 0; k < NL; k++) {
            u32 d = len[k] + (k == 0 ? (u32)m0 : k == 2 ? (u32)m1 : 0);
            s32 v = R[DH_REV_LINE * k + ((rw - d) & (DH_REV_LINE - 1))];
            rv_lp[k] += ((v - rv_lp[k]) * lpc) >> 15;
            y[k] = rv_lp[k];
            s += y[k];
        }
        s >>= 1;                                /* Householder: y - 2/4 sum y */
        for (k = 0; k < NL; k++)
            R[DH_REV_LINE * k + rw] = (s16)sat16(((((y[k] - s) >> 1) * fb) >> 14) + x);
        rw = (rw + 1) & (DH_REV_LINE - 1);
        yl = lim(((y[0] + y[2]) * 23170) >> 14, TOP);              /* two lines a side, at four's level */
        yr = lim(((y[1] + y[3]) * 23170) >> 14, TOP);
        w[2 * i] = lim(((w[2 * i] * dry) >> 12) + ((((pl + yl) >> 1) * wet) >> 12), TOP);
        w[2 * i + 1] = lim(((w[2 * i + 1] * dry) >> 12) + ((((pr + yr) >> 1) * wet) >> 12), TOP);
        w[2 * i + 2] = lim(((w[2 * i + 2] * dry) >> 12) + ((yl * wet) >> 12), TOP);
        w[2 * i + 3] = lim(((w[2 * i + 3] * dry) >> 12) + ((yr * wet) >> 12), TOP);
        pl = yl, pr = yr;
    }
    rv_w = rw, rv_yl = pl, rv_yr = pr;
}

static void m_diff(s32 *w)
{
    s16 *D = DH_DIFF;
    s32 time = sk[K_TIME], amt = sk[K_DAMT], drift = ss[S_DDRIFT], wetv = kt(ch_vol, ss[S_DVOL]);
    u32 msk = DH_DIFF_FR - 1;
    int i, fx = dchroma.fx[M_DIFF];
    if (fx == FX_SPACE) {
        d_fx = fx;
        space(w, time, amt, drift, wetv);
        return;
    }
    if (fx == FX_REVERSE) {                     /* backwards windows of the last moment, at a speed */
        s32 o = (time - 16384) >> 6, s12, dry = kt(ch_mix_dry, amt), wet = (kt(ch_mix_wet, amt) * wetv) >> 12;
        u32 L = qfr ? qfr : 28800, Lmax, inv, a0, a1, step;
        d_fx = fx;
        o += (rwalk_step(&drw, 4800) * (drift >> 8)) >> 19;
        s12 = exp2_q12(o);
        if (L < 7200) L = 7200;
        if (L > 43200) L = 43200;
        Lmax = (u32)((125000u * 4096u) / (u32)(4096 + s12));
        if (L > Lmax)
            L = Lmax;
        if (!rv_age[0] && !rv_age[1])
            rv_age[1] = L / 2;
        a0 = rv_age[0], a1 = rv_age[1];
        inv = 0xffffffffu / L;
        step = (u32)(4096 + s12);
        for (i = 0; i < N; i++) {               /* mono: the sum backwards, to both sides */
            s32 g0 = tri(a0 * inv), g1 = tri(a1 * inv), v;          /* the heads' windows cross-fade */
            u32 b0 = a0 * step + 4096, b1 = a1 * step + 4096;      /* frames back from dw, Q12 */
            D[2 * dw] = (s16)sat16((w[2 * i] + w[2 * i + 1]) >> 2);
            v = ((rdl(D, msk, dw, b0, 0) * g0) >> 15) + ((rdl(D, msk, dw, b1, 0) * g1) >> 15);
            v = (v * wet) >> 12;
            if (++a0 >= L) a0 = 0;
            if (++a1 >= L) a1 = 0;
            dw = (dw + 1) & msk;
            w[2 * i] = lim(((w[2 * i] * dry) >> 12) + v, TOP);
            w[2 * i + 1] = lim(((w[2 * i + 1] * dry) >> 12) + v, TOP);
        }
        rv_age[0] = a0, rv_age[1] = a1;
        return;
    }
    {                                           /* CASCADE, REELS, COLLAGE: a delay with feedback */
        s32 T, fb, step, la, ha, mdep, wet = (wetv * 3482) >> 12, crush = 0, noise = 0, m1, ms;
        s32 l0 = dl_l0, h0 = dl_h0, cur = dl_cur, drop = dl_drop;
        u32 inc1, inc2;
        const s16 *sat = sh_soft;
        if (fx == FX_COLLAGE) {
            T = qfr ? (s32)sync_frames(time, col_div, 6) : kt32(ch_ctime, time);
            fb = (amt * 16712) >> 15;           /* to 1.02: it oscillates, softly clipped */
            step = 4096;                        /* the head moves at up to 2x or stops: bends */
            la = ch_op[247];
            ha = ch_op[30];
            mdep = (drift * 72) >> 15;          /* 1.5 ms */
            inc1 = 15000;
            inc2 = 0;
        } else {
            T = qfr ? (s32)sync_frames(time, dly_div, 7) : kt32(ch_dtime, time);
            if (fx == FX_CASCADE) {             /* bucket-brigade: dark, slow to change */
                fb = (amt * 18000) >> 15;
                step = 2048;
                la = ch_op[180 - ((drift * 30) >> 15)];
                ha = ch_op[59];
                mdep = 10 + ((drift * 120) >> 15);
                inc1 = 48000;                   /* 0.5 Hz */
                inc2 = 0;
                crush = (drift * 6) >> 15;
                noise = (drift * 40) >> 15;
            } else {                            /* REELS: tape, brighter, wow and flutter */
                fb = (amt * 17700) >> 15;
                step = 3072;
                la = ch_op[211 - ((drift * 25) >> 15)];
                ha = ch_op[74];
                mdep = 6 + ((drift * 70) >> 15);
                inc1 = 52500;                   /* 0.55 Hz */
                inc2 = 620000;                  /* 6.5 Hz */
                sat = sh_tape;
                noise = (drift * 24) >> 15;
            }
        }
        if (T > (s32)DH_DIFF_FR - 2048)
            T = (s32)DH_DIFF_FR - 2048;
        if (T < 64)
            T = 64;
        if (fx != d_fx) {                       /* a new delay starts at its time; only turning TIME bends it */
            d_fx = fx;
            cur = T << 12;
            cl_skip = 0;
        }
        if (fx == FX_COLLAGE && drift) {        /* DRIFT: now and then a loop at double speed */
            cl_cnt += N;
            if (!cl_skip && cl_cnt >= (u32)T) {
                cl_cnt = 0;
                if (rnd_n(32768) < (u32)(drift >> 1)) {
                    cl_skip = 1;
                    cl_t = 0;
                    cl_len = (u32)T;
                    cl_start = (dw - (u32)T) & msk;
                }
            }
        }
        if (fx == FX_REELS && drift > 8192) {   /* worn tape: dropouts */
            if (drop >= 32767 && rnd_n(65535) < (u32)(drift >> 9))
                drop = 32767 - (s32)rnd_n(24000);
        }
        if (drop < 32767)
            drop += 64;
        m1 = dl_m;                              /* the modulation: at the block's end, ramped to */
        if (mdep) {
            dl_ph += inc1 * N;
            dl_ph2 += inc2 * N;
            dl_m = (sinq(dl_ph) * mdep) >> 3;   /* Q12 frames */
            if (inc2)
                dl_m += (sinq(dl_ph2) * (mdep >> 2)) >> 3;
        } else {
            dl_m = 0;
        }
        ms = (dl_m - m1) >> 5;
        for (i = 0; i < N; i++) {               /* mono: the sum into the line, the repeats to both sides */
            s32 d, v, in, wr;
            cur += lim((T << 12) - cur, step);
            d = cur + m1;
            m1 += ms;
            if (d < (2 << 12))
                d = 2 << 12;
            if (cl_skip) {                      /* the last loop again, at twice the speed */
                u32 p = (cl_start + ((2 * cl_t) % cl_len)) & msk;
                v = D[2 * p] << 1;
                if (++cl_t >= cl_len)
                    cl_skip = 0;
            } else {
                v = rdl(D, msk, dw, (u32)d, 0);
            }
            v = LP(l0, v, la);
            v -= LP(h0, v, ha);
            if (drop < 32767)
                v = (v * drop) >> 15;
            in = drop_x ? 0 : (w[2 * i] + w[2 * i + 1]) >> 1;
            wr = shape(sat, in + ((v * fb) >> 14));
            if (noise)
                wr += (rnd_s() * noise) >> 14;
            if (crush)
                wr = (wr >> (crush + 4)) << (crush + 4);
            D[2 * dw] = (s16)sat16(wr >> 1);
            v = (v * wet) >> 12;
            w[2 * i] = lim(w[2 * i] + v, TOP);
            w[2 * i + 1] = lim(w[2 * i + 1] + v, TOP);
            dw = (dw + 1) & msk;
        }
        dl_l0 = l0, dl_h0 = h0, dl_cur = cur, dl_drop = drop;
    }
}

/* ---- TEXTURE -------------------------------------------------------------------------------------- */
static u32 tw;                                  /* Texture's line: the next frame written */
static s32 t_a0, t_a1, t_b0, t_b1, t_c0;        /* filters */
static s32 sq_env;
static u32 t_ph, t_ph2, t_cnt, t_ev;
static s32 t_rs, t_rt, t_g = 32767, t_gt = 32767, t_d = 300 << 12, t_am = 32767;
static u32 br_t, br_len, br_next = 48000;
static s32 br_extra, br_xf;
static u32 if_burst, if_gap = 48000, if_st, if_slen, if_sstart, if_crush, if_hold;
static s32 if_hv0, if_hv1, if_env;

static void filt(s32 *w, s32 idx, int hp)       /* two one-poles: 12 dB an octave; idx in ch_op, 8.8 */
{
    s32 a = ch_op[idx >> 8] + (((ch_op[(idx >> 8) + 1 > 255 ? 255 : (idx >> 8) + 1] - ch_op[idx >> 8]) * (idx & 255)) >> 8);
    s32 a0 = t_a0, a1 = t_a1, b0 = t_b0, b1 = t_b1;
    int i;
    for (i = 0; i < N; i++) {
        s32 x0 = w[2 * i], x1 = w[2 * i + 1], p0 = LP(a0, x0, a), p1 = LP(a1, x1, a), q0 = LP(b0, p0, a), q1 = LP(b1, p1, a);
        if (hp) {                               /* HP: (1 - LP)^2 = 1 - 2 LP + LP^2 */
            w[2 * i] = lim(x0 - 2 * p0 + q0, TOP);
            w[2 * i + 1] = lim(x1 - 2 * p1 + q1, TOP);
        } else {
            w[2 * i] = q0;
            w[2 * i + 1] = q1;
        }
    }
    t_a0 = a0, t_a1 = a1, t_b0 = b0, t_b1 = b1;
}

static void m_tex(s32 *w)
{
    s16 *T = DH_TEX;
    s32 amt = sk[K_TAMT];
    u32 msk = DH_TEX_FR - 1;
    int i;
    switch (dchroma.fx[M_TEX]) {
    case FX_FILTER: {                           /* TILT: low-pass left, high-pass right; or LPF, HPF */
        s32 k = amt, idx;
        if (dchroma.style == ST_LPF) {
            idx = (74 << 8) + ((k * 181) >> 7);
            if (idx < (250 << 8))
                filt(w, idx, 0);
        } else if (dchroma.style == ST_HPF) {
            idx = (k * 196) >> 7;
            if (idx > (5 << 8))
                filt(w, idx, 1);
        } else if (k < 16384 - 64) {
            idx = (85 << 8) + ((k * 170) >> 6);
            if (idx < (250 << 8))
                filt(w, idx, 0);
        } else if (k > 16384 + 64) {
            idx = ((k - 16384) * 185) >> 6;
            if (idx > (5 << 8))
                filt(w, idx > (255 << 8) - 1 ? (255 << 8) - 1 : idx, 1);
        }
        break;
    }
    case FX_SQUASH: {                           /* heavy compression; it overdrives near the top */
        s32 thr = (16384 - ((amt * 14384) >> 15)) * 4096 / gin, ratio = 3 + ((amt * 17) >> 15);
        s32 mk = 4096 + ((amt * 4096) >> 15), od = amt > 24384 ? 256 + ((amt - 24384) >> 4) : 0, env = sq_env;
        if (thr < 500)
            thr = 500;
        for (i = 0; i < N; i++) {
            s32 e0 = absv(w[2 * i]), e1 = absv(w[2 * i + 1]), e = e0 > e1 ? e0 : e1, g = mk, y0, y1;
            env += e > env ? (e - env) >> 2 : -(env >> 12);
            if (env > thr)
                g = (((thr + (env - thr) / ratio) * 4096 / env) * mk) >> 12;
            y0 = lim((w[2 * i] * g) >> 12, TOP);
            y1 = lim((w[2 * i + 1] * g) >> 12, TOP);
            if (od) {
                y0 = shape(sh_soft, (y0 * od) >> 8);
                y1 = shape(sh_soft, (y1 * od) >> 8);
            }
            w[2 * i] = y0;
            w[2 * i + 1] = y1;
        }
        sq_env = env;
        break;
    }
    case FX_CASSETTE: {                         /* saturation, a narrowing band, wow, flutter, hiss, dropouts */
        s32 u = amt, u2 = (u >> 7) * (u >> 7) >> 1, drive = 256 + ((u * 640) >> 15);
        s32 la = ch_op[247 - ((u * 46) >> 15)], ha = ch_op[15 + ((u * 59) >> 15)];
        s32 wow = (4 << 12) + u2 * 8, flut = 1600 + (u2 >> 2), warble = u > 19660 ? (u - 19660) * 4 : 0;
        s32 hiss = (u * 50) >> 15, mk = 4096 * 256 / drive, d, ds, g, gs;
        s32 a0 = t_a0, a1 = t_a1, b0 = t_b0, b1 = t_b1;
        if (u > 22937 && t_gt >= 32767 && t_g >= 32767 && rnd_n(65535) < (u32)((u - 22937) >> 9))
            t_gt = 3000 + (s32)rnd_n(14000);    /* a dropout */
        t_cnt += N;
        if (t_gt < 32767 && t_cnt > 2400 + rnd_n(4800)) {
            t_gt = 32767;
            t_cnt = 0;
        }
        if (t_cnt > 6000) {
            t_cnt = 0;
            t_rt = rnd_s();
        }
        t_rs += (t_rt - t_rs) >> 6;
        t_ph += 49000 * N;                      /* wow 0.55 Hz, flutter 7 Hz: at the block's end, ramped to */
        t_ph2 += 626000 * N;
        d = t_d;
        t_d = (300 << 12) + ((sinq(t_ph) * (wow >> 8)) >> 7) + ((sinq(t_ph2) * (flut >> 4)) >> 11)
              + ((t_rs * (warble >> 4)) >> 10);
        ds = (t_d - d) >> 5;
        g = t_g;
        t_g += (t_gt - t_g) >> 2;
        gs = (t_g - g) >> 5;
        for (i = 0; i < N; i++) {
            s32 x0 = (shape(sh_tape, (w[2 * i] * drive) >> 8) * mk) >> 12;
            s32 x1 = (shape(sh_tape, (w[2 * i + 1] * drive) >> 8) * mk) >> 12, v0, v1;
            x0 = LP(a0, x0, la);
            x1 = LP(a1, x1, la);
            x0 -= LP(b0, x0, ha);
            x1 -= LP(b1, x1, ha);
            T[2 * tw] = (s16)sat16(x0 >> 1);
            T[2 * tw + 1] = (s16)sat16(x1 >> 1);
            v0 = rdl(T, msk, tw, (u32)d, 0);
            v1 = rdl(T, msk, tw, (u32)d, 1);
            if (hiss) {
                s32 h = (rnd_s() * hiss) >> 13;
                v0 += h;
                v1 += h;
            }
            w[2 * i] = (v0 * g) >> 15;
            w[2 * i + 1] = (v1 * g) >> 15;
            d += ds;
            g += gs;
            tw = (tw + 1) & msk;
        }
        t_a0 = a0, t_a1 = a1, t_b0 = b0, t_b1 = b1;
        break;
    }
    case FX_BROKEN: {                           /* the motor slows and catches: pitch drops, AM, FM */
        s32 u = amt, depth = 4915 + ((u * 19660) >> 15), am = (u * 11468) >> 15, s = 0, sx, g, gs;
        u32 d, d1;
        if (br_len) {                           /* a drop: the speed sinks and comes back (per block) */
            s32 sh = sinq((u32)((br_t << 15) / br_len) << 16);
            s = (depth * ((sh * sh) >> 15)) >> 15;
            br_t += N;
            if (br_t >= br_len) {
                br_len = 0;
                br_xf = 256;                    /* back to time with a short crossfade */
            }
        } else if (br_next > N) {
            br_next -= N;
        } else {
            br_len = 4800 + rnd_n(14400);
            br_t = 0;
            br_next = 24000 + rnd_n((u32)(96000 - ((u * 72000) >> 15)));
        }
        sx = s >> 3;                            /* the delay grows by 1 - speed, a frame */
        t_ph += 1252000 * N;                    /* AM, 14 Hz; FM, 30 Hz: at the block's end, ramped to */
        t_ph2 += 2683000 * N;
        d = (u32)((64 << 12) + br_extra + ((sinq(t_ph2) * (u >> 6)) >> 9));
        d1 = t_d;                               /* where the last block left off */
        if (d1 < (32u << 12) || d1 > (16000u << 12))
            d1 = d;
        t_d = (s32)(d + (u32)(sx * N));
        g = t_am;
        t_am = 32767 - ((am * ((sinq(t_ph) + 32767) >> 1)) >> 15);
        gs = (t_am - g) >> 5;
        {
            s32 dd = ((s32)t_d - (s32)d1) >> 5;
            u32 dc = d1;
            for (i = 0; i < N; i++) {
                s32 v0, v1;
                T[2 * tw] = (s16)sat16(w[2 * i] >> 1);
                T[2 * tw + 1] = (s16)sat16(w[2 * i + 1] >> 1);
                v0 = rdl(T, msk, tw, dc, 0);
                v1 = rdl(T, msk, tw, dc, 1);
                if (br_xf) {
                    s32 n0 = rdl(T, msk, tw, 64 << 12, 0), n1 = rdl(T, msk, tw, 64 << 12, 1);
                    v0 = (n0 * (256 - br_xf) + v0 * br_xf) >> 8;
                    v1 = (n1 * (256 - br_xf) + v1 * br_xf) >> 8;
                    if (--br_xf == 0) {
                        br_extra = 0;
                        t_d = (s32)(64 << 12);
                        dd = 0;
                        dc = 64 << 12;
                    }
                }
                w[2 * i] = (v0 * g) >> 15;
                w[2 * i + 1] = (v1 * g) >> 15;
                dc += (u32)dd;
                g += gs;
                tw = (tw + 1) & msk;
            }
        }
        br_extra += sx * N;
        if (!br_len && !br_xf)
            br_extra = 0, t_d = (s32)(64 << 12);
        break;
    }
    default: {                                  /* INTERFERENCE: static, fading, buzz, then glitches */
        s32 u = amt, noise = (u * 300) >> 15, c0 = t_c0;
        s32 fade = u > 8192 ? ((u - 8192) * 30) >> 5 : 0, buzz = u > 14745 ? (u - 14745) >> 2 : 0;
        int glitch = u > 19660, crack = -1;
        s32 pk = 0, g;
        for (i = 0; i < 2 * N; i++)
            if (absv(w[i]) > pk)
                pk = absv(w[i]);
        if_env += (pk - if_env) >> 3;
        if (rnd_n(65535) < (u32)((3 + ((u * 80) >> 15)) * 44))     /* 3-83 crackles a second: one this block? */
            crack = (int)rnd_n(N);
        if (fade) {                             /* radio fading: a slow random wave on the level */
            t_cnt += N;
            if (t_cnt > 12000) {
                t_cnt = 0;
                t_rt = (s32)rnd_n(32768);
            }
            t_rs += (t_rt - t_rs) >> 8;
        }
        g = 32767 - ((fade * t_rs) >> 15);
        if (buzz) {                             /* GSM: bursts of a 217 Hz buzz */
            if (if_burst) if_burst = if_burst > N ? if_burst - N : 0;
            else if (if_gap > N) if_gap -= N;
            else {
                if_burst = 14400 + rnd_n(28800);
                if_gap = 24000 + rnd_n(144000);
            }
        }
        if (glitch && !if_st && rnd_n(65535) < (u32)((u - 19660) >> 8)) {
            u32 kind = rnd_n(3);
            if (kind == 0) {                    /* a stutter */
                if_slen = 720 + rnd_n(3120);
                if_st = if_slen * (2 + rnd_n(6));
                if_sstart = (tw - if_slen) & msk;
                if_crush = 0;
            } else if (kind == 1) {             /* crushed and held */
                if_st = 2400 + rnd_n(7200);
                if_slen = 0;
                if_crush = 9 + rnd_n(3);
                if_hold = 4 + rnd_n(8);
            } else {                            /* a dropout */
                if_st = 480 + rnd_n(2400);
                if_slen = 0;
                if_crush = 99;
            }
        }
        for (i = 0; i < N; i++) {
            s32 n = 0, b = 0, x0, x1;
            T[2 * tw] = (s16)sat16(w[2 * i] >> 1);
            T[2 * tw + 1] = (s16)sat16(w[2 * i + 1] >> 1);
            if (i == crack)                     /* a crackle, louder with the music */
                n = (rnd_s() * (((2 + (if_env >> 12)) * (u >> 7)) >> 8)) >> 3;
            if (noise)
                n += (rnd_s() * noise * (1 + (if_env >> 13))) >> 14;
            n -= LP(c0, n, ch_op[170]);         /* above 2 kHz */
            if (if_burst)
                b = ((t_ph & 0xe0000000u) == 0 ? buzz : -(buzz >> 3));
            t_ph += 19417000;                   /* 217 Hz */
            x0 = (w[2 * i] * g) >> 15;
            x1 = (w[2 * i + 1] * g) >> 15;
            if (if_st) {
                if (if_slen) {
                    u32 p = (if_sstart + ((if_slen * 64 - if_st) % if_slen)) & msk;
                    x0 = T[2 * p] << 1;
                    x1 = T[2 * p + 1] << 1;
                } else if (if_crush == 99) {
                    x0 = x1 = 0;
                } else {
                    if (t_ev == 0) {
                        if_hv0 = (x0 >> if_crush) << if_crush;
                        if_hv1 = (x1 >> if_crush) << if_crush;
                    }
                    x0 = if_hv0;
                    x1 = if_hv1;
                }
                if_st--;
                if (++t_ev >= if_hold)
                    t_ev = 0;
            }
            w[2 * i] = lim(x0 + n + b, TOP);
            w[2 * i + 1] = lim(x1 + n + b, TOP);
            tw = (tw + 1) & msk;
        }
        t_c0 = c0;
        break;
    }
    }
    gain(w, kt(ch_vol, ss[S_TVOL]));
}

/* ---- CAPTURE: hold to record, plays on release; a short one plays as a sustained pad -------------- */
static u32 cpos;
static s32 cap[2 * N];
static int cap_zero = 1;                        /* cap holds silence */

static void capture_block(void)
{
    int c = dchroma.ccmd;
    if (c) {
        dchroma.ccmd = CC_NONE;
        if (c == CC_REC) {
            dchroma.crec = 0;
            dchroma.cstate = C_REC;
        } else if (c == CC_PLAY && dchroma.cstate == C_REC) {
            if (dchroma.crec < 2400) {
                dchroma.cstate = C_EMPTY;
            } else {
                dchroma.clen = dchroma.crec;
                cpos = 0;
                dchroma.cstate = C_PLAY;
            }
        } else if (c == CC_STOP) {
            dchroma.cstate = C_EMPTY;
            dchroma.clen = 0;
        }
    }
}

static void capture_play(void)
{
    const s16 *A = DH_CAP;
    u32 L = dchroma.clen, p = cpos;
    int i;
    if (dchroma.cstate != C_PLAY || !L) {
        if (!cap_zero)
            for (i = 0; i < 2 * N; i++)
                cap[i] = 0;
        cap_zero = 1;
        return;
    }
    cap_zero = 0;
    if (L < 48000) {                            /* a sustainer: two windowed readers half a loop apart */
        u32 inv = 0xffffffffu / L, h = L / 2;
        for (i = 0; i < N; i++) {
            u32 p1 = p + h >= L ? p + h - L : p + h;
            s32 w0 = tri(p * inv), w1 = 32767 - w0;                 /* each reader silent at its seam */
            cap[2 * i] = (A[2 * p] * w0 + A[2 * p1] * w1) >> 14;
            cap[2 * i + 1] = (A[2 * p + 1] * w0 + A[2 * p1 + 1] * w1) >> 14;
            if (++p >= L)
                p = 0;
        }
    } else {                                    /* a loop, faded at its seam */
        for (i = 0; i < N; i++) {
            s32 g = 32767;
            if (p < 480)
                g = (s32)p * 68;
            else if (p > L - 480)
                g = (s32)(L - p) * 68;
            cap[2 * i] = (A[2 * p] * g) >> 14;
            cap[2 * i + 1] = (A[2 * p + 1] * g) >> 14;
            if (++p >= L)
                p = 0;
        }
    }
    cpos = p;
}

static void capture_write(const s32 *src)
{
    s16 *A = DH_CAP;
    u32 r = dchroma.crec;
    int i;
    if (dchroma.cstate != C_REC)
        return;
    for (i = 0; i < N && r < DH_CAP_FR; i++, r++) {
        A[2 * r] = (s16)sat16(src[2 * i] >> 1);
        A[2 * r + 1] = (s16)sat16(src[2 * i + 1] >> 1);
    }
    dchroma.crec = r;
    if (r >= DH_CAP_FR) {
        dchroma.clen = r;
        cpos = 0;
        dchroma.cstate = C_PLAY;
    }
}

/* ---- the CPU guard ------------------------------------------------------------------------------- */
/* The whole render, from its entry to its exit, against the time from one block to the next, on DMA timer 0.
 * Over 93% for 300 blocks running (0.2 s) the unit has no time left for its UI: the guard bypasses the pedal,
 * at once (no trails), and says so. The emulator has no DMA timer 0: there the guard sees nothing. */
static u32 r_in, r_prev, r_over;

void dchroma_rin(void)
{
    r_prev = r_in;
    r_in = DTCN0;
}

void dchroma_rout(void)
{
    u32 per = r_in - r_prev, busy = DTCN0 - r_in, l;
    if (per < 1000 || per > 400000)
        return;
    l = busy * 1000u / per;
    dchroma.load = (u16)l;
    if (l > 930 && dchroma_owner.on && !dchroma.bypass) {
        if (++r_over >= 300) {
            dchroma.overload = 1;
            dchroma.bypass = 1;
            r_over = 0;
        }
    } else if (r_over) {
        r_over--;
    }
}

/* ---- the block ------------------------------------------------------------------------------------ */
static u32 t_prev, quiet;

void dchroma_dsp_reset(void)
{
    int k;
    mw = dw = tw = 0;
    dl_cur = 0;
    d_fx = -1;
    rv_w = 0;
    for (k = 0; k < 4; k++)
        ap_w[k] = 0;
    for (k = 0; k < NL; k++)
        rv_lp[k] = 0;
    rv_yl = rv_yr = 0;
    for (k = 0; k < 12; k++)
        ap_x[k] = ap_y[k] = 0;
    c_t0 = c_t1 = c_p0 = c_p1 = c_h0 = c_h1 = c_d0 = c_d1 = c_l0 = c_l1 = c_i0 = c_i1 = 0;
    h_l0 = h_l1 = h_b0 = h_b1 = 0;
    d_cur[0] = d_cur[1] = 0;
    ap_last = ap_prev = 0;
    dl_l0 = dl_h0 = 0;
    t_a0 = t_a1 = t_b0 = t_b1 = t_c0 = 0;
    rv_age[0] = rv_age[1] = 0;
    for (k = 0; k < 8; k++) {
        ek[k] = sk[k] = dchroma.knob[k] << 8;
        ss[k] = dchroma.sec[k] << 8;
        dchroma.gstate[k] = G_NONE;
    }
    dchroma.cstate = C_EMPTY;
    dchroma.clen = 0;
}

void dchroma_render(int32_t *out, const int32_t *in)
{
    static s32 x[2 * N], w[2 * N];
    u32 t0 = DTCN0, tempo = dchroma_tempo();
    s32 md, mw_, ov, pk0 = 0, pk1 = 0, tail = 0;
    int i, k, pre = dchroma.croute, byp = dchroma.bypass;

    dchroma.blocks++;
    qfr = tempo ? 345600000u / tempo : 0;
    gestures_block(tempo);
    knobs_block();
    capture_block();
    capture_play();

    if (byp) {
        for (i = 0; i < 2 * N; i++) {
            x[i] = in[i] >> 16;
            w[i] = 0;
        }
    } else if (pre) {
        for (i = 0; i < 2 * N; i++)
            w[i] = (x[i] = in[i] >> 16) + cap[i];
    } else {
        for (i = 0; i < 2 * N; i++)
            w[i] = x[i] = in[i] >> 16;
    }
    if (dchroma.mono)                           /* a mono source on input L: on both sides */
        for (i = 0; i < 2 * N; i += 2) {
            x[i + 1] = x[i];
            w[i + 1] = w[i];
        }
    drop_x = byp;
    if (!byp) {
        if (pre)
            capture_write(x);
        for (k = 0; k < 4; k++) {
            int m = ch_order[dchroma.order % 24][k];
            if (!dchroma.on[m])
                continue;
            switch (m) {
            case M_CHAR: m_char(w); break;
            case M_MOVE: m_move(w); break;
            case M_DIFF: m_diff(w); break;
            default: m_tex(w); break;
            }
        }
    } else if (dchroma.on[M_DIFF] && dchroma.trails && !dchroma.overload) {
        m_diff(w);                              /* the trails: Diffusion's tail, on silence */
        for (i = 0; i < 2 * N; i++)
            if (absv(w[i]) > tail)
                tail = absv(w[i]);
    }

    /* MIX (the dry against the chain), CAPTURE post-FX, OUTPUT LEVEL and the soft clip, in one pass;
     * bypassed, the dry and the tail at unity */
    ov = kt(ch_vol, ss[S_OUT]);
    if (byp) {
        for (i = 0; i < 2 * N; i += 2) {
            s32 y0 = sat16(x[i] + w[i]), y1 = sat16(x[i + 1] + w[i + 1]);
            if (absv(y0) > pk0) pk0 = absv(y0);
            if (absv(y1) > pk1) pk1 = absv(y1);
            out[i] = y0 << 16;
            out[i + 1] = y1 << 16;
        }
    } else {
        int rec = !pre && dchroma.cstate == C_REC, play = !pre && !cap_zero;
        mw_ = (sk[K_MIX] * 129) >> 10;
        md = 4096 - mw_;
        if (!rec && !play && !md && ov > 4092 && ov < 4100) {
            for (i = 0; i < 2 * N; i++) {       /* all wet, at 0 dB: the soft clip only */
                s32 y = w[i];
                if (y > 26214 || y < -26214)    /* its knee: straight below it */
                    y = shape(sh_out, y);
                out[i] = y << 16;
            }
        } else {
            for (i = 0; i < 2 * N; i++) {
                s32 y = md ? ((x[i] * md) >> 12) + ((w[i] * mw_) >> 12) : w[i];
                if (rec)
                    w[i] = y;
                if (play)
                    y += cap[i];
                y = (y * ov) >> 12;
                if (y > 26214 || y < -26214)
                    y = shape(sh_out, lim(y, 131071));
                out[i] = y << 16;
            }
            if (rec)
                capture_write(w);
        }
        for (i = 0; i < 2 * N; i += 8) {        /* the meter: every fourth frame */
            s32 y0 = absv(out[i] >> 16), y1 = absv(out[i + 1] >> 16);
            if (y0 > pk0) pk0 = y0;
            if (y1 > pk1) pk1 = y1;
        }
    }
    if (pk0 > dchroma.meter[0])
        dchroma.meter[0] = (u16)pk0;
    if (pk1 > dchroma.meter[1])
        dchroma.meter[1] = (u16)pk1;

    /* bypassed: once the tail has been quiet half a second, the render has nothing more to add */
    if (!byp)
        quiet = 0;
    else if (tail > 16 || !dchroma.trails || dchroma.overload)
        quiet = dchroma.trails && !dchroma.overload ? 0 : 750;
    else
        quiet++;
    dchroma.active = (u8)(!byp || quiet < 750);

    {                                           /* the CPU guard's measure: this render's share of a block */
        u32 t1 = DTCN0, per = t0 - t_prev;
        if (per)
            dchroma.cpu = (u16)((t1 - t0) * 1000u / per);
        t_prev = t0;
    }
}
