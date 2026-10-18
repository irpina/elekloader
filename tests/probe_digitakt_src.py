# SPDX-License-Identifier: GPL-2.0-or-later
"""Probe stock Digitakt SRC capacity with an existing digiemu checkout.

By default this calls bounded, unmodified firmware routines. --storage also
builds the shared implementation and metadata fixtures with the existing cross compiler.
Neither mode boots the OS or establishes added-parameter UI behavior.

Run with the existing emulator's dependencies available on PYTHONPATH:
    python tests/probe_digitakt_src.py --emulator /path/to/digiemu \
        --stock /path/to/Digitakt_OS1.53.syx --stock /path/to/Digitakt_OS1.54.syx

Output is a semantic JSON report, never extracted firmware bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from elekloader import formats  # noqa: E402

# Native routine addresses verified independently on both stock releases.
# These are probe fixtures, not exports offered to machine mods.
ROUTINES = {
    '1.53': {'save_map': 0x401AC1D4, 'load_map': 0x401AC28C,
             'lfo': 0x400ED53E, 'lfo_state': 0x421F3E10},
    '1.54': {'save_map': 0x401AC4D4, 'load_map': 0x401AC58C,
             'lfo': 0x400ED766, 'lfo_state': 0x421F4E10},
}
MAP_INIT = 0x40078B20
SLOT_ID = 0x40078F44
PARAM_SLOT = 0x40078D80
SOUND_INIT = 0x40084EF6
SOUND_SAVE = 0x4007A5A0
SOUND_LOAD = 0x4007A236
ENGINE_SOUND = 0x40077282
LOCK_RESOLVE = 0x4006F46E
LOCK_APPLY = 0x40074B0A
LOCK_RESTORE = 0x40074A40
RETURN = 0xDEADBEE0
LIMIT = 200_000


def probe(stock_path, Machine, call, pc_register):
    stock, dev, release = formats.load(str(stock_path))
    if dev.key != 'digitakt-mk1' or release.version not in ROUTINES:
        raise ValueError('probe needs stock Digitakt mk1 OS 1.53 or 1.54')
    image = formats.main_image(stock, dev)
    assert hashlib.sha256(image).hexdigest() == release.main_sha256
    addresses = ROUTINES[release.version]
    save_map = struct.unpack_from('>46I', image, addresses['save_map'] - dev.main_load)
    load_map = struct.unpack_from('>46I', image, addresses['load_map'] - dev.main_load)
    assert sorted(save_map) == sorted(load_map) == list(range(46))
    assert all(load_map[save_map[i]] == i for i in range(46))

    m = Machine()
    m.load(image, dev.main_load)
    m.install_isa_patches_scoped(image, dev.main_load)
    sound, saved, changed, loaded, locks, resolved = (
        0x43000100, 0x43100100, 0x43200100,
        0x43300100, 0x43400100, 0x43500100,
    )
    for pointer in (sound, saved, changed, loaded, locks, resolved):
        m.ensure(pointer)

    def native(address, args):
        result = call(m, address, args, ret_magic=RETURN, limit=LIMIT)
        pc = m.uc.reg_read(pc_register)
        assert pc == RETURN, 'routine 0x%08x stopped at 0x%08x' % (address, pc)
        return result

    native(MAP_INIT, [])
    mapping = [native(SLOT_ID, [slot, 3]) for slot in range(53)]
    assert mapping[17:25] == list(range(132, 140))
    assert all(mapping[slot] == 0 for slot in range(46, 53))
    assert native(SLOT_ID, [53, 3]) == 0
    assert native(PARAM_SLOT, [164]) == 0xFFFFFFFF

    # A legitimate stock sound supplies valid names, LFO modes and sample data.
    native(SOUND_INIT, [sound, 0, 3])
    assert native(SOUND_SAVE, [saved, sound, 0]) & 0xFF == 1
    before = bytes(m.uc.mem_read(saved, 160))
    for slot in range(46, 53):
        m.uc.mem_write(sound + 20 + 2 * slot, struct.pack('>h', 0x1100 + slot))
    assert native(SOUND_SAVE, [changed, sound, 0]) & 0xFF == 1
    after = bytes(m.uc.mem_read(changed, 160))
    assert before == after, 'stock saver unexpectedly preserves candidate slots'
    assert after[120:124] == bytes(4)
    assert native(SOUND_LOAD, [loaded, changed]) & 0xFF == 1
    assert bytes(m.uc.mem_read(loaded + 20 + 46 * 2, 14)) == bytes(14)
    # Also check a normal SRC value, so an entirely empty load cannot pass.
    assert m.uc.mem_read(loaded + 20 + 17 * 2, 2) == m.uc.mem_read(sound + 20 + 17 * 2, 2)

    # The stock resolver scans a selected step's 53 words, skipping -1.
    step = 3
    m.uc.mem_write(locks, struct.pack('>h', -1) * (54 * 64))
    expected = [(17, 0x1200), (46, 0x3400), (52, -123)]
    for slot, value in expected:
        m.uc.mem_write(locks + 108 * step + 2 * slot, struct.pack('>h', value))
    guard = b'\xa5' * 16
    m.uc.mem_write(resolved - 16, guard)
    m.uc.mem_write(resolved + 20 + 53 * 8, guard)
    native(LOCK_RESOLVE, [resolved, locks, 0, step])
    count, = struct.unpack('>I', m.uc.mem_read(resolved + 8, 4))
    assert count == len(expected), count
    actual = [struct.unpack('>Hh', m.uc.mem_read(resolved + 20 + 8 * i, 4))
              for i in range(count)]
    assert actual == expected, actual
    assert bytes(m.uc.mem_read(resolved - 16, 16)) == guard
    assert bytes(m.uc.mem_read(resolved + 20 + 53 * 8, 16)) == guard
    native(LOCK_RESOLVE, [resolved, locks, 0, step + 1])
    assert bytes(m.uc.mem_read(resolved + 8, 4)) == bytes(4)

    # Follow the native engine target path; this does not run smoothing/LFOs.
    engine = 0x800014F0
    values = engine + 18
    targets = 0x80002B50
    base_values = bytes(m.uc.mem_read(sound + 20, 106))
    native(ENGINE_SOUND, [sound, 0])
    assert bytes(m.uc.mem_read(values, 106)) == base_values
    native(LOCK_RESOLVE, [resolved, locks, 0, step])
    native(LOCK_APPLY, [0, resolved, engine])
    locked_values = bytearray(base_values)
    for slot, value in expected:
        struct.pack_into('>h', locked_values, 2 * slot, value)
        target, = struct.unpack('>I', m.uc.mem_read(targets + 4 * slot, 4))
        assert target == (value << 16) & 0xFFFFFFFF
    assert bytes(m.uc.mem_read(values, 106)) == locked_values
    native(LOCK_RESTORE, [0, engine, sound])
    assert bytes(m.uc.mem_read(values, 106)) == base_values
    for slot, _value in expected:
        value, = struct.unpack_from('>h', base_values, 2 * slot)
        target, = struct.unpack('>I', m.uc.mem_read(targets + 4 * slot, 4))
        assert target == (value << 16) & 0xFFFFFFFF

    for slot in range(54):
        m.uc.mem_write(locks + 108 * step + 2 * slot, struct.pack('>h', slot + 1))
    native(LOCK_RESOLVE, [resolved, locks, 0, step])
    count, = struct.unpack('>I', m.uc.mem_read(resolved + 8, 4))
    assert count == 53, count
    full = [struct.unpack('>Hh', m.uc.mem_read(resolved + 20 + 8 * i, 4))
            for i in range(count)]
    assert full == [(slot, slot + 1) for slot in range(53)]
    assert bytes(m.uc.mem_read(resolved + 20 + 53 * 8, 16)) == guard

    # Native smoothing and LFO processing use different MACSR modes. Execute
    # their stock mode-setting instructions, without running the whole render.
    def macsr(value):
        address = {0x20: 0x4006A868, 0xA0: 0x40074732}[value]
        offset = address - dev.main_load
        assert image[offset:offset + 6] == b'\xa9\x3c' + struct.pack('>I', value)
        m.uc.emu_start(address, address + 6, count=1)
        assert m.uc.reg_read(pc_register) == address + 6

    modulation = []
    for destinations in ((19, 24), (46, 47)):
        # Reset the two native LFO states per track for a matched comparison.
        m.ensure(addresses['lfo_state'])
        m.uc.mem_write(addresses['lfo_state'], bytes(8 * 2 * 40))
        native(SOUND_INIT, [sound, 0, 3])
        params = list(struct.unpack('>53h', m.uc.mem_read(sound + 20, 106)))
        params[4], params[12] = [slot << 8 for slot in destinations]
        params[1] = params[9] = 0x5000       # speed
        params[5] = params[13] = 2 << 8      # square wave
        params[6] = params[14] = 0x4000     # phase
        params[7] = params[15] = 1 << 8      # trigger reset
        params[8] = params[16] = 0x4800     # nonzero depth
        for track in range(8):
            params[19] = params[46] = 8000 + track
            params[24] = params[47] = 12000 + track
            m.uc.mem_write(sound + 20, struct.pack('>53h', *params))
            native(ENGINE_SOUND, [sound, track])
        blocks = []
        for block in range(3):
            macsr(0xA0)
            out = native(0x40074B9E, [engine])
            assert out == 0x80002760
            before = bytes(m.uc.mem_read(out, 972))
            for track in range(8):
                assert struct.unpack_from('>2h', before, 18 + 106 * track + 92) == (
                    8000 + track, 12000 + track)
            macsr(0x20)
            native(addresses['lfo'], [out, 14400, 0xFF if block == 0 else 0])
            after = bytes(m.uc.mem_read(out, 972))
            expected = bytearray(before)
            values = []
            for track in range(8):
                pair = []
                for slot in destinations:
                    offset = 18 + 106 * track + 2 * slot
                    expected[offset:offset + 2] = after[offset:offset + 2]
                    pair.append(struct.unpack_from('>h', after, offset)[0])
                values.append(pair)
                assert bytes(m.uc.mem_read(engine + 18 + 106 * track + 92, 4)) == (
                    struct.pack('>2h', 8000 + track, 12000 + track))
            assert after == expected, 'LFO changed a word outside its destinations'
            blocks.append(values)
        modulation.append(blocks)
    assert modulation[0] == modulation[1], 'candidate LFO results differ from stock targets'
    assert modulation[1][0][0] == [8000 + 4095, 12000 + 4095]
    assert modulation[1][1][0] == [8000 - 4096, 12000 - 4096]

    # The existing saved destination permutation does not cover the extras,
    # even though the running LFOs above can use them. Keep this failure visible.
    destination_round_trips = {}
    native(SOUND_INIT, [sound, 0, 3])
    for destination in (19, 24, 45, 46, 47):
        for slot in (4, 12):
            m.uc.mem_write(sound + 20 + 2 * slot, struct.pack('>h', destination << 8))
        assert native(SOUND_SAVE, [saved, sound, 0]) & 0xFF == 1
        assert native(SOUND_LOAD, [loaded, saved]) & 0xFF == 1
        result = [struct.unpack('>h', m.uc.mem_read(loaded + 20 + 2 * slot, 2))[0] >> 8
                  for slot in (4, 12)]
        destination_round_trips[destination] = result
        assert result == ([destination] * 2 if destination < 46 else [destination - 46] * 2)

    return {
        'device': dev.key, 'os': release.version,
        'stock_sha256': release.syx_sha256, 'main_sha256': release.main_sha256,
        'mode': 'bounded stock-routine calls; no full boot or feature validation',
        'instruction_limit_per_call': LIMIT,
        'unregistered_audio_slots': list(range(46, 53)),
        'serialized_parameter_words': len(save_map),
        'stock_save_ignores_candidate_slots': True,
        'stock_load_clears_candidate_slots': True,
        'saved_parameter_padding_bytes': 4,
        'native_resolved_locks': actual,
        'unlocked_step_has_no_locks': True,
        'native_engine_copies_all_53_words': True,
        'native_locks_update_targets_and_restore_base': True,
        'stock_refuses_parameter_id_164_and_slot_53': True,
        'full_resolved_list_stops_at_53_slots': True,
        'native_smoothing_carries_both_extra_slots_on_all_eight_tracks': True,
        'native_lfos_match_stock_destinations_on_all_eight_tracks': True,
        'lfo_destination_round_trips': destination_round_trips,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stock', type=Path, action='append', required=True)
    ap.add_argument('--emulator', type=Path, required=True,
                    help='existing digiemu checkout; does not install dependencies')
    ap.add_argument('--storage', action='store_true',
                    help='also build and check eight additional SRC parameters (needs cross compiler)')
    args = ap.parse_args()
    if not (args.emulator / 'emu' / 'harness.py').is_file():
        ap.error('--emulator must contain emu/harness.py')
    sys.path.insert(0, str(args.emulator.resolve()))
    try:
        from emu.harness import Machine, call
        from unicorn.m68k_const import UC_M68K_REG_PC
    except ImportError as e:
        ap.error('existing emulator dependencies must be importable: %s' % e)
    reports = [probe(path, Machine, call, UC_M68K_REG_PC) for path in args.stock]
    if args.storage:
        from digitakt_src_storage import probe_storage
        for path, report in zip(args.stock, reports):
            report['storage_prototype'] = probe_storage(path, Machine, call, UC_M68K_REG_PC)
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
