| SPDX-License-Identifier: GPL-2.0-or-later
| core-dn1 3.0 (Digitone mk1): firmware locations as exports. A mod that
| names these instead of the addresses rebuilds for another OS version
| unchanged: each OS's port in mod.json (defsym FW_*) gives their values, and
| the linker resolves the names against the core in the build. In C, declare
| them as arrays or functions (elekloader/sdk/include/digitone-mk1/core3.h):
|   extern volatile int32_t fw_voice_pitch[];  ...  fw_voice_pitch[v] = note << 16
| The names are the Digitakt mk1's (mods/core/fw.s) where they mean the same.
| Values are OS 1.43's in the comments. Each 1.44 one was found again by the
| code that uses it, which is the same in both but for the addresses in it
| (docs/ADAPTING.md, "Firmware locations").
|
| The render (interrupt level, 1500 times a second; SRAM):
|   fw_voice_pitch   0x41391f80  each voice's pitch word, the note << 16, a long a voice
|   fw_voice_params  0x800034c4  the render's copy of each voice's sound: slot k of
|                                voice v at +18 + 158 v + 2 k, 8.8
|   fw_voice_len     0x80003f14  each voice's length left, timeline units (0: none), a long
|   fw_gate_off      0x80001f74  bit v: voice v released in the last block
|   fw_timeline      0x80004614  the render's timeline: 5,400,000 units a 16th, at any tempo
|   fw_transpose     0x80003fc4  the transposition, then each track's: +4 + 4 t
|   fw_lfo_state     0x419ea314  each voice's LFOs: LFO1 at +0x50 v, LFO2 0x28 on; the
|                                destination slot at +0x40, the modulation (8.8) at +0x44
| The note queue (mask interrupts around it):
|   fw_ev_alloc      0x400ffd7e  a note event (0x48 bytes) -> d0, 0 when the pool is empty
|   fw_ev_free       0x400ffdb4  free(event), and its p-lock list's reference
|   fw_ev_queue      0x400fff04  queue(event, time on the timeline)
|   fw_lock_alloc    0x400ffd2e  a p-lock list -> d0; no check: test fw_locks_free first
|   fw_locks_free    0x419ed230  the free p-lock lists (0: none)
|   fw_nodes_free    0x419ed234  the queue's free times (with none, queueing at a new
|                                time never returns)
| The UI (its task):
|   fw_kit           0x4138e220  -> the active kit: track t's sound slot k at
|                                +0x2c + 326 t + 2 k
|   fw_slot_ids      0x40528644  each sound slot's parameter id (0-78), a long each
|   fw_str_amp       0x401d63c3  the firmware's "Amp" (a parameter group's name)
|   fw_str_empty     0x401ddbcd  its empty string (a parameter record's +60)
|   fw_fillrect      0x400dd292  fillrect(bmp, x0, y0, x1, y1, colour): colour < 0 XOR,
|                                1 set, 0 clear
|   fw_framerect     0x400dd076  framerect(bmp, x0, y0, x1, y1, colour): an outline
|   fw_textf         0x400dde68  textf(bmp, font, x, y, maxlen, fmt, ...): ORs pixels
|   fw_font5         0x402315c8  the stock 5-pixel font
|   fw_blit          0x400de24c  blit(dst, src, x, y, centre)
|   fw_op_new        0x400e944c  operator new(size) -> d0, 0 when the heap is full
| From 3.1, for machines (ev_render_voices) and their pages:
|   fw_voices        0x80004110  the render's copy of the DSP's eight voices: 32
|                                samples a voice, Q1.31, 128 bytes a voice
|   fw_voice_track   0x80003f8c  each voice's track, a long a voice
|   fw_gate_on       0x80001f70  bit v: voice v started in the render's last block
|   fw_active_track  0x41367ce0  the active track (a long), 0-3 the synth tracks
|   fw_params        0x4018d104  the parameter records, 60 bytes an id
|   fw_uirecs        0x4136b9fc  their UI records, 84 bytes an id
| From 3.2:
|   fw_tempo         0x40241c94  the tempo x 120 (87.0 BPM: 10440), a long: the
|                                timeline moves twice this every block

        .macro  FW name, value
        .globl  \name
        .set    \name, \value
        .endm

        FW      fw_voice_pitch, VOICE_PITCH
        FW      fw_voice_params, FW_VOICE_PARAMS
        FW      fw_voice_len, FW_VOICE_LEN
        FW      fw_gate_off, FW_GATE_OFF
        FW      fw_timeline, FW_TIMELINE
        FW      fw_transpose, FW_TRANSPOSE
        FW      fw_lfo_state, FW_LFO_STATE
        FW      fw_ev_alloc, FW_EV_ALLOC
        FW      fw_ev_free, FW_EV_FREE
        FW      fw_ev_queue, FW_EV_QUEUE
        FW      fw_lock_alloc, FW_LOCK_ALLOC
        FW      fw_locks_free, FW_LOCKS_FREE
        FW      fw_nodes_free, FW_NODES_FREE
        FW      fw_kit, FW_KIT
        FW      fw_slot_ids, FW_SLOT_IDS
        FW      fw_str_amp, FW_STR_AMP
        FW      fw_str_empty, FW_STR_EMPTY
        FW      fw_fillrect, FILLRECT
        FW      fw_framerect, FRAMERECT
        FW      fw_textf, TEXTF
        FW      fw_font5, FONT5
        FW      fw_blit, FW_BLIT
        FW      fw_op_new, OP_NEW
        FW      fw_voices, FW_VOICES
        FW      fw_voice_track, FW_VOICE_TRACK
        FW      fw_gate_on, FW_GATE_ON
        FW      fw_active_track, FW_ACTIVE_TRACK
        FW      fw_params, PARAMS
        FW      fw_uirecs, UIRECS
        FW      fw_tempo, FW_TEMPO
